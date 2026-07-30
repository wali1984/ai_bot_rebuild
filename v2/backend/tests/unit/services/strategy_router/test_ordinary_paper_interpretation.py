from __future__ import annotations

# Importing the established admission fixture first intentionally initializes
# the trainer package before the admission/router pair; sorting this block
# reintroduces the package's pre-existing circular-import collection hazard.
# ruff: noqa: I001

from copy import deepcopy
import inspect
from typing import Any

import pytest

from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    _assess,
    ordinary_source,
)
from v2.backend.app.services.ordinary_paper_admission import (
    OrdinaryPaperAdmissionResult,
    revalidate_ordinary_paper_transport,
)
from v2.backend.app.services.strategy_router import ordinary_paper_interpretation as subject
from v2.backend.app.services.strategy_router.ordinary_paper_interpretation import (
    ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA,
    bind_ordinary_paper_router_envelope,
    interpret_ordinary_paper_router_result,
)
from v2.backend.app.services.strategy_router.service import MODE_REDUCE_SIZE, route_strategy


def _admission(
    *,
    market_score: float = 90.0,
    trust_score: float = 0.8,
    sweep_risk: float = 0.2,
    microstructure_action: str = "ALLOW",
    confidence: float = 0.8,
    direction: str = "long",
) -> OrdinaryPaperAdmissionResult:
    source, replay = ordinary_source(
        confidence=confidence,
        coverage=80.0,
        edge_bps=(12.0 if direction == "long" else -12.0),
        microstructure_trust_score=trust_score,
        sweep_risk_score=sweep_risk,
        microstructure_action=microstructure_action,
        selected_action=direction,
    )
    result = _assess(
        source,
        replay,
        market_score=market_score,
        trust_score=trust_score,
        sweep_risk=sweep_risk,
        action=microstructure_action,
    )
    assert result.accepted is True
    return result


def _router_input(
    admission: OrdinaryPaperAdmissionResult,
    *,
    action: str = "long",
    position: str = "FLAT",
    masa_confidence: float = 0.8,
    execution_probability: float = 0.8,
    drawdown_bps: float = 100.0,
    volatility: float = 0.1,
    liquidity: float = 0.8,
    directions: tuple[str, ...] = ("long", "long", "long"),
) -> dict[str, Any]:
    evidence = admission.evidence
    assert evidence is not None
    timeframes = ("4h", "1h", "1m")
    predictions: list[dict[str, Any]] = []
    for timeframe, direction in zip(timeframes, directions, strict=False):
        row = deepcopy(evidence)
        row.update(
            {
                "timeframe": timeframe,
                "selected_action": direction,
                "confidence_calibrated": masa_confidence,
                "expected_move_after_cost_bps": (12.0 if direction == "long" else -12.0),
            }
        )
        predictions.append(row)
    envelope = deepcopy(evidence)
    envelope.update(
        {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "microstructure_trust_score": evidence["orchestrator_microstructure_trust_score"],
            "microstructure_action": evidence["orchestrator_microstructure_action"],
            "sweep_risk_score": evidence["orchestrator_sweep_risk_score"],
        }
    )
    return {
        "market_state_envelope": envelope,
        "masa_predictions": predictions,
        "ppo_proposed_action": action,
        "current_position_state": position,
        "recent_execution_success_metrics": {
            "execution_success_probability": execution_probability,
            "closed_trade_outcome_count": 10,
            "clean_closed_trade_outcome_count": 10,
        },
        "volatility_liquidity_state": {
            "volatility": volatility,
            "liquidity_score": liquidity,
            "bid_ask_spread_bps": 1.0,
        },
        "data_quality_score": evidence["orchestrator_market_state_integrity_score"],
        "current_drawdown_risk_state": {"current_drawdown_bps": drawdown_bps},
    }


def _run(
    admission: OrdinaryPaperAdmissionResult | None = None,
    *,
    action: str = "long",
    position: str = "FLAT",
    masa_confidence: float = 0.8,
    execution_probability: float = 0.8,
    drawdown_bps: float = 100.0,
    volatility: float = 0.1,
    liquidity: float = 0.8,
    directions: tuple[str, ...] = ("long", "long", "long"),
    mutate_input: Any = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    accepted = admission or _admission()
    material = _router_input(
        accepted,
        action=action,
        position=position,
        masa_confidence=masa_confidence,
        execution_probability=execution_probability,
        drawdown_bps=drawdown_bps,
        volatility=volatility,
        liquidity=liquidity,
        directions=directions,
    )
    if mutate_input is not None:
        mutate_input(material)
    router = route_strategy(**deepcopy(material))
    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=accepted,
        proposed_action=action,
        current_position_state=position,
    )
    return result, router, material


def test_nonordinary_candidate_is_passthrough_without_admission_claim() -> None:
    unclaimed = revalidate_ordinary_paper_transport({})
    material = _router_input(_admission())
    router = route_strategy(**deepcopy(material))

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=unclaimed,
        proposed_action="long",
        current_position_state="FLAT",
    )

    assert result["ordinary_paper_interpretation_claimed"] is False
    assert result["ordinary_paper_interpretation_applied"] is False
    assert result["routes_to_live"] is False


def test_fabricated_admission_mapping_cannot_authorize_interpretation() -> None:
    admission = _admission()
    material = _router_input(admission)
    router = route_strategy(**deepcopy(material))

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission={"claimed": True, "accepted": True},  # type: ignore[arg-type]
        proposed_action="long",
        current_position_state="FLAT",
    )

    assert result["strategy_trade_allowed"] is False
    assert "ORDINARY_PAPER_ADMISSION_RESULT_EXACT_TYPE_REQUIRED" in result["hard_reasons"]


def test_exact_admission_binds_sparse_router_envelope_without_mutating_source() -> None:
    admission = _admission()
    sparse = {"symbol": "WRONG", "unrelated": "preserved"}

    bound = bind_ordinary_paper_router_envelope(
        market_state_envelope=sparse,
        ordinary_admission=admission,
    )

    assert sparse == {"symbol": "WRONG", "unrelated": "preserved"}
    assert bound["symbol"] == admission.evidence["symbol"]
    assert bound["prediction_id"] == admission.evidence["prediction_id"]
    assert bound["decision_time"] == admission.evidence["decision_time"]
    assert bound["ordinary_paper_router_envelope_binding_status"] == (
        "BOUND_EXACT_ADMISSION"
    )
    assert bound["routes_to_live"] is False
    assert bound["places_real_order"] is False


def test_fabricated_admission_cannot_bind_router_envelope() -> None:
    source = {"symbol": "BTCUSDT", "decision_time": "2026-01-01T00:00:00Z"}

    bound = bind_ordinary_paper_router_envelope(
        market_state_envelope=source,
        ordinary_admission={"claimed": True, "accepted": True},  # type: ignore[arg-type]
    )

    assert bound["symbol"] == "BTCUSDT"
    assert bound["ordinary_paper_router_envelope_binding_status"] == "REJECTED"
    assert "prediction_id" not in bound


@pytest.mark.parametrize(
    ("position", "action", "expected_reason"),
    [
        ("LONG", "long", "ORDINARY_ROUTER_POSITION_NOT_FLAT_FOR_NEW_ENTRY"),
        ("FLAT", "hold", "ORDINARY_ROUTER_ACTION_NOT_DIRECTIONAL"),
    ],
)
def test_invalid_position_or_nondirectional_action_remains_hard(
    position: str,
    action: str,
    expected_reason: str,
) -> None:
    result, _, _ = _run(position=position, action=action)

    assert result["strategy_trade_allowed"] is False
    assert expected_reason in result["hard_reasons"]


def test_false_flat_claim_is_rejected_against_authoritative_state() -> None:
    admission = _admission()
    material = _router_input(admission, position="FLAT")
    router = route_strategy(**deepcopy(material))

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=admission,
        proposed_action="long",
        current_position_state="LONG",
    )

    assert result["strategy_trade_allowed"] is False
    assert "ORDINARY_ROUTER_INPUT_POSITION_STATE_MISMATCH" in result["hard_reasons"]
    assert "ORDINARY_ROUTER_POSITION_NOT_FLAT_FOR_NEW_ENTRY" in result["hard_reasons"]


def test_future_masa_input_clock_remains_hard() -> None:
    def mutate(material: dict[str, Any]) -> None:
        material["masa_predictions"][0]["feature_cutoff"] = "2026-07-19T00:00:00Z"

    result, _, _ = _run(mutate_input=mutate)

    assert result["strategy_trade_allowed"] is False
    assert "ORDINARY_ROUTER_MASA_PIT_CLOCK_FUTURE:feature_cutoff" in result["hard_reasons"]


def test_negative_performance_bucket_remains_hard() -> None:
    def mutate(material: dict[str, Any]) -> None:
        material["recent_execution_success_metrics"]["bucket_performance"] = {
            "profit_factor": 0.9,
            "expectancy_bps": -1.0,
            "sample_count": 10,
        }

    result, _, _ = _run(mutate_input=mutate)

    assert result["strategy_trade_allowed"] is False
    assert "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE" in result["hard_reasons"]


@pytest.mark.parametrize(
    ("direction", "aligned_directions"),
    [
        ("long", ("long", "long", "long")),
        ("short", ("short", "short", "short")),
    ],
)
def test_paper_loss_bucket_quarantine_becomes_continuous_reduce_size_not_hard_block(
    direction: str,
    aligned_directions: tuple[str, str, str],
) -> None:
    """CG-F061: a merely-recently-losing bucket must reduce sizing, not veto.

    RED (pre-fix) behavior: a ``paper_loss_quarantine_blocked_bucket_keys``
    match on the candidate's own side forced ``PAPER_LOSS_BUCKET_QUARANTINE``
    into ``hard_reasons`` and ``strategy_trade_allowed`` was False.

    GREEN (post-fix) behavior asserted here: the candidate remains tradeable
    at a reduced ``continuous_weight`` (REDUCE_SIZE), carrying a bounded
    Category-E continuous risk input, symmetric for long and short.
    """

    def mutate(material: dict[str, Any]) -> None:
        material["market_state_envelope"]["paper_loss_quarantine_status"] = (
            "ACTIVE_WITH_QUARANTINES"
        )
        material["market_state_envelope"]["paper_loss_quarantine_blocked_bucket_keys"] = [
            f"side:{direction}"
        ]

    admission = _admission(direction=direction)
    baseline, _, _ = _run(admission, action=direction, directions=aligned_directions)
    quarantined, router, _ = _run(
        admission,
        action=direction,
        directions=aligned_directions,
        mutate_input=mutate,
    )

    # The authoritative router (legacy comparator, service.py) is untouched:
    # it still hard no-trades its own selected_mode/block_reason (see
    # test_paper_loss_quarantine_keys_force_no_trade_before_allocation).
    assert router["block_reason"] == "PAPER_LOSS_BUCKET_QUARANTINE"
    assert f"side:{direction}" in router["paper_loss_quarantine_matched_bucket_keys"]

    # The ordinary-paper continuous interpretation no longer treats that
    # router block as fatal: it is tradeable, at reduced size.
    assert baseline["strategy_trade_allowed"] is True
    assert quarantined["strategy_trade_allowed"] is True
    assert quarantined["effective_mode"] == MODE_REDUCE_SIZE
    assert "PAPER_LOSS_BUCKET_QUARANTINE" not in quarantined["hard_reasons"]
    assert "PAPER_LOSS_BUCKET_QUARANTINE" in quarantined["softened_reasons"]
    assert quarantined["paper_loss_quarantine_category_e_continuous"] is True
    assert quarantined["paper_loss_quarantine_authority_classification"] == (
        "CATEGORY_E_POLICY_PERFORMANCE"
    )
    assert quarantined["paper_loss_quarantine_adaptive_policy_role"] == (
        "CONTINUOUS_OBJECTIVE_RISK_INPUT"
    )
    assert quarantined["paper_loss_quarantine_hard_trading_authority"] is False
    assert quarantined["paper_loss_quarantine_risk_multiplier"] > 1.0
    assert quarantined["paper_loss_quarantine_adaptive_penalty_required"] is True

    # Bounded severity that reduces (never zeroes) downstream sizing
    # relative to an otherwise-identical, unquarantined candidate.
    assert 0.0 < quarantined["continuous_weight"] < baseline["continuous_weight"]


def test_genuinely_catastrophic_bucket_performance_still_hard_blocks_alongside_quarantine() -> None:
    """A negative rolling profit-factor/expectancy bucket is a genuinely
    catastrophic condition and remains a hard veto even when a merely-
    recently-losing quarantine match is ALSO present -- proving the two are
    distinguished rather than the catastrophic control being weakened.
    """

    def mutate(material: dict[str, Any]) -> None:
        material["market_state_envelope"]["paper_loss_quarantine_status"] = (
            "ACTIVE_WITH_QUARANTINES"
        )
        material["market_state_envelope"]["paper_loss_quarantine_blocked_bucket_keys"] = [
            "side:long"
        ]
        material["recent_execution_success_metrics"]["bucket_performance"] = {
            "profit_factor": 0.9,
            "expectancy_bps": -1.0,
            "sample_count": 10,
        }

    result, _, _ = _run(mutate_input=mutate)

    assert result["strategy_trade_allowed"] is False
    assert "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE" in result["hard_reasons"]
    assert "PAPER_LOSS_BUCKET_QUARANTINE" not in result["hard_reasons"]
    assert "PAPER_LOSS_BUCKET_QUARANTINE" in result["softened_reasons"]


def test_absent_optional_magnitudes_are_explicit_and_not_promoted_to_hard_inputs() -> None:
    def mutate(material: dict[str, Any]) -> None:
        material["recent_execution_success_metrics"]["execution_success_probability"] = None
        material["volatility_liquidity_state"].pop("volatility")
        material["volatility_liquidity_state"].pop("liquidity_score")

    result, _, _ = _run(mutate_input=mutate)

    assert result["strategy_trade_allowed"] is True
    assert result["missing_optional_factors"] == [
        "execution_success_probability",
        "liquidity_score",
        "volatility_fraction",
    ]
    assert "execution_success_probability" not in result["continuous_factors"]
    assert "volatility_headroom" not in result["continuous_factors"]
    assert "liquidity_score" not in result["continuous_factors"]


def test_supplied_out_of_domain_optional_magnitude_remains_hard() -> None:
    result, _, _ = _run(liquidity=1.1)

    assert result["strategy_trade_allowed"] is False
    assert "ORDINARY_ROUTER_LIQUIDITY_SCORE_OUTSIDE_UNIT_INTERVAL" in result["hard_reasons"]


def test_timeframe_conflict_is_soft_only_with_directional_edge_proof() -> None:
    result, _, _ = _run(directions=("short", "long", "long"))

    assert result["strategy_trade_allowed"] is True
    assert result["continuous_factors"]["timeframe_direction_alignment"] == pytest.approx(2.0 / 3.0)
    assert "HTF_DIRECTION_CONFLICT" in result["softened_reasons"]


def test_legacy_microstructure_no_trade_is_soft_after_authenticated_reduction() -> None:
    admission = _admission(
        microstructure_action="NO_TRADE",
        trust_score=0.8,
        sweep_risk=0.2,
    )
    result, router, _ = _run(admission)

    assert result["strategy_trade_allowed"] is True
    assert "MICROSTRUCTURE_ACTION_NO_TRADE" in result["softened_reasons"]
    assert result["original_router_telemetry"] == router


def test_unknown_reason_code_fails_closed_even_without_block_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _admission()
    material = _router_input(admission)
    router = route_strategy(**deepcopy(material))
    router["reason_codes"] = [
        *router.get("reason_codes", []),
        "NEW_UNCLASSIFIED_ROUTER_REASON",
    ]
    monkeypatch.setattr(subject, "route_strategy", lambda **_: deepcopy(router))

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=admission,
        proposed_action="long",
        current_position_state="FLAT",
    )

    assert result["strategy_trade_allowed"] is False
    assert "UNCLASSIFIED_ROUTER_REASON:NEW_UNCLASSIFIED_ROUTER_REASON" in result["hard_reasons"]


def test_explicit_benign_router_reason_remains_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _admission()
    material = _router_input(admission)
    router = route_strategy(**deepcopy(material))
    router["reason_codes"] = [
        *router.get("reason_codes", []),
        "PAPER_MAJOR_MOVE_EVIDENCE_BREAKOUT",
    ]
    monkeypatch.setattr(subject, "route_strategy", lambda **_: deepcopy(router))

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=admission,
        proposed_action="long",
        current_position_state="FLAT",
    )

    assert result["strategy_trade_allowed"] is True
    assert "PAPER_MAJOR_MOVE_EVIDENCE_BREAKOUT" in result["telemetry_reasons"]


def test_coherently_resealed_router_output_cannot_replace_exact_replay() -> None:
    admission = _admission()
    material = _router_input(admission)
    router = route_strategy(**deepcopy(material))
    router["reason_codes"] = []
    router["block_reason"] = None
    router["selected_mode"] = "trend_mode"

    result = interpret_ordinary_paper_router_result(
        router_result=router,
        router_input_material=material,
        ordinary_admission=admission,
        proposed_action="long",
        current_position_state="FLAT",
    )

    assert result["strategy_trade_allowed"] is False
    assert "ORDINARY_ROUTER_RESULT_MISMATCH_EXACT_INPUT_REPLAY" in result["hard_reasons"]


@pytest.mark.parametrize(
    ("field", "low", "high", "lower_is_better"),
    [
        ("ppo_confidence", 0.2, 0.8, False),
        ("masa_confidence", 0.2, 0.8, False),
        ("liquidity", 0.2, 0.8, False),
        ("microstructure_trust", 0.2, 0.8, False),
        ("sweep_risk", 0.2, 0.8, True),
        ("drawdown_bps", 100.0, 1_000.0, True),
    ],
)
def test_router_weight_is_monotonic_in_bound_market_magnitudes(
    field: str,
    low: float,
    high: float,
    lower_is_better: bool,
) -> None:
    def result_for(value: float) -> dict[str, Any]:
        if field == "ppo_confidence":
            result, _, _ = _run(_admission(confidence=value))
        elif field == "microstructure_trust":
            result, _, _ = _run(_admission(trust_score=value))
        elif field == "sweep_risk":
            result, _, _ = _run(_admission(sweep_risk=value))
        else:
            result, _, _ = _run(**{field: value})
        return result

    low_result = result_for(low)
    high_result = result_for(high)

    assert low_result["strategy_trade_allowed"] is True
    assert high_result["strategy_trade_allowed"] is True
    if lower_is_better:
        assert low_result["continuous_weight"] > high_result["continuous_weight"]
    else:
        assert low_result["continuous_weight"] < high_result["continuous_weight"]


@pytest.mark.parametrize(
    ("field", "old_threshold"),
    [
        ("market_score", 80.0),
        ("masa_confidence", 0.55),
        ("ppo_confidence", 0.52),
        ("execution_probability", 0.45),
        ("drawdown_bps", 250.0),
        ("volatility", 0.02),
        ("liquidity", 0.35),
        ("microstructure_trust", 0.45),
        ("sweep_risk", 0.75),
    ],
)
def test_epsilon_around_legacy_threshold_has_no_sizing_cliff(
    field: str,
    old_threshold: float,
) -> None:
    epsilon = 1e-9

    def result_for(value: float) -> dict[str, Any]:
        if field == "market_score":
            result, _, _ = _run(_admission(market_score=value))
        elif field == "ppo_confidence":
            result, _, _ = _run(_admission(confidence=value))
        elif field == "microstructure_trust":
            result, _, _ = _run(_admission(trust_score=value))
        elif field == "sweep_risk":
            result, _, _ = _run(_admission(sweep_risk=value))
        else:
            result, _, _ = _run(**{field: value})
        return result

    below = result_for(old_threshold - epsilon)
    above = result_for(old_threshold + epsilon)

    assert below["strategy_trade_allowed"] is True
    assert above["strategy_trade_allowed"] is True
    assert abs(below["continuous_weight"] - above["continuous_weight"]) < 1e-7


@pytest.mark.parametrize(("field", "value"), [("masa_confidence", float("nan"))])
def test_missing_or_nonfinite_router_input_magnitude_fails_closed(
    field: str,
    value: Any,
) -> None:
    result, _, _ = _run(**{field: value})

    assert result["strategy_trade_allowed"] is False
    assert result["continuous_weight"] == 0.0


def test_source_identity_and_pit_mismatch_fail_closed() -> None:
    admission = _admission()
    for field, value, expected_reason in (
        (
            "symbol",
            "ETHUSDT",
            "ORDINARY_ROUTER_INPUT_SOURCE_IDENTITY_MISMATCH:symbol",
        ),
        (
            "decision_time",
            "2026-07-18T00:00:59Z",
            "ORDINARY_ROUTER_INPUT_PIT_IDENTITY_MISMATCH:decision_time",
        ),
    ):
        material = _router_input(admission)
        material["market_state_envelope"][field] = value
        router = route_strategy(**deepcopy(material))
        result = interpret_ordinary_paper_router_result(
            router_result=router,
            router_input_material=material,
            ordinary_admission=admission,
            proposed_action="long",
            current_position_state="FLAT",
        )
        assert result["strategy_trade_allowed"] is False
        assert expected_reason in result["hard_reasons"]


def test_formula_has_no_legacy_static_cutoffs_or_router_config_dependency() -> None:
    source = inspect.getsource(interpret_ordinary_paper_router_result)
    legacy_cutoffs = (
        "0.55",
        "0.52",
        "0.45",
        "250",
        "125",
        "0.02",
        "12.0",
        "0.35",
        "0.65",
        "0.75",
    )

    assert "DEFAULT_ROUTER_CONFIG" not in source
    assert "threshold" not in ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA.lower()
    assert not any(value in ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA for value in legacy_cutoffs)
