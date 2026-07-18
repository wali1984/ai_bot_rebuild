from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from v2.backend.app.services.native_trainer.current_cycle_evidence import (
    EXACT_PARITY_MATRIX_SCHEMA,
    EXECUTED_CONTRACT_RECEIPT_SCHEMA,
    build_current_cycle_parity_attestation,
    build_current_cycle_prediction_publication_evidence,
    canonical_sha256,
    capture_cycle_identity,
    process_instance_id,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    REDIS_STATUS_KEY,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    V2HybridPredictionPublisher,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_parity_fixture(
    *,
    root: Path,
    exact: bool,
    receipt_cycle_id: str = "v2_cycle_parity_exact",
    receipt_process_instance_id: str = "unit-host:123",
) -> None:
    legacy_path = root / "v2/legacy_owned_runtime/rl/hybrid_trainer.py"
    native_path = root / (
        "v2/backend/app/services/native_trainer/"
        "hybrid_cuda_trainer/native_contract.py"
    )
    test_path = root / "v2/backend/tests/unit/test_native_contract.py"
    matrix_path = root / (
        "v2/frontend/public/"
        "v2_native_hybrid_trainer_full_function_parity_and_paper_reverify/"
        "latest/hybrid_trainer_324_method_parity_matrix.json"
    )
    for path in (legacy_path, native_path, test_path, matrix_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        "class HybridTrainer:\n"
        "    def train(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    native_path.write_text(
        "def train_native():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    test_path.write_text(
        "def test_train_contract():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    native_relative = str(native_path.relative_to(root))
    test_relative = str(test_path.relative_to(root))
    native_hash = _sha256(native_path)
    test_hash = _sha256(test_path)
    production_digest = canonical_sha256(
        sorted({native_relative: native_hash}.items())
    )
    receipt = {
        "schema_version": EXECUTED_CONTRACT_RECEIPT_SCHEMA,
        "pytest_nodeid": f"{test_relative}::test_train_contract",
        "outcome": "PASSED",
        "exit_code": 0,
        "executed_utc": "2026-07-18T12:00:00Z",
        "cycle_id": receipt_cycle_id,
        "process_instance_id": receipt_process_instance_id,
        "test_source_sha256": test_hash,
        "production_source_set_digest": production_digest,
        "runner_command_sha256": "a" * 64,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    row: dict[str, object] = {
        "method": "train",
        "lineno": 2,
        "end_lineno": 3,
        "required_for_full_v2_parity": True,
        "classification": "NATIVELY_REPLACED",
        "native_replacement": native_relative,
    }
    if exact:
        row.update(
            {
                "native_symbol_attestations": [
                    {
                        "path": native_relative,
                        "qualified_name": "train_native",
                        "source_sha256": native_hash,
                    }
                ],
                "contract_test_attestations": [
                    {
                        "path": test_relative,
                        "qualified_name": "test_train_contract",
                        "source_sha256": test_hash,
                        "executed_contract_receipt": receipt,
                    }
                ],
            }
        )
    matrix = {
        "schema_version": (
            EXACT_PARITY_MATRIX_SCHEMA if exact else "legacy_declarative_v1"
        ),
        "legacy_method_count": 1,
        "required_missing_count": 0,
        "methods": [row],
    }
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")


def test_cycle_identity_is_collision_resistant_and_process_bound() -> None:
    first = capture_cycle_identity()
    second = capture_cycle_identity()

    assert first["cycle_id"] != second["cycle_id"]
    assert first["cycle_id"].startswith("v2_cycle_")
    assert len(first["cycle_id"]) == len("v2_cycle_") + 32
    assert first["process_instance_id"] == process_instance_id()
    assert second["process_instance_id"] == first["process_instance_id"]
    process_parts = first["process_instance_id"].rsplit(":", 2)
    assert len(process_parts) == 3
    assert int(process_parts[1]) > 0
    assert len(process_parts[2]) == 32


def test_complete_prediction_grid_requires_exact_single_cycle_identity() -> None:
    identity = {
        "cycle_id": "v2_cycle_grid_test",
        "process_instance_id": "unit-host:123",
        "checkpoint_id": "checkpoint-grid-test",
        "candidate_policy_fingerprint": "b" * 64,
    }
    rows = [
        {
            **identity,
            "symbol": "BTCUSDT",
            "timeframe": timeframe,
            "status": "PRESENT_CURRENT",
        }
        for timeframe in ("1m", "5m")
    ]

    complete = build_current_cycle_prediction_publication_evidence(
        rows=rows,
        expected_prediction_count=2,
        lineages_published=2,
        generated_utc="2026-07-18T12:00:00Z",
        publication_attempted=True,
        **identity,
    )
    mixed = build_current_cycle_prediction_publication_evidence(
        rows=[rows[0], {**rows[1], "cycle_id": "v2_cycle_other"}],
        expected_prediction_count=2,
        lineages_published=2,
        generated_utc="2026-07-18T12:00:00Z",
        publication_attempted=True,
        **identity,
    )

    assert complete["publication_complete"] is True
    assert mixed["publication_complete"] is False
    assert (
        "PREDICTION_GRID_IDENTITY_MIXED_OR_LEGACY"
        in mixed["publication_rejection_reasons"]
    )


def test_declarative_parity_matrix_never_counts_as_current_cycle_parity(
    tmp_path: Path,
) -> None:
    _write_parity_fixture(root=tmp_path, exact=False)

    evidence = build_current_cycle_parity_attestation(
        repo_root=tmp_path,
        cycle_id="v2_cycle_parity_declarative",
        process_instance_id="unit-host:123",
    )

    assert evidence["parity_complete"] is False
    assert evidence["status"] == "FULL_FUNCTION_PARITY_BLOCKED"
    assert (
        "DECLARATIVE_PARITY_MATRIX_LACKS_EXACT_SOURCE_AND_EXECUTED_TEST_ATTESTATIONS"
        in evidence["revalidation_rejection_reasons"]
    )


def test_exact_source_and_executed_contract_receipt_can_verify_parity(
    tmp_path: Path,
) -> None:
    _write_parity_fixture(root=tmp_path, exact=True)

    evidence = build_current_cycle_parity_attestation(
        repo_root=tmp_path,
        cycle_id="v2_cycle_parity_exact",
        process_instance_id="unit-host:123",
        generated_utc="2026-07-18T12:01:00Z",
    )

    assert evidence["parity_complete"] is True
    assert evidence["status"] == "FULL_FUNCTION_PARITY_VERIFIED"
    assert evidence["revalidation_rejection_reasons"] == []
    assert (
        evidence["parity_evidence_class"]
        == "EXACT_SOURCE_AND_EXECUTED_CONTRACT_TEST_ATTESTATION"
    )


def test_executed_contract_receipt_cannot_be_reused_by_another_cycle(
    tmp_path: Path,
) -> None:
    _write_parity_fixture(
        root=tmp_path,
        exact=True,
        receipt_cycle_id="v2_cycle_stale_receipt",
    )

    evidence = build_current_cycle_parity_attestation(
        repo_root=tmp_path,
        cycle_id="v2_cycle_current_receipt",
        process_instance_id="unit-host:123",
        generated_utc="2026-07-18T12:01:00Z",
    )

    assert evidence["parity_complete"] is False
    assert any(
        reason.startswith("EXACT_PARITY_EXECUTED_CONTRACT_ATTESTATION_INVALID")
        for reason in evidence["revalidation_rejection_reasons"]
    )


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.status_writes = 0
        self.fail_final_status = False
        self.corrupt_readback_key: str | None = None

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        del ex
        if nx and key in self.store:
            return False
        if key == REDIS_STATUS_KEY:
            self.status_writes += 1
            if self.fail_final_status and self.status_writes == 2:
                return False
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        raw = self.store.get(key)
        if raw is not None and key == self.corrupt_readback_key:
            payload = json.loads(raw)
            payload["corrupted_after_write"] = True
            return json.dumps(payload)
        return raw


def test_current_cycle_key_requires_ttl_ack_and_exact_readback() -> None:
    key = "v2:prediction:BTCUSDT:1m"
    payload = {
        "cycle_id": "v2_cycle_key_test",
        "process_instance_id": "unit-host:123",
        "candidate_policy_fingerprint": "c" * 64,
    }
    redis = _Redis()

    no_ttl = V2HybridPredictionPublisher(
        io=V2OnlyJsonIO(client=redis)
    )._publish_current_cycle_json(key=key, payload=payload)
    redis.corrupt_readback_key = key
    corrupt_readback = V2HybridPredictionPublisher(
        io=V2OnlyJsonIO(client=redis),
        current_cycle_publication_ttl_seconds=30,
    )._publish_current_cycle_json(key=key, payload=payload)

    assert no_ttl["publication_complete"] is False
    assert no_ttl["rejection_reason"] == "CURRENT_CYCLE_TTL_REQUIRED"
    assert corrupt_readback["acknowledged"] is True
    assert corrupt_readback["readback_verified"] is False
    assert corrupt_readback["publication_complete"] is False


def test_failed_final_status_ack_leaves_expiring_blocked_staging_truth() -> None:
    redis = _Redis()
    redis.fail_final_status = True
    instance_id = process_instance_id()
    status = {
        "cycle_id": "v2_cycle_status_fail_closed",
        "process_instance_id": instance_id,
        "current_cycle_learning_envelope": {
            "cycle_id": "v2_cycle_status_fail_closed",
            "process_instance_id": instance_id,
            "checkpoint_id": "checkpoint-status-test",
            "candidate_policy_fingerprint": "d" * 64,
        },
        "runtime_readiness_status": "READY",
        "trainer_learning_ready": True,
    }
    publisher = V2HybridPredictionPublisher(io=V2OnlyJsonIO(client=redis))

    result = publisher.publish_status(
        status=status,
        metrics={"unit": True},
        expected_cycle_cadence_seconds=10,
    )
    persisted = json.loads(redis.store[REDIS_STATUS_KEY])

    assert result["publication_complete"] is False
    assert status["current_cycle_heartbeat_evidence"]["process_id"] == os.getpid()
    assert status["runtime_readiness_status"] == "BLOCKED"
    assert persisted["runtime_readiness_status"] == "BLOCKED"
    assert persisted["trainer_learning_ready"] is False
    assert "current_cycle_learning_envelope" not in persisted
    assert "FINAL_STATUS_TTL_ACK_PENDING" in persisted[
        "runtime_readiness_blockers"
    ]
