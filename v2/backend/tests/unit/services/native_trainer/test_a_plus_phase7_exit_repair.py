from __future__ import annotations

import json

from v2.backend.app.services.native_trainer.a_plus_phase7_exit_repair import (
    build_phase7_exit_repair_status,
    write_phase7_exit_repair_artifacts,
)


def test_phase7_exit_repair_behavioral_proofs_ready() -> None:
    status = build_phase7_exit_repair_status(repair_deployed_utc="2026-07-06T20:00:00Z")

    assert status["status"] == "ATR_STOP_CLUSTER_REPAIR_READY"
    assert status["repair_test_passed"] is True
    assert all(proof["passed"] for proof in status["behavioral_proofs"])
    assert status["pass_conditions"]["atr_stop_floor_active"] is True
    assert status["pass_conditions"]["stop_multiplier_by_regime_active"] is True
    assert status["pass_conditions"]["mfe_protection_active"] is True
    assert status["pass_conditions"]["bucket_quarantine_for_atr_losers_active"] is True
    assert status["paper_entry_freeze_mutated"] is False
    assert status["places_real_order"] is False
    assert status["live_gate"] == "blocked_human_only"


def test_phase7_exit_repair_artifacts_written(tmp_path) -> None:
    goal_dir = tmp_path / "goal"
    public_dir = tmp_path / "public"

    status = write_phase7_exit_repair_artifacts(
        repo_root=tmp_path,
        goal_dir=goal_dir,
        public_dir=public_dir,
        repair_deployed_utc="2026-07-06T20:00:00Z",
    )

    for name in (
        "atr_stop_cluster_repair_status.json",
        "adaptive_exit_repair_status.json",
        "mfe_protection_status.json",
    ):
        goal_payload = json.loads((goal_dir / name).read_text())
        public_payload = json.loads((public_dir / name).read_text())
        assert goal_payload["repair_test_passed"] == status["repair_test_passed"]
        assert public_payload["repair_test_passed"] == status["repair_test_passed"]
