"""Immutable decision and matured-outcome evidence for every policy candidate.

This module is a pure, paper-only contract foundation for FINAL PASS FP-060.
It intentionally performs no persistence and has no execution authority.  A
candidate is first archived as an immutable decision snapshot.  Once every
declared horizon is final, a second append-only archive revision may attach a
separately hashed label record.  Rejected and flat candidates therefore become
learning evidence without ever becoming simulated profit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

SCHEMA_VERSION = "CandidateDecisionOutcomeV2"
DECISION_SCHEMA_VERSION = "CandidateDecisionSnapshotV2"
EVIDENCE_SCHEMA_VERSION = "CandidateDecisionEvidenceV2"
COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION = "CounterfactualScenarioPlanV2"
COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION = "CounterfactualArmPlanV2"
COUNTERFACTUAL_PLAN_SCHEMA_VERSION = "CounterfactualEvaluationPlanV2"
HORIZON_LABEL_SCHEMA_VERSION = "CandidateHorizonLabelV2"
COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION = "CounterfactualScenarioV2"
COUNTERFACTUAL_ARM_SCHEMA_VERSION = "CounterfactualArmOutcomeV2"
ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION = "ActualPaperExecutionOutcomeV2"
MATURED_LABELS_SCHEMA_VERSION = "MaturedCandidateLabelsV2"

LIVE_GATE_BLOCKED_HUMAN_ONLY = "blocked_human_only"

CANDIDATE_DISPOSITIONS = (
    "TRADED",
    "REJECTED",
    "INFEASIBLE",
    "RISK_REDUCED",
    "FLAT",
    "HEDGED",
)
DECISION_DISPOSITIONS = (
    "SELECTED_TRADE",
    "REJECTED",
    "INFEASIBLE",
    "SELECTED_RISK_REDUCED",
    "SELECTED_FLAT",
    "SELECTED_HEDGED",
)
EXECUTED_DISPOSITIONS = frozenset({"TRADED", "RISK_REDUCED", "HEDGED"})
_EVENTUAL_DISPOSITIONS_BY_DECISION = {
    "SELECTED_TRADE": frozenset({"TRADED", "REJECTED", "INFEASIBLE", "FLAT"}),
    "REJECTED": frozenset({"REJECTED"}),
    "INFEASIBLE": frozenset({"INFEASIBLE"}),
    "SELECTED_RISK_REDUCED": frozenset({"RISK_REDUCED", "REJECTED", "INFEASIBLE", "FLAT"}),
    "SELECTED_FLAT": frozenset({"FLAT"}),
    "SELECTED_HEDGED": frozenset({"HEDGED", "REJECTED", "INFEASIBLE", "FLAT"}),
}
COUNTERFACTUAL_ARMS = (
    "unhedged",
    "hedged",
    "alternative_side",
    "alternative_size",
    "alternative_leverage",
    "alternative_entry",
    "alternative_exit",
)
DECISION_EVIDENCE_KINDS = (
    "model_distributions",
    "proposed_action",
    "selected_action",
    "component_estimates",
    "portfolio_state",
    "execution_state",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOLERANCE = 1e-9
_AUTHORITY_FIELDS = frozenset(
    {
        "paper_only",
        "live_gate",
        "routes_to_live",
        "places_real_order",
        "exchange_action_taken",
        "live_order",
        "execution_authority",
        "live_eligible",
        "live_submission_ready",
        "execution_domain",
        "requires_hard_validator",
        "policy_authority_scope",
    }
)


class CandidateOutcomeContractError(ValueError):
    """Raised when candidate evidence is incomplete, mutable, or unsafe."""


def _raise(reason: str, field: str) -> None:
    raise CandidateOutcomeContractError(f"{field}:{reason}")


def _require_literal(value: object, expected: str, field: str) -> None:
    if type(value) is not str or value != expected:
        _raise(f"must_equal_{expected}", field)


def _require_member(value: object, allowed: tuple[str, ...], field: str) -> None:
    if type(value) is not str or value not in allowed:
        _raise("invalid_value", field)


def _require_identifier(value: object, field: str, *, max_length: int = 192) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        or len(value) > max_length
    ):
        _raise("must_be_non_empty_without_whitespace", field)


def _require_text(value: object, field: str, *, max_length: int = 2048) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or value.strip() != value
        or len(value) > max_length
    ):
        _raise("must_be_non_blank_trimmed_text", field)


def _require_sha256(value: object, field: str) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_positive_int(value: object, field: str) -> None:
    if type(value) is not int or value < 1:
        _raise("must_be_positive_int", field)


def _require_nonnegative_int(value: object, field: str) -> None:
    if type(value) is not int or value < 0:
        _raise("must_be_nonnegative_int", field)


def _require_finite_float(
    value: object,
    field: str,
    *,
    minimum: float | None = None,
    strictly_positive: bool = False,
) -> None:
    if type(value) is not float or not math.isfinite(value):
        _raise("must_be_finite_float", field)
    if minimum is not None and value < minimum:
        _raise(f"must_be_at_least_{minimum}", field)
    if strictly_positive and value <= 0.0:
        _raise("must_be_strictly_positive", field)


def _require_sorted_unique_sha256s(value: object, field: str) -> None:
    if type(value) is not tuple or not value:
        _raise("must_be_non_empty_tuple", field)
    if value != tuple(sorted(set(value))):
        _raise("must_be_sorted_and_unique", field)
    for index, digest in enumerate(value):
        _require_sha256(digest, f"{field}[{index}]")


def _to_json_primitive(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {
            field.name: _to_json_primitive(getattr(value, field.name)) for field in fields(value)
        }
    if type(value) is tuple:
        return [_to_json_primitive(item) for item in value]
    if type(value) is list:
        return [_to_json_primitive(item) for item in value]
    if type(value) is dict:
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                _raise("json_object_keys_must_be_exact_strings", "record")
            result[key] = _to_json_primitive(item)
        return result
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _raise("unsupported_json_runtime_type", "record")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            _to_json_primitive(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except CandidateOutcomeContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomeContractError("record:not_canonical_json") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise("duplicate_json_key", "payload_json")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    _raise(f"nonfinite_json_number:{value}", "payload_json")


def _require_payload_authority_safe(payload: object, field: str) -> None:
    if type(payload) is dict:
        for key, value in payload.items():
            if key in _AUTHORITY_FIELDS:
                if key == "paper_only" and value is not True:
                    _raise("payload_authority_contradiction", field)
                if key == "live_gate" and (
                    type(value) is not str or value != LIVE_GATE_BLOCKED_HUMAN_ONLY
                ):
                    _raise("payload_authority_contradiction", field)
                if (
                    key
                    in {
                        "routes_to_live",
                        "places_real_order",
                        "exchange_action_taken",
                        "live_order",
                        "execution_authority",
                        "live_eligible",
                        "live_submission_ready",
                    }
                    and value is not False
                ):
                    _raise("payload_authority_contradiction", field)
                if key == "execution_domain" and (type(value) is not str or value != "PAPER"):
                    _raise("payload_authority_contradiction", field)
                if key == "requires_hard_validator" and value is not True:
                    _raise("payload_authority_contradiction", field)
                if key == "policy_authority_scope" and (
                    type(value) is not str or value != "trading_action_only"
                ):
                    _raise("payload_authority_contradiction", field)
            _require_payload_authority_safe(value, field)
    elif type(payload) is list:
        for value in payload:
            _require_payload_authority_safe(value, field)


def canonical_payload_json(payload: dict[str, Any]) -> str:
    """Return the only accepted encoding for decision evidence payloads."""

    if type(payload) is not dict or not payload:
        _raise("must_be_non_empty_object", "payload")
    return _canonical_json(payload)


def canonical_payload_sha256(payload_json: str) -> str:
    if type(payload_json) is not str:
        _raise("must_be_str", "payload_json")
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateDecisionEvidenceV2:
    """An immutable, complete decision-time input bound to source receipts."""

    schema_version: str
    evidence_kind: str
    record_id: str
    source_record_sha256: str
    source_event_time_ms: int
    producer_generated_at_ms: int
    record_generated_at_ms: int
    record_available_at_ms: int
    feature_cutoff_ms: int
    latest_closed_kline_close_time_ms: int
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    payload_json: str
    payload_sha256: str
    source_receipt_sha256s: tuple[str, ...]
    complete: bool

    def __post_init__(self) -> None:
        _require_literal(self.schema_version, EVIDENCE_SCHEMA_VERSION, "schema_version")
        _require_member(self.evidence_kind, DECISION_EVIDENCE_KINDS, "evidence_kind")
        _require_identifier(self.record_id, "record_id")
        _require_sha256(self.source_record_sha256, "source_record_sha256")
        for field in (
            "source_event_time_ms",
            "producer_generated_at_ms",
            "record_generated_at_ms",
            "record_available_at_ms",
            "feature_cutoff_ms",
            "latest_closed_kline_close_time_ms",
            "latest_unclosed_exclusion_decision_time_ms",
        ):
            _require_positive_int(getattr(self, field), field)
        if self.source_event_time_ms > self.producer_generated_at_ms:
            _raise("source_event_after_producer_generated", "source_event_time_ms")
        if self.producer_generated_at_ms > self.record_generated_at_ms:
            _raise("producer_generated_after_record_generated", "producer_generated_at_ms")
        if self.record_generated_at_ms > self.record_available_at_ms:
            _raise("record_generated_after_available", "record_generated_at_ms")
        if self.latest_closed_kline_close_time_ms > self.feature_cutoff_ms:
            _raise("closed_kline_after_feature_cutoff", "feature_cutoff_ms")
        if self.latest_unclosed_kline_excluded is not True:
            _raise("must_be_true", "latest_unclosed_kline_excluded")
        _require_text(
            self.latest_unclosed_exclusion_method,
            "latest_unclosed_exclusion_method",
        )
        if self.latest_unclosed_exclusion_decision_time_ms < self.feature_cutoff_ms:
            _raise(
                "exclusion_decision_before_feature_cutoff",
                "latest_unclosed_exclusion_decision_time_ms",
            )
        if self.latest_unclosed_exclusion_decision_time_ms > self.producer_generated_at_ms:
            _raise(
                "exclusion_decision_after_producer_generated",
                "latest_unclosed_exclusion_decision_time_ms",
            )
        if type(self.payload_json) is not str:
            _raise("must_be_str", "payload_json")
        try:
            payload = json.loads(
                self.payload_json,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_nonfinite_json,
            )
        except CandidateOutcomeContractError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CandidateOutcomeContractError("payload_json:invalid_json") from exc
        if type(payload) is not dict or not payload:
            _raise("must_encode_non_empty_object", "payload_json")
        if self.payload_json != _canonical_json(payload):
            _raise("must_be_canonical_json", "payload_json")
        _require_payload_authority_safe(payload, "payload_json")
        if self.evidence_kind in {"proposed_action", "selected_action", "execution_state"}:
            expected_authority = {
                "paper_only": True,
                "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
                "execution_authority": False,
                "live_eligible": False,
                "live_submission_ready": False,
                "execution_domain": "PAPER",
                "requires_hard_validator": True,
                "policy_authority_scope": "trading_action_only",
            }
            for key, expected in expected_authority.items():
                if (
                    key not in payload
                    or payload[key] != expected
                    or type(payload[key]) is not type(expected)
                ):
                    _raise(
                        "required_safe_authority_field_missing_or_invalid", f"payload_json.{key}"
                    )
        _require_sha256(self.payload_sha256, "payload_sha256")
        if self.payload_sha256 != canonical_payload_sha256(self.payload_json):
            _raise("must_match_payload", "payload_sha256")
        _require_sorted_unique_sha256s(
            self.source_receipt_sha256s,
            "source_receipt_sha256s",
        )
        if self.complete is not True:
            _raise("must_be_true", "complete")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class CounterfactualScenarioPlanV2:
    schema_version: str
    scenario_id: str
    action_sha256: str

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION,
            "schema_version",
        )
        _require_identifier(self.scenario_id, "scenario_id")
        _require_sha256(self.action_sha256, "action_sha256")


@dataclass(frozen=True, slots=True)
class CounterfactualArmPlanV2:
    schema_version: str
    arm_name: str
    scenarios: tuple[CounterfactualScenarioPlanV2, ...]

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION,
            "schema_version",
        )
        _require_member(self.arm_name, COUNTERFACTUAL_ARMS, "arm_name")
        if type(self.scenarios) is not tuple or not self.scenarios:
            _raise("must_be_non_empty_tuple", "scenarios")
        for index, scenario in enumerate(self.scenarios):
            if type(scenario) is not CounterfactualScenarioPlanV2:
                _raise("structured_scenario_plan_required", f"scenarios[{index}]")
        scenario_ids = tuple(scenario.scenario_id for scenario in self.scenarios)
        if scenario_ids != tuple(sorted(set(scenario_ids))):
            _raise("scenario_ids_must_be_sorted_and_unique", "scenarios")


@dataclass(frozen=True, slots=True)
class CounterfactualEvaluationPlanV2:
    """Decision-time scenario universe; matured labels cannot select it post hoc."""

    schema_version: str
    plan_id: str
    candidate_id: str
    supported_horizon_seconds: tuple[int, ...]
    horizon_contract_sha256: str
    arms: tuple[CounterfactualArmPlanV2, ...]
    producer_generated_at_ms: int
    record_available_at_ms: int
    source_receipt_sha256s: tuple[str, ...]
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            COUNTERFACTUAL_PLAN_SCHEMA_VERSION,
            "schema_version",
        )
        _require_identifier(self.plan_id, "plan_id")
        _require_identifier(self.candidate_id, "candidate_id")
        if type(self.supported_horizon_seconds) is not tuple or not self.supported_horizon_seconds:
            _raise("must_be_non_empty_tuple", "supported_horizon_seconds")
        for index, horizon in enumerate(self.supported_horizon_seconds):
            _require_positive_int(horizon, f"supported_horizon_seconds[{index}]")
        if self.supported_horizon_seconds != tuple(sorted(set(self.supported_horizon_seconds))):
            _raise("must_be_sorted_and_unique", "supported_horizon_seconds")
        _require_sha256(self.horizon_contract_sha256, "horizon_contract_sha256")
        if type(self.arms) is not tuple:
            _raise("must_be_tuple", "arms")
        for index, arm in enumerate(self.arms):
            if type(arm) is not CounterfactualArmPlanV2:
                _raise("structured_arm_plan_required", f"arms[{index}]")
        if tuple(arm.arm_name for arm in self.arms) != COUNTERFACTUAL_ARMS:
            _raise("must_cover_every_counterfactual_arm_exactly", "arms")
        _require_positive_int(self.producer_generated_at_ms, "producer_generated_at_ms")
        _require_positive_int(self.record_available_at_ms, "record_available_at_ms")
        if self.record_available_at_ms < self.producer_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        _require_sorted_unique_sha256s(
            self.source_receipt_sha256s,
            "source_receipt_sha256s",
        )
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        _require_literal(self.live_gate, LIVE_GATE_BLOCKED_HUMAN_ONLY, "live_gate")
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken"):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


def horizon_contract_sha256(
    *,
    policy_id: str,
    policy_sha256: str,
    checkpoint_id: str,
    checkpoint_sha256: str,
    supported_horizon_seconds: tuple[int, ...],
) -> str:
    """Bind the supported universe to the exact policy and checkpoint."""

    return _canonical_sha256(
        {
            "schema_version": "CandidateHorizonContractV2",
            "policy_id": policy_id,
            "policy_sha256": policy_sha256,
            "checkpoint_id": checkpoint_id,
            "checkpoint_sha256": checkpoint_sha256,
            "supported_horizon_seconds": supported_horizon_seconds,
        }
    )


@dataclass(frozen=True, slots=True)
class CandidateDecisionSnapshotV2:
    """Complete point-in-time snapshot produced for every candidate."""

    schema_version: str
    candidate_id: str
    state_id: str
    state_sha256: str
    prediction_id: str
    prediction_sha256: str
    policy_id: str
    policy_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    symbol: str
    timeframe: str
    decision_disposition: str
    disposition_reason: str
    decision_rationale: str
    supported_horizon_seconds: tuple[int, ...]
    horizon_contract_id: str
    horizon_contract_sha256: str
    horizon_contract_receipt_sha256: str
    feature_cutoff_ms: int
    latest_closed_kline_close_time_ms: int
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    decision_time_ms: int
    record_generated_at_ms: int
    record_available_at_ms: int
    model_distributions: CandidateDecisionEvidenceV2
    proposed_action: CandidateDecisionEvidenceV2
    selected_action: CandidateDecisionEvidenceV2
    component_estimates: CandidateDecisionEvidenceV2
    portfolio_state: CandidateDecisionEvidenceV2
    execution_state: CandidateDecisionEvidenceV2
    counterfactual_evaluation_plan: CounterfactualEvaluationPlanV2
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool

    def __post_init__(self) -> None:
        _require_literal(self.schema_version, DECISION_SCHEMA_VERSION, "schema_version")
        for field in (
            "candidate_id",
            "state_id",
            "prediction_id",
            "policy_id",
            "checkpoint_id",
            "symbol",
            "timeframe",
        ):
            _require_identifier(getattr(self, field), field)
        for field in (
            "state_sha256",
            "prediction_sha256",
            "policy_sha256",
            "checkpoint_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        _require_positive_int(self.checkpoint_generation, "checkpoint_generation")
        _require_member(
            self.decision_disposition,
            DECISION_DISPOSITIONS,
            "decision_disposition",
        )
        _require_text(self.disposition_reason, "disposition_reason")
        _require_text(self.decision_rationale, "decision_rationale")
        if type(self.supported_horizon_seconds) is not tuple or not self.supported_horizon_seconds:
            _raise("must_be_non_empty_tuple", "supported_horizon_seconds")
        for index, horizon in enumerate(self.supported_horizon_seconds):
            _require_positive_int(horizon, f"supported_horizon_seconds[{index}]")
        if self.supported_horizon_seconds != tuple(sorted(set(self.supported_horizon_seconds))):
            _raise("must_be_sorted_and_unique", "supported_horizon_seconds")
        _require_identifier(self.horizon_contract_id, "horizon_contract_id")
        _require_sha256(self.horizon_contract_sha256, "horizon_contract_sha256")
        _require_sha256(
            self.horizon_contract_receipt_sha256,
            "horizon_contract_receipt_sha256",
        )
        expected_horizon_contract_sha256 = horizon_contract_sha256(
            policy_id=self.policy_id,
            policy_sha256=self.policy_sha256,
            checkpoint_id=self.checkpoint_id,
            checkpoint_sha256=self.checkpoint_sha256,
            supported_horizon_seconds=self.supported_horizon_seconds,
        )
        if self.horizon_contract_sha256 != expected_horizon_contract_sha256:
            _raise("must_bind_policy_checkpoint_and_horizons", "horizon_contract_sha256")
        for field in (
            "feature_cutoff_ms",
            "latest_closed_kline_close_time_ms",
            "latest_unclosed_exclusion_decision_time_ms",
            "decision_time_ms",
            "record_generated_at_ms",
            "record_available_at_ms",
        ):
            _require_positive_int(getattr(self, field), field)
        if self.latest_unclosed_kline_excluded is not True:
            _raise("must_be_true", "latest_unclosed_kline_excluded")
        _require_text(
            self.latest_unclosed_exclusion_method,
            "latest_unclosed_exclusion_method",
        )
        if self.latest_closed_kline_close_time_ms > self.feature_cutoff_ms:
            _raise("closed_kline_after_feature_cutoff", "feature_cutoff_ms")
        if self.feature_cutoff_ms > self.decision_time_ms:
            _raise("feature_cutoff_after_decision", "feature_cutoff_ms")
        if (
            not self.feature_cutoff_ms
            <= self.latest_unclosed_exclusion_decision_time_ms
            <= (self.decision_time_ms)
        ):
            _raise(
                "exclusion_decision_outside_cutoff_to_decision_window",
                "latest_unclosed_exclusion_decision_time_ms",
            )
        if self.record_generated_at_ms < self.decision_time_ms:
            _raise("record_generated_before_decision", "record_generated_at_ms")
        if self.record_available_at_ms < self.record_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        for field, expected_kind in zip(
            DECISION_EVIDENCE_KINDS,
            DECISION_EVIDENCE_KINDS,
            strict=True,
        ):
            evidence = getattr(self, field)
            if type(evidence) is not CandidateDecisionEvidenceV2:
                _raise("structured_evidence_required", field)
            if evidence.evidence_kind != expected_kind:
                _raise(f"must_have_kind_{expected_kind}", field)
            if evidence.record_available_at_ms > self.decision_time_ms:
                _raise("evidence_available_after_decision", field)
            if evidence.feature_cutoff_ms != self.feature_cutoff_ms:
                _raise("feature_cutoff_mismatch", field)
            if evidence.latest_closed_kline_close_time_ms != self.latest_closed_kline_close_time_ms:
                _raise("latest_closed_kline_mismatch", field)
            if evidence.latest_unclosed_exclusion_method != self.latest_unclosed_exclusion_method:
                _raise("latest_unclosed_exclusion_method_mismatch", field)
            if (
                evidence.latest_unclosed_exclusion_decision_time_ms
                != self.latest_unclosed_exclusion_decision_time_ms
            ):
                _raise("latest_unclosed_exclusion_decision_time_mismatch", field)
        if type(self.counterfactual_evaluation_plan) is not CounterfactualEvaluationPlanV2:
            _raise(
                "structured_counterfactual_plan_required",
                "counterfactual_evaluation_plan",
            )
        if self.counterfactual_evaluation_plan.candidate_id != self.candidate_id:
            _raise("candidate_id_mismatch", "counterfactual_evaluation_plan")
        if (
            self.counterfactual_evaluation_plan.supported_horizon_seconds
            != self.supported_horizon_seconds
        ):
            _raise("supported_horizon_mismatch", "counterfactual_evaluation_plan")
        if (
            self.counterfactual_evaluation_plan.horizon_contract_sha256
            != self.horizon_contract_sha256
        ):
            _raise("horizon_contract_mismatch", "counterfactual_evaluation_plan")
        if self.counterfactual_evaluation_plan.record_available_at_ms > self.decision_time_ms:
            _raise("plan_available_after_decision", "counterfactual_evaluation_plan")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        _require_literal(self.live_gate, LIVE_GATE_BLOCKED_HUMAN_ONLY, "live_gate")
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken"):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class CandidateHorizonLabelV2:
    schema_version: str
    horizon_seconds: int
    horizon_end_ms: int
    future_return_bps: float
    source_event_time_ms: int
    producer_generated_at_ms: int
    record_available_at_ms: int
    source_receipt_sha256: str
    finality_proven: bool

    def __post_init__(self) -> None:
        _require_literal(self.schema_version, HORIZON_LABEL_SCHEMA_VERSION, "schema_version")
        _require_positive_int(self.horizon_seconds, "horizon_seconds")
        for field in (
            "horizon_end_ms",
            "source_event_time_ms",
            "producer_generated_at_ms",
            "record_available_at_ms",
        ):
            _require_positive_int(getattr(self, field), field)
        _require_finite_float(self.future_return_bps, "future_return_bps")
        if self.source_event_time_ms < self.horizon_end_ms:
            _raise("source_event_before_horizon_end", "source_event_time_ms")
        if self.producer_generated_at_ms < self.source_event_time_ms:
            _raise("producer_generated_before_event", "producer_generated_at_ms")
        if self.record_available_at_ms < self.producer_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        _require_sha256(self.source_receipt_sha256, "source_receipt_sha256")
        if self.finality_proven is not True:
            _raise("must_be_true", "finality_proven")


@dataclass(frozen=True, slots=True)
class CounterfactualScenarioV2:
    schema_version: str
    scenario_id: str
    action_sha256: str
    gross_pnl_bps: float
    fees_bps: float
    spread_bps: float
    slippage_bps: float
    funding_bps: float
    market_impact_bps: float
    after_cost_pnl_bps: float
    source_event_time_ms: int
    producer_generated_at_ms: int
    record_available_at_ms: int
    source_receipt_sha256s: tuple[str, ...]
    finality_proven: bool
    counts_as_paper_profit: bool
    actual_accounting_effect: bool

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION,
            "schema_version",
        )
        _require_identifier(self.scenario_id, "scenario_id")
        _require_sha256(self.action_sha256, "action_sha256")
        for field in (
            "gross_pnl_bps",
            "fees_bps",
            "spread_bps",
            "slippage_bps",
            "funding_bps",
            "market_impact_bps",
            "after_cost_pnl_bps",
        ):
            _require_finite_float(getattr(self, field), field)
        for field in ("fees_bps", "spread_bps", "slippage_bps", "market_impact_bps"):
            if getattr(self, field) < 0.0:
                _raise("must_be_nonnegative", field)
        expected = self.gross_pnl_bps - (
            self.fees_bps
            + self.spread_bps
            + self.slippage_bps
            + self.funding_bps
            + self.market_impact_bps
        )
        if not math.isclose(
            self.after_cost_pnl_bps,
            expected,
            rel_tol=0.0,
            abs_tol=_TOLERANCE,
        ):
            _raise("must_equal_gross_minus_costs", "after_cost_pnl_bps")
        _require_positive_int(self.source_event_time_ms, "source_event_time_ms")
        _require_positive_int(self.producer_generated_at_ms, "producer_generated_at_ms")
        _require_positive_int(self.record_available_at_ms, "record_available_at_ms")
        if self.producer_generated_at_ms < self.source_event_time_ms:
            _raise("producer_generated_before_event", "producer_generated_at_ms")
        if self.record_available_at_ms < self.producer_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        _require_sorted_unique_sha256s(
            self.source_receipt_sha256s,
            "source_receipt_sha256s",
        )
        if self.finality_proven is not True:
            _raise("must_be_true", "finality_proven")
        if self.counts_as_paper_profit is not False:
            _raise("must_be_false", "counts_as_paper_profit")
        if self.actual_accounting_effect is not False:
            _raise("must_be_false", "actual_accounting_effect")


@dataclass(frozen=True, slots=True)
class CounterfactualArmOutcomeV2:
    schema_version: str
    arm_name: str
    scenario_universe_sha256: str
    scenarios: tuple[CounterfactualScenarioV2, ...]
    eligible_scenario_count: int
    excluded_scenario_count: int
    exclusion_receipt_sha256: str | None
    complete: bool

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            COUNTERFACTUAL_ARM_SCHEMA_VERSION,
            "schema_version",
        )
        _require_member(self.arm_name, COUNTERFACTUAL_ARMS, "arm_name")
        _require_sha256(self.scenario_universe_sha256, "scenario_universe_sha256")
        if type(self.scenarios) is not tuple or not self.scenarios:
            _raise("must_be_non_empty_tuple", "scenarios")
        for index, scenario in enumerate(self.scenarios):
            if type(scenario) is not CounterfactualScenarioV2:
                _raise("structured_scenario_required", f"scenarios[{index}]")
        scenario_ids = tuple(scenario.scenario_id for scenario in self.scenarios)
        if scenario_ids != tuple(sorted(set(scenario_ids))):
            _raise("scenario_ids_must_be_sorted_and_unique", "scenarios")
        _require_positive_int(self.eligible_scenario_count, "eligible_scenario_count")
        _require_nonnegative_int(self.excluded_scenario_count, "excluded_scenario_count")
        if self.eligible_scenario_count != len(self.scenarios):
            _raise("must_equal_scenario_count", "eligible_scenario_count")
        if self.excluded_scenario_count:
            _require_sha256(self.exclusion_receipt_sha256, "exclusion_receipt_sha256")
        elif self.exclusion_receipt_sha256 is not None:
            _raise("must_be_none_without_exclusions", "exclusion_receipt_sha256")
        expected_universe_sha256 = _canonical_sha256(
            {
                "arm_name": self.arm_name,
                "scenario_content_sha256s": tuple(
                    _canonical_sha256(asdict(scenario)) for scenario in self.scenarios
                ),
                "eligible_scenario_count": self.eligible_scenario_count,
                "excluded_scenario_count": self.excluded_scenario_count,
                "exclusion_receipt_sha256": self.exclusion_receipt_sha256,
            }
        )
        if self.scenario_universe_sha256 != expected_universe_sha256:
            _raise("must_match_complete_universe", "scenario_universe_sha256")
        if self.complete is not True:
            _raise("must_be_true", "complete")


@dataclass(frozen=True, slots=True)
class ActualPaperExecutionOutcomeV2:
    schema_version: str
    candidate_id: str
    selected_action_sha256: str
    signal_id: str
    intent_id: str
    fill_id: str
    position_id: str
    closed_trade_id: str
    fill_receipt_sha256: str
    close_receipt_sha256: str
    accounting_receipt_sha256: str
    fill_execution_time_ms: int
    fill_record_available_at_ms: int
    close_execution_time_ms: int
    close_record_available_at_ms: int
    accounting_record_available_at_ms: int
    executed_quantity: float
    execution_price: float
    gross_notional_usd: float
    effective_leverage: float
    allocated_margin_usd: float
    realized_pnl_usd: float
    realized_pnl_bps: float
    open_quantity_after_close: float
    used_margin_after_close_usd: float
    reserved_margin_after_close_usd: float
    reduce_only_close: bool
    fully_closed: bool
    paper_only: bool
    places_real_order: bool
    exchange_action_taken: bool

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION,
            "schema_version",
        )
        for field in (
            "candidate_id",
            "signal_id",
            "intent_id",
            "fill_id",
            "position_id",
            "closed_trade_id",
        ):
            _require_identifier(getattr(self, field), field)
        for field in (
            "selected_action_sha256",
            "fill_receipt_sha256",
            "close_receipt_sha256",
            "accounting_receipt_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        for field in (
            "fill_execution_time_ms",
            "fill_record_available_at_ms",
            "close_execution_time_ms",
            "close_record_available_at_ms",
            "accounting_record_available_at_ms",
        ):
            _require_positive_int(getattr(self, field), field)
        if self.fill_record_available_at_ms < self.fill_execution_time_ms:
            _raise("fill_record_available_before_execution", "fill_record_available_at_ms")
        if self.close_execution_time_ms < self.fill_record_available_at_ms:
            _raise("close_execution_before_fill_available", "close_execution_time_ms")
        if self.close_record_available_at_ms < self.close_execution_time_ms:
            _raise("close_record_available_before_execution", "close_record_available_at_ms")
        if self.accounting_record_available_at_ms < self.close_record_available_at_ms:
            _raise(
                "accounting_available_before_close_record",
                "accounting_record_available_at_ms",
            )
        for field in (
            "executed_quantity",
            "execution_price",
            "gross_notional_usd",
            "effective_leverage",
            "allocated_margin_usd",
        ):
            _require_finite_float(getattr(self, field), field, strictly_positive=True)
        for field in (
            "realized_pnl_usd",
            "realized_pnl_bps",
            "open_quantity_after_close",
            "used_margin_after_close_usd",
            "reserved_margin_after_close_usd",
        ):
            _require_finite_float(getattr(self, field), field)
        for field in (
            "open_quantity_after_close",
            "used_margin_after_close_usd",
            "reserved_margin_after_close_usd",
        ):
            if getattr(self, field) != 0.0:
                _raise("must_be_zero_after_final_close", field)
        if not math.isclose(
            self.gross_notional_usd,
            self.executed_quantity * self.execution_price,
            rel_tol=0.0,
            abs_tol=_TOLERANCE,
        ):
            _raise("must_equal_quantity_times_price", "gross_notional_usd")
        if not math.isclose(
            self.allocated_margin_usd,
            self.gross_notional_usd / self.effective_leverage,
            rel_tol=0.0,
            abs_tol=_TOLERANCE,
        ):
            _raise("must_equal_notional_over_leverage", "allocated_margin_usd")
        expected_realized_pnl_bps = self.realized_pnl_usd / self.gross_notional_usd * 10_000.0
        if not math.isclose(
            self.realized_pnl_bps,
            expected_realized_pnl_bps,
            rel_tol=0.0,
            abs_tol=_TOLERANCE,
        ):
            _raise("must_match_realized_pnl_usd", "realized_pnl_bps")
        if self.reduce_only_close is not True:
            _raise("must_be_true", "reduce_only_close")
        if self.fully_closed is not True:
            _raise("must_be_true", "fully_closed")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.places_real_order is not False:
            _raise("must_be_false", "places_real_order")
        if self.exchange_action_taken is not False:
            _raise("must_be_false", "exchange_action_taken")


@dataclass(frozen=True, slots=True)
class MaturedLabelsV2:
    """Complete final labels; counterfactuals remain outside paper accounting."""

    schema_version: str
    candidate_id: str
    decision_snapshot_sha256: str
    counterfactual_plan_sha256: str
    eventual_disposition: str
    supported_horizon_seconds: tuple[int, ...]
    horizon_labels: tuple[CandidateHorizonLabelV2, ...]
    max_favorable_excursion_bps: float
    max_adverse_excursion_bps: float
    realized_volatility_bps: float
    estimated_executable_entry: float
    estimated_executable_exit: float
    fees_bps: float
    spread_bps: float
    slippage_bps: float
    funding_bps: float
    market_impact_bps: float
    stop_result: str
    time_exit_result: str
    profit_exit_result: str
    counterfactual_outcomes: tuple[CounterfactualArmOutcomeV2, ...]
    actual_paper_outcome: ActualPaperExecutionOutcomeV2 | None
    labeler_id: str
    labeler_version_sha256: str
    label_source_receipt_sha256s: tuple[str, ...]
    summary_source_event_time_ms: int
    summary_producer_generated_at_ms: int
    summary_record_available_at_ms: int
    summary_receipt_sha256: str
    summary_finality_proven: bool
    label_generated_at_ms: int
    record_available_at_ms: int
    matured: bool
    complete: bool
    counts_as_paper_profit: bool

    def __post_init__(self) -> None:
        _require_literal(
            self.schema_version,
            MATURED_LABELS_SCHEMA_VERSION,
            "schema_version",
        )
        _require_identifier(self.candidate_id, "candidate_id")
        _require_sha256(self.decision_snapshot_sha256, "decision_snapshot_sha256")
        _require_sha256(self.counterfactual_plan_sha256, "counterfactual_plan_sha256")
        _require_member(
            self.eventual_disposition,
            CANDIDATE_DISPOSITIONS,
            "eventual_disposition",
        )
        if type(self.supported_horizon_seconds) is not tuple or not self.supported_horizon_seconds:
            _raise("must_be_non_empty_tuple", "supported_horizon_seconds")
        for index, horizon in enumerate(self.supported_horizon_seconds):
            _require_positive_int(horizon, f"supported_horizon_seconds[{index}]")
        if self.supported_horizon_seconds != tuple(sorted(set(self.supported_horizon_seconds))):
            _raise("must_be_sorted_and_unique", "supported_horizon_seconds")
        if type(self.horizon_labels) is not tuple or not self.horizon_labels:
            _raise("must_be_non_empty_tuple", "horizon_labels")
        for index, label in enumerate(self.horizon_labels):
            if type(label) is not CandidateHorizonLabelV2:
                _raise("structured_horizon_label_required", f"horizon_labels[{index}]")
        actual_horizons = tuple(label.horizon_seconds for label in self.horizon_labels)
        if actual_horizons != self.supported_horizon_seconds:
            _raise("must_cover_every_supported_horizon_exactly", "horizon_labels")
        for field in (
            "max_favorable_excursion_bps",
            "max_adverse_excursion_bps",
            "realized_volatility_bps",
            "estimated_executable_entry",
            "estimated_executable_exit",
            "fees_bps",
            "spread_bps",
            "slippage_bps",
            "funding_bps",
            "market_impact_bps",
        ):
            _require_finite_float(getattr(self, field), field)
        if self.max_favorable_excursion_bps < 0.0:
            _raise("must_be_nonnegative", "max_favorable_excursion_bps")
        if self.max_adverse_excursion_bps > 0.0:
            _raise("must_be_nonpositive", "max_adverse_excursion_bps")
        if self.realized_volatility_bps < 0.0:
            _raise("must_be_nonnegative", "realized_volatility_bps")
        if self.estimated_executable_entry <= 0.0:
            _raise("must_be_strictly_positive", "estimated_executable_entry")
        if self.estimated_executable_exit <= 0.0:
            _raise("must_be_strictly_positive", "estimated_executable_exit")
        for field in ("fees_bps", "spread_bps", "slippage_bps", "market_impact_bps"):
            if getattr(self, field) < 0.0:
                _raise("must_be_nonnegative", field)
        for field in ("stop_result", "time_exit_result", "profit_exit_result"):
            _require_text(getattr(self, field), field)
        if type(self.counterfactual_outcomes) is not tuple:
            _raise("must_be_tuple", "counterfactual_outcomes")
        for index, arm in enumerate(self.counterfactual_outcomes):
            if type(arm) is not CounterfactualArmOutcomeV2:
                _raise(
                    "structured_counterfactual_arm_required", f"counterfactual_outcomes[{index}]"
                )
        arm_names = tuple(arm.arm_name for arm in self.counterfactual_outcomes)
        if arm_names != COUNTERFACTUAL_ARMS:
            _raise("must_cover_every_counterfactual_arm_exactly", "counterfactual_outcomes")
        if (
            self.actual_paper_outcome is not None
            and type(self.actual_paper_outcome) is not ActualPaperExecutionOutcomeV2
        ):
            _raise("structured_actual_outcome_required", "actual_paper_outcome")
        if self.actual_paper_outcome is not None:
            if self.actual_paper_outcome.candidate_id != self.candidate_id:
                _raise("candidate_id_mismatch", "actual_paper_outcome")
            if self.counts_as_paper_profit is not True:
                _raise("actual_outcome_must_count_in_paper_ledger", "counts_as_paper_profit")
        elif self.counts_as_paper_profit is not False:
            _raise("no_actual_outcome_cannot_count_as_profit", "counts_as_paper_profit")
        _require_identifier(self.labeler_id, "labeler_id")
        _require_sha256(self.labeler_version_sha256, "labeler_version_sha256")
        _require_sorted_unique_sha256s(
            self.label_source_receipt_sha256s,
            "label_source_receipt_sha256s",
        )
        for field in (
            "summary_source_event_time_ms",
            "summary_producer_generated_at_ms",
            "summary_record_available_at_ms",
        ):
            _require_positive_int(getattr(self, field), field)
        if self.summary_producer_generated_at_ms < self.summary_source_event_time_ms:
            _raise(
                "summary_generated_before_source_event",
                "summary_producer_generated_at_ms",
            )
        if self.summary_record_available_at_ms < self.summary_producer_generated_at_ms:
            _raise(
                "summary_available_before_generated",
                "summary_record_available_at_ms",
            )
        _require_sha256(self.summary_receipt_sha256, "summary_receipt_sha256")
        if self.summary_finality_proven is not True:
            _raise("must_be_true", "summary_finality_proven")
        _require_positive_int(self.label_generated_at_ms, "label_generated_at_ms")
        _require_positive_int(self.record_available_at_ms, "record_available_at_ms")
        maximum_source_available_at_ms = max(
            label.record_available_at_ms for label in self.horizon_labels
        )
        maximum_horizon_end_ms = max(label.horizon_end_ms for label in self.horizon_labels)
        if self.summary_source_event_time_ms < maximum_horizon_end_ms:
            _raise("summary_source_before_all_horizons_matured", "summary_source_event_time_ms")
        for arm in self.counterfactual_outcomes:
            for scenario in arm.scenarios:
                if scenario.source_event_time_ms < maximum_horizon_end_ms:
                    _raise(
                        "counterfactual_source_before_all_horizons_matured",
                        "counterfactual_outcomes",
                    )
        maximum_counterfactual_available_at_ms = max(
            scenario.record_available_at_ms
            for arm in self.counterfactual_outcomes
            for scenario in arm.scenarios
        )
        if self.label_generated_at_ms < max(
            maximum_source_available_at_ms,
            maximum_counterfactual_available_at_ms,
            self.summary_record_available_at_ms,
        ):
            _raise("label_generated_before_source_available", "label_generated_at_ms")
        if self.record_available_at_ms < self.label_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        if self.matured is not True:
            _raise("must_be_true", "matured")
        if self.complete is not True:
            _raise("must_be_true", "complete")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class CandidateDecisionOutcomeV2:
    """Append-only archive revision containing a decision and optional labels."""

    schema_version: str
    archive_record_id: str
    archive_sequence: int
    decision: CandidateDecisionSnapshotV2
    matured_labels: MaturedLabelsV2 | None
    previous_archive_record_sha256: str | None
    record_generated_at_ms: int
    record_available_at_ms: int
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool

    def __post_init__(self) -> None:
        _require_literal(self.schema_version, SCHEMA_VERSION, "schema_version")
        _require_identifier(self.archive_record_id, "archive_record_id")
        if type(self.decision) is not CandidateDecisionSnapshotV2:
            _raise("structured_decision_required", "decision")
        _require_positive_int(self.archive_sequence, "archive_sequence")
        _require_positive_int(self.record_generated_at_ms, "record_generated_at_ms")
        _require_positive_int(self.record_available_at_ms, "record_available_at_ms")
        if self.matured_labels is None:
            if self.archive_sequence != 1:
                _raise("decision_only_revision_must_be_one", "archive_sequence")
            if self.previous_archive_record_sha256 is not None:
                _raise("first_revision_cannot_have_previous", "previous_archive_record_sha256")
            minimum_generated_at_ms = self.decision.record_available_at_ms
        else:
            if type(self.matured_labels) is not MaturedLabelsV2:
                _raise("structured_labels_required", "matured_labels")
            if self.archive_sequence != 2:
                _raise("matured_revision_must_be_two", "archive_sequence")
            _require_sha256(
                self.previous_archive_record_sha256,
                "previous_archive_record_sha256",
            )
            if self.matured_labels.candidate_id != self.decision.candidate_id:
                _raise("candidate_id_mismatch", "matured_labels")
            if self.matured_labels.decision_snapshot_sha256 != self.decision.content_sha256():
                _raise("decision_snapshot_hash_mismatch", "matured_labels")
            if (
                self.matured_labels.counterfactual_plan_sha256
                != self.decision.counterfactual_evaluation_plan.content_sha256()
            ):
                _raise("counterfactual_plan_hash_mismatch", "matured_labels")
            if (
                self.matured_labels.supported_horizon_seconds
                != self.decision.supported_horizon_seconds
            ):
                _raise("supported_horizon_mismatch", "matured_labels")
            for label in self.matured_labels.horizon_labels:
                expected_horizon_end_ms = (
                    self.decision.decision_time_ms + label.horizon_seconds * 1_000
                )
                if label.horizon_end_ms != expected_horizon_end_ms:
                    _raise("horizon_end_mismatch", "matured_labels")
            allowed_eventual_dispositions = _EVENTUAL_DISPOSITIONS_BY_DECISION[
                self.decision.decision_disposition
            ]
            if self.matured_labels.eventual_disposition not in allowed_eventual_dispositions:
                _raise("eventual_disposition_inconsistent_with_decision", "matured_labels")
            for plan_arm, outcome_arm in zip(
                self.decision.counterfactual_evaluation_plan.arms,
                self.matured_labels.counterfactual_outcomes,
                strict=True,
            ):
                if outcome_arm.excluded_scenario_count != 0:
                    _raise("complete_labels_cannot_drop_planned_scenarios", "matured_labels")
                planned = tuple(
                    (scenario.scenario_id, scenario.action_sha256)
                    for scenario in plan_arm.scenarios
                )
                observed = tuple(
                    (scenario.scenario_id, scenario.action_sha256)
                    for scenario in outcome_arm.scenarios
                )
                if observed != planned:
                    _raise("counterfactual_scenarios_differ_from_decision_plan", "matured_labels")
            is_executed = self.matured_labels.eventual_disposition in EXECUTED_DISPOSITIONS
            if is_executed != (self.matured_labels.actual_paper_outcome is not None):
                _raise("disposition_execution_evidence_mismatch", "matured_labels")
            if self.matured_labels.actual_paper_outcome is not None and (
                self.matured_labels.actual_paper_outcome.selected_action_sha256
                != self.decision.selected_action.content_sha256()
            ):
                _raise("selected_action_hash_mismatch", "matured_labels")
            if self.matured_labels.actual_paper_outcome is not None:
                actual = self.matured_labels.actual_paper_outcome
                if actual.fill_execution_time_ms < self.decision.decision_time_ms:
                    _raise("fill_execution_before_decision", "matured_labels")
                if (
                    actual.accounting_record_available_at_ms
                    > self.matured_labels.label_generated_at_ms
                ):
                    _raise("label_generated_before_accounting_available", "matured_labels")
            minimum_generated_at_ms = self.matured_labels.record_available_at_ms
        if self.record_generated_at_ms < minimum_generated_at_ms:
            _raise("archive_generated_before_content_available", "record_generated_at_ms")
        if self.record_available_at_ms < self.record_generated_at_ms:
            _raise("record_available_before_generated", "record_available_at_ms")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        _require_literal(self.live_gate, LIVE_GATE_BLOCKED_HUMAN_ONLY, "live_gate")
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken"):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)

    def validate(self) -> list[str]:
        """Compatibility helper; construction itself is the validation gate."""

        return []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


def counterfactual_universe_sha256(
    *,
    arm_name: str,
    scenarios: tuple[CounterfactualScenarioV2, ...],
    eligible_scenario_count: int,
    excluded_scenario_count: int,
    exclusion_receipt_sha256: str | None,
) -> str:
    """Deterministic identity required by ``CounterfactualArmOutcomeV2``."""

    return _canonical_sha256(
        {
            "arm_name": arm_name,
            "scenario_content_sha256s": tuple(
                _canonical_sha256(asdict(scenario)) for scenario in scenarios
            ),
            "eligible_scenario_count": eligible_scenario_count,
            "excluded_scenario_count": excluded_scenario_count,
            "exclusion_receipt_sha256": exclusion_receipt_sha256,
        }
    )


def validate_archive_successor(
    previous: CandidateDecisionOutcomeV2,
    current: CandidateDecisionOutcomeV2,
) -> None:
    """Validate the external append-only link between archive revisions."""

    if type(previous) is not CandidateDecisionOutcomeV2:
        _raise("structured_previous_record_required", "previous")
    if type(current) is not CandidateDecisionOutcomeV2:
        _raise("structured_current_record_required", "current")
    if current.archive_sequence != previous.archive_sequence + 1:
        _raise("archive_sequence_not_contiguous", "current")
    if current.archive_record_id == previous.archive_record_id:
        _raise("archive_record_id_must_change", "current")
    if current.previous_archive_record_sha256 != previous.content_sha256():
        _raise("previous_archive_hash_mismatch", "current")
    if current.record_generated_at_ms < previous.record_available_at_ms:
        _raise("successor_generated_before_previous_available", "current")
    if current.decision.content_sha256() != previous.decision.content_sha256():
        _raise("decision_snapshot_changed", "current")
    if previous.matured_labels is not None or current.matured_labels is None:
        _raise("only_decision_to_matured_transition_allowed", "current")


__all__ = [
    "SCHEMA_VERSION",
    "DECISION_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION",
    "COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION",
    "COUNTERFACTUAL_PLAN_SCHEMA_VERSION",
    "HORIZON_LABEL_SCHEMA_VERSION",
    "COUNTERFACTUAL_SCENARIO_SCHEMA_VERSION",
    "COUNTERFACTUAL_ARM_SCHEMA_VERSION",
    "ACTUAL_PAPER_OUTCOME_SCHEMA_VERSION",
    "MATURED_LABELS_SCHEMA_VERSION",
    "LIVE_GATE_BLOCKED_HUMAN_ONLY",
    "CANDIDATE_DISPOSITIONS",
    "DECISION_DISPOSITIONS",
    "COUNTERFACTUAL_ARMS",
    "DECISION_EVIDENCE_KINDS",
    "CandidateOutcomeContractError",
    "CandidateDecisionEvidenceV2",
    "CounterfactualScenarioPlanV2",
    "CounterfactualArmPlanV2",
    "CounterfactualEvaluationPlanV2",
    "CandidateDecisionSnapshotV2",
    "CandidateHorizonLabelV2",
    "CounterfactualScenarioV2",
    "CounterfactualArmOutcomeV2",
    "ActualPaperExecutionOutcomeV2",
    "MaturedLabelsV2",
    "CandidateDecisionOutcomeV2",
    "canonical_payload_json",
    "canonical_payload_sha256",
    "counterfactual_universe_sha256",
    "horizon_contract_sha256",
    "validate_archive_successor",
]
