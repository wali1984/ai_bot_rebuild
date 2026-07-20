"""Canonical paper-only adaptive gate tuner.

This system:
1. Monitors actual paper trading outcomes (win rate, PnL, execution speed)
2. Measures prediction accuracy vs confidence
3. Learns market regime (volatility, directional bias, liquidity)
4. Auto-calibrates confidence thresholds based on realized performance
5. Enables/disables grades (B, A, A+) based on evidence accumulation
6. Feeds back to edge gates and gates continuously

Market-dependent tuning is adaptive.  Evidence-integrity requirements are
immutable: only closed, finite, point-in-time-safe outcomes from the current
paper session can influence the canonical policy.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

import redis

logger = logging.getLogger(__name__)

GATE_TUNING_KEY = "v2:orchestrator:adaptive_gate_tuning_state"
REGIME_KEY = "v2:market:regime_analysis"
CALIBRATION_KEY = "v2:trainer:adaptive_confidence_calibration"
OUTCOMES_KEY = "v2:paper:closed_trades"
PAPER_SESSION_KEY = "v2:paper:session"
TRAINER_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
MARKET_CANDLE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MARKET_CANDLE_TIMEFRAME = "1m"
MARKET_CANDLE_KEYS = tuple(
    f"v2:market:ohlcv_closed:binance:{symbol}:{MARKET_CANDLE_TIMEFRAME}"
    for symbol in MARKET_CANDLE_SYMBOLS
)
CANONICAL_SOURCE_KEYS = (
    OUTCOMES_KEY,
    PAPER_SESSION_KEY,
    *MARKET_CANDLE_KEYS,
)

CANONICAL_PRODUCER = "v2.backend.app.cli.v2_adaptive_gate_tuner"
GATE_TUNING_SCHEMA_VERSION = "v2_adaptive_gate_tuning_state_v4"
GATE_TUNING_POLICY_VERSION = "v2_adaptive_gate_policy_v4"
GATE_TUNING_RECEIPT_SCHEMA_VERSION = "v2_adaptive_gate_tuning_receipt_v1"
CANONICAL_SOURCE_SNAPSHOT_SCHEMA_VERSION = "v2_adaptive_gate_source_snapshot_v1"
GATE_TUNING_TTL_SECONDS = 3600
RECENT_OUTCOME_LIMIT = 100
MAX_OUTCOME_SOURCE_ROWS = RECENT_OUTCOME_LIMIT
MAX_MARKET_CANDLE_ROWS_PER_SYMBOL = 100
MAX_CANONICAL_SOURCE_PAYLOAD_BYTES = 12 * 1024 * 1024
MAX_CANONICAL_SOURCE_SNAPSHOT_BYTES = 12 * 1024 * 1024
# The sealed envelope contains base64 copies of at most one complete bounded
# source snapshot plus compact, row-capped derivations.  These limits protect
# every Redis consumer before semantic validation; they are resource-safety
# invariants, not market or admission thresholds.
MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES = 24 * 1024 * 1024
MAX_CANONICAL_GATE_TUNING_JSON_DEPTH = 32
MAX_CANONICAL_GATE_TUNING_JSON_NODES = 100_000
MAX_CANONICAL_GATE_TUNING_JSON_TEXT_BYTES = ((MAX_CANONICAL_SOURCE_PAYLOAD_BYTES + 2) // 3) * 4
# Alias parsing occurs after the bounded source snapshot is decoded, but each
# semantic scalar remains independently bounded so direct validator calls and
# pathological legacy strings cannot trigger unbounded normalization work.
MAX_OUTCOME_ALIAS_TEXT_CHARS = 4096
MAX_OUTCOME_NUMERIC_ALIAS_TEXT_CHARS = 256
MAX_BINARY64_INTEGER_BITS = 1024
MAX_OUTCOME_SOURCE_HASH_ENTRIES = 64
MAX_OUTCOME_SOURCE_HASH_KEY_CHARS = 256
# This is an evidence-integrity floor, not a market or trading threshold.  It
# may never be reduced by market conditions or by a recovery-mode override.
MIN_CLEAN_OUTCOMES_FOR_ADAPTATION = 20
# These are evidence-integrity requirements, not market admission thresholds.
# A source needs enough finalized observations to estimate its own empirical
# distribution, and its newest closed candle must remain within three expected
# publication cadences.  Market-state boundaries are then learned from that
# distribution instead of being fixed bps constants.
MIN_FINAL_CANDLES_PER_SYMBOL = 20
MARKET_CANDLE_CADENCE_SECONDS = 60
MARKET_CANDLE_MAX_STALENESS_CADENCES = 3
# Risk-envelope bounds: the market-derived percentile may tighten or relax
# continuously inside this interval but cannot exceed the audited authority.
MIN_VOLATILITY_FACTOR = 0.70
MAX_VOLATILITY_FACTOR = 1.50
# Probability-domain extrema and audited factor limits.  These are immutable
# fail-closed/safety values, never learned market or performance thresholds.
FAIL_CLOSED_CONFIDENCE_FLOOR = 1.0
FAIL_CLOSED_LOSS_PROBABILITY_CEILING = 0.0
FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE = 0.0
MIN_PERFORMANCE_FACTOR = 0.50
MAX_PERFORMANCE_FACTOR = 1.50
MIN_A_PLUS_STRICTNESS = 1.0
MAX_A_PLUS_STRICTNESS = 2.0
THRESHOLD_DERIVATION_METHOD = "PIT_EMPIRICAL_RANKS_CALIBRATION_EDGE_AND_WILSON_ONE_SE_V1"

IMMUTABLE_BOUND_CLASSIFICATION: dict[str, dict[str, Any]] = {
    "minimum_clean_outcomes": {
        "value": MIN_CLEAN_OUTCOMES_FOR_ADAPTATION,
        "class": "EVIDENCE_INTEGRITY_SAMPLE_FLOOR",
    },
    "minimum_final_candles_per_symbol": {
        "value": MIN_FINAL_CANDLES_PER_SYMBOL,
        "class": "EVIDENCE_INTEGRITY_DISTRIBUTION_FLOOR",
    },
    "market_candle_staleness_cadences": {
        "value": MARKET_CANDLE_MAX_STALENESS_CADENCES,
        "class": "POINT_IN_TIME_FRESHNESS_BOUND",
    },
    "publication_ttl_seconds": {
        "value": GATE_TUNING_TTL_SECONDS,
        "class": "RESOURCE_AND_REVOCABILITY_BOUND",
    },
    "recent_outcome_window_cap": {
        "value": RECENT_OUTCOME_LIMIT,
        "class": "BOUNDED_COMPUTE_AND_RECENCY_WINDOW",
    },
    "maximum_outcome_source_rows": {
        "value": MAX_OUTCOME_SOURCE_ROWS,
        "class": "BOUNDED_COMPUTE_SOURCE_ROW_LIMIT",
    },
    "maximum_market_candle_rows_per_symbol": {
        "value": MAX_MARKET_CANDLE_ROWS_PER_SYMBOL,
        "class": "BOUNDED_COMPUTE_SOURCE_ROW_LIMIT",
    },
    "maximum_canonical_source_payload_bytes": {
        "value": MAX_CANONICAL_SOURCE_PAYLOAD_BYTES,
        "class": "BOUNDED_COMPUTE_SOURCE_BYTE_LIMIT",
    },
    "maximum_canonical_source_snapshot_bytes": {
        "value": MAX_CANONICAL_SOURCE_SNAPSHOT_BYTES,
        "class": "BOUNDED_COMPUTE_SOURCE_BYTE_LIMIT",
    },
    "maximum_canonical_gate_tuning_payload_bytes": {
        "value": MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES,
        "class": "BOUNDED_COMPUTE_CONSUMER_BYTE_LIMIT",
    },
    "maximum_canonical_gate_tuning_json_depth": {
        "value": MAX_CANONICAL_GATE_TUNING_JSON_DEPTH,
        "class": "BOUNDED_COMPUTE_CONSUMER_DEPTH_LIMIT",
    },
    "maximum_canonical_gate_tuning_json_nodes": {
        "value": MAX_CANONICAL_GATE_TUNING_JSON_NODES,
        "class": "BOUNDED_COMPUTE_CONSUMER_NODE_LIMIT",
    },
    "maximum_canonical_gate_tuning_json_text_bytes": {
        "value": MAX_CANONICAL_GATE_TUNING_JSON_TEXT_BYTES,
        "class": "BOUNDED_COMPUTE_CONSUMER_TEXT_LIMIT",
    },
    "maximum_outcome_alias_text_characters": {
        "value": MAX_OUTCOME_ALIAS_TEXT_CHARS,
        "class": "BOUNDED_COMPUTE_ALIAS_TEXT_LIMIT",
    },
    "maximum_outcome_numeric_alias_text_characters": {
        "value": MAX_OUTCOME_NUMERIC_ALIAS_TEXT_CHARS,
        "class": "BOUNDED_COMPUTE_ALIAS_NUMERIC_TEXT_LIMIT",
    },
    "maximum_outcome_source_hash_entries": {
        "value": MAX_OUTCOME_SOURCE_HASH_ENTRIES,
        "class": "BOUNDED_COMPUTE_LINEAGE_ENTRY_LIMIT",
    },
    "maximum_outcome_source_hash_key_characters": {
        "value": MAX_OUTCOME_SOURCE_HASH_KEY_CHARS,
        "class": "BOUNDED_COMPUTE_LINEAGE_KEY_LIMIT",
    },
    "canonical_source_value_types": {
        "value": ["UTF8_STRING", "IMMUTABLE_BYTES"],
        "class": "IMMUTABLE_EXACT_SOURCE_BYTE_CONTRACT",
    },
    "market_candle_expected_cadence_seconds": {
        "value": MARKET_CANDLE_CADENCE_SECONDS,
        "class": "SOURCE_SCHEMA_CADENCE_CONTRACT",
    },
    "outcome_required_point_in_time_clocks": {
        "value": [
            "feature_cutoff",
            "feature_available_at",
            "decision_time",
            "entry_execution_time",
            "close_time",
            "outcome_available_at",
        ],
        "class": "POINT_IN_TIME_LINEAGE_INTEGRITY_CONTRACT",
    },
    "empirical_uncertainty_estimator": {
        "value": "MEAN_MINUS_ONE_STANDARD_ERROR_AND_BERNOULLI_WILSON_ONE_SE",
        "class": "EVIDENCE_QUALITY_STATISTICAL_METHOD",
    },
    "confidence_probability_domain": {
        "value": [0.0, 1.0],
        "class": "MATHEMATICAL_PROBABILITY_DOMAIN",
    },
    "fail_closed_confidence_floor": {
        "value": FAIL_CLOSED_CONFIDENCE_FLOOR,
        "class": "IMMUTABLE_FAIL_CLOSED_PROBABILITY_EXTREMUM",
    },
    "fail_closed_loss_probability_ceiling": {
        "value": FAIL_CLOSED_LOSS_PROBABILITY_CEILING,
        "class": "IMMUTABLE_FAIL_CLOSED_PROBABILITY_EXTREMUM",
    },
    "fail_closed_entry_freeze_allowance": {
        "value": FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE,
        "class": "IMMUTABLE_FAIL_CLOSED_PROBABILITY_EXTREMUM",
    },
    "volatility_factor_envelope": {
        "value": [MIN_VOLATILITY_FACTOR, MAX_VOLATILITY_FACTOR],
        "class": "AUDITED_RISK_ENVELOPE",
    },
    "performance_factor_envelope": {
        "value": [MIN_PERFORMANCE_FACTOR, MAX_PERFORMANCE_FACTOR],
        "class": "AUDITED_RISK_ENVELOPE",
    },
    "a_plus_strictness_envelope": {
        "value": [MIN_A_PLUS_STRICTNESS, MAX_A_PLUS_STRICTNESS],
        "class": "AUDITED_RISK_ENVELOPE",
    },
    "positive_edge_boundary_bps": {
        "value": 0.0,
        "class": "ECONOMIC_NONLOSS_INVARIANT",
    },
}


class RedisReader(Protocol):
    def get(self, key: str) -> Any: ...


class RedisStore(RedisReader, Protocol):
    def set(self, key: str, value: str, ex: int | None = None) -> Any: ...


GATE_TUNING_POLICY_VALUE_FIELDS = (
    "adaptive_confidence_threshold",
    "adaptive_loss_probability_threshold",
    "enable_b_grade",
    "enable_a_grade",
    "a_grade_ready",
    "blockers_resolved",
    "volatility_factor",
    "trainer_performance_factor",
    "portfolio_performance_factor",
    "adaptive_long_confidence_floor",
    "adaptive_short_confidence_floor",
    "adaptive_expectancy_floor",
    "adaptive_entry_freeze_allowance",
    "adaptive_a_plus_strictness",
)

_CLOSE_TIME_FIELDS = (
    "exit_time",
    "exit_price_utc",
    "closed_at",
    "closed_utc",
    "close_time",
)
_OUTCOME_AVAILABLE_FIELDS = (
    "outcome_available_at",
    "close_available_at",
    "closed_available_at",
)
_FEATURE_CUTOFF_FIELDS = ("feature_cutoff", "entry_feature_cutoff")
_FEATURE_AVAILABLE_FIELDS = (
    "feature_available_at",
    "entry_feature_available_at",
)
_LEGACY_FEATURE_AVAILABLE_FIELDS = ("available_at",)
_DECISION_TIME_FIELDS = ("decision_time", "entry_decision_time")
_ENTRY_EXECUTION_TIME_FIELDS = ("entry_execution_time", "entry_time")
_CLOSE_ID_FIELDS = ("close_id", "paper_close_id")
_REALIZED_PNL_FIELDS = (
    "realized_net_pnl_usd",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "pnl_usd",
    "pnl",
)
_CONFIDENCE_FIELDS = (
    "entry_confidence_calibrated",
    "confidence_calibrated",
    "entry_confidence",
    "confidence",
)
_CLOSED_QUANTITY_FIELDS = ("closed_quantity", "close_quantity", "quantity")
_EXIT_PRICE_FIELDS = ("exit_price", "exit_fill_price")
_CLOSE_REASON_FIELDS = ("close_reason", "exit_reason")
_NUMERIC_ALIAS_CHARACTERS = frozenset("0123456789+-.eE")
_CANONICAL_UTC_MICROSECOND_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"
)
_CONSUMER_UTC_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_aware_utc(value: Any) -> datetime | None:
    """Parse a bounded UTC-Z consumer clock without lossy precision normalization."""

    if type(value) is not str or _CONSUMER_UTC_PATTERN.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _parse_canonical_microsecond_utc(value: Any) -> datetime | None:
    """Parse exactly ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` without normalization."""

    if type(value) is not str or _CANONICAL_UTC_MICROSECOND_PATTERN.fullmatch(value) is None:
        return None
    parsed = _parse_aware_utc(value)
    if parsed is None or _utc_iso(parsed) != value:
        return None
    return parsed


def _parse_source_clock(value: Any) -> datetime | None:
    """Parse one canonical exchange millisecond epoch into UTC exactly.

    Canonical closed-candle rows publish integer millisecond epochs.  Strings,
    floats, bools, and second-epoch heuristics are deliberately unsupported so
    aliases cannot compare equal only after lossy parsing or unit guessing.
    """

    if type(value) is not int or value.bit_length() > 63:
        return None
    try:
        seconds, milliseconds = divmod(value, 1000)
        return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=milliseconds)
    except (OverflowError, OSError, ValueError):
        return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical_json_type_exact_equal(left: Any, right: Any) -> bool:
    """Compare JSON material without Python's bool/numeric type coercion."""

    try:
        return _canonical_json(left) == _canonical_json(right)
    except (MemoryError, RecursionError, TypeError, UnicodeError, ValueError):
        return False


def _sha256_canonical(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _raw_bytes(value: Any) -> bytes:
    if value is None:
        return b"\x00MISSING"
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    return str(value).encode("utf-8")


def _freeze_source_value(value: Any) -> tuple[str | bytes | None, str | None]:
    """Copy one Redis value into an immutable, byte-exact supported type."""

    if value is None or isinstance(value, str | bytes):
        return value, None
    if isinstance(value, bytearray | memoryview):
        return bytes(value), None
    return None, "SOURCE_VALUE_TYPE_INVALID"


def _raw_sha256(value: Any) -> str:
    return hashlib.sha256(_raw_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class _DuplicateJsonKeyError(ValueError):
    """Raised when JSON object identity is ambiguous."""


class _NonFiniteJsonNumberError(ValueError):
    """Raised for non-standard JSON numeric constants."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, item in pairs:
        if key in decoded:
            raise _DuplicateJsonKeyError
        decoded[key] = item
    return decoded


def _reject_nonfinite_json_number(value: str) -> None:
    raise _NonFiniteJsonNumberError(value)


def _bounded_utf8_byte_count(value: str) -> tuple[int | None, str | None]:
    """Count UTF-8 bytes without first allocating an unbounded encoding."""

    byte_count = 0
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            byte_count += 1
        elif codepoint <= 0x7FF:
            byte_count += 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            return None, "CANONICAL_PAYLOAD_UTF8_INVALID"
        elif codepoint <= 0xFFFF:
            byte_count += 3
        else:
            byte_count += 4
        if byte_count > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
            return None, "CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"
    return byte_count, None


def _encode_utf8_exact(value: str) -> bytes:
    return str.encode(value, "utf-8")


def _copy_buffer_exact(value: bytearray | memoryview) -> bytes:
    return bytes(value)


def capture_canonical_gate_tuning_redis_bytes(
    value: Any,
) -> tuple[bytes | None, list[str]]:
    """Freeze one supported Redis value into bounded immutable exact bytes."""

    if value is None:
        return None, ["CANONICAL_PAYLOAD_MISSING"]
    if isinstance(value, str):
        if len(value) > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
            return None, ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]
        byte_count, count_error = _bounded_utf8_byte_count(value)
        if count_error is not None:
            return None, [count_error]
        try:
            raw = _encode_utf8_exact(value)
        except (MemoryError, UnicodeError):
            return None, ["CANONICAL_PAYLOAD_UTF8_INVALID"]
        if byte_count is None or len(raw) != byte_count:
            return None, ["CANONICAL_PAYLOAD_UTF8_INVALID"]
    elif isinstance(value, bytes):
        raw = value
    elif isinstance(value, bytearray):
        try:
            if len(value) > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
                return None, ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]
            raw = _copy_buffer_exact(value)
        except (BufferError, MemoryError, OverflowError, RuntimeError, TypeError, ValueError):
            return None, ["CANONICAL_PAYLOAD_BUFFER_INVALID"]
    elif isinstance(value, memoryview):
        try:
            if value.nbytes > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
                return None, ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]
            raw = _copy_buffer_exact(value)
        except (BufferError, MemoryError, OverflowError, RuntimeError, TypeError, ValueError):
            return None, ["CANONICAL_PAYLOAD_BUFFER_INVALID"]
    else:
        return None, ["CANONICAL_PAYLOAD_TYPE_INVALID"]
    # Mutable buffers can change size after the pre-check but before/during the
    # copy.  Only the immutable post-copy size is authoritative.
    if len(raw) > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
        return None, ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]
    return raw, []


_JSON_WHITESPACE_BYTES = frozenset(b" \t\r\n")
_JSON_PRIMITIVE_BYTES = frozenset(b"0123456789+-.eEtruefalsnul")
_JSON_CONTAINER_CLOSE = {ord("}"): ord("{"), ord("]"): ord("[")}


def _canonical_gate_tuning_lexical_rejection_reasons(raw: bytes) -> list[str]:
    """Reject structurally overbound JSON before invoking the JSON parser.

    This scanner intentionally does not replace JSON syntax validation.  It
    only establishes conservative depth, token-node, and raw-string bounds,
    while honoring quoted strings and backslash escapes exactly enough that
    delimiters inside text can never consume structural budget.
    """

    containers: list[int] = []
    node_count = 0
    in_string = False
    escaped = False
    in_primitive = False
    string_byte_count = 0

    def count_node(*, depth: int) -> str | None:
        nonlocal node_count
        if depth > MAX_CANONICAL_GATE_TUNING_JSON_DEPTH:
            return "CANONICAL_PAYLOAD_JSON_DEPTH_LIMIT_EXCEEDED"
        node_count += 1
        return (
            "CANONICAL_PAYLOAD_JSON_NODE_LIMIT_EXCEEDED"
            if node_count > MAX_CANONICAL_GATE_TUNING_JSON_NODES
            else None
        )

    for byte in raw:
        if in_string:
            if escaped:
                string_byte_count += 1
                escaped = False
            elif byte == ord("\\"):
                string_byte_count += 1
                escaped = True
            elif byte == ord('"'):
                in_string = False
            else:
                string_byte_count += 1
            if string_byte_count > MAX_CANONICAL_GATE_TUNING_JSON_TEXT_BYTES:
                return ["CANONICAL_PAYLOAD_JSON_TEXT_LIMIT_EXCEEDED"]
            continue

        if in_primitive:
            if byte in _JSON_PRIMITIVE_BYTES:
                continue
            in_primitive = False

        if byte in _JSON_WHITESPACE_BYTES or byte in (ord(":"), ord(",")):
            continue
        if byte == ord('"'):
            node_error = count_node(depth=len(containers))
            if node_error is not None:
                return [node_error]
            in_string = True
            escaped = False
            string_byte_count = 0
            continue
        if byte in (ord("{"), ord("[")):
            node_error = count_node(depth=len(containers))
            if node_error is not None:
                return [node_error]
            containers.append(byte)
            continue
        if byte in _JSON_CONTAINER_CLOSE:
            if not containers or containers[-1] != _JSON_CONTAINER_CLOSE[byte]:
                return ["CANONICAL_PAYLOAD_MALFORMED_JSON"]
            containers.pop()
            continue
        node_error = count_node(depth=len(containers))
        if node_error is not None:
            return [node_error]
        in_primitive = True

    if in_string or containers:
        return ["CANONICAL_PAYLOAD_MALFORMED_JSON"]
    return []


def _decode_json(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return None, "SOURCE_KEY_MISSING"

    try:
        return (
            json.loads(
                _raw_bytes(value).decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            ),
            None,
        )
    except _DuplicateJsonKeyError:
        return None, "SOURCE_PAYLOAD_DUPLICATE_JSON_KEY"
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        return None, "SOURCE_PAYLOAD_MALFORMED_JSON"


def _canonical_gate_tuning_structure_rejection_reasons(value: Any) -> list[str]:
    """Bound one decoded canonical envelope before semantic field access."""

    if not isinstance(value, Mapping):
        return ["CANONICAL_PAYLOAD_ROOT_INVALID"]

    stack: list[tuple[Any, int]] = [(value, 0)]
    node_count = 0
    total_text_bytes = 0
    while stack:
        item, depth = stack.pop()
        node_count += 1
        if node_count > MAX_CANONICAL_GATE_TUNING_JSON_NODES:
            return ["CANONICAL_PAYLOAD_JSON_NODE_LIMIT_EXCEEDED"]
        if depth > MAX_CANONICAL_GATE_TUNING_JSON_DEPTH:
            return ["CANONICAL_PAYLOAD_JSON_DEPTH_LIMIT_EXCEEDED"]
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            try:
                number = float(item)
            except (OverflowError, TypeError, ValueError):
                return ["CANONICAL_PAYLOAD_NUMERIC_INVALID"]
            if not math.isfinite(number):
                return ["CANONICAL_PAYLOAD_NUMERIC_INVALID"]
            continue
        if type(item) is float:
            if not math.isfinite(item):
                return ["CANONICAL_PAYLOAD_NUMERIC_INVALID"]
            continue
        if type(item) is str:
            try:
                text_bytes = len(item.encode("utf-8"))
            except UnicodeError:
                return ["CANONICAL_PAYLOAD_TEXT_INVALID"]
            if text_bytes > MAX_CANONICAL_GATE_TUNING_JSON_TEXT_BYTES:
                return ["CANONICAL_PAYLOAD_JSON_TEXT_LIMIT_EXCEEDED"]
            total_text_bytes += text_bytes
            if total_text_bytes > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
                return ["CANONICAL_PAYLOAD_JSON_TEXT_LIMIT_EXCEEDED"]
            continue
        if isinstance(item, Mapping):
            try:
                pairs = tuple(item.items())
            except (MemoryError, RecursionError, RuntimeError, TypeError, ValueError):
                return ["CANONICAL_PAYLOAD_JSON_TYPE_INVALID"]
            remaining_nodes = MAX_CANONICAL_GATE_TUNING_JSON_NODES - node_count
            if len(pairs) > remaining_nodes // 2:
                return ["CANONICAL_PAYLOAD_JSON_NODE_LIMIT_EXCEEDED"]
            for key, nested in pairs:
                if type(key) is not str:
                    return ["CANONICAL_PAYLOAD_JSON_OBJECT_KEY_INVALID"]
                stack.append((nested, depth + 1))
                stack.append((key, depth + 1))
            continue
        if type(item) is list:
            if len(item) > MAX_CANONICAL_GATE_TUNING_JSON_NODES - node_count:
                return ["CANONICAL_PAYLOAD_JSON_NODE_LIMIT_EXCEEDED"]
            stack.extend((nested, depth + 1) for nested in item)
            continue
        return ["CANONICAL_PAYLOAD_JSON_TYPE_INVALID"]

    try:
        canonical_byte_count = len(_canonical_json(value).encode("utf-8"))
    except (MemoryError, RecursionError, TypeError, UnicodeError, ValueError):
        return ["CANONICAL_PAYLOAD_NOT_CANONICAL_JSON"]
    if canonical_byte_count > MAX_CANONICAL_GATE_TUNING_PAYLOAD_BYTES:
        return ["CANONICAL_PAYLOAD_BYTE_LIMIT_EXCEEDED"]
    return []


def decode_canonical_gate_tuning_redis_payload(
    value: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Strictly decode one bounded canonical Redis value without ambiguity."""

    raw, capture_rejection_reasons = capture_canonical_gate_tuning_redis_bytes(value)
    if capture_rejection_reasons:
        return None, capture_rejection_reasons
    assert raw is not None
    lexical_rejection_reasons = _canonical_gate_tuning_lexical_rejection_reasons(raw)
    if lexical_rejection_reasons:
        return None, lexical_rejection_reasons
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, ["CANONICAL_PAYLOAD_UTF8_INVALID"]
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json_number,
        )
    except _DuplicateJsonKeyError:
        return None, ["CANONICAL_PAYLOAD_DUPLICATE_JSON_KEY"]
    except _NonFiniteJsonNumberError:
        return None, ["CANONICAL_PAYLOAD_NUMERIC_INVALID"]
    except (json.JSONDecodeError, MemoryError, RecursionError, TypeError, ValueError):
        return None, ["CANONICAL_PAYLOAD_MALFORMED_JSON"]
    if not isinstance(decoded, dict):
        return None, ["CANONICAL_PAYLOAD_ROOT_INVALID"]
    rejection_reasons = _canonical_gate_tuning_structure_rejection_reasons(decoded)
    return (None, rejection_reasons) if rejection_reasons else (decoded, [])


def _extract_outcome_rows(payload: Any) -> tuple[list[Any], str | None]:
    if type(payload) is list:
        return payload, None
    if isinstance(payload, Mapping):
        collections = [
            payload[field] for field in ("trades", "closed_trades", "rows") if field in payload
        ]
        if not collections:
            return [], "SOURCE_PAYLOAD_ROWS_MISSING"
        if any(type(rows) is not list for rows in collections):
            return [], "SOURCE_PAYLOAD_ROWS_INVALID"
        if any(
            not _canonical_json_type_exact_equal(rows, collections[0]) for rows in collections[1:]
        ):
            return [], "SOURCE_PAYLOAD_ROWS_ALIAS_CONFLICT"
        return collections[0], None
    if payload is None:
        return [], None
    return [], "SOURCE_PAYLOAD_ROOT_INVALID"


def _strict_aliased_nonempty_text(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    missing_reason: str,
    invalid_reason: str,
    conflict_reason: str,
) -> tuple[str | None, list[str]]:
    """Require every alias key that exists to carry the same bounded text."""

    raw_values = [row[field] for field in fields if field in row]
    if not raw_values:
        return None, [missing_reason]
    normalized: list[str] = []
    for value in raw_values:
        if type(value) is not str or len(value) > MAX_OUTCOME_ALIAS_TEXT_CHARS:
            return None, [invalid_reason]
        stripped = value.strip()
        if not stripped:
            return None, [invalid_reason]
        normalized.append(stripped)
    if any(value != normalized[0] for value in normalized[1:]):
        return None, [conflict_reason]
    return normalized[0], []


def _session_identity(payload: Any) -> tuple[str | None, list[str]]:
    if not isinstance(payload, Mapping):
        return None, ["CURRENT_PAPER_SESSION_PAYLOAD_MISSING"]
    session_id, reasons = _strict_aliased_nonempty_text(
        payload,
        ("paper_session_id", "reset_session_id", "session_id"),
        missing_reason="CURRENT_PAPER_SESSION_ID_MISSING",
        invalid_reason="CURRENT_PAPER_SESSION_ID_TYPE_INVALID",
        conflict_reason="CURRENT_PAPER_SESSION_IDENTITY_CONFLICT",
    )
    if payload.get("paper_only") is not True:
        reasons.append("CURRENT_PAPER_SESSION_NOT_EXPLICITLY_PAPER_ONLY")
    if payload.get("routes_to_live") is not False:
        reasons.append("CURRENT_PAPER_SESSION_LIVE_ROUTE_STATUS_NOT_FALSE")
    if payload.get("places_real_order") is not False:
        reasons.append("CURRENT_PAPER_SESSION_REAL_ORDER_STATUS_NOT_FALSE")
    return (session_id if not reasons else None, sorted(set(reasons)))


def _present_alias_values(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
) -> list[Any]:
    """Return aliases whose keys exist, including invalid null/empty values."""

    return [row[field] for field in fields if field in row]


def _aliased_nonempty_text(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    field_name: str,
) -> tuple[str | None, list[str]]:
    """Require every populated text alias to be bounded and equivalent."""

    return _strict_aliased_nonempty_text(
        row,
        fields,
        missing_reason=f"{field_name}_MISSING",
        invalid_reason=f"{field_name}_TYPE_INVALID",
        conflict_reason=f"{field_name}_ALIAS_CONFLICT",
    )


def _bounded_exact_numeric(value: Any) -> tuple[Decimal, float] | None:
    """Parse one scalar into exact comparison material and finite binary64."""

    if type(value) is int:
        if value.bit_length() > MAX_BINARY64_INTEGER_BITS:
            return None
        exact = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            return None
        exact = Decimal(str(value))
    elif type(value) is str:
        if len(value) > MAX_OUTCOME_NUMERIC_ALIAS_TEXT_CHARS:
            return None
        text = value.strip()
        if (
            not text
            or not text.isascii()
            or not any(character.isdigit() for character in text)
            or any(character not in _NUMERIC_ALIAS_CHARACTERS for character in text)
        ):
            return None
        try:
            exact = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    else:
        # In particular, bool must never compare equal to integer zero/one.
        return None
    if not exact.is_finite():
        return None
    try:
        normalized = float(exact)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(normalized) or (normalized == 0.0 and exact != 0):
        return None
    return exact, normalized


def _aliased_finite_numeric(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    invalid_reason: str,
    conflict_reason: str,
) -> tuple[float | None, list[str]]:
    """Require every populated numeric alias to be finite and exactly equal."""

    raw_values = _present_alias_values(row, fields)
    if not raw_values:
        return None, [invalid_reason]
    parsed = [_bounded_exact_numeric(value) for value in raw_values]
    if any(value is None for value in parsed):
        return None, [invalid_reason]
    valid = [value for value in parsed if value is not None]
    first_exact, first_normalized = valid[0]
    if any(exact != first_exact for exact, _normalized in valid[1:]):
        return None, [conflict_reason]
    return first_normalized, []


def _aliased_aware_utc(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    clock_name: str,
    required: bool = True,
) -> tuple[datetime | None, list[str]]:
    """Resolve equivalent clock aliases without concealing conflicts."""

    raw_values = _present_alias_values(row, fields)
    if not raw_values:
        return (None, [f"{clock_name}_MISSING"]) if required else (None, [])
    if any(type(value) is not str for value in raw_values):
        return None, [f"{clock_name}_NOT_AWARE"]
    if any(len(value) > MAX_OUTCOME_ALIAS_TEXT_CHARS for value in raw_values):
        return None, [f"{clock_name}_NOT_AWARE"]
    parsed_values = [_parse_canonical_microsecond_utc(value) for value in raw_values]
    if any(value is None for value in parsed_values):
        return None, [f"{clock_name}_NOT_AWARE"]
    if any(value != raw_values[0] for value in raw_values[1:]):
        return None, [f"{clock_name}_ALIAS_CONFLICT"]
    parsed = parsed_values[0]
    assert parsed is not None
    return parsed, []


def _aliased_source_clock(
    row: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    clock_name: str,
) -> tuple[datetime | None, list[str]]:
    """Require every present exchange-clock alias to be valid and equal."""

    raw_values = _present_alias_values(row, fields)
    if not raw_values:
        return None, [f"{clock_name}_INVALID"]
    if any(type(value) is not int for value in raw_values):
        return None, [f"{clock_name}_INVALID"]
    if any(value != raw_values[0] for value in raw_values[1:]):
        return None, [f"{clock_name}_ALIAS_CONFLICT"]
    parsed = _parse_source_clock(raw_values[0])
    if parsed is None:
        return None, [f"{clock_name}_INVALID"]
    return parsed, []


def _optional_normalized_grade(row: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """Normalize a compatible optional grade without coercing its type."""

    if "grade" not in row or row["grade"] in (None, ""):
        return None, []
    value = row["grade"]
    if type(value) is not str or len(value) > MAX_OUTCOME_ALIAS_TEXT_CHARS:
        return None, ["GRADE_TYPE_INVALID"]
    normalized = value.strip().upper()
    if not normalized:
        return None, ["GRADE_TYPE_INVALID"]
    return normalized, []


def _validated_source_hash_lineage(
    row: Mapping[str, Any],
) -> tuple[dict[str, str] | None, list[str]]:
    """Validate and copy the complete bounded source-hash lineage dictionary."""

    if "source_hashes" not in row:
        return None, ["SOURCE_HASH_LINEAGE_MISSING"]
    source_hashes = row["source_hashes"]
    if type(source_hashes) is not dict:
        return None, ["SOURCE_HASH_LINEAGE_CONTAINER_INVALID"]
    if not source_hashes:
        return None, ["SOURCE_HASH_LINEAGE_EMPTY"]
    if len(source_hashes) > MAX_OUTCOME_SOURCE_HASH_ENTRIES:
        return None, ["SOURCE_HASH_LINEAGE_ENTRY_LIMIT_EXCEEDED"]

    validated: dict[str, str] = {}
    reasons: list[str] = []
    try:
        for key, value in source_hashes.items():
            if (
                type(key) is not str
                or len(key) > MAX_OUTCOME_SOURCE_HASH_KEY_CHARS
                or not key.strip()
                or key != key.strip()
            ):
                reasons.append("SOURCE_HASH_LINEAGE_KEY_INVALID")
                continue
            if type(value) is not str or not _is_sha256(value):
                reasons.append("SOURCE_HASH_LINEAGE_VALUE_INVALID")
                continue
            validated[key] = value
    except (RuntimeError, TypeError, ValueError):
        return None, ["SOURCE_HASH_LINEAGE_CONTAINER_INVALID"]
    if reasons:
        if not validated:
            reasons.append("SOURCE_HASH_LINEAGE_HAS_NO_CANONICAL_SHA256")
        return None, sorted(set(reasons))

    for key, value in validated.items():
        if key in row and row[key] != value:
            reasons.append(f"SOURCE_HASH_LINEAGE_CONFLICT:{key}")
    return (None, sorted(set(reasons))) if reasons else (validated, [])


def _outcome_row_rejection_reasons(
    row: Any,
    *,
    outcomes_cutoff: datetime,
    current_paper_session_id: str | None,
) -> tuple[list[str], dict[str, Any] | None]:
    if not isinstance(row, Mapping):
        return ["ROW_NOT_OBJECT"], None

    reasons: list[str] = []
    if current_paper_session_id is None:
        reasons.append("CURRENT_PAPER_SESSION_ID_UNAVAILABLE")
    row_session_fields = ("paper_session_id", "reset_session_id", "session_id")
    row_session_id, row_session_reasons = _strict_aliased_nonempty_text(
        row,
        row_session_fields,
        missing_reason="ROW_SESSION_ID_MISSING",
        invalid_reason="ROW_SESSION_ID_TYPE_INVALID",
        conflict_reason="ROW_SESSION_IDENTITY_CONFLICT",
    )
    reasons.extend(row_session_reasons)
    if (
        current_paper_session_id is not None
        and row_session_id is not None
        and row_session_id != current_paper_session_id
    ):
        reasons.append("ROW_SESSION_MISMATCH")

    if row.get("paper_only") is not True:
        reasons.append("ROW_NOT_EXPLICITLY_PAPER_ONLY")
    if row.get("places_real_order") is not False:
        reasons.append("ROW_REAL_ORDER_STATUS_NOT_FALSE")
    if row.get("routes_to_live") is not False:
        reasons.append("ROW_LIVE_ROUTE_STATUS_NOT_FALSE")
    if (
        row.get("dirty_flag") is not False
        or type(row.get("dirty_reasons")) is not list
        or bool(row.get("dirty_reasons"))
    ):
        reasons.append("ROW_DIRTY")
    if row.get("future_labels_used_as_features") is not False:
        reasons.append("ROW_FUTURE_LABEL_LEAKAGE_FLAGGED")
    if (
        row.get("candidate_selected_after_outcome") is not False
        or row.get("post_outcome_candidate_selection") is not False
    ):
        reasons.append("ROW_POST_OUTCOME_SELECTION_FLAGGED")

    close_id, close_id_reasons = _aliased_nonempty_text(
        row,
        _CLOSE_ID_FIELDS,
        field_name="CLOSE_ID",
    )
    reasons.extend(close_id_reasons)
    position_id, position_id_reasons = _aliased_nonempty_text(
        row,
        ("position_id",),
        field_name="POSITION_ID",
    )
    reasons.extend(position_id_reasons)

    prediction_id_fields = (
        "prediction_id",
        "entry_prediction_id",
        "source_prediction_id",
    )
    prediction_id, prediction_id_reasons = _strict_aliased_nonempty_text(
        row,
        prediction_id_fields,
        missing_reason="PREDICTION_LINEAGE_MISSING",
        invalid_reason="PREDICTION_LINEAGE_TYPE_INVALID",
        conflict_reason="PREDICTION_LINEAGE_CONFLICT",
    )
    reasons.extend(prediction_id_reasons)
    canonical_source_hashes, source_hash_reasons = _validated_source_hash_lineage(row)
    reasons.extend(source_hash_reasons)

    pnl, pnl_reasons = _aliased_finite_numeric(
        row,
        _REALIZED_PNL_FIELDS,
        invalid_reason="REALIZED_PNL_MISSING_OR_NONFINITE",
        conflict_reason="REALIZED_PNL_ALIAS_CONFLICT",
    )
    confidence, confidence_reasons = _aliased_finite_numeric(
        row,
        _CONFIDENCE_FIELDS,
        invalid_reason="CONFIDENCE_MISSING_NONFINITE_OR_OUT_OF_RANGE",
        conflict_reason="CONFIDENCE_ALIAS_CONFLICT",
    )
    close_quantity, close_quantity_reasons = _aliased_finite_numeric(
        row,
        _CLOSED_QUANTITY_FIELDS,
        invalid_reason="CLOSED_QUANTITY_MISSING_NONFINITE_OR_NONPOSITIVE",
        conflict_reason="CLOSED_QUANTITY_ALIAS_CONFLICT",
    )
    exit_price, exit_price_reasons = _aliased_finite_numeric(
        row,
        _EXIT_PRICE_FIELDS,
        invalid_reason="EXIT_PRICE_MISSING_NONFINITE_OR_NONPOSITIVE",
        conflict_reason="EXIT_PRICE_ALIAS_CONFLICT",
    )
    reasons.extend(pnl_reasons)
    reasons.extend(confidence_reasons)
    reasons.extend(close_quantity_reasons)
    reasons.extend(exit_price_reasons)
    entry_price = _finite(row.get("entry_price"))
    if confidence is None or not 0.0 <= confidence <= 1.0:
        reasons.append("CONFIDENCE_MISSING_NONFINITE_OR_OUT_OF_RANGE")
    if close_quantity is None or close_quantity <= 0.0:
        reasons.append("CLOSED_QUANTITY_MISSING_NONFINITE_OR_NONPOSITIVE")
    if entry_price is None or entry_price <= 0.0:
        reasons.append("ENTRY_PRICE_MISSING_NONFINITE_OR_NONPOSITIVE")
    if exit_price is None or exit_price <= 0.0:
        reasons.append("EXIT_PRICE_MISSING_NONFINITE_OR_NONPOSITIVE")
    entry_notional_usd: float | None = None
    realized_pnl_bps: float | None = None
    if close_quantity is not None and close_quantity > 0.0 and entry_price is not None:
        entry_notional_usd = close_quantity * entry_price
        if not math.isfinite(entry_notional_usd) or entry_notional_usd <= 0.0:
            reasons.append("ENTRY_NOTIONAL_NONFINITE_OR_NONPOSITIVE")
            entry_notional_usd = None
        elif pnl is not None:
            realized_pnl_bps = (pnl / entry_notional_usd) * 10_000.0
            if not math.isfinite(realized_pnl_bps):
                reasons.append("REALIZED_PNL_BPS_NONFINITE")
                realized_pnl_bps = None
    _close_reason, close_reason_reasons = _aliased_nonempty_text(
        row,
        _CLOSE_REASON_FIELDS,
        field_name="CLOSE_REASON",
    )
    reasons.extend(close_reason_reasons)
    grade, grade_reasons = _optional_normalized_grade(row)
    reasons.extend(grade_reasons)

    feature_cutoff, feature_cutoff_reasons = _aliased_aware_utc(
        row,
        _FEATURE_CUTOFF_FIELDS,
        clock_name="FEATURE_CUTOFF",
    )
    feature_available_at, feature_available_reasons = _aliased_aware_utc(
        row,
        _FEATURE_AVAILABLE_FIELDS + _LEGACY_FEATURE_AVAILABLE_FIELDS,
        clock_name="FEATURE_AVAILABLE_AT",
    )
    decision_time, decision_time_reasons = _aliased_aware_utc(
        row,
        _DECISION_TIME_FIELDS,
        clock_name="DECISION_TIME",
    )
    entry_execution_time, entry_execution_reasons = _aliased_aware_utc(
        row,
        _ENTRY_EXECUTION_TIME_FIELDS,
        clock_name="ENTRY_EXECUTION_TIME",
    )
    reasons.extend(feature_cutoff_reasons)
    reasons.extend(feature_available_reasons)
    reasons.extend(decision_time_reasons)
    reasons.extend(entry_execution_reasons)
    if feature_cutoff is not None and feature_available_at is not None:
        if feature_cutoff > feature_available_at:
            reasons.append("FEATURE_CUTOFF_AFTER_FEATURE_AVAILABLE_AT")
    if feature_cutoff is not None and decision_time is not None:
        if feature_cutoff > decision_time:
            reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if feature_available_at is not None and decision_time is not None:
        if feature_available_at > decision_time:
            reasons.append("FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME")
    if decision_time is not None and entry_execution_time is not None:
        if decision_time > entry_execution_time:
            reasons.append("DECISION_TIME_AFTER_ENTRY_EXECUTION_TIME")

    close_time, close_time_reasons = _aliased_aware_utc(
        row,
        _CLOSE_TIME_FIELDS,
        clock_name="CLOSE_TIME",
    )
    outcome_alias_present = bool(_present_alias_values(row, _OUTCOME_AVAILABLE_FIELDS))
    available_at, available_at_reasons = _aliased_aware_utc(
        row,
        _OUTCOME_AVAILABLE_FIELDS,
        clock_name="OUTCOME_AVAILABLE_AT",
        required=False,
    )
    reasons.extend(close_time_reasons)
    reasons.extend(available_at_reasons)
    outcome_availability_source = "ROW_EXPLICIT_OUTCOME_AVAILABLE_AT"
    if not outcome_alias_present:
        # The exact source snapshot was fully read before ``outcomes_cutoff``.
        # A legacy close without a dedicated outcome-availability clock can be
        # admitted conservatively as becoming available at that captured
        # cutoff.  We never reuse the generic row ``available_at`` because on
        # legacy closes it is the entry-feature clock and predates the exit.
        available_at = outcomes_cutoff
        outcome_availability_source = "CONSERVATIVE_SOURCE_SNAPSHOT_OBSERVED_AT_TUNING_CUTOFF"
    if close_time is not None and close_time > outcomes_cutoff:
        reasons.append("CLOSE_TIME_AFTER_OUTCOMES_CUTOFF")
    if entry_execution_time is not None and close_time is not None:
        if entry_execution_time > close_time:
            reasons.append("ENTRY_EXECUTION_TIME_AFTER_CLOSE_TIME")
    if available_at is not None and available_at > outcomes_cutoff:
        reasons.append("OUTCOME_AVAILABLE_AT_AFTER_OUTCOMES_CUTOFF")
    if close_time is not None and available_at is not None and available_at < close_time:
        reasons.append("OUTCOME_AVAILABLE_AT_BEFORE_CLOSE_TIME")

    if reasons:
        return sorted(set(reasons)), None
    assert close_id is not None
    assert position_id is not None
    assert prediction_id is not None
    assert pnl is not None
    assert confidence is not None
    assert close_quantity is not None and close_quantity > 0.0
    assert entry_price is not None and entry_price > 0.0
    assert entry_notional_usd is not None and entry_notional_usd > 0.0
    assert realized_pnl_bps is not None
    assert close_time is not None
    assert available_at is not None
    assert feature_cutoff is not None
    assert feature_available_at is not None
    assert decision_time is not None
    assert entry_execution_time is not None
    assert canonical_source_hashes is not None
    row_material = {
        "close_id": close_id,
        "position_id": position_id,
        "prediction_id": prediction_id,
        "paper_session_id": current_paper_session_id,
        "feature_cutoff": _utc_iso(feature_cutoff),
        "feature_available_at": _utc_iso(feature_available_at),
        "decision_time": _utc_iso(decision_time),
        "entry_execution_time": _utc_iso(entry_execution_time),
        "close_time": _utc_iso(close_time),
        "outcome_available_at": _utc_iso(available_at),
        "outcome_availability_source": outcome_availability_source,
        "realized_pnl_usd": pnl,
        "entry_notional_usd": entry_notional_usd,
        "realized_pnl_bps": realized_pnl_bps,
        "confidence_calibrated": confidence,
        "grade": grade,
        "source_hashes": canonical_source_hashes,
        "valid_source_hash_count": len(canonical_source_hashes),
        "source_hashes_hash_sha256": _sha256_canonical(canonical_source_hashes),
    }
    row_material["row_material_hash_sha256"] = _sha256_canonical(row_material)
    return [], row_material


def _mean_uncertainty(values: list[float]) -> dict[str, Any]:
    """Return deterministic empirical mean/uncertainty facts.

    Two observations are the immutable mathematical minimum for a sample
    variance.  The one-standard-error bound is a statistical estimator, not a
    market/performance cutoff.
    """

    count = len(values)
    if not values or any(not math.isfinite(value) for value in values):
        return {
            "count": count,
            "mean": None,
            "standard_error": None,
            "lower_bound": None,
            "upper_bound": None,
        }
    scale = max(abs(value) for value in values)
    if scale == 0.0:
        mean = 0.0
        standard_error = 0.0 if count >= 2 else None
    else:
        normalized = [value / scale for value in values]
        normalized_mean = math.fsum(normalized) / count
        mean = normalized_mean * scale
        if count < 2:
            standard_error = None
        else:
            normalized_variance = math.fsum(
                (value - normalized_mean) ** 2 for value in normalized
            ) / (count - 1)
            standard_error = math.sqrt(normalized_variance / count) * scale
    if count < 2:
        return {
            "count": count,
            "mean": mean,
            "standard_error": None,
            "lower_bound": None,
            "upper_bound": None,
        }
    assert standard_error is not None
    lower_bound = mean - standard_error
    upper_bound = mean + standard_error
    if not all(math.isfinite(value) for value in (mean, standard_error, lower_bound, upper_bound)):
        return {
            "count": count,
            "mean": None,
            "standard_error": None,
            "lower_bound": None,
            "upper_bound": None,
        }
    return {
        "count": count,
        "mean": mean,
        "standard_error": standard_error,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
    }


def _finite_fsum(values: list[float]) -> float | None:
    try:
        total = math.fsum(values)
    except (OverflowError, ValueError):
        return None
    return total if math.isfinite(total) else None


def _bernoulli_wilson_one_standard_error(values: list[float]) -> dict[str, Any]:
    """Return a bounded Bernoulli interval that remains uncertain at 0%/100%."""

    count = len(values)
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "lower_bound": None,
            "upper_bound": None,
        }
    mean = sum(values) / count
    denominator = 1.0 + (1.0 / count)
    center = (mean + (1.0 / (2.0 * count))) / denominator
    margin = math.sqrt((mean * (1.0 - mean) / count) + (1.0 / (4.0 * count * count))) / denominator
    return {
        "count": count,
        "mean": mean,
        "lower_bound": max(0.0, center - margin),
        "upper_bound": min(1.0, center + margin),
    }


def _empirical_rank_bins(
    confidence_outcomes: list[tuple[float, float]],
) -> dict[str, dict[str, Any]]:
    """Describe equal-rank empirical cohorts without fixed confidence cutoffs."""

    ordered = sorted(enumerate(confidence_outcomes), key=lambda item: (item[1][0], item[0]))
    count = len(ordered)
    first_boundary = count // 3
    second_boundary = (count * 2) // 3
    slices = {
        "low": ordered[:first_boundary],
        "medium": ordered[first_boundary:second_boundary],
        "high": ordered[second_boundary:],
    }
    result: dict[str, dict[str, Any]] = {}
    for name, cohort in slices.items():
        confidences = [item[1][0] for item in cohort]
        wins = [item[1][1] for item in cohort]
        result[name] = {
            "count": len(cohort),
            "win_rate": sum(wins) / len(wins) if wins else 0.0,
            "confidence_min": min(confidences) if confidences else None,
            "confidence_max": max(confidences) if confidences else None,
            "cohort_method": "SORTED_EMPIRICAL_EQUAL_RANK_TERTILE",
        }
    return result


def _analyze_outcome_payload(
    payload: Any,
    *,
    outcomes_cutoff: datetime,
    current_paper_session_id: str | None,
    source_errors: list[str] | None = None,
) -> dict[str, Any]:
    rows, extraction_error = _extract_outcome_rows(payload)
    source_row_count = len(rows)
    source_reason_counts: Counter[str] = Counter(source_errors or [])
    if extraction_error:
        source_reason_counts[extraction_error] += 1
    if source_row_count > MAX_OUTCOME_SOURCE_ROWS:
        source_reason_counts["SOURCE_ROW_LIMIT_EXCEEDED"] += 1
        rows = []

    admitted: list[dict[str, Any]] = []
    rejection_reason_counts: Counter[str] = Counter()
    seen_close_ids: set[str] = set()
    for row in rows:
        reasons, normalized = _outcome_row_rejection_reasons(
            row,
            outcomes_cutoff=outcomes_cutoff,
            current_paper_session_id=current_paper_session_id,
        )
        if reasons:
            rejection_reason_counts.update(reasons)
        elif normalized is not None:
            close_id = str(normalized["close_id"])
            if close_id in seen_close_ids:
                rejection_reason_counts["DUPLICATE_CLOSE_ID"] += 1
            else:
                seen_close_ids.add(close_id)
                admitted.append(normalized)

    admitted.sort(
        key=lambda row: (
            row["outcome_available_at"],
            row["close_time"],
            row["close_id"],
        )
    )
    recent = admitted[-RECENT_OUTCOME_LIMIT:]
    confidence_outcomes = [
        (row["confidence_calibrated"], 1.0 if row["realized_pnl_usd"] > 0.0 else 0.0)
        for row in recent
    ]
    empirical_bins = _empirical_rank_bins(confidence_outcomes)
    admitted_count = len(admitted)
    total_pnl = _finite_fsum([float(row["realized_pnl_usd"]) for row in admitted])
    if admitted and total_pnl is None:
        source_reason_counts["OUTCOME_AGGREGATE_NONFINITE"] += 1
    recent_pnl_bps = [float(row["realized_pnl_bps"]) for row in recent]
    edge_statistics = _mean_uncertainty(recent_pnl_bps)
    realized_edge_mean_bps = edge_statistics["mean"]
    realized_edge_standard_error_bps = edge_statistics["standard_error"]
    realized_edge_lcb_bps = edge_statistics["lower_bound"]
    confidence_distribution = sorted(confidence for confidence, _win in confidence_outcomes)
    realized_wins = [win for _confidence, win in confidence_outcomes]
    win_statistics = _mean_uncertainty(realized_wins)
    win_interval = _bernoulli_wilson_one_standard_error(realized_wins)
    overall_win_rate = win_interval["mean"]
    win_rate_lower_bound = win_interval["lower_bound"]
    confidence_mean = (
        sum(confidence_distribution) / len(confidence_distribution)
        if confidence_distribution
        else None
    )
    grade_evidence: dict[str, dict[str, Any]] = {}
    for grade in ("B", "A", "PROBATION"):
        grade_edges = [float(row["realized_pnl_bps"]) for row in recent if row["grade"] == grade]
        grade_stats = _mean_uncertainty(grade_edges)
        grade_evidence[grade] = {
            **grade_stats,
            "evidence_sufficient": len(grade_edges) >= MIN_CLEAN_OUTCOMES_FOR_ADAPTATION,
            "minimum_clean_outcomes_required": MIN_CLEAN_OUTCOMES_FOR_ADAPTATION,
            "positive_edge": bool(
                len(grade_edges) >= MIN_CLEAN_OUTCOMES_FOR_ADAPTATION
                and grade_stats["lower_bound"] is not None
                and float(grade_stats["lower_bound"]) > 0.0
            ),
        }
    recent_notional = _finite_fsum([float(row["entry_notional_usd"]) for row in recent])
    recent_pnl_usd = _finite_fsum([float(row["realized_pnl_usd"]) for row in recent])
    if recent and (recent_notional is None or recent_pnl_usd is None):
        source_reason_counts["RECENT_OUTCOME_AGGREGATE_NONFINITE"] += 1
    notional_weighted_edge_bps = (
        (recent_pnl_usd / recent_notional) * 10_000.0
        if recent_notional is not None and recent_pnl_usd is not None and recent_notional > 0.0
        else None
    )
    if notional_weighted_edge_bps is not None and not math.isfinite(notional_weighted_edge_bps):
        source_reason_counts["NOTIONAL_WEIGHTED_EDGE_NONFINITE"] += 1
        notional_weighted_edge_bps = None
    evidence_sufficient = bool(
        admitted_count >= MIN_CLEAN_OUTCOMES_FOR_ADAPTATION
        and not source_reason_counts
        and edge_statistics["lower_bound"] is not None
        and recent_notional is not None
        and recent_pnl_usd is not None
    )
    if source_reason_counts:
        status = "UNTRUSTED_OR_UNBOUNDED_SOURCE"
    elif not admitted:
        status = "NO_CLEAN_OUTCOMES"
    elif not evidence_sufficient:
        status = "INSUFFICIENT_CLEAN_EVIDENCE"
    else:
        status = "OK"
    admitted_hash = _sha256_canonical([row["row_material_hash_sha256"] for row in admitted])
    return {
        "status": status,
        "evidence_sufficient": evidence_sufficient,
        "minimum_clean_outcomes_required": MIN_CLEAN_OUTCOMES_FOR_ADAPTATION,
        "clean_outcome_shortfall": max(0, MIN_CLEAN_OUTCOMES_FOR_ADAPTATION - admitted_count),
        "source_row_count": source_row_count,
        "admitted_row_count": admitted_count,
        "rejected_row_count": source_row_count - admitted_count,
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "source_rejection_reason_counts": dict(sorted(source_reason_counts.items())),
        "admitted_rows_material_hash_sha256": admitted_hash,
        "sample_size": admitted_count,
        "recent_sample": len(confidence_outcomes),
        "confidence_bins": empirical_bins,
        "confidence_bin_method": "SORTED_EMPIRICAL_EQUAL_RANK_TERTILES_NO_FIXED_CUTOFFS",
        "confidence_distribution": confidence_distribution,
        "confidence_mean": confidence_mean,
        "overall_win_rate": overall_win_rate,
        "win_rate_lower_bound": win_rate_lower_bound,
        "loss_rate": (1.0 - overall_win_rate if overall_win_rate is not None else None),
        "loss_rate_standard_error": win_statistics["standard_error"],
        "loss_rate_upper_bound": (
            min(1.0, 1.0 - float(win_rate_lower_bound))
            if win_rate_lower_bound is not None
            else None
        ),
        "win_loss_uncertainty_method": "BERNOULLI_WILSON_ONE_STANDARD_ERROR",
        "grade_evidence": grade_evidence,
        "a_grade_count": sum(1 for row in admitted if row["grade"] == "A"),
        "b_grade_count": sum(1 for row in admitted if row["grade"] == "B"),
        "probation_count": sum(1 for row in admitted if row["grade"] == "PROBATION"),
        "total_pnl_usd": total_pnl,
        "average_pnl_per_trade": (
            total_pnl / admitted_count if admitted_count and total_pnl is not None else None
        ),
        "realized_edge_mean_bps": realized_edge_mean_bps,
        "realized_edge_standard_error_bps": realized_edge_standard_error_bps,
        "realized_edge_lcb_bps": realized_edge_lcb_bps,
        "realized_edge_uncertainty_method": "RECENT_MEAN_MINUS_ONE_STANDARD_ERROR",
        "notional_weighted_edge_bps": notional_weighted_edge_bps,
        "recent_entry_notional_usd": recent_notional,
        "legacy_outcome_availability_at_cutoff_count": sum(
            row["outcome_availability_source"]
            == "CONSERVATIVE_SOURCE_SNAPSHOT_OBSERVED_AT_TUNING_CUTOFF"
            for row in admitted
        ),
    }


def analyze_paper_outcomes(redis_client: RedisReader) -> dict[str, Any]:
    """Analyze canonical closed outcomes at a captured point-in-time cutoff."""
    closed_raw = redis_client.get(OUTCOMES_KEY)
    session_raw = redis_client.get(PAPER_SESSION_KEY)
    cutoff = _utc_now()
    closed_payload, closed_error = _decode_json(closed_raw)
    session_payload, session_error = _decode_json(session_raw)
    session_id, session_errors = _session_identity(session_payload)
    return _analyze_outcome_payload(
        closed_payload,
        outcomes_cutoff=cutoff,
        current_paper_session_id=session_id,
        source_errors=[
            reason
            for reason in (closed_error, session_error, *session_errors)
            if reason is not None
        ],
    )


def _quantile(values: list[float], probability: float) -> float:
    """Return a linearly interpolated empirical quantile."""

    if not values:
        raise ValueError("quantile requires evidence")
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def _market_candle_row(
    row: Any,
    *,
    symbol: str,
    cutoff: datetime,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if not isinstance(row, Mapping):
        return None, ["ROW_NOT_OBJECT"]
    if row.get("symbol") != symbol:
        reasons.append("SYMBOL_MISMATCH")
    if row.get("timeframe") != MARKET_CANDLE_TIMEFRAME:
        reasons.append("TIMEFRAME_MISMATCH")
    for field in (
        "is_closed",
        "closed_candle",
        "candle_closed_confirmed",
        "feature_eligible",
    ):
        if row.get(field) is not True:
            reasons.append(f"{field.upper()}_NOT_TRUE")

    close_time, close_time_reasons = _aliased_source_clock(
        row,
        ("candle_close_time", "close_time"),
        clock_name="CLOSE_TIME",
    )
    reasons.extend(close_time_reasons)
    event_time = _parse_source_clock(row.get("event_time"))
    available_at = _parse_source_clock(row.get("available_at"))
    if event_time is None:
        reasons.append("EVENT_TIME_INVALID")
    if available_at is None:
        reasons.append("AVAILABLE_AT_INVALID")
    if close_time is not None and event_time is not None and available_at is not None:
        if not close_time <= event_time <= available_at:
            reasons.append("SOURCE_CLOCK_ORDER_INVALID")
        if close_time > cutoff:
            reasons.append("UNFINISHED_AT_TUNING_CUTOFF")
        if available_at > cutoff:
            reasons.append("AVAILABLE_AFTER_TUNING_CUTOFF")

    open_price = _finite(row.get("open"))
    high = _finite(row.get("high"))
    low = _finite(row.get("low"))
    close = _finite(row.get("close"))
    volume = _finite(row.get("volume"))
    valid_ohlc = all(value is not None and value > 0.0 for value in (open_price, high, low, close))
    if not valid_ohlc:
        reasons.append("OHLC_MISSING_NONFINITE_OR_NONPOSITIVE")
    else:
        assert open_price is not None
        assert high is not None
        assert low is not None
        assert close is not None
        if not low <= min(open_price, close) <= max(open_price, close) <= high:
            reasons.append("OHLC_ORDER_INVALID")
    if volume is None or volume < 0.0:
        reasons.append("VOLUME_MISSING_NONFINITE_OR_NEGATIVE")
    if reasons:
        return None, sorted(set(reasons))

    assert close_time is not None
    assert event_time is not None
    assert available_at is not None
    assert high is not None
    assert low is not None
    assert close is not None
    range_bps = ((high - low) / close) * 10_000.0
    if not math.isfinite(range_bps):
        return None, ["RANGE_BPS_NONFINITE"]
    normalized = {
        "symbol": symbol,
        "timeframe": MARKET_CANDLE_TIMEFRAME,
        "close_time": _utc_iso(close_time),
        "event_time": _utc_iso(event_time),
        "available_at": _utc_iso(available_at),
        "range_bps": range_bps,
    }
    normalized["row_material_hash_sha256"] = _sha256_canonical(normalized)
    return normalized, []


def _market_source_analysis(
    raw_payload: Any,
    *,
    source_key: str,
    symbol: str,
    cutoff: datetime,
) -> dict[str, Any]:
    payload, decode_error = _decode_json(raw_payload)
    source_reasons: Counter[str] = Counter()
    if decode_error is not None:
        source_reasons[decode_error] += 1
    rows = payload if isinstance(payload, list) else []
    if payload is not None and not isinstance(payload, list):
        source_reasons["SOURCE_PAYLOAD_ROOT_NOT_LIST"] += 1
    source_row_count = len(rows)
    if source_row_count > MAX_MARKET_CANDLE_ROWS_PER_SYMBOL:
        source_reasons["SOURCE_ROW_LIMIT_EXCEEDED"] += 1
        rows = []

    admitted: list[dict[str, Any]] = []
    row_reasons: Counter[str] = Counter()
    seen_close_times: set[str] = set()
    for row in rows:
        normalized, reasons = _market_candle_row(
            row,
            symbol=symbol,
            cutoff=cutoff,
        )
        if reasons:
            row_reasons.update(reasons)
            continue
        assert normalized is not None
        close_identity = normalized["close_time"]
        if close_identity in seen_close_times:
            row_reasons["DUPLICATE_CLOSE_TIME"] += 1
            continue
        seen_close_times.add(close_identity)
        admitted.append(normalized)
    admitted.sort(key=lambda item: (item["close_time"], item["available_at"]))

    stale = True
    latest_available_at: datetime | None = None
    if admitted:
        latest_available_at = _parse_canonical_microsecond_utc(admitted[-1]["available_at"])
        assert latest_available_at is not None
        maximum_age = timedelta(
            seconds=(MARKET_CANDLE_CADENCE_SECONDS * MARKET_CANDLE_MAX_STALENESS_CADENCES)
        )
        stale = cutoff - latest_available_at > maximum_age
        if stale:
            source_reasons["LATEST_FINAL_CANDLE_STALE"] += 1

    evidence_sufficient = (
        len(admitted) >= MIN_FINAL_CANDLES_PER_SYMBOL and not stale and not source_reasons
    )
    if len(admitted) < MIN_FINAL_CANDLES_PER_SYMBOL:
        source_reasons["INSUFFICIENT_FINAL_CANDLES"] += 1

    result: dict[str, Any] = {
        "source_key": source_key,
        "source_payload_hash_sha256": _raw_sha256(raw_payload),
        "symbol": symbol,
        "timeframe": MARKET_CANDLE_TIMEFRAME,
        "source_row_count": source_row_count,
        "admitted_row_count": len(admitted),
        "rejected_row_count": source_row_count - len(admitted),
        "minimum_final_candles_required": MIN_FINAL_CANDLES_PER_SYMBOL,
        "latest_available_at": (
            _utc_iso(latest_available_at) if latest_available_at is not None else None
        ),
        "stale_after_cadences": MARKET_CANDLE_MAX_STALENESS_CADENCES,
        "expected_cadence_seconds": MARKET_CANDLE_CADENCE_SECONDS,
        "evidence_sufficient": evidence_sufficient,
        "source_rejection_reason_counts": dict(sorted(source_reasons.items())),
        "row_rejection_reason_counts": dict(sorted(row_reasons.items())),
        "admitted_rows_material_hash_sha256": _sha256_canonical(
            [item["row_material_hash_sha256"] for item in admitted]
        ),
    }
    if admitted:
        ranges = [item["range_bps"] for item in admitted]
        current_window_count = max(1, math.isqrt(len(ranges)))
        current_bps = _quantile(ranges[-current_window_count:], 0.5)
        q25 = _quantile(ranges, 0.25)
        q50 = _quantile(ranges, 0.50)
        q75 = _quantile(ranges, 0.75)
        below = sum(value < current_bps for value in ranges)
        equal = sum(value == current_bps for value in ranges)
        result.update(
            {
                "current_window_count": current_window_count,
                "current_volatility_bps": current_bps,
                "empirical_q25_bps": q25,
                "empirical_median_bps": q50,
                "empirical_q75_bps": q75,
                "current_empirical_percentile": (below + (0.5 * equal)) / len(ranges),
            }
        )
    return result


def learn_market_regime(
    redis_client: RedisReader,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Learn volatility from finalized, PIT-safe canonical candle histories."""

    cutoff = observed_at or _utc_now()
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        return {
            "status": "ERROR",
            "regime": "UNTRUSTED",
            "volatility_factor": MAX_VOLATILITY_FACTOR,
            "reasons": ["TUNING_CUTOFF_NOT_AWARE"],
        }
    cutoff = cutoff.astimezone(UTC)
    analyses: list[dict[str, Any]] = []
    for symbol, key in zip(MARKET_CANDLE_SYMBOLS, MARKET_CANDLE_KEYS, strict=True):
        try:
            raw_payload = redis_client.get(key)
        except Exception:
            raw_payload = None
        analyses.append(
            _market_source_analysis(
                raw_payload,
                source_key=key,
                symbol=symbol,
                cutoff=cutoff,
            )
        )

    evidence_sufficient = all(analysis.get("evidence_sufficient") is True for analysis in analyses)
    if not evidence_sufficient:
        return {
            "status": "INSUFFICIENT_OR_UNTRUSTED_DATA",
            "regime": "UNTRUSTED",
            "volatility_factor": MAX_VOLATILITY_FACTOR,
            "symbols_analyzed": sum(
                analysis.get("evidence_sufficient") is True for analysis in analyses
            ),
            "symbols_required": len(MARKET_CANDLE_SYMBOLS),
            "observed_at": _utc_iso(cutoff),
            "source_analyses": analyses,
        }

    current_values = [float(analysis["current_volatility_bps"]) for analysis in analyses]
    q25_values = [float(analysis["empirical_q25_bps"]) for analysis in analyses]
    median_values = [float(analysis["empirical_median_bps"]) for analysis in analyses]
    q75_values = [float(analysis["empirical_q75_bps"]) for analysis in analyses]
    percentiles = [float(analysis["current_empirical_percentile"]) for analysis in analyses]
    current_bps = _quantile(current_values, 0.5)
    empirical_q25_bps = _quantile(q25_values, 0.5)
    empirical_median_bps = _quantile(median_values, 0.5)
    empirical_q75_bps = _quantile(q75_values, 0.5)
    empirical_percentile = sum(percentiles) / len(percentiles)
    volatility_factor = MIN_VOLATILITY_FACTOR + (
        (MAX_VOLATILITY_FACTOR - MIN_VOLATILITY_FACTOR) * empirical_percentile
    )
    regime = (
        "HIGH"
        if current_bps > empirical_q75_bps
        else ("LOW" if current_bps < empirical_q25_bps else "NORMAL")
    )
    return {
        "status": "OK",
        "regime": regime,
        "volatility_bps": current_bps,
        "empirical_q25_bps": empirical_q25_bps,
        "empirical_median_bps": empirical_median_bps,
        "empirical_q75_bps": empirical_q75_bps,
        "empirical_percentile": empirical_percentile,
        "volatility_factor": round(
            max(MIN_VOLATILITY_FACTOR, min(MAX_VOLATILITY_FACTOR, volatility_factor)),
            8,
        ),
        "factor_derivation": (
            "MIN_VOLATILITY_FACTOR_PLUS_EMPIRICAL_PERCENTILE_TIMES_" "AUDITED_FACTOR_RANGE"
        ),
        "symbols_analyzed": len(analyses),
        "symbols_required": len(MARKET_CANDLE_SYMBOLS),
        "observed_at": _utc_iso(cutoff),
        "source_analyses": analyses,
    }


def _probability(value: Any) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and 0.0 <= parsed <= 1.0 else None


def _is_nonnegative_finite(value: Any) -> bool:
    parsed = _finite(value)
    return parsed is not None and parsed >= 0.0


def compute_adaptive_confidence_threshold(
    outcomes: Mapping[str, Any],
    regime: Mapping[str, Any],
) -> float:
    """Derive a continuous confidence floor from PIT empirical ranks.

    Current market volatility selects a rank in the observed confidence
    distribution.  Empirical overconfidence tightens that rank continuously;
    no fixed win-rate, confidence, or regime boundary participates.
    """

    if (
        outcomes.get("status") != "OK"
        or outcomes.get("evidence_sufficient") is not True
        or regime.get("status") != "OK"
    ):
        return FAIL_CLOSED_CONFIDENCE_FLOOR
    raw_distribution = outcomes.get("confidence_distribution")
    if not isinstance(raw_distribution, list):
        return FAIL_CLOSED_CONFIDENCE_FLOOR
    distribution = [
        parsed for value in raw_distribution if (parsed := _probability(value)) is not None
    ]
    if len(distribution) != len(raw_distribution) or not distribution:
        return FAIL_CLOSED_CONFIDENCE_FLOOR
    market_rank = _probability(regime.get("empirical_percentile"))
    mean_confidence = _probability(outcomes.get("confidence_mean"))
    realized_win_rate = _probability(outcomes.get("overall_win_rate"))
    if market_rank is None or mean_confidence is None or realized_win_rate is None:
        return FAIL_CLOSED_CONFIDENCE_FLOOR
    empirical_rank_floor = _quantile(distribution, market_rank)
    overconfidence = max(0.0, mean_confidence - realized_win_rate)
    tightened = empirical_rank_floor + (overconfidence * (1.0 - empirical_rank_floor))
    return round(max(0.0, min(1.0, tightened)), 8)


def _grade_positive_edge(outcomes: Mapping[str, Any], grade: str) -> bool:
    grade_evidence = outcomes.get("grade_evidence")
    if not isinstance(grade_evidence, Mapping):
        return False
    grade_payload = grade_evidence.get(grade)
    return bool(
        isinstance(grade_payload, Mapping)
        and grade_payload.get("evidence_sufficient") is True
        and grade_payload.get("positive_edge") is True
        and (_finite(grade_payload.get("lower_bound")) or 0.0) > 0.0
    )


def should_enable_b_grade(outcomes: Mapping[str, Any]) -> bool:
    """Enable B only from a sufficient B-grade empirical edge lower bound."""

    return bool(
        outcomes.get("status") == "OK"
        and outcomes.get("evidence_sufficient") is True
        and _grade_positive_edge(outcomes, "B")
    )


def should_enable_a_grade(outcomes: Mapping[str, Any]) -> bool:
    """Enable A only from a sufficient A-grade empirical edge lower bound."""

    return bool(
        outcomes.get("status") == "OK"
        and outcomes.get("evidence_sufficient") is True
        and _grade_positive_edge(outcomes, "A")
    )


def _receipt_hash(payload: Mapping[str, Any]) -> str:
    receipt_material = {
        "receipt_schema_version": GATE_TUNING_RECEIPT_SCHEMA_VERSION,
        "producer": CANONICAL_PRODUCER,
        "canonical_key": GATE_TUNING_KEY,
        "payload": dict(payload),
    }
    return _sha256_canonical(receipt_material)


def _outcomes_evidence_projection(outcomes: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact outcome facts that participate in policy identity."""

    return {
        "status": outcomes.get("status"),
        "evidence_sufficient": outcomes.get("evidence_sufficient") is True,
        "minimum_clean_outcomes_required": outcomes.get("minimum_clean_outcomes_required"),
        "source_row_count": outcomes.get("source_row_count"),
        "admitted_row_count": outcomes.get("admitted_row_count"),
        "rejected_row_count": outcomes.get("rejected_row_count"),
        "rejection_reason_counts": outcomes.get("rejection_reason_counts"),
        "source_rejection_reason_counts": outcomes.get("source_rejection_reason_counts"),
        "admitted_rows_material_hash_sha256": outcomes.get("admitted_rows_material_hash_sha256"),
        "realized_edge_mean_bps": outcomes.get("realized_edge_mean_bps"),
        "realized_edge_standard_error_bps": outcomes.get("realized_edge_standard_error_bps"),
        "realized_edge_lcb_bps": outcomes.get("realized_edge_lcb_bps"),
        "notional_weighted_edge_bps": outcomes.get("notional_weighted_edge_bps"),
        "confidence_distribution": outcomes.get("confidence_distribution"),
        "confidence_mean": outcomes.get("confidence_mean"),
        "overall_win_rate": outcomes.get("overall_win_rate"),
        "win_rate_lower_bound": outcomes.get("win_rate_lower_bound"),
        "loss_rate_upper_bound": outcomes.get("loss_rate_upper_bound"),
        "grade_evidence": outcomes.get("grade_evidence"),
        "legacy_outcome_availability_at_cutoff_count": outcomes.get(
            "legacy_outcome_availability_at_cutoff_count"
        ),
    }


def _derive_bound_source_evidence(
    source_values: Mapping[str, Any],
    *,
    outcomes_cutoff: datetime,
    source_read_errors: list[str],
) -> tuple[dict[str, Any], dict[str, Any], str | None, list[str]]:
    """Re-derive all policy evidence solely from one immutable byte snapshot."""

    closed_payload, closed_decode_error = _decode_json(source_values.get(OUTCOMES_KEY))
    session_payload, session_decode_error = _decode_json(source_values.get(PAPER_SESSION_KEY))
    paper_session_id, session_identity_errors = _session_identity(session_payload)
    outcome_source_errors = [
        reason for reason in (closed_decode_error, session_decode_error) if reason is not None
    ]
    outcome_source_errors.extend(session_identity_errors)
    outcome_source_errors.extend(source_read_errors)
    outcomes = _analyze_outcome_payload(
        closed_payload,
        outcomes_cutoff=outcomes_cutoff,
        current_paper_session_id=paper_session_id,
        source_errors=outcome_source_errors,
    )
    regime = learn_market_regime(
        _SnapshotRedis(source_values),
        observed_at=outcomes_cutoff,
    )
    return outcomes, regime, paper_session_id, session_identity_errors


def adaptive_gate_tuning_rejection_reasons(
    tuning_state: Mapping[str, Any] | None,
    *,
    observed_at: Any | None = None,
    current_paper_session_id: str | None = None,
    require_current_session: bool = False,
) -> list[str]:
    """Validate one canonical adaptive-tuning publication without I/O.

    ``observed_at`` and ``current_paper_session_id`` are consumer facts.  A
    publisher can validate the sealed envelope without them; an admission
    consumer must provide both and set ``require_current_session`` so an
    otherwise byte-valid publication cannot cross a paper-session boundary or
    remain executable after expiry.
    """

    payload = dict(tuning_state) if isinstance(tuning_state, Mapping) else {}
    if isinstance(tuning_state, Mapping):
        structure_reasons = _canonical_gate_tuning_structure_rejection_reasons(payload)
        if structure_reasons:
            return structure_reasons
    reasons: list[str] = []

    def reject(reason: str) -> None:
        reasons.append(reason)

    receipt = payload.get("publication_receipt")
    if not _canonical_json_type_exact_equal(
        payload.get("schema_version"), GATE_TUNING_SCHEMA_VERSION
    ):
        reject("CANONICAL_ENVELOPE_SCHEMA_INVALID")
    if not _canonical_json_type_exact_equal(
        payload.get("policy_version"), GATE_TUNING_POLICY_VERSION
    ):
        reject("CANONICAL_ENVELOPE_POLICY_VERSION_INVALID")
    if not _canonical_json_type_exact_equal(payload.get("producer"), CANONICAL_PRODUCER):
        reject("CANONICAL_ENVELOPE_PRODUCER_INVALID")
    if not _canonical_json_type_exact_equal(payload.get("canonical_key"), GATE_TUNING_KEY):
        reject("CANONICAL_ENVELOPE_KEY_INVALID")
    if payload.get("authoritative") is not True:
        reject("CANONICAL_ENVELOPE_NOT_AUTHORITATIVE")
    if not _canonical_json_type_exact_equal(
        payload.get("authority_scope"), "PAPER_ONLY_ADAPTIVE_GATE_TUNING"
    ):
        reject("CANONICAL_ENVELOPE_AUTHORITY_SCOPE_INVALID")
    if (
        payload.get("paper_only") is not True
        or payload.get("routes_to_live") is not False
        or payload.get("places_real_order") is not False
    ):
        reject("CANONICAL_ENVELOPE_PAPER_SAFETY_FLAGS_INVALID")
    if not isinstance(receipt, Mapping):
        reject("PUBLICATION_RECEIPT_MISSING")

    payload_session_id = payload.get("current_paper_session_id")
    if not _canonical_json_type_exact_equal(payload.get("paper_session_id"), payload_session_id):
        reject("PAPER_SESSION_ALIAS_MISMATCH")
    if not _canonical_json_type_exact_equal(
        payload.get("paper_session_source_key"), PAPER_SESSION_KEY
    ):
        reject("PAPER_SESSION_SOURCE_KEY_INVALID")
    if require_current_session:
        if not isinstance(current_paper_session_id, str) or not current_paper_session_id:
            reject("CURRENT_PAPER_SESSION_ID_MISSING")
        elif not _canonical_json_type_exact_equal(payload_session_id, current_paper_session_id):
            reject("PAPER_SESSION_ID_MISMATCH")

    cutoff = _parse_canonical_microsecond_utc(payload.get("outcomes_cutoff"))
    generated_at = _parse_canonical_microsecond_utc(payload.get("generated_at"))
    available_at = _parse_canonical_microsecond_utc(payload.get("available_at"))
    expires_at = _parse_canonical_microsecond_utc(payload.get("expires_at"))
    if (
        cutoff is None
        or generated_at is None
        or available_at is None
        or expires_at is None
        or not cutoff <= generated_at <= available_at < expires_at
    ):
        reject("PUBLICATION_CLOCKS_INVALID")
    elif expires_at - available_at != timedelta(seconds=GATE_TUNING_TTL_SECONDS):
        reject("PUBLICATION_TTL_WINDOW_INVALID")
    if not _canonical_json_type_exact_equal(payload.get("ttl_seconds"), GATE_TUNING_TTL_SECONDS):
        reject("PUBLICATION_TTL_SECONDS_INVALID")
    if not _canonical_json_type_exact_equal(
        payload.get("generated_utc"), payload.get("generated_at")
    ):
        reject("GENERATED_TIME_ALIAS_MISMATCH")
    if not _canonical_json_type_exact_equal(
        payload.get("source_observed_at"), payload.get("outcomes_cutoff")
    ):
        reject("SOURCE_OBSERVED_AT_CUTOFF_MISMATCH")
    if observed_at is not None:
        observed: datetime | None
        if (
            isinstance(observed_at, datetime)
            and observed_at.tzinfo is not None
            and observed_at.utcoffset() is not None
        ):
            observed = observed_at.astimezone(UTC)
        else:
            observed = _parse_aware_utc(observed_at)
        if observed is None:
            reject("CONSUMER_OBSERVED_AT_INVALID")
        elif (
            available_at is None or expires_at is None or not available_at <= observed < expires_at
        ):
            reject("PUBLICATION_NOT_AVAILABLE_OR_EXPIRED_AT_CONSUMER")

    source_snapshot = payload.get("canonical_source_snapshot")
    try:
        source_snapshot_hash = _sha256_canonical(source_snapshot)
    except (RecursionError, TypeError, ValueError):
        source_snapshot_hash = None
        reject("SOURCE_SNAPSHOT_NOT_CANONICAL_JSON")
    if not _canonical_json_type_exact_equal(
        payload.get("canonical_source_snapshot_hash_sha256"), source_snapshot_hash
    ):
        reject("SOURCE_SNAPSHOT_HASH_INVALID")
    bound_source_values, normalized_snapshot, snapshot_reasons = _decode_bound_source_snapshot(
        source_snapshot
    )
    reasons.extend(snapshot_reasons)

    raw_source_read_errors = payload.get("source_read_errors")
    if (
        not isinstance(raw_source_read_errors, list)
        or any(not isinstance(reason, str) or not reason for reason in raw_source_read_errors)
        or not _canonical_json_type_exact_equal(
            raw_source_read_errors, sorted(set(raw_source_read_errors))
        )
    ):
        reject("SOURCE_READ_ERRORS_INVALID")
        source_read_errors: list[str] = []
    else:
        source_read_errors = list(raw_source_read_errors)

    expected_manifest: list[dict[str, Any]] | None = None
    if normalized_snapshot is not None:
        expected_manifest = _source_manifest_from_snapshot(normalized_snapshot)
        snapshot_by_key = {str(row["source_key"]): row for row in normalized_snapshot}
        required_snapshot_errors = {
            f"{row['omission_reason']}:{row['source_key']}"
            for row in normalized_snapshot
            if row["present"] is True and row["payload_included"] is False
        }
        if not required_snapshot_errors.issubset(source_read_errors):
            reject("SOURCE_SNAPSHOT_OMISSION_ERROR_MISSING")
        for source_error in source_read_errors:
            if source_error in required_snapshot_errors:
                continue
            source_prefixes = (
                "SOURCE_READ_FAILED:",
                "SOURCE_VALUE_TYPE_INVALID:",
            )
            prefix = next(
                (candidate for candidate in source_prefixes if source_error.startswith(candidate)),
                None,
            )
            if prefix is None:
                reject("SOURCE_READ_ERROR_UNRECOGNIZED")
                continue
            source_key = source_error.removeprefix(prefix)
            source_row = snapshot_by_key.get(source_key)
            if source_row is None or source_row.get("present") is not False:
                reject("SOURCE_READ_ERROR_BINDING_INVALID")

    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, list):
        reject("SOURCE_MANIFEST_INVALID")
        source_manifest = []
    else:
        manifest_keys = [
            row.get("source_key") if isinstance(row, Mapping) else None for row in source_manifest
        ]
        if not _canonical_json_type_exact_equal(manifest_keys, list(CANONICAL_SOURCE_KEYS)):
            reject("SOURCE_MANIFEST_KEYS_INVALID")
        for row in source_manifest:
            if (
                not isinstance(row, Mapping)
                or not isinstance(row.get("present"), bool)
                or not _is_sha256(row.get("source_payload_hash_sha256"))
            ):
                reject("SOURCE_MANIFEST_ROW_INVALID")
                break
    if expected_manifest is not None and not _canonical_json_type_exact_equal(
        source_manifest, expected_manifest
    ):
        reject("SOURCE_MANIFEST_SNAPSHOT_MISMATCH")
    try:
        manifest_hash = _sha256_canonical(source_manifest)
    except (RecursionError, TypeError, ValueError):
        manifest_hash = None
        reject("SOURCE_MANIFEST_NOT_CANONICAL_JSON")
    if not _canonical_json_type_exact_equal(
        payload.get("source_manifest_hash_sha256"), manifest_hash
    ):
        reject("SOURCE_MANIFEST_HASH_INVALID")
    manifest_by_key = {
        str(row.get("source_key")): row for row in source_manifest if isinstance(row, Mapping)
    }
    outcomes_manifest = manifest_by_key.get(OUTCOMES_KEY, {})
    session_manifest = manifest_by_key.get(PAPER_SESSION_KEY, {})
    if (
        not _canonical_json_type_exact_equal(payload.get("source_key"), OUTCOMES_KEY)
        or not _canonical_json_type_exact_equal(payload.get("outcomes_source_key"), OUTCOMES_KEY)
        or not _canonical_json_type_exact_equal(
            payload.get("source_hash"), payload.get("outcomes_source_hash_sha256")
        )
        or not _canonical_json_type_exact_equal(
            payload.get("outcomes_source_hash_sha256"),
            outcomes_manifest.get("source_payload_hash_sha256"),
        )
    ):
        reject("OUTCOMES_SOURCE_BINDING_INVALID")
    if not _canonical_json_type_exact_equal(
        payload.get("paper_session_source_hash_sha256"),
        session_manifest.get("source_payload_hash_sha256"),
    ):
        reject("PAPER_SESSION_SOURCE_HASH_INVALID")

    recomputed_outcomes: dict[str, Any] | None = None
    recomputed_regime: dict[str, Any] | None = None
    recomputed_session_id: str | None = None
    recomputed_session_errors: list[str] | None = None
    if bound_source_values is not None and cutoff is not None:
        try:
            (
                recomputed_outcomes,
                recomputed_regime,
                recomputed_session_id,
                recomputed_session_errors,
            ) = _derive_bound_source_evidence(
                bound_source_values,
                outcomes_cutoff=cutoff,
                source_read_errors=source_read_errors,
            )
        except (ArithmeticError, RecursionError, TypeError, ValueError):
            reject("BOUND_SOURCE_DERIVATION_FAILED")
        else:
            if not _canonical_json_type_exact_equal(payload.get("outcomes"), recomputed_outcomes):
                reject("OUTCOMES_SOURCE_DERIVATION_MISMATCH")
            if not _canonical_json_type_exact_equal(
                payload.get("market_regime"), recomputed_regime
            ):
                reject("MARKET_REGIME_SOURCE_DERIVATION_MISMATCH")
            if not _canonical_json_type_exact_equal(
                payload_session_id, recomputed_session_id
            ) or not _canonical_json_type_exact_equal(
                payload.get("paper_session_id"), recomputed_session_id
            ):
                reject("PAPER_SESSION_SOURCE_DERIVATION_MISMATCH")
            if not _canonical_json_type_exact_equal(
                payload.get("session_identity_errors"), recomputed_session_errors
            ):
                reject("SESSION_IDENTITY_SOURCE_DERIVATION_MISMATCH")
            if require_current_session and recomputed_session_errors:
                reject("CURRENT_PAPER_SESSION_SOURCE_UNSAFE")

    policy_material = payload.get("canonical_policy_material")
    if not isinstance(policy_material, Mapping):
        reject("POLICY_MATERIAL_INVALID")
        policy_material = {}
    try:
        policy_material_hash = _sha256_canonical(dict(policy_material))
    except (RecursionError, TypeError, ValueError):
        policy_material_hash = None
        reject("POLICY_MATERIAL_NOT_CANONICAL_JSON")
    if (
        not _canonical_json_type_exact_equal(
            payload.get("canonical_policy_material_hash_sha256"), policy_material_hash
        )
        or not _canonical_json_type_exact_equal(
            payload.get("policy_id"),
            (
                f"adaptive_gate_policy_{policy_material_hash[:24]}"
                if isinstance(policy_material_hash, str)
                else None
            ),
        )
        or not _canonical_json_type_exact_equal(
            policy_material.get("policy_version"), GATE_TUNING_POLICY_VERSION
        )
        or not _canonical_json_type_exact_equal(policy_material.get("producer"), CANONICAL_PRODUCER)
        or not _canonical_json_type_exact_equal(
            policy_material.get("outcomes_cutoff"), payload.get("outcomes_cutoff")
        )
        or not _canonical_json_type_exact_equal(
            policy_material.get("current_paper_session_id"), payload_session_id
        )
        or not _canonical_json_type_exact_equal(
            policy_material.get("source_manifest_hash_sha256"), manifest_hash
        )
        or not _canonical_json_type_exact_equal(
            policy_material.get("canonical_source_snapshot_hash_sha256"), source_snapshot_hash
        )
        or not _canonical_json_type_exact_equal(
            policy_material.get("market_regime"), payload.get("market_regime")
        )
    ):
        reject("POLICY_MATERIAL_BINDING_INVALID")
    if not _canonical_json_type_exact_equal(
        policy_material.get("source_read_errors"), payload.get("source_read_errors")
    ):
        reject("POLICY_SOURCE_READ_ERRORS_BINDING_INVALID")
    if not _canonical_json_type_exact_equal(
        policy_material.get("session_identity_errors"), payload.get("session_identity_errors")
    ):
        reject("POLICY_SESSION_ERRORS_BINDING_INVALID")
    if (
        payload.get("static_market_or_performance_thresholds") is not False
        or policy_material.get("static_market_or_performance_thresholds") is not False
    ):
        reject("STATIC_MARKET_OR_PERFORMANCE_THRESHOLD_FLAG_INVALID")
    if not _canonical_json_type_exact_equal(
        payload.get("threshold_derivation"), THRESHOLD_DERIVATION_METHOD
    ) or not _canonical_json_type_exact_equal(
        policy_material.get("threshold_derivation"), payload.get("threshold_derivation")
    ):
        reject("THRESHOLD_DERIVATION_INVALID")
    if not _canonical_json_type_exact_equal(
        payload.get("immutable_bound_classification"), IMMUTABLE_BOUND_CLASSIFICATION
    ) or not _canonical_json_type_exact_equal(
        policy_material.get("immutable_bound_classification"),
        IMMUTABLE_BOUND_CLASSIFICATION,
    ):
        reject("IMMUTABLE_BOUND_CLASSIFICATION_INVALID")

    policy_values = policy_material.get("policy_values")
    if not isinstance(policy_values, Mapping):
        reject("POLICY_VALUES_INVALID")
        policy_values = {}
    for field in GATE_TUNING_POLICY_VALUE_FIELDS:
        if field not in payload or not _canonical_json_type_exact_equal(
            payload.get(field), policy_values.get(field)
        ):
            reject(f"POLICY_VALUE_BINDING_INVALID:{field}")

    bool_fields = (
        "enable_b_grade",
        "enable_a_grade",
        "a_grade_ready",
        "blockers_resolved",
    )
    for field in bool_fields:
        if not isinstance(payload.get(field), bool):
            reject(f"POLICY_VALUE_TYPE_INVALID:{field}")
    bounded_fields = (
        "adaptive_confidence_threshold",
        "adaptive_loss_probability_threshold",
        "adaptive_long_confidence_floor",
        "adaptive_short_confidence_floor",
        "adaptive_entry_freeze_allowance",
    )
    for field in bounded_fields:
        value = _finite(payload.get(field))
        if value is None or not 0.0 <= value <= 1.0:
            reject(f"POLICY_VALUE_RANGE_INVALID:{field}")
    factor_envelopes = {
        "volatility_factor": (MIN_VOLATILITY_FACTOR, MAX_VOLATILITY_FACTOR),
        "trainer_performance_factor": (MIN_PERFORMANCE_FACTOR, MAX_PERFORMANCE_FACTOR),
        "portfolio_performance_factor": (MIN_PERFORMANCE_FACTOR, MAX_PERFORMANCE_FACTOR),
        "adaptive_a_plus_strictness": (MIN_A_PLUS_STRICTNESS, MAX_A_PLUS_STRICTNESS),
    }
    for field, (lower, upper) in factor_envelopes.items():
        value = _finite(payload.get(field))
        if value is None or not lower <= value <= upper:
            reject(f"POLICY_VALUE_RANGE_INVALID:{field}")
    if _finite(payload.get("adaptive_expectancy_floor")) is None:
        reject("POLICY_VALUE_RANGE_INVALID:adaptive_expectancy_floor")
    if not _canonical_json_type_exact_equal(
        payload.get("enable_a_grade"), payload.get("a_grade_ready")
    ):
        reject("A_GRADE_READY_ALIAS_MISMATCH")
    if payload.get("blockers_resolved") is not False:
        reject("BLOCKERS_RESOLVED_MUST_REMAIN_FALSE")

    outcomes_payload = payload.get("outcomes")
    regime_payload = payload.get("market_regime")
    if isinstance(outcomes_payload, Mapping):
        if not _canonical_json_type_exact_equal(
            policy_material.get("outcomes_evidence"),
            _outcomes_evidence_projection(outcomes_payload),
        ):
            reject("POLICY_OUTCOMES_EVIDENCE_BINDING_INVALID")
        for field in (
            "source_row_count",
            "admitted_row_count",
            "rejected_row_count",
            "rejection_reason_counts",
            "source_rejection_reason_counts",
        ):
            if not _canonical_json_type_exact_equal(
                payload.get(field), outcomes_payload.get(field)
            ):
                reject(f"OUTCOME_SUMMARY_BINDING_INVALID:{field}")
    outcome_evidence_sufficient = bool(
        isinstance(outcomes_payload, Mapping)
        and outcomes_payload.get("evidence_sufficient") is True
    )
    market_evidence_sufficient = bool(
        isinstance(regime_payload, Mapping)
        and _canonical_json_type_exact_equal(regime_payload.get("status"), "OK")
    )
    evidence_sufficient = outcome_evidence_sufficient and market_evidence_sufficient
    realized_edge_lcb_bps = (
        _finite(outcomes_payload.get("realized_edge_lcb_bps"))
        if isinstance(outcomes_payload, Mapping)
        else None
    )
    economic_edge_positive = bool(
        evidence_sufficient and realized_edge_lcb_bps is not None and realized_edge_lcb_bps > 0.0
    )
    if payload.get("outcome_evidence_sufficient") is not outcome_evidence_sufficient:
        reject("OUTCOME_EVIDENCE_SUFFICIENCY_DERIVATION_INVALID")
    if payload.get("market_evidence_sufficient") is not market_evidence_sufficient:
        reject("MARKET_EVIDENCE_SUFFICIENCY_DERIVATION_INVALID")
    if payload.get("evidence_sufficient") is not evidence_sufficient:
        reject("COMBINED_EVIDENCE_SUFFICIENCY_DERIVATION_INVALID")
    if policy_material.get("market_evidence_sufficient") is not market_evidence_sufficient:
        reject("POLICY_MARKET_EVIDENCE_BINDING_INVALID")
    if payload.get("economic_edge_positive") is not economic_edge_positive:
        reject("ECONOMIC_EDGE_POSITIVE_DERIVATION_INVALID")
    if policy_material.get("economic_edge_positive") is not economic_edge_positive:
        reject("POLICY_ECONOMIC_EDGE_BINDING_INVALID")
    if isinstance(outcomes_payload, Mapping) and isinstance(regime_payload, Mapping):
        expected_policy_values = _derive_adaptive_policy_values(
            outcomes_payload,
            regime_payload,
        )
        for field, expected_value in expected_policy_values.items():
            if not _canonical_json_type_exact_equal(payload.get(field), expected_value):
                reject(f"POLICY_VALUE_DERIVATION_INVALID:{field}")
    else:
        reject("POLICY_VALUE_DERIVATION_EVIDENCE_INVALID")
    permissive_authority = bool(
        evidence_sufficient
        and economic_edge_positive
        and (
            payload.get("enable_b_grade") is True
            or payload.get("enable_a_grade") is True
            or (_finite(payload.get("adaptive_entry_freeze_allowance")) or 0.0) > 0.0
        )
    )
    if payload.get("permissive_authority") is not permissive_authority:
        reject("PERMISSIVE_AUTHORITY_DERIVATION_INVALID")
    expected_authority_status = (
        "CANONICAL_EVIDENCE_BACKED_ADAPTIVE"
        if economic_edge_positive
        else "CANONICAL_EVIDENCE_BACKED_RESTRICTIVE"
        if evidence_sufficient
        else "CANONICAL_FAIL_CLOSED"
    )
    expected_policy_status = (
        "EVIDENCE_BACKED_ADAPTIVE_POLICY"
        if economic_edge_positive
        else "EVIDENCE_BACKED_RESTRICTIVE_NONPOSITIVE_EDGE"
        if evidence_sufficient
        else "FAIL_CLOSED_INSUFFICIENT_OR_UNTRUSTED_EVIDENCE"
    )
    if not _canonical_json_type_exact_equal(
        payload.get("authority_status"), expected_authority_status
    ):
        reject("AUTHORITY_STATUS_INVALID")
    if not _canonical_json_type_exact_equal(payload.get("policy_status"), expected_policy_status):
        reject("POLICY_STATUS_INVALID")
    if not economic_edge_positive and (
        payload.get("enable_b_grade") is not False
        or payload.get("enable_a_grade") is not False
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_confidence_threshold"), FAIL_CLOSED_CONFIDENCE_FLOOR
        )
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_loss_probability_threshold"),
            FAIL_CLOSED_LOSS_PROBABILITY_CEILING,
        )
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_long_confidence_floor"), FAIL_CLOSED_CONFIDENCE_FLOOR
        )
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_short_confidence_floor"), FAIL_CLOSED_CONFIDENCE_FLOOR
        )
        or not _is_nonnegative_finite(payload.get("adaptive_expectancy_floor"))
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_entry_freeze_allowance"),
            FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE,
        )
        or not _canonical_json_type_exact_equal(
            payload.get("adaptive_a_plus_strictness"), MAX_A_PLUS_STRICTNESS
        )
    ):
        reject("NONPOSITIVE_OR_INSUFFICIENT_EVIDENCE_POLICY_NOT_RESTRICTIVE")

    if isinstance(receipt, Mapping):
        if (
            not _canonical_json_type_exact_equal(
                receipt.get("schema_version"), GATE_TUNING_RECEIPT_SCHEMA_VERSION
            )
            or not _canonical_json_type_exact_equal(receipt.get("producer"), CANONICAL_PRODUCER)
            or not _canonical_json_type_exact_equal(receipt.get("canonical_key"), GATE_TUNING_KEY)
            or any(
                not _canonical_json_type_exact_equal(receipt.get(field), payload.get(field))
                for field in (
                    "policy_id",
                    "canonical_policy_material_hash_sha256",
                    "canonical_source_snapshot_hash_sha256",
                    "outcomes_source_key",
                    "outcomes_source_hash_sha256",
                    "outcomes_cutoff",
                    "generated_at",
                    "available_at",
                    "expires_at",
                )
            )
        ):
            reject("PUBLICATION_RECEIPT_BINDING_INVALID")
        unsigned_payload = dict(payload)
        unsigned_payload.pop("publication_receipt", None)
        unsigned_payload.pop("receipt_hash_sha256", None)
        try:
            expected_receipt_hash = _receipt_hash(unsigned_payload)
        except (RecursionError, TypeError, ValueError):
            expected_receipt_hash = None
            reject("PUBLICATION_RECEIPT_PAYLOAD_NOT_CANONICAL_JSON")
        if not _canonical_json_type_exact_equal(
            payload.get("receipt_hash_sha256"), expected_receipt_hash
        ) or not _canonical_json_type_exact_equal(
            receipt.get("receipt_hash_sha256"), expected_receipt_hash
        ):
            reject("PUBLICATION_RECEIPT_HASH_INVALID")

    return sorted(set(reasons))


def publish_gate_tuning(
    redis_client: RedisStore,
    tuning_state: Mapping[str, Any],
) -> None:
    """Publish one already-sealed canonical state without mutating it."""
    payload = dict(tuning_state)
    rejection_reasons = adaptive_gate_tuning_rejection_reasons(payload)
    if rejection_reasons:
        raise ValueError("ADAPTIVE_GATE_TUNING_INVALID:" + "|".join(rejection_reasons))

    redis_client.set(
        GATE_TUNING_KEY,
        _canonical_json(payload),
        ex=GATE_TUNING_TTL_SECONDS,
    )


def _compute_volatility_factor(
    redis_client: RedisReader,
    *,
    regime: Mapping[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> float:
    """Return the continuous empirical volatility factor, failing closed."""

    learned = (
        dict(regime)
        if isinstance(regime, Mapping)
        else learn_market_regime(redis_client, observed_at=observed_at)
    )
    return _volatility_factor_from_regime(learned)


def _volatility_factor_from_regime(regime: Mapping[str, Any]) -> float:
    factor = _finite(regime.get("volatility_factor"))
    if regime.get("status") != "OK" or factor is None:
        return MAX_VOLATILITY_FACTOR
    return round(
        max(MIN_VOLATILITY_FACTOR, min(MAX_VOLATILITY_FACTOR, factor)),
        8,
    )


def _bounded_performance_factor(signal: float) -> float:
    midpoint = (MIN_PERFORMANCE_FACTOR + MAX_PERFORMANCE_FACTOR) / 2.0
    half_span = (MAX_PERFORMANCE_FACTOR - MIN_PERFORMANCE_FACTOR) / 2.0
    return round(
        max(
            MIN_PERFORMANCE_FACTOR,
            min(MAX_PERFORMANCE_FACTOR, midpoint + (half_span * math.tanh(signal))),
        ),
        8,
    )


def _compute_trainer_performance_factor(outcomes: Mapping[str, Any]) -> float:
    """Derive calibration performance only from admitted PIT outcomes.

    The raw trainer metrics key has no authenticated session/availability
    contract and therefore cannot control canonical admission.
    """

    if outcomes.get("evidence_sufficient") is not True:
        return MIN_PERFORMANCE_FACTOR
    win_rate = _probability(outcomes.get("overall_win_rate"))
    confidence_mean = _probability(outcomes.get("confidence_mean"))
    if win_rate is None or confidence_mean is None:
        return MIN_PERFORMANCE_FACTOR
    return _bounded_performance_factor(win_rate - confidence_mean)


def _compute_portfolio_performance_factor(outcomes: Mapping[str, Any]) -> float:
    """Map empirical edge signal-to-noise continuously into the risk envelope."""

    if outcomes.get("evidence_sufficient") is not True:
        return MIN_PERFORMANCE_FACTOR
    mean = _finite(outcomes.get("realized_edge_mean_bps"))
    lower_bound = _finite(outcomes.get("realized_edge_lcb_bps"))
    standard_error = _finite(outcomes.get("realized_edge_standard_error_bps"))
    if mean is None or lower_bound is None or standard_error is None:
        return MIN_PERFORMANCE_FACTOR
    scale = max(abs(mean), standard_error)
    signal = lower_bound / scale if scale > 0.0 else 0.0
    return _bounded_performance_factor(signal)


def _derive_adaptive_policy_values(
    outcomes: Mapping[str, Any],
    regime: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive every market/performance value from the same sealed evidence."""

    volatility_factor = _volatility_factor_from_regime(regime)
    trainer_performance_factor = _compute_trainer_performance_factor(outcomes)
    portfolio_performance_factor = _compute_portfolio_performance_factor(outcomes)
    adaptive_confidence_threshold = compute_adaptive_confidence_threshold(outcomes, regime)
    enable_b_grade = should_enable_b_grade(outcomes)
    enable_a_grade = should_enable_a_grade(outcomes)
    loss_probability_threshold = (
        _probability(outcomes.get("win_rate_lower_bound"))
        if outcomes.get("evidence_sufficient") is True
        else None
    )
    if loss_probability_threshold is None:
        loss_probability_threshold = FAIL_CLOSED_LOSS_PROBABILITY_CEILING

    realized_edge_mean_bps = _finite(outcomes.get("realized_edge_mean_bps"))
    realized_edge_lcb_bps = _finite(outcomes.get("realized_edge_lcb_bps"))
    realized_edge_standard_error_bps = _finite(outcomes.get("realized_edge_standard_error_bps"))
    economic_edge_positive = bool(
        outcomes.get("evidence_sufficient") is True
        and realized_edge_lcb_bps is not None
        and realized_edge_lcb_bps > 0.0
    )
    expectancy_floor = max(
        0.0,
        realized_edge_standard_error_bps or 0.0,
        -(realized_edge_lcb_bps or 0.0),
    )
    edge_scale = max(
        abs(realized_edge_mean_bps or 0.0),
        realized_edge_standard_error_bps or 0.0,
    )
    entry_freeze_allowance = (
        max(0.0, min(1.0, realized_edge_lcb_bps / edge_scale))
        if economic_edge_positive and realized_edge_lcb_bps is not None and edge_scale > 0.0
        else FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE
    )
    uncertainty_ratio = (
        min(1.0, (realized_edge_standard_error_bps or 0.0) / edge_scale)
        if edge_scale > 0.0
        else 1.0
    )
    a_plus_strictness = MIN_A_PLUS_STRICTNESS + (
        (MAX_A_PLUS_STRICTNESS - MIN_A_PLUS_STRICTNESS) * uncertainty_ratio
    )

    if (
        outcomes.get("evidence_sufficient") is not True
        or regime.get("status") != "OK"
        or not economic_edge_positive
    ):
        adaptive_confidence_threshold = FAIL_CLOSED_CONFIDENCE_FLOOR
        loss_probability_threshold = FAIL_CLOSED_LOSS_PROBABILITY_CEILING
        enable_b_grade = False
        enable_a_grade = False
        entry_freeze_allowance = FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE
        a_plus_strictness = MAX_A_PLUS_STRICTNESS

    return {
        "adaptive_confidence_threshold": adaptive_confidence_threshold,
        "adaptive_loss_probability_threshold": loss_probability_threshold,
        "enable_b_grade": enable_b_grade,
        "enable_a_grade": enable_a_grade,
        "volatility_factor": volatility_factor,
        "trainer_performance_factor": trainer_performance_factor,
        "portfolio_performance_factor": portfolio_performance_factor,
        "adaptive_long_confidence_floor": adaptive_confidence_threshold,
        "adaptive_short_confidence_floor": adaptive_confidence_threshold,
        "adaptive_expectancy_floor": max(0.0, expectancy_floor),
        "adaptive_entry_freeze_allowance": entry_freeze_allowance,
        "adaptive_a_plus_strictness": a_plus_strictness,
    }


class _SnapshotRedis:
    """Read-only Redis-shaped view over one captured input snapshot."""

    def __init__(self, values: Mapping[str, Any]):
        self._values = dict(values)

    def get(self, key: str) -> Any:
        return self._values.get(key)


def _capture_sources(
    redis_client: RedisReader,
) -> tuple[dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    errors: list[str] = []
    for key in CANONICAL_SOURCE_KEYS:
        try:
            raw_value = redis_client.get(key)
        except Exception:
            values[key] = None
            errors.append(f"SOURCE_READ_FAILED:{key}")
            continue
        frozen_value, freeze_error = _freeze_source_value(raw_value)
        values[key] = frozen_value
        if freeze_error is not None:
            errors.append(f"{freeze_error}:{key}")
    return values, errors


_SOURCE_SNAPSHOT_ROW_FIELDS = frozenset(
    {
        "schema_version",
        "source_key",
        "present",
        "payload_included",
        "payload_byte_count",
        "source_payload_hash_sha256",
        "payload_base64",
        "omission_reason",
    }
)


def _bounded_source_snapshot(
    values: Mapping[str, Any],
    source_read_errors: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Retain exact bounded source bytes so consumers can redo derivation."""

    snapshot: list[dict[str, Any]] = []
    effective_values: dict[str, Any] = {}
    errors = list(source_read_errors)
    included_byte_count = 0
    for key in CANONICAL_SOURCE_KEYS:
        value, freeze_error = _freeze_source_value(values.get(key))
        if freeze_error is not None:
            errors.append(f"{freeze_error}:{key}")
        if value is None:
            snapshot.append(
                {
                    "schema_version": CANONICAL_SOURCE_SNAPSHOT_SCHEMA_VERSION,
                    "source_key": key,
                    "present": False,
                    "payload_included": False,
                    "payload_byte_count": 0,
                    "source_payload_hash_sha256": _raw_sha256(None),
                    "payload_base64": None,
                    "omission_reason": "SOURCE_KEY_MISSING",
                }
            )
            effective_values[key] = None
            continue
        raw = _raw_bytes(value)
        omission_reason: str | None = None
        if len(raw) > MAX_CANONICAL_SOURCE_PAYLOAD_BYTES:
            omission_reason = "SOURCE_PAYLOAD_SIZE_LIMIT_EXCEEDED"
        elif included_byte_count + len(raw) > MAX_CANONICAL_SOURCE_SNAPSHOT_BYTES:
            omission_reason = "SOURCE_SNAPSHOT_TOTAL_SIZE_LIMIT_EXCEEDED"
        if omission_reason is not None:
            errors.append(f"{omission_reason}:{key}")
            snapshot.append(
                {
                    "schema_version": CANONICAL_SOURCE_SNAPSHOT_SCHEMA_VERSION,
                    "source_key": key,
                    "present": True,
                    "payload_included": False,
                    "payload_byte_count": len(raw),
                    "source_payload_hash_sha256": hashlib.sha256(raw).hexdigest(),
                    "payload_base64": None,
                    "omission_reason": omission_reason,
                }
            )
            effective_values[key] = None
            continue
        included_byte_count += len(raw)
        snapshot.append(
            {
                "schema_version": CANONICAL_SOURCE_SNAPSHOT_SCHEMA_VERSION,
                "source_key": key,
                "present": True,
                "payload_included": True,
                "payload_byte_count": len(raw),
                "source_payload_hash_sha256": hashlib.sha256(raw).hexdigest(),
                "payload_base64": base64.b64encode(raw).decode("ascii"),
                "omission_reason": None,
            }
        )
        effective_values[key] = raw
    return snapshot, effective_values, sorted(set(errors))


def _source_manifest_from_snapshot(
    snapshot: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "source_key": row["source_key"],
            "present": row["present"],
            "source_payload_hash_sha256": row["source_payload_hash_sha256"],
        }
        for row in snapshot
    ]


def _decode_bound_source_snapshot(
    value: Any,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
    """Validate bounded exact source bytes without trusting envelope hashes."""

    reasons: list[str] = []
    if not isinstance(value, list):
        return None, None, ["SOURCE_SNAPSHOT_INVALID"]
    if len(value) != len(CANONICAL_SOURCE_KEYS):
        return None, None, ["SOURCE_SNAPSHOT_KEYS_INVALID"]
    values: dict[str, Any] = {}
    normalized: list[dict[str, Any]] = []
    included_byte_count = 0
    maximum_base64_length = ((MAX_CANONICAL_SOURCE_PAYLOAD_BYTES + 2) // 3) * 4
    for expected_key, raw_row in zip(CANONICAL_SOURCE_KEYS, value, strict=True):
        if not isinstance(raw_row, Mapping) or frozenset(raw_row) != _SOURCE_SNAPSHOT_ROW_FIELDS:
            reasons.append("SOURCE_SNAPSHOT_ROW_INVALID")
            continue
        row = dict(raw_row)
        source_key = row.get("source_key")
        present = row.get("present")
        included = row.get("payload_included")
        byte_count = row.get("payload_byte_count")
        digest = row.get("source_payload_hash_sha256")
        payload_base64 = row.get("payload_base64")
        omission_reason = row.get("omission_reason")
        if (
            row.get("schema_version") != CANONICAL_SOURCE_SNAPSHOT_SCHEMA_VERSION
            or source_key != expected_key
            or not isinstance(present, bool)
            or not isinstance(included, bool)
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
            or not _is_sha256(digest)
        ):
            reasons.append("SOURCE_SNAPSHOT_ROW_INVALID")
            continue
        if not present:
            if (
                included
                or byte_count != 0
                or payload_base64 is not None
                or omission_reason != "SOURCE_KEY_MISSING"
                or digest != _raw_sha256(None)
            ):
                reasons.append("SOURCE_SNAPSHOT_MISSING_ROW_INVALID")
                continue
            values[expected_key] = None
            normalized.append(row)
            continue
        if not included:
            if (
                payload_base64 is not None
                or omission_reason
                not in {
                    "SOURCE_PAYLOAD_SIZE_LIMIT_EXCEEDED",
                    "SOURCE_SNAPSHOT_TOTAL_SIZE_LIMIT_EXCEEDED",
                }
                or (
                    omission_reason == "SOURCE_PAYLOAD_SIZE_LIMIT_EXCEEDED"
                    and byte_count <= MAX_CANONICAL_SOURCE_PAYLOAD_BYTES
                )
                or (
                    omission_reason == "SOURCE_SNAPSHOT_TOTAL_SIZE_LIMIT_EXCEEDED"
                    and (
                        byte_count > MAX_CANONICAL_SOURCE_PAYLOAD_BYTES
                        or included_byte_count + byte_count <= MAX_CANONICAL_SOURCE_SNAPSHOT_BYTES
                    )
                )
            ):
                reasons.append("SOURCE_SNAPSHOT_OMITTED_ROW_INVALID")
                continue
            values[expected_key] = None
            normalized.append(row)
            continue
        if (
            omission_reason is not None
            or not isinstance(payload_base64, str)
            or len(payload_base64) > maximum_base64_length
        ):
            reasons.append("SOURCE_SNAPSHOT_INCLUDED_ROW_INVALID")
            continue
        try:
            raw = base64.b64decode(payload_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            reasons.append("SOURCE_SNAPSHOT_BASE64_INVALID")
            continue
        included_byte_count += len(raw)
        if (
            len(raw) != byte_count
            or len(raw) > MAX_CANONICAL_SOURCE_PAYLOAD_BYTES
            or included_byte_count > MAX_CANONICAL_SOURCE_SNAPSHOT_BYTES
            or hashlib.sha256(raw).hexdigest() != digest
        ):
            reasons.append("SOURCE_SNAPSHOT_BYTES_BINDING_INVALID")
            continue
        values[expected_key] = raw
        normalized.append(row)
    if reasons or len(values) != len(CANONICAL_SOURCE_KEYS):
        return None, None, sorted(set(reasons or ["SOURCE_SNAPSHOT_INVALID"]))
    return values, normalized, []


def _source_manifest(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_key": key,
            "present": values.get(key) is not None,
            "source_payload_hash_sha256": _raw_sha256(values.get(key)),
        }
        for key in CANONICAL_SOURCE_KEYS
    ]


def _build_canonical_state(
    *,
    outcomes: dict[str, Any],
    regime: dict[str, Any],
    source_values: Mapping[str, Any],
    source_manifest: list[dict[str, Any]],
    source_read_errors: list[str],
    current_paper_session_id: str | None,
    session_identity_errors: list[str],
    outcomes_cutoff: datetime,
    adaptive_confidence_threshold: float,
    loss_probability_threshold: float,
    enable_b_grade: bool,
    enable_a_grade: bool,
    volatility_factor: float,
    trainer_performance_factor: float,
    portfolio_performance_factor: float,
    long_confidence_floor: float,
    short_confidence_floor: float,
    expectancy_floor: float,
    entry_freeze_allowance: float,
    a_plus_strictness: float,
) -> dict[str, Any]:
    # This private builder historically accepted caller-computed values.  Keep
    # the parameters for source compatibility, but never let a caller bypass
    # the single empirical derivation path (including its fail-closed vector).
    # Exact source bytes are bounded, sealed, and parsed again here; caller-
    # supplied outcomes, regime, manifests, identities, and policy values have
    # no authority.
    (
        canonical_source_snapshot,
        bound_source_values,
        source_read_errors,
    ) = _bounded_source_snapshot(source_values, source_read_errors)
    source_manifest = _source_manifest_from_snapshot(canonical_source_snapshot)
    (
        outcomes,
        regime,
        current_paper_session_id,
        session_identity_errors,
    ) = _derive_bound_source_evidence(
        bound_source_values,
        outcomes_cutoff=outcomes_cutoff,
        source_read_errors=source_read_errors,
    )
    source_snapshot_hash = _sha256_canonical(canonical_source_snapshot)
    derived_policy = _derive_adaptive_policy_values(outcomes, regime)
    adaptive_confidence_threshold = float(derived_policy["adaptive_confidence_threshold"])
    loss_probability_threshold = float(derived_policy["adaptive_loss_probability_threshold"])
    enable_b_grade = bool(derived_policy["enable_b_grade"])
    enable_a_grade = bool(derived_policy["enable_a_grade"])
    volatility_factor = float(derived_policy["volatility_factor"])
    trainer_performance_factor = float(derived_policy["trainer_performance_factor"])
    portfolio_performance_factor = float(derived_policy["portfolio_performance_factor"])
    long_confidence_floor = float(derived_policy["adaptive_long_confidence_floor"])
    short_confidence_floor = float(derived_policy["adaptive_short_confidence_floor"])
    expectancy_floor = float(derived_policy["adaptive_expectancy_floor"])
    entry_freeze_allowance = float(derived_policy["adaptive_entry_freeze_allowance"])
    a_plus_strictness = float(derived_policy["adaptive_a_plus_strictness"])

    outcome_evidence_sufficient = outcomes.get("evidence_sufficient") is True
    market_evidence_sufficient = regime.get("status") == "OK"
    evidence_sufficient = outcome_evidence_sufficient and market_evidence_sufficient
    realized_edge_lcb_bps = _finite(outcomes.get("realized_edge_lcb_bps"))
    economic_edge_positive = bool(
        evidence_sufficient and realized_edge_lcb_bps is not None and realized_edge_lcb_bps > 0.0
    )
    if not evidence_sufficient:
        policy_status = "FAIL_CLOSED_INSUFFICIENT_OR_UNTRUSTED_EVIDENCE"
    elif economic_edge_positive:
        policy_status = "EVIDENCE_BACKED_ADAPTIVE_POLICY"
    else:
        policy_status = "EVIDENCE_BACKED_RESTRICTIVE_NONPOSITIVE_EDGE"
    policy_values = {
        "adaptive_confidence_threshold": adaptive_confidence_threshold,
        "adaptive_loss_probability_threshold": loss_probability_threshold,
        "enable_b_grade": enable_b_grade,
        "enable_a_grade": enable_a_grade,
        "a_grade_ready": enable_a_grade,
        "blockers_resolved": False,
        "volatility_factor": volatility_factor,
        "trainer_performance_factor": trainer_performance_factor,
        "portfolio_performance_factor": portfolio_performance_factor,
        "adaptive_long_confidence_floor": long_confidence_floor,
        "adaptive_short_confidence_floor": short_confidence_floor,
        "adaptive_expectancy_floor": expectancy_floor,
        "adaptive_entry_freeze_allowance": entry_freeze_allowance,
        "adaptive_a_plus_strictness": a_plus_strictness,
    }
    manifest_hash = _sha256_canonical(source_manifest)
    manifest_by_key = {row["source_key"]: row for row in source_manifest}
    outcomes_source_hash = str(manifest_by_key[OUTCOMES_KEY]["source_payload_hash_sha256"])
    paper_session_source_hash = str(
        manifest_by_key[PAPER_SESSION_KEY]["source_payload_hash_sha256"]
    )
    policy_material = {
        "policy_version": GATE_TUNING_POLICY_VERSION,
        "producer": CANONICAL_PRODUCER,
        "outcomes_cutoff": _utc_iso(outcomes_cutoff),
        "outcomes_cutoff_source": "UTC_CLOCK_AFTER_ALL_SOURCE_READS",
        "current_paper_session_id": current_paper_session_id,
        "session_identity_errors": sorted(session_identity_errors),
        "source_manifest_hash_sha256": manifest_hash,
        "canonical_source_snapshot_hash_sha256": source_snapshot_hash,
        "source_read_errors": sorted(source_read_errors),
        "outcomes_evidence": _outcomes_evidence_projection(outcomes),
        "market_evidence_sufficient": market_evidence_sufficient,
        "economic_edge_positive": economic_edge_positive,
        "market_regime": regime,
        "policy_status": policy_status,
        "static_market_or_performance_thresholds": False,
        "threshold_derivation": THRESHOLD_DERIVATION_METHOD,
        "immutable_bound_classification": IMMUTABLE_BOUND_CLASSIFICATION,
        "policy_values": policy_values,
    }
    policy_material_hash = _sha256_canonical(policy_material)
    policy_id = f"adaptive_gate_policy_{policy_material_hash[:24]}"

    generated_at = _utc_now()
    if generated_at < outcomes_cutoff:
        raise RuntimeError("ADAPTIVE_TUNER_GENERATED_CLOCK_BEFORE_OUTCOMES_CUTOFF")
    available_at = _utc_now()
    if available_at < generated_at:
        raise RuntimeError("ADAPTIVE_TUNER_AVAILABLE_CLOCK_BEFORE_GENERATED_CLOCK")
    expires_at = available_at + timedelta(seconds=GATE_TUNING_TTL_SECONDS)

    permissive_authority = bool(
        evidence_sufficient
        and economic_edge_positive
        and (enable_b_grade or enable_a_grade or entry_freeze_allowance > 0.0)
    )
    payload: dict[str, Any] = {
        "schema_version": GATE_TUNING_SCHEMA_VERSION,
        "policy_version": GATE_TUNING_POLICY_VERSION,
        "producer": CANONICAL_PRODUCER,
        "canonical_key": GATE_TUNING_KEY,
        "authoritative": True,
        "authority_scope": "PAPER_ONLY_ADAPTIVE_GATE_TUNING",
        "authority_status": (
            "CANONICAL_EVIDENCE_BACKED_ADAPTIVE"
            if economic_edge_positive
            else "CANONICAL_EVIDENCE_BACKED_RESTRICTIVE"
            if evidence_sufficient
            else "CANONICAL_FAIL_CLOSED"
        ),
        "policy_status": policy_status,
        "permissive_authority": permissive_authority,
        "static_market_or_performance_thresholds": False,
        "threshold_derivation": THRESHOLD_DERIVATION_METHOD,
        "immutable_bound_classification": IMMUTABLE_BOUND_CLASSIFICATION,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "generated_at": _utc_iso(generated_at),
        "generated_utc": _utc_iso(generated_at),
        "generated_at_source": "UTC_CLOCK_AFTER_POLICY_DERIVATION_AND_MATERIAL_HASH",
        "available_at": _utc_iso(available_at),
        "available_at_source": "UTC_CLOCK_AFTER_CANONICAL_PAYLOAD_DERIVATION",
        "expires_at": _utc_iso(expires_at),
        "ttl_seconds": GATE_TUNING_TTL_SECONDS,
        "outcomes_cutoff": _utc_iso(outcomes_cutoff),
        "outcomes_cutoff_source": "UTC_CLOCK_AFTER_ALL_SOURCE_READS",
        "source_observed_at": _utc_iso(outcomes_cutoff),
        "current_paper_session_id": current_paper_session_id,
        "paper_session_id": current_paper_session_id,
        "paper_session_source_key": PAPER_SESSION_KEY,
        "paper_session_source_hash_sha256": paper_session_source_hash,
        "session_identity_errors": sorted(session_identity_errors),
        "source_key": OUTCOMES_KEY,
        "source_hash": outcomes_source_hash,
        "source_hash_contract": "EXACT_REDIS_VALUE_BYTES_SHA256_V1",
        "outcomes_source_key": OUTCOMES_KEY,
        "outcomes_source_hash_sha256": outcomes_source_hash,
        "canonical_source_snapshot": canonical_source_snapshot,
        "canonical_source_snapshot_hash_sha256": source_snapshot_hash,
        "canonical_source_snapshot_hash_contract": (
            "EXACT_SOURCE_BYTES_BASE64_WITH_BOUNDED_OMISSION_FAIL_CLOSED_"
            "SORTED_KEYS_COMPACT_ASCII_JSON_SHA256_V1"
        ),
        "source_manifest": source_manifest,
        "source_manifest_hash_sha256": manifest_hash,
        "source_manifest_hash_contract": (
            "SORTED_KEYS_COMPACT_ASCII_JSON_ALLOW_NAN_FALSE_SHA256_V1"
        ),
        "source_read_errors": sorted(source_read_errors),
        "source_row_count": outcomes.get("source_row_count", 0),
        "admitted_row_count": outcomes.get("admitted_row_count", 0),
        "rejected_row_count": outcomes.get("rejected_row_count", 0),
        "rejection_reason_counts": outcomes.get("rejection_reason_counts", {}),
        "source_rejection_reason_counts": outcomes.get("source_rejection_reason_counts", {}),
        "evidence_sufficient": evidence_sufficient,
        "outcome_evidence_sufficient": outcome_evidence_sufficient,
        "market_evidence_sufficient": market_evidence_sufficient,
        "economic_edge_positive": economic_edge_positive,
        "minimum_clean_outcomes_required": MIN_CLEAN_OUTCOMES_FOR_ADAPTATION,
        "outcomes": outcomes,
        "market_regime": regime,
        **policy_values,
        "canonical_policy_material": policy_material,
        "canonical_policy_material_hash_sha256": policy_material_hash,
        "canonical_policy_material_hash_contract": (
            "SORTED_KEYS_COMPACT_ASCII_JSON_ALLOW_NAN_FALSE_SHA256_V1"
        ),
        "policy_id": policy_id,
        "policy_id_contract": "adaptive_gate_policy_<first_24_policy_material_hash_hex>",
        "receipt_hash_contract": (
            "RECEIPT_SCHEMA_PRODUCER_CANONICAL_KEY_AND_UNSIGNED_PAYLOAD_"
            "SORTED_KEYS_COMPACT_ASCII_JSON_SHA256_V1"
        ),
    }
    receipt_hash = _receipt_hash(payload)
    payload["receipt_hash_sha256"] = receipt_hash
    payload["publication_receipt"] = {
        "schema_version": GATE_TUNING_RECEIPT_SCHEMA_VERSION,
        "producer": CANONICAL_PRODUCER,
        "canonical_key": GATE_TUNING_KEY,
        "policy_id": policy_id,
        "canonical_policy_material_hash_sha256": policy_material_hash,
        "canonical_source_snapshot_hash_sha256": source_snapshot_hash,
        "outcomes_source_key": OUTCOMES_KEY,
        "outcomes_source_hash_sha256": payload["outcomes_source_hash_sha256"],
        "outcomes_cutoff": payload["outcomes_cutoff"],
        "generated_at": payload["generated_at"],
        "available_at": payload["available_at"],
        "expires_at": payload["expires_at"],
        "receipt_hash_contract": payload["receipt_hash_contract"],
        "receipt_hash_sha256": receipt_hash,
    }
    return payload


def run_adaptive_tuning(redis_client: RedisStore | None = None) -> dict[str, Any]:
    """Capture, derive, seal, and publish one canonical tuning state."""
    if redis_client is None:
        redis_from_url: Any = redis.from_url
        redis_client = cast(
            RedisStore,
            redis_from_url(os.environ.get("REDIS_URL", "redis://localhost:6379")),
        )

    source_values, source_read_errors = _capture_sources(redis_client)
    outcomes_cutoff = _utc_now()

    # The legacy private-builder arguments are deliberately inert.  Passing
    # fail-closed placeholders avoids parsing or iterating any source before
    # the builder has enforced byte/row bounds and captured immutable bytes.
    tuning_state = _build_canonical_state(
        outcomes={},
        regime={},
        source_values=source_values,
        source_manifest=[],
        source_read_errors=source_read_errors,
        current_paper_session_id=None,
        session_identity_errors=[],
        outcomes_cutoff=outcomes_cutoff,
        adaptive_confidence_threshold=FAIL_CLOSED_CONFIDENCE_FLOOR,
        loss_probability_threshold=FAIL_CLOSED_LOSS_PROBABILITY_CEILING,
        enable_b_grade=False,
        enable_a_grade=False,
        volatility_factor=MAX_VOLATILITY_FACTOR,
        trainer_performance_factor=MIN_PERFORMANCE_FACTOR,
        portfolio_performance_factor=MIN_PERFORMANCE_FACTOR,
        long_confidence_floor=FAIL_CLOSED_CONFIDENCE_FLOOR,
        short_confidence_floor=FAIL_CLOSED_CONFIDENCE_FLOOR,
        expectancy_floor=0.0,
        entry_freeze_allowance=FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE,
        a_plus_strictness=MAX_A_PLUS_STRICTNESS,
    )

    # Publish state
    publish_gate_tuning(redis_client, tuning_state)

    logger.info(
        "Adaptive tuning: policy_id=%s evidence=%s admitted=%s rejected=%s",
        tuning_state["policy_id"],
        tuning_state["policy_status"],
        tuning_state["admitted_row_count"],
        tuning_state["rejected_row_count"],
    )

    return tuning_state


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(prog="v2_adaptive_gate_tuner")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true", help="run one tuning pass (default)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    if args.loop:
        while True:
            try:
                run_adaptive_tuning()
            except Exception as exc:  # one bad cycle must never kill the loop
                logger.warning("adaptive tuning cycle failed: %s", exc)
            time.sleep(max(5.0, float(args.interval_seconds)))
    result = run_adaptive_tuning()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
