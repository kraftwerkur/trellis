# Trellis Optimization Engine

*Architecture design by Atlas 🏗️ — 2026-03-12*

---

## What It Is

The Optimization Engine is a product module that brings autoresearch-style
experimentation loops into healthcare operations. It lets clinical and ops teams
run controlled experiments on agent behavior — notification timing, prompt wording,
workflow step order — measure real outcomes, and automatically keep what works
while reverting what doesn't.

**Core insight:** Healthcare ops teams already run experiments informally ("let's
try paging the charge nurse 30 minutes earlier"). The Optimization Engine makes
those experiments systematic, measurable, and reversible.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Trellis API Layer                             │
│  POST /optimization/experiments  ← create experiment               │
│  POST /optimization/experiments/{id}/run  ← start loop             │
│  GET  /optimization/experiments/{id}  ← status + results           │
│  POST /optimization/experiments/{id}/approve  ← human gate         │
│  POST /optimization/experiments/{id}/rollback  ← manual revert     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │      Experiment Orchestrator       │
              │  - Manages experiment lifecycle    │
              │  - Schedules variant activation    │
              │  - Triggers metric collection      │
              │  - Applies keep/revert decisions   │
              └────────────────┬──────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       │                       │                       │
┌──────▼──────┐     ┌──────────▼──────┐     ┌─────────▼────────┐
│  Variant    │     │  Metric         │     │  Change          │
│  Manager    │     │  Collector      │     │  Executor        │
│             │     │                 │     │                  │
│ Stores A/B  │     │ Polls outcome   │     │ Applies config   │
│ config      │     │ metrics from    │     │ changes to       │
│ snapshots   │     │ agents/audit    │     │ agents/rules     │
│ for rollback│     │ logs            │     │ via API          │
└─────────────┘     └─────────────────┘     └──────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │         Approval Gateway           │
              │  Human-in-the-loop for any change  │
              │  above risk threshold. Slack/Teams │
              │  integration for approval requests │
              └───────────────────────────────────┘
```

### Component Responsibilities

**Experiment Orchestrator** — The core loop. Takes an experiment spec, runs the
control period, activates variant(s), collects metrics, evaluates statistical
significance, and makes a keep/revert recommendation. Never auto-applies a "keep"
decision without passing through the Approval Gateway if risk_level > "low".

**Variant Manager** — Captures a deep snapshot of current agent/rule configuration
before any change. This is the rollback target. Stored in DB, not just in-memory,
so rollbacks survive server restarts.

**Metric Collector** — Polls structured data from Trellis audit logs, agent response
times, and task completion events. Can also ingest metrics from external systems
(Epic Tapestry for completion rates, UKG for scheduling accuracy) via webhook.

**Change Executor** — Executes the actual variant change via the Trellis API itself
(eating our own dog food). Changes agent prompts, rule weights, notification timing
offsets, workflow step ordering — anything the API supports.

**Approval Gateway** — Any change classified as risk_level "medium" or "high" pauses
for explicit human approval before being applied. Sends a Teams/Slack message with
the proposed change, expected impact, and approve/reject buttons.

---

## API Design

### Experiment Object

```http
POST /api/optimization/experiments
Content-Type: application/json

{
  "name": "Earlier bed-ready notification",
  "description": "Notify charge nurse 45min before discharge instead of 30min",
  "target_metric": "bed_turnover_minutes",
  "direction": "lower",
  "baseline_period_hours": 24,
  "measurement_period_hours": 72,
  "min_sample_size": 30,
  "risk_level": "medium",
  "requires_approval": true,
  "change": {
    "type": "agent_prompt",
    "agent_id": "bed-mgmt-agent-uuid",
    "field": "notification_offset_minutes",
    "control_value": 30,
    "variant_value": 45
  },
  "rollback_trigger": {
    "metric": "bed_turnover_minutes",
    "threshold": 1.15,
    "comparison": "percent_increase_over_baseline"
  },
  "tags": ["bed-management", "q2-2026"]
}
```

**Response:**
```json
{
  "id": "exp_a1b2c3",
  "status": "draft",
  "created_at": "2026-03-12T21:00:00Z",
  "approval_required": true,
  "approval_status": "pending"
}
```

---

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/optimization/experiments` | Create experiment |
| `GET` | `/api/optimization/experiments` | List experiments (filterable by status, tag) |
| `GET` | `/api/optimization/experiments/{id}` | Get experiment + current results |
| `PATCH` | `/api/optimization/experiments/{id}` | Update draft experiment |
| `DELETE` | `/api/optimization/experiments/{id}` | Delete draft (not running) |
| `POST` | `/api/optimization/experiments/{id}/run` | Start experiment loop |
| `POST` | `/api/optimization/experiments/{id}/pause` | Pause (keeps current state) |
| `POST` | `/api/optimization/experiments/{id}/approve` | Human approves pending change |
| `POST` | `/api/optimization/experiments/{id}/reject` | Human rejects pending change |
| `POST` | `/api/optimization/experiments/{id}/rollback` | Immediate manual rollback |
| `GET` | `/api/optimization/experiments/{id}/metrics` | Time-series metric data |
| `GET` | `/api/optimization/experiments/{id}/audit` | Full change/event log |
| `GET` | `/api/optimization/summary` | Aggregate gains across all kept experiments |
| `POST` | `/api/optimization/metrics/ingest` | External metric webhook endpoint |

---

### Experiment Run Response

```json
{
  "id": "exp_a1b2c3",
  "name": "Earlier bed-ready notification",
  "status": "measuring_variant",
  "phase": {
    "name": "variant",
    "started_at": "2026-03-13T06:00:00Z",
    "ends_at": "2026-03-16T06:00:00Z",
    "samples_collected": 18,
    "samples_needed": 30
  },
  "metrics": {
    "control": {
      "mean": 68.4,
      "std": 12.1,
      "sample_size": 45
    },
    "variant": {
      "mean": 61.2,
      "std": 11.8,
      "sample_size": 18
    },
    "delta_pct": -10.5,
    "p_value": 0.083,
    "significance_reached": false
  },
  "risk_flags": [],
  "rollback_triggered": false,
  "approval_status": "approved",
  "approved_by": "eric.obrien@hf.org",
  "approved_at": "2026-03-13T05:48:00Z"
}
```

---

## Data Model

```sql
-- Core experiment record
CREATE TABLE optimization_experiments (
    id              TEXT PRIMARY KEY,            -- exp_<ulid>
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
                    -- draft | pending_approval | running | measuring_baseline
                    -- | measuring_variant | pending_keep_approval | kept | reverted
                    -- | paused | failed
    target_metric   TEXT NOT NULL,
    direction       TEXT NOT NULL,              -- lower | higher
    risk_level      TEXT NOT NULL DEFAULT 'low', -- low | medium | high
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timing
    baseline_period_hours   INTEGER NOT NULL DEFAULT 24,
    measurement_period_hours INTEGER NOT NULL DEFAULT 72,
    min_sample_size         INTEGER NOT NULL DEFAULT 30,
    baseline_started_at     TIMESTAMP,
    variant_started_at      TIMESTAMP,
    completed_at            TIMESTAMP,

    -- Change spec (JSON)
    change_spec     JSONB NOT NULL,             -- {type, agent_id, field, control_value, variant_value}
    control_snapshot JSONB,                     -- full config snapshot before change (for rollback)

    -- Results
    control_mean    FLOAT,
    control_std     FLOAT,
    control_n       INTEGER,
    variant_mean    FLOAT,
    variant_std     FLOAT,
    variant_n       INTEGER,
    p_value         FLOAT,
    delta_pct       FLOAT,
    outcome         TEXT,                       -- kept | reverted | inconclusive

    -- Rollback config
    rollback_trigger JSONB,

    -- Approval
    approval_status TEXT DEFAULT 'not_required', -- not_required | pending | approved | rejected
    approved_by     TEXT,
    approved_at     TIMESTAMP,
    rejected_reason TEXT,

    -- Metadata
    tags            TEXT[],
    created_by      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Individual metric observations
CREATE TABLE optimization_metric_observations (
    id              BIGSERIAL PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES optimization_experiments(id),
    phase           TEXT NOT NULL,              -- baseline | variant
    metric_name     TEXT NOT NULL,
    value           FLOAT NOT NULL,
    observed_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    source          TEXT,                       -- audit_log | webhook | manual
    reference_id    TEXT                        -- links to source record
);

-- Event/audit log for the experiment itself
CREATE TABLE optimization_experiment_events (
    id              BIGSERIAL PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES optimization_experiments(id),
    event_type      TEXT NOT NULL,
                    -- created | started | baseline_complete | variant_activated
                    -- | approval_requested | approved | rejected | kept | reverted
                    -- | rollback_triggered | paused | failed
    actor           TEXT,                       -- system | user email
    details         JSONB,
    occurred_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Cumulative improvement registry (kept experiments)
CREATE TABLE optimization_gains (
    id              BIGSERIAL PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES optimization_experiments(id),
    metric_name     TEXT NOT NULL,
    unit            TEXT,
    baseline_mean   FLOAT NOT NULL,
    final_mean      FLOAT NOT NULL,
    delta_abs       FLOAT NOT NULL,
    delta_pct       FLOAT NOT NULL,
    kept_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    category        TEXT                        -- bed-management | documentation | etc.
);
```

---

## Dashboard Wireframe

```
┌──────────────────────────────────────────────────────────────────────────┐
│  🧪 Optimization Engine                           [+ New Experiment]     │
├──────────────────────────────────────────────────────────────────────────┤
│  CUMULATIVE GAINS (All Kept Experiments)                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ Bed Turnover │  │ Prior Auth   │  │ Doc Complete │  │ Scheduling  │ │
│  │ ↓ 12.3 min  │  │ ↑ 8% rate   │  │ ↑ 23% rate  │  │ ↓ 4.1 hrs  │ │
│  │ avg/room    │  │ approval     │  │             │  │ open gaps   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
├──────────────────────────────────────────────────────────────────────────┤
│  ACTIVE EXPERIMENTS                                                      │
│                                                                          │
│  ● Earlier Bed-Ready Notification         [measuring_variant]  Day 2/3  │
│    bed_turnover_minutes  ↓10.5% (prelim)  p=0.083  n=18/30             │
│    ⚠ Pending final approval before keep                                 │
│    [View Details]  [Rollback Now]                                        │
│                                                                          │
│  ● Prior Auth Prompt Rewording            [measuring_baseline] Day 1/1  │
│    prior_auth_approval_rate  collecting baseline...  n=7/30             │
│    [View Details]  [Pause]                                               │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  EXPERIMENT HISTORY        [Filter: All ▾]  [Date: Last 90d ▾]          │
│                                                                          │
│  ✓ KEPT    Discharge summary timing shift      -8.2 min bed turnover    │
│  ✗ REVERTED Aggressive reminder cadence        +6% patient complaints   │
│  ✓ KEPT    Prior auth pre-fill from Epic       +14% approval rate       │
│  ✗ REVERTED Shorter notification window        rollback triggered auto  │
│  ✓ KEPT    Parallel bed assignment ping        -4.1 min turnover        │
│                                                                          │
│  [Load more...]                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  PENDING APPROVALS   🔴 1 waiting                                        │
│                                                                          │
│  Earlier Bed-Ready Notification — ready to keep                         │
│  Change: notification_offset_minutes 30 → 45                            │
│  Impact: -10.5% bed turnover time (p=0.041, n=47)                       │
│  Risk: MEDIUM  │  Approved by: ——  │  Expires in: 23h                  │
│  [Approve ✓]  [Reject ✗]  [Request More Data]                           │
└──────────────────────────────────────────────────────────────────────────┘
```

**Detail View** (per experiment):
- Header: name, status badge, risk level, approval status
- Metric chart: time-series with control/variant phases marked, baseline mean line
- Stats panel: control vs. variant means, delta %, p-value, confidence interval
- Change details: what changed, before/after values
- Event timeline: full audit trail from creation to outcome
- Rollback button: always visible, requires confirmation dialog

---

## Healthcare Use Cases

### 1. Bed Turnover Optimization
**Problem:** Average 68 minutes from discharge order to next patient admission.
**Experiment:** Vary notification timing (30 → 45 min advance notice to EVS and charge nurse).
**Metric:** `bed_ready_minutes` — time from discharge order to bed marked clean/available.
**Source:** Epic ADT events ingested via FHIR subscription.
**Expected gain:** 8–15% reduction. Small timing shifts have outsized impact on throughput.

### 2. Clinical Documentation Completion
**Problem:** Attending notes often incomplete at shift change, creating handoff risk.
**Experiment:** Adjust the wording and timing of AI documentation prompts.
**Metric:** `documentation_completion_rate` — % of notes complete before shift end.
**Source:** Epic audit events (note signed timestamp vs. shift end).
**Expected gain:** 15–25% improvement in on-time completion.

### 3. Prior Authorization Approval Rate
**Problem:** ~35% of prior auth submissions require additional info, adding 3–5 days.
**Experiment:** Modify the rev_cycle agent's pre-submission data enrichment prompts
to pull more supporting clinical context from Epic before submitting.
**Metric:** `prior_auth_first_pass_rate` — % approved without additional info requests.
**Source:** Webhook from payer portal or manual data entry.
**Expected gain:** 10–20% improvement in first-pass approval.

### 4. Scheduling Gap Reduction
**Problem:** Open scheduling gaps in specialty clinics cause capacity waste.
**Experiment:** Vary the timing and channel (SMS vs. MyChart push) of cancellation
waitlist notifications.
**Metric:** `open_slot_fill_rate` — % of same-day cancellations filled within 2 hours.
**Source:** UKG/Epic scheduling data via webhook.
**Expected gain:** 20–40% improvement in slot utilization.

### 5. Security Alert Fatigue Reduction
**Problem:** Security triage agent generates too many low-priority alerts, causing
analyst burnout and missed critical events.
**Experiment:** Tune the security_triage agent's classification threshold.
**Metric:** `alert_signal_to_noise_ratio` — critical:total alert ratio over 7 days.
**Source:** Trellis audit logs (alert events with severity classifications).
**Expected gain:** 30–50% reduction in noise without missing true positives.

---

## Safety Guardrails

Healthcare operations cannot tolerate uncontrolled automated changes. The
Optimization Engine is built defense-first.

### 1. Human Approval Gates

All experiments have a `risk_level` (low / medium / high).

| Risk Level | Change Type | Approval Needed |
|------------|-------------|-----------------|
| Low | Agent prompt rewording, cosmetic | Auto-apply (logged) |
| Medium | Timing changes, threshold shifts | Approval required to KEEP (variant runs automatically) |
| High | Workflow step reordering, new integrations | Approval required to ACTIVATE variant AND to keep |

Approval requests are sent via Teams message to the experiment owner + their manager.
Approvals expire after 48 hours — expired = auto-revert.

### 2. Automatic Rollback Triggers

Each experiment defines a `rollback_trigger`:
```json
{
  "metric": "bed_turnover_minutes",
  "threshold": 1.15,
  "comparison": "percent_increase_over_baseline"
}
```

If the variant metric exceeds this threshold at any point during measurement,
the experiment rolls back immediately — no human needed. The variant config is
replaced with the pre-experiment snapshot stored in `control_snapshot`.

Rollback events are always logged and a Teams/Slack alert fires regardless of hour.

### 3. Change Limits

- **One experiment per agent at a time.** Two concurrent experiments on the same
  agent would contaminate metrics. Enforced at the API level.
- **Max 3 concurrent active experiments** per tenant (configurable). Prevents the
  system from being a change-management nightmare.
- **Variant activation window:** Variants only activate during configured business
  hours by default (e.g., 06:00–22:00 local). Night activations require explicit opt-in.
- **Mandatory baseline period:** Minimum 4 hours, default 24 hours. No skipping
  baseline with API overrides (except in dev/sandbox mode).

### 4. Immutable Audit Trail

Every state transition, approval, change activation, and rollback is written to
`optimization_experiment_events` with actor identity and timestamp. This table is
append-only (no UPDATE/DELETE via API). Required for HIPAA audit readiness.

### 5. Blast Radius Containment

Experiments operate on **copies** of prompts/configs, not live values directly.
The Change Executor creates a new versioned config entry and points the agent to it.
Rolling back means pointing the agent back to the prior version — the original is
never modified.

### 6. No PHI in Experiment Data

Metric observations store only aggregate values (means, counts, rates). Never
individual patient records. Experiment specs cannot reference patient identifiers.
The PHI Shield runs on any free-text in experiment descriptions before storage.

---

## Implementation Roadmap

**Phase 1 — Foundation (2 weeks)**
- DB schema + Alembic migration
- Experiment CRUD API
- Variant Manager (config snapshot/restore)
- Manual trigger (no automation yet)
- Dashboard: experiment list + detail view

**Phase 2 — Automation (2 weeks)**
- Experiment Orchestrator (state machine)
- Metric Collector (poll from audit logs)
- Automatic rollback trigger evaluation
- Approval Gateway (Teams integration)
- Dashboard: pending approvals panel

**Phase 3 — Intelligence (2 weeks)**
- Statistical significance calculation (Welch's t-test)
- Sample size adequacy checks
- Cumulative gains tracking
- External metric webhook endpoint (Epic, UKG)
- Dashboard: gains summary + history view

**Phase 4 — Scale (ongoing)**
- Multi-variant experiments (A/B/C)
- Bayesian early stopping
- Experiment templates for common healthcare scenarios
- Export to Excel/CSV for board reporting

---

*— Atlas 🏗️*
*Architecture designed for Trellis v1 — Healthcare AI Agent Control Plane*
*Health First deployment context: Azure Container Apps, Epic EMR integration, HIPAA environment*
