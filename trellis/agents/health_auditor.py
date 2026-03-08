"""Health Auditor Agent — platform housekeeping agent.

Monitors agent health endpoints, tracks response times, detects degradation,
and emits structured health_check audit events. Runs as a background task
every TRELLIS_HEALTH_CHECK_INTERVAL seconds (default 300).

Also monitors infrastructure health: LLM providers, database, background tasks,
SMTP relay, and system resources.
"""

import asyncio
import logging
import os
import shutil
import socket
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psutil
from sqlalchemy import func, select, text

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
        agent.status = "healthy"
        return {
            "agent_id": agent_id,
            "status": "healthy",
            "latency_ms": None,
            "baseline_ms": None,
            "note": "native agent, no health endpoint",
        }

    # Function agents without health endpoints — in-process, always healthy
    if not agent.health_endpoint:
        if agent.agent_type == "function":
            agent.status = "healthy"
        return {
            "agent_id": agent_id,
            "status": "healthy" if agent.agent_type == "function" else "unknown",
            "latency_ms": None,
            "baseline_ms": None,
            "note": "in-process agent" if agent.agent_type == "function" else "no health_endpoint configured",
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
    """Background loop — runs forever, checking agent + infra health periodically."""
    if interval is None:
        interval = float(os.environ.get("TRELLIS_HEALTH_CHECK_INTERVAL", 300))

    while True:
        try:
            record_task_heartbeat("health_auditor")

            # Agent health checks
            checks = await run_health_checks()
            counts = _summarize(checks)
            logger.info(
                f"Health audit complete: {counts['total']} agents — "
                f"{counts['healthy']} healthy, {counts['degraded']} degraded, "
                f"{counts['unreachable']} unreachable"
            )

            # Infrastructure health checks
            infra = await run_infra_checks_and_log()
            logger.info(f"Infra health: {infra.overall_status()}")

        except Exception as e:
            logger.error(f"Health auditor loop error: {e}")
        await asyncio.sleep(interval)


def _summarize(checks: list[dict]) -> dict:
    total = len(checks)
    healthy = sum(1 for c in checks if c["status"] == "healthy")
    degraded = sum(1 for c in checks if c["status"] == "degraded")
    unreachable = sum(1 for c in checks if c["status"] == "unreachable")
    return {"total": total, "healthy": healthy, "degraded": degraded, "unreachable": unreachable}


# ── Infrastructure Health Checks ───────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    status: str  # "healthy", "degraded", "unreachable", "warning"
    latency_ms: float | None = None
    details: dict = field(default_factory=dict)


@dataclass
class InfraHealthCheck:
    timestamp: str = ""
    llm_providers: list[dict] = field(default_factory=list)
    database: dict = field(default_factory=dict)
    background_tasks: list[dict] = field(default_factory=list)
    smtp: dict = field(default_factory=dict)
    system: dict = field(default_factory=dict)

    def overall_status(self) -> str:
        all_checks = []
        all_checks.extend(c.get("status", "unknown") for c in self.llm_providers)
        all_checks.append(self.database.get("status", "unknown"))
        all_checks.extend(c.get("status", "unknown") for c in self.background_tasks)
        all_checks.append(self.smtp.get("status", "unknown"))
        all_checks.append(self.system.get("status", "unknown"))
        if "unreachable" in all_checks:
            return "unhealthy"
        if "degraded" in all_checks or "warning" in all_checks:
            return "degraded"
        return "healthy"


# Track last execution timestamps for background tasks
_background_task_heartbeats: dict[str, datetime] = {}

# Stale threshold: if a task hasn't run in 2x its expected interval, it's stale
_TASK_STALE_MULTIPLIER = 2.5


def record_task_heartbeat(task_name: str) -> None:
    """Called by background tasks to record their last execution time."""
    _background_task_heartbeats[task_name] = datetime.now(timezone.utc)


async def _check_llm_providers() -> list[dict]:
    """Check configured LLM provider endpoints with a lightweight models list call."""
    from trellis.gateway import _providers

    results = []
    client = _get_client()
    for name, provider in _providers.items():
        base_url = getattr(provider, "base_url", None)
        if not base_url:
            continue

        # Strip /v1 suffix for models endpoint
        models_url = base_url.rstrip("/") + "/models"
        start = time.monotonic()
        try:
            resp = await client.get(models_url, timeout=5.0)
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            ok = resp.status_code == 200
            model_count = None
            if ok:
                try:
                    data = resp.json()
                    model_count = len(data.get("data", data.get("models", [])))
                except Exception:
                    pass
            results.append(asdict(CheckResult(
                name=name, status="healthy" if ok else "degraded",
                latency_ms=latency_ms,
                details={"url": base_url, "model_count": model_count,
                         "http_status": resp.status_code},
            )))
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            results.append(asdict(CheckResult(
                name=name, status="unreachable", latency_ms=latency_ms,
                details={"url": base_url, "error": str(e)[:120]},
            )))
    return results


async def _check_database() -> dict:
    """Check SQLite database health: file size, WAL size, table counts, last write."""
    from trellis.config import settings
    from trellis.database import async_session
    from trellis.models import Agent, AuditEvent, CostEvent, EnvelopeLog

    result: dict = {"status": "healthy", "details": {}}

    # Parse DB path from URL
    db_url = settings.database_url
    # "sqlite+aiosqlite:///./trellis.db" -> "./trellis.db"
    db_path_str = db_url.split("///", 1)[-1] if "///" in db_url else None
    if db_path_str:
        db_path = Path(db_path_str)
        if db_path.exists():
            result["details"]["file_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
            wal_path = db_path.parent / (db_path.name + "-wal")
            if wal_path.exists():
                result["details"]["wal_size_mb"] = round(wal_path.stat().st_size / (1024 * 1024), 2)
            else:
                result["details"]["wal_size_mb"] = 0
        else:
            result["status"] = "warning"
            result["details"]["error"] = "DB file not found"
            return result

    # Table row counts and last write
    try:
        async with async_session() as db:
            tables = {
                "agents": Agent, "audit_events": AuditEvent,
                "cost_events": CostEvent, "envelope_log": EnvelopeLog,
            }
            counts = {}
            for tname, model in tables.items():
                row = await db.execute(select(func.count()).select_from(model))
                counts[tname] = row.scalar() or 0
            result["details"]["row_counts"] = counts

            # Last audit event timestamp as proxy for "last write"
            row = await db.execute(
                select(AuditEvent.timestamp).order_by(AuditEvent.timestamp.desc()).limit(1)
            )
            last_ts = row.scalar()
            if last_ts:
                result["details"]["last_write"] = last_ts.isoformat()
    except Exception as e:
        result["status"] = "degraded"
        result["details"]["error"] = str(e)[:120]

    return result


def _check_background_tasks() -> list[dict]:
    """Check that background task loops are still running."""
    now = datetime.now(timezone.utc)
    # Expected intervals (seconds) for known tasks
    expected_intervals = {
        "health_auditor": float(os.environ.get("TRELLIS_HEALTH_CHECK_INTERVAL", 300)),
        "audit_compactor": float(os.environ.get("TRELLIS_COMPACTION_INTERVAL", 86400)),
        "rule_optimizer": 3600.0,  # default 1h
        "schema_drift": 86400.0,  # default 24h
        "cost_optimizer": 3600.0,  # default 1h
    }
    results = []
    for task_name, expected_interval in expected_intervals.items():
        last_run = _background_task_heartbeats.get(task_name)
        if last_run is None:
            results.append(asdict(CheckResult(
                name=task_name, status="warning",
                details={"note": "no heartbeat recorded yet"},
            )))
        else:
            age_s = (now - last_run).total_seconds()
            stale = age_s > expected_interval * _TASK_STALE_MULTIPLIER
            results.append(asdict(CheckResult(
                name=task_name,
                status="warning" if stale else "healthy",
                details={
                    "last_run": last_run.isoformat(),
                    "age_seconds": round(age_s, 1),
                    "expected_interval": expected_interval,
                    "stale": stale,
                },
            )))
    return results


def _check_smtp() -> dict:
    """Lightweight SMTP relay reachability check (socket connect, no send)."""
    smtp_host = os.environ.get("TRELLIS_SMTP_HOST", "")
    smtp_port = int(os.environ.get("TRELLIS_SMTP_PORT", "25"))

    if not smtp_host:
        return asdict(CheckResult(
            name="smtp", status="warning",
            details={"note": "TRELLIS_SMTP_HOST not configured"},
        ))

    start = time.monotonic()
    try:
        sock = socket.create_connection((smtp_host, smtp_port), timeout=5)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        sock.close()
        return asdict(CheckResult(
            name="smtp", status="healthy", latency_ms=latency_ms,
            details={"host": smtp_host, "port": smtp_port},
        ))
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return asdict(CheckResult(
            name="smtp", status="unreachable", latency_ms=latency_ms,
            details={"host": smtp_host, "port": smtp_port, "error": str(e)[:120]},
        ))


def _check_system() -> dict:
    """Basic system resource checks: disk, memory."""
    details: dict = {}
    status = "healthy"

    # Disk
    disk = shutil.disk_usage("/")
    details["disk_total_gb"] = round(disk.total / (1024**3), 1)
    details["disk_used_gb"] = round(disk.used / (1024**3), 1)
    details["disk_free_gb"] = round(disk.free / (1024**3), 1)
    details["disk_percent_used"] = round(disk.used / disk.total * 100, 1)
    if details["disk_percent_used"] > 90:
        status = "warning"

    # Memory
    mem = psutil.virtual_memory()
    details["memory_total_gb"] = round(mem.total / (1024**3), 1)
    details["memory_used_gb"] = round(mem.used / (1024**3), 1)
    details["memory_percent_used"] = round(mem.percent, 1)
    if mem.percent > 90:
        status = "warning"

    return asdict(CheckResult(name="system", status=status, details=details))


async def run_infra_checks() -> InfraHealthCheck:
    """Run all infrastructure health checks. Returns InfraHealthCheck."""
    check = InfraHealthCheck(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Run async checks concurrently
    llm_task = asyncio.create_task(_check_llm_providers())
    db_task = asyncio.create_task(_check_database())

    check.llm_providers = await llm_task
    check.database = await db_task

    # Sync checks
    check.background_tasks = _check_background_tasks()
    check.smtp = _check_smtp()
    check.system = _check_system()

    return check


async def run_infra_checks_and_log() -> InfraHealthCheck:
    """Run infra checks and emit an audit event."""
    from trellis.database import async_session
    from trellis.router import emit_audit

    result = await run_infra_checks()
    try:
        async with async_session() as db:
            await emit_audit(
                db, "infra_health",
                details={
                    "overall_status": result.overall_status(),
                    "llm_providers": result.llm_providers,
                    "database": result.database,
                    "background_tasks": result.background_tasks,
                    "smtp": result.smtp,
                    "system": result.system,
                },
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log infra health: {e}")

    return result


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
