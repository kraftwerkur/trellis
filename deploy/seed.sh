#!/bin/bash
# Seed Trellis with the 3 demo agents, routing rules, and test envelopes
# Run from anywhere — just needs curl

set -uo pipefail

BASE="${TRELLIS_URL:-http://localhost:8000}"

echo "Seeding Trellis at: $BASE"
echo ""

# --- Health Check ---
echo "=== Health Check ==="
curl -sf "$BASE/health" | python3 -m json.tool 2>/dev/null || echo '{"status":"healthy"}'
echo ""

# --- Register Agents ---
echo "=== Registering Agents ==="

echo "  → SAM — HR Operations Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "sam-hr",
  "name": "SAM — HR Operations Agent",
  "owner": "HR Team",
  "department": "HR",
  "framework": "trellis-native",
  "agent_type": "llm",
  "system_prompt": "You are SAM (Strategic Automated Manager), an HR operations agent. You handle HR cases including benefits, payroll, PTO, onboarding, compliance, and employee relations.\\n\\nYour process:\\n1. Parse the HR case: extract description, affected employees, any category hints\\n2. Classify the case using classify_hr_case\\n3. Assess priority using assess_hr_priority\\n4. Look up applicable HR policy using lookup_hr_policy\\n5. Assign to the correct team:\\n   - benefits → Benefits Admin\\n   - payroll → Payroll\\n   - pto → HR Generalist\\n   - onboarding → Talent Acquisition\\n   - offboarding → HR Generalist\\n   - compliance → Compliance\\n   - workers_comp/fmla/ada → Employee Relations\\n6. Flag for escalation if regulatory flags exist OR priority is CRITICAL\\n\\nOutput structured triage with category, priority, assigned team, policy reference, and escalation info.",
  "tools": ["classify_hr_case", "assess_hr_priority", "lookup_hr_policy"],
  "channels": ["teams", "api", "email"],
  "maturity": "assisted",
  "cost_mode": "managed",
  "llm_config": {"model": "meta/llama-3.3-70b-instruct", "provider": "nvidia", "temperature": 0.3, "max_tokens": 2048}
}'

echo "  → IT Help Desk Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "it-help",
  "name": "IT Help Desk Agent",
  "owner": "IT Operations",
  "department": "IT",
  "framework": "trellis-native",
  "agent_type": "llm",
  "system_prompt": "You are an IT Help Desk triage agent. You receive IT incident reports and produce structured triage output.\\n\\nYour process:\\n1. Parse the ticket: extract description, severity, affected users\\n2. Classify the ticket using classify_ticket\\n3. Identify affected systems using lookup_tech_stack for relevant keywords\\n4. Assess priority using assess_priority\\n5. Look up known resolutions using lookup_known_resolution\\n6. Assign to the correct team:\\n   - network → Network Ops\\n   - application → App Support\\n   - endpoint → Desktop Support\\n   - access → IAM\\n   - infrastructure → Infrastructure\\n7. Flag for escalation if priority is CRITICAL or HIGH\\n\\nOutput a structured triage result with category, priority, assigned team, known resolution, and escalation status.",
  "tools": ["classify_ticket", "lookup_tech_stack", "assess_priority", "lookup_known_resolution"],
  "channels": ["teams", "api", "phone"],
  "maturity": "assisted",
  "cost_mode": "managed",
  "llm_config": {"model": "meta/llama-3.3-70b-instruct", "provider": "nvidia", "temperature": 0.4, "max_tokens": 2048}
}'

echo "  → Revenue Cycle Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "rev-cycle",
  "name": "Revenue Cycle Agent",
  "owner": "Revenue Cycle Team",
  "department": "Revenue Cycle",
  "framework": "trellis-native",
  "agent_type": "llm",
  "system_prompt": "You are a Revenue Cycle Management agent. You handle claim denials, billing inquiries, coding issues, AR management, and compliance reviews.\\n\\nYour process:\\n1. Parse the case: extract description, payer, amount, days aged\\n2. Classify using classify_rev_cycle_case\\n3. If denial codes are detected, analyze using analyze_denial\\n4. Check timely filing risk (Medicare: 365d, BCBS/UHC: 180d, Aetna/Cigna: 120d, default: 90d)\\n5. Assess priority using assess_rev_cycle_priority\\n6. If timely filing at risk and priority is LOW/MEDIUM, elevate to HIGH\\n7. Assign to sub-team:\\n   - denial_appeal → Denials\\n   - coding_review → Coding\\n   - billing_inquiry → Patient Billing\\n   - ar_followup → AR\\n   - compliance → Compliance\\n\\nOutput structured triage with denial analysis, timely filing alerts, and team assignment.",
  "tools": ["classify_rev_cycle_case", "analyze_denial", "assess_rev_cycle_priority"],
  "channels": ["api"],
  "maturity": "shadow",
  "cost_mode": "managed",
  "llm_config": {"model": "qwen/qwen3-235b-a22b", "provider": "nvidia", "temperature": 0.2, "max_tokens": 4096}
}'

echo "  → Security Triage Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "security-triage",
  "name": "Security Triage Agent",
  "owner": "Security Team",
  "department": "Information Security",
  "framework": "trellis-native",
  "agent_type": "llm",
  "system_prompt": "You are a Security Triage Agent. You analyze security vulnerabilities and produce risk assessments.\\n\\nYour process:\\n1. Extract CVE IDs from the input\\n2. Check each CVE against the CISA Known Exploited Vulnerabilities catalog using check_cisa_kev\\n3. Look up affected systems in the organization tech stack using lookup_tech_stack\\n4. Calculate a composite risk score using calculate_risk_score\\n5. Write a concise risk assessment including:\\n   - Summary of the vulnerability\\n   - Whether it is in CISA KEV\\n   - Risk level: CRITICAL if any CVE is in KEV, HIGH if CVSS >= 7, MEDIUM otherwise, LOW if no CVEs found\\n   - Recommended immediate actions\\n\\nBe concise and actionable. Escalate critical findings immediately.",
  "tools": ["check_cisa_kev", "lookup_tech_stack", "get_cvss_details", "calculate_risk_score"],
  "channels": ["teams", "api"],
  "maturity": "assisted",
  "cost_mode": "managed",
  "llm_config": {
    "model": "meta/llama-3.3-70b-instruct",
    "provider": "nvidia",
    "temperature": 0.1,
    "max_tokens": 4096
  }
}'

echo ""

echo "  → Health Auditor Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "health-auditor",
  "name": "Health Auditor Agent",
  "owner": "Platform",
  "department": "platform",
  "framework": "trellis-native",
  "agent_type": "native",
  "tools": [],
  "channels": ["api"],
  "maturity": "autonomous",
  "cost_mode": "managed"
}'

echo "  → Audit Compactor Agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "platform-audit-compactor",
  "name": "Audit Compactor Agent",
  "owner": "Platform",
  "department": "platform",
  "framework": "trellis-native",
  "agent_type": "native",
  "tools": [],
  "channels": ["api"],
  "maturity": "autonomous",
  "cost_mode": "managed"
}'

echo "  → rule-optimizer agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "rule-optimizer",
  "name": "Rule Optimizer Agent",
  "owner": "Platform",
  "department": "platform",
  "framework": "trellis-native",
  "agent_type": "native",
  "tools": [],
  "channels": ["api"],
  "maturity": "autonomous",
  "cost_mode": "managed"
}'

echo "  → schema-drift-detector agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "schema-drift-detector",
  "name": "Schema Drift Detector",
  "owner": "Platform",
  "department": "platform",
  "framework": "trellis-native",
  "agent_type": "native",
  "tools": [],
  "channels": ["api"],
  "maturity": "autonomous",
  "cost_mode": "managed"
}'

echo "  → cost-optimizer agent"
curl -s -f -X POST "$BASE/api/agents" -H "Content-Type: application/json" -d '{
  "agent_id": "cost-optimizer",
  "name": "Cost Optimizer Agent",
  "owner": "Platform",
  "department": "platform",
  "framework": "trellis-native",
  "agent_type": "native",
  "tools": [],
  "channels": ["api"],
  "maturity": "autonomous",
  "cost_mode": "managed"
}'

echo ""

# --- Create Routing Rules ---
echo "=== Creating Routing Rules ==="

echo "  → HR policy → SAM"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "HR policy questions → SAM",
  "priority": 100,
  "conditions": {"routing_hints.department": "HR", "routing_hints.category": "policy"},
  "actions": {"route_to": "sam-hr"},
  "active": true,
  "fan_out": false
}'

echo "  → IT access → IT-Help"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "IT access & password issues → IT-Help",
  "priority": 100,
  "conditions": {"routing_hints.department": "IT", "routing_hints.category": "access"},
  "actions": {"route_to": "it-help"},
  "active": true,
  "fan_out": false
}'

echo "  → Claim denials → Rev-Cycle"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Claim denials → Rev-Cycle",
  "priority": 100,
  "conditions": {"routing_hints.department": "Revenue Cycle", "routing_hints.category": "denial-appeal"},
  "actions": {"route_to": "rev-cycle"},
  "active": true,
  "fan_out": false
}'

echo "  → Critical IT incidents (escalated)"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Critical IT incidents → IT-Help (escalated)",
  "priority": 50,
  "conditions": {"metadata.priority": "critical", "routing_hints.department": "IT", "routing_hints.category": "incident"},
  "actions": {"route_to": "it-help", "set_priority": "critical"},
  "active": true,
  "fan_out": false
}'

echo "  → New hire onboarding (fan-out → SAM + IT)"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "New hire onboarding → SAM + IT-Help (fan-out)",
  "priority": 90,
  "conditions": {"routing_hints.category": "onboarding", "routing_hints.tags": {"$contains": "it-provisioning"}},
  "actions": {"route_to": ["sam-hr", "it-help"]},
  "active": true,
  "fan_out": true
}'

echo ""

# --- Intake Feed Rules (match metadata.category from Intake sourcer) ---
echo "=== Creating Intake Feed Rules ==="

echo "  → Security feeds → Security Triage Agent"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Security feeds → Security Triage Agent",
  "priority": 80,
  "conditions": {"routing_hints.category": "security"},
  "actions": {"route_to": "security-triage"},
  "active": true
}'

echo "  → Health check requests → Health Auditor"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Health check requests → Health Auditor",
  "priority": 75,
  "conditions": {"routing_hints.category": "health-check"},
  "actions": {"route_to": "health-auditor"},
  "active": true
}'

echo "  → Rule optimization requests → Rule Optimizer"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Rule optimization requests → Rule Optimizer",
  "priority": 75,
  "conditions": {"routing_hints.category": "rule-optimization"},
  "actions": {"route_to": "rule-optimizer"},
  "active": true
}'

echo "  → Schema check requests → Schema Drift Detector"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Schema check requests → Schema Drift Detector",
  "priority": 75,
  "conditions": {"routing_hints.category": "schema-check"},
  "actions": {"route_to": "schema-drift-detector"},
  "active": true
}'

echo "  → Cost optimization requests → Cost Optimizer"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Cost optimization requests → Cost Optimizer",
  "priority": 75,
  "conditions": {"routing_hints.category": "cost-optimization"},
  "actions": {"route_to": "cost-optimizer"},
  "active": true
}'

echo "  → Healthcare news → IT-Help (awareness)"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Healthcare news → IT-Help (awareness)",
  "priority": 90,
  "conditions": {"routing_hints.category": "industry"},
  "actions": {"route_to": "it-help"},
  "active": true
}'

echo "  → Regulatory feeds → Rev-Cycle (compliance)"
curl -s -f -X POST "$BASE/api/rules" -H "Content-Type: application/json" -d '{
  "name": "Regulatory feeds → Rev-Cycle (compliance)",
  "priority": 90,
  "conditions": {"routing_hints.category": "regulatory"},
  "actions": {"route_to": "rev-cycle"},
  "active": true
}'

echo ""

# --- Send Test Envelopes ---
echo "=== Sending Test Envelopes ==="

echo "  → HR policy question"
curl -s -f -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "teams",
  "payload": {"text": "What is our PTO policy for new hires in their first year?"},
  "metadata": {"user": "sarah.jones@example.com", "channel": "teams", "priority": "normal"},
  "routing_hints": {"department": "HR", "category": "policy"}
}'

echo "  → IT password reset"
curl -s -f -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "teams",
  "payload": {"text": "I am locked out of my Epic account, need password reset ASAP"},
  "metadata": {"user": "dr.wilson@example.com", "channel": "teams", "priority": "high"},
  "routing_hints": {"department": "IT", "category": "access"}
}'

echo "  → Claim denial appeal"
curl -s -f -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "api",
  "payload": {"text": "Claim #HC-2026-44891 denied by UHC for medical necessity. Patient: hip replacement, 68yo. Need appeal letter."},
  "metadata": {"claim_id": "HC-2026-44891", "payer": "UnitedHealthcare", "priority": "normal"},
  "routing_hints": {"department": "Revenue Cycle", "category": "denial-appeal"}
}'

echo "  → Critical IT incident"
curl -s -f -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "monitoring",
  "payload": {"text": "CRITICAL: Epic Hyperspace connection pool exhausted at Main Campus. 47 clinicians affected."},
  "metadata": {"source": "logicmonitor", "priority": "critical", "facility": "Main Campus"},
  "routing_hints": {"department": "IT", "category": "incident"}
}'

echo "  → New hire onboarding (fan-out)"
curl -s -f -X POST "$BASE/api/events" -H "Content-Type: application/json" -d '{
  "source_type": "api",
  "payload": {"text": "New hire: Dr. Amanda Chen, Cardiology, starting March 15. Needs Epic access, AD account, badge, parking, HR orientation."},
  "metadata": {"hire_date": "2026-03-15", "department": "Cardiology", "priority": "normal"},
  "routing_hints": {"category": "onboarding", "tags": ["it-provisioning", "hr-orientation"]}
}'

echo ""
echo "=== Done! ==="
echo "Dashboard: $BASE"
echo ""
AGENT_COUNT=$(curl -sf "$BASE/api/agents" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
RULE_COUNT=$(curl -sf "$BASE/api/rules" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
echo "$AGENT_COUNT agents registered, $RULE_COUNT routing rules active."
echo "Refresh the dashboard to see everything."
