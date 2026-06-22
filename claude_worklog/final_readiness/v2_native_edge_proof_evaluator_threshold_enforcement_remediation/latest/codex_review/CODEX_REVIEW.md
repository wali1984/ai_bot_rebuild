# Codex Review: V2 Native Edge-Proof Evaluator Threshold Enforcement Remediation Rerun

GO/NO-GO: `V2_NATIVE_EDGE_PROOF_EVALUATOR_THRESHOLD_ENFORCEMENT_REMEDIATION_CODEX_PASS`

READY was re-reviewed after the replay-bundle cost-model backfill remediation. This review does not approve edge, canary, live trading, legacy shutdown, Redis trimming, or symbol adoption.

## Findings

No blocking findings.

The prior blocker is resolved: current replay-bundle stores no longer contain stale default cost-model rows without the `OPERATOR_DECISION_REQUIRED` literal.

## Reviewed Scope

- `v2/backend/app/services/edge_proof/evaluator.py`
- `v2/backend/app/services/edge_proof/replay_schema.py`
- `v2/backend/app/services/edge_proof/replay_miner.py`
- `v2/backend/app/cli/v2_native_edge_proof_evaluator.py`
- `v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py`
- `v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py`
- `v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py`
- `claude_worklog/final_readiness/v2_native_edge_proof_evaluator_threshold_enforcement_remediation/latest/*`
- current post-hoc replay bundle worklog, public mirror, and miner state JSONL stores
- refreshed native edge-proof and post-hoc miner payloads

## Threshold Enforcement

Verified `EDGE_PROVISIONAL_PAPER_PASS` requires all seven required thresholds:

- `min_sample_count`
- `min_after_cost_expectancy_bps`
- `min_after_cost_lower_ci_bps`
- `max_drawdown_bps_rolling`
- `min_downside_pre_cascade_recall`
- `max_false_positive_rate`
- `max_false_negative_rate`

Read-only probe evidence:

```text
default verdict = EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
pass_case verdict = EDGE_PROVISIONAL_PAPER_PASS
drawdown_fail verdict = EDGE_NOT_PROVEN
missing_drawdown verdict = EDGE_NOT_PROVEN
insufficient_samples verdict = EDGE_NOT_PROVEN_INSUFFICIENT_SAMPLES
guard_failures = []
```

The guard sweep covered missing, null, NaN, nonnumeric, and `OPERATOR_DECISION_REQUIRED` values for every required threshold; none could emit `EDGE_PROVISIONAL_PAPER_PASS`.

Drawdown probe evidence:

```text
pass_case max_drawdown_bps_rolling:
observed_value=50.0 threshold_value=100.0 passed=true evidence_state=NUMERIC_CHECK_PASSED

drawdown_fail max_drawdown_bps_rolling:
observed_value=50.0 threshold_value=25.0 passed=false evidence_state=NUMERIC_CHECK_FAILED

missing_drawdown max_drawdown_bps_rolling:
observed_value=null threshold_value=100.0 passed=false evidence_state=INSUFFICIENT_EVIDENCE
```

Threshold output includes per-threshold `threshold_name`, `threshold_value`, `observed_value`, `passed`, and `evidence_state`.

## Cost Model

Schema/default cost model and current persisted bundle rows contain the required literal:

```text
DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE_OPERATOR_DECISION_REQUIRED
```

Visible operator-overridable defaults remain present:

```text
operator_decision_required=true
operator_override_required=true
default_fee_bps_visible=5.0
default_slippage_estimate_bps_visible=2.0
```

Current replay-bundle stores:

```text
worklog latest replay_outcome_bundles.jsonl: rows=9 bad_cost_model_marker_count=0 missing_visible_override_field_count=0
public mirror replay_outcome_bundles.jsonl: rows=9 bad_cost_model_marker_count=0 missing_visible_override_field_count=0
miner state replay_bundles.jsonl: rows=9 bad_cost_model_marker_count=0 missing_visible_override_field_count=0
```

## Safety Verification

- Evaluator approval fields remain false even in the synthetic `EDGE_PROVISIONAL_PAPER_PASS` probe: `approves_live=false`, `approves_canary=false`, `approves_legacy_shutdown=false`, and `approves_redis_trim=false`.
- `live_gate=blocked_human_only` and `live_symbols=[]` remain present.
- Current miner/native edge-proof verdict remains conservative: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`.
- No old Redis write path was found in reviewed edge-proof code.
- No exchange mutation path was found in reviewed edge-proof code.
- No raw secrets were found in reviewed artifacts; scan hits were safety/report text only.
- No fabricated future outcome windows were found in current replay bundle stores.

## Test Evidence

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py \
  v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py -q
```

Result:

```text
43 passed in 0.33s
```

Compile check:

```text
python -m py_compile \
  v2/backend/app/services/edge_proof/evaluator.py \
  v2/backend/app/services/edge_proof/replay_schema.py \
  v2/backend/app/services/edge_proof/replay_miner.py \
  v2/backend/app/cli/v2_native_edge_proof_evaluator.py \
  v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py
```

Result: pass.

## Safety Scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_write_old_redis
- did_not_call_exchange
- did_not_enable_live
- did_not_create_approval_marker
- did_not_fabricate_future_outcome_windows
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
