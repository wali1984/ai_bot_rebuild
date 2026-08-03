# V2 Route Migration Map

Date: 2026-06-15
Status: Initial migration map. Existing legacy routes must not leak operator/developer content to public/trader users.

## Public canonical routes

- `/`
- `/login`
- `/status`
- `/markets`
- `/market/:symbol`
- `/signals/public` only if intentionally public-safe

## Trader canonical routes

- `/dashboard`
- `/trade`
- `/markets`
- `/market/:symbol`
- `/derivatives`
- `/signals`
- `/ai-predictions`
- `/portfolio`
- `/portfolio/executions`
- `/portfolio/history`
- `/backtests`
- `/backtests/replay`
- `/research`
- `/research/technical-analysis`
- `/alerts`

## Admin canonical routes

- `/admin`
- `/admin/system`
- `/admin/ingestors`
- `/admin/trainer`
- `/admin/orchestrator`
- `/admin/risk`
- `/admin/traders`
- `/admin/execution`
- `/admin/exchanges`
- `/admin/config`
- `/admin/readiness`
- `/admin/users`
- `/admin/logs`
- `/admin/reports`

## Superadmin canonical routes

- `/admin/audit`
- `/admin/evidence`
- `/admin/scripts`
- `/admin/build-validation`
- `/admin/coverage`
- `/admin/migrations`
- `/admin/codex`
- `/admin/ai-tools`

## Existing legacy/admin route mapping

| Existing route | Target | Action |
| --- | --- | --- |
| `/landing` | `/` or mounted landing | redirect/canonicalize |
| `/trade/paper` | `/trade` | redirect |
| `/ai-predictions/model-state` | `/ai-predictions` | redirect |
| `/markets/symbols` | `/markets` | redirect or protected trader-safe symbol universe |
| `/chart/:symbol` | `/market/:symbol` or `/trade` chart module | keep if pro chart canonical is desired, otherwise redirect |
| `/research/technical-analysis` | `/research/technical-analysis` | keep trader-safe or redirect to `/research` tab |
| `/system` | `/admin/system` | migrate/protect |
| `/system/control-center` | `/admin/system` | migrate/protect |
| `/system/ingestors` | `/admin/ingestors` | migrate/protect |
| `/system/trainer` | `/admin/trainer` | migrate/protect |
| `/system/orchestrator` | `/admin/orchestrator` | migrate/protect |
| `/system/risk-controllers` | `/admin/risk` | migrate/protect |
| `/system/strategy-controls` | `/admin/risk` or remove | protect/remove pending approval |
| `/system/execution` | `/admin/execution` | migrate/protect |
| `/system/exchanges` | `/admin/exchanges` | migrate/protect |
| `/system/config` | `/admin/config` | migrate/protect |
| `/system/logs` | `/admin/logs` | migrate/protect |
| `/system/users` | `/admin/users` | migrate/protect |
| `/system/readiness` | `/admin/readiness` | migrate/protect |
| `/system/reports` | `/admin/reports` | migrate/protect |
| `/system/audit-ledger` | `/admin/audit` | superadmin only |
| `/system/evidence` | `/admin/evidence` | superadmin only |
| `/system/scripts` | `/admin/scripts` | superadmin only |
| `/system/build-validation` | `/admin/build-validation` | superadmin only |
| `/system/coverage` | `/admin/coverage` | superadmin only |
| `/system/migrations` | `/admin/migrations` | superadmin only |
| `/system/ai-tools` | `/admin/ai-tools` | superadmin only |
| `/system/position-quarantine` | `/admin/evidence` or `/admin/risk` | superadmin/admin safety surface |

## 2026-06-15 admin alias redirect remediation

Status: PARTIAL REMEDIATION, not launch-ready.

Router behavior changed from blanket filtering of all `/admin/*` legacy redirects to an explicit allowlist for obsolete aliases only. This preserves true admin control routes while redirecting legacy/admin diagnostic aliases to cleaned canonical pages.

Redirected aliases now validated:
- `/admin/ai-brain` -> `/admin/model-state`
- `/admin/symbols` -> `/markets`
- `/admin/signal-explainability` -> `/signals`
- `/admin/replay` -> `/backtests`
- `/admin/technical-analysis` -> `/research`

Protected admin routes preserved and validated:
- `/admin/risk-control`
- `/admin/config-admin`
- `/admin/strategy-admin`
- `/admin/execution-admin`
- `/admin/live-readiness`

Validation evidence:
- `npm run typecheck` passed from `v2/frontend`.
- Focused Playwright route/default-deny validation passed: 11/11 tests.

Remaining blockers:
- Full Chromium suite is still not green.
- Remaining route inventory and visual screenshot matrix must still be completed before launch readiness can advance.
- Real live trading remains blocked.

## 2026-06-15 admin evidence route repair

- Restored `/admin/monitor-center`, `/admin/exchange-manager`, `/admin/external-manual-position-quarantine`, and `/admin/operator-proof-dashboard` as admin-owned evidence routes instead of `/system/*` redirects.
- Added explicit admin compatibility routes for `/admin/trainer-prediction-monitor`, `/admin/signal-explainability`, and `/admin/symbols` so admin evidence pages render their real pages while trader/public canonical routes remain separate.
- Kept `/system/*` behind the admin gate and did not expose admin evidence routes to public/trader users.
- Validation: focused Chromium gate passed 4/4 with `enterprise_trading_cockpit`, `operator_proof_dashboard_historical_30d`, and `phase_13a_visual_gate` route module checks.
