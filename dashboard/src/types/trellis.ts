// Trellis API response types — matches actual Python API responses

export interface Agent {
  agent_id: string;
  name: string;
  owner: string;
  department: string;
  framework: string;
  agent_type: string;
  runtime_type: string;
  endpoint: string | null;
  health_endpoint: string | null;
  tools: string[];
  channels: string[];
  maturity: string;
  cost_mode: string;
  status: string;
  llm_config?: Record<string, unknown> | null;
  function_ref?: string | null;
  created: string;
  last_health_check: string | null;
  api_key?: string; // only on create response
}

export interface AuditEvent {
  id: number;
  trace_id: string | null;
  envelope_id: string | null;
  agent_id: string | null;
  event_type: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface Rule {
  id: number;
  name: string;
  priority: number;
  conditions: Record<string, unknown>;
  actions: {
    route_to: string | string[];
    set_priority?: string;
    require_approval?: boolean;
  };
  active: boolean;
  fan_out: boolean;
}

export interface EnvelopeLog {
  id: number;
  envelope_id: string;
  trace_id: string;
  source_type: string;
  matched_rule_name: string | null;
  target_agent_id: string | null;
  dispatch_status: string;
  error: string | null;
  timestamp: string;
}

export interface CostEvent {
  id: number;
  trace_id: string | null;
  agent_id: string;
  model_requested: string;
  model_used: string;
  provider: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  has_tool_calls: boolean;
  complexity_class: string | null;
  timestamp: string;
}

export interface CostSummary {
  agent_id: string;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  request_count: number;
}

export interface GatewayStats {
  total_requests: number;
  total_tokens: number;
  total_cost: number;
  requests_by_provider: Record<string, number>;
  avg_tokens_per_request: number;
}

export interface HealthStatus {
  status: string;
  service?: string;
}

/* ─── Health Auditor Types ─── */

export interface HealthQuickResponse {
  status: string;
  timestamp: string | null;
  agents: {
    total: number;
    healthy: number;
    degraded: number;
    unreachable: number;
  } | null;
}

export interface HealthCheckResult {
  name: string;
  status: string;
  latency_ms: number | null;
  details: Record<string, unknown>;
}

export interface HealthAgentCheck {
  agent_id: string;
  status: string;
  latency_ms: number | null;
  baseline_ms: number | null;
  note?: string;
  degraded?: boolean;
}

export interface HealthDetailedResponse {
  status: string;
  timestamp: string;
  agents: {
    summary: { total: number; healthy: number; degraded: number; unreachable: number };
    checks: HealthAgentCheck[];
  };
  llm_providers: HealthCheckResult[];
  database: HealthCheckResult;
  background_tasks: HealthCheckResult[];
  smtp: HealthCheckResult;
  system: HealthCheckResult;
  adapters: HealthCheckResult[];
}

export interface HealthCheckRecord {
  id: number;
  check_name: string;
  status: string;
  latency_ms: number | null;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface CostTimeseriesBucket {
  bucket: string;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  request_count: number;
}

export interface GatewayStatsResponse {
  total_requests: number;
  total_tokens: number;
  total_cost: number;
  requests_by_provider: Record<string, number>;
  avg_tokens_per_request: number;
}

// FinOps types

export interface FinOpsSummary {
  spend_today_usd: number;
  spend_this_week_usd: number;
  spend_this_month_usd: number;
  total_requests: number;
  avg_cost_per_request_usd: number;
  top_agents: { agent_id: string; total_cost_usd: number; requests: number }[];
  top_departments: { department: string; total_cost_usd: number; requests: number }[];
}

// Gateway types

export interface GatewayProvider {
  name: string;
  display_name: string;
  configured: boolean;
  base_url: string | null;
  models: string[];
}

export interface GatewayModel {
  model: string;
  provider: string;
  available: boolean;
}

// PHI Shield types

export type PhiShieldMode = "full" | "redact_only" | "audit_only" | "off";

export interface PhiDetectionResult {
  type: string;
  text: string;
  start: number;
  end: number;
  source: string;
  score: number;
}

export interface PhiTestResponse {
  detections: PhiDetectionResult[];
  redacted: string;
}

export interface PhiStatsResponse {
  total_detections: number;
  by_category: Record<string, number>;
  by_agent: Record<string, number>;
  by_day: Record<string, number>;
  recent_events: PhiRecentEvent[];
}

export interface PhiRecentEvent {
  timestamp: string;
  agent_id: string;
  count: number;
  categories: string[];
  mode: string;
}

// Tool Registry types

export interface ToolInfo {
  name: string;
  category: string;
  description: string;
  requires_permissions: string[];
  call_count: number;
  error_count: number;
  avg_latency_ms: number;
}

export interface ToolCallLog {
  id: number;
  trace_id: string | null;
  agent_id: string;
  params: Record<string, unknown>;
  result_summary: string | null;
  status: string;
  latency_ms: number;
  error: string | null;
  timestamp: string | null;
}

export interface AgentPhiConfig {
  agent_id: string;
  name: string;
  phi_shield_mode: PhiShieldMode;
}

/* ─── Observatory Types ─── */

export interface ObservatorySummary {
  total_requests: number;
  total_cost_usd: number;
  error_rate: number;
  unique_models: number;
  unique_agents: number;
  period_start: string;
  period_end: string;
}

export interface ObservatoryModel {
  model_id: string;
  provider: string;
  request_count: number;
  error_count: number;
  error_rate: number;
  avg_latency_ms: number;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  last_used: string;
}

export interface ObservatoryModelMetrics {
  model_id: string;
  latency: {
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
    avg_ms: number;
  };
  tokens: {
    total_input: number;
    total_output: number;
    avg_input_per_request: number;
    avg_output_per_request: number;
  };
  hourly: Array<{
    hour: string;
    requests: number;
    errors: number;
    avg_latency_ms: number;
    cost_usd: number;
  }>;
  cost_per_request_trend: Array<{
    hour: string;
    cost_per_request: number;
  }>;
}

/* ─── Intelligent Routing Types ─── */

export interface AgentIntake {
  agent_id: string;
  categories: string[];
  source_types: string[];
  keywords: string[];
  systems: string[];
  priority_range: [number, number];
  phi_authorized: boolean;
}

export interface RoutingScoreBreakdown {
  category: number;
  source_type: number;
  keyword: number;
  system: number;
  priority: number;
}

export interface RoutingResult {
  agent_id: string;
  agent_name: string;
  score: number;
  confidence: number;
  breakdown: RoutingScoreBreakdown;
}

export interface IntelligentRouteResponse {
  winner: RoutingResult;
  candidates: RoutingResult[];
  envelope_id: string;
  routed_at: string;
}

export interface RoutingDecision {
  id: string;
  envelope_id: string;
  envelope_summary: string;
  winner_agent_id: string;
  winner_agent_name: string;
  score: number;
  confidence: number;
  candidates_count: number;
  routed_at: string;
}
