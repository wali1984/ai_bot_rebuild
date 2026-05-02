# CoinAnk Raw Row Schema

The uploaded CoinAnk symbol list contains rows from CoinAnk discovery feeds. V2 preserves every row verbatim before any normalization.

Required raw fields (preserved as-is, never trimmed or recased before storage):
- `symbol` — original CoinAnk-side symbol string (may contain non-ASCII characters).
- `baseCoin` — original CoinAnk base-coin string (may contain non-ASCII characters).
- `exchangeName` — original CoinAnk exchange string (e.g. `Binance`, `Binance_USDC`, `KuCoin`, `Bybit`, `OKX`).
- `expireAt` — null/0 for non-dated; otherwise a millisecond unix timestamp.
- `updateAt` — millisecond unix timestamp of the CoinAnk update.

Optional raw fields (preserved if present):
- `productType` — CoinAnk product-type string when supplied.
- `quoteCoin` — explicit CoinAnk quote when supplied.
- `tradingPair` — CoinAnk pair string when supplied.
- `marketType` — CoinAnk market-type string when supplied.

Storage model in V2:
- Raw rows are stored under `metadata["coinank_raw"]` of the emitted `SymbolIdentity`.
- Raw rows are also written into the test fixture file as a JSON array of objects with the keys above.
- Test fixtures must include at least one row per classification class (see `02_NORMALIZATION_RULES.md`).
- Synthetic raw rows used in fixtures must be tagged with `is_synthetic=true` to distinguish them from rows derived from the uploaded ODT.

Forbidden mutations of raw rows:
- No case-folding of `symbol`, `baseCoin`, `exchangeName`.
- No removal of non-ASCII characters before classification.
- No expansion of `_PERP` or `_<YYMMDD>` suffixes into separate identities at raw stage.
- No collapse of USDT and USDC quote-currency rows into a single record.

PHASE2_COINANK_RAW_ROW_SCHEMA_READY
