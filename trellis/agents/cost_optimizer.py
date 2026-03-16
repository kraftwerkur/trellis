"""Cost Optimizer Agent — platform FinOps housekeeping agent.

Analyzes cost event data to find optimization opportunities: expensive model
usage for simple tasks, cost-per-agent rankings, model efficiency comparisons,
and budget projections. Runs weekly (configurable). Read-only — never modifies.
"""

from trellis.agents.health_auditor import record_task_heartbeat
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

logger = logging.getLogger("trellis.agents.cost_optimizer")

# Run every 168 hours (weekly) by default
_OPTIMIZER_INTERVAL_HOURS = int(os.environ.get("TRELLIS_COST_OPTIMIZER_INTERVAL", 168))

# Models considered "expensive" — input price > $0.01/1k tokens ($10/Mtok)
_EXPENSIVE_THRESHOLD_PER_MTOK = 10.0

# Free/local models that can replace expensive ones for simple tasks
_LOCAL_MODELS = {"qwen3.5:9b", "qwen3:8b", "llama3.1:8b"}

# Complexity classes considered "simple" (don't need heavy LLMs)
_SIMPLE_CLASSES = {"LOW", "NORMAL", "simple", "low", "normal"}


async def run_analysis(days: int = 7) -> dict:
    """Run cost optimization analysis. Returns structured report dict."""
    from trellis.database import async_session
    from trellis.models import CostEvent
    from trellis.gateway import MODEL_PRICING

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as db:
        # --- Total cost in period ---
        total_result = await db.execute(
            select(func.coalesce(func.sum(CostEvent.cost_usd), 0.0)).where(
                CostEvent.timestamp >= cutoff
            )
        )
        total_cost: float = float(total_result.scalar_one())

        # --- Cost by agent ---
        agent_rows = await db.execute(
            select(
                CostEvent.agent_id,
                func.sum(CostEvent.cost_usd).label("cost_usd"),
                func.count(CostEvent.id).label("requests"),
                func.avg(CostEvent.cost_usd).label("avg_cost"),
            )
            .where(CostEvent.timestamp >= cutoff)
            .group_by(CostEvent.agent_id)
            .order_by(func.sum(CostEvent.cost_usd).desc())
        )
        agent_stats = agent_rows.all()

        # --- Cost + latency by model ---
        model_rows = await db.execute(
            select(
                CostEvent.model_used,
                func.sum(CostEvent.cost_usd).label("cost_usd"),
                func.count(CostEvent.id).label("requests"),
                func.avg(CostEvent.latency_ms).label("avg_latency_ms"),
            )
            .where(CostEvent.timestamp >= cutoff)
            .group_by(CostEvent.model_used)
            .order_by(func.sum(CostEvent.cost_usd).desc())
        )
        model_stats = model_rows.all()

        # p95 latency per model — SQLite supports percentile via window or manual
        # Use a subquery approach: rank ordered rows and pick the 95th percentile
        p95_rows = await db.execute(
            text("""
                SELECT model_used,
                       latency_ms AS p95_latency_ms
                FROM (
                    SELECT model_used, latency_ms,
                           NTILE(100) OVER (PARTITION BY model_used ORDER BY latency_ms) AS pct
                    FROM cost_events
                    WHERE timestamp >= :cutoff
                ) t
                WHERE pct = 95
                GROUP BY model_used
            """),
            {"cutoff": cutoff.isoformat()},
        )
        p95_map: dict[str, int] = {r.model_used: r.p95_latency_ms for r in p95_rows.all()}

        # --- Complexity-class breakdown per agent ---
        complexity_rows = await db.execute(
            select(
                CostEvent.agent_id,
                CostEvent.model_used,
                CostEvent.complexity_class,
                func.count(CostEvent.id).label("requests"),
                func.sum(CostEvent.cost_usd).label("cost_usd"),
            )
            .where(CostEvent.timestamp >= cutoff, CostEvent.complexity_class.isnot(None))
            .group_by(CostEvent.agent_id, CostEvent.model_used, CostEvent.complexity_class)
        )
        complexity_stats = complexity_rows.all()

    # --- Handle empty table gracefully ---
    if total_cost == 0.0 and not agent_stats:
        return {
            "status": "completed",
            "result": {
                "text": "Cost Optimization Report: No cost events in the last {} days. Nothing to analyze.".format(days),
                "data": {
                    "cost_report": {
                        "period_days": days,
                        "total_cost_usd": 0.0,
                        "daily_average_usd": 0.0,
                        "monthly_projection_usd": 0.0,
                        "by_agent": [],
                        "by_model": [],
                        "recommendations": [],
                    }
                },
                "attachments": [],
            },
        }

    # --- Build by_agent list ---
    by_agent = []
    for row in agent_stats:
        cost = float(row.cost_usd or 0.0)
        pct = round((cost / total_cost * 100), 1) if total_cost > 0 else 0.0
        by_agent.append({
            "agent_id": row.agent_id,
            "cost_usd": round(cost, 6),
            "requests": int(row.requests),
            "avg_cost_per_request": round(float(row.avg_cost or 0.0), 6),
            "pct_of_total": pct,
        })

    # --- Build by_model list ---
    by_model = []
    for row in model_stats:
        by_model.append({
            "model": row.model_used,
            "cost_usd": round(float(row.cost_usd or 0.0), 6),
            "requests": int(row.requests),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0.0), 1),
            "p95_latency_ms": p95_map.get(row.model_used),
        })

    # Also surface free/local models with 0 usage so the report shows the gap
    used_models = {r["model"] for r in by_model}
    for local_model in sorted(_LOCAL_MODELS):
        if local_model not in used_models:
            by_model.append({
                "model": local_model,
                "cost_usd": 0.0,
                "requests": 0,
                "avg_latency_ms": None,
                "p95_latency_ms": None,
            })

    # --- Build recommendations ---
    recommendations = []

    # Group complexity stats: agent → model → {simple_pct, total_requests, cost}
    agent_model_complexity: dict[tuple, dict] = {}
    for row in complexity_stats:
        key = (row.agent_id, row.model_used)
        if key not in agent_model_complexity:
            agent_model_complexity[key] = {"simple": 0, "total": 0, "cost": 0.0}
        is_simple = row.complexity_class in _SIMPLE_CLASSES
        agent_model_complexity[key]["total"] += int(row.requests)
        agent_model_complexity[key]["cost"] += float(row.cost_usd or 0.0)
        if is_simple:
            agent_model_complexity[key]["simple"] += int(row.requests)

    for (agent_id, model_used), stats in agent_model_complexity.items():
        if stats["total"] == 0:
            continue
        simple_pct = stats["simple"] / stats["total"] * 100
        if simple_pct < 50:
            continue  # not predominantly simple workload

        # Is the model expensive?
        pricing = MODEL_PRICING.get(model_used, {"input": 0.0, "output": 0.0})
        avg_price_per_mtok = (pricing["input"] + pricing["output"]) / 2.0
        if avg_price_per_mtok < _EXPENSIVE_THRESHOLD_PER_MTOK:
            continue  # not expensive enough to flag

        if model_used in _LOCAL_MODELS:
            continue  # already using local

        recommended = "qwen3.5:9b"
        est_savings_pct = round(min(95, simple_pct * 0.95))
        recommendations.append({
            "type": "model_downgrade",
            "agent_id": agent_id,
            "current_model": model_used,
            "suggested_model": recommended,
            "reason": "{:.0f}% of requests are simple complexity — local model sufficient".format(simple_pct),
            "estimated_savings_pct": est_savings_pct,
        })

    # Catch high-spend agents using expensive models with NO complexity data
    for row in model_stats:
        # Track the most-used model per agent via the complexity join above;
        # fall back to agent cost rows to find the dominant model
        pass

    # Dominant model per agent (from cost_events directly)
    # Find agents with no complexity data but expensive dominant models
    complex_agents = {key[0] for key in agent_model_complexity}
    for row in agent_stats:
        if row.agent_id in complex_agents:
            continue
        # No complexity data — still flag if cost is significant
        cost = float(row.cost_usd or 0.0)
        pct = (cost / total_cost * 100) if total_cost > 0 else 0.0
        if pct < 20:
            continue
        # Find the model this agent used most
        # We'd need another query; skip for now to stay read-simple

    # --- Provider comparison recommendations ---
    # Find models available on multiple providers in pricing map
    # (Out of scope for current pricing dict which keys by model name only)

    # --- Budget projections ---
    daily_avg = round(total_cost / days, 6) if days > 0 else 0.0
    monthly_projection = round(daily_avg * 30, 4)

    # --- Summary text ---
    top_agent = by_agent[0] if by_agent else None
    summary_parts = ["Cost Optimization Report: ${:.4f} spent in {} days.".format(total_cost, days)]
    if top_agent:
        summary_parts.append(
            "{} accounts for {:.0f}% of spend.".format(top_agent["agent_id"], top_agent["pct_of_total"])
        )
    if recommendations:
        r = recommendations[0]
        summary_parts.append(
            "Recommendation: Use {} for {}.".format(r["suggested_model"], r["agent_id"])
        )
    if monthly_projection > 0:
        summary_parts.append("Monthly projection: ${:.2f}.".format(monthly_projection))

    return {
        "status": "completed",
        "result": {
            "text": " ".join(summary_parts),
            "data": {
                "cost_report": {
                    "period_days": days,
                    "total_cost_usd": round(total_cost, 6),
                    "daily_average_usd": daily_avg,
                    "monthly_projection_usd": monthly_projection,
                    "by_agent": by_agent,
                    "by_model": by_model,
                    "recommendations": recommendations,
                }
            },
            "attachments": [],
        },
    }


async def cost_optimizer_loop() -> None:
    """Background loop — runs analysis weekly (configurable via TRELLIS_COST_OPTIMIZER_INTERVAL)."""
    _last_run: datetime | None = None

    while True:
        now = datetime.now(timezone.utc)
        interval = timedelta(hours=_OPTIMIZER_INTERVAL_HOURS)
        due = _last_run is None or (now - _last_run) >= interval

        if due:
            _last_run = now
            record_task_heartbeat("cost_optimizer")
            try:
                result = await run_analysis()
                report = result["result"]["data"]["cost_report"]
                logger.info(
                    "Cost optimizer complete: $%.4f over %d days, %d recommendations",
                    report["total_cost_usd"],
                    report["period_days"],
                    len(report["recommendations"]),
                )
            except Exception as e:
                logger.error("Cost optimizer loop error: %s", e)

        await asyncio.sleep(3600)  # check hourly


class CostOptimizerAgent:
    """Native agent — returns on-demand cost optimization report."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        hints = envelope.routing_hints or {}
        days = int(hints.get("days", 7))
        return await run_analysis(days=days)
