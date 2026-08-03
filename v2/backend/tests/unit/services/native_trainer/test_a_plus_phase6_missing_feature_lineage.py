from __future__ import annotations

import json

from v2.backend.app.services.native_trainer.a_plus_phase6_missing_feature_lineage import (
    CONTRACT_TEST_PASSED,
    build_phase6_missing_feature_lineage_status,
    write_phase6_missing_feature_lineage_artifacts,
)


def test_phase6_missing_feature_lineage_behavioral_proofs_are_non_runtime_contract_tests() -> None:
    status = build_phase6_missing_feature_lineage_status(redis_client=None)

    assert status["status"] == CONTRACT_TEST_PASSED
    assert status["contract_tests_passed"] is True
    assert all(proof["passed"] for proof in status["behavioral_proofs"])
    assert status["contract_test_conditions"]["missing_feature_names_from_actual_snapshot"] is True
    assert status["contract_test_conditions"]["market_state_integrity_reads_canonical_masks"] is True
    assert status["contract_test_conditions"]["actual_missing_features_still_block"] is True
    assert status["runtime_sample_authoritative"] is False
    assert status["runtime_sample_observed"] is False
    assert status["runtime_sample_false_positive_free"] is None
    assert status["evidence_scope"] == "SYNTHETIC_CONTRACT_TEST_ONLY"
    assert status["contract_test_only"] is True
    assert status["canonical_runtime_ready"] is False
    assert status["serving_authorized"] is False
    assert status["a_plus_authorized"] is False
    assert status["paper_authorized"] is False
    assert status["live_authorized"] is False
    assert status["artifact_ttl_enforced"] is False
    assert status["artifact_freshness_authoritative"] is False
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
    assert goal_payload["canonical_runtime_ready"] is False
    assert public_payload["artifact_ttl_enforced"] is False
