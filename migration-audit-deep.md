# Deep Feature & Function Migration Audit

**Generated:** 2026-05-15  
**Scope:** Function/class-level audit of every major subsystem inside the legacy trainer, trading engine, and supporting modules  
**Legend:** ✅ Migrated natively | ⚠️ Partially migrated / schema only | 🔁 Bridge only (reads legacy output) | ❌ Not started

---

## 1. TRAINING LOOP & GPU ENGINE

**File:** `rl/hybrid_trainer.py` (57,250 lines) — `HybridTrainer` class

| Function / Capability | Lines | V2 Status | Notes |
|---|---|---|---|
| `run_hybrid_training_with_predictions()` | 51619–51726 | ❌ | Main orchestration loop — PPO train + predict alternation |
| `train()` — core SB3 loop | 32187–33209 | ❌ | SubprocVecEnv rollout collection, gradient steps |
| `collect_rollouts()` | 9976–10034 | ❌ | Custom rollout buffer fill with GPU batching |
| `_train_return_head()` | 1638–1694 | ❌ | Dual-head return prediction (MASA) |
| `setup_models()` | 31120–31693 | ❌ | Model init from checkpoint or fresh, SB3 PPO + MASA |
| `create_vec_env()` | 30867–30946 | ❌ | SubprocVecEnv / DummyVecEnv / GPU batch env creation |
| `_create_subproc_vec_env()` | 31027–31090 | ❌ | 8-worker subprocess env factory |
| `_create_gpu_batched_vec_env()` | 31091–31119 | ❌ | RTX 5080-specific batched env |
| `warm_gpu_memory()` | 30756–30790 | ❌ | Pre-warm CUDA memory before training |
| `_pre_warm_gpu()` | 48167–48217 | ❌ | Force GPU allocation to avoid first-step OOM |
| `_check_and_fix_ppo_collapse()` | 31694–31807 | ❌ | PPO entropy collapse detection + fix |
| `_periodic_collapse_check()` | 31808–32066 | ❌ | Every-N-loops collapse monitor |
| `apply_aggressive_gpu_optimizations()` | 10472–10492 | ❌ | torch.compile, channels-last, flash attention |
| `setup_gpu_memory_optimization()` | 10493–10514 | ❌ | Memory fragmentation reduction, allocator config |
| `_monitor_cuda_memory()` | 48228–48319 | ❌ | Per-step CUDA memory tracking |
| `_cleanup_cuda_memory()` | 48320–48329 | ❌ | Explicit gc + cache clear |
| `_check_gpu_health()` | 48330–48345 | ❌ | GPU utilization guard |
| `_check_and_adjust_gpu_scaling()` | 20571–20647 | ❌ | Auto-scale batch size based on GPU stats |
| `RTX5080FeatureExtractor` (class) | 704–830 | ❌ | Custom CNN feature extractor for RTX 5080 |
| `RTX5080Policy` (class) | 831–842 | ❌ | Actor-critic policy with RTX 5080 optimizations |
| `HedgeRecoveryPolicy` (class) | 843–900 | ❌ | Separate policy for hedge/recovery actions |
| `GPUForcedPPO` (class) | 1447–1638 | ❌ | PPO subclass forcing GPU operations |
| `GPUBatchedVecEnv` (class) | 10072–10471 | ❌ | 128-env GPU-batched VecEnv implementation |
| `GPUTradingEnvironment` (class) | 10533–12505 | ❌ | Full GPU trading env (state, step_gpu, reset_gpu) |

---

## 2. INFERENCE / PREDICTION PIPELINE

| Function / Capability | Lines | V2 Status | Notes |
|---|---|---|---|
| `run_realtime_predictions()` | 51619+ | ❌ | Main prediction loop, runs in parallel with training |
| `_generate_realtime_predictions()` | 52012–54086 | ❌ | Per-symbol per-timeframe prediction cycle |
| `_make_batch_predictions_gpu()` | 40768–43803 | ❌ | GPU-batched inference for all symbols at once |
| `_make_prediction()` | 54208–54251 | ❌ | Single obs vector → action + confidence |
| `_make_ppo_prediction()` | 54296–56812 | ❌ | PPO policy forward pass with MASA blending |
| `_make_rule_based_prediction()` | 56813–56926 | ❌ | Rule-based fallback when RL confidence low |
| `_blend_masa_ppo_logits()` | 21029–21146 | ❌ | Dynamic MASA/PPO logit blending |
| `_setup_masa_blending()` | 9879–9975 | ❌ | Adaptive weight function based on confidence |
| `_update_dynamic_masa_weight()` | 13366–13416 | ❌ | Live MASA weight update from performance |
| `_calculate_confidence_gpu()` | 40484–40506 | ❌ | GPU softmax → calibrated confidence score |
| `_ensure_inference_policy_snapshot()` | 40589–40682 | ❌ | Copy policy weights to inference snapshot (thread-safe) |
| `_refresh_inference_policy_snapshot()` | 40683–40758 | ❌ | Periodic weight sync between train and inference threads |
| `_get_policy_for_inference()` | 40759–40767 | ❌ | Select snapshot vs live policy |
| `_convert_features_to_array()` | 54087–54207 | ❌ | Dict → float32 numpy array for model input |
| `_preprocess_features_gpu()` | 40313–40483 | ❌ | Batch feature preprocessing on GPU |
| `_normalize_feature_vector_robust()` | 40294–40312 | ❌ | Robust normalization with outlier clipping |
| `_get_or_build_feature_key_order()` | 40240–40293 | ❌ | Stable key ordering for obs tensor |
| `_audit_post_training_signals()` | 48346–48440 | ❌ | Post-training prediction quality check |
| `_record_prediction_for_accuracy()` | 37790–37820 | ❌ | Log prediction for later accuracy eval |
| `_evaluate_prediction_accuracy()` | 37821–37923 | ❌ | Rolling accuracy tracking per symbol/TF |
| `_get_feature_age_snapshot()` | 51727–51823 | ❌ | Feature freshness per key, staleness flagging |
| `_update_reversal_override()` | 51824–52011 | ❌ | Reversal signal injection into features |

---

## 3. CONFIDENCE SYSTEM

### 3a. `rl/calibrated_confidence.py` (263 lines)
| Function | V2 Status |
|---|---|
| `CalibratedConfidenceManager` — temperature scaling on logits | ❌ |
| `apply_temperature_to_logit()` — Platt scaling | ❌ |
| `get_calibrated_confidence()` — raw → calibrated probability | ❌ |
| `log_prediction_comparison()` — raw vs calibrated audit log | ❌ |

### 3b. `rl/confidence_gates.py` (583 lines)
| Function | V2 Status |
|---|---|
| `SymbolConfidenceTracker` — per-symbol rolling hit-rate tracker | ❌ |
| `add_prediction()` — record outcome | ❌ |
| `check_boost_eligibility()` — check if symbol warrants expanded coverage | ❌ |
| `ConfidenceGateManager` — multi-symbol gate orchestrator | ❌ |
| `update_symbol_prediction()` | ❌ |
| `check_symbol_expansion_allowed()` — dynamic symbol universe control | ❌ |
| `_maybe_update_boost_status()` — auto-enable boost mode | ❌ |

### 3c. `rl/threshold_ramper.py` (301 lines)
| Function | V2 Status |
|---|---|
| `ThresholdRamper` — auto-ramp min confidence threshold | ❌ |
| `get_current_threshold()` — reads from Redis | ❌ |
| `check_safety()` — guard before any ramp | ❌ |
| `should_ramp_up()` — win-rate + calibration check | ❌ |
| `ramp_threshold()` — write new threshold to Redis | ❌ |
| `auto_ramp()` — full cycle: check → ramp → log | ❌ |

### 3d. Inside `HybridTrainer`
| Function | V2 Status |
|---|---|
| `_init_confidence_pipeline()` | ❌ |
| `_get_min_conf_entry()` — per-symbol, per-timeframe threshold | ❌ |
| `_get_min_conf_exit()` | ❌ |
| `_compute_contextual_conf_threshold()` — regime-adjusted threshold | ❌ |
| `get_min_conf_for_tf()` (module-level) | ❌ |
| `check_multi_timeframe_confidence()` | ❌ |
| `summarize_tf_state()` | ❌ |
| `classify_trade_opportunity()` | ❌ |

---

## 4. SIGNAL GENERATION & ROUTING

| Function / Capability | Lines | V2 Status |
|---|---|---|
| `_publish_signal_payload()` | 17108 | ❌ |
| `_publish_signal_unified()` | 17120 | ❌ |
| `_emit_proposal()` | 17519 | ❌ |
| `_publish_decisions_batch()` | 44906 | ❌ |
| `_publish_decisions_batch_v2()` | 44983 | ❌ |
| `_publish_decisions_with_reasoning()` | 47978 | ❌ |
| `_publish_buffered_signals()` | 37986 | ❌ |
| `_aggregate_signals_by_symbol()` | 34802 | ❌ |
| `_deconflict_signals()` | 34856 | ❌ |
| `_deconflict_signals_from_grouped()` | 35266 | ❌ |
| `_emit_tf_conflict_signals()` | 35044 | ❌ |
| `_inject_mtf_dca_signals()` | 35970 | ❌ |
| `_apply_direction_stability_gate()` | 36029 | ❌ |
| `_apply_direction_alignment_gate()` | 36098 | ❌ |
| `_apply_aggregation()` | 36823 | ❌ |
| `_build_tf_stack()` | 18489 | ❌ |
| `_is_stack_aligned()` | 18681 | ❌ |
| `_build_trade_signal()` | 3138 | ❌ |
| `_build_signal_payload_margin_v1()` | 4634 | ❌ |
| `_emit_structured_decision_log()` | 9458 | ❌ |
| `_publish_skip_event()` | 18279 | ❌ |
| `_publish_exec_event()` | 18286 | ❌ |
| `_maybe_emit_canary()` | 18322 | ❌ |
| `_log_decision_record()` | 43804 | ❌ |
| `_emit_decision_coverage_sweep()` | 43964 | ❌ |
| `should_generate_signal()` | 27514 | ❌ |
| `_generate_contextual_action()` | 47549 | ❌ |
| `_generate_intelligent_reasoning()` | 56927 | ❌ |

---

## 5. REGIME DETECTION

| Function / Capability | Lines | V2 Status |
|---|---|---|
| `_classify_market_regime()` | 24651 | ❌ |
| `_classify_market_regime_per_symbol_tf()` | 24580 | ❌ |
| `_compute_regime_axes()` | 25222 | ❌ — 5 axes: trend/momentum/vol/sentiment/cross-market |
| `_determine_structural_regime()` | 25057 | ❌ |
| `_compute_structural_metrics()` | 24863 | ❌ |
| `_update_structural_series()` | 24818 | ❌ — rolling 4H close series |
| `_structural_regime_severity()` | 24853 | ❌ |
| `_update_recovery_failures()` | 24965 | ❌ |
| `_regime_one_hot()` | 25402 | ❌ — regime as feature vector |
| `_regime_label_one_hot()` | 25424 | ❌ |
| `_regime_action_allowed()` | 25435 | ❌ — gate entries by regime |
| `_simple_regime_classification()` | 25774 | ❌ |
| `detect_market_regime()` | 27072 | ❌ |
| `get_regime_for_all_timeframes()` | 27150 | ❌ |
| `_get_market_context()` | 18751 | ❌ |
| `get_dynamic_market_state()` | 23533 | ❌ |
| `_analyze_regime_with_lstm()` | 25847 | ❌ — LSTM regime classification |
| `_extract_lstm_regime_features()` | 25945 | ❌ |
| `_fallback_temporal_analysis()` | 26007 | ❌ |
| `_heuristic_regime_from_features()` | 26033 | ❌ |
| `_classify_volatility_regime()` | 26146 | ❌ |
| `_analyze_liquidity_conditions()` | 26177 | ❌ |
| `_classify_sentiment_regime()` | 26205 | ❌ |
| `_analyze_cross_market_regime()` | 26246 | ❌ |
| `_calculate_regime_consensus()` | 25583 | ❌ |
| `_determine_trading_bias()` | 25602 | ❌ |
| `_check_for_regime_alerts()` | 25638 | ❌ |

---

## 6. MULTI-TIMEFRAME (MTF) SYSTEM

| Function / Capability | V2 Status |
|---|---|
| `check_multi_timeframe_confidence()` | ❌ |
| `check_multi_tf_confirmation()` | ❌ |
| `get_tf_predictions_for_symbol()` — reads predictions from all TFs | ❌ |
| `_get_latest_predictions()` | ❌ |
| `_build_tf_stack()` — per-symbol TF alignment stack | ❌ |
| `_is_stack_aligned()` — require N of M TFs to agree | ❌ |
| `_inject_mtf_dca_signals()` — DCA when MTF aligned | ❌ |
| `_apply_direction_alignment_gate()` | ❌ |
| `_log_tf_stack()` | ❌ |

---

## 7. STOP LOSS SYSTEMS

### 7a. Stealth Stops — `trading/stealth_stops.py` (6,972 lines)
| Class / Function | V2 Status |
|---|---|
| `StealthStop` (dataclass) — stop level, trail pct, TP target, side | ❌ |
| `StealthStopMonitor` — main manager, monitors all open stops | ❌ |
| `_monitor_loop()` — background loop, checks every price tick | ❌ |
| `add_stop()` — register new stop for position | ❌ |
| `add_take_profit()` — add TP with trailing or static target | ❌ |
| `remove_stop()` / `remove_all_for_symbol()` | ❌ |
| `calculate_adaptive_stop_levels()` — ATR + volatility → stop distance | ❌ |
| `_atr_adaptive_trail_distance()` — ATR-based trail compression | ❌ |
| `_microstructure_trail_compression()` — tighten trail in thin markets | ❌ |
| `_adaptive_trail_v2_check()` | ❌ |
| `_recalculate_tp_dynamic()` — live TP recalculation on price move | ❌ |
| `_recalculate_sl_dynamic()` — live SL recalculation | ❌ |
| `_sanitize_trailing_tp_trigger()` — sanity check before TP fire | ❌ |
| `_execute_stop()` — market/limit order to close | ❌ |
| `_execute_hybrid_limit_order()` — prefer limit, fallback market | ❌ |
| `_execute_market_order()` — emergency market close | ❌ |
| `_execute_ioc_order()` — IOC fill or cancel | ❌ |
| `_finalize_stop_execution()` | ❌ |
| `_ramp_scale_up_winner()` — add size on trailing TP hit | ❌ |
| `_hedge_tp_guard()` — check hedge coverage before TP | ❌ |
| `_get_hedged_tp_protective_lock()` | ❌ |
| `_maybe_propose_profit_hedge()` — stealth → hedge proposal on profit | ❌ |
| `_emit_orchestrator_proposal()` — emit to orchestrator stream | ❌ |
| `_publish_trail_exit_feedback()` | ❌ |
| `_publish_profit_exit_feedback()` | ❌ |
| `_publish_loss_exit_feedback()` | ❌ |
| `_update_exchange_backstop()` — place exchange native SL order | ❌ |
| `_reconcile_with_exchange()` — sync stop state with Binance | ❌ |
| `get_profit_lock_context()` | ❌ |
| `_check_ride_move_flag()` | ❌ |
| `_is_stress_mode()` | ❌ |

### 7b. Dynamic Adaptive Stops — `trading/dynamic_adaptive_stops.py` (1,063 lines)
| Class / Function | V2 Status |
|---|---|
| `AdaptiveStopLevels` (dataclass) — initial/trail/TP/volatility | ❌ |
| `DynamicAdaptiveStops` — regime-sensitive stop calculator | ❌ |
| Trend regime: tighter trail, wider SL | ❌ |
| Volatile regime: wider trail, reduce position | ❌ |
| Range regime: tight SL, quick TP | ❌ |
| `_calculate_regime_stops()` | ❌ |
| `_apply_microstructure_adjustment()` | ❌ |
| `_get_volatility_multiplier()` | ❌ |
| ATR-based SL sizing | ❌ |

### 7c. Stealth Dynamic Integration — `trading/stealth_dynamic_integration.py` (207 lines)
| Class / Function | V2 Status |
|---|---|
| `StealthDynamicIntegration` | ❌ |
| `update_trailing_stop()` — called every price tick | ❌ |
| `create_stealth_dynamic_integration()` | ❌ |

---

## 8. TAKE PROFIT SYSTEMS

### 8a. Dynamic TP Engine — `trading/dynamic_tp_engine.py` (1,468 lines)
| Class / Function | V2 Status |
|---|---|
| `DynamicTPDecision` (dataclass) — TP price, trail pct, reason | ❌ |
| `DynamicTPEngine` — full TP management | ❌ |
| `calculate_tp_target()` — ROE-based, price-based, ATR-based | ❌ |
| `_tp_from_roe()` — map ROE % target to price | ❌ |
| `_tp_from_atr()` — ATR multiple TP | ❌ |
| `_tp_from_support_resistance()` | ❌ |
| `_validate_tp_vs_liquidation()` | ❌ |
| Trailing TP arming logic | ❌ |
| Partial TP on laddered ROE levels | ❌ |
| `_evaluate_exit_and_hedge()` | ❌ |

### 8b. Inside `HybridTrainer`
| Function | V2 Status |
|---|---|
| `_validate_adaptive_profit_taking()` | ❌ |
| `_check_profit_ladder()` — check if ROE ladder hit | ❌ |
| `_proactive_profit_scanner()` — scan all positions for TP opportunity | ❌ |
| `_evaluate_microstructure_quick_profit()` | ❌ |
| `calculate_dynamic_thresholds()` | ❌ |

### 8c. ROI Kill Switch
| Function | V2 Status |
|---|---|
| `_check_risk_gates()` → ROI-based kill | ❌ |
| `update_risk_metrics()` — track equity drawdown | ❌ |
| `_update_drawdown_tracking()` | ❌ |
| Emergency brake on max daily loss | ❌ |

---

## 9. HEDGE SYSTEMS (4 layers)

### 9a. HedgeManagerV3 — `rl/hedge_manager_v3.py` (2,244 lines)
| Function | V2 Status |
|---|---|
| `HedgeManagerV3` — main hedge decision engine | ❌ |
| `decide_for_symbol()` — full hedge evaluation per symbol | ❌ |
| `compute_continuation_and_toxicity()` — momentum vs toxicity score | ❌ |
| `compute_pds()` — position distress score | ❌ |
| `generate_signals()` — hedge signals for all accounts | ❌ |
| `_resolve_hedge_leverage()` | ❌ |

### 9b. Hedge Harvest Engine — `rl/hedge_harvest_engine.py` (327 lines)
| Function | V2 Status |
|---|---|
| `HedgeHarvestEngine` — close profitable hedges | ❌ |
| `decide()` — harvest hedge when profitable | ❌ |
| `build_signal()` | ❌ |
| `emit_proposal()` | ❌ |

### 9c. Hedge Budget Governor — `rl/hedge_budget_governor.py` (107 lines)
| Function | V2 Status |
|---|---|
| `HedgeBudgetGovernor` — cap total hedge margin | ❌ |
| `compute_allowed_margin()` — returns max hedge margin given portfolio | ❌ |

### 9d. Dynamic Runner Hedge — `rl/dynamic_runner_hedge.py` (791 lines)
| Function | V2 Status |
|---|---|
| `DynamicRunnerHedgeManager` — hedge runner that follows trend | ❌ |
| `should_evaluate()` — check if symbol needs hedge eval | ❌ |
| `update_position_context()` | ❌ |
| `evaluate_actions()` — OPEN_HEDGE / CLOSE_HEDGE / SCALE_HEDGE | ❌ |
| `_calculate_hedge_size()` — ROE-based hedge size | ❌ |
| `record_intent()` | ❌ |
| `RunnerState`, `HedgeState`, `OverlayAction`, `CloseReasonCode` (enums) | ❌ |

### 9e. Trading-layer Hedge — `trading/adaptive_hedge_builder.py` (610 lines)
| Function | V2 Status |
|---|---|
| `AdaptiveHedgeBuilder` | ❌ |
| Build hedge on ATR/regime | ❌ |

### 9f. Dynamic Adaptive Hedge — `trading/dynamic_adaptive_hedge.py` (1,126 lines)
| Function | V2 Status |
|---|---|
| `HedgeReason`, `HedgeUrgency` enums | ❌ |
| Adaptive hedge sizing by urgency | ❌ |
| Liquidation-proximity hedge trigger | ❌ |

### 9g. Inside `HybridTrainer` — Hedge Methods
| Function | V2 Status |
|---|---|
| `_check_adaptive_hedge_opportunities()` | ❌ |
| `_check_adaptive_hedge_opportunities_v2()` | ❌ |
| `_check_fast_reversal_hedges()` | ❌ |
| `_flash_move_auto_hedge_generator()` | ❌ |
| `_favorable_add_margin_generator()` | ❌ |
| `_emit_reversal_hedge()` | ❌ |
| `_apply_hedge_intent()` | ❌ |
| `_apply_liquidation_aware_hedge()` | ❌ |
| `_maybe_publish_recovery_reduction()` | ❌ |
| `enforce_hedge_positions()` | ❌ |
| `generate_hedge_signals()` | ❌ |
| `_enter_hedge_build_state()` / `_exit_hedge_build_state()` | ❌ |
| `_check_hedge_build_block()` | ❌ |
| `_is_hedge_build_active()` | ❌ |

---

## 10. REWARD FUNCTIONS

### `rl/reward_functions.py` (902 lines)
| Class / Function | V2 Status |
|---|---|
| `AdvancedRewardCalculator` | ❌ |
| `calculate_reward()` — composite: PnL + risk + duration + Sharpe | ❌ |
| `_calculate_risk_penalty()` — drawdown, leverage, concentration | ❌ |
| `_calculate_duration_penalty()` — penalize holding too long | ❌ |
| `_calculate_sharpe_reward()` — rolling Sharpe contribution | ❌ |
| `RealisticTradingSimulator` | ❌ |
| `simulate_order_execution()` — slippage + latency | ❌ |
| `_calculate_slippage()` | ❌ |
| `HoldTimeRewardShaper` | ❌ |
| `compute_hold_modifier()` — reward scaling by hold time | ❌ |
| `shape_reward()` | ❌ |
| `TransactionCostAwareReward` | ❌ |
| `compute_reward()` — fee-adjusted reward | ❌ |
| `minimum_profitable_move()` — break-even move size | ❌ |
| `OnlineRewardShaper` — adaptive reward weight updating | ❌ |
| `update_weights()` | ❌ |

### `rl/constrained_reward.py` (298 lines)
| Function | V2 Status |
|---|---|
| Constraint-based reward shaping (safety penalties) | ❌ |
| Liquidation distance penalty | ❌ |
| Portfolio concentration penalty | ❌ |

### `rl/fee_ratio_reward_shaping.py` (519 lines)
| Function | V2 Status |
|---|---|
| Fee-ratio-aware reward modifier | ❌ |
| Minimum fee-to-move ratio enforcement in reward | ❌ |
| Maker/taker split reward adjustment | ❌ |

---

## 11. ANTI-CHURN SYSTEM

### `rl/anti_churn_manager.py` (341 lines)
| Function | V2 Status |
|---|---|
| `AntiChurnManager` — per-symbol action rate limiting | ❌ |
| `check_allowed()` — enforce cooldown + budget | ❌ |
| `record_execution()` | ❌ |
| `categorize_action()` — OPEN_RISK / CLOSE / HEDGE / INCREASE | ❌ |
| `get_symbol_limits()` | ❌ |

### `rl/churn_veto.py` (160 lines)
| Function | V2 Status |
|---|---|
| `ChurnVetoModel` — ML model predicting bad trades | ❌ |
| `predict_p_bad()` — probability of churn trade | ❌ |
| `decide()` — veto or allow | ❌ |

### Inside `HybridTrainer`
| Function | V2 Status |
|---|---|
| `_check_cooldown()` | ❌ |
| `_check_budget()` | ❌ |
| `_set_cooldown()` | ❌ |
| `_increment_budget_counter()` | ❌ |
| `_compute_dynamic_churn_cooldown()` | ❌ |
| `_apply_direction_stability_gate()` | ❌ |

---

## 12. MICROSTRUCTURE SYSTEM

### `rl/microstructure_overlay.py` (1,125 lines)
| Function | V2 Status |
|---|---|
| `MicrostructureOverlay` — pre-trade quality filter | ❌ |
| `evaluate()` — full microstructure evaluation | ❌ |
| `evaluate_1m_action()` — 1m-specific evaluation | ❌ |
| `compute_spoof_score()` — orderbook spoof detection | ❌ |
| `compute_fast_move_score()` — momentum quality | ❌ |
| `update_snapshot()` — live orderbook snapshot | ❌ |
| `_load_canonical_orderbook()` | ❌ |
| Bid/ask imbalance, spread analysis | ❌ |
| `publish_intent()` / `publish_skip_event()` | ❌ |

### `rl/microstructure_features.py` (517 lines)
| Function | V2 Status |
|---|---|
| `MicrostructureFeatureExtractor` | ❌ |
| `_update_symbol_features()` — live bar features | ❌ |
| `_update_orderbook_features()` — depth imbalance | ❌ |
| `_update_volume_features()` — VWAP, volume surge | ❌ |
| `_update_liquidation_features()` | ❌ |
| `_detect_squeeze()` — volatility compression | ❌ |
| `on_trade()` — tick-level trade event handler | ❌ |

### `rl/microstructure_aggregator.py` (464 lines)
| Function | V2 Status |
|---|---|
| `MicrostructureAggregator` — multi-TF aggregation | ❌ |
| `compute_aggregate()` — per-TF aggregated microstructure features | ❌ |
| `consume_msnap_stream()` — Redis stream consumer | ❌ |
| `publish_aggregates_to_redis()` | ❌ |

### Inside `HybridTrainer`
| Function | V2 Status |
|---|---|
| `analyze_market_microstructure()` | ❌ |
| `detect_market_maker_patterns()` | ❌ |
| `detect_fake_breakouts()` | ❌ |
| `calculate_scalp_opportunity()` | ❌ |
| `_apply_proactive_microstructure()` | ❌ |
| `_analyze_liquidation_levels()` | ❌ |

---

## 13. FEATURE BUILDING & OBSERVATION SPACE

### `rl/unified_feature_builder.py` (710 lines)
| Function | V2 Status |
|---|---|
| `UnifiedFeatureBuilder` — assembles 2000+ Redis features into obs vector | ❌ |
| Feature grouping: OHLCV, TA, CoinAnk, KuCoin, liquidations, microstructure, portfolio | ❌ |
| Staleness checks per feature | ❌ |
| Normalization per feature type | ❌ |
| Missing feature imputation | ❌ |

### `rl/environment.py` (1,455 lines)
| Function | V2 Status |
|---|---|
| `TradingEnvironment` — Gymnasium env | ❌ |
| `step()` — action → obs/reward/done | ❌ |
| `reset()` | ❌ |
| `_get_obs()` — build observation tensor | ❌ |
| `_compute_reward()` — composite reward | ❌ |
| `_execute_action()` — simulate order fill | ❌ |

### `rl/tf_aggregator.py`
| Function | V2 Status |
|---|---|
| Multi-timeframe feature aggregation | ❌ |
| Cross-TF feature vectors (1m/5m/15m/1h/4h) | ❌ |

---

## 14. PROFIT BANK & ROI KILL

### `rl/profit_bank.py` (240 lines)
| Function | V2 Status |
|---|---|
| `ProfitBank` — running P&L bank | ❌ |
| `credit()` — bank profit from closed trades | ❌ |
| `debit()` — fund new positions from bank | ❌ |
| `ingest_executed_signals()` — consume execution stream | ❌ |
| `ingest_profit_exit_feedback()` — consume trader feedback | ❌ |

### `rl/profit_freespace_rebalancer.py`
| Function | V2 Status |
|---|---|
| Rebalance free margin after profitable trades | ❌ |

### Inside `HybridTrainer`
| Function | V2 Status |
|---|---|
| `update_risk_metrics()` — equity + drawdown tracking | ❌ |
| `_update_drawdown_tracking()` | ❌ |
| `_check_risk_gates()` → max daily loss kill | ❌ |
| `_handle_extreme_market_scenarios()` | ❌ |
| `_detect_liquidity_crisis()` | ❌ |
| `_send_emergency_alert()` | ❌ |

---

## 15. POSITION SIZING & LEVERAGE

| Function | Lines | V2 Status |
|---|---|---|
| `calculate_enhanced_position_size()` | 29224 | ❌ |
| `_calculate_volatility_targeted_size()` | 20670 | ❌ |
| `_calculate_liquidity_aware_size()` | 20680 | ❌ |
| `_calculate_performance_based_size()` | 20701 | ❌ |
| `_calculate_optimal_position_size()` | 33647 | ❌ |
| `_compute_adaptive_leverage()` | 4423 | ❌ |
| `_apply_global_leverage_cap()` | 4389 | ❌ |
| `_calc_leverage_cap()` | 45533 | ❌ |
| `_calculate_optimal_leverage()` | 34521 | ❌ |
| `calculate_initial_hedge_sizes()` | 27368 | ❌ |
| `_compute_dynamic_headroom_reserve()` | 4312 | ❌ |
| `_check_margin_allocation()` | 20494 | ❌ |
| `validate_margin_for_trade()` | 22285 | ❌ |
| `_check_portfolio_concentration()` | 19716 | ❌ |

---

## 16. DRIFT & TOXICITY

### `rl/drift_monitor.py` (465 lines)
| Function | V2 Status |
|---|---|
| `compute_psi()` — Population Stability Index | ❌ |
| `compute_kl_divergence()` | ❌ |
| `FeatureDriftTracker` — sliding window feature drift | ❌ |
| `PolicyDriftTracker` — action distribution drift | ❌ |
| `ExecutionQualityTracker` — fill/slippage/latency drift | ❌ |
| `DriftMonitor` — composite drift monitor | ❌ |
| `check()` — returns STABLE / DEGRADED / CRITICAL | ❌ |
| `_publish_alerts()` — Redis drift alert | ❌ |

### `rl/toxicity_shield.py` (163 lines)
| Function | V2 Status |
|---|---|
| `ToxicityShield` — block trades in toxic market conditions | ❌ |
| `decide()` — ALLOW / BLOCK | ❌ |

---

## 17. CHECKPOINT SYSTEM

| Function | Lines | V2 Status |
|---|---|---|
| `save_training_checkpoint()` | 49585 | ❌ |
| `load_latest_checkpoint()` | 49967 | ❌ |
| `save_models()` | 49346 | ❌ |
| `load_models()` / `load_latest_models()` | 48861 / 48787 | ❌ |
| `_is_checkpoint_valid()` | 49515 | ❌ |
| `_quarantine_checkpoint()` | 49503 | ❌ |
| `_atomic_replace()` | 49564 | ❌ |
| `_atomic_write_json()` | 49577 | ❌ |
| `_checkpoint_lock()` | 49540 | ❌ |
| `_fsync_file()` | 49557 | ❌ |
| `_cleanup_old_checkpoints()` | 50203 | ❌ |
| `_sb3_save_sanitize()` | 49404 | ❌ |
| `_pickle_probe()` | 49361 | ❌ |
| `_require_checkpoint_live()` | 50115 | ❌ |

---

## 18. SUMMARY TABLE

| Subsystem | Legacy Lines | Functions | V2 Native | V2 Bridge | Not Migrated |
|---|---|---|---|---|---|
| GPU Training Loop | ~15,000 | ~40 | 0 | subprocess wrapper | **100%** |
| Inference/Prediction Pipeline | ~8,000 | ~25 | 0 | reads Redis output | **100%** |
| Confidence System | ~1,150 | ~20 | schema only | — | **~95%** |
| Signal Generation/Routing | ~12,000 | ~30 | 0 | — | **100%** |
| Regime Detection | ~5,000 | ~30 | 0 | — | **100%** |
| MTF System | ~2,000 | ~9 | 0 | — | **100%** |
| Stealth Stop Loss | 6,972 | ~50 | 0 | — | **100%** |
| Dynamic Adaptive Stops | 1,063 | ~10 | 0 | — | **100%** |
| Dynamic TP Engine | 1,468 | ~10 | 0 | — | **100%** |
| Hedge Systems (4 layers) | ~7,000 | ~40 | 0 | — | **100%** |
| Reward Functions | 1,719 | ~15 | 0 | — | **100%** |
| Anti-Churn System | ~500 | ~10 | 0 | — | **100%** |
| Microstructure System | ~2,100 | ~25 | 0 | — | **100%** |
| Feature Builder / Obs Space | ~2,900 | ~20 | schema/domain models | legacy_adapter | **~90%** |
| Profit Bank / ROI Kill | ~400 | ~8 | 0 | — | **100%** |
| Position Sizing / Leverage | embedded | ~15 | 0 | — | **100%** |
| Drift / Toxicity | ~628 | ~15 | 0 | — | **100%** |
| Checkpoint System | ~1,500 | ~15 | 0 | subprocess adapter | **100%** |

---

## 19. What V2 Has That Legacy Doesn't

These are **new capabilities** added in v2 with no legacy equivalent:

| Feature | V2 Location |
|---|---|
| Trainer liveness SLA monitoring (CRITICAL/DEGRADED/HEALTHY) | `domain/trainer_liveness/` |
| Trainer prediction output domain with full invariant enforcement | `domain/trainer_prediction_output/` |
| Feature freshness / staleness domain model | `domain/features/freshness.py` |
| Feature completeness scoring | `domain/features/completeness.py` |
| Lineage chain-of-custody for every prediction | `domain/lineage/` |
| Governance approval chain (human-in-the-loop) | `domain/governance/` |
| Paper execution ledger with full audit trail | `composition/paper_execution_ledger/` |
| Shadow outcome learning (blocked intents → paper fill recording) | `cli/paper_shadow_outcome_observer.py` |
| External manual position quarantine | `domain/external_manual_position_quarantine/` |
| Degraded state fail-closed gates | `composition/degraded_state_fail_closed_gates/` |
| Hot-reload with quorum + rollback state machine | `domain/hot_reload/` |
| REST API (30+ endpoints) | `api/v1/` |
| Operator React dashboard (Vite) | `frontend/` |
| Ollama local LLM integration | `adapters/ollama/` |
| Symbol universe service with dynamic selection | `services/symbol_universe/` |
| Evidence packet writer/reader (audit trail) | `adapters/evidence/` |
| 500+ unit tests for trainer health/liveness | `tests/unit/` |

---

## 20. Overall Migration Completion Estimate

| Category | Completion |
|---|---|
| Infrastructure (Redis, DB, API, auth) | **~85%** |
| Trainer (ML engine, GPU, PPO+MASA) | **~5%** (subprocess wrapper only) |
| Feature pipeline (computation) | **~5%** (reads legacy output) |
| Ingestors (data sources) | **~0%** (legacy still runs all) |
| Stop loss / TP / trailing | **~0%** |
| Hedge systems | **~0%** |
| Reward functions | **~0%** |
| Regime / MTF / confidence | **~0%** |
| Governance / audit / safety | **~90%** |
| Frontend / operator dashboard | **~80%** |
| **Overall** | **~25%** |

The vast majority of the algorithmic intelligence — the year+ of work on PPO+MASA training, all 5 confidence layers, 4 hedge systems, stealth stops, dynamic TP, regime detection, microstructure analysis, reward shaping — is **entirely in legacy** and has not been ported to v2 yet.

---

*Last updated: 2026-05-15*
