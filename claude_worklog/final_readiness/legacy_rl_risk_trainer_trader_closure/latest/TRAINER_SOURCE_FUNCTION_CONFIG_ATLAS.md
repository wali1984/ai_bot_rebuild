# TRAINER_SOURCE_FUNCTION_CONFIG_ATLAS — Phase D

File-level atlas of the legacy trainer subsystem. Function-level mapping is deferred to the per-worker port's `LEGACY_BASELINE_ANALYSIS.md`; this document establishes the scope.

## Trainer entry + immediate runtime

| file | role | V2 mapping |
|---|---|---|
| `rl/hybrid_trainer.py` | main trainer entry (`-m rl.hybrid_trainer --mode hybrid --training-mode <mode> --enhanced-features`) | `v2_trainer_bridge_from_legacy_hybrid_trainer` (P1; subprocess wrapper OR V2-native re-implementation) |
| `rl/gpu_optimized_trainer.py`, `rl/stable_gpu_trainer.py` | GPU-tuned training loop variants | trainer-bridge support |
| `rl/supervised_pretrainer.py`, `rl/warm_start.py` | pretraining + warm start | not part of P1 paper-shadow path; defer until live readiness |
| `rl/light_worker.py` | lightweight trainer worker variant | optional reference |

## RL environment + observation contract

| file | role |
|---|---|
| `rl/obs_schema.py` | observation schema |
| `rl/unified_feature_builder.py` | feature assembly for the trainer |
| `rl/gymnasium_wrapper.py` | Gymnasium environment wrapper |
| `rl/hedge_action_space.py` | action space (includes hedge actions) |
| `rl/fee_ratio_reward_shaping.py` | reward shaping by fee/funding ratio |

## Confidence + decision pipeline

| file | role |
|---|---|
| `rl/confidence_gates.py` | confidence thresholds |
| `rl/threshold_ramper.py` | dynamic threshold ramping |
| `rl/decision_trace.py` | decision-trace recording |
| `rl/ta_direction_oracle.py` | TA-based direction oracle |
| `rl/signal_state_manager.py` | per-symbol signal state |

## Multi-policy + MoE

| file | role |
|---|---|
| `rl/moe_router.py` | mixture-of-experts router |
| `rl/scenario_engine.py` | scenario engine |
| `rl/walk_forward_validation.py` | walk-forward validation |

## Microstructure overlays

| file | role |
|---|---|
| `rl/microstructure_overlay.py` | microstructure overlay |
| `rl/microstructure_tf_modifier.py` | timeframe modifier based on microstructure |
| `rl/execution_overlay.py` | execution-side overlay |

## Replay + feedback loop

| file | role |
|---|---|
| `rl/replay_store.py` | replay storage |
| `rl/trade_feedback.py` | per-trade feedback signal |
| `rl/trade_feedback.py` | reward-feedback |

## Checkpoints + promotion

| file | role |
|---|---|
| `rl/checkpoint_manager.py` | save/load/promote checkpoints |
| `rl/promotion_controller.py` | promotion lifecycle (paper → live promotion gate) |

## Safety + pre-publish

| file | role |
|---|---|
| `rl/proposal_hedge_preflight.py` | hedge preflight before publishing proposals |
| `rl/global_safety_checks.py` | global pre-publish safety |
| `rl/liquidation_prevention.py` | liquidation-prevention overlay |
| `rl/churn_veto.py` | churn-veto |
| `rl/position_monitor.py` | position monitor used by trainer |

## Portfolio + exposure

| file | role |
|---|---|
| `rl/portfolio_recovery_allocator.py` | post-loss recovery allocation |
| `rl/portfolio_policy_manager.py` | portfolio policy manager |
| `rl/target_exposure_controller.py` | target exposure controller |

## Symbol / API

| file | role |
|---|---|
| `rl/coinapi_symbol_map.py` | CoinAPI ↔ Binance symbol map |

## Required classification snapshot

| classification | applies to |
|---|---|
| `TRAINER_SOURCE_MAPPED` | yes — all files above are in `v2/legacy_preserved/full_runtime_closure/rl/` with SHA256 in the manifest |
| `TRAINER_CONFIG_MAPPED` | yes — `config.py` (407 KB) + `config_accounts.py` copied; env flags inventoried in startup-baseline matrix |
| `TRAINER_DEPENDENCIES_COMPLETE` | partial — namespace package edges (`ingest`, `binance_websocket`, `hybrid_rule_based_signals`) still need explicit resolution; external deps `torch`/`stable_baselines3`/`cloudpickle`/`gymnasium` deferred until trainer-bridge port |
| `TRAINER_DEPENDENCIES_INCOMPLETE` | flagged — see closure report unresolved imports |
| `TRAINER_GPU_RUNTIME_MAPPED` | yes — `gpu_optimized_trainer.py`, `stable_gpu_trainer.py`, `gpu_cnn_policy.py`, `gpu_saturation.py` preserved |
| `TRAINER_CHECKPOINT_MAPPED` | partial — `checkpoint_manager.py` and `promotion_controller.py` preserved (text only); 139 binary checkpoint blobs INVENTORIED-ONLY in `binary_artifacts_skipped.json`, NOT copied |
| `TRAINER_CHECKPOINT_MISSING` | binary blobs absent — operator must decide whether to commit them or store under a separate non-git location |
| `TRAINER_CONFIDENCE_MAPPED` | yes — `confidence_gates.py`, `threshold_ramper.py`, `decision_trace.py` preserved |
| `TRAINER_CONFIDENCE_INCOMPLETE` | n/a |
| `WRAPPER_NOT_LEGACY_HYBRID_PARITY` | **active blocker** — V2 paper-mode trainer is a momentum stub. With the full rl/ tree now preserved, the trainer-bridge port can be authored to either subprocess-wrap legacy `hybrid_trainer` or re-implement it; either path must enumerate every rl/ helper in the LEGACY_BASELINE_ANALYSIS.md |

## What V2 currently lacks (relative to legacy trainer)

- A real subprocess wrapper around `rl.hybrid_trainer` or a re-implementation of its training loop
- The 139 binary checkpoint blobs (intentionally not in git; operator decides storage)
- An installed `torch` + `stable_baselines3` + `cloudpickle` + `gymnasium` in `.venv`
- A V2-namespaced equivalent of `trainer:predictions` and `wma:proposals` streams (writers, not just readers)
- Walk-forward validation harness
- Promotion controller — currently V2 has no checkpoint promotion lifecycle

The trainer-bridge port descriptor (`claude_port_v2_trainer_bridge`) must produce its `LEGACY_BASELINE_ANALYSIS.md` enumerating each of these items before any V2 trainer-side code is written.
