"""Tests for the Alerting & Notification Engine."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from trellis.main import app
from trellis.database import Base, engine
from trellis.alerts import (
    evaluate_condition, _in_cooldown, _mark_fired, _mark_resolved,
    _last_fired, _rule_state, fire_alert, fire_alert_event,
)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    _last_fired.clear()
    _rule_state.clear()


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Condition evaluation ──────────────────────────────────────────────────


class TestEvaluateCondition:
    def test_gt(self):
        assert evaluate_condition("gt", 90, 80) is True
        assert evaluate_condition("gt", 80, 80) is False

    def test_lt(self):
        assert evaluate_condition("lt", 70, 80) is True
        assert evaluate_condition("lt", 80, 80) is False

    def test_gte(self):
        assert evaluate_condition("gte", 80, 80) is True
        assert evaluate_condition("gte", 79, 80) is False

    def test_lte(self):
        assert evaluate_condition("lte", 80, 80) is True
        assert evaluate_condition("lte", 81, 80) is False

    def test_eq(self):
        assert evaluate_condition("eq", 80, 80) is True
        assert evaluate_condition("eq", 81, 80) is False

    def test_neq(self):
        assert evaluate_condition("neq", 81, 80) is True
        assert evaluate_condition("neq", 80, 80) is False

    def test_unknown_operator(self):
        assert evaluate_condition("xor", 80, 80) is False


# ── Cooldown / state ──────────────────────────────────────────────────────


class TestCooldownState:
    def test_no_cooldown_initially(self):
        assert _in_cooldown(999, 15) is False

    def test_in_cooldown_after_fire(self):
        _mark_fired(999)
        assert _in_cooldown(999, 15) is True

    def test_not_in_cooldown_with_zero(self):
        _mark_fired(998)
        assert _in_cooldown(998, 0) is False

    def test_resolve_state(self):
        _mark_fired(997)
        assert _rule_state[997] == "firing"
        _mark_resolved(997)
        assert _rule_state[997] == "ok"


# ── CRUD API ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule(client):
    resp = await client.post("/api/alerts/rules", json={
        "name": "Budget > 80%",
        "source": "finops",
        "condition_metric": "budget_pct",
        "condition_operator": "gt",
        "condition_value": "80",
        "channels": ["webhook"],
        "channel_config": {"webhook_url": "https://example.com/hook"},
        "severity": "warning",
        "cooldown_minutes": 15,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Budget > 80%"
    assert data["source"] == "finops"
    assert data["active"] is True
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_list_rules(client):
    await client.post("/api/alerts/rules", json={
        "name": "Rule A", "source": "finops", "condition_metric": "cost",
        "condition_value": "100",
    })
    await client.post("/api/alerts/rules", json={
        "name": "Rule B", "source": "health", "condition_metric": "error_rate",
        "condition_value": "5",
    })
    resp = await client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_rules_filter_source(client):
    await client.post("/api/alerts/rules", json={
        "name": "Rule A", "source": "finops", "condition_metric": "cost",
        "condition_value": "100",
    })
    await client.post("/api/alerts/rules", json={
        "name": "Rule B", "source": "health", "condition_metric": "error_rate",
        "condition_value": "5",
    })
    resp = await client.get("/api/alerts/rules?source=finops")
    assert len(resp.json()) == 1
    assert resp.json()[0]["source"] == "finops"


@pytest.mark.asyncio
async def test_get_rule(client):
    create = await client.post("/api/alerts/rules", json={
        "name": "Test", "source": "custom", "condition_metric": "x",
        "condition_value": "1",
    })
    rule_id = create.json()["id"]
    resp = await client.get(f"/api/alerts/rules/{rule_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test"


@pytest.mark.asyncio
async def test_get_rule_not_found(client):
    resp = await client.get("/api/alerts/rules/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_rule(client):
    create = await client.post("/api/alerts/rules", json={
        "name": "Old Name", "source": "finops", "condition_metric": "cost",
        "condition_value": "100",
    })
    rule_id = create.json()["id"]
    resp = await client.put(f"/api/alerts/rules/{rule_id}", json={
        "name": "New Name", "severity": "critical",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["severity"] == "critical"


@pytest.mark.asyncio
async def test_delete_rule(client):
    create = await client.post("/api/alerts/rules", json={
        "name": "To Delete", "source": "custom", "condition_metric": "x",
        "condition_value": "1",
    })
    rule_id = create.json()["id"]
    resp = await client.delete(f"/api/alerts/rules/{rule_id}")
    assert resp.status_code == 204
    resp2 = await client.get(f"/api/alerts/rules/{rule_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_toggle_rule(client):
    create = await client.post("/api/alerts/rules", json={
        "name": "Toggle Me", "source": "custom", "condition_metric": "x",
        "condition_value": "1",
    })
    rule_id = create.json()["id"]
    assert create.json()["active"] is True
    resp = await client.put(f"/api/alerts/rules/{rule_id}/toggle")
    assert resp.json()["active"] is False
    resp2 = await client.put(f"/api/alerts/rules/{rule_id}/toggle")
    assert resp2.json()["active"] is True


# ── Alert History ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_empty(client):
    resp = await client.get("/api/alerts/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_test_alert(client):
    create = await client.post("/api/alerts/rules", json={
        "name": "Test Alert", "source": "custom", "condition_metric": "x",
        "condition_value": "1", "channels": [],
    })
    rule_id = create.json()["id"]
    resp = await client.post("/api/alerts/test", json={"rule_id": rule_id})
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Should appear in history
    hist = await client.get("/api/alerts/history")
    events = hist.json()
    assert len(events) == 1
    assert events[0]["status"] == "test"


@pytest.mark.asyncio
async def test_test_alert_not_found(client):
    resp = await client.post("/api/alerts/test", json={"rule_id": 99999})
    assert resp.status_code == 404


# ── Summary ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary(client):
    await client.post("/api/alerts/rules", json={
        "name": "R1", "source": "finops", "condition_metric": "cost",
        "condition_value": "100",
    })
    resp = await client.get("/api/alerts/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rules"] == 1
    assert data["active_rules"] == 1


# ── fire_alert engine ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_alert_matches_rule(client):
    # Create a rule
    await client.post("/api/alerts/rules", json={
        "name": "High Cost", "source": "finops", "condition_metric": "budget_pct",
        "condition_operator": "gt", "condition_value": "80",
        "channels": [], "severity": "critical", "cooldown_minutes": 0,
    })
    # Fire alert
    await fire_alert("finops", "budget_pct", 95.0, message="Budget at 95%")

    # Check history
    resp = await client.get("/api/alerts/history")
    events = resp.json()
    assert len(events) == 1
    assert events[0]["status"] == "firing"
    assert events[0]["severity"] == "critical"
    assert "95%" in events[0]["message"]


@pytest.mark.asyncio
async def test_fire_alert_no_match(client):
    await client.post("/api/alerts/rules", json={
        "name": "High Cost", "source": "finops", "condition_metric": "budget_pct",
        "condition_operator": "gt", "condition_value": "80",
        "channels": [], "cooldown_minutes": 0,
    })
    await fire_alert("finops", "budget_pct", 50.0)
    resp = await client.get("/api/alerts/history")
    assert resp.json() == []


@pytest.mark.asyncio
async def test_fire_alert_cooldown(client):
    await client.post("/api/alerts/rules", json={
        "name": "Cooldown Test", "source": "health", "condition_metric": "error_rate",
        "condition_operator": "gt", "condition_value": "5",
        "channels": [], "cooldown_minutes": 60,
    })
    await fire_alert("health", "error_rate", 10.0)
    await fire_alert("health", "error_rate", 15.0)  # should be suppressed

    resp = await client.get("/api/alerts/history")
    assert len(resp.json()) == 1  # only one event, second was suppressed


@pytest.mark.asyncio
async def test_fire_alert_agent_filter(client):
    await client.post("/api/alerts/rules", json={
        "name": "Agent Specific", "source": "health", "condition_metric": "error_rate",
        "condition_operator": "gt", "condition_value": "5",
        "channels": [], "cooldown_minutes": 0, "agent_id_filter": "sam-hr",
    })
    # Should NOT fire for a different agent
    await fire_alert("health", "error_rate", 10.0, agent_id="it-help")
    resp = await client.get("/api/alerts/history")
    assert resp.json() == []

    # Should fire for sam-hr
    await fire_alert("health", "error_rate", 10.0, agent_id="sam-hr")
    resp2 = await client.get("/api/alerts/history")
    assert len(resp2.json()) == 1


@pytest.mark.asyncio
async def test_fire_alert_event(client):
    await client.post("/api/alerts/rules", json={
        "name": "PHI Detected", "source": "phi_shield", "condition_metric": "phi_detected",
        "condition_type": "equals", "condition_value": "true",
        "channels": [], "cooldown_minutes": 0,
    })
    await fire_alert_event("phi_shield", "phi_detected", "PHI found in agent sam-hr", agent_id="sam-hr")

    resp = await client.get("/api/alerts/history")
    events = resp.json()
    assert len(events) == 1
    assert events[0]["agent_id"] == "sam-hr"


@pytest.mark.asyncio
async def test_history_filter_by_severity(client):
    await client.post("/api/alerts/rules", json={
        "name": "R1", "source": "finops", "condition_metric": "cost",
        "condition_operator": "gt", "condition_value": "0",
        "channels": [], "severity": "critical", "cooldown_minutes": 0,
    })
    await client.post("/api/alerts/rules", json={
        "name": "R2", "source": "health", "condition_metric": "latency",
        "condition_operator": "gt", "condition_value": "0",
        "channels": [], "severity": "warning", "cooldown_minutes": 0,
    })
    await fire_alert("finops", "cost", 100.0)
    await fire_alert("health", "latency", 5000.0)

    resp = await client.get("/api/alerts/history?severity=critical")
    assert len(resp.json()) == 1
    assert resp.json()[0]["severity"] == "critical"
