const API_BASE = process.env.NEXT_PUBLIC_TRELLIS_API_URL || "";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

// Re-export types from canonical definitions
export type {
  Agent, AuditEvent, Rule, EnvelopeLog, CostEvent, CostSummary, CostTimeseriesBucket, GatewayStats, GatewayStatsResponse, HealthStatus,
  PhiTestResponse, PhiStatsResponse, PhiShieldMode, AgentPhiConfig, GatewayProvider, GatewayModel, FinOpsSummary, ToolInfo, ToolCallLog,
  ObservatorySummary, ObservatoryModel, ObservatoryModelMetrics,
} from "../types/trellis";

import type { Agent, AuditEvent, Rule, EnvelopeLog, CostEvent, CostSummary, CostTimeseriesBucket, GatewayStatsResponse, HealthStatus, PhiTestResponse, PhiStatsResponse, PhiShieldMode, AgentPhiConfig, GatewayProvider, GatewayModel, FinOpsSummary, ToolInfo, ToolCallLog, ObservatorySummary, ObservatoryModel, ObservatoryModelMetrics } from "../types/trellis";

// API functions
export const api = {
  health: () => apiFetch<HealthStatus>("/health"),
  agents: {
    list: () => apiFetch<Agent[]>("/api/agents"),
    get: (id: string) => apiFetch<Agent>(`/api/agents/${id}`),
    create: (data: Partial<Agent>) => apiFetch<Agent>("/api/agents", { method: "POST", body: JSON.stringify(data) }),
  },
  rules: {
    list: () => apiFetch<Rule[]>("/api/rules"),
    create: (data: Partial<Rule>) => apiFetch<Rule>("/api/rules", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Rule>) => apiFetch<Rule>(`/api/rules/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    toggle: (id: number) => apiFetch<Rule>(`/api/rules/${id}/toggle`, { method: "PUT" }),
    delete: (id: number) => apiFetch<void>(`/api/rules/${id}`, { method: "DELETE" }),
    test: (envelope: Record<string, unknown>) => apiFetch<{ matched_rules: Rule[] }>("/api/rules/test", { method: "POST", body: JSON.stringify({ envelope }) }),
  },
  envelopes: {
    list: () => apiFetch<EnvelopeLog[]>("/api/envelopes"),
  },
  audit: {
    list: (params?: { event_type?: string; agent_id?: string; trace_id?: string }) => {
      const qs = new URLSearchParams();
      if (params?.event_type) qs.set("event_type", params.event_type);
      if (params?.agent_id) qs.set("agent_id", params.agent_id);
      if (params?.trace_id) qs.set("trace_id", params.trace_id);
      const q = qs.toString();
      return apiFetch<AuditEvent[]>(`/api/audit${q ? `?${q}` : ""}`);
    },
    trace: (traceId: string) => apiFetch<AuditEvent[]>(`/api/audit/trace/${traceId}`),
  },
  costs: {
    summary: () => apiFetch<CostSummary[]>("/api/costs/summary"),
    byAgent: (agentId: string) => apiFetch<CostEvent[]>(`/api/costs?agent_id=${agentId}`),
    timeseries: (granularity: string = "day") =>
      apiFetch<CostTimeseriesBucket[]>(`/api/costs/timeseries?granularity=${granularity}`),
  },
  finops: {
    summary: () => apiFetch<FinOpsSummary>("/api/finops/summary"),
  },
  gateway: {
    stats: () => apiFetch<GatewayStatsResponse>("/api/gateway/stats"),
    providers: () => apiFetch<GatewayProvider[]>("/api/gateway/providers"),
    models: () => apiFetch<GatewayModel[]>("/api/gateway/models"),
  },
  tools: {
    list: () => apiFetch<ToolInfo[]>("/api/tools"),
    get: (name: string) => apiFetch<ToolInfo>(`/api/tools/${name}`),
    usage: (name: string, limit: number = 50) => apiFetch<ToolCallLog[]>(`/api/tools/${name}/usage?limit=${limit}`),
  },
  observatory: {
    summary: () => apiFetch<ObservatorySummary>("/api/observatory/summary"),
    models: () => apiFetch<ObservatoryModel[]>("/api/observatory/models"),
    modelMetrics: (modelId: string) => apiFetch<ObservatoryModelMetrics>(`/api/observatory/models/${encodeURIComponent(modelId)}/metrics`),
  },
  phi: {
    test: (text: string) => apiFetch<PhiTestResponse>("/api/phi/test", { method: "POST", body: JSON.stringify({ text }) }),
    stats: () => apiFetch<PhiStatsResponse>("/api/phi/stats"),
    agentConfigs: () => apiFetch<AgentPhiConfig[]>("/api/phi/agents"),
    updateAgentMode: (agentId: string, mode: PhiShieldMode) =>
      apiFetch<AgentPhiConfig>(`/api/agents/${agentId}/phi`, { method: "PUT", body: JSON.stringify({ phi_shield_mode: mode }) }),
  },
};
