# Full Trainer Live and Ingestor Data Proof - 2026-06-03

Generated UTC: 2026-06-04T00:49:08Z

## Verdict

- Fixed: trainer now has a live training loop in addition to live signal inference. `ai-bot-v2-trainer-training-live-loop.service` is active and writes `v2:trainer:training:*`.
- Fixed: native trainer dataset builder now consumes the dynamic symbol resolver and the live `v2:features:latest:*` schema instead of depending on stale `v2:features:ta:*` compatibility keys.
- Dynamic symbol pick is working: training heartbeat shows 27 symbols from the symbol-universe payload, baseline 25 plus `COINANK_ONLY_USDT` and `KUCOIN_ONLY_USDT`.
- Still intentionally blocked: direct old legacy trainer/trader/exchange/destructive scripts. Full PPO/MASA legacy weight deserialization is not performed in production; V2 runs signal-only inference plus live training/evaluation.

## Active Services

- `ai-bot-v2-native-ingestors-live-loop.service`: `active`
- `ai-bot-v2-legacy-kucoin-ingestor.service`: `active`
- `ai-bot-v2-legacy-coinapi-v1-ingestor.service`: `active`
- `ai-bot-v2-kucoin-public-rest-loop.service`: `active`
- `ai-bot-v2-coinapi-rest-fallback-loop.service`: `active`
- `ai-bot-v2-coinank-global-bridge-loop.service`: `active`
- `ai-bot-v2-liquidation-wss-paper-shadow.service`: `active`
- `ai-bot-v2-liquidation-bridge.service`: `active`
- `ai-bot-v2-liquidation-levels-engine.service`: `active`
- `ai-bot-v2-feature-pipeline-native-loop.service`: `active`
- `ai-bot-v2-rl-core-inference-loop.service`: `active`
- `ai-bot-v2-trainer-training-live-loop.service`: `active`
- `ai-bot-v2-trainer-checkpoint-evidence.service`: `active`
- `ai-bot-v2-orchestrator-arbitration-loop.service`: `active`
- `ai-bot-v2-risk-gateway-live-loop.service`: `active`

## Redis Family Counts

| Family | Total | Fresh TTL>0 | No TTL |
|---|---:|---:|---:|
| `v2:market:prices:*` | 27 | 27 | 0 |
| `v2:market:ohlcv:*` | 48 | 17 | 31 |
| `v2:market:orderbook:*` | 37 | 25 | 12 |
| `v2:features:latest:*` | 38 | 27 | 11 |
| `v2:features:kucoin:*` | 117 | 117 | 0 |
| `v2:market:kucoin:*` | 109 | 109 | 0 |
| `v2:latest:coinapi:ohlcv:*` | 6 | 6 | 0 |
| `v2:normalized:ohlcv:*` | 6 | 6 | 0 |
| `v2:market:coinapi:rest:*` | 53 | 53 | 0 |
| `v2:features:coinapi_rest:*` | 25 | 25 | 0 |
| `v2:coinank:global:*` | 12 | 12 | 0 |
| `v2:features:global_coinank:*` | 11 | 11 | 0 |
| `v2:liquidations:*` | 1 | 0 | 1 |
| `v2:market:liquidations:*` | 0 | 0 | 0 |
| `v2:prediction:*` | 52 | 27 | 25 |
| `v2:trainer:*` | 8 | 6 | 2 |
| `v2:orchestrator:*` | 3 | 3 | 0 |
| `v2:risk:gateway:*` | 3 | 3 | 0 |

## BTC / ETH / SOL Data Path

### BTCUSDT
- Binance price `v2:market:prices:BTCUSDT` ttl=423: last=63392.00000000, 24h_change_pct=-5.487, funding=0.00001897, open_interest=103943.492, fetched=2026-06-04T00:46:11Z.
- Binance OHLCV `v2:market:ohlcv:binance:BTCUSDT:1m` ttl=423: candles=100, latest_close=63340.01000000, latest_volume=9.49000000.
- Binance orderbook `v2:market:orderbook:BTCUSDT` ttl=423: bid=63291.3, ask=63291.4, spread_bps=0.015799947385945284, levels=20/20.
- KuCoin `v2:features:kucoin:BTCUSDT:latest` ttl=582: present=True, ticker=True, klines=['1m'], orderbook20=True.
- CoinAPI REST `v2:features:coinapi_rest:BTCUSDT:latest` ttl=574: spread_bps=0.015810039216572213, depth_imbalance=0.5742343851810482, micro_price=63250.97861789385, orderbook_present=True.
- CoinAPI WSS OHLCV `v2:latest:coinapi:ohlcv:BTCUSDT:1m` ttl=3600, normalized `v2:normalized:ohlcv:BTCUSDT:1m` ttl=3600: latest_present=True, normalized_present=True; both keys are Redis hashes.
- Trainer feature snapshot `v2:features:latest:BTCUSDT:1m` ttl=580: feature_count=25, real=25, placeholders=0, missing=0, freshness=CURRENT, trainer_consumable=True.
  Selected features: `{"atr_14": 153.10554476807866, "bid_ask_spread_bps": 0.015799947385945284, "depth_imbalance": -0.8919936930623685, "funding_rate": 1.897e-05, "last_liq_bps_24h": 0.0, "macd": -168.95208487776836, "macd_signal": -190.9097306708548, "oi_change_pct": -0.0057000762379741145, "ret_pct": -0.05486641221374046, "rsi_14": 40.13130544239605}`
- Prediction `v2:prediction:BTCUSDT:1m` ttl=551: source=V2_NATIVE_RL_CORE, action=hold, confidence=0.6809434355382293, after_cost_bps=108.56573370692621, gate=TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN, routes_orchestrator=True, routes_risk=True, trader_enabled=False.
- Training rows: total=8703, trainable=130, validation=34, usable=164, live_feature_pending_label_rows=1.
  Example trained/evaluated row: classification=TRAINABLE, label=correct_no_trade, after_cost_return_bps=-9.008384342233395, source_lineage=['replay_outcome_bundles.jsonl'].

### ETHUSDT
- Binance price `v2:market:prices:ETHUSDT` ttl=440: last=1793.06000000, 24h_change_pct=-4.115, funding=0.00006547, open_interest=2338078.409, fetched=2026-06-04T00:46:28Z.
- Binance OHLCV `v2:market:ohlcv:binance:ETHUSDT:1m` ttl=440: candles=100, latest_close=1792.68000000, latest_volume=215.77640000.
- Binance orderbook `v2:market:orderbook:ETHUSDT` ttl=440: bid=1791.48, ask=1791.49, spread_bps=0.05581961333748764, levels=20/20.
- KuCoin `v2:features:kucoin:ETHUSDT:latest` ttl=582: present=True, ticker=True, klines=['1m'], orderbook20=True.
- CoinAPI REST `v2:features:coinapi_rest:ETHUSDT:latest` ttl=574: spread_bps=0.0559473423613186, depth_imbalance=0.2675613310663104, micro_price=1787.3962612302175, orderbook_present=True.
- CoinAPI WSS OHLCV `v2:latest:coinapi:ohlcv:ETHUSDT:1m` ttl=3599, normalized `v2:normalized:ohlcv:ETHUSDT:1m` ttl=3599: latest_present=True, normalized_present=True; both keys are Redis hashes.
- Trainer feature snapshot `v2:features:latest:ETHUSDT:1m` ttl=580: feature_count=25, real=25, placeholders=0, missing=0, freshness=CURRENT, trainer_consumable=True.
  Selected features: `{"atr_14": 5.074423533066974, "bid_ask_spread_bps": 0.05581961333748764, "depth_imbalance": -0.814562335134139, "funding_rate": 6.547e-05, "last_liq_bps_24h": 0.0, "macd": -3.828727331735763, "macd_signal": -4.847341967018068, "oi_change_pct": -0.01574469171153392, "ret_pct": -0.04114951256945153, "rsi_14": 44.04985302340725}`
- Prediction `v2:prediction:ETHUSDT:1m` ttl=551: source=V2_NATIVE_RL_CORE, action=hold, confidence=0.6809434355382293, after_cost_bps=108.56573370692621, gate=TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN, routes_orchestrator=True, routes_risk=True, trader_enabled=False.
- Training rows: total=8579, trainable=125, validation=38, usable=163, live_feature_pending_label_rows=2.
  Example trained/evaluated row: classification=HELD_OUT_VALIDATION, label=correct_no_trade, after_cost_return_bps=-9.008384342233395, source_lineage=['replay_outcome_bundles.jsonl'].

### SOLUSDT
- Binance price `v2:market:prices:SOLUSDT` ttl=515: last=70.82000000, 24h_change_pct=-5.498, funding=-0.00012463, open_interest=10049725.82, fetched=2026-06-04T00:47:43Z.
- Binance OHLCV `v2:market:ohlcv:binance:SOLUSDT:1m` ttl=515: candles=100, latest_close=70.82000000, latest_volume=3298.91400000.
- Binance orderbook `v2:market:orderbook:SOLUSDT` ttl=515: bid=70.76, ask=70.77, spread_bps=1.4131279587353782, levels=20/20.
- KuCoin `v2:features:kucoin:SOLUSDT:latest` ttl=582: present=True, ticker=True, klines=['1m'], orderbook20=True.
- CoinAPI REST `v2:features:coinapi_rest:SOLUSDT:latest` ttl=574: spread_bps=1.412728685456681, depth_imbalance=-0.3149387380016339, micro_price=70.78591925735363, orderbook_present=True.
- CoinAPI WSS OHLCV `v2:latest:coinapi:ohlcv:SOLUSDT:1m` ttl=3599, normalized `v2:normalized:ohlcv:SOLUSDT:1m` ttl=3599: latest_present=True, normalized_present=True; both keys are Redis hashes.
- Trainer feature snapshot `v2:features:latest:SOLUSDT:1m` ttl=580: feature_count=25, real=25, placeholders=0, missing=0, freshness=CURRENT, trainer_consumable=True.
  Selected features: `{"atr_14": 0.24007623184951976, "bid_ask_spread_bps": 1.4131279587353782, "depth_imbalance": -0.5668145000663923, "funding_rate": -0.00012463, "last_liq_bps_24h": 0.0, "macd": -0.1670184301930533, "macd_signal": -0.21045004179217633, "oi_change_pct": -0.00565851087307962, "ret_pct": -0.05497731518548178, "rsi_14": 45.15311548810698}`
- Prediction `v2:prediction:SOLUSDT:1m` ttl=551: source=V2_NATIVE_RL_CORE, action=hold, confidence=0.5502845488272303, after_cost_bps=-39.92638434956034, gate=BLOCKED_BY_TRAINER_OUTPUT_MALFORMED, routes_orchestrator=True, routes_risk=True, trader_enabled=False.
- Training rows: total=1628, trainable=27, validation=6, usable=33, live_feature_pending_label_rows=2.
  Example trained/evaluated row: classification=TRAINABLE, label=correct_no_trade, after_cost_return_bps=-11.35354498307339, source_lineage=['replay_outcome_bundles.jsonl'].

## Trainer Status

- Inference: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, predictions=27, open_gate=['BTCUSDT', 'ETHUSDT'], mode=V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE, trader_enabled=False.
- Training loop: `V2_TRAINER_TRAINING_LIVE_OK`, rows=19542, train_rows=285, validation_rows=78, trained_model_available=True, publishable_baseline_available=False, published_predictions=False.
- Dynamic symbols: count=27, resolution={"baseline_count": 25, "count": 27, "discovered_count": 27, "smoke_test": false, "source_path": "/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json", "symbol_profile": "dynamic_or_baseline", "symbols": ["1000BONKUSDT", "1000FLOKIUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "ALICEUSDT", "ASTERUSDT", "AUCTIONUSDT", "AVNTUSDT", "BANKUSDT", "BARDUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "FARTCOINUSDT", "HIGHUSDT", "LINKUSDT", "LTCUSDT", "PENGUUSDT", "PIPPINUSDT", "RAVEUSDT", "RIVERUSDT", "SOLUSDT", "UNIUSDT", "WIFUSDT", "XRPUSDT", "COINANK_ONLY_USDT", "KUCOIN_ONLY_USDT"]}
- PPO/MASA checkpoint evidence: selected=ppo_checkpoint_1777264095, candidates=15388, status=LEGACY_CHECKPOINT_METADATA_PRESENT_WEIGHTS_NOT_DESERIALIZED_V2_SAFE_MODE, weights_loaded=False, pickle_deserialized=False.

## Why Direct vs Adapter vs V2 Equivalent

- `RUN_DIRECT_UNDER_SYSTEMD` for ingest/liquidation_bridge.py, ingest/liquidation_levels_engine.py: can run with V2_REDIS_PREFIX and paper-only gates; no order mutation
- `RUN_THROUGH_V2_ADAPTER` for ingest/live_kucoin.py, ingest/live_coinapi_v1.py: adapter preserves legacy parsing while forcing V2-prefixed writes and blocked live gate
- `RUN_V2_EQUIVALENT_NOT_DIRECT` for ingest/live_binance.py, ingest/realtime_price_provider.py, ingest/live_coinank_global_aggregator.py, ingest/live_coinapi_rest.py: direct legacy scripts include destructive/operator-gated markers, unprefixed Redis, or keyed/provider assumptions; V2 equivalent provides same data family safely
- `DO_NOT_START_DIRECT` for rl/hybrid_trainer.py, trading/*, exchange mutation scripts, startup_baseline/*, full_runtime_closure/*: would mutate old runtime, exchange, Redis, or duplicate archival code; replaced by V2 signal-only trainer/training loop and controller stack

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `trader_execution_enabled=false`
- `exchange_action_taken=false`
- `writes_legacy_redis=false`

## Artifacts

- Status JSON: `claude_worklog/final_readiness/full_trainer_live_and_ingestor_data_proof_20260603/latest/STATUS.json`
- Public mirror: `v2/frontend/public/full_trainer_live_and_ingestor_data_proof_20260603/latest`
