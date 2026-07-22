from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_native_cuda_trainer_persistent_loop as cli

WAITING_MODULE = "v2.backend.app.services.native_trainer.profiled_training_waiting_runtime_v1"
LEGACY_RUNTIME_MODULE = "v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime"
CANONICAL_COST_ROOT = (
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
OBSERVER_RELEASE_SHA = "76a8ae2fe1f71fd9e1dc2f68775cdeebec8fc236"


def _valid_args(tmp_path: Path) -> list[str]:
    return [
        "--mode",
        "waiting-for-authenticated-samples",
        "--repo-root",
        str(tmp_path),
        "--ledger-path",
        str(tmp_path / "ledger.sqlite3"),
        "--trusted-cost-store-root",
        str(tmp_path / "cost-cas"),
        "--interval-seconds",
        "30",
        "--max-rows",
        "250000",
    ]


def test_missing_mode_fails_before_any_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, WAITING_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)
    args = _valid_args(tmp_path)
    del args[:2]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_unknown_mode_fails_before_any_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, WAITING_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)
    args = _valid_args(tmp_path)
    args[1] = "training"

    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_valid_mode_dispatches_only_to_waiting_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    fake_module = types.ModuleType(WAITING_MODULE)

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

    def fake_loop(config: object) -> int:
        received["config"] = config
        return 17

    fake_module.ProfiledTrainingWaitingConfigV1 = FakeConfig
    fake_module.run_profiled_training_waiting_loop_v1 = fake_loop
    monkeypatch.setitem(sys.modules, WAITING_MODULE, fake_module)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)

    assert cli.main(_valid_args(tmp_path)) == 17
    assert received["repo_root"] == tmp_path
    assert received["ledger_path"] == tmp_path / "ledger.sqlite3"
    assert received["trusted_cost_store_root"] == tmp_path / "cost-cas"
    assert received["interval_seconds"] == 30.0
    assert received["scan_limit"] == 250_000
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_repository_systemd_unit_pins_only_waiting_mode_and_canonical_paths() -> None:
    root = Path(__file__).resolve().parents[5]
    unit = (
        root / "claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service"
    ).read_text(encoding="utf-8")
    cli_source = Path(cli.__file__).read_text(encoding="utf-8")

    assert "--mode waiting-for-authenticated-samples" in unit
    assert (
        '--ledger-path "/home/wali/ai_bot_local_data/v2_native_trainer/'
        'durable_feature_snapshot_ledger.sqlite3"'
    ) in unit
    assert f'--trusted-cost-store-root "{CANONICAL_COST_ROOT}"' in unit
    assert "--max-rows 250000" in unit
    assert "StandardOutput=null" in unit
    assert "StandardError=null" in unit
    assert "/usr/bin/env bash" not in unit
    assert "V2_TRAINER_" not in unit
    assert "V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER" not in unit
    assert "--no-training" not in unit
    assert "persistent_cuda_trainer_runtime" not in cli_source


def test_repository_systemd_drop_in_pins_immutable_observer_release() -> None:
    root = Path(__file__).resolve().parents[5]
    drop_in = (
        root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-native-cuda-trainer-persistent.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")

    assert set(re.findall(r"[0-9a-f]{40}", drop_in)) == {OBSERVER_RELEASE_SHA}
    assert f'Environment="AI_BOT_CODE_SHA={OBSERVER_RELEASE_SHA}"' in drop_in
    assert (
        f"ExecStartPre=/usr/bin/git -C /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{OBSERVER_RELEASE_SHA} diff --quiet --exit-code "
        f"{OBSERVER_RELEASE_SHA} --"
    ) in drop_in
    assert (
        f"ExecStart=/usr/bin/python3 -I -B /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{OBSERVER_RELEASE_SHA}/v2/backend/app/cli/"
        "v2_native_cuda_trainer_persistent_loop.py "
        "--mode waiting-for-authenticated-samples"
    ) in drop_in
