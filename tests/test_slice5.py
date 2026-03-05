"""Tests for Slice 5: FinOps Engine."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.router import set_client_override
from trellis.gateway import classify_complexity
from trellis.main import app
from trellis.schemas import ChatCompletionRequest, ChatMessage, ToolDef, ToolFunction


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        set_client_override(c)
        from trellis.database import Base, engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield c
        set_client_override(None)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


async def _create_agent(client, agent_id="test-agent", department="HR"):
    resp = await client.post("/api/agents", json={
        "agent_id": agent_id,
        "name": f"Test Agent ({department})",
        "owner": "test",
        "department": department,
        "framework": "test",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201
    return resp.json()["api_key"]


async def _insert_cost_events(client, agent_id, count=5, cost=0.01, trace_id=None, ts=None):
    """Insert cost events directly via DB."""
    from trellis.database import async_session
    from trellis.models import CostEvent

    async with async_session() as db:
        for i in range(count):
            event = CostEvent(
                trace_id=trace_id or f"trace-{i}",
                agent_id=agent_id,
                model_requested="gpt-4o-mini",
                model_used="gpt-4o-mini",
                provider="openai",
                tokens_in=100,
                tokens_out=50,
                cost_usd=cost,
                latency_ms=100,
                has_tool_calls=False,
                timestamp=ts or datetime.now(timezone.utc),
            )
            db.add(event)
        await db.commit()


# ============================================================
# Complexity Classification
# ============================================================

class TestComplexityClassifier:
    def test_simple_short_message(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="What is PTO?")]
        )
        assert classify_complexity(req) == "simple"

    def test_simple_no_tools(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Hello")]
        )
        assert classify_complexity(req) == "simple"

    def test_medium_with_tools(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Look up employee")],
            tools=[ToolDef(function=ToolFunction(name="lookup", description="Lookup"))],
        )
        assert classify_complexity(req) == "medium"

    def test_medium_moderate_length(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="x " * 500)]
        )
        assert classify_complexity(req) == "medium"

    def test_complex_long_context(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="data " * 2000)]
        )
        assert classify_complexity(req) == "complex"

    def test_complex_multiple_tools(self):
        tools = [
            ToolDef(function=ToolFunction(name=f"tool{i}", description=f"Tool {i}"))
            for i in range(4)
        ]
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Do stuff")],
            tools=tools,
        )
        assert classify_complexity(req) == "complex"

    def test_complex_keywords(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Please analyze the budget data and compare departments")]
        )
        assert classify_complexity(req) == "complex"

    def test_complex_reason_keyword(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Can you reason through this problem step by step?")]
        )
        assert classify_complexity(req) == "complex"


# ============================================================
# Department Cost Rollups
# ============================================================

class TestDepartmentCosts:
    async def test_by_department(self, client):
        await _create_agent(client, "hr-agent", "HR")
        await _create_agent(client, "it-agent", "IT")
        await _insert_cost_events(client, "hr-agent", count=3, cost=0.01)
        await _insert_cost_events(client, "it-agent", count=2, cost=0.05)

        resp = await client.get("/api/costs/by-department")
        assert resp.status_code == 200
        data = resp.json()
        depts = {d["department"]: d for d in data}
        assert "HR" in depts
        assert "IT" in depts
        assert depts["HR"]["request_count"] == 3
        assert depts["IT"]["request_count"] == 2

    async def test_by_department_detail(self, client):
        await _create_agent(client, "hr-agent1", "HR")
        await _create_agent(client, "hr-agent2", "HR")
        await _insert_cost_events(client, "hr-agent1", count=2, cost=0.01)
        await _insert_cost_events(client, "hr-agent2", count=3, cost=0.02)

        resp = await client.get("/api/costs/by-department/HR")
        assert resp.status_code == 200
        data = resp.json()
        assert data["department"] == "HR"
        assert len(data["agents"]) == 2
        assert data["total_cost_usd"] > 0

    async def test_by_department_empty(self, client):
        resp = await client.get("/api/costs/by-department/NonExistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["department"] == "NonExistent"
        assert len(data["agents"]) == 0


# ============================================================
# Trace-Level Cost Aggregation
# ============================================================

class TestTraceCosts:
    async def test_trace_aggregation(self, client):
        await _create_agent(client, "agent-a", "HR")
        await _create_agent(client, "agent-b", "HR")
        trace = "trace-chain-001"
        await _insert_cost_events(client, "agent-a", count=2, cost=0.01, trace_id=trace)
        await _insert_cost_events(client, "agent-b", count=1, cost=0.05, trace_id=trace)

        resp = await client.get(f"/api/costs/trace/{trace}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == trace
        assert data["event_count"] == 3
        assert len(data["agents"]) == 2
        # agent-a: 2 * 0.01 = 0.02, agent-b: 1 * 0.05 = 0.05
        assert abs(data["total_cost_usd"] - 0.07) < 0.001

    async def test_trace_empty(self, client):
        resp = await client.get("/api/costs/trace/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 0
        assert data["total_cost_usd"] == 0.0


# ============================================================
# Time-Series Cost Data
# ============================================================

class TestTimeSeries:
    async def test_timeseries_day(self, client):
        await _create_agent(client, "ts-agent", "IT")
        await _insert_cost_events(client, "ts-agent", count=5, cost=0.01)

        resp = await client.get("/api/costs/timeseries?granularity=day")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["request_count"] >= 5

    async def test_timeseries_hour(self, client):
        await _create_agent(client, "ts-agent", "IT")
        await _insert_cost_events(client, "ts-agent", count=3, cost=0.02)

        resp = await client.get("/api/costs/timeseries?granularity=hour")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_timeseries_with_agent_filter(self, client):
        await _create_agent(client, "ts-a", "IT")
        await _create_agent(client, "ts-b", "HR")
        await _insert_cost_events(client, "ts-a", count=3, cost=0.01)
        await _insert_cost_events(client, "ts-b", count=2, cost=0.05)

        resp = await client.get("/api/costs/timeseries?agent_id=ts-a&granularity=day")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["request_count"] == 3


# ============================================================
# Budget Alerts
# ============================================================

class TestBudgetAlerts:
    async def test_budget_warning_at_80_percent(self, client):
        """When spend reaches 80% of budget, a budget_warning audit event should be emitted."""
        api_key = await _create_agent(client, "budget-agent", "HR")

        # Set a daily budget of $1.00
        from trellis.database import async_session
        from trellis.models import ApiKey
        from trellis.gateway import hash_key
        from sqlalchemy import select

        async with async_session() as db:
            res = await db.execute(
                select(ApiKey).where(ApiKey.key_hash == hash_key(api_key))
            )
            key = res.scalar_one()
            key.budget_daily_usd = 1.00
            await db.commit()

        # Insert cost events worth $0.85 (85% of $1.00)
        await _insert_cost_events(client, "budget-agent", count=1, cost=0.85)

        # Trigger a budget alert check by calling the gateway
        # We'll simulate by calling budget alerts directly
        from trellis.gateway import check_budget_alerts
        async with async_session() as db:
            res = await db.execute(
                select(ApiKey).where(ApiKey.key_hash == hash_key(api_key))
            )
            key = res.scalar_one()
            await check_budget_alerts(db, key)
            await db.commit()

        # Check audit events for budget_warning
        resp = await client.get("/api/audit?event_type=budget_warning")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert events[0]["agent_id"] == "budget-agent"
        assert events[0]["details"]["period"] == "daily"

    async def test_budget_exceeded_audit_event(self, client):
        """When budget is exceeded (429), a budget_exceeded audit event should be emitted."""
        api_key = await _create_agent(client, "exceeded-agent", "HR")

        from trellis.database import async_session
        from trellis.models import ApiKey
        from trellis.gateway import hash_key
        from sqlalchemy import select

        async with async_session() as db:
            res = await db.execute(
                select(ApiKey).where(ApiKey.key_hash == hash_key(api_key))
            )
            key = res.scalar_one()
            key.budget_daily_usd = 0.001
            await db.commit()

        # Insert enough cost to exceed
        await _insert_cost_events(client, "exceeded-agent", count=1, cost=0.01)

        # Try to call gateway — should 429
        resp = await client.post("/v1/chat/completions", json={
            "model": "qwen3:8b",
            "messages": [{"role": "user", "content": "test"}],
        }, headers={"Authorization": f"Bearer {api_key}"})
        assert resp.status_code == 429

        # Check for budget_exceeded audit event
        audit_resp = await client.get("/api/audit?event_type=budget_exceeded&agent_id=exceeded-agent")
        assert audit_resp.status_code == 200
        events = audit_resp.json()
        assert len(events) >= 1


# ============================================================
# Cost Anomaly Detection
# ============================================================

class TestCostAnomaly:
    async def test_anomaly_detected(self, client):
        """A cost 3x above 7-day average should emit cost_anomaly audit event."""
        await _create_agent(client, "anomaly-agent", "IT")

        # Insert historical events with low cost
        await _insert_cost_events(client, "anomaly-agent", count=10, cost=0.001)

        # Check anomaly with a high-cost event
        from trellis.database import async_session
        from trellis.gateway import check_cost_anomaly

        async with async_session() as db:
            detected = await check_cost_anomaly(db, "anomaly-agent", 0.01)  # 10x average
            await db.commit()

        assert detected is True

        # Verify audit event
        resp = await client.get("/api/audit?event_type=cost_anomaly&agent_id=anomaly-agent")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert events[0]["details"]["multiplier"] >= 3.0

    async def test_no_anomaly_normal_cost(self, client):
        """Normal cost should not trigger anomaly."""
        await _create_agent(client, "normal-agent", "IT")
        await _insert_cost_events(client, "normal-agent", count=10, cost=0.01)

        from trellis.database import async_session
        from trellis.gateway import check_cost_anomaly

        async with async_session() as db:
            detected = await check_cost_anomaly(db, "normal-agent", 0.01)
            await db.commit()

        assert detected is False

    async def test_no_anomaly_insufficient_history(self, client):
        """With fewer than 5 historical requests, no anomaly check."""
        await _create_agent(client, "new-agent", "IT")
        await _insert_cost_events(client, "new-agent", count=2, cost=0.001)

        from trellis.database import async_session
        from trellis.gateway import check_cost_anomaly

        async with async_session() as db:
            detected = await check_cost_anomaly(db, "new-agent", 0.1)
            await db.commit()

        assert detected is False


# ============================================================
# FinOps Summary
# ============================================================

class TestFinOpsSummary:
    async def test_summary_basic(self, client):
        await _create_agent(client, "fin-a", "HR")
        await _create_agent(client, "fin-b", "IT")
        await _insert_cost_events(client, "fin-a", count=5, cost=0.01)
        await _insert_cost_events(client, "fin-b", count=3, cost=0.05)

        resp = await client.get("/api/finops/summary")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_requests"] == 8
        assert data["spend_today_usd"] > 0
        assert data["spend_this_week_usd"] > 0
        assert data["spend_this_month_usd"] > 0
        assert data["avg_cost_per_request_usd"] > 0
        assert len(data["top_agents"]) >= 2
        assert len(data["top_departments"]) >= 2

    async def test_summary_empty(self, client):
        resp = await client.get("/api/finops/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0
        assert data["spend_today_usd"] == 0.0


# ============================================================
# Cost Event Schema includes complexity_class
# ============================================================

class TestCostEventSchema:
    async def test_complexity_class_in_response(self, client):
        await _create_agent(client, "schema-agent", "HR")

        from trellis.database import async_session
        from trellis.models import CostEvent

        async with async_session() as db:
            event = CostEvent(
                trace_id="t1",
                agent_id="schema-agent",
                model_requested="auto",
                model_used="qwen3:8b",
                provider="ollama",
                tokens_in=50,
                tokens_out=20,
                cost_usd=0.0,
                latency_ms=100,
                has_tool_calls=False,
                complexity_class="simple",
                timestamp=datetime.now(timezone.utc),
            )
            db.add(event)
            await db.commit()

        resp = await client.get("/api/costs?agent_id=schema-agent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["complexity_class"] == "simple"
