# Phase 14A Test Contract

Generated: 2026-06-13

Scope: current intended AlphaForge frontend/backend test contract for Phase 14A full Chromium suite stabilization.

This is not a launch pass. Phase 13, Phase 14, Phase 15, `/trade`, `/market/:symbol`, paper/read-only launch, admin security, and real live trading remain not-PASS.

## Public And Trader Route Contract

| Route | Contract | Auth posture | Required visible safety/data posture |
|---|---|---|---|
| `/` | Canonical public landing should present AlphaForge brand, market intelligence value proposition, paper/read-only posture, market preview, signal preview where available, and CTAs to markets, signals, and login. | Public. | No admin/operator/developer wording; no fake live data; live trading disabled or paper/read-only state visible. |
| `/login` | Professional backend-auth login with email, password, password visibility, safe submit state, and read-only public navigation option. | Public. | No role selector, fake admin shortcut, local-role/session-role wording, or URL role escalation. |
| `/status` | Public-safe platform status: platform availability, API availability, data freshness, paper/read-only mode, live trading disabled, incidents/maintenance, updated timestamp. | Public. | No logs, stack traces, debug JSON, build internals, migration/script/coverage details, env vars, paths, API keys, or raw worker exceptions. |
| `/dashboard` | Trader dashboard with paper portfolio KPIs, chart panel, current AI signal, paper positions, market pulse, and compact status strip. | Backend-confirmed viewer/trader/admin fixture for tests; unauthenticated access may show login. | No mission-control/operator/proof/payload wording in main trader UI. Paper/read-only state visible. |
| `/markets` | Authenticated trader market screener with tabs, search, filters, favorites, professional columns, mobile cards, and honest missing-data states. | Backend-confirmed viewer/trader/admin fixture for tests. | Missing values show `Data source unavailable` or designed unavailable state, never raw `source pending`. |
| `/market/:symbol` | Public/trader read-only market detail with symbol header, chart, microstructure, derivatives, AI/signal, and evidence sections. | Public read-only. | Realtime depth/trades/derivatives gaps remain visible as missing/unavailable states. No raw JSON by default. |
| `/trade` | Paper/read-only terminal with symbol header, chart, order book, depth/tape, paper order ticket, bottom tabs, and trader-scoped local paper audit-event evidence. | Public paper/read-only or backend-confirmed trader fixture. | No live submit button. Authenticated local paper staging/cancel/fill is repository-only with no-auto-fill policy and local audit-event rows; production paper validation, durable audit policy, and persistence hardening remain blocked. |

## Admin Route Contract

Canonical admin routes require backend-confirmed `admin` or `superadmin` unless explicitly documented otherwise. Unauthenticated users must see login/access gate and no protected content. Viewer/trader users must not see admin content.

| Route | Contract |
|---|---|
| `/admin` | Admin dashboard or canonical admin entry protected by backend auth. |
| `/admin/system` | Protected system overview. |
| `/admin/ingestors` | Protected ingestor/system data controls. |
| `/admin/trainer` | Protected trainer system surface. |
| `/admin/orchestrator` | Protected orchestrator system surface. |
| `/admin/risk` | Protected risk/admin controls. |
| `/admin/traders` | Protected trader/account administration. |
| `/admin/execution` | Protected execution administration; no live mutation without superadmin/live-gate approval. |
| `/admin/exchanges` | Protected exchange configuration/readiness surface. |
| `/admin/config` | Protected configuration surface. |
| `/admin/readiness` | Protected readiness surface. |
| `/admin/users` | Protected user administration; admin/superadmin only. |
| `/admin/logs` | Protected logs; no public exposure. |
| `/admin/reports` | Protected reports. |

## Superadmin Route Contract

Superadmin routes require backend-confirmed `superadmin`. Admin, trader, viewer, and unauthenticated users must not see superadmin content.

| Route | Contract |
|---|---|
| `/admin/audit` | Superadmin audit/evidence route. |
| `/admin/evidence` | Superadmin evidence route. |
| `/admin/scripts` | Superadmin scripts route. |
| `/admin/build-validation` | Superadmin build-validation route. |
| `/admin/coverage` | Superadmin coverage route. |
| `/admin/migrations` | Superadmin migrations route. |
| `/admin/codex` | Superadmin AI tooling route; never public/trader. |
| `/admin/ai-tools` | Superadmin AI tooling route; never public/trader. |

## Legacy Route Behavior

| Legacy pattern | Required behavior |
|---|---|
| Old operator/system routes such as `/system/*` | Must redirect to canonical `/admin/*`, show protected access, or render only through backend-confirmed admin/superadmin auth. They must not appear in public/trader nav. |
| Old public landing duplicates such as `/landing` | May redirect to `/` or render equivalent public landing without internal wording. |
| `/trade/paper` | Must redirect to `/trade` or render the same safe paper terminal mode. |
| Mission-control/war-room/operator-proof routes | Must not appear in public/trader UI. If retained, they are protected admin/superadmin surfaces only. |
| `?role=admin`, `?role=superadmin`, sessionStorage/localStorage role override | Must not grant access. Tests must not rely on these paths for authorized access. |

## Safety Contract

| Safety invariant | Required behavior |
|---|---|
| Real live trading | Remains disabled and blocked. |
| Live-gate routes | Require backend-confirmed superadmin and existing live-gate conditions; no public/trader mutation path. |
| Live order submit/cancel/leverage/margin | No live submit, cancel, leverage, or margin mutation path may be added in Phase 14A. |
| Paper submit | Authenticated local paper staging/cancel/fill may write only to the trader-scoped paper repository and local paper audit-event log; no automatic fill, exchange transport, live cancel, leverage, or margin mutation may occur. |
| Missing/stale/fallback data | Must remain visible through designed source/freshness/stale/missing states. Static fallback must not be presented as live. |
| Safety tests | Must be preserved or strengthened. Obsolete wording may be updated, but live-disabled/default-deny coverage must not be removed. |

## Phase 14A Status Guardrails

| Item | Status rule |
|---|---|
| Phase 14 | May move above 50% only if full-suite failure count is materially reduced and documented. Full PASS requires full Chromium suite, typecheck/build/lint, and backend pytest passing. |
| Phase 13 | Remains IN PROGRESS unless every visible route is visually reviewed. |
| Phase 15 | Remains BLOCKED until production deploy/smoke/HTTPS/env verification passes. |
| `/trade` | Remains IN PROGRESS until realtime stream validation, local paper submit/cancel/fill production validation, durable trader repositories, durable audit policy, screenshots, and current tests are complete. |
| `/market/:symbol` | Remains IN PROGRESS until realtime depth/trades/derivatives are complete. |
| Real live trading | Remains BLOCKED. |

## Phase 14A Execution Update

Final verification on 2026-06-13:

- Full Chromium suite: `npx playwright test --project=chromium --reporter=list` passed, 196 tests.
- Backend integration tests passed, 13 tests.
- Frontend typecheck/build/lint passed.
- Superadmin-only smoke routes include `/system/readiness`, `/system/reports`, `/system/audit-ledger`, `/system/evidence`, `/system/scripts`, `/system/build-validation`, `/system/coverage`, `/system/migrations`, `/system/ai-tools`, and `/system/position-quarantine` because the current frontend route guard enforces those as superadmin surfaces.
- This does not mark launch, Phase 15, `/trade`, `/market/:symbol`, or real live trading as PASS.
