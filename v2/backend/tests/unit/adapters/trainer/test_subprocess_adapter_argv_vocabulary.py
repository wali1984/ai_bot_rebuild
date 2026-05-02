from __future__ import annotations

import pytest

from v2.backend.app.adapters.trainer import (
    TrainerSubprocessMode,
    TrainerSubprocessSafetyError,
)


def test_invoke_read_only_builds_expected_argv(adapter, fake_runner):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.READ_ONLY)
    assert fake_runner.calls[0].argv[-2:] == ["--mode", "read_only"]


def test_invoke_status_builds_expected_argv(adapter, fake_runner):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert fake_runner.calls[0].argv[-2:] == ["--mode", "status"]


def test_invoke_export_builds_expected_argv(adapter, fake_runner):
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.EXPORT)
    assert fake_runner.calls[0].argv[-2:] == ["--mode", "export"]


def test_invoke_rejects_string_mode_value(adapter, fake_runner):
    with pytest.raises(TrainerSubprocessSafetyError):
        adapter.invoke(task_id="task1", mode="status")  # type: ignore[arg-type]
    assert fake_runner.calls == []


def test_invoke_rejects_non_enum_mode(adapter, fake_runner):
    with pytest.raises(TrainerSubprocessSafetyError):
        adapter.invoke(task_id="task1", mode=object())  # type: ignore[arg-type]
    assert fake_runner.calls == []


def test_invoke_rejects_non_empty_extra_argv(adapter, fake_runner):
    with pytest.raises(TrainerSubprocessSafetyError):
        adapter.invoke(
            task_id="task1",
            mode=TrainerSubprocessMode.STATUS,
            extra_argv=("--anything",),
        )
    assert fake_runner.calls == []


@pytest.mark.parametrize("fragment", [";", "|", "&&", "`" * 2, "$("])
def test_invoke_rejects_path_with_shell_metacharacters(
    tmp_path, fake_runner, audit_capture, clock_ms, fragment
):
    from v2.backend.app.adapters.trainer import SubprocessTrainerAdapter

    with pytest.raises(TrainerSubprocessSafetyError):
        SubprocessTrainerAdapter(
            legacy_python_path=str(tmp_path / f"python{fragment}bad"),
            legacy_script_path=str(tmp_path / "trainer.py"),
            legacy_bot_root=str(tmp_path / "root"),
            capture_dir=str(tmp_path / "captures"),
            timeout_s=5.0,
            runner=fake_runner,
            clock_ms=clock_ms,
            env_allowlist=frozenset(),
            audit_sink=audit_capture.append,
        )
