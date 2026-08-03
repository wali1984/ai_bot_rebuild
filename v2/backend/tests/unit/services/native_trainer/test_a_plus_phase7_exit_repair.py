from __future__ import annotations

import json
import hashlib

from v2.backend.app.services.native_trainer.a_plus_phase7_exit_repair import (
    build_phase7_exit_repair_status,
    write_phase7_exit_repair_artifacts,
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _valid_receipt(status: dict, *, run_id: str = "phase7_run_current") -> dict:
    validation = status["executed_contract_receipt"]
    receipt = {
        "schema_version": "v2_a_plus_phase7_executed_contract_receipt_v1",
        "run_id": run_id,
        "completed_at": "2026-07-06T20:00:00Z",
        "expires_at": "2026-07-06T20:30:00Z",
        "pytest_nodeid": (
            "v2/backend/tests/unit/services/native_trainer/"
            "test_a_plus_phase7_exit_repair.py::"
            "test_phase7_exit_repair_behavioral_contract"
        ),
        "outcome": "PASSED",
        "exit_code": 0,
        "runner_command": (
            ".venv/bin/pytest -q v2/backend/tests/unit/services/native_trainer/"
            "test_a_plus_phase7_exit_repair.py::"
            "test_phase7_exit_repair_behavioral_contract"
        ),
        "test_source_sha256": validation["test_source_sha256"],
        "production_source_sha256": validation["production_source_sha256"],
        "diagnostic_output_sha256": validation["diagnostic_output_sha256"],
    }
    receipt["runner_command_sha256"] = hashlib.sha256(
        receipt["runner_command"].encode("utf-8")
    ).hexdigest()
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt


def test_phase7_exit_repair_behavioral_contract() -> None:
    status = build_phase7_exit_repair_status(
        repair_deployed_utc="2026-07-06T20:00:00Z",
        generated_utc="2026-07-06T20:10:00Z",
    )

    assert status["status"] == "ATR_STOP_CLUSTER_REPAIR_BLOCKED_NONCANONICAL_EVIDENCE"
    assert status["repair_test_passed"] is False
    assert all(proof["passed"] for proof in status["behavioral_proofs"])
    assert all(
        proof["evidence_class"]
        == "NONCANONICAL_DIAGNOSTIC_SYNTHETIC_SCENARIO"
        for proof in status["behavioral_proofs"]
    )
    assert status["behavioral_proofs_count_as_a_plus_readiness"] is False
    assert status["pass_conditions"]["atr_stop_floor_active"] is False
    assert status["pass_conditions"]["stop_multiplier_by_regime_active"] is False
    assert status["pass_conditions"]["mfe_protection_active"] is False
    assert status["pass_conditions"]["bucket_quarantine_for_atr_losers_active"] is False
    assert all(status["diagnostic_pass_conditions"].values())
    assert status["diagnostic_pass_conditions_count_as_a_plus_readiness"] is False
    assert status["paper_entry_freeze_mutated"] is False
    assert status["places_real_order"] is False
    assert status["live_gate"] == "blocked_human_only"


def test_phase7_valid_executed_test_receipt_still_cannot_replace_runtime_evidence() -> None:
    initial = build_phase7_exit_repair_status(
        generated_utc="2026-07-06T20:10:00Z",
        evidence_run_id="phase7_run_current",
    )
    status = build_phase7_exit_repair_status(
        generated_utc="2026-07-06T20:10:00Z",
        evidence_run_id="phase7_run_current",
        execution_receipt=_valid_receipt(initial),
    )

    assert status["executed_contract_receipt"]["valid"] is True
    assert status["repair_test_passed"] is False
    assert status["paper_entry_freeze_clear_allowed_by_exit_repair"] is False
    assert (
        status["pass_conditions"][
            "canonical_current_paper_exit_runtime_evidence_present"
        ]
        is False
    )


def test_phase7_receipt_tamper_and_expiry_fail_closed() -> None:
    initial = build_phase7_exit_repair_status(
        generated_utc="2026-07-06T21:00:00Z",
        evidence_run_id="phase7_run_current",
    )
    receipt = _valid_receipt(initial)
    receipt["diagnostic_output_sha256"] = "b" * 64
    receipt["receipt_sha256"] = _canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    status = build_phase7_exit_repair_status(
        generated_utc="2026-07-06T21:00:00Z",
        evidence_run_id="phase7_run_current",
        execution_receipt=receipt,
    )

    assert status["executed_contract_receipt"]["valid"] is False
    assert {
        "EXECUTED_CONTRACT_RECEIPT_NOT_CURRENT",
        "EXECUTED_CONTRACT_RECEIPT_OUTPUT_MISMATCH",
    }.issubset(status["executed_contract_receipt"]["rejection_reasons"])


def test_phase7_exit_repair_artifacts_written(tmp_path) -> None:
    goal_dir = tmp_path / "goal"
    public_dir = tmp_path / "public"

    status = write_phase7_exit_repair_artifacts(
        repo_root=tmp_path,
        goal_dir=goal_dir,
        public_dir=public_dir,
        repair_deployed_utc="2026-07-06T20:00:00Z",
        generated_utc="2026-07-06T20:10:00Z",
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
        assert goal_payload["behavioral_proofs_count_as_a_plus_readiness"] is False
