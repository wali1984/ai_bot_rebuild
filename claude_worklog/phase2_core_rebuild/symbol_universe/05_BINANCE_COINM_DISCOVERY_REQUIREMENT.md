# Binance Futures Discovery Requirement

Primary discovery source:
- Base endpoint configurable.
- Path: `/fapi/v1/exchangeInfo`.
- Parse the `symbols` array.
- Primary source key: `binance_usdm`.
- Symbols use USD-M style names such as `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`.
- Contract family is `usd_m` and linear by default.

Optional/future discovery source:
- COIN-M remains supported through `/dapi/v1/exchangeInfo`.
- Source key: `binance_coinm`.
- COIN-M is not the primary universe for current legacy 25-symbol mapping.

Fields preserved:
- `symbol`
- `pair`
- `contractType`
- `contractStatus` or `status`
- `baseAsset`
- `quoteAsset`
- `marginAsset`
- `deliveryDate`
- `onboardDate`
- `filters`
- `pricePrecision`
- `quantityPrecision`

Testing:
- Fixture JSON only.
- No live API calls in tests.
- Fixture contains perpetual, quarterly/delivery, and delivered/non-trading samples.
- Non-trading symbols remain discovered but cannot move to active states without manual override.

BINANCE_USDM_DISCOVERY_REQUIREMENT_READY
