# External Feature Source Decision: ccxt_ohlcv

Target dims (within `unified_features` 1430-dim slice): **10**

## Why current V2 cannot produce ccxt_ohlcv

- Legacy `ccxt_ohlcv` is a secondary-exchange OHLCV slice (10 dims)
  derived from a CCXT-style alternative-exchange feed.
- V2 keeps the native Binance live klines as the canonical OHLCV path;
  running a parallel CCXT feed has not been approved.
- No `v2:market:ccxt_ohlcv` namespace exists today.

## Possible V2-native source

`OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV`. Candidates
(operator selects):

- ccxt against KuCoin (V2 already ingests KuCoin live trades; OHLCV via
  ccxt can be layered).
- ccxt against Binance.us / Bybit / OKX (operator-selected secondary
  exchange).
- CoinAPI OHLCV (V2 already uses CoinAPI for some price data; could be
  extended).

V2 implementation outline, **only if approved**:

1. Extend V2 ingestor registry to publish
   `v2:market:ccxt_ohlcv:{exchange}:{symbol}:{timeframe}`.
2. Add focused projection in `full_observation_builder` for the 10-dim
   slice.
3. Codex review pair before adoption.
4. Continue treating native Binance `v2:market:*` as the canonical OHLCV
   source; `ccxt_ohlcv` is shadow only.

## Required credentials / API

- `CONDITIONAL` — public CCXT OHLCV feeds are available without
  credentials, but private/rate-limited tiers may require API keys.
- Credential storage: `.local_secrets/` (gitignored; **never** embedded
  in payloads).
- Rate-limit decision required.
- **No raw credentials in this packet.**

## Optional for checkpoint compatibility

`OPTIONAL_FOR_CHECKPOINT_COMPATIBILITY_IF_NATIVE_BINANCE_OHLCV_PRESENT`.
V2's native Binance OHLCV plus the `technical_analysis` and
`binance_klines` sub-families already carry the canonical price-history
signal for paper inference. Final answer depends on the operator-provided
checkpoint sidecar metadata.

## Operator decision required

Options:

- **APPROVE_CCXT_OHLCV_SHADOW**: V2 publishes secondary-exchange OHLCV
  to `v2:market:ccxt_ohlcv:*` (shadow only, no live trade impact).
- **DEFER_CCXT_OHLCV**: keep 10 dims explicit-missing as
  `OPERATOR_DECISION_REQUIRED` (current default).
- **EXCLUDE_CCXT_OHLCV**: skip permanently; document the checkpoint
  compatibility assumption that native Binance OHLCV is sufficient.

Current default state: **DEFER_CCXT_OHLCV**.

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- This packet does NOT modify legacy, write old Redis, call exchange
  mutation, enable live, create approvals, or commit credentials.
