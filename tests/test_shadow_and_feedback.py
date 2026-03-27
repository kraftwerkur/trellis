"""HTTP-layer tests for shadow mode endpoints and the feedback API endpoint."""

import pytest
from httpx import AsyncClient


async def _register_agent_with_intake(client: AsyncClient, agent_id: str, categories: list[str]):
    """Register an agent and set its intake declaration."""
    resp = await client.post("/api/agents", json={
        "agent_id": agent_id,
        "name": f"Agent {agent_id}",
        "owner": "test",
        "department": "IT",
        "framework": "mock",
        "agent_type": "http",
        "endpoint": "http://test/mock-agent/envelope",
        "health_endpoint": "http://test/mock-agent/health",
    })
    assert resp.status_code in (200, 201), f"Failed to register agent: {resp.text}"
    # Set intake
    intake_resp = await client.put(f"/api/agents/{agent_id}/intake", json={
        "intake": {
            "categories": categories,
            "source_types": ["api", "email"],
            "keywords": ["test", agent_id],
            "systems": [],
            "priority_range": ["low", "normal", "high", "critical"],
            "negative_categories": [],
        }
    })
    assert intake_resp.status_code == 200, f"Failed to set intake: {intake_resp.text}"
    return resp


def _make_envelope(category: str = "security/incident"):
    return {
        "envelope_id": "test-env-001",
        "source_type": "api",
        "payload": {
            "type": "event",
            "data": {
                "title": "Test security incident",
                "body": "A test event for routing",
                "_classification": {"category": category},
            }
        },
        "metadata": {"tags": ["test", "security"]},
    }


@pytest.mark.asyncio
class TestShadowModeEndpoints:
    async def test_shadow_route_basic(self, client):
        """Shadow mode returns both rule-based and intelligent results."""
        await _register_agent_with_intake(client, "security-triage", ["security"])
        resp = await client.post("/api/route/intelligent/shadow", json={
            "envelope": _make_envelope(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "rule_based" in data
        assert "intelligent" in data
        assert "agreed" in data
        assert isinstance(data["agreed"], bool)
        assert data["comparison_id"] is not None

    async def test_shadow_route_missing_envelope(self, client):
        """Shadow mode rejects requests with missing envelope field."""
        resp = await client.post("/api/route/intelligent/shadow", json={})
        assert resp.status_code == 422

    async def test_shadow_report_empty(self, client):
        """Shadow report works with no comparisons."""
        resp = await client.get("/api/route/shadow/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_comparisons"] == 0
        assert data["agreement_rate"] == 0.0
        assert data["disagreements"] == 0

    async def test_shadow_report_after_comparisons(self, client):
        """Shadow report reflects submitted comparisons."""
        await _register_agent_with_intake(client, "sec-agent", ["security"])
        # Run a couple shadow comparisons
        for i in range(3):
            env = _make_envelope()
            env["envelope_id"] = f"shadow-env-{i}"
            await client.post("/api/route/intelligent/shadow", json={
                "envelope": env,
            })
        resp = await client.get("/api/route/shadow/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_comparisons"] == 3

    async def test_shadow_route_with_custom_weights(self, client):
        """Shadow mode accepts custom scoring weights."""
        await _register_agent_with_intake(client, "weighted-agent", ["security"])
        resp = await client.post("/api/route/intelligent/shadow", json={
            "envelope": _make_envelope(),
            "weights": {
                "category": 0.5,
                "source_type": 0.1,
                "keyword": 0.2,
                "system": 0.1,
                "priority": 0.1,
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intelligent"]["primary"] is not None


@pytest.mark.asyncio
class TestFeedbackEndpoint:
    async def test_submit_feedback_success(self, client):
        """Submit feedback for a routed envelope."""
        await _register_agent_with_intake(client, "feedback-agent", ["security"])
        # First route an envelope to create an envelope_log entry
        route_resp = await client.post("/api/route/intelligent", json={
            "envelope": _make_envelope(),
        })
        assert route_resp.status_code == 200

        # Submit feedback
        resp = await client.post("/api/route/feedback", json={
            "envelope_id": "test-env-001",
            "agent_id": "feedback-agent",
            "outcome": "success",
            "response_time_ms": 150,
            "notes": "Handled well",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "feedback-agent"
        assert data["outcome"] == "success"
        assert data["ema_multiplier"] is not None
        assert "Feedback recorded" in data["message"]

    async def test_submit_feedback_failure_outcome(self, client):
        """Submit negative feedback."""
        await _register_agent_with_intake(client, "fail-agent", ["clinical"])
        resp = await client.post("/api/route/feedback", json={
            "envelope_id": "nonexistent-envelope",
            "agent_id": "fail-agent",
            "outcome": "failure",
            "response_time_ms": 5000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "failure"

    async def test_submit_feedback_updates_ema(self, client):
        """Multiple feedback submissions update the EMA multiplier."""
        await _register_agent_with_intake(client, "ema-agent", ["security"])
        # Submit several successes
        for _ in range(3):
            resp = await client.post("/api/route/feedback", json={
                "envelope_id": "test-env-001",
                "agent_id": "ema-agent",
                "outcome": "success",
                "response_time_ms": 100,
            })
            assert resp.status_code == 200
        data = resp.json()
        # After 3 successes, multiplier should be >= 1.0
        assert data["ema_multiplier"] >= 1.0

    async def test_submit_feedback_missing_fields(self, client):
        """Feedback with missing required fields returns 422."""
        resp = await client.post("/api/route/feedback", json={
            "envelope_id": "test-env-001",
            # missing agent_id and outcome
        })
        assert resp.status_code == 422
