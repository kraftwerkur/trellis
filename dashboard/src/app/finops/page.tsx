"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { CostSummary, CostTimeseriesBucket, GatewayStatsResponse, CostEvent, FinOpsSummary } from "@/types/trellis";
import { DollarSign, TrendingUp, Users, Cpu, Target } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, PieChart, Pie,
} from "recharts";

// Mock fallback data when backend is unavailable
const MOCK_TIMESERIES: CostTimeseriesBucket[] = [
  { bucket: "2026-02-21", total_cost_usd: 1.24, total_tokens_in: 42000, total_tokens_out: 18000, request_count: 34 },
  { bucket: "2026-02-22", total_cost_usd: 2.18, total_tokens_in: 68000, total_tokens_out: 31000, request_count: 52 },
  { bucket: "2026-02-23", total_cost_usd: 1.87, total_tokens_in: 55000, total_tokens_out: 24000, request_count: 41 },
  { bucket: "2026-02-24", total_cost_usd: 3.42, total_tokens_in: 98000, total_tokens_out: 45000, request_count: 78 },
  { bucket: "2026-02-25", total_cost_usd: 2.95, total_tokens_in: 82000, total_tokens_out: 38000, request_count: 65 },
  { bucket: "2026-02-26", total_cost_usd: 4.11, total_tokens_in: 112000, total_tokens_out: 52000, request_count: 91 },
  { bucket: "2026-02-27", total_cost_usd: 3.56, total_tokens_in: 95000, total_tokens_out: 44000, request_count: 73 },
];

const MOCK_SUMMARY: CostSummary[] = [
  { agent_id: "compliance-checker", total_cost_usd: 5.82, total_tokens_in: 180000, total_tokens_out: 85000, request_count: 142 },
  { agent_id: "doc-summarizer", total_cost_usd: 4.21, total_tokens_in: 130000, total_tokens_out: 62000, request_count: 98 },
  { agent_id: "risk-assessor", total_cost_usd: 3.45, total_tokens_in: 95000, total_tokens_out: 48000, request_count: 76 },
  { agent_id: "data-analyst", total_cost_usd: 2.18, total_tokens_in: 68000, total_tokens_out: 30000, request_count: 54 },
  { agent_id: "email-responder", total_cost_usd: 1.67, total_tokens_in: 52000, total_tokens_out: 24000, request_count: 64 },
];

const MOCK_STATS: GatewayStatsResponse = {
  total_requests: 434, total_tokens: 774000, total_cost: 17.33,
  requests_by_provider: { openai: 245, anthropic: 142, google: 47 },
  avg_tokens_per_request: 1783.4,
};

const COLORS = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#ec4899"];
const BUDGET_CAP_DAILY = 25.0; // example cap
const BUDGET_CAP_MONTHLY = 500.0;

export default function FinOpsPage() {
  const [granularity, setGranularity] = useState<"hour" | "day" | "week">("day");

  const fetchTimeseries = useCallback(() => api.costs.timeseries(granularity), [granularity]);
  const fetchSummary = useCallback(() => api.costs.summary(), []);
  const fetchFinops = useCallback(() => api.finops.summary(), []);
  const fetchStats = useCallback(() => api.gateway.stats(), []);

  const { data: rawTimeseries } = useStablePolling(fetchTimeseries, 30000);
  const { data: rawSummary } = useStablePolling(fetchSummary, 30000);
  const { data: rawFinops } = useStablePolling<FinOpsSummary>(fetchFinops, 30000);
  const { data: rawStats } = useStablePolling(fetchStats, 30000);

  const timeseries = rawTimeseries ?? MOCK_TIMESERIES;
  const summary = rawSummary ?? MOCK_SUMMARY;
  const stats = rawStats ?? MOCK_STATS;
  const isMock = !rawTimeseries;

  // Use finops summary if available, otherwise derive from cost summary
  const totalCost = rawFinops?.spend_this_month_usd ?? summary.reduce((s, c) => s + c.total_cost_usd, 0);
  const totalRequests = rawFinops?.total_requests ?? summary.reduce((s, c) => s + c.request_count, 0);

  // Department rollup (use agent_id prefix as pseudo-department)
  const deptData = useMemo(() => {
    const m: Record<string, number> = {};
    summary.forEach(s => {
      const dept = s.agent_id.split("-")[0] || "unknown";
      m[dept] = (m[dept] || 0) + s.total_cost_usd;
    });
    return Object.entries(m).map(([name, value]) => ({ name, value: +value.toFixed(4) }))
      .sort((a, b) => b.value - a.value);
  }, [summary]);

  // Model usage from gateway stats provider breakdown
  const modelData = useMemo(() => {
    if (stats?.requests_by_provider && Object.keys(stats.requests_by_provider).length > 0) {
      return Object.entries(stats.requests_by_provider)
        .map(([model, requests]) => ({ model, requests }))
        .sort((a, b) => b.requests - a.requests).slice(0, 8);
    }
    // fallback mock
    return [
      { model: "gpt-4o", requests: 186 },
      { model: "claude-3.5-sonnet", requests: 142 },
      { model: "gemini-2.0-flash", requests: 47 },
      { model: "gpt-4o-mini", requests: 59 },
    ];
  }, [stats]);

  // Budget calculations
  const todayCost = rawFinops?.spend_today_usd ?? (timeseries.length > 0 ? timeseries[timeseries.length - 1].total_cost_usd : 0);
  const dailyPct = Math.min((todayCost / BUDGET_CAP_DAILY) * 100, 100);
  const monthlyPct = Math.min((totalCost / BUDGET_CAP_MONTHLY) * 100, 100);

  return (
    <div className="space-y-4">
      {isMock && (
        <div className="text-[10px] text-amber-500/60 uppercase tracking-widest">
          ⚠ Showing mock data — backend unavailable
        </div>
      )}

      {/* Top stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: DollarSign, color: "text-amber-500", label: "Total Spend", value: `$${totalCost.toFixed(2)}` },
          { icon: TrendingUp, color: "text-cyan-500", label: "Today", value: `$${todayCost.toFixed(2)}` },
          { icon: Users, color: "text-violet-500", label: "Active Agents", value: String(summary.length) },
          { icon: Cpu, color: "text-emerald-500", label: "Total Requests", value: String(totalRequests) },
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

      {/* Cost Over Time */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Cost Over Time</span>
          <div className="flex gap-1">
            {(["hour", "day", "week"] as const).map(g => (
              <button key={g} onClick={() => setGranularity(g)}
                className={`px-2 py-0.5 text-[10px] uppercase rounded ${granularity === g ? "bg-cyan-500/20 text-cyan-400" : "text-zinc-600 hover:text-zinc-400"}`}>
                {g}
              </button>
            ))}
          </div>
        </div>
        <div className="p-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={timeseries}>
              <defs>
                <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
              <Tooltip contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#a1a1aa" }} itemStyle={{ color: "#06b6d4" }} formatter={(v: number) => [`$${v.toFixed(4)}`, "Cost"]} />
              <Area type="monotone" dataKey="total_cost_usd" stroke="#06b6d4" fill="url(#costGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Cost by Department (Donut) */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Cost by Department</span>
          </div>
          <div className="p-4 h-64 flex items-center">
            <div className="w-1/2 h-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={deptData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                    innerRadius={45} outerRadius={75} strokeWidth={0}>
                    {deptData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`$${v.toFixed(4)}`]} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="w-1/2 space-y-1.5 pl-2">
              {deptData.map((d, i) => (
                <div key={d.name} className="flex items-center gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                  <span className="text-zinc-400 truncate">{d.name}</span>
                  <span className="ml-auto font-data text-zinc-300">${d.value.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Cost by Agent (BarList) */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Top Agents by Spend</span>
          </div>
          <div className="p-4 space-y-2">
            {summary.slice(0, 6).map((s, i) => {
              const maxCost = summary[0]?.total_cost_usd || 1;
              const pct = (s.total_cost_usd / maxCost) * 100;
              return (
                <div key={s.agent_id}>
                  <div className="flex items-center justify-between text-xs mb-0.5">
                    <span className="text-zinc-400 truncate font-mono text-[11px]">{s.agent_id}</span>
                    <span className="font-data text-amber-400">${s.total_cost_usd.toFixed(4)}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/[0.04] overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: COLORS[i % COLORS.length] }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Budget Tracker */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
              <Target className="w-3.5 h-3.5" /> Budget Tracker
            </span>
          </div>
          <div className="p-4 space-y-4">
            {[
              { label: "Daily Budget", current: todayCost, cap: BUDGET_CAP_DAILY, pct: dailyPct },
              { label: "Monthly Budget", current: totalCost, cap: BUDGET_CAP_MONTHLY, pct: monthlyPct },
            ].map(b => (
              <div key={b.label}>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="text-zinc-400">{b.label}</span>
                  <span className="font-data text-zinc-300">${b.current.toFixed(2)} / ${b.cap.toFixed(0)}</span>
                </div>
                <div className="h-2.5 rounded-full bg-white/[0.04] overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${b.pct}%`,
                      background: b.pct > 90 ? "#ef4444" : b.pct > 70 ? "#f59e0b" : "#10b981",
                    }} />
                </div>
                <div className="text-[10px] text-zinc-600 mt-0.5">{b.pct.toFixed(1)}% used</div>
              </div>
            ))}
          </div>
        </div>

        {/* Model Usage */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Model Usage</span>
          </div>
          <div className="p-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={modelData} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="model" tick={{ fontSize: 10, fill: "#71717a" }} tickLine={false} axisLine={false} width={120} />
                <Tooltip contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "#a1a1aa" }} />
                <Bar dataKey="requests" radius={[0, 4, 4, 0]}>
                  {modelData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
