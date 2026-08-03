# API Gap Register (Draft)
Generated: 2026-06-12

This register tracks interfaces the frontend currently references via static payload polling and those still requiring backend API/websocket parity.

## Status legend
- `status: BLOCKED` = no live API or websocket endpoint available in this build.
- `status: PENDING` = endpoint exists but not yet surfaced in navigation.
- `status: PARTIAL` = typed endpoint/contract exists, but durable live/realtime data is still missing or falls back to static/unavailable state.
- `status: OK` = endpoint currently wired.

| feature | expected endpoint | fallback source | status | notes |
|---|---|---|---:|---|
| Market overview / status | `/api/v2/market/overview` | Binance public USD-M 24h inventory, static payload fallback | PARTIAL | Safe read-only contract now prefers public Binance market inventory; WebSocket/SSE stream and production monitoring are still pending. |
| Symbol search / watchlist | `/api/v2/symbols/search` | local symbol payloads | PENDING | Dedicated endpoint should support prefix search + user favorites. |
| Account positions | `/api/v2/account/positions` | runtime payload alias | PARTIAL | Safe paper/read-only contract includes backend trader context when signed in; durable account-scoped repository still missing. |
| Orders and executions | `/api/v2/execution/orders`, `/api/v2/execution/executions` | trader-scoped local paper repository or structured unavailable state | PARTIAL | Contracts return trader-scoped local paper order and execution rows when authenticated. Local paper submit/cancel/fill exists; no live mutation path exists. |
| Signals stream | `/api/v2/signals/stream` or websocket | static signal payloads | PENDING | Replace polling data with stream + de-duplication and stale/lag states. |
| Derivatives feeds (funding/OI/liquidations) | `/api/v2/market/{symbol}/derivatives`, future `/api/v2/derivatives/*` | Binance public funding/OI snapshot plus explicit unavailable states | PARTIAL | Funding, open interest, funding history, open-interest history, long/short ratio, and basis can surface through the read-only market derivatives contract. Liquidations, heatmaps, exchange comparison, durable repositories, realtime streams, and validation remain pending. |
| Dashboard aggregate | `/api/v2/dashboard` | trader-scoped account truth, trade terminal context, read-only prediction rows, and CoinAnk aggregate fallback | BLOCKED | Trader dashboard no longer reads direct runtime truth, paper runtime, portfolio-state, or system-observability payload files for trader-facing status. A durable dashboard endpoint and production trader/account repositories are still missing. |
| Market detail | `/api/v2/market/{symbol}` and `/ws/market-data` | Binance public USD-M ticker/premium/open-interest/depth/trades/closed klines plus fallback payloads | PARTIAL | Typed read-only contracts and backend/browser-side public WebSocket display now prefer Binance public market data. Stream validation/telemetry, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, outbound alert webhook notifier/active-only alert delivery, liquidation analytics, exchange comparison, durable repositories, and validation remain pending. ProChart can map typed funding/open-interest history into OI/funding overlays when available. |
| Market derivatives | `/api/v2/market/{symbol}/derivatives` | Binance public read-only funding history, open-interest history, global long/short ratio, and basis where available | PARTIAL | Liquidations, heatmap, and exchange comparison remain source-pending; no fake live derivatives data is emitted. |
| Order preview and local paper actions | `/api/v2/orders/preview`, `/api/v2/orders/paper`, `/api/v2/orders/paper/{order_id}/cancel`, `/api/v2/orders/paper/{order_id}/fill`, `/api/v2/execution/audit-events` | authenticated trader-scoped local paper repository | PARTIAL | Preview rejects live mode and can allow authenticated paper staging only when the preview scope matches both the active trader and paper account; submit/cancel/fill only mutate the local paper repository in non-production. If the local paper repository is blocked or unavailable, paper action endpoints return structured unavailable contract envelopes instead of bare repository exceptions. Fill rejects invalid sides, local IDs/audit flags are backend-owned, hash-chained local audit events plus append-only local ledger rows are recorded and exposed with audit policy metadata and paper audit retention policy metadata through a read-only typed audit-events contract, and production local repository/audit writes now fail closed. Production validation, durable paper audit policy, durable writer hardening, and screenshots remain pending. |
| Public status | `/api/v2/status` | safe degraded status fallback plus sanitized stream telemetry, local stream alert history summary, production stream alerting artifact metadata, production stream alerting smoke runner evidence, and outbound alert webhook notifier/active-only alert delivery status | PARTIAL | Public-safe contract includes platform/API/data/paper/live-disabled posture, Market stream freshness, current stream alert, local alert-history summary, artifact-present pending status when production alerting evidence is configured, and secret-free notifier state; the smoke runner can produce that artifact from supplied public-safe evidence only. Production alerting/dashboard current validation, incident feed, validation, and deployment smoke remain incomplete. |
| Alerts CRUD | `/api/v2/alerts` | public unavailable state plus authenticated local trader-scoped paper alert repository | PARTIAL | Typed contract surface exists and authenticated traders can use local or SQLAlchemy paper/read-only alert CRUD scoped by `trader_id` and `paper_account_id`. Notification delivery, production alert repositories, preferences, and durable audit logging remain blocked. |
| Auth/session | `/api/auth/login`, `/api/auth/logout`, `/api/auth/refresh`, `/api/auth/me`, `/api/admin/users/{user_id}/activation` | backend-confirmed session with dev file user/revocation stores or explicit SQLAlchemy auth and revocation stores | PARTIAL | Safe user payload now includes sanitized exchange account metadata normalized to the owning trader and paper-account scope, backend-only credential status, and secret-free session security/auth-store/revocation-store status/password-change session revocation/session-version invalidation. The `wajidali1984` trader metadata is scoped to `trader-wajidali1984` / `paper-wajidali1984`; bootstrap defaults do not include hardcoded usable credentials, and activation/reset is backend-protected. Current local metadata may be active after operator/admin activation, but production DB/session hardening remains incomplete. The local auth-user store now rejects duplicate paper-account IDs and rejects production access unless the pytest-only override is active; local token revocation store access also fails closed in production unless the pytest-only override is active. Explicit SQLAlchemy auth-store and revocation-store adapters can be selected with `ALPHAFORGE_AUTH_STORE_BACKEND=sqlalchemy`, `ALPHAFORGE_AUTH_DATABASE_URL`, `ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND=sqlalchemy`, and `ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL`, but production DB migrations/provisioning/session hardening, environment-backed admin step-up partial evidence, MFA/step-up, and full durable admin API coverage remain incomplete. |
| Trader account ownership | `/api/auth/me`, `/api/admin/users`, `/api/admin/credential-status`, `/api/admin/trader-accounts`, `/api/v2/portfolio`, `/api/v2/account/positions`, `/api/v2/execution/*`, `/api/v2/signals`, `/api/v2/orders/preview` | file-backed auth user metadata, safe credential status resolver, optional backend-only local vault-file/read-only scope enforcement binding, local trader account repository with integrity/readiness metadata, read-only multi-trader account-scope smoke runner, multi-trader account-scope smoke artifact metadata, explicit SQLAlchemy trader account repository adapter seam, scoped frontend account display, and typed activity tabs on `/trade` | PARTIAL | Backend trader context is attached for signed-in users. Account-sensitive contracts now use scoped repository state, filter repository rows by trader plus paper-account scope where rows are returned, or withhold fallback data unless both trader and paper-account scope match. The local auth user store and local admin repository route reject paper-account reuse across traders, expose partial local repository readiness metadata, and local repository writes now fail closed in production unless the explicit SQLAlchemy trader account repository backend is configured. Exchange-account metadata is normalized to the owning user `trader_id` and `paper_account_id`, and `/trade` does not display unscoped fallback equity as trader balance. `/trade` bottom tabs consume typed order, execution, and signal contracts where available, with typed portfolio, signal, and activity rows defensively filtered by the active trader plus paper-account scope. Production migration/provisioning, production writer validation, durable credential vault integration, and production portfolio/execution/signal writers and paper-order validation remain pending. |
| Admin users | `/api/admin/users` | local file-backed user store or explicit SQLAlchemy auth store plus local JSONL or explicit SQLAlchemy admin audit store | PARTIAL | Backend-enforced admin/superadmin access added for user management. Admin create/update/delete and activation/reset now write secret-free audit events before mutation, production create/update/delete requires a mutation reason, production local admin audit storage fails closed unless the pytest-only override is active, local auth-user storage rejects production access unless a durable backend is selected, and explicit SQLAlchemy auth-store, revocation-store, and admin-audit adapter seams exist. Alembic version-script authoring is still approval-gated; durable migrations/provisioning, invitation workflow, deactivation-first policy, and production validation remain incomplete. |
| Admin trader accounts | `/api/admin/trader-accounts` | local file-backed trader account repository | PARTIAL | Backend-enforced admin route can list/update local paper account repository state in non-production, exposes integrity/readiness metadata and multi-trader scope-smoke artifact metadata, rejects paper-account reuse across traders, and fails closed if a production environment attempts to write the local repository. This is not a production DB, credential vault, or live execution path. |
| Admin credential and audit readiness | `/api/admin/credential-status` | backend-only environment plus local vault-file/read-only scope enforcement presence resolver, credential vault readiness metadata, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, safe secret-redaction smoke runner, and admin audit-store readiness metadata plus retention-day metadata | PARTIAL | Backend-enforced admin route reports safe credential configured/pending state, aggregate vault readiness, permission-probe artifact status, signed-read validation artifact status, secret-redaction smoke artifact status, and admin audit-store readiness without returning keys/secrets and without calling Binance. Admin audit status now exposes whether retention-day metadata is configured, and production admin audit writes fail closed when retention-day metadata is missing, but durable retention enforcement is not complete. Local vault-file support, readiness metadata, and the smoke runner are backend-only partial evidence until run against production artifacts; durable credential vault integration, production permission probe, signed account adapter validation, production secret-redaction smoke, production audit migrations, and admin audit retention enforcement/policy remain pending. |
| Durable paper audit policy | `/api/v2/execution/audit-events`, local paper audit ledger metadata | hash-chain metadata, append-only local ledger metadata, paper audit retention metadata, and durable paper audit policy artifact metadata | PARTIAL | Local paper audit events remain paper-only and never touch exchange transport. A backend-only durable policy artifact can prove production durable store, retention enforcement, writer hardening, audit verification, and disabled live/exchange mutation as partial evidence, but current validation, durable production writer hardening, and production audit verification remain blockers. |

## Phase 8 `/trade` Gaps

| field/module | expected endpoint | fallback source | status | notes |
|---|---|---|---:|---|
| Mark price | `/api/v2/market/{symbol}` | Binance public premium index, fallback missing state | PARTIAL | Read-only mark price is wired from Binance public data when available; stream-backed freshness remains pending. |
| Index price | `/api/v2/market/{symbol}` | Binance public premium index, fallback missing state | PARTIAL | Read-only index price is wired from Binance public data when available; stream-backed freshness remains pending. |
| 24h change/high/low | `/api/v2/market/{symbol}/ticker` | Binance public 24h ticker, fallback missing state | PARTIAL | 24h fields are wired from read-only public ticker data when available; 1h/4h changes remain source-pending. |
| Candles | `/api/v2/market/{symbol}/candles`, `/ws/market-data` | Binance public closed klines, backend/browser-side public kline display, professional chart payload fallback | PARTIAL | Trade and professional charts prefer typed closed-candle polling and can display public stream kline updates; ProChart attempts the direct read-only Binance public stream before same-origin backend fallbacks, de-duplicates merged typed/live rows by timestamp, normalizes second/millisecond/ISO timestamps before freshness/lag display, sanitizes overlay rows, ignores mismatched native stream symbol/timeframe frames, rejects invalid native/typed/fallback OHLC rows before chart update, withholds stale or static candle snapshots from the primary chart, rotates past silent/stalled stream endpoints to the next read-only source, and no longer refits the viewport on every realtime tick; forming candles remain display-only and validation is pending. |
| Order book ladder | `/api/v2/market/{symbol}/depth`, `/ws/market-data` | Binance public depth ladder, backend/browser-side public depth20 display, top-of-book fallback | PARTIAL | Public depth levels are wired by request-time API and public WebSocket display; reconnect telemetry, alerting, and liquidity-wall analytics remain pending. |
| Market depth curve | `/api/v2/market/{symbol}/depth`, `/ws/market-data` | Binance public depth ladder, backend/browser-side public depth20 display, top-of-book fallback | PARTIAL | Cumulative chart can use typed levels; liquidity wall markers, validation, and production stream telemetry remain pending. |
| Recent trades tape | `/api/v2/market/{symbol}/trades`, `/ws/market-data` or `/events` | Binance public recent trades and aggregate trade stream display | PARTIAL | Request-time recent trades and public aggregate trade stream display are wired; validation, lag telemetry, and durable trade store remain pending. |
| Paper order preview | `/api/v2/orders/preview` | trader-scoped local paper repository | PARTIAL | Preview rejects live mode, malformed symbols, paper-account mismatch, and trader mismatch; it exposes explicit partial local paper execution policy metadata, reports production validation pending, and can allow authenticated local paper staging when paper balance checks pass. |
| Paper order submit | `/api/v2/orders/paper` | trader-scoped local paper repository | PARTIAL | Authenticated local paper staging exists, rejects malformed symbols before local staging, never calls exchange transport, and explicitly uses partial local policy metadata plus a no-auto-fill policy; production validation, audit policy, fill validation, and screenshots remain pending. |
| Paper cancel | `/api/v2/orders/paper/{order_id}/cancel` | trader-scoped local paper repository | PARTIAL | Authenticated local paper cancel exists, returns explicit partial local policy metadata, and never cancels an exchange order; production validation, audit policy, and screenshots remain pending. |
| Paper fill | `/api/v2/orders/paper/{order_id}/fill` | trader-scoped local paper repository | PARTIAL | Authenticated manual local paper fill can write local execution and position rows with local audit metadata, hash-chained local audit events, append-only local ledger rows, and live/exchange mutation flags disabled in non-production; production local repository/audit writes fail closed; invalid sides are rejected; production validation, durable paper audit policy, persistence hardening, screenshots, and rerun evidence remain pending. |
| Positions | `/api/v2/account/positions` | trader-scoped contract, unscoped fallback withheld | PARTIAL | Contract exists and is paper/read-only with backend trader context; launch requires durable auth-scoped account source. |
| Open orders/history | `/api/v2/execution/orders`, `/api/v2/orders/paper/{order_id}/cancel` | trader-scoped contract or designed unavailable state | PARTIAL | Contract exists and `/trade` renders typed paper order rows when available; local paper cancel is available only for authenticated open paper repository orders. Filled orders are no longer cancelable. |
| Executions | `/api/v2/execution/executions` | trader-scoped contract or designed unavailable state | PARTIAL | Contract exists and `/trade` renders typed paper execution rows when available; local staged orders do not auto-fill, and explicit manual local fills can write paper execution rows. Durable production audit validation remains blocked. |
| Signals | `/api/v2/signals` | trader-scoped contract with unscoped fallback signal evidence withheld | PARTIAL | Contract exists and `/trade` renders typed active signal evidence only when scoped to the active trader and paper account. Durable trader-specific signal routing, realtime signal streams, and missing targets/stops/invalidation fields remain blockers. |
| Portfolio summary | `/api/v2/portfolio` | trader-scoped contract, unscoped fallback withheld, `/trade` scoped account display | PARTIAL | Contract exists and is paper/read-only; `/trade` uses it for account truth and shows a designed missing account-source state instead of fallback equity. Durable trader-specific balance/equity repository remains pending. |

## Phase 4A + 7A Contract Pass

Documentation structure check: Phase 8 `/trade` gap rows are in a valid Markdown table under the correct section; no unrelated document heading is embedded inside the table. `/trade` remains `IN PROGRESS`, not `PASS`.

| endpoint | implementation status | data honesty status | remaining blocker |
|---|---|---|---|
| `GET /api/v2/market/overview` | PARTIAL | prefers Binance public USD-M 24h inventory; falls back to static/unavailable | durable market overview repository/stream |
| `GET /api/v2/market/{symbol}` | PARTIAL | prefers Binance public ticker, premium index, and open interest; falls back to static/unavailable | WebSocket/SSE ticker stream and 1h/4h change source |
| `GET /api/v2/market/{symbol}/ticker` | PARTIAL | aliases market detail contract with public Binance data when available | WebSocket/SSE ticker stream and 1h/4h change source |
| `GET /api/v2/market/{symbol}/candles` | PARTIAL | returns Binance public closed klines or static chart fallback/unavailable | WebSocket/SSE candle stream and durable candle store |
| `GET /api/v2/market/{symbol}/depth` | PARTIAL | returns Binance public depth ladder or top-of-book fallback/unavailable | realtime depth stream and liquidity wall annotations |
| `GET /api/v2/market/{symbol}/trades` | PARTIAL | returns Binance public recent trades or structured unavailable state | realtime trade stream/source |
| `WS /ws/market-data` and `WS /api/v2/ws/market-data` | PARTIAL | attempts backend read-only Binance USD-M public streams for ticker/book/mark/depth20/aggTrade/kline, then falls back to safe contract polling | validation, reconnect telemetry, production alerting/dashboard current validation, derivatives/liquidation streams, and production stream monitoring |
| `GET /api/v2/market/{symbol}/stream-status` | PARTIAL | returns local persisted read-only stream telemetry, public-safe current alert state, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner output when configured, and outbound alert webhook notifier/active-only alert delivery status with source, last frame, lag, native frame count, fallback count, and stale state | production alerting/dashboard current validation, reconnect metrics, and validation |
| `GET /api/v2/market/{symbol}/derivatives` | PARTIAL | returns read-only funding/OI snapshot, funding history, open-interest history, long/short ratio, basis, or structured unavailable/static fallback state with source/freshness/missing fields | liquidations, heatmaps, exchange comparison, realtime streams, durable repositories, and validation |
| `GET /api/v2/account/exchange-readonly` | PARTIAL | authenticated trader-scoped Binance USD-M signed read-only account snapshot using backend-only env/local vault-file/read-only scope enforcement binding, secret-free structured unavailable state when credentials/read fails | durable production credential vault, signed-read validation, account stream/repository persistence, multi-exchange support |
| `GET /api/v2/portfolio` | PARTIAL | uses local trader-scoped repository for authenticated traders or withholds unscoped fallback | production auth-scoped portfolio source and writer |
| `GET /api/v2/account/positions` | PARTIAL | uses local trader-scoped repository for authenticated traders or withholds unscoped fallback | production auth-scoped positions source and writer |
| `GET /api/v2/execution/orders` | PARTIAL | uses local trader-scoped paper order repository when authenticated; local paper submit/cancel/fill updates that repository only | production paper-order validation, audit policy, and durable writer hardening |
| `GET /api/v2/execution/executions` | PARTIAL | uses local trader-scoped paper execution repository when authenticated, including explicit manual local paper fills | production paper execution writer/fill policy and audit validation |
| `GET /api/v2/signals` | PARTIAL | uses local trader-scoped signal repository when authenticated; otherwise static signal fallback or unavailable state | durable signal evidence writer |
| `POST /api/v2/orders/preview` | PARTIAL | rejects live mode, malformed symbols, and trader scope mismatch; can approve authenticated local paper staging only | production validation, audit policy, durable writer hardening, screenshots, full rerun |
| `POST /api/v2/orders/paper` | PARTIAL | authenticated trader-scoped local paper order staging only with malformed-symbol rejection; no exchange transport | production validation, audit policy, durable writer hardening, screenshots, full rerun |
| `POST /api/v2/orders/paper/{order_id}/cancel` | PARTIAL | authenticated trader-scoped local paper order cancel only; no exchange transport | production validation, audit policy, durable writer hardening, screenshots, full rerun |
| `POST /api/v2/orders/paper/{order_id}/fill` | PARTIAL | authenticated trader-scoped manual local paper fill only; writes local execution/position rows and no exchange transport | production validation, audit policy, durable writer hardening, screenshots, full rerun |

## Phase 3A + 5B Auth/Status Pass

| endpoint | implementation status | security/data honesty status | remaining blocker |
|---|---|---|---|
| `POST /api/auth/login` | PARTIAL | bcrypt password check, signed token, HttpOnly cookie, safe user payload | production user repository, secret rotation, environment-backed admin step-up partial evidence; MFA/step-up |
| `POST /api/auth/logout` | PARTIAL | clears session cookie | production session invalidation store |
| `POST /api/auth/refresh` | PARTIAL | requires authenticated bearer/cookie session | durable token rotation/revocation policy |
| `GET /api/auth/me` | PARTIAL | returns safe backend-confirmed user and secret-free session security status/password-change session revocation/session-version invalidation or no-user state | production session/cookie verification |
| `GET /api/admin/users` | PARTIAL | rejects unauthenticated and non-admin users in backend tests | durable repository and broader admin audit |
| `POST /api/admin/users` | PARTIAL | admin/superadmin only; hashes passwords; writes secret-free local audit event before mutation; production reason required | durable repository, durable audit trail, invitation flow, and production validation |
| `PUT /api/admin/users/{id}` | PARTIAL | admin/superadmin only; safe user payload; writes secret-free local audit event before mutation; production reason required | durable repository, durable audit trail and production validation |
| `DELETE /api/admin/users/{id}` | PARTIAL | admin/superadmin only; deletes local user record after secret-free local audit event; production reason required | durable repository, durable audit trail, deactivation-first policy, and production validation |
| `GET /api/admin/evidence` | PARTIAL | superadmin-only read-only test route | full superadmin API inventory |
| `GET /api/admin/trader-accounts` | PARTIAL | admin-only local paper account repository list; no secrets exposed | production DB repository, writer audit, and role policy |
| `PUT /api/admin/trader-accounts/{paper_account_id}` | PARTIAL | admin-only local paper account repository upsert in non-production; production local writes fail closed; no exchange mutation | production DB repository, writer audit, and role policy |
| `GET /api/admin/credential-status` | PARTIAL | admin-only safe credential configured/pending status from backend-only env/local vault-file/read-only scope enforcement binding; no raw values exposed; no exchange call | durable production credential vault, permission probe, and signed read-only adapter validation |
| `GET /api/v2/status` | PARTIAL | public-safe status fields only; live trading remains false | production monitoring and incident source |

## Multi-Trader Account Pass

| item | implementation status | safety/data honesty status | remaining blocker |
|---|---|---|---|
| Initial trader user `wajidali1984` | PARTIAL | scoped to `trader-wajidali1984` / `paper-wajidali1984`; current local metadata is active, while bootstrap/default seeding still avoids hardcoded usable credentials and protected admin activation/reset remains the approved workflow | durable user database, environment-backed admin step-up partial evidence, MFA/step-up, and production session hardening |
| Binance account link | PARTIAL | represented as sanitized read-only account metadata with centralized backend-only env/local vault-file/read-only scope enforcement credential binding lookup and safe configured/pending/binding-required status; trader-side linking is metadata-only and no API key/secret or backend credential reference is accepted or exposed through public/trader payloads | durable credential vault/read-only signed account adapter validation |
| Trader context on `/api/v2` contracts | PARTIAL | optional backend-authenticated context is attached; local file-backed trader account repository exists; account-sensitive contracts fail closed when fallback data is unscoped | production database repositories and writers for each trader account |
| Realtime chart data | PARTIAL | charts prefer typed Binance public closed-candle contracts and can display backend/browser-side read-only public stream updates while labeling forming candles as display-only; browser and backend native stream paths filter wrong-symbol/wrong-timeframe kline frames and invalid OHLC frames before chart update | validation, reconnect telemetry, derivatives streams, and durable candle/depth/trade stores |

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

## 2026-06-14 Production Paper Fill-Writer Artifact Metadata Entry

| Area | Current status | Monitoring note |
|---|---|---|
| Paper execution policy | IN PROGRESS | `/api/v2/orders/preview` and paper action policy responses can now report sanitized `ALPHAFORGE_PRODUCTION_PAPER_FILL_WRITER_ARTIFACT` metadata while keeping production paper actions disabled. |
| `production_paper_fill_writer_artifact_metadata_after_latest_changes` | PENDING | Backend tests and full validation queue are pending. `production_paper_fill_writer_missing` remains ACTIVE until production fill-writer evidence is produced, validated, and accepted. Event: `production_paper_fill_writer_artifact_metadata_surfaced`. |
| Real live trading | BLOCKED | No live submit/cancel/leverage/margin/live-gate mutation was added or approved. |

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

- Event: `signals_api_symbol_filter_contract_added`.
- `/api/v2/signals?symbol={symbol}` withholds active signals when symbol evidence is missing or mismatched.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; backend pytest and current validation were not run.
- Signal repositories/realtime streams remain IN PROGRESS; no launch or live-trading status changed.

## 2026-06-14 Trade Terminal Symbol-Scoped Signal Request

- Event: `trade_terminal_symbol_scoped_signal_request_added`.
- `/trade` now requests `/api/v2/signals?symbol={activeSymbol}` and still requires active trader plus paper-account scope before rendering signal evidence.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Signal repositories/realtime streams remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Trade Terminal Signal Symbol Guard Hardening

- Event: `trade_terminal_signal_symbol_guard_hardened`.
- `/trade` now rejects non-empty typed or fallback signal evidence that lacks selected-market symbol proof.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Signal repositories/realtime streams remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Trade Terminal Withheld Signal Source Copy

- Event: `trade_terminal_withheld_signal_source_copy_hardened`.
- `/trade` now reports `Signal source unavailable` when selected-symbol signal evidence is absent or withheld.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Signal repositories/realtime streams remain `PARTIAL`; no live trading path was added.

## 2026-06-14 ProChart Backend Invalid Snapshot Preservation

- Event: `prochart_backend_invalid_snapshot_preserves_last_valid_candle`.
- ProChart backend stream snapshots with invalid fresh OHLC rows now preserve the prior valid stream candle and warn instead of clearing realtime chart state.
- Evidence key `prochart_backend_snapshot_live_candle_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation/alerting remains `PARTIAL`; no live trading path was added.

## 2026-06-14 Paper Account Truth Current-Scope Guard

- Event: `paper_account_truth_requires_current_trader_scope`.
- Frontend paper-account truth now requires typed portfolio data or account-scope proof to match the active trader and paper account before displaying equity.
- Evidence key `frontend_trader_scoped_paper_account_after_latest_changes` remains `PENDING`; validation was not run.
- Durable trader account repositories and writers remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Paper Account Truth Contradictory Scope Fail-Closed

- Event: `paper_account_truth_contradictory_scope_fail_closed`.
- Frontend paper-account truth now withholds typed portfolio data when data-level trader or paper-account IDs contradict the active account.
- Evidence key `frontend_trader_scoped_paper_account_after_latest_changes` remains `PENDING`; validation was not run.
- Durable trader account repositories and writers remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Paper Account Truth Bad Numeric and Fetch-Failure Guard

- Event: `paper_account_truth_bad_numeric_and_fetch_failure_guard_added`.
- Frontend paper-account truth now prevents `NaN` PnL and resolves typed portfolio fetch failures to scoped unavailable state.
- Evidence key `frontend_trader_scoped_paper_account_after_latest_changes` remains `PENDING`; validation was not run.
- Durable trader account repositories and writers remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Local Wajid Trader Read-Only Scope Observation

- Event: `local_wajid_trader_active_readonly_scope_observed`.
- Local auth metadata currently has `wajidali1984` active with a read-only Binance metadata binding scoped to `trader-wajidali1984` / `paper-wajidali1984`.
- Credential status remains `credential_source_pending`; durable credential vault and signed read-only account validation remain `PARTIAL`.
- Evidence key `trader_user_scope_enforcement_after_latest_changes` remains `PENDING`; validation was not run.

## 2026-06-14 Trade Chart Safe Stream Live-Candle Readiness

- Event: `trade_chart_safe_stream_live_candle_readiness_hardened`.
- `/trade` chart readiness now accepts fresh read-only safe stream candles from same-origin stream paths, not only direct native Binance stream candles.
- Evidence key `prochart_realtime_merge_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation/alerting remains `PARTIAL`; no live trading path was added.

## 2026-06-14 ProChart Derivative Overlay Typed-Current Source Priority

- Event: `prochart_derivative_overlay_typed_current_source_preferred`.
- ProChart derivative overlays now prefer fresh typed `/api/v2/market/{symbol}/derivatives` API/repository data and avoid stale/static typed overlays as active context.
- Evidence key `prochart_realtime_contract_spec_after_latest_changes` remains `PENDING`; validation was not run.
- Derivatives realtime sources remain `PARTIAL`; no live trading path was added.

## 2026-06-14 Paper Preview Trader-Scope Contract Hardening

- Event: `paper_preview_trader_scope_contract_hardened`.
- `/api/v2/orders/preview` and local paper submit now normalize response symbols, with authored backend coverage for mismatched `trader_id` rejection.
- Evidence key `production_paper_actions_fail_closed_after_latest_changes` remains `PENDING`; validation was not run.
- Preview remains calculation-only; production paper submit/cancel validation remains `PARTIAL`; no live trading path was added.

- Event: `paper_order_symbol_validation_fail_closed`.
- `/api/v2/orders/preview` and `/api/v2/orders/paper` now reject malformed symbols with structured `symbol_invalid` responses before a local paper order can be staged.
- Evidence key `production_paper_actions_fail_closed_after_latest_changes` remains `PENDING`; validation was not run.
- Production paper submit/cancel validation, durable audit policy, and current validation remain blockers; no live trading path was added.

- Event: `paper_order_unavailable_envelope_symbol_sanitized`.
- `/trade` order API fallback envelopes now omit malformed request symbols if the typed preview/submit endpoint is unavailable, preventing unsafe symbol text from appearing as metadata.
- Evidence key `production_paper_actions_fail_closed_after_latest_changes` remains `PENDING`; validation was not run.
- This does not close production paper submit/cancel validation or durable audit blockers.

## 2026-06-14 Market Contract Input Validation Boundary

- Event: `market_contract_strict_input_validation_added`.
- `/api/v2/market/{symbol}`, `/ticker`, `/derivatives`, `/candles`, `/depth`, `/trades`, and `/ws/market-data` now reject malformed symbols with structured unavailable states instead of silently cleaning input into a different symbol.
- `/api/v2/market/{symbol}/candles` and `/ws/market-data` reject unsupported timeframes with a structured unavailable state.
- Evidence key `prochart_stream_symbol_timeframe_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation, derivatives realtime sources, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Backend Native Stream Channel Guard Boundary

- Event: `backend_native_stream_channel_guard_added`.
- Backend native public stream frames now require a matching symbol and approved Binance public channel before they can update read-only market snapshots.
- Evidence key `backend_native_public_stream_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation, dashboard/current alerting, and full validation remain blockers; no live trading path was added.

## 2026-06-14 Frontend Market API Strict Input Guard Boundary

- Event: `frontend_market_api_strict_input_guard_added`.
- Frontend `/api/v2/market/*` helpers now return local structured unavailable envelopes for malformed symbols or unsupported timeframes before a fetch or fallback metadata reflection can occur.
- Evidence key `prochart_stream_symbol_timeframe_filter_after_latest_changes` remains `PENDING`; validation was not run.
- This does not close production stream validation, derivatives realtime source, or current validation blockers.

## 2026-06-14 Signal Symbol Filter Validation Boundary

- Events: `signals_api_strict_symbol_query_guard_added`, `frontend_signals_strict_symbol_guard_added`.
- `/api/v2/signals?symbol=` and the frontend signal API helper now return structured unavailable states for malformed symbol filters instead of silently normalizing them.
- Evidence key `frontend_typed_portfolio_signal_scope_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Durable trader-specific signal repositories, signal streams, target/stop/invalidation completeness, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Alert Symbol Mutation Validation Boundary

- Events: `alerts_api_symbol_mutation_guard_added`, `frontend_alerts_symbol_mutation_guard_added`.
- Backend `/api/v2/alerts` create/update and frontend alert helpers now reject malformed symbols before local or SQLAlchemy paper-alert repository mutation.
- Evidence key `alerts_contract_after_latest_changes` remains `PENDING`; validation was not run.
- Production alert delivery, notification delivery, durable alert audit repositories, screenshots, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Market Stream Status Symbol Validation Boundary

- Event: `market_stream_status_strict_symbol_guard_added`.
- `/api/v2/market/{symbol}/stream-status` now returns a structured unavailable state for malformed symbols instead of silently cleaning the request into another market's stream telemetry.
- Evidence key `market_stream_status_alert_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation, dashboard/current alerting, and full validation remain blockers; no live trading path was added.

## 2026-06-14 Market Overview and Trade Selector Symbol Filter Boundary

- Events: `market_overview_symbol_inventory_filter_added`, `trade_terminal_symbol_selector_filter_added`.
- `/api/v2/market/overview` now filters malformed symbols from public API and static fallback inventories.
- `/trade` now filters malformed symbols from typed/fallback row sources before presenting selectable terminal symbols.
- Evidence keys `prochart_stream_symbol_timeframe_filter_after_latest_changes` and `trade_typed_activity_tabs_after_latest_changes` remain `PENDING`; validation was not run.
- Production stream validation, production trader repositories, screenshots, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Market Detail Route Symbol Guard Boundary

- Events: `market_detail_route_symbol_guard_added`, `symbol_data_invalid_route_fallback_withheld`.
- `/market/:symbol` now treats malformed route symbols as invalid market state and the shared symbol data hook withholds static fallback detail for invalid route symbols.
- Evidence key `prochart_stream_symbol_timeframe_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation, derivatives realtime sources, screenshots, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Market Detail Route Symbol Guard Boundary

- Events: `market_detail_route_symbol_guard_added`, `symbol_data_invalid_route_fallback_withheld`.
- `/market/:symbol` frontend route state now treats malformed route symbols as invalid market state rather than presenting them as valid market identity.
- Shared market symbol data now returns structured unavailable state for invalid route symbols and does not load static terminal fallback data as market detail.
- Evidence key `prochart_stream_symbol_timeframe_filter_after_latest_changes` remains `PENDING`; validation was not run.
- Production stream validation, derivatives realtime sources, screenshots, and current validation remain blockers; no live trading path was added.

## 2026-06-14 Account Activity Row Scope Strictness

- Account activity rows now require explicit row-level `trader_id` and `paper_account_id` before display or contract exposure.
- Static fallback portfolio payloads with top-level trader scope but unscoped/mismatched rows now return `positions_scope` in `missing_fields` and withhold those rows.
- This closes a local data-isolation defect only; durable production trader repositories, realtime account streams, current validation, and visual QA remain pending.

## 2026-06-14 Typed API Session Credentials

- Shared frontend typed API calls now include backend session credentials by default.
- This fixes a contract transport gap where authenticated trader pages could call `/api/v2/*` account endpoints anonymously and receive public/unavailable states.
- Durable trader repositories, realtime account streams, production auth hardening, and current validation remain pending.

## 2026-06-14 ProChart Stale/Static Candle Withholding

- Trading chart display now requires fresh `api` or `repository` candle envelopes, or a current read-only stream candle.
- `static_payload` and stale candle envelopes are withheld from active chart rendering and must remain documented as fallback/missing state.
- Realtime native stream validation, durable candle repository freshness, and screenshot QA remain pending.

## 2026-06-14 Standalone ProChart Static Overlay Withholding

- Standalone ProChart now requires fresh typed `/api/v2` derivative envelopes before rendering OI/funding overlays.
- Static chart-file overlays, static AI target signals, and raw legacy v1 overlay responses are withheld from realtime chart evidence.
- Missing durable typed indicator/overlay contracts remain a blocker for complete ProChart realtime readiness.

## 2026-06-14 ProChart Indicator Controls Disabled Without Typed Evidence

- EMA, BB, and AI target controls now remain disabled until typed realtime indicator evidence exists.
- OI/L/S controls require fresh typed derivatives overlay data before they can be toggled.
- Missing typed realtime indicator endpoints/contracts remain a blocker for complete ProChart readiness.

## 2026-06-14 Typed Market Indicators Gap Contract

| Endpoint/field | Status | Notes |
|---|---|---|
| `GET /api/v2/market/{symbol}/indicators` | STRUCTURED UNAVAILABLE | Read-only contract added for EMA/BB/AI target indicator evidence. It returns unavailable state and missing fields until a real API/repository source exists. |
| `ema20`, `ema50`, `bb_upper`, `bb_lower`, `bb_middle`, `ai_target` | BLOCKED | No durable typed realtime indicator repository/stream is wired. Static chart-file indicators are withheld. |
| ProChart indicator controls | IN PROGRESS | Controls query the typed indicators contract and stay disabled until fresh typed evidence exists. |

## 2026-06-14 Market Detail Indicator Gap Visibility

- `/market/:symbol` now displays `/api/v2/market/{symbol}/indicators` as an explicit typed contract in market health and evidence UI.
- Missing EMA/BB/AI target fields remain visible as source gaps instead of being hidden by static chart fallback behavior.
- Endpoint remains structured unavailable until a durable realtime indicator repository/stream is wired.

## 2026-06-14 ProChart Indicator Controls Split by Series

- ProChart EMA, BB, and AI target controls now require specific typed indicator series evidence.
- Generic indicator envelope availability is no longer enough to enable unrelated indicator controls.
- Typed realtime indicator source remains blocked.

## 2026-06-14 Trade Chart Indicator Gap Visibility

- Shared chart panel now consumes `/api/v2/market/{symbol}/indicators` and displays indicator source state.
- MA/EMA/VWAP/RSI/MACD labels remain unavailable when typed indicator evidence is missing.
- Durable typed indicator source remains blocked.

## Account readiness typed contract - 2026-06-14

| Endpoint/Field | Status | Notes |
|---|---|---|
| `/api/v2/account/readiness` | ADDED CONTRACT SURFACE | Safe paper/read-only typed contract returns source/freshness/missing/warnings plus authenticated trader/paper-account scope proof. It never exposes credentials and never mutates exchange state. |
| production trader repository | BLOCKED | Local/dev and SQLAlchemy adapter seams exist, but production repository provisioning, migrations, backup/restore, retention, writer validation, and current smoke evidence remain pending. |
| `/trade` account readiness | IN PROGRESS | Frontend now prefers the typed readiness contract and displays account readiness distinctly from credential and exchange read-only status. |

## Derivatives realtime/source artifact metadata - 2026-06-14

| endpoint/field | status | notes |
|---|---|---|
| `/api/v2/market/{symbol}/derivatives.data.production_source_validation` | PARTIAL | Reads sanitized `ALPHAFORGE_DERIVATIVES_REALTIME_SOURCE_ARTIFACT` metadata when configured. Pending/invalid artifact states remain explicit missing data and are not treated as live. |
| `derivatives_realtime_sources_missing` | BLOCKED | Still active until production evidence proves realtime funding, OI, liquidations, long/short, basis, exchange comparison, freshness/stale states, source labels, no fake-live data, and disabled live/exchange mutation. |

## Public status derivatives posture - 2026-06-14

| endpoint/field | status | notes |
|---|---|---|
| `/api/v2/status.derivatives_data` | PARTIAL | Public-safe derivatives data summary exposes pending/verified source posture and missing-count only. It does not expose raw artifacts, logs, credentials, or exchange state. |

## 2026-06-14 ProChart Public-Kline Indicator Contract

| Area | Endpoint/source | Status | Notes |
|---|---|---|---|
| ProChart EMA/Bollinger indicators | `/api/v2/market/{symbol}/indicators` from Binance public USD-M closed klines | PARTIAL | EMA20, EMA50, and Bollinger Bands can now be derived from current read-only public klines when reachable. Static chart-file indicators remain withheld as live context. |
| ProChart AI target overlay | typed prediction overlay source | BLOCKED | AI target stays disabled until a typed current prediction overlay contract exists. |
| ProChart full realtime readiness | native/backend market stream validation, derivatives realtime source validation, indicator contract rerun | IN PROGRESS | Current implementation is read-only and fail-closed; validation rerun and production stream evidence remain pending. |

## 2026-06-14 ProChart overlay render and trader-scope continuation

| Area | Endpoint/source | Status | Notes |
|---|---|---|---|
| ProChart symbol universe | `/api/v2/market/overview` plus supplemental `/api/v1/chart/symbols` | PARTIAL | Symbol panel now prefers the typed market overview contract. The legacy chart-symbol feed is supplemental enrichment only; production stream validation and alerting remain pending. |
| ProChart indicators | `/api/v2/market/{symbol}/indicators` | PARTIAL | Fresh typed indicator series now feed the rendered EMA/Bollinger/AI-target overlay payload. EMA/Bollinger can derive from public closed klines; AI target remains blocked unless a current typed prediction overlay source returns `ai_target`. |
| Trader-specific chart context | `/api/auth/me` | PARTIAL | `/chart/:symbol` header and favorites use backend-authenticated user scope and watchlist. Durable user/session hardening, production repository smoke, and full validation rerun remain pending. |
| Public/trader shell account context | `/api/auth/me` | PARTIAL | Shared public/trader shell now displays backend-authenticated account/paper/exchange posture instead of operator runtime payload values. No credential references or exchange secrets are exposed. |

## 2026-06-14 trader-owned watchlist update path

| Area | Endpoint/source | Status | Notes |
|---|---|---|---|
| Trader watchlist preferences | `PUT /api/accounts/me/watchlist`, `GET /api/auth/me` | PARTIAL | Authenticated users can update their own normalized watchlist, and trader pages consume that user-scoped list. Durable production auth/user store, preference audit policy, screenshots, and validation rerun remain pending. |

## 2026-06-14 ProChart realtime domain display note

| Area | Contract surface | Current state | Remaining gap |
|---|---|---|---|
| `/chart/:symbol` realtime health | `useMarketDataStream` ticker/depth/trades envelopes | ProChart displays explicit price/depth/trades health chips (`Current`, `Stale`, `Unavailable`) and source tooltips. | Production validation for websocket/SSE availability, lag, reconnect, depth/trades completeness, and derivative/signal realtime domains remains pending. |

## 2026-06-14 account-link scope guard note

| Area | Contract surface | Current state | Remaining gap |
|---|---|---|---|
| Trader exchange metadata | `POST /api/accounts/me/exchange-accounts` | Fails closed with `trader_account_scope_required` when the authenticated user lacks `trader_id` or `paper_account_id`, requires exact backend role `trader`, and forces read-only/live-disabled metadata only. | Current backend validation, durable user/account repository constraints, backend-only credential vault binding, signed read-only credential probe, and production smoke remain pending. |

## 2026-06-14 frontend credential-reference type boundary

| Area | Contract surface | Current state | Remaining gap |
|---|---|---|---|
| Credential reference exposure | frontend `AuthUser.exchange_accounts` type | Trader-facing frontend auth types no longer include `credential_ref`; safe user payloads should only expose sanitized `credential_status`. | Current typecheck/build rerun, backend-only credential vault integration, signed read-only probe, secret-redaction smoke, and production session hardening remain pending. |

## 2026-06-14 - Paper preview account-scope hardening

`/api/v2/orders/preview` is still preview-only. It now fails closed with `trader_account_scope_required` when an authenticated user lacks a trader profile or paper workspace. Verified paper submit/cancel service evidence remains missing; real live trading remains blocked.

## 2026-06-14 - Paper preview scoped balance withholding

Paper preview balance estimates are now withheld unless the backend-authenticated session has a trader profile and paper workspace. Remaining gaps: production paper submit/cancel verification, durable paper account writer validation, production account repository, and current backend test run.

## 2026-06-14 - ProChart stream label contract

ProChart now distinguishes true stream-backed `Live` data from fresh non-stream `Current` typed contract data. Production stream validation, alerting, and durable realtime source evidence remain blockers.

## 2026-06-14 Local auth trader-ID uniqueness guard

- Event: `local_auth_user_store_rejects_duplicate_trader_ids`.
- Local auth user storage now rejects duplicate non-empty `trader_id` values on create/update/initial seed reconciliation, matching duplicate paper-account rejection.
- This is partial local isolation evidence only. Production database constraints/migrations, durable account repositories, and current validation remain pending.
- Real live trading remains BLOCKED.

## 2026-06-14 Trader account scope smoke duplicate trader-ID check

- Event: `trader_account_scope_smoke_duplicate_trader_id_check_added`.
- The safe account-scope smoke artifact now includes `trader_ids_unique_across_users` and `duplicate_trader_ids` so duplicate trader ownership can be detected before production promotion.

## 2026-06-14 Incomplete backend trader context fail-closed

- Event: `backend_trader_context_incomplete_scope_fail_closed`.
- `/api/v2` trader context metadata now treats authenticated sessions as account-specific only when both `trader_id` and `paper_account_id` exist.
- `/trade` activity filtering coverage now expects account rows to be withheld when envelope-level account scope does not match the active trader and paper workspace.
- This is contract hardening only; production repositories, migrations, durable credential vault integration, and current validation remain pending.

## 2026-06-14 SQLAlchemy auth user-store trader-ID index

- Event: `sqlalchemy_auth_user_store_trader_id_index_added`.
- The explicit SQLAlchemy auth-store auto-create schema now includes unique `trader_id` storage in addition to unique email and paper-account ownership; SQLite local auto-create stores get a compatibility column/index when missing.
- This is partial multi-trader isolation metadata only. Production migrations/provisioning, auth/session hardening, and validation remain pending.

## 2026-06-14 ProChart native kline history fallback

- Event: `prochart_native_kline_history_fallback_added`.
- Browser-side native Binance public kline frames now maintain bounded in-session candle history for `/chart/:symbol` when typed candle history is unavailable.
- This does not close realtime data blockers: durable backend stream validation, derivatives realtime sources, and full production smoke remain pending.

## 2026-06-14 SQLAlchemy trader account ownership index

- Event: `sqlalchemy_trader_account_ownership_index_added`.
- The explicit SQLAlchemy trader account repository auto-create path now adds a non-unique `trader_id` ownership index and keeps `paper_account_id` unique.
- This improves multi-trader repository shape but does not replace production migrations, writer validation, or current isolation smoke evidence.

## 2026-06-14 Viewer scope and exchange-link role boundary

- Event: `viewer_exchange_link_role_boundary_hardened`.
- `/api/auth/register` now creates viewer accounts without trader/paper scope. `/api/accounts/me/exchange-accounts` requires complete scope plus exact role `trader`; stored exchange metadata remains normalized to the owning trader/paper scope and forced read-only/live-disabled.
- This prevents viewer self-registration or scoped-viewer metadata from creating Binance links before admin approval. Production auth/session hardening remains pending.

## 2026-06-14 Dashboard trader-scoped signal preference

- Event: `dashboard_trader_scoped_signal_preference_added`.
- `/dashboard` now uses `/trade`'s trader-scoped signal state for visible signal direction/confidence/entry/target and treats broad prediction rows as aggregate market context.
- Durable trader-scoped signal writers and current validation remain pending.
- This is validation scaffolding only. The smoke runner and full validation queue were not executed.

## 2026-06-14 Typed indicator source copy hardening

- Event: `typed_indicator_source_copy_hardened`.
- `/api/v2/market/{symbol}/indicators` unavailable states now use `typed_indicator_repository` and `Typed indicator source is unavailable` to avoid presenting current typed API/repository indicators as production realtime streams.
- This does not close production realtime validation or derivatives-source blockers.

## 2026-06-14 update - explicit paper-action trader scope

| Area | Status | Notes |
|---|---|---|
| `/api/v2/orders/paper` local staging scope | PARTIAL, pending validation | Backend now requires explicit `trader_id` and `paper_account_id` in the paper staging request to match the authenticated session before any local paper repository write is accepted. This is a defense-in-depth multi-trader guard and does not enable exchange submission. Current validation rerun remains pending. |
| `/api/v2/orders/preview` scope evidence | PARTIAL, pending validation | Preview responses now echo request scope and include `request_scope_matches_session` plus a request-scope risk check. Preview remains non-mutating and may still return estimates without enabling submit unless scoped paper-action policy passes. |

## 2026-06-14 update - liquidation stream status exposure

| Area | Status | Notes |
|---|---|---|
| `/api/v2/market/{symbol}/derivatives` liquidation stream status | PARTIAL, pending validation | The derivatives contract now exposes source-labeled `liquidation_stream_status` and `liquidation_levels` from the existing liquidation runtime status when available. This does not fill `liquidations_1h` or `liquidations_24h` and does not claim a durable production liquidation repository. |
| 1h/24h liquidation totals | BLOCKED | Still require a verified durable liquidation source/repository or current production derivatives evidence. Missing states remain visible. |
| Exchange comparison | BLOCKED | Still source-pending. |

## 2026-06-14 update - liquidation stream freshness guard

| Area | Status | Notes |
|---|---|---|
| Liquidation runtime status freshness | PARTIAL, pending validation | `liquidation_stream_status` now includes `lag_ms` and `stale`; `/market/:symbol` only presents the stream as active when the runtime status is fresh. |

## Phase 15 account ownership hardening - 2026-06-15

| Area | Contract surface | Current status | Remaining gap |
|---|---|---|---|
| Multi-trader exchange metadata | `/api/accounts/me/exchange-accounts` | PARTIAL: metadata-only link rejects extra credential fields and private-looking labels/types; safe user payloads remain trader/paper scoped. | Durable backend credential vault, read-only permission probe, production account repository migration, and validation rerun remain pending. |
| Multi-trader exchange metadata removal | `/api/accounts/me/exchange-accounts/{account_id}` | PARTIAL: removal now requires backend-confirmed trader role, matching trader/paper scope, read-only metadata, and live-disabled account metadata. | Durable audit and production validation for account-link lifecycle remain pending. |

## Phase 15 ProChart source/freshness hardening - 2026-06-15

| Area | Contract surface | Current status | Remaining gap |
|---|---|---|---|
| ProChart symbol source | `/api/v1/chart/symbols` | PARTIAL: response now includes source, source_type, endpoint, timestamp, received_at, lag_ms, stale, missing_fields, warnings, read-only mode, and no exchange mutation flags. | Production stream validation, alerting, and durable realtime evidence remain pending. |
| ProChart overlay source | `/api/v1/chart/coinank/{symbol}/{timeframe}` | PARTIAL: unavailable/stale CoinAnk overlay states are structured and source-labeled. | Durable CoinAnk/derivatives stream health, freshness SLA, and missing-series remediation remain pending. |

## Phase 15 V2 trader context scope hardening - 2026-06-15

| Area | Contract surface | Current status | Remaining gap |
|---|---|---|---|
| V2 trader context exchange accounts | V2 envelopes with `trader_context` | PARTIAL: exchange account metadata now reuses the scoped safe-user filter, excluding unscoped, unsafe, or live-enabled account records from trader-facing V2 context. | Validation rerun, durable production account repository, and credential-vault proof remain pending. |

## Phase 15 market-detail signal scope hardening - 2026-06-15

| Area | Contract surface | Current status | Remaining gap |
|---|---|---|---|
| Account-specific signal visibility | `/market/:symbol` via `useMarketDetail` | PARTIAL: account-specific signals are now withheld when no backend-confirmed trader/paper scope exists, and still require matching trader/paper scope when signed in. | Validation rerun and broader Signals/AI route cleanup remain pending. |

## Phase 15 signals panel account-scope hardening - 2026-06-15

| Area | Contract surface | Current status | Remaining gap |
|---|---|---|---|
| Trader-facing realtime signal rows | `/signals` via `RealtimeSignalVisibilityPanel` | PARTIAL: trader variant now shows public/shared signal rows plus rows matching the signed-in trader/paper scope; other account-specific rows are withheld with a visible withheld-count note. | Durable scoped signal repository, stream validation, and full Signals/AI redesign remain pending. |
