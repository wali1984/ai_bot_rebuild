# Charting And Market Data Integration

The current cockpit includes an in-app SVG candlestick and volume panel with
signal/risk markers. It is intentionally offline and deterministic.

Read-only integration target:

- Binance USD-M REST klines: `/fapi/v1/klines`
- Binance USD-M kline stream: `<symbol>@kline_<interval>`
- No POST/DELETE/PUT order routes.
- No order, cancel, leverage, or margin methods.

TradingView Lightweight Charts remains the preferred production charting library
once package installation and API-ready read-only market data wiring are opened.

CHARTING_AND_MARKET_DATA_INTEGRATION_READY
