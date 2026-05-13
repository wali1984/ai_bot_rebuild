from __future__ import annotations

import json

import pytest

from v2.backend.app.runtime_contracts.worker_status import (
    V2WorkerStatus,
    WorkerMigrationStatus,
    example_payload,
    ready_blockers,
    validate_required_fields,
    write_json_payload,
)


def test_running_worker_requires_command_payload_and_test(tmp_path) -> None:
    with pytest.raises(ValueError):
        V2WorkerStatus(
            worker_id="risk_gateway_worker",
            category="risk_gateway_worker",
            purpose="risk",
            status=WorkerMigrationStatus.MIGRATED_AND_RUNNING,
            generated_at="2026-05-13T00:00:00Z",
            freshness_seconds=0,
            source_paths=("v2/backend/app/composition/risk_gateway/runtime.py",),
            evidence_status="EVIDENCE_PRESENT",
            legacy_dependency_mode="none",
            runtime_pid=123,
            runnable_command=None,
            public_payload_path=None,
            test_status="missing",
            codex_status="reviewed",
            next_action="none",
        )


def test_backlog_only_is_not_migration() -> None:
    status = V2WorkerStatus(
        worker_id="trainer_bridge",
        category="trainer_bridge",
        purpose="trainer migration",
        status=WorkerMigrationStatus.BACKLOG_ONLY,
        generated_at="2026-05-13T00:00:00Z",
        freshness_seconds=0,
        source_paths=("legacy_module:trainer",),
        evidence_status="EVIDENCE_MISSING",
        legacy_dependency_mode="none",
        test_status="missing",
        codex_status="classified",
        blockers=("backlog_item_only_not_migrated",),
        next_action="port worker",
    ).to_dict()

    assert status["is_migration"] is False
    assert status["status_meaning"] == "migration backlog item only; not migrated"


def test_readonly_wrapper_is_not_independent_runtime() -> None:
    status = V2WorkerStatus(
        worker_id="coinank_bridge",
        category="coinank_bridge",
        purpose="readonly bridge",
        status=WorkerMigrationStatus.WRAPPED_READONLY_ONLY,
        generated_at="2026-05-13T00:00:00Z",
        freshness_seconds=0,
        source_paths=("legacy_reference/ingest/live_coinank.py",),
        evidence_status="EVIDENCE_PRESENT",
        legacy_dependency_mode="readonly_wrapper",
        test_status="present",
        codex_status="classified",
        blockers=("readonly_wrapper_not_independent_runtime",),
        next_action="port independent worker",
    ).to_dict()

    assert status["is_independent_runtime"] is False
    assert status["is_migration"] is False


def test_missing_in_v2_is_honest_allowed_status() -> None:
    status = V2WorkerStatus(
        worker_id="live_execution_stub",
        category="live_execution_stub",
        purpose="blocked live stub",
        status=WorkerMigrationStatus.MISSING_IN_V2,
        generated_at="2026-05-13T00:00:00Z",
        freshness_seconds=0,
        source_paths=(),
        evidence_status="EVIDENCE_MISSING",
        legacy_dependency_mode="none",
        test_status="missing",
        codex_status="classified",
        blockers=("missing_v2_worker",),
        next_action="keep live blocked",
    ).to_dict()

    assert validate_required_fields(status) == []
    assert status["status"] == "MISSING_IN_V2"


def test_json_schema_example_payload_writes(tmp_path) -> None:
    payload = example_payload()
    path = tmp_path / "worker_status.json"

    write_json_payload(path, payload)

    loaded = json.loads(path.read_text())
    assert loaded["status"] == "PAPER_ONLY"
    assert ready_blockers(loaded) == []
