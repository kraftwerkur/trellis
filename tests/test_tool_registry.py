"""Tests for the Tool Registry — permission checking, audit logging, catalog API."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from trellis.tool_registry import (
    ToolRegistry,
    ToolPermissionDenied,
    ToolNotFound,
    register_tool,
    tool_registry,
)
from trellis.models import Base, ToolCallLog


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def registry():
    """Fresh ToolRegistry for each test."""
    return ToolRegistry()


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session for audit log tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


# ── Tool registration ──────────────────────────────────────────────────────

def test_register_and_lookup(registry):
    def my_tool(x: int) -> int:
        return x * 2

    registry.register(my_tool, name="my_tool", category="data", description="Doubles x")
    meta = registry.get("my_tool")

    assert meta.name == "my_tool"
    assert meta.category == "data"
    assert meta.description == "Doubles x"
    assert meta.fn is my_tool


def test_register_not_found(registry):
    with pytest.raises(ToolNotFound) as exc_info:
        registry.get("nonexistent_tool")
    assert "nonexistent_tool" in str(exc_info.value)


def test_register_decorator_style():
    """Test the @register_tool decorator on the global registry."""
    # Use a unique name to avoid collision with builtin registrations
    @register_tool(name="_test_decorator_tool", category="data", description="Test tool")
    def _test_decorator_tool(val: str) -> str:
        return val.upper()

    meta = tool_registry.get("_test_decorator_tool")
    assert meta.name == "_test_decorator_tool"
    assert meta.fn("hello") == "HELLO"


def test_list_tools_returns_all_builtins():
    """Global registry should have all built-in tools registered."""
    catalog = tool_registry.list_tools()
    names = {t["name"] for t in catalog}
    expected = {
        "lookup_tech_stack", "check_cisa_kev", "get_cvss_details", "calculate_risk_score",
        "classify_ticket", "lookup_known_resolution", "assess_priority",
        "classify_hr_case", "assess_hr_priority", "lookup_hr_policy",
        "classify_rev_cycle_case", "analyze_denial", "assess_rev_cycle_priority",
    }
    assert expected.issubset(names)


def test_list_tools_format(registry):
    def sample(a: str) -> str:
        return a

    registry.register(sample, name="sample", category="classify")
    tools = registry.list_tools()
    assert len(tools) == 1
    t = tools[0]
    assert "name" in t and "category" in t and "call_count" in t and "avg_latency_ms" in t


# ── Permission checking ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_permission_allowed(registry):
    def add(a: int, b: int) -> int:
        return a + b

    registry.register(add, name="add", category="data")
    result = await registry.execute(
        agent_id="agent-1",
        tool_name="add",
        params={"a": 2, "b": 3},
        agent_tools=["add"],
    )
    assert result == 5


@pytest.mark.asyncio
async def test_permission_wildcard(registry):
    def greet(name: str) -> str:
        return f"Hello, {name}"

    registry.register(greet, name="greet", category="data")
    result = await registry.execute(
        agent_id="agent-1",
        tool_name="greet",
        params={"name": "Reef"},
        agent_tools=["*"],
    )
    assert result == "Hello, Reef"


@pytest.mark.asyncio
async def test_permission_denied(registry):
    def secret(x: int) -> int:
        return x

    registry.register(secret, name="secret_tool", category="data")
    with pytest.raises(ToolPermissionDenied) as exc_info:
        await registry.execute(
            agent_id="agent-bad",
            tool_name="secret_tool",
            params={"x": 1},
            agent_tools=["other_tool"],
        )
    assert "agent-bad" in str(exc_info.value)
    assert "secret_tool" in str(exc_info.value)


@pytest.mark.asyncio
async def test_permission_none_skips_check(registry):
    """Passing agent_tools=None skips permission check entirely."""
    def internal(val: str) -> str:
        return val

    registry.register(internal, name="internal_tool", category="data")
    result = await registry.execute(
        agent_id="system",
        tool_name="internal_tool",
        params={"val": "ok"},
        agent_tools=None,  # no check
    )
    assert result == "ok"


# ── Execution with audit logging ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_execution_logs_to_db(registry, db_session):
    def multiply(x: int, y: int) -> int:
        return x * y

    registry.register(multiply, name="multiply", category="assess")
    result = await registry.execute(
        agent_id="agent-test",
        tool_name="multiply",
        params={"x": 4, "y": 5},
        trace_id="trace-001",
        agent_tools=["multiply"],
        db=db_session,
    )
    assert result == 20

    # Check ToolCallLog was persisted
    logs = (await db_session.execute(
        select(ToolCallLog).where(ToolCallLog.tool_name == "multiply")
    )).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.agent_id == "agent-test"
    assert log.trace_id == "trace-001"
    assert log.status == "success"
    assert log.latency_ms is not None
    assert log.tool_category == "assess"


@pytest.mark.asyncio
async def test_execution_error_logged(registry, db_session):
    def boom(x: int) -> int:
        raise ValueError("Kaboom!")

    registry.register(boom, name="boom_tool", category="data")
    result = await registry.execute(
        agent_id="agent-test",
        tool_name="boom_tool",
        params={"x": 1},
        agent_tools=["boom_tool"],
        db=db_session,
    )
    # Registry catches the error and returns structured response
    assert result["status"] == "error"
    assert "Kaboom" in result["error"]

    logs = (await db_session.execute(
        select(ToolCallLog).where(ToolCallLog.tool_name == "boom_tool")
    )).scalars().all()
    assert logs[0].status == "error"
    assert "Kaboom" in logs[0].error


@pytest.mark.asyncio
async def test_call_count_tracks(registry):
    counter = {"n": 0}

    def track() -> int:
        counter["n"] += 1
        return counter["n"]

    registry.register(track, name="track_tool", category="data")
    for _ in range(3):
        await registry.execute(
            agent_id="agent-1", tool_name="track_tool", params={}, agent_tools=["*"]
        )

    meta = registry.get("track_tool")
    assert meta.call_count == 3


# ── /api/tools endpoint tests ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client with DB override."""
    from trellis.main import app
    from trellis.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_tools_endpoint(client):
    resp = await client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 13  # all builtins
    names = {t["name"] for t in data}
    assert "lookup_tech_stack" in names
    assert "classify_ticket" in names


@pytest.mark.asyncio
async def test_get_tool_endpoint(client):
    resp = await client.get("/api/tools/lookup_tech_stack")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "lookup_tech_stack"
    assert data["category"] == "data"
    assert "call_count" in data


@pytest.mark.asyncio
async def test_get_tool_not_found(client):
    resp = await client.get("/api/tools/totally_fake_tool_xyz")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tool_usage_endpoint(client, db_session):
    # Run a real tool call to generate a log entry
    result = await tool_registry.execute(
        agent_id="api-test-agent",
        tool_name="check_cisa_kev",
        params={"cve_id": "CVE-2024-9999"},
        agent_tools=["*"],
        db=db_session,
    )
    assert "cve_id" in result

    resp = await client.get("/api/tools/check_cisa_kev/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # At least one entry
    assert any(r["agent_id"] == "api-test-agent" for r in data)
