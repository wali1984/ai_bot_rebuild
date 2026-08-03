from __future__ import annotations

import json

from v2.backend.app.services.a_plus_trade_gate.service import CHECKS
from v2.backend.app.services.native_trainer.a_plus_phase8_trade_gate import (
    CONTRACT_TEST_PASSED,
    build_phase8_a_plus_gate_artifacts,
    write_phase8_a_plus_gate_artifacts,
)


def test_phase8_a_plus_gate_artifacts_are_synthetic_non_runtime_contract_proofs() -> None:
    artifacts = build_phase8_a_plus_gate_artifacts()
    status = artifacts["status"]
    candidates = artifacts["candidate_matrix"]
    rejected = candidates["rejected_candidates"]

    assert status["status"] == CONTRACT_TEST_PASSED
    assert status["contract_tests_passed"] is True
    assert status["contract_test_conditions"]["a_plus_candidate_positive_path_exists"] is True
    assert status["contract_test_conditions"]["all_required_checks_present"] is True
    assert status["contract_test_conditions"]["all_required_checks_can_fail_closed"] is True
    assert status["contract_test_conditions"]["no_non_a_plus_row_can_be_live"] is True
    assert len(rejected) == len(CHECKS)
    assert all(row["contract_evaluator_a_plus"] is False for row in rejected)
    assert all(row["contract_evaluator_live_candidate_eligible"] is False for row in rejected)
    assert all(row["expected_failed_check_present"] is True for row in rejected)
    accepted = candidates["accepted_candidates"][0]
    assert accepted["contract_evaluator_a_plus"] is True
    assert accepted["contract_evaluator_paper_tradeable"] is True
    assert accepted["synthetic_fixture"] is True
    assert accepted["eligible_as_runtime_candidate"] is False
    assert accepted["canonical_a_plus_authorized"] is False
    assert "a_plus" not in accepted
    assert "paper_tradeable" not in accepted
    assert "live_candidate_eligible" not in accepted
    for payload in artifacts.values():
        assert payload["evidence_scope"] == "SYNTHETIC_CONTRACT_TEST_ONLY"
        assert payload["contract_test_only"] is True
        assert payload["canonical_runtime_ready"] is False
        assert payload["serving_authorized"] is False
        assert payload["a_plus_authorized"] is False
        assert payload["paper_authorized"] is False
        assert payload["live_authorized"] is False
        assert payload["artifact_ttl_enforced"] is False
        assert payload["artifact_freshness_authoritative"] is False


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
        assert goal_payload["canonical_runtime_ready"] is False
        assert public_payload["a_plus_authorized"] is False
