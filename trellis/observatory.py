"""LLM Observatory — monitoring and analytics for LLM usage across all agents.

Tracks per-model metrics (latency distributions, error rates, token efficiency),
cost-per-useful-response, time-series storage in SQLite, and exposes dashboard API endpoints.

Single file, Karpathy style.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, Integer, String, DateTime, Boolean, JSON, func, select, text, case, cast
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.database import get_db
from trellis.models import CostEvent

logger = logging.getLogger("trellis.observatory")


# ── Pydantic schemas ───────────────────────────────────────────────────────

class ModelSummary(BaseModel):
    model: str
    provider: str
    total_requests: int
    total_errors: int
    error_rate: float
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    avg_latency_ms: float
    last_used: str | None = None


class LatencyDistribution(BaseModel):
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    avg: float


class TokenEfficiency(BaseModel):
    avg_tokens_in: float
    avg_tokens_out: float
    avg_total_tokens: float
    output_ratio: float  # tokens_out / total — higher = more "useful" output


class ModelMetrics(BaseModel):
    model: str
    provider: str
    period_hours: int
    total_requests: int
    total_errors: int
    error_rate: float
    latency: LatencyDistribution
    token_efficiency: TokenEfficiency
    total_cost_usd: float
    avg_cost_per_request: float
    hourly_breakdown: list[dict[str, Any]]


class ObservatorySummary(BaseModel):
    total_requests: int
    total_errors: int
    overall_error_rate: float
    total_cost_usd: float
    total_tokens: int
    unique_models: int
    unique_agents: int
    top_models_by_requests: list[dict[str, Any]]
    top_models_by_cost: list[dict[str, Any]]
    avg_latency_ms: float
    period_hours: int


# ── Metrics capture hook ───────────────────────────────────────────────────
# Call this from the gateway after each LLM call. The CostEvent table already
# stores everything we need (latency_ms, tokens, model, provider, cost).
# Observatory reads from CostEvent — no separate table needed.
#
# For error tracking, we add a lightweight in-memory counter + periodic
# DB writes. Errors don't create CostEvents (the call failed), so we
# need a separate mechanism.

# In-memory error accumulator (flushed to DB isn't needed — we track errors
# via a simple approach: if latency_ms == -1 in CostEvent, it's an error.
# But CostEvents aren't created for errors. So we'll use AuditEvents instead.)
#
# Strategy: Query AuditEvents with event_type='llm_error' for error counts,
# and CostEvents for success metrics. Or simpler: record errors as CostEvents
# with a sentinel value. Let's go with tracking via the existing data.
#
# Actually, the cleanest approach: the gateway already emits audit events for
# errors (provider errors raise HTTPException). We can count errors from
# audit_events where event_type contains 'error' or from failed requests.
#
# Simplest correct approach: Observatory queries CostEvent for successes
# and AuditEvent for errors. But that couples us to audit event naming.
#
# Let's add a record_error() function that creates a CostEvent with
# cost_usd=0, tokens=0, latency_ms=-1 as error sentinel. This keeps
# everything in one table.

async def record_llm_error(
    db: AsyncSession,
    *,
    agent_id: str,
    model_requested: str,
    model_used: str,
    provider: str,
    error_type: str = "provider_error",
    latency_ms: int = 0,
    trace_id: str | None = None,
) -> CostEvent:
    """Record a failed LLM call as a CostEvent with zero cost and error marker.

    Uses complexity_class field to store error_type (avoids schema changes).
    Uses tokens_in=-1 as error sentinel.
    """
    event = CostEvent(
        trace_id=trace_id,
        agent_id=agent_id,
        model_requested=model_requested,
        model_used=model_used,
        provider=provider,
        tokens_in=-1,  # error sentinel
        tokens_out=0,
        cost_usd=0.0,
        latency_ms=latency_ms,
        has_tool_calls=False,
        complexity_class=f"error:{error_type}",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


# ── Query helpers ──────────────────────────────────────────────────────────

def _period_start(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _is_error_filter():
    """SQLAlchemy filter expression for error events."""
    return CostEvent.tokens_in == -1


def _is_success_filter():
    """SQLAlchemy filter expression for successful events."""
    return CostEvent.tokens_in >= 0


async def _get_latency_percentiles(
    db: AsyncSession, model: str | None = None, hours: int = 24
) -> LatencyDistribution:
    """Compute latency percentiles from successful CostEvents.

    SQLite doesn't have native percentile functions, so we fetch latencies
    and compute in Python. For large datasets, this should use window functions
    or pre-aggregated tables.
    """
    since = _period_start(hours)
    q = select(CostEvent.latency_ms).where(
        CostEvent.timestamp >= since,
        _is_success_filter(),
    )
    if model:
        q = q.where(CostEvent.model_used == model)
    q = q.order_by(CostEvent.latency_ms)

    result = await db.execute(q)
    latencies = [row[0] for row in result.all()]

    if not latencies:
        return LatencyDistribution(p50=0, p95=0, p99=0, min=0, max=0, avg=0)

    n = len(latencies)

    def percentile(pct: float) -> float:
        idx = int(pct / 100 * (n - 1))
        return float(latencies[min(idx, n - 1)])

    return LatencyDistribution(
        p50=percentile(50),
        p95=percentile(95),
        p99=percentile(99),
        min=float(latencies[0]),
        max=float(latencies[-1]),
        avg=round(sum(latencies) / n, 2),
    )


async def _get_token_efficiency(
    db: AsyncSession, model: str | None = None, hours: int = 24
) -> TokenEfficiency:
    since = _period_start(hours)
    q = select(
        func.avg(CostEvent.tokens_in).label("avg_in"),
        func.avg(CostEvent.tokens_out).label("avg_out"),
        func.avg(CostEvent.tokens_in + CostEvent.tokens_out).label("avg_total"),
        func.sum(CostEvent.tokens_out).label("sum_out"),
        func.sum(CostEvent.tokens_in + CostEvent.tokens_out).label("sum_total"),
    ).where(
        CostEvent.timestamp >= since,
        _is_success_filter(),
    )
    if model:
        q = q.where(CostEvent.model_used == model)

    result = await db.execute(q)
    row = result.one()

    avg_in = float(row.avg_in or 0)
    avg_out = float(row.avg_out or 0)
    avg_total = float(row.avg_total or 0)
    sum_out = float(row.sum_out or 0)
    sum_total = float(row.sum_total or 0)

    return TokenEfficiency(
        avg_tokens_in=round(avg_in, 1),
        avg_tokens_out=round(avg_out, 1),
        avg_total_tokens=round(avg_total, 1),
        output_ratio=round(sum_out / sum_total, 4) if sum_total > 0 else 0.0,
    )


async def _get_hourly_breakdown(
    db: AsyncSession, model: str, hours: int = 24
) -> list[dict[str, Any]]:
    """Get hourly request counts and avg latency for a model."""
    since = _period_start(hours)

    # SQLite strftime for hourly bucketing
    hour_expr = func.strftime("%Y-%m-%dT%H:00:00Z", CostEvent.timestamp)

    q = (
        select(
            hour_expr.label("hour"),
            func.count(CostEvent.id).label("total"),
            func.sum(case((_is_error_filter(), 1), else_=0)).label("errors"),
            func.avg(
                case((_is_success_filter(), CostEvent.latency_ms), else_=None)
            ).label("avg_latency_ms"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0.0).label("cost_usd"),
        )
        .where(CostEvent.timestamp >= since, CostEvent.model_used == model)
        .group_by(hour_expr)
        .order_by(hour_expr)
    )

    result = await db.execute(q)
    return [
        {
            "hour": row.hour,
            "total_requests": row.total,
            "errors": int(row.errors),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0), 2),
            "cost_usd": round(float(row.cost_usd), 8),
        }
        for row in result.all()
    ]


# ── API Router ─────────────────────────────────────────────────────────────

from trellis.api import require_management_auth

observatory_router = APIRouter(
    prefix="/observatory", tags=["observatory"],
    dependencies=[Depends(require_management_auth)]
)


@observatory_router.get("/models", response_model=list[ModelSummary])
async def list_models(
    hours: int = Query(24, ge=1, le=8760, description="Lookback period in hours"),
    db: AsyncSession = Depends(get_db),
):
    """List all models with summary metrics."""
    since = _period_start(hours)

    q = (
        select(
            CostEvent.model_used.label("model"),
            CostEvent.provider,
            func.count(CostEvent.id).label("total_requests"),
            func.sum(case((_is_error_filter(), 1), else_=0)).label("total_errors"),
            func.sum(case((_is_success_filter(), CostEvent.tokens_in), else_=0)).label("total_tokens_in"),
            func.sum(CostEvent.tokens_out).label("total_tokens_out"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0.0).label("total_cost_usd"),
            func.avg(
                case((_is_success_filter(), CostEvent.latency_ms), else_=None)
            ).label("avg_latency_ms"),
            func.max(CostEvent.timestamp).label("last_used"),
        )
        .where(CostEvent.timestamp >= since)
        .group_by(CostEvent.model_used, CostEvent.provider)
        .order_by(func.count(CostEvent.id).desc())
    )

    result = await db.execute(q)
    rows = result.all()

    return [
        ModelSummary(
            model=row.model,
            provider=row.provider,
            total_requests=row.total_requests,
            total_errors=int(row.total_errors),
            error_rate=round(int(row.total_errors) / row.total_requests, 4) if row.total_requests > 0 else 0.0,
            total_tokens_in=int(row.total_tokens_in),
            total_tokens_out=int(row.total_tokens_out),
            total_cost_usd=round(float(row.total_cost_usd), 8),
            avg_latency_ms=round(float(row.avg_latency_ms or 0), 2),
            last_used=row.last_used.isoformat() if row.last_used else None,
        )
        for row in rows
    ]


@observatory_router.get("/models/{model_id:path}/metrics", response_model=ModelMetrics)
async def get_model_metrics(
    model_id: str,
    hours: int = Query(24, ge=1, le=8760),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed metrics for a specific model."""
    since = _period_start(hours)

    # Check model exists in period
    count_q = select(func.count(CostEvent.id)).where(
        CostEvent.model_used == model_id,
        CostEvent.timestamp >= since,
    )
    count = (await db.execute(count_q)).scalar()
    if not count:
        raise HTTPException(404, f"No data for model '{model_id}' in the last {hours}h")

    # Basic stats
    stats_q = select(
        CostEvent.provider,
        func.count(CostEvent.id).label("total"),
        func.sum(case((_is_error_filter(), 1), else_=0)).label("errors"),
        func.coalesce(func.sum(CostEvent.cost_usd), 0.0).label("cost"),
    ).where(
        CostEvent.model_used == model_id,
        CostEvent.timestamp >= since,
    ).group_by(CostEvent.provider)

    stats_result = await db.execute(stats_q)
    stats_row = stats_result.first()

    total_requests = stats_row.total
    total_errors = int(stats_row.errors)
    total_cost = float(stats_row.cost)
    provider = stats_row.provider

    latency = await _get_latency_percentiles(db, model_id, hours)
    efficiency = await _get_token_efficiency(db, model_id, hours)
    hourly = await _get_hourly_breakdown(db, model_id, hours)

    return ModelMetrics(
        model=model_id,
        provider=provider,
        period_hours=hours,
        total_requests=total_requests,
        total_errors=total_errors,
        error_rate=round(total_errors / total_requests, 4) if total_requests > 0 else 0.0,
        latency=latency,
        token_efficiency=efficiency,
        total_cost_usd=round(total_cost, 8),
        avg_cost_per_request=round(total_cost / total_requests, 8) if total_requests > 0 else 0.0,
        hourly_breakdown=hourly,
    )


@observatory_router.get("/summary", response_model=ObservatorySummary)
async def get_summary(
    hours: int = Query(24, ge=1, le=8760),
    db: AsyncSession = Depends(get_db),
):
    """Get overall observatory summary across all models."""
    since = _period_start(hours)

    # Aggregate stats
    q = select(
        func.count(CostEvent.id).label("total_requests"),
        func.sum(case((_is_error_filter(), 1), else_=0)).label("total_errors"),
        func.coalesce(func.sum(CostEvent.cost_usd), 0.0).label("total_cost"),
        func.coalesce(
            func.sum(
                case((_is_success_filter(), CostEvent.tokens_in + CostEvent.tokens_out), else_=0)
            ), 0
        ).label("total_tokens"),
        func.avg(
            case((_is_success_filter(), CostEvent.latency_ms), else_=None)
        ).label("avg_latency"),
    ).where(CostEvent.timestamp >= since)

    result = await db.execute(q)
    row = result.one()

    total_requests = int(row.total_requests or 0)
    total_errors = int(row.total_errors or 0)
    total_cost = float(row.total_cost or 0)
    total_tokens = int(row.total_tokens or 0)
    avg_latency = float(row.avg_latency or 0)

    # Unique counts
    models_q = select(func.count(func.distinct(CostEvent.model_used))).where(
        CostEvent.timestamp >= since
    )
    unique_models = (await db.execute(models_q)).scalar() or 0

    agents_q = select(func.count(func.distinct(CostEvent.agent_id))).where(
        CostEvent.timestamp >= since
    )
    unique_agents = (await db.execute(agents_q)).scalar() or 0

    # Top models by requests
    top_req_q = (
        select(
            CostEvent.model_used.label("model"),
            func.count(CostEvent.id).label("requests"),
        )
        .where(CostEvent.timestamp >= since)
        .group_by(CostEvent.model_used)
        .order_by(func.count(CostEvent.id).desc())
        .limit(5)
    )
    top_by_requests = [
        {"model": r.model, "requests": r.requests}
        for r in (await db.execute(top_req_q)).all()
    ]

    # Top models by cost
    top_cost_q = (
        select(
            CostEvent.model_used.label("model"),
            func.coalesce(func.sum(CostEvent.cost_usd), 0.0).label("cost"),
        )
        .where(CostEvent.timestamp >= since)
        .group_by(CostEvent.model_used)
        .order_by(func.sum(CostEvent.cost_usd).desc())
        .limit(5)
    )
    top_by_cost = [
        {"model": r.model, "cost_usd": round(float(r.cost), 8)}
        for r in (await db.execute(top_cost_q)).all()
    ]

    return ObservatorySummary(
        total_requests=total_requests,
        total_errors=total_errors,
        overall_error_rate=round(total_errors / total_requests, 4) if total_requests > 0 else 0.0,
        total_cost_usd=round(total_cost, 8),
        total_tokens=total_tokens,
        unique_models=unique_models,
        unique_agents=unique_agents,
        top_models_by_requests=top_by_requests,
        top_models_by_cost=top_by_cost,
        avg_latency_ms=round(avg_latency, 2),
        period_hours=hours,
    )
