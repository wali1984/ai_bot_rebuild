from __future__ import annotations

from v2.backend.app.services.live_gate.exchange_filter_sizing import ceil_to_step_size, min_executable_order


def test_ceil_to_step_size_rounds_up_for_btc_min_qty() -> None:
    assert str(ceil_to_step_size("0.0003914", "0.001")) == "0.001"


def test_min_executable_order_uses_step_size_and_min_qty() -> None:
    result = min_executable_order(
        mark_price="63870.97258842722",
        min_notional="50",
        min_qty="0.001",
        step_size="0.001",
    )
    assert result["ok"] is True
    assert result["min_executable_quantity"] == 0.001
    assert 63.87 < result["min_executable_notional"] < 63.88


def test_min_executable_order_blocks_missing_price() -> None:
    result = min_executable_order(mark_price=None, min_notional="50", min_qty="0.001", step_size="0.001")
    assert result["ok"] is False
    assert "MARK_PRICE_MISSING_OR_INVALID" in result["blockers"]
