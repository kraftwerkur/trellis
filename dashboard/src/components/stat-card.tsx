import { type ReactNode } from "react";

export function StatCard({ label, value, sub, accent = "cyan" }: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: "cyan" | "emerald" | "amber" | "purple" | "red";
}) {
  return (
    <div className={`card-dark accent-left-${accent} p-4`}>
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 mb-1">{label}</div>
      <div className="text-2xl font-bold font-data text-zinc-100">{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-1">{sub}</div>}
    </div>
  );
}
