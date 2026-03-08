"""All API endpoints — single file.

Consolidates: api/agents, api/audit, api/costs, api/finops, api/gateway,
api/health, api/keys, api/router, api/rules.
"""

import secrets
from datetime import datetime, timedelta, timezone

import httpx
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.adapters import build_envelope, build_hl7_envelope
from trellis.adapters.fhir_adapter import (
    build_fhir_envelope, build_fhir_bundle_envelopes,
    parse_fhir_subscription_notification, FHIRParseError,
)
from trellis.adapters.hl7_adapter import HL7ParseError
from trellis.database import get_db
from trellis.gateway import (
    MODEL_PROVIDER_MAP, _providers, hash_key, log_cost_event,
)
from trellis.models import Agent, ApiKey, AuditEvent, CostEvent, EnvelopeLog, ModelRoute, Rule
from trellis.router import emit_audit, match_envelope_all, route_envelope, set_client_override
import trellis.router as _router_mod
from trellis.schemas import (
    AgentCreate, AgentCreateResponse, AgentRead, AgentUpdate,
    ApiKeyCreate, ApiKeyCreated, ApiKeyRead,
    AuditEventRead,
    ChatCompletionRequest,
    CostEventRead, CostSummary,
    Envelope, EnvelopeLogRead, HttpAdapterInput,
    RuleCreate, RuleRead, RuleTestRequest, RuleTestResult, RuleUpdate,
)


logger = logging.getLogger("trellis.api")

# ── Health ─────────────────────────────────────────────────────────────────

health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "trellis"}


# ── Agents ─────────────────────────────────────────────────────────────────

agents_router = APIRouter(prefix="/agents", tags=["agents"])


def _generate_api_key() -> str:
    return "trl_" + secrets.token_urlsafe(32)


@agents_router.get("", response_model=list[AgentRead])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent))
    return result.scalars().all()


@agents_router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return agent


@agents_router.post("", response_model=AgentCreateResponse, status_code=201)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.get(Agent, data.agent_id)
    if existing:
        raise HTTPException(409, f"Agent '{data.agent_id}' already exists")

    dump = data.model_dump()
    if data.llm_config is not None:
        dump["llm_config"] = data.llm_config.model_dump()

    agent = Agent(**dump)
    db.add(agent)

    raw_key = _generate_api_key()
    api_key = ApiKey(
        key_hash=hash_key(raw_key), key_prefix=raw_key[:12],
        agent_id=data.agent_id, name=f"{data.agent_id}-auto",
    )
    db.add(api_key)

    await db.flush()
    await emit_audit(db, "agent_registered", agent_id=data.agent_id, details={
        "name": data.name, "agent_type": data.agent_type, "department": data.department})
    await emit_audit(db, "key_created", agent_id=data.agent_id, details={
        "key_prefix": raw_key[:12], "name": f"{data.agent_id}-auto"})
    await db.commit()
    await db.refresh(agent)

    resp = AgentCreateResponse.model_validate(agent)
    resp.api_key = raw_key
    return resp


@agents_router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: str, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return agent


@agents_router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    # BUG FIX: was "agent_registered", now correctly "agent_deleted"
    await emit_audit(db, "agent_deleted", agent_id=agent_id, details={
        "action": "deleted", "name": agent.name})
    await db.delete(agent)
    await db.commit()


@agents_router.post("/{agent_id}/sync", response_model=AgentRead)
async def sync_agent_manifest(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if agent.agent_type != "http":
        raise HTTPException(400, "Manifest sync only supported for http agents")
    if not agent.endpoint:
        raise HTTPException(400, "Agent has no endpoint configured")

    base = agent.endpoint.rsplit("/", 1)[0] if "/" in agent.endpoint else agent.endpoint
    manifest_url = f"{base}/manifest"

    try:
        if _router_mod._client_override is not None:
            resp = await _router_mod._client_override.get(manifest_url)
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(manifest_url)
        resp.raise_for_status()
        manifest = resp.json()
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch manifest: {e}")

    for field in ("name", "tools", "channels", "maturity", "framework", "department"):
        if field in manifest:
            setattr(agent, field, manifest[field])

    await db.commit()
    await db.refresh(agent)
    return agent


# ── Rules ──────────────────────────────────────────────────────────────────

rules_router = APIRouter(prefix="/rules", tags=["rules"])


@rules_router.get("", response_model=list[RuleRead])
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).order_by(Rule.priority))
    return result.scalars().all()


@rules_router.get("/{rule_id}", response_model=RuleRead)
async def get_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@rules_router.post("", response_model=RuleRead, status_code=201)
async def create_rule(data: RuleCreate, db: AsyncSession = Depends(get_db)):
    rule = Rule(**data.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    await emit_audit(db, "rule_changed", details={
        "action": "created", "rule_id": rule.id, "rule_name": rule.name})
    await db.commit()
    return rule


@rules_router.put("/{rule_id}", response_model=RuleRead)
async def update_rule(rule_id: int, data: RuleUpdate, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    await emit_audit(db, "rule_changed", details={
        "action": "updated", "rule_id": rule_id, "changes": changes})
    await db.commit()
    await db.refresh(rule)
    return rule


@rules_router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    await emit_audit(db, "rule_changed", details={
        "action": "deleted", "rule_id": rule_id, "rule_name": rule.name})
    await db.delete(rule)
    await db.commit()


@rules_router.put("/{rule_id}/toggle", response_model=RuleRead)
async def toggle_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    rule.active = not rule.active
    await emit_audit(db, "rule_changed", details={
        "action": "toggled", "rule_id": rule_id, "active": rule.active})
    await db.commit()
    await db.refresh(rule)
    return rule


@rules_router.post("/test", response_model=RuleTestResult)
async def test_rules(body: RuleTestRequest, db: AsyncSession = Depends(get_db)):
    envelope = Envelope(**body.envelope)
    result = await db.execute(select(Rule).where(Rule.active == True))
    rules = list(result.scalars().all())
    matched = match_envelope_all(envelope, rules)
    return RuleTestResult(matched_rules=[RuleRead.model_validate(r) for r in matched])


# ── Envelope routing ───────────────────────────────────────────────────────

event_router = APIRouter(tags=["routing"])


@event_router.post("/envelopes")
async def receive_envelope(envelope: Envelope, db: AsyncSession = Depends(get_db)):
    return await route_envelope(envelope, db)


@event_router.post("/adapter/http")
async def http_adapter(input_data: HttpAdapterInput, db: AsyncSession = Depends(get_db)):
    envelope = build_envelope(input_data)
    return await route_envelope(envelope, db)


@event_router.post("/adapter/hl7")
async def hl7_adapter(request: "Request", db: AsyncSession = Depends(get_db)):
    """Receive raw HL7v2 message (text/plain or text/hl7v2) and route it."""
    raw = (await request.body()).decode("utf-8", errors="replace")
    try:
        envelope = build_hl7_envelope(raw)
    except HL7ParseError as e:
        raise HTTPException(400, f"HL7 parse error: {e}")
    return await route_envelope(envelope, db)


@event_router.post("/adapter/fhir")
async def fhir_adapter(resource: dict, db: AsyncSession = Depends(get_db)):
    """Receive a FHIR R4 resource or Bundle and route it."""
    try:
        if resource.get("resourceType") == "Bundle":
            envelopes = build_fhir_bundle_envelopes(resource)
            if not envelopes:
                raise HTTPException(400, "No parseable resources in Bundle")
            results = []
            for env in envelopes:
                results.append(await route_envelope(env, db))
            return {"status": "ok", "envelopes_processed": len(results), "results": results}
        else:
            envelope = build_fhir_envelope(resource)
            return await route_envelope(envelope, db)
    except FHIRParseError as e:
        raise HTTPException(400, f"FHIR parse error: {e}")


@event_router.post("/adapter/fhir/subscription")
async def fhir_subscription_webhook(payload: dict, db: AsyncSession = Depends(get_db)):
    """Webhook for FHIR Subscription notifications (e.g., Epic)."""
    try:
        notification = parse_fhir_subscription_notification(payload)
    except FHIRParseError as e:
        raise HTTPException(400, f"Subscription parse error: {e}")

    resources = notification.get("resources", [])
    if not resources:
        return {"status": "ok", "message": "Notification received, no focus resources"}

    results = []
    for resource in resources:
        try:
            envelope = build_fhir_envelope(resource)
            results.append(await route_envelope(envelope, db))
        except (FHIRParseError, Exception) as e:
            logger.warning(f"Skipping subscription resource: {e}")

    return {
        "status": "ok",
        "subscription": notification.get("subscription_url", ""),
        "envelopes_processed": len(results),
        "results": results,
    }


@event_router.get("/envelopes", response_model=list[EnvelopeLogRead])
async def list_envelopes(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EnvelopeLog).order_by(EnvelopeLog.timestamp.desc()).limit(limit))
    return result.scalars().all()


# ── API Keys (no plaintext caching!) ──────────────────────────────────────

keys_router = APIRouter(prefix="/keys", tags=["keys"])


@keys_router.post("", status_code=201, response_model=ApiKeyCreated)
async def create_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    raw_key = _generate_api_key()
    key = ApiKey(
        key_hash=hash_key(raw_key), key_prefix=raw_key[:12],
        agent_id=body.agent_id, name=body.name,
        budget_daily_usd=body.budget_daily_usd, budget_monthly_usd=body.budget_monthly_usd,
        preferred_provider=body.preferred_provider, default_model=body.default_model,
    )
    db.add(key)
    await db.flush()
    await emit_audit(db, "key_created", agent_id=body.agent_id, details={
        "key_prefix": raw_key[:12], "name": body.name})
    await db.commit()
    await db.refresh(key)
    return ApiKeyCreated(id=key.id, key=raw_key, key_prefix=key.key_prefix,
                         agent_id=key.agent_id, name=key.name)


@keys_router.get("", response_model=list[ApiKeyRead])
async def list_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.active == True))
    return result.scalars().all()


@keys_router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key.active = False
    await emit_audit(db, "key_revoked", agent_id=key.agent_id, details={
        "key_id": key_id, "key_prefix": key.key_prefix})
    await db.commit()


# ── Audit ──────────────────────────────────────────────────────────────────

audit_router = APIRouter(prefix="/audit", tags=["audit"])


@audit_router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    event_type: str | None = Query(None), agent_id: str | None = Query(None),
    trace_id: str | None = Query(None), since: datetime | None = Query(None),
    until: datetime | None = Query(None), limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)
    if event_type: q = q.where(AuditEvent.event_type == event_type)
    if agent_id: q = q.where(AuditEvent.agent_id == agent_id)
    if trace_id: q = q.where(AuditEvent.trace_id == trace_id)
    if since: q = q.where(AuditEvent.timestamp >= since)
    if until: q = q.where(AuditEvent.timestamp <= until)
    result = await db.execute(q)
    return result.scalars().all()


@audit_router.get("/trace/{trace_id}", response_model=list[AuditEventRead])
async def get_trace_audit(trace_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AuditEvent).where(AuditEvent.trace_id == trace_id).order_by(AuditEvent.timestamp.asc()))
    return result.scalars().all()


# ── Costs ──────────────────────────────────────────────────────────────────

costs_router = APIRouter(prefix="/costs", tags=["costs"])


@costs_router.get("", response_model=list[CostEventRead])
async def list_costs(
    agent_id: str | None = Query(None), trace_id: str | None = Query(None),
    since: datetime | None = Query(None), until: datetime | None = Query(None),
    limit: int = Query(100, le=1000), db: AsyncSession = Depends(get_db),
):
    q = select(CostEvent).order_by(CostEvent.timestamp.desc()).limit(limit)
    if agent_id: q = q.where(CostEvent.agent_id == agent_id)
    if trace_id: q = q.where(CostEvent.trace_id == trace_id)
    if since: q = q.where(CostEvent.timestamp >= since)
    if until: q = q.where(CostEvent.timestamp <= until)
    result = await db.execute(q)
    return result.scalars().all()


@costs_router.get("/summary", response_model=list[CostSummary])
async def cost_summary(
    since: datetime | None = Query(None), until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(
        CostEvent.agent_id,
        func.sum(CostEvent.cost_usd).label("total_cost_usd"),
        func.sum(CostEvent.tokens_in).label("total_tokens_in"),
        func.sum(CostEvent.tokens_out).label("total_tokens_out"),
        func.count(CostEvent.id).label("request_count"),
    ).group_by(CostEvent.agent_id)
    if since: q = q.where(CostEvent.timestamp >= since)
    if until: q = q.where(CostEvent.timestamp <= until)
    result = await db.execute(q)
    return [CostSummary(agent_id=r.agent_id, total_cost_usd=r.total_cost_usd or 0.0,
            total_tokens_in=r.total_tokens_in or 0, total_tokens_out=r.total_tokens_out or 0,
            request_count=r.request_count) for r in result.all()]


@costs_router.get("/by-department")
async def costs_by_department(
    since: datetime | None = Query(None), until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = (select(Agent.department, func.sum(CostEvent.cost_usd).label("total_cost_usd"),
         func.sum(CostEvent.tokens_in).label("total_tokens_in"),
         func.sum(CostEvent.tokens_out).label("total_tokens_out"),
         func.count(CostEvent.id).label("request_count"))
         .join(Agent, CostEvent.agent_id == Agent.agent_id).group_by(Agent.department))
    if since: q = q.where(CostEvent.timestamp >= since)
    if until: q = q.where(CostEvent.timestamp <= until)
    result = await db.execute(q)
    return [{"department": r.department, "total_cost_usd": round(r.total_cost_usd or 0.0, 8),
             "total_tokens_in": r.total_tokens_in or 0, "total_tokens_out": r.total_tokens_out or 0,
             "request_count": r.request_count} for r in result.all()]


@costs_router.get("/by-department/{dept}")
async def costs_by_department_detail(
    dept: str, since: datetime | None = Query(None), until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = (select(CostEvent.agent_id, Agent.name.label("agent_name"),
         func.sum(CostEvent.cost_usd).label("total_cost_usd"),
         func.sum(CostEvent.tokens_in).label("total_tokens_in"),
         func.sum(CostEvent.tokens_out).label("total_tokens_out"),
         func.count(CostEvent.id).label("request_count"))
         .join(Agent, CostEvent.agent_id == Agent.agent_id)
         .where(Agent.department == dept).group_by(CostEvent.agent_id, Agent.name))
    if since: q = q.where(CostEvent.timestamp >= since)
    if until: q = q.where(CostEvent.timestamp <= until)
    result = await db.execute(q)
    agents = [{"agent_id": r.agent_id, "agent_name": r.agent_name,
               "total_cost_usd": round(r.total_cost_usd or 0.0, 8),
               "total_tokens_in": r.total_tokens_in or 0, "total_tokens_out": r.total_tokens_out or 0,
               "request_count": r.request_count} for r in result.all()]
    total = sum(a["total_cost_usd"] for a in agents)
    return {"department": dept, "total_cost_usd": round(total, 8), "agents": agents}


@costs_router.get("/trace/{trace_id}")
async def costs_by_trace(trace_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CostEvent).where(CostEvent.trace_id == trace_id).order_by(CostEvent.timestamp.asc()))
    events = result.scalars().all()
    total_cost = sum(e.cost_usd for e in events)
    total_tokens_in = sum(e.tokens_in for e in events)
    total_tokens_out = sum(e.tokens_out for e in events)
    agent_costs: dict[str, dict] = {}
    for e in events:
        if e.agent_id not in agent_costs:
            agent_costs[e.agent_id] = {"agent_id": e.agent_id, "total_cost_usd": 0.0,
                                        "tokens_in": 0, "tokens_out": 0, "request_count": 0}
        ac = agent_costs[e.agent_id]
        ac["total_cost_usd"] += e.cost_usd
        ac["tokens_in"] += e.tokens_in
        ac["tokens_out"] += e.tokens_out
        ac["request_count"] += 1
    return {"trace_id": trace_id, "total_cost_usd": round(total_cost, 8),
            "total_tokens_in": total_tokens_in, "total_tokens_out": total_tokens_out,
            "event_count": len(events), "agents": list(agent_costs.values())}


@costs_router.get("/timeseries")
async def cost_timeseries(
    agent_id: str | None = Query(None),
    granularity: str = Query("day", pattern="^(hour|day|week)$"),
    since: datetime | None = Query(None), until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if granularity == "hour":
        bucket_expr = func.strftime("%Y-%m-%d %H:00:00", CostEvent.timestamp)
    elif granularity == "week":
        bucket_expr = func.strftime("%Y-W%W", CostEvent.timestamp)
    else:
        bucket_expr = func.strftime("%Y-%m-%d", CostEvent.timestamp)

    q = (select(bucket_expr.label("bucket"), func.sum(CostEvent.cost_usd).label("total_cost_usd"),
         func.sum(CostEvent.tokens_in).label("total_tokens_in"),
         func.sum(CostEvent.tokens_out).label("total_tokens_out"),
         func.count(CostEvent.id).label("request_count"))
         .group_by(bucket_expr).order_by(bucket_expr))
    if agent_id: q = q.where(CostEvent.agent_id == agent_id)
    if since: q = q.where(CostEvent.timestamp >= since)
    if until: q = q.where(CostEvent.timestamp <= until)
    result = await db.execute(q)
    return [{"bucket": r.bucket, "total_cost_usd": round(r.total_cost_usd or 0.0, 8),
             "total_tokens_in": r.total_tokens_in or 0, "total_tokens_out": r.total_tokens_out or 0,
             "request_count": r.request_count} for r in result.all()]


# ── FinOps ─────────────────────────────────────────────────────────────────

finops_router = APIRouter(prefix="/finops", tags=["finops"])


@finops_router.get("/summary")
async def finops_summary(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def _spend_since(since: datetime) -> tuple[float, int]:
        result = await db.execute(
            select(func.coalesce(func.sum(CostEvent.cost_usd), 0.0), func.count(CostEvent.id))
            .where(CostEvent.timestamp >= since))
        row = result.one()
        return float(row[0]), int(row[1])

    spend_today, requests_today = await _spend_since(start_of_day)
    spend_week, requests_week = await _spend_since(start_of_week)
    spend_month, requests_month = await _spend_since(start_of_month)

    total_res = await db.execute(
        select(func.count(CostEvent.id), func.coalesce(func.sum(CostEvent.cost_usd), 0.0)))
    total_row = total_res.one()
    total_requests = int(total_row[0])
    total_cost = float(total_row[1])
    avg_cost = round(total_cost / total_requests, 8) if total_requests > 0 else 0.0

    top_agents_res = await db.execute(
        select(CostEvent.agent_id, func.sum(CostEvent.cost_usd).label("total_cost"),
               func.count(CostEvent.id).label("requests"))
        .group_by(CostEvent.agent_id).order_by(func.sum(CostEvent.cost_usd).desc()).limit(5))
    top_agents = [{"agent_id": r.agent_id, "total_cost_usd": round(float(r.total_cost), 8),
                   "requests": r.requests} for r in top_agents_res.all()]

    top_depts_res = await db.execute(
        select(Agent.department, func.sum(CostEvent.cost_usd).label("total_cost"),
               func.count(CostEvent.id).label("requests"))
        .join(Agent, CostEvent.agent_id == Agent.agent_id)
        .group_by(Agent.department).order_by(func.sum(CostEvent.cost_usd).desc()).limit(3))
    top_departments = [{"department": r.department, "total_cost_usd": round(float(r.total_cost), 8),
                        "requests": r.requests} for r in top_depts_res.all()]

    return {
        "spend_today_usd": round(spend_today, 8), "spend_this_week_usd": round(spend_week, 8),
        "spend_this_month_usd": round(spend_month, 8), "total_requests": total_requests,
        "avg_cost_per_request_usd": avg_cost, "top_agents": top_agents, "top_departments": top_departments,
    }


# ── Gateway management ────────────────────────────────────────────────────

gateway_mgmt_router = APIRouter(prefix="/gateway", tags=["gateway"])

PROVIDER_META = {
    "ollama": {"display_name": "Ollama (Local)"}, "groq": {"display_name": "Groq"},
    "openai": {"display_name": "OpenAI"}, "anthropic": {"display_name": "Anthropic"},
}


class ProviderInfo(BaseModel):
    name: str; display_name: str; configured: bool; base_url: str | None = None; models: list[str]

class ModelInfo(BaseModel):
    model: str; provider: str; available: bool

class GatewayStats(BaseModel):
    total_requests: int; total_tokens: int; total_cost: float
    requests_by_provider: dict[str, int]; avg_tokens_per_request: float

class ModelRouteRead(BaseModel):
    id: int; model_name: str; provider: str; cost_per_1k_input: float
    cost_per_1k_output: float; active: bool
    model_config = {"from_attributes": True}

class ModelRouteCreate(BaseModel):
    model_name: str; provider: str; cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0; active: bool = True

class ModelRouteUpdate(BaseModel):
    provider: str | None = None; cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None; active: bool | None = None

class LLMConfigSchema(BaseModel):
    model: str | None = None; system_prompt: str | None = None
    temperature: float | None = None; max_tokens: int | None = None
    allowed_models: list[str] | None = None; preferred_provider: str | None = None


@gateway_mgmt_router.get("/providers", response_model=list[ProviderInfo])
async def list_providers():
    provider_models: dict[str, list[str]] = {}
    for model, prov in MODEL_PROVIDER_MAP.items():
        provider_models.setdefault(prov, []).append(model)
    result = []
    for name, provider in _providers.items():
        meta = PROVIDER_META.get(name, {})
        base_url = getattr(provider, "base_url", None)
        result.append(ProviderInfo(name=name, display_name=meta.get("display_name", name),
            configured=provider.is_configured(), base_url=base_url,
            models=provider_models.get(name, [])))
    return result


@gateway_mgmt_router.get("/models", response_model=list[ModelInfo])
async def list_models():
    return [ModelInfo(model=model, provider=prov_name,
            available=_providers[prov_name].is_configured() if prov_name in _providers else False)
            for model, prov_name in MODEL_PROVIDER_MAP.items()]


@gateway_mgmt_router.get("/stats", response_model=GatewayStats)
async def gateway_stats(db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(
        func.count(CostEvent.id), func.coalesce(func.sum(CostEvent.tokens_in + CostEvent.tokens_out), 0),
        func.coalesce(func.sum(CostEvent.cost_usd), 0.0)))).one()
    total_requests, total_tokens, total_cost = int(row[0]), int(row[1]), float(row[2])
    rows = (await db.execute(
        select(CostEvent.provider, func.count(CostEvent.id)).group_by(CostEvent.provider))).all()
    requests_by_provider = {r[0]: int(r[1]) for r in rows}
    return GatewayStats(total_requests=total_requests, total_tokens=total_tokens,
        total_cost=round(total_cost, 6), requests_by_provider=requests_by_provider,
        avg_tokens_per_request=round(total_tokens / total_requests, 1) if total_requests else 0.0)


@gateway_mgmt_router.get("/routes", response_model=list[ModelRouteRead])
async def list_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelRoute).order_by(ModelRoute.model_name))
    return result.scalars().all()


@gateway_mgmt_router.post("/routes", response_model=ModelRouteRead, status_code=201)
async def create_route(data: ModelRouteCreate, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(
        select(ModelRoute).where(ModelRoute.model_name == data.model_name))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Route for '{data.model_name}' already exists")
    route = ModelRoute(**data.model_dump())
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return route


@gateway_mgmt_router.put("/routes/{model_name}", response_model=ModelRouteRead)
async def update_route(model_name: str, data: ModelRouteUpdate, db: AsyncSession = Depends(get_db)):
    route = (await db.execute(
        select(ModelRoute).where(ModelRoute.model_name == model_name))).scalar_one_or_none()
    if not route:
        raise HTTPException(404, f"Route for '{model_name}' not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(route, field, value)
    await db.commit()
    await db.refresh(route)
    return route


@gateway_mgmt_router.delete("/routes/{model_name}", status_code=204)
async def delete_route(model_name: str, db: AsyncSession = Depends(get_db)):
    route = (await db.execute(
        select(ModelRoute).where(ModelRoute.model_name == model_name))).scalar_one_or_none()
    if not route:
        raise HTTPException(404, f"Route for '{model_name}' not found")
    await db.delete(route)
    await db.commit()


@gateway_mgmt_router.get("/agents/{agent_id}/llm-config", response_model=LLMConfigSchema)
async def get_agent_llm_config(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return LLMConfigSchema(**(agent.llm_config or {}))


@gateway_mgmt_router.put("/agents/{agent_id}/llm-config", response_model=LLMConfigSchema)
async def update_agent_llm_config(agent_id: str, data: LLMConfigSchema, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    agent.llm_config = data.model_dump(exclude_unset=True)
    await db.commit()
    await db.refresh(agent)
    return LLMConfigSchema(**(agent.llm_config or {}))


# ── Seed default routes ───────────────────────────────────────────────────

# ── PHI Shield ─────────────────────────────────────────────────────────

phi_router = APIRouter(prefix="/phi", tags=["phi"])


class PhiTestRequest(BaseModel):
    text: str


class PhiDetectionResult(BaseModel):
    type: str
    text: str
    start: int
    end: int
    source: str = "regex"
    score: float = 1.0


class PhiTestResponse(BaseModel):
    redacted: str
    detections: list[PhiDetectionResult]


class PhiModeUpdate(BaseModel):
    phi_shield_mode: str  # full | redact_only | audit_only | off


@phi_router.get("/agents")
async def phi_agent_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent))
    agents = result.scalars().all()
    return [{"agent_id": a.agent_id, "name": a.name,
             "phi_shield_mode": a.phi_shield_mode or "off"} for a in agents]


@phi_router.post("/test", response_model=PhiTestResponse)
async def phi_test(body: PhiTestRequest):
    from trellis.phi_shield import PhiVault, redact, detect
    vault = PhiVault()
    redacted_text, detections = redact(body.text, vault)
    return PhiTestResponse(
        redacted=redacted_text,
        detections=[PhiDetectionResult(
            type=d.phi_type, text=d.text, start=d.start, end=d.end,
            source=d.source, score=d.score,
        ) for d in detections],
    )


@phi_router.get("/stats")
async def phi_stats_endpoint():
    from trellis.phi_shield import phi_stats
    return phi_stats.summary()


@agents_router.put("/{agent_id}/phi", response_model=AgentRead)
async def update_agent_phi_mode(agent_id: str, body: PhiModeUpdate, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if body.phi_shield_mode not in ("full", "redact_only", "audit_only", "off"):
        raise HTTPException(400, f"Invalid phi_shield_mode: {body.phi_shield_mode}")
    agent.phi_shield_mode = body.phi_shield_mode
    await emit_audit(db, "phi_config_changed", agent_id=agent_id, details={
        "phi_shield_mode": body.phi_shield_mode})
    await db.commit()
    await db.refresh(agent)
    return agent


async def seed_default_routes(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(ModelRoute.id)))).scalar()
    if count and count > 0:
        return

    COSTS = {
        "gpt-4o": (0.005, 0.015), "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-3.5-turbo": (0.0005, 0.0015), "claude-sonnet-4-5": (0.003, 0.015),
        "claude-3-haiku": (0.00025, 0.00125), "qwen3.5:9b": (0.0, 0.0), "qwen3:8b": (0.0, 0.0), "llama3.1:8b": (0.0, 0.0),
        "llama-3.3-70b-versatile": (0.00059, 0.00079), "llama-3.1-8b-instant": (0.00005, 0.00008),
        "mixtral-8x7b-32768": (0.00024, 0.00024), "gemma2-9b-it": (0.0002, 0.0002),
        "meta/llama-3.3-70b-instruct": (0.00059, 0.00079),
        "meta/llama-3.1-405b-instruct": (0.005, 0.016),
        "qwen/qwen3-235b-a22b": (0.0012, 0.0012), "qwen/qwen3.5-397b-a22b": (0.0015, 0.0015),
        "qwen/qwen3-coder-480b-a35b": (0.0015, 0.0015),
        "deepseek-ai/deepseek-r1": (0.003, 0.008),
        "mistralai/mistral-large-3-675b-instruct": (0.002, 0.006),
        "nvidia/llama-3.1-nemotron-ultra-253b-v1": (0.003, 0.005),
    }

    for model_name, provider in MODEL_PROVIDER_MAP.items():
        costs = COSTS.get(model_name, (0.0, 0.0))
        db.add(ModelRoute(model_name=model_name, provider=provider,
                          cost_per_1k_input=costs[0], cost_per_1k_output=costs[1]))
    await db.commit()
