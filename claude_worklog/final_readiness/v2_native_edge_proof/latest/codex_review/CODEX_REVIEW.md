# Codex Review: V2 Native Edge-Proof Evaluator

GO/NO-GO: `V2_NATIVE_EDGE_PROOF_EVALUATOR_CODEX_FAIL`

READY was reviewed as evaluator existence only. This review does not approve edge, canary, live trading, legacy shutdown, Redis trimming, or symbol adoption.

## Reviewed Scope

- `v2/backend/app/services/edge_proof/replay_schema.py`
- `v2/backend/app/services/edge_proof/evaluator.py`
- `v2/backend/app/cli/v2_native_edge_proof_evaluator.py`
- `v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py`
- `claude_worklog/final_readiness/v2_native_edge_proof/latest/replay_bundle_schema.json`
- `claude_worklog/final_readiness/v2_native_edge_proof/latest/native_edge_proof_status.json`
- `claude_worklog/final_readiness/v2_native_edge_proof/latest/edge_metrics_summary.json`
- `v2/frontend/public/v2_native_edge_proof/latest/operator_dashboard_payload.json`
- `v2/frontend/public/v2_native_edge_proof/latest/edge_metrics_summary.json`
- `v2/frontend/public/v2_native_edge_proof/latest/replay_bundle_schema.json`

## Blocking Findings

1. **Replay bundle schema omits the full feature snapshot required by the review contract.**

   `ReplayBundle` includes `feature_snapshot_id` and `features_hash`, and the CLI reads `v2:features:latest:{symbol}:{timeframe}`, but the feature snapshot payload is not stored in the bundle or emitted in `bundle_fields`. The CLI discards the snapshot after hashing it. This fails the required schema item "feature snapshot" and weakens replay auditability because the frozen bundle cannot independently reconstruct the model input.

   Evidence:
   - `v2/backend/app/services/edge_proof/replay_schema.py`: `ReplayBundle` fields include `feature_snapshot_id` and `features_hash`, but no `feature_snapshot`.
   - `v2/backend/app/services/edge_proof/replay_schema.py`: `emit_canonical_schema()` emits no `feature_snapshot` field.
   - `v2/backend/app/cli/v2_native_edge_proof_evaluator.py`: `features` is read and only used for `_features_hash(features)`.
   - `claude_worklog/final_readiness/v2_native_edge_proof/latest/replay_bundle_schema.json`: `bundle_fields` has no `feature_snapshot`.

2. **`max_drawdown_bps_rolling` is declared as an operator threshold but is not computed or enforced before `EDGE_PROVISIONAL_PAPER_PASS`.**

   `DEFAULT_THRESHOLDS` exposes `max_drawdown_bps_rolling`, but `MetricSummary` has no drawdown metric and `thresholds_satisfied` never includes `max_drawdown_bps_rolling`. A read-only probe showed the evaluator can return `EDGE_PROVISIONAL_PAPER_PASS` with all other thresholds passing while every bundle has severe drawdown, because the drawdown threshold is ignored.

   Probe result:

   ```text
   {'verdict': 'EDGE_PROVISIONAL_PAPER_PASS',
    'thresholds_satisfied': {'min_sample_count': True,
                             'min_after_cost_expectancy_bps': True,
                             'min_after_cost_lower_ci_bps': True,
                             'min_downside_pre_cascade_recall': True,
                             'max_false_positive_rate': True,
                             'max_false_negative_rate': True,
                             'min_v2_vs_legacy_action_match_rate': 'INFORMATIONAL_ONLY'},
    'has_drawdown_check': False}
   ```

   This violates the core claim that edge is never claimed unless every operator-set numeric threshold is satisfied.

3. **The evaluator trusts pre-existing non-`insufficient_evidence` labels instead of deriving labels from realized outcomes.**

   `_classify()` immediately returns `bundle.label` when it is not `INSUFFICIENT_EVIDENCE`. That permits fake or stale labels to drive false-positive/false-negative metrics even when the future outcome contradicts the label. A replay evaluator should recompute objective labels from realized after-cost outcomes, or at minimum validate supplied labels against the outcome window before using them.

   Probe result with losing accepted trades labeled `correct_trade`:

   ```text
   {'verdict': 'EDGE_PROVISIONAL_PAPER_PASS',
    'false_positive_rate': 0.0,
    'thresholds_satisfied': {'min_sample_count': True,
                             'min_after_cost_expectancy_bps': True,
                             'min_after_cost_lower_ci_bps': True,
                             'min_downside_pre_cascade_recall': True,
                             'max_false_positive_rate': True,
                             'max_false_negative_rate': True,
                             'min_v2_vs_legacy_action_match_rate': 'INFORMATIONAL_ONLY'}}
   ```

   The current CLI creates `INSUFFICIENT_EVIDENCE` labels, but the evaluator itself is the canonical scorer and should not accept fake outcome labels from replay bundles.

## Non-Blocking Contract Mismatch

- When `min_sample_count` is numeric but sample count is too low, the evaluator returns `EDGE_NOT_PROVEN` rather than the documented `EDGE_NOT_PROVEN_INSUFFICIENT_SAMPLES`. It does not claim edge in this case, but the verdict taxonomy does not match the report.

  Probe result:

  ```text
  {'insufficient_sample_verdict': 'EDGE_NOT_PROVEN',
   'minimum_sample_satisfied': False}
  ```

## Verified Passing Items

- Default runtime/artifact verdict is conservative: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`.
- Required metrics are present in `MetricSummary` / `summary_to_dict`: `sample_count`, `minimum_sample_satisfied`, after-cost metrics, false-positive/false-negative rates, downside recall/precision, latency, gate block distribution, V2-vs-legacy match rate, checkpoint/strict-gate counts, no-trade/false-block counts, fee/slippage, and bootstrap CI fields.
- `live_gate` remains `blocked_human_only`.
- `live_symbols` remains `[]`.
- `approves_live`, `approves_canary`, `approves_legacy_shutdown`, and `approves_redis_trim` remain `False`, including on `EDGE_PROVISIONAL_PAPER_PASS`.
- Legacy comparison is reference-only: the CLI reads the V2-vs-legacy public mirror file and `_safe_redis_read()` refuses non-`v2:*` Redis keys.
- No old Redis write was found in the reviewed edge-proof code. Redis use is `get()` only through `_safe_redis_read()`.
- No exchange mutation path was found in the reviewed edge-proof code.
- No raw secrets were found in the reviewed edge-proof code or emitted V2 native edge-proof artifacts. Matches were safety text only.
- Future outcome windows emitted by the realtime CLI are not fabricated: they remain `None`/`samples=0` and labels are `INSUFFICIENT_EVIDENCE`.
- Worklog and frontend schema/metrics mirrors match byte-for-byte for the checked files.
- Required visible dashboard text is present in `operator_dashboard_payload.json`.

## Test Evidence

```text
PYTHONPATH=$PWD .venv/bin/pytest v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py -q
```

Result:

```text
9 passed in 0.14s
```

Read-only CLI smoke:

```text
PYTHONPATH=$PWD .venv/bin/python v2/backend/app/cli/v2_native_edge_proof_evaluator.py --dry-run --json
```

Observed summary:

```text
go_no_go=V2_NATIVE_EDGE_PROOF_SPEC_AND_REPLAY_EVALUATOR_READY
verdict=EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
sample_count=3
live_gate=blocked_human_only
live_symbols=[]
approves_live=false
approves_canary=false
approves_legacy_shutdown=false
approves_redis_trim=false
```

## Required Remediation Before Pass

1. Add a frozen `feature_snapshot` field, or an equivalent immutable feature payload field, to `ReplayBundle`, `emit_canonical_schema()`, bundle assembly, artifacts, and tests.
2. Compute rolling/primary drawdown from outcome windows, include the drawdown metric in `MetricSummary`, and enforce `max_drawdown_bps_rolling` in `thresholds_satisfied` before any provisional paper pass.
3. Make label classification objective: recompute labels from realized after-cost outcomes and gate decisions, or validate supplied labels and fail/mark insufficient when labels contradict outcomes.
4. Fix insufficient-sample verdict ordering so numeric sample shortfall emits `EDGE_NOT_PROVEN_INSUFFICIENT_SAMPLES`.
5. Add regression tests for all four items above.

## Safety Scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_write_old_redis
- did_not_call_exchange
- did_not_enable_live
- did_not_create_approval_marker
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
