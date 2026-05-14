from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_script_monitor as worker
from v2.backend.app.cli.v2_script_monitor import (
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    build_status,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


def _route_worker(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    public_dir = tmp_path / "public" / "operator_runtime" / worker.WORKER_ID / "latest"
    local_dir = tmp_path / "runtime" / worker.WORKER_ID / "latest"
    worker_dir = tmp_path / "workers"
    cli_dir = tmp_path / "v2" / "backend" / "app" / "cli"
    runtime_root = tmp_path / "public" / "operator_runtime"
    task_dir = tmp_path / "tasks"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", public_dir / f"{worker.WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{worker.WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", worker_dir / f"{worker.WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worker, "V2_ROOT", tmp_path / "v2")
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "missing_symbol_payload.json"],
    )
    return {
        "public": public_dir,
        "local": local_dir,
        "worker": worker_dir,
        "cli": cli_dir,
        "runtime_root": runtime_root,
        "task_dir": task_dir,
    }


def _patch_service_roots(tmp_path: Path, monkeypatch, routes: dict[str, Path]) -> None:
    def _collect_script_statuses(*, repo_root: Path):
        from v2.backend.app.services.monitor_runner import collect_script_statuses

        return collect_script_statuses(
            repo_root=tmp_path,
            cli_dir=routes["cli"],
            public_runtime_root=routes["runtime_root"],
            task_dir=routes["task_dir"],
        )

    monkeypatch.setattr(worker, "collect_script_statuses", _collect_script_statuses)


def _write_cli(routes: dict[str, Path], name: str, text: str) -> Path:
    routes["cli"].mkdir(parents=True, exist_ok=True)
    path = routes["cli"] / name
    path.write_text(text)
    return path


def _write_task(routes: dict[str, Path], worker_id: str) -> None:
    routes["task_dir"].mkdir(parents=True, exist_ok=True)
    (routes["task_dir"] / f"claude_port_{worker_id}.json").write_text(
        json.dumps({"task_id": f"claude_port_{worker_id}", "status": "pending"})
    )


def _write_payload(routes: dict[str, Path], worker_id: str, payload: dict) -> None:
    path = routes["runtime_root"] / worker_id / "latest" / f"{worker_id}_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_each_monitored_script_status_captured(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    _write_cli(
        routes,
        "v2_good_worker.py",
        'import argparse\n\ndef main():\n    return 0\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    )
    _write_task(routes, "v2_good_worker")
    _write_payload(
        routes,
        "v2_good_worker",
        {"worker_id": "v2_good_worker", "last_run_ts": "2026-05-14T08:00:00Z"},
    )
    status = build_status()
    assert status["scripts_enumerated_total"] == 1
    assert status["scripts_by_status"]["active"] == 1
    assert status["scripts"][0]["worker_id"] == "v2_good_worker"
    assert status["scripts"][0]["metrics_emitted"] is True


def test_broken_script_classified_correctly(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    _write_cli(routes, "v2_broken_worker.py", '"""placeholder"""\n')
    status = build_status()
    assert status["scripts_by_status"]["broken"] == 1
    assert status["scripts_broken"][0]["worker_id"] == "v2_broken_worker"
    assert "placeholder_or_stub" in status["scripts_broken"][0]["alerts"]


def test_unused_script_classified_correctly(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    _write_cli(
        routes,
        "v2_unused_worker.py",
        'import argparse\n\ndef main():\n    return 0\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    )
    status = build_status()
    assert status["scripts_by_status"]["unused"] == 1
    assert status["scripts_unused"][0]["worker_id"] == "v2_unused_worker"


def test_monitor_does_not_execute_legacy_scripts_invariant(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    marker = tmp_path / "legacy_would_have_run"
    legacy_script = tmp_path / "legacy_reference" / "danger.py"
    legacy_script.parent.mkdir(parents=True, exist_ok=True)
    legacy_script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
    _write_cli(
        routes,
        "v2_good_worker.py",
        'import argparse\n\ndef main():\n    return 0\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    )
    status = build_status()
    assert status["legacy_scripts_executed"] is False
    assert not marker.exists()


def test_no_old_redis_write_contract() -> None:
    source = Path(worker.__file__).read_text(encoding="utf-8")
    forbidden = [
        "X" + "A" + "DD",
        "H" + "S" + "ET",
        "X" + "D" + "EL",
        "X" + "T" + "RIM",
        "F" + "L" + "USH",
        "redis" + ".Redis(",
        "from " + "redis",
        "import " + "redis",
    ]
    for token in forbidden:
        assert token not in source


def test_symbol_universe_contract_required(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    status = build_status()
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status
    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert status["live_symbols"] == []
    assert status["live_gate"] == LIVE_GATE_STATUS
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False


def test_public_symbol_payload_cannot_override_canonical_legacy_25(
    tmp_path: Path, monkeypatch
) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    symbol_payload = tmp_path / "symbol_universe_status.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": ["BTCUSDT"],
                "discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
                "dynamic_discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT", "KUCOINONLYUSDT"],
                "training_symbols": ["BTCUSDT"],
                "paper_symbols": ["BTCUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT"],
                "live_blocked_symbols": ["BTCUSDT", "COINANKONLYUSDT", "KUCOINONLYUSDT"],
            }
        )
    )
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [symbol_payload])
    status = build_status()
    assert status["symbol_universe_public_payload_status"] == "PRESENT"
    assert (
        status["legacy_active_symbols_public_payload_status"]
        == "PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED"
    )
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert status["dynamic_discovered_symbols"] == ["BTCUSDT", "COINANKONLYUSDT", "KUCOINONLYUSDT"]
    assert status["training_symbols"] == ["BTCUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert status["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"
    assert status["binance_usdm_confirmed_symbols"] == ["BTCUSDT"]
    assert status["symbol_selection_score_factors"] == list(SYMBOL_SELECTION_SCORE_FACTORS)


def test_run_once_writes_all_status_files(tmp_path: Path, monkeypatch) -> None:
    routes = _route_worker(tmp_path, monkeypatch)
    _patch_service_roots(tmp_path, monkeypatch, routes)
    status = run_once(write=True)
    assert status["worker_id"] == worker.WORKER_ID
    assert (routes["public"] / f"{worker.WORKER_ID}_status.json").exists()
    assert (routes["local"] / f"{worker.WORKER_ID}_status.json").exists()
    assert (routes["worker"] / f"{worker.WORKER_ID}_status.json").exists()
