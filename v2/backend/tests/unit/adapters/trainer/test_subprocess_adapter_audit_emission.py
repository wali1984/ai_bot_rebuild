from __future__ import annotations

import hashlib

import pytest

from v2.backend.app.adapters.trainer import (
    SubprocessRunResult,
    TrainerSubprocessMode,
)


def test_invoke_emits_exactly_one_audit_event_on_success(
    adapter, audit_capture
):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert len(audit_capture) == 1
    assert audit_capture[0].safety_violation is None


def test_invoke_emits_exactly_one_audit_event_on_runner_exception(
    adapter, fake_runner, audit_capture
):
    fake_runner.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert len(audit_capture) == 1
    assert audit_capture[0].safety_violation == "runner_exception:RuntimeError"


def test_invoke_audit_event_carries_start_and_end_ts_from_clock_ms(
    adapter, fake_runner, audit_capture
):
    fake_runner.result = SubprocessRunResult(
        returncode=0,
        stdout=b"out",
        stderr=b"err",
        pid=42,
        start_ts_ms=111,
        end_ts_ms=222,
    )
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert audit_capture[0].start_ts_ms == 1000
    assert audit_capture[0].end_ts_ms == 222


def test_invoke_audit_event_carries_stdout_and_stderr_digests(
    adapter, fake_runner, audit_capture
):
    fake_runner.result = SubprocessRunResult(
        returncode=0,
        stdout=b"out",
        stderr=b"err",
        pid=42,
        start_ts_ms=111,
        end_ts_ms=222,
    )
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert audit_capture[0].stdout_digest_sha256 == hashlib.sha256(b"out").hexdigest()
    assert audit_capture[0].stderr_digest_sha256 == hashlib.sha256(b"err").hexdigest()


def test_invoke_audit_event_carries_stdout_and_stderr_paths_under_capture_dir(
    adapter, fake_runner, audit_capture
):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert audit_capture[0].stdout_path.endswith("task1/stdout.bin")
    assert audit_capture[0].stderr_path.endswith("task1/stderr.bin")
