"use client";

import { useCallback } from "react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { GatewayProvider, GatewayModel, GatewayStatsResponse } from "@/types/trellis";
import { Server, Zap, DollarSign, BarChart3 } from "lucide-react";

export default function GatewayPage() {
  const fetchHealth = useCallback(() => api.health(), []);
  const fetchProviders = useCallback(() => api.gateway.providers(), []);
  const fetchModels = useCallback(() => api.gateway.models(), []);
  const fetchStats = useCallback(() => api.gateway.stats(), []);

  const { data: health } = useStablePolling(fetchHealth, 10000);
  const { data: providers, loading } = useStablePolling<GatewayProvider[]>(fetchProviders, 30000);
  const { data: models } = useStablePolling<GatewayModel[]>(fetchModels, 30000);
  const { data: stats } = useStablePolling<GatewayStatsResponse>(fetchStats, 15000);

  const isOnline = health?.status === "ok" || health?.status === "healthy";

  const totalCost = stats?.total_cost ?? 0;
  const totalRequests = stats?.total_requests ?? 0;

  return (
    <div className="space-y-4">
      {/* Gateway status + stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="card-dark p-4 flex items-center gap-3">
          <Server className={`w-5 h-5 ${isOnline ? "text-emerald-500" : "text-red-500"}`} />
          <div>
            <div className="text-sm font-medium text-zinc-200">{isOnline ? "Online" : "Offline"}</div>
            <div className="text-[10px] text-zinc-600 uppercase">Gateway Status</div>
          </div>
        </div>
        <div className="card-dark p-4 flex items-center gap-3">
          <Zap className="w-5 h-5 text-cyan-500" />
          <div>
            <div className="text-sm font-data text-zinc-200">{providers?.filter(p => p.configured).length ?? 0}</div>
            <div className="text-[10px] text-zinc-600 uppercase">Providers</div>
          </div>
        </div>
        <div className="card-dark p-4 flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-blue-500" />
          <div>
            <div className="text-sm font-data text-zinc-200">{totalRequests}</div>
            <div className="text-[10px] text-zinc-600 uppercase">Total Requests</div>
          </div>
        </div>
        <div className="card-dark p-4 flex items-center gap-3">
          <DollarSign className="w-5 h-5 text-amber-500" />
          <div>
            <div className="text-sm font-data text-zinc-200">${totalCost.toFixed(4)}</div>
            <div className="text-[10px] text-zinc-600 uppercase">Total Spend</div>
          </div>
        </div>
      </div>

      {/* Provider cards */}
      {providers && providers.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-widest text-zinc-500 font-medium mb-2">Providers</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {providers.map(p => (
              <div key={p.name} className="card-dark p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`status-dot ${p.configured ? "status-dot-online" : "status-dot-offline"}`} />
                  <span className="text-sm font-medium text-zinc-200">{p.display_name}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="font-data text-zinc-300">{p.models.length}</div>
                    <div className="text-zinc-600">models</div>
                  </div>
                  <div>
                    <div className="font-data text-zinc-300">{stats?.requests_by_provider?.[p.name] ?? 0}</div>
                    <div className="text-zinc-600">requests</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Model routing table */}
      <div className="card-dark overflow-hidden">
        <div className="px-4 py-2.5 border-b border-white/[0.06]">
          <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">Model Routing</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-zinc-600 uppercase border-b border-white/[0.06]">
                <th className="text-left px-3 py-2">Model</th>
                <th className="text-left px-3 py-2">Provider</th>
                <th className="text-left px-3 py-2">Requests</th>
                <th className="text-left px-3 py-2">Tokens</th>
                <th className="text-left px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i}>{Array.from({ length: 5 }).map((_, j) => (
                    <td key={j} className="px-3 py-2"><div className="skeleton h-4 w-full" /></td>
                  ))}</tr>
                ))
              ) : !models?.length ? (
                <tr><td colSpan={5} className="text-center text-zinc-600 py-8">No model data yet</td></tr>
              ) : (
                models.map(m => (
                  <tr key={m.model} className="table-row-hover">
                    <td className="px-3 py-2 font-data text-xs text-zinc-300">{m.model}</td>
                    <td className="px-3 py-2 text-xs text-zinc-400 capitalize">{m.provider}</td>
                    <td className="px-3 py-2 font-data text-xs text-zinc-400">—</td>
                    <td className="px-3 py-2 font-data text-xs text-zinc-400">—</td>
                    <td className="px-3 py-2 text-xs">
                      <span className={m.available ? "text-emerald-400" : "text-zinc-600"}>{m.available ? "Available" : "Not configured"}</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
