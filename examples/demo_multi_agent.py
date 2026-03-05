#!/usr/bin/env python3
"""
Trellis Multi-Agent Demo
========================
Showcases Trellis managing multiple AI agents across a healthcare enterprise.
Designed for CIO-level demonstrations.

Scenario: Three agents — HR (SAM), IT Helpdesk, and Revenue Cycle — each with
different configurations, budgets, and tool permissions. Routing rules
automatically direct work to the right agent. The platform tracks every
action, every token, every dollar.

Prerequisites:
    1. Trellis running: cd projects/trellis && uv run uvicorn trellis.main:app --port 8100
    2. Run this script: uv run python examples/demo_multi_agent.py

What it demonstrates:
    - Agent registration with distinct configs (model prefs, budgets, tools)
    - Intelligent routing rules (keyword + department matching)
    - Fan-out routing (one event → multiple agents)
    - Priority escalation via rules
    - Full audit trail per trace
    - Cost tracking and FinOps visibility
"""

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8100"
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
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


def error(text: str):
    print(f"    {RED}✗ {text}{RESET}")
    sys.exit(1)


def check_health(client: httpx.Client):
    """Verify Trellis is running."""
    try:
        r = client.get(f"{BASE}/health")
        r.raise_for_status()
        return True
    except (httpx.ConnectError, httpx.HTTPStatusError):
        return False


# ─── Agent Definitions ────────────────────────────────────────────────────────

AGENTS = [
    {
        "agent_id": "sam-hr",
        "name": "SAM — HR Operations Agent",
        "owner": "Jane Smith, VP Human Resources",
        "department": "HR",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["peoplesoft-lookup", "ukg-schedule", "benefits-lookup", "email-send"],
        "channels": ["teams", "api", "email"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "it-help",
        "name": "IT Help Desk Agent",
        "owner": "Mike Torres, Director IT Operations",
        "department": "IT",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["ad-password-reset", "ivanti-ticket", "vpn-provision", "epic-access"],
        "channels": ["teams", "api", "phone"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "rev-cycle",
        "name": "Revenue Cycle Agent",
        "owner": "Lisa Chen, Director Revenue Cycle",
        "department": "Revenue Cycle",
        "framework": "pi-sdk",
        "agent_type": "function",
        "function_ref": "echo",
        "tools": ["epic-claims", "payer-portal", "appeal-generator", "coding-lookup"],
        "channels": ["api"],
        "maturity": "shadow",
        "cost_mode": "managed",
    },
]

# Budget configurations per agent (applied via API keys)
AGENT_BUDGETS = {
    "sam-hr": {"daily": 10.00, "monthly": 200.00, "model": "qwen3:8b"},
    "it-help": {"daily": 15.00, "monthly": 300.00, "model": "qwen3:8b"},
    "rev-cycle": {"daily": 25.00, "monthly": 500.00, "model": "qwen3:8b"},
}

# ─── Routing Rules ────────────────────────────────────────────────────────────

RULES = [
    {
        "name": "HR policy questions → SAM",
        "priority": 100,
        "conditions": {
            "routing_hints.department": "HR",
            "routing_hints.category": "policy",
        },
        "actions": {"route_to": "sam-hr"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "IT access & password issues → IT-Help",
        "priority": 100,
        "conditions": {
            "routing_hints.department": "IT",
            "routing_hints.category": "access",
        },
        "actions": {"route_to": "it-help"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "Claim denials → Rev-Cycle",
        "priority": 100,
        "conditions": {
            "routing_hints.department": "Revenue Cycle",
            "routing_hints.category": "denial-appeal",
        },
        "actions": {"route_to": "rev-cycle"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "Critical IT incidents → IT-Help (escalated)",
        "priority": 50,  # Higher priority (lower number = evaluated first)
        "conditions": {
            "metadata.priority": "critical",
            "routing_hints.department": "IT",
            "routing_hints.category": "incident",
        },
        "actions": {"route_to": "it-help", "set_priority": "critical"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "New hire onboarding → SAM + IT-Help (fan-out)",
        "priority": 90,
        "conditions": {
            "routing_hints.category": "onboarding",
            "routing_hints.tags": {"$contains": "it-provisioning"},
        },
        "actions": {"route_to": ["sam-hr", "it-help"]},
        "active": True,
        "fan_out": True,
    },
]


def cleanup(client: httpx.Client):
    """Remove demo agents and rules from previous runs."""
    for agent in AGENTS:
        client.delete(f"{BASE}/api/agents/{agent['agent_id']}")
    # Clean rules by listing and deleting demo ones
    r = client.get(f"{BASE}/api/rules")
    if r.status_code == 200:
        for rule in r.json():
            if rule["name"] in [r["name"] for r in RULES]:
                client.delete(f"{BASE}/api/rules/{rule['id']}")


def register_agents(client: httpx.Client) -> dict[str, str]:
    """Register all demo agents and return their API keys."""
    header("1. AGENT REGISTRATION")
    print("  Registering three agents across HR, IT, and Revenue Cycle.")
    print("  Each agent gets its own identity, tools, budget, and API key.\n")

    api_keys = {}
    for agent_def in AGENTS:
        r = client.post(f"{BASE}/api/agents", json=agent_def)
        if r.status_code == 201:
            data = r.json()
            api_keys[agent_def["agent_id"]] = data.get("api_key", "")
            step(f"{BOLD}{data['name']}{RESET}")
            info(f"ID: {data['agent_id']}  |  Dept: {data['department']}  |  Maturity: {data['maturity']}")
            info(f"Tools: {', '.join(data['tools'])}")
            info(f"API Key: {data.get('api_key', 'N/A')[:16]}...")
        elif r.status_code == 409:
            warn(f"{agent_def['agent_id']} already registered (skipping)")
        else:
            error(f"Failed to register {agent_def['agent_id']}: {r.status_code} {r.text}")
    return api_keys


def create_api_keys(client: httpx.Client, existing_keys: dict[str, str]):
    """Create API keys with budget caps for each agent."""
    header("2. BUDGET & API KEY CONFIGURATION")
    print("  Each agent gets a Trellis API key with daily/monthly budget caps.")
    print("  The LLM Gateway enforces these — no agent can overspend.\n")

    for agent_id, budget in AGENT_BUDGETS.items():
        r = client.post(f"{BASE}/api/keys", json={
            "agent_id": agent_id,
            "name": f"{agent_id}-demo-key",
            "budget_daily_usd": budget["daily"],
            "budget_monthly_usd": budget["monthly"],
            "default_model": budget["model"],
        })
        if r.status_code == 201:
            data = r.json()
            step(f"{BOLD}{agent_id}{RESET}  →  ${budget['daily']}/day, ${budget['monthly']}/mo")
            info(f"Default model: {budget['model']}  |  Key: {data['key'][:16]}...")
        else:
            warn(f"Key creation for {agent_id}: {r.status_code} (may already exist)")


def create_rules(client: httpx.Client):
    """Create routing rules."""
    header("3. ROUTING RULES")
    print("  Rules determine which agent handles each request.")
    print("  Priority 50 = evaluated first. Fan-out sends to multiple agents.\n")

    for rule_def in RULES:
        r = client.post(f"{BASE}/api/rules", json=rule_def)
        if r.status_code == 201:
            data = r.json()
            fan = " [FAN-OUT]" if data.get("fan_out") else ""
            step(f"Rule #{data['id']}: {BOLD}{data['name']}{RESET}{fan}")
            info(f"Priority: {data['priority']}  |  Conditions: {json.dumps(data['conditions'], separators=(',', ':'))}")
        else:
            warn(f"Rule '{rule_def['name']}': {r.status_code}")


def send_envelopes(client: httpx.Client):
    """Load and send demo envelopes, showing routing results."""
    header("4. LIVE EVENT ROUTING")
    print("  Sending 5 real healthcare scenarios through the event router.")
    print("  Watch each envelope get matched to the right agent.\n")

    envelope_path = Path(__file__).parent / "demo_envelopes.json"
    envelopes = json.loads(envelope_path.read_text())

    trace_ids = []
    for i, item in enumerate(envelopes, 1):
        print(f"  {CYAN}━━━ Scenario {i}: {item['name']} ━━━{RESET}")
        info(item["description"])

        r = client.post(f"{BASE}/api/envelopes", json=item["envelope"])
        if r.status_code == 200:
            data = r.json()
            status = data.get("status", "unknown")
            agent = data.get("target_agent", "none")
            rule = data.get("matched_rule", "none")
            trace = data.get("trace_id") or item["envelope"].get("metadata", {}).get("trace_id")

            # For fan-out, results may be a list
            if isinstance(data.get("results"), list):
                step(f"Status: {GREEN}{status}{RESET}  |  Rule: {rule}")
                for result in data["results"]:
                    info(f"  → Agent: {BOLD}{result.get('agent_id', '?')}{RESET}")
            else:
                step(f"Status: {GREEN}{status}{RESET}  |  Agent: {BOLD}{agent}{RESET}  |  Rule: {rule}")

            if trace:
                trace_ids.append(trace)
                info(f"Trace: {trace}")
        else:
            warn(f"Envelope dispatch: {r.status_code} — {r.text[:100]}")
        print()

    return trace_ids


def show_audit_trail(client: httpx.Client, trace_ids: list[str]):
    """Query and display the audit trail."""
    header("5. AUDIT TRAIL")
    print("  Every action is logged — routing decisions, dispatches, errors.")
    print("  HIPAA-ready: immutable, traceable, queryable.\n")

    r = client.get(f"{BASE}/api/audit", params={"limit": 25})
    if r.status_code == 200:
        events = r.json()
        step(f"Total audit events from this demo: {BOLD}{len(events)}{RESET}")
        print()

        # Group by type
        by_type: dict[str, int] = {}
        for evt in events:
            t = evt["event_type"]
            by_type[t] = by_type.get(t, 0) + 1

        for event_type, count in sorted(by_type.items()):
            info(f"{event_type}: {count} events")

        # Show a sample trace
        if trace_ids:
            print()
            step("Sample trace chain:")
            tr = client.get(f"{BASE}/api/audit/trace/{trace_ids[0]}")
            if tr.status_code == 200:
                for evt in tr.json():
                    info(f"  [{evt['event_type']}] agent={evt.get('agent_id', '-')} | {evt['timestamp']}")


def show_cost_summary(client: httpx.Client):
    """Display cost tracking and FinOps data."""
    header("6. FINOPS & COST TRACKING")
    print("  Every token, every inference call, every tool invocation — tracked.")
    print("  Per-agent, per-department, per-trace cost attribution.\n")

    # Per-agent costs
    r = client.get(f"{BASE}/api/costs/summary")
    if r.status_code == 200:
        summaries = r.json()
        if summaries:
            step("Cost by Agent:")
            for s in summaries:
                info(f"  {s['agent_id']}: ${s['total_cost_usd']:.4f}  ({s['request_count']} requests, {s['total_tokens_in']+s['total_tokens_out']} tokens)")
        else:
            info("No cost data yet (agents used function dispatch, not LLM gateway)")

    # Department costs
    r = client.get(f"{BASE}/api/costs/by-department")
    if r.status_code == 200:
        depts = r.json()
        if depts:
            print()
            step("Cost by Department:")
            for d in depts:
                info(f"  {d['department']}: ${d['total_cost_usd']:.4f}")

    # FinOps executive summary
    r = client.get(f"{BASE}/api/finops/summary")
    if r.status_code == 200:
        fin = r.json()
        print()
        step("Executive Summary:")
        info(f"  Spend today:      ${fin.get('spend_today_usd', 0):.2f}")
        info(f"  Spend this week:  ${fin.get('spend_this_week_usd', 0):.2f}")
        info(f"  Spend this month: ${fin.get('spend_this_month_usd', 0):.2f}")
        info(f"  Total requests:   {fin.get('total_requests', 0)}")
        avg = fin.get('avg_cost_per_request_usd', 0)
        info(f"  Avg cost/request: ${avg:.4f}")


def show_platform_summary(client: httpx.Client):
    """Final summary of what's running on the platform."""
    header("7. PLATFORM STATUS")

    r = client.get(f"{BASE}/api/agents")
    agents = r.json() if r.status_code == 200 else []
    r = client.get(f"{BASE}/api/rules")
    rules = r.json() if r.status_code == 200 else []
    r = client.get(f"{BASE}/api/keys")
    keys = r.json() if r.status_code == 200 else []

    step(f"Registered Agents: {BOLD}{len(agents)}{RESET}")
    for a in agents:
        info(f"  {a['agent_id']}  |  {a['department']}  |  {a['maturity']}  |  {a['status']}")

    print()
    step(f"Active Rules: {BOLD}{len([r for r in rules if r['active']])}{RESET} of {len(rules)}")
    for r in rules:
        state = f"{GREEN}●{RESET}" if r["active"] else f"{RED}○{RESET}"
        info(f"  {state} [{r['priority']}] {r['name']}")

    print()
    step(f"API Keys: {BOLD}{len(keys)}{RESET}")

    print(f"\n{'='*70}")
    print(f"{BOLD}{GREEN}  ✓ Demo complete. Trellis is managing {len(agents)} agents.{RESET}")
    print(f"{'='*70}")
    print(f"\n  {DIM}Dashboard: http://localhost:3000")
    print(f"  Swagger:  http://localhost:8100/docs")
    print(f"  Audit:    GET /api/audit")
    print(f"  Costs:    GET /api/finops/summary{RESET}\n")


def main():
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
  {DIM}Multi-Agent Demo — Healthcare Operations{RESET}
""")

    with httpx.Client(timeout=30) as client:
        # Pre-flight
        if not check_health(client):
            error("Trellis is not running. Start it with:\n"
                  "      cd projects/trellis && uv run uvicorn trellis.main:app --port 8100")

        step(f"Connected to Trellis at {BASE}")
        print()

        # Clean slate
        cleanup(client)

        # Run demo sequence
        api_keys = register_agents(client)
        create_api_keys(client, api_keys)
        create_rules(client)
        trace_ids = send_envelopes(client)
        show_audit_trail(client, trace_ids)
        show_cost_summary(client)
        show_platform_summary(client)


if __name__ == "__main__":
    main()
