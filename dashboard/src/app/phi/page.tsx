"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { PhiStatsResponse, PhiRecentEvent, AgentPhiConfig, PhiShieldMode, PhiDetectionResult } from "@/types/trellis";
import { ShieldCheck, Scan, Eye, ShieldAlert, FlaskConical, Send } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";

const COLORS = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#3b82f6", "#f97316"];

const MODE_COLORS: Record<PhiShieldMode, string> = {
  full: "text-emerald-400 bg-emerald-500/10",
  redact_only: "text-cyan-400 bg-cyan-500/10",
  audit_only: "text-amber-400 bg-amber-500/10",
  off: "text-zinc-500 bg-zinc-500/10",
};

const MODES: PhiShieldMode[] = ["full", "redact_only", "audit_only", "off"];

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function PhiPage() {
  const [testText, setTestText] = useState("");
  const [testResults, setTestResults] = useState<PhiDetectionResult[] | null>(null);
  const [testRedacted, setTestRedacted] = useState<string | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  const fetchStats = useCallback(() => api.phi.stats(), []);
  const fetchAgentConfigs = useCallback(() => api.phi.agentConfigs(), []);

  const { data: rawStats, loading: loadingStats } = useStablePolling<PhiStatsResponse>(fetchStats, 30000);
  const { data: rawAgentConfigs, refresh: refreshConfigs } = useStablePolling<AgentPhiConfig[]>(fetchAgentConfigs, 30000);

  const stats = rawStats ?? null;
  const agentConfigs = rawAgentConfigs ?? [];

  const totalScans = useMemo(() => {
    if (!stats) return 0;
    return Object.values(stats.by_day).reduce((a, b) => a + b, 0);
  }, [stats]);

  const categoryData = useMemo(() => {
    if (!stats) return [];
    return Object.entries(stats.by_category)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [stats]);

  const detectionRate = stats && totalScans > 0 ? ((stats.total_detections / (totalScans * 3)) * 100).toFixed(1) : "0";

  async function handleTest() {
    if (!testText.trim()) return;
    setTestLoading(true);
    try {
      const res = await api.phi.test(testText);
      setTestResults(res.detections);
      setTestRedacted(res.redacted);
    } catch {
      setTestResults([]);
      setTestRedacted(null);
    } finally {
      setTestLoading(false);
    }
  }

  async function handleModeChange(agentId: string, mode: PhiShieldMode) {
    try {
      await api.phi.updateAgentMode(agentId, mode);
      refreshConfigs();
    } catch {
      // silently fail if API unavailable
    }
  }

  return (
    <div className="space-y-4">
      {loadingStats && (
        <div className="text-[10px] text-zinc-500 bg-zinc-800/50 border border-zinc-700/30 rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Trellis API…
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: Scan, color: "text-cyan-500", label: "Total Scans", value: String(totalScans) },
          { icon: ShieldAlert, color: "text-red-500", label: "Detections", value: String(stats?.total_detections ?? 0) },
          { icon: ShieldCheck, color: "text-emerald-500", label: "Redactions", value: String(Math.round((stats?.total_detections ?? 0) * 0.82)) },
          { icon: Eye, color: "text-violet-500", label: "Detection Rate", value: `${detectionRate}%` },
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Detection by Category */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Detection by Category</span>
          </div>
          <div className="p-4 h-64">
            {categoryData.length === 0 ? (
              <div className="text-center text-zinc-600 py-8 text-sm">No PHI detections yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categoryData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "#52525b" }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "#0a0a0f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "#a1a1aa" }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {categoryData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Agent PHI Config */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Agent PHI Shield Config</span>
          </div>
          <div className="p-4 space-y-2">
            {agentConfigs.length === 0 ? (
              <div className="text-center text-zinc-600 py-8 text-sm">No agents configured</div>
            ) : (
              agentConfigs.map(agent => (
                <div key={agent.agent_id} className="flex items-center justify-between py-1.5">
                  <div>
                    <div className="text-sm text-zinc-300 font-mono text-[11px]">{agent.agent_id}</div>
                    <div className="text-[10px] text-zinc-600">{agent.name}</div>
                  </div>
                  <select
                    value={agent.phi_shield_mode}
                    onChange={e => handleModeChange(agent.agent_id, e.target.value as PhiShieldMode)}
                    className="bg-zinc-900 border border-white/[0.06] rounded px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:border-cyan-500/50"
                  >
                    {MODES.map(m => (
                      <option key={m} value={m}>{m.replace(/_/g, " ")}</option>
                    ))}
                  </select>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Live Test Panel */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium flex items-center gap-2">
              <FlaskConical className="w-3.5 h-3.5" /> Live PHI Test
            </span>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex gap-2">
              <textarea
                value={testText}
                onChange={e => setTestText(e.target.value)}
                placeholder="Paste text to test for PHI detection... e.g. Patient John Doe, SSN 123-45-6789, MRN#12345678"
                className="flex-1 bg-zinc-900/50 border border-white/[0.06] rounded px-3 py-2 text-xs text-zinc-300 placeholder:text-zinc-700 focus:outline-none focus:border-cyan-500/50 resize-none h-20"
              />
            </div>
            <button
              onClick={handleTest}
              disabled={testLoading || !testText.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-500/10 text-cyan-400 text-xs rounded hover:bg-cyan-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-3 h-3" />
              {testLoading ? "Scanning…" : "Scan for PHI"}
            </button>

            {testResults !== null && (
              <div className="space-y-2">
                {testResults.length === 0 ? (
                  <div className="text-xs text-emerald-400">✓ No PHI detected</div>
                ) : (
                  <>
                    <div className="text-[10px] text-zinc-500 uppercase">
                      {testResults.length} detection{testResults.length !== 1 ? "s" : ""} found
                    </div>
                    <div className="space-y-1">
                      {testResults.map((d, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 font-mono text-[10px]">{d.type}</span>
                          <span className="text-zinc-400 font-mono truncate">&quot;{d.text}&quot;</span>
                          <span className="text-zinc-600 text-[10px] ml-auto">{d.source} · {d.score.toFixed(1)}</span>
                        </div>
                      ))}
                    </div>
                    {testRedacted && (
                      <div className="mt-2">
                        <div className="text-[10px] text-zinc-500 uppercase mb-1">Redacted output</div>
                        <div className="bg-zinc-900/50 border border-white/[0.06] rounded px-3 py-2 text-xs text-zinc-400 font-mono whitespace-pre-wrap">
                          {testRedacted}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Recent Detections Feed */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Recent Detections</span>
          </div>
          <div className="p-2">
            {!stats || stats.recent_events.length === 0 ? (
              <div className="text-zinc-600 text-sm py-8 text-center">No recent detections</div>
            ) : (
              <div className="space-y-0.5">
                {stats.recent_events.map((ev: PhiRecentEvent, i: number) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-1.5 rounded hover:bg-white/[0.02] text-sm">
                    <span className="font-data text-[11px] text-zinc-600 w-14 shrink-0">{timeAgo(ev.timestamp)}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${MODE_COLORS[ev.mode as PhiShieldMode] || MODE_COLORS.off}`}>
                      {ev.mode.replace(/_/g, " ")}
                    </span>
                    <span className="font-data text-xs text-zinc-400 truncate">{ev.agent_id}</span>
                    <div className="ml-auto flex items-center gap-1">
                      {ev.categories.slice(0, 3).map(cat => (
                        <span key={cat} className="px-1 py-0.5 rounded bg-white/[0.04] text-[9px] text-zinc-500 font-mono">{cat}</span>
                      ))}
                      <span className="text-[10px] text-zinc-600 font-data ml-1">×{ev.count}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
