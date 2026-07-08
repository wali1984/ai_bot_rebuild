from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.symbol_universe_public_payload import build_payload
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


def _write_status(root: Path, worker: str, payload: dict[str, object]) -> None:
    path = root / "v2/frontend/public/operator_runtime" / worker / "latest" / f"{worker}_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _write_portfolio(root: Path, payload: dict[str, object]) -> None:
    path = root / "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_payload_preserves_symbol_roles_without_live_symbols(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_trainer_bridge",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
            "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
            "observed_symbols": ["BTCUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
        },
    )

    payload = build_payload(tmp_path, generated_at="2026-05-14T10:00:00Z")

    assert payload["generated_at"] == "2026-05-14T10:00:00Z"
    assert payload["symbol_universe_contract"] == "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
    assert payload["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert payload["legacy_active_symbols_are_full_universe"] is False
    assert payload["discovered_symbols"] == ["BTCUSDT", "COINANK_ONLY_USDT", "ETHUSDT"]
    assert payload["observed_symbols"] == ["BTCUSDT"]
    assert payload["training_symbols"] == ["BTCUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    assert payload["live_symbols"] == []
    assert payload["live_gate"] == "blocked_human_only"


def test_training_or_paper_scope_matching_all_discovered_is_rejected(tmp_path: Path) -> None:
    discovered = ["BTCUSDT", "ETHUSDT"]
    _write_status(
        tmp_path,
        "v2_bad_scope",
        {
            "discovered_symbols": discovered,
            "training_symbols": discovered,
            "paper_symbols": discovered,
            "binance_usdm_confirmed_symbols": discovered,
        },
    )

    payload = build_payload(tmp_path)

    assert payload["training_symbols"] == []
    assert payload["paper_symbols"] == []
    assert payload["train_all_discovered_symbols"] is False
    assert payload["trade_all_discovered_symbols"] is False
    assert "requested_scope_matches_or_contains_all_discovered_symbols" in payload["symbol_universe_payload_evidence_gaps"]


def test_coinank_only_symbols_are_not_directly_tradable(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_coinank",
        {
            "discovered_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "paper_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
        },
    )

    payload = build_payload(tmp_path)

    assert payload["paper_symbols"] == []
    assert "COINANK_ONLY_USDT" in payload["rejected_paper_symbols"]
    assert payload["coinank_symbols_directly_tradable"] is False
    assert payload["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"


def test_active_paper_position_enters_runtime_scopes_when_binance_tradable(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        "v2_dynamic_symbol_discovery",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            "binance_usdm_tradable_symbols": ["BTCUSDT", "ETHUSDT", "BASUSDT"],
        },
    )
    _write_portfolio(
        tmp_path,
        {
            "open_positions": [
                {
                    "symbol": "BASUSDT",
                    "open_position": True,
                    "paper_session_id": "paper_3000_current",
                }
            ]
        },
    )

    payload = build_payload(tmp_path)

    assert "BASUSDT" in payload["active_paper_position_symbols"]
    assert "BASUSDT" in payload["discovered_symbols"]
    assert "BASUSDT" in payload["observed_symbols"]
    assert "BASUSDT" in payload["training_symbols"]
    assert "BASUSDT" in payload["paper_symbols"]
    assert payload["live_data_symbols"] == ["BASUSDT"]
    assert "BASUSDT" not in payload["rejected_paper_symbols"]
