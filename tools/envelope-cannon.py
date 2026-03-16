#!/usr/bin/env python3
"""
Envelope Cannon — Trellis Load Generator
Fires real NVD CVEs, synthetic IT tickets, and HR cases at a Trellis instance.

Usage:
    python tools/envelope-cannon.py --source nvd --count 50 --target http://localhost:8100
    python tools/envelope-cannon.py --source it --count 20
    python tools/envelope-cannon.py --source hr --count 10
    python tools/envelope-cannon.py --source mixed --count 100 --rate 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ── NVD API ─────────────────────────────────────────────────────────────────

NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_PAGE_SIZE = 50
NVD_RATE_LIMIT = 5          # requests per window
NVD_RATE_WINDOW = 30.0      # seconds
NVD_MAX_RETRIES = 3
NVD_RETRY_BACKOFF = 6.0     # seconds between retries


async def fetch_nvd_page(client: httpx.AsyncClient, start_index: int) -> list[dict]:
    """Fetch one page of CVEs from NVD. Returns list of parsed CVE dicts."""
    params = {
        "resultsPerPage": NVD_PAGE_SIZE,
        "startIndex": start_index,
    }
    for attempt in range(NVD_MAX_RETRIES):
        try:
            resp = await client.get(NVD_BASE, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return [_parse_nvd_cve(item) for item in data.get("vulnerabilities", [])]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                wait = NVD_RETRY_BACKOFF * (attempt + 1)
                print(f"  [NVD] Rate limited, waiting {wait:.0f}s before retry {attempt+1}/{NVD_MAX_RETRIES}...",
                      file=sys.stderr)
                await asyncio.sleep(wait)
            else:
                print(f"  [NVD] HTTP error {e.response.status_code}: {e}", file=sys.stderr)
                if attempt < NVD_MAX_RETRIES - 1:
                    await asyncio.sleep(NVD_RETRY_BACKOFF)
                else:
                    raise
        except (httpx.RequestError, json.JSONDecodeError) as e:
            print(f"  [NVD] Request error (attempt {attempt+1}): {e}", file=sys.stderr)
            if attempt < NVD_MAX_RETRIES - 1:
                await asyncio.sleep(NVD_RETRY_BACKOFF)
            else:
                raise
    return []


def _parse_nvd_cve(item: dict) -> dict:
    """Extract structured fields from a raw NVD vulnerability entry."""
    cve = item.get("cve", {})
    cve_id = cve.get("id", "CVE-UNKNOWN")

    # Description — prefer English
    descriptions = cve.get("descriptions", [])
    description = next(
        (d["value"] for d in descriptions if d.get("lang") == "en"),
        descriptions[0]["value"] if descriptions else "No description available.",
    )

    # CVSS — try v3.1, then v3.0, then v2.0
    metrics = cve.get("metrics", {})
    cvss_score = None
    severity = "UNKNOWN"

    for version_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        metric_list = metrics.get(version_key, [])
        if metric_list:
            m = metric_list[0].get("cvssData", {})
            cvss_score = m.get("baseScore")
            severity = (
                metric_list[0].get("baseSeverity")
                or m.get("baseSeverity")
                or _cvss_to_severity(cvss_score)
            )
            break

    # Vendor / product from CPE configurations
    vendor, product = _extract_vendor_product(cve)

    # References
    references = [r.get("url", "") for r in cve.get("references", [])][:5]

    published = cve.get("published", "")
    modified = cve.get("lastModified", "")

    return {
        "cve_id": cve_id,
        "title": f"{cve_id} — {severity} Vulnerability",
        "description": description[:2000],
        "vendor": vendor,
        "product": product,
        "severity": severity.upper() if severity else "UNKNOWN",
        "cvss_score": cvss_score,
        "references": references,
        "published": published,
        "modified": modified,
        "exploited_in_wild": False,
    }


def _extract_vendor_product(cve: dict) -> tuple[str, str]:
    """Pull vendor and product from CPE data."""
    configs = cve.get("configurations", [])
    for config in configs:
        for node in config.get("nodes", []):
            for cpe_match in node.get("cpeMatch", []):
                cpe = cpe_match.get("criteria", "")
                parts = cpe.split(":")
                if len(parts) >= 5:
                    return parts[3], parts[4]
    # Fall back to affected packages
    cve.get("weaknesses", [])
    return "", ""


def _cvss_to_severity(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


async def generate_nvd_envelopes(count: int, verbose: bool = False) -> list[dict]:
    """Fetch enough CVEs from NVD to satisfy count. Respects rate limits."""
    envelopes = []
    start_index = 0
    pages_fetched = 0
    window_start = time.monotonic()

    async with httpx.AsyncClient(
        headers={"User-Agent": "trellis-envelope-cannon/1.0"},
        follow_redirects=True,
    ) as client:
        while len(envelopes) < count:
            # NVD rate limit: 5 requests per 30 seconds
            if pages_fetched > 0 and pages_fetched % NVD_RATE_LIMIT == 0:
                elapsed = time.monotonic() - window_start
                if elapsed < NVD_RATE_WINDOW:
                    wait = NVD_RATE_WINDOW - elapsed + 0.5
                    print(f"  [NVD] Rate limit pause: {wait:.1f}s ({pages_fetched} pages fetched so far)...",
                          file=sys.stderr)
                    await asyncio.sleep(wait)
                window_start = time.monotonic()

            if verbose:
                print(f"  [NVD] Fetching page starting at index {start_index}...", file=sys.stderr)

            cves = await fetch_nvd_page(client, start_index)
            if not cves:
                print("  [NVD] No more results from NVD API.", file=sys.stderr)
                break

            for cve in cves:
                if len(envelopes) >= count:
                    break
                envelopes.append(_cve_to_envelope(cve))

            pages_fetched += 1
            start_index += NVD_PAGE_SIZE

    return envelopes[:count]


def _cve_to_envelope(cve: dict) -> dict:
    """Convert a parsed CVE dict into a Trellis envelope."""
    severity = cve["severity"].upper()
    priority = {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "normal",
        "LOW": "low",
    }.get(severity, "normal")

    return {
        "envelope_id": str(uuid4()),
        "source_type": "cisa_kev",
        "source_id": cve["cve_id"],
        "payload": {
            "text": f"{cve['cve_id']}: {cve['description'][:500]}",
            "data": {
                "cve_id": cve["cve_id"],
                "title": cve["title"],
                "description": cve["description"],
                "vendor": cve["vendor"],
                "product": cve["product"],
                "severity": severity,
                "cvss_score": cve["cvss_score"],
                "references": cve["references"],
                "published": cve["published"],
                "exploited_in_wild": cve["exploited_in_wild"],
            },
        },
        "metadata": {
            "trace_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "priority": priority,
            "sender": {
                "id": "nvd-feed",
                "name": "NVD CVE Feed",
                "department": "Information Security",
                "roles": ["vulnerability-feed"],
            },
        },
        "routing_hints": {
            "category": "security",
            "tags": ["cve", "vulnerability", severity.lower()],
        },
        "_label": f"{cve['cve_id']}",
        "_target_hint": "security-triage",
        "_priority": priority.upper(),
    }


# ── Synthetic IT Tickets ──────────────────────────────────────────────────

IT_TEMPLATES = [
    {
        "category": "password-reset",
        "texts": [
            "I'm locked out of my {app} account and need a password reset ASAP. Patient care is being affected.",
            "My {app} password expired and I can't log in. Please reset it.",
            "Can't access {app} — getting 'account locked' error after too many login attempts.",
            "Password reset needed for {app}. I've been locked out since this morning.",
        ],
        "apps": ["Epic Hyperspace", "Epic MyChart", "PeopleSoft", "Azure AD", "VPN", "8x8 softphone", "CrowdStrike console"],
    },
    {
        "category": "vpn",
        "texts": [
            "VPN is not connecting from home. Getting error: {error}.",
            "Remote access stopped working this morning. VPN client shows '{error}'.",
            "Can't connect to VPN — it was working yesterday. Error: {error}.",
            "Cisco AnyConnect giving '{error}' error, can't get into the network remotely.",
        ],
        "errors": [
            "Connection attempt has timed out",
            "AnyConnect cannot confirm it is connected to your secure gateway",
            "Authentication failed",
            "Unable to contact the VPN server",
            "The VPN client agent has encountered an error",
        ],
    },
    {
        "category": "printer",
        "texts": [
            "Printer on {floor} is not printing. Jobs are queued but nothing comes out.",
            "The {printer_type} printer near {floor} is offline. Staff can't print patient labels.",
            "Print jobs stuck in queue on {floor}. Printer shows 'Ready' but nothing prints.",
            "Zebra label printer at {location} not responding. Patient wristbands backed up.",
        ],
        "floors": ["2nd floor nursing station", "3rd floor radiology", "ED triage", "ICU", "OR prep area", "pharmacy"],
        "printer_types": ["HP LaserJet", "Zebra label", "Lexmark", "Canon"],
        "locations": ["nursing station 3B", "ED charge desk", "pharmacy window", "radiology waiting"],
    },
    {
        "category": "application-error",
        "texts": [
            "{app} is throwing an error: {error}. Multiple users affected on {unit}.",
            "Getting '{error}' in {app}. Can't complete {workflow}.",
            "{app} crashed and won't reopen. Error: {error}. Affects {count} users on {unit}.",
            "Critical: {app} unresponsive — {error}. {count} clinicians can't access records.",
        ],
        "apps": ["Epic Hyperspace", "Epic Willow", "PeopleSoft HCM", "UKG Workforce", "LogicMonitor", "8x8"],
        "errors": [
            "EpicCare disconnected from server",
            "Error code: CON-2847",
            "Database connection timeout",
            "Application not responding",
            "SSL handshake failed",
            "License server unreachable",
        ],
        "workflows": ["medication reconciliation", "patient discharge", "order entry", "scheduling", "time entry"],
        "units": ["Holmes Regional", "Cape Canaveral Hospital", "Palm Bay Hospital", "Viera Hospital", "all facilities"],
        "counts": ["3", "7", "12", "47", "20+"],
    },
    {
        "category": "network",
        "texts": [
            "Network extremely slow on {floor}. Can't access any systems.",
            "Wi-Fi keeps dropping in {location}. Clinical staff having connectivity issues.",
            "No internet access in {location}. All workstations affected.",
            "Intermittent network outages in {floor} disrupting clinical workflows.",
        ],
        "floors": ["ICU ward", "3rd floor east wing", "radiology suite", "ED", "OR"],
        "locations": ["Building C", "the new Cape Canaveral Hospital annex", "Viera MOB", "Palm Bay ED"],
    },
    {
        "category": "account-lockout",
        "texts": [
            "My Active Directory account is locked. Need it unlocked to access patient systems.",
            "AD account locked after failed logins — not me, possibly suspicious activity.",
            "Service account {svc_account} locked, causing {app} integration to fail.",
            "Multiple user accounts locked in {department}. Possible brute force attempt.",
        ],
        "svc_accounts": ["svc-epic-int", "svc-lab-hl7", "svc-pharmacy-link", "svc-monitoring"],
        "apps": ["Epic", "PeopleSoft", "UKG", "lab systems"],
        "departments": ["radiology", "pharmacy", "nursing", "billing"],
    },
]

SEVERITIES = ["low", "low", "normal", "normal", "high", "critical"]

USERS = [
    ("dr.patel@healthfirst.org", "Dr. Patel", "Cardiology"),
    ("nurse.thompson@healthfirst.org", "R. Thompson RN", "ICU"),
    ("j.rodriguez@healthfirst.org", "J. Rodriguez", "ED"),
    ("admin.chen@healthfirst.org", "A. Chen", "Administration"),
    ("billing.ops@healthfirst.org", "Billing Ops", "Revenue Cycle"),
    ("pharmacy.tech@healthfirst.org", "Pharmacy Tech", "Pharmacy"),
    ("rad.tech01@healthfirst.org", "Rad Tech 01", "Radiology"),
    ("lab.director@healthfirst.org", "Lab Director", "Laboratory"),
]


def _pick(lst: list) -> str:
    return random.choice(lst)


def generate_it_ticket() -> dict:
    template = _pick(IT_TEMPLATES)
    text_template = _pick(template["texts"])

    # Fill in template vars
    fills: dict[str, str] = {}
    for key in ["apps", "errors", "floors", "printer_types", "locations", "workflows",
                "units", "counts", "svc_accounts", "departments"]:
        if key in template:
            fills[key[:-1]] = _pick(template[key])  # strip trailing 's'

    try:
        text = text_template.format(**fills)
    except KeyError:
        text = text_template  # some templates may not match all vars

    severity = _pick(SEVERITIES)
    user_email, user_name, department = _pick(USERS)
    ticket_id = f"INC-{random.randint(100000, 999999)}"

    return {
        "envelope_id": str(uuid4()),
        "source_type": "teams",
        "source_id": ticket_id,
        "payload": {
            "text": text,
            "data": {
                "ticket_id": ticket_id,
                "category": template["category"],
                "reported_by": user_name,
            },
        },
        "metadata": {
            "trace_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "priority": severity,
            "sender": {
                "id": user_email,
                "name": user_name,
                "department": department,
                "roles": ["staff"],
            },
        },
        "routing_hints": {
            "department": "IT",
            "category": "incident",
            "tags": [template["category"], severity],
        },
        "_label": ticket_id,
        "_target_hint": "it-help",
        "_priority": severity.upper(),
    }


# ── Synthetic HR Cases ────────────────────────────────────────────────────

HR_TEMPLATES = [
    {
        "category": "pto",
        "texts": [
            "I'd like to request PTO from {start_date} through {end_date}. Is my balance sufficient?",
            "Requesting vacation leave: {start_date} to {end_date}. Please confirm approval process.",
            "How many PTO hours do I have available? Planning time off in {month}.",
            "PTO request for {start_date}–{end_date}. I have {hours} hours accrued — should be enough.",
        ],
        "months": ["April", "May", "June", "July", "August", "September", "October"],
        "hours": ["40", "56", "80", "120"],
    },
    {
        "category": "benefits",
        "texts": [
            "Open enrollment question: Can I add my {dependent} to the {plan} plan mid-year due to qualifying life event?",
            "What's the difference between the BCBS Select and BCBS Premier plans? Trying to decide before enrollment closes.",
            "I missed open enrollment — is there a special enrollment period available?",
            "How do I enroll in the HSA? I selected the high-deductible plan but haven't set up contributions.",
            "Benefits question: does our dental plan cover orthodontics for {dependent}?",
        ],
        "dependents": ["spouse", "newborn", "child", "domestic partner"],
        "plans": ["BCBS Select", "BCBS Premier", "UHC Choice", "Kaiser HMO"],
    },
    {
        "category": "payroll",
        "texts": [
            "My paycheck for {pay_period} looks wrong — missing {hours} hours of overtime.",
            "I believe I was underpaid for the pay period ending {pay_period}. Shift differential not included.",
            "My direct deposit didn't arrive on payday. Account details are correct — please investigate.",
            "Holiday pay not reflected in my {pay_period} paycheck. I worked {holiday}.",
            "Payroll discrepancy: my W-2 shows a different amount than my pay stubs. Need correction before taxes.",
        ],
        "pay_periods": ["Feb 28", "Mar 15", "Mar 1", "Feb 15"],
        "hours": ["8", "12", "16", "24"],
        "holidays": ["Christmas Day", "New Year's Day", "Thanksgiving", "July 4th"],
    },
    {
        "category": "policy",
        "texts": [
            "What is the policy for working remotely more than 2 days per week?",
            "Can you clarify the attendance policy — specifically call-out procedures for scheduled shifts?",
            "What is the bereavement leave policy for extended family?",
            "Is there a policy on cell phone use during patient care shifts?",
            "Tuition reimbursement policy — what's the annual maximum and approval process?",
            "What does the progressive discipline policy say about tardiness thresholds?",
        ],
    },
    {
        "category": "onboarding",
        "texts": [
            "New hire starting {start_date}: {name}, {role} in {department}. Needs benefits enrollment, ID badge, parking pass.",
            "Onboarding checklist for {name} — {role}, {department}. Start date: {start_date}. Please initiate HR orientation.",
            "I'm a new employee starting {start_date} and haven't received my onboarding packet or system access yet.",
            "New hire paperwork for {name} ({role}): I9 verification, direct deposit, benefits selection needed by {start_date}.",
        ],
        "names": ["Dr. Maria Santos", "James Whitfield RN", "Priya Nair", "Carlos Mendez", "Ava Kim RN"],
        "roles": ["Staff Nurse", "Hospitalist", "Medical Assistant", "Clinical Pharmacist", "Radiology Tech"],
        "departments": ["ICU", "Cardiology", "ED", "Pharmacy", "Radiology"],
    },
]

HR_USERS = [
    ("m.johnson@healthfirst.org", "M. Johnson", "Nursing"),
    ("t.williams@healthfirst.org", "T. Williams", "HR"),
    ("s.davis@healthfirst.org", "S. Davis", "Finance"),
    ("k.brown@healthfirst.org", "K. Brown", "Radiology"),
    ("l.jones@healthfirst.org", "L. Jones", "Laboratory"),
    ("p.garcia@healthfirst.org", "P. Garcia", "Administration"),
]


def generate_hr_case() -> dict:
    template = _pick(HR_TEMPLATES)
    text_template = _pick(template["texts"])

    # Build fill dict from available template vars
    fills: dict[str, str] = {}
    optional_keys = {
        "months": "month",
        "hours": "hours",
        "dependents": "dependent",
        "plans": "plan",
        "pay_periods": "pay_period",
        "holidays": "holiday",
        "names": "name",
        "roles": "role",
        "departments": "department",
    }
    for list_key, fill_key in optional_keys.items():
        if list_key in template:
            fills[fill_key] = _pick(template[list_key])

    # Static date fills
    fills["start_date"] = f"March {random.randint(15, 28)}, 2026"
    fills["end_date"] = f"April {random.randint(1, 15)}, 2026"

    try:
        text = text_template.format(**fills)
    except KeyError:
        text = text_template

    user_email, user_name, department = _pick(HR_USERS)
    case_id = f"HR-{random.randint(10000, 99999)}"

    return {
        "envelope_id": str(uuid4()),
        "source_type": "teams",
        "source_id": case_id,
        "payload": {
            "text": text,
            "data": {
                "case_id": case_id,
                "category": template["category"],
                "submitted_by": user_name,
            },
        },
        "metadata": {
            "trace_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "priority": "normal",
            "sender": {
                "id": user_email,
                "name": user_name,
                "department": department,
                "roles": ["staff"],
            },
        },
        "routing_hints": {
            "department": "HR",
            "category": template["category"],
            "tags": ["hr-case", template["category"]],
        },
        "_label": case_id,
        "_target_hint": "sam-hr",
        "_priority": "NORMAL",
    }


# ── Envelope Firing ──────────────────────────────────────────────────────

async def fire_envelope(
    client: httpx.AsyncClient,
    target: str,
    envelope: dict,
    index: int,
    total: int,
    dry_run: bool = False,
) -> dict:
    """POST a single envelope to Trellis. Returns result dict."""
    label = envelope.pop("_label", envelope["envelope_id"][:8])
    target_hint = envelope.pop("_target_hint", "?")
    priority = envelope.pop("_priority", "NORMAL")

    if dry_run:
        print(f"  [DRY RUN] [{index}/{total}] {label} → {target_hint} ({priority})")
        return {"success": True, "label": label, "priority": priority, "latency_ms": 0}

    url = f"{target.rstrip('/')}/api/envelopes"
    t0 = time.monotonic()
    try:
        resp = await client.post(url, json=envelope, timeout=60.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        resp.raise_for_status()
        print(f"  [{index}/{total}] {label} → {target_hint} ({priority}, {latency_ms}ms)")
        return {"success": True, "label": label, "priority": priority, "latency_ms": latency_ms}
    except httpx.HTTPStatusError as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        print(f"  [{index}/{total}] {label} → FAILED (HTTP {e.response.status_code}, {latency_ms}ms)",
              file=sys.stderr)
        return {"success": False, "label": label, "priority": priority, "latency_ms": latency_ms,
                "error": str(e.response.status_code)}
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        print(f"  [{index}/{total}] {label} → FAILED ({e}, {latency_ms}ms)", file=sys.stderr)
        return {"success": False, "label": label, "priority": priority, "latency_ms": latency_ms,
                "error": str(e)}


async def fire_batch(
    envelopes: list[dict],
    target: str,
    rate: float,
    dry_run: bool,
) -> list[dict]:
    """Fire all envelopes, respecting rate limit (envelopes/sec)."""
    results = []
    total = len(envelopes)
    interval = 1.0 / rate if rate > 0 else 0.0
    semaphore = asyncio.Semaphore(min(10, max(1, int(rate) or 1)))

    async with httpx.AsyncClient(
        headers={"User-Agent": "trellis-envelope-cannon/1.0"},
        follow_redirects=True,
    ) as client:
        tasks = []

        async def _fire_one(i: int, env: dict) -> dict:
            async with semaphore:
                return await fire_envelope(client, target, env, i + 1, total, dry_run)

        # Stagger fires to respect rate limit
        for i, env in enumerate(envelopes):
            task = asyncio.create_task(_fire_one(i, env))
            tasks.append(task)
            if interval > 0 and i < total - 1:
                await asyncio.sleep(interval)

        results = await asyncio.gather(*tasks)

    return list(results)


# ── Summary ───────────────────────────────────────────────────────────────

def print_summary(results: list[dict], source: str, elapsed: float) -> None:
    total = len(results)
    successes = sum(1 for r in results if r["success"])
    failures = total - successes
    latencies = [r["latency_ms"] for r in results if r["success"] and r["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    by_priority: dict[str, int] = defaultdict(int)
    for r in results:
        by_priority[r.get("priority", "UNKNOWN")] += 1

    print()
    print("=" * 55)
    print(f"  Envelope Cannon — Summary ({source.upper()})")
    print("=" * 55)
    print(f"  Total sent   : {total}")
    print(f"  Success      : {successes}")
    print(f"  Failed       : {failures}")
    print(f"  Avg latency  : {avg_latency:.0f}ms")
    print(f"  Total time   : {elapsed:.1f}s")
    print(f"  Throughput   : {total/elapsed:.1f} envelopes/sec" if elapsed > 0 else "")
    if by_priority:
        print()
        print("  By Priority:")
        for pri in ["CRITICAL", "HIGH", "NORMAL", "LOW", "UNKNOWN"]:
            count = by_priority.get(pri, 0)
            if count:
                bar = "█" * min(count, 30)
                print(f"    {pri:<10} {count:>4}  {bar}")
    print("=" * 55)


# ── CLI ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Envelope Cannon — Trellis load generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--source",
        choices=["nvd", "it", "hr", "mixed"],
        default="mixed",
        help="Envelope source (default: mixed)",
    )
    p.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of envelopes to fire (default: 10)",
    )
    p.add_argument(
        "--target",
        default="http://localhost:8100",
        help="Trellis base URL (default: http://localhost:8100)",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Max envelopes per second (default: 5.0)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print envelopes without sending",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose NVD fetch progress",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="Strip routing_hints before sending — tests that the Classification Engine infers routing correctly",
    )
    return p


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print(f"🔫 Envelope Cannon firing at {args.target}")
    print(f"   Source: {args.source} | Count: {args.count} | Rate: {args.rate}/s")
    if args.dry_run:
        print("   [DRY RUN — not actually sending]")
    print()

    # Generate envelopes
    envelopes: list[dict] = []

    if args.source == "nvd":
        print(f"Fetching {args.count} CVEs from NVD API...")
        envelopes = await generate_nvd_envelopes(args.count, args.verbose)
        print(f"  Got {len(envelopes)} CVEs.\n")

    elif args.source == "it":
        print(f"Generating {args.count} synthetic IT tickets...")
        envelopes = [generate_it_ticket() for _ in range(args.count)]
        print(f"  Generated {len(envelopes)} tickets.\n")

    elif args.source == "hr":
        print(f"Generating {args.count} synthetic HR cases...")
        envelopes = [generate_hr_case() for _ in range(args.count)]
        print(f"  Generated {len(envelopes)} cases.\n")

    elif args.source == "mixed":
        # Split roughly: 40% NVD, 35% IT, 25% HR
        nvd_count = max(1, int(args.count * 0.40))
        it_count = max(1, int(args.count * 0.35))
        hr_count = args.count - nvd_count - it_count

        print(f"Mixed load: {nvd_count} CVEs, {it_count} IT tickets, {hr_count} HR cases")
        print("Fetching CVEs from NVD API...")
        nvd_envelopes = await generate_nvd_envelopes(nvd_count, args.verbose)
        print(f"  Got {len(nvd_envelopes)} CVEs.")

        it_envelopes = [generate_it_ticket() for _ in range(it_count)]
        hr_envelopes = [generate_hr_case() for _ in range(hr_count)]

        envelopes = nvd_envelopes + it_envelopes + hr_envelopes
        random.shuffle(envelopes)
        print(f"  Total: {len(envelopes)} envelopes ready.\n")

    if not envelopes:
        print("ERROR: No envelopes generated. Check NVD connectivity or reduce --count.", file=sys.stderr)
        sys.exit(1)

    # Fire!
    print(f"Firing {len(envelopes)} envelopes...")
    t0 = time.monotonic()
    if args.raw:
        print("   [RAW MODE — stripping routing_hints to test Classification Engine]")
        for env in envelopes:
            env.pop("routing_hints", None)

    results = await fire_batch(envelopes, args.target, args.rate, args.dry_run)
    elapsed = time.monotonic() - t0

    print_summary(results, args.source, elapsed)


if __name__ == "__main__":
    asyncio.run(main())
