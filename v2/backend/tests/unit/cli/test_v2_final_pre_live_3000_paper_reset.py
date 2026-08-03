from __future__ import annotations

from v2.backend.app.cli import v2_final_pre_live_3000_paper_reset as reset


def test_reset_payloads_initialize_clean_3000_paper_session() -> None:
    payloads = reset._build_reset_payloads(
        "paper_3000_final_pre_live_20260705T000000Z",
        "2026-07-05T00:00:00Z",
    )

    portfolio = payloads["portfolio_state"]
    session = payloads["paper_session"]
    ledger = payloads["ledger"]

    assert session["initial_capital"] == 3000.0
    assert session["starting_equity_usd"] == 3000.0
    assert session["paper_session_id"] == "paper_3000_final_pre_live_20260705T000000Z"
    assert session["places_real_order"] is False
    assert portfolio["initial_capital"] == 3000.0
    assert portfolio["starting_equity_usd"] == 3000.0
    assert portfolio["equity"] == 3000.0
    assert portfolio["available_balance"] == 3000.0
    assert portfolio["open_positions"] == []
    assert portfolio["closed_trades"] == []
    assert portfolio["account_scope"] == "PAPER_SIM_ACCOUNT"
    assert portfolio["paper_or_live"] == "paper"
    assert portfolio["equity_trusted"] is True
    assert portfolio["pnl_trusted"] is True
    assert portfolio["places_real_order"] is False
    assert portfolio["routes_to_live"] is False
    assert ledger["accepted"] == []
    assert ledger["closed_trades"] == []
    assert ledger["trainer_feedback_outcomes_quarantine"] == []
    assert ledger["paper_session_id"] == "paper_3000_final_pre_live_20260705T000000Z"


def test_btc_100_phantom_detection_uses_signal_id_and_price() -> None:
    payloads = {
        "v2:paper:ledger": {
            "accepted": [
                {
                    "signal_id": "signal-btc-1m",
                    "symbol": "BTCUSDT",
                    "entry_price": 100.0,
                    "quantity": 8,
                }
            ]
        }
    }

    assert reset._btc_100_phantom_absent(payloads) is False
    assert reset._btc_100_phantom_absent({"v2:paper:ledger": {"accepted": []}}) is True


def test_reset_key_plan_preserves_quarantine_and_deletes_only_outcome_memory_pattern() -> None:
    plan = reset._reset_key_plan(["v2:paper:outcome_memory:BTCUSDT:1m"])

    assert "v2:paper:quarantine:*" in plan["preserved_keys"]
    assert "v2:paper:historical_outcome_counts" in plan["preserved_keys"]
    assert "v2:paper:quarantine:*" not in plan["fixed_reset_keys"]
    assert "v2:paper:session" in plan["fixed_reset_keys"]
    assert plan["pattern_reset_keys"] == {
        "v2:paper:outcome_memory:*": ["v2:paper:outcome_memory:BTCUSDT:1m"]
    }
    assert plan["redis_trim_used"] is False
    assert plan["old_redis_writes"] is False
