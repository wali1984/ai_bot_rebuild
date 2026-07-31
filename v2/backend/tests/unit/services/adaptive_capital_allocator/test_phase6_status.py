from __future__ import annotations

from typing import cast

from v2.backend.app.services.adaptive_capital_allocator import AllocationInput
from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY,
    PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY,
    build_paper_liquidation_atr_evidence,
)
from v2.backend.app.services.adaptive_capital_allocator.phase6_status import (
    build_adaptive_leverage_margin_simulation_status,
    build_capital_productivity_runtime_status,
    build_portfolio_exposure_runtime_status,
    build_risk_of_ruin_runtime_status,
)
from v2.backend.tests.unit.services.adaptive_capital_allocator.growth_receipt_test_utils import (
    allocate_authorized_growth,
)


def _row(**overrides: object) -> AllocationInput:
    values = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "price": 100.0,
        "equity": 10_000.0,
        "available_margin": 5_000.0,
        "wallet_balance": 10_000.0,
        "confidence_calibrated": 0.82,
        "expected_move_after_cost_bps": 80.0,
        "market_state_integrity_score": 95.0,
        "volatility_bps": 25.0,
        "liquidity_score": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "maintenance_margin_rate": 0.005,
        "drawdown_bps": 0.0,
        "symbol_exposure_usdt": 0.0,
        "total_exposure_usdt": 100.0,
        "correlation_exposure_pct": 0.01,
        "regime_score": 1.0,
        "lineage_ids": {"prediction_id": "pred"},
    }
    values.update(overrides)
    entry_atr_bps = values.get("entry_atr_bps", values["volatility_bps"])
    values["entry_atr_bps"] = entry_atr_bps
    receipt, reasons = build_paper_liquidation_atr_evidence(
        feature_snapshot={
            "feature_snapshot_id": "phase6-final-feature",
            "symbol": values["symbol"],
            "timeframe": values["timeframe"],
            "feature_freshness_state": "CURRENT",
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "candle_close_time": "2026-07-18T11:59:55Z",
            "feature_cutoff": "2026-07-18T11:59:56Z",
            "available_at": "2026-07-18T11:59:57Z",
            "generated_at": "2026-07-18T11:59:58Z",
            "features": {"atr_bps": entry_atr_bps},
        },
        symbol=values["symbol"],
        timeframe=values["timeframe"],
        entry_price=values["price"],
        allocation_decision_time="2026-07-18T11:59:59Z",
    )
    assert not reasons
    assert receipt is not None
    lineage_ids = dict(cast(dict[str, object], values.get("lineage_ids") or {}))
    lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = receipt
    lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY] = receipt["evidence_sha256"]
    values["lineage_ids"] = lineage_ids
    return AllocationInput(**values)


def _payloads() -> list[dict[str, object]]:
    # Distinct per-candidate reservation lineage seeds the deterministic
    # paper learning-exploration sizing floor (sha256 of
    # symbol:timeframe:reservation-hash) exactly as real cycles do.  These
    # draws keep the weak candidate's floor below its own policy product, so
    # the two target notionals stay non-static for the phase6 pass condition.
    weak = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.62,
            expected_move_after_cost_bps=40.0,
            volatility_bps=45.0,
            stop_distance_bps=600.0,
            lineage_ids={
                "prediction_id": "weak",
                "paper_cycle_reservation_snapshot_hash": "phase6-weak",
            },
        )
    ).to_payload()
    strong = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            lineage_ids={
                "prediction_id": "strong",
                "paper_cycle_reservation_snapshot_hash": "phase6-strong",
            },
        )
    ).to_payload()
    return [weak, strong]


def test_phase6_leverage_margin_status_passes_real_allocator_payloads() -> None:
    status = build_adaptive_leverage_margin_simulation_status(_payloads())

    assert status["status"] == "ADAPTIVE_LEVERAGE_MARGIN_SIMULATION_READY"
    assert status["overall_pass"] is True
    assert status["pass_conditions"]["recommended_leverage_not_static_1x"] is True
    assert status["pass_conditions"]["target_notional_not_static"] is True
    assert status["pass_conditions"]["risk_budget_linked_to_edge"] is True
    assert status["live_mutation_violation_count"] == 0


def test_phase6_leverage_margin_status_blocks_pf_below_one_leverage_increase() -> None:
    row = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    ).to_payload()
    row["bucket_profit_factor"] = 0.8

    status = build_adaptive_leverage_margin_simulation_status([row])

    assert status["overall_pass"] is False
    assert status["pass_conditions"]["leverage_does_not_rise_when_profit_factor_below_1"] is False
    assert status["sample_leverage_pf_violations"][0]["profit_factor"] == 0.8


def test_phase6_runtime_statuses_pass_with_allocator_payloads() -> None:
    rows = _payloads()

    capital = build_capital_productivity_runtime_status(rows)
    ruin = build_risk_of_ruin_runtime_status(rows)
    exposure = build_portfolio_exposure_runtime_status(rows)

    assert capital["status"] == "CAPITAL_PRODUCTIVITY_RUNTIME_READY"
    assert capital["best_expected_margin_return"] > 0.0
    assert ruin["status"] == "RISK_OF_RUIN_RUNTIME_READY"
    assert 0.0 <= ruin["max_risk_of_ruin_contribution"] <= 1.0
    assert exposure["status"] == "PORTFOLIO_EXPOSURE_RUNTIME_READY"
    assert exposure["max_portfolio_exposure_after_trade"] > 0.0
    assert 0.0 <= exposure["max_correlation_exposure_after_trade"] <= 1.0


def test_phase6_statuses_block_empty_runtime_rows() -> None:
    assert build_adaptive_leverage_margin_simulation_status([])["overall_pass"] is False
    assert build_capital_productivity_runtime_status([])["overall_pass"] is False
    assert build_risk_of_ruin_runtime_status([])["overall_pass"] is False
    assert build_portfolio_exposure_runtime_status([])["overall_pass"] is False
