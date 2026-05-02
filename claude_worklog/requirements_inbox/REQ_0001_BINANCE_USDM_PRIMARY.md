# Requirement 0001 - Binance USD-M Primary Futures Universe

Binance futures primary universe must be USD-M, not COIN-M.

Rules:
- USD-M is primary.
- Endpoint family `/fapi`.
- Exchange info path `/fapi/v1/exchangeInfo`.
- USD-M symbols like BTCUSDT/ETHUSDT are primary.
- Legacy config.py active symbols are USD-M-style subset.
- COIN-M is optional/future adapter only.
- COIN-M symbols like BTCUSD_PERP must not collapse into USD-M BTCUSDT.
- Dated contracts must not collapse into perpetual contracts.
- USDC pairs must remain distinct from USDT pairs unless explicitly related as aliases, not identical markets.

REQ_BINANCE_USDM_PRIMARY_READY
