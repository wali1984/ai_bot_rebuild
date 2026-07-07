from __future__ import annotations

import json

from v2.backend.app.cli import v2_portfolio_state_publisher as publisher
from v2.backend.app.services.paper_accounting.mark_to_market import build_accounting_state


class FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = {key: json.dumps(value) for key, value in values.items()}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        return iter([])


def test_accepted_fill_recomputes_equity_from_current_market_price(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:live_gate:state": {
                "live_gate": "enabled_operator_approved",
                "trader_execution_enabled": True,
                "live_symbols": ["BTCUSDT"],
            },
            "v2:trader:execution_state": {"trader_execution_enabled": True},
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [
                    {
                        "intent_id": "intent-1",
                        "signal_id": "signal-1",
                        "source_prediction_id": "prediction-1",
                        "risk_decision_id": "risk-1",
                        "orchestrator_decision_id": "orch-1",
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "fill_price": 100.0,
                        "quantity": 2.0,
                        "notional": 200.0,
                    }
                ],
                "held_by_paper_fill_gate": [{"intent_id": "held-1", "symbol": "ETHUSDT"}],
                "accepted_count": 1,
                "held_by_paper_fill_gate_count": 1,
                "shadow_observation_count": 0,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "110.0"},
                "fetched_utc": "2026-06-08T21:00:05Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_EQUITY_OK"
    assert result["accepted_fill_total"] == 1
    assert result["held_by_paper_fill_gate_total"] == 1
    assert result["open_positions_count"] == 1
    assert result["order_counters"] == {
        "paper_accepted_intent_count": 1,
        "paper_accepted_fill_count": 1,
        "paper_accepted_fill_raw_count": 1,
        "paper_invalid_admission_accepted_count": 0,
        "paper_economic_fill_count": 1,
        "paper_non_economic_fill_count": 0,
        "paper_held_intent_count": 1,
        "paper_blocked_intent_count": 0,
        "paper_shadow_observation_count": 0,
        "paper_open_position_count": 1,
        "paper_closed_position_count": 0,
        "paper_closed_position_raw_count": 0,
        "paper_invalid_admission_closed_count": 0,
        "live_order_count": 0,
        "test_order_count": 0,
        "exchange_order_mutation_count": 0,
    }
    assert result["order_counters_source"] == "v2:paper:ledger + v2:paper:closed_trades"
    assert result["unrealized_pnl_usd"] == 20.0
    assert result["equity"] == 10020.0
    assert result["live_gate_status"] == "enabled_operator_approved"
    assert result["positions"][0]["position_state"] == "accepted_paper_fill_open"
    assert all(row.get("open_position") is not True for row in result["positions"][1:])


def test_no_accepted_fills_reports_no_open_position_without_fabricating_pnl(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [],
                "held_by_paper_fill_gate": [{"intent_id": "held-1", "symbol": "ETHUSDT"}],
                "accepted_count": 0,
                "held_by_paper_fill_gate_count": 1,
                "shadow_observation_count": 0,
            }
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_NO_ACCEPTED_FILLS"
    assert result["accepted_fill_total"] == 0
    assert result["open_positions_count"] == 0
    assert result["unrealized_pnl_usd"] == 0.0
    assert result["equity"] == 10000.0
    assert result["paper_equity_reason"] == "NO_ACCEPTED_PAPER_FILL_IN_CURRENT_V2_LEDGER"


def test_no_accepted_fills_uses_reset_session_initial_capital(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:paper:session": {
                "initial_capital": 3000.0,
                "starting_equity_usd": 3000.0,
                "paper_session_id": "paper_3000_final_pre_live_test",
                "reset_session_id": "paper_3000_final_pre_live_test",
            },
            "v2:portfolio:state": {
                "reset_session_id": "paper_3000_final_pre_live_test",
            },
            "v2:paper:ledger": {
                "generated_utc": "2026-07-05T00:00:00Z",
                "accepted": [],
                "accepted_count": 0,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["initial_capital"] == 3000.0
    assert result["starting_equity_usd"] == 3000.0
    assert result["equity"] == 3000.0
    assert result["current_session_equity"] == 3000.0
    assert result["equity_change_since_last"] == 0.0
    assert result["paper_session_id"] == "paper_3000_final_pre_live_test"


def test_invalid_admission_rows_are_excluded_from_clean_session_equity(monkeypatch, tmp_path):
    session_id = "paper_3000_final_pre_live_test"
    fake = FakeRedis(
        {
            "v2:paper:session": {
                "initial_capital": 3000.0,
                "starting_equity_usd": 3000.0,
                "paper_session_id": session_id,
                "reset_session_id": session_id,
            },
            "v2:paper:ledger": {
                "generated_utc": "2026-07-05T00:00:00Z",
                "paper_session_id": session_id,
                "starting_equity_usd": 3000.0,
                "accepted": [
                    {
                        "fill_id": "fill-blocked",
                        "intent_id": "fill-blocked",
                        "prediction_id": "pred-blocked",
                        "symbol": "CRVUSDT",
                        "side": "short",
                        "fill_price": 0.2131,
                        "quantity": 100.0,
                        "entry_gate_block_reasons": [
                            "REGIME_GATE_CASCADE_CONTEXT_SHADOW_ONLY:short:trend_mode:CRVUSDT:15m"
                        ],
                    }
                ],
                "closed_trades": [
                    {
                        "close_id": "close-blocked",
                        "symbol": "CRVUSDT",
                        "source_fill_ids": ["fill-blocked"],
                        "realized_pnl_usd": -0.95,
                    }
                ],
                "accepted_count": 1,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
            "v2:paper:closed_trades": [
                {
                    "close_id": "close-blocked",
                    "symbol": "CRVUSDT",
                    "source_fill_ids": ["fill-blocked"],
                    "realized_pnl_usd": -0.95,
                }
            ],
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == (
        "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_INVALID_ADMISSIONS_EXCLUDED"
    )
    assert result["accepted_fill_total"] == 0
    assert result["accepted_fill_raw_total"] == 1
    assert result["invalid_admission_accepted_excluded"] == 1
    assert result["closed_positions_count"] == 0
    assert result["closed_positions_raw_count"] == 1
    assert result["invalid_admission_closed_trades_excluded"] == 1
    assert result["realized_pnl_usd"] == 0.0
    assert result["clean_session_valid_equity_usd"] == 3000.0
    assert result["equity"] == 3000.0
    assert result["current_session_equity"] == 3000.0
    assert result["raw_realized_pnl_including_invalid_admissions_usd"] == -0.95
    assert result["raw_equity_including_invalid_admissions_usd"] == 2999.05
    assert result["contains_quarantined_positions"] is True
    assert result["equity_trusted"] is True
    assert result["pnl_trusted"] is True


def test_closed_trade_ledger_realized_pnl_is_included_in_equity(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:portfolio:state": {
                "equity": 10100.0,
                "equity_high_water_mark": 10100.0,
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_usd": 0.0,
            },
            "v2:paper:closed_trades": [
                {
                    "close_id": "close-win",
                    "symbol": "BTCUSDT",
                    "realized_pnl_usd": 25.0,
                },
                {
                    "close_id": "close-loss",
                    "symbol": "ETHUSDT",
                    "realized_pnl_usd": -2.77,
                },
            ],
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["realized_pnl_usd"] == 22.23
    assert result["closed_ledger_net_pnl_usd"] == 22.23
    assert result["portfolio_realized_matches_closed_ledger"] is True
    assert result["equity"] == 10022.23
    assert result["equity_reconciles_within_1_cent"] is True
    assert result["equity_high_water_mark"] == 10100.0
    assert result["current_drawdown_bps"] > 0.0


def test_paper_accounting_fixture_moves_equity_with_mark_price() -> None:
    state = build_accounting_state(
        [
            {
                "intent_id": "intent-btc",
                "signal_id": "signal-btc",
                "prediction_id": "prediction-btc",
                "risk_decision_id": "risk-btc",
                "orchestrator_decision_id": "orch-btc",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.001,
                "fill_price": 60000.0,
            }
        ],
        [],
        {"BTCUSDT": (60100.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert state["economic_fill_count"] == 1
    assert state["open_positions_count"] == 1
    assert state["unrealized_pnl"] == 0.1
    assert state["current_session_equity"] == 10000.1
    fill = state["inventory"][0]
    assert fill["fill_price"] == 60000.0
    assert fill["mark_price_at_fill"] == 60000.0
    assert fill["current_mark_price"] == 60100.0

    closed = build_accounting_state(
        [
            {
                "intent_id": "intent-btc-open",
                "signal_id": "signal-btc-open",
                "prediction_id": "prediction-btc-open",
                "risk_decision_id": "risk-btc-open",
                "orchestrator_decision_id": "orch-btc-open",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.001,
                "fill_price": 60000.0,
            },
            {
                "intent_id": "intent-btc-close",
                "signal_id": "signal-btc-close",
                "prediction_id": "prediction-btc-close",
                "risk_decision_id": "risk-btc-close",
                "orchestrator_decision_id": "orch-btc-close",
                "symbol": "BTCUSDT",
                "side": "SELL",
                "quantity": 0.001,
                "fill_price": 60100.0,
            },
        ],
        [],
        {"BTCUSDT": (60100.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert closed["economic_fill_count"] == 2
    assert closed["open_positions_count"] == 0
    assert closed["realized_pnl"] == 0.1
    assert closed["unrealized_pnl"] == 0.0
    assert closed["current_session_equity"] == 10000.1


def test_closed_trade_ledger_is_authoritative_when_reconstructed_close_fill_overlaps() -> None:
    state = build_accounting_state(
        [
            {
                "intent_id": "intent-btc-open",
                "signal_id": "signal-btc-open",
                "prediction_id": "prediction-btc-open",
                "risk_decision_id": "risk-btc-open",
                "orchestrator_decision_id": "orch-btc-open",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 10.0,
            },
            {
                "intent_id": "intent-btc-close",
                "signal_id": "signal-btc-close",
                "prediction_id": "prediction-btc-close",
                "risk_decision_id": "risk-btc-close",
                "orchestrator_decision_id": "orch-btc-close",
                "symbol": "BTCUSDT",
                "side": "SELL",
                "quantity": 1.0,
                "fill_price": 11.0,
            },
        ],
        [{"close_id": "close-btc", "symbol": "BTCUSDT", "realized_pnl_usd": 1.0}],
        {"BTCUSDT": (11.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert state["reconstructed_fill_realized_pnl"] == 1.0
    assert state["reconstructed_fill_realized_pnl_suppressed"] == 1.0
    assert state["realized_pnl_source"] == "explicit_closed_trade_ledger"
    assert state["closed_ledger_net_pnl"] == 1.0
    assert state["realized_pnl"] == 1.0
    assert state["current_session_equity"] == 10001.0
    assert state["closed_ledger_matches_portfolio_realized"] is True


def test_closed_trade_source_ids_remove_accepted_fill_from_open_inventory() -> None:
    state = build_accounting_state(
        [
            {
                "intent_id": "intent-btc",
                "signal_id": "signal-btc",
                "prediction_id": "prediction-btc",
                "risk_decision_id": "risk-btc",
                "orchestrator_decision_id": "orch-btc",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 10.0,
            }
        ],
        [
            {
                "close_id": "close-btc",
                "symbol": "BTCUSDT",
                "source_fill_ids": ["intent-btc"],
                "realized_pnl_usd": 1.0,
            }
        ],
        {"BTCUSDT": (20.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert state["accepted_fill_count"] == 1
    assert state["active_accepted_fill_count"] == 0
    assert state["accepted_closed_filter_count"] == 1
    assert state["open_positions_count"] == 0
    assert state["unrealized_pnl"] == 0.0
    assert state["realized_pnl"] == 1.0
    assert state["current_session_equity"] == 10001.0


def test_portfolio_publisher_does_not_double_count_closed_trade_ledger(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [
                    {
                        "intent_id": "intent-btc-open",
                        "signal_id": "signal-btc-open",
                        "prediction_id": "prediction-btc-open",
                        "risk_decision_id": "risk-btc-open",
                        "orchestrator_decision_id": "orch-btc-open",
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1.0,
                        "fill_price": 10.0,
                    },
                    {
                        "intent_id": "intent-btc-close",
                        "signal_id": "signal-btc-close",
                        "prediction_id": "prediction-btc-close",
                        "risk_decision_id": "risk-btc-close",
                        "orchestrator_decision_id": "orch-btc-close",
                        "symbol": "BTCUSDT",
                        "side": "SELL",
                        "quantity": 1.0,
                        "fill_price": 11.0,
                    },
                ],
                "closed_trades": [
                    {
                        "close_id": "close-btc",
                        "symbol": "BTCUSDT",
                        "realized_pnl_usd": 1.0,
                    }
                ],
                "accepted_count": 2,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "11.0"},
                "fetched_utc": "2026-06-08T21:00:05Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["closed_ledger_net_pnl_usd"] == 1.0
    assert result["realized_pnl_usd"] == 1.0
    assert result["portfolio_realized_matches_closed_ledger"] is True
    assert result["equity"] == 10001.0


def test_portfolio_publisher_resets_stale_high_water_after_closed_fill_suppression(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:portfolio:state": {
                "equity": 14000.0,
                "equity_high_water_mark": 14000.0,
                "open_positions_count": 1,
            },
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [
                    {
                        "intent_id": "intent-btc",
                        "signal_id": "signal-btc",
                        "prediction_id": "prediction-btc",
                        "risk_decision_id": "risk-btc",
                        "orchestrator_decision_id": "orch-btc",
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1.0,
                        "fill_price": 10.0,
                    }
                ],
                "closed_trades": [
                    {
                        "close_id": "close-btc",
                        "symbol": "BTCUSDT",
                        "source_fill_ids": ["intent-btc"],
                        "realized_pnl_usd": 1.0,
                    }
                ],
                "accepted_count": 1,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "20.0"},
                "fetched_utc": "2026-06-08T21:00:05Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_CLOSED_ONLY"
    assert result["active_accepted_fill_total"] == 0
    assert result["accepted_fills_suppressed_by_closed_ledger_count"] == 1
    assert result["open_positions_count"] == 0
    assert result["unrealized_pnl_usd"] == 0.0
    assert result["equity"] == 10001.0
    assert result["equity_high_water_mark"] == 10001.0
    assert result["current_drawdown_bps"] == 0.0
    assert result["equity_high_water_mark_reset_reason"] == (
        "RESET_STALE_HIGH_WATER_AFTER_CLOSED_LEDGER_SUPPRESSED_PHANTOM_OPEN_INVENTORY"
    )


def test_portfolio_publisher_respects_authoritative_zero_open_ledger(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": "2026-07-06T01:40:00Z",
                "accepted": [
                    {
                        "intent_id": "intent-btc",
                        "signal_id": "signal-btc",
                        "prediction_id": "prediction-btc",
                        "risk_decision_id": "risk-btc",
                        "orchestrator_decision_id": "orch-btc",
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1.0,
                        "fill_price": 10.0,
                    }
                ],
                "open_position_count": 0,
                "open_positions": [],
                "positions_by_symbol": {},
                "closed_trades": [
                    {
                        "close_id": "close-btc",
                        "symbol": "BTCUSDT",
                        "realized_pnl_usd": 1.0,
                    }
                ],
                "accepted_count": 1,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "20.0"},
                "fetched_utc": "2026-07-06T01:40:05Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_CLOSED_ONLY"
    assert result["ledger_authoritative_no_open_positions"] is True
    assert result["accepted_fills_suppressed_by_authoritative_open_ledger_count"] == 1
    assert result["open_positions_count"] == 0
    assert result["unrealized_pnl_usd"] == 0.0
    assert result["equity"] == 10001.0
    assert result["ledger_to_portfolio_status"] == "LEDGER_TO_PORTFOLIO_CLOSED_ONLY"


def test_portfolio_publisher_resets_stale_high_water_with_remaining_active_fill(monkeypatch, tmp_path):
    fake = FakeRedis(
        {
            "v2:portfolio:state": {
                "equity": 14000.0,
                "equity_high_water_mark": 14000.0,
                "open_positions_count": 2,
            },
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [
                    {
                        "intent_id": "intent-closed",
                        "signal_id": "signal-closed",
                        "prediction_id": "prediction-closed",
                        "risk_decision_id": "risk-closed",
                        "orchestrator_decision_id": "orch-closed",
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "quantity": 1.0,
                        "fill_price": 10.0,
                    },
                    {
                        "intent_id": "intent-open",
                        "signal_id": "signal-open",
                        "prediction_id": "prediction-open",
                        "risk_decision_id": "risk-open",
                        "orchestrator_decision_id": "orch-open",
                        "symbol": "ETHUSDT",
                        "side": "BUY",
                        "quantity": 1.0,
                        "fill_price": 20.0,
                    },
                ],
                "closed_trades": [
                    {
                        "close_id": "close-btc",
                        "symbol": "BTCUSDT",
                        "source_fill_ids": ["intent-closed"],
                        "realized_pnl_usd": 1.0,
                    }
                ],
                "accepted_count": 2,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "20.0"},
                "fetched_utc": "2026-06-08T21:00:05Z",
            },
            "v2:market:prices:ETHUSDT": {
                "ticker_24hr": {"lastPrice": "20.0"},
                "fetched_utc": "2026-06-08T21:00:05Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["active_accepted_fill_total"] == 1
    assert result["accepted_fills_suppressed_by_closed_ledger_count"] == 1
    assert result["open_positions_count"] == 1
    assert result["equity"] == 10001.0
    assert result["equity_high_water_mark"] == 10001.0
    assert result["current_drawdown_bps"] == 0.0


def test_missing_quantity_and_lineage_are_non_economic_fill() -> None:
    state = build_accounting_state(
        [
            {
                "intent_id": "intent-btc",
                "source_prediction_id": "prediction-btc",
                "symbol": "BTCUSDT",
                "side": "long",
                "fill_price": 60000.0,
            }
        ],
        [],
        {"BTCUSDT": (60100.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert state["accepted_fill_count"] == 1
    assert state["economic_fill_count"] == 0
    assert state["ledger_to_position_status"] == "FILL_TO_POSITION_PIPE_BROKEN"
    blocker = state["non_economic_fill_blockers"][0]
    assert "MISSING_QTY" in blocker["missing_fields"]
    assert "MISSING_RISK_DECISION_ID" in blocker["missing_fields"]
