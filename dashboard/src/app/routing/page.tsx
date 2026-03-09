"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent, AgentIntake, IntelligentRouteResponse, RoutingResult, RoutingDecision } from "@/types/trellis";
import {
  Route, Send, ChevronDown, ChevronRight, Shield, AlertTriangle,
  Trophy, Clock, Grid3x3, History,
} from "lucide-react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid, Cell,
} from "recharts";

/* ─── Mock Data ─── */

const MOCK_AGENTS: Agent[] = [
  { agent_id: "reef", name: "Reef", owner: "eric", department: "IT", framework: "openclaw", agent_type: "general", runtime_type: "persistent", endpoint: null, health_endpoint: null, tools: [], channels: ["webchat"], maturity: "production", cost_mode: "tracked", status: "active", created: new Date().toISOString(), last_health_check: new Date().toISOString() },
  { agent_id: "secops", name: "SecOps Agent", owner: "eric", department: "Security", framework: "langchain", agent_type: "specialist", runtime_type: "on-demand", endpoint: null, health_endpoint: null, tools: [], channels: ["email"], maturity: "beta", cost_mode: "tracked", status: "active", created: new Date().toISOString(), last_health_check: new Date().toISOString() },
  { agent_id: "helpdesk", name: "Help Desk Bot", owner: "eric", department: "IT", framework: "custom", agent_type: "specialist", runtime_type: "persistent", endpoint: null, health_endpoint: null, tools: [], channels: ["teams"], maturity: "production", cost_mode: "tracked", status: "active", created: new Date().toISOString(), last_health_check: new Date().toISOString() },
  { agent_id: "epic-support", name: "Epic Support", owner: "eric", department: "Clinical", framework: "openclaw", agent_type: "specialist", runtime_type: "on-demand", endpoint: null, health_endpoint: null, tools: [], channels: ["email"], maturity: "alpha", cost_mode: "tracked", status: "active", created: new Date().toISOString(), last_health_check: new Date().toISOString() },
];

const MOCK_INTAKES: Record<string, AgentIntake> = {
  reef: { agent_id: "reef", categories: ["general", "research", "development"], source_types: ["webchat", "api", "email"], keywords: ["trellis", "build", "deploy", "code"], systems: ["openclaw", "github", "vercel"], priority_range: [1, 5], phi_authorized: false },
  secops: { agent_id: "secops", categories: ["security", "compliance", "incident"], source_types: ["email", "siem", "api"], keywords: ["vulnerability", "breach", "firewall", "crowdstrike", "sentinel"], systems: ["crowdstrike", "sentinel", "sailpoint"], priority_range: [1, 3], phi_authorized: true },
  helpdesk: { agent_id: "helpdesk", categories: ["support", "general", "hardware"], source_types: ["teams", "email", "phone"], keywords: ["password", "reset", "vpn", "printer", "access"], systems: ["ivanti", "sailpoint", "8x8"], priority_range: [3, 5], phi_authorized: false },
  "epic-support": { agent_id: "epic-support", categories: ["clinical", "emr", "support"], source_types: ["email", "teams"], keywords: ["epic", "order", "chart", "patient", "tapestry"], systems: ["epic", "peoplesoft"], priority_range: [1, 4], phi_authorized: true },
};

const MOCK_ROUTE_RESPONSE: IntelligentRouteResponse = {
  winner: { agent_id: "secops", agent_name: "SecOps Agent", score: 0.92, confidence: 0.88, breakdown: { category: 0.95, source_type: 0.85, keyword: 0.98, system: 0.90, priority: 0.92 } },
  candidates: [
    { agent_id: "secops", agent_name: "SecOps Agent", score: 0.92, confidence: 0.88, breakdown: { category: 0.95, source_type: 0.85, keyword: 0.98, system: 0.90, priority: 0.92 } },
    { agent_id: "reef", agent_name: "Reef", score: 0.45, confidence: 0.40, breakdown: { category: 0.30, source_type: 0.70, keyword: 0.20, system: 0.50, priority: 0.55 } },
    { agent_id: "helpdesk", agent_name: "Help Desk Bot", score: 0.38, confidence: 0.32, breakdown: { category: 0.25, source_type: 0.60, keyword: 0.15, system: 0.45, priority: 0.45 } },
    { agent_id: "epic-support", agent_name: "Epic Support", score: 0.22, confidence: 0.18, breakdown: { category: 0.10, source_type: 0.30, keyword: 0.05, system: 0.35, priority: 0.30 } },
  ],
  envelope_id: "env-demo-001",
  routed_at: new Date().toISOString(),
};

const MOCK_DECISIONS: RoutingDecision[] = [
  { id: "dec-001", envelope_id: "env-7a3f", envelope_summary: "CrowdStrike alert: suspicious login from unknown IP", winner_agent_id: "secops", winner_agent_name: "SecOps Agent", score: 0.94, confidence: 0.91, candidates_count: 4, routed_at: new Date(Date.now() - 120000).toISOString() },
  { id: "dec-002", envelope_id: "env-9b2e", envelope_summary: "Password reset request for user jsmith", winner_agent_id: "helpdesk", winner_agent_name: "Help Desk Bot", score: 0.89, confidence: 0.85, candidates_count: 4, routed_at: new Date(Date.now() - 600000).toISOString() },
  { id: "dec-003", envelope_id: "env-4c1d", envelope_summary: "Epic order entry workflow error in Tapestry", winner_agent_id: "epic-support", winner_agent_name: "Epic Support", score: 0.87, confidence: 0.82, candidates_count: 4, routed_at: new Date(Date.now() - 1800000).toISOString() },
  { id: "dec-004", envelope_id: "env-2f8a", envelope_summary: "Build Trellis dashboard routing page", winner_agent_id: "reef", winner_agent_name: "Reef", score: 0.96, confidence: 0.93, candidates_count: 4, routed_at: new Date(Date.now() - 3600000).toISOString() },
  { id: "dec-005", envelope_id: "env-5e7c", envelope_summary: "SailPoint access review for Q1 compliance", winner_agent_id: "secops", winner_agent_name: "SecOps Agent", score: 0.91, confidence: 0.87, candidates_count: 4, routed_at: new Date(Date.now() - 7200000).toISOString() },
];

const SAMPLE_ENVELOPE = `{
  "source": "email",
  "category": "security",
  "priority": 2,
  "subject": "CrowdStrike alert: suspicious login",
  "body": "Detected unauthorized access attempt from unknown IP on sentinel-monitored endpoint",
  "systems": ["crowdstrike", "sentinel"],
  "phi_present": false
}`;

/* ─── Helpers ─── */

const COLORS = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444"];
const DIMENSION_LABELS: Record<string, string> = {
  category: "Category",
  source_type: "Source",
  keyword: "Keyword",
  system: "System",
  priority: "Priority",
};

function confidenceColor(c: number): string {
  if (c >= 0.8) return "text-emerald-400";
  if (c >= 0.5) return "text-amber-400";
  return "text-red-400";
}

function confidenceBg(c: number): string {
  if (c >= 0.8) return "bg-emerald-500/10 border-emerald-500/20";
  if (c >= 0.5) return "bg-amber-500/10 border-amber-500/20";
  return "bg-red-500/10 border-red-500/20";
}

function overlapColor(v: number): string {
  if (v < 0.3) return "#10b981";
  if (v < 0.7) return "#f59e0b";
  return "#ef4444";
}

function overlapBg(v: number): string {
  if (v < 0.3) return "bg-emerald-500/20";
  if (v < 0.7) return "bg-amber-500/20";
  return "bg-red-500/20";
}

function formatTimeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function computeOverlap(a: AgentIntake, b: AgentIntake): number {
  const jaccard = (x: string[], y: string[]) => {
    const setX = new Set(x), setY = new Set(y);
    const intersection = [...setX].filter(i => setY.has(i)).length;
    const union = new Set([...setX, ...setY]).size;
    return union === 0 ? 0 : intersection / union;
  };
  const catOverlap = jaccard(a.categories, b.categories);
  const srcOverlap = jaccard(a.source_types, b.source_types);
  const kwOverlap = jaccard(a.keywords, b.keywords);
  const sysOverlap = jaccard(a.systems, b.systems);
  // Priority range overlap
  const overlapStart = Math.max(a.priority_range[0], b.priority_range[0]);
  const overlapEnd = Math.min(a.priority_range[1], b.priority_range[1]);
  const rangeA = a.priority_range[1] - a.priority_range[0] + 1;
  const rangeB = b.priority_range[1] - b.priority_range[0] + 1;
  const priOverlap = overlapEnd >= overlapStart ? (overlapEnd - overlapStart + 1) / Math.max(rangeA, rangeB) : 0;
  return (catOverlap + srcOverlap + kwOverlap + sysOverlap + priOverlap) / 5;
}

/* ─── Route Tester Section ─── */

function RouteTester() {
  const [envelope, setEnvelope] = useState(SAMPLE_ENVELOPE);
  const [result, setResult] = useState<IntelligentRouteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<string | null>(null);

  const handleRoute = async () => {
    setLoading(true);
    setError(null);
    try {
      const parsed = JSON.parse(envelope);
      const res = await api.routing.intelligent(parsed);
      setResult(res);
    } catch (e) {
      // Fallback to mock
      if (e instanceof SyntaxError) {
        setError("Invalid JSON — check your envelope syntax");
        setLoading(false);
        return;
      }
      setResult(MOCK_ROUTE_RESPONSE);
    }
    setLoading(false);
  };

  const radarData = useMemo(() => {
    if (!result) return [];
    const candidate = selectedCandidate
      ? result.candidates.find(c => c.agent_id === selectedCandidate)
      : result.winner;
    if (!candidate) return [];
    return Object.entries(candidate.breakdown).map(([key, value]) => ({
      dimension: DIMENSION_LABELS[key] || key,
      score: value,
      fullMark: 1,
    }));
  }, [result, selectedCandidate]);

  const activeCandidate = selectedCandidate
    ? result?.candidates.find(c => c.agent_id === selectedCandidate)
    : result?.winner;

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
          <Send className="w-3.5 h-3.5" /> Route Tester
        </span>
      </div>
      <div className="p-4 space-y-4">
        {/* Input */}
        <div className="flex flex-col lg:flex-row gap-3">
          <div className="flex-1">
            <textarea
              value={envelope}
              onChange={e => setEnvelope(e.target.value)}
              className="w-full h-40 bg-white/[0.03] border border-white/[0.08] rounded-lg p-3 text-xs font-mono text-zinc-300 resize-none focus:outline-none focus:border-cyan-500/40 transition-colors"
              placeholder="Paste JSON envelope here..."
              spellCheck={false}
            />
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={handleRoute}
                disabled={loading}
                className="px-4 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs font-medium hover:bg-cyan-500/30 transition-colors disabled:opacity-50"
              >
                {loading ? "Routing…" : "Route Envelope"}
              </button>
              {error && <span className="text-xs text-red-400">{error}</span>}
            </div>
          </div>

          {/* Radar Chart */}
          {result && (
            <div className="w-full lg:w-72 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="70%">
                  <PolarGrid stroke="rgba(255,255,255,0.06)" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 10, fill: "#a1a1aa" }} />
                  <PolarRadiusAxis angle={90} domain={[0, 1]} tick={{ fontSize: 8, fill: "#52525b" }} tickCount={5} />
                  <Radar name="Score" dataKey="score" stroke="#06b6d4" fill="#06b6d4" fillOpacity={0.25} strokeWidth={2} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Results */}
        {result && (
          <div className="space-y-2">
            {/* Winner banner */}
            <div className={`flex items-center gap-3 p-3 rounded-lg border ${confidenceBg(result.winner.confidence)}`}>
              <Trophy className="w-5 h-5 text-amber-400" />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-zinc-100">{result.winner.agent_name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-zinc-400 font-mono">{result.winner.agent_id}</span>
                </div>
                <span className="text-[10px] text-zinc-500">Winner — routed {formatTimeAgo(result.routed_at)}</span>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold font-data text-cyan-400">{(result.winner.score * 100).toFixed(0)}%</div>
                <div className={`text-[10px] font-data ${confidenceColor(result.winner.confidence)}`}>
                  {(result.winner.confidence * 100).toFixed(0)}% confidence
                </div>
              </div>
            </div>

            {/* All candidates */}
            <div className="space-y-1">
              {result.candidates.map((c, i) => (
                <button
                  key={c.agent_id}
                  onClick={() => setSelectedCandidate(c.agent_id === selectedCandidate ? null : c.agent_id)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                    c.agent_id === selectedCandidate ? "bg-cyan-500/10 border border-cyan-500/20" : "bg-white/[0.02] border border-white/[0.04] hover:bg-white/[0.04]"
                  }`}
                >
                  <span className={`text-xs font-bold w-5 text-center ${i === 0 ? "text-amber-400" : "text-zinc-500"}`}>#{i + 1}</span>
                  <span className="text-xs text-zinc-300 flex-1">{c.agent_name}</span>
                  <div className="flex items-center gap-3">
                    {/* Mini bar chart for breakdown */}
                    <div className="flex items-end gap-0.5 h-4">
                      {Object.values(c.breakdown).map((v, j) => (
                        <div key={j} className="w-1.5 rounded-t" style={{ height: `${v * 16}px`, background: COLORS[j] }} />
                      ))}
                    </div>
                    <span className="text-xs font-data text-zinc-300 w-10 text-right">{(c.score * 100).toFixed(0)}%</span>
                    <span className={`text-[10px] font-data w-12 text-right ${confidenceColor(c.confidence)}`}>
                      {(c.confidence * 100).toFixed(0)}% conf
                    </span>
                  </div>
                </button>
              ))}
            </div>

            {/* Score breakdown bar chart for selected */}
            {activeCandidate && (
              <div className="h-32 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={Object.entries(activeCandidate.breakdown).map(([key, value]) => ({
                      dimension: DIMENSION_LABELS[key] || key,
                      score: value,
                    }))}
                    margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                    <XAxis dataKey="dimension" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} width={30} />
                    <Tooltip
                      contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v: number) => [`${(v * 100).toFixed(0)}%`, "Score"]}
                    />
                    <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                      {Object.keys(activeCandidate.breakdown).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Agent Intake Registry ─── */

function IntakeRegistry({ agents, intakes }: { agents: Agent[]; intakes: Record<string, AgentIntake> }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
          <Route className="w-3.5 h-3.5" /> Agent Intake Registry
        </span>
        <span className="text-[10px] text-zinc-600">{agents.length} agents</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/[0.06]">
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium w-6"></th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Agent</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Categories</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Sources</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Priority</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">PHI</th>
            </tr>
          </thead>
          <tbody>
            {agents.map(agent => {
              const intake = intakes[agent.agent_id];
              const isExpanded = expanded === agent.agent_id;
              if (!intake) return null;
              return (
                <>
                  <tr
                    key={agent.agent_id}
                    onClick={() => setExpanded(isExpanded ? null : agent.agent_id)}
                    className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3 text-zinc-500">
                      {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-data text-zinc-200">{agent.name}</span>
                      <span className="text-[10px] text-zinc-600 ml-2">{agent.agent_id}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {intake.categories.slice(0, 3).map(c => (
                          <span key={c} className="px-1.5 py-0.5 rounded text-[10px] bg-cyan-500/10 text-cyan-400">{c}</span>
                        ))}
                        {intake.categories.length > 3 && (
                          <span className="text-[10px] text-zinc-600">+{intake.categories.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {intake.source_types.map(s => (
                          <span key={s} className="px-1.5 py-0.5 rounded text-[10px] bg-violet-500/10 text-violet-400">{s}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-data text-zinc-300">
                      P{intake.priority_range[0]}–P{intake.priority_range[1]}
                    </td>
                    <td className="px-4 py-3">
                      {intake.phi_authorized
                        ? <Shield className="w-3.5 h-3.5 text-emerald-400" />
                        : <span className="text-zinc-600 text-[10px]">No</span>}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${agent.agent_id}-detail`} className="border-b border-white/[0.04]">
                      <td colSpan={6} className="px-4 py-3 bg-white/[0.01]">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Keywords</div>
                            <div className="flex flex-wrap gap-1">
                              {intake.keywords.map(k => (
                                <span key={k} className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400">{k}</span>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Systems</div>
                            <div className="flex flex-wrap gap-1">
                              {intake.systems.map(s => (
                                <span key={s} className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400">{s}</span>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Full Config</div>
                            <div className="text-[10px] text-zinc-400 space-y-0.5">
                              <div>Priority: P{intake.priority_range[0]}–P{intake.priority_range[1]}</div>
                              <div>PHI Authorized: {intake.phi_authorized ? "Yes ✓" : "No"}</div>
                              <div>Categories: {intake.categories.length} | Keywords: {intake.keywords.length} | Systems: {intake.systems.length}</div>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Overlap Matrix ─── */

function OverlapMatrix({ agents, intakes }: { agents: Agent[]; intakes: Record<string, AgentIntake> }) {
  const agentsWithIntake = agents.filter(a => intakes[a.agent_id]);

  const matrix = useMemo(() => {
    return agentsWithIntake.map(a =>
      agentsWithIntake.map(b => {
        if (a.agent_id === b.agent_id) return 1;
        return computeOverlap(intakes[a.agent_id], intakes[b.agent_id]);
      })
    );
  }, [agentsWithIntake, intakes]);

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
          <Grid3x3 className="w-3.5 h-3.5" /> Overlap Matrix
        </span>
        <div className="flex items-center gap-2 text-[10px]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-emerald-500/40" /> &lt;0.3</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-amber-500/40" /> 0.3–0.7</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-red-500/40" /> &gt;0.7</span>
        </div>
      </div>
      <div className="p-4 overflow-x-auto">
        <table className="text-xs mx-auto">
          <thead>
            <tr>
              <th className="px-2 py-1"></th>
              {agentsWithIntake.map(a => (
                <th key={a.agent_id} className="px-2 py-1 text-[10px] text-zinc-500 font-medium text-center whitespace-nowrap" style={{ writingMode: "vertical-lr", transform: "rotate(180deg)" }}>
                  {a.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agentsWithIntake.map((a, i) => (
              <tr key={a.agent_id}>
                <td className="px-2 py-1 text-[10px] text-zinc-400 font-medium whitespace-nowrap text-right">{a.name}</td>
                {matrix[i].map((val, j) => (
                  <td key={j} className="px-1 py-1 text-center">
                    {i === j ? (
                      <div className="w-10 h-10 rounded flex items-center justify-center bg-white/[0.04] text-zinc-600 text-[10px] font-mono">—</div>
                    ) : (
                      <div
                        className={`w-10 h-10 rounded flex items-center justify-center text-[10px] font-mono font-bold ${overlapBg(val)}`}
                        style={{ color: overlapColor(val) }}
                        title={`${a.name} ↔ ${agentsWithIntake[j].name}: ${(val * 100).toFixed(0)}%`}
                      >
                        {(val * 100).toFixed(0)}
                      </div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Recent Routing Decisions ─── */

function RecentDecisions({ decisions }: { decisions: RoutingDecision[] }) {
  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
          <History className="w-3.5 h-3.5" /> Recent Routing Decisions
        </span>
        <span className="text-[10px] text-zinc-600">{decisions.length} decisions</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/[0.06]">
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Envelope</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Winner</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Score</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Confidence</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">Candidates</th>
              <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-widest text-zinc-500 font-medium">When</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map(d => (
              <tr key={d.id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-3">
                  <div className="max-w-xs">
                    <span className="text-zinc-300 line-clamp-1">{d.envelope_summary}</span>
                    <span className="text-[10px] text-zinc-600 font-mono">{d.envelope_id}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="font-data text-zinc-200">{d.winner_agent_name}</span>
                </td>
                <td className="px-4 py-3">
                  <span className="font-data text-cyan-400">{(d.score * 100).toFixed(0)}%</span>
                </td>
                <td className="px-4 py-3">
                  <span className={`font-data ${confidenceColor(d.confidence)}`}>
                    {(d.confidence * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="px-4 py-3 font-data text-zinc-400">{d.candidates_count}</td>
                <td className="px-4 py-3 text-zinc-500 font-data">{formatTimeAgo(d.routed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */

export default function RoutingPage() {
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const { data: rawAgents } = useStablePolling<Agent[]>(fetchAgents, 15000);
  const agents = rawAgents ?? MOCK_AGENTS;

  // In a real setup, we'd fetch intakes per agent. For now, use mock with API fallback pattern.
  const intakes = MOCK_INTAKES;
  const decisions = MOCK_DECISIONS;

  return (
    <div className="space-y-4">
      <RouteTester />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <IntakeRegistry agents={agents} intakes={intakes} />
        <OverlapMatrix agents={agents} intakes={intakes} />
      </div>
      <RecentDecisions decisions={decisions} />
    </div>
  );
}
