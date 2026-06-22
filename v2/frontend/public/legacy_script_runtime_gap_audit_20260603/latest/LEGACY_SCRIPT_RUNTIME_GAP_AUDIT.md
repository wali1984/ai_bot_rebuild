# Legacy Script Runtime Gap Audit - 2026-06-03

Generated UTC: 2026-06-04T00:37:07Z

## Bottom Line

- Not all 708 legacy-owned scripts are running, and they should not be blanket-started. The legacy folder includes live trading, exchange mutation, cleanup/restart, duplicate startup-baseline, archived full-runtime, and unprefixed Redis paths.
- Production-equivalent non-trader data and signal routing are live through managed `ai-bot-v2-*` services using V2-prefixed Redis keys.
- Trainer signal generation is live: `v2:trainer:heartbeat` reports `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, 27 predictions, signal-only, routed to orchestrator/risk, trader disabled.
- Update: trainer training is now also live through `ai-bot-v2-trainer-training-live-loop.service`. It writes `v2:trainer:training:*`, rebuilds the dynamic-symbol dataset, evaluates the native baseline, and reports `V2_TRAINER_TRAINING_LIVE_OK`. Proof: `claude_worklog/final_readiness/full_trainer_live_and_ingestor_data_proof_20260603/latest/FULL_TRAINER_LIVE_AND_INGESTOR_DATA_PROOF.md`.
- Full legacy PPO + MASA parity is **not** live. The latest PPO/MASA artifacts are inventoried as checkpoint metadata, but weights are not deserialized/loaded into the V2 process.
- Full legacy TA-Lib all-indicator parity is **not** live. The trainer receives fresh TA-derived fields in `v2:features:latest:*`; the old compatibility `v2:features:ta:*` keys are stale historical artifacts.

## Runtime Status Counts

| Runtime status | Scripts |
|---|---:|
| `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | 6 |
| `NOT_RUNNING_ARCHIVAL_FULL_RUNTIME_COPY` | 235 |
| `NOT_RUNNING_DUPLICATE_STARTUP_BASELINE_COPY` | 32 |
| `NOT_RUNNING_KEYED_OR_PAID_PROVIDER_GATED` | 7 |
| `NOT_RUNNING_LEGACY_API_REPLACED_BY_V2_API` | 5 |
| `NOT_RUNNING_LEGACY_INGESTOR_STATIC_OR_BACKFILL` | 4 |
| `NOT_RUNNING_OPERATOR_GATED_DESTRUCTIVE_OR_MAINTENANCE` | 52 |
| `NOT_RUNNING_OPERATOR_GATED_EXCHANGE_MUTATION` | 7 |
| `NOT_RUNNING_OPERATOR_GATED_TRADING_RUNTIME` | 32 |
| `NOT_RUNNING_STATIC_ONE_SHOT_OR_LIBRARY` | 96 |
| `NOT_RUNNING_TRAINER_RL_PARITY_GATED` | 225 |
| `PARTIAL_V2_FEATURE_COVERAGE_NOT_FULL_LEGACY_PARITY` | 3 |
| `RUNNING_DIRECT_V2_MANAGED` | 2 |
| `RUNNING_VIA_V2_LEGACY_ADAPTER` | 2 |

## Legacy Classification Counts

| Execution class | Scripts |
|---|---:|
| `api_static_validated_runtime_not_started` | 5 |
| `covered_by_v2_native_ingestors_live_loop` | 1 |
| `legacy_ingestor_static_validated_runtime_not_started` | 5 |
| `operator_gated_destructive_or_maintenance_not_executed` | 91 |
| `operator_gated_exchange_mutation_not_executed` | 13 |
| `operator_gated_keyed_or_paid_ingestor_not_executed` | 15 |
| `operator_gated_trading_runtime_not_executed` | 65 |
| `static_validated_not_runtime_started` | 133 |
| `trainer_or_rl_static_validated_runtime_gated` | 376 |
| `validated_by_v2_coinank_and_liquidation_bridge` | 2 |
| `validated_by_v2_legacy_ingestor_adapter` | 2 |

## User-Requested Capability Coverage

| Capability | Status | Active service/equivalent | Evidence | Note |
|---|---|---|---|---|
| live_binance / realtime_price_provider | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-native-ingestors-live-loop.service | prices=27, fresh_ohlcv=17, orderbooks=25 | legacy live_binance.py is not direct-started because classification has destructive/operator-gated marker; public Binance V2 loop is live |
| live_binance_liquidations / liquidation bridge | `SERVICE_ONLINE_EVENT_DEPENDENT_DATA` | ai-bot-v2-liquidation-wss-paper-shadow.service, ai-bot-v2-liquidation-bridge.service, ai-bot-v2-liquidation-levels-engine.service | liquidation_keys=0, liquidation_stream_keys=1 | services are active; zero liquidation event keys means no forceOrder event currently observed, not service failure |
| live_kucoin | `RUNNING_VIA_V2_LEGACY_ADAPTER` | ai-bot-v2-legacy-kucoin-ingestor.service, ai-bot-v2-kucoin-public-rest-loop.service | legacy_adapter_keys_total=150, fresh_features_kucoin=117, fresh_market_kucoin=109 | adapter compatibility keys are no-TTL; fresh KuCoin feature and market keys are TTL-positive |
| live_coinank | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-coinank-global-bridge-loop.service | coinank_global=12, features_global_coinank=11 |  |
| CoinAPI REST and WSS/V1 | `RUNNING_ADAPTER_AND_REST_FALLBACK_PARTIAL_WSDS` | ai-bot-v2-legacy-coinapi-v1-ingestor.service, ai-bot-v2-coinapi-rest-fallback-loop.service | coinapi_wss_ohlcv_keys=6, coinapi_normalized_ohlcv_keys=6, coinapi_rest_keys=53, coinapi_rest_feature_keys=25 | live_coinapi_v1 adapter and REST fallback are online; legacy live_coinapi_wsds.py itself remains keyed/operator-gated |
| OHLCV / real-time price / orderbook | `ACTIVE_FEEDING_FEATURE_PIPELINE` | ai-bot-v2-native-ingestors-live-loop.service, ai-bot-v2-legacy-kucoin-ingestor.service, ai-bot-v2-legacy-coinapi-v1-ingestor.service | fresh_prices=27, fresh_ohlcv=17, fresh_orderbooks=25, fresh_feature_snapshots=27 |  |
| TA-Lib / technical_analysis.py | `PARTIAL_V2_FEATURE_COVERAGE_NOT_FULL_LEGACY_TALIB` | ai-bot-v2-feature-pipeline-native-loop.service | fresh_features_latest=27, compat_ta_keys_total=24, compat_ta_keys_fresh=0 | talib imports in the venv, but the live V2 feature pipeline writes core TA-derived fields in v2:features:latest, not the full legacy all-indicator TA-Lib service |
| trainer / PPO / MASA | `V2_SIGNAL_ONLY_TRAINER_ACTIVE_FULL_PPO_MASA_NOT_LOADED` | ai-bot-v2-rl-core-inference-loop.service, ai-bot-v2-trainer-checkpoint-evidence.service | trainer_status=V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK, predictions_count=27, fresh_prediction_keys=27, checkpoint_id=ppo_checkpoint_1777264095, latest_ppo=ppo_checkpoint_1777264095, latest_masa=masa_checkpoint_1777264095, weights_loaded=False | V2 trainer is live for signal generation, but policy is V2 deterministic CPU forward with checkpoint metadata only; full legacy PPO/MASA parity is not complete |

## Trainer / Orchestrator / Risk

- Trainer heartbeat TTL: 252 seconds; classification: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`; predictions: 27; open-gate symbols: ['BTCUSDT', 'ETHUSDT'].
- Trainer mode: `V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE`; production_signal_only=True; routes_to_orchestrator=True; routes_to_risk_gateway=True; trader_execution_enabled=False.
- Checkpoint evidence: selected=`ppo_checkpoint_1777264095`, latest_ppo=`ppo_checkpoint_1777264095`, latest_masa=`masa_checkpoint_1777264095`, candidates=15388, weights_loaded=False, pickle_deserialized=False.
- Orchestrator: classification=`V2_ORCHESTRATOR_PRODUCTION_OK`, predictions_seen=52, proposals_arbitrated=2, held_by_gate=50.
- Risk gateway: classification=`V2_RISK_GATEWAY_LIVE_OK`, decisions_processed_total=2, latest=allow/allow_proceed_long, places_real_order=False, exchange_action_taken=False.

## Redis Dataflow Evidence

| Pattern | Total | Fresh TTL>0 | No TTL/stale-compatible |
|---|---:|---:|---:|
| `v2:market:prices:*` | 27 | 27 | 0 |
| `v2:market:ohlcv:*` | 48 | 17 | 31 |
| `v2:market:orderbook:*` | 37 | 25 | 12 |
| `v2:features:latest:*` | 38 | 27 | 11 |
| `v2:features:ta:*` | 24 | 0 | 24 |
| `v2:kc:*` | 150 | 0 | 150 |
| `v2:features:kucoin:*` | 117 | 117 | 0 |
| `v2:market:kucoin:*` | 109 | 109 | 0 |
| `v2:latest:coinapi:ohlcv:*` | 6 | 6 | 0 |
| `v2:normalized:ohlcv:*` | 6 | 6 | 0 |
| `v2:market:coinapi:rest:*` | 53 | 53 | 0 |
| `v2:features:coinapi_rest:*` | 25 | 25 | 0 |
| `v2:coinank:global:*` | 12 | 12 | 0 |
| `v2:market:coinank:global:*` | 11 | 11 | 0 |
| `v2:features:global_coinank:*` | 11 | 11 | 0 |
| `v2:market:liquidations:*` | 0 | 0 | 0 |
| `v2:liquidations:*` | 1 | 0 | 1 |
| `v2:prediction:*` | 52 | 27 | 25 |
| `v2:trainer:*` | 6 | 4 | 2 |
| `v2:orchestrator:*` | 3 | 3 | 0 |
| `v2:risk:gateway:*` | 3 | 3 | 0 |

## Fresh BTCUSDT Sample

- `v2:features:latest:BTCUSDT:1m`: ttl=581, feature_count=25, real_feature_count=25, placeholders=0, missing=0, freshness=`CURRENT`, trainer_consumable=True.
- `v2:prediction:BTCUSDT:1m`: ttl=552, trainer_source=`V2_NATIVE_RL_CORE`, checkpoint=`ppo_checkpoint_1777264095`, paper_fill_gate=`TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN`, routes_to_orchestrator=True, routes_to_risk_gateway=True, trader_execution_enabled=False, weights_loaded=False.

## Important Script-Level Rows

| Legacy script | Runtime status | Why / service |
|---|---|---|
| `ingest/liquidation_bridge.py` | `RUNNING_DIRECT_V2_MANAGED` | ai-bot-v2-liquidation-bridge.service: running direct copied legacy-owned runtime with V2_REDIS_PREFIX=v2:, paper-only gates |
| `ingest/liquidation_levels_engine.py` | `RUNNING_DIRECT_V2_MANAGED` | ai-bot-v2-liquidation-levels-engine.service: running direct copied legacy-owned runtime with V2_REDIS_PREFIX=v2:, paper-only gates |
| `ingest/live_binance.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-native-ingestors-live-loop.service: covered by V2 native public Binance loop; legacy file not direct-started because classified destructive/operator-gated |
| `ingest/live_binance_liquidations.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-liquidation-wss-paper-shadow.service + ai-bot-v2-liquidation-bridge.service: covered by V2 Binance forceOrder WSS plus copied bridge/levels; event stream can be empty when no forceOrder events arrive |
| `ingest/live_coinank_global_aggregator.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-coinank-global-bridge-loop.service: covered by V2 CoinAnk global bridge loop; V2 namespace only |
| `ingest/live_coinapi_rest.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-coinapi-rest-fallback-loop.service: covered by V2 CoinAPI REST fallback loop; legacy keyed script not direct-started |
| `ingest/live_coinapi_v1.py` | `RUNNING_VIA_V2_LEGACY_ADAPTER` | ai-bot-v2-legacy-coinapi-v1-ingestor.service: running through v2_legacy_ingestor_adapter coinapi_v1; V2 namespace only |
| `ingest/live_coinapi_wsds.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-legacy-coinapi-v1-ingestor.service + ai-bot-v2-coinapi-rest-fallback-loop.service: partially covered by CoinAPI v1 WSS and REST fallback; legacy WSDS script itself remains keyed/operator-gated |
| `ingest/live_kucoin.py` | `RUNNING_VIA_V2_LEGACY_ADAPTER` | ai-bot-v2-legacy-kucoin-ingestor.service: running through v2_legacy_ingestor_adapter kucoin; V2 namespace only |
| `ingest/live_technical_analysis.py` | `PARTIAL_V2_FEATURE_COVERAGE_NOT_FULL_LEGACY_PARITY` | ai-bot-v2-feature-pipeline-native-loop.service: partial live TA-derived fields in v2:features:latest; full legacy TA-Lib all-indicator engine is not running |
| `ingest/realtime_price_provider.py` | `COVERED_BY_ACTIVE_V2_EQUIVALENT_NOT_DIRECT` | ai-bot-v2-native-ingestors-live-loop.service: covered by V2 native public Binance price/OHLCV/orderbook loop |
| `ingest/technical_analysis.py` | `PARTIAL_V2_FEATURE_COVERAGE_NOT_FULL_LEGACY_PARITY` | ai-bot-v2-feature-pipeline-native-loop.service: partial live TA-derived fields in v2:features:latest; full legacy TA-Lib all-indicator engine is not running |
| `rl/agents/masa_agent.py` | `NOT_RUNNING_TRAINER_RL_PARITY_GATED` | legacy trainer/RL script statically validated but not direct-started; V2 signal-only trainer is live, full PPO/MASA weight loading remains blocked |
| `rl/gpu_forced_ppo.py` | `NOT_RUNNING_TRAINER_RL_PARITY_GATED` | legacy trainer/RL script statically validated but not direct-started; V2 signal-only trainer is live, full PPO/MASA weight loading remains blocked |
| `rl/hybrid_trainer.py` | `NOT_RUNNING_OPERATOR_GATED_DESTRUCTIVE_OR_MAINTENANCE` | destructive/restart/cleanup/maintenance marker; not safe for blind production start |
| `rl/masa_supervised_pretrainer.py` | `NOT_RUNNING_TRAINER_RL_PARITY_GATED` | legacy trainer/RL script statically validated but not direct-started; V2 signal-only trainer is live, full PPO/MASA weight loading remains blocked |
| `startup_baseline/ingest/live_coinapi_v1.py` | `NOT_RUNNING_DUPLICATE_STARTUP_BASELINE_COPY` | startup_baseline duplicate/reference copy; primary V2-managed path is used when safe |
| `startup_baseline/ingest/live_kucoin.py` | `NOT_RUNNING_DUPLICATE_STARTUP_BASELINE_COPY` | startup_baseline duplicate/reference copy; primary V2-managed path is used when safe |
| `startup_baseline/ingest/realtime_price_provider.py` | `NOT_RUNNING_DUPLICATE_STARTUP_BASELINE_COPY` | startup_baseline duplicate/reference copy; primary V2-managed path is used when safe |
| `technical_analysis.py` | `PARTIAL_V2_FEATURE_COVERAGE_NOT_FULL_LEGACY_PARITY` | ai-bot-v2-feature-pipeline-native-loop.service: partial live TA-derived fields in v2:features:latest; full legacy TA-Lib all-indicator engine is not running |

## Why Most Scripts Are Not Running

- `trainer_or_rl_static_validated_runtime_gated`: legacy trainer/RL modules, experiments, PPO/MASA components, and analysis scripts. They are static-validated but not live because V2 currently runs a signal-only native CPU policy and does not load legacy weight blobs.
- `operator_gated_trading_runtime_not_executed`: old trader/runtime files. They remain stopped because trader/live execution is outside the allowed non-trader runtime.
- `operator_gated_exchange_mutation_not_executed`: old exchange mutation paths. They remain stopped because no leverage, margin, order placement, or order cancellation is allowed.
- `operator_gated_destructive_or_maintenance_not_executed`: scripts with cleanup/restart/destructive markers. They remain stopped to avoid mutating old production state.
- `operator_gated_keyed_or_paid_ingestor_not_executed`: old paid-provider/keyed scripts. Only reviewed V2-prefixed replacements are online.
- `static_validated_not_runtime_started`, `legacy_ingestor_static_validated_runtime_not_started`, and `api_static_validated_runtime_not_started`: one-shot helpers, duplicate baseline copies, static libraries, backfills, monitors, and old API modules. These are validated but not continuous daemons.

## Safety State

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `trader_execution_enabled=false`
- `exchange_action_taken=false`
- `writes_legacy_redis=false` for the V2 trainer/risk/controller paths
- failed `ai-bot-v2*` user services: 0

## Artifacts

- Full matrix: `claude_worklog/final_readiness/legacy_script_runtime_gap_audit_20260603/latest/legacy_script_runtime_gap_matrix.json`
- Status JSON: `claude_worklog/final_readiness/legacy_script_runtime_gap_audit_20260603/latest/STATUS.json`
- Public mirror: `v2/frontend/public/legacy_script_runtime_gap_audit_20260603/latest`
