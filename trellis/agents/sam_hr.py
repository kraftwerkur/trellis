"""SAM-HR — Strategic Automated Manager for HR. Native agent, no LLM calls.

Receives HR case envelopes and produces structured triage output.
Pure logic + pattern matching. Fast, deterministic.
"""

import logging
import time

from trellis.agents.tools import (
    assess_hr_priority,
    classify_hr_case,
    lookup_hr_policy,
)

logger = logging.getLogger("trellis.agents.sam_hr")

# Team assignment by category
_TEAM_MAP = {
    "benefits": "Benefits Admin",
    "payroll": "Payroll",
    "pto": "HR Generalist",
    "onboarding": "Talent Acquisition",
    "offboarding": "HR Generalist",
    "policy": "HR Generalist",
    "compliance": "Compliance",
    "workers_comp": "Employee Relations",
    "fmla": "Employee Relations",
    "ada": "Employee Relations",
}


class SAMHRAgent:
    """Native HR case triage agent."""

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

        case = self._parse_case(merged)

        # 2. Classify the HR case
        classification = classify_hr_case(case["description"], case.get("category_hint"))

        # 3. Assess priority
        priority_result = assess_hr_priority(
            category=classification["category"],
            regulatory_flags=classification["regulatory_flags"],
            affected_employees=case.get("affected_employees", 1),
        )

        # 4. Lookup HR policy
        policy = lookup_hr_policy(classification["category"], classification["keywords"])

        # 5. Determine assigned team + escalation
        assigned_team = _TEAM_MAP.get(classification["category"], "HR Generalist")
        requires_escalation = bool(classification["regulatory_flags"]) or priority_result["priority"] == "CRITICAL"
        escalation_reason = None
        if classification["regulatory_flags"]:
            escalation_reason = f"Regulatory compliance case: {', '.join(classification['regulatory_flags'])}"
        elif priority_result["priority"] == "CRITICAL":
            escalation_reason = "Critical priority HR case"

        # Build triage output
        case_id = case.get("case_id", "HR-UNKNOWN")
        triage = {
            "case_id": case_id,
            "category": classification["category"],
            "subcategory": classification["subcategory"],
            "priority": priority_result["priority"],
            "priority_justification": priority_result["justification"],
            "assigned_team": assigned_team,
            "regulatory_flags": classification["regulatory_flags"],
            "sla_hours": priority_result["sla_hours"],
            "policy_reference": policy["policy_reference"],
            "standard_procedure": policy["standard_procedure"],
            "requires_escalation": requires_escalation,
            "escalation_reason": escalation_reason,
        }

        latency_ms = int((time.monotonic() - start) * 1000)

        brief = classification.get("subcategory", classification["category"]).replace("_", " ").title()
        text = (
            f"HR Case triaged: {classification['category'].upper()} - {brief}. "
            f"Priority: {priority_result['priority']}. "
            f"Assigned: {assigned_team}. "
            f"SLA: {priority_result['sla_hours']}h"
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

    def _parse_case(self, payload: dict) -> dict:
        """Extract HR case fields from event payload."""
        return {
            "case_id": payload.get("case_id", payload.get("id", "HR-UNKNOWN")),
            "description": payload.get("description", payload.get("text", payload.get("content", ""))),
            "affected_employees": int(payload.get("affected_employees", payload.get("employee_count", 1))),
            "category_hint": payload.get("category", payload.get("category_hint")),
        }
