"""Canonical authenticated 5m/1h OHLCV capture-set contract v1.

This boundary combines two already factory-authenticated canonical atomic
captures into the exact causal source window required by
``OHLCV_BOOTSTRAP_5M_1H_V1``: 71 closed 5m rows and 34 closed 1h rows.  Every
retained row remains bound to its exact payload CAS address and v4 source-read
receipt.  Historical Binance REST rows are permitted, but the latest
decision-bound row for each timeframe must be a finalized live Binance WSS
row.

The set distinguishes ``event_time``, ``ingested_at``, ``available_at``,
``generated_at``, ``feature_cutoff``, ``decision_time``, and
``execution_time``.  It rejects unfinished, future, stale, non-finite, or
lineage-invalid data and stores its deterministic canonical manifest in an
``ImmutableSourcePayloadStore``.

Authentication here is deliberately narrow: code-owned atomic-capture
construction, exact row receipts, and fresh CAS readback.  The hermetic replay
policy is hash-bound as a required downstream dependency, but this module does
not claim that hermetic replay ran, that Binance transport identity was
cryptographically authenticated, or that any trainer/prediction/execution
authority was granted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    CANONICAL_OHLCV_REQUIRED_PRODUCER_POLICY_ID,
    TYPED_NEGATIVE_POLICY_ID,
    AdaptiveOhlcvFeatureSelectionProfileV1,
    adaptive_ohlcv_feature_selection_profile_v1_contract,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvAtomicCaptureError,
    CanonicalOhlcvAtomicReceiptCapture,
    SelectedClosedCandleReceiptCapture,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_boundary_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_policy_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    EXISTING_CORE_CONTRACT_VERSION,
    EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
    TRUE_1H_TA_MINIMUM_ROWS,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    SourceReadReceiptV4,
    SourceReadReceiptV4Error,
    validate_source_read_receipt_v4,
)

CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION: Final = (
    "canonical_ohlcv_multitimeframe_capture_set_v1"
)
CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION: Final = (
    "canonical_ohlcv_multitimeframe_capture_set_manifest_v1"
)
CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID: Final = (
    "OHLCV_BOOTSTRAP_5M_1H_CAPTURE_SET_POLICY_V1"
)
CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256: Final = (
    "f8115e5c6c67909c5486c3d65d4489e60e2ecb5d3545f6d41f0d7ff1d4fd091b"
)
CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_EVIDENCE_CLASSIFICATION: Final = (
    "AUTHENTICATED_ATOMIC_CAPTURE_ROW_RECEIPT_AND_CAS_INTEGRITY_ONLY"
)
CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_DOWNSTREAM_STATUS: Final = (
    "NON_CONSUMABLE_HERMETIC_REPLAY_UNEXECUTED_NO_TRAINER_PREDICTION_OR_EXECUTION_AUTHORITY"
)

CAPTURE_SET_REQUIRED_TIMEFRAMES: Final = ("5m", "1h")
CAPTURE_SET_REQUIRED_LOOKBACKS: Final = (
    ("5m", EXISTING_CORE_MINIMUM_SOURCE_ROWS),
    ("1h", TRUE_1H_TA_MINIMUM_ROWS),
)
CAPTURE_SET_CLOCK_FIELDS: Final = (
    "event_time",
    "ingested_at",
    "available_at",
    "generated_at",
    "feature_cutoff",
    "decision_time",
    "execution_time",
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@{}+-]{0,511}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_MANIFEST_BYTES = 1024 * 1024
_CONSTRUCTION_TOKEN = object()

_AUTHORITY_FALSE_FIELDS = (
    "hermetic_replay_executed",
    "upstream_transport_authenticity_claimed",
    "multi_timeframe_atomic_read_claimed",
    "feature_snapshot_published",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)


class CanonicalOhlcvMultitimeframeCaptureSetV1Error(RuntimeError):
    """The capture set failed validation or immutable integrity checks."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(*reasons) from None


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _canonical_json_bytes(value: object, *, size_limit: int = _MAX_MANIFEST_BYTES) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("canonical_ohlcv_multitimeframe_canonical_encoding_failed")
    if not encoded or len(encoded) > size_limit:
        _fail("canonical_ohlcv_multitimeframe_manifest_size_invalid")
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    if parsed.strftime(_CLOCK_FORMAT) != value:
        _fail(reason)
    return parsed


def _ms_to_clock(value: int) -> str:
    if type(value) is not int or value < 0:
        _fail("canonical_ohlcv_multitimeframe_source_clock_invalid")
    try:
        parsed = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _fail("canonical_ohlcv_multitimeframe_source_clock_invalid")
    return parsed.strftime(_CLOCK_FORMAT)


def _clock_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + delta.microseconds // 1_000


def _expected_latest_finalized_close_ms(*, decision: datetime, timeframe: str) -> int:
    duration_ms = TIMEFRAME_DURATION_MS.get(timeframe)
    if type(duration_ms) is not int or duration_ms <= 0:
        _fail("canonical_ohlcv_multitimeframe_timeframe_invalid")
    expected = (_clock_to_ms(decision) // duration_ms) * duration_ms - 1
    if expected < 0:
        _fail("canonical_ohlcv_multitimeframe_expected_finalized_close_invalid")
    return expected


def _finite_number(value: object, *, reason: str, positive: bool = False) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(value):
        _fail(reason)
    if positive and value <= 0:
        _fail(reason)
    if not positive and value < 0:
        _fail(reason)
    return cast(int | float, value)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _validate_address(
    address: object,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    reason: str,
) -> SourcePayloadAddress:
    if type(address) is not SourcePayloadAddress:
        _fail(reason)
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != expected_sha256
        or address.payload_byte_count != expected_byte_count
        or not _valid_label(address.relative_path)
    ):
        _fail(reason)
    return address


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvCaptureSetRowV1:
    """One exact causal row identity, payload address, and source receipt."""

    capture_set_row_ordinal: int
    atomic_selected_ordinal: int
    atomic_source_index: int
    symbol: str
    timeframe: str
    candle_id: str
    candle_open_time_ms: int
    candle_close_time_ms: int
    event_time: str
    producer_event_time: str
    ingested_at: str
    available_at: str
    feature_cutoff: str
    source_transport: str
    source_sequence_id: str
    raw_payload_hash: str
    is_backfilled: bool
    open: int | float
    high: int | float
    low: int | float
    close: int | float
    volume: int | float
    quote_volume: int | float
    num_trades: int
    taker_buy_base_vol: int | float
    taker_buy_quote_vol: int | float
    exact_payload_sha256: str
    exact_payload_byte_count: int
    source_payload_address: SourcePayloadAddress
    source_read_receipt: SourceReadReceiptV4
    row_identity_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("canonical_ohlcv_multitimeframe_factory_construction_required")
        _validate_row(self)


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvTimeframeCaptureV1:
    """Exact required suffix for one physical timeframe."""

    timeframe: str
    duration_ms: int
    required_lookback_rows: int
    symbol: str
    source_key: str
    source_key_version: str
    atomic_batch_id: str
    atomic_capture_schema_version: str
    atomic_suffix_manifest_schema_version: str
    atomic_suffix_digest_sha256: str
    atomic_suffix_manifest_address: SourcePayloadAddress
    atomic_consumer_observed_at: str
    atomic_selected_start_ordinal: int
    rows: tuple[CanonicalOhlcvCaptureSetRowV1, ...]
    event_time: str
    ingested_at: str
    available_at: str
    feature_cutoff: str
    latest_candle_id: str
    ordered_row_identity_sha256s: tuple[str, ...]
    ordered_source_receipt_sha256s: tuple[str, ...]
    timeframe_capture_sha256: str
    typed_negative: bool
    _atomic_capture: CanonicalOhlcvAtomicReceiptCapture = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("canonical_ohlcv_multitimeframe_factory_construction_required")
        _validate_timeframe_capture(self)


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvMultitimeframeCaptureSetV1:
    """Factory-only immutable 5m/1h capture-set artifact."""

    schema_version: str
    manifest_schema_version: str
    policy_id: str
    policy_sha256: str
    evidence_classification: str
    downstream_status: str
    profile_id: str
    profile_sha256: str
    symbol: str
    required_timeframes: tuple[str, ...]
    required_lookbacks: tuple[tuple[str, int], ...]
    timeframe_captures: tuple[CanonicalOhlcvTimeframeCaptureV1, ...]
    event_time: str
    ingested_at: str
    available_at: str
    generated_at: str
    feature_cutoff: str
    decision_time: str
    execution_time: None
    typed_negative_timeframes: tuple[str, ...]
    typed_negative_policy_id: str
    atomic_capture_factory_verified: bool
    row_receipts_verified: bool
    row_cas_readback_verified: bool
    hermetic_policy_dependency_bound: bool
    audit_only: bool
    market_performance_thresholds_applied: bool
    hermetic_replay_executed: bool
    upstream_transport_authenticity_claimed: bool
    multi_timeframe_atomic_read_claimed: bool
    feature_snapshot_published: bool
    consumer_eligible: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    capture_set_sha256: str
    capture_set_manifest_byte_count: int
    capture_set_manifest_address: SourcePayloadAddress
    capture_set_manifest_json: str = field(repr=False)
    _capture_set_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("canonical_ohlcv_multitimeframe_factory_construction_required")
        _validate_capture_set(self)


def _row_identity_material_values(
    *,
    capture_set_row_ordinal: int,
    atomic_selected_ordinal: int,
    atomic_source_index: int,
    symbol: str,
    timeframe: str,
    candle_id: str,
    candle_open_time_ms: int,
    candle_close_time_ms: int,
    event_time: str,
    producer_event_time: str,
    ingested_at: str,
    available_at: str,
    feature_cutoff: str,
    source_transport: str,
    source_sequence_id: str,
    raw_payload_hash: str,
    is_backfilled: bool,
    open_price: int | float,
    high: int | float,
    low: int | float,
    close: int | float,
    volume: int | float,
    quote_volume: int | float,
    num_trades: int,
    taker_buy_base_vol: int | float,
    taker_buy_quote_vol: int | float,
    exact_payload_sha256: str,
    exact_payload_byte_count: int,
    source_payload_address: SourcePayloadAddress,
    source_read_receipt_sha256: str,
) -> dict[str, object]:
    return {
        "capture_set_row_ordinal": capture_set_row_ordinal,
        "atomic_selected_ordinal": atomic_selected_ordinal,
        "atomic_source_index": atomic_source_index,
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_id": candle_id,
        "candle_open_time_ms": candle_open_time_ms,
        "candle_close_time_ms": candle_close_time_ms,
        "event_time": event_time,
        "producer_event_time": producer_event_time,
        "ingested_at": ingested_at,
        "available_at": available_at,
        "feature_cutoff": feature_cutoff,
        "source_transport": source_transport,
        "source_sequence_id": source_sequence_id,
        "raw_payload_hash": raw_payload_hash,
        "is_backfilled": is_backfilled,
        "ohlcv": {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": quote_volume,
            "num_trades": num_trades,
            "taker_buy_base_vol": taker_buy_base_vol,
            "taker_buy_quote_vol": taker_buy_quote_vol,
        },
        "exact_payload_sha256": exact_payload_sha256,
        "exact_payload_byte_count": exact_payload_byte_count,
        "source_payload_address": _address_material(source_payload_address),
        "source_read_receipt_sha256": source_read_receipt_sha256,
    }


def _row_identity_material(row: CanonicalOhlcvCaptureSetRowV1) -> dict[str, object]:
    return _row_identity_material_values(
        capture_set_row_ordinal=row.capture_set_row_ordinal,
        atomic_selected_ordinal=row.atomic_selected_ordinal,
        atomic_source_index=row.atomic_source_index,
        symbol=row.symbol,
        timeframe=row.timeframe,
        candle_id=row.candle_id,
        candle_open_time_ms=row.candle_open_time_ms,
        candle_close_time_ms=row.candle_close_time_ms,
        event_time=row.event_time,
        producer_event_time=row.producer_event_time,
        ingested_at=row.ingested_at,
        available_at=row.available_at,
        feature_cutoff=row.feature_cutoff,
        source_transport=row.source_transport,
        source_sequence_id=row.source_sequence_id,
        raw_payload_hash=row.raw_payload_hash,
        is_backfilled=row.is_backfilled,
        open_price=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        quote_volume=row.quote_volume,
        num_trades=row.num_trades,
        taker_buy_base_vol=row.taker_buy_base_vol,
        taker_buy_quote_vol=row.taker_buy_quote_vol,
        exact_payload_sha256=row.exact_payload_sha256,
        exact_payload_byte_count=row.exact_payload_byte_count,
        source_payload_address=row.source_payload_address,
        source_read_receipt_sha256=row.source_read_receipt.receipt_sha256,
    )


def _row_manifest_material(row: CanonicalOhlcvCaptureSetRowV1) -> dict[str, object]:
    material = _row_identity_material(row)
    material["source_read_receipt_v4"] = row.source_read_receipt.receipt
    material["row_identity_sha256"] = row.row_identity_sha256
    return material


def _validate_row(row: CanonicalOhlcvCaptureSetRowV1) -> None:
    for value, reason in (
        (row.capture_set_row_ordinal, "canonical_ohlcv_multitimeframe_row_ordinal_invalid"),
        (row.atomic_selected_ordinal, "canonical_ohlcv_multitimeframe_atomic_ordinal_invalid"),
        (row.atomic_source_index, "canonical_ohlcv_multitimeframe_source_index_invalid"),
        (row.candle_open_time_ms, "canonical_ohlcv_multitimeframe_row_open_time_invalid"),
        (row.candle_close_time_ms, "canonical_ohlcv_multitimeframe_row_close_time_invalid"),
    ):
        if type(value) is not int or value < 0:
            _fail(reason)
    labels = (
        row.symbol,
        row.timeframe,
        row.candle_id,
        row.source_transport,
        row.source_sequence_id,
    )
    if any(not _valid_label(value) for value in labels):
        _fail("canonical_ohlcv_multitimeframe_row_label_invalid")
    if not _valid_sha256(row.raw_payload_hash) or not _valid_sha256(row.exact_payload_sha256):
        _fail("canonical_ohlcv_multitimeframe_row_digest_invalid")
    if type(row.exact_payload_byte_count) is not int or row.exact_payload_byte_count <= 0:
        _fail("canonical_ohlcv_multitimeframe_row_payload_count_invalid")
    duration_ms = TIMEFRAME_DURATION_MS.get(row.timeframe)
    if (
        type(duration_ms) is not int
        or row.candle_open_time_ms % duration_ms != 0
        or row.candle_close_time_ms != row.candle_open_time_ms + duration_ms - 1
    ):
        _fail("canonical_ohlcv_multitimeframe_row_interval_invalid")
    parsed = {
        "event_time": _parse_clock(
            row.event_time,
            reason="canonical_ohlcv_multitimeframe_row_event_time_invalid",
        ),
        "producer_event_time": _parse_clock(
            row.producer_event_time,
            reason="canonical_ohlcv_multitimeframe_row_producer_event_time_invalid",
        ),
        "ingested_at": _parse_clock(
            row.ingested_at,
            reason="canonical_ohlcv_multitimeframe_row_ingested_at_invalid",
        ),
        "available_at": _parse_clock(
            row.available_at,
            reason="canonical_ohlcv_multitimeframe_row_available_at_invalid",
        ),
        "feature_cutoff": _parse_clock(
            row.feature_cutoff,
            reason="canonical_ohlcv_multitimeframe_row_feature_cutoff_invalid",
        ),
    }
    close_clock = _parse_clock(
        _ms_to_clock(row.candle_close_time_ms),
        reason="canonical_ohlcv_multitimeframe_row_close_time_invalid",
    )
    if parsed["event_time"] != close_clock or parsed["feature_cutoff"] != close_clock:
        _fail("canonical_ohlcv_multitimeframe_row_economic_clock_binding_invalid")
    if not (
        parsed["event_time"]
        <= parsed["producer_event_time"]
        <= parsed["ingested_at"]
        <= parsed["available_at"]
    ):
        _fail("canonical_ohlcv_multitimeframe_row_causal_clock_order_invalid")
    if row.source_transport == "binance_wss":
        if row.is_backfilled is not False:
            _fail("canonical_ohlcv_multitimeframe_wss_backfill_invalid")
    elif row.source_transport == "binance_rest":
        if row.is_backfilled is not True:
            _fail("canonical_ohlcv_multitimeframe_rest_history_invalid")
    else:
        _fail("canonical_ohlcv_multitimeframe_row_transport_invalid")
    open_price = _finite_number(
        row.open,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
        positive=True,
    )
    high = _finite_number(
        row.high,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
        positive=True,
    )
    low = _finite_number(
        row.low,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
        positive=True,
    )
    close = _finite_number(
        row.close,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
        positive=True,
    )
    volume = _finite_number(
        row.volume,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
    )
    quote_volume = _finite_number(
        row.quote_volume,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
    )
    taker_buy_base = _finite_number(
        row.taker_buy_base_vol,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
    )
    taker_buy_quote = _finite_number(
        row.taker_buy_quote_vol,
        reason="canonical_ohlcv_multitimeframe_row_ohlcv_nonfinite",
    )
    if (
        type(row.num_trades) is not int
        or row.num_trades < 0
        or high < max(open_price, close)
        or low > min(open_price, close)
        or low > high
        or taker_buy_base > volume
        or taker_buy_quote > quote_volume
    ):
        _fail("canonical_ohlcv_multitimeframe_row_ohlcv_invariant_invalid")
    _validate_address(
        row.source_payload_address,
        expected_sha256=row.exact_payload_sha256,
        expected_byte_count=row.exact_payload_byte_count,
        reason="canonical_ohlcv_multitimeframe_row_cas_address_invalid",
    )
    if type(row.source_read_receipt) is not SourceReadReceiptV4:
        _fail("canonical_ohlcv_multitimeframe_row_receipt_type_invalid")
    try:
        validated_receipt = validate_source_read_receipt_v4(row.source_read_receipt.receipt)
    except SourceReadReceiptV4Error as exc:
        raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
            "canonical_ohlcv_multitimeframe_row_receipt_invalid"
        ) from exc
    receipt = validated_receipt.receipt
    expected_source_label = f"ohlcv_closed:binance:{row.symbol}:{row.timeframe}:{row.candle_id}"
    expected_receipt_values = (
        (receipt["source_label"], expected_source_label),
        (receipt["payload_type"], CANONICAL_OHLCV_ROW_PAYLOAD_TYPE),
        (receipt["payload_sha256"], row.exact_payload_sha256),
        (receipt["payload_byte_count"], row.exact_payload_byte_count),
        (receipt["economic_event_time"], row.event_time),
        (receipt["producer_event_time"], row.producer_event_time),
        (receipt["ingested_at"], row.ingested_at),
        (receipt["available_at"], row.available_at),
        (receipt["feature_cutoff"], row.feature_cutoff),
        (receipt["receipt_sha256"], row.source_read_receipt.receipt_sha256),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in expected_receipt_values
    ):
        _fail("canonical_ohlcv_multitimeframe_row_receipt_binding_invalid")
    expected_identity = _sha256(_row_identity_material(row))
    if row.row_identity_sha256 != expected_identity:
        _fail("canonical_ohlcv_multitimeframe_row_identity_sha256_invalid")


def _timeframe_material_values(
    *,
    timeframe: str,
    duration_ms: int,
    required_lookback_rows: int,
    symbol: str,
    source_key: str,
    source_key_version: str,
    atomic_batch_id: str,
    atomic_suffix_digest_sha256: str,
    atomic_suffix_manifest_address: SourcePayloadAddress,
    atomic_consumer_observed_at: str,
    atomic_selected_start_ordinal: int,
    rows: tuple[CanonicalOhlcvCaptureSetRowV1, ...],
    event_time: str,
    ingested_at: str,
    available_at: str,
    feature_cutoff: str,
    latest_candle_id: str,
    ordered_row_identity_sha256s: tuple[str, ...],
    ordered_source_receipt_sha256s: tuple[str, ...],
    typed_negative: bool,
) -> dict[str, object]:
    return {
        "timeframe": timeframe,
        "duration_ms": duration_ms,
        "required_lookback_rows": required_lookback_rows,
        "symbol": symbol,
        "source_key": source_key,
        "source_key_version": source_key_version,
        "atomic_batch_id": atomic_batch_id,
        "atomic_capture_schema_version": CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        "atomic_suffix_manifest_schema_version": CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
        "atomic_suffix_digest_sha256": atomic_suffix_digest_sha256,
        "atomic_suffix_manifest_address": _address_material(atomic_suffix_manifest_address),
        "atomic_consumer_observed_at": atomic_consumer_observed_at,
        "atomic_selected_start_ordinal": atomic_selected_start_ordinal,
        "rows": [_row_manifest_material(row) for row in rows],
        "event_time": event_time,
        "ingested_at": ingested_at,
        "available_at": available_at,
        "feature_cutoff": feature_cutoff,
        "latest_candle_id": latest_candle_id,
        "ordered_row_identity_sha256s": list(ordered_row_identity_sha256s),
        "ordered_source_receipt_sha256s": list(ordered_source_receipt_sha256s),
        "typed_negative": typed_negative,
    }


def _timeframe_material(capture: CanonicalOhlcvTimeframeCaptureV1) -> dict[str, object]:
    material = _timeframe_material_values(
        timeframe=capture.timeframe,
        duration_ms=capture.duration_ms,
        required_lookback_rows=capture.required_lookback_rows,
        symbol=capture.symbol,
        source_key=capture.source_key,
        source_key_version=capture.source_key_version,
        atomic_batch_id=capture.atomic_batch_id,
        atomic_suffix_digest_sha256=capture.atomic_suffix_digest_sha256,
        atomic_suffix_manifest_address=capture.atomic_suffix_manifest_address,
        atomic_consumer_observed_at=capture.atomic_consumer_observed_at,
        atomic_selected_start_ordinal=capture.atomic_selected_start_ordinal,
        rows=capture.rows,
        event_time=capture.event_time,
        ingested_at=capture.ingested_at,
        available_at=capture.available_at,
        feature_cutoff=capture.feature_cutoff,
        latest_candle_id=capture.latest_candle_id,
        ordered_row_identity_sha256s=capture.ordered_row_identity_sha256s,
        ordered_source_receipt_sha256s=capture.ordered_source_receipt_sha256s,
        typed_negative=capture.typed_negative,
    )
    material["timeframe_capture_sha256"] = capture.timeframe_capture_sha256
    return material


def _validate_timeframe_capture(capture: CanonicalOhlcvTimeframeCaptureV1) -> None:
    expected_lookbacks = dict(CAPTURE_SET_REQUIRED_LOOKBACKS)
    expected_rows = expected_lookbacks.get(capture.timeframe)
    expected_duration = TIMEFRAME_DURATION_MS.get(capture.timeframe)
    if (
        expected_rows is None
        or capture.required_lookback_rows != expected_rows
        or capture.duration_ms != expected_duration
        or capture.typed_negative is not False
    ):
        _fail("canonical_ohlcv_multitimeframe_timeframe_contract_invalid")
    if not _valid_label(capture.symbol) or not _valid_label(capture.source_key):
        _fail("canonical_ohlcv_multitimeframe_timeframe_label_invalid")
    expected_key = f"v2:market:ohlcv_closed:binance:{capture.symbol}:{capture.timeframe}"
    if capture.source_key != expected_key:
        _fail("canonical_ohlcv_multitimeframe_timeframe_source_key_invalid")
    if (
        capture.atomic_capture_schema_version != CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION
        or capture.atomic_suffix_manifest_schema_version
        != CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
        or not _valid_label(capture.source_key_version)
        or not _valid_label(capture.atomic_batch_id)
        or not _valid_sha256(capture.atomic_suffix_digest_sha256)
    ):
        _fail("canonical_ohlcv_multitimeframe_atomic_binding_invalid")
    _validate_address(
        capture.atomic_suffix_manifest_address,
        expected_sha256=capture.atomic_suffix_manifest_address.payload_sha256,
        expected_byte_count=capture.atomic_suffix_manifest_address.payload_byte_count,
        reason="canonical_ohlcv_multitimeframe_atomic_manifest_address_invalid",
    )
    if (
        type(capture.atomic_selected_start_ordinal) is not int
        or capture.atomic_selected_start_ordinal < 0
    ):
        _fail("canonical_ohlcv_multitimeframe_atomic_start_invalid")
    if type(capture.rows) is not tuple or len(capture.rows) != expected_rows:
        _fail("canonical_ohlcv_multitimeframe_exact_lookback_required")
    if any(type(row) is not CanonicalOhlcvCaptureSetRowV1 for row in capture.rows):
        _fail("canonical_ohlcv_multitimeframe_row_type_invalid")
    for row in capture.rows:
        _validate_row(row)
    if tuple(row.capture_set_row_ordinal for row in capture.rows) != tuple(range(expected_rows)):
        _fail("canonical_ohlcv_multitimeframe_row_order_invalid")
    if tuple(row.atomic_selected_ordinal for row in capture.rows) != tuple(
        range(
            capture.atomic_selected_start_ordinal,
            capture.atomic_selected_start_ordinal + expected_rows,
        )
    ):
        _fail("canonical_ohlcv_multitimeframe_atomic_row_order_invalid")
    if any(
        row.symbol != capture.symbol or row.timeframe != capture.timeframe for row in capture.rows
    ):
        _fail("canonical_ohlcv_multitimeframe_row_scope_invalid")
    if len({row.candle_id for row in capture.rows}) != expected_rows:
        _fail("canonical_ohlcv_multitimeframe_duplicate_row_identity")
    for earlier, later in zip(capture.rows, capture.rows[1:], strict=False):
        if (
            later.candle_open_time_ms - earlier.candle_open_time_ms != capture.duration_ms
            or later.candle_close_time_ms - earlier.candle_close_time_ms != capture.duration_ms
        ):
            _fail("canonical_ohlcv_multitimeframe_noncontiguous_history")
    latest = capture.rows[-1]
    if latest.source_transport != "binance_wss" or latest.is_backfilled is not False:
        _fail("canonical_ohlcv_multitimeframe_latest_live_wss_required")
    expected_row_hashes = tuple(row.row_identity_sha256 for row in capture.rows)
    expected_receipt_hashes = tuple(row.source_read_receipt.receipt_sha256 for row in capture.rows)
    if (
        capture.ordered_row_identity_sha256s != expected_row_hashes
        or capture.ordered_source_receipt_sha256s != expected_receipt_hashes
    ):
        _fail("canonical_ohlcv_multitimeframe_timeframe_lineage_invalid")
    derived_event = _ms_to_clock(latest.candle_close_time_ms)
    derived_ingested = max(
        capture.rows, key=lambda row: _parse_clock(row.ingested_at, reason="x")
    ).ingested_at
    derived_available = max(
        capture.rows, key=lambda row: _parse_clock(row.available_at, reason="x")
    ).available_at
    expected_clocks = (
        (capture.event_time, derived_event),
        (capture.ingested_at, derived_ingested),
        (capture.available_at, derived_available),
        (capture.feature_cutoff, derived_event),
        (capture.latest_candle_id, latest.candle_id),
    )
    if any(actual != expected for actual, expected in expected_clocks):
        _fail("canonical_ohlcv_multitimeframe_timeframe_clock_binding_invalid")
    if type(capture._atomic_capture) is not CanonicalOhlcvAtomicReceiptCapture:
        _fail("canonical_ohlcv_multitimeframe_atomic_capture_type_invalid")
    try:
        atomic_rows = capture._atomic_capture.selected_candles
    except CanonicalOhlcvAtomicCaptureError as exc:
        raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
            "canonical_ohlcv_multitimeframe_atomic_capture_revalidation_failed"
        ) from exc
    if (
        capture._atomic_capture.source_key != capture.source_key
        or capture._atomic_capture.source_key_version != capture.source_key_version
        or capture._atomic_capture.atomic_batch_id != capture.atomic_batch_id
        or capture._atomic_capture.suffix_digest_sha256 != capture.atomic_suffix_digest_sha256
        or capture._atomic_capture.suffix_manifest_address != capture.atomic_suffix_manifest_address
        or capture._atomic_capture.consumer_observed_at != capture.atomic_consumer_observed_at
        or len(atomic_rows) < expected_rows
    ):
        _fail("canonical_ohlcv_multitimeframe_atomic_capture_binding_invalid")
    selected_atomic = atomic_rows[-expected_rows:]
    if capture.atomic_selected_start_ordinal != len(atomic_rows) - expected_rows:
        _fail("canonical_ohlcv_multitimeframe_atomic_start_invalid")
    for row, atomic in zip(capture.rows, selected_atomic, strict=True):
        if not _row_matches_atomic(row, atomic, capture._atomic_capture):
            _fail("canonical_ohlcv_multitimeframe_atomic_row_binding_invalid")
    material = _timeframe_material(capture)
    supplied_hash = cast(str, material.pop("timeframe_capture_sha256"))
    if supplied_hash != _sha256(material):
        _fail("canonical_ohlcv_multitimeframe_timeframe_sha256_invalid")


def _row_matches_atomic(
    row: CanonicalOhlcvCaptureSetRowV1,
    atomic: SelectedClosedCandleReceiptCapture,
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> bool:
    source_row = capture.validated_window.rows[atomic.source_index]
    values = (
        (row.atomic_selected_ordinal, atomic.selected_ordinal),
        (row.atomic_source_index, atomic.source_index),
        (row.symbol, source_row.symbol),
        (row.timeframe, source_row.timeframe),
        (row.candle_id, atomic.candle_id),
        (row.candle_open_time_ms, atomic.candle_open_time_ms),
        (row.candle_close_time_ms, atomic.candle_close_time_ms),
        (row.event_time, _ms_to_clock(atomic.candle_close_time_ms)),
        (row.producer_event_time, _ms_to_clock(atomic.producer_event_time_ms)),
        (row.ingested_at, _ms_to_clock(atomic.ingested_at_ms)),
        (row.available_at, _ms_to_clock(atomic.available_at_ms)),
        (row.feature_cutoff, _ms_to_clock(atomic.candle_close_time_ms)),
        (row.source_transport, atomic.source),
        (row.source_sequence_id, atomic.source_sequence_id),
        (row.raw_payload_hash, atomic.raw_payload_hash),
        (row.is_backfilled, atomic.is_backfilled),
        (row.open, source_row.open),
        (row.high, source_row.high),
        (row.low, source_row.low),
        (row.close, source_row.close),
        (row.volume, source_row.volume),
        (row.quote_volume, source_row.quote_volume),
        (row.num_trades, source_row.num_trades),
        (row.taker_buy_base_vol, source_row.taker_buy_base_vol),
        (row.taker_buy_quote_vol, source_row.taker_buy_quote_vol),
        (row.exact_payload_sha256, atomic.exact_payload_sha256),
        (row.exact_payload_byte_count, atomic.exact_payload_byte_count),
        (row.source_payload_address, atomic.source_payload_address),
        (row.source_read_receipt.receipt_sha256, atomic.source_read_receipt.receipt_sha256),
    )
    return all(type(actual) is type(expected) and actual == expected for actual, expected in values)


_POLICY_MATERIAL: Final = {
    "schema_version": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION,
    "manifest_schema_version": (
        CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION
    ),
    "policy_id": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
    "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    "required_timeframes": list(CAPTURE_SET_REQUIRED_TIMEFRAMES),
    "required_lookbacks": [
        {"timeframe": timeframe, "row_count": count}
        for timeframe, count in CAPTURE_SET_REQUIRED_LOOKBACKS
    ],
    "native_5m_lookback_contract_version": EXISTING_CORE_CONTRACT_VERSION,
    "model_ta_dependency_contract_version": MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
    "model_ta_dependency_contract_sha256": MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    "atomic_capture_schema_version": CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    "atomic_suffix_manifest_schema_version": CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    "source_payload_address_schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    "source_read_receipt_schema_version": SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    "hermetic_replay_policy_schema_version": (
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION
    ),
    "hermetic_replay_policy_contract_version": (
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION
    ),
    "hermetic_replay_policy_id": CANONICAL_OHLCV_REQUIRED_PRODUCER_POLICY_ID,
    "hermetic_replay_policy_source_sha256": CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SOURCE_SHA256,
    "hermetic_replay_protocol_sha256": CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    "clock_fields": list(CAPTURE_SET_CLOCK_FIELDS),
    "clock_format": "UTC_MICROSECOND_Z",
    "latest_decision_bound_transport": "FINALIZED_LIVE_BINANCE_WSS_ONLY",
    "historical_transport": "EXACT_RECEIPT_BOUND_BINANCE_REST_OR_LIVE_BINANCE_WSS",
    "typed_negative_policy_id": TYPED_NEGATIVE_POLICY_ID,
    "required_timeframe_typed_negatives_allowed": False,
    "market_performance_thresholds_applied": False,
}


def canonical_ohlcv_multitimeframe_capture_set_v1_policy_contract() -> dict[str, Any]:
    """Return a detached copy of the pinned static capture-set policy."""

    computed = _sha256(_POLICY_MATERIAL)
    if computed != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256:
        _fail("canonical_ohlcv_multitimeframe_policy_sha256_drift")
    return cast(dict[str, Any], json.loads(_canonical_json_bytes(_POLICY_MATERIAL)))


def _capture_set_material_values(
    *,
    symbol: str,
    timeframe_captures: tuple[CanonicalOhlcvTimeframeCaptureV1, ...],
    event_time: str,
    ingested_at: str,
    available_at: str,
    generated_at: str,
    feature_cutoff: str,
    decision_time: str,
) -> dict[str, object]:
    return {
        "schema_version": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION,
        "manifest_schema_version": (
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION
        ),
        "policy_id": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
        "policy_sha256": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256,
        "evidence_classification": (
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_DOWNSTREAM_STATUS,
        "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        "symbol": symbol,
        "required_timeframes": list(CAPTURE_SET_REQUIRED_TIMEFRAMES),
        "required_lookbacks": [
            {"timeframe": timeframe, "row_count": count}
            for timeframe, count in CAPTURE_SET_REQUIRED_LOOKBACKS
        ],
        "timeframes": [_timeframe_material(capture) for capture in timeframe_captures],
        "timestamps": {
            "event_time": event_time,
            "ingested_at": ingested_at,
            "available_at": available_at,
            "generated_at": generated_at,
            "feature_cutoff": feature_cutoff,
            "decision_time": decision_time,
            "execution_time": None,
        },
        "timestamp_semantics": {
            "event_time": "LATEST_RETAINED_ECONOMIC_CANDLE_CLOSE",
            "ingested_at": "MAX_RETAINED_SOURCE_INGESTED_AT",
            "available_at": "MAX_RETAINED_SOURCE_AVAILABLE_AT",
            "generated_at": "CAPTURE_SET_CANONICAL_MANIFEST_GENERATED_AT",
            "feature_cutoff": "MAX_RETAINED_TIMEFRAME_FINAL_CANDLE_CLOSE",
            "decision_time": "PROSPECTIVE_SAMPLE_DECISION_TIME",
            "execution_time": "NONE_NO_EXECUTION_OCCURRED_OR_AUTHORIZED",
        },
        "typed_negatives": {
            "policy_id": TYPED_NEGATIVE_POLICY_ID,
            "timeframes": [],
            "count": 0,
            "required_timeframe_typed_negatives_allowed": False,
        },
        "proof_scope": {
            "atomic_capture_factory_verified": True,
            "row_receipts_verified": True,
            "row_cas_readback_verified": True,
            "hermetic_policy_dependency_bound": True,
            "hermetic_replay_executed": False,
            "upstream_transport_authenticity_claimed": False,
            "multi_timeframe_atomic_read_claimed": False,
        },
        "market_performance_thresholds": [],
        "market_performance_thresholds_applied": False,
        "authorization": {
            "audit_only": True,
            "feature_snapshot_published": False,
            "consumer_eligible": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
            "runtime_wired": False,
        },
    }


def _capture_set_material(
    capture_set: CanonicalOhlcvMultitimeframeCaptureSetV1,
) -> dict[str, object]:
    return _capture_set_material_values(
        symbol=capture_set.symbol,
        timeframe_captures=capture_set.timeframe_captures,
        event_time=capture_set.event_time,
        ingested_at=capture_set.ingested_at,
        available_at=capture_set.available_at,
        generated_at=capture_set.generated_at,
        feature_cutoff=capture_set.feature_cutoff,
        decision_time=capture_set.decision_time,
    )


def _validate_decision_relative_timeframe(
    capture: CanonicalOhlcvTimeframeCaptureV1,
    *,
    generated: datetime,
    decision: datetime,
) -> None:
    for row in capture.rows:
        close = _parse_clock(
            row.feature_cutoff,
            reason="canonical_ohlcv_multitimeframe_row_feature_cutoff_invalid",
        )
        available = _parse_clock(
            row.available_at,
            reason="canonical_ohlcv_multitimeframe_row_available_at_invalid",
        )
        if close >= decision:
            _fail("canonical_ohlcv_multitimeframe_unfinished_or_future_candle")
        if available > decision:
            _fail("canonical_ohlcv_multitimeframe_row_available_after_decision")
    observed = _parse_clock(
        capture.atomic_consumer_observed_at,
        reason="canonical_ohlcv_multitimeframe_atomic_consumer_clock_invalid",
    )
    if observed > generated:
        _fail("canonical_ohlcv_multitimeframe_atomic_observed_after_generated")
    latest = capture.rows[-1]
    expected_close = _expected_latest_finalized_close_ms(
        decision=decision,
        timeframe=capture.timeframe,
    )
    if latest.candle_close_time_ms != expected_close:
        _fail("canonical_ohlcv_multitimeframe_stale_latest_candle")
    if latest.source_transport != "binance_wss" or latest.is_backfilled is not False:
        _fail("canonical_ohlcv_multitimeframe_latest_live_wss_required")


def _validate_capture_set(capture_set: CanonicalOhlcvMultitimeframeCaptureSetV1) -> None:
    exact_scalars = (
        (capture_set.schema_version, CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION),
        (
            capture_set.manifest_schema_version,
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION,
        ),
        (capture_set.policy_id, CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID),
        (capture_set.policy_sha256, CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256),
        (
            capture_set.evidence_classification,
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_EVIDENCE_CLASSIFICATION,
        ),
        (
            capture_set.downstream_status,
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_DOWNSTREAM_STATUS,
        ),
        (capture_set.profile_id, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID),
        (capture_set.profile_sha256, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256),
    )
    if any(type(actual) is not str or actual != expected for actual, expected in exact_scalars):
        _fail("canonical_ohlcv_multitimeframe_static_binding_invalid")
    if not _valid_label(capture_set.symbol):
        _fail("canonical_ohlcv_multitimeframe_symbol_invalid")
    if (
        capture_set.required_timeframes != CAPTURE_SET_REQUIRED_TIMEFRAMES
        or capture_set.required_lookbacks != CAPTURE_SET_REQUIRED_LOOKBACKS
        or type(capture_set.timeframe_captures) is not tuple
        or tuple(item.timeframe for item in capture_set.timeframe_captures)
        != CAPTURE_SET_REQUIRED_TIMEFRAMES
    ):
        _fail("canonical_ohlcv_multitimeframe_inventory_invalid")
    if any(
        type(item) is not CanonicalOhlcvTimeframeCaptureV1
        for item in capture_set.timeframe_captures
    ):
        _fail("canonical_ohlcv_multitimeframe_timeframe_type_invalid")
    for item in capture_set.timeframe_captures:
        _validate_timeframe_capture(item)
        if item.symbol != capture_set.symbol:
            _fail("canonical_ohlcv_multitimeframe_symbol_binding_invalid")
    clocks = {
        "event_time": _parse_clock(
            capture_set.event_time,
            reason="canonical_ohlcv_multitimeframe_event_time_invalid",
        ),
        "ingested_at": _parse_clock(
            capture_set.ingested_at,
            reason="canonical_ohlcv_multitimeframe_ingested_at_invalid",
        ),
        "available_at": _parse_clock(
            capture_set.available_at,
            reason="canonical_ohlcv_multitimeframe_available_at_invalid",
        ),
        "generated_at": _parse_clock(
            capture_set.generated_at,
            reason="canonical_ohlcv_multitimeframe_generated_at_invalid",
        ),
        "feature_cutoff": _parse_clock(
            capture_set.feature_cutoff,
            reason="canonical_ohlcv_multitimeframe_feature_cutoff_invalid",
        ),
        "decision_time": _parse_clock(
            capture_set.decision_time,
            reason="canonical_ohlcv_multitimeframe_decision_time_invalid",
        ),
    }
    if capture_set.execution_time is not None:
        _fail("canonical_ohlcv_multitimeframe_execution_time_must_be_none")
    if not (
        clocks["event_time"]
        <= clocks["ingested_at"]
        <= clocks["available_at"]
        <= clocks["generated_at"]
        <= clocks["decision_time"]
    ):
        _fail("canonical_ohlcv_multitimeframe_capture_set_clock_order_invalid")
    if clocks["feature_cutoff"] >= clocks["decision_time"]:
        _fail("canonical_ohlcv_multitimeframe_feature_cutoff_not_before_decision")
    for item in capture_set.timeframe_captures:
        _validate_decision_relative_timeframe(
            item,
            generated=clocks["generated_at"],
            decision=clocks["decision_time"],
        )
    five_minute, one_hour = capture_set.timeframe_captures
    if _parse_clock(
        one_hour.feature_cutoff,
        reason="canonical_ohlcv_multitimeframe_1h_cutoff_invalid",
    ) > _parse_clock(
        five_minute.feature_cutoff,
        reason="canonical_ohlcv_multitimeframe_5m_cutoff_invalid",
    ):
        _fail("canonical_ohlcv_multitimeframe_cross_timeframe_order_invalid")
    all_rows = tuple(row for timeframe in capture_set.timeframe_captures for row in timeframe.rows)
    derived_event = max(
        capture_set.timeframe_captures,
        key=lambda item: _parse_clock(item.event_time, reason="x"),
    ).event_time
    derived_ingested = max(
        all_rows,
        key=lambda row: _parse_clock(row.ingested_at, reason="x"),
    ).ingested_at
    derived_available = max(
        all_rows,
        key=lambda row: _parse_clock(row.available_at, reason="x"),
    ).available_at
    derived_cutoff = max(
        capture_set.timeframe_captures,
        key=lambda item: _parse_clock(item.feature_cutoff, reason="x"),
    ).feature_cutoff
    if (
        capture_set.event_time != derived_event
        or capture_set.ingested_at != derived_ingested
        or capture_set.available_at != derived_available
        or capture_set.feature_cutoff != derived_cutoff
    ):
        _fail("canonical_ohlcv_multitimeframe_aggregate_clock_binding_invalid")
    if (
        capture_set.typed_negative_timeframes != ()
        or capture_set.typed_negative_policy_id != TYPED_NEGATIVE_POLICY_ID
    ):
        _fail("canonical_ohlcv_multitimeframe_required_typed_negative_forbidden")
    required_true = (
        capture_set.atomic_capture_factory_verified,
        capture_set.row_receipts_verified,
        capture_set.row_cas_readback_verified,
        capture_set.hermetic_policy_dependency_bound,
        capture_set.audit_only,
    )
    authority_false = tuple(getattr(capture_set, name) for name in _AUTHORITY_FALSE_FIELDS)
    if any(value is not True for value in required_true) or any(
        value is not False for value in authority_false
    ):
        _fail("canonical_ohlcv_multitimeframe_proof_or_authority_claim_invalid")
    if capture_set.market_performance_thresholds_applied is not False:
        _fail("canonical_ohlcv_multitimeframe_market_threshold_forbidden")
    material = _capture_set_material(capture_set)
    manifest_bytes = _canonical_json_bytes(material)
    expected_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if (
        capture_set.capture_set_sha256 != expected_sha
        or capture_set.capture_set_manifest_byte_count != len(manifest_bytes)
        or capture_set.capture_set_manifest_json != manifest_bytes.decode("ascii")
    ):
        _fail("canonical_ohlcv_multitimeframe_capture_set_digest_invalid")
    _validate_address(
        capture_set.capture_set_manifest_address,
        expected_sha256=expected_sha,
        expected_byte_count=len(manifest_bytes),
        reason="canonical_ohlcv_multitimeframe_capture_set_address_invalid",
    )
    if type(capture_set._capture_set_store) is not ImmutableSourcePayloadStore:
        _fail("canonical_ohlcv_multitimeframe_capture_set_store_invalid")
    try:
        readback = capture_set._capture_set_store.get(
            expected_sha,
            expected_byte_count=len(manifest_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
            "canonical_ohlcv_multitimeframe_capture_set_cas_readback_failed"
        ) from exc
    if not hmac.compare_digest(readback, manifest_bytes):
        _fail("canonical_ohlcv_multitimeframe_capture_set_cas_readback_mismatch")


def _build_row(
    *,
    capture_set_row_ordinal: int,
    atomic: SelectedClosedCandleReceiptCapture,
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> CanonicalOhlcvCaptureSetRowV1:
    source = capture.validated_window.rows[atomic.source_index]
    values: dict[str, Any] = {
        "capture_set_row_ordinal": capture_set_row_ordinal,
        "atomic_selected_ordinal": atomic.selected_ordinal,
        "atomic_source_index": atomic.source_index,
        "symbol": source.symbol,
        "timeframe": source.timeframe,
        "candle_id": atomic.candle_id,
        "candle_open_time_ms": atomic.candle_open_time_ms,
        "candle_close_time_ms": atomic.candle_close_time_ms,
        "event_time": _ms_to_clock(atomic.candle_close_time_ms),
        "producer_event_time": _ms_to_clock(atomic.producer_event_time_ms),
        "ingested_at": _ms_to_clock(atomic.ingested_at_ms),
        "available_at": _ms_to_clock(atomic.available_at_ms),
        "feature_cutoff": _ms_to_clock(atomic.candle_close_time_ms),
        "source_transport": atomic.source,
        "source_sequence_id": atomic.source_sequence_id,
        "raw_payload_hash": atomic.raw_payload_hash,
        "is_backfilled": atomic.is_backfilled,
        "open_price": source.open,
        "high": source.high,
        "low": source.low,
        "close": source.close,
        "volume": source.volume,
        "quote_volume": source.quote_volume,
        "num_trades": source.num_trades,
        "taker_buy_base_vol": source.taker_buy_base_vol,
        "taker_buy_quote_vol": source.taker_buy_quote_vol,
        "exact_payload_sha256": atomic.exact_payload_sha256,
        "exact_payload_byte_count": atomic.exact_payload_byte_count,
        "source_payload_address": atomic.source_payload_address,
        "source_read_receipt_sha256": atomic.source_read_receipt.receipt_sha256,
    }
    row_identity_sha256 = _sha256(_row_identity_material_values(**values))
    return CanonicalOhlcvCaptureSetRowV1(
        capture_set_row_ordinal=capture_set_row_ordinal,
        atomic_selected_ordinal=atomic.selected_ordinal,
        atomic_source_index=atomic.source_index,
        symbol=source.symbol,
        timeframe=source.timeframe,
        candle_id=atomic.candle_id,
        candle_open_time_ms=atomic.candle_open_time_ms,
        candle_close_time_ms=atomic.candle_close_time_ms,
        event_time=values["event_time"],
        producer_event_time=values["producer_event_time"],
        ingested_at=values["ingested_at"],
        available_at=values["available_at"],
        feature_cutoff=values["feature_cutoff"],
        source_transport=atomic.source,
        source_sequence_id=atomic.source_sequence_id,
        raw_payload_hash=atomic.raw_payload_hash,
        is_backfilled=atomic.is_backfilled,
        open=source.open,
        high=source.high,
        low=source.low,
        close=source.close,
        volume=source.volume,
        quote_volume=source.quote_volume,
        num_trades=source.num_trades,
        taker_buy_base_vol=source.taker_buy_base_vol,
        taker_buy_quote_vol=source.taker_buy_quote_vol,
        exact_payload_sha256=atomic.exact_payload_sha256,
        exact_payload_byte_count=atomic.exact_payload_byte_count,
        source_payload_address=atomic.source_payload_address,
        source_read_receipt=atomic.source_read_receipt,
        row_identity_sha256=row_identity_sha256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _build_timeframe_capture(
    capture: CanonicalOhlcvAtomicReceiptCapture,
    *,
    timeframe: str,
    required_rows: int,
) -> CanonicalOhlcvTimeframeCaptureV1:
    try:
        atomic_rows = capture.selected_candles
    except CanonicalOhlcvAtomicCaptureError as exc:
        raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
            "canonical_ohlcv_multitimeframe_atomic_capture_revalidation_failed"
        ) from exc
    if len(atomic_rows) < required_rows:
        _fail("canonical_ohlcv_multitimeframe_exact_lookback_required")
    selected = atomic_rows[-required_rows:]
    rows = tuple(
        _build_row(
            capture_set_row_ordinal=ordinal,
            atomic=atomic,
            capture=capture,
        )
        for ordinal, atomic in enumerate(selected)
    )
    latest = rows[-1]
    event_time = latest.event_time
    ingested_at = max(
        rows,
        key=lambda row: _parse_clock(row.ingested_at, reason="x"),
    ).ingested_at
    available_at = max(
        rows,
        key=lambda row: _parse_clock(row.available_at, reason="x"),
    ).available_at
    row_hashes = tuple(row.row_identity_sha256 for row in rows)
    receipt_hashes = tuple(row.source_read_receipt.receipt_sha256 for row in rows)
    values = {
        "timeframe": timeframe,
        "duration_ms": TIMEFRAME_DURATION_MS[timeframe],
        "required_lookback_rows": required_rows,
        "symbol": capture.validated_window.symbol,
        "source_key": capture.source_key,
        "source_key_version": capture.source_key_version,
        "atomic_batch_id": capture.atomic_batch_id,
        "atomic_suffix_digest_sha256": capture.suffix_digest_sha256,
        "atomic_suffix_manifest_address": capture.suffix_manifest_address,
        "atomic_consumer_observed_at": capture.consumer_observed_at,
        "atomic_selected_start_ordinal": len(atomic_rows) - required_rows,
        "rows": rows,
        "event_time": event_time,
        "ingested_at": ingested_at,
        "available_at": available_at,
        "feature_cutoff": event_time,
        "latest_candle_id": latest.candle_id,
        "ordered_row_identity_sha256s": row_hashes,
        "ordered_source_receipt_sha256s": receipt_hashes,
        "typed_negative": False,
    }
    digest = _sha256(_timeframe_material_values(**values))
    return CanonicalOhlcvTimeframeCaptureV1(
        **values,
        atomic_capture_schema_version=CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        atomic_suffix_manifest_schema_version=CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
        timeframe_capture_sha256=digest,
        _atomic_capture=capture,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def build_canonical_ohlcv_multitimeframe_capture_set_v1(
    *,
    profile: object,
    atomic_captures: object,
    capture_set_store: object,
    generated_at: object,
    decision_time: object,
    execution_time: object = None,
    typed_negative_timeframes: object = (),
) -> CanonicalOhlcvMultitimeframeCaptureSetV1:
    """Build and CAS-publish the exact causal 5m/1h capture-set manifest."""

    if type(profile) is not AdaptiveOhlcvFeatureSelectionProfileV1:
        _fail("canonical_ohlcv_multitimeframe_profile_type_invalid")
    adaptive_ohlcv_feature_selection_profile_v1_contract(profile)
    if profile != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1:
        _fail("canonical_ohlcv_multitimeframe_profile_binding_invalid")
    if type(atomic_captures) is not tuple or len(atomic_captures) != 2:
        _fail("canonical_ohlcv_multitimeframe_atomic_capture_inventory_invalid")
    if any(type(item) is not CanonicalOhlcvAtomicReceiptCapture for item in atomic_captures):
        _fail("canonical_ohlcv_multitimeframe_atomic_capture_type_invalid")
    if type(capture_set_store) is not ImmutableSourcePayloadStore:
        _fail("canonical_ohlcv_multitimeframe_capture_set_store_invalid")
    if type(typed_negative_timeframes) is not tuple:
        _fail("canonical_ohlcv_multitimeframe_typed_negative_type_invalid")
    if typed_negative_timeframes:
        _fail("canonical_ohlcv_multitimeframe_required_typed_negative_forbidden")
    if execution_time is not None:
        _fail("canonical_ohlcv_multitimeframe_execution_time_must_be_none")
    generated = _parse_clock(
        generated_at,
        reason="canonical_ohlcv_multitimeframe_generated_at_invalid",
    )
    decision = _parse_clock(
        decision_time,
        reason="canonical_ohlcv_multitimeframe_decision_time_invalid",
    )
    if generated > decision:
        _fail("canonical_ohlcv_multitimeframe_generated_after_decision")
    captures = cast(tuple[CanonicalOhlcvAtomicReceiptCapture, ...], atomic_captures)
    if (
        tuple(capture.validated_window.timeframe for capture in captures)
        != CAPTURE_SET_REQUIRED_TIMEFRAMES
    ):
        _fail("canonical_ohlcv_multitimeframe_atomic_capture_order_invalid")
    if len({capture.validated_window.symbol for capture in captures}) != 1:
        _fail("canonical_ohlcv_multitimeframe_symbol_binding_invalid")
    lookbacks = dict(CAPTURE_SET_REQUIRED_LOOKBACKS)
    timeframe_captures = tuple(
        _build_timeframe_capture(
            capture,
            timeframe=timeframe,
            required_rows=lookbacks[timeframe],
        )
        for capture, timeframe in zip(captures, CAPTURE_SET_REQUIRED_TIMEFRAMES, strict=True)
    )
    for capture in timeframe_captures:
        _validate_decision_relative_timeframe(
            capture,
            generated=generated,
            decision=decision,
        )
    five_minute, one_hour = timeframe_captures
    if _parse_clock(one_hour.feature_cutoff, reason="x") > _parse_clock(
        five_minute.feature_cutoff,
        reason="x",
    ):
        _fail("canonical_ohlcv_multitimeframe_cross_timeframe_order_invalid")
    all_rows = tuple(row for capture in timeframe_captures for row in capture.rows)
    event_time_value = max(
        timeframe_captures,
        key=lambda capture: _parse_clock(capture.event_time, reason="x"),
    ).event_time
    ingested_value = max(
        all_rows,
        key=lambda row: _parse_clock(row.ingested_at, reason="x"),
    ).ingested_at
    available_value = max(
        all_rows,
        key=lambda row: _parse_clock(row.available_at, reason="x"),
    ).available_at
    feature_cutoff_value = max(
        timeframe_captures,
        key=lambda capture: _parse_clock(capture.feature_cutoff, reason="x"),
    ).feature_cutoff
    if _parse_clock(available_value, reason="x") > generated:
        _fail("canonical_ohlcv_multitimeframe_available_after_generated")
    material = _capture_set_material_values(
        symbol=timeframe_captures[0].symbol,
        timeframe_captures=timeframe_captures,
        event_time=event_time_value,
        ingested_at=ingested_value,
        available_at=available_value,
        generated_at=cast(str, generated_at),
        feature_cutoff=feature_cutoff_value,
        decision_time=cast(str, decision_time),
    )
    manifest_bytes = _canonical_json_bytes(material)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        address = capture_set_store.put(
            manifest_bytes,
            expected_sha256=digest,
            expected_byte_count=len(manifest_bytes),
        )
        readback = capture_set_store.get(
            digest,
            expected_byte_count=len(manifest_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
            "canonical_ohlcv_multitimeframe_capture_set_cas_publish_failed"
        ) from exc
    if not hmac.compare_digest(readback, manifest_bytes):
        _fail("canonical_ohlcv_multitimeframe_capture_set_cas_readback_mismatch")
    return CanonicalOhlcvMultitimeframeCaptureSetV1(
        schema_version=CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION,
        manifest_schema_version=(
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION
        ),
        policy_id=CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
        policy_sha256=CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256,
        evidence_classification=(
            CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_EVIDENCE_CLASSIFICATION
        ),
        downstream_status=CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_DOWNSTREAM_STATUS,
        profile_id=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        profile_sha256=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        symbol=timeframe_captures[0].symbol,
        required_timeframes=CAPTURE_SET_REQUIRED_TIMEFRAMES,
        required_lookbacks=CAPTURE_SET_REQUIRED_LOOKBACKS,
        timeframe_captures=timeframe_captures,
        event_time=event_time_value,
        ingested_at=ingested_value,
        available_at=available_value,
        generated_at=cast(str, generated_at),
        feature_cutoff=feature_cutoff_value,
        decision_time=cast(str, decision_time),
        execution_time=None,
        typed_negative_timeframes=(),
        typed_negative_policy_id=TYPED_NEGATIVE_POLICY_ID,
        atomic_capture_factory_verified=True,
        row_receipts_verified=True,
        row_cas_readback_verified=True,
        hermetic_policy_dependency_bound=True,
        audit_only=True,
        market_performance_thresholds_applied=False,
        hermetic_replay_executed=False,
        upstream_transport_authenticity_claimed=False,
        multi_timeframe_atomic_read_claimed=False,
        feature_snapshot_published=False,
        consumer_eligible=False,
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        capture_set_sha256=digest,
        capture_set_manifest_byte_count=len(manifest_bytes),
        capture_set_manifest_address=address,
        capture_set_manifest_json=manifest_bytes.decode("ascii"),
        _capture_set_store=capture_set_store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def canonical_ohlcv_multitimeframe_capture_set_v1_contract(
    capture_set: CanonicalOhlcvMultitimeframeCaptureSetV1,
) -> dict[str, Any]:
    """Return a detached, freshly CAS-revalidated capture-set contract."""

    if type(capture_set) is not CanonicalOhlcvMultitimeframeCaptureSetV1:
        _fail("canonical_ohlcv_multitimeframe_capture_set_type_invalid")
    _validate_capture_set(capture_set)
    contract = _capture_set_material(capture_set)
    contract["content_address"] = _address_material(capture_set.capture_set_manifest_address)
    contract["capture_set_sha256"] = capture_set.capture_set_sha256
    contract["capture_set_manifest_byte_count"] = capture_set.capture_set_manifest_byte_count
    return cast(dict[str, Any], json.loads(_canonical_json_bytes(contract)))


_computed_policy_sha256 = _sha256(_POLICY_MATERIAL)
if _computed_policy_sha256 != CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256:
    _fail("canonical_ohlcv_multitimeframe_policy_sha256_drift")


__all__ = [
    "CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_EVIDENCE_CLASSIFICATION",
    "CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_MANIFEST_SCHEMA_VERSION",
    "CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID",
    "CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256",
    "CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_SCHEMA_VERSION",
    "CAPTURE_SET_CLOCK_FIELDS",
    "CAPTURE_SET_REQUIRED_LOOKBACKS",
    "CAPTURE_SET_REQUIRED_TIMEFRAMES",
    "CanonicalOhlcvCaptureSetRowV1",
    "CanonicalOhlcvMultitimeframeCaptureSetV1",
    "CanonicalOhlcvMultitimeframeCaptureSetV1Error",
    "CanonicalOhlcvTimeframeCaptureV1",
    "build_canonical_ohlcv_multitimeframe_capture_set_v1",
    "canonical_ohlcv_multitimeframe_capture_set_v1_contract",
    "canonical_ohlcv_multitimeframe_capture_set_v1_policy_contract",
]
