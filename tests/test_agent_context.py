"""Tests for AgentContext runtime context."""

import pytest
from sqlalchemy import select

from trellis.agent_context import AgentContext
from trellis.database import Base, engine, async_session
from trellis.models import AuditEvent


@pytest.fixture(autouse=True)
async def _setup_tables():
    """Ensure tables exist and are clean for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_context_creation():
    """AgentContext can be created with all required fields."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="test-agent",
            trace_id="trace-001",
            envelope={"envelope_id": "env-1", "source_type": "test"},
            db=db,
        )
        assert ctx.agent_id == "test-agent"
        assert ctx.trace_id == "trace-001"
        assert ctx.envelope == {"envelope_id": "env-1", "source_type": "test"}
        assert ctx.db is db
        assert ctx.memory == {}
        assert ctx.logger is not None


@pytest.mark.asyncio
async def test_emit_event_writes_to_db():
    """emit_event() creates an AuditEvent row in the database."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="audit-agent",
            trace_id="trace-002",
            envelope={"envelope_id": "env-2"},
            db=db,
        )
        event = await ctx.emit_event("test_event", details={"foo": "bar"})

        assert event.id is not None
        assert event.event_type == "test_event"
        assert event.agent_id == "audit-agent"
        assert event.trace_id == "trace-002"
        assert event.envelope_id == "env-2"
        assert event.details == {"foo": "bar"}

        # Verify it's actually in the DB
        result = await db.execute(
            select(AuditEvent).where(AuditEvent.id == event.id)
        )
        row = result.scalar_one()
        assert row.event_type == "test_event"


@pytest.mark.asyncio
async def test_delegate_works():
    """delegate() routes to DelegationEngine and returns a result."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="del-agent",
            trace_id="trace-003",
            envelope={"envelope_id": "env-3"},
            db=db,
        )
        result = await ctx.delegate("it-help", text="Server is down", context={"description": "Server is down", "severity": "high"})
        assert result["status"] in ("completed", "error")
        assert "delegation_id" in result


@pytest.mark.asyncio
async def test_async_context_manager():
    """AgentContext works as an async context manager and clears memory on exit."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="ctx-agent",
            trace_id="trace-004",
            envelope={"envelope_id": "env-4"},
            db=db,
        )

        async with ctx as c:
            assert c is ctx
            c.memory["scratch"] = "value"
            assert c.memory["scratch"] == "value"

        # Memory should be cleared after exiting
        assert ctx.memory == {}


@pytest.mark.asyncio
async def test_emit_event_without_details():
    """emit_event() works without explicit details (defaults to empty dict)."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="simple-agent",
            trace_id="trace-005",
            envelope={"envelope_id": "env-5"},
            db=db,
        )
        event = await ctx.emit_event("simple_event")
        assert event.details == {}


@pytest.mark.asyncio
async def test_tools_property():
    """tools property returns the tool registry."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="tool-agent",
            trace_id="trace-006",
            envelope={},
            db=db,
        )
        registry = ctx.tools
        assert registry is not None


@pytest.mark.asyncio
async def test_llm_property():
    """llm property returns a proxy with chat_completion method."""
    async with async_session() as db:
        ctx = AgentContext(
            agent_id="llm-agent",
            trace_id="trace-007",
            envelope={},
            db=db,
        )
        proxy = ctx.llm
        assert hasattr(proxy, "chat_completion")
