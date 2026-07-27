"""Durable, immutable archive for canonical finalized Binance 5m candles.

This module is intentionally independent from the live market-data writers.
It provides one crash-safe SQLite append boundary and one bounded point-in-time
range-read boundary for trainer labels.  It never reads Redis, starts a
service, prunes data, or touches an exchange.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_candle_id,
)

ARCHIVE_SCHEMA_VERSION = "durable_canonical_finalized_5m_label_archive_v1"
APPEND_RECEIPT_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_append_receipt_v1"
)
POSTCOMMIT_READBACK_RECEIPT_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_postcommit_readback_v1"
)
RANGE_PROOF_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_range_proof_v1"
)
COVERAGE_PROOF_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_sparse_coverage_proof_v1"
)
EMPTY_INITIALIZATION_RECEIPT_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_empty_initialization_v1"
)
EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_exact_tail_transaction_v1"
)
EXACT_TRANSACTION_IDENTITY_ATTESTATION_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_exact_transaction_identity_v1"
)
ARCHIVE_WRITER_LEASE_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_label_archive_writer_lease_v2"
)
_ARCHIVE_WRITER_LEASE_CONSTRUCTION_TOKEN = object()
LABEL_PATH_PROOF_SCHEMA_VERSION = (
    "durable_canonical_finalized_5m_trainer_label_path_proof_v1"
)
LABEL_TIMEFRAME = "5m"
LABEL_SLOT_MILLISECONDS = 5 * 60 * 1000
RETENTION_POLICY = "NO_AUTOMATIC_PRUNING_OPERATOR_MANAGED"
DEFAULT_ARCHIVE_REL = Path(
    ".local_data/v2_native_trainer/canonical_finalized_5m_label_archive.sqlite3"
)
MAX_APPEND_ROWS = 4_096
MAX_CANONICAL_CANDLE_PAYLOAD_BYTES = 1024 * 1024
MAX_APPEND_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_QUERY_ROWS = 4_096
MAX_QUERY_PAYLOAD_BYTES = 64 * 1024 * 1024
ALLOWED_CANONICAL_SOURCES = frozenset(
    {
        "binance_wss",
        "binance_rest",
        "v2_closed_candle_resampler:1m",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$")
_INITIALIZATION_INTENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,199}$")
_CANONICAL_UTC_MILLISECOND_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_APPEND_RECEIPT_ORDER = "COMMIT_PREPARED_AT_ASC_STRICT_UNIQUE"
_GENESIS_CHAIN_SHA256 = hashlib.sha256(
    f"{ARCHIVE_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_CANONICAL_OHLCV_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)
_CANONICAL_BASE_PAYLOAD_FIELDS = frozenset(
    {
        "symbol",
        "exchange",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "event_time",
        "ingested_at",
        "available_at",
        "is_closed",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "ohlcv",
        "is_backfilled",
        "feature_eligible",
        "candle_id",
        "open_time",
        "close_time",
        "ts",
        "closed_candle",
        "candle_closed_confirmed",
    }
)


class Canonical5mArchiveError(ValueError):
    """Base fail-closed archive contract error."""


class Canonical5mValidationError(Canonical5mArchiveError):
    def __init__(self, reasons: Iterable[str]) -> None:
        self.reasons = tuple(sorted({str(reason) for reason in reasons}))
        super().__init__("canonical_5m_validation_failed:" + ",".join(self.reasons))


class Canonical5mIdentityConflictError(Canonical5mArchiveError):
    def __init__(self, identities: Iterable[str]) -> None:
        self.identities = tuple(sorted({str(value) for value in identities}))
        super().__init__(
            "canonical_5m_identity_conflict:" + ",".join(self.identities[:20])
        )


class Canonical5mArchiveReadbackError(Canonical5mArchiveError):
    pass


class Canonical5mArchiveWriterLeaseError(Canonical5mArchiveError):
    """The exact archive-path writer lease is absent, stale, or contended."""


def canonical_5m_archive_writer_lease_path(archive_path: Path) -> Path:
    """Return the one advisory writer-lock path for an exact archive path."""

    exact_archive_path = Path(archive_path).expanduser().resolve()
    return exact_archive_path.with_name(exact_archive_path.name + ".writer.lock")


class Canonical5mArchiveWriterLease:
    """One-shot, path-and-inode, nonblocking exclusive writer lease.

    A lease instance cannot be reacquired after release.  The private file
    descriptors remain open for the entire lease lifetime.  The sidecar lock
    serializes creation at the resolved archive path; as soon as the archive
    exists, a second lock on the archive inode serializes every hardlink alias
    of that database.  All sanctioned archive mutation APIs either acquire
    this lease themselves or validate a caller-provided instance before and
    after their critical section.
    """

    __slots__ = (
        "_archive_device",
        "_archive_file_descriptor",
        "_archive_inode",
        "_archive_path",
        "_file_descriptor",
        "_lock_device",
        "_lock_inode",
        "_lock_path",
        "_owner_pid",
        "_released",
    )

    def __init__(
        self,
        *,
        archive_path: Path,
        lock_path: Path,
        file_descriptor: int,
        lock_device: int,
        lock_inode: int,
        archive_file_descriptor: int = -1,
        archive_device: int = -1,
        archive_inode: int = -1,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _ARCHIVE_WRITER_LEASE_CONSTRUCTION_TOKEN:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_must_use_acquire"
            )
        self._archive_path = Path(archive_path)
        self._lock_path = Path(lock_path)
        self._file_descriptor = int(file_descriptor)
        self._lock_device = int(lock_device)
        self._lock_inode = int(lock_inode)
        self._archive_file_descriptor = int(archive_file_descriptor)
        self._archive_device = int(archive_device)
        self._archive_inode = int(archive_inode)
        self._owner_pid = os.getpid()
        self._released = False

    @classmethod
    def acquire(cls, archive_path: Path) -> Canonical5mArchiveWriterLease:
        exact_archive_path = Path(archive_path).expanduser().resolve()
        lock_path = canonical_5m_archive_writer_lease_path(exact_archive_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            file_descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_open_failed"
            ) from exc
        try:
            lock_stat = os.fstat(file_descriptor)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise Canonical5mArchiveWriterLeaseError(
                    "canonical_5m_archive_writer_lease_not_regular_file"
                )
            fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(file_descriptor)
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_already_held"
            ) from exc
        except Exception:
            os.close(file_descriptor)
            raise
        lease = cls(
            archive_path=exact_archive_path,
            lock_path=lock_path,
            file_descriptor=file_descriptor,
            lock_device=lock_stat.st_dev,
            lock_inode=lock_stat.st_ino,
            _construction_token=_ARCHIVE_WRITER_LEASE_CONSTRUCTION_TOKEN,
        )
        try:
            lease.validate_for(exact_archive_path)
        except BaseException:
            # Validation occurs after the nonblocking flock.  Never strand
            # that kernel lock if path/inode/PID validation itself fails.
            try:
                lease.release()
            except Canonical5mArchiveWriterLeaseError:
                pass
            raise
        return lease

    def _acquire_archive_inode_lock(self, *, create_if_missing: bool) -> None:
        if self._archive_file_descriptor >= 0:
            return
        flags = os.O_RDWR
        if create_if_missing:
            flags |= os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            archive_file_descriptor = os.open(
                self._archive_path,
                flags,
                0o600,
            )
        except FileNotFoundError:
            if not create_if_missing:
                return
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_archive_open_failed"
            ) from None
        except OSError as exc:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_archive_open_failed"
            ) from exc
        try:
            descriptor_stat = os.fstat(archive_file_descriptor)
            if not stat.S_ISREG(descriptor_stat.st_mode):
                raise Canonical5mArchiveWriterLeaseError(
                    "canonical_5m_archive_writer_lease_archive_not_regular_file"
                )
            fcntl.flock(
                archive_file_descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
            path_stat = os.stat(self._archive_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or (path_stat.st_dev, path_stat.st_ino)
                != (descriptor_stat.st_dev, descriptor_stat.st_ino)
            ):
                raise Canonical5mArchiveWriterLeaseError(
                    "canonical_5m_archive_writer_lease_archive_inode_changed"
                )
        except BlockingIOError as exc:
            os.close(archive_file_descriptor)
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_archive_inode_already_held"
            ) from exc
        except Exception:
            os.close(archive_file_descriptor)
            raise
        self._archive_file_descriptor = archive_file_descriptor
        self._archive_device = int(descriptor_stat.st_dev)
        self._archive_inode = int(descriptor_stat.st_ino)

    def bind_archive_inode_for_write(self, archive_path: Path) -> None:
        """Create if necessary and continuously lock the database inode."""

        self.validate_for(archive_path)
        if self._archive_file_descriptor < 0:
            self._acquire_archive_inode_lock(create_if_missing=True)
        self.validate_for(archive_path)

    @property
    def archive_path(self) -> Path:
        return self._archive_path

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def held(self) -> bool:
        if self._released or self._file_descriptor < 0:
            return False
        try:
            self.validate_for(self._archive_path)
        except Canonical5mArchiveWriterLeaseError:
            return False
        return True

    def validate_for(self, archive_path: Path) -> None:
        exact_archive_path = Path(archive_path).expanduser().resolve()
        if exact_archive_path != self._archive_path:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_path_mismatch"
            )
        if os.getpid() != self._owner_pid:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_owner_process_mismatch"
            )
        if self._released or self._file_descriptor < 0:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_not_held"
            )
        try:
            descriptor_stat = os.fstat(self._file_descriptor)
            path_stat = os.stat(self._lock_path, follow_symlinks=False)
        except OSError as exc:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_validation_failed"
            ) from exc
        identity = (self._lock_device, self._lock_inode)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino) != identity
            or (path_stat.st_dev, path_stat.st_ino) != identity
        ):
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_inode_changed"
            )
        if self._archive_file_descriptor < 0:
            self._acquire_archive_inode_lock(create_if_missing=False)
        if self._archive_file_descriptor >= 0:
            try:
                archive_descriptor_stat = os.fstat(
                    self._archive_file_descriptor
                )
                archive_path_stat = os.stat(
                    self._archive_path,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise Canonical5mArchiveWriterLeaseError(
                    "canonical_5m_archive_writer_lease_archive_validation_failed"
                ) from exc
            archive_identity = (self._archive_device, self._archive_inode)
            if (
                not stat.S_ISREG(archive_descriptor_stat.st_mode)
                or not stat.S_ISREG(archive_path_stat.st_mode)
                or (
                    archive_descriptor_stat.st_dev,
                    archive_descriptor_stat.st_ino,
                )
                != archive_identity
                or (archive_path_stat.st_dev, archive_path_stat.st_ino)
                != archive_identity
            ):
                raise Canonical5mArchiveWriterLeaseError(
                    "canonical_5m_archive_writer_lease_archive_inode_changed"
                )

    def contract(self) -> dict[str, Any]:
        self.validate_for(self._archive_path)
        return {
            "schema_version": ARCHIVE_WRITER_LEASE_SCHEMA_VERSION,
            "archive_path": str(self._archive_path),
            "lock_path": str(self._lock_path),
            "exclusive": True,
            "continuously_held": True,
            "exact_path_sidecar_lock_held": True,
            "archive_inode_lock_held": self._archive_file_descriptor >= 0,
            "hardlink_aliases_serialized_when_archive_exists": True,
            "process_probe_role": "SECONDARY_EVIDENCE_ONLY",
        }

    def release(self) -> None:
        if self._released:
            return
        archive_file_descriptor = self._archive_file_descriptor
        file_descriptor = self._file_descriptor
        self._released = True
        self._archive_file_descriptor = -1
        self._file_descriptor = -1
        release_error: OSError | None = None
        for descriptor in (archive_file_descriptor, file_descriptor):
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError as exc:
                if release_error is None:
                    release_error = exc
        if release_error is not None:
            raise Canonical5mArchiveWriterLeaseError(
                "canonical_5m_archive_writer_lease_release_failed"
            ) from release_error

    def __enter__(self) -> Canonical5mArchiveWriterLease:
        self.validate_for(self._archive_path)
        return self

    def __exit__(self, *_: Any) -> None:
        self.release()


@dataclass(frozen=True)
class Canonical5mAppendResult:
    transaction_id: str
    attempted_rows: int
    inserted_rows: int
    duplicate_rows: int
    total_unique_rows: int
    archive_chain_sha256: str
    batch_sha256: str
    append_receipt_sha256: str
    transaction_committed: bool
    transaction_readback_verified: bool
    retention_policy: str
    automatic_pruning_enabled: bool


def default_archive_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / DEFAULT_ARCHIVE_REL


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _canonical_utc_millisecond(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _CANONICAL_UTC_MILLISECOND_RE.fullmatch(
        value
    ):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    normalized = parsed.astimezone(UTC)
    canonical = normalized.isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )
    return normalized if canonical == value else None


def _format_utc_millisecond(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _strict_epoch_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1_000_000_000_000:
        return None
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _aware_epoch_us(value: datetime | str | int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        epoch_ms = _strict_epoch_ms(value)
        return epoch_ms * 1_000 if epoch_ms is not None else None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    normalized = value.astimezone(UTC)
    delta = normalized - datetime(1970, 1, 1, tzinfo=UTC)
    epoch_us = (
        (delta.days * 86_400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )
    return epoch_us if epoch_us >= 1_000_000_000_000_000 else None


def _aware_epoch_ms(
    value: datetime | str | int,
    *,
    ceiling: bool = False,
) -> int | None:
    epoch_us = _aware_epoch_us(value)
    if epoch_us is None:
        return None
    if ceiling:
        return (epoch_us + 999) // 1_000
    # Floor causal observation clocks so a time just before an integer-ms
    # availability boundary can never round forward into eligibility.
    return epoch_us // 1_000


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _valid_sha256(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if _SHA256_RE.fullmatch(normalized) else None


def validate_canonical_finalized_5m_candle(
    row: Mapping[str, Any],
    *,
    expected_symbol: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize one exact ``CanonicalCandle.to_dict`` payload."""

    reasons: list[str] = []
    payload = dict(row)
    symbol_raw = payload.get("symbol")
    symbol = symbol_raw.strip() if isinstance(symbol_raw, str) else ""
    normalized_expected = (
        str(expected_symbol).strip().upper() if expected_symbol is not None else None
    )
    if (
        not _SYMBOL_RE.fullmatch(symbol)
        or symbol != symbol.upper()
        or symbol_raw != symbol
    ):
        reasons.append("LABEL_CANDLE_SYMBOL_NOT_CANONICAL_UPPERCASE")
    if normalized_expected is not None and symbol != normalized_expected:
        reasons.append("LABEL_CANDLE_SYMBOL_MISMATCH")
    if payload.get("exchange") != "binance":
        reasons.append("LABEL_CANDLE_EXCHANGE_MISMATCH")
    if payload.get("timeframe") != LABEL_TIMEFRAME:
        reasons.append("LABEL_CANDLE_NOT_CANONICAL_5M")
    if payload.get("is_closed") is not True:
        reasons.append("LABEL_CANDLE_NOT_FINAL")
    if payload.get("closed_candle") is not True:
        reasons.append("LABEL_CANDLE_CLOSED_FLAG_MISSING")
    if payload.get("candle_closed_confirmed") is not True:
        reasons.append("LABEL_CANDLE_FINALITY_CONFIRMATION_MISSING")
    if payload.get("feature_eligible") is not True:
        reasons.append("LABEL_CANDLE_FEATURE_ELIGIBILITY_UNPROVEN")
    is_backfilled = payload.get("is_backfilled")
    if not isinstance(is_backfilled, bool):
        reasons.append("LABEL_CANDLE_BACKFILL_STATE_MISSING")
    source = payload.get("source")
    if source not in ALLOWED_CANONICAL_SOURCES:
        reasons.append("LABEL_CANDLE_SOURCE_NOT_CANONICAL")
    elif source == "binance_wss" and is_backfilled is not False:
        reasons.append("LABEL_CANDLE_WSS_BACKFILL_STATE_INVALID")
    elif source == "binance_rest" and is_backfilled is not True:
        reasons.append("LABEL_CANDLE_REST_BACKFILL_STATE_INVALID")
    elif (
        source == "v2_closed_candle_resampler:1m"
        and is_backfilled is not False
    ):
        reasons.append("LABEL_CANDLE_RESAMPLER_BACKFILL_STATE_INVALID")
    source_sequence_id = payload.get("source_sequence_id")
    if not isinstance(source_sequence_id, str) or not source_sequence_id.strip():
        reasons.append("LABEL_CANDLE_SOURCE_SEQUENCE_ID_MISSING")
    elif source_sequence_id != source_sequence_id.strip():
        reasons.append("LABEL_CANDLE_SOURCE_SEQUENCE_ID_NOT_CANONICAL")
    allowed_fields = set(_CANONICAL_BASE_PAYLOAD_FIELDS)
    allowed_fields.update(_CANONICAL_OHLCV_FIELDS)
    if payload.get("source") == "v2_closed_candle_resampler:1m":
        allowed_fields.update(
            {"resampled_from_timeframe", "resampled_source_candle_count"}
        )
        if payload.get("resampled_from_timeframe") != "1m":
            reasons.append("LABEL_CANDLE_RESAMPLER_SOURCE_TIMEFRAME_INVALID")
        resampled_count = payload.get("resampled_source_candle_count")
        if (
            isinstance(resampled_count, bool)
            or not isinstance(resampled_count, int)
            or resampled_count != 5
        ):
            reasons.append("LABEL_CANDLE_RESAMPLER_SOURCE_COUNT_INVALID")
    unknown_fields = [
        field
        for field in payload
        if not isinstance(field, str) or field not in allowed_fields
    ]
    if unknown_fields:
        reasons.append("LABEL_CANDLE_UNKNOWN_TOP_LEVEL_FIELDS")

    open_ms = _strict_epoch_ms(payload.get("candle_open_time"))
    close_ms = _strict_epoch_ms(payload.get("candle_close_time"))
    event_ms = _strict_epoch_ms(payload.get("event_time"))
    ingested_ms = _strict_epoch_ms(payload.get("ingested_at"))
    available_ms = _strict_epoch_ms(payload.get("available_at"))
    for value, reason in (
        (open_ms, "LABEL_CANDLE_OPEN_TIME_MISSING_OR_INVALID"),
        (close_ms, "LABEL_CANDLE_CLOSE_TIME_MISSING_OR_INVALID"),
        (event_ms, "LABEL_CANDLE_EVENT_TIME_MISSING_OR_INVALID"),
        (ingested_ms, "LABEL_CANDLE_INGESTED_AT_MISSING_OR_INVALID"),
        (available_ms, "LABEL_CANDLE_AVAILABLE_AT_MISSING_OR_INVALID"),
    ):
        if value is None:
            reasons.append(reason)
    if open_ms is not None:
        if open_ms % LABEL_SLOT_MILLISECONDS != 0:
            reasons.append("LABEL_CANDLE_5M_OPEN_NOT_SLOT_ALIGNED")
        if payload.get("open_time") != open_ms or payload.get("ts") != open_ms:
            reasons.append("LABEL_CANDLE_OPEN_TIME_CANONICAL_COPY_MISMATCH")
    if close_ms is not None:
        if payload.get("close_time") != close_ms:
            reasons.append("LABEL_CANDLE_CLOSE_TIME_CANONICAL_COPY_MISMATCH")
    if open_ms is not None and close_ms is not None:
        if close_ms - open_ms != LABEL_SLOT_MILLISECONDS - 1:
            reasons.append("LABEL_CANDLE_5M_SLOT_BOUNDS_INVALID")
    if close_ms is not None and event_ms is not None and event_ms < close_ms:
        reasons.append("LABEL_CANDLE_EVENT_BEFORE_CLOSE")
    if close_ms is not None and ingested_ms is not None and ingested_ms < close_ms:
        reasons.append("LABEL_CANDLE_INGESTED_BEFORE_CLOSE")
    if (
        close_ms is not None
        and event_ms is not None
        and ingested_ms is not None
        and available_ms is not None
        and available_ms != max(close_ms, event_ms, ingested_ms)
    ):
        reasons.append("LABEL_CANDLE_AVAILABLE_AT_NOT_CANONICAL_MAX_CLOCK")
    if source == "binance_rest" and close_ms is not None:
        if event_ms != close_ms:
            reasons.append("LABEL_CANDLE_REST_EVENT_TIME_NOT_CLOSE_TIME")
        if source_sequence_id != str(close_ms):
            reasons.append("LABEL_CANDLE_REST_SOURCE_SEQUENCE_ID_INVALID")

    nested = payload.get("ohlcv")
    if not isinstance(nested, Mapping):
        reasons.append("LABEL_CANDLE_CANONICAL_OHLCV_MISSING")
        nested = {}
    for field in _CANONICAL_OHLCV_FIELDS - {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }:
        if (field in payload) != (field in nested):
            reasons.append("LABEL_CANDLE_OHLCV_CANONICAL_COPY_MISMATCH")
    normalized_ohlcv: dict[str, float | int] = {}
    for field in ("open", "high", "low", "close", "volume"):
        top_value = _finite_number(payload.get(field))
        nested_value = _finite_number(nested.get(field))
        if top_value is None:
            reasons.append(f"LABEL_CANDLE_{field.upper()}_MISSING_OR_INVALID")
            continue
        if field == "volume":
            if top_value < 0.0:
                reasons.append("LABEL_CANDLE_VOLUME_NEGATIVE")
                continue
        elif top_value <= 0.0:
            reasons.append(f"LABEL_CANDLE_{field.upper()}_MISSING_OR_INVALID")
            continue
        if nested_value is None or nested_value != top_value:
            reasons.append(
                f"LABEL_CANDLE_{field.upper()}_CANONICAL_COPY_MISMATCH"
            )
            continue
        normalized_ohlcv[field] = top_value
    for field, raw_value in nested.items():
        field_name = str(field)
        if field_name not in _CANONICAL_OHLCV_FIELDS:
            reasons.append("LABEL_CANDLE_UNKNOWN_OHLCV_FIELD")
            continue
        parsed = _finite_number(raw_value)
        if parsed is None:
            reasons.append("LABEL_CANDLE_OHLCV_NONFINITE_VALUE")
            continue
        if (
            payload.get(field_name) != raw_value
            or type(payload.get(field_name)) is not type(raw_value)
        ):
            reasons.append("LABEL_CANDLE_OHLCV_CANONICAL_COPY_MISMATCH")
        normalized_ohlcv.setdefault(field_name, parsed)
        if field_name == "num_trades" and (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, int)
            or raw_value < 0
        ):
            reasons.append("LABEL_CANDLE_NUM_TRADES_INVALID")
        if field_name in {
            "quote_volume",
            "taker_buy_base_vol",
            "taker_buy_quote_vol",
        } and parsed < 0.0:
            reasons.append(
                f"LABEL_CANDLE_{field_name.upper()}_NEGATIVE"
            )
    if all(field in normalized_ohlcv for field in ("open", "high", "low", "close")):
        open_price = float(normalized_ohlcv["open"])
        high_price = float(normalized_ohlcv["high"])
        low_price = float(normalized_ohlcv["low"])
        close_price = float(normalized_ohlcv["close"])
        if high_price < max(open_price, close_price):
            reasons.append("LABEL_CANDLE_HIGH_BELOW_OPEN_OR_CLOSE")
        if low_price > min(open_price, close_price):
            reasons.append("LABEL_CANDLE_LOW_ABOVE_OPEN_OR_CLOSE")
        if high_price < low_price:
            reasons.append("LABEL_CANDLE_HIGH_BELOW_LOW")

    raw_payload_hash = _valid_sha256(payload.get("raw_payload_hash"))
    if raw_payload_hash is None:
        reasons.append("LABEL_CANDLE_RAW_PAYLOAD_HASH_MISSING_OR_INVALID")
    elif payload.get("raw_payload_hash") != raw_payload_hash:
        reasons.append("LABEL_CANDLE_RAW_PAYLOAD_HASH_NOT_LOWERCASE")
    candle_id_raw = payload.get("candle_id")
    candle_id = (
        candle_id_raw.strip() if isinstance(candle_id_raw, str) else ""
    )
    if not candle_id:
        reasons.append("LABEL_CANDLE_ID_MISSING")
    elif candle_id_raw != candle_id:
        reasons.append("LABEL_CANDLE_ID_NOT_CANONICAL")
    elif candle_id != canonical_candle_id(payload):
        reasons.append("LABEL_CANDLE_ID_MISMATCH")
    try:
        payload_json = canonical_json(payload)
    except (TypeError, ValueError):
        payload_json = ""
        reasons.append("LABEL_CANDLE_PAYLOAD_NOT_STRICT_JSON")
    if reasons:
        raise Canonical5mValidationError(reasons)
    assert open_ms is not None
    assert close_ms is not None
    assert event_ms is not None
    assert ingested_ms is not None
    assert available_ms is not None
    assert raw_payload_hash is not None
    return {
        "payload": payload,
        "payload_json": payload_json,
        "content_sha256": hashlib.sha256(payload_json.encode()).hexdigest(),
        "market_fact_sha256": stable_sha256(
            {
                "exchange": "binance",
                "symbol": symbol,
                "timeframe": LABEL_TIMEFRAME,
                "candle_open_time_ms": open_ms,
                "candle_close_time_ms": close_ms,
                "ohlcv": normalized_ohlcv,
            }
        ),
        "symbol": symbol,
        "candle_id": candle_id,
        "open_time_ms": open_ms,
        "close_time_ms": close_ms,
        "event_time_ms": event_ms,
        "ingested_at_ms": ingested_ms,
        "available_at_ms": available_ms,
        "raw_payload_hash": raw_payload_hash,
    }


class DurableCanonical5mLabelArchive:
    """Crash-safe immutable archive and bounded trainer range reader."""

    def __init__(
        self,
        path: Path,
        *,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> None:
        self.path = Path(path)
        self._writer_lease = writer_lease
        if writer_lease is not None:
            writer_lease.validate_for(self.path)

    @contextmanager
    def writer_lease(
        self,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> Iterator[Canonical5mArchiveWriterLease]:
        """Yield a validated lease, acquiring one when the caller has none."""

        held_lease = writer_lease or self._writer_lease
        acquired_here = held_lease is None
        if held_lease is None:
            held_lease = Canonical5mArchiveWriterLease.acquire(self.path)
        try:
            held_lease.validate_for(self.path)
            yield held_lease
            held_lease.validate_for(self.path)
        finally:
            if acquired_here:
                held_lease.release()

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")

    def _connect_write(
        self,
        *,
        writer_lease: Canonical5mArchiveWriterLease,
        initialize: bool = False,
    ) -> sqlite3.Connection:
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            writer_lease.bind_archive_inode_for_write(self.path)
        elif not self.path.is_file():
            raise Canonical5mArchiveError(
                "durable_canonical_5m_label_archive_missing"
            )
        writer_lease.validate_for(self.path)
        connection = sqlite3.connect(str(self.path), timeout=60.0)
        self._configure_connection(connection)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        if not initialize:
            return connection
        connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS canonical_5m_candles (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                candle_close_time_ms INTEGER NOT NULL,
                candle_open_time_ms INTEGER NOT NULL,
                available_at_ms INTEGER NOT NULL,
                candle_id TEXT NOT NULL UNIQUE,
                raw_payload_hash TEXT NOT NULL,
                market_fact_sha256 TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_chain_sha256 TEXT NOT NULL,
                record_chain_sha256 TEXT NOT NULL,
                append_transaction_id TEXT NOT NULL,
                archived_at TEXT NOT NULL,
                UNIQUE(symbol, candle_close_time_ms)
            );
            CREATE INDEX IF NOT EXISTS canonical_5m_symbol_close_time
                ON canonical_5m_candles(symbol, candle_close_time_ms);
            CREATE INDEX IF NOT EXISTS canonical_5m_available_at
                ON canonical_5m_candles(symbol, available_at_ms);
            CREATE INDEX IF NOT EXISTS canonical_5m_append_transaction
                ON canonical_5m_candles(append_transaction_id);
            CREATE TABLE IF NOT EXISTS canonical_5m_append_receipts (
                transaction_id TEXT PRIMARY KEY,
                receipt_schema_version TEXT NOT NULL,
                batch_sha256 TEXT NOT NULL,
                attempted_rows INTEGER NOT NULL,
                inserted_rows INTEGER NOT NULL,
                duplicate_rows INTEGER NOT NULL,
                total_unique_rows INTEGER NOT NULL,
                archive_chain_sha256 TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                commit_prepared_at TEXT NOT NULL,
                precommit_readback_verified INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS canonical_5m_postcommit_readback_receipts (
                transaction_id TEXT PRIMARY KEY,
                readback_schema_version TEXT NOT NULL,
                append_receipt_sha256 TEXT NOT NULL,
                inserted_rows INTEGER NOT NULL,
                inserted_identities_sha256 TEXT NOT NULL,
                readback_receipt_sha256 TEXT NOT NULL,
                readback_receipt_json TEXT NOT NULL,
                postcommit_readback_at TEXT NOT NULL,
                FOREIGN KEY(transaction_id)
                    REFERENCES canonical_5m_append_receipts(transaction_id)
            );
            CREATE TABLE IF NOT EXISTS canonical_5m_archive_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS canonical_5m_candles_no_update
            BEFORE UPDATE ON canonical_5m_candles
            BEGIN
                SELECT RAISE(ABORT, 'canonical_5m_candles_are_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_candles_no_delete
            BEFORE DELETE ON canonical_5m_candles
            BEGIN
                SELECT RAISE(ABORT, 'canonical_5m_candles_are_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_receipts_no_update
            BEFORE UPDATE ON canonical_5m_append_receipts
            BEGIN
                SELECT RAISE(ABORT, 'canonical_5m_receipts_are_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_receipts_no_delete
            BEFORE DELETE ON canonical_5m_append_receipts
            BEGIN
                SELECT RAISE(ABORT, 'canonical_5m_receipts_are_immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_postcommit_receipts_no_update
            BEFORE UPDATE ON canonical_5m_postcommit_readback_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'canonical_5m_postcommit_receipts_are_immutable'
                );
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_postcommit_receipts_no_delete
            BEFORE DELETE ON canonical_5m_postcommit_readback_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'canonical_5m_postcommit_receipts_are_immutable'
                );
            END;
            CREATE TRIGGER IF NOT EXISTS canonical_5m_payload_bytes_bounded
            BEFORE INSERT ON canonical_5m_candles
            WHEN length(CAST(NEW.payload_json AS BLOB)) >
                 {MAX_CANONICAL_CANDLE_PAYLOAD_BYTES}
            BEGIN
                SELECT RAISE(ABORT, 'canonical_5m_payload_bytes_exceeded');
            END;
            """
        )
        now = utc_now()
        for key, value in (
            ("archive_schema_version", ARCHIVE_SCHEMA_VERSION),
            ("retention_policy", RETENTION_POLICY),
            ("automatic_pruning_enabled", "false"),
            ("total_unique_rows", "0"),
            ("archive_chain_sha256", _GENESIS_CHAIN_SHA256),
        ):
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_5m_archive_metadata(
                    metadata_key, metadata_value, updated_at
                ) VALUES (?, ?, ?)
                """,
                (key, value, now),
            )
        connection.commit()
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise Canonical5mArchiveError(
                "durable_canonical_5m_label_archive_missing"
            )
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=60.0)
        self._configure_connection(connection)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _ensure_initialized(
        self,
        *,
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> None:
        connection = self._connect_write(
            initialize=True,
            writer_lease=writer_lease,
        )
        connection.close()

    def initialize_empty_archive(
        self,
        *,
        initialization_intent_id: str,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> dict[str, Any]:
        with self.writer_lease(writer_lease) as held_lease:
            return self._initialize_empty_archive_locked(
                initialization_intent_id=initialization_intent_id,
                writer_lease=held_lease,
            )

    def _initialize_empty_archive_locked(
        self,
        *,
        initialization_intent_id: str,
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> dict[str, Any]:
        """Create or read one deterministic, fully verified empty genesis.

        The receipt deliberately excludes wall-clock creation time, so a crash
        after SQLite initialization but before caller acknowledgement can be
        retried with the same intent and produce the exact same receipt hash.
        Any candle or append receipt makes the archive non-empty and blocks
        this boundary instead of being silently treated as initialization.
        """

        intent = str(initialization_intent_id or "")
        if (
            intent != initialization_intent_id
            or not _INITIALIZATION_INTENT_RE.fullmatch(intent)
        ):
            raise Canonical5mArchiveError(
                "empty_archive_initialization_intent_id_invalid"
            )
        archive_preexisted = self.path.is_file()
        self._ensure_initialized(writer_lease=writer_lease)
        integrity = self.verify_integrity()
        if (
            integrity.get("archive_integrity_verified") is not True
            or integrity.get("verified_rows") != 0
            or integrity.get("verified_max_sequence") != 0
            or integrity.get("verified_append_receipts") != 0
            or integrity.get("verified_postcommit_readback_receipts") != 0
            or integrity.get("archive_chain_sha256") != _GENESIS_CHAIN_SHA256
        ):
            raise Canonical5mArchiveReadbackError(
                "empty_archive_initialization_not_pristine_genesis"
            )
        receipt_material = {
            "schema_version": EMPTY_INITIALIZATION_RECEIPT_SCHEMA_VERSION,
            "initialization_intent_id": intent,
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "archive_chain_sha256": _GENESIS_CHAIN_SHA256,
            "verified_rows": 0,
            "verified_max_sequence": 0,
            "verified_append_receipts": 0,
            "verified_postcommit_readback_receipts": 0,
            "retention_policy": RETENTION_POLICY,
            "automatic_pruning_enabled": False,
            "empty_genesis_integrity_verified": True,
        }
        receipt_json = canonical_json(receipt_material)
        return {
            **receipt_material,
            "status": (
                "VERIFIED_EXISTING_EMPTY_CANONICAL_5M_ARCHIVE"
                if archive_preexisted
                else "CREATED_AND_VERIFIED_EMPTY_CANONICAL_5M_ARCHIVE"
            ),
            "initialization_receipt_json": receipt_json,
            "initialization_receipt_sha256": hashlib.sha256(
                receipt_json.encode()
            ).hexdigest(),
            "archive_integrity_proof": integrity,
        }

    @staticmethod
    def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
        return {
            str(row["metadata_key"]): str(row["metadata_value"])
            for row in connection.execute(
                "SELECT metadata_key, metadata_value "
                "FROM canonical_5m_archive_metadata"
            )
        }

    def _integrity_proof_rejection_reasons(
        self,
        connection: sqlite3.Connection,
        proof: Mapping[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        metadata = self._metadata(connection)
        if proof.get("archive_integrity_verified") is not True:
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_NOT_VERIFIED")
        if proof.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_SCHEMA_MISMATCH")
        if str(proof.get("archive_path") or "") != str(self.path):
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_PATH_MISMATCH")
        if proof.get("retention_policy") != RETENTION_POLICY:
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_RETENTION_MISMATCH")
        if proof.get("automatic_pruning_enabled") is not False:
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_PRUNING_MISMATCH")
        if (
            proof.get("append_receipt_ordering_verified") is not True
            or proof.get("append_receipt_order") != _APPEND_RECEIPT_ORDER
        ):
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_RECEIPT_ORDERING_UNVERIFIED"
            )
        if proof.get("append_receipt_cumulative_state_verified") is not True:
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_RECEIPT_STATE_UNVERIFIED"
            )
        if proof.get("postcommit_clock_causality_verified") is not True:
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_POSTCOMMIT_CLOCK_UNVERIFIED"
            )
        verified_rows = proof.get("verified_rows")
        if (
            isinstance(verified_rows, bool)
            or not isinstance(verified_rows, int)
            or str(verified_rows) != metadata.get("total_unique_rows")
        ):
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_ROW_COUNT_STALE")
        if (
            str(proof.get("archive_chain_sha256") or "")
            != metadata.get("archive_chain_sha256")
        ):
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_CHAIN_STALE")
        append_receipt_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM canonical_5m_append_receipts"
            ).fetchone()[0]
        )
        postcommit_receipt_count = int(
            connection.execute(
                "SELECT COUNT(*) "
                "FROM canonical_5m_postcommit_readback_receipts"
            ).fetchone()[0]
        )
        latest_append_clock = connection.execute(
            """
            SELECT commit_prepared_at
            FROM canonical_5m_append_receipts
            ORDER BY commit_prepared_at DESC
            LIMIT 1
            """
        ).fetchone()
        expected_last_append_clock = (
            str(latest_append_clock["commit_prepared_at"])
            if latest_append_clock is not None
            else None
        )
        if proof.get("verified_last_commit_prepared_at") != (
            expected_last_append_clock
        ):
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_LAST_APPEND_CLOCK_STALE"
            )
        latest_postcommit_clock = connection.execute(
            """
            SELECT postcommit_readback_at
            FROM canonical_5m_postcommit_readback_receipts
            ORDER BY postcommit_readback_at DESC
            LIMIT 1
            """
        ).fetchone()
        expected_last_postcommit_clock = (
            str(latest_postcommit_clock["postcommit_readback_at"])
            if latest_postcommit_clock is not None
            else None
        )
        if proof.get("verified_last_postcommit_readback_at") != (
            expected_last_postcommit_clock
        ):
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_LAST_POSTCOMMIT_CLOCK_STALE"
            )
        proof_append_receipts = proof.get("verified_append_receipts")
        if (
            isinstance(proof_append_receipts, bool)
            or not isinstance(proof_append_receipts, int)
            or proof_append_receipts != append_receipt_count
        ):
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_APPEND_RECEIPT_COUNT_STALE"
            )
        proof_postcommit_receipts = proof.get(
            "verified_postcommit_readback_receipts"
        )
        if (
            isinstance(proof_postcommit_receipts, bool)
            or not isinstance(proof_postcommit_receipts, int)
            or proof_postcommit_receipts != postcommit_receipt_count
        ):
            reasons.append(
                "LABEL_ARCHIVE_INTEGRITY_PROOF_POSTCOMMIT_RECEIPT_COUNT_STALE"
            )
        if append_receipt_count != postcommit_receipt_count:
            reasons.append(
                "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_COUNT_MISMATCH"
            )
        if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
            reasons.append("LABEL_ARCHIVE_SCHEMA_VERSION_MISMATCH")
        if metadata.get("retention_policy") != RETENTION_POLICY:
            reasons.append("LABEL_ARCHIVE_RETENTION_POLICY_MISMATCH")
        if metadata.get("automatic_pruning_enabled") != "false":
            reasons.append("LABEL_ARCHIVE_AUTOMATIC_PRUNING_ENABLED")
        required_schema_objects = {
            "canonical_5m_symbol_close_time": "index",
            "canonical_5m_append_transaction": "index",
            "canonical_5m_candles_no_update": "trigger",
            "canonical_5m_candles_no_delete": "trigger",
            "canonical_5m_receipts_no_update": "trigger",
            "canonical_5m_receipts_no_delete": "trigger",
            "canonical_5m_postcommit_receipts_no_update": "trigger",
            "canonical_5m_postcommit_receipts_no_delete": "trigger",
            "canonical_5m_payload_bytes_bounded": "trigger",
        }
        schema_objects = {
            str(row["name"]): str(row["type"])
            for row in connection.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(required_schema_objects),
            )
        }
        if schema_objects != required_schema_objects:
            reasons.append("LABEL_ARCHIVE_IMMUTABILITY_OR_INDEX_SCHEMA_MISSING")
        latest = connection.execute(
            """
            SELECT sequence, record_chain_sha256
            FROM canonical_5m_candles
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
        latest_chain = (
            str(latest["record_chain_sha256"])
            if latest is not None
            else _GENESIS_CHAIN_SHA256
        )
        if latest_chain != metadata.get("archive_chain_sha256"):
            reasons.append("LABEL_ARCHIVE_CHAIN_METADATA_MISMATCH")
        expected_max_sequence = int(latest["sequence"]) if latest is not None else 0
        proof_max_sequence = proof.get("verified_max_sequence")
        if (
            isinstance(proof_max_sequence, bool)
            or not isinstance(proof_max_sequence, int)
            or proof_max_sequence != expected_max_sequence
        ):
            reasons.append("LABEL_ARCHIVE_INTEGRITY_PROOF_SEQUENCE_STALE")
        return sorted(set(reasons))

    def integrity_proof_is_current(self, proof: Mapping[str, Any]) -> bool:
        """Cheaply bind a prior full proof to the archive's current state."""

        if not self.path.is_file() or not isinstance(proof, Mapping):
            return False
        try:
            connection = self._connect_readonly()
        except (OSError, sqlite3.Error, Canonical5mArchiveError):
            return False
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            reasons = self._integrity_proof_rejection_reasons(
                connection,
                proof,
            )
            connection.commit()
            return not reasons
        except sqlite3.Error:
            return False
        finally:
            connection.close()

    def _integrity_prefix_proof_rejection_reasons(
        self,
        connection: sqlite3.Connection,
        proof: Mapping[str, Any],
    ) -> list[str]:
        """Validate a prior full proof as an immutable archive prefix.

        A sanctioned append makes ``integrity_proof_is_current`` false even
        though every row covered by the prior proof remains immutable.  This
        narrower check binds the old terminal row, append receipt, postcommit
        receipt, schema guards, and cumulative counts inside the caller's
        read transaction.  It never authorizes rows beyond the old verified
        sequence; ``verified_range`` enforces that boundary explicitly.
        """

        reasons: list[str] = []
        if proof.get("archive_integrity_verified") is not True:
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_NOT_VERIFIED")
        if proof.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_SCHEMA_MISMATCH")
        if str(proof.get("archive_path") or "") != str(self.path):
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_PATH_MISMATCH")
        if proof.get("retention_policy") != RETENTION_POLICY:
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_RETENTION_MISMATCH")
        if proof.get("automatic_pruning_enabled") is not False:
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_PRUNING_MISMATCH")
        if (
            proof.get("append_receipt_ordering_verified") is not True
            or proof.get("append_receipt_order") != _APPEND_RECEIPT_ORDER
            or proof.get("append_receipt_cumulative_state_verified") is not True
            or proof.get("postcommit_clock_causality_verified") is not True
        ):
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_RECEIPTS_UNVERIFIED")

        verified_rows = proof.get("verified_rows")
        verified_sequence = proof.get("verified_max_sequence")
        verified_receipts = proof.get("verified_append_receipts")
        verified_postcommit = proof.get("verified_postcommit_readback_receipts")
        if (
            isinstance(verified_rows, bool)
            or not isinstance(verified_rows, int)
            or verified_rows < 0
            or isinstance(verified_sequence, bool)
            or not isinstance(verified_sequence, int)
            or verified_sequence != verified_rows
            or isinstance(verified_receipts, bool)
            or not isinstance(verified_receipts, int)
            or verified_receipts < 0
            or isinstance(verified_postcommit, bool)
            or not isinstance(verified_postcommit, int)
            or verified_postcommit != verified_receipts
        ):
            reasons.append("LABEL_ARCHIVE_PREFIX_PROOF_FRONTIER_INVALID")
            return sorted(set(reasons))

        required_schema_objects = {
            "canonical_5m_symbol_close_time": "index",
            "canonical_5m_append_transaction": "index",
            "canonical_5m_candles_no_update": "trigger",
            "canonical_5m_candles_no_delete": "trigger",
            "canonical_5m_receipts_no_update": "trigger",
            "canonical_5m_receipts_no_delete": "trigger",
            "canonical_5m_postcommit_receipts_no_update": "trigger",
            "canonical_5m_postcommit_receipts_no_delete": "trigger",
            "canonical_5m_payload_bytes_bounded": "trigger",
        }
        schema_objects = {
            str(row["name"]): str(row["type"])
            for row in connection.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(required_schema_objects),
            )
        }
        if schema_objects != required_schema_objects:
            reasons.append("LABEL_ARCHIVE_IMMUTABILITY_OR_INDEX_SCHEMA_MISSING")

        metadata = self._metadata(connection)
        try:
            current_rows = int(metadata.get("total_unique_rows") or "")
        except ValueError:
            current_rows = -1
        if current_rows < verified_rows:
            reasons.append("LABEL_ARCHIVE_PREFIX_ROW_COUNT_REGRESSED")
        if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
            reasons.append("LABEL_ARCHIVE_SCHEMA_VERSION_MISMATCH")
        if metadata.get("retention_policy") != RETENTION_POLICY:
            reasons.append("LABEL_ARCHIVE_RETENTION_POLICY_MISMATCH")
        if metadata.get("automatic_pruning_enabled") != "false":
            reasons.append("LABEL_ARCHIVE_AUTOMATIC_PRUNING_ENABLED")

        expected_chain = str(proof.get("archive_chain_sha256") or "")
        if verified_rows == 0:
            if expected_chain != _GENESIS_CHAIN_SHA256:
                reasons.append("LABEL_ARCHIVE_PREFIX_GENESIS_CHAIN_MISMATCH")
        else:
            anchor = connection.execute(
                """
                SELECT sequence, record_chain_sha256
                FROM canonical_5m_candles
                WHERE sequence = ?
                """,
                (verified_sequence,),
            ).fetchone()
            if (
                anchor is None
                or int(anchor["sequence"]) != verified_sequence
                or str(anchor["record_chain_sha256"]) != expected_chain
            ):
                reasons.append("LABEL_ARCHIVE_PREFIX_TERMINAL_ROW_MISMATCH")

        last_append_at = proof.get("verified_last_commit_prepared_at")
        last_postcommit_at = proof.get("verified_last_postcommit_readback_at")
        if verified_receipts == 0:
            if last_append_at is not None or last_postcommit_at is not None:
                reasons.append("LABEL_ARCHIVE_PREFIX_EMPTY_RECEIPT_CLOCK_INVALID")
        elif type(last_append_at) is not str or type(last_postcommit_at) is not str:
            reasons.append("LABEL_ARCHIVE_PREFIX_RECEIPT_CLOCK_MISSING")
        else:
            prefix_receipt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_append_receipts "
                    "WHERE commit_prepared_at <= ?",
                    (last_append_at,),
                ).fetchone()[0]
            )
            prefix_postcommit_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_postcommit_readback_receipts "
                    "WHERE postcommit_readback_at <= ?",
                    (last_postcommit_at,),
                ).fetchone()[0]
            )
            if prefix_receipt_count != verified_receipts:
                reasons.append("LABEL_ARCHIVE_PREFIX_APPEND_RECEIPT_COUNT_MISMATCH")
            if prefix_postcommit_count != verified_postcommit:
                reasons.append("LABEL_ARCHIVE_PREFIX_POSTCOMMIT_RECEIPT_COUNT_MISMATCH")
            anchor_receipt = connection.execute(
                """
                SELECT transaction_id, receipt_schema_version, batch_sha256,
                       attempted_rows, inserted_rows, duplicate_rows,
                       total_unique_rows, archive_chain_sha256, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM canonical_5m_append_receipts
                WHERE commit_prepared_at = ?
                """,
                (last_append_at,),
            ).fetchone()
            if anchor_receipt is None:
                reasons.append("LABEL_ARCHIVE_PREFIX_APPEND_RECEIPT_MISSING")
            else:
                reasons.extend(self._append_receipt_rejection_reasons(anchor_receipt))
                if (
                    int(anchor_receipt["total_unique_rows"]) != verified_rows
                    or str(anchor_receipt["archive_chain_sha256"]) != expected_chain
                ):
                    reasons.append("LABEL_ARCHIVE_PREFIX_APPEND_RECEIPT_STATE_MISMATCH")
                anchor_postcommit = connection.execute(
                    """
                    SELECT transaction_id, readback_schema_version,
                           append_receipt_sha256, inserted_rows,
                           inserted_identities_sha256,
                           readback_receipt_sha256, readback_receipt_json,
                           postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    WHERE transaction_id = ?
                    """,
                    (str(anchor_receipt["transaction_id"]),),
                ).fetchone()
                if anchor_postcommit is None:
                    reasons.append("LABEL_ARCHIVE_PREFIX_POSTCOMMIT_RECEIPT_MISSING")
                else:
                    reasons.extend(
                        self._postcommit_receipt_rejection_reasons(anchor_postcommit)
                    )
                    if (
                        str(anchor_postcommit["postcommit_readback_at"])
                        != last_postcommit_at
                        or str(anchor_postcommit["append_receipt_sha256"])
                        != str(anchor_receipt["receipt_sha256"])
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_PREFIX_POSTCOMMIT_RECEIPT_STATE_MISMATCH"
                        )
        return sorted(set(reasons))

    def extend_integrity_proof(
        self,
        proof: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Extend one full proof across sanctioned append-only suffixes.

        The first proof must still come from ``verify_integrity``.  Every
        extension rebinds its immutable prefix, streams and validates each new
        canonical row, and verifies every new append/postcommit receipt in one
        SQLite snapshot.  It performs no trust-by-row-count shortcut.
        """

        if not isinstance(proof, Mapping):
            raise Canonical5mArchiveError(
                "label_archive_integrity_proof_mapping_required"
            )
        try:
            connection = self._connect_readonly()
        except (OSError, sqlite3.Error, Canonical5mArchiveError) as exc:
            return {
                **dict(proof),
                "status": "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_PROOF_EXTENSION_FAILED",
                "archive_integrity_verified": False,
                "verification_mode": "BLOCKED_PREFIX_EXTENSION",
                "rejection_reasons": [
                    f"LABEL_ARCHIVE_OPEN_FAILED:{type(exc).__name__}"
                ],
            }

        reasons: list[str] = []
        prior_rows = int(proof.get("verified_rows") or 0)
        prior_receipts = int(proof.get("verified_append_receipts") or 0)
        prior_chain = str(proof.get("archive_chain_sha256") or "")
        prior_commit_at = proof.get("verified_last_commit_prepared_at")
        prior_postcommit_at = proof.get("verified_last_postcommit_readback_at")
        verified_rows = prior_rows
        verified_receipts = prior_receipts
        verified_postcommit_receipts = int(
            proof.get("verified_postcommit_readback_receipts") or 0
        )
        verified_max_sequence = int(proof.get("verified_max_sequence") or 0)
        verified_receipt_clocks = prior_receipts
        verified_receipt_states = prior_receipts
        previous_chain = prior_chain
        expected_receipt_chain = prior_chain
        expected_receipt_total = prior_rows
        previous_receipt_clock = (
            _canonical_utc_millisecond(prior_commit_at)
            if prior_commit_at is not None
            else None
        )
        previous_postcommit_clock = (
            _canonical_utc_millisecond(prior_postcommit_at)
            if prior_postcommit_at is not None
            else None
        )
        last_commit_prepared_at = prior_commit_at
        last_postcommit_readback_at = prior_postcommit_at
        total_append_receipts = prior_receipts
        metadata: dict[str, str] = {}
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            reasons.extend(
                self._integrity_prefix_proof_rejection_reasons(connection, proof)
            )
            metadata = self._metadata(connection)
            suffix_cursor = connection.execute(
                """
                SELECT sequence, symbol, candle_close_time_ms,
                       candle_open_time_ms, available_at_ms, candle_id,
                       raw_payload_hash, market_fact_sha256, content_sha256,
                       payload_json, previous_chain_sha256,
                       record_chain_sha256, append_transaction_id
                FROM canonical_5m_candles
                WHERE sequence > ?
                ORDER BY sequence ASC
                """,
                (verified_max_sequence,),
            )
            while not reasons:
                stored = suffix_cursor.fetchone()
                if stored is None:
                    break
                if int(stored["sequence"]) != verified_max_sequence + 1:
                    reasons.append("LABEL_ARCHIVE_SUFFIX_SEQUENCE_GAP")
                    break
                payload_json = str(stored["payload_json"])
                if len(payload_json.encode()) > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES:
                    reasons.append("LABEL_ARCHIVE_ROW_PAYLOAD_BYTES_EXCEEDED")
                    break
                try:
                    payload = json.loads(payload_json)
                    canonical_payload_json = canonical_json(payload)
                    validated = validate_canonical_finalized_5m_candle(payload)
                except (
                    TypeError,
                    ValueError,
                    Canonical5mValidationError,
                ):
                    reasons.append("LABEL_ARCHIVE_STORED_CANONICAL_PAYLOAD_INVALID")
                    break
                content_hash = hashlib.sha256(
                    canonical_payload_json.encode()
                ).hexdigest()
                if canonical_payload_json != payload_json:
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_NOT_CANONICAL_JSON")
                    break
                if content_hash != str(stored["content_sha256"]):
                    reasons.append("LABEL_ARCHIVE_CONTENT_SHA256_MISMATCH")
                    break
                if (
                    str(stored["symbol"]) != validated["symbol"]
                    or int(stored["candle_close_time_ms"])
                    != validated["close_time_ms"]
                    or int(stored["candle_open_time_ms"])
                    != validated["open_time_ms"]
                    or int(stored["available_at_ms"])
                    != validated["available_at_ms"]
                    or str(stored["candle_id"]) != validated["candle_id"]
                    or str(stored["raw_payload_hash"])
                    != validated["raw_payload_hash"]
                    or str(stored["market_fact_sha256"])
                    != validated["market_fact_sha256"]
                ):
                    reasons.append("LABEL_ARCHIVE_INDEX_PAYLOAD_IDENTITY_MISMATCH")
                    break
                if str(stored["previous_chain_sha256"]) != previous_chain:
                    reasons.append("LABEL_ARCHIVE_CHAIN_PREDECESSOR_MISMATCH")
                    break
                expected_chain = self._record_chain_sha256(
                    previous_chain_sha256=previous_chain,
                    validated=validated,
                    append_transaction_id=str(stored["append_transaction_id"]),
                )
                if expected_chain != str(stored["record_chain_sha256"]):
                    reasons.append("LABEL_ARCHIVE_RECORD_CHAIN_SHA256_MISMATCH")
                    break
                previous_chain = expected_chain
                verified_rows += 1
                verified_max_sequence = int(stored["sequence"])

            missing_suffix_receipts = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM canonical_5m_candles AS candle
                    LEFT JOIN canonical_5m_append_receipts AS receipt
                      ON receipt.transaction_id = candle.append_transaction_id
                    WHERE candle.sequence > ? AND receipt.transaction_id IS NULL
                    """,
                    (prior_rows,),
                ).fetchone()[0]
            )
            if missing_suffix_receipts:
                reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_MISSING")
            total_append_receipts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_append_receipts"
                ).fetchone()[0]
            )
            receipt_cursor = connection.execute(
                """
                SELECT transaction_id, receipt_schema_version, batch_sha256,
                       attempted_rows, inserted_rows, duplicate_rows,
                       total_unique_rows, archive_chain_sha256, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM canonical_5m_append_receipts
                WHERE (? IS NULL OR commit_prepared_at > ?)
                ORDER BY commit_prepared_at ASC
                """,
                (prior_commit_at, prior_commit_at),
            )
            while not reasons:
                receipt = receipt_cursor.fetchone()
                if receipt is None:
                    break
                receipt_reasons = self._append_receipt_rejection_reasons(receipt)
                if receipt_reasons:
                    reasons.extend(receipt_reasons)
                    break
                receipt_clock = _canonical_utc_millisecond(
                    receipt["commit_prepared_at"]
                )
                if (
                    receipt_clock is None
                    or (
                        previous_receipt_clock is not None
                        and receipt_clock <= previous_receipt_clock
                    )
                    or (
                        previous_postcommit_clock is not None
                        and receipt_clock <= previous_postcommit_clock
                    )
                ):
                    reasons.append("LABEL_ARCHIVE_SUFFIX_RECEIPT_CLOCK_INVALID")
                    break
                transaction_rows = connection.execute(
                    """
                    SELECT sequence, symbol, candle_close_time_ms,
                           content_sha256, previous_chain_sha256,
                           record_chain_sha256
                    FROM canonical_5m_candles
                    WHERE append_transaction_id = ?
                    ORDER BY sequence ASC
                    LIMIT ?
                    """,
                    (str(receipt["transaction_id"]), MAX_APPEND_ROWS + 1),
                ).fetchall()
                inserted_rows = int(receipt["inserted_rows"])
                if len(transaction_rows) != inserted_rows:
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_INSERTED_ROWS_MISMATCH"
                    )
                    break
                prior_expected_total = expected_receipt_total
                expected_receipt_total += inserted_rows
                if int(receipt["total_unique_rows"]) != expected_receipt_total:
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_CUMULATIVE_TOTAL_MISMATCH"
                    )
                    break
                receipt_chain = str(receipt["archive_chain_sha256"])
                if transaction_rows:
                    if (
                        int(transaction_rows[0]["sequence"])
                        != prior_expected_total + 1
                        or int(transaction_rows[-1]["sequence"])
                        != expected_receipt_total
                        or str(transaction_rows[0]["previous_chain_sha256"])
                        != expected_receipt_chain
                        or str(transaction_rows[-1]["record_chain_sha256"])
                        != receipt_chain
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_APPEND_RECEIPT_CHAIN_TRANSITION_MISMATCH"
                        )
                        break
                elif receipt_chain != expected_receipt_chain:
                    reasons.append(
                        "LABEL_ARCHIVE_DUPLICATE_ONLY_RECEIPT_CHAIN_CHANGED"
                    )
                    break
                identities = [
                    (
                        str(row["symbol"]),
                        int(row["candle_close_time_ms"]),
                        str(row["content_sha256"]),
                    )
                    for row in transaction_rows
                ]
                postcommit = connection.execute(
                    """
                    SELECT transaction_id, readback_schema_version,
                           append_receipt_sha256, inserted_rows,
                           inserted_identities_sha256,
                           readback_receipt_sha256, readback_receipt_json,
                           postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    WHERE transaction_id = ?
                    """,
                    (str(receipt["transaction_id"]),),
                ).fetchone()
                if postcommit is None:
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
                    )
                    break
                reasons.extend(self._postcommit_receipt_rejection_reasons(postcommit))
                postcommit_clock = _canonical_utc_millisecond(
                    postcommit["postcommit_readback_at"]
                )
                if (
                    postcommit_clock is None
                    or postcommit_clock < receipt_clock
                    or (
                        previous_postcommit_clock is not None
                        and postcommit_clock <= previous_postcommit_clock
                    )
                    or str(postcommit["append_receipt_sha256"])
                    != str(receipt["receipt_sha256"])
                    or int(postcommit["inserted_rows"]) != len(identities)
                    or str(postcommit["inserted_identities_sha256"])
                    != self._inserted_identities_sha256(identities)
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_SUFFIX_POSTCOMMIT_BINDING_MISMATCH"
                    )
                    break
                expected_receipt_chain = receipt_chain
                previous_receipt_clock = receipt_clock
                previous_postcommit_clock = postcommit_clock
                last_commit_prepared_at = str(receipt["commit_prepared_at"])
                last_postcommit_readback_at = str(
                    postcommit["postcommit_readback_at"]
                )
                verified_receipts += 1
                verified_postcommit_receipts += 1
                verified_receipt_clocks += 1
                verified_receipt_states += 1

            if verified_receipts != total_append_receipts:
                reasons.append("LABEL_ARCHIVE_SUFFIX_RECEIPT_COUNT_MISMATCH")
            if verified_postcommit_receipts != total_append_receipts:
                reasons.append(
                    "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_COUNT_MISMATCH"
                )
            if expected_receipt_total != verified_rows:
                reasons.append(
                    "LABEL_ARCHIVE_APPEND_RECEIPT_CUMULATIVE_FINAL_TOTAL_MISMATCH"
                )
            if expected_receipt_chain != previous_chain:
                reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_FINAL_CHAIN_MISMATCH")
            if int(metadata.get("total_unique_rows") or 0) != verified_rows:
                reasons.append("LABEL_ARCHIVE_TOTAL_UNIQUE_ROWS_MISMATCH")
            if metadata.get("archive_chain_sha256") != previous_chain:
                reasons.append("LABEL_ARCHIVE_FINAL_CHAIN_SHA256_MISMATCH")
            connection.commit()
        except (
            OSError,
            sqlite3.Error,
            Canonical5mArchiveError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            reasons.append(
                "LABEL_ARCHIVE_PROOF_EXTENSION_FAILED:"
                f"{type(exc).__name__}"
            )
        finally:
            connection.close()

        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "status": (
                "VERIFIED_CANONICAL_5M_LABEL_ARCHIVE"
                if not reasons
                else "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_PROOF_EXTENSION_FAILED"
            ),
            "archive_integrity_verified": not reasons,
            "verified_rows": verified_rows,
            "verified_max_sequence": verified_max_sequence,
            "verified_append_receipts": verified_receipts,
            "verified_postcommit_readback_receipts": verified_postcommit_receipts,
            "append_receipt_ordering_verified": (
                verified_receipt_clocks == total_append_receipts
            ),
            "append_receipt_order": _APPEND_RECEIPT_ORDER,
            "append_receipt_cumulative_state_verified": (
                verified_receipt_states == total_append_receipts
                and expected_receipt_total == verified_rows
                and expected_receipt_chain == previous_chain
            ),
            "postcommit_clock_causality_verified": (
                verified_postcommit_receipts == total_append_receipts
            ),
            "verified_last_commit_prepared_at": last_commit_prepared_at,
            "verified_last_postcommit_readback_at": last_postcommit_readback_at,
            "archive_chain_sha256": previous_chain,
            "retention_policy": metadata.get("retention_policy"),
            "automatic_pruning_enabled": (
                metadata.get("automatic_pruning_enabled") != "false"
            ),
            "verification_memory_bound": (
                "STREAMING_ONE_SUFFIX_CANDLE_OR_RECEIPT_PLUS_JSON_PAYLOAD"
            ),
            "verification_mode": "VERIFIED_APPEND_ONLY_SUFFIX_EXTENSION",
            "proof_extended_from_rows": prior_rows,
            "proof_extended_rows": verified_rows - prior_rows,
            "proof_extended_receipts": verified_receipts - prior_receipts,
            "rejection_reasons": sorted(set(reasons)),
        }

    @staticmethod
    def _set_metadata(
        connection: sqlite3.Connection,
        *,
        key: str,
        value: str,
        updated_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO canonical_5m_archive_metadata(
                metadata_key, metadata_value, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(metadata_key) DO UPDATE SET
                metadata_value=excluded.metadata_value,
                updated_at=excluded.updated_at
            """,
            (key, value, updated_at),
        )

    @staticmethod
    def _next_append_commit_prepared_at(
        connection: sqlite3.Connection,
    ) -> str:
        """Return the next immutable receipt clock inside the write lock.

        ``BEGIN IMMEDIATE`` plus the process/file writer lease serializes this
        read with the receipt insert.  The logical millisecond bump prevents
        wall-clock ties or rollback from making append order ambiguous.  A
        prior postcommit clock is also a lower bound so receipt visibility can
        never move backward across transaction boundaries.
        """

        candidate = _canonical_utc_millisecond(utc_now())
        if candidate is None:
            raise Canonical5mArchiveError(
                "append_receipt_candidate_clock_not_canonical_utc_millisecond"
            )
        prior_clock: datetime | None = None
        prior_sources = (
            (
                "append_receipt",
                connection.execute(
                    """
                    SELECT commit_prepared_at
                    FROM canonical_5m_append_receipts
                    ORDER BY commit_prepared_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
                "commit_prepared_at",
            ),
            (
                "postcommit_readback",
                connection.execute(
                    """
                    SELECT postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    ORDER BY postcommit_readback_at DESC
                    LIMIT 1
                    """
                ).fetchone(),
                "postcommit_readback_at",
            ),
        )
        for source, row, column in prior_sources:
            if row is None:
                continue
            parsed = _canonical_utc_millisecond(str(row[column]))
            if parsed is None:
                raise Canonical5mArchiveError(
                    f"prior_{source}_clock_not_canonical_utc_millisecond"
                )
            prior_clock = (
                parsed
                if prior_clock is None or parsed > prior_clock
                else prior_clock
            )
        if prior_clock is not None and candidate <= prior_clock:
            try:
                candidate = prior_clock + timedelta(milliseconds=1)
            except OverflowError as exc:
                raise Canonical5mArchiveError(
                    "append_receipt_logical_clock_overflow"
                ) from exc
        return _format_utc_millisecond(candidate)

    @staticmethod
    def _postcommit_readback_clock(commit_prepared_at: Any) -> str:
        prepared = _canonical_utc_millisecond(commit_prepared_at)
        candidate = _canonical_utc_millisecond(utc_now())
        if prepared is None or candidate is None:
            raise Canonical5mArchiveError(
                "postcommit_readback_clock_not_canonical_utc_millisecond"
            )
        return _format_utc_millisecond(max(prepared, candidate))

    @staticmethod
    def _record_chain_sha256(
        *,
        previous_chain_sha256: str,
        validated: Mapping[str, Any],
        append_transaction_id: str,
    ) -> str:
        return stable_sha256(
            {
                "previous_chain_sha256": previous_chain_sha256,
                "append_transaction_id": append_transaction_id,
                "symbol": validated["symbol"],
                "candle_close_time_ms": validated["close_time_ms"],
                "candle_id": validated["candle_id"],
                "content_sha256": validated["content_sha256"],
                "market_fact_sha256": validated["market_fact_sha256"],
            }
        )

    @staticmethod
    def _append_receipt_rejection_reasons(
        receipt: Mapping[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        receipt_json = str(receipt["receipt_json"])
        receipt_sha256 = str(receipt["receipt_sha256"])
        if hashlib.sha256(receipt_json.encode()).hexdigest() != receipt_sha256:
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_SHA256_MISMATCH")
        try:
            payload = json.loads(receipt_json)
        except (TypeError, ValueError):
            payload = None
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_JSON_INVALID")
        if not isinstance(payload, Mapping):
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_PAYLOAD_NOT_OBJECT")
            return reasons
        try:
            if canonical_json(payload) != receipt_json:
                reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_NOT_CANONICAL_JSON")
        except (TypeError, ValueError):
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_NOT_STRICT_JSON")
        expected_material = {
            "schema_version": str(receipt["receipt_schema_version"]),
            "transaction_id": str(receipt["transaction_id"]),
            "batch_sha256": str(receipt["batch_sha256"]),
            "attempted_rows": int(receipt["attempted_rows"]),
            "inserted_rows": int(receipt["inserted_rows"]),
            "duplicate_rows": int(receipt["duplicate_rows"]),
            "total_unique_rows": int(receipt["total_unique_rows"]),
            "archive_chain_sha256": str(receipt["archive_chain_sha256"]),
            "retention_policy": RETENTION_POLICY,
            "automatic_pruning_enabled": False,
            "commit_prepared_at": str(receipt["commit_prepared_at"]),
            "precommit_readback_verified": True,
        }
        if dict(payload) != expected_material:
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_COLUMN_MISMATCH")
        attempted = int(receipt["attempted_rows"])
        inserted = int(receipt["inserted_rows"])
        duplicates = int(receipt["duplicate_rows"])
        total = int(receipt["total_unique_rows"])
        if (
            str(receipt["receipt_schema_version"])
            != APPEND_RECEIPT_SCHEMA_VERSION
        ):
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_SCHEMA_MISMATCH")
        if not str(receipt["transaction_id"]).startswith(
            "canonical_5m_append_"
        ):
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_TRANSACTION_INVALID")
        if _valid_sha256(receipt["batch_sha256"]) is None:
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_BATCH_SHA256_INVALID")
        if _valid_sha256(receipt["archive_chain_sha256"]) is None:
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_CHAIN_SHA256_INVALID")
        if (
            attempted < 0
            or inserted < 0
            or duplicates < 0
            or total < 0
            or attempted != inserted + duplicates
            or inserted > total
        ):
            reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_COUNTS_INVALID")
        if int(receipt["precommit_readback_verified"]) != 1:
            reasons.append(
                "LABEL_ARCHIVE_APPEND_RECEIPT_PRECOMMIT_READBACK_UNVERIFIED"
            )
        if _canonical_utc_millisecond(receipt["commit_prepared_at"]) is None:
            reasons.append(
                "LABEL_ARCHIVE_APPEND_RECEIPT_COMMIT_PREPARED_AT_"
                "NOT_CANONICAL_UTC_MILLISECOND"
            )
        return reasons

    @staticmethod
    def _inserted_identities_sha256(
        identities: Iterable[tuple[str, int, str]],
    ) -> str:
        return stable_sha256(
            [
                {
                    "symbol": symbol,
                    "candle_close_time_ms": close_ms,
                    "content_sha256": content_sha256,
                }
                for symbol, close_ms, content_sha256 in sorted(identities)
            ]
        )

    @staticmethod
    def _postcommit_receipt_rejection_reasons(
        receipt: Mapping[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        receipt_json = str(receipt["readback_receipt_json"])
        receipt_sha256 = str(receipt["readback_receipt_sha256"])
        if hashlib.sha256(receipt_json.encode()).hexdigest() != receipt_sha256:
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_RECEIPT_SHA256_MISMATCH")
        try:
            payload = json.loads(receipt_json)
        except (TypeError, ValueError):
            payload = None
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_RECEIPT_JSON_INVALID")
        if not isinstance(payload, Mapping):
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_RECEIPT_NOT_OBJECT")
            return reasons
        expected = {
            "schema_version": str(receipt["readback_schema_version"]),
            "transaction_id": str(receipt["transaction_id"]),
            "append_receipt_sha256": str(receipt["append_receipt_sha256"]),
            "inserted_rows": int(receipt["inserted_rows"]),
            "inserted_identities_sha256": str(
                receipt["inserted_identities_sha256"]
            ),
            "postcommit_readback_at": str(
                receipt["postcommit_readback_at"]
            ),
            "postcommit_readback_verified": True,
        }
        try:
            payload_is_canonical = canonical_json(payload) == receipt_json
        except (TypeError, ValueError):
            payload_is_canonical = False
        if dict(payload) != expected or not payload_is_canonical:
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_RECEIPT_COLUMN_MISMATCH")
        if (
            str(receipt["readback_schema_version"])
            != POSTCOMMIT_READBACK_RECEIPT_SCHEMA_VERSION
        ):
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_RECEIPT_SCHEMA_MISMATCH")
        if _valid_sha256(receipt["append_receipt_sha256"]) is None:
            reasons.append(
                "LABEL_ARCHIVE_POSTCOMMIT_APPEND_RECEIPT_SHA256_INVALID"
            )
        if _valid_sha256(receipt["inserted_identities_sha256"]) is None:
            reasons.append(
                "LABEL_ARCHIVE_POSTCOMMIT_IDENTITIES_SHA256_INVALID"
            )
        if int(receipt["inserted_rows"]) < 0:
            reasons.append("LABEL_ARCHIVE_POSTCOMMIT_INSERTED_ROWS_INVALID")
        if _canonical_utc_millisecond(receipt["postcommit_readback_at"]) is None:
            reasons.append(
                "LABEL_ARCHIVE_POSTCOMMIT_READBACK_AT_"
                "NOT_CANONICAL_UTC_MILLISECOND"
            )
        return reasons

    @staticmethod
    def _bounded_validated_rows(
        candles: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        validated_rows: list[dict[str, Any]] = []
        identities: dict[tuple[str, int], str] = {}
        candle_ids: dict[str, str] = {}
        conflicts: list[str] = []
        total_payload_bytes = 0
        for raw in candles:
            if len(validated_rows) >= MAX_APPEND_ROWS:
                raise Canonical5mArchiveError(
                    f"canonical_5m_append_row_limit_exceeded:{MAX_APPEND_ROWS}"
                )
            if not isinstance(raw, Mapping):
                raise Canonical5mValidationError(["LABEL_CANDLE_ROW_NOT_OBJECT"])
            validated = validate_canonical_finalized_5m_candle(raw)
            payload_bytes = len(str(validated["payload_json"]).encode())
            if payload_bytes > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES:
                raise Canonical5mArchiveError(
                    "canonical_5m_candle_payload_bytes_exceeded:"
                    f"{MAX_CANONICAL_CANDLE_PAYLOAD_BYTES}"
                )
            total_payload_bytes += payload_bytes
            if total_payload_bytes > MAX_APPEND_PAYLOAD_BYTES:
                raise Canonical5mArchiveError(
                    "canonical_5m_append_payload_bytes_exceeded:"
                    f"{MAX_APPEND_PAYLOAD_BYTES}"
                )
            identity = (
                str(validated["symbol"]),
                int(validated["close_time_ms"]),
            )
            content_hash = str(validated["content_sha256"])
            prior = identities.get(identity)
            if prior is not None and prior != content_hash:
                conflicts.append(f"{identity[0]}:{identity[1]}")
            identities.setdefault(identity, content_hash)
            candle_id = str(validated["candle_id"])
            prior_id_content = candle_ids.get(candle_id)
            if (
                prior_id_content is not None
                and prior_id_content != content_hash
            ):
                conflicts.append(f"candle_id:{candle_id}")
            candle_ids.setdefault(candle_id, content_hash)
            validated_rows.append(validated)
        if conflicts:
            raise Canonical5mIdentityConflictError(conflicts)
        return validated_rows

    def append_candles(
        self,
        candles: Iterable[Mapping[str, Any]],
        *,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> Canonical5mAppendResult:
        with self.writer_lease(writer_lease) as held_lease:
            return self._append_candles_locked(
                candles,
                writer_lease=held_lease,
            )

    def _append_candles_locked(
        self,
        candles: Iterable[Mapping[str, Any]],
        *,
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> Canonical5mAppendResult:
        validated_rows = self._bounded_validated_rows(candles)
        attempted_rows = len(validated_rows)
        transaction_id = f"canonical_5m_append_{uuid.uuid4().hex}"
        batch_sha256 = stable_sha256(
            [
                {
                    "symbol": row["symbol"],
                    "candle_close_time_ms": row["close_time_ms"],
                    "candle_id": row["candle_id"],
                    "content_sha256": row["content_sha256"],
                    "market_fact_sha256": row["market_fact_sha256"],
                }
                for row in validated_rows
            ]
        )
        inserted = 0
        duplicates = 0
        inserted_identities: list[tuple[str, int, str]] = []
        self._ensure_initialized(writer_lease=writer_lease)
        self.recover_pending_postcommit_readbacks(writer_lease=writer_lease)
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            connection.execute("BEGIN IMMEDIATE")
            metadata = self._metadata(connection)
            if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
                raise Canonical5mArchiveError("archive_schema_version_mismatch")
            if metadata.get("retention_policy") != RETENTION_POLICY:
                raise Canonical5mArchiveError("archive_retention_policy_mismatch")
            if metadata.get("automatic_pruning_enabled") != "false":
                raise Canonical5mArchiveError("automatic_pruning_must_remain_disabled")
            stored_count = int(metadata.get("total_unique_rows") or 0)
            actual_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_candles"
                ).fetchone()[0]
            )
            if stored_count != actual_count:
                raise Canonical5mArchiveError("archive_row_count_metadata_mismatch")
            previous_chain = str(
                metadata.get("archive_chain_sha256") or _GENESIS_CHAIN_SHA256
            )
            latest = connection.execute(
                """
                SELECT record_chain_sha256
                FROM canonical_5m_candles
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()
            actual_latest_chain = (
                str(latest["record_chain_sha256"])
                if latest is not None
                else _GENESIS_CHAIN_SHA256
            )
            if actual_latest_chain != previous_chain:
                raise Canonical5mArchiveError("archive_chain_metadata_mismatch")
            conflicts: list[str] = []
            for validated in validated_rows:
                existing = connection.execute(
                    """
                    SELECT symbol, candle_close_time_ms, candle_id,
                           market_fact_sha256, content_sha256, payload_json
                    FROM canonical_5m_candles
                    WHERE (symbol = ? AND candle_close_time_ms = ?)
                       OR candle_id = ?
                    """,
                    (
                        validated["symbol"],
                        validated["close_time_ms"],
                        validated["candle_id"],
                    ),
                ).fetchall()
                if existing:
                    if all(
                        str(row["symbol"]) == validated["symbol"]
                        and int(row["candle_close_time_ms"])
                        == validated["close_time_ms"]
                        and str(row["candle_id"]) == validated["candle_id"]
                        and str(row["market_fact_sha256"])
                        == validated["market_fact_sha256"]
                        and str(row["content_sha256"])
                        == validated["content_sha256"]
                        and str(row["payload_json"])
                        == validated["payload_json"]
                        for row in existing
                    ):
                        duplicates += 1
                        continue
                    conflicts.append(
                        f"{validated['symbol']}:{validated['close_time_ms']}"
                    )
                    continue
                record_chain = self._record_chain_sha256(
                    previous_chain_sha256=previous_chain,
                    validated=validated,
                    append_transaction_id=transaction_id,
                )
                connection.execute(
                    """
                    INSERT INTO canonical_5m_candles(
                        symbol, candle_close_time_ms, candle_open_time_ms,
                        available_at_ms, candle_id, raw_payload_hash,
                        market_fact_sha256, content_sha256, payload_json,
                        previous_chain_sha256,
                        record_chain_sha256, append_transaction_id, archived_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        validated["symbol"],
                        validated["close_time_ms"],
                        validated["open_time_ms"],
                        validated["available_at_ms"],
                        validated["candle_id"],
                        validated["raw_payload_hash"],
                        validated["market_fact_sha256"],
                        validated["content_sha256"],
                        validated["payload_json"],
                        previous_chain,
                        record_chain,
                        transaction_id,
                        utc_now(),
                    ),
                )
                previous_chain = record_chain
                inserted += 1
                inserted_identities.append(
                    (
                        str(validated["symbol"]),
                        int(validated["close_time_ms"]),
                        str(validated["content_sha256"]),
                    )
                )
            if conflicts:
                raise Canonical5mIdentityConflictError(conflicts)
            total_unique_rows = actual_count + inserted
            commit_prepared_at = self._next_append_commit_prepared_at(
                connection
            )
            self._set_metadata(
                connection,
                key="total_unique_rows",
                value=str(total_unique_rows),
                updated_at=commit_prepared_at,
            )
            self._set_metadata(
                connection,
                key="archive_chain_sha256",
                value=previous_chain,
                updated_at=commit_prepared_at,
            )
            receipt_material = {
                "schema_version": APPEND_RECEIPT_SCHEMA_VERSION,
                "transaction_id": transaction_id,
                "batch_sha256": batch_sha256,
                "attempted_rows": attempted_rows,
                "inserted_rows": inserted,
                "duplicate_rows": duplicates,
                "total_unique_rows": total_unique_rows,
                "archive_chain_sha256": previous_chain,
                "retention_policy": RETENTION_POLICY,
                "automatic_pruning_enabled": False,
                "commit_prepared_at": commit_prepared_at,
                "precommit_readback_verified": True,
            }
            receipt_json = canonical_json(receipt_material)
            receipt_sha256 = hashlib.sha256(receipt_json.encode()).hexdigest()
            connection.execute(
                """
                INSERT INTO canonical_5m_append_receipts(
                    transaction_id, receipt_schema_version, batch_sha256,
                    attempted_rows, inserted_rows, duplicate_rows,
                    total_unique_rows, archive_chain_sha256, receipt_sha256,
                    receipt_json, commit_prepared_at,
                    precommit_readback_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    transaction_id,
                    APPEND_RECEIPT_SCHEMA_VERSION,
                    batch_sha256,
                    attempted_rows,
                    inserted,
                    duplicates,
                    total_unique_rows,
                    previous_chain,
                    receipt_sha256,
                    receipt_json,
                    commit_prepared_at,
                ),
            )
            for symbol, close_ms, expected_hash in inserted_identities:
                readback = connection.execute(
                    """
                    SELECT content_sha256 FROM canonical_5m_candles
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    (symbol, close_ms),
                ).fetchone()
                if (
                    readback is None
                    or str(readback["content_sha256"]) != expected_hash
                ):
                    raise Canonical5mArchiveReadbackError(
                        "append_transaction_precommit_readback_failed"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        self._verify_committed_transaction(
            transaction_id=transaction_id,
            receipt_sha256=receipt_sha256,
            inserted_identities=inserted_identities,
            writer_lease=writer_lease,
        )
        return Canonical5mAppendResult(
            transaction_id=transaction_id,
            attempted_rows=attempted_rows,
            inserted_rows=inserted,
            duplicate_rows=duplicates,
            total_unique_rows=total_unique_rows,
            archive_chain_sha256=previous_chain,
            batch_sha256=batch_sha256,
            append_receipt_sha256=receipt_sha256,
            transaction_committed=True,
            transaction_readback_verified=True,
            retention_policy=RETENTION_POLICY,
            automatic_pruning_enabled=False,
        )

    def _verify_committed_transaction(
        self,
        *,
        transaction_id: str,
        receipt_sha256: str,
        inserted_identities: Iterable[tuple[str, int, str]],
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> None:
        writer_lease.validate_for(self.path)
        identities = tuple(inserted_identities)
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            receipt = connection.execute(
                """
                SELECT transaction_id, receipt_schema_version, batch_sha256,
                       attempted_rows, inserted_rows, duplicate_rows,
                       total_unique_rows, archive_chain_sha256, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM canonical_5m_append_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if (
                receipt is None
                or str(receipt["receipt_sha256"]) != receipt_sha256
                or self._append_receipt_rejection_reasons(receipt)
            ):
                raise Canonical5mArchiveReadbackError(
                    "append_transaction_receipt_readback_failed"
                )
            for symbol, close_ms, expected_hash in identities:
                row = connection.execute(
                    """
                    SELECT content_sha256, append_transaction_id
                    FROM canonical_5m_candles
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    (symbol, close_ms),
                ).fetchone()
                if (
                    row is None
                    or str(row["content_sha256"]) != expected_hash
                    or str(row["append_transaction_id"]) != transaction_id
                ):
                    raise Canonical5mArchiveReadbackError(
                        "append_transaction_row_readback_failed"
                    )
            connection.commit()
        finally:
            connection.close()

        postcommit_readback_at = self._postcommit_readback_clock(
            receipt["commit_prepared_at"]
        )
        attestation_material = {
            "schema_version": POSTCOMMIT_READBACK_RECEIPT_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "append_receipt_sha256": receipt_sha256,
            "inserted_rows": len(identities),
            "inserted_identities_sha256": self._inserted_identities_sha256(
                identities
            ),
            "postcommit_readback_at": postcommit_readback_at,
            "postcommit_readback_verified": True,
        }
        attestation_json = canonical_json(attestation_material)
        attestation_sha256 = hashlib.sha256(
            attestation_json.encode()
        ).hexdigest()
        connection = self._connect_write(writer_lease=writer_lease)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_5m_postcommit_readback_receipts(
                    transaction_id, readback_schema_version,
                    append_receipt_sha256, inserted_rows,
                    inserted_identities_sha256, readback_receipt_sha256,
                    readback_receipt_json, postcommit_readback_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    POSTCOMMIT_READBACK_RECEIPT_SCHEMA_VERSION,
                    receipt_sha256,
                    len(identities),
                    attestation_material["inserted_identities_sha256"],
                    attestation_sha256,
                    attestation_json,
                    postcommit_readback_at,
                ),
            )
            stored = connection.execute(
                """
                SELECT transaction_id, readback_schema_version,
                       append_receipt_sha256, inserted_rows,
                       inserted_identities_sha256, readback_receipt_sha256,
                       readback_receipt_json, postcommit_readback_at
                FROM canonical_5m_postcommit_readback_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if (
                stored is None
                or self._postcommit_receipt_rejection_reasons(stored)
                or str(stored["append_receipt_sha256"]) != receipt_sha256
                or int(stored["inserted_rows"]) != len(identities)
                or str(stored["inserted_identities_sha256"])
                != attestation_material["inserted_identities_sha256"]
            ):
                raise Canonical5mArchiveReadbackError(
                    "append_transaction_postcommit_attestation_failed"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            stored = connection.execute(
                """
                SELECT transaction_id, readback_schema_version,
                       append_receipt_sha256, inserted_rows,
                       inserted_identities_sha256, readback_receipt_sha256,
                       readback_receipt_json, postcommit_readback_at
                FROM canonical_5m_postcommit_readback_receipts
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if (
                stored is None
                or self._postcommit_receipt_rejection_reasons(stored)
                or str(stored["append_receipt_sha256"]) != receipt_sha256
                or int(stored["inserted_rows"]) != len(identities)
                or str(stored["inserted_identities_sha256"])
                != attestation_material["inserted_identities_sha256"]
            ):
                raise Canonical5mArchiveReadbackError(
                    "append_transaction_postcommit_receipt_readback_failed"
                )
            connection.commit()
        finally:
            connection.close()

    def recover_pending_postcommit_readbacks(
        self,
        *,
        max_transactions: int = MAX_APPEND_ROWS,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> dict[str, Any]:
        with self.writer_lease(writer_lease) as held_lease:
            return self._recover_pending_postcommit_readbacks_locked(
                max_transactions=max_transactions,
                writer_lease=held_lease,
            )

    def _recover_pending_postcommit_readbacks_locked(
        self,
        *,
        max_transactions: int,
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> dict[str, Any]:
        """Attest bounded transaction-A crash gaps after independent reopen."""

        bounded = _strict_positive_int(max_transactions)
        if bounded is None or bounded > MAX_APPEND_ROWS:
            raise Canonical5mArchiveError(
                "postcommit_recovery_transaction_limit_invalid"
            )
        if not self.path.is_file():
            return {
                "status": "NO_ARCHIVE_TO_RECOVER",
                "pending_transactions": 0,
                "recovered_transactions": 0,
            }
        connection = self._connect_readonly()
        pending: list[tuple[str, str, tuple[tuple[str, int, str], ...]]] = []
        try:
            connection.execute("BEGIN")
            candidates = connection.execute(
                """
                SELECT receipt.transaction_id, receipt.receipt_schema_version,
                       receipt.batch_sha256, receipt.attempted_rows,
                       receipt.inserted_rows, receipt.duplicate_rows,
                       receipt.total_unique_rows,
                       receipt.archive_chain_sha256, receipt.receipt_sha256,
                       receipt.receipt_json, receipt.commit_prepared_at,
                       receipt.precommit_readback_verified
                FROM canonical_5m_append_receipts AS receipt
                LEFT JOIN canonical_5m_postcommit_readback_receipts AS post
                  ON post.transaction_id = receipt.transaction_id
                WHERE post.transaction_id IS NULL
                ORDER BY receipt.commit_prepared_at ASC
                LIMIT ?
                """,
                (bounded + 1,),
            ).fetchall()
            if len(candidates) > bounded:
                raise Canonical5mArchiveError(
                    "postcommit_recovery_transaction_limit_exceeded"
                )
            for receipt in candidates:
                receipt_reasons = self._append_receipt_rejection_reasons(
                    receipt
                )
                if receipt_reasons:
                    raise Canonical5mArchiveReadbackError(
                        "pending_append_receipt_invalid:"
                        + ",".join(receipt_reasons)
                    )
                identities = tuple(
                    (
                        str(row["symbol"]),
                        int(row["candle_close_time_ms"]),
                        str(row["content_sha256"]),
                    )
                    for row in connection.execute(
                        """
                        SELECT symbol, candle_close_time_ms, content_sha256
                        FROM canonical_5m_candles
                        WHERE append_transaction_id = ?
                        ORDER BY symbol, candle_close_time_ms, content_sha256
                        LIMIT ?
                        """,
                        (
                            str(receipt["transaction_id"]),
                            MAX_APPEND_ROWS + 1,
                        ),
                    )
                )
                if len(identities) != int(receipt["inserted_rows"]):
                    raise Canonical5mArchiveReadbackError(
                        "pending_append_transaction_row_count_mismatch"
                    )
                pending.append(
                    (
                        str(receipt["transaction_id"]),
                        str(receipt["receipt_sha256"]),
                        identities,
                    )
                )
            connection.commit()
        finally:
            connection.close()
        for transaction_id, receipt_sha256, identities in pending:
            self._verify_committed_transaction(
                transaction_id=transaction_id,
                receipt_sha256=receipt_sha256,
                inserted_identities=identities,
                writer_lease=writer_lease,
            )
        return {
            "status": "POSTCOMMIT_READBACK_RECOVERY_COMPLETE",
            "pending_transactions": len(pending),
            "recovered_transactions": len(pending),
        }

    def attest_exact_tail_transaction(
        self,
        candles: Iterable[Mapping[str, Any]],
        *,
        writer_lease: Canonical5mArchiveWriterLease | None = None,
    ) -> dict[str, Any]:
        with self.writer_lease(writer_lease) as held_lease:
            return self._attest_exact_tail_transaction_locked(
                candles,
                writer_lease=held_lease,
            )

    def _attest_exact_tail_transaction_locked(
        self,
        candles: Iterable[Mapping[str, Any]],
        *,
        writer_lease: Canonical5mArchiveWriterLease,
    ) -> dict[str, Any]:
        """Prove one exact all-inserted append is the current archive tail.

        This narrow proof closes the crash gap where an append transaction
        committed but its caller did not durably record the returned receipt.
        It is intentionally not a substitute for ``verify_integrity``: callers
        must hold their archive-writer lease, must have proven the identities
        absent before the append, and must run one terminal full verification.
        """

        validated_rows = self._bounded_validated_rows(candles)
        if not validated_rows:
            raise Canonical5mArchiveError(
                "exact_tail_transaction_attestation_rows_empty"
            )
        expected_batch_sha256 = stable_sha256(
            [
                {
                    "symbol": row["symbol"],
                    "candle_close_time_ms": row["close_time_ms"],
                    "candle_id": row["candle_id"],
                    "content_sha256": row["content_sha256"],
                    "market_fact_sha256": row["market_fact_sha256"],
                }
                for row in validated_rows
            ]
        )
        expected_bindings = [
            {
                "symbol": str(row["symbol"]),
                "candle_close_time_ms": int(row["close_time_ms"]),
                "candle_id": str(row["candle_id"]),
                "content_sha256": str(row["content_sha256"]),
                "market_fact_sha256": str(row["market_fact_sha256"]),
            }
            for row in validated_rows
        ]
        proof: dict[str, Any] = {
            "schema_version": (
                EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION
            ),
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "status": "BLOCKED_CANONICAL_5M_EXACT_TAIL_TRANSACTION_UNVERIFIED",
            "transaction_scope_verified": False,
            "archive_integrity_verified": False,
            "terminal_full_integrity_verification_required": True,
            "expected_rows": len(validated_rows),
            "expected_batch_sha256": expected_batch_sha256,
            "expected_bindings_sha256": stable_sha256(expected_bindings),
            "transaction_id": None,
            "append_receipt_sha256": None,
            "postcommit_readback_receipt_sha256": None,
            "transaction_attestation_sha256": None,
            "rejection_reasons": [],
        }
        try:
            recovery = self.recover_pending_postcommit_readbacks(
                writer_lease=writer_lease
            )
        except (
            OSError,
            sqlite3.Error,
            Canonical5mArchiveError,
            TypeError,
            ValueError,
        ) as exc:
            proof["rejection_reasons"] = [
                "LABEL_ARCHIVE_POSTCOMMIT_RECOVERY_FAILED:"
                f"{type(exc).__name__}"
            ]
            return proof
        proof["postcommit_recovery"] = recovery

        reasons: list[str] = []
        transaction_id: str | None = None
        transaction_rows: list[sqlite3.Row] = []
        receipt: sqlite3.Row | None = None
        postcommit: sqlite3.Row | None = None
        metadata: dict[str, str] = {}
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect_write(writer_lease=writer_lease)
            # A reserved writer lock keeps the tail snapshot stable while the
            # exact transaction, receipts, and metadata are cross-checked.
            connection.execute("BEGIN IMMEDIATE")
            metadata = self._metadata(connection)
            if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
                reasons.append("LABEL_ARCHIVE_SCHEMA_VERSION_MISMATCH")
            if metadata.get("retention_policy") != RETENTION_POLICY:
                reasons.append("LABEL_ARCHIVE_RETENTION_POLICY_MISMATCH")
            if metadata.get("automatic_pruning_enabled") != "false":
                reasons.append("LABEL_ARCHIVE_AUTOMATIC_PRUNING_ENABLED")

            first_expected = validated_rows[0]
            first_match = connection.execute(
                """
                SELECT append_transaction_id
                FROM canonical_5m_candles
                WHERE symbol = ? AND candle_close_time_ms = ?
                """,
                (
                    first_expected["symbol"],
                    first_expected["close_time_ms"],
                ),
            ).fetchone()
            if first_match is None:
                reasons.append(
                    "LABEL_ARCHIVE_EXACT_TAIL_TRANSACTION_ROWS_MISSING"
                )
            else:
                transaction_id = str(first_match["append_transaction_id"])
                transaction_rows = list(
                    connection.execute(
                        """
                        SELECT sequence, symbol, candle_close_time_ms,
                               candle_open_time_ms, available_at_ms, candle_id,
                               raw_payload_hash, market_fact_sha256,
                               content_sha256, payload_json,
                               previous_chain_sha256, record_chain_sha256,
                               append_transaction_id
                        FROM canonical_5m_candles
                        WHERE append_transaction_id = ?
                        ORDER BY sequence ASC
                        LIMIT ?
                        """,
                        (transaction_id, MAX_APPEND_ROWS + 1),
                    )
                )
                if len(transaction_rows) != len(validated_rows):
                    reasons.append(
                        "LABEL_ARCHIVE_EXACT_TAIL_TRANSACTION_ROW_COUNT_MISMATCH"
                    )

            if len(transaction_rows) == len(validated_rows):
                sequences = [int(row["sequence"]) for row in transaction_rows]
                if sequences != list(
                    range(sequences[0], sequences[0] + len(sequences))
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_EXACT_TAIL_TRANSACTION_SEQUENCE_GAP"
                    )
                latest = connection.execute(
                    """
                    SELECT sequence, record_chain_sha256
                    FROM canonical_5m_candles
                    ORDER BY sequence DESC
                    LIMIT 1
                    """
                ).fetchone()
                if (
                    latest is None
                    or int(latest["sequence"]) != sequences[-1]
                    or str(latest["record_chain_sha256"])
                    != str(transaction_rows[-1]["record_chain_sha256"])
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_NOT_CURRENT_TAIL"
                    )
                if (
                    metadata.get("archive_chain_sha256")
                    != str(transaction_rows[-1]["record_chain_sha256"])
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_FINAL_CHAIN_MISMATCH"
                    )
                predecessor = connection.execute(
                    """
                    SELECT record_chain_sha256
                    FROM canonical_5m_candles
                    WHERE sequence < ?
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (sequences[0],),
                ).fetchone()
                expected_previous_chain = (
                    str(predecessor["record_chain_sha256"])
                    if predecessor is not None
                    else _GENESIS_CHAIN_SHA256
                )
                for stored, expected in zip(
                    transaction_rows,
                    validated_rows,
                    strict=True,
                ):
                    try:
                        stored_payload = json.loads(str(stored["payload_json"]))
                        stored_validated = (
                            validate_canonical_finalized_5m_candle(
                                stored_payload
                            )
                        )
                    except (TypeError, ValueError, Canonical5mValidationError):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_PAYLOAD_INVALID"
                        )
                        continue
                    exact_columns = (
                        str(stored["symbol"]) == str(expected["symbol"])
                        and int(stored["candle_close_time_ms"])
                        == int(expected["close_time_ms"])
                        and int(stored["candle_open_time_ms"])
                        == int(expected["open_time_ms"])
                        and int(stored["available_at_ms"])
                        == int(expected["available_at_ms"])
                        and str(stored["candle_id"])
                        == str(expected["candle_id"])
                        and str(stored["raw_payload_hash"])
                        == str(expected["raw_payload_hash"])
                        and str(stored["market_fact_sha256"])
                        == str(expected["market_fact_sha256"])
                        and str(stored["content_sha256"])
                        == str(expected["content_sha256"])
                        and str(stored["payload_json"])
                        == str(expected["payload_json"])
                        and str(stored["append_transaction_id"])
                        == transaction_id
                        and stored_validated["content_sha256"]
                        == expected["content_sha256"]
                    )
                    if not exact_columns:
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_PAYLOAD_MISMATCH"
                        )
                    if (
                        str(stored["previous_chain_sha256"])
                        != expected_previous_chain
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_CHAIN_LINK_MISMATCH"
                        )
                    expected_record_chain = self._record_chain_sha256(
                        previous_chain_sha256=expected_previous_chain,
                        validated=expected,
                        append_transaction_id=str(transaction_id),
                    )
                    if (
                        str(stored["record_chain_sha256"])
                        != expected_record_chain
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_CHAIN_FORMULA_MISMATCH"
                        )
                    expected_previous_chain = expected_record_chain

            if transaction_id is not None:
                receipt = connection.execute(
                    """
                    SELECT transaction_id, receipt_schema_version,
                           batch_sha256, attempted_rows, inserted_rows,
                           duplicate_rows, total_unique_rows,
                           archive_chain_sha256, receipt_sha256, receipt_json,
                           commit_prepared_at, precommit_readback_verified
                    FROM canonical_5m_append_receipts
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
                if receipt is None:
                    reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_MISSING")
                else:
                    reasons.extend(
                        self._append_receipt_rejection_reasons(receipt)
                    )
                    latest_receipt = connection.execute(
                        """
                        SELECT commit_prepared_at
                        FROM canonical_5m_append_receipts
                        ORDER BY commit_prepared_at DESC
                        LIMIT 1
                        """
                    ).fetchone()
                    if (
                        latest_receipt is None
                        or str(receipt["commit_prepared_at"])
                        != str(latest_receipt["commit_prepared_at"])
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_NOT_LATEST_RECEIPT"
                        )
                    if str(receipt["batch_sha256"]) != expected_batch_sha256:
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_BATCH_MISMATCH"
                        )
                    if (
                        int(receipt["attempted_rows"]) != len(validated_rows)
                        or int(receipt["inserted_rows"])
                        != len(validated_rows)
                        or int(receipt["duplicate_rows"]) != 0
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_COUNTS_MISMATCH"
                        )
                    if (
                        str(receipt["total_unique_rows"])
                        != metadata.get("total_unique_rows")
                        or str(receipt["archive_chain_sha256"])
                        != metadata.get("archive_chain_sha256")
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_NOT_METADATA_TAIL"
                        )

                postcommit = connection.execute(
                    """
                    SELECT transaction_id, readback_schema_version,
                           append_receipt_sha256, inserted_rows,
                           inserted_identities_sha256,
                           readback_receipt_sha256,
                           readback_receipt_json, postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
                if postcommit is None:
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
                    )
                else:
                    reasons.extend(
                        self._postcommit_receipt_rejection_reasons(postcommit)
                    )
                    identities = [
                        (
                            str(row["symbol"]),
                            int(row["candle_close_time_ms"]),
                            str(row["content_sha256"]),
                        )
                        for row in transaction_rows
                    ]
                    if (
                        receipt is None
                        or str(postcommit["append_receipt_sha256"])
                        != str(receipt["receipt_sha256"])
                        or int(postcommit["inserted_rows"])
                        != len(validated_rows)
                        or str(postcommit["inserted_identities_sha256"])
                        != self._inserted_identities_sha256(identities)
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_EXACT_TRANSACTION_POSTCOMMIT_BINDING_MISMATCH"
                        )
            connection.commit()
        except (
            OSError,
            sqlite3.Error,
            Canonical5mArchiveError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            reasons.append(
                "LABEL_ARCHIVE_EXACT_TAIL_TRANSACTION_READ_FAILED:"
                f"{type(exc).__name__}"
            )
        finally:
            if connection is not None:
                connection.close()

        proof["transaction_id"] = transaction_id
        proof["rejection_reasons"] = sorted(set(reasons))
        if reasons or receipt is None or postcommit is None:
            return proof
        transaction_bindings = [
            {
                "sequence": int(row["sequence"]),
                "symbol": str(row["symbol"]),
                "candle_close_time_ms": int(row["candle_close_time_ms"]),
                "candle_id": str(row["candle_id"]),
                "content_sha256": str(row["content_sha256"]),
                "market_fact_sha256": str(row["market_fact_sha256"]),
            }
            for row in transaction_rows
        ]
        attestation_material = {
            "schema_version": (
                EXACT_TAIL_TRANSACTION_ATTESTATION_SCHEMA_VERSION
            ),
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "status": "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION",
            "transaction_scope_verified": True,
            "archive_integrity_verified": False,
            "transaction_id": transaction_id,
            "expected_batch_sha256": expected_batch_sha256,
            "expected_bindings_sha256": stable_sha256(expected_bindings),
            "transaction_bindings": transaction_bindings,
            "attempted_rows": int(receipt["attempted_rows"]),
            "inserted_rows": int(receipt["inserted_rows"]),
            "duplicate_rows": int(receipt["duplicate_rows"]),
            "append_receipt_sha256": str(receipt["receipt_sha256"]),
            "postcommit_readback_receipt_sha256": str(
                postcommit["readback_receipt_sha256"]
            ),
            "archive_total_unique_rows": int(
                metadata["total_unique_rows"]
            ),
            "archive_chain_sha256": metadata["archive_chain_sha256"],
            "transaction_is_current_tail": True,
            "terminal_full_integrity_verification_required": True,
            "rejection_reasons": [],
        }
        proof.update(attestation_material)
        proof.update(
            {
                "status": "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION",
                "transaction_scope_verified": True,
                "archive_integrity_verified": False,
                "transaction_attestation_sha256": stable_sha256(
                    attestation_material
                ),
                "rejection_reasons": [],
            }
        )
        return proof

    def attest_exact_transaction_identity(
        self,
        *,
        transaction_id: str,
        candles: Iterable[Mapping[str, Any]],
        expected_append_receipt_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Revalidate one immutable append transaction at any archive depth.

        Unlike ``attest_exact_tail_transaction``, this proof remains meaningful
        after later sanctioned appends.  It binds every supplied canonical row
        to one contiguous transaction, its append receipt, its postcommit
        readback receipt, and its chain predecessor/formula.  It never claims
        that the transaction is still the current archive tail.
        """

        validated_rows = self._bounded_validated_rows(candles)
        normalized_transaction_id = str(transaction_id or "")
        expected_receipt_sha = (
            _valid_sha256(expected_append_receipt_sha256)
            if expected_append_receipt_sha256 is not None
            else None
        )
        expected_bindings = [
            {
                "symbol": str(row["symbol"]),
                "candle_close_time_ms": int(row["close_time_ms"]),
                "candle_id": str(row["candle_id"]),
                "content_sha256": str(row["content_sha256"]),
                "market_fact_sha256": str(row["market_fact_sha256"]),
            }
            for row in validated_rows
        ]
        expected_batch_sha256 = stable_sha256(expected_bindings)
        rejection_reasons: list[str] = []
        if not re.fullmatch(r"canonical_5m_append_[0-9a-f]{32}", normalized_transaction_id):
            rejection_reasons.append("LABEL_ARCHIVE_TRANSACTION_ID_INVALID")
        if not validated_rows:
            rejection_reasons.append("LABEL_ARCHIVE_EXACT_TRANSACTION_ROWS_EMPTY")
        if (
            expected_append_receipt_sha256 is not None
            and expected_receipt_sha is None
        ):
            rejection_reasons.append(
                "LABEL_ARCHIVE_EXPECTED_APPEND_RECEIPT_SHA256_INVALID"
            )

        transaction_rows: list[sqlite3.Row] = []
        receipt: sqlite3.Row | None = None
        postcommit: sqlite3.Row | None = None
        transaction_is_current_tail = False
        try:
            connection = self._connect_readonly()
            try:
                connection.execute("BEGIN")
                transaction_rows = list(
                    connection.execute(
                        """
                        SELECT sequence, symbol, candle_close_time_ms,
                               candle_open_time_ms, available_at_ms, candle_id,
                               raw_payload_hash, market_fact_sha256,
                               content_sha256, payload_json,
                               previous_chain_sha256, record_chain_sha256,
                               append_transaction_id
                        FROM canonical_5m_candles
                        WHERE append_transaction_id = ?
                        ORDER BY sequence ASC
                        LIMIT ?
                        """,
                        (normalized_transaction_id, MAX_APPEND_ROWS + 1),
                    )
                )
                receipt = connection.execute(
                    """
                    SELECT transaction_id, receipt_schema_version,
                           batch_sha256, attempted_rows, inserted_rows,
                           duplicate_rows, total_unique_rows,
                           archive_chain_sha256, receipt_sha256, receipt_json,
                           commit_prepared_at, precommit_readback_verified
                    FROM canonical_5m_append_receipts
                    WHERE transaction_id = ?
                    """,
                    (normalized_transaction_id,),
                ).fetchone()
                postcommit = connection.execute(
                    """
                    SELECT transaction_id, readback_schema_version,
                           append_receipt_sha256, inserted_rows,
                           inserted_identities_sha256,
                           readback_receipt_sha256,
                           readback_receipt_json, postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    WHERE transaction_id = ?
                    """,
                    (normalized_transaction_id,),
                ).fetchone()
                latest = connection.execute(
                    """
                    SELECT sequence, record_chain_sha256
                    FROM canonical_5m_candles
                    ORDER BY sequence DESC LIMIT 1
                    """
                ).fetchone()
                if transaction_rows and latest is not None:
                    transaction_is_current_tail = (
                        int(latest["sequence"])
                        == int(transaction_rows[-1]["sequence"])
                        and str(latest["record_chain_sha256"])
                        == str(transaction_rows[-1]["record_chain_sha256"])
                    )
                predecessor = None
                if transaction_rows:
                    predecessor = connection.execute(
                        """
                        SELECT record_chain_sha256
                        FROM canonical_5m_candles
                        WHERE sequence < ?
                        ORDER BY sequence DESC LIMIT 1
                        """,
                        (int(transaction_rows[0]["sequence"]),),
                    ).fetchone()
                connection.commit()
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            rejection_reasons.append(
                "LABEL_ARCHIVE_EXACT_TRANSACTION_READ_FAILED:"
                f"{type(exc).__name__}"
            )
            predecessor = None

        if len(transaction_rows) != len(validated_rows):
            rejection_reasons.append(
                "LABEL_ARCHIVE_EXACT_TRANSACTION_ROW_COUNT_MISMATCH"
            )
        if transaction_rows:
            sequences = [int(row["sequence"]) for row in transaction_rows]
            if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
                rejection_reasons.append(
                    "LABEL_ARCHIVE_EXACT_TRANSACTION_SEQUENCE_GAP"
                )
            expected_previous_chain = (
                str(predecessor["record_chain_sha256"])
                if predecessor is not None
                else _GENESIS_CHAIN_SHA256
            )
            for stored, expected in zip(
                transaction_rows,
                validated_rows,
                strict=False,
            ):
                try:
                    stored_payload = json.loads(str(stored["payload_json"]))
                    stored_validated = validate_canonical_finalized_5m_candle(
                        stored_payload
                    )
                except (TypeError, ValueError, Canonical5mValidationError):
                    rejection_reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_PAYLOAD_INVALID"
                    )
                    continue
                exact_columns = (
                    str(stored["symbol"]) == str(expected["symbol"])
                    and int(stored["candle_close_time_ms"])
                    == int(expected["close_time_ms"])
                    and int(stored["candle_open_time_ms"])
                    == int(expected["open_time_ms"])
                    and int(stored["available_at_ms"])
                    == int(expected["available_at_ms"])
                    and str(stored["candle_id"]) == str(expected["candle_id"])
                    and str(stored["raw_payload_hash"])
                    == str(expected["raw_payload_hash"])
                    and str(stored["market_fact_sha256"])
                    == str(expected["market_fact_sha256"])
                    and str(stored["content_sha256"])
                    == str(expected["content_sha256"])
                    and str(stored["payload_json"]) == str(expected["payload_json"])
                    and str(stored["append_transaction_id"])
                    == normalized_transaction_id
                    and stored_validated["content_sha256"]
                    == expected["content_sha256"]
                )
                if not exact_columns:
                    rejection_reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_PAYLOAD_MISMATCH"
                    )
                if str(stored["previous_chain_sha256"]) != expected_previous_chain:
                    rejection_reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_CHAIN_LINK_MISMATCH"
                    )
                expected_record_chain = self._record_chain_sha256(
                    previous_chain_sha256=expected_previous_chain,
                    validated=expected,
                    append_transaction_id=normalized_transaction_id,
                )
                if str(stored["record_chain_sha256"]) != expected_record_chain:
                    rejection_reasons.append(
                        "LABEL_ARCHIVE_EXACT_TRANSACTION_CHAIN_FORMULA_MISMATCH"
                    )
                expected_previous_chain = expected_record_chain

        if receipt is None:
            rejection_reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_MISSING")
        else:
            rejection_reasons.extend(self._append_receipt_rejection_reasons(receipt))
            if (
                str(receipt["transaction_id"]) != normalized_transaction_id
                or str(receipt["batch_sha256"]) != expected_batch_sha256
                or int(receipt["attempted_rows"]) != len(validated_rows)
                or int(receipt["inserted_rows"]) != len(validated_rows)
                or int(receipt["duplicate_rows"]) != 0
                or (
                    transaction_rows
                    and str(receipt["archive_chain_sha256"])
                    != str(transaction_rows[-1]["record_chain_sha256"])
                )
            ):
                rejection_reasons.append(
                    "LABEL_ARCHIVE_EXACT_TRANSACTION_RECEIPT_BINDING_MISMATCH"
                )
            if (
                expected_receipt_sha is not None
                and str(receipt["receipt_sha256"]) != expected_receipt_sha
            ):
                rejection_reasons.append(
                    "LABEL_ARCHIVE_EXACT_TRANSACTION_EXPECTED_RECEIPT_MISMATCH"
                )

        identities = [
            (
                str(row["symbol"]),
                int(row["candle_close_time_ms"]),
                str(row["content_sha256"]),
            )
            for row in transaction_rows
        ]
        if postcommit is None:
            rejection_reasons.append(
                "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
            )
        else:
            rejection_reasons.extend(
                self._postcommit_receipt_rejection_reasons(postcommit)
            )
            if (
                receipt is None
                or str(postcommit["transaction_id"]) != normalized_transaction_id
                or str(postcommit["append_receipt_sha256"])
                != str(receipt["receipt_sha256"])
                or int(postcommit["inserted_rows"]) != len(validated_rows)
                or str(postcommit["inserted_identities_sha256"])
                != self._inserted_identities_sha256(identities)
            ):
                rejection_reasons.append(
                    "LABEL_ARCHIVE_EXACT_TRANSACTION_POSTCOMMIT_BINDING_MISMATCH"
                )

        transaction_bindings = [
            {
                "sequence": int(row["sequence"]),
                "symbol": str(row["symbol"]),
                "candle_close_time_ms": int(row["candle_close_time_ms"]),
                "candle_id": str(row["candle_id"]),
                "content_sha256": str(row["content_sha256"]),
                "market_fact_sha256": str(row["market_fact_sha256"]),
            }
            for row in transaction_rows
        ]
        reasons = sorted(set(rejection_reasons))
        material = {
            "schema_version": EXACT_TRANSACTION_IDENTITY_ATTESTATION_SCHEMA_VERSION,
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "transaction_id": normalized_transaction_id,
            "expected_rows": len(validated_rows),
            "expected_batch_sha256": expected_batch_sha256,
            "expected_bindings_sha256": stable_sha256(expected_bindings),
            "transaction_bindings": transaction_bindings,
            "append_receipt_sha256": (
                str(receipt["receipt_sha256"]) if receipt is not None else None
            ),
            "postcommit_readback_receipt_sha256": (
                str(postcommit["readback_receipt_sha256"])
                if postcommit is not None
                else None
            ),
            "transaction_total_unique_rows": (
                int(receipt["total_unique_rows"]) if receipt is not None else None
            ),
            "transaction_archive_chain_sha256": (
                str(transaction_rows[-1]["record_chain_sha256"])
                if transaction_rows
                else None
            ),
            "transaction_is_current_tail": transaction_is_current_tail,
            "transaction_identity_verified": not reasons,
            "rejection_reasons": reasons,
        }
        return {
            **material,
            "status": (
                "VERIFIED_CANONICAL_5M_EXACT_TRANSACTION_IDENTITY"
                if not reasons
                else "BLOCKED_CANONICAL_5M_EXACT_TRANSACTION_IDENTITY_UNVERIFIED"
            ),
            "transaction_identity_attestation_sha256": stable_sha256(material),
        }

    def verified_range(
        self,
        *,
        symbol: str,
        start_close_time_ms: int,
        end_close_time_ms: int,
        training_observed_at: datetime | str | int,
        limit: int,
        archive_integrity_proof: Mapping[str, Any] | None = None,
        _allow_sparse_coverage: bool = False,
        _require_receipt_cutoff: bool = False,
        _verified_transaction_cache: set[
            tuple[str, str, str, str, int, str]
        ] | None = None,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Return one complete contiguous range or a fail-closed proof."""

        normalized_symbol = str(symbol).strip().upper()
        start_ms = _strict_epoch_ms(start_close_time_ms)
        end_ms = _strict_epoch_ms(end_close_time_ms)
        observed_us = _aware_epoch_us(training_observed_at)
        observed_ms = _aware_epoch_ms(training_observed_at)
        bounded_limit = _strict_positive_int(limit)
        reasons: list[str] = []
        if not _SYMBOL_RE.fullmatch(normalized_symbol):
            reasons.append("LABEL_ARCHIVE_QUERY_SYMBOL_INVALID")
        if start_ms is None or (start_ms + 1) % LABEL_SLOT_MILLISECONDS != 0:
            reasons.append("LABEL_ARCHIVE_QUERY_START_CLOSE_INVALID")
        if end_ms is None or (end_ms + 1) % LABEL_SLOT_MILLISECONDS != 0:
            reasons.append("LABEL_ARCHIVE_QUERY_END_CLOSE_INVALID")
        if start_ms is not None and end_ms is not None and end_ms < start_ms:
            reasons.append("LABEL_ARCHIVE_QUERY_RANGE_REVERSED")
        if observed_us is None or observed_ms is None:
            reasons.append("TRAINING_OBSERVED_AT_MISSING_OR_INVALID")
        if bounded_limit is None or bounded_limit > MAX_QUERY_ROWS:
            reasons.append("LABEL_ARCHIVE_QUERY_LIMIT_INVALID")
        if not isinstance(_allow_sparse_coverage, bool):
            reasons.append("LABEL_ARCHIVE_QUERY_COVERAGE_MODE_INVALID")
        if not isinstance(_require_receipt_cutoff, bool):
            reasons.append("LABEL_ARCHIVE_QUERY_RECEIPT_CUTOFF_MODE_INVALID")
        if _allow_sparse_coverage and not isinstance(
            archive_integrity_proof,
            Mapping,
        ):
            reasons.append(
                "LABEL_ARCHIVE_CURRENT_FULL_INTEGRITY_PROOF_REQUIRED"
            )
        expected_rows = (
            ((end_ms - start_ms) // LABEL_SLOT_MILLISECONDS) + 1
            if start_ms is not None
            and end_ms is not None
            and end_ms >= start_ms
            else 0
        )
        if expected_rows > MAX_QUERY_ROWS:
            reasons.append("LABEL_ARCHIVE_QUERY_RANGE_EXCEEDS_MAXIMUM_ROWS")
        if bounded_limit is not None and expected_rows > bounded_limit:
            reasons.append("LABEL_ARCHIVE_QUERY_LIMIT_INSUFFICIENT")
        proof: dict[str, Any] = {
            "schema_version": RANGE_PROOF_SCHEMA_VERSION,
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "symbol": normalized_symbol,
            "start_close_time_ms": start_ms,
            "end_close_time_ms": end_ms,
            "training_observed_at_epoch_us": observed_us,
            "training_observed_at_ms": observed_ms,
            "requested_limit": bounded_limit,
            "maximum_query_rows": MAX_QUERY_ROWS,
            "maximum_query_payload_bytes": MAX_QUERY_PAYLOAD_BYTES,
            "expected_rows": expected_rows,
            "loaded_rows": 0,
            "loaded_payload_bytes": 0,
            "retention_policy": RETENTION_POLICY,
            "automatic_pruning_enabled": False,
            "silent_pruning_used": False,
            "bounded_memory_contract": "O_QUERY_ROWS_AND_PAYLOAD_BYTES",
            "indexed_query_contract": "SYMBOL_PLUS_CANDLE_CLOSE_TIME_RANGE",
            "range_completeness_required": not _allow_sparse_coverage,
            "receipt_commit_cutoff_required": _require_receipt_cutoff,
        }
        if reasons:
            proof.update(
                {
                    "status": "BLOCKED_INVALID_CANONICAL_5M_RANGE_QUERY",
                    "rejection_reasons": sorted(set(reasons)),
                }
            )
            return None, proof
        assert bounded_limit is not None
        if not self.path.is_file():
            proof.update(
                {
                    "status": "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_MISSING",
                    "rejection_reasons": [
                        "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
                    ],
                }
            )
            return None, proof
        assert start_ms is not None
        assert end_ms is not None
        assert observed_ms is not None
        try:
            connection = self._connect_readonly()
        except (OSError, sqlite3.Error, Canonical5mArchiveError) as exc:
            proof.update(
                {
                    "status": "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_OPEN_FAILED",
                    "rejection_reasons": [
                        f"LABEL_ARCHIVE_OPEN_FAILED:{type(exc).__name__}"
                    ],
                }
            )
            return None, proof
        rows: list[dict[str, Any]] = []
        query_plan: list[str] = []
        index_used = False
        payload_bytes = 0
        preflight_payload_bytes = 0
        maximum_row_payload_bytes = 0
        integrity_proof_current = False
        integrity_prefix_proof_verified = False
        quick_check_verified = False
        validated_payload_rows = 0
        pit_verified_rows = 0
        append_receipts_verified = 0
        postcommit_receipts_verified = 0
        transaction_identity_cache_hits = 0
        row_chain_provenance: list[dict[str, Any]] = []
        append_receipt_hashes: list[str] = []
        postcommit_receipt_hashes: list[str] = []
        transaction_ids: set[str] = set()
        metadata: dict[str, str] = {}
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            quick_check = str(
                connection.execute("PRAGMA quick_check(1)").fetchone()[0]
                if archive_integrity_proof is None
                else "integrity_proof_reused"
            )
            integrity_proof_current = False
            if archive_integrity_proof is None:
                if quick_check != "ok":
                    reasons.append("LABEL_ARCHIVE_SQLITE_QUICK_CHECK_FAILED")
                else:
                    quick_check_verified = True
            else:
                proof_reasons = self._integrity_proof_rejection_reasons(
                    connection,
                    archive_integrity_proof,
                )
                integrity_proof_current = not proof_reasons
                if proof_reasons and not _allow_sparse_coverage:
                    prefix_reasons = self._integrity_prefix_proof_rejection_reasons(
                        connection,
                        archive_integrity_proof,
                    )
                    if prefix_reasons:
                        reasons.extend(prefix_reasons)
                    else:
                        integrity_prefix_proof_verified = True
                else:
                    reasons.extend(proof_reasons)
            metadata = self._metadata(connection)
            if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
                reasons.append("LABEL_ARCHIVE_SCHEMA_VERSION_MISMATCH")
            if metadata.get("retention_policy") != RETENTION_POLICY:
                reasons.append("LABEL_ARCHIVE_RETENTION_POLICY_MISMATCH")
            if metadata.get("automatic_pruning_enabled") != "false":
                reasons.append("LABEL_ARCHIVE_AUTOMATIC_PRUNING_ENABLED")
            query_plan = [
                str(row[3])
                for row in connection.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT * FROM canonical_5m_candles
                    WHERE symbol = ?
                      AND candle_close_time_ms BETWEEN ? AND ?
                    ORDER BY candle_close_time_ms ASC
                    LIMIT ?
                    """,
                    (normalized_symbol, start_ms, end_ms, bounded_limit + 1),
                )
            ]
            index_used = any(
                "canonical_5m_symbol_close_time" in detail
                or "sqlite_autoindex_canonical_5m_candles_2" in detail
                for detail in query_plan
            )
            if not index_used:
                reasons.append("LABEL_ARCHIVE_SYMBOL_CLOSE_INDEX_NOT_USED")
            aggregate = connection.execute(
                """
                SELECT COUNT(*) AS row_count,
                       COALESCE(
                           SUM(length(CAST(payload_json AS BLOB))),
                           0
                       ) AS payload_bytes,
                       COALESCE(
                           MAX(length(CAST(payload_json AS BLOB))),
                           0
                       ) AS maximum_row_payload_bytes
                FROM canonical_5m_candles
                WHERE symbol = ?
                  AND candle_close_time_ms BETWEEN ? AND ?
                """,
                (normalized_symbol, start_ms, end_ms),
            ).fetchone()
            stored_row_count = int(aggregate["row_count"])
            preflight_payload_bytes = int(aggregate["payload_bytes"])
            maximum_row_payload_bytes = int(
                aggregate["maximum_row_payload_bytes"]
            )
            if (
                stored_row_count != expected_rows
                and not _allow_sparse_coverage
            ):
                reasons.append("LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH")
            if preflight_payload_bytes > MAX_QUERY_PAYLOAD_BYTES:
                reasons.append("LABEL_ARCHIVE_QUERY_PAYLOAD_BYTES_EXCEEDED")
            if maximum_row_payload_bytes > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES:
                reasons.append("LABEL_ARCHIVE_ROW_PAYLOAD_BYTES_EXCEEDED")
            stored_cursor = connection.execute(
                """
                SELECT sequence, symbol, candle_close_time_ms,
                       candle_open_time_ms,
                       available_at_ms, candle_id, raw_payload_hash,
                       market_fact_sha256, content_sha256, payload_json,
                       previous_chain_sha256, record_chain_sha256,
                       append_transaction_id
                FROM canonical_5m_candles
                WHERE symbol = ?
                  AND candle_close_time_ms BETWEEN ? AND ?
                ORDER BY candle_close_time_ms ASC
                LIMIT ?
                """,
                (normalized_symbol, start_ms, end_ms, bounded_limit + 1),
            )
            payload_bytes = 0
            prior_close: int | None = None
            streamed_rows = 0
            nonblocking_preflight_reasons = {
                "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH"
            }
            while not any(
                reason not in nonblocking_preflight_reasons
                for reason in reasons
            ):
                stored = stored_cursor.fetchone()
                if stored is None:
                    break
                streamed_rows += 1
                if streamed_rows > bounded_limit:
                    reasons.append("LABEL_ARCHIVE_QUERY_LIMIT_EXCEEDED")
                    break
                if (
                    integrity_prefix_proof_verified
                    and archive_integrity_proof is not None
                    and int(stored["sequence"])
                    > int(archive_integrity_proof["verified_max_sequence"])
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_RANGE_EXCEEDS_VERIFIED_PREFIX_FRONTIER"
                    )
                    break
                payload_json = str(stored["payload_json"])
                payload_bytes += len(payload_json.encode())
                if payload_bytes > MAX_QUERY_PAYLOAD_BYTES:
                    reasons.append("LABEL_ARCHIVE_QUERY_PAYLOAD_BYTES_EXCEEDED")
                    break
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_JSON_INVALID")
                    continue
                if not isinstance(payload, Mapping):
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_NOT_OBJECT")
                    continue
                try:
                    canonical_payload_json = canonical_json(payload)
                except (TypeError, ValueError):
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_NOT_STRICT_JSON")
                    continue
                if canonical_payload_json != payload_json:
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_NOT_CANONICAL_JSON")
                    continue
                content_hash = hashlib.sha256(
                    canonical_payload_json.encode()
                ).hexdigest()
                if content_hash != str(stored["content_sha256"]):
                    reasons.append("LABEL_ARCHIVE_CONTENT_SHA256_MISMATCH")
                    continue
                try:
                    validated = validate_canonical_finalized_5m_candle(
                        payload,
                        expected_symbol=normalized_symbol,
                    )
                except Canonical5mValidationError as exc:
                    reasons.extend(exc.reasons)
                    continue
                close_ms = int(validated["close_time_ms"])
                if (
                    str(stored["symbol"]) != validated["symbol"]
                    or int(stored["candle_close_time_ms"]) != close_ms
                    or int(stored["candle_open_time_ms"])
                    != validated["open_time_ms"]
                    or int(stored["available_at_ms"])
                    != validated["available_at_ms"]
                    or str(stored["candle_id"]) != validated["candle_id"]
                    or str(stored["raw_payload_hash"])
                    != validated["raw_payload_hash"]
                    or str(stored["market_fact_sha256"])
                    != validated["market_fact_sha256"]
                ):
                    reasons.append("LABEL_ARCHIVE_INDEX_PAYLOAD_IDENTITY_MISMATCH")
                    continue
                validated_payload_rows += 1
                expected_record_chain = self._record_chain_sha256(
                    previous_chain_sha256=str(
                        stored["previous_chain_sha256"]
                    ),
                    validated=validated,
                    append_transaction_id=str(
                        stored["append_transaction_id"]
                    ),
                )
                if expected_record_chain != str(stored["record_chain_sha256"]):
                    reasons.append(
                        "LABEL_ARCHIVE_RECORD_CHAIN_SHA256_MISMATCH"
                    )
                    continue
                row_chain_provenance.append(
                    {
                        "sequence": int(stored["sequence"]),
                        "previous_chain_sha256": str(
                            stored["previous_chain_sha256"]
                        ),
                        "record_chain_sha256": str(
                            stored["record_chain_sha256"]
                        ),
                    }
                )
                if int(validated["available_at_ms"]) > observed_ms:
                    reasons.append(
                        "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
                    )
                else:
                    pit_verified_rows += 1
                if (
                    prior_close is not None
                    and close_ms != prior_close + LABEL_SLOT_MILLISECONDS
                    and not _allow_sparse_coverage
                ):
                    reasons.append("CANONICAL_5M_LABEL_PATH_GAP")
                prior_close = close_ms
                transaction_ids.add(str(stored["append_transaction_id"]))
                rows.append(dict(payload))
            if rows and not _allow_sparse_coverage:
                if int(rows[0]["candle_close_time"]) != start_ms:
                    reasons.append("LABEL_ARCHIVE_RANGE_START_MISSING")
                if int(rows[-1]["candle_close_time"]) != end_ms:
                    reasons.append("LABEL_ARCHIVE_RANGE_END_MISSING")
            if transaction_ids:
                for transaction_id in sorted(transaction_ids):
                    receipt = connection.execute(
                        """
                    SELECT transaction_id, receipt_schema_version,
                           batch_sha256, attempted_rows, inserted_rows,
                           duplicate_rows, total_unique_rows,
                           archive_chain_sha256, receipt_sha256, receipt_json,
                           commit_prepared_at,
                           precommit_readback_verified
                    FROM canonical_5m_append_receipts
                    WHERE transaction_id = ?
                    """,
                        (transaction_id,),
                    ).fetchone()
                    if receipt is None:
                        reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_MISSING")
                        continue
                    receipt_reasons = self._append_receipt_rejection_reasons(
                        receipt
                    )
                    if receipt_reasons:
                        reasons.extend(receipt_reasons)
                        continue
                    receipt_prepared_us = _aware_epoch_us(
                        str(receipt["commit_prepared_at"])
                    )
                    if _require_receipt_cutoff and (
                        observed_us is None
                        or receipt_prepared_us is None
                        or receipt_prepared_us > observed_us
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_APPEND_RECEIPT_AFTER_TRAINING_OBSERVED_AT"
                        )
                        continue
                    append_receipts_verified += 1
                    append_receipt_hashes.append(
                        str(receipt["receipt_sha256"])
                    )
                    postcommit = connection.execute(
                        """
                        SELECT transaction_id, readback_schema_version,
                               append_receipt_sha256, inserted_rows,
                               inserted_identities_sha256,
                               readback_receipt_sha256,
                               readback_receipt_json,
                               postcommit_readback_at
                        FROM canonical_5m_postcommit_readback_receipts
                        WHERE transaction_id = ?
                        """,
                        (transaction_id,),
                    ).fetchone()
                    if postcommit is None:
                        reasons.append(
                            "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
                        )
                        continue
                    postcommit_reasons = (
                        self._postcommit_receipt_rejection_reasons(postcommit)
                    )
                    if postcommit_reasons:
                        reasons.extend(postcommit_reasons)
                        continue
                    postcommit_readback_us = _aware_epoch_us(
                        str(postcommit["postcommit_readback_at"])
                    )
                    if _require_receipt_cutoff and (
                        observed_us is None
                        or postcommit_readback_us is None
                        or postcommit_readback_us > observed_us
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_POSTCOMMIT_READBACK_AFTER_TRAINING_OBSERVED_AT"
                        )
                        continue
                    if (
                        str(postcommit["append_receipt_sha256"])
                        != str(receipt["receipt_sha256"])
                        or int(postcommit["inserted_rows"])
                        != int(receipt["inserted_rows"])
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_POSTCOMMIT_READBACK_BINDING_MISMATCH"
                        )
                        continue
                    cache_namespace = str(
                        archive_integrity_proof.get("archive_chain_sha256")
                        if archive_integrity_proof is not None
                        else metadata.get("archive_chain_sha256")
                    )
                    cache_key = (
                        cache_namespace,
                        transaction_id,
                        str(receipt["receipt_sha256"]),
                        str(postcommit["readback_receipt_sha256"]),
                        int(receipt["inserted_rows"]),
                        str(postcommit["inserted_identities_sha256"]),
                    )
                    if (
                        _verified_transaction_cache is not None
                        and cache_key in _verified_transaction_cache
                    ):
                        transaction_identity_cache_hits += 1
                        postcommit_receipts_verified += 1
                        postcommit_receipt_hashes.append(
                            str(postcommit["readback_receipt_sha256"])
                        )
                        continue
                    identities = [
                        (
                            str(identity["symbol"]),
                            int(identity["candle_close_time_ms"]),
                            str(identity["content_sha256"]),
                        )
                        for identity in connection.execute(
                            """
                            SELECT symbol, candle_close_time_ms, content_sha256
                            FROM canonical_5m_candles
                            WHERE append_transaction_id = ?
                            ORDER BY symbol, candle_close_time_ms,
                                     content_sha256
                            LIMIT ?
                            """,
                            (transaction_id, MAX_APPEND_ROWS + 1),
                        )
                    ]
                    if len(identities) != int(receipt["inserted_rows"]):
                        reasons.append(
                            "LABEL_ARCHIVE_APPEND_RECEIPT_INSERTED_ROWS_MISMATCH"
                        )
                        continue
                    if str(postcommit["inserted_identities_sha256"]) != (
                        self._inserted_identities_sha256(identities)
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_POSTCOMMIT_READBACK_BINDING_MISMATCH"
                        )
                        continue
                    if (
                        _verified_transaction_cache is not None
                        and len(_verified_transaction_cache) < MAX_QUERY_ROWS
                    ):
                        _verified_transaction_cache.add(cache_key)
                    postcommit_receipts_verified += 1
                    postcommit_receipt_hashes.append(
                        str(postcommit["readback_receipt_sha256"])
                    )
            connection.commit()
        except sqlite3.Error as exc:
            reasons.append(
                f"LABEL_ARCHIVE_SQLITE_READ_FAILED:{type(exc).__name__}"
            )
            query_plan = []
            index_used = False
            payload_bytes = 0
            quick_check_verified = False
        finally:
            connection.close()
        verification_target_rows = (
            len(rows) if _allow_sparse_coverage else expected_rows
        )
        receipt_scope_verified = (
            not transaction_ids and verification_target_rows == 0
        ) or (
            bool(transaction_ids)
            and append_receipts_verified == len(transaction_ids)
        )
        postcommit_scope_verified = (
            not transaction_ids and verification_target_rows == 0
        ) or (
            bool(transaction_ids)
            and postcommit_receipts_verified == len(transaction_ids)
        )
        proof.update(
            {
                "loaded_rows": len(rows),
                "loaded_payload_bytes": payload_bytes,
                "preflight_payload_bytes": preflight_payload_bytes,
                "maximum_row_payload_bytes": maximum_row_payload_bytes,
                "sqlite_quick_check_verified": (
                    quick_check_verified
                    if archive_integrity_proof is None
                    else None
                ),
                "archive_integrity_proof_reused": (
                    archive_integrity_proof is not None
                ),
                "archive_integrity_proof_current": (
                    integrity_proof_current
                    if archive_integrity_proof is not None
                    else None
                ),
                "archive_integrity_prefix_proof_verified": (
                    integrity_prefix_proof_verified
                    if archive_integrity_proof is not None
                    else None
                ),
                "symbol_close_time_index_used": index_used,
                "query_plan": query_plan,
                "retention_policy": metadata.get("retention_policy"),
                "automatic_pruning_enabled": (
                    metadata.get("automatic_pruning_enabled") != "false"
                    if metadata
                    else None
                ),
                "archive_schema_and_retention_verified": bool(metadata)
                and metadata.get("archive_schema_version")
                == ARCHIVE_SCHEMA_VERSION
                and metadata.get("retention_policy") == RETENTION_POLICY
                and metadata.get("automatic_pruning_enabled") == "false",
                "canonical_payloads_verified": (
                    validated_payload_rows == verification_target_rows
                ),
                "content_sha256_verified": (
                    validated_payload_rows == verification_target_rows
                ),
                "append_transaction_precommit_receipts_verified": (
                    receipt_scope_verified
                ),
                "postcommit_readback_receipts_verified": (
                    postcommit_scope_verified
                ),
                "record_chain_formula_verified": (
                    len(row_chain_provenance) == verification_target_rows
                ),
                "append_transaction_readback_receipts_verified": (
                    postcommit_scope_verified
                ),
                "pit_available_at_verified": (
                    pit_verified_rows == verification_target_rows
                ),
                "contiguous_path_verified": (
                    None
                    if _allow_sparse_coverage
                    else len(rows) == expected_rows
                    and not any(
                        reason
                        in {
                            "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH",
                            "CANONICAL_5M_LABEL_PATH_GAP",
                            "LABEL_ARCHIVE_RANGE_START_MISSING",
                            "LABEL_ARCHIVE_RANGE_END_MISSING",
                        }
                        for reason in reasons
                    )
                ),
                "sparse_coverage_rows_verified": (
                    validated_payload_rows == len(rows)
                    if _allow_sparse_coverage
                    else None
                ),
                "archive_total_unique_rows": metadata.get(
                    "total_unique_rows"
                ),
                "archive_chain_sha256": metadata.get(
                    "archive_chain_sha256"
                ),
                "append_receipt_sha256": sorted(append_receipt_hashes),
                "postcommit_readback_receipt_sha256": sorted(
                    postcommit_receipt_hashes
                ),
                "transaction_identity_cache_hits": transaction_identity_cache_hits,
            }
        )
        if reasons:
            proof.update(
                {
                    "status": "BLOCKED_CANONICAL_5M_LABEL_RANGE_UNVERIFIED",
                    "rejection_reasons": sorted(set(reasons)),
                    "range_sha256": None,
                }
            )
            return None, proof
        range_material = {
            "schema_version": RANGE_PROOF_SCHEMA_VERSION,
            "range_mode": (
                "SPARSE_COVERAGE"
                if _allow_sparse_coverage
                else "COMPLETE_CONTIGUOUS"
            ),
            "symbol": normalized_symbol,
            "start_close_time_ms": start_ms,
            "end_close_time_ms": end_ms,
            "training_observed_at_epoch_us": observed_us,
            "training_observed_at_ms": observed_ms,
            "receipt_commit_cutoff_required": _require_receipt_cutoff,
            "candle_ids": [row["candle_id"] for row in rows],
            "content_sha256_by_close": [
                {
                    "candle_close_time_ms": row["candle_close_time"],
                    "content_sha256": hashlib.sha256(
                        canonical_json(row).encode()
                    ).hexdigest(),
                }
                for row in rows
            ],
            "row_chain_provenance": row_chain_provenance,
            "append_receipt_sha256": sorted(append_receipt_hashes),
            "postcommit_readback_receipt_sha256": sorted(
                postcommit_receipt_hashes
            ),
            "archive_total_unique_rows": metadata.get("total_unique_rows"),
            "archive_chain_sha256": metadata.get("archive_chain_sha256"),
            "integrity_checkpoint_chain_sha256": (
                archive_integrity_proof.get("archive_chain_sha256")
                if archive_integrity_proof is not None
                else None
            ),
        }
        proof.update(
            {
                "status": (
                    "VERIFIED_CANONICAL_5M_SPARSE_COVERAGE_ROWS"
                    if _allow_sparse_coverage
                    else "VERIFIED_CANONICAL_5M_LABEL_RANGE"
                ),
                "rejection_reasons": [],
                "range_sha256": stable_sha256(range_material),
                "transaction_snapshot_verified": True,
            }
        )
        return rows, proof

    def verified_coverage(
        self,
        *,
        symbol: str,
        start_close_time_ms: int,
        end_close_time_ms: int,
        training_observed_at: datetime | str | int,
        limit: int,
        archive_integrity_proof: Mapping[str, Any] | None,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Return bounded occupied rows and explicitly proven-absent slots.

        Coverage is admitted only under a current full archive integrity proof.
        The indexed read and the absence inventory share one SQLite snapshot;
        a later concurrent append can therefore only make the proof stale or
        cause an immutable append conflict, never silently overwrite authority.
        """

        coverage_proof: dict[str, Any] = {
            "schema_version": COVERAGE_PROOF_SCHEMA_VERSION,
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "symbol": str(symbol).strip().upper(),
            "start_close_time_ms": start_close_time_ms,
            "end_close_time_ms": end_close_time_ms,
            "requested_limit": limit,
            "maximum_query_rows": MAX_QUERY_ROWS,
            "maximum_query_payload_bytes": MAX_QUERY_PAYLOAD_BYTES,
            "full_integrity_proof_required": True,
            "retention_policy": RETENTION_POLICY,
            "automatic_pruning_enabled": False,
        }
        if not isinstance(archive_integrity_proof, Mapping):
            coverage_proof.update(
                {
                    "status": (
                        "BLOCKED_CANONICAL_5M_SPARSE_COVERAGE_"
                        "INTEGRITY_PROOF_REQUIRED"
                    ),
                    "rejection_reasons": [
                        "LABEL_ARCHIVE_CURRENT_FULL_INTEGRITY_PROOF_REQUIRED"
                    ],
                    "occupied_rows": 0,
                    "proven_absent_rows": 0,
                    "range_proof": None,
                }
            )
            return None, coverage_proof

        rows, range_proof = self.verified_range(
            symbol=symbol,
            start_close_time_ms=start_close_time_ms,
            end_close_time_ms=end_close_time_ms,
            training_observed_at=training_observed_at,
            limit=limit,
            archive_integrity_proof=archive_integrity_proof,
            _allow_sparse_coverage=True,
        )
        coverage_proof["range_proof"] = range_proof
        if rows is None:
            coverage_proof.update(
                {
                    "status": (
                        "BLOCKED_CANONICAL_5M_SPARSE_COVERAGE_UNVERIFIED"
                    ),
                    "rejection_reasons": list(
                        range_proof.get("rejection_reasons") or []
                    ),
                    "occupied_rows": 0,
                    "proven_absent_rows": 0,
                }
            )
            return None, coverage_proof
        if (
            range_proof.get("archive_integrity_proof_reused") is not True
            or range_proof.get("archive_integrity_proof_current") is not True
            or range_proof.get("sparse_coverage_rows_verified") is not True
        ):
            coverage_proof.update(
                {
                    "status": (
                        "BLOCKED_CANONICAL_5M_SPARSE_COVERAGE_UNVERIFIED"
                    ),
                    "rejection_reasons": [
                        "LABEL_ARCHIVE_SPARSE_COVERAGE_PROOF_NOT_CURRENT"
                    ],
                    "occupied_rows": len(rows),
                    "proven_absent_rows": 0,
                }
            )
            return None, coverage_proof

        normalized_start = int(range_proof["start_close_time_ms"])
        normalized_end = int(range_proof["end_close_time_ms"])
        expected_close_times = list(
            range(
                normalized_start,
                normalized_end + 1,
                LABEL_SLOT_MILLISECONDS,
            )
        )
        occupied_by_close = {
            int(row["candle_close_time"]): row for row in rows
        }
        absent_close_times = [
            close_ms
            for close_ms in expected_close_times
            if close_ms not in occupied_by_close
        ]
        occupied_identities = [
            {
                "symbol": str(row["symbol"]),
                "candle_close_time_ms": int(row["candle_close_time"]),
                "candle_id": str(row["candle_id"]),
                "content_sha256": hashlib.sha256(
                    canonical_json(row).encode()
                ).hexdigest(),
                "source": str(row["source"]),
                "is_backfilled": bool(row["is_backfilled"]),
            }
            for row in rows
        ]
        coverage_complete = (
            len(occupied_identities) + len(absent_close_times)
            == len(expected_close_times)
            and len(occupied_by_close) == len(rows)
        )
        if not coverage_complete:
            coverage_proof.update(
                {
                    "status": (
                        "BLOCKED_CANONICAL_5M_SPARSE_COVERAGE_UNVERIFIED"
                    ),
                    "rejection_reasons": [
                        "LABEL_ARCHIVE_SPARSE_COVERAGE_PARTITION_INVALID"
                    ],
                    "occupied_rows": len(rows),
                    "proven_absent_rows": len(absent_close_times),
                }
            )
            return None, coverage_proof

        checkpoint = {
            "archive_chain_sha256": archive_integrity_proof.get(
                "archive_chain_sha256"
            ),
            "verified_rows": archive_integrity_proof.get("verified_rows"),
            "verified_max_sequence": archive_integrity_proof.get(
                "verified_max_sequence"
            ),
            "verified_append_receipts": archive_integrity_proof.get(
                "verified_append_receipts"
            ),
            "verified_postcommit_readback_receipts": (
                archive_integrity_proof.get(
                    "verified_postcommit_readback_receipts"
                )
            ),
        }
        coverage_material = {
            "schema_version": COVERAGE_PROOF_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "symbol": str(range_proof["symbol"]),
            "start_close_time_ms": normalized_start,
            "end_close_time_ms": normalized_end,
            "expected_close_times": expected_close_times,
            "occupied_identities": occupied_identities,
            "proven_absent_close_time_ms": absent_close_times,
            "range_sha256": range_proof["range_sha256"],
            "archive_integrity_checkpoint": checkpoint,
        }
        coverage_proof.update(
            {
                "status": "VERIFIED_CANONICAL_5M_SPARSE_COVERAGE",
                "rejection_reasons": [],
                "symbol": str(range_proof["symbol"]),
                "start_close_time_ms": normalized_start,
                "end_close_time_ms": normalized_end,
                "expected_rows": len(expected_close_times),
                "occupied_rows": len(occupied_identities),
                "proven_absent_rows": len(absent_close_times),
                "occupied_identities": occupied_identities,
                "proven_absent_close_time_ms": absent_close_times,
                "coverage_partition_complete": True,
                "indexed_snapshot_verified": True,
                "archive_integrity_checkpoint": checkpoint,
                "coverage_sha256": stable_sha256(coverage_material),
            }
        )
        return rows, coverage_proof

    def verified_label_path(
        self,
        *,
        symbol: str,
        decision_time: datetime | str | int,
        training_observed_at: datetime | str | int,
        horizon_seconds: int,
        archive_integrity_proof: Mapping[str, Any] | None = None,
        require_receipt_committed_by_observation: bool = False,
        _verified_transaction_cache: set[
            tuple[str, str, str, str, int, str]
        ] | None = None,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Read the exact finalized-5m path needed by one trainer decision.

        The first row is the first canonical close strictly after the decision.
        The final row is the first canonical close at or after the requested
        outcome horizon.  Consequently, an intra-candle decision includes its
        overlapping candle for horizon returns, while downstream excursion
        logic can explicitly exclude that pre-decision overlap.
        """

        normalized_symbol = str(symbol).strip().upper()
        decision_us = _aware_epoch_us(decision_time)
        observed_us = _aware_epoch_us(training_observed_at)
        decision_ms = _aware_epoch_ms(decision_time)
        decision_ceiling_ms = _aware_epoch_ms(decision_time, ceiling=True)
        observed_ms = _aware_epoch_ms(training_observed_at)
        bounded_horizon_seconds = _strict_positive_int(horizon_seconds)
        reasons: list[str] = []
        if not _SYMBOL_RE.fullmatch(normalized_symbol):
            reasons.append("LABEL_ARCHIVE_QUERY_SYMBOL_INVALID")
        if decision_ms is None:
            reasons.append("DECISION_TIME_MISSING_OR_INVALID")
        if observed_ms is None:
            reasons.append("TRAINING_OBSERVED_AT_MISSING_OR_INVALID")
        if (
            decision_us is not None
            and observed_us is not None
            and observed_us <= decision_us
        ):
            reasons.append("TRAINING_OBSERVED_AT_NOT_AFTER_DECISION_TIME")
        if bounded_horizon_seconds is None:
            reasons.append("LABEL_HORIZON_SECONDS_MISSING_OR_INVALID")

        target_time_ms: int | None = None
        start_close_ms: int | None = None
        end_close_ms: int | None = None
        expected_rows = 0
        target_time_us: int | None = None
        if (
            decision_ms is not None
            and decision_ceiling_ms is not None
            and decision_us is not None
            and bounded_horizon_seconds is not None
        ):
            target_time_us = (
                decision_us + bounded_horizon_seconds * 1_000_000
            )
            target_time_ms = (
                target_time_us + 999
            ) // 1_000
            # Canonical closes are ``(slot multiple) - 1ms``.  These formulas
            # deliberately distinguish strict-after for the start from
            # at-or-after for the horizon endpoint.
            start_close_ms = (
                ((decision_ms + 1) // LABEL_SLOT_MILLISECONDS + 1)
                * LABEL_SLOT_MILLISECONDS
                - 1
            )
            end_close_ms = (
                ((target_time_ms + LABEL_SLOT_MILLISECONDS)
                 // LABEL_SLOT_MILLISECONDS)
                * LABEL_SLOT_MILLISECONDS
                - 1
            )
            expected_rows = (
                (end_close_ms - start_close_ms) // LABEL_SLOT_MILLISECONDS
            ) + 1
            if expected_rows <= 0 or expected_rows > MAX_QUERY_ROWS:
                reasons.append(
                    "TRAINER_LABEL_PATH_EXCEEDS_BOUNDED_ARCHIVE_QUERY"
                )

        proof: dict[str, Any] = {
            "schema_version": LABEL_PATH_PROOF_SCHEMA_VERSION,
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "symbol": normalized_symbol,
            "decision_time_epoch_us": decision_us,
            "decision_time_ms": decision_ms,
            "decision_time_ceiling_ms": decision_ceiling_ms,
            "decision_time_integer_close_comparison": (
                "FLOOR_FOR_STRICT_AFTER"
            ),
            "training_observed_at_epoch_us": observed_us,
            "training_observed_at_ms": observed_ms,
            "horizon_seconds": bounded_horizon_seconds,
            "horizon_target_time_epoch_us": target_time_us,
            "horizon_target_time_ms": target_time_ms,
            "horizon_target_integer_close_comparison": (
                "CEILING_FOR_AT_OR_AFTER"
            ),
            "start_rule": "FIRST_CANONICAL_5M_CLOSE_STRICTLY_AFTER_DECISION",
            "end_rule": "FIRST_CANONICAL_5M_CLOSE_AT_OR_AFTER_HORIZON_TARGET",
            "start_close_time_ms": start_close_ms,
            "end_close_time_ms": end_close_ms,
            "expected_rows": expected_rows,
            "maximum_query_rows": MAX_QUERY_ROWS,
        }
        if reasons:
            proof.update(
                {
                    "status": "BLOCKED_INVALID_TRAINER_LABEL_PATH_QUERY",
                    "rejection_reasons": sorted(set(reasons)),
                    "range_proof": None,
                }
            )
            return None, proof

        assert start_close_ms is not None
        assert end_close_ms is not None
        assert decision_us is not None
        assert decision_ms is not None
        assert observed_us is not None
        assert observed_ms is not None
        assert target_time_us is not None
        assert target_time_ms is not None
        rows, range_proof = self.verified_range(
            symbol=normalized_symbol,
            start_close_time_ms=start_close_ms,
            end_close_time_ms=end_close_ms,
            training_observed_at=training_observed_at,
            limit=expected_rows,
            archive_integrity_proof=archive_integrity_proof,
            _require_receipt_cutoff=(
                require_receipt_committed_by_observation
            ),
            _verified_transaction_cache=_verified_transaction_cache,
        )
        proof["range_proof"] = range_proof
        if rows is None:
            proof.update(
                {
                    "status": "BLOCKED_TRAINER_LABEL_PATH_UNVERIFIED",
                    "rejection_reasons": list(
                        range_proof.get("rejection_reasons") or []
                    ),
                }
            )
            return None, proof

        path_reasons: list[str] = []
        first_open_ms = int(rows[0]["candle_open_time"])
        first_close_ms = int(rows[0]["candle_close_time"])
        final_close_ms = int(rows[-1]["candle_close_time"])
        if not (
            first_open_ms * 1_000 <= decision_us + 1_000
            and first_close_ms * 1_000 > decision_us
        ):
            path_reasons.append("CANONICAL_5M_LABEL_PATH_START_GAP")
        horizon_lateness_us = final_close_ms * 1_000 - target_time_us
        horizon_lateness_ms = horizon_lateness_us // 1_000
        if not 0 <= horizon_lateness_us < LABEL_SLOT_MILLISECONDS * 1_000:
            path_reasons.append("CANONICAL_5M_HORIZON_ENDPOINT_INVALID")
        label_available_at_ms = max(int(row["available_at"]) for row in rows)
        if label_available_at_ms * 1_000 > observed_us:
            path_reasons.append(
                "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
            )
        proof.update(
            {
                "loaded_rows": len(rows),
                "first_candle_open_time_ms": first_open_ms,
                "first_candle_close_time_ms": first_close_ms,
                "first_candle_overlaps_decision": (
                    first_open_ms * 1_000 < decision_us
                ),
                "final_candle_close_time_ms": final_close_ms,
                "horizon_lateness_us": horizon_lateness_us,
                "horizon_lateness_ms": horizon_lateness_ms,
                "label_available_at_ms": label_available_at_ms,
                "strictly_after_decision_verified": (
                    first_close_ms * 1_000 > decision_us
                ),
                "horizon_endpoint_verified": not any(
                    reason == "CANONICAL_5M_HORIZON_ENDPOINT_INVALID"
                    for reason in path_reasons
                ),
                "pit_available_at_verified": (
                    label_available_at_ms * 1_000 <= observed_us
                ),
            }
        )
        if path_reasons:
            proof.update(
                {
                    "status": "BLOCKED_TRAINER_LABEL_PATH_UNVERIFIED",
                    "rejection_reasons": sorted(set(path_reasons)),
                }
            )
            return None, proof
        proof.update(
            {
                "status": "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH",
                "rejection_reasons": [],
                "label_path_sha256": stable_sha256(
                    {
                        "schema_version": LABEL_PATH_PROOF_SCHEMA_VERSION,
                        "symbol": normalized_symbol,
                        "decision_time_epoch_us": decision_us,
                        "decision_time_ms": decision_ms,
                        "training_observed_at_epoch_us": observed_us,
                        "training_observed_at_ms": observed_ms,
                        "horizon_seconds": bounded_horizon_seconds,
                        "horizon_target_time_epoch_us": target_time_us,
                        "horizon_target_time_ms": target_time_ms,
                        "start_close_time_ms": start_close_ms,
                        "end_close_time_ms": end_close_ms,
                        "range_sha256": range_proof["range_sha256"],
                    }
                ),
            }
        )
        return rows, proof

    def retention_status(self) -> dict[str, Any]:
        connection = self._connect_readonly()
        try:
            metadata = self._metadata(connection)
            return {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "archive_path": str(self.path),
                "retention_policy": metadata.get("retention_policy"),
                "automatic_pruning_enabled": (
                    metadata.get("automatic_pruning_enabled") != "false"
                ),
                "silent_pruning_used": False,
                "delete_api_exposed": False,
                "total_unique_rows": int(
                    metadata.get("total_unique_rows") or 0
                ),
                "archive_chain_sha256": metadata.get("archive_chain_sha256"),
            }
        finally:
            connection.close()

    def verify_integrity(self) -> dict[str, Any]:
        """Stream the archive to verify rows, chain, receipts, and metadata."""

        if not self.path.is_file():
            return {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "archive_path": str(self.path),
                "status": "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_MISSING",
                "archive_integrity_verified": False,
                "verified_rows": 0,
                "verified_max_sequence": 0,
                "verified_append_receipts": 0,
                "verified_postcommit_readback_receipts": 0,
                "append_receipt_ordering_verified": False,
                "append_receipt_order": _APPEND_RECEIPT_ORDER,
                "append_receipt_cumulative_state_verified": False,
                "postcommit_clock_causality_verified": False,
                "verified_last_commit_prepared_at": None,
                "verified_last_postcommit_readback_at": None,
                "archive_chain_sha256": None,
                "retention_policy": None,
                "automatic_pruning_enabled": None,
                "rejection_reasons": [
                    "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
                ],
            }
        try:
            connection = self._connect_readonly()
        except (OSError, sqlite3.Error, Canonical5mArchiveError) as exc:
            return {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "archive_path": str(self.path),
                "status": (
                    "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_INTEGRITY_FAILED"
                ),
                "archive_integrity_verified": False,
                "verified_rows": 0,
                "verified_max_sequence": 0,
                "verified_append_receipts": 0,
                "verified_postcommit_readback_receipts": 0,
                "append_receipt_ordering_verified": False,
                "append_receipt_order": _APPEND_RECEIPT_ORDER,
                "append_receipt_cumulative_state_verified": False,
                "postcommit_clock_causality_verified": False,
                "verified_last_commit_prepared_at": None,
                "verified_last_postcommit_readback_at": None,
                "archive_chain_sha256": None,
                "retention_policy": None,
                "automatic_pruning_enabled": None,
                "rejection_reasons": [
                    f"LABEL_ARCHIVE_OPEN_FAILED:{type(exc).__name__}"
                ],
            }
        reasons: list[str] = []
        verified_rows = 0
        verified_receipts = 0
        verified_postcommit_receipts = 0
        verified_max_sequence = 0
        verified_receipt_clocks = 0
        verified_receipt_states = 0
        total_append_receipts = 0
        previous_receipt_clock: datetime | None = None
        previous_postcommit_clock: datetime | None = None
        last_commit_prepared_at: str | None = None
        last_postcommit_readback_at: str | None = None
        expected_receipt_total = 0
        expected_receipt_chain = _GENESIS_CHAIN_SHA256
        previous_chain = _GENESIS_CHAIN_SHA256
        try:
            connection.execute("BEGIN")
            if str(connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
                reasons.append("LABEL_ARCHIVE_SQLITE_INTEGRITY_CHECK_FAILED")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                reasons.append("LABEL_ARCHIVE_SQLITE_FOREIGN_KEY_CHECK_FAILED")
            metadata = self._metadata(connection)
            if metadata.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
                reasons.append("LABEL_ARCHIVE_SCHEMA_VERSION_MISMATCH")
            required_schema_objects = {
                "canonical_5m_symbol_close_time": "index",
                "canonical_5m_append_transaction": "index",
                "canonical_5m_candles_no_update": "trigger",
                "canonical_5m_candles_no_delete": "trigger",
                "canonical_5m_receipts_no_update": "trigger",
                "canonical_5m_receipts_no_delete": "trigger",
                "canonical_5m_postcommit_receipts_no_update": "trigger",
                "canonical_5m_postcommit_receipts_no_delete": "trigger",
                "canonical_5m_payload_bytes_bounded": "trigger",
            }
            schema_objects = {
                str(row["name"]): str(row["type"])
                for row in connection.execute(
                    "SELECT name, type FROM sqlite_master "
                    "WHERE name IN (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(required_schema_objects),
                )
            }
            if schema_objects != required_schema_objects:
                reasons.append("LABEL_ARCHIVE_IMMUTABILITY_OR_INDEX_SCHEMA_MISSING")
            cursor = connection.execute(
                """
                SELECT sequence, symbol, candle_close_time_ms,
                       candle_open_time_ms,
                       available_at_ms, candle_id, raw_payload_hash,
                       market_fact_sha256, content_sha256, payload_json,
                       previous_chain_sha256, record_chain_sha256,
                       append_transaction_id
                FROM canonical_5m_candles
                ORDER BY sequence ASC
                """
            )
            while True:
                stored = cursor.fetchone()
                if stored is None:
                    break
                payload_json = str(stored["payload_json"])
                if (
                    len(payload_json.encode())
                    > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES
                ):
                    reasons.append("LABEL_ARCHIVE_ROW_PAYLOAD_BYTES_EXCEEDED")
                    break
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    reasons.append("LABEL_ARCHIVE_STORED_CANONICAL_PAYLOAD_INVALID")
                    break
                try:
                    canonical_payload_json = canonical_json(payload)
                except (TypeError, ValueError):
                    reasons.append("LABEL_ARCHIVE_STORED_CANONICAL_PAYLOAD_INVALID")
                    break
                if canonical_payload_json != payload_json:
                    reasons.append("LABEL_ARCHIVE_PAYLOAD_NOT_CANONICAL_JSON")
                    break
                content_hash = hashlib.sha256(
                    canonical_payload_json.encode()
                ).hexdigest()
                if content_hash != str(stored["content_sha256"]):
                    reasons.append("LABEL_ARCHIVE_CONTENT_SHA256_MISMATCH")
                    break
                try:
                    validated = validate_canonical_finalized_5m_candle(payload)
                except Canonical5mValidationError:
                    reasons.append("LABEL_ARCHIVE_STORED_CANONICAL_PAYLOAD_INVALID")
                    break
                if (
                    str(stored["symbol"]) != validated["symbol"]
                    or int(stored["candle_close_time_ms"])
                    != validated["close_time_ms"]
                    or int(stored["candle_open_time_ms"])
                    != validated["open_time_ms"]
                    or int(stored["available_at_ms"])
                    != validated["available_at_ms"]
                    or str(stored["candle_id"]) != validated["candle_id"]
                    or str(stored["raw_payload_hash"])
                    != validated["raw_payload_hash"]
                    or str(stored["market_fact_sha256"])
                    != validated["market_fact_sha256"]
                ):
                    reasons.append("LABEL_ARCHIVE_INDEX_PAYLOAD_IDENTITY_MISMATCH")
                    break
                if str(stored["previous_chain_sha256"]) != previous_chain:
                    reasons.append("LABEL_ARCHIVE_CHAIN_PREDECESSOR_MISMATCH")
                    break
                expected_chain = self._record_chain_sha256(
                    previous_chain_sha256=previous_chain,
                    validated=validated,
                    append_transaction_id=str(
                        stored["append_transaction_id"]
                    ),
                )
                if expected_chain != str(stored["record_chain_sha256"]):
                    reasons.append("LABEL_ARCHIVE_RECORD_CHAIN_SHA256_MISMATCH")
                    break
                previous_chain = expected_chain
                verified_rows += 1
                verified_max_sequence = int(stored["sequence"])
            missing_receipts = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM canonical_5m_candles AS candle
                    LEFT JOIN canonical_5m_append_receipts AS receipt
                      ON receipt.transaction_id = candle.append_transaction_id
                    WHERE receipt.transaction_id IS NULL
                    """
                ).fetchone()[0]
            )
            if missing_receipts:
                reasons.append("LABEL_ARCHIVE_APPEND_RECEIPT_MISSING")
            missing_postcommit_receipts = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM canonical_5m_append_receipts AS receipt
                    LEFT JOIN canonical_5m_postcommit_readback_receipts AS post
                      ON post.transaction_id = receipt.transaction_id
                    WHERE post.transaction_id IS NULL
                    """
                ).fetchone()[0]
            )
            if missing_postcommit_receipts:
                reasons.append(
                    "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
                )
            total_append_receipts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_append_receipts"
                ).fetchone()[0]
            )
            receipt_cursor = connection.execute(
                """
                SELECT transaction_id, receipt_schema_version, batch_sha256,
                       attempted_rows, inserted_rows, duplicate_rows,
                       total_unique_rows, archive_chain_sha256, receipt_sha256,
                       receipt_json, commit_prepared_at,
                       precommit_readback_verified
                FROM canonical_5m_append_receipts
                ORDER BY commit_prepared_at ASC
                """
            )
            while True:
                receipt = receipt_cursor.fetchone()
                if receipt is None:
                    break
                receipt_reasons = self._append_receipt_rejection_reasons(
                    receipt
                )
                if receipt_reasons:
                    reasons.extend(receipt_reasons)
                    break
                receipt_clock = _canonical_utc_millisecond(
                    receipt["commit_prepared_at"]
                )
                if receipt_clock is None:
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_COMMIT_PREPARED_AT_"
                        "NOT_CANONICAL_UTC_MILLISECOND"
                    )
                    break
                if (
                    previous_receipt_clock is not None
                    and receipt_clock <= previous_receipt_clock
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_COMMIT_PREPARED_AT_"
                        "NOT_STRICTLY_INCREASING"
                    )
                    break
                if (
                    previous_postcommit_clock is not None
                    and receipt_clock <= previous_postcommit_clock
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_NOT_AFTER_PRIOR_"
                        "POSTCOMMIT_READBACK"
                    )
                    break
                previous_receipt_clock = receipt_clock
                last_commit_prepared_at = str(receipt["commit_prepared_at"])
                verified_receipt_clocks += 1
                transaction_rows = connection.execute(
                    """
                    SELECT sequence, symbol, candle_close_time_ms,
                           content_sha256, previous_chain_sha256,
                           record_chain_sha256
                    FROM canonical_5m_candles
                    WHERE append_transaction_id = ?
                    ORDER BY sequence ASC
                    LIMIT ?
                    """,
                    (
                        str(receipt["transaction_id"]),
                        MAX_APPEND_ROWS + 1,
                    ),
                ).fetchall()
                inserted_rows = int(receipt["inserted_rows"])
                if len(transaction_rows) != inserted_rows:
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_INSERTED_ROWS_MISMATCH"
                    )
                    break
                prior_expected_total = expected_receipt_total
                expected_receipt_total += inserted_rows
                if int(receipt["total_unique_rows"]) != expected_receipt_total:
                    reasons.append(
                        "LABEL_ARCHIVE_APPEND_RECEIPT_CUMULATIVE_TOTAL_MISMATCH"
                    )
                    break
                receipt_chain = str(receipt["archive_chain_sha256"])
                if transaction_rows:
                    first_transaction_row = transaction_rows[0]
                    last_transaction_row = transaction_rows[-1]
                    if (
                        int(first_transaction_row["sequence"])
                        != prior_expected_total + 1
                        or int(last_transaction_row["sequence"])
                        != expected_receipt_total
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_APPEND_RECEIPT_SEQUENCE_TRANSITION_"
                            "MISMATCH"
                        )
                        break
                    if (
                        str(first_transaction_row["previous_chain_sha256"])
                        != expected_receipt_chain
                        or str(last_transaction_row["record_chain_sha256"])
                        != receipt_chain
                    ):
                        reasons.append(
                            "LABEL_ARCHIVE_APPEND_RECEIPT_CHAIN_TRANSITION_"
                            "MISMATCH"
                        )
                        break
                elif receipt_chain != expected_receipt_chain:
                    reasons.append(
                        "LABEL_ARCHIVE_DUPLICATE_ONLY_RECEIPT_CHAIN_CHANGED"
                    )
                    break
                expected_receipt_chain = receipt_chain
                verified_receipt_states += 1
                verified_receipts += 1
                identities = [
                    (
                        str(identity["symbol"]),
                        int(identity["candle_close_time_ms"]),
                        str(identity["content_sha256"]),
                    )
                    for identity in transaction_rows
                ]
                postcommit = connection.execute(
                    """
                    SELECT transaction_id, readback_schema_version,
                           append_receipt_sha256, inserted_rows,
                           inserted_identities_sha256,
                           readback_receipt_sha256,
                           readback_receipt_json, postcommit_readback_at
                    FROM canonical_5m_postcommit_readback_receipts
                    WHERE transaction_id = ?
                    """,
                    (str(receipt["transaction_id"]),),
                ).fetchone()
                if postcommit is None:
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING"
                    )
                    break
                postcommit_reasons = (
                    self._postcommit_receipt_rejection_reasons(postcommit)
                )
                if postcommit_reasons:
                    reasons.extend(postcommit_reasons)
                    break
                postcommit_clock = _canonical_utc_millisecond(
                    postcommit["postcommit_readback_at"]
                )
                if postcommit_clock is None or postcommit_clock < receipt_clock:
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_BEFORE_COMMIT_PREPARED"
                    )
                    break
                if (
                    previous_postcommit_clock is not None
                    and postcommit_clock <= previous_postcommit_clock
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_AT_"
                        "NOT_STRICTLY_INCREASING"
                    )
                    break
                if (
                    str(postcommit["append_receipt_sha256"])
                    != str(receipt["receipt_sha256"])
                    or int(postcommit["inserted_rows"]) != len(identities)
                    or str(postcommit["inserted_identities_sha256"])
                    != self._inserted_identities_sha256(identities)
                ):
                    reasons.append(
                        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_BINDING_MISMATCH"
                    )
                    break
                previous_postcommit_clock = postcommit_clock
                last_postcommit_readback_at = str(
                    postcommit["postcommit_readback_at"]
                )
                verified_postcommit_receipts += 1
            if expected_receipt_total != verified_rows:
                reasons.append(
                    "LABEL_ARCHIVE_APPEND_RECEIPT_CUMULATIVE_FINAL_TOTAL_"
                    "MISMATCH"
                )
            if expected_receipt_chain != previous_chain:
                reasons.append(
                    "LABEL_ARCHIVE_APPEND_RECEIPT_FINAL_CHAIN_MISMATCH"
                )
            if int(metadata.get("total_unique_rows") or 0) != verified_rows:
                reasons.append("LABEL_ARCHIVE_TOTAL_UNIQUE_ROWS_MISMATCH")
            if metadata.get("archive_chain_sha256") != previous_chain:
                reasons.append("LABEL_ARCHIVE_FINAL_CHAIN_SHA256_MISMATCH")
            if metadata.get("retention_policy") != RETENTION_POLICY:
                reasons.append("LABEL_ARCHIVE_RETENTION_POLICY_MISMATCH")
            if metadata.get("automatic_pruning_enabled") != "false":
                reasons.append("LABEL_ARCHIVE_AUTOMATIC_PRUNING_ENABLED")
            connection.commit()
        finally:
            connection.close()
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_path": str(self.path),
            "status": (
                "VERIFIED_CANONICAL_5M_LABEL_ARCHIVE"
                if not reasons
                else "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_INTEGRITY_FAILED"
            ),
            "archive_integrity_verified": not reasons,
            "verified_rows": verified_rows,
            "verified_max_sequence": verified_max_sequence,
            "verified_append_receipts": verified_receipts,
            "verified_postcommit_readback_receipts": (
                verified_postcommit_receipts
            ),
            "append_receipt_ordering_verified": (
                verified_receipt_clocks == total_append_receipts
            ),
            "append_receipt_order": _APPEND_RECEIPT_ORDER,
            "append_receipt_cumulative_state_verified": (
                verified_receipt_states == total_append_receipts
                and expected_receipt_total == verified_rows
                and expected_receipt_chain == previous_chain
            ),
            "postcommit_clock_causality_verified": (
                verified_postcommit_receipts == total_append_receipts
            ),
            "verified_last_commit_prepared_at": last_commit_prepared_at,
            "verified_last_postcommit_readback_at": (
                last_postcommit_readback_at
            ),
            "archive_chain_sha256": previous_chain,
            "retention_policy": metadata.get("retention_policy"),
            "automatic_pruning_enabled": (
                metadata.get("automatic_pruning_enabled") != "false"
            ),
            "verification_memory_bound": (
                "STREAMING_ONE_CANDLE_OR_RECEIPT_PLUS_JSON_PAYLOAD"
            ),
            "rejection_reasons": sorted(set(reasons)),
        }
