from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_config_admin_manager as worker
from v2.backend.app.cli.v2_config_admin_manager import (
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    build_status,
    run_once,
)
from v2.backend.app.services.config_admin.service import (
    VALIDATION_PENDING_APPROVAL,
    default_settings,
    stage_setting,
    summarize_settings,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


def _route_worker(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    public_dir = tmp_path / "public" / "operator_runtime" / worker.WORKER_ID / "latest"
    local_dir = tmp_path / "runtime" / worker.WORKER_ID / "latest"
    worker_dir = tmp_path / "workers"
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
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _setting(status: dict, key: str) -> dict:
    for row in status["settings"]:
        if row["setting_key"] == key:
            return row
    raise AssertionError(key)


def test_non_dangerous_settings_crud_works() -> None:
    settings = stage_setting(
        default_settings(now="2026-05-14T08:00:00Z"),
        setting_key="paper_runtime_interval_seconds",
        staged_value=45,
        actor="operator",
        changed_at="2026-05-14T08:01:00Z",
    )
    row = summarize_settings(settings)["settings"][0]
    assert row["setting_key"] == "paper_runtime_interval_seconds"
    assert row["effective_value"] == 45
    assert row["rollback_value"] == 30
    assert row["approval_required"] is False


def test_dangerous_settings_require_human_approval_token() -> None:
    settings = stage_setting(
        default_settings(now="2026-05-14T08:00:00Z"),
        setting_key="live_trading_enabled",
        staged_value=True,
        actor="operator",
        approval_token_present=False,
        changed_at="2026-05-14T08:01:00Z",
    )
    summary = summarize_settings(settings)
    row = next(r for r in summary["settings"] if r["setting_key"] == "live_trading_enabled")
    assert row["effective_value"] is False
    assert row["staged_value"] is True
    assert row["validation_status"] == VALIDATION_PENDING_APPROVAL
    assert len(summary["dangerous_settings_pending_approval"]) == 1


def test_approval_token_for_gate_leverage_or_margin_is_never_self_creatable(
    tmp_path: Path, monkeypatch
) -> None:
    _route_worker(tmp_path, monkeypatch)
    approval = tmp_path / "claude_worklog" / "approvals" / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
    staged = tmp_path / "staged.json"
    staged.write_text(
        json.dumps(
            {
                "staged_changes": [
                    {"setting_key": "leverage_cap", "staged_value": 5, "actor": "operator"},
                    {"setting_key": "margin_mode", "staged_value": "CROSS", "actor": "operator"},
                ]
            }
        )
    )
    status = run_once(staged_changes_path=staged, write=True)
    assert status["approval_token_created"] is False
    assert status["approval_token_self_creatable"] is False
    assert not approval.exists()
    assert _setting(status, "leverage_cap")["effective_value"] == 1
    assert _setting(status, "margin_mode")["effective_value"] == "ISOLATED_ONLY"


def test_staged_value_distinct_from_effective_value_and_rollback_recorded() -> None:
    settings = stage_setting(
        default_settings(now="2026-05-14T08:00:00Z"),
        setting_key="paper_to_live_switch",
        staged_value="go_live",
        actor="operator",
        changed_at="2026-05-14T08:01:00Z",
    )
    row = next(r for r in summarize_settings(settings)["settings"] if r["setting_key"] == "paper_to_live_switch")
    assert row["effective_value"] == "blocked_human_only"
    assert row["staged_value"] == "go_live"
    assert row["rollback_value"] == "blocked_human_only"
    assert row["approval_required"] is True


def test_secrets_not_written_to_payload_invariant() -> None:
    status = build_status()
    key = _setting(status, "binance_api_key")
    secret = _setting(status, "binance_api_secret")
    assert key["effective_value"] == "REDACTED"
    assert secret["effective_value"] == "REDACTED"
    assert status["secrets_written_to_payload"] is False
    assert status["secrets_redacted"] is True


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
    _route_worker(tmp_path, monkeypatch)
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
    _route_worker(tmp_path, monkeypatch)
    symbol_payload = tmp_path / "symbol_universe_status.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": ["BTCUSDT"],
                "discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
                "dynamic_discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
                "training_symbols": ["BTCUSDT"],
                "paper_symbols": ["BTCUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT"],
                "live_blocked_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            }
        )
    )
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [symbol_payload])
    status = build_status()
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert (
        status["legacy_active_symbols_public_payload_status"]
        == "PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED"
    )
    assert status["dynamic_discovered_symbols"] == ["BTCUSDT", "COINANKONLYUSDT"]
    assert status["training_symbols"] == ["BTCUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert status["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"
    assert status["symbol_selection_score_factors"] == list(SYMBOL_SELECTION_SCORE_FACTORS)
