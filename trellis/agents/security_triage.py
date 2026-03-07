"""Security Triage Agent — real tool-calling agent, not a prompt wrapper.

Processes vulnerability alerts, cross-references against HF tech stack,
scores risk, and drafts structured advisories.
"""

import json
import logging
import time
from datetime import datetime, timezone

from trellis.agents.tools import (
    calculate_risk_score,
    check_cisa_kev,
    get_cvss_details,
    lookup_tech_stack,
)

logger = logging.getLogger("trellis.agents.security_triage")


class SecurityTriageAgent:
    """Native agent that processes security vulnerability events."""

    def __init__(self, agent):
        self.agent = agent
        self.llm_config = getattr(agent, "llm_config", None) or {}

    async def process(self, envelope) -> dict:
        """Full triage pipeline: parse → enrich → score → advise."""
        start = time.monotonic()

        # 1. Parse the vulnerability payload
        if hasattr(envelope, "model_dump"):
            env_dict = envelope.model_dump()
        elif isinstance(envelope, dict):
            env_dict = envelope
        else:
            env_dict = {"payload": {}}

        payload = env_dict.get("payload", {})
        # Payload fields may be in payload.data (structured) or payload top-level
        payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
        merged_payload = {**payload_data, **payload}
        vuln = self._parse_vulnerability(merged_payload)

        # 2. Call tools to enrich
        tech_result = lookup_tech_stack(vuln["product"], vuln["vendor"])
        kev_result = check_cisa_kev(vuln["cve_id"])
        cvss_result = get_cvss_details(vuln["cve_id"], vuln["cvss_score"], vuln["severity"])

        # Determine exposure
        hf_exposed = tech_result["exposed"]
        top_match = tech_result["matches"][0] if tech_result["matches"] else None
        system_criticality = top_match["criticality"] if top_match else "medium"

        # Use payload's exploited_in_wild if CISA KEV check returned unknown
        exploited = vuln.get("exploited_in_wild", False)
        if kev_result.get("in_kev") is True:
            exploited = True

        # 3. Calculate composite risk score
        risk = calculate_risk_score(
            cvss=cvss_result["cvss_score"],
            exploited=exploited,
            hf_exposed=hf_exposed,
            system_criticality=system_criticality,
        )

        # 4. Build the structured advisory (tool-generated, no LLM needed)
        advisory = self._build_advisory(vuln, tech_result, kev_result, cvss_result, risk)

        # 5. Optionally enhance with LLM (graceful degradation if unavailable)
        llm_enhanced = False
        llm_narrative = None
        try:
            llm_narrative = await self._llm_enhance(vuln, tech_result, risk, advisory)
            if llm_narrative:
                advisory["llm_narrative"] = llm_narrative
                llm_enhanced = True
        except Exception as e:
            logger.info(f"LLM enhancement skipped (graceful degradation): {e}")

        latency_ms = int((time.monotonic() - start) * 1000)

        return {
            "status": "completed",
            "result": {
                "text": self._format_text_summary(advisory),
                "data": {
                    "advisory": advisory,
                    "tool_calls": [
                        {"tool": "lookup_tech_stack", "result": tech_result},
                        {"tool": "check_cisa_kev", "result": kev_result},
                        {"tool": "get_cvss_details", "result": cvss_result},
                        {"tool": "calculate_risk_score", "result": risk},
                    ],
                    "llm_enhanced": llm_enhanced,
                    "latency_ms": latency_ms,
                    "agent_type": "native",
                },
                "attachments": [],
            },
        }

    def _parse_vulnerability(self, payload: dict) -> dict:
        """Extract vulnerability fields from event payload."""
        return {
            "cve_id": payload.get("cve_id", "UNKNOWN"),
            "title": payload.get("title", "Unknown Vulnerability"),
            "vendor": payload.get("vendor", ""),
            "product": payload.get("product", ""),
            "severity": payload.get("severity", ""),
            "cvss_score": payload.get("cvss_score"),
            "description": payload.get("description", ""),
            "exploited_in_wild": payload.get("exploited_in_wild", False),
            "date_added": payload.get("date_added", ""),
        }

    def _build_advisory(self, vuln, tech, kev, cvss, risk) -> dict:
        """Build structured advisory from tool results."""
        affected_systems = []
        for m in tech.get("matches", []):
            affected_systems.append({
                "system": m["system"],
                "category": m["category"],
                "vendor": m["vendor"],
                "criticality": m["criticality"],
                "match_confidence": m["match_confidence"],
            })

        # Recommended actions based on priority
        actions = []
        if risk["priority"] == "CRITICAL":
            actions = [
                "IMMEDIATELY notify CISO Kim Alkire and Security Operations team",
                f"Assess all {vuln['product']} instances for vulnerability exposure",
                "Implement emergency patch or compensating controls within 24 hours",
                "Enable enhanced monitoring on affected systems via CrowdStrike/Sentinel",
                "Brief IT leadership (Michael Carr, CIO) on exposure and remediation plan",
                "Document incident in Ivanti SM for compliance tracking",
            ]
        elif risk["priority"] == "HIGH":
            actions = [
                "Notify Security Operations team for assessment",
                f"Schedule emergency patching for {vuln['product']} within 72 hours",
                "Review CrowdStrike detections for related IOCs",
                "Create Ivanti SM ticket for tracking",
            ]
        elif risk["priority"] == "MEDIUM":
            actions = [
                f"Add {vuln['product']} patch to next maintenance window",
                "Review security posture of affected systems",
                "Create Ivanti SM ticket for tracking",
            ]
        else:
            actions = [
                f"Schedule {vuln['product']} patch in next cycle",
                "Monitor for escalation in threat landscape",
            ]

        # Escalation path
        if risk["priority"] in ("CRITICAL", "HIGH"):
            escalation = [
                "Level 1: Security Operations Center (SOC)",
                "Level 2: Kim Alkire, CISO",
                "Level 3: Michael Carr, CIO",
                "Level 4: Executive Leadership Team",
            ]
        else:
            escalation = [
                "Level 1: Security Operations Center (SOC)",
                "Level 2: Kim Alkire, CISO (if escalation needed)",
            ]

        return {
            "cve_id": vuln["cve_id"],
            "title": vuln["title"],
            "executive_summary": (
                f"{vuln['title']} ({vuln['cve_id']}) affects {vuln['vendor']} {vuln['product']}. "
                f"CVSS: {cvss['cvss_score']}/10 ({cvss['severity']}). "
                f"{'ACTIVELY EXPLOITED IN THE WILD. ' if vuln.get('exploited_in_wild') else ''}"
                f"Health First exposure: {'YES — ' + ', '.join(m['system'] for m in tech.get('matches', [])) if tech['exposed'] else 'No direct match in known tech stack'}. "
                f"Risk priority: {risk['priority']} (score: {risk['composite_score']}/100)."
            ),
            "risk_score": risk,
            "affected_systems": affected_systems,
            "hf_exposed": tech["exposed"],
            "exploited_in_wild": vuln.get("exploited_in_wild", False),
            "recommended_actions": actions,
            "remediation_timeline": risk["remediation_timeline"],
            "escalation_path": escalation,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _format_text_summary(self, advisory: dict) -> str:
        """Format advisory as readable text for the activity feed."""
        lines = [
            f"🔒 SECURITY ADVISORY: {advisory['title']}",
            f"CVE: {advisory['cve_id']} | Priority: {advisory['risk_score']['priority']}",
            "",
            advisory["executive_summary"],
            "",
            f"Risk Score: {advisory['risk_score']['composite_score']}/100",
            f"Timeline: {advisory['remediation_timeline']}",
            "",
            "Recommended Actions:",
        ]
        for i, action in enumerate(advisory["recommended_actions"], 1):
            lines.append(f"  {i}. {action}")

        if advisory.get("llm_narrative"):
            lines.extend(["", "--- LLM-Enhanced Analysis ---", advisory["llm_narrative"]])

        return "\n".join(lines)

    async def _llm_enhance(self, vuln, tech, risk, advisory) -> str | None:
        """Use LLM via gateway cost pipeline to draft a narrative advisory. Returns None on failure."""
        try:
            from trellis.gateway import (
                _providers, MODEL_PROVIDER_MAP, log_cost_event, calculate_cost,
            )
            from trellis.database import async_session
        except ImportError:
            return None

        model = self.llm_config.get("model", "meta/llama-3.3-70b-instruct")
        system_prompt = self.llm_config.get("system_prompt", "You are a security analyst.")

        prompt = (
            f"Write a concise security advisory narrative for this vulnerability:\n\n"
            f"CVE: {vuln['cve_id']}\n"
            f"Title: {vuln['title']}\n"
            f"CVSS: {vuln.get('cvss_score', 'N/A')}/10\n"
            f"Exploited in wild: {vuln.get('exploited_in_wild', False)}\n"
            f"Description: {vuln.get('description', 'N/A')}\n"
            f"HF Exposed: {tech['exposed']}\n"
            f"Matched Systems: {json.dumps(tech.get('matches', []))}\n"
            f"Risk Priority: {risk['priority']} ({risk['composite_score']}/100)\n\n"
            f"Write 2-3 paragraphs: situational context, impact to Health First specifically, "
            f"and recommended immediate actions. Be direct and actionable. No boilerplate."
        )

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.llm_config.get("temperature", 0.1),
            "max_tokens": self.llm_config.get("max_tokens", 4096),
            "stream": False,
        }

        provider_name = MODEL_PROVIDER_MAP.get(model, "nvidia")
        provider = _providers.get(provider_name)
        configured = getattr(provider, "available", getattr(provider, "is_configured", lambda: False))
        if not provider or not (configured() if callable(configured) else configured):
            provider = _providers.get("ollama")
            if not provider:
                return None

        start = time.monotonic()
        result = await provider.chat_completion(body)
        latency_ms = int((time.monotonic() - start) * 1000)

        # Log cost through the gateway pipeline
        usage = result.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        prov_name = getattr(provider, "name", provider_name)

        try:
            async with async_session() as db:
                await log_cost_event(
                    db, agent_id=self.agent.agent_id, trace_id=None,
                    model_requested=model, model_used=model,
                    provider=prov_name, tokens_in=tokens_in, tokens_out=tokens_out,
                    latency_ms=latency_ms, has_tool_calls=False,
                )
        except Exception as e:
            logger.warning(f"Failed to log LLM cost event: {e}")

        choices = result.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return None
