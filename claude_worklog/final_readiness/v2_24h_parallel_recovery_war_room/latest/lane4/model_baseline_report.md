# V2 Compact Model Baseline (analysis-only)

live_gate=blocked_human_only. live_symbols=[]. approves_live=false.

validation_samples: 7 | train_samples: 26

| Baseline | enters | mean_after_cost_bps | sum_after_cost_bps | stdev |
|---|---:|---:|---:|---:|
| hold | 0 | 0.0 | 0.0 | 0.0 |
| v2_deterministic_policy_shadow_only | 0 | 0.0 | 0.0 | 0.0 |
| naive_threshold_expected_move_10bps | 7 | -3.468982685300559 | -24.282878797103912 | 9.011746472218457 |
| logistic_baseline_1d_expected_move | 6 | -0.7737513709878174 | -5.416259596914722 | 6.465046117607162 |

Legacy reference: MISSING_EVIDENCE — legacy_reference_action is null in all replay bundles

No checkpoint compatibility or policy-architecture parity is claimed. Result is analysis-only and does not approve live or canary trading.
