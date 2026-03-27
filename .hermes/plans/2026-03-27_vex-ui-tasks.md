# Vex UI Redesign — Task Plan

**Author:** Lux (architect)
**Date:** 2026-03-27
**Target:** Align Trellis dashboard with UI vision document
**Stack:** Next.js 16 · React 19 · Tailwind CSS v4 · Recharts · Lucide React

---

## Global Rules (apply to EVERY task)

- **DO NOT** change any API calls, types, data fetching logic, or `useStablePolling` hooks
- **DO NOT** change file structure or add new dependencies
- **DO NOT** rewrite entire files — use `patch()` targeted edits
- All colors must use CSS custom properties from `globals.css`, not hardcoded hex
- Dark mode is PRIMARY — never default to light
- Icons: Lucide React only (already installed)

---

## Task 1: CSS Design Tokens — Align with Vision

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/globals.css`

**What to change:**

1. In the `@theme inline` block, update these token values to match the vision spec exactly:
   - `--color-background`: change from `hsl(220 20% 6%)` → `hsl(222 25% 7%)` (vision: `#0f1218`)
   - `--color-card`: change from `hsl(220 18% 10%)` → `hsl(222 20% 11%)` (vision: `#161b26`)
   - `--color-popover`: same as card → `hsl(222 20% 11%)`
   - `--color-secondary`: change from `hsl(220 14% 16%)` → `hsl(222 14% 20%)` (vision: `#2a3140`)
   - `--color-muted`: change from `hsl(220 14% 14%)` → `hsl(222 16% 15%)` (vision: `#1e2430`)
   - `--color-border`: change from `hsl(220 14% 18%)` → `hsl(220 14% 20%)` (vision: `#2a3140`)
   - `--color-input`: same as border → `hsl(220 14% 20%)`
   - `--color-foreground`: change from `hsl(210 20% 90%)` → `hsl(210 25% 92%)` (vision: `#e4ecf5`)
   - `--color-card-foreground`: match foreground
   - `--color-popover-foreground`: match foreground
   - `--color-status-healthy`: change from `hsl(142 71% 45%)` → `hsl(160 64% 45%)` (vision: `#10B981`)

2. Add missing token inside the `@theme inline` block, after the existing status tokens:
   ```css
   --color-status-info: hsl(199 89% 48%);      /* #0EA5E9 blue informational */
   ```

3. Update the chart palette values to match vision:
   - `--color-chart-1`: change from `hsl(187 80% 37%)` → `hsl(187 80% 45%)` (vision says 45%)
   - `--color-chart-2`: change from `hsl(160 64% 35%)` → `hsl(160 64% 45%)` (vision says 45%)

4. In the light mode `@media` override block at the bottom, update `--color-border` to `hsl(220 14% 90%)` (already correct, just verify it stays consistent).

**What NOT to change:**
- Do not touch `--color-primary`, `--color-accent`, `--color-destructive` — they already match vision
- Do not touch any animation keyframes, utility classes, or event-badge definitions
- Do not touch the `@import` statements or `@custom-variant` line

**Acceptance criteria:**
- All token values in `@theme inline` match the vision document's color spec
- `--color-status-info` exists as a new token
- Light mode override block is unchanged except border if needed
- No visual breakage — these are just subtle hue/lightness shifts
- File compiles without Tailwind errors

**Estimated changes:** ~25 lines modified

---

## Task 2: Layout & Header — Vision-Aligned Frame

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/layout.tsx`

**What to change:**

1. **Header component** — update the `<header>` element's className:
   - Replace `bg-black/60` with `bg-[hsl(var(--card))]/80` (vision: no pure black)
   - Replace `border-white/[0.06]` with `border-[hsl(var(--border))]` (use token)
   - Change the page title `<span>` from `text-zinc-500` to `text-[hsl(var(--muted-foreground))]`
   - Change the description `<span>` from `text-zinc-600` to `text-[hsl(var(--muted-foreground))]/60`

2. **Header status pill** — update the container div:
   - Replace `bg-white/[0.04] border border-white/[0.06]` with `bg-[hsl(var(--muted))] border border-[hsl(var(--border))]`
   - Change `text-zinc-400` to `text-[hsl(var(--muted-foreground))]`

3. **Main content area** — in the `<main>` tag:
   - Add `max-w-[1600px]` to the inner `<div className="p-4">` wrapper — change to `<div className="p-4 lg:p-6 max-w-[1600px] mx-auto">`
   - This implements the vision's "Content: fluid, max-w-[1600px] centered" spec

4. **Footer** — update the `<footer>`:
   - Change `text-zinc-600` to `text-[hsl(var(--muted-foreground))]/50`

**What NOT to change:**
- Do not change `PAGE_TITLES` object
- Do not change `useStablePolling(api.health, 10000)` call
- Do not change sidebar props/state (`expanded`, `setExpanded`, `sidebarWidth`)
- Do not change the `<ErrorBoundary>` wrapper
- Do not change `<html lang="en" className="dark">` — dark mode stays primary

**Acceptance criteria:**
- No hardcoded `bg-black` anywhere in the file
- All colors reference CSS custom properties via `hsl(var(...))` or Tailwind tokens
- Content area is centered with max-width on large screens
- Header still correctly positions relative to sidebar width
- Page renders without errors

**Estimated changes:** ~15 lines modified

---

## Task 3: Shared Components — StatCard, ActivityFeed, ErrorBoundary

**Files to modify:**
- `~/workspace/trellis/dashboard/src/components/stat-card.tsx`
- `~/workspace/trellis/dashboard/src/components/activity-feed.tsx`
- `~/workspace/trellis/dashboard/src/components/error-boundary.tsx`

### stat-card.tsx

1. Update the outer `<div>` className: the `card-dark` class and `accent-left-${accent}` are fine, but add `hover:border-[hsl(var(--primary))]/20 transition-colors` to implement vision's card hover spec.
   - Change: `className={`card-dark accent-left-${accent} p-4 group`}`
   - To: `` className={`card-dark accent-left-${accent} p-5 group hover:border-[hsl(var(--primary))]/20 transition-colors`} ``
   - Note: p-4 → p-5 per vision's "Internal padding p-5"

2. Update the value text: change `text-zinc-100` to `text-[hsl(var(--foreground))]`

3. Update the label text: change `text-zinc-500` to `text-[hsl(var(--muted-foreground))]`

4. Update the sub text: change `text-zinc-500` to `text-[hsl(var(--muted-foreground))]`

### activity-feed.tsx

1. In the skeleton `<div>`, change `skeleton h-8` class — this is fine, no change needed.

2. In the empty state, change `text-zinc-600` to `text-[hsl(var(--muted-foreground))]/60`.

3. In the event row, change `text-zinc-600` (time ago) to `text-[hsl(var(--muted-foreground))]/60`.

4. Change `text-zinc-400` (agent ID) to `text-[hsl(var(--muted-foreground))]`.

5. Change `text-zinc-600` (trace ID) to `text-[hsl(var(--muted-foreground))]/50`.

### error-boundary.tsx

1. Change `text-zinc-300` to `text-[hsl(var(--foreground))]`.

2. Change `text-zinc-600` (error message) to `text-[hsl(var(--muted-foreground))]/60`.

3. Change `text-cyan-400 bg-cyan-500/10 hover:bg-cyan-500/20` to `text-[hsl(var(--primary))] bg-[hsl(var(--primary))]/10 hover:bg-[hsl(var(--primary))]/20` on the Retry button.

**What NOT to change:**
- Do not change the StatCard props interface or any prop types
- Do not change ActivityFeed's `timeAgo()` function or `eventBadgeClass()` logic
- Do not change ErrorBoundary's `getDerivedStateFromError` or class component structure
- Do not change any data processing logic

**Acceptance criteria:**
- All three components use CSS variable tokens instead of hardcoded zinc-N colors
- StatCard has p-5 padding and hover border effect matching vision
- No TypeScript errors
- Components render identically in dark mode (colors are near-equivalent)

**Estimated changes:** ~30 lines across 3 files

---

## Task 4: Overview Page — System Health Bar + KPI Strip (Top Section)

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/page.tsx`

**What to change:**

Focus ONLY on the top section of the overview page (lines ~464-526): the loading indicator, system health bar, and KPI stat cards grid.

1. **Loading indicator** (line ~467): Replace hardcoded colors
   - Change `text-zinc-500 bg-zinc-800/50 border border-zinc-700/30` to `text-[hsl(var(--muted-foreground))] bg-[hsl(var(--muted))]/50 border border-[hsl(var(--border))]/50`

2. **System Health Bar** (lines ~473-492): Replace hardcoded colors
   - In the health bar metrics array (lines 480-483), replace all `text-emerald-400` / `text-red-400` / `text-cyan-400` / `text-amber-400` / `text-zinc-500` with the corresponding status token classes:
     - `text-emerald-400` → `text-[hsl(var(--status-healthy))]`
     - `text-red-400` → `text-[hsl(var(--status-critical))]`
     - `text-cyan-400` → `text-[hsl(var(--primary))]`
     - `text-amber-400` → `text-[hsl(var(--status-warning))]`
   - Replace dot colors similarly: `bg-emerald-500` → `bg-[hsl(var(--status-healthy))]`, etc.
   - Change `text-zinc-500` labels to `text-[hsl(var(--muted-foreground))]`
   - Change `text-[hsl(var(--muted-foreground))]` is already used for the "Command Center" label — keep it

3. **Inline StatCard** (lines ~50-96): This component duplicates `@/components/stat-card.tsx`. Leave it as-is for now (refactoring to use the shared component would change data flow), but update its hardcoded colors:
   - `text-zinc-100` → `text-[hsl(var(--foreground))]`
   - `text-zinc-500` (label/trend) → `text-[hsl(var(--muted-foreground))]`
   - `text-emerald-400` (trend up) → `text-[hsl(var(--status-healthy))]`
   - `text-red-400` (trend down) → `text-[hsl(var(--status-critical))]`

**What NOT to change:**
- Do not change any `useStablePolling` calls or `useMemo`/`useCallback` hooks
- Do not change the data computation logic (lines 384-461)
- Do not change the grid layout `grid-cols-2 lg:grid-cols-4 gap-3`
- Do not touch the middle or bottom sections yet
- Do not remove or rename the inline StatCard/Sparkline components

**Acceptance criteria:**
- Top section of overview uses design tokens throughout
- No hardcoded zinc/emerald/red/cyan color classes in the health bar or stat cards
- KPI strip still shows 4 cards in correct grid layout
- Health bar still displays live status metrics
- Page renders without errors

**Estimated changes:** ~50 lines modified

---

## Task 5: Overview Page — Charts, Feeds, and Bottom Section

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/page.tsx`

**What to change:**

Focus on the MIDDLE section (lines ~528-561) and BOTTOM section (lines ~563-598), plus the chart/feed components defined earlier in the file.

1. **ActivityTimeline component** (lines ~142-179): Update colors
   - Change card `border-white/[0.06]` → `border-[hsl(var(--border))]` (3 occurrences in this component)
   - Change `bg-[hsl(var(--card))]` — already correct, keep it
   - Change `text-zinc-600` (separator dot, empty state) → `text-[hsl(var(--muted-foreground))]/50`
   - Change `text-zinc-500` (agent name) → `text-[hsl(var(--muted-foreground))]`
   - Change `text-zinc-300` (message text) → `text-[hsl(var(--foreground))]/80`
   - Change `text-zinc-600` (timestamp) → `text-[hsl(var(--muted-foreground))]/50`
   - Change `bg-emerald-500` (live pulse) → `bg-[hsl(var(--status-healthy))]`
   - Change divider `divide-white/[0.04]` → `divide-[hsl(var(--border))]/50`
   - Change hover `hover:bg-white/[0.02]` → `hover:bg-[hsl(var(--muted))]/50`

2. **AgentHealthGrid component** (lines ~183-225): Update colors
   - Same card border pattern as above
   - Change `text-zinc-200` → `text-[hsl(var(--foreground))]`
   - Change `text-zinc-500` → `text-[hsl(var(--muted-foreground))]`
   - Change `text-zinc-600` → `text-[hsl(var(--muted-foreground))]/60`
   - Replace status dot colors: `bg-emerald-500` → `bg-[hsl(var(--status-healthy))]`, `bg-amber-500` → `bg-[hsl(var(--status-warning))]`, `bg-red-500` → `bg-[hsl(var(--status-critical))]`
   - Same for ring colors

3. **CostTrendChart** (lines ~229-262): Update Tooltip
   - Change Tooltip `contentStyle` background from `#18181b` to `hsl(222, 20%, 11%)` (matches --card token)
   - Change border to use token-equivalent: `1px solid hsl(220, 14%, 20%)`

4. **EventsOverTimeChart** (lines ~266-325): Same Tooltip update as above
   - Change background from `#18181b` to `hsl(222, 20%, 11%)`
   - Change `text-zinc-600` "No event data" → `text-[hsl(var(--muted-foreground))]/50`

5. **AgentStatusChart** (lines ~329-380): Update legend colors
   - Change `text-zinc-400` → `text-[hsl(var(--muted-foreground))]`
   - Change `text-zinc-200` → `text-[hsl(var(--foreground))]`
   - Replace status dot colors in legend same as AgentHealthGrid

6. **Cost by Agent section** (lines ~534-559) and **Recent Alerts** (lines ~569-595):
   - These already use `hsl(var(...))` tokens — verify and leave unchanged
   - Change any remaining `text-zinc-600` → `text-[hsl(var(--muted-foreground))]/50`

**What NOT to change:**
- Do not change Recharts data transformations or chart configs (dataKey, type, margins)
- Do not change `useMemo`/`useEffect`/`useCallback` hooks
- Do not change the EVENT_CONFIG mapping object
- Do not change `formatTimeAgo()` or `eventSummary()` helper functions
- Do not change grid layouts (grid-cols-1 lg:grid-cols-2)

**Acceptance criteria:**
- All chart tooltips use design token colors (no hardcoded hex in contentStyle)
- All text colors reference CSS variables
- Activity feed, agent grid, and charts render correctly
- Status dots use `--status-*` tokens
- No hardcoded zinc-N classes remain in the modified sections

**Estimated changes:** ~80 lines modified

---

## Task 6: Agents Page — Token Alignment

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/agents/page.tsx`
- `~/workspace/trellis/dashboard/src/components/agent-card.tsx`
- `~/workspace/trellis/dashboard/src/components/agent-detail-panel.tsx`

### agents/page.tsx

1. Replace all hardcoded zinc colors:
   - `text-zinc-500` → `text-[hsl(var(--muted-foreground))]` (header label, filter count)
   - `text-zinc-600` → `text-[hsl(var(--muted-foreground))]/60` (table headers, timestamps, empty states)
   - `text-zinc-300` → `text-[hsl(var(--foreground))]/80` (search input text)
   - `text-zinc-200` → `text-[hsl(var(--foreground))]` (agent name)
   - `text-zinc-400` → `text-[hsl(var(--muted-foreground))]` (department, type, framework)
   - `placeholder-zinc-600` → `placeholder-[hsl(var(--muted-foreground))]/40`

2. Replace `border-white/[0.06]` with `border-[hsl(var(--border))]` throughout

3. In the search input, replace `focus:border-cyan-500/40 focus:ring-cyan-500/20` with `focus:border-[hsl(var(--primary))]/40 focus:ring-[hsl(var(--primary))]/20`

4. In the expanded row detail (line ~121), replace `bg-black/30` with `bg-[hsl(var(--background))]/80` and `bg-black/40` (code block) with `bg-[hsl(var(--background))]`

5. Replace `text-amber-400` (cost value) with `text-[hsl(var(--status-warning))]`

### agent-card.tsx

1. Replace all zinc-N colors with token equivalents (same pattern as above)
2. Change `bg-white/[0.04] border border-white/[0.06]` (framework badge) to `bg-[hsl(var(--muted))] border border-[hsl(var(--border))]`

### agent-detail-panel.tsx

1. Replace `bg-[#0a0b10]` (panel background, line 25) with `bg-[hsl(var(--background))]` — vision says no near-black hex
2. Replace `bg-black/50` (overlay) with `bg-[hsl(var(--background))]/60`
3. Replace all zinc-N text colors with token equivalents
4. Replace `text-emerald-400` (cost value) with `text-[hsl(var(--status-healthy))]`
5. Replace `border-white/[0.06]` with `border-[hsl(var(--border))]` throughout

**What NOT to change:**
- Do not change `useStablePolling` calls or any data fetching
- Do not change the `AgentRow` component's conditional polling (`isExpanded ? 10000 : 0`)
- Do not change table structure or column layout
- Do not change the `costMap` or `filteredAgents` memo logic
- Do not change the `formatDate` helper function

**Acceptance criteria:**
- Zero hardcoded hex colors (`#0a0b10`, `#52525b`, etc.) in any of the three files
- Zero hardcoded `zinc-N` Tailwind classes
- All colors reference `hsl(var(--*))` design tokens
- Table, expanded row, agent cards, and detail panel render correctly
- Search/filter functionality unchanged

**Estimated changes:** ~80 lines across 3 files

---

## Task 7: FinOps Page — Token Alignment + Vision Polish

**Files to modify:**
- `~/workspace/trellis/dashboard/src/app/finops/page.tsx`

**What to change:**

1. **Top stat cards** (lines ~71-86): Replace hardcoded icon colors
   - `text-amber-500` → `text-[hsl(var(--status-warning))]`
   - `text-cyan-500` → `text-[hsl(var(--primary))]`
   - `text-violet-500` → `text-[hsl(var(--chart-4))]`
   - `text-emerald-500` → `text-[hsl(var(--status-healthy))]`
   - `text-zinc-200` → `text-[hsl(var(--foreground))]`
   - `text-zinc-600` → `text-[hsl(var(--muted-foreground))]/60`
   - Add `p-5` instead of `p-4` per vision card padding spec

2. **All card headers**: Replace `text-zinc-500` → `text-[hsl(var(--muted-foreground))]`

3. **All Tooltip contentStyle objects** (4 occurrences): Replace `background: "#0a0a0f"` with `background: "hsl(222, 20%, 11%)"` and `border: "1px solid rgba(255,255,255,0.06)"` with `border: "1px solid hsl(220, 14%, 20%)"`

4. **Granularity toggle buttons** (lines ~93-98):
   - Replace `bg-cyan-500/20 text-cyan-400` with `bg-[hsl(var(--primary))]/20 text-[hsl(var(--primary))]`
   - Replace `text-zinc-600 hover:text-zinc-400` with `text-[hsl(var(--muted-foreground))]/60 hover:text-[hsl(var(--muted-foreground))]`

5. **XAxis/YAxis tick fills**: Replace `fill: "#52525b"` with `fill: "hsl(215, 15%, 55%)"` (matches --muted-foreground) and `fill: "#71717a"` with same value

6. **Cost by Agent bar list** (lines ~171-187):
   - Replace `text-zinc-400` → `text-[hsl(var(--muted-foreground))]`
   - Replace `text-amber-400` → `text-[hsl(var(--status-warning))]`
   - Replace `bg-white/[0.04]` → `bg-[hsl(var(--muted))]/30`

7. **Budget tracker** (lines ~200-220):
   - Replace `text-zinc-400` → `text-[hsl(var(--muted-foreground))]`
   - Replace `text-zinc-300` → `text-[hsl(var(--foreground))]/80`
   - Replace `text-zinc-600` → `text-[hsl(var(--muted-foreground))]/50`
   - The progress bar colors (`#ef4444`, `#f59e0b`, `#10b981`) should use token values:
     - `#ef4444` → `hsl(0, 72%, 51%)` (matches --status-critical)
     - `#f59e0b` → `hsl(38, 92%, 50%)` (matches --status-warning)
     - `#10b981` → `hsl(160, 64%, 45%)` (matches --status-healthy)

8. Replace `border-white/[0.06]` with `border-[hsl(var(--border))]` throughout

**What NOT to change:**
- Do not change `COLORS` array (used for Recharts Cell fills — these are fine as-is for chart variety)
- Do not change `BUDGET_CAP_DAILY` or `BUDGET_CAP_MONTHLY` constants
- Do not change any `useStablePolling` calls or memo logic
- Do not change `granularity` state or its setter
- Do not change chart data transformations (`deptData`, `modelData` memos)

**Acceptance criteria:**
- Zero `#0a0a0f` or other hardcoded dark hex values in tooltip styles
- All text colors reference design tokens
- Budget progress bars use token-equivalent HSL values
- Granularity toggle uses primary token color
- All card borders use `--border` token
- Charts and data display render correctly

**Estimated changes:** ~70 lines modified

---

## Execution Summary

| Task | Risk | Files | Est. Lines |
|------|------|-------|------------|
| 1. CSS Tokens | Zero (CSS-only) | 1 | ~25 |
| 2. Layout/Header | Low | 1 | ~15 |
| 3. Shared Components | Low | 3 | ~30 |
| 4. Overview Top | Medium | 1 | ~50 |
| 5. Overview Charts/Bottom | Medium | 1 | ~80 |
| 6. Agents + Components | Medium | 3 | ~80 |
| 7. FinOps | Medium | 1 | ~70 |

**Total estimated changes:** ~350 lines across 11 files

**Execute in order.** Task 1 must complete before all others (tokens referenced downstream). Tasks 2-3 can run in parallel. Tasks 4-7 depend on Task 1 being done.

After all tasks: verify `npm run build` passes with zero TypeScript or Tailwind errors.
