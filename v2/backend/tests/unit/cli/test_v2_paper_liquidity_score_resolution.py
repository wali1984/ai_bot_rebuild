"""Regression tests for allocator liquidity score resolution.

F-0001 leg: alt-data producers (DeFiLlama TVL) emit 0.0 for symbols they have
no data for (majors like BTCUSDT have no DeFi TVL). A non-positive "explicit"
liquidity score must be treated as missing evidence and fall through to
orderbook depth/spread derivation — never as an explicit zero-liquidity
verdict that blocks the allocator.
"""
from __future__ import annotations

import importlib

paper_loop = importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")


def _derive(**overrides):
    kwargs = {
        "intent": {},
        "signal": {},
        "prediction": {},
        "features": {},
        "market_microstructure": {},
        "spread_bps": None,
        "feature_source_name": "features",
    }
    kwargs.update(overrides)
    return paper_loop._derive_allocator_liquidity_score(**kwargs)


class TestExplicitZeroTreatedAsMissing:
    def test_defillama_zero_falls_through_to_depth_and_spread(self):
        score, source, reason = _derive(
            features={"defillama_liquidity_score": 0.0},
            market_microstructure={"orderbook_depth_usd": 120_000.0},
            spread_bps=3.0,
        )
        assert reason == "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD"
        assert score > 0.0

    def test_defillama_zero_with_depth_only(self):
        score, source, reason = _derive(
            features={"defillama_liquidity_score": 0.0},
            market_microstructure={"orderbook_depth_usd": 300_000.0},
        )
        assert reason == "DERIVED_FROM_ORDERBOOK_DEPTH"
        assert score == 1.0

    def test_negative_explicit_treated_as_missing(self):
        score, source, reason = _derive(
            features={"liquidity_score": -1.0},
            spread_bps=2.0,
        )
        assert reason == "DERIVED_FROM_SPREAD_ONLY"
        assert score == 1.0


class TestPositiveExplicitStillRespected:
    def test_positive_explicit_score_wins(self):
        score, source, reason = _derive(
            features={"defillama_liquidity_score": 0.72},
            market_microstructure={"orderbook_depth_usd": 300_000.0},
            spread_bps=2.0,
        )
        assert reason == "EXPLICIT_LIQUIDITY_SCORE"
        assert score == 0.72

    def test_intent_explicit_takes_priority_over_features(self):
        score, source, reason = _derive(
            intent={"liquidity_score": 0.4},
            features={"defillama_liquidity_score": 0.0},
        )
        assert reason == "EXPLICIT_LIQUIDITY_SCORE"
        assert score == 0.4


class TestNoEvidenceDefault:
    def test_everything_missing_returns_neutral_default(self):
        score, source, reason = _derive()
        assert reason == "DEFAULT_NEUTRAL_LIQUIDITY_SCORE"
        assert score == 1.0

    def test_zero_explicit_and_no_orderbook_returns_neutral_default(self):
        # With the orderbook feed down AND alt-data zeroed, resolution lands on
        # the neutral default; the microstructure trust gate (fail-closed) is
        # the layer responsible for blocking entries on missing book data.
        score, source, reason = _derive(features={"defillama_liquidity_score": 0.0})
        assert reason == "DEFAULT_NEUTRAL_LIQUIDITY_SCORE"
        assert score == 1.0
