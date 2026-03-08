"""Tests for Gateway Management API — providers, model routes, per-agent LLM config."""

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.main import app


async def _create_agent(client, agent_id="test-agent"):
    resp = await client.post("/api/agents", json={
        "agent_id": agent_id,
        "name": "Test Agent",
        "owner": "test",
        "department": "IT",
        "framework": "test",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code == 201
    return resp.json()


# --- Provider listing ---

@pytest.mark.asyncio
async def test_list_providers_returns_all(client):
    resp = await client.get("/api/gateway/providers")
    assert resp.status_code == 200
    providers = resp.json()
    names = {p["name"] for p in providers}
    assert {"ollama", "openai", "anthropic", "groq"}.issubset(names)
    # Ollama should always be configured
    ollama = next(p for p in providers if p["name"] == "ollama")
    assert ollama["configured"] is True
    assert len(ollama["models"]) > 0


@pytest.mark.asyncio
async def test_list_models(client):
    resp = await client.get("/api/gateway/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) > 0
    # Check structure
    m = models[0]
    assert "model" in m
    assert "provider" in m
    assert "available" in m


# --- Gateway stats ---

@pytest.mark.asyncio
async def test_gateway_stats_empty(client):
    resp = await client.get("/api/gateway/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total_requests"] == 0
    assert stats["total_tokens"] == 0
    assert stats["total_cost"] == 0.0


# --- Model routes CRUD ---

@pytest.mark.asyncio
async def test_model_routes_crud(client):
    # List (may be empty in test since lifespan seed doesn't run)
    resp = await client.get("/api/gateway/routes")
    assert resp.status_code == 200

    # Create
    resp = await client.post("/api/gateway/routes", json={
        "model_name": "custom-model:latest",
        "provider": "ollama",
        "cost_per_1k_input": 0.001,
        "cost_per_1k_output": 0.002,
    })
    assert resp.status_code == 201
    route = resp.json()
    assert route["model_name"] == "custom-model:latest"
    assert route["provider"] == "ollama"

    # Duplicate → 409
    resp = await client.post("/api/gateway/routes", json={
        "model_name": "custom-model:latest",
        "provider": "ollama",
    })
    assert resp.status_code == 409

    # Update
    resp = await client.put("/api/gateway/routes/custom-model:latest", json={
        "provider": "groq",
        "active": False,
    })
    assert resp.status_code == 200
    assert resp.json()["provider"] == "groq"
    assert resp.json()["active"] is False

    # Delete
    resp = await client.delete("/api/gateway/routes/custom-model:latest")
    assert resp.status_code == 204

    # Not found
    resp = await client.delete("/api/gateway/routes/nonexistent")
    assert resp.status_code == 404


# --- Table auto-creation on startup ---

@pytest.mark.asyncio
async def test_model_routes_table_created(client):
    """model_routes table should be auto-created by the test fixture (mirrors lifespan)."""
    from trellis.database import engine
    from sqlalchemy import inspect as sa_inspect

    async with engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: sa_inspect(sync_conn).get_table_names()
        )
    assert "model_routes" in table_names


# --- Per-agent LLM config ---

@pytest.mark.asyncio
async def test_agent_llm_config(client):
    agent_data = await _create_agent(client)

    # Get default (empty)
    resp = await client.get("/api/gateway/agents/test-agent/llm-config")
    assert resp.status_code == 200
    config = resp.json()
    assert config["model"] is None

    # Update
    resp = await client.put("/api/gateway/agents/test-agent/llm-config", json={
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.7,
        "max_tokens": 1024,
        "allowed_models": ["llama-3.3-70b-versatile", "qwen3:8b"],
        "preferred_provider": "groq",
    })
    assert resp.status_code == 200
    config = resp.json()
    assert config["model"] == "llama-3.3-70b-versatile"
    assert config["allowed_models"] == ["llama-3.3-70b-versatile", "qwen3:8b"]

    # Read back
    resp = await client.get("/api/gateway/agents/test-agent/llm-config")
    assert resp.status_code == 200
    assert resp.json()["preferred_provider"] == "groq"


@pytest.mark.asyncio
async def test_agent_llm_config_not_found(client):
    resp = await client.get("/api/gateway/agents/nonexistent/llm-config")
    assert resp.status_code == 404


# --- Model allowlist enforcement ---

@pytest.mark.asyncio
async def test_allowlist_enforcement(client):
    """When agent has allowed_models set, disallowed models should be redirected."""
    from trellis.gateway import resolve_model_and_provider_async
    from trellis.models import ApiKey
    from trellis.database import async_session

    agent_data = await _create_agent(client, agent_id="restricted-agent")

    # Set allowed_models
    resp = await client.put("/api/gateway/agents/restricted-agent/llm-config", json={
        "model": "qwen3:8b",
        "allowed_models": ["qwen3:8b", "llama3.1:8b"],
    })
    assert resp.status_code == 200

    # Create a mock ApiKey object
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(ApiKey).where(ApiKey.agent_id == "restricted-agent")
        )
        api_key = result.scalar_one()

        # Request a disallowed model → should get redirected to agent's default
        model, provider, _ = await resolve_model_and_provider_async(
            "gpt-4o", api_key, None
        )
        assert model in ["qwen3:8b", "llama3.1:8b"], f"Expected allowed model, got {model}"
