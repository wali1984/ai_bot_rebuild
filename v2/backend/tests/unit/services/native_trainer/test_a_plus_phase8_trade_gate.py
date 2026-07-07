from __future__ import annotations

import json

from v2.backend.app.services.a_plus_trade_gate.service import CHECKS
from v2.backend.app.services.native_trainer.a_plus_phase8_trade_gate import (
    build_phase8_a_plus_gate_artifacts,
    write_phase8_a_plus_gate_artifacts,
)


def test_phase8_a_plus_gate_artifacts_prove_positive_and_rejection_paths() -> None:
    artifacts = build_phase8_a_plus_gate_artifacts()
    status = artifacts["status"]
    candidates = artifacts["candidate_matrix"]
    rejected = candidates["rejected_candidates"]

    assert status["status"] == "A_PLUS_ZERO_TOLERANCE_GATE_READY"
    assert status["pass_conditions"]["a_plus_candidate_positive_path_exists"] is True
    assert status["pass_conditions"]["all_required_checks_present"] is True
    assert status["pass_conditions"]["all_required_checks_can_fail_closed"] is True
    assert status["pass_conditions"]["no_non_a_plus_row_can_be_live"] is True
    assert len(rejected) == len(CHECKS)
    assert all(row["a_plus"] is False for row in rejected)
    assert all(row["live_candidate_eligible"] is False for row in rejected)
    assert all(row["expected_failed_check_present"] is True for row in rejected)
    assert candidates["accepted_candidates"][0]["a_plus"] is True
    assert candidates["accepted_candidates"][0]["paper_tradeable"] is True


def test_phase8_a_plus_gate_artifacts_written(tmp_path) -> None:
    goal_dir = tmp_path / "goal"
    public_dir = tmp_path / "public"

    status = write_phase8_a_plus_gate_artifacts(goal_dir=goal_dir, public_dir=public_dir)

    for name in (
        "a_plus_trade_gate_status.json",
        "a_plus_candidate_matrix.json",
        "a_plus_rejected_reason_matrix.json",
    ):
        goal_payload = json.loads((goal_dir / name).read_text())
        public_payload = json.loads((public_dir / name).read_text())
        assert goal_payload["goal_id"] == status["goal_id"]
        assert public_payload["goal_id"] == status["goal_id"]
