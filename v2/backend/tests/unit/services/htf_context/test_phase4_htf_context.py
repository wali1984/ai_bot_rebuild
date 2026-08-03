from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.cli.v2_a_plus_context_loop import (
    REQUIRED_CROSS_ASSET_FIELDS,
    REQUIRED_CROSS_ASSET_TENSOR_FIELDS,
    REQUIRED_HTF_FEATURE_FIELDS,
    REQUIRED_HTF_TENSOR_FIELDS,
    REQUIRED_REGIME_TENSOR_FIELDS,
    _tensor_field_status,
)
from v2.backend.app.services.a_plus_trade_gate.service import APlusGateConfig, _htf_check
from v2.backend.app.services.htf_context.service import (
    build_cross_asset_context,
    build_htf_context,
)


def _klines(*, start_price: float = 100.0, step: float = 0.2, rows: int = 160) -> list[list[float]]:
    out: list[list[float]] = []
    open_time = 1_780_000_000_000
    for index in range(rows):
        price = start_price + step * index
        high = price + 1.0
        low = price - 1.0
        close = price + step * 0.5
        volume = 1000.0 + index
        out.append(
            [
                open_time + index * 14_400_000,
                price,
                high,
                low,
                close,
                volume,
                open_time + (index + 1) * 14_400_000 - 1,
                volume * close,
                10,
                volume * 0.55,
                volume * close * 0.55,
                0,
            ]
        )
    return out


def test_phase4_htf_context_emits_required_fields_and_tensor_consumes_them() -> None:
    context = build_htf_context("BTCUSDT", _klines())

    assert context["htf_feature_count"] >= 20
    assert all(field in context for field in REQUIRED_HTF_FEATURE_FIELDS)
    assert _tensor_field_status(REQUIRED_HTF_TENSOR_FIELDS)["trainer_tensor_consumes_all_required_fields"] is True
    assert _tensor_field_status(REQUIRED_REGIME_TENSOR_FIELDS)["trainer_tensor_consumes_all_required_fields"] is True


def test_phase4_cross_asset_context_has_required_fields_and_tensor_consumes_them() -> None:
    context = build_cross_asset_context(
        btc_klines_1h=_klines(rows=80, step=0.1),
        btc_klines_4h=_klines(rows=160, step=0.2),
        eth_klines_4h=_klines(start_price=0.05, step=0.0001, rows=160),
    )

    assert all(field in context for field in REQUIRED_CROSS_ASSET_FIELDS)
    assert _tensor_field_status(REQUIRED_CROSS_ASSET_TENSOR_FIELDS)[
        "trainer_tensor_consumes_all_required_fields"
    ] is True


def test_phase4_a_plus_htf_check_blocks_misaligned_trade() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    htf_context = {
        "generated_utc": "2026-07-06T12:00:00Z",
        "htf_4h_trend": "DOWN",
        "htf_4h_macd_state": "BEARISH",
        "htf_1d_ema_direction": "DOWN",
        "htf_4h_rsi_zone": "BEARISH",
    }
    cross_asset = {
        "generated_utc": "2026-07-06T12:00:00Z",
        "btc_direction_4h": "DOWN",
        "risk_off_proxy": True,
    }

    result = _htf_check(
        htf_context=htf_context,
        cross_asset=cross_asset,
        side="long",
        entry_timeframe_trend="TRENDING_DOWN",
        now=now,
        config=APlusGateConfig(min_htf_alignment_score=0.25),
    )

    assert result["passed"] is False
    assert "alignment_score=" in result["reason"]
