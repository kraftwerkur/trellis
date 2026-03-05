# Trellis Refactor Summary — Karpathy-Style Consolidation

**Date:** 2026-02-26
**Result:** 45 files → 11 files. All 127 tests passing.

## What Changed

### File Consolidation
| Before | After | What merged |
|--------|-------|-------------|
| `models/*.py` (7 files) | `models.py` | Agent, ApiKey, AuditEvent, CostEvent, EnvelopeLog, ModelRoute, Rule |
| `schemas/*.py` (7 files) | `schemas.py` | All Pydantic schemas for agents, audit, costs, envelopes, gateway, rules |
| `api/*.py` (9 files) | `api.py` | All API endpoints: agents, audit, costs, finops, gateway mgmt, health, keys, routing, rules |
| `gateway/*.py` + `gateway/providers/*.py` (8+6 files) | `gateway.py` | Providers, model router, auth, budget, cost tracker, finops, chat endpoint |
| `core/*.py` (5 files) | `router.py` | Rule engine, event router, dispatcher, audit emission |
| `adapters/*.py` (2 files) | `adapters.py` | HTTP adapter + RSS adapter |
| `functions/*.py` (3 files) | `functions.py` | Registry + echo + ticket_logger |
| `runtimes/*.py` (4 files) | **deleted** | Dead code with bypass bug |

### Critical Fixes
1. **Removed plaintext key caching** — `_cache_agent_key()` and `data/key_cache/` eliminated. Keys are only returned once on creation, never written to disk.
2. **Fixed delete audit event** — Agent delete now emits `"agent_deleted"` instead of `"agent_registered"`.
3. **Fixed NvidiaProvider** — Replaced with `OpenAICompatibleProvider("nvidia", ...)`, properly inherits `LLMProvider`.
4. **Fixed dashboard type mismatches** — `trellis.ts` and `api.ts` now match actual Python API response shapes (CostSummary fields, CostEvent fields, EnvelopeLog instead of Envelope).

### Provider Consolidation
Six near-identical provider classes → one `OpenAICompatibleProvider` class + config:
```python
"ollama": OpenAICompatibleProvider("ollama", None, "http://localhost:11434/v1", always_available=True),
"openai": OpenAICompatibleProvider("openai", "TRELLIS_OPENAI_API_KEY", "https://api.openai.com/v1"),
"groq": OpenAICompatibleProvider("groq", "TRELLIS_GROQ_API_KEY", "https://api.groq.com/openai/v1"),
...
"anthropic": AnthropicProvider(),  # only custom one (different API format)
```

### Dead Code Removed
- `runtimes/` directory (4 files) — dead code, `dispatch_via_runtime()` was never the real path
- `_cache_agent_key()` — security issue
- `NvidiaProvider.list_models()` — orphan method (gone with provider consolidation)

### What Stayed The Same
- `config.py` — unchanged
- `database.py` — unchanged
- `__init__.py` — unchanged
- All API behavior — same endpoints, same responses
- All 127 tests pass without behavior changes
