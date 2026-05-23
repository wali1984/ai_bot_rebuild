# V2 Edge Proof Analysis Report (analysis-only)
live_gate=blocked_human_only. live_symbols=[]. approves_live=false.
## Observed evaluator inputs
- min_sample_count: 1259
- min_after_cost_expectancy_bps: -6.648327647688229
- min_after_cost_lower_ci_bps: -9.972796045733514
- max_drawdown_bps_rolling: 309.82905982905976
- max_false_negative_rate: 0.18181818181818182
- max_false_positive_rate: None

## Profile simulations

### conservative
- verdict: INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING
  - min_sample_count: observed=1259 profile=10000 reason=FAIL
  - min_after_cost_expectancy_bps: observed=-6.648327647688229 profile=15.0 reason=FAIL
  - min_after_cost_lower_ci_bps: observed=-9.972796045733514 profile=5.0 reason=FAIL
  - max_drawdown_bps_rolling: observed=309.82905982905976 profile=200.0 reason=FAIL
  - max_false_negative_rate: observed=0.18181818181818182 profile=0.1 reason=FAIL
  - max_false_positive_rate: observed=None profile=0.05 reason=OBSERVED_VALUE_MISSING

### balanced
- verdict: INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING
  - min_sample_count: observed=1259 profile=5000 reason=FAIL
  - min_after_cost_expectancy_bps: observed=-6.648327647688229 profile=8.0 reason=FAIL
  - min_after_cost_lower_ci_bps: observed=-9.972796045733514 profile=0.0 reason=FAIL
  - max_drawdown_bps_rolling: observed=309.82905982905976 profile=300.0 reason=FAIL
  - max_false_negative_rate: observed=0.18181818181818182 profile=0.15 reason=FAIL
  - max_false_positive_rate: observed=None profile=0.1 reason=OBSERVED_VALUE_MISSING

### aggressive
- verdict: INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING
  - min_sample_count: observed=1259 profile=2000 reason=FAIL
  - min_after_cost_expectancy_bps: observed=-6.648327647688229 profile=3.0 reason=FAIL
  - min_after_cost_lower_ci_bps: observed=-9.972796045733514 profile=-5.0 reason=FAIL
  - max_drawdown_bps_rolling: observed=309.82905982905976 profile=500.0 reason=PASS
  - max_false_negative_rate: observed=0.18181818181818182 profile=0.25 reason=PASS
  - max_false_positive_rate: observed=None profile=0.2 reason=OBSERVED_VALUE_MISSING

## Edge gate analysis
- edge_claimed: False
- edge_claim_blocked_reason: operator_thresholds_required_and_not_set

No profile is interpreted as an approval. The miner/evaluator gate stays at OPERATOR_DECISION_REQUIRED until the operator sets concrete numerics through the official path. This report is analysis-only.
