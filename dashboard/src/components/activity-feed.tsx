"use client";

import type { AuditEvent } from "@/types/trellis";

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

function eventBadgeClass(type: string): string {
  const key = type.toLowerCase().replace(/\./g, "_");
  return `event-badge event-${key}`;
}

export function ActivityFeed({ events, limit = 20 }: { events: AuditEvent[] | null; limit?: number }) {
  if (!events) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton h-8 w-full" />
        ))}
      </div>
    );
  }

  if (events.length === 0) {
    return <div className="text-zinc-600 text-sm py-8 text-center">No events yet</div>;
  }

  const shown = events.slice(0, limit);

  return (
    <div className="space-y-0.5">
      {shown.map((ev) => (
        <div key={ev.id} className="flex items-center gap-3 px-3 py-1.5 table-row-hover rounded text-sm">
          <span className="font-data text-[11px] text-zinc-600 w-14 shrink-0">{timeAgo(ev.timestamp)}</span>
          <span className={eventBadgeClass(ev.event_type)}>{ev.event_type.replace(/_/g, " ")}</span>
          {ev.agent_id && (
            <span className="font-data text-xs text-zinc-400 truncate">{ev.agent_id}</span>
          )}
          {ev.trace_id && (
            <span className="font-data text-[10px] text-zinc-600 ml-auto truncate max-w-[120px]" title={ev.trace_id}>
              {ev.trace_id.slice(0, 8)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
