# Trellis Code Review — Overnight Build
**Date:** 2026-03-08  
**Reviewer:** Reef  
**Scope:** Overnight additions — native agents, platform agents, tools, email output, load generator, and router/main/api changes  

---

## Executive Summary

**Grade: B+**

Solid, well-organized work for a single-night sprint. The agent architecture is consistent, the audit trail is genuinely comprehensive, and the decision to go "native" (no LLM, pure logic) for IT/HR/RevCycle was the right call — fast, deterministic, testable. The email output adapter is clean. The load generator is genuinely useful for load testing.

The gaps that'll bite you in production cluster around three themes:

1. **Auth is opt-in, not required** — no key set means open API. That's fine for dev but terrifying in prod, and there's no hard guard preventing deployment without keys.
2. **PHI in audit logs and envelope storage** — `EnvelopeLog.envelope_data` stores the full envelope. If it contains patient data, that's a HIPAA audit trail problem.
3. **Email is fire-and-forget in ways that could lose critical alerts** — `asyncio.ensure_future` with swallowed exceptions is not appropriate for CRITICAL priority notifications.

Nothing is a disaster. There's no injection-ready SQL, no hardcoded secrets, no obvious data exfiltration paths. The codebase is respectable. These are the things to fix before going beyond dev/staging.

---

## File-by-File Findings

### 1. `trellis/api.py` — Auth Dependencies ⚠️ HIGH

**What's good:** Clean dependency injection pattern. Two separate auth dependencies for management vs ingestion is the right separation. No plaintext key storage.

**Issues:**

**[P0] Auth silently disabled when env var is missing**
```python
async def require_management_auth(request: Request):
    key = os.environ.get("TRELLIS_MANAGEMENT_API_KEY")
    if not key:
        return  # dev mode — no auth required
```
The warning in `main.py` lifespan helps, but a misconfigured prod deployment (env var missing) silently exposes the full management API — agents, rules, keys, audit, everything. The warning only appears in logs at startup; someone reviewing the running system won't see it.

**Fix:** Add a `TRELLIS_ENV=production` (or similar) guard that turns the missing-key case into a 500 or forced-auth refusal. Or require explicit `TRELLIS_ALLOW_OPEN_AUTH=1` to enable dev mode.

**[P1] `keys_router` has no auth dependency**
```python
keys_router = APIRouter(prefix="/keys", tags=["keys"])
```
All other sensitive routers have `dependencies=[Depends(require_management_auth)]`. The keys router doesn't. Anyone can list active API keys (prefixes, not hashes, but still), create new keys, and revoke existing ones — no auth required, even when management auth is set.

**Fix:** Add `dependencies=[Depends(require_management_auth)]` to `keys_router`.

**[P1] Timing attack possible on key comparison**
```python
if auth == f"Bearer {key}" or api_key == key:
```
String comparison is not constant-time. For an internal platform this risk is lower, but if it ever faces the internet, this is exploitable. Use `secrets.compare_digest()`.

**[P2] `phi_router` has no auth dependency**
The `/phi/test` endpoint takes arbitrary text and runs PHI detection on it — this is fine for a test tool. But `/phi/agents` returns the PHI mode config for all agents with no auth. Low risk, but inconsistent.

**[P2] `_generate_api_key()` defined twice**
Same function appears in both the `agents_router` section and the `keys_router` section. DRY violation — if the token length or prefix changes, one copy gets out of sync.

---

### 2. `trellis/router.py` — Email Hook, Commit-Before-Dispatch ⚠️ HIGH

**What's good:** The commit-before-dispatch pattern (committing the pre-dispatch audit trail before the potentially-long LLM call) is genuinely smart — prevents DB lock contention during multi-second inference. The fan-out logic is clean. Audit coverage at every stage is solid.

**Issues:**

**[P1] `asyncio.ensure_future` for email is dangerous for CRITICAL alerts**
```python
asyncio.ensure_future(_maybe_send_email(dispatch_result, matched_rule, envelope))
```
If the event loop is closing (e.g., during graceful shutdown), `ensure_future` tasks are silently abandoned. For CRITICAL-priority security alerts, losing the email without any record is a compliance problem. Also, if `_maybe_send_email` itself raises an unexpected exception outside the `try/except`, the future's exception is never retrieved and Python will log "Task exception was never retrieved."

**Fix:** Use `asyncio.create_task()` and hold a reference, or at minimum log at ERROR level (not WARNING) when email fails for CRITICAL envelopes.

**[P1] `_maybe_send_email` imports private function from email module**
```python
from trellis.outputs.email import send_email_output, _extract_priority
```
Importing `_extract_priority` (private by convention) into router creates a hidden coupling. If `email.py` is refactored, this breaks silently.

**[P2] Post-dispatch audit only fires for `status == "success"`**
```python
if status == "success" and result_data:
    asyncio.ensure_future(_maybe_send_email(...))
```
This is correct behavior, but failed dispatches generate no email. For CRITICAL security alerts that fail dispatch (agent timeout, agent not found), ops gets nothing. Consider a fallback email on CRITICAL failures.

**[P2] `_log_gateway_cost` is called after `db.commit()`, then does another `db.commit()`**
This results in two commits per dispatched envelope (plus whatever `_dispatch_single` does). Not wrong, but adds DB round-trips. Could be unified.

**[P2] `$regex` operator in rule engine has no size/complexity limit**
```python
elif op == "$regex":
    if value is _SENTINEL or not isinstance(value, str) or not re.search(operand, value):
```
A malicious rule (or misconfigured one) with a ReDoS-vulnerable regex on a large payload field could cause significant latency. Consider `re.compile()` with a timeout or complexity limit, or validate regex patterns at rule creation time.

---

### 3. `trellis/main.py` — CORS, Auth Middleware, Lifespan ⚠️ MEDIUM

**What's good:** CORS is configurable via env var. Lifespan tasks are properly cancelled on shutdown. The health check loop uses an interruptible sleep pattern (checking `_health_running` each second) — nice touch.

**Issues:**

**[P0] CORS wildcard in default dev config**
```python
_cors_origins = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else ["http://localhost:8100", "http://localhost:3000"]
)
```
With `allow_credentials=True`, CORS is restrictive by default (localhost only) — that's actually correct behavior. But if someone sets `TRELLIS_CORS_ORIGINS=*`, the combination of `allow_credentials=True` + wildcard origin is rejected by browsers AND is a security misconfiguration. Add a guard that rejects `*` when `allow_credentials=True`.

**[P1] Dashboard catch-all intercepts POST requests**
```python
@app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"])
async def dashboard_catchall(path: str, request: Request):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(_resolve_static(path))
```
The comment says "Next.js RSC prefetch" but POST requests to arbitrary paths returning static HTML is unusual. If a client POSTs to `/envelopes` without the `/api/` prefix, it gets a silent 200 with HTML instead of a 404 or routing error. This could mask misconfigured clients.

**[P2] `_health_running` global is a threading antipattern in async code**
Using a global bool for loop control works here because it's single-threaded async, but it's fragile if the health checker ever moves to a thread. An `asyncio.Event` would be more idiomatic.

**[P2] No rate limiting on `/api/envelopes`**
The ingestion endpoint has auth (when configured) but no rate limiting. A compromised or misbehaving client can flood the router. The envelope cannon itself can demonstrate this. Consider adding a simple token-bucket middleware.

---

### 4. `trellis/agents/health_auditor.py` — Platform Agent ✅ GOOD

**What's good:** Clean separation between `run_audit()` (the logic) and `health_auditor_loop()` (the scheduler). Readable, well-structured. The scheduler correctly tracks `_last_run_day` to avoid double-firing on a given day.

**Issues:**

**[P2] `_last_run_day` is a local variable scoped to `health_auditor_loop`**
```python
async def health_auditor_loop() -> None:
    _last_run_day: int | None = None
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == _AUDITOR_HOUR and now.day != _last_run_day:
```
If the loop restarts (task cancelled and recreated), `_last_run_day` resets to `None`, causing a re-fire if the loop restarts during the scheduled hour. This is a restart-race condition. Low probability but worth noting.

**[P2] No audit event emitted for health auditor run results**
The auditor assesses the health of agents but doesn't write an `AuditEvent` for its own run. For HIPAA audit trail completeness, platform agent activity should itself be audited.

**[P2] `run_audit()` does not distinguish between "no agents" and "healthy system"**
If there are zero registered agents, `run_audit()` returns `status: completed` with an empty assessment. This would look like a clean bill of health in the dashboard when really the system is unconfigured.

---

### 5. `trellis/agents/audit_compactor.py` — Platform Agent ✅ GOOD

**What's good:** The "rehydrate-then-delete" compaction pattern is safe. Keeping summaries instead of deleting raw events outright is audit-trail-conscious. The configurable retention window via env var is the right approach.

**Issues:**

**[P1] HIPAA concern: envelope data in `EnvelopeLog` may contain PHI**
The compactor deletes `EnvelopeLog` records after summarizing them. If `EnvelopeLog.envelope_data` contains PHI (patient names, MRNs, etc. from FHIR/HL7 envelopes), you may be destroying the only audit record of who accessed what data. 

HIPAA requires audit logs for PHI access to be retained for **6 years**. A 30-day compactor that nukes `envelope_data` is a compliance risk.

**Fix:** Ensure PHI is redacted from `envelope_data` before logging (PHI Shield should do this pre-storage), OR extend the compactor retention for PHI-tagged envelopes, OR exclude PHI-containing logs from compaction.

**[P2] Compactor summary is stored in... where?**
The code builds a `summary` dict but I don't see it being persisted to a `CompactionSummary` model or audit event in the compactor loop itself. Need to verify the summary is written somewhere durable, not just logged.

**[P2] No dry-run mode for compactor**
Running the compactor manually (or accidentally triggering it via the agent's `process()` method) permanently deletes records. A `dry_run=True` flag that shows what *would* be compacted would prevent accidents.

---

### 6. `trellis/agents/rule_optimizer.py` — Platform Agent ✅ GOOD

**What's good:** Read-only by design (explicitly documented). Clean analysis structure. The overlap detection logic (same conditions → different priorities) is genuinely useful and not trivial to get right. Good work on the utilization ranking.

**Issues:**

**[P2] Condition overlap detection uses naive string key**
```python
def _cond_key(conditions: dict) -> str:
    return str(sorted(conditions.items()))
```
`sorted()` on dict items sorts by key, but nested dict values aren't deeply sorted. Two rules with `{"metadata.priority": {"$in": ["HIGH", "CRITICAL"]}}` and `{"metadata.priority": {"$in": ["CRITICAL", "HIGH"]}}` would not be detected as overlapping. Use `json.dumps(conditions, sort_keys=True)` for a stable key.

**[P2] No on-demand trigger via API**
The optimizer only runs on schedule (nightly at 2 AM) or when the `RuleOptimizerAgent` is dispatched via envelope. There's no admin API endpoint to trigger it manually (useful for post-config-change analysis). The `process()` method exists but requires a matching routing rule to invoke it.

**[P2] `_OPTIMIZER_HOUR` is in UTC; documentation doesn't say so**
If ops reads `TRELLIS_RULE_OPTIMIZER_HOUR=2` as "2 AM local time" they'll be surprised. Document that this is UTC in the env var name or description. Same issue in `health_auditor.py` and `audit_compactor.py`.

---

### 7. `trellis/agents/tools.py` — Agent Tools ✅ GOOD

**What's good:** Self-contained, no external dependencies. Fuzzy matching for tech stack lookup is practical and well-implemented. The revenue cycle denial code library is comprehensive and accurate. Risk scoring formula is documented inline. HR regulatory flag logic is correct (workers comp as CRITICAL is legally accurate — 24-hour reporting requirement).

**Issues:**

**[P1] Tech stack loaded from disk on first call, then cached globally**
```python
_tech_stack: list[dict] | None = None

def _load_tech_stack() -> list[dict]:
    global _tech_stack
    if _tech_stack is None:
        with open(_DATA_DIR / "tech_stack.json") as f:
            _tech_stack = json.load(f)["systems"]
    return _tech_stack
```
This is a synchronous file read called from an async context (the agents call tools from `async def process()`). In an async application, blocking I/O on the event loop is bad. It only blocks once (cached after), but on a cold start under load, multiple concurrent requests could all hit the uncached path simultaneously — not thread-safe in CPython's GIL sense, though functionally okay.

**Fix:** Pre-load the tech stack at module import time, or use `asyncio.get_event_loop().run_in_executor()` for the load. Simplest: just load at module level.

**[P2] `classify_ticket` falls back to "application" category silently**
```python
if not scores:
    return {"category": "application", "subcategory": "general", "keywords": []}
```
A blank or unrecognizable ticket description silently becomes "App Support." No log, no signal. The fallback category should at least be logged as a classification miss for analytics.

**[P2] `check_cisa_kev` is a stub**
```python
def check_cisa_kev(cve_id: str) -> dict:
    return {
        "cve_id": cve_id,
        "in_kev": None,  # None = unknown (no local cache yet)
        ...
    }
```
This is clearly documented as a stub, so it's not a bug — but it means the security triage agent is making risk decisions without knowing if a CVE is actively exploited in the wild. The KEV status is one of the most important factors for patching priority. Needs a real implementation (CISA publishes a free JSON feed).

**[P2] `calculate_risk_score` returns score > 100 if inputs are extreme**
```python
raw = base * exploit_mult * exposure_mult * crit_mult * 100
composite = min(100.0, round(raw, 1))
```
The `min(100.0)` clamp is correct. But there's no `max(0.0)` clamp — a CVSS score of 0 with all multipliers applied returns 0.0, which is fine. Just noting it's only clamped on the high end; a CVSS < 0 (invalid input) would return negative. Add input validation on `cvss`.

---

### 8. `trellis/agents/it_help.py`, `sam_hr.py`, `rev_cycle.py` — Native Agents ✅ GOOD

All three follow an identical pattern: parse → classify → assess → assign. The consistency is excellent — reading one teaches you all three.

**[P2] Payload parsing duplication across all three agents**
```python
if hasattr(envelope, "model_dump"):
    env_dict = envelope.model_dump()
elif isinstance(envelope, dict):
    env_dict = envelope
else:
    env_dict = {"payload": {}}
payload = env_dict.get("payload", {})
payload_data = payload.get("data", {}) if isinstance(payload, dict) else {}
merged = {**payload_data, **payload}
```
This exact block appears in all three agents. Extract to a utility function in `trellis/agents/base.py` or `tools.py`. If the envelope schema changes, three places break instead of one.

**[P2] `_identify_systems` in `it_help.py` splits on whitespace**
```python
search_terms = keywords + description.split()
```
Single-word splitting generates a lot of noise — common words like "the", "is", "at" all get passed to `lookup_tech_stack`. The `if len(term) < 3: continue` guard helps but "SAP", "VM", "DB" would still pass. Consider a stopword filter or only pass known product-like terms.

**[P2] `rev_cycle.py` timely filing check assumes days_aged=0 means "fresh"**
A case with `days_aged=0` that actually has `timely_filing_deadline=90` returns no alert. But `0` might mean "unknown" vs. "filed today." A `None` check would be safer than treating `0` as "definitely fine."

**[P2] No input length validation on description fields**
A maliciously crafted envelope with a 100MB `description` field would cause the keyword-scanning loops to run for a very long time. Add a `description = description[:5000]` guard in `_parse_ticket`/`_parse_case`.

---

### 9. `trellis/outputs/email.py` — Email Output Adapter ✅ GOOD

**What's good:** Clean separation of SMTP (sync) and async caller. The `run_in_executor` pattern for SMTP is correct. The HTML templates are readable and production-quality. Priority-based color coding in the security template is a nice touch.

**Issues:**

**[P1] XSS risk in generic HTML template**
```python
html = f"""...
  <pre ...>{text}</pre>
  ...
  <strong>Agent:</strong> {agent}<br><strong>Rule:</strong> {rule}
"""
```
`text`, `agent`, and `rule` are inserted directly into HTML without escaping. If an attacker can control envelope payload text (e.g., via a malicious webhook), they can inject HTML into the email. In a healthcare context, phishing via injected HTML in internal emails is a real risk.

**Fix:** `from html import escape` and wrap all user-controlled values in `escape()`.

**[P1] Same XSS risk in security template**
`exec_summary`, `cve_id`, `title`, and table cell values from `affected_systems` are all unescaped. A CVE description from NVD could theoretically contain `<script>` tags (unlikely but possible with adversarial data).

**[P2] SMTP credentials handling**
```python
host = os.environ.get("TRELLIS_SMTP_HOST", "smtp.gmail.com")
password = os.environ.get("TRELLIS_SMTP_PASSWORD", "")
```
No validation that password is set before attempting login. A startup with missing credentials will fail silently on the first email (exception is caught and logged as WARNING). Consider a startup check that warns if SMTP config is incomplete — same pattern as the API key warning in `main.py`.

**[P2] No email queuing/retry**
If SMTP is temporarily down, the email is lost. For CRITICAL alerts this matters. Even a simple in-memory retry queue with 3 attempts + backoff would help.

**[P2] `asyncio.get_event_loop()` is deprecated in Python 3.10+**
```python
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, _send_smtp, to, subject, html)
```
Use `asyncio.get_running_loop()` instead. `get_event_loop()` generates a deprecation warning in Python 3.10+ when called outside the main thread.

---

### 10. `tools/envelope-cannon.py` — Load Generator ✅ GOOD

This is a genuinely excellent load generator. The NVD integration with rate limiting, retry with backoff, and page pagination is solid. The synthetic templates are realistic and healthcare-domain-accurate.

**Issues:**

**[P1] Envelope cannon has no auth header support**
```python
async with httpx.AsyncClient(
    headers={"User-Agent": "trellis-envelope-cannon/1.0"},
    ...
) as client:
```
No `--api-key` argument. Once ingestion auth is enabled in prod, the cannon can't be used to test it without code changes. Add `--api-key` CLI argument that adds the `X-Api-Key` header.

**[P2] `source_type: "cisa_kev"` for NVD data is misleading**
NVD ≠ CISA KEV. The NVD is the vulnerability database; CISA KEV is the subset of exploited vulnerabilities. These are different sources. The envelope's `source_type` should be `"nvd"`. The routing rules presumably key off this field.

**[P2] `envelope.pop("_label", ...)` mutates the envelope dict**
```python
label = envelope.pop("_label", envelope["envelope_id"][:8])
target_hint = envelope.pop("_target_hint", "?")
priority = envelope.pop("_priority", "NORMAL")
```
Mutating the envelope dict before sending removes internal metadata, which is fine. But if `fire_batch` is ever called with re-usable envelope objects (e.g., in a replay scenario), they'd be corrupted after the first fire. Use `.get()` + a copy, or clearly document that envelopes are consumed.

**[P2] Mixed mode split doesn't guarantee total count**
```python
nvd_count = max(1, int(args.count * 0.40))
it_count = max(1, int(args.count * 0.35))
hr_count = args.count - nvd_count - it_count
```
For small `--count` values (e.g., 3), `max(1, int(3*0.40))` = 1, `max(1, int(3*0.35))` = 1, `hr_count = 1`. That works. But for `--count 2`, you'd get `nvd=1, it=1, hr=0`. For `--count 1`, `hr_count = -1`. No negative-count guard.

---

## Recommended Fixes

### P0 — Fix Before Any External Exposure

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `api.py` | Auth silently disabled when env var missing | Add `TRELLIS_ENV` guard or require explicit opt-in for dev mode |
| 2 | `main.py` | CORS `*` + `allow_credentials=True` possible misconfiguration | Validate and reject wildcard origin when credentials enabled |

### P1 — Fix Before Production

| # | File | Issue | Fix |
|---|------|-------|-----|
| 3 | `api.py` | `keys_router` has no auth dependency | Add `dependencies=[Depends(require_management_auth)]` |
| 4 | `api.py` | Timing attack on key comparison | Use `secrets.compare_digest()` |
| 5 | `router.py` | `asyncio.ensure_future` drops CRITICAL email tasks | Use `asyncio.create_task()` + hold reference |
| 6 | `router.py` | Imports private `_extract_priority` from email module | Make `_extract_priority` public or move the logic |
| 7 | `audit_compactor.py` | PHI in `envelope_data` may be destroyed before 6-year HIPAA retention | Verify PHI Shield redacts before storage; exempt PHI-tagged logs from compaction |
| 8 | `outputs/email.py` | XSS in HTML templates (both security and generic) | Wrap all user-controlled values in `html.escape()` |
| 9 | `tools/envelope-cannon.py` | No auth header support for protected endpoints | Add `--api-key` CLI argument |

### P2 — Fix Before Scale

| # | File | Issue | Fix |
|---|------|-------|-----|
| 10 | `api.py` | `_generate_api_key` defined twice | Consolidate to one function |
| 11 | `router.py` | `$regex` with no ReDoS protection | Validate regex at rule creation; add per-match timeout |
| 12 | `main.py` | No rate limiting on ingestion endpoint | Add token-bucket middleware |
| 13 | `tools.py` | Sync file I/O (`_load_tech_stack`) on first async call | Pre-load at module level |
| 14 | `tools.py` | `check_cisa_kev` is a stub | Implement CISA KEV JSON feed integration |
| 15 | `agents/*.py` | Payload parsing block duplicated 3x | Extract to `parse_envelope_payload()` utility |
| 16 | `agents/*.py` | No input length limit on description | Add `[:5000]` truncation guard |
| 17 | `outputs/email.py` | `asyncio.get_event_loop()` deprecated | Use `asyncio.get_running_loop()` |
| 18 | `outputs/email.py` | No SMTP retry on transient failure | Add simple retry loop with backoff |
| 19 | `rule_optimizer.py` | Condition key not deeply stable (nested dicts) | Use `json.dumps(conditions, sort_keys=True)` |
| 20 | `rule_optimizer.py` | UTC hour not documented in env var | Add `_UTC` suffix to env var name or document in README |
| 21 | `envelope-cannon.py` | `source_type: "cisa_kev"` for NVD data is wrong | Change to `"nvd"` |
| 22 | `envelope-cannon.py` | Negative `hr_count` possible for small `--count` | Add `max(0, ...)` guard |

---

## What's Good

Worth calling out explicitly — a lot of this is genuinely solid:

- **Consistent agent architecture.** All three native agents follow the same pattern. Reading one teaches you all three. This is how you build a maintainable multi-agent platform.

- **Commit-before-dispatch in `router.py`.** Smart. Pre-committing the audit trail before the LLM call prevents DB lock contention during multi-second inference. This is the kind of thing you only figure out after getting burned by it.

- **Audit trail breadth.** `rule_matched` → `agent_dispatched` → `agent_responded` → `tool_call` is comprehensive. Most platforms don't audit at this granularity.

- **No LLM for triage agents.** IT/HR/RevCycle are pure logic. Faster, cheaper, deterministic, testable. Right call. Save LLM budget for where it actually adds value.

- **Revenue cycle denial code library.** CO-4, CO-16, CO-45, CO-97, PR-1, PR-2, CO-29, CO-50, OA-23 — with root causes and resolution steps. This is real RCM domain knowledge, not made-up codes.

- **HR regulatory category handling.** Workers comp as CRITICAL (24-hour legal requirement) and FMLA/ADA as automatic HIGH is legally accurate. Someone did their homework.

- **Load generator quality.** The NVD integration with proper rate limiting, retry, and pagination is solid. The synthetic templates are realistic. The stats summary is clear and actionable.

- **Email adapter is non-blocking and non-fatal.** Errors are logged but don't propagate. Correct behavior for an output side-effect that shouldn't break core routing.

- **PHI Shield exists.** The fact that there's a phi_router with a `/test` endpoint and per-agent mode configuration shows the architecture is HIPAA-aware. Now it needs to be wired into the storage path.

---

## Testing Gaps

Current status: envelope cannon exists, which is great for integration/load testing. But no unit tests spotted for:

- Rule engine condition matching (`_match_condition`, `_resolve_field`) — this is the most logic-dense, security-critical code in the codebase and has no tests.
- Native agent classification logic — easy to unit test, high value.
- PHI detection/redaction — needs property-based tests with known PHI patterns.
- Email template rendering — at minimum, smoke test that templates render without exceptions.
- Auth dependency behavior (key present vs. missing) — needs both happy and sad path tests.

Recommend adding pytest fixtures that mock the DB and test the rule engine in isolation first. It's the core of the platform.

---

*Review complete. ~ 1,150 lines reviewed across 12 files.*
