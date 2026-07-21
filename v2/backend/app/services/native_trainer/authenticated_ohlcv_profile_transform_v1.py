"""Pure exact transform for the authenticated 5m/1h OHLCV profile v1.

This module is deliberately an unwired calculation boundary.  It accepts the
detached, already-authenticated canonical multi-timeframe capture-set mapping,
independently verifies its immutable digests and direct row receipts, and emits
the 35 enabled ``OHLCV_BOOTSTRAP_5M_1H_V1`` scalars.  It does not publish a
feature snapshot, admit a training sample, or grant prediction, paper, live, or
execution authority.

The input adapter is mapping-based on purpose: the capture producer may remain
factory-only while this transform stays independent of its Python object type.
All accepted input is copied into strict JSON before validation, so later caller
mutation cannot change the values used by the transform.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

import numpy as np

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    DEPLOYED_TALIB_ENVIRONMENT_SHA256,
    EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    TRUE_1H_TA_MINIMUM_ROWS,
    ModelTATechnicalDependencyContractError,
    inspect_deployed_talib_environment,
    validate_deployed_talib_environment,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SourceReadReceiptV4Error,
    validate_source_read_receipt_v4,
)

AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION: Final = (
    "authenticated_ohlcv_profile_transform_v1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_SCHEMA_VERSION: Final = (
    "canonical_ohlcv_multitimeframe_capture_set_v1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_MANIFEST_SCHEMA_VERSION: Final = (
    "canonical_ohlcv_multitimeframe_capture_set_manifest_v1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_ID: Final = (
    "OHLCV_BOOTSTRAP_5M_1H_CAPTURE_SET_POLICY_V1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_SHA256: Final = (
    "f8115e5c6c67909c5486c3d65d4489e60e2ecb5d3545f6d41f0d7ff1d4fd091b"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID: Final = (
    "OHLCV_BOOTSTRAP_5M_1H_EXACT_TRANSFORM_V1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CLASSIFICATION: Final = (
    "PURE_EXACT_RECEIPT_MATERIAL_ONLY_UNWIRED_NO_DOWNSTREAM_AUTHORITY"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_COMPOSITE_SCHEMA_VERSION: Final = (
    "authenticated_ohlcv_composite_derivation_material_v1"
)
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_AUXILIARY_SCHEMA_VERSION: Final = (
    "authenticated_ohlcv_auxiliary_label_evidence_requirements_v1"
)

_CAPTURE_EVIDENCE_CLASSIFICATION = "AUTHENTICATED_ATOMIC_CAPTURE_ROW_RECEIPT_AND_CAS_INTEGRITY_ONLY"
_CAPTURE_DOWNSTREAM_STATUS = (
    "NON_CONSUMABLE_HERMETIC_REPLAY_UNEXECUTED_NO_TRAINER_PREDICTION_OR_EXECUTION_AUTHORITY"
)
_SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION = "source_payload_content_address_v1"
_ATOMIC_CAPTURE_SCHEMA_VERSION = "canonical_ohlcv_atomic_capture_v1"
_ATOMIC_SUFFIX_MANIFEST_SCHEMA_VERSION = "canonical_ohlcv_suffix_manifest_v1"
_CANONICAL_ROW_PAYLOAD_TYPE = "EXACT_CANONICAL_CLOSED_OHLCV_ROW_BYTES"
_FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION = "feature_source_derivation_v1"
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@{}+-]{0,511}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_MAX_CONTRACT_BYTES = 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_CONTAINER_ITEMS = 4096
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()

_TIMEFRAME_DURATION_MS: Final = {"5m": 300_000, "1h": 3_600_000}
_TIMEFRAME_REQUIRED_ROWS: Final = {
    "5m": EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    "1h": TRUE_1H_TA_MINIMUM_ROWS,
}
_EXPECTED_TIMEFRAMES: Final = ("5m", "1h")
_TIMESTAMP_FIELDS: Final = (
    "event_time",
    "ingested_at",
    "available_at",
    "generated_at",
    "feature_cutoff",
    "decision_time",
    "execution_time",
)

_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "manifest_schema_version",
        "policy_id",
        "policy_sha256",
        "evidence_classification",
        "downstream_status",
        "profile_id",
        "profile_sha256",
        "symbol",
        "required_timeframes",
        "required_lookbacks",
        "timeframes",
        "timestamps",
        "timestamp_semantics",
        "typed_negatives",
        "proof_scope",
        "market_performance_thresholds",
        "market_performance_thresholds_applied",
        "authorization",
        "content_address",
        "capture_set_sha256",
        "capture_set_manifest_byte_count",
    }
)
_TIMEFRAME_FIELDS = frozenset(
    {
        "timeframe",
        "duration_ms",
        "required_lookback_rows",
        "symbol",
        "source_key",
        "source_key_version",
        "atomic_batch_id",
        "atomic_capture_schema_version",
        "atomic_suffix_manifest_schema_version",
        "atomic_suffix_digest_sha256",
        "atomic_suffix_manifest_address",
        "atomic_consumer_observed_at",
        "atomic_selected_start_ordinal",
        "rows",
        "event_time",
        "ingested_at",
        "available_at",
        "feature_cutoff",
        "latest_candle_id",
        "ordered_row_identity_sha256s",
        "ordered_source_receipt_sha256s",
        "typed_negative",
        "timeframe_capture_sha256",
    }
)
_ROW_FIELDS = frozenset(
    {
        "capture_set_row_ordinal",
        "atomic_selected_ordinal",
        "atomic_source_index",
        "symbol",
        "timeframe",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "feature_cutoff",
        "source_transport",
        "source_sequence_id",
        "raw_payload_hash",
        "is_backfilled",
        "ohlcv",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "source_payload_address",
        "source_read_receipt_sha256",
        "source_read_receipt_v4",
        "row_identity_sha256",
    }
)
_OHLCV_FIELDS = frozenset(
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
_ADDRESS_FIELDS = frozenset(
    {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
)
_TIMESTAMP_SEMANTICS = {
    "event_time": "LATEST_RETAINED_ECONOMIC_CANDLE_CLOSE",
    "ingested_at": "MAX_RETAINED_SOURCE_INGESTED_AT",
    "available_at": "MAX_RETAINED_SOURCE_AVAILABLE_AT",
    "generated_at": "CAPTURE_SET_CANONICAL_MANIFEST_GENERATED_AT",
    "feature_cutoff": "MAX_RETAINED_TIMEFRAME_FINAL_CANDLE_CLOSE",
    "decision_time": "PROSPECTIVE_SAMPLE_DECISION_TIME",
    "execution_time": "NONE_NO_EXECUTION_OCCURRED_OR_AUTHORIZED",
}
_TYPED_NEGATIVE_FIELDS = frozenset(
    {"policy_id", "timeframes", "count", "required_timeframe_typed_negatives_allowed"}
)
_PROOF_FIELDS = frozenset(
    {
        "atomic_capture_factory_verified",
        "row_receipts_verified",
        "row_cas_readback_verified",
        "hermetic_policy_dependency_bound",
        "hermetic_replay_executed",
        "upstream_transport_authenticity_claimed",
        "multi_timeframe_atomic_read_claimed",
    }
)
_AUTHORIZATION_FIELDS = frozenset(
    {
        "audit_only",
        "feature_snapshot_published",
        "consumer_eligible",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_wired",
    }
)


class AuthenticatedOhlcvProfileTransformV1Error(ValueError):
    """The authenticated input or exact transform failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedOhlcvProfileTransformV1Error(*reasons) from None


def _strict_json_snapshot(value: object, *, depth: int = 0) -> Any:
    if depth > _MAX_JSON_DEPTH:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_JSON_DEPTH_EXCEEDED")
    if isinstance(value, Mapping):
        try:
            items = tuple(value.items())
        except (RuntimeError, TypeError, ValueError):
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_MAPPING_SNAPSHOT_FAILED")
        if len(items) > _MAX_JSON_CONTAINER_ITEMS:
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_MAPPING_SIZE_EXCEEDED")
        result: dict[str, Any] = {}
        for key, item in items:
            if type(key) is not str or key in result:
                _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_MAPPING_KEY_INVALID")
            result[key] = _strict_json_snapshot(item, depth=depth + 1)
        return result
    if type(value) in {list, tuple}:
        sequence = cast(Sequence[object], value)
        if len(sequence) > _MAX_JSON_CONTAINER_ITEMS:
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_SEQUENCE_SIZE_EXCEEDED")
        return [_strict_json_snapshot(item, depth=depth + 1) for item in sequence]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_NONFINITE_INPUT")
        return value
    _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_NON_STRICT_JSON_INPUT")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CANONICAL_ENCODING_FAILED")
    if not encoded or len(encoded) > _MAX_CONTRACT_BYTES:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CANONICAL_SIZE_INVALID")
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _exact_fields(value: object, expected: frozenset[str], *, reason: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        _fail(reason)
    return cast(dict[str, Any], value)


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
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_SOURCE_CLOCK_INVALID")
    try:
        parsed = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_SOURCE_CLOCK_INVALID")
    return parsed.strftime(_CLOCK_FORMAT)


def _clock_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + delta.microseconds // 1_000


def _finite_number(
    value: object,
    *,
    reason: str,
    positive: bool = False,
) -> float:
    if type(value) not in {int, float}:
        _fail(reason)
    try:
        number = float(cast(int | float, value))
    except OverflowError:
        _fail(reason)
    if not math.isfinite(number) or (positive and number <= 0.0) or (not positive and number < 0.0):
        _fail(reason)
    return number


def _validated_address(
    value: object,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    reason: str,
) -> dict[str, Any]:
    address = _exact_fields(value, _ADDRESS_FIELDS, reason=reason)
    if (
        address["schema_version"] != _SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address["payload_sha256"] != expected_sha256
        or address["payload_byte_count"] != expected_byte_count
        or not _valid_label(address["relative_path"])
    ):
        _fail(reason)
    return address


@dataclass(frozen=True, slots=True)
class ValidatedAuthenticatedOhlcvRowV1:
    """Frozen numeric projection and exact receipt root for one causal row."""

    ordinal: int
    candle_open_time_ms: int
    candle_close_time_ms: int
    event_time: str
    ingested_at: str
    available_at: str
    feature_cutoff: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    num_trades: int
    taker_buy_base_vol: float
    taker_buy_quote_vol: float
    source_read_receipt_sha256: str
    row_identity_sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedAuthenticatedOhlcvCaptureSetV1:
    """Immutable exact transform projection of the authenticated capture set."""

    capture_set_sha256: str
    profile_sha256: str
    symbol: str
    timestamps: tuple[tuple[str, str | None], ...]
    five_minute_rows: tuple[ValidatedAuthenticatedOhlcvRowV1, ...]
    one_hour_rows: tuple[ValidatedAuthenticatedOhlcvRowV1, ...]
    timeframe_capture_sha256s: tuple[tuple[str, str], ...]

    @property
    def timestamp_mapping(self) -> dict[str, str | None]:
        return dict(self.timestamps)


@dataclass(frozen=True, slots=True)
class AuthenticatedOhlcvProfileTransformV1Result:
    """Factory-created deterministic transform artifact."""

    schema_version: str
    profile_id: str
    profile_sha256: str
    capture_set_sha256: str
    symbol: str
    ordered_feature_names: tuple[str, ...]
    ordered_feature_values: tuple[float, ...]
    ordered_receipt_material_sha256s: tuple[str, ...]
    artifact_sha256: str
    artifact_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_FACTORY_CONSTRUCTION_REQUIRED")

    @property
    def contract(self) -> dict[str, Any]:
        """Return a detached strict-JSON copy of the verified artifact."""

        try:
            parsed = json.loads(self.artifact_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ARTIFACT_JSON_INVALID")
        if type(parsed) is not dict or _sha256(parsed) != self.artifact_sha256:
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ARTIFACT_BINDING_INVALID")
        return cast(dict[str, Any], parsed)


def _validate_static_capture_contract(capture: dict[str, Any]) -> None:
    expected_scalars = {
        "schema_version": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_SCHEMA_VERSION,
        "manifest_schema_version": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_MANIFEST_SCHEMA_VERSION
        ),
        "policy_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_ID,
        "policy_sha256": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_SHA256,
        "evidence_classification": _CAPTURE_EVIDENCE_CLASSIFICATION,
        "downstream_status": _CAPTURE_DOWNSTREAM_STATUS,
        "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    }
    if any(capture.get(key) != expected for key, expected in expected_scalars.items()):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_STATIC_CAPTURE_BINDING_INVALID")
    if type(capture.get("symbol")) is not str or _SYMBOL_RE.fullmatch(capture["symbol"]) is None:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_SYMBOL_INVALID")
    if capture.get("required_timeframes") != list(_EXPECTED_TIMEFRAMES):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_INVENTORY_INVALID")
    expected_lookbacks = [
        {"timeframe": timeframe, "row_count": _TIMEFRAME_REQUIRED_ROWS[timeframe]}
        for timeframe in _EXPECTED_TIMEFRAMES
    ]
    if capture.get("required_lookbacks") != expected_lookbacks:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_LOOKBACK_INVENTORY_INVALID")

    semantics = _exact_fields(
        capture.get("timestamp_semantics"),
        frozenset(_TIMESTAMP_FIELDS),
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMESTAMP_SEMANTICS_INVALID",
    )
    if semantics != _TIMESTAMP_SEMANTICS:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMESTAMP_SEMANTICS_INVALID")
    typed = _exact_fields(
        capture.get("typed_negatives"),
        _TYPED_NEGATIVE_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TYPED_NEGATIVES_INVALID",
    )
    if (
        typed["policy_id"] != "PROFILE_TYPED_NEGATIVE_DISPOSITION_POLICY_V1"
        or typed["timeframes"] != []
        or typed["count"] != 0
        or typed["required_timeframe_typed_negatives_allowed"] is not False
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TYPED_NEGATIVES_INVALID")
    proof = _exact_fields(
        capture.get("proof_scope"),
        _PROOF_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_PROOF_SCOPE_INVALID",
    )
    required_true = (
        "atomic_capture_factory_verified",
        "row_receipts_verified",
        "row_cas_readback_verified",
        "hermetic_policy_dependency_bound",
    )
    required_false = (
        "hermetic_replay_executed",
        "upstream_transport_authenticity_claimed",
        "multi_timeframe_atomic_read_claimed",
    )
    if any(proof[name] is not True for name in required_true) or any(
        proof[name] is not False for name in required_false
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_PROOF_SCOPE_INVALID")
    authorization = _exact_fields(
        capture.get("authorization"),
        _AUTHORIZATION_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_AUTHORIZATION_INVALID",
    )
    if authorization["audit_only"] is not True or any(
        authorization[name] is not False for name in _AUTHORIZATION_FIELDS - {"audit_only"}
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_AUTHORIZATION_INVALID")
    if (
        capture.get("market_performance_thresholds") != []
        or capture.get("market_performance_thresholds_applied") is not False
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_MARKET_THRESHOLD_CLAIM_INVALID")


def _validate_capture_root(
    capture: dict[str, Any],
    *,
    expected_capture_set_sha256: object,
    expected_profile_sha256: object,
) -> None:
    supplied = capture.get("capture_set_sha256")
    if not _valid_sha256(expected_capture_set_sha256) or not _valid_sha256(supplied):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_CAPTURE_SHA256_INVALID")
    if not _valid_sha256(expected_profile_sha256):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_PROFILE_SHA256_INVALID")
    if expected_profile_sha256 != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_PROFILE_SHA256_MISMATCH")
    if capture.get("profile_sha256") != expected_profile_sha256:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_PROFILE_SHA256_MISMATCH")
    if supplied != expected_capture_set_sha256:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_CAPTURE_SHA256_MISMATCH")
    material = {
        key: value
        for key, value in capture.items()
        if key not in {"content_address", "capture_set_sha256", "capture_set_manifest_byte_count"}
    }
    material_bytes = _canonical_json_bytes(material)
    if supplied != hashlib.sha256(material_bytes).hexdigest():
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_SHA256_MISMATCH")
    byte_count = capture.get("capture_set_manifest_byte_count")
    if type(byte_count) is not int or byte_count != len(material_bytes):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_BYTE_COUNT_MISMATCH")
    _validated_address(
        capture.get("content_address"),
        expected_sha256=cast(str, supplied),
        expected_byte_count=byte_count,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_ADDRESS_INVALID",
    )


def _validate_row(
    raw: object,
    *,
    symbol: str,
    timeframe: str,
    expected_ordinal: int,
    decision: datetime,
    atomic_consumer_observed_at: str,
) -> ValidatedAuthenticatedOhlcvRowV1:
    row = _exact_fields(
        raw,
        _ROW_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_FIELD_SET_INVALID",
    )
    if (
        row["capture_set_row_ordinal"] != expected_ordinal
        or type(row["atomic_selected_ordinal"]) is not int
        or type(row["atomic_source_index"]) is not int
        or row["atomic_selected_ordinal"] < 0
        or row["atomic_source_index"] < 0
        or row["symbol"] != symbol
        or row["timeframe"] != timeframe
        or not _valid_label(row["candle_id"])
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_IDENTITY_INVALID")
    duration_ms = _TIMEFRAME_DURATION_MS[timeframe]
    open_ms = row["candle_open_time_ms"]
    close_ms = row["candle_close_time_ms"]
    if (
        type(open_ms) is not int
        or type(close_ms) is not int
        or open_ms < 0
        or open_ms % duration_ms != 0
        or close_ms != open_ms + duration_ms - 1
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_INTERVAL_INVALID")
    clocks = {
        name: _parse_clock(
            row[name],
            reason=f"AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_{name.upper()}_INVALID",
        )
        for name in (
            "event_time",
            "producer_event_time",
            "ingested_at",
            "available_at",
            "feature_cutoff",
        )
    }
    close_clock = _parse_clock(
        _ms_to_clock(close_ms),
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_CLOSE_CLOCK_INVALID",
    )
    if clocks["event_time"] != close_clock or clocks["feature_cutoff"] != close_clock:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_ECONOMIC_CLOCK_MISMATCH")
    if not (
        clocks["event_time"]
        <= clocks["producer_event_time"]
        <= clocks["ingested_at"]
        <= clocks["available_at"]
        <= decision
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_CAUSAL_ORDER_INVALID")
    if close_clock >= decision:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_UNFINISHED_OR_FUTURE_CANDLE")
    source_transport = row["source_transport"]
    if (
        source_transport == "binance_wss"
        and row["is_backfilled"] is not False
        or source_transport == "binance_rest"
        and row["is_backfilled"] is not True
        or source_transport not in {"binance_wss", "binance_rest"}
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_TRANSPORT_INVALID")
    if not _valid_sha256(row["raw_payload_hash"]) or not _valid_sha256(row["exact_payload_sha256"]):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_PAYLOAD_SHA256_INVALID")
    byte_count = row["exact_payload_byte_count"]
    if type(byte_count) is not int or byte_count <= 0:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_PAYLOAD_BYTE_COUNT_INVALID")
    _validated_address(
        row["source_payload_address"],
        expected_sha256=row["exact_payload_sha256"],
        expected_byte_count=byte_count,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_ADDRESS_INVALID",
    )
    ohlcv = _exact_fields(
        row["ohlcv"],
        _OHLCV_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_FIELD_SET_INVALID",
    )
    open_price = _finite_number(
        ohlcv["open"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID", positive=True
    )
    high = _finite_number(
        ohlcv["high"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID", positive=True
    )
    low = _finite_number(
        ohlcv["low"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID", positive=True
    )
    close = _finite_number(
        ohlcv["close"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID", positive=True
    )
    volume = _finite_number(
        ohlcv["volume"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID"
    )
    quote_volume = _finite_number(
        ohlcv["quote_volume"], reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID"
    )
    taker_buy_base = _finite_number(
        ohlcv["taker_buy_base_vol"],
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID",
    )
    taker_buy_quote = _finite_number(
        ohlcv["taker_buy_quote_vol"],
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVALID",
    )
    num_trades = ohlcv["num_trades"]
    if (
        type(num_trades) is not int
        or num_trades < 0
        or high < max(open_price, close)
        or low > min(open_price, close)
        or low > high
        or taker_buy_base > volume
        or taker_buy_quote > quote_volume
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_OHLCV_INVARIANT_INVALID")

    try:
        receipt_artifact = validate_source_read_receipt_v4(row["source_read_receipt_v4"])
    except SourceReadReceiptV4Error as exc:
        raise AuthenticatedOhlcvProfileTransformV1Error(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_RECEIPT_INVALID"
        ) from exc
    receipt = receipt_artifact.receipt
    receipt_sha256 = row["source_read_receipt_sha256"]
    expected_receipt_values = {
        "source_label": f"ohlcv_closed:binance:{symbol}:{timeframe}:{row['candle_id']}",
        "payload_type": _CANONICAL_ROW_PAYLOAD_TYPE,
        "payload_sha256": row["exact_payload_sha256"],
        "payload_byte_count": byte_count,
        "economic_event_time": row["event_time"],
        "producer_event_time": row["producer_event_time"],
        "ingested_at": row["ingested_at"],
        "available_at": row["available_at"],
        "consumer_observed_at": atomic_consumer_observed_at,
        "feature_cutoff": row["feature_cutoff"],
        "receipt_sha256": receipt_sha256,
    }
    if not _valid_sha256(receipt_sha256) or any(
        receipt.get(name) != expected for name, expected in expected_receipt_values.items()
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_RECEIPT_BINDING_INVALID")
    identity_material = {
        key: value
        for key, value in row.items()
        if key not in {"source_read_receipt_v4", "row_identity_sha256"}
    }
    if not _valid_sha256(row["row_identity_sha256"]) or row["row_identity_sha256"] != _sha256(
        identity_material
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_IDENTITY_SHA256_MISMATCH")
    return ValidatedAuthenticatedOhlcvRowV1(
        ordinal=expected_ordinal,
        candle_open_time_ms=open_ms,
        candle_close_time_ms=close_ms,
        event_time=row["event_time"],
        ingested_at=row["ingested_at"],
        available_at=row["available_at"],
        feature_cutoff=row["feature_cutoff"],
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        quote_volume=quote_volume,
        num_trades=num_trades,
        taker_buy_base_vol=taker_buy_base,
        taker_buy_quote_vol=taker_buy_quote,
        source_read_receipt_sha256=receipt_sha256,
        row_identity_sha256=row["row_identity_sha256"],
    )


def _validate_timeframe(
    raw: object,
    *,
    symbol: str,
    expected_timeframe: str,
    generated: datetime,
    decision: datetime,
) -> tuple[tuple[ValidatedAuthenticatedOhlcvRowV1, ...], str, dict[str, Any]]:
    timeframe = _exact_fields(
        raw,
        _TIMEFRAME_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_FIELD_SET_INVALID",
    )
    duration_ms = _TIMEFRAME_DURATION_MS[expected_timeframe]
    expected_rows = _TIMEFRAME_REQUIRED_ROWS[expected_timeframe]
    if (
        timeframe["timeframe"] != expected_timeframe
        or timeframe["duration_ms"] != duration_ms
        or timeframe["required_lookback_rows"] != expected_rows
        or timeframe["symbol"] != symbol
        or timeframe["source_key"]
        != f"v2:market:ohlcv_closed:binance:{symbol}:{expected_timeframe}"
        or timeframe["atomic_capture_schema_version"] != _ATOMIC_CAPTURE_SCHEMA_VERSION
        or timeframe["atomic_suffix_manifest_schema_version"]
        != _ATOMIC_SUFFIX_MANIFEST_SCHEMA_VERSION
        or timeframe["typed_negative"] is not False
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_BINDING_INVALID")
    if any(
        not _valid_label(timeframe[name])
        for name in ("source_key_version", "atomic_batch_id", "latest_candle_id")
    ) or not _valid_sha256(timeframe["atomic_suffix_digest_sha256"]):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_ATOMIC_BINDING_INVALID")
    atomic_start = timeframe["atomic_selected_start_ordinal"]
    if type(atomic_start) is not int or atomic_start < 0:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_ATOMIC_START_INVALID")
    manifest_address = _exact_fields(
        timeframe["atomic_suffix_manifest_address"],
        _ADDRESS_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_MANIFEST_ADDRESS_INVALID",
    )
    if (
        manifest_address["schema_version"] != _SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or not _valid_sha256(manifest_address["payload_sha256"])
        or type(manifest_address["payload_byte_count"]) is not int
        or manifest_address["payload_byte_count"] <= 0
        or not _valid_label(manifest_address["relative_path"])
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_MANIFEST_ADDRESS_INVALID")
    observed = _parse_clock(
        timeframe["atomic_consumer_observed_at"],
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_ATOMIC_OBSERVED_AT_INVALID",
    )
    if observed > generated:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_ATOMIC_OBSERVED_AFTER_GENERATED")
    raw_rows = timeframe["rows"]
    if type(raw_rows) is not list or len(raw_rows) != expected_rows:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXACT_LOOKBACK_REQUIRED")
    rows = tuple(
        _validate_row(
            row,
            symbol=symbol,
            timeframe=expected_timeframe,
            expected_ordinal=index,
            decision=decision,
            atomic_consumer_observed_at=timeframe["atomic_consumer_observed_at"],
        )
        for index, row in enumerate(raw_rows)
    )
    if tuple(row.candle_open_time_ms for row in rows[1:]) != tuple(
        row.candle_open_time_ms + duration_ms for row in rows[:-1]
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_NONCONTIGUOUS_HISTORY")
    raw_latest = cast(dict[str, Any], raw_rows[-1])
    if raw_latest["source_transport"] != "binance_wss" or raw_latest["is_backfilled"] is not False:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_LATEST_LIVE_WSS_REQUIRED")
    expected_latest_close = (_clock_to_ms(decision) // duration_ms) * duration_ms - 1
    if rows[-1].candle_close_time_ms != expected_latest_close:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_STALE_OR_UNFINISHED_LATEST_CANDLE")
    row_hashes = [row.row_identity_sha256 for row in rows]
    receipt_hashes = [row.source_read_receipt_sha256 for row in rows]
    if (
        timeframe["ordered_row_identity_sha256s"] != row_hashes
        or timeframe["ordered_source_receipt_sha256s"] != receipt_hashes
        or len(set(receipt_hashes)) != expected_rows
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_LINEAGE_INVALID")
    derived_event = rows[-1].event_time
    derived_ingested = max(rows, key=lambda item: item.ingested_at).ingested_at
    derived_available = max(rows, key=lambda item: item.available_at).available_at
    if (
        timeframe["event_time"] != derived_event
        or timeframe["ingested_at"] != derived_ingested
        or timeframe["available_at"] != derived_available
        or timeframe["feature_cutoff"] != rows[-1].feature_cutoff
        or timeframe["latest_candle_id"] != raw_latest["candle_id"]
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_CLOCK_BINDING_INVALID")
    timeframe_material = {
        key: value for key, value in timeframe.items() if key != "timeframe_capture_sha256"
    }
    timeframe_sha256 = timeframe["timeframe_capture_sha256"]
    if not _valid_sha256(timeframe_sha256) or timeframe_sha256 != _sha256(timeframe_material):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_SHA256_MISMATCH")
    return rows, timeframe_sha256, timeframe


def validate_authenticated_ohlcv_capture_set_v1(
    capture_set_contract: Mapping[str, Any],
    *,
    expected_capture_set_sha256: str,
    expected_profile_sha256: str = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
) -> ValidatedAuthenticatedOhlcvCaptureSetV1:
    """Strictly snapshot and validate the detached authenticated capture mapping."""

    capture = _strict_json_snapshot(capture_set_contract)
    capture = _exact_fields(
        capture,
        _TOP_FIELDS,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TOP_FIELD_SET_INVALID",
    )
    _validate_capture_root(
        capture,
        expected_capture_set_sha256=expected_capture_set_sha256,
        expected_profile_sha256=expected_profile_sha256,
    )
    _validate_static_capture_contract(capture)
    timestamp_values = _exact_fields(
        capture["timestamps"],
        frozenset(_TIMESTAMP_FIELDS),
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMESTAMP_FIELD_SET_INVALID",
    )
    parsed_timestamps = {
        name: _parse_clock(
            timestamp_values[name],
            reason=f"AUTHENTICATED_OHLCV_TRANSFORM_V1_{name.upper()}_INVALID",
        )
        for name in _TIMESTAMP_FIELDS
        if name != "execution_time"
    }
    if timestamp_values["execution_time"] is not None:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_EXECUTION_TIME_MUST_BE_NONE")
    if (
        not (
            parsed_timestamps["event_time"]
            <= parsed_timestamps["ingested_at"]
            <= parsed_timestamps["available_at"]
            <= parsed_timestamps["generated_at"]
            <= parsed_timestamps["decision_time"]
        )
        or not parsed_timestamps["feature_cutoff"] < parsed_timestamps["decision_time"]
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_CLOCK_ORDER_INVALID")

    raw_timeframes = capture["timeframes"]
    if type(raw_timeframes) is list:
        if len(raw_timeframes) != 2:
            _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_INVENTORY_INVALID")
        timeframe_inputs = raw_timeframes
    elif type(raw_timeframes) is dict and set(raw_timeframes) == set(_EXPECTED_TIMEFRAMES):
        timeframe_inputs = [raw_timeframes[name] for name in _EXPECTED_TIMEFRAMES]
    else:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_TIMEFRAME_INVENTORY_INVALID")
    validated_timeframes = tuple(
        _validate_timeframe(
            raw,
            symbol=capture["symbol"],
            expected_timeframe=expected,
            generated=parsed_timestamps["generated_at"],
            decision=parsed_timestamps["decision_time"],
        )
        for raw, expected in zip(timeframe_inputs, _EXPECTED_TIMEFRAMES, strict=True)
    )
    five_rows, five_sha, five_contract = validated_timeframes[0]
    one_rows, one_sha, one_contract = validated_timeframes[1]
    if _parse_clock(
        one_contract["feature_cutoff"],
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_1H_FEATURE_CUTOFF_INVALID",
    ) > _parse_clock(
        five_contract["feature_cutoff"],
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_5M_FEATURE_CUTOFF_INVALID",
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CROSS_TIMEFRAME_ORDER_INVALID")
    all_rows = (*five_rows, *one_rows)
    derived_event = max(five_contract["event_time"], one_contract["event_time"])
    derived_ingested = max(row.ingested_at for row in all_rows)
    derived_available = max(row.available_at for row in all_rows)
    derived_cutoff = max(five_contract["feature_cutoff"], one_contract["feature_cutoff"])
    if (
        timestamp_values["event_time"] != derived_event
        or timestamp_values["ingested_at"] != derived_ingested
        or timestamp_values["available_at"] != derived_available
        or timestamp_values["feature_cutoff"] != derived_cutoff
    ):
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_AGGREGATE_CLOCK_BINDING_INVALID")
    return ValidatedAuthenticatedOhlcvCaptureSetV1(
        capture_set_sha256=capture["capture_set_sha256"],
        profile_sha256=capture["profile_sha256"],
        symbol=capture["symbol"],
        timestamps=tuple((name, timestamp_values[name]) for name in _TIMESTAMP_FIELDS),
        five_minute_rows=five_rows,
        one_hour_rows=one_rows,
        timeframe_capture_sha256s=(("5m", five_sha), ("1h", one_sha)),
    )


_IMPLEMENTATION_MANIFEST = {
    "schema_version": "authenticated_ohlcv_exact_formula_manifest_v1",
    "implementation_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
    "float_input_dtype": "IEEE754_BINARY64",
    "scalar_output_encoding": "IEEE754_BINARY32_BIG_ENDIAN_HEX",
    "native_formulas": {
        "SIMPLE_CLOSE_RETURN_V1": "(close_t-close_t_minus_1)/close_t_minus_1",
        "NATURAL_LOG_CLOSE_RETURN_V1": "ln(close_t/close_t_minus_1)",
        "HIGH_MINUS_LOW_OVER_CLOSE_V1": "(high_t-low_t)/close_t",
        "CLOSE_MINUS_OPEN_OVER_CLOSE_V1": "(close_t-open_t)/close_t",
        "WILDER_ATR_14_OVER_CLOSE_V1": "sma_seed_tr_1_to_14_then_wilder_recursive/close_t",
        "SMA_SEEDED_EMA_12_V1": "sma_seed_then_alpha_2_over_13_recursive",
        "SMA_SEEDED_EMA_26_V1": "sma_seed_then_alpha_2_over_27_recursive",
        "WILDER_RSI_14_V1": "sma_seed_gains_losses_then_wilder_recursive",
        "SMA_SEEDED_MACD_12_26_9_LINE_V1": "aligned_sma_seeded_ema12_minus_ema26",
        "SMA_SEEDED_MACD_12_26_9_SIGNAL_V1": "sma_seeded_ema9_of_aligned_macd_line",
        "SMA_SEEDED_MACD_12_26_9_HISTOGRAM_V1": "macd_line_minus_signal",
        "BOLLINGER_POPULATION_WIDTH_20_2_OVER_MEAN_V1": "4*pstdev(last20)/mean(last20)",
    },
    "talib_calls": {
        "TALIB_RSI_14_REAL_V1": "RSI(close,timeperiod=14)[-1]",
        "TALIB_ADX_14_REAL_V1": "ADX(high,low,close,timeperiod=14)[-1]",
        "TALIB_MACD_12_26_9_MACDHIST_V1": (
            "MACD(close,fastperiod=12,slowperiod=26,signalperiod=9).macdhist[-1]"
        ),
        "TALIB_ATR_14_REAL_V1": "ATR(high,low,close,timeperiod=14)[-1]",
        "TALIB_MFI_14_REAL_V1": "MFI(high,low,close,volume,timeperiod=14)[-1]",
        "TALIB_WILLR_14_REAL_V1": "WILLR(high,low,close,timeperiod=14)[-1]",
        "TALIB_NATR_14_REAL_V1": "NATR(high,low,close,timeperiod=14)[-1]",
        "TALIB_CCI_14_REAL_V1": "CCI(high,low,close,timeperiod=14)[-1]",
    },
    "strict_latest": "EXACT_FINAL_INDEX_ONLY_NO_BACKSCAN_NO_FILL",
    "talib_environment_validation": (
        "PINNED_IDENTITY_INSPECTED_AND_VALIDATED_IMMEDIATELY_BEFORE_AND_AFTER_CALLS"
    ),
    "model_ta_dependency_contract_sha256": MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    "deployed_talib_environment_sha256": DEPLOYED_TALIB_ENVIRONMENT_SHA256,
}
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256: Final = (
    "43559de24732f71ba220abeb356435a37d37aedf5e56430dbe29f17e3e89a634"
)
_CONFIGURATION_CONTRACT = {
    "schema_version": "authenticated_ohlcv_exact_configuration_v1",
    "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    "required_rows": {"5m": EXISTING_CORE_MINIMUM_SOURCE_ROWS, "1h": TRUE_1H_TA_MINIMUM_ROWS},
    "ema_periods": [12, 26],
    "rsi_period": 14,
    "atr_period": 14,
    "macd_periods": [12, 26, 9],
    "bollinger": {"period": 20, "deviations": 2, "standard_deviation": "population"},
    "talib_period": 14,
    "output_dtype": "float32",
    "zero_denominator_policy": "REJECT",
    "nonfinite_policy": "REJECT",
}
AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256: Final = (
    "7c1340de9d9a5b5ff167b988a4083129a367ea8ddf81279d6ecde5dd36e79002"
)
if _sha256(_IMPLEMENTATION_MANIFEST) != (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
) or _sha256(_CONFIGURATION_CONTRACT) != (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
):
    _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_STATIC_HASH_DRIFT")


def _module_code_sha256() -> str:
    try:
        source = Path(__file__).read_bytes()
    except OSError:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CODE_READ_FAILED")
    if not source:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_CODE_READ_FAILED")
    return hashlib.sha256(source).hexdigest()


def _nonzero(value: float, *, reason: str) -> float:
    if not math.isfinite(value) or value == 0.0:
        _fail(reason)
    return value


def _ema(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_INSUFFICIENT_EMA_LOOKBACK")
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)
    return result


def _rsi(values: Sequence[float], period: int = 14) -> float:
    if len(values) < period + 1:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_INSUFFICIENT_RSI_LOOKBACK")
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:], strict=False):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0.0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _wilder_atr(rows: Sequence[ValidatedAuthenticatedOhlcvRowV1], period: int = 14) -> float:
    if len(rows) < period + 1:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_INSUFFICIENT_ATR_LOOKBACK")
    true_ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(rows, rows[1:], strict=False)
    ]
    result = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        result = (result * (period - 1) + true_range) / period
    return result


def _macd(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) < 35:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_INSUFFICIENT_MACD_LOOKBACK")

    def rolling_ema(source: Sequence[float], period: int) -> list[float]:
        alpha = 2.0 / (period + 1.0)
        output = [sum(source[:period]) / period]
        for value in source[period:]:
            output.append(value * alpha + output[-1] * (1.0 - alpha))
        return output

    fast = rolling_ema(values, 12)
    slow = rolling_ema(values, 26)
    aligned = min(len(fast), len(slow))
    line = [fast[-aligned + index] - slow[-aligned + index] for index in range(aligned)]
    signal = rolling_ema(line, 9)[-1]
    return line[-1], signal, line[-1] - signal


def _bb_width(values: Sequence[float]) -> float:
    if len(values) < 20:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_INSUFFICIENT_BB_LOOKBACK")
    window = values[-20:]
    mean = _nonzero(
        sum(window) / 20,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_BB_MEAN_ZERO",
    )
    return 4.0 * statistics.pstdev(window) / mean


def _strict_talib_latest(value: object, *, feature_name: str, row_count: int) -> float:
    array = np.asarray(value)
    if array.ndim != 1 or len(array) != row_count:
        _fail(f"AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_SHAPE_INVALID:{feature_name}")
    latest = float(array[-1])
    if not math.isfinite(latest):
        _fail(f"AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_NONFINITE:{feature_name}")
    return latest


def _validate_active_talib_environment() -> None:
    try:
        identity = inspect_deployed_talib_environment()
        validate_deployed_talib_environment(identity)
    except ModelTATechnicalDependencyContractError as exc:
        raise AuthenticatedOhlcvProfileTransformV1Error(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_ENVIRONMENT_MISMATCH"
        ) from exc


def _compute_values(
    capture: ValidatedAuthenticatedOhlcvCaptureSetV1,
) -> dict[str, float]:
    five = capture.five_minute_rows
    one = capture.one_hour_rows
    latest = five[-1]
    previous = five[-2]
    previous_close = _nonzero(
        previous.close,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_PREVIOUS_CLOSE_ZERO",
    )
    latest_close = _nonzero(
        latest.close,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_LATEST_CLOSE_ZERO",
    )
    latest_volume = _nonzero(
        latest.volume,
        reason="AUTHENTICATED_OHLCV_TRANSFORM_V1_LATEST_VOLUME_ZERO",
    )
    closes = [row.close for row in five]
    macd, macd_signal, macd_hist = _macd(closes)
    values = {
        "quote_volume": latest.quote_volume,
        "volume": latest.volume,
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "num_trades": float(latest.num_trades),
        "taker_buy_base_vol": latest.taker_buy_base_vol,
        "taker_buy_quote_vol": latest.taker_buy_quote_vol,
        "taker_sell_base_vol": latest.volume - latest.taker_buy_base_vol,
        "taker_sell_quote_vol": latest.quote_volume - latest.taker_buy_quote_vol,
        "taker_buy_ratio": latest.taker_buy_base_vol / latest_volume,
        "taker_sell_ratio": 1.0 - latest.taker_buy_base_vol / latest_volume,
        "ohlcv_close": latest.close,
        "ohlcv_volume": latest.volume,
        "ret_pct": (latest.close - previous.close) / previous_close,
        "log_return": math.log(latest.close / previous_close),
        "range_pct": (latest.high - latest.low) / latest_close,
        "body_pct": (latest.close - latest.open) / latest_close,
        "true_range_pct": _wilder_atr(five) / latest_close,
        "ema_12": _ema(closes, 12),
        "ema_26": _ema(closes, 26),
        "rsi_14": _rsi(closes),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_width_pct": _bb_width(closes),
    }
    try:
        import talib  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        raise AuthenticatedOhlcvProfileTransformV1Error(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_IMPORT_FAILED"
        ) from exc
    _validate_active_talib_environment()
    highs = np.asarray([row.high for row in one], dtype="float64")
    lows = np.asarray([row.low for row in one], dtype="float64")
    one_closes = np.asarray([row.close for row in one], dtype="float64")
    volumes = np.asarray([row.volume for row in one], dtype="float64")
    one_count = len(one)
    try:
        talib_outputs = {
            "htf1h_taf_rsi": talib.RSI(one_closes, timeperiod=14),
            "htf1h_taf_adx": talib.ADX(highs, lows, one_closes, timeperiod=14),
            "htf1h_taf_atr": talib.ATR(highs, lows, one_closes, timeperiod=14),
            "htf1h_taf_mfi": talib.MFI(highs, lows, one_closes, volumes, timeperiod=14),
            "htf1h_taf_willr": talib.WILLR(highs, lows, one_closes, timeperiod=14),
            "htf1h_taf_natr": talib.NATR(highs, lows, one_closes, timeperiod=14),
            "htf1h_taf_cci": talib.CCI(highs, lows, one_closes, timeperiod=14),
        }
        _macd_line, _macd_signal, one_hist = talib.MACD(
            one_closes,
            fastperiod=12,
            slowperiod=26,
            signalperiod=9,
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthenticatedOhlcvProfileTransformV1Error(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_EVALUATION_FAILED"
        ) from exc
    _validate_active_talib_environment()
    talib_outputs["htf1h_taf_macd_hist"] = one_hist
    for name, output in talib_outputs.items():
        values[name] = _strict_talib_latest(output, feature_name=name, row_count=one_count)
    return values


def _float32(value: object, *, feature_name: str) -> tuple[float, str]:
    if type(value) not in {int, float} or not math.isfinite(value):
        _fail(f"AUTHENTICATED_OHLCV_TRANSFORM_V1_VALUE_NONFINITE:{feature_name}")
    try:
        packed = struct.pack(">f", float(value))
    except (OverflowError, struct.error):
        _fail(f"AUTHENTICATED_OHLCV_TRANSFORM_V1_FLOAT32_OVERFLOW:{feature_name}")
    canonical = struct.unpack(">f", packed)[0]
    if not math.isfinite(canonical):
        _fail(f"AUTHENTICATED_OHLCV_TRANSFORM_V1_FLOAT32_NONFINITE:{feature_name}")
    if canonical == 0.0:
        canonical = 0.0
        packed = struct.pack(">f", canonical)
    return canonical, packed.hex()


def _profile_transform_specs() -> tuple[dict[str, Any], ...]:
    by_ordinal: dict[int, dict[str, Any]] = {}
    families = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.timeframe_finality_transform_contracts
    for family in families:
        for transform in family.transforms:
            by_ordinal[transform.ordinal] = {
                "ordinal": transform.ordinal,
                "feature_name": transform.feature_name,
                "transform_id": transform.transform_id,
                "input_fields": list(transform.input_fields),
                "minimum_closed_source_rows": transform.minimum_closed_source_rows,
                "source_timeframe": family.physical_timeframe,
            }
    try:
        ordered = tuple(
            by_ordinal[ordinal]
            for ordinal in ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS
        )
    except KeyError:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_PROFILE_TRANSFORM_INVENTORY_INVALID")
    if len(ordered) != 35 or len({item["feature_name"] for item in ordered}) != 35:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_PROFILE_TRANSFORM_INVENTORY_INVALID")
    return ordered


def _auxiliary_label_evidence_contract() -> dict[str, Any]:
    required = [
        {
            "input_name": name,
            "model_feature": False,
            "required_from_later_label_publisher": True,
            "unit_policy": "EXPLICIT_UNIT_AND_SIGN_CONVENTION_REQUIRED",
            "separate_source_receipt_required": True,
        }
        for name in ("fee", "spread", "slippage", "funding")
    ]
    return {
        "schema_version": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_AUXILIARY_SCHEMA_VERSION,
        "channel_id": "SEPARATE_CANONICAL_LABEL_ECONOMICS_EVIDENCE_V1",
        "required_inputs": required,
        "required_input_names": [item["input_name"] for item in required],
        "excluded_from_model_feature_vector": True,
        "included_in_35_enabled_features": False,
        "supplied_by_this_transform": False,
        "later_label_publisher_must_fail_closed_when_missing": True,
        "label_publication_authorized": False,
    }


def transform_authenticated_ohlcv_profile_v1(
    capture_set_contract: Mapping[str, Any],
    *,
    expected_capture_set_sha256: str,
    expected_profile_sha256: str = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
) -> AuthenticatedOhlcvProfileTransformV1Result:
    """Compute the exact 35-feature profile and deterministic receipt material."""

    capture = validate_authenticated_ohlcv_capture_set_v1(
        capture_set_contract,
        expected_capture_set_sha256=expected_capture_set_sha256,
        expected_profile_sha256=expected_profile_sha256,
    )
    try:
        computed = _compute_values(capture)
    except AuthenticatedOhlcvProfileTransformV1Error:
        raise
    except (ArithmeticError, ValueError) as exc:
        raise AuthenticatedOhlcvProfileTransformV1Error(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_NUMERIC_EVALUATION_FAILED"
        ) from exc
    specs = _profile_transform_specs()
    expected_names = {spec["feature_name"] for spec in specs}
    if set(computed) != expected_names:
        _fail("AUTHENTICATED_OHLCV_TRANSFORM_V1_COMPUTED_FEATURE_INVENTORY_INVALID")
    module_code_sha256 = _module_code_sha256()
    timestamps = capture.timestamp_mapping
    row_roots = {
        "5m": tuple(row.source_read_receipt_sha256 for row in capture.five_minute_rows),
        "1h": tuple(row.source_read_receipt_sha256 for row in capture.one_hour_rows),
    }
    ordered_features: list[dict[str, Any]] = []
    ordered_values: list[float] = []
    ordered_receipt_sha256s: list[str] = []
    for spec in specs:
        name = cast(str, spec["feature_name"])
        timeframe = cast(str, spec["source_timeframe"])
        value, value_hex = _float32(computed[name], feature_name=name)
        feature_configuration = {
            "schema_version": "authenticated_ohlcv_feature_configuration_v1",
            "global_configuration_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
            ),
            "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
            "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
            **spec,
            "exact_source_row_count": len(row_roots[timeframe]),
            "output_encoding": "IEEE754_BINARY32_BIG_ENDIAN_HEX",
        }
        configuration_sha256 = _sha256(feature_configuration)
        transform_contract = {
            "schema_version": "authenticated_ohlcv_feature_transform_contract_v1",
            "implementation_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
            ),
            "module_code_sha256": module_code_sha256,
            "configuration_sha256": configuration_sha256,
            "feature_configuration": feature_configuration,
        }
        transform_sha256 = _sha256(transform_contract)
        child_bindings = [
            {
                "input_role": f"closed_{timeframe}_row_{index:03d}",
                "receipt_sha256": receipt_sha256,
            }
            for index, receipt_sha256 in enumerate(row_roots[timeframe])
        ]
        scalar_bytes = bytes.fromhex(value_hex)
        receipt_material = {
            "schema_version": (AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_COMPOSITE_SCHEMA_VERSION),
            "receipt_kind": "COMPOSITE_DERIVATION",
            "feature_ordinal": spec["ordinal"],
            "feature_name": name,
            "source_timeframe": timeframe,
            "payload_type": "IEEE754_BINARY32_SCALAR",
            "payload_sha256": hashlib.sha256(scalar_bytes).hexdigest(),
            "payload_byte_count": len(scalar_bytes),
            "value_float32_be_hex": value_hex,
            "child_read_bindings": child_bindings,
            "derivation_material": {
                "schema_version": _FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
                "producer_id": "authenticated_ohlcv_profile_transform_v1",
                "producer_version": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION,
                "transform_sha256": transform_sha256,
                "configuration_sha256": configuration_sha256,
            },
            "exact_bindings": {
                "capture_set_sha256": capture.capture_set_sha256,
                "timeframe_capture_sha256": dict(capture.timeframe_capture_sha256s)[timeframe],
                "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
                "profile_sha256": capture.profile_sha256,
                "transform_id": spec["transform_id"],
                "implementation_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
                "implementation_sha256": (
                    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
                ),
                "module_code_sha256": module_code_sha256,
                "global_configuration_sha256": (
                    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
                ),
                "feature_configuration_sha256": configuration_sha256,
                "transform_sha256": transform_sha256,
                "timestamps": timestamps,
            },
        }
        receipt_sha256 = _sha256(receipt_material)
        ordered_features.append(
            {
                "ordinal": spec["ordinal"],
                "feature_name": name,
                "source_timeframe": timeframe,
                "transform_id": spec["transform_id"],
                "value_float32": value,
                "value_float32_be_hex": value_hex,
                "composite_derivation_receipt_material": receipt_material,
                "composite_derivation_receipt_material_sha256": receipt_sha256,
            }
        )
        ordered_values.append(value)
        ordered_receipt_sha256s.append(receipt_sha256)
    artifact_material = {
        "schema_version": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION,
        "evidence_classification": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CLASSIFICATION,
        "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": capture.profile_sha256,
        "capture_set_sha256": capture.capture_set_sha256,
        "symbol": capture.symbol,
        "timestamps": timestamps,
        "implementation": {
            "implementation_id": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
            ),
            "module_code_sha256": module_code_sha256,
            "configuration_sha256": (AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256),
            "model_ta_dependency_contract_sha256": (MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256),
            "deployed_talib_environment_sha256": DEPLOYED_TALIB_ENVIRONMENT_SHA256,
        },
        "feature_count": len(ordered_features),
        "ordered_features": ordered_features,
        "auxiliary_label_evidence_requirements": _auxiliary_label_evidence_contract(),
        "authorization": {
            "feature_snapshot_published": False,
            "consumer_eligible": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
            "runtime_wired": False,
        },
    }
    artifact_json = _canonical_json_bytes(artifact_material).decode("ascii")
    artifact_sha256 = hashlib.sha256(artifact_json.encode("ascii")).hexdigest()
    return AuthenticatedOhlcvProfileTransformV1Result(
        schema_version=AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION,
        profile_id=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        profile_sha256=capture.profile_sha256,
        capture_set_sha256=capture.capture_set_sha256,
        symbol=capture.symbol,
        ordered_feature_names=tuple(item["feature_name"] for item in ordered_features),
        ordered_feature_values=tuple(ordered_values),
        ordered_receipt_material_sha256s=tuple(ordered_receipt_sha256s),
        artifact_sha256=artifact_sha256,
        artifact_json=artifact_json,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_AUXILIARY_SCHEMA_VERSION",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_ID",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CAPTURE_POLICY_SHA256",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CLASSIFICATION",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_COMPOSITE_SCHEMA_VERSION",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_MANIFEST_SCHEMA_VERSION",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_INPUT_SCHEMA_VERSION",
    "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION",
    "AuthenticatedOhlcvProfileTransformV1Error",
    "AuthenticatedOhlcvProfileTransformV1Result",
    "ValidatedAuthenticatedOhlcvCaptureSetV1",
    "ValidatedAuthenticatedOhlcvRowV1",
    "transform_authenticated_ohlcv_profile_v1",
    "validate_authenticated_ohlcv_capture_set_v1",
]
