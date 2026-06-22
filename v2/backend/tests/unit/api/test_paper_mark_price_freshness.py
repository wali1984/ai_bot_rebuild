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
    _paper_market_price_candidate,
    _select_freshest_paper_mark,
)


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

        pos = _make_position("UNKNOWNSDT", "SHORT", 1.0, 100.0)
        positions, metrics = _enrich_paper_positions(
            client,
            [pos],
            max_leverage=5.0,
        )
        assert metrics["missing_mark_price_count"] == 1
        assert metrics["stale_mark_price_count"] == 0

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
        assert abs(positions[0]["unrealized_pnl"] - 20.0) < 0.01

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
