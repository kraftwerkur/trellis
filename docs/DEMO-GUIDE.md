# Trellis — Executive Demo Guide

**Audience:** CIO/CTO-level technical executives
**Platform:** Trellis — Enterprise AI Agent Orchestration
**Tagline:** *"Kubernetes for AI agents — deploy, route, govern, and track costs for every AI agent in the enterprise."*

---

## Table of Contents

- [5-Minute Elevator Demo](#5-minute-elevator-demo)
- [20-Minute Deep Dive](#20-minute-deep-dive)
  - [Act 1: Setup & Platform Overview](#act-1-setup--platform-overview)
  - [Act 2: The Patient Journey](#act-2-the-patient-journey)
  - [Act 3: PHI Shield — Compliance by Default](#act-3-phi-shield--compliance-by-default)
  - [Act 4: FinOps — Every Dollar Tracked](#act-4-finops--every-dollar-tracked)
  - [Act 5: Dashboard — The Command Center](#act-5-dashboard--the-command-center)
  - [Act 6: Azure — Production Ready](#act-6-azure--production-ready)
- [Act 7: Intelligent Routing — Self-Organizing Agents](#act-7-intelligent-routing--self-organizing-agents)
  - [Act 8: LLM Observatory — Model Intelligence](#act-8-llm-observatory--model-intelligence)
  - [Act 9: Health Auditor & Platform Housekeeping](#act-9-health-auditor--platform-housekeeping)
- [Appendix: Setup Instructions](#appendix-setup-instructions)

---

## 5-Minute Elevator Demo

> **Presenter notes:** This version hits the three things leadership cares about: *visibility, compliance, and cost control.* No setup — start with everything running.

### Talking Points (with commands)

**1. "We have no idea how many AI agents we're running, what they cost, or what data they touch."** *(20 sec)*

```bash
# Show all registered agents — every AI agent in the enterprise, one registry
curl -s http://localhost:8100/api/agents | python3 -m json.tool
```

> *"Trellis gives us a single registry. Every agent — whether it's SAM in HR, a revenue cycle bot, or a vendor black-box — is registered, health-checked, and auditable. One dashboard for the entire enterprise."*

**2. "Watch a clinical event flow through the system in real time."** *(90 sec)*

```bash
# Simulate an Epic ADT^A01 — patient admitted to Holmes Regional ICU
curl -s -X POST http://localhost:8100/api/adapter/hl7 \
  -H "Content-Type: text/plain" \
  -d 'MSH|^~\&|EPIC|HOLMESREGIONAL|TRELLIS|HF|20260301120000||ADT^A01|MSG10001|P|2.5
PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F
PV1||I|ICU^301^A|||||||||||||||VN-20260301-001' | python3 -m json.tool
```

> *"Elena Martinez was just admitted to the ICU at Holmes Regional. That HL7 message from Epic hit Trellis, got converted to a standard envelope, the rules engine matched it to the bed management agent, and the agent responded — before the admitting clerk closed their Epic screen. Full audit trail."*

```bash
# Show the audit trail for this event
curl -s "http://localhost:8100/api/audit?limit=5" | python3 -m json.tool
```

**3. "PHI never leaves our perimeter."** *(60 sec)*

```bash
# PHI Shield — test with real-looking clinical data
curl -s -X POST http://localhost:8100/api/phi/detect \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient Elena Martinez (MRN-78432, SSN 123-45-6789) admitted to ICU 301-A with hyperglycemia. Contact: 321-555-0142, elena.martinez@email.com"}' | python3 -m json.tool
```

> *"Six PHI elements detected and tokenized. The LLM never sees the SSN, never sees the MRN. After processing, tokens get rehydrated back. HIPAA compliance is automatic — not a policy document, not a hope, but code."*

**4. "Every token, every dollar, every agent."** *(60 sec)*

```bash
# FinOps executive summary
curl -s http://localhost:8100/api/finops/summary | python3 -m json.tool
```

> *"SAM cost $47 this month. The bed management agent cost $12. Department-level rollups, per-query costs, budget caps with automatic throttling. No surprises on the Azure bill."*

[SCREENSHOT: Dashboard overview — agent health tiles, cost chart, recent activity feed]

**5. "Agents route themselves — no manual rules needed."** *(30 sec)*

```bash
# Intelligent routing scores every agent for every envelope
curl -s http://localhost:8100/api/health/detailed | python3 -m json.tool
```

> *"Agents declare what they handle — categories, source types, keywords. The platform scores every envelope against every agent across 5 dimensions. A feedback loop learns from outcomes. When we go from 5 agents to 50, we don't need 200 routing rules. And 7 infrastructure health checks run every 15 minutes — the platform maintains itself."*

> *"One platform. Every agent registered, every PHI element shielded, every dollar tracked, every route scored. That's Trellis."*

---

## 20-Minute Deep Dive

### Act 1: Setup & Platform Overview
*(3 minutes)*

#### Start Trellis

**Option A — Docker (recommended for demo):**
```bash
cd ~/projects/trellis
docker compose up -d --build
# API:       http://localhost:8000
# Dashboard: http://localhost:3000
```

**Option B — Direct:**
```bash
cd ~/projects/trellis
uv sync
uv run alembic upgrade head
uv run -m trellis.main
# API:       http://localhost:8100
# Swagger:   http://localhost:8100/docs
```

> **Note:** All commands below use port 8100 (direct). For Docker, substitute port 8000.

#### Verify health

```bash
curl -s http://localhost:8100/health | python3 -m json.tool
```

**Expected output:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "database": "connected"
}
```

[SCREENSHOT: Swagger UI at /docs showing all available endpoints]

#### Architecture in 60 seconds

> *"Three layers. **Adapters** translate any input — Teams messages, HL7 feeds from Epic, FHIR APIs, file drops — into a standard envelope. **Platform Core** routes that envelope via rules, tracks costs, and logs everything. **Agents** do the actual work, using any framework they want. The critical piece: agents call our LLM Gateway instead of OpenAI directly, so we get full cost visibility without touching their code."*

[SCREENSHOT: Architecture diagram from ARCHITECTURE.md — three-layer Mermaid diagram]

---

### Act 2: The Patient Journey
*(8 minutes)*

> **The story:** Elena Martinez, 60, arrives at Holmes Regional with hyperglycemia and altered mental status. We'll follow her journey — admission, lab orders, results, and discharge — through Trellis, showing how each clinical event triggers the right agent automatically.

#### Step 1: Register Healthcare Agents

```bash
# Bed Management Agent — handles patient flow
curl -s -X POST http://localhost:8100/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "bed-manager",
    "name": "Bed Manager — Patient Flow Agent",
    "owner": "Nancy Rivera, Director Patient Flow",
    "department": "Patient Flow",
    "framework": "pi-sdk",
    "agent_type": "function",
    "function_ref": "echo",
    "channels": ["hl7", "fhir", "api"],
    "maturity": "assisted",
    "cost_mode": "managed"
  }' | python3 -m json.tool

# Lab Processor Agent — handles results and critical values
curl -s -X POST http://localhost:8100/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "lab-processor",
    "name": "Lab Processor — Results Agent",
    "owner": "Dr. Rachel Kim, Lab Director",
    "department": "Laboratory",
    "framework": "pi-sdk",
    "agent_type": "function",
    "function_ref": "echo",
    "channels": ["hl7", "fhir", "api"],
    "maturity": "assisted",
    "cost_mode": "managed"
  }' | python3 -m json.tool

# Discharge Coordinator Agent
curl -s -X POST http://localhost:8100/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "discharge-coord",
    "name": "Discharge Coordinator Agent",
    "owner": "Care Management",
    "department": "Care Management",
    "framework": "pi-sdk",
    "agent_type": "function",
    "function_ref": "echo",
    "channels": ["hl7", "fhir", "api"],
    "maturity": "assisted",
    "cost_mode": "managed"
  }' | python3 -m json.tool
```

**Expected output** (per agent):
```json
{
  "agent_id": "bed-manager",
  "name": "Bed Manager — Patient Flow Agent",
  "status": "registered",
  "api_key": "trl_abc123..."
}
```

> *"Three agents registered in 30 seconds. Each gets its own API key, its own identity, its own budget. The bed manager can't access lab systems. The lab processor can't discharge patients. Least-privilege, enforced by the platform."*

#### Step 2: Create Routing Rules

```bash
# ADT messages → Bed Manager
curl -s -X POST http://localhost:8100/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ADT messages → Bed Manager",
    "priority": 100,
    "conditions": {"routing_hints.tags": {"$contains": "adt"}},
    "actions": {"route_to": "bed-manager"}
  }' | python3 -m json.tool

# Lab results → Lab Processor
curl -s -X POST http://localhost:8100/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Lab results → Lab Processor",
    "priority": 100,
    "conditions": {"routing_hints.tags": {"$contains": "result"}},
    "actions": {"route_to": "lab-processor"}
  }' | python3 -m json.tool

# Discharge events → Discharge Coordinator
curl -s -X POST http://localhost:8100/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Discharge events → Discharge Coordinator",
    "priority": 100,
    "conditions": {"routing_hints.tags": {"$contains": "discharge"}},
    "actions": {"route_to": "discharge-coord"}
  }' | python3 -m json.tool
```

> *"Rules are data, not code. No developer needed to change routing. The rules engine supports complex conditions — regex, contains, comparisons — and it's all editable from the dashboard. Your department admins can manage their own routing."*

[SCREENSHOT: Dashboard Rules page — showing the three rules with conditions displayed as human-readable text]

#### Step 3: Admit — Elena Arrives at Holmes Regional

```bash
# Epic fires an ADT^A01 — patient admission
curl -s -X POST http://localhost:8100/api/adapter/hl7 \
  -H "Content-Type: text/plain" \
  -d 'MSH|^~\&|EPIC|HOLMESREGIONAL|TRELLIS|HF|20260301120000||ADT^A01|MSG10001|P|2.5
PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F
PV1||I|ICU^301^A|||||||||||||||VN-20260301-001' | python3 -m json.tool
```

**Expected output:**
```json
{
  "status": "routed",
  "target_agent": "bed-manager",
  "matched_rule": "ADT messages → Bed Manager",
  "trace_id": "a1b2c3d4-...",
  "envelope_id": "e5f6g7h8-..."
}
```

> 💡 **Health First value:** *"Before the admitting clerk closes their Epic screen, Trellis has already notified the bed manager agent. It checks ICU capacity, flags any isolation requirements, and alerts the charge nurse — automatically. No manual page, no phone call, no delay."*

#### Step 4: Lab Order — BMP Ordered

```bash
# Simulate via FHIR — a lab order as an Observation resource
curl -s -X POST http://localhost:8100/api/adapter/fhir \
  -H "Content-Type: application/json" \
  -d '{
    "resourceType": "Observation",
    "id": "obs-bmp-20260301",
    "status": "final",
    "code": {"coding": [{"system": "http://loinc.org", "code": "2345-7", "display": "Glucose"}]},
    "subject": {"reference": "Patient/pat-hf-78432", "display": "Elena Martinez"},
    "effectiveDateTime": "2026-03-01T13:00:00-05:00",
    "valueQuantity": {"value": 142, "unit": "mg/dL"}
  }' | python3 -m json.tool
```

**Expected output:**
```json
{
  "status": "routed",
  "target_agent": "lab-processor",
  "matched_rule": "Lab results → Lab Processor"
}
```

> 💡 **Health First value:** *"The same patient, different protocol (FHIR instead of HL7), different agent — but the same platform, the same audit trail, the same trace ID linking everything together. Epic fires HL7v2 for ADT, FHIR R4 for results. Trellis handles both."*

#### Step 5: Lab Results — Critical Value

```bash
# HL7 ORU^R01 — lab results with a high glucose value
curl -s -X POST http://localhost:8100/api/adapter/hl7 \
  -H "Content-Type: text/plain" \
  -d 'MSH|^~\&|BEAKER|HOLMESREGIONAL|EPIC|HF|20260301130000||ORU^R01|MSG10002|P|2.5
PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F
OBR|1|ORD-5521||BMP^Basic Metabolic Panel
OBX|1|NM|GLU^Glucose||142|mg/dL|70-100|H
OBX|2|NM|CREAT^Creatinine||1.1|mg/dL|0.7-1.3|N
OBX|3|NM|BUN^Blood Urea Nitrogen||18|mg/dL|7-20|N' | python3 -m json.tool
```

> 💡 **Health First value:** *"Glucose 142, flagged high. The lab processor agent can trigger critical value notifications, check if orders have been acknowledged, and escalate if thresholds are breached — all following your clinical protocols, coded as rules in the platform."*

#### Step 6: Discharge — Elena Goes Home

```bash
# ADT^A03 — patient discharge
curl -s -X POST http://localhost:8100/api/adapter/hl7 \
  -H "Content-Type: text/plain" \
  -d 'MSH|^~\&|EPIC|HOLMESREGIONAL|TRELLIS|HF|20260301180000||ADT^A03|MSG10004|P|2.5
PID|||MRN-78432^^^HF||MARTINEZ^ELENA||19651214|F
PV1||I|ICU^301^A|||||||||||||||VN-20260301-001' | python3 -m json.tool
```

**Expected output:**
```json
{
  "status": "routed",
  "target_agent": "discharge-coord",
  "matched_rule": "Discharge events → Discharge Coordinator"
}
```

> 💡 **Health First value:** *"Discharge triggers the coordinator agent — follow-up appointment scheduling, medication reconciliation reminders, patient education materials. The readmission clock starts ticking; the agent ensures nothing falls through the cracks."*

#### Step 7: Full Audit Trail

```bash
# Every event for Elena's journey — linked by trace
curl -s "http://localhost:8100/api/audit?limit=20" | python3 -m json.tool
```

> *"Four clinical events, three different agents, two protocols (HL7 and FHIR), one audit trail. Every decision — which rule matched, which agent responded, what it cost — is logged, immutable, and queryable. Six years of retention, per HIPAA. This is what survives an audit."*

[SCREENSHOT: Dashboard Audit page — showing the trace chain for Elena's journey with timestamps]

---

### Act 3: PHI Shield — Compliance by Default
*(3 minutes)*

> *"Every AI agent in the enterprise is a potential PHI leak. Trellis prevents that at the infrastructure layer."*

#### Detect PHI in Clinical Text

```bash
curl -s -X POST http://localhost:8100/api/phi/detect \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Patient Elena Martinez (MRN-78432, DOB: 12/14/1965, SSN 123-45-6789) was admitted to Holmes Regional ICU 301-A for hyperglycemia. Emergency contact: 321-555-0142. Email: elena.martinez@email.com. Attending: Dr. Patel (NPI 1234567890)."
  }' | python3 -m json.tool
```

**Expected output:**
```json
{
  "detections": [
    {"type": "MRN", "text": "MRN-78432", "source": "regex", "score": 0.95},
    {"type": "DATE_OF_BIRTH", "text": "DOB: 12/14/1965", "source": "regex", "score": 0.95},
    {"type": "SSN", "text": "123-45-6789", "source": "regex", "score": 0.9},
    {"type": "PHONE", "text": "321-555-0142", "source": "regex", "score": 0.9},
    {"type": "EMAIL", "text": "elena.martinez@email.com", "source": "regex", "score": 0.9},
    {"type": "NPI", "text": "NPI 1234567890", "source": "regex", "score": 0.95}
  ],
  "redacted_text": "Patient Elena Martinez ([MRN_1], [DATE_OF_BIRTH_1], [SSN_1]) was admitted to Holmes Regional ICU 301-A for hyperglycemia. Emergency contact: [PHONE_1]. Email: [EMAIL_1]. Attending: Dr. Patel ([NPI_1])."
}
```

> *"Six types of PHI detected and tokenized. The LLM sees `[SSN_1]`, not `123-45-6789`. After the model responds, tokens are rehydrated back. Three modes per agent:"*
>
> - **`full`** — Redact before LLM, rehydrate after. Default for clinical agents.
> - **`redact_only`** — Redact, no rehydration. For analytics/summarization.
> - **`audit_only`** — Log detections but don't modify. For monitoring rollout.

[SCREENSHOT: Dashboard PHI Shield page — detection categories bar chart, per-agent breakdown, recent events feed]

> 💡 **Health First value:** *"PHI Shield covers all 18 HIPAA Safe Harbor identifiers plus healthcare-specific types (MRN, NPI, ICD-10, CPT codes). It uses regex for structured data and Presidio NLP for unstructured text (names, addresses). Kim Alkire's security team can set the mode per agent from the dashboard — no code changes."*

---

### Act 4: FinOps — Every Dollar Tracked
*(3 minutes)*

> *"AI costs are invisible until they're not. Trellis makes them visible from day one."*

#### Cost Summary

```bash
curl -s http://localhost:8100/api/finops/summary | python3 -m json.tool
```

**Expected output:**
```json
{
  "total_cost_usd": 0.042,
  "total_requests": 12,
  "by_agent": {
    "bed-manager": {"cost_usd": 0.018, "requests": 5},
    "lab-processor": {"cost_usd": 0.015, "requests": 4},
    "discharge-coord": {"cost_usd": 0.009, "requests": 3}
  },
  "by_department": {
    "Patient Flow": 0.018,
    "Laboratory": 0.015,
    "Care Management": 0.009
  },
  "anomalies": [],
  "budget_alerts": []
}
```

#### Per-Agent Cost Drill-Down

```bash
curl -s "http://localhost:8100/api/costs/by-agent?agent_id=bed-manager" | python3 -m json.tool
```

#### Smart Model Routing

```bash
# The gateway automatically routes to the cheapest capable model
# Simple query → GPT-4o-mini ($0.15/1M tokens)
# Complex reasoning → GPT-4o ($2.50/1M tokens)
# This saves 60-80% on inference costs without any agent code changes

curl -s -X POST http://localhost:8100/api/finops/classify \
  -H "Content-Type: application/json" \
  -d '{"text": "What is the PTO policy for new hires?"}' | python3 -m json.tool
```

**Expected output:**
```json
{
  "complexity": "simple",
  "recommended_model": "gpt-4o-mini",
  "estimated_cost_per_1k_tokens": 0.00015
}
```

> 💡 **Health First value:** *"Budget caps per agent. If the revenue cycle bot hits its monthly limit, it gets throttled — not killed. Alert at 80%, hard stop at 100%. Department-level rollups so Michael can see exactly what IT is spending vs. Clinical vs. Revenue Cycle. No Azure bill surprises."*

[SCREENSHOT: Dashboard FinOps page — cost trend chart, per-department breakdown, budget utilization bars]

---

### Act 5: Dashboard — The Command Center
*(2 minutes)*

Open the dashboard:
- **Docker:** http://localhost:3000
- **Direct:** Served via Next.js dev server (see setup)

[SCREENSHOT: Dashboard home page — dark theme, agent health tiles with green/yellow/red indicators]

#### Dashboard Tour

| Page | What It Shows | Why It Matters |
|------|---------------|----------------|
| **Agents** | Registry, health status, type, department | "How many agents do we have?" |
| **Rules** | Routing rules with CRUD, toggle, test | "How is work being distributed?" |
| **FinOps** | Cost charts, budgets, anomaly alerts | "What are we spending?" |
| **PHI Shield** | Detection stats, per-agent modes, recent events | "Are we compliant?" |
| **Audit** | Full event log, trace chains, search | "What happened and when?" |
| **Gateway** | LLM request log, model usage, latency | "How are models performing?" |

[SCREENSHOT: Rules CRUD page — creating a new rule with condition builder and agent dropdown]

[SCREENSHOT: FinOps charts — line chart showing cost over time, pie chart by department]

[SCREENSHOT: Audit trace view — tree visualization of a multi-agent event chain]

> *"This is what the CIO sees. Not a terminal, not a config file — a real-time ops dashboard. Dark ops aesthetic, Datadog-level visibility, healthcare-grade compliance. And the rules engine is editable right here — department admins can manage their own routing without a deployment."*

---

### Act 6: Azure — Production Ready
*(1 minute)*

#### Deployment Architecture

```
Azure Resource Group (rg-trellis)
├── Container Registry (Basic)        ~$5/mo
├── Container Apps Environment         Free tier
│   ├── trellis-api (0.5 vCPU/1GB)   Pay-per-use, scales to zero
│   └── trellis-dashboard             Pay-per-use, scales to zero
├── Log Analytics (Free <5GB/mo)       Free
└── Key Vault (secrets)                Negligible
                                       ─────────
                            Total: ~$5-10/mo at demo scale
```

#### Deploy

```bash
cd ~/projects/trellis/deploy
./deploy.sh setup    # Creates infra, builds images, deploys
./deploy.sh status   # Check what's running
```

#### Verify Live Deployment

```bash
# If deployed — replace with actual URL
TRELLIS_URL="https://trellis-api.<region>.azurecontainerapps.io"

curl -s "$TRELLIS_URL/health" | python3 -m json.tool
```

> 💡 **Health First value:** *"Runs in our Azure tenant, behind our VNet, with our managed identities. PHI never leaves our perimeter. Scales to zero when idle — $5/month at demo scale, production-grade when we need it. No vendor lock-in, no third-party BAA complexity."*

[SCREENSHOT: Azure Portal — Container Apps showing trellis-api running with green health indicator]

---

### Act 7: Intelligent Routing — Self-Organizing Agents
*(2 minutes)*

> *"Static rules don't scale past 20 agents. Intelligent routing lets agents declare what they handle — no manual rule creation."*

#### Agent Intake Declarations

```bash
# Register an agent with intake declaration — it declares what it handles
curl -s -X POST http://localhost:8100/api/routing/intake/bed-manager \
  -H "Content-Type: application/json" \
  -d '{
    "categories": ["clinical.admission", "clinical.transfer", "clinical.discharge"],
    "source_types": ["hl7", "fhir"],
    "keywords": ["adt", "bed", "icu", "transfer", "admit"],
    "systems": ["epic"],
    "priority_range": {"min": "normal", "max": "critical"}
  }' | python3 -m json.tool
```

#### Scored Routing in Action

```bash
# Score an envelope against all agents — 5 dimensions
curl -s -X POST http://localhost:8100/api/routing/score \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "hl7",
    "routing_hints": {"category": "clinical.admission", "tags": ["adt", "epic"]},
    "metadata": {"priority": "high"}
  }' | python3 -m json.tool
```

> *"Five scoring dimensions — category affinity, source type, keyword overlap, system match, priority alignment — weighted and configurable. Historical feedback adjusts weights over time. Shadow mode lets you run scored routing alongside rules to build confidence before switching."*

#### Overlap Detection

```bash
# Check for agent intake overlaps — find routing ambiguity
curl -s http://localhost:8100/api/routing/overlaps | python3 -m json.tool
```

> 💡 **Health First value:** *"When we go from 5 agents to 50, we don't need 200 routing rules. Each new agent declares its intake and starts routing correctly from day one. The feedback loop learns from outcomes — routing accuracy improves automatically."*

[SCREENSHOT: Dashboard Routing page — agent scores visualization, overlap warnings]

---

### Act 8: LLM Observatory — Model Intelligence
*(1 minute)*

> *"Which models are fast? Which are expensive? Which are failing? The observatory tracks every inference call."*

```bash
# Model performance overview
curl -s http://localhost:8100/api/observatory/models | python3 -m json.tool

# Detailed metrics for a specific model
curl -s http://localhost:8100/api/observatory/models/qwen3:8b/metrics | python3 -m json.tool

# Cross-model summary
curl -s http://localhost:8100/api/observatory/summary | python3 -m json.tool
```

> *"Latency percentiles, token efficiency, error rates, cost per request — broken down by model and by hour. When Azure OpenAI has a bad day, you see it here before your agents start failing."*

[SCREENSHOT: Dashboard Observatory page — model comparison charts, latency trends]

---

### Act 9: Health Auditor & Platform Housekeeping
*(1 minute)*

> *"Trellis manages your agents. But who manages Trellis? These platform agents do."*

```bash
# Quick health check — 7 infrastructure checks
curl -s http://localhost:8100/api/health/detailed | python3 -m json.tool

# Health history
curl -s http://localhost:8100/api/health/history | python3 -m json.tool

# Tool registry — what tools are available and who can use them
curl -s http://localhost:8100/api/tools | python3 -m json.tool
```

> *"Seven checks: agent health, database, background tasks, SMTP, system resources, and adapter status for HTTP, Teams, and FHIR. The Health Auditor runs every 15 minutes. The Rule Optimizer finds dead rules nightly. The Audit Compactor archives old events weekly. The platform maintains itself."*

| Housekeeping Agent | Schedule | Purpose |
|-------------------|----------|---------|
| **Health Auditor** | Every 15 min | Agent degradation detection, trend analysis |
| **Rule Optimizer** | Nightly | Dead rule cleanup, overlap detection, suggestions |
| **Cost Optimizer** | Daily | Model downgrade recommendations, cost trends |
| **Schema Drift Detector** | Inline + daily | Payload structure change monitoring |
| **Audit Compactor** | Weekly | Log rollup, cold storage archival |

[SCREENSHOT: Dashboard Health page — infrastructure check grid with status indicators]

---

## Key Differentiators for Health First

| Capability | Why It Matters Here |
|------------|-------------------|
| **HL7/FHIR Adapters** | Direct integration with Epic — our EMR since June 2025. ADT, ORM, ORU, SIU messages route automatically. |
| **PHI Shield** | HIPAA compliance enforced by infrastructure, not policy. Kim Alkire's team gets per-agent control. |
| **FinOps** | Michael Carr gets a single dashboard for all AI spend across departments. Budget caps prevent runaway costs. |
| **Rules Engine** | Department admins manage routing without code deployments. Clinical, HR, Revenue Cycle — each manages their own rules. |
| **Teams Adapter** | Agents are accessible where staff already work — Microsoft Teams. No new app to learn. |
| **Intelligent Routing** | Agents declare intake, platform scores and routes. No manual rules for new agents. Feedback loop learns from outcomes. |
| **LLM Observatory** | Model performance visibility — latency, errors, cost per request. Catch provider degradation before agents fail. |
| **Platform Housekeeping** | Self-maintaining — Health Auditor, Rule Optimizer, Cost Optimizer, Audit Compactor run autonomously. |
| **Tool Registry** | Centralized tool governance with permission policies. Agents get scoped tool access, every call logged. |
| **Framework Agnostic** | SAM (HR) runs natively. Next agent could be LangChain, OpenAI SDK, or a vendor black-box. All governed the same way. |
| **Self-Hosted** | Runs in our Azure tenant. No vendor data traversal. Our infrastructure, our audit trail, our control. |
| **$5-10/mo Demo** | Proves the concept at negligible cost. Scales to production without rearchitecting. |

---

## Closing Slide

> *"Today we have SAM in HR. Tomorrow we'll have agents in Revenue Cycle, Patient Flow, IT, Supply Chain, and Clinical. Trellis doesn't care what framework they use — it cares that every one of them is registered, auditable, compliant, and cost-tracked. One platform, one dashboard, one audit trail for every AI agent in the enterprise. That's what we're building."*

---

## Appendix: Setup Instructions

### Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Platform core |
| uv | Latest | Python package manager |
| Node.js | 18+ | Dashboard |
| Docker | Latest | Containerized demo |
| Ollama | Latest | Local LLM (optional) |

### Full Setup (Direct)

```bash
# 1. Clone
git clone https://github.com/kraftwerkur/trellis.git
cd trellis

# 2. Install Python dependencies
uv sync

# 3. Initialize database
uv run alembic upgrade head

# 4. Configure providers (optional)
cp .env.example .env
# Edit .env with your API keys

# 5. Start API server
uv run -m trellis.main
# → http://localhost:8100

# 6. Start Dashboard (separate terminal)
cd dashboard
npm install
npm run dev
# → http://localhost:3000
```

### Full Setup (Docker)

```bash
cd trellis
docker compose up -d --build
# API:       http://localhost:8000
# Dashboard: http://localhost:3000
```

### Run the Automated Demo

```bash
# Healthcare pipeline (HL7 + FHIR, full patient journey)
uv run python examples/demo_healthcare_pipeline.py --server

# Multi-agent demo (HR, IT, Revenue Cycle)
uv run python examples/demo_multi_agent.py

# Docker-based demo (starts stack + runs demo)
./examples/docker-demo.sh
```

### Cleanup

```bash
# Docker
docker compose down -v

# Direct — just stop the server (Ctrl+C) — SQLite is ephemeral
```

---

*Demo guide created for Health First leadership presentations.*
*Trellis — Enterprise AI Agent Orchestration Platform*
*Built by Eric O'Brien, SVP Enterprise Technology and Operations*
