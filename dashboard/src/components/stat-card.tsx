import { type ReactNode } from "react";
import {
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from "lucide-react";

type Accent = "cyan" | "emerald" | "amber" | "purple" | "red";
type Status = "healthy" | "warning" | "critical";
type Trend = "up" | "down";

const STATUS_CONFIG: Record<
  Status,
  { icon: typeof CheckCircle2; color: string; label: string }
> = {
  healthy: {
    icon: CheckCircle2,
    color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    label: "Healthy",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    label: "Warning",
  },
  critical: {
    icon: XCircle,
    color: "text-red-400 bg-red-400/10 border-red-400/20",
    label: "Critical",
  },
};

const TREND_CONFIG: Record<Trend, { icon: typeof TrendingUp; color: string }> =
  {
    up: { icon: TrendingUp, color: "text-emerald-400" },
    down: { icon: TrendingDown, color: "text-red-400" },
  };

export function StatCard({
  label,
  value,
  sub,
  accent = "cyan",
  trend,
  trendLabel,
  status,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: Accent;
  trend?: Trend;
  trendLabel?: string;
  status?: Status;
}) {
  const trendCfg = trend ? TREND_CONFIG[trend] : null;
  const statusCfg = status ? STATUS_CONFIG[status] : null;

  return (
    <div className={`card-dark accent-left-${accent} p-5 group hover:border-[hsl(var(--primary))]/20 transition-colors`}>
      {/* Header row: label + optional status badge */}
      <div className="flex items-center justify-between mb-1">
        <div className="text-[10px] uppercase tracking-widest text-[hsl(var(--muted-foreground))]">
          {label}
        </div>
        {statusCfg && (
          <span
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold border ${statusCfg.color}`}
          >
            <statusCfg.icon className="w-2.5 h-2.5" />
            {statusCfg.label}
          </span>
        )}
      </div>

      {/* Value row */}
      <div className="flex items-end gap-2">
        <div className="text-2xl font-bold font-data text-[hsl(var(--foreground))]">
          {value}
        </div>
        {trendCfg && (
          <div
            className={`flex items-center gap-0.5 mb-0.5 ${trendCfg.color}`}
          >
            <trendCfg.icon className="w-3.5 h-3.5" />
            {trendLabel && (
              <span className="text-xs font-data">{trendLabel}</span>
            )}
          </div>
        )}
      </div>

      {/* Sub text */}
      {sub && <div className="text-xs text-[hsl(var(--muted-foreground))] mt-1">{sub}</div>}
    </div>
  );
}
