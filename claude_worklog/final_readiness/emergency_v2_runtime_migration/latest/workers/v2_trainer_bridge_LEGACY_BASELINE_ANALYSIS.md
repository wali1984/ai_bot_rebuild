# V2 Trainer Bridge Legacy Baseline Analysis

Generated: 2026-05-14

## Classification

- Worker: `v2_trainer_bridge`
- Lane: P1 runtime migration
- Resulting mode: read-only parity bridge, not live activation
- Live gate: `blocked_human_only`
- Legacy mutation: forbidden
- Old Redis writes: forbidden
- Exchange actions: forbidden
- Symbol contract: `SYMBOL_UNIVERSE_CONTRACT_REQUIRED`

## Copied Baseline Evidence

Primary copied source:

- `v2/legacy_preserved/startup_baseline/rl/hybrid_trainer.py`
- Manifest: `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
- Manifest SHA256: `f379d80fdb8b4b44934cafb304e28050ee28bc38e3ff96b2fdbdb569c32f677c`
- Trainer source SHA256: `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`
- Manifest record status: `COPIED`
- Source SHA status: `SHA_MATCH`

Supporting copied sources:

- `v2/legacy_preserved/startup_baseline/config.py` SHA256 `98cfaa1c9650f013f8603c451f6f37491b8fa65e36ed1445a037c34d5f27f522`
- `v2/legacy_preserved/startup_baseline/scripts/start_all_services_production.sh` SHA256 `2b5a9a63fc76487b3a6f46cdbb8060044aeab69c5f8117bbf30e7efdb8a10ca9`
- `v2/legacy_preserved/startup_baseline/scripts/monitor_trainer_predictions.py` SHA256 `38068905908317415f91f76ed19797c393ee01f20135d59030289e2d697a495a`

## Legacy Source Paths

- `legacy_reference/rl/hybrid_trainer.py`
- `legacy_reference/config.py`
- `legacy_reference/scripts/start_all_services_production.sh`
- `legacy_reference/scripts/monitor_trainer_predictions.py`
- Copied equivalents under `v2/legacy_preserved/startup_baseline/`

The V2 bridge reads the copied baseline, not `/home/wali/Desktop/AI BOT`.

## Legacy Functions And Classes Preserved As Contract

Static inspection of the copied trainer confirmed these trainer components:

- `RTX5080FeatureExtractor`
- `RTX5080Policy`
- `GPUForcedPPO`
- `HybridTrainer`
- `HybridConfig`
- `RTX5080Optimizer`

The copied source also exposes the required methods:

- `setup_models`
- `_build_trade_signal`
- `_normalize_action_name`
- `_publish_signal_payload`
- `_publish_signal_unified`

## Legacy Inputs

- Symbols from config `SYMBOLS`, now scoped through `SymbolUniverseService`
- Timeframes from config `TIMEFRAMES`
- Feature snapshots from the V2 feature snapshot / feature pipeline payloads
- Trainer loop timing from `PREDICTION_LOOP_SECONDS`
- Safe-mode and checkpoint settings from `SAFE_MODE_DEFAULT_ON`, `SAVE_EVERY_LOOPS`, and `DISABLE_MODEL_SAVES`
- GPU behavior from CUDA allocator, CUDA module loading, AMP, and GPU batch inference settings
- Stream names from `SIGNAL_OUTPUT_STREAM`, `SIGNAL_HEARTBEAT_STREAM`, proposal streams, and trainer heartbeat/status keys as read-only references

## Legacy Outputs

The legacy trainer can emit:

- Trading signal payloads
- Trainer heartbeat/status records
- Proposal records for the orchestrator path
- Per-symbol prediction records
- Checkpoint/model state metadata
- Confidence and action/proposal metadata

The V2 bridge does not emit orders and does not publish into old Redis. It only publishes a V2 public payload and a worklog status JSON.

## Legacy Redis Keys And Streams As Read-Only References

- `signals:trading`
- `signals:trainer:heartbeat`
- `wma:proposals`
- `prediction:{symbol}:{timeframe}`
- `status:trainer`
- `heartbeat:trainer`

These are documented as legacy contracts only. The bridge does not write them.

## Legacy Config Dependencies

- `SYMBOLS`
- `TIMEFRAMES`
- `PREDICTION_LOOP_SECONDS`
- `SAVE_EVERY_LOOPS`
- `DISABLE_MODEL_SAVES`
- `OBS_SCHEMA_VERSION`
- `SAFE_MODE_DEFAULT_ON`
- `ENABLE_GPU_BATCH_INFERENCE`
- `SIGNAL_OUTPUT_STREAM`
- `SIGNAL_HEARTBEAT_STREAM`

## Legacy Runtime And GPU Behavior

- Startup runs `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features` in the legacy runtime.
- Startup checks memory before the trainer starts.
- Startup monitors trainer memory during initialization.
- Startup applies an OOM score so the trainer is terminated before system freeze under memory pressure.
- The copied trainer configures CUDA allocator defaults and lazy module loading.
- The trainer includes RTX 5080 optimized feature extraction, policy, GPU PPO, AMP scaling, optional compile paths, and GPU utilization/VRAM observation.

V2 currently observes process/GPU evidence only. It does not start or restart the legacy trainer.

## Legacy Checkpoint And Model Behavior

The copied trainer includes:

- PPO checkpoint load
- state dict fallback
- MASA checkpoint load
- safe mode until checkpoint load succeeds
- checkpoint compatibility guards
- model save controls

The V2 bridge exposes `model_checkpoint_id` only when a current accepted legacy-hybrid or V2-native trainer prediction payload carries checkpoint evidence. The current paper momentum wrapper checkpoint is rejected as parity evidence.

## Feature Input Contract

The bridge consumes V2 feature snapshot evidence from:

- `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`

It propagates:

- `feature_snapshot_id`
- `feature_snapshot_trainer_readiness_signal`
- `missing_feature_flags`
- `stale_feature_flags`
- feature snapshot dependency status

Missing or stale feature flags block trainer readiness even if a prediction record exists.

## Symbol Universe Contract

The trainer bridge preserves distinct symbol roles:

- `legacy_active_symbols`: current 25-symbol legacy subset from `SymbolUniverseService`
- `dynamic_discovered_symbols`: broader passive discovery universe from Binance Futures, CoinAnk, CoinAPI, KuCoin, and future ingestors
- `observed_symbols`: symbols seen in current payload evidence
- `training_symbols`: selected evidence-backed training subset
- `paper_symbols`: selected paper subset
- `live_symbols`: always `[]` while live is blocked
- `live_blocked_symbols`: symbols explicitly blocked from live action

The bridge reads upstream scope from the Symbol Universe service and, when no Symbol Universe public payload exists, from V2 feature-pipeline public status. It does not treat the current 25 symbols as the full universe. It does not train or trade all discovered symbols automatically. CoinAnk-only symbols remain market-intelligence candidates until Binance USD-M confirmation exists.

Symbol selection scoring cites:

- liquidity
- volume
- volatility
- funding
- open interest
- spread
- freshness
- feature completeness
- exchange availability
- risk profile
- model confidence
- replay performance
- operator overrides

## V2 Mapping

- CLI: `v2/backend/app/cli/v2_trainer_bridge.py`
- Evidence helpers: `v2/backend/app/services/trainer_bridge/service.py`
- Tests: `v2/backend/tests/integration/cli/test_v2_trainer_bridge.py`
- Public payload: `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`
- Worklog status: `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_trainer_bridge_status.json`

The current implementation is a read-only parity bridge. It maps and validates current trainer evidence but intentionally refuses to synthesize predictions.

## Intentional Changes

- No legacy process is started by the bridge.
- No legacy state directories are written.
- No old Redis write occurs.
- No exchange action path is invoked.
- No live key activation occurs.
- No final approval token is created.
- Paper momentum-wrapper predictions are surfaced as evidence but rejected as full legacy hybrid trainer parity.
- Legacy log snapshots missing `prediction_id`, `feature_snapshot_id`, checkpoint, calibrated confidence, and feature flags are rejected as incomplete evidence.

## Current Runtime Result

Current status is `BLOCKED`, not fake-ready:

- Trainer source hash: `b7dad66b63b57c0d5c29e0fbaf67466d9c2aab81baf7a4f67b6e681e38c5b102`
- Trainer process evidence: observed read-only
- GPU evidence: present
- Feature snapshot readiness: present
- Accepted predictions emitted: `0`
- Blocker: `WRAPPER_NOT_LEGACY_HYBRID_PARITY`
- Live gate: `blocked_human_only`
- `live_symbols`: `[]`

This is the correct fail-closed behavior until a current legacy-hybrid or V2-native trainer prediction with checkpoint, feature snapshot, confidence, and feature freshness evidence exists.
