"""Tests for the Health Auditor — comprehensive infrastructure health monitoring."""

import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/test_trellis.db"

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.main import app
from trellis.database import Base, engine, async_session
from trellis.models import Agent, HealthCheck
from trellis.router import set_client_override


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        set_client_override(c)
        yield c
        set_client_override(None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, checkfirst=True)


async def _seed_agent(agent_id="test-agent", agent_type="http", health_endpoint="http://test/mock-agent/health"):
    async with async_session() as db:
        db.add(Agent(
            agent_id=agent_id, name="Test Agent", owner="test",
            department="IT", framework="test", agent_type=agent_type,
            health_endpoint=health_endpoint, status="unknown",
        ))
        await db.commit()


# ── API Endpoint Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_quick_returns_status(client):
    """GET /api/health should return a status."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")


@pytest.mark.asyncio
async def test_health_detailed_returns_all_sections(client):
    """GET /api/health/detailed should return all check categories."""
    resp = await client.get("/api/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "timestamp" in data
    assert "agents" in data
    assert "llm_providers" in data
    assert "database" in data
    assert "background_tasks" in data
    assert "smtp" in data
    assert "system" in data
    assert "adapters" in data


@pytest.mark.asyncio
async def test_health_detailed_persists_to_db(client):
    """Detailed check should persist results to health_checks table."""
    resp = await client.get("/api/health/detailed")
    assert resp.status_code == 200

    # Query health_checks table
    from sqlalchemy import select, func
    async with async_session() as db:
        count = await db.execute(select(func.count()).select_from(HealthCheck))
        n = count.scalar()
    assert n > 0, "Health checks should be persisted to DB"


@pytest.mark.asyncio
async def test_health_history_returns_records(client):
    """GET /api/health/history should return persisted check records."""
    # Run a detailed check first to populate
    await client.get("/api/health/detailed")

    resp = await client.get("/api/health/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    record = data[0]
    assert "check_name" in record
    assert "status" in record
    assert "timestamp" in record


@pytest.mark.asyncio
async def test_health_history_filter_by_name(client):
    """GET /api/health/history?check_name=database should filter."""
    await client.get("/api/health/detailed")

    resp = await client.get("/api/health/history?check_name=database")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["check_name"] == "database" for r in data)


@pytest.mark.asyncio
async def test_health_history_limit(client):
    """GET /api/health/history?limit=2 should respect limit."""
    await client.get("/api/health/detailed")

    resp = await client.get("/api/health/history?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 2


# ── Agent Health Check Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_native_agent_always_healthy(client):
    """Native agents should always report healthy (no health endpoint)."""
    from trellis.agents.health_auditor import check_one_agent
    agent = MagicMock()
    agent.agent_id = "native-1"
    agent.agent_type = "native"
    result = await check_one_agent(agent)
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_function_agent_no_endpoint_healthy(client):
    """Function agents without health endpoint should be healthy."""
    from trellis.agents.health_auditor import check_one_agent
    agent = MagicMock()
    agent.agent_id = "func-1"
    agent.agent_type = "function"
    agent.health_endpoint = None
    result = await check_one_agent(agent)
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_agent_unreachable_on_connection_error(client):
    """Agent should be marked unreachable if health endpoint fails."""
    from trellis.agents.health_auditor import check_one_agent
    agent = MagicMock()
    agent.agent_id = "bad-agent"
    agent.agent_type = "http"
    agent.health_endpoint = "http://localhost:99999/health"  # bad port
    result = await check_one_agent(agent)
    assert result["status"] == "unreachable"


# ── Infrastructure Check Tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_database_check_healthy(client):
    """Database check should return healthy for test DB."""
    from trellis.agents.health_auditor import check_database
    result = await check_database()
    assert result.status == "healthy"
    assert result.details.get("integrity") == "ok"


@pytest.mark.asyncio
async def test_background_tasks_warning_no_heartbeat(client):
    """Background tasks with no heartbeat should show warning."""
    from trellis.agents.health_auditor import check_background_tasks, _background_task_heartbeats
    # Clear heartbeats
    _background_task_heartbeats.clear()
    results = check_background_tasks()
    assert len(results) > 0
    assert all(r.status == "warning" for r in results)


@pytest.mark.asyncio
async def test_background_tasks_healthy_after_heartbeat(client):
    """Background task should be healthy after recording heartbeat."""
    from trellis.agents.health_auditor import check_background_tasks, record_task_heartbeat
    record_task_heartbeat("health_auditor")
    results = check_background_tasks()
    ha = [r for r in results if r.name == "task:health_auditor"][0]
    assert ha.status == "healthy"


@pytest.mark.asyncio
async def test_smtp_warning_when_not_configured(client):
    """SMTP check should warn when not configured."""
    from trellis.agents.health_auditor import check_smtp
    with patch.dict(os.environ, {"TRELLIS_SMTP_HOST": ""}, clear=False):
        result = check_smtp()
    assert result.status == "warning"
    assert "not configured" in result.details.get("note", "")


@pytest.mark.asyncio
async def test_system_check_returns_disk_and_memory(client):
    """System check should return disk and memory info."""
    from trellis.agents.health_auditor import check_system
    result = check_system()
    assert result.status in ("healthy", "warning")
    assert "disk_total_gb" in result.details
    assert "disk_free_gb" in result.details


@pytest.mark.asyncio
async def test_adapter_http_always_healthy(client):
    """HTTP adapter should always report healthy (built-in)."""
    from trellis.agents.health_auditor import check_adapters
    results = await check_adapters()
    http_adapter = [r for r in results if r.name == "adapter:http"][0]
    assert http_adapter.status == "healthy"


@pytest.mark.asyncio
async def test_adapter_teams_warning_when_not_configured(client):
    """Teams adapter should warn when TEAMS_APP_ID not set."""
    from trellis.agents.health_auditor import check_adapters
    with patch.dict(os.environ, {"TEAMS_APP_ID": ""}, clear=False):
        results = await check_adapters()
    teams = [r for r in results if r.name == "adapter:teams"][0]
    assert teams.status == "warning"


@pytest.mark.asyncio
async def test_adapter_fhir_warning_when_not_configured(client):
    """FHIR adapter should warn when endpoint not configured."""
    from trellis.agents.health_auditor import check_adapters
    with patch.dict(os.environ, {"TRELLIS_FHIR_ENDPOINT": ""}, clear=False):
        results = await check_adapters()
    fhir = [r for r in results if r.name == "adapter:fhir"][0]
    assert fhir.status == "warning"


# ── HealthAuditorAgent Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_auditor_agent_process(client):
    """HealthAuditorAgent.process should return completed status with report."""
    from trellis.agents.health_auditor import HealthAuditorAgent
    agent = HealthAuditorAgent(agent=MagicMock())
    result = await agent.process(envelope=MagicMock())
    assert result["status"] == "completed"
    assert "Health Report" in result["result"]["text"]
    assert "report" in result["result"]["data"]


# ── Record Task Heartbeat Tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_task_heartbeat(client):
    """record_task_heartbeat should store timestamp."""
    from trellis.agents.health_auditor import record_task_heartbeat, _background_task_heartbeats
    record_task_heartbeat("test_task")
    assert "test_task" in _background_task_heartbeats
    assert isinstance(_background_task_heartbeats["test_task"], datetime)


# ── Integration: Quick endpoint uses cached result ─────────────────────────

@pytest.mark.asyncio
async def test_health_quick_uses_cache_after_detailed(client):
    """After running detailed, quick should return cached result without re-running."""
    # Run detailed first
    resp1 = await client.get("/api/health/detailed")
    assert resp1.status_code == 200

    # Quick should return cached
    resp2 = await client.get("/api/health")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["status"] == resp1.json()["status"]
    assert data["timestamp"] is not None
