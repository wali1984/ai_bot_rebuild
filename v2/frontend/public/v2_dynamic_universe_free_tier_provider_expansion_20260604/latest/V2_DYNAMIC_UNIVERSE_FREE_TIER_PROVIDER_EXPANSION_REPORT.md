# V2 Dynamic Universe Free-Tier Provider Expansion Report

Generated: 2026-06-04T05:32Z

GO/NO-GO: `V2_DYNAMIC_UNIVERSE_FREE_TIER_PROVIDER_EXPANSION_CODEX_PASS`

## Result

The V2 non-execution runtime now expands beyond the 27-symbol baseline and auto-updates data, feature, TA, prediction, scoring, and trainer paths from a dynamic exchange-confirmed universe.

Execution remains blocked:

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `execution_live_symbols`: `[]`
- `trade_all_discovered_symbols`: `false`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

Current dynamic runtime:

- `discovered_symbols`: `93`
- `training_symbols`: `93`
- `paper_symbols`: `93`
- `live_data_symbols`: `93`
- `train_all_discovered_symbols`: `true`
- `paper_all_discovered_symbols`: `true`

## Implemented

- Added `v2_dynamic_symbol_discovery_free_tier`.
  - CoinGecko markets/trending discovery.
  - Binance USDM public `exchangeInfo` confirmation.
  - Surf market-price probe with free-tier cap.
  - CoinGlass v4 supported-coins status probe.
  - V2-only Redis writes under `v2:symbol_universe:*` and `v2:altdata:*`.

- Added persistent service:
  - `ai-bot-v2-dynamic-symbol-discovery-loop.service`
  - Interval: 6 hours.
  - Surf default probe budget: 3 symbols per cycle, estimated 12 calls/day.

- Updated dynamic propagation:
  - Native ingestor re-resolves symbols every loop cycle.
  - Feature pipeline re-resolves symbols every loop cycle.
  - RL inference re-resolves symbols every loop cycle.
  - Symbol universe resolver now prefers exchange-confirmed training/paper scope over raw discovered scope.

- Updated scoring/candidates:
  - Scorer now consumes `coingecko`, `surf`, and `coinglass` V2 payloads in addition to Nansen/LunarCrush.
  - Candidate publisher no longer blocks a scored symbol just because another provider is missing.
  - Missing provider flags remain visible.

- Updated native ingestor:
  - Uses Binance Futures ticker/klines endpoints for USDM symbols.
  - Bounded concurrent public fetches with V2-only Redis writes.

## Provider Status

CoinGecko:

- `market_source_status`: `API_OK`
- `trending_source_status`: `API_OK`
- `successful_symbol_count`: `81`
- `raw_credential_value_exposed`: `false`

Surf:

- `source_status_counts`: `{"API_OK": 3}`
- `successful_symbol_count`: `3`
- `free_tier_budget_guard`: 12 calls/day at current defaults
- `raw_credential_value_exposed`: `false`

CoinGlass:

- `source_status_counts`: `{"API_PLAN_BLOCKED_401_UPGRADE_PLAN": 1}`
- `successful_symbol_count`: `0`
- The script is configured and running; current account/API plan blocks the tested endpoint.

## Runtime Refresh Evidence

- Native ingestor: `NATIVE_V2_PUBLIC_REST_OK`, `558` V2 market keys written.
- Feature pipeline: `NATIVE_V2_FEATURES_OK`, `93` snapshots built.
- Full TA-Lib: `V2_FULL_TALIB_TA_LIVE_OK`, `274` TA keys written, max indicator count `221`.
- RL inference: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, `93` predictions written.
- Candidate publisher:
  - `candidate_count`: `93`
  - `SYMBOL_UNIVERSE_GATE_REQUIRED`: `82`
  - `MISSING_PROVIDER_DATA`: `11`
  - `SYMBOL_NOT_TRADABLE_ON_BINANCE`: `0`
- Trainer:
  - `classification`: `V2_TRAINER_TRAINING_LIVE_OK`
  - `row_count`: `23038`
  - `train_rows`: `299`
  - `validation_rows`: `82`
  - `trained_model_available`: `true`

## Verification

- `python -m py_compile` on touched backend files.
- `pytest` focused backend suite: `75 passed`.
- Frontend `npm run typecheck`: passed.
- Frontend `npm run build`: passed.
- User services checked: `0` failed.

## Surf Plan

Surf skills were reviewed as an agent-facing discovery layer. The current integration uses the underlying Surf market-price API directly rather than shelling through a CLI, because the runtime worker needs deterministic V2-only Redis output, redacted credentials, bounded free-tier calls, and no operator-interactive dependency.

Future efficient free-tier Surf usage:

- Keep `market-price` probes capped to BTC/ETH/SOL or top dynamic candidates.
- Add `surf_news`/search summaries only as cached, low-frequency context features.
- Do not use Surf for high-frequency per-symbol ingestion unless a paid tier is explicitly approved.

## Sources Reviewed

- Surf skills repository: `https://github.com/asksurf-ai/surf-skills`
- CoinGecko coins markets endpoint: `https://docs.coingecko.com/reference/coins-markets`
- CoinGlass supported coins endpoint: `https://docs.coinglass.com/reference/coins`
