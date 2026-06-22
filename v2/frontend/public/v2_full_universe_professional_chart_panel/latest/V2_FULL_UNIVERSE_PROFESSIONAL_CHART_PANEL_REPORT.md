# V2 Full Universe Professional Chart Panel Report

Gate: `V2_FULL_UNIVERSE_PROFESSIONAL_CHART_PANEL_READY`
Generated EST: `2026-06-05T00:55:00-04:00`

Final implementation keeps the existing raw CoinAPI WSDS realtime microprice chart as a separate panel and adds a professional OHLCV/TA/signal chart panel backed by V2 runtime payloads.

- Raw CoinAPI WSDS panel: unchanged, still requires current `v2:market:coinapi:wsds:{symbol}` snapshots.
- Raw WSDS known real gap: `OPUSDT` currently has no CoinAPI WSDS snapshot and remains shown as unavailable in the raw panel.
- Binance kline WSS service: `V2_BINANCE_KLINE_WSS_CONNECTED`
- Binance kline WSS streams: `505`
- Binance kline WSS connections: `5`
- Binance kline WSS symbols: `101`
- Binance kline WSS timeframes: `1m, 5m, 15m, 1h, 4h`
- Professional chart manifest: `V2_PROFESSIONAL_MARKET_CHARTS_READY`
- Professional chart payloads: `505/505` current
- Professional chart all-timeframe symbols: `101/101` current
- Professional chart source type: `EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED`
- Pipeline static status rows: `505`
- Pipeline chart-visible symbols: `101`
- Pipeline blockers: `{}`
- Ingestors status: `INGESTORS_OK`, active `16/19`
- Local route crawl: exited `0` over the canonical dashboard route set
- Focused browser canvas check: passed on `/market?role=admin`, `/trader?role=admin`, `/admin/symbols?role=admin`, and `/admin/mission-control?role=admin`

The professional chart uses `lightweight-charts` candlesticks, volume bars, SMA/EMA/Bollinger overlays, and paper signal target overlays. It reads static V2 chart payloads under `/operator_runtime/v2_professional_market_chart/latest` and does not call provider APIs from the browser.

Safety unchanged:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `execution_live_symbols`: `[]`
- No live/canary enablement
- No order/test-order/cancel/modify
- No leverage or margin mutation
- No old Redis write
- No Redis trim
- No legacy restart
