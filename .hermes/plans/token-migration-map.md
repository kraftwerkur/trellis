# Token Migration Map

## Zinc → Semantic Tokens

| Raw Class | Semantic Replacement | Rationale |
|-----------|---------------------|-----------|
| `text-zinc-500` | `text-muted-foreground` | Subdued/secondary text |
| `text-zinc-600` | `text-muted-foreground` | Subdued text (dark variant) |
| `text-zinc-400` | `text-muted-foreground` | Secondary text |
| `text-zinc-300` | `text-foreground/80` | Near-primary text |
| `text-zinc-200` | `text-foreground` | Primary text on dark bg |
| `text-zinc-100` | `text-foreground` | Bright text |
| `text-zinc-700` | `text-muted-foreground` | Very subdued text |
| `bg-zinc-800/50` | `bg-muted/50` | Muted background |
| `bg-zinc-800` | `bg-muted` | Muted background |
| `bg-zinc-900` | `bg-background` | Deep background |
| `bg-zinc-900/50` | `bg-background/50` | Semi-transparent background |
| `bg-zinc-600` | `bg-secondary` | Secondary/hover background |
| `bg-zinc-500` | `bg-secondary` | Secondary background |
| `bg-zinc-500/10` | `bg-secondary/10` | Subtle highlight |
| `border-zinc-700/30` | `border-border` | Standard border |
| `border-zinc-500/20` | `border-border` | Subtle border |
| `placeholder-zinc-600` | `placeholder-muted-foreground` | Input placeholder |

## Status Colors → Status Tokens

| Raw Class Pattern | Semantic Replacement | Status |
|-------------------|---------------------|--------|
| `text-emerald-400`, `text-emerald-500` | `text-status-healthy` | Healthy/success |
| `bg-emerald-500/10`, `bg-emerald-400/10` | `bg-status-healthy/10` | Healthy bg |
| `bg-emerald-500/20`, `bg-emerald-400/20` | `bg-status-healthy/20` | Healthy bg |
| `bg-emerald-500`, `bg-emerald-400` | `bg-status-healthy` | Healthy solid |
| `border-emerald-500/20`, `border-emerald-400/20` | `border-status-healthy/20` | Healthy border |
| `text-red-400`, `text-red-500` | `text-destructive` | Critical/error |
| `bg-red-500/10`, `bg-red-400/10` | `bg-destructive/10` | Critical bg |
| `bg-red-500/20`, `bg-red-400/20` | `bg-destructive/20` | Critical bg |
| `bg-red-400`, `bg-red-500` | `bg-destructive` | Critical solid |
| `border-red-500/20`, `border-red-400/20` | `border-destructive/20` | Critical border |
| `text-amber-400`, `text-amber-500` | `text-status-warning` | Warning |
| `bg-amber-500/10`, `bg-amber-400/10` | `bg-status-warning/10` | Warning bg |
| `bg-amber-500/20`, `bg-amber-400/20` | `bg-status-warning/20` | Warning bg |
| `bg-amber-400` | `bg-status-warning` | Warning solid |
| `border-amber-500/20`, `border-amber-400/20` | `border-status-warning/20` | Warning border |
| `text-cyan-400`, `text-cyan-500` | `text-primary` | Primary/info |
| `bg-cyan-500/10`, `bg-cyan-400/10` | `bg-primary/10` | Primary bg |
| `bg-cyan-500/20` | `bg-primary/20` | Primary bg |
| `bg-cyan-500/30` | `bg-primary/30` | Primary bg |
| `bg-cyan-500`, `bg-cyan-400` | `bg-primary` | Primary solid |
| `bg-cyan-600` | `bg-primary` | Primary solid |
| `bg-cyan-500/60` | `bg-primary/60` | Primary bg |
| `border-cyan-500/50` | `border-primary/50` | Primary border |
| `border-cyan-500/40` | `border-primary/40` | Primary border |
| `border-cyan-500/30` | `border-primary/30` | Primary border |
| `border-cyan-500/20` | `border-primary/20` | Primary border |
| `border-cyan-400` | `border-primary` | Primary border |
| `ring-cyan-500/20` | `ring-primary/20` | Primary ring |
| `text-cyan-400/70` | `text-primary/70` | Primary text |
| `text-violet-400`, `text-violet-500` | `text-chart-4` | Chart purple |
| `bg-violet-500/10` | `bg-chart-4/10` | Chart bg |

## Border/Background Fixes

| Raw Class | Replacement |
|-----------|-------------|
| `border-white/[0.06]` | `border-border` |
| `border-white/[0.08]` | `border-border` |
| `border-white/[0.04]` | `border-border/60` |
| `border-white/[0.15]` | `border-border` |
| `border-white/20` | `border-border` |
| `bg-black/60` | `bg-background/80` |
| `bg-black/40` | `bg-background/60` |
| `bg-black/30` | `bg-background/50` |

## Hex Values in Recharts

| Hex | Semantic CSS Variable | Context |
|-----|----------------------|---------|
| `#0a0a0f` | `var(--color-card)` | Tooltip backgrounds |
| `#52525b` | `var(--color-muted-foreground)` | Chart tick fills |
| `#71717a` | `var(--color-status-unknown)` | Fallback/unknown status |
| `#06b6d4` | `var(--color-primary)` | Cyan/primary in charts |
| `#10b981` | `var(--color-status-healthy)` | Green in charts |
| `#f59e0b` | `var(--color-status-warning)` | Amber in charts |
| `#ef4444` | `var(--color-destructive)` | Red in charts |
| `#8b5cf6` | `var(--color-chart-4)` | Purple in charts |
| `#ec4899` | `var(--color-chart-5)` or keep | Pink accent |
| `#a1a1aa` | `var(--color-muted-foreground)` | Gray text/labels |
| `#22d3ee` | `var(--color-primary)` | Cyan variant |
| `#34d399` | `var(--color-status-healthy)` | Green variant |
| `#f87171` | `var(--color-destructive)` | Red variant |
| `#fbbf24` | `var(--color-status-warning)` | Amber variant |
| `#c084fc` | `var(--color-chart-4)` | Purple variant |
| `#60a5fa` | `var(--color-status-info)` | Blue info |
| `#3b82f6` | `var(--color-status-info)` | Blue |
| `#e4e4e7` | `var(--color-foreground)` | Light text |
| `#f97316` | `var(--color-status-warning)` | Orange |
| `#123456` | REMOVE or replace with token | Likely test/placeholder |

## IMPORTANT RULES

1. Tailwind v4 with `@theme` block — tokens are used as `text-primary`, `bg-muted`, `border-border` etc. (no `hsl(var(...))` wrapper needed)
2. For opacity variants: `text-primary/70`, `bg-muted/50` etc.
3. Recharts `fill`/`stroke` props need actual CSS var references: `var(--color-primary)`
4. Some hex values appear in Recharts color arrays — replace with CSS var references
5. Don't change structural classes (flex, grid, p-*, m-*, rounded-*, etc.)
6. Don't change event-badge classes or other CSS utility classes defined in globals.css
7. `text-foreground/80` is valid Tailwind v4 for 80% opacity foreground
