"""Tests filling coverage gaps: model router, agent CRUD edge cases, audit filtering, cost endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.gateway import classify_complexity, resolve_model_and_provider
from trellis.main import app
from trellis.schemas import ChatCompletionRequest, ChatMessage


async def _register_agent(client: AsyncClient, agent_id: str = "mock-echo", department: str = "IT"):
    resp = await client.post("/api/agents", json={
        "agent_id": agent_id,
        "name": f"Agent {agent_id}",
        "owner": "test",
        "department": department,
        "framework": "mock",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    return resp


async def _create_key(client: AsyncClient, agent_id: str = "mock-echo", **kwargs):
    resp = await client.post("/api/keys", json={
        "agent_id": agent_id,
        "name": f"{agent_id}-key",
        **kwargs,
    })
    return resp.json()


# === Model Router Unit Tests ===

class TestModelRouter:
    def test_classify_simple(self):
        req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="Hi")])
        assert classify_complexity(req) == "simple"

    def test_classify_complex_keyword(self):
        req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="Please analyze the trade-offs between these approaches")])
        assert classify_complexity(req) == "complex"

    def test_classify_medium_with_tools(self):
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Look up the weather")],
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )
        assert classify_complexity(req) == "medium"

    def test_resolve_auto_model(self):
        """When model is 'auto', complexity classification drives model selection."""
        from unittest.mock import MagicMock
        api_key = MagicMock()
        api_key.preferred_provider = None
        api_key.default_model = None
        req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="Hi")])
        model, provider, complexity = resolve_model_and_provider("auto", api_key, req)
        assert complexity == "simple"
        assert model == "qwen3.5:9b"

    def test_resolve_explicit_model(self):
        from unittest.mock import MagicMock
        api_key = MagicMock()
        api_key.preferred_provider = None
        req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="Hi")])
        model, provider, complexity = resolve_model_and_provider("qwen3.5:9b", api_key, req)
        assert complexity is None
        assert model == "qwen3.5:9b"

    def test_resolve_none_model(self):
        from unittest.mock import MagicMock
        api_key = MagicMock()
        api_key.preferred_provider = None
        api_key.default_model = None
        req = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Analyze and compare the reasoning behind these multi-step approaches step by step" * 20)],
        )
        model, provider, complexity = resolve_model_and_provider(None, api_key, req)
        assert complexity == "complex"


# === Agent CRUD Edge Cases ===

class TestAgentCRUD:
    async def test_get_nonexistent_agent(self, client):
        resp = await client.get("/api/agents/nonexistent")
        assert resp.status_code == 404

    async def test_delete_agent(self, client):
        await _register_agent(client, "to-delete")
        resp = await client.delete("/api/agents/to-delete")
        assert resp.status_code == 204
        resp = await client.get("/api/agents/to-delete")
        assert resp.status_code == 404

    async def test_update_agent(self, client):
        await _register_agent(client, "to-update")
        resp = await client.put("/api/agents/to-update", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_list_agents(self, client):
        await _register_agent(client, "agent-a")
        await _register_agent(client, "agent-b")
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        ids = [a["agent_id"] for a in resp.json()]
        assert "agent-a" in ids
        assert "agent-b" in ids

    async def test_duplicate_agent_id(self, client):
        await _register_agent(client, "dupe")
        resp = await _register_agent(client, "dupe")
        # Should fail with conflict or error
        assert resp.status_code in (400, 409, 500)


# === Audit Filtering ===

class TestAuditFiltering:
    async def test_audit_filter_by_agent_id(self, client):
        await _register_agent(client, "audit-agent")
        key_data = await _create_key(client, "audit-agent")
        # Generate some audit events via gateway call (will fail but still audits)
        await client.post("/v1/chat/completions",
            headers={"Authorization": f"Bearer {key_data['key']}"},
            json={"model": "qwen3.5:9b", "messages": [{"role": "user", "content": "test"}]},
        )
        resp = await client.get("/api/audit", params={"agent_id": "audit-agent"})
        assert resp.status_code == 200
        events = resp.json()
        # All returned events should be for this agent
        for e in events:
            if e.get("agent_id"):
                assert e["agent_id"] == "audit-agent"

    async def test_audit_with_limit(self, client):
        resp = await client.get("/api/audit", params={"limit": 5})
        assert resp.status_code == 200
        assert len(resp.json()) <= 5


# === Cost Endpoints Edge Cases ===

class TestCostEndpoints:
    async def test_cost_timeseries_week(self, client):
        resp = await client.get("/api/costs/timeseries", params={"granularity": "week"})
        assert resp.status_code == 200

    async def test_cost_by_department_empty(self, client):
        resp = await client.get("/api/costs/by-department")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_cost_by_department_detail_empty(self, client):
        resp = await client.get("/api/costs/by-department/NonExistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["department"] == "NonExistent"
        assert data["agents"] == []

    async def test_cost_trace_empty(self, client):
        resp = await client.get("/api/costs/trace/nonexistent-trace")
        assert resp.status_code == 200
        assert resp.json()["event_count"] == 0

    async def test_costs_list_empty(self, client):
        resp = await client.get("/api/costs")
        assert resp.status_code == 200
        assert resp.json() == []


# === Rule CRUD Edge Cases ===

class TestRuleCRUD:
    async def test_get_nonexistent_rule(self, client):
        resp = await client.get("/api/rules/99999")
        assert resp.status_code == 404

    async def test_delete_rule(self, client):
        create = await client.post("/api/rules", json={
            "name": "temp-rule", "priority": 50,
            "conditions": {"source_type": "api"},
            "actions": {"route_to": "test"},
        })
        rule_id = create.json()["id"]
        resp = await client.delete(f"/api/rules/{rule_id}")
        assert resp.status_code == 204

    async def test_update_rule(self, client):
        create = await client.post("/api/rules", json={
            "name": "update-me", "priority": 50,
            "conditions": {"source_type": "api"},
            "actions": {"route_to": "test"},
        })
        rule_id = create.json()["id"]
        resp = await client.put(f"/api/rules/{rule_id}", json={"name": "updated-name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "updated-name"


# === Health Endpoint ===

class TestHealth:
    async def test_root_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    async def test_api_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
