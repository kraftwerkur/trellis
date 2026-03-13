"use client";

import "./globals.css";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { useStablePolling } from "@/lib/hooks";
import { Sidebar } from "@/components/sidebar";
import { ErrorBoundary } from "@/components/error-boundary";

const PAGE_TITLES: Record<string, { title: string; desc: string }> = {
  "/": { title: "Command Center", desc: "System health and activity at a glance" },
  "/agents": { title: "Agents", desc: "Registered agents, status, and performance" },
  "/audit": { title: "Audit Log", desc: "Event stream — what happened and when" },
  "/routing": { title: "Routing", desc: "Intelligent routing, agent intake, and overlap analysis" },
  "/rules": { title: "Rules", desc: "Routing rules that determine agent dispatch" },
  "/gateway": { title: "Gateway", desc: "LLM gateway providers, routes, and stats" },
  "/phi": { title: "PHI Shield", desc: "Protected health information detection and redaction" },
  "/finops": { title: "FinOps", desc: "Cost tracking, budgets, and model usage analytics" },
  "/documents": { title: "Documents", desc: "Document ingestion and text extraction" },
  "/alerts": { title: "Alerts", desc: "Alert rules, notification channels, and event history" },
  "/docs": { title: "Docs", desc: "Architecture, API reference, and quick start guides" },
};

function Header({ sidebarWidth }: { sidebarWidth: number }) {
  const pathname = usePathname();
  const { data: health } = useStablePolling(api.health, 10000);
  const page = Object.entries(PAGE_TITLES).find(([k]) => k === "/" ? pathname === "/" : pathname.startsWith(k))?.[1];
  const isOnline = health?.status === "ok" || health?.status === "healthy";

  return (
    <header
      className="fixed top-0 right-0 z-30 h-12 flex items-center justify-between px-4 bg-black/60 backdrop-blur-xl border-b border-white/[0.06]"
      style={{ left: sidebarWidth }}
    >
      <div className="flex items-center gap-3">
        <span className="text-xs uppercase tracking-widest text-zinc-500 font-medium">{page?.title || "Trellis"}</span>
        {page?.desc && (
          <span className="hidden sm:inline text-[10px] text-zinc-600">— {page.desc}</span>
        )}
      </div>
      <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-white/[0.04] border border-white/[0.06]">
        <span className={`status-dot ${isOnline ? "status-dot-online" : "status-dot-unhealthy"}`} />
        <span className="text-xs font-data text-zinc-400">
          {health ? (isOnline ? "Online" : "Offline") : "…"}
        </span>
      </div>
    </header>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const sidebarWidth = expanded ? 220 : 56;

  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Sidebar expanded={expanded} setExpanded={setExpanded} />
        <Header sidebarWidth={sidebarWidth} />
        <main
          className="grid-bg pt-12 min-h-screen transition-all duration-200"
          style={{ marginLeft: sidebarWidth }}
        >
          <div className="p-4">
            <ErrorBoundary fallbackTitle="Page failed to render">
              {children}
            </ErrorBoundary>
          </div>
          <footer className="flex items-center justify-center gap-2 py-4 text-[10px] text-zinc-600 uppercase tracking-widest">
            <span className="heartbeat-dot" />
            <span>Trellis v0.1.0 • Health First</span>
          </footer>
        </main>
      </body>
    </html>
  );
}
