"""Runtime publisher for authenticated, quarantined 35-feature profile records.

The publisher is intentionally narrower than a trainer or prediction service.
It discovers symbols from the intersection of the canonical Binance closed
``5m`` and ``1h`` Redis keys, captures their exact bytes with the existing
atomic receipt adapter, and durably records both source captures before it
computes or publishes a feature record.  Published records use
``profiled_model_feature_snapshot_record_v1`` and therefore grant no trainer,
prediction, paper, or live authority.

Symbol coverage rotates by least-recent attempted publication, while successful
coverage is tracked independently.  Per-cycle
work is derived from observed local evidence bytes, observed symbol latency,
the configured service cadence, and current disk headroom above an immutable
shared-filesystem reserve.  The sole bootstrap estimate is the measured 4.9 MB
per symbol supplied by the runtime audit; after observations exist it is not
used.  No market, confidence, return, leverage, or performance threshold
participates in selection.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AuthenticatedOhlcvProfileTransformV1Error,
    transform_authenticated_ohlcv_profile_v1,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicCaptureError,
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    CanonicalOhlcvMultitimeframeCaptureSetV1Error,
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
    canonical_ohlcv_multitimeframe_capture_set_v1_contract,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotAppendResult,
    FeatureSnapshotLedgerError,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    ProfiledModelFeatureSnapshotRecordV1Error,
    build_profiled_model_feature_snapshot_record_v1,
    validate_profiled_model_feature_snapshot_record_v1,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    MAX_LEDGER_BYTES,
    MAX_LEDGER_ENTRIES,
    MAX_LEDGER_ENTRY_BYTES,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
    TrainerSourceProvenanceAppendResultV4,
    TrainerSourceProvenanceLedgerV4,
    TrainerSourceProvenanceLedgerV4Error,
)

PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION: Final = "profiled_base_feature_publisher_v1"
PROFILED_BASE_FEATURE_PUBLISHER_STATE_V1_SCHEMA_VERSION: Final = (
    "profiled_base_feature_publisher_state_v1"
)
PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION: Final = (
    "profiled_base_feature_publisher_status_v1"
)
PROFILED_BASE_FEATURE_PUBLISHER_RUN_ID: Final = "profiled-base-publisher-v1"
CANONICAL_KEY_PREFIX: Final = "v2:market:ohlcv_closed:binance:"
REQUIRED_TIMEFRAMES: Final = ("5m", "1h")

# Resource-integrity limits only.  They never classify a market observation.
BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL: Final = 4_900_000
MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS: Final = 90 * 24 * 60 * 60
DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS: Final = (
    MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS
)
MAX_DISCOVERY_KEYS: Final = 100_000
MAX_STATE_BYTES: Final = 16 * 1024 * 1024
MAX_WRITER_LOCK_METADATA_BYTES: Final = 4 * 1024
WRITER_LOCK_FILENAME: Final = ".profiled_base_feature_publisher_v1.writer.lock"
SOURCE_ENTRY_ACCOUNTING_OVERHEAD_BYTES: Final = 1024 * 1024
DISK_RESERVE_PUBLICATION_UNITS: Final = 2
DISK_RESERVE_TOTAL_FRACTION_NUMERATOR: Final = 1
DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR: Final = 5
DISK_RESERVE_POLICY_V1: Final = (
    "MAX_TWO_ESTIMATED_PUBLICATION_UNITS_OR_CEILING_ONE_FIFTH_TOTAL_DISK"
)
SOURCE_SHARD_RE = re.compile(r"^shard-([0-9]{8})$", re.ASCII)
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,48}$", re.ASCII)
CLOCK_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"
BOUNDARY_REASON_FRAGMENTS: Final = (
    "STALE_OR_UNFINISHED",
    "LATEST_FINALIZED",
    "EXPECTED_FINALIZED",
    "TAIL_IS_STALE",
    "CROSS_TIMEFRAME",
    "AVAILABLE_AFTER_GENERATED",
    "SOURCE_AVAILABLE_AFTER_CONSUMER",
    "PUBLICATION_CLOCK_ORDER",
)
AUTHORITY_FIELDS: Final = (
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)
DECISION_TIMEFRAME: Final = "5m"
MAX_DECISION_WAIT_CHUNK_SECONDS: Final = 1.0
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class ProfiledBaseFeaturePublisherV1Error(RuntimeError):
    """Base fail-closed publisher error containing stable reason codes."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons)) or ("PUBLISHER_FAILURE",)
        super().__init__(";".join(self.reasons))


class ProfiledBaseFeaturePublisherV1ConfigurationError(ProfiledBaseFeaturePublisherV1Error):
    """A path, cadence, dependency, or clock cannot satisfy the contract."""


class ProfiledBaseFeaturePublisherV1StateError(ProfiledBaseFeaturePublisherV1Error):
    """Mutable rotation/status state could not be safely read or persisted."""


class ProfiledBaseFeaturePublisherV1ResourceError(ProfiledBaseFeaturePublisherV1Error):
    """A bounded disk or source-ledger safety limit prevented publication."""


def _fail(error: type[ProfiledBaseFeaturePublisherV1Error], *reasons: str) -> NoReturn:
    raise error(*reasons) from None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clock_text(value: datetime, *, reason: str) -> str:
    if type(value) is not datetime or value.tzinfo is not UTC:
        _fail(ProfiledBaseFeaturePublisherV1ConfigurationError, reason)
    return value.strftime(CLOCK_FORMAT)


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str:
        _fail(ProfiledBaseFeaturePublisherV1StateError, reason)
    try:
        parsed = datetime.strptime(value, CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail(ProfiledBaseFeaturePublisherV1StateError, reason)
    if parsed.strftime(CLOCK_FORMAT) != value:
        _fail(ProfiledBaseFeaturePublisherV1StateError, reason)
    return parsed


def prospective_decision_midpoint_v1(generated_at: datetime) -> datetime:
    """Choose a future decision strictly inside the current 5m interval.

    Keeping the decision before the next close means the already captured
    finalized suffix remains the exact latest suffix at that decision.  The
    midpoint leaves a clock-derived half-interval for transform/record
    construction without inventing a market or performance threshold.
    """

    if type(generated_at) is not datetime or generated_at.tzinfo is not UTC:
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_DECISION_PLANNER_CLOCK_INVALID",
        )
    interval_us = TIMEFRAME_DURATION_MS[DECISION_TIMEFRAME] * 1_000
    elapsed = generated_at - _EPOCH
    generated_us = (
        elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds
    )
    next_boundary_us = (generated_us // interval_us + 1) * interval_us
    remaining_us = next_boundary_us - generated_us
    if remaining_us < 2:
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_NO_PROSPECTIVE_DECISION_WINDOW",
        )
    decision_us = generated_us + remaining_us // 2
    decision = _EPOCH + timedelta(microseconds=decision_us)
    boundary = _EPOCH + timedelta(microseconds=next_boundary_us)
    if not generated_at < decision < boundary:
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_DECISION_PLANNER_RESULT_INVALID",
        )
    return decision


def wait_for_prospective_decision_v1(
    decision_at: datetime,
    *,
    clock: Callable[[], datetime] = _utc_now,
    sleeper: Callable[[float], None] = time.sleep,
) -> datetime:
    """Wait in bounded chunks and reject a wall-clock rollback."""

    if (
        type(decision_at) is not datetime
        or decision_at.tzinfo is not UTC
        or not callable(clock)
        or not callable(sleeper)
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_DECISION_WAIT_INPUT_INVALID",
        )
    try:
        observed = clock()
    except Exception as exc:  # noqa: BLE001 - clock detail is not evidence
        raise ProfiledBaseFeaturePublisherV1ConfigurationError(
            "PROFILED_BASE_PUBLISHER_DECISION_WAIT_CLOCK_FAILED"
        ) from exc
    _clock_text(
        observed,
        reason="PROFILED_BASE_PUBLISHER_DECISION_WAIT_CLOCK_INVALID",
    )
    while observed < decision_at:
        remaining = (decision_at - observed).total_seconds()
        try:
            sleeper(min(MAX_DECISION_WAIT_CHUNK_SECONDS, remaining))
            current = clock()
        except Exception as exc:  # noqa: BLE001 - wait detail is not evidence
            raise ProfiledBaseFeaturePublisherV1ConfigurationError(
                "PROFILED_BASE_PUBLISHER_DECISION_WAIT_FAILED"
            ) from exc
        _clock_text(
            current,
            reason="PROFILED_BASE_PUBLISHER_DECISION_WAIT_CLOCK_INVALID",
        )
        if current < observed:
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_DECISION_WAIT_CLOCK_MOVED_BACKWARDS",
            )
        observed = current
    return observed


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_JSON_ENCODING_FAILED",
        )


def _strict_path(path: Path, *, reason: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        _fail(ProfiledBaseFeaturePublisherV1ConfigurationError, reason)
    return path


def _initial_state() -> dict[str, Any]:
    return {
        "schema_version": PROFILED_BASE_FEATURE_PUBLISHER_STATE_V1_SCHEMA_VERSION,
        "coverage": {},
        "rotation_last_attempted_at": {},
        "observations": {
            "cycle_count": 0,
            "materialized_publication_count": 0,
            "materialized_publication_elapsed_seconds": 0.0,
            "materialized_publication_bytes": 0,
        },
    }


def _validate_state(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "coverage",
        "rotation_last_attempted_at",
        "observations",
    }:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_FIELDS_INVALID",
        )
    state = cast(dict[str, Any], value)
    if state["schema_version"] != PROFILED_BASE_FEATURE_PUBLISHER_STATE_V1_SCHEMA_VERSION:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_SCHEMA_INVALID",
        )
    coverage = state["coverage"]
    rotation = state["rotation_last_attempted_at"]
    observations = state["observations"]
    if (
        type(coverage) is not dict
        or type(rotation) is not dict
        or type(observations) is not dict
        or set(observations)
        != {
            "cycle_count",
            "materialized_publication_count",
            "materialized_publication_elapsed_seconds",
            "materialized_publication_bytes",
        }
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_SHAPE_INVALID",
        )
    for name in (
        "cycle_count",
        "materialized_publication_count",
        "materialized_publication_bytes",
    ):
        if type(observations[name]) is not int or observations[name] < 0:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_STATE_OBSERVATION_INVALID",
            )
    elapsed = observations["materialized_publication_elapsed_seconds"]
    if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_OBSERVATION_INVALID",
        )
    for symbol, item in coverage.items():
        if (
            type(symbol) is not str
            or SYMBOL_RE.fullmatch(symbol) is None
            or type(item) is not dict
            or set(item)
            != {
                "last_published_at",
                "feature_cutoff",
                "decision_time",
                "window_fingerprint_sha256",
                "durable_snapshot_id",
                "record_sha256",
            }
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_STATE_COVERAGE_INVALID",
            )
        _parse_clock(
            item["last_published_at"],
            reason="PROFILED_BASE_PUBLISHER_STATE_COVERAGE_CLOCK_INVALID",
        )
        _parse_clock(
            item["feature_cutoff"],
            reason="PROFILED_BASE_PUBLISHER_STATE_COVERAGE_CLOCK_INVALID",
        )
        _parse_clock(
            item["decision_time"],
            reason="PROFILED_BASE_PUBLISHER_STATE_COVERAGE_CLOCK_INVALID",
        )
        for field_name in (
            "window_fingerprint_sha256",
            "durable_snapshot_id",
            "record_sha256",
        ):
            field_value = item[field_name]
            if type(field_value) is not str or not field_value:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_STATE_COVERAGE_IDENTITY_INVALID",
                )
    for symbol, attempted_at in rotation.items():
        if type(symbol) is not str or SYMBOL_RE.fullmatch(symbol) is None:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_STATE_ROTATION_INVALID",
            )
        _parse_clock(
            attempted_at,
            reason="PROFILED_BASE_PUBLISHER_STATE_ROTATION_CLOCK_INVALID",
        )
    return state


def _load_state(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _initial_state()
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(
            "PROFILED_BASE_PUBLISHER_STATE_READ_FAILED"
        ) from exc
    if not raw or len(raw) > MAX_STATE_BYTES or b"\r" in raw or not raw.endswith(b"\n"):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_FRAMING_INVALID",
        )
    try:
        parsed = json.loads(raw[:-1].decode("ascii", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_JSON_INVALID",
        )
    if _canonical_json_bytes(parsed) + b"\n" != raw:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_STATE_NOT_CANONICAL",
        )
    return _validate_state(parsed)


def _atomic_write_json(path: Path, value: object, *, failure_reason: str) -> None:
    payload = _canonical_json_bytes(value) + b"\n"
    if len(payload) > MAX_STATE_BYTES:
        _fail(ProfiledBaseFeaturePublisherV1StateError, failure_reason)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink():
            _fail(ProfiledBaseFeaturePublisherV1StateError, failure_reason)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", buffering=0, closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        if path.read_bytes() != payload:
            _fail(ProfiledBaseFeaturePublisherV1StateError, failure_reason)
    except ProfiledBaseFeaturePublisherV1Error:
        raise
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(failure_reason) from exc


@contextmanager
def _singleton_writer_lock(data_root: Path) -> Iterator[dict[str, Any]]:
    """Hold the sole state/shard/publication writer capability for one cycle."""

    try:
        root_stat = os.lstat(data_root)
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1ResourceError(
            "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_ROOT_STAT_FAILED"
        ) from exc
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or root_stat.st_uid != os.geteuid()
        or stat.S_IMODE(root_stat.st_mode) & 0o022
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1ResourceError,
            "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_ROOT_UNSAFE",
        )
    lock_path = data_root / WRITER_LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    locked = False
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        root_descriptor = os.open(
            data_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(lock_path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or stat.S_IMODE(descriptor_stat.st_mode) != 0o600
            or stat.S_IMODE(path_stat.st_mode) != 0o600
            or descriptor_stat.st_uid != os.geteuid()
            or path_stat.st_uid != os.geteuid()
            or descriptor_stat.st_nlink != 1
            or path_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_IDENTITY_INVALID",
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SINGLETON_WRITER_LOCK_CONTENDED",
            )
        locked = True
        metadata: dict[str, Any] = {
            "schema_version": "profiled_base_publisher_singleton_writer_lock_v1",
            "acquired_at": _clock_text(
                _utc_now(),
                reason="PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_CLOCK_INVALID",
            ),
            "owner_pid": os.getpid(),
            "data_root_sha256": hashlib.sha256(os.fsencode(str(data_root))).hexdigest(),
            "state_shard_and_publication_writer_exclusive": True,
        }
        payload = _canonical_json_bytes(metadata) + b"\n"
        if len(payload) > MAX_WRITER_LOCK_METADATA_BYTES:
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_METADATA_TOO_LARGE",
            )
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                _fail(
                    ProfiledBaseFeaturePublisherV1ResourceError,
                    "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_METADATA_WRITE_FAILED",
                )
            written += count
        os.fsync(descriptor)
        final_descriptor_stat = os.fstat(descriptor)
        final_path_stat = os.lstat(lock_path)
        if (final_descriptor_stat.st_dev, final_descriptor_stat.st_ino) != (
            final_path_stat.st_dev,
            final_path_stat.st_ino,
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_IDENTITY_CHANGED",
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, MAX_WRITER_LOCK_METADATA_BYTES + 1) != payload:
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_METADATA_READBACK_FAILED",
            )
        yield metadata
    except ProfiledBaseFeaturePublisherV1Error:
        raise
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1ResourceError(
            "PROFILED_BASE_PUBLISHER_SINGLETON_LOCK_OPERATION_FAILED"
        ) from exc
    finally:
        if descriptor >= 0:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _error_reasons(exc: BaseException) -> tuple[str, ...]:
    raw = getattr(exc, "reasons", None)
    if type(raw) is tuple and raw and all(type(item) is str for item in raw):
        return cast(tuple[str, ...], raw)
    if isinstance(
        exc,
        ProfiledBaseFeaturePublisherV1Error
        | CanonicalOhlcvAtomicCaptureError
        | CanonicalOhlcvMultitimeframeCaptureSetV1Error
        | AuthenticatedOhlcvProfileTransformV1Error
        | ProfiledModelFeatureSnapshotRecordV1Error
        | TrainerSourceProvenanceLedgerV4Error
        | FeatureSnapshotLedgerError
        | SourcePayloadStoreError,
    ):
        text = str(exc)
        if text:
            return tuple(dict.fromkeys(part for part in text.split(";") if part))
    return (f"PROFILED_BASE_PUBLISHER_UNEXPECTED_{type(exc).__name__.upper()}",)


def _boundary_related(reasons: Iterable[str]) -> bool:
    normalized = tuple(reason.upper() for reason in reasons)
    return any(
        fragment in reason for reason in normalized for fragment in BOUNDARY_REASON_FRAGMENTS
    )


@dataclass(frozen=True, slots=True)
class PublisherResourceDecisionV1:
    discovered_eligible_count: int
    selected_count: int
    estimated_evidence_bytes_per_symbol: int
    estimated_seconds_per_symbol: float
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    disk_reserve_policy: str
    disk_reserve_publication_units: int
    disk_reserve_total_fraction_numerator: int
    disk_reserve_total_fraction_denominator: int
    disk_reserve_bytes: int
    safe_disk_headroom_bytes: int
    resource_sustainability_horizon_seconds: float
    sustainable_cycle_write_budget_bytes: int
    absolute_disk_capacity_symbols: int
    disk_capacity_symbols: int
    publication_latency_capacity_symbols: int
    bootstrap_observation_required: bool
    reasons: tuple[str, ...]

    @property
    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": "profiled_base_publisher_resource_decision_v1",
            "discovered_eligible_count": self.discovered_eligible_count,
            "selected_count": self.selected_count,
            "estimated_evidence_bytes_per_symbol": (self.estimated_evidence_bytes_per_symbol),
            "estimated_seconds_per_symbol": self.estimated_seconds_per_symbol,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_used_bytes": self.disk_used_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_reserve_policy": self.disk_reserve_policy,
            "disk_reserve_publication_units": self.disk_reserve_publication_units,
            "disk_reserve_total_fraction_numerator": (self.disk_reserve_total_fraction_numerator),
            "disk_reserve_total_fraction_denominator": (
                self.disk_reserve_total_fraction_denominator
            ),
            "disk_reserve_bytes": self.disk_reserve_bytes,
            "safe_disk_headroom_bytes": self.safe_disk_headroom_bytes,
            "resource_sustainability_horizon_seconds": (
                self.resource_sustainability_horizon_seconds
            ),
            "sustainable_cycle_write_budget_bytes": (self.sustainable_cycle_write_budget_bytes),
            "absolute_disk_capacity_symbols": self.absolute_disk_capacity_symbols,
            "disk_capacity_symbols": self.disk_capacity_symbols,
            "publication_latency_capacity_symbols": (self.publication_latency_capacity_symbols),
            "bootstrap_observation_required": self.bootstrap_observation_required,
            "reasons": list(self.reasons),
            "market_performance_thresholds_applied": False,
        }


def adaptive_resource_decision_v1(
    *,
    eligible_count: int,
    observations: Mapping[str, Any],
    cycle_period_seconds: float,
    resource_sustainability_horizon_seconds: float,
    disk_total_bytes: int,
    disk_used_bytes: int,
    disk_free_bytes: int,
) -> PublisherResourceDecisionV1:
    """Choose an evidence-bound workload without a symbol or market cap."""

    if (
        type(eligible_count) is not int
        or eligible_count < 0
        or type(cycle_period_seconds) not in {int, float}
        or not math.isfinite(cycle_period_seconds)
        or cycle_period_seconds <= 0
        or type(resource_sustainability_horizon_seconds) not in {int, float}
        or not math.isfinite(resource_sustainability_horizon_seconds)
        or resource_sustainability_horizon_seconds < MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS
        or any(
            type(value) is not int or value < 0
            for value in (disk_total_bytes, disk_used_bytes, disk_free_bytes)
        )
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_RESOURCE_INPUT_INVALID",
        )
    publication_count = observations.get("materialized_publication_count")
    publication_elapsed = observations.get("materialized_publication_elapsed_seconds")
    publication_bytes = observations.get("materialized_publication_bytes")
    if (
        type(publication_count) is not int
        or publication_count < 0
        or type(publication_elapsed) not in {int, float}
        or not math.isfinite(publication_elapsed)
        or publication_elapsed < 0
        or type(publication_bytes) is not int
        or publication_bytes < 0
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_RESOURCE_OBSERVATION_INVALID",
        )
    bootstrap = publication_count == 0 or publication_bytes == 0
    estimated_bytes = (
        BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL
        if publication_count == 0 or publication_bytes == 0
        else max(1, math.ceil(publication_bytes / publication_count))
    )
    estimated_seconds = (
        float(cycle_period_seconds)
        if publication_count == 0 or publication_elapsed == 0
        else max(
            float.fromhex("0x1.0p-20"),
            float(publication_elapsed) / publication_count,
        )
    )
    publication_unit_reserve = estimated_bytes * DISK_RESERVE_PUBLICATION_UNITS
    total_disk_fraction_reserve = (
        disk_total_bytes * DISK_RESERVE_TOTAL_FRACTION_NUMERATOR
        + DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR
        - 1
    ) // DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR
    reserve = max(publication_unit_reserve, total_disk_fraction_reserve)
    safe_headroom = max(0, disk_free_bytes - reserve)
    absolute_disk_capacity = safe_headroom // estimated_bytes
    sustainable_cycle_budget = math.floor(
        safe_headroom
        * min(cycle_period_seconds, resource_sustainability_horizon_seconds)
        / resource_sustainability_horizon_seconds
    )
    disk_capacity = min(
        absolute_disk_capacity,
        sustainable_cycle_budget // estimated_bytes,
    )
    latency_capacity = max(1, math.floor(cycle_period_seconds / estimated_seconds))
    selected = min(eligible_count, disk_capacity, latency_capacity)
    reasons = [
        "LEAST_RECENTLY_COVERED_ROTATION",
        "IMMUTABLE_SHARED_FILESYSTEM_RESERVE_APPLIED",
        "SUSTAINABLE_DISK_HORIZON_DERIVED_WRITE_BUDGET",
        "MATERIALIZED_PUBLICATION_LATENCY_DERIVED_WORKLOAD",
    ]
    reasons.append(
        "BOOTSTRAP_MEASURED_4_9MB_EVIDENCE_COST"
        if bootstrap
        else "LOCAL_MATERIALIZED_PUBLICATION_BYTES_AND_LATENCY_OBSERVATIONS"
    )
    if selected == disk_capacity and selected < eligible_count:
        reasons.append("DISK_HEADROOM_BINDING")
    if selected == latency_capacity and selected < eligible_count:
        reasons.append("CYCLE_LATENCY_BINDING")
    if selected == 0:
        reasons.append("RESOURCE_HEADROOM_NO_SAFE_PUBLICATION_UNIT")
    return PublisherResourceDecisionV1(
        discovered_eligible_count=eligible_count,
        selected_count=selected,
        estimated_evidence_bytes_per_symbol=estimated_bytes,
        estimated_seconds_per_symbol=estimated_seconds,
        disk_total_bytes=disk_total_bytes,
        disk_used_bytes=disk_used_bytes,
        disk_free_bytes=disk_free_bytes,
        disk_reserve_policy=DISK_RESERVE_POLICY_V1,
        disk_reserve_publication_units=DISK_RESERVE_PUBLICATION_UNITS,
        disk_reserve_total_fraction_numerator=(DISK_RESERVE_TOTAL_FRACTION_NUMERATOR),
        disk_reserve_total_fraction_denominator=(DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR),
        disk_reserve_bytes=reserve,
        safe_disk_headroom_bytes=safe_headroom,
        resource_sustainability_horizon_seconds=float(resource_sustainability_horizon_seconds),
        sustainable_cycle_write_budget_bytes=sustainable_cycle_budget,
        absolute_disk_capacity_symbols=absolute_disk_capacity,
        disk_capacity_symbols=disk_capacity,
        publication_latency_capacity_symbols=latency_capacity,
        bootstrap_observation_required=bootstrap,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class _Discovery:
    discovered_symbols: tuple[str, ...]
    eligible_symbols: tuple[str, ...]
    missing_timeframes: tuple[tuple[str, tuple[str, ...]], ...]
    rejected_key_sha256s: tuple[str, ...]


def discover_canonical_profile_symbols_v1(redis_client: object) -> _Discovery:
    """Discover the exact 5m/1h key intersection without reading feature values."""

    scan = getattr(redis_client, "scan_iter", None)
    if not callable(scan):
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_REDIS_SCAN_UNAVAILABLE",
        )
    by_symbol: dict[str, set[str]] = {}
    rejected: list[str] = []
    try:
        observed_keys = 0
        for required_timeframe in REQUIRED_TIMEFRAMES:
            iterator = scan(
                match=(CANONICAL_KEY_PREFIX + f"*:{required_timeframe}").encode("ascii"),
                count=512,
            )
            for raw_key in iterator:
                observed_keys += 1
                if observed_keys > MAX_DISCOVERY_KEYS:
                    _fail(
                        ProfiledBaseFeaturePublisherV1ResourceError,
                        "PROFILED_BASE_PUBLISHER_DISCOVERY_KEY_LIMIT_EXCEEDED",
                    )
                if type(raw_key) is not bytes:
                    _fail(
                        ProfiledBaseFeaturePublisherV1ConfigurationError,
                        "PROFILED_BASE_PUBLISHER_REDIS_RAW_MODE_REQUIRED",
                    )
                try:
                    key = raw_key.decode("ascii", errors="strict")
                except UnicodeDecodeError:
                    rejected.append(hashlib.sha256(raw_key).hexdigest())
                    continue
                parts = key.split(":")
                if (
                    len(parts) != 6
                    or parts[:4] != ["v2", "market", "ohlcv_closed", "binance"]
                    or SYMBOL_RE.fullmatch(parts[4]) is None
                    or parts[5] != required_timeframe
                ):
                    rejected.append(hashlib.sha256(raw_key).hexdigest())
                    continue
                by_symbol.setdefault(parts[4], set()).add(parts[5])
    except ProfiledBaseFeaturePublisherV1Error:
        raise
    except Exception as exc:  # noqa: BLE001 - transport detail must not escape
        raise ProfiledBaseFeaturePublisherV1Error(
            "PROFILED_BASE_PUBLISHER_REDIS_DISCOVERY_FAILED"
        ) from exc
    discovered = tuple(sorted(by_symbol))
    required = set(REQUIRED_TIMEFRAMES)
    eligible = tuple(symbol for symbol in discovered if by_symbol[symbol] == required)
    missing = tuple(
        (symbol, tuple(sorted(required - by_symbol[symbol])))
        for symbol in discovered
        if by_symbol[symbol] != required
    )
    return _Discovery(
        discovered_symbols=discovered,
        eligible_symbols=eligible,
        missing_timeframes=missing,
        rejected_key_sha256s=tuple(sorted(set(rejected))),
    )


def least_recently_covered_symbols_v1(
    eligible_symbols: Iterable[str],
    coverage: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return stable fair rotation order; never privilege a hardcoded symbol."""

    symbols = tuple(sorted(set(eligible_symbols)))

    def key(symbol: str) -> tuple[int, str, str]:
        item = coverage.get(symbol)
        if type(item) is str:
            return (1, item, symbol)
        if type(item) is not dict:
            return (0, "", symbol)
        clock = item.get("last_published_at")
        if type(clock) is not str:
            return (0, "", symbol)
        return (1, clock, symbol)

    return tuple(sorted(symbols, key=key))


def _capture_projected_entry_bytes(capture: CanonicalOhlcvAtomicReceiptCapture) -> int:
    try:
        exact_source = capture.exact_full_source_payload_bytes
        selected = capture.selected_candles
    except CanonicalOhlcvAtomicCaptureError:
        raise
    selected_receipt_bytes = sum(
        len(row.source_read_receipt.receipt_json.encode("ascii")) for row in selected
    )
    projected = (
        len(exact_source)
        + len(capture.suffix_manifest_json.encode("ascii"))
        + len(capture.atomic_batch_material_json.encode("ascii"))
        + selected_receipt_bytes
        + SOURCE_ENTRY_ACCOUNTING_OVERHEAD_BYTES
    )
    if projected > MAX_LEDGER_ENTRY_BYTES:
        _fail(
            ProfiledBaseFeaturePublisherV1ResourceError,
            "PROFILED_BASE_PUBLISHER_SOURCE_ENTRY_PROJECTED_LIMIT_EXCEEDED",
        )
    return projected


def select_source_shard_index_v1(
    *,
    active_index: int | None,
    active_ledger_bytes: int,
    active_ledger_entries: int,
    projected_pair_bytes: int,
) -> tuple[int, bool]:
    """Choose the current or next deterministic source-ledger shard."""

    if (active_index is not None and (type(active_index) is not int or active_index < 0)) or any(
        type(value) is not int or value < 0
        for value in (
            active_ledger_bytes,
            active_ledger_entries,
            projected_pair_bytes,
        )
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            "PROFILED_BASE_PUBLISHER_SOURCE_SHARD_INPUT_INVALID",
        )
    if projected_pair_bytes > MAX_LEDGER_BYTES:
        _fail(
            ProfiledBaseFeaturePublisherV1ResourceError,
            "PROFILED_BASE_PUBLISHER_SOURCE_PAIR_PROJECTED_LIMIT_EXCEEDED",
        )
    if active_index is None:
        return 0, False
    fits = (
        active_ledger_bytes + projected_pair_bytes <= MAX_LEDGER_BYTES
        and active_ledger_entries + len(REQUIRED_TIMEFRAMES) <= MAX_LEDGER_ENTRIES
    )
    return (active_index, False) if fits else (active_index + 1, True)


@dataclass(frozen=True, slots=True)
class _SymbolOutcome:
    symbol: str
    classification: str
    window_fingerprint_sha256: str
    materialized_evidence_bytes: int
    detail: dict[str, Any]
    coverage: dict[str, Any] | None


class ProfiledBaseFeaturePublisherV1:
    """One-cycle orchestrator with per-symbol isolation and durable rotation state."""

    def __init__(
        self,
        *,
        redis_client: object,
        data_root: Path,
        feature_ledger_path: Path,
        cycle_period_seconds: float,
        resource_sustainability_horizon_seconds: float = (
            DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS
        ),
        state_path: Path | None = None,
        status_path: Path | None = None,
        boundary_retry_limit: int = 2,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
        decision_planner: Callable[[datetime], datetime] = (prospective_decision_midpoint_v1),
        decision_waiter: Callable[[datetime], datetime] | None = None,
        capture_function: Callable[..., CanonicalOhlcvAtomicReceiptCapture] = (
            capture_canonical_closed_ohlcv_atomic_receipts
        ),
        capture_set_builder: Callable[..., Any] = (
            build_canonical_ohlcv_multitimeframe_capture_set_v1
        ),
    ) -> None:
        self.redis_client = redis_client
        self.data_root = _strict_path(
            data_root,
            reason="PROFILED_BASE_PUBLISHER_DATA_ROOT_INVALID",
        )
        self.feature_ledger_path = _strict_path(
            feature_ledger_path,
            reason="PROFILED_BASE_PUBLISHER_FEATURE_LEDGER_PATH_INVALID",
        )
        self.state_path = _strict_path(
            state_path or self.data_root / "profiled_base_publisher_state_v1.json",
            reason="PROFILED_BASE_PUBLISHER_STATE_PATH_INVALID",
        )
        self.status_path = _strict_path(
            status_path or self.data_root / "profiled_base_publisher_status_v1.json",
            reason="PROFILED_BASE_PUBLISHER_STATUS_PATH_INVALID",
        )
        if (
            type(cycle_period_seconds) not in {int, float}
            or not math.isfinite(cycle_period_seconds)
            or cycle_period_seconds <= 0
            or type(resource_sustainability_horizon_seconds) not in {int, float}
            or not math.isfinite(resource_sustainability_horizon_seconds)
            or resource_sustainability_horizon_seconds
            < MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS
            or type(boundary_retry_limit) is not int
            or boundary_retry_limit < 1
            or boundary_retry_limit > 8
            or not callable(clock)
            or not callable(monotonic)
            or not callable(disk_usage)
            or not callable(decision_planner)
            or (decision_waiter is not None and not callable(decision_waiter))
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_CONFIGURATION_INVALID",
            )
        self.cycle_period_seconds = float(cycle_period_seconds)
        self.resource_sustainability_horizon_seconds = float(
            resource_sustainability_horizon_seconds
        )
        self.boundary_retry_limit = boundary_retry_limit
        self.clock = clock
        self.monotonic = monotonic
        self.disk_usage = disk_usage
        self.decision_planner = decision_planner
        self.decision_waiter = decision_waiter or (
            lambda decision_at: wait_for_prospective_decision_v1(
                decision_at,
                clock=self.clock,
            )
        )
        self.capture_function = capture_function
        self.capture_set_builder = capture_set_builder

    def _sample_clock(self, reason: str) -> tuple[datetime, str]:
        try:
            value = self.clock()
        except Exception as exc:  # noqa: BLE001 - hostile clock detail is suppressed
            raise ProfiledBaseFeaturePublisherV1ConfigurationError(reason) from exc
        return value, _clock_text(value, reason=reason)

    def _stores(
        self,
    ) -> tuple[
        ImmutableSourcePayloadStore,
        ImmutableSourcePayloadStore,
        ImmutableSourcePayloadStore,
    ]:
        return (
            ImmutableSourcePayloadStore(self.data_root / "atomic-capture-cas"),
            ImmutableSourcePayloadStore(self.data_root / "capture-set-cas"),
            ImmutableSourcePayloadStore(self.data_root / "profiled-model-evidence-cas"),
        )

    def _disk_sample(self) -> tuple[int, int, int]:
        try:
            usage = self.disk_usage(self.data_root)
            values = (int(usage.total), int(usage.used), int(usage.free))
        except Exception as exc:  # noqa: BLE001 - platform detail must not escape
            raise ProfiledBaseFeaturePublisherV1ResourceError(
                "PROFILED_BASE_PUBLISHER_DISK_USAGE_SAMPLE_FAILED"
            ) from exc
        if any(value < 0 for value in values):
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_DISK_USAGE_SAMPLE_INVALID",
            )
        return values

    def _source_ledger(
        self,
        captures: tuple[
            CanonicalOhlcvAtomicReceiptCapture,
            CanonicalOhlcvAtomicReceiptCapture,
        ],
    ) -> tuple[TrainerSourceProvenanceLedgerV4, int, bool, int]:
        projected_pair = sum(_capture_projected_entry_bytes(item) for item in captures)
        root = self.data_root / "source-provenance-shards"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        observed: list[int] = []
        for item in root.iterdir():
            match = SOURCE_SHARD_RE.fullmatch(item.name)
            if match is None:
                _fail(
                    ProfiledBaseFeaturePublisherV1ResourceError,
                    "PROFILED_BASE_PUBLISHER_SOURCE_SHARD_INVENTORY_INVALID",
                )
            if not item.is_dir() or item.is_symlink():
                _fail(
                    ProfiledBaseFeaturePublisherV1ResourceError,
                    "PROFILED_BASE_PUBLISHER_SOURCE_SHARD_INVENTORY_INVALID",
                )
            observed.append(int(match.group(1)))
        observed.sort()
        if observed and observed != list(range(observed[-1] + 1)):
            _fail(
                ProfiledBaseFeaturePublisherV1ResourceError,
                "PROFILED_BASE_PUBLISHER_SOURCE_SHARD_SEQUENCE_INVALID",
            )
        active = observed[-1] if observed else None
        active_bytes = 0
        active_entries = 0
        if active is not None:
            active_root = root / f"shard-{active:08d}"
            ledger = TrainerSourceProvenanceLedgerV4(active_root)
            active_entries = len(ledger.read_entries())
            try:
                ledger_path = active_root / TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME
                active_bytes = ledger_path.stat().st_size if ledger_path.exists() else 0
            except OSError as exc:
                raise ProfiledBaseFeaturePublisherV1ResourceError(
                    "PROFILED_BASE_PUBLISHER_SOURCE_LEDGER_STAT_FAILED"
                ) from exc
        index, rolled = select_source_shard_index_v1(
            active_index=active,
            active_ledger_bytes=active_bytes,
            active_ledger_entries=active_entries,
            projected_pair_bytes=projected_pair,
        )
        return (
            TrainerSourceProvenanceLedgerV4(root / f"shard-{index:08d}"),
            index,
            rolled,
            projected_pair,
        )

    @staticmethod
    def _window_fingerprint(
        symbol: str,
        captures: tuple[
            CanonicalOhlcvAtomicReceiptCapture,
            CanonicalOhlcvAtomicReceiptCapture,
        ],
    ) -> str:
        return stable_sha256(
            {
                "schema_version": "profiled_base_finalized_window_fingerprint_v1",
                "symbol": symbol,
                "timeframes": [
                    {
                        "timeframe": timeframe,
                        "suffix_digest_sha256": capture.suffix_digest_sha256,
                        "latest_candle_id": capture.selected_candle_ids[-1],
                    }
                    for timeframe, capture in zip(
                        REQUIRED_TIMEFRAMES,
                        captures,
                        strict=True,
                    )
                ],
            }
        )

    def _capture_and_build_set(
        self,
        *,
        symbol: str,
        source_store: ImmutableSourcePayloadStore,
        capture_set_store: ImmutableSourcePayloadStore,
        prior_fingerprint: str | None,
    ) -> tuple[
        tuple[CanonicalOhlcvAtomicReceiptCapture, CanonicalOhlcvAtomicReceiptCapture],
        str,
        Any,
        dict[str, Any],
        int,
        datetime | None,
    ]:
        last_reasons: tuple[str, ...] = ()
        for attempt in range(1, self.boundary_retry_limit + 1):
            try:
                captures = cast(
                    tuple[
                        CanonicalOhlcvAtomicReceiptCapture,
                        CanonicalOhlcvAtomicReceiptCapture,
                    ],
                    tuple(
                        self.capture_function(
                            self.redis_client,
                            source_store,
                            expected_symbol=symbol,
                            expected_timeframe=timeframe,
                            consumer_clock=self.clock,
                        )
                        for timeframe in REQUIRED_TIMEFRAMES
                    ),
                )
                fingerprint = self._window_fingerprint(symbol, captures)
                if prior_fingerprint == fingerprint:
                    return captures, fingerprint, None, {}, attempt, None
                generated_at, generated = self._sample_clock(
                    "PROFILED_BASE_PUBLISHER_CAPTURE_GENERATED_CLOCK_INVALID"
                )
                try:
                    decision_at = self.decision_planner(generated_at)
                except ProfiledBaseFeaturePublisherV1Error:
                    raise
                except Exception as exc:  # noqa: BLE001 - planner detail is suppressed
                    raise ProfiledBaseFeaturePublisherV1ConfigurationError(
                        "PROFILED_BASE_PUBLISHER_DECISION_PLANNER_FAILED"
                    ) from exc
                decision = _clock_text(
                    decision_at,
                    reason="PROFILED_BASE_PUBLISHER_DECISION_CLOCK_INVALID",
                )
                if decision_at < generated_at:
                    _fail(
                        ProfiledBaseFeaturePublisherV1ConfigurationError,
                        "PROFILED_BASE_PUBLISHER_DECISION_BEFORE_CAPTURE_GENERATED",
                    )
                capture_set = self.capture_set_builder(
                    profile=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
                    atomic_captures=captures,
                    capture_set_store=capture_set_store,
                    generated_at=generated,
                    decision_time=decision,
                )
                contract = canonical_ohlcv_multitimeframe_capture_set_v1_contract(capture_set)
                return captures, fingerprint, capture_set, contract, attempt, decision_at
            except (
                CanonicalOhlcvAtomicCaptureError,
                CanonicalOhlcvMultitimeframeCaptureSetV1Error,
            ) as exc:
                last_reasons = _error_reasons(exc)
                if not _boundary_related(last_reasons) or attempt >= self.boundary_retry_limit:
                    raise
        raise ProfiledBaseFeaturePublisherV1Error(
            "PROFILED_BASE_PUBLISHER_BOUNDARY_RETRY_EXHAUSTED",
            *last_reasons,
        )

    def _publish_symbol_once(
        self,
        *,
        symbol: str,
        prior_coverage: Mapping[str, Any] | None,
        source_store: ImmutableSourcePayloadStore,
        capture_set_store: ImmutableSourcePayloadStore,
        artifact_store: ImmutableSourcePayloadStore,
        feature_ledger: DurableFeatureSnapshotLedger,
    ) -> _SymbolOutcome:
        prior_fingerprint = (
            cast(str, prior_coverage.get("window_fingerprint_sha256"))
            if prior_coverage is not None
            and type(prior_coverage.get("window_fingerprint_sha256")) is str
            else None
        )
        captures, fingerprint, capture_set, contract, attempts, decision_at = (
            self._capture_and_build_set(
                symbol=symbol,
                source_store=source_store,
                capture_set_store=capture_set_store,
                prior_fingerprint=prior_fingerprint,
            )
        )
        if capture_set is None:
            return _SymbolOutcome(
                symbol=symbol,
                classification="UNCHANGED_FINALIZED_WINDOWS",
                window_fingerprint_sha256=fingerprint,
                materialized_evidence_bytes=0,
                detail={
                    "symbol": symbol,
                    "classification": "UNCHANGED_FINALIZED_WINDOWS",
                    "boundary_attempts": attempts,
                    "window_fingerprint_sha256": fingerprint,
                    "authority": {name: False for name in AUTHORITY_FIELDS},
                },
                coverage=None,
            )
        if decision_at is None:
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_DECISION_MISSING_FOR_CHANGED_WINDOW",
            )

        source_ledger, shard_index, rolled, projected_pair = self._source_ledger(captures)
        append_results: list[TrainerSourceProvenanceAppendResultV4] = []
        for timeframe, capture in zip(REQUIRED_TIMEFRAMES, captures, strict=True):
            cycle_digest = stable_sha256(
                {
                    "schema_version": "profiled_base_source_cycle_v1",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
                    "suffix_digest_sha256": capture.suffix_digest_sha256,
                }
            )
            append_results.append(
                source_ledger.append_atomic_capture(
                    capture,
                    trainer_run_id=PROFILED_BASE_FEATURE_PUBLISHER_RUN_ID,
                    trainer_cycle_id=f"base35:{symbol}:{timeframe}:{cycle_digest}",
                    ledger_clock=self.clock,
                )
            )
        source_entries = cast(
            tuple[Any, Any],
            tuple(result.entry for result in append_results),
        )
        transformed = transform_authenticated_ohlcv_profile_v1(
            contract,
            expected_capture_set_sha256=contract["capture_set_sha256"],
        )
        _, transform_available_at = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_TRANSFORM_AVAILABLE_CLOCK_INVALID"
        )
        _, record_generated_at = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_RECORD_GENERATED_CLOCK_INVALID"
        )
        record = build_profiled_model_feature_snapshot_record_v1(
            transform_result=transformed,
            capture_set_contract=contract,
            capture_set_store=capture_set_store,
            artifact_store=artifact_store,
            source_provenance_ledger=source_ledger,
            source_provenance_entries=source_entries,
            transform_available_at=transform_available_at,
            generated_at=record_generated_at,
        )
        validation = validate_profiled_model_feature_snapshot_record_v1(
            record,
            transform_result=transformed,
            capture_set_contract=contract,
            capture_set_store=capture_set_store,
            artifact_store=artifact_store,
            source_provenance_ledger=source_ledger,
            source_provenance_entries=source_entries,
        )
        existing_snapshot = (
            feature_ledger.get_snapshot(validation.durable_snapshot_id)
            if feature_ledger.path.is_file()
            else None
        )
        if existing_snapshot is not None and existing_snapshot.record != record:
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                "PROFILED_BASE_PUBLISHER_EXISTING_SNAPSHOT_CONTENT_MISMATCH",
            )
        try:
            decision_wait_completed_at = self.decision_waiter(decision_at)
        except ProfiledBaseFeaturePublisherV1Error:
            raise
        except Exception as exc:  # noqa: BLE001 - waiter detail is suppressed
            raise ProfiledBaseFeaturePublisherV1ConfigurationError(
                "PROFILED_BASE_PUBLISHER_DECISION_WAITER_FAILED"
            ) from exc
        decision_wait_completed = _clock_text(
            decision_wait_completed_at,
            reason="PROFILED_BASE_PUBLISHER_DECISION_WAIT_RESULT_INVALID",
        )
        if decision_wait_completed_at < decision_at:
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_APPEND_BEFORE_PROSPECTIVE_DECISION",
            )
        feature_append: FeatureSnapshotAppendResult = feature_ledger.append_snapshot(record)
        if (
            feature_append.transaction_committed is not True
            or feature_append.transaction_readback_verified is not True
            or any(getattr(validation, name) is not False for name in AUTHORITY_FIELDS)
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                "PROFILED_BASE_PUBLISHER_POSTCOMMIT_OR_AUTHORITY_INVALID",
            )
        envelope = cast(dict[str, Any], record["frozen_envelope"])
        classification = (
            "AUTHENTICATED_QUARANTINED_BASE_INSERTED"
            if existing_snapshot is None and feature_append.inserted_rows == 1
            else "AUTHENTICATED_QUARANTINED_BASE_EXACT_REPLAY"
        )
        source_ledger_entries_after = len(source_ledger.read_entries())
        source_ledger_bytes_after = source_ledger.path.stat().st_size
        materialized_evidence_bytes = (
            projected_pair
            + int(capture_set.capture_set_manifest_byte_count)
            + len(transformed.artifact_json.encode("ascii"))
            + len(_canonical_json_bytes(record))
            + sum(len(result.entry.entry_json.encode("ascii")) for result in append_results)
        )
        charged_materialized_evidence_bytes = (
            materialized_evidence_bytes
            if classification == "AUTHENTICATED_QUARANTINED_BASE_INSERTED"
            else 0
        )
        source_details = [
            {
                "timeframe": timeframe,
                "ledger_sequence": result.entry.ledger_sequence,
                "entry_sha256": result.entry.entry_sha256,
                "replay_identity_sha256": result.entry.replay_identity_sha256,
                "cycle_identity_sha256": result.entry.cycle_identity_sha256,
                "disposition": result.disposition,
                "durable_postcommit_readback_verified": (
                    result.durable_postcommit_readback_verified
                ),
            }
            for timeframe, result in zip(REQUIRED_TIMEFRAMES, append_results, strict=True)
        ]
        detail = {
            "symbol": symbol,
            "classification": classification,
            "boundary_attempts": attempts,
            "window_fingerprint_sha256": fingerprint,
            "event_time": contract["timestamps"]["event_time"],
            "ingested_at": contract["timestamps"]["ingested_at"],
            "available_at": contract["timestamps"]["available_at"],
            "capture_generated_at": contract["timestamps"]["generated_at"],
            "feature_cutoff": envelope["feature_cutoff"],
            "decision_time": envelope["tensor_decision_time"],
            "decision_wait_completed_at": decision_wait_completed,
            "prospective_decision_wait_verified": True,
            "transform_available_at": transform_available_at,
            "record_generated_at": envelope["generated_at"],
            "execution_time": contract["timestamps"]["execution_time"],
            "capture_set_sha256": validation.capture_set_sha256,
            "transform_artifact_sha256": validation.transform_artifact_sha256,
            "durable_snapshot_id": validation.durable_snapshot_id,
            "record_sha256": validation.record_sha256,
            "frozen_envelope_sha256": validation.frozen_envelope_sha256,
            "source_lineage_sha256": validation.source_lineage_sha256,
            "physical_model_vector_sha256": validation.physical_model_vector_sha256,
            "logical_model_vector_sha256": (validation.logical_projection.model_vector_sha256),
            "lineage_binding_sha256": validation.lineage_binding_sha256,
            "source_provenance_shard_index": shard_index,
            "source_provenance_shard_rolled": rolled,
            "source_pair_projected_ledger_bytes": projected_pair,
            "materialized_evidence_bytes": charged_materialized_evidence_bytes,
            "source_ledger_entries_after": source_ledger_entries_after,
            "source_ledger_entry_limit": MAX_LEDGER_ENTRIES,
            "source_ledger_remaining_entries": (MAX_LEDGER_ENTRIES - source_ledger_entries_after),
            "source_ledger_bytes_after": source_ledger_bytes_after,
            "source_ledger_byte_limit": MAX_LEDGER_BYTES,
            "source_ledger_remaining_bytes": (MAX_LEDGER_BYTES - source_ledger_bytes_after),
            "source_appends": source_details,
            "feature_append": {
                "transaction_id": feature_append.transaction_id,
                "batch_sha256": feature_append.batch_sha256,
                "inserted_rows": feature_append.inserted_rows,
                "duplicate_rows": feature_append.duplicate_rows,
                "total_unique_rows": feature_append.total_unique_rows,
                "archive_chain_sha256": feature_append.archive_chain_sha256,
                "append_receipt_sha256": feature_append.append_receipt_sha256,
                "postcommit_receipt_sha256": feature_append.postcommit_receipt_sha256,
                "postcommit_readback_at": feature_append.postcommit_readback_at,
                "transaction_committed": feature_append.transaction_committed,
                "transaction_readback_verified": (feature_append.transaction_readback_verified),
            },
            "authority": {name: False for name in AUTHORITY_FIELDS},
            "legacy_feature_redis_write_performed": False,
        }
        coverage = {
            "last_published_at": feature_append.postcommit_readback_at,
            "feature_cutoff": envelope["feature_cutoff"],
            "decision_time": envelope["tensor_decision_time"],
            "window_fingerprint_sha256": fingerprint,
            "durable_snapshot_id": validation.durable_snapshot_id,
            "record_sha256": validation.record_sha256,
        }
        return _SymbolOutcome(
            symbol=symbol,
            classification=classification,
            window_fingerprint_sha256=fingerprint,
            materialized_evidence_bytes=charged_materialized_evidence_bytes,
            detail=detail,
            coverage=coverage,
        )

    def _publish_symbol(
        self,
        *,
        symbol: str,
        prior_coverage: Mapping[str, Any] | None,
        source_store: ImmutableSourcePayloadStore,
        capture_set_store: ImmutableSourcePayloadStore,
        artifact_store: ImmutableSourcePayloadStore,
        feature_ledger: DurableFeatureSnapshotLedger,
    ) -> _SymbolOutcome:
        """Retry the whole finalized-window capture if a decision window is missed."""

        last_reasons: tuple[str, ...] = ()
        for attempt in range(1, self.boundary_retry_limit + 1):
            try:
                outcome = self._publish_symbol_once(
                    symbol=symbol,
                    prior_coverage=prior_coverage,
                    source_store=source_store,
                    capture_set_store=capture_set_store,
                    artifact_store=artifact_store,
                    feature_ledger=feature_ledger,
                )
                return _SymbolOutcome(
                    symbol=outcome.symbol,
                    classification=outcome.classification,
                    window_fingerprint_sha256=outcome.window_fingerprint_sha256,
                    materialized_evidence_bytes=outcome.materialized_evidence_bytes,
                    detail={**outcome.detail, "publication_attempts": attempt},
                    coverage=outcome.coverage,
                )
            except ProfiledModelFeatureSnapshotRecordV1Error as exc:
                last_reasons = _error_reasons(exc)
                missed = any(
                    "PUBLICATION_CLOCK_ORDER_INVALID" in reason.upper() for reason in last_reasons
                )
                if not missed or attempt >= self.boundary_retry_limit:
                    raise
        raise ProfiledBaseFeaturePublisherV1Error(
            "PROFILED_BASE_PUBLISHER_PROSPECTIVE_DECISION_RETRY_EXHAUSTED",
            *last_reasons,
        )

    def run_cycle(self) -> dict[str, Any]:
        """Run one cycle under the exclusive state, shard, and publication lock."""

        self.data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with _singleton_writer_lock(self.data_root) as lock_metadata:
            return self._run_cycle_locked(lock_metadata=lock_metadata)

    def _run_cycle_locked(self, *, lock_metadata: dict[str, Any]) -> dict[str, Any]:
        """Run one bounded cycle after singleton-writer acquisition."""

        cycle_started_dt, cycle_started = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_CYCLE_START_CLOCK_INVALID"
        )
        monotonic_start = self.monotonic()
        state = _load_state(self.state_path)
        discovery = discover_canonical_profile_symbols_v1(self.redis_client)
        _, discovery_completed = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_DISCOVERY_CLOCK_INVALID"
        )
        disk_total, disk_used, disk_free = self._disk_sample()
        decision = adaptive_resource_decision_v1(
            eligible_count=len(discovery.eligible_symbols),
            observations=cast(dict[str, Any], state["observations"]),
            cycle_period_seconds=self.cycle_period_seconds,
            resource_sustainability_horizon_seconds=(self.resource_sustainability_horizon_seconds),
            disk_total_bytes=disk_total,
            disk_used_bytes=disk_used,
            disk_free_bytes=disk_free,
        )
        rotation = least_recently_covered_symbols_v1(
            discovery.eligible_symbols,
            cast(dict[str, Any], state["rotation_last_attempted_at"]),
        )
        planned_selection = rotation[: decision.selected_count]
        _, selection_at = self._sample_clock("PROFILED_BASE_PUBLISHER_SELECTION_CLOCK_INVALID")

        if planned_selection:
            source_store, capture_set_store, artifact_store = self._stores()
            feature_ledger: DurableFeatureSnapshotLedger | None = DurableFeatureSnapshotLedger(
                self.feature_ledger_path
            )
        else:
            source_store = capture_set_store = artifact_store = None
            feature_ledger = None
        published: list[dict[str, Any]] = []
        replayed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        selected: list[str] = []
        resource_deferred: list[str] = []
        failures: list[dict[str, Any]] = [
            {
                "symbol": symbol,
                "stage": "DISCOVERY_ELIGIBILITY",
                "reasons": ["MISSING_REQUIRED_TIMEFRAME:" + ",".join(missing)],
                "missing_timeframes": list(missing),
                "retryable": True,
            }
            for symbol, missing in discovery.missing_timeframes
        ]
        coverage = cast(dict[str, Any], state["coverage"])
        rotation_last_attempted = cast(
            dict[str, str],
            state["rotation_last_attempted_at"],
        )
        materialized_publication_elapsed = 0.0
        materialized_cycle_evidence_bytes = 0
        materialized_cycle_publication_count = 0
        cycle_disk_consumption_high_water = 0
        cycle_start_disk_free = disk_free
        for selection_index, symbol in enumerate(planned_selection):
            _current_total, _current_used, current_disk_free = self._disk_sample()
            cycle_disk_consumption_high_water = max(
                cycle_disk_consumption_high_water,
                max(0, cycle_start_disk_free - current_disk_free),
            )
            current_cycle_bytes = max(
                materialized_cycle_evidence_bytes,
                cycle_disk_consumption_high_water,
            )
            effective_next_publication_bytes = max(
                decision.estimated_evidence_bytes_per_symbol,
                (
                    math.ceil(
                        materialized_cycle_evidence_bytes / materialized_cycle_publication_count
                    )
                    if materialized_cycle_publication_count > 0
                    else 0
                ),
            )
            if (
                current_cycle_bytes + effective_next_publication_bytes
                > decision.sustainable_cycle_write_budget_bytes
            ):
                resource_deferred.extend(planned_selection[selection_index:])
                break
            selected.append(symbol)
            rotation_last_attempted[symbol] = selection_at
            symbol_started = self.monotonic()
            materialized = False
            try:
                if (
                    source_store is None
                    or capture_set_store is None
                    or artifact_store is None
                    or feature_ledger is None
                ):
                    _fail(
                        ProfiledBaseFeaturePublisherV1Error,
                        "PROFILED_BASE_PUBLISHER_SELECTED_WITHOUT_STORES",
                    )
                prior = coverage.get(symbol)
                outcome = self._publish_symbol(
                    symbol=symbol,
                    prior_coverage=prior if type(prior) is dict else None,
                    source_store=source_store,
                    capture_set_store=capture_set_store,
                    artifact_store=artifact_store,
                    feature_ledger=feature_ledger,
                )
                if outcome.classification == "UNCHANGED_FINALIZED_WINDOWS":
                    skipped.append(outcome.detail)
                elif outcome.classification.endswith("EXACT_REPLAY"):
                    replayed.append(outcome.detail)
                else:
                    published.append(outcome.detail)
                    materialized = True
                    materialized_cycle_evidence_bytes += outcome.materialized_evidence_bytes
                    materialized_cycle_publication_count += 1
                if outcome.coverage is not None:
                    coverage[symbol] = outcome.coverage
            except Exception as exc:  # noqa: BLE001 - isolate every symbol
                reasons = _error_reasons(exc)
                failures.append(
                    {
                        "symbol": symbol,
                        "stage": "AUTHENTICATED_BASE_PUBLICATION",
                        "reasons": list(reasons),
                        "retryable": isinstance(
                            exc,
                            CanonicalOhlcvAtomicCaptureError
                            | CanonicalOhlcvMultitimeframeCaptureSetV1Error
                            | TrainerSourceProvenanceLedgerV4Error
                            | FeatureSnapshotLedgerError,
                        ),
                        "boundary_or_finality_related": _boundary_related(reasons),
                    }
                )
            finally:
                elapsed = self.monotonic() - symbol_started
                if type(elapsed) in {int, float} and math.isfinite(elapsed) and elapsed >= 0:
                    if materialized:
                        materialized_publication_elapsed += float(elapsed)

        _final_total, _final_used, final_disk_free = self._disk_sample()
        cycle_disk_consumption_high_water = max(
            cycle_disk_consumption_high_water,
            max(0, cycle_start_disk_free - final_disk_free),
        )
        evidence_delta = max(
            materialized_cycle_evidence_bytes,
            cycle_disk_consumption_high_water,
        )
        observations = cast(dict[str, Any], state["observations"])
        observations["cycle_count"] += 1
        if published:
            observations["materialized_publication_count"] += len(published)
            observations["materialized_publication_elapsed_seconds"] = (
                float(observations["materialized_publication_elapsed_seconds"])
                + materialized_publication_elapsed
            )
            # The deterministic authenticated-artifact accounting is floored
            # by the cycle's observed filesystem-free-space high-water delta.
            # Unchanged/replay-only cycles cannot dilute the publication mean.
            observations["materialized_publication_bytes"] += evidence_delta
        _atomic_write_json(
            self.state_path,
            state,
            failure_reason="PROFILED_BASE_PUBLISHER_STATE_WRITE_FAILED",
        )

        cycle_completed_dt, cycle_completed = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_CYCLE_COMPLETE_CLOCK_INVALID"
        )
        total_elapsed = self.monotonic() - monotonic_start
        if (
            type(total_elapsed) not in {int, float}
            or not math.isfinite(total_elapsed)
            or total_elapsed < 0
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_MONOTONIC_CLOCK_INVALID",
            )
        if cycle_completed_dt < cycle_started_dt:
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_WALL_CLOCK_MOVED_BACKWARDS",
            )
        coverage_status: dict[str, Any] = {}
        for symbol in discovery.eligible_symbols:
            item = coverage.get(symbol)
            if type(item) is not dict:
                coverage_status[symbol] = {
                    "last_published_at": None,
                    "coverage_age_seconds": None,
                    "feature_cutoff": None,
                    "durable_snapshot_id": None,
                }
                continue
            last = _parse_clock(
                item["last_published_at"],
                reason="PROFILED_BASE_PUBLISHER_COVERAGE_CLOCK_INVALID",
            )
            coverage_status[symbol] = {
                "last_published_at": item["last_published_at"],
                "coverage_age_seconds": max(
                    0.0,
                    (cycle_completed_dt - last).total_seconds(),
                ),
                "feature_cutoff": item["feature_cutoff"],
                "durable_snapshot_id": item["durable_snapshot_id"],
            }
        selected_failure_count = sum(
            1 for failure in failures if failure["symbol"] in set(selected)
        )
        status_classification = (
            "NO_ELIGIBLE_SYMBOLS"
            if not discovery.eligible_symbols
            else "RESOURCE_HEADROOM_HOLD"
            if not selected and not resource_deferred
            else "CYCLE_WRITE_BUDGET_BACKPRESSURE_HOLD"
            if not selected and resource_deferred
            else "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"
            if selected_failure_count > 0
            else "CYCLE_COMPLETE_RESOURCE_BACKPRESSURE_DEFERRED"
            if resource_deferred
            else "CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED"
        )
        status: dict[str, Any] = {
            "schema_version": PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION,
            "publisher_schema_version": PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION,
            "classification": status_classification,
            "cycle_started_at": cycle_started,
            "discovery_completed_at": discovery_completed,
            "selection_at": selection_at,
            "cycle_completed_at": cycle_completed,
            "cycle_elapsed_seconds": float(total_elapsed),
            "cycle_period_seconds": self.cycle_period_seconds,
            "resource_sustainability_horizon_seconds": (
                self.resource_sustainability_horizon_seconds
            ),
            "discovered_symbol_count": len(discovery.discovered_symbols),
            "discovered_symbols": list(discovery.discovered_symbols),
            "eligible_symbol_count": len(discovery.eligible_symbols),
            "eligible_symbols": list(discovery.eligible_symbols),
            "selected_symbol_count": len(selected),
            "selected_symbols": list(selected),
            "resource_deferred_symbol_count": len(resource_deferred),
            "resource_deferred_symbols": resource_deferred,
            "published_symbol_count": len(published),
            "published_symbols": [item["symbol"] for item in published],
            "exact_replay_symbol_count": len(replayed),
            "exact_replay_symbols": [item["symbol"] for item in replayed],
            "unchanged_symbol_count": len(skipped),
            "unchanged_symbols": [item["symbol"] for item in skipped],
            "failed_symbol_count": len(failures),
            "failed_symbols": sorted({item["symbol"] for item in failures}),
            "rejected_discovery_key_sha256s": list(discovery.rejected_key_sha256s),
            "resource_decision": decision.contract,
            "disk_resource_safety": {
                "policy": decision.disk_reserve_policy,
                "reserve_bytes": decision.disk_reserve_bytes,
                "reserve_publication_units": decision.disk_reserve_publication_units,
                "reserve_total_fraction_numerator": (
                    decision.disk_reserve_total_fraction_numerator
                ),
                "reserve_total_fraction_denominator": (
                    decision.disk_reserve_total_fraction_denominator
                ),
                "free_bytes_at_cycle_start": decision.disk_free_bytes,
                "safe_headroom_bytes_at_cycle_start": decision.safe_disk_headroom_bytes,
                "operational_invariant_not_market_selection": True,
            },
            "cycle_evidence_accounted_bytes": evidence_delta,
            "cycle_materialized_artifact_bytes": materialized_cycle_evidence_bytes,
            "cycle_materialized_publication_count": (materialized_cycle_publication_count),
            "cycle_disk_consumption_high_water_bytes": (cycle_disk_consumption_high_water),
            "evidence_accounting_method": (
                "MAX_DETERMINISTIC_AUTHENTICATED_ARTIFACT_BYTES_AND_"
                "FILESYSTEM_FREE_SPACE_HIGH_WATER"
            ),
            "coverage": coverage_status,
            "rotation_last_attempted_at": {
                symbol: rotation_last_attempted.get(symbol) for symbol in discovery.eligible_symbols
            },
            "publications": [*published, *replayed],
            "skips": skipped,
            "failures": failures,
            "authority": {name: False for name in AUTHORITY_FIELDS},
            "legacy_feature_redis_write_performed": False,
            "market_performance_thresholds_applied": False,
            "singleton_writer_lock": lock_metadata,
            "state_sha256": stable_sha256(state),
        }
        status["status_sha256"] = stable_sha256(status)
        _atomic_write_json(
            self.status_path,
            status,
            failure_reason="PROFILED_BASE_PUBLISHER_STATUS_WRITE_FAILED",
        )
        return status


__all__ = [
    "BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL",
    "CANONICAL_KEY_PREFIX",
    "DECISION_TIMEFRAME",
    "DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS",
    "DISK_RESERVE_POLICY_V1",
    "DISK_RESERVE_PUBLICATION_UNITS",
    "DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR",
    "DISK_RESERVE_TOTAL_FRACTION_NUMERATOR",
    "MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS",
    "PROFILED_BASE_FEATURE_PUBLISHER_STATE_V1_SCHEMA_VERSION",
    "PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION",
    "PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION",
    "ProfiledBaseFeaturePublisherV1",
    "ProfiledBaseFeaturePublisherV1ConfigurationError",
    "ProfiledBaseFeaturePublisherV1Error",
    "ProfiledBaseFeaturePublisherV1ResourceError",
    "ProfiledBaseFeaturePublisherV1StateError",
    "PublisherResourceDecisionV1",
    "adaptive_resource_decision_v1",
    "discover_canonical_profile_symbols_v1",
    "least_recently_covered_symbols_v1",
    "prospective_decision_midpoint_v1",
    "select_source_shard_index_v1",
    "wait_for_prospective_decision_v1",
]
