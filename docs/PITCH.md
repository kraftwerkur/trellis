# Trellis — Enterprise AI Agent Orchestration

**Executive Briefing | Acme Health**
**Prepared by:** Eric O'Brien, SVP Enterprise Technology
**Date:** February 2026

---

## The Problem

Every department wants AI agents. HR has one. Revenue Cycle is building one. IT wants a help desk bot. Clinical teams are exploring Epic-integrated copilots. Supply Chain sees automation opportunities everywhere.

This is shadow AI — the new shadow IT.

Without a platform, each agent is a standalone project: its own LLM subscription, its own deployment, its own security review, its own cost center buried in someone's Azure bill. There is no central registry of what agents exist. No audit trail of what they do. No way to answer the question every regulator, board member, and CFO will eventually ask: **"How many AI agents do we have, what are they accessing, and what are they costing us?"**

The trajectory is predictable. We've seen it with SaaS sprawl, with RPA, with cloud migration. Organic growth without governance produces fragmentation, risk, and cost overruns. The only question is whether we build the control plane now — while we have three agents — or later, when we have thirty and the cleanup is a multi-quarter initiative.

---

## The Solution

**Trellis is a self-hosted, framework-agnostic platform that deploys, routes, governs, and tracks every AI agent in the enterprise.**

Think of it as Kubernetes for AI agents. Kubernetes doesn't care if your container runs Java or Python — it manages the lifecycle, networking, and resource limits. Trellis doesn't care if your agent runs on Pi SDK, LangChain, OpenAI Assistants, or a vendor black box. It manages the routing, cost tracking, audit trail, and governance.

**One platform. One dashboard. One audit trail. Every agent.**

Key design principles:

- **Framework-agnostic.** Agents keep their autonomy — they own their logic, tools, and reasoning. Trellis provides the infrastructure around them.
- **Self-hosted.** Runs in our Azure environment, behind our firewalls, under our BAA. No data leaves our control.
- **Healthcare-native.** HL7/FHIR adapters, HIPAA-compliant audit retention, Epic integration path, PHI-aware tooling policies.
- **Governance by default.** Every agent is registered, every action is logged, every dollar is tracked — from day one, not as an afterthought.

---

## Why Now

**1. The Epic ecosystem is ready.** Azure Health Data Services supports FHIR subscriptions. Epic events — admissions, discharges, lab results, orders — can trigger AI agents in real time. The technical path from "Epic fires an event" to "an agent acts on it" is now straightforward. The missing piece is the orchestration layer.

**2. Regulatory pressure is building.** CMS, ONC, and state regulators are moving toward AI transparency requirements in healthcare. The organizations that can demonstrate a governed, auditable AI deployment model will have a material compliance advantage. The ones that can't will be scrambling.

**3. Cost explosion is a real risk.** A single agent running GPT-4o against moderate traffic can cost $2,000–$5,000/month in inference alone. Multiply by a dozen agents across departments with no budget caps and no visibility, and we're looking at six-figure annual LLM spend with no attribution. Trellis's LLM Gateway provides token-level cost tracking and budget enforcement from the first API call.

**4. Competitive pressure.** Health systems that operationalize AI agents across revenue cycle, clinical operations, and patient experience will see measurable efficiency gains. The question isn't whether to deploy agents — it's whether to deploy them with governance or without it.

---

## Architecture Overview

Trellis uses a clean three-layer architecture:

```
┌─────────────────────────────────────────────────────┐
│  LAYER 1: ADAPTERS                                  │
│  Teams · HTTP · HL7/FHIR · Email · Queue · Cron     │
│  ↓ Convert any input into a Generic Envelope ↓      │
├─────────────────────────────────────────────────────┤
│  LAYER 2: PLATFORM CORE                             │
│  Event Router · Rules Engine · Agent Registry        │
│  Tool Registry · FinOps Engine · Audit Log           │
├─────────────────────────────────────────────────────┤
│  LAYER 3: AGENTS                                    │
│  SAM (HR) · IT Help Desk · Rev Cycle · Vendor X     │
│  Any framework — Pi SDK, LangChain, OpenAI, HTTP    │
│  ↕ All LLM calls route through Trellis Gateway ↕   │
└─────────────────────────────────────────────────────┘
```

**In business terms:**

- **Adapters** are the on-ramps. A Teams message, an Epic event, a scheduled job, an API call — they all enter the platform the same way. The platform team owns all adapters; departments don't touch them.
- **Platform Core** is the traffic controller. It decides which agent handles which request, enforces budget limits, and logs every action for compliance.
- **Agents** are the workers. They do the actual thinking — answering HR questions, processing claims, triaging IT tickets. Departments own their agents and can build them with whatever framework they choose. Trellis doesn't constrain their technology choices; it provides the guardrails.

The **LLM Gateway** is the critical infrastructure component. Agents call Trellis instead of calling OpenAI or Anthropic directly. Same API shape — agents don't even know they're going through a proxy. But the platform gets full cost visibility, model routing, and budget enforcement without touching agent logic.

---

## Agent Architecture — Three Tiers

Trellis doesn't force agents into one pattern. It supports three tiers of agent complexity, all managed the same way — same cost tracking, same PHI shield, same audit trail, same routing rules.

### Tier 1: Atomic Agents (Prompt Wrappers)
Single-function agents. A system prompt, an LLM call, a response. Fast, cheap, predictable.

**Examples:** "Summarize this radiology report." "Extract ICD-10 codes from this note." "Draft a patient appointment reminder." "Classify this ticket by department."

**Why they matter:** These are the building blocks. Each one does one thing well. They're simple enough that a department can define one in 15 minutes — just a system prompt and a model selection. Most enterprise AI use cases start here and many never need to go further.

### Tier 2: Tool-Calling Agents
Agents that orchestrate multiple steps and call tools. They reason about a problem, gather data, and produce structured output.

**Examples:** The Security Triage Agent receives a vulnerability alert, cross-references it against the organization's tech stack, checks CISA KEV status, calculates a composite risk score, and drafts a structured advisory with recommended actions and escalation paths. All without human intervention.

**Why they matter:** This is where agents start doing real work — not just generating text, but making decisions based on data. The tools are the differentiator. An agent that can query your actual tech stack, your actual ticket system, your actual clinical guidelines is fundamentally different from one that can only write prose about them.

### Tier 3: Workflow Agents
Chains of Tier 1 and Tier 2 agents orchestrated by routing rules. One event triggers multiple agents in sequence or parallel.

**Examples:** A new hire event triggers fan-out — SAM (HR agent) generates onboarding documentation while IT Help Desk provisions accounts and access. A critical vulnerability triggers Security Triage for risk assessment, then routes the advisory to the appropriate response team based on the score.

**Why they matter:** This is where the platform pays for itself. Individual agents are useful. Orchestrated agents are transformative. The routing rules and fan-out capabilities turn isolated automations into end-to-end workflows — without anyone writing integration code.

**The key insight:** Start with prompt wrappers. Graduate to tool-calling when you need it. Orchestrate workflows when you're ready. The control plane manages them all the same way. Departments don't have to choose an architecture upfront — they can evolve their agents as their use cases mature.

### Framework-Agnostic by Design

Trellis is the control plane, not the agent runtime. It doesn't build agents — it governs them. Any agent framework can plug in:

- **Pi SDK** agents via RPC
- **Qwen-Agent** via their protocol
- **OpenClaw** sessions
- **LangChain / CrewAI** via HTTP webhooks
- **Simple LLM wrappers** through the Trellis Gateway
- **Custom Python agents** for built-in capabilities

Each framework is just a **dispatch adapter** — a thin layer that translates between Trellis envelopes and the agent's native interface. Trellis owns everything around the agent: the envelope pipeline (intake, classification, routing), the LLM gateway (cost tracking, model routing, budget enforcement), and the governance layer (audit trail, PHI detection, compliance). The agent runtime is a black box.

This matters because the agent framework space is dynamic. New frameworks emerge monthly. Today's best choice may be obsolete in a year. By keeping the dispatch adapter thin, swapping one agent runtime for another is a configuration change — not a rewrite. **Trellis's value is the envelope and the gateway, not any particular agent implementation.**

We build agents to prove value and deliver results. We just don't marry the runtime.

---

## Key Capabilities

### LLM Gateway → Cost Control
Every LLM call from every agent flows through a single gateway. Token-level cost tracking is automatic — no self-reporting, no trust required. **Business outcome:** Complete visibility into AI inference spend, attributed by agent, department, and individual request.

### FinOps Engine → Budget Enforcement
Per-agent and per-department budget caps with alerts at 80% and hard stops at 100%. Cost anomaly detection flags unexpected spikes. Smart model routing automatically selects the cheapest model capable of handling each request — routing 80% of simple queries to low-cost models while reserving premium models for complex reasoning. **Business outcome:** AI spend stays within approved budgets. No surprise invoices.

### Rules Engine → Intelligent Routing
Configurable rules determine which agent handles which request. Rules are data, not code — editable through the dashboard, testable before deployment. Supports fan-out (one event triggers multiple agents) and priority-based matching. **Business outcome:** New agents come online by adding a routing rule, not by rewiring infrastructure.

### Audit Trail → Compliance Readiness
Every envelope received, every routing decision, every tool call, every LLM inference — logged immutably with full trace chains. HIPAA-compliant retention (6+ years). PHI redaction in prompt logs. **Business outcome:** When a regulator asks "what did your AI agent do with this patient's data?" — you have the answer in seconds.

### Dashboard → Executive Visibility
Real-time operational dashboard showing agent health, event flow, cost metrics, and audit queries. Designed for both platform operators and executive stakeholders. **Business outcome:** One screen that answers "how many agents, what are they doing, what are they costing."

---

## Healthcare-Native

Trellis isn't a generic AI platform adapted for healthcare. It was designed for a health system from day one.

- **HL7/FHIR Adapters.** Epic fires an ADT event (admission, discharge, transfer). The FHIR adapter converts it into a Trellis envelope. The rules engine routes it to the appropriate agent. The agent acts before a human reviews the alert. This is the killer integration — real-time clinical event response.
- **HIPAA Audit Trail.** Append-only, immutable audit logs with 6+ year retention. PHI redacted from LLM prompt logs. Access controls enforced at every layer.
- **Epic Integration Path.** Azure Health Data Services → FHIR Subscriptions → Trellis adapter. No custom Epic APIs required. Standard FHIR R4.
- **PHI-Aware Tool Governance.** Tools that access protected health information are flagged in the registry, require CISO review before activation, and run in isolated containers with restricted network egress.
- **Clinical Workflow Awareness.** Agents can be scoped by department, facility, and clinical context. Maturity levels (shadow → assisted → autonomous) provide a governed promotion path for clinical use cases where trust must be earned incrementally.

---

## Competitive Landscape

| Capability | **Trellis** | LangSmith | Vertex AI Agent Builder | Azure AI Studio |
|---|---|---|---|---|
| **Self-hosted** | ✅ Runs in your infra | ❌ SaaS only | ❌ GCP only | ⚠️ Azure only |
| **Framework-agnostic** | ✅ Any framework | ❌ LangChain ecosystem | ❌ Google SDKs | ⚠️ Azure SDKs preferred |
| **LLM cost governance** | ✅ Gateway + budgets + anomaly detection | ⚠️ Observability only | ❌ | ⚠️ Basic monitoring |
| **Healthcare adapters** | ✅ HL7/FHIR native | ❌ | ❌ | ❌ |
| **Audit trail (HIPAA)** | ✅ Immutable, 6yr retention | ❌ | ❌ | ⚠️ Generic logging |
| **Multi-agent routing** | ✅ Rules engine + fan-out | ❌ | ⚠️ Limited | ⚠️ Limited |

**The gap:** Existing platforms are either observability tools (they watch agents but don't govern them), cloud-locked (they only work within one provider's ecosystem), or framework-locked (they only support agents built with their SDK). None are self-hosted, framework-agnostic, and healthcare-native. Trellis occupies that intersection.

---

## Deployment Model

**Today:** Docker Compose. One command (`docker compose up`) launches the full stack — API server, dashboard, and SQLite database. Runs on any machine with Docker.

**Tomorrow:** Azure Container Apps. Each agent and adapter runs in its own container with managed identity, network isolation, and resource limits. PostgreSQL replaces SQLite. Azure AD provides authentication. Application Insights provides telemetry.

**Key point:** Trellis can run in Acme Health's existing Azure infrastructure. No new cloud subscriptions, no vendor dependencies, no SaaS contracts. It's software we own and operate.

---

## Roadmap

### Built (Slices 1–6) — Complete

| Slice | What It Delivers |
|---|---|
| **Platform Core** | Event router, agent registry, HTTP adapter, envelope handling |
| **LLM Gateway** | OpenAI-compatible proxy, multi-provider support, token tracking, budget caps |
| **Agent Onboarding** | Four agent types, auto-key provisioning, health checks, manifest sync |
| **Rules Engine + Audit** | Advanced condition matching, fan-out routing, immutable audit trail |
| **FinOps Engine** | Cost rollups, anomaly detection, smart model routing, executive summary |
| **Dashboard** | Next.js ops dashboard with real-time monitoring and cost visualization |

**104 tests passing.** Working Docker deployment. API documentation complete.

### Next (Slices 7+)

| Priority | Deliverable | Timeline | Dependency |
|---|---|---|---|
| **1** | Teams Adapter (Bot Framework) | 2–3 weeks | Azure Bot registration, Teams admin approval |
| **2** | HL7/FHIR Adapter (Epic events) | 2–3 weeks | Azure Health Data Services access |
| **3** | Azure Container Apps deployment | 2–3 weeks | Azure dev subscription |
| **4** | Agent-to-agent delegation | 2 weeks | — |
| **5** | RBAC + Azure AD integration | 2 weeks | Azure AD app registration |

---

## The Ask

To move Trellis from working prototype to pilot deployment, we need:

1. **Azure dev subscription** — A resource group with permissions to deploy Container Apps, Azure Database for PostgreSQL, and Azure Health Data Services. Estimated cost: <$500/month during development.

2. **Teams bot registration** — Admin consent to register a Teams bot for the first adapter. This is what makes agents accessible to end users via chat.

3. **Pilot scope definition** — Agreement on the first 2–3 agents and departments for the pilot. Recommendation: SAM (HR — already built), IT Help Desk (high volume, low PHI risk), and one clinical use case via Epic FHIR integration.

4. **Architecture review session** — 60 minutes with infrastructure and security teams to validate the deployment model, network topology, and identity approach.

The platform core is built and tested. The path from here to a live pilot is weeks, not months.

---

*Full architecture documentation: [ARCHITECTURE.md](../ARCHITECTURE.md) · API reference: [API.md](../API.md) · Source: [projects/trellis/](../)*
