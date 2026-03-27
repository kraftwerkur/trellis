# Trellis Agent Migration Manifest
## Date: 2026-03-27
## Purpose: Convert 9 native Python agents to LLM agent configs (system prompt + tool bindings)

---

## Tool Registry Summary

The `ToolRegistry` (trellis/tool_registry.py) provides centralized tool execution with:
- Permission checking (agent_tools list with wildcard `*` support)
- Audit logging (ToolCallLog persistence)
- Timing/latency tracking
- Error handling with graceful fallback

### Registered Tools (from `_register_builtin_tools`)

| Tool Name | Category | Description | Permissions |
|---|---|---|---|
| `lookup_tech_stack` | data | Check if product/vendor is in Health First's tech stack | tech_stack.read |
| `check_cisa_kev` | data | Check if CVE is in CISA KEV catalog | cisa_kev.read |
| `get_cvss_details` | data | Get CVSS score breakdown for a CVE | cvss.read |
| `calculate_risk_score` | assess | Calculate composite risk score for Health First | risk.assess |
| `classify_ticket` | classify | Classify IT ticket by category (keyword matching) | tickets.classify |
| `lookup_known_resolution` | lookup | Look up known resolution for common IT issues | resolutions.read |
| `assess_priority` | assess | Assess IT ticket priority (severity + impact) | tickets.assess |
| `classify_hr_case` | classify | Classify HR case by category | hr.classify |
| `assess_hr_priority` | assess | Assess HR case priority (category + regulatory flags) | hr.assess |
| `lookup_hr_policy` | lookup | Look up HR policy reference and procedure | hr.policy.read |
| `classify_rev_cycle_case` | classify | Classify revenue cycle case by category | revcycle.classify |
| `analyze_denial` | assess | Analyze denial code → root cause + resolution steps | revcycle.analyze |
| `assess_rev_cycle_priority` | assess | Assess revenue cycle case priority | revcycle.assess |

### Tool Schema for LLM (CISA KEV — only one currently defined as OpenAI function schema)

```json
{
  "type": "function",
  "function": {
    "name": "check_cisa_kev",
    "description": "Check if a CVE ID is in the CISA Known Exploited Vulnerabilities catalog",
    "parameters": {
      "type": "object",
      "properties": {"cve_id": {"type": "string", "description": "CVE identifier (e.g. CVE-2024-1234)"}},
      "required": ["cve_id"]
    }
  }
}
```

---

## Agent 1: SecurityTriageAgent

**File:** `trellis/agents/security_triage.py`
**Class:** `SecurityTriageAgent`
**Uses AgentLoop:** YES — this is the only agent that uses LLM reasoning
**Recommended agent_type:** `llm`

### System Prompt

```
You are a security triage analyst. You receive vulnerability reports and CISA KEV lookup results, then produce a concise risk assessment.

Given the CVE information and KEV lookup results provided, write a brief risk assessment that includes:
- Summary of the vulnerability
- Whether it is in the CISA Known Exploited Vulnerabilities catalog
- Risk level: CRITICAL if any CVE is in KEV, HIGH if CVSS >= 7 or description mentions active exploitation, MEDIUM otherwise, LOW if no CVEs found
- Recommended immediate actions

Be concise and actionable. Output plain text, not JSON.
```

### Tool Bindings

| Tool | Schema | Executor |
|---|---|---|
| `check_cisa_kev` | `CISA_KEV_SCHEMA` (OpenAI function format) | `check_cisa_kev()` from tools.py |

### Processing Flow (process method)

1. Extract text from envelope (handles Pydantic objects and dicts)
2. Extract CVE IDs via regex `CVE-\d{4}-\d{4,}` (unique, ordered)
3. Check each CVE against CISA KEV catalog (direct function call, not via AgentLoop)
4. Build context message with KEV lookup results
5. Create AgentLoop with system prompt, tools, max_steps=3, temperature=0.3
6. Run AgentLoop with context message
7. Determine risk_level from KEV results (hardcoded logic: no CVEs→LOW, any in KEV→CRITICAL, else→MEDIUM)
8. **Delegation:** If risk_level is CRITICAL and db+trace_id available, delegates to `it-help` agent via AgentContext
9. Return structured result with assessment text, CVE data, risk level

### Hardcoded Logic to Migrate

- **CVE regex extraction** (`CVE-\d{4}-\d{4,}`) — should become a tool or stay as pre-processing
- **Risk level determination** (lines 105-110) — duplicates what the LLM prompt asks for; the hardcoded version overrides LLM output. RECOMMENDATION: Let the LLM determine risk level via structured output, or keep as post-processing validation
- **KEV lookups before AgentLoop** — tools are called BEFORE the loop, then results are injected as context. The loop also has the tool available for additional lookups
- **Delegation to it-help** — cross-agent delegation for CRITICAL findings. This should become a tool or a routing rule

### AgentLoop Config

```python
model="default"
temperature=0.3
max_steps=3
```

### Migration Notes

- This is the ONLY agent that actually uses an LLM. All others are pure logic.
- The pre-processing (CVE extraction, KEV lookups) happens BEFORE the AgentLoop runs, then results are passed as context. This is a hybrid pattern.
- The delegation to it-help (lines 123-168) should be converted to a routing rule or a delegation tool.
- The `_extract_text` helper handles multiple envelope formats — this should be a shared utility.

---

## Agent 2: ITHelpAgent

**File:** `trellis/agents/it_help.py`
**Class:** `ITHelpAgent`
**Uses AgentLoop:** NO — pure deterministic logic
**Recommended agent_type:** `llm` with structured output instructions

### System Prompt (NEW — currently has none)

Recommended system prompt for LLM migration:

```
You are an IT help desk triage agent for Health First. You receive IT incident reports and produce structured triage output.

Your job:
1. Parse the ticket: extract ticket_id, description, severity, affected_users, category_hint
2. Classify the ticket using the classify_ticket tool
3. Identify affected systems using lookup_tech_stack for relevant keywords
4. Assess priority using assess_priority tool
5. Look up known resolutions using lookup_known_resolution tool
6. Assign to the correct team based on category:
   - network → Network Ops
   - application → App Support
   - endpoint → Desktop Support
   - access → IAM
   - infrastructure → Infrastructure
7. Flag for escalation if priority is CRITICAL or HIGH

Output a structured triage result.
```

### Tool Bindings

| Tool | Usage |
|---|---|
| `classify_ticket` | Classify ticket by category via keyword matching |
| `lookup_tech_stack` | Match description keywords against Health First tech stack |
| `assess_priority` | Assess priority from severity, affected_users, system_criticality |
| `lookup_known_resolution` | Find known resolution for category + keywords |

### Processing Flow

1. Parse envelope → extract payload (handles Pydantic + dict)
2. `_parse_ticket()` → extracts ticket_id, description, severity, affected_users, category_hint
3. `classify_ticket(description, category_hint)` → category, subcategory, keywords
4. `_identify_systems(description, keywords)` → iterates keywords + description words, calls `lookup_tech_stack(term)` for each, filters by match_confidence >= 0.6
5. Determine highest system_criticality from affected systems
6. `assess_priority(severity, affected_users, system_criticality)` → priority, justification
7. `lookup_known_resolution(category, keywords)` → resolution text or None
8. Map category → assigned_team via `_TEAM_MAP`
9. Set `requires_escalation = priority in ("CRITICAL", "HIGH")`
10. Build triage dict and return

### Hardcoded Logic to Migrate

- **Team mapping** (`_TEAM_MAP`) — should be in the system prompt or a lookup tool
- **Escalation logic** — priority threshold check, put in prompt
- **System identification loop** — iterates all keywords + description words through `lookup_tech_stack` with confidence filtering. This multi-step search pattern should become a tool instruction
- **Ticket parsing** — flexible field extraction from various payload shapes

### Migration Notes

- Currently pure logic, no LLM. Converting to LLM gives flexibility but may be slower.
- The `_identify_systems` method does N calls to `lookup_tech_stack` (one per keyword + description word). With LLM, the agent could call it selectively.
- Consider keeping as deterministic (`native` type) for speed, or converting to LLM for better classification accuracy.

---

## Agent 3: SAMHRAgent

**File:** `trellis/agents/sam_hr.py`
**Class:** `SAMHRAgent`
**Uses AgentLoop:** NO — pure deterministic logic
**Recommended agent_type:** `llm` with structured output instructions

### System Prompt (NEW — currently has none)

```
You are SAM-HR (Strategic Automated Manager for HR), an HR case triage agent for Health First.

Your job:
1. Parse the HR case: extract case_id, description, affected_employees, category_hint
2. Classify the case using classify_hr_case tool
3. Assess priority using assess_hr_priority tool
4. Look up applicable HR policy using lookup_hr_policy tool
5. Assign to the correct team:
   - benefits → Benefits Admin
   - payroll → Payroll
   - pto → HR Generalist
   - onboarding → Talent Acquisition
   - offboarding → HR Generalist
   - policy → HR Generalist
   - compliance → Compliance
   - workers_comp → Employee Relations
   - fmla → Employee Relations
   - ada → Employee Relations
6. Flag for escalation if regulatory flags exist OR priority is CRITICAL
7. If escalating, provide escalation_reason

Output structured triage with case_id, category, priority, assigned_team, regulatory_flags, SLA hours, policy reference, and escalation info.
```

### Tool Bindings

| Tool | Usage |
|---|---|
| `classify_hr_case` | Classify HR case by category via keyword matching |
| `assess_hr_priority` | Assess priority from category, regulatory flags, employee count |
| `lookup_hr_policy` | Look up HR policy reference and standard procedure |

### Processing Flow

1. Parse envelope → extract payload
2. `_parse_case()` → case_id, description, affected_employees, category_hint
3. `classify_hr_case(description, category_hint)` → category, subcategory, keywords, regulatory_flags
4. `assess_hr_priority(category, regulatory_flags, affected_employees)` → priority, sla_hours, justification
5. `lookup_hr_policy(category, keywords)` → policy_reference, standard_procedure
6. Map category → assigned_team via `_TEAM_MAP`
7. Set `requires_escalation = bool(regulatory_flags) or priority == "CRITICAL"`
8. Build escalation_reason if applicable
9. Return structured triage

### Hardcoded Logic to Migrate

- **Team mapping** (`_TEAM_MAP`) — put in system prompt
- **Escalation logic** — regulatory flags or CRITICAL priority triggers escalation
- **Escalation reason generation** — concatenates regulatory flag names

---

## Agent 4: RevCycleAgent

**File:** `trellis/agents/rev_cycle.py`
**Class:** `RevCycleAgent`
**Uses AgentLoop:** NO — pure deterministic logic
**Recommended agent_type:** `llm` with structured output instructions

### System Prompt (NEW — currently has none)

```
You are a Revenue Cycle Management triage agent for Health First. You handle claim denials, billing inquiries, coding issues, AR management, and compliance reviews.

Your job:
1. Parse the case: extract case_id, description, payer, amount, days_aged, category_hint
2. Classify using classify_rev_cycle_case tool
3. If denial codes are detected, analyze the primary denial using analyze_denial tool
4. Check timely filing risk based on payer filing limits:
   - Medicare/Medicaid: 365 days
   - BCBS/UHC: 180 days
   - Aetna/Cigna: 120 days
   - Default: 90 days
   Alert when >80% of window is used
5. Assess priority using assess_rev_cycle_priority tool
6. If timely filing is at risk and priority is LOW/MEDIUM, elevate to HIGH
7. Assign to sub-team:
   - denial_appeal → Denials
   - coding_review → Coding
   - billing_inquiry → Patient Billing
   - ar_followup → AR
   - compliance → Compliance
   - prior_auth → Prior Auth
   - credentialing → Credentialing
   - charge_capture → Coding
   - underpayment → Denials
   - bad_debt → Patient Billing

Output structured triage with timely filing alerts and denial analysis.
```

### Tool Bindings

| Tool | Usage |
|---|---|
| `classify_rev_cycle_case` | Classify rev cycle case by category + detect denial codes |
| `analyze_denial` | Analyze denial code → root cause, resolution steps, appeal template |
| `assess_rev_cycle_priority` | Assess priority from category, amount, aging, filing deadline |

### Processing Flow

1. Parse envelope → extract payload
2. `_parse_case()` → case_id, description, payer, amount, days_aged, category_hint
3. `classify_rev_cycle_case(description, category_hint)` → category, subcategory, keywords, denial_codes
4. If denial_codes: `analyze_denial(primary_code, payer, amount)` → denial analysis
5. Check timely filing: payer → filing_limit, calculate days remaining, alert if >80% used
6. `assess_rev_cycle_priority(category, amount, days_aged, filing_limit)` → priority, urgency, justification
7. Elevate priority if timely filing at risk and current priority is LOW/MEDIUM
8. Map category → assigned_team
9. Return structured triage with timely_filing_alert and denial_analysis

### Hardcoded Logic to Migrate

- **Payer timely filing limits** (`_TIMELY_FILING` dict) — should be in prompt or a lookup tool
- **Filing alert threshold** (80%) — put in prompt
- **Priority elevation** for timely filing risk — put in prompt instructions
- **Team mapping** (`_TEAM_MAP`) — put in prompt
- **Timely filing check** (`_check_timely_filing`) — complex logic, could become a tool

---

## Agent 5: HealthAuditorAgent

**File:** `trellis/agents/health_auditor.py`
**Class:** `HealthAuditorAgent`
**Uses AgentLoop:** NO — pure infrastructure monitoring logic
**Recommended agent_type:** `native` (keep as-is, NOT suitable for LLM)

### Why NOT to convert to LLM

This agent is fundamentally an infrastructure monitoring service, not a reasoning agent. It:
- Runs health checks against HTTP endpoints
- Checks database integrity via SQL
- Monitors background task heartbeats
- Checks SMTP connectivity
- Monitors system resources (disk, memory)
- Exposes FastAPI API endpoints (`/health`, `/health/detailed`, `/health/history`)
- Runs as a background loop every 60 seconds
- Stores results in `health_checks` DB table
- Fires alerts for failed checks

### Key Components

1. **Agent health checks** — HTTP GET to each agent's health_endpoint, tracks latency history, detects degradation (>3x rolling average)
2. **LLM provider checks** — pings `/models` endpoints
3. **Database checks** — PRAGMA integrity_check, row counts, file size, disk space
4. **Background task heartbeat monitoring** — tracks last execution time for health_auditor, audit_compactor, rule_optimizer, schema_drift, cost_optimizer
5. **SMTP check** — socket connect to SMTP relay
6. **System resources** — disk usage, memory (psutil)
7. **Adapter checks** — HTTP, Teams, FHIR endpoint connectivity
8. **API Router** — 3 endpoints mounted on the main app

### Processing Flow (when triggered as agent)

1. `run_all_checks()` — runs all checks concurrently
2. Persists results to `health_checks` table
3. Fires alerts for failed checks
4. Returns summary text + full report data

### Background Loop

```python
health_auditor_loop(interval=60)  # TRELLIS_HEALTH_CHECK_INTERVAL
```

### Migration Notes

- **DO NOT CONVERT TO LLM.** This is infrastructure code with HTTP clients, DB queries, socket operations, and FastAPI routes.
- The `HealthAuditorAgent.process()` wrapper is simple — it calls `run_all_checks()` and formats the result. This can remain a native agent.
- The API router (`health_auditor_router`) must stay as Python code.

---

## Agent 6: AuditCompactorAgent

**File:** `trellis/agents/audit_compactor.py`
**Class:** `AuditCompactorAgent`
**Uses AgentLoop:** NO — pure database housekeeping logic
**Recommended agent_type:** `native` (keep as-is, NOT suitable for LLM)

### Why NOT to convert to LLM

This agent performs database maintenance:
- Queries old audit events (older than RETENTION_DAYS)
- Groups by hour + event_type + agent_id
- Archives to gzipped JSONL files
- Creates summary rows in AuditSummary table
- Deletes archived rows
- Runs as background loop every 86400 seconds (daily)

### Processing Flow

1. Query AuditEvent rows older than cutoff (90 days default)
2. Group by hour + event_type + agent_id
3. For each group: write to gzip archive, create AuditSummary row
4. Delete archived AuditEvent rows
5. Emit meta audit event about the compaction run
6. Return stats (archived count, summaries created, archive files)

### Configuration

- `TRELLIS_AUDIT_RETENTION_DAYS` (default: 90)
- `TRELLIS_COMPACTION_INTERVAL` (default: 86400)
- `TRELLIS_ARCHIVE_DIR` (default: data/audit_archive)

### Background Loop

```python
compactor_loop(interval=86400)  # TRELLIS_COMPACTION_INTERVAL
```

### Migration Notes

- **DO NOT CONVERT TO LLM.** Pure database operations.
- The `.process()` method runs actual compaction (not dry-run despite the text saying "dry run").
- Keep as native agent with background loop.

---

## Agent 7: RuleOptimizerAgent

**File:** `trellis/agents/rule_optimizer.py`
**Class:** `RuleOptimizerAgent`
**Uses AgentLoop:** NO — pure database analysis logic
**Recommended agent_type:** `native` (keep as-is, NOT suitable for LLM)

### Why NOT to convert to LLM

This agent performs read-only database analysis:
- Queries all active rules and recent envelope logs
- Identifies dead rules (0 matches in period)
- Detects overlapping rules (same conditions, different priorities/targets)
- Finds priority conflicts
- Ranks rule utilization
- Reports unmatched envelopes by source type

### Processing Flow

1. Query active Rules and EnvelopeLog entries (last N days)
2. Build match count per rule_id
3. Find dead rules (active but 0 matches)
4. Find overlapping rules (identical conditions, different priorities)
5. Find priority conflicts (same conditions, different targets)
6. Build utilization ranking
7. Report top unmatched sources
8. Return structured report

### Configuration

- `TRELLIS_RULE_OPTIMIZER_HOUR` (default: 2) — runs daily at 2 AM UTC

### Background Loop

```python
rule_optimizer_loop()  # checks hourly, runs once per day at configured hour
```

### Migration Notes

- **DO NOT CONVERT TO LLM.** Pure SQL analytics.
- The `.process()` method accepts `days` parameter from `envelope.routing_hints`.
- Keep as native agent with background loop.

---

## Agent 8: SchemaDriftDetectorAgent

**File:** `trellis/agents/schema_drift.py`
**Class:** `SchemaDriftDetectorAgent`
**Uses AgentLoop:** NO — pure schema comparison logic
**Recommended agent_type:** `native` (keep as-is, NOT suitable for LLM)

### Why NOT to convert to LLM

This agent performs schema monitoring:
- Extracts field structures from recent envelopes
- Compares against stored baselines
- Detects new fields, missing fields, type changes
- Assigns severity (critical for type changes, major for missing fields, minor for new fields)
- Persists baselines to JSON file on disk
- Emits audit events for drift detection

### Processing Flow

1. Load schema baselines from disk (data/schema_baselines.json)
2. Query EnvelopeLog entries from last 24 hours
3. Group by source_type
4. For each source: extract field structures recursively, compare against baseline
5. Detect new_fields, missing_fields, type_changes
6. Assign severity: type_changes → critical, missing_fields → major, new_fields → minor
7. Update baselines with merged schema
8. Save baselines to disk
9. Return structured drift report

### Configuration

- `TRELLIS_SCHEMA_CHECK_INTERVAL` (default: 21600 = 6 hours)
- `TRELLIS_SCHEMA_BASELINES` (default: data/schema_baselines.json)

### Background Loop

```python
schema_drift_loop()  # runs every TRELLIS_SCHEMA_CHECK_INTERVAL seconds
```

### Migration Notes

- **DO NOT CONVERT TO LLM.** Pure data comparison logic.
- Keep as native agent with background loop.

---

## Agent 9: CostOptimizerAgent

**File:** `trellis/agents/cost_optimizer.py`
**Class:** `CostOptimizerAgent`
**Uses AgentLoop:** NO — pure database analytics
**Recommended agent_type:** `native` (keep as-is, NOT suitable for LLM)

### Why NOT to convert to LLM

This agent performs FinOps analysis:
- Queries CostEvent table for spending data
- Calculates cost by agent, cost by model
- Computes p95 latency per model
- Analyzes complexity class breakdowns
- Generates model downgrade recommendations (expensive models for simple tasks)
- Projects monthly budget

### Processing Flow

1. Query CostEvent table for period (default 7 days)
2. Calculate total cost, cost by agent, cost by model
3. Compute p95 latency via NTILE window function
4. Analyze complexity class breakdown per agent+model
5. Generate recommendations: if >50% of requests are "simple" complexity AND model is expensive (>$10/Mtok input), recommend downgrade to local model (qwen3.5:9b)
6. Calculate daily average and monthly projection
7. Return structured cost report

### Configuration

- `TRELLIS_COST_OPTIMIZER_INTERVAL` (default: 168 hours = weekly)
- Expensive threshold: $10/Mtok average
- Local models: qwen3.5:9b, qwen3:8b, llama3.1:8b
- Simple complexity classes: LOW, NORMAL, simple, low, normal

### Background Loop

```python
cost_optimizer_loop()  # checks hourly, runs on interval
```

### Migration Notes

- **DO NOT CONVERT TO LLM.** Pure SQL analytics with complex window functions.
- The `.process()` method accepts `days` parameter from `envelope.routing_hints`.
- Keep as native agent with background loop.

---

## Migration Summary

### Agents to Convert to LLM Config

| Agent | Current Type | Target Type | Has System Prompt | Tools Needed |
|---|---|---|---|---|
| SecurityTriageAgent | LLM (AgentLoop) | `llm` | YES (existing) | check_cisa_kev |
| ITHelpAgent | Native (no LLM) | `llm` | NO (needs new) | classify_ticket, lookup_tech_stack, assess_priority, lookup_known_resolution |
| SAMHRAgent | Native (no LLM) | `llm` | NO (needs new) | classify_hr_case, assess_hr_priority, lookup_hr_policy |
| RevCycleAgent | Native (no LLM) | `llm` | NO (needs new) | classify_rev_cycle_case, analyze_denial, assess_rev_cycle_priority |

### Agents to Keep as Native

| Agent | Reason |
|---|---|
| HealthAuditorAgent | Infrastructure monitoring with HTTP clients, DB queries, API routes, background loop |
| AuditCompactorAgent | Database maintenance (archive + delete), background loop |
| RuleOptimizerAgent | SQL analytics (dead rules, overlaps, utilization), background loop |
| SchemaDriftDetectorAgent | Schema comparison with baseline persistence, background loop |
| CostOptimizerAgent | FinOps SQL analytics with window functions, background loop |

### Shared Patterns to Extract

1. **Envelope parsing** — All agents have similar `_parse_*` / `_extract_text` methods. Extract to a shared utility.
2. **Team mapping** — IT Help, SAM-HR, and Rev Cycle all have `_TEAM_MAP` dicts. These should go in system prompts for LLM agents.
3. **Background loops** — 5 agents have background loops. These are infrastructure, not agent behavior.
4. **Result format** — All agents return `{"status": "completed", "result": {"text": ..., "data": ..., "attachments": []}}`. This is the standard envelope.

### Tool Schemas Needed for LLM Agents

All tools currently exist as Python functions in `tools.py` and are registered in `tool_registry.py`. To use them with LLM agents, each needs an OpenAI function-calling schema. Currently only `check_cisa_kev` has one (`CISA_KEV_SCHEMA`).

**Schemas to create:**

1. `classify_ticket(description: str, category_hint: str | None) → dict`
2. `lookup_tech_stack(product: str, vendor: str = "") → dict`
3. `assess_priority(severity: str | None, affected_users: int, system_criticality: str | None) → dict`
4. `lookup_known_resolution(category: str, keywords: list[str]) → str | None`
5. `classify_hr_case(description: str, category_hint: str | None) → dict`
6. `assess_hr_priority(category: str, regulatory_flags: list[str], affected_employees: int) → dict`
7. `lookup_hr_policy(category: str, keywords: list[str]) → dict`
8. `classify_rev_cycle_case(description: str, category_hint: str | None) → dict`
9. `analyze_denial(denial_code: str, payer: str, amount: float) → dict`
10. `assess_rev_cycle_priority(category: str, amount: float, days_aged: int, timely_filing_deadline: int) → dict`

### Cross-Agent Delegation

SecurityTriageAgent delegates to ITHelpAgent for CRITICAL CVEs via `AgentContext.delegate()`. This should be converted to either:
- A routing rule (CRITICAL security findings auto-create IT tickets)
- A delegation tool available to the security agent
- A post-processing hook in the agent config

### Key Decision: LLM vs Native for IT Help, SAM-HR, Rev Cycle

These 3 agents are currently pure deterministic logic. Converting to LLM adds:
- **Pros:** Better classification accuracy, natural language explanations, flexible handling of edge cases
- **Cons:** Slower (200ms → 2-5s), costs money, non-deterministic, may hallucinate priority levels

**Recommendation:** Convert to LLM but include the deterministic tools as structured function calls. The LLM orchestrates the tool calls but the actual classification/priority logic stays in the tools. This gives the best of both worlds — LLM reasoning for orchestration, deterministic tools for accuracy.
