"""Durable ex-ante commitment for quarantined profiled hypotheses.

This module is an intentionally unwired paper/research primitive.  It binds an
exact factory-built shadow hypothesis to its complete portable causal-cost
closure, then appends the binding to an immutable SQLite chain before the
counterfactual label can exist.  The database transaction contains the
hypothesis row, append receipt, and pending-index row.  A separate transaction
records an independently reopened post-commit readback receipt.

No label value, outcome, calibration datum, trainer admission, signal, order,
exchange connection, Redis value, or runtime service is accepted or produced.
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
from collections.abc import Iterator, Mapping
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
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.locally_authenticated_profiled_research_inference_v1 import (  # noqa: E501
    LOCAL_PROFILED_RESEARCH_INFERENCE_V2_SCHEMA_VERSION,
    LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V2_CLASSIFICATION,
    LocallyAuthenticatedProfiledResearchInferenceV1Error,
    validate_portable_profiled_research_raw_inference_v2_payload,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_portable_closure_v1 import (  # noqa: E501
    PaperResearchCausalCostPortableClosureV1,
    PaperResearchCausalCostPortableClosureV1Error,
    open_paper_research_causal_cost_portable_closure_v1,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_v1 import (  # noqa: E501
    PROFILED_RESEARCH_COST_BINDING_V1_SCHEMA_VERSION,
    PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE,
    PROFILED_RESEARCH_DECISION_REFERENCE_V1_SCHEMA_VERSION,
    PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION,
    PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION,
    ProfiledResearchShadowHypothesisArtifactV1,
    ProfiledResearchShadowHypothesisV1Error,
)

PROFILED_RESEARCH_SHADOW_COMMITMENT_LEDGER_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_commitment_ledger_v1"
)
PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_commitment_v1"
)
PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION: Final = (
    "DURABLE_EX_ANTE_PROFILED_RESEARCH_SHADOW_HYPOTHESIS_NO_AUTHORITY_V1"
)
PROFILED_RESEARCH_SHADOW_COMMITMENT_APPEND_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_commitment_append_receipt_v1"
)
PROFILED_RESEARCH_SHADOW_COMMITMENT_POSTCOMMIT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_commitment_postcommit_readback_v1"
)
PROFILED_RESEARCH_SHADOW_PENDING_INDEX_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_pending_index_v1"
)
PROFILED_RESEARCH_SHADOW_HEAD_ANCHOR_V1_SCHEMA_VERSION: Final = (
    "profiled_research_shadow_hypothesis_head_anchor_v1"
)

_APPLICATION_ID = 0x50534843
_USER_VERSION = 1
_GENESIS_CHAIN_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_SHADOW_COMMITMENT_LEDGER_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_GENESIS_HEAD_ANCHOR_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_SHADOW_HEAD_ANCHOR_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CANONICAL_UTC_MILLISECOND_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$", re.ASCII)
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}$", re.ASCII)
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_LEDGER_RECORDS = 65_536
_MAX_PENDING_RESULTS = 4_096
_MAX_LEDGER_AGGREGATE_JSON_BYTES = 64 * 1024 * 1024
_MAX_LEDGER_DATABASE_BYTES = 512 * 1024 * 1024
_BUSY_TIMEOUT_MS = 60_000
_RESULT_TOKEN = object()
_LEASE_TOKEN = object()
_RESULT_SEAL_KEY = secrets.token_bytes(32)

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

_COMMITMENT_STATUS: Final = {
    "durable_ex_ante_commit_receipt_present": True,
    "pending_hypothesis_index_registered": True,
    "portable_cost_source_closure_complete": True,
    "restart_reopen_supported": True,
    "postcommit_readback_receipt_present": True,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
}

_ORIGINAL_HYPOTHESIS_DURABILITY_STATUS: Final = {
    "status": (
        "QUARANTINED_DURABLE_COMMITMENT_AND_PORTABLE_SOURCE_CLOSURE_REQUIRED"
    ),
    "durable_ex_ante_commit_receipt_present": False,
    "pending_hypothesis_index_registered": False,
    "portable_cost_source_closure_complete": False,
    "restart_reopen_supported": False,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
}

_RAW_FALSE_AUTHORITY_FIELDS: Final = (
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "serving_authorized",
    "serving_activation_authorized",
    "serving_promotion_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "exchange_access_authorized",
    "deployment_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)

_HYPOTHESIS_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "raw_inference_payload",
        "raw_inference_binding_sha256",
        "cost_evidence_binding",
        "decision_reference_binding",
        "counterfactual_holding_horizon_seconds",
        "durability_status",
        "authorization",
        "local_research_non_promotable",
        "hypothesis_material_sha256",
    }
)

_COST_BINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "artifact_sha256",
        "artifact_byte_count",
        "artifact_cas_address",
        "evidence_id",
        "contract_material_sha256",
        "symbol",
        "feature_snapshot_identity",
        "decision_time",
        "counterfactual_holding_horizon_seconds",
        "ordered_feature_names",
        "ordered_values",
        "ordered_receipt_sha256s",
        "fee_source_authenticity_status",
        "market_source_authenticity_status",
        "account_specific_commission_authenticated",
        "research_only",
    }
)

_DECISION_REFERENCE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "source",
        "symbol",
        "feature_snapshot_identity",
        "decision_time",
        "best_bid",
        "best_ask",
        "mid",
        "expected_notional_usd",
        "spread_receipt_sha256",
        "orderbook_child_read_bindings",
        "exact_rederivation_sha256",
        "caller_supplied_price_used",
        "unfinished_candle_price_used",
    }
)

_METADATA: Final = {
    "ledger_schema_version": (
        PROFILED_RESEARCH_SHADOW_COMMITMENT_LEDGER_V1_SCHEMA_VERSION
    ),
    "retention_policy": "APPEND_ONLY_NO_AUTOMATIC_PRUNING",
    "automatic_pruning_enabled": "false",
    "label_values_accepted": "false",
    "runtime_wired": "false",
}


class ProfiledResearchShadowHypothesisCommitmentV1Error(RuntimeError):
    """Stable, payload-safe base error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProfiledResearchShadowHypothesisCommitmentV1ValidationError(
    ProfiledResearchShadowHypothesisCommitmentV1Error
):
    """A caller value is invalid or the ex-ante window has closed."""


class ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
    ProfiledResearchShadowHypothesisCommitmentV1Error
):
    """Durable bytes, schema, chain, receipt, or readback failed validation."""


class ProfiledResearchShadowHypothesisCommitmentV1ConflictError(
    ProfiledResearchShadowHypothesisCommitmentV1Error
):
    """An immutable hypothesis identity is already bound differently."""


class ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
    ProfiledResearchShadowHypothesisCommitmentV1Error
):
    """The exact path/inode writer lease is absent, stale, or contended."""


def _validation(reason: str) -> NoReturn:
    raise ProfiledResearchShadowHypothesisCommitmentV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(reason) from None


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


def _sha256(value: object, *, reason: str = "SHADOW_COMMITMENT_JSON_INVALID") -> str:
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
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_integrity(reason)),
        )
    except (
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        RecursionError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        _integrity(reason)
    if type(value) is not dict:
        _integrity(reason)
    try:
        canonical = _canonical_bytes(value, reason=reason)
    except ProfiledResearchShadowHypothesisCommitmentV1ValidationError:
        _integrity(reason)
    if canonical != raw:
        _integrity(reason)
    return cast(dict[str, Any], value)


def _strict_sha256(value: object) -> str | None:
    return value if type(value) is str and _SHA256_RE.fullmatch(value) else None


def _strict_positive_int(value: object, *, maximum: int | None = None) -> int | None:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        return None
    return value


def _strict_nonnegative_int(
    value: object,
    *,
    maximum: int | None = None,
) -> int | None:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        return None
    return value


def _finite_float(value: object, *, positive: bool = False) -> float | None:
    if type(value) is not float or not math.isfinite(value):
        return None
    if positive and value <= 0.0:
        return None
    return value


def _exact_typed_mapping(value: object, expected: Mapping[str, object]) -> bool:
    if type(value) is not dict or set(value) != set(expected):
        return False
    supplied = cast(dict[str, Any], value)
    for key, expected_value in expected.items():
        actual = supplied[key]
        if type(actual) is not type(expected_value) or actual != expected_value:
            return False
    return True


def _aware_clock(value: object) -> datetime | None:
    if type(value) is not str or not value or value != value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_millisecond_clock(value: object) -> datetime | None:
    if type(value) is not str or _CANONICAL_UTC_MILLISECOND_RE.fullmatch(value) is None:
        return None
    parsed = _aware_clock(value)
    if parsed is None or _format_millisecond(parsed) != value:
        return None
    return parsed


def _format_millisecond(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_microsecond(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _ceil_millisecond(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    floored = normalized.replace(
        microsecond=(normalized.microsecond // 1000) * 1000
    )
    if floored == normalized:
        return floored
    try:
        return floored + timedelta(milliseconds=1)
    except OverflowError:
        _integrity("SHADOW_COMMITMENT_CLOCK_CEILING_OVERFLOW")


def _utc_now() -> datetime:
    """Internal wall clock; tests replace this function, never a public argument."""

    return datetime.now(UTC)


def _expected_address(payload: bytes) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(payload),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )


def _address_mapping(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _address_from_columns(
    *,
    sha256: object,
    byte_count: object,
    relative_path: object,
) -> SourcePayloadAddress:
    if (
        _strict_sha256(sha256) is None
        or _strict_positive_int(byte_count, maximum=_MAX_JSON_BYTES) is None
        or type(relative_path) is not str
    ):
        _integrity("SHADOW_COMMITMENT_CAS_ADDRESS_INVALID")
    address = SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=cast(str, sha256),
        payload_byte_count=cast(int, byte_count),
        relative_path=cast(str, relative_path),
    )
    expected_relative = (
        f"sha256/{address.payload_sha256[:2]}/{address.payload_sha256}"
    )
    if address.relative_path != expected_relative:
        _integrity("SHADOW_COMMITMENT_CAS_ADDRESS_INVALID")
    return address


def _lexical_absolute_path(path: object) -> Path:
    if not isinstance(path, Path):
        _validation("SHADOW_COMMITMENT_LEDGER_PATH_EXACT_PATH_REQUIRED")
    candidate = cast(Path, path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


def _writer_lock_path(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".writer.lock")


class ProfiledResearchShadowHypothesisCommitmentWriterLease:
    """Nonblocking path-and-inode lease for the single sanctioned writer."""

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
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_FACTORY_REQUIRED"
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
    def acquire(
        cls,
        ledger_path: Path,
    ) -> ProfiledResearchShadowHypothesisCommitmentWriterLease:
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
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_OPEN_FAILED"
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
                raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                    "SHADOW_COMMITMENT_WRITER_LEASE_INODE_INVALID"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_ALREADY_HELD"
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
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_DATABASE_INODE_OPEN_FAILED"
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
                raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                    "SHADOW_COMMITMENT_DATABASE_INODE_INVALID"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_DATABASE_INODE_ALREADY_HELD"
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
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_PATH_MISMATCH"
            )
        if self._released or self._lock_fd < 0 or os.getpid() != self._owner_pid:
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_NOT_HELD"
            )
        try:
            descriptor_stat = os.fstat(self._lock_fd)
            path_stat = os.stat(self._lock_path, follow_symlinks=False)
        except OSError as exc:
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_BINDING_MISSING"
            ) from exc
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            != (self._lock_device, self._lock_inode)
            or (int(path_stat.st_dev), int(path_stat.st_ino))
            != (self._lock_device, self._lock_inode)
        ):
            raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                "SHADOW_COMMITMENT_WRITER_LEASE_BINDING_CHANGED"
            )
        if self._db_fd >= 0:
            try:
                db_stat = os.fstat(self._db_fd)
                db_path_stat = os.stat(self._ledger_path, follow_symlinks=False)
            except OSError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                    "SHADOW_COMMITMENT_DATABASE_BINDING_MISSING"
                ) from exc
            if (
                not stat.S_ISREG(db_stat.st_mode)
                or (int(db_stat.st_dev), int(db_stat.st_ino))
                != (self._db_device, self._db_inode)
                or (int(db_path_stat.st_dev), int(db_path_stat.st_ino))
                != (self._db_device, self._db_inode)
            ):
                raise ProfiledResearchShadowHypothesisCommitmentWriterLeaseError(
                    "SHADOW_COMMITMENT_DATABASE_BINDING_CHANGED"
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

    def __enter__(
        self,
    ) -> ProfiledResearchShadowHypothesisCommitmentWriterLease:
        self.validate_for(self._ledger_path)
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class _PreparedHypothesis:
    artifact_address: SourcePayloadAddress
    artifact_bytes: bytes
    artifact_contract: dict[str, Any] = field(repr=False)
    closure_address: SourcePayloadAddress
    cost_evidence_artifact_sha256: str
    hypothesis_identity_sha256: str
    raw_inference_binding_sha256: str
    hypothesis_material_sha256: str
    symbol: str
    durable_snapshot_id: str
    decision_time: str
    hypothesis_generated_at: str
    label_earliest_available_at: str
    holding_horizon_seconds: int


def _validate_address_mapping(
    value: object,
    *,
    expected: SourcePayloadAddress,
    reason: str,
) -> None:
    if type(value) is not dict or value != _address_mapping(expected):
        _integrity(reason)


def _validate_raw_inference_payload(
    value: object,
) -> tuple[dict[str, Any], datetime, datetime]:
    if type(value) is not dict:
        _integrity("SHADOW_COMMITMENT_RAW_INFERENCE_PAYLOAD_INVALID")
    try:
        payload = validate_portable_profiled_research_raw_inference_v2_payload(
            value
        )
    except LocallyAuthenticatedProfiledResearchInferenceV1Error as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_RAW_INFERENCE_PAYLOAD_INVALID"
        ) from exc
    binding = payload.get("hypothesis_binding_sha256")
    material = {key: item for key, item in payload.items() if key != "hypothesis_binding_sha256"}
    if (
        payload.get("schema_version")
        != LOCAL_PROFILED_RESEARCH_INFERENCE_V2_SCHEMA_VERSION
        or payload.get("classification")
        != LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V2_CLASSIFICATION
        or _strict_sha256(binding) is None
        or binding
        != _sha256(
            material,
            reason="SHADOW_COMMITMENT_RAW_INFERENCE_PAYLOAD_INVALID",
        )
        or payload.get("local_research_non_promotable") is not True
        or payload.get("external_witness_verified") is not False
        or payload.get("confidence_calibrated") is not None
        or payload.get("profitability_probability") is not None
        or payload.get("model_tensors_device_verified") is not True
        or type(payload.get("cuda_active")) is not bool
        or any(payload.get(field_name) is not False for field_name in _RAW_FALSE_AUTHORITY_FIELDS)
    ):
        _integrity("SHADOW_COMMITMENT_RAW_INFERENCE_PAYLOAD_INVALID")
    symbol = payload.get("symbol")
    durable_snapshot_id = payload.get("durable_snapshot_id")
    decision_time = payload.get("source_decision_time")
    generated_at = payload.get("hypothesis_generated_at")
    decision_clock = _aware_clock(decision_time)
    generated_clock = _aware_clock(generated_at)
    if (
        type(symbol) is not str
        or _SYMBOL_RE.fullmatch(symbol) is None
        or type(durable_snapshot_id) is not str
        or _IDENTITY_RE.fullmatch(durable_snapshot_id) is None
        or decision_clock is None
        or generated_clock is None
        or _format_microsecond(decision_clock) != decision_time
        or _format_microsecond(generated_clock) != generated_at
        or generated_clock < decision_clock
    ):
        _integrity("SHADOW_COMMITMENT_RAW_INFERENCE_IDENTITY_INVALID")
    return payload, decision_clock, generated_clock


def _validate_hypothesis_against_closure(
    *,
    artifact_bytes: bytes,
    artifact_address: SourcePayloadAddress,
    cost_closure: PaperResearchCausalCostPortableClosureV1,
) -> _PreparedHypothesis:
    if artifact_address != _expected_address(artifact_bytes):
        _integrity("SHADOW_COMMITMENT_HYPOTHESIS_ADDRESS_INVALID")
    contract = _parse_exact_object(
        artifact_bytes,
        reason="SHADOW_COMMITMENT_HYPOTHESIS_JSON_INVALID",
    )
    if (
        set(contract) != _HYPOTHESIS_FIELDS
        or contract.get("schema_version")
        != PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION
        or contract.get("classification")
        != PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION
        or not _exact_typed_mapping(contract.get("authorization"), _AUTHORIZATION)
        or not _exact_typed_mapping(
            contract.get("durability_status"),
            _ORIGINAL_HYPOTHESIS_DURABILITY_STATUS,
        )
        or contract.get("local_research_non_promotable") is not True
        or contract.get("counterfactual_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    ):
        _integrity("SHADOW_COMMITMENT_HYPOTHESIS_CONTRACT_INVALID")
    material = {
        key: value
        for key, value in contract.items()
        if key != "hypothesis_material_sha256"
    }
    hypothesis_material_sha256 = contract.get("hypothesis_material_sha256")
    if (
        _strict_sha256(hypothesis_material_sha256) is None
        or hypothesis_material_sha256
        != _sha256(material, reason="SHADOW_COMMITMENT_HYPOTHESIS_CONTRACT_INVALID")
    ):
        _integrity("SHADOW_COMMITMENT_HYPOTHESIS_MATERIAL_INVALID")

    raw, decision_clock, generated_clock = _validate_raw_inference_payload(
        contract.get("raw_inference_payload")
    )
    raw_binding = raw["hypothesis_binding_sha256"]
    if contract.get("raw_inference_binding_sha256") != raw_binding:
        _integrity("SHADOW_COMMITMENT_RAW_INFERENCE_BINDING_INVALID")

    try:
        closure_manifest = cost_closure.manifest
        cost_contract = cost_closure.cost_contract
        ordered_receipts = cost_closure.ordered_receipts
    except PaperResearchCausalCostPortableClosureV1Error as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_PORTABLE_COST_REVALIDATION_FAILED"
        ) from exc
    cost_binding = contract.get("cost_evidence_binding")
    if type(cost_binding) is not dict or set(cost_binding) != _COST_BINDING_FIELDS:
        _integrity("SHADOW_COMMITMENT_COST_BINDING_INVALID")
    binding = cast(dict[str, Any], cost_binding)
    cost_artifact_address = _expected_address(
        _canonical_bytes(
            cost_contract,
            reason="SHADOW_COMMITMENT_PORTABLE_COST_CONTRACT_INVALID",
        )
    )
    _validate_address_mapping(
        binding.get("artifact_cas_address"),
        expected=cost_artifact_address,
        reason="SHADOW_COMMITMENT_COST_ADDRESS_BINDING_INVALID",
    )
    expected_cost_values = list(cost_closure.ordered_values)
    expected_cost_receipts = list(cost_closure.ordered_receipt_sha256s)
    if (
        binding.get("schema_version")
        != PROFILED_RESEARCH_COST_BINDING_V1_SCHEMA_VERSION
        or binding.get("artifact_sha256")
        != cost_closure.cost_evidence_artifact_sha256
        or closure_manifest.get("cost_evidence_artifact_sha256")
        != cost_closure.cost_evidence_artifact_sha256
        or binding.get("artifact_byte_count")
        != cost_artifact_address.payload_byte_count
        or binding.get("evidence_id") != cost_contract.get("evidence_id")
        or binding.get("contract_material_sha256")
        != cost_contract.get("contract_material_sha256")
        or binding.get("symbol") != cost_contract.get("symbol")
        or binding.get("feature_snapshot_identity")
        != cost_contract.get("feature_snapshot_identity")
        or binding.get("decision_time") != cost_contract.get("decision_time")
        or binding.get("counterfactual_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or binding.get("ordered_feature_names")
        != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or binding.get("ordered_values") != expected_cost_values
        or binding.get("ordered_receipt_sha256s") != expected_cost_receipts
        or binding.get("fee_source_authenticity_status")
        != cost_contract.get("fee_source_authenticity_status")
        or binding.get("market_source_authenticity_status")
        != cost_contract.get("market_source_authenticity_status")
        or binding.get("account_specific_commission_authenticated") is not False
        or binding.get("research_only") is not True
    ):
        _integrity("SHADOW_COMMITMENT_COST_BINDING_INVALID")

    decision_reference = contract.get("decision_reference_binding")
    if (
        type(decision_reference) is not dict
        or set(decision_reference) != _DECISION_REFERENCE_FIELDS
    ):
        _integrity("SHADOW_COMMITMENT_DECISION_REFERENCE_INVALID")
    reference = cast(dict[str, Any], decision_reference)
    best_bid = _finite_float(reference.get("best_bid"), positive=True)
    best_ask = _finite_float(reference.get("best_ask"), positive=True)
    mid = _finite_float(reference.get("mid"), positive=True)
    expected_notional = _finite_float(
        reference.get("expected_notional_usd"),
        positive=True,
    )
    if len(ordered_receipts) != 4 or type(ordered_receipts[1]) is not dict:
        _integrity("SHADOW_COMMITMENT_COST_RECEIPTS_INVALID")
    spread_receipt = ordered_receipts[1]
    exact_rederivation = spread_receipt.get("derivation_material", {}).get(
        "exact_rederivation"
    )
    child_bindings = spread_receipt.get("child_read_bindings")
    if (
        reference.get("schema_version")
        != PROFILED_RESEARCH_DECISION_REFERENCE_V1_SCHEMA_VERSION
        or reference.get("source") != PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE
        or reference.get("symbol") != raw.get("symbol")
        or reference.get("feature_snapshot_identity")
        != raw.get("durable_snapshot_id")
        or reference.get("decision_time") != raw.get("source_decision_time")
        or binding.get("symbol") != raw.get("symbol")
        or binding.get("feature_snapshot_identity")
        != raw.get("durable_snapshot_id")
        or binding.get("decision_time") != raw.get("source_decision_time")
        or best_bid is None
        or best_ask is None
        or best_ask <= best_bid
        or mid is None
        or mid != (best_bid + best_ask) / 2.0
        or expected_notional is None
        or reference.get("spread_receipt_sha256")
        != spread_receipt.get("receipt_sha256")
        or reference.get("orderbook_child_read_bindings") != child_bindings
        or type(exact_rederivation) is not dict
        or reference.get("exact_rederivation_sha256")
        != _sha256(
            exact_rederivation,
            reason="SHADOW_COMMITMENT_DECISION_REFERENCE_INVALID",
        )
        or reference.get("caller_supplied_price_used") is not False
        or reference.get("unfinished_candle_price_used") is not False
    ):
        _integrity("SHADOW_COMMITMENT_DECISION_REFERENCE_INVALID")

    try:
        label_clock = decision_clock + timedelta(
            seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        )
    except OverflowError:
        _integrity("SHADOW_COMMITMENT_LABEL_EARLIEST_CLOCK_INVALID")
    if generated_clock >= label_clock:
        _validation("SHADOW_COMMITMENT_HYPOTHESIS_ALREADY_POST_LABEL")
    identity_material = {
        "domain": "v2/native-trainer/profiled-research-shadow-identity/v1",
        "raw_inference_binding_sha256": raw_binding,
        "symbol": raw["symbol"],
        "durable_snapshot_id": raw["durable_snapshot_id"],
        "decision_time": raw["source_decision_time"],
        "counterfactual_holding_horizon_seconds": (
            CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ),
    }
    return _PreparedHypothesis(
        artifact_address=artifact_address,
        artifact_bytes=artifact_bytes,
        artifact_contract=contract,
        closure_address=cost_closure.closure_address,
        cost_evidence_artifact_sha256=cost_closure.cost_evidence_artifact_sha256,
        hypothesis_identity_sha256=_sha256(identity_material),
        raw_inference_binding_sha256=raw_binding,
        hypothesis_material_sha256=cast(str, hypothesis_material_sha256),
        symbol=cast(str, raw["symbol"]),
        durable_snapshot_id=cast(str, raw["durable_snapshot_id"]),
        decision_time=cast(str, raw["source_decision_time"]),
        hypothesis_generated_at=cast(str, raw["hypothesis_generated_at"]),
        label_earliest_available_at=_format_microsecond(label_clock),
        holding_horizon_seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    )


def _preflight_hypothesis(
    *,
    hypothesis: object,
    cost_closure: object,
    store: object,
) -> _PreparedHypothesis:
    if type(hypothesis) is not ProfiledResearchShadowHypothesisArtifactV1:
        _validation("SHADOW_COMMITMENT_EXACT_HYPOTHESIS_REQUIRED")
    if type(cost_closure) is not PaperResearchCausalCostPortableClosureV1:
        _validation("SHADOW_COMMITMENT_EXACT_PORTABLE_COST_CLOSURE_REQUIRED")
    if type(store) is not ImmutableSourcePayloadStore:
        _validation("SHADOW_COMMITMENT_EXACT_IMMUTABLE_STORE_REQUIRED")
    exact_hypothesis = cast(ProfiledResearchShadowHypothesisArtifactV1, hypothesis)
    exact_closure = cast(PaperResearchCausalCostPortableClosureV1, cost_closure)
    exact_store = cast(ImmutableSourcePayloadStore, store)
    try:
        factory_contract = exact_hypothesis.contract
        artifact_bytes = exact_hypothesis.artifact_json.encode(
            "ascii",
            errors="strict",
        )
    except (ProfiledResearchShadowHypothesisV1Error, UnicodeError) as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_HYPOTHESIS_FACTORY_REVALIDATION_FAILED"
        ) from exc
    if (
        not artifact_bytes
        or len(artifact_bytes) > _MAX_JSON_BYTES
        or exact_hypothesis.artifact_address != _expected_address(artifact_bytes)
        or factory_contract
        != _parse_exact_object(
            artifact_bytes,
            reason="SHADOW_COMMITMENT_HYPOTHESIS_JSON_INVALID",
        )
    ):
        _integrity("SHADOW_COMMITMENT_HYPOTHESIS_FACTORY_BINDING_INVALID")
    try:
        reopened_closure = open_paper_research_causal_cost_portable_closure_v1(
            store=exact_store,
            closure_address=exact_closure.closure_address,
        )
        if reopened_closure.manifest != exact_closure.manifest:
            _integrity("SHADOW_COMMITMENT_PORTABLE_COST_SUBSTITUTION")
    except PaperResearchCausalCostPortableClosureV1Error as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_PORTABLE_COST_REOPEN_FAILED"
        ) from exc
    prepared = _validate_hypothesis_against_closure(
        artifact_bytes=artifact_bytes,
        artifact_address=exact_hypothesis.artifact_address,
        cost_closure=reopened_closure,
    )
    try:
        copied = exact_store.put(
            artifact_bytes,
            expected_sha256=prepared.artifact_address.payload_sha256,
            expected_byte_count=prepared.artifact_address.payload_byte_count,
        )
        readback = exact_store.get(
            copied.payload_sha256,
            expected_byte_count=copied.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_HYPOTHESIS_CAS_PUBLICATION_FAILED"
        ) from exc
    if copied != prepared.artifact_address or not hmac.compare_digest(
        readback,
        artifact_bytes,
    ):
        _integrity("SHADOW_COMMITMENT_HYPOTHESIS_CAS_READBACK_FAILED")
    return prepared


_TABLE_NAMES: Final = frozenset(
    {
        "profiled_shadow_commitment_metadata",
        "profiled_shadow_hypotheses",
        "profiled_shadow_pending_hypothesis_index",
        "profiled_shadow_commitment_append_receipts",
        "profiled_shadow_commitment_postcommit_receipts",
        "profiled_shadow_commitment_head_anchors",
    }
)
_INDEX_NAMES: Final = frozenset(
    {
        "profiled_shadow_pending_label_time",
        "profiled_shadow_hypothesis_decision_time",
    }
)
_TRIGGER_NAMES: Final = frozenset(
    {
        f"{table_name}_no_{operation}"
        for table_name in _TABLE_NAMES
        for operation in ("update", "delete")
    }
)


def _schema_script() -> str:
    horizon = CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    return f"""
    PRAGMA application_id={_APPLICATION_ID};
    PRAGMA user_version={_USER_VERSION};
    CREATE TABLE profiled_shadow_commitment_metadata (
        metadata_key TEXT PRIMARY KEY,
        metadata_value TEXT NOT NULL
    );
    CREATE TABLE profiled_shadow_hypotheses (
        sequence INTEGER PRIMARY KEY,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_byte_count INTEGER NOT NULL CHECK(
            hypothesis_artifact_byte_count > 0
            AND hypothesis_artifact_byte_count <= {_MAX_JSON_BYTES}
        ),
        hypothesis_artifact_relative_path TEXT NOT NULL,
        cost_closure_sha256 TEXT NOT NULL,
        cost_closure_byte_count INTEGER NOT NULL CHECK(
            cost_closure_byte_count > 0
            AND cost_closure_byte_count <= {_MAX_JSON_BYTES}
        ),
        cost_closure_relative_path TEXT NOT NULL,
        cost_evidence_artifact_sha256 TEXT NOT NULL,
        raw_inference_binding_sha256 TEXT NOT NULL,
        hypothesis_material_sha256 TEXT NOT NULL,
        symbol TEXT NOT NULL,
        durable_snapshot_id TEXT NOT NULL,
        decision_time TEXT NOT NULL,
        hypothesis_generated_at TEXT NOT NULL,
        label_earliest_available_at TEXT NOT NULL,
        holding_horizon_seconds INTEGER NOT NULL CHECK(
            holding_horizon_seconds = {horizon}
        ),
        commitment_sha256 TEXT NOT NULL,
        commitment_json TEXT NOT NULL CHECK(
            length(CAST(commitment_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        previous_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        transaction_id TEXT NOT NULL UNIQUE,
        commit_observed_at TEXT NOT NULL,
        commit_prepared_at TEXT NOT NULL UNIQUE
    );
    CREATE TABLE profiled_shadow_pending_hypothesis_index (
        hypothesis_identity_sha256 TEXT PRIMARY KEY,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
        decision_time TEXT NOT NULL,
        label_earliest_available_at TEXT NOT NULL,
        transaction_id TEXT NOT NULL UNIQUE,
        registered_at TEXT NOT NULL,
        index_entry_sha256 TEXT NOT NULL,
        index_entry_json TEXT NOT NULL CHECK(
            length(CAST(index_entry_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        FOREIGN KEY(hypothesis_identity_sha256)
            REFERENCES profiled_shadow_hypotheses(hypothesis_identity_sha256),
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_shadow_hypotheses(transaction_id)
    );
    CREATE TABLE profiled_shadow_commitment_append_receipts (
        transaction_id TEXT PRIMARY KEY,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
        cost_closure_sha256 TEXT NOT NULL,
        previous_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        commitment_sha256 TEXT NOT NULL,
        total_committed_hypotheses INTEGER NOT NULL,
        receipt_sha256 TEXT NOT NULL UNIQUE,
        receipt_json TEXT NOT NULL CHECK(
            length(CAST(receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        commit_observed_at TEXT NOT NULL,
        commit_prepared_at TEXT NOT NULL UNIQUE,
        precommit_readback_verified INTEGER NOT NULL CHECK(
            precommit_readback_verified = 1
        ),
        FOREIGN KEY(hypothesis_identity_sha256)
            REFERENCES profiled_shadow_hypotheses(hypothesis_identity_sha256),
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_shadow_hypotheses(transaction_id)
    );
    CREATE TABLE profiled_shadow_commitment_postcommit_receipts (
        transaction_id TEXT PRIMARY KEY,
        append_receipt_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
        record_chain_sha256 TEXT NOT NULL,
        readback_receipt_sha256 TEXT NOT NULL UNIQUE,
        readback_receipt_json TEXT NOT NULL CHECK(
            length(CAST(readback_receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        postcommit_observed_at TEXT NOT NULL,
        postcommit_readback_at TEXT NOT NULL UNIQUE,
        ex_ante_durability_verified INTEGER NOT NULL CHECK(
            ex_ante_durability_verified IN (0, 1)
        ),
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_shadow_commitment_append_receipts(transaction_id),
        FOREIGN KEY(hypothesis_identity_sha256)
            REFERENCES profiled_shadow_hypotheses(hypothesis_identity_sha256)
    );
    CREATE TABLE profiled_shadow_commitment_head_anchors (
        sequence INTEGER PRIMARY KEY,
        transaction_id TEXT NOT NULL UNIQUE,
        total_committed_hypotheses INTEGER NOT NULL,
        hypothesis_identity_sha256 TEXT NOT NULL UNIQUE,
        hypothesis_artifact_sha256 TEXT NOT NULL UNIQUE,
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
        commit_observed_at TEXT NOT NULL,
        postcommit_observed_at TEXT NOT NULL,
        anchored_at TEXT NOT NULL UNIQUE,
        ex_ante_durability_verified INTEGER NOT NULL CHECK(
            ex_ante_durability_verified IN (0, 1)
        ),
        FOREIGN KEY(transaction_id)
            REFERENCES profiled_shadow_commitment_postcommit_receipts(transaction_id),
        FOREIGN KEY(hypothesis_identity_sha256)
            REFERENCES profiled_shadow_hypotheses(hypothesis_identity_sha256)
    );
    CREATE INDEX profiled_shadow_pending_label_time
        ON profiled_shadow_pending_hypothesis_index(
            label_earliest_available_at,
            hypothesis_identity_sha256
        );
    CREATE INDEX profiled_shadow_hypothesis_decision_time
        ON profiled_shadow_hypotheses(
            symbol,
            decision_time,
            hypothesis_identity_sha256
        );
    """ + "\n".join(
        f"""
        CREATE TRIGGER {table_name}_no_update
        BEFORE UPDATE ON {table_name}
        BEGIN
            SELECT RAISE(ABORT, '{table_name}_rows_are_immutable');
        END;
        CREATE TRIGGER {table_name}_no_delete
        BEFORE DELETE ON {table_name}
        BEGIN
            SELECT RAISE(ABORT, '{table_name}_rows_are_immutable');
        END;
        """
        for table_name in sorted(_TABLE_NAMES)
    )


def _normalized_schema_sql(value: object) -> str | None:
    if type(value) is not str or not value.strip():
        return None
    return " ".join(value.split())


@lru_cache(maxsize=1)
def _expected_schema_sql() -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(_schema_script())
        rows = connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    finally:
        connection.close()
    result: dict[tuple[str, str], str] = {}
    for object_type, name, sql in rows:
        normalized = _normalized_schema_sql(sql)
        if normalized is None:
            _integrity("SHADOW_COMMITMENT_EXPECTED_SCHEMA_INVALID")
        result[(str(object_type), str(name))] = normalized
    return result


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_PARENT_DIRECTORY_FSYNC_FAILED"
        ) from exc


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def _validate_schema(connection: sqlite3.Connection) -> None:
    try:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        rows = connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        quick_check = connection.execute("PRAGMA quick_check").fetchall()
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
            "SHADOW_COMMITMENT_SCHEMA_READ_FAILED"
        ) from exc
    observed = {
        "table": frozenset(str(row["name"]) for row in rows if row["type"] == "table"),
        "index": frozenset(str(row["name"]) for row in rows if row["type"] == "index"),
        "trigger": frozenset(
            str(row["name"]) for row in rows if row["type"] == "trigger"
        ),
    }
    observed_sql: dict[tuple[str, str], str] = {}
    for row in rows:
        normalized = _normalized_schema_sql(row["sql"])
        if normalized is None:
            _integrity("SHADOW_COMMITMENT_SCHEMA_SQL_INVALID")
        observed_sql[(str(row["type"]), str(row["name"]))] = normalized
    if (
        application_id != _APPLICATION_ID
        or user_version != _USER_VERSION
        or foreign_keys != 1
        or observed["table"] != _TABLE_NAMES
        or observed["index"] != _INDEX_NAMES
        or observed["trigger"] != _TRIGGER_NAMES
        or observed_sql != _expected_schema_sql()
        or len(quick_check) != 1
        or tuple(quick_check[0]) != ("ok",)
        or foreign_key_violations
    ):
        _integrity("SHADOW_COMMITMENT_SCHEMA_INVALID")
    metadata_rows = connection.execute(
        """
        SELECT metadata_key, metadata_value
        FROM profiled_shadow_commitment_metadata
        ORDER BY metadata_key
        """
    ).fetchall()
    metadata = {
        str(row["metadata_key"]): str(row["metadata_value"])
        for row in metadata_rows
    }
    if metadata != _METADATA:
        _integrity("SHADOW_COMMITMENT_METADATA_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledResearchShadowHypothesisCommitmentIntegrityV1:
    total_committed_hypotheses: int
    ex_ante_verified_hypotheses: int
    quarantined_hypotheses: int
    append_receipts_verified: int
    postcommit_receipts_verified: int
    pending_index_entries_verified: int
    head_anchors_verified: int
    chain_head_sha256: str
    last_commit_prepared_at: str | None
    last_postcommit_readback_at: str | None
    schema_verified: bool
    clock_causality_verified: bool
    cas_closures_verified: int
    cas_head_anchors_verified: int


@dataclass(frozen=True, slots=True)
class DurablyCommittedProfiledResearchShadowHypothesisV1:
    hypothesis_identity_sha256: str
    hypothesis_artifact_sha256: str
    hypothesis_artifact_byte_count: int
    hypothesis_artifact_address: SourcePayloadAddress
    cost_closure_address: SourcePayloadAddress
    cost_evidence_artifact_sha256: str
    raw_inference_binding_sha256: str
    hypothesis_material_sha256: str
    symbol: str
    durable_snapshot_id: str
    decision_time: str
    hypothesis_generated_at: str
    label_earliest_available_at: str
    holding_horizon_seconds: int
    transaction_id: str
    append_receipt_sha256: str
    postcommit_readback_receipt_sha256: str
    commitment_sha256: str
    record_chain_sha256: str
    commit_observed_at: str
    commit_prepared_at: str
    postcommit_observed_at: str
    postcommit_readback_at: str
    _artifact_json: str = field(repr=False, compare=False)
    _ledger: ProfiledResearchShadowHypothesisCommitmentLedgerV1 = field(
        repr=False,
        compare=False,
    )
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _validation_writer_lease: (
        ProfiledResearchShadowHypothesisCommitmentWriterLease | None
    ) = field(repr=False, compare=False)
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def hypothesis_contract(self) -> dict[str, Any]:
        return _validated_committed_result(self)

    @property
    def commitment_status(self) -> dict[str, bool]:
        _validated_committed_result(self)
        return dict(_COMMITMENT_STATUS)

    @property
    def authorization(self) -> dict[str, bool]:
        _validated_committed_result(self)
        return dict(_AUTHORIZATION)

    def _verified_status(self, field_name: str) -> bool:
        _validated_committed_result(self)
        return cast(bool, _RESULT_STATUS_FIELDS[field_name])

    @property
    def pending_hypothesis_index_registered(self) -> bool:
        return self._verified_status("pending_hypothesis_index_registered")

    @property
    def durable_ex_ante_commitment_verified(self) -> bool:
        return self._verified_status("durable_ex_ante_commitment_verified")

    @property
    def portable_cost_source_closure_complete(self) -> bool:
        return self._verified_status("portable_cost_source_closure_complete")

    @property
    def restart_reopen_verified(self) -> bool:
        return self._verified_status("restart_reopen_verified")

    @property
    def outcome_maturation_authorized(self) -> bool:
        return self._verified_status("outcome_maturation_authorized")

    @property
    def calibration_input_authorized(self) -> bool:
        return self._verified_status("calibration_input_authorized")

    @property
    def trainer_admission_authorized(self) -> bool:
        return self._verified_status("trainer_admission_authorized")

    @property
    def paper_trading_authorized(self) -> bool:
        return self._verified_status("paper_trading_authorized")

    @property
    def live_execution_authorized(self) -> bool:
        return self._verified_status("live_execution_authorized")

    @property
    def runtime_wired(self) -> bool:
        return self._verified_status("runtime_wired")


class ProfiledResearchShadowHypothesisCommitmentLedgerV1:
    """Append-only SQLite commitment chain and restart-safe pending reader."""

    def __init__(
        self,
        path: Path,
        *,
        writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ) = None,
    ) -> None:
        self.path = _lexical_absolute_path(path)
        self._writer_lease = writer_lease
        if writer_lease is not None:
            writer_lease.validate_for(self.path)

    @contextmanager
    def writer_lease(
        self,
        writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ) = None,
    ) -> Iterator[ProfiledResearchShadowHypothesisCommitmentWriterLease]:
        held = writer_lease if writer_lease is not None else self._writer_lease
        acquired_here = held is None
        if held is None:
            held = ProfiledResearchShadowHypothesisCommitmentWriterLease.acquire(
                self.path
            )
        try:
            held.validate_for(self.path)
            yield held
            held.validate_for(self.path)
        finally:
            if acquired_here:
                held.release()

    @contextmanager
    def _reader_snapshot_lease(self) -> Iterator[None]:
        """Exclude the sanctioned writer across DB, CAS, and anchor reads."""

        configured_writer = self._writer_lease
        if configured_writer is not None:
            try:
                configured_writer.validate_for(self.path)
            except ProfiledResearchShadowHypothesisCommitmentWriterLeaseError as exc:
                if exc.reason != "SHADOW_COMMITMENT_WRITER_LEASE_NOT_HELD":
                    raise
            else:
                yield
                configured_writer.validate_for(self.path)
                return

        lock_path = _writer_lock_path(self.path)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        lock_fd = -1
        database_fd = -1
        try:
            try:
                lock_fd = os.open(lock_path, flags)
            except OSError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                    "SHADOW_COMMITMENT_READER_LEASE_OPEN_FAILED"
                ) from exc
            lock_stat = os.fstat(lock_fd)
            lock_path_stat = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or not stat.S_ISREG(lock_path_stat.st_mode)
                or (lock_stat.st_dev, lock_stat.st_ino)
                != (lock_path_stat.st_dev, lock_path_stat.st_ino)
            ):
                _integrity("SHADOW_COMMITMENT_READER_LEASE_BINDING_INVALID")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                    "SHADOW_COMMITMENT_READER_LEASE_WRITER_ACTIVE"
                ) from exc

            try:
                database_fd = os.open(self.path, flags)
            except OSError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                    "SHADOW_COMMITMENT_READER_DATABASE_OPEN_FAILED"
                ) from exc
            database_stat = os.fstat(database_fd)
            database_path_stat = os.stat(self.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(database_stat.st_mode)
                or not stat.S_ISREG(database_path_stat.st_mode)
                or (database_stat.st_dev, database_stat.st_ino)
                != (database_path_stat.st_dev, database_path_stat.st_ino)
            ):
                _integrity("SHADOW_COMMITMENT_READER_DATABASE_BINDING_INVALID")
            try:
                fcntl.flock(database_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                    "SHADOW_COMMITMENT_READER_LEASE_WRITER_ACTIVE"
                ) from exc

            yield

            final_lock_stat = os.stat(lock_path, follow_symlinks=False)
            final_database_stat = os.stat(self.path, follow_symlinks=False)
            if (
                (final_lock_stat.st_dev, final_lock_stat.st_ino)
                != (lock_stat.st_dev, lock_stat.st_ino)
                or (final_database_stat.st_dev, final_database_stat.st_ino)
                != (database_stat.st_dev, database_stat.st_ino)
            ):
                _integrity("SHADOW_COMMITMENT_READER_SNAPSHOT_BINDING_CHANGED")
        except OSError as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_READER_SNAPSHOT_VALIDATION_FAILED"
            ) from exc
        finally:
            for descriptor in (database_fd, lock_fd):
                if descriptor >= 0:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)

    def _connect_write(
        self,
        *,
        writer_lease: ProfiledResearchShadowHypothesisCommitmentWriterLease,
    ) -> sqlite3.Connection:
        writer_lease.validate_for(self.path)
        writer_lease.bind_database_inode(create=True)
        try:
            connection = sqlite3.connect(str(self.path), timeout=60.0)
            _configure_connection(connection)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA temp_store=MEMORY")
            writer_lease.validate_for(self.path)
            return connection
        except sqlite3.Error as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_WRITE_CONNECTION_FAILED"
            ) from exc

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            _integrity("SHADOW_COMMITMENT_LEDGER_MISSING")
        try:
            path_stat = os.stat(self.path, follow_symlinks=False)
            if not stat.S_ISREG(path_stat.st_mode):
                _integrity("SHADOW_COMMITMENT_LEDGER_NOT_REGULAR_FILE")
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro",
                uri=True,
                timeout=60.0,
            )
            _configure_connection(connection)
            connection.execute("PRAGMA query_only=ON")
            if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
                _integrity("SHADOW_COMMITMENT_READONLY_MODE_INVALID")
            return connection
        except sqlite3.Error as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_READONLY_CONNECTION_FAILED"
            ) from exc

    def _ensure_initialized(
        self,
        *,
        writer_lease: ProfiledResearchShadowHypothesisCommitmentWriterLease,
    ) -> None:
        writer_lease.validate_for(self.path)
        writer_lease.bind_database_inode(create=True)
        try:
            size = self.path.stat().st_size
        except OSError as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_LEDGER_STAT_FAILED"
            ) from exc
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            self._preflight_database_size(connection)
            objects = connection.execute(
                """
                SELECT type, name
                FROM sqlite_master
                WHERE sql IS NOT NULL
                  AND name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            application_id = int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            )
            user_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if objects is not None:
                _validate_schema(connection)
                return
            if application_id != 0 or user_version != 0:
                _integrity("SHADOW_COMMITMENT_PARTIAL_OR_FOREIGN_SCHEMA")
            if self._observed_head_anchor_catalog_digests():
                _integrity(
                    "SHADOW_COMMITMENT_HEAD_ANCHOR_EXISTS_FOR_PRISTINE_LEDGER"
                )
            if size > 0 and connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                _integrity("SHADOW_COMMITMENT_PRISTINE_DATABASE_INVALID")
            # Schema, fixed metadata, and their application/user identifiers
            # are one transaction. A process death can leave only the exact
            # pristine database state, which this branch can safely retry.
            connection.executescript("BEGIN IMMEDIATE;\n" + _schema_script())
            for key, value in sorted(_METADATA.items()):
                connection.execute(
                    """
                    INSERT INTO profiled_shadow_commitment_metadata(
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
    def _next_commit_clock(connection: sqlite3.Connection) -> tuple[str, str]:
        observed = _utc_now()
        if (
            type(observed) is not datetime
            or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            _integrity("SHADOW_COMMITMENT_INTERNAL_CLOCK_INVALID")
        raw_observed = observed.astimezone(UTC)
        raw_high_water: datetime | None = None
        raw_sources = (
            (
                "commit_observed_at",
                connection.execute(
                    """
                    SELECT commit_observed_at
                    FROM profiled_shadow_commitment_append_receipts
                    ORDER BY commit_prepared_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
            ),
            (
                "postcommit_observed_at",
                connection.execute(
                    """
                    SELECT postcommit_observed_at
                    FROM profiled_shadow_commitment_postcommit_receipts
                    ORDER BY postcommit_readback_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
            ),
        )
        for column, row in raw_sources:
            if row is None:
                continue
            parsed = _aware_clock(row[column])
            if parsed is None or _format_microsecond(parsed) != row[column]:
                _integrity("SHADOW_COMMITMENT_PRIOR_RAW_CLOCK_INVALID")
            if raw_high_water is None or parsed > raw_high_water:
                raw_high_water = parsed
        if raw_high_water is not None and raw_observed <= raw_high_water:
            _validation("SHADOW_COMMITMENT_INTERNAL_CLOCK_NOT_MONOTONIC")
        previous: datetime | None = None
        sources = (
            (
                "commit_prepared_at",
                connection.execute(
                    """
                    SELECT commit_prepared_at
                    FROM profiled_shadow_commitment_append_receipts
                    ORDER BY commit_prepared_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
            ),
            (
                "postcommit_readback_at",
                connection.execute(
                    """
                    SELECT postcommit_readback_at
                    FROM profiled_shadow_commitment_postcommit_receipts
                    ORDER BY postcommit_readback_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
            ),
        )
        for column, row in sources:
            if row is None:
                continue
            parsed = _canonical_millisecond_clock(row[column])
            if parsed is None:
                _integrity("SHADOW_COMMITMENT_PRIOR_CLOCK_INVALID")
            if previous is None or parsed > previous:
                previous = parsed
        candidate = _ceil_millisecond(raw_observed)
        if previous is not None and candidate <= previous:
            try:
                candidate = previous + timedelta(milliseconds=1)
            except OverflowError:
                _integrity("SHADOW_COMMITMENT_LOGICAL_CLOCK_OVERFLOW")
        return _format_millisecond(candidate), _format_microsecond(raw_observed)

    @staticmethod
    def _next_postcommit_clock(
        connection: sqlite3.Connection,
        *,
        commit_prepared_at: str,
    ) -> tuple[str, str]:
        commit_clock = _canonical_millisecond_clock(commit_prepared_at)
        observed = _utc_now()
        if (
            commit_clock is None
            or type(observed) is not datetime
            or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            _integrity("SHADOW_COMMITMENT_POSTCOMMIT_CLOCK_INVALID")
        raw_observed = observed.astimezone(UTC)
        candidate = _ceil_millisecond(raw_observed)
        prior = connection.execute(
            """
            SELECT postcommit_readback_at
            FROM profiled_shadow_commitment_postcommit_receipts
            ORDER BY postcommit_readback_at DESC
            LIMIT 1
            """
        ).fetchone()
        lower_bound = commit_clock
        if prior is not None:
            prior_clock = _canonical_millisecond_clock(prior["postcommit_readback_at"])
            if prior_clock is None:
                _integrity("SHADOW_COMMITMENT_PRIOR_POSTCOMMIT_CLOCK_INVALID")
            lower_bound = max(lower_bound, prior_clock)
        if candidate <= lower_bound:
            try:
                candidate = lower_bound + timedelta(milliseconds=1)
            except OverflowError:
                _integrity("SHADOW_COMMITMENT_POSTCOMMIT_CLOCK_OVERFLOW")
        return _format_millisecond(candidate), _format_microsecond(raw_observed)

    @staticmethod
    def _transaction_id(prepared: _PreparedHypothesis) -> str:
        material = {
            "domain": "v2/native-trainer/profiled-shadow-commit-operation/v1",
            "hypothesis_identity_sha256": prepared.hypothesis_identity_sha256,
            "hypothesis_artifact_sha256": prepared.artifact_address.payload_sha256,
            "cost_closure_sha256": prepared.closure_address.payload_sha256,
        }
        return "profiled_shadow_commit_v1_" + _sha256(material)

    @staticmethod
    def _commitment_material(
        *,
        prepared: _PreparedHypothesis,
        transaction_id: str,
        commit_observed_at: str,
        commit_prepared_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION
            ),
            "classification": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION
            ),
            "hypothesis_identity_sha256": prepared.hypothesis_identity_sha256,
            "hypothesis_artifact_cas_address": _address_mapping(
                prepared.artifact_address
            ),
            "cost_closure_cas_address": _address_mapping(prepared.closure_address),
            "cost_evidence_artifact_sha256": (
                prepared.cost_evidence_artifact_sha256
            ),
            "raw_inference_binding_sha256": (
                prepared.raw_inference_binding_sha256
            ),
            "hypothesis_material_sha256": prepared.hypothesis_material_sha256,
            "symbol": prepared.symbol,
            "durable_snapshot_id": prepared.durable_snapshot_id,
            "decision_time": prepared.decision_time,
            "hypothesis_generated_at": prepared.hypothesis_generated_at,
            "label_earliest_available_at": (
                prepared.label_earliest_available_at
            ),
            "counterfactual_holding_horizon_seconds": (
                prepared.holding_horizon_seconds
            ),
            "transaction_id": transaction_id,
            "commit_observed_at": commit_observed_at,
            "commit_prepared_at": commit_prepared_at,
            "label_value_present": False,
            "outcome_payload_present": False,
            "future_data_consumed": False,
            "commitment_status": {
                **_COMMITMENT_STATUS,
                "postcommit_readback_receipt_present": False,
            },
            "authorization": dict(_AUTHORIZATION),
            "research_only": True,
        }

    @staticmethod
    def _record_chain_sha256(
        *,
        sequence: int,
        previous_chain_sha256: str,
        commitment_sha256: str,
        prepared: _PreparedHypothesis,
        transaction_id: str,
        commit_observed_at: str,
        commit_prepared_at: str,
    ) -> str:
        return _sha256(
            {
                "domain": "v2/native-trainer/profiled-shadow-commit-chain/v1",
                "sequence": sequence,
                "previous_chain_sha256": previous_chain_sha256,
                "commitment_sha256": commitment_sha256,
                "hypothesis_identity_sha256": (
                    prepared.hypothesis_identity_sha256
                ),
                "hypothesis_artifact_sha256": (
                    prepared.artifact_address.payload_sha256
                ),
                "cost_closure_sha256": prepared.closure_address.payload_sha256,
                "transaction_id": transaction_id,
                "commit_observed_at": commit_observed_at,
                "commit_prepared_at": commit_prepared_at,
            }
        )

    @staticmethod
    def _commitment_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        artifact_address = _address_from_columns(
            sha256=row["hypothesis_artifact_sha256"],
            byte_count=row["hypothesis_artifact_byte_count"],
            relative_path=row["hypothesis_artifact_relative_path"],
        )
        closure_address = _address_from_columns(
            sha256=row["cost_closure_sha256"],
            byte_count=row["cost_closure_byte_count"],
            relative_path=row["cost_closure_relative_path"],
        )
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION
            ),
            "classification": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION
            ),
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_cas_address": _address_mapping(
                artifact_address
            ),
            "cost_closure_cas_address": _address_mapping(closure_address),
            "cost_evidence_artifact_sha256": row[
                "cost_evidence_artifact_sha256"
            ],
            "raw_inference_binding_sha256": row[
                "raw_inference_binding_sha256"
            ],
            "hypothesis_material_sha256": row["hypothesis_material_sha256"],
            "symbol": row["symbol"],
            "durable_snapshot_id": row["durable_snapshot_id"],
            "decision_time": row["decision_time"],
            "hypothesis_generated_at": row["hypothesis_generated_at"],
            "label_earliest_available_at": row[
                "label_earliest_available_at"
            ],
            "counterfactual_holding_horizon_seconds": row[
                "holding_horizon_seconds"
            ],
            "transaction_id": row["transaction_id"],
            "commit_observed_at": row["commit_observed_at"],
            "commit_prepared_at": row["commit_prepared_at"],
            "label_value_present": False,
            "outcome_payload_present": False,
            "future_data_consumed": False,
            "commitment_status": {
                **_COMMITMENT_STATUS,
                "postcommit_readback_receipt_present": False,
            },
            "authorization": dict(_AUTHORIZATION),
            "research_only": True,
        }

    @staticmethod
    def _index_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_PENDING_INDEX_V1_SCHEMA_VERSION
            ),
            "status": "PENDING_FINALIZED_LABEL_OUTCOME_NOT_AUTHORIZED",
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_sha256": row[
                "hypothesis_artifact_sha256"
            ],
            "decision_time": row["decision_time"],
            "label_earliest_available_at": row[
                "label_earliest_available_at"
            ],
            "transaction_id": row["transaction_id"],
            "registered_at": row["commit_prepared_at"],
            "label_value_present": False,
            "outcome_payload_present": False,
            "outcome_maturation_authorized": False,
            "calibration_input_authorized": False,
            "research_only": True,
        }

    @staticmethod
    def _append_receipt_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_APPEND_RECEIPT_V1_SCHEMA_VERSION
            ),
            "transaction_id": row["transaction_id"],
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_sha256": row[
                "hypothesis_artifact_sha256"
            ],
            "cost_closure_sha256": row["cost_closure_sha256"],
            "commitment_sha256": row["commitment_sha256"],
            "previous_chain_sha256": row["previous_chain_sha256"],
            "record_chain_sha256": row["record_chain_sha256"],
            "total_committed_hypotheses": row["sequence"],
            "commit_observed_at": row["commit_observed_at"],
            "commit_prepared_at": row["commit_prepared_at"],
            "precommit_readback_verified": True,
            "pending_hypothesis_index_registered": True,
            "label_value_present": False,
            "outcome_payload_present": False,
            "authorization": dict(_AUTHORIZATION),
        }

    @staticmethod
    def _postcommit_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_COMMITMENT_POSTCOMMIT_V1_SCHEMA_VERSION
            ),
            "transaction_id": row["transaction_id"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_sha256": row[
                "hypothesis_artifact_sha256"
            ],
            "record_chain_sha256": row["record_chain_sha256"],
            "commit_observed_at": row["commit_observed_at"],
            "postcommit_observed_at": row["postcommit_observed_at"],
            "postcommit_readback_at": row["postcommit_readback_at"],
            "independent_readback_verified": True,
            "pending_hypothesis_index_readback_verified": True,
            "durable_commit_observed_before_label_availability": (
                row["ex_ante_durability_verified"] == 1
            ),
            "label_value_present": False,
            "outcome_payload_present": False,
            "authorization": dict(_AUTHORIZATION),
        }

    @staticmethod
    def _head_anchor_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_RESEARCH_SHADOW_HEAD_ANCHOR_V1_SCHEMA_VERSION
            ),
            "sequence": row["sequence"],
            "transaction_id": row["transaction_id"],
            "total_committed_hypotheses": row["sequence"],
            "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
            "hypothesis_artifact_sha256": row[
                "hypothesis_artifact_sha256"
            ],
            "record_chain_sha256": row["record_chain_sha256"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "postcommit_receipt_sha256": row["readback_receipt_sha256"],
            "previous_head_anchor_sha256": row[
                "previous_head_anchor_sha256"
            ],
            "commit_observed_at": row["commit_observed_at"],
            "postcommit_observed_at": row["postcommit_observed_at"],
            "anchored_at": row["postcommit_readback_at"],
            "ex_ante_durability_verified": (
                row["ex_ante_durability_verified"] == 1
            ),
            "label_value_present": False,
            "outcome_payload_present": False,
            "research_only": True,
            "authorization": dict(_AUTHORIZATION),
        }

    @staticmethod
    def _joined_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                h.sequence,
                h.hypothesis_identity_sha256,
                h.hypothesis_artifact_sha256,
                h.hypothesis_artifact_byte_count,
                h.hypothesis_artifact_relative_path,
                h.cost_closure_sha256,
                h.cost_closure_byte_count,
                h.cost_closure_relative_path,
                h.cost_evidence_artifact_sha256,
                h.raw_inference_binding_sha256,
                h.hypothesis_material_sha256,
                h.symbol,
                h.durable_snapshot_id,
                h.decision_time,
                h.hypothesis_generated_at,
                h.label_earliest_available_at,
                h.holding_horizon_seconds,
                h.commitment_sha256,
                h.commitment_json,
                h.previous_chain_sha256,
                h.record_chain_sha256,
                h.transaction_id,
                h.commit_observed_at,
                h.commit_prepared_at,
                idx.hypothesis_identity_sha256 AS index_identity_sha256,
                idx.hypothesis_artifact_sha256 AS index_artifact_sha256,
                idx.decision_time AS index_decision_time,
                idx.label_earliest_available_at AS index_label_available_at,
                idx.transaction_id AS index_transaction_id,
                idx.registered_at AS index_registered_at,
                idx.index_entry_sha256,
                idx.index_entry_json,
                receipt.hypothesis_identity_sha256 AS receipt_identity_sha256,
                receipt.hypothesis_artifact_sha256 AS receipt_artifact_sha256,
                receipt.cost_closure_sha256 AS receipt_closure_sha256,
                receipt.previous_chain_sha256 AS receipt_previous_chain_sha256,
                receipt.record_chain_sha256 AS receipt_record_chain_sha256,
                receipt.commitment_sha256 AS receipt_commitment_sha256,
                receipt.total_committed_hypotheses,
                receipt.receipt_sha256 AS append_receipt_sha256,
                receipt.receipt_json AS append_receipt_json,
                receipt.commit_observed_at AS receipt_commit_observed_at,
                receipt.commit_prepared_at AS receipt_commit_prepared_at,
                receipt.precommit_readback_verified,
                post.append_receipt_sha256 AS post_append_receipt_sha256,
                post.hypothesis_identity_sha256 AS post_identity_sha256,
                post.hypothesis_artifact_sha256 AS post_artifact_sha256,
                post.record_chain_sha256 AS post_record_chain_sha256,
                post.readback_receipt_sha256,
                post.readback_receipt_json,
                post.postcommit_observed_at,
                post.postcommit_readback_at,
                post.ex_ante_durability_verified,
                anchor.sequence AS head_anchor_sequence,
                anchor.transaction_id AS head_anchor_transaction_id,
                anchor.total_committed_hypotheses AS head_anchor_total,
                anchor.hypothesis_identity_sha256 AS head_anchor_identity,
                anchor.hypothesis_artifact_sha256 AS head_anchor_artifact,
                anchor.record_chain_sha256 AS head_anchor_record_chain,
                anchor.append_receipt_sha256 AS head_anchor_append_receipt,
                anchor.postcommit_receipt_sha256 AS head_anchor_postcommit_receipt,
                anchor.previous_head_anchor_sha256,
                anchor.head_anchor_sha256,
                anchor.head_anchor_byte_count,
                anchor.head_anchor_relative_path,
                anchor.head_anchor_json,
                anchor.commit_observed_at AS head_anchor_commit_observed_at,
                anchor.postcommit_observed_at AS head_anchor_postcommit_observed_at,
                anchor.anchored_at AS head_anchor_anchored_at,
                anchor.ex_ante_durability_verified AS head_anchor_ex_ante_verified
            FROM profiled_shadow_hypotheses AS h
            LEFT JOIN profiled_shadow_pending_hypothesis_index AS idx
              ON idx.hypothesis_identity_sha256 = h.hypothesis_identity_sha256
            LEFT JOIN profiled_shadow_commitment_append_receipts AS receipt
              ON receipt.transaction_id = h.transaction_id
            LEFT JOIN profiled_shadow_commitment_postcommit_receipts AS post
              ON post.transaction_id = h.transaction_id
            LEFT JOIN profiled_shadow_commitment_head_anchors AS anchor
              ON anchor.transaction_id = h.transaction_id
            ORDER BY h.sequence ASC
            LIMIT ?
            """,
            (_MAX_LEDGER_RECORDS + 1,),
        ).fetchall()

    @staticmethod
    def _preflight_database_size(connection: sqlite3.Connection) -> None:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        if (
            type(page_size) is not int
            or type(page_count) is not int
            or page_size <= 0
            or page_count < 0
            or page_size * page_count > _MAX_LEDGER_DATABASE_BYTES
        ):
            _integrity("SHADOW_COMMITMENT_DATABASE_RESOURCE_BOUND_EXCEEDED")

    @staticmethod
    def _preflight_json_resource_bounds(connection: sqlite3.Connection) -> None:
        aggregates = connection.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(length(CAST(commitment_json AS BLOB)))
                    FROM profiled_shadow_hypotheses
                ), 0)
                + COALESCE((
                    SELECT SUM(length(CAST(index_entry_json AS BLOB)))
                    FROM profiled_shadow_pending_hypothesis_index
                ), 0)
                + COALESCE((
                    SELECT SUM(length(CAST(receipt_json AS BLOB)))
                    FROM profiled_shadow_commitment_append_receipts
                ), 0)
                + COALESCE((
                    SELECT SUM(length(CAST(readback_receipt_json AS BLOB)))
                    FROM profiled_shadow_commitment_postcommit_receipts
                ), 0)
                + COALESCE((
                    SELECT SUM(length(CAST(head_anchor_json AS BLOB)))
                    FROM profiled_shadow_commitment_head_anchors
                ), 0)
                AS aggregate_json_bytes
            """
        ).fetchone()["aggregate_json_bytes"]
        if (
            type(aggregates) is not int
            or aggregates < 0
            or aggregates > _MAX_LEDGER_AGGREGATE_JSON_BYTES
        ):
            _integrity("SHADOW_COMMITMENT_JSON_RESOURCE_BOUND_EXCEEDED")

    def _verify_database_integrity(
        self,
        connection: sqlite3.Connection,
        *,
        require_postcommit: bool,
    ) -> tuple[ProfiledResearchShadowHypothesisCommitmentIntegrityV1, list[sqlite3.Row]]:
        self._preflight_database_size(connection)
        _validate_schema(connection)
        self._preflight_json_resource_bounds(connection)
        rows = self._joined_rows(connection)
        if len(rows) > _MAX_LEDGER_RECORDS:
            _integrity("SHADOW_COMMITMENT_LEDGER_RESOURCE_BOUND_EXCEEDED")
        counts = {
            "profiled_shadow_hypotheses": int(
                connection.execute(
                    "SELECT COUNT(*) FROM profiled_shadow_hypotheses"
                ).fetchone()[0]
            ),
            "profiled_shadow_pending_hypothesis_index": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM profiled_shadow_pending_hypothesis_index
                    """
                ).fetchone()[0]
            ),
            "profiled_shadow_commitment_append_receipts": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM profiled_shadow_commitment_append_receipts
                    """
                ).fetchone()[0]
            ),
            "profiled_shadow_commitment_postcommit_receipts": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM profiled_shadow_commitment_postcommit_receipts
                    """
                ).fetchone()[0]
            ),
            "profiled_shadow_commitment_head_anchors": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM profiled_shadow_commitment_head_anchors
                    """
                ).fetchone()[0]
            ),
        }
        expected_count = len(rows)
        if (
            counts["profiled_shadow_hypotheses"] != expected_count
            or counts["profiled_shadow_pending_hypothesis_index"] != expected_count
            or counts["profiled_shadow_commitment_append_receipts"]
            != expected_count
            or (
                require_postcommit
                and counts["profiled_shadow_commitment_postcommit_receipts"]
                != expected_count
            )
            or counts["profiled_shadow_commitment_postcommit_receipts"]
            > expected_count
            or counts["profiled_shadow_commitment_head_anchors"]
            != counts["profiled_shadow_commitment_postcommit_receipts"]
        ):
            _integrity("SHADOW_COMMITMENT_LEDGER_CARDINALITY_INVALID")

        previous_chain = _GENESIS_CHAIN_SHA256
        previous_commit: datetime | None = None
        previous_postcommit: datetime | None = None
        missing_postcommit_seen = False
        postcommit_verified = 0
        ex_ante_verified = 0
        quarantined = 0
        head_anchors_verified = 0
        previous_head_anchor = _GENESIS_HEAD_ANCHOR_SHA256
        previous_raw_high_water: datetime | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            if type(row["sequence"]) is not int or row["sequence"] != expected_sequence:
                _integrity("SHADOW_COMMITMENT_SEQUENCE_INVALID")
            sha_fields = (
                "hypothesis_identity_sha256",
                "hypothesis_artifact_sha256",
                "cost_closure_sha256",
                "cost_evidence_artifact_sha256",
                "raw_inference_binding_sha256",
                "hypothesis_material_sha256",
                "commitment_sha256",
                "previous_chain_sha256",
                "record_chain_sha256",
                "index_entry_sha256",
                "append_receipt_sha256",
            )
            if any(_strict_sha256(row[field_name]) is None for field_name in sha_fields):
                _integrity("SHADOW_COMMITMENT_HASH_FIELD_INVALID")
            if (
                row["previous_chain_sha256"] != previous_chain
                or row["index_identity_sha256"]
                != row["hypothesis_identity_sha256"]
                or row["index_artifact_sha256"]
                != row["hypothesis_artifact_sha256"]
                or row["index_decision_time"] != row["decision_time"]
                or row["index_label_available_at"]
                != row["label_earliest_available_at"]
                or row["index_transaction_id"] != row["transaction_id"]
                or row["index_registered_at"] != row["commit_prepared_at"]
                or row["receipt_identity_sha256"]
                != row["hypothesis_identity_sha256"]
                or row["receipt_artifact_sha256"]
                != row["hypothesis_artifact_sha256"]
                or row["receipt_closure_sha256"] != row["cost_closure_sha256"]
                or row["receipt_previous_chain_sha256"]
                != row["previous_chain_sha256"]
                or row["receipt_record_chain_sha256"]
                != row["record_chain_sha256"]
                or row["receipt_commitment_sha256"] != row["commitment_sha256"]
                or row["total_committed_hypotheses"] != expected_sequence
                or row["receipt_commit_observed_at"]
                != row["commit_observed_at"]
                or row["receipt_commit_prepared_at"] != row["commit_prepared_at"]
                or row["precommit_readback_verified"] != 1
            ):
                _integrity("SHADOW_COMMITMENT_RELATIONAL_BINDING_INVALID")

            decision_clock = _aware_clock(row["decision_time"])
            generated_clock = _aware_clock(row["hypothesis_generated_at"])
            label_clock = _aware_clock(row["label_earliest_available_at"])
            commit_observed_clock = _aware_clock(row["commit_observed_at"])
            commit_clock = _canonical_millisecond_clock(row["commit_prepared_at"])
            horizon = _strict_positive_int(row["holding_horizon_seconds"])
            if (
                decision_clock is None
                or generated_clock is None
                or label_clock is None
                or commit_observed_clock is None
                or commit_clock is None
                or horizon != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
                or _format_microsecond(decision_clock) != row["decision_time"]
                or _format_microsecond(generated_clock)
                != row["hypothesis_generated_at"]
                or _format_microsecond(label_clock)
                != row["label_earliest_available_at"]
                or _format_microsecond(commit_observed_clock)
                != row["commit_observed_at"]
            ):
                _integrity("SHADOW_COMMITMENT_CLOCK_INVALID")
            try:
                expected_label_clock = decision_clock + timedelta(seconds=horizon)
            except OverflowError:
                _integrity("SHADOW_COMMITMENT_LABEL_CLOCK_OVERFLOW")
            if (
                expected_label_clock != label_clock
                or generated_clock < decision_clock
                or commit_observed_clock < generated_clock
                or commit_observed_clock >= label_clock
                or commit_clock < commit_observed_clock
                or commit_clock >= label_clock
                or (
                    previous_raw_high_water is not None
                    and commit_observed_clock <= previous_raw_high_water
                )
                or (previous_commit is not None and commit_clock <= previous_commit)
                or (
                    previous_postcommit is not None
                    and commit_clock <= previous_postcommit
                )
            ):
                _integrity("SHADOW_COMMITMENT_EX_ANTE_CLOCK_CAUSALITY_INVALID")

            commitment_material = self._commitment_material_from_row(row)
            commitment_json = _canonical_json(
                commitment_material,
                reason="SHADOW_COMMITMENT_COMMITMENT_JSON_INVALID",
            )
            if (
                row["commitment_json"] != commitment_json
                or row["commitment_sha256"]
                != hashlib.sha256(commitment_json.encode("ascii")).hexdigest()
                or _parse_exact_object(
                    row["commitment_json"],
                    reason="SHADOW_COMMITMENT_COMMITMENT_JSON_INVALID",
                )
                != commitment_material
            ):
                _integrity("SHADOW_COMMITMENT_COMMITMENT_RECEIPT_INVALID")
            expected_chain = _sha256(
                {
                    "domain": "v2/native-trainer/profiled-shadow-commit-chain/v1",
                    "sequence": expected_sequence,
                    "previous_chain_sha256": previous_chain,
                    "commitment_sha256": row["commitment_sha256"],
                    "hypothesis_identity_sha256": row[
                        "hypothesis_identity_sha256"
                    ],
                    "hypothesis_artifact_sha256": row[
                        "hypothesis_artifact_sha256"
                    ],
                    "cost_closure_sha256": row["cost_closure_sha256"],
                    "transaction_id": row["transaction_id"],
                    "commit_observed_at": row["commit_observed_at"],
                    "commit_prepared_at": row["commit_prepared_at"],
                }
            )
            if expected_chain != row["record_chain_sha256"]:
                _integrity("SHADOW_COMMITMENT_CHAIN_INVALID")

            index_material = self._index_material_from_row(row)
            index_json = _canonical_json(
                index_material,
                reason="SHADOW_COMMITMENT_PENDING_INDEX_JSON_INVALID",
            )
            append_material = self._append_receipt_material_from_row(row)
            append_json = _canonical_json(
                append_material,
                reason="SHADOW_COMMITMENT_APPEND_RECEIPT_JSON_INVALID",
            )
            if (
                row["index_entry_json"] != index_json
                or row["index_entry_sha256"]
                != hashlib.sha256(index_json.encode("ascii")).hexdigest()
                or row["append_receipt_json"] != append_json
                or row["append_receipt_sha256"]
                != hashlib.sha256(append_json.encode("ascii")).hexdigest()
                or _parse_exact_object(
                    row["index_entry_json"],
                    reason="SHADOW_COMMITMENT_PENDING_INDEX_JSON_INVALID",
                )
                != index_material
                or _parse_exact_object(
                    row["append_receipt_json"],
                    reason="SHADOW_COMMITMENT_APPEND_RECEIPT_JSON_INVALID",
                )
                != append_material
            ):
                _integrity("SHADOW_COMMITMENT_APPEND_OR_INDEX_RECEIPT_INVALID")

            postcommit_clock: datetime | None = None
            if row["postcommit_readback_at"] is None:
                missing_postcommit_seen = True
                if row["head_anchor_sha256"] is not None:
                    _integrity("SHADOW_COMMITMENT_ORPHAN_HEAD_ANCHOR")
                if require_postcommit:
                    _integrity("SHADOW_COMMITMENT_POSTCOMMIT_RECEIPT_MISSING")
            else:
                if missing_postcommit_seen:
                    _integrity("SHADOW_COMMITMENT_POSTCOMMIT_GAP_NOT_TAIL")
                post_sha_fields = (
                    "post_append_receipt_sha256",
                    "post_identity_sha256",
                    "post_artifact_sha256",
                    "post_record_chain_sha256",
                    "readback_receipt_sha256",
                    "head_anchor_identity",
                    "head_anchor_artifact",
                    "head_anchor_record_chain",
                    "head_anchor_append_receipt",
                    "head_anchor_postcommit_receipt",
                    "previous_head_anchor_sha256",
                    "head_anchor_sha256",
                )
                if any(
                    _strict_sha256(row[field_name]) is None
                    for field_name in post_sha_fields
                ):
                    _integrity("SHADOW_COMMITMENT_POSTCOMMIT_HASH_INVALID")
                postcommit_clock = _canonical_millisecond_clock(
                    row["postcommit_readback_at"]
                )
                postcommit_observed_clock = _aware_clock(
                    row["postcommit_observed_at"]
                )
                ex_ante_durability_verified = row[
                    "ex_ante_durability_verified"
                ]
                if (
                    postcommit_clock is None
                    or postcommit_observed_clock is None
                    or _format_microsecond(postcommit_observed_clock)
                    != row["postcommit_observed_at"]
                    or postcommit_clock < postcommit_observed_clock
                    or postcommit_clock <= commit_clock
                    or type(ex_ante_durability_verified) is not int
                    or ex_ante_durability_verified not in (0, 1)
                    or (
                        postcommit_observed_clock > commit_observed_clock
                        and postcommit_observed_clock < label_clock
                    )
                    != (ex_ante_durability_verified == 1)
                    or (
                        previous_postcommit is not None
                        and postcommit_clock <= previous_postcommit
                    )
                    or row["post_append_receipt_sha256"]
                    != row["append_receipt_sha256"]
                    or row["post_identity_sha256"]
                    != row["hypothesis_identity_sha256"]
                    or row["post_artifact_sha256"]
                    != row["hypothesis_artifact_sha256"]
                    or row["post_record_chain_sha256"]
                    != row["record_chain_sha256"]
                    or row["head_anchor_sequence"] != expected_sequence
                    or row["head_anchor_transaction_id"]
                    != row["transaction_id"]
                    or row["head_anchor_total"] != expected_sequence
                    or row["head_anchor_identity"]
                    != row["hypothesis_identity_sha256"]
                    or row["head_anchor_artifact"]
                    != row["hypothesis_artifact_sha256"]
                    or row["head_anchor_record_chain"]
                    != row["record_chain_sha256"]
                    or row["head_anchor_append_receipt"]
                    != row["append_receipt_sha256"]
                    or row["head_anchor_postcommit_receipt"]
                    != row["readback_receipt_sha256"]
                    or row["previous_head_anchor_sha256"]
                    != previous_head_anchor
                    or row["head_anchor_anchored_at"]
                    != row["postcommit_readback_at"]
                    or row["head_anchor_commit_observed_at"]
                    != row["commit_observed_at"]
                    or row["head_anchor_postcommit_observed_at"]
                    != row["postcommit_observed_at"]
                    or row["head_anchor_ex_ante_verified"]
                    != ex_ante_durability_verified
                ):
                    _integrity("SHADOW_COMMITMENT_POSTCOMMIT_BINDING_INVALID")
                post_material = self._postcommit_material_from_row(row)
                post_json = _canonical_json(
                    post_material,
                    reason="SHADOW_COMMITMENT_POSTCOMMIT_JSON_INVALID",
                )
                if (
                    row["readback_receipt_json"] != post_json
                    or row["readback_receipt_sha256"]
                    != hashlib.sha256(post_json.encode("ascii")).hexdigest()
                    or _parse_exact_object(
                        row["readback_receipt_json"],
                        reason="SHADOW_COMMITMENT_POSTCOMMIT_JSON_INVALID",
                    )
                    != post_material
                ):
                    _integrity("SHADOW_COMMITMENT_POSTCOMMIT_RECEIPT_INVALID")
                head_material = self._head_anchor_material_from_row(row)
                head_json = _canonical_json(
                    head_material,
                    reason="SHADOW_COMMITMENT_HEAD_ANCHOR_JSON_INVALID",
                )
                head_address = _address_from_columns(
                    sha256=row["head_anchor_sha256"],
                    byte_count=row["head_anchor_byte_count"],
                    relative_path=row["head_anchor_relative_path"],
                )
                if (
                    row["head_anchor_json"] != head_json
                    or head_address != _expected_address(head_json.encode("ascii"))
                    or _parse_exact_object(
                        row["head_anchor_json"],
                        reason="SHADOW_COMMITMENT_HEAD_ANCHOR_JSON_INVALID",
                    )
                    != head_material
                ):
                    _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_INVALID")
                postcommit_verified += 1
                if ex_ante_durability_verified == 1:
                    ex_ante_verified += 1
                else:
                    quarantined += 1
                previous_postcommit = postcommit_clock
                previous_raw_high_water = max(
                    commit_observed_clock,
                    postcommit_observed_clock,
                )
                previous_head_anchor = cast(str, row["head_anchor_sha256"])
                head_anchors_verified += 1
            previous_chain = cast(str, row["record_chain_sha256"])
            previous_commit = commit_clock
            if row["postcommit_readback_at"] is None:
                previous_raw_high_water = commit_observed_clock

        return (
            ProfiledResearchShadowHypothesisCommitmentIntegrityV1(
                total_committed_hypotheses=expected_count,
                ex_ante_verified_hypotheses=ex_ante_verified,
                quarantined_hypotheses=quarantined,
                append_receipts_verified=expected_count,
                postcommit_receipts_verified=postcommit_verified,
                pending_index_entries_verified=expected_count,
                head_anchors_verified=head_anchors_verified,
                chain_head_sha256=previous_chain,
                last_commit_prepared_at=(
                    cast(str, rows[-1]["commit_prepared_at"]) if rows else None
                ),
                last_postcommit_readback_at=(
                    cast(str, rows[-1]["postcommit_readback_at"])
                    if rows and rows[-1]["postcommit_readback_at"] is not None
                    else None
                ),
                schema_verified=True,
                clock_causality_verified=True,
                cas_closures_verified=0,
                cas_head_anchors_verified=0,
            ),
            rows,
        )

    @staticmethod
    def _row_matches_prepared(
        row: sqlite3.Row,
        prepared: _PreparedHypothesis,
    ) -> bool:
        return (
            row["hypothesis_identity_sha256"]
            == prepared.hypothesis_identity_sha256
            and row["hypothesis_artifact_sha256"]
            == prepared.artifact_address.payload_sha256
            and row["hypothesis_artifact_byte_count"]
            == prepared.artifact_address.payload_byte_count
            and row["hypothesis_artifact_relative_path"]
            == prepared.artifact_address.relative_path
            and row["cost_closure_sha256"]
            == prepared.closure_address.payload_sha256
            and row["cost_closure_byte_count"]
            == prepared.closure_address.payload_byte_count
            and row["cost_closure_relative_path"]
            == prepared.closure_address.relative_path
            and row["cost_evidence_artifact_sha256"]
            == prepared.cost_evidence_artifact_sha256
            and row["raw_inference_binding_sha256"]
            == prepared.raw_inference_binding_sha256
            and row["hypothesis_material_sha256"]
            == prepared.hypothesis_material_sha256
            and row["symbol"] == prepared.symbol
            and row["durable_snapshot_id"] == prepared.durable_snapshot_id
            and row["decision_time"] == prepared.decision_time
            and row["hypothesis_generated_at"]
            == prepared.hypothesis_generated_at
            and row["label_earliest_available_at"]
            == prepared.label_earliest_available_at
            and row["holding_horizon_seconds"]
            == prepared.holding_horizon_seconds
            and row["transaction_id"]
            == ProfiledResearchShadowHypothesisCommitmentLedgerV1._transaction_id(
                prepared
            )
        )

    def _reopen_row_cas(
        self,
        row: sqlite3.Row,
        *,
        store: ImmutableSourcePayloadStore,
    ) -> _PreparedHypothesis:
        artifact_address = _address_from_columns(
            sha256=row["hypothesis_artifact_sha256"],
            byte_count=row["hypothesis_artifact_byte_count"],
            relative_path=row["hypothesis_artifact_relative_path"],
        )
        closure_address = _address_from_columns(
            sha256=row["cost_closure_sha256"],
            byte_count=row["cost_closure_byte_count"],
            relative_path=row["cost_closure_relative_path"],
        )
        try:
            artifact_bytes = store.get(
                artifact_address.payload_sha256,
                expected_byte_count=artifact_address.payload_byte_count,
            )
            closure = open_paper_research_causal_cost_portable_closure_v1(
                store=store,
                closure_address=closure_address,
            )
        except (SourcePayloadStoreError, PaperResearchCausalCostPortableClosureV1Error) as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_RESTART_CAS_REOPEN_FAILED"
            ) from exc
        prepared = _validate_hypothesis_against_closure(
            artifact_bytes=artifact_bytes,
            artifact_address=artifact_address,
            cost_closure=closure,
        )
        if not self._row_matches_prepared(row, prepared):
            _integrity("SHADOW_COMMITMENT_RESTART_ROW_CAS_BINDING_INVALID")
        return prepared

    def _verify_rows_cas(
        self,
        rows: list[sqlite3.Row],
        *,
        store: ImmutableSourcePayloadStore,
    ) -> list[_PreparedHypothesis]:
        return [self._reopen_row_cas(row, store=store) for row in rows]

    @property
    def _head_anchor_catalog_root(self) -> Path:
        return self.path.with_name(self.path.name + ".head-anchor-cas")

    def _observed_head_anchor_catalog_digests(self) -> frozenset[str]:
        root = self._head_anchor_catalog_root
        if not root.exists():
            return frozenset()
        namespace = root / "sha256"
        if not namespace.is_dir():
            _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_INVALID")
        digests: set[str] = set()
        try:
            with os.scandir(namespace) as shards:
                for shard in shards:
                    if (
                        shard.name == "."
                        or shard.name == ".."
                        or re.fullmatch(r"[0-9a-f]{2}", shard.name) is None
                        or not shard.is_dir(follow_symlinks=False)
                    ):
                        _integrity(
                            "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_INVALID"
                        )
                    with os.scandir(shard.path) as objects:
                        for item in objects:
                            if (
                                _strict_sha256(item.name) is None
                                or not item.is_file(follow_symlinks=False)
                                or item.name[:2] != shard.name
                                or item.name in digests
                            ):
                                _integrity(
                                    "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_INVALID"
                                )
                            digests.add(item.name)
                            if len(digests) > _MAX_LEDGER_RECORDS:
                                _integrity(
                                    "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_LIMIT_EXCEEDED"
                                )
        except OSError as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_SCAN_FAILED"
            ) from exc
        return frozenset(digests)

    def _publish_head_anchor_catalog_entry(self, *, transaction_id: str) -> None:
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            _report, rows = self._verify_database_integrity(
                connection,
                require_postcommit=True,
            )
            matches = [row for row in rows if row["transaction_id"] == transaction_id]
            if len(matches) != 1:
                _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_TRANSACTION_MISSING")
            row = matches[0]
            anchor_address = _address_from_columns(
                sha256=row["head_anchor_sha256"],
                byte_count=row["head_anchor_byte_count"],
                relative_path=row["head_anchor_relative_path"],
            )
            anchor_bytes = cast(str, row["head_anchor_json"]).encode(
                "ascii",
                errors="strict",
            )
            connection.commit()
        finally:
            connection.close()
        catalog = ImmutableSourcePayloadStore(self._head_anchor_catalog_root)
        try:
            published = catalog.put(
                anchor_bytes,
                expected_sha256=anchor_address.payload_sha256,
                expected_byte_count=anchor_address.payload_byte_count,
            )
            readback = catalog.get(
                published.payload_sha256,
                expected_byte_count=published.payload_byte_count,
            )
        except SourcePayloadStoreError as exc:
            raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_PUBLICATION_FAILED"
            ) from exc
        if published != anchor_address or not hmac.compare_digest(
            readback,
            anchor_bytes,
        ):
            _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_READBACK_FAILED")

    def _verify_head_anchor_catalog(self, rows: list[sqlite3.Row]) -> int:
        expected_rows = [
            row for row in rows if row["postcommit_readback_at"] is not None
        ]
        expected = frozenset(
            cast(str, row["head_anchor_sha256"]) for row in expected_rows
        )
        observed = self._observed_head_anchor_catalog_digests()
        if observed != expected:
            _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_MEMBERSHIP_INVALID")
        if not expected_rows:
            return 0
        catalog = ImmutableSourcePayloadStore(self._head_anchor_catalog_root)
        for row in expected_rows:
            address = _address_from_columns(
                sha256=row["head_anchor_sha256"],
                byte_count=row["head_anchor_byte_count"],
                relative_path=row["head_anchor_relative_path"],
            )
            try:
                payload = catalog.get(
                    address.payload_sha256,
                    expected_byte_count=address.payload_byte_count,
                )
            except SourcePayloadStoreError as exc:
                raise ProfiledResearchShadowHypothesisCommitmentV1IntegrityError(
                    "SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_REOPEN_FAILED"
                ) from exc
            expected_payload = cast(str, row["head_anchor_json"]).encode(
                "ascii",
                errors="strict",
            )
            if not hmac.compare_digest(payload, expected_payload):
                _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_MISMATCH")
        return len(expected_rows)

    def verify_integrity(
        self,
        *,
        store: object,
    ) -> ProfiledResearchShadowHypothesisCommitmentIntegrityV1:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("SHADOW_COMMITMENT_EXACT_IMMUTABLE_STORE_REQUIRED")
        exact_store = cast(ImmutableSourcePayloadStore, store)
        with self._reader_snapshot_lease():
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                report, rows = self._verify_database_integrity(
                    connection,
                    require_postcommit=True,
                )
                connection.commit()
            finally:
                connection.close()
            verified = self._verify_rows_cas(rows, store=exact_store)
            verified_head_anchors = self._verify_head_anchor_catalog(rows)
            return ProfiledResearchShadowHypothesisCommitmentIntegrityV1(
                total_committed_hypotheses=report.total_committed_hypotheses,
                ex_ante_verified_hypotheses=report.ex_ante_verified_hypotheses,
                quarantined_hypotheses=report.quarantined_hypotheses,
                append_receipts_verified=report.append_receipts_verified,
                postcommit_receipts_verified=report.postcommit_receipts_verified,
                pending_index_entries_verified=(
                    report.pending_index_entries_verified
                ),
                head_anchors_verified=report.head_anchors_verified,
                chain_head_sha256=report.chain_head_sha256,
                last_commit_prepared_at=report.last_commit_prepared_at,
                last_postcommit_readback_at=report.last_postcommit_readback_at,
                schema_verified=True,
                clock_causality_verified=True,
                cas_closures_verified=len(verified),
                cas_head_anchors_verified=verified_head_anchors,
            )

    def _write_postcommit_readback(
        self,
        *,
        transaction_id: str,
        writer_lease: ProfiledResearchShadowHypothesisCommitmentWriterLease,
    ) -> None:
        writer_lease.validate_for(self.path)
        readonly = self._connect_readonly()
        try:
            readonly.execute("BEGIN")
            _report, rows = self._verify_database_integrity(
                readonly,
                require_postcommit=False,
            )
            matches = [row for row in rows if row["transaction_id"] == transaction_id]
            if len(matches) != 1:
                _integrity("SHADOW_COMMITMENT_POSTCOMMIT_TRANSACTION_MISSING")
            source_row = matches[0]
            readonly.commit()
        finally:
            readonly.close()
        if source_row["postcommit_readback_at"] is not None:
            self._publish_head_anchor_catalog_entry(
                transaction_id=transaction_id
            )
            return

        connection = self._connect_write(writer_lease=writer_lease)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _report, rows = self._verify_database_integrity(
                connection,
                require_postcommit=False,
            )
            matches = [row for row in rows if row["transaction_id"] == transaction_id]
            if len(matches) != 1:
                _integrity("SHADOW_COMMITMENT_POSTCOMMIT_TRANSACTION_MISSING")
            row = matches[0]
            if row["postcommit_readback_at"] is None:
                postcommit_readback_at, postcommit_observed_at = (
                    self._next_postcommit_clock(
                        connection,
                        commit_prepared_at=cast(
                            str,
                            row["commit_prepared_at"],
                        ),
                    )
                )
                postcommit_observed_clock = cast(
                    datetime,
                    _aware_clock(postcommit_observed_at),
                )
                commit_observed_clock = cast(
                    datetime,
                    _aware_clock(row["commit_observed_at"]),
                )
                label_clock = cast(
                    datetime,
                    _aware_clock(row["label_earliest_available_at"]),
                )
                ex_ante_durability_verified = int(
                    postcommit_observed_clock > commit_observed_clock
                    and postcommit_observed_clock < label_clock
                )
                material = {
                    "schema_version": (
                        PROFILED_RESEARCH_SHADOW_COMMITMENT_POSTCOMMIT_V1_SCHEMA_VERSION
                    ),
                    "transaction_id": row["transaction_id"],
                    "append_receipt_sha256": row["append_receipt_sha256"],
                    "hypothesis_identity_sha256": row[
                        "hypothesis_identity_sha256"
                    ],
                    "hypothesis_artifact_sha256": row[
                        "hypothesis_artifact_sha256"
                    ],
                    "record_chain_sha256": row["record_chain_sha256"],
                    "commit_observed_at": row["commit_observed_at"],
                    "postcommit_observed_at": postcommit_observed_at,
                    "postcommit_readback_at": postcommit_readback_at,
                    "independent_readback_verified": True,
                    "pending_hypothesis_index_readback_verified": True,
                    "durable_commit_observed_before_label_availability": (
                        ex_ante_durability_verified == 1
                    ),
                    "label_value_present": False,
                    "outcome_payload_present": False,
                    "authorization": dict(_AUTHORIZATION),
                }
                receipt_json = _canonical_json(
                    material,
                    reason="SHADOW_COMMITMENT_POSTCOMMIT_JSON_INVALID",
                )
                receipt_sha256 = hashlib.sha256(
                    receipt_json.encode("ascii")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO profiled_shadow_commitment_postcommit_receipts(
                        transaction_id,
                        append_receipt_sha256,
                        hypothesis_identity_sha256,
                        hypothesis_artifact_sha256,
                        record_chain_sha256,
                        readback_receipt_sha256,
                        readback_receipt_json,
                        postcommit_observed_at,
                        postcommit_readback_at,
                        ex_ante_durability_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["transaction_id"],
                        row["append_receipt_sha256"],
                        row["hypothesis_identity_sha256"],
                        row["hypothesis_artifact_sha256"],
                        row["record_chain_sha256"],
                        receipt_sha256,
                        receipt_json,
                        postcommit_observed_at,
                        postcommit_readback_at,
                        ex_ante_durability_verified,
                    ),
                )
                prior_anchor = connection.execute(
                    """
                    SELECT sequence, head_anchor_sha256
                    FROM profiled_shadow_commitment_head_anchors
                    ORDER BY sequence DESC
                    LIMIT 1
                    """
                ).fetchone()
                sequence = cast(int, row["sequence"])
                if sequence == 1:
                    if prior_anchor is not None:
                        _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_ORDER_INVALID")
                    previous_head_anchor = _GENESIS_HEAD_ANCHOR_SHA256
                else:
                    if (
                        prior_anchor is None
                        or prior_anchor["sequence"] != sequence - 1
                        or _strict_sha256(prior_anchor["head_anchor_sha256"])
                        is None
                    ):
                        _integrity("SHADOW_COMMITMENT_HEAD_ANCHOR_ORDER_INVALID")
                    previous_head_anchor = cast(
                        str,
                        prior_anchor["head_anchor_sha256"],
                    )
                anchor_material = {
                    "schema_version": (
                        PROFILED_RESEARCH_SHADOW_HEAD_ANCHOR_V1_SCHEMA_VERSION
                    ),
                    "sequence": sequence,
                    "transaction_id": row["transaction_id"],
                    "total_committed_hypotheses": sequence,
                    "hypothesis_identity_sha256": row[
                        "hypothesis_identity_sha256"
                    ],
                    "hypothesis_artifact_sha256": row[
                        "hypothesis_artifact_sha256"
                    ],
                    "record_chain_sha256": row["record_chain_sha256"],
                    "append_receipt_sha256": row["append_receipt_sha256"],
                    "postcommit_receipt_sha256": receipt_sha256,
                    "previous_head_anchor_sha256": previous_head_anchor,
                    "commit_observed_at": row["commit_observed_at"],
                    "postcommit_observed_at": postcommit_observed_at,
                    "anchored_at": postcommit_readback_at,
                    "ex_ante_durability_verified": (
                        ex_ante_durability_verified == 1
                    ),
                    "label_value_present": False,
                    "outcome_payload_present": False,
                    "research_only": True,
                    "authorization": dict(_AUTHORIZATION),
                }
                anchor_json = _canonical_json(
                    anchor_material,
                    reason="SHADOW_COMMITMENT_HEAD_ANCHOR_JSON_INVALID",
                )
                anchor_bytes = anchor_json.encode("ascii")
                anchor_address = _expected_address(anchor_bytes)
                connection.execute(
                    """
                    INSERT INTO profiled_shadow_commitment_head_anchors(
                        sequence,
                        transaction_id,
                        total_committed_hypotheses,
                        hypothesis_identity_sha256,
                        hypothesis_artifact_sha256,
                        record_chain_sha256,
                        append_receipt_sha256,
                        postcommit_receipt_sha256,
                        previous_head_anchor_sha256,
                        head_anchor_sha256,
                        head_anchor_byte_count,
                        head_anchor_relative_path,
                        head_anchor_json,
                        commit_observed_at,
                        postcommit_observed_at,
                        anchored_at,
                        ex_ante_durability_verified
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        sequence,
                        row["transaction_id"],
                        sequence,
                        row["hypothesis_identity_sha256"],
                        row["hypothesis_artifact_sha256"],
                        row["record_chain_sha256"],
                        row["append_receipt_sha256"],
                        receipt_sha256,
                        previous_head_anchor,
                        anchor_address.payload_sha256,
                        anchor_address.payload_byte_count,
                        anchor_address.relative_path,
                        anchor_json,
                        row["commit_observed_at"],
                        postcommit_observed_at,
                        postcommit_readback_at,
                        ex_ante_durability_verified,
                    ),
                )
            self._verify_database_integrity(
                connection,
                require_postcommit=True,
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

        self._publish_head_anchor_catalog_entry(transaction_id=transaction_id)
        readonly = self._connect_readonly()
        try:
            readonly.execute("BEGIN")
            self._verify_database_integrity(
                readonly,
                require_postcommit=True,
            )
            readonly.commit()
        finally:
            readonly.close()

    def recover_pending_postcommit_readbacks(
        self,
        *,
        store: object,
        max_transactions: int = _MAX_PENDING_RESULTS,
        writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ) = None,
    ) -> dict[str, int | str]:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("SHADOW_COMMITMENT_EXACT_IMMUTABLE_STORE_REQUIRED")
        bounded = _strict_positive_int(
            max_transactions,
            maximum=_MAX_PENDING_RESULTS,
        )
        if bounded is None:
            _validation("SHADOW_COMMITMENT_RECOVERY_LIMIT_INVALID")
        exact_store = cast(ImmutableSourcePayloadStore, store)
        with self.writer_lease(writer_lease) as held:
            self._ensure_initialized(writer_lease=held)
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_database_integrity(
                    connection,
                    require_postcommit=False,
                )
                pending = [
                    row
                    for row in rows
                    if row["postcommit_readback_at"] is None
                ]
                if len(pending) > bounded:
                    _integrity("SHADOW_COMMITMENT_RECOVERY_LIMIT_EXCEEDED")
                connection.commit()
            finally:
                connection.close()
            self._verify_rows_cas(pending, store=exact_store)
            for row in pending:
                self._write_postcommit_readback(
                    transaction_id=cast(str, row["transaction_id"]),
                    writer_lease=held,
                )
            final_connection = self._connect_readonly()
            try:
                final_connection.execute("BEGIN")
                final_report, final_rows = self._verify_database_integrity(
                    final_connection,
                    require_postcommit=True,
                )
                final_connection.commit()
            finally:
                final_connection.close()
            for row in final_rows:
                self._publish_head_anchor_catalog_entry(
                    transaction_id=cast(str, row["transaction_id"])
                )
            self._verify_head_anchor_catalog(final_rows)
            return {
                "status": "SHADOW_COMMITMENT_POSTCOMMIT_RECOVERY_COMPLETE",
                "pending_transactions": len(pending),
                "recovered_transactions": len(pending),
                "ex_ante_verified_transactions": (
                    final_report.ex_ante_verified_hypotheses
                ),
                "quarantined_transactions": final_report.quarantined_hypotheses,
            }

    def commit_hypothesis(
        self,
        *,
        hypothesis: object,
        cost_closure: object,
        store: object,
        writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ) = None,
    ) -> DurablyCommittedProfiledResearchShadowHypothesisV1:
        """Commit an exact hypothesis without accepting any future label data."""

        prepared = _preflight_hypothesis(
            hypothesis=hypothesis,
            cost_closure=cost_closure,
            store=store,
        )
        exact_store = cast(ImmutableSourcePayloadStore, store)
        transaction_id = self._transaction_id(prepared)
        duplicate = False
        with self.writer_lease(writer_lease) as held:
            self._ensure_initialized(writer_lease=held)
            self.recover_pending_postcommit_readbacks(
                store=exact_store,
                writer_lease=held,
            )
            readonly = self._connect_readonly()
            try:
                readonly.execute("BEGIN")
                _report, existing_rows = self._verify_database_integrity(
                    readonly,
                    require_postcommit=True,
                )
                readonly.commit()
            finally:
                readonly.close()
            self._verify_rows_cas(existing_rows, store=exact_store)
            self._verify_head_anchor_catalog(existing_rows)

            connection = self._connect_write(writer_lease=held)
            try:
                connection.execute("BEGIN IMMEDIATE")
                report, rows = self._verify_database_integrity(
                    connection,
                    require_postcommit=True,
                )
                conflicts = [
                    row
                    for row in rows
                    if row["hypothesis_identity_sha256"]
                    == prepared.hypothesis_identity_sha256
                    or row["hypothesis_artifact_sha256"]
                    == prepared.artifact_address.payload_sha256
                    or row["transaction_id"] == transaction_id
                ]
                if conflicts:
                    if len(conflicts) != 1 or not self._row_matches_prepared(
                        conflicts[0],
                        prepared,
                    ):
                        raise ProfiledResearchShadowHypothesisCommitmentV1ConflictError(
                            "SHADOW_COMMITMENT_IMMUTABLE_IDENTITY_CONFLICT"
                        )
                    duplicate = True
                    connection.rollback()
                else:
                    if report.total_committed_hypotheses >= _MAX_LEDGER_RECORDS:
                        _integrity("SHADOW_COMMITMENT_LEDGER_RESOURCE_BOUND_EXCEEDED")
                    sequence = report.total_committed_hypotheses + 1
                    previous_chain = report.chain_head_sha256
                    commit_prepared_at, commit_observed_at = (
                        self._next_commit_clock(connection)
                    )
                    commit_clock = cast(
                        datetime,
                        _canonical_millisecond_clock(commit_prepared_at),
                    )
                    generated_clock = cast(
                        datetime,
                        _aware_clock(prepared.hypothesis_generated_at),
                    )
                    label_clock = cast(
                        datetime,
                        _aware_clock(prepared.label_earliest_available_at),
                    )
                    commit_observed_clock = cast(
                        datetime,
                        _aware_clock(commit_observed_at),
                    )
                    if commit_observed_clock < generated_clock:
                        _validation(
                            "SHADOW_COMMITMENT_INTERNAL_CLOCK_PRECEDES_HYPOTHESIS"
                        )
                    if (
                        commit_observed_clock >= label_clock
                        or commit_clock >= label_clock
                    ):
                        _validation(
                            "SHADOW_COMMITMENT_EX_ANTE_WINDOW_CLOSED"
                        )
                    commitment_material = self._commitment_material(
                        prepared=prepared,
                        transaction_id=transaction_id,
                        commit_observed_at=commit_observed_at,
                        commit_prepared_at=commit_prepared_at,
                    )
                    commitment_json = _canonical_json(
                        commitment_material,
                        reason="SHADOW_COMMITMENT_COMMITMENT_JSON_INVALID",
                    )
                    commitment_sha256 = hashlib.sha256(
                        commitment_json.encode("ascii")
                    ).hexdigest()
                    record_chain = self._record_chain_sha256(
                        sequence=sequence,
                        previous_chain_sha256=previous_chain,
                        commitment_sha256=commitment_sha256,
                        prepared=prepared,
                        transaction_id=transaction_id,
                        commit_observed_at=commit_observed_at,
                        commit_prepared_at=commit_prepared_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO profiled_shadow_hypotheses(
                            sequence,
                            hypothesis_identity_sha256,
                            hypothesis_artifact_sha256,
                            hypothesis_artifact_byte_count,
                            hypothesis_artifact_relative_path,
                            cost_closure_sha256,
                            cost_closure_byte_count,
                            cost_closure_relative_path,
                            cost_evidence_artifact_sha256,
                            raw_inference_binding_sha256,
                            hypothesis_material_sha256,
                            symbol,
                            durable_snapshot_id,
                            decision_time,
                            hypothesis_generated_at,
                            label_earliest_available_at,
                            holding_horizon_seconds,
                            commitment_sha256,
                            commitment_json,
                            previous_chain_sha256,
                            record_chain_sha256,
                            transaction_id,
                            commit_observed_at,
                            commit_prepared_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            sequence,
                            prepared.hypothesis_identity_sha256,
                            prepared.artifact_address.payload_sha256,
                            prepared.artifact_address.payload_byte_count,
                            prepared.artifact_address.relative_path,
                            prepared.closure_address.payload_sha256,
                            prepared.closure_address.payload_byte_count,
                            prepared.closure_address.relative_path,
                            prepared.cost_evidence_artifact_sha256,
                            prepared.raw_inference_binding_sha256,
                            prepared.hypothesis_material_sha256,
                            prepared.symbol,
                            prepared.durable_snapshot_id,
                            prepared.decision_time,
                            prepared.hypothesis_generated_at,
                            prepared.label_earliest_available_at,
                            prepared.holding_horizon_seconds,
                            commitment_sha256,
                            commitment_json,
                            previous_chain,
                            record_chain,
                            transaction_id,
                            commit_observed_at,
                            commit_prepared_at,
                        ),
                    )
                    index_material = {
                        "schema_version": (
                            PROFILED_RESEARCH_SHADOW_PENDING_INDEX_V1_SCHEMA_VERSION
                        ),
                        "status": (
                            "PENDING_FINALIZED_LABEL_OUTCOME_NOT_AUTHORIZED"
                        ),
                        "hypothesis_identity_sha256": (
                            prepared.hypothesis_identity_sha256
                        ),
                        "hypothesis_artifact_sha256": (
                            prepared.artifact_address.payload_sha256
                        ),
                        "decision_time": prepared.decision_time,
                        "label_earliest_available_at": (
                            prepared.label_earliest_available_at
                        ),
                        "transaction_id": transaction_id,
                        "registered_at": commit_prepared_at,
                        "label_value_present": False,
                        "outcome_payload_present": False,
                        "outcome_maturation_authorized": False,
                        "calibration_input_authorized": False,
                        "research_only": True,
                    }
                    index_json = _canonical_json(
                        index_material,
                        reason="SHADOW_COMMITMENT_PENDING_INDEX_JSON_INVALID",
                    )
                    index_sha256 = hashlib.sha256(
                        index_json.encode("ascii")
                    ).hexdigest()
                    connection.execute(
                        """
                        INSERT INTO profiled_shadow_pending_hypothesis_index(
                            hypothesis_identity_sha256,
                            hypothesis_artifact_sha256,
                            decision_time,
                            label_earliest_available_at,
                            transaction_id,
                            registered_at,
                            index_entry_sha256,
                            index_entry_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            prepared.hypothesis_identity_sha256,
                            prepared.artifact_address.payload_sha256,
                            prepared.decision_time,
                            prepared.label_earliest_available_at,
                            transaction_id,
                            commit_prepared_at,
                            index_sha256,
                            index_json,
                        ),
                    )
                    append_material = {
                        "schema_version": (
                            PROFILED_RESEARCH_SHADOW_COMMITMENT_APPEND_RECEIPT_V1_SCHEMA_VERSION
                        ),
                        "transaction_id": transaction_id,
                        "hypothesis_identity_sha256": (
                            prepared.hypothesis_identity_sha256
                        ),
                        "hypothesis_artifact_sha256": (
                            prepared.artifact_address.payload_sha256
                        ),
                        "cost_closure_sha256": (
                            prepared.closure_address.payload_sha256
                        ),
                        "commitment_sha256": commitment_sha256,
                        "previous_chain_sha256": previous_chain,
                        "record_chain_sha256": record_chain,
                        "total_committed_hypotheses": sequence,
                        "commit_observed_at": commit_observed_at,
                        "commit_prepared_at": commit_prepared_at,
                        "precommit_readback_verified": True,
                        "pending_hypothesis_index_registered": True,
                        "label_value_present": False,
                        "outcome_payload_present": False,
                        "authorization": dict(_AUTHORIZATION),
                    }
                    receipt_json = _canonical_json(
                        append_material,
                        reason="SHADOW_COMMITMENT_APPEND_RECEIPT_JSON_INVALID",
                    )
                    receipt_sha256 = hashlib.sha256(
                        receipt_json.encode("ascii")
                    ).hexdigest()
                    connection.execute(
                        """
                        INSERT INTO profiled_shadow_commitment_append_receipts(
                            transaction_id,
                            hypothesis_identity_sha256,
                            hypothesis_artifact_sha256,
                            cost_closure_sha256,
                            previous_chain_sha256,
                            record_chain_sha256,
                            commitment_sha256,
                            total_committed_hypotheses,
                            receipt_sha256,
                            receipt_json,
                            commit_observed_at,
                            commit_prepared_at,
                            precommit_readback_verified
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            transaction_id,
                            prepared.hypothesis_identity_sha256,
                            prepared.artifact_address.payload_sha256,
                            prepared.closure_address.payload_sha256,
                            previous_chain,
                            record_chain,
                            commitment_sha256,
                            sequence,
                            receipt_sha256,
                            receipt_json,
                            commit_observed_at,
                            commit_prepared_at,
                        ),
                    )
                    precommit_report, precommit_rows = (
                        self._verify_database_integrity(
                            connection,
                            require_postcommit=False,
                        )
                    )
                    if (
                        precommit_report.total_committed_hypotheses != sequence
                        or len(precommit_rows) != sequence
                        or not self._row_matches_prepared(
                            precommit_rows[-1],
                            prepared,
                        )
                    ):
                        _integrity("SHADOW_COMMITMENT_PRECOMMIT_READBACK_FAILED")
                    connection.commit()
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise ProfiledResearchShadowHypothesisCommitmentV1ConflictError(
                    "SHADOW_COMMITMENT_SQLITE_IDENTITY_CONFLICT"
                ) from exc
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
            if not duplicate:
                self._write_postcommit_readback(
                    transaction_id=transaction_id,
                    writer_lease=held,
                )
            held.validate_for(self.path)
            result = self._open_committed_hypothesis_under_stability_lease(
                hypothesis_artifact_sha256=(
                    prepared.artifact_address.payload_sha256
                ),
                store=exact_store,
                validation_writer_lease=held,
            )
            held.validate_for(self.path)
            return result

    def _make_result(
        self,
        row: sqlite3.Row,
        prepared: _PreparedHypothesis,
        *,
        store: ImmutableSourcePayloadStore,
        validation_writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ),
    ) -> DurablyCommittedProfiledResearchShadowHypothesisV1:
        if row["postcommit_readback_at"] is None:
            _integrity("SHADOW_COMMITMENT_POSTCOMMIT_RECOVERY_REQUIRED")
        if row["ex_ante_durability_verified"] != 1:
            _integrity("SHADOW_COMMITMENT_EX_ANTE_DURABILITY_UNVERIFIED")
        public = {
            "hypothesis_identity_sha256": row[
                "hypothesis_identity_sha256"
            ],
            "hypothesis_artifact_sha256": row[
                "hypothesis_artifact_sha256"
            ],
            "hypothesis_artifact_byte_count": row[
                "hypothesis_artifact_byte_count"
            ],
            "hypothesis_artifact_address": prepared.artifact_address,
            "cost_closure_address": prepared.closure_address,
            "cost_evidence_artifact_sha256": row[
                "cost_evidence_artifact_sha256"
            ],
            "raw_inference_binding_sha256": row[
                "raw_inference_binding_sha256"
            ],
            "hypothesis_material_sha256": row["hypothesis_material_sha256"],
            "symbol": row["symbol"],
            "durable_snapshot_id": row["durable_snapshot_id"],
            "decision_time": row["decision_time"],
            "hypothesis_generated_at": row["hypothesis_generated_at"],
            "label_earliest_available_at": row[
                "label_earliest_available_at"
            ],
            "holding_horizon_seconds": row["holding_horizon_seconds"],
            "transaction_id": row["transaction_id"],
            "append_receipt_sha256": row["append_receipt_sha256"],
            "postcommit_readback_receipt_sha256": row[
                "readback_receipt_sha256"
            ],
            "commitment_sha256": row["commitment_sha256"],
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
            store=store,
        )
        return DurablyCommittedProfiledResearchShadowHypothesisV1(
            **public,
            _artifact_json=artifact_json,
            _ledger=self,
            _store=store,
            _validation_writer_lease=validation_writer_lease,
            _factory_seal=seal,
            _construction_token=_RESULT_TOKEN,
        )

    def _open_committed_hypothesis_under_stability_lease(
        self,
        *,
        hypothesis_artifact_sha256: str,
        store: ImmutableSourcePayloadStore,
        validation_writer_lease: (
            ProfiledResearchShadowHypothesisCommitmentWriterLease | None
        ),
    ) -> DurablyCommittedProfiledResearchShadowHypothesisV1:
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            _report, rows = self._verify_database_integrity(
                connection,
                require_postcommit=True,
            )
            matches = [
                row
                for row in rows
                if row["hypothesis_artifact_sha256"]
                == hypothesis_artifact_sha256
            ]
            if len(matches) != 1:
                _validation("SHADOW_COMMITMENT_HYPOTHESIS_NOT_FOUND")
            row = matches[0]
            if row["ex_ante_durability_verified"] != 1:
                _validation("SHADOW_COMMITMENT_EX_ANTE_DURABILITY_UNVERIFIED")
            connection.commit()
        finally:
            connection.close()
        prepared = self._reopen_row_cas(row, store=store)
        self._verify_head_anchor_catalog(rows)
        return self._make_result(
            row,
            prepared,
            store=store,
            validation_writer_lease=validation_writer_lease,
        )

    def open_committed_hypothesis(
        self,
        *,
        hypothesis_artifact_sha256: object,
        store: object,
    ) -> DurablyCommittedProfiledResearchShadowHypothesisV1:
        if _strict_sha256(hypothesis_artifact_sha256) is None:
            _validation("SHADOW_COMMITMENT_HYPOTHESIS_SHA256_INVALID")
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("SHADOW_COMMITMENT_EXACT_IMMUTABLE_STORE_REQUIRED")
        exact_store = cast(ImmutableSourcePayloadStore, store)
        with self._reader_snapshot_lease():
            return self._open_committed_hypothesis_under_stability_lease(
                hypothesis_artifact_sha256=cast(
                    str,
                    hypothesis_artifact_sha256,
                ),
                store=exact_store,
                validation_writer_lease=self._writer_lease,
            )

    def list_pending_hypotheses(
        self,
        *,
        store: object,
        max_results: int = _MAX_PENDING_RESULTS,
    ) -> tuple[DurablyCommittedProfiledResearchShadowHypothesisV1, ...]:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("SHADOW_COMMITMENT_EXACT_IMMUTABLE_STORE_REQUIRED")
        bounded = _strict_positive_int(max_results, maximum=_MAX_PENDING_RESULTS)
        if bounded is None:
            _validation("SHADOW_COMMITMENT_PENDING_RESULT_LIMIT_INVALID")
        exact_store = cast(ImmutableSourcePayloadStore, store)
        with self._reader_snapshot_lease():
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                _report, rows = self._verify_database_integrity(
                    connection,
                    require_postcommit=True,
                )
                eligible_rows = [
                    row
                    for row in rows
                    if row["ex_ante_durability_verified"] == 1
                ]
                if len(eligible_rows) > bounded:
                    _validation(
                        "SHADOW_COMMITMENT_PENDING_RESULT_LIMIT_EXCEEDED"
                    )
                connection.commit()
            finally:
                connection.close()
            prepared = self._verify_rows_cas(rows, store=exact_store)
            self._verify_head_anchor_catalog(rows)
            return tuple(
                self._make_result(
                    row,
                    item,
                    store=exact_store,
                    validation_writer_lease=self._writer_lease,
                )
                for row, item in zip(rows, prepared, strict=True)
                if row["ex_ante_durability_verified"] == 1
            )


_RESULT_STATUS_FIELDS: Final = {
    "pending_hypothesis_index_registered": True,
    "durable_ex_ante_commitment_verified": True,
    "portable_cost_source_closure_complete": True,
    "restart_reopen_verified": True,
    "outcome_maturation_authorized": False,
    "calibration_input_authorized": False,
    "trainer_admission_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}

_RESULT_PUBLIC_FIELDS: Final = (
    "hypothesis_identity_sha256",
    "hypothesis_artifact_sha256",
    "hypothesis_artifact_byte_count",
    "hypothesis_artifact_address",
    "cost_closure_address",
    "cost_evidence_artifact_sha256",
    "raw_inference_binding_sha256",
    "hypothesis_material_sha256",
    "symbol",
    "durable_snapshot_id",
    "decision_time",
    "hypothesis_generated_at",
    "label_earliest_available_at",
    "holding_horizon_seconds",
    "transaction_id",
    "append_receipt_sha256",
    "postcommit_readback_receipt_sha256",
    "commitment_sha256",
    "record_chain_sha256",
    "commit_observed_at",
    "commit_prepared_at",
    "postcommit_observed_at",
    "postcommit_readback_at",
)


def _result_public_material(
    value: DurablyCommittedProfiledResearchShadowHypothesisV1,
) -> dict[str, Any]:
    material = {name: getattr(value, name) for name in _RESULT_PUBLIC_FIELDS}
    artifact_address = material["hypothesis_artifact_address"]
    closure_address = material["cost_closure_address"]
    if (
        type(artifact_address) is not SourcePayloadAddress
        or type(closure_address) is not SourcePayloadAddress
    ):
        _integrity("SHADOW_COMMITMENT_RESULT_ADDRESS_INVALID")
    material["hypothesis_artifact_address"] = _address_mapping(artifact_address)
    material["cost_closure_address"] = _address_mapping(closure_address)
    return material


def _result_seal(
    *,
    public: Mapping[str, Any],
    artifact_json: str,
    ledger: ProfiledResearchShadowHypothesisCommitmentLedgerV1,
    store: ImmutableSourcePayloadStore,
) -> str:
    normalized = dict(public)
    artifact_address = normalized.get("hypothesis_artifact_address")
    closure_address = normalized.get("cost_closure_address")
    if (
        type(artifact_address) is not SourcePayloadAddress
        or type(closure_address) is not SourcePayloadAddress
    ):
        _integrity("SHADOW_COMMITMENT_RESULT_ADDRESS_INVALID")
    normalized["hypothesis_artifact_address"] = _address_mapping(artifact_address)
    normalized["cost_closure_address"] = _address_mapping(closure_address)
    try:
        artifact_bytes = artifact_json.encode("ascii", errors="strict")
    except (AttributeError, UnicodeError):
        _integrity("SHADOW_COMMITMENT_RESULT_ARTIFACT_JSON_INVALID")
    seal_material = {
        "domain": "v2/native-trainer/profiled-shadow-commit-result/v1",
        "public": normalized,
        "artifact_retained_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "artifact_retained_byte_count": len(artifact_bytes),
        "ledger_path": str(ledger.path),
        "store_root_path": str(store.root_path),
        "ledger_process_identity": id(ledger),
        "store_process_identity": id(store),
    }
    return hmac.new(
        _RESULT_SEAL_KEY,
        _canonical_bytes(
            seal_material,
            reason="SHADOW_COMMITMENT_RESULT_SEAL_INVALID",
        ),
        hashlib.sha256,
    ).hexdigest()


def _validated_committed_result(
    result: DurablyCommittedProfiledResearchShadowHypothesisV1,
) -> dict[str, Any]:
    if (
        type(result) is not DurablyCommittedProfiledResearchShadowHypothesisV1
        or result._construction_token is not _RESULT_TOKEN
        or type(result._ledger)
        is not ProfiledResearchShadowHypothesisCommitmentLedgerV1
        or type(result._store) is not ImmutableSourcePayloadStore
        or (
            result._validation_writer_lease is not None
            and type(result._validation_writer_lease)
            is not ProfiledResearchShadowHypothesisCommitmentWriterLease
        )
        or type(result._artifact_json) is not str
        or type(result._factory_seal) is not str
        or _SHA256_RE.fullmatch(result._factory_seal) is None
    ):
        _integrity("SHADOW_COMMITMENT_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
    public_values = {name: getattr(result, name) for name in _RESULT_PUBLIC_FIELDS}
    public = _result_public_material(result)
    expected_seal = _result_seal(
        public=public_values,
        artifact_json=result._artifact_json,
        ledger=result._ledger,
        store=result._store,
    )
    if not hmac.compare_digest(result._factory_seal, expected_seal):
        _integrity("SHADOW_COMMITMENT_RESULT_FACTORY_SEAL_INVALID")
    validation_writer = result._validation_writer_lease
    if validation_writer is not None:
        try:
            validation_writer.validate_for(result._ledger.path)
        except ProfiledResearchShadowHypothesisCommitmentWriterLeaseError as exc:
            if exc.reason != "SHADOW_COMMITMENT_WRITER_LEASE_NOT_HELD":
                raise
            validation_writer = None
    if validation_writer is None:
        reopened = result._ledger.open_committed_hypothesis(
            hypothesis_artifact_sha256=result.hypothesis_artifact_sha256,
            store=result._store,
        )
    else:
        reopened = (
            result._ledger._open_committed_hypothesis_under_stability_lease(  # noqa: SLF001
                hypothesis_artifact_sha256=result.hypothesis_artifact_sha256,
                store=result._store,
                validation_writer_lease=validation_writer,
            )
        )
        validation_writer.validate_for(result._ledger.path)
    if (
        _result_public_material(reopened) != public
        or reopened._artifact_json != result._artifact_json
    ):
        _integrity("SHADOW_COMMITMENT_RESULT_DURABLE_BINDING_INVALID")
    return _parse_exact_object(
        result._artifact_json,
        reason="SHADOW_COMMITMENT_RESULT_ARTIFACT_JSON_INVALID",
    )


__all__ = (
    "PROFILED_RESEARCH_SHADOW_COMMITMENT_APPEND_RECEIPT_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_SHADOW_COMMITMENT_LEDGER_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_SHADOW_COMMITMENT_POSTCOMMIT_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION",
    "PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION",
    "PROFILED_RESEARCH_SHADOW_PENDING_INDEX_V1_SCHEMA_VERSION",
    "DurablyCommittedProfiledResearchShadowHypothesisV1",
    "ProfiledResearchShadowHypothesisCommitmentIntegrityV1",
    "ProfiledResearchShadowHypothesisCommitmentLedgerV1",
    "ProfiledResearchShadowHypothesisCommitmentV1ConflictError",
    "ProfiledResearchShadowHypothesisCommitmentV1Error",
    "ProfiledResearchShadowHypothesisCommitmentV1IntegrityError",
    "ProfiledResearchShadowHypothesisCommitmentV1ValidationError",
    "ProfiledResearchShadowHypothesisCommitmentWriterLease",
    "ProfiledResearchShadowHypothesisCommitmentWriterLeaseError",
)
