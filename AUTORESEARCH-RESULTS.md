# Trellis Autoresearch — Session 1 Results

*Optimization target: Test Suite Speed*
*Session date: 2026-03-13*
*Agent: Forge ⚡*

---

## Baseline

| Metric | Value |
|--------|-------|
| **Test suite duration** | **92.0s** |
| Test count | 534 |
| Pass rate | 100% |
| Measured | `./autoresearch.sh test` |

The baseline was dominated by two tests making live Ollama calls:
- `test_llm_agent_dispatch` — 48.4s (dispatches to qwen3.5:9b, awaits LLM response)
- `test_audit_filter_by_agent_id` — 41.3s (gateway proxy call to Ollama)

Secondary overhead: per-test SQLite schema drop/recreate (534 × ~0.05s = ~27s).
Tertiary overhead: health auditor tests probing real HTTP/SMTP endpoints (~0.5s × 4 tests = 2s).

---

## Experiments

### Run 1 — Mock LLM Provider ✅ KEPT

**Hypothesis:** Both slow tests exist to verify routing logic, not LLM output quality.
Mocking the Ollama HTTP call turns 48s + 41s into <0.1s without losing coverage.

**Change:** Added `autouse=True` pytest fixture to `tests/conftest.py` that patches
`trellis.gateway.OpenAICompatibleProvider.chat_completion` with an `AsyncMock`
returning a minimal valid completion response. Tests requiring real Ollama calls
can opt out with `@pytest.mark.no_llm_mock`.

**Result:**

| Before | After | Delta |
|--------|-------|-------|
| 92.0s | 16.8s | **−81.7%** |

534/534 tests pass. Committed: `e01c935`.

---

### Run 2 — Replace Schema Drop/Recreate with Truncate ✅ KEPT

**Hypothesis:** Every `client` fixture invocation calls `drop_all` + `create_all` on SQLite.
With 534 tests, that's 534 schema rebuilds. Replace with `create_all(checkfirst=True)` +
`table.delete()` per-table: schema created once, data cleared between tests.

**Change:** Modified `client` fixture in `tests/conftest.py` to skip `drop_all` entirely.
On first call, `create_all(checkfirst=True)` creates the schema. On subsequent calls it's
a no-op. `table.delete()` clears rows to maintain test isolation.

**Result:**

| Before | After | Delta |
|--------|-------|-------|
| 16.8s | 11.2s | **−33.3%** |

534/534 tests pass. Committed: `4470078`.

---

### Run 3 — Mock Health Check Network Probes ✅ KEPT

**Hypothesis:** `GET /api/health/detailed` probes all LLM provider `/models` endpoints
and attempts an SMTP socket connection. These calls add ~0.5s each in the test environment
(connection refused/timeout). 4 health auditor tests × this overhead = ~2s.

**Change:** Extended the `mock_llm_provider` autouse fixture to also patch:
- `trellis.agents.health_auditor.check_llm_providers` → `AsyncMock` returning valid `CheckResult` objects
- `trellis.agents.health_auditor.check_smtp` → sync mock returning standard "not configured" result

**Result:**

| Before | After | Delta |
|--------|-------|-------|
| 11.2s | 8.3s | **−25.9%** |

534/534 tests pass. Committed: `4648f72`.

---

## Final Result

| Stage | Duration | vs. Baseline |
|-------|----------|-------------|
| Baseline | 92.0s | — |
| After Run 1 (LLM mock) | 16.8s | −82% |
| After Run 2 (truncate) | 11.2s | −88% |
| After Run 3 (health mock) | **8.3s** | **−91%** |

**Total improvement: 92.0s → 8.3s — an 11× speedup.**

---

## State of `tests/conftest.py`

The fixture stack is clean and composable:

```
autouse: mock_llm_provider
  ├── patches OpenAICompatibleProvider.chat_completion (AsyncMock)
  ├── patches check_llm_providers (AsyncMock → CheckResult list)
  └── patches check_smtp (sync mock → CheckResult)

async fixture: client
  ├── create_all(checkfirst=True) — schema once
  ├── table.delete() × N — fast row truncation
  └── ASGITransport(app) with set_client_override
```

Tests needing real Ollama: mark with `@pytest.mark.no_llm_mock`.

---

## What's Next

Remaining test time (8.3s) is dominated by:
- Presidio NLP initialization: ~1.2s (one-time per session, unavoidable)
- PHI shield test corpus: ~0.5s (CPU-bound, no external calls)
- Slice/API DB setup overhead: ~3s residual

Next experiments to try:
1. **pytest-xdist** — with no shared mutable state, the suite could run in ~2-3s with `-n auto`
2. **Presidio warm-up fixture** — session-scoped fixture that pre-initializes the NLP engine before tests start, moving the 1.2s cost to setup rather than first test
3. **Dashboard bundle size** (Target 2) — separate autoresearch loop once test target is satisfied

---

— Forge ⚡
