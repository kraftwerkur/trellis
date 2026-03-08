"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Bot, Shield, ShieldCheck, GitBranch, Network, DollarSign, BookOpen, Wrench, Telescope, ChevronLeft, ChevronRight } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/audit", label: "Audit", icon: Shield },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/rules", label: "Rules", icon: GitBranch },
  { href: "/gateway", label: "Gateway", icon: Network },
  { href: "/phi", label: "PHI Shield", icon: ShieldCheck },
  { href: "/finops", label: "FinOps", icon: DollarSign },
  { href: "/observatory", label: "Observatory", icon: Telescope },
  { href: "/docs", label: "Docs", icon: BookOpen },
];

export function Sidebar({ expanded, setExpanded }: { expanded: boolean; setExpanded: (v: boolean) => void }) {
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 bottom-0 z-40 flex flex-col border-r border-white/[0.06] transition-all duration-200"
      style={{ width: expanded ? 220 : 56, background: "#050508" }}
    >
      <div className="flex items-center h-12 px-3 border-b border-white/[0.06]">
        {expanded ? (
          <span className="text-sm font-bold tracking-tight text-cyan-400">TRELLIS</span>
        ) : (
          <span className="text-sm font-bold text-cyan-400 mx-auto">T</span>
        )}
      </div>
      <nav className="flex-1 py-2 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item flex items-center gap-3 px-3 py-2 text-sm ${
                active ? "nav-item-active text-cyan-400" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <item.icon className="w-4 h-4 shrink-0" />
              {expanded && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-center h-10 border-t border-white/[0.06] text-zinc-600 hover:text-zinc-400"
      >
        {expanded ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>
    </aside>
  );
}
