from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION,
    COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION,
    COUNTERFACTUAL_ARM_SCHEMA_VERSION,
    COUNTERFACTUAL_ARMS,
    COUNTERFACTUAL_PLAN_SCHEMA_VERSION,
    COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION,
    COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION,
    DECISION_DISPOSITIONS,
    DECISION_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    HORIZON_LABEL_SCHEMA_VERSION,
    LIVE_GATE_BLOCKED_HUMAN_ONLY,
    MATURED_LABELS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ActualPaperExecutionOutcomeV2,
    CandidateDecisionEvidenceV2,
    CandidateDecisionOutcomeV2,
    CandidateDecisionSnapshotV2,
    CandidateHorizonLabelV2,
    CandidateOutcomeContractError,
    CounterfactualArmOutcomeV2,
    CounterfactualArmPlanV2,
    CounterfactualEvaluationPlanV2,
    CounterfactualScenarioPlanV2,
    CounterfactualScenarioV2,
    MaturedLabelsV2,
    candidate_decision_outcome_from_dict,
    canonical_payload_json,
    canonical_payload_sha256,
    counterfactual_universe_sha256,
    horizon_contract_sha256,
    validate_archive_successor,
)

DECISION_TIME_MS = 1_000_000
HORIZONS = (300, 900)


class StrSubclass(str):
    pass


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _evidence(kind: str, **overrides: object) -> CandidateDecisionEvidenceV2:
    payload_json = canonical_payload_json(
        {
            "exchange_action_taken": False,
            "execution_authority": False,
            "execution_domain": "PAPER",
            "kind": kind,
            "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
            "live_eligible": False,
            "live_submission_ready": False,
            "paper_only": True,
            "places_real_order": False,
            "policy_authority_scope": "trading_action_only",
            "requires_hard_validator": True,
            "routes_to_live": False,
            "value": 1.0,
        }
    )
    values: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": kind,
        "record_id": f"record-{kind}",
        "source_record_sha256": _sha(f"source-{kind}"),
        "source_event_time_ms": DECISION_TIME_MS - 110,
        "producer_generated_at_ms": DECISION_TIME_MS - 80,
        "record_generated_at_ms": DECISION_TIME_MS - 70,
        "record_available_at_ms": DECISION_TIME_MS - 60,
        "feature_cutoff_ms": DECISION_TIME_MS - 100,
        "latest_closed_kline_close_time_ms": DECISION_TIME_MS - 200,
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "close_time_lte_feature_cutoff",
        "latest_unclosed_exclusion_decision_time_ms": DECISION_TIME_MS - 100,
        "payload_json": payload_json,
        "payload_sha256": canonical_payload_sha256(payload_json),
        "source_receipt_sha256s": (_sha(f"receipt-{kind}"),),
        "complete": True,
    }
    values.update(overrides)
    return CandidateDecisionEvidenceV2(**values)  # type: ignore[arg-type]


def _scenario_plan(arm: str) -> CounterfactualScenarioPlanV2:
    return CounterfactualScenarioPlanV2(
        schema_version=COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION,
        scenario_id=f"{arm}-001",
        action_sha256=_sha(f"action-{arm}"),
    )


def _counterfactual_plan(
    *,
    candidate_id: str,
    supported_horizon_seconds: tuple[int, ...],
    horizon_contract_digest: str,
) -> CounterfactualEvaluationPlanV2:
    return CounterfactualEvaluationPlanV2(
        schema_version=COUNTERFACTUAL_PLAN_SCHEMA_VERSION,
        plan_id=f"plan-{candidate_id}",
        candidate_id=candidate_id,
        supported_horizon_seconds=supported_horizon_seconds,
        horizon_contract_sha256=horizon_contract_digest,
        arms=tuple(
            CounterfactualArmPlanV2(
                schema_version=COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION,
                arm_name=arm,
                scenarios=(_scenario_plan(arm),),
            )
            for arm in COUNTERFACTUAL_ARMS
        ),
        producer_generated_at_ms=DECISION_TIME_MS - 2,
        record_available_at_ms=DECISION_TIME_MS - 1,
        source_receipt_sha256s=(_sha("counterfactual-plan"),),
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


def _decision(**overrides: object) -> CandidateDecisionSnapshotV2:
    values: dict[str, object] = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "candidate_id": "candidate-1",
        "state_id": "state-1",
        "state_sha256": _sha("state"),
        "prediction_id": "prediction-1",
        "prediction_sha256": _sha("prediction"),
        "policy_id": "policy-1",
        "policy_sha256": _sha("policy"),
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_sha256": _sha("checkpoint"),
        "symbol": "OPUSDT",
        "timeframe": "1h",
        "decision_disposition": "REJECTED",
        "disposition_reason": "EXIT_FEASIBILITY_BELOW_POLICY_INPUT",
        "decision_rationale": "Complete governed policy evaluation selected remain-flat.",
        "supported_horizon_seconds": HORIZONS,
        "horizon_contract_id": "checkpoint-policy-horizons-v2",
        "feature_cutoff_ms": DECISION_TIME_MS - 100,
        "latest_closed_kline_close_time_ms": DECISION_TIME_MS - 200,
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "close_time_lte_feature_cutoff",
        "latest_unclosed_exclusion_decision_time_ms": DECISION_TIME_MS - 100,
        "decision_time_ms": DECISION_TIME_MS,
        "record_generated_at_ms": DECISION_TIME_MS + 1,
        "record_available_at_ms": DECISION_TIME_MS + 2,
        "model_distributions": _evidence("model_distributions"),
        "proposed_action": _evidence("proposed_action"),
        "selected_action": _evidence("selected_action"),
        "component_estimates": _evidence("component_estimates"),
        "portfolio_state": _evidence("portfolio_state"),
        "execution_state": _evidence("execution_state"),
        "paper_only": True,
        "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    values.update(overrides)
    if "horizon_contract_sha256" not in values:
        values["horizon_contract_sha256"] = horizon_contract_sha256(
            policy_id=values["policy_id"],  # type: ignore[arg-type]
            policy_sha256=values["policy_sha256"],  # type: ignore[arg-type]
            checkpoint_id=values["checkpoint_id"],  # type: ignore[arg-type]
            checkpoint_sha256=values["checkpoint_sha256"],  # type: ignore[arg-type]
            supported_horizon_seconds=values["supported_horizon_seconds"],  # type: ignore[arg-type]
        )
    values.setdefault("horizon_contract_receipt_sha256", _sha("horizon-contract-receipt"))
    values.setdefault(
        "counterfactual_evaluation_plan",
        _counterfactual_plan(
            candidate_id=values["candidate_id"],  # type: ignore[arg-type]
            supported_horizon_seconds=values["supported_horizon_seconds"],  # type: ignore[arg-type]
            horizon_contract_digest=values["horizon_contract_sha256"],  # type: ignore[arg-type]
        ),
    )
    return CandidateDecisionSnapshotV2(**values)  # type: ignore[arg-type]


def _horizon(horizon_seconds: int, **overrides: object) -> CandidateHorizonLabelV2:
    horizon_end_ms = DECISION_TIME_MS + horizon_seconds * 1_000
    values: dict[str, object] = {
        "schema_version": HORIZON_LABEL_SCHEMA_VERSION,
        "horizon_seconds": horizon_seconds,
        "horizon_end_ms": horizon_end_ms,
        "future_return_bps": 8.0 if horizon_seconds == 300 else -3.0,
        "source_event_time_ms": horizon_end_ms + 1,
        "producer_generated_at_ms": horizon_end_ms + 2,
        "record_available_at_ms": horizon_end_ms + 3,
        "source_receipt_sha256": _sha(f"horizon-{horizon_seconds}"),
        "finality_proven": True,
    }
    values.update(overrides)
    return CandidateHorizonLabelV2(**values)  # type: ignore[arg-type]


def _scenario(arm: str, **overrides: object) -> CounterfactualScenarioV2:
    values: dict[str, object] = {
        "schema_version": COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION,
        "scenario_id": f"{arm}-001",
        "action_sha256": _sha(f"action-{arm}"),
        "gross_pnl_bps": 10.0,
        "fees_bps": 2.0,
        "spread_bps": 1.0,
        "slippage_bps": 1.0,
        "funding_bps": 0.5,
        "market_impact_bps": 0.5,
        "after_cost_pnl_bps": 5.0,
        "source_event_time_ms": 1_900_001,
        "producer_generated_at_ms": 1_900_002,
        "record_available_at_ms": 1_900_003,
        "source_receipt_sha256s": (_sha(f"scenario-receipt-{arm}"),),
        "finality_proven": True,
        "counts_as_paper_profit": False,
        "actual_accounting_effect": False,
    }
    values.update(overrides)
    return CounterfactualScenarioV2(**values)  # type: ignore[arg-type]


def _arm(arm: str, **overrides: object) -> CounterfactualArmOutcomeV2:
    scenarios = overrides.pop("scenarios", (_scenario(arm),))
    eligible = overrides.pop("eligible_scenario_count", len(scenarios))
    excluded = overrides.pop("excluded_scenario_count", 0)
    exclusion_receipt = overrides.pop("exclusion_receipt_sha256", None)
    universe = counterfactual_universe_sha256(
        arm_name=arm,
        scenarios=scenarios,
        eligible_scenario_count=eligible,
        excluded_scenario_count=excluded,
        exclusion_receipt_sha256=exclusion_receipt,
    )
    values: dict[str, object] = {
        "schema_version": COUNTERFACTUAL_ARM_SCHEMA_VERSION,
        "arm_name": arm,
        "scenario_universe_sha256": universe,
        "scenarios": scenarios,
        "eligible_scenario_count": eligible,
        "excluded_scenario_count": excluded,
        "exclusion_receipt_sha256": exclusion_receipt,
        "complete": True,
    }
    values.update(overrides)
    return CounterfactualArmOutcomeV2(**values)  # type: ignore[arg-type]


def _actual(
    decision: CandidateDecisionSnapshotV2,
    **overrides: object,
) -> ActualPaperExecutionOutcomeV2:
    values: dict[str, object] = {
        "schema_version": ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION,
        "candidate_id": decision.candidate_id,
        "selected_action_sha256": decision.selected_action.content_sha256(),
        "signal_id": "signal-1",
        "intent_id": "intent-1",
        "fill_id": "fill-1",
        "position_id": "position-1",
        "closed_trade_id": "closed-trade-1",
        "fill_receipt_sha256": _sha("fill"),
        "close_receipt_sha256": _sha("close"),
        "accounting_receipt_sha256": _sha("accounting"),
        "action_decision_time_ms": 1_000_005,
        "fill_execution_time_ms": 1_000_010,
        "fill_record_available_at_ms": 1_000_011,
        "close_execution_time_ms": 1_900_000,
        "close_record_available_at_ms": 1_900_001,
        "accounting_record_available_at_ms": 1_900_002,
        "executed_quantity": 10.0,
        "execution_price": 2.0,
        "gross_notional_usd": 20.0,
        "effective_leverage": 2.0,
        "allocated_margin_usd": 10.0,
        "realized_pnl_usd": -0.2,
        "realized_pnl_bps": -100.0,
        "open_quantity_after_close": 0.0,
        "used_margin_after_close_usd": 0.0,
        "reserved_margin_after_close_usd": 0.0,
        "reduce_only_close": True,
        "fully_closed": True,
        "paper_only": True,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    values.update(overrides)
    return ActualPaperExecutionOutcomeV2(**values)  # type: ignore[arg-type]


def _labels(
    decision: CandidateDecisionSnapshotV2,
    *,
    actual: ActualPaperExecutionOutcomeV2 | None = None,
    **overrides: object,
) -> MaturedLabelsV2:
    eventual_by_decision = {
        "SELECTED_TRADE": "TRADED",
        "REJECTED": "REJECTED",
        "INFEASIBLE": "INFEASIBLE",
        "SELECTED_RISK_REDUCED": "RISK_REDUCED",
        "SELECTED_FLAT": "FLAT",
        "SELECTED_HEDGED": "HEDGED",
    }
    values: dict[str, object] = {
        "schema_version": MATURED_LABELS_SCHEMA_VERSION,
        "candidate_id": decision.candidate_id,
        "decision_snapshot_sha256": decision.content_sha256(),
        "counterfactual_plan_sha256": decision.counterfactual_evaluation_plan.content_sha256(),
        "eventual_disposition": eventual_by_decision[decision.decision_disposition],
        "supported_horizon_seconds": decision.supported_horizon_seconds,
        "horizon_labels": tuple(
            _horizon(horizon) for horizon in decision.supported_horizon_seconds
        ),
        "max_favorable_excursion_bps": 18.0,
        "max_adverse_excursion_bps": -11.0,
        "realized_volatility_bps": 14.0,
        "estimated_executable_entry": 2.0,
        "estimated_executable_exit": 1.98,
        "fees_bps": 2.0,
        "spread_bps": 1.0,
        "slippage_bps": 1.0,
        "funding_bps": 0.5,
        "market_impact_bps": 0.5,
        "stop_result": "NOT_HIT",
        "time_exit_result": "HORIZON_FINAL",
        "profit_exit_result": "NOT_HIT",
        "counterfactual_outcomes": tuple(_arm(arm) for arm in COUNTERFACTUAL_ARMS),
        "actual_paper_outcome": actual,
        "labeler_id": "point-in-time-labeler-v2",
        "labeler_version_sha256": _sha("labeler"),
        "label_source_receipt_sha256s": (_sha("label-source"),),
        "summary_source_event_time_ms": 1_900_001,
        "summary_producer_generated_at_ms": 1_900_002,
        "summary_record_available_at_ms": 1_900_003,
        "summary_receipt_sha256": _sha("summary"),
        "summary_finality_proven": True,
        "label_generated_at_ms": 1_900_004,
        "record_available_at_ms": 1_900_005,
        "matured": True,
        "complete": True,
        "counts_as_paper_profit": actual is not None,
    }
    values.update(overrides)
    return MaturedLabelsV2(**values)  # type: ignore[arg-type]


def _archive(
    decision: CandidateDecisionSnapshotV2 | None = None,
    labels: MaturedLabelsV2 | None = None,
    **overrides: object,
) -> CandidateDecisionOutcomeV2:
    decision = decision or _decision()
    is_matured = labels is not None
    values: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "archive_record_id": "candidate-1-revision-2" if is_matured else "candidate-1-revision-1",
        "archive_sequence": 2 if is_matured else 1,
        "decision": decision,
        "matured_labels": labels,
        "previous_archive_record_sha256": _sha("revision-1") if is_matured else None,
        "record_generated_at_ms": 1_900_006 if is_matured else DECISION_TIME_MS + 3,
        "record_available_at_ms": 1_900_007 if is_matured else DECISION_TIME_MS + 4,
        "paper_only": True,
        "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    values.update(overrides)
    return CandidateDecisionOutcomeV2(**values)  # type: ignore[arg-type]


def test_decision_only_revision_records_rejected_candidate_completely() -> None:
    record = _archive()
    assert record.validate() == []
    assert record.decision.decision_disposition == "REJECTED"
    assert record.matured_labels is None


def test_every_required_disposition_is_recordable_at_decision_time() -> None:
    for disposition in DECISION_DISPOSITIONS:
        assert (
            _archive(_decision(decision_disposition=disposition)).decision.decision_disposition
            == disposition
        )


def test_record_is_deeply_immutable_by_construction() -> None:
    record = _archive()
    with pytest.raises(FrozenInstanceError):
        record.decision.candidate_id = "different"  # type: ignore[misc]
    assert type(record.decision.model_distributions.payload_json) is str
    assert type(record.decision.model_distributions.source_receipt_sha256s) is tuple


def test_content_hash_is_deterministic_and_sensitive() -> None:
    assert _archive().content_sha256() == _archive().content_sha256()
    assert (
        _archive().content_sha256()
        != _archive(_decision(candidate_id="candidate-2")).content_sha256()
    )


def test_strict_decoder_round_trips_decision_and_matured_records() -> None:
    first = _archive()
    assert candidate_decision_outcome_from_dict(first.to_dict()) == first
    second = _archive(
        first.decision,
        _labels(first.decision),
        previous_archive_record_sha256=first.content_sha256(),
    )
    decoded = candidate_decision_outcome_from_dict(second.to_dict())
    assert decoded == second
    assert type(decoded.decision.supported_horizon_seconds) is tuple
    assert type(decoded.matured_labels.horizon_labels) is tuple  # type: ignore[union-attr]


def test_strict_decoder_rejects_missing_unknown_and_malformed_nested_fields() -> None:
    missing = _archive().to_dict()
    del missing["paper_only"]
    with pytest.raises(CandidateOutcomeContractError, match="exact_keys_required:missing=paper_only"):
        candidate_decision_outcome_from_dict(missing)

    unknown = _archive().to_dict()
    unknown["untrusted_extension"] = True
    with pytest.raises(
        CandidateOutcomeContractError,
        match="unexpected=untrusted_extension",
    ):
        candidate_decision_outcome_from_dict(unknown)

    malformed = _archive().to_dict()
    malformed["decision"]["model_distributions"]["source_receipt_sha256s"] = "not-an-array"
    with pytest.raises(CandidateOutcomeContractError, match="must_be_array"):
        candidate_decision_outcome_from_dict(malformed)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"checkpoint_generation": True}, "checkpoint_generation:must_be_positive_int"),
        ({"decision_rationale": "  "}, "decision_rationale:must_be_non_blank"),
        ({"latest_unclosed_kline_excluded": False}, "latest_unclosed_kline_excluded:must_be_true"),
        (
            {"feature_cutoff_ms": DECISION_TIME_MS + 1},
            "feature_cutoff_ms:feature_cutoff_after_decision",
        ),
        (
            {"record_generated_at_ms": DECISION_TIME_MS - 1},
            "record_generated_at_ms:record_generated_before_decision",
        ),
        ({"paper_only": False}, "paper_only:must_be_true"),
        ({"routes_to_live": True}, "routes_to_live:must_be_false"),
    ],
)
def test_decision_rejects_malformed_identity_time_and_authority(
    overrides: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(CandidateOutcomeContractError, match=match):
        _decision(**overrides)


def test_evidence_must_be_available_before_decision() -> None:
    future = _evidence("model_distributions", record_available_at_ms=DECISION_TIME_MS + 1)
    with pytest.raises(CandidateOutcomeContractError, match="evidence_available_after_decision"):
        _decision(model_distributions=future)


def test_decision_requires_exact_evidence_kind_in_each_slot() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="must_have_kind_model_distributions"):
        _decision(model_distributions=_evidence("execution_state"))


def test_evidence_rejects_noncanonical_duplicate_and_nonfinite_json() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="must_be_canonical_json"):
        _evidence("model_distributions", payload_json='{ "value" : 1 }', payload_sha256=_sha("x"))
    duplicate = '{"value":1,"value":2}'
    with pytest.raises(CandidateOutcomeContractError, match="duplicate_json_key"):
        _evidence(
            "model_distributions",
            payload_json=duplicate,
            payload_sha256=canonical_payload_sha256(duplicate),
        )
    nonfinite = '{"value":NaN}'
    with pytest.raises(CandidateOutcomeContractError, match="nonfinite_json_number"):
        _evidence(
            "model_distributions",
            payload_json=nonfinite,
            payload_sha256=canonical_payload_sha256(nonfinite),
        )


def test_canonical_payload_rejects_non_string_keys_without_collision() -> None:
    with pytest.raises(
        CandidateOutcomeContractError,
        match="json_object_keys_must_be_exact_strings",
    ):
        canonical_payload_json({1: "dropped", "1": "retained"})  # type: ignore[dict-item]
    with pytest.raises(
        CandidateOutcomeContractError,
        match="json_object_keys_must_be_exact_strings",
    ):
        canonical_payload_json({"nested": [{1: "not-json"}]})  # type: ignore[dict-item]


def test_schema_enums_and_live_gate_reject_string_subclasses() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="schema_version"):
        _decision(schema_version=StrSubclass(DECISION_SCHEMA_VERSION))
    with pytest.raises(CandidateOutcomeContractError, match="evidence_kind"):
        _evidence("model_distributions", evidence_kind=StrSubclass("model_distributions"))
    with pytest.raises(CandidateOutcomeContractError, match="arm_name"):
        _arm("unhedged", arm_name=StrSubclass("unhedged"))
    with pytest.raises(CandidateOutcomeContractError, match="live_gate"):
        _archive(live_gate=StrSubclass(LIVE_GATE_BLOCKED_HUMAN_ONLY))


def test_action_and_execution_payloads_cannot_contradict_no_live_authority() -> None:
    unsafe = canonical_payload_json(
        {
            "exchange_action_taken": False,
            "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
            "nested": {"routes_to_live": True},
            "paper_only": True,
            "places_real_order": False,
            "routes_to_live": False,
        }
    )
    with pytest.raises(CandidateOutcomeContractError, match="payload_authority_contradiction"):
        _evidence(
            "selected_action",
            payload_json=unsafe,
            payload_sha256=canonical_payload_sha256(unsafe),
        )
    canonical_action_live_claim = canonical_payload_json(
        {
            "exchange_action_taken": False,
            "execution_authority": True,
            "execution_domain": "LIVE",
            "live_eligible": True,
            "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
            "live_submission_ready": True,
            "paper_only": True,
            "places_real_order": False,
            "policy_authority_scope": "trading_action_only",
            "requires_hard_validator": True,
            "routes_to_live": False,
        }
    )
    with pytest.raises(CandidateOutcomeContractError, match="payload_authority_contradiction"):
        _evidence(
            "selected_action",
            payload_json=canonical_action_live_claim,
            payload_sha256=canonical_payload_sha256(canonical_action_live_claim),
        )
    incomplete = canonical_payload_json({"selected_action": "remain_flat"})
    with pytest.raises(
        CandidateOutcomeContractError,
        match="required_safe_authority_field_missing_or_invalid",
    ):
        _evidence(
            "selected_action",
            payload_json=incomplete,
            payload_sha256=canonical_payload_sha256(incomplete),
        )


def test_decision_evidence_clocks_and_finality_contract_are_exact() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="source_event_after_producer"):
        _evidence("model_distributions", source_event_time_ms=DECISION_TIME_MS - 1)
    with pytest.raises(CandidateOutcomeContractError, match="record_generated_after_available"):
        _evidence(
            "model_distributions",
            record_generated_at_ms=DECISION_TIME_MS - 1,
            record_available_at_ms=DECISION_TIME_MS - 2,
        )
    with pytest.raises(
        CandidateOutcomeContractError,
        match="exclusion_decision_after_producer_generated",
    ):
        _evidence(
            "model_distributions",
            latest_unclosed_exclusion_decision_time_ms=DECISION_TIME_MS - 50,
        )
    mismatch = _evidence(
        "model_distributions",
        latest_unclosed_exclusion_method="different_finality_method",
    )
    with pytest.raises(
        CandidateOutcomeContractError,
        match="latest_unclosed_exclusion_method_mismatch",
    ):
        _decision(model_distributions=mismatch)


def test_horizon_contract_is_bound_to_exact_policy_checkpoint_and_universe() -> None:
    with pytest.raises(
        CandidateOutcomeContractError,
        match="must_bind_policy_checkpoint_and_horizons",
    ):
        _decision(horizon_contract_sha256=_sha("self-declared-smaller-universe"))


def test_evidence_payload_hash_and_completeness_are_mandatory() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="must_match_payload"):
        _evidence("model_distributions", payload_sha256=_sha("wrong"))
    with pytest.raises(CandidateOutcomeContractError, match="complete:must_be_true"):
        _evidence("model_distributions", complete=False)


def test_complete_rejected_candidate_matures_without_paper_profit() -> None:
    decision = _decision()
    labels = _labels(decision)
    record = _archive(decision, labels)
    assert record.matured_labels is not None
    assert record.matured_labels.counts_as_paper_profit is False
    assert record.matured_labels.actual_paper_outcome is None
    assert record.matured_labels.supported_horizon_seconds == HORIZONS


def test_matured_labels_require_every_supported_horizon_exactly() -> None:
    decision = _decision()
    with pytest.raises(
        CandidateOutcomeContractError, match="must_cover_every_supported_horizon_exactly"
    ):
        _labels(decision, horizon_labels=(_horizon(300),))


def test_horizon_end_must_match_decision_when_attached() -> None:
    decision = _decision()
    labels = _labels(
        decision,
        horizon_labels=(
            _horizon(300, horizon_end_ms=1_300_001),
            _horizon(900),
        ),
    )
    # The label record proves finality internally; attachment proves the end is
    # the declared decision horizon, preventing a relabeled shorter window.
    with pytest.raises(CandidateOutcomeContractError, match="horizon_end_mismatch"):
        _archive(decision, labels)


def test_horizon_label_rejects_unfinalized_or_early_source() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="source_event_before_horizon_end"):
        _horizon(300, source_event_time_ms=1_299_999)
    with pytest.raises(CandidateOutcomeContractError, match="finality_proven:must_be_true"):
        _horizon(300, finality_proven=False)


def test_labels_cannot_exist_before_all_sources_are_available() -> None:
    decision = _decision()
    with pytest.raises(
        CandidateOutcomeContractError, match="label_generated_before_source_available"
    ):
        _labels(decision, label_generated_at_ms=1_900_001)


def test_counterfactual_arms_are_complete_and_ordered() -> None:
    decision = _decision()
    incomplete = tuple(_arm(arm) for arm in COUNTERFACTUAL_ARMS[:-1])
    with pytest.raises(
        CandidateOutcomeContractError, match="must_cover_every_counterfactual_arm_exactly"
    ):
        _labels(decision, counterfactual_outcomes=incomplete)


def test_counterfactual_scenario_can_never_touch_paper_accounting() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="counts_as_paper_profit:must_be_false"):
        _scenario("hedged", counts_as_paper_profit=True)
    with pytest.raises(
        CandidateOutcomeContractError, match="actual_accounting_effect:must_be_false"
    ):
        _scenario("hedged", actual_accounting_effect=True)
    with pytest.raises(CandidateOutcomeContractError, match="finality_proven:must_be_true"):
        _scenario("hedged", finality_proven=False)


def test_counterfactual_after_cost_math_is_recomputed() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="must_equal_gross_minus_costs"):
        _scenario("alternative_side", after_cost_pnl_bps=100.0)


def test_counterfactual_labels_wait_for_all_declared_horizons() -> None:
    decision = _decision()
    early_arm = _arm(
        "unhedged",
        scenarios=(
            _scenario(
                "unhedged",
                source_event_time_ms=1_899_999,
                producer_generated_at_ms=1_900_000,
                record_available_at_ms=1_900_001,
            ),
        ),
    )
    arms = (early_arm, *(_arm(arm) for arm in COUNTERFACTUAL_ARMS[1:]))
    with pytest.raises(
        CandidateOutcomeContractError,
        match="counterfactual_source_before_all_horizons_matured",
    ):
        _labels(decision, counterfactual_outcomes=arms)


def test_counterfactual_universe_hash_and_drop_accounting_are_enforced() -> None:
    with pytest.raises(CandidateOutcomeContractError, match="must_match_complete_universe"):
        _arm("alternative_size", scenario_universe_sha256=_sha("forged"))
    with pytest.raises(CandidateOutcomeContractError, match="exclusion_receipt_sha256"):
        _arm("alternative_size", excluded_scenario_count=1)
    arm = _arm(
        "alternative_size",
        excluded_scenario_count=1,
        exclusion_receipt_sha256=_sha("excluded"),
    )
    assert arm.excluded_scenario_count == 1


def test_matured_counterfactuals_must_equal_decision_time_plan_without_drops() -> None:
    decision = _decision()
    changed_scenario = _scenario("alternative_side", action_sha256=_sha("post-hoc-action"))
    changed_arm = _arm("alternative_side", scenarios=(changed_scenario,))
    outcomes = tuple(
        changed_arm if arm == "alternative_side" else _arm(arm) for arm in COUNTERFACTUAL_ARMS
    )
    labels = _labels(decision, counterfactual_outcomes=outcomes)
    with pytest.raises(
        CandidateOutcomeContractError,
        match="counterfactual_scenarios_differ_from_decision_plan",
    ):
        _archive(decision, labels)
    excluded_arm = _arm(
        "alternative_size",
        excluded_scenario_count=1,
        exclusion_receipt_sha256=_sha("excluded"),
    )
    dropped = tuple(
        excluded_arm if arm == "alternative_size" else _arm(arm) for arm in COUNTERFACTUAL_ARMS
    )
    with pytest.raises(
        CandidateOutcomeContractError,
        match="complete_labels_cannot_drop_planned_scenarios",
    ):
        _archive(decision, _labels(decision, counterfactual_outcomes=dropped))


def test_nonexecuted_candidate_cannot_attach_actual_paper_profit() -> None:
    decision = _decision(decision_disposition="REJECTED")
    labels = _labels(decision, actual=_actual(decision))
    with pytest.raises(
        CandidateOutcomeContractError, match="disposition_execution_evidence_mismatch"
    ):
        _archive(decision, labels)


def test_executed_candidate_requires_actual_persisted_fill_and_close() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    labels = _labels(decision)
    with pytest.raises(
        CandidateOutcomeContractError, match="disposition_execution_evidence_mismatch"
    ):
        _archive(decision, labels)
    actual = _actual(decision)
    assert _archive(decision, _labels(decision, actual=actual)).validate() == []


def test_selected_trade_can_naturally_mature_infeasible_without_fake_fill() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    labels = _labels(decision, eventual_disposition="INFEASIBLE")
    assert _archive(decision, labels).matured_labels is labels
    flat = _decision(decision_disposition="SELECTED_FLAT")
    with pytest.raises(
        CandidateOutcomeContractError,
        match="eventual_disposition_inconsistent_with_decision",
    ):
        _archive(flat, _labels(flat, eventual_disposition="TRADED", actual=_actual(flat)))


def test_actual_paper_outcome_reconciles_notional_and_margin() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    with pytest.raises(CandidateOutcomeContractError, match="must_equal_quantity_times_price"):
        _actual(decision, gross_notional_usd=19.0)
    with pytest.raises(CandidateOutcomeContractError, match="must_equal_notional_over_leverage"):
        _actual(decision, allocated_margin_usd=9.0)
    with pytest.raises(CandidateOutcomeContractError, match="must_match_realized_pnl_usd"):
        _actual(decision, realized_pnl_bps=-99.0)


def test_actual_paper_outcome_clocks_are_ordered_and_label_available() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    with pytest.raises(
        CandidateOutcomeContractError,
        match="fill_record_available_before_execution",
    ):
        _actual(decision, fill_record_available_at_ms=1_000_009)
    with pytest.raises(
        CandidateOutcomeContractError,
        match="accounting_available_before_close_record",
    ):
        _actual(decision, accounting_record_available_at_ms=1_900_000)
    actual = _actual(decision, accounting_record_available_at_ms=1_900_005)
    labels = _labels(decision, actual=actual)
    with pytest.raises(
        CandidateOutcomeContractError,
        match="label_generated_before_accounting_available",
    ):
        _archive(decision, labels)


def test_actual_paper_outcome_requires_final_reduce_only_flat_accounting() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    with pytest.raises(CandidateOutcomeContractError, match="must_be_zero_after_final_close"):
        _actual(decision, reserved_margin_after_close_usd=0.01)
    with pytest.raises(CandidateOutcomeContractError, match="reduce_only_close:must_be_true"):
        _actual(decision, reduce_only_close=False)
    with pytest.raises(CandidateOutcomeContractError, match="exchange_action_taken:must_be_false"):
        _actual(decision, exchange_action_taken=True)


def test_actual_outcome_is_bound_to_exact_selected_action() -> None:
    decision = _decision(decision_disposition="SELECTED_TRADE")
    actual = _actual(decision, selected_action_sha256=_sha("another-action"))
    labels = _labels(decision, actual=actual)
    with pytest.raises(CandidateOutcomeContractError, match="selected_action_hash_mismatch"):
        _archive(decision, labels)


def test_labels_are_bound_to_exact_decision_and_horizon_contract() -> None:
    decision = _decision()
    with pytest.raises(CandidateOutcomeContractError, match="decision_snapshot_hash_mismatch"):
        _archive(
            decision,
            _labels(decision, decision_snapshot_sha256=_sha("different-decision")),
        )
    with pytest.raises(CandidateOutcomeContractError, match="supported_horizon_mismatch"):
        altered = _decision(supported_horizon_seconds=(300, 900, 3_600))
        _archive(
            altered,
            _labels(
                altered,
                supported_horizon_seconds=HORIZONS,
                horizon_labels=tuple(_horizon(horizon) for horizon in HORIZONS),
            ),
        )


def test_archive_revisions_are_append_only_and_temporally_ordered() -> None:
    decision = _decision()
    with pytest.raises(CandidateOutcomeContractError, match="decision_only_revision_must_be_one"):
        _archive(decision, archive_sequence=2)
    labels = _labels(decision)
    with pytest.raises(CandidateOutcomeContractError, match="matured_revision_must_be_two"):
        _archive(decision, labels, archive_sequence=1)
    with pytest.raises(CandidateOutcomeContractError, match="previous_archive_record_sha256"):
        _archive(decision, labels, previous_archive_record_sha256=None)
    with pytest.raises(
        CandidateOutcomeContractError, match="archive_generated_before_content_available"
    ):
        _archive(decision, labels, record_generated_at_ms=1_900_003)


def test_archive_successor_must_reference_exact_first_revision() -> None:
    decision = _decision()
    previous = _archive(decision)
    labels = _labels(decision)
    current = _archive(
        decision,
        labels,
        previous_archive_record_sha256=previous.content_sha256(),
    )
    validate_archive_successor(previous, current)
    forged = _archive(decision, labels, previous_archive_record_sha256=_sha("unrelated"))
    with pytest.raises(CandidateOutcomeContractError, match="previous_archive_hash_mismatch"):
        validate_archive_successor(previous, forged)


def test_archive_successor_cannot_replay_before_previous_revision_available() -> None:
    decision = _decision()
    previous = _archive(
        decision,
        record_generated_at_ms=3_000_000,
        record_available_at_ms=3_000_001,
    )
    labels = _labels(decision)
    current = _archive(
        decision,
        labels,
        previous_archive_record_sha256=previous.content_sha256(),
    )
    with pytest.raises(
        CandidateOutcomeContractError,
        match="successor_generated_before_previous_available",
    ):
        validate_archive_successor(previous, current)


def test_matured_labels_cannot_claim_profit_without_actual_outcome() -> None:
    with pytest.raises(
        CandidateOutcomeContractError, match="no_actual_outcome_cannot_count_as_profit"
    ):
        _labels(_decision(), counts_as_paper_profit=True)


def test_outer_archive_reasserts_paper_only_no_live_authority() -> None:
    with pytest.raises(
        CandidateOutcomeContractError, match="live_gate:must_equal_blocked_human_only"
    ):
        _archive(live_gate="open")
    with pytest.raises(CandidateOutcomeContractError, match="places_real_order:must_be_false"):
        _archive(places_real_order=True)
