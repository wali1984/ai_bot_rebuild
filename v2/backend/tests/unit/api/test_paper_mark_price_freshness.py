"""Unit tests for paper mark price staleness logic in market_contracts.

Covers:
- _select_freshest_paper_mark: picks lowest-age candidate
- _enrich_paper_positions stale counter: threshold is 90s (not 15s)
- REST-polled marks (60s cycle) stay non-stale within 90s window
- WSDS marks (<2s) are never stale
- Stored mark from position row is used only as last resort
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.api.v2.market_contracts import (
    _enrich_paper_positions,
    _first_positive_price_with_source,
    _latest_position_signal_reasoning,
    _paper_market_price_candidate,
    _recent_closed_trade_rows as _market_recent_closed_trade_rows,
    _row_position_reasoning,
    _select_freshest_paper_mark,
)
from app.api.v2.mobile import (
    _compact_position,
    _mobile_closed_positions,
    _recent_closed_trade_rows as _mobile_recent_closed_trade_rows,
)


class _MobilePaperSummaryFakeRedis:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get(self, key: str) -> bytes | None:
        import json

        value = self.values.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        return json.dumps(value).encode()

    def scan(self, cursor: int, match: str, count: int = 10) -> tuple[int, list[str]]:
        return 0, []


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _age_iso(age_seconds: float) -> str:
    return datetime.fromtimestamp(time.time() - age_seconds, UTC).isoformat()


# ---------------------------------------------------------------------------
# _select_freshest_paper_mark
# ---------------------------------------------------------------------------

class TestSelectFreshestPaperMark:
    def test_returns_empty_dict_when_no_valid_candidates(self) -> None:
        result = _select_freshest_paper_mark([])
        assert result.get("price") is None
        assert result.get("source") == "MISSING_PAPER_MARK_PRICE"

    def test_picks_lowest_age(self) -> None:
        older = {"price": 100.0, "age_seconds": 60.0, "priority": 1}
        newer = {"price": 101.0, "age_seconds": 5.0, "priority": 2}
        result = _select_freshest_paper_mark([older, newer])
        assert result["price"] == 101.0

    def test_picks_by_priority_when_ages_equal(self) -> None:
        high_priority = {"price": 100.0, "age_seconds": 5.0, "priority": 0}
        low_priority = {"price": 101.0, "age_seconds": 5.0, "priority": 2}
        result = _select_freshest_paper_mark([low_priority, high_priority])
        assert result["priority"] == 0

    def test_ignores_none_age_in_favour_of_known_age(self) -> None:
        no_age = {"price": 99.0, "age_seconds": None, "priority": 0}
        has_age = {"price": 100.0, "age_seconds": 30.0, "priority": 3}
        result = _select_freshest_paper_mark([no_age, has_age])
        assert result["price"] == 100.0

    def test_rejects_zero_and_negative_prices(self) -> None:
        bad = {"price": 0.0, "age_seconds": 1.0, "priority": 0}
        good = {"price": 50.0, "age_seconds": 50.0, "priority": 3}
        result = _select_freshest_paper_mark([bad, good])
        assert result["price"] == 50.0


class TestPriceSourceSelection:
    def test_first_positive_price_skips_zero(self) -> None:
        price, source = _first_positive_price_with_source(
            {"exit_price": 0.0, "paper_exit_price": 101.25},
            [("exit_price", "exit_price"), ("paper_exit_price", "paper_exit_price")],
        )
        assert price == 101.25
        assert source == "paper_exit_price"

    def test_row_reasoning_preserves_ledger_signal_basis(self) -> None:
        reasoning = _row_position_reasoning(
            {
                "signal_id": "sig-ledger",
                "prediction_id": "pred-ledger",
                "side": "LONG",
                "close_reason": "TIER_2_TAKE_PROFIT",
                "confidence": 0.73,
            },
            source="v2:paper:closed_trades",
        )
        assert reasoning is not None
        assert reasoning["source"] == "v2:paper:closed_trades"
        assert reasoning["signal_id"] == "sig-ledger"
        assert reasoning["reason"] == "TIER_2_TAKE_PROFIT"

    def test_mobile_closed_positions_preserve_exit_price_and_decision_basis(self) -> None:
        import json

        client = MagicMock()

        def _get(key: str) -> bytes | None:
            if key == "v2:signals:latest:ETHUSDT":
                return json.dumps({
                    "signal_id": "sig-close",
                    "prediction_id": "pred-close",
                    "action": "SHORT",
                    "confidence": 0.74,
                    "reason": "matched_closed_trade_basis",
                    "available_at": _now_iso(),
                }).encode()
            return None

        client.get.side_effect = _get
        client.scan.return_value = (0, [])

        rows = _mobile_closed_positions(
            client,
            [{
                "close_id": "close-1",
                "symbol": "ETHUSDT",
                "side": "SHORT",
                "quantity": 0.5,
                "entry_price": 2500.0,
                "exit_price": 0.0,
                "paper_exit_price": 2400.0,
                "realized_pnl_usd": 50.0,
                "close_reason": "TIER_2_TAKE_PROFIT",
                "exit_price_utc": "2026-06-18T00:00:00Z",
                "signal_id": "sig-close",
                "prediction_id": "pred-close",
            }],
        )

        assert len(rows) == 1
        assert rows[0]["id"] == "close-1"
        assert rows[0]["entry_price"] == 2500.0
        assert rows[0]["exit_price"] == 2400.0
        assert rows[0]["exit_price_source"] == "paper_exit_price"
        assert rows[0]["realized_pnl"] == 50.0
        assert rows[0]["status"] == "closed"
        assert rows[0]["decision_reasoning"]["reason"] == "matched_closed_trade_basis"

    def test_mobile_compact_position_skips_zero_prices_for_positive_fallbacks(self) -> None:
        row = _compact_position({
            "position_id": "pos-1",
            "symbol": "ETHUSDT",
            "side": "LONG",
            "quantity": 0.5,
            "entry_price": 0.0,
            "avg_entry_price": 2500.0,
            "exit_price": 0.0,
            "paper_exit_price": 2550.0,
            "mark_price": 0.0,
            "last_mark_price": 2540.0,
            "last_mark_price_source": "v2:market:mark:ETHUSDT",
        })

        assert row["entry_price"] == 2500.0
        assert row["entry_price_source"] == "avg_entry_price"
        assert row["exit_price"] == 2550.0
        assert row["exit_price_source"] == "paper_exit_price"
        assert row["mark_price"] == 2540.0
        assert row["mark_price_source"] == "v2:market:mark:ETHUSDT"

    def test_mobile_compact_position_skips_non_finite_prices_for_positive_fallbacks(self) -> None:
        row = _compact_position({
            "position_id": "pos-finite",
            "symbol": "ETHUSDT",
            "side": "LONG",
            "quantity": "Infinity",
            "net_quantity": 0.5,
            "entry_price": "NaN",
            "avg_entry_price": 2500.0,
            "exit_price": "inf",
            "paper_exit_price": 2550.0,
            "mark_price": "-Infinity",
            "last_mark_price": 2540.0,
            "last_mark_price_source": "v2:market:mark:ETHUSDT",
            "unrealized_pnl": "NaN",
        })

        assert row["qty"] == 0.5
        assert row["entry_price"] == 2500.0
        assert row["entry_price_source"] == "avg_entry_price"
        assert row["exit_price"] == 2550.0
        assert row["exit_price_source"] == "paper_exit_price"
        assert row["mark_price"] == 2540.0
        assert row["mark_price_source"] == "v2:market:mark:ETHUSDT"
        assert row["unrealized_pnl"] is None

    def test_mobile_compact_position_leaves_non_finite_prices_unavailable_without_fallback(self) -> None:
        row = _compact_position({
            "position_id": "pos-unavailable",
            "symbol": "ETHUSDT",
            "side": "LONG",
            "quantity": 1.0,
            "entry_price": "NaN",
            "exit_price": "inf",
            "mark_price": "-Infinity",
        })

        assert row["entry_price"] is None
        assert row["exit_price"] is None
        assert row["mark_price"] is None

    def test_mobile_compact_position_skips_zero_qty_for_real_quantity(self) -> None:
        row = _compact_position({
            "position_id": "pos-qty",
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "qty": 0.0,
            "quantity": 0.75,
            "net_quantity": 0.75,
            "entry_price": 2500.0,
            "mark_price": 2490.0,
        })

        assert row["qty"] == 0.75
        assert row["entry_price"] == 2500.0
        assert row["mark_price"] == 2490.0

    def test_latest_position_reasoning_unwraps_active_signal_payload(self) -> None:
        import json

        client = MagicMock()

        def _get(key: str) -> bytes | None:
            if key == "v2:signals:paper:ETHUSDT:5m":
                return json.dumps({
                    "active_signal": {
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "proposed_action": "SHORT",
                        "confidence_calibrated": 0.67,
                        "explanation": "Blocked No Orchestrator Decision",
                        "blocked_reason": "Expected Move After Cost Below Threshold",
                        "paper_fill_status": "PAPER_FILL_GATE_BLOCKED",
                        "generated_at": _now_iso(),
                        "lineage_summary": {
                            "signal_id": "sig-active",
                            "prediction_id": "pred-active",
                            "risk_state": "Paper Gate Blocked Before Risk",
                            "paper_state": "No Paper Intent For All Tf Signal",
                        },
                    },
                }).encode()
            return None

        client.get.side_effect = _get
        client.scan.return_value = (0, ["v2:signals:paper:ETHUSDT:5m"])

        reasoning = _latest_position_signal_reasoning(
            client,
            "ETHUSDT",
            {"symbol": "ETHUSDT", "side": "SHORT", "timeframe": "5m"},
        )

        assert reasoning is not None
        assert reasoning["source"] == "v2:signals:paper:ETHUSDT:5m"
        assert reasoning["signal_id"] == "sig-active"
        assert reasoning["prediction_id"] == "pred-active"
        assert reasoning["action"] == "SHORT"
        assert reasoning["confidence"] == 0.67
        assert reasoning["risk_state"] == "Paper Gate Blocked Before Risk"
        assert reasoning["reason"] == "Blocked No Orchestrator Decision"

    def test_closed_position_without_signal_id_uses_row_basis_without_scanning(self) -> None:
        client = MagicMock()

        reasoning = _latest_position_signal_reasoning(
            client,
            "ETHUSDT",
            {
                "symbol": "ETHUSDT",
                "side": "SHORT",
                "close_reason": "TIER_2_TAKE_PROFIT",
                "entry_price": 2500.0,
                "exit_price": 2400.0,
            },
            row_source="v2:paper:closed_trades",
        )

        client.get.assert_not_called()
        client.scan.assert_not_called()
        assert reasoning is not None
        assert reasoning["source"] == "v2:paper:closed_trades"
        assert reasoning["action"] == "SHORT"
        assert reasoning["reason"] == "TIER_2_TAKE_PROFIT"

    def test_open_position_adaptive_allocation_basis_avoids_scan(self) -> None:
        client = MagicMock()
        client.get.return_value = None

        reasoning = _latest_position_signal_reasoning(
            client,
            "IDUSDT",
            {
                "symbol": "IDUSDT",
                "side": "short",
                "adaptive_allocation": {
                    "confidence_calibrated": 0.649,
                    "capital_allocation_reason": "adaptive_allocation_from_confidence_edge",
                    "decision_time": "2026-06-23T16:04:56.238Z",
                },
                "decision": "ACCEPTED_PAPER_FILL",
            },
        )

        client.scan.assert_not_called()
        assert reasoning is not None
        assert reasoning["source"] == "v2:paper:positions"
        assert reasoning["action"] == "short"
        assert reasoning["confidence"] == 0.649
        assert reasoning["reason"] == "adaptive_allocation_from_confidence_edge"

    def test_recent_closed_trade_rows_sort_and_limit_before_projection(self) -> None:
        rows = [
            {"close_id": "old", "exit_price_utc": "2026-06-20T00:00:00Z"},
            {"close_id": "new", "exit_price_utc": "2026-06-22T00:00:00Z"},
            {"close_id": "mid", "exit_price_utc": "2026-06-21T00:00:00Z"},
        ]

        assert [row["close_id"] for row in _market_recent_closed_trade_rows(rows, 2)] == ["new", "mid"]
        assert [row["close_id"] for row in _mobile_recent_closed_trade_rows(rows, 2)] == ["new", "mid"]

    @pytest.mark.asyncio
    async def test_mobile_paper_summary_uses_realtime_mark_and_reasoning_enrichment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.api.v2.mobile as mobile

        fake = _MobilePaperSummaryFakeRedis({
            "v2:paper:heartbeat": {
                "paper_signals_seen": 4,
                "intents_built": 2,
                "intents_accepted": 1,
                "intents_blocked": 1,
                "closed_trade_count": 3,
                "realized_pnl_usd": 12.5,
                "classification": "RUNNING",
            },
            "v2:risk:active_profile": {"fields": {"max_leverage": 10}},
            "v2:paper:positions": [{
                "position_id": "pos-btc",
                "symbol": "BTCUSDT",
                "side": "LONG",
                "quantity": 0.01,
                "entry_price": 0.0,
                "avg_entry_price": 60000.0,
                "mark_price": 0.0,
                "last_mark_price": 59000.0,
                "signal_id": "sig-BTC",
                "prediction_id": "pred-BTC",
            }],
            "v2:market:coinapi:wsds:BTCUSDT": {
                "mid_px": 62000.0,
                "generated_at": int((time.time() - 1) * 1000),
            },
            "v2:signals:latest:BTCUSDT": {
                "signal_id": "sig-BTC",
                "prediction_id": "pred-BTC",
                "action": "LONG",
                "confidence": 0.81,
                "reason": "fresh_features_positive_edge",
                "available_at": _now_iso(),
            },
        })
        monkeypatch.setattr(mobile, "get_redis", lambda: fake)

        payload = await mobile.get_mobile_paper_summary()
        preview = payload["positions"]["positions_preview"][0]

        assert payload["positions"]["open_count"] == 1
        assert preview["entry_price"] == 60000.0
        assert preview["entry_price_source"] == "avg_entry_price"
        assert preview["mark_price"] == 62000.0
        assert preview["mark_price_source"] == "v2:market:coinapi:wsds:BTCUSDT.mid_px"
        assert preview["decision_reasoning"]["reason"] == "fresh_features_positive_edge"
        assert payload["position_pricing"]["live_mark_price_count"] == 1
        assert payload["position_pricing"]["missing_mark_price_count"] == 0
        assert payload["position_pricing"]["unrealized_pnl_usd"] == pytest.approx(20.0)
        assert payload["pnl"]["unrealized_usd"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# _paper_market_price_candidate
# ---------------------------------------------------------------------------

class TestPaperMarketPriceCandidate:
    def test_returns_none_for_missing_price(self) -> None:
        result = _paper_market_price_candidate(
            source_key="v2:market:funding:BTCUSDT",
            source_field="markPrice",
            price=None,
            generated_at=_now_iso(),
            priority=1,
        )
        assert result is None

    def test_returns_none_for_zero_price(self) -> None:
        result = _paper_market_price_candidate(
            source_key="v2:market:funding:BTCUSDT",
            source_field="markPrice",
            price=0.0,
            generated_at=_now_iso(),
            priority=1,
        )
        assert result is None

    @pytest.mark.parametrize("bad_price", ["NaN", "inf", "-Infinity"])
    def test_returns_none_for_non_finite_price(self, bad_price: str) -> None:
        result = _paper_market_price_candidate(
            source_key="v2:market:funding:BTCUSDT",
            source_field="markPrice",
            price=bad_price,
            generated_at=_now_iso(),
            priority=1,
        )
        assert result is None

    def test_returns_valid_candidate_with_age(self) -> None:
        iso = _age_iso(30.0)
        result = _paper_market_price_candidate(
            source_key="v2:market:funding:BTCUSDT",
            source_field="markPrice",
            price=62000.0,
            generated_at=iso,
            priority=1,
        )
        assert result is not None
        assert result["price"] == 62000.0
        assert result["age_seconds"] is not None
        assert 28 < result["age_seconds"] < 32

    def test_age_is_none_when_generated_at_is_none(self) -> None:
        result = _paper_market_price_candidate(
            source_key="v2:market:funding:BTCUSDT",
            source_field="markPrice",
            price=62000.0,
            generated_at=None,
            priority=1,
        )
        assert result is not None
        assert result["age_seconds"] is None


# ---------------------------------------------------------------------------
# _enrich_paper_positions — stale threshold at 90s
# ---------------------------------------------------------------------------

def _make_mock_client(price: float, age_seconds: float) -> Any:
    """Redis client mock returning a single mark price candidate."""
    client = MagicMock()

    wsds_age = _age_iso(age_seconds)
    wsds_payload = {
        "mid_px": price,
        "generated_at": int((time.time() - age_seconds) * 1000),
    }

    def _mock_get(key: str) -> bytes | None:
        import json
        if "coinapi:wsds" in key:
            return json.dumps(wsds_payload).encode()
        return None

    client.get.side_effect = _mock_get
    return client


def _make_position(symbol: str, side: str, entry: float, qty: float) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "avg_entry_price": entry,
        "net_quantity": qty,
    }


class TestEnrichPaperPositionsStaleThreshold:
    def test_wsds_fresh_mark_is_not_stale(self) -> None:
        """A WSDS mark 1s old should not count as stale (well below 90s threshold)."""
        client = _make_mock_client(price=62000.0, age_seconds=1.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert metrics["stale_mark_price_count"] == 0
        assert metrics["live_mark_price_count"] == 1

    def test_rest_polled_mark_60s_old_is_not_stale(self) -> None:
        """A REST-polled mark 60s old is within the 90s threshold → not stale."""
        client = _make_mock_client(price=62000.0, age_seconds=60.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert metrics["stale_mark_price_count"] == 0

    def test_rest_polled_mark_89s_old_is_not_stale(self) -> None:
        """A mark 89s old is still within the 90s threshold."""
        client = _make_mock_client(price=62000.0, age_seconds=89.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert metrics["stale_mark_price_count"] == 0

    def test_mark_91s_old_is_stale(self) -> None:
        """A mark 91s old exceeds the 90s threshold → counted as stale."""
        client = _make_mock_client(price=62000.0, age_seconds=91.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert metrics["stale_mark_price_count"] == 1

    def test_missing_mark_counted_as_missing_not_stale(self) -> None:
        """When no mark is available, missing_mark_price_count increments, not stale."""
        client = MagicMock()
        client.get.return_value = None
        client.scan.return_value = (0, [])

        pos = _make_position("UNKNOWNSDT", "SHORT", 1.0, 100.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [pos],
            max_leverage=5.0,
        )
        assert metrics["missing_mark_price_count"] == 1
        assert metrics["stale_mark_price_count"] == 0
        assert positions[0]["mark_price"] is None
        assert positions[0]["current_price"] is None
        assert positions[0]["mark_price_source"] == "MISSING_PAPER_MARK_PRICE"

    def test_pnl_calculated_from_live_mark(self) -> None:
        """Unrealised PnL uses the live mark price, not the stored one."""
        client = _make_mock_client(price=62000.0, age_seconds=1.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert len(positions) == 1
        # Long: (62000 - 60000) * 0.01 = 20 USD
        assert positions[0]["mark_price"] == 62000.0
        assert abs(positions[0]["unrealized_pnl"] - 20.0) < 0.01

    def test_position_reasoning_attached_from_latest_signal(self) -> None:
        import json

        client = MagicMock()

        def _get(key: str) -> bytes | None:
            if "coinapi:wsds" in key:
                return json.dumps({"mid_px": 62000.0, "generated_at": int((time.time() - 1) * 1000)}).encode()
            if key == "v2:signals:latest:BTCUSDT":
                return json.dumps({
                    "signal_id": "sig-BTC",
                    "prediction_id": "pred-BTC",
                    "action": "LONG",
                    "confidence": 0.81,
                    "risk_state": "ALLOW",
                    "paper_fill_status": "ACCEPTED",
                    "market_regime": "trend",
                    "reason": "fresh_features_positive_edge",
                    "available_at": _now_iso(),
                    "model_version": "trainer-v1",
                }).encode()
            return None

        client.get.side_effect = _get
        client.scan.return_value = (0, [])
        positions, _metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "LONG", 60000.0, 0.01)],
            max_leverage=10.0,
        )

        reasoning = positions[0]["decision_reasoning"]
        assert reasoning["signal_id"] == "sig-BTC"
        assert reasoning["prediction_id"] == "pred-BTC"
        assert reasoning["confidence"] == 0.81
        assert reasoning["reason"] == "fresh_features_positive_edge"

    def test_position_reasoning_prefers_matching_signal_id(self) -> None:
        import json

        client = MagicMock()

        def _get(key: str) -> bytes | None:
            if key == "v2:signals:latest:BTCUSDT":
                return json.dumps({
                    "signal_id": "sig-other",
                    "prediction_id": "pred-other",
                    "reason": "unrelated_latest_signal",
                    "available_at": _now_iso(),
                }).encode()
            if key == "v2:signals:paper:BTCUSDT":
                return json.dumps({
                    "signal_id": "sig-ledger",
                    "prediction_id": "pred-ledger",
                    "reason": "matched_entry_signal",
                    "available_at": _now_iso(),
                }).encode()
            return None

        client.get.side_effect = _get
        client.scan.return_value = (0, [])
        reasoning = _latest_position_signal_reasoning(
            client,
            "BTCUSDT",
            {"signal_id": "sig-ledger", "prediction_id": "pred-ledger", "side": "LONG"},
        )

        assert reasoning is not None
        assert reasoning["signal_id"] == "sig-ledger"
        assert reasoning["reason"] == "matched_entry_signal"

    def test_position_reasoning_rejects_unmatched_latest_signal(self) -> None:
        import json

        client = MagicMock()
        client.get.return_value = json.dumps({
            "signal_id": "sig-other",
            "prediction_id": "pred-other",
            "reason": "unrelated_latest_signal",
            "available_at": _now_iso(),
        }).encode()
        client.scan.return_value = (0, [])

        reasoning = _latest_position_signal_reasoning(
            client,
            "BTCUSDT",
            {
                "signal_id": "sig-ledger",
                "prediction_id": "pred-ledger",
                "side": "LONG",
                "entry_reason": "ledger_entry_basis",
            },
        )

        assert reasoning is not None
        assert reasoning["source"] == "v2:paper:positions"
        assert reasoning["signal_id"] == "sig-ledger"
        assert reasoning["reason"] == "ledger_entry_basis"

    def test_short_pnl_sign(self) -> None:
        """Short PnL is negative when mark > entry."""
        client = _make_mock_client(price=62000.0, age_seconds=1.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [_make_position("BTCUSDT", "SHORT", 60000.0, 0.01)],
            max_leverage=10.0,
        )
        assert positions[0]["unrealized_pnl"] < 0

    def test_aggregate_metrics_across_multiple_positions(self) -> None:
        """Stale and live counts aggregate correctly across all positions."""
        # Create client: first symbol is fresh, second is very stale
        import json

        def _multi_get(key: str) -> bytes | None:
            if "BTCUSDT" in key and "coinapi" in key:
                return json.dumps({"mid_px": 62000.0, "generated_at": int((time.time() - 1) * 1000)}).encode()
            if "ETHUSDT" in key and "coinapi" in key:
                return json.dumps({"mid_px": 3000.0, "generated_at": int((time.time() - 100) * 1000)}).encode()
            return None

        client = MagicMock()
        client.get.side_effect = _multi_get

        rows = [
            _make_position("BTCUSDT", "LONG", 60000.0, 0.01),
            _make_position("ETHUSDT", "SHORT", 2900.0, 0.1),
        ]
        positions, metrics = _enrich_paper_positions(client, rows, max_leverage=10.0)
        assert metrics["live_mark_price_count"] == 2
        assert metrics["stale_mark_price_count"] == 1  # ETHUSDT is 100s old
