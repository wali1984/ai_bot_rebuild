from __future__ import annotations

import pytest

from v2.backend.app.adapters.trainer import (
    TrainerSubprocessMode,
    TrainerSubprocessTimeoutError,
)


def test_invoke_raises_timeout_error_when_runner_times_out(
    adapter, fake_runner
):
    fake_runner.side_effect = TrainerSubprocessTimeoutError("timed out")
    with pytest.raises(TrainerSubprocessTimeoutError):
        adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)


def test_invoke_emits_audit_event_with_timeout_violation(
    adapter, fake_runner, audit_capture
):
    fake_runner.side_effect = TrainerSubprocessTimeoutError("timed out")
    with pytest.raises(TrainerSubprocessTimeoutError):
        adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert len(audit_capture) == 1
    assert audit_capture[0].safety_violation == "timeout"


def test_invoke_returncode_none_on_timeout(adapter, fake_runner, audit_capture):
    fake_runner.side_effect = TrainerSubprocessTimeoutError("timed out")
    with pytest.raises(TrainerSubprocessTimeoutError):
        adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert audit_capture[0].returncode is None
