# Trellis API Reference

Base URL: `http://localhost:8100`

Interactive docs: `GET /docs` (Swagger UI) | `GET /redoc` (ReDoc)

---

## Authentication

The LLM Gateway (`/v1/chat/completions`) requires a Bearer token:

```
Authorization: Bearer trl_abc123...
```

API keys are created via `POST /api/keys` and returned **once** in plaintext. They are stored as SHA-256 hashes. Keys are scoped to a single agent and carry optional budget caps.

All other `/api/*` endpoints are currently unauthenticated (admin access).

---

## Health

### `GET /health`
Root health check.

**Response:** `200 OK`
```json
{"status": "healthy", "service": "trellis"}
```

### `GET /api/health`
API health check.

**Response:** `200 OK`
```json
{"status": "healthy", "service": "trellis", "version": "0.3.0"}
```

---

## Agents

### `POST /api/agents`
Register a new agent.

**Request:**
```json
{
  "agent_id": "mock-echo",
  "name": "Mock Echo Agent",
  "owner": "platform-team",
  "department": "IT",
  "framework": "mock",
  "agent_type": "http",
  "endpoint": "http://localhost:8100/mock-agent/envelope",
  "health_endpoint": "http://localhost:8100/mock-agent/health",
  "tools": ["echo"],
  "channels": ["api"],
  "maturity": "shadow",
  "cost_mode": "managed"
}
```

Agent types: `http` | `webhook` | `function` | `llm`

For `function` agents, set `function_ref` (e.g., `"echo"`). For `llm` agents, set `llm_config`:
```json
{
  "agent_type": "llm",
  "llm_config": {
    "system_prompt": "You are a helpful assistant.",
    "model": "qwen3:8b",
    "temperature": 0.7,
    "max_tokens": 1024
  }
}
```

**Response:** `201 Created`
```json
{
  "agent_id": "mock-echo",
  "name": "Mock Echo Agent",
  "owner": "platform-team",
  "department": "IT",
  "framework": "mock",
  "agent_type": "http",
  "endpoint": "http://localhost:8100/mock-agent/envelope",
  "health_endpoint": "http://localhost:8100/mock-agent/health",
  "tools": ["echo"],
  "channels": ["api"],
  "maturity": "shadow",
  "cost_mode": "managed",
  "status": "unknown",
  "created": "2026-02-22T20:00:00Z",
  "last_health_check": null,
  "api_key": "trl_abc123..."
}
```

> **Note:** `api_key` is returned only on creation. Store it — it cannot be retrieved again.

### `GET /api/agents`
List all registered agents.

**Response:** `200 OK` — Array of agent objects.

### `GET /api/agents/{agent_id}`
Get a single agent by ID.

**Response:** `200 OK` | `404 Not Found`

### `PUT /api/agents/{agent_id}`
Update an agent. Partial updates supported.

**Request:**
```json
{"name": "Updated Name", "maturity": "autonomous"}
```

**Response:** `200 OK`

### `DELETE /api/agents/{agent_id}`
Remove an agent from the registry.

**Response:** `204 No Content` | `404 Not Found`

### `POST /api/agents/{agent_id}/sync`
Pull manifest from the agent's endpoint and update registry fields (tools, channels, maturity, framework, department).

**Response:** `200 OK` — Updated agent object.

---

## Rules

### `POST /api/rules`
Create a routing rule.

**Request:**
```json
{
  "name": "Route HR queries to SAM",
  "priority": 100,
  "conditions": {
    "source_type": "teams",
    "metadata.sender.department": "HR"
  },
  "actions": {"route_to": "sam-hr"},
  "active": true,
  "fan_out": false
}
```

**Condition operators:**
| Operator | Example | Description |
|----------|---------|-------------|
| Equality | `{"source_type": "api"}` | Exact match |
| `$in` | `{"priority": {"$in": ["high","critical"]}}` | Value in list |
| `$gt` / `$gte` | `{"score": {"$gt": 0.8}}` | Greater than |
| `$lt` / `$lte` | `{"score": {"$lt": 0.5}}` | Less than |
| `$exists` | `{"payload.data.patient_id": {"$exists": true}}` | Field exists |
| `$regex` | `{"payload.text": {"$regex": "urgent.*"}}` | Regex match |
| `$not` | `{"status": {"$not": "closed"}}` | Not equal |
| `$contains` | `{"tags": {"$contains": "priority"}}` | String/list contains |

Dot notation supported for nested fields (e.g., `metadata.sender.department`).

**Response:** `201 Created`

### `GET /api/rules`
List all rules.

### `GET /api/rules/{rule_id}`
Get a single rule.

### `PUT /api/rules/{rule_id}`
Update a rule (partial).

### `DELETE /api/rules/{rule_id}`
Delete a rule.

### `PUT /api/rules/{rule_id}/toggle`
Toggle a rule's `active` status.

**Response:** `200 OK` — Updated rule with toggled `active` field.

### `POST /api/rules/test`
Dry-run: test which rules match a given envelope.

**Request:**
```json
{
  "envelope": {
    "source_type": "api",
    "payload": {"text": "Test message"},
    "metadata": {"priority": "high"}
  }
}
```

**Response:** `200 OK`
```json
{
  "matched_rules": [
    {"id": 1, "name": "Route all", "priority": 100, "conditions": {...}, "actions": {...}, "active": true, "fan_out": false}
  ]
}
```

---

## Event Router

### `POST /api/envelopes`
Submit a raw envelope to the event router. The platform matches rules, dispatches to agents, and logs everything.

**Request:** Full [Generic Envelope](#generic-envelope-spec) object.

**Response:** `200 OK`
```json
{
  "status": "completed",
  "envelope_id": "uuid",
  "matched_rule": "Route all to mock",
  "target_agent": "mock-echo",
  "result": {...}
}
```

### `POST /api/adapter/http`
Simplified HTTP adapter. Builds an envelope from simple fields.

**Request:**
```json
{
  "text": "Hello Trellis!",
  "sender_name": "Eric",
  "sender_department": "IT",
  "priority": "normal",
  "tags": ["demo"],
  "data": {}
}
```

**Response:** Same as `POST /api/envelopes`.

### `GET /api/envelopes`
Query the envelope audit log.

**Query params:** `source_type`, `trace_id`, `limit` (default 100)

**Response:** `200 OK` — Array of envelope log entries.

---

## API Keys

### `POST /api/keys`
Create an API key for an agent (used for LLM Gateway auth).

**Request:**
```json
{
  "agent_id": "mock-echo",
  "name": "dev-key",
  "budget_daily_usd": 5.00,
  "budget_monthly_usd": 100.00,
  "preferred_provider": "ollama",
  "default_model": "qwen3:8b"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "key": "trl_abc123...",
  "key_prefix": "trl_abc1",
  "agent_id": "mock-echo",
  "name": "dev-key"
}
```

> The `key` field is returned **only once**. Store it securely.

### `GET /api/keys`
List API keys (shows prefix only, never the full key).

### `DELETE /api/keys/{key_id}`
Revoke an API key. Immediately stops all gateway access for that key.

---

## LLM Gateway

### `POST /v1/chat/completions`
OpenAI-compatible chat completions proxy. Requires `Authorization: Bearer trl_...`.

**Request:**
```json
{
  "model": "qwen3:8b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is PTO?"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "lookup_policy",
        "description": "Look up an HR policy",
        "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}}
      }
    }
  ]
}
```

**Smart model routing:** Set `model` to `"auto"` (or omit) to let Trellis classify request complexity and pick the optimal model:
- **Simple** → local model (qwen3:8b)
- **Medium** → GPT-4o
- **Complex** → Claude Sonnet

**Response:** `200 OK` — Standard OpenAI chat completion response, plus headers:
- `X-Trellis-Cost-USD`: Cost of this request
- `X-Trellis-Complexity`: Complexity class (when auto-routing)

**Error responses:**
- `401 Unauthorized` — Missing, invalid, or revoked API key
- `429 Too Many Requests` — Budget cap exceeded
- `502 Bad Gateway` — Provider error

---

## Costs

### `GET /api/costs`
List cost events.

**Query params:** `agent_id`, `trace_id`, `since`, `until`, `limit`

### `GET /api/costs/summary`
Aggregated costs per agent.

**Query params:** `since`, `until`

**Response:**
```json
[
  {
    "agent_id": "mock-echo",
    "total_cost_usd": 0.00234,
    "total_tokens_in": 1500,
    "total_tokens_out": 800,
    "request_count": 12
  }
]
```

### `GET /api/costs/by-department`
Costs aggregated by department.

### `GET /api/costs/by-department/{dept}`
Drill into a department's costs, broken down by agent.

### `GET /api/costs/trace/{trace_id}`
Total cost for an entire trace chain with per-agent breakdown.

### `GET /api/costs/timeseries`
Cost over time for dashboard charts.

**Query params:** `agent_id`, `granularity` (`hour`|`day`|`week`), `since`, `until`

**Response:**
```json
[
  {"bucket": "2026-02-22", "total_cost_usd": 0.0045, "total_tokens_in": 3000, "total_tokens_out": 1500, "request_count": 8}
]
```

---

## FinOps

### `GET /api/finops/summary`
Executive dashboard summary.

**Response:**
```json
{
  "spend_today_usd": 1.23,
  "spend_this_week_usd": 8.45,
  "spend_this_month_usd": 34.56,
  "total_requests": 1250,
  "avg_cost_per_request_usd": 0.0028,
  "top_agents": [
    {"agent_id": "sam-hr", "total_cost_usd": 12.34, "requests": 500}
  ],
  "top_departments": [
    {"department": "HR", "total_cost_usd": 15.67, "requests": 600}
  ]
}
```

---

## Audit

### `GET /api/audit`
Query audit events.

**Query params:** `event_type`, `agent_id`, `trace_id`, `since`, `until`, `limit`

**Event types:** `envelope_received`, `rule_matched`, `agent_dispatched`, `agent_responded`, `error`, `llm_inference`, `budget_exceeded`, `budget_warning`, `cost_anomaly`, `key_created`, `key_revoked`, `rule_created`, `rule_updated`, `rule_deleted`, `rule_toggled`

**Response:**
```json
[
  {
    "id": 1,
    "trace_id": "uuid",
    "envelope_id": "uuid",
    "agent_id": "mock-echo",
    "event_type": "agent_dispatched",
    "details": {"agent_type": "http", "rule_name": "Route all"},
    "timestamp": "2026-02-22T20:00:00Z"
  }
]
```

### `GET /api/audit/trace/{trace_id}`
Full audit chain for a trace.

---

## Generic Envelope Spec

```json
{
  "envelope_id": "uuid (auto-generated)",
  "source_type": "api|teams|hl7|file|queue|schedule|agent|manual",
  "source_id": "identifier for the source instance",
  "payload": {
    "text": "Human message or parsed content",
    "data": {},
    "attachments": []
  },
  "metadata": {
    "trace_id": "uuid (auto-generated, links entire chain)",
    "timestamp": "ISO-8601",
    "priority": "low|normal|high|critical",
    "sender": {
      "id": "user or system id",
      "name": "display name",
      "department": "HR|IT|...",
      "roles": ["manager", "admin"]
    }
  },
  "routing_hints": {
    "agent_id": "optional — direct routing",
    "department": "optional",
    "category": "optional",
    "tags": []
  }
}
```
