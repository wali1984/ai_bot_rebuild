# Trainer Parity Comparison

Generated: 2026-05-12T06:11:36Z

Overall classification: `BLOCKED_FULL_LEGACY_GPU_PARITY_NOT_PROVEN`.

| Area | Classification | Evidence | Gap |
|---|---|---|---|
| legacy trainer file atlas | parity_verified | legacy_reference trainer files inventoried; see TRAINER_FILE_ATLAS.md |  |
| legacy PPO/MASA runtime process | missing_runtime_evidence | ps output lacks rl.hybrid_trainer | Legacy trainer is not running and was not started by this non-live validation. |
| legacy trainer monitor process | missing_runtime_evidence | ps output lacks monitor_trainer_predictions | Legacy trainer prediction monitor is not running. |
| GPU availability on host | parity_verified | nvidia-smi and torch show RTX 5080 and torch CUDA available |  |
| current trainer GPU use | missing_runtime_evidence | No legacy trainer process in nvidia-smi process list; V2 paper wrapper is CPU/read-only momentum logic | Cannot prove PPO/MASA CUDA inference/training path is active. |
| legacy checkpoint inventory | parity_verified | legacy_reference/.models and .backups checkpoint files mapped; latest metadata found |  |
| checkpoint identity used by V2 wrapper | v2_simplified_wrapper_not_full_parity | V2 model_checkpoint=v2_paper_readonly_momentum_wrapper_v1 | V2 wrapper does not load ppo_checkpoint_latest.zip or masa_checkpoint_*.pkl. |
| feature input parity | v2_simplified_wrapper_not_full_parity | Legacy uses large Redis-driven feature vectors; V2 wrapper uses return_1m/5m/15m, volume, volatility from read-only Binance candles | No one-to-one mapping to legacy 768/1041 feature vector proven. |
| confidence behavior parity | v2_simplified_wrapper_not_full_parity | Legacy has PPO/MASA agreement and optional temperature calibration; V2 wrapper subtracts 0.02 from raw confidence | Legacy calibrated confidence is not reproduced. |
| V2 current paper lineage | wrapper_equivalent_for_paper | Current prediction, feature snapshot, signal, orchestrator, risk, execution intent, paper ledger IDs present |  |
| V2 wrapper required output completeness | blocked | v2_paper_trainer_current_record.json | Missing explicit model_id, top_positive_features, top_negative_features, missing_feature_flags, stale_feature_flags. |
| legacy-to-V2 full parity | blocked | This packet | Full parity cannot be claimed until legacy trainer runtime, GPU use, checkpoint loading, feature vector, and confidence calibration are observed or safely replayed. |
