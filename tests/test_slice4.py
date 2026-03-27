"""Tests for Slice 4: Enhanced Rules Engine + Audit."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.router import _match_condition, _resolve_field, _SENTINEL, match_envelope, match_envelope_all
from trellis.main import app
from trellis.models import Rule
from trellis.schemas import Envelope


class TestConditionOperators:
    """Test new condition operators in isolation."""

    def test_gt(self):
        assert _match_condition(10, {"$gt": 5}) is True
        assert _match_condition(5, {"$gt": 5}) is False
        assert _match_condition(3, {"$gt": 5}) is False

    def test_gte(self):
        assert _match_condition(5, {"$gte": 5}) is True
        assert _match_condition(6, {"$gte": 5}) is True
        assert _match_condition(4, {"$gte": 5}) is False

    def test_lt(self):
        assert _match_condition(3, {"$lt": 5}) is True
        assert _match_condition(5, {"$lt": 5}) is False

    def test_lte(self):
        assert _match_condition(5, {"$lte": 5}) is True
        assert _match_condition(4, {"$lte": 5}) is True
        assert _match_condition(6, {"$lte": 5}) is False

    def test_exists_true(self):
        assert _match_condition("hello", {"$exists": True}) is True
        assert _match_condition(_SENTINEL, {"$exists": True}) is False

    def test_exists_false(self):
        assert _match_condition(_SENTINEL, {"$exists": False}) is True
        assert _match_condition("hello", {"$exists": False}) is False

    def test_regex(self):
        assert _match_condition("ADT^A01", {"$regex": r"^ADT\^A0[12]$"}) is True
        assert _match_condition("ORM^O01", {"$regex": r"^ADT"}) is False
        assert _match_condition(123, {"$regex": r"\d+"}) is False  # non-string

    def test_not(self):
        assert _match_condition("api", {"$not": "teams"}) is True
        assert _match_condition("teams", {"$not": "teams"}) is False
        assert _match_condition(10, {"$not": {"$lt": 5}}) is True
        assert _match_condition(3, {"$not": {"$lt": 5}}) is False

    def test_contains(self):
        assert _match_condition("hello world", {"$contains": "world"}) is True
        assert _match_condition("hello", {"$contains": "world"}) is False
        assert _match_condition(123, {"$contains": "12"}) is False  # non-string

    def test_in_still_works(self):
        assert _match_condition("high", {"$in": ["high", "critical"]}) is True
        assert _match_condition("low", {"$in": ["high", "critical"]}) is False

    def test_equality_still_works(self):
        assert _match_condition("api", "api") is True
        assert _match_condition("api", "teams") is False

    def test_combined_operators(self):
        """Multiple operators in one condition dict — all must match."""
        assert _match_condition(10, {"$gt": 5, "$lt": 15}) is True
        assert _match_condition(20, {"$gt": 5, "$lt": 15}) is False


class TestResolveField:
    def test_nested(self):
        data = {"a": {"b": {"c": 42}}}
        assert _resolve_field(data, "a.b.c") == 42

    def test_missing(self):
        data = {"a": {"b": 1}}
        assert _resolve_field(data, "a.c") is _SENTINEL


# ============================================================
# Fan-out Routing
# ============================================================


def _make_rule(id, name, conditions, actions, priority=100, active=True, fan_out=False):
    r = Rule(id=id, name=name, conditions=conditions, actions=actions,
             priority=priority, active=active, fan_out=fan_out)
    return r


class TestFanOut:
    def test_single_match_no_fanout(self):
        rules = [
            _make_rule(1, "R1", {"source_type": "api"}, {"route_to": "a1"}),
            _make_rule(2, "R2", {"source_type": "api"}, {"route_to": "a2"}),
        ]
        env = Envelope(source_type="api")
        matched = match_envelope_all(env, rules)
        assert len(matched) == 1
        assert matched[0].actions["route_to"] == "a1"

    def test_fanout_both_match(self):
        rules = [
            _make_rule(1, "R1", {"source_type": "api"}, {"route_to": "a1"}, fan_out=True),
            _make_rule(2, "R2", {"source_type": "api"}, {"route_to": "a2"}, fan_out=True),
        ]
        env = Envelope(source_type="api")
        matched = match_envelope_all(env, rules)
        assert len(matched) == 2

    def test_fanout_mixed(self):
        """Fan-out rules + one non-fan-out rule."""
        rules = [
            _make_rule(1, "Fan1", {"source_type": "api"}, {"route_to": "audit-agent"}, fan_out=True, priority=50),
            _make_rule(2, "Normal", {"source_type": "api"}, {"route_to": "main-agent"}, fan_out=False, priority=100),
            _make_rule(3, "Normal2", {"source_type": "api"}, {"route_to": "backup-agent"}, fan_out=False, priority=200),
        ]
        env = Envelope(source_type="api")
        matched = match_envelope_all(env, rules)
        assert len(matched) == 2
        targets = {r.actions["route_to"] for r in matched}
        assert targets == {"audit-agent", "main-agent"}

    def test_backward_compat_match_envelope(self):
        """Original match_envelope still returns first match only."""
        rules = [
            _make_rule(1, "R1", {"source_type": "api"}, {"route_to": "a1"}),
            _make_rule(2, "R2", {"source_type": "api"}, {"route_to": "a2"}),
        ]
        env = Envelope(source_type="api")
        result = match_envelope(env, rules)
        assert result is not None
        assert result.actions["route_to"] == "a1"


# ============================================================
# API Tests
# ============================================================


@pytest.mark.asyncio
async def test_rule_toggle(client: AsyncClient):
    """PUT /api/rules/{id}/toggle flips active status."""
    resp = await client.post("/api/rules", json={
        "name": "Toggle test",
        "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "x"},
        "active": True,
    })
    assert resp.status_code == 201
    rule_id = resp.json()["id"]
    assert resp.json()["active"] is True

    # Toggle off
    resp = await client.put(f"/api/rules/{rule_id}/toggle")
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    # Toggle on
    resp = await client.put(f"/api/rules/{rule_id}/toggle")
    assert resp.status_code == 200
    assert resp.json()["active"] is True


@pytest.mark.asyncio
async def test_rule_toggle_not_found(client: AsyncClient):
    resp = await client.put("/api/rules/9999/toggle")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rule_test_endpoint(client: AsyncClient):
    """POST /api/rules/test returns matched rules without dispatching."""
    await client.post("/api/rules", json={
        "name": "API rule",
        "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "agent-a"},
    })
    await client.post("/api/rules", json={
        "name": "Teams rule",
        "priority": 100,
        "conditions": {"source_type": "teams"},
        "actions": {"route_to": "agent-b"},
    })

    resp = await client.post("/api/rules/test", json={
        "envelope": {"source_type": "api", "payload": {"text": "hello"}},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["matched_rules"]) == 1
    assert data["matched_rules"][0]["name"] == "API rule"


@pytest.mark.asyncio
async def test_rule_test_no_match(client: AsyncClient):
    resp = await client.post("/api/rules/test", json={
        "envelope": {"source_type": "unknown"},
    })
    assert resp.status_code == 200
    assert len(resp.json()["matched_rules"]) == 0


@pytest.mark.asyncio
async def test_fan_out_dispatch(client: AsyncClient):
    """Fan-out routing dispatches to multiple agents."""
    # Register two agents
    await client.post("/api/agents", json={
        "agent_id": "echo-1", "name": "Echo 1", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/agents", json={
        "agent_id": "echo-2", "name": "Echo 2", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })

    # Create two fan-out rules
    await client.post("/api/rules", json={
        "name": "Fan to echo-1", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "echo-1"},
        "fan_out": True,
    })
    await client.post("/api/rules", json={
        "name": "Fan to echo-2", "priority": 200,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "echo-2"},
        "fan_out": True,
    })

    resp = await client.post("/api/adapter/http", json={
        "text": "Fan out test", "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "fan_out"
    assert len(data["dispatches"]) == 2
    targets = {d["target_agent"] for d in data["dispatches"]}
    assert targets == {"echo-1", "echo-2"}


@pytest.mark.asyncio
async def test_fan_out_field_in_schema(client: AsyncClient):
    """fan_out field is returned in rule reads."""
    resp = await client.post("/api/rules", json={
        "name": "Fan rule", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "x"},
        "fan_out": True,
    })
    assert resp.status_code == 201
    assert resp.json()["fan_out"] is True


# ============================================================
# Audit Events
# ============================================================


@pytest.mark.asyncio
async def test_audit_events_emitted_on_dispatch(client: AsyncClient):
    """Dispatching an envelope creates audit events."""
    await client.post("/api/agents", json={
        "agent_id": "audit-echo", "name": "Audit Echo", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/rules", json={
        "name": "Route for audit", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "audit-echo"},
    })

    resp = await client.post("/api/adapter/http", json={
        "text": "Audit test", "sender_name": "Test",
    })
    assert resp.status_code == 200

    # Query audit events
    resp = await client.get("/api/audit")
    assert resp.status_code == 200
    events = resp.json()
    event_types = [e["event_type"] for e in events]
    assert "envelope_received" in event_types
    assert "rule_matched" in event_types
    assert "agent_dispatched" in event_types
    assert "agent_responded" in event_types


@pytest.mark.asyncio
async def test_audit_trace_chain(client: AsyncClient):
    """GET /api/audit/trace/{trace_id} returns full chain."""
    await client.post("/api/agents", json={
        "agent_id": "trace-echo", "name": "Trace Echo", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/rules", json={
        "name": "Trace rule", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "trace-echo"},
    })

    # Send envelope with known trace_id
    resp = await client.post("/api/envelopes", json={
        "source_type": "api",
        "payload": {"text": "trace test"},
        "metadata": {"trace_id": "test-trace-123"},
    })
    assert resp.status_code == 200

    # Query trace
    resp = await client.get("/api/audit/trace/test-trace-123")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 3  # envelope_received, rule_matched, agent_dispatched, agent_responded
    # All events should have the same trace_id
    for e in events:
        assert e["trace_id"] == "test-trace-123"
    # Events should be in chronological order
    types = [e["event_type"] for e in events]
    assert types[0] == "envelope_received"


@pytest.mark.asyncio
async def test_audit_filter_by_event_type(client: AsyncClient):
    """Filter audit events by event_type."""
    # Create an agent to generate audit events
    await client.post("/api/agents", json={
        "agent_id": "filter-test", "name": "Filter", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })

    resp = await client.get("/api/audit", params={"event_type": "agent_registered"})
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    assert all(e["event_type"] == "agent_registered" for e in events)


@pytest.mark.asyncio
async def test_audit_on_key_creation(client: AsyncClient):
    """Key creation emits key_created audit event."""
    await client.post("/api/agents", json={
        "agent_id": "key-audit", "name": "Key Audit", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/keys", json={
        "agent_id": "key-audit", "name": "manual-key",
    })

    resp = await client.get("/api/audit", params={"event_type": "key_created"})
    assert resp.status_code == 200
    events = resp.json()
    # At least 2: one auto from agent creation, one manual
    assert len(events) >= 2


@pytest.mark.asyncio
async def test_audit_on_key_revocation(client: AsyncClient):
    """Key revocation emits key_revoked audit event."""
    await client.post("/api/agents", json={
        "agent_id": "revoke-audit", "name": "Revoke", "owner": "test", "department": "IT",
        "agent_type": "function", "function_ref": "trellis.functions.echo",
    })
    # Get the auto-created key
    resp = await client.get("/api/keys")
    keys = [k for k in resp.json() if k["agent_id"] == "revoke-audit"]
    assert len(keys) >= 1

    await client.delete(f"/api/keys/{keys[0]['id']}")

    resp = await client.get("/api/audit", params={"event_type": "key_revoked"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_audit_on_rule_change(client: AsyncClient):
    """Rule CRUD emits rule_changed audit events."""
    resp = await client.post("/api/rules", json={
        "name": "Audit rule", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "x"},
    })
    rule_id = resp.json()["id"]

    await client.put(f"/api/rules/{rule_id}", json={"priority": 50})
    await client.put(f"/api/rules/{rule_id}/toggle")
    await client.delete(f"/api/rules/{rule_id}")

    resp = await client.get("/api/audit", params={"event_type": "rule_changed"})
    assert resp.status_code == 200
    events = resp.json()
    actions = [e["details"]["action"] for e in events]
    assert "created" in actions
    assert "updated" in actions
    assert "toggled" in actions
    assert "deleted" in actions


# ============================================================
# Backward Compatibility
# ============================================================


@pytest.mark.asyncio
async def test_slice1_flow_still_works(client: AsyncClient):
    """Full Slice 1 flow still works with Slice 4 changes."""
    resp = await client.post("/api/agents", json={
        "agent_id": "mock-echo", "name": "Mock Echo Agent", "owner": "test",
        "department": "IT", "framework": "mock",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201

    resp = await client.post("/api/rules", json={
        "name": "Route all to mock", "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "mock-echo"},
    })
    assert resp.status_code == 201

    resp = await client.post("/api/adapter/http", json={
        "text": "Hello Trellis!", "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "I received your message: Hello Trellis!" in data["result"]["result"]["text"]
