"""Cascade-context publisher: squeeze-detector input derivation (raw book/tape/premium)."""
from __future__ import annotations

import pytest


def test_derive_orderbook_squeeze_inputs_from_raw_depth() -> None:
    """Regression: the raw Binance book has no derived metrics, so the squeeze
    detector ran for hours as a one-input (sweep-only) detector with direction
    permanently 'unclear' (trap == probability, block/ride never fired)."""
    from app.cli.v2_cascade_context_publisher import derive_orderbook_squeeze_inputs

    book = {
        "bids": [["100.0", "9.0"], ["99.9", "6.0"]],
        "asks": [["100.1", "3.0"], ["100.2", "2.0"]],
    }
    out = derive_orderbook_squeeze_inputs(book)
    assert out is not None
    assert out["depth_imbalance"] == pytest.approx((15.0 - 5.0) / 20.0)
    assert out["spread_bps"] == pytest.approx(0.1 / 100.05 * 10000.0)
    assert derive_orderbook_squeeze_inputs({"bids": [], "asks": []}) is None
    assert derive_orderbook_squeeze_inputs(None) is None
    # crossed/garbage books refuse rather than emit a fake signal
    assert derive_orderbook_squeeze_inputs({"bids": [["101", "1"]], "asks": [["100", "1"]]}) is None


def test_derive_tape_imbalance_notional_weighted_aggressor() -> None:
    from app.cli.v2_cascade_context_publisher import derive_tape_imbalance

    # m=False -> aggressive BUY, m=True -> aggressive SELL (Binance semantics)
    payload = {
        "trades": [
            {"p": "100", "q": "3", "m": False},
            {"p": "100", "q": "1", "m": True},
        ]
    }
    out = derive_tape_imbalance(payload)
    assert out is not None
    assert out["tape_imbalance"] == pytest.approx((300.0 - 100.0) / 400.0)
    assert derive_tape_imbalance({"trades": []}) is None
    assert derive_tape_imbalance(None) is None


def test_derive_mark_index_divergence_bps() -> None:
    from app.cli.v2_cascade_context_publisher import derive_mark_index_divergence

    out = derive_mark_index_divergence({"markPrice": "100.10", "indexPrice": "100.00"})
    assert out is not None
    assert out["mark_index_divergence_bps"] == pytest.approx(10.0, abs=1e-6)
    assert derive_mark_index_divergence({"markPrice": "x"}) is None
    assert derive_mark_index_divergence(None) is None
