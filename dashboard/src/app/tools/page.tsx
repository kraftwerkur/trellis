"use client";

import { useCallback, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { ToolInfo, ToolCallLog } from "@/types/trellis";

function timeAgo(ts: string | null) {
  if (!ts) return "—";
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function ToolsPage() {
  const fetchTools = useCallback(() => api.tools.list(), []);
  const { data: tools, loading } = useStablePolling<ToolInfo[]>(fetchTools, 10000);
  const [search, setSearch] = useState("");
  const [selectedTool, setSelectedTool] = useState<string | null>(null);

  const filteredTools = useMemo(() => {
    if (!tools) return [];
    if (!search.trim()) return tools;
    const q = search.toLowerCase();
    return tools.filter(t => t.name.toLowerCase().includes(q) || t.category.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
  }, [tools, search]);

  return (
    <div className="space-y-4">
      {/* Tool Registry */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-border flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Tool Registry</span>
            {tools && <span className="text-xs text-muted-foreground">({filteredTools.length}{search ? `/${tools.length}` : ""})</span>}
          </div>
          <input
            type="text"
            placeholder="Filter tools…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-muted/10 border border-border rounded-md px-3 py-1 text-xs text-foreground/80 placeholder-muted-foreground outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/20 transition-colors w-48"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase border-b border-border">
                <th className="text-left px-3 py-2">Name</th>
                <th className="text-left px-3 py-2">Category</th>
                <th className="text-left px-3 py-2">Description</th>
                <th className="text-left px-3 py-2">Permissions</th>
                <th className="text-right px-3 py-2">Calls</th>
                <th className="text-right px-3 py-2">Errors</th>
                <th className="text-right px-3 py-2">Avg Latency</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-3 py-2"><div className="skeleton h-4 w-full" /></td>
                    ))}
                  </tr>
                ))
              ) : !filteredTools.length ? (
                <tr><td colSpan={7} className="text-center text-muted-foreground py-8">{tools?.length ? "No tools match filter" : "No tools registered"}</td></tr>
              ) : (
                filteredTools.map(t => (
                  <tr
                    key={t.name}
                    className={`table-row-hover cursor-pointer ${selectedTool === t.name ? "bg-muted/10" : ""}`}
                    onClick={() => setSelectedTool(selectedTool === t.name ? null : t.name)}
                  >
                    <td className="px-3 py-2 text-foreground font-medium font-data text-xs">{t.name}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                        t.category === "data" ? "bg-status-info/10 text-status-info" :
                        t.category === "communication" ? "bg-status-healthy/10 text-status-healthy" :
                        t.category === "system" ? "bg-status-warning/10 text-status-warning" :
                        "bg-secondary/10 text-muted-foreground"
                      }`}>{t.category}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground max-w-xs truncate">{t.description}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {t.requires_permissions.length ? t.requires_permissions.join(", ") : <span className="text-muted-foreground">none</span>}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-xs text-foreground/80">{t.call_count}</td>
                    <td className="px-3 py-2 text-right font-data text-xs">
                      <span className={t.error_count > 0 ? "text-destructive" : "text-muted-foreground"}>{t.error_count}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-data text-xs text-muted-foreground">
                      {t.avg_latency_ms > 0 ? `${t.avg_latency_ms}ms` : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Tool Execution Log (shown when a tool is selected) */}
      {selectedTool && (
        <ToolUsagePanel toolName={selectedTool} />
      )}
    </div>
  );
}

function ToolUsagePanel({ toolName }: { toolName: string }) {
  const fetchUsage = useCallback(() => api.tools.usage(toolName, 30), [toolName]);
  const { data: logs, loading } = useStablePolling<ToolCallLog[]>(fetchUsage, 10000);

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
        <span className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Execution Log</span>
        <span className="font-data text-xs text-primary">{toolName}</span>
        {logs && <span className="text-xs text-muted-foreground">({logs.length})</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground uppercase border-b border-border">
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Agent</th>
              <th className="text-left px-3 py-2">Trace</th>
              <th className="text-left px-3 py-2">Result</th>
              <th className="text-right px-3 py-2">Latency</th>
              <th className="text-right px-3 py-2">When</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-3 py-2"><div className="skeleton h-4 w-full" /></td>
                  ))}
                </tr>
              ))
            ) : !logs?.length ? (
              <tr><td colSpan={6} className="text-center text-muted-foreground py-8">No execution history</td></tr>
            ) : (
              logs.map(l => (
                <tr key={l.id} className="table-row-hover">
                  <td className="px-3 py-2">
                    <span className={`status-dot ${
                      l.status === "success" ? "status-dot-healthy" :
                      l.status === "error" ? "status-dot-unhealthy" :
                      "bg-secondary"
                    }`} style={l.status !== "success" && l.status !== "error" ? { animation: "none" } : undefined} />
                  </td>
                  <td className="px-3 py-2 font-data text-xs text-muted-foreground">{l.agent_id}</td>
                  <td className="px-3 py-2 font-data text-[10px] text-muted-foreground">{l.trace_id ? l.trace_id.slice(0, 8) + "…" : "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground max-w-xs truncate">
                    {l.error ? <span className="text-destructive">{l.error}</span> : (l.result_summary || "—")}
                  </td>
                  <td className="px-3 py-2 text-right font-data text-xs text-muted-foreground">{l.latency_ms}ms</td>
                  <td className="px-3 py-2 text-right text-xs text-muted-foreground">{timeAgo(l.timestamp)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
