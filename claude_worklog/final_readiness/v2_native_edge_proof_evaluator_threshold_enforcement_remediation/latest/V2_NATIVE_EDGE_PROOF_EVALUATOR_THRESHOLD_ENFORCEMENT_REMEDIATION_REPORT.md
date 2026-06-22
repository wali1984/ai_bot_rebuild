# V2 Native Edge-Proof Evaluator Threshold Enforcement Remediation Report

GO/NO-GO: V2_NATIVE_EDGE_PROOF_EVALUATOR_THRESHOLD_ENFORCEMENT_REMEDIATION_READY

This packet remediates the two Codex fail blockers from
V2_POST_HOC_REPLAY_OUTCOME_MINER_CODEX review:

1. Evaluator did not enforce max_drawdown_bps_rolling.
2. Default cost model did not surface the literal OPERATOR_DECISION_REQUIRED.

The replay miner timer remains NOT installed and NOT enabled, per the
constraint.

## Evaluator patch

File: v2/backend/app/services/edge_proof/evaluator.py

Changes:

1. New observed metric max_drawdown_bps_observed, computed as the
   maximum of |drawdown_bps| across every bundle's every outcome
   window. Surfaces as a top-level field in MetricSummary and in
   summary_to_dict.
2. New REQUIRED_THRESHOLDS tuple lists the seven thresholds that must
   all numerically pass before EDGE_PROVISIONAL_PAPER_PASS is allowed:
   - min_sample_count
   - min_after_cost_expectancy_bps
   - min_after_cost_lower_ci_bps
   - max_drawdown_bps_rolling
   - min_downside_pre_cascade_recall
   - max_false_positive_rate
   - max_false_negative_rate
3. New structured threshold_evidence list. Every row carries:
   - threshold_name
   - threshold_value
   - observed_value
   - passed
   - evidence_state in {NUMERIC_CHECK_PASSED, NUMERIC_CHECK_FAILED,
     OPERATOR_DECISION_REQUIRED, INSUFFICIENT_EVIDENCE, INVALID_THRESHOLD}
4. Hard safety thresholds (sample count, expectancy, CI lower,
   drawdown) are never vacuously satisfied: missing observed evidence
   yields INSUFFICIENT_EVIDENCE which fails the gate.
5. Rate thresholds (false positive, false negative, recall) remain
   vacuously satisfied when no data exists to evaluate.
6. Verdict logic now flips to EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
   on any OPERATOR_DECISION_REQUIRED or INVALID_THRESHOLD on a required
   threshold. EDGE_PROVISIONAL_PAPER_PASS requires every REQUIRED
   threshold to be NUMERIC_CHECK_PASSED.

## Cost-model marker patch

File: v2/backend/app/services/edge_proof/replay_miner.py

- COST_MODEL_NOTE now reads
  DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE_OPERATOR_DECISION_REQUIRED
- New module flag COST_MODEL_OPERATOR_OVERRIDE_REQUIRED = True
- _new_bundle_from_row sets the per-bundle market_snapshot fields:
  - fee_bps (default 5.0, visible)
  - slippage_estimate_bps (default 2.0, visible)
  - cost_model_source: full marker string
  - operator_override_required: True
  - operator_decision_required: True
  - default_fee_bps_visible: 5.0
  - default_slippage_estimate_bps_visible: 2.0

File: v2/backend/app/services/edge_proof/replay_schema.py

- emit_canonical_schema now exposes default_cost_model and
  required_thresholds_for_provisional_paper_pass. The default_cost_model
  block carries the literal OPERATOR_DECISION_REQUIRED in
  cost_model_source plus operator_override_required = True.

File: v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py

- status payload propagates cost_model_note (with literal),
  cost_model_operator_override_required, and visible defaults.

## Tests

Regression tests added in
v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py:

- test_drawdown_threshold_operator_pending_blocks_provisional_pass
- test_drawdown_threshold_missing_observation_blocks_provisional_pass
- test_drawdown_threshold_numeric_observed_exceeds_cap_blocks_provisional_pass
- test_provisional_pass_only_when_all_seven_required_thresholds_pass_numerically
- test_invalid_threshold_value_blocks_provisional_pass
- test_threshold_evidence_records_expected_fields_per_row
- test_evaluator_approvals_remain_false_on_provisional_paper_pass
- test_default_cost_model_contains_operator_decision_required_literal

Regression test updated in
v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py:

- test_default_paper_cost_model_contains_operator_decision_required_literal
  asserts the literal OPERATOR_DECISION_REQUIRED is inside
  COST_MODEL_NOTE; asserts COST_MODEL_OPERATOR_OVERRIDE_REQUIRED is True;
  asserts the bundle's market_snapshot exposes default_fee_bps_visible,
  default_slippage_estimate_bps_visible, operator_override_required,
  operator_decision_required.

Results:

- Focused evaluator tests: 34 of 34 passed.
- Focused miner tests: 18 of 18 passed.
- Combined regression sweep across evaluator + miner + website + report
  center: 74 of 74 passed.

## Artifacts refreshed

- claude_worklog/final_readiness/v2_native_edge_proof/latest/native_edge_proof_status.json
- claude_worklog/final_readiness/v2_native_edge_proof/latest/edge_metrics_summary.json
- claude_worklog/final_readiness/v2_native_edge_proof/latest/replay_bundle_schema.json
- v2/frontend/public/v2_native_edge_proof/latest/operator_dashboard_payload.json
- v2/frontend/public/v2_native_edge_proof/latest/edge_metrics_summary.json
- v2/frontend/public/v2_native_edge_proof/latest/replay_bundle_schema.json
- claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json
- claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/edge_metrics_summary.json
- claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/operator_dashboard_payload.json
- claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl
- v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/*

## Validation scans

- py_compile across modified modules: PASS.
- Old Redis write scan across edge-proof code: PASS, 0 hits.
- Exchange mutation scan across edge-proof code: PASS, 0 hits.
- Approval-token truthy scan across edge-proof artifacts: PASS, 0 hits.
- Raw-secret scan across edge-proof artifacts: PASS, 0 hits for AKIA,
  ASIA, PEM private-key headers, .local_secrets/.

## What this cycle did NOT do

- Did not install or enable the replay miner timer.
- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop legacy or V2 runtime.
- Did not stop continuous remediation, Codex governors, the report
  center indexer, the legacy log observer, the V2-vs-legacy comparator,
  the liquidation WSS daemon, or the position-history persistent tracker.
- Did not write old Redis keys.
- Did not call the exchange.
- Did not create approval markers or shutdown-acceptance files.
- Did not enable live or canary.
- Did not adopt Symbol Universe candidates.
- Did not adopt external feeds.
- Did not expose any raw API key.

## Safety scoreboard

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- did_not_install_or_enable_replay_miner_timer = true

## Operator next step

The evaluator now refuses EDGE_PROVISIONAL_PAPER_PASS in every
operator-pending, invalid, insufficient-evidence, or numeric-failure
case for any of the seven required thresholds, including
max_drawdown_bps_rolling. The cost model is unambiguously flagged as
operator-decision-required in every emitted bundle and summary. The
miner remains paper-only and is NOT timer-enabled.

When the operator decides to enable the miner timer (separate
operator action), the miner will start accumulating real future
outcome windows; only then does the evaluator gain the data needed
to potentially flip from EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
to any numeric verdict.
