#!/usr/bin/env python3
"""
Setup Real LLM Agents for Trellis
==================================
Replaces demo echo agents with 3 real LLM-powered agents:
  - Security Analyst (security-analyst)
  - Compliance Monitor (compliance-monitor)
  - News Digest (news-digest)

Creates routing rules to connect RSS feed categories to the right agent.

Usage:
    cd projects/trellis && uv run python examples/setup_real_agents.py
"""

import sys
import httpx

BASE = "http://127.0.0.1:8100"
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

DEMO_AGENTS = ["sam-hr", "it-help", "rev-cycle"]

AGENTS = [
    {
        "agent_id": "security-analyst",
        "name": "Security Analyst",
        "owner": "Security Operations",
        "department": "Security",
        "framework": "trellis-llm",
        "agent_type": "llm",
        "llm_config": {
            "system_prompt": (
                "You are a healthcare security analyst at a large hospital system. "
                "Our tech stack includes: "
                "Ivanti SM (ITSM), CrowdStrike (EDR), Sentinel/Defender (SIEM), "
                "SailPoint (IAM), Nutanix (infra), Arista (network), Epic (EMR), "
                "Azure (cloud). When given a security advisory or vulnerability, assess: "
                "1) Does this affect our stack? 2) Severity rating (Critical/High/Medium/Low) "
                "3) Recommended action. Be concise and direct."
            ),
            "model": "qwen3:8b",
            "temperature": 0.3,
            "max_tokens": 512,
        },
        "tools": [],
        "channels": ["api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "compliance-monitor",
        "name": "Compliance Monitor",
        "owner": "Compliance Office",
        "department": "Compliance",
        "framework": "trellis-llm",
        "agent_type": "llm",
        "llm_config": {
            "system_prompt": (
                "You are a HIPAA compliance analyst at a healthcare system. "
                "When given a breach report, analyze: "
                "1) Type of breach and data exposed "
                "2) Whether the breached entity could be in our vendor/supply chain "
                "3) Lessons learned for our organization "
                "4) Any regulatory action required. Be concise."
            ),
            "model": "qwen3:8b",
            "temperature": 0.3,
            "max_tokens": 512,
        },
        "tools": [],
        "channels": ["api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
    {
        "agent_id": "news-digest",
        "name": "News Digest",
        "owner": "Strategy & Innovation",
        "department": "Strategy",
        "framework": "trellis-llm",
        "agent_type": "llm",
        "llm_config": {
            "system_prompt": (
                "You are a healthcare IT intelligence analyst. When given a healthcare "
                "technology news article, provide: "
                "1) One-line summary "
                "2) Relevance tags (choose from: Epic, Security, AI/ML, Infrastructure, "
                "Patient Experience, Revenue Cycle, Regulatory, Workforce) "
                "3) Relevance to a mid-size hospital system (1-5 scale) "
                "4) Key takeaway. Be extremely concise — 4 lines max."
            ),
            "model": "qwen3:8b",
            "temperature": 0.3,
            "max_tokens": 256,
        },
        "tools": [],
        "channels": ["api"],
        "maturity": "assisted",
        "cost_mode": "managed",
    },
]

BUDGETS = {
    "security-analyst": {"daily": 5.00, "monthly": 100.00},
    "compliance-monitor": {"daily": 3.00, "monthly": 60.00},
    "news-digest": {"daily": 5.00, "monthly": 100.00},
}

RULES = [
    {
        "name": "Security Feed → Security Analyst",
        "priority": 100,
        "conditions": {"routing_hints.category": "security"},
        "actions": {"route_to": "security-analyst"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "Compliance Feed → Compliance Monitor",
        "priority": 100,
        "conditions": {"routing_hints.category": "compliance"},
        "actions": {"route_to": "compliance-monitor"},
        "active": True,
        "fan_out": False,
    },
    {
        "name": "News Feed → News Digest",
        "priority": 100,
        "conditions": {"routing_hints.category": "news"},
        "actions": {"route_to": "news-digest"},
        "active": True,
        "fan_out": False,
    },
]


def main():
    print(f"\n{BOLD}{CYAN}Trellis — Setting up Real LLM Agents{RESET}\n")

    with httpx.Client(timeout=30) as c:
        # Health check
        try:
            c.get(f"{BASE}/health").raise_for_status()
        except Exception:
            print(f"{RED}Trellis not running at {BASE}. Start it first.{RESET}")
            sys.exit(1)

        # 1. Delete demo agents
        print(f"{BOLD}1. Cleaning up demo agents...{RESET}")
        for aid in DEMO_AGENTS:
            r = c.delete(f"{BASE}/api/agents/{aid}")
            if r.status_code in (200, 204):
                print(f"  Deleted {aid}")
            elif r.status_code == 404:
                print(f"  {aid} not found (ok)")

        # Also delete our agents if re-running
        for agent in AGENTS:
            c.delete(f"{BASE}/api/agents/{agent['agent_id']}")

        # 2. Register agents
        print(f"\n{BOLD}2. Registering LLM agents...{RESET}")
        for agent in AGENTS:
            r = c.post(f"{BASE}/api/agents", json=agent)
            if r.status_code == 201:
                data = r.json()
                print(f"  {GREEN}✓{RESET} {data['name']} ({data['agent_id']}) — {data['department']}")
            else:
                print(f"  {RED}✗{RESET} {agent['agent_id']}: {r.status_code} {r.text[:100]}")

        # 3. Budget caps
        print(f"\n{BOLD}3. Setting up budget caps...{RESET}")
        for agent_id, budget in BUDGETS.items():
            r = c.post(f"{BASE}/api/keys", json={
                "agent_id": agent_id,
                "name": f"{agent_id}-key",
                "budget_daily_usd": budget["daily"],
                "budget_monthly_usd": budget["monthly"],
                "default_model": "qwen3:8b",
            })
            if r.status_code == 201:
                print(f"  {GREEN}✓{RESET} {agent_id}: ${budget['daily']}/day, ${budget['monthly']}/mo")
            else:
                print(f"  {YELLOW}⚠{RESET} {agent_id}: {r.status_code}")

        # 4. Delete demo rules
        print(f"\n{BOLD}4. Cleaning up demo rules...{RESET}")
        r = c.get(f"{BASE}/api/rules")
        if r.status_code == 200:
            demo_rule_names = {
                "HR policy questions → SAM",
                "IT access & password issues → IT-Help",
                "Claim denials → Rev-Cycle",
                "Critical IT incidents → IT-Help (escalated)",
                "New hire onboarding → SAM + IT-Help (fan-out)",
            }
            # Also delete our rules if re-running
            our_rule_names = {rule["name"] for rule in RULES}
            for rule in r.json():
                if rule["name"] in demo_rule_names or rule["name"] in our_rule_names:
                    c.delete(f"{BASE}/api/rules/{rule['id']}")
                    print(f"  Deleted rule: {rule['name']}")

        # 5. Create routing rules
        print(f"\n{BOLD}5. Creating routing rules...{RESET}")
        for rule in RULES:
            r = c.post(f"{BASE}/api/rules", json=rule)
            if r.status_code == 201:
                data = r.json()
                print(f"  {GREEN}✓{RESET} {data['name']}")
            else:
                print(f"  {RED}✗{RESET} {rule['name']}: {r.status_code} {r.text[:100]}")

        # 6. Summary
        print(f"\n{BOLD}{'='*50}{RESET}")
        agents_r = c.get(f"{BASE}/api/agents")
        rules_r = c.get(f"{BASE}/api/rules")
        agents_list = agents_r.json() if agents_r.status_code == 200 else []
        rules_list = rules_r.json() if rules_r.status_code == 200 else []

        print(f"{GREEN}{BOLD}Setup complete!{RESET}")
        print(f"  Agents: {len(agents_list)}")
        for a in agents_list:
            print(f"    - {a['agent_id']} ({a['department']}) [{a['agent_type']}]")
        print(f"  Rules: {len(rules_list)}")
        for r in rules_list:
            active = "●" if r["active"] else "○"
            print(f"    - {active} {r['name']}")
        print(f"\n  Test: curl -X POST {BASE}/api/adapter/http -H 'Content-Type: application/json' \\")
        print(f'    -d \'{{"text": "CVE-2026-1281: Critical RCE in Ivanti EPMM", "sender_name": "rss-adapter", "metadata": {{"category": "security"}}}}\'')


if __name__ == "__main__":
    main()
