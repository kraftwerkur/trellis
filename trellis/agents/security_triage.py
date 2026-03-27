"""Security Triage Agent — multi-step agent using AgentLoop and real KEV lookup.

Processes vulnerability alerts by:
1. Extracting CVE IDs from envelope text via regex
2. Checking each CVE against CISA KEV catalog
3. Using AgentLoop + LLM for risk assessment narrative
4. Returning structured triage result
"""

import json
import logging
import re
from typing import Any

from trellis.agent_loop import AgentLoop, AgentLoopResult
from trellis.agents.tools import check_cisa_kev, CISA_KEV_SCHEMA

logger = logging.getLogger("trellis.agents.security_triage")

CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,}")

SYSTEM_PROMPT = """\
You are a security triage analyst. You receive vulnerability reports and \
CISA KEV lookup results, then produce a concise risk assessment.

Given the CVE information and KEV lookup results provided, write a brief \
risk assessment that includes:
- Summary of the vulnerability
- Whether it is in the CISA Known Exploited Vulnerabilities catalog
- Risk level: CRITICAL if any CVE is in KEV, HIGH if CVSS >= 7 or \
description mentions active exploitation, MEDIUM otherwise, LOW if no CVEs found
- Recommended immediate actions

Be concise and actionable. Output plain text, not JSON."""


class SecurityTriageAgent:
    """Multi-step security triage agent using AgentLoop."""

    def __init__(self, agent=None, llm_call=None):
        self.agent = agent
        self.system_prompt = SYSTEM_PROMPT
        self.llm_call = llm_call

    async def process(
        self, envelope, *, db=None, trace_id: str | None = None
    ) -> dict:
        """Process a security envelope through multi-step triage.

        Steps:
        1. Extract CVE IDs from text
        2. Check each against CISA KEV
        3. Build context and run AgentLoop for risk assessment
        4. Return structured result
        """
        # Extract text from envelope
        text = self._extract_text(envelope)

        # Step 1: Extract CVE IDs
        cve_ids = list(dict.fromkeys(CVE_PATTERN.findall(text)))  # unique, ordered
        logger.info("Extracted %d CVE IDs: %s", len(cve_ids), cve_ids)

        # Step 2: KEV lookups for each CVE
        kev_results = {}
        for cve_id in cve_ids:
            kev_results[cve_id] = check_cisa_kev(cve_id)

        any_in_kev = any(r.get("found") for r in kev_results.values())

        # Step 3: Build prompt with KEV context and run AgentLoop
        context_parts = [f"Security alert text:\n{text}\n"]

        if cve_ids:
            context_parts.append(f"CVE IDs found: {', '.join(cve_ids)}\n")
            context_parts.append("CISA KEV lookup results:")
            for cve_id, result in kev_results.items():
                if result.get("found"):
                    vuln = result.get("vulnerability", {})
                    context_parts.append(
                        f"  {cve_id}: FOUND in KEV — {vuln.get('shortDescription', 'N/A')}. "
                        f"Required action: {vuln.get('requiredAction', 'N/A')}. "
                        f"Due date: {vuln.get('dueDate', 'N/A')}."
                    )
                else:
                    context_parts.append(f"  {cve_id}: NOT in KEV catalog")
        else:
            context_parts.append("No CVE IDs found in the alert text.")

        user_message = "\n".join(context_parts)
        user_message += "\n\nProvide your risk assessment."

        loop = AgentLoop(
            system_prompt=self.system_prompt,
            tools=[CISA_KEV_SCHEMA],
            tool_executors={"check_cisa_kev": check_cisa_kev},
            llm_call=self.llm_call,
            model="default",
            temperature=0.3,
            max_steps=3,
        )

        loop_result: AgentLoopResult = await loop.run(user_message)

        # Step 4: Determine risk level from KEV results
        if not cve_ids:
            risk_level = "LOW"
        elif any_in_kev:
            risk_level = "CRITICAL"
        else:
            risk_level = "MEDIUM"

        assessment_text = loop_result.result.get("text", "")

        result_data = {
            "cve_ids": cve_ids,
            "kev_results": kev_results,
            "any_in_kev": any_in_kev,
            "risk_level": risk_level,
            "agent_loop_steps": loop_result.steps,
        }

        # Delegate to ITHelpAgent for CRITICAL CVEs when full context available
        if risk_level == "CRITICAL" and db is not None and trace_id is not None:
            try:
                from trellis.agent_context import AgentContext

                async with AgentContext(
                    agent_id="security-triage",
                    trace_id=trace_id,
                    envelope=envelope,
                    db=db,
                ) as ctx:
                    delegation_text = (
                        f"CRITICAL vulnerability remediation needed. "
                        f"CVEs in CISA KEV: {', '.join(c for c, r in kev_results.items() if r.get('found'))}. "
                        f"Assessment: {assessment_text[:500]}"
                    )
                    delegation_context = {
                        "description": delegation_text,
                        "severity": "critical",
                        "category_hint": "infrastructure",
                        "affected_users": 100,
                        "ticket_id": f"TRL-{trace_id[:8].upper()}",
                        "cve_ids": cve_ids,
                        "kev_results": kev_results,
                        "risk_level": risk_level,
                    }
                    delegation_result = await ctx.delegate(
                        to_agent="it-help",
                        text=delegation_text,
                        context=delegation_context,
                    )
                    if delegation_result.get("status") == "completed":
                        inner = delegation_result.get("result", {})
                        inner_result = inner.get("result", {})
                        inner_data = inner_result.get("data", {})
                        triage = inner_data.get("triage", {})
                        result_data["ticket_id"] = triage.get(
                            "ticket_id", delegation_context["ticket_id"]
                        )
                        result_data["delegation_id"] = delegation_result.get("delegation_id")
                    else:
                        logger.warning(
                            "Delegation to it-help failed: %s",
                            delegation_result.get("error"),
                        )
            except Exception:
                logger.exception("Delegation to ITHelpAgent failed; continuing without ticket")

        return {
            "status": "completed",
            "result": {
                "text": assessment_text,
                "data": result_data,
                "attachments": [],
            },
        }

    @staticmethod
    def _extract_text(envelope) -> str:
        """Pull text content from an envelope (Pydantic object or dict)."""
        # Handle Pydantic Envelope objects (from native dispatcher)
        if hasattr(envelope, "payload"):
            payload = envelope.payload
            if hasattr(payload, "text") and payload.text:
                return payload.text
            if hasattr(payload, "data") and payload.data:
                return json.dumps(payload.data if isinstance(payload.data, dict) else payload.data)
            # Convert to dict and fall through
            if hasattr(envelope, "model_dump"):
                envelope = envelope.model_dump()
            elif hasattr(envelope, "dict"):
                envelope = envelope.dict()
            else:
                return str(envelope)

        # Dict-based envelope shapes
        if isinstance(envelope, dict):
            if "body" in envelope:
                body = envelope["body"]
                if isinstance(body, dict):
                    return body.get("text", body.get("content", json.dumps(body)))
                return str(body)
            if "text" in envelope:
                return envelope["text"]
            if "payload" in envelope:
                payload = envelope["payload"]
                if isinstance(payload, dict):
                    return payload.get("text", payload.get("description", json.dumps(payload)))
                return str(payload)
            if "content" in envelope:
                return envelope["content"]
            return json.dumps(envelope)

        return str(envelope)
