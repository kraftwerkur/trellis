"""Trellis agent tools — self-contained, no external APIs needed."""

import json
import time
from pathlib import Path
from difflib import SequenceMatcher

import httpx

_DATA_DIR = Path(__file__).parent / "data"
_tech_stack: list[dict] | None = None

# ── CISA KEV cache ─────────────────────────────────────────────────
_CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_CISA_KEV_TTL = 3600  # 1 hour
_cisa_kev_cache: dict[str, dict] | None = None
_cisa_kev_cache_ts: float = 0.0

CISA_KEV_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_cisa_kev",
        "description": "Check if a CVE ID is in the CISA Known Exploited Vulnerabilities catalog",
        "parameters": {
            "type": "object",
            "properties": {"cve_id": {"type": "string", "description": "CVE identifier (e.g. CVE-2024-1234)"}},
            "required": ["cve_id"]
        }
    }
}


def _fetch_cisa_kev() -> dict[str, dict]:
    """Fetch the CISA KEV catalog and return a dict keyed by CVE ID."""
    global _cisa_kev_cache, _cisa_kev_cache_ts
    now = time.time()
    if _cisa_kev_cache is not None and (now - _cisa_kev_cache_ts) < _CISA_KEV_TTL:
        return _cisa_kev_cache

    resp = httpx.get(_CISA_KEV_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    _cisa_kev_cache = {
        v["cveID"]: v for v in data.get("vulnerabilities", [])
    }
    _cisa_kev_cache_ts = now
    return _cisa_kev_cache


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
    """Check if a CVE ID is in the CISA Known Exploited Vulnerabilities catalog.

    Fetches the catalog from CISA (cached for 1 hour) and looks up the CVE.
    Returns {found: bool, vulnerability: {...} | None} on success,
    or {found: False, error: "..."} on network failure.
    """
    try:
        catalog = _fetch_cisa_kev()
    except Exception as exc:
        return {"found": False, "vulnerability": None, "error": str(exc)}

    cve_upper = cve_id.strip().upper()
    entry = catalog.get(cve_upper)
    if entry is None:
        return {"found": False, "vulnerability": None}

    return {
        "found": True,
        "vulnerability": {
            "cveID": entry.get("cveID"),
            "vendorProject": entry.get("vendorProject"),
            "product": entry.get("product"),
            "dateAdded": entry.get("dateAdded"),
            "shortDescription": entry.get("shortDescription"),
            "requiredAction": entry.get("requiredAction"),
            "dueDate": entry.get("dueDate"),
        },
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


# ── IT Help Desk Tools ──────────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "network": ["vpn", "wifi", "network", "connectivity", "dns", "dhcp", "firewall", "arista", "cisco", "anyconnect", "internet"],
    "application": ["epic", "peoplesoft", "ukg", "8x8", "sailpoint", "app", "application", "software", "login", "access", "error", "crash"],
    "endpoint": ["printer", "laptop", "desktop", "monitor", "keyboard", "mouse", "docking", "hardware", "pc", "workstation"],
    "access": ["password", "account", "locked", "mfa", "reset", "permissions", "role", "unlock", "credentials", "sso"],
    "infrastructure": ["server", "storage", "nutanix", "azure", "vm", "virtual", "backup", "disk", "cpu", "memory", "outage"],
}

_KNOWN_RESOLUTIONS = {
    "password_reset": "Direct to self-service portal at password.hf.org, or IAM team for locked accounts",
    "vpn_connectivity": "Check Cisco AnyConnect version, clear DNS cache, verify MFA token",
    "printer_issues": "Restart print spooler, check queue, verify network path",
    "epic_access": "Submit access request via ServiceNow, requires manager approval",
    "email_8x8": "Check 8x8 app version, clear cache, verify network connectivity",
    "account_lockout": "Check AD lockout status, verify no brute-force, unlock via IAM",
    "app_error": "Collect screenshots, check application logs, restart application",
}

_RESOLUTION_PATTERNS = {
    "password": "password_reset", "reset": "password_reset", "locked out": "account_lockout",
    "lockout": "account_lockout", "vpn": "vpn_connectivity", "anyconnect": "vpn_connectivity",
    "printer": "printer_issues", "print": "printer_issues", "epic": "epic_access",
    "8x8": "email_8x8", "phone": "email_8x8",
}

_TEAM_MAP = {
    "network": "Network Ops",
    "application": "App Support",
    "endpoint": "Desktop Support",
    "access": "IAM",
    "infrastructure": "Infrastructure",
}


def classify_ticket(description: str, category_hint: str | None = None) -> dict:
    """Classify an IT ticket by category based on keyword matching."""
    desc_lower = description.lower()
    scores: dict[str, int] = {}
    matched_keywords: list[str] = []

    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scores[category] = score
            matched_keywords.extend(kw for kw in keywords if kw in desc_lower)

    if category_hint and category_hint in _CATEGORY_KEYWORDS:
        scores[category_hint] = scores.get(category_hint, 0) + 3

    if not scores:
        return {"category": "application", "subcategory": "general", "keywords": []}

    best = max(scores, key=scores.get)
    # Determine subcategory from matched keywords
    subcategory = "general"
    for kw in matched_keywords:
        if kw in _RESOLUTION_PATTERNS:
            subcategory = _RESOLUTION_PATTERNS[kw]
            break

    return {"category": best, "subcategory": subcategory, "keywords": list(set(matched_keywords))}


def lookup_known_resolution(category: str, keywords: list[str]) -> str | None:
    """Look up a known resolution for common IT issues."""
    for kw in keywords:
        pattern_key = _RESOLUTION_PATTERNS.get(kw)
        if pattern_key and pattern_key in _KNOWN_RESOLUTIONS:
            return _KNOWN_RESOLUTIONS[pattern_key]
    return None


def assess_priority(severity: str | None, affected_users: int = 1, system_criticality: str | None = None) -> dict:
    """Assess ticket priority based on impact and urgency."""
    severity = (severity or "low").lower()
    sev_score = {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 1)
    crit_score = {"tier_1": 4, "tier_2": 3, "tier_3": 2}.get(system_criticality or "", 1)
    user_score = 4 if affected_users > 100 else 3 if affected_users > 10 else 2 if affected_users > 1 else 1

    composite = (sev_score * 2 + crit_score * 2 + user_score) / 5
    if composite >= 3.5:
        priority = "CRITICAL"
    elif composite >= 2.5:
        priority = "HIGH"
    elif composite >= 1.5:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    return {
        "priority": priority,
        "justification": f"Severity={severity}, affected_users={affected_users}, system_criticality={system_criticality or 'unknown'}",
    }


# ── SAM-HR Tools ────────────────────────────────────────────────────

_HR_CATEGORY_KEYWORDS = {
    "benefits": ["benefits", "enrollment", "insurance", "dental", "vision", "medical", "hsa", "fsa", "401k", "cobra", "open enrollment"],
    "payroll": ["payroll", "paycheck", "salary", "wage", "overtime", "direct deposit", "withholding", "garnishment", "tax", "w2", "discrepancy"],
    "pto": ["pto", "vacation", "sick", "time off", "leave", "holiday", "paid time", "absence", "ukg"],
    "onboarding": ["onboarding", "new hire", "new employee", "orientation", "start date", "first day", "servicenow", "provisioning", "badge"],
    "offboarding": ["offboarding", "termination", "resign", "resignation", "separation", "exit", "last day", "final paycheck"],
    "policy": ["policy", "handbook", "procedure", "rule", "guideline", "code of conduct", "dress code"],
    "compliance": ["compliance", "audit", "hipaa", "regulation", "investigation", "ethics", "reporting", "whistleblower"],
    "workers_comp": ["workers comp", "workers compensation", "work injury", "workplace injury", "accident", "osha", "incident report"],
    "fmla": ["fmla", "family leave", "medical leave", "maternity", "paternity", "parental leave", "serious health", "caregiver leave"],
    "ada": ["ada", "accommodation", "disability", "reasonable accommodation", "accessibility", "impairment", "medical restriction"],
}

_HR_REGULATORY_FLAGS = {
    "fmla": ["FMLA"],
    "ada": ["ADA"],
    "workers_comp": ["Workers Comp", "OSHA"],
    "compliance": ["HIPAA", "Regulatory"],
}

_HR_POLICIES = {
    "pto": {
        "policy_reference": "HR-301: PTO Policy",
        "standard_procedure": "Submit via UKG Self-Service. Manager approval required. Policy HR-301.",
    },
    "benefits": {
        "policy_reference": "HR-201: Benefits Enrollment Policy",
        "standard_procedure": "Open enrollment Oct 15-Nov 15. Mid-year changes require qualifying life event. Policy HR-201.",
    },
    "fmla": {
        "policy_reference": "HR-401: FMLA Leave Policy",
        "standard_procedure": "12 weeks unpaid leave for eligible employees. Must file with HR within 30 days. Policy HR-401. REGULATORY.",
    },
    "ada": {
        "policy_reference": "HR-402: ADA Accommodation Policy",
        "standard_procedure": "Reasonable accommodation request process. Interactive dialogue required. Policy HR-402. REGULATORY.",
    },
    "payroll": {
        "policy_reference": "HR-501: Payroll Discrepancy Policy",
        "standard_procedure": "Submit correction via PeopleSoft. Processed in next pay cycle. Policy HR-501.",
    },
    "onboarding": {
        "policy_reference": "HR-101: Onboarding Policy",
        "standard_procedure": "Standard 90-day onboarding plan. IT provisioning via ServiceNow. Policy HR-101.",
    },
    "workers_comp": {
        "policy_reference": "HR-403: Workers Compensation Policy",
        "standard_procedure": "Report within 24 hours to supervisor and HR. File with carrier. Policy HR-403. REGULATORY.",
    },
    "offboarding": {
        "policy_reference": "HR-102: Offboarding Policy",
        "standard_procedure": "Complete separation checklist. Final paycheck per state law. Return all equipment. Policy HR-102.",
    },
    "compliance": {
        "policy_reference": "HR-601: Compliance & Ethics Policy",
        "standard_procedure": "Report via ethics hotline or direct to Compliance. Investigations conducted per HR-601. REGULATORY.",
    },
    "policy": {
        "policy_reference": "HR-001: Employee Handbook",
        "standard_procedure": "Refer to current Employee Handbook. Policy questions routed to HR Generalist. Policy HR-001.",
    },
}

_HR_SLA_HOURS = {
    "CRITICAL": 4,
    "HIGH": 24,
    "MEDIUM": 48,
    "LOW": 72,
}

# Regulatory categories always get HIGH priority minimum
_REGULATORY_CATEGORIES = {"fmla", "ada", "workers_comp", "compliance"}


def classify_hr_case(description: str, category_hint: str | None = None) -> dict:
    """Classify an HR case by category based on keyword matching."""
    desc_lower = description.lower()
    scores: dict[str, int] = {}
    matched_keywords: list[str] = []

    for category, keywords in _HR_CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scores[category] = score
            matched_keywords.extend(kw for kw in keywords if kw in desc_lower)

    if category_hint and category_hint in _HR_CATEGORY_KEYWORDS:
        scores[category_hint] = scores.get(category_hint, 0) + 3

    if not scores:
        best = "policy"
        subcategory = "general"
    else:
        best = max(scores, key=scores.get)
        subcategory = best

    # Determine regulatory flags
    regulatory_flags = list(_HR_REGULATORY_FLAGS.get(best, []))

    return {
        "category": best,
        "subcategory": subcategory,
        "keywords": list(set(matched_keywords)),
        "regulatory_flags": regulatory_flags,
    }


def assess_hr_priority(category: str, regulatory_flags: list[str], affected_employees: int = 1) -> dict:
    """Assess HR case priority based on category, regulatory flags, and employee impact."""
    # Regulatory cases are always HIGH minimum
    if regulatory_flags or category in _REGULATORY_CATEGORIES:
        base_priority = "HIGH"
        justification = f"{category.upper()} has regulatory compliance requirements"
    elif affected_employees > 50:
        base_priority = "HIGH"
        justification = f"Large employee impact: {affected_employees} employees affected"
    elif affected_employees > 10:
        base_priority = "MEDIUM"
        justification = f"Moderate employee impact: {affected_employees} employees affected"
    else:
        base_priority = "LOW"
        justification = f"Standard HR case, {affected_employees} employee(s) affected"

    # Workers comp gets CRITICAL (24h report requirement)
    if category == "workers_comp":
        base_priority = "CRITICAL"
        justification = "Workers comp must be reported within 24 hours — legal requirement"

    sla_hours = _HR_SLA_HOURS.get(base_priority, 72)

    return {
        "priority": base_priority,
        "sla_hours": sla_hours,
        "justification": justification,
    }


def lookup_hr_policy(category: str, keywords: list[str]) -> dict:
    """Look up HR policy reference and standard procedure for a case category."""
    policy = _HR_POLICIES.get(category, _HR_POLICIES["policy"])
    return {
        "policy_reference": policy["policy_reference"],
        "standard_procedure": policy["standard_procedure"],
    }


# ── Revenue Cycle Tools ─────────────────────────────────────────────

_RC_CATEGORY_KEYWORDS = {
    "denial_appeal": ["denial", "denied", "appeal", "rejected", "not covered", "co-4", "co-16", "co-45", "co-97", "co-29", "co-50"],
    "coding_review": ["coding", "cpt", "icd", "modifier", "diagnosis", "procedure code", "unbundling", "upcoding", "co-4"],
    "billing_inquiry": ["billing", "bill", "statement", "balance", "patient balance", "charge", "invoice", "payment plan"],
    "ar_followup": ["ar", "accounts receivable", "aging", "follow up", "unpaid", "outstanding", "claim status", "resubmit"],
    "compliance": ["compliance", "audit", "hipaa", "fraud", "waste", "abuse", "oa-23", "overpayment", "refund", "recoupment"],
    "prior_auth": ["prior auth", "preauthorization", "pre-auth", "authorization", "auth", "precertification"],
    "credentialing": ["credentialing", "credential", "provider enrollment", "npi", "ptan", "taxonomy", "network"],
    "charge_capture": ["charge capture", "missed charge", "late charge", "charge entry", "cdm", "chargemaster"],
    "underpayment": ["underpayment", "underpaid", "short pay", "fee schedule", "co-45", "contractual", "eob"],
    "bad_debt": ["bad debt", "write off", "collection", "charity care", "financial assistance", "indigent", "uninsured"],
}

_RC_DENIAL_CODES = {
    "CO-4": "Procedure code inconsistent with modifier or modifier required",
    "CO-16": "Claim/service lacks information or submission/billing error",
    "CO-45": "Charges exceed fee schedule/maximum allowable",
    "CO-97": "Payment adjusted — already adjudicated",
    "PR-1": "Deductible amount",
    "PR-2": "Coinsurance amount",
    "CO-29": "Time limit for filing has expired",
    "CO-50": "Non-covered service — not deemed medically necessary",
    "OA-23": "Impact of prior payer adjudication",
}

_RC_DENIAL_RESOLUTION = {
    "CO-4": {
        "root_cause": "Modifier missing or incorrect on procedure code",
        "resolution_steps": ["Review procedure and modifier pairing", "Correct modifier per CPT guidelines", "Resubmit claim with corrected modifier"],
        "appeal_template_ref": "APPEAL-MOD-001",
    },
    "CO-16": {
        "root_cause": "Missing or invalid claim information",
        "resolution_steps": ["Identify missing fields from remittance", "Obtain missing documentation", "Correct and resubmit claim"],
        "appeal_template_ref": "APPEAL-INFO-001",
    },
    "CO-45": {
        "root_cause": "Billed amount exceeds payer fee schedule",
        "resolution_steps": ["Verify contractual adjustment applied", "Review fee schedule for service", "If underpaid, calculate variance and appeal"],
        "appeal_template_ref": "APPEAL-FEE-001",
    },
    "CO-97": {
        "root_cause": "Claim previously adjudicated — possible duplicate or COB issue",
        "resolution_steps": ["Check prior adjudication details", "Verify COB order", "If COB: resubmit with prior EOB attached"],
        "appeal_template_ref": "APPEAL-DUP-001",
    },
    "PR-1": {
        "root_cause": "Patient deductible applies",
        "resolution_steps": ["Verify deductible accumulator", "Bill patient for deductible amount", "Send patient statement"],
        "appeal_template_ref": None,
    },
    "PR-2": {
        "root_cause": "Patient coinsurance applies",
        "resolution_steps": ["Calculate coinsurance per EOB", "Bill patient for coinsurance", "Send patient statement"],
        "appeal_template_ref": None,
    },
    "CO-29": {
        "root_cause": "Claim submitted past timely filing limit",
        "resolution_steps": ["Document original submission date proof", "Obtain proof of timely filing (clearinghouse receipt)", "Appeal with timely filing exception documentation"],
        "appeal_template_ref": "APPEAL-TF-001",
    },
    "CO-50": {
        "root_cause": "Service not deemed medically necessary by payer",
        "resolution_steps": ["Obtain clinical documentation supporting necessity", "Request peer-to-peer review if clinical denial", "Submit appeal with medical records and clinical notes"],
        "appeal_template_ref": "APPEAL-MED-NEC-001",
    },
    "OA-23": {
        "root_cause": "Primary payer adjudication affects secondary payment",
        "resolution_steps": ["Attach primary payer EOB to secondary claim", "Verify COB setup is correct", "Resubmit to secondary with primary EOB"],
        "appeal_template_ref": "APPEAL-COB-001",
    },
}

_RC_PRIORITY_AMOUNTS = {
    "CRITICAL": 50000.0,
    "HIGH": 10000.0,
    "MEDIUM": 2500.0,
}

_RC_HIGH_PRIORITY_CATEGORIES = {"denial_appeal", "compliance", "prior_auth"}


def classify_rev_cycle_case(description: str, category_hint: str | None = None) -> dict:
    """Classify a revenue cycle case by category using keyword matching.

    Returns category, subcategory, matched keywords, and detected denial codes.
    """
    desc_lower = description.lower()
    scores: dict[str, int] = {}
    matched_keywords: list[str] = []

    for category, keywords in _RC_CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scores[category] = score
            matched_keywords.extend(kw for kw in keywords if kw in desc_lower)

    if category_hint and category_hint in _RC_CATEGORY_KEYWORDS:
        scores[category_hint] = scores.get(category_hint, 0) + 3

    if not scores:
        best = "billing_inquiry"
        subcategory = "general"
    else:
        best = max(scores, key=scores.get)
        subcategory = best

    # Detect denial codes mentioned in description
    denial_codes = [code for code in _RC_DENIAL_CODES if code.lower() in desc_lower]

    return {
        "category": best,
        "subcategory": subcategory,
        "keywords": list(set(matched_keywords)),
        "denial_codes": denial_codes,
    }


def analyze_denial(denial_code: str, payer: str, amount: float) -> dict:
    """Analyze a denial code and return root cause, resolution steps, and appeal template.

    Args:
        denial_code: Standard denial reason code (e.g., "CO-4", "CO-16")
        payer: Payer name (for context)
        amount: Claim dollar amount

    Returns:
        root_cause, resolution_steps, appeal_template_ref, denial_description
    """
    code_upper = denial_code.upper()
    description = _RC_DENIAL_CODES.get(code_upper, "Unknown denial reason code")
    resolution = _RC_DENIAL_RESOLUTION.get(code_upper, {
        "root_cause": "Review denial reason with payer",
        "resolution_steps": ["Contact payer for clarification", "Review remittance advice", "Determine appeal eligibility"],
        "appeal_template_ref": "APPEAL-GENERAL-001",
    })

    return {
        "denial_code": code_upper,
        "denial_description": description,
        "payer": payer,
        "amount": amount,
        "root_cause": resolution["root_cause"],
        "resolution_steps": resolution["resolution_steps"],
        "appeal_template_ref": resolution["appeal_template_ref"],
    }


def assess_rev_cycle_priority(
    category: str,
    amount: float,
    days_aged: int,
    timely_filing_deadline: int,
) -> dict:
    """Assess revenue cycle case priority based on dollar amount, aging, and category.

    Args:
        category: Case category (e.g., "denial_appeal", "ar_followup")
        amount: Dollar amount of claim/balance
        days_aged: Days since claim was filed or denial received
        timely_filing_deadline: Payer timely filing limit in days

    Returns:
        priority (CRITICAL/HIGH/MEDIUM/LOW), urgency, justification
    """
    reasons = []

    # Amount-based priority floor
    if amount >= _RC_PRIORITY_AMOUNTS["CRITICAL"]:
        amount_priority = "CRITICAL"
        reasons.append(f"High-dollar claim ${amount:,.0f}")
    elif amount >= _RC_PRIORITY_AMOUNTS["HIGH"]:
        amount_priority = "HIGH"
        reasons.append(f"Significant claim ${amount:,.0f}")
    elif amount >= _RC_PRIORITY_AMOUNTS["MEDIUM"]:
        amount_priority = "MEDIUM"
        reasons.append(f"Moderate claim ${amount:,.0f}")
    else:
        amount_priority = "LOW"

    # Category-based priority floor
    if category in _RC_HIGH_PRIORITY_CATEGORIES:
        category_priority = "HIGH"
        reasons.append(f"{category.replace('_', ' ').title()} requires prompt action")
    else:
        category_priority = "LOW"

    # Aging urgency
    if timely_filing_deadline > 0 and days_aged > 0:
        pct_used = days_aged / timely_filing_deadline
        if pct_used >= 1.0:
            reasons.append("Timely filing deadline exceeded")
            aging_priority = "CRITICAL"
        elif pct_used >= 0.80:
            remaining = timely_filing_deadline - days_aged
            reasons.append(f"Only {remaining} days left in filing window")
            aging_priority = "HIGH"
        elif days_aged > 90:
            reasons.append(f"Aged {days_aged} days")
            aging_priority = "MEDIUM"
        else:
            aging_priority = "LOW"
    else:
        aging_priority = "LOW"

    # Take highest priority across all dimensions
    priority_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    final = max([amount_priority, category_priority, aging_priority], key=lambda p: priority_rank[p])

    # Urgency label
    urgency_map = {"CRITICAL": "immediate", "HIGH": "high", "MEDIUM": "standard", "LOW": "routine"}

    return {
        "priority": final,
        "urgency": urgency_map[final],
        "justification": " | ".join(reasons) if reasons else "Standard rev cycle case",
    }
