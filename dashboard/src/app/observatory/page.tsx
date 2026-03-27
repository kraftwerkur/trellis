"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { ObservatorySummary, ObservatoryModel, ObservatoryModelMetrics } from "@/types/trellis";
import {
  Telescope, Activity, DollarSign, AlertTriangle, Bot, Clock, ArrowLeft,
  Cpu, Zap, TrendingUp,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "@/lib/charts";

/* ─── Mock Data (demo mode fallback) ─── */

const MOCK_SUMMARY: ObservatorySummary = {
  total_requests: 14832,
  total_cost_usd: 47.63,
  error_rate: 0.023,
  unique_models: 6,
  unique_agents: 4,
  period_start: new Date(Date.now() - 7 * 86400000).toISOString(),
  period_end: new Date().toISOString(),
};

const MOCK_MODELS: ObservatoryModel[] = [
  { model_id: "claude-opus-4", provider: "anthropic", request_count: 4210, error_count: 42, error_rate: 0.01, avg_latency_ms: 2340, total_cost_usd: 18.42, total_input_tokens: 12600000, total_output_tokens: 4200000, last_used: new Date(Date.now() - 120000).toISOString() },
  { model_id: "claude-sonnet-4", provider: "anthropic", request_count: 6120, error_count: 183, error_rate: 0.03, avg_latency_ms: 890, total_cost_usd: 12.85, total_input_tokens: 18360000, total_output_tokens: 6120000, last_used: new Date(Date.now() - 60000).toISOString() },
  { model_id: "gpt-4o", provider: "openai", request_count: 2100, error_count: 63, error_rate: 0.03, avg_latency_ms: 1560, total_cost_usd: 9.24, total_input_tokens: 6300000, total_output_tokens: 2100000, last_used: new Date(Date.now() - 300000).toISOString() },
  { model_id: "gemini-2.5-pro", provider: "google", request_count: 1800, error_count: 18, error_rate: 0.01, avg_latency_ms: 1120, total_cost_usd: 5.40, total_input_tokens: 5400000, total_output_tokens: 1800000, last_used: new Date(Date.now() - 600000).toISOString() },
  { model_id: "gemini-2.5-flash", provider: "google", request_count: 502, error_count: 25, error_rate: 0.05, avg_latency_ms: 420, total_cost_usd: 0.82, total_input_tokens: 1506000, total_output_tokens: 502000, last_used: new Date(Date.now() - 1800000).toISOString() },
  { model_id: "llama-3.1-8b", provider: "ollama", request_count: 100, error_count: 8, error_rate: 0.08, avg_latency_ms: 340, total_cost_usd: 0.00, total_input_tokens: 300000, total_output_tokens: 100000, last_used: new Date(Date.now() - 7200000).toISOString() },
];

function generateMockMetrics(modelId: string): ObservatoryModelMetrics {
  const hours = Array.from({ length: 24 }, (_, i) => {
    const h = new Date(Date.now() - (23 - i) * 3600000);
    return `${String(h.getHours()).padStart(2, "0")}:00`;
  });
  return {
    model_id: modelId,
    latency: { p50_ms: 820, p95_ms: 2100, p99_ms: 4500, avg_ms: 1120 },
    tokens: { total_input: 5400000, total_output: 1800000, avg_input_per_request: 3000, avg_output_per_request: 1000 },
    hourly: hours.map(hour => ({
      hour,
      requests: Math.floor(Math.random() * 200 + 50),
      errors: Math.floor(Math.random() * 10),
      avg_latency_ms: Math.floor(Math.random() * 800 + 600),
      cost_usd: +(Math.random() * 2 + 0.1).toFixed(4),
    })),
    cost_per_request_trend: hours.map(hour => ({
      hour,
      cost_per_request: +(Math.random() * 0.005 + 0.001).toFixed(5),
    })),
  };
}

/* ─── Helpers ─── */

const COLORS = ["var(--color-primary)", "var(--color-chart-4)", "var(--color-status-warning)", "var(--color-status-healthy)", "var(--color-destructive)", "var(--color-chart-5)"];

function formatTimeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function formatLatency(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

/* ─── Sort logic ─── */

type SortKey = "model_id" | "provider" | "request_count" | "error_rate" | "avg_latency_ms" | "total_cost_usd" | "last_used";
type SortDir = "asc" | "desc";

function sortModels(models: ObservatoryModel[], key: SortKey, dir: SortDir): ObservatoryModel[] {
  return [...models].sort((a, b) => {
    let av: string | number = a[key] as string | number;
    let bv: string | number = b[key] as string | number;
    if (key === "last_used") { av = new Date(av).getTime(); bv = new Date(bv).getTime(); }
    if (av < bv) return dir === "asc" ? -1 : 1;
    if (av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

/* ─── Model Detail View ─── */

function ModelDetailView({ modelId, onBack }: { modelId: string; onBack: () => void }) {
  const fetchMetrics = useCallback(() => api.observatory.modelMetrics(modelId), [modelId]);
  const { data: rawMetrics, loading } = useStablePolling<ObservatoryModelMetrics>(fetchMetrics, 15000);
  const metrics = rawMetrics ?? generateMockMetrics(modelId);

  const maxLatency = Math.max(metrics.latency.p50_ms, metrics.latency.p95_ms, metrics.latency.p99_ms);
  const totalTokens = metrics.tokens.total_input + metrics.tokens.total_output;
  const inputPct = totalTokens > 0 ? (metrics.tokens.total_input / totalTokens) * 100 : 50;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="w-8 h-8 rounded-lg bg-muted/10 flex items-center justify-center hover:bg-muted/20 transition-colors">
          <ArrowLeft className="w-4 h-4 text-muted-foreground" />
        </button>
        <div>
          <h2 className="text-lg font-bold text-foreground font-data">{modelId}</h2>
          <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Model Metrics</p>
        </div>
      </div>

      {loading && !rawMetrics && (
        <div className="text-[10px] text-muted-foreground bg-muted/50 border border-border rounded-lg px-3 py-1.5 text-center animate-pulse">
          Loading metrics…
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Latency Distribution */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium flex items-center gap-2">
              <Clock className="w-3.5 h-3.5" /> Latency Distribution
            </span>
          </div>
          <div className="p-4 space-y-3">
            {[
              { label: "p50", value: metrics.latency.p50_ms, color: "var(--color-status-healthy)" },
              { label: "p95", value: metrics.latency.p95_ms, color: "var(--color-status-warning)" },
              { label: "p99", value: metrics.latency.p99_ms, color: "var(--color-destructive)" },
            ].map(p => (
              <div key={p.label}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-muted-foreground uppercase font-mono">{p.label}</span>
                  <span className="font-data text-foreground">{formatLatency(p.value)}</span>
                </div>
                <div className="h-2 rounded-full bg-muted/10 overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${maxLatency > 0 ? (p.value / maxLatency) * 100 : 0}%`, background: p.color }} />
                </div>
              </div>
            ))}
            <div className="pt-2 border-t border-border flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Average</span>
              <span className="font-data text-primary">{formatLatency(metrics.latency.avg_ms)}</span>
            </div>
          </div>
        </div>

        {/* Token Efficiency */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium flex items-center gap-2">
              <Zap className="w-3.5 h-3.5" /> Token Efficiency
            </span>
          </div>
          <div className="p-4 space-y-4">
            {/* Input/Output ratio bar */}
            <div>
              <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1.5">
                <span>Input ({inputPct.toFixed(0)}%)</span>
                <span>Output ({(100 - inputPct).toFixed(0)}%)</span>
              </div>
              <div className="h-3 rounded-full overflow-hidden flex">
                <div className="h-full bg-primary/60 transition-all" style={{ width: `${inputPct}%` }} />
                <div className="h-full bg-chart-4/60 transition-all" style={{ width: `${100 - inputPct}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Total Input", value: formatTokens(metrics.tokens.total_input), color: "text-primary" },
                { label: "Total Output", value: formatTokens(metrics.tokens.total_output), color: "text-chart-4" },
                { label: "Avg Input/Req", value: formatTokens(metrics.tokens.avg_input_per_request), color: "text-primary" },
                { label: "Avg Output/Req", value: formatTokens(metrics.tokens.avg_output_per_request), color: "text-chart-4" },
              ].map(s => (
                <div key={s.label} className="text-center p-2 rounded-lg bg-muted/5">
                  <div className={`text-lg font-bold font-data ${s.color}`}>{s.value}</div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Hourly Requests/Errors */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Requests & Errors (24h)</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">Hourly</span>
        </div>
        <div className="p-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={metrics.hourly} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-primary)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--color-primary)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="errGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-destructive)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--color-destructive)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} width={36} />
              <Tooltip
                contentStyle={{ background: "var(--color-card)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "var(--color-muted-foreground)" }}
              />
              <Area type="monotone" dataKey="requests" stroke="var(--color-primary)" fill="url(#reqGrad)" strokeWidth={2} name="Requests" />
              <Area type="monotone" dataKey="errors" stroke="var(--color-destructive)" fill="url(#errGrad)" strokeWidth={1.5} name="Errors" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Cost per Request Trend */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium flex items-center gap-2">
            <TrendingUp className="w-3.5 h-3.5" /> Cost per Request Trend
          </span>
        </div>
        <div className="p-4 h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={metrics.cost_per_request_trend} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="cprGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-status-warning)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--color-status-warning)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} width={48}
                tickFormatter={(v: number) => `$${v.toFixed(3)}`} />
              <Tooltip
                contentStyle={{ background: "var(--color-card)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "var(--color-muted-foreground)" }}
                formatter={(v: number) => [`$${v.toFixed(5)}`, "Cost/Request"]}
              />
              <Area type="monotone" dataKey="cost_per_request" stroke="var(--color-status-warning)" fill="url(#cprGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Observatory Page ─── */

export default function ObservatoryPage() {
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("total_cost_usd");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const fetchSummary = useCallback(() => api.observatory.summary(), []);
  const fetchModels = useCallback(() => api.observatory.models(), []);

  const { data: rawSummary, loading: loadingSummary } = useStablePolling<ObservatorySummary>(fetchSummary, 15000);
  const { data: rawModels, loading: loadingModels } = useStablePolling<ObservatoryModel[]>(fetchModels, 15000);

  const summary = rawSummary ?? MOCK_SUMMARY;
  const models = useMemo(() => sortModels(rawModels ?? MOCK_MODELS, sortKey, sortDir), [rawModels, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const isLoading = loadingSummary && loadingModels;

  if (selectedModel) {
    return <ModelDetailView modelId={selectedModel} onBack={() => setSelectedModel(null)} />;
  }

  const sortIndicator = (key: SortKey) => sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  return (
    <div className="space-y-4">
      {isLoading && (
        <div className="text-[10px] text-muted-foreground bg-muted/50 border border-border rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Observatory API…
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          { icon: Activity, color: "text-primary", label: "Total Requests", value: summary.total_requests.toLocaleString() },
          { icon: DollarSign, color: "text-status-warning", label: "Total Cost", value: `$${summary.total_cost_usd.toFixed(2)}` },
          { icon: AlertTriangle, color: "text-destructive", label: "Error Rate", value: `${(summary.error_rate * 100).toFixed(1)}%` },
          { icon: Cpu, color: "text-chart-4", label: "Models", value: String(summary.unique_models) },
          { icon: Bot, color: "text-status-healthy", label: "Agents", value: String(summary.unique_agents) },
        ].map(s => (
          <div key={s.label} className="card-dark p-4 flex items-center gap-3">
            <s.icon className={`w-5 h-5 ${s.color}`} />
            <div>
              <div className="text-sm font-data text-foreground">{s.value}</div>
              <div className="text-[10px] text-muted-foreground uppercase">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Model Table */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium flex items-center gap-2">
            <Telescope className="w-3.5 h-3.5" /> Model Overview
          </span>
          <span className="text-[10px] text-muted-foreground">{models.length} models</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                {([
                  ["model_id", "Model"],
                  ["provider", "Provider"],
                  ["request_count", "Requests"],
                  ["error_rate", "Error Rate"],
                  ["avg_latency_ms", "Avg Latency"],
                  ["total_cost_usd", "Total Cost"],
                  ["last_used", "Last Used"],
                ] as [SortKey, string][]).map(([key, label]) => (
                  <th key={key}
                    onClick={() => handleSort(key)}
                    className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-muted-foreground font-medium cursor-pointer hover:text-foreground/80 transition-colors select-none whitespace-nowrap">
                    {label}{sortIndicator(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => (
                <tr key={m.model_id}
                  onClick={() => setSelectedModel(m.model_id)}
                  className="border-b border-border/60 hover:bg-muted/5 cursor-pointer transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-data text-foreground">{m.model_id}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                      style={{ background: `${COLORS[i % COLORS.length]}15`, color: COLORS[i % COLORS.length] }}>
                      {m.provider}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-data text-foreground/80">{m.request_count.toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <span className={`font-data ${m.error_rate > 0.05 ? "text-destructive" : m.error_rate > 0.02 ? "text-status-warning" : "text-status-healthy"}`}>
                      {(m.error_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 font-data text-foreground/80">{formatLatency(m.avg_latency_ms)}</td>
                  <td className="px-4 py-3 font-data text-status-warning">${m.total_cost_usd.toFixed(2)}</td>
                  <td className="px-4 py-3 text-muted-foreground font-data">{formatTimeAgo(m.last_used)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Model Cost Distribution */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border">
          <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Cost by Model</span>
        </div>
        <div className="p-4 h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={models} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={true} vertical={false} />
              <XAxis dataKey="model_id" tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false}
                tickFormatter={(v: number) => `$${v}`} width={40} />
              <Tooltip
                contentStyle={{ background: "var(--color-card)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "var(--color-muted-foreground)" }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, "Cost"]}
              />
              <Bar dataKey="total_cost_usd" radius={[4, 4, 0, 0]}>
                {models.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
