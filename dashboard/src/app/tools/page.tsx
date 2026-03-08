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
        <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Tool Registry</span>
            {tools && <span className="text-xs text-zinc-600">({filteredTools.length}{search ? `/${tools.length}` : ""})</span>}
          </div>
          <input
            type="text"
            placeholder="Filter tools…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-white/[0.04] border border-white/[0.06] rounded-md px-3 py-1 text-xs text-zinc-300 placeholder-zinc-600 outline-none focus:border-cyan-500/40 focus:ring-1 focus:ring-cyan-500/20 transition-colors w-48"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-600 uppercase border-b border-white/[0.06]">
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
                <tr><td colSpan={7} className="text-center text-zinc-600 py-8">{tools?.length ? "No tools match filter" : "No tools registered"}</td></tr>
              ) : (
                filteredTools.map(t => (
                  <tr
                    key={t.name}
                    className={`table-row-hover cursor-pointer ${selectedTool === t.name ? "bg-white/[0.04]" : ""}`}
                    onClick={() => setSelectedTool(selectedTool === t.name ? null : t.name)}
                  >
                    <td className="px-3 py-2 text-zinc-200 font-medium font-data text-xs">{t.name}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${
                        t.category === "data" ? "bg-blue-500/10 text-blue-400" :
                        t.category === "communication" ? "bg-green-500/10 text-green-400" :
                        t.category === "system" ? "bg-amber-500/10 text-amber-400" :
                        "bg-zinc-500/10 text-zinc-400"
                      }`}>{t.category}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-400 max-w-xs truncate">{t.description}</td>
                    <td className="px-3 py-2 text-xs text-zinc-500">
                      {t.requires_permissions.length ? t.requires_permissions.join(", ") : <span className="text-zinc-700">none</span>}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-xs text-zinc-300">{t.call_count}</td>
                    <td className="px-3 py-2 text-right font-data text-xs">
                      <span className={t.error_count > 0 ? "text-red-400" : "text-zinc-600"}>{t.error_count}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-data text-xs text-zinc-400">
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
      <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center gap-2">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Execution Log</span>
        <span className="font-data text-xs text-cyan-400">{toolName}</span>
        {logs && <span className="text-xs text-zinc-600">({logs.length})</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 uppercase border-b border-white/[0.06]">
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
              <tr><td colSpan={6} className="text-center text-zinc-600 py-8">No execution history</td></tr>
            ) : (
              logs.map(l => (
                <tr key={l.id} className="table-row-hover">
                  <td className="px-3 py-2">
                    <span className={`status-dot ${
                      l.status === "success" ? "status-dot-healthy" :
                      l.status === "error" ? "status-dot-unhealthy" :
                      "bg-zinc-500"
                    }`} style={l.status !== "success" && l.status !== "error" ? { animation: "none" } : undefined} />
                  </td>
                  <td className="px-3 py-2 font-data text-xs text-zinc-400">{l.agent_id}</td>
                  <td className="px-3 py-2 font-data text-[10px] text-zinc-600">{l.trace_id ? l.trace_id.slice(0, 8) + "…" : "—"}</td>
                  <td className="px-3 py-2 text-xs text-zinc-400 max-w-xs truncate">
                    {l.error ? <span className="text-red-400">{l.error}</span> : (l.result_summary || "—")}
                  </td>
                  <td className="px-3 py-2 text-right font-data text-xs text-zinc-400">{l.latency_ms}ms</td>
                  <td className="px-3 py-2 text-right text-xs text-zinc-600">{timeAgo(l.timestamp)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
