# SYSTEM PRESETS & EXECUTION PROTOCOL
- MODE: Deterministic, Production Engineering Run.
- TARGET: Execute changes sequentially. Do not simulate, audit, or draft text.
- INTEGRITY: No code stubbing (`pass`, `// TODO`, `# ...`). Write complete implementations.
- HARD BOUNDARY: Live gate MUST remain `blocked_human_only`. Do not authorize order execution, leverage mutation, or live row promotion under any circumstances.

# CURRENT SYSTEM STATE METRICS
---
date: 2026-07-11
status: NOT_FIXED (Training-Row Starved)
hardware_profile: RTX 5080 (16GB VRAM, currently bottlenecked at ~15% util, 1.3GB usage due to CPU data-loader starvation)
metrics:
  accepted_training_rows: 225
  available_examples: 4096
  ppo_on_policy_rows: 0
  training_rejection_count: 3871
  materialized_positions: 0
  PPO_clipped_surrogate_active: false
  dominant_rejection_reasons: [MISSING_CRITICAL_FEATURE_FAMILY, ROW_CLASSIFICATION_MISSING_MASKED]
---

# SEQUENTIAL WORKFLOW ACTIONS

## PHASE 1: DATA ADMISSION & REJECTION REPAIR
### 1. File Patches Required
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py`
- `v2/backend/app/services/market_state_integrity/sample_rejection.py`
- `v2/backend/app/services/feature_lineage_masks.py`
- `v2/backend/app/services/strategy_supply/feedback_maturation.py`

### 2. Output Artifact Target
Create and populate: `phase1_trainer_rejection_repair.json`
Required JSON Keys:
  - `row_source`, `row_count`, `missing_feature_families`, `masked_feature_families`, `stale_feature_families`, `critical_missing_vs_optional_missing`, `feature_family_introduced_after_snapshot_time`, `source_availability`, `lineage_mask_present`, `classification_mask_present`, `safe_to_train_with_missing_mask`, `unsafe_to_train_reason`

### 3. Implementation Rules
- PROHIBITED: Do not zero-fill missing features silently. Do not train stale or future-leaked data.
- MANDATORY EXCEPTION: Allow historical/replay rows with missing-masked feature families if they did not exist at snapshot time, provided that `feature_cutoff` is valid, `source_availability` is verified, `missing_mask` is explicit, and no future leaks exist.

### 4. Gate Thresholds
- PASS: `accepted_training_rows` >= 2000 minimum. Rejection counts drop significantly.
- HARD FAIL: `accepted_training_rows` < 500 while `available_examples` >= 4096. Block execution of Phase 2 if hit.

---

## PHASE 2: REPLAY & FEEDBACK FEEDER EXPANSION
### 1. Output Artifact Target
Create and populate: `phase2_replay_feedback_feeder_expansion.json`
Required JSON Keys:
  - `trusted_replay_rows_loaded_before`, `trusted_replay_rows_loaded_after`, `feedback_rows_entered_batch_before`, `feedback_rows_entered_batch_after`, `counterfactual_rows_available`, `counterfactual_rows_consumed`, `paper_closed_rows_available`, `paper_closed_rows_consumed`, `strategy_supply_feedback_rows`, `historical_replay_rows`, `feature_snapshot_archive_rows`, `frontier_reached`, `cursor_offset`

### 2. Implementation Rules
- Patch feeding pipelines sequentially until the trainer has sufficient real rows to saturate the GPU.
- TARGET CRITERIA: `target_accepted_training_rows` >= 8192 AND `target_trusted_replay_rows` >= 8192.

### 3. Gate Thresholds
- HARD FAIL: Proceeding to Phase 3 or claiming GPU starvation is fixed while active accepted training rows remain tiny.

---

## PHASE 3: ADAPTIVE GPU SATURATION CONTROLLER
### 1. File Patches Required
- `v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py`
- `v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py`
- `systemd unit for ai-bot-v2-native-cuda-trainer-persistent.service`

### 2. Output Artifact Target
Create and populate: `phase3_adaptive_gpu_saturation_controller.json`
Required JSON Keys:
  - `gpu_utilization_before`, `vram_used_before`, `accepted_training_rows_before`, `batch_size_before`, `train_steps_before`, `data_loader_time_ms`, `gpu_train_time_ms`, `cpu_prep_bottleneck`, `gpu_utilization_after`, `vram_used_after`, `accepted_training_rows_after`, `batch_size_after`, `train_steps_after`, `model_dim_after`, `parallel_rollouts_after`, `oom_events`

### 3. Controller Logic Rules
- IF `accepted_training_rows` < `batch_size`: Do not increase batch size. Set status to `DATA_STARVED`.
- IF `accepted_training_rows` >= `batch_size`: Gradually increment batch size.
- IF GPU Utility < 65% AND CPU prep is the bottleneck: Increase data loader workers, prefetch queues, pinned memory allocation, or caching layers. Do not touch batch size.
- IF VRAM & GPU Utility < 60%: Scale up model width/depth, parallel rollouts, or replay windows only if data bounds permit.
- IF OOM Event Triggers: Activate immediate backoff, downscale batch/model dims, and log to tracking schema.

### 4. Target Goals
- `target_gpu_utilization_pct`: 65-75
- `target_vram_utilization_pct`: 60-75
- `oom_backoff_enabled`: true
- `cycle_timeout_safe`: true

---

## PHASE 4: PPO CLIPPED SURROGATE & LOSS FUNCTION VALIDATION
### 1. File Patches Required
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_loss.py`
- `v2/backend/app/services/native_trainer/math_operators/tensor_clamp.py`

### 2. Output Artifact Target
Create and populate: `phase4_ppo_loss_validation.json`
Required JSON Keys:
  - `ppo_clipped_surrogate_active`, `mean_policy_loss`, `mean_value_loss`, `entropy_bonus`, `clip_fraction`, `approx_kl_divergence`, `advantage_mean`, `advantage_std`, `tensor_nan_inf_count`

### 3. Implementation Rules
- Fix structural issues preventing `PPO_clipped_surrogate_active` from turning true.
- Enforce strict clipping bounds ($[1 - \epsilon, 1 + \epsilon]$ where $\epsilon = 0.2$).
- MANDATORY: Add tracking assertions to catch exploding/vanishing advantages before applying backpropagation.

### 4. Gate Thresholds
- PASS: `PPO_clipped_surrogate_active` == true AND `tensor_nan_inf_count` == 0.

---

## PHASE 5: PAPER MATERIALIZATION LOOP & POSITION CIRCUITS
### 1. File Patches Required
- `v2/backend/app/services/paper_execution/paper_loop_manager.py`
- `v2/backend/app/services/paper_execution/quarantine_circuits.py`
- `v2/backend/app/services/paper_execution/clearing_house_mock.py`

### 2. Output Artifact Target
Create and populate: `phase5_paper_materialization.json`
Required JSON Keys:
  - `materialized_positions_before`, `materialized_positions_after`, `quarantine_circuit_status`, `performance_circuit_tripped_reason`, `simulated_slippage_pct`, `simulated_latency_ms`, `order_fill_count`

### 3. Implementation Rules
- Unblock the paper execution loop held up by quarantine/performance circuits.
- Ensure that valid agent predictions transition fully from the trainer to mock execution states.
- MANDATORY: Verify positions update safely inside the local cache without real-world API connectivity.

### 4. Gate Thresholds
- PASS: `materialized_positions_after` > 0 without tripping performance circuits.

---

## PHASE 6: PROBATION & PERFORMANCE TRACKING
### 1. File Patches Required
- `v2/backend/app/services/analytics/probation_monitor.py`
- `v2/backend/app/services/analytics/metrics_exporter.py`

### 2. Output Artifact Target
Create and populate: `phase6_probation_metrics.json`
Required JSON Keys:
  - `monitor_probation_status`, `consecutive_profitable_cycles`, `max_drawdown_observed`, `sharpe_ratio_estimate`, `telemetry_lag_ms`, `evidence_packet_generated`

### 3. Implementation Rules
- Establish automated telemetry logs validating that the restored learning loops match A+ grading frameworks.
- Log real-time training evaluation statistics directly into standard out / system logging profiles.

### 4. Gate Thresholds
- PASS: `evidence_packet_generated` == true AND system metrics stay stable for 10 sequential training evaluations.

---

## PHASE 7: LIVE-CANARY INTEGRITY & NO-EXECUTE READY PACKING
### 1. File Patches Required
- `v2/backend/app/services/risk_gates/canary_validator.py`
- `v2/backend/app/services/risk_gates/packet_signer.py`

### 2. Output Artifact Target
Create and populate: `phase7_canary_readiness.json`
Required JSON Keys:
  - `live_gate_status`, `no_execute_packet_signed`, `hidden_defects_count`, `binance_readiness_confirmed`, `final_a_plus_candidates`

### 3. Implementation Rules
- Bundle the entire operational status array into an un-mutated, signed, "No-Execute" validation package.
- This package must prove complete runtime viability without modifying the live gate block.
- ABSOLUTE SANITY CHECK: Explicitly assert that `live_gate` equals `blocked_human_only`.

### 4. Gate Thresholds
- PASS: `no_execute_packet_signed` == true AND `hidden_defects_count` == 0.
