"""Adaptive Card builder helpers for common Trellis outputs.

Builds Microsoft Adaptive Card JSON (schema v1.5) for Teams rendering.
No dependencies — pure dict construction.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
CARD_VERSION = "1.5"


def _card_wrapper(body: list[dict], actions: list[dict] | None = None) -> dict[str, Any]:
    """Wrap body elements in a standard Adaptive Card envelope."""
    card: dict[str, Any] = {
        "$schema": SCHEMA,
        "type": "AdaptiveCard",
        "version": CARD_VERSION,
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


# ── Alert Card ─────────────────────────────────────────────────────────────

def alert_card(
    title: str,
    message: str,
    severity: str = "normal",
    details: dict[str, str] | None = None,
    action_url: str | None = None,
) -> dict[str, Any]:
    """Build an alert notification card.

    Args:
        title: Alert headline.
        message: Alert body text.
        severity: "low", "normal", "high", or "critical" — affects color.
        details: Optional key-value pairs shown as facts.
        action_url: Optional URL for a "View Details" button.
    """
    color_map = {
        "critical": "attention",
        "high": "warning",
        "normal": "default",
        "low": "light",
    }
    color = color_map.get(severity, "default")

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": title,
            "weight": "bolder",
            "size": "medium",
            "color": color,
        },
        {
            "type": "TextBlock",
            "text": message,
            "wrap": True,
        },
    ]

    if details:
        body.append({
            "type": "FactSet",
            "facts": [{"title": k, "value": v} for k, v in details.items()],
        })

    actions = []
    if action_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "View Details",
            "url": action_url,
        })

    return _card_wrapper(body, actions or None)


# ── Agent Status Card ──────────────────────────────────────────────────────

def agent_status_card(
    agent_id: str,
    agent_name: str,
    status: str,
    department: str = "",
    maturity: str = "",
    last_health: str = "",
    cost_today_usd: float | None = None,
) -> dict[str, Any]:
    """Build an agent status summary card."""
    status_emoji = {
        "healthy": "🟢",
        "degraded": "🟡",
        "unhealthy": "🔴",
        "unreachable": "⚫",
    }
    emoji = status_emoji.get(status, "⚪")

    facts = [
        {"title": "Status", "value": f"{emoji} {status}"},
        {"title": "Agent ID", "value": agent_id},
    ]
    if department:
        facts.append({"title": "Department", "value": department})
    if maturity:
        facts.append({"title": "Maturity", "value": maturity})
    if last_health:
        facts.append({"title": "Last Health Check", "value": last_health})
    if cost_today_usd is not None:
        facts.append({"title": "Cost Today", "value": f"${cost_today_usd:.4f}"})

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": agent_name,
            "weight": "bolder",
            "size": "medium",
        },
        {
            "type": "FactSet",
            "facts": facts,
        },
    ]

    return _card_wrapper(body)


# ── Event Summary Card ─────────────────────────────────────────────────────

def event_summary_card(
    title: str,
    events: list[dict[str, str]],
    footer: str = "",
) -> dict[str, Any]:
    """Build an event summary card (e.g., daily digest, trace summary).

    Args:
        title: Card headline.
        events: List of dicts with "label" and "value" keys.
        footer: Optional footer text.
    """
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": title,
            "weight": "bolder",
            "size": "medium",
        },
    ]

    if events:
        body.append({
            "type": "FactSet",
            "facts": [
                {"title": e.get("label", ""), "value": e.get("value", "")}
                for e in events
            ],
        })

    if footer:
        body.append({
            "type": "TextBlock",
            "text": footer,
            "size": "small",
            "isSubtle": True,
            "wrap": True,
        })

    return _card_wrapper(body)


# ── Envelope Result Card ──────────────────────────────────────────────────

def envelope_result_card(
    agent_name: str,
    result_text: str,
    trace_id: str = "",
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Build a card showing an agent's response to a routed envelope."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": f"Response from {agent_name}",
            "weight": "bolder",
            "size": "medium",
        },
        {
            "type": "TextBlock",
            "text": result_text,
            "wrap": True,
        },
    ]

    facts = []
    if trace_id:
        facts.append({"title": "Trace ID", "value": trace_id})
    if cost_usd is not None:
        facts.append({"title": "Cost", "value": f"${cost_usd:.4f}"})

    if facts:
        body.append({"type": "FactSet", "facts": facts})

    return _card_wrapper(body)
