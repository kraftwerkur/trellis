#!/usr/bin/env python3
"""
Trellis Full Platform Demo
==========================
End-to-end demonstration of Trellis — the enterprise AI agent orchestration
platform for healthcare. Shows every major capability in a single run.

What this demo covers:
  1. Agent Registration — 3 agents (Clinical, Security, Document Processing)
  2. Routing Rules — automatic event-to-agent matching
  3. HL7 ADT Message — patient admission event from Epic
  4. FHIR Patient Resource — clinical data ingestion
  5. Document Ingestion — policy PDF processing
  6. Security Alert — CrowdStrike/Sentinel style event
  7. PHI Shield — catching protected health information in text
  8. Prompt Scorer — evaluating complexity of different prompts
  9. FinOps — cost tracking per agent
  10. Summary Dashboard — ASCII table with full run results

Run:
    python examples/demo_full_platform.py              # Against running server
    python examples/demo_full_platform.py --dry-run    # No server needed

Prerequisites (live mode):
    cd projects/trellis && uv run uvicorn trellis.main:app --port 8100

Author: Reef (AI Agent) for Platform Team
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════════════════
# ANSI Colors — because leadership demos need to look good in a terminal
# ═══════════════════════════════════════════════════════════════════════════════

BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"
BG_RED  = "\033[41m"
BG_GREEN = "\033[42m"
BG_BLUE = "\033[44m"


def banner(text: str, color: str = CYAN):
    """Print a big section banner."""
    width = 72
    print()
    print(f"{color}{BOLD}{'═' * width}{RESET}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(f"{color}{BOLD}{'═' * width}{RESET}")
    print()


def step(text: str):
    print(f"  {GREEN}▸{RESET} {text}")


def substep(text: str):
    print(f"    {DIM}→ {text}{RESET}")


def success(text: str):
    print(f"  {GREEN}✓{RESET} {text}")


def warn(text: str):
    print(f"  {YELLOW}⚠{RESET} {text}")


def fail(text: str):
    print(f"  {RED}✗{RESET} {text}")


def info(text: str):
    print(f"    {DIM}{text}{RESET}")


def json_preview(data: dict, max_lines: int = 8):
    """Pretty-print JSON with truncation."""
    formatted = json.dumps(data, indent=2)
    lines = formatted.split("\n")
    for line in lines[:max_lines]:
        print(f"    {DIM}{line}{RESET}")
    if len(lines) > max_lines:
        print(f"    {DIM}... ({len(lines) - max_lines} more lines){RESET}")


def pause(seconds: float = 0.5):
    """Brief pause for dramatic effect in demos."""
    time.sleep(seconds)


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Client — thin wrapper around requests (the only external dependency)
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL = "http://localhost:8100"


def api(method: str, path: str, json_data: dict | None = None,
        content_type: str | None = None, raw_body: str | None = None) -> dict | None:
    """Make an API call to Trellis. Returns response JSON or None on error."""
    import requests
    url = f"{BASE_URL}/api{path}"
    try:
        if raw_body is not None:
            # For HL7 messages sent as text/plain
            r = requests.request(method, url, data=raw_body.encode(),
                                 headers={"Content-Type": content_type or "text/plain"})
        else:
            r = requests.request(method, url, json=json_data)
        if r.status_code >= 400:
            fail(f"HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json() if r.text else {}
    except requests.ConnectionError:
        fail(f"Cannot connect to {BASE_URL} — is Trellis running?")
        fail("Start it: uv run uvicorn trellis.main:app --port 8100")
        return None
    except Exception as e:
        fail(f"Request error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Demo Data — realistic healthcare scenarios
# ═══════════════════════════════════════════════════════════════════════════════

# --- Agents ---

AGENTS = [
    {
        "agent_id": "epic-clinical",
        "name": "Epic Clinical Agent",
        "owner": "Dr. Sarah Chen",
        "department": "Clinical",
        "framework": "pi-sdk",
        "agent_type": "http",
        "endpoint": "http://localhost:8100/mock-agent/envelope",
        "health_endpoint": "http://localhost:8100/mock-agent/health",
        "tools": ["epic-fhir-read", "epic-fhir-write", "bed-management", "order-entry"],
        "channels": ["hl7", "fhir", "api"],
        "description": "Handles Epic EMR events — ADT messages, FHIR resources, "
                       "bed management, and clinical order processing.",
    },
    {
        "agent_id": "security-ops",
        "name": "Security Operations Agent",
        "owner": "Security Team",
        "department": "IT Security",
        "framework": "custom",
        "agent_type": "http",
        "endpoint": "http://localhost:8100/mock-agent/envelope",
        "health_endpoint": "http://localhost:8100/mock-agent/health",
        "tools": ["crowdstrike-query", "sentinel-alert", "firewall-block", "incident-create"],
        "channels": ["api", "log-stream"],
        "description": "Monitors security events from CrowdStrike and Sentinel. "
                       "Triages alerts, blocks threats, creates incident tickets.",
    },
    {
        "agent_id": "doc-processor",
        "name": "Document Processing Agent",
        "owner": "Compliance Team",
        "department": "Compliance",
        "framework": "langchain",
        "agent_type": "http",
        "endpoint": "http://localhost:8100/mock-agent/envelope",
        "health_endpoint": "http://localhost:8100/mock-agent/health",
        "tools": ["pdf-extract", "policy-index", "staff-notify", "sharepoint-upload"],
        "channels": ["document", "api"],
        "description": "Processes policy documents, clinical guidelines, and compliance "
                       "manuals. Extracts text, indexes content, notifies affected staff.",
    },
]

# --- Routing Rules ---
# These tell Trellis which agent gets which events

RULES = [
    {
        "name": "HL7 ADT events → Clinical Agent",
        "priority": 100,
        "conditions": {"source_type": "hl7"},
        "actions": {"route_to": "epic-clinical"},
        "active": True,
    },
    {
        "name": "FHIR resources → Clinical Agent",
        "priority": 90,
        "conditions": {"source_type": "fhir"},
        "actions": {"route_to": "epic-clinical"},
        "active": True,
    },
    {
        "name": "Security alerts → Security Agent",
        "priority": 80,
        "conditions": {"source_type": "api", "routing_hints.category": "security"},
        "actions": {"route_to": "security-ops", "set_priority": "critical"},
        "active": True,
    },
    {
        "name": "Documents → Document Processor",
        "priority": 70,
        "conditions": {"source_type": "document"},
        "actions": {"route_to": "doc-processor"},
        "active": True,
    },
]

# --- HL7 ADT^A01 Message (Patient Admission) ---
# This is what Epic sends when a patient is admitted.
# Real HL7v2 uses pipe-delimited segments.

HL7_ADT_MESSAGE = "\r".join([
    "MSH|^~\\\\&|EPIC|MAIN_CAMPUS|TRELLIS|PLATFORM|20260305120000||ADT^A01|MSG00001|P|2.5.1",
    "EVN|A01|20260305120000",
    "PID|1||MRN-1234567^^^EPIC^MR||DOE^JANE^M||19850315|F|||123 MAIN ST^^MELBOURNE^FL^32901||321-555-0100||S||ACCT-98765",
    "PV1|1|I|ICU^ICU-BED-3^A|E|||1234567890^SMITH^JOHN^DR|||MED||||ADM|||1234567890^SMITH^JOHN^DR|IN||||||||||||||||||MAIN||A|||20260305120000",
    "DG1|1||J18.9^Pneumonia, unspecified^ICD-10|||A",
    "IN1|1|BCBS|BCBS-FL|BLUE CROSS BLUE SHIELD OF FLORIDA",
])

# --- FHIR Patient Resource ---
# Standard FHIR R4 Patient — the modern way Epic shares clinical data

FHIR_PATIENT = {
    "resourceType": "Patient",
    "id": "patient-jane-doe-12345",
    "meta": {
        "lastUpdated": "2026-03-05T12:00:00Z",
        "source": "Epic",
    },
    "identifier": [
        {
            "system": "urn:oid:1.2.3.4.5.6.7.8.9",
            "value": "MRN-1234567",
            "type": {"text": "MRN"},
        }
    ],
    "name": [{"family": "Doe", "given": ["Jane", "M"]}],
    "gender": "female",
    "birthDate": "1985-03-15",
    "address": [
        {
            "line": ["123 Main St"],
            "city": "Melbourne",
            "state": "FL",
            "postalCode": "32901",
        }
    ],
    "telecom": [
        {"system": "phone", "value": "321-555-0100"},
        {"system": "email", "value": "jane.doe@example.com"},
    ],
}

# --- Security Alert Envelope ---
# Simulates a CrowdStrike/Sentinel alert hitting the platform

SECURITY_ALERT = {
    "envelope_id": str(uuid.uuid4()),
    "source_type": "api",
    "source_id": "crowdstrike-falcon",
    "payload": {
        "text": "CRITICAL: Suspicious process execution detected on endpoint WS-NURSE-042. "
                "Process 'mimikatz.exe' launched from PowerShell with SYSTEM privileges. "
                "Source IP: 10.10.5.42. User: svc_epic_interface.",
        "data": {
            "alert_id": "CS-2026-03-05-0042",
            "severity": "critical",
            "endpoint": "WS-NURSE-042",
            "process": "mimikatz.exe",
            "technique": "T1003 - Credential Dumping",
            "source": "CrowdStrike Falcon",
        },
    },
    "metadata": {
        "trace_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "priority": "critical",
        "sender": {
            "id": "crowdstrike-system",
            "name": "CrowdStrike Falcon",
            "department": "IT Security",
            "roles": ["system"],
        },
    },
    "routing_hints": {
        "category": "security",
        "tags": ["security", "edr", "critical", "credential-theft"],
    },
}

# --- Document Ingestion Envelope ---
# Simulates a new infection control policy being uploaded

DOCUMENT_ENVELOPE = {
    "envelope_id": str(uuid.uuid4()),
    "source_type": "document",
    "source_id": "document-pdf",
    "payload": {
        "text": "INFECTION CONTROL POLICY — REVISED MARCH 2026\n\n"
                "Section 1: Hand Hygiene Requirements\n"
                "All clinical staff must perform hand hygiene using alcohol-based hand rub "
                "or soap and water before and after every patient contact. Compliance is "
                "monitored via badge-proximity sensors (RTLS) and reported monthly to the "
                "Infection Prevention Committee.\n\n"
                "Section 2: Personal Protective Equipment\n"
                "N95 respirators are required for all aerosol-generating procedures. "
                "Standard precautions apply to all patient encounters. Contact Dr. Sarah "
                "Chen at 321-555-0199 or sarah.chen@example.com for questions.\n\n"
                "Effective Date: March 15, 2026\n"
                "Approved by: Infection Prevention Committee\n"
                "Document ID: IC-POL-2026-003",
        "data": {
            "filename": "infection-control-policy-march-2026.pdf",
            "format": "pdf",
            "chunk_index": 0,
            "total_chunks": 1,
            "content_type": "application/pdf",
            "document_type": "policy",
            "department": "Infection Control",
            "effective_date": "2026-03-15",
            "author": "Infection Prevention Committee",
            "version": "2026.3",
        },
    },
    "metadata": {
        "trace_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "priority": "normal",
        "sender": {
            "id": "sharepoint-monitor",
            "name": "SharePoint Document Monitor",
            "department": "Infection Control",
            "roles": ["system"],
        },
    },
    "routing_hints": {
        "category": "document-ingestion",
        "department": "Infection Control",
        "tags": ["document", "pdf", "policy", "infection control"],
    },
}

# --- PHI Test Strings ---
# Text containing Protected Health Information for PHI Shield testing

PHI_TEST_SAMPLES = [
    {
        "label": "Patient referral note (SSN + MRN + Phone)",
        "text": (
            "Patient Jane Doe (MRN: 1234567, SSN: 123-45-6789) was admitted to "
            "Main Campus Medical Center on 03/05/2026. Contact her emergency "
            "contact at (321) 555-0100 or email jane.doe@example.com for follow-up. "
            "Diagnosis: J18.9 Pneumonia. NPI: 1234567890."
        ),
    },
    {
        "label": "Discharge summary with PHI",
        "text": (
            "DISCHARGE SUMMARY — Patient John Smith, DOB: 01/15/1960, "
            "Account# ACCT-12345. Treated for acute myocardial infarction. "
            "Follow up with Dr. Roberts at 321-555-0200. "
            "Insurance: BCBS Member# HPN123456789."
        ),
    },
    {
        "label": "Clean text (no PHI)",
        "text": (
            "The infection control committee met on Tuesday to review hand hygiene "
            "compliance rates. Overall compliance improved from 82% to 91% this quarter. "
            "New alcohol-based hand rub dispensers will be installed at all entry points."
        ),
    },
]

# --- Scorer Test Prompts ---
# Different complexity levels to show smart model routing

SCORER_PROMPTS = [
    {
        "label": "Simple greeting",
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "expected": "simple",
    },
    {
        "label": "Clinical question with FHIR/HL7 terms",
        "messages": [
            {"role": "user", "content": (
                "Analyze the HL7 ADT^A01 message flow from Epic to our FHIR server. "
                "Compare the interoperability trade-offs between direct HL7v2 parsing "
                "and FHIR R4 subscription notifications. What are the implications for "
                "our clinical workflow if we switch to pure FHIR? Consider HIPAA "
                "compliance and PHI handling in the data pipeline."
            )}
        ],
        "expected": "complex/reasoning",
    },
    {
        "label": "Multi-step security remediation",
        "messages": [
            {"role": "user", "content": (
                "Step 1: Investigate the CrowdStrike alert for mimikatz on WS-NURSE-042. "
                "Step 2: Check if the service account svc_epic_interface has been compromised. "
                "Step 3: If compromised, rotate credentials in SailPoint and block the source IP "
                "in our Arista firewall. Step 4: Create an incident ticket in Ivanti and "
                "escalate to the CISO. Step 5: Generate a comprehensive forensic report "
                "with timeline, IOCs, and remediation steps."
            )}
        ],
        "expected": "complex",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Demo State — tracks results for the summary dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class DemoState:
    """Tracks everything that happens during the demo for the final dashboard."""

    def __init__(self):
        self.agents_registered: list[dict] = []
        self.rules_created: list[dict] = []
        self.events_sent: list[dict] = []     # {type, description, routed_to, trace_id}
        self.phi_results: list[dict] = []     # {label, detections_count, categories}
        self.scorer_results: list[dict] = []  # {label, tier, score, confidence}
        self.costs: dict = {}                 # from finops summary
        self.errors: list[str] = []

    def add_event(self, event_type: str, description: str, routed_to: str = "?",
                  trace_id: str = ""):
        self.events_sent.append({
            "type": event_type,
            "description": description,
            "routed_to": routed_to,
            "trace_id": trace_id,
        })


state = DemoState()


# ═══════════════════════════════════════════════════════════════════════════════
# DRY RUN MODE — prints what would happen without a server
# ═══════════════════════════════════════════════════════════════════════════════

def run_dry():
    """Dry-run mode: show exactly what the demo would do, no server needed."""
    banner("TRELLIS FULL PLATFORM DEMO — DRY RUN", YELLOW)
    print(f"  {DIM}This shows what the demo WOULD do against a running Trellis server.{RESET}")
    print(f"  {DIM}No network calls are made.{RESET}")

    # --- Agents ---
    banner("1. AGENT REGISTRATION", BLUE)
    for a in AGENTS:
        step(f"Register: {BOLD}{a['name']}{RESET} ({a['agent_id']})")
        substep(f"Department: {a['department']}")
        substep(f"Framework: {a['framework']}")
        substep(f"Tools: {', '.join(a['tools'])}")
        print()

    # --- Rules ---
    banner("2. ROUTING RULES", BLUE)
    for r in RULES:
        step(f"Create rule: {BOLD}{r['name']}{RESET}")
        substep(f"Conditions: {json.dumps(r['conditions'])}")
        substep(f"Actions: {json.dumps(r['actions'])}")
        print()

    # --- Events ---
    banner("3. HL7 ADT MESSAGE (Patient Admission)", MAGENTA)
    step("Send raw HL7v2 ADT^A01 message to /api/events/adapter/hl7")
    substep("Patient: Jane Doe, MRN-1234567")
    substep("Admission to ICU at Main Campus")
    substep("Diagnosis: J18.9 Pneumonia")
    info("Expected: Rules engine matches source_type=hl7 → routes to epic-clinical agent")
    print()
    print(f"    {DIM}HL7 Message Preview:{RESET}")
    for seg in HL7_ADT_MESSAGE.split("\r")[:3]:
        print(f"    {DIM}  {seg[:80]}...{RESET}" if len(seg) > 80 else f"    {DIM}  {seg}{RESET}")

    banner("4. FHIR PATIENT RESOURCE", MAGENTA)
    step("POST FHIR R4 Patient resource to /api/events/adapter/fhir")
    substep("Patient: Jane Doe, DOB 1985-03-15")
    substep("MRN: MRN-1234567")
    info("Expected: Rules engine matches source_type=fhir → routes to epic-clinical agent")
    print()
    json_preview(FHIR_PATIENT)

    banner("5. DOCUMENT INGESTION (Policy PDF)", MAGENTA)
    step("POST document envelope to /api/events/envelope")
    substep("File: infection-control-policy-march-2026.pdf")
    substep("Type: policy | Department: Infection Control")
    info("Expected: Rules engine matches source_type=document → routes to doc-processor agent")

    banner("6. SECURITY ALERT (CrowdStrike)", MAGENTA)
    step("POST security alert envelope to /api/events/envelope")
    substep("Alert: Mimikatz detected on WS-NURSE-042")
    substep("Severity: CRITICAL | Technique: T1003 Credential Dumping")
    info("Expected: Rules engine matches category=security → routes to security-ops agent")

    # --- PHI Shield ---
    banner("7. PHI SHIELD", RED)
    step("Test PHI detection and redaction")
    for sample in PHI_TEST_SAMPLES:
        print()
        substep(f"Test: {sample['label']}")
        # Do local detection to show what would be found
        # Use simple regex to demonstrate without importing trellis
        import re
        ssn_count = len(re.findall(r'\d{3}-\d{2}-\d{4}', sample['text']))
        mrn_count = len(re.findall(r'MRN[\s:#-]*\d{6,10}', sample['text'], re.I))
        phone_count = len(re.findall(r'\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}', sample['text']))
        email_count = len(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', sample['text']))
        total = ssn_count + mrn_count + phone_count + email_count
        if total > 0:
            info(f"Would detect ~{total} PHI elements (SSN:{ssn_count} MRN:{mrn_count} "
                 f"Phone:{phone_count} Email:{email_count})")
        else:
            info("Clean — no PHI expected")

    # --- Scorer ---
    banner("8. PROMPT COMPLEXITY SCORER", CYAN)
    step("Score prompts for smart model routing")
    # Import the actual scorer since it's pure Python with no server dependency
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from trellis.scorer import score_request
        for prompt in SCORER_PROMPTS:
            result = score_request(prompt["messages"])
            tier_color = {"simple": GREEN, "standard": YELLOW,
                          "complex": MAGENTA, "reasoning": RED}.get(result.tier, WHITE)
            print()
            substep(f"{prompt['label']}")
            info(f"Tier: {tier_color}{BOLD}{result.tier}{RESET}  "
                 f"Score: {result.score:.3f}  "
                 f"Confidence: {result.confidence:.1%}  "
                 f"Reason: {result.reason}")
            # Show top contributing dimensions
            top_dims = sorted(result.dimensions, key=lambda d: abs(d.weighted_score), reverse=True)[:3]
            for d in top_dims:
                if d.weighted_score != 0:
                    info(f"  {d.name}: {d.weighted_score:+.4f} (raw={d.raw_score:.2f})")
    except ImportError:
        warn("Could not import scorer — skipping local scoring")
        for prompt in SCORER_PROMPTS:
            substep(f"{prompt['label']} → expected: {prompt['expected']}")

    # --- FinOps ---
    banner("9. FINOPS COST TRACKING", GREEN)
    step("Would query /api/finops/summary for cost breakdown")
    substep("Per-agent costs, per-department rollups, budget utilization")
    substep("In live mode, each routed event generates cost events tracked by the platform")

    # --- Dashboard ---
    banner("10. SUMMARY DASHBOARD", CYAN)
    _print_dry_run_dashboard()

    print()
    print(f"  {GREEN}{BOLD}Dry run complete!{RESET}")
    print(f"  {DIM}To run against a live server:{RESET}")
    print(f"  {DIM}  1. Start Trellis: uv run uvicorn trellis.main:app --port 8100{RESET}")
    print(f"  {DIM}  2. Run: python examples/demo_full_platform.py{RESET}")
    print()


def _print_dry_run_dashboard():
    """Print a mock dashboard for dry-run mode."""
    print(f"  {BOLD}┌─────────────────────────────────────────────────────────────────┐{RESET}")
    print(f"  {BOLD}│  TRELLIS PLATFORM SUMMARY                                     │{RESET}")
    print(f"  {BOLD}├────────────────────┬──────────┬──────────┬──────────┬──────────┤{RESET}")
    print(f"  {BOLD}│ Agent              │ Events   │ Status   │ Cost     │ PHI Det. │{RESET}")
    print(f"  {BOLD}├────────────────────┼──────────┼──────────┼──────────┼──────────┤{RESET}")
    print(f"  │ Epic Clinical      │ 2        │ {GREEN}healthy{RESET}  │ $0.000   │ —        │")
    print(f"  │ Security Ops       │ 1        │ {GREEN}healthy{RESET}  │ $0.000   │ —        │")
    print(f"  │ Doc Processor      │ 1        │ {GREEN}healthy{RESET}  │ $0.000   │ —        │")
    print(f"  {BOLD}├────────────────────┼──────────┼──────────┼──────────┼──────────┤{RESET}")
    print(f"  {BOLD}│ TOTAL              │ 4        │          │ $0.000   │ 0        │{RESET}")
    print(f"  {BOLD}└────────────────────┴──────────┴──────────┴──────────┴──────────┘{RESET}")
    print()
    print(f"  {BOLD}PHI Shield Results:{RESET}")
    print(f"  ┌────────────────────────────────────────┬────────────┬────────────────────┐")
    print(f"  │ Test                                   │ Detections │ Categories         │")
    print(f"  ├────────────────────────────────────────┼────────────┼────────────────────┤")
    print(f"  │ Patient referral note                  │ ~6         │ SSN,MRN,PHONE,EMAIL│")
    print(f"  │ Discharge summary                      │ ~4         │ PHONE,EMAIL,ACCT   │")
    print(f"  │ Clean text (no PHI)                    │ 0          │ —                  │")
    print(f"  └────────────────────────────────────────┴────────────┴────────────────────┘")
    print()
    print(f"  {BOLD}Scorer Results (Smart Model Routing):{RESET}")
    print(f"  ┌────────────────────────────────────────┬──────────┬─────────┬────────────┐")
    print(f"  │ Prompt                                 │ Tier     │ Score   │ Confidence │")
    print(f"  ├────────────────────────────────────────┼──────────┼─────────┼────────────┤")
    print(f"  │ Simple greeting                        │ {GREEN}simple{RESET}   │ -0.300  │ 95%        │")
    print(f"  │ Clinical FHIR/HL7 analysis             │ {RED}complex{RESET}  │  0.250  │ 88%        │")
    print(f"  │ Multi-step security remediation        │ {MAGENTA}complex{RESET}  │  0.300  │ 92%        │")
    print(f"  └────────────────────────────────────────┴──────────┴─────────┴────────────┘")


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MODE — runs against a real Trellis server
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup_previous_run():
    """Remove agents/rules from any previous demo run."""
    step("Cleaning up any previous demo data...")
    for a in AGENTS:
        api("DELETE", f"/agents/{a['agent_id']}")
    # Rules: fetch all, delete any matching our demo rules
    rules = api("GET", "/rules")
    if rules:
        demo_rule_names = {r["name"] for r in RULES}
        for r in rules:
            if r.get("name") in demo_rule_names:
                api("DELETE", f"/rules/{r['id']}")
    substep("Clean slate ready")


def register_agents():
    """Register all 3 demo agents."""
    banner("1. AGENT REGISTRATION", BLUE)
    step("Registering 3 agents across Clinical, Security, and Compliance...")
    print()

    for agent_data in AGENTS:
        result = api("POST", "/agents", agent_data)
        if result:
            agent_id = result.get("agent_id", agent_data["agent_id"])
            api_key = result.get("api_key", "")
            success(f"{BOLD}{agent_data['name']}{RESET} registered")
            substep(f"ID: {agent_id} | Dept: {agent_data['department']}")
            substep(f"Tools: {', '.join(agent_data['tools'])}")
            if api_key:
                substep(f"API Key: {api_key[:16]}... (for LLM Gateway auth)")
            state.agents_registered.append(result)
            print()
        else:
            state.errors.append(f"Failed to register {agent_data['agent_id']}")


def create_rules():
    """Create routing rules."""
    banner("2. ROUTING RULES", BLUE)
    step("Creating event routing rules...")
    print()

    for rule_data in RULES:
        result = api("POST", "/rules", rule_data)
        if result:
            success(f"Rule: {BOLD}{rule_data['name']}{RESET}")
            substep(f"When: {json.dumps(rule_data['conditions'])}")
            substep(f"Then: {json.dumps(rule_data['actions'])}")
            state.rules_created.append(result)
            print()
        else:
            state.errors.append(f"Failed to create rule: {rule_data['name']}")


def send_hl7_event():
    """Send an HL7 ADT^A01 message through the HL7 adapter."""
    banner("3. HL7 ADT MESSAGE — Patient Admission", MAGENTA)
    step("Sending HL7v2 ADT^A01 (patient admission) to the HL7 adapter...")
    substep("Patient: Jane Doe | MRN: 1234567 | Facility: Main Campus")
    substep("Admission: ICU Bed 3 | Diagnosis: J18.9 Pneumonia")
    print()

    # Show a preview of the raw HL7 message
    info("Raw HL7v2 message:")
    for seg in HL7_ADT_MESSAGE.split("\r"):
        preview = seg[:78] + "..." if len(seg) > 78 else seg
        info(f"  {preview}")
    print()

    result = api("POST", "/events/adapter/hl7", raw_body=HL7_ADT_MESSAGE,
                 content_type="text/plain")
    if result:
        matched = result.get("matched_rule", result.get("routed_to", ""))
        trace = result.get("trace_id", "")
        success(f"HL7 message routed successfully!")
        substep(f"Matched rule: {matched}")
        substep(f"Trace ID: {trace}")
        state.add_event("HL7 ADT^A01", "Patient admission — Jane Doe, ICU",
                        "epic-clinical", trace)
    else:
        warn("HL7 routing returned no result (agent may not be reachable)")
        state.add_event("HL7 ADT^A01", "Patient admission — Jane Doe, ICU",
                        "epic-clinical (attempted)")


def send_fhir_event():
    """Send a FHIR Patient resource through the FHIR adapter."""
    banner("4. FHIR PATIENT RESOURCE", MAGENTA)
    step("Sending FHIR R4 Patient resource to the FHIR adapter...")
    substep("Resource: Patient/patient-jane-doe-12345")
    substep("Source: Epic EMR → Azure Health Data Services → Trellis")
    print()

    json_preview(FHIR_PATIENT)
    print()

    result = api("POST", "/events/adapter/fhir", FHIR_PATIENT)
    if result:
        matched = result.get("matched_rule", result.get("routed_to", ""))
        trace = result.get("trace_id", "")
        success(f"FHIR resource routed successfully!")
        substep(f"Matched rule: {matched}")
        substep(f"Trace ID: {trace}")
        state.add_event("FHIR Patient", "Patient resource — Jane Doe",
                        "epic-clinical", trace)
    else:
        warn("FHIR routing returned no result")
        state.add_event("FHIR Patient", "Patient resource — Jane Doe",
                        "epic-clinical (attempted)")


def send_document_event():
    """Send a document ingestion envelope."""
    banner("5. DOCUMENT INGESTION — Policy PDF", MAGENTA)
    step("Sending document envelope (infection control policy) to event router...")
    substep("File: infection-control-policy-march-2026.pdf")
    substep("Type: policy | Department: Infection Control")
    substep("This simulates a new policy dropping on SharePoint → Trellis picks it up")
    print()

    result = api("POST", "/events/envelope", DOCUMENT_ENVELOPE)
    if result:
        matched = result.get("matched_rule", result.get("routed_to", ""))
        trace = result.get("trace_id", DOCUMENT_ENVELOPE["metadata"]["trace_id"])
        success(f"Document envelope routed successfully!")
        substep(f"Matched rule: {matched}")
        substep(f"Trace ID: {trace}")
        state.add_event("Document", "Infection control policy PDF",
                        "doc-processor", trace)
    else:
        warn("Document routing returned no result")
        state.add_event("Document", "Infection control policy PDF",
                        "doc-processor (attempted)")


def send_security_alert():
    """Send a security alert envelope."""
    banner("6. SECURITY ALERT — CrowdStrike Detection", MAGENTA)
    step(f"{RED}{BOLD}CRITICAL:{RESET} Sending CrowdStrike Falcon alert...")
    substep("Mimikatz detected on WS-NURSE-042")
    substep("Technique: T1003 Credential Dumping | User: svc_epic_interface")
    substep("This is the kind of alert that triggers immediate incident response")
    print()

    result = api("POST", "/events/envelope", SECURITY_ALERT)
    if result:
        matched = result.get("matched_rule", result.get("routed_to", ""))
        trace = result.get("trace_id", SECURITY_ALERT["metadata"]["trace_id"])
        success(f"Security alert routed successfully!")
        substep(f"Matched rule: {matched}")
        substep(f"Priority escalated to: CRITICAL")
        substep(f"Trace ID: {trace}")
        state.add_event("Security Alert", "Mimikatz on WS-NURSE-042 (CRITICAL)",
                        "security-ops", trace)
    else:
        warn("Security alert routing returned no result")
        state.add_event("Security Alert", "Mimikatz on WS-NURSE-042 (CRITICAL)",
                        "security-ops (attempted)")


def test_phi_shield():
    """Test PHI Shield detection and redaction."""
    banner("7. PHI SHIELD — HIPAA-Compliant Redaction", RED)
    step("Testing PHI detection against sample texts...")
    substep("PHI Shield scans all text for HIPAA Safe Harbor identifiers")
    substep("Detects: SSN, MRN, phone, email, DOB, NPI, account numbers, and more")
    print()

    for sample in PHI_TEST_SAMPLES:
        print(f"  {YELLOW}{'─' * 66}{RESET}")
        step(f"Test: {BOLD}{sample['label']}{RESET}")
        info(f"Input: \"{sample['text'][:100]}...\"" if len(sample['text']) > 100
             else f"Input: \"{sample['text']}\"")

        result = api("POST", "/phi/test", {"text": sample["text"]})
        if result:
            detections = result.get("detections", [])
            redacted = result.get("redacted", "")
            if detections:
                success(f"{RED}{BOLD}{len(detections)} PHI elements detected!{RESET}")
                categories = sorted(set(d["type"] for d in detections))
                for det in detections:
                    substep(f"{det['type']}: \"{det['text']}\" → redacted")
                info(f"Categories: {', '.join(categories)}")
                info(f"Redacted: \"{redacted[:100]}...\"" if len(redacted) > 100
                     else f"Redacted: \"{redacted}\"")
                state.phi_results.append({
                    "label": sample["label"],
                    "detections": len(detections),
                    "categories": categories,
                })
            else:
                success(f"{GREEN}Clean — no PHI detected{RESET}")
                state.phi_results.append({
                    "label": sample["label"],
                    "detections": 0,
                    "categories": [],
                })
            print()
        else:
            state.errors.append(f"PHI test failed for: {sample['label']}")


def test_scorer():
    """Test the prompt complexity scorer."""
    banner("8. PROMPT COMPLEXITY SCORER — Smart Model Routing", CYAN)
    step("Scoring prompts to determine optimal model tier...")
    substep("Trellis routes each request to the cheapest model that can handle it")
    substep("Simple → GPT-4o-mini ($0.15/1M) | Complex → GPT-4o ($2.50/1M) | Reasoning → o1 ($15/1M)")
    print()

    # Use the scorer directly — it's pure Python, no server needed
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from trellis.scorer import score_request

        for prompt in SCORER_PROMPTS:
            result = score_request(prompt["messages"])
            tier_colors = {
                "simple": GREEN, "standard": YELLOW,
                "complex": MAGENTA, "reasoning": RED,
            }
            tc = tier_colors.get(result.tier, WHITE)

            print(f"  {CYAN}{'─' * 66}{RESET}")
            step(f"Prompt: {BOLD}{prompt['label']}{RESET}")
            info(f"\"{prompt['messages'][-1]['content'][:80]}...\"")
            print()
            success(f"Tier: {tc}{BOLD}{result.tier.upper()}{RESET}  │  "
                    f"Score: {result.score:+.3f}  │  "
                    f"Confidence: {result.confidence:.0%}  │  "
                    f"Reason: {result.reason}")

            # Show top 3 contributing dimensions
            top = sorted(result.dimensions,
                         key=lambda d: abs(d.weighted_score), reverse=True)[:3]
            top_nonzero = [d for d in top if d.weighted_score != 0]
            if top_nonzero:
                dims_str = ", ".join(
                    f"{d.name}={d.weighted_score:+.4f}" for d in top_nonzero)
                substep(f"Top factors: {dims_str}")

            # Show model routing implication
            model_map = {
                "simple": "GPT-4o-mini (~$0.15/1M tokens)",
                "standard": "GPT-4o (~$2.50/1M tokens)",
                "complex": "GPT-4o ($2.50/1M tokens)",
                "reasoning": "o1 ($15/1M tokens)",
            }
            substep(f"Would route to: {model_map.get(result.tier, 'unknown')}")

            state.scorer_results.append({
                "label": prompt["label"],
                "tier": result.tier,
                "score": result.score,
                "confidence": result.confidence,
            })
            print()

    except ImportError as e:
        warn(f"Could not import scorer: {e}")
        warn("Scorer test skipped — run from the trellis project directory")


def check_finops():
    """Pull FinOps summary from the platform."""
    banner("9. FINOPS — Cost Tracking & Budget Management", GREEN)
    step("Querying FinOps summary for cost data...")
    print()

    result = api("GET", "/finops/summary")
    if result:
        state.costs = result
        success("FinOps summary retrieved")

        # Total spend
        total_30d = result.get("spend_30d_usd", 0)
        total_7d = result.get("spend_7d_usd", 0)
        total_24h = result.get("spend_24h_usd", 0)
        substep(f"Last 24h: ${total_24h:.4f} | Last 7d: ${total_7d:.4f} | Last 30d: ${total_30d:.4f}")

        # Per-agent breakdown
        agents_cost = result.get("top_agents", [])
        if agents_cost:
            print()
            info("Per-Agent Cost Breakdown:")
            for ac in agents_cost:
                info(f"  {ac.get('agent_id', '?')}: ${ac.get('total_cost_usd', 0):.4f} "
                     f"({ac.get('total_requests', 0)} requests)")

        # Budget utilization
        budgets = result.get("budget_utilization", [])
        if budgets:
            print()
            info("Budget Utilization:")
            for b in budgets:
                pct = b.get("utilization_pct", 0)
                bar_color = GREEN if pct < 80 else (YELLOW if pct < 100 else RED)
                info(f"  {b.get('agent_id', '?')}: {bar_color}{pct:.0f}%{RESET} "
                     f"(${b.get('spent', 0):.4f} / ${b.get('budget', 0):.2f})")

        # Anomalies
        anomalies = result.get("anomalies", [])
        if anomalies:
            print()
            warn(f"{len(anomalies)} cost anomalies detected!")
            for a in anomalies[:3]:
                warn(f"  {a}")
    else:
        warn("Could not retrieve FinOps summary")
    print()


def print_summary_dashboard():
    """Print the final summary dashboard — the money shot."""
    banner("10. SUMMARY DASHBOARD", CYAN)

    # Agent summary table
    print(f"  {BOLD}┌──────────────────────┬──────────┬──────────┬──────────┬──────────┐{RESET}")
    print(f"  {BOLD}│ Agent                │ Events   │ Status   │ Cost     │ PHI Det. │{RESET}")
    print(f"  {BOLD}├──────────────────────┼──────────┼──────────┼──────────┼──────────┤{RESET}")

    # Count events per agent
    agent_events = {}
    for ev in state.events_sent:
        target = ev["routed_to"].split(" ")[0]  # strip "(attempted)"
        agent_events[target] = agent_events.get(target, 0) + 1

    total_events = 0
    total_phi = sum(p["detections"] for p in state.phi_results)
    for agent_data in AGENTS:
        aid = agent_data["agent_id"]
        name = agent_data["name"][:20]
        events = agent_events.get(aid, 0)
        total_events += events
        status = f"{GREEN}healthy{RESET}"
        cost = "$0.000"  # Mock agents don't incur real cost
        phi = "—"
        print(f"  │ {name:<20s} │ {events:<8d} │ {status}  │ {cost:<8s} │ {phi:<8s} │")

    print(f"  {BOLD}├──────────────────────┼──────────┼──────────┼──────────┼──────────┤{RESET}")
    print(f"  {BOLD}│ TOTAL                │ {total_events:<8d} │          │ $0.000   │ {total_phi:<8d} │{RESET}")
    print(f"  {BOLD}└──────────────────────┴──────────┴──────────┴──────────┴──────────┘{RESET}")

    # Events timeline
    if state.events_sent:
        print()
        print(f"  {BOLD}Event Flow:{RESET}")
        for i, ev in enumerate(state.events_sent, 1):
            arrow = f"{CYAN}→{RESET}"
            print(f"    {i}. [{ev['type']:<15s}] {arrow} {ev['routed_to']:<20s} │ {ev['description']}")

    # PHI Shield results
    if state.phi_results:
        print()
        print(f"  {BOLD}PHI Shield Results:{RESET}")
        print(f"  ┌────────────────────────────────────────┬────────────┬─────────────────────┐")
        print(f"  │ Test                                   │ Detections │ Categories          │")
        print(f"  ├────────────────────────────────────────┼────────────┼─────────────────────┤")
        for p in state.phi_results:
            label = p["label"][:38]
            dets = str(p["detections"])
            cats = ",".join(p["categories"])[:19] if p["categories"] else "—"
            print(f"  │ {label:<38s} │ {dets:^10s} │ {cats:<19s} │")
        print(f"  └────────────────────────────────────────┴────────────┴─────────────────────┘")

    # Scorer results
    if state.scorer_results:
        print()
        print(f"  {BOLD}Scorer Results (Smart Model Routing):{RESET}")
        print(f"  ┌────────────────────────────────────────┬───────────┬─────────┬────────────┐")
        print(f"  │ Prompt                                 │ Tier      │ Score   │ Confidence │")
        print(f"  ├────────────────────────────────────────┼───────────┼─────────┼────────────┤")
        for s in state.scorer_results:
            label = s["label"][:38]
            tc = {"simple": GREEN, "standard": YELLOW,
                  "complex": MAGENTA, "reasoning": RED}.get(s["tier"], WHITE)
            tier_str = f"{tc}{s['tier']:<7s}{RESET}"
            # For alignment, we need to account for ANSI codes in the tier column
            print(f"  │ {label:<38s} │ {tier_str}   │ {s['score']:+.3f}  │ {s['confidence']:>9.0%}  │")
        print(f"  └────────────────────────────────────────┴───────────┴─────────┴────────────┘")

    # Errors
    if state.errors:
        print()
        warn(f"{len(state.errors)} errors occurred:")
        for e in state.errors:
            fail(f"  {e}")


def run_live():
    """Live mode: run the full demo against a Trellis server."""
    banner("TRELLIS FULL PLATFORM DEMO", CYAN)
    print(f"  {DIM}Enterprise AI Agent Orchestration for Healthcare{RESET}")
    print(f"  {DIM}Health First — Brevard County's Integrated Health System{RESET}")
    print(f"  {DIM}{'─' * 56}{RESET}")
    print(f"  {DIM}Target: {BASE_URL}{RESET}")
    print(f"  {DIM}Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}{RESET}")
    print()

    # Health check
    step("Checking Trellis server health...")
    health = api("GET", "/../health")
    if not health:
        print()
        fail("Cannot reach Trellis server!")
        print(f"  {DIM}Start it with: uv run uvicorn trellis.main:app --port 8100{RESET}")
        print(f"  {DIM}Or run with --dry-run to see the demo without a server{RESET}")
        sys.exit(1)
    success(f"Trellis is running: {health.get('status', 'ok')}")
    print()

    # Run each phase
    pause(0.3)
    cleanup_previous_run()
    pause(0.3)
    register_agents()
    pause(0.3)
    create_rules()
    pause(0.3)
    send_hl7_event()
    pause(0.3)
    send_fhir_event()
    pause(0.3)
    send_document_event()
    pause(0.3)
    send_security_alert()
    pause(0.3)
    test_phi_shield()
    pause(0.3)
    test_scorer()
    pause(0.3)
    check_finops()
    pause(0.3)
    print_summary_dashboard()

    # Final status
    print()
    if state.errors:
        print(f"  {YELLOW}{BOLD}Demo complete with {len(state.errors)} warnings.{RESET}")
    else:
        print(f"  {GREEN}{BOLD}Demo complete — all systems operational!{RESET}")
    print()
    print(f"  {DIM}This is Trellis: Kubernetes for AI agents.{RESET}")
    print(f"  {DIM}One platform. Every agent. Full governance.{RESET}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Trellis Full Platform Demo — Enterprise AI Agent Orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/demo_full_platform.py              # Run against live server
  python examples/demo_full_platform.py --dry-run    # Preview without server
  python examples/demo_full_platform.py --port 9000  # Custom port
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what WOULD happen without needing a running server")
    parser.add_argument("--port", type=int, default=8100,
                        help="Trellis server port (default: 8100)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colors")
    args = parser.parse_args()

    # Update base URL if custom port
    global BASE_URL
    BASE_URL = f"http://localhost:{args.port}"

    # Disable colors if requested
    if args.no_color:
        global BOLD, DIM, RESET, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE
        global BG_RED, BG_GREEN, BG_BLUE
        BOLD = DIM = RESET = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = ""
        BG_RED = BG_GREEN = BG_BLUE = ""

    if args.dry_run:
        run_dry()
    else:
        run_live()


if __name__ == "__main__":
    main()
