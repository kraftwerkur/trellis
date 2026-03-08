"""IT Help Desk Triage Agent — native agent, no LLM calls.

Receives IT incident envelopes and produces structured triage output.
Pure logic + pattern matching. Fast, deterministic.
"""

import logging
import time

from trellis.agents.tools import (
    assess_priority,
    classify_ticket,
    lookup_known_resolution,
    lookup_tech_stack,
)

logger = logging.getLogger("trellis.agents.it_help")

# Team assignment by category
_TEAM_MAP = {
    "network": "Network Ops",
    "application": "App Support",
    "endpoint": "Desktop Support",
    "access": "IAM",
    "infrastructure": "Infrastructure",
}


class ITHelpAgent:
    """Native IT help desk triage agent."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        """Full triage pipeline: parse → classify → prioritize → assign."""
        start = time.monotonic()

        # 1. Parse payload
        if hasattr(envelope, "model_dump"):
            env_dict = envelope.model_dump()
        elif isinstance(envelope, dict):
            env_dict = envelope
        else:
            env_dict = {"payload": {}}

        payload = env_dict.get("payload", {})
        payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
        merged = {**payload_data, **payload}

        ticket = self._parse_ticket(merged)

        # 2. Classify the ticket
        classification = classify_ticket(ticket["description"], ticket.get("category_hint"))

        # 3. Identify affected systems from tech stack
        affected_systems = self._identify_systems(ticket["description"], classification["keywords"])

        # Determine highest system criticality for priority assessment
        system_criticality = "low"
        crit_order = ["critical", "high", "medium", "low"]
        for sys in affected_systems:
            c = sys["criticality"]
            if crit_order.index(c) < crit_order.index(system_criticality):
                system_criticality = c

        # 4. Assess priority
        priority_result = assess_priority(
            severity=ticket.get("severity", "medium"),
            affected_users=ticket.get("affected_users", 1),
            system_criticality=system_criticality,
        )

        # 5. Lookup known resolution
        resolution = lookup_known_resolution(classification["category"], classification["keywords"])

        # 6. Determine assigned team + escalation
        assigned_team = _TEAM_MAP.get(classification["category"], "App Support")
        requires_escalation = priority_result["priority"] in ("CRITICAL", "HIGH")

        # Build triage output
        ticket_id = ticket.get("ticket_id", "INC-UNKNOWN")
        triage = {
            "ticket_id": ticket_id,
            "category": classification["category"],
            "subcategory": classification["subcategory"],
            "priority": priority_result["priority"],
            "priority_justification": priority_result["justification"],
            "affected_systems": affected_systems,
            "assigned_team": assigned_team,
            "known_resolution": resolution,
            "requires_escalation": requires_escalation,
        }

        latency_ms = int((time.monotonic() - start) * 1000)

        brief = classification.get("subcategory", classification["category"]).replace("_", " ").title()
        text = (
            f"IT Ticket {ticket_id} triaged: {classification['category'].upper()} - {brief}. "
            f"Priority: {priority_result['priority']}. Assigned: {assigned_team}."
        )

        return {
            "status": "completed",
            "result": {
                "text": text,
                "data": {
                    "triage": triage,
                    "latency_ms": latency_ms,
                    "agent_type": "native",
                },
                "attachments": [],
            },
        }

    def _parse_ticket(self, payload: dict) -> dict:
        """Extract ticket fields from event payload."""
        return {
            "ticket_id": payload.get("ticket_id", payload.get("id", "INC-UNKNOWN")),
            "description": payload.get("description", payload.get("text", payload.get("content", ""))),
            "severity": payload.get("severity", "medium"),
            "affected_users": int(payload.get("affected_users", payload.get("user_count", 1))),
            "category_hint": payload.get("category", payload.get("category_hint")),
        }

    def _identify_systems(self, description: str, keywords: list[str]) -> list[dict]:
        """Match description and keywords against Health First tech stack."""
        found = {}
        # Search by each keyword + key terms from description
        search_terms = keywords + description.split()
        for term in search_terms:
            if len(term) < 3:
                continue
            result = lookup_tech_stack(term)
            for match in result.get("matches", []):
                if match["match_confidence"] >= 0.6:
                    sys_name = match["system"]
                    if sys_name not in found or match["match_confidence"] > found[sys_name]["match_confidence"]:
                        found[sys_name] = match

        return [
            {"system": m["system"], "criticality": m["criticality"]}
            for m in sorted(found.values(), key=lambda x: x["match_confidence"], reverse=True)
        ]
