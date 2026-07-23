"""Durable admission of model-bound finalized profitability calibration evidence.

The ledger consumes exact factory-built finalized outcomes, copies their
canonical artifacts into one immutable CAS, assigns chronological purged-train
and untouched forward-validation roles, fits the checkpoint-bound temperature,
and admits it only when paired uncertainty proves non-regression globally and
for both directional heads.

This module authorizes only a later calibration-only checkpoint write.  It does
not authorize optimizer execution, prediction serving, PAPER or live trading,
exchange access, deployment, orders, or runtime wiring.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NoReturn, cast
from urllib.parse import quote

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
    CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
    CONFIDENCE_FIT_PARTITION,
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
    CONFIDENCE_UNCERTAINTY_METHOD,
    LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
    LEGACY_CONFIDENCE_UNCERTAINTY_METHOD,
    brier_score,
    confidence_uncertainty_evidence_digest,
    expected_calibration_error,
    fit_legacy_temperature,
    fit_temperature,
    legacy_brier_score,
    legacy_confidence_uncertainty_evidence_digest,
    legacy_expected_calibration_error,
    legacy_temperature_scaled_probability,
    normalize_calibration_state,
    normalize_legacy_calibration_state,
    paired_confidence_nonregression_evidence,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_research_finalized_outcome_ledger_v1 import (  # noqa: E501
    PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION,
    DurablyMaturedProfiledResearchFinalizedOutcomeV1,
    ProfiledResearchFinalizedOutcomeV1Error,
    validate_profiled_research_finalized_outcome_artifact_v1,
)

PROFILED_RESEARCH_CALIBRATION_ADMISSION_LEDGER_V1_SCHEMA_VERSION: Final = (
    "profiled_research_calibration_admission_ledger_v1"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_SCHEMA_VERSION: Final = (
    "profiled_research_calibration_admission_v1"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_CLASSIFICATION: Final = (
    "MODEL_BOUND_PURGED_FORWARD_VALIDATED_CALIBRATION_ADMISSION_V1"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_SCHEMA_VERSION: Final = (
    "profiled_research_calibration_admission_v2"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_CLASSIFICATION: Final = (
    "MODEL_BOUND_PURGED_FORWARD_VALIDATED_ADAPTIVE_CALIBRATION_ADMISSION_V2"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_APPEND_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_calibration_admission_append_receipt_v1"
)
PROFILED_RESEARCH_CALIBRATION_ADMISSION_HEAD_ANCHOR_V1_SCHEMA_VERSION: Final = (
    "profiled_research_calibration_admission_head_anchor_v1"
)
PROFILED_RESEARCH_CALIBRATION_UNCERTAINTY_METHOD: Final = (
    CONFIDENCE_UNCERTAINTY_METHOD
)
PROFILED_RESEARCH_CALIBRATION_LEGACY_UNCERTAINTY_METHOD: Final = (
    LEGACY_CONFIDENCE_UNCERTAINTY_METHOD
)

_APPLICATION_ID = 0x5043414C
_USER_VERSION = 1
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_ROWS = 65_536
_MAX_LEDGER_RECORDS = 4_096
_MAX_DATABASE_BYTES = 512 * 1024 * 1024
_MAX_SOURCE_ARTIFACT_BYTES_PER_ADMISSION = 512 * 1024 * 1024
_GENESIS_CHAIN_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CALIBRATION_ADMISSION_LEDGER_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_GENESIS_HEAD_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CALIBRATION_ADMISSION_HEAD_ANCHOR_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_PARTITION_METHOD = (
    "LATEST_CHRONOLOGICAL_STRUCTURALLY_IDENTIFIABLE_SUFFIX_WITH_"
    "STRICT_LABEL_AVAILABILITY_PURGE"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_RESULT_TOKEN = object()
_RESULT_SEAL_KEY = secrets.token_bytes(32)
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_AUTHORIZATION: Final = {
    "consumer_eligible": True,
    "calibration_input_authorized": True,
    "calibration_only_checkpoint_write_authorized": True,
    "optimizer_execution_authorized": False,
    "optimizer_checkpoint_write_authorized": False,
    "model_weight_mutation_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "risk_authority": False,
    "allocator_authority": False,
    "runtime_wired": False,
}

_ARTIFACT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "model_binding",
        "source_outcome_inventory",
        "partition",
        "calibration_state",
        "forward_validation",
        "evidence_policy",
        "authorization",
        "status",
        "admission_material_sha256",
    }
)
_MODEL_FIELDS: Final = frozenset(
    {
        "checkpoint_id",
        "checkpoint_generation",
        "model_parameter_fingerprint",
        "model_binding_sha256",
        "confidence_head_schema_version",
        "confidence_head_actions",
        "label_semantics",
    }
)
_SOURCE_ROW_FIELDS: Final = frozenset(
    {
        "row_id",
        "outcome_artifact_sha256",
        "outcome_artifact_byte_count",
        "outcome_material_sha256",
        "hypothesis_artifact_sha256",
        "record_chain_sha256",
        "append_receipt_sha256",
        "postcommit_readback_receipt_sha256",
        "model_binding_sha256",
        "decision_time",
        "actual_label_available_at",
        "maturation_observed_at",
        "outcome_commit_observed_at",
        "outcome_postcommit_observed_at",
        "outcome_postcommit_readback_at",
        "selected_action",
        "raw_probability",
        "observed_strictly_positive_net_pnl",
        "source_role",
    }
)
_PARTITION_FIELDS: Final = frozenset(
    {
        "method",
        "ordered_row_ids",
        "purged_train_row_ids",
        "purged_gap_row_ids",
        "untouched_forward_validation_row_ids",
        "purged_train_row_digest",
        "purged_gap_row_digest",
        "untouched_forward_validation_row_digest",
        "first_forward_validation_decision_time",
        "maximum_train_label_available_at",
        "latest_source_postcommit_readback_at",
        "strict_train_label_before_validation_decision_verified",
        "role_disjointness_verified",
        "complete_inventory_assignment_verified",
    }
)
_EVIDENCE_POLICY_V1: Final = {
    "configured_sample_count_threshold_used": False,
    "static_market_threshold_used": False,
    "validation_outcomes_used_to_select_partition": False,
    "mathematical_fit_requires_both_binary_classes": True,
    "mathematical_fit_requires_both_directional_actions": True,
    "mathematical_uncertainty_requires_two_rows_per_scope": True,
    "purged_train_only_fit": True,
    "untouched_forward_validation_only_evaluation": True,
    "one_standard_error_non_regression_required": True,
    "source_row_role_reuse_allowed": False,
    "weight_mutation_allowed": False,
}
_EVIDENCE_POLICY_V2: Final = {
    **_EVIDENCE_POLICY_V1,
    "one_standard_error_non_regression_required": False,
    "full_sample_non_regression_required": True,
    "every_delete_one_non_regression_required": True,
    "adaptive_calibration_error_estimator": (
        CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
    ),
    "bounded_temperature_search_used": False,
}

_TABLE_NAMES: Final = frozenset(
    {
        "profiled_calibration_metadata",
        "profiled_calibration_admissions",
        "profiled_calibration_source_rows",
        "profiled_calibration_append_receipts",
        "profiled_calibration_head_anchors",
    }
)
_INDEX_NAMES: Final = frozenset(
    {
        "profiled_calibration_source_model_role",
        "profiled_calibration_checkpoint_identity",
    }
)
_TRIGGER_NAMES: Final = frozenset(
    {
        f"{table}_no_{operation}"
        for table in _TABLE_NAMES
        for operation in ("update", "delete")
    }
)
_METADATA: Final = {
    "ledger_schema_version": (
        PROFILED_RESEARCH_CALIBRATION_ADMISSION_LEDGER_V1_SCHEMA_VERSION
    ),
    "retention_policy": "APPEND_ONLY_NO_AUTOMATIC_PRUNING",
    "automatic_pruning_enabled": "false",
    "runtime_wired": "false",
    "weight_mutation_authorized": "false",
}


class ProfiledResearchCalibrationAdmissionV1Error(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProfiledResearchCalibrationAdmissionV1ValidationError(
    ProfiledResearchCalibrationAdmissionV1Error
):
    pass


class ProfiledResearchCalibrationAdmissionV1IntegrityError(
    ProfiledResearchCalibrationAdmissionV1Error
):
    pass


class ProfiledResearchCalibrationAdmissionV1ConflictError(
    ProfiledResearchCalibrationAdmissionV1Error
):
    pass


def _validation(reason: str) -> NoReturn:
    raise ProfiledResearchCalibrationAdmissionV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise ProfiledResearchCalibrationAdmissionV1IntegrityError(reason) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation(reason)
    if not encoded or len(encoded) > _MAX_JSON_BYTES:
        _validation(reason)
    return encoded


def _canonical_json(value: object, *, reason: str) -> str:
    return _canonical_bytes(value, reason=reason).decode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes(value, reason="PROFILED_CALIBRATION_JSON_INVALID")
    ).hexdigest()


def _parse_exact_object(payload: bytes | str, *, reason: str) -> dict[str, Any]:
    raw = payload.encode("ascii", errors="strict") if type(payload) is str else payload
    if type(raw) is not bytes or not raw or len(raw) > _MAX_JSON_BYTES:
        _integrity(reason)

    def reject_constant(_value: str) -> NoReturn:
        _integrity(reason)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _integrity(reason)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii", errors="strict"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        _integrity(reason)
    if type(value) is not dict:
        _integrity(reason)
    result = cast(dict[str, Any], value)
    if _canonical_bytes(result, reason=reason) != raw:
        _integrity(reason)
    return result


def _strict_sha256(value: object) -> str | None:
    return value if type(value) is str and _SHA256_RE.fullmatch(value) else None


def _finite_float(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    parsed = float(cast(int | float, value))
    return parsed if math.isfinite(parsed) else None


def _clock(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _format_microsecond(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _internally_observed_clock() -> str:
    value = _utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        _integrity("PROFILED_CALIBRATION_INTERNAL_CLOCK_INVALID")
    return _format_microsecond(value)


def _next_observed_clock(previous: datetime) -> str:
    now = _utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        _integrity("PROFILED_CALIBRATION_INTERNAL_CLOCK_INVALID")
    candidate = max(now.astimezone(UTC), previous + timedelta(microseconds=1))
    return _format_microsecond(candidate)


def _address_mapping(address: SourcePayloadAddress) -> dict[str, object]:
    if type(address) is not SourcePayloadAddress:
        _integrity("PROFILED_CALIBRATION_CAS_ADDRESS_INVALID")
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _address_from_mapping(value: object) -> SourcePayloadAddress:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }:
        _integrity("PROFILED_CALIBRATION_CAS_ADDRESS_INVALID")
    mapping = cast(dict[str, Any], value)
    digest = _strict_sha256(mapping.get("payload_sha256"))
    count = mapping.get("payload_byte_count")
    if (
        mapping.get("schema_version") != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or digest is None
        or type(count) is not int
        or not 0 < count <= _MAX_JSON_BYTES
        or mapping.get("relative_path") != f"sha256/{digest[:2]}/{digest}"
    ):
        _integrity("PROFILED_CALIBRATION_CAS_ADDRESS_INVALID")
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=count,
        relative_path=cast(str, mapping["relative_path"]),
    )


def _put_exact(store: ImmutableSourcePayloadStore, payload: bytes) -> SourcePayloadAddress:
    try:
        return store.put(
            payload,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_count=len(payload),
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
            "PROFILED_CALIBRATION_CAS_WRITE_FAILED"
        ) from exc


def _get_exact(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
) -> bytes:
    try:
        payload = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
            "PROFILED_CALIBRATION_CAS_READ_FAILED"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != address.payload_sha256:
        _integrity("PROFILED_CALIBRATION_CAS_DIGEST_MISMATCH")
    return payload


@dataclass(frozen=True, slots=True)
class _EvidenceRow:
    row_id: str
    outcome_artifact_sha256: str
    outcome_artifact_byte_count: int
    outcome_material_sha256: str
    hypothesis_artifact_sha256: str
    record_chain_sha256: str
    append_receipt_sha256: str
    postcommit_readback_receipt_sha256: str
    checkpoint_id: str
    checkpoint_generation: int
    model_parameter_fingerprint: str
    model_binding_sha256: str
    decision_time: str
    actual_label_available_at: str
    maturation_observed_at: str
    outcome_commit_observed_at: str
    outcome_postcommit_observed_at: str
    outcome_postcommit_readback_at: str
    selected_action: str
    raw_probability: float
    observed_strictly_positive_net_pnl: bool
    outcome_artifact_bytes: bytes = field(repr=False, compare=False)

    @property
    def decision_clock(self) -> datetime:
        parsed = _clock(self.decision_time)
        if parsed is None:  # pragma: no cover - constructed only after validation.
            _integrity("PROFILED_CALIBRATION_ROW_DECISION_CLOCK_INVALID")
        return parsed

    @property
    def label_clock(self) -> datetime:
        parsed = _clock(self.actual_label_available_at)
        if parsed is None:  # pragma: no cover - constructed only after validation.
            _integrity("PROFILED_CALIBRATION_ROW_LABEL_CLOCK_INVALID")
        return parsed


@dataclass(frozen=True, slots=True)
class _Partition:
    train: tuple[_EvidenceRow, ...]
    purge: tuple[_EvidenceRow, ...]
    validation: tuple[_EvidenceRow, ...]


@dataclass(frozen=True, slots=True)
class ProfiledResearchCalibrationEvaluationV1:
    status: str
    reason: str | None
    total_outcomes: int
    eligible_rows: int
    ineligible_rows: int
    model_parameter_fingerprint: str | None
    purged_train_rows: int
    purged_gap_rows: int
    untouched_forward_validation_rows: int
    calibration_fitted: bool
    uncertainty_non_regression_proven: bool
    admission_ready: bool
    configured_sample_count_threshold_used: bool = False
    static_market_threshold_used: bool = False


def _validated_evidence_row(
    value: object,
) -> _EvidenceRow | None:
    if type(value) is not DurablyMaturedProfiledResearchFinalizedOutcomeV1:
        _validation("PROFILED_CALIBRATION_EXACT_FINALIZED_OUTCOME_REQUIRED")
    outcome = value
    try:
        contract = outcome.outcome_contract
        calibration = contract.get("calibration_row")
        authorization = contract.get("authorization")
    except ProfiledResearchFinalizedOutcomeV1Error as exc:
        raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
            "PROFILED_CALIBRATION_SOURCE_OUTCOME_REVALIDATION_FAILED"
        ) from exc
    if type(calibration) is not dict or type(authorization) is not dict:
        _integrity("PROFILED_CALIBRATION_SOURCE_OUTCOME_CONTRACT_INVALID")
    calibration = cast(dict[str, Any], calibration)
    authorization = cast(dict[str, Any], authorization)
    canonical = _canonical_bytes(
        contract,
        reason="PROFILED_CALIBRATION_SOURCE_OUTCOME_JSON_INVALID",
    )
    if (
        hashlib.sha256(canonical).hexdigest() != outcome.outcome_artifact_sha256
        or len(canonical) != outcome.outcome_artifact_byte_count
    ):
        _integrity("PROFILED_CALIBRATION_SOURCE_OUTCOME_ADDRESS_MISMATCH")
    validate_profiled_research_finalized_outcome_artifact_v1(canonical)
    if (
        type(authorization) is not dict
        or authorization.get("calibration_input_authorized") is not False
    ):
        _integrity("PROFILED_CALIBRATION_SOURCE_PREAUTHORIZED_FORBIDDEN")
    if calibration.get("eligible") is not True:
        return None
    model = contract.get("model_binding")
    probability = _finite_float(calibration.get("raw_probability"))
    observed = calibration.get("observed_strictly_positive_net_pnl")
    clocks = {
        "decision": _clock(outcome.decision_time),
        "label": _clock(outcome.actual_label_available_at),
        "maturation": _clock(outcome.maturation_observed_at),
        "commit": _clock(outcome.commit_observed_at),
        "postcommit": _clock(outcome.postcommit_observed_at),
        "postcommit_readback": _clock(outcome.postcommit_readback_at),
    }
    if (
        type(model) is not dict
        or calibration.get("schema_version")
        != PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION
        or calibration.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS
        or calibration.get("fit_partition")
        != "UNASSIGNED_REQUIRES_PURGED_TRAIN_ONLY_ADMISSION"
        or calibration.get("calibration_input_authorized") is not False
        or calibration.get("selected_action_preserved_ex_ante") is not True
        or calibration.get("hindsight_action_substitution_used") is not False
        or calibration.get("selected_directional_action")
        not in CONFIDENCE_HEAD_ACTIONS
        or probability is None
        or not 0.0 <= probability <= 1.0
        or type(observed) is not bool
        or calibration.get("checkpoint_id") != outcome.checkpoint_id
        or calibration.get("checkpoint_generation") != outcome.checkpoint_generation
        or calibration.get("model_parameter_fingerprint")
        != outcome.model_parameter_fingerprint
        or calibration.get("model_binding_sha256") != outcome.model_binding_sha256
        or model.get("checkpoint_id") != outcome.checkpoint_id
        or model.get("checkpoint_generation") != outcome.checkpoint_generation
        or model.get("model_parameter_fingerprint")
        != outcome.model_parameter_fingerprint
        or contract.get("model_binding_sha256") != outcome.model_binding_sha256
        or any(clock is None for clock in clocks.values())
    ):
        _integrity("PROFILED_CALIBRATION_SOURCE_ROW_INVALID")
    decision = cast(datetime, clocks["decision"])
    label = cast(datetime, clocks["label"])
    maturation = cast(datetime, clocks["maturation"])
    commit = cast(datetime, clocks["commit"])
    postcommit = cast(datetime, clocks["postcommit"])
    postcommit_readback = cast(datetime, clocks["postcommit_readback"])
    if not decision < label <= maturation < commit < postcommit <= postcommit_readback:
        _integrity("PROFILED_CALIBRATION_SOURCE_CLOCK_ORDER_INVALID")
    return _EvidenceRow(
        row_id=cast(str, calibration["row_id"]),
        outcome_artifact_sha256=outcome.outcome_artifact_sha256,
        outcome_artifact_byte_count=outcome.outcome_artifact_byte_count,
        outcome_material_sha256=outcome.outcome_material_sha256,
        hypothesis_artifact_sha256=outcome.hypothesis_artifact_sha256,
        record_chain_sha256=outcome.record_chain_sha256,
        append_receipt_sha256=outcome.append_receipt_sha256,
        postcommit_readback_receipt_sha256=(
            outcome.postcommit_readback_receipt_sha256
        ),
        checkpoint_id=outcome.checkpoint_id,
        checkpoint_generation=outcome.checkpoint_generation,
        model_parameter_fingerprint=outcome.model_parameter_fingerprint,
        model_binding_sha256=outcome.model_binding_sha256,
        decision_time=outcome.decision_time,
        actual_label_available_at=outcome.actual_label_available_at,
        maturation_observed_at=outcome.maturation_observed_at,
        outcome_commit_observed_at=outcome.commit_observed_at,
        outcome_postcommit_observed_at=outcome.postcommit_observed_at,
        outcome_postcommit_readback_at=outcome.postcommit_readback_at,
        selected_action=cast(str, calibration["selected_directional_action"]),
        raw_probability=probability,
        observed_strictly_positive_net_pnl=observed,
        outcome_artifact_bytes=canonical,
    )


def _has_fit_identifiability(rows: Sequence[_EvidenceRow]) -> bool:
    return (
        {row.selected_action for row in rows} == set(CONFIDENCE_HEAD_ACTIONS)
        and {row.observed_strictly_positive_net_pnl for row in rows}
        == {False, True}
    )


def _has_validation_identifiability(rows: Sequence[_EvidenceRow]) -> bool:
    return all(
        sum(row.selected_action == action for row in rows) >= 2
        for action in CONFIDENCE_HEAD_ACTIONS
    )


def _chronological_partition(rows: Sequence[_EvidenceRow]) -> _Partition | None:
    ordered = tuple(sorted(rows, key=lambda row: (row.decision_clock, row.row_id)))
    # Search from the latest possible validation start. Structural action
    # coverage selects the suffix; validation outcomes are never inspected.
    for split in range(len(ordered) - 1, 0, -1):
        validation = ordered[split:]
        if ordered[split - 1].decision_clock == validation[0].decision_clock:
            continue
        if not _has_validation_identifiability(validation):
            continue
        validation_start = validation[0].decision_clock
        prefix = ordered[:split]
        train = tuple(row for row in prefix if row.label_clock < validation_start)
        purge = tuple(row for row in prefix if row.label_clock >= validation_start)
        if _has_fit_identifiability(train):
            return _Partition(train=train, purge=purge, validation=validation)
    return None


def _scope_uncertainty(
    rows: Sequence[_EvidenceRow],
    *,
    logit_scale: float,
    scope: str,
) -> dict[str, Any]:
    probabilities = [row.raw_probability for row in rows]
    outcomes = [int(row.observed_strictly_positive_net_pnl) for row in rows]
    normalized_scope = scope.upper()
    evidence = paired_confidence_nonregression_evidence(
        probabilities,
        outcomes,
        logit_scale=logit_scale,
        scope=normalized_scope,
    )
    evidence.update(
        {
            "scope": normalized_scope,
            "method": PROFILED_RESEARCH_CALIBRATION_UNCERTAINTY_METHOD,
            "calibration_error_estimator": (
                CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
            ),
            "raw_brier": brier_score(probabilities, outcomes),
            "calibrated_brier": brier_score(
                probabilities,
                outcomes,
                logit_scale=logit_scale,
            ),
            "raw_ece": expected_calibration_error(probabilities, outcomes),
            "calibrated_ece": expected_calibration_error(
                probabilities,
                outcomes,
                logit_scale=logit_scale,
            ),
            "non_regression_proven": (
                evidence["paired_brier_non_regression_proven"] is True
                and evidence["ece_non_regression_proven"] is True
            ),
        }
    )
    return evidence


def _legacy_scope_uncertainty(
    rows: Sequence[_EvidenceRow],
    *,
    temperature: float,
    scope: str,
) -> dict[str, Any]:
    """Frozen V1 evidence producer used only by the legacy verifier."""

    probabilities = [row.raw_probability for row in rows]
    outcomes = [int(row.observed_strictly_positive_net_pnl) for row in rows]
    calibrated = [
        legacy_temperature_scaled_probability(value, temperature)
        for value in probabilities
    ]
    paired = [
        (after - outcome) ** 2
        - (legacy_temperature_scaled_probability(before, 1.0) - outcome) ** 2
        for before, after, outcome in zip(
            probabilities,
            calibrated,
            outcomes,
            strict=True,
        )
    ]
    count = len(paired)
    mean = sum(paired) / count if count else None
    standard_error: float | None = None
    if count > 1 and mean is not None:
        variance = sum((value - mean) ** 2 for value in paired) / (count - 1)
        standard_error = math.sqrt(variance / count)
    upper = (
        mean + standard_error
        if mean is not None and standard_error is not None
        else None
    )
    raw_ece = legacy_expected_calibration_error(probabilities, outcomes, 1.0)
    calibrated_ece = legacy_expected_calibration_error(
        probabilities,
        outcomes,
        temperature,
    )
    ece_delta = calibrated_ece - raw_ece
    leave_one_out: list[float] = []
    if count > 1:
        for excluded in range(count):
            leave_one_out_probabilities = [
                value
                for index, value in enumerate(probabilities)
                if index != excluded
            ]
            leave_one_out_outcomes = [
                value
                for index, value in enumerate(outcomes)
                if index != excluded
            ]
            leave_one_out.append(
                legacy_expected_calibration_error(
                    leave_one_out_probabilities,
                    leave_one_out_outcomes,
                    temperature,
                )
                - legacy_expected_calibration_error(
                    leave_one_out_probabilities,
                    leave_one_out_outcomes,
                    1.0,
                )
            )
    ece_standard_error: float | None = None
    if leave_one_out:
        leave_one_out_mean = sum(leave_one_out) / len(leave_one_out)
        ece_standard_error = math.sqrt(
            ((count - 1) / count)
            * sum(
                (value - leave_one_out_mean) ** 2
                for value in leave_one_out
            )
        )
    ece_upper = (
        ece_delta + ece_standard_error
        if ece_standard_error is not None
        else None
    )
    normalized_scope = scope.upper()
    evidence: dict[str, Any] = {
        "paired_brier_delta_per_row": paired,
        "paired_brier_delta_mean": mean,
        "paired_brier_delta_standard_error": standard_error,
        "paired_brier_delta_one_standard_error_upper_bound": upper,
        "paired_brier_uncertainty_available": standard_error is not None,
        "paired_brier_non_regression_proven": (
            upper is not None and upper <= 0.0
        ),
        "ece_delta": ece_delta,
        "ece_leave_one_out_delta": leave_one_out,
        "ece_jackknife_standard_error": ece_standard_error,
        "ece_one_standard_error_upper_bound": ece_upper,
        "ece_uncertainty_available": ece_standard_error is not None,
        "ece_non_regression_proven": (
            ece_upper is not None and ece_upper <= 0.0
        ),
        "uncertainty_row_count": count,
        "uncertainty_minimum_not_configured": True,
        "uncertainty_mathematical_minimum_rows": 2,
    }
    evidence["uncertainty_evidence_digest"] = (
        legacy_confidence_uncertainty_evidence_digest(
            scope=normalized_scope,
            evidence=evidence,
        )
    )
    evidence.update(
        {
            "scope": normalized_scope,
            "method": PROFILED_RESEARCH_CALIBRATION_LEGACY_UNCERTAINTY_METHOD,
            "raw_brier": legacy_brier_score(probabilities, outcomes, 1.0),
            "calibrated_brier": legacy_brier_score(
                probabilities,
                outcomes,
                temperature,
            ),
            "raw_ece": raw_ece,
            "calibrated_ece": calibrated_ece,
            "non_regression_proven": (
                evidence["paired_brier_non_regression_proven"] is True
                and evidence["ece_non_regression_proven"] is True
            ),
        }
    )
    return evidence


def _evaluate_rows(
    rows: Sequence[_EvidenceRow],
) -> tuple[
    ProfiledResearchCalibrationEvaluationV1,
    _Partition | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    if not rows:
        return (
            ProfiledResearchCalibrationEvaluationV1(
                status="WAITING_FOR_DIRECTIONAL_FINALIZED_OUTCOMES",
                reason="NO_DIRECTIONAL_FINALIZED_OUTCOMES",
                total_outcomes=0,
                eligible_rows=0,
                ineligible_rows=0,
                model_parameter_fingerprint=None,
                purged_train_rows=0,
                purged_gap_rows=0,
                untouched_forward_validation_rows=0,
                calibration_fitted=False,
                uncertainty_non_regression_proven=False,
                admission_ready=False,
            ),
            None,
            None,
            None,
        )
    identities = {
        (
            row.checkpoint_id,
            row.checkpoint_generation,
            row.model_parameter_fingerprint,
            row.model_binding_sha256,
        )
        for row in rows
    }
    if len(identities) != 1:
        _validation("PROFILED_CALIBRATION_MIXED_MODEL_IDENTITIES_FORBIDDEN")
    row_ids = [row.row_id for row in rows]
    outcomes = [row.outcome_artifact_sha256 for row in rows]
    if len(set(row_ids)) != len(row_ids) or len(set(outcomes)) != len(outcomes):
        _validation("PROFILED_CALIBRATION_DUPLICATE_SOURCE_ROW_FORBIDDEN")
    partition = _chronological_partition(rows)
    fingerprint = rows[0].model_parameter_fingerprint
    if partition is None:
        return (
            ProfiledResearchCalibrationEvaluationV1(
                status="WAITING_FOR_IDENTIFIABLE_PURGED_FORWARD_EVIDENCE",
                reason="PURGED_TRAIN_OR_FORWARD_VALIDATION_NOT_IDENTIFIABLE",
                total_outcomes=len(rows),
                eligible_rows=len(rows),
                ineligible_rows=0,
                model_parameter_fingerprint=fingerprint,
                purged_train_rows=0,
                purged_gap_rows=0,
                untouched_forward_validation_rows=0,
                calibration_fitted=False,
                uncertainty_non_regression_proven=False,
                admission_ready=False,
            ),
            None,
            None,
            None,
        )
    fitted = fit_temperature(
        [row.raw_probability for row in partition.train],
        [int(row.observed_strictly_positive_net_pnl) for row in partition.train],
        row_ids=[row.row_id for row in partition.train],
        action_labels=[row.selected_action for row in partition.train],
        fit_partition=CONFIDENCE_FIT_PARTITION,
        validation_rows_used=0,
    )
    if fitted.get("fitted") is not True:
        return (
            ProfiledResearchCalibrationEvaluationV1(
                status="WAITING_FOR_FINITE_CALIBRATION_IDENTIFIABILITY",
                reason=str(fitted.get("reason") or "CALIBRATION_FIT_NOT_IDENTIFIABLE"),
                total_outcomes=len(rows),
                eligible_rows=len(rows),
                ineligible_rows=0,
                model_parameter_fingerprint=fingerprint,
                purged_train_rows=len(partition.train),
                purged_gap_rows=len(partition.purge),
                untouched_forward_validation_rows=len(partition.validation),
                calibration_fitted=False,
                uncertainty_non_regression_proven=False,
                admission_ready=False,
            ),
            partition,
            None,
            None,
        )
    fitted = normalize_calibration_state(
        {**fitted, "model_parameter_fingerprint": fingerprint}
    )
    if (
        fitted.get("fitted") is not True
        or fitted.get("model_parameter_fingerprint") != fingerprint
    ):
        _integrity("PROFILED_CALIBRATION_MODEL_BOUND_FIT_INVALID")
    logit_scale = _finite_float(fitted.get("logit_scale"))
    if logit_scale is None or logit_scale < 0.0:
        _integrity("PROFILED_CALIBRATION_LOGIT_SCALE_INVALID")
    validation = {
        "global": _scope_uncertainty(
            partition.validation,
            logit_scale=logit_scale,
            scope="GLOBAL",
        ),
        **{
            action: _scope_uncertainty(
                tuple(
                    row
                    for row in partition.validation
                    if row.selected_action == action
                ),
                logit_scale=logit_scale,
                scope=action,
            )
            for action in CONFIDENCE_HEAD_ACTIONS
        },
    }
    non_regression = all(
        evidence["non_regression_proven"] is True
        for evidence in validation.values()
    )
    return (
        ProfiledResearchCalibrationEvaluationV1(
            status=(
                "READY_FOR_DURABLE_CALIBRATION_ADMISSION"
                if non_regression
                else "HELD_FORWARD_VALIDATION_NON_REGRESSION_NOT_PROVEN"
            ),
            reason=None if non_regression else "FORWARD_VALIDATION_NON_REGRESSION_NOT_PROVEN",
            total_outcomes=len(rows),
            eligible_rows=len(rows),
            ineligible_rows=0,
            model_parameter_fingerprint=fingerprint,
            purged_train_rows=len(partition.train),
            purged_gap_rows=len(partition.purge),
            untouched_forward_validation_rows=len(partition.validation),
            calibration_fitted=True,
            uncertainty_non_regression_proven=non_regression,
            admission_ready=non_regression,
        ),
        partition,
        fitted,
        validation,
    )


def _row_inventory(row: _EvidenceRow, *, source_role: str) -> dict[str, Any]:
    if source_role not in {"purged_train", "purged_gap", "untouched_forward_validation"}:
        _integrity("PROFILED_CALIBRATION_SOURCE_ROLE_INVALID")
    return {
        "row_id": row.row_id,
        "outcome_artifact_sha256": row.outcome_artifact_sha256,
        "outcome_artifact_byte_count": row.outcome_artifact_byte_count,
        "outcome_material_sha256": row.outcome_material_sha256,
        "hypothesis_artifact_sha256": row.hypothesis_artifact_sha256,
        "record_chain_sha256": row.record_chain_sha256,
        "append_receipt_sha256": row.append_receipt_sha256,
        "postcommit_readback_receipt_sha256": (
            row.postcommit_readback_receipt_sha256
        ),
        "model_binding_sha256": row.model_binding_sha256,
        "decision_time": row.decision_time,
        "actual_label_available_at": row.actual_label_available_at,
        "maturation_observed_at": row.maturation_observed_at,
        "outcome_commit_observed_at": row.outcome_commit_observed_at,
        "outcome_postcommit_observed_at": row.outcome_postcommit_observed_at,
        "outcome_postcommit_readback_at": row.outcome_postcommit_readback_at,
        "selected_action": row.selected_action,
        "raw_probability": row.raw_probability,
        "observed_strictly_positive_net_pnl": (
            row.observed_strictly_positive_net_pnl
        ),
        "source_role": source_role,
    }


def _ordered_digest(row_ids: Sequence[str], *, role: str) -> str:
    return _sha256({"role": role, "ordered_row_ids": list(row_ids)})


def _prepare_admission_artifact(
    rows: Sequence[_EvidenceRow],
    *,
    partition: _Partition,
    calibration_state: Mapping[str, Any],
    forward_validation: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    identity = {
        (
            row.checkpoint_id,
            row.checkpoint_generation,
            row.model_parameter_fingerprint,
            row.model_binding_sha256,
        )
        for row in rows
    }
    if len(identity) != 1:
        _integrity("PROFILED_CALIBRATION_PREPARED_MODEL_IDENTITY_INVALID")
    checkpoint_id, generation, fingerprint, binding_sha = next(iter(identity))
    roles: dict[str, str] = {
        **{row.row_id: "purged_train" for row in partition.train},
        **{row.row_id: "purged_gap" for row in partition.purge},
        **{
            row.row_id: "untouched_forward_validation"
            for row in partition.validation
        },
    }
    if len(roles) != len(rows):
        _integrity("PROFILED_CALIBRATION_ROLE_ASSIGNMENT_INVALID")
    ordered = tuple(sorted(rows, key=lambda row: (row.decision_clock, row.row_id)))
    inventory = [_row_inventory(row, source_role=roles[row.row_id]) for row in ordered]
    train_ids = [row.row_id for row in partition.train]
    purge_ids = [row.row_id for row in partition.purge]
    validation_ids = [row.row_id for row in partition.validation]
    first_validation = partition.validation[0].decision_clock
    maximum_train_label = max(row.label_clock for row in partition.train)
    latest_source_readback = max(
        cast(datetime, _clock(row.outcome_postcommit_readback_at)) for row in rows
    )
    partition_contract = {
        "method": _PARTITION_METHOD,
        "ordered_row_ids": [row.row_id for row in ordered],
        "purged_train_row_ids": train_ids,
        "purged_gap_row_ids": purge_ids,
        "untouched_forward_validation_row_ids": validation_ids,
        "purged_train_row_digest": _ordered_digest(
            train_ids, role="purged_train"
        ),
        "purged_gap_row_digest": _ordered_digest(purge_ids, role="purged_gap"),
        "untouched_forward_validation_row_digest": _ordered_digest(
            validation_ids, role="untouched_forward_validation"
        ),
        "first_forward_validation_decision_time": _format_microsecond(
            first_validation
        ),
        "maximum_train_label_available_at": _format_microsecond(
            maximum_train_label
        ),
        "latest_source_postcommit_readback_at": _format_microsecond(
            latest_source_readback
        ),
        "strict_train_label_before_validation_decision_verified": (
            maximum_train_label < first_validation
        ),
        "role_disjointness_verified": True,
        "complete_inventory_assignment_verified": True,
    }
    model_binding = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_generation": generation,
        "model_parameter_fingerprint": fingerprint,
        "model_binding_sha256": binding_sha,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
    }
    base: dict[str, Any] = {
        "schema_version": PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_CLASSIFICATION,
        "model_binding": model_binding,
        "source_outcome_inventory": inventory,
        "partition": partition_contract,
        "calibration_state": dict(calibration_state),
        "forward_validation": dict(forward_validation),
        "evidence_policy": dict(_EVIDENCE_POLICY_V2),
        "authorization": dict(_AUTHORIZATION),
        "status": {
            "calibration_admission_verified": True,
            "unchanged_model_weight_binding_verified": True,
            "purged_train_fit_verified": True,
            "untouched_forward_validation_verified": True,
            "uncertainty_non_regression_verified": True,
            "durable_replay_protection_verified": True,
            "runtime_wired": False,
        },
    }
    artifact = {
        **base,
        "admission_material_sha256": _sha256(base),
    }
    _validate_admission_artifact(artifact)
    return artifact, _canonical_bytes(
        artifact,
        reason="PROFILED_CALIBRATION_ADMISSION_ARTIFACT_JSON_INVALID",
    )


def _validate_uncertainty_scope(
    value: object,
    *,
    expected_scope: str,
    legacy: bool,
) -> None:
    if type(value) is not dict:
        _integrity("PROFILED_CALIBRATION_FORWARD_VALIDATION_INVALID")
    evidence = cast(dict[str, Any], value)
    row_count = evidence.get("uncertainty_row_count")
    normalized = expected_scope.upper()
    try:
        expected_digest = (
            legacy_confidence_uncertainty_evidence_digest(
                scope=normalized,
                evidence=evidence,
            )
            if legacy
            else confidence_uncertainty_evidence_digest(
                scope=normalized,
                evidence=evidence,
            )
        )
    except (TypeError, ValueError):
        _integrity("PROFILED_CALIBRATION_UNCERTAINTY_EVIDENCE_INVALID")
    if (
        evidence.get("scope") != normalized
        or evidence.get("method")
        != (
            PROFILED_RESEARCH_CALIBRATION_LEGACY_UNCERTAINTY_METHOD
            if legacy
            else PROFILED_RESEARCH_CALIBRATION_UNCERTAINTY_METHOD
        )
        or (
            not legacy
            and evidence.get("calibration_error_estimator")
            != CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
        )
        or evidence.get("uncertainty_evidence_digest") != expected_digest
        or type(row_count) is not int
        or cast(int, row_count) < 2
        or evidence.get("uncertainty_mathematical_minimum_rows") != 2
        or evidence.get("uncertainty_minimum_not_configured") is not True
        or evidence.get("paired_brier_non_regression_proven") is not True
        or evidence.get("ece_non_regression_proven") is not True
        or evidence.get("non_regression_proven") is not True
    ):
        _integrity("PROFILED_CALIBRATION_UNCERTAINTY_EVIDENCE_INVALID")


def _validate_admission_artifact(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _ARTIFACT_FIELDS:
        _integrity("PROFILED_CALIBRATION_ADMISSION_ARTIFACT_FIELDS_INVALID")
    artifact = cast(dict[str, Any], value)
    model = artifact.get("model_binding")
    inventory = artifact.get("source_outcome_inventory")
    partition = artifact.get("partition")
    calibration = artifact.get("calibration_state")
    validation = artifact.get("forward_validation")
    status = artifact.get("status")
    schema_version = artifact.get("schema_version")
    legacy = schema_version == PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_SCHEMA_VERSION
    current = schema_version == PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_SCHEMA_VERSION
    if (
        not (legacy or current)
        or artifact.get("classification")
        != (
            PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_CLASSIFICATION
            if legacy
            else PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_CLASSIFICATION
        )
        or type(model) is not dict
        or set(model) != _MODEL_FIELDS
        or type(inventory) is not list
        or not inventory
        or len(inventory) > _MAX_SOURCE_ROWS
        or type(partition) is not dict
        or set(partition) != _PARTITION_FIELDS
        or type(calibration) is not dict
        or type(validation) is not dict
        or set(validation) != {"global", *CONFIDENCE_HEAD_ACTIONS}
        or artifact.get("evidence_policy")
        != (_EVIDENCE_POLICY_V1 if legacy else _EVIDENCE_POLICY_V2)
        or artifact.get("authorization") != _AUTHORIZATION
        or status
        != {
            "calibration_admission_verified": True,
            "unchanged_model_weight_binding_verified": True,
            "purged_train_fit_verified": True,
            "untouched_forward_validation_verified": True,
            "uncertainty_non_regression_verified": True,
            "durable_replay_protection_verified": True,
            "runtime_wired": False,
        }
    ):
        _integrity("PROFILED_CALIBRATION_ADMISSION_ARTIFACT_INVALID")
    model_map = cast(dict[str, Any], model)
    generation = model_map.get("checkpoint_generation")
    fingerprint = _strict_sha256(model_map.get("model_parameter_fingerprint"))
    binding_sha = _strict_sha256(model_map.get("model_binding_sha256"))
    if (
        type(model_map.get("checkpoint_id")) is not str
        or _IDENTIFIER_RE.fullmatch(cast(str, model_map["checkpoint_id"])) is None
        or type(generation) is not int
        or cast(int, generation) < 0
        or fingerprint is None
        or binding_sha is None
        or model_map.get("confidence_head_schema_version")
        != CONFIDENCE_HEAD_SCHEMA_VERSION
        or model_map.get("confidence_head_actions") != list(CONFIDENCE_HEAD_ACTIONS)
        or model_map.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS
    ):
        _integrity("PROFILED_CALIBRATION_MODEL_BINDING_INVALID")
    normalized = (
        normalize_legacy_calibration_state(cast(dict[str, Any], calibration))
        if legacy
        else normalize_calibration_state(cast(dict[str, Any], calibration))
    )
    if (
        normalized != calibration
        or normalized.get("schema_version")
        != (
            LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION
            if legacy
            else CONFIDENCE_CALIBRATION_SCHEMA_VERSION
        )
        or normalized.get("fitted") is not True
        or normalized.get("fit_partition") != CONFIDENCE_FIT_PARTITION
        or normalized.get("validation_rows_used") != 0
        or normalized.get("model_parameter_fingerprint") != fingerprint
    ):
        _integrity("PROFILED_CALIBRATION_STATE_INVALID")
    source_maps: list[dict[str, Any]] = []
    row_ids: list[str] = []
    source_hashes: list[str] = []
    roles: dict[str, str] = {}
    previous_order: tuple[datetime, str] | None = None
    for raw in cast(list[Any], inventory):
        if type(raw) is not dict or set(raw) != _SOURCE_ROW_FIELDS:
            _integrity("PROFILED_CALIBRATION_SOURCE_INVENTORY_INVALID")
        row = cast(dict[str, Any], raw)
        row_id = row.get("row_id")
        artifact_sha = _strict_sha256(row.get("outcome_artifact_sha256"))
        count = row.get("outcome_artifact_byte_count")
        decision = _clock(row.get("decision_time"))
        label = _clock(row.get("actual_label_available_at"))
        maturation = _clock(row.get("maturation_observed_at"))
        commit = _clock(row.get("outcome_commit_observed_at"))
        postcommit = _clock(row.get("outcome_postcommit_observed_at"))
        postcommit_readback = _clock(row.get("outcome_postcommit_readback_at"))
        role = row.get("source_role")
        order = (decision, cast(str, row_id)) if decision is not None else None
        if (
            type(row_id) is not str
            or _IDENTIFIER_RE.fullmatch(row_id) is None
            or artifact_sha is None
            or type(count) is not int
            or not 0 < count <= _MAX_JSON_BYTES
            or any(
                _strict_sha256(row.get(field)) is None
                for field in (
                    "outcome_material_sha256",
                    "hypothesis_artifact_sha256",
                    "record_chain_sha256",
                    "append_receipt_sha256",
                    "postcommit_readback_receipt_sha256",
                )
            )
            or row.get("model_binding_sha256") != binding_sha
            or decision is None
            or label is None
            or maturation is None
            or commit is None
            or postcommit is None
            or postcommit_readback is None
            or not decision < label <= maturation < commit < postcommit <= postcommit_readback
            or row.get("selected_action") not in CONFIDENCE_HEAD_ACTIONS
            or _finite_float(row.get("raw_probability")) is None
            or not 0.0 <= cast(float, _finite_float(row.get("raw_probability"))) <= 1.0
            or type(row.get("observed_strictly_positive_net_pnl")) is not bool
            or role
            not in {
                "purged_train",
                "purged_gap",
                "untouched_forward_validation",
            }
            or order is None
            or (previous_order is not None and order <= previous_order)
        ):
            _integrity("PROFILED_CALIBRATION_SOURCE_INVENTORY_INVALID")
        previous_order = order
        row_ids.append(row_id)
        source_hashes.append(artifact_sha)
        roles[row_id] = cast(str, role)
        source_maps.append(row)
    if len(set(row_ids)) != len(row_ids) or len(set(source_hashes)) != len(source_hashes):
        _integrity("PROFILED_CALIBRATION_SOURCE_INVENTORY_DUPLICATE")
    partition_map = cast(dict[str, Any], partition)
    ordered_ids = partition_map.get("ordered_row_ids")
    train_ids = partition_map.get("purged_train_row_ids")
    purge_ids = partition_map.get("purged_gap_row_ids")
    validation_ids = partition_map.get("untouched_forward_validation_row_ids")
    if not all(type(item) is list for item in (ordered_ids, train_ids, purge_ids, validation_ids)):
        _integrity("PROFILED_CALIBRATION_PARTITION_INVALID")
    train_list = cast(list[Any], train_ids)
    purge_list = cast(list[Any], purge_ids)
    validation_list = cast(list[Any], validation_ids)
    role_ids = train_list + purge_list + validation_list
    first_validation = _clock(
        partition_map.get("first_forward_validation_decision_time")
    )
    maximum_train = _clock(partition_map.get("maximum_train_label_available_at"))
    latest_source_readback = _clock(
        partition_map.get("latest_source_postcommit_readback_at")
    )
    if (
        partition_map.get("method") != _PARTITION_METHOD
        or ordered_ids != row_ids
        or any(type(item) is not str for item in role_ids)
        or len(role_ids) != len(row_ids)
        or set(cast(list[str], role_ids)) != set(row_ids)
        or len(set(cast(list[str], role_ids))) != len(row_ids)
        or any(roles.get(row_id) != "purged_train" for row_id in train_list)
        or any(roles.get(row_id) != "purged_gap" for row_id in purge_list)
        or any(
            roles.get(row_id) != "untouched_forward_validation"
            for row_id in validation_list
        )
        or partition_map.get("purged_train_row_digest")
        != _ordered_digest(cast(list[str], train_list), role="purged_train")
        or partition_map.get("purged_gap_row_digest")
        != _ordered_digest(cast(list[str], purge_list), role="purged_gap")
        or partition_map.get("untouched_forward_validation_row_digest")
        != _ordered_digest(
            cast(list[str], validation_list),
            role="untouched_forward_validation",
        )
        or not train_list
        or not validation_list
        or first_validation is None
        or maximum_train is None
        or latest_source_readback is None
        or not maximum_train < first_validation
        or partition_map.get(
            "strict_train_label_before_validation_decision_verified"
        )
        is not True
        or partition_map.get("role_disjointness_verified") is not True
        or partition_map.get("complete_inventory_assignment_verified") is not True
    ):
        _integrity("PROFILED_CALIBRATION_PARTITION_INVALID")
    by_id = {row["row_id"]: row for row in source_maps}
    train_label_clocks = [
        _clock(by_id[row_id]["actual_label_available_at"])
        for row_id in train_list
    ]
    if any(clock is None for clock in train_label_clocks):
        _integrity("PROFILED_CALIBRATION_PARTITION_CLOCK_INVALID")
    if (
        max(cast(list[datetime], train_label_clocks))
        != maximum_train
        or _clock(by_id[validation_list[0]]["decision_time"]) != first_validation
        or max(
            cast(datetime, _clock(row["outcome_postcommit_readback_at"]))
            for row in source_maps
        )
        != latest_source_readback
        or {by_id[row_id]["selected_action"] for row_id in train_list}
        != set(CONFIDENCE_HEAD_ACTIONS)
        or {
            by_id[row_id]["observed_strictly_positive_net_pnl"]
            for row_id in train_list
        }
        != {False, True}
        or any(
            sum(by_id[row_id]["selected_action"] == action for row_id in validation_list)
            < 2
            for action in CONFIDENCE_HEAD_ACTIONS
        )
    ):
        _integrity("PROFILED_CALIBRATION_PARTITION_EVIDENCE_INVALID")
    reconstructed_rows = tuple(
        _EvidenceRow(
            row_id=cast(str, row["row_id"]),
            outcome_artifact_sha256=cast(str, row["outcome_artifact_sha256"]),
            outcome_artifact_byte_count=cast(int, row["outcome_artifact_byte_count"]),
            outcome_material_sha256=cast(str, row["outcome_material_sha256"]),
            hypothesis_artifact_sha256=cast(str, row["hypothesis_artifact_sha256"]),
            record_chain_sha256=cast(str, row["record_chain_sha256"]),
            append_receipt_sha256=cast(str, row["append_receipt_sha256"]),
            postcommit_readback_receipt_sha256=cast(
                str, row["postcommit_readback_receipt_sha256"]
            ),
            checkpoint_id=cast(str, model_map["checkpoint_id"]),
            checkpoint_generation=cast(int, model_map["checkpoint_generation"]),
            model_parameter_fingerprint=cast(
                str, model_map["model_parameter_fingerprint"]
            ),
            model_binding_sha256=cast(str, row["model_binding_sha256"]),
            decision_time=cast(str, row["decision_time"]),
            actual_label_available_at=cast(str, row["actual_label_available_at"]),
            maturation_observed_at=cast(str, row["maturation_observed_at"]),
            outcome_commit_observed_at=cast(
                str, row["outcome_commit_observed_at"]
            ),
            outcome_postcommit_observed_at=cast(
                str, row["outcome_postcommit_observed_at"]
            ),
            outcome_postcommit_readback_at=cast(
                str, row["outcome_postcommit_readback_at"]
            ),
            selected_action=cast(str, row["selected_action"]),
            raw_probability=cast(float, _finite_float(row["raw_probability"])),
            observed_strictly_positive_net_pnl=cast(
                bool, row["observed_strictly_positive_net_pnl"]
            ),
            outcome_artifact_bytes=b"",
        )
        for row in source_maps
    )
    reconstructed_partition = _chronological_partition(reconstructed_rows)
    if (
        reconstructed_partition is None
        or [row.row_id for row in reconstructed_partition.train] != train_list
        or [row.row_id for row in reconstructed_partition.purge] != purge_list
        or [row.row_id for row in reconstructed_partition.validation]
        != validation_list
    ):
        _integrity("PROFILED_CALIBRATION_PARTITION_RECOMPUTATION_FAILED")
    fit_function = fit_legacy_temperature if legacy else fit_temperature
    recomputed_state = fit_function(
        [row.raw_probability for row in reconstructed_partition.train],
        [
            int(row.observed_strictly_positive_net_pnl)
            for row in reconstructed_partition.train
        ],
        row_ids=[row.row_id for row in reconstructed_partition.train],
        action_labels=[row.selected_action for row in reconstructed_partition.train],
        fit_partition=CONFIDENCE_FIT_PARTITION,
        validation_rows_used=0,
    )
    bound_recomputed_state = {
        **recomputed_state,
        "model_parameter_fingerprint": fingerprint,
    }
    recomputed_state = (
        normalize_legacy_calibration_state(bound_recomputed_state)
        if legacy
        else normalize_calibration_state(bound_recomputed_state)
    )
    if recomputed_state != calibration:
        _integrity("PROFILED_CALIBRATION_FIT_RECOMPUTATION_FAILED")
    fitted_temperature = _finite_float(recomputed_state.get("temperature"))
    fitted_logit_scale = _finite_float(recomputed_state.get("logit_scale"))
    if legacy:
        if fitted_temperature is None or fitted_temperature <= 0.0:
            _integrity("PROFILED_CALIBRATION_TEMPERATURE_INVALID")
    elif fitted_logit_scale is None or fitted_logit_scale < 0.0:
        _integrity("PROFILED_CALIBRATION_LOGIT_SCALE_INVALID")
    for scope, evidence in cast(dict[str, Any], validation).items():
        _validate_uncertainty_scope(
            evidence,
            expected_scope=scope,
            legacy=legacy,
        )
    if legacy:
        assert fitted_temperature is not None
        expected_validation = {
            "global": _legacy_scope_uncertainty(
                reconstructed_partition.validation,
                temperature=fitted_temperature,
                scope="GLOBAL",
            ),
            **{
                action: _legacy_scope_uncertainty(
                    tuple(
                        row
                        for row in reconstructed_partition.validation
                        if row.selected_action == action
                    ),
                    temperature=fitted_temperature,
                    scope=action,
                )
                for action in CONFIDENCE_HEAD_ACTIONS
            },
        }
    else:
        assert fitted_logit_scale is not None
        expected_validation = {
            "global": _scope_uncertainty(
                reconstructed_partition.validation,
                logit_scale=fitted_logit_scale,
                scope="GLOBAL",
            ),
            **{
                action: _scope_uncertainty(
                    tuple(
                        row
                        for row in reconstructed_partition.validation
                        if row.selected_action == action
                    ),
                    logit_scale=fitted_logit_scale,
                    scope=action,
                )
                for action in CONFIDENCE_HEAD_ACTIONS
            },
        }
    if expected_validation != validation:
        _integrity("PROFILED_CALIBRATION_FORWARD_VALIDATION_RECOMPUTATION_FAILED")
    if (
        cast(dict[str, Any], validation)["global"].get("uncertainty_row_count")
        != len(validation_list)
        or any(
            cast(dict[str, Any], validation)[action].get("uncertainty_row_count")
            != sum(
                by_id[row_id]["selected_action"] == action
                for row_id in validation_list
            )
            for action in CONFIDENCE_HEAD_ACTIONS
        )
    ):
        _integrity("PROFILED_CALIBRATION_FORWARD_VALIDATION_COUNT_INVALID")
    expected_material = _sha256(
        {key: artifact[key] for key in artifact if key != "admission_material_sha256"}
    )
    if artifact.get("admission_material_sha256") != expected_material:
        _integrity("PROFILED_CALIBRATION_ADMISSION_MATERIAL_INVALID")
    return artifact


def validate_profiled_research_calibration_admission_artifact_v1(
    payload: object,
) -> dict[str, Any]:
    if type(payload) is not bytes:
        _validation("PROFILED_CALIBRATION_ADMISSION_EXACT_BYTES_REQUIRED")
    artifact = _parse_exact_object(
        cast(bytes, payload),
        reason="PROFILED_CALIBRATION_ADMISSION_ARTIFACT_JSON_INVALID",
    )
    _validate_admission_artifact(artifact)
    return artifact


def _schema_script() -> str:
    return f"""
    PRAGMA application_id={_APPLICATION_ID};
    PRAGMA user_version={_USER_VERSION};
    CREATE TABLE profiled_calibration_metadata (
        metadata_key TEXT PRIMARY KEY,
        metadata_value TEXT NOT NULL
    );
    CREATE TABLE profiled_calibration_admissions (
        sequence INTEGER PRIMARY KEY,
        checkpoint_id TEXT NOT NULL,
        checkpoint_generation INTEGER NOT NULL CHECK(checkpoint_generation >= 0),
        model_parameter_fingerprint TEXT NOT NULL UNIQUE,
        model_binding_sha256 TEXT NOT NULL UNIQUE,
        admission_artifact_sha256 TEXT NOT NULL UNIQUE,
        admission_artifact_byte_count INTEGER NOT NULL CHECK(
            admission_artifact_byte_count > 0
            AND admission_artifact_byte_count <= {_MAX_JSON_BYTES}
        ),
        admission_artifact_relative_path TEXT NOT NULL,
        admission_artifact_json TEXT NOT NULL CHECK(
            length(CAST(admission_artifact_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        admission_material_sha256 TEXT NOT NULL UNIQUE,
        source_inventory_digest TEXT NOT NULL UNIQUE,
        purged_train_row_digest TEXT NOT NULL,
        purged_gap_row_digest TEXT NOT NULL,
        untouched_forward_validation_row_digest TEXT NOT NULL,
        previous_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL UNIQUE,
        transaction_id TEXT NOT NULL UNIQUE,
        admitted_observed_at TEXT NOT NULL UNIQUE
    );
    CREATE TABLE profiled_calibration_source_rows (
        row_id TEXT PRIMARY KEY,
        outcome_artifact_sha256 TEXT NOT NULL UNIQUE,
        outcome_artifact_byte_count INTEGER NOT NULL CHECK(
            outcome_artifact_byte_count > 0
            AND outcome_artifact_byte_count <= {_MAX_JSON_BYTES}
        ),
        outcome_artifact_relative_path TEXT NOT NULL,
        admission_sequence INTEGER NOT NULL,
        model_parameter_fingerprint TEXT NOT NULL,
        source_role TEXT NOT NULL CHECK(source_role IN (
            'purged_train', 'purged_gap', 'untouched_forward_validation'
        )),
        decision_time TEXT NOT NULL,
        actual_label_available_at TEXT NOT NULL,
        source_row_json TEXT NOT NULL CHECK(
            length(CAST(source_row_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        FOREIGN KEY(admission_sequence)
            REFERENCES profiled_calibration_admissions(sequence)
    );
    CREATE TABLE profiled_calibration_append_receipts (
        transaction_id TEXT PRIMARY KEY,
        admission_artifact_sha256 TEXT NOT NULL UNIQUE,
        record_chain_sha256 TEXT NOT NULL UNIQUE,
        total_admissions INTEGER NOT NULL CHECK(total_admissions > 0),
        receipt_sha256 TEXT NOT NULL UNIQUE,
        receipt_json TEXT NOT NULL CHECK(
            length(CAST(receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        committed_at TEXT NOT NULL UNIQUE,
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_calibration_admissions(transaction_id)
    );
    CREATE TABLE profiled_calibration_head_anchors (
        sequence INTEGER PRIMARY KEY,
        transaction_id TEXT NOT NULL UNIQUE,
        admission_artifact_sha256 TEXT NOT NULL UNIQUE,
        record_chain_sha256 TEXT NOT NULL UNIQUE,
        append_receipt_sha256 TEXT NOT NULL UNIQUE,
        previous_head_anchor_sha256 TEXT NOT NULL,
        head_anchor_sha256 TEXT NOT NULL UNIQUE,
        head_anchor_byte_count INTEGER NOT NULL CHECK(
            head_anchor_byte_count > 0
            AND head_anchor_byte_count <= {_MAX_JSON_BYTES}
        ),
        head_anchor_relative_path TEXT NOT NULL,
        head_anchor_json TEXT NOT NULL CHECK(
            length(CAST(head_anchor_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        anchored_at TEXT NOT NULL UNIQUE,
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_calibration_append_receipts(transaction_id)
    );
    CREATE INDEX profiled_calibration_source_model_role
        ON profiled_calibration_source_rows(
            model_parameter_fingerprint, source_role, decision_time, row_id
        );
    CREATE INDEX profiled_calibration_checkpoint_identity
        ON profiled_calibration_admissions(
            checkpoint_id, checkpoint_generation, model_parameter_fingerprint
        );
    """ + "\n".join(
        f"""
        CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
        BEGIN SELECT RAISE(ABORT, '{table}_rows_are_immutable'); END;
        CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT, '{table}_rows_are_immutable'); END;
        """
        for table in sorted(_TABLE_NAMES)
    )


def _normalized_schema_sql(value: object) -> str | None:
    return " ".join(value.split()) if type(value) is str and value.strip() else None


@lru_cache(maxsize=1)
def _expected_schema_sql() -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_schema_script())
        rows = connection.execute(
            """
            SELECT type, name, sql FROM sqlite_master
            WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
    finally:
        connection.close()
    result: dict[tuple[str, str], str] = {}
    for row in rows:
        normalized = _normalized_schema_sql(row["sql"])
        if normalized is None:
            _integrity("PROFILED_CALIBRATION_EXPECTED_SCHEMA_INVALID")
        result[(str(row["type"]), str(row["name"]))] = normalized
    return result


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=60000")


def _validate_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT type, name, sql FROM sqlite_master
        WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    observed: dict[str, set[str]] = {"table": set(), "index": set(), "trigger": set()}
    observed_sql: dict[tuple[str, str], str] = {}
    for row in rows:
        object_type = str(row["type"])
        name = str(row["name"])
        if object_type in observed:
            observed[object_type].add(name)
        normalized = _normalized_schema_sql(row["sql"])
        if normalized is None:
            _integrity("PROFILED_CALIBRATION_SCHEMA_SQL_INVALID")
        observed_sql[(object_type, name)] = normalized
    try:
        metadata = {
            str(row["metadata_key"]): str(row["metadata_value"])
            for row in connection.execute(
                "SELECT metadata_key, metadata_value FROM profiled_calibration_metadata"
            )
        }
    except sqlite3.DatabaseError as exc:
        raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
            "PROFILED_CALIBRATION_SCHEMA_INVALID"
        ) from exc
    if (
        int(connection.execute("PRAGMA application_id").fetchone()[0])
        != _APPLICATION_ID
        or int(connection.execute("PRAGMA user_version").fetchone()[0])
        != _USER_VERSION
        or int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1
        or observed["table"] != _TABLE_NAMES
        or observed["index"] != _INDEX_NAMES
        or observed["trigger"] != _TRIGGER_NAMES
        or observed_sql != _expected_schema_sql()
        or tuple(connection.execute("PRAGMA quick_check").fetchone()) != ("ok",)
        or connection.execute("PRAGMA foreign_key_check").fetchall()
        or metadata != _METADATA
    ):
        _integrity("PROFILED_CALIBRATION_SCHEMA_INVALID")


def _lexical_absolute_path(path: object) -> Path:
    if not isinstance(path, Path):
        _validation("PROFILED_CALIBRATION_LEDGER_EXACT_PATH_REQUIRED")
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


def _writer_lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".writer.lock")


def _head_catalog_root(path: Path) -> Path:
    return path.with_name(path.name + ".head-anchor-cas")


def _validate_regular_path(path: Path, *, allow_missing: bool) -> None:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return
        _integrity("PROFILED_CALIBRATION_LEDGER_MISSING")
    except OSError as exc:
        raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
            "PROFILED_CALIBRATION_LEDGER_PATH_INVALID"
        ) from exc
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_size > _MAX_DATABASE_BYTES
    ):
        _integrity("PROFILED_CALIBRATION_LEDGER_PATH_INVALID")


@contextmanager
def _database_lease(
    path: Path, *, exclusive: bool, create_database: bool
) -> Iterator[bool]:
    if exclusive:
        path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _writer_lock_path(path)
    flags = os.O_RDWR | os.O_CREAT if exclusive else os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ProfiledResearchCalibrationAdmissionV1ConflictError(
            "PROFILED_CALIBRATION_WRITER_LEASE_OPEN_FAILED"
        ) from exc
    database_descriptor = -1
    created = False
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(lock_path, follow_symlinks=False)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise ProfiledResearchCalibrationAdmissionV1ConflictError(
                "PROFILED_CALIBRATION_WRITER_LEASE_BINDING_INVALID"
            )
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, lock_mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProfiledResearchCalibrationAdmissionV1ConflictError(
                "PROFILED_CALIBRATION_DATABASE_LEASE_ALREADY_HELD"
            ) from exc
        database_flags = os.O_RDWR if exclusive else os.O_RDONLY
        database_flags |= getattr(os, "O_CLOEXEC", 0)
        database_flags |= getattr(os, "O_NOFOLLOW", 0)
        if create_database:
            database_flags |= os.O_CREAT | os.O_EXCL
        try:
            database_descriptor = os.open(path, database_flags, 0o600)
            created = create_database
        except FileExistsError:
            if not create_database:
                raise
            database_flags &= ~(os.O_CREAT | os.O_EXCL)
            database_descriptor = os.open(path, database_flags)
            created = False
        except OSError as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_DATABASE_INODE_OPEN_FAILED"
            ) from exc
        database_stat = os.fstat(database_descriptor)
        database_path_stat = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(database_stat.st_mode)
            or (database_stat.st_dev, database_stat.st_ino)
            != (database_path_stat.st_dev, database_path_stat.st_ino)
        ):
            _integrity("PROFILED_CALIBRATION_DATABASE_INODE_INVALID")
        try:
            fcntl.flock(database_descriptor, lock_mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProfiledResearchCalibrationAdmissionV1ConflictError(
                "PROFILED_CALIBRATION_DATABASE_INODE_ALREADY_HELD"
            ) from exc
        yield created
        final_stat = os.stat(path, follow_symlinks=False)
        if (final_stat.st_dev, final_stat.st_ino) != (
            database_stat.st_dev,
            database_stat.st_ino,
        ):
            _integrity("PROFILED_CALIBRATION_DATABASE_BINDING_CHANGED")
    finally:
        if database_descriptor >= 0:
            try:
                fcntl.flock(database_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(database_descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _expected_address(payload: bytes) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(payload),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )


@dataclass(frozen=True, slots=True)
class _PreparedAdmission:
    rows: tuple[_EvidenceRow, ...]
    partition: _Partition
    artifact: dict[str, Any] = field(repr=False)
    artifact_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProfiledResearchCalibrationAdmissionIntegrityV1:
    total_admissions: int
    source_rows_verified: int
    append_receipts_verified: int
    head_anchors_verified: int
    admission_cas_artifacts_verified: int
    source_outcome_cas_artifacts_verified: int
    head_catalog_artifacts_verified: int
    replayed_source_rows: int
    schema_verified: bool
    chain_head_sha256: str
    head_anchor_sha256: str


@dataclass(frozen=True, slots=True)
class DurablyAdmittedProfiledResearchCalibrationV1:
    sequence: int
    checkpoint_id: str
    checkpoint_generation: int
    model_parameter_fingerprint: str
    model_binding_sha256: str
    admission_artifact_sha256: str
    admission_artifact_byte_count: int
    admission_artifact_address: SourcePayloadAddress
    admission_material_sha256: str
    source_inventory_digest: str
    transaction_id: str
    append_receipt_sha256: str
    record_chain_sha256: str
    head_anchor_sha256: str
    admitted_observed_at: str
    _artifact_json: str = field(repr=False, compare=False)
    _ledger: ProfiledResearchCalibrationAdmissionLedgerV1 = field(
        repr=False, compare=False
    )
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def admission_contract(self) -> dict[str, Any]:
        return _validated_result(self)

    @property
    def calibration_state(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.admission_contract["calibration_state"])

    @property
    def forward_validation(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.admission_contract["forward_validation"])

    @property
    def authorization(self) -> dict[str, bool]:
        _validated_result(self)
        return dict(_AUTHORIZATION)

    @property
    def calibration_input_authorized(self) -> bool:
        _validated_result(self)
        return True

    @property
    def calibration_only_checkpoint_write_authorized(self) -> bool:
        _validated_result(self)
        return True

    @property
    def model_weight_mutation_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def optimizer_execution_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def serving_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def paper_trading_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def live_execution_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def runtime_wired(self) -> bool:
        _validated_result(self)
        return False


def _result_seal_material(
    *,
    sequence: int,
    model_parameter_fingerprint: str,
    admission_artifact_sha256: str,
    transaction_id: str,
    append_receipt_sha256: str,
    record_chain_sha256: str,
    head_anchor_sha256: str,
) -> bytes:
    return _canonical_bytes(
        {
            "sequence": sequence,
            "model_parameter_fingerprint": model_parameter_fingerprint,
            "admission_artifact_sha256": admission_artifact_sha256,
            "transaction_id": transaction_id,
            "append_receipt_sha256": append_receipt_sha256,
            "record_chain_sha256": record_chain_sha256,
            "head_anchor_sha256": head_anchor_sha256,
        },
        reason="PROFILED_CALIBRATION_RESULT_SEAL_MATERIAL_INVALID",
    )


def _factory_seal(**values: Any) -> str:
    return hmac.new(
        _RESULT_SEAL_KEY,
        _result_seal_material(**values),
        hashlib.sha256,
    ).hexdigest()


class ProfiledResearchCalibrationAdmissionLedgerV1:
    """Append-only, CAS-backed calibration admission boundary.

    The class is deliberately not runtime-wired.  Successful admission proves
    only that one unchanged checkpoint has durable calibration evidence that a
    later calibration-only promoter may consume.
    """

    def __init__(self, path: Path, *, store: ImmutableSourcePayloadStore) -> None:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("PROFILED_CALIBRATION_EXACT_CAS_STORE_REQUIRED")
        self.path = _lexical_absolute_path(path)
        self.store = store

    def evaluate_outcomes(
        self, outcomes: object
    ) -> ProfiledResearchCalibrationEvaluationV1:
        evaluation, _prepared = _prepare_outcomes(outcomes)
        return evaluation

    def admit_outcomes(
        self, outcomes: object
    ) -> (
        ProfiledResearchCalibrationEvaluationV1
        | DurablyAdmittedProfiledResearchCalibrationV1
    ):
        evaluation, prepared = _prepare_outcomes(outcomes)
        if prepared is None:
            return evaluation
        return self._append_prepared(prepared)

    def _connect_write(self, *, created: bool) -> sqlite3.Connection:
        _validate_regular_path(self.path, allow_missing=False)
        if not created and self.path.stat().st_size == 0:
            _integrity("PROFILED_CALIBRATION_LEDGER_EMPTY")
        try:
            connection = sqlite3.connect(self.path, isolation_level=None)
        except sqlite3.DatabaseError as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_LEDGER_OPEN_FAILED"
            ) from exc
        _configure_connection(connection)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA temp_store=MEMORY")
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            maximum_pages = _MAX_DATABASE_BYTES // page_size
            configured_pages = int(
                connection.execute(
                    f"PRAGMA max_page_count={maximum_pages}"
                ).fetchone()[0]
            )
            if created:
                connection.executescript("BEGIN IMMEDIATE;\n" + _schema_script())
                connection.executemany(
                    """
                    INSERT INTO profiled_calibration_metadata(
                        metadata_key, metadata_value
                    ) VALUES (?, ?)
                    """,
                    sorted(_METADATA.items()),
                )
                connection.execute("COMMIT")
                _fsync_parent(self.path)
            _validate_schema(connection)
            if (
                str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                != "delete"
                or int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2
                or int(connection.execute("PRAGMA temp_store").fetchone()[0]) != 2
                or configured_pages > maximum_pages
                or int(connection.execute("PRAGMA page_count").fetchone()[0])
                > maximum_pages
            ):
                _integrity("PROFILED_CALIBRATION_DURABILITY_PRAGMA_INVALID")
        except BaseException:
            connection.close()
            raise
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        _validate_regular_path(self.path, allow_missing=False)
        uri = f"file:{quote(str(self.path), safe='/')}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, isolation_level=None)
        except sqlite3.DatabaseError as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_LEDGER_OPEN_FAILED"
            ) from exc
        _configure_connection(connection)
        try:
            connection.execute("PRAGMA query_only=ON")
            _validate_schema(connection)
        except BaseException:
            connection.close()
            raise
        return connection

    @staticmethod
    def _joined_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT a.*,
                   r.receipt_sha256, r.receipt_json, r.total_admissions,
                   r.committed_at,
                   h.append_receipt_sha256 AS head_append_receipt_sha256,
                   h.previous_head_anchor_sha256, h.head_anchor_sha256,
                   h.head_anchor_byte_count, h.head_anchor_relative_path,
                   h.head_anchor_json, h.anchored_at
            FROM profiled_calibration_admissions AS a
            LEFT JOIN profiled_calibration_append_receipts AS r
                ON r.transaction_id = a.transaction_id
            LEFT JOIN profiled_calibration_head_anchors AS h
                ON h.transaction_id = a.transaction_id
            ORDER BY a.sequence
            LIMIT ?
            """,
            (_MAX_LEDGER_RECORDS + 1,),
        ).fetchall()
        if len(rows) > _MAX_LEDGER_RECORDS:
            _integrity("PROFILED_CALIBRATION_LEDGER_RESOURCE_BOUND_EXCEEDED")
        return rows

    @staticmethod
    def _source_rows(
        connection: sqlite3.Connection, *, admission_sequence: int
    ) -> list[sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT * FROM profiled_calibration_source_rows
            WHERE admission_sequence = ?
            ORDER BY decision_time, row_id
            LIMIT ?
            """,
            (admission_sequence, _MAX_SOURCE_ROWS + 1),
        ).fetchall()
        if len(rows) > _MAX_SOURCE_ROWS:
            _integrity("PROFILED_CALIBRATION_SOURCE_RESOURCE_BOUND_EXCEEDED")
        return rows

    def _observed_head_catalog_digests(
        self, *, allow_empty_shards: bool = False
    ) -> set[str]:
        root = _head_catalog_root(self.path)
        sha_root = root / "sha256"
        try:
            root_stat = os.stat(root, follow_symlinks=False)
        except FileNotFoundError:
            return set()
        except OSError as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID"
            ) from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID")
        try:
            sha_stat = os.stat(sha_root, follow_symlinks=False)
        except FileNotFoundError:
            return set()
        except OSError as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID"
            ) from exc
        if not stat.S_ISDIR(sha_stat.st_mode):
            _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID")
        observed: set[str] = set()
        shard_count = 0
        for shard in sha_root.iterdir():
            shard_count += 1
            try:
                shard_stat = os.stat(shard, follow_symlinks=False)
            except OSError as exc:
                raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                    "PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID"
                ) from exc
            if (
                shard_count > 256
                or not stat.S_ISDIR(shard_stat.st_mode)
                or re.fullmatch(r"[0-9a-f]{2}", shard.name) is None
            ):
                _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID")
            objects = 0
            for payload in shard.iterdir():
                objects += 1
                try:
                    payload_stat = os.stat(payload, follow_symlinks=False)
                except OSError as exc:
                    raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                        "PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID"
                    ) from exc
                if (
                    len(observed) >= _MAX_LEDGER_RECORDS
                    or not stat.S_ISREG(payload_stat.st_mode)
                    or not 0 < payload_stat.st_size <= _MAX_JSON_BYTES
                    or _strict_sha256(payload.name) is None
                    or payload.name[:2] != shard.name
                ):
                    _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID")
                observed.add(payload.name)
            if objects == 0 and not allow_empty_shards:
                _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_LAYOUT_INVALID")
        return observed

    def _publish_head_catalog(self, *, transaction_id: str) -> None:
        connection = self._connect_readonly()
        try:
            row = connection.execute(
                """
                SELECT head_anchor_sha256, head_anchor_byte_count,
                       head_anchor_relative_path, head_anchor_json
                FROM profiled_calibration_head_anchors
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            _integrity("PROFILED_CALIBRATION_HEAD_ANCHOR_MISSING")
        payload = cast(str, row["head_anchor_json"]).encode("ascii")
        expected = SourcePayloadAddress(
            schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
            payload_sha256=cast(str, row["head_anchor_sha256"]),
            payload_byte_count=cast(int, row["head_anchor_byte_count"]),
            relative_path=cast(str, row["head_anchor_relative_path"]),
        )
        published = _put_exact(
            ImmutableSourcePayloadStore(_head_catalog_root(self.path)), payload
        )
        if published != expected:
            _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_PUBLICATION_INVALID")

    def _verify_head_catalog(self, rows: Sequence[sqlite3.Row]) -> int:
        expected = {
            cast(str, row["head_anchor_sha256"])
            for row in rows
            if row["head_anchor_sha256"] is not None
        }
        if self._observed_head_catalog_digests() != expected:
            _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_MEMBERSHIP_INVALID")
        if not expected:
            return 0
        catalog = ImmutableSourcePayloadStore(_head_catalog_root(self.path))
        for row in rows:
            if row["head_anchor_sha256"] is None:
                continue
            address = SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=cast(str, row["head_anchor_sha256"]),
                payload_byte_count=cast(int, row["head_anchor_byte_count"]),
                relative_path=cast(str, row["head_anchor_relative_path"]),
            )
            payload = _get_exact(catalog, address)
            if payload != cast(str, row["head_anchor_json"]).encode("ascii"):
                _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_MISMATCH")
        return len(expected)

    @staticmethod
    def _record_chain_material(
        *,
        sequence: int,
        transaction_id: str,
        admission_artifact_sha256: str,
        admission_material_sha256: str,
        source_inventory_digest: str,
        previous_chain_sha256: str,
        admitted_observed_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_CALIBRATION_ADMISSION_LEDGER_V1_SCHEMA_VERSION
            ),
            "sequence": sequence,
            "transaction_id": transaction_id,
            "admission_artifact_sha256": admission_artifact_sha256,
            "admission_material_sha256": admission_material_sha256,
            "source_inventory_digest": source_inventory_digest,
            "previous_chain_sha256": previous_chain_sha256,
            "admitted_observed_at": admitted_observed_at,
        }

    @staticmethod
    def _append_receipt_contract(
        *,
        transaction_id: str,
        admission_artifact_sha256: str,
        record_chain_sha256: str,
        total_admissions: int,
        committed_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_CALIBRATION_ADMISSION_APPEND_RECEIPT_V1_SCHEMA_VERSION
            ),
            "transaction_id": transaction_id,
            "admission_artifact_sha256": admission_artifact_sha256,
            "record_chain_sha256": record_chain_sha256,
            "total_admissions": total_admissions,
            "committed_at": committed_at,
            "precommit_readback_verified": True,
        }

    @staticmethod
    def _head_anchor_contract(
        *,
        sequence: int,
        transaction_id: str,
        admission_artifact_sha256: str,
        record_chain_sha256: str,
        append_receipt_sha256: str,
        previous_head_anchor_sha256: str,
        anchored_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_CALIBRATION_ADMISSION_HEAD_ANCHOR_V1_SCHEMA_VERSION
            ),
            "sequence": sequence,
            "transaction_id": transaction_id,
            "admission_artifact_sha256": admission_artifact_sha256,
            "record_chain_sha256": record_chain_sha256,
            "append_receipt_sha256": append_receipt_sha256,
            "previous_head_anchor_sha256": previous_head_anchor_sha256,
            "anchored_at": anchored_at,
        }

    def _verify_rows(
        self,
        connection: sqlite3.Connection,
        *,
        require_head_catalog: bool,
    ) -> tuple[ProfiledResearchCalibrationAdmissionIntegrityV1, list[sqlite3.Row]]:
        rows = self._joined_rows(connection)
        previous_chain = _GENESIS_CHAIN_SHA256
        previous_head = _GENESIS_HEAD_SHA256
        previous_clock = _UTC_EPOCH
        source_seen: set[str] = set()
        source_artifacts = 0
        for expected_sequence, row in enumerate(rows, start=1):
            artifact_json = row["admission_artifact_json"]
            if type(artifact_json) is not str:
                _integrity("PROFILED_CALIBRATION_ARTIFACT_JSON_INVALID")
            artifact_bytes = artifact_json.encode("ascii", errors="strict")
            artifact = validate_profiled_research_calibration_admission_artifact_v1(
                artifact_bytes
            )
            address = SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=cast(str, row["admission_artifact_sha256"]),
                payload_byte_count=cast(int, row["admission_artifact_byte_count"]),
                relative_path=cast(str, row["admission_artifact_relative_path"]),
            )
            admitted_clock = _clock(row["admitted_observed_at"])
            model = cast(dict[str, Any], artifact["model_binding"])
            partition = cast(dict[str, Any], artifact["partition"])
            latest_source_readback = _clock(
                partition.get("latest_source_postcommit_readback_at")
            )
            inventory = cast(list[dict[str, Any]], artifact["source_outcome_inventory"])
            inventory_digest = _sha256(inventory)
            if (
                row["sequence"] != expected_sequence
                or address != _expected_address(artifact_bytes)
                or _get_exact(self.store, address) != artifact_bytes
                or row["checkpoint_id"] != model["checkpoint_id"]
                or row["checkpoint_generation"] != model["checkpoint_generation"]
                or row["model_parameter_fingerprint"]
                != model["model_parameter_fingerprint"]
                or row["model_binding_sha256"] != model["model_binding_sha256"]
                or row["admission_material_sha256"]
                != artifact["admission_material_sha256"]
                or row["source_inventory_digest"] != inventory_digest
                or row["purged_train_row_digest"]
                != partition["purged_train_row_digest"]
                or row["purged_gap_row_digest"]
                != partition["purged_gap_row_digest"]
                or row["untouched_forward_validation_row_digest"]
                != partition["untouched_forward_validation_row_digest"]
                or row["previous_chain_sha256"] != previous_chain
                or admitted_clock is None
                or admitted_clock <= previous_clock
                or latest_source_readback is None
                or admitted_clock <= latest_source_readback
            ):
                _integrity("PROFILED_CALIBRATION_LEDGER_ROW_INVALID")
            expected_chain = _sha256(
                self._record_chain_material(
                    sequence=expected_sequence,
                    transaction_id=cast(str, row["transaction_id"]),
                    admission_artifact_sha256=address.payload_sha256,
                    admission_material_sha256=cast(
                        str, row["admission_material_sha256"]
                    ),
                    source_inventory_digest=inventory_digest,
                    previous_chain_sha256=previous_chain,
                    admitted_observed_at=cast(str, row["admitted_observed_at"]),
                )
            )
            receipt = self._append_receipt_contract(
                transaction_id=cast(str, row["transaction_id"]),
                admission_artifact_sha256=address.payload_sha256,
                record_chain_sha256=expected_chain,
                total_admissions=expected_sequence,
                committed_at=cast(str, row["admitted_observed_at"]),
            )
            receipt_json = _canonical_json(
                receipt, reason="PROFILED_CALIBRATION_RECEIPT_JSON_INVALID"
            )
            receipt_sha = hashlib.sha256(receipt_json.encode("ascii")).hexdigest()
            head = self._head_anchor_contract(
                sequence=expected_sequence,
                transaction_id=cast(str, row["transaction_id"]),
                admission_artifact_sha256=address.payload_sha256,
                record_chain_sha256=expected_chain,
                append_receipt_sha256=receipt_sha,
                previous_head_anchor_sha256=previous_head,
                anchored_at=cast(str, row["admitted_observed_at"]),
            )
            head_json = _canonical_json(
                head, reason="PROFILED_CALIBRATION_HEAD_JSON_INVALID"
            )
            head_address = _expected_address(head_json.encode("ascii"))
            if (
                row["record_chain_sha256"] != expected_chain
                or row["receipt_json"] != receipt_json
                or row["receipt_sha256"] != receipt_sha
                or row["total_admissions"] != expected_sequence
                or row["committed_at"] != row["admitted_observed_at"]
                or row["head_append_receipt_sha256"] != receipt_sha
                or row["previous_head_anchor_sha256"] != previous_head
                or row["head_anchor_json"] != head_json
                or row["head_anchor_sha256"] != head_address.payload_sha256
                or row["head_anchor_byte_count"] != head_address.payload_byte_count
                or row["head_anchor_relative_path"] != head_address.relative_path
                or row["anchored_at"] != row["admitted_observed_at"]
            ):
                _integrity("PROFILED_CALIBRATION_RECEIPT_OR_HEAD_INVALID")
            source_rows = self._source_rows(
                connection, admission_sequence=expected_sequence
            )
            if len(source_rows) != len(inventory):
                _integrity("PROFILED_CALIBRATION_SOURCE_LEDGER_COUNT_INVALID")
            source_by_id = {cast(str, item["row_id"]): item for item in source_rows}
            for source_contract in inventory:
                source = source_by_id.get(cast(str, source_contract["row_id"]))
                source_json = _canonical_json(
                    source_contract,
                    reason="PROFILED_CALIBRATION_SOURCE_ROW_JSON_INVALID",
                )
                if source is None:
                    _integrity("PROFILED_CALIBRATION_SOURCE_LEDGER_ROW_MISSING")
                source_address = SourcePayloadAddress(
                    schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                    payload_sha256=cast(str, source["outcome_artifact_sha256"]),
                    payload_byte_count=cast(int, source["outcome_artifact_byte_count"]),
                    relative_path=cast(str, source["outcome_artifact_relative_path"]),
                )
                source_payload = _get_exact(self.store, source_address)
                source_artifact = (
                    validate_profiled_research_finalized_outcome_artifact_v1(
                        source_payload
                    )
                )
                calibration_row = source_artifact.get("calibration_row")
                hypothesis_binding = source_artifact.get("hypothesis_binding")
                if (
                    source["admission_sequence"] != expected_sequence
                    or source["model_parameter_fingerprint"]
                    != row["model_parameter_fingerprint"]
                    or source["source_role"] != source_contract["source_role"]
                    or source["decision_time"] != source_contract["decision_time"]
                    or source["actual_label_available_at"]
                    != source_contract["actual_label_available_at"]
                    or source["source_row_json"] != source_json
                    or source_address != _expected_address(source_payload)
                    or source_address.payload_sha256
                    != source_contract["outcome_artifact_sha256"]
                    or source_address.payload_byte_count
                    != source_contract["outcome_artifact_byte_count"]
                    or type(calibration_row) is not dict
                    or type(hypothesis_binding) is not dict
                    or source_artifact.get("outcome_material_sha256")
                    != source_contract["outcome_material_sha256"]
                    or hypothesis_binding.get("hypothesis_artifact_sha256")
                    != source_contract["hypothesis_artifact_sha256"]
                    or calibration_row.get("row_id") != source_contract["row_id"]
                    or calibration_row.get("selected_directional_action")
                    != source_contract["selected_action"]
                    or calibration_row.get("raw_probability")
                    != source_contract["raw_probability"]
                    or calibration_row.get("observed_strictly_positive_net_pnl")
                    != source_contract["observed_strictly_positive_net_pnl"]
                    or calibration_row.get("model_binding_sha256")
                    != source_contract["model_binding_sha256"]
                    or source_address.payload_sha256 in source_seen
                ):
                    _integrity("PROFILED_CALIBRATION_SOURCE_REOPEN_INVALID")
                source_seen.add(source_address.payload_sha256)
                source_artifacts += 1
            previous_chain = expected_chain
            previous_head = head_address.payload_sha256
            previous_clock = admitted_clock
        head_count = self._verify_head_catalog(rows) if require_head_catalog else 0
        return (
            ProfiledResearchCalibrationAdmissionIntegrityV1(
                total_admissions=len(rows),
                source_rows_verified=source_artifacts,
                append_receipts_verified=len(rows),
                head_anchors_verified=len(rows),
                admission_cas_artifacts_verified=len(rows),
                source_outcome_cas_artifacts_verified=source_artifacts,
                head_catalog_artifacts_verified=head_count,
                replayed_source_rows=0,
                schema_verified=True,
                chain_head_sha256=previous_chain,
                head_anchor_sha256=previous_head,
            ),
            rows,
        )

    def verify_integrity(self) -> ProfiledResearchCalibrationAdmissionIntegrityV1:
        with _database_lease(
            self.path, exclusive=False, create_database=False
        ):
            return self._verify_integrity_unleased()

    def _verify_integrity_unleased(
        self,
    ) -> ProfiledResearchCalibrationAdmissionIntegrityV1:
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            report, _ = self._verify_rows(
                connection, require_head_catalog=True
            )
            connection.commit()
            return report
        finally:
            connection.close()

    def _make_result(self, row: sqlite3.Row) -> DurablyAdmittedProfiledResearchCalibrationV1:
        sequence = cast(int, row["sequence"])
        fingerprint = cast(str, row["model_parameter_fingerprint"])
        artifact_sha = cast(str, row["admission_artifact_sha256"])
        transaction_id = cast(str, row["transaction_id"])
        receipt_sha = cast(str, row["receipt_sha256"])
        chain_sha = cast(str, row["record_chain_sha256"])
        head_sha = cast(str, row["head_anchor_sha256"])
        seal_values = {
            "sequence": sequence,
            "model_parameter_fingerprint": fingerprint,
            "admission_artifact_sha256": artifact_sha,
            "transaction_id": transaction_id,
            "append_receipt_sha256": receipt_sha,
            "record_chain_sha256": chain_sha,
            "head_anchor_sha256": head_sha,
        }
        return DurablyAdmittedProfiledResearchCalibrationV1(
            sequence=sequence,
            checkpoint_id=cast(str, row["checkpoint_id"]),
            checkpoint_generation=cast(int, row["checkpoint_generation"]),
            model_parameter_fingerprint=fingerprint,
            model_binding_sha256=cast(str, row["model_binding_sha256"]),
            admission_artifact_sha256=artifact_sha,
            admission_artifact_byte_count=cast(
                int, row["admission_artifact_byte_count"]
            ),
            admission_artifact_address=SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=artifact_sha,
                payload_byte_count=cast(int, row["admission_artifact_byte_count"]),
                relative_path=cast(str, row["admission_artifact_relative_path"]),
            ),
            admission_material_sha256=cast(
                str, row["admission_material_sha256"]
            ),
            source_inventory_digest=cast(str, row["source_inventory_digest"]),
            transaction_id=transaction_id,
            append_receipt_sha256=receipt_sha,
            record_chain_sha256=chain_sha,
            head_anchor_sha256=head_sha,
            admitted_observed_at=cast(str, row["admitted_observed_at"]),
            _artifact_json=cast(str, row["admission_artifact_json"]),
            _ledger=self,
            _factory_seal=_factory_seal(**seal_values),
            _construction_token=_RESULT_TOKEN,
        )

    def open_admission(
        self, *, model_parameter_fingerprint: object
    ) -> DurablyAdmittedProfiledResearchCalibrationV1:
        fingerprint = _strict_sha256(model_parameter_fingerprint)
        if fingerprint is None:
            _validation("PROFILED_CALIBRATION_MODEL_FINGERPRINT_INVALID")
        with _database_lease(
            self.path, exclusive=False, create_database=False
        ):
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_rows(
                    connection, require_head_catalog=True
                )
                matches = [
                    row
                    for row in rows
                    if row["model_parameter_fingerprint"] == fingerprint
                ]
                if len(matches) != 1:
                    _validation("PROFILED_CALIBRATION_ADMISSION_NOT_FOUND")
                result = self._make_result(matches[0])
                connection.commit()
                return result
            finally:
                connection.close()

    def _validated_contract_for_result(
        self, result: DurablyAdmittedProfiledResearchCalibrationV1
    ) -> dict[str, Any]:
        with _database_lease(
            self.path, exclusive=False, create_database=False
        ):
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_rows(
                    connection, require_head_catalog=True
                )
                matches = [
                    row
                    for row in rows
                    if row["sequence"] == result.sequence
                    and row["model_parameter_fingerprint"]
                    == result.model_parameter_fingerprint
                ]
                if len(matches) != 1:
                    _integrity("PROFILED_CALIBRATION_RESULT_LEDGER_ROW_MISSING")
                row = matches[0]
                if (
                    row["checkpoint_id"] != result.checkpoint_id
                    or row["checkpoint_generation"]
                    != result.checkpoint_generation
                    or row["model_binding_sha256"]
                    != result.model_binding_sha256
                    or row["admission_artifact_sha256"]
                    != result.admission_artifact_sha256
                    or row["admission_artifact_byte_count"]
                    != result.admission_artifact_byte_count
                    or row["admission_material_sha256"]
                    != result.admission_material_sha256
                    or row["source_inventory_digest"]
                    != result.source_inventory_digest
                    or row["transaction_id"] != result.transaction_id
                    or row["receipt_sha256"] != result.append_receipt_sha256
                    or row["record_chain_sha256"] != result.record_chain_sha256
                    or row["head_anchor_sha256"] != result.head_anchor_sha256
                    or row["admitted_observed_at"]
                    != result.admitted_observed_at
                    or row["admission_artifact_json"] != result._artifact_json
                ):
                    _integrity("PROFILED_CALIBRATION_RESULT_LEDGER_MISMATCH")
                artifact = validate_profiled_research_calibration_admission_artifact_v1(
                    result._artifact_json.encode("ascii", errors="strict")
                )
                connection.commit()
                return artifact
            finally:
                connection.close()

    def _append_prepared(
        self, prepared: _PreparedAdmission
    ) -> DurablyAdmittedProfiledResearchCalibrationV1:
        aggregate_source_bytes = sum(
            row.outcome_artifact_byte_count for row in prepared.rows
        )
        if (
            aggregate_source_bytes <= 0
            or aggregate_source_bytes
            > _MAX_SOURCE_ARTIFACT_BYTES_PER_ADMISSION
        ):
            _validation(
                "PROFILED_CALIBRATION_SOURCE_ARTIFACT_AGGREGATE_CAP_EXCEEDED"
            )
        artifact = prepared.artifact
        artifact_bytes = prepared.artifact_bytes
        artifact_address = _expected_address(artifact_bytes)
        model = cast(dict[str, Any], artifact["model_binding"])
        partition = cast(dict[str, Any], artifact["partition"])
        inventory = cast(list[dict[str, Any]], artifact["source_outcome_inventory"])
        fingerprint = cast(str, model["model_parameter_fingerprint"])
        result_fingerprint: str | None = None
        transaction_id: str | None = None
        with _database_lease(
            self.path, exclusive=True, create_database=not self.path.exists()
        ) as created:
            connection = self._connect_write(created=created)
            try:
                connection.execute("BEGIN IMMEDIATE")
                _report, rows = self._verify_rows(
                    connection, require_head_catalog=True
                )
                existing = [
                    row
                    for row in rows
                    if row["model_parameter_fingerprint"] == fingerprint
                ]
                if existing:
                    row = existing[0]
                    if (
                        len(existing) != 1
                        or row["admission_artifact_sha256"]
                        != artifact_address.payload_sha256
                        or row["admission_artifact_json"]
                        != artifact_bytes.decode("ascii")
                    ):
                        raise ProfiledResearchCalibrationAdmissionV1ConflictError(
                            "PROFILED_CALIBRATION_MODEL_ALREADY_ADMITTED_WITH_DIFFERENT_EVIDENCE"
                        )
                    result_fingerprint = fingerprint
                    connection.commit()
                else:
                    source_hashes = [row.outcome_artifact_sha256 for row in prepared.rows]
                    source_ids = [row.row_id for row in prepared.rows]
                    reused = next(
                        (
                            found
                            for artifact_sha, row_id in zip(
                                source_hashes, source_ids, strict=True
                            )
                            if (
                                found := connection.execute(
                                    """
                                    SELECT row_id
                                    FROM profiled_calibration_source_rows
                                    WHERE outcome_artifact_sha256 = ? OR row_id = ?
                                    LIMIT 1
                                    """,
                                    (artifact_sha, row_id),
                                ).fetchone()
                            )
                            is not None
                        ),
                        None,
                    )
                    if reused is not None:
                        raise ProfiledResearchCalibrationAdmissionV1ConflictError(
                            "PROFILED_CALIBRATION_SOURCE_ROW_REUSE_FORBIDDEN"
                        )
                    source_row_bytes = sum(
                        len(
                            _canonical_bytes(
                                item,
                                reason=(
                                    "PROFILED_CALIBRATION_SOURCE_ROW_JSON_INVALID"
                                ),
                            )
                        )
                        for item in inventory
                    )
                    estimated_growth = 4 * (
                        len(artifact_bytes)
                        + source_row_bytes
                        + len(inventory) * 1024
                        + 64 * 1024
                    )
                    if self.path.stat().st_size + estimated_growth > _MAX_DATABASE_BYTES:
                        _integrity(
                            "PROFILED_CALIBRATION_DATABASE_CAPACITY_EXCEEDED"
                        )
                    for source in prepared.rows:
                        copied = _put_exact(self.store, source.outcome_artifact_bytes)
                        if (
                            copied.payload_sha256 != source.outcome_artifact_sha256
                            or copied.payload_byte_count
                            != source.outcome_artifact_byte_count
                        ):
                            _integrity(
                                "PROFILED_CALIBRATION_SOURCE_OUTCOME_COPY_MISMATCH"
                            )
                    published_artifact = _put_exact(self.store, artifact_bytes)
                    if published_artifact != artifact_address:
                        _integrity("PROFILED_CALIBRATION_ARTIFACT_COPY_MISMATCH")
                    sequence = len(rows) + 1
                    if sequence > _MAX_LEDGER_RECORDS:
                        _integrity(
                            "PROFILED_CALIBRATION_LEDGER_RESOURCE_BOUND_EXCEEDED"
                        )
                    previous_chain = (
                        cast(str, rows[-1]["record_chain_sha256"])
                        if rows
                        else _GENESIS_CHAIN_SHA256
                    )
                    previous_head = (
                        cast(str, rows[-1]["head_anchor_sha256"])
                        if rows
                        else _GENESIS_HEAD_SHA256
                    )
                    prior_clock = (
                        _clock(rows[-1]["admitted_observed_at"])
                        if rows
                        else _UTC_EPOCH
                    )
                    if prior_clock is None:
                        _integrity("PROFILED_CALIBRATION_INTERNAL_CLOCK_NOT_MONOTONIC")
                    latest_source_readback = _clock(
                        partition["latest_source_postcommit_readback_at"]
                    )
                    if latest_source_readback is None:
                        _integrity(
                            "PROFILED_CALIBRATION_SOURCE_DURABILITY_CLOCK_INVALID"
                        )
                    admitted_at = _next_observed_clock(
                        max(prior_clock, latest_source_readback)
                    )
                    transaction_id = hashlib.sha256(
                        artifact_bytes
                        + admitted_at.encode("ascii")
                        + secrets.token_bytes(32)
                    ).hexdigest()
                    inventory_digest = _sha256(inventory)
                    chain = _sha256(
                        self._record_chain_material(
                            sequence=sequence,
                            transaction_id=transaction_id,
                            admission_artifact_sha256=artifact_address.payload_sha256,
                            admission_material_sha256=cast(
                                str, artifact["admission_material_sha256"]
                            ),
                            source_inventory_digest=inventory_digest,
                            previous_chain_sha256=previous_chain,
                            admitted_observed_at=admitted_at,
                        )
                    )
                    receipt = self._append_receipt_contract(
                        transaction_id=transaction_id,
                        admission_artifact_sha256=artifact_address.payload_sha256,
                        record_chain_sha256=chain,
                        total_admissions=sequence,
                        committed_at=admitted_at,
                    )
                    receipt_json = _canonical_json(
                        receipt, reason="PROFILED_CALIBRATION_RECEIPT_JSON_INVALID"
                    )
                    receipt_sha = hashlib.sha256(
                        receipt_json.encode("ascii")
                    ).hexdigest()
                    head = self._head_anchor_contract(
                        sequence=sequence,
                        transaction_id=transaction_id,
                        admission_artifact_sha256=artifact_address.payload_sha256,
                        record_chain_sha256=chain,
                        append_receipt_sha256=receipt_sha,
                        previous_head_anchor_sha256=previous_head,
                        anchored_at=admitted_at,
                    )
                    head_json = _canonical_json(
                        head, reason="PROFILED_CALIBRATION_HEAD_JSON_INVALID"
                    )
                    head_address = _expected_address(head_json.encode("ascii"))
                    connection.execute(
                        """
                        INSERT INTO profiled_calibration_admissions VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            sequence,
                            model["checkpoint_id"],
                            model["checkpoint_generation"],
                            fingerprint,
                            model["model_binding_sha256"],
                            artifact_address.payload_sha256,
                            artifact_address.payload_byte_count,
                            artifact_address.relative_path,
                            artifact_bytes.decode("ascii"),
                            artifact["admission_material_sha256"],
                            inventory_digest,
                            partition["purged_train_row_digest"],
                            partition["purged_gap_row_digest"],
                            partition["untouched_forward_validation_row_digest"],
                            previous_chain,
                            chain,
                            transaction_id,
                            admitted_at,
                        ),
                    )
                    inventory_by_id = {
                        cast(str, item["row_id"]): item for item in inventory
                    }
                    connection.executemany(
                        """
                        INSERT INTO profiled_calibration_source_rows VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        [
                            (
                                source.row_id,
                                source.outcome_artifact_sha256,
                                source.outcome_artifact_byte_count,
                                f"sha256/{source.outcome_artifact_sha256[:2]}/"
                                f"{source.outcome_artifact_sha256}",
                                sequence,
                                fingerprint,
                                inventory_by_id[source.row_id]["source_role"],
                                source.decision_time,
                                source.actual_label_available_at,
                                _canonical_json(
                                    inventory_by_id[source.row_id],
                                    reason=(
                                        "PROFILED_CALIBRATION_SOURCE_ROW_JSON_INVALID"
                                    ),
                                ),
                            )
                            for source in prepared.rows
                        ],
                    )
                    connection.execute(
                        """
                        INSERT INTO profiled_calibration_append_receipts VALUES (
                            ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            transaction_id,
                            artifact_address.payload_sha256,
                            chain,
                            sequence,
                            receipt_sha,
                            receipt_json,
                            admitted_at,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO profiled_calibration_head_anchors VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            sequence,
                            transaction_id,
                            artifact_address.payload_sha256,
                            chain,
                            receipt_sha,
                            previous_head,
                            head_address.payload_sha256,
                            head_address.payload_byte_count,
                            head_address.relative_path,
                            head_json,
                            admitted_at,
                        ),
                    )
                    readback = connection.execute(
                        """
                        SELECT a.admission_artifact_sha256, a.record_chain_sha256,
                               r.receipt_sha256, h.head_anchor_sha256
                        FROM profiled_calibration_admissions AS a
                        JOIN profiled_calibration_append_receipts AS r
                            ON r.transaction_id = a.transaction_id
                        JOIN profiled_calibration_head_anchors AS h
                            ON h.transaction_id = a.transaction_id
                        WHERE a.transaction_id = ?
                        """,
                        (transaction_id,),
                    ).fetchone()
                    if (
                        readback is None
                        or tuple(readback)
                        != (
                            artifact_address.payload_sha256,
                            chain,
                            receipt_sha,
                            head_address.payload_sha256,
                        )
                    ):
                        _integrity("PROFILED_CALIBRATION_PRECOMMIT_READBACK_FAILED")
                    connection.commit()
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                    "PROFILED_CALIBRATION_DATABASE_WRITE_FAILED"
                ) from exc
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
            if transaction_id is not None:
                self._publish_head_catalog(transaction_id=transaction_id)
                self._verify_integrity_unleased()
        return self.open_admission(
            model_parameter_fingerprint=result_fingerprint or fingerprint
        )

    def recover_head_catalog(self) -> int:
        transactions: list[str] = []
        with _database_lease(
            self.path, exclusive=True, create_database=False
        ) as created:
            connection = self._connect_write(created=created)
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_rows(
                    connection, require_head_catalog=False
                )
                expected = {
                    cast(str, row["head_anchor_sha256"]): cast(
                        str, row["transaction_id"]
                    )
                    for row in rows
                }
                observed = self._observed_head_catalog_digests(
                    allow_empty_shards=True
                )
                if not observed.issubset(expected):
                    _integrity("PROFILED_CALIBRATION_HEAD_CATALOG_HAS_UNKNOWN_HEAD")
                ordered_heads = [
                    cast(str, row["head_anchor_sha256"]) for row in rows
                ]
                first_missing = next(
                    (
                        index
                        for index, digest in enumerate(ordered_heads)
                        if digest not in observed
                    ),
                    len(ordered_heads),
                )
                if any(
                    digest in observed for digest in ordered_heads[first_missing:]
                ):
                    _integrity(
                        "PROFILED_CALIBRATION_HEAD_CATALOG_INTERIOR_GAP"
                    )
                transactions = [
                    expected[digest] for digest in ordered_heads[first_missing:]
                ]
                connection.commit()
            finally:
                connection.close()
            for transaction in transactions:
                self._publish_head_catalog(transaction_id=transaction)
            self._verify_integrity_unleased()
        return len(transactions)


def _prepare_outcomes(
    outcomes: object,
) -> tuple[
    ProfiledResearchCalibrationEvaluationV1,
    _PreparedAdmission | None,
]:
    if type(outcomes) not in (list, tuple):
        _validation("PROFILED_CALIBRATION_EXACT_OUTCOME_SEQUENCE_REQUIRED")
    source = cast(Sequence[object], outcomes)
    if len(source) > _MAX_SOURCE_ROWS:
        _validation("PROFILED_CALIBRATION_SOURCE_RESOURCE_BOUND_EXCEEDED")
    eligible: list[_EvidenceRow] = []
    ineligible = 0
    for value in source:
        try:
            row = _validated_evidence_row(value)
        except ProfiledResearchFinalizedOutcomeV1Error as exc:
            raise ProfiledResearchCalibrationAdmissionV1IntegrityError(
                "PROFILED_CALIBRATION_SOURCE_OUTCOME_REVALIDATION_FAILED"
            ) from exc
        if row is None:
            ineligible += 1
        else:
            eligible.append(row)
    evaluation, partition, calibration, validation = _evaluate_rows(eligible)
    evaluation = replace(
        evaluation,
        total_outcomes=len(source),
        eligible_rows=len(eligible),
        ineligible_rows=ineligible,
    )
    if not evaluation.admission_ready:
        return evaluation, None
    if partition is None or calibration is None or validation is None:
        _integrity("PROFILED_CALIBRATION_READY_EVALUATION_INCOMPLETE")
    artifact, artifact_bytes = _prepare_admission_artifact(
        eligible,
        partition=partition,
        calibration_state=calibration,
        forward_validation=validation,
    )
    return (
        evaluation,
        _PreparedAdmission(
            rows=tuple(eligible),
            partition=partition,
            artifact=artifact,
            artifact_bytes=artifact_bytes,
        ),
    )


def evaluate_profiled_research_finalized_outcomes_for_calibration_v1(
    outcomes: object,
) -> ProfiledResearchCalibrationEvaluationV1:
    evaluation, _prepared = _prepare_outcomes(outcomes)
    return evaluation


def _validated_result(
    result: DurablyAdmittedProfiledResearchCalibrationV1,
) -> dict[str, Any]:
    if (
        type(result) is not DurablyAdmittedProfiledResearchCalibrationV1
        or result._construction_token is not _RESULT_TOKEN
        or type(result._ledger) is not ProfiledResearchCalibrationAdmissionLedgerV1
    ):
        _integrity("PROFILED_CALIBRATION_RESULT_FACTORY_REQUIRED")
    expected_seal = _factory_seal(
        sequence=result.sequence,
        model_parameter_fingerprint=result.model_parameter_fingerprint,
        admission_artifact_sha256=result.admission_artifact_sha256,
        transaction_id=result.transaction_id,
        append_receipt_sha256=result.append_receipt_sha256,
        record_chain_sha256=result.record_chain_sha256,
        head_anchor_sha256=result.head_anchor_sha256,
    )
    if (
        not hmac.compare_digest(result._factory_seal, expected_seal)
        or result.admission_artifact_address
        != SourcePayloadAddress(
            schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
            payload_sha256=result.admission_artifact_sha256,
            payload_byte_count=result.admission_artifact_byte_count,
            relative_path=(
                f"sha256/{result.admission_artifact_sha256[:2]}/"
                f"{result.admission_artifact_sha256}"
            ),
        )
    ):
        _integrity("PROFILED_CALIBRATION_RESULT_SEAL_INVALID")
    return result._ledger._validated_contract_for_result(result)


__all__ = [
    "PROFILED_RESEARCH_CALIBRATION_ADMISSION_LEDGER_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_CALIBRATION_ADMISSION_V1_CLASSIFICATION",
    "PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_SCHEMA_VERSION",
    "PROFILED_RESEARCH_CALIBRATION_ADMISSION_V2_CLASSIFICATION",
    "PROFILED_RESEARCH_CALIBRATION_UNCERTAINTY_METHOD",
    "DurablyAdmittedProfiledResearchCalibrationV1",
    "ProfiledResearchCalibrationAdmissionIntegrityV1",
    "ProfiledResearchCalibrationAdmissionLedgerV1",
    "ProfiledResearchCalibrationAdmissionV1ConflictError",
    "ProfiledResearchCalibrationAdmissionV1Error",
    "ProfiledResearchCalibrationAdmissionV1IntegrityError",
    "ProfiledResearchCalibrationAdmissionV1ValidationError",
    "ProfiledResearchCalibrationEvaluationV1",
    "evaluate_profiled_research_finalized_outcomes_for_calibration_v1",
    "validate_profiled_research_calibration_admission_artifact_v1",
]
