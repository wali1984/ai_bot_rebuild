# CoinAnk Normalization Rules

CoinAnk rows are normalized cautiously into V2 `SymbolIdentity` records that are explicitly marked as discovery-only.

Source key: `coinank`.
Identity prefix: `COINANK-DISC-`.
Default normalization confidence: `low`.
Default status: `discovery_only`.

## Classification flags

For each raw row the V2 classifier computes:
- `is_chinese_name` — true if `symbol` or `baseCoin` contains any character outside ASCII.
- `is_stock_like` — true if `baseCoin` (uppercased, stripped of non-letters) appears in the V2 stock/commodity stop-list.
- `is_dated` — true if `expireAt` is a non-null integer greater than zero, or if `symbol` matches `_\d{6}$`.
- `is_perp_inverse` — true if `symbol` ends with `_PERP` and the quote inferred from `symbol` is `USD` (not `USDT` or `USDC`).
- `is_usdc` — true if `symbol` ends with `USDC`.
- `is_usdt` — true if `symbol` ends with `USDT` and `is_usdc` is false.
- `quote_kind` — one of `USDT`, `USDC`, `USD`, `BTC`, `ETH`, or `OTHER`.
- `requires_confirmation` — always true for CoinAnk rows.
- `candidate_for_usdm_confirmation` — true only when `is_chinese_name=false`, `is_stock_like=false`, `is_dated=false`, `is_perp_inverse=false`, and `quote_kind in {USDT, USDC}`.

Stock/commodity stop-list seeded in V2:
`AAPL, TSLA, GOOGL, GOOG, AMZN, NVDA, META, MSFT, NFLX, AMD, INTC, IBM, ORCL, QQQ, SPY, GOLD, SILVER, OIL, WTI, BRENT, COPPER, NATGAS, SP500, DOW, NASDAQ`.

## Identity construction

- `canonical_symbol_id = COINANK-DISC-{exchange_slug}-{base}-{quote}-{type_part}`
  - `exchange_slug` is `exchangeName` uppercased with non-alphanumerics replaced by `_`.
  - `base` is `baseCoin` uppercased with non-alphanumerics removed; if entirely non-ASCII, `base` becomes `CJK<sha1[:8]>`.
  - `quote` is the inferred or explicit quote; `OTHER` when not in {USDT, USDC, USD, BTC, ETH}.
  - `type_part` is `PERP`, `INVERSE_PERP`, `DATED<expireAt|YYMMDD>`, or `UNKNOWN`.
- `contract_family` is `unknown`.
- `contract_type` is `perpetual`, `dated_delivery`, or `unknown`.
- `market_type` is `futures` only when `exchange_slug` is in the BINANCE_USDM_EXCHANGE_SLUGS set; otherwise `unknown`.
- `legacy_symbol` is never set for CoinAnk identities.
- `normalization_confidence` is `low`.
- `status` is `discovery_only`.

## Hard non-collapse rules

CoinAnk identities never collapse with USD-M, COIN-M, KuCoin, or CoinAPI identities through `match_cross_source_symbol` because:
- `canonical_symbol_id` carries the unique `COINANK-DISC-` prefix.
- `contract_family` is `unknown`.
- `source` is `coinank`, distinguished from `binance_usdm`, `binance_coinm`, `coinapi_ws`, `coinapi_rest`, `kucoin`.

## Confirmation function

`confirm_coinank_against_usdm(coinank_identity, usdm_identities)` returns the matching `SymbolIdentity` only when ALL hold:
- `coinank_identity.metadata["candidate_for_usdm_confirmation"] is True`
- `coinank_identity.metadata["exchange_slug"]` is one of `BINANCE`, `BINANCE_USDM`, `BINANCE_FUTURES`, `BINANCE_PERP`.
- A USD-M identity exists with matching `base_asset`, `quote_asset`, `contract_type=perpetual`, `contract_family=usd_m`.
- The matching USD-M identity is `is_trading()` true.

Returns `None` otherwise. Never mutates either identity.

## Auto-eligibility prohibition

CoinAnk identities are forbidden from auto-eligibility for `eligible_for_training`, `eligible_for_paper`, `shadow_candidate`, or `live_blocked`. They may move out of `discovered` only via manual operator override or after `confirm_coinank_against_usdm` returns a USD-M identity, in which case the USD-M identity is the one promoted.

PHASE2_COINANK_NORMALIZATION_RULES_READY
