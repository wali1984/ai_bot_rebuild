# V2 Dynamic Universe And Alt-Data Runtime Repair Report

Generated: 2026-06-04T03:45Z

GO/NO-GO: `V2_DYNAMIC_UNIVERSE_ALTDATA_RUNTIME_REPAIR_CODEX_PASS`

## Result

The V2 non-execution runtime is no longer narrowed to BTC/ETH/SOL. The symbol universe publisher now separates execution scope from live data/training/paper-shadow scope and uses Redis runtime evidence for current observed coverage.

Execution remains down by design:

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `execution_live_symbols`: `[]`
- `trade_all_discovered_symbols`: `false`

Everything else is live over the dynamic universe:

- `discovered_symbols`: `27`
- `observed_symbols`: `27`
- `live_data_symbols`: `27`
- `trainer_live_symbols`: `27`
- `paper_shadow_live_symbols`: `27`
- `train_all_discovered_symbols`: `true`
- `paper_all_discovered_symbols`: `true`

## Fixes Applied

- Updated `v2/backend/app/cli/symbol_universe_public_payload.py`
  - Defaults trainer and paper-shadow scopes to all dynamic discovered symbols.
  - Adds explicit non-execution live fields: `live_data_symbols`, `live_monitoring_symbols`, `trainer_live_symbols`, `paper_shadow_live_symbols`.
  - Keeps execution fields empty: `live_symbols`, `execution_live_symbols`.
  - Reads Redis runtime evidence from V2 market, feature, prediction, and Binance OHLCV keys.
  - Filters non-symbol heartbeat keys out of symbol evidence.

- Updated `v2/backend/app/cli/v2_arkham_presence_only_worker.py`
  - Writes operator-runtime status at `v2/frontend/public/operator_runtime/arkham_presence_only/latest/arkham_presence_only_status.json`.
  - Keeps Arkham presence-only: no HTTP request, no raw credential read/exposure.

- Updated `v2/frontend/src/pages/market-intelligence/index.tsx`
  - Replaced the hardcoded BTC/ETH/SOL coverage panel with dynamic universe coverage.
  - Shows live data, trainer, paper-shadow, Binance OHLCV, and execution coverage counts.
  - Shows `Execution universe 0` with the trader-down explanation.

- Added and started persistent safe user services:
  - `ai-bot-v2-nansen-altdata-loop.service`
  - `ai-bot-v2-lunarcrush-altdata-loop.service`
  - `ai-bot-v2-alternative-data-status-loop.service`
  - `ai-bot-v2-alt-data-symbol-scoring-loop.service`
  - `ai-bot-v2-alt-data-candidate-publisher-loop.service`
  - `ai-bot-v2-arkham-presence-loop.service`

## Provider Status

Nansen:

- `symbol_count`: `27`
- `key_present`: `true`
- `network_call_attempted`: `true`
- `successful_symbol_count`: `27`
- `source_status_counts`: `{"API_OK": 1, "CACHE_HIT": 26}`
- `default_endpoint_id`: `smart_money_holdings_free`
- `symbol_signal_coverage`: `6 / 27`
- `symbol_signal_coverage_symbols`: `BTCUSDT`, `ETHUSDT`, `FARTCOINUSDT`, `PENGUUSDT`, `SOLUSDT`, `UNIUSDT`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

LunarCrush:

- `symbol_count`: `27`
- `key_present`: `true`
- `network_call_attempted`: `true`
- `successful_symbol_count`: `0`
- `source_status_counts`: `{"API_PAYMENT_REQUIRED_402": 27}`
- `default_endpoint_id`: `public_coins_list_v2_free`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

Arkham:

- `credential_status_by_name`: `KEY_PRESENT_BY_NAME`
- `client_status`: `FUTURE_PLACEHOLDER_AWAITING_CLIENT_ADAPTER`
- `http_request_made`: `false`
- `raw_credential_value_exposed`: `false`
- `redis_keys_written_count`: `1`

## Candidate And Scoring Status

- Alternative-data status symbols: `27`
- Provider ids: `nansen`, `lunarcrush`, `alphavantage`, `tokenmetrics`, `arkham_future`, `binance_existing`, `coinank_existing`, `liquidation_wss_existing`
- Alt-data scorer symbols: `27`
- Candidate publisher count: `27`
- Candidate state counts:
  - `MISSING_PROVIDER_DATA`: `17`
  - `SYMBOL_NOT_TRADABLE_ON_BINANCE`: `10`
  - `CANDIDATE_READY`: `0`

## Services

Active services verified:

- `ai-bot-v2-symbol-universe-publisher.service`
- `ai-bot-v2-nansen-altdata-loop.service`
- `ai-bot-v2-lunarcrush-altdata-loop.service`
- `ai-bot-v2-alternative-data-status-loop.service`
- `ai-bot-v2-alt-data-symbol-scoring-loop.service`
- `ai-bot-v2-alt-data-candidate-publisher-loop.service`
- `ai-bot-v2-arkham-presence-loop.service`

Failed user services: `0`.

## Verification

Commands passed:

- `python -m py_compile` for touched backend CLIs
- `python -m pytest v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py`
- `python -m pytest v2/backend/tests/integration/cli/test_v2_alternative_data_status.py v2/backend/tests/integration/cli/test_v2_alt_data_symbol_universe_scoring.py v2/backend/tests/integration/cli/test_v2_alt_data_symbol_candidate_publisher.py v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py`
- `npm run typecheck`
- `npm run build`
- focused route crawl for `/admin/market-intelligence?role=admin` and `/admin/live-readiness?role=admin`

Test results:

- Symbol-universe unit tests: `3 passed`
- Alt-data integration tests: `110 passed`
- Frontend typecheck/build: passed
- Route crawl: passed

Route crawl evidence:

- `claude_worklog/final_readiness/v2_dynamic_universe_altdata_runtime_repair_20260603/latest/route_crawl_results.json`
- screenshots in `claude_worklog/final_readiness/v2_dynamic_universe_altdata_runtime_repair_20260603/latest/screenshots/`

## Provider Docs Repair Addendum

Follow-up report:

- `claude_worklog/final_readiness/v2_nansen_lunarcrush_docs_aligned_api_repair_20260604/latest/NANSEN_LUNARCRUSH_DOCS_ALIGNED_API_REPAIR_REPORT.md`

The earlier `API_FORBIDDEN_403` provider snapshot is superseded. Nansen is now docs-aligned and live through the V2 namespace. LunarCrush is also docs-aligned, but the provider returns `API_PAYMENT_REQUIRED_402` for the current account/key on the documented `api4` coins endpoint.

## Remaining External Blockers

LunarCrush scripts are running over the full 27-symbol universe, but the provider returns `API_PAYMENT_REQUIRED_402` for all symbols on the documented endpoint. That is an upstream account/subscription issue, not a missing worker or V2 runtime gap.

Arkham is presence-only. It confirms credential presence by name and writes safe V2 status, but it does not claim a real Arkham client adapter or make HTTP requests. A local search found no existing full legacy Arkham client to reuse; the prior parity materials state that legacy did not run Arkham.
