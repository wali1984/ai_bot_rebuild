from __future__ import annotations

import math
from typing import Any

from v2.backend.app.services.adaptive_capital_allocator.contracts import RiskEnvelope
from v2.backend.app.services.adaptive_capital_allocator.dynamic_envelope import (
    calculate_dynamic_risk_envelope,
)


class _ExplodingFloat:
    def __float__(self) -> float:
        raise RuntimeError("attacker-controlled scalar text")


class _ExplodingClassObservation:
    class_observation_calls = 0

    def __getattribute__(self, name: str) -> Any:
        if name == "__class__":
            type(self).class_observation_calls += 1
            raise RuntimeError("SENSITIVE_SCALAR_CLASS_SECRET")
        return object.__getattribute__(self, name)

    def __float__(self) -> float:
        return 1.0


class _FalseyPaperMode:
    def __bool__(self) -> bool:
        return False


class _TruthyPaperMode:
    def __bool__(self) -> bool:
        return True


class _ExplodingPaperMode:
    bool_calls = 0

    def __bool__(self) -> bool:
        type(self).bool_calls += 1
        raise RuntimeError("attacker-controlled secret")


class _HostileRiskEnvelope(RiskEnvelope):
    bool_calls = 0
    attribute_calls = 0
    _sensitive_attributes = frozenset(RiskEnvelope.__dataclass_fields__)

    def __bool__(self) -> bool:
        type(self).bool_calls += 1
        raise RuntimeError("hostile envelope truth value")

    def __getattribute__(self, name: str) -> Any:
        if name in type(self)._sensitive_attributes:
            type(self).attribute_calls += 1
            raise RuntimeError("hostile envelope attribute")
        return object.__getattribute__(self, name)


class _ExplodingStringIdentity:
    def __str__(self) -> str:
        raise RuntimeError("attacker-controlled symbol text")


class _ThrowingStringSubclass(str):
    def strip(self, chars: str | None = None) -> str:
        del chars
        raise RuntimeError("attacker-controlled string method")


class _WrongReturnTypeStringSubclass(str):
    def strip(self, chars: str | None = None) -> Any:
        del chars
        return object()


class _SpoofingStringSubclass(str):
    _spoofed_text: str

    def __new__(
        cls,
        actual_text: str,
        spoofed_text: str,
    ) -> _SpoofingStringSubclass:
        instance = str.__new__(cls, actual_text)
        instance._spoofed_text = spoofed_text
        return instance

    def strip(self, chars: str | None = None) -> str:
        del chars
        return self._spoofed_text


def _positive_pit_evidence(**overrides: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "after_cost_edge_lower_bound_bps": 3.5,
        "after_cost_edge_scale_bps": 3.5,
        "after_cost_edge_resolution_bps": 0.01,
        "after_cost_edge_evidence_count": 100,
        "after_cost_edge_evidence_source": "closed_paper_outcome_lcb",
        "edge_available_at": "2026-07-17T12:00:00Z",
        "liquidity_score": 0.90,
        "regime_quality_score": 0.90,
        "market_context_source": "point_in_time_market_context",
        "market_context_available_at": "2026-07-17T12:00:01Z",
        "decision_time": "2026-07-17T12:00:02Z",
    }
    evidence.update(overrides)
    return evidence


def test_low_confidence_is_finite_and_never_raises_complex_type_error() -> None:
    envelope = calculate_dynamic_risk_envelope(
        win_rate=0.45,
        profit_factor=0.8,
        closed_trade_count=20,
        model_avg_confidence=0.4,
        paper_mode=True,
    )

    assert math.isfinite(envelope.max_effective_leverage)
    assert envelope.max_effective_leverage >= 1.0


def test_losing_evidence_contracts_risk_and_leverage_below_base() -> None:
    base = RiskEnvelope()
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=base,
        win_rate=0.40,
        profit_factor=0.70,
        closed_trade_count=86,
        current_drawdown_pct=0.01,
        model_avg_confidence=0.95,
        paper_mode=True,
    )

    assert envelope.max_total_portfolio_risk_pct < base.max_total_portfolio_risk_pct
    assert envelope.max_loss_per_trade_pct < base.max_loss_per_trade_pct
    assert envelope.max_effective_leverage < base.max_effective_leverage
    assert envelope.min_available_margin_buffer_pct > base.min_available_margin_buffer_pct
    assert envelope.min_liquidation_buffer_bps > base.min_liquidation_buffer_bps


def test_confidence_cannot_turn_losing_evidence_into_more_leverage() -> None:
    low_confidence = calculate_dynamic_risk_envelope(
        win_rate=0.40,
        profit_factor=0.70,
        closed_trade_count=100,
        model_avg_confidence=0.40,
        paper_mode=True,
    )
    high_confidence = calculate_dynamic_risk_envelope(
        win_rate=0.40,
        profit_factor=0.70,
        closed_trade_count=100,
        model_avg_confidence=0.95,
        paper_mode=True,
    )

    assert high_confidence.max_effective_leverage <= low_confidence.max_effective_leverage


def test_favorable_realized_evidence_can_earn_higher_paper_leverage() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=configured,
        win_rate=0.70,
        profit_factor=2.0,
        closed_trade_count=100,
        current_drawdown_pct=0.0,
        model_avg_confidence=0.85,
        paper_mode=True,
        **_positive_pit_evidence(),
    )

    assert envelope.max_effective_leverage > operating_baseline
    assert envelope.max_effective_leverage > 10.0
    assert envelope.max_effective_leverage <= configured.max_effective_leverage
    assert envelope.max_loss_per_trade_pct <= configured.max_loss_per_trade_pct


def test_favorable_evidence_respects_authorized_per_symbol_ceiling() -> None:
    arguments: dict[str, Any] = {
        "base_envelope": RiskEnvelope(max_effective_leverage=100.0),
        "win_rate": 0.90,
        "profit_factor": 5.0,
        "closed_trade_count": 500,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 0.95,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_evidence_count=500,
            liquidity_score=0.99,
            regime_quality_score=0.99,
        ),
    }

    btc = calculate_dynamic_risk_envelope(symbol="BTCUSDT", **arguments)
    sol = calculate_dynamic_risk_envelope(symbol="SOLUSDT", **arguments)
    alt = calculate_dynamic_risk_envelope(symbol="DOGEUSDT", **arguments)

    assert 1.0 < alt.max_effective_leverage <= 25.0
    assert alt.max_effective_leverage < sol.max_effective_leverage <= 100.0
    assert sol.max_effective_leverage == btc.max_effective_leverage <= 100.0


def test_configured_cap_intersects_symbol_and_global_ceiling() -> None:
    strong: dict[str, Any] = {
        "win_rate": 1.0,
        "profit_factor": 1e300,
        "closed_trade_count": 10**100,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 1.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e300,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=10**100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }

    sol = calculate_dynamic_risk_envelope(
        base_envelope=RiskEnvelope(max_effective_leverage=20.0),
        symbol="SOLUSDT",
        **strong,
    )
    btc = calculate_dynamic_risk_envelope(
        base_envelope=RiskEnvelope(max_effective_leverage=10.0),
        symbol="BTCUSDT",
        **strong,
    )

    assert sol.max_effective_leverage == 20.0
    assert btc.max_effective_leverage == 10.0


def test_exact_operator_symbol_tier_ceilings_remain_binding() -> None:
    arguments: dict[str, Any] = {
        "base_envelope": RiskEnvelope(max_effective_leverage=100.0),
        "win_rate": 1.0,
        "profit_factor": 1e300,
        "closed_trade_count": 10**100,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 1.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e300,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=10**100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }

    expected = {
        "BTCUSDT": 100.0,
        "ETHUSDT": 100.0,
        "SOLUSDT": 100.0,
        "LTCUSDT": 100.0,
        "XRPUSDT": 100.0,
        "DOGEUSDT": 25.0,
    }

    observed = {
        symbol: calculate_dynamic_risk_envelope(
            symbol=symbol,
            **arguments,
        ).max_effective_leverage
        for symbol in expected
    }

    assert observed == expected


def test_none_is_the_only_portfolio_global_symbol_identity() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=configured,
        symbol=None,
        win_rate=1.0,
        profit_factor=1e300,
        closed_trade_count=10**100,
        current_drawdown_pct=0.0,
        model_avg_confidence=1.0,
        paper_mode=True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e300,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=10**100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    )

    assert envelope.max_effective_leverage == 75.0


def test_blank_malformed_or_non_string_symbols_fail_closed_to_one_x() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "win_rate": 1.0,
        "profit_factor": 1e300,
        "closed_trade_count": 10**100,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 1.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e300,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=10**100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }

    for symbol in ("", "   ", "BTC/USDT", "USDT", 42, _ExplodingStringIdentity()):
        envelope = calculate_dynamic_risk_envelope(
            symbol=symbol,  # type: ignore[arg-type]
            **arguments,
        )
        assert envelope.max_effective_leverage == 1.0


def test_hostile_string_subclasses_cannot_spoof_symbol_identity() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "win_rate": 1.0,
        "profit_factor": 1e300,
        "closed_trade_count": 10**100,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 1.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e300,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=10**100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }

    hostile_symbols = (
        _ThrowingStringSubclass("BTCUSDT"),
        _WrongReturnTypeStringSubclass("BTCUSDT"),
        _SpoofingStringSubclass("not-the-symbol", "BTCUSDT"),
    )
    for hostile_symbol in hostile_symbols:
        envelope = calculate_dynamic_risk_envelope(
            symbol=hostile_symbol,
            **arguments,
        )
        assert envelope.max_effective_leverage == 1.0


def test_hostile_string_subclasses_cannot_spoof_provenance_sources() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    operating_baseline = RiskEnvelope().max_effective_leverage
    hostile_values = (
        _ThrowingStringSubclass("valid-looking-source"),
        _WrongReturnTypeStringSubclass("valid-looking-source"),
        _SpoofingStringSubclass("", "forged-valid-source"),
    )

    for source_field in (
        "after_cost_edge_evidence_source",
        "market_context_source",
    ):
        for hostile_value in hostile_values:
            envelope = calculate_dynamic_risk_envelope(
                base_envelope=configured,
                win_rate=0.70,
                profit_factor=2.0,
                # One lifecycle keeps the paper learning-exploration term below
                # the base envelope while the growth path stays observable: a
                # spoofed source must fail the growth gate, not hide behind
                # exploration leverage.
                closed_trade_count=1,
                current_drawdown_pct=0.0,
                model_avg_confidence=0.95,
                paper_mode=True,
                **_positive_pit_evidence(**{source_field: hostile_value}),
            )
            assert envelope.max_effective_leverage <= operating_baseline


def test_hostile_string_subclasses_cannot_spoof_any_pit_timestamp() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    operating_baseline = RiskEnvelope().max_effective_leverage

    valid_timestamp_by_field = {
        "edge_available_at": "2026-07-17T12:00:00Z",
        "market_context_available_at": "2026-07-17T12:00:01Z",
        "decision_time": "2026-07-17T12:00:02Z",
    }
    for timestamp_field, valid_timestamp in valid_timestamp_by_field.items():
        hostile_values = (
            _ThrowingStringSubclass(valid_timestamp),
            _WrongReturnTypeStringSubclass(valid_timestamp),
            _SpoofingStringSubclass("not-a-time", valid_timestamp),
        )
        for hostile_value in hostile_values:
            envelope = calculate_dynamic_risk_envelope(
                base_envelope=configured,
                win_rate=0.70,
                profit_factor=2.0,
                # One lifecycle: exploration leverage stays below the base
                # envelope, so a spoofed PIT timestamp must fail the growth
                # gate itself for this bound to hold.
                closed_trade_count=1,
                current_drawdown_pct=0.0,
                model_avg_confidence=0.95,
                paper_mode=True,
                **_positive_pit_evidence(**{timestamp_field: hostile_value}),
            )
            assert envelope.max_effective_leverage <= operating_baseline


def test_configured_cap_is_not_the_starting_leverage_grant() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)

    envelope = calculate_dynamic_risk_envelope(
        base_envelope=configured,
        win_rate=0.70,
        profit_factor=2.0,
        # A starting grant is judged at the start: one lifecycle keeps the
        # paper learning-exploration term below the base envelope, so the
        # configured cap alone must not move leverage off the base.
        closed_trade_count=1,
        current_drawdown_pct=0.0,
        model_avg_confidence=0.95,
        paper_mode=True,
    )

    assert envelope.max_effective_leverage == RiskEnvelope().max_effective_leverage
    assert envelope.max_effective_leverage < configured.max_effective_leverage


def test_favorable_summary_metrics_alone_cannot_grow_leverage() -> None:
    base = RiskEnvelope()

    envelope = calculate_dynamic_risk_envelope(
        base_envelope=base,
        win_rate=0.70,
        profit_factor=2.0,
        closed_trade_count=100,
        current_drawdown_pct=0.0,
        model_avg_confidence=0.95,
        paper_mode=True,
    )

    assert envelope.max_effective_leverage == base.max_effective_leverage


def test_non_positive_after_cost_lower_bound_cannot_grow_leverage() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)

    for lower_bound in (0.0, -0.01):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=configured,
            win_rate=0.70,
            profit_factor=2.0,
            # One lifecycle keeps exploration below the base envelope; a
            # non-positive LCB must fail the growth gate itself.
            closed_trade_count=1,
            current_drawdown_pct=0.0,
            model_avg_confidence=0.95,
            paper_mode=True,
            **_positive_pit_evidence(
                after_cost_edge_lower_bound_bps=lower_bound,
            ),
        )

        assert envelope.max_effective_leverage <= operating_baseline


def test_after_cost_edge_scale_is_required_and_must_be_positive() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)

    for scale in (None, 0.0, -1.0):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=configured,
            win_rate=0.70,
            profit_factor=2.0,
            # One lifecycle keeps exploration below the base envelope; a
            # missing/non-positive scale must fail the growth gate itself.
            closed_trade_count=1,
            current_drawdown_pct=0.0,
            model_avg_confidence=0.95,
            paper_mode=True,
            **_positive_pit_evidence(after_cost_edge_scale_bps=scale),
        )

        assert envelope.max_effective_leverage <= operating_baseline


def test_edge_scale_must_match_finite_data_resolution_contract() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)
    smallest_positive = math.nextafter(0.0, 1.0)

    for overrides in (
        {"after_cost_edge_resolution_bps": None},
        {"after_cost_edge_resolution_bps": 0.0},
        {
            "after_cost_edge_scale_bps": 0.005,
            "after_cost_edge_resolution_bps": 0.01,
        },
        {
            "after_cost_edge_scale_bps": smallest_positive,
            "after_cost_edge_resolution_bps": smallest_positive,
        },
        {
            "after_cost_edge_scale_bps": smallest_positive,
            "after_cost_edge_resolution_bps": 0.01,
        },
    ):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=configured,
            win_rate=0.70,
            profit_factor=2.0,
            # One lifecycle keeps exploration below the base envelope; an
            # under-resolved scale must fail the growth gate itself.
            closed_trade_count=1,
            current_drawdown_pct=0.0,
            model_avg_confidence=0.95,
            paper_mode=True,
            **_positive_pit_evidence(**overrides),
        )

        assert envelope.max_effective_leverage <= operating_baseline


def test_after_cost_lcb_magnitude_scales_growth_continuously() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "win_rate": 0.70,
        "profit_factor": 2.0,
        # One lifecycle keeps the paper learning-exploration term below the
        # base envelope, so the ordering below observes the growth path alone.
        "closed_trade_count": 1,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 0.95,
        "paper_mode": True,
    }

    infinitesimal = calculate_dynamic_risk_envelope(
        **arguments,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=1e-12,
            after_cost_edge_scale_bps=3.5,
        ),
    )
    moderate = calculate_dynamic_risk_envelope(
        **arguments,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=3.5,
            after_cost_edge_scale_bps=3.5,
        ),
    )
    strong = calculate_dynamic_risk_envelope(
        **arguments,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=35.0,
            after_cost_edge_scale_bps=3.5,
        ),
    )

    assert infinitesimal.max_effective_leverage < moderate.max_effective_leverage
    assert moderate.max_effective_leverage < strong.max_effective_leverage


def test_after_cost_lcb_is_nondecreasing_from_zero() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "win_rate": 0.70,
        "profit_factor": 2.0,
        # One lifecycle keeps the paper learning-exploration term below the
        # base envelope, so the zero-LCB case still lands exactly on the base.
        "closed_trade_count": 1,
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": 0.95,
        "paper_mode": True,
    }
    lower_bounds = (0.0, math.nextafter(0.0, 1.0), 1e-12, 3.5)
    leverages = [
        calculate_dynamic_risk_envelope(
            **arguments,
            **_positive_pit_evidence(
                after_cost_edge_lower_bound_bps=lower_bound,
                after_cost_edge_scale_bps=3.5,
                after_cost_edge_resolution_bps=0.01,
            ),
        ).max_effective_leverage
        for lower_bound in lower_bounds
    ]

    assert leverages[0] == RiskEnvelope().max_effective_leverage
    assert leverages == sorted(leverages)


def test_future_or_naive_evidence_timestamps_cannot_grow_leverage() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)

    for timestamp_overrides in (
        {"edge_available_at": "2026-07-17T12:00:03Z"},
        {"market_context_available_at": "2026-07-17T12:00:03Z"},
        {"edge_available_at": "2026-07-17T12:00:00"},
        {"decision_time": "2026-07-17T12:00:02"},
    ):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=configured,
            win_rate=0.70,
            profit_factor=2.0,
            # One lifecycle keeps exploration below the base envelope; future
            # or naive timestamps must fail the growth gate itself.
            closed_trade_count=1,
            current_drawdown_pct=0.0,
            model_avg_confidence=0.95,
            paper_mode=True,
            **_positive_pit_evidence(**timestamp_overrides),
        )

        assert envelope.max_effective_leverage <= operating_baseline


def test_missing_edge_provenance_or_count_cannot_grow_leverage() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)

    for evidence_overrides in (
        {"after_cost_edge_evidence_source": ""},
        {"after_cost_edge_evidence_count": None},
        {"after_cost_edge_evidence_count": 0},
        {"market_context_source": ""},
    ):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=configured,
            win_rate=0.70,
            profit_factor=2.0,
            # One lifecycle keeps exploration below the base envelope; missing
            # provenance or counts must fail the growth gate itself.
            closed_trade_count=1,
            current_drawdown_pct=0.0,
            model_avg_confidence=0.95,
            paper_mode=True,
            **_positive_pit_evidence(**evidence_overrides),
        )

        assert envelope.max_effective_leverage <= operating_baseline


def test_adverse_liquidity_and_regime_context_withholds_growth_smoothly() -> None:
    operating_baseline = RiskEnvelope().max_effective_leverage
    configured = RiskEnvelope(max_effective_leverage=75.0)
    favorable = calculate_dynamic_risk_envelope(
        base_envelope=configured,
        win_rate=0.70,
        profit_factor=2.0,
        # One lifecycle keeps the paper learning-exploration term below the
        # base envelope, so context quality alone separates these envelopes.
        closed_trade_count=1,
        current_drawdown_pct=0.0,
        model_avg_confidence=0.95,
        paper_mode=True,
        **_positive_pit_evidence(liquidity_score=0.95, regime_quality_score=0.95),
    )
    adverse = calculate_dynamic_risk_envelope(
        base_envelope=configured,
        win_rate=0.70,
        profit_factor=2.0,
        closed_trade_count=1,
        current_drawdown_pct=0.0,
        model_avg_confidence=0.95,
        paper_mode=True,
        **_positive_pit_evidence(liquidity_score=0.05, regime_quality_score=0.05),
    )

    assert favorable.max_effective_leverage > operating_baseline
    assert adverse.max_effective_leverage == operating_baseline
    assert adverse.max_effective_leverage < favorable.max_effective_leverage


def test_leverage_is_continuous_at_favorable_growth_drawdown_boundary() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    boundary = 0.007775
    epsilon = 1e-9
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "symbol": "BTCUSDT",
        "win_rate": 1.0,
        "profit_factor": 1.0,
        "closed_trade_count": 100,
        "model_avg_confidence": 0.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=311.0 / 89.0,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }

    leverages = [
        calculate_dynamic_risk_envelope(
            current_drawdown_pct=drawdown,
            **arguments,
        ).max_effective_leverage
        for drawdown in (boundary - epsilon, boundary, boundary + epsilon)
    ]

    # At the favorable-growth boundary the growth path contributes exactly the
    # base envelope; with 100 lifecycles the PAPER LEARNING EXPLORATION term
    # (progress * confidence_quality * exp(losing_pressure) * drawdown headroom,
    # capped at half the ceiling distance) is the binding leverage.  Both terms
    # are continuous in drawdown, so the max() stays continuous across the
    # boundary.  Recomputed from the fixture inputs (win_rate=1.0 and
    # profit_factor=1.0 give non-negative realized evidence, so
    # losing_evidence_pressure == 0).
    exploration_progress = 100 / (100 + 25.0)
    confidence_quality = 0.5 + (0.5 * 0.0)
    drawdown_pressure = boundary / max(RiskEnvelope().max_daily_drawdown_pct, 1e-9)
    exploration_capacity = (
        exploration_progress
        * confidence_quality
        * math.exp(0.0)
        * max(0.0, 1.0 - drawdown_pressure)
    )
    expected_boundary_leverage = 1.0 + (0.5 * exploration_capacity * (75.0 - 1.0))
    assert expected_boundary_leverage > RiskEnvelope().max_effective_leverage
    assert leverages[0] >= leverages[1] >= leverages[2]
    assert math.isclose(
        leverages[1],
        expected_boundary_leverage,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert max(abs(value - leverages[1]) for value in leverages) < 2e-6


def test_leverage_drawdown_sweep_is_nondecreasing_in_safety() -> None:
    configured = RiskEnvelope(max_effective_leverage=75.0)
    arguments: dict[str, Any] = {
        "base_envelope": configured,
        "symbol": "BTCUSDT",
        "win_rate": 1.0,
        "profit_factor": 1.0,
        "closed_trade_count": 100,
        "model_avg_confidence": 0.0,
        "paper_mode": True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=311.0 / 89.0,
            after_cost_edge_scale_bps=1.0,
            after_cost_edge_evidence_count=100,
            liquidity_score=1.0,
            regime_quality_score=1.0,
        ),
    }
    drawdowns = [index / 100_000.0 for index in range(0, 1_601)]
    leverages = [
        calculate_dynamic_risk_envelope(
            current_drawdown_pct=drawdown,
            **arguments,
        ).max_effective_leverage
        for drawdown in drawdowns
    ]

    assert all(left >= right for left, right in zip(leverages, leverages[1:], strict=False))


def test_invalid_growth_evidence_applies_drawdown_contraction_once() -> None:
    base = RiskEnvelope()
    drawdown = 0.01

    envelope = calculate_dynamic_risk_envelope(
        base_envelope=base,
        win_rate=0.70,
        profit_factor=2.0,
        closed_trade_count=100,
        current_drawdown_pct=drawdown,
        model_avg_confidence=0.95,
        paper_mode=True,
    )

    expected = base.max_effective_leverage * math.exp(-(drawdown / base.max_daily_drawdown_pct))
    assert math.isclose(envelope.max_effective_leverage, expected, rel_tol=0.0, abs_tol=1e-15)


def test_non_finite_inputs_fail_closed_without_nan_or_exception() -> None:
    base = RiskEnvelope()

    for non_finite in (float("nan"), float("inf"), float("-inf")):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=base,
            win_rate=non_finite,
            profit_factor=non_finite,
            closed_trade_count=non_finite,  # type: ignore[arg-type]
            current_drawdown_pct=non_finite,
            model_avg_confidence=non_finite,
            paper_mode=True,
            **_positive_pit_evidence(
                after_cost_edge_lower_bound_bps=non_finite,
                after_cost_edge_scale_bps=non_finite,
                after_cost_edge_resolution_bps=non_finite,
                after_cost_edge_evidence_count=non_finite,
                liquidity_score=non_finite,
                regime_quality_score=non_finite,
            ),
        )

        assert math.isfinite(envelope.max_total_portfolio_risk_pct)
        assert math.isfinite(envelope.max_loss_per_trade_pct)
        assert math.isfinite(envelope.max_effective_leverage)
        assert math.isfinite(envelope.min_available_margin_buffer_pct)
        assert math.isfinite(envelope.min_liquidation_buffer_bps)
        assert envelope.max_effective_leverage <= base.max_effective_leverage


def test_huge_integer_inputs_fail_closed_without_overflow() -> None:
    huge = 10**400
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=RiskEnvelope(
            max_effective_leverage=huge,  # type: ignore[arg-type]
            min_liquidation_buffer_bps=huge,  # type: ignore[arg-type]
        ),
        win_rate=huge,  # type: ignore[arg-type]
        profit_factor=huge,  # type: ignore[arg-type]
        closed_trade_count=huge,
        current_drawdown_pct=huge,  # type: ignore[arg-type]
        model_avg_confidence=huge,  # type: ignore[arg-type]
        paper_mode=True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=huge,
            after_cost_edge_scale_bps=huge,
            after_cost_edge_resolution_bps=huge,
            after_cost_edge_evidence_count=huge,
            liquidity_score=huge,
            regime_quality_score=huge,
        ),
    )

    assert math.isfinite(envelope.max_effective_leverage)
    assert math.isfinite(envelope.min_liquidation_buffer_bps)
    assert envelope.max_effective_leverage == 1.0


def test_hostile_numeric_conversion_is_totalized_and_fails_closed() -> None:
    hostile = _ExplodingFloat()
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=RiskEnvelope(
            max_effective_leverage=hostile,  # type: ignore[arg-type]
            min_liquidation_buffer_bps=hostile,  # type: ignore[arg-type]
        ),
        symbol="BTCUSDT",
        win_rate=hostile,  # type: ignore[arg-type]
        profit_factor=hostile,  # type: ignore[arg-type]
        closed_trade_count=hostile,  # type: ignore[arg-type]
        current_drawdown_pct=hostile,  # type: ignore[arg-type]
        model_avg_confidence=hostile,  # type: ignore[arg-type]
        paper_mode=True,
        **_positive_pit_evidence(
            after_cost_edge_lower_bound_bps=hostile,
            after_cost_edge_scale_bps=hostile,
            after_cost_edge_resolution_bps=hostile,
            after_cost_edge_evidence_count=hostile,
            liquidity_score=hostile,
            regime_quality_score=hostile,
        ),
    )

    assert math.isfinite(envelope.max_effective_leverage)
    assert math.isfinite(envelope.min_liquidation_buffer_bps)
    assert envelope.max_effective_leverage == 1.0


def test_invalid_paper_base_values_are_sanitized_defensively() -> None:
    invalid_base = RiskEnvelope(
        max_total_portfolio_risk_pct=float("nan"),
        max_single_symbol_exposure_pct=float("inf"),
        max_daily_drawdown_pct=float("nan"),
        max_loss_per_trade_pct=float("-inf"),
        min_available_margin_buffer_pct=float("nan"),
        max_correlation_exposure_pct=float("nan"),
        min_liquidation_buffer_bps=float("nan"),
        max_effective_leverage=float("inf"),
        tail_loss_multiplier=float("nan"),
        emergency_absolute_cap_usdt=float("nan"),
    )

    envelope = calculate_dynamic_risk_envelope(
        base_envelope=invalid_base,
        paper_mode=True,
    )

    assert envelope.max_total_portfolio_risk_pct == 0.0
    assert envelope.max_single_symbol_exposure_pct == 0.0
    assert envelope.max_daily_drawdown_pct == 0.0
    assert envelope.max_loss_per_trade_pct == 0.0
    assert envelope.max_correlation_exposure_pct == 0.0
    assert envelope.max_effective_leverage == 1.0
    assert envelope.min_available_margin_buffer_pct == 1.0
    assert envelope.min_liquidation_buffer_bps >= 10_000.0
    assert envelope.emergency_absolute_cap_usdt == 0.0


def test_hostile_scalar_class_metadata_is_never_observed() -> None:
    _ExplodingClassObservation.class_observation_calls = 0
    hostile = _ExplodingClassObservation()
    base = RiskEnvelope(max_effective_leverage=hostile)  # type: ignore[arg-type]

    from_evidence = calculate_dynamic_risk_envelope(
        base_envelope=RiskEnvelope(max_effective_leverage=75.0),
        win_rate=hostile,  # type: ignore[arg-type]
        paper_mode=True,
        **_positive_pit_evidence(
            after_cost_edge_scale_bps=hostile,
        ),
    )
    from_base = calculate_dynamic_risk_envelope(
        base_envelope=base,
        paper_mode=True,
    )

    assert from_evidence.max_effective_leverage == 3.0
    assert from_base.max_effective_leverage == 1.0
    assert _ExplodingClassObservation.class_observation_calls == 0


def test_malformed_paper_modes_fail_closed_without_truth_coercion() -> None:
    _ExplodingPaperMode.bool_calls = 0

    for invalid_mode in (_FalseyPaperMode(), _TruthyPaperMode(), _ExplodingPaperMode(), 0, 1):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=RiskEnvelope(max_effective_leverage=75.0),
            paper_mode=invalid_mode,  # type: ignore[arg-type]
        )

        assert envelope.max_total_portfolio_risk_pct == 0.0
        assert envelope.max_single_symbol_exposure_pct == 0.0
        assert envelope.max_daily_drawdown_pct == 0.0
        assert envelope.max_loss_per_trade_pct == 0.0
        assert envelope.max_correlation_exposure_pct == 0.0
        assert envelope.max_effective_leverage == 1.0
        assert envelope.min_available_margin_buffer_pct == 1.0
        assert envelope.min_liquidation_buffer_bps == 10_000.0
        assert envelope.emergency_absolute_cap_usdt == 0.0

    assert _ExplodingPaperMode.bool_calls == 0


def test_hostile_risk_envelope_subclass_is_rejected_without_observation() -> None:
    _HostileRiskEnvelope.bool_calls = 0
    _HostileRiskEnvelope.attribute_calls = 0
    hostile = _HostileRiskEnvelope(max_effective_leverage=75.0)

    for mode in (True, False):
        envelope = calculate_dynamic_risk_envelope(
            base_envelope=hostile,
            paper_mode=mode,
        )

        assert envelope.max_total_portfolio_risk_pct == 0.0
        assert envelope.max_effective_leverage == 1.0
        assert envelope.min_available_margin_buffer_pct == 1.0
        assert envelope.min_liquidation_buffer_bps == 10_000.0

    assert _HostileRiskEnvelope.bool_calls == 0
    assert _HostileRiskEnvelope.attribute_calls == 0


def test_live_mode_never_uses_paper_adaptation() -> None:
    base = RiskEnvelope()

    assert (
        calculate_dynamic_risk_envelope(
            base_envelope=base,
            win_rate=0.99,
            profit_factor=10.0,
            closed_trade_count=10_000,
            model_avg_confidence=0.99,
            paper_mode=False,
        )
        == base
    )
