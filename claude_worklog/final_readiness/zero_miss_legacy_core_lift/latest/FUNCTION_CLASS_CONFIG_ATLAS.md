# Function / Class / Config Atlas

Zero-miss legacy core lift: AST + regex atlas over `v2/legacy_owned_runtime/**/*.py`.

## Summary

- Files atlassed: 259
- Total classes: 497
- Total functions: 945
- Total constants: 4214
- Files with `__main__` entrypoint: 107
- Parse errors: 0

## Files per risk category

| Category | Files |
| --- | ---: |
| config | 3 |
| feature_pipeline | 1 |
| ingestor | 13 |
| monitoring | 4 |
| other | 10 |
| risk | 22 |
| scripts | 17 |
| services | 8 |
| trading | 37 |
| trainer | 123 |
| utils | 21 |

## Per-file index

| File | Category | LOC | Classes | Functions | Constants | Redis keys | Exchange refs | Entry |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `v2/legacy_owned_runtime/full_runtime_closure/binance_websocket.py` | other | 610 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/config.py` | config | 6007 | 5 | 11 | 1908 | 10 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/config_accounts.py` | config | 328 | 0 | 9 | 1 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/hybrid_rule_based_signals.py` | other | 436 | 1 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/__init__.py` | risk | 1 | 0 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/adaptive_gate.py` | risk | 775 | 2 | 2 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/assertions.py` | risk | 505 | 1 | 10 | 2 | 3 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/auto_deleverager.py` | risk | 1745 | 4 | 2 | 0 | 7 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/global_breadth.py` | risk | 308 | 0 | 5 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/halt_manager.py` | risk | 614 | 2 | 0 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/hedge_cage_manager.py` | risk | 436 | 5 | 2 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/intelligent_close_guard.py` | risk | 1164 | 2 | 21 | 0 | 4 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/kill_switch.py` | risk | 192 | 0 | 9 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/ltf_reversal.py` | risk | 671 | 0 | 23 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/margin_governor.py` | risk | 876 | 2 | 5 | 0 | 5 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/market_regime.py` | risk | 603 | 0 | 4 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/market_state_contract.py` | risk | 365 | 2 | 6 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/microstructure_toxicity.py` | risk | 316 | 1 | 6 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/phase_controller.py` | risk | 397 | 0 | 10 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/reduce_only_latch.py` | risk | 188 | 0 | 6 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/reversal_detector.py` | risk | 304 | 1 | 5 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/risk_budget_allocator.py` | risk | 619 | 1 | 9 | 5 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/risk_state_machine.py` | risk | 495 | 6 | 2 | 0 | 3 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/shared_risk_gate.py` | risk | 404 | 1 | 3 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/trainer_alignment.py` | risk | 459 | 2 | 5 | 0 | 12 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/risk/trainer_intent.py` | risk | 360 | 1 | 6 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ADDITIONAL_CRITICAL_FIXES.py` | trainer | 597 | 3 | 0 | 1 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py` | trainer | 1226 | 3 | 0 | 2 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/POSITION_MANAGER.py` | trainer | 251 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/WIN_RATE_OPTIMIZER.py` | trainer | 410 | 4 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/action_ontology.py` | trainer | 521 | 0 | 14 | 10 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/advanced_risk_management.py` | trainer | 580 | 6 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/agents/__init__.py` | trainer | 8 | 0 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/agents/masa_agent.py` | trainer | 520 | 7 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/anti_churn_manager.py` | trainer | 341 | 4 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/auto_contraction.py` | trainer | 570 | 5 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/batch_utils.py` | trainer | 572 | 3 | 6 | 2 | 0 | 1 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/btc_correlation.py` | trainer | 283 | 0 | 7 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/calibrated_confidence.py` | trainer | 263 | 1 | 1 | 0 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/checkpoint_manager.py` | trainer | 359 | 1 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/churn_veto.py` | trainer | 160 | 2 | 2 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/coinapi_symbol_map.py` | trainer | 393 | 2 | 1 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/confidence_gates.py` | trainer | 584 | 5 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/confidence_logger.py` | trainer | 224 | 2 | 0 | 0 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/constrained_reward.py` | trainer | 298 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/continuous_learner.py` | trainer | 662 | 3 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/contract_enrichment.py` | trainer | 236 | 1 | 4 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/cpu_env.py` | trainer | 1114 | 1 | 2 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/decision_trace.py` | trainer | 73 | 0 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/drift_monitor.py` | trainer | 465 | 4 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/dynamic_position_sizing.py` | trainer | 282 | 0 | 3 | 3 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/dynamic_runner_hedge.py` | trainer | 791 | 8 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/enhanced_architectures.py` | trainer | 611 | 4 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/env_factory.py` | trainer | 30 | 0 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/environment.py` | trainer | 1455 | 3 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/execution_overlay.py` | trainer | 75 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/fastlane_detector.py` | trainer | 422 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/feature_health.py` | trainer | 393 | 4 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/fee_ratio_reward_shaping.py` | trainer | 519 | 3 | 3 | 6 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/global_safety_checks.py` | trainer | 554 | 5 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_batch_env.py` | trainer | 240 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_cnn_policy.py` | trainer | 207 | 2 | 2 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_env_wrapper.py` | trainer | 119 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_environment.py` | trainer | 1249 | 1 | 2 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_forced_ppo.py` | trainer | 295 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_optimized_trainer.py` | trainer | 329 | 2 | 0 | 0 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_optimizer.py` | trainer | 233 | 1 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gpu_saturation.py` | trainer | 522 | 4 | 6 | 6 | 0 | 1 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/gymnasium_wrapper.py` | trainer | 343 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_action_space.py` | trainer | 361 | 5 | 2 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_budget_governor.py` | trainer | 107 | 2 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_harvest_engine.py` | trainer | 327 | 2 | 2 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_manager_v3.py` | trainer | 2244 | 2 | 2 | 0 | 8 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_position_manager.py` | trainer | 585 | 4 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_reward_functions.py` | trainer | 452 | 3 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hedge_rule_engine.py` | trainer | 544 | 5 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_csv_loader.py` | trainer | 350 | 1 | 1 | 0 | 0 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_data_loader.py` | trainer | 331 | 1 | 1 | 0 | 0 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/historical_data_manager.py` | trainer | 791 | 2 | 1 | 0 | 0 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hybrid_action_space.py` | trainer | 458 | 5 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/hybrid_trainer.py` | trainer | 57250 | 13 | 22 | 3 | 144 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/increase_signal_validator.py` | trainer | 307 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ingestor_quality_router.py` | trainer | 538 | 6 | 2 | 1 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/intent_engine.py` | trainer | 164 | 2 | 1 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/light_vec_env.py` | trainer | 253 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/light_worker.py` | trainer | 135 | 0 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/liquidation_prevention.py` | trainer | 779 | 7 | 6 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/market_context.py` | trainer | 639 | 5 | 2 | 1 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/masa_supervised_pretrainer.py` | trainer | 313 | 2 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/metrics_tracker.py` | trainer | 211 | 2 | 0 | 0 | 5 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_aggregator.py` | trainer | 469 | 3 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_features.py` | trainer | 587 | 3 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_overlay.py` | trainer | 1127 | 7 | 3 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_proactive.py` | trainer | 1434 | 3 | 2 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_source_router.py` | trainer | 561 | 4 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_tf_modifier.py` | trainer | 322 | 2 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/minimum_hold_time.py` | trainer | 491 | 3 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/moe_router.py` | trainer | 385 | 3 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/move_shock_engine.py` | trainer | 224 | 2 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/mtf_position_builder.py` | trainer | 341 | 1 | 0 | 5 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/mtf_scenario_tags.py` | trainer | 86 | 0 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/obs_schema.py` | trainer | 468 | 4 | 7 | 2 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/orchestrator_worker.py` | trainer | 10523 | 3 | 1 | 13 | 26 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_aware_features.py` | trainer | 506 | 3 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_policy_manager.py` | trainer | 1134 | 4 | 2 | 0 | 7 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_recovery_allocator.py` | trainer | 515 | 2 | 3 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/portfolio_risk_features.py` | trainer | 465 | 3 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/position_context.py` | trainer | 138 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/position_monitor.py` | trainer | 638 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/profit_bank.py` | trainer | 240 | 2 | 2 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/profit_freespace_rebalancer.py` | trainer | 184 | 2 | 3 | 1 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/promotion_controller.py` | trainer | 920 | 5 | 1 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_bus.py` | trainer | 70 | 0 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_hedge_preflight.py` | trainer | 74 | 0 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/proposal_schema.py` | trainer | 501 | 3 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/replay_store.py` | trainer | 385 | 2 | 1 | 5 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/reward_functions.py` | trainer | 902 | 5 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scenario_engine.py` | trainer | 76 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/backfill_predictions_stub.py` | trainer | 56 | 0 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/export_audit_pack.py` | trainer | 81 | 0 | 2 | 0 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/healthcheck_trainer_runtime.py` | trainer | 167 | 0 | 6 | 0 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/replay_decision.py` | trainer | 42 | 0 | 1 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/scripts/train_churn_veto.py` | trainer | 222 | 0 | 7 | 1 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/signal_state_manager.py` | trainer | 554 | 4 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/stable_gpu_trainer.py` | trainer | 0 | 0 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/supervised_pretrainer.py` | trainer | 372 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/supervised_trainer.py` | trainer | 1083 | 2 | 6 | 8 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/ta_direction_oracle.py` | trainer | 653 | 0 | 7 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/target_exposure_controller.py` | trainer | 1073 | 6 | 2 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/temperature_calibration.py` | trainer | 144 | 1 | 1 | 0 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_move_shock_engine.py` | trainer | 109 | 1 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_scenario_engine_clamp.py` | trainer | 34 | 0 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_signal_pipeline.py` | trainer | 78 | 2 | 0 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tests/test_tf_aggregator.py` | trainer | 34 | 0 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tf_aggregator.py` | trainer | 188 | 0 | 4 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/threshold_ramper.py` | trainer | 301 | 1 | 1 | 0 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/toxicity_shield.py` | trainer | 163 | 2 | 2 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trade_feedback.py` | trainer | 936 | 4 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trade_proposal.py` | trainer | 238 | 1 | 3 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/tradeplan_orchestrator.py` | trainer | 1427 | 2 | 17 | 1 | 7 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trainer_enhancements.py` | trainer | 519 | 4 | 0 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/trainer_realtime_mixin.py` | trainer | 352 | 1 | 0 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/uncertainty.py` | trainer | 306 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/underwater_recovery_controller.py` | trainer | 1136 | 2 | 7 | 0 | 9 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/unified_feature_builder.py` | trainer | 711 | 4 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/walk_forward_validation.py` | trainer | 231 | 1 | 1 | 0 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/rl/warm_start.py` | trainer | 389 | 2 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/audit_orchestrator_last30m.py` | scripts | 294 | 0 | 9 | 0 | 6 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/audit_trade_attribution.py` | scripts | 109 | 0 | 3 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/check_trainer_signal_health.py` | scripts | 289 | 0 | 11 | 0 | 7 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/close_all_positions.py` | scripts | 470 | 1 | 5 | 0 | 0 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/monitor_orchestrator_shadow.py` | scripts | 131 | 0 | 3 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/monitor_trainer_predictions.py` | scripts | 381 | 1 | 8 | 11 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/monitor_trainer_prices.py` | scripts | 336 | 1 | 10 | 13 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/test_hedge_build.py` | scripts | 294 | 0 | 7 | 0 | 0 | 1 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/trace_trade_lifecycle.py` | scripts | 859 | 1 | 11 | 2 | 5 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/validate_trader_alignment.py` | scripts | 126 | 1 | 4 | 4 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/verify_trader_consumption.py` | scripts | 73 | 0 | 2 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/scripts/why_hedged_timeline.py` | scripts | 494 | 0 | 20 | 1 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/services/__init__.py` | services | 30 | 0 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/services/data_archiver.py` | services | 439 | 1 | 2 | 0 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/services/liquidation_intelligence.py` | services | 174 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/services/live_decision_evaluator.py` | services | 483 | 1 | 6 | 1 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/services/onchain_analyzer.py` | services | 561 | 1 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/services/portfolio_publisher.py` | services | 89 | 0 | 2 | 0 | 3 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/services/portfolio_state.py` | services | 482 | 5 | 5 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/services/service_monitor.py` | services | 489 | 1 | 1 | 9 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/telegram_alerts.py` | other | 2243 | 1 | 1 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/action_constants.py` | trading | 240 | 2 | 3 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/adaptive_edge_gate.py` | trading | 1569 | 7 | 3 | 0 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/adaptive_hedge_builder.py` | trading | 610 | 3 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/adaptive_threshold_engine.py` | trading | 794 | 2 | 1 | 0 | 3 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/assert_governor.py` | trading | 31 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/base_executor.py` | trading | 2132 | 3 | 1 | 0 | 1 | 5 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/churn_prevention.py` | trading | 572 | 5 | 2 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/coinank_signal_adapter.py` | trading | 225 | 2 | 4 | 0 | 11 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/depth_execution_gate.py` | trading | 458 | 2 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/dynamic_adaptive_hedge.py` | trading | 1126 | 4 | 1 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/dynamic_adaptive_stops.py` | trading | 1063 | 2 | 1 | 0 | 11 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/dynamic_margin_manager.py` | trading | 393 | 1 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/dynamic_tp_engine.py` | trading | 1468 | 2 | 0 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/execution_engine.py` | trading | 348 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/exit_coordinator.py` | trading | 489 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/fee_ratio_gate.py` | trading | 412 | 2 | 4 | 5 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/hedge_context.py` | trading | 1308 | 3 | 4 | 0 | 14 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/hedge_intelligence_engine.py` | trading | 947 | 6 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/hedge_pair_coordinator.py` | trading | 337 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/leg_manager.py` | trading | 629 | 2 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/lifecycle_controller.py` | trading | 104 | 2 | 0 | 2 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/maker_execution.py` | trading | 661 | 4 | 3 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/market_intelligence.py` | trading | 1806 | 1 | 28 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/market_regime_detector.py` | trading | 799 | 2 | 0 | 0 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/opportunity_tracker.py` | trading | 211 | 1 | 0 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/position_reporter.py` | trading | 429 | 1 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/redesign_v2_helpers.py` | trading | 903 | 0 | 18 | 0 | 5 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/redis_stream_reader.py` | trading | 412 | 1 | 1 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/signal_router.py` | trading | 349 | 1 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/smart_entry_gate.py` | trading | 865 | 4 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/stealth_dynamic_integration.py` | trading | 222 | 1 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/stealth_stops.py` | trading | 6972 | 2 | 3 | 0 | 24 | 2 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/trader-asjad.py` | trading | 47 | 0 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/trader.py` | trading | 24277 | 1 | 3 | 2 | 38 | 4 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/trading/trader_websocket_helper.py` | trading | 866 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/ai_coins_manager.py` | utils | 309 | 1 | 1 | 1 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/binance_rate_limiter.py` | utils | 315 | 2 | 7 | 1 | 2 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/data_manager.py` | utils | 97 | 1 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/data_normalizer.py` | utils | 578 | 4 | 3 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/decision_bus.py` | utils | 75 | 0 | 4 | 1 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/ensemble_diagnostics.py` | utils | 50 | 0 | 3 | 1 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/healthbeat.py` | utils | 58 | 0 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/interpreter_guard.py` | utils | 24 | 0 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/interrupt_lock.py` | utils | 69 | 0 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/logger.py` | utils | 47 | 0 | 1 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/metrics.py` | utils | 21 | 0 | 2 | 1 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/preflight.py` | utils | 60 | 0 | 4 | 0 | 4 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/redis_client.py` | utils | 357 | 1 | 5 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/redis_hardening.py` | utils | 28 | 0 | 2 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/redis_key_audit.py` | utils | 232 | 0 | 6 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/runtime_flags.py` | utils | 134 | 0 | 6 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/signal_publish.py` | utils | 125 | 0 | 3 | 0 | 1 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/signal_schema.py` | utils | 85 | 0 | 3 | 2 | 0 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/symbol_manager.py` | utils | 694 | 0 | 19 | 5 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/unified_position_loader.py` | utils | 287 | 0 | 5 | 0 | 3 | 0 |  |
| `v2/legacy_owned_runtime/full_runtime_closure/utils/websocket_limits.py` | utils | 131 | 2 | 0 | 0 | 0 | 0 |  |
| `v2/legacy_owned_runtime/ingest/technical_analysis.py` | ingestor | 762 | 1 | 1 | 0 | 4 | 0 | Y |
| `v2/legacy_owned_runtime/ingestors/live_coinank.py` | ingestor | 2309 | 0 | 31 | 34 | 22 | 0 | Y |
| `v2/legacy_owned_runtime/monitoring/deep_troubleshooter.py` | monitoring | 3943 | 6 | 1 | 1 | 12 | 0 | Y |
| `v2/legacy_owned_runtime/monitoring/live_system_auditor.py` | monitoring | 1834 | 4 | 1 | 0 | 6 | 0 | Y |
| `v2/legacy_owned_runtime/monitoring/oom_monitor.py` | monitoring | 401 | 2 | 1 | 7 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/monitoring/regression_alarms.py` | monitoring | 445 | 1 | 1 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/config.py` | config | 6007 | 5 | 11 | 1908 | 10 | 0 |  |
| `v2/legacy_owned_runtime/startup_baseline/feature_pipeline.py` | feature_pipeline | 1437 | 2 | 1 | 0 | 12 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/liquidation_bridge.py` | ingestor | 227 | 0 | 6 | 9 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/liquidation_levels_engine.py` | ingestor | 492 | 1 | 6 | 12 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_binance.py` | ingestor | 2642 | 2 | 30 | 22 | 11 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_binance_liquidations.py` | ingestor | 921 | 0 | 13 | 13 | 9 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_coinank.py` | ingestor | 2754 | 0 | 41 | 48 | 28 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_coinank_global_aggregator.py` | ingestor | 376 | 0 | 8 | 1 | 11 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_coinapi_v1.py` | ingestor | 739 | 2 | 4 | 8 | 2 | 1 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_coinapi_wsds.py` | ingestor | 1735 | 3 | 1 | 0 | 1 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_kucoin.py` | ingestor | 896 | 0 | 26 | 15 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/live_technical_analysis.py` | ingestor | 158 | 1 | 1 | 1 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ingest/realtime_price_provider.py` | ingestor | 1146 | 5 | 6 | 1 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/monitor_portfolio_asjad.py` | other | 468 | 1 | 5 | 9 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/monitor_portfolio_primary.py` | other | 471 | 1 | 5 | 9 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/monitor_system_memory.py` | other | 466 | 1 | 1 | 11 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/ohlcv_resampler_hotfix.py` | other | 259 | 1 | 1 | 8 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/rl/hybrid_trainer.py` | trainer | 57250 | 13 | 22 | 3 | 144 | 1 | Y |
| `v2/legacy_owned_runtime/startup_baseline/rl/orchestrator_worker.py` | trainer | 10523 | 3 | 1 | 13 | 26 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/scripts/health_probe.py` | scripts | 423 | 1 | 1 | 3 | 6 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/scripts/memory_monitor.py` | scripts | 236 | 0 | 6 | 9 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/scripts/monitor_trainer_predictions.py` | scripts | 381 | 1 | 8 | 11 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/scripts/paralysis_detectors.py` | scripts | 242 | 1 | 9 | 0 | 3 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/scripts/validate_symbol_universe_data.py` | scripts | 261 | 0 | 4 | 0 | 7 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/system_telegram_monitor.py` | other | 743 | 1 | 1 | 0 | 2 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/trading/trader-asjad.py` | trading | 47 | 0 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/startup_baseline/trading/trader.py` | trading | 24277 | 1 | 3 | 2 | 38 | 4 | Y |
| `v2/legacy_owned_runtime/startup_baseline/vpn_monitor.py` | other | 389 | 1 | 1 | 0 | 0 | 0 | Y |
| `v2/legacy_owned_runtime/tools/health.py` | other | 17 | 0 | 1 | 0 | 0 | 0 |  |
