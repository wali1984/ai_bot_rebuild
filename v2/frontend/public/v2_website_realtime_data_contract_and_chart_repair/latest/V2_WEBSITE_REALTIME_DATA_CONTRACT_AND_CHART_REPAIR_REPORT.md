# V2 Website Realtime Data Contract And Chart Repair Report

Gate: `V2_WEBSITE_REALTIME_DATA_CONTRACT_AND_CHART_REPAIR_READY`
Generated EST: `2026-06-04T23:02:18-04:00`

## Fixed

- Removed the redundant Mission Control chart and removed the external TradingView widget path from active pages.
- Added a V2 realtime market chart publisher backed by existing CoinAPI WSDS Redis snapshots only.
- Added BTCUSDT, ETHUSDT, and SOLUSDT chart payloads under `/operator_runtime/v2_market_chart/latest/`.
- Replaced synthetic trader-terminal candles with the V2 websocket-fed realtime chart.
- Replaced fake order book/depth rows with real CoinAPI WSDS bid/ask/spread/top-5 book evidence when available.
- Replaced placeholder/stub panels on trader, liquidation, trainer history, positions, system health, symbols, live readiness, audit, market intelligence, operator truth, and monitor-center surfaces with explicit current-source or unavailable-source states.
- Prevented missing liquidation/funding aggregate values from rendering as zero on Mission Control.
- Removed stale TradingView production report artifact and generated V2 realtime chart report output.

## Runtime Evidence

- `ai-bot-v2-market-chart-payload-publisher.service`: `active`
- Chart source: existing Redis keys `v2:market:coinapi:wsds:{symbol}`
- BTCUSDT chart: `CURRENT`, `240` samples
- ETHUSDT chart: `CURRENT`, `240` samples
- SOLUSDT chart: `CURRENT`, `240` samples
- Route crawl: `32/32` canonical routes passed
- Failed route requests: `0`
- Console errors: `0`
- Network errors: `0`

## Validation

- `python3 -m py_compile v2/backend/app/cli/v2_market_chart_payload_publisher.py` passed.
- `npm run typecheck` passed.
- `npm run build` passed.
- Route crawl passed: `production_route_matrix_v2_website_realtime_data_contract_and_chart_repair_final.json`.
- Source/artifact scan found no active TradingView, fallback static chart, GET-only chart, `MISSING_EVIDENCE`, `MISSING_SOURCE`, or missing-telemetry markers in repaired surfaces.

## Remaining Real Reasons

- Live/canary/order/leverage/margin controls remain unavailable because backend audit and human approval contracts are not enabled.
- Provider-plan, credential, and event-dependent fields remain visible as real unavailable-provider states; the frontend does not fabricate them.
- Full depth/tape/funding/OI/basis visualizations remain unavailable where no typed V2 backend contract exists.

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `execution_live_symbols`: `[]`
- No live/canary enable.
- No order/test-order/cancel/modify.
- No leverage or margin mutation.
- No old Redis write.
- No Redis trim.
- No legacy restart.
