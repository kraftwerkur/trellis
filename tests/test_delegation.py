"""Tests for the agent-to-agent delegation protocol."""

import asyncio
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trellis.database import Base, engine
from trellis.models import Agent, AuditEvent
from trellis.delegation import DelegationEngine, DelegationRequest, DelegationResult


# ── Fixtures ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def _session_factory():
    """Yield a fresh async session from the shared test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def seed_agents():
    """Create two test agents and clean tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with _session_factory() as db:
        db.add(Agent(
            agent_id="agent-a", name="Agent A", owner="test",
            department="eng", framework="http", agent_type="http",
            endpoint="http://a.local/run",
        ))
        db.add(Agent(
            agent_id="agent-b", name="Agent B", owner="test",
            department="eng", framework="http", agent_type="http",
            endpoint="http://b.local/run",
        ))
        db.add(Agent(
            agent_id="agent-c", name="Agent C", owner="test",
            department="ops", framework="http", agent_type="http",
            endpoint="http://c.local/run",
        ))
        await db.commit()


def _make_engine(dispatch_fn=None):
    """Helper — builds a DelegationEngine with an optional mock dispatch."""
    mock_dispatch = dispatch_fn or AsyncMock(return_value={"answer": 42})
    return DelegationEngine(
        db_session_factory=_session_factory,
        router_dispatch_fn=mock_dispatch,
    ), mock_dispatch


# ── Tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_basic_delegation(seed_agents):
    """Agent A delegates to Agent B — success path."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "summarise"},
    )

    result = await eng.delegate(req)

    assert result.status == "completed"
    assert result.from_agent == "agent-a"
    assert result.to_agent == "agent-b"
    assert result.result == {"answer": 42}
    assert result.hop_count == 1
    assert result.error is None
    mock_dispatch.assert_awaited_once()

    # Verify the envelope passed to dispatch has delegation metadata
    call_envelope = mock_dispatch.call_args[0][0]
    assert call_envelope["delegated_by"] == "agent-a"
    assert "agent-a" in call_envelope["delegation_chain"]


@pytest.mark.asyncio
async def test_max_hops_exceeded(seed_agents):
    """Delegation rejected when hop_count >= max_hops."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "deep"},
        max_hops=3,
        hop_count=3,
    )

    result = await eng.delegate(req)

    assert result.status == "rejected"
    assert "max hops exceeded" in result.error
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_self_delegation_rejected(seed_agents):
    """Agent cannot delegate to itself."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-a",
        envelope={"task": "loop"},
    )

    result = await eng.delegate(req)

    assert result.status == "rejected"
    assert "self-delegation" in result.error
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_circular_delegation_detected(seed_agents):
    """A→B→A detected via delegation_chain."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-b",
        to_agent="agent-a",
        envelope={"task": "circle"},
        delegation_chain=["agent-a"],  # A already in chain
        hop_count=1,
    )

    result = await eng.delegate(req)

    assert result.status == "rejected"
    assert "circular delegation" in result.error
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_events_emitted(seed_agents):
    """Delegation emits start and complete audit events."""
    eng, _ = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "audit-me"},
        parent_trace_id="trace-123",
    )

    await eng.delegate(req)

    async with _session_factory() as db:
        events = (await db.execute(
            select(AuditEvent).where(AuditEvent.trace_id == "trace-123")
            .order_by(AuditEvent.id)
        )).scalars().all()

    event_types = [e.event_type for e in events]
    assert "delegation.start" in event_types
    assert "delegation.complete" in event_types


@pytest.mark.asyncio
async def test_audit_event_on_rejection(seed_agents):
    """Rejected delegation still emits an audit event."""
    eng, _ = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-a",
        envelope={"task": "self"},
        parent_trace_id="trace-rej",
    )

    await eng.delegate(req)

    async with _session_factory() as db:
        events = (await db.execute(
            select(AuditEvent).where(AuditEvent.trace_id == "trace-rej")
        )).scalars().all()

    assert any(e.event_type == "delegation.rejected" for e in events)


@pytest.mark.asyncio
async def test_fire_and_forget_mode(seed_agents):
    """fire_and_forget returns immediately with envelope_id."""
    dispatch_called = asyncio.Event()

    async def slow_dispatch(envelope, agent, db):
        dispatch_called.set()
        return {"done": True}

    eng, _ = _make_engine(dispatch_fn=slow_dispatch)
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "background"},
        callback_mode="fire_and_forget",
    )

    result = await eng.delegate(req)

    assert result.status == "completed"
    assert result.result.get("fire_and_forget") is True
    assert "envelope_id" in result.result

    # Give background task a moment to run
    await asyncio.sleep(0.15)
    assert dispatch_called.is_set()


@pytest.mark.asyncio
async def test_delegation_with_context(seed_agents):
    """Context from parent is passed through to the delegation envelope."""
    eng, mock_dispatch = _make_engine()
    ctx = {"user_id": "u-42", "priority": "high"}
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "contextual"},
        context=ctx,
    )

    await eng.delegate(req)

    call_envelope = mock_dispatch.call_args[0][0]
    assert call_envelope["delegation_context"] == ctx


@pytest.mark.asyncio
async def test_target_agent_not_found(seed_agents):
    """Delegation to non-existent agent is rejected."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-z",
        envelope={"task": "nowhere"},
    )

    result = await eng.delegate(req)

    assert result.status == "rejected"
    assert "not found" in result.error
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_failure_returns_failed(seed_agents):
    """If dispatch raises, result status is 'failed'."""
    async def boom(envelope, agent, db):
        raise RuntimeError("downstream exploded")

    eng, _ = _make_engine(dispatch_fn=boom)
    req = DelegationRequest(
        from_agent="agent-a",
        to_agent="agent-b",
        envelope={"task": "crash"},
        parent_trace_id="trace-fail",
    )

    result = await eng.delegate(req)

    assert result.status == "failed"
    assert "downstream exploded" in result.error

    # Check failed audit event
    async with _session_factory() as db:
        events = (await db.execute(
            select(AuditEvent).where(AuditEvent.trace_id == "trace-fail")
        )).scalars().all()
    assert any(e.event_type == "delegation.failed" for e in events)


@pytest.mark.asyncio
async def test_delegation_chain_tracking(seed_agents):
    """Chain grows as delegation progresses."""
    eng, mock_dispatch = _make_engine()
    req = DelegationRequest(
        from_agent="agent-b",
        to_agent="agent-c",
        envelope={"task": "chain"},
        delegation_chain=["agent-a"],
        hop_count=1,
    )

    await eng.delegate(req)

    call_envelope = mock_dispatch.call_args[0][0]
    assert call_envelope["delegation_chain"] == ["agent-a", "agent-b"]
    assert call_envelope["delegation_hop"] == 2


@pytest.mark.asyncio
async def test_validate_delegation_public(seed_agents):
    """validate_delegation() returns bool."""
    eng, _ = _make_engine()

    valid = await eng.validate_delegation(DelegationRequest(
        from_agent="agent-a", to_agent="agent-b", envelope={},
    ))
    assert valid is True

    invalid = await eng.validate_delegation(DelegationRequest(
        from_agent="agent-a", to_agent="agent-a", envelope={},
    ))
    assert invalid is False
