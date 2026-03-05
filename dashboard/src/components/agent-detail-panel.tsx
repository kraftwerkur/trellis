"use client";

import { useCallback } from "react";
import { X } from "lucide-react";
import type { Agent, AuditEvent, CostSummary } from "@/types/trellis";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";

export function AgentDetailPanel({ agent, cost, onClose }: {
  agent: Agent;
  cost?: CostSummary;
  onClose: () => void;
}) {
  const fetchAudit = useCallback(() => api.audit.list({ agent_id: agent.agent_id }), [agent.agent_id]);
  const { data: events } = useStablePolling<AuditEvent[]>(fetchAudit, 10000);

  const model = agent.llm_config
    ? (agent.llm_config as Record<string, string>).model || "—"
    : "—";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-lg bg-[#0a0b10] border-l border-white/[0.06] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-white/[0.06]">
          <div>
            <h2 className="text-sm font-medium text-zinc-200">{agent.name}</h2>
            <p className="text-[10px] font-data text-zinc-600">{agent.agent_id}</p>
          </div>
          <button onClick={onClose} className="p-1 text-zinc-500 hover:text-zinc-300">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Config */}
        <div className="p-4 border-b border-white/[0.06]">
          <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-3">Configuration</h3>
          <div className="grid grid-cols-2 gap-3 text-xs">
            {[
              ["Status", agent.status],
              ["Framework", agent.framework],
              ["Model", model],
              ["Type", agent.agent_type],
              ["Runtime", agent.runtime_type],
              ["Department", agent.department],
              ["Owner", agent.owner],
              ["Maturity", agent.maturity],
              ["Cost Mode", agent.cost_mode],
            ].map(([label, val]) => (
              <div key={label}>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider">{label}</div>
                <div className="font-data text-zinc-400">{val || "—"}</div>
              </div>
            ))}
          </div>
          {agent.endpoint && (
            <div className="mt-3">
              <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Endpoint</div>
              <div className="font-data text-[11px] text-zinc-400 break-all">{agent.endpoint}</div>
            </div>
          )}
          {agent.tools.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1">Tools</div>
              <div className="flex flex-wrap gap-1">
                {agent.tools.map((t) => (
                  <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.06] text-zinc-500 font-data">{t}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Cost */}
        {cost && (
          <div className="p-4 border-b border-white/[0.06]">
            <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-3">Cost Summary</h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Total Cost</div>
                <div className="font-data text-emerald-400">${cost.total_cost_usd.toFixed(4)}</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Requests</div>
                <div className="font-data text-zinc-400">{cost.request_count}</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Tokens In</div>
                <div className="font-data text-zinc-400">{cost.total_tokens_in.toLocaleString()}</div>
              </div>
              <div>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Tokens Out</div>
                <div className="font-data text-zinc-400">{cost.total_tokens_out.toLocaleString()}</div>
              </div>
            </div>
          </div>
        )}

        {/* Recent Events */}
        <div className="p-4">
          <h3 className="text-[10px] uppercase tracking-widest text-zinc-500 mb-3">Recent Activity</h3>
          {!events ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-6 w-full" />)}
            </div>
          ) : events.length === 0 ? (
            <div className="text-zinc-600 text-xs text-center py-4">No activity recorded</div>
          ) : (
            <div className="space-y-1">
              {events.slice(0, 30).map((ev) => (
                <div key={ev.id} className="flex items-center gap-2 text-xs py-1 table-row-hover rounded px-2">
                  <span className="font-data text-[10px] text-zinc-600 w-16 shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={`event-badge event-${ev.event_type.toLowerCase().replace(/\./g, "_")}`}>
                    {ev.event_type.replace(/_/g, " ")}
                  </span>
                  {ev.trace_id && (
                    <span className="font-data text-[10px] text-zinc-600 ml-auto">{ev.trace_id.slice(0, 8)}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
