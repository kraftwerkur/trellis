"""Tests for the LLM Observatory module."""

import pytest
from datetime import datetime, timedelta, timezone

from trellis.models import Agent, ApiKey, CostEvent
from trellis.gateway import hash_key
from trellis.database import async_session


# ── Helpers ────────────────────────────────────────────────────────────────

async def _seed_agent(db):
    """Create a test agent + API key."""
    agent = Agent(
        agent_id="obs-test-agent",
        name="Observatory Test Agent",
        owner="test",
        department="IT",
        framework="test",
        agent_type="http",
        status="healthy",
    )
    db.add(agent)

    key = ApiKey(
        key_hash=hash_key("obs-test-key-123"),
        key_prefix="obs-test-ke",
        agent_id="obs-test-agent",
        name="obs-test-key",
    )
    db.add(key)
    await db.commit()


async def _seed_cost_events(db, events: list[dict]):
    """Insert CostEvent rows from dicts."""
    for e in events:
        ce = CostEvent(
            agent_id=e.get("agent_id", "obs-test-agent"),
            model_requested=e.get("model_requested", e.get("model_used", "qwen3.5:9b")),
            model_used=e.get("model_used", "qwen3.5:9b"),
            provider=e.get("provider", "ollama"),
            tokens_in=e.get("tokens_in", 100),
            tokens_out=e.get("tokens_out", 50),
            cost_usd=e.get("cost_usd", 0.0),
            latency_ms=e.get("latency_ms", 200),
            has_tool_calls=e.get("has_tool_calls", False),
            complexity_class=e.get("complexity_class", None),
            timestamp=e.get("timestamp", datetime.now(timezone.utc)),
            trace_id=e.get("trace_id", None),
        )
        db.add(ce)
    await db.commit()


# ── Test: GET /api/observatory/models ──────────────────────────────────────

@pytest.mark.asyncio
async def test_models_empty(client):
    """No data — should return empty list."""
    resp = await client.get("/api/observatory/models")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_models_with_data(client):
    """Seed some events and check model listing."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 500, "tokens_out": 200, "cost_usd": 0.005, "latency_ms": 300},
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 400, "tokens_out": 150, "cost_usd": 0.004, "latency_ms": 250},
            {"model_used": "qwen3.5:9b", "provider": "ollama", "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.0, "latency_ms": 100},
        ])

    resp = await client.get("/api/observatory/models")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    # Sorted by request count desc — gpt-4o has 2, qwen has 1
    assert data[0]["model"] == "gpt-4o"
    assert data[0]["total_requests"] == 2
    assert data[0]["total_tokens_in"] == 900
    assert data[0]["total_tokens_out"] == 350
    assert data[0]["error_rate"] == 0.0

    assert data[1]["model"] == "qwen3.5:9b"
    assert data[1]["total_requests"] == 1


@pytest.mark.asyncio
async def test_models_with_errors(client):
    """Error events (tokens_in=-1) should show up in error_rate."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 500, "tokens_out": 200, "cost_usd": 0.005, "latency_ms": 300},
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": -1, "tokens_out": 0, "cost_usd": 0.0, "latency_ms": 100, "complexity_class": "error:timeout"},
        ])

    resp = await client.get("/api/observatory/models")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["total_requests"] == 2
    assert data[0]["total_errors"] == 1
    assert data[0]["error_rate"] == 0.5


@pytest.mark.asyncio
async def test_models_hours_filter(client):
    """Events outside the lookback window should be excluded."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=48)
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 200, "timestamp": old_time},
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 200},  # recent
        ])

    # Default 24h — should only see 1
    resp = await client.get("/api/observatory/models?hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["total_requests"] == 1

    # 72h — should see both
    resp = await client.get("/api/observatory/models?hours=72")
    data = resp.json()
    assert data[0]["total_requests"] == 2


# ── Test: GET /api/observatory/models/{model_id}/metrics ───────────────────

@pytest.mark.asyncio
async def test_model_metrics_not_found(client):
    """Unknown model should 404."""
    resp = await client.get("/api/observatory/models/nonexistent/metrics")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_model_metrics_latency(client):
    """Check latency distribution calculation."""
    async with async_session() as db:
        await _seed_agent(db)
        # 10 events with known latencies
        events = [
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": lat, "cost_usd": 0.001}
            for lat in [100, 150, 200, 250, 300, 350, 400, 450, 500, 1000]
        ]
        await _seed_cost_events(db, events)

    resp = await client.get("/api/observatory/models/gpt-4o/metrics")
    assert resp.status_code == 200
    data = resp.json()

    assert data["model"] == "gpt-4o"
    assert data["total_requests"] == 10
    assert data["total_errors"] == 0
    assert data["latency"]["min"] == 100
    assert data["latency"]["max"] == 1000
    assert data["latency"]["p50"] > 0
    assert data["latency"]["p95"] >= data["latency"]["p50"]
    assert data["latency"]["p99"] >= data["latency"]["p95"]


@pytest.mark.asyncio
async def test_model_metrics_token_efficiency(client):
    """Check token efficiency calculation."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 800, "tokens_out": 200, "latency_ms": 200},
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 600, "tokens_out": 400, "latency_ms": 300},
        ])

    resp = await client.get("/api/observatory/models/gpt-4o/metrics")
    data = resp.json()

    eff = data["token_efficiency"]
    assert eff["avg_tokens_in"] == 700.0
    assert eff["avg_tokens_out"] == 300.0
    assert eff["avg_total_tokens"] == 1000.0
    # output_ratio = 600 / 2000 = 0.3
    assert eff["output_ratio"] == 0.3


@pytest.mark.asyncio
async def test_model_metrics_hourly_breakdown(client):
    """Hourly breakdown should have entries."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 200, "cost_usd": 0.001},
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 300, "cost_usd": 0.002},
        ])

    resp = await client.get("/api/observatory/models/gpt-4o/metrics")
    data = resp.json()
    assert len(data["hourly_breakdown"]) >= 1
    hour = data["hourly_breakdown"][0]
    assert "hour" in hour
    assert "total_requests" in hour
    assert "errors" in hour
    assert "avg_latency_ms" in hour
    assert "cost_usd" in hour


@pytest.mark.asyncio
async def test_model_metrics_with_errors(client):
    """Errors should be counted but not affect latency/token stats."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 500, "tokens_out": 200, "latency_ms": 300, "cost_usd": 0.005},
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": -1, "tokens_out": 0, "latency_ms": 50, "cost_usd": 0.0, "complexity_class": "error:timeout"},
        ])

    resp = await client.get("/api/observatory/models/gpt-4o/metrics")
    data = resp.json()
    assert data["total_requests"] == 2
    assert data["total_errors"] == 1
    assert data["error_rate"] == 0.5
    # Latency should only reflect the successful call
    assert data["latency"]["avg"] == 300.0
    # Token efficiency should only reflect the successful call
    assert data["token_efficiency"]["avg_tokens_in"] == 500.0


# ── Test: GET /api/observatory/summary ─────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_empty(client):
    """Empty DB should return zeroes."""
    resp = await client.get("/api/observatory/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_requests"] == 0
    assert data["total_errors"] == 0
    assert data["total_cost_usd"] == 0.0
    assert data["unique_models"] == 0
    assert data["unique_agents"] == 0


@pytest.mark.asyncio
async def test_summary_with_data(client):
    """Summary should aggregate across all models."""
    async with async_session() as db:
        await _seed_agent(db)
        # Also create a second agent
        agent2 = Agent(
            agent_id="obs-test-agent-2", name="Agent 2", owner="test",
            department="HR", framework="test", agent_type="http", status="healthy",
        )
        db.add(agent2)
        await db.commit()

        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": 500, "tokens_out": 200, "cost_usd": 0.005, "latency_ms": 300},
            {"model_used": "gpt-4o-mini", "provider": "openai", "tokens_in": 200, "tokens_out": 100, "cost_usd": 0.001, "latency_ms": 150},
            {"model_used": "qwen3.5:9b", "provider": "ollama", "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.0, "latency_ms": 80, "agent_id": "obs-test-agent-2"},
            # Error event
            {"model_used": "gpt-4o", "provider": "openai", "tokens_in": -1, "tokens_out": 0, "cost_usd": 0.0, "latency_ms": 50, "complexity_class": "error:500"},
        ])

    resp = await client.get("/api/observatory/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_requests"] == 4
    assert data["total_errors"] == 1
    assert data["overall_error_rate"] == 0.25
    assert data["total_cost_usd"] == 0.006
    assert data["unique_models"] == 3
    assert data["unique_agents"] == 2
    assert data["period_hours"] == 24
    assert len(data["top_models_by_requests"]) <= 5
    assert len(data["top_models_by_cost"]) <= 5
    assert data["avg_latency_ms"] > 0


@pytest.mark.asyncio
async def test_summary_hours_filter(client):
    """Hours param should filter old events."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=48)
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 200, "cost_usd": 0.001, "timestamp": old_time},
            {"model_used": "gpt-4o", "provider": "openai", "latency_ms": 200, "cost_usd": 0.002},
        ])

    resp = await client.get("/api/observatory/summary?hours=24")
    data = resp.json()
    assert data["total_requests"] == 1
    assert data["total_cost_usd"] == 0.002

    resp = await client.get("/api/observatory/summary?hours=72")
    data = resp.json()
    assert data["total_requests"] == 2


# ── Test: record_llm_error ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_llm_error(client):
    """record_llm_error should create a CostEvent with error sentinel."""
    from trellis.observatory import record_llm_error

    async with async_session() as db:
        await _seed_agent(db)
        event = await record_llm_error(
            db,
            agent_id="obs-test-agent",
            model_requested="gpt-4o",
            model_used="gpt-4o",
            provider="openai",
            error_type="TimeoutError",
            latency_ms=5000,
        )

    assert event.tokens_in == -1
    assert event.cost_usd == 0.0
    assert event.complexity_class == "error:TimeoutError"
    assert event.latency_ms == 5000

    # Should show up in models endpoint
    resp = await client.get("/api/observatory/models")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["total_errors"] == 1
    assert data[0]["error_rate"] == 1.0


# ── Test: cost-per-useful-response ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_avg_cost_per_request(client):
    """avg_cost_per_request in metrics should reflect cost / requests."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "cost_usd": 0.01, "latency_ms": 200},
            {"model_used": "gpt-4o", "provider": "openai", "cost_usd": 0.03, "latency_ms": 300},
        ])

    resp = await client.get("/api/observatory/models/gpt-4o/metrics")
    data = resp.json()
    # avg = 0.04 / 2 = 0.02
    assert data["avg_cost_per_request"] == 0.02


# ── Test: path parameter with slashes (NVIDIA models) ─────────────────────

@pytest.mark.asyncio
async def test_model_id_with_slashes(client):
    """Model IDs like 'meta/llama-3.3-70b-instruct' should work."""
    async with async_session() as db:
        await _seed_agent(db)
        await _seed_cost_events(db, [
            {"model_used": "meta/llama-3.3-70b-instruct", "provider": "nvidia", "latency_ms": 500, "cost_usd": 0.001},
        ])

    resp = await client.get("/api/observatory/models/meta/llama-3.3-70b-instruct/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "meta/llama-3.3-70b-instruct"


# ── Test: multiple agents per model ────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_agents_same_model(client):
    """Summary unique_agents should count distinct agents."""
    async with async_session() as db:
        await _seed_agent(db)
        agent2 = Agent(
            agent_id="obs-agent-2", name="Agent 2", owner="test",
            department="HR", framework="test", agent_type="http", status="healthy",
        )
        db.add(agent2)
        await db.commit()
        await _seed_cost_events(db, [
            {"model_used": "gpt-4o", "provider": "openai", "agent_id": "obs-test-agent", "latency_ms": 200},
            {"model_used": "gpt-4o", "provider": "openai", "agent_id": "obs-agent-2", "latency_ms": 300},
        ])

    resp = await client.get("/api/observatory/summary")
    data = resp.json()
    assert data["unique_agents"] == 2
    assert data["unique_models"] == 1
