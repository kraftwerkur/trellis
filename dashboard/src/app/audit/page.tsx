"use client";

import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent, AuditEvent } from "@/types/trellis";

function formatTime(ts: string) {
  const d = new Date(ts);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function EventBadge({ type }: { type: string }) {
  return <span className={`event-badge event-${type}`}>{type.replace(/_/g, " ")}</span>;
}

function detailsSummary(d: Record<string, unknown>): string {
  if (d.subject) return String(d.subject);
  if (d.message) return String(d.message);
  if (d.model) return `model: ${d.model}`;
  if (d.rule_name) return `rule: ${d.rule_name}`;
  if (d.agent_name) return `agent: ${d.agent_name}`;
  const keys = Object.keys(d).slice(0, 3);
  return keys.map(k => `${k}: ${JSON.stringify(d[k])}`).join(", ") || "—";
}

export default function AuditPage() {
  const [filterType, setFilterType] = useState("");
  const [filterAgent, setFilterAgent] = useState("");
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

  const fetchAudit = useCallback(() => {
    const params: { event_type?: string; agent_id?: string } = {};
    if (filterType) params.event_type = filterType;
    if (filterAgent) params.agent_id = filterAgent;
    return api.audit.list(params);
  }, [filterType, filterAgent]);
  const fetchAgents = useCallback(() => api.agents.list(), []);

  const { data: events, loading } = useStablePolling<AuditEvent[]>(fetchAudit, 5000);
  const { data: agents } = useStablePolling<Agent[]>(fetchAgents, 30000);

  const eventTypes = useMemo(() => {
    const s = new Set((events ?? []).map(e => e.event_type));
    return Array.from(s).sort();
  }, [events]);

  const agentMap = useMemo(() => {
    const m: Record<string, string> = {};
    (agents ?? []).forEach(a => { m[a.agent_id] = a.name; });
    return m;
  }, [agents]);

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex items-center gap-3">
        <select
          className="bg-black/40 border border-white/[0.06] rounded px-2 py-1.5 text-xs text-zinc-400 focus:outline-none focus:border-cyan-500/30"
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
        >
          <option value="">All event types</option>
          {eventTypes.map(t => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </select>
        <select
          className="bg-black/40 border border-white/[0.06] rounded px-2 py-1.5 text-xs text-zinc-400 focus:outline-none focus:border-cyan-500/30"
          value={filterAgent}
          onChange={e => setFilterAgent(e.target.value)}
        >
          <option value="">All agents</option>
          {(agents ?? []).map(a => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
      </div>

      {/* Table */}
      <div className="card-dark overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-600 uppercase border-b border-white/[0.06]">
                <th className="text-left px-3 py-2">Timestamp</th>
                <th className="text-left px-3 py-2">Trace</th>
                <th className="text-left px-3 py-2">Agent</th>
                <th className="text-left px-3 py-2">Event</th>
                <th className="text-left px-3 py-2">Details</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i}>{Array.from({ length: 5 }).map((_, j) => (
                    <td key={j} className="px-3 py-2"><div className="skeleton h-4 w-full" /></td>
                  ))}</tr>
                ))
              ) : !events?.length ? (
                <tr><td colSpan={5} className="text-center text-zinc-600 py-8">No audit events</td></tr>
              ) : (
                events.map(e => (
                  <AuditRow
                    key={e.id}
                    event={e}
                    agentName={e.agent_id ? agentMap[e.agent_id] : undefined}
                    isTraceExpanded={expandedTrace === e.trace_id}
                    onTraceClick={() => e.trace_id && setExpandedTrace(expandedTrace === e.trace_id ? null : e.trace_id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function AuditRow({ event: e, agentName, isTraceExpanded, onTraceClick }: {
  event: AuditEvent; agentName?: string; isTraceExpanded: boolean; onTraceClick: () => void;
}) {
  const fetchTrace = useCallback(() => api.audit.trace(e.trace_id!), [e.trace_id]);
  const { data: traceEvents } = useStablePolling<AuditEvent[]>(fetchTrace, isTraceExpanded && e.trace_id ? 10000 : 0);

  return (
    <>
      <tr className="table-row-hover">
        <td className="px-3 py-1.5 font-data text-xs text-zinc-500 whitespace-nowrap">{formatTime(e.timestamp)}</td>
        <td className="px-3 py-1.5">
          {e.trace_id ? (
            <button onClick={onTraceClick} className="font-data text-xs text-cyan-400/70 hover:text-cyan-400 transition-colors">
              {e.trace_id.slice(0, 8)}
            </button>
          ) : <span className="text-xs text-zinc-600">—</span>}
        </td>
        <td className="px-3 py-1.5 text-xs text-zinc-300">{agentName ?? (e.agent_id?.slice(0, 8) || "—")}</td>
        <td className="px-3 py-1.5"><EventBadge type={e.event_type} /></td>
        <td className="px-3 py-1.5 text-xs text-zinc-400 truncate max-w-[400px]">{detailsSummary(e.details)}</td>
      </tr>
      {isTraceExpanded && e.trace_id && (
        <tr>
          <td colSpan={5} className="bg-black/30 px-4 py-3 border-b border-white/[0.06]">
            <div className="text-[10px] uppercase text-zinc-600 mb-2 tracking-wider">Trace {e.trace_id.slice(0, 8)}… — Full Chain</div>
            {traceEvents?.length ? (
              <div className="space-y-1">
                {traceEvents
                  .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
                  .map((te, i) => (
                    <div key={te.id} className="flex items-center gap-3 text-xs">
                      <span className="text-zinc-700 font-data w-4 text-right">{i + 1}</span>
                      <span className="font-data text-zinc-600 text-[10px] w-20 shrink-0">{formatTime(te.timestamp)}</span>
                      <EventBadge type={te.event_type} />
                      <span className="text-zinc-400 truncate">{detailsSummary(te.details)}</span>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="text-xs text-zinc-600">Loading trace…</div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
