# Trainer + Signal Explainability UI Report

Every prediction the V2 trainer emits must be paired with the exact
evidence behind it: input features, snapshot ID, model version,
checkpoint marker, raw output, calibrated confidence, freshness
state, and any missing-evidence flags. This page makes that pairing
visible to operators.

## Page: `/bot-intelligence`

### Header band

- Sticky `live_gate=blocked_human_only` chip.
- Sticky `checkpoint_compatibility_claimed=false` chip.
- Sticky `policy_architecture_parity_claimed=false` chip.
- Sticky `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` chip when state is partial.

These four chips never disappear while the underlying invariant holds.
They are visible in the top third of the viewport on every device.

### Trainer prediction monitor (per symbol)

Source: `v2:prediction:{symbol}:1m` + `v2:trainer:heartbeat` +
`v2:features:latest:{symbol}:1m`.

Surfaced fields:

| Field | Source field |
|---|---|
| model_version | trainer heartbeat |
| checkpoint marker | trainer heartbeat |
| last prediction (ms ago) | derived from prediction.generated_utc |
| raw output | prediction.raw_output |
| argmax action | prediction.selected_action |
| confidence raw | prediction.confidence_raw |
| confidence calibrated | prediction.confidence_calibrated |
| feature freshness state | feature snapshot |
| feature_snapshot_id | feature snapshot |
| missing feature flags | feature snapshot.missing_feature_flags |
| stale feature flags | feature snapshot.stale_feature_flags |

When a field is absent, the row renders `MISSING` with the exact key
name. The card NEVER renders an empty zero, NEVER guesses confidence,
and NEVER fabricates a checkpoint marker.

### Full-observation builder progress

Source:
`v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`

Renders:

- `state` (must show `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` while partial).
- `target_full_observation_dim = 1911` (never re-labeled).
- `per_symbol_generated_dim` table (e.g. BTCUSDT 156 / 1911).
- `subfamily_present_counts_total` vs `subfamily_target_counts_total` bar grid.
- Explicit `checkpoint_compatibility_claimed=false` and `policy_architecture_parity_claimed=false` lines.

### Feature missing / stale flags panel

Per symbol, list the contents of `missing_feature_flags` and
`stale_feature_flags` from the feature snapshot. Each entry renders
as a chip with the feature name and the categorical reason
(`*_missing` vs `*_stale`).

### Paper-fill gate block reasons

Source: `v2:paper:intents_held_by_paper_fill_gate`.

Per held intent, render:

- `symbol`, `selected_action_upstream`, `paper_fill_gate_status`
- the full `paper_fill_gate_block_reasons` array as chips
  (NEGATIVE_EXPECTED_MOVE_AFTER_COST, EDGE_AFTER_COST_BELOW_THRESHOLD,
  FEATURE_FRESHNESS_NOT_CURRENT, CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED, etc.)
- `checkpoint_blocker` if present, with explicit `operator_required`
  framing
- `source_prediction_id` and `feature_snapshot_id` for cross-referencing
  on the same page

### Checkpoint blocker chip

Reads any payload that asserts a checkpoint requirement. When the
blocker is `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`, render a red
chip + a short operator-readable explanation: "checkpoint weight
blob is operator-decision-required; trainer cannot promote without
operator approval."

### Per-prediction explainability drawer

Clicking a prediction row opens a side drawer with:

- Full feature snapshot table (every key from the snapshot)
- Source key path (`v2:features:latest:{symbol}:1m`)
- Feature freshness state with timestamp + age
- The raw trainer output array
- The calibrated probability vector
- The orchestrator decision derived from this prediction (if any)
- The risk gate result (if any)
- Audit pointer: `feature_snapshot_id` → `prediction_id` → `signal_id` → `risk_decision_id` → `execution_intent_id` chain

If any chain hop is missing, the drawer shows the missing hop with
its source key — never fabricates a hop.

## Read-only guarantees

- No "promote checkpoint" button on the user surface (admin-only).
- No "force prediction" button anywhere.
- No "approve checkpoint compatibility" button anywhere.
- No "enable canary" / "enable live" button anywhere.

## What this report does NOT do

It does not ship the TSX drawer / table components. The wiring rules
above let a separate frontend packet implement panel readers without
re-designing payload contracts.
