from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_hermetic_replay_boundary_v4 as boundary_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_boundary_v4 import (
    CanonicalOhlcvHermeticReplayBoundaryV4Error,
    CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4,
    run_canonical_ohlcv_hermetic_replay_boundary_v4,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_protocol_v4 import (
    encode_canonical_ohlcv_hermetic_replay_policy_channel_v4,
    validate_canonical_ohlcv_hermetic_replay_policy_channel_v4,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_hermetic_replay_worker_v4 as worker_support,
)

_RESULT_DOMAIN_SEPARATOR = b"canonical_ohlcv_hermetic_replay_result_v4/result_sha256/v1\0"
_BOUNDARY_SOURCE = Path(boundary_module.__file__).resolve(strict=True)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _coordinates(
    fixture: worker_support._WorkerFixture,
    *,
    wall_time_milliseconds: int = 45_000,
    max_stdout_bytes: int = 64 * 1024,
    max_stderr_bytes: int = 64 * 1024,
) -> CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4:
    channel = dict(validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(fixture.channel))
    policy_document = cast(bytes, channel["policy_document"])
    policy = cast(dict[str, object], json.loads(policy_document))
    python_runtime = cast(dict[str, object], policy["python_runtime"])
    cas_root = cast(dict[str, object], policy["ledger_owned_cas_root"])
    return CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4(
        expected_policy_sha256=cast(str, channel["expected_policy_sha256"]),
        expected_registry_id=cast(str, channel["expected_registry_id"]),
        expected_registry_version=cast(str, channel["expected_registry_version"]),
        expected_policy_id=cast(str, channel["expected_policy_id"]),
        expected_policy_revision=cast(int, channel["expected_policy_revision"]),
        project_root=cast(str, policy["project_root"]),
        project_owner_uid=cast(int, policy["project_owner_uid"]),
        ledger_owned_cas_root=cast(str, cas_root["absolute_path"]),
        python_absolute_path=cast(str, python_runtime["absolute_path"]),
        python_executable_sha256=cast(str, python_runtime["executable_sha256"]),
        worker_absolute_path=str(fixture.worker_path),
        worker_sha256=hashlib.sha256(fixture.worker_path.read_bytes()).hexdigest(),
        wall_time_milliseconds=wall_time_milliseconds,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )


def _assert_boundary_error(call: Any, reason: str) -> None:
    with pytest.raises(CanonicalOhlcvHermeticReplayBoundaryV4Error) as exc_info:
        call()
    assert exc_info.value.reason == reason
    assert exc_info.value.cleanup_unconfirmed is False


def _replace_worker(
    fixture: worker_support._WorkerFixture,
    source: str,
) -> worker_support._WorkerFixture:
    fixture.worker_path.write_text(source, encoding="utf-8")
    fixture.worker_path.chmod(0o644)
    old_channel = dict(validate_canonical_ohlcv_hermetic_replay_policy_channel_v4(fixture.channel))
    old_policy = cast(dict[str, object], json.loads(cast(bytes, old_channel["policy_document"])))
    cas_root = Path(
        cast(
            str,
            cast(dict[str, object], old_policy["ledger_owned_cas_root"])["absolute_path"],
        )
    )
    policy_document, policy_sha256 = worker_support._policy_document(
        project_root=fixture.project_root,
        cas_root=cas_root,
        python_path=fixture.python_path,
    )
    channel = encode_canonical_ohlcv_hermetic_replay_policy_channel_v4(
        expected_policy_sha256=policy_sha256,
        expected_registry_id=worker_support._REGISTRY_ID,
        expected_registry_version=worker_support._REGISTRY_VERSION,
        expected_policy_id=worker_support._POLICY_ID,
        expected_policy_revision=worker_support._POLICY_REVISION,
        policy_document=policy_document,
    )
    return dataclasses.replace(
        fixture,
        channel=channel,
        expected_policy_sha256=policy_sha256,
    )


def _run(
    fixture: worker_support._WorkerFixture,
    *,
    coordinates: CanonicalOhlcvHermeticReplaySupervisorCoordinatesV4 | None = None,
) -> object:
    return run_canonical_ohlcv_hermetic_replay_boundary_v4(
        request_document=fixture.request,
        policy_channel_document=fixture.channel,
        supervisor_coordinates=coordinates or _coordinates(fixture),
    )


def _rehash_result(result: dict[str, object]) -> bytes:
    material = dict(result)
    material.pop("result_sha256", None)
    result["result_sha256"] = hashlib.sha256(
        _RESULT_DOMAIN_SEPARATOR + _canonical(material)
    ).hexdigest()
    return _canonical(result)


def test_boundary_source_is_dormant_and_has_no_trading_or_service_wiring_imports() -> None:
    tree = ast.parse(_BOUNDARY_SOURCE.read_bytes())
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert not any(
        marker in module
        for module in imported_modules
        for marker in (
            "redis",
            "allocator",
            "risk",
            "paper_trade",
            "execution",
            "orchestrator",
            "trainer_runtime",
        )
    )


def test_real_worker_success_is_exact_audit_only_and_non_authorizing(tmp_path: Path) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    result = cast(dict[str, object], _run(fixture))
    assert result["schema_version"] == "canonical_ohlcv_hermetic_replay_result_v4"
    assert result["request_sha256"] == fixture.expected_request_sha256
    assert result["policy_sha256"] == fixture.expected_policy_sha256
    assert result["manifest_sha256"] == fixture.expected_manifest_sha256
    assert result["selected_row_payload_sha256"] == fixture.expected_selected_row_sha256
    assert result["policy_channel_sealing_verified"] is True
    assert result["policy_channel_immutability_verified"] is True
    assert result["selected_row_binding_replayed"] is True
    assert result["runtime_network_disable_required"] is True
    assert result["runtime_filesystem_write_disable_required"] is True
    assert result["process_resource_limits_applied_after_interpreter_bootstrap"] is True
    assert result["process_resource_limits_verified_at_validation"] is True
    assert result["process_resource_limits_enforced_before_interpreter_bootstrap"] is False
    assert result["process_core_limit_bytes"] == 0
    assert result["process_cpu_time_limit_seconds"] == 30
    assert result["process_address_space_limit_bytes"] == 2 * 1024 * 1024 * 1024
    assert result["process_open_file_descriptor_limit"] == 32
    assert result["process_count_limit"] == 1
    assert result["process_file_write_limit_bytes"] == 0
    for field in (
        "policy_source_authenticated",
        "runtime_dependency_closure_verified",
        "runtime_sandbox_enforced",
        "runtime_network_disabled",
        "runtime_filesystem_write_disabled",
        "systemd_unit_verified",
        "systemd_sandbox_enforced",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_wired",
    ):
        assert result[field] is False
    assert result["audit_only"] is True
    with pytest.raises(TypeError):
        result["runtime_wired"] = True


def test_caller_inputs_and_supervisor_coordinates_are_strict_and_separate(
    tmp_path: Path,
) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    coordinates = _coordinates(fixture)

    _assert_boundary_error(
        lambda: run_canonical_ohlcv_hermetic_replay_boundary_v4(
            request_document=bytearray(fixture.request),
            policy_channel_document=fixture.channel,
            supervisor_coordinates=coordinates,
        ),
        "hermetic_replay_boundary_request_exact_bytes_required",
    )
    _assert_boundary_error(
        lambda: run_canonical_ohlcv_hermetic_replay_boundary_v4(
            request_document=fixture.request,
            policy_channel_document=memoryview(fixture.channel),
            supervisor_coordinates=coordinates,
        ),
        "hermetic_replay_boundary_policy_channel_exact_bytes_required",
    )
    _assert_boundary_error(
        lambda: run_canonical_ohlcv_hermetic_replay_boundary_v4(
            request_document=fixture.request,
            policy_channel_document=fixture.channel,
            supervisor_coordinates=dataclasses.asdict(coordinates),
        ),
        "hermetic_replay_boundary_supervisor_coordinates_exact_type_required",
    )
    _assert_boundary_error(
        lambda: run_canonical_ohlcv_hermetic_replay_boundary_v4(
            request_document=fixture.request + b"\n",
            policy_channel_document=fixture.channel,
            supervisor_coordinates=coordinates,
        ),
        "hermetic_replay_boundary_request_invalid",
    )
    _assert_boundary_error(
        lambda: run_canonical_ohlcv_hermetic_replay_boundary_v4(
            request_document=fixture.request,
            policy_channel_document=fixture.channel + b"\n",
            supervisor_coordinates=coordinates,
        ),
        "hermetic_replay_boundary_policy_channel_invalid",
    )
    mismatched_policy = dataclasses.replace(coordinates, expected_policy_sha256="0" * 64)
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=mismatched_policy),
        "hermetic_replay_boundary_policy_channel_supervisor_coordinate_mismatch",
    )
    expanded_wall = dataclasses.replace(coordinates, wall_time_milliseconds=45_001)
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=expanded_wall),
        "hermetic_replay_boundary_wall_ceiling_invalid",
    )
    alternate_project_root = str(tmp_path / "alternate-hermetic-root")
    alternate_root = dataclasses.replace(
        coordinates,
        project_root=alternate_project_root,
        worker_absolute_path=str(
            Path(alternate_project_root) / "v2/backend/app/services/native_trainer/"
            "canonical_ohlcv_hermetic_replay_worker_v4.py"
        ),
    )
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=alternate_root),
        "hermetic_replay_boundary_policy_supervisor_coordinate_mismatch",
    )


@pytest.mark.parametrize(
    ("body", "coordinate_overrides", "reason"),
    [
        (
            "import sys\nsys.stdin.buffer.read()\nraise SystemExit(17)\n",
            {},
            "hermetic_replay_boundary_worker_nonzero_exit",
        ),
        (
            "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('{')\n",
            {},
            "hermetic_replay_boundary_result_json_invalid",
        ),
        (
            "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('{}\\n')\n",
            {},
            "hermetic_replay_boundary_result_noncanonical_json",
        ),
        (
            "import sys\nsys.stdin.buffer.read()\nsys.stdout.write('{}')\n"
            "sys.stderr.write('unexpected-stderr')\n",
            {},
            "hermetic_replay_boundary_worker_stderr_forbidden",
        ),
        (
            "import os,sys\nsys.stdin.buffer.read()\nos.write(1,b'x'*1025)\n",
            {"max_stdout_bytes": 1024},
            "hermetic_replay_boundary_stdout_limit_exceeded",
        ),
        (
            "import os,sys\nsys.stdin.buffer.read()\nos.write(2,b'x'*1025)\n",
            {"max_stderr_bytes": 1024},
            "hermetic_replay_boundary_stderr_limit_exceeded",
        ),
    ],
)
def test_real_process_nonzero_partial_trailing_stderr_and_flood_fail_closed(
    tmp_path: Path,
    body: str,
    coordinate_overrides: dict[str, int],
    reason: str,
) -> None:
    fixture = _replace_worker(worker_support._build_worker_fixture(tmp_path), body)
    coordinates = cast(Any, dataclasses.replace)(_coordinates(fixture), **coordinate_overrides)
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=coordinates),
        reason,
    )


def test_timeout_kills_process_group_and_reaps_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _replace_worker(
        worker_support._build_worker_fixture(tmp_path),
        "import sys,time\nsys.stdin.buffer.read()\ntime.sleep(30)\n",
    )
    coordinates = _coordinates(fixture, wall_time_milliseconds=100)
    real_killpg = os.killpg
    killed_groups: list[int] = []

    def recording_killpg(process_group: int, selected_signal: signal.Signals) -> None:
        killed_groups.append(process_group)
        real_killpg(process_group, selected_signal)

    monkeypatch.setattr(os, "killpg", recording_killpg)
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=coordinates),
        "hermetic_replay_boundary_wall_timeout",
    )
    assert len(killed_groups) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(killed_groups[0], 0)


def test_child_receives_exact_flags_args_cwd_environment_and_sealed_read_only_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inherited_sentinel = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
    helper = f"""\
import fcntl
import os
import sys

ok = len(sys.argv) == 5 and sys.argv[1] == "--policy-fd"
ok = ok and sys.argv[3] == "--worker-path" and os.path.isabs(sys.argv[4])
ok = ok and sys.argv[0].startswith("/proc/self/fd/")
ok = ok and sys.flags.isolated == 1 and sys.flags.no_site == 1
ok = ok and sys.flags.dont_write_bytecode == 1 and sys.flags.optimize == 0
ok = ok and os.getcwd() == "/"
ok = ok and dict(os.environ) == {{"LANG": "C", "LC_ALL": "C"}}
try:
    os.fstat({inherited_sentinel})
except OSError:
    pass
else:
    ok = False
try:
    policy_fd = int(sys.argv[2])
    worker_fd = int(sys.argv[0].removeprefix("/proc/self/fd/"))
    flags = fcntl.fcntl(policy_fd, fcntl.F_GETFL)
    seals = fcntl.fcntl(policy_fd, fcntl.F_GET_SEALS)
    worker_flags = fcntl.fcntl(worker_fd, fcntl.F_GETFL)
    worker_seals = fcntl.fcntl(worker_fd, fcntl.F_GET_SEALS)
    required = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
    os.lseek(policy_fd, 0, os.SEEK_SET)
    channel = os.read(policy_fd, 192 * 1024 + 1)
    ok = ok and flags & os.O_ACCMODE == os.O_RDONLY
    ok = ok and seals & required == required
    ok = ok and channel.startswith(b"{{") and channel.endswith(b"}}")
    ok = ok and worker_flags & os.O_ACCMODE == os.O_RDONLY
    ok = ok and worker_seals & required == required
except BaseException:
    ok = False
sys.stdin.buffer.read()
if not ok:
    raise SystemExit(19)
sys.stdout.write("{{}}")
"""
    try:
        fixture = _replace_worker(worker_support._build_worker_fixture(tmp_path), helper)
        real_popen = subprocess.Popen
        observed_invocations = 0

        def inspecting_popen(*args: Any, **kwargs: Any) -> Any:
            nonlocal observed_invocations
            observed_invocations += 1
            command = cast(list[str], args[0])
            executable = cast(str, kwargs["executable"])
            pass_fds = cast(tuple[int, ...], kwargs["pass_fds"])
            assert "preexec_fn" not in kwargs
            assert executable.startswith("/proc/self/fd/")
            assert command[1:4] == ["-I", "-S", "-B"]
            assert command[4].startswith("/proc/self/fd/")
            assert command[5] == "--policy-fd"
            assert command[7] == "--worker-path"
            assert command[8] == str(fixture.worker_path)
            assert set(pass_fds) == {
                int(executable.removeprefix("/proc/self/fd/")),
                int(command[4].removeprefix("/proc/self/fd/")),
                int(command[6]),
            }
            assert kwargs["shell"] is False
            assert kwargs["cwd"] == "/"
            assert kwargs["close_fds"] is True
            assert kwargs["start_new_session"] is True
            return real_popen(*args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", inspecting_popen)
        _assert_boundary_error(
            lambda: _run(fixture),
            "hermetic_replay_boundary_result_fields_invalid",
        )
        assert observed_invocations == 1
    finally:
        os.close(inherited_sentinel)


def test_self_digested_authority_and_coordinate_tampering_is_rejected(
    tmp_path: Path,
) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    coordinates = _coordinates(fixture)
    validated = boundary_module._validate_parent_inputs(
        request_document=fixture.request,
        policy_channel_document=fixture.channel,
        supervisor_coordinates=coordinates,
    )
    original = dict(cast(Any, _run(fixture, coordinates=coordinates)))

    authority = dict(original)
    authority["trainer_admission_authorized"] = True
    _assert_boundary_error(
        lambda: boundary_module._validate_result(
            _rehash_result(authority),
            validated=validated,
        ),
        "hermetic_replay_boundary_result_authority_or_sandbox_claim_invalid",
    )

    coordinate = dict(original)
    coordinate["project_root"] = str(tmp_path / "self-digested-alternate-root")
    _assert_boundary_error(
        lambda: boundary_module._validate_result(
            _rehash_result(coordinate),
            validated=validated,
        ),
        "hermetic_replay_boundary_result_request_policy_coordinate_mismatch",
    )

    digest = dict(original)
    digest["result_sha256"] = "0" * 64
    _assert_boundary_error(
        lambda: boundary_module._validate_result(
            _canonical(digest),
            validated=validated,
        ),
        "hermetic_replay_boundary_result_digest_mismatch",
    )

    expanded_resource = dict(original)
    expanded_resource["process_open_file_descriptor_limit"] = 33
    _assert_boundary_error(
        lambda: boundary_module._validate_result(
            _rehash_result(expanded_resource),
            validated=validated,
        ),
        "hermetic_replay_boundary_result_resource_limit_claim_invalid",
    )


def test_launch_stage_time_is_charged_to_wall_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    coordinates = _coordinates(fixture, wall_time_milliseconds=50)
    real_popen = subprocess.Popen

    def delayed_popen(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.15)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", delayed_popen)
    _assert_boundary_error(
        lambda: _run(fixture, coordinates=coordinates),
        "hermetic_replay_boundary_wall_timeout",
    )


def test_worker_path_replacement_after_parent_validation_fails_before_launch(
    tmp_path: Path,
) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    coordinates = _coordinates(fixture)
    validated = boundary_module._validate_parent_inputs(
        request_document=fixture.request,
        policy_channel_document=fixture.channel,
        supervisor_coordinates=coordinates,
    )
    original_source = fixture.worker_path.read_bytes()
    try:
        fixture.worker_path.write_bytes(b"raise SystemExit(99)\n")
        fixture.worker_path.chmod(0o644)
        _assert_boundary_error(
            lambda: boundary_module._launch_and_capture(validated, fixture.request),
            "hermetic_replay_boundary_worker_launch_identity_mismatch",
        )
    finally:
        fixture.worker_path.write_bytes(original_source)
        fixture.worker_path.chmod(0o644)


def test_descriptor_bound_worker_rejects_path_swap_at_exec_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = worker_support._build_worker_fixture(tmp_path)
    coordinates = _coordinates(fixture)
    original_source = fixture.worker_path.read_bytes()
    real_popen = subprocess.Popen

    def swapping_popen(*args: Any, **kwargs: Any) -> Any:
        fixture.worker_path.write_bytes(b"raise SystemExit(98)\n")
        fixture.worker_path.chmod(0o644)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", swapping_popen)
    try:
        _assert_boundary_error(
            lambda: _run(fixture, coordinates=coordinates),
            "hermetic_replay_boundary_worker_nonzero_exit",
        )
    finally:
        fixture.worker_path.write_bytes(original_source)
        fixture.worker_path.chmod(0o644)


def test_repeated_reap_failure_is_explicitly_cleanup_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NeverReapedProcess:
        pid = 2_000_000_000
        stdin = None
        stdout = None
        stderr = None

        def __init__(self) -> None:
            self.wait_calls = 0
            self.kill_calls = 0

        def wait(self, *, timeout: float) -> int:
            self.wait_calls += 1
            raise subprocess.TimeoutExpired(cmd="reap-probe", timeout=timeout)

        def kill(self) -> None:
            self.kill_calls += 1

    monkeypatch.setattr(os, "killpg", lambda _pid, _signal: None)
    first = NeverReapedProcess()
    assert boundary_module._kill_process_group_and_reap(cast(Any, first)) is False
    assert first.wait_calls == 2
    assert first.kill_calls == 2

    second = NeverReapedProcess()
    with pytest.raises(CanonicalOhlcvHermeticReplayBoundaryV4Error) as exc_info:
        boundary_module._cleanup_or_fail(cast(Any, second))
    assert exc_info.value.reason == "hermetic_replay_boundary_cleanup_unconfirmed"
    assert exc_info.value.cleanup_unconfirmed is True
    assert second.wait_calls == 2
    assert second.kill_calls == 2
