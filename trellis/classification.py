"""Classification Engine — Platform Middleware.

Auto-enriches every envelope's routing_hints before the rules engine sees it.
This is NOT an agent. It runs synchronously in the request path.
No LLM calls. No DB queries. Always on.

Pipeline:
    Raw input → Adapter (build_envelope) → classify_envelope() → Rules Engine → Agent
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from trellis.schemas import Envelope, RoutingHints

logger = logging.getLogger("trellis.classification")

# ── Source-type → category/department map ────────────────────────────────

SOURCE_TYPE_MAP: dict[str, dict[str, str]] = {
    "cisa_kev":     {"category": "security",    "department": "Information Security"},
    "nvd":          {"category": "security",    "department": "Information Security"},
    "nist":         {"category": "security",    "department": "Information Security"},
    "ivanti":       {"category": "incident",    "department": "IT"},
    "servicenow":   {"category": "incident",    "department": "IT"},
    "hr_system":    {"category": "hr",          "department": "HR"},
    "ukg":          {"category": "hr",          "department": "HR"},
    "peoplesoft":   {"category": "hr",          "department": "HR"},
    "epic":         {"category": "clinical",    "department": "Clinical"},
    "claims":       {"category": "revenue",     "department": "Revenue Cycle"},
    "payer":        {"category": "revenue",     "department": "Revenue Cycle"},
    "cms":          {"category": "regulatory",  "department": "Compliance"},
    "healthit_news": {"category": "industry",   "department": "IT"},
    "beckers":      {"category": "industry",    "department": "IT"},
}

# ── Keyword sets per category ─────────────────────────────────────────────

KEYWORD_MAP: dict[str, list[str]] = {
    "security": [
        "cve", "vulnerability", "exploit", "breach", "malware",
        "ransomware", "patch", "firewall",
    ],
    "incident": [
        "ticket", "incident", "outage", "password", "vpn",
        "printer", "network", "server", "error",
    ],
    "hr": [
        "employee", "benefits", "pto", "fmla", "onboarding",
        "payroll", "ada", "workers comp",
    ],
    "revenue": [
        "claim", "denial", "billing", "coding", "payer",
        "reimbursement", "appeal", "co-4", "co-16",
    ],
    "clinical": [
        "patient", "medication", "order", "lab", "radiology",
        "admission", "discharge",
    ],
    "compliance": [
        "hipaa", "regulation", "audit", "cms", "oig",
        "compliance", "policy",
    ],
}

# category → department (for keyword-matched categories)
CATEGORY_DEPARTMENT_MAP: dict[str, str] = {
    "security":   "Information Security",
    "incident":   "IT",
    "hr":         "HR",
    "revenue":    "Revenue Cycle",
    "clinical":   "Clinical",
    "compliance": "Compliance",
}

# ── Critical-severity keywords ────────────────────────────────────────────

CRITICAL_KEYWORDS = ["outage", "down", "breach", "ransomware", "exploited_in_wild"]
HIGH_KEYWORDS = ["urgent", "escalat"]  # prefix match (escalate, escalation)

# ── Tech stack tag extraction ─────────────────────────────────────────────

def _load_tech_stack_names() -> list[str]:
    """Load system names from Health First tech_stack.json for tag extraction."""
    try:
        data_dir = Path(__file__).parent / "agents" / "data"
        ts_path = data_dir / "tech_stack.json"
        with open(ts_path) as f:
            ts = json.load(f)
        names = []
        for sys in ts.get("systems", []):
            name = sys.get("name", "")
            if name:
                names.append(name.lower())
                # Also add shorthand (first word) if multi-word
                first = name.split()[0].lower()
                if first != name.lower() and len(first) > 2:
                    names.append(first)
        return names
    except Exception as e:
        logger.warning(f"Could not load tech_stack.json: {e}")
        return []


_TECH_STACK_NAMES: list[str] = _load_tech_stack_names()

# Known payer names (Health First context)
_PAYER_NAMES = ["medicare", "medicaid", "bcbs", "aetna", "cigna", "humana", "united", "uhc", "florida blue"]

# Denial codes (revenue cycle)
_DENIAL_CODES = ["co-4", "co-16", "co-97", "co-50", "pr-1", "pr-2", "pr-3", "co-45", "co-96"]


# ── Core extraction helpers ───────────────────────────────────────────────

def _extract_text_from_payload(data: dict[str, Any]) -> str:
    """Flatten all string fields from payload.data into one lowercase blob."""
    parts: list[str] = []

    def _recurse(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj.lower())
        elif isinstance(obj, dict):
            for v in obj.values():
                _recurse(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _recurse(item)

    _recurse(data)
    return " ".join(parts)


def _classify_by_keywords(text: str) -> tuple[str | None, str | None]:
    """Return (category, department) by keyword frequency. First wins on tie."""
    scores: dict[str, int] = {}
    for category, keywords in KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[category] = score

    if not scores:
        return None, None

    best = max(scores, key=lambda c: scores[c])
    return best, CATEGORY_DEPARTMENT_MAP.get(best)


def _infer_severity(text: str, payload_data: dict[str, Any]) -> str | None:
    """Infer severity from payload content. Returns 'critical', 'high', or None (→ normal)."""
    # Check CVSS score first
    cvss = _get_nested(payload_data, "cvss_score") or _get_nested(payload_data, "baseScore")
    if cvss is not None:
        try:
            if float(cvss) >= 9.0:
                return "critical"
        except (ValueError, TypeError):
            pass

    # Check exploited-in-wild flag
    if _get_nested(payload_data, "exploited_in_wild") or "exploited_in_wild" in text:
        return "critical"

    for kw in CRITICAL_KEYWORDS:
        if kw in text:
            return "critical"

    for kw in HIGH_KEYWORDS:
        if kw in text:
            return "high"

    return None  # caller will default to "normal"


def _get_nested(data: dict, *keys: str) -> Any:
    """Try multiple key paths in a dict, return first found value."""
    for key in keys:
        # Direct lookup
        if key in data:
            return data[key]
        # Nested path (dot-notation key)
        parts = key.split(".")
        cur = data
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                cur = None
                break
            cur = cur[p]
        if cur is not None:
            return cur
    return None


def _extract_tags(text: str, payload_data: dict[str, Any]) -> list[str]:
    """Extract relevant tags: tech stack systems, payer names, denial codes, CVE IDs."""
    tags: set[str] = set()

    # CVE IDs
    import re
    for match in re.finditer(r"cve-\d{4}-\d+", text):
        tags.add(match.group(0))

    # Tech stack system names
    for name in _TECH_STACK_NAMES:
        if name in text:
            tags.add(name)

    # Payer names
    for payer in _PAYER_NAMES:
        if payer in text:
            tags.add(payer)

    # Denial codes
    for code in _DENIAL_CODES:
        if code in text:
            tags.add(code)

    return sorted(tags)


# ── Main entry point ──────────────────────────────────────────────────────

def classify_envelope(envelope: Envelope) -> Envelope:
    """Enrich envelope.routing_hints with inferred classification.

    Sender-provided hints take priority (explicit > inferred).
    Always adds classification_source and classification_confidence for auditability.
    Never raises — returns envelope unchanged on any error.
    """
    try:
        return _classify_envelope(envelope)
    except Exception as e:
        logger.error(f"Classification engine error (non-fatal): {e}", exc_info=True)
        return envelope


def _classify_envelope(envelope: Envelope) -> Envelope:
    existing = envelope.routing_hints
    source_type = (envelope.source_type or "").lower()

    # Flatten payload text for analysis
    payload_text = (envelope.payload.text or "").lower()
    payload_data = envelope.payload.data or {}
    data_text = _extract_text_from_payload(payload_data)
    full_text = f"{payload_text} {data_text}".strip()

    # ── Step 1: Source-type mapping ───────────────────────────────────────
    inferred_category: str | None = None
    inferred_department: str | None = None
    classification_source = "unknown"
    classification_confidence = "low"

    if source_type in SOURCE_TYPE_MAP:
        mapped = SOURCE_TYPE_MAP[source_type]
        inferred_category = mapped["category"]
        inferred_department = mapped["department"]
        classification_source = "source_type_map"
        classification_confidence = "high"

    # ── Step 2: Keyword fallback ──────────────────────────────────────────
    elif full_text:
        kw_category, kw_department = _classify_by_keywords(full_text)
        if kw_category:
            inferred_category = kw_category
            inferred_department = kw_department
            classification_source = "keyword_analysis"
            classification_confidence = "medium"

    # ── Step 3: Severity inference ────────────────────────────────────────
    inferred_severity = _infer_severity(full_text, payload_data) or "normal"

    # ── Step 4: Tag extraction ────────────────────────────────────────────
    inferred_tags = _extract_tags(full_text, payload_data)

    # ── Merge: sender hints take priority ─────────────────────────────────
    final_category = existing.category or inferred_category
    final_department = existing.department or inferred_department

    # Merge tags (union, preserving existing)
    existing_tags = list(existing.tags or [])
    merged_tags = existing_tags + [t for t in inferred_tags if t not in existing_tags]

    # Build enriched routing hints
    # We store classification metadata in a dict, then reconstruct RoutingHints
    # RoutingHints doesn't have severity/classification fields — we'll store them
    # in envelope.payload.data["_classification"] for auditability
    classification_meta = {
        "category": final_category,
        "department": final_department,
        "severity": inferred_severity,
        "tags": merged_tags,
        "classification_source": classification_source,
        "classification_confidence": classification_confidence,
    }

    # Update routing_hints (Pydantic model — recreate with merged values)
    new_hints = RoutingHints(
        agent_id=existing.agent_id,
        department=final_department,
        category=final_category,
        tags=merged_tags,
    )

    # Also update metadata priority if severity is higher than current
    new_metadata = envelope.metadata.model_copy()
    current_priority = (envelope.metadata.priority or "normal").lower()
    priority_order = {"normal": 0, "high": 1, "critical": 2}
    inferred_priority = "critical" if inferred_severity == "critical" else (
        "high" if inferred_severity == "high" else "normal"
    )
    if priority_order.get(inferred_priority, 0) > priority_order.get(current_priority, 0):
        new_metadata = envelope.metadata.model_copy(update={"priority": inferred_priority.upper()})

    # Attach classification metadata to payload.data for auditability
    new_data = dict(payload_data)
    new_data["_classification"] = classification_meta

    new_payload = envelope.payload.model_copy(update={"data": new_data})

    enriched = envelope.model_copy(update={
        "routing_hints": new_hints,
        "metadata": new_metadata,
        "payload": new_payload,
    })

    logger.debug(
        f"Classified envelope {envelope.envelope_id}: "
        f"source={source_type} → category={final_category}, "
        f"department={final_department}, severity={inferred_severity}, "
        f"confidence={classification_confidence}"
    )

    return enriched
