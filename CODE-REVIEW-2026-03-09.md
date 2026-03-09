# Trellis Code Review — March 9, 2026

**Reviewer:** Reef (autonomous review)  
**Commit:** `1b2d952` (docs: comprehensive README, DEMO-GUIDE, and ARCHITECTURE update)  
**Scope:** Full codebase — 10,068 LOC across 36 Python files, 6,014 LOC tests (438 tests, all passing)  
**Focus:** Consistency, security, test gaps, dead code, and DB model integrity after rapid 8-module build sprint

---

## Executive Summary

Trellis is in strong shape for a sprint-built system. The architecture is clean — single-file modules following a "Karpathy style" convention, consistent Pydantic/SQLAlchemy patterns, and a well-thought-out routing pipeline. The 438 tests all pass in 29 seconds.

However, the rapid build sprint left three categories of issues:

1. **🔴 CRITICAL: Auth gaps on new endpoints** — Observatory, Health Auditor, Intelligent Router, PHI, and Tools API routes have **zero authentication**. In a healthcare/HIPAA context, this is a blocker.
2. **🟡 MODERATE: Duplicate functionality and dead code** — Two competing health check loops, unused imports, a hacky `_primary_category` function.
3. **🟢 MINOR: Test coverage gaps** — Shadow mode and feedback API endpoints have zero test coverage despite thorough unit-level testing of the underlying logic.

**Overall grade: B+** — Excellent architecture, solid test foundation, but security gaps need immediate attention before any production deployment.

---

## 1. Security Review (HIPAA Context)

### 🔴 P0: Missing Authentication on New API Routes

This is the most critical finding. The original API routes in `api.py` properly use `require_management_auth` or `require_ingestion_auth` dependencies. But the new modules define their own `APIRouter` instances **without any auth**:

| Router | File | Auth | Exposes |
|--------|------|------|---------|
| `intelligent_router` | `intelligent_router.py:632` | ❌ **None** | Agent intake declarations, routing scores, feedback, shadow comparisons |
| `observatory_router` | `observatory.py:277` | ❌ **None** | LLM usage metrics, costs, latency distributions, per-agent data |
| `health_auditor_router` | `health_auditor.py:564` | ❌ **None** | Full infrastructure health data, DB integrity, system resources, disk usage |
| `phi_router` | `api.py:755` | ❌ **None** | PHI detection test endpoint, PHI stats |
| `tools_router` | `api.py:825` | ❌ **None** | Tool registry, execution history |
| `health_router` | `api.py:76` | ❌ **None** | Infrastructure health endpoint |

**Impact:** An unauthenticated attacker can:
- Enumerate all registered agents, their intake declarations, and scoring weights
- View LLM cost data, token usage, and provider configurations
- Probe infrastructure health (DB size, disk space, memory, SMTP config)
- Test PHI detection patterns to reverse-engineer redaction rules
- Submit routing feedback to poison the EMA-based scoring system (`POST /route/feedback`)
- View tool execution history including parameters

**Fix:** Add `dependencies=[Depends(require_management_auth)]` to all new routers. The feedback endpoint specifically should also validate that the submitting entity has authority over the claimed `agent_id`.

### 🟡 P1: Feedback Endpoint — No Input Validation on agent_id

`POST /api/route/feedback` accepts any `agent_id` without verifying the agent exists. Combined with the auth gap above, anyone can inject feedback for arbitrary agents, poisoning the EMA scoring:

```python
# intelligent_router.py:803
# No check that body.agent_id refers to a real agent
feedback = RoutingFeedback(
    envelope_id=body.envelope_id,
    agent_id=body.agent_id,  # ← unvalidated
    ...
)
```

**Fix:** Add `agent = await db.get(Agent, body.agent_id)` check with 404 if not found.

### 🟢 P2: PHI Test Endpoint Exposure

`POST /api/phi/test` allows testing arbitrary text against the PHI detection engine. While it doesn't expose real PHI, it reveals detection patterns. An attacker could use this to craft text that evades detection. This endpoint should be behind management auth.

### ✅ What's Good

- `require_management_auth` uses `secrets.compare_digest` (timing-safe) — correct
- Production mode correctly refuses to start without API keys configured
- PHI vault is ephemeral, per-request, never persisted — excellent HIPAA design
- API keys stored as hashes, never plaintext
- Presidio integration for healthcare-specific entity recognition

---

## 2. Consistency Issues Between New Modules

### 🟡 Duplicate Health Check Loops

Two independent health check systems run simultaneously:

1. **`main.py:55` — `health_check_loop()`**: Simple loop, checks agent health endpoints, updates `Agent.status`
2. **`agents/health_auditor.py:431` — `health_auditor_loop()`**: Comprehensive loop that also checks agents, plus LLM providers, DB integrity, SMTP, system resources, adapters, and background tasks

Both are started in `lifespan()` (main.py:99 and main.py:102). The `health_check_loop` in main.py is **dead code** — everything it does is a subset of what `health_auditor` does, but they run independently and may produce conflicting `Agent.status` values.

**Fix:** Remove `health_check_loop` and `check_agent_health` from `main.py`. The health auditor subsumes all of it.

### 🟡 `_primary_category` Hack in Intelligent Router

```python
def _primary_category(scored: ScoredAgent) -> str:
    """Extract the primary category root from a scored agent (best effort)."""
    # We don't have intake here directly, but we can infer from agent_id patterns
    return scored.agent_id.split("-")[0] if scored.agent_id else ""
```

This is a leftover stub from rapid development. It infers category from agent_id by splitting on `-`, which is fragile and wrong. An agent named `schema-drift-detector` returns `"schema"`, not the actual intake category. This affects multi-dispatch routing decisions (`MULTI_DISPATCH_CATEGORY_PAIRS` lookup).

**Fix:** Pass the `AgentIntake` through the `ScoredAgent` dataclass so `_primary_category` can read `intake.categories[0]` directly.

### ✅ What's Consistent

- All modules follow the same Pydantic schema patterns
- Database models are centralized in `models.py` — no scattered table definitions
- Async patterns are consistent (all use `async_session()`, proper `await`)
- Classification pipeline integrates cleanly — `classify_envelope()` is called before routing in both rule-based and intelligent paths
- Tool registry pattern is consistent across all native agents

---

## 3. Test Coverage Gaps

### Test Coverage Summary

| Module | Test File | Test Count | Coverage Assessment |
|--------|-----------|------------|-------------------|
| Intelligent Router (core) | `test_intelligent_router.py` | 69 | ✅ Excellent — scoring, weights, overlap, EMA |
| Observatory | `test_observatory.py` | 16 | ✅ Good — all API endpoints covered |
| Health Auditor | `test_health_auditor.py` | 20 | ✅ Good — checks, degradation, background tasks |
| Classification | `test_classification.py` | 37 | ✅ Excellent |
| Tool Registry | `test_tool_registry.py` | 16 | ✅ Good |
| PHI Shield | `test_phi_shield.py` | ~30 (in file) | ✅ Excellent |
| **Shadow Mode API** | — | **0** | 🔴 **Not tested** |
| **Feedback API endpoint** | — | **0** | 🔴 **Not tested** |
| **Shadow Report API** | — | **0** | 🔴 **Not tested** |

### Specific Gaps

1. **Shadow mode endpoints** (`POST /route/intelligent/shadow`, `GET /route/shadow/report`) — zero tests. These endpoints call both routing systems and log comparisons. The `ShadowComparison` model is exercised only indirectly.

2. **Feedback API endpoint** (`POST /route/feedback`) — The underlying `update_ema()` function is well-tested, but the HTTP endpoint that wraps it — including the envelope lookup, category extraction, dimension score tracking, and DB persistence — has no integration test.

3. **Multi-dispatch path** — The `MULTI_DISPATCH_CATEGORY_PAIRS` logic depends on `_primary_category` which is broken (see above). No test verifies the actual multi-dispatch decision path with real agent data.

4. **Health Auditor API endpoints** — `test_health_auditor.py` tests the check functions directly but not the FastAPI endpoints (`/health`, `/health/detailed`, `/health/history`).

5. **Cost Optimizer and Schema Drift** — These platform agents have no dedicated test files. They run as background loops and are only tested indirectly.

---

## 4. Dead Code and Leftover Stubs

### 🟡 Dead Code in `main.py`

The entire `check_agent_health()` function and `health_check_loop()` in `main.py` (lines 34-70) are dead code — superseded by the health auditor agent. The loop still runs but its work is redundant and potentially conflicting.

### 🟢 Unused Imports in `observatory.py`

```python
from sqlalchemy import Float, Integer, String, DateTime, Boolean, JSON, func, select, text, case, cast
```

Only `func`, `select`, `case` are used. `Float`, `Integer`, `String`, `DateTime`, `Boolean`, `JSON`, `text`, and `cast` are unused — copy-paste artifact from writing a models file.

### 🟢 Stale Comment in `observatory.py`

Lines 110-137 contain a lengthy internal design discussion comment about error tracking strategy. This is valuable as a design document but shouldn't live in production code. Move to `ARCHITECTURE.md` or delete.

### 🟡 `_hc_stop` / `_hc_start` in `main.py`

These functions control the dead health check loop and are also dead code.

---

## 5. Database Model Consistency

### ✅ All Models Centralized

All 13 SQLAlchemy models live in `models.py` — no scattered definitions. This is excellent practice and was maintained throughout the sprint.

### Models Inventory

| Model | Table | Added In Sprint? | Has Tests? |
|-------|-------|-----------------|-----------|
| `Agent` | `agents` | No (original) | ✅ |
| `ApiKey` | `api_keys` | No | ✅ |
| `AuditEvent` | `audit_events` | No | ✅ |
| `CostEvent` | `cost_events` | No | ✅ |
| `EnvelopeLog` | `envelope_log` | No | ✅ |
| `ModelRoute` | `model_routes` | No | ✅ |
| `AuditSummary` | `audit_summaries` | Yes | ✅ (via compactor) |
| `ToolCallLog` | `tool_calls` | Yes | ✅ |
| `HealthCheck` | `health_checks` | Yes | ✅ |
| `Rule` | `rules` | No | ✅ |
| `RoutingFeedback` | `routing_feedback` | Yes | 🟡 Unit only |
| `ShadowComparison` | `shadow_comparisons` | Yes | 🔴 No direct tests |

### 🟢 Minor: No Migration Strategy

Tables are created via `Base.metadata.create_all()` in the lifespan. No Alembic migrations are configured despite `alembic` being a dependency. This is fine for development but will bite when schema changes need to be applied to existing databases.

### ✅ Column Consistency

All datetime columns use `DateTime(timezone=True)` with `timezone.utc` defaults. All JSON columns use `JSON` type with appropriate defaults. Index placement is consistent. Foreign keys are used correctly (ApiKey → Agent). No orphan relationships detected.

### 🟡 Observatory Error Sentinel

The observatory uses `tokens_in=-1` as an error sentinel in the `CostEvent` table:

```python
event = CostEvent(
    tokens_in=-1,  # error sentinel
    ...
    complexity_class=f"error:{error_type}",
)
```

This is a code smell — overloading a numeric column with a sentinel value. It works but makes queries fragile (every query must remember to filter `tokens_in >= 0` for real events). A boolean `is_error` column or a separate error table would be cleaner.

---

## 6. Architecture Observations

### ✅ Strengths

1. **Single-file modules** — Each feature (PHI shield, classification, intelligent routing, observatory) is self-contained. Easy to understand, test, and replace.

2. **Clean separation of concerns** — Classification is middleware (sync, no DB), routing is the engine, gateway handles LLM proxy, observatory monitors. No circular dependencies.

3. **Native agent pattern** — The agent registry in `agents/__init__.py` is clean. New agents register in one place. The `process(envelope)` interface is simple and consistent.

4. **PHI Shield design** — Ephemeral vault, never-persisted tokens, regex + Presidio hybrid detection. This is the right architecture for HIPAA.

5. **Intelligent Router** — The scoring engine with dimension weights, historical EMA, load balancing, and overlap detection is well-designed. The shadow mode concept for gradual migration from rule-based to intelligent routing is production-thoughtful.

### 🟡 Concerns

1. **SQLite StaticPool** — Using `StaticPool` means a single connection shared across all async operations. This avoids WAL visibility issues but creates a bottleneck under load. Fine for development/PoC, needs PostgreSQL migration for production.

2. **In-memory caches without TTL** — `_stats_cache`, `_load_cache`, `_health_history` in intelligent_router.py and health_auditor.py grow unbounded. Should have max-size limits or TTL eviction.

3. **Background task coordination** — Six background tasks launch in lifespan with no coordination. If one fails, others continue. The health auditor monitors task heartbeats (good!) but can't restart failed tasks.

---

## Action Items (Priority Order)

### P0 — Must Fix Before Production

1. **Add auth to all new API routers** — `intelligent_router`, `observatory_router`, `health_auditor_router`, `phi_router`, `tools_router`, `health_router`. Use `require_management_auth`.
2. **Validate `agent_id` in feedback endpoint** — Check agent exists before accepting feedback.

### P1 — Fix Soon

3. **Remove dead health check loop** from `main.py` (lines 18-70, 97-99). Let health auditor own it.
4. **Fix `_primary_category`** — Pass intake data through `ScoredAgent` dataclass.
5. **Add integration tests** for shadow mode, feedback API, and health auditor API endpoints.

### P2 — Housekeeping

6. **Clean unused imports** in `observatory.py`.
7. **Move design comments** in observatory.py to architecture docs.
8. **Add `is_error` column** to CostEvent (or accept the sentinel and document it).
9. **Add TTL/max-size** to in-memory caches.
10. **Configure Alembic** for schema migrations.

---

## Test Results

```
438 passed in 29.05s
```

All tests pass. No warnings, no skips, no failures. The test suite is well-structured with proper async fixtures and a shared conftest.py.

---

*Review completed March 9, 2026 01:34 EDT*  
*Reviewer: Reef 🪸*
