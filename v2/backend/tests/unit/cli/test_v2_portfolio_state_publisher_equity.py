from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_portfolio_state_publisher as publisher
from v2.backend.app.services.paper_accounting.mark_to_market import build_accounting_state


class FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = {key: json.dumps(value) for key, value in values.items()}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        return iter([])


def _parse_utc(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_runtime_repo_root_can_be_separate_from_immutable_code(tmp_path) -> None:
    code_root = Path("/immutable/release")

    assert publisher._configured_repo_root(  # noqa: SLF001
        {publisher.PORTFOLIO_RUNTIME_REPO_ROOT_ENV: str(tmp_path)},
        code_root=code_root,
    ) == tmp_path.resolve()
    assert publisher._configured_repo_root({}, code_root=code_root) == code_root  # noqa: SLF001


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
                "open_positions": [
                    {
                        "position_id": "paper_pos_btc",
                        "entry_fill_id": "intent-1",
                        "source_fill_ids": ["intent-1"],
                        "symbol": "BTCUSDT",
                        "side": "long",
                            "net_quantity": 2.0,
                            "avg_entry_price": 100.0,
                            "effective_leverage": 4.0,
                            "maintenance_margin_rate": 0.005,
                            "current_capital_accounting": {
                                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                                "effective_leverage": 4.0,
                                "effective_leverage_validated": True,
                                "maintenance_margin_rate": 0.005,
                            },
                            # Stale upstream field must not override 200 / 4.
                        "allocated_margin_usd": 1.0,
                    }
                ],
                "open_position_count": 1,
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
    assert result["wallet_balance"] == 10000.0
    assert result["used_margin_usd"] == pytest.approx(50.0)
    assert result["available_margin"] == pytest.approx(9950.0)
    assert result["paper_account_margin_status"]["invariant_holds"] is True
    assert result["paper_account_margin_status"]["source"] == (
        "V2_PAPER_LEDGER_OPEN_POSITIONS"
    )
    assert result["paper_account_margin_status"]["generated_utc"] == result[
        "generated_utc"
    ]
    assert result["live_gate_status"] == "enabled_operator_approved"
    assert result["positions"][0]["position_state"] == "accepted_paper_fill_open"
    assert all(row.get("open_position") is not True for row in result["positions"][1:])


def _proof_backed_aave_ledger(*, mutate_proof: bool = False) -> dict[str, object]:
    position = {
        "position_id": "paper_pos_AAVEUSDT_generation",
        "position_generation_id": "generation-aave",
        "entry_fill_id": "fill-aave",
        "source_fill_ids": ["fill-aave"],
        "prediction_id": "prediction-aave",
        "signal_id": "signal-aave",
        "orchestrator_decision_id": "decision-aave",
        "risk_decision_id": "risk-aave",
        "allocation_id": "allocation-aave",
        "symbol": "AAVEUSDT",
        "timeframe": "4h",
        "side": "short",
        "net_quantity": 0.5,
        "avg_entry_price": 97.03,
        "gross_notional_usd": 48.515,
        "effective_leverage": 1.0,
        "maintenance_margin_rate": 0.01,
        "current_capital_accounting": {
            "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
            "effective_leverage": 1.0,
            "effective_leverage_validated": True,
            "maintenance_margin_rate": 0.01,
        },
        "allocated_margin_usd": 48.515,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    proof = {
        "schema_version": "paper_open_position_fill_proof_v1",
        "proof_origin": "CURRENT_CYCLE_FINAL_ADMISSION_PASS",
        "proof_created_at": "2026-07-28T01:27:29.501011Z",
        "fill_id": "fill-aave",
        "ledger_row_id": "fill-aave",
        "position_id": position["position_id"],
        "position_generation_id": position["position_generation_id"],
        "prediction_id": position["prediction_id"],
        "signal_id": position["signal_id"],
        "intent_id": "intent-aave",
        "orchestrator_decision_id": position["orchestrator_decision_id"],
        "risk_decision_id": position["risk_decision_id"],
        "allocation_id": position["allocation_id"],
        "adaptive_policy_action_id": "action-aave",
        "symbol": "AAVEUSDT",
        "timeframe": "4h",
        "side": "short",
        "quantity": 0.5,
        "fill_price": 97.03,
        "gross_notional_usd": 48.515,
        "effective_leverage": 1.0,
        "allocated_margin_usd": 48.515,
        "paper_final_admission_status": "PASS",
        "paper_final_admission_receipt_hash": "a" * 64,
        "paper_final_admission_bound_material_hash": "b" * 64,
        "paper_persisted_ledger_contract_hash": "c" * 64,
        "paper_cycle_reservation_commit_receipt_hash": "d" * 64,
        "adaptive_policy_action_sha256": "e" * 64,
        "adaptive_paper_policy_authorization_sha256": "f" * 64,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    proof["proof_id"] = publisher._canonical_sha256(proof)  # noqa: SLF001
    if mutate_proof:
        proof["quantity"] = 0.6
    proofs = [proof]
    proof_status = {
        "schema_version": "paper_open_position_fill_proof_status_v1",
        "status": "PASS",
        "input_open_position_count": 1,
        "proof_count": 1,
        "proofs_sha256": publisher._canonical_sha256(proofs),  # noqa: SLF001
        "one_proof_per_open_position": True,
    }
    return {
        "generated_utc": "2026-07-28T01:30:00Z",
        "paper_session_id": "paper-session-aave",
        "starting_equity_usd": 3000.0,
        "initial_capital": 3000.0,
        "accepted": [],
        "accepted_count": 0,
        "open_positions": [position],
        "open_position_count": 1,
        "open_position_fill_proofs": proofs,
        "paper_open_position_fill_proof_status": proof_status,
        "closed_trades": [],
        "held_by_paper_fill_gate_count": 0,
        "shadow_observation_count": 0,
    }


def test_compacted_fill_uses_hash_valid_durable_open_position_proof(
    monkeypatch,
    tmp_path,
) -> None:
    fake = FakeRedis(
        {
            "v2:paper:session": {
                "initial_capital": 3000.0,
                "starting_equity_usd": 3000.0,
                "paper_session_id": "paper-session-aave",
            },
            "v2:paper:ledger": _proof_backed_aave_ledger(),
            "v2:market:prices:AAVEUSDT": {
                "ticker_24hr": {"lastPrice": "97.41"},
                "fetched_utc": "2026-07-28T01:30:01Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "portfolio.json")

    result = publisher.run_once(write_redis=False)

    assert result["open_position_fill_proof_accounting_status"]["status"] == "PASS"
    assert result["open_position_fill_proof_accounting_status"][
        "one_proof_per_open_position"
    ] is True
    assert result["accepted_fill_total"] == 1
    assert result["open_positions_count"] == 1
    assert result["unrealized_pnl_usd"] == pytest.approx(-0.19)
    assert result["wallet_balance"] == 3000.0
    assert result["equity"] == pytest.approx(2999.81)
    assert result["used_margin_usd"] == 48.515
    assert result["paper_account_margin_status"]["status"] == "PASS"


def test_mutated_durable_open_position_proof_never_authorizes_pnl(
    monkeypatch,
    tmp_path,
) -> None:
    fake = FakeRedis(
        {
            "v2:paper:ledger": _proof_backed_aave_ledger(mutate_proof=True),
            "v2:market:prices:AAVEUSDT": {
                "ticker_24hr": {"lastPrice": "97.41"},
                "fetched_utc": "2026-07-28T01:30:01Z",
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "portfolio.json")

    result = publisher.run_once(write_redis=False)

    proof_status = result["open_position_fill_proof_accounting_status"]
    assert proof_status["status"] == "BLOCKED"
    assert "OPEN_POSITION_FILL_PROOF_HASH_INVALID:paper_pos_AAVEUSDT_generation" in (
        proof_status["rejection_reasons"]
    )
    assert result["accepted_fill_total"] == 0
    assert result["unrealized_pnl_usd"] == 0.0
    assert result["equity_trusted"] is False


def test_future_ledger_clock_blocks_portfolio_time_contract(monkeypatch, tmp_path) -> None:
    fake = FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": "2099-01-01T00:00:00Z",
                "accepted": [],
                "open_positions": [],
                "accepted_count": 0,
            }
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["portfolio_state_time_contract_status"] == "BLOCKED"
    assert result["source_event_time"] is None
    assert result["event_time"] is None
    assert result["portfolio_state_time_contract_rejection_reasons"] == [
        "PAPER_LEDGER_GENERATED_AFTER_PORTFOLIO_STATE"
    ]


def test_portfolio_clock_contract_orders_source_generated_and_available(
    monkeypatch,
    tmp_path,
) -> None:
    fake = FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": "2026-06-08T21:00:00Z",
                "accepted": [],
                "open_positions": [],
                "accepted_count": 0,
            }
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["portfolio_state_time_contract_status"] == "PASS"
    assert result["source_event_time"] == "2026-06-08T21:00:00.000Z"
    assert result["source_event_time"] == result["event_time"]
    assert result["producer_generated_at"] == result["generated_at"]
    assert result["record_available_at"] == result["available_at"]
    assert _parse_utc(result["source_event_time"]) <= _parse_utc(
        result["producer_generated_at"]
    ) <= _parse_utc(result["record_available_at"])


def test_missing_mark_price_marks_portfolio_untrusted_and_preserves_session(
    monkeypatch,
    tmp_path,
):
    session_id = "paper_3000_current"
    fake = FakeRedis(
        {
            "v2:paper:session": {
                "initial_capital": 3000.0,
                "starting_equity_usd": 3000.0,
                "paper_session_id": session_id,
                "reset_session_id": session_id,
            },
            "v2:paper:ledger": {
                "generated_utc": "2026-07-07T05:00:00Z",
                "paper_session_id": session_id,
                "accepted": [
                    {
                        "fill_id": "paper_pos_bas",
                        "intent_id": "paper_pos_bas",
                        "signal_id": "signal-bas",
                        "prediction_id": "prediction-bas",
                        "risk_decision_id": "risk-bas",
                        "orchestrator_decision_id": "orch-bas",
                        "symbol": "BASUSDT",
                        "side": "long",
                        "fill_price": 0.030994,
                        "quantity": 366.275065325735,
                        "notional": 11.352,
                        "paper_session_id": session_id,
                        "session_id": session_id,
                        "reset_session_id": session_id,
                        "starting_equity_usd": 3000.0,
                    }
                ],
                "accepted_count": 1,
                "held_by_paper_fill_gate_count": 0,
                "shadow_observation_count": 0,
            },
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["classification"] == "PORTFOLIO_STATE_CURRENT_PAPER_LEDGER_MARK_PRICE_MISSING"
    assert result["paper_zero_pnl_reason"] == "MARK_PRICE_MISSING"
    assert result["paper_equity_reason"] == "MARK_PRICE_MISSING"
    assert result["equity_trusted"] is False
    assert result["pnl_trusted"] is False
    assert result["reason_if_untrusted"] == "MARK_PRICE_MISSING_FOR_OPEN_POSITION"
    assert result["open_positions_count"] == 1
    assert result["open_positions"][0]["symbol"] == "BASUSDT"
    assert result["open_positions"][0]["paper_session_id"] == session_id
    assert result["mark_price_blockers"][0]["symbol"] == "BASUSDT"
    assert result["mark_price_blockers"][0]["paper_session_id"] == session_id
    assert result["pnl_blockers"][0]["classification"] == "MARK_PRICE_MISSING"


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


def test_p0019_portfolio_equity_uses_net_closed_pnl_when_gross_alias_exists(
    monkeypatch,
    tmp_path,
):
    fake = FakeRedis(
        {
            "v2:paper:session": {
                "initial_capital": 3000.0,
                "starting_equity_usd": 3000.0,
                "paper_session_id": "paper_3000_p0019",
                "reset_session_id": "paper_3000_p0019",
            },
            "v2:paper:closed_trades": [
                {
                    "close_id": "close-win-after-cost",
                    "symbol": "BTCUSDT",
                    "realized_pnl_usd": 1.0,
                    "realized_pnl": 1.0,
                    "realized_net_pnl_usd": 0.73,
                },
                {
                    "close_id": "close-loss-after-cost",
                    "symbol": "ETHUSDT",
                    "realized_pnl_usd": -0.5,
                    "realized_pnl": -0.5,
                    "realized_net_pnl_usd": -0.98,
                },
            ],
        }
    )
    monkeypatch.setattr(publisher, "_connect_redis", lambda: fake)
    monkeypatch.setattr(publisher, "PAYLOAD_PATH", tmp_path / "v2_portfolio_state.json")

    result = publisher.run_once(write_redis=False)

    assert result["realized_pnl_usd"] == -0.25
    assert result["realized_net_pnl_usd"] == -0.25
    assert result["realized_gross_pnl_usd"] == 0.5
    assert result["total_pnl_usd"] == -0.25
    assert result["closed_ledger_net_pnl_usd"] == -0.25
    assert result["portfolio_realized_matches_closed_ledger"] is True
    assert result["equity"] == 2999.75
    assert result["equity_reconciles_within_1_cent"] is True


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


def test_p0019_accounting_state_uses_net_closed_pnl_when_gross_alias_exists() -> None:
    state = build_accounting_state(
        [],
        [
            {
                "close_id": "close-btc",
                "symbol": "BTCUSDT",
                "realized_pnl_usd": 1.0,
                "realized_pnl": 1.0,
                "realized_net_pnl_usd": 0.73,
            },
            {
                "close_id": "close-eth",
                "symbol": "ETHUSDT",
                "realized_pnl_usd": -0.5,
                "realized_pnl": -0.5,
                "realized_net_pnl_usd": -0.98,
            },
        ],
        {},
        initial_capital=3000.0,
    )

    assert state["closed_ledger_net_pnl"] == -0.25
    assert state["realized_pnl"] == -0.25
    assert state["current_session_equity"] == 2999.75


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


def test_closed_generation_filter_keeps_later_reopen_with_reused_ids() -> None:
    common = {
        "intent_id": "reused-intent",
        "signal_id": "reused-signal",
        "prediction_id": "reused-prediction",
        "risk_decision_id": "reused-risk",
        "orchestrator_decision_id": "reused-orchestrator",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 1.0,
    }
    state = build_accounting_state(
        [
            {
                **common,
                "fill_price": 10.0,
                "generated_utc": "2026-06-11T10:00:00Z",
            },
            {
                **common,
                "fill_price": 12.0,
                "generated_utc": "2026-06-11T10:06:00Z",
            },
        ],
        [
            {
                "close_id": "first-generation-close",
                "symbol": "BTCUSDT",
                "side": "long",
                "source_fill_ids": ["reused-intent"],
                "entry_signal_id": "reused-signal",
                "entry_prediction_id": "reused-prediction",
                "entry_time": "2026-06-11T10:00:00Z",
                "exit_time": "2026-06-11T10:05:00Z",
                "realized_pnl_usd": 1.0,
            }
        ],
        {"BTCUSDT": (13.0, "TEST_MARK_PRICE", 1.0)},
        initial_capital=10000.0,
    )

    assert state["accepted_fill_count"] == 2
    assert state["accepted_closed_filter_count"] == 1
    assert state["active_accepted_fill_count"] == 1
    assert state["open_positions_count"] == 1
    assert state["unrealized_pnl"] == pytest.approx(1.0)
    assert state["current_session_equity"] == pytest.approx(10002.0)
    assert state["accepted_closed_filter_sample"][0][
        "closed_generation_match_type"
    ] in {
        "DERIVED_ENTRY_GENERATION_ID",
        "LEGACY_STRONG_ID_WITH_TEMPORAL_EVIDENCE",
    }


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
