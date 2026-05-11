# Visual Component Mapping

Source handoff: `claude_worklog/frontend_design/handoffs/2026-05-11/`

Current V2 route: `/admin/mission-control?role=admin`

Mapped visual patterns:

| Claude Design reference | V2 implementation |
|---|---|
| `mission-control.jsx` command hero | `MissionCommandHero` in `v2/frontend/src/pages/mission-control/index.tsx` |
| `mission-control.jsx` subsystem row | `SubsystemStrip` in `v2/frontend/src/pages/mission-control/index.tsx` |
| `mission-control.jsx` risk/gate panel | `RiskBoundaryPanel` in `v2/frontend/src/pages/mission-control/index.tsx` |
| design `Panel` / bracket primitives | shared `Panel` in `v2/frontend/src/pages/cockpitComponents.tsx` plus `panel`, `bracketed`, and `hatch` classes |
| design layout density | `mission-command-layout` and `mission-system-grid` in `v2/frontend/src/styles.css` |
| design chart area | existing `ChartPanel` with `TradingViewWidget` primary chart |

Rejected as source-of-truth:

- `data.jsx` mock telemetry and demo subsystem values.
- `window.AIBOT` globals from prototype files.
- Design-only placeholder module behavior.
- Prototype SVG chart as a primary chart.

Retained existing V2 surfaces:

- `MissionControlReadinessBanner`
- `LiveBlockBanner` from `AdminShell`
- `ChartPanel` / `TradingViewWidget`
- `DecisionDrawers`
- `MarketPulse`
- `MonitorTable`
- `ConfigTable`
- `ExchangeManager`
- Redis remediation panels
- system atlas and quarantine panels
- `AI BOT V2 Modern Dashboard Loaded` integration marker
