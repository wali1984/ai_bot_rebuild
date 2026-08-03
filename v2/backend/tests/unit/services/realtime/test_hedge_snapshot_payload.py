"""Hedge posture surfaced on the realtime risk snapshot (observability, read-only)."""
from __future__ import annotations

import json

from app.services.realtime.operator_snapshot import _hedge_payload, _risk_payload


class _FakeRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self._d = data

    def get(self, key: str):
        return self._d.get(key)


def test_hedge_payload_counts_open_and_negative_positions() -> None:
    positions = [
        {"symbol": "BTCUSDT", "side": "long", "is_open": True, "unrealized_pnl_usd": -12.0},
        {"symbol": "ETHUSDT", "side": "short", "status": "open", "unrealized_pnl_usd": 5.0},
        {"symbol": "SOLUSDT", "side": "long", "status": "closed", "unrealized_pnl_usd": -3.0},
    ]
    fake = _FakeRedis(
        {
            "v2:paper:positions": json.dumps({"positions": positions}),
            "v2:portfolio:state": json.dumps({"portfolio_liquidation_buffer_usd": 150.0}),
        }
    )
    out = _hedge_payload(fake)
    assert out["hedge_engine_active"] is True
    assert out["open_position_count"] == 2  # closed one excluded
    assert out["negative_position_count"] == 1  # only the open BTC long
    assert out["hedge_required_candidates"][0]["symbol"] == "BTCUSDT"
    assert out["portfolio_liquidation_buffer_usd"] == 150.0
    assert out["places_real_order"] is False


def test_hedge_payload_empty_positions_is_safe() -> None:
    out = _hedge_payload(_FakeRedis({}))
    assert out["open_position_count"] == 0
    assert out["negative_position_count"] == 0
    assert out["hedge_required_candidates"] == []
    assert out["places_real_order"] is False


def test_risk_snapshot_includes_hedge_block() -> None:
    out = _risk_payload(_FakeRedis({}))
    assert "hedge" in out
    assert out["hedge"]["hedge_engine_active"] is True
    assert out["places_real_order"] is False
