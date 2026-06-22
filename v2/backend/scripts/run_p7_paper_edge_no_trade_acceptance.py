"""Phase 7: paper-edge no-trade acceptance packet emitter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.rl_core.trainer_output import (
    emit_trainer_output,
    trainer_output_invariants_snapshot,
    validate_for_paper_fill_gate,
)

SNAPSHOT = Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json")
TARGET_WORKLOG = Path(
    "claude_worklog/final_readiness/core_completion_blocker_burndown/latest/paper_edge_no_trade_acceptance_status.json"
)
TARGET_PUBLIC = Path(
    "v2/frontend/public/core_completion_blocker_burndown/latest/paper_edge_no_trade_acceptance_status.json"
)


def main() -> int:
    snap = json.loads(SNAPSHOT.read_text())
    rec = emit_trainer_output(snap)
    gate = validate_for_paper_fill_gate(rec)
    paper_fill_blocked = not gate["paper_fill_allowed"]
    expected_move_after_cost_bps = rec.expected_move_after_cost_bps
    no_trade_mode_classification = (
        "PAPER_EDGE_NOT_PROVEN_SAFE_NO_TRADE_MODE"
        if (paper_fill_blocked and expected_move_after_cost_bps < 0)
        else "PAPER_EDGE_POSITIVE_BUT_OPERATOR_ACCEPTANCE_STILL_REQUIRED"
    )
    out = {
        "phase": "P7_PAPER_EDGE_NO_TRADE_ACCEPTANCE",
        "schema_version": "v2_paper_edge_no_trade_acceptance_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "paper_fill_gate_status": gate["paper_fill_gate_status"],
        "paper_fill_allowed": gate["paper_fill_allowed"],
        "paper_fill_gate_block_reasons": list(gate["paper_fill_gate_block_reasons"]),
        "expected_move_bps": rec.expected_move_bps,
        "expected_move_after_cost_bps": rec.expected_move_after_cost_bps,
        "expected_move_after_cost_min_bps": gate["expected_move_after_cost_min_bps"],
        "current_no_trade_state": {
            "paper_fill_allowed": gate["paper_fill_allowed"],
            "open_positions": 0,
            "no_exchange_mutation": True,
            "no_old_redis_writes": True,
            "no_unsafe_post_remediation_fills": True,
        },
        "no_trade_mode_classification": no_trade_mode_classification,
        "operator_acceptance_packet": {
            "operator_accepts_no_trade_paper_only_for_legacy_shutdown": False,
            "this_packet_does_not_approve_live": True,
            "this_packet_does_not_approve_canary": True,
            "this_packet_does_not_loosen_paper_fill_gate": True,
            "this_packet_does_not_approve_trading": True,
            "what_operator_must_do": (
                "If the operator wishes to consider legacy shutdown while V2 has "
                "no positive paper edge yet, the operator must explicitly accept "
                "no-trade paper-only mode as a temporary state in the final "
                "burndown decision. This packet records the acceptance request; "
                "it does NOT auto-accept."
            ),
        },
        "trainer_output_invariants": trainer_output_invariants_snapshot(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    body = json.dumps(out, indent=2, sort_keys=True) + "\n"
    TARGET_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    TARGET_WORKLOG.write_text(body)
    TARGET_PUBLIC.write_text(body)
    print(
        "no_trade_mode_classification",
        no_trade_mode_classification,
        "paper_fill_allowed",
        gate["paper_fill_allowed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
