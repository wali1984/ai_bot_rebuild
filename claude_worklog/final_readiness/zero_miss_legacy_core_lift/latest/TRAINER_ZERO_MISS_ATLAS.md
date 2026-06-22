# Trainer Zero-Miss Atlas

Trainer-specific atlas restricted to `rl/` files with category flags.

## Summary

- Trainer files atlassed: 121
- Total classes: 291
- Total functions: 245
- Total constants: 77
- Files with entrypoint: 40
- Parse errors: 0

## hybrid_trainer.py top-level index

- top_level_items: 35
- classes: 13
- functions: 22

### First 50 top-level items

| Line | Kind | Name |
| ---: | --- | --- |
| 30 | class | `_SafeStream` |
| 88 | class | `WebSocketErrorFilter` |
| 162 | function | `_mdv2_escape` |
| 176 | function | `get_prediction_loop_interval_seconds` |
| 213 | function | `get_post_training_pause_seconds` |
| 252 | function | `get_rollout_params` |
| 350 | function | `_make_subproc_env` |
| 443 | function | `cleanup_resources` |
| 467 | function | `is_shutting_down` |
| 471 | function | `signal_handler` |
| 704 | class | `RTX5080FeatureExtractor` |
| 831 | class | `RTX5080Policy` |
| 843 | class | `HedgeRecoveryPolicy` |
| 901 | function | `create_rtx5080_policy_kwargs` |
| 911 | function | `create_tailored_policy_kwargs` |
| 969 | function | `create_hedge_recovery_policy_kwargs` |
| 998 | function | `safe_close_vecenv` |
| 1123 | function | `get_min_conf_for_tf` |
| 1158 | function | `get_active_symbols` |
| 1196 | class | `GPUOperationTimeout` |
| 1200 | function | `safe_redis_operation` |
| 1233 | function | `gpu_operation_timeout` |
| 1275 | class | `RTX5080Optimizer` |
| 1327 | function | `_lookup_natr_atr_pct` |
| 1354 | function | `_compute_price_target` |
| 1447 | class | `GPUForcedPPO` |
| 10072 | class | `GPUBatchedVecEnv` |
| 10472 | function | `apply_aggressive_gpu_optimizations` |
| 10493 | function | `setup_gpu_memory_optimization` |
| 10515 | class | `GPUForcedEnvWrapper` |
| 10533 | class | `GPUTradingEnvironment` |
| 12506 | class | `HybridConfig` |
| 12613 | class | `HybridTrainer` |
| 57035 | function | `consume_execution_event_for_audit` |
| 57053 | function | `main` |

## Per-file category flags

| File | LOC | training | inference | reward | confidence | checkpoint | gpu | regime | feature | observation | hedge | dca | stop | take_profit | proposal | signal | redis | model |
| --- | ---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ADDITIONAL_CRITICAL_FIXES.py` | 597 | Y |  |  | Y |  |  |  |  |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py` | 1226 | Y |  | Y | Y |  |  |  | Y | Y | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/POSITION_MANAGER.py` | 251 |  |  |  | Y |  |  |  |  |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/WIN_RATE_OPTIMIZER.py` | 410 | Y |  |  | Y |  |  |  |  |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/action_ontology.py` | 521 | Y |  | Y |  | Y |  |  |  |  | Y |  | Y | Y |  | Y |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/advanced_risk_management.py` | 580 | Y |  | Y |  |  |  |  | Y |  |  |  | Y | Y |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/agents/__init__.py` | 8 |  |  |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/agents/masa_agent.py` | 520 | Y | Y |  |  |  | Y |  | Y | Y |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/anti_churn_manager.py` | 341 |  | Y |  |  |  |  |  | Y |  | Y |  | Y | Y |  | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/auto_contraction.py` | 570 | Y |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/batch_utils.py` | 572 | Y | Y |  | Y |  | Y |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/btc_correlation.py` | 283 |  | Y |  |  |  | Y | Y | Y |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/calibrated_confidence.py` | 263 |  |  |  | Y |  |  |  | Y |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/checkpoint_manager.py` | 359 | Y |  |  |  | Y | Y |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/churn_veto.py` | 160 |  |  |  | Y |  |  |  | Y |  | Y |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/coinapi_symbol_map.py` | 393 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/confidence_gates.py` | 584 |  | Y |  | Y |  |  | Y |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/confidence_logger.py` | 224 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/constrained_reward.py` | 298 | Y | Y | Y |  | Y |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/continuous_learner.py` | 662 | Y | Y | Y |  |  |  | Y |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/contract_enrichment.py` | 236 | Y |  |  |  |  |  |  |  |  | Y |  |  |  |  | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/cpu_env.py` | 1114 | Y | Y | Y |  |  | Y |  | Y | Y | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/decision_trace.py` | 73 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/drift_monitor.py` | 465 |  | Y |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/dynamic_position_sizing.py` | 282 |  |  |  | Y |  |  | Y |  |  | Y |  |  |  |  | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/dynamic_runner_hedge.py` | 791 | Y |  |  | Y |  |  |  | Y |  | Y |  | Y |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/enhanced_architectures.py` | 611 | Y | Y | Y |  | Y | Y | Y | Y | Y |  |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/env_factory.py` | 30 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/environment.py` | 1455 | Y |  | Y |  |  |  |  | Y | Y | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/execution_overlay.py` | 75 | Y |  |  |  |  |  |  |  |  |  |  | Y |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/fastlane_detector.py` | 422 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/feature_health.py` | 393 |  |  |  |  |  |  |  | Y | Y |  |  |  |  |  | Y |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/fee_ratio_reward_shaping.py` | 519 | Y | Y | Y | Y |  |  |  | Y | Y | Y |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/global_safety_checks.py` | 554 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_batch_env.py` | 240 | Y |  | Y |  |  | Y |  |  | Y |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_cnn_policy.py` | 207 |  | Y |  |  |  | Y |  | Y | Y |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_env_wrapper.py` | 119 | Y |  | Y |  |  | Y |  |  | Y |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_environment.py` | 1249 | Y | Y | Y |  |  | Y |  | Y | Y | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_forced_ppo.py` | 295 | Y | Y | Y |  |  | Y |  |  | Y |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_optimized_trainer.py` | 329 | Y | Y | Y |  | Y | Y |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_optimizer.py` | 233 | Y |  |  |  |  | Y |  |  |  |  |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_saturation.py` | 522 | Y | Y |  | Y |  | Y |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gymnasium_wrapper.py` | 343 | Y |  | Y |  |  | Y |  |  | Y | Y |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_action_space.py` | 361 |  | Y |  | Y |  |  |  | Y |  | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_budget_governor.py` | 107 | Y |  |  | Y |  |  |  |  |  | Y |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_harvest_engine.py` | 327 | Y |  |  | Y |  |  | Y |  |  | Y |  |  |  | Y | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_manager_v3.py` | 2244 | Y | Y |  | Y |  |  | Y | Y |  | Y |  |  | Y |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_position_manager.py` | 585 | Y |  |  | Y |  |  |  | Y |  | Y |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_reward_functions.py` | 452 | Y |  | Y | Y |  |  |  |  |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_rule_engine.py` | 544 |  |  |  | Y |  |  | Y |  |  | Y |  |  |  |  | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_csv_loader.py` | 350 | Y |  |  |  |  | Y |  | Y |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_data_loader.py` | 331 | Y | Y |  |  |  | Y |  | Y |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_data_manager.py` | 791 | Y |  |  |  | Y | Y |  | Y |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hybrid_action_space.py` | 458 | Y | Y |  | Y |  |  |  | Y |  |  |  |  |  |  | Y |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hybrid_trainer.py` | 57250 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/increase_signal_validator.py` | 307 |  |  |  | Y |  |  |  | Y |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ingestor_quality_router.py` | 538 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/intent_engine.py` | 164 |  | Y |  | Y |  |  | Y |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/light_vec_env.py` | 253 | Y | Y | Y |  |  |  |  |  | Y |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/light_worker.py` | 135 | Y |  | Y |  |  | Y |  |  | Y |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/liquidation_prevention.py` | 779 | Y |  | Y |  |  |  |  |  |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/market_context.py` | 639 | Y |  |  | Y |  |  | Y | Y |  |  |  |  |  | Y |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/masa_supervised_pretrainer.py` | 313 | Y | Y |  |  | Y | Y |  |  |  | Y |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/metrics_tracker.py` | 211 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_aggregator.py` | 469 |  |  |  |  |  |  |  | Y | Y |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_features.py` | 587 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_overlay.py` | 1127 |  |  |  | Y |  |  |  | Y |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_proactive.py` | 1434 | Y | Y |  | Y |  |  | Y | Y |  | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_source_router.py` | 561 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_tf_modifier.py` | 322 |  |  |  | Y |  |  |  | Y |  |  |  | Y | Y |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/minimum_hold_time.py` | 491 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/moe_router.py` | 385 | Y | Y | Y |  | Y | Y | Y | Y |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/move_shock_engine.py` | 224 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/mtf_position_builder.py` | 341 | Y |  |  | Y |  |  | Y | Y |  |  | Y |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/mtf_scenario_tags.py` | 86 |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/obs_schema.py` | 468 |  | Y |  |  | Y |  |  | Y | Y |  |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/orchestrator_worker.py` | 10523 | Y | Y |  | Y |  | Y | Y | Y |  | Y |  | Y | Y | Y | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_aware_features.py` | 506 | Y | Y |  | Y |  | Y | Y | Y |  | Y |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_policy_manager.py` | 1134 | Y | Y |  | Y |  |  |  | Y |  | Y |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_recovery_allocator.py` | 515 |  |  |  | Y |  |  |  | Y |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_risk_features.py` | 465 | Y |  |  |  |  |  |  | Y |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/position_context.py` | 138 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/position_monitor.py` | 638 | Y |  |  | Y |  |  |  | Y |  | Y |  | Y | Y |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/profit_bank.py` | 240 | Y |  |  |  |  |  |  |  |  |  |  |  | Y |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/profit_freespace_rebalancer.py` | 184 | Y |  |  | Y |  |  | Y |  |  |  |  |  |  | Y |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/promotion_controller.py` | 920 | Y | Y |  |  |  |  |  |  |  | Y |  | Y | Y |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_bus.py` | 70 |  |  |  |  |  |  |  |  |  |  |  |  |  | Y |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_hedge_preflight.py` | 74 |  |  |  | Y |  |  |  |  |  | Y |  |  |  | Y |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_schema.py` | 501 | Y | Y |  | Y |  | Y | Y | Y |  | Y |  | Y | Y | Y | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/replay_store.py` | 385 | Y | Y | Y |  |  |  | Y | Y |  |  |  |  |  |  |  |  | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/reward_functions.py` | 902 | Y |  | Y |  |  |  |  |  |  |  |  |  |  |  |  | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scenario_engine.py` | 76 |  |  | Y |  |  |  |  | Y |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/backfill_predictions_stub.py` | 56 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/export_audit_pack.py` | 81 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/healthcheck_trainer_runtime.py` | 167 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/replay_decision.py` | 42 |  |  |  |  |  |  |  |  |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/train_churn_veto.py` | 222 | Y | Y |  | Y |  |  |  | Y |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/signal_state_manager.py` | 554 |  |  |  | Y |  |  |  |  |  | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/stable_gpu_trainer.py` | 0 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/supervised_pretrainer.py` | 372 | Y | Y |  |  | Y | Y |  | Y | Y |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/supervised_trainer.py` | 1083 | Y | Y | Y | Y | Y | Y |  | Y | Y | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ta_direction_oracle.py` | 653 |  |  |  | Y |  |  |  | Y |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/target_exposure_controller.py` | 1073 | Y | Y |  | Y |  |  |  | Y |  | Y |  | Y | Y |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/temperature_calibration.py` | 144 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_move_shock_engine.py` | 109 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_scenario_engine_clamp.py` | 34 |  |  |  |  |  |  |  | Y |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_signal_pipeline.py` | 78 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_tf_aggregator.py` | 34 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tf_aggregator.py` | 188 | Y |  |  | Y |  |  |  |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/threshold_ramper.py` | 301 |  |  |  | Y |  |  |  |  |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/toxicity_shield.py` | 163 | Y |  |  | Y |  |  |  |  |  |  |  |  |  |  |  |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trade_feedback.py` | 936 | Y |  | Y | Y |  |  |  |  |  | Y |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trade_proposal.py` | 238 | Y |  |  | Y |  |  |  |  |  | Y |  | Y | Y | Y | Y |  |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tradeplan_orchestrator.py` | 1427 | Y | Y |  | Y |  |  | Y | Y |  | Y |  | Y | Y | Y | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trainer_enhancements.py` | 519 | Y |  |  | Y |  | Y | Y | Y | Y |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trainer_realtime_mixin.py` | 352 |  |  |  | Y |  |  | Y |  |  |  |  | Y | Y |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/uncertainty.py` | 306 | Y | Y | Y | Y | Y | Y |  | Y |  |  |  |  |  |  | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/underwater_recovery_controller.py` | 1136 | Y |  |  | Y |  |  | Y | Y |  | Y |  |  |  | Y | Y | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/unified_feature_builder.py` | 711 |  |  |  |  |  | Y |  | Y |  |  |  |  |  |  | Y | Y |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/walk_forward_validation.py` | 231 | Y | Y |  |  |  |  |  |  |  |  |  |  |  |  |  | Y | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/warm_start.py` | 389 |  |  |  |  |  |  |  | Y | Y |  |  |  |  |  |  | Y | Y |
