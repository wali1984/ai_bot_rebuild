from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE_PATH = REPO_ROOT / "v2/scripts/deployment/preflight_check.py"
START_SCRIPT = REPO_ROOT / "v2/scripts/deployment/start_local_paper_runtime.sh"
STOP_SCRIPT = REPO_ROOT / "v2/scripts/deployment/stop_all_workers.sh"

spec = importlib.util.spec_from_file_location("v2_deployment_preflight_check", MODULE_PATH)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    python_bin = root / ".venv/bin/python3"
    python_bin.parent.mkdir(parents=True, exist_ok=True)
    python_bin.write_text("#!/usr/bin/env python3\n")
    python_bin.chmod(0o755)
    state = root / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"live_gate": "blocked_human_only", "final_approval_token": "absent"}))
    return root


def _write_symbol_payload(root: Path, payload: Dict[str, Any]) -> None:
    path = root / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_preflight_check_fails_when_approval_token_present(tmp_path: Path) -> None:
    root = _root(tmp_path)
    approval = root / "claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
    approval.parent.mkdir(parents=True, exist_ok=True)
    approval.write_text("not allowed\n")
    code, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert code == 2
    assert payload["status"] == "BLOCKED"
    assert "final_live_approval_token_present" in payload["blockers"]
    assert payload["live_gate"] == "blocked_human_only"


def test_preflight_check_passes_when_paper_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    code, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert code == 0
    assert payload["status"] == "PASS"
    assert payload["live_enabled"] is False
    assert payload["old_redis_write"] is False
    assert payload["exchange_action"] is False
    assert payload["leverage_or_margin_change"] is False
    assert payload["live_gate"] == "blocked_human_only"


def test_start_script_refuses_to_start_with_real_mode_flag() -> None:
    result = subprocess.run(
        ["bash", str(START_SCRIPT), "--paper-only", "--real"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "non_paper_mode_forbidden" in result.stderr


def test_start_script_paper_only_dry_run_is_safe() -> None:
    result = subprocess.run(
        ["bash", str(START_SCRIPT), "--paper-only", "--dry-run"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "V2_LOCAL_PAPER_RUNTIME_START_OK" in result.stdout
    assert "blocked_human_only" in result.stdout


def test_stop_script_idempotent_and_safe() -> None:
    result = subprocess.run(
        ["bash", str(STOP_SCRIPT), "--dry-run"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "V2_LOCAL_PAPER_STOP_OK" in result.stdout
    assert "legacy_untouched=true" in result.stdout
    assert "redis_untouched=true" in result.stdout


def test_stop_script_refuses_legacy_target() -> None:
    result = subprocess.run(
        ["bash", str(STOP_SCRIPT), "--legacy"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "target_not_allowed" in result.stderr


def test_symbol_universe_contract_required(tmp_path: Path) -> None:
    root = _root(tmp_path)
    code, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert code == 0
    assert payload["symbol_universe_contract"] == preflight.SYMBOL_UNIVERSE_CONTRACT
    assert payload["symbol_universe_source_path"] == preflight.SYMBOL_UNIVERSE_SERVICE_PATH
    assert payload["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert "missing_symbol_universe_public_payload" in payload["symbol_universe_payload_evidence_gaps"]


def test_symbol_scope_roles_distinguished(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    for field in (
        "legacy_active_symbols",
        "discovered_symbols",
        "observed_symbols",
        "training_symbols",
        "paper_symbols",
        "live_blocked_symbols",
        "binance_usdm_confirmed_symbols",
        "dynamic_discovered_symbols",
        "live_symbols",
    ):
        assert field in payload
    assert payload["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)


def test_no_hardcoded_current_25_symbols_as_full_universe() -> None:
    source = MODULE_PATH.read_text()
    for symbol in LEGACY_ACTIVE_SYMBOLS_25:
        assert f'"{symbol}"' not in source


def test_no_train_or_trade_all_discovered_symbols_automatically(tmp_path: Path) -> None:
    root = _root(tmp_path)
    discovered = ["BTCUSDT", "ETHUSDT", "COINANKONLYUSDT"]
    _write_symbol_payload(
        root,
        {
            "discovered_symbols": discovered,
            "dynamic_discovered_symbols": discovered,
            "training_symbols": discovered,
            "paper_symbols": discovered,
            "binance_usdm_confirmed_symbols": discovered,
            "symbol_selection_evidence": {"source": "test"},
        },
    )
    _, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert payload["train_all_discovered_symbols"] is False
    assert payload["trade_all_discovered_symbols"] is False
    assert payload["training_symbols"] == []
    assert payload["paper_symbols"] == []
    assert "requested_scope_matches_or_contains_all_discovered_symbols" in payload["symbol_universe_payload_evidence_gaps"]


def test_coinank_symbols_require_binance_usdm_confirmation_before_tradable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_symbol_payload(
        root,
        {
            "discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "dynamic_discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "training_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "paper_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            "symbol_selection_evidence": {"source": "test"},
        },
    )
    _, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert payload["training_symbols"] == []
    assert payload["paper_symbols"] == []
    assert "COINANKONLYUSDT" in payload["rejected_training_symbols"]
    assert "COINANKONLYUSDT" in payload["rejected_paper_symbols"]


def test_live_symbols_empty_while_live_blocked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    assert payload["live_symbols"] == []
    assert payload["live_symbol_policy"] == "none_live_blocked_human_only"
    assert payload["live_gate"] == "blocked_human_only"


def test_symbol_selection_score_factors_present(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _, payload = preflight.run_preflight(root=root, paper_only=True, mode="paper")
    for required in (
        "liquidity",
        "volume",
        "volatility",
        "funding",
        "open_interest",
        "spread",
        "freshness",
        "feature_completeness",
        "exchange_availability",
        "risk_profile",
        "model_confidence",
        "replay_performance",
        "operator_overrides",
    ):
        assert required in payload["symbol_selection_score_factors"]
