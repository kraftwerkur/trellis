"""Tests for the Teams Bot Framework adapter.

Covers: token validation, activity parsing, envelope conversion, card rendering,
and the TeamsClient proactive messaging.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trellis.adapters.teams_adapter import (
    ACTIVITY_TYPE_CONVERSATION_UPDATE,
    ACTIVITY_TYPE_INVOKE,
    ACTIVITY_TYPE_MESSAGE,
    TeamsClient,
    _jwks_cache,
    build_teams_envelope,
    parse_activity,
    validate_bot_token,
)
from trellis.adapters.teams_cards import (
    alert_card,
    agent_status_card,
    event_summary_card,
    envelope_result_card,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

SAMPLE_MESSAGE_ACTIVITY = {
    "type": "message",
    "id": "msg-001",
    "timestamp": "2026-03-04T10:00:00Z",
    "text": "What is the PTO policy?",
    "channelId": "msteams",
    "conversation": {
        "id": "conv-abc-123",
        "tenantId": "tenant-xyz",
    },
    "from": {
        "id": "user-001",
        "name": "Jane Smith",
        "aadObjectId": "aad-oid-001",
    },
    "recipient": {
        "id": "bot-001",
        "name": "Trellis Bot",
    },
    "serviceUrl": "https://smba.trafficmanager.net/teams/",
    "attachments": [
        {
            "name": "screenshot.png",
            "contentType": "image/png",
            "contentUrl": "https://example.com/screenshot.png",
        }
    ],
}

SAMPLE_CONVERSATION_UPDATE = {
    "type": "conversationUpdate",
    "id": "update-001",
    "timestamp": "2026-03-04T10:01:00Z",
    "channelId": "msteams",
    "conversation": {"id": "conv-abc-123", "tenantId": "tenant-xyz"},
    "from": {"id": "bot-001", "name": "Trellis Bot"},
    "serviceUrl": "https://smba.trafficmanager.net/teams/",
    "membersAdded": [
        {"id": "user-002", "name": "Bob Jones"},
    ],
    "membersRemoved": [],
}

SAMPLE_INVOKE_ACTIVITY = {
    "type": "invoke",
    "id": "invoke-001",
    "timestamp": "2026-03-04T10:02:00Z",
    "text": "",
    "channelId": "msteams",
    "conversation": {"id": "conv-abc-123", "tenantId": "tenant-xyz"},
    "from": {"id": "user-001", "name": "Jane Smith", "aadObjectId": "aad-oid-001"},
    "serviceUrl": "https://smba.trafficmanager.net/teams/",
    "name": "adaptiveCard/action",
    "value": {"action": "approve", "request_id": "req-123"},
}


# ── Activity parsing tests ─────────────────────────────────────────────────

class TestParseActivity:
    def test_parse_message(self):
        parsed = parse_activity(SAMPLE_MESSAGE_ACTIVITY)
        assert parsed["type"] == "message"
        assert parsed["text"] == "What is the PTO policy?"
        assert parsed["channel_id"] == "msteams"
        assert parsed["conversation"]["id"] == "conv-abc-123"
        assert parsed["from"]["name"] == "Jane Smith"
        assert len(parsed["attachments"]) == 1

    def test_parse_conversation_update(self):
        parsed = parse_activity(SAMPLE_CONVERSATION_UPDATE)
        assert parsed["type"] == "conversationUpdate"
        assert len(parsed["members_added"]) == 1
        assert parsed["members_added"][0]["name"] == "Bob Jones"

    def test_parse_invoke(self):
        parsed = parse_activity(SAMPLE_INVOKE_ACTIVITY)
        assert parsed["type"] == "invoke"
        assert parsed["name"] == "adaptiveCard/action"
        assert parsed["value"]["action"] == "approve"

    def test_parse_minimal_activity(self):
        """Activity with missing optional fields should not crash."""
        parsed = parse_activity({"type": "message"})
        assert parsed["type"] == "message"
        assert parsed["text"] == ""
        assert parsed["conversation"] == {}
        assert parsed["from"] == {}
        assert parsed["attachments"] == []

    def test_parse_empty_dict(self):
        parsed = parse_activity({})
        assert parsed["type"] == "message"  # default


# ── Envelope conversion tests ──────────────────────────────────────────────

class TestBuildTeamsEnvelope:
    def test_message_envelope(self):
        env = build_teams_envelope(SAMPLE_MESSAGE_ACTIVITY)
        assert env.source_type == "teams"
        assert env.source_id == "teams-msteams-conv-abc-123"
        assert env.payload.text == "What is the PTO policy?"
        assert env.metadata.sender.id == "aad-oid-001"
        assert env.metadata.sender.name == "Jane Smith"
        assert "teams-chat" in env.routing_hints.tags
        assert env.payload.data["conversation_id"] == "conv-abc-123"
        assert env.payload.data["service_url"] == "https://smba.trafficmanager.net/teams/"
        assert env.payload.data["tenant_id"] == "tenant-xyz"
        assert len(env.payload.attachments) == 1
        assert env.payload.attachments[0]["name"] == "screenshot.png"

    def test_conversation_update_envelope(self):
        env = build_teams_envelope(SAMPLE_CONVERSATION_UPDATE)
        assert env.source_type == "teams"
        assert "conversation-update" in env.routing_hints.tags
        assert env.payload.data["members_added"][0]["name"] == "Bob Jones"

    def test_invoke_envelope(self):
        env = build_teams_envelope(SAMPLE_INVOKE_ACTIVITY)
        assert env.source_type == "teams"
        assert "invoke" in env.routing_hints.tags
        assert env.payload.data["invoke_name"] == "adaptiveCard/action"
        assert env.payload.data["invoke_value"]["action"] == "approve"

    def test_envelope_has_ids(self):
        env = build_teams_envelope(SAMPLE_MESSAGE_ACTIVITY)
        assert env.envelope_id  # UUID generated
        assert env.metadata.trace_id  # UUID generated

    def test_sender_fallback_to_id(self):
        """When aadObjectId is missing, fall back to from.id."""
        activity = {**SAMPLE_MESSAGE_ACTIVITY, "from": {"id": "fallback-id", "name": "Test"}}
        env = build_teams_envelope(activity)
        assert env.metadata.sender.id == "fallback-id"


# ── Token validation tests ─────────────────────────────────────────────────

class TestTokenValidation:
    @pytest.mark.asyncio
    async def test_missing_auth_header(self):
        with pytest.raises(ValueError, match="Missing or malformed"):
            await validate_bot_token("", "app-id")

    @pytest.mark.asyncio
    async def test_non_bearer_header(self):
        with pytest.raises(ValueError, match="Missing or malformed"):
            await validate_bot_token("Basic abc123", "app-id")

    @pytest.mark.asyncio
    async def test_malformed_token(self):
        with pytest.raises(ValueError, match="Invalid token format"):
            await validate_bot_token("Bearer not-a-jwt", "app-id")

    @pytest.mark.asyncio
    async def test_no_matching_kid(self):
        """Token with a kid not in JWKS should fail."""
        # Create a minimal JWT with a fake kid
        import jwt as pyjwt

        # Generate a throwaway RSA key
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        token = pyjwt.encode(
            {"aud": "app-id", "iss": "https://sts.windows.net/fake/", "exp": time.time() + 300},
            private_key,
            algorithm="RS256",
            headers={"kid": "nonexistent-kid-12345"},
        )

        # Mock _fetch_jwks to return empty
        with patch("trellis.adapters.teams_adapter._fetch_jwks", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(ValueError, match="No matching JWKS key"):
                await validate_bot_token(f"Bearer {token}", "app-id")

    @pytest.mark.asyncio
    async def test_valid_token_flow(self):
        """Full validation with a self-signed token and matching JWKS."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from jwt.algorithms import RSAAlgorithm

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        kid = "test-kid-001"
        app_id = "my-bot-app-id"

        token = pyjwt.encode(
            {
                "aud": app_id,
                "iss": "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
                "exp": int(time.time()) + 300,
                "iat": int(time.time()),
                "nbf": int(time.time()),
            },
            private_key,
            algorithm="RS256",
            headers={"kid": kid},
        )

        # Build a JWKS entry from the public key
        jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
        jwk_dict["kid"] = kid
        jwk_dict["use"] = "sig"

        with patch("trellis.adapters.teams_adapter._fetch_jwks", new_callable=AsyncMock, return_value=[jwk_dict]):
            claims = await validate_bot_token(f"Bearer {token}", app_id)
            assert claims["aud"] == app_id

    @pytest.mark.asyncio
    async def test_audience_mismatch(self):
        """Token with wrong audience should fail."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from jwt.algorithms import RSAAlgorithm

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        kid = "test-kid-aud"

        token = pyjwt.encode(
            {
                "aud": "wrong-app-id",
                "iss": "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
                "exp": int(time.time()) + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": kid},
        )

        jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
        jwk_dict["kid"] = kid

        with patch("trellis.adapters.teams_adapter._fetch_jwks", new_callable=AsyncMock, return_value=[jwk_dict]):
            with pytest.raises(ValueError, match="audience mismatch"):
                await validate_bot_token(f"Bearer {token}", "correct-app-id")

    @pytest.mark.asyncio
    async def test_untrusted_issuer(self):
        """Token from an untrusted issuer should fail."""
        import jwt as pyjwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from jwt.algorithms import RSAAlgorithm

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        kid = "test-kid-iss"

        token = pyjwt.encode(
            {
                "aud": "app-id",
                "iss": "https://evil.example.com/",
                "exp": int(time.time()) + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": kid},
        )

        jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
        jwk_dict["kid"] = kid

        with patch("trellis.adapters.teams_adapter._fetch_jwks", new_callable=AsyncMock, return_value=[jwk_dict]):
            with pytest.raises(ValueError, match="Untrusted token issuer"):
                await validate_bot_token(f"Bearer {token}", "app-id")


# ── Card rendering tests ──────────────────────────────────────────────────

class TestCards:
    def test_alert_card_basic(self):
        card = alert_card("System Alert", "CPU usage at 95%")
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.5"
        assert any(b["text"] == "System Alert" for b in card["body"] if "text" in b)
        assert any(b["text"] == "CPU usage at 95%" for b in card["body"] if "text" in b)

    def test_alert_card_critical_color(self):
        card = alert_card("Critical!", "DB down", severity="critical")
        title_block = card["body"][0]
        assert title_block["color"] == "attention"

    def test_alert_card_with_details_and_action(self):
        card = alert_card(
            "Alert",
            "Details here",
            details={"Source": "LogicMonitor", "Host": "db-01"},
            action_url="https://example.com/alert/123",
        )
        fact_set = [b for b in card["body"] if b.get("type") == "FactSet"][0]
        assert len(fact_set["facts"]) == 2
        assert card["actions"][0]["url"] == "https://example.com/alert/123"

    def test_agent_status_card(self):
        card = agent_status_card(
            agent_id="sam-hr",
            agent_name="SAM - HR Operations",
            status="healthy",
            department="HR",
            maturity="assisted",
            cost_today_usd=0.0423,
        )
        assert card["type"] == "AdaptiveCard"
        facts = card["body"][1]["facts"]
        status_fact = next(f for f in facts if f["title"] == "Status")
        assert "🟢" in status_fact["value"]

    def test_event_summary_card(self):
        card = event_summary_card(
            title="Daily Summary",
            events=[
                {"label": "Envelopes processed", "value": "142"},
                {"label": "Total cost", "value": "$1.23"},
            ],
            footer="Generated by Trellis",
        )
        assert card["body"][0]["text"] == "Daily Summary"
        facts = card["body"][1]["facts"]
        assert len(facts) == 2

    def test_envelope_result_card(self):
        card = envelope_result_card(
            agent_name="SAM",
            result_text="PTO policy allows 15 days per year.",
            trace_id="trace-abc",
            cost_usd=0.003,
        )
        assert "SAM" in card["body"][0]["text"]
        facts = [b for b in card["body"] if b.get("type") == "FactSet"][0]["facts"]
        assert any(f["title"] == "Trace ID" for f in facts)

    def test_card_no_actions_when_none(self):
        card = alert_card("Test", "Body")
        assert "actions" not in card

    def test_event_summary_empty_events(self):
        card = event_summary_card("Empty", events=[])
        # Should still produce a valid card, just no FactSet
        assert card["type"] == "AdaptiveCard"


# ── TeamsClient tests ──────────────────────────────────────────────────────

class TestTeamsClient:
    @pytest.mark.asyncio
    async def test_send_text(self):
        client = TeamsClient("app-id", "app-secret")
        client._token = "fake-token"
        client._token_expires = time.time() + 3600

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "reply-001"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await client.send_text(
                "https://smba.trafficmanager.net/teams/",
                "conv-123",
                "Hello from Trellis!",
            )

            assert result["id"] == "reply-001"
            call_args = instance.post.call_args
            assert "conv-123/activities" in call_args[0][0]
            body = call_args[1]["json"]
            assert body["type"] == "message"
            assert body["text"] == "Hello from Trellis!"

    @pytest.mark.asyncio
    async def test_send_card(self):
        client = TeamsClient("app-id", "app-secret")
        client._token = "fake-token"
        client._token_expires = time.time() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "reply-002"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            card = alert_card("Test", "Body")
            result = await client.send_card(
                "https://smba.trafficmanager.net/teams/",
                "conv-123",
                card,
                summary="Test alert",
            )

            assert result["id"] == "reply-002"
            body = instance.post.call_args[1]["json"]
            assert body["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
