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

const COLORS = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#ec4899"];

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
        <button onClick={onBack} className="w-8 h-8 rounded-lg bg-white/[0.04] flex items-center justify-center hover:bg-white/[0.08] transition-colors">
          <ArrowLeft className="w-4 h-4 text-zinc-400" />
        </button>
        <div>
          <h2 className="text-lg font-bold text-zinc-100 font-data">{modelId}</h2>
          <p className="text-[10px] text-zinc-500 uppercase tracking-widest">Model Metrics</p>
        </div>
      </div>

      {loading && !rawMetrics && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Loading metrics…
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Latency Distribution */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
              <Clock className="w-3.5 h-3.5" /> Latency Distribution
            </span>
          </div>
          <div className="p-4 space-y-3">
            {[
              { label: "p50", value: metrics.latency.p50_ms, color: "#10b981" },
              { label: "p95", value: metrics.latency.p95_ms, color: "#f59e0b" },
              { label: "p99", value: metrics.latency.p99_ms, color: "#ef4444" },
            ].map(p => (
              <div key={p.label}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-zinc-400 uppercase font-mono">{p.label}</span>
                  <span className="font-data text-zinc-200">{formatLatency(p.value)}</span>
                </div>
                <div className="h-2 rounded-full bg-white/[0.04] overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${maxLatency > 0 ? (p.value / maxLatency) * 100 : 0}%`, background: p.color }} />
                </div>
              </div>
            ))}
            <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-xs">
              <span className="text-zinc-500">Average</span>
              <span className="font-data text-cyan-400">{formatLatency(metrics.latency.avg_ms)}</span>
            </div>
          </div>
        </div>

        {/* Token Efficiency */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
              <Zap className="w-3.5 h-3.5" /> Token Efficiency
            </span>
          </div>
          <div className="p-4 space-y-4">
            {/* Input/Output ratio bar */}
            <div>
              <div className="flex items-center justify-between text-[10px] text-zinc-500 mb-1.5">
                <span>Input ({inputPct.toFixed(0)}%)</span>
                <span>Output ({(100 - inputPct).toFixed(0)}%)</span>
              </div>
              <div className="h-3 rounded-full overflow-hidden flex">
                <div className="h-full bg-cyan-500/60 transition-all" style={{ width: `${inputPct}%` }} />
                <div className="h-full bg-purple-500/60 transition-all" style={{ width: `${100 - inputPct}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Total Input", value: formatTokens(metrics.tokens.total_input), color: "text-cyan-400" },
                { label: "Total Output", value: formatTokens(metrics.tokens.total_output), color: "text-purple-400" },
                { label: "Avg Input/Req", value: formatTokens(metrics.tokens.avg_input_per_request), color: "text-cyan-400" },
                { label: "Avg Output/Req", value: formatTokens(metrics.tokens.avg_output_per_request), color: "text-purple-400" },
              ].map(s => (
                <div key={s.label} className="text-center p-2 rounded-lg bg-white/[0.02]">
                  <div className={`text-lg font-bold font-data ${s.color}`}>{s.value}</div>
                  <div className="text-[10px] text-zinc-600 uppercase tracking-wider">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Hourly Requests/Errors */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Requests & Errors (24h)</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 font-medium">Hourly</span>
        </div>
        <div className="p-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={metrics.hourly} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="errGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} width={36} />
              <Tooltip
                contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }}
              />
              <Area type="monotone" dataKey="requests" stroke="#06b6d4" fill="url(#reqGrad)" strokeWidth={2} name="Requests" />
              <Area type="monotone" dataKey="errors" stroke="#ef4444" fill="url(#errGrad)" strokeWidth={1.5} name="Errors" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Cost per Request Trend */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06]">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
            <TrendingUp className="w-3.5 h-3.5" /> Cost per Request Trend
          </span>
        </div>
        <div className="p-4 h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={metrics.cost_per_request_trend} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="cprGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} width={48}
                tickFormatter={(v: number) => `$${v.toFixed(3)}`} />
              <Tooltip
                contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }}
                formatter={(v: number) => [`$${v.toFixed(5)}`, "Cost/Request"]}
              />
              <Area type="monotone" dataKey="cost_per_request" stroke="#f59e0b" fill="url(#cprGrad)" strokeWidth={2} />
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
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Observatory API…
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          { icon: Activity, color: "text-cyan-500", label: "Total Requests", value: summary.total_requests.toLocaleString() },
          { icon: DollarSign, color: "text-amber-500", label: "Total Cost", value: `$${summary.total_cost_usd.toFixed(2)}` },
          { icon: AlertTriangle, color: "text-red-500", label: "Error Rate", value: `${(summary.error_rate * 100).toFixed(1)}%` },
          { icon: Cpu, color: "text-violet-500", label: "Models", value: String(summary.unique_models) },
          { icon: Bot, color: "text-emerald-500", label: "Agents", value: String(summary.unique_agents) },
        ].map(s => (
          <div key={s.label} className="card-dark p-4 flex items-center gap-3">
            <s.icon className={`w-5 h-5 ${s.color}`} />
            <div>
              <div className="text-sm font-data text-zinc-200">{s.value}</div>
              <div className="text-[10px] text-zinc-600 uppercase">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Model Table */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
            <Telescope className="w-3.5 h-3.5" /> Model Overview
          </span>
          <span className="text-[10px] text-zinc-600">{models.length} models</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/[0.06]">
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
                    className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium cursor-pointer hover:text-zinc-300 transition-colors select-none whitespace-nowrap">
                    {label}{sortIndicator(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => (
                <tr key={m.model_id}
                  onClick={() => setSelectedModel(m.model_id)}
                  className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-data text-zinc-200">{m.model_id}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                      style={{ background: `${COLORS[i % COLORS.length]}15`, color: COLORS[i % COLORS.length] }}>
                      {m.provider}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-data text-zinc-300">{m.request_count.toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <span className={`font-data ${m.error_rate > 0.05 ? "text-red-400" : m.error_rate > 0.02 ? "text-amber-400" : "text-emerald-400"}`}>
                      {(m.error_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 font-data text-zinc-300">{formatLatency(m.avg_latency_ms)}</td>
                  <td className="px-4 py-3 font-data text-amber-400">${m.total_cost_usd.toFixed(2)}</td>
                  <td className="px-4 py-3 text-zinc-500 font-data">{formatTimeAgo(m.last_used)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Model Cost Distribution */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06]">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Cost by Model</span>
        </div>
        <div className="p-4 h-48">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={models} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={true} vertical={false} />
              <XAxis dataKey="model_id" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false}
                tickFormatter={(v: number) => `$${v}`} width={40} />
              <Tooltip
                contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }}
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
