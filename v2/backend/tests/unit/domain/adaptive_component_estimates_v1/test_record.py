from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import math

import pytest

from v2.backend.app.domain.adaptive_component_estimates_v1 import (
    AUTHORITY_MODE,
    AVAILABLE,
    CALIBRATED_DISTRIBUTION,
    CALIBRATED_PROBABILITY,
    COMPONENT_NAMES,
    EMPIRICAL_DISTRIBUTION,
    FACT,
    HEURISTIC_SCORE,
    LIVE_GATE,
    REGIME_CATEGORIES,
    UNAVAILABLE,
    AdaptiveComponentEstimateDomainError,
    AdaptiveComponentEstimatesV1,
    CalibrationEvidenceV1,
    CategoricalEstimateV1,
    CategoryProbabilityV1,
    ComponentEstimateGroupV1,
    DistributionEstimateV1,
    QuantileV1,
    ScalarEstimateV1,
    unavailable_component_group,
)


def _sha(character: str) -> str:
    return character * 64


def _groups() -> tuple[ComponentEstimateGroupV1, ...]:
    return tuple(
        unavailable_component_group(name, reason="producer_not_yet_calibrated")
        for name in COMPONENT_NAMES
    )


def _valid_bundle(**overrides: object) -> AdaptiveComponentEstimatesV1:
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
        "source_receipt_sha256s": (_sha("1"), _sha("2"), _sha("c")),
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
        "component_groups": _groups(),
        "authority_mode": AUTHORITY_MODE,
        "consumed_for_policy": False,
        "consumed_for_admission": False,
        "emits_trading_action": False,
        "paper_only": True,
        "live_gate": LIVE_GATE,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    values.update(overrides)
    return AdaptiveComponentEstimatesV1.create(**values)


def _calibration(component: str, metric: str, model_id: str = "model_001") -> CalibrationEvidenceV1:
    return CalibrationEvidenceV1(
        component_name=component,
        metric_name=metric,
        calibration_receipt_sha256=_sha("c"),
        fitted=True,
        probability_semantics_valid=True,
        model_id=model_id,
        model_parameter_fingerprint=_sha("d"),
        row_digest=_sha("e"),
        calibration_population_sha256=_sha("f"),
        calibration_window_start_ms=100,
        calibration_window_end_ms=800,
        sample_count=200,
        checkpoint_generation=3,
        checkpoint_id="checkpoint_003",
        checkpoint_sha256=_sha("a"),
    )


def _calibrated_probability(
    name: str,
    *,
    component: str = "loss_risk",
    value: float = 0.6,
) -> ScalarEstimateV1:
    return ScalarEstimateV1(
        name=name,
        availability=AVAILABLE,
        semantic_kind=CALIBRATED_PROBABILITY,
        value=value,
        unit="probability_0_1",
        horizon_seconds=300,
        sample_count=200,
        producer_id="calibrated_probability_producer_v1",
        source_field=name,
        source_schema="calibrated_component_output_v1",
        model_id="model_001",
        calibration_evidence=_calibration(component, name),
        source_receipt_sha256s=(_sha("1"),),
        unavailable_reason=None,
    )


def _replace_scalar(
    group: ComponentEstimateGroupV1,
    replacement: ScalarEstimateV1,
) -> ComponentEstimateGroupV1:
    values = {item.name: item for item in group.scalar_estimates}
    values[replacement.name] = replacement
    return dataclasses.replace(
        group,
        scalar_estimates=tuple(values[name] for name in sorted(values)),
    )


def test_all_required_components_and_metrics_are_explicitly_unavailable() -> None:
    bundle = _valid_bundle()
    assert tuple(group.component_name for group in bundle.component_groups) == COMPONENT_NAMES
    estimates = [
        estimate
        for group in bundle.component_groups
        for estimate in (
            *group.scalar_estimates,
            *group.distribution_estimates,
            *group.categorical_estimates,
        )
    ]
    assert estimates
    assert all(estimate.availability == UNAVAILABLE for estimate in estimates)
    assert all(estimate.unavailable_reason for estimate in estimates)
    assert all(getattr(estimate, "value", None) is None for estimate in estimates)


def test_missing_component_or_metric_fails_closed() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="canonical_order"):
        _valid_bundle(component_groups=_groups()[:-1])
    confidence = _groups()[0]
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="required_metrics"):
        dataclasses.replace(confidence, scalar_estimates=confidence.scalar_estimates[:-1])


def test_unavailable_estimate_cannot_smuggle_zero() -> None:
    estimate = _groups()[3].scalar_estimates[3]
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="null_estimate"):
        dataclasses.replace(estimate, value=0.0)


def test_calibrated_probability_requires_structured_proof() -> None:
    assert _calibrated_probability("loss_probability").value == 0.6
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="structured_calibration"):
        dataclasses.replace(
            _calibrated_probability("loss_probability"),
            calibration_evidence=None,
        )
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="unit_interval"):
        _calibrated_probability("loss_probability", value=1.1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("unit", "score", "unit_does_not_match_metric"),
        ("semantic_kind", HEURISTIC_SCORE, "semantic_kind_does_not_match_metric"),
        ("horizon_seconds", None, "horizon_required_for_metric"),
        ("sample_count", 0, "positive_sample_required_for_metric"),
    ],
)
def test_metric_semantics_are_exact(field: str, value: object, message: str) -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match=message):
        dataclasses.replace(_calibrated_probability("loss_probability"), **{field: value})


def test_heuristic_is_namespaced_and_kept_out_of_required_probability_slot() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="FACT_boolean|semantic_kind"):
        dataclasses.replace(
            _calibrated_probability("loss_probability"),
            semantic_kind=HEURISTIC_SCORE,
            unit="score",
            model_id="heuristic_v1",
            calibration_evidence=None,
        )
    score = ScalarEstimateV1(
        name="loss_risk_heuristic_legacy_score",
        availability=AVAILABLE,
        semantic_kind=HEURISTIC_SCORE,
        value=0.7,
        unit="score",
        horizon_seconds=300,
        sample_count=None,
        producer_id="legacy_projection_v1",
        source_field="loss_score",
        source_schema="legacy_risk_record_v1",
        model_id="legacy_heuristic_v1",
        calibration_evidence=None,
        source_receipt_sha256s=(_sha("1"),),
        unavailable_reason=None,
    )
    group = dataclasses.replace(_groups()[3], diagnostic_scalar_estimates=(score,))
    bundle = _valid_bundle(component_groups=(*_groups()[:3], group, *_groups()[4:]))
    assert bundle.component_groups[3].diagnostic_scalar_estimates == (score,)
    assert group.consumed_for_policy is False


def test_venue_feasibility_is_a_fact() -> None:
    venue_fact = ScalarEstimateV1(
        name="venue_feasible",
        availability=AVAILABLE,
        semantic_kind=FACT,
        value=True,
        unit="boolean",
        horizon_seconds=None,
        sample_count=None,
        producer_id="venue_rules_v1",
        source_field="venue_feasible",
        source_schema="venue_feasibility_v1",
        model_id=None,
        calibration_evidence=None,
        source_receipt_sha256s=(_sha("1"),),
        unavailable_reason=None,
    )
    execution = _replace_scalar(_groups()[1], venue_fact)
    bundle = _valid_bundle(component_groups=(_groups()[0], execution, *_groups()[2:]))
    assert bundle.component_groups[1].scalar_estimates[-1].value is True
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="FACT_boolean|semantic_kind"):
        dataclasses.replace(venue_fact, semantic_kind=HEURISTIC_SCORE, model_id="bad")


def _calibrated_distribution() -> DistributionEstimateV1:
    return DistributionEstimateV1(
        name="return_bps_distribution",
        availability=AVAILABLE,
        semantic_kind=CALIBRATED_DISTRIBUTION,
        unit="bps",
        horizon_seconds=300,
        quantiles=(QuantileV1(0.1, -5.0), QuantileV1(0.5, 0.0), QuantileV1(0.9, 8.0)),
        sample_count=200,
        producer_id="return_distribution_v1",
        source_field="return_quantiles",
        source_schema="calibrated_component_output_v1",
        model_id="model_001",
        calibration_evidence=_calibration("loss_risk", "return_bps_distribution"),
        source_receipt_sha256s=(_sha("1"),),
        unavailable_reason=None,
    )


def test_distribution_requires_exact_grid_order_and_calibration() -> None:
    valid = _calibrated_distribution()
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="quantile_grid"):
        dataclasses.replace(valid, quantiles=(QuantileV1(0.5, 0.0),))
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="nondecreasing"):
        dataclasses.replace(
            valid,
            quantiles=(QuantileV1(0.1, 5.0), QuantileV1(0.5, 0.0), QuantileV1(0.9, -5.0)),
        )
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="structured_calibration"):
        dataclasses.replace(valid, calibration_evidence=None)


def test_empirical_distribution_requires_sample_count_and_full_grid() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="quantile_grid"):
        dataclasses.replace(
            _calibrated_distribution(),
            semantic_kind=EMPIRICAL_DISTRIBUTION,
            quantiles=(QuantileV1(0.5, 2.0),),
            sample_count=0,
            calibration_evidence=None,
        )


def _regime_distribution() -> CategoricalEstimateV1:
    probabilities = tuple(
        CategoryProbabilityV1(category, 1.0 if category == "ranging" else 0.0)
        for category in REGIME_CATEGORIES
    )
    return CategoricalEstimateV1(
        name="regime_probabilities",
        availability=AVAILABLE,
        semantic_kind=CALIBRATED_DISTRIBUTION,
        probabilities=probabilities,
        horizon_seconds=300,
        sample_count=200,
        producer_id="regime_distribution_v1",
        source_field="regime_probabilities",
        source_schema="calibrated_component_output_v1",
        model_id="model_001",
        calibration_evidence=_calibration("regime", "regime_probabilities"),
        source_receipt_sha256s=(_sha("1"),),
        unavailable_reason=None,
    )


def test_regime_requires_exact_categories_and_normalization() -> None:
    valid = _regime_distribution()
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="exact_regime"):
        dataclasses.replace(valid, probabilities=valid.probabilities[:-1])
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="sum_to_one"):
        probabilities = list(valid.probabilities)
        probabilities[2] = dataclasses.replace(probabilities[2], probability=0.2)
        dataclasses.replace(valid, probabilities=tuple(probabilities))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_ingested_at_ms", 900),
        ("feature_cutoff_ms", 1_300),
        ("source_available_at_ms", 1_050),
        ("producer_generated_at_ms", 1_100),
        ("record_available_at_ms", 1_300),
        ("decision_time_ms", 1_300),
    ],
)
def test_point_in_time_inversions_fail_closed(field: str, value: int) -> None:
    updates: dict[str, object] = {field: value}
    if field == "decision_time_ms":
        updates["latest_unclosed_exclusion_decision_time_ms"] = value
    with pytest.raises(
        AdaptiveComponentEstimateDomainError,
        match="point_in_time_order_invalid|effective_availability",
    ):
        _valid_bundle(**updates)


def test_finality_method_and_decision_time_are_bound() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="non_empty"):
        _valid_bundle(latest_unclosed_exclusion_method="")
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="equal_decision_time"):
        _valid_bundle(latest_unclosed_exclusion_decision_time_ms=1_599)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consumed_for_policy", True),
        ("consumed_for_admission", True),
        ("emits_trading_action", True),
        ("paper_only", False),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("exchange_action_taken", True),
    ],
)
def test_shadow_and_live_authority_is_fail_closed(field: str, value: bool) -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError):
        _valid_bundle(**{field: value})


def test_available_estimate_receipts_must_be_bundle_subset() -> None:
    estimate = dataclasses.replace(
        _calibrated_probability("loss_probability"),
        source_receipt_sha256s=(_sha("4"),),
    )
    group = _replace_scalar(_groups()[3], estimate)
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="bundle_receipt_subset"):
        _valid_bundle(component_groups=(*_groups()[:3], group, *_groups()[4:]))


def test_calibration_must_match_component_checkpoint_and_sample() -> None:
    estimate = _calibrated_probability("loss_probability")
    wrong = dataclasses.replace(
        estimate,
        calibration_evidence=dataclasses.replace(
            estimate.calibration_evidence,
            component_name="confidence",
        ),
    )
    group = _replace_scalar(_groups()[3], wrong)
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="component_mismatch"):
        _valid_bundle(component_groups=(*_groups()[:3], group, *_groups()[4:]))
    wrong = dataclasses.replace(
        estimate,
        calibration_evidence=dataclasses.replace(
            estimate.calibration_evidence,
            checkpoint_generation=2,
        ),
    )
    group = _replace_scalar(_groups()[3], wrong)
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="checkpoint_mismatch"):
        _valid_bundle(component_groups=(*_groups()[:3], group, *_groups()[4:]))


def test_candidate_action_and_transport_clocks_are_identity_bound() -> None:
    first = _valid_bundle()
    changed_candidate = _valid_bundle(candidate_id="candidate_002")
    delayed = _valid_bundle(producer_generated_at_ms=1_450, record_available_at_ms=1_450)
    assert first.bundle_id != changed_candidate.bundle_id
    assert first.semantic_fingerprint_sha256 != changed_candidate.semantic_fingerprint_sha256
    assert first.bundle_id != delayed.bundle_id
    assert first.semantic_fingerprint_sha256 != delayed.semantic_fingerprint_sha256


def test_strict_round_trip_and_tamper_detection() -> None:
    bundle = _valid_bundle()
    assert AdaptiveComponentEstimatesV1.from_payload(bundle.to_payload()) == bundle
    assert AdaptiveComponentEstimatesV1.from_json(bundle.canonical_json()) == bundle
    extra = bundle.to_payload()
    extra["selected_action"] = "directional_trade"
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="exact_keys_required"):
        AdaptiveComponentEstimatesV1.from_payload(extra)
    tampered = bundle.to_payload()
    tampered["semantic_fingerprint_sha256"] = "0" * 64
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="semantic_payload"):
        AdaptiveComponentEstimatesV1.from_payload(tampered)


def test_nested_calibration_round_trip() -> None:
    group = _replace_scalar(_groups()[3], _calibrated_probability("loss_probability"))
    bundle = _valid_bundle(component_groups=(*_groups()[:3], group, *_groups()[4:]))
    restored = AdaptiveComponentEstimatesV1.from_json(bundle.canonical_json())
    evidence = restored.component_groups[3].scalar_estimates[3].calibration_evidence
    assert evidence is not None
    assert evidence.fitted is True


def test_nonfinite_and_duplicate_json_fail_closed() -> None:
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="finite_float"):
        dataclasses.replace(_calibrated_probability("loss_probability"), value=math.nan)
    with pytest.raises(AdaptiveComponentEstimateDomainError, match="duplicate_json_key"):
        AdaptiveComponentEstimatesV1.from_json('{"bundle_id":"a","bundle_id":"b"}')


def test_records_are_frozen() -> None:
    bundle = _valid_bundle()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.authority_mode = "AUTHORITATIVE"  # type: ignore[misc]


def test_contract_module_has_no_io_or_external_runtime_dependency() -> None:
    record_module = importlib.import_module(
        "v2.backend.app.domain.adaptive_component_estimates_v1.record"
    )
    syntax_tree = ast.parse(inspect.getsource(record_module))
    imported_roots: set[str] = set()
    forbidden_calls = {"connect", "getenv", "open", "publish", "request", "send", "system"}
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls
    assert imported_roots == {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "re",
        "typing",
    }
