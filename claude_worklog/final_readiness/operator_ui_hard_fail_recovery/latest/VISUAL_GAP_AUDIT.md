VISUAL_GAP_AUDIT

Audit source:
- Active Vite route screenshots under `screenshots/`
- Claude Design handoff under `claude_worklog/frontend_design/handoffs/2026-05-11/`
- V2 React components under `v2/frontend/src/`

Route classifications after this pass:

| Route | Classification | Notes |
|---|---|---|
| `/admin/mission-control` | acceptable | Rebuilt first screen with truth deck, status rail, grouped nav, runtime matrix, critical system cards, TradingView/chart panel, compact signal stream, and explicit static/stale/missing labels. |
| `/admin/monitor-center` | acceptable | Adds route truth summary before monitor script table. Shows stale supervisor/trainer evidence state. |
| `/admin/trainer-prediction-monitor` | acceptable | Current trainer runtime evidence appears first; fixture decision drawers remain proof examples below. |
| `/admin/signal-explainability` | acceptable | No-guessing rule and route truth summary appear before proof drawers. |
| `/admin/risk-control` | acceptable | Route truth summary and fail-closed risk gates are visible. |
| `/admin/config-admin` | acceptable | Route truth summary and classified settings table are visible; dangerous changes remain approval-gated by shell metadata. |
| `/admin/build-validation-status` | acceptable | Route truth summary and payload freshness appear before proof details. |
| `/admin/claude-admin-ai` | acceptable | Non-live AI role and prohibited actions are explicit. |
| `/admin/mobile-iphone-readiness` | acceptable | Mobile future path and missing native bridge evidence are explicit. |
| `/admin/paper-trading` | acceptable | Placeholder shell replaced with current paper/shadow runtime status and non-live evidence warning. |
| `/admin/replay` | acceptable | Placeholder shell replaced with historical replay proof status; static fixture limitations are explicit. |
| `/admin/live-readiness` | acceptable | Placeholder shell replaced with live readiness hard-stop and current blockers. |
| `/admin/operator-proof-dashboard` | acceptable | Remains evidence/proof page by design, not the primary cockpit. |

Remaining runtime gaps visible in UI:
- Supervisor status is stale/conflicting.
- Trainer runtime evidence is missing.
- Signal lineage remains static proof fixture.
- Several public payloads remain stale.

These are runtime/readiness blockers, not hidden UI state.
