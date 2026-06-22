from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.operator_truth import realtime_runtime_truth as rt


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {
            "v2:paper:ledger": json.dumps({
                "accepted": [],
                "held_by_paper_fill_gate": [{"symbol": "BTCUSDT"}],
                "shadow_observations": [],
            }),
            "v2:portfolio:state": json.dumps({
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
    assert result["current_session_equity"] == 10000.0
    assert result["accepted_fill_count"] == 0
    assert result["paper_minus_49_classification"] == "STALE_OR_LIFETIME_PAPER_ONLINE_PNL_NOT_CURRENT_SESSION"
    assert result["fills_fabricated"] is False


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
