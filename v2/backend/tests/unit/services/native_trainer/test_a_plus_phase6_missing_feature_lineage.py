from __future__ import annotations

import json

from v2.backend.app.services.native_trainer.a_plus_phase6_missing_feature_lineage import (
    build_phase6_missing_feature_lineage_status,
    write_phase6_missing_feature_lineage_artifacts,
)


def test_phase6_missing_feature_lineage_behavioral_proofs_ready() -> None:
    status = build_phase6_missing_feature_lineage_status(redis_client=None)

    assert status["status"] == "MISSING_CRITICAL_FEATURE_LINEAGE_FIX_READY"
    assert all(proof["passed"] for proof in status["behavioral_proofs"])
    assert status["pass_conditions"]["missing_feature_names_from_actual_snapshot"] is True
    assert status["pass_conditions"]["market_state_integrity_reads_canonical_masks"] is True
    assert status["pass_conditions"]["actual_missing_features_still_block"] is True
    assert status["places_real_order"] is False
    assert status["live_gate"] == "blocked_human_only"


def test_phase6_missing_feature_lineage_artifacts_written(tmp_path) -> None:
    goal_dir = tmp_path / "goal"
    public_dir = tmp_path / "public"

    status = write_phase6_missing_feature_lineage_artifacts(
        redis_client=None,
        repo_root=tmp_path,
        goal_dir=goal_dir,
        public_dir=public_dir,
    )

    goal_payload = json.loads((goal_dir / "missing_critical_feature_lineage_fix_status.json").read_text())
    public_payload = json.loads((public_dir / "missing_critical_feature_lineage_fix_status.json").read_text())
    assert goal_payload["status"] == status["status"]
    assert public_payload["status"] == status["status"]
