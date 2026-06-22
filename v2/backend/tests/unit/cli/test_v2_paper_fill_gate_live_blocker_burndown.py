from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli import (
    v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready as cli,
)


def test_valid_negative_expected_move_hold_is_not_bug_block() -> None:
    inventory = {
        "holds": [
            {
                "prediction_id": "pred_1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "paper_fill_block_reasons": ["negative_expected_move_after_cost_block"],
                "confidence_calibrated": None,
                "expected_move_after_cost_bps": None,
                "data_coverage_percent": None,
                "price_target": None,
                "null_field_hold": True,
                "prediction_enriched": False,
                "valid_block_reason_present": True,
            }
        ]
    }

    result = cli.classify_gate_validity(inventory, "2026-06-05T12:00:00-04:00")

    assert result["valid_block_count"] == 1
    assert result["bug_block_count"] == 0
    assert result["rows"][0]["classification"] == "VALID_BLOCK"


def test_final_gate_blocks_proposed_risk_caps_without_operator_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cuda_dir = tmp_path / "cuda"
    final_dir = tmp_path / "final"
    cuda_dir.mkdir()
    final_dir.mkdir()
    (cuda_dir / "binance_private_trader_connectivity_status.json").write_text(
        json.dumps(
            {
                "account_read_status": "OK",
                "account_summary_redacted": {"balances_redacted": True},
                "position_read_status": "OK",
                "exchange_info_status": "OK",
                "test_order_endpoint_attempted": False,
                "real_order_attempted": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
            }
        ),
        encoding="utf-8",
    )
    (cuda_dir / "trader_runtime_start_status.json").write_text(
        json.dumps(
            {
                "status": "TRADER_CONNECTED_EXECUTION_FROZEN",
                "exchange_mutation_state": "EXCHANGE_MUTATION_FROZEN",
            }
        ),
        encoding="utf-8",
    )
    (final_dir / "final_live_gate_evaluation_status.json").write_text(
        json.dumps({"verdict": "PRIOR_PACKET_EXISTS_WITHOUT_OPERATOR_AUDIT"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "CUDA_GATE_DIR", cuda_dir)
    monkeypatch.setattr(cli, "FINAL_LIVE_PACKET_DIR", final_dir)

    inventory = {
        "accepted_paper_fills": 8,
        "held_by_paper_fill_gate": 104,
        "paper_fill_allowed_propagation_bug_count": 0,
    }
    reactivation = {"enable_paper_profile_only": True}
    symbol_payload = {
        "proposed_live_symbols": ["BTCUSDT"],
        "operator_acceptance_required": True,
        "operator_acceptance_present": False,
        "operator_acceptance_audit_id": None,
        "live_symbols_written": [],
        "execution_live_symbols_written": [],
    }
    risk_payload = {
        "profiles": {"balanced": {"max_notional_per_trade": 75.0}},
        "operator_acceptance_required": True,
        "operator_acceptance_present": False,
        "operator_acceptance_audit_id": None,
        "auto_accept": False,
    }

    _, final_payload, dashboard = cli.build_runtime_and_final_gate(
        inventory,
        reactivation,
        symbol_payload,
        risk_payload,
        "2026-06-05T12:00:00-04:00",
    )

    assert final_payload["verdict"] == "LIVE_GATE_BLOCKED_RISK_CAPS_OPERATOR_REQUIRED"
    assert final_payload["live_enable_available_through_backend_gate"] is False
    assert final_payload["live_symbols"] == []
    assert final_payload["execution_live_symbols"] == []
    assert final_payload["requirements"]["risk_profile_operator_accepted"] is False
    assert dashboard["backend_live_enable_callable"] is False
