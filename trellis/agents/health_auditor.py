"""Health Auditor Agent — platform housekeeping agent.

Monitors agent health endpoints, tracks response times, detects degradation,
and emits structured health_check audit events. Runs as a background task
every TRELLIS_HEALTH_CHECK_INTERVAL seconds (default 300).
"""

import logging
import os
import time
from collections import deque
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

logger = logging.getLogger("trellis.agents.health_auditor")

# In-memory response time history: agent_id -> deque of last 20 latencies (ms)
_health_history: dict[str, deque] = {}
_MAX_HISTORY = 20
_DEGRADATION_THRESHOLD = 3.0  # >3x rolling average = degraded

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def check_one_agent(agent) -> dict:
    """Check a single agent. Returns a check result dict."""
    agent_id = agent.agent_id

    # Native agents have no health endpoint — always healthy
    if agent.agent_type == "native":
        return {
            "agent_id": agent_id,
            "status": "healthy",
            "latency_ms": None,
            "baseline_ms": None,
            "note": "native agent, no health endpoint",
        }

    # Agents without health endpoints
    if not agent.health_endpoint:
        return {
            "agent_id": agent_id,
            "status": "unknown",
            "latency_ms": None,
            "baseline_ms": None,
            "note": "no health_endpoint configured",
        }

    # HTTP health check
    client = _get_client()
    start = time.monotonic()
    try:
        resp = await client.get(agent.health_endpoint)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        ok = resp.status_code == 200
    except Exception as e:
        logger.warning(f"Health check failed for {agent_id}: {e}")
        agent.status = "unreachable"
        agent.last_health_check = datetime.now(timezone.utc)
        return {
            "agent_id": agent_id,
            "status": "unreachable",
            "latency_ms": None,
            "baseline_ms": None,
            "note": str(e)[:120],
        }

    # Track response time history
    history = _health_history.setdefault(agent_id, deque(maxlen=_MAX_HISTORY))
    history.append(latency_ms)

    # Detect degradation vs baseline (rolling avg of prior readings)
    baseline_ms = None
    degraded = False
    if len(history) >= 2:
        prior = list(history)[:-1]
        baseline_ms = round(sum(prior) / len(prior), 1)
        if latency_ms > baseline_ms * _DEGRADATION_THRESHOLD:
            degraded = True

    if not ok:
        status = "unreachable"
    elif degraded:
        status = "degraded"
    else:
        status = "healthy"

    agent.status = status
    agent.last_health_check = datetime.now(timezone.utc)

    return {
        "agent_id": agent_id,
        "status": status,
        "latency_ms": latency_ms,
        "baseline_ms": baseline_ms,
        "degraded": degraded,
    }


async def run_health_checks() -> list[dict]:
    """Run health checks on all agents. Returns list of check results."""
    from trellis.database import async_session
    from trellis.models import Agent
    from trellis.router import emit_audit

    checks = []
    async with async_session() as db:
        result = await db.execute(select(Agent))
        agents = list(result.scalars().all())

        for agent in agents:
            try:
                check = await check_one_agent(agent)
                checks.append(check)

                await emit_audit(
                    db, "health_check",
                    agent_id=agent.agent_id,
                    details={
                        "status": check["status"],
                        "latency_ms": check.get("latency_ms"),
                        "baseline_ms": check.get("baseline_ms"),
                        "degraded": check.get("degraded", False),
                    },
                )
            except Exception as e:
                logger.error(f"Error checking agent {agent.agent_id}: {e}")

        await db.commit()

    return checks


async def health_auditor_loop(interval: float | None = None) -> None:
    """Background loop — runs forever, checking agent health periodically."""
    import asyncio
    if interval is None:
        interval = float(os.environ.get("TRELLIS_HEALTH_CHECK_INTERVAL", 300))

    while True:
        try:
            checks = await run_health_checks()
            counts = _summarize(checks)
            logger.info(
                f"Health audit complete: {counts['total']} agents — "
                f"{counts['healthy']} healthy, {counts['degraded']} degraded, "
                f"{counts['unreachable']} unreachable"
            )
        except Exception as e:
            logger.error(f"Health auditor loop error: {e}")
        await asyncio.sleep(interval)


def _summarize(checks: list[dict]) -> dict:
    total = len(checks)
    healthy = sum(1 for c in checks if c["status"] == "healthy")
    degraded = sum(1 for c in checks if c["status"] == "degraded")
    unreachable = sum(1 for c in checks if c["status"] == "unreachable")
    return {"total": total, "healthy": healthy, "degraded": degraded, "unreachable": unreachable}


class HealthAuditorAgent:
    """Native agent — returns on-demand health report when triggered via envelope."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        checks = await run_health_checks()
        counts = _summarize(checks)

        # Build degradation highlights for summary text
        issues = [
            c for c in checks if c["status"] in ("degraded", "unreachable")
        ]
        issue_text = ""
        if issues:
            parts = []
            for c in issues:
                if c["status"] == "degraded" and c.get("baseline_ms"):
                    parts.append(f"{c['agent_id']}: avg {c['latency_ms']}ms, baseline {c['baseline_ms']}ms")
                else:
                    parts.append(f"{c['agent_id']}: {c['status']}")
            issue_text = " (" + "; ".join(parts) + ")"

        summary = (
            f"Health Report: {counts['total']} agents checked. "
            f"{counts['healthy']} healthy, {counts['degraded']} degraded, "
            f"{counts['unreachable']} unreachable{issue_text}"
        )

        return {
            "status": "completed",
            "result": {
                "text": summary,
                "data": {
                    "report": {
                        "total_agents": counts["total"],
                        "healthy": counts["healthy"],
                        "degraded": counts["degraded"],
                        "unreachable": counts["unreachable"],
                        "checks": checks,
                    }
                },
                "attachments": [],
            },
        }
