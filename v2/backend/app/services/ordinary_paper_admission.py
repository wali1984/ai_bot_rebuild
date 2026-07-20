"""Canonical, scale-free admission evidence for ordinary PAPER candidates.

The native trainer owns the source admission decision.  This module gives
downstream PAPER-only workers a small, public contract for independently
recomputing the continuous quality weight, binding the immutable evidence to a
hash, and applying current market-state/microstructure magnitudes without
reintroducing threshold cliffs.

No function in this module can enable live trading or submit an exchange order.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    canonical_sha256,
    exact_cost_provenance_rejection_reasons,
)

ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION = "v2_native_trainer_ordinary_paper_scale_free_admission_v1"
ORDINARY_PAPER_ADMISSION_MODE = "SCALE_FREE_CONTINUOUS_QUALITY_PAPER_ONLY"
ORDINARY_PAPER_QUALITY_FORMULA = (
    "(coverage_percent/100)*calibrated_profit_probability*"
    "(abs(after_cost_edge_bps)/(abs(after_cost_edge_bps)+round_trip_cost_bps))"
)
ORDINARY_PAPER_EVIDENCE_SCHEMA_VERSION = "v2_ordinary_paper_admission_evidence_v1"
MICROSTRUCTURE_TRUST_EVIDENCE_SCHEMA_VERSION = "v2_native_trainer_microstructure_trust_evidence_v1"
MICROSTRUCTURE_TRUST_SOURCE_SCHEMA_VERSION = "microstructure_trust_score_v2"
ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA = (
    "publisher_weight*(market_state_integrity_score/100)*"
    "microstructure_trust_score*(1-sweep_risk_score)"
)

_PAPER_ONLY_LIVE_GATE = "blocked_human_only"
_ALLOWED_MICROSTRUCTURE_ACTIONS = {"ALLOW", "REDUCE_SIZE"}
_RESULT_FACTORY_TOKEN = object()
_IDENTITY_FIELDS = (
    "prediction_id",
    "signal_id",
    "decision_id",
    "market_state_id",
    "symbol",
    "timeframe",
    "selected_action",
    "feature_snapshot_id",
    "feature_vector_hash",
    "input_feature_hash",
    "checkpoint_id",
    "model_version",
    "cycle_id",
    "process_instance_id",
    "candidate_policy_fingerprint",
)
_SOURCE_EVIDENCE_FIELDS = (
    *_IDENTITY_FIELDS,
    "ordinary_paper_admission_schema_version",
    "ordinary_paper_quality_schema_version",
    "ordinary_paper_admission_mode",
    "ordinary_paper_fill_allowed",
    "ordinary_paper_admission_rejection_reasons",
    "ordinary_paper_gate_block_reasons",
    "paper_quality_sizing_formula",
    "paper_quality_sizing_weight",
    "paper_quality_coverage_component",
    "paper_quality_calibrated_probability_component",
    "paper_quality_relative_after_cost_edge_component",
    "paper_quality_zero_boundary_semantics",
    "paper_quality_market_static_threshold_used",
    "paper_quality_paper_only",
    "paper_quality_routes_to_live",
    "paper_quality_places_real_order",
    "legacy_static_thresholds_telemetry_only",
    "data_coverage_percent",
    "confidence_calibrated",
    "confidence_calibration_fitted",
    "confidence_calibration",
    "expected_move_after_cost_bps",
    "round_trip_cost_bps",
    "exact_cost_provenance",
    "exact_cost_provenance_valid",
    "exact_cost_provenance_rejection_reasons",
    "on_policy_sampling_selected",
    "trust_row_accepted_for_training",
    "trust_row_valid_for_training",
    "trust_row_trainer_consumable",
    "row_classification",
    "training_trust_reject_reasons",
    "backfilled",
    "is_backfilled",
    "missing_feature_count",
    "stale_feature_count",
    "missing_feature_names",
    "stale_feature_names",
    "feature_freshness_state",
    "missing_candle_count",
    "duplicate_event_count",
    "out_of_order_event_count",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "candle_closed_confirmed",
    "candle_open_time",
    "candle_close_time",
    "source_event_time",
    "source_event_time_est",
    "source_received_time",
    "source_received_time_est",
    "source_available_time",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "ppo_decision_time",
    "all_tf_candle_timestamps",
    "all_source_event_times",
    "source_candle_timestamps",
    "mtf_snapshot_id",
    "mtf_snapshot_valid",
    "replay_snapshot_id",
    "replay_snapshot_key",
    "replay_snapshot_ready",
    "replay_snapshot_write_success",
    "replay_snapshot_write_acknowledged",
    "replay_snapshot_readback_verified",
    "replay_snapshot_content_sha256",
    "replay_snapshot_ttl_seconds",
    "trust_schema_version",
    "trust_gate_result",
    "source_hashes",
    "microstructure_trust_evidence",
    "microstructure_trust_evidence_sha256",
    "source_availability",
    "source_availability_vector",
    "paper_fill_allowed",
    "routes_to_orchestrator",
    "prediction_eligible",
    "risk_eligible",
    "paper_eligible",
    "live_gate",
    "live_symbols",
    "exchange_mutation",
    "trainer_direct_trading",
    "source_redis_key",
    "source_prediction_observed_ttl_seconds",
)

ORDINARY_PAPER_PROVENANCE_FIELDS = (
    "ordinary_paper_admission_schema_version",
    "ordinary_paper_quality_schema_version",
    "ordinary_paper_admission_mode",
    "ordinary_paper_fill_allowed",
    "ordinary_paper_admission_rejection_reasons",
    "ordinary_paper_gate_block_reasons",
    "paper_quality_sizing_formula",
    "paper_quality_sizing_weight",
    "paper_quality_coverage_component",
    "paper_quality_calibrated_probability_component",
    "paper_quality_relative_after_cost_edge_component",
    "paper_quality_zero_boundary_semantics",
    "paper_quality_market_static_threshold_used",
    "paper_quality_paper_only",
    "paper_quality_routes_to_live",
    "paper_quality_places_real_order",
    "legacy_static_thresholds_telemetry_only",
    "publisher_paper_quality_sizing_weight",
    "ordinary_paper_effective_sizing_weight",
    "ordinary_paper_effective_sizing_formula",
    "ordinary_paper_effective_sizing_factors",
    "ordinary_paper_raw_microstructure_action",
    "ordinary_paper_effective_microstructure_action",
    "ordinary_paper_legacy_microstructure_block_reasons",
    "ordinary_scale_free_paper_admission_revalidated",
    "ordinary_scale_free_paper_admission_rejection_reasons",
    "ordinary_paper_admission_evidence",
    "ordinary_paper_admission_evidence_sha256",
    "microstructure_trust_evidence",
    "microstructure_trust_evidence_sha256",
    "source_redis_key",
    "source_prediction_observed_ttl_seconds",
)


def build_microstructure_trust_evidence(
    *,
    source_payload: Mapping[str, Any] | None,
    source_payload_readback: Mapping[str, Any] | None,
    source_key: str,
    source_observed_ttl_seconds: Any,
    tensor_id: str,
    feature_snapshot_id: str,
    tensor_source_lineage_hash: str,
    tensor_decision_time: Any,
    symbol: str,
    timeframe: str,
    tensor_temporal_rejection_reasons: Sequence[Any] = (),
) -> dict[str, Any]:
    """Build an immutable envelope from the exact source read by the trainer.

    ``source_payload_readback`` must come from the same Redis key in a read-only
    GET+TTL observation.  A changed, missing, persistent, or expired key is
    represented explicitly and rejected by every downstream validator.
    """

    loaded = copy.deepcopy(dict(source_payload)) if isinstance(source_payload, Mapping) else {}
    observed = (
        copy.deepcopy(dict(source_payload_readback))
        if isinstance(source_payload_readback, Mapping)
        else {}
    )
    loaded_hash = canonical_sha256(loaded) if loaded else None
    observed_hash = canonical_sha256(observed) if observed else None
    evidence: dict[str, Any] = {
        "schema_version": MICROSTRUCTURE_TRUST_EVIDENCE_SCHEMA_VERSION,
        "source_schema_version": observed.get("schema_version"),
        "source_key": source_key,
        "source_payload": observed,
        "source_payload_sha256": observed_hash,
        "source_payload_loaded_sha256": loaded_hash,
        "source_readback_verified": bool(loaded and observed and loaded_hash == observed_hash),
        "source_observed_ttl_seconds": source_observed_ttl_seconds,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_tensor_id": tensor_id,
        "feature_snapshot_id": feature_snapshot_id,
        "tensor_source_lineage_hash": tensor_source_lineage_hash,
        "tensor_decision_time": tensor_decision_time,
        "tensor_temporal_rejection_reasons": [
            str(reason)
            for reason in tensor_temporal_rejection_reasons
            if str(reason).startswith("MICROSTRUCTURE_TRUST_")
        ],
    }
    producer_reasons = _microstructure_trust_evidence_core_rejection_reasons(
        evidence,
        expected_symbol=symbol,
        expected_timeframe=timeframe,
        expected_tensor_id=tensor_id,
        expected_feature_snapshot_id=feature_snapshot_id,
        expected_tensor_source_lineage_hash=tensor_source_lineage_hash,
        expected_ppo_decision_time=None,
    )
    evidence["producer_rejection_reasons"] = producer_reasons
    evidence["evidence_valid"] = not producer_reasons
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def microstructure_trust_evidence_rejection_reasons(
    evidence: Mapping[str, Any] | Any,
    *,
    expected_symbol: Any,
    expected_timeframe: Any,
    expected_tensor_id: Any,
    expected_feature_snapshot_id: Any,
    expected_tensor_source_lineage_hash: Any,
    expected_ppo_decision_time: Any,
) -> list[str]:
    """Independently validate exact-source identity, PIT clocks, TTL, and hash."""

    if not isinstance(evidence, Mapping):
        return ["microstructure_trust_evidence_missing"]
    row = copy.deepcopy(dict(evidence))
    claimed_hash = row.pop("evidence_sha256", None)
    try:
        computed_hash = canonical_sha256(row)
    except (TypeError, ValueError):
        computed_hash = None
    reasons = _microstructure_trust_evidence_core_rejection_reasons(
        evidence,
        expected_symbol=expected_symbol,
        expected_timeframe=expected_timeframe,
        expected_tensor_id=expected_tensor_id,
        expected_feature_snapshot_id=expected_feature_snapshot_id,
        expected_tensor_source_lineage_hash=expected_tensor_source_lineage_hash,
        expected_ppo_decision_time=expected_ppo_decision_time,
    )
    if not _is_sha256(claimed_hash) or claimed_hash != computed_hash:
        reasons.append("microstructure_trust_evidence_hash_mismatch")
    producer_reasons = evidence.get("producer_rejection_reasons")
    if not isinstance(producer_reasons, list) or sorted(set(producer_reasons)) != sorted(
        set(reasons) - {"microstructure_trust_evidence_hash_mismatch"}
    ):
        reasons.append("microstructure_trust_evidence_producer_reasons_mismatch")
    if evidence.get("evidence_valid") is not (not producer_reasons):
        reasons.append("microstructure_trust_evidence_validity_claim_mismatch")
    return sorted(set(reasons))


def microstructure_admission_values(payload: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Extract admission inputs only from the hash-bound source envelope."""

    evidence = (
        payload.get("microstructure_trust_evidence") if isinstance(payload, Mapping) else None
    )
    source = evidence.get("source_payload") if isinstance(evidence, Mapping) else None
    source = source if isinstance(source, Mapping) else {}
    return {
        "microstructure_trust_score": source.get("microstructure_trust_score"),
        "sweep_risk_score": source.get("sweep_risk_score"),
        "microstructure_action": source.get("microstructure_action"),
        "book_sequence_gap": source.get("book_sequence_gap"),
        "feed_integrity_pass": source.get("feed_integrity_pass"),
        "latency_within_bound": source.get("latency_within_bound"),
        "sequence_gap_free": source.get("sequence_gap_free"),
        "sweep_direction_uncertain": source.get("sweep_direction_uncertain"),
        "microstructure_missing_components": copy.deepcopy(source.get("missing_components")),
    }


def _microstructure_trust_evidence_core_rejection_reasons(
    evidence: Mapping[str, Any],
    *,
    expected_symbol: Any,
    expected_timeframe: Any,
    expected_tensor_id: Any,
    expected_feature_snapshot_id: Any,
    expected_tensor_source_lineage_hash: Any,
    expected_ppo_decision_time: Any,
) -> list[str]:
    reasons: list[str] = []
    if evidence.get("schema_version") != MICROSTRUCTURE_TRUST_EVIDENCE_SCHEMA_VERSION:
        reasons.append("microstructure_trust_evidence_schema_invalid")
    source = evidence.get("source_payload")
    if not isinstance(source, Mapping) or not source:
        source = {}
        reasons.append("microstructure_trust_source_payload_missing")
    source_hash = evidence.get("source_payload_sha256")
    try:
        computed_source_hash = canonical_sha256(source) if source else None
    except (TypeError, ValueError):
        computed_source_hash = None
    if not _is_sha256(source_hash) or source_hash != computed_source_hash:
        reasons.append("microstructure_trust_source_payload_hash_mismatch")
    if (
        evidence.get("source_readback_verified") is not True
        or evidence.get("source_payload_loaded_sha256") != source_hash
    ):
        reasons.append("microstructure_trust_source_readback_not_verified")
    ttl = _finite(evidence.get("source_observed_ttl_seconds"))
    if ttl is None or ttl <= 0.0 or not float(ttl).is_integer():
        reasons.append("microstructure_trust_source_ttl_not_positive")

    symbol = str(expected_symbol or "").upper()
    timeframe = str(expected_timeframe or "")
    canonical_key = f"v2:microstructure:trust_score:{symbol}:{timeframe}"
    if evidence.get("source_key") != canonical_key:
        reasons.append("microstructure_trust_source_key_invalid")
    if evidence.get("symbol") != symbol or str(source.get("symbol") or "").upper() != symbol:
        reasons.append("microstructure_trust_symbol_identity_mismatch")
    if evidence.get("timeframe") != timeframe or str(source.get("timeframe") or "") != timeframe:
        reasons.append("microstructure_trust_timeframe_identity_mismatch")
    if (
        evidence.get("source_schema_version") != MICROSTRUCTURE_TRUST_SOURCE_SCHEMA_VERSION
        or source.get("schema_version") != MICROSTRUCTURE_TRUST_SOURCE_SCHEMA_VERSION
    ):
        reasons.append("microstructure_trust_source_schema_invalid")
    for field, expected in (
        ("feature_tensor_id", expected_tensor_id),
        ("feature_snapshot_id", expected_feature_snapshot_id),
        ("tensor_source_lineage_hash", expected_tensor_source_lineage_hash),
    ):
        if not isinstance(expected, str) or not expected or evidence.get(field) != expected:
            reasons.append(f"microstructure_trust_{field}_identity_mismatch")
    if not _is_sha256(evidence.get("tensor_source_lineage_hash")):
        reasons.append("microstructure_trust_tensor_source_lineage_hash_invalid")
    temporal_reasons = evidence.get("tensor_temporal_rejection_reasons")
    if not isinstance(temporal_reasons, list) or temporal_reasons:
        reasons.append("microstructure_trust_tensor_temporal_rejection_present")

    tensor_decision = _strict_utc(evidence.get("tensor_decision_time"))
    available_at = _strict_utc(source.get("available_at"))
    source_decision = _strict_utc(source.get("decision_time"))
    generated_at = _strict_utc(source.get("generated_at"))
    if any(
        clock is None for clock in (tensor_decision, available_at, source_decision, generated_at)
    ):
        reasons.append("microstructure_trust_source_clock_invalid")
    else:
        assert tensor_decision is not None
        assert available_at is not None
        assert source_decision is not None
        assert generated_at is not None
        if not (
            available_at <= source_decision <= tensor_decision and generated_at <= tensor_decision
        ):
            reasons.append("microstructure_trust_source_clock_order_invalid")
        if expected_ppo_decision_time not in (None, ""):
            ppo_decision = _strict_utc(expected_ppo_decision_time)
            if ppo_decision is None or any(
                clock > ppo_decision
                for clock in (
                    available_at,
                    source_decision,
                    generated_at,
                    tensor_decision,
                )
            ):
                reasons.append("microstructure_trust_source_after_ppo_decision_time")

    trust = _finite(source.get("microstructure_trust_score"))
    composite = _finite(source.get("composite_microstructure_trust_score"))
    sweep = _finite(source.get("sweep_risk_score"))
    sweep_alias = _finite(source.get("sweep_risk"))
    if (
        trust is None
        or composite is None
        or not 0.0 <= trust <= 1.0
        or not _numbers_close(trust, composite)
    ):
        reasons.append("microstructure_trust_score_binding_invalid")
    if (
        sweep is None
        or sweep_alias is None
        or not 0.0 <= sweep <= 1.0
        or not _numbers_close(sweep, sweep_alias)
    ):
        reasons.append("microstructure_trust_sweep_binding_invalid")
    if str(source.get("microstructure_action") or "").upper() not in {
        "ALLOW",
        "REDUCE_SIZE",
        "NO_TRADE",
        "SHADOW_ONLY",
    }:
        reasons.append("microstructure_trust_action_invalid")
    for field in (
        "book_sequence_gap",
        "feed_integrity_pass",
        "latency_within_bound",
        "sequence_gap_free",
        "sweep_direction_uncertain",
    ):
        if not isinstance(source.get(field), bool):
            reasons.append(f"microstructure_trust_{field}_missing")
    sequence_gap_flag = _finite(source.get("sequence_gap_flag"))
    book_sequence_gap = source.get("book_sequence_gap")
    sequence_gap_free = source.get("sequence_gap_free")
    if (
        isinstance(book_sequence_gap, bool)
        and isinstance(sequence_gap_free, bool)
        and (
            book_sequence_gap is sequence_gap_free
            or sequence_gap_flag != float(int(book_sequence_gap))
        )
    ):
        reasons.append("microstructure_trust_sequence_binding_invalid")
    if not isinstance(source.get("missing_components"), list):
        reasons.append("microstructure_trust_missing_components_invalid")
    return sorted(set(reasons))


class OrdinaryPaperAdmissionIntegrityError(ValueError):
    """An admission result was not issued by this module or lost its binding."""


@dataclass(frozen=True, slots=True)
class OrdinaryPaperAdmissionResult:
    """Factory-issued immutable admission result shared by PAPER consumers.

    Evidence is retained as strict canonical JSON and exposed only as a fresh
    parse.  Consequently a caller cannot mutate the authenticated result by
    retaining or changing a source dictionary.  Direct construction and
    ``dataclasses.replace`` fail because neither has the private factory token.
    """

    claimed: bool
    accepted: bool
    rejection_reasons: tuple[str, ...]
    publisher_sizing_weight: float | None
    effective_sizing_weight: float | None
    evidence_sha256: str | None
    _evidence_json: str | None = dataclass_field(repr=False, compare=False)
    _factory_binding: object = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )
    _factory_token: InitVar[object | None] = None

    def __post_init__(self, _factory_token: object | None) -> None:
        if _factory_token is not _RESULT_FACTORY_TOKEN:
            raise OrdinaryPaperAdmissionIntegrityError(
                "ORDINARY_PAPER_ADMISSION_RESULT_FACTORY_REQUIRED"
            )
        object.__setattr__(self, "_factory_binding", _RESULT_FACTORY_TOKEN)
        reasons = ordinary_paper_admission_result_rejection_reasons(self)
        if reasons:
            raise OrdinaryPaperAdmissionIntegrityError(";".join(reasons))

    @property
    def evidence(self) -> dict[str, Any] | None:
        """Return a fresh exact parse of the hash-bound canonical evidence."""

        if self._evidence_json is None:
            return None
        try:
            parsed = json.loads(self._evidence_json)
        except (TypeError, ValueError, RecursionError) as exc:  # pragma: no cover
            raise OrdinaryPaperAdmissionIntegrityError(
                "ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_JSON_INVALID"
            ) from exc
        if not isinstance(parsed, dict):  # pragma: no cover - factory invariant
            raise OrdinaryPaperAdmissionIntegrityError(
                "ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_NOT_OBJECT"
            )
        return parsed

    def transport_payload(self) -> dict[str, Any]:
        """Return the hash-bound fields that must travel with the candidate."""

        integrity_reasons = ordinary_paper_admission_result_rejection_reasons(self)
        if integrity_reasons:
            raise OrdinaryPaperAdmissionIntegrityError(";".join(integrity_reasons))
        evidence = self.evidence
        payload: dict[str, Any] = {
            "ordinary_scale_free_paper_admission_revalidated": self.accepted,
            "ordinary_scale_free_paper_admission_rejection_reasons": list(self.rejection_reasons),
            "publisher_paper_quality_sizing_weight": self.publisher_sizing_weight,
            "ordinary_paper_effective_sizing_weight": self.effective_sizing_weight,
            "ordinary_paper_effective_sizing_formula": (ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA),
            "ordinary_paper_admission_evidence": evidence,
            "ordinary_paper_admission_evidence_sha256": self.evidence_sha256,
        }
        if evidence is not None:
            for field in (
                "ordinary_paper_admission_schema_version",
                "ordinary_paper_quality_schema_version",
                "ordinary_paper_admission_mode",
                "paper_quality_sizing_formula",
                "paper_quality_sizing_weight",
            ):
                payload[field] = copy.deepcopy(evidence.get(field))
            payload["ordinary_paper_effective_sizing_factors"] = {
                "market_state_integrity_factor": evidence.get(
                    "orchestrator_market_state_integrity_factor"
                ),
                "microstructure_trust_factor": evidence.get(
                    "orchestrator_microstructure_trust_factor"
                ),
                "sweep_survival_factor": evidence.get("orchestrator_sweep_survival_factor"),
            }
            payload["ordinary_paper_raw_microstructure_action"] = evidence.get(
                "orchestrator_microstructure_action"
            )
            payload["ordinary_paper_effective_microstructure_action"] = evidence.get(
                "ordinary_paper_effective_microstructure_action"
            )
            payload["ordinary_paper_legacy_microstructure_block_reasons"] = list(
                evidence.get("orchestrator_legacy_microstructure_block_reasons") or []
            )
            payload["microstructure_trust_evidence"] = copy.deepcopy(
                evidence.get("microstructure_trust_evidence")
            )
            payload["microstructure_trust_evidence_sha256"] = evidence.get(
                "microstructure_trust_evidence_sha256"
            )
            payload["source_redis_key"] = evidence.get("source_redis_key")
            payload["source_prediction_observed_ttl_seconds"] = evidence.get(
                "source_prediction_observed_ttl_seconds"
            )
        return payload


def _canonical_evidence_json(evidence: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(evidence),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _ordinary_paper_admission_result(
    *,
    claimed: bool,
    accepted: bool,
    rejection_reasons: Sequence[str],
    publisher_sizing_weight: float | None,
    effective_sizing_weight: float | None,
    evidence: Mapping[str, Any] | None,
    evidence_sha256: str | None,
) -> OrdinaryPaperAdmissionResult:
    evidence_json: str | None = None
    if evidence is not None:
        try:
            evidence_json = _canonical_evidence_json(evidence)
        except (TypeError, ValueError, OverflowError, RecursionError):
            evidence_json = None
            evidence_sha256 = None
    return OrdinaryPaperAdmissionResult(
        claimed=claimed,
        accepted=accepted,
        rejection_reasons=tuple(rejection_reasons),
        publisher_sizing_weight=publisher_sizing_weight,
        effective_sizing_weight=effective_sizing_weight,
        evidence_sha256=evidence_sha256,
        _evidence_json=evidence_json,
        _factory_token=_RESULT_FACTORY_TOKEN,
    )


def ordinary_paper_admission_result_rejection_reasons(
    result: Any,
    *,
    require_accepted: bool = False,
) -> list[str]:
    """Validate exact type, factory identity, canonical content, and hash.

    The check is deliberately public so every in-process PAPER boundary can
    reject fabricated dataclasses, subclasses, replaced instances, or any
    result whose frozen fields were altered through low-level reflection.
    """

    if type(result) is not OrdinaryPaperAdmissionResult:
        return ["ORDINARY_PAPER_ADMISSION_RESULT_EXACT_TYPE_REQUIRED"]
    reasons: list[str] = []
    if getattr(result, "_factory_binding", None) is not _RESULT_FACTORY_TOKEN:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_FACTORY_BINDING_INVALID")
    if type(result.claimed) is not bool or type(result.accepted) is not bool:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_BOOLEAN_FIELDS_INVALID")
    rejection_reasons = result.rejection_reasons
    if (
        type(rejection_reasons) is not tuple
        or any(type(reason) is not str or not reason for reason in rejection_reasons)
        or tuple(sorted(set(rejection_reasons))) != rejection_reasons
    ):
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_REASONS_INVALID")
    if result.accepted is not (result.claimed and not rejection_reasons):
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_DECISION_BINDING_INVALID")
    if require_accepted and result.accepted is not True:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_NOT_ACCEPTED")

    evidence: dict[str, Any] | None = None
    if result._evidence_json is not None:
        try:
            evidence = json.loads(result._evidence_json)
        except (TypeError, ValueError, RecursionError):
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_JSON_INVALID")
        if not isinstance(evidence, dict):
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_NOT_OBJECT")
            evidence = None
        elif _canonical_evidence_json(evidence) != result._evidence_json:
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_NOT_CANONICAL")

    if result.claimed is False:
        if any(
            value is not None
            for value in (
                result.publisher_sizing_weight,
                result.effective_sizing_weight,
                result.evidence_sha256,
                result._evidence_json,
            )
        ):
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_UNCLAIMED_CONTENT_INVALID")
        return sorted(set(reasons))

    if evidence is None:
        if result.accepted:
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_ACCEPTED_EVIDENCE_MISSING")
        if result.evidence_sha256 is not None:
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_HASH_ORPHANED")
    else:
        try:
            computed_hash = canonical_sha256(evidence)
        except (TypeError, ValueError, OverflowError, RecursionError):
            computed_hash = None
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_NOT_HASHABLE")
        if computed_hash != result.evidence_sha256:
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EVIDENCE_HASH_MISMATCH")

    publisher_weight = _finite(result.publisher_sizing_weight)
    effective_weight = _finite(result.effective_sizing_weight)
    if result.publisher_sizing_weight is not None and publisher_weight is None:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_PUBLISHER_WEIGHT_INVALID")
    if result.effective_sizing_weight is not None and effective_weight is None:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EFFECTIVE_WEIGHT_INVALID")
    if result.accepted:
        if publisher_weight is None or not 0.0 < publisher_weight <= 1.0:
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_PUBLISHER_WEIGHT_UNBOUND")
        if (
            effective_weight is None
            or publisher_weight is None
            or not 0.0 < effective_weight <= publisher_weight
        ):
            reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EFFECTIVE_WEIGHT_UNBOUND")
        if evidence is not None:
            if not _numbers_close(evidence.get("paper_quality_sizing_weight"), publisher_weight):
                reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_PUBLISHER_EVIDENCE_MISMATCH")
            if not _numbers_close(
                evidence.get("ordinary_paper_effective_sizing_weight"),
                effective_weight,
            ):
                reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EFFECTIVE_EVIDENCE_MISMATCH")
            if (
                evidence.get("ordinary_paper_effective_sizing_formula")
                != ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA
            ):
                reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_EFFECTIVE_FORMULA_INVALID")
    elif result.effective_sizing_weight is not None:
        reasons.append("ORDINARY_PAPER_ADMISSION_RESULT_REJECTED_EFFECTIVE_WEIGHT_PRESENT")
    return sorted(set(reasons))


def claims_ordinary_paper_admission(payload: Mapping[str, Any] | Any) -> bool:
    """Return whether a payload claims the ordinary (non-exploration) lane."""

    if not isinstance(payload, Mapping):
        return False
    if payload.get("ordinary_scale_free_paper_admission_revalidated") is True:
        return True
    if payload.get("ordinary_paper_fill_allowed") is True:
        return True
    # A partially stripped ordinary claim must fail closed instead of silently
    # falling back to legacy admission.  Sampled exploration remains outside
    # this contract unless it explicitly claims the ordinary lane above.
    return bool(
        payload.get("paper_fill_allowed") is True
        and payload.get("adaptive_paper_exploration_fill_allowed") is not True
        and (
            payload.get("ordinary_paper_admission_schema_version") not in (None, "")
            or payload.get("ordinary_paper_admission_mode") not in (None, "")
            or payload.get("paper_quality_sizing_weight") not in (None, "")
        )
    )


def copy_ordinary_paper_provenance(
    payload: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Copy ordinary-PAPER provenance without changing its meaning."""

    if not isinstance(payload, Mapping) or not claims_ordinary_paper_admission(payload):
        return {}
    return {
        field: copy.deepcopy(payload.get(field))
        for field in ORDINARY_PAPER_PROVENANCE_FIELDS
        if field in payload
    }


def assess_ordinary_paper_candidate(
    payload: Mapping[str, Any],
    *,
    market_state_integrity_score: Any,
    market_state_reject_reasons: Sequence[Any] = (),
    market_state_quality_reasons: Sequence[Any] = (),
    microstructure_trust_score: Any,
    sweep_risk_score: Any,
    microstructure_action: Any,
    book_sequence_gap: Any,
    feed_integrity_pass: Any,
    latency_within_bound: Any,
    sequence_gap_free: Any,
    sweep_direction_uncertain: Any,
    microstructure_missing_components: Any,
    legacy_microstructure_block_reasons: Sequence[Any] = (),
    replay_snapshot: Mapping[str, Any] | None = None,
    replay_snapshot_observed_ttl_seconds: Any = None,
) -> OrdinaryPaperAdmissionResult:
    """Build and validate the canonical transport evidence for one candidate.

    Market magnitudes are continuous sizing factors.  They have structural
    bounds but no performance threshold: every finite positive factor remains
    admissible and can only reduce the publisher's sizing weight.
    """

    if not claims_ordinary_paper_admission(payload):
        return _ordinary_paper_admission_result(
            claimed=False,
            accepted=False,
            rejection_reasons=(),
            publisher_sizing_weight=None,
            effective_sizing_weight=None,
            evidence=None,
            evidence_sha256=None,
        )
    evidence = {
        "schema_version": ORDINARY_PAPER_EVIDENCE_SCHEMA_VERSION,
        **{field: copy.deepcopy(payload.get(field)) for field in _SOURCE_EVIDENCE_FIELDS},
        "orchestrator_market_state_integrity_score": market_state_integrity_score,
        "orchestrator_market_state_reject_reasons": [
            str(reason) for reason in market_state_reject_reasons if reason
        ],
        "orchestrator_market_state_continuous_quality_reasons": [
            str(reason) for reason in market_state_quality_reasons if reason
        ],
        "orchestrator_microstructure_trust_score": microstructure_trust_score,
        "orchestrator_sweep_risk_score": sweep_risk_score,
        "orchestrator_microstructure_action": microstructure_action,
        "orchestrator_book_sequence_gap": book_sequence_gap,
        "orchestrator_feed_integrity_pass": feed_integrity_pass,
        "orchestrator_latency_within_bound": latency_within_bound,
        "orchestrator_sequence_gap_free": sequence_gap_free,
        "orchestrator_sweep_direction_uncertain": sweep_direction_uncertain,
        "orchestrator_microstructure_missing_components": copy.deepcopy(
            microstructure_missing_components
        ),
        "orchestrator_legacy_microstructure_block_reasons": [
            str(reason) for reason in legacy_microstructure_block_reasons if reason
        ],
        "orchestrator_replay_snapshot_observed_ttl_seconds": (replay_snapshot_observed_ttl_seconds),
    }
    return _assess_evidence(
        evidence,
        replay_snapshot=replay_snapshot,
        replay_snapshot_observed_ttl_seconds=(replay_snapshot_observed_ttl_seconds),
    )


def revalidate_ordinary_paper_transport(
    payload: Mapping[str, Any],
    *,
    replay_snapshot: Mapping[str, Any] | None = None,
    replay_snapshot_observed_ttl_seconds: Any = None,
    source_prediction: Mapping[str, Any] | None = None,
    source_prediction_observed_ttl_seconds: Any = None,
    expected_identity: Mapping[str, Any] | None = None,
) -> OrdinaryPaperAdmissionResult:
    """Revalidate a transported evidence packet and every direct binding."""

    if not claims_ordinary_paper_admission(payload):
        return _ordinary_paper_admission_result(
            claimed=False,
            accepted=False,
            rejection_reasons=(),
            publisher_sizing_weight=None,
            effective_sizing_weight=None,
            evidence=None,
            evidence_sha256=None,
        )
    reasons: list[str] = []
    evidence = payload.get("ordinary_paper_admission_evidence")
    if not isinstance(evidence, Mapping):
        return _ordinary_paper_admission_result(
            claimed=True,
            accepted=False,
            rejection_reasons=("ordinary_paper_evidence_missing",),
            publisher_sizing_weight=None,
            effective_sizing_weight=None,
            evidence=None,
            evidence_sha256=None,
        )
    evidence = copy.deepcopy(dict(evidence))
    try:
        evidence_sha256 = canonical_sha256(evidence)
    except (TypeError, ValueError):
        evidence_sha256 = None
        reasons.append("ordinary_paper_evidence_not_canonically_hashable")
    if evidence_sha256 != payload.get("ordinary_paper_admission_evidence_sha256"):
        reasons.append("ordinary_paper_evidence_hash_mismatch")

    if source_prediction is not None or source_prediction_observed_ttl_seconds is not None:
        prior_source_ttl = _finite(evidence.get("source_prediction_observed_ttl_seconds"))
        current_source_ttl = _finite(source_prediction_observed_ttl_seconds)
        if (
            current_source_ttl is None
            or current_source_ttl <= 0.0
            or not current_source_ttl.is_integer()
            or prior_source_ttl is None
            or current_source_ttl > prior_source_ttl
        ):
            reasons.append("ordinary_paper_current_prediction_ttl_invalid")
        if not isinstance(source_prediction, Mapping):
            reasons.append("ordinary_paper_source_prediction_readback_missing")
        else:
            for field in _SOURCE_EVIDENCE_FIELDS:
                if field in {
                    "source_redis_key",
                    "source_prediction_observed_ttl_seconds",
                }:
                    continue
                if source_prediction.get(field) != evidence.get(field):
                    reasons.append(f"ordinary_paper_source_prediction_readback_{field}_mismatch")
                    break

    assessed = _assess_evidence(
        evidence,
        replay_snapshot=replay_snapshot,
        replay_snapshot_observed_ttl_seconds=(replay_snapshot_observed_ttl_seconds),
    )
    reasons.extend(assessed.rejection_reasons)
    for field in (
        "ordinary_paper_admission_schema_version",
        "ordinary_paper_quality_schema_version",
        "ordinary_paper_admission_mode",
        "paper_quality_sizing_formula",
        "paper_quality_sizing_weight",
    ):
        if payload.get(field) != evidence.get(field):
            reasons.append(f"ordinary_paper_transport_{field}_mismatch")
    if payload.get("ordinary_scale_free_paper_admission_revalidated") is not True:
        reasons.append("ordinary_paper_transport_not_upstream_revalidated")
    if payload.get("ordinary_scale_free_paper_admission_rejection_reasons"):
        reasons.append("ordinary_paper_transport_upstream_rejection_present")
    if not _numbers_close(
        payload.get("publisher_paper_quality_sizing_weight"),
        assessed.publisher_sizing_weight,
    ):
        reasons.append("ordinary_paper_transport_publisher_weight_mismatch")
    if not _numbers_close(
        payload.get("ordinary_paper_effective_sizing_weight"),
        assessed.effective_sizing_weight,
    ):
        reasons.append("ordinary_paper_transport_effective_weight_mismatch")
    if (
        payload.get("ordinary_paper_effective_sizing_formula")
        != ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA
    ):
        reasons.append("ordinary_paper_transport_effective_formula_invalid")
    if payload.get("ordinary_paper_raw_microstructure_action") != evidence.get(
        "orchestrator_microstructure_action"
    ):
        reasons.append("ordinary_paper_transport_raw_microstructure_action_mismatch")
    if payload.get("ordinary_paper_effective_microstructure_action") != evidence.get(
        "ordinary_paper_effective_microstructure_action"
    ):
        reasons.append("ordinary_paper_transport_effective_microstructure_action_mismatch")
    if expected_identity is not None:
        for field in _IDENTITY_FIELDS:
            expected = expected_identity.get(field)
            if field == "prediction_id" and expected in (None, ""):
                expected = expected_identity.get("winner_proposal_id")
            if field == "selected_action" and expected in (None, ""):
                expected = expected_identity.get("side")
            if expected not in (None, "") and str(evidence.get(field) or "") != str(expected):
                reasons.append(f"ordinary_paper_transport_{field}_identity_mismatch")
    reasons = sorted(set(reasons))
    return _ordinary_paper_admission_result(
        claimed=True,
        accepted=not reasons,
        rejection_reasons=tuple(reasons),
        publisher_sizing_weight=assessed.publisher_sizing_weight,
        effective_sizing_weight=(assessed.effective_sizing_weight if not reasons else None),
        evidence=evidence,
        evidence_sha256=evidence_sha256,
    )


def _assess_evidence(
    evidence: Mapping[str, Any],
    *,
    replay_snapshot: Mapping[str, Any] | None,
    replay_snapshot_observed_ttl_seconds: Any,
) -> OrdinaryPaperAdmissionResult:
    evidence = copy.deepcopy(dict(evidence))
    assert isinstance(evidence, dict)
    reasons: list[str] = []
    if evidence.get("schema_version") != ORDINARY_PAPER_EVIDENCE_SCHEMA_VERSION:
        reasons.append("ordinary_paper_evidence_schema_invalid")
    if (
        evidence.get("ordinary_paper_admission_schema_version")
        != ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION
        or evidence.get("ordinary_paper_quality_schema_version")
        != ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION
    ):
        reasons.append("ordinary_paper_publisher_schema_invalid")
    if evidence.get("ordinary_paper_admission_mode") != ORDINARY_PAPER_ADMISSION_MODE:
        reasons.append("ordinary_paper_admission_mode_invalid")
    if evidence.get("paper_quality_sizing_formula") != ORDINARY_PAPER_QUALITY_FORMULA:
        reasons.append("ordinary_paper_quality_formula_invalid")
    if evidence.get("ordinary_paper_fill_allowed") is not True:
        reasons.append("ordinary_paper_fill_not_explicitly_allowed")
    if evidence.get("ordinary_paper_admission_rejection_reasons"):
        reasons.append("ordinary_paper_publisher_admission_rejection_present")
    if evidence.get("ordinary_paper_gate_block_reasons"):
        reasons.append("ordinary_paper_publisher_gate_rejection_present")
    if evidence.get("on_policy_sampling_selected") is not False:
        reasons.append("ordinary_paper_lane_not_explicitly_non_sampled")

    for field in _IDENTITY_FIELDS:
        value = evidence.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"ordinary_paper_{field}_missing")
    for field in (
        "feature_vector_hash",
        "input_feature_hash",
        "candidate_policy_fingerprint",
    ):
        if not _is_sha256(evidence.get(field)):
            reasons.append(f"ordinary_paper_{field}_invalid")
    source_hashes = evidence.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        reasons.append("ordinary_paper_source_hashes_missing")
        source_hashes = {}
    microstructure_evidence = evidence.get("microstructure_trust_evidence")
    microstructure_reasons = microstructure_trust_evidence_rejection_reasons(
        microstructure_evidence,
        expected_symbol=evidence.get("symbol"),
        expected_timeframe=evidence.get("timeframe"),
        expected_tensor_id=source_hashes.get("feature_tensor_id"),
        expected_feature_snapshot_id=evidence.get("feature_snapshot_id"),
        expected_tensor_source_lineage_hash=source_hashes.get("tensor_source_lineage_hash"),
        expected_ppo_decision_time=evidence.get("ppo_decision_time"),
    )
    reasons.extend(f"ordinary_paper_{reason}" for reason in microstructure_reasons)
    inner_microstructure_hash = (
        microstructure_evidence.get("evidence_sha256")
        if isinstance(microstructure_evidence, Mapping)
        else None
    )
    if (
        evidence.get("microstructure_trust_evidence_sha256") != inner_microstructure_hash
        or source_hashes.get("microstructure_trust_evidence_sha256") != inner_microstructure_hash
    ):
        reasons.append("ordinary_paper_microstructure_evidence_hash_not_bound")
    source_payload_hash = (
        microstructure_evidence.get("source_payload_sha256")
        if isinstance(microstructure_evidence, Mapping)
        else None
    )
    if source_hashes.get("microstructure_trust_source_payload_sha256") != source_payload_hash:
        reasons.append("ordinary_paper_microstructure_source_hash_not_bound")

    for field in (
        "trust_row_accepted_for_training",
        "trust_row_valid_for_training",
        "trust_row_trainer_consumable",
        "candle_closed_confirmed",
        "mtf_snapshot_valid",
        "replay_snapshot_ready",
        "replay_snapshot_write_success",
        "replay_snapshot_write_acknowledged",
        "replay_snapshot_readback_verified",
        "paper_fill_allowed",
        "routes_to_orchestrator",
        "prediction_eligible",
        "risk_eligible",
        "paper_eligible",
        "exact_cost_provenance_valid",
        "paper_quality_paper_only",
    ):
        if evidence.get(field) is not True:
            reasons.append(f"ordinary_paper_{field}_not_proven")
    for field in (
        "exchange_mutation",
        "trainer_direct_trading",
        "paper_quality_market_static_threshold_used",
        "paper_quality_routes_to_live",
        "paper_quality_places_real_order",
    ):
        if evidence.get(field) is not False:
            reasons.append(f"ordinary_paper_{field}_not_false")
    if evidence.get("live_gate") != _PAPER_ONLY_LIVE_GATE:
        reasons.append("ordinary_paper_live_gate_not_blocked")
    if evidence.get("live_symbols") != []:
        reasons.append("ordinary_paper_live_symbols_not_empty")
    canonical_prediction_key = f"v2:prediction:{evidence.get('symbol')}:{evidence.get('timeframe')}"
    if evidence.get("source_redis_key") != canonical_prediction_key:
        reasons.append("ordinary_paper_prediction_source_redis_key_invalid")
    prediction_ttl = _finite(evidence.get("source_prediction_observed_ttl_seconds"))
    if prediction_ttl is None or prediction_ttl <= 0.0 or not prediction_ttl.is_integer():
        reasons.append("ordinary_paper_prediction_source_ttl_not_positive")
    if str(evidence.get("row_classification") or "").upper() != "TRAINABLE":
        reasons.append("ordinary_paper_row_not_trainable")
    if str(evidence.get("feature_freshness_state") or "").upper() != "CURRENT":
        reasons.append("ordinary_paper_feature_freshness_not_current")
    for field in (
        "training_trust_reject_reasons",
        "missing_feature_names",
        "stale_feature_names",
        "exact_cost_provenance_rejection_reasons",
    ):
        if evidence.get(field):
            reasons.append(f"ordinary_paper_{field}_not_empty")
    if evidence.get("backfilled") is not False or evidence.get("is_backfilled") is not False:
        reasons.append("ordinary_paper_backfilled")
    for field in (
        "missing_feature_count",
        "stale_feature_count",
        "missing_candle_count",
        "duplicate_event_count",
        "out_of_order_event_count",
    ):
        value = _finite(evidence.get(field))
        if value is None or value != 0.0:
            reasons.append(f"ordinary_paper_{field}_not_zero")

    publisher_weight, quality_reasons = _quality_weight(evidence)
    reasons.extend(quality_reasons)
    reasons.extend(_confidence_rejection_reasons(evidence))
    reasons.extend(_temporal_rejection_reasons(evidence))
    reasons.extend(
        f"ordinary_paper_exact_cost:{reason}"
        for reason in exact_cost_provenance_rejection_reasons(
            evidence.get("exact_cost_provenance"),
            expected_symbol=evidence.get("symbol"),
            expected_round_trip_cost_bps=evidence.get("round_trip_cost_bps"),
            expected_decision_time=evidence.get("decision_time"),
        )
    )
    reasons.extend(
        _replay_rejection_reasons(
            evidence,
            replay_snapshot=replay_snapshot,
            replay_snapshot_observed_ttl_seconds=(replay_snapshot_observed_ttl_seconds),
        )
    )

    trust_gate = evidence.get("trust_gate_result")
    if not isinstance(trust_gate, Mapping):
        reasons.append("ordinary_paper_trust_gate_result_missing")
    else:
        trust_accepted = (
            trust_gate.get("accepted") is True
            if "accepted" in trust_gate
            else trust_gate.get("allowed") is True
        )
        if not trust_accepted or trust_gate.get("reject_reasons"):
            reasons.append("ordinary_paper_trust_gate_not_accepted")
    if evidence.get("trust_schema_version") != "pipeline_trust_v3":
        reasons.append("ordinary_paper_trust_schema_invalid")

    market_score = _finite(evidence.get("orchestrator_market_state_integrity_score"))
    market_reasons = evidence.get("orchestrator_market_state_reject_reasons")
    trust_score = _finite(evidence.get("orchestrator_microstructure_trust_score"))
    sweep_risk = _finite(evidence.get("orchestrator_sweep_risk_score"))
    source_microstructure = microstructure_admission_values(
        {"microstructure_trust_evidence": microstructure_evidence}
    )
    for field in (
        "microstructure_trust_score",
        "sweep_risk_score",
    ):
        if not _numbers_close(
            evidence.get(f"orchestrator_{field}"), source_microstructure.get(field)
        ):
            reasons.append(f"ordinary_paper_orchestrator_{field}_source_mismatch")
    for field in (
        "microstructure_action",
        "book_sequence_gap",
        "feed_integrity_pass",
        "latency_within_bound",
        "sequence_gap_free",
        "sweep_direction_uncertain",
        "microstructure_missing_components",
    ):
        if evidence.get(f"orchestrator_{field}") != source_microstructure.get(field):
            reasons.append(f"ordinary_paper_orchestrator_{field}_source_mismatch")
    if market_score is None or not 0.0 < market_score <= 100.0:
        reasons.append("ordinary_paper_market_state_integrity_magnitude_invalid")
    if not isinstance(market_reasons, list) or market_reasons:
        reasons.append("ordinary_paper_market_state_structural_rejection_present")
    if trust_score is None or not 0.0 < trust_score <= 1.0:
        reasons.append("ordinary_paper_microstructure_trust_magnitude_invalid")
    if sweep_risk is None or not 0.0 <= sweep_risk < 1.0:
        reasons.append("ordinary_paper_sweep_risk_magnitude_invalid")
    raw_microstructure_action = str(
        evidence.get("orchestrator_microstructure_action") or ""
    ).upper()
    if evidence.get("orchestrator_book_sequence_gap") not in (False, 0, 0.0):
        reasons.append("ordinary_paper_book_sequence_continuity_not_proven")
    for field in (
        "orchestrator_feed_integrity_pass",
        "orchestrator_sequence_gap_free",
    ):
        if evidence.get(field) is not True:
            reasons.append(f"ordinary_paper_{field}_not_proven")
    if not isinstance(evidence.get("orchestrator_latency_within_bound"), bool):
        reasons.append("ordinary_paper_orchestrator_latency_evidence_missing")
    if evidence.get("orchestrator_sweep_direction_uncertain") is not False:
        reasons.append("ordinary_paper_sweep_direction_uncertainty_not_disproven")
    if evidence.get("orchestrator_microstructure_missing_components") != []:
        reasons.append("ordinary_paper_microstructure_components_incomplete")
    if raw_microstructure_action in _ALLOWED_MICROSTRUCTURE_ACTIONS:
        effective_microstructure_action = raw_microstructure_action
    elif raw_microstructure_action in {"NO_TRADE", "SHADOW_ONLY"}:
        # These two actions are the legacy score-band classifications.  Once
        # independent structural evidence above passes, retain the raw action
        # as telemetry and convert its positive magnitude to reduced sizing.
        effective_microstructure_action = "REDUCE_SIZE"
    else:
        effective_microstructure_action = None
        reasons.append("ordinary_paper_microstructure_action_not_routeable")
    evidence["ordinary_paper_effective_microstructure_action"] = effective_microstructure_action

    effective_weight: float | None = None
    if (
        publisher_weight is not None
        and market_score is not None
        and 0.0 < market_score <= 100.0
        and trust_score is not None
        and 0.0 < trust_score <= 1.0
        and sweep_risk is not None
        and 0.0 <= sweep_risk < 1.0
    ):
        market_factor = market_score / 100.0
        sweep_factor = 1.0 - sweep_risk
        effective_weight = publisher_weight * market_factor * trust_score * sweep_factor
        effective_weight = min(publisher_weight, effective_weight)
        evidence["orchestrator_market_state_integrity_factor"] = market_factor
        evidence["orchestrator_microstructure_trust_factor"] = trust_score
        evidence["orchestrator_sweep_survival_factor"] = sweep_factor
        evidence["ordinary_paper_effective_sizing_weight"] = effective_weight
        evidence["ordinary_paper_effective_sizing_formula"] = (
            ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA
        )
        if (
            not math.isfinite(effective_weight)
            or not 0.0 < effective_weight <= publisher_weight <= 1.0
        ):
            reasons.append("ordinary_paper_effective_sizing_weight_invalid")
            effective_weight = None

    try:
        evidence_sha256 = canonical_sha256(evidence)
    except (TypeError, ValueError):
        evidence_sha256 = None
        reasons.append("ordinary_paper_evidence_not_canonically_hashable")
    reasons = sorted(set(reasons))
    return _ordinary_paper_admission_result(
        claimed=True,
        accepted=not reasons,
        rejection_reasons=tuple(reasons),
        publisher_sizing_weight=publisher_weight,
        effective_sizing_weight=effective_weight if not reasons else None,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
    )


def _quality_weight(evidence: Mapping[str, Any]) -> tuple[float | None, list[str]]:
    reasons: list[str] = []
    coverage = _finite(evidence.get("data_coverage_percent"))
    probability = _finite(evidence.get("confidence_calibrated"))
    edge = _finite(evidence.get("expected_move_after_cost_bps"))
    cost = _finite(evidence.get("round_trip_cost_bps"))
    action = str(evidence.get("selected_action") or "").lower()
    if coverage is None or not 0.0 < coverage <= 100.0:
        reasons.append("ordinary_paper_coverage_magnitude_invalid")
    if probability is None or not 0.0 < probability <= 1.0:
        reasons.append("ordinary_paper_probability_magnitude_invalid")
    if edge is None or edge == 0.0:
        reasons.append("ordinary_paper_after_cost_edge_magnitude_invalid")
    elif action not in {"long", "short"} or (
        (action == "long" and edge < 0.0) or (action == "short" and edge > 0.0)
    ):
        reasons.append("ordinary_paper_after_cost_edge_direction_invalid")
    if cost is None or cost <= 0.0:
        reasons.append("ordinary_paper_round_trip_cost_magnitude_invalid")
    if reasons:
        return None, reasons
    assert coverage is not None and probability is not None
    assert edge is not None and cost is not None
    relative_edge = abs(edge) / (abs(edge) + cost)
    recomputed = (coverage / 100.0) * probability * relative_edge
    stored = _finite(evidence.get("paper_quality_sizing_weight"))
    if stored is None or not _numbers_close(stored, recomputed):
        reasons.append("ordinary_paper_quality_weight_binding_invalid")
    for field, expected in (
        ("paper_quality_coverage_component", coverage / 100.0),
        ("paper_quality_calibrated_probability_component", probability),
        ("paper_quality_relative_after_cost_edge_component", relative_edge),
    ):
        if not _numbers_close(evidence.get(field), expected):
            reasons.append(f"ordinary_paper_{field}_binding_invalid")
    if not (
        evidence.get("paper_quality_zero_boundary_semantics")
        == "EXACT_ZERO_IS_STRUCTURAL_NO_INFORMATION_AND_BLOCKS;"
        "EVERY_FINITE_POSITIVE_VALUE_IS_CONTINUOUSLY_WEIGHTED"
    ):
        reasons.append("ordinary_paper_zero_boundary_semantics_invalid")
    return (recomputed if not reasons else None), reasons


def _confidence_rejection_reasons(evidence: Mapping[str, Any]) -> list[str]:
    calibration = evidence.get("confidence_calibration")
    action = str(evidence.get("selected_action") or "").lower()
    if not isinstance(calibration, Mapping):
        return ["ordinary_paper_confidence_calibration_missing"]
    if not (
        evidence.get("confidence_calibration_fitted") is True
        and calibration.get("calibration_fitted") is True
        and calibration.get("probability_semantics_valid") is True
        and calibration.get("label_semantics") == CONFIDENCE_LABEL_SEMANTICS
        and calibration.get("confidence_head_schema_version") == CONFIDENCE_HEAD_SCHEMA_VERSION
        and tuple(calibration.get("confidence_head_actions") or ()) == CONFIDENCE_HEAD_ACTIONS
        and calibration.get("selected_action_is_directional") is True
        and calibration.get("selected_action") == action
        and _is_sha256(calibration.get("model_parameter_fingerprint"))
    ):
        return ["ordinary_paper_confidence_semantics_invalid"]
    return []


def _temporal_rejection_reasons(evidence: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    clocks = {
        field: _strict_utc(evidence.get(field))
        for field in (
            "decision_time",
            "feature_cutoff",
            "available_at",
            "candle_close_time",
            "masa_feature_cutoff",
            "ppo_feature_cutoff",
            "ppo_decision_time",
        )
    }
    clocks["source_event_time"] = _strict_utc(
        evidence.get("source_event_time_est") or evidence.get("source_event_time")
    )
    clocks["source_received_time"] = _strict_utc(
        evidence.get("source_received_time_est") or evidence.get("source_received_time")
    )
    for field, clock in clocks.items():
        if clock is None:
            reasons.append(f"ordinary_paper_{field}_invalid")
    if reasons:
        return reasons
    decision = clocks["decision_time"]
    cutoff = clocks["feature_cutoff"]
    available = clocks["available_at"]
    close = clocks["candle_close_time"]
    event = clocks["source_event_time"]
    received = clocks["source_received_time"]
    masa = clocks["masa_feature_cutoff"]
    ppo_cutoff = clocks["ppo_feature_cutoff"]
    ppo_decision = clocks["ppo_decision_time"]
    assert all(
        value is not None
        for value in (
            decision,
            cutoff,
            available,
            close,
            event,
            received,
            masa,
            ppo_cutoff,
            ppo_decision,
        )
    )
    assert decision is not None and cutoff is not None and available is not None
    assert close is not None and event is not None and received is not None
    assert masa is not None and ppo_cutoff is not None and ppo_decision is not None
    if not (close <= cutoff <= available < decision):
        reasons.append("ordinary_paper_feature_clock_order_invalid")
    if not (event <= received <= available):
        reasons.append("ordinary_paper_source_clock_order_invalid")
    if not (masa <= ppo_decision <= decision and ppo_cutoff <= ppo_decision):
        reasons.append("ordinary_paper_cross_model_clock_order_invalid")
    for field, upper_bound in (
        ("all_tf_candle_timestamps", cutoff),
        ("all_source_event_times", available),
    ):
        values = evidence.get(field)
        if not isinstance(values, list | tuple) or not values:
            reasons.append(f"ordinary_paper_{field}_missing")
            continue
        parsed = [_strict_utc(value) for value in values]
        if any(value is None for value in parsed):
            reasons.append(f"ordinary_paper_{field}_invalid")
        elif any(value > upper_bound for value in parsed if value is not None):
            reasons.append(f"ordinary_paper_{field}_after_causal_bound")
    return reasons


def _replay_rejection_reasons(
    evidence: Mapping[str, Any],
    *,
    replay_snapshot: Mapping[str, Any] | None,
    replay_snapshot_observed_ttl_seconds: Any,
) -> list[str]:
    reasons: list[str] = []
    for field in ("replay_snapshot_id", "replay_snapshot_key"):
        if not isinstance(evidence.get(field), str) or not str(evidence.get(field)).strip():
            reasons.append(f"ordinary_paper_{field}_missing")
    expected_hash = evidence.get("replay_snapshot_content_sha256")
    if not _is_sha256(expected_hash):
        reasons.append("ordinary_paper_replay_snapshot_hash_invalid")
    if not isinstance(replay_snapshot, Mapping):
        reasons.append("ordinary_paper_replay_snapshot_readback_missing")
    else:
        try:
            actual_hash = canonical_sha256(replay_snapshot)
        except (TypeError, ValueError):
            actual_hash = None
        if actual_hash != expected_hash:
            reasons.append("ordinary_paper_replay_snapshot_readback_hash_mismatch")
    ttl_seconds = _finite(evidence.get("replay_snapshot_ttl_seconds"))
    if ttl_seconds is None or ttl_seconds <= 0.0:
        reasons.append("ordinary_paper_replay_snapshot_expiry_not_proven")
    orchestrator_ttl = _finite(evidence.get("orchestrator_replay_snapshot_observed_ttl_seconds"))
    current_ttl = _finite(replay_snapshot_observed_ttl_seconds)
    if (
        orchestrator_ttl is None
        or orchestrator_ttl <= 0.0
        or ttl_seconds is None
        or orchestrator_ttl > ttl_seconds
    ):
        reasons.append("ordinary_paper_orchestrator_replay_ttl_invalid")
    if (
        current_ttl is None
        or current_ttl <= 0.0
        or orchestrator_ttl is None
        or current_ttl > orchestrator_ttl
    ):
        reasons.append("ordinary_paper_current_replay_ttl_invalid")
    return reasons


def _strict_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _numbers_close(left: Any, right: Any) -> bool:
    left_value = _finite(left)
    right_value = _finite(right)
    return bool(
        left_value is not None
        and right_value is not None
        and math.isclose(left_value, right_value, rel_tol=1e-12, abs_tol=1e-15)
    )


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


__all__ = [
    "MICROSTRUCTURE_TRUST_EVIDENCE_SCHEMA_VERSION",
    "MICROSTRUCTURE_TRUST_SOURCE_SCHEMA_VERSION",
    "ORDINARY_PAPER_ADMISSION_MODE",
    "ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION",
    "ORDINARY_PAPER_EFFECTIVE_SIZING_FORMULA",
    "ORDINARY_PAPER_EVIDENCE_SCHEMA_VERSION",
    "ORDINARY_PAPER_PROVENANCE_FIELDS",
    "ORDINARY_PAPER_QUALITY_FORMULA",
    "OrdinaryPaperAdmissionIntegrityError",
    "OrdinaryPaperAdmissionResult",
    "assess_ordinary_paper_candidate",
    "build_microstructure_trust_evidence",
    "claims_ordinary_paper_admission",
    "copy_ordinary_paper_provenance",
    "microstructure_admission_values",
    "microstructure_trust_evidence_rejection_reasons",
    "ordinary_paper_admission_result_rejection_reasons",
    "revalidate_ordinary_paper_transport",
]
