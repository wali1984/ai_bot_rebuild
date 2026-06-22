# Route Inventory After Current Redesign Pass

Generated: 2026-06-13

Source files inspected:
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/productNavigation.ts`
- `v2/frontend/src/components/layout/AdminShell.tsx`
- `v2/frontend/src/components/layout/Nav.tsx`
- `v2/frontend/src/components/layout/PublicShell.tsx`

## Canonical Public Routes

| Route | Classification | Status | Notes |
|---|---|---|---|
| `/` | REDIRECT | IN PROGRESS | Redirects to `/landing`; route-contract and overflow coverage are authored, but current validation rerun is pending. |
| `/landing` | PUBLIC | IN PROGRESS | Canonical landing. Paper/read-only stance visible. |
| `/status` | PUBLIC | IN PROGRESS | Public-safe status exists; production monitoring/smoke and current validation remain pending. |
| `/status-simple` | PUBLIC | IN PROGRESS | Public-safe simple status route is unshadowed and source-path hardened; screenshot/overflow and public status validation rerun pending. |
| `/login` | PUBLIC | IN PROGRESS | Backend auth surface and professional login exist; production hardening and current validation remain pending. |

## Canonical Trader Routes

| Route | Classification | Status | Notes |
|---|---|---|---|
| `/dashboard` | TRADER | IN PROGRESS | Trader dashboard rebuilt; screenshots/copy QA pending. |
| `/markets` | TRADER | IN PROGRESS | Screener upgraded; screenshot/overflow QA pending. |
| `/markets/symbols` | TRADER | IN PROGRESS | Redirects to canonical `/markets`; validation rerun pending. |
| `/market/:symbol?` | TRADER | IN PROGRESS | Public/trader read-only redesign exists; production stream and derivatives blockers remain. |
| `/trade` | TRADER | IN PROGRESS | Paper/read-only terminal exists; realtime validation and verified production paper services remain pending. |
| `/trade/paper` | TRADER | IN PROGRESS | Redirects to canonical `/trade`; validation rerun pending. |
| `/derivatives` | TRADER | IN PROGRESS | Cleaned read-only snapshot; dedicated derivatives analytics still partial. |
| `/signals` | TRADER | IN PROGRESS | Cleaned trader-safe signal evidence; durable signal stream/evidence remain pending. |
| `/ai-predictions` | TRADER | IN PROGRESS | Cleaned trader-safe forecast evidence; durable prediction APIs remain pending. |
| `/ai-predictions/model-state` | TRADER | IN PROGRESS | Redirects to canonical `/ai-predictions`; validation rerun pending. |
| `/portfolio` | TRADER | IN PROGRESS | Cleaned scoped paper portfolio summary; durable repositories remain pending. |
| `/portfolio/executions` | TRADER | IN PROGRESS | Cleaned typed paper activity view; durable repositories remain pending. |
| `/portfolio/history` | TRADER | IN PROGRESS | Cleaned typed paper history view; durable repositories remain pending. |
| `/backtests` | TRADER | IN PROGRESS | Cleaned read-only backtest readiness summary; typed backtest API remains pending. |
| `/backtests/replay` | TRADER | IN PROGRESS | Redirects to canonical `/backtests`; validation rerun pending. |
| `/research` | TRADER | IN PROGRESS | Cleaned read-only market intelligence summary; typed research API remains pending. |
| `/research/technical-analysis` | TRADER | IN PROGRESS | Redirects to canonical `/research`; validation rerun pending. |
| `/alerts` | TRADER | IN PROGRESS | Cleaned professional unavailable state and read-only `/api/v2/alerts` contract; CRUD/delivery/audit remain pending. |

## Canonical System/Admin Routes

| Route | Classification | Status | Notes |
|---|---|---|---|
| `/system` | ADMIN | IN PROGRESS | System overview. |
| `/system/control-center` | ADMIN | IN PROGRESS | Internal control center. |
| `/system/health` | ADMIN | IN PROGRESS | System health. |
| `/system/ingestors` | ADMIN | IN PROGRESS | Read/write controls need confirmation/reason/audit hardening. |
| `/system/trainer` | ADMIN | IN PROGRESS | Trainer admin. |
| `/system/orchestrator` | ADMIN | IN PROGRESS | Orchestrator admin. |
| `/system/risk-controllers` | ADMIN | IN PROGRESS | Risk controls; no live behavior changed. |
| `/system/strategy-controls` | ADMIN | IN PROGRESS | Strategy controls; no strategy logic changed. |
| `/system/execution` | ADMIN | IN PROGRESS | Execution admin; live remains blocked. |
| `/system/exchanges` | ADMIN | IN PROGRESS | Exchange manager. |
| `/system/config` | ADMIN | IN PROGRESS | Config admin. |
| `/system/logs` | ADMIN | IN PROGRESS | Internal logs. |
| `/system/audit-ledger` | SUPERADMIN | IN PROGRESS | Audit/evidence. |
| `/system/scripts` | SUPERADMIN | IN PROGRESS | Developer scripts. |
| `/system/build-validation` | SUPERADMIN | IN PROGRESS | Build validation. |
| `/system/coverage` | SUPERADMIN | IN PROGRESS | Coverage. |
| `/system/migrations` | SUPERADMIN | IN PROGRESS | Migrations. |
| `/system/users` | ADMIN | BLOCKED | Real user management API missing. |
| `/system/ai-tools` | SUPERADMIN | IN PROGRESS | Internal AI tools only. |
| `/system/readiness` | ADMIN | BLOCKED | Live readiness must remain blocked until auth/RBAC/audit gates pass. |
| `/system/readiness/mobile` | ADMIN | IN PROGRESS | Mobile readiness. |
| `/system/reports` | ADMIN | IN PROGRESS | Reports. |
| `/system/position-quarantine` | ADMIN | IN PROGRESS | Quarantine admin. |
| `/system/evidence` | SUPERADMIN | IN PROGRESS | Internal evidence. |
| `/system/executive-summary` | ADMIN | IN PROGRESS | Executive summary. |
| `/system/build-code-review` | SUPERADMIN | IN PROGRESS | Internal build/code review. |

## Redirect Map

| Legacy route | Canonical route |
|---|---|
| `/admin` | `/system` |
| `/admin/mission-control` | `/dashboard` |
| `/admin/war-room` | `/system/control-center` |
| `/admin/permanent-migration` | `/system/migrations` |
| `/admin/monitor-center` | `/system/health` |
| `/admin/coverage-system-atlas` | `/system/coverage` |
| `/admin/script-registry` | `/system/scripts` |
| `/admin/trainer-prediction-monitor` | `/ai-predictions` |
| `/admin/signal-explainability` | `/signals` |
| `/admin/symbols` | `/markets` |
| `/markets/symbols` | `/markets` |
| `/admin/market-intelligence` | `/research` |
| `/research/technical-analysis` | `/research` |
| `/admin/ai-brain` | `/ai-predictions` |
| `/ai-predictions/model-state` | `/ai-predictions` |
| `/admin/signals` | `/signals` |
| `/admin/executions` | `/portfolio/executions` |
| `/admin/positions` | `/portfolio` |
| `/admin/risk-control` | `/system/risk-controllers` |
| `/admin/exchange-manager` | `/system/exchanges` |
| `/admin/external-manual-position-quarantine` | `/system/position-quarantine` |
| `/admin/config-admin` | `/system/config` |
| `/admin/config` | `/system/config` |
| `/admin/strategy-admin` | `/system/strategy-controls` |
| `/admin/ingestors` | `/system/ingestors` |
| `/admin/technical-analysis` | `/research` |
| `/admin/liquidation-bridge` | `/derivatives` |
| `/admin/strategy-backtesting` | `/backtests` |
| `/admin/logs-errors` | `/system/logs` |
| `/admin/trainer-admin` | `/system/trainer` |
| `/admin/orchestrator-admin` | `/system/orchestrator` |
| `/admin/execution-admin` | `/system/execution` |
| `/admin/paper-trading` | `/trade` |
| `/trade/paper` | `/trade` |
| `/admin/replay` | `/backtests` |
| `/backtests/replay` | `/backtests` |
| `/admin/audit-ledger` | `/system/audit-ledger` |
| `/admin/system-health` | `/system` |
| `/admin/live-readiness` | `/system/readiness` |
| `/admin/claude-admin-ai` | `/system/ai-tools` |
| `/admin/ollama-local-assistant` | `/system/ai-tools` |
| `/admin/codex-review-center` | `/system/build-code-review` |
| `/admin/report-center` | `/system/reports` |
| `/admin/executive-status` | `/system/executive-summary` |
| `/admin/build-validation-status` | `/system/build-validation` |
| `/admin/operator-proof-dashboard` | `/system/evidence` |
| `/admin/mobile-iphone-readiness` | `/system/readiness/mobile` |
| `/trader` | `/trade` |
| `/history` | `/portfolio/history` |
| `/landing-legacy` | `/landing` |

Note: `/status-simple` is no longer a legacy redirect. It is tracked as a public route above and remains `IN PROGRESS` pending public status, screenshot/overflow, and docs-consistency validation.
