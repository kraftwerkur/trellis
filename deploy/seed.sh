#!/bin/bash
# Seed Trellis with the 3 demo agents, routing rules, and test envelopes
# Run from anywhere — just needs curl

set -uo pipefail

BASE="${TRELLIS_URL:-https://trellis-api.lemonglacier-3bef39e2.eastus2.azurecontainerapps.io}"

echo "Seeding Trellis at: $BASE"
echo ""

# --- Health Check ---
echo "=== Health Check ==="
curl -sf "$BASE/health" | python3 -m json.tool 2>/dev/null || echo '{"status":"healthy"}'
echo ""

# --- Register Agents ---
echo "=== Registering Agents ==="

echo "  → SAM — HR Operations Agent"
curl -sf -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
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
  "llm_config": {"model": "meta/llama-3.3-70b-instruct", "provider": "nvidia", "temperature": 0.3, "max_tokens": 2048}
}' -o /dev/null

echo "  → IT Help Desk Agent"
curl -sf -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
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
  "llm_config": {"model": "meta/llama-3.3-70b-instruct", "provider": "nvidia", "temperature": 0.4, "max_tokens": 2048}
}' -o /dev/null

echo "  → Revenue Cycle Agent"
curl -sf -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
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
  "llm_config": {"model": "qwen/qwen3-235b-a22b", "provider": "nvidia", "temperature": 0.2, "max_tokens": 4096}
}' -o /dev/null

echo ""

# --- Create Routing Rules ---
echo "=== Creating Routing Rules ==="

echo "  → HR policy → SAM"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "HR policy questions → SAM",
  "priority": 100,
  "conditions": {"routing_hints.department": "HR", "routing_hints.category": "policy"},
  "actions": {"route_to": "sam-hr"},
  "active": true,
  "fan_out": false
}' -o /dev/null

echo "  → IT access → IT-Help"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "IT access & password issues → IT-Help",
  "priority": 100,
  "conditions": {"routing_hints.department": "IT", "routing_hints.category": "access"},
  "actions": {"route_to": "it-help"},
  "active": true,
  "fan_out": false
}' -o /dev/null

echo "  → Claim denials → Rev-Cycle"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Claim denials → Rev-Cycle",
  "priority": 100,
  "conditions": {"routing_hints.department": "Revenue Cycle", "routing_hints.category": "denial-appeal"},
  "actions": {"route_to": "rev-cycle"},
  "active": true,
  "fan_out": false
}' -o /dev/null

echo "  → Critical IT incidents (escalated)"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Critical IT incidents → IT-Help (escalated)",
  "priority": 50,
  "conditions": {"metadata.priority": "critical", "routing_hints.department": "IT", "routing_hints.category": "incident"},
  "actions": {"route_to": "it-help", "set_priority": "critical"},
  "active": true,
  "fan_out": false
}' -o /dev/null

echo "  → New hire onboarding (fan-out → SAM + IT)"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "New hire onboarding → SAM + IT-Help (fan-out)",
  "priority": 90,
  "conditions": {"routing_hints.category": "onboarding", "routing_hints.tags": {"$contains": "it-provisioning"}},
  "actions": {"route_to": ["sam-hr", "it-help"]},
  "active": true,
  "fan_out": true
}' -o /dev/null

echo ""

# --- Intake Feed Rules (match metadata.category from Intake sourcer) ---
echo "=== Creating Intake Feed Rules ==="

echo "  → Security feeds → SAM (triage)"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Security feeds → SAM-HR (security triage)",
  "priority": 80,
  "conditions": {"routing_hints.category": "security"},
  "actions": {"route_to": "sam-hr"},
  "active": true
}' -o /dev/null

echo "  → Healthcare news → IT-Help (awareness)"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Healthcare news → IT-Help (awareness)",
  "priority": 90,
  "conditions": {"routing_hints.category": "industry"},
  "actions": {"route_to": "it-help"},
  "active": true
}' -o /dev/null

echo "  → Regulatory feeds → Rev-Cycle (compliance)"
curl -sf -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Regulatory feeds → Rev-Cycle (compliance)",
  "priority": 90,
  "conditions": {"routing_hints.category": "regulatory"},
  "actions": {"route_to": "rev-cycle"},
  "active": true
}' -o /dev/null

echo ""

# --- Send Test Envelopes ---
echo "=== Sending Test Envelopes ==="

echo "  → HR policy question"
curl -sf -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "teams",
  "payload": {"text": "What is our PTO policy for new hires in their first year?"},
  "metadata": {"user": "sarah.jones@healthfirst.org", "channel": "teams", "priority": "normal"},
  "routing_hints": {"department": "HR", "category": "policy"}
}' -o /dev/null

echo "  → IT password reset"
curl -sf -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "teams",
  "payload": {"text": "I am locked out of my Epic account, need password reset ASAP"},
  "metadata": {"user": "dr.wilson@healthfirst.org", "channel": "teams", "priority": "high"},
  "routing_hints": {"department": "IT", "category": "access"}
}' -o /dev/null

echo "  → Claim denial appeal"
curl -sf -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "api",
  "payload": {"text": "Claim #HC-2026-44891 denied by UHC for medical necessity. Patient: hip replacement, 68yo. Need appeal letter."},
  "metadata": {"claim_id": "HC-2026-44891", "payer": "UnitedHealthcare", "priority": "normal"},
  "routing_hints": {"department": "Revenue Cycle", "category": "denial-appeal"}
}' -o /dev/null

echo "  → Critical IT incident"
curl -sf -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "monitoring",
  "payload": {"text": "CRITICAL: Epic Hyperspace connection pool exhausted at Holmes Regional. 47 clinicians affected."},
  "metadata": {"source": "logicmonitor", "priority": "critical", "facility": "Holmes Regional"},
  "routing_hints": {"department": "IT", "category": "incident"}
}' -o /dev/null

echo "  → New hire onboarding (fan-out)"
curl -sf -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "api",
  "payload": {"text": "New hire: Dr. Amanda Chen, Cardiology, starting March 15. Needs Epic access, AD account, badge, parking, HR orientation."},
  "metadata": {"hire_date": "2026-03-15", "department": "Cardiology", "priority": "normal"},
  "routing_hints": {"category": "onboarding", "tags": ["it-provisioning", "hr-orientation"]}
}' -o /dev/null

echo ""
echo "=== Done! ==="
echo "Dashboard: $BASE"
echo ""
echo "3 agents registered, 5 routing rules active, 5 test events processed."
echo "Refresh the dashboard to see everything."
