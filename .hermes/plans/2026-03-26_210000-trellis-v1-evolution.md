# Trellis v1.0 Evolution Plan

**Goal:** Evolve Trellis from a v0.3 agent orchestration demo into a v1.0 platform with
truly agentic agents, agent-to-agent delegation, semantic routing, streaming LLM,
hardened intake pipeline, and a professional dashboard UI.

**Current state:** ~40k LOC. FastAPI + SQLAlchemy/SQLite + Next.js 16 dashboard.
9 native agents that are essentially prompt templates. Rules-based routing.
PHI Shield and FinOps are solid. Tests: 447.

**Branch strategy:** All work on `feat/v1-evolution` branch, push to origin after each iteration.

---

## Iteration 1: Agent Execution Engine (Foundation)

**Why first:** Everything else (delegation, tools, streaming) depends on agents being
able to actually *do things* beyond formatting a prompt.

### Tasks

#### 1.1 — Agent Execution Context
Create `trellis/agent_context.py` — a runtime context object passed to agents during execution.

```python
class AgentContext:
    agent_id: str
    trace_id: str
    envelope: dict
    db: AsyncSession
    tools: ToolRegistry          # bound to this agent's permissions
    llm: LLMClient              # bound to this agent's config/budget
    emit_event: Callable         # audit event emitter
    delegate: Callable           # send envelope to another agent (Iteration 2)
    memory: AgentMemory          # per-agent key-value store (Iteration 3)
```

- File: `trellis/agent_context.py` (~80 lines)
- Modify: `trellis/router.py` — dispatcher builds context before calling agent
- Tests: `tests/test_agent_context.py`

#### 1.2 — Tool Execution in Agents
Wire the existing tool_registry into agent execution so agents can actually call tools.

- Modify: `trellis/tool_registry.py` — add `execute_tool(agent_id, tool_name, params)` method
- Modify: `trellis/agents/security_triage.py` — use `ctx.tools.call("check_cisa_kev", cve_id=...)`
  instead of the current stub
- Implement: `trellis/agents/tools.py` — make `check_cisa_kev` actually call CISA KEV API
- Tests: `tests/test_tool_execution.py`

#### 1.3 — Multi-Step Agent Loop
Replace single-shot prompt→response with a ReAct-style loop for LLM agents.

```python
async def run_agent_loop(ctx: AgentContext, max_steps: int = 5):
    messages = [{"role": "system", "content": agent.system_prompt}]
    messages.append({"role": "user", "content": format_envelope(ctx.envelope)})
    
    for step in range(max_steps):
        response = await ctx.llm.chat(messages, tools=ctx.tools.schemas())
        if response.tool_calls:
            for call in response.tool_calls:
                result = await ctx.tools.call(call.name, **call.args)
                messages.append(tool_result_message(call, result))
        else:
            return response.content  # Final answer
```

- File: `trellis/agent_loop.py` (~150 lines)
- Modify: `trellis/router.py` — use `run_agent_loop` for LLM-type agents
- Modify: `trellis/gateway.py` — expose tool-call-aware completions
- Tests: `tests/test_agent_loop.py`

#### 1.4 — Upgrade SecurityTriageAgent as Proof
Rewrite SecurityTriageAgent to use the new execution engine:
- Step 1: Classify the CVE/vulnerability from envelope
- Step 2: Call `check_cisa_kev` tool with CVE ID
- Step 3: Cross-reference with internal asset inventory (mock tool)
- Step 4: Generate risk assessment with LLM
- Step 5: Return structured triage result

- Modify: `trellis/agents/security_triage.py`
- Tests: `tests/test_security_triage_v2.py`

### Files changed: ~8 files, ~500 lines new, ~200 lines modified
### Verification: Start server, POST a CVE envelope, verify multi-step execution in audit log

---

## Iteration 2: Agent-to-Agent Delegation

**Why second:** This unlocks compound workflows — the key differentiator for enterprise.

### Tasks

#### 2.1 — Delegation Protocol
Define how agents request work from other agents.

```python
class DelegationRequest:
    from_agent: str
    to_agent: str
    envelope: Envelope           # the work to delegate
    callback_mode: str           # "sync" | "async" | "fire_and_forget"
    context: dict                # shared context from parent
    max_hops: int = 3            # prevent infinite delegation chains
    hop_count: int = 0
```

- File: `trellis/delegation.py` (~200 lines)
- Modify: `trellis/agent_context.py` — wire `ctx.delegate()` method
- New migration: add `parent_envelope_id` and `delegation_chain` to EnvelopeLog
- Tests: `tests/test_delegation.py`

#### 2.2 — Delegation-Aware Router
Extend the router to handle delegated envelopes.

- Modify: `trellis/router.py` — detect delegation requests in agent responses,
  route delegated envelopes with hop tracking, return results to parent agent
- Add: circuit breaker for delegation loops (max_hops enforcement)
- Tests: `tests/test_delegation_routing.py`

#### 2.3 — Cross-Agent Workflow: Security → IT Help
Build first compound workflow:
1. SecurityTriageAgent finds critical CVE
2. Delegates to ITHelpAgent to create remediation ticket
3. ITHelpAgent returns ticket ID
4. SecurityTriageAgent includes ticket reference in final report

- Modify: `trellis/agents/security_triage.py` — add delegation step
- Modify: `trellis/agents/it_help.py` — accept delegated work
- Tests: `tests/test_cross_agent_workflow.py`
- Integration test: POST CVE → verify both agents executed → verify ticket created

### Files changed: ~6 files, ~400 lines new, ~150 lines modified
### Verification: End-to-end CVE → triage → ticket creation flow via API

---

## Iteration 3: Semantic Classification & Routing

**Why third:** Rules-only routing breaks when content doesn't match keywords. Embeddings
make routing intelligent without manual rule maintenance.

### Tasks

#### 3.1 — Embedding Service
Add lightweight embedding support for semantic matching.

- File: `trellis/embeddings.py` (~120 lines)
- Use: sentence-transformers with `all-MiniLM-L6-v2` (fast, small, good enough)
- API: `embed(text) → vector`, `similarity(v1, v2) → float`
- Fallback: if model not available, degrade to keyword matching (current behavior)
- Config: `TRELLIS_EMBEDDING_MODEL` env var
- Tests: `tests/test_embeddings.py`

#### 3.2 — Agent Intent Profiles
Each agent gets a semantic profile — a natural language description of what it handles.

- Modify: `trellis/models.py` — add `intent_description: str` and `intent_embedding: JSON`
  to Agent model
- Modify: `trellis/schemas.py` — add to AgentCreate/AgentUpdate
- New migration: add columns
- Auto-compute: on agent create/update, embed the intent_description
- Tests: `tests/test_agent_intent.py`

#### 3.3 — Semantic Router
Add semantic scoring to the intelligent router.

- Modify: `trellis/intelligent_router.py` — add 6th scoring dimension: `semantic_score`
  (weighted at 25%, reduce others proportionally)
- Envelope text → embed → cosine similarity against all agent intent embeddings
- Cache embeddings in memory (agents don't change often)
- Tests: `tests/test_semantic_routing.py`

#### 3.4 — Classification Enhancement
Add semantic features to the classification engine.

- Modify: `trellis/classification.py` — use embeddings for category detection as
  supplement to keyword matching
- Add confidence scores to classification output
- Tests: `tests/test_semantic_classification.py`

### Files changed: ~6 files, ~400 lines new, ~200 lines modified
### Verification: POST ambiguous envelopes, verify semantic routing outperforms keyword-only

---

## Iteration 4: Streaming LLM Responses

**Why fourth:** Needed for Teams bot and dashboard UX. Users shouldn't stare at a spinner
for 30 seconds.

### Tasks

#### 4.1 — Streaming Gateway
Add SSE streaming support to the LLM gateway.

- Modify: `trellis/gateway.py` — add `stream=True` support to `/v1/chat/completions`
- Return: `text/event-stream` SSE with OpenAI-compatible chunks
- PHI Shield: streaming-aware redaction (buffer until sentence boundary)
- Tests: `tests/test_streaming_gateway.py`

#### 4.2 — Streaming Agent Responses
Agents can stream results back to callers.

- Modify: `trellis/router.py` — add streaming dispatch mode
- Modify: `trellis/api.py` — add `/api/envelopes/stream` endpoint (SSE)
- Wire into agent_loop: yield intermediate steps
- Tests: `tests/test_streaming_dispatch.py`

#### 4.3 — Teams Streaming
Stream LLM responses in Teams chat (typing indicator + incremental updates).

- Modify: `trellis/adapters/teams_adapter.py` — use activity update for streaming
- Modify: `trellis/bot_service.py` — typing indicator during processing
- Tests: `tests/test_teams_streaming.py`

### Files changed: ~5 files, ~350 lines new, ~150 lines modified
### Verification: Call streaming endpoint with curl, verify SSE chunks arrive incrementally

---

## Iteration 5: Intake Pipeline Hardening

**Why fifth:** Production reliability for the content sourcing pipeline.

### Tasks

#### 5.1 — Retry & Error Handling
- Modify: `~/workspace/intake/sourcer.py` — add exponential backoff on delivery failures
- Add: per-source error counters and circuit breaker (disable source after N consecutive failures)
- Add: dead letter queue (failed envelopes saved to SQLite for replay)
- Tests: `~/workspace/intake/tests/test_retry.py`

#### 5.2 — SeenDB Maintenance
- Modify: `~/workspace/intake/sourcer.py` — add TTL to seen entries (default 30 days)
- Add: cleanup job that runs on startup
- Tests: `~/workspace/intake/tests/test_seendb.py`

#### 5.3 — HHS Breach Scraper
Implement the stubbed `fetch_scrape` for the OCR breach portal.

- Modify: `~/workspace/intake/fetchers.py` — implement HHS breach portal scraping
- Use: httpx + selectolax (lightweight HTML parsing)
- Enable: hhs-breaches source in config.yaml
- Tests: `~/workspace/intake/tests/test_hhs_scraper.py`

#### 5.4 — Intake Health Endpoint
Add a `/health` endpoint so Trellis can monitor intake status.

- Modify: `~/workspace/intake/sourcer.py` — add minimal FastAPI app with health + metrics
- Expose: sources status, last fetch times, error counts, seen DB size
- Config: `INTAKE_PORT` env var (default 8001)
- Tests: `~/workspace/intake/tests/test_health.py`

#### 5.5 — Fix Configuration Issues
- Fix: Dockerfile python version (3.12 → match pyproject.toml)
- Fix: pyproject.toml description
- Add: .env.example with TRELLIS_URL documentation
- Add: docker-compose.yml for intake standalone

### Files changed: ~6 files in intake, ~600 lines new, ~100 lines modified
### Verification: Run intake with intentional failures, verify retry + DLQ behavior

---

## Iteration 6: Dashboard UI Redesign

**Why last:** The platform needs to be functionally complete before polishing the UI.
Uses the ui-ux-design-system skill for design intelligence.

### Tasks

#### 6.1 — Generate Design System
Run the UI/UX search engine to generate a tailored design system for Trellis.

```bash
python3 ~/.hermes/skills/software-development/ui-ux-design-system/scripts/search.py \
  "enterprise SaaS healthcare security dashboard" \
  --design-system -p "Trellis" --format markdown
```

Apply the generated palette, typography, and patterns to the dashboard.

#### 6.2 — Design Token Foundation
Create CSS variables and Tailwind config based on design system output.

- Modify: `dashboard/src/app/globals.css` — replace current tokens with generated palette
- Modify: `dashboard/postcss.config.mjs` / tailwind config if needed
- Ensure dark mode (this is an ops dashboard — dark by default is correct)

#### 6.3 — Navigation & Layout Polish
- Modify: `dashboard/src/components/sidebar.tsx` — apply new design tokens,
  improve active state, add collapsible behavior
- Modify: `dashboard/src/app/layout.tsx` — responsive layout improvements
- Add: breadcrumbs component for deeper navigation

#### 6.4 — Overview Dashboard Redesign
- Modify: `dashboard/src/app/page.tsx` — redesign with proper stat cards,
  activity feed, system health at-a-glance
- Use: Recharts with design system colors
- Add: real-time polling indicators

#### 6.5 — Agent Management Page
- Modify: `dashboard/src/app/agents/page.tsx` — card grid with status indicators,
  health badges, delegation chain visualization (new in v1)
- Add: agent detail slide-over panel with execution history

#### 6.6 — FinOps & Observatory Polish
- Modify: `dashboard/src/app/finops/page.tsx` — cost charts with proper design tokens
- Modify: `dashboard/src/app/observatory/page.tsx` — latency/throughput visualization
- Apply: consistent chart theming

#### 6.7 — New: Delegation Flow Visualization
- New: `dashboard/src/app/delegation/page.tsx` — visualize agent-to-agent delegation
  chains, show active workflows, trace compound operations
- Use: tree/graph visualization for delegation chains

#### 6.8 — Responsive & Accessibility Pass
- All pages: ensure 375px–1440px responsive
- All interactive elements: keyboard navigation, focus states, ARIA labels
- All charts: color-blind safe palettes
- Run: Lighthouse audit, fix issues

### Files changed: ~15 dashboard files, ~1500 lines new/modified
### Verification: Visual inspection at all breakpoints, Lighthouse score ≥ 90

---

## Summary

| Iteration | Focus | New LOC (est) | Key Deliverable |
|-----------|-------|---------------|-----------------|
| 1 | Agent Execution Engine | ~500 | Multi-step ReAct agents with tool use |
| 2 | Agent-to-Agent Delegation | ~400 | Compound workflows (Security → IT) |
| 3 | Semantic Classification | ~400 | Embedding-based routing |
| 4 | Streaming LLM | ~350 | SSE streaming for gateway + Teams |
| 5 | Intake Hardening | ~600 | Retry, DLQ, HHS scraper, health |
| 6 | Dashboard UI Redesign | ~1500 | Professional UI with design system |
| **Total** | | **~3,750** | |

## Risks & Mitigations

- **SQLite contention under load:** Mitigated by keeping this as a demo/staging concern.
  Production migration to Azure SQL is a separate track.
- **Embedding model size:** all-MiniLM-L6-v2 is 80MB. Acceptable for server deployment.
  Falls back to keyword matching if unavailable.
- **Streaming + PHI Shield conflict:** Must buffer at sentence boundaries to avoid
  leaking partial PHI. Explicitly tested.
- **Delegation loops:** Hard cap at max_hops=3 with circuit breaker. Tested.

## Open Questions

1. Should delegation support async callbacks (webhook-style) or only sync?
   Plan assumes sync-first with async as future enhancement.
2. Should the embedding service be shared with intake for semantic dedup?
   Good idea but out of scope for v1.
3. Dashboard: keep Next.js 16 or consider simpler SPA (Vite + React)?
   Plan keeps Next.js since it's already working.
