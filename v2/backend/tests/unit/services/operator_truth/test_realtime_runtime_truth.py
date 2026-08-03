from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.operator_truth import realtime_runtime_truth as rt


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {
            "v2:paper:ledger": json.dumps({
                "paper_session_id": "paper_3000_test",
                "accepted": [],
                "held_by_paper_fill_gate": [{"symbol": "BTCUSDT"}],
                "shadow_observations": [],
            }),
            "v2:portfolio:state": json.dumps({
                "paper_session_id": "paper_3000_test",
                "initial_capital": 10000.0,
                "cash_balance": 10000.0,
                "equity": 10000.0,
                "total_pnl_usd": 0.0,
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_usd": 0.0,
                "open_positions_count": 0,
            }),
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        return iter([])


def test_minus_49_from_old_paper_online_is_not_current_session(tmp_path: Path, monkeypatch) -> None:
    public = tmp_path / "v2/frontend/public"
    events = public / "operator_runtime/paper_online/latest/paper_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(json.dumps({"paper_realized_pnl": -49.345535}) + "\n", encoding="utf-8")
    monkeypatch.setattr(rt, "PUBLIC_ROOT", public)
    monkeypatch.setattr(rt, "REPO_ROOT", tmp_path)

    result = rt.build_paper_pnl_source_of_truth(FakeRedis())

    assert result["current_session_pnl"] == 0.0
    assert result["paper_session_id"] == "paper_3000_test"
    assert result["current_session_equity"] == 10000.0
    assert result["accepted_fill_count"] == 0
    assert result["paper_minus_49_classification"] == "STALE_OR_LIFETIME_PAPER_ONLINE_PNL_NOT_CURRENT_SESSION"
    assert result["fills_fabricated"] is False


def test_paper_pnl_source_of_truth_uses_canonical_portfolio_state(monkeypatch, tmp_path: Path) -> None:
    public = tmp_path / "v2/frontend/public"
    public.mkdir(parents=True)
    monkeypatch.setattr(rt, "PUBLIC_ROOT", public)
    monkeypatch.setattr(rt, "REPO_ROOT", tmp_path)
    fake = FakeRedis()
    portfolio = json.loads(fake.store["v2:portfolio:state"])
    portfolio.update({
        "equity": 3000.25,
        "realized_net_pnl_usd": 1.25,
        "clean_session_valid_realized_pnl_usd": 1.25,
        "realized_pnl_usd": -999.0,
        "unrealized_pnl_usd": 0.75,
        "total_pnl_usd": 2.0,
        "pnl_source_key": "v2:portfolio:state",
        "pnl_source_route": "/api/v2/portfolio",
        "pnl_source_type": "CANONICAL_CURRENT_SESSION_RUNTIME",
    })
    fake.store["v2:portfolio:state"] = json.dumps(portfolio)
    ledger = json.loads(fake.store["v2:paper:ledger"])
    ledger.update({"realized_pnl_usd": -999.0, "accepted": []})
    fake.store["v2:paper:ledger"] = json.dumps(ledger)

    result = rt.build_paper_pnl_source_of_truth(fake)

    assert result["current_session_pnl"] == 2.0
    assert result["current_session_equity"] == 3000.25
    assert result["realized_pnl"] == 1.25
    assert result["unrealized_pnl"] == 0.75
    assert result["pnl_source_redis_keys"] == ["v2:portfolio:state"]
    assert result["pnl_source_key"] == "v2:portfolio:state"
    assert result["pnl_source_route"] == "/api/v2/portfolio"
    assert result["pnl_source_type"] == "CANONICAL_CURRENT_SESSION_RUNTIME"
    assert result["pnl_lineage_context_redis_keys"] == ["v2:paper:ledger"]


def test_live_gate_display_state_never_enables_submit() -> None:
    result = rt.build_live_gate_runtime_display_state(
        runtime_truth={
            "generated_est": "2026-06-13T16:05:00-04:00",
            "live_gate": "enabled_operator_approved",
            "trader_state": "LIVE_ARMED_BALANCE_HOLD",
            "transport_state": "BINANCE_TRANSPORT_BOUND_BALANCE_HELD",
            "live_order_submit_allowed": True,
            "live_order_submit_blocker": None,
            "available_margin": 100.0,
            "required_initial_margin": 64.86,
            "accepted_live_symbols": ["BTCUSDT"],
            "live_execution_source_payload_age_seconds": 10.0,
            "live_execution_source_payload_fresh": True,
            "signed_account_snapshot": {"ok": True, "raw_credentials_exposed": False},
            "open_orders_snapshot": {"ok": True, "open_orders_count": 0},
            "position_mode_snapshot": {"ok": True, "dual_side_position": False},
            "symbol_filter_snapshot": {"filters": {"BTCUSDT": {"ok": True, "step_size": "0.001"}}},
            "selected_candidate_snapshot": {"symbol": "BTCUSDT", "quantity": 0.001},
        },
        previous_state={
            "accepted_risk_audit_id": "risk_audit",
            "accepted_symbols_audit_id": "symbol_audit",
            "final_approval_audit_id": "final_audit",
            "enable_audit_id": "enable_audit",
        },
    )

    assert result["live_gate"] == "enabled_operator_approved"
    assert result["live_order_submit_allowed"] is True
    assert result["trader_execution_enabled"] is False
    assert result["live_trading_enabled"] is False
    assert result["order_transport_submit_enabled"] is False
    assert result["places_real_order"] is False
    assert result["exchange_action_taken"] is False
    assert result["source_payload_fresh"] is True
    assert result["signed_account_snapshot"]["raw_credentials_exposed"] is False
    assert result["open_orders_snapshot"]["open_orders_count"] == 0
    assert result["symbol_filter_snapshot"]["filters"]["BTCUSDT"]["step_size"] == "0.001"


def test_current_live_execution_hold_uses_redis_live_gate_over_stale_signed_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public = tmp_path / "v2/frontend/public"
    signed_path = (
        public
        / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest/operator_dashboard_payload.json"
    )
    balance_path = (
        public
        / "v2_live_transport_balance_aware_hold_and_first_order_monitor/latest/operator_dashboard_payload.json"
    )
    signed_path.parent.mkdir(parents=True)
    balance_path.parent.mkdir(parents=True)
    signed_path.write_text(
        json.dumps({
            "live_gate": "enabled_operator_approved",
            "trader_state": "LIVE_ARMED_BALANCE_HOLD",
            "signed_read_classification": "NO_451_DETECTED",
            "blockers": ["INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"],
            "live_submit_allowed": True,
        }),
        encoding="utf-8",
    )
    balance_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(rt, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rt, "PUBLIC_ROOT", public)
    monkeypatch.setattr(rt, "SIGNED_READ_RECOVERED_PATH", signed_path)
    monkeypatch.setattr(rt, "BALANCE_HOLD_PATH", balance_path)

    result = rt._current_live_execution_hold(  # noqa: SLF001
        live_gate_state={
            "live_gate": "blocked_human_only",
            "operator_approved": False,
            "order_transport_submit_enabled": False,
        }
    )

    assert result["live_gate"] == "blocked_human_only"
    assert result["live_order_submit_allowed"] is False
    assert result["live_order_submit_blocker"] == "LIVE_GATE_NOT_ENABLED"
    assert "LIVE_GATE_NOT_ENABLED" in result["blockers"]


def test_current_live_execution_hold_marks_stale_signed_read_proof_not_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public = tmp_path / "v2/frontend/public"
    signed_dir = public / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest"
    monitor_dir = public / "v2_live_transport_balance_aware_hold_and_first_order_monitor/latest"
    signed_path = signed_dir / "operator_dashboard_payload.json"
    balance_path = monitor_dir / "operator_dashboard_payload.json"
    signed_dir.mkdir(parents=True)
    monitor_dir.mkdir(parents=True)
    signed_path.write_text(
        json.dumps({
            "live_gate": "enabled_operator_approved",
            "trader_state": "LIVE_ARMED_BALANCE_HOLD",
            "signed_read_classification": "NO_451_DETECTED",
            "critical_account_read_gate": "CRITICAL_ACCOUNT_READ_GATE_READY",
            "blockers": ["INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"],
            "live_submit_allowed": True,
            "available_margin": 0.0,
        }),
        encoding="utf-8",
    )
    balance_path.write_text(json.dumps({}), encoding="utf-8")
    (signed_dir / "account_margin_balance_hold_status.json").write_text(
        json.dumps({
            "generated_est": "2026-01-01T00:00:00-05:00",
            "status": "LIVE_ARMED_BALANCE_HOLD",
            "available_margin": 0.0,
        }),
        encoding="utf-8",
    )
    (monitor_dir / "open_orders_snapshot_status.json").write_text(
        json.dumps({"status": "OPEN_ORDERS_READ_OK", "ok": True, "open_orders_count": 0}),
        encoding="utf-8",
    )
    (monitor_dir / "live_symbol_min_executable_map.json").write_text(
        json.dumps({
            "status": "LIVE_SYMBOL_MIN_EXECUTABLE_BALANCE_HOLD",
            "rows": [
                {
                    "symbol": "BTCUSDT",
                    "filter_status": {"ok": True, "symbol": "BTCUSDT", "step_size": "0.001", "tick_size": "0.10"},
                }
            ],
        }),
        encoding="utf-8",
    )
    (monitor_dir / "live_order_transport_pre_submit_evaluation_status.json").write_text(
        json.dumps({"position_mode_status": {"ok": True, "dual_side_position": False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rt, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rt, "PUBLIC_ROOT", public)
    monkeypatch.setattr(rt, "SIGNED_READ_RECOVERED_PATH", signed_path)
    monkeypatch.setattr(rt, "BALANCE_HOLD_PATH", balance_path)
    monkeypatch.setattr(rt, "_age_seconds", lambda path: 7200.0 if path == signed_path else 10.0)

    result = rt._current_live_execution_hold(  # noqa: SLF001
        live_gate_state={
            "live_gate": "enabled_operator_approved",
            "operator_approved": True,
            "order_transport_submit_enabled": True,
        }
    )

    assert result["source_payload_fresh"] is False
    assert result["critical_account_read_gate"] == "CRITICAL_ACCOUNT_READ_GATE_STALE"
    assert result["live_order_submit_allowed"] is False
    assert result["binance_private_execution"] == "SIGNED_READ_SOURCE_STALE"
    assert "LIVE_SIGNED_READ_SOURCE_STALE" in result["blockers"]
    assert result["signed_account_snapshot"]["ok"] is False
    assert result["signed_account_snapshot"]["last_known_signed_account_read_ok"] is True
    assert result["signed_account_snapshot"]["fresh"] is False
    assert result["open_orders_snapshot"]["open_orders_count"] == 0
    assert result["symbol_filter_snapshot"]["filters"]["BTCUSDT"]["step_size"] == "0.001"
