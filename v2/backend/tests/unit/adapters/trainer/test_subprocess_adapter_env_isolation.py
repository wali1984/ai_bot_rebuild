from __future__ import annotations

from v2.backend.app.adapters.trainer import TrainerSubprocessMode
from v2.backend.app.adapters.trainer.audit_emitter import to_dict


def test_invoke_does_not_pass_through_os_environ(
    monkeypatch, make_adapter, fake_runner
):
    monkeypatch.setenv("POISON_SECRET_TOKEN", "should-not-appear")
    adapter = make_adapter(env_allowlist=frozenset())
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert "POISON_SECRET_TOKEN" not in fake_runner.calls[0].env


def test_invoke_passes_only_allowlisted_env_keys(
    monkeypatch, make_adapter, fake_runner
):
    monkeypatch.setenv("POISON_SECRET_TOKEN", "should-not-appear")
    adapter = make_adapter(env_allowlist=frozenset({"PYTHONUNBUFFERED"}))
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    assert fake_runner.calls[0].env == {"PYTHONUNBUFFERED": ""}


def test_invoke_env_values_are_not_audit_logged(make_adapter, fake_runner, audit_capture):
    adapter = make_adapter(env_allowlist=frozenset({"SENTINEL_ENV"}))
    adapter.invoke(task_id="task1", mode=TrainerSubprocessMode.STATUS)
    payload = str(to_dict(audit_capture[0]))
    assert "secret-value" not in payload
    assert "SENTINEL_ENV" not in payload
