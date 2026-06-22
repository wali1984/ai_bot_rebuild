"""Unit tests for _enrich_paper_positions mark_price_stale field.

Verifies that:
- Every position dict includes a mark_price_stale boolean field.
- mark_price_stale is True when mark_age_seconds > 90.
- mark_price_stale is False when mark_age_seconds <= 90.
- mark_price_stale is False when mark_age_seconds is None (unknown age).
- Summary stale_mark_price_count matches count of True mark_price_stale in positions.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.api.v2.market_contracts import _enrich_paper_positions  # noqa: E402


def _base_position(**overrides) -> dict:
    row = {
        "symbol": "BTCUSDT",
        "side": "SHORT",
        "avg_entry_price": 65000.0,
        "net_quantity": 0.01,
        "unrealized_pnl": -1.5,
        "unrealized_pnl_bps": -23,
        "position_id": "pos-001",
    }
    row.update(overrides)
    return row


def _null_client() -> MagicMock:
    """Redis client mock that returns no live price."""
    client = MagicMock()
    client.get.return_value = None
    client.hgetall.return_value = {}
    return client


def _run(positions_raw, max_leverage=10.0):
    client = _null_client()
    with patch(
        "v2.backend.app.api.v2.market_contracts._paper_live_market_price",
        return_value={},
    ):
        return _enrich_paper_positions(client, positions_raw, max_leverage=max_leverage)


class TestMarkPriceStaleFlagPresent:
    def test_mark_price_stale_field_exists_in_output(self) -> None:
        positions, _ = _run([_base_position()])
        assert len(positions) == 1
        assert "mark_price_stale" in positions[0], (
            "mark_price_stale boolean must be present in every position output"
        )

    def test_mark_price_stale_is_bool(self) -> None:
        positions, _ = _run([_base_position()])
        assert isinstance(positions[0]["mark_price_stale"], bool)

    def test_stale_false_when_age_none(self) -> None:
        """Unknown age → treat as not stale (cannot confirm staleness)."""
        positions, _ = _run([_base_position()])
        assert positions[0]["mark_price_stale"] is False

    def test_stale_false_when_age_90_seconds(self) -> None:
        """90 seconds exactly is at threshold — not stale (> 90 triggers stale)."""
        stored_mark = {
            "price": 64500.0,
            "source": "v2:paper:positions",
            "source_key": "v2:paper:positions",
            "age_seconds": 90,
            "generated_at": None,
        }
        with patch(
            "v2.backend.app.api.v2.market_contracts._paper_live_market_price",
            return_value={},
        ), patch(
            "v2.backend.app.api.v2.market_contracts._paper_position_stored_mark_candidate",
            return_value=stored_mark,
        ), patch(
            "v2.backend.app.api.v2.market_contracts._select_freshest_paper_mark",
            return_value=stored_mark,
        ):
            client = _null_client()
            positions, metrics = _enrich_paper_positions(
                client, [_base_position()], max_leverage=10.0
            )
        assert positions[0]["mark_price_stale"] is False
        assert metrics["stale_mark_price_count"] == 0

    def test_stale_true_when_age_91_seconds(self) -> None:
        """91 seconds exceeds 90s threshold → stale."""
        stored_mark = {
            "price": 64500.0,
            "source": "v2:paper:positions",
            "source_key": "v2:paper:positions",
            "age_seconds": 91,
            "generated_at": None,
        }
        with patch(
            "v2.backend.app.api.v2.market_contracts._paper_live_market_price",
            return_value={},
        ), patch(
            "v2.backend.app.api.v2.market_contracts._paper_position_stored_mark_candidate",
            return_value=stored_mark,
        ), patch(
            "v2.backend.app.api.v2.market_contracts._select_freshest_paper_mark",
            return_value=stored_mark,
        ):
            client = _null_client()
            positions, metrics = _enrich_paper_positions(
                client, [_base_position()], max_leverage=10.0
            )
        assert positions[0]["mark_price_stale"] is True
        assert metrics["stale_mark_price_count"] == 1

    def test_summary_stale_count_matches_per_position_flags(self) -> None:
        """stale_mark_price_count in summary must equal sum of mark_price_stale in positions."""
        stale_mark = {
            "price": 100.0,
            "source": "v2:paper:positions",
            "source_key": "v2:paper:positions",
            "age_seconds": 200,
            "generated_at": None,
        }
        fresh_mark = {
            "price": 100.0,
            "source": "v2:paper:positions",
            "source_key": "v2:paper:positions",
            "age_seconds": 30,
            "generated_at": None,
        }
        pos1 = _base_position(symbol="BTCUSDT")
        pos2 = _base_position(symbol="ETHUSDT")
        calls = [stale_mark, fresh_mark]
        call_iter = iter(calls)

        with patch(
            "v2.backend.app.api.v2.market_contracts._paper_live_market_price",
            return_value={},
        ), patch(
            "v2.backend.app.api.v2.market_contracts._paper_position_stored_mark_candidate",
            side_effect=lambda _: next(call_iter),
        ), patch(
            "v2.backend.app.api.v2.market_contracts._select_freshest_paper_mark",
            side_effect=lambda marks: marks[0] if marks else {},
        ):
            client = _null_client()
            positions, metrics = _enrich_paper_positions(
                client, [pos1, pos2], max_leverage=10.0
            )

        per_position_stale = sum(1 for p in positions if p["mark_price_stale"])
        assert per_position_stale == metrics["stale_mark_price_count"], (
            "per-position mark_price_stale count must match summary stale_mark_price_count"
        )
