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
            "status": "PASS_AUTHORITATIVE_PAPER_POLICY",
            "generated_utc": generated,
            "directional_authorized_count": 5,
            "flat_authorized_count": 2,
            "source_candidate_count": 7,
            "checkpoint_generation": 3,
            "checkpoint_id": "checkpoint-3",
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
        supervisor.CANDIDATE_OUTCOMES_STATUS_KEY: {
            "schema_version": "candidate_outcome_publisher_runtime_v2",
            "status": "PASS",
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
                "status": "PASS",
                "matured_revision_count": 500,
                "eligible_matured_label_coverage": 1.0,
                "unexplained_maturation_drops": 0,
                "paper_only": True,
                "live_gate": "blocked_human_only",
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            },
            "candidate_outcome_maturer_runtime_integrated": True,
        },
        runtime.PERFORMANCE_STATUS_KEY: {
            "schema_version": "paper_performance_governor_status_v2",
            "status": "HALTED_PERFORMANCE",
            "state": "HALTED_PERFORMANCE",
            "enabled": True,
            "new_entries_allowed": False,
            "allow_feedback_recording": True,
            "generated_utc": generated,
            "closed_outcome_count": 24,
            "governed_closed_rows": 24,
            "notional_weighted_expectancy_bps": -7.25,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
        runtime.ACTIVE_REGISTRY_KEY: {
            "schema_version": "model_registry_active_v2",
            "lane": "paper",
            "registry_generation": 3,
            "checkpoint_id": "checkpoint-3",
            "checkpoint_bundle_sha256": "a" * 64,
            "activated_at": "2026-07-27T12:00:00Z",
            "paper_only": True,
            "live_eligible": False,
        },
    }


def test_authenticate_runtime_inputs_binds_negative_edge() -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    authority, outcomes, performance, registry = runtime.authenticate_runtime_inputs(
        _Redis(_runtime_values(now)),
        now=now,
        max_age_seconds=60,
    )

    assert authority["live_gate"] == "blocked_human_only"
    assert outcomes["archive"]["matured_revision_count"] == 500
    assert performance["notional_weighted_expectancy_bps"] == -7.25
    assert len(performance["source_payload_sha256"]) == 64
    assert registry["registry_generation"] == 3


@pytest.mark.parametrize(
    ("target_key", "mutator", "reason"),
    [
        (
            supervisor.POLICY_AUTHORITY_STATUS_KEY,
            lambda row: row.update(status="FAIL"),
            "STATUS_INVALID",
        ),
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
            supervisor.CANDIDATE_OUTCOMES_STATUS_KEY,
            lambda row: row["maturation"].update(routes_to_live=True),
            "UNSAFE_AUTHORITY",
        ),
        (
            supervisor.CANDIDATE_OUTCOMES_STATUS_KEY,
            lambda row: row["archive"].update(live_gate="live_enabled"),
            "UNSAFE_AUTHORITY",
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
        (
            runtime.PERFORMANCE_STATUS_KEY,
            lambda row: row.update(live_gate="live_enabled"),
            "UNSAFE_AUTHORITY",
        ),
        (
            runtime.PERFORMANCE_STATUS_KEY,
            lambda row: row.update(
                notional_weighted_expectancy_bps=1.0,
                status="FAILED_INTERNAL",
                state="FAILED_INTERNAL",
                enabled=False,
                new_entries_allowed=True,
                allow_feedback_recording=False,
            ),
            "STATE_INCOHERENT",
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


def test_runtime_configuration_rejects_nan_freshness_limit() -> None:
    with pytest.raises(
        runtime.AdaptiveEscalationRuntimeError,
        match="max_status_age_seconds:POSITIVE_FINITE_REQUIRED",
    ):
        runtime._validate_runtime_configuration(  # noqa: SLF001
            max_status_age_seconds=float("nan"),
            min_new_matured_outcomes=250,
            min_new_effective_n=25.0,
            build_timeout_seconds=900,
            dispatch_timeout_seconds=3600,
        )


def test_failure_cycle_rejects_old_or_unrelated_legacy_receipts(tmp_path: Path) -> None:
    authority = {"checkpoint_generation": 4, "checkpoint_id": "checkpoint-4"}
    registry = {
        "registry_generation": 4,
        "checkpoint_id": "checkpoint-4",
        "checkpoint_bundle_sha256": "f" * 64,
        "activated_at": "2026-07-28T16:30:00Z",
    }
    cycle = runtime._failure_cycle(  # noqa: SLF001
        authority,
        registry,
        edge_bps=-1.0,
        performance_sha256="9" * 64,
    )
    release = _release(tmp_path)
    unrelated = runtime.CompletedDispatch(
        runtime.INCREMENTAL_STEP,
        release,
        {
            "trigger": ["admission_starved"],
            "completed_utc": "2026-07-28T16:31:00Z",
        },
    )
    old_negative = runtime.CompletedDispatch(
        runtime.INCREMENTAL_STEP,
        release,
        {
            "trigger": ["negative_after_cost_edge"],
            "completed_utc": "2026-07-27T12:00:00Z",
        },
    )
    bound = runtime.CompletedDispatch(
        runtime.INCREMENTAL_STEP,
        release,
        {"failure_cycle_id": cycle["failure_cycle_id"]},
    )

    assert runtime._dispatch_matches_failure_cycle(unrelated, cycle) is False  # noqa: SLF001
    assert runtime._dispatch_matches_failure_cycle(old_negative, cycle) is False  # noqa: SLF001
    assert runtime._dispatch_matches_failure_cycle(bound, cycle) is True  # noqa: SLF001


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


def _release(
    tmp_path: Path,
    *,
    name: str = "release",
    sha_character: str = "a",
    matured: int = 500,
    decisions: int = 700,
) -> runtime.ReleaseEvidence:
    root = (tmp_path / name).resolve()
    root.mkdir()
    projection = {
        "root": str(root),
        "paths": {
            "dataset": str(root / "dataset.json"),
            "manifest": str(root / "manifest.json"),
            "parity": str(root / "parity.json"),
            "build_receipt": str(root / "receipt.json"),
        },
        "dataset_sha256": sha_character * 64,
        "manifest_sha256": "b" * 64,
        "parity_sha256": "c" * 64,
        "build_receipt_file_sha256": "d" * 64,
        "source_terminal_chain_sha256": "e" * 64,
        "training_rows": 100,
        "validation_rows": 20,
        "holdout_rows": 20,
    }
    return runtime.ReleaseEvidence(root, projection, matured, decisions, "e" * 64)


def _self_hashed_state(**updates) -> dict:
    value = {
        "schema_version": runtime.SCHEMA_VERSION,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "failure_cycle": {
            "active": True,
            "classification": "UNRESOLVED_NEGATIVE_AFTER_COST_EDGE",
            "failure_cycle_id": "adaptive_failure_cycle_" + "1" * 32,
            "started_utc": "2026-07-28T14:00:00Z",
            "last_negative_edge_bps": -7.25,
        },
        "completed_steps_for_failure_cycle": [],
    }
    value.update(updates)
    value["payload_sha256"] = hashlib.sha256(
        runtime._canonical_bytes(value)  # noqa: SLF001
    ).hexdigest()
    return value


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

    receipt["failure_reason"] = "CONTRADICTORY_SUCCESS_FAILURE"
    (run_root / "dispatch_terminal_v1.json").write_text(json.dumps(receipt))
    assert runtime.discover_completed_steps(
        release, dispatch_root=dispatch_root
    ) == frozenset()
    receipt.pop("failure_reason")
    (run_root / "dispatch_terminal_v1.json").write_text(json.dumps(receipt))

    (run_root / "stdout.bin").write_bytes(b"tampered")
    assert runtime.discover_completed_steps(
        release, dispatch_root=dispatch_root
    ) == frozenset()

    (run_root / "stdout.bin").write_bytes(stdout)
    receipt["dataset_release"] = {**release.projection, "dataset_sha256": "0" * 64}
    receipt["input_manifest_sha"] = "0" * 64
    (run_root / "dispatch_terminal_v1.json").write_text(json.dumps(receipt))
    assert runtime.discover_completed_steps(
        release, dispatch_root=dispatch_root
    ) == frozenset()


def test_rebuilt_release_must_cover_triggering_maturity_watermark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _release(tmp_path, name="release_previous", matured=500, decisions=700)
    behind = _release(
        tmp_path,
        name="release_behind",
        sha_character="f",
        matured=749,
        decisions=900,
    )
    monkeypatch.setattr(runtime, "select_latest_release", lambda parent: previous)
    monkeypatch.setattr(runtime, "build_signed_release", lambda *args, **kwargs: behind)

    with pytest.raises(
        runtime.AdaptiveEscalationRuntimeError,
        match="REBUILT_SOURCE_WATERMARK_BEHIND_TRIGGER",
    ):
        runtime.resolve_release(
            tmp_path,
            current_matured_revision_count=750,
            feature_archive_root=tmp_path / "features",
            min_new_matured_outcomes=250,
            build_timeout_seconds=900,
        )
def test_run_once_advances_from_incremental_receipt_to_representation_rebuild(
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
            {
                **_runtime_values(now)[runtime.ACTIVE_REGISTRY_KEY],
                "source_payload_sha256": "8" * 64,
            },
        ),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_release",
        lambda *args, **kwargs: (release, False, release),
    )
    monkeypatch.setattr(
        runtime,
        "discover_historical_completed_dispatches",
        lambda *args, **kwargs: (
            runtime.CompletedDispatch(
                runtime.INCREMENTAL_STEP,
                release,
                {
                    "dispatch_id": "adaptive_dispatch_incremental",
                    "completed_utc": "2026-07-28T15:00:00Z",
                    "trigger": ["negative_after_cost_edge"],
                },
            ),
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
    assert payload["selected_step"] == "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION"
    assert payload["runtime_input_evidence"]["after_cost_edge_bps"] == -7.25
    assert payload["paper_only"] is True
    assert payload["exchange_action_taken"] is False


def _patch_run_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    release: runtime.ReleaseEvidence,
    previous_release: runtime.ReleaseEvidence,
    rebuilt: bool,
    effective_n: float,
    historical_steps: tuple[tuple[str, runtime.ReleaseEvidence], ...] = (),
) -> None:
    values = _runtime_values(now)
    monkeypatch.setattr(
        runtime,
        "authenticate_runtime_inputs",
        lambda *args, **kwargs: (
            values[supervisor.POLICY_AUTHORITY_STATUS_KEY],
            values[supervisor.CANDIDATE_OUTCOMES_STATUS_KEY],
            {
                **values[runtime.PERFORMANCE_STATUS_KEY],
                "source_payload_sha256": "9" * 64,
            },
            {
                **values[runtime.ACTIVE_REGISTRY_KEY],
                "source_payload_sha256": "8" * 64,
            },
        ),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_release",
        lambda *args, **kwargs: (release, rebuilt, previous_release),
    )
    monkeypatch.setattr(
        runtime,
        "discover_historical_completed_dispatches",
        lambda *args, **kwargs: tuple(
            runtime.CompletedDispatch(
                step,
                step_release,
                {
                    "dispatch_id": f"adaptive_dispatch_{index}",
                    "completed_utc": "2026-07-28T15:00:00Z",
                    "trigger": ["negative_after_cost_edge"],
                },
            )
            for index, (step, step_release) in enumerate(historical_steps)
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
            effective_n=effective_n,
            input_manifest_sha=release.projection["dataset_sha256"],
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "load_gen5_corpus_effective_n",
        lambda path: (
            (30.0, 140)
            if Path(path) == Path(previous_release.projection["paths"]["dataset"])
            else (effective_n, 200)
        ),
    )
    monkeypatch.setattr(runtime, "_persist_state", lambda *args, **kwargs: None)


@pytest.mark.parametrize("dispatch_succeeded", [False, True])
def test_new_release_retries_incremental_and_advances_baseline_only_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dispatch_succeeded: bool,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    previous = _release(tmp_path, name="release_old", matured=250, decisions=400)
    current = _release(
        tmp_path,
        name="release_new",
        sha_character="f",
        matured=500,
        decisions=700,
    )
    prior = _self_hashed_state(
        input_manifest_sha=previous.projection["dataset_sha256"],
        completed_steps_for_failure_cycle=[
            "RECALIBRATE_CURRENT_MODELS",
            "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES",
            "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES",
            "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION",
        ],
        launch_baseline={
            "matured_outcome_count": 250,
            "effective_n": 30.0,
            "dataset_sha256": previous.projection["dataset_sha256"],
            "source_terminal_chain_sha256": previous.source_terminal_chain_sha256,
        },
    )
    values = _runtime_values(now)
    values[supervisor.STATUS_REDIS_KEY] = prior
    client = _Redis(values)
    _patch_run_inputs(
        monkeypatch,
        now=now,
        release=current,
        previous_release=previous,
        rebuilt=True,
        effective_n=55.0,
        historical_steps=(
            (runtime.RECALIBRATION_STEP, previous),
            (runtime.INCREMENTAL_STEP, previous),
            ("ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES", previous),
            ("INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION", previous),
        ),
    )
    monkeypatch.setattr(
        supervisor,
        "dispatch_worker",
        lambda *args, **kwargs: {
            "launch_baseline_success": dispatch_succeeded,
            "dispatch_id": "adaptive_dispatch_test",
        },
    )

    payload = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=True,
        now=now,
    )

    assert payload["selected_step"] == runtime.INCREMENTAL_STEP
    if dispatch_succeeded:
        assert payload["launch_baseline"]["matured_outcome_count"] == 500
        assert payload["launch_baseline"]["effective_n"] == 55.0
        assert runtime.INCREMENTAL_STEP in payload["completed_steps_for_failure_cycle"]
    else:
        assert payload["launch_baseline"]["matured_outcome_count"] == 250
        assert payload["launch_baseline"]["effective_n"] == 30.0
        assert runtime.INCREMENTAL_STEP not in payload["completed_steps_for_failure_cycle"]
        client.set(supervisor.STATUS_REDIS_KEY, json.dumps(payload))
        retry = runtime.run_once(
            client,
            release_parent=tmp_path,
            state_path=tmp_path / "state.json",
            dispatch_root=tmp_path / "dispatches",
            execute_worker=False,
            now=now,
        )
        assert retry["selected_step"] == runtime.INCREMENTAL_STEP
        assert retry["launch_baseline"]["matured_outcome_count"] == 250


def test_bounded_multi_dispatch_advances_past_incremental_on_one_frozen_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    previous = _release(tmp_path, name="release_old", matured=250, decisions=400)
    current = _release(
        tmp_path,
        name="release_new",
        sha_character="f",
        matured=500,
        decisions=700,
    )
    values = _runtime_values(now)
    client = _Redis(values)
    _patch_run_inputs(
        monkeypatch,
        now=now,
        release=current,
        previous_release=previous,
        rebuilt=True,
        effective_n=55.0,
        historical_steps=(
            (runtime.RECALIBRATION_STEP, previous),
            (runtime.INCREMENTAL_STEP, previous),
            ("ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES", previous),
            ("INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION", previous),
        ),
    )
    dispatched: list[str] = []

    def dispatch(plan, **_kwargs):
        dispatched.append(str(plan.selected_step))
        return {
            "launch_baseline_success": True,
            "dispatch_id": f"adaptive_dispatch_{len(dispatched)}",
            "selected_step": plan.selected_step,
        }

    monkeypatch.setattr(supervisor, "dispatch_worker", dispatch)

    payload = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=True,
        max_dispatches_per_run=4,
        now=now,
    )

    assert dispatched == [
        runtime.INCREMENTAL_STEP,
        "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS",
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS",
    ]
    assert payload["executed_steps_this_run"] == dispatched
    assert len(payload["dispatch_results"]) == 4
    assert payload["dispatch_limit_reached"] is True
    assert payload["continuation_plan"]["selected_step"] == (
        "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES"
    )
    assert payload["selected_step"] == dispatched[-1]
    assert payload["launch_baseline"]["matured_outcome_count"] == 500
    assert payload["completed_steps_for_input_manifest"] == [
        runtime.RECALIBRATION_STEP,
        runtime.INCREMENTAL_STEP,
        "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
        "TRAIN_HORIZON_SPECIFIC_CHALLENGERS",
        "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS",
    ]


def test_multi_dispatch_stops_at_first_failed_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    release = _release(tmp_path, matured=500, decisions=700)
    client = _Redis(_runtime_values(now))
    _patch_run_inputs(
        monkeypatch,
        now=now,
        release=release,
        previous_release=release,
        rebuilt=False,
        effective_n=55.0,
    )
    dispatched: list[str] = []

    def dispatch(plan, **_kwargs):
        dispatched.append(str(plan.selected_step))
        return {
            "launch_baseline_success": len(dispatched) == 1,
            "dispatch_id": f"adaptive_dispatch_{len(dispatched)}",
            "selected_step": plan.selected_step,
        }

    monkeypatch.setattr(supervisor, "dispatch_worker", dispatch)

    payload = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=True,
        max_dispatches_per_run=4,
        now=now,
    )

    assert dispatched == [
        runtime.RECALIBRATION_STEP,
        "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
    ]
    assert payload["dispatch_results"][-1]["launch_baseline_success"] is False
    assert payload["selected_step"] == dispatched[-1]
    assert dispatched[-1] not in payload["completed_steps_for_failure_cycle"]


@pytest.mark.parametrize("limit", [0, len(supervisor.LADDER) + 1])
def test_multi_dispatch_limit_fails_closed(limit: int) -> None:
    with pytest.raises(runtime.AdaptiveEscalationRuntimeError):
        runtime._validate_runtime_configuration(  # noqa: SLF001
            max_status_age_seconds=600.0,
            min_new_matured_outcomes=250,
            min_new_effective_n=25.0,
            build_timeout_seconds=900,
            dispatch_timeout_seconds=3600,
            max_dispatches_per_run=limit,
        )


def test_plan_only_and_non_information_success_preserve_training_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    release = _release(tmp_path, matured=500, decisions=700)
    completed = list(supervisor.LADDER[:6])
    prior = _self_hashed_state(
        input_manifest_sha=release.projection["dataset_sha256"],
        completed_steps_for_failure_cycle=completed,
        launch_baseline={
            "matured_outcome_count": 500,
            "effective_n": 30.0,
            "dataset_sha256": release.projection["dataset_sha256"],
            "source_terminal_chain_sha256": release.source_terminal_chain_sha256,
        },
    )
    values = _runtime_values(now)
    values[supervisor.STATUS_REDIS_KEY] = prior
    client = _Redis(values)
    _patch_run_inputs(
        monkeypatch,
        now=now,
        release=release,
        previous_release=release,
        rebuilt=False,
        effective_n=30.0,
        historical_steps=tuple((step, release) for step in completed),
    )

    planned = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=False,
        now=now,
    )
    assert planned["selected_step"] == "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES"
    assert planned["launch_baseline"]["matured_outcome_count"] == 500

    monkeypatch.setattr(
        supervisor,
        "dispatch_worker",
        lambda *args, **kwargs: {
            "launch_baseline_success": True,
            "dispatch_id": "adaptive_dispatch_strategy",
        },
    )
    executed = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=True,
        now=now,
    )
    assert executed["launch_baseline"] == planned["launch_baseline"]


def test_forgeable_prior_state_cannot_claim_completed_rungs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 28, 15, 40, tzinfo=UTC)
    release = _release(tmp_path, matured=500, decisions=700)
    forged = _self_hashed_state(
        input_manifest_sha=release.projection["dataset_sha256"],
        completed_steps_for_failure_cycle=list(supervisor.LADDER),
        completed_steps_for_input_manifest=list(supervisor.LADDER),
        launch_baseline={
            "matured_outcome_count": 999999,
            "effective_n": 999999.0,
        },
    )
    values = _runtime_values(now)
    values[supervisor.STATUS_REDIS_KEY] = forged
    client = _Redis(values)
    _patch_run_inputs(
        monkeypatch,
        now=now,
        release=release,
        previous_release=release,
        rebuilt=False,
        effective_n=30.0,
        historical_steps=(),
    )

    payload = runtime.run_once(
        client,
        release_parent=tmp_path,
        state_path=tmp_path / "state.json",
        dispatch_root=tmp_path / "dispatches",
        execute_worker=False,
        now=now,
    )

    assert payload["selected_step"] == runtime.RECALIBRATION_STEP
    assert payload["completed_steps_for_failure_cycle"] == []
    assert payload["launch_baseline"]["matured_outcome_count"] == 500
    assert payload["prior_runtime_state_advisory_only"] is True
