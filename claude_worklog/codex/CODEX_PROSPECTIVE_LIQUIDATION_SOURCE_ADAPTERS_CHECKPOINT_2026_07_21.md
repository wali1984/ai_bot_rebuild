# Prospective liquidation source-adapter checkpoint — 2026-07-21

## Immutable checkpoint

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Source-family commit: `6d9f2400fb62f6bbb648852a1bddc6afea528ec8`
- Parent checkpoint: `a0ba078dcfb5e70cf6e248887294e1bff0e8090a`
- Remote head verified equal to the source-family commit after push.
- Files committed: 7
- Diff: 1,485 additions, 25 deletions
- Physical targeted test functions: 102
- Expanded targeted cases: 201 passed, 0 failed
- Independent remediation review: 4 passed, 0 failed, 0 blocking
- Ruff lint/format and Python compilation: passed
- Provider calls: 0
- Redis/runtime writes, service restarts, or deployments: 0
- Exchange orders, cancellations, leverage changes, margin-mode changes,
  transfers, or live-execution mutations: 0

## What this family establishes

This family converts exact, caller-observed Redis bytes into the typed inputs
of the prospective liquidation-surface model. Producer timestamps remain
source metadata; the caller's read clock is the causal availability clock.
The SHA-256 of the exact bytes, including their original whitespace, is the
source lineage identifier.

The four accepted evidence paths are:

1. Finalized Binance USD-M candles from either
   `v2:market:ohlcv:binance:{symbol}:{timeframe}` or
   `v2:market:ohlcv_closed:binance:{symbol}:{timeframe}`.
2. Binance USD-M mark price from `v2:market:mark_price:{symbol}`, with the
   tightly enumerated funding/premium-index fallback
   `v2:market:funding:{symbol}`.
3. CoinAnk trading-pair OI kline evidence from
   `latest:coinank:open_interest:{symbol}:{source_timeframe}`.
4. The complete authenticated Binance USD-M leverage-bracket curve from the
   account/environment-scoped signed evidence cache.

No adapter calls a provider or writes Redis.

## Exact Binance candle contract

Every row must bind all of the following:

- exact uppercase symbol and requested timeframe
- `exchange=binance`
- `venue=binance_usdm`
- `product_type=USD-M`
- all three finality aliases plus `feature_eligible=true`
- an enumerated native source (`binance_wss`, `binance_rest`) or a complete
  canonical lower-timeframe resampler identity
- valid raw-payload SHA-256
- `open < close <= event <= ingested <= source_available <= consumer_observed`
- exact OHLC values and optional quote/taker-buy quote volume

A resampled candle additionally proves its source timeframe and exact number
of constituent candles. The model independently verifies duration, boundary,
continuity, OHLC geometry, positivity, and finality.

## Exact Binance mark contract

The native WebSocket path requires:

- exact symbol, `venue=binance_usdm`, and `product_type=USD-M`
- schema `binance_usdm_mark_price_wss_v1`
- source `binance_usdm_wss_mark_price_all_symbols`
- transport `websocket_primary`
- exact key identity, positive mark price, and causal event/source/read clocks

The only REST fallback accepted is the enumerated source
`binance_public_rest_premium_index_fallback`, transport `rest_fallback`, and
endpoint `/fapi/v1/premiumIndex`. Prefix matching, missing symbols, generic
`binance` assertions, and spot identity are rejected.

The surface still requires at least two validated mark observations to derive
an observed adaptive cadence. A latest-only Redis key must therefore be
supplemented by bounded, receipt-preserving mark history in the producer
family; one observation cannot make the surface trainer-eligible.

## CoinAnk Plan3-safe OI contract

The operator's Plan3 subscription can access the lower-plan trading-pair OI
kline route `/api/openInterest/kline`; no Plan4 liquidation map or heatmap is
called or accepted. The payload must prove:

- family `open_interest` and internal endpoint identity `openInterest_kline`
- exact top-level Binance/symbol/timeframe identity
- exact request parameters for Binance, the same symbol/timeframe, and
  `productType=SWAP`
- a successful CoinAnk response envelope
- a pre-request `request_started_at_ms`
- post-response `ts_ms` no later than the consumer observation
- each retained period satisfies `begin + duration < request_started_at_ms`

Equality at the request-start boundary is not final. The endpoint's documented
OHLC series is position quantity, so `close` is labeled `base_asset`, not
quote notional and not an unproven exchange contract count. The official
CoinAnk documentation describes this as the trading-pair position-quantity
kline: <https://api-cn.doc.coinank.com/api-394180358>.

The adapter returns only the latest continuous finalized suffix. Missing,
failed, stale, malformed, wrongly scoped, or clockless CoinAnk evidence is
unavailable; it is never restamped or fabricated.

## Source-timeframe adaptivity and rate-limit implication

The surface timeframe and OI source timeframe are now distinct, explicit
fields. A causal 5-minute OI series may support a 1-minute price surface with
`open_interest_temporal_resolution_coverage=0.2`; a finer OI series on a
coarser surface is capped at coverage `1.0`. Mixed OI source timeframes inside
one window fail closed.

This makes a rate-limit-safe producer design possible without false relabeling:
one venue/symbol 5-minute OI request can be reused across the five price
surface timeframes while each output declares the true OI resolution. For the
currently observed 159-symbol training universe, revisiting one OI lane per
symbol within 10 minutes implies 15.9 requests/minute, rather than 79.5
requests/minute for five separate timeframe requests. This is a planning
calculation, not an implemented scheduler or a market-admission threshold.

## Authenticated full leverage-bracket curve

`read_authenticated_bracket_surface_evidence` now:

- reads only the exact account/environment-scoped Redis key
- accepts exact text/bytes only
- caps raw evidence at 1 MiB and the curve at 1,024 rows as computational
  safety limits, not market thresholds
- validates schema, producer, endpoint, symbol, account/environment binding,
  content checksum, HMAC, canonical curve, and all producer clocks
- records one clock after Redis GET and a second clock after authentication
- rejects clock regression, source availability after observation, and expiry
  at either consumer clock
- contains JSON/canonicalization recursion failures
- returns typed `LeverageBracket` observations directly

The observation `available_at_ms` is the conservatively rounded-up
post-validation clock. Expiry is rounded down because it is exclusive. The
old forgeable public adapter that trusted a mapping containing
`evidence_authenticated=true` was removed. The model later enforces bracket
`available_at <= surface_as_of`; historical surfaces cannot consume a current
key first observed in their future.

## Resource and authority boundaries

- Raw source bytes: hard computational maximum 16 MiB
- Parsed candle/OI rows: hard computational maximum 250,000
- Model-request source rows: caller-configured bound with the same 250,000
  hard maximum
- Timeframe durations and epoch-millisecond strings: signed-64-bit bounds
- Recursive/unverified `authority` or `*_authority` claims: rejected
- Nonfinite JSON/numeric values: rejected
- These are crash/memory/integer controls, not static market thresholds.

Model outputs remain `trainer_authority=false`, `available_at=null`, and
`postcommit_receipt_bound=false`. Source adaptation alone cannot authorize a
trainer feature.

## Bounded source-map evidence

The read-only mapping pass inspected 22 implementation/config artifacts, 13
test files, 8 external routes, 35 Redis/data-plane key patterns, and 253 named
fields/positions across 18 contract surfaces. It made no runtime/provider
calls and changed no files.

The 201 expanded cases cover exact-byte hashes, strict JSON, resource limits,
symbol/key/venue/product identity, candle finality and resampling, mark source
enumeration, CoinAnk request and response binding, request-start finality,
Plan4 rejection, OI continuity/unit/source-timeframe resolution, signed
bracket HMAC/account binding, full-curve delivery, read/validation clocks,
staleness, recursion, rounding, and tamper rejection.

## Known runtime blockers deliberately not hidden

1. The active runtime CoinAnk producer is an untracked/ignored workspace file
   absent from this branch. Its observed SHA-256 is
   `d794b2258dcb02a4652f0e17137241d54f43f827b8a27f8230345d136d1f5c35`.
   It does not persist `request_started_at_ms`, so the strict adapter must
   reject current real payloads.
2. The active canonical candle and mark publishers do not yet emit the new
   exact `binance_usdm`/`USD-M` fields. They must be repaired and tested before
   this adapter family can be deployed.
3. The latest-only mark key does not provide the two-observation history
   required for adaptive cadence.
4. No surface publication/readback receipt exists yet.
5. No trainer feature or missingness mask is wired yet.

These are the next implementation families. They do not justify weakening
PIT, venue, finality, or authentication rules.

## Files committed

- `v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py`
- `v2/backend/app/services/liquidation_surface/__init__.py`
- `v2/backend/app/services/liquidation_surface/model.py`
- `v2/backend/app/services/liquidation_surface/source_adapters.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_model.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py`
- `v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py`

## Verification commands

```text
.venv/bin/ruff format --check <8 targeted implementation/test files>
.venv/bin/ruff check <8 targeted implementation/test files>
python3 -m py_compile <5 targeted implementation files>
.venv/bin/pytest -q \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py
git diff --cached --check
git commit -m "feat(liquidation): bind causal source evidence"
git push origin codex/liquidation-levels-bridge-remediation-20260721
git ls-remote --heads origin codex/liquidation-levels-bridge-remediation-20260721
```

## Next component family

Repair and version the producer ABI before publication:

1. persist CoinAnk request-start and response-observation clocks without
   calling any Plan4 route;
2. add exact USD-M product identity to canonical candle and mark outputs;
3. retain bounded exact mark history with read receipts;
4. add producer-to-adapter contract tests proving current runtime payloads are
   accepted;
5. then implement canonical surface publication plus exact readback receipts.

No service restart or runtime release is authorized by this checkpoint alone.
