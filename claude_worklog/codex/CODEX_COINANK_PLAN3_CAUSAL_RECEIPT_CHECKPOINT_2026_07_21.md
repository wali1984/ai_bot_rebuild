# CoinAnk Plan3 Causal Receipt Checkpoint — 2026-07-21

## Checkpoint identity

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Receipt implementation commit: `ea92e727ae`
- Request-boundary regression commit: `7ac69cc3d0`
- Provenance baseline parent: `678eb2058d`
- Service/provider/Redis calls during implementation: 0
- Service restarts: 0
- Live trading/order/leverage/margin behavior changed: 0

The active CoinAnk producer can now emit a causal request receipt that the
strict prospective-liquidation OI adapter accepts. This checkpoint does not
yet enable a surface publisher or trainer feature.

## Evidence counts

- Production/helper files changed or added: 2
- Test files added: 1
- Receipt fields added to producer envelopes: 2
  - `request_started_at_ms`
  - `response_observed_at_ms`
- Existing persistence clock retained: `ts_ms`
- Provider request parameter map retained exactly: `request_parameters`
- Network request sites wrapped: 1
- Canonical flat-snapshot construction sites replaced: 2
- Plan4/liquidation-map routes registered after change: 0
- Raw session-header value logging sites after change: 0
- New receipt test functions: 12
- Combined targeted tests: 267 passed, 0 failed
- Defects remaining in this receipt family: 0
- Remaining producer-coverage defects: 1 (all-universe 5m OI cadence)

## Clock sequence

```text
global rate gate admits call
  -> request_started_at_ms
  -> requests.Session.get(...)
  -> response_observed_at_ms
  -> response semantic validation
  -> persistence-attempt ts_ms
  -> Redis consumer-observation receipt (future publisher family)
```

The request helper captures the start clock immediately before network I/O and
the response clock immediately after `Session.get` returns. Requests loads the
response body by default before returning. Persistence validates:

```text
0 < request_started_at_ms <= response_observed_at_ms <= ts_ms
```

Booleans, non-integers, missing clocks, non-positive clocks, signed-64-bit
overflow, clock regression, and a persistence clock earlier than the response
all fail before the first file or Redis write.

## Finality result

The strict OI adapter admits a row only when:

```text
row_begin + source_timeframe_duration < request_started_at_ms
```

It deliberately does not use the later response or persistence clock for bar
finality. A dedicated regression places a 5m bar close between request start
and response observation; that row is excluded, while the prior closed row is
accepted. This closes the network-latency look-ahead window.

## Exact flat envelope

The active canonical flat key remains:

```text
latest:coinank:{family}:{symbol}:{interval}
```

For the prospective surface, the accepted identity is exactly:

```text
latest:coinank:open_interest:{BINANCE_USDM_SYMBOL}:5m
```

Its relevant payload fields are now:

```json
{
  "ts_ms": 1800000600031,
  "timestamp": 1800000600031,
  "request_started_at_ms": 1800000600001,
  "response_observed_at_ms": 1800000600021,
  "symbol": "BTCUSDT",
  "exchange": "Binance",
  "family": "open_interest",
  "endpoint": "openInterest_kline",
  "endpoint_variant": null,
  "request_parameters": {
    "exchange": "Binance",
    "symbol": "BTCUSDT",
    "interval": "5m",
    "productType": "SWAP",
    "size": 3
  },
  "interval": "5m",
  "data": {
    "success": true,
    "code": "1",
    "data": []
  }
}
```

The example illustrates schema only; tests use non-empty closed rows. The
producer never sets trainer authority. The eventual publisher must still hash
the exact Redis bytes and issue a separate consumer-observation receipt.

## Plan3 and heatmap boundary

The directly registered `/api/liqMap/getLiqHeatMapSymbol` route and all runtime
references to it were removed. Ambient `COINANK_ENABLE_PLAN4` cannot restore
it; the active producer is pinned to `False`. This follows the operator's
subscription boundary even though the public documentation labels the symbol
list separately from actual liquidation-map data.

The Plan3 funding-rate heatmap route remains available to the general CoinAnk
ingestor. It is not a prospective liquidation-level source, and the strict
surface adapter cannot consume it. No forced-liquidation stream, funding
heatmap, liquidation heatmap, or map-symbol list can create estimated open
position liquidation levels.

Relevant official contracts:

- OI kline: <https://api-int.doc.coinank.com/api-394180263>
- OI quantity semantics: <https://api-cn.doc.coinank.com/api-394180358>
- CoinAnk error code `-2` for excessive request frequency:
  <https://api-int.doc.coinank.com/>
- Removed liquidation heatmap-symbol route:
  <https://api-int.doc.coinank.com/api-394180274>

No numerical rate entitlement was inferred from search results. The existing
global token bucket and critical endpoint shares were left unchanged in this
receipt slice.

## Credential-safety repair

The debug preflight no longer renders `dict(SESSION.headers)`, which could
contain the API key. It logs only normalized header names and a boolean
`apikey_present` indicator. A scoped secret-literal scan found zero committed
key, token, password, bearer, or authorization values.

## Verification commands

```text
PYTHONPATH="$PWD/v2/backend:$PWD" \
  '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/pytest' -q \
  v2/backend/tests/unit/services/altdata/test_coinank_receipts.py \
  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py \
  v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py \
  v2/backend/tests/unit/cli/test_v2_binance_public_metadata_websocket_primary.py
```

Result: `267 passed in 0.40s`, with one pre-existing `pytest_asyncio`
configuration deprecation warning.

Additional checks:

```text
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/ruff' check \
  v2/backend/app/services/altdata/coinank_receipts.py \
  v2/backend/tests/unit/services/altdata/test_coinank_receipts.py
'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m compileall -q \
  v2/backend/app/services/altdata/coinank_receipts.py \
  v2/legacy_owned_runtime/ingest/live_coinank.py
git diff --check
git diff --cached --check
```

All passed. The assigned second-agent review did not return a report inside the
bounded window, so it is not counted as evidence.

## Remaining all-universe blocker

`openInterest_kline` still inherits the deep-symbol default cap and generic
multi-timeframe rotation. That does not prove a fresh reusable 5m OI lane for
every training-universe symbol within the available request budget. The next
family must prioritize exactly one 5m OI lane per universe symbol, derive its
per-visit batch from observed endpoint cadence and the bounded freshness SLA,
rotate fairly across failures, retain remaining capacity for non-surface
CoinAnk intervals, and publish honest partial-coverage evidence when the
measured rate cannot meet the plan.
