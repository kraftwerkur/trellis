"use client";

import { useCallback, useState, useMemo } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent, AuditEvent, CostSummary } from "@/types/trellis";

function formatDate(ts: string) {
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function AgentsPage() {
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const fetchCosts = useCallback(() => api.costs.summary(), []);
  const { data: agents, loading } = useStablePolling<Agent[]>(fetchAgents, 10000);
  const { data: costs } = useStablePolling<CostSummary[]>(fetchCosts, 15000);
  const [expanded, setExpanded] = useState<string | null>(null);

  const costMap = useMemo(() => {
    const m: Record<string, CostSummary> = {};
    (costs ?? []).forEach(c => { m[c.agent_id] = c; });
    return m;
  }, [costs]);

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Agent Registry</span>
        {agents && <span className="text-xs text-zinc-600 ml-2">({agents.length})</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-zinc-600 uppercase border-b border-white/[0.06]">
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Name</th>
              <th className="text-left px-3 py-2">Agent ID</th>
              <th className="text-left px-3 py-2">Department</th>
              <th className="text-left px-3 py-2">Type</th>
              <th className="text-left px-3 py-2">Framework</th>
              <th className="text-left px-3 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-3 py-2"><div className="skeleton h-4 w-full" /></td>
                  ))}
                </tr>
              ))
            ) : !agents?.length ? (
              <tr><td colSpan={7} className="text-center text-zinc-600 py-8">No agents registered</td></tr>
            ) : (
              agents.map(a => {
                const ok = a.status === "healthy" || a.status === "active";
                const isExpanded = expanded === a.agent_id;
                return (
                  <AgentRow
                    key={a.agent_id}
                    agent={a}
                    ok={ok}
                    isExpanded={isExpanded}
                    cost={costMap[a.agent_id]}
                    onToggle={() => setExpanded(isExpanded ? null : a.agent_id)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AgentRow({ agent: a, ok, isExpanded, cost, onToggle }: {
  agent: Agent; ok: boolean; isExpanded: boolean; cost?: CostSummary; onToggle: () => void;
}) {
  const fetchAudit = useCallback(() => api.audit.list({ agent_id: a.agent_id }), [a.agent_id]);
  const { data: auditEvents } = useStablePolling<AuditEvent[]>(fetchAudit, isExpanded ? 10000 : 0);

  return (
    <>
      <tr className="table-row-hover cursor-pointer" onClick={onToggle}>
        <td className="px-3 py-2">
          <span className={`status-dot ${ok ? "status-dot-online" : "status-dot-unhealthy"}`} />
        </td>
        <td className="px-3 py-2 text-zinc-200 font-medium">{a.name}</td>
        <td className="px-3 py-2 font-data text-xs text-zinc-500">{a.agent_id.slice(0, 12)}…</td>
        <td className="px-3 py-2 text-xs text-zinc-400">{a.department}</td>
        <td className="px-3 py-2 text-xs text-zinc-400">{a.agent_type}</td>
        <td className="px-3 py-2 text-xs text-zinc-400">{a.framework}</td>
        <td className="px-3 py-2 text-xs text-zinc-500">{formatDate(a.created)}</td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={7} className="bg-black/30 px-4 py-3 border-b border-white/[0.06]">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Config */}
              <div>
                <div className="text-[10px] uppercase text-zinc-600 mb-1 tracking-wider">Config</div>
                <pre className="text-[11px] font-data text-zinc-400 bg-black/40 rounded p-2 overflow-auto max-h-48">
                  {JSON.stringify({ llm_config: a.llm_config, endpoint: a.endpoint, tools: a.tools, channels: a.channels, cost_mode: a.cost_mode, maturity: a.maturity }, null, 2)}
                </pre>
              </div>
              {/* Cost */}
              <div>
                <div className="text-[10px] uppercase text-zinc-600 mb-1 tracking-wider">Cost Breakdown</div>
                {cost ? (
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between text-zinc-400"><span>Total Cost</span><span className="font-data text-amber-400">${cost.total_cost_usd.toFixed(4)}</span></div>
                    <div className="flex justify-between text-zinc-400"><span>Requests</span><span className="font-data">{cost.request_count}</span></div>
                    <div className="flex justify-between text-zinc-400"><span>Tokens In</span><span className="font-data">{cost.total_tokens_in.toLocaleString()}</span></div>
                    <div className="flex justify-between text-zinc-400"><span>Tokens Out</span><span className="font-data">{cost.total_tokens_out.toLocaleString()}</span></div>
                  </div>
                ) : (
                  <div className="text-xs text-zinc-600">No cost data</div>
                )}
              </div>
              {/* Recent audit */}
              <div>
                <div className="text-[10px] uppercase text-zinc-600 mb-1 tracking-wider">Recent Events</div>
                {auditEvents?.length ? (
                  <div className="space-y-1 max-h-48 overflow-auto">
                    {auditEvents.slice(0, 10).map(e => (
                      <div key={e.id} className="flex items-center gap-2 text-xs">
                        <span className="font-data text-zinc-600 text-[10px] w-16 shrink-0">
                          {new Date(e.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}
                        </span>
                        <span className={`event-badge event-${e.event_type}`}>{e.event_type.replace(/_/g, " ")}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-zinc-600">No events</div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
