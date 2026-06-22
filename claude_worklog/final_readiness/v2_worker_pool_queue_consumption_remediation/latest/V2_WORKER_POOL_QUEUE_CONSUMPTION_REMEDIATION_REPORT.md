# V2 Worker Pool Queue-Consumption Remediation Report

Marker: `V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_READY`
Generated: 2026-05-24T23:42:59Z

## Worker Pool

| metric | value |
| --- | --- |
| worker_count_total | 6 |
| worker_count_active | 6 |
| worker_count_busy | 4 |
| worker_count_idle_ready | 2 |
| active_claude_workers | 3 |
| active_codex_workers | 3 |
| active_lane_count | 6 |
| active_leases_count | 4 |
| current_automatable_count | 4 |

## Cycle Accounting

| metric | value |
| --- | --- |
| completed_task_count_this_cycle | 0 |
| failed_task_count_this_cycle | 0 |
| remediation_created_count_this_cycle | 0 |
| blocked_task_count_this_cycle | 0 |
| still_running_task_count | 4 |
| idle_workers_with_eligible_work_count | 0 |

## Queue Consumption Diagnosis (current rows)

| task_id | task_type | status | lease | blocker_if_not_leased |
| --- | --- | --- | --- | --- |
| claude_autoseed_baseline_after_cost_calibration_r15 | CLAUDE_IMPLEMENTATION | running | True | - |
| claude_autoseed_observation_gap_feature_source_burndown_r15 | CLAUDE_IMPLEMENTATION | running | True | - |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r14 | CLAUDE_IMPLEMENTATION | running | True | - |
| codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract | CODEX_REVIEW | running | True | - |
| claude_autoseed_baseline_after_cost_calibration | CLAUDE_IMPLEMENTATION | completed | False | - |
| claude_autoseed_baseline_after_cost_calibration_r10 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r11 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r12 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r13 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r14 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r2 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r3 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r4 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r5 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r6 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r7 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r8 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_baseline_after_cost_calibration_r9 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_decision_match_runtime_replay_comparator | CLAUDE_IMPLEMENTATION | completed | False | - |
| claude_autoseed_decision_match_runtime_replay_comparator_r2 | CLAUDE_IMPLEMENTATION | failed | False | - |
| claude_autoseed_dynamic_symbol_coverage_missing_source_closure | CLAUDE_IMPLEMENTATION | completed | False | - |
| claude_autoseed_dynamic_symbol_coverage_missing_source_closure_r2 | CLAUDE_IMPLEMENTATION | failed | False | - |
| claude_autoseed_observation_gap_feature_source_burndown | CLAUDE_IMPLEMENTATION | completed | False | - |
| claude_autoseed_observation_gap_feature_source_burndown_r10 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r11 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r12 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r13 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r14 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r2 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r3 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r4 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r5 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r6 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r7 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r8 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_observation_gap_feature_source_burndown_r9 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment | CLAUDE_IMPLEMENTATION | completed | False | - |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r10 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r11 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r12 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r13 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r2 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r3 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r4 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r5 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r6 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r7 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r8 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r9 | CLAUDE_IMPLEMENTATION | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r10 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r11 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r12 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r13 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r14 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r15 | CODEX_REVIEW | blocked_dependency | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r2 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r3 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r4 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r5 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r6 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r7 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r8 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_baseline_after_cost_calibration_r9 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_decision_match_runtime_replay_comparator | CODEX_REVIEW | failed | False | - |
| codex_review_autoseed_decision_match_runtime_replay_comparator_r2 | CODEX_REVIEW | failed | False | - |
| codex_review_autoseed_dynamic_symbol_coverage_missing_source_closure | CODEX_REVIEW | failed | False | - |
| codex_review_autoseed_dynamic_symbol_coverage_missing_source_closure_r2 | CODEX_REVIEW | failed | False | - |
| codex_review_autoseed_observation_gap_feature_source_burndown | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r10 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r11 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r12 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r13 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r14 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r15 | CODEX_REVIEW | blocked_dependency | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r2 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r3 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r4 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r5 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r6 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r7 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r8 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_observation_gap_feature_source_burndown_r9 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r10 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r11 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r12 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r13 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r14 | CODEX_REVIEW | blocked_dependency | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r2 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r3 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r4 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r5 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r6 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r7 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r8 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r9 | CODEX_REVIEW | failed | False | FILE_LOCK_CONFLICT |
| real_mode_probe_claude_alpha | CLAUDE_IMPLEMENTATION | completed | False | - |
| real_mode_probe_claude_beta | CLAUDE_IMPLEMENTATION | completed | False | - |
| real_mode_probe_claude_gamma | CLAUDE_IMPLEMENTATION | completed | False | - |
| real_mode_probe_codex_alpha | CODEX_REVIEW | failed | False | - |
| real_mode_probe_codex_beta | CODEX_REVIEW | failed | False | - |
| real_mode_probe_codex_gamma | CODEX_REVIEW | failed | False | - |

## Current Task Assignments (active leases only)

| worker_id | task_id | lane_type | leased_at |
| --- | --- | --- | --- |
| codex-2 | codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract | CODEX_REVIEW | 2026-05-24T23:41:24Z |
| claude-2 | claude_autoseed_baseline_after_cost_calibration_r15 | CLAUDE_IMPLEMENTATION | 2026-05-24T23:41:24Z |
| claude-3 | claude_autoseed_observation_gap_feature_source_burndown_r15 | CLAUDE_IMPLEMENTATION | 2026-05-24T23:41:28Z |
| claude-1 | claude_autoseed_paper_edge_false_negative_gate_reason_enrichment_r14 | CLAUDE_IMPLEMENTATION | 2026-05-24T23:41:32Z |

## Zombies Reset

- (none)

## Lease Cycle Results

- claude_leases_created: 0
- codex_leases_created:  0

## Blockers

- (none)

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false
