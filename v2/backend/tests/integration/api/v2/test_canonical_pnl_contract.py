from __future__ import annotations

import json
from typing import Any

from app.services.portfolio import build_canonical_pnl


class FakeRedis:
    def __init__(self, kv: dict[str, Any]) -> None:
        self.kv = {key: json.dumps(value) for key, value in kv.items()}

    def get(self, key: str) -> str | None:
        return self.kv.get(key)


def test_canonical_pnl_reconciles_current_session_usd_values() -> None:
    payload = build_canonical_pnl(FakeRedis({
        "v2:portfolio:state": {
            "generated_utc": "2026-07-09T00:00:00Z",
            "paper_session_id": "session-a",
            "starting_equity_usd": 3000.0,
            "equity": 3001.25,
            "realized_net_pnl_usd": 1.0,
            "unrealized_pnl_usd": 0.25,
            "fees_usd": 0.05,
            "slippage_usd": 0.02,
            "funding_usd": 0.0,
            "closed_trade_count": 2,
        }
    }))

    assert payload["schema_version"] == "canonical_pnl_v1"
    assert payload["account_scope"] == "paper"
    assert payload["equity_usd"] == 3001.25
    assert payload["net_pnl_usd"] == 1.25
    assert payload["reconciliation_status"] == "PASS"
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_canonical_pnl_marks_missing_values_partial() -> None:
    payload = build_canonical_pnl(FakeRedis({}))

    assert payload["reconciliation_status"] == "PARTIAL"
    assert "equity_usd" in payload["missing_fields"]
    assert payload["source"] == "unavailable"
    assert payload["places_real_order"] is False
