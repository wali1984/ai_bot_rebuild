# V2 Top-10 Binance Dashboard Data Feed Report

GO/NO-GO: V2_TOP10_BINANCE_DASHBOARD_DATA_FEED_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT call authenticated endpoints (no credential required for the
public ticker URLs). It does NOT synthesize ticker rows.

## Scope

Implements the Binance market-baseline portion of the Top-10 operator
dashboards contracted earlier:

1. Binance Spot 12h Volume Leaders        (spot_volume_12h)
2. Binance Futures 12h Volume Leaders     (futures_volume_12h)
3. Binance Spot 12h Most Traded           (spot_trades_12h)
4. Binance Futures 12h Most Traded        (futures_trades_12h)
5. Binance Spot 12h Volatility Leaders    (spot_volatility_12h)
6. Binance Futures 12h Volatility Leaders (futures_volatility_12h)

Alternative-data dashboards (Nansen smart-money, LunarCrush social
momentum, Arkham future-state, etc.) remain disabled at the dashboard
layer until Codex passes the per-provider clients. The Nansen and
LunarCrush clients were just emitted with their own GO_NO_GO packets;
their dashboard wiring is a separate operator decision.

## Files added

### v2/backend/app/services/alternative_data/binance_top10_dashboards.py

- Allowed Redis-write set (seven keys, all under
  `v2:dashboards:binance_top10:`):
  - `v2:dashboards:binance_top10:spot_volume_12h`
  - `v2:dashboards:binance_top10:futures_volume_12h`
  - `v2:dashboards:binance_top10:spot_trades_12h`
  - `v2:dashboards:binance_top10:futures_trades_12h`
  - `v2:dashboards:binance_top10:spot_volatility_12h`
  - `v2:dashboards:binance_top10:futures_volatility_12h`
  - `v2:dashboards:binance_top10:heartbeat`
- `_safe_redis_set` refuses any key outside this set, so the module
  cannot accidentally write to `v2:market:*`, `v2:altdata:*`, or any
  legacy namespace.
- Module constants document the source endpoints:
  - SPOT_ROLLING_TICKER_URL =
    `https://api.binance.com/api/v3/ticker?windowSize=12h`
  - FUTURES_24H_TICKER_URL =
    `https://fapi.binance.com/fapi/v1/ticker/24hr`
- `fetch_ticker(url, http_get=..., timeout=...)` returns a
  (source_status, rows) tuple. Source-status mapping is explicit:
  - 200 → `API_OK` (with rows)
  - 429 → `API_RATE_LIMITED_429`
  - 403 → `API_FORBIDDEN_403`
  - other status / `ConnectionError` / generic exception →
    `API_NETWORK_ERROR`
  - `TimeoutError` → `API_TIMEOUT`
  - 200 with non-list/non-dict body → `API_PARSE_ERROR`
- `filter_symbols(rows, quote_filter)` drops non-matching pairs so
  USDT-only ranking is the default (avoids BNB/BTC quote spam).
- `rank_top_n(rows, metric_field, metric_transform, top_n)` is the
  ranking primitive. Volume and trade-count use `quoteVolume` and
  `count` directly. Volatility uses `abs(priceChangePercent)` via
  the `_abs_price_change` transform.
- `build_dashboards(spot_rows, futures_rows, ...)` builds all six
  dashboard payloads from already-fetched ticker rows. Each payload
  declares both `window_size_requested` ("12h") and
  `window_size_actual` so consumers can see when Binance's futures
  endpoint forces a 24h window.
- `build_heartbeat_payload(...)` and `write_heartbeat_payload(...)`
  publish a freshness pulse at
  `v2:dashboards:binance_top10:heartbeat` with TTL 180s.

### Rolling-window asymmetry

Binance Spot exposes `GET /api/v3/ticker?windowSize=12h` so the spot
dashboards use a true 12h rolling window. Binance Futures only
publishes a 24h rolling ticker at `GET /fapi/v1/ticker/24hr`, so the
futures dashboards consume that 24h ticker and surface the actual
window via `window_size_actual="24h"` (with
`window_size_requested="12h"`). No per-symbol kline aggregation is
performed in this packet; that is a future enhancement requiring
heavier per-symbol weight and a per-call rate limiter.

### v2/backend/app/cli/v2_top10_binance_dashboard_feed.py

- Bounded one-shot. No --loop flag. Each invocation:
  1. Calls the spot rolling ticker once (no auth).
  2. Calls the futures 24h ticker once (no auth).
  3. Builds the six dashboards.
  4. Publishes each dashboard payload to its Redis key.
  5. Publishes a heartbeat key.
  6. Writes a summary status JSON to the worklog and two public
     mirrors.
- CLI flags:
  - `--quote-filter` (default `USDT`; pass empty string to disable).
  - `--top-n` (default 10).
  - `--timeout-seconds` (default 10).
- Per-provider failure isolation: if spot succeeds and futures fails
  (or vice versa), the failing dashboards still publish, with
  `rank_count=0` and the failing `source_status`. The dashboards
  that succeed publish normally. The heartbeat reflects both
  statuses.

### v2/backend/tests/integration/cli/test_v2_top10_binance_dashboard_feed.py

20/20 tests pass. Coverage includes:

- `_safe_redis_set` refuses anything outside the allowed seven keys.
- `filter_symbols` keeps only USDT pairs (BNB / BTC pairs dropped).
- Volume / trade-count / volatility ranking returns the expected
  ordering, including absolute-value transform for volatility.
- `fetch_ticker` maps 200 / 429 / 403 / other status, TimeoutError,
  and ConnectionError to the declared source-status sentinels.
- `build_dashboards` produces all six dashboards with the safety
  fields populated.
- Spot dashboards advertise `window_size_actual="12h"`; futures
  dashboards advertise `window_size_actual="24h"`.
- `publish_dashboards` writes only to the allowed-key set.
- Heartbeat payload includes the safety fields and the
  dashboard_published list.
- CLI end-to-end with FakeRedis + fake http: all 6 dashboards plus
  heartbeat appear in the store; only allowed keys are written.
- CLI handles provider unreachable without crashing: rc=0,
  `source_status` reflects `API_NETWORK_ERROR` for both venues,
  no fabricated rows.
- top_n truncation when more than 10 rows are eligible.
- Partial provider failure (spot OK, futures 429): spot dashboards
  publish populated rows, futures dashboards publish with
  `rank_count=0` and the failing source_status, heartbeat still
  published.
- No torch import. No pickle deserialization. No exchange-mutation
  verb in either module source (piecewise composition check).

## Behavior summary

- Authentication: none. The public ticker endpoints require no key
  and no signature.
- Endpoints per run: 2 (one spot, one futures).
- Per-symbol cooldown / cache TTL: not needed at this layer; each
  invocation pulls fresh ticker rows. Run cadence is operator-
  controlled.
- Rate-limit policy: a single weight-40 spot call plus a single
  weight-40 futures call per invocation, well within the documented
  free Binance public limits (1200 weight/minute spot).
- Top-N: default 10 per dashboard.
- Quote filter: default `USDT`.

## Allowed Redis writes

Only the seven keys in `ALLOWED_KEYS`. The safe-set boundary in
`_safe_redis_set` refuses anything else. Tests prove this directly
(`test_safe_redis_set_refuses_non_dashboard_keys`).

## Safety invariants

- gate = blocked_human_only
- symbols_real = []
- approves_real = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- writes_legacy_redis = false
- writes_exchange_orders = false
- no_synthetic_market_data = true
- no_torch_imported = true
- no_pickle_loaded = true
- no_legacy_filesystem_modified = true
- credential_in_payload = NEVER
- auth_required_for_source_endpoints = false

## Runtime impact

The CLI is operator-invocable. It is NOT yet wired into the
continuous remediation governor's fail-blocking process list; that
remains a separate operator/Codex decision. The CLI is independent
of the soak, the liquidation WSS daemon, the legacy log observer,
and the symbol-universe automation; it does not touch any of them.

The V2 paper/shadow runtime was not paused or reconfigured by this
packet.

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not enable alternative-data dashboards (Nansen / LunarCrush /
  Arkham future-state / etc.) at the dashboard layer.
- Does not modify legacy.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not synthesize ticker rows.
- Does not commit any credential.
- Does not create approval tokens.
- Does not call authenticated endpoints.
- Does not start the policy architecture port.
- Does not claim checkpoint compatibility or policy architecture
  parity.

## Outputs

- claude_worklog/final_readiness/v2_top10_binance_dashboard_feed/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_top10_binance_dashboard_feed/latest/V2_TOP10_BINANCE_DASHBOARD_FEED_REPORT.md
- v2/backend/app/services/alternative_data/binance_top10_dashboards.py (added)
- v2/backend/app/cli/v2_top10_binance_dashboard_feed.py (added)
- v2/backend/tests/integration/cli/test_v2_top10_binance_dashboard_feed.py (added; 20/20 pass)
