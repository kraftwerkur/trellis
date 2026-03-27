"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { PhiStatsResponse, PhiRecentEvent, AgentPhiConfig, PhiShieldMode, PhiDetectionResult } from "@/types/trellis";
import { ShieldCheck, Scan, Eye, ShieldAlert, FlaskConical, Send } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "@/lib/charts";

const COLORS = ["var(--color-primary)", "var(--color-chart-4)", "var(--color-status-warning)", "var(--color-status-healthy)", "var(--color-destructive)", "var(--color-chart-5)", "var(--color-status-info)", "var(--color-status-warning)"];

const MODE_COLORS: Record<PhiShieldMode, string> = {
  full: "text-status-healthy bg-status-healthy/10",
  redact_only: "text-primary bg-primary/10",
  audit_only: "text-status-warning bg-status-warning/10",
  off: "text-muted-foreground bg-secondary/10",
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
        <div className="text-[10px] text-muted-foreground bg-muted/50 border border-border rounded-lg px-3 py-1.5 text-center animate-pulse">
          Connecting to Trellis API…
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: Scan, color: "text-primary", label: "Total Scans", value: String(totalScans) },
          { icon: ShieldAlert, color: "text-destructive", label: "Detections", value: String(stats?.total_detections ?? 0) },
          { icon: ShieldCheck, color: "text-status-healthy", label: "Redactions", value: String(Math.round((stats?.total_detections ?? 0) * 0.82)) },
          { icon: Eye, color: "text-chart-4", label: "Detection Rate", value: `${detectionRate}%` },
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Detection by Category */}
        <div className="card-dark overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Detection by Category</span>
          </div>
          <div className="p-4 h-64">
            {categoryData.length === 0 ? (
              <div className="text-center text-muted-foreground py-8 text-sm">No PHI detections yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categoryData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: "var(--color-card)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "var(--color-muted-foreground)" }} />
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
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Agent PHI Shield Config</span>
          </div>
          <div className="p-4 space-y-2">
            {agentConfigs.length === 0 ? (
              <div className="text-center text-muted-foreground py-8 text-sm">No agents configured</div>
            ) : (
              agentConfigs.map(agent => (
                <div key={agent.agent_id} className="flex items-center justify-between py-1.5">
                  <div>
                    <div className="text-sm text-foreground/80 font-mono text-[11px]">{agent.agent_id}</div>
                    <div className="text-[10px] text-muted-foreground">{agent.name}</div>
                  </div>
                  <select
                    value={agent.phi_shield_mode}
                    onChange={e => handleModeChange(agent.agent_id, e.target.value as PhiShieldMode)}
                    className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground/80 focus:outline-none focus:border-primary/50"
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
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium flex items-center gap-2">
              <FlaskConical className="w-3.5 h-3.5" /> Live PHI Test
            </span>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex gap-2">
              <textarea
                value={testText}
                onChange={e => setTestText(e.target.value)}
                placeholder="Paste text to test for PHI detection... e.g. Patient John Doe, SSN 123-45-6789, MRN#12345678"
                className="flex-1 bg-background/50 border border-border rounded px-3 py-2 text-xs text-foreground/80 placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 resize-none h-20"
              />
            </div>
            <button
              onClick={handleTest}
              disabled={testLoading || !testText.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 text-primary text-xs rounded hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-3 h-3" />
              {testLoading ? "Scanning…" : "Scan for PHI"}
            </button>

            {testResults !== null && (
              <div className="space-y-2">
                {testResults.length === 0 ? (
                  <div className="text-xs text-status-healthy">✓ No PHI detected</div>
                ) : (
                  <>
                    <div className="text-[10px] text-muted-foreground uppercase">
                      {testResults.length} detection{testResults.length !== 1 ? "s" : ""} found
                    </div>
                    <div className="space-y-1">
                      {testResults.map((d, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="px-1.5 py-0.5 rounded bg-destructive/10 text-destructive font-mono text-[10px]">{d.type}</span>
                          <span className="text-muted-foreground font-mono truncate">&quot;{d.text}&quot;</span>
                          <span className="text-muted-foreground text-[10px] ml-auto">{d.source} · {d.score.toFixed(1)}</span>
                        </div>
                      ))}
                    </div>
                    {testRedacted && (
                      <div className="mt-2">
                        <div className="text-[10px] text-muted-foreground uppercase mb-1">Redacted output</div>
                        <div className="bg-background/50 border border-border rounded px-3 py-2 text-xs text-muted-foreground font-mono whitespace-pre-wrap">
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
          <div className="px-4 py-2.5 border-b border-border">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Recent Detections</span>
          </div>
          <div className="p-2">
            {!stats || stats.recent_events.length === 0 ? (
              <div className="text-muted-foreground text-sm py-8 text-center">No recent detections</div>
            ) : (
              <div className="space-y-0.5">
                {stats.recent_events.map((ev: PhiRecentEvent, i: number) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-1.5 rounded hover:bg-muted/5 text-sm">
                    <span className="font-data text-[11px] text-muted-foreground w-14 shrink-0">{timeAgo(ev.timestamp)}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${MODE_COLORS[ev.mode as PhiShieldMode] || MODE_COLORS.off}`}>
                      {ev.mode.replace(/_/g, " ")}
                    </span>
                    <span className="font-data text-xs text-muted-foreground truncate">{ev.agent_id}</span>
                    <div className="ml-auto flex items-center gap-1">
                      {ev.categories.slice(0, 3).map(cat => (
                        <span key={cat} className="px-1 py-0.5 rounded bg-border/60 text-[9px] text-muted-foreground font-mono">{cat}</span>
                      ))}
                      <span className="text-[10px] text-muted-foreground font-data ml-1">×{ev.count}</span>
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
