# Trellis Demo — Multi-Agent Healthcare Operations

This demo showcases Trellis managing three AI agents across a healthcare enterprise. It's designed for CIO-level demonstrations of the platform's orchestration, governance, and cost tracking capabilities.

## What It Does

1. **Registers 3 agents** with distinct configurations:
   - **SAM** (HR) — PTO, benefits, onboarding. Tools: PeopleSoft, UKG, email. $200/mo budget.
   - **IT-Help** (IT) — Password resets, provisioning, incidents. Tools: AD, Ivanti, VPN. $300/mo budget.
   - **Rev-Cycle** (Revenue Cycle) — Claim denials, appeals, coding. Tools: Epic Claims, payer portals. $500/mo budget.

2. **Creates routing rules** that direct work automatically:
   - HR policy questions → SAM
   - IT access issues → IT-Help
   - Claim denials → Rev-Cycle
   - Critical IT incidents → IT-Help (priority escalation)
   - New hire onboarding → SAM + IT-Help (fan-out)

3. **Sends 5 real healthcare scenarios** through the event router and shows how each gets matched, dispatched, and audited.

4. **Displays the audit trail** — every routing decision, every dispatch, every result logged.

5. **Shows FinOps data** — cost per agent, per department, executive summary.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Trellis project dependencies installed

## Running the Demo

### 1. Start Trellis

```bash
cd /path/to/projects/trellis
uv run uvicorn trellis.main:app --port 8100
```

### 2. Run the Demo

In another terminal:

```bash
cd /path/to/projects/trellis
uv run python examples/demo_multi_agent.py
```

### 3. Explore

After the demo runs, explore the API:

- **Swagger UI:** http://localhost:8100/docs
- **Agents:** `GET http://localhost:8100/api/agents`
- **Audit log:** `GET http://localhost:8100/api/audit`
- **Cost summary:** `GET http://localhost:8100/api/finops/summary`
- **Rules:** `GET http://localhost:8100/api/rules`

## Healthcare Pipeline Demo (HL7v2 & FHIR R4)

The `demo_healthcare_pipeline.py` script showcases Trellis ingesting clinical messages from HL7v2 interfaces and FHIR R4 APIs, routing them to specialized healthcare agents.

### What It Does

1. **Registers 3 clinical agents:** Bed Manager (patient flow), Lab Processor (results), Scheduler (appointments)
2. **Creates 6 routing rules** mapping HL7 message types and FHIR resource types to agents
3. **Sends HL7v2 messages:** ADT^A01 (admission), ORU^R01 (lab results), SIU^S12 (scheduling)
4. **Sends FHIR resources:** Patient, Encounter, Observation (vital signs)
5. **Processes a FHIR Subscription notification** (Epic-style real-time ADT webhook)
6. **Shows full audit trail** and routing summary

### Running

```bash
# Option 1: Start Trellis separately
uv run uvicorn trellis.main:app --port 8100
uv run python examples/demo_healthcare_pipeline.py

# Option 2: Start server inline
uv run python examples/demo_healthcare_pipeline.py --server
```

---

## Files

| File | Description |
|------|-------------|
| `demo_multi_agent.py` | Multi-agent demo — HR, IT, Revenue Cycle agents with routing and FinOps |
| `demo_healthcare_pipeline.py` | Healthcare pipeline demo — HL7v2 & FHIR R4 adapter ingestion and routing |
| `demo_envelopes.json` | 5 sample envelopes representing real healthcare scenarios |
| `README.md` | This file |

## Sample Envelopes

The `demo_envelopes.json` file contains:

1. **PTO Policy Inquiry** — Nurse asking about accrual rules → SAM
2. **Password Reset** — Finance manager locked out of PeopleSoft → IT-Help
3. **Claim Denial Appeal** — $14,250 cardiac cath bundling denial → Rev-Cycle
4. **After-Hours IT Emergency** — Epic connection pool exhausted in the ED → IT-Help (critical)
5. **New Hire Onboarding** — Physician starting, needs Epic + AD + badge → SAM + IT-Help (fan-out)

## What This Proves

- **One platform, many agents** — Different frameworks, departments, and maturity levels, all governed centrally.
- **Intelligent routing** — Rules route work without human intervention. Priority escalation for critical events.
- **Fan-out** — One event triggers multiple agents when cross-department coordination is needed.
- **Full audit trail** — Every decision traceable. HIPAA-ready.
- **Cost governance** — Per-agent budgets, per-department rollups, executive dashboards.
- **Framework agnostic** — Agents can be Pi SDK, LangChain, OpenAI Assistants, or raw HTTP. The platform doesn't care.
