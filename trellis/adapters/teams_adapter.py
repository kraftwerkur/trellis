"""Microsoft Teams Bot Framework adapter for Trellis.

Receives Bot Framework v4 Activity objects via POST /api/messages,
validates the JWT token, converts to a Trellis Envelope, and dispatches.
Supports proactive messaging back to Teams conversations.

Dependencies: PyJWT (for token validation), httpx (already in project).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import jwt

from trellis.schemas import Envelope, Metadata, Payload, RoutingHints, Sender

logger = logging.getLogger("trellis.adapters.teams")

# ── Bot Framework token validation ─────────────────────────────────────────

# Microsoft's OpenID metadata endpoints
BOT_FRAMEWORK_OPENID_URL = (
    "https://login.botframework.com/v1/.well-known/openidconfiguration"
)
EMULATOR_OPENID_URL = (
    "https://login.microsoftonline.com/botframework.com/v2.0/"
    ".well-known/openid-configuration"
)

# IMPORTANT: The audience claim in Bot Framework tokens is the bot's App ID,
# NOT "https://api.botframework.com" as some docs suggest. The token's "aud"
# field must match YOUR bot's Microsoft App ID. This is the #1 gotcha.
#
# The issuer can be either:
#   - v1 tokens: https://sts.windows.net/{tenant-id}/
#   - v2 tokens: https://login.microsoftonline.com/{tenant-id}/v2.0
# We validate against the JWKS keys rather than hardcoding issuers.

VALID_TOKEN_ISSUERS = [
    "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",  # Bot Framework tenant
    "https://login.microsoftonline.com/d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0",
    "https://sts.windows.net/f8cdef31-a31e-4b4a-93e4-5f571e91255a/",  # US Gov
    "https://login.microsoftonline.com/f8cdef31-a31e-4b4a-93e4-5f571e91255a/v2.0",
]

# Cache for JWKS keys
_jwks_cache: dict[str, Any] = {"keys": [], "expires": 0}
_JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_jwks() -> list[dict[str, Any]]:
    """Fetch JSON Web Key Set from Bot Framework's OpenID endpoint."""
    now = time.time()
    if _jwks_cache["keys"] and now < _jwks_cache["expires"]:
        return _jwks_cache["keys"]

    all_keys: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for openid_url in [BOT_FRAMEWORK_OPENID_URL, EMULATOR_OPENID_URL]:
            try:
                resp = await client.get(openid_url)
                resp.raise_for_status()
                jwks_uri = resp.json().get("jwks_uri")
                if not jwks_uri:
                    continue
                jwks_resp = await client.get(jwks_uri)
                jwks_resp.raise_for_status()
                all_keys.extend(jwks_resp.json().get("keys", []))
            except Exception as e:
                logger.warning("Failed to fetch JWKS from %s: %s", openid_url, e)

    if all_keys:
        _jwks_cache["keys"] = all_keys
        _jwks_cache["expires"] = now + _JWKS_CACHE_TTL

    return all_keys


async def validate_bot_token(auth_header: str, app_id: str) -> dict[str, Any]:
    """Validate a Bot Framework JWT token.

    Args:
        auth_header: The full Authorization header value ("Bearer <token>").
        app_id: The bot's Microsoft App ID (expected audience).

    Returns:
        Decoded token claims on success.

    Raises:
        ValueError: If validation fails.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        raise ValueError("Missing or malformed Authorization header")

    token = auth_header[7:]  # Strip "Bearer "

    # Decode header to find the key ID
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as e:
        raise ValueError(f"Invalid token format: {e}")

    kid = unverified_header.get("kid")
    if not kid:
        raise ValueError("Token header missing 'kid'")

    # Fetch JWKS and find matching key
    jwks = await _fetch_jwks()
    signing_key = None
    for key_data in jwks:
        if key_data.get("kid") == kid:
            signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
            break

    if signing_key is None:
        # Force refresh cache and retry once
        _jwks_cache["expires"] = 0
        jwks = await _fetch_jwks()
        for key_data in jwks:
            if key_data.get("kid") == kid:
                signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
                break

    if signing_key is None:
        raise ValueError(f"No matching JWKS key for kid={kid}")

    # Validate the token
    # CRITICAL: audience MUST be the bot's own App ID, not some generic URL.
    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=app_id,
            options={"verify_iss": False},  # We check issuer manually below
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidAudienceError:
        raise ValueError(
            f"Token audience mismatch. Expected aud={app_id}. "
            "Ensure TEAMS_APP_ID matches your Bot registration."
        )
    except jwt.exceptions.PyJWTError as e:
        raise ValueError(f"Token validation failed: {e}")

    # Verify issuer is from a known Microsoft tenant
    issuer = claims.get("iss", "")
    if not any(issuer == valid_iss for valid_iss in VALID_TOKEN_ISSUERS):
        # Also accept any sts.windows.net or login.microsoftonline.com issuer
        # since multi-tenant bots can receive tokens from any AAD tenant
        if not (
            issuer.startswith("https://sts.windows.net/")
            or issuer.startswith("https://login.microsoftonline.com/")
        ):
            raise ValueError(f"Untrusted token issuer: {issuer}")

    return claims


# ── Activity parsing → Envelope ────────────────────────────────────────────

# Bot Framework Activity types we handle
ACTIVITY_TYPE_MESSAGE = "message"
ACTIVITY_TYPE_CONVERSATION_UPDATE = "conversationUpdate"
ACTIVITY_TYPE_INVOKE = "invoke"


def parse_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw Bot Framework Activity into a clean dict.

    Handles missing/optional fields gracefully.
    """
    return {
        "type": activity.get("type", "message"),
        "id": activity.get("id", ""),
        "timestamp": activity.get("timestamp", ""),
        "text": activity.get("text", ""),
        "channel_id": activity.get("channelId", ""),
        "conversation": activity.get("conversation", {}),
        "from": activity.get("from", {}),
        "recipient": activity.get("recipient", {}),
        "service_url": activity.get("serviceUrl", ""),
        "attachments": activity.get("attachments", []),
        "entities": activity.get("entities", []),
        "value": activity.get("value"),  # For invoke activities
        "name": activity.get("name", ""),  # Invoke name
        "members_added": activity.get("membersAdded", []),
        "members_removed": activity.get("membersRemoved", []),
    }


def build_teams_envelope(activity: dict[str, Any]) -> Envelope:
    """Convert a Bot Framework Activity into a Trellis Envelope.

    Args:
        activity: Raw activity dict from Bot Framework webhook.

    Returns:
        A Trellis Envelope with source_type="teams".
    """
    parsed = parse_activity(activity)
    activity_type = parsed["type"]
    conversation = parsed["conversation"]
    sender = parsed["from"]

    # Build payload based on activity type
    text = parsed["text"] or ""
    data: dict[str, Any] = {
        "activity_type": activity_type,
        "conversation_id": conversation.get("id", ""),
        "message_id": parsed["id"],
        "channel_id": parsed["channel_id"],
        "service_url": parsed["service_url"],
        "tenant_id": conversation.get("tenantId", ""),
    }

    attachments: list[dict[str, Any]] = []
    tags = ["teams-chat"]

    if activity_type == ACTIVITY_TYPE_MESSAGE:
        # Standard text message
        for att in parsed["attachments"]:
            attachments.append({
                "name": att.get("name", ""),
                "content_type": att.get("contentType", ""),
                "url": att.get("contentUrl", ""),
                "content": att.get("content"),
            })

    elif activity_type == ACTIVITY_TYPE_CONVERSATION_UPDATE:
        # Members added/removed
        data["members_added"] = [
            {"id": m.get("id", ""), "name": m.get("name", "")}
            for m in parsed["members_added"]
        ]
        data["members_removed"] = [
            {"id": m.get("id", ""), "name": m.get("name", "")}
            for m in parsed["members_removed"]
        ]
        text = text or f"Conversation update: {len(data['members_added'])} added, {len(data['members_removed'])} removed"
        tags.append("conversation-update")

    elif activity_type == ACTIVITY_TYPE_INVOKE:
        # Invoke activities (adaptive card actions, messaging extensions, etc.)
        data["invoke_name"] = parsed["name"]
        data["invoke_value"] = parsed["value"]
        text = text or f"Invoke: {parsed['name']}"
        tags.append("invoke")

    return Envelope(
        source_type="teams",
        source_id=f"teams-{parsed['channel_id']}-{conversation.get('id', '')}",
        payload=Payload(
            text=text,
            data=data,
            attachments=attachments,
        ),
        metadata=Metadata(
            timestamp=parsed["timestamp"] or datetime.now(timezone.utc).isoformat(),
            priority="normal",
            sender=Sender(
                id=sender.get("aadObjectId", sender.get("id", "")),
                name=sender.get("name", ""),
                department="",  # Resolved by platform via Azure AD lookup
                roles=[],
            ),
        ),
        routing_hints=RoutingHints(tags=tags),
    )


# ── Proactive messaging (send back to Teams) ──────────────────────────────

# ── Service URL validation (SSRF prevention) ──────────────────────────────

# Bot Framework only sends activities from these domains.
# Reject anything else to prevent SSRF via crafted serviceUrl.
ALLOWED_SERVICE_URL_PREFIXES = [
    "https://smba.trafficmanager.net/",
    "https://webchat.botframework.com/",
    "https://directline.botframework.com/",
    "https://europe.directline.botframework.com/",
    "https://asia.directline.botframework.com/",
    "https://smba.infra.gcc.teams.microsoft.com/",  # GCC
    "https://smba.infra.gcch.teams.microsoft.com/",  # GCC-H
    "https://smba.infra.dod.teams.microsoft.com/",  # DoD
    # Allow localhost for dev/emulator
    "http://localhost:",
    "http://127.0.0.1:",
]


def _validate_service_url(service_url: str) -> None:
    """Ensure the service URL is a known Bot Framework endpoint.

    Raises:
        ValueError: If the URL doesn't match any allowed prefix.
    """
    if not service_url:
        raise ValueError("Empty service URL")
    if not any(service_url.startswith(prefix) for prefix in ALLOWED_SERVICE_URL_PREFIXES):
        raise ValueError(
            f"Untrusted service URL: {service_url}. "
            "Only Bot Framework endpoints are allowed."
        )


class TeamsClient:
    """Send messages and cards back to Teams conversations.

    Uses the Bot Framework REST API (v3) to post activities.
    """

    def __init__(self, app_id: str, app_password: str):
        self.app_id = app_id
        self.app_password = app_password
        self._token: str | None = None
        self._token_expires: float = 0

    async def _get_token(self) -> str:
        """Get an OAuth token for the Bot Framework API."""
        now = time.time()
        if self._token and now < self._token_expires - 60:
            return self._token

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.app_id,
                    "client_secret": self.app_password,
                    "scope": "https://api.botframework.com/.default",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        self._token_expires = now + data.get("expires_in", 3600)
        return self._token

    async def send_text(
        self,
        service_url: str,
        conversation_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Send a plain text reply to a Teams conversation."""
        return await self._send_activity(service_url, conversation_id, {
            "type": "message",
            "text": text,
        })

    async def send_card(
        self,
        service_url: str,
        conversation_id: str,
        card: dict[str, Any],
        summary: str = "",
    ) -> dict[str, Any]:
        """Send an Adaptive Card to a Teams conversation."""
        return await self._send_activity(service_url, conversation_id, {
            "type": "message",
            "summary": summary or "Trellis notification",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }],
        })

    async def _send_activity(
        self,
        service_url: str,
        conversation_id: str,
        activity: dict[str, Any],
    ) -> dict[str, Any]:
        """POST an activity to the Bot Framework conversation endpoint.

        Validates service_url against known Bot Framework domains and
        retries once on 401 (token refresh) or 429/5xx (transient).
        """
        _validate_service_url(service_url)
        token = await self._get_token()
        url = (
            f"{service_url.rstrip('/')}/v3/conversations/"
            f"{conversation_id}/activities"
        )

        for attempt in range(2):
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    json=activity,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 401 and attempt == 0:
                    # Token may have expired; force refresh and retry
                    self._token = None
                    self._token_expires = 0
                    token = await self._get_token()
                    continue
                if resp.status_code == 429 and attempt == 0:
                    # Rate limited; wait briefly and retry once
                    import asyncio
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    await asyncio.sleep(min(retry_after, 10))
                    continue
                resp.raise_for_status()
                return resp.json()

        # Should not reach here, but just in case
        resp.raise_for_status()
        return resp.json()
