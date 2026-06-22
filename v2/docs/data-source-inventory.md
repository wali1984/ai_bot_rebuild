# Data Source Inventory

Generated: 2026-06-14

This summarizes the frontend data stance after the current redesign pass. Static payloads remain fallback sources and must show freshness, stale, or missing-source state.

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Landing/status | `/api/v2/status`, `/api/v2/signals`, plus safe degraded frontend fallback; `/api/v2/status` includes public-safe market stream freshness, stream-alert copy, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner evidence, and outbound alert webhook notifier/active-only alert delivery status; `/api/v2/market/overview` now prefers Binance public USD-M 24h inventory | production monitoring, incidents, production stream alerting/dashboard current validation | IN PROGRESS | Public landing/status are safe/read-only; landing no longer displays fallback account equity/PnL as public account data and no longer reads the paper runtime payload for public signal preview. Local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, and outbound alert webhook notifier/active-only alert delivery are partial evidence only. Production alerting/dashboard current validation, incident source, current validation rerun, and human visual review remain pending. |
| Dashboard | `/api/v2/market/overview`, ProChart typed candles/read-only public stream sources, trader-scoped account truth, trade terminal context, read-only prediction rows, and CoinAnk market aggregate fallback | `/api/v2/dashboard`, production `/api/v2/portfolio`, `/api/v2/signals`, trader-scoped positions repository, `/ws/market-data` | IN PROGRESS | Trader dashboard requires backend trader scope for account values, uses typed V2 market overview for current public market-universe freshness where available, uses ProChart instead of legacy chart JSON polling, no longer reads direct runtime truth, paper runtime, portfolio-state, or system-observability payload files for trader-facing status, and no longer renders unscoped fallback position rows as trader-specific rows. |
| Markets | `/api/v2/market/overview` with public USD-M 24h ticker rows, all-timeframe prediction, top10 dashboard, CoinAnk payloads | `/api/v2/market`, `/api/v2/derivatives`, stream updates | IN PROGRESS | The screener now prefers typed V2 market overview for the public symbol universe, source freshness, last price, 24h change, and turnover where current public ticker rows exist, and no longer reads paper runtime payloads for symbol or freshness fallback. Derivatives/prediction columns intentionally show `Data source unavailable` where durable sources are missing. |
| Market detail | safe `/api/v2/market/*` surfaces, `/api/v2/market/{symbol}/stream-status` with public-safe alert state, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner evidence, and outbound alert webhook notifier/active-only alert delivery status, `/api/v2/market/{symbol}/derivatives`, backend/browser-side read-only Binance public WebSocket display, direct read-only Binance public REST candle backfill for ProChart, and read-only API polling fallback now prefer Binance public USD-M ticker, premium index, open interest, funding/OI history rendered on market detail, long-short ratio, basis, closed klines, depth ladder, and recent trades with fallback files retained | production stream alerting/dashboard current validation, durable derivatives repositories, stream-backed freshness | IN PROGRESS | Public read-only market data is wired through request-time API calls, same-origin backend native stream with fallback, browser-side native fallback, direct public REST candle backfill for chart history, local persisted stream telemetry, local alert history, production stream alerting artifact metadata, production stream alerting smoke runner, and notifier status. ProChart tries the direct read-only Binance public stream before same-origin backend stream fallbacks, uses direct read-only Binance public REST candles only as current public market display data, normalizes second/millisecond event timestamps for freshness, rejects invalid native/API/fallback OHLC rows, withholds stale or static candle snapshots from the primary chart, maps funding/open-interest history into OI/funding overlays when the legacy overlay endpoint is unavailable, and rotates past silent/stalled read-only stream endpoints; production alerting/dashboard current validation, liquidation analytics, heatmaps, exchange comparison, durable derivative repositories, and validation remain pending. |
| Trade | safe `/api/v2/market/*`, `/api/v2/market/{symbol}/stream-status` with public-safe alert state, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner evidence, and outbound alert webhook notifier/active-only alert delivery status, backend/browser-side read-only Binance public WebSocket display, direct read-only Binance public REST candle backfill for ProChart and the terminal chart, read-only API polling fallback, `/api/v2/orders/preview`, trader-scoped portfolio/signals API surfaces plus candle polling and labeled fallback files | production stream alerting/dashboard current validation, production paper submit/cancel/fill validation, trader-scoped repositories | IN PROGRESS | Trader/account context is surfaced from backend auth when signed in, and frontend primary exchange-account selection now fails closed unless backend-confirmed scoped read-only metadata matches the active trader and paper account. Paper order staging now requires the preview scope to match the active trader and paper account. ProChart and the `/trade` chart reject invalid native/API/fallback OHLC rows, use direct read-only Binance public REST candles only as current public market display data when backend candles are absent/stale/static, withhold stale or static candle snapshots from the primary chart, map funding/open-interest history into OI/funding overlays where available, and rotate past silent/stalled read-only stream endpoints. Production stream alerting artifact metadata and production stream alerting smoke runner are partial evidence only. Unscoped account fallback data is withheld for signed-in traders, and safe portfolio, signal, and activity rows are defensively filtered by active trader plus paper-account scope. No live order route enabled; authenticated paper submit/cancel/fill is local repository-only and pending production validation. |
| Signals/AI | trader-safe signal state plus designed unavailable evidence states; legacy trainer/runtime panels removed from `/signals` and `/ai-predictions` | `/api/v2/signals`, `/api/v2/ai/predictions`, `/ws/signals` | IN PROGRESS | Visible trader routes now show signal/prediction evidence, but durable prediction APIs, target/stop/invalidation completeness, signal stream delivery, and model evidence remain pending. |
| Portfolio/executions | safe `/api/v2/portfolio`, `/api/v2/account/positions`, `/api/v2/execution/*` API surfaces plus backend trader context, local file-backed trader account repository, and explicit SQLAlchemy trader account repository adapter seam | production auth-scoped portfolio/execution database repositories | IN PROGRESS | Initial multi-trader ownership metadata, a read-only account-scope smoke runner, and protected scope-smoke artifact metadata exist for `wajidali1984`; public/trader account surfaces now either use scoped repository state with row-level filtering or fail closed/sign-in-required rather than showing unscoped or partially matched fallback as trader-specific. Local paper-account reuse across traders is rejected. Local manual paper fills can create trader-scoped execution, position, and audit-event rows with paper audit retention policy metadata and without exchange mutation in non-production, local repository plus local paper audit ledger writes fail closed in production, and an explicit SQLAlchemy trader account repository backend can be selected for paper/read-only account state. Production DB migrations/provisioning, production writer validation, audit validation, durable paper audit policy, and verified paper execution source are still pending. |
| Backtests/research | read-only professional missing-state summaries with API market/signal context where available | `/api/v2/backtests`, `/api/v2/research`, replay/equity-curve repositories | IN PROGRESS | `/backtests` and `/research` are cleaned trader surfaces; `/backtests/replay` and `/research/technical-analysis` redirect to canonical pages until durable APIs exist. |
| Alerts | professional unavailable public state plus authenticated local or SQLAlchemy trader-scoped paper alert CRUD through structured `/api/v2/alerts` API | production alert repositories, preferences, notifications, delivery, and durable audit logging | IN PROGRESS | Visible route no longer exposes payload telemetry or fake actions. The alerts API now supports authenticated local or SQLAlchemy trader-scoped paper alert CRUD with delivery disabled; production alert repository provisioning, notification delivery, and durable audit logging remain incomplete. |
| Auth/trader accounts | authenticated `/api/auth/*`, `/api/admin/users/{user_id}/activation`, `/api/admin/credential-status`, safe user payload, backend trader context, safe credential status resolver, secret-free session/auth-store/revocation-store security status, centralized backend-only environment/local vault-file credential binding, credential vault readiness metadata, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, safe secret-redaction smoke runner, local file-backed account repository, explicit SQLAlchemy auth-store, revocation-store, and trader account repository adapters | durable users/traders/accounts database with credential vault integration and durable session/revocation storage | IN PROGRESS | The default local/dev seed for `wajidali1984` stays inactive without an operator-provided password, while the current local workspace metadata is active, scoped to `trader-wajidali1984` / `paper-wajidali1984`, and tied only to read-only/live-disabled Binance metadata plus an empty scoped paper repository. the local auth-user store now rejects duplicate paper-account IDs and rejects production access unless the pytest-only override is active. SQLAlchemy auth-store, revocation-store, and trader account repository adapters can be selected explicitly with `ALPHAFORGE_AUTH_STORE_BACKEND=sqlalchemy`, `ALPHAFORGE_AUTH_DATABASE_URL`, `ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND=sqlalchemy`, `ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL`, `ALPHAFORGE_TRADER_ACCOUNT_REPOSITORY_BACKEND=sqlalchemy`, and `ALPHAFORGE_TRADER_ACCOUNT_DATABASE_URL`, but production migrations/provisioning, writer validation, retention/rotation policy, and smoke are still pending. Stored exchange-account metadata is normalized to the owning user `trader_id`, signed read-only account selection requires matching `trader_id` plus `paper_account_id`, and exchange metadata is forced read-only/live-disabled on admin create/update. Local paper-account IDs cannot be reused across traders through the admin user store or admin repository route. Trader-side account linking is metadata-only and now requires exact backend role `trader`; admins use separate admin-management workflows. Backend can report configured/pending/binding-required credential status, credential vault readiness posture, credential permission-probe artifact status, signed-read validation artifact status, secret-redaction smoke artifact status, session security posture, auth-store/revocation-store readiness posture, activate/reset users through an admin-protected route, resolve env or local vault-file credentials internally only for read-only/live-disabled/read-only-scoped account metadata, and generate a local secret-redaction smoke artifact without exposing keys, secrets, temporary passwords, or backend credential references to public/trader payloads, but no durable credential vault, production permission probe, production secret-redaction smoke execution, or signed account adapter validation is complete. |
| Admin/system | authenticated `/api/auth/*`, `/api/admin/users`, `/api/admin/credential-status` admin audit readiness, explicit SQLAlchemy admin-audit adapter, and protected local `/api/admin/trader-accounts` paper repository updates with integrity/readiness metadata plus existing runtime/system payloads | durable authenticated `/api/admin/*` with durable audit trail | IN PROGRESS | Backend auth/RBAC surface exists; admin user create/update/delete and activation/reset now have secret-free audit events before mutation as partial evidence through local JSONL in dev/test or SQLAlchemy when explicitly configured, production create/update/delete requires a mutation reason, production local admin audit storage fails closed unless the pytest-only override is active, production admin audit writes fail closed when retention-day metadata is missing, `/api/admin/credential-status` exposes secret-free admin audit-store readiness including retention-policy metadata, admin paper account balance refreshes preserve omitted trader collections, SQLAlchemy auth/revocation/audit-store selection exists, and local auth/trader repository readiness metadata is partial evidence only. Production DB migrations/provisioning/session hardening, production trader repositories, durable audit retention enforcement/policy, invitation/deactivation workflow hardening, and full admin API coverage remain incomplete. |


Multi-trader note: local paper repository operations and fallback payload matching now require strict `trader_id` plus `paper_account_id` matching when both are present. Local manual paper fills are scoped the same way and remain paper-only in non-production, local paper audit ledger rows expose paper audit retention policy metadata, and local repository plus local paper audit ledger writes fail closed in production. Local repository readiness metadata, the account-scope smoke runner, and account-scope smoke artifact metadata are partial evidence only. Production persistence and full isolation validation remain pending.

Realtime/trader-source note: read-only market stream stale transitions and partial stale backend snapshots now mark cached ticker, depth, trades, and candle envelopes stale so ProChart, `/trade`, and market detail surfaces cannot keep old stream snapshots eligible as current realtime data after idle/disconnect rotation. `/market/:symbol` also requires stream envelope symbol and candle timeframe proof before stream data can override typed polling state. `/trade` activity source labels now require matching authenticated `trader_id` plus `paper_account_id` scope proof before showing trader-specific order, execution, paper audit, or signal source copy. Validation remains pending.

## Production HTTPS Smoke Artifact Metadata Boundary

- Admin-only deployment readiness now can read `ALPHAFORGE_PRODUCTION_HTTPS_SMOKE_ARTIFACT` and expose sanitized artifact metadata.
- Evidence key `production_https_smoke_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- This is partial artifact metadata only; `production_https_smoke` remains `MISSING` until deployed HTTPS smoke evidence is produced and accepted.
- Real live trading remains `BLOCKED`; no submit/cancel/leverage/margin/live-gate path is enabled.

## Production Trader Repository Smoke Artifact Boundary

- `scripts/run_production_trader_repository_smoke.py` can validate already-produced durable repository, writer, isolation, migration, and backup/restore evidence.
- Admin trader-account readiness can read `ALPHAFORGE_PRODUCTION_TRADER_REPOSITORY_SMOKE_ARTIFACT` and expose sanitized artifact metadata.
- Evidence keys `production_trader_repository_smoke_runner_after_latest_changes` and `production_trader_repository_smoke_artifact_metadata_after_latest_changes` remain `PENDING` until backend tests and the full validation queue are run.
- `production_trader_repositories_and_writers` remains `MISSING`; this metadata does not by itself close the production repository/writer blocker.
- Real live trading remains `BLOCKED`; no submit/cancel/leverage/margin/live-gate path is enabled.


## Auth/session hardening artifact metadata note

- auth/session hardening artifact metadata is partial evidence only and is exposed only through admin-protected readiness metadata.
- Evidence key `auth_session_hardening_artifact_metadata_after_latest_changes` remains `PENDING` until backend tests and the full validation queue are run.
- `production_auth_session_hardening_missing` remains ACTIVE until production evidence is produced, validated, reviewed, and accepted.
- Real live trading remains BLOCKED; this note does not add live submit/cancel/leverage/margin/live-gate mutation.

## 2026-06-14 Durable Credential Vault Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Credential vault readiness | IN PROGRESS | `credential_vault_readiness_status()` can now report sanitized `ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT` metadata for backend-only vault integration, rotation policy, redaction, access control, audit logging, and no-live-mutation evidence. |
| `durable_credential_vault_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `backend_only_binance_credential_vault_missing` remains ACTIVE until durable production vault evidence is produced, validated, and accepted. Event: `durable_credential_vault_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Derivatives Realtime Source Smoke Runner Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Derivatives realtime/source evidence | IN PROGRESS | Added `scripts/run_derivatives_realtime_source_smoke.py` to validate already-produced funding/OI/liquidation/long-short/basis/exchange-comparison freshness and no-fake-live evidence. |
| `derivatives_realtime_source_smoke_runner_after_latest_changes` | PENDING | Unit coverage and full validation queue are pending. `derivatives_realtime_sources_missing` remains ACTIVE until production derivatives source evidence is produced, validated, and accepted. Event: `derivatives_realtime_source_smoke_runner_added`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Production Stream Validation Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Market stream source validation | IN PROGRESS | `/api/v2/market/{symbol}/stream-status` can now report sanitized `ALPHAFORGE_MARKET_STREAM_PRODUCTION_VALIDATION_ARTIFACT` metadata separately from stream alerting/dashboard metadata. |
| `production_stream_validation_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `production_stream_validation_alerting_missing` remains ACTIVE until stream source validation and alerting evidence are produced, validated, and accepted. Event: `production_stream_validation_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No websocket behavior, exchange call, live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

## 2026-06-14 Signals API Symbol Filter Contract

- Event: `signals_api_symbol_filter_API_added`.
- `/api/v2/signals?symbol={symbol}` withholds active signals when symbol evidence is missing or mismatched.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; backend pytest and current validation were not run.
- Signal repositories/realtime streams remain IN PROGRESS; no launch or live-trading status changed.

## 2026-06-14 Stream and Paper Symbol Validation Boundary

- ProChart read-only stream URL construction now fails closed for malformed symbols before opening native Binance public or same-origin backend WebSocket targets.
- `/api/v2/orders/preview`, `/api/v2/orders/paper`, and `/trade` order fallback envelopes now reject or omit malformed paper order symbols before local paper staging can be exposed.
- These are data-honesty and input-validation hardening changes only. Production stream validation, derivatives realtime sources, production paper submit/cancel validation, durable audit policy, and current validation remain pending.
- Real live trading remains `BLOCKED`; no live submit/cancel/leverage/margin/live-gate mutation was added or approved.

## 2026-06-14 ProChart Timeframe Validation Boundary

- ProChart read-only stream URL construction now accepts only the supported terminal chart timeframes: `1m`, `3m`, `5m`, `15m`, `1h`, `4h`, `1d`, and `1w`.
- Unsupported or malformed timeframes fail closed before native Binance public or same-origin backend stream URLs are built.
- This is stream-channel hardening only. Production stream validation, derivatives realtime sources, and current validation remain pending.

## 2026-06-14 ProChart Native Channel Validation Boundary

- ProChart native public stream frames now require matching symbol and an approved read-only channel before they can mark the chart stream connected.
- Unknown or malformed native stream names are ignored instead of becoming chart-readiness evidence.
- This is stream-frame hardening only. Production stream validation, derivatives realtime sources, and current validation remain pending.

## 2026-06-14 ProChart Partial Backend Snapshot Merge Boundary

- Partial backend market snapshots now preserve last valid ticker, depth, trades, candles, and stream-candle state when a snapshot omits a component.
- This keeps read-only panels from going blank during partial stream updates without presenting stale/static payloads as live evidence.
- Production stream validation, derivatives realtime sources, and current validation remain pending.

## 2026-06-14 Backend Market Contract Input Validation Boundary

- Public market detail/ticker/derivatives/candles/depth/trades endpoints now return structured unavailable states for malformed symbols rather than silently cleaning request input into a different symbol.
- Candles and market-data stream queries now return structured unavailable states for unsupported timeframes.
- Backend native public stream frames require matching symbol plus approved public channel before they can update read-only stream snapshots.
- This improves data honesty only. Production stream validation, derivatives realtime sources, durable repositories, and current validation remain pending.

## 2026-06-14 Frontend Market API Strict Input Guard Boundary

- Frontend market API helpers now return local structured unavailable envelopes for malformed symbols or unsupported timeframes before fetch.
- This prevents unsafe request values from becoming fallback metadata in `/trade`, `/market/:symbol`, or ProChart states.
- Production stream validation, derivatives realtime sources, durable repositories, and current validation remain pending.

## 2026-06-14 Signal Symbol Filter Validation Boundary

- `/api/v2/signals?symbol=` and the frontend signal API helper now fail closed for malformed symbol filters.
- This prevents `/trade` and `/market/:symbol` from silently normalizing malformed signal filters into a different market's evidence.
- Durable trader-specific signal routing, signal streams, and current validation remain pending.

## 2026-06-14 Alert Symbol Mutation Validation Boundary

- Paper alert create/update now rejects malformed symbols before repository mutation on the backend and before fetch in the frontend helper.
- Valid alert symbols are normalized before paper/read-only mutation; invalid symbols return structured unavailable state and do not create/update alert rows.
- Production alert delivery, notification delivery, durable alert audit repositories, screenshots, and current validation remain pending.

## 2026-06-14 Market Stream Status Symbol Validation Boundary

- `/api/v2/market/{symbol}/stream-status` now fails closed for malformed symbols before looking up read-only stream telemetry.
- This prevents malformed market inputs from being represented as another symbol's freshness or alert state.
- Production stream validation, dashboard/current alerting, and current validation remain pending.

## 2026-06-14 Market Overview and Trade Selector Symbol Filter Boundary

- Market overview symbol inventories now filter malformed symbols from public API and static fallback sources.
- `/trade` symbol selection now filters malformed symbols from native/API/fallback row data before presenting selectable state.
- This improves public/trader symbol data hygiene only. Production stream validation, durable repositories, and current validation remain pending.

## 2026-06-14 Market Detail Route Symbol Guard Boundary

- `/market/:symbol` route-derived symbols now pass through strict market-symbol validation before market detail state is exposed.
- Invalid route symbols return designed unavailable state and do not load static terminal fallback data as if it matched the requested market.
- Production stream validation, derivatives realtime sources, durable repositories, screenshots, and current validation remain pending.

## 2026-06-14 Market Detail Route Symbol Guard Boundary

- `/market/:symbol` frontend route state now fail-closes malformed route symbols into designed unavailable market state.
- Shared symbol data withholds static terminal fallback data for invalid route symbols instead of presenting fallback BTC/market data as if it matched the route.
- Production stream validation, derivatives realtime sources, durable repositories, screenshots, and current validation remain pending.

## 2026-06-14 Account Activity Row Scope Strictness

- `/trade` and account API surfaces now require explicit row-level trader/paper-account identifiers for account activity rows.
- Top-level scoped fallback payloads are no longer enough to display positions, orders, executions, audit events, or signal rows in trader account context.
- Realtime account streams and durable production repositories remain pending.

## 2026-06-14 Typed API Session Credentials

- `/trade`, `/dashboard`, alerts, and account-aware frontend API wrappers now send backend session credentials by default through the shared API helper.
- Trader-specific data remains available only when backend auth and account-scoped repositories return matching envelopes and rows.
- Public market data remains read-only; no live trading or exchange mutation path was added.

## 2026-06-14 ProChart Stale/Static Candle Withholding

- `/trade` and `/market/:symbol` chart panels now withhold stale/static candles from active chart rendering.
- Market stream ticker/depth/trade envelopes are used only while fresh API/repository stream data is available; stale stream snapshots no longer outrank API polling APIs.
- Realtime Binance public stream and durable repository validation remain pending.

## 2026-06-14 Standalone ProChart Static Overlay Withholding

- Standalone ProChart candles remain driven only by fresh API/repository candles or read-only public stream candles.
- OI/funding overlays now require fresh derivatives APIs; raw legacy overlay responses and static chart-file overlays are not treated as realtime evidence.
- Typed realtime indicator APIs for EMA/BB/AI target overlays remain pending.

## 2026-06-14 ProChart Indicator Controls Disabled Without Current Evidence

- Standalone ProChart no longer treats static chart-file indicators as live EMA/BB/AI target evidence.
- OI and L/S overlays depend on fresh derivatives APIs.
- Typed realtime indicator API surfaces and current validation remain pending.

## 2026-06-14 Market Indicators Gap Surface

- New read-only current indicator API: `/api/v2/market/{symbol}/indicators`.
- Current source status is structured unavailable for EMA/BB/AI target overlays.
- Static chart-file indicator payloads remain withheld from live/realtime chart evidence.
- Durable current indicator repository/stream remains pending.

## 2026-06-14 Market Detail Indicator Gap Visibility

- Market detail now reads current indicator API state from `/api/v2/market/{symbol}/indicators`.
- Indicator source gaps are visible in the page health and evidence sections.
- Static chart-file indicators remain withheld from realtime evidence.

## 2026-06-14 ProChart Indicator Controls Split by Series

- ProChart indicator controls now map to specific typed series: EMA uses `ema20`/`ema50`, BB uses `bb_upper`/`bb_lower`/`bb_middle`, AI target uses `ai_target`.
- Missing series keep their controls disabled and visible as source gaps.

## 2026-06-14 Trade Chart Indicator Gap Visibility

- `/trade` and `/market/:symbol` shared chart panel now reads current indicator API state.
- Indicator source posture is visible in chart toolbar and stats.
- Static chart-file indicators remain withheld from live evidence.

## Account readiness API update - 2026-06-14

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Trader account readiness | `/api/v2/account/readiness` backed by authenticated trader context and trader-account repository readiness metadata | production auth-scoped trader/account database, migration evidence, writer validation, current smoke evidence | IN PROGRESS | Public callers get sign-in-required structured state. Authenticated callers get sanitized account-specific readiness and missing production evidence. No raw credentials or live mutation state is exposed. |

## Market detail signal scope update - 2026-06-14

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Market detail signals | `/api/v2/signals?symbol={symbol}` plus frontend authenticated scope guard | durable trader-scoped signal repository and realtime signal stream | IN PROGRESS | Signed-in users now withhold active signal UI unless the envelope matches authenticated `trader_id` and `paper_account_id` or account-scope proof verifies the match. Public preview remains read-only and labeled. |

## ProChart symbol/timeframe evidence update - 2026-06-14

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Chart candles | `/api/v2/market/{symbol}/candles`, `/api/v2/ws/market-data`, public Binance stream adapter | durable realtime market stream with SLA and current validation evidence | IN PROGRESS | Chart rendering now rejects candle envelopes that do not explicitly match the active symbol and timeframe. Static/stale fallback remains withheld from live chart rendering. |

## Derivatives source-validation metadata update - 2026-06-14

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Market derivatives source validation | `/api/v2/market/{symbol}/derivatives.data.production_source_validation` from sanitized `ALPHAFORGE_DERIVATIVES_REALTIME_SOURCE_ARTIFACT` metadata | validated production realtime derivatives sources and durable derivative repositories | IN PROGRESS | The UI can now distinguish production derivatives evidence pending vs verified. This metadata does not fabricate liquidation/heatmap/exchange-comparison data and does not close the derivatives realtime blocker until current validation passes. |

## Public status derivatives posture update - 2026-06-14

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Public status derivatives posture | `/api/v2/status.derivatives_data` from sanitized derivatives source-evidence metadata | validated production realtime derivatives sources and public-safe monitoring | IN PROGRESS | `/status` can now show derivatives source evidence pending/verified without raw artifacts or private data. The derivatives realtime blocker remains active until evidence is produced and validation passes. |

## 2026-06-14 ProChart indicator source update

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| ProChart indicators | `/api/v2/market/{symbol}/indicators` deriving EMA/Bollinger from Binance public USD-M closed klines when reachable | durable read-only market-data repository plus stream validation artifact | IN PROGRESS | Static chart-file indicators are still withheld as live context; AI target remains unavailable until a durable prediction overlay source is wired; validation rerun pending. |
| ProChart watchlist | signed-in `/api/auth/me` user watchlist with public fallback favorites | trader-specific watchlist repository and symbol universe API | IN PROGRESS | ProChart favorites now use authenticated user watchlist when available; validation rerun pending. |

## 2026-06-14 ProChart continuation note

- `/chart/:symbol` now prefers typed `/api/v2/market/overview` for the symbol universe and uses the older chart-symbol feed only as supplemental enrichment.
- ProChart EMA/Bollinger overlays render only from fresh typed `/api/v2/market/{symbol}/indicators` API/repository envelopes.
- AI target remains unavailable unless the indicator/prediction overlay source returns current `ai_target`; static chart-file AI targets are not promoted as live.
- Authenticated trader account context comes from `/api/auth/me`; account values remain scoped by `trader_id` plus `paper_account_id`.
- Production stream validation, durable trader repositories/writers, verified paper submit/cancel/fill, and full validation rerun remain pending.

## 2026-06-14 authenticated shell account-scope guard

- Authenticated shell paper account chips now require the same safe portfolio account-scope match used by `/trade`.
- Header equity/PnL values are no longer sourced from unscoped runtime fallback data as trader-specific account truth.
- Validation rerun and screenshots remain pending.

## 2026-06-14 markets watchlist scoping

- `/markets` Favorites and Watchlist controls now prefer `/api/auth/me` user watchlist data for authenticated traders.
- Unsigned or empty-watchlist views use public default favorites only as a non-account fallback.
- Durable account preference persistence and validation rerun remain pending.

## 2026-06-14 trade symbol universe watchlist scoping

- `/trade` symbol selection now includes the authenticated backend user watchlist from `/api/auth/me`.
- The selector still includes scoped positions and current market symbols, with BTCUSDT as a public-safe fallback.
- Validation rerun remains pending.

## 2026-06-14 dashboard paper-mode scope cleanup

- `/dashboard` paper status copy now uses scoped paper-account truth instead of runtime fallback paper mode.
- Validation rerun remains pending.

## 2026-06-14 authenticated shell unscoped account fallback removed

- Authenticated shell `Paper PnL` and `Paper Equity` chips now fail closed to `Trader source unavailable` instead of falling back to unscoped runtime/portfolio payload values.
- Validation rerun remains pending.

## 2026-06-14 trader-owned watchlist update path

- `/api/accounts/me/watchlist` now provides a signed-in per-user watchlist update path.
- `/account-settings` can edit the signed-in user's watchlist; `/markets`, `/trade`, and `/chart/:symbol` consume the refreshed user watchlist through `/api/auth/me`.
- This closes the global-frontend-watchlist issue for these surfaces but does not close durable production account preference persistence, auth/session hardening, or validation blockers.

## 2026-06-14 trader exchange metadata scope note

- Exchange-account metadata is now linked only for signed-in users with both trader and paper account scope.
- Viewer or partially scoped accounts cannot create exchange metadata from the self-service route.
- This remains local/API partial evidence until durable production repositories, credential vault integration, signed read-only probes, and current validation pass.

## 2026-06-14 - Trader-scoped preview source posture

Paper preview remains a read-only calculation path. It requires signed-in trader and paper-account scope before exposing account-specific balance estimates. Sessions without scope receive a structured blocked preview response instead of fallback account data.

## 2026-06-14 Public/Trader Copy and Account-Scope Continuation

- Public/trader pages now prefer signed-in trader/user and paper workspace wording instead of backend/operator terminology.
- Account-sensitive data remains scoped by `trader_id` plus `paper_account_id` in backend API surfaces and is withheld when source rows are unscoped or mismatched.
- ProChart and trading chart copy now distinguishes read-only public streams, current candle sources, fallback/stale data, and unavailable sources without claiming full production realtime completion.
- Validation, screenshots, production stream evidence, durable repositories, signed read-only account validation, and production smoke remain pending.
- Real live trading remains BLOCKED; no live submit/cancel/leverage/margin/live-gate mutation was added.

## 2026-06-14 Public/Trader Direct Runtime Decoupling Continuation

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Landing | `/api/v2/market/overview`, `/api/v2/market/{symbol}/ticker`, `/api/v2/signals` with structured unavailable states | production monitoring, public market overview, market ticker stream, signal preview stream | IN PROGRESS | Landing no longer reads direct operator runtime, ingestor, or chart-manifest payload files. Market preview is typed contract-first and does not present fallback data as live. |
| Dashboard | trader-scoped paper account truth, trade terminal context, read-only prediction rows, CoinAnk aggregate fallback | durable auth-scoped trader/account repositories and validated market/signal streams | IN PROGRESS | Dashboard no longer reads direct runtime truth, portfolio-state, or system-observability payload files for trader-facing status. It remains blocked on durable repositories and validation. |

## 2026-06-14 Trade Terminal Legacy Runtime Removal

| Route area | Current source | Expected durable API/stream | Status | Notes |
|---|---|---|---|---|
| Trade terminal shared state | `/api/v2/portfolio`, `/api/v2/account/positions`, `/api/v2/execution/*`, `/api/v2/signals`, `/api/v2/market/*`, read-only market stream, direct public candle backfill | production trader repositories, validated market streams, verified paper submit/cancel service | IN PROGRESS | `useTradeTerminal` no longer reads direct legacy operator terminal, paper runtime, portfolio-state, or live-gate runtime files. Account/activity rows require typed trader and paper-account scope. Market fields rely on stream/API contracts and render unavailable labels when missing. |

## 2026-06-14 update - multi-trader paper-action scope

- Local paper order staging now requires explicit request `trader_id` and `paper_account_id` to match the backend-authenticated session before the trader-scoped repository can be mutated.
- Paper preview remains read-only/non-mutating and now reports whether the request scope matches the backend session.
- This is not production paper submit/cancel/fill validation; production paper actions remain blocked until verified service and durable repository evidence exist.
- Validation is pending; no phase or route status advances from this documentation update alone.

## 2026-06-14 update - derivatives liquidation runtime status

- `/api/v2/market/{symbol}/derivatives` now includes source-labeled liquidation runtime stream status and available liquidation-level metadata where the current runtime status provides it.
- 1h/24h liquidation notional totals, heatmaps, and exchange comparison remain source-pending and must stay displayed as unavailable until durable validated sources exist.
- No exchange mutation, live trading, leverage, or margin path is added.
- Validation is pending.

## Phase 15 account-link data stance update - 2026-06-15

- Trader exchange-account metadata remains backend-auth scoped and read-only. The self-service link route now rejects private-looking metadata and unknown request fields instead of accepting them as ignored payload.
- The first seeded trader remains `wajidali1984` / `wajidali1984@hotmail.com` with Binance read-only metadata bound to `trader-wajidali1984` and `paper-wajidali1984`; future traders require unique trader and paper-account IDs.
- No raw Binance credentials are stored in frontend state or returned from safe user payloads. Backend credential vault integration and signed read-only validation remain source-pending.

## Phase 15 ProChart data stance update - 2026-06-15

- ProChart continues to prefer read-only Binance USD-M public WebSocket frames and typed market contracts for active candles.
- `/api/v1/chart/symbols` and `/api/v1/chart/coinank/{symbol}/{timeframe}` now expose structured source/freshness/stale/missing fields instead of returning only legacy status values.
- The ProChart symbol sidebar now shows per-symbol freshness or `Data source unavailable` so stale/static chart symbols are not presented as live.
- Full realtime completion remains blocked until production stream validation, alerting, and durable derivatives/overlay repositories are proven.
