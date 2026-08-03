"""Production-wired, fail-closed receipt for native feature publication.

This boundary proves what the feature worker placed in Redis, when Redis
linearized that publication, and that a consumer subsequently reopened the
same immutable snapshot and receipt bytes.  It binds every deployed tensor ABI
slot in ordinal order to the code-owned v4 source registry and resolution plan.

It deliberately does *not* convert the current source declarations into source
authentication.  The active feature worker still obtains several upstream
values through mutable, source-specific readers and 90 deployed slots have no
truthful resolver in the pinned v4 plan.  Accordingly every receipt records
``source_scope_complete = false`` and every trainer/prediction/paper/live flag
remains false.  This is the publication keystone on which later authenticated
source receipts can be joined; it is not permission to release a consumer.

The Redis protocol is two phase and fail closed:

1. one Lua script immutably creates/adopts the archive object, updates the
   mutable latest projection, then samples ``TIME`` as its final command;
2. the client builds a canonical receipt containing that post-write server
   clock, and a second Lua script conditionally commits it only while the exact
   archive bytes still match;
3. a third Lua script bounds and atomically reopens both values, then samples
   ``TIME``.  Python re-derives every hash and every ABI-slot binding.

All byte/count limits below are resource-integrity ceilings.  They do not
select a market, signal, training row, leverage value, or risk outcome.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol, cast

from v2.backend.app.services.native_trainer.feature_resolution_plan_v4 import (
    FEATURE_RESOLUTION_PLAN_V4,
    FEATURE_RESOLUTION_PLAN_V4_SHA256,
    FeatureSlotResolutionPlanV4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
    REQUIREMENT_REQUIRED,
    FeatureSourceRegistrySlotV4,
)

FEATURE_PUBLICATION_RECEIPT_SCHEMA_VERSION = "native_feature_publication_postcommit_receipt_v1"
FEATURE_PUBLICATION_SLOT_BINDING_SCHEMA_VERSION = "native_feature_publication_slot_binding_v1"
FEATURE_PUBLICATION_RECEIPT_EVIDENCE_CLASSIFICATION = (
    "POSTCOMMIT_REOPEN_VERIFIED_PUBLICATION_SOURCE_AUTHENTICATION_HELD"
)
FEATURE_PUBLICATION_RECEIPT_DOWNSTREAM_STATUS = (
    "PUBLICATION_INTEGRITY_ONLY_NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
FEATURE_PUBLICATION_TRANSFORM_SCHEMA_VERSION = (
    "EXACT_SNAPSHOT_FEATURE_SLOT_EXTRACTION_AND_FLOAT32_BINDING_V1"
)
FEATURE_PUBLICATION_CHAIN_DOMAIN = "v2/native-feature-publication/ordered-slot-bindings/v1"
FEATURE_PUBLICATION_RECEIPT_KEY_PREFIX = "v2:features:publication_receipt:"
FEATURE_PUBLICATION_RECEIPT_LATEST_KEY_PREFIX = "v2:features:publication_receipt:latest:"

MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 24
MAX_JSON_NODES = 32_768
MAX_JSON_CONTAINER_ITEMS = 4_096
MAX_JSON_STRING_BYTES = 2 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SNAPSHOT_ID_RE = re.compile(r"^v2_fsnap_[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]*[mhd]$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\." r"(?:[0-9]{3}|[0-9]{6})Z$",
    re.ASCII,
)
_CONSTRUCTION_TOKEN = object()

_AUTHORITY_FIELDS = (
    "source_scope_complete",
    "per_field_source_receipts_complete",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "feature_snapshot_id",
        "snapshot_archive_key",
        "snapshot_payload_sha256",
        "snapshot_payload_byte_count",
        "snapshot_features_sha256",
        "symbol",
        "timeframe",
        "feature_cutoff",
        "available_at",
        "available_at_clock_source",
        "feature_source_registry_sha256",
        "feature_resolution_plan_sha256",
        "feature_abi_sha256",
        "feature_requirement_policy_id",
        "producer_code_sha256",
        "producer_config_sha256",
        "publication_transform_schema_version",
        "publication_transform_code_sha256",
        "publication_transform_config_sha256",
        "slot_count",
        "required_slot_count",
        "optional_slot_count",
        "resolved_value_slot_count",
        "missing_required_slot_count",
        "missing_optional_slot_count",
        "unresolved_plan_slot_count",
        "complete_slot_coverage",
        "publication_binding_complete",
        "publication_binding_authenticated",
        "temporal_invariants_valid",
        "slot_binding_derivation_contract",
        "ordered_slot_binding_chain_sha256",
        *_AUTHORITY_FIELDS,
        "receipt_sha256",
    }
)

_PREPARE_PUBLICATION_LUA = r"""
-- native_feature_publication_prepare_v1
local archive_key = KEYS[1]
local latest_key = KEYS[2]
local receipt_key = KEYS[3]
local payload = ARGV[1]
local archive_ttl = tonumber(ARGV[2])
local latest_ttl = tonumber(ARGV[3])
local max_snapshot = tonumber(ARGV[4])

if not archive_ttl or not latest_ttl or archive_ttl <= latest_ttl
   or archive_ttl ~= math.floor(archive_ttl)
   or latest_ttl ~= math.floor(latest_ttl) then
  return {"ERROR", "SNAPSHOT_ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL"}
end
if string.len(payload) > max_snapshot then
  return {"ERROR", "SNAPSHOT_ARGUMENT_OVERSIZED"}
end
local archive_type = redis.call("TYPE", archive_key)["ok"]
if archive_type ~= "none" and archive_type ~= "string" then
  return {"ERROR", "SNAPSHOT_ARCHIVE_TYPE_INVALID"}
end
if archive_type == "string" then
  local archive_len = redis.call("STRLEN", archive_key)
  if archive_len > max_snapshot then
    return {"ERROR", "SNAPSHOT_ARCHIVE_OVERSIZED"}
  end
  if redis.call("GET", archive_key) ~= payload then
    return {"ERROR", "SNAPSHOT_ARCHIVE_IDENTITY_CONFLICT"}
  end
  if redis.call("EXPIRE", archive_key, archive_ttl) ~= 1 then
    return {"ERROR", "SNAPSHOT_ARCHIVE_TTL_REFRESH_FAILED"}
  end
else
  redis.call("SET", archive_key, payload, "EX", archive_ttl)
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "RECEIPT_TYPE_INVALID"}
end
if receipt_type == "string" then
  return {"ERROR", "RECEIPT_ALREADY_EXISTS_USE_CONSUMER_REOPEN"}
end
redis.call("SET", latest_key, payload, "EX", latest_ttl)
if redis.call("PTTL", archive_key) <= latest_ttl * 1000 then
  return {"ERROR", "SNAPSHOT_ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local observed = redis.call("TIME")
return {"PREPARED", observed[1], observed[2]}
"""

_COMMIT_RECEIPT_LUA = r"""
-- native_feature_publication_commit_receipt_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local pointer_key = KEYS[3]
local snapshot_payload = ARGV[1]
local receipt_payload = ARGV[2]
local ttl = tonumber(ARGV[3])
local max_snapshot = tonumber(ARGV[4])
local max_receipt = tonumber(ARGV[5])
local snapshot_id = ARGV[6]

if string.len(snapshot_payload) > max_snapshot then
  return {"ERROR", "SNAPSHOT_ARGUMENT_OVERSIZED"}
end
if string.len(receipt_payload) > max_receipt then
  return {"ERROR", "RECEIPT_ARGUMENT_OVERSIZED"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "SNAPSHOT_ARCHIVE_MISSING"}
end
local archive_len = redis.call("STRLEN", archive_key)
if archive_len > max_snapshot then
  return {"ERROR", "SNAPSHOT_ARCHIVE_OVERSIZED"}
end
if redis.call("GET", archive_key) ~= snapshot_payload then
  return {"ERROR", "SNAPSHOT_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("PTTL", archive_key) <= ttl * 1000 then
  return {"ERROR", "SNAPSHOT_ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "RECEIPT_TYPE_INVALID"}
end
if receipt_type == "string" then
  local receipt_len = redis.call("STRLEN", receipt_key)
  if receipt_len > max_receipt then
    return {"ERROR", "RECEIPT_OVERSIZED"}
  end
  if redis.call("GET", receipt_key) ~= receipt_payload then
    return {"ERROR", "RECEIPT_IDENTITY_CONFLICT"}
  end
else
  redis.call("SET", receipt_key, receipt_payload, "EX", ttl)
end
redis.call("SET", pointer_key, snapshot_id, "EX", ttl)
local observed = redis.call("TIME")
return {receipt_type == "string" and "IDEMPOTENT" or "COMMITTED", observed[1], observed[2]}
"""

_REOPEN_PUBLICATION_LUA = r"""
-- native_feature_publication_reopen_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local max_snapshot = tonumber(ARGV[1])
local max_receipt = tonumber(ARGV[2])
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "SNAPSHOT_ARCHIVE_MISSING"}
end
if redis.call("TYPE", receipt_key)["ok"] ~= "string" then
  return {"ERROR", "RECEIPT_MISSING"}
end
local archive_len = redis.call("STRLEN", archive_key)
if archive_len > max_snapshot then
  return {"ERROR", "SNAPSHOT_ARCHIVE_OVERSIZED"}
end
local receipt_len = redis.call("STRLEN", receipt_key)
if receipt_len > max_receipt then
  return {"ERROR", "RECEIPT_OVERSIZED"}
end
local snapshot_payload = redis.call("GET", archive_key)
local receipt_payload = redis.call("GET", receipt_key)
local observed = redis.call("TIME")
return {"REOPENED", snapshot_payload, receipt_payload, observed[1], observed[2]}
"""


class RedisFeaturePublicationClient(Protocol):
    """Minimal synchronous Redis surface used by this boundary."""

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class FeaturePublicationReceiptError(RuntimeError):
    """Base fail-closed feature publication error."""


class FeaturePublicationReceiptValidationError(FeaturePublicationReceiptError):
    """Caller data or a persisted receipt violates the receipt contract."""


class FeaturePublicationReceiptIntegrityError(FeaturePublicationReceiptError):
    """Redis state changed, disappeared, or failed consumer re-verification."""


class FeaturePublicationReceiptTransportError(FeaturePublicationReceiptError):
    """Redis did not execute the bounded atomic protocol."""


@dataclass(frozen=True, slots=True)
class VerifiedFeaturePublication:
    """Factory-only result after exact consumer reopen verification."""

    feature_snapshot_id: str
    snapshot_archive_key: str
    receipt_key: str
    latest_receipt_pointer_key: str
    snapshot_available_at: str
    receipt_postcommit_observed_at: str
    consumer_reopened_at: str
    receipt_sha256: str
    snapshot_payload_sha256: str
    slot_count: int
    complete_slot_coverage: bool
    publication_binding_authenticated: bool
    source_scope_complete: bool
    per_field_source_receipts_complete: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    receipt: Mapping[str, Any] = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _validation_error("FEATURE_PUBLICATION_FACTORY_CONSTRUCTION_REQUIRED")
        if (
            self.slot_count != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
            or self.complete_slot_coverage is not True
            or self.publication_binding_authenticated is not True
            or self.source_scope_complete is not False
            or self.per_field_source_receipts_complete is not False
            or any(
                value is not False
                for value in (
                    self.trainer_admission_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                )
            )
        ):
            _validation_error("FEATURE_PUBLICATION_RESULT_AUTHORITY_INVALID")


def _validation_error(reason: str) -> NoReturn:
    raise FeaturePublicationReceiptValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise FeaturePublicationReceiptIntegrityError(reason) from None


def _canonical_json_bytes(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation_error("FEATURE_PUBLICATION_CANONICAL_JSON_INVALID")
    if not encoded or len(encoded) > maximum:
        _validation_error("FEATURE_PUBLICATION_CANONICAL_JSON_SIZE_INVALID")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum=MAX_RECEIPT_BYTES))


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _validation_error("FEATURE_PUBLICATION_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _parse_json_int(value: str) -> int:
    if len(value) > 128:
        _validation_error("FEATURE_PUBLICATION_JSON_NUMBER_RESOURCE_LIMIT")
    try:
        return int(value)
    except ValueError:
        _validation_error("FEATURE_PUBLICATION_JSON_NUMBER_INVALID")


def _parse_json_float(value: str) -> float:
    if len(value) > 128:
        _validation_error("FEATURE_PUBLICATION_JSON_NUMBER_RESOURCE_LIMIT")
    try:
        parsed = float(value)
    except ValueError:
        _validation_error("FEATURE_PUBLICATION_JSON_NUMBER_INVALID")
    if not math.isfinite(parsed):
        _validation_error("FEATURE_PUBLICATION_JSON_NONFINITE")
    return parsed


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            _validation_error("FEATURE_PUBLICATION_JSON_RESOURCE_LIMIT")
        if isinstance(item, dict):
            if len(item) > MAX_JSON_CONTAINER_ITEMS:
                _validation_error("FEATURE_PUBLICATION_JSON_RESOURCE_LIMIT")
            for key, child in item.items():
                if type(key) is not str or len(key.encode("utf-8")) > 512:
                    _validation_error("FEATURE_PUBLICATION_JSON_KEY_INVALID")
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            if len(item) > MAX_JSON_CONTAINER_ITEMS:
                _validation_error("FEATURE_PUBLICATION_JSON_RESOURCE_LIMIT")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item.encode("utf-8")) > MAX_JSON_STRING_BYTES:
                _validation_error("FEATURE_PUBLICATION_JSON_RESOURCE_LIMIT")
        elif item is None or type(item) in (bool, int, float):
            if type(item) is float and not math.isfinite(item):
                _validation_error("FEATURE_PUBLICATION_JSON_NONFINITE")
        else:
            _validation_error("FEATURE_PUBLICATION_JSON_TYPE_INVALID")


def _parse_json_object(payload: object, *, maximum: int) -> dict[str, Any]:
    if type(payload) is str:
        try:
            raw = payload.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _validation_error("FEATURE_PUBLICATION_JSON_UTF8_INVALID")
    elif type(payload) is bytes:
        raw = payload
    else:
        _validation_error("FEATURE_PUBLICATION_JSON_PAYLOAD_TYPE_INVALID")
    if not raw or len(raw) > maximum:
        _validation_error("FEATURE_PUBLICATION_JSON_PAYLOAD_SIZE_INVALID")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_int=_parse_json_int,
            parse_float=_parse_json_float,
            parse_constant=lambda _value: _validation_error("FEATURE_PUBLICATION_JSON_NONFINITE"),
        )
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        _validation_error("FEATURE_PUBLICATION_JSON_PARSE_FAILED")
    if type(parsed) is not dict:
        _validation_error("FEATURE_PUBLICATION_JSON_OBJECT_REQUIRED")
    _validate_json_tree(parsed)
    return cast(dict[str, Any], parsed)


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_clock(value: object) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _validation_error("FEATURE_PUBLICATION_CLOCK_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _validation_error("FEATURE_PUBLICATION_CLOCK_INVALID")
    fraction = value.rsplit(".", 1)[1][:-1]
    timespec = "milliseconds" if len(fraction) == 3 else "microseconds"
    if parsed.isoformat(timespec=timespec).replace("+00:00", "Z") != value:
        _validation_error("FEATURE_PUBLICATION_CLOCK_INVALID")
    return parsed


def _redis_clock(seconds: object, microseconds: object) -> str:
    try:
        if isinstance(seconds, bytes):
            seconds = seconds.decode("ascii", errors="strict")
        if isinstance(microseconds, bytes):
            microseconds = microseconds.decode("ascii", errors="strict")
        if type(seconds) not in (str, int) or type(microseconds) not in (str, int):
            raise ValueError
        seconds_value = cast(str | int, seconds)
        microseconds_value = cast(str | int, microseconds)
        seconds_int = int(seconds_value)
        microseconds_int = int(microseconds_value)
        if str(seconds_int) != str(seconds) or str(microseconds_int) != str(microseconds):
            raise ValueError
        if seconds_int < 0 or not 0 <= microseconds_int <= 999_999:
            raise ValueError
        value = datetime.fromtimestamp(
            seconds_int + microseconds_int / 1_000_000,
            tz=UTC,
        )
    except (OSError, OverflowError, UnicodeDecodeError, ValueError):
        _integrity_error("FEATURE_PUBLICATION_REDIS_TIME_INVALID")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _response_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _integrity_error("FEATURE_PUBLICATION_REDIS_RESPONSE_UTF8_INVALID")
    if type(value) is str:
        return value
    _integrity_error("FEATURE_PUBLICATION_REDIS_RESPONSE_TYPE_INVALID")


def _eval(
    redis_client: RedisFeaturePublicationClient,
    script: str,
    keys: Sequence[str],
    arguments: Sequence[object],
) -> list[object]:
    try:
        result = redis_client.eval(script, len(keys), *keys, *arguments)
    except Exception as exc:
        raise FeaturePublicationReceiptTransportError(
            "FEATURE_PUBLICATION_REDIS_EVAL_FAILED"
        ) from exc
    if type(result) not in (list, tuple):
        _integrity_error("FEATURE_PUBLICATION_REDIS_RESPONSE_INVALID")
    return list(cast(Sequence[object], result))


def _eval_status(response: Sequence[object], *, expected_size: int) -> str:
    if len(response) < 2:
        _integrity_error("FEATURE_PUBLICATION_REDIS_RESPONSE_INVALID")
    status = _response_text(response[0])
    if status == "ERROR":
        _integrity_error(_response_text(response[1]))
    if len(response) != expected_size:
        _integrity_error("FEATURE_PUBLICATION_REDIS_RESPONSE_INVALID")
    return status


def _exact_snapshot_id(snapshot: Mapping[str, Any]) -> str:
    without_id = dict(snapshot)
    without_id.pop("feature_snapshot_id", None)
    try:
        encoded = json.dumps(without_id, sort_keys=True).encode()
    except (OverflowError, RecursionError, TypeError, ValueError):
        _validation_error("FEATURE_PUBLICATION_SNAPSHOT_ID_INPUT_INVALID")
    return f"v2_fsnap_{hashlib.sha256(encoded).hexdigest()}"


def _validated_snapshot_payload(snapshot_payload: object) -> tuple[dict[str, Any], bytes]:
    snapshot = _parse_json_object(snapshot_payload, maximum=MAX_SNAPSHOT_BYTES)
    snapshot_id = snapshot.get("feature_snapshot_id")
    if type(snapshot_id) is not str or _SNAPSHOT_ID_RE.fullmatch(snapshot_id) is None:
        _validation_error("FEATURE_PUBLICATION_SNAPSHOT_ID_INVALID")
    if snapshot_id != _exact_snapshot_id(snapshot):
        _validation_error("FEATURE_PUBLICATION_SNAPSHOT_ID_MISMATCH")
    if (
        snapshot.get("schema_version") != "v2_native_feature_snapshot_v2"
        or snapshot.get("worker_id") != "v2_feature_pipeline_native_loop"
        or type(snapshot.get("symbol")) is not str
        or _SYMBOL_RE.fullmatch(cast(str, snapshot["symbol"])) is None
        or type(snapshot.get("timeframe")) is not str
        or _TIMEFRAME_RE.fullmatch(cast(str, snapshot["timeframe"])) is None
        or type(snapshot.get("features")) is not dict
    ):
        _validation_error("FEATURE_PUBLICATION_SNAPSHOT_CONTRACT_INVALID")
    if any(
        snapshot.get(field_name) is not False
        for field_name in ("trainer_consumable", "valid_for_prediction", "valid_for_paper")
    ):
        _validation_error("FEATURE_PUBLICATION_SNAPSHOT_HOLD_REQUIRED")
    raw = (
        snapshot_payload.encode("utf-8")
        if type(snapshot_payload) is str
        else cast(bytes, snapshot_payload)
    )
    return snapshot, raw


def _float32_hex(value: object) -> str | None:
    if isinstance(value, bool) or type(value) not in (int, float):
        return None
    try:
        numeric = float(cast(int | float, value))
        packed = struct.pack("!f", numeric)
        roundtrip = struct.unpack("!f", packed)[0]
    except (OverflowError, struct.error, TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not math.isfinite(roundtrip):
        return None
    if numeric != 0.0 and roundtrip == 0.0:
        return None
    return packed.hex()


def _source_declaration(
    slot: FeatureSourceRegistrySlotV4,
    plan_slot: FeatureSlotResolutionPlanV4,
) -> dict[str, object]:
    return {
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "ordinal": slot.ordinal,
        "feature_name": slot.feature_name,
        "configured_source_label": slot.configured_source_label,
        "source_key_template": plan_slot.source_key_template,
        "source_timeframe_template": plan_slot.source_timeframe_template,
        "source_payload_schema_version": plan_slot.source_payload_schema_version,
        "resolution_plan_status": plan_slot.plan_status,
        "resolution_plan_unresolved_reason": plan_slot.unresolved_reason,
    }


def _transform_declaration(
    plan_slot: FeatureSlotResolutionPlanV4,
) -> dict[str, object]:
    return {
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "ordinal": plan_slot.ordinal,
        "feature_name": plan_slot.feature_name,
        "branches": [
            {
                "branch_id": branch.branch_id,
                "selected_alias": branch.selected_alias,
                "dependency_paths": [list(path) for path in branch.dependency_paths],
                "transform_id": branch.transform_id,
                "transform_version": branch.transform_version,
            }
            for branch in plan_slot.branches
        ],
    }


_PUBLICATION_TRANSFORM_CODE_SHA256 = _stable_sha256(
    {
        "schema_version": FEATURE_PUBLICATION_TRANSFORM_SCHEMA_VERSION,
        "operation": (
            "EXACT_FEATURE_NAME_LOOKUP_THEN_CANONICAL_JSON_SHA256_AND_IEEE754_"
            "BINARY32_BIG_ENDIAN_BINDING"
        ),
        "missing_policy": "PRESERVE_MISSING_NEVER_ZERO_FILL",
        "nonfinite_policy": "REJECT_AS_MISSING_NEVER_SERIALIZE_NONFINITE",
    }
)
_PUBLICATION_TRANSFORM_CONFIG_SHA256 = _stable_sha256(
    {
        "schema_version": "native_feature_publication_transform_config_v1",
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "feature_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "feature_requirement_policy_id": (FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID),
    }
)


def _slot_bindings(
    *,
    snapshot: Mapping[str, Any],
    snapshot_payload_sha256: str,
    snapshot_features_sha256: str,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    features = cast(Mapping[str, Any], snapshot["features"])
    slots = FEATURE_SOURCE_REGISTRY_V4.slots
    plan_slots = FEATURE_RESOLUTION_PLAN_V4.slots
    if len(slots) != len(plan_slots) or len(slots) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _validation_error("FEATURE_PUBLICATION_ABI_DIMENSION_INVALID")

    bindings: list[dict[str, Any]] = []
    chain = hashlib.sha256(FEATURE_PUBLICATION_CHAIN_DOMAIN.encode("ascii")).hexdigest()
    counts = {
        "required": 0,
        "optional": 0,
        "resolved": 0,
        "missing_required": 0,
        "missing_optional": 0,
        "unresolved_plan": 0,
    }
    for slot, plan_slot in zip(slots, plan_slots, strict=True):
        if (
            slot.ordinal != plan_slot.ordinal
            or slot.feature_name != plan_slot.feature_name
            or slot.configured_source_label != plan_slot.configured_source_label
            or slot.requirement_class != plan_slot.requirement_class
        ):
            _validation_error("FEATURE_PUBLICATION_REGISTRY_PLAN_DRIFT")
        if slot.requirement_class == REQUIREMENT_REQUIRED:
            counts["required"] += 1
        elif slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT:
            counts["optional"] += 1
        else:
            _validation_error("FEATURE_PUBLICATION_REQUIREMENT_CLASS_INVALID")

        present = slot.feature_name in features
        raw_value = features.get(slot.feature_name)
        float32_hex = _float32_hex(raw_value) if present else None
        if float32_hex is not None:
            value_status = "PRESENT_FINITE_VALUE_BOUND"
            value_sha256 = _stable_sha256(raw_value)
            counts["resolved"] += 1
        elif slot.requirement_class == REQUIREMENT_REQUIRED:
            value_status = "MISSING_REQUIRED_VALUE_HELD"
            value_sha256 = _stable_sha256(None)
            counts["missing_required"] += 1
        else:
            value_status = "MISSING_OPTIONAL_WITHOUT_TYPED_NEGATIVE_RECEIPT_HELD"
            value_sha256 = _stable_sha256(None)
            counts["missing_optional"] += 1
        if plan_slot.unresolved_reason is not None:
            counts["unresolved_plan"] += 1

        value_binding = {
            "schema_version": "native_feature_published_value_binding_v1",
            "feature_snapshot_id": snapshot["feature_snapshot_id"],
            "snapshot_payload_sha256": snapshot_payload_sha256,
            "snapshot_features_sha256": snapshot_features_sha256,
            "ordinal": slot.ordinal,
            "feature_name": slot.feature_name,
            "value_status": value_status,
            "published_value_json_sha256": value_sha256,
            "published_value_float32_be_hex": float32_hex,
        }
        unsigned = {
            "schema_version": FEATURE_PUBLICATION_SLOT_BINDING_SCHEMA_VERSION,
            "ordinal": slot.ordinal,
            "feature_name": slot.feature_name,
            "configured_source_label": slot.configured_source_label,
            "requirement_class": slot.requirement_class,
            "resolution_plan_status": plan_slot.plan_status,
            "resolution_plan_unresolved_reason": plan_slot.unresolved_reason,
            "configured_source_identity_sha256": _stable_sha256(
                _source_declaration(slot, plan_slot)
            ),
            "declared_transform_set_sha256": _stable_sha256(_transform_declaration(plan_slot)),
            "value_status": value_status,
            "published_value_json_sha256": value_sha256,
            "published_value_float32_be_hex": float32_hex,
            "published_value_binding_sha256": _stable_sha256(value_binding),
            # The exact publication value is bound above.  These remain empty
            # until an authenticated upstream source adapter supplies them.
            "upstream_source_payload_sha256": None,
            "upstream_source_receipt_sha256": None,
            "upstream_source_receipt_verified": False,
            "executed_transform_verified": False,
        }
        slot_binding_sha256 = _stable_sha256(unsigned)
        binding = {**unsigned, "slot_binding_sha256": slot_binding_sha256}
        chain = hashlib.sha256(
            bytes.fromhex(chain) + bytes.fromhex(slot_binding_sha256)
        ).hexdigest()
        bindings.append(binding)
    return bindings, chain, counts


def _temporal_invariants_valid(snapshot: Mapping[str, Any], available_at: str) -> bool:
    try:
        feature_cutoff = _parse_clock(snapshot.get("feature_cutoff"))
        available = _parse_clock(available_at)
    except FeaturePublicationReceiptValidationError:
        return False
    return bool(
        snapshot.get("candle_closed_confirmed") is True
        and snapshot.get("latest_candle_temporally_valid") is True
        and snapshot.get("exact_source_clock_valid") is True
        and feature_cutoff <= available
    )


def _build_receipt(
    *,
    snapshot: Mapping[str, Any],
    snapshot_payload: bytes,
    snapshot_archive_key: str,
    available_at: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
) -> dict[str, Any]:
    if not _valid_sha256(producer_code_sha256) or not _valid_sha256(producer_config_sha256):
        _validation_error("FEATURE_PUBLICATION_PRODUCER_IDENTITY_INVALID")
    features_sha256 = _stable_sha256(snapshot["features"])
    payload_sha256 = _sha256_bytes(snapshot_payload)
    bindings, chain, counts = _slot_bindings(
        snapshot=snapshot,
        snapshot_payload_sha256=payload_sha256,
        snapshot_features_sha256=features_sha256,
    )
    unsigned: dict[str, Any] = {
        "schema_version": FEATURE_PUBLICATION_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": (FEATURE_PUBLICATION_RECEIPT_EVIDENCE_CLASSIFICATION),
        "downstream_status": FEATURE_PUBLICATION_RECEIPT_DOWNSTREAM_STATUS,
        "feature_snapshot_id": snapshot["feature_snapshot_id"],
        "snapshot_archive_key": snapshot_archive_key,
        "snapshot_payload_sha256": payload_sha256,
        "snapshot_payload_byte_count": len(snapshot_payload),
        "snapshot_features_sha256": features_sha256,
        "symbol": snapshot["symbol"],
        "timeframe": snapshot["timeframe"],
        "feature_cutoff": snapshot.get("feature_cutoff"),
        "available_at": available_at,
        "available_at_clock_source": (
            "REDIS_TIME_FINAL_COMMAND_AFTER_ATOMIC_SNAPSHOT_ARCHIVE_AND_LATEST_SET"
        ),
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_resolution_plan_sha256": FEATURE_RESOLUTION_PLAN_V4_SHA256,
        "feature_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "feature_requirement_policy_id": (FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID),
        "producer_code_sha256": producer_code_sha256,
        "producer_config_sha256": producer_config_sha256,
        "publication_transform_schema_version": (FEATURE_PUBLICATION_TRANSFORM_SCHEMA_VERSION),
        "publication_transform_code_sha256": (_PUBLICATION_TRANSFORM_CODE_SHA256),
        "publication_transform_config_sha256": (_PUBLICATION_TRANSFORM_CONFIG_SHA256),
        "slot_count": len(bindings),
        "required_slot_count": counts["required"],
        "optional_slot_count": counts["optional"],
        "resolved_value_slot_count": counts["resolved"],
        "missing_required_slot_count": counts["missing_required"],
        "missing_optional_slot_count": counts["missing_optional"],
        "unresolved_plan_slot_count": counts["unresolved_plan"],
        "complete_slot_coverage": len(bindings) == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        "publication_binding_complete": True,
        "publication_binding_authenticated": True,
        "temporal_invariants_valid": _temporal_invariants_valid(
            snapshot,
            available_at,
        ),
        # The 446 verbose leaves are deterministically re-derived from the
        # reopened snapshot plus the two pinned code-owned contracts.  Only
        # their ordered chain is retained in Redis; persisting every leaf for
        # every symbol/timeframe/cycle would create avoidable Redis pressure.
        "slot_binding_derivation_contract": (
            "REOPEN_EXACT_SNAPSHOT_THEN_DERIVE_ALL_ABI_ORDERED_SLOT_BINDINGS_"
            "FROM_PINNED_SOURCE_REGISTRY_AND_RESOLUTION_PLAN_V1"
        ),
        "ordered_slot_binding_chain_sha256": chain,
        # These fixed holds are part of the receipt hash.  Publication-byte
        # integrity is not upstream source authentication.
        "source_scope_complete": False,
        "per_field_source_receipts_complete": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    return {**unsigned, "receipt_sha256": _stable_sha256(unsigned)}


def _validate_receipt(
    *,
    receipt: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    snapshot_payload: bytes,
    expected_archive_key: str,
    expected_producer_code_sha256: str,
    expected_producer_config_sha256: str,
) -> dict[str, Any]:
    if frozenset(receipt) != _RECEIPT_FIELDS:
        _integrity_error("FEATURE_PUBLICATION_RECEIPT_FIELDS_INVALID")
    if any(receipt.get(field_name) is not False for field_name in _AUTHORITY_FIELDS):
        _integrity_error("FEATURE_PUBLICATION_RECEIPT_AUTHORITY_INVALID")
    available_at = receipt.get("available_at")
    if type(available_at) is not str:
        _integrity_error("FEATURE_PUBLICATION_RECEIPT_AVAILABLE_AT_INVALID")
    expected = _build_receipt(
        snapshot=snapshot,
        snapshot_payload=snapshot_payload,
        snapshot_archive_key=expected_archive_key,
        available_at=available_at,
        producer_code_sha256=expected_producer_code_sha256,
        producer_config_sha256=expected_producer_config_sha256,
    )
    if dict(receipt) != expected:
        _integrity_error("FEATURE_PUBLICATION_RECEIPT_REDERIVATION_MISMATCH")
    return dict(receipt)


def derive_feature_publication_slot_bindings(
    snapshot_payload: str | bytes,
) -> tuple[Mapping[str, Any], ...]:
    """Re-derive the complete ordered per-slot audit leaves from exact bytes."""

    snapshot, snapshot_raw = _validated_snapshot_payload(snapshot_payload)
    bindings, _chain, _counts = _slot_bindings(
        snapshot=snapshot,
        snapshot_payload_sha256=_sha256_bytes(snapshot_raw),
        snapshot_features_sha256=_stable_sha256(snapshot["features"]),
    )
    return tuple(dict(binding) for binding in bindings)


def _keys(snapshot_id: str, symbol: str, timeframe: str) -> tuple[str, str, str, str]:
    archive_key = f"v2:features:snapshot:{snapshot_id}"
    latest_key = f"v2:features:latest:{symbol}:{timeframe}"
    receipt_key = f"{FEATURE_PUBLICATION_RECEIPT_KEY_PREFIX}{snapshot_id}"
    pointer_key = f"{FEATURE_PUBLICATION_RECEIPT_LATEST_KEY_PREFIX}{symbol}:{timeframe}"
    return archive_key, latest_key, receipt_key, pointer_key


def publish_and_verify_feature_snapshot(
    redis_client: RedisFeaturePublicationClient,
    snapshot_payload: str | bytes,
    *,
    archive_ttl_seconds: int,
    latest_ttl_seconds: int,
    producer_code_sha256: str,
    producer_config_sha256: str,
) -> VerifiedFeaturePublication:
    """Publish exact bytes, commit a receipt, then independently reopen both.

    A successful return authenticates the publication binding only.  All
    downstream authorization properties are deliberately false.
    """

    if (
        type(archive_ttl_seconds) is not int
        or type(latest_ttl_seconds) is not int
        or archive_ttl_seconds <= 0
        or latest_ttl_seconds <= 0
        or archive_ttl_seconds <= latest_ttl_seconds
    ):
        _validation_error("FEATURE_PUBLICATION_TTL_INVALID")
    snapshot, snapshot_raw = _validated_snapshot_payload(snapshot_payload)
    snapshot_id = cast(str, snapshot["feature_snapshot_id"])
    symbol = cast(str, snapshot["symbol"])
    timeframe = cast(str, snapshot["timeframe"])
    archive_key, latest_key, receipt_key, pointer_key = _keys(
        snapshot_id,
        symbol,
        timeframe,
    )

    prepared = _eval(
        redis_client,
        _PREPARE_PUBLICATION_LUA,
        (archive_key, latest_key, receipt_key),
        (
            snapshot_raw,
            archive_ttl_seconds,
            latest_ttl_seconds,
            MAX_SNAPSHOT_BYTES,
        ),
    )
    prepare_status = _eval_status(prepared, expected_size=3)
    if prepare_status != "PREPARED":
        _integrity_error("FEATURE_PUBLICATION_PREPARE_STATUS_INVALID")
    snapshot_available_at = _redis_clock(prepared[1], prepared[2])
    receipt = _build_receipt(
        snapshot=snapshot,
        snapshot_payload=snapshot_raw,
        snapshot_archive_key=archive_key,
        available_at=snapshot_available_at,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
    )
    receipt_raw = _canonical_json_bytes(receipt, maximum=MAX_RECEIPT_BYTES)

    committed = _eval(
        redis_client,
        _COMMIT_RECEIPT_LUA,
        (archive_key, receipt_key, pointer_key),
        (
            snapshot_raw,
            receipt_raw,
            latest_ttl_seconds,
            MAX_SNAPSHOT_BYTES,
            MAX_RECEIPT_BYTES,
            snapshot_id,
        ),
    )
    commit_status = _eval_status(committed, expected_size=3)
    if commit_status not in {"COMMITTED", "IDEMPOTENT"}:
        _integrity_error("FEATURE_PUBLICATION_COMMIT_STATUS_INVALID")
    receipt_postcommit_at = _redis_clock(committed[1], committed[2])

    reopened = _eval(
        redis_client,
        _REOPEN_PUBLICATION_LUA,
        (archive_key, receipt_key),
        (MAX_SNAPSHOT_BYTES, MAX_RECEIPT_BYTES),
    )
    reopen_status = _eval_status(reopened, expected_size=5)
    if reopen_status != "REOPENED":
        _integrity_error("FEATURE_PUBLICATION_REOPEN_STATUS_INVALID")
    reopened_snapshot, reopened_snapshot_raw = _validated_snapshot_payload(reopened[1])
    reopened_receipt = _parse_json_object(reopened[2], maximum=MAX_RECEIPT_BYTES)
    consumer_reopened_at = _redis_clock(reopened[3], reopened[4])

    if reopened_snapshot_raw != snapshot_raw or reopened_snapshot != snapshot:
        _integrity_error("FEATURE_PUBLICATION_SNAPSHOT_REOPEN_MISMATCH")
    validated_receipt = _validate_receipt(
        receipt=reopened_receipt,
        snapshot=reopened_snapshot,
        snapshot_payload=reopened_snapshot_raw,
        expected_archive_key=archive_key,
        expected_producer_code_sha256=producer_code_sha256,
        expected_producer_config_sha256=producer_config_sha256,
    )
    if validated_receipt != receipt:
        _integrity_error("FEATURE_PUBLICATION_RECEIPT_REOPEN_MISMATCH")

    available_clock = _parse_clock(snapshot_available_at)
    commit_clock = _parse_clock(receipt_postcommit_at)
    reopen_clock = _parse_clock(consumer_reopened_at)
    if not available_clock <= commit_clock <= reopen_clock:
        _integrity_error("FEATURE_PUBLICATION_POSTCOMMIT_CLOCK_ORDER_INVALID")

    return VerifiedFeaturePublication(
        feature_snapshot_id=snapshot_id,
        snapshot_archive_key=archive_key,
        receipt_key=receipt_key,
        latest_receipt_pointer_key=pointer_key,
        snapshot_available_at=snapshot_available_at,
        receipt_postcommit_observed_at=receipt_postcommit_at,
        consumer_reopened_at=consumer_reopened_at,
        receipt_sha256=cast(str, receipt["receipt_sha256"]),
        snapshot_payload_sha256=_sha256_bytes(snapshot_raw),
        slot_count=FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        complete_slot_coverage=True,
        publication_binding_authenticated=True,
        source_scope_complete=False,
        per_field_source_receipts_complete=False,
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        receipt=validated_receipt,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "FEATURE_PUBLICATION_RECEIPT_EVIDENCE_CLASSIFICATION",
    "FEATURE_PUBLICATION_RECEIPT_KEY_PREFIX",
    "FEATURE_PUBLICATION_RECEIPT_LATEST_KEY_PREFIX",
    "FEATURE_PUBLICATION_RECEIPT_SCHEMA_VERSION",
    "FeaturePublicationReceiptError",
    "FeaturePublicationReceiptIntegrityError",
    "FeaturePublicationReceiptTransportError",
    "FeaturePublicationReceiptValidationError",
    "VerifiedFeaturePublication",
    "derive_feature_publication_slot_bindings",
    "publish_and_verify_feature_snapshot",
]
