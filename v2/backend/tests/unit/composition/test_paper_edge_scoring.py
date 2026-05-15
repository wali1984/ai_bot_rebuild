from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.composition.paper_edge_scoring import (
    EDGE_AFTER_COSTS_MISSING_BLOCK,
    EDGE_AFTER_COSTS_NEGATIVE_BLOCK,
    EDGE_AFTER_COSTS_PASS,
    CONFIDENCE_TOO_LOW_BLOCK,
    FEATURE_FRESHNESS_MISSING_BLOCK,
    FEATURE_STALE_BLOCK,
    SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK,
    TRAINER_SOURCE_MISSING_BLOCK,
    score_paper_edge,
)


def _record(**overrides):
    base = {
        "symbol": "BTCUSDT",
        "risk_action": "allow",
        "trainer_source": "LEGACY_HYBRID_TRAINER_LOG_READONLY",
        "feature_freshness_state": "CURRENT",
        "confidence_calibrated": 0.72,
        "expected_move_bps": 20.0,
        "expected_move_after_cost_bps": 10.0,
        "fee_bps": 4.0,
        "spread_bps": 1.0,
        "slippage_bps": 2.0,
        "funding_risk_bps": 0.5,
    }
    base.update(overrides)
    return base


def test_all_required_fields_pass() -> None:
    result = score_paper_edge(_record(), paper_symbols=["BTCUSDT"])

    assert result["fill_allowed"] is True
    assert result["classification"] == EDGE_AFTER_COSTS_PASS
    assert result["edge_score"] == pytest.approx(10.0)
    assert result["computed_expected_move_after_cost_bps"] == pytest.approx(12.5)


def test_missing_expected_move_after_cost_blocks_fill() -> None:
    result = score_paper_edge(
        _record(expected_move_after_cost_bps=None),
        paper_symbols=["BTCUSDT"],
    )

    assert result["fill_allowed"] is False
    assert EDGE_AFTER_COSTS_MISSING_BLOCK in result["blockers"]


def test_edge_below_threshold_blocks_fill() -> None:
    result = score_paper_edge(
        _record(expected_move_after_cost_bps=7.99),
        paper_symbols=["BTCUSDT"],
    )

    assert result["fill_allowed"] is False
    assert EDGE_AFTER_COSTS_NEGATIVE_BLOCK in result["blockers"]


def test_missing_trainer_source_blocks_fill() -> None:
    result = score_paper_edge(_record(trainer_source=""), paper_symbols=["BTCUSDT"])

    assert result["fill_allowed"] is False
    assert TRAINER_SOURCE_MISSING_BLOCK in result["blockers"]


def test_missing_feature_freshness_blocks_fill() -> None:
    result = score_paper_edge(
        _record(feature_freshness_state=""),
        paper_symbols=["BTCUSDT"],
    )

    assert result["fill_allowed"] is False
    assert FEATURE_FRESHNESS_MISSING_BLOCK in result["blockers"]


def test_stale_feature_freshness_blocks_fill() -> None:
    result = score_paper_edge(
        _record(feature_freshness_state="STALE"),
        paper_symbols=["BTCUSDT"],
    )

    assert result["fill_allowed"] is False
    assert FEATURE_STALE_BLOCK in result["blockers"]


def test_symbol_not_in_paper_symbols_blocks_fill() -> None:
    result = score_paper_edge(_record(), paper_symbols=[])

    assert result["fill_allowed"] is False
    assert SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK in result["blockers"]


def test_confidence_alone_cannot_allow_fill() -> None:
    result = score_paper_edge(
        _record(
            trainer_source="",
            feature_freshness_state="",
            expected_move_after_cost_bps=None,
            confidence_calibrated=0.99,
        ),
        paper_symbols=["BTCUSDT"],
    )

    assert result["fill_allowed"] is False
    assert TRAINER_SOURCE_MISSING_BLOCK in result["blockers"]
    assert FEATURE_FRESHNESS_MISSING_BLOCK in result["blockers"]
    assert EDGE_AFTER_COSTS_MISSING_BLOCK in result["blockers"]
    assert CONFIDENCE_TOO_LOW_BLOCK not in result["blockers"]
