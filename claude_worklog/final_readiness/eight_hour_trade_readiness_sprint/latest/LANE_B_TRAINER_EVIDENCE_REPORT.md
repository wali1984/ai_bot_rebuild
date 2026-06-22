# Lane B — Trainer Evidence Inspection (8h Sprint)

Generated: 2026-05-15
Lane: B
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Inputs

Inspected (read-only, no mutation, no training started):
- `v2/legacy_preserved/full_runtime_closure/rl/hybrid_trainer.py` (57,250 lines)
- `v2/legacy_preserved/full_runtime_closure/rl/calibrated_confidence.py`
- `v2/legacy_preserved/full_runtime_closure/rl/temperature_calibration.py`
- `v2/legacy_preserved/full_runtime_closure/rl/calibrated_confidence.py`
- `v2/legacy_preserved/full_runtime_closure/trading/adaptive_edge_gate.py`
- `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`

## Native evidence found in legacy trainer

| Field | Present in legacy? | Notes |
|-------|-------------------|-------|
| `expected_move_pct` (raw, ATR-derived) | YES (13 references in hybrid_trainer.py) | Computed from `atr_pct * atr_multiplier * tf_mult * conf_scale * value_scale`, clamped to `[0.002, 0.25]`. |
| `calibrated_confidence` | YES, but gated by Redis feature flag `rl:config:features.calibrated_confidence` | Implemented in `calibrated_confidence.py` via temperature scaling. If flag is off, returns raw confidence. |
| `feature_snapshot_id` (V2 contract name) | NO | Legacy does not emit a stable feature-snapshot identifier in V2-compatible form. |
| `feature_attribution` (top-positive / top-negative) | NO | Legacy does not emit a structured per-prediction attribution table. |
| `expected_move_after_cost_bps` | NO | Legacy computes `expected_move_pct` (raw), not a cost-aware after-cost estimate. |
| `model_version` | YES (via `MODEL_VERSION`/checkpoint metadata) | Used in trainer log lines. |
| `checkpoint_id` | YES | Tracked by `checkpoint_manager.py`. |

## Honest classification

Under the migration completion contract:

- The V2 trainer bridge is correctly classified `READONLY_BRIDGED` / `PAPER_ONLY`.
- It is NOT `MIGRATED_CODEX_PASS`.
- The current bridge classification `DERIVED_FROM_LEGACY_LOG` is honest: it
  derives V2 fields (`expected_move_after_cost_bps`, `feature_snapshot_id`,
  per-prediction `confidence_calibrated`) from legacy log/Redis state that does
  not natively emit those fields under the V2 contract name.
- The `calibrated_confidence` path exists natively. If the Redis feature flag is
  on, native calibrated confidence is available. If off, V2 must record
  `confidence_calibration_mode=DERIVED_FROM_LEGACY_LOG` (current state).

## What would close the trainer parity gap

To advance from `READONLY_BRIDGED` to `MIGRATED_CODEX_PASS`, the trainer bridge
must add (with Codex PASS for each):

1. Native cost-aware expected-move emitter, computing
   `expected_move_after_cost_bps = expected_move_pct * 1e4 - cost_bps`, with
   cost_bps derived from the live fee schedule. This is a thin V2-side adapter
   over the existing legacy emitter, not a trainer rewrite.
2. Native `feature_snapshot_id` emitter, with `sha256(feature_payload)` as the
   id and a `feature_snapshot_age_seconds` field. Adapter only.
3. Native `feature_attribution` table extraction from legacy hybrid trainer
   gradients or SHAP-style export (one of several legacy paths). This is the
   non-trivial piece. If unavailable, must remain `INCOMPLETE` honestly.
4. Calibrated-confidence Redis feature flag must be confirmed `enabled` and a
   recent temperature record must exist in `rl:calibration:temperature`.

## Operator paper-only acceptance packet

Path:
`claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest/TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md`

The router (`v2_permanent_objective_router.py`) already emits
`TRAINER_PARITY_INCOMPLETE` as P0 and points to that acceptance packet for
operators who wish to accept derived evidence for paper-only shutdown
evaluation. **No new acceptance is granted by this lane.** Live and canary
remain blocked.

## What this lane does NOT do

- Does not start legacy trainer.
- Does not modify the protected trainer venv.
- Does not write to legacy Redis.
- Does not authorize live, canary, or legacy shutdown.
- Does not fabricate native attribution evidence.

## GO/NO-GO for Lane B

`LANE_B_TRAINER_EVIDENCE_DERIVED_PAPER_ONLY_HONEST_CLASSIFICATION`

(This is not a "ready for live" label — it confirms honest classification of
derived/paper-only evidence under the migration contract.)

Live remains `blocked_human_only`.
