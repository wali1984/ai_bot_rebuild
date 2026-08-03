# V2 Route Inventory Complete

Date: 2026-06-15
Status vocabulary: BLOCKED means not eligible for pass. IN_PROGRESS means route exists but fails at least one data/design/test gate. REDIRECT means canonical redirect required. REMOVE means should not remain visible.

## Public routes

| Route | Page/component | Surface | Visual status | Data status | Auth status | Realtime status | Current tests | Missing data/controls | Forbidden copy risk | Screenshot status | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/` | public landing / redirect shell | PUBLIC | IN_PROGRESS | PARTIAL market fallback; signals preview not fully verified | Public | PARTIAL | public landing and nav tests exist | verified live market pulse, signal preview source metadata | admin/operator CTA risk must stay absent | partial overflow only | BLOCKED |
| `/landing` | mounted landing alias | PUBLIC/REDIRECT | IN_PROGRESS | PARTIAL | Public | PARTIAL | route cleanliness | canonical redirect decision | legacy alias | partial | REDIRECT |
| `/login` | login page | PUBLIC | IN_PROGRESS | N/A | Public | N/A | auth_rbac_redesign, failing in full suite due browser env | secure production auth backend audit, no role selector | local/session-role copy risk | partial | BLOCKED |
| `/status` | public status | PUBLIC | IN_PROGRESS | PARTIAL | Public | PARTIAL | public_status_redesign, focused status tests exist | API/data-health backend contract | internal status leakage must remain absent | partial | BLOCKED |
| `/status-simple` | legacy status | PUBLIC/REDIRECT | IN_PROGRESS | PARTIAL | Public | PARTIAL | public_status_redesign | canonical route migration | legacy status copy | partial | REDIRECT |
| `/markets` | markets screener | PUBLIC/TRADER | IN_PROGRESS | PARTIAL read-only market fallback; derivatives columns incomplete | Public/trader | PARTIAL | trader_first, nav cleanliness | predicted funding, OI change windows, liquidations, market cap, trend, AI columns | source pending/unavailable risk | partial | BLOCKED |
| `/market/:symbol` | market detail | PUBLIC/TRADER | IN_PROGRESS | PARTIAL | Public/trader | PARTIAL | market_detail_redesign, full suite blocked | complete source metadata for every chart/panel, AI/signal source | raw JSON/backend enum risk | partial | BLOCKED |
| `/signals/public` | public signal preview | PUBLIC | NOT VERIFIED | UNKNOWN | Public | UNKNOWN | not isolated | intentional public-safe signal preview contract | trader/account leakage | none | BLOCKED |

## Trader routes

| Route | Page/component | Surface | Visual status | Data status | Auth status | Realtime status | Current tests | Missing data/controls | Forbidden copy risk | Screenshot status | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/dashboard` | mission-control/trader dashboard | TRADER | IN_PROGRESS | PARTIAL | Trader context optional/read-only | PARTIAL | trader nav cleanliness | paper equity, PnL, current signal, market regime must be valid or gated | mission-control/operator wording risk | partial | BLOCKED |
| `/trade` | trade terminal | TRADER | IN_PROGRESS | PARTIAL market; account/execution fail-closed | Trader | PARTIAL | trade terminal focused tests exist | verified paper service before paper submit, full execution source metadata | live submit must remain absent | partial | BLOCKED |
| `/trade/paper` | legacy paper route | REDIRECT | N/A | N/A | Trader | N/A | route cleanliness | canonical redirect | legacy copy | N/A | REDIRECT |
| `/derivatives` | liquidation/derivatives bridge | TRADER | IN_PROGRESS | PARTIAL funding/OI fallback; liquidation levels require backend | Trader/public read-only | PARTIAL | selector tests | liquidation heatmap/map, exchange comparison, accumulated funding, OI by exchange | raw admin source risk reduced | partial | BLOCKED |
| `/signals` | signal evidence | TRADER | IN_PROGRESS | PARTIAL | Trader | PARTIAL | nav cleanliness, selector controls | pending/expired/rejected/executed signals, risk/reward, stop/invalidation, stream | model/debug wording risk | partial | BLOCKED |
| `/ai-predictions` | AI predictions/model-state | TRADER | IN_PROGRESS | PARTIAL | Trader | PARTIAL | nav cleanliness | forecast bands, realized vs predicted, calibration, feature importance, trainer status | AI brain/dev wording risk | partial | BLOCKED |
| `/ai-predictions/model-state` | legacy model state | REDIRECT | N/A | N/A | Trader | N/A | route cleanliness | canonical redirect | legacy internal copy | N/A | REDIRECT |
| `/portfolio` | portfolio summary | TRADER | IN_PROGRESS | MISSING/PARTIAL unless authenticated paper repo exists | Trader | MISSING/PARTIAL | nav cleanliness | paper balance/equity/PnL/drawdown/exposure source | unscoped fallback equity risk | partial | BLOCKED |
| `/portfolio/executions` | executions | TRADER | IN_PROGRESS | MISSING/PARTIAL | Trader | MISSING/PARTIAL | nav cleanliness | orders/fills/rejects/slippage/fees/audit | operator ledger wording risk | partial | BLOCKED |
| `/portfolio/history` | history | TRADER | IN_PROGRESS | MISSING/PARTIAL | Trader | MISSING/PARTIAL | nav cleanliness | trade journal/performance/evidence source | raw ledger risk | partial | BLOCKED |
| `/backtests` | strategy backtesting | TRADER | IN_PROGRESS | SNAPSHOT/PARTIAL | Trader | SNAPSHOT/PARTIAL | route cleanliness | equity curve, drawdown, win rate, benchmark, overlays source | admin replay wording risk | partial | BLOCKED |
| `/backtests/replay` | replay | TRADER | IN_PROGRESS | SNAPSHOT/PARTIAL | Trader | SNAPSHOT/PARTIAL | route cleanliness | replay timeline, risk/execution simulation source | admin replay wording risk | partial | BLOCKED |
| `/research` | research | TRADER | IN_PROGRESS | PARTIAL | Trader | PARTIAL | nav cleanliness | market regime, volatility, derivatives context, AI summary source | ingestor/admin panels must stay absent | partial | BLOCKED |
| `/research/technical-analysis` | TA alias/page | TRADER/REDIRECT | IN_PROGRESS | PARTIAL | Trader | PARTIAL | route cleanliness | support/resistance/indicator source | legacy technical analysis alias | partial | REDIRECT |
| `/alerts` | alerts | TRADER | IN_PROGRESS | PARTIAL/MISSING actions | Trader | PARTIAL | nav cleanliness | create/update/delete backend audit, notification history | payload telemetry risk | partial | BLOCKED |
| `/account-settings` | account settings | TRADER | IN_PROGRESS | PARTIAL | Trader | N/A | nav cleanliness | production exchange linking approval, credential vault status | raw IDs/secrets risk tested | partial | BLOCKED |
| `/chart/:symbol` | pro chart | TRADER | IN_PROGRESS | PARTIAL market fallback | Trader/public | PARTIAL | pro_chart tests | full source metadata and stale handling | raw enum risk | partial | BLOCKED |
| `/markets/symbols` | symbol universe | TRADER/REDIRECT | IN_PROGRESS | SNAPSHOT/PARTIAL | Trader | SNAPSHOT/PARTIAL | symbols route contract | canonical screener integration | admin source copy risk | partial | REDIRECT |

## Admin/system routes currently observed

Target final canonical route is `/admin/*`; existing `/system/*` routes must be redirected/protected or removed from nav.

| Route | Target surface | Current status | Required action |
| --- | --- | --- | --- |
| `/system` | ADMIN | IN_PROGRESS | migrate/canonicalize to `/admin`; backend-confirmed admin only |
| `/system/control-center` | ADMIN | IN_PROGRESS | migrate to `/admin/system`; actionable incidents only |
| `/system/ingestors` | ADMIN | IN_PROGRESS | migrate to `/admin/ingestors`; add heartbeat/lag/error/remediation |
| `/system/trainer` | ADMIN | IN_PROGRESS | migrate to `/admin/trainer`; no raw trainer dumps |
| `/system/orchestrator` | ADMIN | IN_PROGRESS | migrate to `/admin/orchestrator` |
| `/system/risk-controllers` | ADMIN | IN_PROGRESS | migrate to `/admin/risk`; controls backend-authorized/audited |
| `/system/strategy-controls` | ADMIN | IN_PROGRESS | protect or remove if not approved |
| `/system/execution` | ADMIN | IN_PROGRESS | migrate to `/admin/execution`; no live mutation |
| `/system/exchanges` | ADMIN | IN_PROGRESS | migrate to `/admin/exchanges`; masked credentials only |
| `/system/config` | ADMIN | IN_PROGRESS | migrate to `/admin/config`; controls confirmation-required |
| `/system/logs` | ADMIN | IN_PROGRESS | migrate to `/admin/logs`; structured logs and no secrets |
| `/system/users` | ADMIN | IN_PROGRESS | migrate to `/admin/users`; RBAC required |
| `/system/readiness` | ADMIN/SUPERADMIN | IN_PROGRESS | migrate to `/admin/readiness`; final live approval disabled |
| `/system/reports` | ADMIN | IN_PROGRESS | migrate to `/admin/reports` |
| `/system/audit-ledger` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/audit`; immutable audit view |
| `/system/scripts` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/scripts`; hidden from admins/traders/public |
| `/system/build-validation` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/build-validation` |
| `/system/coverage` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/coverage` |
| `/system/migrations` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/migrations` |
| `/system/ai-tools` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/ai-tools` |
| `/system/position-quarantine` | SUPERADMIN | IN_PROGRESS | migrate to admin evidence/safety route |
| `/system/evidence` | SUPERADMIN | IN_PROGRESS | migrate to `/admin/evidence` |

## Canonical admin routes required but not yet proven

`/admin`, `/admin/system`, `/admin/ingestors`, `/admin/trainer`, `/admin/orchestrator`, `/admin/risk`, `/admin/traders`, `/admin/execution`, `/admin/exchanges`, `/admin/config`, `/admin/readiness`, `/admin/users`, `/admin/logs`, `/admin/reports`, `/admin/audit`, `/admin/evidence`, `/admin/scripts`, `/admin/build-validation`, `/admin/coverage`, `/admin/migrations`, `/admin/codex`, `/admin/ai-tools`.

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

- Data-contract primitives are EXISTS/PARTIAL, not MISSING: `ValidatedDataEnvelope`, `useRealtimeResource`, `useDataFreshness`, `DataQualityBadge`, `FreshnessBadge`, `SourceBadge`, `EvidenceDrawer`, `RealtimeStatusBar`, `ProTable`, `MetricCard`, and `KPIGrid` exist in `frontend/src`.
- Adoption is PARTIAL. Any public/trader page or visible component still importing `usePayloadFile`, `operatorTruthData`, raw `/operator_runtime/*` paths, raw payload filenames, or legacy cockpit/operator surfaces remains DATA-BLOCKED until rewired to `/api/v2/*` envelopes/realtime streams or gated behind admin incident views.
- Backend collection currently succeeds: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/pytest v2/backend/tests/ --collect-only -q` collected `4093` tests with no collection/import errors.
- Local viewing is restored with Vite on `5173`, Cloudflare serving the Vite shell, and FastAPI on `8000` using detached 4-worker Uvicorn. This is local smoke evidence only, not launch readiness.
- `/` redirects to `/landing`; `/market` redirects to `/markets`; `/dashboard` redirects to `/trade`; unauthenticated `/trade` fails closed to `/login?returnTo=%2Ftrade`.
- Full backend pytest, full Chromium, route-by-route data coverage, and screenshot matrix are still UNPROVEN in the current pass.
- Do not mark Phase 14, Phase 15, `/trade`, `/market/:symbol`, realtime data, paper/read-only launch, admin security, or real live trading as PASS from this evidence.
- Real live trading remains BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- This is targeted evidence only. Full backend pytest, full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.
- Real live trading remains BLOCKED.

