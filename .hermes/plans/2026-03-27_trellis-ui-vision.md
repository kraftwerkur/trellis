# Trellis Dashboard — UI Vision

## Design Philosophy

Trellis is an **enterprise healthcare agent orchestration platform**. The dashboard
is an ops command center — it needs to feel like mission control, not a toy.

**Not cyberpunk.** Matrix green and glitch effects are for gaming. Trellis handles
PHI, manages security agents, and monitors healthcare operations. The UI needs to
project trust, competence, and calm authority.

**Not generic SaaS.** Indigo/violet gradients are for productivity apps. Trellis is
an operations platform — it needs status-at-a-glance, real-time data density, and
clear information hierarchy.

## The Right Approach: Dark Ops + Healthcare Trust

Blend the cybersecurity ops palette's dark foundation with healthcare's calming teal.
Think: Bloomberg Terminal meets a modern hospital's command center.

### Color System (Dark-first)

Core palette derived from:
- Cybersecurity Platform (dark foundation, high contrast)
- Healthcare App (teal primary = trust + calm)
- Custom status colors for ops

```
BACKGROUND LAYER
  --background:    222 25% 7%     (#0f1218)  Navy-black, not pure black
  --card:          222 20% 11%    (#161b26)  Lifted surface
  --popover:       222 20% 11%
  --muted:         222 16% 15%    (#1e2430)  Subtle depth
  --border:        220 14% 20%    (#2a3140)  Visible but quiet

CONTENT LAYER  
  --foreground:    210 25% 92%    (#e4ecf5)  Primary text
  --card-foreground: same
  --muted-foreground: 215 15% 55% (#7b8a9e)  Secondary text

BRAND COLORS
  --primary:       187 80% 37%    (#0891B2)  Healthcare teal — trust
  --primary-foreground: 0 0% 100%
  --accent:        160 64% 35%    (#059669)  Health green — positive
  --accent-foreground: 0 0% 100%
  --secondary:     222 14% 20%    (#2a3140)  Muted interactive
  --secondary-foreground: 210 20% 85%
  --destructive:   0 72% 51%     (#DC2626)  Alert red
  --ring:          187 80% 37%    (matches primary)

STATUS COLORS (critical for ops dashboards)
  --status-healthy:  160 64% 45%  (#10B981)  Green pulse
  --status-warning:  38 92% 50%   (#F59E0B)  Amber caution
  --status-critical: 0 72% 51%    (#EF4444)  Red alert
  --status-info:     199 89% 48%  (#0EA5E9)  Blue informational
  --status-unknown:  215 15% 55%  (#7b8a9e)  Gray unknown

CHART PALETTE (5 distinct, colorblind-safe)
  --chart-1: 187 80% 45%   Teal (primary metric)
  --chart-2: 160 64% 45%   Green (positive/health)
  --chart-3: 38 92% 50%    Amber (caution/secondary)
  --chart-4: 262 83% 58%   Purple (tertiary/comparison)
  --chart-5: 0 72% 51%     Red (alerts/negative)
```

### Typography

**Plus Jakarta Sans** — professional, modern, excellent readability at small sizes.
Perfect for data-dense dashboards.

```
Headings: Plus Jakarta Sans 700 (Bold)
Subheads: Plus Jakarta Sans 600 (SemiBold)  
Body:     Plus Jakarta Sans 400 (Regular)
Code/IDs: Fira Code 400 (for trace IDs, agent IDs, JSON)
```

Type scale: 12px captions → 14px body → 16px subhead → 20px section → 28px page title

### Layout Architecture

```
┌──────────────────────────────────────────────────────┐
│ ┌────────┐ ┌──────────────────────────────────────┐  │
│ │        │ │  HEADER BAR                          │  │
│ │ SIDE   │ │  Page title + breadcrumb + actions   │  │
│ │ BAR    │ ├──────────────────────────────────────┤  │
│ │        │ │                                      │  │
│ │ Logo   │ │  KPI STRIP (4 stat cards)            │  │
│ │        │ ├──────────────────────────────────────┤  │
│ │ Ops    │ │                                      │  │
│ │ Intel  │ │  PRIMARY CONTENT AREA                │  │
│ │ Plat   │ │  (charts, tables, feeds)             │  │
│ │ Docs   │ │                                      │  │
│ │        │ │                                      │  │
│ │ ────── │ │                                      │  │
│ │ Status │ │                                      │  │
│ └────────┘ └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

- Sidebar: 240px expanded, 64px collapsed (icon-only)
- Content: fluid, max-w-[1600px] centered
- KPI strip: always visible at top of every page
- Responsive: sidebar becomes bottom sheet on mobile

### Component Language

**Cards:** Subtle border (--border), no shadow. Hover: border brightens to primary/20%.
Rounded-lg (8px). Internal padding p-5.

**Status indicators:** Colored dot (8px) + text label. Never color-only.
Pulse animation on live/healthy status.

**Tables:** Zebra striping with muted/background alternation. Sticky headers.
Monospace for IDs and timestamps.

**Charts:** Recharts with CSS variable colors. Always include legend.
Tooltip follows design tokens. Grid lines at 10% opacity.

**Buttons:** Primary = filled teal. Secondary = ghost with border. 
Destructive = red outline, filled on hover. All have focus ring.

### Page-Specific Notes

**Overview (/):** Command center. 4 KPI cards, cost trend chart, 
activity feed, agent health grid. Real-time polling indicators.

**Agents (/agents):** Card grid with live health dots. Click for detail
slide-over. Show delegation chains as connection lines.

**FinOps (/finops):** Cost trend (area chart), cost by agent (horizontal bar),
budget utilization gauges, model cost comparison table.

**PHI Shield (/phi):** Detection stats, recent redactions (anonymized),
per-agent PHI mode configuration. Red accent for PHI events.

**Gateway (/gateway):** Provider status cards, model routing table,
latency sparklines per model, streaming indicator.

**Routing (/routing):** Rule list with match counts, intelligent router
scoring visualization, feedback history.

### Anti-Patterns to Avoid

- Pure black backgrounds (#000000) — too stark, causes halation
- Matrix/neon green as primary — screams "hacker toy"  
- Emojis as UI elements — SVG icons only (Lucide)
- Color-only status indicators — always pair with text/icon
- Excessive animation — ops dashboards need calm, not motion
- Light mode as default — ops teams work in dark environments
- AI purple/pink gradients — generic and meaningless
