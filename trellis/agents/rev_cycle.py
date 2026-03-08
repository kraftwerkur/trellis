"""Revenue Cycle Management — native agent, no LLM calls.

Handles claim denials, billing inquiries, coding issues, AR management,
and compliance reviews. Pure logic + pattern matching. Fast, deterministic.
"""

import logging
import time

from trellis.agents.tools import (
    analyze_denial,
    assess_rev_cycle_priority,
    classify_rev_cycle_case,
)

logger = logging.getLogger("trellis.agents.rev_cycle")

# Sub-team routing by category
_TEAM_MAP = {
    "denial_appeal": "Denials",
    "coding_review": "Coding",
    "billing_inquiry": "Patient Billing",
    "ar_followup": "AR",
    "compliance": "Compliance",
    "prior_auth": "Prior Auth",
    "credentialing": "Credentialing",
    "charge_capture": "Coding",
    "underpayment": "Denials",
    "bad_debt": "Patient Billing",
}

# Payer timely filing limits (days)
_TIMELY_FILING = {
    "medicare": 365,
    "medicaid": 365,
    "bcbs": 180,
    "uhc": 180,
    "aetna": 120,
    "cigna": 120,
}
_DEFAULT_FILING_LIMIT = 90
_FILING_ALERT_THRESHOLD = 0.80  # Alert when >80% of window used


class RevCycleAgent:
    """Native Revenue Cycle Management triage agent."""

    def __init__(self, agent):
        self.agent = agent

    async def process(self, envelope) -> dict:
        """Full triage pipeline: parse → classify → analyze → prioritize → assign."""
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

        # 2. Classify the case
        classification = classify_rev_cycle_case(
            case["description"], case.get("category_hint")
        )

        # 3. Denial analysis (if denial codes present)
        denial_analysis = None
        if classification["denial_codes"]:
            primary_code = classification["denial_codes"][0]
            denial_analysis = analyze_denial(
                denial_code=primary_code,
                payer=case.get("payer", ""),
                amount=case.get("amount", 0.0),
            )

        # 4. Timely filing check
        payer_key = case.get("payer", "").lower()
        filing_limit = _TIMELY_FILING.get(payer_key, _DEFAULT_FILING_LIMIT)
        days_aged = case.get("days_aged", 0)
        timely_filing_alert = self._check_timely_filing(days_aged, filing_limit)

        # 5. Priority assessment
        priority_result = assess_rev_cycle_priority(
            category=classification["category"],
            amount=case.get("amount", 0.0),
            days_aged=days_aged,
            timely_filing_deadline=filing_limit,
        )

        # Elevate priority if timely filing at risk
        if timely_filing_alert["alert"] and priority_result["priority"] in ("LOW", "MEDIUM"):
            priority_result["priority"] = "HIGH"
            priority_result["urgency"] = "high"
            priority_result["justification"] += f" | Timely filing risk: {timely_filing_alert['message']}"

        # 6. Assign sub-team
        assigned_team = _TEAM_MAP.get(classification["category"], "AR")

        # Build triage output
        case_id = case.get("case_id", "RC-UNKNOWN")
        triage = {
            "case_id": case_id,
            "category": classification["category"],
            "subcategory": classification["subcategory"],
            "keywords": classification["keywords"],
            "denial_codes": classification["denial_codes"],
            "priority": priority_result["priority"],
            "urgency": priority_result["urgency"],
            "priority_justification": priority_result["justification"],
            "assigned_team": assigned_team,
            "timely_filing_alert": timely_filing_alert,
            "denial_analysis": denial_analysis,
        }

        latency_ms = int((time.monotonic() - start) * 1000)

        brief = classification.get("subcategory", classification["category"]).replace("_", " ").title()
        text = (
            f"Rev Cycle case triaged: {classification['category'].upper()} — {brief}. "
            f"Priority: {priority_result['priority']}. "
            f"Assigned: {assigned_team}."
        )
        if timely_filing_alert["alert"]:
            text += f" ⚠️ {timely_filing_alert['message']}"

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
        """Extract revenue cycle fields from event payload."""
        return {
            "case_id": payload.get("case_id", payload.get("id", "RC-UNKNOWN")),
            "description": payload.get("description", payload.get("text", payload.get("content", ""))),
            "payer": payload.get("payer", payload.get("insurance", payload.get("payer_name", ""))),
            "amount": float(payload.get("amount", payload.get("claim_amount", payload.get("charge", 0.0)))),
            "days_aged": int(payload.get("days_aged", payload.get("aging_days", payload.get("days", 0)))),
            "category_hint": payload.get("category", payload.get("category_hint")),
        }

    def _check_timely_filing(self, days_aged: int, filing_limit: int) -> dict:
        """Check if claim is approaching or past timely filing limit."""
        if days_aged <= 0:
            return {"alert": False, "message": "", "days_remaining": filing_limit, "pct_used": 0.0}

        pct_used = days_aged / filing_limit
        days_remaining = max(0, filing_limit - days_aged)

        if days_aged >= filing_limit:
            return {
                "alert": True,
                "message": f"Timely filing expired — {days_aged} days aged, limit is {filing_limit}",
                "days_remaining": 0,
                "pct_used": 1.0,
            }
        elif pct_used >= _FILING_ALERT_THRESHOLD:
            return {
                "alert": True,
                "message": f"Timely filing risk — {days_remaining} days remaining of {filing_limit}-day window",
                "days_remaining": days_remaining,
                "pct_used": round(pct_used, 2),
            }
        return {"alert": False, "message": "", "days_remaining": days_remaining, "pct_used": round(pct_used, 2)}
