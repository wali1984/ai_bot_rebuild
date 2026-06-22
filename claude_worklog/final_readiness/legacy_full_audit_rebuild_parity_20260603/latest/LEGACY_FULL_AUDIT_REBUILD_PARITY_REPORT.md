# Legacy Full Audit vs V2 Rebuild Parity Report

Generated: 2026-06-04T02:20Z  
Baseline compared: `/home/wali/Desktop/AI BOT REBUILD/LEGACY_SYSTEM_FULL_AUDIT.md` (`Audit Date: 2026-05-22`)  
Scope: V2 rebuild runtime, V2 Redis namespace, trainer path, orchestrator/risk path, dry-run canary.

## Executive Result

The new V2 build is live for the non-mutating production path and now has a fresh full TA-Lib compatibility data plane. It is not yet a literal 100% replacement for every namespace and endpoint listed in `LEGACY_SYSTEM_FULL_AUDIT.md`.

I did not enable real exchange order placement. The active runtime remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `trader_execution_enabled`: `false`
- `places_real_order`: `false`
- `exchange_action_taken`: `false`
- `writes_legacy_redis`: `false`

The dry-run canary is active through the timer and uses `FakeExchangeAdapter`; it writes V2 canary intents/ledger/status only and remains blocked from real orders.

## Fix Applied In This Pass

Added and started a full TA-Lib V2 compatibility loop:

- Code:
  - `v2/backend/app/services/full_talib_ta/service.py`
  - `v2/backend/app/cli/v2_full_talib_ta_loop.py`
  - `v2/backend/tests/integration/cli/test_v2_full_talib_ta_loop.py`
- Systemd:
  - `claude_worklog/systemd/user/ai-bot-v2-full-talib-ta-loop.service`
  - installed to `/home/wali/.config/systemd/user/ai-bot-v2-full-talib-ta-loop.service`
- Redis outputs:
  - `v2:features:ta:{symbol}:{timeframe}`
  - `v2:features:ta_full:{symbol}:{timeframe}`
  - `v2:features:ta:heartbeat`

The worker computes TA-Lib over live V2 OHLCV rows where available and writes compact fallback payloads with an explicit partial classification where full OHLCV is missing but V2 compact TA/features exist.

Current full TA heartbeat:

- `classification`: `V2_FULL_TALIB_TA_LIVE_OK`
- `result_count`: `71`
- `keys_written_count`: `142`
- all `v2:features:ta:*` keys are fresh; no no-TTL stale TA compatibility keys remain
- max indicator count observed: `221`

## Runtime State

Active V2 services: `41` loaded active `ai-bot-v2*` services.  
Failed user services: `0`.

Core enabled/active services:

- `ai-bot-v2-native-ingestors-live-loop.service`
- `ai-bot-v2-feature-pipeline-native-loop.service`
- `ai-bot-v2-full-talib-ta-loop.service`
- `ai-bot-v2-rl-core-inference-loop.service`
- `ai-bot-v2-trainer-training-live-loop.service`
- `ai-bot-v2-orchestrator-arbitration-loop.service`
- `ai-bot-v2-risk-gateway-live-loop.service`
- `ai-bot-v2-coinapi-rest-fallback-loop.service`
- `ai-bot-v2-legacy-coinapi-v1-ingestor.service`
- `ai-bot-v2-kucoin-public-rest-loop.service`
- `ai-bot-v2-legacy-kucoin-ingestor.service`
- `ai-bot-v2-coinank-global-bridge-loop.service`
- `ai-bot-v2-liquidation-wss-paper-shadow.service`
- `ai-bot-v2-liquidation-bridge.service`
- `ai-bot-v2-live-canary-dry-run.timer`

Dry-run canary state:

- `go_no_go`: `V2_24H_LIVE_CANARY_BLOCKED_EXCHANGE_PERMISSION_UNKNOWN`
- `dry_run`: `true`
- `live_enabled`: `false`
- `exchange_adapter_kind`: `FakeExchangeAdapter`
- `real_order_attempted`: `false`
- `real_order_submitted`: `false`
- `writes_exchange_orders`: `false`

## Fresh Redis Evidence

Fresh V2 key counts observed after the fix:

| Namespace | Total | Fresh | Notes |
|---|---:|---:|---|
| `v2:market:prices:*` | 27 | 27 | Live price/funding/OI payloads |
| `v2:market:ohlcv:binance:*` | 48 | 17 | Live plus wrapped historical/compat payloads |
| `v2:market:orderbook:*` | 37 | 25 | Live orderbook top/depth surfaces |
| `v2:features:latest:*` | 38 | 27 | Trainer-ready compact features |
| `v2:features:ta:*` | 72 | 72 | Fresh full/partial TA compatibility payloads |
| `v2:features:ta_full:*` | 71 | 71 | Full TA payload mirror |
| `v2:features:kucoin:*` | 117 | 117 | KuCoin feature equivalent active |
| `v2:market:kucoin:*` | 109 | 109 | KuCoin market data active |
| `v2:latest:coinapi:ohlcv:*` | 6 | 6 | CoinAPI OHLCV latest |
| `v2:normalized:ohlcv:*` | 6 | 6 | Normalized CoinAPI/V2 OHLCV |
| `v2:market:coinapi:rest:*` | 53 | 53 | CoinAPI REST fallback active |
| `v2:features:coinapi_rest:*` | 25 | 25 | CoinAPI REST features active |
| `v2:coinank:global:*` | 12 | 12 | CoinAnk global bridge active |
| `v2:features:global_coinank:*` | 11 | 11 | Global CoinAnk features active |
| `v2:prediction:*` | 52 | 27 | RL inference publishing |
| `v2:trainer:*` | 8 | 6 | Trainer/training heartbeats/status active |
| `v2:orchestrator:*` | 3 | 3 | Orchestrator active |
| `v2:risk:gateway:*` | 3 | 3 | Risk gateway active |
| `v2:live_canary:*` | 4 | 4 | Dry-run canary active |

Event-dependent caveat: `v2:liquidations:events` is a Redis stream and does not use TTL. `v2:market:liquidations:*` aggregates were not present at this snapshot.

## BTC / ETH / SOL Proof

All three requested symbols have live price, 1m OHLCV, orderbook, compact features, full TA, and prediction keys.

| Symbol | OHLCV | Compact Feature Payload | Full TA Payload | Prediction |
|---|---:|---:|---:|---|
| `BTCUSDT` | 100 live 1m candles | 25 real features, 0 missing | `216` fields, `V2_FULL_TALIB_TA_OK` | present |
| `ETHUSDT` | 100 live 1m candles | 25 real features, 0 missing | `216` fields, `V2_FULL_TALIB_TA_OK` | present |
| `SOLUSDT` | 100 live 1m candles | 25 real features, 0 missing | `219` fields, `V2_FULL_TALIB_TA_OK` | present |

Example trainer-facing indicators now present in `v2:features:ta:{symbol}:1m`:

- `ta_RSI_14`
- `ta_MACD_12_26_9_macd`
- `ta_ATR_14`
- `ema_12`
- `ema_26`

## Trainer Flow

Current trainer training cycle was forced after the TA refresh:

- `classification`: `V2_TRAINER_TRAINING_LIVE_OK`
- `row_count`: `19952`
- `train_rows`: `285`
- `validation_rows`: `78`
- `trained_model_available`: `true`
- `go_no_go`: `V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_READY`
- `places_real_order`: `false`
- `exchange_action_taken`: `false`
- `writes_legacy_redis`: `false`

Trainer data path:

1. V2 ingestors publish market/OHLCV/orderbook/liquidation/altdata into `v2:*`.
2. `ai-bot-v2-feature-pipeline-native-loop` publishes `v2:features:latest:{symbol}:{tf}`.
3. `ai-bot-v2-full-talib-ta-loop` publishes fresh `v2:features:ta:{symbol}:{tf}` and `v2:features:ta_full:{symbol}:{tf}`.
4. `v2_trainer_training_live_loop` reads only V2 keys through `V2OnlyReader`, including:
   - `v2:features:latest:{symbol}:{tf}`
   - `v2:features:ta:{symbol}:{tf}`
   - `v2:market:ohlcv:binance:{symbol}:{tf}`
   - `v2:market:orderbook:binance:{symbol}` / current V2 orderbook inputs
   - `v2:prediction:{symbol}:{tf}`
   - `v2:risk:decisions`
   - optional altdata/liquidation sources
5. `ai-bot-v2-rl-core-inference-loop` publishes signal-only predictions.
6. `ai-bot-v2-orchestrator-arbitration-loop` consumes predictions and produces V2 proposals/decisions.
7. `ai-bot-v2-risk-gateway-live-loop` evaluates decisions but does not submit exchange orders.

## Legacy Checklist Comparison

| Legacy audit item | Current V2 state | Status |
|---|---|---|
| Binance OHLCV/mark/funding | `v2:market:prices:*`, `v2:market:ohlcv:binance:*`, native ingestor active | `LIVE_PARTIAL_DEPTH` |
| Binance liquidations | WSS paper-shadow and bridge services active; stream event-dependent | `LIVE_EVENT_DEPENDENT_PARTIAL` |
| Realtime price/orderbook | 27 price payloads and 25 fresh orderbook surfaces | `LIVE` |
| KuCoin | `v2:market:kucoin:*` and `v2:features:kucoin:*` fresh | `LIVE` |
| CoinAPI REST/v1 OHLCV | REST fallback and legacy CoinAPI v1 V2 proxy active | `LIVE_PARTIAL_SYMBOL_TF_DEPTH` |
| CoinAPI WSDS microstructure | No full `microfeat:*` / `msnap:*` equivalent at legacy breadth | `GAP` |
| CoinAnk global | `v2:coinank:global:*` and `v2:features:global_coinank:*` fresh | `LIVE_GLOBAL_ONLY` |
| CoinAnk full endpoint/cursor family | Legacy had 2,403 + 3,054 + 2,150 endpoint/cursor keys; V2 does not yet reproduce this breadth | `GAP` |
| Technical analysis 160 fields | Full TA-Lib V2 loop active; 216-221 fields on full OHLCV payloads | `FIXED_LIVE` |
| Unified features 562 fields | Compact feature payloads active plus full TA, but not the full 562-field merged legacy vector | `GAP_PARTIAL` |
| Predictions / trainer output | RL inference live, 52 prediction keys, 27 fresh; training loop live | `LIVE_WITH_MODEL_PARITY_GAP` |
| PPO + MASA legacy trainer parity | V2 has signal-only inference/training baseline; full PPO/MASA legacy weight load is not proven | `GAP` |
| Orchestrator | V2 orchestrator live, sees 52 predictions, arbitrated 2 proposals | `LIVE_NON_MUTATING` |
| Risk gateway | V2 risk gateway live, no exchange mutation | `LIVE_NON_MUTATING` |
| Trader/live positions | Paper/tracking only; real live trader not enabled from chat | `BLOCKED_BY_OPERATOR_SAFETY` |
| TokenMetrics | No confirmed V2 TokenMetrics equivalent live | `GAP` |
| AlphaVantage news | No confirmed V2 equivalent live | `GAP` |
| CCXT multi-exchange OHLCV | Not confirmed as active V2 equivalent | `GAP` |
| RL metrics namespace | Trainer/training heartbeats active; old `rl:*` namespace not reproduced one-for-one | `PARTIAL` |

## Why Legacy Scripts Are Not Direct-Started

Direct-starting the old scripts from `/home/wali/Desktop/AI BOT/` would violate the rebuild boundary:

- They write old Redis namespaces such as `ta:*`, `unified_features:*`, `prediction:*`, `features:coinank:*`, and `signals:*`.
- Some legacy processes are coupled to the old runtime tree, old config, old locks, and old shutdown assumptions.
- Trading-side legacy scripts can interact with live execution paths.
- V2 must publish V2-prefixed keys and keep exchange mutation behind explicit reviewed operator gates.

Where reuse is safe, the rebuild uses V2 wrappers/adapters, for example:

- legacy CoinAPI v1 via V2-prefixed service
- legacy KuCoin via V2-prefixed service
- liquidation bridge through V2 namespace
- dry-run live canary through `FakeExchangeAdapter`

## Verification Commands Run

- `python -m py_compile v2/backend/app/services/full_talib_ta/service.py v2/backend/app/cli/v2_full_talib_ta_loop.py`
- `python -m pytest v2/backend/tests/integration/cli/test_v2_full_talib_ta_loop.py`
- `python -m v2.backend.app.cli.v2_full_talib_ta_loop --once`
- `systemctl --user enable --now ai-bot-v2-full-talib-ta-loop.service`
- `systemctl --user start ai-bot-v2-live-canary-dry-run.service`
- `python -m v2.backend.app.cli.v2_trainer_training_live_loop --once --minimum-train-rows 64 --v2-redis-ttl-seconds 900`
- `systemctl --user --failed --no-pager --plain`

Focused test result: `3 passed`.

## Current Go-Live Position

Safe V2 production runtime is live for:

- market data ingestion
- feature pipeline
- full TA-Lib compatibility
- trainer training
- RL inference
- orchestrator
- risk gateway
- paper loop
- dry-run canary

Not approved/enabled:

- real live order placement
- live trader execution
- legacy shutdown
- Redis trimming/deleting old namespaces

Remaining hard work for true `LEGACY_SYSTEM_FULL_AUDIT.md` parity:

1. Full CoinAnk endpoint/cursor breadth.
2. Full 562-field unified feature vector.
3. Full CoinAPI WSDS microstructure (`microfeat`, `msnap`) parity.
4. PPO/MASA legacy model/weight parity proof.
5. TokenMetrics, AlphaVantage, and CCXT active V2 equivalents if still required.
6. Live-position/trader path through a reviewed operator-controlled deployment, not from chat.
