from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.api.v2.mobile import _paper_account_session_fields
from app.services.portfolio import build_canonical_pnl


class FakeRedis:
    def __init__(self, kv: dict[str, Any], *, fail_on_get: set[str] | None = None) -> None:
        self.kv = {key: json.dumps(value) for key, value in kv.items()}
        self.fail_on_get = fail_on_get or set()
        self.get_calls: list[str] = []

    def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        if key in self.fail_on_get:
            raise AssertionError(f"unexpected Redis GET for {key}")
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
    assert payload["paper_equity_usd"] == 3001.25
    assert payload["paper_realized_pnl_usd"] == 1.0
    assert payload["paper_unrealized_pnl_usd"] == 0.25
    assert payload["paper_total_pnl_usd"] == 1.25
    assert payload["net_pnl_usd"] == 1.25
    assert payload["data_source"] == "v2:portfolio:state"
    assert payload["staleness_seconds"] is not None
    assert payload["freshness_status"] in {"fresh", "degraded", "stale"}
    assert payload["reconciliation_status"] == "PASS"
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_canonical_pnl_does_not_read_heavy_ledger_when_portfolio_is_complete() -> None:
    redis = FakeRedis(
        {
            "v2:portfolio:state": {
                "generated_utc": "2026-07-09T00:00:00Z",
                "paper_session_id": "session-current",
                "starting_equity_usd": 3000.0,
                "equity": 3002.0,
                "realized_net_pnl_usd": 1.5,
                "unrealized_pnl_usd": 0.5,
                "closed_trade_count": 3,
            },
            "v2:paper:session": {
                "generated_utc": "2026-07-09T00:00:00Z",
                "paper_session_id": "session-current",
                "starting_equity_usd": 3000.0,
            },
            "v2:paper:ledger": {
                "generated_utc": "1999-01-01T00:00:00Z",
                "paper_session_id": "stale-ledger",
                "realized_pnl_usd": -999.0,
            },
        },
        fail_on_get={"v2:paper:ledger"},
    )

    payload = build_canonical_pnl(redis)

    assert payload["paper_session_id"] == "session-current"
    assert payload["paper_equity_usd"] == 3002.0
    assert payload["paper_total_pnl_usd"] == 2.0
    assert payload["source_keys"] == ["v2:portfolio:state", "v2:paper:session"]
    assert "v2:paper:ledger" not in redis.get_calls


def test_static_session_creation_time_does_not_make_fresh_portfolio_stale() -> None:
    now = datetime.now(UTC)
    payload = build_canonical_pnl(
        FakeRedis(
            {
                "v2:portfolio:state": {
                    "generated_utc": (now - timedelta(seconds=5)).isoformat(),
                    "paper_session_id": "session-current",
                    "starting_equity_usd": 3000.0,
                    "equity": 3001.0,
                    "realized_net_pnl_usd": 1.0,
                    "unrealized_pnl_usd": 0.0,
                    "closed_trade_count": 1,
                },
                "v2:paper:session": {
                    "generated_utc": (now - timedelta(days=6)).isoformat(),
                    "paper_session_id": "session-current",
                    "starting_equity_usd": 3000.0,
                },
            }
        )
    )

    assert payload["freshness_status"] == "fresh"
    assert 0.0 <= payload["staleness_seconds"] < 30.0


def test_mobile_account_fields_do_not_read_heavy_ledger_when_portfolio_is_complete() -> None:
    redis = FakeRedis(
        {
            "v2:portfolio:state": {
                "generated_utc": "2026-07-09T00:00:00Z",
                "paper_session_id": "session-mobile",
                "starting_equity_usd": 3000.0,
                "equity": 3001.25,
                "realized_net_pnl_usd": 1.0,
                "unrealized_pnl_usd": 0.25,
                "open_positions_count": 2,
                "closed_trade_count": 4,
            },
            "v2:paper:session": {
                "paper_session_id": "session-mobile",
                "starting_equity_usd": 3000.0,
            },
            "v2:paper:ledger": {"paper_session_id": "stale-ledger"},
        },
        fail_on_get={"v2:paper:ledger"},
    )

    payload = _paper_account_session_fields(
        redis,
        {"paper_session_id": "session-mobile"},
        source_type="unit_mobile_dashboard",
    )

    assert payload["paper_session_id"] == "session-mobile"
    assert payload["paper_equity_usd"] == 3001.25
    assert payload["paper_total_pnl_usd"] == 1.25
    assert payload["open_position_count"] == 2
    assert payload["closed_trade_count"] == 4
    assert payload["data_source"] == "v2:portfolio:state+v2:paper:session"
    assert "v2:paper:ledger" not in redis.get_calls


def test_canonical_pnl_marks_missing_values_partial() -> None:
    payload = build_canonical_pnl(FakeRedis({}))

    assert payload["reconciliation_status"] == "PARTIAL"
    assert "equity_usd" in payload["missing_fields"]
    assert payload["source"] == "unavailable"
    assert payload["data_source"] == "unavailable"
    assert payload["freshness_status"] == "unavailable"
    assert payload["places_real_order"] is False
