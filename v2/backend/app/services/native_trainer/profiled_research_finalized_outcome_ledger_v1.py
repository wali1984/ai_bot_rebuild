"""Durable PIT maturation for profiled research shadow hypotheses.

This module consumes only an exact, durably committed ex-ante hypothesis and
the canonical finalized Binance 5-minute label archive.  It derives one
selected-action profitability observation from the authenticated decision-time
mid and the portable explicit-cost closure, copies the exact finalized candle
path into immutable CAS, and registers the outcome in an append-only ledger.

The result is calibration *evidence*, not calibration admission.  No trainer,
optimizer, publisher, serving, PAPER, live, exchange, order, deployment, or
execution authority is granted here.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    ARCHIVE_SCHEMA_VERSION,
    LABEL_PATH_PROOF_SCHEMA_VERSION,
    RANGE_PROOF_SCHEMA_VERSION,
    Canonical5mValidationError,
    DurableCanonical5mLabelArchive,
    validate_canonical_finalized_5m_candle,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    canonical_json as canonical_candle_json,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    stable_sha256 as archive_stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.locally_authenticated_profiled_research_inference_v1 import (  # noqa: E501
    LocallyAuthenticatedProfiledResearchInferenceV1Error,
    validate_portable_profiled_research_raw_inference_v2_payload,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_commitment_v1 import (  # noqa: E501
    DurablyCommittedProfiledResearchShadowHypothesisV1,
    ProfiledResearchShadowHypothesisCommitmentV1Error,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    counterfactual_excursion_bps,
)

PROFILED_RESEARCH_FINALIZED_OUTCOME_LEDGER_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_ledger_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_CLASSIFICATION: Final = (
    "FINALIZED_PROFILED_RESEARCH_SELECTED_ACTION_OUTCOME_NO_AUTHORITY_V1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_APPEND_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_append_receipt_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_POSTCOMMIT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_postcommit_readback_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_HEAD_ANCHOR_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_head_anchor_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_calibration_row_v1"
)
PROFILED_RESEARCH_FINALIZED_OUTCOME_MODEL_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_research_finalized_outcome_model_binding_v1"
)

_APPLICATION_ID = 0x50464F4C
_USER_VERSION = 1
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_LEDGER_RECORDS = 65_536
_MAX_LEDGER_DATABASE_BYTES = 512 * 1024 * 1024
_MAX_LEDGER_AGGREGATE_JSON_BYTES = 128 * 1024 * 1024
_MAX_LABEL_PATH_ROWS = 8
_GENESIS_CHAIN_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_FINALIZED_OUTCOME_LEDGER_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_GENESIS_HEAD_ANCHOR_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_FINALIZED_OUTCOME_HEAD_ANCHOR_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SHA256_SHARD_RE = re.compile(r"^[0-9a-f]{2}$", re.ASCII)
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$", re.ASCII)
_RESULT_TOKEN = object()
_LEASE_TOKEN = object()
_RESULT_SEAL_KEY = secrets.token_bytes(32)
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_AUTHORIZATION: Final = {
    "consumer_eligible": False,
    "trainer_admission_authorized": False,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
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
    "runtime_wired": False,
}

_ARTIFACT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "hypothesis_binding",
        "model_binding",
        "model_binding_sha256",
        "maturation_observed_at",
        "actual_label_available_at",
        "label_source_binding",
        "label_source_binding_sha256",
        "label_path_proof_at_maturation",
        "label_candle_inventory",
        "economics",
        "calibration_row",
        "outcome_material_sha256",
        "status",
        "authorization",
        "research_only",
    }
)
_MODEL_BINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "checkpoint_id",
        "checkpoint_generation",
        "checkpoint_generated_at",
        "checkpoint_weight_sha256",
        "model_id",
        "model_parameter_fingerprint",
        "candidate_contract_sha256",
        "candidate_authorization_receipt_sha256",
        "candidate_code_release_sha",
        "confidence_head_schema_version",
        "confidence_head_actions",
        "profitability_label_semantics",
        "raw_inference_binding_sha256",
        "hypothesis_artifact_sha256",
    }
)
_HYPOTHESIS_BINDING_FIELDS: Final = frozenset(
    {
        "hypothesis_identity_sha256",
        "hypothesis_artifact_sha256",
        "hypothesis_artifact_byte_count",
        "hypothesis_artifact_cas_address",
        "cost_closure_cas_address",
        "cost_evidence_artifact_sha256",
        "raw_inference_binding_sha256",
        "hypothesis_material_sha256",
        "symbol",
        "durable_snapshot_id",
        "decision_time",
        "hypothesis_generated_at",
        "label_earliest_available_at",
        "holding_horizon_seconds",
        "commitment_transaction_id",
        "commitment_append_receipt_sha256",
        "commitment_postcommit_receipt_sha256",
        "commitment_sha256",
        "commitment_record_chain_sha256",
        "commit_observed_at",
        "commit_prepared_at",
        "postcommit_observed_at",
        "postcommit_readback_at",
    }
)
_LABEL_SOURCE_BINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "archive_schema_version",
        "archive_path",
        "symbol",
        "decision_time",
        "maturation_observed_at",
        "horizon_seconds",
        "start_close_time_ms",
        "end_close_time_ms",
        "actual_label_available_at",
        "candle_inventory",
        "append_receipt_sha256s",
        "postcommit_readback_receipt_sha256s",
        "receipt_commit_cutoff_required",
        "future_available_candle_used",
    }
)
_LABEL_CANDLE_INVENTORY_FIELDS: Final = frozenset(
    {
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "available_at_ms",
        "raw_payload_hash",
        "market_fact_sha256",
        "content_sha256",
        "candle_cas_address",
    }
)
_ECONOMICS_FIELDS: Final = frozenset(
    {
        "schema_version",
        "basis",
        "entry_price",
        "exit_price",
        "raw_market_return_bps",
        "cost_feature_names",
        "cost_feature_values",
        "fee_bps_per_side",
        "full_round_trip_spread_bps",
        "expected_slippage_bps_per_side",
        "signed_horizon_funding_bps",
        "base_execution_cost_bps",
        "long_total_cost_bps",
        "short_total_cost_bps",
        "conservative_total_cost_bps",
        "counterfactual_long_net_pnl_bps",
        "counterfactual_short_net_pnl_bps",
        "counterfactual_hold_net_pnl_bps",
        "selected_action",
        "selected_action_net_pnl_bps",
        "selected_action_profitable",
        "selected_action_max_favorable_excursion_bps",
        "selected_action_max_adverse_excursion_bps",
        "postdecision_excursion_candle_count",
        "predecision_overlap_excluded_from_excursion",
        "diagnostic_best_after_cost_action",
        "selected_action_matches_diagnostic_best",
        "model_expected_move_bps",
        "expected_move_error_bps",
        "model_selected_action_probability",
        "profitability_uses_strict_positive_zero_boundary",
        "static_market_threshold_used",
        "hindsight_action_substituted_for_selected_action",
        "funding_sign_convention",
    }
)
_CALIBRATION_ROW_FIELDS: Final = frozenset(
    {
        "schema_version",
        "row_id",
        "label_semantics",
        "eligible",
        "selected_directional_action",
        "raw_probability",
        "observed_strictly_positive_net_pnl",
        "raw_brier_contribution",
        "selected_action_net_pnl_bps",
        "selected_action_preserved_ex_ante",
        "hindsight_action_substitution_used",
        "fit_partition",
        "calibration_input_authorized",
        "model_binding_sha256",
        "model_parameter_fingerprint",
        "checkpoint_id",
        "checkpoint_generation",
    }
)

_STATUS: Final = {
    "canonical_finalized_label_path_verified": True,
    "archive_receipts_committed_by_observation": True,
    "portable_explicit_cost_closure_verified": True,
    "selected_action_outcome_materialized": True,
    "calibration_row_materialized_when_directional": True,
    "maturity_ledger_registration_required": True,
    "trainer_admission_authorized": False,
    "calibration_input_authorized": False,
}

_TABLE_NAMES: Final = frozenset(
    {
        "profiled_finalized_outcome_metadata",
        "profiled_finalized_outcomes",
        "profiled_finalized_outcome_append_receipts",
        "profiled_finalized_outcome_postcommit_receipts",
        "profiled_finalized_outcome_head_anchors",
    }
)
_INDEX_NAMES: Final = frozenset(
    {
        "profiled_finalized_outcome_label_available",
        "profiled_finalized_outcome_decision_time",
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
        PROFILED_RESEARCH_FINALIZED_OUTCOME_LEDGER_V1_SCHEMA_VERSION
    ),
    "retention_policy": "APPEND_ONLY_NO_AUTOMATIC_PRUNING",
    "automatic_pruning_enabled": "false",
    "runtime_wired": "false",
    "trainer_authority": "false",
    "calibration_authority": "false",
}


class ProfiledResearchFinalizedOutcomeV1Error(RuntimeError):
    """Stable, payload-safe base error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProfiledResearchFinalizedOutcomeV1ValidationError(
    ProfiledResearchFinalizedOutcomeV1Error
):
    """A caller value or not-yet-mature label path is invalid."""


class ProfiledResearchFinalizedOutcomeV1IntegrityError(
    ProfiledResearchFinalizedOutcomeV1Error
):
    """Durable bytes, source lineage, schema, or receipts are invalid."""


class ProfiledResearchFinalizedOutcomeV1ConflictError(
    ProfiledResearchFinalizedOutcomeV1Error
):
    """A hypothesis identity is already bound to a different outcome."""


class ProfiledResearchFinalizedOutcomeWriterLeaseError(
    ProfiledResearchFinalizedOutcomeV1Error
):
    """The exact writer path/inode lease is absent, stale, or contended."""


def _validation(reason: str) -> NoReturn:
    raise ProfiledResearchFinalizedOutcomeV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise ProfiledResearchFinalizedOutcomeV1IntegrityError(reason) from None


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


def _sha256(value: object, *, reason: str = "PROFILED_OUTCOME_JSON_INVALID") -> str:
    return hashlib.sha256(_canonical_bytes(value, reason=reason)).hexdigest()


def _parse_exact_object(payload: bytes | str, *, reason: str) -> dict[str, Any]:
    try:
        raw = payload.encode("ascii", errors="strict") if type(payload) is str else payload
    except (AttributeError, UnicodeError):
        _integrity(reason)
    if type(raw) is not bytes or not raw or len(raw) > _MAX_JSON_BYTES:
        _integrity(reason)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _integrity(reason)
            result[key] = value
        return result

    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: _integrity(reason),
        )
    except ProfiledResearchFinalizedOutcomeV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _integrity(reason)
    if type(parsed) is not dict:
        _integrity(reason)
    result = cast(dict[str, Any], parsed)
    try:
        canonical = _canonical_bytes(result, reason=reason)
    except ProfiledResearchFinalizedOutcomeV1ValidationError as exc:
        raise ProfiledResearchFinalizedOutcomeV1IntegrityError(reason) from exc
    if not hmac.compare_digest(raw, canonical):
        _integrity(reason)
    return result


def _strict_sha256(value: object) -> str | None:
    return value if type(value) is str and _SHA256_RE.fullmatch(value) else None


def _strict_positive_int(value: object, *, maximum: int | None = None) -> int | None:
    if type(value) is not int or value <= 0:
        return None
    return value if maximum is None or value <= maximum else None


def _finite_float(value: object, *, positive: bool = False) -> float | None:
    if type(value) is not float or not math.isfinite(value):
        return None
    if positive and value <= 0.0:
        return None
    return value


def _aware_clock(value: object) -> datetime | None:
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


def _epoch_microseconds(value: datetime) -> int:
    delta = value.astimezone(UTC) - _UTC_EPOCH
    return (
        delta.days * 86_400 * 1_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def _datetime_from_epoch_milliseconds(value: int) -> datetime:
    return _UTC_EPOCH + timedelta(milliseconds=value)


def _ceil_millisecond(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    remainder = normalized.microsecond % 1_000
    if remainder:
        normalized += timedelta(microseconds=1_000 - remainder)
    return normalized


def _format_millisecond(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _canonical_millisecond_clock(value: object) -> datetime | None:
    parsed = _aware_clock(value)
    if parsed is None or parsed.microsecond % 1_000:
        return None
    return parsed if _format_millisecond(parsed) == value else None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _expected_address(payload: bytes) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(payload),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )


def _address_from_mapping(value: object, *, reason: str) -> SourcePayloadAddress:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }:
        _integrity(reason)
    mapping = cast(dict[str, Any], value)
    digest = _strict_sha256(mapping.get("payload_sha256"))
    count = _strict_positive_int(
        mapping.get("payload_byte_count"), maximum=_MAX_JSON_BYTES
    )
    relative = mapping.get("relative_path")
    if (
        mapping.get("schema_version") != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or digest is None
        or count is None
        or type(relative) is not str
        or relative != f"sha256/{digest[:2]}/{digest}"
    ):
        _integrity(reason)
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=count,
        relative_path=relative,
    )


def _address_from_columns(
    *, sha256: object, byte_count: object, relative_path: object
) -> SourcePayloadAddress:
    return _address_from_mapping(
        {
            "schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
            "payload_sha256": sha256,
            "payload_byte_count": byte_count,
            "relative_path": relative_path,
        },
        reason="PROFILED_OUTCOME_CAS_ADDRESS_INVALID",
    )


def _put_exact(store: ImmutableSourcePayloadStore, payload: bytes) -> SourcePayloadAddress:
    expected = _expected_address(payload)
    try:
        address = store.put(
            payload,
            expected_sha256=expected.payload_sha256,
            expected_byte_count=expected.payload_byte_count,
        )
        readback = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
            "PROFILED_OUTCOME_CAS_PUBLICATION_FAILED"
        ) from exc
    if address != expected or not hmac.compare_digest(readback, payload):
        _integrity("PROFILED_OUTCOME_CAS_READBACK_INVALID")
    return address


def _get_exact(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    *,
    reason: str,
) -> bytes:
    try:
        payload = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchFinalizedOutcomeV1IntegrityError(reason) from exc
    if address != _expected_address(payload):
        _integrity(reason)
    return payload


def _lexical_absolute_path(path: object) -> Path:
    if not isinstance(path, Path):
        _validation("PROFILED_OUTCOME_LEDGER_PATH_EXACT_PATH_REQUIRED")
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


def _writer_lock_path(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".writer.lock")


def _head_catalog_root(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".head-anchor-cas")


class ProfiledResearchFinalizedOutcomeWriterLease:
    """Nonblocking path-and-inode lease for the single outcome writer."""

    __slots__ = (
        "_db_device",
        "_db_fd",
        "_db_inode",
        "_ledger_path",
        "_lock_device",
        "_lock_fd",
        "_lock_inode",
        "_lock_path",
        "_owner_pid",
        "_released",
    )

    def __init__(
        self,
        *,
        ledger_path: Path,
        lock_path: Path,
        lock_fd: int,
        lock_device: int,
        lock_inode: int,
        token: object,
    ) -> None:
        if token is not _LEASE_TOKEN:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_FACTORY_REQUIRED"
            )
        self._ledger_path = ledger_path
        self._lock_path = lock_path
        self._lock_fd = lock_fd
        self._lock_device = lock_device
        self._lock_inode = lock_inode
        self._db_fd = -1
        self._db_device = -1
        self._db_inode = -1
        self._owner_pid = os.getpid()
        self._released = False

    @classmethod
    def acquire(cls, ledger_path: Path) -> ProfiledResearchFinalizedOutcomeWriterLease:
        exact_path = _lexical_absolute_path(ledger_path)
        lock_path = _writer_lock_path(exact_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_OPEN_FAILED"
            ) from exc
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or not stat.S_ISREG(path_stat.st_mode)
                or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                    "PROFILED_OUTCOME_WRITER_LEASE_INODE_INVALID"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_ALREADY_HELD"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise
        result = cls(
            ledger_path=exact_path,
            lock_path=lock_path,
            lock_fd=descriptor,
            lock_device=int(descriptor_stat.st_dev),
            lock_inode=int(descriptor_stat.st_ino),
            token=_LEASE_TOKEN,
        )
        result.validate_for(exact_path)
        return result

    def bind_database_inode(self, *, create: bool) -> None:
        self.validate_for(self._ledger_path)
        if self._db_fd >= 0:
            return
        flags = os.O_RDWR | (os.O_CREAT if create else 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(self._ledger_path, flags, 0o600)
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_DATABASE_INODE_OPEN_FAILED"
            ) from exc
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(self._ledger_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or not stat.S_ISREG(path_stat.st_mode)
                or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                    "PROFILED_OUTCOME_DATABASE_INODE_INVALID"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_DATABASE_INODE_ALREADY_HELD"
            ) from exc
        except BaseException:
            os.close(descriptor)
            raise
        self._db_fd = descriptor
        self._db_device = int(descriptor_stat.st_dev)
        self._db_inode = int(descriptor_stat.st_ino)
        self.validate_for(self._ledger_path)

    def validate_for(self, ledger_path: Path) -> None:
        if _lexical_absolute_path(ledger_path) != self._ledger_path:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_PATH_MISMATCH"
            )
        if self._released or self._lock_fd < 0 or os.getpid() != self._owner_pid:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_NOT_HELD"
            )
        try:
            descriptor_stat = os.fstat(self._lock_fd)
            path_stat = os.stat(self._lock_path, follow_symlinks=False)
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_BINDING_MISSING"
            ) from exc
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (self._lock_device, self._lock_inode)
            or (path_stat.st_dev, path_stat.st_ino)
            != (self._lock_device, self._lock_inode)
        ):
            raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                "PROFILED_OUTCOME_WRITER_LEASE_BINDING_CHANGED"
            )
        if self._db_fd >= 0:
            try:
                db_stat = os.fstat(self._db_fd)
                db_path_stat = os.stat(self._ledger_path, follow_symlinks=False)
            except OSError as exc:
                raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                    "PROFILED_OUTCOME_DATABASE_BINDING_MISSING"
                ) from exc
            if (
                not stat.S_ISREG(db_stat.st_mode)
                or (db_stat.st_dev, db_stat.st_ino)
                != (self._db_device, self._db_inode)
                or (db_path_stat.st_dev, db_path_stat.st_ino)
                != (self._db_device, self._db_inode)
            ):
                raise ProfiledResearchFinalizedOutcomeWriterLeaseError(
                    "PROFILED_OUTCOME_DATABASE_BINDING_CHANGED"
                )

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        descriptors = (self._db_fd, self._lock_fd)
        self._db_fd = -1
        self._lock_fd = -1
        for descriptor in descriptors:
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    def __enter__(self) -> ProfiledResearchFinalizedOutcomeWriterLease:
        self.validate_for(self._ledger_path)
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _schema_script() -> str:
    return f"""
    PRAGMA application_id={_APPLICATION_ID};
    PRAGMA user_version={_USER_VERSION};
    CREATE TABLE profiled_finalized_outcome_metadata (
        metadata_key TEXT PRIMARY KEY,
        metadata_value TEXT NOT NULL
    );
    CREATE TABLE profiled_finalized_outcomes (
        sequence INTEGER PRIMARY KEY,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
        commitment_append_receipt_sha256 TEXT NOT NULL,
        commitment_postcommit_receipt_sha256 TEXT NOT NULL,
        commitment_record_chain_sha256 TEXT NOT NULL,
        outcome_artifact_sha256 TEXT NOT NULL UNIQUE,
        outcome_artifact_byte_count INTEGER NOT NULL CHECK(
            outcome_artifact_byte_count > 0
            AND outcome_artifact_byte_count <= {_MAX_JSON_BYTES}
        ),
        outcome_artifact_relative_path TEXT NOT NULL,
        outcome_artifact_json TEXT NOT NULL CHECK(
            length(CAST(outcome_artifact_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        outcome_material_sha256 TEXT NOT NULL UNIQUE,
        label_source_binding_sha256 TEXT NOT NULL,
        symbol TEXT NOT NULL,
        decision_time TEXT NOT NULL,
        label_earliest_available_at TEXT NOT NULL,
        actual_label_available_at TEXT NOT NULL,
        maturation_observed_at TEXT NOT NULL UNIQUE,
        selected_action TEXT NOT NULL,
        diagnostic_best_after_cost_action TEXT NOT NULL,
        calibration_eligible INTEGER NOT NULL CHECK(calibration_eligible IN (0, 1)),
        previous_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        transaction_id TEXT NOT NULL UNIQUE,
        commit_observed_at TEXT NOT NULL UNIQUE,
        commit_prepared_at TEXT NOT NULL UNIQUE
    );
    CREATE TABLE profiled_finalized_outcome_append_receipts (
        transaction_id TEXT PRIMARY KEY,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        outcome_artifact_sha256 TEXT NOT NULL UNIQUE,
        previous_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        total_finalized_outcomes INTEGER NOT NULL,
        receipt_sha256 TEXT NOT NULL UNIQUE,
        receipt_json TEXT NOT NULL CHECK(
            length(CAST(receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        maturation_observed_at TEXT NOT NULL UNIQUE,
        commit_observed_at TEXT NOT NULL UNIQUE,
        commit_prepared_at TEXT NOT NULL UNIQUE,
        precommit_readback_verified INTEGER NOT NULL CHECK(
            precommit_readback_verified = 1
        ),
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_finalized_outcomes(transaction_id)
    );
    CREATE TABLE profiled_finalized_outcome_postcommit_receipts (
        transaction_id TEXT PRIMARY KEY,
        append_receipt_sha256 TEXT NOT NULL UNIQUE,
        outcome_artifact_sha256 TEXT NOT NULL UNIQUE,
        record_chain_sha256 TEXT NOT NULL,
        readback_receipt_sha256 TEXT NOT NULL UNIQUE,
        readback_receipt_json TEXT NOT NULL CHECK(
            length(CAST(readback_receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        postcommit_observed_at TEXT NOT NULL UNIQUE,
        postcommit_readback_at TEXT NOT NULL UNIQUE,
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_finalized_outcome_append_receipts(transaction_id)
    );
    CREATE TABLE profiled_finalized_outcome_head_anchors (
        sequence INTEGER PRIMARY KEY,
        transaction_id TEXT NOT NULL UNIQUE,
        outcome_artifact_sha256 TEXT NOT NULL UNIQUE,
        record_chain_sha256 TEXT NOT NULL,
        append_receipt_sha256 TEXT NOT NULL UNIQUE,
        postcommit_receipt_sha256 TEXT NOT NULL UNIQUE,
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
            REFERENCES profiled_finalized_outcome_postcommit_receipts(transaction_id)
    );
    CREATE INDEX profiled_finalized_outcome_label_available
        ON profiled_finalized_outcomes(actual_label_available_at, hypothesis_identity_sha256);
    CREATE INDEX profiled_finalized_outcome_decision_time
        ON profiled_finalized_outcomes(symbol, decision_time, hypothesis_identity_sha256);
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
            _integrity("PROFILED_OUTCOME_EXPECTED_SCHEMA_INVALID")
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
            _integrity("PROFILED_OUTCOME_SCHEMA_SQL_INVALID")
        observed_sql[(object_type, name)] = normalized
    metadata = {
        str(row["metadata_key"]): str(row["metadata_value"])
        for row in connection.execute(
            "SELECT metadata_key, metadata_value FROM profiled_finalized_outcome_metadata"
        )
    }
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
        _integrity("PROFILED_OUTCOME_SCHEMA_INVALID")


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class _PreparedOutcome:
    artifact_address: SourcePayloadAddress
    artifact_bytes: bytes
    artifact_contract: dict[str, Any] = field(repr=False)
    hypothesis_identity_sha256: str
    hypothesis_artifact_sha256: str
    outcome_material_sha256: str
    label_source_binding_sha256: str
    symbol: str
    decision_time: str
    label_earliest_available_at: str
    actual_label_available_at: str
    maturation_observed_at: str
    selected_action: str
    diagnostic_best_after_cost_action: str
    calibration_eligible: bool
    checkpoint_id: str
    checkpoint_generation: int
    model_parameter_fingerprint: str
    model_binding_sha256: str


def _validate_source_free_label_semantics(
    *,
    artifact: Mapping[str, Any],
    hypothesis_binding: Mapping[str, Any],
    label_binding: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
) -> None:
    symbol = hypothesis_binding.get("symbol")
    decision = _aware_clock(hypothesis_binding.get("decision_time"))
    maturation = _aware_clock(artifact.get("maturation_observed_at"))
    earliest = _aware_clock(hypothesis_binding.get("label_earliest_available_at"))
    actual = _aware_clock(artifact.get("actual_label_available_at"))
    generated = _aware_clock(hypothesis_binding.get("hypothesis_generated_at"))
    commit_observed = _aware_clock(hypothesis_binding.get("commit_observed_at"))
    commit_prepared = _canonical_millisecond_clock(
        hypothesis_binding.get("commit_prepared_at")
    )
    post_observed = _aware_clock(hypothesis_binding.get("postcommit_observed_at"))
    post_readback = _canonical_millisecond_clock(
        hypothesis_binding.get("postcommit_readback_at")
    )
    start = label_binding.get("start_close_time_ms")
    end = label_binding.get("end_close_time_ms")
    archive_path = label_binding.get("archive_path")
    proof = artifact.get("label_path_proof_at_maturation")
    if (
        type(symbol) is not str
        or _SYMBOL_RE.fullmatch(symbol) is None
        or decision is None
        or maturation is None
        or earliest is None
        or actual is None
        or generated is None
        or commit_observed is None
        or commit_prepared is None
        or post_observed is None
        or post_readback is None
        or _format_microsecond(decision) != hypothesis_binding.get("decision_time")
        or _format_microsecond(maturation) != artifact.get("maturation_observed_at")
        or _format_microsecond(earliest)
        != hypothesis_binding.get("label_earliest_available_at")
        or _format_microsecond(actual) != artifact.get("actual_label_available_at")
        or _format_microsecond(generated)
        != hypothesis_binding.get("hypothesis_generated_at")
        or _format_microsecond(commit_observed)
        != hypothesis_binding.get("commit_observed_at")
        or _format_microsecond(post_observed)
        != hypothesis_binding.get("postcommit_observed_at")
        or maturation < earliest
        or maturation < actual
        or earliest != decision + timedelta(
            seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        )
        or generated >= commit_observed
        or commit_observed > commit_prepared
        or post_observed <= commit_observed
        or post_observed > post_readback
        or post_readback <= commit_prepared
        or post_readback >= earliest
        or hypothesis_binding.get("holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or label_binding.get("schema_version")
        != "profiled_research_label_source_binding_v1"
        or label_binding.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION
        or type(archive_path) is not str
        or not Path(archive_path).is_absolute()
        or label_binding.get("symbol") != symbol
        or label_binding.get("decision_time") != hypothesis_binding.get("decision_time")
        or label_binding.get("maturation_observed_at")
        != artifact.get("maturation_observed_at")
        or label_binding.get("horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or type(start) is not int
        or type(end) is not int
        or start % 300_000 != 299_999
        or end < start
        or (end - start) % 300_000
        or (end - start) // 300_000 + 1 != len(inventory)
        or label_binding.get("actual_label_available_at")
        != artifact.get("actual_label_available_at")
        or type(proof) is not dict
    ):
        _integrity("PROFILED_OUTCOME_SOURCE_FREE_LABEL_BINDING_INVALID")
    hypothesis_hash_fields = (
        "hypothesis_identity_sha256",
        "hypothesis_artifact_sha256",
        "cost_evidence_artifact_sha256",
        "raw_inference_binding_sha256",
        "hypothesis_material_sha256",
        "commitment_append_receipt_sha256",
        "commitment_postcommit_receipt_sha256",
        "commitment_sha256",
        "commitment_record_chain_sha256",
    )
    artifact_address = _address_from_mapping(
        hypothesis_binding.get("hypothesis_artifact_cas_address"),
        reason="PROFILED_OUTCOME_HYPOTHESIS_ARTIFACT_ADDRESS_INVALID",
    )
    _address_from_mapping(
        hypothesis_binding.get("cost_closure_cas_address"),
        reason="PROFILED_OUTCOME_COST_CLOSURE_ADDRESS_INVALID",
    )
    if (
        any(
            _strict_sha256(hypothesis_binding.get(name)) is None
            for name in hypothesis_hash_fields
        )
        or artifact_address.payload_sha256
        != hypothesis_binding.get("hypothesis_artifact_sha256")
        or artifact_address.payload_byte_count
        != hypothesis_binding.get("hypothesis_artifact_byte_count")
        or type(hypothesis_binding.get("durable_snapshot_id")) is not str
        or not cast(str, hypothesis_binding.get("durable_snapshot_id")).strip()
        or type(hypothesis_binding.get("commitment_transaction_id")) is not str
        or not cast(str, hypothesis_binding.get("commitment_transaction_id")).strip()
    ):
        _integrity("PROFILED_OUTCOME_HYPOTHESIS_BINDING_STRUCTURE_INVALID")
    previous_close: int | None = None
    maximum_available_ms = 0
    for index, item in enumerate(inventory):
        open_ms = item.get("candle_open_time_ms")
        close_ms = item.get("candle_close_time_ms")
        available_ms = item.get("available_at_ms")
        if (
            type(open_ms) is not int
            or type(close_ms) is not int
            or type(available_ms) is not int
            or close_ms - open_ms != 299_999
            or close_ms != start + index * 300_000
            or available_ms <= close_ms
            or (previous_close is not None and close_ms - previous_close != 300_000)
        ):
            _integrity("PROFILED_OUTCOME_CANDLE_INVENTORY_TIME_INVALID")
        address = _address_from_mapping(
            item.get("candle_cas_address"),
            reason="PROFILED_OUTCOME_CANDLE_INVENTORY_ADDRESS_INVALID",
        )
        if address.payload_sha256 != item.get("content_sha256"):
            _integrity("PROFILED_OUTCOME_CANDLE_INVENTORY_CONTENT_BINDING_INVALID")
        previous_close = close_ms
        maximum_available_ms = max(maximum_available_ms, available_ms)
    if (
        _datetime_from_epoch_milliseconds(maximum_available_ms) != actual
        or _epoch_microseconds(actual) % 1_000
        or proof.get("schema_version") != LABEL_PATH_PROOF_SCHEMA_VERSION
        or proof.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION
        or proof.get("status") != "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
        or proof.get("rejection_reasons") != []
        or proof.get("symbol") != symbol
        or proof.get("decision_time_epoch_us") != _epoch_microseconds(decision)
        or proof.get("training_observed_at_epoch_us")
        != _epoch_microseconds(maturation)
        or proof.get("horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or proof.get("start_close_time_ms") != start
        or proof.get("end_close_time_ms") != end
        or proof.get("expected_rows") != len(inventory)
        or proof.get("loaded_rows") != len(inventory)
        or proof.get("label_available_at_ms") != maximum_available_ms
        or start * 1_000 <= _epoch_microseconds(decision)
        or end * 1_000
        < _epoch_microseconds(decision)
        + CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS * 1_000_000
        or end * 1_000
        - (
            _epoch_microseconds(decision)
            + CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS * 1_000_000
        )
        >= 300_000 * 1_000
        or proof.get("strictly_after_decision_verified") is not True
        or proof.get("horizon_endpoint_verified") is not True
        or proof.get("pit_available_at_verified") is not True
        or _strict_sha256(proof.get("label_path_sha256")) is None
    ):
        _integrity("PROFILED_OUTCOME_STORED_LABEL_PATH_PROOF_INVALID")
    range_proof = proof.get("range_proof")
    required_range = {
        "schema_version": RANGE_PROOF_SCHEMA_VERSION,
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "status": "VERIFIED_CANONICAL_5M_LABEL_RANGE",
        "rejection_reasons": [],
        "symbol": symbol,
        "start_close_time_ms": start,
        "end_close_time_ms": end,
        "expected_rows": len(inventory),
        "loaded_rows": len(inventory),
        "receipt_commit_cutoff_required": True,
        "canonical_payloads_verified": True,
        "content_sha256_verified": True,
        "append_transaction_precommit_receipts_verified": True,
        "postcommit_readback_receipts_verified": True,
        "record_chain_formula_verified": True,
        "pit_available_at_verified": True,
        "contiguous_path_verified": True,
        "transaction_snapshot_verified": True,
        "archive_schema_and_retention_verified": True,
        "automatic_pruning_enabled": False,
    }
    decision_us = _epoch_microseconds(decision)
    observed_us = _epoch_microseconds(maturation)
    target_us = (
        decision_us
        + CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS * 1_000_000
    )
    expected_candle_ids = [item["candle_id"] for item in inventory]
    expected_content_by_close = [
        {
            "candle_close_time_ms": item["candle_close_time_ms"],
            "content_sha256": item["content_sha256"],
        }
        for item in inventory
    ]
    stored_range_material = (
        range_proof.get("range_material") if type(range_proof) is dict else None
    )
    row_chain = (
        stored_range_material.get("row_chain_provenance")
        if type(stored_range_material) is dict
        else None
    )
    if (
        type(row_chain) is not list
        or len(row_chain) != len(inventory)
        or any(
            type(item) is not dict
            or set(item)
            != {"sequence", "previous_chain_sha256", "record_chain_sha256"}
            or _strict_positive_int(item.get("sequence")) is None
            or _strict_sha256(item.get("previous_chain_sha256")) is None
            or _strict_sha256(item.get("record_chain_sha256")) is None
            for item in row_chain
        )
    ):
        _integrity("PROFILED_OUTCOME_STORED_LABEL_ROW_CHAIN_INVALID")
    assert type(range_proof) is dict
    assert type(stored_range_material) is dict
    checkpoint_chain = stored_range_material.get(
        "integrity_checkpoint_chain_sha256"
    )
    if checkpoint_chain is not None and _strict_sha256(checkpoint_chain) is None:
        _integrity("PROFILED_OUTCOME_STORED_LABEL_CHECKPOINT_CHAIN_INVALID")
    range_material = {
        "schema_version": RANGE_PROOF_SCHEMA_VERSION,
        "range_mode": "COMPLETE_CONTIGUOUS",
        "symbol": symbol,
        "start_close_time_ms": start,
        "end_close_time_ms": end,
        "training_observed_at_epoch_us": observed_us,
        "training_observed_at_ms": observed_us // 1_000,
        "receipt_commit_cutoff_required": True,
        "candle_ids": expected_candle_ids,
        "content_sha256_by_close": expected_content_by_close,
        "row_chain_provenance": row_chain,
        "append_receipt_sha256": label_binding.get("append_receipt_sha256s"),
        "postcommit_readback_receipt_sha256": label_binding.get(
            "postcommit_readback_receipt_sha256s"
        ),
        "archive_total_unique_rows": stored_range_material.get(
            "archive_total_unique_rows"
        ),
        "archive_chain_sha256": stored_range_material.get(
            "archive_chain_sha256"
        ),
        "integrity_checkpoint_chain_sha256": checkpoint_chain,
    }
    expected_range_sha = archive_stable_sha256(range_material)
    label_material = {
        "schema_version": LABEL_PATH_PROOF_SCHEMA_VERSION,
        "symbol": symbol,
        "decision_time_epoch_us": decision_us,
        "decision_time_ms": decision_us // 1_000,
        "training_observed_at_epoch_us": observed_us,
        "training_observed_at_ms": observed_us // 1_000,
        "horizon_seconds": CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
        "horizon_target_time_epoch_us": target_us,
        "horizon_target_time_ms": (target_us + 999) // 1_000,
        "start_close_time_ms": start,
        "end_close_time_ms": end,
        "range_sha256": expected_range_sha,
    }
    if (
        type(range_proof) is not dict
        or any(range_proof.get(key) != value for key, value in required_range.items())
        or stored_range_material != range_material
        or range_proof.get("training_observed_at_epoch_us")
        != _epoch_microseconds(maturation)
        or range_proof.get("training_observed_at_ms") != observed_us // 1_000
        or range_proof.get("append_receipt_sha256")
        != label_binding.get("append_receipt_sha256s")
        or range_proof.get("postcommit_readback_receipt_sha256")
        != label_binding.get("postcommit_readback_receipt_sha256s")
        or type(stored_range_material.get("archive_total_unique_rows")) is not str
        or not cast(
            str, stored_range_material.get("archive_total_unique_rows")
        ).isdecimal()
        or int(cast(str, stored_range_material.get("archive_total_unique_rows")))
        < len(inventory)
        or _strict_sha256(stored_range_material.get("archive_chain_sha256")) is None
        or range_proof.get("range_sha256") != expected_range_sha
        or proof.get("decision_time_ms") != decision_us // 1_000
        or proof.get("training_observed_at_ms") != observed_us // 1_000
        or proof.get("horizon_target_time_epoch_us") != target_us
        or proof.get("horizon_target_time_ms") != (target_us + 999) // 1_000
        or proof.get("label_path_sha256")
        != archive_stable_sha256(label_material)
    ):
        _integrity("PROFILED_OUTCOME_STORED_LABEL_RANGE_PROOF_INVALID")


def _validate_economics_identities(economics: Mapping[str, Any]) -> None:
    float_fields = (
        "entry_price",
        "exit_price",
        "raw_market_return_bps",
        "fee_bps_per_side",
        "full_round_trip_spread_bps",
        "expected_slippage_bps_per_side",
        "signed_horizon_funding_bps",
        "base_execution_cost_bps",
        "long_total_cost_bps",
        "short_total_cost_bps",
        "conservative_total_cost_bps",
        "counterfactual_long_net_pnl_bps",
        "counterfactual_short_net_pnl_bps",
        "counterfactual_hold_net_pnl_bps",
        "selected_action_net_pnl_bps",
        "model_expected_move_bps",
        "expected_move_error_bps",
        "model_selected_action_probability",
    )
    if any(
        type(economics.get(name)) is not float
        or not math.isfinite(cast(float, economics.get(name)))
        for name in float_fields
    ):
        _integrity("PROFILED_OUTCOME_ECONOMICS_FLOAT_FIELDS_INVALID")
    entry = cast(float, economics["entry_price"])
    exit_price = cast(float, economics["exit_price"])
    raw_return = cast(float, economics["raw_market_return_bps"])
    fee = cast(float, economics["fee_bps_per_side"])
    spread = cast(float, economics["full_round_trip_spread_bps"])
    impact = cast(float, economics["expected_slippage_bps_per_side"])
    funding = cast(float, economics["signed_horizon_funding_bps"])
    base = 2.0 * fee + spread + 2.0 * impact
    long_cost = base + funding
    short_cost = base - funding
    long_net = raw_return - long_cost
    short_net = -raw_return - short_cost
    selected = economics.get("selected_action")
    if type(selected) is not str:
        _integrity("PROFILED_OUTCOME_SELECTED_ACTION_INVALID")
    selected_net = {"hold": 0.0, "long": long_net, "short": short_net}.get(selected)
    diagnostic = (
        "hold"
        if max(long_net, short_net) <= 0.0
        else "long"
        if long_net >= short_net
        else "short"
    )
    values = economics.get("cost_feature_values")
    if (
        entry <= 0.0
        or exit_price <= 0.0
        or fee < 0.0
        or spread < 0.0
        or impact < 0.0
        or economics.get("basis")
        != "AUTHENTICATED_DECISION_REFERENCE_MID_TO_FINALIZED_900S_CLOSE"
        or economics.get("cost_feature_names")
        != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or values != [fee, spread, impact, funding]
        or raw_return != (exit_price - entry) / entry * 10_000.0
        or economics.get("base_execution_cost_bps") != base
        or economics.get("long_total_cost_bps") != long_cost
        or economics.get("short_total_cost_bps") != short_cost
        or economics.get("conservative_total_cost_bps") != base + abs(funding)
        or economics.get("counterfactual_long_net_pnl_bps") != long_net
        or economics.get("counterfactual_short_net_pnl_bps") != short_net
        or economics.get("counterfactual_hold_net_pnl_bps") != 0.0
        or selected_net is None
        or economics.get("selected_action_net_pnl_bps") != selected_net
        or economics.get("selected_action_profitable")
        is not (selected_net > 0.0 if selected != "hold" else None)
        or economics.get("diagnostic_best_after_cost_action") != diagnostic
        or economics.get("selected_action_matches_diagnostic_best")
        is not (selected == diagnostic)
        or economics.get("expected_move_error_bps")
        != raw_return - cast(float, economics["model_expected_move_bps"])
        or not 0.0 <= cast(float, economics["model_selected_action_probability"]) <= 1.0
        or type(economics.get("postdecision_excursion_candle_count")) is not int
        or cast(int, economics["postdecision_excursion_candle_count"]) <= 0
        or economics.get("predecision_overlap_excluded_from_excursion") is not True
        or economics.get("funding_sign_convention")
        != "POSITIVE_VENUE_RATE_LONG_PAYS_SHORT_RECEIVES"
    ):
        _integrity("PROFILED_OUTCOME_ECONOMICS_IDENTITY_INVALID")


def _validate_artifact_structure(
    artifact: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if set(artifact) != _ARTIFACT_FIELDS:
        _integrity("PROFILED_OUTCOME_ARTIFACT_FIELDS_INVALID")
    material = {
        name: value
        for name, value in artifact.items()
        if name != "outcome_material_sha256"
    }
    if (
        artifact.get("schema_version")
        != PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_SCHEMA_VERSION
        or artifact.get("classification")
        != PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_CLASSIFICATION
        or artifact.get("status") != _STATUS
        or artifact.get("authorization") != _AUTHORIZATION
        or artifact.get("research_only") is not True
        or artifact.get("outcome_material_sha256") != _sha256(material)
    ):
        _integrity("PROFILED_OUTCOME_ARTIFACT_ENVELOPE_INVALID")
    hypothesis_binding = artifact.get("hypothesis_binding")
    model_binding = artifact.get("model_binding")
    label_binding = artifact.get("label_source_binding")
    inventory = artifact.get("label_candle_inventory")
    economics = artifact.get("economics")
    calibration = artifact.get("calibration_row")
    if (
        type(hypothesis_binding) is not dict
        or set(hypothesis_binding) != _HYPOTHESIS_BINDING_FIELDS
        or type(model_binding) is not dict
        or set(model_binding) != _MODEL_BINDING_FIELDS
        or type(label_binding) is not dict
        or set(label_binding) != _LABEL_SOURCE_BINDING_FIELDS
        or type(inventory) is not list
        or not 0 < len(inventory) <= _MAX_LABEL_PATH_ROWS
        or any(
            type(item) is not dict
            or set(item) != _LABEL_CANDLE_INVENTORY_FIELDS
            for item in inventory
        )
        or label_binding.get("candle_inventory") != inventory
        or type(economics) is not dict
        or set(economics) != _ECONOMICS_FIELDS
        or type(calibration) is not dict
        or set(calibration) != _CALIBRATION_ROW_FIELDS
    ):
        _integrity("PROFILED_OUTCOME_ARTIFACT_NESTED_FIELDS_INVALID")
    expected_model_binding, expected_model_binding_sha = _model_binding(
        raw=model_binding,
        hypothesis_binding=hypothesis_binding,
    )
    if (
        model_binding != expected_model_binding
        or artifact.get("model_binding_sha256") != expected_model_binding_sha
    ):
        _integrity("PROFILED_OUTCOME_MODEL_BINDING_STRUCTURE_INVALID")
    _validate_source_free_label_semantics(
        artifact=artifact,
        hypothesis_binding=hypothesis_binding,
        label_binding=label_binding,
        inventory=inventory,
    )
    _validate_economics_identities(economics)
    binding_sha = artifact.get("label_source_binding_sha256")
    append_receipts = label_binding.get("append_receipt_sha256s")
    postcommit_receipts = label_binding.get("postcommit_readback_receipt_sha256s")
    if (
        _strict_sha256(binding_sha) is None
        or binding_sha != _sha256(label_binding)
        or type(append_receipts) is not list
        or not append_receipts
        or any(_strict_sha256(value) is None for value in append_receipts)
        or append_receipts != sorted(set(append_receipts))
        or type(postcommit_receipts) is not list
        or not postcommit_receipts
        or any(_strict_sha256(value) is None for value in postcommit_receipts)
        or postcommit_receipts != sorted(set(postcommit_receipts))
        or label_binding.get("receipt_commit_cutoff_required") is not True
        or label_binding.get("future_available_candle_used") is not False
    ):
        _integrity("PROFILED_OUTCOME_LABEL_BINDING_STRUCTURE_INVALID")
    for item in inventory:
        _address_from_mapping(
            item.get("candle_cas_address"),
            reason="PROFILED_OUTCOME_CANDLE_INVENTORY_ADDRESS_INVALID",
        )
        if any(
            _strict_sha256(item.get(name)) is None
            for name in ("raw_payload_hash", "market_fact_sha256", "content_sha256")
        ):
            _integrity("PROFILED_OUTCOME_CANDLE_INVENTORY_HASH_INVALID")
    selected_action = economics.get("selected_action")
    diagnostic_action = economics.get("diagnostic_best_after_cost_action")
    directional = selected_action in CONFIDENCE_HEAD_ACTIONS
    raw_probability = calibration.get("raw_probability")
    observed = calibration.get("observed_strictly_positive_net_pnl")
    brier = calibration.get("raw_brier_contribution")
    if (
        selected_action not in {"hold", "long", "short"}
        or diagnostic_action not in {"hold", "long", "short"}
        or economics.get("schema_version")
        != "profiled_research_selected_action_economics_v1"
        or economics.get("profitability_uses_strict_positive_zero_boundary")
        is not True
        or economics.get("static_market_threshold_used") is not False
        or economics.get("hindsight_action_substituted_for_selected_action")
        is not False
        or calibration.get("schema_version")
        != PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION
        or calibration.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS
        or calibration.get("eligible") is not directional
        or calibration.get("selected_directional_action")
        != (selected_action if directional else None)
        or calibration.get("selected_action_net_pnl_bps")
        != economics.get("selected_action_net_pnl_bps")
        or calibration.get("selected_action_preserved_ex_ante") is not True
        or calibration.get("hindsight_action_substitution_used") is not False
        or calibration.get("fit_partition")
        != "UNASSIGNED_REQUIRES_PURGED_TRAIN_ONLY_ADMISSION"
        or calibration.get("calibration_input_authorized") is not False
        or calibration.get("model_binding_sha256") != expected_model_binding_sha
        or calibration.get("model_parameter_fingerprint")
        != model_binding.get("model_parameter_fingerprint")
        or calibration.get("checkpoint_id") != model_binding.get("checkpoint_id")
        or calibration.get("checkpoint_generation")
        != model_binding.get("checkpoint_generation")
    ):
        _integrity("PROFILED_OUTCOME_CALIBRATION_SEMANTICS_INVALID")
    expected_row_id = _sha256(
        {
            "domain": "v2/native-trainer/profiled-finalized-calibration-row/v1",
            "hypothesis_identity_sha256": hypothesis_binding.get(
                "hypothesis_identity_sha256"
            ),
            "hypothesis_artifact_sha256": hypothesis_binding.get(
                "hypothesis_artifact_sha256"
            ),
            "raw_inference_binding_sha256": hypothesis_binding.get(
                "raw_inference_binding_sha256"
            ),
            "model_binding_sha256": expected_model_binding_sha,
            "label_source_binding_sha256": binding_sha,
            "selected_action": selected_action,
        }
    )
    if calibration.get("row_id") != expected_row_id:
        _integrity("PROFILED_OUTCOME_CALIBRATION_ROW_ID_INVALID")
    if directional:
        probability = _finite_float(raw_probability)
        selected_net = _finite_float(economics.get("selected_action_net_pnl_bps"))
        mfe = _finite_float(
            economics.get("selected_action_max_favorable_excursion_bps")
        )
        mae = _finite_float(
            economics.get("selected_action_max_adverse_excursion_bps")
        )
        if (
            probability is None
            or not 0.0 <= probability <= 1.0
            or type(observed) is not bool
            or selected_net is None
            or observed is not (selected_net > 0.0)
            or mfe is None
            or mfe < 0.0
            or mae is None
            or mae > 0.0
            or brier != (probability - (1.0 if observed else 0.0)) ** 2
        ):
            _integrity("PROFILED_OUTCOME_DIRECTIONAL_CALIBRATION_ROW_INVALID")
    elif (
        raw_probability is not None
        or observed is not None
        or brier is not None
        or economics.get("selected_action_max_favorable_excursion_bps") is not None
        or economics.get("selected_action_max_adverse_excursion_bps") is not None
    ):
        _integrity("PROFILED_OUTCOME_HOLD_CALIBRATION_ROW_INVALID")
    return hypothesis_binding, label_binding, economics, calibration


def _hypothesis_binding(
    committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        contract = committed.hypothesis_contract
        authorization = committed.authorization
        status = committed.commitment_status
    except ProfiledResearchShadowHypothesisCommitmentV1Error as exc:
        raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
            "PROFILED_OUTCOME_COMMITTED_HYPOTHESIS_REVALIDATION_FAILED"
        ) from exc
    if (
        authorization != _AUTHORIZATION
        or status.get("durable_ex_ante_commit_receipt_present") is not True
        or status.get("postcommit_readback_receipt_present") is not True
        or committed.durable_ex_ante_commitment_verified is not True
        or committed.runtime_wired is not False
    ):
        _integrity("PROFILED_OUTCOME_EX_ANTE_COMMITMENT_INVALID")
    raw_value = contract.get("raw_inference_payload")
    try:
        raw = validate_portable_profiled_research_raw_inference_v2_payload(raw_value)
    except LocallyAuthenticatedProfiledResearchInferenceV1Error as exc:
        raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
            "PROFILED_OUTCOME_RAW_INFERENCE_INVALID"
        ) from exc
    binding = {
        "hypothesis_identity_sha256": committed.hypothesis_identity_sha256,
        "hypothesis_artifact_sha256": committed.hypothesis_artifact_sha256,
        "hypothesis_artifact_byte_count": committed.hypothesis_artifact_byte_count,
        "hypothesis_artifact_cas_address": _address_mapping(
            committed.hypothesis_artifact_address
        ),
        "cost_closure_cas_address": _address_mapping(committed.cost_closure_address),
        "cost_evidence_artifact_sha256": committed.cost_evidence_artifact_sha256,
        "raw_inference_binding_sha256": committed.raw_inference_binding_sha256,
        "hypothesis_material_sha256": committed.hypothesis_material_sha256,
        "symbol": committed.symbol,
        "durable_snapshot_id": committed.durable_snapshot_id,
        "decision_time": committed.decision_time,
        "hypothesis_generated_at": committed.hypothesis_generated_at,
        "label_earliest_available_at": committed.label_earliest_available_at,
        "holding_horizon_seconds": committed.holding_horizon_seconds,
        "commitment_transaction_id": committed.transaction_id,
        "commitment_append_receipt_sha256": committed.append_receipt_sha256,
        "commitment_postcommit_receipt_sha256": (
            committed.postcommit_readback_receipt_sha256
        ),
        "commitment_sha256": committed.commitment_sha256,
        "commitment_record_chain_sha256": committed.record_chain_sha256,
        "commit_observed_at": committed.commit_observed_at,
        "commit_prepared_at": committed.commit_prepared_at,
        "postcommit_observed_at": committed.postcommit_observed_at,
        "postcommit_readback_at": committed.postcommit_readback_at,
    }
    if (
        _strict_sha256(binding["hypothesis_identity_sha256"]) is None
        or _strict_sha256(binding["hypothesis_artifact_sha256"]) is None
        or binding["holding_horizon_seconds"]
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or binding["symbol"] != raw.get("symbol")
        or binding["decision_time"] != raw.get("source_decision_time")
    ):
        _integrity("PROFILED_OUTCOME_HYPOTHESIS_BINDING_INVALID")
    return binding, raw


def _model_binding(
    *,
    raw: Mapping[str, Any],
    hypothesis_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    binding = {
        "schema_version": (
            PROFILED_RESEARCH_FINALIZED_OUTCOME_MODEL_BINDING_V1_SCHEMA_VERSION
        ),
        "checkpoint_id": raw.get("checkpoint_id"),
        "checkpoint_generation": raw.get("checkpoint_generation"),
        "checkpoint_generated_at": raw.get("checkpoint_generated_at"),
        "checkpoint_weight_sha256": raw.get("checkpoint_weight_sha256"),
        "model_id": raw.get("model_id"),
        "model_parameter_fingerprint": raw.get("model_parameter_fingerprint"),
        "candidate_contract_sha256": raw.get("candidate_contract_sha256"),
        "candidate_authorization_receipt_sha256": raw.get(
            "candidate_authorization_receipt_sha256"
        ),
        "candidate_code_release_sha": raw.get("candidate_code_release_sha"),
        "confidence_head_schema_version": raw.get(
            "confidence_head_schema_version"
        ),
        "confidence_head_actions": raw.get("confidence_head_actions"),
        "profitability_label_semantics": (
            raw.get("confidence_label_semantics")
            if raw.get("confidence_label_semantics") is not None
            else raw.get("profitability_label_semantics")
        ),
        "raw_inference_binding_sha256": hypothesis_binding.get(
            "raw_inference_binding_sha256"
        ),
        "hypothesis_artifact_sha256": hypothesis_binding.get(
            "hypothesis_artifact_sha256"
        ),
    }
    checkpoint_clock = _aware_clock(binding["checkpoint_generated_at"])
    decision_clock = _aware_clock(hypothesis_binding.get("decision_time"))
    if (
        set(binding) != _MODEL_BINDING_FIELDS
        or type(binding["checkpoint_id"]) is not str
        or _IDENTIFIER_RE.fullmatch(binding["checkpoint_id"]) is None
        or type(binding["checkpoint_generation"]) is not int
        or binding["checkpoint_generation"] <= 0
        or checkpoint_clock is None
        or decision_clock is None
        or checkpoint_clock >= decision_clock
        or type(binding["model_id"]) is not str
        or not binding["model_id"]
        or any(
            _strict_sha256(binding[name]) is None
            for name in (
                "checkpoint_weight_sha256",
                "model_parameter_fingerprint",
                "candidate_contract_sha256",
                "candidate_authorization_receipt_sha256",
                "raw_inference_binding_sha256",
                "hypothesis_artifact_sha256",
            )
        )
        or type(binding["candidate_code_release_sha"]) is not str
        or _SHA1_RE.fullmatch(binding["candidate_code_release_sha"]) is None
        or binding["confidence_head_schema_version"]
        != CONFIDENCE_HEAD_SCHEMA_VERSION
        or binding["confidence_head_actions"] != list(CONFIDENCE_HEAD_ACTIONS)
        or binding["profitability_label_semantics"] != CONFIDENCE_LABEL_SEMANTICS
    ):
        _integrity("PROFILED_OUTCOME_MODEL_BINDING_INVALID")
    return binding, _sha256(binding)


def _internally_observed_clock() -> tuple[str, datetime]:
    observed = _utc_now()
    if (
        type(observed) is not datetime
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        _integrity("PROFILED_OUTCOME_INTERNAL_CLOCK_INVALID")
    normalized = observed.astimezone(UTC)
    return _format_microsecond(normalized), normalized


def _validated_label_source(
    *,
    archive: DurableCanonical5mLabelArchive,
    hypothesis_binding: Mapping[str, Any],
    observed_at: str,
    store: ImmutableSourcePayloadStore,
    publish_candle_cas: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    decision_time = cast(str, hypothesis_binding["decision_time"])
    earliest = _aware_clock(hypothesis_binding["label_earliest_available_at"])
    observed_clock = _aware_clock(observed_at)
    if earliest is None or observed_clock is None:
        _integrity("PROFILED_OUTCOME_CLOCK_BINDING_INVALID")
    if observed_clock < earliest:
        _validation("PROFILED_OUTCOME_EARLIEST_LABEL_TIME_NOT_REACHED")
    rows, proof = archive.verified_label_path(
        symbol=cast(str, hypothesis_binding["symbol"]),
        decision_time=decision_time,
        training_observed_at=observed_at,
        horizon_seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
        require_receipt_committed_by_observation=True,
    )
    if rows is None:
        reasons = proof.get("rejection_reasons")
        reason = (
            str(reasons[0])
            if type(reasons) is list and reasons and type(reasons[0]) is str
            else "UNKNOWN"
        )
        _validation(f"PROFILED_OUTCOME_LABEL_PATH_NOT_MATURE:{reason}")
    if not rows or len(rows) > _MAX_LABEL_PATH_ROWS:
        _integrity("PROFILED_OUTCOME_LABEL_PATH_ROW_BOUND_INVALID")
    range_proof = proof.get("range_proof")
    if type(range_proof) is not dict:
        _integrity("PROFILED_OUTCOME_LABEL_RANGE_PROOF_INVALID")
    range_mapping = cast(dict[str, Any], range_proof)
    required_path = {
        "schema_version": LABEL_PATH_PROOF_SCHEMA_VERSION,
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "status": "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH",
        "rejection_reasons": [],
        "horizon_seconds": CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
        "strictly_after_decision_verified": True,
        "horizon_endpoint_verified": True,
        "pit_available_at_verified": True,
    }
    required_range = {
        "schema_version": RANGE_PROOF_SCHEMA_VERSION,
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "status": "VERIFIED_CANONICAL_5M_LABEL_RANGE",
        "rejection_reasons": [],
        "receipt_commit_cutoff_required": True,
        "canonical_payloads_verified": True,
        "content_sha256_verified": True,
        "append_transaction_precommit_receipts_verified": True,
        "postcommit_readback_receipts_verified": True,
        "record_chain_formula_verified": True,
        "pit_available_at_verified": True,
        "contiguous_path_verified": True,
        "transaction_snapshot_verified": True,
        "archive_schema_and_retention_verified": True,
        "automatic_pruning_enabled": False,
    }
    if any(proof.get(key) != value for key, value in required_path.items()) or any(
        range_mapping.get(key) != value for key, value in required_range.items()
    ):
        _integrity("PROFILED_OUTCOME_LABEL_PROOF_SEMANTICS_INVALID")
    if (
        proof.get("symbol") != hypothesis_binding["symbol"]
        or range_mapping.get("symbol") != hypothesis_binding["symbol"]
        or proof.get("expected_rows") != len(rows)
        or proof.get("loaded_rows") != len(rows)
        or range_mapping.get("expected_rows") != len(rows)
        or range_mapping.get("loaded_rows") != len(rows)
    ):
        _integrity("PROFILED_OUTCOME_LABEL_PROOF_IDENTITY_INVALID")

    inventory: list[dict[str, Any]] = []
    canonical_rows: list[dict[str, Any]] = []
    previous_close: int | None = None
    maximum_available_ms = 0
    for row in rows:
        try:
            validated = validate_canonical_finalized_5m_candle(
                row,
                expected_symbol=cast(str, hypothesis_binding["symbol"]),
            )
            payload_json = canonical_candle_json(row)
        except (Canonical5mValidationError, TypeError, ValueError) as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_CANONICAL_LABEL_CANDLE_INVALID"
            ) from exc
        payload = payload_json.encode("ascii", errors="strict")
        address = _expected_address(payload)
        if publish_candle_cas:
            if _put_exact(store, payload) != address:
                _integrity("PROFILED_OUTCOME_CANDLE_CAS_PUBLICATION_INVALID")
        elif _get_exact(
            store,
            address,
            reason="PROFILED_OUTCOME_CANDLE_CAS_REOPEN_FAILED",
        ) != payload:
            _integrity("PROFILED_OUTCOME_CANDLE_CAS_REOPEN_MISMATCH")
        close_ms = cast(int, validated["close_time_ms"])
        if previous_close is not None and close_ms - previous_close != 300_000:
            _integrity("PROFILED_OUTCOME_LABEL_PATH_GAP")
        previous_close = close_ms
        maximum_available_ms = max(
            maximum_available_ms,
            cast(int, validated["available_at_ms"]),
        )
        canonical_rows.append(dict(row))
        inventory.append(
            {
                "candle_id": validated["candle_id"],
                "candle_open_time_ms": validated["open_time_ms"],
                "candle_close_time_ms": close_ms,
                "available_at_ms": validated["available_at_ms"],
                "raw_payload_hash": validated["raw_payload_hash"],
                "market_fact_sha256": validated["market_fact_sha256"],
                "content_sha256": validated["content_sha256"],
                "candle_cas_address": _address_mapping(address),
            }
        )
    actual_available = _datetime_from_epoch_milliseconds(maximum_available_ms)
    if actual_available > observed_clock:
        _integrity("PROFILED_OUTCOME_LABEL_AVAILABLE_AFTER_OBSERVATION")
    if proof.get("label_available_at_ms") != maximum_available_ms:
        _integrity("PROFILED_OUTCOME_LABEL_AVAILABLE_BINDING_INVALID")
    stable_material = {
        "schema_version": "profiled_research_label_source_binding_v1",
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "archive_path": str(archive.path),
        "symbol": hypothesis_binding["symbol"],
        "decision_time": decision_time,
        "maturation_observed_at": observed_at,
        "horizon_seconds": CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
        "start_close_time_ms": proof.get("start_close_time_ms"),
        "end_close_time_ms": proof.get("end_close_time_ms"),
        "actual_label_available_at": _format_microsecond(actual_available),
        "candle_inventory": inventory,
        "append_receipt_sha256s": range_mapping.get("append_receipt_sha256"),
        "postcommit_readback_receipt_sha256s": range_mapping.get(
            "postcommit_readback_receipt_sha256"
        ),
        "receipt_commit_cutoff_required": True,
        "future_available_candle_used": False,
    }
    return canonical_rows, proof, stable_material, _sha256(stable_material)


def _derive_economics(
    *,
    contract: Mapping[str, Any],
    raw: Mapping[str, Any],
    label_rows: Sequence[Mapping[str, Any]],
    hypothesis_identity_sha256: str,
    hypothesis_artifact_sha256: str,
    label_source_binding_sha256: str,
    decision_time: str,
    model_binding: Mapping[str, Any],
    model_binding_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision_reference = contract.get("decision_reference_binding")
    cost_binding = contract.get("cost_evidence_binding")
    if type(decision_reference) is not dict or type(cost_binding) is not dict:
        _integrity("PROFILED_OUTCOME_HYPOTHESIS_ECONOMICS_BINDING_INVALID")
    reference = cast(dict[str, Any], decision_reference)
    costs = cast(dict[str, Any], cost_binding)
    entry = _finite_float(reference.get("mid"), positive=True)
    ordered_names = costs.get("ordered_feature_names")
    ordered_values = costs.get("ordered_values")
    if (
        entry is None
        or ordered_names != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or type(ordered_values) is not list
        or len(ordered_values) != 4
        or any(type(value) is not float or not math.isfinite(value) for value in ordered_values)
    ):
        _integrity("PROFILED_OUTCOME_EXPLICIT_COST_BINDING_INVALID")
    fee, spread, impact, funding = cast(list[float], ordered_values)
    if fee < 0.0 or spread < 0.0 or impact < 0.0:
        _integrity("PROFILED_OUTCOME_EXPLICIT_COST_VALUE_INVALID")
    exit_price = _finite_float(label_rows[-1].get("close"), positive=True)
    if exit_price is None:
        _integrity("PROFILED_OUTCOME_FINAL_CLOSE_INVALID")
    raw_return = (exit_price - entry) / entry * 10_000.0
    base_execution = 2.0 * fee + spread + 2.0 * impact
    long_cost = base_execution + funding
    short_cost = base_execution - funding
    conservative_cost = base_execution + abs(funding)
    long_net = raw_return - long_cost
    short_net = -raw_return - short_cost
    if not all(
        math.isfinite(value)
        for value in (
            raw_return,
            base_execution,
            long_cost,
            short_cost,
            conservative_cost,
            long_net,
            short_net,
        )
    ):
        _integrity("PROFILED_OUTCOME_ECONOMICS_NONFINITE")
    diagnostic_best_after_cost_action = (
        "hold"
        if max(long_net, short_net) <= 0.0
        else "long"
        if long_net >= short_net
        else "short"
    )
    selected_action = raw.get("selected_action")
    if selected_action not in {"hold", "long", "short"}:
        _integrity("PROFILED_OUTCOME_SELECTED_ACTION_INVALID")
    selected_net = {
        "hold": 0.0,
        "long": long_net,
        "short": short_net,
    }[cast(str, selected_action)]
    directional = selected_action in CONFIDENCE_HEAD_ACTIONS
    observed_profitable = selected_net > 0.0 if directional else None
    decision_clock = _aware_clock(decision_time)
    if decision_clock is None:
        _integrity("PROFILED_OUTCOME_DECISION_CLOCK_INVALID")
    decision_time_us = _epoch_microseconds(decision_clock)
    postdecision_rows = [
        row
        for row in label_rows
        if type(row.get("candle_open_time")) is int
        and cast(int, row["candle_open_time"]) * 1_000 >= decision_time_us
    ]
    if not postdecision_rows:
        _integrity("PROFILED_OUTCOME_POSTDECISION_EXCURSION_PATH_MISSING")
    excursion: tuple[float, float] | None = None
    if directional:
        excursion = counterfactual_excursion_bps(
            entry_price=entry,
            target_action=selected_action,
            highs=(cast(float, row.get("high")) for row in postdecision_rows),
            lows=(cast(float, row.get("low")) for row in postdecision_rows),
        )
        if excursion is None or not all(math.isfinite(value) for value in excursion):
            _integrity("PROFILED_OUTCOME_SELECTED_EXCURSION_INVALID")
    raw_probability = raw.get("selected_directional_profitability_raw")
    if directional:
        raw_probability = _finite_float(raw_probability)
        if raw_probability is None or not 0.0 <= raw_probability <= 1.0:
            _integrity("PROFILED_OUTCOME_DIRECTIONAL_PROBABILITY_INVALID")
        outcome = 1.0 if observed_profitable is True else 0.0
        brier = (raw_probability - outcome) ** 2
    else:
        if raw_probability is not None:
            _integrity("PROFILED_OUTCOME_HOLD_PROBABILITY_MUST_BE_ABSENT")
        brier = None
    action_probabilities = raw.get("model_action_probabilities")
    selected_index = raw.get("selected_action_index")
    if (
        type(action_probabilities) is not list
        or type(selected_index) is not int
        or not 0 <= selected_index < len(action_probabilities)
        or type(action_probabilities[selected_index]) is not float
    ):
        _integrity("PROFILED_OUTCOME_ACTION_PROBABILITY_BINDING_INVALID")
    selected_policy_probability = action_probabilities[selected_index]
    expected_move = _finite_float(raw.get("expected_move_bps"))
    if expected_move is None:
        _integrity("PROFILED_OUTCOME_EXPECTED_MOVE_INVALID")
    economics = {
        "schema_version": "profiled_research_selected_action_economics_v1",
        "basis": "AUTHENTICATED_DECISION_REFERENCE_MID_TO_FINALIZED_900S_CLOSE",
        "entry_price": entry,
        "exit_price": exit_price,
        "raw_market_return_bps": raw_return,
        "cost_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "cost_feature_values": list(ordered_values),
        "fee_bps_per_side": fee,
        "full_round_trip_spread_bps": spread,
        "expected_slippage_bps_per_side": impact,
        "signed_horizon_funding_bps": funding,
        "base_execution_cost_bps": base_execution,
        "long_total_cost_bps": long_cost,
        "short_total_cost_bps": short_cost,
        "conservative_total_cost_bps": conservative_cost,
        "counterfactual_long_net_pnl_bps": long_net,
        "counterfactual_short_net_pnl_bps": short_net,
        "counterfactual_hold_net_pnl_bps": 0.0,
        "selected_action": selected_action,
        "selected_action_net_pnl_bps": selected_net,
        "selected_action_profitable": observed_profitable,
        "selected_action_max_favorable_excursion_bps": (
            excursion[0] if excursion is not None else None
        ),
        "selected_action_max_adverse_excursion_bps": (
            excursion[1] if excursion is not None else None
        ),
        "postdecision_excursion_candle_count": len(postdecision_rows),
        "predecision_overlap_excluded_from_excursion": True,
        "diagnostic_best_after_cost_action": diagnostic_best_after_cost_action,
        "selected_action_matches_diagnostic_best": (
            selected_action == diagnostic_best_after_cost_action
        ),
        "model_expected_move_bps": expected_move,
        "expected_move_error_bps": raw_return - expected_move,
        "model_selected_action_probability": selected_policy_probability,
        "profitability_uses_strict_positive_zero_boundary": True,
        "static_market_threshold_used": False,
        "hindsight_action_substituted_for_selected_action": False,
        "funding_sign_convention": "POSITIVE_VENUE_RATE_LONG_PAYS_SHORT_RECEIVES",
    }
    row_id = _sha256(
        {
            "domain": "v2/native-trainer/profiled-finalized-calibration-row/v1",
            "hypothesis_identity_sha256": hypothesis_identity_sha256,
            "hypothesis_artifact_sha256": hypothesis_artifact_sha256,
            "raw_inference_binding_sha256": contract.get("raw_inference_binding_sha256"),
            "model_binding_sha256": model_binding_sha256,
            "label_source_binding_sha256": label_source_binding_sha256,
            "selected_action": selected_action,
        }
    )
    calibration = {
        "schema_version": (
            PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION
        ),
        "row_id": row_id,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "eligible": directional,
        "selected_directional_action": selected_action if directional else None,
        "raw_probability": raw_probability,
        "observed_strictly_positive_net_pnl": observed_profitable,
        "raw_brier_contribution": brier,
        "selected_action_net_pnl_bps": selected_net,
        "selected_action_preserved_ex_ante": True,
        "hindsight_action_substitution_used": False,
        "fit_partition": "UNASSIGNED_REQUIRES_PURGED_TRAIN_ONLY_ADMISSION",
        "calibration_input_authorized": False,
        "model_binding_sha256": model_binding_sha256,
        "model_parameter_fingerprint": model_binding["model_parameter_fingerprint"],
        "checkpoint_id": model_binding["checkpoint_id"],
        "checkpoint_generation": model_binding["checkpoint_generation"],
    }
    return economics, calibration


def _prepare_new_outcome(
    *,
    committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
    archive: DurableCanonical5mLabelArchive,
    store: ImmutableSourcePayloadStore,
    observed_at: str,
) -> _PreparedOutcome:
    hypothesis_binding, raw = _hypothesis_binding(committed)
    model_binding, model_binding_sha = _model_binding(
        raw=raw,
        hypothesis_binding=hypothesis_binding,
    )
    rows, proof, label_binding, label_binding_sha = _validated_label_source(
        archive=archive,
        hypothesis_binding=hypothesis_binding,
        observed_at=observed_at,
        store=store,
        publish_candle_cas=True,
    )
    contract = committed.hypothesis_contract
    economics, calibration = _derive_economics(
        contract=contract,
        raw=raw,
        label_rows=rows,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256=label_binding_sha,
        decision_time=committed.decision_time,
        model_binding=model_binding,
        model_binding_sha256=model_binding_sha,
    )
    actual_available = cast(str, label_binding["actual_label_available_at"])
    inventory = cast(list[dict[str, Any]], label_binding["candle_inventory"])
    material = {
        "schema_version": PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_CLASSIFICATION,
        "hypothesis_binding": hypothesis_binding,
        "model_binding": model_binding,
        "model_binding_sha256": model_binding_sha,
        "maturation_observed_at": observed_at,
        "actual_label_available_at": actual_available,
        "label_source_binding": label_binding,
        "label_source_binding_sha256": label_binding_sha,
        "label_path_proof_at_maturation": proof,
        "label_candle_inventory": inventory,
        "economics": economics,
        "calibration_row": calibration,
        "status": dict(_STATUS),
        "authorization": dict(_AUTHORIZATION),
        "research_only": True,
    }
    artifact = {
        **material,
        "outcome_material_sha256": _sha256(material),
    }
    payload = _canonical_bytes(
        artifact,
        reason="PROFILED_OUTCOME_ARTIFACT_JSON_INVALID",
    )
    address = _put_exact(store, payload)
    return _PreparedOutcome(
        artifact_address=address,
        artifact_bytes=payload,
        artifact_contract=artifact,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        outcome_material_sha256=cast(str, artifact["outcome_material_sha256"]),
        label_source_binding_sha256=label_binding_sha,
        symbol=committed.symbol,
        decision_time=committed.decision_time,
        label_earliest_available_at=committed.label_earliest_available_at,
        actual_label_available_at=actual_available,
        maturation_observed_at=observed_at,
        selected_action=cast(str, economics["selected_action"]),
        diagnostic_best_after_cost_action=cast(
            str, economics["diagnostic_best_after_cost_action"]
        ),
        calibration_eligible=cast(bool, calibration["eligible"]),
        checkpoint_id=cast(str, model_binding["checkpoint_id"]),
        checkpoint_generation=cast(int, model_binding["checkpoint_generation"]),
        model_parameter_fingerprint=cast(
            str, model_binding["model_parameter_fingerprint"]
        ),
        model_binding_sha256=model_binding_sha,
    )


def _reopen_prepared(
    *,
    address: SourcePayloadAddress,
    committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
    archive: DurableCanonical5mLabelArchive,
    store: ImmutableSourcePayloadStore,
) -> _PreparedOutcome:
    payload = _get_exact(store, address, reason="PROFILED_OUTCOME_ARTIFACT_REOPEN_FAILED")
    artifact = _parse_exact_object(payload, reason="PROFILED_OUTCOME_ARTIFACT_JSON_INVALID")
    (
        stored_hypothesis_binding,
        stored_label_binding,
        _stored_economics,
        _stored_calibration,
    ) = _validate_artifact_structure(artifact)
    if _expected_address(payload) != address:
        _integrity("PROFILED_OUTCOME_ARTIFACT_ADDRESS_INVALID")
    observed_at = artifact.get("maturation_observed_at")
    observed_clock = _aware_clock(observed_at)
    if observed_clock is None or _format_microsecond(observed_clock) != observed_at:
        _integrity("PROFILED_OUTCOME_MATURATION_CLOCK_INVALID")
    hypothesis_binding, raw = _hypothesis_binding(committed)
    if stored_hypothesis_binding != hypothesis_binding:
        _integrity("PROFILED_OUTCOME_HYPOTHESIS_REOPEN_BINDING_MISMATCH")
    model_binding, model_binding_sha = _model_binding(
        raw=raw,
        hypothesis_binding=hypothesis_binding,
    )
    if (
        artifact.get("model_binding") != model_binding
        or artifact.get("model_binding_sha256") != model_binding_sha
    ):
        _integrity("PROFILED_OUTCOME_MODEL_REOPEN_BINDING_MISMATCH")
    stored_label_binding_sha = artifact.get("label_source_binding_sha256")
    stored_proof = artifact.get("label_path_proof_at_maturation")
    stored_inventory = artifact.get("label_candle_inventory")
    if (
        type(stored_proof) is not dict
        or type(stored_inventory) is not list
        or _strict_sha256(stored_label_binding_sha) is None
        or stored_label_binding.get("candle_inventory") != stored_inventory
    ):
        _integrity("PROFILED_OUTCOME_STORED_LABEL_BINDING_INVALID")
    stored_range = stored_proof.get("range_proof")
    if (
        type(stored_range) is not dict
        or stored_proof.get("schema_version") != LABEL_PATH_PROOF_SCHEMA_VERSION
        or stored_proof.get("status")
        != "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
        or stored_proof.get("rejection_reasons") != []
        or stored_proof.get("symbol") != committed.symbol
        or stored_proof.get("horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or stored_proof.get("training_observed_at_epoch_us")
        != _epoch_microseconds(observed_clock)
        or stored_range.get("schema_version") != RANGE_PROOF_SCHEMA_VERSION
        or stored_range.get("status") != "VERIFIED_CANONICAL_5M_LABEL_RANGE"
        or stored_range.get("rejection_reasons") != []
        or stored_range.get("receipt_commit_cutoff_required") is not True
    ):
        _integrity("PROFILED_OUTCOME_STORED_LABEL_PROOF_INVALID")
    rows, _current_proof, current_label_binding, current_label_binding_sha = (
        _validated_label_source(
            archive=archive,
            hypothesis_binding=hypothesis_binding,
            observed_at=cast(str, observed_at),
            store=store,
            publish_candle_cas=False,
        )
    )
    if (
        current_label_binding != stored_label_binding
        or current_label_binding_sha != stored_label_binding_sha
    ):
        _integrity("PROFILED_OUTCOME_LABEL_SOURCE_REDERIVATION_MISMATCH")
    contract = committed.hypothesis_contract
    economics, calibration = _derive_economics(
        contract=contract,
        raw=raw,
        label_rows=rows,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256=current_label_binding_sha,
        decision_time=committed.decision_time,
        model_binding=model_binding,
        model_binding_sha256=model_binding_sha,
    )
    expected_material = {
        "schema_version": PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_CLASSIFICATION,
        "hypothesis_binding": hypothesis_binding,
        "model_binding": model_binding,
        "model_binding_sha256": model_binding_sha,
        "maturation_observed_at": observed_at,
        "actual_label_available_at": current_label_binding[
            "actual_label_available_at"
        ],
        "label_source_binding": current_label_binding,
        "label_source_binding_sha256": current_label_binding_sha,
        "label_path_proof_at_maturation": stored_proof,
        "label_candle_inventory": stored_inventory,
        "economics": economics,
        "calibration_row": calibration,
        "status": dict(_STATUS),
        "authorization": dict(_AUTHORIZATION),
        "research_only": True,
    }
    expected_artifact = {
        **expected_material,
        "outcome_material_sha256": _sha256(expected_material),
    }
    if expected_artifact != artifact:
        _integrity("PROFILED_OUTCOME_ARTIFACT_REDERIVATION_MISMATCH")
    return _PreparedOutcome(
        artifact_address=address,
        artifact_bytes=payload,
        artifact_contract=artifact,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        outcome_material_sha256=cast(str, artifact["outcome_material_sha256"]),
        label_source_binding_sha256=current_label_binding_sha,
        symbol=committed.symbol,
        decision_time=committed.decision_time,
        label_earliest_available_at=committed.label_earliest_available_at,
        actual_label_available_at=cast(
            str, current_label_binding["actual_label_available_at"]
        ),
        maturation_observed_at=cast(str, observed_at),
        selected_action=cast(str, economics["selected_action"]),
        diagnostic_best_after_cost_action=cast(
            str, economics["diagnostic_best_after_cost_action"]
        ),
        calibration_eligible=cast(bool, calibration["eligible"]),
        checkpoint_id=cast(str, model_binding["checkpoint_id"]),
        checkpoint_generation=cast(int, model_binding["checkpoint_generation"]),
        model_parameter_fingerprint=cast(
            str, model_binding["model_parameter_fingerprint"]
        ),
        model_binding_sha256=model_binding_sha,
    )


@dataclass(frozen=True, slots=True)
class ProfiledResearchFinalizedOutcomeIntegrityV1:
    total_finalized_outcomes: int
    append_receipts_verified: int
    postcommit_receipts_verified: int
    head_anchors_verified: int
    cas_outcomes_verified: int
    cas_label_candles_verified: int
    cas_head_anchors_verified: int
    calibration_eligible_rows: int
    calibration_ineligible_rows: int
    chain_head_sha256: str
    schema_verified: bool
    clock_causality_verified: bool


@dataclass(frozen=True, slots=True)
class DurablyMaturedProfiledResearchFinalizedOutcomeV1:
    hypothesis_identity_sha256: str
    hypothesis_artifact_sha256: str
    outcome_artifact_sha256: str
    outcome_artifact_byte_count: int
    outcome_artifact_address: SourcePayloadAddress
    outcome_material_sha256: str
    label_source_binding_sha256: str
    symbol: str
    decision_time: str
    label_earliest_available_at: str
    actual_label_available_at: str
    maturation_observed_at: str
    selected_action: str
    diagnostic_best_after_cost_action: str
    calibration_eligible: bool
    checkpoint_id: str
    checkpoint_generation: int
    model_parameter_fingerprint: str
    model_binding_sha256: str
    transaction_id: str
    append_receipt_sha256: str
    postcommit_readback_receipt_sha256: str
    record_chain_sha256: str
    commit_observed_at: str
    commit_prepared_at: str
    postcommit_observed_at: str
    postcommit_readback_at: str
    _artifact_json: str = field(repr=False, compare=False)
    _ledger: ProfiledResearchFinalizedOutcomeLedgerV1 = field(repr=False, compare=False)
    _committed: DurablyCommittedProfiledResearchShadowHypothesisV1 = field(
        repr=False, compare=False
    )
    _archive: DurableCanonical5mLabelArchive = field(repr=False, compare=False)
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _validation_writer_lease: (
        ProfiledResearchFinalizedOutcomeWriterLease | None
    ) = field(repr=False, compare=False)
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def outcome_contract(self) -> dict[str, Any]:
        return _validated_result(self)

    @property
    def economics(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.outcome_contract["economics"])

    @property
    def calibration_row(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.outcome_contract["calibration_row"])

    @property
    def authorization(self) -> dict[str, bool]:
        _validated_result(self)
        return dict(_AUTHORIZATION)

    @property
    def runtime_wired(self) -> bool:
        _validated_result(self)
        return False

    @property
    def trainer_admission_authorized(self) -> bool:
        _validated_result(self)
        return False

    @property
    def calibration_input_authorized(self) -> bool:
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


class ProfiledResearchFinalizedOutcomeLedgerV1:
    """Append-only finalized-outcome chain with restart-safe CAS reopening."""

    def __init__(
        self,
        path: Path,
        *,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease | None = None,
    ) -> None:
        self.path = _lexical_absolute_path(path)
        self._writer_lease = writer_lease
        if writer_lease is not None:
            writer_lease.validate_for(self.path)

    @contextmanager
    def writer_lease(
        self,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease | None = None,
    ) -> Iterator[ProfiledResearchFinalizedOutcomeWriterLease]:
        held = writer_lease if writer_lease is not None else self._writer_lease
        acquired_here = held is None
        if held is None:
            held = ProfiledResearchFinalizedOutcomeWriterLease.acquire(self.path)
        try:
            held.validate_for(self.path)
            yield held
            held.validate_for(self.path)
        finally:
            if acquired_here:
                held.release()

    @contextmanager
    def _reader_lease(self) -> Iterator[None]:
        configured = self._writer_lease
        if configured is not None:
            try:
                configured.validate_for(self.path)
            except ProfiledResearchFinalizedOutcomeWriterLeaseError as exc:
                if exc.reason != "PROFILED_OUTCOME_WRITER_LEASE_NOT_HELD":
                    raise
            else:
                yield
                configured.validate_for(self.path)
                return
        lock_path = _writer_lock_path(self.path)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        lock_fd = -1
        database_fd = -1
        try:
            lock_fd = os.open(lock_path, flags)
            lock_stat = os.fstat(lock_fd)
            lock_path_stat = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or (lock_stat.st_dev, lock_stat.st_ino)
                != (lock_path_stat.st_dev, lock_path_stat.st_ino)
            ):
                _integrity("PROFILED_OUTCOME_READER_LEASE_BINDING_INVALID")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                    "PROFILED_OUTCOME_READER_LEASE_WRITER_ACTIVE"
                ) from exc
            database_fd = os.open(self.path, flags)
            database_stat = os.fstat(database_fd)
            database_path_stat = os.stat(self.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(database_stat.st_mode)
                or (database_stat.st_dev, database_stat.st_ino)
                != (database_path_stat.st_dev, database_path_stat.st_ino)
            ):
                _integrity("PROFILED_OUTCOME_READER_DATABASE_BINDING_INVALID")
            try:
                fcntl.flock(database_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                    "PROFILED_OUTCOME_READER_LEASE_WRITER_ACTIVE"
                ) from exc
            yield
            final_lock = os.stat(lock_path, follow_symlinks=False)
            final_database = os.stat(self.path, follow_symlinks=False)
            if (
                (final_lock.st_dev, final_lock.st_ino)
                != (lock_stat.st_dev, lock_stat.st_ino)
                or (final_database.st_dev, final_database.st_ino)
                != (database_stat.st_dev, database_stat.st_ino)
            ):
                _integrity("PROFILED_OUTCOME_READER_SNAPSHOT_BINDING_CHANGED")
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_READER_LEASE_FAILED"
            ) from exc
        finally:
            for descriptor in (database_fd, lock_fd):
                if descriptor >= 0:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)

    def _connect_write(
        self, *, writer_lease: ProfiledResearchFinalizedOutcomeWriterLease
    ) -> sqlite3.Connection:
        writer_lease.validate_for(self.path)
        writer_lease.bind_database_inode(create=True)
        try:
            path_stat = os.stat(self.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_size > _MAX_LEDGER_DATABASE_BYTES
            ):
                _integrity("PROFILED_OUTCOME_LEDGER_RESOURCE_BOUND_EXCEEDED")
            connection = sqlite3.connect(str(self.path), timeout=60.0)
            _configure_connection(connection)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA temp_store=MEMORY")
            return connection
        except sqlite3.Error as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_WRITE_CONNECTION_FAILED"
            ) from exc

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            _integrity("PROFILED_OUTCOME_LEDGER_MISSING")
        try:
            path_stat = os.stat(self.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_size > _MAX_LEDGER_DATABASE_BYTES
            ):
                _integrity("PROFILED_OUTCOME_LEDGER_NOT_REGULAR_FILE")
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro", uri=True, timeout=60.0
            )
            _configure_connection(connection)
            connection.execute("PRAGMA query_only=ON")
            return connection
        except sqlite3.Error as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_READONLY_CONNECTION_FAILED"
            ) from exc

    def _ensure_initialized(
        self, *, writer_lease: ProfiledResearchFinalizedOutcomeWriterLease
    ) -> None:
        writer_lease.validate_for(self.path)
        writer_lease.bind_database_inode(create=True)
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            objects = connection.execute(
                """
                SELECT type, name FROM sqlite_master
                WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' LIMIT 1
                """
            ).fetchone()
            if objects is not None:
                _validate_schema(connection)
                return
            if (
                int(connection.execute("PRAGMA application_id").fetchone()[0]) != 0
                or int(connection.execute("PRAGMA user_version").fetchone()[0]) != 0
                or self._observed_head_catalog_digests()
            ):
                _integrity("PROFILED_OUTCOME_PARTIAL_OR_FOREIGN_SCHEMA")
            connection.executescript("BEGIN IMMEDIATE;\n" + _schema_script())
            for key, value in sorted(_METADATA.items()):
                connection.execute(
                    """
                    INSERT INTO profiled_finalized_outcome_metadata(
                        metadata_key, metadata_value
                    ) VALUES (?, ?)
                    """,
                    (key, value),
                )
            _validate_schema(connection)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        _fsync_parent(self.path)
        writer_lease.validate_for(self.path)

    @staticmethod
    def _preflight_resources(connection: sqlite3.Connection) -> None:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        aggregate = connection.execute(
            """
            SELECT
              COALESCE((SELECT SUM(length(CAST(outcome_artifact_json AS BLOB)))
                        FROM profiled_finalized_outcomes), 0)
              + COALESCE((SELECT SUM(length(CAST(receipt_json AS BLOB)))
                          FROM profiled_finalized_outcome_append_receipts), 0)
              + COALESCE((SELECT SUM(length(CAST(readback_receipt_json AS BLOB)))
                          FROM profiled_finalized_outcome_postcommit_receipts), 0)
              + COALESCE((SELECT SUM(length(CAST(head_anchor_json AS BLOB)))
                          FROM profiled_finalized_outcome_head_anchors), 0)
            """
        ).fetchone()[0]
        if (
            type(page_size) is not int
            or type(page_count) is not int
            or page_size <= 0
            or page_count < 0
            or page_size * page_count > _MAX_LEDGER_DATABASE_BYTES
            or type(aggregate) is not int
            or aggregate > _MAX_LEDGER_AGGREGATE_JSON_BYTES
        ):
            _integrity("PROFILED_OUTCOME_LEDGER_RESOURCE_BOUND_EXCEEDED")

    @staticmethod
    def _joined_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT o.*,
              a.receipt_sha256 AS append_receipt_sha256,
              a.receipt_json AS append_receipt_json,
              a.hypothesis_identity_sha256 AS append_identity,
              a.outcome_artifact_sha256 AS append_artifact,
              a.previous_chain_sha256 AS append_previous_chain,
              a.record_chain_sha256 AS append_record_chain,
              a.total_finalized_outcomes,
              a.maturation_observed_at AS append_observed_at,
              a.commit_observed_at AS append_commit_observed_at,
              a.commit_prepared_at AS append_commit_prepared_at,
              a.precommit_readback_verified,
              p.append_receipt_sha256 AS post_append_receipt,
              p.outcome_artifact_sha256 AS post_artifact,
              p.record_chain_sha256 AS post_record_chain,
              p.readback_receipt_sha256,
              p.readback_receipt_json,
              p.postcommit_observed_at,
              p.postcommit_readback_at,
              h.sequence AS head_sequence,
              h.transaction_id AS head_transaction,
              h.outcome_artifact_sha256 AS head_artifact,
              h.record_chain_sha256 AS head_record_chain,
              h.append_receipt_sha256 AS head_append_receipt,
              h.postcommit_receipt_sha256 AS head_post_receipt,
              h.previous_head_anchor_sha256,
              h.head_anchor_sha256,
              h.head_anchor_byte_count,
              h.head_anchor_relative_path,
              h.head_anchor_json,
              h.anchored_at
            FROM profiled_finalized_outcomes AS o
            LEFT JOIN profiled_finalized_outcome_append_receipts AS a
              ON a.transaction_id = o.transaction_id
            LEFT JOIN profiled_finalized_outcome_postcommit_receipts AS p
              ON p.transaction_id = o.transaction_id
            LEFT JOIN profiled_finalized_outcome_head_anchors AS h
              ON h.transaction_id = o.transaction_id
            ORDER BY o.sequence ASC
            LIMIT ?
            """,
            (_MAX_LEDGER_RECORDS + 1,),
        ).fetchall()

    @staticmethod
    def _append_material(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_FINALIZED_OUTCOME_APPEND_RECEIPT_V1_SCHEMA_VERSION
            ),
            "transaction_id": row["transaction_id"],
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "outcome_artifact_sha256": row["outcome_artifact_sha256"],
            "previous_chain_sha256": row["previous_chain_sha256"],
            "record_chain_sha256": row["record_chain_sha256"],
            "total_finalized_outcomes": row["sequence"],
            "maturation_observed_at": row["maturation_observed_at"],
            "commit_observed_at": row["commit_observed_at"],
            "commit_prepared_at": row["commit_prepared_at"],
            "precommit_readback_verified": True,
            "authorization": dict(_AUTHORIZATION),
        }

    @staticmethod
    def _post_material(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_FINALIZED_OUTCOME_POSTCOMMIT_V1_SCHEMA_VERSION
            ),
            "transaction_id": row["transaction_id"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "outcome_artifact_sha256": row["outcome_artifact_sha256"],
            "record_chain_sha256": row["record_chain_sha256"],
            "postcommit_observed_at": row["postcommit_observed_at"],
            "postcommit_readback_at": row["postcommit_readback_at"],
            "independent_readback_verified": True,
            "authorization": dict(_AUTHORIZATION),
        }

    @staticmethod
    def _head_material(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_FINALIZED_OUTCOME_HEAD_ANCHOR_V1_SCHEMA_VERSION
            ),
            "sequence": row["sequence"],
            "transaction_id": row["transaction_id"],
            "outcome_artifact_sha256": row["outcome_artifact_sha256"],
            "record_chain_sha256": row["record_chain_sha256"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "postcommit_receipt_sha256": row["readback_receipt_sha256"],
            "previous_head_anchor_sha256": row["previous_head_anchor_sha256"],
            "postcommit_observed_at": row["postcommit_observed_at"],
            "anchored_at": row["postcommit_readback_at"],
            "authorization": dict(_AUTHORIZATION),
        }

    def _verify_database(
        self, connection: sqlite3.Connection, *, require_postcommit: bool
    ) -> tuple[ProfiledResearchFinalizedOutcomeIntegrityV1, list[sqlite3.Row]]:
        _validate_schema(connection)
        self._preflight_resources(connection)
        rows = self._joined_rows(connection)
        if len(rows) > _MAX_LEDGER_RECORDS:
            _integrity("PROFILED_OUTCOME_LEDGER_RECORD_BOUND_EXCEEDED")
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in _TABLE_NAMES
            if table != "profiled_finalized_outcome_metadata"
        }
        expected = len(rows)
        if (
            counts["profiled_finalized_outcomes"] != expected
            or counts["profiled_finalized_outcome_append_receipts"] != expected
            or counts["profiled_finalized_outcome_postcommit_receipts"]
            not in ({expected} if require_postcommit else {expected, expected - 1})
            or counts["profiled_finalized_outcome_head_anchors"]
            != counts["profiled_finalized_outcome_postcommit_receipts"]
        ):
            _integrity("PROFILED_OUTCOME_LEDGER_CARDINALITY_INVALID")
        previous_chain = _GENESIS_CHAIN_SHA256
        previous_head = _GENESIS_HEAD_ANCHOR_SHA256
        previous_observed: datetime | None = None
        previous_commit_observed: datetime | None = None
        previous_commit: datetime | None = None
        previous_post_observed: datetime | None = None
        previous_post: datetime | None = None
        append_verified = 0
        post_verified = 0
        head_verified = 0
        eligible = 0
        for sequence, row in enumerate(rows, start=1):
            if row["sequence"] != sequence:
                _integrity("PROFILED_OUTCOME_SEQUENCE_INVALID")
            hash_fields = (
                "hypothesis_identity_sha256",
                "hypothesis_artifact_sha256",
                "commitment_append_receipt_sha256",
                "commitment_postcommit_receipt_sha256",
                "commitment_record_chain_sha256",
                "outcome_artifact_sha256",
                "outcome_material_sha256",
                "label_source_binding_sha256",
                "previous_chain_sha256",
                "record_chain_sha256",
                "append_receipt_sha256",
            )
            if any(_strict_sha256(row[name]) is None for name in hash_fields):
                _integrity("PROFILED_OUTCOME_HASH_FIELD_INVALID")
            observed = _aware_clock(row["maturation_observed_at"])
            commit_observed = _aware_clock(row["commit_observed_at"])
            commit = _canonical_millisecond_clock(row["commit_prepared_at"])
            label_earliest = _aware_clock(row["label_earliest_available_at"])
            label_available = _aware_clock(row["actual_label_available_at"])
            if (
                observed is None
                or commit_observed is None
                or commit is None
                or label_earliest is None
                or label_available is None
                or _format_microsecond(observed) != row["maturation_observed_at"]
                or _format_microsecond(commit_observed)
                != row["commit_observed_at"]
                or observed < label_earliest
                or observed < label_available
                or commit_observed <= observed
                or commit < commit_observed
                or (previous_observed is not None and observed <= previous_observed)
                or (
                    previous_commit_observed is not None
                    and commit_observed <= previous_commit_observed
                )
                or (previous_commit is not None and commit <= previous_commit)
                or (
                    previous_post_observed is not None
                    and observed <= previous_post_observed
                )
                or (previous_post is not None and commit <= previous_post)
            ):
                _integrity("PROFILED_OUTCOME_CLOCK_CAUSALITY_INVALID")
            artifact = _parse_exact_object(
                row["outcome_artifact_json"],
                reason="PROFILED_OUTCOME_ARTIFACT_JSON_INVALID",
            )
            hypothesis_binding, label_binding, economics, calibration = (
                _validate_artifact_structure(artifact)
            )
            artifact_bytes = cast(str, row["outcome_artifact_json"]).encode("ascii")
            artifact_address = _address_from_columns(
                sha256=row["outcome_artifact_sha256"],
                byte_count=row["outcome_artifact_byte_count"],
                relative_path=row["outcome_artifact_relative_path"],
            )
            if (
                artifact_address != _expected_address(artifact_bytes)
                or row["outcome_artifact_json"]
                != _canonical_json(
                    artifact, reason="PROFILED_OUTCOME_ARTIFACT_JSON_INVALID"
                )
                or artifact.get("outcome_material_sha256")
                != row["outcome_material_sha256"]
                or artifact.get("label_source_binding_sha256")
                != row["label_source_binding_sha256"]
                or artifact.get("maturation_observed_at")
                != row["maturation_observed_at"]
                or artifact.get("actual_label_available_at")
                != row["actual_label_available_at"]
                or hypothesis_binding.get("hypothesis_identity_sha256")
                != row["hypothesis_identity_sha256"]
                or hypothesis_binding.get("hypothesis_artifact_sha256")
                != row["hypothesis_artifact_sha256"]
                or hypothesis_binding.get("commitment_append_receipt_sha256")
                != row["commitment_append_receipt_sha256"]
                or hypothesis_binding.get("commitment_postcommit_receipt_sha256")
                != row["commitment_postcommit_receipt_sha256"]
                or hypothesis_binding.get("commitment_record_chain_sha256")
                != row["commitment_record_chain_sha256"]
                or hypothesis_binding.get("symbol") != row["symbol"]
                or hypothesis_binding.get("decision_time") != row["decision_time"]
                or hypothesis_binding.get("label_earliest_available_at")
                != row["label_earliest_available_at"]
                or label_binding.get("actual_label_available_at")
                != row["actual_label_available_at"]
                or label_binding.get("maturation_observed_at")
                != row["maturation_observed_at"]
                or economics.get("selected_action") != row["selected_action"]
                or economics.get("diagnostic_best_after_cost_action")
                != row["diagnostic_best_after_cost_action"]
                or calibration.get("eligible")
                is not (row["calibration_eligible"] == 1)
            ):
                _integrity("PROFILED_OUTCOME_ARTIFACT_LEDGER_BINDING_INVALID")
            expected_chain = _sha256(
                {
                    "domain": "v2/native-trainer/profiled-finalized-outcome-chain/v1",
                    "sequence": sequence,
                    "previous_chain_sha256": previous_chain,
                    "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
                    "outcome_artifact_sha256": row["outcome_artifact_sha256"],
                    "outcome_material_sha256": row["outcome_material_sha256"],
                    "maturation_observed_at": row["maturation_observed_at"],
                    "commit_observed_at": row["commit_observed_at"],
                    "transaction_id": row["transaction_id"],
                    "commit_prepared_at": row["commit_prepared_at"],
                }
            )
            append_material = self._append_material(row)
            append_json = _canonical_json(
                append_material, reason="PROFILED_OUTCOME_APPEND_RECEIPT_JSON_INVALID"
            )
            if (
                row["previous_chain_sha256"] != previous_chain
                or row["record_chain_sha256"] != expected_chain
                or row["append_identity"] != row["hypothesis_identity_sha256"]
                or row["append_artifact"] != row["outcome_artifact_sha256"]
                or row["append_previous_chain"] != row["previous_chain_sha256"]
                or row["append_record_chain"] != row["record_chain_sha256"]
                or row["total_finalized_outcomes"] != sequence
                or row["append_observed_at"] != row["maturation_observed_at"]
                or row["append_commit_observed_at"]
                != row["commit_observed_at"]
                or row["append_commit_prepared_at"] != row["commit_prepared_at"]
                or row["precommit_readback_verified"] != 1
                or row["append_receipt_json"] != append_json
                or row["append_receipt_sha256"]
                != hashlib.sha256(append_json.encode("ascii")).hexdigest()
            ):
                _integrity("PROFILED_OUTCOME_APPEND_RECEIPT_INVALID")
            append_verified += 1
            if row["postcommit_readback_at"] is None:
                if require_postcommit or sequence != expected:
                    _integrity("PROFILED_OUTCOME_POSTCOMMIT_RECEIPT_MISSING")
            else:
                post_observed = _aware_clock(row["postcommit_observed_at"])
                post_clock = _canonical_millisecond_clock(
                    row["postcommit_readback_at"]
                )
                post_material = self._post_material(row)
                post_json = _canonical_json(
                    post_material,
                    reason="PROFILED_OUTCOME_POSTCOMMIT_RECEIPT_JSON_INVALID",
                )
                head_material = self._head_material(row)
                head_json = _canonical_json(
                    head_material,
                    reason="PROFILED_OUTCOME_HEAD_ANCHOR_JSON_INVALID",
                )
                head_address = _address_from_columns(
                    sha256=row["head_anchor_sha256"],
                    byte_count=row["head_anchor_byte_count"],
                    relative_path=row["head_anchor_relative_path"],
                )
                if (
                    post_observed is None
                    or post_clock is None
                    or _format_microsecond(post_observed)
                    != row["postcommit_observed_at"]
                    or post_observed <= commit_observed
                    or post_clock < post_observed
                    or post_clock <= commit
                    or (
                        previous_post_observed is not None
                        and post_observed <= previous_post_observed
                    )
                    or (previous_post is not None and post_clock <= previous_post)
                    or row["post_append_receipt"] != row["append_receipt_sha256"]
                    or row["post_artifact"] != row["outcome_artifact_sha256"]
                    or row["post_record_chain"] != row["record_chain_sha256"]
                    or row["readback_receipt_json"] != post_json
                    or row["readback_receipt_sha256"]
                    != hashlib.sha256(post_json.encode("ascii")).hexdigest()
                    or row["head_sequence"] != sequence
                    or row["head_transaction"] != row["transaction_id"]
                    or row["head_artifact"] != row["outcome_artifact_sha256"]
                    or row["head_record_chain"] != row["record_chain_sha256"]
                    or row["head_append_receipt"] != row["append_receipt_sha256"]
                    or row["head_post_receipt"] != row["readback_receipt_sha256"]
                    or row["previous_head_anchor_sha256"] != previous_head
                    or row["anchored_at"] != row["postcommit_readback_at"]
                    or row["head_anchor_json"] != head_json
                    or head_address != _expected_address(head_json.encode("ascii"))
                ):
                    _integrity("PROFILED_OUTCOME_POSTCOMMIT_OR_HEAD_INVALID")
                previous_post_observed = post_observed
                previous_post = post_clock
                previous_head = cast(str, row["head_anchor_sha256"])
                post_verified += 1
                head_verified += 1
            if row["calibration_eligible"] == 1:
                eligible += 1
            elif row["calibration_eligible"] != 0:
                _integrity("PROFILED_OUTCOME_CALIBRATION_ELIGIBILITY_INVALID")
            previous_chain = cast(str, row["record_chain_sha256"])
            previous_observed = observed
            previous_commit_observed = commit_observed
            previous_commit = commit
        return (
            ProfiledResearchFinalizedOutcomeIntegrityV1(
                total_finalized_outcomes=expected,
                append_receipts_verified=append_verified,
                postcommit_receipts_verified=post_verified,
                head_anchors_verified=head_verified,
                cas_outcomes_verified=0,
                cas_label_candles_verified=0,
                cas_head_anchors_verified=0,
                calibration_eligible_rows=eligible,
                calibration_ineligible_rows=expected - eligible,
                chain_head_sha256=previous_chain,
                schema_verified=True,
                clock_causality_verified=True,
            ),
            rows,
        )

    @staticmethod
    def _next_commit_clock(
        connection: sqlite3.Connection, *, maturation_observed_at: str
    ) -> tuple[str, str]:
        maturation = _aware_clock(maturation_observed_at)
        commit_observed_at, commit_observed = _internally_observed_clock()
        if maturation is None:
            _integrity("PROFILED_OUTCOME_MATURATION_CLOCK_INVALID")
        if commit_observed <= maturation:
            _validation("PROFILED_OUTCOME_COMMIT_CLOCK_NOT_AFTER_MATURATION")
        prior = connection.execute(
            """
            SELECT maturation_observed_at, commit_observed_at, commit_prepared_at
            FROM profiled_finalized_outcomes ORDER BY sequence DESC LIMIT 1
            """
        ).fetchone()
        lower: datetime | None = None
        if prior is not None:
            prior_observed = _aware_clock(prior["maturation_observed_at"])
            prior_commit_observed = _aware_clock(prior["commit_observed_at"])
            prior_commit = _canonical_millisecond_clock(prior["commit_prepared_at"])
            if (
                prior_observed is None
                or prior_commit_observed is None
                or prior_commit is None
            ):
                _integrity("PROFILED_OUTCOME_PRIOR_CLOCK_INVALID")
            if (
                maturation <= prior_observed
                or commit_observed <= prior_commit_observed
            ):
                _validation("PROFILED_OUTCOME_INTERNAL_CLOCK_NOT_MONOTONIC")
            lower = prior_commit
            prior_post = connection.execute(
                """
                SELECT postcommit_observed_at, postcommit_readback_at
                FROM profiled_finalized_outcome_postcommit_receipts
                ORDER BY postcommit_readback_at DESC LIMIT 1
                """
            ).fetchone()
            if prior_post is not None:
                parsed_post_observed = _aware_clock(
                    prior_post["postcommit_observed_at"]
                )
                parsed_post = _canonical_millisecond_clock(
                    prior_post["postcommit_readback_at"]
                )
                if parsed_post_observed is None or parsed_post is None:
                    _integrity("PROFILED_OUTCOME_PRIOR_POSTCOMMIT_CLOCK_INVALID")
                if (
                    maturation <= parsed_post_observed
                    or commit_observed <= parsed_post_observed
                ):
                    _validation("PROFILED_OUTCOME_INTERNAL_CLOCK_NOT_MONOTONIC")
                lower = max(lower, parsed_post)
        candidate = _ceil_millisecond(commit_observed)
        if lower is not None and candidate <= lower:
            candidate = lower + timedelta(milliseconds=1)
        return commit_observed_at, _format_millisecond(candidate)

    @staticmethod
    def _next_postcommit_clock(
        connection: sqlite3.Connection,
        *,
        commit_observed_at: str,
        commit_prepared_at: str,
    ) -> tuple[str, str]:
        commit_observed = _aware_clock(commit_observed_at)
        commit = _canonical_millisecond_clock(commit_prepared_at)
        postcommit_observed_at, postcommit_observed = _internally_observed_clock()
        if commit_observed is None or commit is None:
            _integrity("PROFILED_OUTCOME_POSTCOMMIT_CLOCK_INVALID")
        if postcommit_observed <= commit_observed:
            _validation("PROFILED_OUTCOME_POSTCOMMIT_CLOCK_NOT_AFTER_COMMIT")
        candidate = _ceil_millisecond(postcommit_observed)
        if candidate <= commit:
            candidate = commit + timedelta(milliseconds=1)
        prior = connection.execute(
            """
            SELECT postcommit_observed_at, postcommit_readback_at
            FROM profiled_finalized_outcome_postcommit_receipts
            ORDER BY postcommit_readback_at DESC LIMIT 1
            """
        ).fetchone()
        if prior is not None:
            previous_observed = _aware_clock(prior["postcommit_observed_at"])
            previous = _canonical_millisecond_clock(prior["postcommit_readback_at"])
            if previous_observed is None or previous is None:
                _integrity("PROFILED_OUTCOME_PRIOR_POSTCOMMIT_CLOCK_INVALID")
            if postcommit_observed <= previous_observed:
                _validation("PROFILED_OUTCOME_INTERNAL_CLOCK_NOT_MONOTONIC")
            if candidate <= previous:
                candidate = previous + timedelta(milliseconds=1)
        return postcommit_observed_at, _format_millisecond(candidate)

    def _observed_head_catalog_digests(self) -> set[str]:
        root = _head_catalog_root(self.path)
        sha_root = root / "sha256"
        try:
            root_stat = os.stat(root, follow_symlinks=False)
        except FileNotFoundError:
            return set()
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID"
            ) from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            _integrity("PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID")
        try:
            sha_stat = os.stat(sha_root, follow_symlinks=False)
        except FileNotFoundError:
            return set()
        except OSError as exc:
            raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                "PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID"
            ) from exc
        if not stat.S_ISDIR(sha_stat.st_mode):
            _integrity("PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID")
        observed: set[str] = set()
        directory_count = 0
        for first in sha_root.iterdir():
            directory_count += 1
            if directory_count > 256:
                _integrity("PROFILED_OUTCOME_HEAD_CATALOG_RESOURCE_BOUND_EXCEEDED")
            try:
                first_stat = os.stat(first, follow_symlinks=False)
            except OSError as exc:
                raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                    "PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID"
                ) from exc
            if (
                not stat.S_ISDIR(first_stat.st_mode)
                or _SHA256_SHARD_RE.fullmatch(first.name) is None
            ):
                _integrity("PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID")
            shard_payload_count = 0
            for payload in first.iterdir():
                if len(observed) >= _MAX_LEDGER_RECORDS:
                    _integrity(
                        "PROFILED_OUTCOME_HEAD_CATALOG_RESOURCE_BOUND_EXCEEDED"
                    )
                try:
                    payload_stat = os.stat(payload, follow_symlinks=False)
                except OSError as exc:
                    raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                        "PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID"
                    ) from exc
                if (
                    not stat.S_ISREG(payload_stat.st_mode)
                    or payload_stat.st_size > _MAX_JSON_BYTES
                    or _strict_sha256(payload.name) is None
                    or payload.name[:2] != first.name
                ):
                    _integrity("PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID")
                observed.add(payload.name)
                shard_payload_count += 1
            if shard_payload_count == 0:
                _integrity("PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID")
        return observed

    def _publish_head_catalog(self, *, transaction_id: str) -> None:
        connection = self._connect_readonly()
        try:
            row = connection.execute(
                """
                SELECT head_anchor_sha256, head_anchor_byte_count,
                       head_anchor_relative_path, head_anchor_json
                FROM profiled_finalized_outcome_head_anchors
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            _integrity("PROFILED_OUTCOME_HEAD_ANCHOR_MISSING")
        address = _address_from_columns(
            sha256=row["head_anchor_sha256"],
            byte_count=row["head_anchor_byte_count"],
            relative_path=row["head_anchor_relative_path"],
        )
        catalog = ImmutableSourcePayloadStore(_head_catalog_root(self.path))
        payload = cast(str, row["head_anchor_json"]).encode("ascii")
        published = _put_exact(catalog, payload)
        if published != address:
            _integrity("PROFILED_OUTCOME_HEAD_CATALOG_PUBLICATION_INVALID")

    def _verify_head_catalog(self, rows: Sequence[sqlite3.Row]) -> int:
        expected = {
            cast(str, row["head_anchor_sha256"])
            for row in rows
            if row["head_anchor_sha256"] is not None
        }
        if self._observed_head_catalog_digests() != expected:
            _integrity("PROFILED_OUTCOME_HEAD_CATALOG_MEMBERSHIP_INVALID")
        catalog = ImmutableSourcePayloadStore(_head_catalog_root(self.path))
        for row in rows:
            if row["head_anchor_sha256"] is None:
                continue
            address = _address_from_columns(
                sha256=row["head_anchor_sha256"],
                byte_count=row["head_anchor_byte_count"],
                relative_path=row["head_anchor_relative_path"],
            )
            payload = _get_exact(
                catalog,
                address,
                reason="PROFILED_OUTCOME_HEAD_CATALOG_REOPEN_FAILED",
            )
            if payload != cast(str, row["head_anchor_json"]).encode("ascii"):
                _integrity("PROFILED_OUTCOME_HEAD_CATALOG_MISMATCH")
        return len(expected)

    @staticmethod
    def _verify_outcome_cas(
        rows: Sequence[sqlite3.Row], *, store: ImmutableSourcePayloadStore
    ) -> tuple[int, int]:
        candle_addresses: dict[str, SourcePayloadAddress] = {}
        for row in rows:
            address = _address_from_columns(
                sha256=row["outcome_artifact_sha256"],
                byte_count=row["outcome_artifact_byte_count"],
                relative_path=row["outcome_artifact_relative_path"],
            )
            payload = _get_exact(
                store,
                address,
                reason="PROFILED_OUTCOME_CAS_REOPEN_FAILED",
            )
            if payload != cast(str, row["outcome_artifact_json"]).encode("ascii"):
                _integrity("PROFILED_OUTCOME_CAS_LEDGER_MISMATCH")
            artifact = _parse_exact_object(
                payload,
                reason="PROFILED_OUTCOME_ARTIFACT_JSON_INVALID",
            )
            hypothesis, _label, _economics, _calibration = (
                _validate_artifact_structure(artifact)
            )
            inventory = cast(list[dict[str, Any]], artifact["label_candle_inventory"])
            for item in inventory:
                candle_address = _address_from_mapping(
                    item["candle_cas_address"],
                    reason="PROFILED_OUTCOME_CANDLE_INVENTORY_ADDRESS_INVALID",
                )
                prior = candle_addresses.get(candle_address.payload_sha256)
                if prior is not None and prior != candle_address:
                    _integrity("PROFILED_OUTCOME_CANDLE_CAS_IDENTITY_CONFLICT")
                candle_addresses[candle_address.payload_sha256] = candle_address
                candle_payload = _get_exact(
                    store,
                    candle_address,
                    reason="PROFILED_OUTCOME_CANDLE_CAS_REOPEN_FAILED",
                )
                try:
                    candle_json = candle_payload.decode("ascii", errors="strict")
                    candle = json.loads(candle_json)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                        "PROFILED_OUTCOME_CANDLE_CAS_PAYLOAD_INVALID"
                    ) from exc
                if type(candle) is not dict:
                    _integrity("PROFILED_OUTCOME_CANDLE_CAS_PAYLOAD_INVALID")
                try:
                    validated = validate_canonical_finalized_5m_candle(
                        candle,
                        expected_symbol=cast(str, hypothesis["symbol"]),
                    )
                except Canonical5mValidationError as exc:
                    raise ProfiledResearchFinalizedOutcomeV1IntegrityError(
                        "PROFILED_OUTCOME_CANDLE_CAS_PAYLOAD_INVALID"
                    ) from exc
                if (
                    canonical_candle_json(candle) != candle_json
                    or validated["candle_id"] != item["candle_id"]
                    or validated["open_time_ms"] != item["candle_open_time_ms"]
                    or validated["close_time_ms"] != item["candle_close_time_ms"]
                    or validated["available_at_ms"] != item["available_at_ms"]
                    or validated["raw_payload_hash"] != item["raw_payload_hash"]
                    or validated["market_fact_sha256"]
                    != item["market_fact_sha256"]
                    or validated["content_sha256"] != item["content_sha256"]
                ):
                    _integrity("PROFILED_OUTCOME_CANDLE_CAS_INVENTORY_MISMATCH")
        return len(rows), len(candle_addresses)

    def _write_postcommit(
        self,
        *,
        transaction_id: str,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease,
    ) -> None:
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _report, rows = self._verify_database(
                connection, require_postcommit=False
            )
            matches = [row for row in rows if row["transaction_id"] == transaction_id]
            if len(matches) != 1:
                _integrity("PROFILED_OUTCOME_POSTCOMMIT_TRANSACTION_MISSING")
            row = matches[0]
            if row["postcommit_readback_at"] is None:
                post_observed_at, post_at = self._next_postcommit_clock(
                    connection,
                    commit_observed_at=cast(str, row["commit_observed_at"]),
                    commit_prepared_at=cast(str, row["commit_prepared_at"]),
                )
                post_material = {
                    "schema_version": (
                        PROFILED_RESEARCH_FINALIZED_OUTCOME_POSTCOMMIT_V1_SCHEMA_VERSION
                    ),
                    "transaction_id": row["transaction_id"],
                    "append_receipt_sha256": row["append_receipt_sha256"],
                    "outcome_artifact_sha256": row["outcome_artifact_sha256"],
                    "record_chain_sha256": row["record_chain_sha256"],
                    "postcommit_observed_at": post_observed_at,
                    "postcommit_readback_at": post_at,
                    "independent_readback_verified": True,
                    "authorization": dict(_AUTHORIZATION),
                }
                post_json = _canonical_json(
                    post_material,
                    reason="PROFILED_OUTCOME_POSTCOMMIT_RECEIPT_JSON_INVALID",
                )
                post_sha = hashlib.sha256(post_json.encode("ascii")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO profiled_finalized_outcome_postcommit_receipts(
                        transaction_id, append_receipt_sha256,
                        outcome_artifact_sha256, record_chain_sha256,
                        readback_receipt_sha256, readback_receipt_json,
                        postcommit_observed_at, postcommit_readback_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["transaction_id"],
                        row["append_receipt_sha256"],
                        row["outcome_artifact_sha256"],
                        row["record_chain_sha256"],
                        post_sha,
                        post_json,
                        post_observed_at,
                        post_at,
                    ),
                )
                sequence = cast(int, row["sequence"])
                prior = connection.execute(
                    """
                    SELECT sequence, head_anchor_sha256
                    FROM profiled_finalized_outcome_head_anchors
                    ORDER BY sequence DESC LIMIT 1
                    """
                ).fetchone()
                if sequence == 1:
                    if prior is not None:
                        _integrity("PROFILED_OUTCOME_HEAD_ORDER_INVALID")
                    previous_head = _GENESIS_HEAD_ANCHOR_SHA256
                else:
                    if prior is None or prior["sequence"] != sequence - 1:
                        _integrity("PROFILED_OUTCOME_HEAD_ORDER_INVALID")
                    previous_head = cast(str, prior["head_anchor_sha256"])
                head_material = {
                    "schema_version": (
                        PROFILED_RESEARCH_FINALIZED_OUTCOME_HEAD_ANCHOR_V1_SCHEMA_VERSION
                    ),
                    "sequence": sequence,
                    "transaction_id": row["transaction_id"],
                    "outcome_artifact_sha256": row["outcome_artifact_sha256"],
                    "record_chain_sha256": row["record_chain_sha256"],
                    "append_receipt_sha256": row["append_receipt_sha256"],
                    "postcommit_receipt_sha256": post_sha,
                    "previous_head_anchor_sha256": previous_head,
                    "postcommit_observed_at": post_observed_at,
                    "anchored_at": post_at,
                    "authorization": dict(_AUTHORIZATION),
                }
                head_json = _canonical_json(
                    head_material,
                    reason="PROFILED_OUTCOME_HEAD_ANCHOR_JSON_INVALID",
                )
                head_address = _expected_address(head_json.encode("ascii"))
                connection.execute(
                    """
                    INSERT INTO profiled_finalized_outcome_head_anchors(
                        sequence, transaction_id, outcome_artifact_sha256,
                        record_chain_sha256, append_receipt_sha256,
                        postcommit_receipt_sha256, previous_head_anchor_sha256,
                        head_anchor_sha256, head_anchor_byte_count,
                        head_anchor_relative_path, head_anchor_json, anchored_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        row["transaction_id"],
                        row["outcome_artifact_sha256"],
                        row["record_chain_sha256"],
                        row["append_receipt_sha256"],
                        post_sha,
                        previous_head,
                        head_address.payload_sha256,
                        head_address.payload_byte_count,
                        head_address.relative_path,
                        head_json,
                        post_at,
                    ),
                )
            self._verify_database(connection, require_postcommit=True)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        self._publish_head_catalog(transaction_id=transaction_id)

    def recover_pending_postcommit_readbacks(
        self,
        *,
        store: object,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease | None = None,
    ) -> dict[str, int | str]:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("PROFILED_OUTCOME_EXACT_IMMUTABLE_STORE_REQUIRED")
        exact_store = store
        with self.writer_lease(writer_lease) as held:
            self._ensure_initialized(writer_lease=held)
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_database(
                    connection, require_postcommit=False
                )
                pending = [row for row in rows if row["postcommit_readback_at"] is None]
                connection.commit()
            finally:
                connection.close()
            self._verify_outcome_cas(pending, store=exact_store)
            for row in pending:
                self._write_postcommit(
                    transaction_id=cast(str, row["transaction_id"]),
                    writer_lease=held,
                )
            final = self._connect_readonly()
            try:
                final.execute("BEGIN")
                report, rows = self._verify_database(
                    final, require_postcommit=True
                )
                final.commit()
            finally:
                final.close()
            for row in rows:
                self._publish_head_catalog(
                    transaction_id=cast(str, row["transaction_id"])
                )
            self._verify_head_catalog(rows)
            return {
                "status": "PROFILED_OUTCOME_POSTCOMMIT_RECOVERY_COMPLETE",
                "pending_transactions": len(pending),
                "recovered_transactions": len(pending),
                "total_finalized_outcomes": report.total_finalized_outcomes,
            }

    def mature_hypothesis(
        self,
        *,
        committed_hypothesis: object,
        label_archive: object,
        store: object,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease | None = None,
    ) -> DurablyMaturedProfiledResearchFinalizedOutcomeV1:
        if type(committed_hypothesis) is not DurablyCommittedProfiledResearchShadowHypothesisV1:
            _validation("PROFILED_OUTCOME_EXACT_COMMITTED_HYPOTHESIS_REQUIRED")
        if type(label_archive) is not DurableCanonical5mLabelArchive:
            _validation("PROFILED_OUTCOME_EXACT_LABEL_ARCHIVE_REQUIRED")
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("PROFILED_OUTCOME_EXACT_IMMUTABLE_STORE_REQUIRED")
        committed = committed_hypothesis
        archive = label_archive
        exact_store = store
        hypothesis_binding, _raw = _hypothesis_binding(committed)
        with self.writer_lease(writer_lease) as held:
            self._ensure_initialized(writer_lease=held)
            self.recover_pending_postcommit_readbacks(
                store=exact_store, writer_lease=held
            )
            existing_connection = self._connect_readonly()
            try:
                existing_connection.execute("BEGIN")
                _report, existing_rows = self._verify_database(
                    existing_connection, require_postcommit=True
                )
                matches = [
                    row
                    for row in existing_rows
                    if row["hypothesis_identity_sha256"]
                    == hypothesis_binding["hypothesis_identity_sha256"]
                ]
                existing_connection.commit()
            finally:
                existing_connection.close()
            if matches:
                if len(matches) != 1:
                    _integrity("PROFILED_OUTCOME_DUPLICATE_IDENTITY_INVALID")
                return self._open_row_under_writer(
                    row=matches[0],
                    committed=committed,
                    archive=archive,
                    store=exact_store,
                    writer_lease=held,
                )

            observed_at, _observed_clock = _internally_observed_clock()
            prepared = _prepare_new_outcome(
                committed=committed,
                archive=archive,
                store=exact_store,
                observed_at=observed_at,
            )
            transaction_id = "profiled_outcome_" + _sha256(
                {
                    "domain": "v2/native-trainer/profiled-finalized-outcome-operation/v1",
                    "hypothesis_identity_sha256": prepared.hypothesis_identity_sha256,
                    "outcome_artifact_sha256": prepared.artifact_address.payload_sha256,
                }
            )[:32]
            connection = self._connect_write(writer_lease=held)
            try:
                connection.execute("BEGIN IMMEDIATE")
                report, rows = self._verify_database(
                    connection, require_postcommit=True
                )
                conflicts = [
                    row
                    for row in rows
                    if row["hypothesis_identity_sha256"]
                    == prepared.hypothesis_identity_sha256
                    or row["hypothesis_artifact_sha256"]
                    == prepared.hypothesis_artifact_sha256
                    or row["transaction_id"] == transaction_id
                ]
                if conflicts:
                    raise ProfiledResearchFinalizedOutcomeV1ConflictError(
                        "PROFILED_OUTCOME_IMMUTABLE_IDENTITY_CONFLICT"
                    )
                if report.total_finalized_outcomes >= _MAX_LEDGER_RECORDS:
                    _integrity("PROFILED_OUTCOME_LEDGER_RECORD_BOUND_EXCEEDED")
                sequence = report.total_finalized_outcomes + 1
                previous_chain = report.chain_head_sha256
                commit_observed_at, commit_at = self._next_commit_clock(
                    connection,
                    maturation_observed_at=prepared.maturation_observed_at,
                )
                record_chain = _sha256(
                    {
                        "domain": "v2/native-trainer/profiled-finalized-outcome-chain/v1",
                        "sequence": sequence,
                        "previous_chain_sha256": previous_chain,
                        "hypothesis_identity_sha256": prepared.hypothesis_identity_sha256,
                        "outcome_artifact_sha256": prepared.artifact_address.payload_sha256,
                        "outcome_material_sha256": prepared.outcome_material_sha256,
                        "maturation_observed_at": prepared.maturation_observed_at,
                        "commit_observed_at": commit_observed_at,
                        "transaction_id": transaction_id,
                        "commit_prepared_at": commit_at,
                    }
                )
                connection.execute(
                    """
                    INSERT INTO profiled_finalized_outcomes(
                        sequence, hypothesis_identity_sha256,
                        hypothesis_artifact_sha256,
                        commitment_append_receipt_sha256,
                        commitment_postcommit_receipt_sha256,
                        commitment_record_chain_sha256,
                        outcome_artifact_sha256, outcome_artifact_byte_count,
                        outcome_artifact_relative_path, outcome_artifact_json,
                        outcome_material_sha256, label_source_binding_sha256,
                        symbol, decision_time, label_earliest_available_at,
                        actual_label_available_at, maturation_observed_at,
                        selected_action, diagnostic_best_after_cost_action,
                        calibration_eligible,
                        previous_chain_sha256, record_chain_sha256,
                        transaction_id, commit_observed_at, commit_prepared_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        sequence,
                        prepared.hypothesis_identity_sha256,
                        prepared.hypothesis_artifact_sha256,
                        committed.append_receipt_sha256,
                        committed.postcommit_readback_receipt_sha256,
                        committed.record_chain_sha256,
                        prepared.artifact_address.payload_sha256,
                        prepared.artifact_address.payload_byte_count,
                        prepared.artifact_address.relative_path,
                        prepared.artifact_bytes.decode("ascii"),
                        prepared.outcome_material_sha256,
                        prepared.label_source_binding_sha256,
                        prepared.symbol,
                        prepared.decision_time,
                        prepared.label_earliest_available_at,
                        prepared.actual_label_available_at,
                        prepared.maturation_observed_at,
                        prepared.selected_action,
                        prepared.diagnostic_best_after_cost_action,
                        int(prepared.calibration_eligible),
                        previous_chain,
                        record_chain,
                        transaction_id,
                        commit_observed_at,
                        commit_at,
                    ),
                )
                append_material = {
                    "schema_version": (
                        PROFILED_RESEARCH_FINALIZED_OUTCOME_APPEND_RECEIPT_V1_SCHEMA_VERSION
                    ),
                    "transaction_id": transaction_id,
                    "hypothesis_identity_sha256": prepared.hypothesis_identity_sha256,
                    "outcome_artifact_sha256": prepared.artifact_address.payload_sha256,
                    "previous_chain_sha256": previous_chain,
                    "record_chain_sha256": record_chain,
                    "total_finalized_outcomes": sequence,
                    "maturation_observed_at": prepared.maturation_observed_at,
                    "commit_observed_at": commit_observed_at,
                    "commit_prepared_at": commit_at,
                    "precommit_readback_verified": True,
                    "authorization": dict(_AUTHORIZATION),
                }
                append_json = _canonical_json(
                    append_material,
                    reason="PROFILED_OUTCOME_APPEND_RECEIPT_JSON_INVALID",
                )
                append_sha = hashlib.sha256(append_json.encode("ascii")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO profiled_finalized_outcome_append_receipts(
                        transaction_id, hypothesis_identity_sha256,
                        outcome_artifact_sha256, previous_chain_sha256,
                        record_chain_sha256, total_finalized_outcomes,
                        receipt_sha256, receipt_json, maturation_observed_at,
                        commit_observed_at, commit_prepared_at,
                        precommit_readback_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        transaction_id,
                        prepared.hypothesis_identity_sha256,
                        prepared.artifact_address.payload_sha256,
                        previous_chain,
                        record_chain,
                        sequence,
                        append_sha,
                        append_json,
                        prepared.maturation_observed_at,
                        commit_observed_at,
                        commit_at,
                    ),
                )
                pre_report, pre_rows = self._verify_database(
                    connection, require_postcommit=False
                )
                if (
                    pre_report.total_finalized_outcomes != sequence
                    or len(pre_rows) != sequence
                ):
                    _integrity("PROFILED_OUTCOME_PRECOMMIT_READBACK_FAILED")
                connection.commit()
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise ProfiledResearchFinalizedOutcomeV1ConflictError(
                    "PROFILED_OUTCOME_SQLITE_IDENTITY_CONFLICT"
                ) from exc
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
            self._write_postcommit(transaction_id=transaction_id, writer_lease=held)
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_database(
                    connection, require_postcommit=True
                )
                row = [item for item in rows if item["transaction_id"] == transaction_id][0]
                connection.commit()
            finally:
                connection.close()
            return self._open_row_under_writer(
                row=row,
                committed=committed,
                archive=archive,
                store=exact_store,
                writer_lease=held,
            )

    def _make_result(
        self,
        *,
        row: sqlite3.Row,
        prepared: _PreparedOutcome,
        committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
        archive: DurableCanonical5mLabelArchive,
        store: ImmutableSourcePayloadStore,
        validation_writer_lease: (
            ProfiledResearchFinalizedOutcomeWriterLease | None
        ),
    ) -> DurablyMaturedProfiledResearchFinalizedOutcomeV1:
        public = {
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_sha256": row["hypothesis_artifact_sha256"],
            "outcome_artifact_sha256": row["outcome_artifact_sha256"],
            "outcome_artifact_byte_count": row["outcome_artifact_byte_count"],
            "outcome_artifact_address": prepared.artifact_address,
            "outcome_material_sha256": row["outcome_material_sha256"],
            "label_source_binding_sha256": row["label_source_binding_sha256"],
            "symbol": row["symbol"],
            "decision_time": row["decision_time"],
            "label_earliest_available_at": row["label_earliest_available_at"],
            "actual_label_available_at": row["actual_label_available_at"],
            "maturation_observed_at": row["maturation_observed_at"],
            "selected_action": row["selected_action"],
            "diagnostic_best_after_cost_action": row[
                "diagnostic_best_after_cost_action"
            ],
            "calibration_eligible": row["calibration_eligible"] == 1,
            "checkpoint_id": prepared.checkpoint_id,
            "checkpoint_generation": prepared.checkpoint_generation,
            "model_parameter_fingerprint": prepared.model_parameter_fingerprint,
            "model_binding_sha256": prepared.model_binding_sha256,
            "transaction_id": row["transaction_id"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "postcommit_readback_receipt_sha256": row["readback_receipt_sha256"],
            "record_chain_sha256": row["record_chain_sha256"],
            "commit_observed_at": row["commit_observed_at"],
            "commit_prepared_at": row["commit_prepared_at"],
            "postcommit_observed_at": row["postcommit_observed_at"],
            "postcommit_readback_at": row["postcommit_readback_at"],
        }
        artifact_json = prepared.artifact_bytes.decode("ascii")
        seal = _result_seal(
            public=public,
            artifact_json=artifact_json,
            ledger=self,
            committed=committed,
            archive=archive,
            store=store,
        )
        return DurablyMaturedProfiledResearchFinalizedOutcomeV1(
            **public,
            _artifact_json=artifact_json,
            _ledger=self,
            _committed=committed,
            _archive=archive,
            _store=store,
            _validation_writer_lease=validation_writer_lease,
            _factory_seal=seal,
            _construction_token=_RESULT_TOKEN,
        )

    def _open_row_under_writer(
        self,
        *,
        row: sqlite3.Row,
        committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
        archive: DurableCanonical5mLabelArchive,
        store: ImmutableSourcePayloadStore,
        writer_lease: ProfiledResearchFinalizedOutcomeWriterLease,
    ) -> DurablyMaturedProfiledResearchFinalizedOutcomeV1:
        writer_lease.validate_for(self.path)
        address = _address_from_columns(
            sha256=row["outcome_artifact_sha256"],
            byte_count=row["outcome_artifact_byte_count"],
            relative_path=row["outcome_artifact_relative_path"],
        )
        prepared = _reopen_prepared(
            address=address,
            committed=committed,
            archive=archive,
            store=store,
        )
        self._verify_head_catalog(self._all_rows_readonly())
        writer_lease.validate_for(self.path)
        return self._make_result(
            row=row,
            prepared=prepared,
            committed=committed,
            archive=archive,
            store=store,
            validation_writer_lease=writer_lease,
        )

    def _all_rows_readonly(self) -> list[sqlite3.Row]:
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            _report, rows = self._verify_database(connection, require_postcommit=True)
            connection.commit()
            return rows
        finally:
            connection.close()

    def open_matured_outcome(
        self,
        *,
        hypothesis_artifact_sha256: object,
        committed_hypothesis: object,
        label_archive: object,
        store: object,
    ) -> DurablyMaturedProfiledResearchFinalizedOutcomeV1:
        if _strict_sha256(hypothesis_artifact_sha256) is None:
            _validation("PROFILED_OUTCOME_HYPOTHESIS_SHA256_INVALID")
        if type(committed_hypothesis) is not DurablyCommittedProfiledResearchShadowHypothesisV1:
            _validation("PROFILED_OUTCOME_EXACT_COMMITTED_HYPOTHESIS_REQUIRED")
        if type(label_archive) is not DurableCanonical5mLabelArchive:
            _validation("PROFILED_OUTCOME_EXACT_LABEL_ARCHIVE_REQUIRED")
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("PROFILED_OUTCOME_EXACT_IMMUTABLE_STORE_REQUIRED")
        committed = committed_hypothesis
        archive = label_archive
        exact_store = store
        with self._reader_lease():
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_database(
                    connection, require_postcommit=True
                )
                matches = [
                    row
                    for row in rows
                    if row["hypothesis_artifact_sha256"]
                    == hypothesis_artifact_sha256
                ]
                if len(matches) != 1:
                    _validation("PROFILED_OUTCOME_NOT_FOUND")
                row = matches[0]
                connection.commit()
            finally:
                connection.close()
            if committed.hypothesis_artifact_sha256 != hypothesis_artifact_sha256:
                _integrity("PROFILED_OUTCOME_COMMITTED_HYPOTHESIS_MISMATCH")
            address = _address_from_columns(
                sha256=row["outcome_artifact_sha256"],
                byte_count=row["outcome_artifact_byte_count"],
                relative_path=row["outcome_artifact_relative_path"],
            )
            prepared = _reopen_prepared(
                address=address,
                committed=committed,
                archive=archive,
                store=exact_store,
            )
            self._verify_head_catalog(rows)
            return self._make_result(
                row=row,
                prepared=prepared,
                committed=committed,
                archive=archive,
                store=exact_store,
                validation_writer_lease=self._writer_lease,
            )

    def verify_integrity(
        self, *, store: object
    ) -> ProfiledResearchFinalizedOutcomeIntegrityV1:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("PROFILED_OUTCOME_EXACT_IMMUTABLE_STORE_REQUIRED")
        exact_store = store
        with self._reader_lease():
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                report, rows = self._verify_database(
                    connection, require_postcommit=True
                )
                connection.commit()
            finally:
                connection.close()
            cas, candle_cas = self._verify_outcome_cas(rows, store=exact_store)
            heads = self._verify_head_catalog(rows)
            return ProfiledResearchFinalizedOutcomeIntegrityV1(
                total_finalized_outcomes=report.total_finalized_outcomes,
                append_receipts_verified=report.append_receipts_verified,
                postcommit_receipts_verified=report.postcommit_receipts_verified,
                head_anchors_verified=report.head_anchors_verified,
                cas_outcomes_verified=cas,
                cas_label_candles_verified=candle_cas,
                cas_head_anchors_verified=heads,
                calibration_eligible_rows=report.calibration_eligible_rows,
                calibration_ineligible_rows=report.calibration_ineligible_rows,
                chain_head_sha256=report.chain_head_sha256,
                schema_verified=True,
                clock_causality_verified=report.clock_causality_verified,
            )


_RESULT_PUBLIC_FIELDS: Final = (
    "hypothesis_identity_sha256",
    "hypothesis_artifact_sha256",
    "outcome_artifact_sha256",
    "outcome_artifact_byte_count",
    "outcome_artifact_address",
    "outcome_material_sha256",
    "label_source_binding_sha256",
    "symbol",
    "decision_time",
    "label_earliest_available_at",
    "actual_label_available_at",
    "maturation_observed_at",
    "selected_action",
    "diagnostic_best_after_cost_action",
    "calibration_eligible",
    "checkpoint_id",
    "checkpoint_generation",
    "model_parameter_fingerprint",
    "model_binding_sha256",
    "transaction_id",
    "append_receipt_sha256",
    "postcommit_readback_receipt_sha256",
    "record_chain_sha256",
    "commit_observed_at",
    "commit_prepared_at",
    "postcommit_observed_at",
    "postcommit_readback_at",
)


def _public_material(
    result: DurablyMaturedProfiledResearchFinalizedOutcomeV1,
) -> dict[str, Any]:
    material = {name: getattr(result, name) for name in _RESULT_PUBLIC_FIELDS}
    address = material["outcome_artifact_address"]
    if type(address) is not SourcePayloadAddress:
        _integrity("PROFILED_OUTCOME_RESULT_ADDRESS_INVALID")
    material["outcome_artifact_address"] = _address_mapping(address)
    return material


def _result_seal(
    *,
    public: Mapping[str, Any],
    artifact_json: str,
    ledger: ProfiledResearchFinalizedOutcomeLedgerV1,
    committed: DurablyCommittedProfiledResearchShadowHypothesisV1,
    archive: DurableCanonical5mLabelArchive,
    store: ImmutableSourcePayloadStore,
) -> str:
    normalized = dict(public)
    address = normalized.get("outcome_artifact_address")
    if type(address) is not SourcePayloadAddress:
        _integrity("PROFILED_OUTCOME_RESULT_ADDRESS_INVALID")
    normalized["outcome_artifact_address"] = _address_mapping(address)
    material = {
        "domain": "v2/native-trainer/profiled-finalized-outcome-result/v1",
        "public": normalized,
        "artifact_json_sha256": hashlib.sha256(artifact_json.encode("ascii")).hexdigest(),
        "ledger_path": str(ledger.path),
        "commitment_artifact_sha256": committed.hypothesis_artifact_sha256,
        "archive_path": str(archive.path),
        "store_root_path": str(store.root_path),
        "ledger_process_identity": id(ledger),
        "commitment_process_identity": id(committed),
        "archive_process_identity": id(archive),
        "store_process_identity": id(store),
    }
    return hmac.new(
        _RESULT_SEAL_KEY,
        _canonical_bytes(material, reason="PROFILED_OUTCOME_RESULT_SEAL_INVALID"),
        hashlib.sha256,
    ).hexdigest()


def _validated_result(
    result: DurablyMaturedProfiledResearchFinalizedOutcomeV1,
) -> dict[str, Any]:
    if (
        type(result) is not DurablyMaturedProfiledResearchFinalizedOutcomeV1
        or result._construction_token is not _RESULT_TOKEN
        or type(result._ledger) is not ProfiledResearchFinalizedOutcomeLedgerV1
        or type(result._committed)
        is not DurablyCommittedProfiledResearchShadowHypothesisV1
        or type(result._archive) is not DurableCanonical5mLabelArchive
        or type(result._store) is not ImmutableSourcePayloadStore
        or (
            result._validation_writer_lease is not None
            and type(result._validation_writer_lease)
            is not ProfiledResearchFinalizedOutcomeWriterLease
        )
        or type(result._artifact_json) is not str
        or _strict_sha256(result._factory_seal) is None
    ):
        _integrity("PROFILED_OUTCOME_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
    public = {name: getattr(result, name) for name in _RESULT_PUBLIC_FIELDS}
    expected_seal = _result_seal(
        public=public,
        artifact_json=result._artifact_json,
        ledger=result._ledger,
        committed=result._committed,
        archive=result._archive,
        store=result._store,
    )
    if not hmac.compare_digest(result._factory_seal, expected_seal):
        _integrity("PROFILED_OUTCOME_RESULT_FACTORY_SEAL_INVALID")
    validation_writer = result._validation_writer_lease
    if validation_writer is not None:
        try:
            validation_writer.validate_for(result._ledger.path)
        except ProfiledResearchFinalizedOutcomeWriterLeaseError as exc:
            if exc.reason != "PROFILED_OUTCOME_WRITER_LEASE_NOT_HELD":
                raise
            validation_writer = None
    if validation_writer is None:
        reopened = result._ledger.open_matured_outcome(
            hypothesis_artifact_sha256=result.hypothesis_artifact_sha256,
            committed_hypothesis=result._committed,
            label_archive=result._archive,
            store=result._store,
        )
    else:
        rows = result._ledger._all_rows_readonly()  # noqa: SLF001
        matches = [
            row
            for row in rows
            if row["hypothesis_artifact_sha256"]
            == result.hypothesis_artifact_sha256
        ]
        if len(matches) != 1:
            _integrity("PROFILED_OUTCOME_RESULT_LEDGER_ROW_MISSING")
        reopened = result._ledger._open_row_under_writer(  # noqa: SLF001
            row=matches[0],
            committed=result._committed,
            archive=result._archive,
            store=result._store,
            writer_lease=validation_writer,
        )
        validation_writer.validate_for(result._ledger.path)
    if (
        _public_material(reopened) != _public_material(result)
        or reopened._artifact_json != result._artifact_json
    ):
        _integrity("PROFILED_OUTCOME_RESULT_DURABLE_BINDING_INVALID")
    return _parse_exact_object(
        result._artifact_json,
        reason="PROFILED_OUTCOME_RESULT_ARTIFACT_JSON_INVALID",
    )


__all__ = (
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_APPEND_RECEIPT_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_CALIBRATION_ROW_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_HEAD_ANCHOR_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_LEDGER_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_MODEL_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_POSTCOMMIT_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_CLASSIFICATION",
    "PROFILED_RESEARCH_FINALIZED_OUTCOME_V1_SCHEMA_VERSION",
    "DurablyMaturedProfiledResearchFinalizedOutcomeV1",
    "ProfiledResearchFinalizedOutcomeIntegrityV1",
    "ProfiledResearchFinalizedOutcomeLedgerV1",
    "ProfiledResearchFinalizedOutcomeV1ConflictError",
    "ProfiledResearchFinalizedOutcomeV1Error",
    "ProfiledResearchFinalizedOutcomeV1IntegrityError",
    "ProfiledResearchFinalizedOutcomeV1ValidationError",
    "ProfiledResearchFinalizedOutcomeWriterLease",
    "ProfiledResearchFinalizedOutcomeWriterLeaseError",
)
