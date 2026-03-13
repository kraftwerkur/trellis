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

---

# Trellis Autoresearch — Session 2 Results

*Optimization target: Dashboard Bundle Size*
*Session date: 2026-03-13*
*Agent: Forge ⚡*

---

## Baseline

| Metric | Value |
|--------|-------|
| **Total JS bundle (raw)** | **2,036 KB** |
| **Total JS bundle (gzip)** | **568 KB** |
| Largest chunks | 3 × 386KB (recharts) |
| Build tool | Next.js 16.1.6 + Turbopack |
| Build type | Static export (`output: 'export'`) |

### Chunk Analysis

Turbopack creates **3 separate recharts chunks** for different route groups:
- `7eee2edf` (386KB / 102KB gzip) → `/` main page only
- `9b3b4d75` (386KB / 102KB gzip) → `/routing` page only  
- `66f3d504` (386KB / 102KB gzip) → shared by `/observatory`, `/health`, `/phi`, `/finops`

The remaining ~878KB is React DOM runtime (224KB), Next.js internals (151KB + 112KB), and page-specific chunks.

---

## Experiments

### Run 1 — Centralized Recharts Imports ❌ NO CHANGE

**Hypothesis:** Creating `src/lib/charts.ts` as a unified re-export module for all recharts components would force Turbopack to recognize recharts as a single shared dependency.

**Change:** Created `src/lib/charts.ts` exporting all recharts components; updated all 6 chart pages to import from `@/lib/charts` instead of `recharts` directly.

**Result:** Bundle unchanged at 2,036KB. Turbopack's chunking is based on route-group participation, not import paths. Even with centralized imports, each route group's unique module dependency pattern creates a separate chunk.

**Learning:** Turbopack deduplication works at the chunk-group level. The 3 separate recharts chunks are **by design** — Turbopack already deduplicates recharts across 4 pages into one shared chunk (`66f3d504`). The other two copies are for route groups with different dependency patterns.

---

### Run 2 — `optimizePackageImports` Config ❌ NO CHANGE

**Hypothesis:** Next.js `experimental.optimizePackageImports: ['recharts', 'lucide-react']` would force shared treatment.

**Change:** Added to `next.config.ts`.

**Result:** Bundle unchanged at 2,036KB. This config optimizes tree-shaking for barrel files (like `lucide-react`'s 1000+ icons), but doesn't affect Turbopack's route-group chunking behavior.

**Learning:** `optimizePackageImports` is about import scope, not chunk allocation.

---

### Run 3 — Package.json Dependency Audit ✅ KEPT (hygiene improvement)

**Hypothesis:** Unused packages might be contributing to bundle bloat.

**Findings:**
- `cmdk` — in `dependencies`, **never imported** → removed
- `@tanstack/react-table` — in `devDependencies`, **never imported** → removed  
- `radash` — in `devDependencies`, **never imported** → removed
- `recharts`, `lucide-react`, `class-variance-authority`, `clsx`, `tailwind-merge` — **runtime deps misclassified** as devDependencies → moved to `dependencies`

**Result:** Bundle size unchanged (tree-shaking already excluded unused packages). But dependency hygiene is now correct, preventing future confusion and potential installation issues in production-only deploys.

**Packages removed:** 3 (`cmdk`, `@tanstack/react-table`, `radash`)  
**Packages reclassified:** 5 (moved from devDeps to deps)

---

## Summary

| Metric | Baseline | After |
|--------|----------|-------|
| Raw bundle | 2,036 KB | 2,036 KB |
| Gzip bundle | 568 KB | 568 KB |
| Unused packages | 3 | 0 |
| Misclassified packages | 5 | 0 |

### Key Technical Finding: Turbopack Chunk Architecture

The 3×386KB recharts pattern is **correct Turbopack behavior**, not a bug:
- Turbopack optimizes for **per-route-group deduplication**, not global deduplication
- A user visiting only `/routing` downloads exactly one recharts chunk (102KB gzip)
- A user visiting only `/observatory` downloads one recharts chunk (same)
- These users never waste bandwidth on the other's chunk
- This is better than webpack's global vendor chunk (where every page loads ALL recharts)

**Real impact:** A user who visits BOTH `/routing` AND `/observatory` would download recharts twice (~204KB gzip). With a global webpack vendor chunk, they'd download it once (~80KB gzip). This is a real tradeoff — webpack wins for power users who traverse many sections; Turbopack wins for users who stay in one section.

### Recommended Next Steps for Bundle Reduction

1. **Replace routing-page radar chart with pure SVG** — RadarChart is the sole reason `/routing` gets its own 386KB recharts chunk. A pure SVG spider chart would eliminate that chunk entirely, saving 102KB gzip for routing-only users.
2. **Replace home-page sparklines with CSS/canvas** — The `/` page uses recharts for tiny 32px sparklines that could be replaced with a 200-line Canvas implementation, eliminating the third recharts chunk.
3. **Target: 1,264KB raw (−772KB, −38%)** if both above implemented.

---

*Previous session: Test Suite Speed (92s → 8.3s, 11x speedup)*

— Forge ⚡
