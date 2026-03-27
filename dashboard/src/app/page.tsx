"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent, AuditEvent, CostSummary, CostTimeseriesBucket } from "@/types/trellis";
import {
  Bot, Activity, Shield, DollarSign, HeartPulse,
  TrendingUp, TrendingDown, Zap, Lock, Gauge,
  AlertTriangle, Check, Settings, UserPlus, Key, GitBranch,
} from "lucide-react";
import {
  AreaChart as RechartsAreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis,
  PieChart, Pie, Cell, CartesianGrid,
} from "@/lib/charts";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/* ─── Sparkline (small inline chart, keep recharts for this) ─── */

function Sparkline({ data, color = "#22d3ee", height = 32 }: { data: number[]; color?: string; height?: number }) {
  const chartData = data.map((v, i) => ({ v, i }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsAreaChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <defs>
          <linearGradient id={`spark-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#spark-${color.replace("#", "")})`}
          dot={false}
          isAnimationActive={false}
        />
      </RechartsAreaChart>
    </ResponsiveContainer>
  );
}

/* ─── Stat Card (shadcn Card based) ─── */

function StatCard({ label, value, icon: Icon, accent, trend, sparkData }: {
  label: string;
  value: string;
  icon: React.ElementType;
  accent: string;
  trend?: { direction: "up" | "down" | "flat"; label: string };
  sparkData?: number[];
}) {
  const accentColors: Record<string, { text: string; bg: string; spark: string }> = {
    cyan: { text: "text-cyan-400", bg: "bg-cyan-500/10", spark: "#22d3ee" },
    emerald: { text: "text-emerald-400", bg: "bg-emerald-500/10", spark: "#34d399" },
    blue: { text: "text-blue-400", bg: "bg-blue-500/10", spark: "#60a5fa" },
    red: { text: "text-red-400", bg: "bg-red-500/10", spark: "#f87171" },
    amber: { text: "text-amber-400", bg: "bg-amber-500/10", spark: "#fbbf24" },
    purple: { text: "text-purple-400", bg: "bg-purple-500/10", spark: "#c084fc" },
  };
  const c = accentColors[accent] ?? accentColors.cyan;

  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0 hover:border-[hsl(var(--primary))]/20 transition-colors">
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${c.bg}`}>
            <Icon className={`w-4 h-4 ${c.text}`} />
          </div>
          {trend && (
            <Badge variant="outline" className={`text-[10px] border-0 px-1.5 py-0 font-medium ${
              trend.direction === "up" ? "text-[hsl(var(--status-healthy))]" : trend.direction === "down" ? "text-[hsl(var(--status-critical))]" : "text-[hsl(var(--muted-foreground))]"
            }`}>
              {trend.direction === "up" ? <TrendingUp className="w-3 h-3 mr-1" /> : trend.direction === "down" ? <TrendingDown className="w-3 h-3 mr-1" /> : null}
              {trend.label}
            </Badge>
          )}
        </div>
        <div>
          <div className="text-2xl font-bold font-data text-[hsl(var(--foreground))]">{value}</div>
          <div className="text-[10px] text-[hsl(var(--muted-foreground))] uppercase tracking-widest">{label}</div>
        </div>
        {sparkData && sparkData.length > 1 && (
          <div className="pt-1">
            <Sparkline data={sparkData} color={c.spark} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Activity Timeline ─── */

const EVENT_CONFIG: Record<string, { color: string; icon: React.ElementType; label: string }> = {
  envelope_received: { color: "text-cyan-400", icon: Zap, label: "Envelope Received" },
  rule_matched: { color: "text-amber-400", icon: GitBranch, label: "Rule Matched" },
  rule_triggered: { color: "text-amber-400", icon: AlertTriangle, label: "Rule Triggered" },
  agent_dispatched: { color: "text-blue-400", icon: Bot, label: "Agent Dispatched" },
  agent_responded: { color: "text-emerald-400", icon: Check, label: "Agent Responded" },
  phi_detected: { color: "text-red-400", icon: Lock, label: "PHI Blocked" },
  phi_blocked: { color: "text-red-400", icon: Lock, label: "PHI Blocked" },
  rule_changed: { color: "text-purple-400", icon: Settings, label: "Rule Changed" },
  agent_registered: { color: "text-green-400", icon: UserPlus, label: "Agent Registered" },
  key_created: { color: "text-yellow-400", icon: Key, label: "Key Created" },
  agent_action: { color: "text-cyan-400", icon: Zap, label: "Agent Action" },
  budget_alert: { color: "text-purple-400", icon: DollarSign, label: "Budget Alert" },
};

function formatTimeAgo(ts: string) {
  const date = new Date(ts);
  if (isNaN(date.getTime())) return "—";
  const diff = Date.now() - date.getTime();
  if (diff < 0) return "just now";
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const DEFAULT_EVENT_CFG = { color: "text-zinc-400", icon: Activity, label: "" };

function eventSummary(e: AuditEvent): string {
  const d = e.details || {};
  if (d.message) return String(d.message);
  if (d.rule_name) return `Rule: ${d.rule_name}`;
  if (d.rule) return `Rule: ${d.rule}`;
  if (d.status) return String(d.status);
  if (d.dispatch_status) return String(d.dispatch_status);
  if (d.agent_name) return `Agent: ${d.agent_name}`;
  if (d.channel) return `Channel: ${d.channel}`;
  if (d.reason) return String(d.reason);
  return e.event_type.replace(/_/g, " ");
}

function ActivityTimeline({ events, agentMap }: { events: AuditEvent[]; agentMap: Record<string, Agent> }) {
  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
      <CardHeader className="flex-row items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
        <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Activity Feed</CardTitle>
        <span className="live-pulse w-2 h-2 rounded-full bg-emerald-500 inline-block" />
      </CardHeader>
      <CardContent className="p-0 divide-y divide-white/[0.04] max-h-[400px] overflow-y-auto">
        {events.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No recent activity</div>
        ) : (
          events.map(e => {
            const cfg = EVENT_CONFIG[e.event_type] ?? { ...DEFAULT_EVENT_CFG, label: e.event_type.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) };
            const IconComp = cfg.icon;
            const agentName = e.agent_id ? (agentMap[e.agent_id]?.name ?? e.agent_id.slice(0, 8)) : "System";
            const message = eventSummary(e);
            return (
              <div key={e.id} className="flex items-start gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors">
                <div className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${cfg.color.replace("text-", "bg-").replace("400", "500/10")}`}>
                  <IconComp className={`w-3 h-3 ${cfg.color}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-semibold uppercase tracking-wider ${cfg.color}`}>{cfg.label}</span>
                    <span className="text-[10px] text-zinc-600">•</span>
                    <span className="text-[10px] text-zinc-500 font-data">{agentName}</span>
                  </div>
                  <div className="text-xs text-zinc-300 mt-0.5 truncate">{message}</div>
                </div>
                <div className="text-[10px] text-zinc-600 font-data whitespace-nowrap flex-shrink-0">{formatTimeAgo(e.timestamp)}</div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Agent Health Grid ─── */

function AgentHealthGrid({ agents }: { agents: Agent[] }) {
  const statusConfig = (status: string) => {
    const s = status.toLowerCase();
    if (s === "healthy" || s === "active") return { dot: "bg-emerald-500", ring: "ring-emerald-500/20", label: "Healthy" };
    if (s === "degraded" || s === "warning") return { dot: "bg-amber-500", ring: "ring-amber-500/20", label: "Degraded" };
    return { dot: "bg-red-500", ring: "ring-red-500/20", label: "Unhealthy" };
  };

  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
      <CardHeader className="px-4 py-2.5 border-b border-white/[0.06]">
        <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Agent Status Grid</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {agents.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No agents registered</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-px bg-white/[0.04]">
            {agents.map(a => {
              const sc = statusConfig(a.status);
              return (
                <div key={a.agent_id} className="bg-[hsl(var(--background))] p-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${sc.dot} ring-2 ${sc.ring}`} />
                    <span className="text-xs font-medium text-zinc-200 truncate">{a.name}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-zinc-500 font-data">
                      {a.llm_config && typeof a.llm_config === "object" && "model" in a.llm_config
                        ? String(a.llm_config.model)
                        : a.framework}
                    </span>
                    <span className="text-[10px] text-zinc-600 font-data">{formatTimeAgo(a.last_health_check ?? a.created)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Cost Trend Chart (Tremor AreaChart) ─── */

function CostTrendChart({ data }: { data: CostTimeseriesBucket[] }) {
  const chartData = data.map(d => ({
    day: d.bucket.slice(5),
    Cost: d.total_cost_usd,
  }));

  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
      <CardHeader className="px-4 py-2.5 border-b border-white/[0.06]">
        <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Cost Breakdown — 7 Day</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        {data.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No cost data yet</div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <RechartsAreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="day" tick={{ fill: "#52525b", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#52525b", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(0)}`} width={36} />
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [`$${v.toFixed(2)}`, "Cost"]} />
              <Area type="monotone" dataKey="Cost" stroke="hsl(var(--chart-1))" strokeWidth={2} fill="url(#costGrad)" dot={false} isAnimationActive={false} />
            </RechartsAreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Events Over Time (Tremor AreaChart) ─── */

function EventsOverTimeChart({ events }: { events: AuditEvent[] }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(id);
  }, []);

  const chartData = useMemo(() => {
    if (events.length === 0) return [];
    const buckets: Record<string, number> = {};
    for (let i = 23; i >= 0; i--) {
      const h = new Date(now - i * 3600000);
      const key = `${String(h.getHours()).padStart(2, "0")}:00`;
      buckets[key] = 0;
    }
    events.forEach(e => {
      const t = new Date(e.timestamp);
      if (now - t.getTime() > 86400000) return;
      const key = `${String(t.getHours()).padStart(2, "0")}:00`;
      if (key in buckets) buckets[key]++;
    });
    return Object.entries(buckets).map(([hour, count]) => ({ hour, Events: count }));
  }, [events, now]);

  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
      <CardHeader className="flex-row items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
        <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Events Over Time</CardTitle>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 font-medium">Last 24h</span>
      </CardHeader>
      <CardContent className="p-4">
        {chartData.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No event data yet</div>
        ) : (
          <ResponsiveContainer width="100%" height={176}>
            <RechartsAreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="eventsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--chart-4))" stopOpacity={0.4} />
                  <stop offset="50%" stopColor="hsl(var(--chart-4))" stopOpacity={0.1} />
                  <stop offset="100%" stopColor="hsl(var(--chart-4))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="hour" tick={{ fill: "#52525b", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#52525b", fontSize: 10 }} axisLine={false} tickLine={false} width={28} />
              <Tooltip
                contentStyle={{ background: "#18181b", border: "1px solid rgba(139,92,246,0.3)", borderRadius: 8, fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,0.5)" }}
                labelStyle={{ color: "#a1a1aa", fontSize: 10, marginBottom: 4 }}
                itemStyle={{ color: "#c084fc" }}
                cursor={{ stroke: "rgba(139,92,246,0.2)", strokeWidth: 1 }}
              />
              <Area type="monotone" dataKey="Events" stroke="hsl(var(--chart-4))" strokeWidth={2} fill="url(#eventsGrad)" dot={false} isAnimationActive={false} />
            </RechartsAreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Agent Status (Tremor DonutChart) ─── */

function AgentStatusChart({ agents }: { agents: Agent[] }) {
  const statusData = useMemo(() => {
    if (agents.length === 0) return [];
    const counts: Record<string, number> = {};
    agents.forEach(a => {
      const s = a.status.toLowerCase();
      const label = (s === "active" || s === "healthy") ? "Healthy" : s === "degraded" || s === "warning" ? "Degraded" : s === "offline" ? "Offline" : "Unhealthy";
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [agents]);

  const colorMap: Record<string, string> = { Healthy: "#34d399", Degraded: "#fbbf24", Unhealthy: "#f87171", Offline: "#71717a" };
  const pieColors = statusData.map(d => colorMap[d.name] || "#71717a");

  return (
    <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
      <CardHeader className="px-4 py-2.5 border-b border-white/[0.06]">
        <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Agent Status</CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        {agents.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No agents registered</div>
        ) : (
          <div className="flex items-center">
            <div className="w-1/2 flex items-center justify-center">
              <ResponsiveContainer width="100%" height={144}>
                <PieChart>
                  <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={36} outerRadius={56} strokeWidth={0} isAnimationActive={false}>
                    {statusData.map((_, i) => <Cell key={i} fill={pieColors[i]} />)}
                  </Pie>
                  <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill="#e4e4e7" fontSize={18} fontWeight="bold">{agents.length}</text>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="w-1/2 space-y-2 pl-2">
              {statusData.map(d => (
                <div key={d.name} className="flex items-center gap-2 text-xs">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${
                    d.name === "Healthy" ? "bg-emerald-500" : d.name === "Degraded" ? "bg-amber-500" : d.name === "Unhealthy" ? "bg-red-500" : "bg-zinc-500"
                  }`} />
                  <span className="text-zinc-400">{d.name}</span>
                  <span className="ml-auto font-data text-zinc-200">{d.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── Main Page ─── */

export default function OverviewPage() {
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const fetchAudit = useCallback(() => api.audit.list(), []);
  const fetchHealth = useCallback(() => api.health(), []);
  const fetchCosts = useCallback(() => api.costs.summary(), []);
  const fetchTimeseries = useCallback(() => api.costs.timeseries("day"), []);

  const { data: rawAgents, loading: loadingAgents } = useStablePolling<Agent[]>(fetchAgents, 10000);
  const { data: rawEvents, loading: loadingEvents } = useStablePolling<AuditEvent[]>(fetchAudit, 5000);
  const { data: health } = useStablePolling(fetchHealth, 10000);
  const { data: rawCosts, loading: loadingCosts } = useStablePolling<CostSummary[]>(fetchCosts, 15000);
  const { data: rawTimeseries } = useStablePolling<CostTimeseriesBucket[]>(fetchTimeseries, 30000);

  const agents = useMemo(() => rawAgents ?? [], [rawAgents]);
  const events = useMemo(() => rawEvents ?? [], [rawEvents]);
  const costs = useMemo(() => rawCosts ?? [], [rawCosts]);
  const timeseries = rawTimeseries ?? [];

  // Stable clock for time-based filtering (updates every minute)
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(id);
  }, []);

  const onlineCount = agents.filter(a => a.status === "healthy" || a.status === "active").length;
  const totalAgents = agents.length;
  const recentEvents = useMemo(() => events.slice(0, 12), [events]);
  const events24h = useMemo(() => {
    const cutoff = now - 86400000;
    return events.filter(e => new Date(e.timestamp).getTime() > cutoff).length;
  }, [events, now]);

  const totalCost = costs.reduce((s, c) => s + c.total_cost_usd, 0);
  const budgetLimit = 50;
  const budgetPct = Math.min(100, Math.round((totalCost / budgetLimit) * 100));

  const phiBlocked = useMemo(() =>
    events.filter(e => e.event_type === "phi_blocked").reduce((s, e) => s + (Number(e.details.count) || 1), 0)
  , [events]);

  const eventsLastHour = useMemo(() => {
    const cutoff = now - 3600000;
    return events.filter(e => new Date(e.timestamp).getTime() > cutoff).length;
  }, [events, now]);

  const ruleMatchRate = useMemo(() => {
    if (events.length === 0) return 0;
    const ruleMatches = events.filter(e => e.event_type === "rule_triggered" || e.event_type === "rule_matched").length;
    const totalEnvelopes = events.filter(e => e.event_type === "envelope_received" || e.event_type === "agent_action" || e.event_type === "rule_triggered" || e.event_type === "rule_matched").length;
    return totalEnvelopes > 0 ? Math.round((ruleMatches / totalEnvelopes) * 100) : 0;
  }, [events]);

  const phiToday = useMemo(() => {
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    return events.filter(e => e.event_type === "phi_blocked" && new Date(e.timestamp).getTime() >= todayStart.getTime())
      .reduce((s, e) => s + (Number(e.details.count) || 1), 0);
  }, [events]);

  const totalRequests = useMemo(() => costs.reduce((s, c) => s + c.request_count, 0), [costs]);

  const systemHealth = useMemo(() => {
    const healthyPct = totalAgents > 0 ? (onlineCount / totalAgents) * 100 : 0;
    const isGwUp = health?.status === "ok" || health?.status === "healthy";
    if (totalAgents === 0 && !isGwUp) return 0;
    return Math.round(isGwUp ? healthyPct : healthyPct * 0.5);
  }, [onlineCount, totalAgents, health]);

  const agentMap = useMemo(() => {
    const m: Record<string, Agent> = {};
    agents.forEach(a => { m[a.agent_id] = a; });
    return m;
  }, [agents]);

  const costSpark = timeseries.map(t => t.total_cost_usd);
  const requestSpark = timeseries.map(t => t.request_count);

  const isLoading = loadingAgents && loadingEvents && loadingCosts;

  return (
    <div className="space-y-4">
      {isLoading && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Trellis API…
        </div>
      )}

      {/* System Health Bar */}
      <div className="health-bar px-4 py-3 flex items-center gap-6 flex-wrap rounded-lg border border-white/[0.06] bg-[hsl(var(--card))]">
        <div className="flex items-center gap-2">
          <HeartPulse className="w-4 h-4 text-[hsl(var(--primary))]" />
          <span className="text-[10px] uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Command Center</span>
        </div>
        <div className="flex items-center gap-6 flex-wrap flex-1">
          {[
            { label: "Uptime", value: health?.status === "ok" || health?.status === "healthy" ? "Online" : "Offline", color: health?.status === "ok" || health?.status === "healthy" ? "text-emerald-400" : "text-red-400", dot: health?.status === "ok" || health?.status === "healthy" ? "bg-emerald-500" : "bg-red-500" },
            { label: "Events Processed", value: String(events.length), color: "text-cyan-400", dot: events.length > 0 ? "bg-emerald-500" : "bg-zinc-500" },
            { label: "Active Agents", value: totalAgents > 0 ? `${onlineCount}/${totalAgents}` : "—", color: onlineCount === totalAgents && totalAgents > 0 ? "text-emerald-400" : totalAgents > 0 ? "text-amber-400" : "text-zinc-500", dot: onlineCount === totalAgents && totalAgents > 0 ? "bg-emerald-500" : totalAgents > 0 ? "bg-amber-500" : "bg-zinc-500" },
            { label: "Rule Match Rate", value: events.length > 0 ? `${ruleMatchRate}%` : "—", color: ruleMatchRate >= 50 ? "text-emerald-400" : ruleMatchRate > 0 ? "text-amber-400" : "text-zinc-500", dot: ruleMatchRate >= 50 ? "bg-emerald-500" : ruleMatchRate > 0 ? "bg-amber-500" : "bg-zinc-500" },
          ].map(m => (
            <div key={m.label} className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${m.dot}`} />
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider">{m.label}</span>
              <span className={`text-xs font-data font-semibold ${m.color}`}>{m.value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ═══ TOP SECTION: Key Metrics ═══ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Active Agents"
          value={totalAgents > 0 ? `${onlineCount}/${totalAgents}` : "—"}
          icon={Bot}
          accent="emerald"
          trend={totalAgents > 0 ? { direction: onlineCount === totalAgents ? "up" : "down", label: `${onlineCount} healthy` } : undefined}
        />
        <StatCard
          label="Envelopes Today"
          value={String(events24h)}
          icon={Activity}
          accent="cyan"
          sparkData={requestSpark}
          trend={eventsLastHour > 0 ? { direction: "up", label: `${eventsLastHour} last hr` } : undefined}
        />
        <StatCard
          label="Total Cost (24h)"
          value={totalCost > 0 ? `$${totalCost.toFixed(2)}` : "—"}
          icon={DollarSign}
          accent="amber"
          trend={totalCost > 0 ? { direction: budgetPct > 75 ? "up" : "flat", label: `${budgetPct}% of budget` } : undefined}
          sparkData={costSpark}
        />
        <StatCard
          label="System Health"
          value={totalAgents > 0 ? `${systemHealth}%` : "—"}
          icon={HeartPulse}
          accent={systemHealth >= 90 ? "emerald" : systemHealth >= 70 ? "amber" : "red"}
          trend={totalAgents > 0 ? { direction: systemHealth >= 90 ? "up" : systemHealth >= 70 ? "flat" : "down", label: systemHealth >= 90 ? "All clear" : "Degraded" } : undefined}
        />
      </div>

      {/* ═══ MIDDLE SECTION: Activity Feed + Cost Chart ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ActivityTimeline events={recentEvents} agentMap={agentMap} />
        <div className="space-y-3">
          <CostTrendChart data={timeseries} />
          {/* Cost Breakdown by Agent */}
          <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
            <CardHeader className="px-4 py-2.5 border-b border-white/[0.06]">
              <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Cost by Agent</CardTitle>
            </CardHeader>
            <CardContent className="p-4">
              {costs.length === 0 ? (
                <div className="text-center text-zinc-600 py-4 text-sm">No cost data yet</div>
              ) : (
                <div className="space-y-2.5">
                  {costs.slice(0, 5).map(c => {
                    const agent = agentMap[c.agent_id];
                    const pct = totalCost > 0 ? (c.total_cost_usd / totalCost) * 100 : 0;
                    return (
                      <div key={c.agent_id} className="flex items-center gap-2">
                        <span className="text-xs text-[hsl(var(--foreground))] truncate w-28">{agent?.name ?? c.agent_id.slice(0, 12)}</span>
                        <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-[hsl(var(--primary))]" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-[10px] text-[hsl(var(--muted-foreground))] font-data w-14 text-right">${c.total_cost_usd.toFixed(2)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ═══ BOTTOM SECTION: Agent Status + Alerts ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <AgentHealthGrid agents={agents} />
        <div className="space-y-3">
          <EventsOverTimeChart events={events} />
          {/* Recent Alerts */}
          <Card className="border-white/[0.06] bg-[hsl(var(--card))] py-0 gap-0">
            <CardHeader className="px-4 py-2.5 border-b border-white/[0.06]">
              <CardTitle className="text-xs uppercase tracking-widest text-[hsl(var(--muted-foreground))] font-medium">Recent Alerts</CardTitle>
            </CardHeader>
            <CardContent className="p-0 divide-y divide-white/[0.04]">
              {(() => {
                const alerts = events.filter(e => e.event_type === "phi_blocked" || e.event_type === "budget_alert" || e.event_type === "rule_triggered").slice(0, 5);
                if (alerts.length === 0) return (
                  <div className="flex items-center justify-center gap-2 py-6 text-sm text-zinc-600">
                    <Check className="w-4 h-4 text-emerald-500" />
                    No recent alerts
                  </div>
                );
                return alerts.map(e => {
                  const cfg = EVENT_CONFIG[e.event_type] ?? DEFAULT_EVENT_CFG;
                  const IconComp = cfg.icon;
                  return (
                    <div key={e.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.02] transition-colors">
                      <IconComp className={`w-3.5 h-3.5 flex-shrink-0 ${cfg.color}`} />
                      <span className="text-xs text-[hsl(var(--foreground))] truncate flex-1">{eventSummary(e)}</span>
                      <span className="text-[10px] text-zinc-600 font-data whitespace-nowrap">{formatTimeAgo(e.timestamp)}</span>
                    </div>
                  );
                });
              })()}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
