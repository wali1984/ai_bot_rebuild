# Top-10 Market And Alternative-Data Dashboard Contracts

Generated: `2026-05-18T01:31:40Z`

GO/NO-GO: `V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_READY`

## Decision

The top-10 website dashboard contracts are defined using V2 data only. This is contract/data-shape work only; it does not implement provider clients, does not call provider APIs, does not write Redis, and does not affect trading gates.

## Dashboards

1. `binance_spot_12h_volume_leaders` - Binance Spot 12h Volume Leaders
2. `binance_futures_12h_volume_leaders` - Binance Futures 12h Volume Leaders
3. `binance_spot_12h_most_traded` - Binance Spot 12h Most Traded
4. `binance_futures_12h_most_traded` - Binance Futures 12h Most Traded
5. `binance_spot_12h_volatility_leaders` - Binance Spot 12h Volatility Leaders
6. `binance_futures_12h_volatility_leaders` - Binance Futures 12h Volatility Leaders
7. `liquidation_tape_top_symbols` - Liquidation Tape Top Symbols
8. `funding_oi_movers` - Funding/OI Movers
9. `nansen_smart_money_top_symbols` - Nansen Smart Money Top Symbols
10. `lunarcrush_social_momentum_top_symbols` - LunarCrush Social Momentum Top Symbols

## Data Rules

- Binance 12h dashboards use Binance rolling-window stats when present, or locally computed 12h windows from V2 market data.
- Liquidation tape uses V2 liquidation WSS aggregate keys only and never synthesizes liquidation events.
- Funding/OI movers use existing V2 CoinAnk/funding/open-interest payloads.
- Nansen and LunarCrush dashboards remain disabled/empty until provider clients pass Codex.
- Missing provider keys produce `MISSING_SOURCE`; present keys without Codex-passed clients produce `KEY_PRESENT_NO_CLIENT_YET`.

## Alternative-Data Panels

- `nansen_smart_money_top_symbols`: enabled=`false`, disabled_reason=`KEY_PRESENT_NO_CLIENT_YET`
- `lunarcrush_social_momentum_top_symbols`: enabled=`false`, disabled_reason=`KEY_PRESENT_NO_CLIENT_YET`

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_old_redis`: `false`
- `exchange_mutation`: `false`
- raw values exposed: `false`
- provider network calls attempted: `false`

## Final Decision

`V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_READY`
