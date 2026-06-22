# V2 Native RL MASA/PPO P0.2F - Trainer Output Contract

Phase P0.2F; Sprint 12h native core migration.

Last refreshed: 2026-05-16T06:15:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541
Authoritative companion: V2_NATIVE_RL_MASA_PPO_P0_2F_REMEDIATION_REPORT.md

NOTE: This report has been refreshed to match the post-remediation
strict paper-fill-gate. The prior prose (which incorrectly described
the negative-edge sample as opening the gate) has been removed.

## What was built

- v2/backend/app/services/rl_core/trainer_output.py emits a single
  trainer prediction record per native feature snapshot.
  Fields: prediction_id, feature_snapshot_id,
  trainer_source=V2_NATIVE_RL_CORE, checkpoint_id or explicit
  checkpoint_blocker, expected_move_bps from the native policy
  expected-move scalar head, expected_move_after_cost_bps,
  confidence_raw from native softmax, confidence_calibrated via
  temperature scaling on the selected-action logit,
  top_positive_features and top_negative_features from
  finite-difference sensitivity attribution (labeled honestly via
  attribution_method), missing_feature_flags, stale_feature_flags,
  policy_action_probabilities, feature_freshness_state,
  prediction_live_gate, prediction_live_symbols.
- validate_for_paper_fill_gate() returns
  TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN only when ALL strict
  conditions are met (see Strict Gate section). Otherwise it returns
  BLOCKED_BY_TRAINER_OUTPUT_MISSING or
  BLOCKED_BY_TRAINER_OUTPUT_MALFORMED with the enumerated block
  reason(s).
- v2/backend/tests/integration/cli/test_v2_rl_core_p0_2f_trainer_output.py
  has 19 passing tests covering the open-gate path and every block
  reason.

## Strict gate conditions (post-remediation)

The gate opens only when ALL of the following are true:

- prediction_id present
- feature_snapshot_id present
- trainer_source == V2_NATIVE_RL_CORE
- expected_move_after_cost_bps present and finite
- expected_move_after_cost_bps >= 0 (no negative edge)
- expected_move_after_cost_bps >= expected_move_after_cost_min_bps
  (default 8.0 bps; tunable per call / per CLI invocation)
- feature_freshness_state == CURRENT
- missing_feature_flags == []
- stale_feature_flags == []
- confidence_calibrated in (0, 1]
- prediction_live_gate == blocked_human_only
- prediction_live_symbols == []

## Enumerated block reasons

- MISSING_PREDICTION_ID_BLOCK
- MISSING_FEATURE_SNAPSHOT_ID_BLOCK
- MISSING_TRAINER_SOURCE_BLOCK
- MISSING_EXPECTED_MOVE_AFTER_COST_BLOCK
- NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK
- EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK
- FEATURE_FRESHNESS_NOT_CURRENT_BLOCK
- MISSING_FEATURE_FLAGS_BLOCK
- STALE_FEATURE_FLAGS_BLOCK
- CONFIDENCE_MISSING_OR_INVALID_BLOCK
- LIVE_GATE_NOT_BLOCKED_BLOCK
- LIVE_SYMBOLS_NOT_EMPTY_BLOCK

## Run snapshot against the live P0.1 snapshot (post-remediation)

The current native feature snapshot produces a NEGATIVE after-cost
edge, so the strict gate correctly BLOCKS it:

- paper_fill_gate_status: BLOCKED_BY_TRAINER_OUTPUT_MALFORMED
- paper_fill_allowed: false
- paper_fill_gate_block_reasons: ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]
- expected_move_bps: -56.46
- expected_move_after_cost_bps: -68.46 (= -56.46 - 12.0 round-trip cost)
- expected_move_after_cost_min_bps (threshold): 8.0
- confidence_calibrated: 0.565 (T=1.5 temperature scaling)
- checkpoint_blocker: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
- feature_freshness_state: CURRENT
- missing_feature_flags: []
- stale_feature_flags: []
- prediction_live_gate: blocked_human_only
- prediction_live_symbols: []

The authoritative JSON for this run is
trainer_output_status.json in this directory and the
p0_2f_paper_fill_gate block of
v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json.

## Confidence and attribution honesty

- Confidence is computed entirely from V2-native policy softmax
  (raw) plus temperature scaling (calibrated). It is never derived
  from legacy log lines.
- Attribution method is honestly labeled as
  simple_sensitivity_finite_difference_on_selected_action_prob.
  This is not Shapley/Integrated Gradients/feature ablation, and
  the trainer output record says so. No fabrication.
- Crucially, high confidence alone cannot open the gate: a
  high-confidence record with a negative after-cost edge remains
  BLOCKED with NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK.

## Permanent migration contract checklist

- Legacy source path: yes (RL policy is the source of truth; legacy
  trainer's prediction_to_signal conversion is preserved at the
  surface level).
- SHA256: yes (via policy.py legacy citations + checkpoint module).
- Dependency closure: pure stdlib.
- Config/env mapping: temperature is a runtime knob with default 1.5;
  round-trip cost defaults to 12 bps;
  expected_move_after_cost_min_bps defaults to 8.0 bps.
- Behavior mapping: yes (emit + validate_for_paper_fill_gate mirrors
  the legacy trainer output contract for paper trade decisions).
- V2 implementation: yes.
- Tests: yes (19 passing in test_v2_rl_core_p0_2f_trainer_output.py).
- Public payload: yes (trainer_output_status.json and the
  p0_2f_paper_fill_gate block in v2_rl_core_status.json).
- Codex review: V2_NATIVE_RL_MASA_PPO_P0_2F_REMEDIATION_CODEX_PASS.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P0.2F is READY at the strict paper-fill-gate contract level. The
gate now refuses to open for negative or sub-threshold after-cost
edge, stale or missing features, malformed trainer output, or any
live-state leak. Real checkpoint-backed expected-move and
confidence remain gated by the operator + Codex approval flow
defined in P0.2C. Full trainer migration is NOT claimed.
