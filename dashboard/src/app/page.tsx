"use client";

import { useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent, AuditEvent, CostSummary, CostTimeseriesBucket } from "@/types/trellis";
import {
  Bot, Activity, Shield, DollarSign, HeartPulse,
  TrendingUp, TrendingDown, AlertTriangle, Zap, Lock, Gauge,
} from "lucide-react";
import {
  AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

/* ─── Mock / Fallback Data ─── */

const MOCK_AGENTS: Agent[] = [
  { agent_id: "a1", name: "Compliance Checker", owner: "ops", department: "Legal", framework: "langchain", agent_type: "llm", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["pdf-parse"], channels: ["email"], maturity: "production", cost_mode: "standard", status: "healthy", llm_config: { model: "gpt-4o" }, created: "2026-02-20T10:00:00Z", last_health_check: new Date(Date.now() - 120000).toISOString() },
  { agent_id: "a2", name: "Doc Summarizer", owner: "ops", department: "Clinical", framework: "crewai", agent_type: "llm", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["ocr"], channels: ["api"], maturity: "production", cost_mode: "standard", status: "healthy", llm_config: { model: "claude-3.5-sonnet" }, created: "2026-02-18T08:00:00Z", last_health_check: new Date(Date.now() - 300000).toISOString() },
  { agent_id: "a3", name: "Risk Assessor", owner: "risk", department: "Finance", framework: "autogen", agent_type: "llm", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["calculator"], channels: ["api"], maturity: "staging", cost_mode: "budget", status: "healthy", llm_config: { model: "gpt-4o-mini" }, created: "2026-02-22T14:00:00Z", last_health_check: new Date(Date.now() - 60000).toISOString() },
  { agent_id: "a4", name: "PHI Redactor", owner: "security", department: "IT", framework: "custom", agent_type: "tool", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["regex", "ner"], channels: ["gateway"], maturity: "production", cost_mode: "standard", status: "active", llm_config: null, created: "2026-02-15T09:00:00Z", last_health_check: new Date(Date.now() - 45000).toISOString() },
  { agent_id: "a5", name: "Billing Auditor", owner: "finance", department: "Revenue Cycle", framework: "langchain", agent_type: "llm", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["sql"], channels: ["slack"], maturity: "production", cost_mode: "standard", status: "unhealthy", llm_config: { model: "gpt-4o" }, created: "2026-02-19T11:00:00Z", last_health_check: new Date(Date.now() - 7200000).toISOString() },
  { agent_id: "a6", name: "Patient Scheduler", owner: "ops", department: "Clinical", framework: "crewai", agent_type: "llm", runtime_type: "hosted", endpoint: null, health_endpoint: null, tools: ["calendar"], channels: ["sms", "email"], maturity: "staging", cost_mode: "budget", status: "healthy", llm_config: { model: "claude-3.5-sonnet" }, created: "2026-02-25T16:00:00Z", last_health_check: new Date(Date.now() - 180000).toISOString() },
];

const MOCK_EVENTS: AuditEvent[] = [
  { id: 1, trace_id: "t1", envelope_id: null, agent_id: "a1", event_type: "agent_action", details: { message: "Reviewed compliance doc #4821" }, timestamp: new Date(Date.now() - 30000).toISOString() },
  { id: 2, trace_id: "t2", envelope_id: null, agent_id: "a4", event_type: "phi_blocked", details: { message: "Blocked SSN in outbound response", count: 3 }, timestamp: new Date(Date.now() - 90000).toISOString() },
  { id: 3, trace_id: "t3", envelope_id: null, agent_id: "a3", event_type: "rule_triggered", details: { rule_name: "high-risk-flag", message: "Escalated to human review" }, timestamp: new Date(Date.now() - 180000).toISOString() },
  { id: 4, trace_id: "t4", envelope_id: null, agent_id: "a2", event_type: "agent_action", details: { message: "Summarized radiology report batch (12 docs)" }, timestamp: new Date(Date.now() - 300000).toISOString() },
  { id: 5, trace_id: "t5", envelope_id: null, agent_id: "a5", event_type: "budget_alert", details: { message: "Agent approaching 80% daily budget limit" }, timestamp: new Date(Date.now() - 420000).toISOString() },
  { id: 6, trace_id: "t6", envelope_id: null, agent_id: "a4", event_type: "phi_blocked", details: { message: "Redacted MRN from query response", count: 1 }, timestamp: new Date(Date.now() - 600000).toISOString() },
  { id: 7, trace_id: "t7", envelope_id: null, agent_id: "a1", event_type: "agent_action", details: { message: "Generated HIPAA audit trail export" }, timestamp: new Date(Date.now() - 900000).toISOString() },
  { id: 8, trace_id: "t8", envelope_id: null, agent_id: "a6", event_type: "rule_triggered", details: { rule_name: "off-hours-block", message: "Blocked scheduling outside business hours" }, timestamp: new Date(Date.now() - 1200000).toISOString() },
  { id: 9, trace_id: "t9", envelope_id: null, agent_id: "a3", event_type: "agent_action", details: { message: "Risk score calculated for claim #98234" }, timestamp: new Date(Date.now() - 1500000).toISOString() },
  { id: 10, trace_id: "t10", envelope_id: null, agent_id: "a4", event_type: "phi_blocked", details: { message: "Blocked DOB + patient name combination", count: 2 }, timestamp: new Date(Date.now() - 1800000).toISOString() },
];

const MOCK_COST_TIMESERIES: CostTimeseriesBucket[] = [
  { bucket: "2026-02-22", total_cost_usd: 1.24, total_tokens_in: 42000, total_tokens_out: 18000, request_count: 34 },
  { bucket: "2026-02-23", total_cost_usd: 2.18, total_tokens_in: 68000, total_tokens_out: 31000, request_count: 52 },
  { bucket: "2026-02-24", total_cost_usd: 1.87, total_tokens_in: 55000, total_tokens_out: 24000, request_count: 41 },
  { bucket: "2026-02-25", total_cost_usd: 3.42, total_tokens_in: 98000, total_tokens_out: 45000, request_count: 78 },
  { bucket: "2026-02-26", total_cost_usd: 2.95, total_tokens_in: 82000, total_tokens_out: 38000, request_count: 65 },
  { bucket: "2026-02-27", total_cost_usd: 4.11, total_tokens_in: 112000, total_tokens_out: 52000, request_count: 91 },
  { bucket: "2026-02-28", total_cost_usd: 3.56, total_tokens_in: 95000, total_tokens_out: 44000, request_count: 73 },
];

const MOCK_COSTS: CostSummary[] = [
  { agent_id: "a1", total_cost_usd: 5.82, total_tokens_in: 180000, total_tokens_out: 85000, request_count: 142 },
  { agent_id: "a2", total_cost_usd: 4.21, total_tokens_in: 130000, total_tokens_out: 62000, request_count: 98 },
  { agent_id: "a3", total_cost_usd: 3.45, total_tokens_in: 95000, total_tokens_out: 48000, request_count: 76 },
  { agent_id: "a4", total_cost_usd: 0.12, total_tokens_in: 5000, total_tokens_out: 2000, request_count: 210 },
  { agent_id: "a5", total_cost_usd: 2.18, total_tokens_in: 68000, total_tokens_out: 30000, request_count: 54 },
  { agent_id: "a6", total_cost_usd: 1.67, total_tokens_in: 52000, total_tokens_out: 24000, request_count: 64 },
];

/* ─── Sparkline Component ─── */

function Sparkline({ data, color = "#22d3ee", height = 32 }: { data: number[]; color?: string; height?: number }) {
  const chartData = data.map((v, i) => ({ v, i }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
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
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ─── Enhanced Stat Card ─── */

function CommandStatCard({ label, value, icon: Icon, accent, trend, sparkData }: {
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
    <div className="card-dark p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${c.bg}`}>
          <Icon className={`w-4 h-4 ${c.text}`} />
        </div>
        {trend && (
          <div className={`flex items-center gap-1 text-[10px] font-medium ${
            trend.direction === "up" ? "text-emerald-400" : trend.direction === "down" ? "text-red-400" : "text-zinc-500"
          }`}>
            {trend.direction === "up" ? <TrendingUp className="w-3 h-3" /> : trend.direction === "down" ? <TrendingDown className="w-3 h-3" /> : null}
            {trend.label}
          </div>
        )}
      </div>
      <div>
        <div className="text-2xl font-bold font-data text-zinc-100">{value}</div>
        <div className="text-[10px] text-zinc-500 uppercase tracking-widest">{label}</div>
      </div>
      {sparkData && (
        <div className="pt-1">
          <Sparkline data={sparkData} color={c.spark} />
        </div>
      )}
    </div>
  );
}

/* ─── Activity Timeline ─── */

const EVENT_CONFIG: Record<string, { color: string; icon: React.ElementType; label: string }> = {
  agent_action: { color: "text-cyan-400", icon: Zap, label: "Agent Action" },
  phi_blocked: { color: "text-red-400", icon: Lock, label: "PHI Blocked" },
  rule_triggered: { color: "text-amber-400", icon: AlertTriangle, label: "Rule Triggered" },
  budget_alert: { color: "text-purple-400", icon: DollarSign, label: "Budget Alert" },
};

function formatTimeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function ActivityTimeline({ events, agentMap }: { events: AuditEvent[]; agentMap: Record<string, Agent> }) {
  return (
    <div className="card-dark">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Activity Timeline</span>
        <span className="live-pulse w-2 h-2 rounded-full bg-emerald-500 inline-block" />
      </div>
      <div className="divide-y divide-white/[0.04] max-h-[400px] overflow-y-auto">
        {events.length === 0 ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No recent activity</div>
        ) : (
          events.map(e => {
            const cfg = EVENT_CONFIG[e.event_type] ?? EVENT_CONFIG.agent_action;
            const IconComp = cfg.icon;
            const agentName = e.agent_id ? (agentMap[e.agent_id]?.name ?? e.agent_id.slice(0, 8)) : "System";
            const message = e.details.message ? String(e.details.message) : e.event_type.replace(/_/g, " ");
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
      </div>
    </div>
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
    <div className="card-dark">
      <div className="px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Agent Health</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-px bg-white/[0.04]">
        {agents.map(a => {
          const sc = statusConfig(a.status);
          return (
            <div key={a.agent_id} className="bg-zinc-950 p-3 space-y-1.5">
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
    </div>
  );
}

/* ─── Cost Trend Chart ─── */

function CostTrendChart({ data }: { data: CostTimeseriesBucket[] }) {
  const chartData = data.map(d => ({
    day: d.bucket.slice(5), // MM-DD
    cost: d.total_cost_usd,
    requests: d.request_count,
  }));

  return (
    <div className="card-dark">
      <div className="px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">7-Day Cost Trend</span>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#52525b" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#52525b" }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} width={40} />
            <Tooltip
              contentStyle={{ backgroundColor: "#18181b", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: "#a1a1aa" }}
              itemStyle={{ color: "#22d3ee" }}
              formatter={(v: number) => [`$${v.toFixed(2)}`, "Cost"]}
            />
            <Area type="monotone" dataKey="cost" stroke="#22d3ee" strokeWidth={2} fill="url(#costGrad)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export default function OverviewPage() {
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const fetchAudit = useCallback(() => api.audit.list(), []);
  const fetchHealth = useCallback(() => api.health(), []);
  const fetchCosts = useCallback(() => api.costs.summary(), []);
  const fetchTimeseries = useCallback(() => api.costs.timeseries("day"), []);

  const { data: rawAgents } = useStablePolling<Agent[]>(fetchAgents, 10000);
  const { data: rawEvents } = useStablePolling<AuditEvent[]>(fetchAudit, 5000);
  const { data: health } = useStablePolling(fetchHealth, 10000);
  const { data: rawCosts } = useStablePolling<CostSummary[]>(fetchCosts, 15000);
  const { data: rawTimeseries } = useStablePolling<CostTimeseriesBucket[]>(fetchTimeseries, 30000);

  // Fallback to mock data when backend is unavailable
  const agents = rawAgents ?? MOCK_AGENTS;
  const events = rawEvents ?? MOCK_EVENTS;
  const costs = rawCosts ?? MOCK_COSTS;
  const timeseries = rawTimeseries ?? MOCK_COST_TIMESERIES;
  const isMock = !rawAgents;

  const onlineCount = agents.filter(a => a.status === "healthy" || a.status === "active").length;
  const totalAgents = agents.length;
  const recentEvents = useMemo(() => events.slice(0, 12), [events]);
  const events24h = useMemo(() => {
    const cutoff = Date.now() - 86400000;
    return events.filter(e => new Date(e.timestamp).getTime() > cutoff).length;
  }, [events]);

  const totalCost = costs.reduce((s, c) => s + c.total_cost_usd, 0);
  const budgetLimit = 50; // configurable
  const budgetPct = Math.min(100, Math.round((totalCost / budgetLimit) * 100));

  const phiBlocked = useMemo(() =>
    events.filter(e => e.event_type === "phi_blocked").reduce((s, e) => s + (Number(e.details.count) || 1), 0)
  , [events]);

  const eventsLastHour = useMemo(() => {
    const cutoff = Date.now() - 3600000;
    return events.filter(e => new Date(e.timestamp).getTime() > cutoff).length;
  }, [events]);

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
    const isGwUp = health?.status === "ok" || health?.status === "healthy" || isMock;
    return Math.round(isGwUp ? healthyPct : healthyPct * 0.5);
  }, [onlineCount, totalAgents, health, isMock]);

  const agentMap = useMemo(() => {
    const m: Record<string, Agent> = {};
    agents.forEach(a => { m[a.agent_id] = a; });
    return m;
  }, [agents]);

  // Sparkline data from timeseries
  const costSpark = timeseries.map(t => t.total_cost_usd);
  const requestSpark = timeseries.map(t => t.request_count);

  return (
    <div className="space-y-4">
      {/* Mock data banner */}
      {isMock && (
        <div className="text-[10px] text-amber-500/70 bg-amber-500/5 border border-amber-500/10 rounded-lg px-3 py-1.5 text-center">
          ⚠ Demo mode — showing simulated data (backend unavailable)
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        <CommandStatCard
          label="Active Agents"
          value={`${onlineCount}/${totalAgents}`}
          icon={Bot}
          accent="emerald"
          trend={totalAgents > 0 ? { direction: onlineCount === totalAgents ? "up" : "down", label: `${onlineCount} healthy` } : undefined}
        />
        <CommandStatCard
          label="Events / 24h"
          value={String(events24h)}
          icon={Activity}
          accent="blue"
          sparkData={requestSpark}
        />
        <CommandStatCard
          label="Total Requests"
          value={String(totalRequests)}
          icon={Gauge}
          accent="cyan"
          sparkData={requestSpark}
        />
        <CommandStatCard
          label="PHI Blocked"
          value={String(phiBlocked)}
          icon={Shield}
          accent="red"
        />
        <CommandStatCard
          label="Budget Used"
          value={`${budgetPct}%`}
          icon={DollarSign}
          accent="amber"
          trend={{ direction: budgetPct > 75 ? "up" : "flat", label: `$${totalCost.toFixed(2)}/$${budgetLimit}` }}
          sparkData={costSpark}
        />
        <CommandStatCard
          label="System Health"
          value={`${systemHealth}%`}
          icon={HeartPulse}
          accent="purple"
          trend={{ direction: systemHealth >= 90 ? "up" : systemHealth >= 70 ? "flat" : "down", label: systemHealth >= 90 ? "All clear" : "Degraded" }}
        />
      </div>

      {/* System Health Summary */}
      <div className="card-dark p-4 gradient-border">
        <div className="flex items-center gap-2 mb-3">
          <HeartPulse className="w-4 h-4 text-cyan-400" />
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">System Health Summary</span>
          <span className="live-pulse w-2 h-2 rounded-full bg-emerald-500 inline-block ml-auto" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {[
            { label: "Total Agents", value: String(totalAgents), color: "text-blue-400" },
            { label: "Active Agents", value: `${onlineCount}`, color: onlineCount === totalAgents ? "text-emerald-400" : "text-amber-400" },
            { label: "Events (1h)", value: String(eventsLastHour), color: "text-cyan-400" },
            { label: "Rule Match Rate", value: `${ruleMatchRate}%`, color: "text-purple-400" },
            { label: "PHI Detections Today", value: String(phiToday), color: phiToday > 0 ? "text-red-400" : "text-emerald-400" },
          ].map(s => (
            <div key={s.label} className="text-center">
              <div className={`text-xl font-bold font-data ${s.color}`}>{s.value}</div>
              <div className="text-[10px] text-zinc-600 uppercase tracking-wider mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Two-column: Timeline + Cost Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
        <div className="lg:col-span-3">
          <ActivityTimeline events={recentEvents} agentMap={agentMap} />
        </div>
        <div className="lg:col-span-2 space-y-3">
          <CostTrendChart data={timeseries} />
          {/* Mini summary */}
          <div className="card-dark p-4">
            <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-medium mb-2">Cost Breakdown</div>
            <div className="space-y-2">
              {costs.slice(0, 5).map(c => {
                const agent = agentMap[c.agent_id];
                const pct = totalCost > 0 ? (c.total_cost_usd / totalCost) * 100 : 0;
                return (
                  <div key={c.agent_id} className="flex items-center gap-2">
                    <span className="text-xs text-zinc-300 truncate w-28">{agent?.name ?? c.agent_id.slice(0, 12)}</span>
                    <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div className="h-full bg-cyan-500/60 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[10px] text-zinc-500 font-data w-14 text-right">${c.total_cost_usd.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Agent Health Grid */}
      <AgentHealthGrid agents={agents} />
    </div>
  );
}
