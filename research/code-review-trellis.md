# Trellis Code Review

**Date:** 2026-02-25
**Reviewer:** Reef (automated)
**Scope:** Full codebase — `trellis/` (8,008 LOC Python), `dashboard/src/` (1,135 LOC TypeScript), `tests/` (2,063 LOC)
**Test Results:** 104/104 passing (25s), `test_gateway_api.py` excluded (requires live Ollama)

---

## Executive Summary

Trellis is in strong shape for demo-stage software. The architecture is sound, the test coverage is excellent for this stage, and the core event routing + LLM gateway pipeline works end-to-end. The code is generally readable and well-structured.

**The biggest structural issue is over-fragmentation.** The codebase is split across ~50 Python files when ~10-15 would be more readable, maintainable, and Karpathy-appropriate. There's a premature abstraction layer (runtimes) that adds complexity without current value, and the models/schemas/api split creates a lot of tiny files that force you to hop between 3+ files to understand any single feature.

**Verdict:** Solid foundation. Consolidate aggressively before adding features. The complexity budget is being spent on file organization instead of actual functionality.

---

## 🔴 Critical Issues

### 1. API Key Plaintext Caching on Disk (`api/keys.py:_cache_agent_key`)

```python
def _cache_agent_key(agent_id: str, raw_key: str) -> None:
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "key_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key_file = os.path.join(cache_dir, f"{agent_id}.key")
    with open(key_file, "w") as f:
        f.write(raw_key)
    os.chmod(key_file, 0o600)
```

This writes raw API keys to disk in plaintext. In a HIPAA context, this is a finding. Keys are hashed in the DB (good), then un-hashed copies are stored on the filesystem (bad). If the server is compromised, every agent key is immediately available.

**Fix:** Remove the key cache entirely. If internal gateway routing needs to authenticate, use a server-side bypass (internal header, loopback whitelist) instead of replaying real keys.

### 2. `NvidiaProvider` Doesn't Inherit `LLMProvider`

```python
class NvidiaProvider:  # ← missing LLMProvider base
    name = "nvidia"
```

Every other provider inherits `LLMProvider`. Nvidia doesn't. It has `available` property instead of `is_configured()` method. This causes the `model_router.py` to do awkward duck-typing:

```python
configured = getattr(provider, 'available', getattr(provider, 'is_configured', lambda: False))
if not provider or not (configured() if callable(configured) else configured):
```

**Fix:** Make `NvidiaProvider` inherit `LLMProvider`, rename `available` → `is_configured()`. Delete the duck-typing hack.

### 3. New `httpx.AsyncClient` Per Request in Every Provider

Every provider creates and tears down an `httpx.AsyncClient` per call:

```python
async with httpx.AsyncClient(timeout=120.0) as client:
    resp = await client.post(...)
```

This means a new TCP connection + TLS handshake for every single LLM call. For a platform routing hundreds of requests, this is a significant performance hit.

**Fix:** Use a shared client per provider (initialized in `__init__`, closed on shutdown). FastAPI's lifespan hook is the right place.

---

## 🟡 Structural Issues (Over-Engineering)

### 4. The Runtimes Abstraction Is Premature — Delete It

The `runtimes/` package (5 files, ~300 LOC) provides an `AgentRuntime` ABC with two implementations:
- **`HttpRuntime`** — wraps `dispatch_http` in more code
- **`PiRuntime`** — creates `OllamaProvider()` directly, bypassing the entire gateway routing/cost-tracking pipeline

Problems:
- `PiRuntime` hardcodes `OllamaProvider()`, skipping model routing, cost tracking, budget enforcement, and audit logging. Any agent using the Pi runtime gets zero FinOps visibility.
- `dispatch_via_runtime()` in `dispatcher.py` exists but **nothing calls it** — the actual `event_router.py` calls `_dispatch_by_type()` which uses the legacy path.
- The whole abstraction is dead code with a live bug (the Pi runtime bypass).

**Fix:** Delete `runtimes/` entirely. It's 300 lines that do nothing in the current architecture. When you actually need pluggable runtimes (Pi SDK integration), build it then — you'll know the real requirements.

### 5. Too Many Tiny Files — Consolidate the Layers

Current structure forces you to look at 3-4 files to understand one feature:

| Feature | Files |
|---------|-------|
| Agents | `models/agent.py` (30 LOC) + `schemas/agent.py` (70 LOC) + `api/agents.py` (100 LOC) |
| Rules | `models/rule.py` (18 LOC) + `schemas/rule.py` (40 LOC) + `api/rules.py` (80 LOC) |
| Audit | `models/audit_event.py` (20 LOC) + `schemas/audit.py` (15 LOC) + `api/audit.py` (40 LOC) + `core/audit.py` (20 LOC) |

The `models/` dir has 7 files averaging 25 LOC each. The `schemas/` dir has 7 files averaging 30 LOC each. This is premature separation.

**Proposed consolidation (Karpathy-style):**

```
trellis/
  main.py          ← app setup, lifespan, health
  config.py         ← keep as-is
  database.py       ← keep, add all models here (they're tiny)
  models.py         ← merge all 7 model files (total ~170 LOC)
  schemas.py        ← merge all 7 schema files (total ~210 LOC)
  router.py         ← event routing + rule engine (currently 2 files, ~250 LOC)
  gateway.py        ← merge gateway/{router,auth,budget,cost_tracker,finops,model_router}.py + all providers
  api.py            ← merge all 9 api/*.py files into one (they're all thin CRUD)
  adapters.py       ← merge http_adapter + rss_adapter
  functions.py      ← merge echo + ticket_logger (trivial)
```

That's 10 files instead of ~40. Everything is readable top-to-bottom. You can `grep` for anything and find it.

### 6. `gateway/providers/` — 6 Providers, 5 Are Copy-Paste

`OpenAIProvider`, `GroqProvider`, `GoogleProvider` are identical except for `name`, `base_url`, and env var name. They're all "POST to OpenAI-compatible endpoint with Bearer token":

```python
class GroqProvider(LLMProvider):
    name = "groq"
    def __init__(self):
        self.api_key = os.environ.get("TRELLIS_GROQ_API_KEY", "")
        self.base_url = "https://api.groq.com/openai/v1"
    # ... identical chat_completion
```

Only `AnthropicProvider` and `NvidiaProvider` have meaningfully different logic.

**Fix:** One `OpenAICompatibleProvider` class, configured per-instance:

```python
providers = {
    "openai": OpenAICompatibleProvider("openai", "TRELLIS_OPENAI_API_KEY", "https://api.openai.com/v1"),
    "groq": OpenAICompatibleProvider("groq", "TRELLIS_GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "google": OpenAICompatibleProvider("google", "TRELLIS_GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "ollama": OpenAICompatibleProvider("ollama", None, "http://localhost:11434/v1", always_configured=True),
    "nvidia": OpenAICompatibleProvider("nvidia", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
    "anthropic": AnthropicProvider(),  # only this one needs custom logic
}
```

That replaces 7 files with ~30 lines of config + one small class.

### 7. Dual Dispatch Path Is Confusing

`dispatcher.py` has two dispatch systems:
1. **Legacy:** `dispatch_http()`, `dispatch_function()`, `dispatch_llm()` — actually used
2. **Runtime:** `dispatch_via_runtime()` — never called

And `dispatch_llm()` reimplements provider resolution inline instead of calling the gateway endpoint. It does `from trellis.gateway.model_router import MODEL_PROVIDER_MAP, _providers` and manually calls providers, duplicating logic from `gateway/router.py`.

**Fix:** One dispatch path. `dispatch_llm` should call the same `resolve_model_and_provider_async` + `provider.chat_completion` that the gateway endpoint uses. Better yet, since agents go through the event router anyway, just use the gateway endpoint's logic directly.

---

## 🟡 Code Quality Issues

### 8. `dispatch_llm` Opens Its Own DB Session Then Doesn't Use It

```python
async def dispatch_llm(...):
    from trellis.database import async_session  # imported but never used
```

The import is dead code. Cost logging happens in `event_router._log_gateway_cost` after the fact. This suggests the function was refactored partway and the cleanup wasn't finished.

### 9. Module-Level Mutable State in `dispatcher.py`

```python
_client_override: httpx.AsyncClient | None = None
def set_client_override(client: httpx.AsyncClient | None) -> None:
    global _client_override
    _client_override = client
```

This is a test-only hook using global mutable state. It works for single-threaded tests but is a footgun in production (async concurrency). The test fixtures do clean it up, but it's still a code smell.

**Fix:** Use `httpx.MockTransport` or dependency injection via FastAPI's `app.dependency_overrides` instead.

### 10. `health_checker.py` Global `_running` Flag

```python
_running = True
def stop():
    global _running
    _running = False
```

Same pattern — global mutable state for lifecycle control. Works, but fragile.

### 11. Dashboard TypeScript Types Don't Match API

The dashboard `CostSummary` interface expects `agent_name`, `department`, `total_cost`, `total_tokens`, `event_count` — but the actual `/api/costs/summary` endpoint returns `agent_id`, `total_cost_usd`, `total_tokens_in`, `total_tokens_out`, `request_count`. Almost none of the field names match.

Similarly, `CostEvent` expects `cost_event_id`, `department`, `event_type`, `model` — the API returns `id`, `model_used`, `model_requested`, `provider` with no `department` or `event_type`.

**Impact:** The dashboard costs page likely renders empty/broken data. Either the types are aspirational (from a spec) or from an older API version.

**Fix:** Regenerate types from the actual API or add a `/openapi.json` → TypeScript codegen step.

### 12. Delete Audit Event Uses Wrong Event Type

```python
# api/agents.py, delete_agent:
await emit_audit(db, "agent_registered", agent_id=agent_id, details={
    "action": "deleted", "name": agent.name,
})
```

The event type `"agent_registered"` is wrong for a deletion. Should be `"agent_deleted"` or at least a distinct type. This makes audit filtering unreliable — querying for `event_type=agent_registered` returns both creates and deletes.

### 13. `NvidiaProvider.list_models()` Exists Only on Nvidia

No other provider has `list_models()`. It's not in the `LLMProvider` ABC. This is unused code that creates an inconsistent interface.

---

## 🟢 What's Working Well

### Strong Test Suite
104 tests covering CRUD, event routing, rule engine operators, fan-out dispatch, budget enforcement, anomaly detection, complexity classification, cost aggregation, and audit trails. Tests use proper async fixtures and isolated DB sessions. The slice-based organization is clear.

### Rule Engine Is Excellent
`rule_engine.py` is the best file in the codebase. Clean, focused, handles 10 operators with dot-notation field resolution. The `_SENTINEL` pattern for missing fields is correct. Fan-out logic is well-designed. This is Karpathy-quality code.

### Audit Trail Design
Granular audit events with trace_id threading is exactly right for healthcare. Every significant action emits an audit event. The trace chain view (`/audit/trace/{trace_id}`) is a strong differentiator.

### Gateway Architecture
The model routing concept (complexity classification → model selection → provider resolution → cost tracking) is sound. The separation of concerns between "which model" and "which provider" is correct. Budget caps + anomaly detection are real FinOps features, not demo fluff.

### Envelope Spec
The generic envelope with payload, metadata, routing hints, and trace_id is a good abstraction. The HTTP adapter that normalizes simplified input into full envelopes is practical.

### Config Is Clean
`pydantic-settings` with sensible defaults. No secrets in code. Environment variables follow a consistent `TRELLIS_` prefix convention.

---

## 📋 Prioritized Recommendations

### Must-Do Before Production

1. **Remove plaintext key caching** — security risk, especially for HIPAA
2. **Fix NvidiaProvider** — inherit LLMProvider, kill the duck-typing hack
3. **Fix dashboard type mismatches** — costs page is likely broken
4. **Fix delete audit event type** — `agent_registered` → `agent_deleted`

### Should-Do (Consolidation Sprint)

5. **Delete `runtimes/`** — dead code with a live bypass bug
6. **Merge providers into one `OpenAICompatibleProvider`** — 7 files → 1 class + config
7. **Merge `models/` into `models.py`** — 7 files → 1 file (~170 LOC)
8. **Merge `schemas/` into `schemas.py`** — 7 files → 1 file (~210 LOC)
9. **Merge `api/` into `api.py`** — 9 files → 1 file, each section is just thin CRUD
10. **Unify dispatch path** — one `dispatch_llm` that uses gateway routing, not a parallel implementation

### Nice-to-Have

11. **Shared `httpx.AsyncClient` per provider** — connection pooling, significant perf gain
12. **Replace `_client_override` global** with proper DI or mock transport
13. **Add `alembic` migrations** — currently relies on `create_all()`, no migration path
14. **Rate limiting on gateway endpoint** — budget caps exist but no request throttling
15. **Add `/openapi.json` → TypeScript codegen** for dashboard type safety

---

## Metrics

| Metric | Value |
|--------|-------|
| Python source files | ~45 |
| Python LOC (excl. tests) | ~8,000 |
| Test LOC | ~2,060 |
| Test count | 104 passing |
| Dashboard LOC | ~1,135 |
| Dependencies | 9 runtime + 3 dev |
| Suggested file count after consolidation | ~12-15 |

---

## Bottom Line

The functionality is solid. The architecture is sound. The problem is organizational complexity — too many files, too many layers, too many abstractions for what's essentially a ~3,000 LOC application padded to 8,000 by file structure overhead. A consolidation sprint that merges the obvious candidates would make this codebase dramatically more readable and maintainable without changing any functionality. Kill the runtimes, flatten the layers, and this is a tight, impressive demo.
