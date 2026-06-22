"""Helper: emit the strict P0.2F trainer output payload."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.rl_core.trainer_output import (
    ALL_BLOCK_REASONS,
    DEFAULT_EDGE_AFTER_COST_MIN_BPS,
    emit_trainer_output,
    trainer_output_invariants_snapshot,
    validate_for_paper_fill_gate,
)

SNAPSHOT = Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json")
TARGET = Path(
    "claude_worklog/final_readiness/v2_native_rl_masa_ppo_p0_2f/latest/trainer_output_status.json"
)


def main() -> int:
    snap = json.loads(SNAPSHOT.read_text())
    rec = emit_trainer_output(snap)
    gate = validate_for_paper_fill_gate(rec)
    out = {
        "prediction_id": rec.prediction_id,
        "feature_snapshot_id": rec.feature_snapshot_id,
        "trainer_source": rec.trainer_source,
        "checkpoint_id": rec.checkpoint_id,
        "checkpoint_blocker": rec.checkpoint_blocker,
        "expected_move_bps": rec.expected_move_bps,
        "expected_move_after_cost_bps": rec.expected_move_after_cost_bps,
        "confidence_raw": rec.confidence_raw,
        "confidence_calibrated": rec.confidence_calibrated,
        "confidence_temperature": rec.confidence_temperature,
        "confidence_used_calibration": rec.confidence_used_calibration,
        "top_positive_features": [
            {"feature_name": a.feature_name, "sensitivity": a.sensitivity}
            for a in rec.top_positive_features
        ],
        "top_negative_features": [
            {"feature_name": a.feature_name, "sensitivity": a.sensitivity}
            for a in rec.top_negative_features
        ],
        "attribution_method": rec.attribution_method,
        "missing_feature_flags": list(rec.missing_feature_flags),
        "stale_feature_flags": list(rec.stale_feature_flags),
        "policy_action_labels": list(rec.policy_action_labels),
        "policy_action_probabilities": list(rec.policy_action_probabilities),
        "hedge_action_classification": rec.hedge_action_classification,
        "selected_action": rec.selected_action,
        "generated_utc": rec.generated_utc,
        "feature_freshness_state": rec.feature_freshness_state,
        "prediction_live_gate": rec.prediction_live_gate,
        "prediction_live_symbols": list(rec.prediction_live_symbols),
        "scope": rec.scope,
        "paper_fill_gate_status": gate["paper_fill_gate_status"],
        "paper_fill_allowed": gate["paper_fill_allowed"],
        "paper_fill_gate_block_reasons": list(gate["paper_fill_gate_block_reasons"]),
        "paper_fill_gate_blockers": list(gate["blockers"]),
        "expected_move_after_cost_min_bps": gate["expected_move_after_cost_min_bps"],
        "all_known_block_reasons": list(ALL_BLOCK_REASONS),
        "default_edge_after_cost_min_bps": DEFAULT_EDGE_AFTER_COST_MIN_BPS,
        "invariants": trainer_output_invariants_snapshot(),
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "gate_status",
        gate["paper_fill_gate_status"],
        "paper_fill_allowed",
        gate["paper_fill_allowed"],
        "em_after_cost",
        rec.expected_move_after_cost_bps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
