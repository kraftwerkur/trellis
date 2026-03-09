"""Azure Bot Service integration for Trellis.

Provides the /api/messages endpoint that Bot Framework calls,
bridges activities to Trellis's event router, and supports
proactive messaging back to Teams conversations.

Single file. No SDK dependency — just HTTP + JWT validation
using the existing teams_adapter module.

Env vars:
    TEAMS_APP_ID       — Microsoft App ID from Azure Bot registration
    TEAMS_APP_PASSWORD — Microsoft App Password (client secret)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from trellis.adapters.teams_adapter import (
    TeamsClient,
    build_teams_envelope,
    validate_bot_token,
)
from trellis.adapters.teams_cards import envelope_result_card
from trellis.database import async_session
from trellis.router import route_envelope
from trellis.schemas import Envelope

logger = logging.getLogger("trellis.bot_service")

bot_router = APIRouter(tags=["bot-service"])

# ── Conversation references store (in-memory) ─────────────────────────────
# Maps conversation_id → {service_url, conversation_id, tenant_id}
# Used for proactive messaging. In production, persist to DB.
_conversation_refs: dict[str, dict[str, str]] = {}


def get_conversation_refs() -> dict[str, dict[str, str]]:
    """Get the conversation references store (for testing/proactive use)."""
    return _conversation_refs


def _get_credentials() -> tuple[str, str]:
    """Get bot credentials from env vars. Returns (app_id, app_password)."""
    app_id = os.environ.get("TEAMS_APP_ID", "")
    app_password = os.environ.get("TEAMS_APP_PASSWORD", "")
    return app_id, app_password


def _get_teams_client() -> TeamsClient | None:
    """Create a TeamsClient if credentials are configured."""
    app_id, app_password = _get_credentials()
    if not app_id or not app_password:
        return None
    return TeamsClient(app_id, app_password)


# ── /api/messages endpoint ─────────────────────────────────────────────────

@bot_router.post("/api/messages")
async def handle_bot_message(
    request: Request,
    authorization: str | None = Header(None),
):
    """Bot Framework webhook endpoint.

    Receives Activity objects from Azure Bot Service, validates the JWT,
    converts to a Trellis Envelope, routes it, and sends the response
    back to Teams.
    """
    app_id, app_password = _get_credentials()

    if not app_id or not app_password:
        raise HTTPException(
            status_code=503,
            detail="Bot not configured. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD.",
        )

    # Parse the activity
    try:
        activity: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Validate Bot Framework JWT token
    # Skip validation for emulator (no auth header) in dev mode only
    if authorization:
        try:
            await validate_bot_token(authorization, app_id)
        except ValueError as e:
            logger.warning("Token validation failed: %s", e)
            raise HTTPException(status_code=401, detail=str(e))
    else:
        # No auth header — only allow if explicitly in dev mode
        if os.environ.get("TRELLIS_BOT_DEV_MODE", "").lower() != "true":
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
            )
        logger.warning("Bot dev mode: skipping token validation")

    activity_type = activity.get("type", "")

    # Store conversation reference for proactive messaging
    conversation = activity.get("conversation", {})
    conv_id = conversation.get("id", "")
    service_url = activity.get("serviceUrl", "")
    if conv_id and service_url:
        _conversation_refs[conv_id] = {
            "service_url": service_url,
            "conversation_id": conv_id,
            "tenant_id": conversation.get("tenantId", ""),
        }

    # Only route message activities through Trellis
    if activity_type != "message":
        # Acknowledge non-message activities (conversationUpdate, etc.)
        return {"status": "ok", "activity_type": activity_type}

    # Convert to Trellis envelope and route
    envelope: Envelope = build_teams_envelope(activity)

    async with async_session() as db:
        result = await route_envelope(envelope, db)
        await db.commit()

    # Send response back to Teams
    response_text = _extract_response_text(result)
    if response_text and conv_id and service_url:
        client = _get_teams_client()
        if client:
            try:
                # Build an Adaptive Card for rich responses
                trace_id = envelope.metadata.trace_id
                agent_name = result.get("target_agent", "Trellis")
                cost = _extract_cost(result)

                card = envelope_result_card(
                    agent_name=agent_name,
                    result_text=response_text,
                    trace_id=trace_id,
                    cost_usd=cost,
                )
                await client.send_card(
                    service_url=service_url,
                    conversation_id=conv_id,
                    card=card,
                    summary=response_text[:100],
                )
            except Exception as e:
                logger.error("Failed to send Teams reply: %s", e)
                # Fall back to plain text
                try:
                    await client.send_text(service_url, conv_id, response_text)
                except Exception:
                    logger.error("Failed to send plain text fallback")

    return {
        "status": result.get("status", "ok"),
        "envelope_id": envelope.envelope_id,
    }


# ── Proactive messaging ───────────────────────────────────────────────────

async def send_proactive_message(
    conversation_id: str,
    text: str | None = None,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a proactive message to a Teams conversation.

    Args:
        conversation_id: The conversation to message (must have a stored reference).
        text: Plain text message.
        card: Adaptive Card JSON.

    Returns:
        Bot Framework API response.

    Raises:
        ValueError: If conversation not found or bot not configured.
    """
    ref = _conversation_refs.get(conversation_id)
    if not ref:
        raise ValueError(
            f"No conversation reference for '{conversation_id}'. "
            "The bot must receive a message from this conversation first."
        )

    client = _get_teams_client()
    if not client:
        raise ValueError("Bot not configured. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD.")

    if card:
        return await client.send_card(
            service_url=ref["service_url"],
            conversation_id=conversation_id,
            card=card,
        )
    elif text:
        return await client.send_text(
            service_url=ref["service_url"],
            conversation_id=conversation_id,
            text=text,
        )
    else:
        raise ValueError("Must provide either text or card")


# ── Proactive messaging API endpoint ──────────────────────────────────────

@bot_router.post("/api/proactive")
async def proactive_endpoint(request: Request):
    """Send a proactive message to a Teams conversation.

    Body: {"conversation_id": "...", "text": "...", "card": {...}}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    conversation_id = body.get("conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id required")

    try:
        result = await send_proactive_message(
            conversation_id=conversation_id,
            text=body.get("text"),
            card=body.get("card"),
        )
        return {"status": "sent", "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Helpers ────────────────────────────────────────────────────────────────

def _extract_response_text(result: dict[str, Any]) -> str:
    """Pull human-readable text from a route_envelope result."""
    if result.get("status") == "no_match":
        return "I'm not sure how to help with that. No agent matched your request."

    if result.get("status") == "agent_not_found":
        return "Sorry, the assigned agent is currently unavailable."

    # Standard dispatch result
    inner = result.get("result")
    if isinstance(inner, dict):
        r = inner.get("result", {})
        if isinstance(r, dict):
            return r.get("text", "")
        return inner.get("text", "")

    # Fan-out: combine responses
    dispatches = result.get("dispatches", [])
    if dispatches:
        texts = []
        for d in dispatches:
            t = _extract_response_text(d)
            if t:
                agent = d.get("target_agent", "Agent")
                texts.append(f"**{agent}:** {t}")
        return "\n\n".join(texts)

    return ""


def _extract_cost(result: dict[str, Any]) -> float | None:
    """Pull cost from a route_envelope result, if available."""
    inner = result.get("result")
    if isinstance(inner, dict):
        data = inner.get("result", {}).get("data", {})
        cost = data.get("cost_usd")
        if cost is not None:
            try:
                return float(cost)
            except (ValueError, TypeError):
                return None
    return None
