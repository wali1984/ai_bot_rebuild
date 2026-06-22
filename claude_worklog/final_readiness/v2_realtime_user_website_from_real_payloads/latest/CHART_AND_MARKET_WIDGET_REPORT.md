# Chart + Market Widget Report

## Primary chart (TradingView with labeled fallback)

The Market Overview page renders a TradingView embedded chart for the
selected symbol/timeframe. The embed is the only third-party widget on
the public surface; everything else is rendered from V2 truth.

- **Default symbol**: `BTCUSDT` (operator-selectable from the symbol picker).
- **Timeframes**: 1m, 5m, 15m, 1h, 4h, 1d.
- **Labeled fallback**: if the TradingView embed fails to load (network, ad-block, region), the panel renders a minimal in-house SVG candle chart driven by `v2:market:prices:{symbol}.ticker_24hr` + recent klines. The fallback chart is clearly labeled `FALLBACK CHART — NOT TRADINGVIEW` so operators know the source.
- **Price stats strip** below the chart sources from the same ticker_24hr block (lastPrice, openPrice, highPrice, lowPrice, count, quoteVolume).
- **Funding inline**: `+0.0083% / 8h` chip sources from `v2:market:funding:{symbol}`.

The chart is read-only. There are no live order buttons on the chart
canvas, the panel header, or any context menu. The page banner labels
the surface `paper / shadow only` regardless of which symbol is loaded.

## Binance top-10 dashboards

Six tables, one per (venue × metric) combination, each rendered from
its corresponding `v2:dashboards:binance_top10:*` key plus the public
mirror written by `v2_top10_binance_dashboard_feed`.

| Dashboard | Source key | Metric | Window |
|---|---|---|---|
| Spot 12h volume leaders | `v2:dashboards:binance_top10:spot_volume_12h` | quoteVolume | 12h (true rolling) |
| Spot 12h most traded | `v2:dashboards:binance_top10:spot_trades_12h` | count | 12h (true rolling) |
| Spot 12h volatility leaders | `v2:dashboards:binance_top10:spot_volatility_12h` | abs(priceChangePercent) | 12h (true rolling) |
| Futures 12h volume leaders | `v2:dashboards:binance_top10:futures_volume_12h` | quoteVolume | 24h (window_actual; documented in payload) |
| Futures 12h most traded | `v2:dashboards:binance_top10:futures_trades_12h` | count | 24h (window_actual) |
| Futures 12h volatility leaders | `v2:dashboards:binance_top10:futures_volatility_12h` | abs(priceChangePercent) | 24h (window_actual) |

Each row renders rank, symbol, quote_volume, trade_count, price_change_percent, last_price. The window difference (12h spot vs 24h futures) is shown as a chip on each futures dashboard so the operator is never misled.

## Liquidation tape

A streaming list rendered from the persistent V2 liquidation WSS
daemon's Redis writes:

- Header: `LIQ tape · last 30 events · paper/shadow only`
- Row: `[time] [side: long/short] [symbol] [notional] [price] [venue]`
- Empty state when no events in the quiet window: explicit
  `no events yet — heartbeat fresh, no synthesis` chip plus the
  heartbeat TTL value. Never fabricate a row.

Source keys:

- `v2:market:liquidations:heartbeat` (status + TTL)
- `v2:market:liquidations:latest:{symbol}`
- `v2:market:liquidations:aggregate:{symbol}`

## Funding / OI movers panel

Side panel listing top symbols by 4h Δ OI and top symbols by funding
extremity, sourced from `v2:market:funding:{symbol}` and
`v2:market:open_interest:{symbol}`.

## Alt-data status panels

Two compact panels on the Market Overview page:

### Nansen status

- Reads `v2:altdata:nansen:status`.
- When `key_present=false`: chip says `KEY_MISSING_NO_NETWORK`.
- When `key_present=true` but `source_status_counts.API_FORBIDDEN_403>0`: chip says `API_FORBIDDEN_403 — operator decision required`.
- When `paid_endpoints_enabled=false`: chip stays `FREE_TIER`.
- Per-symbol scores are read from `v2:altdata:nansen:symbol:{symbol}` and rendered with explicit `null` cells when missing — never as zero.

### LunarCrush status

- Same pattern as Nansen, reading `v2:altdata:lunarcrush:status` + `v2:altdata:lunarcrush:symbol:{symbol}`.
- Bearer auth scheme is shown in the status panel for transparency, but the key value never appears anywhere.

## Symbol-universe alt-data ranking

A table read from `v2:symbol_universe:altdata_candidates`:

- Columns: rank, symbol, altdata_symbol_score, providers_consulted, missing_signal_per_candidate, stale_signal_per_candidate, paper_only flag.
- Header chip: `MISSING_PROVIDER_DATA_SAFE` while Nansen / LunarCrush are unavailable.
- Footer must show `paper_symbols_expanded=false`, `live_symbols=[]`, `may_not_override_strict_paper_fill_gate=true`, `may_not_authorize_live_or_canary=true`.

## What this report does NOT specify

It does not ship the TSX components. The wiring rules above are
explicit so the follow-up frontend packet can implement panel readers
that drop into the existing Monitor Center grid system without re-
designing payload contracts.
