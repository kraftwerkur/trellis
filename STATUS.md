# Trellis Dashboard ↔ Backend Wiring Status

**Date:** 2026-02-28
**Purpose:** Gap analysis for connecting dashboard UI to real backend APIs.

---

## 1. Dashboard Pages

| # | Route | Page | Data Displayed |
|---|-------|------|----------------|
| 1 | `/` | **Overview** | Agent fleet status, activity feed, cost sparklines, health indicators, stat cards (agents online, events/min, PHI blocks, spend) |
| 2 | `/agents` | **Agent Registry** | Agent table (status, name, ID, department, type, framework, created), expandable rows with cost per agent |
| 3 | `/rules` | **Routing Rules** | Rule list sorted by priority, conditions in human-readable form, route targets, active/inactive toggle, fan-out badges |
| 4 | `/audit` | **Audit Log** | Filterable audit event table (by type, agent), trace expansion, timestamps, event details |
| 5 | `/finops` | **FinOps** | Cost timeseries chart (hour/day/week), agent cost breakdown bar chart, department pie chart, budget gauges, provider distribution, model breakdown |
| 6 | `/gateway` | **Gateway** | Gateway online status, provider list with request counts, model routing table, total cost/requests |
| 7 | `/phi` | **PHI Shield** | PHI detection stats by category/agent/day, recent detection events, per-agent PHI mode config, live PHI test tool |
| 8 | `/docs` | **Docs** | Static — architecture overview, quick-start curl examples, API reference links |

---

## 2. Backend API Endpoints (FastAPI)

All mounted under `/api/` prefix.

### Agents
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/agents` | ✅ |
| GET | `/api/agents/{agent_id}` | ✅ |
| POST | `/api/agents` | ✅ |
| PUT | `/api/agents/{agent_id}` | ✅ |
| DELETE | `/api/agents/{agent_id}` | ✅ |
| POST | `/api/agents/{agent_id}/sync` | ✅ |
| PUT | `/api/agents/{agent_id}/phi` | ✅ |

### Rules
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/rules` | ✅ |
| GET | `/api/rules/{rule_id}` | ✅ |
| POST | `/api/rules` | ✅ |
| PUT | `/api/rules/{rule_id}` | ✅ |
| DELETE | `/api/rules/{rule_id}` | ✅ |
| PUT | `/api/rules/{rule_id}/toggle` | ✅ |
| POST | `/api/rules/test` | ✅ |

### Envelopes / Routing
| Method | Path | Status |
|--------|------|--------|
| POST | `/api/envelopes` | ✅ |
| POST | `/api/adapter/http` | ✅ |
| GET | `/api/envelopes` | ✅ |

### Audit
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/audit` | ✅ (filterable: event_type, agent_id, trace_id, since, until) |
| GET | `/api/audit/trace/{trace_id}` | ✅ |

### Costs
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/costs` | ✅ (filterable: agent_id, trace_id, since, until) |
| GET | `/api/costs/summary` | ✅ |
| GET | `/api/costs/by-department` | ✅ |
| GET | `/api/costs/by-department/{dept}` | ✅ |
| GET | `/api/costs/trace/{trace_id}` | ✅ |
| GET | `/api/costs/timeseries` | ✅ (granularity: hour/day/week) |

### FinOps
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/finops/summary` | ✅ |

### Gateway Management
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/gateway/providers` | ✅ |
| GET | `/api/gateway/models` | ✅ |
| GET | `/api/gateway/stats` | ✅ |
| GET/POST/PUT/DELETE | `/api/gateway/routes` | ✅ |
| GET/PUT | `/api/gateway/agents/{id}/llm-config` | ✅ |

### PHI Shield
| Method | Path | Status |
|--------|------|--------|
| POST | `/api/phi/test` | ✅ |
| GET | `/api/phi/stats` | ✅ |

### API Keys
| Method | Path | Status |
|--------|------|--------|
| POST | `/api/keys` | ✅ |
| GET | `/api/keys` | ✅ |
| DELETE | `/api/keys/{key_id}` | ✅ |

### Health
| Method | Path | Status |
|--------|------|--------|
| GET | `/health` | ✅ |

---

## 3. Gap Analysis: Mock vs Real Data

### Pages Using ONLY Real API Calls (no mock fallback)
| Page | APIs Used | Status |
|------|-----------|--------|
| `/agents` | `api.agents.list()`, `api.costs.summary()` | ✅ **FULLY WIRED** |
| `/rules` | `api.rules.list()`, `api.agents.list()` | ✅ **FULLY WIRED** |
| `/audit` | `api.audit.list(params)`, `api.agents.list()` | ✅ **FULLY WIRED** |
| `/gateway` | `api.health()`, `api.costs.summary()`, `api.costs.byAgent()` | ✅ **FULLY WIRED** |
| `/docs` | None (static content) | ✅ **N/A** |

### Pages With Mock Fallback (real API attempted, falls back to mock on failure)
| Page | APIs Attempted | Mock Data Used When Backend Down | Issues |
|------|---------------|----------------------------------|--------|
| `/` (Overview) | `api.agents.list()`, `api.audit.list()`, `api.costs.summary()`, `api.costs.timeseries()`, `api.health()` | `MOCK_AGENTS` (6 fake agents), `MOCK_EVENTS` (10 fake events), `MOCK_COSTS`, `MOCK_COST_TIMESERIES` | Shows "DEMO MODE" banner when using mock. **Pattern is correct** — will work with live backend. |
| `/finops` | `api.costs.timeseries()`, `api.costs.summary()`, `api.gateway.stats()`, `api.costs.byAgent()` | `MOCK_TIMESERIES`, `MOCK_SUMMARY`, `MOCK_STATS` | Same pattern — shows "DEMO MODE" banner. **Will work with live backend.** |
| `/phi` | `api.phi.stats()`, `api.phi.agentConfigs()`, `api.phi.test()` | `MOCK_STATS` (347 detections, categories), `MOCK_AGENT_CONFIGS` (5 agents) | **Has a gap** — see below. |

---

## 4. Missing Backend Endpoints

### `/api/phi/agents` — **DOES NOT EXIST**
- **Dashboard expects:** `GET /api/phi/agents` → returns `AgentPhiConfig[]` (agent_id, name, phi_shield_mode)
- **Backend has:** No such endpoint. The `phi_shield_mode` field exists on the Agent model, and `PUT /api/agents/{id}/phi` can update it.
- **Fix:** Add a `GET /api/phi/agents` endpoint that queries all agents and returns `[{agent_id, name, phi_shield_mode}]`.

### `/api/phi/stats` — **EXISTS BUT INCOMPLETE**
- **Dashboard expects:** `PhiStatsResponse` with fields: `total_detections`, `by_category`, `by_agent`, `by_day`, `recent_events`
- **Backend returns:** `phi_stats.summary()` from `phi_shield.py` — need to verify this matches the expected shape.
- **Risk:** The `phi_stats` object is in-memory only (resets on restart). The dashboard types expect `recent_events[]` with `timestamp`, `agent_id`, `count`, `categories`, `mode`. This may not match what `phi_stats.summary()` returns.

---

## 5. Wiring Plan

### Already Working (no action needed)
These pages make real API calls and will display live data when the backend is running:
- **`/agents`** — fully wired
- **`/rules`** — fully wired
- **`/audit`** — fully wired
- **`/gateway`** — fully wired (derives provider/model stats from cost events)
- **`/docs`** — static

### Mock-Fallback Pages (work with backend, graceful degradation)
These pages already call real APIs and fall back to mock. They'll "just work" once the backend has data:
- **`/` (Overview)** — no code changes needed
- **`/finops`** — no code changes needed

### Gaps to Close

#### Gap 1: `GET /api/phi/agents` endpoint (backend)
**Effort:** ~15 min
```python
@phi_router.get("/agents")
async def phi_agent_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent))
    agents = result.scalars().all()
    return [{"agent_id": a.agent_id, "name": a.name, 
             "phi_shield_mode": a.phi_shield_mode or "off"} for a in agents]
```

#### Gap 2: Verify `phi_stats.summary()` response shape
**Effort:** ~15 min
- Check `trellis/phi_shield.py` → `PhiStats.summary()` return value
- Ensure it returns `{total_detections, by_category, by_agent, by_day, recent_events}`
- If not, either update the backend to match or update the dashboard types

#### Gap 3: Gateway page could use dedicated endpoints
**Current state:** Gateway page derives provider/model data by fetching ALL cost events from multiple agents — N+1 query pattern.
**Better:** Use the existing `GET /api/gateway/providers` and `GET /api/gateway/models` endpoints which already exist but aren't called by the dashboard.
**Effort:** ~30 min to update `gateway/page.tsx` to use `api.gateway.providers` and `api.gateway.models` instead of deriving from cost events.

#### Gap 4: FinOps page doesn't use `/api/finops/summary`
**Current state:** FinOps page assembles its own summary from `costs/summary` + `gateway/stats`.
**Opportunity:** The backend has a rich `GET /api/finops/summary` endpoint (spend today/week/month, top agents, top departments, avg cost per request) that isn't used.
**Effort:** ~30 min to add FinOps summary cards using this endpoint.

#### Gap 5: Dashboard has no CRUD UI for agents/rules
**Current state:** Agents and rules are display-only. The API client (`api.ts`) has `create`, `update`, `toggle` methods wired up, but no UI forms exist.
**Effort:** ~2-3 hours per page (add modals/forms for create agent, create rule, toggle rule)

---

## 6. Priority Order for Next Build Session

1. **Add `GET /api/phi/agents`** — 15 min, unblocks PHI page from mock
2. **Verify PHI stats shape** — 15 min, ensures PHI page renders correctly
3. **Refactor Gateway page** to use `/api/gateway/providers` + `/api/gateway/models` — 30 min, eliminates N+1
4. **Add FinOps summary endpoint usage** — 30 min, richer data
5. **Add rule toggle UI** (click the toggle switch → calls `api.rules.toggle()`) — 30 min, quick win
6. **Add agent/rule create forms** — 2-3 hours, completes CRUD loop

**Total estimated wiring time: ~4-5 hours** to go from mock/display-only to fully interactive with live data.
