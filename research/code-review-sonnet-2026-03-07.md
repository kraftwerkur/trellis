# Code Review: Trellis
**Date:** 2026-03-07
**Reviewer:** Reef (Autonomous — claude-sonnet-4-6)
**Commit:** cab3a57
**Scope:** Full codebase review — Python backend (5,719 LOC), Next.js dashboard, tests

---

## Executive Summary

Trellis is architecturally sound and impressively well-structured for an early platform. The single-file consolidation strategy is the right call — `api.py`, `gateway.py`, `router.py`, and `phi_shield.py` are all readable end-to-end. But there are **three showstoppers before this can be considered production-ready for a HIPAA environment**: (1) every management API endpoint is completely unauthenticated, (2) PHI defaults to "off" meaning patient data flows unprotected by default, and (3) full envelope payloads — potentially containing HL7/FHIR patient data — are persisted to the database unconditionally. Fix those three things before phase 2 of anything.

---

## Project Overview

- **Stack:** Python 3.12, FastAPI, SQLAlchemy async, SQLite (dev), Alembic, Next.js 15, Tailwind
- **Size:** 23 Python source files, 5,719 LOC backend; 4,437 LOC tests; ~1,000 LOC Next.js frontend
- **Test files:** 13 test files, ~300 tests total
- **Test Results (full suite):** 297 passed, 16 failed
  - 11 phi_shield failures — `pip` not available in venv, spaCy can't download `en_core_web_lg` model (Presidio NLP broken in this environment)
  - 4 slice2/slice3 failures — Ollama not running (expected in CI without local models)
  - **1 genuine environment issue, rest are infra-dependent failures**

---

## 1. Architecture

### 🟢 Three-layer design is clean and well-executed

Adapters → Platform Core → Agents is a defensible separation. Adapters really are dumb translators — the HL7, FHIR, Teams, and document adapters contain zero business logic. The Generic Envelope spec means you can add a new input type (email, Service Bus, CDC) without touching the core. This is the right call.

### 🟢 Single-file consolidation (Karpathy-style)

`api.py` (814 LOC), `gateway.py` (556 LOC), `router.py` (378 LOC), `phi_shield.py` (527 LOC). You can read each file top-to-bottom and understand the whole subsystem. No abstraction layers for their own sake. Good discipline.

### 🔴 CRITICAL: Zero authentication on management APIs

**The entire management plane is unauthenticated.** Anyone who can reach port 8100 can:
- Register a new agent and get an API key (`POST /api/agents`)
- Create API keys for any agent (`POST /api/keys`)
- Read the full audit trail (`GET /api/audit`)
- Read all cost data and agent configs (`GET /api/costs`, `/api/gateway/providers`)
- Delete agents and rules (`DELETE /api/agents/{id}`, `/api/rules/{id}`)

Only the LLM Gateway endpoint (`/v1/chat/completions`) requires authentication. The `authenticate_agent` dependency in `gateway.py` is never applied to any router in `api.py`. For a healthcare platform with a HIPAA mandate, this is a critical gap. The audit trail alone contains enough operational intelligence to map the entire AI infrastructure.

### 🔴 CRITICAL: CORS is wide open

```python
# main.py:106
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```

In production on Azure Container Apps, this means any website can make authenticated cross-origin requests to the API. Combined with no management auth, a CSRF attack could compromise the platform from a phishing link. Must be locked to specific origins before prod.

### 🟡 SQLite in production

The default `database_url = "sqlite+aiosqlite:///./trellis.db"` and there's no evidence this is overridden in the Azure deployment configuration. The roadmap lists "Azure SQL migration" as future work. With concurrent async requests, SQLite's write serialization will become a bottleneck. More importantly: SQLite has no network-accessible connection, so there's no way to inspect the database without exec access to the container. Not a dealbreaker for phase 1, but needs a timeline.

### 🟡 No streaming support

`body["stream"] = False` is hardcoded in `chat_completions` (gateway.py:481). All LLM responses buffer completely before returning. For complex medical document analysis prompts, users wait minutes with no feedback. Streaming is on the roadmap but the hardcoded `False` means even a client that requests streaming gets none.

### 🟡 `scorer.py` is dead code (843 lines)

The 23-dimension complexity scorer in `scorer.py` is imported nowhere in the main codebase. Zero uses. `gateway.py` has its own simpler `classify_complexity()` (30 lines, regex + token count) that actually gets called. `scorer.py` is a ported TypeScript file that never got wired up. Either integrate it or delete it — dead code in a security-critical codebase is confusing.

**Architecture Verdict:** Sound design with a clean separation of concerns. The showstopper is management plane auth — everything else is fixable in phase 2.

---

## 2. Code Quality

**Grade: B+**

### 🟢 Strengths

- Consistent async patterns throughout — no sync/async mixing surprises
- Error handling in dispatch paths is solid: timeouts, HTTP errors, and generic exceptions all have distinct handling with informative messages
- Rule engine condition operators are clean and composable
- `_SENTINEL` pattern in `router.py` for field resolution is clever and avoids `None` ambiguity

### 🟡 Pricing data duplication creates real inconsistency

Two pricing sources exist that will drift:

1. `MODEL_PRICING` in `gateway.py` (lines 395–408) — per-million-token pricing used by `calculate_cost()` for actual billing
2. `COSTS` dict in `api.py` `seed_default_routes()` — per-1k-token pricing stored in `ModelRoute` table for display

The `ModelRoute` table is **never used for cost calculation** — `calculate_cost()` only reads `MODEL_PRICING`. The dashboard's gateway routes page shows prices from `ModelRoute` which are 1000x different in units than what's actually being billed. Users configuring model routes via the UI have no effect on real cost tracking.

```python
# gateway.py:409 — actual billing uses MODEL_PRICING (per million)
pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
cost = (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000

# api.py:802 — ModelRoute stores per-1k (display only, never used in billing)
"gpt-4o": (0.005, 0.015),  # these are per-1k, not per-million
```

**Fix:** Either use `ModelRoute` for cost calculation (query it in `calculate_cost`) or rename `cost_per_1k_input` to signal it's display-only. The current state is misleading.

### 🟡 `dispatch_llm` bypasses budget enforcement

When an LLM-type agent processes an envelope via `router.py:dispatch_llm()`, it directly calls the provider without going through the gateway's budget check (`check_budget`), PHI shield, or proper auth pipeline. The `_log_gateway_cost` function logs cost after the fact, but:
- Budget is never checked before the call
- PHI shield is never applied
- Anomaly detection runs but budget enforcement doesn't

An LLM agent can exceed its budget cap indefinitely if routed via the event router rather than via `/v1/chat/completions`.

### 🟡 Module-level mutable globals

```python
# router.py
_client_override: httpx.AsyncClient | None = None  # test injection hook
_health_running = True  # health checker state
```

These are test seams and process state crammed into module globals. `_client_override` is particularly risky — a test that fails to clean up this override will corrupt subsequent test runs. The existing tests in `test_slice2.py` and `test_slice3.py` do appear to clean up properly, but this is fragile.

### 🟢 `secrets.token_urlsafe(32)` for key generation

Correct. 32 bytes of entropy from `os.urandom`. SHA-256 hashing for storage. The `trl_` prefix for identification. This is done right.

### 🔵 Comment left in production code

```python
# api.py:126
# BUG FIX: was "agent_registered", now correctly "agent_deleted"
```

Delete it. It's a commit message in the wrong place.

### 🟡 `seed_default_routes` runs on every startup

`seed_default_routes` in `api.py` checks `if count and count > 0: return` before seeding, which is fine. But it opens a new session via the lifespan context. If the seed fails partway through, you get partial data with no rollback. The `await db.commit()` at the end commits all or nothing — but if the process crashes between adds, you get inconsistency. Low probability, but worth noting for production.

---

## 3. Tests

### 🟢 Coverage is broad across happy paths

104 tests claimed in README; actual count is ~300 across 13 files. The slice structure maps well to the feature slices — `test_slice1.py` through `test_slice6_gaps.py` give good progression coverage. The adapter tests are thorough.

### 🔴 PHI Shield tests are completely broken in this environment

11 of 16 failures are phi_shield tests. The root cause: `pip` is not available in the `.venv` (it's a uv-managed venv), so when `_get_analyzer()` tries to download `en_core_web_lg` via `spacy`, it fails with `SystemExit: 1`. This means **the most security-critical component of a HIPAA platform has an untestable test suite** in the standard development environment.

The fix is either:
1. Pre-install `en_core_web_lg` in the venv: `uv run python -m spacy download en_core_web_lg`
2. Mock the analyzer in tests rather than testing the real NLP engine

### 🟡 Slice2/Slice3 LLM tests require live Ollama

`test_gateway_proxy_ollama`, `test_cost_events_logged`, `test_cost_summary`, `test_budget_cap_enforcement`, and `test_llm_agent_dispatch` all require Ollama running locally on port 11434. They fail with 502 in any CI environment without a local model server. These should be marked `@pytest.mark.integration` and skipped by default, or mocked.

### 🟡 No tests for unauthenticated access to management APIs

There is no test that verifies the management API rejects unauthenticated requests. Because there's no auth, such tests would pass for the wrong reason. This reflects the gap — once auth is added, a full set of 401/403 tests needs to be written.

### 🟡 No tests for PHI flowing into audit logs

Given that `EnvelopeLog` stores `envelope_data=envelope.model_dump()`, there should be a test verifying that HL7/FHIR envelopes with PHI are either redacted before storage or flagged. Currently nothing tests this path.

### 🟢 Rule engine tests are comprehensive

`test_slice4.py` and `test_slice6_gaps.py` cover the full operator set (`$gt`, `$lt`, `$regex`, `$not`, `$contains`, `$in`, `$exists`), fan-out routing, and edge cases. This is the strongest part of the test suite.

**Test Verdict:** The suite is adequate for business logic but has critical gaps in security-sensitive paths and doesn't run cleanly out of the box.

---

## 4. Performance

### 🟡 New httpx client per request

`OpenAICompatibleProvider.chat_completion()` and `dispatch_http()` both create a new `httpx.AsyncClient` for every call:

```python
async with httpx.AsyncClient(timeout=120.0) as client:
    resp = await client.post(...)
```

This means a new TCP connection (plus TLS handshake for HTTPS) per LLM request. At low volume this is fine. At meaningful throughput (dozens of concurrent requests), connection establishment overhead accumulates. The fix is a shared client with connection pooling — either a module-level `httpx.AsyncClient` or a FastAPI lifespan-managed one.

### 🟡 `_get_db_routes()` and `_get_agent_llm_config()` open rogue sessions

These functions in `gateway.py` open their own database sessions outside of the request-scoped session:

```python
async def _get_db_routes() -> dict[str, str]:
    async with async_session() as db:  # new session, not the request one
        ...
```

This means every gateway request opens 2 extra DB sessions in addition to the request session. With SQLite (single-writer), this creates lock contention. Cache these in memory with a short TTL — model routes don't change frequently.

### 🟡 `AuditEvent` table will grow unbounded

No TTL, no archival, no pagination limits beyond the query-level `limit` parameter. At enterprise scale with dozens of agents processing thousands of events daily, this table becomes a performance problem within months. Add an archival/retention policy.

### 🟡 `EnvelopeLog.envelope_data` is stored as JSON

Full envelope payloads as JSON in every row. For HL7 or large document envelopes, this can be tens of KB per row. At scale, this is both a storage and query performance issue. Consider storing only a summary + a reference, with full payload in blob storage.

### 🟢 Async throughout

No sync DB calls, no blocking I/O in hot paths. The async pattern is consistent and correct throughout.

---

## 5. Security

### 🔴 CRITICAL: PHI defaults to "off"

```python
# models.py:30
phi_shield_mode: Mapped[str] = mapped_column(String, default="off")
```

Every newly registered agent defaults to PHI shield disabled. This is backwards for a HIPAA platform. An agent processing HL7 admission events will send raw patient data to the LLM provider with zero interception unless an admin explicitly enables protection. The default should be `"audit_only"` at minimum, with `"full"` recommended and requiring explicit opt-out.

### 🔴 CRITICAL: PHI is persisted to `EnvelopeLog` without redaction

```python
# router.py:264
log = EnvelopeLog(envelope_data=envelope.model_dump(), ...)
```

The `envelope_data` field stores the full envelope as JSON. For HL7 ADT^A01 events, this includes patient name, DOB, MRN, SSN potentially, and other identifiers. The PHI shield only operates on LLM request/response content — it does not intercept the envelope storage path. Result: **patient data is being written to the SQLite database unconditionally**, regardless of phi_shield_mode.

### 🔴 Management plane has zero authentication

Covered in Architecture. Repeating here because it's also a security finding. There is no API key, no OAuth, no IP allowlist, no mutual TLS on any management endpoint. In Azure Container Apps with a public ingress, this is exploitable.

### 🟡 Audit event error messages may contain PHI

```python
# router.py:various
await emit_audit(db, "error", details={"error": f"Agent returned {e.response.status_code}: {e.response.text[:500]}"})
```

Error messages from HL7/FHIR parsers that fail mid-processing could contain patient data from the payload. Error messages are stored in `AuditEvent.details` as JSON. This should be sanitized — log the error type and position, not the raw payload text.

### 🟡 No input size limits on envelope endpoints

`/api/adapter/fhir` accepts `resource: dict` with no size validation. A malicious actor could POST a 100MB JSON payload to trigger memory pressure. FastAPI has no default body size limit. Add `Request` body size limiting middleware.

### 🟡 API key prefix stored in plaintext

`key_prefix: Mapped[str]` stores the first 12 characters of the key in plaintext for display purposes. This is a common pattern and generally acceptable, but if the prefix leaks (audit log, log aggregation), it reduces the effective search space for a brute-force attack slightly. Low severity, worth noting.

### 🟡 `validate_bot_token` in Teams adapter is HMAC-based

The Teams adapter uses HMAC validation (`validate_bot_token`), which is correct. But the app_password is passed as a constructor argument without any validation that it's non-empty. A Teams adapter with an empty password would accept any request silently.

### 🟢 API keys are hashed with SHA-256

Keys are never stored in plaintext. The hash comparison is done correctly — hash the incoming key, compare to stored hash. No timing oracle risk from Python's `==` on strings (SHA-256 outputs are fixed-length so no early exit).

### 🟢 PHI vault is properly ephemeral

`PhiVault` is created per-request and never serialized or persisted. The token→original mapping dies with the request. The audit trail logs detection counts and categories, never the actual PHI values. This is the right design.

**Security Verdict:** The PHI shield implementation is thoughtful and correct for what it covers. But the coverage gaps (management auth, PHI persisted to EnvelopeLog, "off" default) are not minor — they're HIPAA compliance failures if patient data flows through the system today.

---

## Top Issues (Priority Order)

| # | Severity | Category | Issue | Recommendation |
|---|----------|----------|-------|----------------|
| 1 | 🔴 Critical | Security | Management API has zero authentication | Add API key or OAuth2 middleware to all `api.py` routers; the gateway's `authenticate_agent` pattern is already there — extend it |
| 2 | 🔴 Critical | HIPAA | `EnvelopeLog` persists full envelope payload including PHI | Strip or hash PHI from `envelope_data` before storage, or apply PHI detection to envelope content before logging |
| 3 | 🔴 Critical | HIPAA | `phi_shield_mode` defaults to `"off"` | Change default to `"audit_only"` in models.py and schemas.py; require explicit opt-out |
| 4 | 🔴 Critical | Security | CORS `allow_origins=["*"]` in production | Lock to specific known origins in production config; use env var override |
| 5 | 🟡 Warning | Testing | PHI shield tests fail — spaCy model missing | `uv run python -m spacy download en_core_web_lg`; add to dev setup docs and CI |
| 6 | 🟡 Warning | Correctness | `ModelRoute` pricing never used in billing | Either wire `ModelRoute` into `calculate_cost()` or document it as display-only |
| 7 | 🟡 Warning | Security | `dispatch_llm` bypasses budget enforcement | Move budget check into `dispatch_llm` or route all LLM calls through the gateway API |
| 8 | 🟡 Warning | Performance | New httpx client per request | Create a shared `httpx.AsyncClient` in lifespan; inject via app state |
| 9 | 🟡 Warning | Performance | `_get_db_routes()` opens extra DB sessions per request | Cache model routes in memory (TTL: 60s); avoid per-request DB session overhead |
| 10 | 🟡 Warning | Code Quality | `scorer.py` (843 LOC) is dead code | Delete or integrate into `classify_complexity()` in gateway.py |
| 11 | 🟡 Warning | Reliability | Slice2/Slice3 tests fail without Ollama | Mark as `@pytest.mark.integration`, skip in standard CI |
| 12 | 🔵 Info | Ops | `dashboard/.env.production` has empty API URL | Set actual production URL; currently dashboard would connect to nothing |
| 13 | 🔵 Info | Code Quality | Audit log error messages may contain PHI | Sanitize error strings before storing in `AuditEvent.details` |
| 14 | 🔵 Info | Scalability | No `AuditEvent` retention/archival policy | Add TTL or archival migration before production load |

---

## Strengths

**The architecture is genuinely good.** The three-layer design is clean, the Generic Envelope spec is well-conceived, and the adapter pattern means you can add new input types without touching the core. The decision to consolidate into single files (api.py, gateway.py, etc.) was the right call — the codebase is readable.

**The LLM gateway is well-structured.** The `OpenAICompatibleProvider` abstraction elegantly handles Ollama, OpenAI, Groq, Google, and NVIDIA with one class. The `AnthropicProvider` translation layer is correct and doesn't leak provider-specific details into the calling code. The complexity classifier is simple and effective for a v1.

**The PHI vault design is sound.** Ephemeral, per-request, never persisted. Tokens are deterministic within a request (same PHI gets same token). Rehydration works correctly. The regex pattern library covers all 18 HIPAA Safe Harbor identifiers. The merge/deduplication of regex + Presidio results is handled properly (start-to-end sort, overlap detection). This is the most thought-through piece of the codebase.

**The Security Triage Agent is impressive.** It's a real tool-calling agent, not a prompt wrapper. The tool chain (CISA KEV lookup → CVSS enrichment → tech stack cross-reference → risk scoring → advisory generation) with graceful LLM enhancement degradation is exactly the pattern native agents should follow. The hardcoded Health First context (CISO escalation, Ivanti SM ticketing, CrowdStrike monitoring) makes it immediately useful rather than generic.

**The rule engine operator coverage is solid.** `$gt`, `$lt`, `$gte`, `$lte`, `$exists`, `$regex`, `$not`, `$contains`, `$in` covers the real-world routing cases without inventing a new query language. The `_SENTINEL` pattern for distinguishing missing fields from `None` is the right call.

---

## Recommended Next Steps

1. **[S] Fix PHI default** — Change `phi_shield_mode` default from `"off"` to `"audit_only"` in `models.py` and `schemas.py`. One line change, immediate HIPAA risk reduction. **(Do this today.)**

2. **[S] Fix CORS** — Change `allow_origins=["*"]` to an env-var-configurable list. Default to `["http://localhost:3000"]` in dev, require explicit production config.

3. **[M] Add management plane auth** — Implement a simple admin API key (separate from agent keys, stored as env var hash, checked via FastAPI dependency). Apply to all `api.py` routers. This doesn't need RBAC yet — a single admin key is sufficient for phase 1. Estimate: 1 day.

4. **[M] Fix EnvelopeLog PHI exposure** — Before `envelope_data=envelope.model_dump()`, run the envelope's text content through the PHI detector and redact. Alternatively, store only metadata (envelope_id, source_type, rule matched, agent dispatched) and drop full payload storage. Estimate: 1 day.

5. **[S] Fix the test environment** — Document `uv run python -m spacy download en_core_web_lg` as a required setup step. Mark Ollama-dependent tests as integration tests. Get the test suite to 0 failures on a clean checkout.

6. **[M] Delete or integrate `scorer.py`** — 843 lines of dead code. If the 23-dimension scorer is better than the 30-line `classify_complexity()`, replace it. If not, delete it. Either way, there should be one complexity classifier.

7. **[M] Shared httpx client** — Add an `httpx.AsyncClient` to FastAPI's lifespan, pass it via `app.state`. Inject into providers at request time. Estimate: half day.

8. **[L] Route `dispatch_llm` through budget enforcement** — The internal LLM dispatch path needs the same budget/PHI/cost checks as the external gateway. Easiest fix: make `dispatch_llm` call the gateway endpoint internally rather than calling providers directly. This requires the agent to have an API key, which is already true at registration time.

9. **[L] Model pricing single source of truth** — Either use `ModelRoute` in `calculate_cost()` (preferred — makes the UI meaningful) or remove `cost_per_1k_*` from `ModelRoute` and make it display-only with a clear comment.

10. **[L] AuditEvent retention** — Add an Alembic migration to add a `retained_until` column and a background task (or cron) to archive/delete old events. Define retention policy before production (HIPAA requires audit log retention for 6 years, so archival to cold storage, not deletion).

---

*Reviewed by Reef (autonomous). Model: claude-sonnet-4-6. Duration: single pass.*
