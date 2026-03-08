"""Health Auditor — comprehensive infrastructure health monitoring.

Single file, Karpathy style. Monitors:
- Agent health endpoints (response time, degradation detection)
- LLM provider availability (ping /models endpoints)
- Database health (SQLite integrity, file size, disk space)
- Background task health (heartbeat tracking, staleness detection)
- SMTP/notification connectivity
- Adapter health (HTTP, Teams, HL7/FHIR endpoints)
- System resources (disk, memory)

Stores results in `health_checks` table. Exposes API endpoints:
  GET /api/health          — quick status (cached last run)
  GET /api/health/detailed — run all checks now, return full results
  GET /api/health/history  — recent check results from DB

Background loop runs every TRELLIS_HEALTH_CHECK_INTERVAL seconds (default 60).
"""

import asyncio
import logging
import os
import shutil
import socket
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.database import async_session, get_db
from trellis.models import Agent, AuditEvent, CostEvent, EnvelopeLog, HealthCheck

logger = logging.getLogger("trellis.agents.health_auditor")

# ── Constants ──────────────────────────────────────────────────────────────

_MAX_HISTORY = 20
_DEGRADATION_THRESHOLD = 3.0  # >3x rolling average = degraded
_TASK_STALE_MULTIPLIER = 2.5

# In-memory response time history: agent_id -> deque of last N latencies (ms)
_health_history: dict[str, deque] = {}

# Track last execution timestamps for background tasks
_background_task_heartbeats: dict[str, datetime] = {}

# Cached last full check result
_last_check_result: dict[str, Any] | None = None
_last_check_time: datetime | None = None

# Shared HTTP client
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


def record_task_heartbeat(task_name: str) -> None:
    """Called by background tasks to record their last execution time."""
    _background_task_heartbeats[task_name] = datetime.now(timezone.utc)


# ── Check Result Dataclass ─────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    status: str  # "healthy", "degraded", "unreachable", "warning"
    latency_ms: float | None = None
    details: dict = field(default_factory=dict)


# ── Agent Health Checks ────────────────────────────────────────────────────

async def check_one_agent(agent) -> dict:
    """Check a single agent's health endpoint. Returns a check result dict."""
    agent_id = agent.agent_id

    if agent.agent_type == "native":
        agent.status = "healthy"
        return {
            "agent_id": agent_id, "status": "healthy",
            "latency_ms": None, "baseline_ms": None,
            "note": "native agent, no health endpoint",
        }

    if not agent.health_endpoint:
        if agent.agent_type == "function":
            agent.status = "healthy"
        return {
            "agent_id": agent_id,
            "status": "healthy" if agent.agent_type == "function" else "unknown",
            "latency_ms": None, "baseline_ms": None,
            "note": "in-process agent" if agent.agent_type == "function" else "no health_endpoint configured",
        }

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
            "agent_id": agent_id, "status": "unreachable",
            "latency_ms": None, "baseline_ms": None,
            "note": str(e)[:120],
        }

    history = _health_history.setdefault(agent_id, deque(maxlen=_MAX_HISTORY))
    history.append(latency_ms)

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
        "agent_id": agent_id, "status": status,
        "latency_ms": latency_ms, "baseline_ms": baseline_ms,
        "degraded": degraded,
    }


async def run_agent_health_checks() -> list[dict]:
    """Run health checks on all registered agents. Returns list of results."""
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
                    db, "health_check", agent_id=agent.agent_id,
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


# ── Infrastructure Checks ──────────────────────────────────────────────────

async def check_llm_providers() -> list[CheckResult]:
    """Check configured LLM provider endpoints with a lightweight /models call."""
    from trellis.gateway import _providers

    results = []
    client = _get_client()
    for name, provider in _providers.items():
        base_url = getattr(provider, "base_url", None)
        if not base_url:
            continue

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
            results.append(CheckResult(
                name=f"llm:{name}", status="healthy" if ok else "degraded",
                latency_ms=latency_ms,
                details={"url": base_url, "model_count": model_count, "http_status": resp.status_code},
            ))
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            results.append(CheckResult(
                name=f"llm:{name}", status="unreachable", latency_ms=latency_ms,
                details={"url": base_url, "error": str(e)[:120]},
            ))
    return results


async def check_database() -> CheckResult:
    """Check SQLite database: file exists, writable, integrity, size, row counts."""
    from trellis.config import settings

    details: dict = {}

    # Parse DB path
    db_url = settings.database_url
    db_path_str = db_url.split("///", 1)[-1] if "///" in db_url else None

    if db_path_str and db_path_str != ":memory:":
        db_path = Path(db_path_str)
        if db_path.exists():
            details["file_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2)
            details["writable"] = os.access(db_path, os.W_OK)
            wal_path = db_path.parent / (db_path.name + "-wal")
            if wal_path.exists():
                details["wal_size_mb"] = round(wal_path.stat().st_size / (1024 * 1024), 2)
            # Disk space for DB partition
            disk = shutil.disk_usage(str(db_path.parent))
            details["partition_free_gb"] = round(disk.free / (1024**3), 1)
            if not details["writable"]:
                return CheckResult(name="database", status="unreachable", details=details)
        else:
            return CheckResult(name="database", status="unreachable",
                               details={"error": f"DB file not found: {db_path_str}"})

    # Integrity check + row counts
    start = time.monotonic()
    try:
        async with async_session() as db:
            # PRAGMA integrity_check
            row = await db.execute(text("PRAGMA integrity_check"))
            integrity = row.scalar()
            details["integrity"] = integrity
            if integrity != "ok":
                return CheckResult(name="database", status="degraded",
                                   latency_ms=round((time.monotonic() - start) * 1000, 1),
                                   details=details)

            # Row counts
            tables = {"agents": Agent, "audit_events": AuditEvent,
                      "cost_events": CostEvent, "envelope_log": EnvelopeLog}
            counts = {}
            for tname, model in tables.items():
                r = await db.execute(select(func.count()).select_from(model))
                counts[tname] = r.scalar() or 0
            details["row_counts"] = counts

            # Last write
            r = await db.execute(
                select(AuditEvent.timestamp).order_by(AuditEvent.timestamp.desc()).limit(1)
            )
            last_ts = r.scalar()
            if last_ts:
                details["last_write"] = last_ts.isoformat()

        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return CheckResult(name="database", status="healthy", latency_ms=latency_ms, details=details)

    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        details["error"] = str(e)[:120]
        return CheckResult(name="database", status="degraded", latency_ms=latency_ms, details=details)


def check_background_tasks() -> list[CheckResult]:
    """Check that background task loops are still running via heartbeat tracking."""
    now = datetime.now(timezone.utc)
    expected_intervals = {
        "health_auditor": float(os.environ.get("TRELLIS_HEALTH_CHECK_INTERVAL", 60)),
        "audit_compactor": float(os.environ.get("TRELLIS_COMPACTION_INTERVAL", 86400)),
        "rule_optimizer": 3600.0,
        "schema_drift": 86400.0,
        "cost_optimizer": 3600.0,
    }
    results = []
    for task_name, expected_interval in expected_intervals.items():
        last_run = _background_task_heartbeats.get(task_name)
        if last_run is None:
            results.append(CheckResult(
                name=f"task:{task_name}", status="warning",
                details={"note": "no heartbeat recorded yet"},
            ))
        else:
            age_s = (now - last_run).total_seconds()
            stale = age_s > expected_interval * _TASK_STALE_MULTIPLIER
            results.append(CheckResult(
                name=f"task:{task_name}",
                status="warning" if stale else "healthy",
                details={
                    "last_run": last_run.isoformat(),
                    "age_seconds": round(age_s, 1),
                    "expected_interval": expected_interval,
                    "stale": stale,
                },
            ))
    return results


def check_smtp() -> CheckResult:
    """Lightweight SMTP relay reachability check (socket connect, no send)."""
    smtp_host = os.environ.get("TRELLIS_SMTP_HOST", "")
    smtp_port = int(os.environ.get("TRELLIS_SMTP_PORT", "25"))

    if not smtp_host:
        return CheckResult(
            name="smtp", status="warning",
            details={"note": "TRELLIS_SMTP_HOST not configured"},
        )

    start = time.monotonic()
    try:
        sock = socket.create_connection((smtp_host, smtp_port), timeout=5)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        sock.close()
        return CheckResult(name="smtp", status="healthy", latency_ms=latency_ms,
                           details={"host": smtp_host, "port": smtp_port})
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return CheckResult(name="smtp", status="unreachable", latency_ms=latency_ms,
                           details={"host": smtp_host, "port": smtp_port, "error": str(e)[:120]})


def check_system() -> CheckResult:
    """Basic system resource checks: disk, memory."""
    details: dict = {}
    status = "healthy"

    try:
        disk = shutil.disk_usage("/")
        details["disk_total_gb"] = round(disk.total / (1024**3), 1)
        details["disk_used_gb"] = round(disk.used / (1024**3), 1)
        details["disk_free_gb"] = round(disk.free / (1024**3), 1)
        details["disk_percent_used"] = round(disk.used / disk.total * 100, 1)
        if details["disk_percent_used"] > 90:
            status = "warning"
    except Exception as e:
        details["disk_error"] = str(e)[:120]
        status = "warning"

    try:
        import psutil
        mem = psutil.virtual_memory()
        details["memory_total_gb"] = round(mem.total / (1024**3), 1)
        details["memory_used_gb"] = round(mem.used / (1024**3), 1)
        details["memory_percent_used"] = round(mem.percent, 1)
        if mem.percent > 90:
            status = "warning"
    except ImportError:
        details["memory_note"] = "psutil not installed"
    except Exception as e:
        details["memory_error"] = str(e)[:120]

    return CheckResult(name="system", status=status, details=details)


async def check_adapters() -> list[CheckResult]:
    """Check adapter health — configured adapter endpoints."""
    results = []

    # Check HTTP adapter (always available — it's the main app)
    results.append(CheckResult(name="adapter:http", status="healthy",
                               details={"note": "built-in, always available"}))

    # Teams adapter — check if configured (Bot Framework app_id set)
    teams_app_id = os.environ.get("TEAMS_APP_ID", "")
    if teams_app_id:
        results.append(CheckResult(name="adapter:teams", status="healthy",
                                   details={"app_id_configured": True}))
    else:
        results.append(CheckResult(name="adapter:teams", status="warning",
                                   details={"note": "TEAMS_APP_ID not configured"}))

    # HL7/FHIR adapter — check if FHIR endpoint configured
    fhir_url = os.environ.get("TRELLIS_FHIR_ENDPOINT", "")
    if fhir_url:
        client = _get_client()
        start = time.monotonic()
        try:
            resp = await client.get(fhir_url + "/metadata", timeout=5.0)
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            results.append(CheckResult(
                name="adapter:fhir", status="healthy" if resp.status_code == 200 else "degraded",
                latency_ms=latency_ms,
                details={"url": fhir_url, "http_status": resp.status_code},
            ))
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            results.append(CheckResult(
                name="adapter:fhir", status="unreachable", latency_ms=latency_ms,
                details={"url": fhir_url, "error": str(e)[:120]},
            ))
    else:
        results.append(CheckResult(name="adapter:fhir", status="warning",
                                   details={"note": "TRELLIS_FHIR_ENDPOINT not configured"}))

    return results


# ── Orchestrator ───────────────────────────────────────────────────────────

async def run_all_checks() -> dict[str, Any]:
    """Run ALL health checks (agents + infra). Returns structured result dict."""
    global _last_check_result, _last_check_time

    timestamp = datetime.now(timezone.utc)

    # Run async checks concurrently
    agent_task = asyncio.create_task(run_agent_health_checks())
    llm_task = asyncio.create_task(check_llm_providers())
    db_task = asyncio.create_task(check_database())
    adapter_task = asyncio.create_task(check_adapters())

    agent_checks = await agent_task
    llm_checks = await llm_task
    db_check = await db_task
    adapter_checks = await adapter_task

    # Sync checks
    bg_checks = check_background_tasks()
    smtp_check = check_smtp()
    system_check = check_system()

    # Flatten all CheckResults for persistence
    all_check_results: list[CheckResult] = []
    all_check_results.extend(llm_checks)
    all_check_results.append(db_check)
    all_check_results.extend(bg_checks)
    all_check_results.append(smtp_check)
    all_check_results.append(system_check)
    all_check_results.extend(adapter_checks)

    # Persist to health_checks table
    try:
        async with async_session() as db:
            for cr in all_check_results:
                db.add(HealthCheck(
                    check_name=cr.name,
                    status=cr.status,
                    latency_ms=cr.latency_ms,
                    details=cr.details,
                    timestamp=timestamp,
                ))
            # Also persist agent checks
            for ac in agent_checks:
                db.add(HealthCheck(
                    check_name=f"agent:{ac['agent_id']}",
                    status=ac["status"],
                    latency_ms=ac.get("latency_ms"),
                    details={k: v for k, v in ac.items() if k not in ("agent_id", "status", "latency_ms")},
                    timestamp=timestamp,
                ))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist health checks: {e}")

    # Determine overall status
    all_statuses = [cr.status for cr in all_check_results] + [ac["status"] for ac in agent_checks]
    if "unreachable" in all_statuses:
        overall = "unhealthy"
    elif "degraded" in all_statuses or "warning" in all_statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    # Agent summary
    agent_summary = {
        "total": len(agent_checks),
        "healthy": sum(1 for c in agent_checks if c["status"] == "healthy"),
        "degraded": sum(1 for c in agent_checks if c["status"] == "degraded"),
        "unreachable": sum(1 for c in agent_checks if c["status"] == "unreachable"),
    }

    result = {
        "status": overall,
        "timestamp": timestamp.isoformat(),
        "agents": {"summary": agent_summary, "checks": agent_checks},
        "llm_providers": [asdict(c) for c in llm_checks],
        "database": asdict(db_check),
        "background_tasks": [asdict(c) for c in bg_checks],
        "smtp": asdict(smtp_check),
        "system": asdict(system_check),
        "adapters": [asdict(c) for c in adapter_checks],
    }

    _last_check_result = result
    _last_check_time = timestamp
    return result


# ── Background Loop ────────────────────────────────────────────────────────

async def health_auditor_loop(interval: float | None = None) -> None:
    """Background loop — runs forever, checking health periodically."""
    if interval is None:
        interval = float(os.environ.get("TRELLIS_HEALTH_CHECK_INTERVAL", 60))

    while True:
        try:
            record_task_heartbeat("health_auditor")
            result = await run_all_checks()
            logger.info(f"Health audit complete: {result['status']} — "
                        f"{result['agents']['summary']['total']} agents, "
                        f"{len(result['llm_providers'])} providers")
        except Exception as e:
            logger.error(f"Health auditor loop error: {e}")
        await asyncio.sleep(interval)


# ── Native Agent Class ─────────────────────────────────────────────────────

class HealthAuditorAgent:
    """Native agent — returns on-demand health report when triggered via envelope."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        result = await run_all_checks()
        summary = result["agents"]["summary"]
        issues = [c for c in result["agents"]["checks"] if c["status"] in ("degraded", "unreachable")]
        issue_text = ""
        if issues:
            parts = [f"{c['agent_id']}: {c['status']}" for c in issues]
            issue_text = " (" + "; ".join(parts) + ")"

        text = (
            f"Health Report: {summary['total']} agents — "
            f"{summary['healthy']} healthy, {summary['degraded']} degraded, "
            f"{summary['unreachable']} unreachable{issue_text}. "
            f"Overall: {result['status']}"
        )

        return {
            "status": "completed",
            "result": {"text": text, "data": {"report": result}, "attachments": []},
        }


# ── API Router ─────────────────────────────────────────────────────────────

health_auditor_router = APIRouter(prefix="/health", tags=["health-auditor"])


class HealthQuickResponse(BaseModel):
    status: str
    timestamp: str | None = None
    agents: dict | None = None


class HealthCheckRecord(BaseModel):
    id: int
    check_name: str
    status: str
    latency_ms: float | None = None
    details: dict = {}
    timestamp: str


@health_auditor_router.get("", response_model=HealthQuickResponse)
async def health_quick():
    """Quick health status — returns cached last run or runs a fresh check."""
    global _last_check_result, _last_check_time
    if _last_check_result and _last_check_time:
        return HealthQuickResponse(
            status=_last_check_result["status"],
            timestamp=_last_check_result["timestamp"],
            agents=_last_check_result["agents"]["summary"],
        )
    # No cached result — run a fresh check
    result = await run_all_checks()
    return HealthQuickResponse(
        status=result["status"],
        timestamp=result["timestamp"],
        agents=result["agents"]["summary"],
    )


@health_auditor_router.get("/detailed")
async def health_detailed():
    """Run all checks now and return full results."""
    return await run_all_checks()


@health_auditor_router.get("/history", response_model=list[HealthCheckRecord])
async def health_history(
    check_name: str | None = Query(None, description="Filter by check name"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Recent health check results from database."""
    q = select(HealthCheck).order_by(HealthCheck.timestamp.desc()).limit(limit)
    if check_name:
        q = q.where(HealthCheck.check_name == check_name)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        HealthCheckRecord(
            id=r.id, check_name=r.check_name, status=r.status,
            latency_ms=r.latency_ms, details=r.details or {},
            timestamp=r.timestamp.isoformat() if r.timestamp else "",
        )
        for r in rows
    ]
