"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Bot,
  GitBranch,
  Route,
  Network,
  Telescope,
  ShieldCheck,
  DollarSign,
  Shield,
  HeartPulse,
  BellRing,
  Wrench,
  FileText,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Circle,
} from "lucide-react";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import type { Agent } from "@/lib/api";
import type { LucideIcon } from "lucide-react";

/* ── Nav structure ────────────────────────────────────────── */

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: "agents";
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Operations",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/agents", label: "Agents", icon: Bot, badge: "agents" },
      { href: "/rules", label: "Rules", icon: GitBranch },
      { href: "/routing", label: "Routing", icon: Route },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/gateway", label: "Gateway", icon: Network },
      { href: "/observatory", label: "Observatory", icon: Telescope },
      { href: "/phi", label: "PHI Shield", icon: ShieldCheck },
    ],
  },
  {
    title: "Platform",
    items: [
      { href: "/finops", label: "FinOps", icon: DollarSign },
      { href: "/audit", label: "Audit", icon: Shield },
      { href: "/health", label: "Health", icon: HeartPulse },
      { href: "/alerts", label: "Alerts", icon: BellRing },
      { href: "/tools", label: "Tools", icon: Wrench },
      { href: "/documents", label: "Documents", icon: FileText },
    ],
  },
  {
    title: "Documentation",
    items: [{ href: "/docs", label: "Docs", icon: BookOpen }],
  },
];

/* ── Agent health helper ──────────────────────────────────── */

function useAgentHealth() {
  const { data: agents } = useStablePolling<Agent[]>(api.agents.list, 15000);
  if (!agents) return { count: 0, color: "bg-secondary" };
  const healthy = agents.filter(
    (a) => a.status === "healthy" || a.status === "idle",
  ).length;
  const ratio = agents.length > 0 ? healthy / agents.length : 0;
  const color =
    ratio >= 0.8
      ? "bg-status-healthy"
      : ratio >= 0.5
        ? "bg-status-warning"
        : "bg-destructive";
  return { count: agents.length, color };
}

/* ── Sidebar ──────────────────────────────────────────────── */

export function Sidebar({
  expanded,
  setExpanded,
}: {
  expanded: boolean;
  setExpanded: (v: boolean) => void;
}) {
  const pathname = usePathname();
  const agentHealth = useAgentHealth();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const sidebarContent = (
    <>
      {/* Logo / Title */}
      <div className="flex items-center h-12 px-3 border-b border-border shrink-0">
        {expanded ? (
          <div className="flex items-center gap-2">
            <span className="w-2 h-5 rounded-sm bg-primary" />
            <span className="text-sm font-bold tracking-widest text-foreground">
              TRELLIS
            </span>
          </div>
        ) : (
          <div className="flex items-center justify-center w-full">
            <span className="text-sm font-bold text-primary">T</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title}>
            {expanded && (
              <div className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground font-semibold px-2 mb-1.5">
                {section.title}
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={[
                      "group relative flex items-center gap-3 rounded-md text-sm transition-all duration-200",
                      expanded ? "px-3 py-2" : "justify-center py-2 px-0",
                      active
                        ? "bg-primary/[0.08] text-primary border-l-[3px] border-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50 border-l-[3px] border-transparent",
                    ].join(" ")}
                  >
                    <item.icon className="w-4 h-4 shrink-0" />
                    {expanded && (
                      <span className="truncate">{item.label}</span>
                    )}
                    {/* Agent status dot */}
                    {item.badge === "agents" && (
                      <span className="flex items-center gap-1 ml-auto">
                        <Circle
                          className={`w-2 h-2 ${agentHealth.color} rounded-full fill-current`}
                        />
                        {expanded && agentHealth.count > 0 && (
                          <span className="text-[10px] font-data text-muted-foreground">
                            {agentHealth.count}
                          </span>
                        )}
                      </span>
                    )}
                    {/* Tooltip for collapsed mode */}
                    {!expanded && (
                      <span className="absolute left-full ml-2 px-2 py-1 rounded bg-background border border-border text-xs text-foreground/80 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none z-50">
                        {item.label}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Collapse toggle (desktop) */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="hidden md:flex items-center justify-center h-10 border-t border-border text-muted-foreground hover:text-muted-foreground transition-colors duration-200 shrink-0"
      >
        {expanded ? (
          <ChevronLeft className="w-4 h-4" />
        ) : (
          <ChevronRight className="w-4 h-4" />
        )}
      </button>
    </>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-2 left-2 z-50 p-2 rounded-md bg-card border border-border text-muted-foreground hover:text-foreground transition-colors"
        aria-label="Open menu"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={[
          "md:hidden fixed left-0 top-0 bottom-0 z-50 w-64 flex flex-col border-r border-border transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
        style={{ background: "var(--color-card)" }}
      >
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute top-2 right-2 p-1 text-muted-foreground hover:text-foreground/80"
          aria-label="Close menu"
        >
          <X className="w-4 h-4" />
        </button>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex fixed left-0 top-0 bottom-0 z-40 flex-col border-r border-border transition-all duration-200"
        style={{
          width: expanded ? 220 : 56,
          background: "var(--color-card)",
        }}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
