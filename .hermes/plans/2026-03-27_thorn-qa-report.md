# Thorn QA Report — Trellis Dashboard UI Redesign

**Date:** 2026-03-27
**Inspector:** Thorn (QA)
**Scope:** dashboard/src/ (.tsx, .ts, .css files only)

---

## 1. Token Audit — FAIL ❌

Massive number of hardcoded color anti-patterns remain across nearly every page.

### 1a. `zinc-` (Tailwind zinc scale) — 291 instances

| File | Count |
|------|-------|
| routing/page.tsx | 43 |
| rules/page.tsx | 31 |
| health/page.tsx | 30 |
| documents/page.tsx | 28 |
| alerts/page.tsx | 26 |
| observatory/page.tsx | 24 |
| phi/page.tsx | 24 |
| tools/page.tsx | 23 |
| gateway/page.tsx | 22 |
| docs/page.tsx | 17 |
| audit/page.tsx | 13 |
| components/sidebar.tsx | 9 |
| page.tsx (home) | 1 |

### 1b. `emerald-` `red-` `amber-` `cyan-` `violet-` (non-token colors) — 136 instances

| File | Count |
|------|-------|
| routing/page.tsx | 25 |
| rules/page.tsx | 19 |
| alerts/page.tsx | 15 |
| observatory/page.tsx | 12 |
| phi/page.tsx | 12 |
| page.tsx (home) | 11 |
| documents/page.tsx | 9 |
| components/sidebar.tsx | 6 |
| components/stat-card.tsx | 5 |
| health/page.tsx | 5 |
| tools/page.tsx | 5 |
| gateway/page.tsx | 4 |
| docs/page.tsx | 4 |
| audit/page.tsx | 3 |
| components/error-boundary.tsx | 1 |

### 1c. Hardcoded hex (`#0a0a0f`, `#52525b`, `#71717a`) — 24 instances

| File | Count |
|------|-------|
| observatory/page.tsx | 9 (chart tick fills + tooltip bg) |
| health/page.tsx | 6 (chart tick fills + tooltip bg + fallback color) |
| routing/page.tsx | 4 (chart tick fills + tooltip bg) |
| phi/page.tsx | 3 (chart tick fills + tooltip bg) |
| page.tsx (home) | 2 (`#71717a` in pie chart color map) |

Notable: `#0a0a0f` used as tooltip background in 6 places, `#52525b` used as chart tick fill in 12+ places, `#71717a` used as fallback status color.

### 1d. `bg-black` (pure black backgrounds) — 7 instances

| File | Count |
|------|-------|
| audit/page.tsx | 3 (bg-black/40, bg-black/30) |
| alerts/page.tsx | 1 (bg-black/60 modal overlay) |
| rules/page.tsx | 1 (bg-black/60 modal overlay) |
| docs/page.tsx | 1 (bg-black/40) |
| components/sidebar.tsx | 1 (bg-black/60 mobile overlay) |

### 1e. `border-white/` (non-token borders) — 76 instances

| File | Count |
|------|-------|
| routing/page.tsx | 11 |
| observatory/page.tsx | 9 |
| health/page.tsx | 8 |
| documents/page.tsx | 8 |
| alerts/page.tsx | 8 |
| phi/page.tsx | 7 |
| rules/page.tsx | 7 |
| components/sidebar.tsx | 6 |
| tools/page.tsx | 5 |
| audit/page.tsx | 4 |
| gateway/page.tsx | 2 |
| docs/page.tsx | 1 |

### Token Audit Total: **534 violations across 15 files**

---

## 2. CSS Token Completeness — PASS ✅

All required tokens verified present in `globals.css`:

| Token Category | Tokens | Status |
|---------------|--------|--------|
| Dark surfaces | background, card, popover, muted, border, input | ✅ All present |
| Text | foreground, card-foreground, muted-foreground | ✅ All present |
| Brand | primary, accent, secondary, destructive | ✅ All present |
| Ops status | status-healthy, status-warning, status-critical, status-info, status-unknown | ✅ All present |
| Data viz | chart-1, chart-2, chart-3, chart-4, chart-5 | ✅ All present |

Additional good findings:
- Utility classes (.text-healthy, .bg-healthy, etc.) defined
- Status dot animations use CSS vars
- Light mode override also defined
- card-dark, glow-*, accent-left-* utility classes provided

---

## 3. Build Check — PARTIAL PASS ⚠️

- **TypeScript compilation:** PASS ✅ — `npx tsc --noEmit` exits clean, zero errors
- **Next.js build:** FAIL ❌ — Turbopack build fails with workspace root resolution error:
  ```
  Error: Next.js inferred your workspace root, but it may not be correct.
  We couldn't find the Next.js package (next/package.json) from the project directory
  ```
  This is a Turbopack config issue (Next.js 16.2.1), not a code issue. The `turbopack.root` option needs to be set in `next.config.ts`. This is an infra/config concern, not a UI redesign regression.

---

## 4. Overall Verdict: REQUEST_CHANGES ❌

### Summary

The CSS design token system in globals.css is **well-designed and complete**. However, the tokens are barely used in the actual component files. The vast majority of pages still use raw Tailwind color classes (zinc-*, emerald-*, red-*, cyan-*, etc.) and hardcoded hex values instead of the semantic tokens.

### What must be fixed

1. **Replace all 291 `zinc-*` usages** with semantic tokens (muted, muted-foreground, border, card, secondary, etc.)
2. **Replace all 136 `emerald-/red-/amber-/cyan-/violet-*` usages** with status tokens (status-healthy, status-warning, status-critical, status-info) and brand tokens (primary, accent, destructive, chart-*)
3. **Replace all 24 hardcoded hex values** in Recharts configs with CSS variable references
4. **Replace 76 `border-white/[0.0x]` usages** with `border-border` or appropriate token
5. **Replace 7 `bg-black/*` usages** with `bg-background` or appropriate card/overlay token
6. **Fix Next.js build** by adding `turbopack: { root: '.' }` to next.config.ts (or similar)

### Files requiring the most work (by total violations)

1. `routing/page.tsx` — ~83 violations
2. `rules/page.tsx` — ~58 violations
3. `alerts/page.tsx` — ~50 violations
4. `health/page.tsx` — ~44 violations
5. `observatory/page.tsx` — ~42 violations
6. `phi/page.tsx` — ~43 violations
7. `documents/page.tsx` — ~36 violations

The token system exists. The migration to actually *use* it was not performed.
