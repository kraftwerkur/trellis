"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type {
  HealthQuickResponse, HealthDetailedResponse, HealthCheckResult,
  HealthCheckRecord, HealthAgentCheck,
} from "@/types/trellis";
import {
  HeartPulse, Database, Cpu, Mail, Plug, Bot, Clock, ArrowLeft,
  Activity, RefreshCw, CheckCircle2, AlertTriangle, XCircle, Loader2,
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ScatterChart, Scatter, Cell,
} from "@/lib/charts";

/* ─── Mock Data (demo mode fallback) ─── */

const MOCK_QUICK: HealthQuickResponse = {
  status: "degraded",
  timestamp: new Date(Date.now() - 45000).toISOString(),
  agents: { total: 5, healthy: 4, degraded: 1, unreachable: 0 },
};

const MOCK_DETAILED: HealthDetailedResponse = {
  status: "degraded",
  timestamp: new Date(Date.now() - 45000).toISOString(),
  agents: {
    summary: { total: 5, healthy: 4, degraded: 1, unreachable: 0 },
    checks: [
      { agent_id: "health_auditor", status: "healthy", latency_ms: null, baseline_ms: null, note: "native agent, no health endpoint" },
      { agent_id: "phi_shield", status: "healthy", latency_ms: null, baseline_ms: null, note: "in-process agent" },
      { agent_id: "cost_optimizer", status: "healthy", latency_ms: null, baseline_ms: null, note: "in-process agent" },
      { agent_id: "schema_drift", status: "degraded", latency_ms: 2450, baseline_ms: 800, degraded: true },
      { agent_id: "rule_optimizer", status: "healthy", latency_ms: 120, baseline_ms: 110 },
    ],
  },
  llm_providers: [
    { name: "llm:anthropic", status: "healthy", latency_ms: 245, details: { url: "https://api.anthropic.com/v1", model_count: 8, http_status: 200 } },
    { name: "llm:openai", status: "healthy", latency_ms: 189, details: { url: "https://api.openai.com/v1", model_count: 14, http_status: 200 } },
    { name: "llm:ollama", status: "healthy", latency_ms: 12, details: { url: "http://localhost:11434/v1", model_count: 3, http_status: 200 } },
  ],
  database: {
    name: "database", status: "healthy", latency_ms: 4.2,
    details: { file_size_mb: 24.8, writable: true, integrity: "ok", partition_free_gb: 142.3, row_counts: { agents: 5, audit_events: 14832, cost_events: 8421, envelope_log: 3200 } },
  },
  background_tasks: [
    { name: "task:health_auditor", status: "healthy", latency_ms: null, details: { last_run: new Date(Date.now() - 45000).toISOString(), age_seconds: 45, expected_interval: 60, stale: false } },
    { name: "task:audit_compactor", status: "healthy", latency_ms: null, details: { last_run: new Date(Date.now() - 3600000).toISOString(), age_seconds: 3600, expected_interval: 86400, stale: false } },
    { name: "task:rule_optimizer", status: "warning", latency_ms: null, details: { note: "no heartbeat recorded yet" } },
    { name: "task:schema_drift", status: "healthy", latency_ms: null, details: { last_run: new Date(Date.now() - 7200000).toISOString(), age_seconds: 7200, expected_interval: 86400, stale: false } },
    { name: "task:cost_optimizer", status: "healthy", latency_ms: null, details: { last_run: new Date(Date.now() - 1800000).toISOString(), age_seconds: 1800, expected_interval: 3600, stale: false } },
  ],
  smtp: { name: "smtp", status: "warning", latency_ms: null, details: { note: "TRELLIS_SMTP_HOST not configured" } },
  system: {
    name: "system", status: "healthy", latency_ms: null,
    details: { disk_total_gb: 500, disk_used_gb: 142, disk_free_gb: 358, disk_percent_used: 28.4, memory_total_gb: 32, memory_used_gb: 18.4, memory_percent_used: 57.5 },
  },
  adapters: [
    { name: "adapter:http", status: "healthy", latency_ms: null, details: { note: "built-in, always available" } },
    { name: "adapter:teams", status: "warning", latency_ms: null, details: { note: "TEAMS_APP_ID not configured" } },
    { name: "adapter:fhir", status: "warning", latency_ms: null, details: { note: "TRELLIS_FHIR_ENDPOINT not configured" } },
  ],
};

function generateMockHistory(checkName: string): HealthCheckRecord[] {
  return Array.from({ length: 24 }, (_, i) => ({
    id: 24 - i,
    check_name: checkName,
    status: i === 5 ? "degraded" : i === 12 ? "warning" : "healthy",
    latency_ms: checkName.startsWith("llm:") ? Math.random() * 300 + 100 : checkName === "database" ? Math.random() * 8 + 2 : null,
    details: {},
    timestamp: new Date(Date.now() - i * 3600000).toISOString(),
  }));
}

/* ─── Helpers ─── */

function formatTimeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function formatLatency(ms: number | null) {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

const STATUS_CONFIG = {
  healthy: { color: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20", icon: CheckCircle2, label: "Healthy" },
  degraded: { color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20", icon: AlertTriangle, label: "Degraded" },
  warning: { color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20", icon: AlertTriangle, label: "Warning" },
  unreachable: { color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/20", icon: XCircle, label: "Unreachable" },
  unhealthy: { color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/20", icon: XCircle, label: "Unhealthy" },
  unknown: { color: "text-zinc-500", bg: "bg-zinc-500/10", border: "border-zinc-500/20", icon: Clock, label: "Unknown" },
} as const;

function getStatusConfig(status: string) {
  return STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.unknown;
}

/* ─── Check Category Definitions ─── */

interface CheckCategory {
  key: string;
  label: string;
  icon: typeof HeartPulse;
  getChecks: (d: HealthDetailedResponse) => HealthCheckResult[];
  getStatus: (d: HealthDetailedResponse) => string;
  getSummary: (d: HealthDetailedResponse) => string;
  getLatency: (d: HealthDetailedResponse) => number | null;
}

const CATEGORIES: CheckCategory[] = [
  {
    key: "llm_providers",
    label: "LLM Providers",
    icon: Cpu,
    getChecks: (d) => d.llm_providers,
    getStatus: (d) => {
      const statuses = d.llm_providers.map(c => c.status);
      if (statuses.includes("unreachable")) return "unreachable";
      if (statuses.includes("degraded")) return "degraded";
      return "healthy";
    },
    getSummary: (d) => `${d.llm_providers.length} provider${d.llm_providers.length !== 1 ? "s" : ""}`,
    getLatency: (d) => {
      const lats = d.llm_providers.map(c => c.latency_ms).filter((v): v is number => v !== null);
      return lats.length ? Math.round(lats.reduce((a, b) => a + b, 0) / lats.length) : null;
    },
  },
  {
    key: "database",
    label: "Database",
    icon: Database,
    getChecks: (d) => [d.database],
    getStatus: (d) => d.database.status,
    getSummary: (d) => {
      const size = d.database.details.file_size_mb;
      return size ? `${size} MB` : "connected";
    },
    getLatency: (d) => d.database.latency_ms,
  },
  {
    key: "background_tasks",
    label: "Background Tasks",
    icon: Activity,
    getChecks: (d) => d.background_tasks,
    getStatus: (d) => {
      const statuses = d.background_tasks.map(c => c.status);
      if (statuses.includes("unreachable")) return "unreachable";
      if (statuses.includes("warning")) return "warning";
      return "healthy";
    },
    getSummary: (d) => {
      const ok = d.background_tasks.filter(c => c.status === "healthy").length;
      return `${ok}/${d.background_tasks.length} running`;
    },
    getLatency: () => null,
  },
  {
    key: "smtp",
    label: "SMTP",
    icon: Mail,
    getChecks: (d) => [d.smtp],
    getStatus: (d) => d.smtp.status,
    getSummary: (d) => {
      if (d.smtp.status === "warning") return "not configured";
      return d.smtp.status;
    },
    getLatency: (d) => d.smtp.latency_ms,
  },
  {
    key: "adapters",
    label: "Adapters",
    icon: Plug,
    getChecks: (d) => d.adapters,
    getStatus: (d) => {
      const statuses = d.adapters.map(c => c.status);
      if (statuses.includes("unreachable")) return "unreachable";
      if (statuses.includes("degraded")) return "degraded";
      if (statuses.includes("warning")) return "warning";
      return "healthy";
    },
    getSummary: (d) => {
      const ok = d.adapters.filter(c => c.status === "healthy").length;
      return `${ok}/${d.adapters.length} active`;
    },
    getLatency: (d) => {
      const lats = d.adapters.map(c => c.latency_ms).filter((v): v is number => v !== null);
      return lats.length ? Math.round(lats.reduce((a, b) => a + b, 0) / lats.length) : null;
    },
  },
  {
    key: "system",
    label: "System Resources",
    icon: Cpu,
    getChecks: (d) => [d.system],
    getStatus: (d) => d.system.status,
    getSummary: (d) => {
      const disk = d.system.details.disk_percent_used;
      const mem = d.system.details.memory_percent_used;
      const parts: string[] = [];
      if (typeof disk === "number") parts.push(`Disk ${disk}%`);
      if (typeof mem === "number") parts.push(`Mem ${mem}%`);
      return parts.join(", ") || "checked";
    },
    getLatency: () => null,
  },
  {
    key: "agents",
    label: "Agents",
    icon: Bot,
    getChecks: (d) => d.agents.checks.map(a => ({
      name: `agent:${a.agent_id}`,
      status: a.status,
      latency_ms: a.latency_ms,
      details: { baseline_ms: a.baseline_ms, note: a.note, degraded: a.degraded },
    })),
    getStatus: (d) => {
      const s = d.agents.summary;
      if (s.unreachable > 0) return "unreachable";
      if (s.degraded > 0) return "degraded";
      return "healthy";
    },
    getSummary: (d) => {
      const s = d.agents.summary;
      return `${s.healthy}/${s.total} healthy`;
    },
    getLatency: (d) => {
      const lats = d.agents.checks.map(c => c.latency_ms).filter((v): v is number => v !== null);
      return lats.length ? Math.round(lats.reduce((a, b) => a + b, 0) / lats.length) : null;
    },
  },
];

/* ─── History Detail View ─── */

function HistoryDetailView({ checkName, onBack }: { checkName: string; onBack: () => void }) {
  const fetchHistory = useCallback(() => api.healthAuditor.history(checkName, 100), [checkName]);
  const { data: rawHistory, loading } = useStablePolling<HealthCheckRecord[]>(fetchHistory, 30000);
  const history = rawHistory ?? generateMockHistory(checkName);

  // Prepare chart data (oldest first)
  const chartData = useMemo(() => {
    return [...history].reverse().map(r => ({
      time: new Date(r.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      latency: r.latency_ms,
      status: r.status === "healthy" ? 1 : r.status === "warning" || r.status === "degraded" ? 0.5 : 0,
      statusLabel: r.status,
      fullTime: new Date(r.timestamp).toLocaleString(),
    }));
  }, [history]);

  const hasLatency = chartData.some(d => d.latency !== null);

  const STATUS_COLORS: Record<string, string> = {
    healthy: "#10b981",
    degraded: "#f59e0b",
    warning: "#f59e0b",
    unreachable: "#ef4444",
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="w-8 h-8 rounded-lg bg-white/[0.04] flex items-center justify-center hover:bg-white/[0.08] transition-colors">
          <ArrowLeft className="w-4 h-4 text-zinc-400" />
        </button>
        <div>
          <h2 className="text-lg font-bold text-zinc-100 font-data">{checkName}</h2>
          <p className="text-[10px] text-zinc-500 uppercase tracking-widest">Check History · {history.length} records</p>
        </div>
      </div>

      {loading && !rawHistory && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Loading history…
        </div>
      )}

      {/* Status Timeline */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06]">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Status Timeline</span>
        </div>
        <div className="p-4 h-32">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
              <YAxis domain={[-0.1, 1.1]} tick={false} axisLine={false} width={0} />
              <Tooltip
                contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }}
                formatter={(_: unknown, __: unknown, props: { payload?: { statusLabel?: string } }) => [props?.payload?.statusLabel ?? "—", "Status"]}
              />
              <Scatter data={chartData} dataKey="status">
                {chartData.map((d, i) => (
                  <Cell key={i} fill={STATUS_COLORS[d.statusLabel] ?? "#71717a"} r={5} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Latency Trend */}
      {hasLatency && (
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Latency Trend</span>
          </div>
          <div className="p-4 h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="latGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} width={48}
                  tickFormatter={(v: number) => `${Math.round(v)}ms`} />
                <Tooltip
                  contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "#a1a1aa" }}
                  formatter={(v: number) => [`${v?.toFixed(1)}ms`, "Latency"]}
                />
                <Area type="monotone" dataKey="latency" stroke="#06b6d4" fill="url(#latGrad)" strokeWidth={2} connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Recent Records Table */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06]">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Recent Records</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Time</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Latency</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {history.slice(0, 20).map(r => {
                const sc = getStatusConfig(r.status);
                return (
                  <tr key={r.id} className="border-b border-white/[0.04]">
                    <td className="px-4 py-2.5 font-data text-zinc-400">{formatTimeAgo(r.timestamp)}</td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 text-xs ${sc.color}`}>
                        <sc.icon className="w-3 h-3" /> {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-data text-zinc-300">{formatLatency(r.latency_ms)}</td>
                    <td className="px-4 py-2.5 text-zinc-500 font-mono text-[10px] max-w-[300px] truncate">
                      {Object.keys(r.details).length > 0 ? JSON.stringify(r.details) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Health Page ─── */

export default function HealthPage() {
  const [selectedCheck, setSelectedCheck] = useState<string | null>(null);
  const [runningCheck, setRunningCheck] = useState(false);

  const fetchQuick = useCallback(() => api.healthAuditor.quick(), []);
  const fetchDetailed = useCallback(() => api.healthAuditor.detailed(), []);

  const { data: rawQuick, loading: loadingQuick } = useStablePolling<HealthQuickResponse>(fetchQuick, 15000);
  const { data: rawDetailed, loading: loadingDetailed, refresh } = useStablePolling<HealthDetailedResponse>(fetchDetailed, 60000);

  const quick = rawQuick ?? MOCK_QUICK;
  const detailed = rawDetailed ?? MOCK_DETAILED;

  const handleRunFullCheck = async () => {
    setRunningCheck(true);
    try {
      await api.healthAuditor.detailed();
      await refresh();
    } catch {
      // Will show mock data on failure
    } finally {
      setRunningCheck(false);
    }
  };

  if (selectedCheck) {
    return <HistoryDetailView checkName={selectedCheck} onBack={() => setSelectedCheck(null)} />;
  }

  const overallConfig = getStatusConfig(quick.status);
  const OverallIcon = overallConfig.icon;

  return (
    <div className="space-y-4">
      {loadingQuick && loadingDetailed && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Health Auditor API…
        </div>
      )}

      {/* Overall Status Banner */}
      <div className={`card-dark overflow-hidden border ${overallConfig.border}`}>
        <div className={`px-5 py-4 flex items-center justify-between ${overallConfig.bg}`}>
          <div className="flex items-center gap-3">
            <OverallIcon className={`w-6 h-6 ${overallConfig.color}`} />
            <div>
              <div className={`text-lg font-bold font-data ${overallConfig.color}`}>
                System {overallConfig.label}
              </div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest">
                {quick.timestamp ? `Last check ${formatTimeAgo(quick.timestamp)}` : "No checks yet"}
                {quick.agents && ` · ${quick.agents.total} agents monitored`}
              </div>
            </div>
          </div>
          <button
            onClick={handleRunFullCheck}
            disabled={runningCheck}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.10] text-xs text-zinc-300 transition-colors disabled:opacity-50"
          >
            {runningCheck ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            {runningCheck ? "Running…" : "Run Full Check"}
          </button>
        </div>
      </div>

      {/* Check Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {CATEGORIES.map(cat => {
          const status = cat.getStatus(detailed);
          const sc = getStatusConfig(status);
          const StatusIcon = sc.icon;
          const latency = cat.getLatency(detailed);
          const checks = cat.getChecks(detailed);

          return (
            <div
              key={cat.key}
              onClick={() => {
                // Navigate to first check's history
                if (checks.length === 1) {
                  setSelectedCheck(checks[0].name);
                } else if (checks.length > 0) {
                  setSelectedCheck(checks[0].name);
                }
              }}
              className={`card-dark overflow-hidden cursor-pointer hover:bg-white/[0.02] transition-colors border ${sc.border}`}
            >
              <div className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <cat.icon className={`w-4 h-4 ${sc.color}`} />
                    <span className="text-sm font-medium text-zinc-200">{cat.label}</span>
                  </div>
                  <StatusIcon className={`w-4 h-4 ${sc.color}`} />
                </div>
                <div className="space-y-1.5">
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider">
                    {cat.getSummary(detailed)}
                  </div>
                  {latency !== null && (
                    <div className="flex items-center gap-1 text-[10px] text-zinc-500">
                      <Clock className="w-3 h-3" />
                      <span className="font-data">{formatLatency(latency)}</span>
                    </div>
                  )}
                  {/* Sub-checks preview */}
                  {checks.length > 1 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {checks.map(c => {
                        const csc = getStatusConfig(c.status);
                        return (
                          <button
                            key={c.name}
                            onClick={(e) => { e.stopPropagation(); setSelectedCheck(c.name); }}
                            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] ${csc.bg} ${csc.color} hover:opacity-80 transition-opacity`}
                          >
                            <csc.icon className="w-2.5 h-2.5" />
                            {c.name.split(":").pop()}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
              <div className={`h-0.5 ${sc.bg}`} />
            </div>
          );
        })}
      </div>

      {/* Detailed Check Results Table */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
            <HeartPulse className="w-3.5 h-3.5" /> All Checks
          </span>
          <span className="text-[10px] text-zinc-600">
            {detailed.timestamp ? new Date(detailed.timestamp).toLocaleString() : "—"}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Check</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Status</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Latency</th>
                <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const allChecks: HealthCheckResult[] = [
                  ...detailed.llm_providers,
                  detailed.database,
                  ...detailed.background_tasks,
                  detailed.smtp,
                  detailed.system,
                  ...detailed.adapters,
                  ...detailed.agents.checks.map(a => ({
                    name: `agent:${a.agent_id}`,
                    status: a.status,
                    latency_ms: a.latency_ms,
                    details: { note: a.note, degraded: a.degraded } as Record<string, unknown>,
                  })),
                ];
                return allChecks.map(c => {
                  const sc = getStatusConfig(c.status);
                  const detailStr = Object.entries(c.details || {})
                    .filter(([, v]) => v !== null && v !== undefined && v !== false)
                    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
                    .join(" · ");
                  return (
                    <tr
                      key={c.name}
                      onClick={() => setSelectedCheck(c.name)}
                      className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-2.5 font-data text-zinc-200">{c.name}</td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex items-center gap-1 ${sc.color}`}>
                          <sc.icon className="w-3 h-3" /> {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-data text-zinc-300">{formatLatency(c.latency_ms)}</td>
                      <td className="px-4 py-2.5 text-zinc-500 text-[10px] max-w-[400px] truncate">{detailStr || "—"}</td>
                    </tr>
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
