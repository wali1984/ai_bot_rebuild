"""Resource-bounded, non-authoritative CoinAnk Redis hot history.

The authoritative provider response remains in the expiring ``:latest`` value
and append-only JSONL collection.  This module only creates a bounded scalar
diagnostic projection.  It grants no publication, trainer, prediction, risk,
or execution authority and never fills a missing value with zero.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final, NoReturn, cast

HOT_SERIES_SCHEMA_VERSION: Final = "coinank_bounded_scalar_hot_series_v3"
MAX_HOT_SERIES_ROWS: Final = 500
MAX_HOT_SERIES_SOURCE_BYTES: Final = 16 * 1024 * 1024
MAX_HOT_SERIES_ENCODED_BYTES: Final = 16 * 1024 * 1024
MAX_HOT_SERIES_RECORD_BYTES: Final = 64 * 1024
MAX_HOT_SERIES_SCALAR_FIELDS: Final = 4_096
MAX_HOT_SERIES_INPUT_MAPPING_FIELDS: Final = 4_096
MAX_HOT_SERIES_KEY_BYTES: Final = 256
MAX_HOT_SERIES_STRING_BYTES: Final = 2_048
MAX_HOT_SERIES_JSON_STRING_BYTES: Final = 256 * 1024
MAX_HOT_SERIES_JSON_DEPTH: Final = 32
MAX_HOT_SERIES_JSON_NODES: Final = 200_000
MAX_HOT_SERIES_JSON_CONTAINERS: Final = 50_000
MAX_HOT_SERIES_JSON_CONTAINER_ITEMS: Final = 100_000
_COMPACTION_METADATA_RESERVE_BYTES: Final = 8 * 1024
_MAX_SIGNED_64: Final = (1 << 63) - 1

_CORE_FIELDS: Final = (
    "ts_epoch_ms",
    "source_ts_ms",
    "timestamp",
    "ts_ms",
    "family",
    "baseCoin",
    "exchange",
    "interval",
    "endpoint",
    "endpoint_variant",
    "source",
)
_OMITTED_CONTAINER_FIELDS: Final = frozenset({"raw_data", "request_parameters"})
_AUTHORITY_FIELDS: Final = (
    "publication_authority",
    "trainer_authority",
    "prediction_authority",
    "risk_authority",
    "orchestrator_authority",
    "allocator_authority",
    "paper_authority",
    "live_authority",
    "live_execution_authority",
)
_CONSUMPTION_ADMISSION_FIELDS: Final = (
    "actual_consumption",
    "publication_consumption",
    "trainer_consumption",
    "prediction_consumption",
    "provider_tensor_consumption",
    "ppo_consumption",
    "masa_consumption",
    "risk_consumption",
    "orchestrator_consumption",
    "allocator_consumption",
    "paper_consumption",
    "live_consumption",
    "live_dryrun_consumption",
    "feedback_attribution",
    "trainer_consumption_prerequisites_bound",
    "consumer_receipts_bound",
    "postcommit_receipt_bound",
    "publication_atomic",
    "publication_committed",
    "consumer_eligible",
    "trainer_consumable",
    "publication_admission_granted",
    "trainer_admission_granted",
    "prediction_admission_granted",
    "risk_admission_granted",
    "orchestrator_admission_granted",
    "allocator_admission_granted",
    "paper_admission_granted",
    "live_admission_granted",
    "publication_granted",
    "trainer_granted",
    "prediction_granted",
    "risk_granted",
    "orchestrator_granted",
    "allocator_granted",
    "paper_granted",
    "live_granted",
    "admitted_ready",
    "feature_bridge_ready",
    "provider_ready",
    "source_ready",
    "coinank_can_approve_trade_alone",
    "provider_can_approve_trade_alone",
    "single_provider_can_approve",
    "provider_data_can_approve_trade_alone",
    "can_boost_confidence_modestly",
    "can_block_reduce_size_or_require_hedge",
    "live_execution_authorized",
    "exchange_action_taken",
    "places_real_order",
    "writes_exchange_orders",
    "valid_for_trainer",
    "valid_for_prediction",
    "valid_for_risk",
    "valid_for_orchestrator",
    "valid_for_allocator",
    "valid_for_paper",
    "valid_for_live",
)
_GENERATED_CONTRACT_FIELDS: Final = frozenset(
    {
        "hot_series_schema_version",
        "hot_series_role",
        "raw_data_omitted_from_hot_series",
        "request_parameters_omitted_from_hot_series",
        "omitted_scalar_field_count",
        "available_at",
        "admitted_feature_count",
        "zero_filled_field_count",
        "no_zero_fill_for_unknown_fields",
        "hot_series_reset_reason",
        "hot_series_prior_series_bytes",
        "hot_series_source_record_count",
        "hot_series_retained_record_count",
        "hot_series_evicted_record_count",
        "raw_provider_payload_not_deleted_by_hot_cache_compaction",
    }
)
_INVALID: Final = object()
_DIRECT_STRING_UTF8_CHUNK_CHARACTERS: Final = 64 * 1024


def _normalize_contract_key(value: str) -> str:
    """Casefold/NFKC and collapse every human separator to one underscore."""

    folded = unicodedata.normalize("NFKC", value).casefold()
    characters: list[str] = []
    separator_pending = False
    for character in folded:
        if character.isalnum():
            if separator_pending and characters:
                characters.append("_")
            characters.append(character)
            separator_pending = False
        else:
            separator_pending = bool(characters)
    return "".join(characters)


_PROTECTED_CONTRACT_FIELDS: Final = frozenset(
    _GENERATED_CONTRACT_FIELDS
    | _OMITTED_CONTAINER_FIELDS
    | frozenset(_AUTHORITY_FIELDS)
    | frozenset(_CONSUMPTION_ADMISSION_FIELDS)
)
_PROTECTED_NORMALIZED_FIELDS: Final = frozenset(
    _normalize_contract_key(field) for field in _PROTECTED_CONTRACT_FIELDS
)
_PROTECTED_FLAT_FIELDS: Final = frozenset(
    field.replace("_", "") for field in _PROTECTED_NORMALIZED_FIELDS
)
_SEMANTIC_TOKEN_BOUNDARY_1: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEMANTIC_TOKEN_BOUNDARY_2: Final = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_SEMANTIC_DENY_FLAT_STEMS: Final = (
    "admission",
    "admissible",
    "admit",
    "admitted",
    "allow",
    "approv",
    "authoris",
    "authorit",
    "authoriz",
    "eligib",
    "enabl",
    "execut",
    "grant",
    "permission",
    "permit",
    "readiness",
    "recommend",
    "safe",
    "signal",
    "train",
)
_SEMANTIC_DENY_TOKEN_PREFIXES: Final = (
    "action",
    "admiss",
    "admit",
    "allow",
    "approv",
    "authoris",
    "authorit",
    "authoriz",
    "eligib",
    "enabl",
    "execut",
    "grant",
    "permit",
    "recommend",
    "safe",
    "signal",
    "train",
)
_SEMANTIC_DENY_EXACT_TOKENS: Final = frozenset(
    {
        "advice",
        "can",
        "may",
        "must",
        "ok",
        "permission",
        "ready",
        "should",
    }
)
_SEMANTIC_DENY_FLAT_PHRASES: Final = (
    "actiontaken",
    "canexecute",
    "canorder",
    "cantrade",
    "golive",
    "gotrade",
    "mayexecute",
    "mayorder",
    "maytrade",
    "orderaction",
    "orderok",
    "placeorder",
    "shouldexecute",
    "shouldorder",
    "shouldtrade",
    "submitorder",
    "takeaction",
    "tradeaction",
    "tradeok",
    "trustforlive",
    "trustfortraining",
    "useforlive",
    "usefortraining",
)
_SAFE_TELEMETRY_SEMANTIC_COMPOUNDS: Final = (
    "bigorder",
    "marketorder",
    "orderbook",
    "orderflow",
    "toptrader",
)
_SAFE_TELEMETRY_EVIDENCE_TOKENS: Final = frozenset(
    {
        "account",
        "accounts",
        "amount",
        "amounts",
        "ask",
        "asks",
        "bid",
        "bids",
        "close",
        "closes",
        "count",
        "counts",
        "cvd",
        "data",
        "depth",
        "depths",
        "first",
        "imbalance",
        "imbalances",
        "last",
        "lists",
        "long",
        "longs",
        "mean",
        "means",
        "median",
        "medians",
        "open",
        "opens",
        "position",
        "positions",
        "price",
        "prices",
        "qty",
        "quantity",
        "quantities",
        "rate",
        "rates",
        "ratio",
        "ratios",
        "short",
        "shorts",
        "sum",
        "sums",
        "total",
        "totals",
        "turnover",
        "turnovers",
        "usd",
        "value",
        "values",
        "vol",
        "vols",
        "volume",
        "volumes",
    }
)
_SAFE_TELEMETRY_EVIDENCE_COMPOUNDS: Final = frozenset(
    {
        "buysellcount",
        "buysellvalue",
        "buysellvolume",
        "getaggcvd",
        "getaggbuysellcount",
        "getaggbuysellvalue",
        "getaggbuysellvolume",
        "getbuysellcount",
        "getbuysellvalue",
        "getbuysellvolume",
        "getcvd",
        "longratio",
        "longshortratio",
    }
)
_SAFE_TELEMETRY_CONTEXT_TOKENS: Final = frozenset(
    _SAFE_TELEMETRY_EVIDENCE_TOKENS
    | _SAFE_TELEMETRY_EVIDENCE_COMPOUNDS
    | {"agg", "buy", "col", "get", "ls", "sell"}
)
_SAFE_TELEMETRY_INDEX_TOKEN: Final = re.compile(r"(?:col)?[0-9]+")


class CoinAnkHotSeriesValidationError(ValueError):
    """A hostile or resource-unbounded hot-series payload was rejected."""


@dataclass(frozen=True, slots=True)
class CoinAnkHotSeriesCompaction:
    records: tuple[dict[str, Any], ...]
    encoded_json: str
    source_record_count: int
    retained_record_count: int
    evicted_record_count: int
    reset_reason: str | None


def _invalid(reason: str) -> NoReturn:
    raise CoinAnkHotSeriesValidationError(reason) from None


def _safe_unicode(value: str, *, maximum_bytes: int) -> bool:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return (
        len(encoded) <= maximum_bytes
        and unicodedata.normalize("NFC", value) == value
        and not any(unicodedata.category(char).startswith("C") for char in value)
    )


def _preflight_json_text(text: str) -> None:
    """Bound depth/tokens before ``json.loads`` allocates the object graph."""

    depth = 0
    nodes = 0
    containers = 0
    in_string = False
    escaped = False
    primitive = False
    raw_string_characters = 0
    maximum_raw_string_characters = MAX_HOT_SERIES_JSON_STRING_BYTES * 6
    for char in text:
        if in_string:
            raw_string_characters += 1
            if raw_string_characters > maximum_raw_string_characters:
                _invalid("coinank_hot_series_json_string_too_large")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            escaped = False
            primitive = False
            raw_string_characters = 0
            nodes += 1
        elif char in "[{":
            depth += 1
            containers += 1
            nodes += 1
            primitive = False
            if depth > MAX_HOT_SERIES_JSON_DEPTH:
                _invalid("coinank_hot_series_json_depth_exceeded")
            if containers > MAX_HOT_SERIES_JSON_CONTAINERS:
                _invalid("coinank_hot_series_json_container_count_exceeded")
        elif char in "]}":
            depth -= 1
            primitive = False
            if depth < 0:
                _invalid("coinank_hot_series_json_unbalanced")
        elif char in " \t\r\n,:":
            primitive = False
        elif not primitive:
            nodes += 1
            primitive = True
        if nodes > MAX_HOT_SERIES_JSON_NODES:
            _invalid("coinank_hot_series_json_node_count_exceeded")
    if in_string or depth != 0:
        _invalid("coinank_hot_series_json_unbalanced")


def _decode_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) > MAX_HOT_SERIES_JSON_CONTAINER_ITEMS:
        _invalid("coinank_hot_series_json_object_too_wide")
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if not _safe_unicode(key, maximum_bytes=MAX_HOT_SERIES_KEY_BYTES):
            _invalid("coinank_hot_series_json_key_invalid")
        if key in decoded:
            _invalid("coinank_hot_series_json_duplicate_key")
        decoded[key] = value
    return decoded


def _decode_int(token: str) -> int:
    if len(token.lstrip("-")) > 309:
        _invalid("coinank_hot_series_json_integer_too_large")
    value = int(token)
    if value.bit_length() > 1_024:
        _invalid("coinank_hot_series_json_integer_too_large")
    return value


def _decode_float(token: str) -> float:
    if len(token) > 128:
        _invalid("coinank_hot_series_json_float_too_large")
    value = float(token)
    if not math.isfinite(value):
        _invalid("coinank_hot_series_json_nonfinite")
    return value


def _reject_json_constant(_token: str) -> NoReturn:
    _invalid("coinank_hot_series_json_nonfinite")


def _validate_decoded_json(root: object) -> None:
    stack: list[tuple[object, int]] = [(root, 0)]
    nodes = 0
    containers = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_HOT_SERIES_JSON_NODES:
            _invalid("coinank_hot_series_json_node_count_exceeded")
        if type(value) is dict:
            containers += 1
            if depth >= MAX_HOT_SERIES_JSON_DEPTH:
                _invalid("coinank_hot_series_json_depth_exceeded")
            mapping = cast(dict[str, object], value)
            if len(mapping) > MAX_HOT_SERIES_JSON_CONTAINER_ITEMS:
                _invalid("coinank_hot_series_json_object_too_wide")
            stack.extend((item, depth + 1) for item in mapping.values())
        elif type(value) is list:
            containers += 1
            if depth >= MAX_HOT_SERIES_JSON_DEPTH:
                _invalid("coinank_hot_series_json_depth_exceeded")
            sequence = cast(list[object], value)
            if len(sequence) > MAX_HOT_SERIES_JSON_CONTAINER_ITEMS:
                _invalid("coinank_hot_series_json_array_too_wide")
            stack.extend((item, depth + 1) for item in sequence)
        elif type(value) is str:
            if not _safe_unicode(value, maximum_bytes=MAX_HOT_SERIES_JSON_STRING_BYTES):
                _invalid("coinank_hot_series_json_string_invalid")
        elif type(value) is int:
            if value.bit_length() > 1_024:
                _invalid("coinank_hot_series_json_integer_too_large")
        elif type(value) is float:
            if not math.isfinite(value):
                _invalid("coinank_hot_series_json_nonfinite")
        elif value is not None and type(value) is not bool:
            _invalid("coinank_hot_series_json_type_invalid")
        if containers > MAX_HOT_SERIES_JSON_CONTAINERS:
            _invalid("coinank_hot_series_json_container_count_exceeded")


def _bounded_direct_string_utf8_length(value: str, *, maximum_bytes: int) -> int:
    """Count UTF-8 incrementally so an oversized ``str`` is never encoded whole."""

    if not value or len(value) > maximum_bytes:
        _invalid("coinank_hot_series_json_byte_count_invalid")
    byte_count = 0
    for offset in range(0, len(value), _DIRECT_STRING_UTF8_CHUNK_CHARACTERS):
        chunk = value[offset : offset + _DIRECT_STRING_UTF8_CHUNK_CHARACTERS]
        try:
            byte_count += len(chunk.encode("utf-8", errors="strict"))
        except UnicodeError:
            _invalid("coinank_hot_series_json_utf8_invalid")
        if byte_count > maximum_bytes:
            _invalid("coinank_hot_series_json_byte_count_invalid")
    return byte_count


def decode_coinank_hot_series_json(
    raw: object,
    *,
    max_bytes: int = MAX_HOT_SERIES_SOURCE_BYTES,
) -> object:
    """Decode one strictly bounded JSON value with hostile-input rejection."""

    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_HOT_SERIES_SOURCE_BYTES:
        _invalid("coinank_hot_series_json_max_bytes_invalid")
    if type(raw) is bytes:
        if not raw or len(raw) > max_bytes:
            _invalid("coinank_hot_series_json_byte_count_invalid")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            _invalid("coinank_hot_series_json_utf8_invalid")
    elif type(raw) is str:
        _bounded_direct_string_utf8_length(raw, maximum_bytes=max_bytes)
        text = raw
    else:
        _invalid("coinank_hot_series_json_input_type_invalid")
    _preflight_json_text(text)
    try:
        decoded: object = json.loads(
            text,
            object_pairs_hook=_decode_object_pairs,
            parse_constant=_reject_json_constant,
            parse_int=_decode_int,
            parse_float=_decode_float,
        )
    except CoinAnkHotSeriesValidationError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError):
        _invalid("coinank_hot_series_json_syntax_invalid")
    _validate_decoded_json(decoded)
    return decoded


def _bounded_scalar(value: object) -> object:
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value if value.bit_length() <= 63 else _INVALID
    if type(value) is float:
        return value if math.isfinite(value) else _INVALID
    if type(value) is str:
        return (
            value if _safe_unicode(value, maximum_bytes=MAX_HOT_SERIES_STRING_BYTES) else _INVALID
        )
    return _INVALID


def _valid_key(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value.isascii()
        and _safe_unicode(value, maximum_bytes=MAX_HOT_SERIES_KEY_BYTES)
    )


def _without_evidence_backed_telemetry_compounds(parts: tuple[str, ...]) -> str:
    """Strip compounds only when the entire telemetry shape is closed and known."""

    compound_spans: list[tuple[int, int]] = []
    evidence_indexes = {
        index
        for index, token in enumerate(parts)
        if token in _SAFE_TELEMETRY_EVIDENCE_TOKENS or token in _SAFE_TELEMETRY_EVIDENCE_COMPOUNDS
    }
    index = 0
    while index < len(parts):
        width = 0
        if parts[index] in _SAFE_TELEMETRY_SEMANTIC_COMPOUNDS:
            width = 1
        elif (
            index + 1 < len(parts)
            and parts[index] + parts[index + 1] in _SAFE_TELEMETRY_SEMANTIC_COMPOUNDS
        ):
            width = 2
        if width:
            compound_spans.append((index, index + width))
            index += width
            continue
        if (
            parts[index] not in _SAFE_TELEMETRY_CONTEXT_TOKENS
            and _SAFE_TELEMETRY_INDEX_TOKEN.fullmatch(parts[index]) is None
        ):
            return "".join(parts)
        index += 1

    removable_indexes: set[int] = set()
    for start, end in compound_spans:
        if any(evidence_index >= end for evidence_index in evidence_indexes):
            removable_indexes.update(range(start, end))
    return "".join(
        token for token_index, token in enumerate(parts) if token_index not in removable_indexes
    )


def _is_semantic_authority_or_action_claim(key: str) -> bool:
    """Reject semantic authority aliases while retaining observed telemetry names."""

    camel_split = _SEMANTIC_TOKEN_BOUNDARY_1.sub("_", key)
    camel_split = _SEMANTIC_TOKEN_BOUNDARY_2.sub("_", camel_split)
    normalized = _normalize_contract_key(camel_split)
    semantic_parts = tuple(part for part in normalized.split("_") if part)
    flattened = normalized.replace("_", "")
    provider_parts = semantic_parts[1:] if semantic_parts[:1] == ("coinank",) else semantic_parts

    # CoinAnk emits order-flow/order-book/top-trader telemetry.  Those words are
    # descriptive only in a closed telemetry shape with concrete measurement
    # evidence after the compound.  This prevents unrelated words such as
    # ``operational`` (``ratio``), split aliases such as ``ope_ratio_nal``, or an
    # action alias with a real ``value`` suffix from supplying proof.
    semantic_flattened = _without_evidence_backed_telemetry_compounds(provider_parts)

    if "order" in semantic_flattened or "trade" in semantic_flattened:
        return True
    if "action" in flattened.replace("transaction", ""):
        return True
    if "ready" in flattened.replace("already", ""):
        return True
    if any(fragment in flattened for fragment in _SEMANTIC_DENY_FLAT_STEMS):
        return True
    if any(phrase in flattened for phrase in _SEMANTIC_DENY_FLAT_PHRASES):
        return True
    for semantic_part in semantic_parts:
        if semantic_part in _SEMANTIC_DENY_EXACT_TOKENS:
            return True
        if semantic_part != "already" and semantic_part.endswith("ready"):
            return True
        if semantic_part.startswith(_SEMANTIC_DENY_TOKEN_PREFIXES):
            return True
    return False


def _is_generated_or_authority_claim(key: str) -> bool:
    normalized = _normalize_contract_key(key)
    flattened = normalized.replace("_", "")
    return (
        normalized in _PROTECTED_NORMALIZED_FIELDS
        or flattened in _PROTECTED_FLAT_FIELDS
        or _is_semantic_authority_or_action_claim(key)
        or "authorit" in flattened
        or "consum" in flattened
        or "admission" in flattened
        or "admitted" in flattened
        or "grant" in flattened
        or "authoriz" in flattened
        or "authoris" in flattened
        or "approv" in flattened
        or "permission" in flattened
        or "eligible" in flattened
        or "validfor" in flattened
        or "providerready" in flattened
        or "sourceready" in flattened
        or "featureready" in flattened
        or "liveready" in flattened
        or "readyfor" in flattened
        or "oktotrade" in flattened
        or "cantrade" in flattened
        or "maytrade" in flattened
        or "tradeallowed" in flattened
        or "tradeenabled" in flattened
        or "tradingallowed" in flattened
        or "tradingenabled" in flattened
        or "executionallowed" in flattened
        or "executionenabled" in flattened
        or "canexecute" in flattened
        or "ordersubmission" in flattened
        or "actiontaken" in flattened
        or "realorder" in flattened
        or "writesexchangeorders" in flattened
        or "canboostconfidence" in flattened
        or "canblockreducesize" in flattened
        or "requirehedge" in flattened
        or "publication" in flattened
        or "publish" in flattened
        or "hotseries" in flattened
        or "availableat" in flattened
        or "zerofill" in flattened
        or "rawdata" in flattened
        or "requestparameters" in flattened
        or "requestparams" in flattened
        or "omittedscalar" in flattened
        or "rawproviderpayload" in flattened
    )


def _contract_metadata(*, omitted_scalar_fields: int) -> dict[str, object]:
    metadata: dict[str, object] = {
        "hot_series_schema_version": HOT_SERIES_SCHEMA_VERSION,
        "hot_series_role": "EXPIRING_NON_AUTHORITATIVE_SCALAR_HISTORY",
        "raw_data_omitted_from_hot_series": True,
        "request_parameters_omitted_from_hot_series": True,
        "omitted_scalar_field_count": omitted_scalar_fields,
        "available_at": None,
        "admitted_feature_count": 0,
        "zero_filled_field_count": 0,
        "no_zero_fill_for_unknown_fields": True,
    }
    metadata.update({field: False for field in _AUTHORITY_FIELDS})
    metadata.update({field: False for field in _CONSUMPTION_ADMISSION_FIELDS})
    return metadata


def _encode_bounded(value: object, *, maximum_bytes: int) -> str | None:
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    chunks: list[str] = []
    byte_count = 0
    try:
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("ascii", errors="strict")
            byte_count += len(encoded)
            if byte_count > maximum_bytes:
                return None
            chunks.append(chunk)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None
    return "".join(chunks)


def _required_identity_valid(compact: dict[str, Any]) -> bool:
    timestamp = compact.get("ts_epoch_ms")
    endpoint = compact.get("endpoint")
    family = compact.get("family")
    return (
        type(timestamp) is int
        and 0 <= timestamp <= _MAX_SIGNED_64
        and type(endpoint) is str
        and bool(endpoint)
        and _safe_unicode(endpoint, maximum_bytes=MAX_HOT_SERIES_STRING_BYTES)
        and type(family) is str
        and bool(family)
        and _safe_unicode(family, maximum_bytes=MAX_HOT_SERIES_STRING_BYTES)
    )


def _provider_scalar_key_allowed(key: str) -> bool:
    return key in _CORE_FIELDS or (key.startswith("coinank_") and len(key) > len("coinank_"))


def _strictly_increasing_timestamps(
    records: list[object] | tuple[object, ...],
    current_record: object,
) -> bool:
    previous = -1
    for record in records:
        if type(record) is not dict:
            return False
        timestamp = cast(dict[object, object], record).get("ts_epoch_ms")
        if (
            type(timestamp) is not int
            or not 0 <= timestamp <= _MAX_SIGNED_64
            or timestamp <= previous
        ):
            return False
        previous = timestamp
    if type(current_record) is not dict:
        return False
    current_timestamp = cast(dict[object, object], current_record).get("ts_epoch_ms")
    return (
        type(current_timestamp) is int
        and 0 <= current_timestamp <= _MAX_SIGNED_64
        and current_timestamp > previous
    )


def compact_coinank_hot_series_record(record: object) -> dict[str, Any] | None:
    """Return one bounded scalar projection with a closed negative-authority ABI."""

    if type(record) is not dict:
        return None
    raw_record = cast(dict[object, object], record)
    if len(raw_record) > MAX_HOT_SERIES_INPUT_MAPPING_FIELDS:
        return None
    try:
        pairs = tuple(raw_record.items())
    except RuntimeError:
        return None
    if len(pairs) != len(raw_record) or any(not _valid_key(key) for key, _value in pairs):
        return None

    compact: dict[str, Any] = {}
    omitted_scalar_fields = 0
    for raw_key, value in sorted(pairs, key=lambda item: cast(str, item[0])):
        key = cast(str, raw_key)
        if _is_generated_or_authority_claim(key):
            continue
        bounded = _bounded_scalar(value)
        if bounded is _INVALID:
            continue
        if not _provider_scalar_key_allowed(key):
            omitted_scalar_fields += 1
            continue
        if len(compact) >= MAX_HOT_SERIES_SCALAR_FIELDS:
            omitted_scalar_fields += 1
            continue
        compact[key] = bounded
    if not _required_identity_valid(compact):
        return None
    compact.update(_contract_metadata(omitted_scalar_fields=omitted_scalar_fields))
    if _encode_bounded(compact, maximum_bytes=MAX_HOT_SERIES_RECORD_BYTES) is not None:
        return compact

    minimal = {key: compact[key] for key in _CORE_FIELDS if key in compact}
    minimal.update(_contract_metadata(omitted_scalar_fields=omitted_scalar_fields))
    minimal["hot_series_record_scalar_projection_oversized"] = True
    if _encode_bounded(minimal, maximum_bytes=MAX_HOT_SERIES_RECORD_BYTES) is None:
        return None
    return minimal


def _bounded_reset_reason(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not _safe_unicode(value, maximum_bytes=512):
        return "INVALID_RESET_REASON_REDACTED"
    return value


def compact_coinank_hot_series(
    existing_records: object,
    current_record: object,
    *,
    reset_reason: str | None = None,
    prior_series_bytes: int | None = None,
) -> CoinAnkHotSeriesCompaction | None:
    """Build a contiguous newest suffix under fixed row and byte ceilings."""

    if type(existing_records) not in {list, tuple}:
        return None
    source = cast(list[object] | tuple[object, ...], existing_records)
    if len(source) > MAX_HOT_SERIES_JSON_CONTAINER_ITEMS:
        return None
    current = compact_coinank_hot_series_record(current_record)
    if current is None:
        return None
    reset = _bounded_reset_reason(reset_reason)
    if reset is None:
        if not _strictly_increasing_timestamps(source, current_record):
            return None
        source_count = len(source) + 1
        candidates = source[-(MAX_HOT_SERIES_ROWS - 1) :]
    else:
        source_count = 1
        candidates = ()

    current_encoded = _encode_bounded(current, maximum_bytes=MAX_HOT_SERIES_RECORD_BYTES)
    if current_encoded is None:
        return None
    selection_cap = MAX_HOT_SERIES_ENCODED_BYTES - _COMPACTION_METADATA_RESERVE_BYTES
    retained_reversed: list[dict[str, Any]] = [current]
    retained_bytes = 2 + len(current_encoded.encode("ascii"))
    for raw_record in reversed(candidates):
        projected = compact_coinank_hot_series_record(raw_record)
        if projected is None:
            break
        encoded_item = _encode_bounded(projected, maximum_bytes=MAX_HOT_SERIES_RECORD_BYTES)
        if encoded_item is None:
            break
        item_bytes = len(encoded_item.encode("ascii")) + 1
        if (
            len(retained_reversed) >= MAX_HOT_SERIES_ROWS
            or retained_bytes + item_bytes > selection_cap
        ):
            break
        retained_reversed.append(projected)
        retained_bytes += item_bytes

    retained = list(reversed(retained_reversed))
    evicted = max(0, source_count - len(retained))
    if reset is not None or evicted:
        latest = dict(retained[-1])
        latest.update(
            {
                "hot_series_reset_reason": reset,
                "hot_series_prior_series_bytes": (
                    prior_series_bytes
                    if type(prior_series_bytes) is int and 0 <= prior_series_bytes <= _MAX_SIGNED_64
                    else None
                ),
                "hot_series_source_record_count": source_count,
                "hot_series_retained_record_count": len(retained),
                "hot_series_evicted_record_count": evicted,
                "raw_provider_payload_not_deleted_by_hot_cache_compaction": True,
            }
        )
        retained[-1] = latest

    encoded = _encode_bounded(retained, maximum_bytes=MAX_HOT_SERIES_ENCODED_BYTES)
    if encoded is None:
        return None
    return CoinAnkHotSeriesCompaction(
        records=tuple(retained),
        encoded_json=encoded,
        source_record_count=source_count,
        retained_record_count=len(retained),
        evicted_record_count=evicted,
        reset_reason=reset,
    )
