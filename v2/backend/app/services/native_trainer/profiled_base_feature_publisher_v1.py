"""Runtime publisher for authenticated profiled-training evidence.

The publisher is intentionally narrower than a trainer or prediction service.
It discovers symbols from the intersection of the canonical Binance closed
``5m`` and ``1h`` Redis keys, captures their exact bytes with the existing
atomic receipt adapter, and durably records both source captures before it
computes a still-unappended 35-feature parent.  With complete protected
commission credentials, a parent is published only in one adjacent ledger
transaction with its four label-only causal-cost values.  When the complete
credential bundle is absent, the same point-in-time-safe parent may instead be
appended alone as a quarantined observation with an explicit four-slot missing
cost mask and no cost values or receipts.  Neither path grants prediction,
paper, or live authority.

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

from v2.backend.app.services.binance_usdm_commission_evidence_broker import (
    CredentiallessCommissionEvidence,
)
from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    AtomicRedisSourceReadBatch,
    AtomicRedisSourceReadError,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AuthenticatedOhlcvProfileTransformV1Error,
    transform_authenticated_ohlcv_profile_v1,
)
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS,
    BinanceUSDMCommissionCaptureV1Error,
    build_binance_usdm_commission_refresh_policy_v1,
    capture_binance_usdm_commission_rate_v1,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicCaptureError,
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256,
    CanonicalOhlcvMultitimeframeCaptureSetV1Error,
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
    canonical_ohlcv_multitimeframe_capture_set_v1_contract,
)
from v2.backend.app.services.native_trainer.causal_adaptive_cold_start_notional_policy_v1 import (
    CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
    CausalAdaptiveColdStartNotionalPolicyV1Error,
    build_causal_adaptive_cold_start_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
    CausalCostEvidenceV1Error,
    CausalCostEvidenceV1Result,
    build_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    CAUSAL_EXPECTED_NOTIONAL_ZERO_CANDIDATE_REASON,
    CausalExpectedNotionalPolicyV1Error,
    build_causal_expected_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
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
    PHYSICAL_ORDERED_FEATURE_NAMES,
    ProfiledModelFeatureSnapshotRecordV1Error,
    build_profiled_model_feature_snapshot_record_v1,
    validate_profiled_model_feature_snapshot_record_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_enrichment_record_v1 import (
    ProfiledTrainingEnrichmentPairV1,
    ProfiledTrainingEnrichmentRecordV1Error,
    append_profiled_training_enrichment_pair_v1,
    build_profiled_training_enrichment_pair_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    MAX_PROFILED_TRAINING_SCAN_ROWS,
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY,
    ProfiledTrainingLedgerLoaderV1Error,
    ProfiledTrainingLedgerSampleV1,
    load_profiled_training_ledger_v1,
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
AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE: Final = (
    "AUTHENTICATED_COST_EVIDENCE_REQUIRED"
)
MASKED_COST_OBSERVATION_MODE: Final = "MASKED_COST_OBSERVATION"
BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE: Final = (
    "BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK"
)
PROFILED_MASKED_COST_OBSERVATION_V1_SCHEMA_VERSION: Final = (
    "profiled_masked_cost_observation_v1"
)
CANONICAL_KEY_PREFIX: Final = "v2:market:ohlcv_closed:binance:"
REQUIRED_TIMEFRAMES: Final = ("5m", "1h")
DYNAMIC_SYMBOL_SELECTION_KEY: Final = "v2:symbol_universe:dynamic_discovered_symbols"

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
PAIR_LEDGER_RECORD_ACCOUNTING_MULTIPLIER: Final = 4
PAIR_AUXILIARY_CAS_SQLITE_ACCOUNTING_OVERHEAD_BYTES: Final = 1024 * 1024
DISK_RESERVE_PUBLICATION_UNITS: Final = 2
DISK_RESERVE_TOTAL_FRACTION_NUMERATOR: Final = 1
DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR: Final = 5
DISK_RESERVE_POLICY_V1: Final = (
    "MAX_TWO_ESTIMATED_PUBLICATION_UNITS_OR_CEILING_ONE_FIFTH_TOTAL_DISK"
)
SOURCE_SHARD_RE = re.compile(r"^shard-([0-9]{8})$", re.ASCII)
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,48}$", re.ASCII)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
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
COST_TEMPORAL_RETRY_REASONS: Final = frozenset(
    {
        "CAUSAL_COST_ATOMIC_CAPTURE_AFTER_DECISION",
        "EXPECTED_NOTIONAL_ATOMIC_CAPTURE_AFTER_DECISION",
        "EXPECTED_NOTIONAL_SOURCE_EXPIRED_AT_DECISION",
        "COLD_START_NOTIONAL_PORTFOLIO_CAPTURE_AFTER_DECISION",
        "COLD_START_NOTIONAL_PORTFOLIO_EXPIRED_AT_DECISION",
        "COLD_START_NOTIONAL_CONTROL_CAPTURE_AFTER_DECISION",
        "COLD_START_NOTIONAL_ZERO_CANDIDATE_EXPIRED_AT_DECISION",
        "COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_MISMATCH",
        "COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_ID_MISMATCH",
        "COLD_START_NOTIONAL_MARKET_CAPTURE_AFTER_DECISION",
        "COLD_START_NOTIONAL_MARKET_EXPIRED_AT_DECISION",
        "COMMISSION_BROKER_DECISION_TEMPORAL_ADMISSION_FAILED",
        "PROFILED_BASE_PUBLISHER_COMMISSION_POLICY_AFTER_DECISION",
        "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_WINDOW_MISSED",
        "PROFILED_BASE_PUBLISHER_NOTIONAL_PTTL_SUBSECOND_UNUSABLE",
        "PROFILED_MODEL_RECORD_PUBLICATION_CLOCK_ORDER_INVALID",
        "PROFILED_TRAINING_ENRICHMENT_PUBLICATION_CLOCK_ORDER_INVALID",
    }
)
COST_SOURCE_EXPIRED_AT_DECISION_RE = re.compile(
    r"^CAUSAL_COST_(ORDERBOOK_DEPTH|ORDERBOOK_FEATURES|MARK_PRICE)_" r"SOURCE_EXPIRED_AT_DECISION$",
    re.ASCII,
)
COST_OPERATOR_BLOCKER_REASON_FRAGMENTS: Final = (
    "CREDENTIAL",
    "ACCOUNT_SPECIFIC",
    "READ_ONLY_CREDENTIAL",
    "FINGERPRINT_HMAC",
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
PROFILED_TRAINING_ENRICHMENT_CAS_DIRECTORY: Final = "profiled-training-enrichment-cas"
# The unversioned directory is retained as the immutable V1 audit namespace.
PROFILED_TRAINING_PAIR_RECOVERY_DIRECTORY: Final = "profiled-training-pair-recovery-receipts"
PROFILED_TRAINING_PAIR_RECOVERY_V2_DIRECTORY: Final = (
    "profiled-training-pair-recovery-receipts-v2"
)
PROFILED_TRAINING_PAIR_RECOVERY_V1_SCHEMA_VERSION: Final = (
    "profiled_training_pair_recovery_receipt_v1"
)
PROFILED_TRAINING_PAIR_RECOVERY_V2_SCHEMA_VERSION: Final = (
    "profiled_training_pair_recovery_receipt_v2"
)
PROFILED_MASKED_PARENT_RECOVERY_DIRECTORY: Final = (
    "profiled-masked-parent-recovery-receipts-v1"
)
PROFILED_MASKED_PARENT_RECOVERY_V1_SCHEMA_VERSION: Final = (
    "profiled_masked_parent_recovery_receipt_v1"
)
_PAIR_RECOVERY_V1_FIELDS: Final = frozenset(
    {
        "schema_version",
        "symbol",
        "window_fingerprint_sha256",
        "parent_durable_snapshot_id",
        "parent_record_sha256",
        "child_durable_snapshot_id",
        "child_record_sha256",
        "cost_capture_artifact_sha256",
        "cost_store_root",
        "prepared_at",
        "append_disposition",
        "materialized_evidence_bytes",
        "evidence_accounting_method",
        "recovery_receipt_sha256",
    }
)
_PAIR_RECOVERY_FIELDS: Final = frozenset(
    {
        "schema_version",
        "symbol",
        "window_fingerprint_sha256",
        "capture_policy_id",
        "capture_policy_sha256",
        "transform_configuration_sha256",
        "parent_durable_snapshot_id",
        "parent_record_sha256",
        "child_durable_snapshot_id",
        "child_record_sha256",
        "cost_capture_artifact_sha256",
        "cost_store_root",
        "prepared_at",
        "append_disposition",
        "materialized_evidence_bytes",
        "evidence_accounting_method",
        "recovery_receipt_sha256",
    }
)
_MASKED_PARENT_RECOVERY_FIELDS: Final = frozenset(
    {
        "schema_version",
        "symbol",
        "window_fingerprint_sha256",
        "capture_policy_id",
        "capture_policy_sha256",
        "transform_configuration_sha256",
        "parent_durable_snapshot_id",
        "parent_record_sha256",
        "cost_observation_binding_sha256",
        "prepared_at",
        "append_disposition",
        "materialized_evidence_bytes",
        "evidence_accounting_method",
        "recovery_receipt_sha256",
    }
)
COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED: Final = (
    "COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED"
)
COMMISSION_REFRESH_POLICY_ID: Final = "profiled-training-commission-notional-pttl-refresh-v1"
COMMISSION_REFRESH_POLICY_VERSION: Final = "notional-redis-pttl-server-clock-v1"
COMMISSION_CAPTURE_FALLBACK_REASON: Final = "profiled-training-causal-cost-required"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _masked_cost_observation_contract() -> dict[str, Any]:
    """Return a fresh no-value mask for the atomic four-field cost bundle."""

    return {
        "schema_version": PROFILED_MASKED_COST_OBSERVATION_V1_SCHEMA_VERSION,
        "classification": "REQUIRED_LABEL_AUXILIARY_COST_BUNDLE_UNAVAILABLE_MASKED",
        "ordered_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "missing_mask": [1] * len(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "stale_mask": [0] * len(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "source_availability_mask": [0] * len(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "feature_values_emitted": False,
        "feature_source_receipts_emitted": False,
        "unavailability_reason": (
            "COMPLETE_PROTECTED_COMMISSION_CREDENTIAL_BUNDLE_ABSENT_"
            "AT_PROSPECTIVE_DECISION"
        ),
        "strict_training_eligible": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }


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


def pttl_derived_cost_recapture_target_v1(
    *,
    atomic_captures: tuple[AtomicRedisSourceReadBatch, AtomicRedisSourceReadBatch],
    decision_at: datetime,
) -> datetime:
    """Derive a just-in-time recapture target only from Redis clocks/PTTLs.

    The first capture is the one-key notional source and the second is the
    three-key market source.  Half of the shortest observed persisted lifetime
    is retained after recapture.  This is scheduling geometry over source
    expiry evidence, not a consumer freshness or market threshold; the final
    factories still require every recaptured expiry to cover the decision.
    """

    if (
        type(atomic_captures) is not tuple
        or len(atomic_captures) != 2
        or any(type(batch) is not AtomicRedisSourceReadBatch for batch in atomic_captures)
        or type(decision_at) is not datetime
        or decision_at.tzinfo is not UTC
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
            "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_INPUT_INVALID",
        )
    server_times: list[datetime] = []
    pttls: list[int] = []
    for batch in atomic_captures:
        try:
            server_at = _EPOCH + timedelta(
                seconds=batch.server_time_seconds,
                microseconds=batch.server_time_microseconds,
            )
        except (OverflowError, TypeError, ValueError):
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_SERVER_CLOCK_INVALID",
            )
        if (
            server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
            != batch.server_observed_at
            or server_at >= decision_at
            or type(batch.results) is not tuple
            or not batch.results
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_SERVER_CLOCK_INVALID",
            )
        server_times.append(server_at)
        for result in batch.results:
            if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
                _fail(
                    ProfiledBaseFeaturePublisherV1ConfigurationError,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_PTTL_INVALID",
                )
            pttls.append(result.pttl_ms)
    if len(atomic_captures[0].results) != 1 or len(atomic_captures[1].results) != 3:
        _fail(
            ProfiledBaseFeaturePublisherV1ConfigurationError,
            COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
            "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_SOURCE_SHAPE_INVALID",
        )
    shortest_pttl_ms = min(pttls)
    retained_lifetime_ms = max(1, shortest_pttl_ms // 2)
    target = decision_at - timedelta(milliseconds=retained_lifetime_ms)
    return max(*server_times, target)


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


def _regular_tree_file_bytes(root: Path) -> int:
    """Measure only durable regular files owned by one publisher tree."""

    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1ResourceError(
            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_SAMPLE_FAILED"
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        _fail(
            ProfiledBaseFeaturePublisherV1ResourceError,
            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_ROOT_INVALID",
        )
    total = 0
    pending = [root]
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    item_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(item_stat.st_mode):
                        total += item_stat.st_size
                    elif stat.S_ISDIR(item_stat.st_mode):
                        pending.append(Path(entry.path))
                    else:
                        _fail(
                            ProfiledBaseFeaturePublisherV1ResourceError,
                            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_ENTRY_INVALID",
                        )
    except ProfiledBaseFeaturePublisherV1ResourceError:
        raise
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1ResourceError(
            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_SAMPLE_FAILED"
        ) from exc
    return total


def _regular_file_bytes(path: Path) -> int:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1ResourceError(
            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_SAMPLE_FAILED"
        ) from exc
    if not stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        _fail(
            ProfiledBaseFeaturePublisherV1ResourceError,
            "PROFILED_BASE_PUBLISHER_OWNED_FOOTPRINT_ENTRY_INVALID",
        )
    return path_stat.st_size


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


def _pair_recovery_receipt_path(data_root: Path, symbol: str) -> Path:
    if SYMBOL_RE.fullmatch(symbol) is None:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_SYMBOL_INVALID",
        )
    return data_root / PROFILED_TRAINING_PAIR_RECOVERY_V2_DIRECTORY / f"{symbol}.json"


def _masked_parent_recovery_receipt_path(data_root: Path, symbol: str) -> Path:
    if SYMBOL_RE.fullmatch(symbol) is None:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_SYMBOL_INVALID",
        )
    return data_root / PROFILED_MASKED_PARENT_RECOVERY_DIRECTORY / f"{symbol}.json"


def _legacy_pair_recovery_receipt_path(data_root: Path, symbol: str) -> Path:
    if SYMBOL_RE.fullmatch(symbol) is None:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_SYMBOL_INVALID",
        )
    return data_root / PROFILED_TRAINING_PAIR_RECOVERY_DIRECTORY / f"{symbol}.json"


def _observe_legacy_pair_recovery_receipt(data_root: Path, symbol: str) -> dict[str, Any]:
    path = _legacy_pair_recovery_receipt_path(data_root, symbol)
    try:
        observed = os.lstat(path)
    except FileNotFoundError:
        return {
            "classification": "LEGACY_V1_RECOVERY_RECEIPT_ABSENT",
            "present": False,
            "regular_file": False,
            "owned_by_runtime_uid": False,
            "private_mode": False,
            "content_consumed": False,
            "authority_granted": False,
        }
    except OSError:
        return {
            "classification": "LEGACY_V1_RECOVERY_RECEIPT_UNREADABLE_PRESERVED",
            "present": True,
            "regular_file": False,
            "owned_by_runtime_uid": False,
            "private_mode": False,
            "content_consumed": False,
            "authority_granted": False,
        }
    mode = stat.S_IMODE(observed.st_mode)
    regular = stat.S_ISREG(observed.st_mode) and not stat.S_ISLNK(observed.st_mode)
    return {
        "classification": "LEGACY_V1_RECOVERY_RECEIPT_PRESERVED_UNCONSUMED",
        "present": True,
        "regular_file": regular,
        "owned_by_runtime_uid": observed.st_uid == os.geteuid(),
        "private_mode": regular and mode & 0o077 == 0,
        "content_consumed": False,
        "authority_granted": False,
    }


def _load_pair_recovery_receipt(
    path: Path,
    *,
    expected_symbol: str,
    expected_cost_store_root: Path,
) -> dict[str, Any] | None:
    """Read one canonical pre-append intent without trusting it as a commit."""

    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_READ_FAILED"
        ) from exc
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or stat.S_IMODE(path_stat.st_mode) & 0o022
        or path_stat.st_size <= 0
        or path_stat.st_size > MAX_STATE_BYTES
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_FILE_INVALID",
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_READ_FAILED"
        ) from exc
    if b"\r" in raw or not raw.endswith(b"\n"):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_FRAMING_INVALID",
        )
    try:
        parsed = json.loads(raw[:-1].decode("ascii", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_JSON_INVALID",
        )
    if type(parsed) is not dict or _canonical_json_bytes(parsed) + b"\n" != raw:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_FIELDS_INVALID",
        )
    receipt = cast(dict[str, Any], parsed)
    unsigned = {key: value for key, value in receipt.items() if key != "recovery_receipt_sha256"}
    if receipt.get("schema_version") == PROFILED_TRAINING_PAIR_RECOVERY_V1_SCHEMA_VERSION:
        legacy_sha_fields = (
            "window_fingerprint_sha256",
            "parent_record_sha256",
            "child_record_sha256",
            "cost_capture_artifact_sha256",
            "recovery_receipt_sha256",
        )
        if (
            set(receipt) != _PAIR_RECOVERY_V1_FIELDS
            or receipt.get("symbol") != expected_symbol
            or receipt.get("cost_store_root") != str(expected_cost_store_root)
            or receipt.get("append_disposition")
            != "PREPARED_BEFORE_ATOMIC_PAIR_APPEND_REQUIRES_LEDGER_READBACK"
            or receipt.get("evidence_accounting_method")
            != (
                "CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_"
                "AND_AUXILIARY_SQLITE_OVERHEAD"
            )
            or type(receipt.get("materialized_evidence_bytes")) is not int
            or cast(int, receipt.get("materialized_evidence_bytes")) <= 0
            or any(
                type(receipt.get(name)) is not str
                or SHA256_RE.fullmatch(cast(str, receipt.get(name))) is None
                for name in legacy_sha_fields
            )
            or any(
                type(receipt.get(name)) is not str or not receipt.get(name)
                for name in ("parent_durable_snapshot_id", "child_durable_snapshot_id")
            )
            or stable_sha256(unsigned) != receipt.get("recovery_receipt_sha256")
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_BINDING_INVALID",
            )
        _parse_clock(
            receipt.get("prepared_at"),
            reason="PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PREPARED_CLOCK_INVALID",
        )
        # V1 did not bind the capture policy or transform configuration.  It
        # can never recover authority after a policy migration; a fresh V2
        # publication must independently rebuild and authenticate the pair.
        return None
    if set(receipt) != _PAIR_RECOVERY_FIELDS:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_FIELDS_INVALID",
        )
    sha_fields = (
        "window_fingerprint_sha256",
        "capture_policy_sha256",
        "transform_configuration_sha256",
        "parent_record_sha256",
        "child_record_sha256",
        "cost_capture_artifact_sha256",
        "recovery_receipt_sha256",
    )
    if (
        receipt["schema_version"] != PROFILED_TRAINING_PAIR_RECOVERY_V2_SCHEMA_VERSION
        or receipt["symbol"] != expected_symbol
        or receipt["capture_policy_id"]
        != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID
        or receipt["capture_policy_sha256"]
        != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
        or receipt["transform_configuration_sha256"]
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        or receipt["cost_store_root"] != str(expected_cost_store_root)
        or receipt["append_disposition"]
        != "PREPARED_BEFORE_ATOMIC_PAIR_APPEND_REQUIRES_LEDGER_READBACK"
        or receipt["evidence_accounting_method"]
        != ("CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_" "AND_AUXILIARY_SQLITE_OVERHEAD")
        or type(receipt["materialized_evidence_bytes"]) is not int
        or receipt["materialized_evidence_bytes"] <= 0
        or any(
            type(receipt[name]) is not str or SHA256_RE.fullmatch(cast(str, receipt[name])) is None
            for name in sha_fields
        )
        or any(
            type(receipt[name]) is not str or not receipt[name]
            for name in ("parent_durable_snapshot_id", "child_durable_snapshot_id")
        )
        or stable_sha256(unsigned) != receipt["recovery_receipt_sha256"]
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_BINDING_INVALID",
        )
    _parse_clock(
        receipt["prepared_at"],
        reason="PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PREPARED_CLOCK_INVALID",
    )
    return receipt


def _load_masked_parent_recovery_receipt(
    path: Path,
    *,
    expected_symbol: str,
) -> dict[str, Any] | None:
    """Read one masked-parent pre-append intent without treating it as a commit."""

    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_READ_FAILED"
        ) from exc
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or stat.S_IMODE(path_stat.st_mode) & 0o022
        or path_stat.st_size <= 0
        or path_stat.st_size > MAX_STATE_BYTES
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_FILE_INVALID",
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfiledBaseFeaturePublisherV1StateError(
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_READ_FAILED"
        ) from exc
    if b"\r" in raw or not raw.endswith(b"\n"):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_FRAMING_INVALID",
        )
    try:
        parsed = json.loads(raw[:-1].decode("ascii", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_JSON_INVALID",
        )
    if type(parsed) is not dict or _canonical_json_bytes(parsed) + b"\n" != raw:
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_FIELDS_INVALID",
        )
    receipt = cast(dict[str, Any], parsed)
    unsigned = {key: value for key, value in receipt.items() if key != "recovery_receipt_sha256"}
    sha_fields = (
        "window_fingerprint_sha256",
        "capture_policy_sha256",
        "transform_configuration_sha256",
        "parent_record_sha256",
        "cost_observation_binding_sha256",
        "recovery_receipt_sha256",
    )
    if (
        set(receipt) != _MASKED_PARENT_RECOVERY_FIELDS
        or receipt["schema_version"]
        != PROFILED_MASKED_PARENT_RECOVERY_V1_SCHEMA_VERSION
        or receipt["symbol"] != expected_symbol
        or receipt["capture_policy_id"]
        != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID
        or receipt["capture_policy_sha256"]
        != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
        or receipt["transform_configuration_sha256"]
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        or receipt["append_disposition"]
        != "PREPARED_BEFORE_MASKED_PARENT_APPEND_REQUIRES_LEDGER_READBACK"
        or receipt["evidence_accounting_method"]
        != (
            "CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_"
            "AND_AUXILIARY_SQLITE_OVERHEAD"
        )
        or type(receipt["materialized_evidence_bytes"]) is not int
        or receipt["materialized_evidence_bytes"] <= 0
        or type(receipt["parent_durable_snapshot_id"]) is not str
        or not receipt["parent_durable_snapshot_id"]
        or any(
            type(receipt[name]) is not str
            or SHA256_RE.fullmatch(cast(str, receipt[name])) is None
            for name in sha_fields
        )
        or stable_sha256(unsigned) != receipt["recovery_receipt_sha256"]
    ):
        _fail(
            ProfiledBaseFeaturePublisherV1StateError,
            "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_BINDING_INVALID",
        )
    _parse_clock(
        receipt["prepared_at"],
        reason="PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_PREPARED_CLOCK_INVALID",
    )
    return receipt


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
        | ProfiledTrainingEnrichmentRecordV1Error
        | TrainerSourceProvenanceLedgerV4Error
        | FeatureSnapshotLedgerError
        | SourcePayloadStoreError
        | AtomicRedisSourceReadError
        | CausalAdaptiveColdStartNotionalPolicyV1Error
        | CausalExpectedNotionalPolicyV1Error
        | BinanceUSDMCommissionCaptureV1Error
        | CausalCostEvidenceV1Error,
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


def _cost_temporal_retryable(reasons: Iterable[str]) -> bool:
    normalized = tuple(reason.upper() for reason in reasons)
    return any(
        reason in COST_TEMPORAL_RETRY_REASONS
        or COST_SOURCE_EXPIRED_AT_DECISION_RE.fullmatch(reason) is not None
        for reason in normalized
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
    observed_cycle_count: int
    consumed_materialized_evidence_bytes: int
    cumulative_sustainable_write_budget_bytes: int
    write_credit_capacity_bytes: int
    available_write_credit_bytes: int
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
            "observed_cycle_count": self.observed_cycle_count,
            "consumed_materialized_evidence_bytes": (
                self.consumed_materialized_evidence_bytes
            ),
            "cumulative_sustainable_write_budget_bytes": (
                self.cumulative_sustainable_write_budget_bytes
            ),
            "write_credit_capacity_bytes": self.write_credit_capacity_bytes,
            "available_write_credit_bytes": self.available_write_credit_bytes,
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
    observed_cycle_count = observations.get("cycle_count")
    if (
        type(observed_cycle_count) is not int
        or observed_cycle_count < 0
        or type(publication_count) is not int
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
    # A sustainable byte rate can be smaller than one indivisible evidence
    # unit.  Treat that rate as credit accrued across completed cycles instead
    # of requiring every individual cycle to fund a whole unit.  The bucket is
    # capped at the larger of one observed unit or one cycle's byte budget, so
    # an idle publisher cannot accumulate an unbounded catch-up burst.
    cumulative_sustainable_budget = sustainable_cycle_budget * (
        observed_cycle_count + 1
    )
    write_credit_capacity = max(sustainable_cycle_budget, estimated_bytes)
    available_write_credit = min(
        write_credit_capacity,
        max(0, cumulative_sustainable_budget - publication_bytes),
    )
    disk_capacity = min(
        absolute_disk_capacity,
        available_write_credit // estimated_bytes,
    )
    latency_capacity = max(1, math.floor(cycle_period_seconds / estimated_seconds))
    selected = min(eligible_count, disk_capacity, latency_capacity)
    reasons = [
        "LEAST_RECENTLY_COVERED_ROTATION",
        "IMMUTABLE_SHARED_FILESYSTEM_RESERVE_APPLIED",
        "SUSTAINABLE_DISK_HORIZON_DERIVED_WRITE_BUDGET",
        "BOUNDED_CROSS_CYCLE_WRITE_CREDIT_ACCRUAL",
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
        reasons.append(
            "BOUNDED_WRITE_CREDIT_ACCRUAL_PENDING"
            if absolute_disk_capacity > 0
            and available_write_credit < estimated_bytes
            else "RESOURCE_HEADROOM_NO_SAFE_PUBLICATION_UNIT"
        )
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
        observed_cycle_count=observed_cycle_count,
        consumed_materialized_evidence_bytes=publication_bytes,
        cumulative_sustainable_write_budget_bytes=cumulative_sustainable_budget,
        write_credit_capacity_bytes=write_credit_capacity,
        available_write_credit_bytes=available_write_credit,
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
    universe_symbols: tuple[str, ...]
    universe_excluded_symbols: tuple[str, ...]
    universe_status: str
    universe_reason: str | None
    universe_server_observed_at: str | None
    universe_pttl_ms: int | None
    universe_rejected_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SelectionUniverse:
    symbols: tuple[str, ...]
    status: str
    reason: str | None
    server_observed_at: str | None
    pttl_ms: int | None
    rejected_symbols: tuple[str, ...]


def _dynamic_selection_universe_v1(
    redis_client: object,
    *,
    atomic_reader: Callable[..., AtomicRedisSourceReadBatch],
) -> _SelectionUniverse:
    """Validate the expiring universe as selection metadata, never evidence."""

    try:
        batch = atomic_reader(redis_client, (DYNAMIC_SYMBOL_SELECTION_KEY,))
    except Exception as exc:  # noqa: BLE001 - transport detail must not escape
        return _SelectionUniverse(
            symbols=(),
            status="UNAVAILABLE_HOLD",
            reason=f"DYNAMIC_SELECTION_UNIVERSE_{type(exc).__name__.upper()}",
            server_observed_at=None,
            pttl_ms=None,
            rejected_symbols=(),
        )
    if (
        type(batch) is not AtomicRedisSourceReadBatch
        or type(batch.results) is not tuple
        or len(batch.results) != 1
    ):
        return _SelectionUniverse(
            symbols=(),
            status="MALFORMED_HOLD",
            reason="DYNAMIC_SELECTION_UNIVERSE_ATOMIC_SHAPE_INVALID",
            server_observed_at=None,
            pttl_ms=None,
            rejected_symbols=(),
        )
    result = batch.results[0]
    payload = result.exact_payload_bytes
    if (
        result.source_key != DYNAMIC_SYMBOL_SELECTION_KEY
        or result.redis_type != "string"
        or result.present is not True
        or type(payload) is not bytes
        or not payload
        or type(result.pttl_ms) is not int
        or result.pttl_ms <= 0
    ):
        return _SelectionUniverse(
            symbols=(),
            status="UNAVAILABLE_HOLD",
            reason="DYNAMIC_SELECTION_UNIVERSE_SOURCE_MISSING_OR_UNPERSISTED",
            server_observed_at=batch.server_observed_at,
            pttl_ms=result.pttl_ms if type(result.pttl_ms) is int else None,
            rejected_symbols=(),
        )

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError("duplicate")
            parsed[key] = value
        return parsed

    try:
        decoded = json.loads(
            cast(bytes, payload).decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
        server_at = _EPOCH + timedelta(
            seconds=batch.server_time_seconds,
            microseconds=batch.server_time_microseconds,
        )
        generated_raw = decoded.get("generated_utc")
        generated_at = datetime.strptime(generated_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (AttributeError, TypeError, UnicodeError, ValueError, OverflowError):
        return _SelectionUniverse(
            symbols=(),
            status="MALFORMED_HOLD",
            reason="DYNAMIC_SELECTION_UNIVERSE_PAYLOAD_INVALID",
            server_observed_at=batch.server_observed_at,
            pttl_ms=result.pttl_ms,
            rejected_symbols=(),
        )
    raw_symbols = decoded.get("symbols")
    if (
        type(decoded) is not dict
        or set(decoded) != {"generated_utc", "symbols"}
        or type(raw_symbols) is not list
        or any(type(symbol) is not str for symbol in raw_symbols)
        or len(set(raw_symbols)) != len(raw_symbols)
        or server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        != batch.server_observed_at
        or generated_at > server_at
    ):
        return _SelectionUniverse(
            symbols=(),
            status="MALFORMED_HOLD",
            reason="DYNAMIC_SELECTION_UNIVERSE_SCHEMA_OR_CLOCK_INVALID",
            server_observed_at=batch.server_observed_at,
            pttl_ms=result.pttl_ms,
            rejected_symbols=(),
        )
    # The writer atomically publishes this payload with its own Redis expiry.
    # A positive observed PTTL is therefore the source-owned availability
    # contract.  Comparing payload age with *remaining* PTTL would incorrectly
    # invalidate every healthy key halfway through its lifetime because the
    # original TTL is not present in this receipt.
    typed_symbols = cast(list[str], raw_symbols)
    symbols = tuple(symbol for symbol in typed_symbols if SYMBOL_RE.fullmatch(symbol) is not None)
    rejected_symbols = tuple(
        symbol for symbol in typed_symbols if SYMBOL_RE.fullmatch(symbol) is None
    )
    return _SelectionUniverse(
        symbols=symbols,
        status="VALID" if symbols else "VALID_EMPTY_HOLD",
        reason=None if symbols else "DYNAMIC_SELECTION_UNIVERSE_EMPTY",
        server_observed_at=batch.server_observed_at,
        pttl_ms=result.pttl_ms,
        rejected_symbols=rejected_symbols,
    )


def discover_canonical_profile_symbols_v1(
    redis_client: object,
    *,
    atomic_reader: Callable[..., AtomicRedisSourceReadBatch] = read_atomic_redis_sources,
) -> _Discovery:
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
    universe = _dynamic_selection_universe_v1(
        redis_client,
        atomic_reader=atomic_reader,
    )
    universe_set = set(universe.symbols) if universe.status == "VALID" else set()
    discovered = tuple(sorted(by_symbol))
    required = set(REQUIRED_TIMEFRAMES)
    eligible = tuple(
        symbol for symbol in discovered if by_symbol[symbol] == required and symbol in universe_set
    )
    missing = tuple(
        (symbol, tuple(sorted(required - by_symbol[symbol])))
        for symbol in discovered
        if symbol in universe_set and by_symbol[symbol] != required
    )
    return _Discovery(
        discovered_symbols=discovered,
        eligible_symbols=eligible,
        missing_timeframes=missing,
        rejected_key_sha256s=tuple(sorted(set(rejected))),
        universe_symbols=universe.symbols,
        universe_excluded_symbols=tuple(
            symbol for symbol in discovered if symbol not in universe_set
        ),
        universe_status=universe.status,
        universe_reason=universe.reason,
        universe_server_observed_at=universe.server_observed_at,
        universe_pttl_ms=universe.pttl_ms,
        universe_rejected_symbols=universe.rejected_symbols,
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
        feature_ledger: DurableFeatureSnapshotLedger | None = None,
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
        cost_evidence_factory: Callable[..., CausalCostEvidenceV1Result] | None = None,
        atomic_redis_reader: Callable[..., AtomicRedisSourceReadBatch] = (
            read_atomic_redis_sources
        ),
        expected_notional_builder: Callable[..., Any] = (build_causal_expected_notional_policy_v1),
        cold_start_notional_builder: Callable[..., Any] = (
            build_causal_adaptive_cold_start_notional_policy_v1
        ),
        commission_refresh_builder: Callable[..., Any] = (
            build_binance_usdm_commission_refresh_policy_v1
        ),
        commission_capture_function: Callable[..., Any] = (capture_binance_usdm_commission_rate_v1),
        commission_evidence_reader: Callable[..., dict[str, Any]] | None = None,
        causal_cost_builder: Callable[..., CausalCostEvidenceV1Result] = (
            build_causal_cost_evidence_v1
        ),
        commission_fingerprint_hmac_key: bytes | None = None,
        commission_cost_mode: str = AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE,
        exchange_credentials_loaded_by_publisher: bool = False,
        cost_recapture_waiter: Callable[[datetime], datetime] | None = None,
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
        if feature_ledger is not None and (
            type(feature_ledger) is not DurableFeatureSnapshotLedger
            or feature_ledger.path != self.feature_ledger_path
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1ConfigurationError,
                "PROFILED_BASE_PUBLISHER_FEATURE_LEDGER_BINDING_INVALID",
            )
        self._feature_ledger = feature_ledger
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
            or (cost_evidence_factory is not None and not callable(cost_evidence_factory))
            or not callable(atomic_redis_reader)
            or not callable(expected_notional_builder)
            or not callable(cold_start_notional_builder)
            or not callable(commission_refresh_builder)
            or not callable(commission_capture_function)
            or (
                commission_evidence_reader is not None
                and not callable(commission_evidence_reader)
            )
            or not callable(causal_cost_builder)
            or (cost_recapture_waiter is not None and not callable(cost_recapture_waiter))
            or (
                commission_fingerprint_hmac_key is not None
                and type(commission_fingerprint_hmac_key) is not bytes
            )
            or type(exchange_credentials_loaded_by_publisher) is not bool
            or commission_cost_mode
            not in {
                AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE,
                BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE,
                MASKED_COST_OBSERVATION_MODE,
            }
            or (
                commission_cost_mode == MASKED_COST_OBSERVATION_MODE
                and (
                    cost_evidence_factory is not None
                    or commission_fingerprint_hmac_key is not None
                    or commission_evidence_reader is not None
                )
            )
            or (
                commission_cost_mode
                == BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
                and (
                    commission_evidence_reader is None
                    or commission_fingerprint_hmac_key is not None
                    or cost_evidence_factory is not None
                )
            )
            or (
                commission_cost_mode == AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE
                and commission_evidence_reader is not None
            )
            or (
                exchange_credentials_loaded_by_publisher
                and commission_cost_mode != AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE
            )
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
        self.cost_evidence_factory = cost_evidence_factory
        self.atomic_redis_reader = atomic_redis_reader
        self.expected_notional_builder = expected_notional_builder
        self.cold_start_notional_builder = cold_start_notional_builder
        self.commission_refresh_builder = commission_refresh_builder
        self.commission_capture_function = commission_capture_function
        self.commission_evidence_reader = commission_evidence_reader
        self.causal_cost_builder = causal_cost_builder
        self._commission_fingerprint_hmac_key = commission_fingerprint_hmac_key
        self.commission_cost_mode = commission_cost_mode
        self.exchange_credentials_loaded_by_publisher = (
            exchange_credentials_loaded_by_publisher
        )
        self.cost_recapture_waiter = cost_recapture_waiter or (
            lambda target_at: wait_for_prospective_decision_v1(
                target_at,
                clock=self.clock,
            )
        )

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
        ImmutableSourcePayloadStore,
    ]:
        return (
            ImmutableSourcePayloadStore(self.data_root / "atomic-capture-cas"),
            ImmutableSourcePayloadStore(self.data_root / "capture-set-cas"),
            ImmutableSourcePayloadStore(self.data_root / "profiled-model-evidence-cas"),
            ImmutableSourcePayloadStore(
                self.data_root / PROFILED_TRAINING_ENRICHMENT_CAS_DIRECTORY
            ),
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

    def _owned_durable_footprint_bytes(self) -> int:
        """Measure publisher-owned files without attributing shared-disk traffic."""

        total = _regular_tree_file_bytes(self.data_root)
        for path in (
            self.feature_ledger_path,
            Path(f"{self.feature_ledger_path}-wal"),
            Path(f"{self.feature_ledger_path}-shm"),
        ):
            if path.is_relative_to(self.data_root):
                continue
            total += _regular_file_bytes(path)
        return total

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
                "schema_version": "profiled_base_finalized_window_fingerprint_v2",
                "symbol": symbol,
                "capture_policy_id": (
                    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID
                ),
                "capture_policy_sha256": (
                    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
                ),
                "transform_configuration_sha256": (
                    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
                ),
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

    @staticmethod
    def _cost_market_keys(symbol: str) -> tuple[str, str, str]:
        return (
            f"v2:orderbook:depth:binance:{symbol}",
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:market:mark_price:{symbol}",
        )

    def _read_cost_sources(
        self,
        *,
        symbol: str,
    ) -> tuple[AtomicRedisSourceReadBatch, AtomicRedisSourceReadBatch]:
        notional = self.atomic_redis_reader(
            self.redis_client,
            (CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,),
        )
        market = self.atomic_redis_reader(
            self.redis_client,
            self._cost_market_keys(symbol),
        )
        if (
            type(notional) is not AtomicRedisSourceReadBatch
            or type(market) is not AtomicRedisSourceReadBatch
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                "PROFILED_BASE_PUBLISHER_COST_ATOMIC_READER_RESULT_INVALID",
            )
        return notional, market

    def _read_cold_start_control_sources(self) -> AtomicRedisSourceReadBatch:
        capture = self.atomic_redis_reader(
            self.redis_client,
            (
                CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
                CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
            ),
        )
        if type(capture) is not AtomicRedisSourceReadBatch:
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                "PROFILED_BASE_PUBLISHER_COLD_START_CONTROL_READER_RESULT_INVALID",
            )
        return capture

    def _broker_commission_evidence_for_parent(
        self,
        *,
        parent_record: dict[str, Any],
    ) -> tuple[CredentiallessCommissionEvidence | None, str]:
        """Read one authenticated fee schedule or return a safe mask reason."""

        reader = self.commission_evidence_reader
        if reader is None:
            return None, "COMMISSION_BROKER_READER_NOT_CONFIGURED"
        envelope = cast(dict[str, Any], parent_record["frozen_envelope"])
        symbol = cast(str, envelope["symbol"])
        decision_time = cast(str, envelope["tensor_decision_time"])
        try:
            result = reader(
                symbol=symbol,
                decision_time=decision_time,
                now_fn=self.clock,
            )
        except Exception as exc:  # noqa: BLE001 - dependency detail stays masked
            return None, f"COMMISSION_BROKER_READER_EXCEPTION_{type(exc).__name__.upper()}"
        if type(result) is not dict:
            return None, "COMMISSION_BROKER_READER_RESULT_INVALID"
        status = result.get("status")
        if (
            type(status) is not str
            or not status.isascii()
            or not 1 <= len(status) <= 192
            or re.fullmatch(r"[A-Z0-9_]+", status, re.ASCII) is None
        ):
            return None, "COMMISSION_BROKER_READER_STATUS_INVALID"
        evidence = result.get("evidence")
        if status == "COMMISSION_BROKER_DECISION_TEMPORAL_ADMISSION_FAILED":
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                status,
            )
        if status != "READY":
            return None, status
        if (
            type(evidence) is not CredentiallessCommissionEvidence
            or evidence.symbol != symbol
            or evidence.decision_time != decision_time
            or evidence.exchange_credentials_read is not False
            or any(
                getattr(evidence, field) is not False
                for field in (
                    "trainer_authority",
                    "prediction_authority",
                    "paper_authority",
                    "live_authority",
                )
            )
        ):
            return None, "COMMISSION_BROKER_READY_EVIDENCE_INVALID"
        return evidence, status

    def _build_runtime_cost_evidence(
        self,
        *,
        parent_record: dict[str, Any],
        enrichment_store: ImmutableSourcePayloadStore,
        decision_at: datetime,
        commission_evidence: CredentiallessCommissionEvidence | None = None,
    ) -> tuple[CausalCostEvidenceV1Result, int]:
        envelope = cast(dict[str, Any], parent_record["frozen_envelope"])
        symbol = cast(str, envelope["symbol"])
        decision_text = cast(str, envelope["tensor_decision_time"])
        initial = self._read_cost_sources(symbol=symbol)
        recapture_target = pttl_derived_cost_recapture_target_v1(
            atomic_captures=initial,
            decision_at=decision_at,
        )
        latest_initial_server = max(
            _EPOCH
            + timedelta(
                seconds=batch.server_time_seconds,
                microseconds=batch.server_time_microseconds,
            )
            for batch in initial
        )
        captures = initial
        if recapture_target > latest_initial_server:
            try:
                waited = self.cost_recapture_waiter(recapture_target)
            except ProfiledBaseFeaturePublisherV1Error:
                raise
            except Exception as exc:  # noqa: BLE001 - dependency detail is suppressed
                raise ProfiledBaseFeaturePublisherV1Error(
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_WAIT_FAILED",
                ) from exc
            _clock_text(
                waited,
                reason="PROFILED_BASE_PUBLISHER_COST_RECAPTURE_WAIT_CLOCK_INVALID",
            )
            if waited < recapture_target or waited >= decision_at:
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COST_RECAPTURE_WINDOW_MISSED",
                )
            captures = self._read_cost_sources(symbol=symbol)

        notional_capture, market_capture = captures
        try:
            notional = self.expected_notional_builder(
                atomic_capture=notional_capture,
                source_payload_store=enrichment_store,
                symbol=symbol,
                feature_snapshot_identity=parent_record["durable_snapshot_id"],
                feature_snapshot_decision_time=decision_at,
            )
            notional_refresh_pttl_ms = notional_capture.results[0].pttl_ms
        except CausalExpectedNotionalPolicyV1Error as exc:
            if exc.reason != CAUSAL_EXPECTED_NOTIONAL_ZERO_CANDIDATE_REASON:
                raise
            control_capture = self._read_cold_start_control_sources()
            notional = self.cold_start_notional_builder(
                control_atomic_capture=control_capture,
                market_atomic_capture=market_capture,
                source_payload_store=enrichment_store,
                symbol=symbol,
                feature_snapshot_identity=parent_record["durable_snapshot_id"],
                feature_snapshot_decision_time=decision_at,
            )
            notional_refresh_pttl_ms = min(
                result.pttl_ms
                for batch in (
                    control_capture,
                    market_capture,
                )
                for result in batch.results
            )
        if commission_evidence is None:
            policy_at, policy_clock = self._sample_clock(
                "PROFILED_BASE_PUBLISHER_COMMISSION_POLICY_CLOCK_INVALID"
            )
            if policy_at >= decision_at:
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COMMISSION_POLICY_AFTER_DECISION",
                )
            # This refresh receipt authenticates the notional source PTTL, so do
            # not overclaim that it also binds the three market-source lifetimes.
            # Their minimum remains exclusively the just-in-time recapture input.
            if notional_refresh_pttl_ms < 1_000:
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_NOTIONAL_PTTL_SUBSECOND_UNUSABLE",
                )
            refresh_interval_seconds = min(
                IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS,
                notional_refresh_pttl_ms // 1_000,
            )
            refresh_policy = self.commission_refresh_builder(
                store=enrichment_store,
                symbol=symbol,
                policy_id=COMMISSION_REFRESH_POLICY_ID,
                policy_version=COMMISSION_REFRESH_POLICY_VERSION,
                refresh_interval_seconds=refresh_interval_seconds,
                adaptive_input_receipt_sha256=notional.source_read_receipt_sha256,
                generated_at=policy_clock,
                available_at=policy_clock,
                recorded_at=policy_clock,
            )
            commission = self.commission_capture_function(
                store=enrichment_store,
                symbol=symbol,
                refresh_policy=refresh_policy,
                fallback_reason=COMMISSION_CAPTURE_FALLBACK_REASON,
                credential_fingerprint_hmac_key=self._commission_fingerprint_hmac_key,
                now_fn=self.clock,
            )
            fee_artifact_bytes = commission.fee_artifact_bytes
            fee_raw_response_bytes = commission.raw_response_bytes
            fee_schedule_receipt = commission.fee_schedule_receipt
            auxiliary_cas_bytes = (
                len(refresh_policy.artifact_bytes)
                + len(refresh_policy.receipt_bytes)
                + len(commission.sanitized_request_identity_bytes)
            )
            fee_transport_envelope_bytes = None
            fee_transport_consumer_receipt_bytes = None
        else:
            if (
                type(commission_evidence) is not CredentiallessCommissionEvidence
                or commission_evidence.symbol != symbol
                or commission_evidence.decision_time != decision_text
                or commission_evidence.exchange_credentials_read is not False
                or commission_evidence.trainer_authority is not False
                or commission_evidence.prediction_authority is not False
                or commission_evidence.paper_authority is not False
                or commission_evidence.live_authority is not False
            ):
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_BROKER_COMMISSION_EVIDENCE_INVALID",
                )
            fee_artifact_bytes = commission_evidence.fee_artifact_bytes
            fee_raw_response_bytes = commission_evidence.raw_response_bytes
            fee_schedule_receipt = commission_evidence.fee_schedule_receipt
            fee_transport_envelope_bytes = commission_evidence.broker_envelope_bytes
            fee_transport_consumer_receipt_bytes = (
                commission_evidence.broker_consumer_receipt_bytes
            )
            # The broker created its own separately accounted immutable CAS.
            # The cost builder below accounts for every object copied into this
            # publisher's enrichment CAS, so no broker-side bytes are charged
            # again to the publisher's local materialization budget.
            auxiliary_cas_bytes = 0
        result = self.causal_cost_builder(
            atomic_capture=market_capture,
            source_payload_store=enrichment_store,
            fee_schedule_artifact_bytes=fee_artifact_bytes,
            fee_schedule_raw_response_bytes=fee_raw_response_bytes,
            fee_schedule_receipt=fee_schedule_receipt,
            expected_notional_usd=notional.expected_notional_usd,
            expected_notional_policy_artifact_bytes=notional.notional_artifact_bytes,
            expected_notional_policy_receipt=notional.notional_receipt,
            expected_notional_policy_source_receipt_bytes=(
                notional.source_read_receipt_bytes
            ),
            expected_notional_policy_factory_token=notional,
            symbol=symbol,
            feature_snapshot_identity=parent_record["durable_snapshot_id"],
            decision_time=decision_text,
            counterfactual_holding_horizon_seconds=(CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS),
            fee_transport_envelope_bytes=fee_transport_envelope_bytes,
            fee_transport_consumer_receipt_bytes=(
                fee_transport_consumer_receipt_bytes
            ),
        )
        if type(result) is not CausalCostEvidenceV1Result:
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                "PROFILED_BASE_PUBLISHER_COST_FACTORY_RESULT_INVALID",
            )
        return result, auxiliary_cas_bytes

    def _cost_evidence_for_parent(
        self,
        *,
        parent_record: dict[str, Any],
        enrichment_store: ImmutableSourcePayloadStore,
        decision_at: datetime,
        commission_evidence: CredentiallessCommissionEvidence | None = None,
    ) -> tuple[CausalCostEvidenceV1Result, int]:
        try:
            if self.cost_evidence_factory is not None:
                result = self.cost_evidence_factory(
                    parent_record=parent_record,
                    enrichment_store=enrichment_store,
                    decision_at=decision_at,
                )
                auxiliary_cas_bytes = 0
            else:
                result, auxiliary_cas_bytes = self._build_runtime_cost_evidence(
                    parent_record=parent_record,
                    enrichment_store=enrichment_store,
                    decision_at=decision_at,
                    commission_evidence=commission_evidence,
                )
            if type(result) is not CausalCostEvidenceV1Result:
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COST_FACTORY_RESULT_INVALID",
                )
            result_contract = result.contract
            notional_source = result_contract.get("notional_source")
            provenance = (
                notional_source.get("policy_provenance")
                if type(notional_source) is dict
                else None
            )
            if (
                type(provenance) is not dict
                or provenance.get("verification_status")
                != CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS
                or provenance.get("source_receipt_supplied") is not True
                or provenance.get("factory_token_revalidated") is not True
                or provenance.get("strict_publisher_eligible") is not True
            ):
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_NOTIONAL_POLICY_PROVENANCE_UNVERIFIED",
                )
            if type(auxiliary_cas_bytes) is not int or auxiliary_cas_bytes < 0:
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                    "PROFILED_BASE_PUBLISHER_COST_AUXILIARY_ACCOUNTING_INVALID",
                )
            return result, auxiliary_cas_bytes
        except Exception as exc:  # noqa: BLE001 - only stable reasons leave this boundary
            reasons = _error_reasons(exc)
            if COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED in reasons:
                raise
            raise ProfiledBaseFeaturePublisherV1Error(
                COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED,
                *reasons,
            ) from None

    def _write_pair_recovery_receipt(
        self,
        *,
        symbol: str,
        window_fingerprint_sha256: str,
        pair: ProfiledTrainingEnrichmentPairV1,
        enrichment_store: ImmutableSourcePayloadStore,
        materialized_evidence_bytes: int,
    ) -> None:
        if type(materialized_evidence_bytes) is not int or materialized_evidence_bytes <= 0:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_ACCOUNTING_INVALID",
            )
        unsigned: dict[str, Any] = {
            "schema_version": PROFILED_TRAINING_PAIR_RECOVERY_V2_SCHEMA_VERSION,
            "symbol": symbol,
            "window_fingerprint_sha256": window_fingerprint_sha256,
            "capture_policy_id": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
            "capture_policy_sha256": (
                CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
            ),
            "transform_configuration_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
            ),
            "parent_durable_snapshot_id": pair.parent_durable_snapshot_id,
            "parent_record_sha256": pair.parent_record_sha256,
            "child_durable_snapshot_id": pair.child_durable_snapshot_id,
            "child_record_sha256": pair.child_record_sha256,
            "cost_capture_artifact_sha256": pair.cost_capture_artifact_sha256,
            "cost_store_root": str(enrichment_store.root_path),
            "prepared_at": pair.generated_at,
            "append_disposition": ("PREPARED_BEFORE_ATOMIC_PAIR_APPEND_REQUIRES_LEDGER_READBACK"),
            "materialized_evidence_bytes": materialized_evidence_bytes,
            "evidence_accounting_method": (
                "CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_"
                "AND_AUXILIARY_SQLITE_OVERHEAD"
            ),
        }
        receipt = {
            **unsigned,
            "recovery_receipt_sha256": stable_sha256(unsigned),
        }
        _atomic_write_json(
            _pair_recovery_receipt_path(self.data_root, symbol),
            receipt,
            failure_reason="PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_RECEIPT_WRITE_FAILED",
        )

    def _write_masked_parent_recovery_receipt(
        self,
        *,
        symbol: str,
        window_fingerprint_sha256: str,
        parent_durable_snapshot_id: str,
        parent_record_sha256: str,
        cost_observation_binding_sha256: str,
        prepared_at: str,
        materialized_evidence_bytes: int,
    ) -> None:
        if type(materialized_evidence_bytes) is not int or materialized_evidence_bytes <= 0:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_ACCOUNTING_INVALID",
            )
        unsigned: dict[str, Any] = {
            "schema_version": PROFILED_MASKED_PARENT_RECOVERY_V1_SCHEMA_VERSION,
            "symbol": symbol,
            "window_fingerprint_sha256": window_fingerprint_sha256,
            "capture_policy_id": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
            "capture_policy_sha256": (
                CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
            ),
            "transform_configuration_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
            ),
            "parent_durable_snapshot_id": parent_durable_snapshot_id,
            "parent_record_sha256": parent_record_sha256,
            "cost_observation_binding_sha256": cost_observation_binding_sha256,
            "prepared_at": prepared_at,
            "append_disposition": (
                "PREPARED_BEFORE_MASKED_PARENT_APPEND_REQUIRES_LEDGER_READBACK"
            ),
            "materialized_evidence_bytes": materialized_evidence_bytes,
            "evidence_accounting_method": (
                "CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_"
                "AND_AUXILIARY_SQLITE_OVERHEAD"
            ),
        }
        receipt = {
            **unsigned,
            "recovery_receipt_sha256": stable_sha256(unsigned),
        }
        _atomic_write_json(
            _masked_parent_recovery_receipt_path(self.data_root, symbol),
            receipt,
            failure_reason="PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_RECEIPT_WRITE_FAILED",
        )

    @staticmethod
    def _recovery_sample(
        *,
        ledger: DurableFeatureSnapshotLedger,
        child_postcommit_readback_at: str,
        child_durable_snapshot_id: str,
        enrichment_store: ImmutableSourcePayloadStore,
    ) -> ProfiledTrainingLedgerSampleV1:
        observed = _parse_clock(
            child_postcommit_readback_at,
            reason="PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_POSTCOMMIT_CLOCK_INVALID",
        )
        try:
            observed += timedelta(microseconds=1)
        except OverflowError:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_POSTCOMMIT_CLOCK_INVALID",
            )
        observed_text = _clock_text(
            observed,
            reason="PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_OBSERVATION_CLOCK_INVALID",
        )
        after_sequence = 0
        page_cursor: str | None = None
        while True:
            batch = load_profiled_training_ledger_v1(
                ledger=ledger,
                trusted_immutable_cost_store_root=enrichment_store.root_path,
                training_observed_at=observed_text,
                scan_limit=MAX_PROFILED_TRAINING_SCAN_ROWS,
                after_sequence=after_sequence,
                page_cursor=page_cursor,
            )
            matches = tuple(
                sample
                for sample in batch.samples
                if sample.durable_snapshot_id == child_durable_snapshot_id
            )
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_CHILD_DUPLICATE",
                )
            if not batch.has_remaining_strict_rows:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_CHILD_NOT_AUTHENTICATED",
                )
            after_sequence = batch.next_after_sequence
            page_cursor = batch.next_cursor

    def _recover_committed_pair(
        self,
        *,
        symbol: str,
        prior_coverage: Mapping[str, Any] | None,
        enrichment_store: ImmutableSourcePayloadStore,
        feature_ledger: DurableFeatureSnapshotLedger,
    ) -> _SymbolOutcome | None:
        receipt = _load_pair_recovery_receipt(
            _pair_recovery_receipt_path(self.data_root, symbol),
            expected_symbol=symbol,
            expected_cost_store_root=enrichment_store.root_path,
        )
        if receipt is None or not feature_ledger.path.is_file():
            return None
        if (
            prior_coverage is not None
            and prior_coverage.get("durable_snapshot_id") == receipt["child_durable_snapshot_id"]
        ):
            return None
        try:
            parent = feature_ledger.get_snapshot(receipt["parent_durable_snapshot_id"])
            child = feature_ledger.get_snapshot(receipt["child_durable_snapshot_id"])
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledBaseFeaturePublisherV1StateError(
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_LEDGER_READ_FAILED"
            ) from exc
        if parent is None and child is None:
            # A crash before the atomic append leaves a harmless prepared
            # intent.  The next fresh pair may replace it.
            return None
        if parent is None or child is None:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PARTIAL_PAIR_QUARANTINED",
            )
        if prior_coverage is not None:
            prior_id = prior_coverage.get("durable_snapshot_id")
            try:
                prior = (
                    feature_ledger.get_snapshot(cast(str, prior_id))
                    if type(prior_id) is str
                    else None
                )
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledBaseFeaturePublisherV1StateError(
                    "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PRIOR_LEDGER_READ_FAILED"
                ) from exc
            if prior is None:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PRIOR_COVERAGE_MISSING",
                )
            if child.sequence <= prior.sequence:
                return None
        try:
            sample = self._recovery_sample(
                ledger=feature_ledger,
                child_postcommit_readback_at=child.postcommit_readback_at,
                child_durable_snapshot_id=receipt["child_durable_snapshot_id"],
                enrichment_store=enrichment_store,
            )
        except ProfiledTrainingLedgerLoaderV1Error as exc:
            raise ProfiledBaseFeaturePublisherV1StateError(
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_LOADER_AUTHENTICATION_FAILED",
                *exc.reasons,
            ) from exc
        child_record = child.record
        child_envelope = cast(dict[str, Any], child_record["frozen_envelope"])
        lineage = cast(dict[str, Any], child_envelope["source_lineage_material"])
        attestation = lineage.get(PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY)
        cost_binding = (
            attestation.get("cost_capture_binding") if type(attestation) is dict else None
        )
        if (
            parent.record.get("record_sha256") != receipt["parent_record_sha256"]
            or child_record.get("record_sha256") != receipt["child_record_sha256"]
            or parent.sequence + 1 != child.sequence
            or parent.append_transaction_id != child.append_transaction_id
            or parent.append_receipt_sha256 != child.append_receipt_sha256
            or parent.postcommit_receipt_sha256 != child.postcommit_receipt_sha256
            or parent.postcommit_readback_at != child.postcommit_readback_at
            or sample.sequence != child.sequence
            or sample.parent_durable_snapshot_id != receipt["parent_durable_snapshot_id"]
            or sample.parent_record_sha256 != receipt["parent_record_sha256"]
            or sample.record_sha256 != receipt["child_record_sha256"]
            or sample.append_transaction_id != child.append_transaction_id
            or sample.append_receipt_sha256 != child.append_receipt_sha256
            or sample.postcommit_receipt_sha256 != child.postcommit_receipt_sha256
            or type(attestation) is not dict
            or attestation.get("transform_configuration_sha256")
            != receipt["transform_configuration_sha256"]
            or type(cost_binding) is not dict
            or cost_binding.get("cost_capture_artifact_sha256")
            != receipt["cost_capture_artifact_sha256"]
            or cost_binding.get("immutable_cost_store_root") != str(enrichment_store.root_path)
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_SHARED_BINDING_INVALID",
            )
        detail = {
            "symbol": symbol,
            "classification": "AUTHENTICATED_PROFILED_TRAINING_PAIR_EXACT_REPLAY",
            "window_fingerprint_sha256": receipt["window_fingerprint_sha256"],
            "feature_cutoff": sample.feature_cutoff,
            "decision_time": sample.decision_time,
            "durable_snapshot_id": sample.durable_snapshot_id,
            "record_sha256": sample.record_sha256,
            "parent_durable_snapshot_id": sample.parent_durable_snapshot_id,
            "parent_record_sha256": sample.parent_record_sha256,
            "cost_capture_artifact_sha256": receipt["cost_capture_artifact_sha256"],
            "cost_store_root": str(enrichment_store.root_path),
            "legacy_recovery_receipt_observation": (
                _observe_legacy_pair_recovery_receipt(self.data_root, symbol)
            ),
            "feature_append": {
                "transaction_id": sample.append_transaction_id,
                "inserted_rows": 0,
                "duplicate_rows": 0,
                "parent_sequence": parent.sequence,
                "child_sequence": child.sequence,
                "append_receipt_sha256": sample.append_receipt_sha256,
                "postcommit_receipt_sha256": sample.postcommit_receipt_sha256,
                "postcommit_readback_at": sample.postcommit_readback_at,
                "transaction_committed": True,
                "transaction_readback_verified": True,
            },
            "recovery": {
                "classification": "STATE_LOSS_COMMITTED_PAIR_INDEPENDENTLY_AUTHENTICATED",
                "recovery_receipt_sha256": receipt["recovery_receipt_sha256"],
                "ledger_and_trusted_cost_cas_reopened": True,
                "cost_or_commission_recapture_performed": False,
                "feature_ledger_append_performed": False,
                "coverage_recovered_from_commit_receipt": True,
            },
            "authority": {
                "publisher_runtime_authority_granted": False,
                "parent_trainer_admission_authorized": False,
                "child_trainer_admission_authorized": True,
                "trainer_candidate_in_lineage": True,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
            },
            "legacy_feature_redis_write_performed": False,
        }
        return _SymbolOutcome(
            symbol=symbol,
            classification="AUTHENTICATED_PROFILED_TRAINING_PAIR_EXACT_REPLAY",
            window_fingerprint_sha256=cast(str, receipt["window_fingerprint_sha256"]),
            materialized_evidence_bytes=cast(int, receipt["materialized_evidence_bytes"]),
            detail=detail,
            coverage={
                "last_published_at": sample.postcommit_readback_at,
                "feature_cutoff": sample.feature_cutoff,
                "decision_time": sample.decision_time,
                "window_fingerprint_sha256": receipt["window_fingerprint_sha256"],
                "durable_snapshot_id": sample.durable_snapshot_id,
                "record_sha256": sample.record_sha256,
            },
        )

    def _recover_masked_parent(
        self,
        *,
        symbol: str,
        prior_coverage: Mapping[str, Any] | None,
        feature_ledger: DurableFeatureSnapshotLedger,
    ) -> _SymbolOutcome | None:
        """Recover an exact quarantined parent without rebuilding timestamped identity."""

        receipt = _load_masked_parent_recovery_receipt(
            _masked_parent_recovery_receipt_path(self.data_root, symbol),
            expected_symbol=symbol,
        )
        if receipt is None or not feature_ledger.path.is_file():
            return None
        parent_id = cast(str, receipt["parent_durable_snapshot_id"])
        if (
            prior_coverage is not None
            and prior_coverage.get("durable_snapshot_id") == parent_id
        ):
            return None
        try:
            parent = feature_ledger.get_snapshot(parent_id)
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledBaseFeaturePublisherV1StateError(
                "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_LEDGER_READ_FAILED"
            ) from exc
        if parent is None:
            # The durable intent may precede a crash before append.  A fresh
            # attempt may replace it; it never proves that a parent committed.
            return None
        if prior_coverage is not None:
            prior_id = prior_coverage.get("durable_snapshot_id")
            try:
                prior = (
                    feature_ledger.get_snapshot(cast(str, prior_id))
                    if type(prior_id) is str
                    else None
                )
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledBaseFeaturePublisherV1StateError(
                    "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_PRIOR_LEDGER_READ_FAILED"
                ) from exc
            if prior is None:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_PRIOR_COVERAGE_MISSING",
                )
            if parent.sequence <= prior.sequence:
                return None
        record = parent.record
        envelope = record.get("frozen_envelope")
        if type(envelope) is not dict:
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_PARENT_INVALID",
            )
        parent_envelope = cast(dict[str, Any], envelope)
        lineage = parent_envelope.get("source_lineage_material")
        authorization = (
            lineage.get("authorization") if type(lineage) is dict else None
        )
        mask_contract = _masked_cost_observation_contract()
        mask_binding = {
            "schema_version": "profiled_masked_cost_observation_binding_v1",
            "parent_durable_snapshot_id": parent_id,
            "parent_record_sha256": receipt["parent_record_sha256"],
            "window_fingerprint_sha256": receipt["window_fingerprint_sha256"],
            "decision_time": parent_envelope.get("tensor_decision_time"),
            "cost_observation": mask_contract,
        }
        decision_time = _parse_clock(
            parent_envelope.get("tensor_decision_time"),
            reason="PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_DECISION_CLOCK_INVALID",
        )
        postcommit_at = _parse_clock(
            parent.postcommit_readback_at,
            reason="PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_POSTCOMMIT_CLOCK_INVALID",
        )
        if (
            record.get("record_sha256") != receipt["parent_record_sha256"]
            or parent_envelope.get("symbol") != symbol
            or parent_envelope.get("ordered_feature_names")
            != list(PHYSICAL_ORDERED_FEATURE_NAMES)
            or any(
                name in cast(list[Any], parent_envelope["ordered_feature_names"])
                for name in CAUSAL_COST_ORDERED_FEATURE_NAMES
            )
            or parent_envelope.get("strict_training_eligible") is not False
            or type(authorization) is not dict
            or any(authorization.get(name) is not False for name in AUTHORITY_FIELDS)
            or parent_envelope.get("generated_at") != receipt["prepared_at"]
            or stable_sha256(mask_binding)
            != receipt["cost_observation_binding_sha256"]
            or postcommit_at < decision_time
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1StateError,
                "PROFILED_BASE_PUBLISHER_MASKED_RECOVERY_PARENT_BINDING_INVALID",
            )
        detail = {
            "symbol": symbol,
            "classification": "MASKED_COST_OBSERVATION_PARENT_EXACT_REPLAY",
            "window_fingerprint_sha256": receipt["window_fingerprint_sha256"],
            "feature_cutoff": parent_envelope["feature_cutoff"],
            "decision_time": parent_envelope["tensor_decision_time"],
            "append_after_prospective_decision_reverified": True,
            "durable_snapshot_id": parent_id,
            "record_sha256": receipt["parent_record_sha256"],
            "cost_observation": mask_contract,
            "cost_observation_binding_sha256": receipt[
                "cost_observation_binding_sha256"
            ],
            "cost_values_or_receipts_fabricated": False,
            "commission_capture_attempted": False,
            "cost_source_read_attempted": False,
            "materialized_evidence_bytes": receipt["materialized_evidence_bytes"],
            "feature_append": {
                "transaction_id": parent.append_transaction_id,
                "new_rows_inserted_this_cycle": False,
                "parent_sequence": parent.sequence,
                "append_receipt_sha256": parent.append_receipt_sha256,
                "postcommit_receipt_sha256": parent.postcommit_receipt_sha256,
                "postcommit_readback_at": parent.postcommit_readback_at,
                "transaction_committed": True,
                "transaction_readback_verified": True,
            },
            "recovery": {
                "classification": (
                    "STATE_LOSS_MASKED_PARENT_LEDGER_READBACK_VERIFIED"
                ),
                "recovery_receipt_sha256": receipt["recovery_receipt_sha256"],
                "ledger_reopened": True,
                "cost_or_commission_capture_performed": False,
                "feature_ledger_append_performed": False,
                "coverage_recovered_from_commit_receipt": True,
            },
            "authority": {
                "publisher_runtime_authority_granted": False,
                "parent_trainer_admission_authorized": False,
                "child_trainer_admission_authorized": False,
                "trainer_candidate_in_lineage": False,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
            },
            "legacy_feature_redis_write_performed": False,
        }
        return _SymbolOutcome(
            symbol=symbol,
            classification="MASKED_COST_OBSERVATION_PARENT_EXACT_REPLAY",
            window_fingerprint_sha256=cast(
                str,
                receipt["window_fingerprint_sha256"],
            ),
            materialized_evidence_bytes=cast(
                int,
                receipt["materialized_evidence_bytes"],
            ),
            detail=detail,
            coverage={
                "last_published_at": parent.postcommit_readback_at,
                "feature_cutoff": parent_envelope["feature_cutoff"],
                "decision_time": parent_envelope["tensor_decision_time"],
                "window_fingerprint_sha256": receipt["window_fingerprint_sha256"],
                "durable_snapshot_id": parent_id,
                "record_sha256": receipt["parent_record_sha256"],
            },
        )

    def _publish_symbol_once(
        self,
        *,
        symbol: str,
        prior_coverage: Mapping[str, Any] | None,
        source_store: ImmutableSourcePayloadStore,
        capture_set_store: ImmutableSourcePayloadStore,
        artifact_store: ImmutableSourcePayloadStore,
        enrichment_store: ImmutableSourcePayloadStore,
        feature_ledger: DurableFeatureSnapshotLedger,
    ) -> _SymbolOutcome:
        recovered = self._recover_masked_parent(
            symbol=symbol,
            prior_coverage=prior_coverage,
            feature_ledger=feature_ledger,
        )
        if recovered is not None:
            return recovered
        recovered = self._recover_committed_pair(
            symbol=symbol,
            prior_coverage=prior_coverage,
            enrichment_store=enrichment_store,
            feature_ledger=feature_ledger,
        )
        if recovered is not None:
            return recovered
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
        broker_commission_evidence: CredentiallessCommissionEvidence | None = None
        commission_evidence_status = "DIRECT_CAPTURE_NOT_YET_ATTEMPTED"
        commission_evidence_read_attempted = False
        if (
            self.commission_cost_mode
            == BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
        ):
            commission_evidence_read_attempted = True
            (
                broker_commission_evidence,
                commission_evidence_status,
            ) = self._broker_commission_evidence_for_parent(parent_record=record)
        elif self.commission_cost_mode == MASKED_COST_OBSERVATION_MODE:
            commission_evidence_status = "COMMISSION_EVIDENCE_NOT_CONFIGURED"
        use_masked_cost_observation = (
            self.commission_cost_mode == MASKED_COST_OBSERVATION_MODE
            or (
                self.commission_cost_mode
                == BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
                and broker_commission_evidence is None
            )
        )
        if use_masked_cost_observation:
            if existing_snapshot is not None and existing_snapshot.record != record:
                _fail(
                    ProfiledBaseFeaturePublisherV1StateError,
                    "PROFILED_BASE_PUBLISHER_MASKED_PARENT_EXISTING_RECORD_MISMATCH",
                )
            mask_contract = _masked_cost_observation_contract()
            mask_binding = {
                "schema_version": "profiled_masked_cost_observation_binding_v1",
                "parent_durable_snapshot_id": validation.durable_snapshot_id,
                "parent_record_sha256": validation.record_sha256,
                "window_fingerprint_sha256": fingerprint,
                "decision_time": contract["timestamps"]["decision_time"],
                "cost_observation": mask_contract,
            }
            mask_binding_sha256 = stable_sha256(mask_binding)
            parent_envelope = cast(dict[str, Any], record["frozen_envelope"])
            parent_record_bytes = len(_canonical_json_bytes(record))
            materialized_evidence_bytes = (
                projected_pair
                + int(capture_set.capture_set_manifest_byte_count)
                + len(transformed.artifact_json.encode("ascii"))
                + PAIR_LEDGER_RECORD_ACCOUNTING_MULTIPLIER * parent_record_bytes
                + len(_canonical_json_bytes(mask_binding))
                + sum(
                    len(result.entry.entry_json.encode("ascii"))
                    for result in append_results
                )
                + PAIR_AUXILIARY_CAS_SQLITE_ACCOUNTING_OVERHEAD_BYTES
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
            self._write_masked_parent_recovery_receipt(
                symbol=symbol,
                window_fingerprint_sha256=fingerprint,
                parent_durable_snapshot_id=validation.durable_snapshot_id,
                parent_record_sha256=validation.record_sha256,
                cost_observation_binding_sha256=mask_binding_sha256,
                prepared_at=cast(str, parent_envelope["generated_at"]),
                materialized_evidence_bytes=materialized_evidence_bytes,
            )
            try:
                feature_append = feature_ledger.append_snapshot(record)
                committed_parent = feature_ledger.get_snapshot(
                    validation.durable_snapshot_id
                )
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledBaseFeaturePublisherV1Error(
                    "PROFILED_BASE_PUBLISHER_MASKED_PARENT_APPEND_FAILED"
                ) from exc
            if (
                feature_append.attempted_rows != 1
                or feature_append.inserted_rows != 1
                or feature_append.duplicate_rows != 0
                or feature_append.transaction_committed is not True
                or feature_append.transaction_readback_verified is not True
                or committed_parent is None
                or committed_parent.record != record
                or committed_parent.append_transaction_id
                != feature_append.transaction_id
                or committed_parent.append_receipt_sha256
                != feature_append.append_receipt_sha256
                or committed_parent.postcommit_receipt_sha256
                != feature_append.postcommit_receipt_sha256
                or committed_parent.postcommit_readback_at
                != feature_append.postcommit_readback_at
                or any(getattr(validation, name) is not False for name in AUTHORITY_FIELDS)
            ):
                _fail(
                    ProfiledBaseFeaturePublisherV1Error,
                    "PROFILED_BASE_PUBLISHER_MASKED_PARENT_POSTCOMMIT_INVALID",
                )
            source_ledger_entries_after = len(source_ledger.read_entries())
            source_ledger_bytes_after = source_ledger.path.stat().st_size
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
                for timeframe, result in zip(
                    REQUIRED_TIMEFRAMES,
                    append_results,
                    strict=True,
                )
            ]
            classification = (
                "MASKED_COST_OBSERVATION_PARENT_EXACT_REPLAY"
                if existing_snapshot is not None
                else "MASKED_COST_OBSERVATION_PARENT_INSERTED"
            )
            detail = {
                "symbol": symbol,
                "classification": classification,
                "boundary_attempts": attempts,
                "window_fingerprint_sha256": fingerprint,
                "event_time": contract["timestamps"]["event_time"],
                "ingested_at": contract["timestamps"]["ingested_at"],
                "available_at": contract["timestamps"]["available_at"],
                "capture_generated_at": contract["timestamps"]["generated_at"],
                "feature_cutoff": parent_envelope["feature_cutoff"],
                "decision_time": parent_envelope["tensor_decision_time"],
                "decision_wait_completed_at": decision_wait_completed,
                "prospective_decision_wait_verified": True,
                "transform_available_at": transform_available_at,
                "parent_record_generated_at": parent_envelope["generated_at"],
                "execution_time": contract["timestamps"]["execution_time"],
                "capture_set_sha256": validation.capture_set_sha256,
                "transform_artifact_sha256": validation.transform_artifact_sha256,
                "durable_snapshot_id": validation.durable_snapshot_id,
                "record_sha256": validation.record_sha256,
                "frozen_envelope_sha256": record["frozen_envelope_sha256"],
                "source_lineage_sha256": validation.source_lineage_sha256,
                "physical_model_vector_sha256": (
                    validation.physical_model_vector_sha256
                ),
                "logical_model_vector_sha256": (
                    validation.logical_projection.model_vector_sha256
                ),
                "lineage_binding_sha256": validation.lineage_binding_sha256,
                "cost_observation": mask_contract,
                "cost_observation_binding_sha256": mask_binding_sha256,
                "cost_values_or_receipts_fabricated": False,
                "commission_capture_attempted": False,
                "commission_evidence_read_attempted": commission_evidence_read_attempted,
                "commission_evidence_status": commission_evidence_status,
                "commission_evidence_authenticated": False,
                "cost_source_read_attempted": False,
                "source_provenance_shard_index": shard_index,
                "source_provenance_shard_rolled": rolled,
                "source_pair_projected_ledger_bytes": projected_pair,
                "materialized_evidence_bytes": materialized_evidence_bytes,
                "source_ledger_entries_after": source_ledger_entries_after,
                "source_ledger_entry_limit": MAX_LEDGER_ENTRIES,
                "source_ledger_remaining_entries": (
                    MAX_LEDGER_ENTRIES - source_ledger_entries_after
                ),
                "source_ledger_bytes_after": source_ledger_bytes_after,
                "source_ledger_byte_limit": MAX_LEDGER_BYTES,
                "source_ledger_remaining_bytes": (
                    MAX_LEDGER_BYTES - source_ledger_bytes_after
                ),
                "source_appends": source_details,
                "feature_append": {
                    "transaction_id": feature_append.transaction_id,
                    "original_transaction_inserted_rows": (
                        feature_append.inserted_rows
                    ),
                    "new_rows_inserted_this_cycle": (
                        existing_snapshot is None
                    ),
                    "parent_sequence": committed_parent.sequence,
                    "append_receipt_sha256": (
                        feature_append.append_receipt_sha256
                    ),
                    "postcommit_receipt_sha256": (
                        feature_append.postcommit_receipt_sha256
                    ),
                    "postcommit_readback_at": (
                        feature_append.postcommit_readback_at
                    ),
                    "transaction_committed": True,
                    "transaction_readback_verified": True,
                },
                "authority": {
                    "publisher_runtime_authority_granted": False,
                    "parent_trainer_admission_authorized": False,
                    "child_trainer_admission_authorized": False,
                    "trainer_candidate_in_lineage": False,
                    "prediction_authorized": False,
                    "paper_trading_authorized": False,
                    "live_execution_authorized": False,
                    "runtime_wired": False,
                },
                "legacy_feature_redis_write_performed": False,
            }
            return _SymbolOutcome(
                symbol=symbol,
                classification=classification,
                window_fingerprint_sha256=fingerprint,
                materialized_evidence_bytes=materialized_evidence_bytes,
                detail=detail,
                coverage={
                    "last_published_at": feature_append.postcommit_readback_at,
                    "feature_cutoff": parent_envelope["feature_cutoff"],
                    "decision_time": parent_envelope["tensor_decision_time"],
                    "window_fingerprint_sha256": fingerprint,
                    "durable_snapshot_id": validation.durable_snapshot_id,
                    "record_sha256": validation.record_sha256,
                },
            )
        if existing_snapshot is not None:
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                "PROFILED_BASE_PUBLISHER_EXISTING_35_PARENT_QUARANTINED_NOT_RETRO_ENRICHED",
            )
        cost_evidence, runtime_cost_auxiliary_cas_bytes = self._cost_evidence_for_parent(
            parent_record=record,
            enrichment_store=enrichment_store,
            decision_at=decision_at,
            commission_evidence=broker_commission_evidence,
        )
        runtime_notional_source = cast(
            dict[str, Any],
            cost_evidence.contract["notional_source"],
        )
        _, cost_artifact_available_at = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_COST_ARTIFACT_AVAILABLE_CLOCK_INVALID"
        )
        _, enrichment_available_at = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_ENRICHMENT_AVAILABLE_CLOCK_INVALID"
        )
        _, enrichment_generated_at = self._sample_clock(
            "PROFILED_BASE_PUBLISHER_ENRICHMENT_GENERATED_CLOCK_INVALID"
        )
        pair = build_profiled_training_enrichment_pair_v1(
            parent_record=record,
            transform_result=transformed,
            capture_set_contract=contract,
            capture_set_store=capture_set_store,
            parent_artifact_store=artifact_store,
            source_provenance_ledger=source_ledger,
            source_provenance_entries=source_entries,
            cost_evidence=cost_evidence,
            enrichment_store=enrichment_store,
            cost_artifact_available_at=cost_artifact_available_at,
            enrichment_available_at=enrichment_available_at,
            generated_at=enrichment_generated_at,
        )
        child_record = pair.child_record
        pair_record_bytes = len(_canonical_json_bytes(record)) + len(
            _canonical_json_bytes(child_record)
        )
        cost_object_bytes = sum(
            address.payload_byte_count
            for address, _payload in cost_evidence._exact_objects  # noqa: SLF001
        )
        materialized_evidence_bytes = (
            projected_pair
            + int(capture_set.capture_set_manifest_byte_count)
            + len(transformed.artifact_json.encode("ascii"))
            + PAIR_LEDGER_RECORD_ACCOUNTING_MULTIPLIER * pair_record_bytes
            + cost_object_bytes
            + runtime_cost_auxiliary_cas_bytes
            + 4 * 4
            + sum(len(result.entry.entry_json.encode("ascii")) for result in append_results)
            + PAIR_AUXILIARY_CAS_SQLITE_ACCOUNTING_OVERHEAD_BYTES
        )
        self._write_pair_recovery_receipt(
            symbol=symbol,
            window_fingerprint_sha256=fingerprint,
            pair=pair,
            enrichment_store=enrichment_store,
            materialized_evidence_bytes=materialized_evidence_bytes,
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
        feature_append = append_profiled_training_enrichment_pair_v1(
            ledger=feature_ledger,
            pair=pair,
        )
        if (
            feature_append.transaction_committed is not True
            or feature_append.transaction_readback_verified is not True
            or any(getattr(validation, name) is not False for name in AUTHORITY_FIELDS)
            or pair.prediction_authorized is not False
            or pair.paper_trading_authorized is not False
            or pair.live_execution_authorized is not False
            or pair.runtime_wired is not False
            or feature_append.runtime_wired is not False
        ):
            _fail(
                ProfiledBaseFeaturePublisherV1Error,
                "PROFILED_BASE_PUBLISHER_POSTCOMMIT_OR_AUTHORITY_INVALID",
            )
        parent_envelope = cast(dict[str, Any], pair.parent_record["frozen_envelope"])
        child_envelope = cast(dict[str, Any], child_record["frozen_envelope"])
        classification = "AUTHENTICATED_PROFILED_TRAINING_PAIR_INSERTED"
        source_ledger_entries_after = len(source_ledger.read_entries())
        source_ledger_bytes_after = source_ledger.path.stat().st_size
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
            "feature_cutoff": child_envelope["feature_cutoff"],
            "parent_model_feature_cutoff": parent_envelope["feature_cutoff"],
            "decision_time": child_envelope["tensor_decision_time"],
            "decision_wait_completed_at": decision_wait_completed,
            "prospective_decision_wait_verified": True,
            "transform_available_at": transform_available_at,
            "parent_record_generated_at": parent_envelope["generated_at"],
            "cost_artifact_available_at": cost_artifact_available_at,
            "enrichment_available_at": enrichment_available_at,
            "child_record_generated_at": child_envelope["generated_at"],
            "execution_time": contract["timestamps"]["execution_time"],
            "capture_set_sha256": validation.capture_set_sha256,
            "transform_artifact_sha256": validation.transform_artifact_sha256,
            "durable_snapshot_id": pair.child_durable_snapshot_id,
            "record_sha256": pair.child_record_sha256,
            "frozen_envelope_sha256": child_record["frozen_envelope_sha256"],
            "parent_durable_snapshot_id": pair.parent_durable_snapshot_id,
            "parent_record_sha256": pair.parent_record_sha256,
            "cost_capture_artifact_sha256": pair.cost_capture_artifact_sha256,
            "cost_store_root": str(enrichment_store.root_path),
            "legacy_recovery_receipt_observation": (
                _observe_legacy_pair_recovery_receipt(self.data_root, symbol)
            ),
            "source_lineage_sha256": validation.source_lineage_sha256,
            "physical_model_vector_sha256": validation.physical_model_vector_sha256,
            "logical_model_vector_sha256": (validation.logical_projection.model_vector_sha256),
            "lineage_binding_sha256": validation.lineage_binding_sha256,
            "source_provenance_shard_index": shard_index,
            "source_provenance_shard_rolled": rolled,
            "source_pair_projected_ledger_bytes": projected_pair,
            "materialized_evidence_bytes": materialized_evidence_bytes,
            "runtime_cost_auxiliary_cas_bytes": runtime_cost_auxiliary_cas_bytes,
            "expected_notional_usd": runtime_notional_source[
                "expected_notional_usd"
            ],
            "expected_notional_policy_id": runtime_notional_source["policy_id"],
            "expected_notional_policy_version": runtime_notional_source[
                "policy_version"
            ],
            "expected_notional_policy_source_key": runtime_notional_source[
                "policy_source_key"
            ],
            "commission_evidence_read_attempted": commission_evidence_read_attempted,
            "commission_evidence_status": (
                commission_evidence_status
                if commission_evidence_read_attempted
                else "DIRECT_CAPTURE_COMPLETED"
            ),
            "commission_evidence_authenticated": True,
            "pair_ledger_record_accounting_multiplier": (PAIR_LEDGER_RECORD_ACCOUNTING_MULTIPLIER),
            "pair_auxiliary_cas_sqlite_accounting_overhead_bytes": (
                PAIR_AUXILIARY_CAS_SQLITE_ACCOUNTING_OVERHEAD_BYTES
            ),
            "source_ledger_entries_after": source_ledger_entries_after,
            "source_ledger_entry_limit": MAX_LEDGER_ENTRIES,
            "source_ledger_remaining_entries": (MAX_LEDGER_ENTRIES - source_ledger_entries_after),
            "source_ledger_bytes_after": source_ledger_bytes_after,
            "source_ledger_byte_limit": MAX_LEDGER_BYTES,
            "source_ledger_remaining_bytes": (MAX_LEDGER_BYTES - source_ledger_bytes_after),
            "source_appends": source_details,
            "feature_append": {
                "transaction_id": feature_append.transaction_id,
                "inserted_rows": 2,
                "duplicate_rows": 0,
                "parent_sequence": feature_append.parent_sequence,
                "child_sequence": feature_append.child_sequence,
                "append_receipt_sha256": feature_append.append_receipt_sha256,
                "postcommit_receipt_sha256": feature_append.postcommit_receipt_sha256,
                "postcommit_readback_at": feature_append.postcommit_readback_at,
                "transaction_committed": feature_append.transaction_committed,
                "transaction_readback_verified": (feature_append.transaction_readback_verified),
            },
            "authority": {
                "publisher_runtime_authority_granted": False,
                "parent_trainer_admission_authorized": False,
                "child_trainer_admission_authorized": True,
                "trainer_candidate_in_lineage": True,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
            },
            "legacy_feature_redis_write_performed": False,
        }
        coverage = {
            "last_published_at": feature_append.postcommit_readback_at,
            "feature_cutoff": child_envelope["feature_cutoff"],
            "decision_time": child_envelope["tensor_decision_time"],
            "window_fingerprint_sha256": fingerprint,
            "durable_snapshot_id": pair.child_durable_snapshot_id,
            "record_sha256": pair.child_record_sha256,
        }
        return _SymbolOutcome(
            symbol=symbol,
            classification=classification,
            window_fingerprint_sha256=fingerprint,
            materialized_evidence_bytes=materialized_evidence_bytes,
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
        enrichment_store: ImmutableSourcePayloadStore,
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
                    enrichment_store=enrichment_store,
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
            except (
                ProfiledModelFeatureSnapshotRecordV1Error,
                ProfiledTrainingEnrichmentRecordV1Error,
                ProfiledBaseFeaturePublisherV1Error,
            ) as exc:
                last_reasons = _error_reasons(exc)
                missed = _cost_temporal_retryable(last_reasons)
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
        discovery = discover_canonical_profile_symbols_v1(
            self.redis_client,
            atomic_reader=self.atomic_redis_reader,
        )
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
            source_store, capture_set_store, artifact_store, enrichment_store = self._stores()
            feature_ledger: DurableFeatureSnapshotLedger | None = (
                self._feature_ledger
                if self._feature_ledger is not None
                else DurableFeatureSnapshotLedger(self.feature_ledger_path)
            )
        else:
            source_store = capture_set_store = artifact_store = enrichment_store = None
            feature_ledger = None
        published: list[dict[str, Any]] = []
        replayed: list[dict[str, Any]] = []
        masked_cost_observations: list[dict[str, Any]] = []
        masked_cost_replays: list[dict[str, Any]] = []
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
        cycle_start_owned_durable_bytes = self._owned_durable_footprint_bytes()
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
                > decision.available_write_credit_bytes
            ):
                resource_deferred.extend(planned_selection[selection_index:])
                break
            selected.append(symbol)
            rotation_last_attempted[symbol] = selection_at
            symbol_started = self.monotonic()
            attempt_start_owned_durable_bytes = self._owned_durable_footprint_bytes()
            materialized = False
            try:
                if (
                    source_store is None
                    or capture_set_store is None
                    or artifact_store is None
                    or enrichment_store is None
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
                    enrichment_store=enrichment_store,
                    feature_ledger=feature_ledger,
                )
                if outcome.classification == "UNCHANGED_FINALIZED_WINDOWS":
                    skipped.append(outcome.detail)
                elif outcome.classification == "MASKED_COST_OBSERVATION_PARENT_INSERTED":
                    masked_cost_observations.append(outcome.detail)
                    materialized = True
                    materialized_cycle_evidence_bytes += outcome.materialized_evidence_bytes
                    materialized_cycle_publication_count += 1
                elif outcome.classification == "MASKED_COST_OBSERVATION_PARENT_EXACT_REPLAY":
                    masked_cost_replays.append(outcome.detail)
                    if outcome.materialized_evidence_bytes > 0:
                        materialized_cycle_evidence_bytes += outcome.materialized_evidence_bytes
                        materialized_cycle_publication_count += 1
                        materialized_publication_elapsed += (
                            decision.estimated_seconds_per_symbol
                        )
                elif outcome.classification.endswith("EXACT_REPLAY"):
                    replayed.append(outcome.detail)
                    if outcome.materialized_evidence_bytes > 0:
                        # Recover the byte/count observation lost with the
                        # crashed state write.  The original elapsed time is
                        # unavailable, so charge the pre-cycle adaptive
                        # estimate.  This preserves the observed mean instead
                        # of letting a fast readback replay manufacture extra
                        # publication throughput.
                        materialized_cycle_evidence_bytes += outcome.materialized_evidence_bytes
                        materialized_cycle_publication_count += 1
                        materialized_publication_elapsed += decision.estimated_seconds_per_symbol
                else:
                    published.append(outcome.detail)
                    materialized = True
                    materialized_cycle_evidence_bytes += outcome.materialized_evidence_bytes
                    materialized_cycle_publication_count += 1
                if outcome.coverage is not None:
                    coverage[symbol] = outcome.coverage
            except Exception as exc:  # noqa: BLE001 - isolate every symbol
                reasons = _error_reasons(exc)
                failed_owned_durable_bytes = self._owned_durable_footprint_bytes()
                try:
                    _failed_total, _failed_used, failed_disk_free = self._disk_sample()
                except ProfiledBaseFeaturePublisherV1Error:
                    failed_disk_free = current_disk_free
                failed_materialized_bytes = max(
                    0,
                    failed_owned_durable_bytes - attempt_start_owned_durable_bytes,
                )
                if failed_materialized_bytes > 0:
                    materialized = True
                    materialized_cycle_evidence_bytes += failed_materialized_bytes
                    materialized_cycle_publication_count += 1
                    cycle_disk_consumption_high_water = max(
                        cycle_disk_consumption_high_water,
                        max(0, cycle_start_disk_free - failed_disk_free),
                    )
                failures.append(
                    {
                        "symbol": symbol,
                        "stage": (
                            "MASKED_COST_OBSERVATION_PARENT_PUBLICATION"
                            if self.commission_cost_mode == MASKED_COST_OBSERVATION_MODE
                            else "AUTHENTICATED_PROFILED_TRAINING_PAIR_PUBLICATION"
                        ),
                        "reasons": list(reasons),
                        "materialized_evidence_bytes": failed_materialized_bytes,
                        "orphan_feature_ledger_record_appended": False,
                        "coverage_advanced": False,
                        "in_cycle_temporal_retryable": _cost_temporal_retryable(reasons),
                        "retryable": isinstance(
                            exc,
                            CanonicalOhlcvAtomicCaptureError
                            | CanonicalOhlcvMultitimeframeCaptureSetV1Error
                            | TrainerSourceProvenanceLedgerV4Error
                            | FeatureSnapshotLedgerError
                            | ProfiledTrainingEnrichmentRecordV1Error,
                        )
                        or (
                            COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED in reasons
                            and not any(
                                fragment in reason.upper()
                                for reason in reasons
                                for fragment in COST_OPERATOR_BLOCKER_REASON_FRAGMENTS
                            )
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
        final_owned_durable_bytes = self._owned_durable_footprint_bytes()
        cycle_owned_durable_growth = max(
            0,
            final_owned_durable_bytes - cycle_start_owned_durable_bytes,
        )
        evidence_delta = max(
            materialized_cycle_evidence_bytes,
            cycle_owned_durable_growth,
        )
        observations = cast(dict[str, Any], state["observations"])
        observations["cycle_count"] += 1
        if materialized_cycle_publication_count > 0:
            observations["materialized_publication_count"] += materialized_cycle_publication_count
            observations["materialized_publication_elapsed_seconds"] = (
                float(observations["materialized_publication_elapsed_seconds"])
                + materialized_publication_elapsed
            )
            # Attribute only deterministic artifacts and growth under paths
            # this publisher owns. Shared-filesystem traffic still binds live
            # headroom/backpressure, but cannot poison the per-symbol mean.
            # Failed durable writes remain visible in the owned-path delta.
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
            f"DYNAMIC_SELECTION_UNIVERSE_{discovery.universe_status}"
            if discovery.universe_status != "VALID"
            else "NO_ELIGIBLE_SYMBOLS"
            if not discovery.eligible_symbols
            else "RESOURCE_HEADROOM_HOLD"
            if not selected and not resource_deferred
            else "CYCLE_WRITE_BUDGET_BACKPRESSURE_HOLD"
            if not selected and resource_deferred
            else "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"
            if selected_failure_count > 0
            else "CYCLE_COMPLETE_MASKED_COST_OBSERVATIONS"
            if masked_cost_observations or masked_cost_replays
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
            "dynamic_selection_universe": {
                "schema_version": "profiled_base_dynamic_selection_universe_v1",
                "source_key": DYNAMIC_SYMBOL_SELECTION_KEY,
                "status": discovery.universe_status,
                "reason": discovery.universe_reason,
                "server_observed_at": discovery.universe_server_observed_at,
                "source_pttl_ms": discovery.universe_pttl_ms,
                "availability_contract": "POSITIVE_SOURCE_OWNED_REDIS_PTTL",
                "symbol_count": len(discovery.universe_symbols),
                "symbols": list(discovery.universe_symbols),
                "rejected_symbol_count": len(discovery.universe_rejected_symbols),
                "rejected_symbols": list(discovery.universe_rejected_symbols),
                "rejected_symbol_reason": (
                    "SYMBOL_FORMAT_NOT_CANONICAL_ASCII_RUNTIME_SYMBOL"
                    if discovery.universe_rejected_symbols
                    else None
                ),
                "ohlcv_discovered_excluded_count": len(discovery.universe_excluded_symbols),
                "ohlcv_discovered_excluded_symbols": list(discovery.universe_excluded_symbols),
                "selection_metadata_only": True,
                "trainer_evidence_or_authority_conferred": False,
            },
            "selected_symbol_count": len(selected),
            "selected_symbols": list(selected),
            "resource_deferred_symbol_count": len(resource_deferred),
            "resource_deferred_symbols": resource_deferred,
            "published_symbol_count": len(published),
            "published_symbols": [item["symbol"] for item in published],
            "exact_replay_symbol_count": len(replayed),
            "exact_replay_symbols": [item["symbol"] for item in replayed],
            "masked_cost_observation_symbol_count": len(masked_cost_observations),
            "masked_cost_observation_symbols": [
                item["symbol"] for item in masked_cost_observations
            ],
            "masked_cost_observation_replay_symbol_count": len(masked_cost_replays),
            "masked_cost_observation_replay_symbols": [
                item["symbol"] for item in masked_cost_replays
            ],
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
            "cycle_owned_durable_growth_bytes": cycle_owned_durable_growth,
            "evidence_accounting_method": (
                "MAX_DETERMINISTIC_AUTHENTICATED_ARTIFACT_BYTES_AND_"
                "PUBLISHER_OWNED_DURABLE_PATH_GROWTH"
            ),
            "coverage": coverage_status,
            "rotation_last_attempted_at": {
                symbol: rotation_last_attempted.get(symbol) for symbol in discovery.eligible_symbols
            },
            "publications": [*published, *replayed],
            "masked_cost_observations": [
                *masked_cost_observations,
                *masked_cost_replays,
            ],
            "skips": skipped,
            "failures": failures,
            "authority": {name: False for name in AUTHORITY_FIELDS},
            "authority_semantics": {
                "publisher_runtime_authority_granted": False,
                "published_child_trainer_admission_authorized": bool(published or replayed),
                "masked_parent_trainer_admission_authorized": False,
                "prediction_paper_live_authority_granted": False,
                "automatic_trainer_transition_authorized": False,
            },
            "commission_cost_mode": self.commission_cost_mode,
            "commission_credentials_available": (
                self.commission_cost_mode
                == AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE
            ),
            "commission_broker_reader_available": (
                self.commission_cost_mode
                == BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
            ),
            "exchange_credentials_loaded_by_publisher": (
                self.exchange_credentials_loaded_by_publisher
            ),
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
    "AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE",
    "BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE",
    "BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL",
    "CANONICAL_KEY_PREFIX",
    "COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED",
    "DECISION_TIMEFRAME",
    "DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS",
    "DISK_RESERVE_POLICY_V1",
    "DISK_RESERVE_PUBLICATION_UNITS",
    "DISK_RESERVE_TOTAL_FRACTION_DENOMINATOR",
    "DISK_RESERVE_TOTAL_FRACTION_NUMERATOR",
    "DYNAMIC_SYMBOL_SELECTION_KEY",
    "MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS",
    "MASKED_COST_OBSERVATION_MODE",
    "PROFILED_MASKED_COST_OBSERVATION_V1_SCHEMA_VERSION",
    "PROFILED_BASE_FEATURE_PUBLISHER_STATE_V1_SCHEMA_VERSION",
    "PROFILED_BASE_FEATURE_PUBLISHER_STATUS_V1_SCHEMA_VERSION",
    "PROFILED_BASE_FEATURE_PUBLISHER_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_ENRICHMENT_CAS_DIRECTORY",
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
    "pttl_derived_cost_recapture_target_v1",
    "select_source_shard_index_v1",
    "wait_for_prospective_decision_v1",
]
