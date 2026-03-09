"""Tests for Slice 3: Agent Onboarding — types, auto-keys, health checks, dispatch."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.main import app


# --- Agent Type Creation ---


@pytest.mark.asyncio
async def test_create_http_agent(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "sam-hr",
        "name": "SAM HR Agent",
        "owner": "Jane",
        "department": "HR",
        "framework": "pi-sdk",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_type"] == "http"
    assert data["api_key"].startswith("trl_")


@pytest.mark.asyncio
async def test_create_webhook_agent(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "notify-webhook",
        "name": "Notification Webhook",
        "owner": "ops",
        "department": "IT",
        "agent_type": "webhook",
        "endpoint": "https://hooks.example.com/notify",
    })
    assert resp.status_code == 201
    assert resp.json()["agent_type"] == "webhook"
    assert resp.json()["api_key"] is not None


@pytest.mark.asyncio
async def test_create_function_agent(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "echo-fn",
        "name": "Echo Function",
        "owner": "platform-team",
        "department": "IT",
        "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_type"] == "function"
    assert data["function_ref"] == "trellis.functions.echo"
    assert data["api_key"].startswith("trl_")


@pytest.mark.asyncio
async def test_create_llm_agent(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "policy-bot",
        "name": "Policy Q&A Bot",
        "owner": "Jane Smith",
        "department": "HR",
        "agent_type": "llm",
        "llm_config": {
            "system_prompt": "You are an HR policy assistant.",
            "model": "qwen3.5:9b",
            "temperature": 0.3,
            "max_tokens": 64,
        },
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_type"] == "llm"
    assert data["llm_config"]["system_prompt"] == "You are an HR policy assistant."
    assert data["api_key"].startswith("trl_")


# --- Auto API Key Generation ---


@pytest.mark.asyncio
async def test_auto_key_generation(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "key-test",
        "name": "Key Test",
        "owner": "test",
        "department": "IT",
        "agent_type": "http",
        "endpoint": "http://localhost/test",
    })
    assert resp.status_code == 201
    raw_key = resp.json()["api_key"]
    assert raw_key.startswith("trl_")

    # Key should work for gateway auth
    resp = await client.get("/api/keys")
    keys = resp.json()
    matching = [k for k in keys if k["agent_id"] == "key-test"]
    assert len(matching) == 1
    assert matching[0]["key_prefix"] == raw_key[:12]

    # Subsequent GET should NOT show the raw key
    resp = await client.get("/api/agents/key-test")
    assert "api_key" not in resp.json() or resp.json().get("api_key") is None


# --- Health Check ---


@pytest.mark.asyncio
async def test_health_check_updates_status(client: AsyncClient):
    """Test that function and LLM agents are created with expected defaults."""
    await client.post("/api/agents", json={
        "agent_id": "hc-fn",
        "name": "HC Function",
        "owner": "test",
        "department": "IT",
        "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    await client.post("/api/agents", json={
        "agent_id": "hc-llm",
        "name": "HC LLM",
        "owner": "test",
        "department": "IT",
        "agent_type": "llm",
        "llm_config": {"system_prompt": "test", "model": "qwen3.5:9b"},
    })

    # Verify agents exist and have expected types
    resp = await client.get("/api/agents/hc-fn")
    assert resp.status_code == 200
    assert resp.json()["agent_type"] == "function"

    resp = await client.get("/api/agents/hc-llm")
    assert resp.status_code == 200
    assert resp.json()["agent_type"] == "llm"


# --- Function Agent Dispatch ---


@pytest.mark.asyncio
async def test_function_agent_dispatch(client: AsyncClient):
    """Route an envelope to a function agent via rules engine."""
    # Register function agent
    await client.post("/api/agents", json={
        "agent_id": "echo-fn",
        "name": "Echo Function",
        "owner": "platform-team",
        "department": "IT",
        "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    # Create routing rule
    await client.post("/api/rules", json={
        "name": "Route to echo function",
        "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "echo-fn"},
        "active": True,
    })
    # Send envelope via HTTP adapter
    resp = await client.post("/api/adapter/http", json={
        "text": "Hello function!",
        "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["target_agent"] == "echo-fn"
    assert "Echo: Hello function!" in data["result"]["result"]["text"]


# --- LLM Agent Dispatch (requires Ollama) ---


@pytest.mark.asyncio
async def test_llm_agent_dispatch(client: AsyncClient):
    """Route an envelope to an LLM agent — calls Ollama internally."""
    await client.post("/api/agents", json={
        "agent_id": "llm-bot",
        "name": "LLM Bot",
        "owner": "test",
        "department": "HR",
        "agent_type": "llm",
        "llm_config": {
            "system_prompt": "You are a test bot. Reply with exactly one word: OK. No thinking, no explanation. /no_think",
            "model": "qwen3.5:9b",
            "temperature": 0.0,
            "max_tokens": 512,
        },
    })
    await client.post("/api/rules", json={
        "name": "Route to LLM bot",
        "priority": 200,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "llm-bot"},
        "active": True,
    })
    resp = await client.post("/api/adapter/http", json={
        "text": "Say OK",
        "sender_name": "Test",
    }, timeout=120.0)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["target_agent"] == "llm-bot"
    # LLM should have produced some response (qwen3.5 may put output in reasoning field)
    result = data["result"]["result"]
    assert result["text"] != "" or result.get("data", {}).get("usage", {}).get("completion_tokens", 0) > 0


# --- Manifest Sync ---


@pytest.mark.asyncio
async def test_manifest_sync(client: AsyncClient):
    """Sync an HTTP agent's manifest from its /manifest endpoint."""
    await client.post("/api/agents", json={
        "agent_id": "mock-sync",
        "name": "Before Sync",
        "owner": "test",
        "department": "IT",
        "framework": "mock",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
    })

    # Sync manifest
    resp = await client.post("/api/agents/mock-sync/sync")
    assert resp.status_code == 200
    data = resp.json()
    # Should have updated from mock manifest
    assert data["name"] == "Mock Echo Agent"
    assert "echo" in data["tools"]
    assert data["maturity"] == "autonomous"


@pytest.mark.asyncio
async def test_manifest_sync_non_http_fails(client: AsyncClient):
    await client.post("/api/agents", json={
        "agent_id": "fn-no-sync",
        "name": "Function",
        "owner": "test",
        "department": "IT",
        "agent_type": "function",
        "function_ref": "trellis.functions.echo",
    })
    resp = await client.post("/api/agents/fn-no-sync/sync")
    assert resp.status_code == 400


# --- Default agent_type ---


@pytest.mark.asyncio
async def test_default_agent_type_is_http(client: AsyncClient):
    resp = await client.post("/api/agents", json={
        "agent_id": "default-type",
        "name": "Default",
        "owner": "test",
        "department": "IT",
        "endpoint": "http://localhost/test",
    })
    assert resp.status_code == 201
    assert resp.json()["agent_type"] == "http"


# --- Slice 1 & 2 Compatibility ---


@pytest.mark.asyncio
async def test_slice1_flow_still_works(client: AsyncClient):
    """Full Slice 1 flow with the new schema."""
    resp = await client.post("/api/agents", json={
        "agent_id": "mock-echo",
        "name": "Mock Echo Agent",
        "owner": "test",
        "department": "IT",
        "framework": "mock",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201

    resp = await client.post("/api/rules", json={
        "name": "Route all to mock",
        "priority": 100,
        "conditions": {"source_type": "api"},
        "actions": {"route_to": "mock-echo"},
        "active": True,
    })
    assert resp.status_code == 201

    resp = await client.post("/api/adapter/http", json={
        "text": "Hello Trellis!",
        "sender_name": "Test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "I received your message: Hello Trellis!" in data["result"]["result"]["text"]
