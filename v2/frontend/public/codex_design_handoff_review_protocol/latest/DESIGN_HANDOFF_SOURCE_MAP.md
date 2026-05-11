# Design Handoff Source Map

Latest design handoff observed:

- `claude_worklog/frontend_design/handoffs/2026-05-11/CLAUDE_CODE_PROMPT.md`
- `claude_worklog/frontend_design/handoffs/2026-05-11/README.md`
- `claude_worklog/frontend_design/handoffs/2026-05-11/_raw/HANDOFF_BUNDLE.md`
- Prototype references: `app.jsx`, `mission-control.jsx`, `pages-admin.jsx`, `pages-ai.jsx`, `pages-inspect.jsx`, `pages-operate.jsx`, `pages-system.jsx`, `primitives.jsx`, `risk-control.jsx`, `signal-explainability.jsx`, `tweaks-panel.jsx`, `data.jsx`, `module-placeholder.jsx`

Current V2 frontend review surface:

- `v2/frontend/package.json`
- `v2/frontend/index.html`
- `v2/frontend/src/main.tsx`
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/mission-control/index.tsx`
- `v2/frontend/src/pages/cockpitComponents.tsx`
- `v2/frontend/src/pages/cockpitData.ts`
- `v2/frontend/src/components/charts/TradingViewWidget.tsx`
- `v2/frontend/src/components/banners/LiveBlockBanner.tsx`
- `v2/frontend/src/components/banners/MissionControlReadinessBanner.tsx`
- `v2/frontend/src/components/layout/AdminShell.tsx`
- `v2/frontend/src/components/layout/Nav.tsx`
- `v2/frontend/src/components/layout/PageShell.tsx`

Final readiness surfaces to inspect:

- `claude_worklog/final_readiness/enterprise_ui_polish/latest/`
- `claude_worklog/final_readiness/codex_parallel_audit_plan/latest/`
- `claude_worklog/final_readiness/online_readiness_control_plane/latest/`
- `claude_worklog/final_readiness/realtime_legacy_monitoring_continuity/latest/`
- `claude_worklog/final_readiness/v2_data_plane_independence/latest/`

Review interpretation:

- Handoff JSX files are design references, not production source.
- `data.jsx` is mock/reference-only and cannot be displayed as live truth.
- `module-placeholder.jsx` is a design placeholder and must become either a real V2 route or an explicit evidence-gap route.
- `tweaks-panel.jsx` is design-tool-only and must not ship as an operator/admin control.
