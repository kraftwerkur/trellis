"""Event routing: rule engine, dispatcher, audit emission.

Consolidates: core/rule_engine, core/event_router, core/dispatcher, core/audit.
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.config import settings
from trellis.models import Agent, AuditEvent, EnvelopeLog, Rule
from trellis.schemas import Envelope

logger = logging.getLogger("trellis.router")

# Module-level client override for testing (allows httpx.AsyncClient injection)
_client_override: httpx.AsyncClient | None = None


def set_client_override(client: httpx.AsyncClient | None) -> None:
    global _client_override
    _client_override = client


# ── Audit ──────────────────────────────────────────────────────────────────

async def emit_audit(
    db: AsyncSession, event_type: str, *,
    trace_id: str | None = None, envelope_id: str | None = None,
    agent_id: str | None = None, details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        trace_id=trace_id, envelope_id=envelope_id, agent_id=agent_id,
        event_type=event_type, details=details or {},
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


# ── Rule engine ────────────────────────────────────────────────────────────

_SENTINEL = object()


def _resolve_field(data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return _SENTINEL
            current = current[part]
        else:
            try:
                val = getattr(current, part, _SENTINEL)
                if val is _SENTINEL:
                    return _SENTINEL
                current = val
            except Exception:
                return _SENTINEL
    return current


def _match_condition(value: Any, condition: Any) -> bool:
    if isinstance(condition, dict):
        for op, operand in condition.items():
            if op == "$in":
                if value is _SENTINEL or value not in operand:
                    return False
            elif op == "$gt":
                if value is _SENTINEL or not (value > operand):
                    return False
            elif op == "$gte":
                if value is _SENTINEL or not (value >= operand):
                    return False
            elif op == "$lt":
                if value is _SENTINEL or not (value < operand):
                    return False
            elif op == "$lte":
                if value is _SENTINEL or not (value <= operand):
                    return False
            elif op == "$exists":
                if (value is not _SENTINEL) != operand:
                    return False
            elif op == "$regex":
                if value is _SENTINEL or not isinstance(value, str) or not re.search(operand, value):
                    return False
            elif op == "$not":
                if _match_condition(value, operand):
                    return False
            elif op == "$contains":
                if value is _SENTINEL or not isinstance(value, str) or operand not in value:
                    return False
            else:
                return False
        return True
    if value is _SENTINEL:
        return False
    return value == condition


def _rule_matches(envelope_dict: dict[str, Any], rule: Rule) -> bool:
    return all(
        _match_condition(_resolve_field(envelope_dict, field), cond)
        for field, cond in rule.conditions.items()
    )


def match_envelope(envelope: Envelope, rules: list[Rule]) -> Rule | None:
    envelope_dict = envelope.model_dump()
    for rule in sorted(rules, key=lambda r: r.priority):
        if rule.active and _rule_matches(envelope_dict, rule):
            return rule
    return None


def match_envelope_all(envelope: Envelope, rules: list[Rule]) -> list[Rule]:
    envelope_dict = envelope.model_dump()
    matched: list[Rule] = []
    first_match_found = False
    for rule in sorted(rules, key=lambda r: r.priority):
        if not rule.active:
            continue
        if _rule_matches(envelope_dict, rule):
            if rule.fan_out:
                matched.append(rule)
            elif not first_match_found:
                matched.append(rule)
                first_match_found = True
    return matched


# ── Dispatch ───────────────────────────────────────────────────────────────

async def dispatch_http(
    endpoint: str, envelope: Envelope
) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        if _client_override is not None:
            resp = await _client_override.post(endpoint, json=envelope.model_dump())
            resp.raise_for_status()
            return "success", resp.json(), None
        async with httpx.AsyncClient(timeout=settings.dispatch_timeout) as client:
            resp = await client.post(endpoint, json=envelope.model_dump())
            resp.raise_for_status()
            return "success", resp.json(), None
    except httpx.TimeoutException:
        return "timeout", None, "Agent did not respond within timeout"
    except httpx.HTTPStatusError as e:
        return "error", None, f"Agent returned {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        return "error", None, f"Dispatch failed: {str(e)[:500]}"


async def dispatch_function(
    function_ref: str, envelope: Envelope
) -> tuple[str, dict[str, Any] | None, str | None]:
    from trellis.functions import get_function
    fn = get_function(function_ref)
    if fn is None:
        return "error", None, f"Function '{function_ref}' not found in registry"
    try:
        result = await fn(envelope.model_dump())
        return "success", result, None
    except Exception as e:
        return "error", None, f"Function agent error: {str(e)[:500]}"


async def dispatch_llm(
    llm_config: dict, envelope: Envelope, agent_id: str | None = None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Run an LLM agent through gateway routing. Agents never touch real API keys."""
    from trellis.gateway import MODEL_PROVIDER_MAP, _providers

    text = envelope.payload.text or "(no text)"
    system_prompt = llm_config.get("system_prompt", "You are a helpful assistant.")
    model = llm_config.get("model", "qwen3.5:9b")
    temperature = llm_config.get("temperature", 0.7)
    max_tokens = llm_config.get("max_tokens", 1024)

    body = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
        "temperature": temperature, "max_tokens": max_tokens, "stream": False,
    }

    try:
        provider_name = MODEL_PROVIDER_MAP.get(model, "nvidia")
        provider = _providers.get(provider_name)
        configured = getattr(provider, 'available', getattr(provider, 'is_configured', lambda: False))
        if not provider or not (configured() if callable(configured) else configured):
            provider = _providers.get("ollama")
            if not provider:
                return "error", None, "No LLM provider available"

        start = time.monotonic()
        result = await provider.chat_completion(body)
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = result.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        prov_name = getattr(provider, "name", provider_name)

        choices = result.get("choices", [])
        msg = choices[0].get("message", {}) if choices else {}
        response_text = msg.get("content", "") or msg.get("reasoning", "") or ""

        return "success", {
            "status": "completed",
            "result": {
                "text": response_text,
                "data": {
                    "model": model, "model_requested": model, "provider": prov_name,
                    "usage": usage, "tokens_in": tokens_in, "tokens_out": tokens_out,
                    "cost_usd": "0.0", "latency_ms": latency_ms,
                    "complexity_class": None, "routed_via": "trellis-gateway",
                },
                "attachments": [],
            },
        }, None
    except Exception as e:
        return "error", None, f"LLM dispatch failed: {str(e)[:500]}"


async def _dispatch_by_type(agent: Agent, envelope: Envelope):
    if agent.agent_type in ("http", "webhook"):
        if not agent.endpoint:
            return "error", None, f"Agent '{agent.agent_id}' has no endpoint"
        return await dispatch_http(agent.endpoint, envelope)
    elif agent.agent_type == "function":
        if not agent.function_ref:
            return "error", None, f"Agent '{agent.agent_id}' has no function_ref"
        return await dispatch_function(agent.function_ref, envelope)
    elif agent.agent_type == "llm":
        if not agent.llm_config:
            return "error", None, f"Agent '{agent.agent_id}' has no llm_config"
        return await dispatch_llm(agent.llm_config, envelope, agent_id=agent.agent_id)
    elif agent.agent_type == "native":
        from trellis.agents import dispatch_native_agent
        return await dispatch_native_agent(agent, envelope)
    else:
        return "error", None, f"Unknown agent type: {agent.agent_type}"


async def _maybe_send_email(dispatch_result: dict, rule: Rule, envelope: Envelope) -> None:
    """Fire email outputs based on rule on_complete config or global default. Never raises."""
    try:
        from trellis.outputs.email import send_email_output, _extract_priority
        priority = _extract_priority(dispatch_result) or (
            envelope.metadata.priority if hasattr(envelope.metadata, "priority") else None
        )

        on_complete = rule.actions.get("on_complete", [])
        if on_complete:
            for action in on_complete:
                if action.get("type") != "email":
                    continue
                conditions = action.get("conditions", {})
                priority_filter = conditions.get("priority")
                if priority_filter and priority not in priority_filter:
                    continue
                await send_email_output(dispatch_result, action)
        elif priority == "CRITICAL":
            default_email = os.environ.get("TRELLIS_DEFAULT_EMAIL")
            if default_email:
                await send_email_output(dispatch_result, {"to": default_email})
    except Exception as e:
        logger.warning(f"Post-dispatch email hook failed (non-fatal): {e}")


async def _dispatch_single(envelope: Envelope, matched_rule: Rule, db: AsyncSession) -> dict:
    target_agent_id = matched_rule.actions.get("route_to")

    await emit_audit(db, "rule_matched", trace_id=envelope.metadata.trace_id,
        envelope_id=envelope.envelope_id,
        details={"rule_id": matched_rule.id, "rule_name": matched_rule.name, "target_agent": target_agent_id})

    agent = await db.get(Agent, target_agent_id)
    if not agent:
        log = EnvelopeLog(
            envelope_id=envelope.envelope_id, trace_id=envelope.metadata.trace_id,
            source_type=envelope.source_type, envelope_data=envelope.model_dump(),
            matched_rule_id=str(matched_rule.id), matched_rule_name=matched_rule.name,
            target_agent_id=target_agent_id, dispatch_status="agent_not_found",
            error=f"Agent '{target_agent_id}' not found in registry",
        )
        db.add(log)
        await emit_audit(db, "error", trace_id=envelope.metadata.trace_id,
            envelope_id=envelope.envelope_id, agent_id=target_agent_id,
            details={"error": f"Agent '{target_agent_id}' not found"})
        return {"status": "agent_not_found", "error": f"Agent '{target_agent_id}' not found in registry",
                "envelope_id": envelope.envelope_id, "matched_rule": matched_rule.name, "target_agent": target_agent_id}

    await emit_audit(db, "agent_dispatched", trace_id=envelope.metadata.trace_id,
        envelope_id=envelope.envelope_id, agent_id=target_agent_id,
        details={"agent_type": agent.agent_type, "rule_name": matched_rule.name})

    # Commit pre-dispatch audit trail and release DB lock before potentially long LLM calls
    await db.commit()

    status, result_data, error = await _dispatch_by_type(agent, envelope)

    if error:
        await emit_audit(db, "error", trace_id=envelope.metadata.trace_id,
            envelope_id=envelope.envelope_id, agent_id=target_agent_id,
            details={"dispatch_status": status, "error": error})
    else:
        await emit_audit(db, "agent_responded", trace_id=envelope.metadata.trace_id,
            envelope_id=envelope.envelope_id, agent_id=target_agent_id,
            details={"dispatch_status": status})

        # Emit audit events for tool calls (native agent visibility)
        if result_data and isinstance(result_data, dict):
            tool_calls = (result_data.get("result") or {}).get("data", {}).get("tool_calls", [])
            for tc in tool_calls:
                await emit_audit(db, "tool_call", trace_id=envelope.metadata.trace_id,
                    envelope_id=envelope.envelope_id, agent_id=target_agent_id,
                    details={"tool": tc.get("tool"), "agent_type": agent.agent_type})

    log = EnvelopeLog(
        envelope_id=envelope.envelope_id, trace_id=envelope.metadata.trace_id,
        source_type=envelope.source_type, envelope_data=envelope.model_dump(),
        matched_rule_id=str(matched_rule.id), matched_rule_name=matched_rule.name,
        target_agent_id=target_agent_id, dispatch_status=status,
        dispatch_result=result_data, error=error,
    )
    db.add(log)

    dispatch_result = {"status": status, "envelope_id": envelope.envelope_id,
                       "matched_rule": matched_rule.name, "target_agent": target_agent_id,
                       "result": result_data, "error": error}

    # Post-dispatch: fire email outputs if conditions match (non-blocking)
    if status == "success" and result_data:
        task = asyncio.create_task(_maybe_send_email(dispatch_result, matched_rule, envelope))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

    return dispatch_result


async def _log_gateway_cost(dispatch_result: dict, db: AsyncSession) -> None:
    try:
        result_data = dispatch_result.get("result")
        if not result_data:
            return
        inner = result_data.get("result", {}).get("data", {})
        if inner.get("routed_via") != "trellis-gateway":
            return
        agent_id = dispatch_result.get("target_agent")
        if not agent_id:
            return

        from trellis.gateway import log_cost_event
        await log_cost_event(
            db, agent_id=agent_id, trace_id=None,
            model_requested=inner.get("model_requested", inner.get("model", "")),
            model_used=inner.get("model", ""), provider=inner.get("provider", "unknown"),
            tokens_in=inner.get("tokens_in", inner.get("usage", {}).get("prompt_tokens", 0)),
            tokens_out=inner.get("tokens_out", inner.get("usage", {}).get("completion_tokens", 0)),
            latency_ms=inner.get("latency_ms", 0), has_tool_calls=False,
            complexity_class=inner.get("complexity_class"),
        )
        await emit_audit(db, "llm_inference", agent_id=agent_id, details={
            "model_used": inner.get("model"), "provider": inner.get("provider"),
            "tokens_in": inner.get("tokens_in", 0), "tokens_out": inner.get("tokens_out", 0),
            "latency_ms": inner.get("latency_ms", 0),
        })
        await db.commit()
    except Exception as e:
        logger.warning(f"Post-dispatch cost logging failed: {e}")


async def route_envelope(envelope: Envelope, db: AsyncSession) -> dict:
    # ── Classification Engine (platform middleware — always runs) ──────────
    from trellis.classification import classify_envelope
    envelope = classify_envelope(envelope)
    # ──────────────────────────────────────────────────────────────────────

    await emit_audit(db, "envelope_received", trace_id=envelope.metadata.trace_id,
        envelope_id=envelope.envelope_id,
        details={"source_type": envelope.source_type, "source_id": envelope.source_id})

    result = await db.execute(select(Rule).where(Rule.active))
    rules = list(result.scalars().all())
    matched_rules = match_envelope_all(envelope, rules)

    if not matched_rules:
        log = EnvelopeLog(
            envelope_id=envelope.envelope_id, trace_id=envelope.metadata.trace_id,
            source_type=envelope.source_type, envelope_data=envelope.model_dump(),
            dispatch_status="no_match", error="No routing rule matched this envelope",
        )
        db.add(log)
        await db.commit()
        return {"status": "no_match", "error": "No routing rule matched this envelope",
                "envelope_id": envelope.envelope_id}

    if len(matched_rules) == 1:
        result = await _dispatch_single(envelope, matched_rules[0], db)
        await db.commit()
        await _log_gateway_cost(result, db)
        return result

    results = []
    for rule in matched_rules:
        r = await _dispatch_single(envelope, rule, db)
        results.append(r)
    await db.commit()
    for r in results:
        await _log_gateway_cost(r, db)
    return {"status": "fan_out", "envelope_id": envelope.envelope_id, "dispatches": results}
