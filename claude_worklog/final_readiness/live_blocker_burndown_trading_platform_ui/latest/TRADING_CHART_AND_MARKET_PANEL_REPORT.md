
# Trading Chart And Market Panel Report

Generated: `2026-05-13T05:46:26Z`

- Mission Control chart remains read-only and labeled from current market feed context.
- Chart and market panels do not expose order placement, leverage, margin, or live controls.
- Symbols/market panel separates candles/price from funding, OI, liquidation, long/short, and CoinAnk availability.
- Missing optional market evidence is rendered as `MISSING_EVIDENCE`, not fake data.
- If external TradingView is unavailable, fallback chart is read-only and cannot place orders.
