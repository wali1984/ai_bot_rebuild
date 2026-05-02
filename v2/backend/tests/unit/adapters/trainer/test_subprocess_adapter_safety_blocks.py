from __future__ import annotations

import inspect

from v2.backend.app.adapters.trainer import default_runner, subprocess_adapter


def _source(module) -> str:
    return inspect.getsource(module)


def test_adapter_module_does_not_import_subprocess_directly():
    text = _source(subprocess_adapter)
    assert "import subprocess" not in text
    assert "from subprocess" not in text


def test_adapter_module_does_not_import_legacy_modules():
    text = _source(subprocess_adapter)
    forbidden = [
        "legacy_reference",
        "rl.hybrid_trainer",
        "rl.orchestrator_worker",
        "trading.trader",
        "trading.trader_asjad",
    ]
    for target in forbidden:
        assert target not in text


def test_adapter_module_does_not_import_redis():
    text = _source(subprocess_adapter)
    assert "import redis" not in text
    assert "redis.asyncio" not in text


def test_default_runner_uses_shell_false():
    text = _source(default_runner)
    assert "subprocess.run(" in text
    assert "shell=False" in text
    assert "shell=True" not in text
