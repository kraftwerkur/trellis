"""LLM Gateway — providers, model routing, auth, budget, cost tracking, finops, chat endpoint.

Consolidates: gateway/providers/*, gateway/model_router, gateway/router, gateway/auth,
gateway/budget, gateway/cost_tracker, gateway/finops.
"""

import hashlib
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.database import get_db
from trellis.models import Agent, ApiKey, CostEvent, ModelRoute
from trellis.schemas import ChatCompletionRequest

logger = logging.getLogger("trellis.gateway")


# ── Provider interface ─────────────────────────────────────────────────────

class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat_completion(self, request_body: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def is_configured(self) -> bool: ...


class OpenAICompatibleProvider(LLMProvider):
    """One class for OpenAI, Groq, Google, Ollama, NVIDIA — they all speak the same protocol."""

    def __init__(self, name: str, env_key: str | None, base_url: str, *, always_available: bool = False):
        self.name = name
        self.api_key = os.environ.get(env_key, "") if env_key else ""
        self.base_url = base_url
        self._always_available = always_available

    def is_configured(self) -> bool:
        return self._always_available or bool(self.api_key)

    @property
    def available(self) -> bool:
        return self.is_configured()

    async def chat_completion(self, request_body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=request_body,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()


class AnthropicProvider(LLMProvider):
    """Anthropic uses its own messages API — needs format translation."""

    name = "anthropic"

    def __init__(self):
        self.api_key = os.environ.get("TRELLIS_ANTHROPIC_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def available(self) -> bool:
        return self.is_configured()

    async def chat_completion(self, request_body: dict[str, Any]) -> dict[str, Any]:
        messages = request_body.get("messages", [])
        system = None
        api_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m.get("content", "")
            else:
                api_messages.append({"role": m["role"], "content": m.get("content", "")})

        body: dict[str, Any] = {
            "model": request_body.get("model", "claude-sonnet-4-5-20250514"),
            "messages": api_messages,
            "max_tokens": request_body.get("max_tokens", 4096),
        }
        if system:
            body["system"] = system
        if request_body.get("temperature") is not None:
            body["temperature"] = request_body["temperature"]

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=body,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage = data.get("usage", {})
        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "created": 0,
            "model": data.get("model", ""),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": data.get("stop_reason", "stop")}],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }


# ── Provider registry ──────────────────────────────────────────────────────

_providers: dict[str, LLMProvider] = {
    "ollama": OpenAICompatibleProvider("ollama", None, os.environ.get("TRELLIS_OLLAMA_URL", "http://localhost:11434/v1"), always_available=True),
    "openai": OpenAICompatibleProvider("openai", "TRELLIS_OPENAI_API_KEY", "https://api.openai.com/v1"),
    "groq": OpenAICompatibleProvider("groq", "TRELLIS_GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "google": OpenAICompatibleProvider("google", "TRELLIS_GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "nvidia": OpenAICompatibleProvider("nvidia", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
    "anthropic": AnthropicProvider(),
}

# Also check TRELLIS_NVIDIA_API_KEY as fallback
if not _providers["nvidia"].api_key:
    _providers["nvidia"].api_key = os.environ.get("TRELLIS_NVIDIA_API_KEY", "")


# ── Model routing ──────────────────────────────────────────────────────────

MODEL_PROVIDER_MAP: dict[str, str] = {
    "gpt-4o": "openai", "gpt-4o-mini": "openai", "gpt-3.5-turbo": "openai",
    "claude-sonnet-4-5": "anthropic", "claude-3-haiku": "anthropic",
    "qwen3.5:9b": "ollama", "qwen3:8b": "ollama", "llama3.1:8b": "ollama",
    "llama-3.3-70b-versatile": "groq", "llama-3.1-8b-instant": "groq",
    "mixtral-8x7b-32768": "groq", "gemma2-9b-it": "groq",
    "gemini-2.5-flash": "google", "gemini-2.5-pro": "google", "gemini-2.0-flash": "google",
    "meta/llama-3.3-70b-instruct": "nvidia", "meta/llama-3.1-405b-instruct": "nvidia",
    "nvidia/llama-3.1-nemotron-70b-instruct": "nvidia",
    "mistralai/mistral-large-2-instruct": "nvidia", "deepseek-ai/deepseek-r1": "nvidia",
}

COMPLEXITY_MODEL_MAP: dict[str, str] = {"simple": "qwen3.5:9b", "medium": "gpt-4o", "complex": "claude-sonnet-4-5"}

_COMPLEX_KEYWORDS = re.compile(
    r"\b(analyze|analyse|compare|reason|reasoning|evaluate|synthesize|"
    r"multi-step|step.by.step|chain.of.thought|explain why|trade.?off|"
    r"pros and cons|critique|debate)\b",
    re.IGNORECASE,
)

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen3.5:9b"


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


def classify_complexity(request: ChatCompletionRequest) -> str:
    total_text = ""
    for msg in request.messages:
        if msg.content:
            total_text += msg.content
    est_tokens = _estimate_tokens(total_text)
    num_tools = len(request.tools) if request.tools else 0
    if est_tokens > 2000 or num_tools >= 3 or _COMPLEX_KEYWORDS.search(total_text):
        return "complex"
    if num_tools > 0 or est_tokens > 200:
        return "medium"
    return "simple"


async def _get_db_routes() -> dict[str, str]:
    try:
        from trellis.database import async_session
        async with async_session() as db:
            result = await db.execute(select(ModelRoute).where(ModelRoute.active.is_(True)))
            routes = result.scalars().all()
            if routes:
                return {r.model_name: r.provider for r in routes}
    except Exception:
        pass
    return {}


async def _get_agent_llm_config(agent_id: str) -> dict[str, Any] | None:
    try:
        from trellis.database import async_session
        async with async_session() as db:
            agent = await db.get(Agent, agent_id)
            if agent and agent.llm_config:
                return agent.llm_config
    except Exception:
        pass
    return None


def resolve_model_and_provider(
    requested_model: str | None,
    api_key: ApiKey,
    request: ChatCompletionRequest | None = None,
) -> tuple[str, LLMProvider, str | None]:
    """Synchronous resolve — legacy compatibility."""
    complexity_class: str | None = None
    if requested_model is None or requested_model == "auto":
        if request is not None:
            complexity_class = classify_complexity(request)
            model = COMPLEXITY_MODEL_MAP[complexity_class]
        else:
            model = api_key.default_model or DEFAULT_MODEL
    else:
        model = requested_model

    if api_key.preferred_provider and api_key.preferred_provider in _providers:
        provider_name = api_key.preferred_provider
    elif model in MODEL_PROVIDER_MAP:
        provider_name = MODEL_PROVIDER_MAP[model]
    else:
        provider_name = DEFAULT_PROVIDER

    provider = _providers[provider_name]
    if not provider.is_configured():
        provider = _providers["ollama"]
        if model in MODEL_PROVIDER_MAP and MODEL_PROVIDER_MAP[model] != "ollama":
            model = DEFAULT_MODEL

    return model, provider, complexity_class


async def resolve_model_and_provider_async(
    requested_model: str | None,
    api_key: ApiKey,
    request: ChatCompletionRequest | None = None,
) -> tuple[str, LLMProvider, str | None]:
    complexity_class: str | None = None
    agent_config = await _get_agent_llm_config(api_key.agent_id)

    if requested_model is None or requested_model == "auto":
        if agent_config and agent_config.get("model"):
            model = agent_config["model"]
        elif request is not None:
            complexity_class = classify_complexity(request)
            model = COMPLEXITY_MODEL_MAP[complexity_class]
        else:
            model = api_key.default_model or DEFAULT_MODEL
    else:
        model = requested_model

    if agent_config and agent_config.get("allowed_models"):
        allowed = agent_config["allowed_models"]
        if model not in allowed:
            model = agent_config.get("model") or allowed[0]

    provider_name: str | None = None
    if agent_config and agent_config.get("preferred_provider"):
        pref = agent_config["preferred_provider"]
        if pref in _providers:
            provider_name = pref

    if not provider_name:
        db_routes = await _get_db_routes()
        if model in db_routes:
            provider_name = db_routes[model]

    if not provider_name:
        if api_key.preferred_provider and api_key.preferred_provider in _providers:
            provider_name = api_key.preferred_provider
        elif model in MODEL_PROVIDER_MAP:
            provider_name = MODEL_PROVIDER_MAP[model]
        else:
            provider_name = DEFAULT_PROVIDER

    provider = _providers[provider_name]
    if not provider.is_configured():
        provider = _providers["ollama"]
        if model in MODEL_PROVIDER_MAP and MODEL_PROVIDER_MAP[model] != "ollama":
            model = DEFAULT_MODEL

    return model, provider, complexity_class


# ── Auth ───────────────────────────────────────────────────────────────────

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def authenticate_agent(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    raw_key = auth[7:]
    key_hash = hash_key(raw_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()
    if api_key is None or not api_key.active:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    await db.execute(update(ApiKey).where(ApiKey.id == api_key.id).values(last_used=datetime.now(timezone.utc)))
    await db.commit()
    await db.refresh(api_key)
    return api_key


# ── Budget ─────────────────────────────────────────────────────────────────

BUDGET_WARNING_THRESHOLD = 0.8


async def _get_daily_spend(db: AsyncSession, agent_id: str) -> float:
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(CostEvent.cost_usd), 0.0)).where(
            CostEvent.agent_id == agent_id, CostEvent.timestamp >= start_of_day,
        )
    )
    return result.scalar()


async def _get_monthly_spend(db: AsyncSession, agent_id: str) -> float:
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(CostEvent.cost_usd), 0.0)).where(
            CostEvent.agent_id == agent_id, CostEvent.timestamp >= start_of_month,
        )
    )
    return result.scalar()


async def check_budget(db: AsyncSession, api_key: ApiKey) -> str | None:
    if api_key.budget_daily_usd is not None:
        daily_spend = await _get_daily_spend(db, api_key.agent_id)
        if daily_spend >= api_key.budget_daily_usd:
            return f"Daily budget exceeded: ${daily_spend:.4f} >= ${api_key.budget_daily_usd:.4f}"
    if api_key.budget_monthly_usd is not None:
        monthly_spend = await _get_monthly_spend(db, api_key.agent_id)
        if monthly_spend >= api_key.budget_monthly_usd:
            return f"Monthly budget exceeded: ${monthly_spend:.4f} >= ${api_key.budget_monthly_usd:.4f}"
    return None


async def check_budget_alerts(db: AsyncSession, api_key: ApiKey) -> None:
    from trellis.router import emit_audit
    from trellis.alerts import fire_alert
    if api_key.budget_daily_usd is not None:
        daily_spend = await _get_daily_spend(db, api_key.agent_id)
        ratio = daily_spend / api_key.budget_daily_usd
        if ratio >= BUDGET_WARNING_THRESHOLD:
            try:
                await fire_alert("finops", "budget_pct", ratio * 100,
                                 agent_id=api_key.agent_id,
                                 details={"period": "daily", "spend": round(daily_spend, 6),
                                          "budget": api_key.budget_daily_usd})
            except Exception:
                pass
        if BUDGET_WARNING_THRESHOLD <= ratio < 1.0:
            await emit_audit(db, "budget_warning", agent_id=api_key.agent_id, details={
                "period": "daily", "spend": round(daily_spend, 6),
                "budget": api_key.budget_daily_usd, "ratio": round(ratio, 4),
            })
    if api_key.budget_monthly_usd is not None:
        monthly_spend = await _get_monthly_spend(db, api_key.agent_id)
        ratio = monthly_spend / api_key.budget_monthly_usd
        if ratio >= BUDGET_WARNING_THRESHOLD:
            try:
                await fire_alert("finops", "budget_pct", ratio * 100,
                                 agent_id=api_key.agent_id,
                                 details={"period": "monthly", "spend": round(monthly_spend, 6),
                                          "budget": api_key.budget_monthly_usd})
            except Exception:
                pass
        if BUDGET_WARNING_THRESHOLD <= ratio < 1.0:
            await emit_audit(db, "budget_warning", agent_id=api_key.agent_id, details={
                "period": "monthly", "spend": round(monthly_spend, 6),
                "budget": api_key.budget_monthly_usd, "ratio": round(ratio, 4),
            })


# ── Cost tracking ──────────────────────────────────────────────────────────

MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "meta/llama-3.3-70b-instruct": {"input": 0.40, "output": 0.40},
    "meta/llama-3.1-405b-instruct": {"input": 2.00, "output": 2.00},
    "nvidia/llama-3.1-nemotron-70b-instruct": {"input": 0.40, "output": 0.40},
    "mistralai/mistral-large-2-instruct": {"input": 2.00, "output": 6.00},
    "deepseek-ai/deepseek-r1": {"input": 0.55, "output": 2.19},
    "qwen3.5:9b": {"input": 0.0, "output": 0.0},
    "qwen3:8b": {"input": 0.0, "output": 0.0},
    "llama3.1:8b": {"input": 0.0, "output": 0.0},
}


def calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
    cost = (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000
    return round(cost, 8)


async def log_cost_event(
    db: AsyncSession, *, agent_id: str, trace_id: str | None,
    model_requested: str, model_used: str, provider: str,
    tokens_in: int, tokens_out: int, latency_ms: int,
    has_tool_calls: bool, complexity_class: str | None = None,
) -> CostEvent:
    cost = calculate_cost(model_used, tokens_in, tokens_out)
    event = CostEvent(
        trace_id=trace_id, agent_id=agent_id, model_requested=model_requested,
        model_used=model_used, provider=provider, tokens_in=tokens_in,
        tokens_out=tokens_out, cost_usd=cost, latency_ms=latency_ms,
        has_tool_calls=has_tool_calls, complexity_class=complexity_class,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


# ── FinOps anomaly detection ───────────────────────────────────────────────

ANOMALY_MULTIPLIER = 3.0
ANOMALY_LOOKBACK_DAYS = 7
ANOMALY_MIN_REQUESTS = 5


async def check_cost_anomaly(db: AsyncSession, agent_id: str, current_cost: float) -> bool:
    if current_cost <= 0:
        return False
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=ANOMALY_LOOKBACK_DAYS)
    result = await db.execute(
        select(func.avg(CostEvent.cost_usd).label("avg_cost"), func.count(CostEvent.id).label("cnt"))
        .where(CostEvent.agent_id == agent_id, CostEvent.timestamp >= lookback)
    )
    row = result.one()
    if row.avg_cost is None or row.cnt < ANOMALY_MIN_REQUESTS or row.avg_cost <= 0:
        return False
    if current_cost > row.avg_cost * ANOMALY_MULTIPLIER:
        from trellis.router import emit_audit
        await emit_audit(db, "cost_anomaly", agent_id=agent_id, details={
            "current_cost": round(current_cost, 8), "avg_cost_7d": round(float(row.avg_cost), 8),
            "multiplier": round(current_cost / float(row.avg_cost), 2), "historical_requests": row.cnt,
        })
        return True
    return False


# ── Chat completions endpoint ──────────────────────────────────────────────

router = APIRouter(tags=["gateway"])


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: ApiKey = Depends(authenticate_agent),
    db: AsyncSession = Depends(get_db),
):
    from trellis.router import emit_audit

    budget_msg = await check_budget(db, api_key)
    if budget_msg:
        await emit_audit(db, "budget_exceeded", agent_id=api_key.agent_id, details={"message": budget_msg})
        await db.commit()
        raise HTTPException(status_code=429, detail=budget_msg)

    model, provider, complexity_class = await resolve_model_and_provider_async(request.model, api_key, request)

    # ── PHI Shield ──────────────────────────────────────────────────────
    from trellis.phi_shield import shield_request, shield_response
    phi_mode = "off"
    try:
        agent = await db.get(Agent, api_key.agent_id)
        if agent:
            phi_mode = agent.phi_shield_mode or "off"
    except Exception:
        pass

    raw_messages = [m.model_dump(exclude_none=True) for m in request.messages]
    shielded_messages, phi_vault, phi_detections = await shield_request(
        raw_messages, api_key.agent_id, phi_mode, db=db)

    body: dict = {
        "model": model,
        "messages": shielded_messages,
    }
    if request.tools:
        body["tools"] = [t.model_dump() for t in request.tools]
    if request.tool_choice is not None:
        body["tool_choice"] = request.tool_choice
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        body["top_p"] = request.top_p
    body["stream"] = False

    start = time.monotonic()
    try:
        result = await provider.chat_completion(body)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        # Record error in observatory
        from trellis.observatory import record_llm_error
        await record_llm_error(
            db,
            agent_id=api_key.agent_id,
            model_requested=request.model or model,
            model_used=model,
            provider=provider.name,
            error_type=type(e).__name__,
            latency_ms=latency_ms,
        )
        raise HTTPException(status_code=502, detail=f"Provider error: {e}")
    latency_ms = int((time.monotonic() - start) * 1000)

    # ── PHI Shield rehydrate ──────────────────────────────────────────
    result = shield_response(result, phi_vault, phi_mode)

    usage = result.get("usage", {})
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)

    has_tool_calls = any(
        choice.get("message", {}).get("tool_calls") for choice in result.get("choices", [])
    )

    audit_details = {
        "model_requested": request.model or model, "model_used": model,
        "provider": provider.name, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "latency_ms": latency_ms, "has_tool_calls": has_tool_calls,
    }
    if complexity_class:
        audit_details["complexity_class"] = complexity_class
    await emit_audit(db, "llm_inference", agent_id=api_key.agent_id, details=audit_details)

    event = await log_cost_event(
        db, agent_id=api_key.agent_id, trace_id=None,
        model_requested=request.model or model, model_used=model,
        provider=provider.name, tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=latency_ms, has_tool_calls=has_tool_calls, complexity_class=complexity_class,
    )

    await check_budget_alerts(db, api_key)
    await check_cost_anomaly(db, api_key.agent_id, event.cost_usd)

    response = JSONResponse(content=result)
    response.headers["X-Trellis-Cost-USD"] = str(event.cost_usd)
    if complexity_class:
        response.headers["X-Trellis-Complexity"] = complexity_class
    return response
