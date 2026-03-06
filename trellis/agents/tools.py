"""Security Triage Agent tools — self-contained, no external APIs needed."""

import json
from pathlib import Path
from difflib import SequenceMatcher

_DATA_DIR = Path(__file__).parent / "data"
_tech_stack: list[dict] | None = None


def _load_tech_stack() -> list[dict]:
    global _tech_stack
    if _tech_stack is None:
        with open(_DATA_DIR / "tech_stack.json") as f:
            _tech_stack = json.load(f)["systems"]
    return _tech_stack


def _fuzzy_match(a: str, b: str) -> float:
    """Case-insensitive fuzzy match ratio."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def lookup_tech_stack(product: str, vendor: str = "") -> dict:
    """Check if a product/vendor is in Health First's tech stack.

    Returns matching systems with match confidence.
    """
    systems = _load_tech_stack()
    matches = []

    for sys in systems:
        # Check product name match
        name_score = max(
            _fuzzy_match(product, sys["name"]),
            # Also check if product contains the system name or vice versa
            1.0 if sys["name"].lower() in product.lower() else 0.0,
            1.0 if product.lower() in sys["name"].lower() else 0.0,
        )

        # Check vendor match
        vendor_score = 0.0
        if vendor:
            vendor_score = max(
                _fuzzy_match(vendor, sys["vendor"]),
                1.0 if sys["vendor"].lower() in vendor.lower() else 0.0,
                1.0 if vendor.lower() in sys["vendor"].lower() else 0.0,
            )

        # Combined score: product match is primary, vendor is secondary
        combined = name_score * 0.7 + vendor_score * 0.3 if vendor else name_score

        if combined >= 0.4:
            matches.append({
                "system": sys["name"],
                "category": sys["category"],
                "vendor": sys["vendor"],
                "criticality": sys["criticality"],
                "match_confidence": round(combined, 2),
                "modules": sys.get("modules"),
            })

    matches.sort(key=lambda m: m["match_confidence"], reverse=True)

    return {
        "exposed": len(matches) > 0,
        "matches": matches[:5],  # Top 5
        "query": {"product": product, "vendor": vendor},
    }


def check_cisa_kev(cve_id: str) -> dict:
    """Check if CVE is in CISA Known Exploited Vulnerabilities catalog.

    Uses payload data if available, otherwise returns unknown status.
    """
    # In production, this would query a local CISA KEV cache/DB.
    # For now, we rely on the event payload's exploited_in_wild field
    # and return a structured response.
    return {
        "cve_id": cve_id,
        "in_kev": None,  # None = unknown (no local cache yet)
        "source": "payload_metadata",
        "note": "CISA KEV local cache not yet populated. Using event payload metadata.",
    }


def get_cvss_details(cve_id: str, cvss_score: float | None = None, severity: str | None = None) -> dict:
    """Return CVSS score breakdown. Uses payload data when available."""
    score = cvss_score or 0.0
    if severity:
        sev = severity.upper()
    elif score >= 9.0:
        sev = "CRITICAL"
    elif score >= 7.0:
        sev = "HIGH"
    elif score >= 4.0:
        sev = "MEDIUM"
    else:
        sev = "LOW"

    return {
        "cve_id": cve_id,
        "cvss_score": score,
        "severity": sev,
        "source": "event_payload" if cvss_score else "estimated",
    }


def calculate_risk_score(
    cvss: float,
    exploited: bool,
    hf_exposed: bool,
    system_criticality: str | None = None,
) -> dict:
    """Calculate composite risk score for Health First.

    Formula: base_score × exploitability_multiplier × exposure_multiplier × criticality_multiplier
    """
    # Normalize CVSS to 0-1
    base = cvss / 10.0

    # Exploitability: known exploited = 1.5x, unknown = 1.0x
    exploit_mult = 1.5 if exploited else 1.0

    # Exposure: in HF stack = 1.5x, not in stack = 0.3x
    exposure_mult = 1.5 if hf_exposed else 0.3

    # System criticality multiplier
    crit_map = {"critical": 1.5, "high": 1.2, "medium": 1.0, "low": 0.7}
    crit_mult = crit_map.get((system_criticality or "medium").lower(), 1.0)

    # Composite score (0-100 scale)
    raw = base * exploit_mult * exposure_mult * crit_mult * 100
    composite = min(100.0, round(raw, 1))

    # Priority bucket
    if composite >= 80:
        priority = "CRITICAL"
    elif composite >= 60:
        priority = "HIGH"
    elif composite >= 35:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    # Timeline based on priority
    timelines = {
        "CRITICAL": "Immediate action required — patch/mitigate within 24 hours",
        "HIGH": "Patch/mitigate within 72 hours",
        "MEDIUM": "Patch within standard maintenance window (7-14 days)",
        "LOW": "Address in next scheduled patch cycle (30 days)",
    }

    return {
        "composite_score": composite,
        "priority": priority,
        "breakdown": {
            "cvss_base": cvss,
            "exploitability_multiplier": exploit_mult,
            "exposure_multiplier": exposure_mult,
            "criticality_multiplier": crit_mult,
        },
        "remediation_timeline": timelines[priority],
    }
