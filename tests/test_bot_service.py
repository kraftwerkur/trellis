"""Tests for the Azure Bot Service integration module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from trellis.bot_service import (
    _extract_cost,
    _extract_response_text,
    bot_router,
    get_conversation_refs,
    send_proactive_message,
)


# ── Helper: sample activity ───────────────────────────────────────────────

def _make_activity(text="Hello", activity_type="message", conv_id="conv-1"):
    return {
        "type": activity_type,
        "id": "msg-1",
        "timestamp": "2026-03-09T12:00:00Z",
        "text": text,
        "channelId": "msteams",
        "conversation": {"id": conv_id, "tenantId": "tenant-1"},
        "from": {"id": "user-1", "name": "Test User", "aadObjectId": "aad-1"},
        "recipient": {"id": "bot-1", "name": "Trellis Bot"},
        "serviceUrl": "https://smba.trafficmanager.net/teams/",
        "attachments": [],
        "entities": [],
    }


# ── _extract_response_text ────────────────────────────────────────────────

class TestExtractResponseText:
    def test_no_match(self):
        result = {"status": "no_match"}
        text = _extract_response_text(result)
        assert "not sure" in text.lower()

    def test_agent_not_found(self):
        result = {"status": "agent_not_found"}
        text = _extract_response_text(result)
        assert "unavailable" in text.lower()

    def test_standard_result(self):
        result = {
            "status": "success",
            "result": {"result": {"text": "PTO balance is 12 days", "data": {}}},
        }
        assert _extract_response_text(result) == "PTO balance is 12 days"

    def test_fan_out(self):
        result = {
            "status": "fan_out",
            "dispatches": [
                {
                    "target_agent": "sam-hr",
                    "status": "success",
                    "result": {"result": {"text": "HR says hi"}},
                },
                {
                    "target_agent": "it-help",
                    "status": "success",
                    "result": {"result": {"text": "IT says hello"}},
                },
            ],
        }
        text = _extract_response_text(result)
        assert "sam-hr" in text
        assert "it-help" in text

    def test_empty_result(self):
        assert _extract_response_text({"status": "success"}) == ""


class TestExtractCost:
    def test_with_cost(self):
        result = {
            "result": {"result": {"data": {"cost_usd": "0.003"}}}
        }
        assert _extract_cost(result) == 0.003

    def test_no_cost(self):
        assert _extract_cost({"result": {}}) is None

    def test_no_result(self):
        assert _extract_cost({}) is None


# ── Conversation refs ─────────────────────────────────────────────────────

class TestConversationRefs:
    def test_refs_dict(self):
        refs = get_conversation_refs()
        assert isinstance(refs, dict)


# ── /api/messages endpoint ────────────────────────────────────────────────

@pytest.fixture
def _bot_env(monkeypatch):
    monkeypatch.setenv("TEAMS_APP_ID", "test-app-id")
    monkeypatch.setenv("TEAMS_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("TRELLIS_BOT_DEV_MODE", "true")


@pytest.fixture
def _no_bot_env(monkeypatch):
    monkeypatch.delenv("TEAMS_APP_ID", raising=False)
    monkeypatch.delenv("TEAMS_APP_PASSWORD", raising=False)


def _make_test_app():
    """Create a minimal FastAPI app with just the bot router for testing."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(bot_router)
    return app


@pytest.mark.asyncio
async def test_messages_no_config(_no_bot_env):
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/messages", json=_make_activity())
        assert resp.status_code == 503


@pytest.mark.asyncio
async def test_messages_no_auth_no_dev_mode(monkeypatch):
    monkeypatch.setenv("TEAMS_APP_ID", "test-app-id")
    monkeypatch.setenv("TEAMS_APP_PASSWORD", "test-pw")
    monkeypatch.delenv("TRELLIS_BOT_DEV_MODE", raising=False)
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/messages", json=_make_activity())
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_messages_conversation_update(_bot_env):
    app = _make_test_app()
    activity = _make_activity(activity_type="conversationUpdate")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/messages", json=activity)
        assert resp.status_code == 200
        data = resp.json()
        assert data["activity_type"] == "conversationUpdate"


@pytest.mark.asyncio
async def test_messages_stores_conversation_ref(_bot_env):
    app = _make_test_app()
    refs = get_conversation_refs()
    refs.clear()

    activity = _make_activity(activity_type="conversationUpdate", conv_id="ref-test-conv")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/api/messages", json=activity)

    assert "ref-test-conv" in refs
    assert refs["ref-test-conv"]["service_url"] == "https://smba.trafficmanager.net/teams/"


@pytest.mark.asyncio
async def test_messages_routes_message(_bot_env):
    """Message activities go through route_envelope."""
    app = _make_test_app()

    mock_result = {
        "status": "success",
        "target_agent": "sam-hr",
        "result": {"result": {"text": "Hello from SAM", "data": {}}},
    }

    with patch("trellis.bot_service.route_envelope", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = mock_result
        # Also mock the TeamsClient to avoid real HTTP calls
        with patch("trellis.bot_service._get_teams_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.send_card = AsyncMock(return_value={"id": "resp-1"})
            mock_client_fn.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/messages", json=_make_activity("What is my PTO?"))

            assert resp.status_code == 200
            assert resp.json()["status"] == "success"
            mock_route.assert_called_once()
            # Verify it sent a card back
            mock_client.send_card.assert_called_once()


@pytest.mark.asyncio
async def test_messages_no_match_response(_bot_env):
    """No-match results return a friendly message."""
    app = _make_test_app()

    with patch("trellis.bot_service.route_envelope", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = {"status": "no_match", "error": "No rule matched"}
        with patch("trellis.bot_service._get_teams_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.send_card = AsyncMock(return_value={"id": "resp-1"})
            mock_client_fn.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/messages", json=_make_activity())

            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_messages_invalid_json(_bot_env):
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/messages",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ── Proactive messaging ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proactive_no_ref():
    with pytest.raises(ValueError, match="No conversation reference"):
        await send_proactive_message("nonexistent-conv", text="hi")


@pytest.mark.asyncio
async def test_proactive_no_config(monkeypatch):
    monkeypatch.delenv("TEAMS_APP_ID", raising=False)
    monkeypatch.delenv("TEAMS_APP_PASSWORD", raising=False)
    refs = get_conversation_refs()
    refs["test-conv"] = {
        "service_url": "https://smba.trafficmanager.net/teams/",
        "conversation_id": "test-conv",
        "tenant_id": "t1",
    }
    with pytest.raises(ValueError, match="not configured"):
        await send_proactive_message("test-conv", text="hi")


@pytest.mark.asyncio
async def test_proactive_no_content(monkeypatch):
    monkeypatch.setenv("TEAMS_APP_ID", "app-id")
    monkeypatch.setenv("TEAMS_APP_PASSWORD", "pw")
    refs = get_conversation_refs()
    refs["test-conv-2"] = {
        "service_url": "https://smba.trafficmanager.net/teams/",
        "conversation_id": "test-conv-2",
        "tenant_id": "t1",
    }
    with pytest.raises(ValueError, match="Must provide"):
        await send_proactive_message("test-conv-2")


@pytest.mark.asyncio
async def test_proactive_sends_text(monkeypatch):
    monkeypatch.setenv("TEAMS_APP_ID", "app-id")
    monkeypatch.setenv("TEAMS_APP_PASSWORD", "pw")
    refs = get_conversation_refs()
    refs["pro-conv"] = {
        "service_url": "https://smba.trafficmanager.net/teams/",
        "conversation_id": "pro-conv",
        "tenant_id": "t1",
    }
    with patch("trellis.bot_service._get_teams_client") as mock_fn:
        mock_client = AsyncMock()
        mock_client.send_text = AsyncMock(return_value={"id": "msg-1"})
        mock_fn.return_value = mock_client
        result = await send_proactive_message("pro-conv", text="Alert!")
        mock_client.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_proactive_sends_card(monkeypatch):
    monkeypatch.setenv("TEAMS_APP_ID", "app-id")
    monkeypatch.setenv("TEAMS_APP_PASSWORD", "pw")
    refs = get_conversation_refs()
    refs["card-conv"] = {
        "service_url": "https://smba.trafficmanager.net/teams/",
        "conversation_id": "card-conv",
        "tenant_id": "t1",
    }
    card = {"type": "AdaptiveCard", "body": []}
    with patch("trellis.bot_service._get_teams_client") as mock_fn:
        mock_client = AsyncMock()
        mock_client.send_card = AsyncMock(return_value={"id": "msg-2"})
        mock_fn.return_value = mock_client
        await send_proactive_message("card-conv", card=card)
        mock_client.send_card.assert_called_once()


# ── /api/proactive endpoint ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proactive_endpoint_no_conv_id():
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/proactive", json={"text": "hi"})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_proactive_endpoint_missing_ref():
    app = _make_test_app()
    refs = get_conversation_refs()
    refs.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/proactive",
            json={"conversation_id": "nope", "text": "hi"},
        )
        assert resp.status_code == 400
