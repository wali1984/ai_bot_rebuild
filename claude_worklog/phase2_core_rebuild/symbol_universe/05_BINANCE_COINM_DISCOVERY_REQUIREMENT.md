# Binance COIN-M Discovery Requirement

Discovery source:
- Base endpoint configurable.
- Path: `/dapi/v1/exchangeInfo`.
- Parse the `symbols` array.

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

BINANCE_COINM_DISCOVERY_REQUIREMENT_READY
