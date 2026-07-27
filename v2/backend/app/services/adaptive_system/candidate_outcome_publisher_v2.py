"""Build complete decision revisions from one finalized paper-loop cycle.

The publisher is deliberately downstream of the production paper decision.  It
does not approve a fill and it has no execution authority.  A cycle is accepted
only when the paper-loop status, uncapped intent projection, and preemptive
decision matrix describe the exact same candidate universe.  This makes a
missing/truncated candidate an explicit coverage failure instead of silently
turning a diagnostic sample into a learning corpus.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION,
    COUNTERFACTUAL_ARMS,
    COUNTERFACTUAL_PLAN_SCHEMA_VERSION,
    COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION,
    DECISION_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    LIVE_GATE_BLOCKED_HUMAN_ONLY,
    SCHEMA_VERSION,
    CandidateDecisionEvidenceV2,
    CandidateDecisionOutcomeV2,
    CandidateDecisionSnapshotV2,
    CounterfactualArmPlanV2,
    CounterfactualEvaluationPlanV2,
    CounterfactualScenarioPlanV2,
    canonical_payload_json,
    canonical_payload_sha256,
    horizon_contract_sha256,
)

PUBLISHER_SCHEMA_VERSION = "candidate_outcome_publisher_v2"
CYCLE_SCHEMA_VERSION = "candidate_outcome_publisher_cycle_v2"
PAPER_MATRIX_SCHEMA_VERSION = "preemptive_candidate_decision_matrix_v1"
SUPPORTED_HORIZON_SECONDS = (300, 900, 1_800, 3_600)
HORIZON_CONTRACT_ID = "paper-candidate-outcome-horizons-5m-15m-30m-1h-v2"
DURABLE_FEATURE_SNAPSHOT_SCHEMA_VERSION = "durable_feature_snapshot_archive_record_v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ACTION_AUTHORITY = {
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


class CandidateOutcomePublisherError(ValueError):
    """Raised when a paper cycle cannot prove complete decision coverage."""


def _fail(reason: str, field: str) -> None:
    raise CandidateOutcomePublisherError(f"{field}:{reason}")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomePublisherError("payload:not_strict_json") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail("lowercase_sha256_required", field)
    return value


def _require_identifier(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
        or len(value) > 192
    ):
        _fail("identifier_required", field)
    return value


def _parse_utc_ms(value: object, field: str) -> int:
    if type(value) is not str or not value.strip():
        _fail("aware_utc_timestamp_required", field)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateOutcomePublisherError(
            f"{field}:aware_utc_timestamp_required"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("aware_utc_timestamp_required", field)
    return int(parsed.astimezone(UTC).timestamp() * 1_000)


def _clean_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        encoded = _canonical_json(dict(value))
    except CandidateOutcomePublisherError:
        _fail("strict_json_object_required", "source_mapping")
    decoded = json.loads(encoded)
    if type(decoded) is not dict:
        _fail("strict_json_object_required", "source_mapping")
    return decoded


def _project(source: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: source.get(field) for field in fields}


def _source_receipts(
    intent: Mapping[str, Any],
    registry: PaperRegistryBindingV2,
    feature_snapshot: Mapping[str, Any],
) -> tuple[str, ...]:
    prediction = intent.get("entry_prediction_snapshot")
    prediction = prediction if isinstance(prediction, Mapping) else {}
    source_hashes = prediction.get("source_hashes")
    source_hashes = source_hashes if isinstance(source_hashes, Mapping) else {}
    candidates: list[object] = [
        intent.get("source_row_canonical_sha256"),
        intent.get("preemptive_input_hash"),
        intent.get("feature_abi_sha256"),
        intent.get("feature_builder_sha256"),
        intent.get("policy_fingerprint"),
        registry.checkpoint_bundle_sha256,
        registry.weight_sha256,
        registry.model_parameter_fingerprint,
        registry.feature_abi_sha256,
        feature_snapshot.get("content_sha256"),
        *source_hashes.values(),
        *(
            feature_snapshot.get("source_hashes").values()
            if isinstance(feature_snapshot.get("source_hashes"), Mapping)
            else ()
        ),
    ]
    receipts = tuple(
        sorted(
            {
                value
                for value in candidates
                if type(value) is str and _SHA256_RE.fullmatch(value) is not None
            }
        )
    )
    if not receipts:
        _fail("source_receipt_required", "source_receipt_sha256s")
    return receipts


@dataclass(frozen=True, slots=True)
class PaperRegistryBindingV2:
    registry_generation: int
    checkpoint_id: str
    checkpoint_bundle_sha256: str
    weight_sha256: str
    model_parameter_fingerprint: str
    feature_abi_sha256: str
    activation_receipt_id: str
    paper_only: bool
    live_eligible: bool

    @classmethod
    def from_payload(cls, payload: object) -> PaperRegistryBindingV2:
        if not isinstance(payload, Mapping):
            _fail("object_required", "registry")
        bundle = payload.get("checkpoint_bundle")
        if not isinstance(bundle, Mapping):
            _fail("checkpoint_bundle_required", "registry")
        generation = payload.get("registry_generation")
        if type(generation) is not int or generation < 1:
            _fail("positive_int_required", "registry.registry_generation")
        result = cls(
            registry_generation=generation,
            checkpoint_id=_require_identifier(
                payload.get("checkpoint_id"), "registry.checkpoint_id"
            ),
            checkpoint_bundle_sha256=_require_sha256(
                payload.get("checkpoint_bundle_sha256"),
                "registry.checkpoint_bundle_sha256",
            ),
            weight_sha256=_require_sha256(
                bundle.get("weight_sha256"), "registry.checkpoint_bundle.weight_sha256"
            ),
            model_parameter_fingerprint=_require_sha256(
                bundle.get("model_parameter_fingerprint"),
                "registry.checkpoint_bundle.model_parameter_fingerprint",
            ),
            feature_abi_sha256=_require_sha256(
                payload.get("feature_abi_sha256"), "registry.feature_abi_sha256"
            ),
            activation_receipt_id=_require_identifier(
                payload.get("receipt_id"), "registry.receipt_id"
            ),
            paper_only=payload.get("paper_only") is True,
            live_eligible=payload.get("live_eligible") is True,
        )
        if not result.paper_only:
            _fail("must_be_true", "registry.paper_only")
        if result.live_eligible:
            _fail("must_be_false", "registry.live_eligible")
        return result


@dataclass(frozen=True, slots=True)
class PublisherCycleV2:
    cycle_generated_at_ms: int
    matrix_generated_at_ms: int
    source_candidate_count: int
    decision_records: tuple[CandidateDecisionOutcomeV2, ...]
    source_candidate_ids_sha256: str
    recorded_candidate_ids_sha256: str
    candidate_recording_coverage: float
    unexplained_candidate_drops: int
    paper_only: bool = True
    live_gate: str = LIVE_GATE_BLOCKED_HUMAN_ONLY
    routes_to_live: bool = False
    places_real_order: bool = False
    exchange_action_taken: bool = False
    schema_version: str = CYCLE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class FeatureSnapshotBindingV2:
    feature_snapshot_id: str
    content_sha256: str
    feature_cutoff_ms: int
    available_at_ms: int
    original_decision_time_ms: int
    latest_closed_kline_close_time_ms: int
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int


def _require_same_optional_value(
    declared: object,
    authoritative: object,
    field: str,
) -> None:
    if declared not in (None, "") and declared != authoritative:
        _fail("durable_feature_snapshot_mismatch", field)


def _bind_durable_feature_snapshot(
    *,
    intent: Mapping[str, Any],
    prediction: Mapping[str, Any],
    feature_snapshot: Mapping[str, Any],
    cycle_generated_at_ms: int,
    registry: PaperRegistryBindingV2,
) -> FeatureSnapshotBindingV2:
    """Validate one verified archive record against its exact paper candidate.

    Persistence callers must load the record with archive ``verify=True``.  The
    content digest is rechecked here so the pure cycle builder also rejects a
    mutated fixture or an unverified mapping.
    """

    if feature_snapshot.get("schema_version") != DURABLE_FEATURE_SNAPSHOT_SCHEMA_VERSION:
        _fail("schema_mismatch", "feature_snapshot.schema_version")
    content_digest = _require_sha256(
        feature_snapshot.get("content_sha256"), "feature_snapshot.content_sha256"
    )
    content_material = {
        key: value for key, value in feature_snapshot.items() if key != "content_sha256"
    }
    if _sha256(content_material) != content_digest:
        _fail("content_digest_mismatch", "feature_snapshot.content_sha256")

    _require_identifier(
        prediction.get("prediction_id"), "intent.entry_prediction_snapshot.prediction_id"
    )
    snapshot_id = _require_identifier(
        feature_snapshot.get("snapshot_id"), "feature_snapshot.snapshot_id"
    )
    declared_snapshot_ids = {
        str(value)
        for value in (
            intent.get("entry_feature_snapshot_id"),
            intent.get("feature_snapshot_id"),
            prediction.get("feature_snapshot_id"),
        )
        if value not in (None, "")
    }
    if declared_snapshot_ids != {snapshot_id}:
        _fail("identity_mismatch", "feature_snapshot.snapshot_id")
    _require_same_optional_value(
        feature_snapshot.get("feature_snapshot_id"),
        snapshot_id,
        "feature_snapshot.feature_snapshot_id",
    )

    symbol = _require_identifier(
        str(intent.get("symbol") or "").upper(), "intent.symbol"
    )
    timeframe = _require_identifier(str(intent.get("timeframe") or ""), "intent.timeframe")
    if str(feature_snapshot.get("symbol") or "").upper() != symbol:
        _fail("symbol_mismatch", "feature_snapshot.symbol")
    if str(feature_snapshot.get("timeframe") or "") != timeframe:
        _fail("timeframe_mismatch", "feature_snapshot.timeframe")
    _require_same_optional_value(prediction.get("symbol"), symbol, "prediction.symbol")
    _require_same_optional_value(prediction.get("timeframe"), timeframe, "prediction.timeframe")

    checkpoint = feature_snapshot.get("checkpoint_id")
    if checkpoint not in (None, "") and checkpoint != registry.checkpoint_id:
        _fail("checkpoint_mismatch", "feature_snapshot.checkpoint_id")
    original_decision_ms = _parse_utc_ms(intent.get("decision_time"), "intent.decision_time")
    prediction_decision_ms = _parse_utc_ms(
        prediction.get("decision_time"), "intent.entry_prediction_snapshot.decision_time"
    )
    archive_decision_ms = _parse_utc_ms(
        feature_snapshot.get("decision_time"), "feature_snapshot.decision_time"
    )
    if original_decision_ms != prediction_decision_ms:
        _fail("millisecond_identity_mismatch", "prediction.decision_time")
    if archive_decision_ms > original_decision_ms:
        _fail("source_decision_after_candidate_decision", "feature_snapshot.decision_time")
    if original_decision_ms > cycle_generated_at_ms:
        _fail("paper_decision_after_cycle_record", "intent.decision_time")

    feature_cutoff_ms = _parse_utc_ms(
        feature_snapshot.get("feature_cutoff"), "feature_snapshot.feature_cutoff"
    )
    for source, value in (
        (
            "intent.feature_cutoff",
            intent.get("entry_feature_cutoff") or intent.get("feature_cutoff"),
        ),
        ("prediction.feature_cutoff", prediction.get("feature_cutoff")),
    ):
        if _parse_utc_ms(value, source) != feature_cutoff_ms:
            _fail("millisecond_identity_mismatch", source)
    available_at_ms = _parse_utc_ms(
        feature_snapshot.get("available_at"), "feature_snapshot.available_at"
    )
    prediction_available_at_ms = _parse_utc_ms(
        prediction.get("available_at"), "intent.entry_prediction_snapshot.available_at"
    )
    if available_at_ms != prediction_available_at_ms:
        _fail("millisecond_identity_mismatch", "feature_snapshot.available_at")
    if not feature_cutoff_ms <= available_at_ms <= archive_decision_ms <= original_decision_ms:
        _fail("clock_order_invalid", "feature_snapshot.available_at")

    if feature_snapshot.get("candle_closed_confirmed") is not True:
        _fail("must_be_true", "feature_snapshot.candle_closed_confirmed")
    if feature_snapshot.get("latest_unclosed_kline_excluded") is not True:
        _fail("must_be_true", "feature_snapshot.latest_unclosed_kline_excluded")
    latest_closed = feature_snapshot.get("latest_closed_kline_close_time_ms")
    if type(latest_closed) is not int or latest_closed < 1:
        _fail("positive_int_required", "feature_snapshot.latest_closed_kline_close_time_ms")
    exclusion_decision = feature_snapshot.get(
        "latest_unclosed_exclusion_decision_time_ms"
    )
    if type(exclusion_decision) is not int or exclusion_decision < 1:
        _fail(
            "positive_int_required",
            "feature_snapshot.latest_unclosed_exclusion_decision_time_ms",
        )
    exclusion_method = _require_identifier(
        feature_snapshot.get("latest_unclosed_exclusion_method"),
        "feature_snapshot.latest_unclosed_exclusion_method",
    )
    if not latest_closed <= feature_cutoff_ms <= exclusion_decision <= archive_decision_ms:
        _fail("clock_order_invalid", "feature_snapshot.finality")

    finality_crosschecks = (
        (
            "intent.entry_feature_latest_unclosed_kline_excluded",
            intent.get("entry_feature_latest_unclosed_kline_excluded"),
            True,
        ),
        (
            "intent.entry_feature_latest_unclosed_exclusion_method",
            intent.get("entry_feature_latest_unclosed_exclusion_method"),
            exclusion_method,
        ),
        (
            "intent.entry_feature_latest_unclosed_exclusion_decision_time_ms",
            intent.get("entry_feature_latest_unclosed_exclusion_decision_time_ms"),
            exclusion_decision,
        ),
        (
            "intent.entry_feature_latest_closed_kline_close_time_ms",
            intent.get("entry_feature_latest_closed_kline_close_time_ms"),
            latest_closed,
        ),
    )
    for field, declared, authoritative in finality_crosschecks:
        _require_same_optional_value(declared, authoritative, field)
    if not isinstance(feature_snapshot.get("features"), Mapping) or not feature_snapshot.get(
        "features"
    ):
        _fail("nonempty_mapping_required", "feature_snapshot.features")

    return FeatureSnapshotBindingV2(
        feature_snapshot_id=snapshot_id,
        content_sha256=content_digest,
        feature_cutoff_ms=feature_cutoff_ms,
        available_at_ms=available_at_ms,
        original_decision_time_ms=original_decision_ms,
        latest_closed_kline_close_time_ms=latest_closed,
        latest_unclosed_exclusion_method=exclusion_method,
        latest_unclosed_exclusion_decision_time_ms=exclusion_decision,
    )


_MODEL_FIELDS = (
    "prediction_id",
    "source_prediction_id",
    "model_id",
    "model_version",
    "checkpoint_id",
    "action_labels",
    "action_probabilities",
    "raw_action_logits",
    "selected_action_index",
    "selected_action_probability",
    "confidence_calibrated",
    "expected_move_after_cost_bps",
    "policy_value",
    "feature_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "source_hashes",
)
_PROPOSED_ACTION_FIELDS = (
    "prediction_id",
    "symbol",
    "timeframe",
    "side",
    "selected_action",
    "target_notional_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "effective_leverage",
    "recommended_leverage",
    "recommended_margin_mode",
    "entry_price",
    "stop_distance_bps",
    "expected_move_after_cost_bps",
)
_COMPONENT_FIELDS = (
    "pre_trade_profit_probability",
    "pre_trade_loss_probability",
    "microstructure_trust_score",
    "exit_feasibility_score",
    "regime_compatibility_score",
    "confidence_overstatement_risk",
    "execution_probability",
    "expected_slippage_bps",
    "expected_funding_bps",
    "observed_spread_bps",
    "depth_derived_price_impact_bps",
    "mark_index_divergence_bps",
    "expected_shortfall_usd",
    "modeled_999_adverse_move_bps",
    "pre_trade_expected_net_pnl_usd",
    "pre_trade_expected_gross_pnl_usd",
    "pre_trade_expected_cost_usd",
    "pre_trade_max_loss_usd",
    "preemptive_predicate_details",
)
_PORTFOLIO_FIELDS = (
    "paper_cycle_base_resource_evidence",
    "paper_cycle_base_resource_evidence_hash",
    "paper_cycle_reservation_snapshot",
    "paper_cycle_reservation_snapshot_hash",
    "paper_dynamic_envelope_reservation_evidence",
    "paper_dynamic_envelope_reservation_evidence_hash",
    "portfolio_exposure_after_trade",
    "correlation_exposure_after_trade",
    "drawdown_bps",
    "risk_budget_usd",
    "allocated_margin_usd",
    "gross_notional_usd",
)
_EXECUTION_FIELDS = (
    "allocator_decision",
    "allocator_reason",
    "paper_fill_allowed",
    "paper_fill_allowed_source",
    "paper_fill_gate_status",
    "paper_fill_gate_block_reasons",
    "paper_fill_block_reason",
    "paper_execution_minimum_feasible",
    "paper_execution_minimum_executable_notional",
    "paper_execution_minimum_executable_quantity",
    "paper_execution_mark_price",
    "paper_exchange_filter_snapshot_hash",
    "paper_exchange_filter_status",
    "gross_notional_usd",
    "allocated_margin_usd",
    "effective_leverage",
    "observed_bid",
    "observed_ask",
    "observed_spread_bps",
    "fee_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
    "cost_source",
    "cost_source_timestamp",
    "preemptive_decision",
    "preemptive_decision_id",
    "preemptive_decision_reasons",
)


def _decision_disposition(intent: Mapping[str, Any]) -> tuple[str, str, str]:
    if intent.get("paper_fill_allowed") is True:
        side = str(intent.get("side") or intent.get("selected_action") or "").upper()
        return (
            "SELECTED_TRADE",
            "PAPER_FINAL_GOVERNED_AUTHORIZATION",
            side if side in {"LONG", "SHORT"} else "TRADE",
        )
    allocator = str(intent.get("allocator_decision") or "")
    infeasible = (
        allocator.startswith("BLOCK_EXCHANGE")
        or intent.get("paper_execution_minimum_feasible") is False
        or str(intent.get("paper_fill_block_reason") or "").startswith("EXCHANGE_")
    )
    reasons = intent.get("paper_fill_gate_block_reasons")
    if not isinstance(reasons, list):
        reasons = []
    reason = str(
        intent.get("paper_fill_block_reason")
        or (reasons[0] if reasons else None)
        or allocator
        or intent.get("preemptive_action")
        or intent.get("preemptive_decision")
        or "PAPER_POLICY_SELECTED_FLAT"
    )
    return (
        "INFEASIBLE" if infeasible else "REJECTED",
        reason[:512],
        "REMAIN_FLAT",
    )


def _evidence(
    *,
    kind: str,
    candidate_id: str,
    payload: dict[str, Any],
    source_receipts: tuple[str, ...],
    feature_cutoff_ms: int,
    latest_closed_ms: int,
    exclusion_method: str,
    exclusion_decision_ms: int,
    decision_time_ms: int,
) -> CandidateDecisionEvidenceV2:
    payload = {**payload, **_SAFE_ACTION_AUTHORITY}
    payload_json = canonical_payload_json(payload)
    source_record_sha256 = _sha256(payload)
    return CandidateDecisionEvidenceV2(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        evidence_kind=kind,
        record_id=f"{candidate_id}-{kind}",
        source_record_sha256=source_record_sha256,
        source_event_time_ms=feature_cutoff_ms,
        producer_generated_at_ms=decision_time_ms,
        record_generated_at_ms=decision_time_ms,
        record_available_at_ms=decision_time_ms,
        feature_cutoff_ms=feature_cutoff_ms,
        latest_closed_kline_close_time_ms=latest_closed_ms,
        latest_unclosed_kline_excluded=True,
        latest_unclosed_exclusion_method=exclusion_method,
        latest_unclosed_exclusion_decision_time_ms=exclusion_decision_ms,
        payload_json=payload_json,
        payload_sha256=canonical_payload_sha256(payload_json),
        source_receipt_sha256s=source_receipts,
        complete=True,
    )


def _counterfactual_plan(
    *,
    candidate_id: str,
    selected_action_payload: Mapping[str, Any],
    horizon_contract_digest: str,
    decision_time_ms: int,
    source_receipts: tuple[str, ...],
) -> CounterfactualEvaluationPlanV2:
    arms: list[CounterfactualArmPlanV2] = []
    for arm in COUNTERFACTUAL_ARMS:
        action_material = {
            "schema_version": "candidate_counterfactual_action_template_v2",
            "candidate_id": candidate_id,
            "arm_name": arm,
            "selected_action": dict(selected_action_payload),
            "paper_only": True,
            "counts_as_paper_profit": False,
            "actual_accounting_effect": False,
        }
        scenario = CounterfactualScenarioPlanV2(
            schema_version=COUNTERFACTUAL_SCENARIO_PLAN_SCHEMA_VERSION,
            scenario_id=f"{candidate_id}-{arm}",
            action_sha256=_sha256(action_material),
        )
        arms.append(
            CounterfactualArmPlanV2(
                schema_version=COUNTERFACTUAL_ARM_PLAN_SCHEMA_VERSION,
                arm_name=arm,
                scenarios=(scenario,),
            )
        )
    plan_material = {
        "candidate_id": candidate_id,
        "supported_horizon_seconds": SUPPORTED_HORIZON_SECONDS,
        "horizon_contract_sha256": horizon_contract_digest,
        "arm_action_sha256s": [
            arm.scenarios[0].action_sha256 for arm in arms
        ],
    }
    return CounterfactualEvaluationPlanV2(
        schema_version=COUNTERFACTUAL_PLAN_SCHEMA_VERSION,
        plan_id=f"cfp2_{_sha256(plan_material)}",
        candidate_id=candidate_id,
        supported_horizon_seconds=SUPPORTED_HORIZON_SECONDS,
        horizon_contract_sha256=horizon_contract_digest,
        arms=tuple(arms),
        producer_generated_at_ms=decision_time_ms,
        record_available_at_ms=decision_time_ms,
        source_receipt_sha256s=source_receipts,
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


def build_decision_revision(
    *,
    intent: Mapping[str, Any],
    feature_snapshot: Mapping[str, Any],
    cycle_generated_at_ms: int,
    registry: PaperRegistryBindingV2,
) -> CandidateDecisionOutcomeV2:
    """Convert one finalized paper intent into revision one of the archive."""

    if type(cycle_generated_at_ms) is not int or cycle_generated_at_ms < 1:
        _fail("positive_int_required", "cycle_generated_at_ms")
    prediction_id = _require_identifier(intent.get("prediction_id"), "intent.prediction_id")
    preemptive_id = _require_identifier(
        intent.get("preemptive_decision_id"), "intent.preemptive_decision_id"
    )
    checkpoint_id = _require_identifier(intent.get("checkpoint_id"), "intent.checkpoint_id")
    declared_generations = {
        value
        for value in (
            intent.get("checkpoint_generation"),
            intent.get("active_model_registry_generation"),
        )
        if value is not None
    }
    if any(type(value) is not int for value in declared_generations):
        _fail("positive_int_required", "intent.checkpoint_generation")
    if declared_generations and declared_generations != {registry.registry_generation}:
        _fail("active_registry_generation_mismatch", "intent.checkpoint_generation")
    checkpoint_generation = registry.registry_generation
    if checkpoint_id != registry.checkpoint_id:
        _fail("active_registry_checkpoint_mismatch", "intent.checkpoint_id")
    if intent.get("paper_only") is not True:
        _fail("must_be_true", "intent.paper_only")
    for field in ("routes_to_live", "places_real_order", "live_order"):
        if intent.get(field) not in {False, None}:
            _fail("must_be_false", f"intent.{field}")
    if intent.get("order_submitted") is True or intent.get("test_order_submitted") is True:
        _fail("order_submission_forbidden", "intent")

    policy_id = _require_identifier(
        intent.get("policy_id") or intent.get("candidate_id"), "intent.policy_id"
    )
    policy_sha256 = _require_sha256(
        intent.get("policy_fingerprint"), "intent.policy_fingerprint"
    )
    declared_feature_abi = intent.get("feature_abi_sha256")
    feature_abi = (
        _require_sha256(declared_feature_abi, "intent.feature_abi_sha256")
        if declared_feature_abi not in (None, "")
        else registry.feature_abi_sha256
    )
    if feature_abi != registry.feature_abi_sha256:
        _fail("active_registry_feature_abi_mismatch", "intent.feature_abi_sha256")

    identity_material = {
        "prediction_id": prediction_id,
        "preemptive_decision_id": preemptive_id,
        "policy_id": policy_id,
        "policy_sha256": policy_sha256,
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_id": checkpoint_id,
    }
    candidate_id = f"cdo2_{_sha256(identity_material)}"
    prediction = _clean_mapping(intent.get("entry_prediction_snapshot"))
    if prediction.get("prediction_id") != prediction_id:
        _fail("entry_prediction_identity_mismatch", "intent.entry_prediction_snapshot")
    feature_binding = _bind_durable_feature_snapshot(
        intent=intent,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
        cycle_generated_at_ms=cycle_generated_at_ms,
        registry=registry,
    )
    feature_cutoff_ms = feature_binding.feature_cutoff_ms
    latest_closed = feature_binding.latest_closed_kline_close_time_ms
    exclusion_decision = feature_binding.latest_unclosed_exclusion_decision_time_ms
    exclusion_method = feature_binding.latest_unclosed_exclusion_method
    original_decision_ms = feature_binding.original_decision_time_ms

    source_receipts = _source_receipts(intent, registry, feature_snapshot)
    disposition, disposition_reason, final_action = _decision_disposition(intent)
    model_payload = {
        "schema_version": "candidate_model_distributions_projection_v2",
        **_project(prediction, _MODEL_FIELDS),
        "feature_abi_sha256": feature_abi,
        "durable_feature_snapshot_content_sha256": feature_binding.content_sha256,
        "original_policy_decision_time_ms": original_decision_ms,
    }
    proposed_payload = {
        "schema_version": "candidate_proposed_action_projection_v2",
        **_project(intent, _PROPOSED_ACTION_FIELDS),
        "proposed_action": str(intent.get("side") or intent.get("selected_action") or "").upper(),
    }
    selected_payload = {
        "schema_version": "candidate_selected_action_projection_v2",
        "candidate_id": candidate_id,
        "prediction_id": prediction_id,
        "preemptive_decision_id": preemptive_id,
        "selected_action": final_action,
        "decision_disposition": disposition,
        "disposition_reason": disposition_reason,
        "production_preemptive_decision": intent.get("preemptive_decision"),
        "production_preemptive_action": intent.get("preemptive_action"),
        "production_preemptive_reasons": intent.get("preemptive_decision_reasons") or [],
        "paper_fill_allowed": intent.get("paper_fill_allowed") is True,
    }
    component_payload = {
        "schema_version": "candidate_component_estimates_projection_v2",
        **_project(intent, _COMPONENT_FIELDS),
        "missing_estimate_names": sorted(
            field
            for field in _COMPONENT_FIELDS
            if intent.get(field) is None
        ),
    }
    portfolio_payload = {
        "schema_version": "candidate_portfolio_state_projection_v2",
        **_project(intent, _PORTFOLIO_FIELDS),
    }
    execution_payload = {
        "schema_version": "candidate_execution_state_projection_v2",
        **_project(intent, _EXECUTION_FIELDS),
    }

    evidence = {
        kind: _evidence(
            kind=kind,
            candidate_id=candidate_id,
            payload=payload,
            source_receipts=source_receipts,
            feature_cutoff_ms=feature_cutoff_ms,
            latest_closed_ms=latest_closed,
            exclusion_method=exclusion_method,
            exclusion_decision_ms=exclusion_decision,
            decision_time_ms=cycle_generated_at_ms,
        )
        for kind, payload in (
            ("model_distributions", model_payload),
            ("proposed_action", proposed_payload),
            ("selected_action", selected_payload),
            ("component_estimates", component_payload),
            ("portfolio_state", portfolio_payload),
            ("execution_state", execution_payload),
        )
    }
    state_payload = {
        "market_state_id": intent.get("market_state_id"),
        "feature_snapshot_id": feature_binding.feature_snapshot_id,
        "feature_snapshot_content_sha256": feature_binding.content_sha256,
        "feature_snapshot_available_at_ms": feature_binding.available_at_ms,
        "feature_abi_sha256": feature_abi,
        "feature_cutoff_ms": feature_cutoff_ms,
        "latest_closed_kline_close_time_ms": latest_closed,
        "symbol": intent.get("symbol"),
        "timeframe": intent.get("timeframe"),
    }
    state_id = _require_identifier(
        intent.get("market_state_id") or feature_binding.feature_snapshot_id,
        "intent.market_state_id",
    )
    horizon_digest = horizon_contract_sha256(
        policy_id=policy_id,
        policy_sha256=policy_sha256,
        checkpoint_id=checkpoint_id,
        checkpoint_sha256=registry.checkpoint_bundle_sha256,
        supported_horizon_seconds=SUPPORTED_HORIZON_SECONDS,
    )
    plan = _counterfactual_plan(
        candidate_id=candidate_id,
        selected_action_payload=selected_payload,
        horizon_contract_digest=horizon_digest,
        decision_time_ms=cycle_generated_at_ms,
        source_receipts=source_receipts,
    )
    horizon_receipt = _sha256(
        {
            "schema_version": "candidate_horizon_contract_receipt_v2",
            "horizon_contract_id": HORIZON_CONTRACT_ID,
            "horizon_contract_sha256": horizon_digest,
            "source_receipt_sha256s": source_receipts,
            "available_at_ms": cycle_generated_at_ms,
        }
    )
    decision = CandidateDecisionSnapshotV2(
        schema_version=DECISION_SCHEMA_VERSION,
        candidate_id=candidate_id,
        state_id=state_id,
        state_sha256=_sha256(state_payload),
        prediction_id=prediction_id,
        prediction_sha256=_sha256(prediction),
        policy_id=policy_id,
        policy_sha256=policy_sha256,
        checkpoint_generation=checkpoint_generation,
        checkpoint_id=checkpoint_id,
        checkpoint_sha256=registry.checkpoint_bundle_sha256,
        symbol=_require_identifier(str(intent.get("symbol") or "").upper(), "intent.symbol"),
        timeframe=_require_identifier(str(intent.get("timeframe") or ""), "intent.timeframe"),
        decision_disposition=disposition,
        disposition_reason=disposition_reason,
        decision_rationale=(
            "Finalized paper-loop candidate was recorded after all production "
            "policy and physical-feasibility decisions; the archive grants no execution authority."
        ),
        supported_horizon_seconds=SUPPORTED_HORIZON_SECONDS,
        horizon_contract_id=HORIZON_CONTRACT_ID,
        horizon_contract_sha256=horizon_digest,
        horizon_contract_receipt_sha256=horizon_receipt,
        feature_cutoff_ms=feature_cutoff_ms,
        latest_closed_kline_close_time_ms=latest_closed,
        latest_unclosed_kline_excluded=True,
        latest_unclosed_exclusion_method=exclusion_method,
        latest_unclosed_exclusion_decision_time_ms=exclusion_decision,
        decision_time_ms=cycle_generated_at_ms,
        record_generated_at_ms=cycle_generated_at_ms,
        record_available_at_ms=cycle_generated_at_ms,
        model_distributions=evidence["model_distributions"],
        proposed_action=evidence["proposed_action"],
        selected_action=evidence["selected_action"],
        component_estimates=evidence["component_estimates"],
        portfolio_state=evidence["portfolio_state"],
        execution_state=evidence["execution_state"],
        counterfactual_evaluation_plan=plan,
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )
    archive_id = f"{candidate_id}-decision"
    return CandidateDecisionOutcomeV2(
        schema_version=SCHEMA_VERSION,
        archive_record_id=archive_id,
        archive_sequence=1,
        decision=decision,
        matured_labels=None,
        previous_archive_record_sha256=None,
        record_generated_at_ms=cycle_generated_at_ms,
        record_available_at_ms=cycle_generated_at_ms,
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


def build_publisher_cycle(
    *,
    paper_status: Mapping[str, Any],
    intents: object,
    registry_payload: object,
    feature_snapshots_by_id: Mapping[str, Mapping[str, Any]],
) -> PublisherCycleV2:
    """Reconcile and build an exact, non-sampled finalized paper cycle."""

    if paper_status.get("paper_only") is not True:
        _fail("must_be_true", "paper_status.paper_only")
    for field in ("routes_to_live", "places_real_order"):
        if paper_status.get(field) is not False:
            _fail("must_be_false", f"paper_status.{field}")
    matrix = paper_status.get("preemptive_candidate_decision_matrix")
    if not isinstance(matrix, Mapping):
        _fail("matrix_required", "paper_status.preemptive_candidate_decision_matrix")
    if matrix.get("schema_version") != PAPER_MATRIX_SCHEMA_VERSION:
        _fail("schema_mismatch", "matrix.schema_version")
    if matrix.get("paper_only") is not True:
        _fail("must_be_true", "matrix.paper_only")
    for field in ("routes_to_live", "places_real_order"):
        if matrix.get(field) is not False:
            _fail("must_be_false", f"matrix.{field}")
    rows = matrix.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        _fail("object_rows_required", "matrix.rows")
    candidate_count = matrix.get("candidate_count")
    if type(candidate_count) is not int or candidate_count < 0:
        _fail("nonnegative_int_required", "matrix.candidate_count")
    if candidate_count != len(rows):
        _fail("diagnostic_matrix_truncated", "matrix.rows")
    if not isinstance(intents, list) or any(not isinstance(row, Mapping) for row in intents):
        _fail("object_rows_required", "intents")
    if len(intents) != candidate_count:
        _fail("candidate_count_mismatch", "intents")

    cycle_ms = _parse_utc_ms(paper_status.get("generated_utc"), "paper_status.generated_utc")
    matrix_ms = _parse_utc_ms(matrix.get("generated_utc"), "matrix.generated_utc")
    if matrix_ms > cycle_ms:
        _fail("matrix_generated_after_status", "matrix.generated_utc")
    registry = PaperRegistryBindingV2.from_payload(registry_payload)
    if not isinstance(feature_snapshots_by_id, Mapping):
        _fail("mapping_required", "feature_snapshots_by_id")

    def identities(
        source_rows: list[Mapping[str, Any]], source: str
    ) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        seen_predictions: set[str] = set()
        for index, row in enumerate(source_rows):
            decision_id = _require_identifier(
                row.get("preemptive_decision_id"), f"{source}[{index}].preemptive_decision_id"
            )
            prediction_id = _require_identifier(
                row.get("prediction_id"), f"{source}[{index}].prediction_id"
            )
            if decision_id in result:
                _fail("duplicate_preemptive_decision_id", source)
            if prediction_id in seen_predictions:
                _fail("duplicate_prediction_id", source)
            result[decision_id] = row
            seen_predictions.add(prediction_id)
        return result

    matrix_by_id = identities(rows, "matrix.rows")
    intents_by_id = identities(intents, "intents")
    if set(matrix_by_id) != set(intents_by_id):
        _fail("candidate_identity_universe_mismatch", "cycle")
    for decision_id, matrix_row in matrix_by_id.items():
        intent = intents_by_id[decision_id]
        if matrix_row.get("prediction_id") != intent.get("prediction_id"):
            _fail("prediction_identity_mismatch", f"cycle.{decision_id}")
        if matrix_row.get("checkpoint_id") != intent.get("checkpoint_id"):
            _fail("checkpoint_identity_mismatch", f"cycle.{decision_id}")

    records = tuple(
        sorted(
            (
                build_decision_revision(
                    intent=intents_by_id[decision_id],
                    feature_snapshot=feature_snapshots_by_id.get(
                        str(
                            intents_by_id[decision_id].get("entry_feature_snapshot_id")
                            or intents_by_id[decision_id].get("feature_snapshot_id")
                            or (
                                intents_by_id[decision_id].get("entry_prediction_snapshot")
                                or {}
                            ).get("feature_snapshot_id")
                        ),
                        {},
                    ),
                    cycle_generated_at_ms=cycle_ms,
                    registry=registry,
                )
                for decision_id in sorted(intents_by_id)
            ),
            key=lambda record: record.decision.candidate_id,
        )
    )
    source_ids = tuple(sorted(matrix_by_id))
    recorded_ids = tuple(sorted(record.decision.candidate_id for record in records))
    unexplained = candidate_count - len(records)
    return PublisherCycleV2(
        cycle_generated_at_ms=cycle_ms,
        matrix_generated_at_ms=matrix_ms,
        source_candidate_count=candidate_count,
        decision_records=records,
        source_candidate_ids_sha256=_sha256(source_ids),
        recorded_candidate_ids_sha256=_sha256(recorded_ids),
        candidate_recording_coverage=(
            len(records) / candidate_count if candidate_count else 1.0
        ),
        unexplained_candidate_drops=unexplained,
    )


__all__ = [
    "PUBLISHER_SCHEMA_VERSION",
    "CYCLE_SCHEMA_VERSION",
    "SUPPORTED_HORIZON_SECONDS",
    "HORIZON_CONTRACT_ID",
    "DURABLE_FEATURE_SNAPSHOT_SCHEMA_VERSION",
    "CandidateOutcomePublisherError",
    "FeatureSnapshotBindingV2",
    "PaperRegistryBindingV2",
    "PublisherCycleV2",
    "build_decision_revision",
    "build_publisher_cycle",
]
