from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_adaptive_escalation_runtime as runtime
from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor
from v2.backend.app.services.adaptive_system.escalation_supervisor_v2 import (
    SupervisorInputs,
)


class _Redis:
    def __init__(self, values: dict[str, dict]) -> None:
        self.values = {key: json.dumps(value) for key, value in values.items()}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        return True


def _runtime_values(now: datetime) -> dict[str, dict]:
    generated = now.isoformat().replace("+00:00", "Z")
    return {
        supervisor.POLICY_AUTHORITY_STATUS_KEY: {
            "schema_version": "adaptive_paper_policy_runtime_status_v2",
            "generated_utc": generated,
            "directional_authorized_count": 5,
            "flat_authorized_count": 2,
            "source_candidate_count": 7,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
        supervisor.CANDIDATE_OUTCOMES_STATUS_KEY: {
            "schema_version": "candidate_outcome_publisher_runtime_v2",
            "generated_at": generated,
            "candidate_recording_coverage": 1.0,
            "unexplained_candidate_drops": 0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "archive": {
                "verified": True,
                "matured_revision_count": 500,
                "decision_revision_count": 700,
                "invalid_row_count": 0,
                "duplicate_archive_record_count": 0,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            },
            "maturation": {
                "matured_revision_count": 500,
                "eligible_matured_label_coverage": 1.0,
                "unexplained_maturation_drops": 0,
            },
        },
        runtime.PERFORMANCE_STATUS_KEY: {
            "schema_version": "paper_performance_governor_status_v2",
            "generated_utc": generated,
            "closed_outcome_count": 24,
            "governed_closed_rows": 24,
            "notional_weighted_expectancy_bps": -7.25,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
    }


def test_authenticate_runtime_inputs_binds_negative_edge() -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    authority, outcomes, performance = runtime.authenticate_runtime_inputs(
        _Redis(_runtime_values(now)),
        now=now,
        max_age_seconds=60,
    )

    assert authority["live_gate"] == "blocked_human_only"
    assert outcomes["archive"]["matured_revision_count"] == 500
    assert performance["notional_weighted_expectancy_bps"] == -7.25
    assert len(performance["source_payload_sha256"]) == 64


@pytest.mark.parametrize(
    ("target_key", "mutator", "reason"),
    [
        (
            supervisor.POLICY_AUTHORITY_STATUS_KEY,
            lambda row: row.update(exchange_action_taken=True),
            "UNSAFE_AUTHORITY",
        ),
        (
            supervisor.CANDIDATE_OUTCOMES_STATUS_KEY,
            lambda row: row["archive"].update(invalid_row_count=1),
            "INTEGRITY_INVALID",
        ),
        (
            runtime.PERFORMANCE_STATUS_KEY,
            lambda row: row.update(closed_outcome_count=23),
            "COHERENT_CLOSED_COUNT_REQUIRED",
        ),
        (
            runtime.PERFORMANCE_STATUS_KEY,
            lambda row: row.update(notional_weighted_expectancy_bps=float("nan")),
            "FINITE_EDGE_REQUIRED",
        ),
    ],
)
def test_authenticate_runtime_inputs_fails_closed(
    target_key: str,
    mutator,
    reason: str,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    values = _runtime_values(now)
    mutator(values[target_key])
    with pytest.raises(runtime.AdaptiveEscalationRuntimeError, match=reason):
        runtime.authenticate_runtime_inputs(
            _Redis(values), now=now, max_age_seconds=60
        )


def test_authenticate_runtime_inputs_rejects_stale_status() -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    values = _runtime_values(now)
    values[runtime.PERFORMANCE_STATUS_KEY]["generated_utc"] = (
        now - timedelta(seconds=61)
    ).isoformat().replace("+00:00", "Z")
    with pytest.raises(runtime.AdaptiveEscalationRuntimeError, match="STALE_OR_FUTURE"):
        runtime.authenticate_runtime_inputs(
            _Redis(values), now=now, max_age_seconds=60
        )


def test_prior_state_requires_self_hash_and_no_live_authority(tmp_path: Path) -> None:
    client = _Redis({})
    state_path = tmp_path / "state.json"
    valid = {
        "schema_version": runtime.SCHEMA_VERSION,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "completed_steps_for_input_manifest": ["RECALIBRATE_CURRENT_MODELS"],
    }
    valid["payload_sha256"] = hashlib.sha256(
        runtime._canonical_bytes(valid)  # noqa: SLF001
    ).hexdigest()
    state_path.write_text(json.dumps(valid))

    assert runtime._load_prior_state(client, state_path) == valid  # noqa: SLF001

    tampered = dict(valid)
    tampered["routes_to_live"] = True
    state_path.write_text(json.dumps(tampered))
    assert runtime._load_prior_state(client, state_path) == {}  # noqa: SLF001


def _release(tmp_path: Path) -> runtime.ReleaseEvidence:
    root = (tmp_path / "release").resolve()
    root.mkdir()
    projection = {
        "root": str(root),
        "paths": {
            "dataset": str(root / "dataset.json"),
            "manifest": str(root / "manifest.json"),
            "parity": str(root / "parity.json"),
            "build_receipt": str(root / "receipt.json"),
        },
        "dataset_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "parity_sha256": "c" * 64,
        "build_receipt_file_sha256": "d" * 64,
        "source_terminal_chain_sha256": "e" * 64,
        "training_rows": 100,
        "validation_rows": 20,
        "holdout_rows": 20,
    }
    return runtime.ReleaseEvidence(root, projection, 500, 700, "e" * 64)


def test_discover_completed_steps_authenticates_receipt_and_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(tmp_path)
    dispatch_root = (tmp_path / "dispatches").resolve()
    dispatch_root.mkdir()
    step = "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES"
    worker = supervisor.WORKER_COMMANDS[step]
    monkeypatch.setattr(supervisor, "_worker_code_sha256", lambda value: "f" * 64)
    material = {
        "schema_version": supervisor.DISPATCH_SCHEMA_VERSION,
        "selected_step": step,
        "trigger": ["negative_after_cost_edge"],
        "input_manifest_sha": release.projection["dataset_sha256"],
        "worker_scope": worker["scope"],
        "worker_entrypoint": worker["entrypoint"],
        "worker_entrypoint_file_sha256": "f" * 64,
        "worker_argv_template": worker["argv"],
        "dataset_release": release.projection,
    }
    dispatch_id = "adaptive_dispatch_" + hashlib.sha256(
        runtime._canonical_bytes(material)  # noqa: SLF001
    ).hexdigest()[:32]
    run_root = dispatch_root / dispatch_id
    run_root.mkdir()
    stdout = b"ok\n"
    stderr = b""
    (run_root / "stdout.bin").write_bytes(stdout)
    (run_root / "stderr.bin").write_bytes(stderr)
    receipt = {
        **material,
        "dispatch_id": dispatch_id,
        "argv": supervisor._resolved_worker_argv(  # noqa: SLF001
            worker,
            dataset_release_root=release.root,
            dispatch_run_root=run_root,
        ),
        "status": "COMPLETED",
        "returncode": 0,
        "timed_out": False,
        "launch_baseline_success": True,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    (run_root / "dispatch_terminal_v1.json").write_text(json.dumps(receipt))

    completed = runtime.discover_completed_steps(
        release, dispatch_root=dispatch_root
    )

    assert step in completed
    assert "RECALIBRATE_CURRENT_MODELS" in completed

    (run_root / "stdout.bin").write_bytes(b"tampered")
    assert runtime.discover_completed_steps(
        release, dispatch_root=dispatch_root
    ) == frozenset()


def test_run_once_advances_from_incremental_receipt_to_strategy_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    client = _Redis(_runtime_values(now))
    release = _release(tmp_path)
    monkeypatch.setattr(
        runtime,
        "authenticate_runtime_inputs",
        lambda *args, **kwargs: (
            _runtime_values(now)[supervisor.POLICY_AUTHORITY_STATUS_KEY],
            _runtime_values(now)[supervisor.CANDIDATE_OUTCOMES_STATUS_KEY],
            {
                **_runtime_values(now)[runtime.PERFORMANCE_STATUS_KEY],
                "source_payload_sha256": "9" * 64,
            },
        ),
    )
    monkeypatch.setattr(runtime, "resolve_release", lambda *args, **kwargs: (release, False))
    monkeypatch.setattr(
        runtime,
        "discover_completed_steps",
        lambda *args, **kwargs: frozenset(
            {
                "RECALIBRATE_CURRENT_MODELS",
                "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES",
            }
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "build_inputs_from_redis",
        lambda *args, **kwargs: SupervisorInputs(
            directional_authorized_count=5,
            flat_authorized_count=2,
            candidate_count=7,
            persistent_flat_cycles=0,
            matured_outcome_count=500,
            effective_n=30.0,
            input_manifest_sha="a" * 64,
        ),
    )
    monkeypatch.setattr(supervisor, "load_gen5_corpus_effective_n", lambda path: (30.0, 140))
    monkeypatch.setattr(runtime, "_persist_state", lambda *args, **kwargs: None)

    payload = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=False,
        now=now,
    )

    assert payload["action"] == supervisor.ACTION_LAUNCH
    assert payload["selected_step"] == "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES"
    assert payload["runtime_input_evidence"]["after_cost_edge_bps"] == -7.25
    assert payload["paper_only"] is True
    assert payload["exchange_action_taken"] is False
