# V2 CoinAnk Subscription Endpoint Pipeline Trainer Website Validation Report

Gate: `V2_COINANK_SUBSCRIPTION_ENDPOINT_PIPELINE_TRAINER_WEBSITE_VALIDATION_READY`
Generated EST: `2026-06-09T20:41:03-04:00`
CoinAnk runtime: `DIRECT_COINANK_RUNTIME_OK`
Direct endpoint probe: `ok=54 fail=0`
Current endpoint errors: `0`
Missing API blockers: `[]`
Direct key counts: `{'features_coinank': 2009, 'features_global_coinank': 30, 'latest_coinank': 1042}`
Global aggregate: `DIRECT_COINANK_GLOBAL_AGGREGATE_OK`
Trainer CoinAnk coverage: `native trainer reads latest:coinank:* directly and masks unavailable per-symbol fields`
Website trade payload: `BTCUSDT long_short=2.2531 source=latest:coinank:long_short:BTCUSDT:15m`
Website derivatives modules: `{'basis': 'CURRENT_OR_RECENT', 'funding': 'CURRENT_OR_RECENT', 'liquidations': 'CURRENT_OR_RECENT', 'long_short': 'CURRENT_OR_RECENT', 'open_interest': 'CURRENT_OR_RECENT'}`
Production payloads: `CoinAnk=DIRECT_COINANK_RUNTIME_OK trade_long_short=2.2531`
Production route crawl: `33/34 ready, failed=1`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

## Result

CoinAnk subscription access is validated. The direct `live_coinank.py --test-once` probe returned all 54 active endpoints OK and 0 failures. The current runtime status reports no recent API errors and no missing active endpoint blockers. `orderBook_v2_bySymbol` and `instruments_getLastPrice` remain intentionally disabled because price/orderbook is owned by Binance/KuCoin/CoinAPI public feeds.

The old CoinAnk global bridge is masked. The running services are the direct V2 legacy-owned scripts and the direct status publisher. I restarted only V2-owned services and the native trainer path; no legacy production restart was performed.

The native trainer now reads direct CoinAnk current-source keys (`latest:coinank:*`) for open interest, funding, long/short, liquidations, market order flow, and advanced CoinAnk payloads. The tensor builder consumes those fields where current values exist and leaves unavailable per-symbol fields masked instead of fabricating values.

The trade terminal and derivatives payloads are refreshed locally and in production. BTCUSDT long/short now comes from `latest:coinank:long_short:BTCUSDT:15m`, and derivatives modules for funding, open interest, long/short, basis, and liquidations are `CURRENT_OR_RECENT`.

## Remaining Note

Production route crawl is 33/34 ready. The remaining repair marker is `/admin/monitor-center?role=admin`, which redirects to `/system/health` and is classified by the crawler as `proof_dump_primary`. That is not a CoinAnk endpoint or payload blocker, but it is recorded in `coinank_website_payload_sync_status.json`.

## Validation

- py_compile: `PASS`
- focused backend tests: `PASS: 4 passed`
- frontend typecheck: `PASS`
- frontend build: `PASS`
- local route crawl: `PASS`
- production payload fetch: `PASS`
- direct endpoint probe: `PASS: 54/54`
- exchange mutation scan: `PASS`
- old Redis write scan: `PASS for new trainer/operator-truth/status code`
- raw secret scan: `PASS`

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no legacy restart, no Redis trim, and no raw credential output.
