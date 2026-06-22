# V2 Crypto-Vision-Inspired Public Intel Free-Tier Report

Generated: `2026-06-04T05:44:02Z`

GO/NO-GO: `V2_PUBLIC_INTEL_FREE_TIER_LIVE_OK`

## Result

Reviewed crypto-vision as a broad reference platform and integrated only non-duplicative free public intelligence lanes into V2: DeFi TVL/liquidity context, public news attention/sentiment, global Fear & Greed, and Bitcoin mempool pressure.

- Runtime symbols scored: `93`
- Symbols with public score: `93`
- DeFiLlama symbols: `64`
- News symbols: `21`
- Fear & Greed status: `API_OK`
- Mempool status: `API_OK`

## Top Public-Intel Symbols

| Symbol | Public score | Providers |
| --- | ---: | --- |
| AAVEUSDT | 0.673243 | defillama,fear_greed |
| LDOUSDT | 0.665709 | defillama,fear_greed |
| SSVUSDT | 0.661038 | defillama,fear_greed |
| XAUTUSDT | 0.643138 | defillama,fear_greed |
| ONDOUSDT | 0.641541 | defillama,fear_greed |
| POLUSDT | 0.636714 | defillama,fear_greed |
| JSTUSDT | 0.636567 | defillama,fear_greed |
| PAXGUSDT | 0.632401 | defillama,fear_greed |
| OPUSDT | 0.631059 | defillama,fear_greed |
| ARBUSDT | 0.628857 | defillama,fear_greed |
| UNIUSDT | 0.62707 | defillama,fear_greed |
| CRVUSDT | 0.618094 | defillama,fear_greed |
| ENAUSDT | 0.60724 | defillama,news,fear_greed |
| HYPEUSDT | 0.59739 | defillama,news,fear_greed |
| SLXUSDT | 0.596477 | defillama,fear_greed |
| JTOUSDT | 0.592638 | defillama,fear_greed |
| PENDLEUSDT | 0.590721 | defillama,fear_greed |
| BARDUSDT | 0.59028 | defillama,fear_greed |
| ZROUSDT | 0.589577 | defillama,news,fear_greed |
| ASTERUSDT | 0.582945 | defillama,fear_greed |

## Safety

- `LIVE_GATE`: `blocked_human_only`
- `live_symbols`: `[]`
- `execution_live_symbols`: `[]`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`
- `raw_credential_value_exposed`: `false`

## Runtime Integration

- New worker: `v2/backend/app/cli/v2_public_intel_free_tier.py`
- Scoring hook: `v2:altdata:public_intel:symbol:{symbol}` now feeds `v2_alt_data_symbol_universe_scoring`.
- Persistent service: `ai-bot-v2-public-intel-free-tier-loop.service`, active and enabled.
- Status/registry loop no longer overwrites live `v2:altdata:symbol_score:*` or `v2:symbol_universe:altdata_candidates`; those keys are owned by the scorer and candidate publisher.
- Market Intelligence page now displays dynamic discovery plus public-intel runtime panels from `operator_runtime/latest`.

## Downstream Evidence

- Candidate publisher: `93` candidates.
- Candidate states: `CANDIDATE_READY=4`, `SYMBOL_UNIVERSE_GATE_REQUIRED=89`, `MISSING_PROVIDER_DATA=0`, `STALE_PROVIDER_DATA=0`, `SYMBOL_NOT_TRADABLE_ON_BINANCE=0`.
- Trainer: `V2_TRAINER_TRAINING_LIVE_OK`, `row_count=23909`, `train_rows=299`, `validation_rows=82`, `trained_model_available=true`.
- Services checked active: public intel, alt-data scoring, alt-data candidate publisher, trainer training loop.
- Failed user services: `0`.

## Verification

- `python -m py_compile` on touched backend modules.
- Focused pytest: `54 passed`.
- Dynamic universe focused tests: `5 passed`.
- Frontend `npm run typecheck`: passed.
- Frontend `npm run build`: passed.
- Focused route crawl: passed for `/admin/market-intelligence?role=admin` and `/admin/live-readiness?role=admin`.
- Route crawl evidence: `claude_worklog/final_readiness/v2_crypto_vision_public_intel_free_tier_20260604/latest/route_crawl_results.json`.

## Source Review Decision

`nirholas/crypto-vision` was treated as a reference architecture, not a vendored dependency. The useful non-duplicative ideas were DeFi liquidity context, public news sentiment, global market sentiment, and on-chain/mempool pressure. Existing V2 market data remains owned by the V2 market ingestors to avoid duplicating prices, OHLCV, order books, funding, or open interest.
