# Dashboard Changelog

## 2026-03-04 — Polish Pass

### Added
- **System Health Summary Card** on Command Center page — shows total agents, active agents, events in last hour, rule match rate, and PHI detections today in a single glanceable card with gradient border accent
- **ErrorBoundary** component (`components/error-boundary.tsx`) — wraps all page content with a retry button; prevents one page crash from taking down the whole app
- Missing **PAGE_TITLES** entries for PHI Shield, FinOps, and Docs pages — header now shows correct title and description on all routes

### Fixed
- Command Center header previously showed "Overview" — now correctly labeled "Command Center"

### Reviewed (no issues found)
- All imports resolve correctly across all 8 pages
- Dark theme styling is consistent (card-dark, zinc palette, font-data mono) on every page
- Loading skeletons present on Agents, Audit, Rules, Gateway pages
- Mock/fallback data present on Command Center, FinOps, PHI Shield pages for demo mode
- All pages build without errors or warnings
