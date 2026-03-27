# Trellis Dashboard Token Migration — QA Re-verification Report

**Date:** 2026-03-27
**QA Engineer:** Thorn
**Scope:** All `.tsx` files under `src/` (excluding `node_modules`)

---

## 1. Token Audit

### zinc-\d (Tailwind zinc scale)
**Result: PASS — 0 instances**

### Semantic color scales (emerald, red, amber, cyan, violet, purple, blue, green, yellow)
**Result: PASS — 0 instances**

### Hardcoded hex colors (#RRGGBB)
**Result: FAIL — 6 real violations in 1 file**

| File | Count | Notes |
|------|-------|-------|
| `src/app/finops/page.tsx` | 6 | Chart colors: `#06b6d4`, `#8b5cf6`, `#f59e0b`, `#10b981`, `#ef4444`, `#ec4899`; also `#a1a1aa` for label text |
| `src/app/phi/page.tsx` | 1 | FALSE POSITIVE — `MRN#12345678` in placeholder text |

**Real violations: 6** (all in finops/page.tsx, used for Recharts SVG fills/strokes)

### bg-black/
**Result: PASS — 0 instances**

### border-white/
**Result: PASS — 0 instances**

### bg-white/\[
**Result: FAIL — 30 instances across 7 files**

| File | Count |
|------|-------|
| `src/app/alerts/page.tsx` | 7 |
| `src/app/routing/page.tsx` | 7 |
| `src/app/rules/page.tsx` | 5 |
| `src/app/health/page.tsx` | 4 |
| `src/app/observatory/page.tsx` | 4 |
| `src/app/tools/page.tsx` | 2 |
| `src/app/phi/page.tsx` | 1 |
| **Total** | **30** |

All instances use low-opacity white overlays (`bg-white/[0.02]` through `bg-white/[0.10]`) for subtle hover/active states on dark backgrounds. These should ideally be replaced with semantic tokens (e.g., `bg-surface-hover`, `bg-muted/5`).

---

## 2. Build Check
**Result: PASS**

`npx next build` completed successfully. All 15 routes generated as static content.
One non-blocking CSS warning: `@import` rule ordering (cosmetic, not a token issue).

---

## 3. TypeScript Check
**Result: PASS**

`npx tsc --noEmit` completed with exit code 0, zero errors.

---

## Summary

| Check | Result |
|-------|--------|
| zinc-\d scale | PASS (0) |
| Semantic color scales | PASS (0) |
| Hardcoded hex | FAIL (6 in finops chart code) |
| bg-black/ | PASS (0) |
| border-white/ | PASS (0) |
| bg-white/\[ | FAIL (30 across 7 files) |
| Next.js build | PASS |
| TypeScript | PASS |

### Overall: FAIL — 36 remaining violations

**Priority items:**
1. **finops/page.tsx** — 6 hardcoded hex colors for Recharts. Should use CSS variables or a chart color token array.
2. **bg-white/[0.0x]** pattern (30 instances, 7 files) — Low-opacity white overlays used as subtle surface tints. Should be replaced with semantic tokens like `bg-surface-hover` or similar.

The build and type system are clean. The remaining violations are visual/token consistency issues, not functional breakages.
