"""Side-effect-bounded resident observer for authenticated-ledger readiness.

This module is intentionally not a trainer.  It does not import or construct
Redis, CUDA, a model, legacy replay/prefetch, checkpoints, prediction
publishers, paper guards, or execution components.  Discovering a profiled
child candidate changes operator status only and can never transition this
process into training or claim that full sample authentication was performed.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

PROFILED_TRAINING_WAITING_STATUS_V1_SCHEMA_VERSION: Final = "profiled_training_waiting_status_v1"
PROFILED_TRAINING_WAITING_MODE_V1: Final = "WAITING_FOR_AUTHENTICATED_SAMPLES"
PROFILED_CHILD_CANDIDATES_AVAILABLE_STATE: Final = (
    "PROFILED_CHILD_CANDIDATES_AVAILABLE_OPERATOR_PROMOTION_REQUIRED"
)
WAITING_FOR_AUTHENTICATED_SAMPLES_STATE: Final = "WAITING_FOR_AUTHENTICATED_SAMPLES"
WAITING_PROBE_INCOMPLETE_STATE: Final = (
    "WAITING_FOR_AUTHENTICATED_SAMPLES_PROBE_INCOMPLETE_FAIL_CLOSED"
)
WAITING_PROBE_FAILED_STATE: Final = "WAITING_FOR_AUTHENTICATED_SAMPLES_PROBE_FAILED_CLOSED"
WAITING_STATUS_RELATIVE_PATH: Final = Path(
    "v2/runtime/native_cuda_trainer_waiting_for_authenticated_samples_status.json"
)
MAX_WAITING_SCAN_ROWS: Final = 250_000
_SAFE_REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$", re.ASCII)
_PROFILED_LINEAGE_KEY: Final = "authenticated_profiled_training_enrichment_v1"
_PROFILED_LINEAGE_SCHEMA: Final = "authenticated_profiled_training_enrichment_lineage_v1"
_PROFILED_LINEAGE_CLASSIFICATION: Final = (
    "AUTHENTICATED_PARENT_35_PLUS_CAUSAL_COST_4_TRAINING_EVIDENCE"
)
_PROFILED_LINEAGE_STATUS: Final = "STRICT_TRAINING_CANDIDATE_NO_SERVING_OR_EXECUTION_AUTHORITY"
_PROFILED_TRANSFORM_CONFIGURATION_SHA256: Final = (
    "3db3bcfa1ef4245a1d463d66ab39a67850f9fd56c592cd6ff0bca28d29f91fb5"
)
_CANONICAL_PROVENANCE_CLASSIFICATION: Final = "CANONICAL_RECEIPT_BACKED_V3"
_EXPECTED_SAMPLE_AUTHORIZATION: Final = {
    "trainer_admission_authorized": True,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}
_PHYSICAL_PROFILED_FEATURE_COUNT: Final = 39
_PARENT_PROFILED_FEATURE_COUNT: Final = 35
_AUXILIARY_COST_FEATURE_NAMES: Final = (
    "fee_bps",
    "spread_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
)
_PARENT_PROFILED_SCHEMA: Final = "profiled_model_feature_snapshot_record_v1"
_PARENT_PROFILED_CLASSIFICATION: Final = "AUTHENTICATED_OHLCV_MODEL_ONLY_LEDGER_V3_UNWIRED"
_PARENT_PROFILED_STATUS: Final = "VALIDATED_QUARANTINED_NO_RUNTIME_AUTHORITY"
_EXPECTED_PARENT_AUTHORIZATION: Final = {
    "feature_snapshot_published": False,
    "consumer_eligible": False,
    "trainer_admission_authorized": False,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}


class ProfiledTrainingWaitingRuntimeV1Error(RuntimeError):
    """The waiting observer could not preserve its fail-closed contract."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _validate_lexical_absolute_path(value: Path, *, field: str) -> Path:
    if (
        type(value) is not type(Path())
        or not value.is_absolute()
        or ".." in value.parts
        or "\x00" in str(value)
    ):
        raise ProfiledTrainingWaitingRuntimeV1Error(f"{field}_invalid")
    return value


def _require_trusted_directory(path: Path, *, reason: str) -> None:
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error(reason) from exc
    if not stat.S_ISDIR(observed.st_mode) or observed.st_uid != os.geteuid():
        raise ProfiledTrainingWaitingRuntimeV1Error(reason)


@dataclass(frozen=True, slots=True)
class ProfiledTrainingWaitingConfigV1:
    """Immutable configuration for the observation-only resident process."""

    repo_root: Path
    ledger_path: Path
    trusted_cost_store_root: Path
    interval_seconds: float
    scan_limit: int

    def __post_init__(self) -> None:
        repo_root = _validate_lexical_absolute_path(self.repo_root, field="repo_root")
        _validate_lexical_absolute_path(self.ledger_path, field="ledger_path")
        _validate_lexical_absolute_path(
            self.trusted_cost_store_root,
            field="trusted_cost_store_root",
        )
        _require_trusted_directory(repo_root, reason="repo_root_not_trusted_directory")
        if (
            type(self.interval_seconds) not in {int, float}
            or isinstance(self.interval_seconds, bool)
            or not math.isfinite(float(self.interval_seconds))
            or self.interval_seconds <= 0
        ):
            raise ProfiledTrainingWaitingRuntimeV1Error("interval_seconds_invalid")
        if type(self.scan_limit) is not int or not 0 < self.scan_limit <= MAX_WAITING_SCAN_ROWS:
            raise ProfiledTrainingWaitingRuntimeV1Error("scan_limit_invalid")
        status_parent = self.status_path.parent
        _require_trusted_directory(
            repo_root / "v2",
            reason="waiting_status_path_component_not_trusted_directory",
        )
        _require_trusted_directory(
            status_parent,
            reason="waiting_status_parent_not_trusted_directory",
        )

    @property
    def status_path(self) -> Path:
        return self.repo_root / WAITING_STATUS_RELATIVE_PATH


@dataclass(frozen=True, slots=True)
class AuthenticatedSampleProbeV1:
    """Read-only integrity and profiled-child readiness observation."""

    authenticated_sample_count: int | None
    strict_training_eligible_row_count: int
    profiled_child_candidate_count: int
    excluded_record_count: int
    exclusions_by_reason: Mapping[str, int]
    integrity_verified_record_count: int
    integrity_verified_append_receipt_count: int
    integrity_observation_sha256: str
    archive_chain_sha256: str
    ledger_integrity_verified: bool
    full_sample_authentication_performed: bool
    scan_complete: bool
    runtime_scalability_status: str


def _canonical_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_materialized_read_sidecars(ledger_path: Path) -> None:
    """Prevent a read cycle from creating SQLite WAL coordination artifacts."""

    for path, reason in (
        (ledger_path, "ledger_main_file_not_materialized"),
        (Path(f"{ledger_path}-wal"), "ledger_wal_sidecar_not_materialized"),
        (Path(f"{ledger_path}-shm"), "ledger_shm_sidecar_not_materialized"),
    ):
        try:
            observed = os.lstat(path)
        except OSError as exc:
            raise ProfiledTrainingWaitingRuntimeV1Error(reason) from exc
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_uid != os.geteuid()
        ):
            raise ProfiledTrainingWaitingRuntimeV1Error(reason)


def _strict_prior_observation(value: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ProfiledTrainingWaitingRuntimeV1Error("training_observed_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error("training_observed_at_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProfiledTrainingWaitingRuntimeV1Error("training_observed_at_invalid")
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ProfiledTrainingWaitingRuntimeV1Error("training_observed_at_invalid")
    try:
        strict_prior = normalized - timedelta(microseconds=1)
    except OverflowError as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error("training_observed_at_invalid") from exc
    return strict_prior.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _profiled_child_candidate_rejection(
    item: Any,
    *,
    ledger: Any,
) -> str | None:
    record = item.record
    envelope = record.get("frozen_envelope") if type(record) is dict else None
    if type(envelope) is not dict:
        return "STRICT_ROW_ENVELOPE_INVALID"
    lineage = envelope.get("source_lineage_material")
    attestation = lineage.get(_PROFILED_LINEAGE_KEY) if type(lineage) is dict else None
    if type(attestation) is not dict:
        return "STRICT_ROW_NOT_PROFILED_ENRICHMENT"
    if (
        attestation.get("transform_configuration_sha256")
        != _PROFILED_TRANSFORM_CONFIGURATION_SHA256
    ):
        return "PROFILED_CHILD_UNSUPPORTED_TRANSFORM_CONFIGURATION"
    authorization = attestation.get("authorization")
    names = envelope.get("ordered_feature_names")
    values = envelope.get("feature_values")
    labels = envelope.get("ordered_feature_source_labels")
    receipt_roots = envelope.get("feature_source_receipt_sha256s")
    if (
        attestation.get("schema_version") != _PROFILED_LINEAGE_SCHEMA
        or attestation.get("classification") != _PROFILED_LINEAGE_CLASSIFICATION
        or attestation.get("status") != _PROFILED_LINEAGE_STATUS
        or attestation.get("physical_feature_count") != _PHYSICAL_PROFILED_FEATURE_COUNT
        or authorization != _EXPECTED_SAMPLE_AUTHORIZATION
        or envelope.get("provenance_classification")
        != _CANONICAL_PROVENANCE_CLASSIFICATION
        or envelope.get("legacy_v1_snapshot_id") is not None
        or envelope.get("strict_training_eligible") is not True
        or envelope.get("strict_training_ineligibility_reasons") != []
        or envelope.get("temporal_rejection_reasons") != []
        or type(names) is not list
        or len(names) != _PHYSICAL_PROFILED_FEATURE_COUNT
        or type(values) is not list
        or len(values) != _PHYSICAL_PROFILED_FEATURE_COUNT
        or type(labels) is not list
        or len(labels) != _PHYSICAL_PROFILED_FEATURE_COUNT
        or type(receipt_roots) is not list
        or len(receipt_roots) != _PHYSICAL_PROFILED_FEATURE_COUNT
        or envelope.get("missing_mask") != [0] * _PHYSICAL_PROFILED_FEATURE_COUNT
        or envelope.get("stale_mask") != [0] * _PHYSICAL_PROFILED_FEATURE_COUNT
        or envelope.get("source_availability_mask") != [1] * _PHYSICAL_PROFILED_FEATURE_COUNT
    ):
        return "PROFILED_CHILD_CANDIDATE_CONTRACT_INVALID"
    parent_binding = attestation.get("parent_model_record_binding")
    parent_id = parent_binding.get("durable_snapshot_id") if type(parent_binding) is dict else None
    if type(parent_id) is not str or not parent_id:
        return "PROFILED_CHILD_PARENT_BINDING_INVALID"
    parent = ledger.get_snapshot(parent_id)
    if parent is None:
        return "PROFILED_CHILD_PARENT_MISSING"
    parent_record = parent.record
    parent_envelope = parent_record.get("frozen_envelope") if type(parent_record) is dict else None
    if type(parent_envelope) is not dict:
        return "PROFILED_CHILD_PARENT_BINDING_INVALID"
    parent_names = parent_envelope.get("ordered_feature_names")
    parent_values = parent_envelope.get("feature_values")
    parent_labels = parent_envelope.get("ordered_feature_source_labels")
    parent_roots = parent_envelope.get("feature_source_receipt_sha256s")
    parent_lineage = parent_envelope.get("source_lineage_material")
    if (
        parent.sequence + 1 != item.sequence
        or parent.append_transaction_id != item.append_transaction_id
        or parent.append_receipt_sha256 != item.append_receipt_sha256
        or parent.postcommit_receipt_sha256 != item.postcommit_receipt_sha256
        or parent.postcommit_readback_at != item.postcommit_readback_at
    ):
        return "PROFILED_CHILD_PARENT_SHARED_APPEND_INVALID"
    if (
        type(parent_names) is not list
        or len(parent_names) != _PARENT_PROFILED_FEATURE_COUNT
        or type(parent_values) is not list
        or len(parent_values) != _PARENT_PROFILED_FEATURE_COUNT
        or type(parent_labels) is not list
        or len(parent_labels) != _PARENT_PROFILED_FEATURE_COUNT
        or type(parent_roots) is not list
        or len(parent_roots) != _PARENT_PROFILED_FEATURE_COUNT
        or type(parent_lineage) is not dict
        or parent_lineage.get("schema_version") != _PARENT_PROFILED_SCHEMA
        or parent_lineage.get("classification") != _PARENT_PROFILED_CLASSIFICATION
        or parent_lineage.get("status") != _PARENT_PROFILED_STATUS
        or parent_lineage.get("physical_model_feature_count") != _PARENT_PROFILED_FEATURE_COUNT
        or parent_lineage.get("transform_configuration_sha256")
        != _PROFILED_TRANSFORM_CONFIGURATION_SHA256
        or parent_lineage.get("authorization") != _EXPECTED_PARENT_AUTHORIZATION
        or parent_envelope.get("provenance_classification")
        != _CANONICAL_PROVENANCE_CLASSIFICATION
        or parent_envelope.get("legacy_v1_snapshot_id") is not None
        or parent_envelope.get("strict_training_eligible") is not False
        or parent_envelope.get("missing_mask") != [0] * _PARENT_PROFILED_FEATURE_COUNT
        or parent_envelope.get("stale_mask") != [0] * _PARENT_PROFILED_FEATURE_COUNT
        or parent_envelope.get("source_availability_mask") != [1] * _PARENT_PROFILED_FEATURE_COUNT
        or names != [*parent_names, *_AUXILIARY_COST_FEATURE_NAMES]
        or values[:_PARENT_PROFILED_FEATURE_COUNT] != parent_values
        or labels[:_PARENT_PROFILED_FEATURE_COUNT] != parent_labels
        or receipt_roots[:_PARENT_PROFILED_FEATURE_COUNT] != parent_roots
        or any(
            envelope.get(field) != parent_envelope.get(field)
            for field in (
                "symbol",
                "timeframe",
                "tensor_decision_time",
                "masa_feature_cutoff",
                "ppo_decision_time",
            )
        )
    ):
        return "PROFILED_CHILD_PARENT_BIT_IDENTITY_INVALID"
    return None


def inspect_authenticated_profiled_samples_v1(
    config: ProfiledTrainingWaitingConfigV1,
    *,
    training_observed_at: str,
) -> AuthenticatedSampleProbeV1:
    """Run a minimal read-only integrity/profile-child readiness observation.

    Full sample authentication remains an offline/operator promotion gate.  It
    is deliberately not imported here because the current factory loader's
    sample-identity dependency executes the CUDA trainer package initializer.
    """

    from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
        MAX_QUERY_ROWS,
        DurableFeatureSnapshotLedger,
        stable_sha256,
    )

    _require_materialized_read_sidecars(config.ledger_path)
    strict_prior = _strict_prior_observation(training_observed_at)
    ledger = DurableFeatureSnapshotLedger(config.ledger_path)
    before_report = ledger.verify_integrity_streaming()
    if before_report.integrity_verified is not True:
        raise ProfiledTrainingWaitingRuntimeV1Error("ledger_integrity_unverified")
    after_sequence = 0
    scanned_count = 0
    exclusions: Counter[str] = Counter()
    candidate_count = 0
    while scanned_count < config.scan_limit:
        page_limit = min(MAX_QUERY_ROWS, config.scan_limit - scanned_count)
        page = ledger.query_fixed_cutoff(
            decision_time_cutoff=strict_prior,
            training_observed_at=strict_prior,
            limit=page_limit,
            after_sequence=after_sequence,
        )
        if not page:
            break
        for item in page:
            rejection = _profiled_child_candidate_rejection(item, ledger=ledger)
            if rejection is None:
                candidate_count += 1
            else:
                exclusions[rejection] += 1
        page_count = len(page)
        scanned_count += page_count
        after_sequence = page[-1].sequence
        del item
        del page
        if page_count < page_limit:
            break
    scan_complete = True
    if scanned_count == config.scan_limit:
        scan_complete = not bool(
            ledger.query_fixed_cutoff(
                decision_time_cutoff=strict_prior,
                training_observed_at=strict_prior,
                limit=1,
                after_sequence=after_sequence,
            )
        )
    after_report = ledger.verify_integrity_streaming()
    if before_report != after_report:
        raise ProfiledTrainingWaitingRuntimeV1Error("ledger_integrity_frontier_moved_during_probe")
    integrity_material = {
        "schema_version": PROFILED_TRAINING_WAITING_STATUS_V1_SCHEMA_VERSION,
        "ledger_path": str(config.ledger_path),
        "training_observed_at": training_observed_at,
        "strict_prior_observation": strict_prior,
        "verified_records": before_report.verified_records,
        "verified_append_receipts": before_report.verified_append_receipts,
        "verified_postcommit_receipts": before_report.verified_postcommit_receipts,
        "verified_projection_outbox_rows": (before_report.verified_projection_outbox_rows),
        "total_record_bytes": before_report.total_record_bytes,
        "archive_chain_sha256": before_report.archive_chain_sha256,
        "scanned_strict_row_count": scanned_count,
        "scan_complete": scan_complete,
        "profiled_child_candidate_count": candidate_count,
        "full_sample_authentication_performed": False,
    }
    return AuthenticatedSampleProbeV1(
        authenticated_sample_count=None,
        strict_training_eligible_row_count=scanned_count,
        profiled_child_candidate_count=candidate_count,
        excluded_record_count=sum(exclusions.values()),
        exclusions_by_reason=dict(sorted(exclusions.items())),
        integrity_verified_record_count=before_report.verified_records,
        integrity_verified_append_receipt_count=before_report.verified_append_receipts,
        integrity_observation_sha256=stable_sha256(integrity_material),
        archive_chain_sha256=before_report.archive_chain_sha256,
        ledger_integrity_verified=True,
        full_sample_authentication_performed=False,
        scan_complete=scan_complete,
        runtime_scalability_status=(
            "MINIMAL_READINESS_PROBE_NO_FULL_SAMPLE_AUTHENTICATION_NO_RUNTIME_WIRING"
        ),
    )


def _safe_probe_error(exc: Exception) -> dict[str, Any]:
    raw_reasons = getattr(exc, "reasons", ())
    reasons: list[str] = []
    if isinstance(raw_reasons, tuple | list):
        for value in raw_reasons[:32]:
            if type(value) is str and _SAFE_REASON_RE.fullmatch(value):
                reasons.append(value)
    return {
        "error_type": type(exc).__name__,
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _authority_payload() -> dict[str, Any]:
    return {
        "trainer_admission_authorized": False,
        "training_loop_active": False,
        "continuous_training_enabled": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "execution_authorized": False,
        "checkpoint_authorized": False,
        "model_authorized": False,
        "checkpoint_id": None,
        "checkpoint_path": None,
        "model_id": None,
        "runtime_wired": False,
        "automatic_transition_authorized": False,
    }


def build_profiled_training_waiting_status_v1(
    config: ProfiledTrainingWaitingConfigV1,
    *,
    training_observed_at: str,
    probe: Callable[..., AuthenticatedSampleProbeV1] = inspect_authenticated_profiled_samples_v1,
) -> dict[str, Any]:
    """Build truthful status while converting every probe failure into a hold."""

    probe_result: AuthenticatedSampleProbeV1 | None = None
    probe_error: dict[str, Any] | None = None
    try:
        probe_result = probe(config, training_observed_at=training_observed_at)
    except Exception as exc:  # Fail closed and remain resident for operator diagnosis.
        probe_error = _safe_probe_error(exc)

    if probe_result is None:
        state = WAITING_PROBE_FAILED_STATE
        promotion_required = False
    elif not probe_result.scan_complete:
        state = WAITING_PROBE_INCOMPLETE_STATE
        promotion_required = False
    elif probe_result.profiled_child_candidate_count > 0:
        state = PROFILED_CHILD_CANDIDATES_AVAILABLE_STATE
        promotion_required = True
    else:
        state = WAITING_FOR_AUTHENTICATED_SAMPLES_STATE
        promotion_required = False

    authenticated_sample_count = (
        probe_result.authenticated_sample_count if probe_result is not None else None
    )

    inventory = {
        "probe_succeeded": probe_result is not None,
        "probe_error": probe_error,
        "authenticated_sample_count": authenticated_sample_count,
        "authenticated_samples_available": (
            authenticated_sample_count > 0 if authenticated_sample_count is not None else None
        ),
        "strict_training_eligible_row_count": (
            probe_result.strict_training_eligible_row_count if probe_result is not None else None
        ),
        "profiled_child_candidate_count": (
            probe_result.profiled_child_candidate_count if probe_result is not None else 0
        ),
        "profiled_child_candidates_available": (
            probe_result.profiled_child_candidate_count > 0 if probe_result is not None else False
        ),
        "strict_training_eligible_row_count_semantics": (
            "FIXED_CUTOFF_STRICT_ROWS_EXACT_WHEN_SCAN_COMPLETE_OTHERWISE_LOWER_BOUND"
        ),
        "strict_training_eligible_row_count_exact": (
            probe_result.scan_complete if probe_result is not None else False
        ),
        "profiled_child_candidate_count_semantics": (
            "EXACT_39_STRUCTURAL_CONTRACT_AND_SHARED_PARENT_APPEND_BIT_IDENTITY_"
            "FULL_COST_CAS_AUTHENTICATION_NOT_PERFORMED"
        ),
        "operator_promotion_required": promotion_required,
        "excluded_record_count": (
            probe_result.excluded_record_count if probe_result is not None else 0
        ),
        "exclusions_by_reason": (
            dict(probe_result.exclusions_by_reason) if probe_result is not None else {}
        ),
        "integrity_verified_record_count": (
            probe_result.integrity_verified_record_count if probe_result is not None else None
        ),
        "integrity_verified_append_receipt_count": (
            probe_result.integrity_verified_append_receipt_count
            if probe_result is not None
            else None
        ),
        "integrity_observation_sha256": (
            probe_result.integrity_observation_sha256 if probe_result is not None else None
        ),
        "archive_chain_sha256": (
            probe_result.archive_chain_sha256 if probe_result is not None else None
        ),
        "ledger_integrity_verified": (
            probe_result.ledger_integrity_verified if probe_result is not None else False
        ),
        "full_sample_authentication_performed": (
            probe_result.full_sample_authentication_performed if probe_result is not None else False
        ),
        "authenticated_sample_count_semantics": (
            "NOT_EVALUATED_IN_RESIDENT_WAITING_MODE"
            if probe_result is None or probe_result.full_sample_authentication_performed is not True
            else "FULL_HARDENED_AUTHENTICATION"
        ),
        "scan_complete": probe_result.scan_complete if probe_result is not None else False,
        "runtime_scalability_status": (
            probe_result.runtime_scalability_status if probe_result is not None else None
        ),
    }
    try:
        producer_store_stat = os.lstat(config.trusted_cost_store_root)
    except OSError:
        producer_materialized = False
    else:
        producer_materialized = (
            stat.S_ISDIR(producer_store_stat.st_mode) and producer_store_stat.st_uid == os.geteuid()
        )
    return {
        "schema_version": PROFILED_TRAINING_WAITING_STATUS_V1_SCHEMA_VERSION,
        "generated_at": training_observed_at,
        "mode": PROFILED_TRAINING_WAITING_MODE_V1,
        "state": state,
        "service_process_active": True,
        **_authority_payload(),
        "operator_promotion_required": promotion_required,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "authenticated_sample_inventory": inventory,
        "authenticated_sample_producer": {
            "trusted_cost_store_root": str(config.trusted_cost_store_root),
            "materialized": producer_materialized,
            "state": ("MATERIALIZED" if producer_materialized else "NOT_YET_MATERIALIZED"),
        },
        "side_effect_contract": {
            "ledger_access": "READ_ONLY_MINIMAL_INTEGRITY_AND_PROFILE_CHILD_READINESS_PROBE",
            "full_sample_authentication_runtime_authorized": False,
            "permitted_write_path": str(config.status_path),
            "redis_access_authorized": False,
            "cuda_or_model_construction_authorized": False,
            "legacy_prefetch_authorized": False,
            "checkpoint_access_authorized": False,
            "publisher_access_authorized": False,
            "paper_guard_access_authorized": False,
        },
    }


def write_profiled_training_waiting_status_v1(
    config: ProfiledTrainingWaitingConfigV1,
    payload: Mapping[str, Any],
) -> None:
    """Atomically replace the one dedicated local waiting-status artifact."""

    path = config.status_path
    parent = path.parent
    try:
        parent_stat = os.lstat(parent)
    except OSError as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error("waiting_status_parent_unavailable") from exc
    if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
        raise ProfiledTrainingWaitingRuntimeV1Error("waiting_status_parent_not_trusted_directory")
    try:
        target_stat = os.lstat(path)
    except FileNotFoundError:
        target_stat = None
    except OSError as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error("waiting_status_target_invalid") from exc
    if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
        raise ProfiledTrainingWaitingRuntimeV1Error("waiting_status_target_not_regular_file")

    try:
        encoded = (
            json.dumps(
                dict(payload),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error(
            "waiting_status_payload_not_canonical_json"
        ) from exc

    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ProfiledTrainingWaitingRuntimeV1Error("waiting_status_atomic_write_failed") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def run_profiled_training_waiting_cycle_v1(
    config: ProfiledTrainingWaitingConfigV1,
    *,
    probe: Callable[..., AuthenticatedSampleProbeV1] = inspect_authenticated_profiled_samples_v1,
    clock: Callable[[], str] = _canonical_utc_now,
    writer: Callable[[ProfiledTrainingWaitingConfigV1, Mapping[str, Any]], None] = (
        write_profiled_training_waiting_status_v1
    ),
) -> dict[str, Any]:
    """Run one observer cycle and mutate only the dedicated status artifact."""

    observed_at = clock()
    payload = build_profiled_training_waiting_status_v1(
        config,
        training_observed_at=observed_at,
        probe=probe,
    )
    writer(config, payload)
    return payload


def run_profiled_training_waiting_loop_v1(
    config: ProfiledTrainingWaitingConfigV1,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Remain in waiting mode until the service manager stops the process."""

    try:
        while True:
            run_profiled_training_waiting_cycle_v1(config)
            sleep(float(config.interval_seconds))
    except KeyboardInterrupt:
        return 0


__all__ = [
    "AuthenticatedSampleProbeV1",
    "MAX_WAITING_SCAN_ROWS",
    "PROFILED_CHILD_CANDIDATES_AVAILABLE_STATE",
    "PROFILED_TRAINING_WAITING_MODE_V1",
    "PROFILED_TRAINING_WAITING_STATUS_V1_SCHEMA_VERSION",
    "ProfiledTrainingWaitingConfigV1",
    "ProfiledTrainingWaitingRuntimeV1Error",
    "WAITING_FOR_AUTHENTICATED_SAMPLES_STATE",
    "WAITING_PROBE_FAILED_STATE",
    "WAITING_PROBE_INCOMPLETE_STATE",
    "WAITING_STATUS_RELATIVE_PATH",
    "build_profiled_training_waiting_status_v1",
    "inspect_authenticated_profiled_samples_v1",
    "run_profiled_training_waiting_cycle_v1",
    "run_profiled_training_waiting_loop_v1",
    "write_profiled_training_waiting_status_v1",
]
