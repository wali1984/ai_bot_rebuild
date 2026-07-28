"""Unit tests for the operational escalation supervisor (FINAL PASS item #2).

Core guarantee under test: a persistent FLAT policy output NEVER means "wait for
data".  It either LAUNCHES a real tracked worker, or — only when every
controllable lever is exhausted — AWAITS on an EXACT numeric threshold (never a
passive wait).  Escalation is never terminal.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor
from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import (
    LADDER,
    PROHIBITED_TERMINAL_RESPONSES,
)
from v2.backend.app.services.adaptive_system.escalation_supervisor_v2 import (
    ACTION_AWAIT,
    ACTION_LAUNCH,
    ACTION_NO_ESCALATION,
    PASSIVE_WAIT_MARKERS,
    WORKER_COMMANDS,
    EscalationWorkPlan,
    SupervisorInputs,
    derive_conditions,
    kish_effective_n,
    plan_escalation,
)

RECALIBRATE = "RECALIBRATE_CURRENT_MODELS"
TRAIN_INCREMENTAL = "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES"
ALT_STRATEGY = "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES"
EXPLORE = "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION"
PROMOTE = "PROMOTE_SUPERIOR_CHALLENGER"


def _flat_inputs(**over) -> SupervisorInputs:
    """A persistently-FLAT state (directional=0 over the window, candidates present)."""
    base = dict(
        directional_authorized_count=0,
        flat_authorized_count=6,
        candidate_count=16,
        persistent_flat_cycles=5,
        min_persistent_flat_cycles=3,
        matured_outcome_count=3911,
        effective_n=181.0,
        baseline_matured_outcome_count=None,
        baseline_effective_n=None,
        min_new_matured_outcomes=250,
        min_new_effective_n=25.0,
        superior_challenger_available=False,
        input_manifest_sha="deadbeef",
    )
    base.update(over)
    return SupervisorInputs(**base)


# --------------------------------------------------------------------------- #
# Kish effective-N (reused corpus-diversity logic)
# --------------------------------------------------------------------------- #
def test_kish_effective_n_collapses_clustered_rows():
    # 100 rows all at the SAME decision-minute -> effective N == 1.
    same = ["2026-07-27T23:30:11Z"] * 100
    assert kish_effective_n(same) == 1.0
    # fully time-independent rows -> effective N == row count.
    distinct = [f"2026-07-27T23:{m:02d}:00Z" for m in range(30)]
    assert kish_effective_n(distinct) == 30.0
    # empty corpus is an honest zero, never silently non-zero.
    assert kish_effective_n([]) == 0.0


# --------------------------------------------------------------------------- #
# 1) persistent-flat + NEW info -> LAUNCH a real worker
# --------------------------------------------------------------------------- #
def test_persistent_flat_with_new_info_launches_worker():
    inp = _flat_inputs()  # matured=3911 vs null baseline -> new info exists
    assert inp.new_information_exists() is True
    plan = plan_escalation(inp)

    assert plan.action == ACTION_LAUNCH
    assert plan.selected_step in LADDER
    assert plan.worker_command is not None
    # the descriptor points at a real in-repo entrypoint and is paper-only
    assert plan.worker_command["entrypoint"] == WORKER_COMMANDS[plan.selected_step]["entrypoint"]
    assert plan.worker_command["paper_only"] is True
    assert plan.worker_command["routes_to_live"] is False
    assert plan.exact_trigger_condition is None
    assert plan.next_step is not None
    assert plan.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    assert plan.validate() == []


def test_launch_advances_to_training_worker_when_recalibrate_exhausted():
    inp = _flat_inputs(exhausted_steps=frozenset({RECALIBRATE}))
    plan = plan_escalation(inp)
    assert plan.action == ACTION_LAUNCH
    # recalibrate exhausted -> ladder advances to incremental training on new data
    assert plan.selected_step == TRAIN_INCREMENTAL
    assert plan.worker_command["entrypoint"].endswith(
        "train_serving_profitability_v3_checkpoint.py"
    )
    assert plan.validate() == []


# --------------------------------------------------------------------------- #
# 2) persistent-flat + NO new info + cheap levers exhausted -> AWAIT with an
#    EXACT numeric threshold (never a passive wait)
# --------------------------------------------------------------------------- #
def test_persistent_flat_without_new_info_awaits_exact_threshold():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,   # new matured = 0  (< 250)
        effective_n=10.0,
        baseline_effective_n=10.0,            # new effective_N = 0 (< 25)
        superior_challenger_available=False,
        exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
    )
    assert inp.new_information_exists() is False
    plan = plan_escalation(inp)

    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is False
    # EXACT numeric threshold: baseline(100)+250 and baseline(10)+25
    cond = plan.exact_trigger_condition
    assert cond == "matured_outcomes >= 350 OR effective_N >= 35.0"
    assert any(ch.isdigit() for ch in cond)
    assert ">=" in cond
    assert "matured_outcomes" in cond and "effective_N" in cond
    # it still names the worker it will launch once the threshold is met
    assert plan.next_step == TRAIN_INCREMENTAL
    assert plan.selected_step == TRAIN_INCREMENTAL
    assert plan.validate() == []


def test_await_threshold_tracks_the_baseline():
    inp = _flat_inputs(
        matured_outcome_count=500,
        baseline_matured_outcome_count=500,
        effective_n=40.0,
        baseline_effective_n=40.0,
        min_new_matured_outcomes=300,
        min_new_effective_n=50.0,
        exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.exact_trigger_condition == "matured_outcomes >= 800 OR effective_N >= 90.0"


# --------------------------------------------------------------------------- #
# 3) the supervisor NEVER emits a passive wait / prohibited terminal response
# --------------------------------------------------------------------------- #
def test_never_emits_passive_wait_across_states():
    scenarios = [
        _flat_inputs(),  # launch
        _flat_inputs(  # data-gated await
            matured_outcome_count=100,
            baseline_matured_outcome_count=100,
            effective_n=10.0,
            baseline_effective_n=10.0,
            exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
        ),
        _flat_inputs(  # operator-gated await
            matured_outcome_count=100,
            baseline_matured_outcome_count=100,
            effective_n=10.0,
            baseline_effective_n=10.0,
            exhausted_steps=frozenset(LADDER),
            external_blocker="missing_operator_credential",
        ),
        _flat_inputs(directional_authorized_count=5, persistent_flat_cycles=0),  # healthy
    ]
    for inp in scenarios:
        plan = plan_escalation(inp)
        assert plan.validate() == [], f"validation failed: {plan.validate()} for {plan.action}"
        blob = " ".join(
            str(x).lower()
            for x in (
                plan.interpretation,
                plan.exact_trigger_condition or "",
                plan.rationale,
            )
        )
        for marker in PASSIVE_WAIT_MARKERS:
            assert marker not in blob, f"passive-wait marker {marker!r} leaked in {plan.action}"
        for bad in PROHIBITED_TERMINAL_RESPONSES:
            assert bad.lower() not in blob


def test_hand_built_passive_await_fails_validation():
    # A plan that says "wait for more data" must be rejected by validate().
    bad = EscalationWorkPlan(
        trigger=["persistent_flat_without_information_gain"],
        interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
        action=ACTION_AWAIT,
        selected_step=TRAIN_INCREMENTAL,
        next_step=TRAIN_INCREMENTAL,
        worker_command=None,
        exact_trigger_condition="wait for more data",
        input_manifest_sha="x",
        is_operator_gated=False,
        external_blocker=None,
        rationale="x",
        decision=plan_escalation(_flat_inputs()).decision,
    )
    errors = bad.validate()
    assert any("PASSIVE_WAIT_LANGUAGE_EMITTED" in e for e in errors)
    assert any("AWAIT_TRIGGER_NOT_QUANTITATIVE" in e for e in errors)


# --------------------------------------------------------------------------- #
# 4) ladder step advances when a step is exhausted
# --------------------------------------------------------------------------- #
def test_ladder_step_advances_when_step_exhausted():
    inp0 = _flat_inputs()
    step0 = plan_escalation(inp0).selected_step
    assert step0 == LADDER[0]

    inp1 = _flat_inputs(exhausted_steps=frozenset({LADDER[0]}))
    step1 = plan_escalation(inp1).selected_step
    assert step1 == LADDER[1]

    inp2 = _flat_inputs(exhausted_steps=frozenset({LADDER[0], LADDER[1]}))
    step2 = plan_escalation(inp2).selected_step
    assert step2 == LADDER[2]


# --------------------------------------------------------------------------- #
# 5) escalation is never terminal
# --------------------------------------------------------------------------- #
def test_escalation_never_terminal_even_operator_gated():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
        exhausted_steps=frozenset(LADDER),
        external_blocker="missing_operator_credential",
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is True
    # names the exact external resolution — not a market verdict, not a passive wait
    assert plan.exact_trigger_condition == "operator_resolves:missing_operator_credential"
    assert plan.external_blocker == "missing_operator_credential"
    # still forward-pointing: it knows the worker it will launch once unblocked
    assert plan.next_step is not None
    assert plan.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    for bad in PROHIBITED_TERMINAL_RESPONSES:
        assert bad not in plan.interpretation
    assert plan.validate() == []


def test_all_exhausted_no_blocker_still_awaits_with_numeric_threshold():
    # Ladder fully exhausted, no external blocker, no new info -> NOT terminal:
    # a data-gated AWAIT with an exact numeric threshold.
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
        exhausted_steps=frozenset(LADDER),
        external_blocker=None,
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is False
    assert plan.exact_trigger_condition == "matured_outcomes >= 350 OR effective_N >= 35.0"
    assert plan.next_step is not None
    assert plan.validate() == []


# --------------------------------------------------------------------------- #
# Healthy state + condition derivation
# --------------------------------------------------------------------------- #
def test_directional_authorized_is_healthy_not_escalation():
    inp = _flat_inputs(directional_authorized_count=5, persistent_flat_cycles=0)
    plan = plan_escalation(inp)
    assert plan.action == ACTION_NO_ESCALATION
    assert plan.worker_command is None
    assert plan.exact_trigger_condition is None
    assert plan.validate() == []


def test_derive_conditions_flags_admission_starved_and_persistence():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
    )
    cond = derive_conditions(inp)
    assert cond["admission_starved"] is True
    assert cond["persistent_flat_without_information_gain"] is True
    assert cond["corpus_stagnation"] is True
    # with abundant NEW info, "without information gain" is False but admission
    # starvation still triggers escalation (never a passive wait).
    cond2 = derive_conditions(_flat_inputs())
    assert cond2["persistent_flat_without_information_gain"] is False
    assert cond2["admission_starved"] is True


def test_negative_after_cost_edge_triggers():
    inp = _flat_inputs(directional_authorized_count=3, after_cost_edge_bps=-4.2)
    cond = derive_conditions(inp)
    assert cond["negative_after_cost_edge"] is True
    plan = plan_escalation(inp)
    assert plan.action == ACTION_LAUNCH
    assert plan.validate() == []


# --------------------------------------------------------------------------- #
# Operator #2: every ladder rung must launch a REAL worker, never a no-op.
# Guards against a descriptor silently pointing at a deprecated/removed command
# (a "LAUNCH_WORKER" that does nothing is a passive wait in disguise).
_REPO_ROOT = Path(__file__).resolve().parents[6]

# Commands that are deprecated fail-closed no-ops and must NEVER be a worker target.
_DEPRECATED_NOOP_ENTRYPOINTS = frozenset(
    {"v2.backend.app.cli.v2_trainer_fit_confidence_calibration"}
)


def test_no_worker_targets_a_deprecated_noop_command():
    for step, wc in WORKER_COMMANDS.items():
        assert wc["entrypoint"] not in _DEPRECATED_NOOP_ENTRYPOINTS, (
            f"{step} points at deprecated fail-closed no-op {wc['entrypoint']!r}; "
            "a LAUNCH_WORKER that does nothing is a passive wait in disguise"
        )


def test_every_worker_entrypoint_is_a_real_resolvable_target():
    for step, wc in WORKER_COMMANDS.items():
        kind = wc["entrypoint_kind"]
        ep = wc["entrypoint"]
        if kind == "script":
            assert (_REPO_ROOT / ep).is_file(), f"{step}: missing script {ep}"
        elif kind == "module":
            assert importlib.util.find_spec(ep) is not None, (
                f"{step}: unimportable module {ep}"
            )
        else:  # pragma: no cover - descriptor schema guard
            raise AssertionError(f"{step}: unknown entrypoint_kind {kind!r}")
        # every descriptor stays paper-only and never routes to live
        assert wc["paper_only"] is True and wc["routes_to_live"] is False


# --------------------------------------------------------------------------- #
# Dispatch regression: a LAUNCH_WORKER plan executes exactly one authenticated
# serving-profitability-v3 training process.  It never invokes the superseded
# v2 trainer or the legacy H2L mutation path and carries no live authority.
# --------------------------------------------------------------------------- #
_DATASET_FILENAME = "adaptive_serving_compatible_dataset_v2.json"
_MANIFEST_FILENAME = "adaptive_serving_compatible_dataset_manifest_v2.json"
_PARITY_FILENAME = "adaptive_train_serve_feature_parity_report_v2.json"
_BUILD_RECEIPT_FILENAME = "candidate_outcome_dataset_build_receipt_v3.json"


class _FakeRunner:
    def __init__(
        self,
        state_path: Path,
        *,
        returncode: int = 0,
        stdout: str = "trained\n",
        stderr: str = "",
        raises_timeout: bool = False,
    ) -> None:
        self.state_path = state_path
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises_timeout = raises_timeout
        self.calls: list[tuple[list[str], float]] = []
        self.state_at_call: dict | None = None

    def __call__(self, argv, timeout_seconds):  # noqa: ANN001, ANN204
        assert isinstance(argv, list)
        assert all(type(value) is str for value in argv)
        self.calls.append((list(argv), timeout_seconds))
        self.state_at_call = json.loads(self.state_path.read_text(encoding="utf-8"))
        if self.raises_timeout:
            raise subprocess.TimeoutExpired(
                cmd=argv,
                timeout=timeout_seconds,
                output=self.stdout,
                stderr=self.stderr,
            )
        return subprocess.CompletedProcess(
            args=argv,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def _dataset_release(tmp_path: Path) -> Path:
    root = (tmp_path / "dataset-release").resolve()
    root.mkdir()
    for filename in (
        _DATASET_FILENAME,
        _MANIFEST_FILENAME,
        _PARITY_FILENAME,
        _BUILD_RECEIPT_FILENAME,
    ):
        (root / filename).write_text("{}\n", encoding="utf-8")
    return root


def _authenticated_release_projection(release_root: Path) -> dict:
    return {
        "root": str(release_root),
        "paths": {
            "dataset": str(release_root / _DATASET_FILENAME),
            "manifest": str(release_root / _MANIFEST_FILENAME),
            "parity": str(release_root / _PARITY_FILENAME),
            "build_receipt": str(release_root / _BUILD_RECEIPT_FILENAME),
        },
        "dataset_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "parity_sha256": "3" * 64,
        "build_receipt_file_sha256": "4" * 64,
        "source_terminal_chain_sha256": "5" * 64,
        "training_rows": 100,
        "validation_rows": 20,
        "holdout_rows": 20,
    }


class _MemoryRedis:
    def __init__(self, values: dict[str, dict] | None = None) -> None:
        self.values = {
            key: json.dumps(value, sort_keys=True)
            for key, value in (values or {}).items()
        }

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        return True

    def json_value(self, key: str) -> dict:
        return json.loads(self.values[key])


def _runtime_redis(*, champion: dict | None = None) -> _MemoryRedis:
    return _MemoryRedis(
        {
            supervisor.POLICY_AUTHORITY_STATUS_KEY: {
                "directional_authorized_count": 0,
                "flat_authorized_count": 6,
                "source_candidate_count": 16,
            },
            supervisor.CANDIDATE_OUTCOMES_STATUS_KEY: {
                "maturation": {"matured_revision_count": 3911},
            },
            supervisor.CHAMPION_CHALLENGER_STATUS_KEY: champion or {},
        }
    )


def _write_dataset_identity(path: Path, dataset_sha256: str) -> None:
    path.write_text(
        json.dumps(
            {
                "dataset_sha256": dataset_sha256,
                "rows": [{"decision_time": "2026-07-28T00:00:00Z"}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _launch_plan(step: str) -> EscalationWorkPlan:
    exhausted = frozenset() if step == RECALIBRATE else frozenset({RECALIBRATE})
    plan = plan_escalation(_flat_inputs(exhausted_steps=exhausted))
    assert plan.action == ACTION_LAUNCH
    assert plan.selected_step == step
    return plan


def _dispatch(
    plan: EscalationWorkPlan,
    tmp_path: Path,
    runner: _FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    timeout_seconds: int = 17,
) -> tuple[dict, Path, Path, Path]:
    release_root = _dataset_release(tmp_path)
    dispatch_root = (tmp_path / "dispatches").resolve()
    state_path = (tmp_path / "dispatch-state.json").resolve()
    lock_path = (tmp_path / "dispatch.lock").resolve()
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")
    monkeypatch.setattr(
        supervisor,
        "_authenticated_dataset_release",
        lambda root: _authenticated_release_projection(Path(root).resolve()),
    )
    result = supervisor.dispatch_worker(
        plan,
        dataset_release_root=release_root,
        dispatch_root=dispatch_root,
        state_path=state_path,
        lock_path=lock_path,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    return result, release_root, dispatch_root, state_path


def _expected_argv(
    *,
    release_root: Path,
    dispatch_root: Path,
    dispatch_id: str,
) -> list[str]:
    output_root = dispatch_root / dispatch_id
    return [
        ".venv/bin/python",
        "scripts/train_serving_profitability_v3_checkpoint.py",
        "--dataset",
        str(release_root / _DATASET_FILENAME),
        "--manifest",
        str(release_root / _MANIFEST_FILENAME),
        "--parity",
        str(release_root / _PARITY_FILENAME),
        "--build-receipt",
        str(release_root / _BUILD_RECEIPT_FILENAME),
        "--model-dir",
        str(output_root / "models"),
        "--evidence-dir",
        str(output_root / "evidence"),
    ]


@pytest.mark.parametrize("step", [RECALIBRATE, TRAIN_INCREMENTAL])
def test_dispatch_uses_exact_authenticated_v3_training_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> None:
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)
    result, release_root, dispatch_root, _ = _dispatch(
        _launch_plan(step),
        tmp_path,
        runner,
        monkeypatch,
    )
    expected = _expected_argv(
        release_root=release_root,
        dispatch_root=dispatch_root,
        dispatch_id=result["dispatch_id"],
    )

    assert runner.calls == [(expected, 17)]
    assert result["argv"] == expected
    assert result["status"] == "COMPLETED"
    joined = " ".join(expected)
    assert "train_serving_feature_abi_v2_checkpoint.py" not in joined
    assert "v2_trainer_h2l_promote" not in joined
    assert result["paper_only"] is True
    assert result["live_gate"] == "blocked_human_only"
    assert result["routes_to_live"] is False
    assert result["places_real_order"] is False
    assert result["exchange_action_taken"] is False


def test_adaptive_shadow_worker_descriptor_is_bounded_to_one_cycle() -> None:
    argv = WORKER_COMMANDS[EXPLORE]["argv"]
    assert argv[-1] == "--once"
    assert argv.count("--once") == 1


def test_dispatch_writes_running_before_runner_and_hashes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(
        state_path,
        stdout="fixture stdout\n",
        stderr="fixture stderr\n",
    )
    result, _, _, written_state_path = _dispatch(
        _launch_plan(RECALIBRATE),
        tmp_path,
        runner,
        monkeypatch,
    )

    assert runner.state_at_call is not None
    assert runner.state_at_call["status"] == "RUNNING"
    assert runner.state_at_call["dispatch_id"] == result["dispatch_id"]
    assert runner.state_at_call["launch_baseline_success"] is False
    assert result["stdout_sha256"] == hashlib.sha256(b"fixture stdout\n").hexdigest()
    assert result["stderr_sha256"] == hashlib.sha256(b"fixture stderr\n").hexdigest()
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["launch_baseline_success"] is True
    assert stat.S_IMODE(written_state_path.stat().st_mode) == 0o600
    assert list(written_state_path.parent.glob(f".{written_state_path.name}.*.tmp")) == []


def test_completed_dispatch_replay_is_idempotent_and_does_not_execute_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)
    plan = _launch_plan(RECALIBRATE)
    first, release_root, dispatch_root, _ = _dispatch(
        plan,
        tmp_path,
        runner,
        monkeypatch,
    )
    assert len(runner.calls) == 1

    replay_runner = _FakeRunner(state_path, returncode=99)
    replay = supervisor.dispatch_worker(
        plan,
        dataset_release_root=release_root,
        dispatch_root=dispatch_root,
        state_path=state_path,
        lock_path=(tmp_path / "dispatch.lock").resolve(),
        runner=replay_runner,
        timeout_seconds=17,
    )

    assert replay["dispatch_id"] == first["dispatch_id"]
    assert replay["status"] == "COMPLETED"
    assert replay["idempotent_replay"] is True
    assert replay_runner.calls == []
    assert json.loads(state_path.read_text(encoding="utf-8")) == first


def test_dispatch_lock_contention_rejects_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _dataset_release(tmp_path)
    dispatch_root = (tmp_path / "dispatches").resolve()
    state_path = (tmp_path / "dispatch-state.json").resolve()
    lock_path = (tmp_path / "dispatch.lock").resolve()
    lock_path.touch(mode=0o600)
    runner = _FakeRunner(state_path)
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")
    monkeypatch.setattr(
        supervisor,
        "_authenticated_dataset_release",
        lambda root: _authenticated_release_projection(Path(root).resolve()),
    )

    with lock_path.open("r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = supervisor.dispatch_worker(
            _launch_plan(RECALIBRATE),
            dataset_release_root=release_root,
            dispatch_root=dispatch_root,
            state_path=state_path,
            lock_path=lock_path,
            runner=runner,
            timeout_seconds=17,
        )

    assert result["status"] == "FAILED"
    assert result["failure_reason"] == "DISPATCH_LOCK_CONTENDED"
    assert result["launch_baseline_success"] is False
    assert runner.calls == []
    assert not state_path.exists()


def test_dispatch_rejects_unauthenticated_release_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _dataset_release(tmp_path)
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")

    with pytest.raises(ValueError):
        supervisor.dispatch_worker(
            _launch_plan(RECALIBRATE),
            dataset_release_root=release_root,
            dispatch_root=(tmp_path / "dispatches").resolve(),
            state_path=state_path,
            lock_path=(tmp_path / "dispatch.lock").resolve(),
            runner=runner,
            timeout_seconds=17,
        )

    assert runner.calls == []
    assert not state_path.exists()


@pytest.mark.parametrize("live_gate", [None, "open", "BLOCKED_HUMAN_ONLY"])
def test_dispatch_requires_exact_blocked_human_only_live_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_gate: str | None,
) -> None:
    release_root = _dataset_release(tmp_path)
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)
    if live_gate is None:
        monkeypatch.delenv("LIVE_GATE", raising=False)
    else:
        monkeypatch.setenv("LIVE_GATE", live_gate)

    with pytest.raises(ValueError, match="LIVE_GATE_BLOCK_REQUIRED"):
        supervisor.dispatch_worker(
            _launch_plan(RECALIBRATE),
            dataset_release_root=release_root,
            dispatch_root=(tmp_path / "dispatches").resolve(),
            state_path=state_path,
            lock_path=(tmp_path / "dispatch.lock").resolve(),
            runner=runner,
            timeout_seconds=17,
        )

    assert runner.calls == []
    assert not state_path.exists()


@pytest.mark.parametrize(
    ("returncode", "raises_timeout", "expected_stderr"),
    [
        (7, False, "training failed\n"),
        (0, True, "timed out\n"),
    ],
)
def test_failed_or_timed_out_dispatch_is_evidenced_without_baseline_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    raises_timeout: bool,
    expected_stderr: str,
) -> None:
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(
        state_path,
        returncode=returncode,
        stdout="partial stdout\n",
        stderr=expected_stderr,
        raises_timeout=raises_timeout,
    )
    result, _, _, _ = _dispatch(
        _launch_plan(RECALIBRATE),
        tmp_path,
        runner,
        monkeypatch,
    )

    assert result["status"] == "FAILED"
    assert result["timed_out"] is raises_timeout
    assert result["launch_baseline_success"] is False
    assert result["stdout_sha256"] == hashlib.sha256(b"partial stdout\n").hexdigest()
    assert result["stderr_sha256"] == hashlib.sha256(
        expected_stderr.encode("utf-8")
    ).hexdigest()
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("paper_only", False),
        ("live_gate", "open"),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("exchange_action_taken", True),
    ],
)
def test_dispatch_rejects_unsafe_authority_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: object,
) -> None:
    plan = _launch_plan(RECALIBRATE)
    worker = {**plan.worker_command, field: invalid}
    bad_plan = replace(plan, worker_command=worker)
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)

    with pytest.raises(ValueError, match="UNSAFE_DISPATCH_AUTHORITY"):
        _dispatch(bad_plan, tmp_path, runner, monkeypatch)
    assert runner.calls == []


def test_dispatch_argv_is_not_a_shell_or_authority_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = (tmp_path / "dispatch-state.json").resolve()
    runner = _FakeRunner(state_path)
    result, _, _, _ = _dispatch(
        _launch_plan(RECALIBRATE),
        tmp_path,
        runner,
        monkeypatch,
    )

    argv = result["argv"]
    assert type(argv) is list
    assert not any(token in " ".join(argv).lower() for token in (
        "redis",
        "model_registry",
        "exchange",
        "submit_order",
        "place_order",
        "live_gate",
        "systemctl",
    ))
    assert not any(token in argv for token in ("sh", "bash", "-c"))


# --------------------------------------------------------------------------- #
# Durable progress semantics: planning alone never claims completed work.  Only
# a successful dispatch advances the ladder, and that progress is scoped to the
# exact authenticated dataset identity.
# --------------------------------------------------------------------------- #
def test_planned_launch_without_execution_does_not_create_launch_baseline(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "dataset.json"
    _write_dataset_identity(dataset_path, "a" * 64)
    client = _runtime_redis()

    plan = supervisor.run_once(
        client,
        dataset_path=dataset_path,
        ledger_path=tmp_path / "ledger.jsonl",
        execute_worker=False,
    )
    status = client.json_value(supervisor.STATUS_REDIS_KEY)

    assert plan.action == ACTION_LAUNCH
    assert status["worker_execution_enabled"] is False
    assert status["dispatch_result"] is None
    assert status["completed_steps_for_input_manifest"] == []
    assert "launch_baseline" not in status


def test_successful_dispatch_completes_step_once_and_next_cycle_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "dataset.json"
    dataset_sha256 = "a" * 64
    _write_dataset_identity(dataset_path, dataset_sha256)
    client = _runtime_redis()
    successful_dispatch = {
        "dispatch_id": "adaptive_dispatch_fixture",
        "launch_baseline_success": True,
        "dataset_release": {"build_receipt_file_sha256": "b" * 64},
    }
    monkeypatch.setattr(
        supervisor,
        "dispatch_worker",
        lambda *args, **kwargs: dict(successful_dispatch),
    )

    first = supervisor.run_once(
        client,
        dataset_path=dataset_path,
        ledger_path=tmp_path / "ledger.jsonl",
        execute_worker=True,
        dataset_release_root=tmp_path,
    )
    first_status = client.json_value(supervisor.STATUS_REDIS_KEY)

    assert first.selected_step == RECALIBRATE
    assert first_status["input_manifest_sha"] == dataset_sha256
    assert first_status["completed_steps_for_input_manifest"] == [RECALIBRATE]
    assert first_status["completed_steps_for_input_manifest"].count(RECALIBRATE) == 1
    assert first_status["launch_baseline"]["launched_step"] == RECALIBRATE

    restored = supervisor.build_inputs_from_redis(
        client,
        dataset_path=dataset_path,
    )
    assert restored.exhausted_steps == frozenset({RECALIBRATE})

    second = supervisor.run_once(
        client,
        dataset_path=dataset_path,
        ledger_path=tmp_path / "ledger.jsonl",
        execute_worker=False,
    )
    second_status = client.json_value(supervisor.STATUS_REDIS_KEY)

    assert second.action == ACTION_LAUNCH
    assert second.selected_step == ALT_STRATEGY
    assert LADDER.index(second.selected_step) > LADDER.index(RECALIBRATE)
    assert second_status["completed_steps_for_input_manifest"] == [RECALIBRATE]
    assert second_status["launch_baseline"] == first_status["launch_baseline"]


def test_changed_dataset_identity_resets_completed_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "dataset.json"
    _write_dataset_identity(dataset_path, "a" * 64)
    client = _runtime_redis()
    monkeypatch.setattr(
        supervisor,
        "dispatch_worker",
        lambda *args, **kwargs: {
            "dispatch_id": "adaptive_dispatch_fixture",
            "launch_baseline_success": True,
            "dataset_release": {"build_receipt_file_sha256": "b" * 64},
        },
    )
    supervisor.run_once(
        client,
        dataset_path=dataset_path,
        ledger_path=tmp_path / "ledger.jsonl",
        execute_worker=True,
        dataset_release_root=tmp_path,
    )
    assert client.json_value(supervisor.STATUS_REDIS_KEY)[
        "completed_steps_for_input_manifest"
    ] == [RECALIBRATE]

    _write_dataset_identity(dataset_path, "c" * 64)
    refreshed = supervisor.build_inputs_from_redis(client, dataset_path=dataset_path)
    refreshed_plan = plan_escalation(refreshed)

    assert refreshed.input_manifest_sha == "c" * 64
    assert refreshed.exhausted_steps == frozenset()
    assert refreshed_plan.selected_step == RECALIBRATE


@pytest.mark.parametrize(
    ("champion", "expected"),
    [
        ({"best_challenger_id": "challenger"}, False),
        (
            {
                "best_challenger_id": "challenger",
                "best_challenger_superior": False,
                "paper_only": True,
                "live_eligible": False,
            },
            False,
        ),
        (
            {
                "best_challenger_id": "challenger",
                "best_challenger_superior": True,
                "paper_only": False,
                "live_eligible": False,
            },
            False,
        ),
        (
            {
                "best_challenger_id": "challenger",
                "best_challenger_superior": True,
                "paper_only": True,
                "live_eligible": True,
            },
            False,
        ),
        (
            {
                "best_challenger_id": "challenger",
                "best_challenger_superior": True,
                "paper_only": True,
                "live_eligible": False,
            },
            True,
        ),
        (
            {
                "best_challenger_id": "challenger",
                "best_challenger_superior": True,
                "paper_only": True,
            },
            True,
        ),
    ],
)
def test_promotion_requires_explicit_superiority_and_paper_only_authority(
    tmp_path: Path,
    champion: dict,
    expected: bool,
) -> None:
    dataset_path = tmp_path / "dataset.json"
    _write_dataset_identity(dataset_path, "a" * 64)
    inp = supervisor.build_inputs_from_redis(
        _runtime_redis(champion=champion),
        dataset_path=dataset_path,
    )

    assert inp.superior_challenger_available is expected

    promotion_boundary = replace(inp, exhausted_steps=frozenset(LADDER[:-1]))
    plan = plan_escalation(promotion_boundary)
    if expected:
        assert plan.action == ACTION_LAUNCH
        assert plan.selected_step == PROMOTE
    else:
        assert plan.selected_step != PROMOTE


def test_dispatch_identity_binds_entrypoint_bytes_and_argv_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = _dataset_release(tmp_path)
    dispatch_root = (tmp_path / "dispatches").resolve()
    state_path = (tmp_path / "dispatch-state.json").resolve()
    lock_path = (tmp_path / "dispatch.lock").resolve()
    entrypoint = (tmp_path / "worker.py").resolve()
    entrypoint.write_bytes(b"first worker bytes\n")
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")
    monkeypatch.setattr(
        supervisor,
        "_authenticated_dataset_release",
        lambda root: _authenticated_release_projection(Path(root).resolve()),
    )
    base_plan = _launch_plan(RECALIBRATE)
    worker = {
        **base_plan.worker_command,
        "entrypoint": str(entrypoint),
        "entrypoint_kind": "script",
        "argv": [".venv/bin/python", str(entrypoint)],
    }
    plan = replace(base_plan, worker_command=worker)

    first = supervisor.dispatch_worker(
        plan,
        dataset_release_root=release_root,
        dispatch_root=dispatch_root,
        state_path=state_path,
        lock_path=lock_path,
        runner=_FakeRunner(state_path),
        timeout_seconds=17,
    )
    first_sha256 = hashlib.sha256(b"first worker bytes\n").hexdigest()
    assert first["worker_entrypoint_file_sha256"] == first_sha256

    entrypoint.write_bytes(b"second worker bytes\n")
    second = supervisor.dispatch_worker(
        plan,
        dataset_release_root=release_root,
        dispatch_root=dispatch_root,
        state_path=state_path,
        lock_path=lock_path,
        runner=_FakeRunner(state_path),
        timeout_seconds=17,
    )
    second_sha256 = hashlib.sha256(b"second worker bytes\n").hexdigest()
    assert second["worker_entrypoint_file_sha256"] == second_sha256
    assert second["dispatch_id"] != first["dispatch_id"]

    changed_argv = [*worker["argv"], "--variant"]
    third_plan = replace(plan, worker_command={**worker, "argv": changed_argv})
    third = supervisor.dispatch_worker(
        third_plan,
        dataset_release_root=release_root,
        dispatch_root=dispatch_root,
        state_path=state_path,
        lock_path=lock_path,
        runner=_FakeRunner(state_path),
        timeout_seconds=17,
    )

    assert third["worker_entrypoint_file_sha256"] == second_sha256
    assert third["worker_argv_template"] == changed_argv
    assert third["dispatch_id"] not in {first["dispatch_id"], second["dispatch_id"]}
