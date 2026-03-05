"use client";

import type { Agent } from "@/types/trellis";
import type { CostSummary } from "@/types/trellis";

function statusDotClass(status: string): string {
  const s = status?.toLowerCase();
  if (s === "active" || s === "healthy" || s === "online") return "status-dot status-dot-healthy";
  if (s === "degraded" || s === "warning") return "status-dot status-dot-degraded";
  return "status-dot status-dot-unhealthy";
}

export function AgentCard({ agent, cost, onClick }: {
  agent: Agent;
  cost?: CostSummary;
  onClick?: () => void;
}) {
  const model = agent.llm_config
    ? (agent.llm_config as Record<string, string>).model || "—"
    : "—";

  return (
    <div
      className="card-dark p-4 cursor-pointer group"
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={statusDotClass(agent.status)} />
            <span className="text-sm font-medium text-zinc-200 truncate">{agent.name}</span>
          </div>
          <div className="text-[10px] text-zinc-600 font-data mt-1 truncate">{agent.agent_id}</div>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.04] border border-white/[0.06] text-zinc-500 font-data shrink-0">
          {agent.framework}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Model</div>
          <div className="font-data text-zinc-400 truncate">{model}</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Type</div>
          <div className="font-data text-zinc-400">{agent.agent_type}</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Requests</div>
          <div className="font-data text-zinc-400">{cost?.request_count ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-600 uppercase tracking-wider">Cost</div>
          <div className="font-data text-zinc-400">
            {cost ? `$${cost.total_cost_usd.toFixed(4)}` : "—"}
          </div>
        </div>
      </div>

      {agent.last_health_check && (
        <div className="mt-3 text-[10px] text-zinc-600 font-data">
          Last check: {new Date(agent.last_health_check).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
