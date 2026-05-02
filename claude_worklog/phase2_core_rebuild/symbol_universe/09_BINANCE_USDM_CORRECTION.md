# Binance USD-M Primary Correction

Previous Phase 2B implementation incorrectly centered Binance COIN-M futures as the primary Binance futures universe.

Correction:
- Primary Binance futures source is now USD-M.
- Primary endpoint family is `/fapi`.
- Primary exchange-info path is `/fapi/v1/exchangeInfo`.
- Primary source key is `binance_usdm`.
- Legacy 25-symbol config entries such as `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` are USD-M-style active subset symbols.
- COIN-M remains optional/future adapter support only through `binance_coinm`.

Safety:
- No legacy ingestors changed.
- No `v2/legacy_preserved/ingestors/live_coinank.py` changes.
- No live Binance API calls were made in tests.
- No Redis writes were made.
- No live trading was enabled.

BINANCE_USDM_CORRECTION_READY
