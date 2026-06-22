# V2 Native RL MASA/PPO P0.2F - Paper Fill Gate Remediation

Phase: P0.2F remediation.
Generated: 2026-05-16T06:00:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## Why this remediation exists

Codex flagged the original P0.2F payload because
expected_move_after_cost_bps was -68.46 yet
paper_fill_gate_status was OPEN. The validator only checked field
presence and ranges, not after-cost edge, feature freshness, flag
emptiness, or live_gate/live_symbols on the prediction.

## What was changed

- v2/backend/app/services/rl_core/trainer_output.py
  - Extended TrainerOutputRecord with feature_freshness_state,
    prediction_live_gate, prediction_live_symbols.
  - emit_trainer_output now copies feature_freshness_state from the
    snapshot observation and live_gate / live_symbols from the
    snapshot itself.
  - validate_for_paper_fill_gate now requires ALL of the following
    before opening the gate:
    - prediction_id non-empty
    - feature_snapshot_id non-empty
    - trainer_source == V2_NATIVE_RL_CORE
    - expected_move_after_cost_bps present and finite
    - expected_move_after_cost_bps >= 0 (no negative edge)
    - expected_move_after_cost_bps >= configured threshold
      (default 8.0 bps; overridable per call)
    - feature_freshness_state == CURRENT
    - missing_feature_flags is empty
    - stale_feature_flags is empty
    - confidence_calibrated in (0, 1]
    - prediction_live_gate == "blocked_human_only"
    - prediction_live_symbols == ()
  - Result dict now carries paper_fill_allowed and
    paper_fill_gate_block_reasons; the legacy blockers tuple is
    preserved as an alias.

- v2/backend/tests/integration/cli/test_v2_rl_core_p0_2f_trainer_output.py
  - Rewritten to 19 strict tests covering each block reason path
    and the open-gate path against a synthetic record with strong
    positive edge.

- v2/backend/app/cli/v2_rl_core_worker.py
  - New --p0-2f-paper-fill-gate flag attaches the strict
    P0.2F block to v2_rl_core_status.json.
  - --expected-move-after-cost-min-bps tunes the threshold (default 8.0).

## Block reasons enumerated

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

## Public payload (after remediation)

The canonical
v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json
now carries:

- p0_2f_paper_fill_gate.paper_fill_gate_status =
  BLOCKED_BY_TRAINER_OUTPUT_MALFORMED
- p0_2f_paper_fill_gate.paper_fill_allowed = false
- p0_2f_paper_fill_gate.expected_move_after_cost_bps = -68.46
- p0_2f_paper_fill_gate.paper_fill_gate_block_reasons =
  ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]

The previously-emitted negative-edge example is now blocked as
required by Codex.

## Test summary

```
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2f_trainer_output.py
.................... 19 passed
```

Plus the full sprint regression (rl_core, orchestrator, trade
management, ingestors, startup) continues to pass.

## Permanent migration contract checklist

- Legacy source paths: yes (P0.2B legacy citations still apply).
- SHA256: yes.
- Dependency closure: pure stdlib; no torch, no numpy, no redis.
- Config/env mapping: expected_move_after_cost_min_bps documented
  default 8.0; overridable per call and per CLI invocation.
- Behavior mapping: yes.
- V2 implementation: yes.
- Tests: yes (19 passing).
- Public payload: yes
  (v2_rl_core_status.json + trainer_output_status.json).
- Codex review: pending re-review on this remediation.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## What this does NOT change

- Full trainer migration: still NOT claimed. Classification
  remains partial until P0.2A through P0.2G earn Codex PASS and
  checkpoint / hedge / operator blockers are resolved or
  explicitly accepted for paper-only.
- live, canary, shutdown, redis trim: all remain BLOCKED.

## Decision

V2_NATIVE_RL_MASA_PPO_P0_2F_PAPER_FILL_GATE_REMEDIATION_READY at
the strict gate level. The paper fill gate now blocks negative
or sub-threshold edge, stale freshness, non-empty missing/stale
flags, missing trainer fields, and any live-state leak.
