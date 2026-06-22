# Codex Review: V2 Top-10 Binance Dashboard Data Feed

Generated: `2026-05-18T04:56:00Z`

GO/NO-GO: `V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_CODEX_PASS`

## Decision

Codex passes the Binance top-10 dashboard data feed at the dashboard/data-feed scope. The implementation uses public no-auth Binance market-data endpoints only, writes through a narrow V2 dashboard Redis allowlist, exposes the futures 24h window asymmetry honestly, and does not affect trading gates.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, external feed production use, or legacy shutdown.

## Evidence Reviewed

Reviewed source and packet artifacts:

- `v2/backend/app/services/alternative_data/binance_top10_dashboards.py`
- `v2/backend/app/cli/v2_top10_binance_dashboard_feed.py`
- `v2/backend/tests/integration/cli/test_v2_top10_binance_dashboard_feed.py`
- `claude_worklog/final_readiness/v2_top10_binance_dashboard_feed/latest/`

Note: the implementation packet is stored under `v2_top10_binance_dashboard_feed/latest`, while this Codex review is written under the requested `v2_top10_binance_dashboard_data_feed/latest/codex_review` path. The packet GO/NO-GO itself uses `V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_READY`.

## Endpoint Scope

The feed uses exactly two public no-auth market-data endpoints:

- Spot rolling ticker: `https://api.binance.com/api/v3/ticker?windowSize=12h`
- Futures 24h ticker: `https://fapi.binance.com/fapi/v1/ticker/24hr`

No private, account, authenticated, signed, order, leverage, margin, listen-key, or user-data endpoint was found in the reviewed source.

`fetch_ticker()` calls the configured URL with empty headers and maps provider outcomes to explicit statuses: `API_OK`, `API_RATE_LIMITED_429`, `API_FORBIDDEN_403`, `API_TIMEOUT`, `API_PARSE_ERROR`, or `API_NETWORK_ERROR`.

## Dashboard Semantics

The six Binance dashboards are built from fetched ticker rows:

- Binance Spot 12h Volume Leaders
- Binance Futures 12h Volume Leaders
- Binance Spot 12h Most Traded
- Binance Futures 12h Most Traded
- Binance Spot 12h Volatility Leaders
- Binance Futures 12h Volatility Leaders

Spot panels declare:

- `window_size_requested=12h`
- `window_size_actual=12h`

Futures panels declare:

- `window_size_requested=12h`
- `window_size_actual=24h`

This satisfies the futures-window honesty requirement. The feed does not silently label futures 24h ticker data as true 12h data.

No synthetic ticker rows are produced. If one provider side fails, its dashboards publish `rank_count=0` with the failure `source_status`, while the successful side can still publish populated rows.

## Redis Boundary

The service safe-set boundary allows only these Redis keys:

- `v2:dashboards:binance_top10:spot_volume_12h`
- `v2:dashboards:binance_top10:futures_volume_12h`
- `v2:dashboards:binance_top10:spot_trades_12h`
- `v2:dashboards:binance_top10:futures_trades_12h`
- `v2:dashboards:binance_top10:spot_volatility_12h`
- `v2:dashboards:binance_top10:futures_volatility_12h`
- `v2:dashboards:binance_top10:heartbeat`

The tests prove `_safe_redis_set` refuses old Redis keys such as `prediction:*` and unrelated V2 namespaces. A live Redis scan during this review found no current `v2:dashboards:binance_top10:*` keys, so no unexpected dashboard key was present.

## Public Payloads

The CLI defines worklog and public status output paths:

- `claude_worklog/final_readiness/v2_top10_binance_dashboard_feed/latest/v2_top10_binance_dashboard_feed_status.json`
- `v2/frontend/public/operator_runtime/v2_top10_binance_dashboard_feed/latest/v2_top10_binance_dashboard_feed_status.json`
- `v2/frontend/public/v2_top10_binance_dashboard_feed/latest/operator_dashboard_payload.json`

Those public payload files were not present at review time, which is acceptable for this source/test review because the CLI is one-shot/operator-invocable and was not run against live Binance during this Codex review. The output contract is present in the CLI and test-covered.

## Runtime Governor

The standing continuous remediation governor was refreshed:

- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- V2/remediation processes: `13/13`
- V2 Redis namespaces non-empty: `true`
- 6h soak remains passed: `true`
- full observation builder payload fresh: `true`
- full observation state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- full observation dims: `BTCUSDT=148`, `ETHUSDT=148`, `SOLUSDT=143`
- checkpoint task count: `2`
- premature policy architecture implementation: `false`
- fail blockers: none

## Safety

Codex verified:

- no raw secret values in reviewed Binance dashboard source/report/public paths;
- no old Redis write path in reviewed source;
- no exchange order placement/cancel/modify, leverage, or margin surface in reviewed source/tests;
- no live/canary/shutdown/Redis-trim approval drift in reviewed artifacts;
- dashboard payloads carry `gate=blocked_human_only` and `symbols_real=[]`;
- dashboard feed cannot alter trading gates.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Validation

- Focused tests: `20 passed`.
- Raw secret-value scan: PASS.
- Private/auth/trading endpoint scan: PASS.
- Redis allowlist scan/test: PASS.
- Exchange mutation scan: PASS.
- Runtime governor refresh: PASS.

## Final Decision

`V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_CODEX_PASS`
