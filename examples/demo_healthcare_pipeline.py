#!/usr/bin/env python3
"""
Trellis Healthcare Pipeline Demo — HL7v2 & FHIR R4 Adapters
=============================================================
Showcases Trellis ingesting clinical messages from HL7v2 interfaces and
FHIR R4 APIs, routing them to specialized healthcare agents.

This demonstrates a realistic hospital integration scenario where ADT feeds,
lab results, scheduling messages, and FHIR resources all flow through a
single orchestration layer with full audit trails.

Prerequisites:
    1. Trellis running: cd projects/trellis && uv run uvicorn trellis.main:app --port 8100
    2. Run this script: uv run python examples/demo_healthcare_pipeline.py

Or start the server inline:
    uv run python examples/demo_healthcare_pipeline.py --server

What it demonstrates:
    - HL7v2 adapter: ADT^A01, ORU^R01, SIU^S12 message ingestion
    - FHIR R4 adapter: Patient, Encounter, Observation resources
    - FHIR Subscription webhook: Epic-style subscription notifications
    - Tag-based routing rules (HL7 message types → agents, FHIR resource types → agents)
    - Full audit trail per message with trace IDs
    - Cross-protocol correlation (HL7 + FHIR for the same patient)
"""

import argparse
import json
import subprocess
import sys
import time
import uuid

import requests

BASE = "http://localhost:8100"

# ── Terminal Colors ────────────────────────────────────────────────────────

BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(text: str):
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{'='*70}\n")


def step(text: str):
    print(f"  {GREEN}▸{RESET} {text}")


def info(text: str):
    print(f"    {DIM}{text}{RESET}")


def warn(text: str):
    print(f"    {YELLOW}⚠ {text}{RESET}")


def success(text: str):
    print(f"  {GREEN}✓{RESET} {text}")


def fail(text: str):
    print(f"  {RED}✗ {text}{RESET}")
    sys.exit(1)


def section(emoji: str, text: str):
    print(f"\n  {MAGENTA}{emoji} {text}{RESET}")


# ── Healthcare Agents ──────────────────────────────────────────────────────

AGENTS = [
    {
        "agent_id": "bed-manager",
        "name": "Bed Manager — Patient Flow Agent",
        "owner": "Nancy Rivera, Director Patient Flow",
        "department": "Patient Flow",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["epic-adt", "bed-board", "capacity-tracker", "transfer-center"],
        "channels": ["hl7", "fhir", "api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "lab-processor",
        "name": "Lab Processor — Results & Orders Agent",
        "owner": "Dr. Rachel Kim, Lab Director",
        "department": "Laboratory",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["epic-results", "beaker-interface", "critical-alert", "abnormal-flag"],
        "channels": ["hl7", "fhir", "api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "scheduler",
        "name": "Scheduler — Appointments & Scheduling Agent",
        "owner": "Tom Briggs, Manager Scheduling Services",
        "department": "Scheduling",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["epic-cadence", "appointment-manager", "waitlist-optimizer", "reminder-send"],
        "channels": ["hl7", "fhir", "api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
]

# ── Routing Rules ──────────────────────────────────────────────────────────

RULES = [
    # HL7-based rules (tag matching)
    {
        "name": "ADT messages → Bed Manager",
        "priority": 100,
        "conditions": {"routing_hints.tags": {"$contains": "adt"}},
        "actions": {"route_to": "bed-manager"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "ORU results → Lab Processor",
        "priority": 100,
        "conditions": {"routing_hints.tags": {"$contains": "result"}},
        "actions": {"route_to": "lab-processor"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "SIU scheduling → Scheduler",
        "priority": 100,
        "conditions": {"routing_hints.tags": {"$contains": "scheduling"}},
        "actions": {"route_to": "scheduler"},
        "active": True,
        "fan_out": False,
    },
    # FHIR-based rules
    {
        "name": "FHIR Encounter → Bed Manager",
        "priority": 110,
        "conditions": {"routing_hints.tags": {"$contains": "encounter"}},
        "actions": {"route_to": "bed-manager"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "FHIR Observation → Lab Processor",
        "priority": 110,
        "conditions": {"routing_hints.tags": {"$contains": "observation"}},
        "actions": {"route_to": "lab-processor"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "FHIR Appointment → Scheduler",
        "priority": 110,
        "conditions": {"routing_hints.tags": {"$contains": "appointment"}},
        "actions": {"route_to": "scheduler"},
        "active": True,
        "fan_out": False,
    },
]

# ── Sample HL7v2 Messages ─────────────────────────────────────────────────

HL7_ADT_A01 = (
    "MSH|^~\\&|EPIC|HOLMESREGIONAL|TRELLIS|HF|20260301120000||ADT^A01|MSG10001|P|2.5\r"
    "PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F\r"
    "PV1||I|ICU^301^A|||||||||||||||VN-20260301-001"
)

HL7_ORU_R01 = (
    "MSH|^~\\&|BEAKER|HOLMESREGIONAL|EPIC|HF|20260301130000||ORU^R01|MSG10002|P|2.5\r"
    "PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F\r"
    "OBR|1|ORD-5521||BMP^Basic Metabolic Panel\r"
    "OBX|1|NM|GLU^Glucose||142|mg/dL|70-100|H\r"
    "OBX|2|NM|CREAT^Creatinine||1.1|mg/dL|0.7-1.3|N\r"
    "OBX|3|NM|BUN^Blood Urea Nitrogen||18|mg/dL|7-20|N"
)

HL7_SIU_S12 = (
    "MSH|^~\\&|CADENCE|VIERAHOSPITAL|TRELLIS|HF|20260301090000||SIU^S12|MSG10003|P|2.5\r"
    "PID|||MRN-41098^^^HF||THOMPSON^JAMES||19880507|M"
)

# ── Sample FHIR Resources ─────────────────────────────────────────────────

FHIR_PATIENT = {
    "resourceType": "Patient",
    "id": "pat-hf-78432",
    "identifier": [{"system": "urn:oid:2.16.840.1.113883.3.552", "value": "MRN-78432"}],
    "name": [{"family": "Martinez", "given": ["Elena"]}],
    "gender": "female",
    "birthDate": "1965-12-14",
}

FHIR_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-20260301-001",
    "status": "in-progress",
    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP"},
    "subject": {"reference": "Patient/pat-hf-78432", "display": "Elena Martinez"},
    "period": {"start": "2026-03-01T12:00:00-05:00"},
    "location": [{"location": {"display": "Holmes Regional — ICU 301-A"}}],
    "reasonCode": [{"text": "Hyperglycemia with altered mental status"}],
}

FHIR_OBSERVATION = {
    "resourceType": "Observation",
    "id": "obs-vitals-20260301",
    "status": "final",
    "category": [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs",
                }
            ]
        }
    ],
    "code": {
        "coding": [
            {"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}
        ]
    },
    "subject": {"reference": "Patient/pat-hf-78432", "display": "Elena Martinez"},
    "effectiveDateTime": "2026-03-01T12:30:00-05:00",
    "valueQuantity": {"value": 92, "unit": "beats/minute", "system": "http://unitsofmeasure.org", "code": "/min"},
}

FHIR_APPOINTMENT = {
    "resourceType": "Appointment",
    "id": "appt-20260305-001",
    "status": "booked",
    "description": "Follow-up: Post-discharge glucose monitoring",
    "start": "2026-03-05T10:00:00-05:00",
    "end": "2026-03-05T10:30:00-05:00",
    "participant": [
        {"actor": {"reference": "Patient/pat-hf-78432", "display": "Elena Martinez"}, "status": "accepted"},
        {"actor": {"reference": "Practitioner/doc-patel", "display": "Dr. Anita Patel"}, "status": "accepted"},
    ],
}

FHIR_SUBSCRIPTION_NOTIFICATION = {
    "resourceType": "Bundle",
    "type": "subscription-notification",
    "entry": [
        {
            "resource": {
                "resourceType": "SubscriptionStatus",
                "status": "active",
                "type": "event-notification",
                "subscription": {"reference": "Subscription/epic-adt-sub-001"},
            }
        },
        {
            "resource": {
                "resourceType": "Encounter",
                "id": "enc-sub-20260301",
                "status": "arrived",
                "class": {"code": "EMER"},
                "subject": {"reference": "Patient/pat-hf-55210", "display": "Robert Chen"},
                "location": [{"location": {"display": "Cape Canaveral Hospital — ED Bay 7"}}],
                "reasonCode": [{"text": "Chest pain, rule out ACS"}],
            }
        },
    ],
}


# ── Demo Functions ─────────────────────────────────────────────────────────

def check_health() -> bool:
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


def cleanup():
    """Remove demo agents/rules from prior runs."""
    for agent in AGENTS:
        try:
            requests.delete(f"{BASE}/api/agents/{agent['agent_id']}", timeout=5)
        except Exception:
            pass
    try:
        r = requests.get(f"{BASE}/api/rules", timeout=5)
        if r.status_code == 200:
            rule_names = {rule["name"] for rule in RULES}
            for rule in r.json():
                if rule["name"] in rule_names:
                    requests.delete(f"{BASE}/api/rules/{rule['id']}", timeout=5)
    except Exception:
        pass


def register_agents():
    header("1 │ REGISTER HEALTHCARE AGENTS")
    print("  Three specialized agents, each handling a different clinical domain.\n")

    for agent_def in AGENTS:
        r = requests.post(f"{BASE}/api/agents", json=agent_def, timeout=10)
        if r.status_code == 201:
            data = r.json()
            step(f"{BOLD}{data['name']}{RESET}")
            info(f"ID: {data['agent_id']}  │  Dept: {data['department']}")
            info(f"Tools: {', '.join(data['tools'])}")
            info(f"Channels: {', '.join(data['channels'])}")
        elif r.status_code == 409:
            warn(f"{agent_def['agent_id']} already exists (skipping)")
        else:
            fail(f"Failed to register {agent_def['agent_id']}: {r.status_code} {r.text}")


def create_rules():
    header("2 │ CREATE ROUTING RULES")
    print("  Six rules map HL7 message types and FHIR resource types to agents.\n")

    section("📨", "HL7v2 Rules")
    for rule_def in RULES[:3]:
        r = requests.post(f"{BASE}/api/rules", json=rule_def, timeout=10)
        if r.status_code == 201:
            data = r.json()
            step(f"Rule #{data['id']}: {BOLD}{data['name']}{RESET}")
        else:
            warn(f"Rule '{rule_def['name']}': {r.status_code}")

    section("🔥", "FHIR R4 Rules")
    for rule_def in RULES[3:]:
        r = requests.post(f"{BASE}/api/rules", json=rule_def, timeout=10)
        if r.status_code == 201:
            data = r.json()
            step(f"Rule #{data['id']}: {BOLD}{data['name']}{RESET}")
        else:
            warn(f"Rule '{rule_def['name']}': {r.status_code}")


def send_hl7_messages() -> list[dict]:
    header("3 │ HL7v2 MESSAGE INGESTION")
    print("  Sending raw HL7v2 messages through the /api/adapter/hl7 endpoint.")
    print("  These simulate an Epic ADT feed, Beaker lab results, and Cadence scheduling.\n")

    messages = [
        ("ADT^A01 — Patient Admission", HL7_ADT_A01,
         "Elena Martinez admitted to Holmes Regional ICU 301-A (hyperglycemia)"),
        ("ORU^R01 — Lab Results", HL7_ORU_R01,
         "BMP results for Martinez: Glucose 142 mg/dL (HIGH), Creatinine 1.1, BUN 18"),
        ("SIU^S12 — Appointment Scheduled", HL7_SIU_S12,
         "James Thompson appointment booked via Cadence at Viera Hospital"),
    ]

    results = []
    for name, raw_msg, description in messages:
        print(f"  {CYAN}━━━ {name} ━━━{RESET}")
        info(description)

        r = requests.post(
            f"{BASE}/api/adapter/hl7",
            data=raw_msg,
            headers={"Content-Type": "text/plain"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            agent = data.get("target_agent", "none")
            rule = data.get("matched_rule", "none")
            trace = data.get("trace_id", "")
            step(f"Routed → {BOLD}{agent}{RESET}  │  Rule: {rule}")
            if trace:
                info(f"Trace: {trace}")
            results.append({"name": name, "agent": agent, "trace_id": trace, "protocol": "HL7v2"})
        else:
            warn(f"Failed: {r.status_code} — {r.text[:80]}")
            results.append({"name": name, "agent": "ERROR", "trace_id": "", "protocol": "HL7v2"})
        print()

    return results


def send_fhir_resources() -> list[dict]:
    header("4 │ FHIR R4 RESOURCE INGESTION")
    print("  Sending FHIR resources through /api/adapter/fhir.")
    print("  Simulates an Epic FHIR API integration.\n")

    resources = [
        ("Patient Resource", FHIR_PATIENT,
         "Elena Martinez demographics (correlates with HL7 MRN-78432)"),
        ("Encounter Resource", FHIR_ENCOUNTER,
         "ICU encounter for Martinez — hyperglycemia with altered mental status"),
        ("Observation — Vital Signs", FHIR_OBSERVATION,
         "Heart rate 92 bpm recorded at 12:30 during ICU stay"),
    ]

    results = []
    for name, resource, description in resources:
        print(f"  {CYAN}━━━ {name} ━━━{RESET}")
        info(description)

        r = requests.post(f"{BASE}/api/adapter/fhir", json=resource, timeout=10)
        if r.status_code == 200:
            data = r.json()
            agent = data.get("target_agent", "none")
            rule = data.get("matched_rule", "none")
            trace = data.get("trace_id", "")
            step(f"Routed → {BOLD}{agent}{RESET}  │  Rule: {rule}")
            if trace:
                info(f"Trace: {trace}")
            results.append({"name": name, "agent": agent, "trace_id": trace, "protocol": "FHIR"})
        else:
            warn(f"Failed: {r.status_code} — {r.text[:80]}")
            results.append({"name": name, "agent": "ERROR", "trace_id": "", "protocol": "FHIR"})
        print()

    return results


def send_fhir_subscription() -> list[dict]:
    header("5 │ FHIR SUBSCRIPTION WEBHOOK")
    print("  Simulating an Epic FHIR Subscription notification.")
    print("  This is how real-time ADT events arrive from Epic's subscription API.\n")

    print(f"  {CYAN}━━━ Subscription Notification — ED Arrival ━━━{RESET}")
    info("Robert Chen arrived at Cape Canaveral Hospital ED Bay 7 (chest pain, r/o ACS)")

    r = requests.post(f"{BASE}/api/adapter/fhir/subscription", json=FHIR_SUBSCRIPTION_NOTIFICATION, timeout=10)
    results = []
    if r.status_code == 200:
        data = r.json()
        processed = data.get("envelopes_processed", 0)
        step(f"Processed {BOLD}{processed}{RESET} resource(s) from subscription notification")
        sub_results = data.get("results", [])
        for sr in sub_results:
            agent = sr.get("target_agent", "none")
            trace = sr.get("trace_id", "")
            info(f"→ {BOLD}{agent}{RESET}  │  Trace: {trace}")
            results.append({"name": "FHIR Subscription — Encounter", "agent": agent, "trace_id": trace, "protocol": "FHIR Sub"})
    else:
        warn(f"Failed: {r.status_code} — {r.text[:80]}")
    print()

    return results


def show_audit_trail(all_results: list[dict]):
    header("6 │ AUDIT TRAIL")
    print("  Every message — HL7 and FHIR — is logged with full traceability.")
    print("  HIPAA-ready: immutable, timestamped, queryable by trace ID.\n")

    r = requests.get(f"{BASE}/api/audit", params={"limit": 50}, timeout=10)
    if r.status_code == 200:
        events = r.json()
        step(f"Total audit events: {BOLD}{len(events)}{RESET}")

        by_type: dict[str, int] = {}
        for evt in events:
            t = evt["event_type"]
            by_type[t] = by_type.get(t, 0) + 1

        for event_type, count in sorted(by_type.items()):
            info(f"  {event_type}: {count}")

        # Show one trace in detail
        trace_ids = [r["trace_id"] for r in all_results if r.get("trace_id")]
        if trace_ids:
            print()
            step(f"Sample trace ({trace_ids[0][:20]}...):")
            tr = requests.get(f"{BASE}/api/audit/trace/{trace_ids[0]}", timeout=10)
            if tr.status_code == 200:
                for evt in tr.json():
                    info(f"  [{evt['event_type']}] agent={evt.get('agent_id', '-')} │ {evt['timestamp']}")


def show_summary(all_results: list[dict]):
    header("7 │ PIPELINE SUMMARY")
    print("  Complete message flow — every protocol, every agent, every trace.\n")

    # Group by agent
    by_agent: dict[str, list[dict]] = {}
    for result in all_results:
        agent = result.get("agent", "unrouted")
        by_agent.setdefault(agent, []).append(result)

    agent_emoji = {"bed-manager": "🛏️", "lab-processor": "🧪", "scheduler": "📅"}

    for agent, messages in by_agent.items():
        emoji = agent_emoji.get(agent, "❓")
        step(f"{emoji} {BOLD}{agent}{RESET}  ({len(messages)} messages)")
        for msg in messages:
            info(f"  [{msg['protocol']}] {msg['name']}")

    # Stats
    print()
    total = len(all_results)
    hl7_count = sum(1 for r in all_results if r["protocol"] == "HL7v2")
    fhir_count = sum(1 for r in all_results if r["protocol"] in ("FHIR", "FHIR Sub"))
    routed = sum(1 for r in all_results if r["agent"] not in ("none", "ERROR"))

    step(f"Total messages:  {BOLD}{total}{RESET}")
    step(f"HL7v2 messages:  {BOLD}{hl7_count}{RESET}")
    step(f"FHIR resources:  {BOLD}{fhir_count}{RESET}")
    step(f"Successfully routed: {BOLD}{routed}/{total}{RESET}")

    print(f"\n{'='*70}")
    print(f"{BOLD}{GREEN}  ✓ Healthcare pipeline demo complete.{RESET}")
    print(f"{'='*70}")
    print(f"\n  {DIM}Swagger:  {BASE}/docs")
    print(f"  Audit:   GET {BASE}/api/audit")
    print(f"  HL7:     POST {BASE}/api/adapter/hl7")
    print(f"  FHIR:    POST {BASE}/api/adapter/fhir")
    print(f"  Sub:     POST {BASE}/api/adapter/fhir/subscription{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Trellis Healthcare Pipeline Demo")
    parser.add_argument("--server", action="store_true", help="Start Trellis server inline before running demo")
    parser.add_argument("--port", type=int, default=8100, help="Trellis server port (default: 8100)")
    args = parser.parse_args()

    global BASE
    BASE = f"http://localhost:{args.port}"

    print(f"""
{BOLD}{CYAN}
  ████████╗██████╗ ███████╗██╗     ██╗     ██╗███████╗
  ╚══██╔══╝██╔══██╗██╔════╝██║     ██║     ██║██╔════╝
     ██║   ██████╔╝█████╗  ██║     ██║     ██║███████╗
     ██║   ██╔══██╗██╔══╝  ██║     ██║     ██║╚════██║
     ██║   ██║  ██║███████╗███████╗███████╗██║███████║
     ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝╚══════╝
{RESET}
  {DIM}Enterprise AI Agent Orchestration Platform{RESET}
  {BOLD}Healthcare Pipeline Demo — HL7v2 & FHIR R4 Adapters{RESET}
""")

    server_proc = None
    if args.server:
        step("Starting Trellis server inline...")
        server_proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "trellis.main:app", "--port", str(args.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for server to be ready
        for i in range(30):
            if check_health():
                break
            time.sleep(0.5)
        else:
            fail("Trellis server failed to start within 15 seconds")

    try:
        if not check_health():
            fail(f"Trellis is not running at {BASE}. Start it with:\n"
                 f"      cd projects/trellis && uv run uvicorn trellis.main:app --port {args.port}\n"
                 f"    Or use: python examples/demo_healthcare_pipeline.py --server")

        step(f"Connected to Trellis at {BASE}")
        print()

        cleanup()
        register_agents()
        create_rules()

        all_results = []
        all_results.extend(send_hl7_messages())
        all_results.extend(send_fhir_resources())
        all_results.extend(send_fhir_subscription())

        show_audit_trail(all_results)
        show_summary(all_results)

    finally:
        if server_proc:
            server_proc.terminate()
            server_proc.wait(timeout=5)
            info("Trellis server stopped.")


if __name__ == "__main__":
    main()
