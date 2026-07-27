from __future__ import annotations

import copy
import dataclasses

import pytest

from v2.backend.app.domain.adaptive_component_estimates_v1 import (
    FACT,
    HEURISTIC_SCORE,
    UNAVAILABLE,
    AdaptiveComponentEstimateDomainError,
)
from v2.backend.app.services.adaptive_system.component_estimate_shadow_projection import (
    LegacyCandidateProjectionContextV1,
    project_legacy_candidate_diagnostics,
)


def _sha(character: str) -> str:
    return character * 64


def _context(**overrides: object) -> LegacyCandidateProjectionContextV1:
    values: dict[str, object] = {
        "candidate_id": "candidate_001",
        "prediction_id": "prediction_001",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "LONG",
        "venue": "binance_paper",
        "order_type": "MARKET",
        "action_under_evaluation_sha256": _sha("9"),
        "state_id": "state_001",
        "state_sha256": _sha("8"),
        "feature_snapshot_id": "feature_001",
        "feature_abi_sha256": _sha("7"),
        "feature_builder_sha256": _sha("6"),
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint_003",
        "checkpoint_sha256": _sha("a"),
        "policy_id": "adaptive_policy_shadow_001",
        "source_receipt_sha256s": (_sha("1"),),
        "state_event_time_ms": 1_000,
        "state_ingested_at_ms": 1_100,
        "feature_cutoff_ms": 1_150,
        "source_available_at_ms": 1_200,
        "producer_generated_at_ms": 1_400,
        "record_available_at_ms": 1_400,
        "decision_time_ms": 1_600,
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "close_time_strictly_before_cutoff",
        "latest_unclosed_exclusion_decision_time_ms": 1_600,
        "latest_closed_kline_close_time_ms": 900,
        "source_producer_id": "paper_candidate_evaluator_v1",
        "source_schema": "paper_candidate_matrix_v1",
    }
    values.update(overrides)
    return LegacyCandidateProjectionContextV1(**values)  # type: ignore[arg-type]


def _group(bundle: object, component_name: str) -> object:
    return next(
        group
        for group in bundle.component_groups  # type: ignore[attr-defined]
        if group.component_name == component_name
    )


def test_legacy_probability_named_values_remain_diagnostic_not_calibrated() -> None:
    bundle = project_legacy_candidate_diagnostics(
        {
            "pre_trade_loss_probability": 0.65,
            "exit_feasibility_score": 0.72,
            "microstructure_action": "ALLOW",
        },
        _context(),
    )
    loss = _group(bundle, "loss_risk")
    required = next(item for item in loss.scalar_estimates if item.name == "loss_probability")
    diagnostic = loss.diagnostic_scalar_estimates[0]
    assert required.availability == UNAVAILABLE
    assert diagnostic.semantic_kind == HEURISTIC_SCORE
    assert diagnostic.name == "loss_risk_heuristic_pre_trade_loss_probability"
    assert diagnostic.value == 0.65
    assert diagnostic.calibration_evidence is None
    assert bundle.consumed_for_policy is False
    assert bundle.emits_trading_action is False


def test_discrete_legacy_action_is_diagnostic_only() -> None:
    bundle = project_legacy_candidate_diagnostics(
        {"microstructure_action": "BLOCK"},
        _context(),
    )
    microstructure = _group(bundle, "microstructure")
    assert microstructure.source_diagnostic_action == "BLOCK"
    assert microstructure.consumed_for_policy is False
    assert microstructure.consumed_for_admission is False
    assert bundle.routes_to_live is False


def test_explicit_venue_boolean_projects_as_fact() -> None:
    bundle = project_legacy_candidate_diagnostics(
        {"venue_feasible": False},
        _context(),
    )
    execution = _group(bundle, "execution_quality")
    venue = next(item for item in execution.scalar_estimates if item.name == "venue_feasible")
    assert venue.semantic_kind == FACT
    assert venue.value is False
    assert venue.model_id is None


def test_missing_and_nonfinite_values_are_not_zero_filled() -> None:
    bundle = project_legacy_candidate_diagnostics(
        {
            "pre_trade_loss_probability": float("nan"),
            "exit_feasibility_score": None,
            "venue_feasible": 0,
        },
        _context(),
    )
    assert all(not group.diagnostic_scalar_estimates for group in bundle.component_groups)
    execution = _group(bundle, "execution_quality")
    venue = next(item for item in execution.scalar_estimates if item.name == "venue_feasible")
    assert venue.availability == UNAVAILABLE


def test_projection_is_deterministic_and_does_not_mutate_source() -> None:
    source = {"confidence": 0.7, "microstructure_action": "REDUCE_SIZE"}
    original = copy.deepcopy(source)
    first = project_legacy_candidate_diagnostics(source, _context())
    second = project_legacy_candidate_diagnostics(source, _context())
    assert source == original
    assert first == second
    assert first.bundle_id == second.bundle_id


def test_context_point_in_time_and_receipt_failures_propagate_fail_closed() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="point_in_time"):
        project_legacy_candidate_diagnostics(
            {"confidence": 0.7},
            _context(feature_cutoff_ms=1_700),
        )
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="unique_and_sorted"):
        project_legacy_candidate_diagnostics(
            {"confidence": 0.7},
            _context(source_receipt_sha256s=(_sha("2"), _sha("1"))),
        )


def test_context_change_changes_identity() -> None:
    source = {"confidence": 0.7}
    first = project_legacy_candidate_diagnostics(source, _context())
    second = project_legacy_candidate_diagnostics(
        source,
        dataclasses.replace(_context(), action_under_evaluation_sha256=_sha("5")),
    )
    assert first.bundle_id != second.bundle_id
