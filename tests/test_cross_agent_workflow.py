"""Tests for SecurityTriage → ITHelp cross-agent delegation workflow."""

import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:////tmp/test_trellis.db")

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from trellis.database import Base
from trellis.models import AuditEvent
from trellis.agents.security_triage import SecurityTriageAgent
from trellis.agent_context import AgentContext


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session for delegation tests."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _mock_llm_call(content="Risk assessment: CRITICAL vulnerability found in CISA KEV."):
    """Create a mock LLM callable that returns a fixed response."""
    async def llm_call(messages, tools=None, model="default", temperature=0.7):
        return {
            "choices": [{"message": {"content": content, "role": "assistant"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
    return llm_call


def _mock_kev_found(cve_id: str) -> dict:
    """Mock check_cisa_kev that always returns found."""
    return {
        "found": True,
        "cve_id": cve_id,
        "vulnerability": {
            "cveID": cve_id,
            "shortDescription": f"Test vulnerability {cve_id}",
            "requiredAction": "Apply patches immediately",
            "dueDate": "2025-01-01",
        },
    }


def _mock_kev_not_found(cve_id: str) -> dict:
    """Mock check_cisa_kev that always returns not found."""
    return {"found": False, "cve_id": cve_id}


# ── Tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_security_triage_delegates_to_it_help_on_critical(db_session):
    """When a CVE is in KEV (CRITICAL), SecurityTriage delegates to ITHelp and gets a ticket_id."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call())

    envelope = {
        "envelope_id": "env-test-001",
        "body": {"text": "Critical vulnerability CVE-2024-12345 detected in production."},
    }
    trace_id = "trace-xagent-001"

    with patch("trellis.agents.security_triage.check_cisa_kev", side_effect=_mock_kev_found):
        result = await agent.execute(envelope, db=db_session, trace_id=trace_id)

    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert data["risk_level"] == "CRITICAL"
    assert data["any_in_kev"] is True

    # Delegation should have produced a ticket_id
    assert "ticket_id" in data, f"Expected ticket_id in result data, got keys: {list(data.keys())}"
    assert data["ticket_id"].startswith("TRL-") or data["ticket_id"].startswith("INC-")

    # Delegation ID should be present
    assert "delegation_id" in data
    assert data["delegation_id"].startswith("del-")


@pytest.mark.asyncio
async def test_delegation_creates_audit_events(db_session):
    """Delegation should emit delegation_requested and delegation_completed audit events."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call())

    envelope = {
        "envelope_id": "env-test-002",
        "body": {"text": "Vuln alert: CVE-2024-99999 is actively exploited."},
    }
    trace_id = "trace-audit-002"

    with patch("trellis.agents.security_triage.check_cisa_kev", side_effect=_mock_kev_found):
        result = await agent.execute(envelope, db=db_session, trace_id=trace_id)
        await db_session.commit()

    # Query audit events
    stmt = select(AuditEvent).where(AuditEvent.trace_id == trace_id)
    events = (await db_session.execute(stmt)).scalars().all()
    event_types = [e.event_type for e in events]

    assert "delegation_requested" in event_types, f"Expected delegation_requested, got {event_types}"
    assert "delegation_completed" in event_types, f"Expected delegation_completed, got {event_types}"

    # Check delegation_requested details
    req_event = next(e for e in events if e.event_type == "delegation_requested")
    assert req_event.details["to_agent"] == "it-help"
    assert req_event.agent_id == "security-triage"


@pytest.mark.asyncio
async def test_delegation_failure_does_not_break_triage(db_session):
    """If delegation to ITHelp fails, triage should still return successfully."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call())

    envelope = {
        "envelope_id": "env-test-003",
        "body": {"text": "CVE-2024-55555 found in critical system."},
    }
    trace_id = "trace-fail-003"

    def _kev_found_with_bad_data(cve_id):
        return _mock_kev_found(cve_id)

    # Patch delegation engine to raise an error
    with patch("trellis.agents.security_triage.check_cisa_kev", side_effect=_kev_found_with_bad_data):
        with patch("trellis.agent_context.AgentContext.delegate", side_effect=RuntimeError("delegation exploded")):
            result = await agent.execute(envelope, db=db_session, trace_id=trace_id)

    # Triage should still complete successfully
    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert data["risk_level"] == "CRITICAL"
    assert data["any_in_kev"] is True
    # No ticket_id since delegation failed
    assert "ticket_id" not in data


@pytest.mark.asyncio
async def test_no_delegation_without_db_and_trace():
    """Without db and trace_id, no delegation should be attempted."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call())

    envelope = {
        "body": {"text": "CVE-2024-77777 found."},
    }

    with patch("trellis.agents.security_triage.check_cisa_kev", side_effect=_mock_kev_found):
        result = await agent.execute(envelope)  # no db, no trace_id

    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert data["risk_level"] == "CRITICAL"
    # No delegation attempted → no ticket_id
    assert "ticket_id" not in data


@pytest.mark.asyncio
async def test_no_delegation_for_non_critical(db_session):
    """Non-CRITICAL CVEs should not trigger delegation."""
    agent = SecurityTriageAgent(llm_call=_mock_llm_call("Low risk assessment."))

    envelope = {
        "envelope_id": "env-test-005",
        "body": {"text": "CVE-2024-00001 found in staging system."},
    }
    trace_id = "trace-medium-005"

    with patch("trellis.agents.security_triage.check_cisa_kev", side_effect=_mock_kev_not_found):
        result = await agent.execute(envelope, db=db_session, trace_id=trace_id)

    assert result["status"] == "completed"
    data = result["result"]["data"]
    assert data["risk_level"] == "MEDIUM"
    assert "ticket_id" not in data


@pytest.mark.asyncio
async def test_agent_context_delegate_method(db_session):
    """Test AgentContext.delegate() directly."""
    ctx = AgentContext(
        agent_id="test-agent",
        trace_id="trace-ctx-001",
        envelope={"envelope_id": "env-ctx-001"},
        db=db_session,
    )

    # Delegate to it-help
    result = await ctx.delegate(
        to_agent="it-help",
        text="Server down in production",
        context={
            "description": "Server down in production",
            "severity": "high",
            "ticket_id": "TRL-CTX001",
        },
    )

    assert result["status"] == "completed"
    assert result["delegation_id"].startswith("del-")
    assert result["error"] is None

    # Check audit events were emitted
    await db_session.commit()
    stmt = select(AuditEvent).where(AuditEvent.trace_id == "trace-ctx-001")
    events = (await db_session.execute(stmt)).scalars().all()
    event_types = [e.event_type for e in events]
    assert "delegation_requested" in event_types
    assert "delegation_completed" in event_types


@pytest.mark.asyncio
async def test_agent_context_delegate_unknown_agent(db_session):
    """Delegating to an unknown agent returns an error result."""
    ctx = AgentContext(
        agent_id="test-agent",
        trace_id="trace-ctx-002",
        envelope={"envelope_id": "env-ctx-002"},
        db=db_session,
    )

    result = await ctx.delegate(
        to_agent="nonexistent-agent",
        text="This should fail gracefully",
    )

    assert result["status"] == "error"
    assert "nonexistent-agent" in result["error"]
