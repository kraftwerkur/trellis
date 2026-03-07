"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { CostSummary, CostTimeseriesBucket, GatewayStatsResponse, FinOpsSummary } from "@/types/trellis";
import { DollarSign, TrendingUp, Users, Cpu, Target } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, PieChart, Pie,
} from "recharts";

const COLORS = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#ec4899"];
const BUDGET_CAP_DAILY = 25.0;
const BUDGET_CAP_MONTHLY = 500.0;

export default function FinOpsPage() {
  const [granularity, setGranularity] = useState<"hour" | "day" | "week">("day");

  const fetchTimeseries = useCallback(() => api.costs.timeseries(granularity), [granularity]);
  const fetchSummary = useCallback(() => api.costs.summary(), []);
  const fetchFinops = useCallback(() => api.finops.summary(), []);
  const fetchStats = useCallback(() => api.gateway.stats(), []);

  const { data: rawTimeseries, loading: loadingTimeseries } = useStablePolling<CostTimeseriesBucket[]>(fetchTimeseries, 30000);
  const { data: rawSummary, loading: loadingSummary } = useStablePolling<CostSummary[]>(fetchSummary, 30000);
  const { data: rawFinops } = useStablePolling<FinOpsSummary>(fetchFinops, 30000);
  const { data: rawStats } = useStablePolling<GatewayStatsResponse>(fetchStats, 30000);

  const timeseries = rawTimeseries ?? [];
  const summary = useMemo(() => rawSummary ?? [], [rawSummary]);
  const stats = rawStats ?? null;

  const totalCost = rawFinops?.spend_this_month_usd ?? summary.reduce((s, c) => s + c.total_cost_usd, 0);
  const totalRequests = rawFinops?.total_requests ?? summary.reduce((s, c) => s + c.request_count, 0);

  const deptData = useMemo(() => {
    const m: Record<string, number> = {};
    summary.forEach(s => {
      const dept = s.agent_id.split("-")[0] || "unknown";
      m[dept] = (m[dept] || 0) + s.total_cost_usd;
    });
    return Object.entries(m).map(([name, value]) => ({ name, value: +value.toFixed(4) }))
      .sort((a, b) => b.value - a.value);
  }, [summary]);

  const modelData = useMemo(() => {
    if (stats?.requests_by_provider && Object.keys(stats.requests_by_provider).length > 0) {
      return Object.entries(stats.requests_by_provider)
        .map(([model, requests]) => ({ model, requests }))
        .sort((a, b) => b.requests - a.requests).slice(0, 8);
    }
    return [];
  }, [stats]);

  const todayCost = rawFinops?.spend_today_usd ?? (timeseries.length > 0 ? timeseries[timeseries.length - 1].total_cost_usd : 0);
  const dailyPct = Math.min((todayCost / BUDGET_CAP_DAILY) * 100, 100);
  const monthlyPct = Math.min((totalCost / BUDGET_CAP_MONTHLY) * 100, 100);

  const isLoading = loadingTimeseries && loadingSummary;

  return (
    <div className="space-y-4">
      {isLoading && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Trellis API…
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
          {timeseries.length === 0 ? (
            <div className="text-center text-zinc-600 py-8 text-sm">No cost data yet</div>
          ) : (
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
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Cost by Department (Donut) */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Cost by Department</span>
          </div>
          <div className="p-4 h-64 flex items-center">
            {deptData.length === 0 ? (
              <div className="text-center text-zinc-600 py-8 text-sm w-full">No cost data yet</div>
            ) : (
              <>
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
              </>
            )}
          </div>
        </div>

        {/* Cost by Agent (BarList) */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Top Agents by Spend</span>
          </div>
          <div className="p-4 space-y-2">
            {summary.length === 0 ? (
              <div className="text-center text-zinc-600 py-8 text-sm">No agent cost data yet</div>
            ) : (
              summary.slice(0, 6).map((s, i) => {
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
              })
            )}
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
            {modelData.length === 0 ? (
              <div className="text-center text-zinc-600 py-8 text-sm">No model usage data yet</div>
            ) : (
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
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
