"""Tests for Slice 2: LLM Gateway — auth, proxying, cost tracking, budget caps."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.main import app


async def _register_agent(client: AsyncClient, agent_id: str = "mock-echo"):
    """Register a mock agent in the registry."""
    await client.post(
        "/api/agents",
        json={
            "agent_id": agent_id,
            "name": "Mock Echo Agent",
            "owner": "test",
            "department": "IT",
            "framework": "mock",
            "endpoint": "http://test/mock-agent/envelope",
        },
    )


async def _create_key(client: AsyncClient, agent_id: str = "mock-echo", **kwargs) -> str:
    """Create an API key and return the raw key."""
    body = {"agent_id": agent_id, "name": "test-key", **kwargs}
    resp = await client.post("/api/keys", json=body)
    assert resp.status_code == 201
    return resp.json()["key"]


# --- Key Management ---


@pytest.mark.asyncio
async def test_create_and_list_keys(client: AsyncClient):
    await _register_agent(client)
    raw_key = await _create_key(client)
    assert raw_key.startswith("trl_")

    resp = await client.get("/api/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1  # auto-key from agent creation + manual key
    # Find our manually created key
    manual_key = [k for k in keys if k["key_prefix"] == raw_key[:12]]
    assert len(manual_key) == 1
    assert "key" not in manual_key[0]  # raw key NOT in list


@pytest.mark.asyncio
async def test_revoke_key(client: AsyncClient):
    await _register_agent(client)
    raw_key = await _create_key(client)

    # Revoke ALL keys for this agent so none authenticate
    resp = await client.get("/api/keys")
    for k in resp.json():
        await client.delete(f"/api/keys/{k['id']}")

    # Key should no longer authenticate
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


# --- Authentication ---


@pytest.mark.asyncio
async def test_no_auth_returns_401(client: AsyncClient):
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bad_key_returns_401(client: AsyncClient):
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer trl_bogus_key_12345"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


# --- Gateway Proxy (requires Ollama running locally) ---


@pytest.mark.asyncio
async def test_gateway_proxy_ollama(client: AsyncClient):
    """Proxy a real request to Ollama and verify response + cost logging."""
    await _register_agent(client)
    raw_key = await _create_key(client)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "temperature": 0.0,
            "max_tokens": 32,
        },
        timeout=120.0,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert data["usage"]["total_tokens"] > 0
    assert "X-Trellis-Cost-USD" in resp.headers


# --- Cost Tracking ---


@pytest.mark.asyncio
async def test_cost_events_logged(client: AsyncClient):
    """After a gateway call, cost events should be queryable."""
    await _register_agent(client)
    raw_key = await _create_key(client)

    await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "Say hi"}],
            "max_tokens": 8,
        },
        timeout=120.0,
    )

    resp = await client.get("/api/costs", params={"agent_id": "mock-echo"})
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    assert events[0]["agent_id"] == "mock-echo"
    assert events[0]["provider"] == "ollama"


@pytest.mark.asyncio
async def test_cost_summary(client: AsyncClient):
    """Summary endpoint aggregates costs per agent."""
    await _register_agent(client)
    raw_key = await _create_key(client)

    await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        },
        timeout=120.0,
    )

    resp = await client.get("/api/costs/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert len(summary) >= 1
    assert summary[0]["agent_id"] == "mock-echo"
    assert summary[0]["request_count"] >= 1


# --- Budget Cap Enforcement ---


@pytest.mark.asyncio
async def test_budget_cap_enforcement(client: AsyncClient):
    """Create key with tiny budget, make calls until 429."""
    await _register_agent(client)
    # Budget of $0 — should reject immediately since local models are free
    # Use a non-zero budget but log a fake cost first
    raw_key = await _create_key(client, budget_daily_usd=0.0001)

    # First call — qwen3:8b is free ($0), so it should pass budget check
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        },
        timeout=120.0,
    )
    # Free model = $0 cost, so budget not exceeded
    assert resp.status_code == 200

    # Now manually insert a cost event to simulate spending
    from trellis.database import async_session
    from trellis.gateway import log_cost_event

    async with async_session() as db:
        await log_cost_event(
            db,
            agent_id="mock-echo",
            trace_id=None,
            model_requested="gpt-4o",
            model_used="gpt-4o",
            provider="openai",
            tokens_in=1000,
            tokens_out=1000,
            latency_ms=100,
            has_tool_calls=False,
        )

    # Next call should be rejected (budget exceeded)
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        },
        timeout=120.0,
    )
    assert resp.status_code == 429


# --- Slice 1 Still Works ---


@pytest.mark.asyncio
async def test_slice1_health_still_works(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
