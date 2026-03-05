"use client";

import { useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Rule, Agent } from "@/types/trellis";

function conditionToEnglish(conditions: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(conditions)) {
    if (typeof value === "string") {
      parts.push(`${key} = "${value}"`);
    } else if (typeof value === "object" && value !== null) {
      const inner = value as Record<string, unknown>;
      for (const [op, val] of Object.entries(inner)) {
        if (op === "$contains" || op === "contains") parts.push(`${key} contains "${val}"`);
        else if (op === "$regex" || op === "regex") parts.push(`${key} matches /${val}/`);
        else if (op === "$in" || op === "in") parts.push(`${key} in [${(val as string[]).join(", ")}]`);
        else parts.push(`${key} ${op} ${JSON.stringify(val)}`);
      }
    } else {
      parts.push(`${key} = ${JSON.stringify(value)}`);
    }
  }
  return parts.join(" AND ") || "all envelopes";
}

function targetToString(actions: Rule["actions"], agentMap: Record<string, string>): string {
  const targets = Array.isArray(actions.route_to) ? actions.route_to : [actions.route_to];
  return targets.map(t => agentMap[t] ?? t.slice(0, 12)).join(", ");
}

export default function RulesPage() {
  const fetchRules = useCallback(() => api.rules.list(), []);
  const fetchAgents = useCallback(() => api.agents.list(), []);
  const { data: rules, loading } = useStablePolling<Rule[]>(fetchRules, 10000);
  const { data: agents } = useStablePolling<Agent[]>(fetchAgents, 30000);

  const agentMap = useMemo(() => {
    const m: Record<string, string> = {};
    (agents ?? []).forEach(a => { m[a.agent_id] = a.name; });
    return m;
  }, [agents]);

  const sorted = useMemo(() => (rules ?? []).sort((a, b) => a.priority - b.priority), [rules]);

  return (
    <div className="card-dark overflow-hidden">
      <div className="px-4 py-2.5 border-b border-white/[0.06]">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Routing Rules</span>
        {rules && <span className="text-xs text-zinc-600 ml-2">({rules.length})</span>}
      </div>
      <div className="divide-y divide-white/[0.04]">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="px-4 py-3"><div className="skeleton h-10 w-full" /></div>
          ))
        ) : !sorted.length ? (
          <div className="text-center text-zinc-600 py-8 text-sm">No rules configured</div>
        ) : (
          sorted.map(r => (
            <div key={r.id} className="px-4 py-3 table-row-hover">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-3">
                  <span className="font-data text-[10px] text-zinc-600 bg-white/[0.04] px-1.5 py-0.5 rounded">P{r.priority}</span>
                  <span className="text-sm font-medium text-zinc-200">{r.name}</span>
                  {r.fan_out && <span className="text-[10px] text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">fan-out</span>}
                </div>
                <div className={`w-8 h-4 rounded-full relative ${r.active ? "bg-emerald-500/20" : "bg-zinc-800"}`}>
                  <div className={`w-3 h-3 rounded-full absolute top-0.5 transition-all ${r.active ? "left-4 bg-emerald-500" : "left-0.5 bg-zinc-600"}`} />
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-zinc-400">when</span>
                <span className="font-data text-cyan-400/70">{conditionToEnglish(r.conditions)}</span>
                <span className="flow-arrow" />
                <span className="text-zinc-400">route to</span>
                <span className="font-data text-purple-400/80">{targetToString(r.actions, agentMap)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
