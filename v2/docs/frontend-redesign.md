# Frontend Redesign Route Map

Generated: 2026-06-04

The V2 website is now organized as a trader-first crypto intelligence and execution platform. The primary product navigation is:

- Dashboard: `/dashboard`
- Markets: `/markets`
- Trade: `/trade`
- Derivatives: `/derivatives`
- Signals: `/signals`
- AI Predictions: `/ai-predictions`
- Portfolio: `/portfolio`
- Backtests: `/backtests`
- Research: `/research`
- Alerts: `/alerts`

Protected System routes are separated from the trader flow:

- Overview: `/system`
- Control Center: `/system/control-center`
- Ingestors: `/system/ingestors`
- Trainer: `/system/trainer`
- Orchestrator: `/system/orchestrator`
- Risk Controllers: `/system/risk-controllers`
- Strategy Controls: `/system/strategy-controls`
- Execution: `/system/execution`
- Exchanges: `/system/exchanges`
- Config: `/system/config`
- Logs: `/system/logs`
- Audit Ledger: `/system/audit-ledger`
- Scripts: `/system/scripts`
- Build Validation: `/system/build-validation`
- Coverage: `/system/coverage`
- Migrations: `/system/migrations`
- Users: `/system/users`
- AI Tools: `/system/ai-tools`
- Readiness: `/system/readiness`
- Reports: `/system/reports`
- Position Quarantine: `/system/position-quarantine`
- Evidence: `/system/evidence`

Legacy `/admin/*` routes redirect to the canonical product or System route and preserve query parameters such as `?role=admin`.

Inventory reconciliation:

- `frontend/src/pages` contains 51 page directories from the original inventory.
- The unlisted route is `admin-war-room`, implemented as `/admin/war-room` and now redirected to `/system/control-center`.
- Merged pages are intentionally not active routes: `config`, `signal-explainability`, `ollama-local-assistant`, and `public-landing` redirect or merge into canonical pages.

Safety state:

- Live/canary remain blocked.
- The active burn-in report shows after-cost expectancy below zero and `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`.
- No route introduced live enablement, order submission, order cancel/modify, leverage, margin, old Redis write, legacy restart, or Redis trim behavior.
