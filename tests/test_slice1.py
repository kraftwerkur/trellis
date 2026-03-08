"""End-to-end test for Slice 1: register agent → create rule → post envelope → verify."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.main import app


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_full_flow(client: AsyncClient):
    # 1. Register mock agent
    resp = await client.post(
        "/api/agents",
        json={
            "agent_id": "mock-echo",
            "name": "Mock Echo Agent",
            "owner": "test",
            "department": "IT",
            "framework": "mock",
            "endpoint": "http://test/mock-agent/envelope",
            "health_endpoint": "http://test/mock-agent/health",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["agent_id"] == "mock-echo"

    # 2. Create routing rule
    resp = await client.post(
        "/api/rules",
        json={
            "name": "Route all to mock",
            "priority": 100,
            "conditions": {"source_type": "api"},
            "actions": {"route_to": "mock-echo"},
            "active": True,
        },
    )
    assert resp.status_code == 201

    # 3. Send via HTTP adapter
    resp = await client.post(
        "/api/adapter/http",
        json={"text": "Hello Trellis!", "sender_name": "Test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["target_agent"] == "mock-echo"
    assert "I received your message: Hello Trellis!" in data["result"]["result"]["text"]

    # 4. Check audit log
    resp = await client.get("/api/envelopes")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert logs[0]["dispatch_status"] == "success"


@pytest.mark.asyncio
async def test_no_matching_rule(client: AsyncClient):
    resp = await client.post(
        "/api/adapter/http",
        json={"text": "No rules exist", "sender_name": "Test"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_match"


@pytest.mark.asyncio
async def test_agent_crud(client: AsyncClient):
    # Create
    resp = await client.post(
        "/api/agents",
        json={
            "agent_id": "test-agent",
            "name": "Test",
            "owner": "me",
            "department": "IT",
            "framework": "test",
            "endpoint": "http://localhost/test",
        },
    )
    assert resp.status_code == 201

    # Read
    resp = await client.get("/api/agents/test-agent")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test"

    # Update
    resp = await client.put("/api/agents/test-agent", json={"name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"

    # List
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Delete
    resp = await client.delete("/api/agents/test-agent")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_rule_crud(client: AsyncClient):
    resp = await client.post(
        "/api/rules",
        json={
            "name": "Test rule",
            "priority": 50,
            "conditions": {"source_type": "teams"},
            "actions": {"route_to": "some-agent"},
        },
    )
    assert resp.status_code == 201
    rule_id = resp.json()["id"]

    resp = await client.get(f"/api/rules/{rule_id}")
    assert resp.status_code == 200

    resp = await client.put(f"/api/rules/{rule_id}", json={"priority": 10})
    assert resp.status_code == 200
    assert resp.json()["priority"] == 10

    resp = await client.delete(f"/api/rules/{rule_id}")
    assert resp.status_code == 204
