"""Post-commit publication proof for authenticated strategy-TA output.

This module is intentionally an unwired boundary.  It accepts only the
factory-authenticated deterministic TA transform, publishes one immutable
authoritative envelope, commits a receipt, and atomically reopens the exact
archive/latest/receipt/pointer tuple.  The Redis ``TIME`` sampled after the
archive and latest projection are written is the first truthful output
``available_at``.

The current strategy policy still contains unauthenticated market/economic
constants.  Those values are not accepted here.  Consequently the published
envelope is an explicit no-candidate hold and the paper assessment remains
rejected until a later factory-authenticated adaptive-policy artifact is
attached.  Publication integrity is not strategy, paper, or live authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, Protocol, cast

from v2.backend.app.services.strategy_supply.authenticated_strategy_ta_transform_v1 import (
    AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION,
    AuthenticatedStrategyTaTransformV1,
)

STRATEGY_OUTPUT_ENVELOPE_SCHEMA_VERSION: Final = "authenticated_strategy_output_envelope_v1"
STRATEGY_OUTPUT_PUBLICATION_RECEIPT_SCHEMA_VERSION: Final = (
    "authenticated_strategy_output_postcommit_receipt_v1"
)
STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION: Final = (
    "authenticated_strategy_output_paper_admission_v1"
)
STRATEGY_OUTPUT_EVIDENCE_CLASSIFICATION: Final = (
    "WRITER_AUTHENTICATED_TA_OUTPUT_POSTCOMMIT_REOPEN_VERIFIED_POLICY_HELD"
)
STRATEGY_OUTPUT_DOWNSTREAM_STATUS: Final = (
    "PUBLICATION_PROOF_ONLY_ADAPTIVE_POLICY_CANDIDATE_PAPER_AND_LIVE_AUTHORITY_HELD"
)

STRATEGY_OUTPUT_ARCHIVE_KEY_PREFIX: Final = "v2:strategy_supply:authenticated_output:archive:"
STRATEGY_OUTPUT_LATEST_KEY_PREFIX: Final = "v2:strategy_supply:authenticated_output:latest:"
STRATEGY_OUTPUT_RECEIPT_KEY_PREFIX: Final = "v2:strategy_supply:authenticated_output:receipt:"
STRATEGY_OUTPUT_RECEIPT_LATEST_KEY_PREFIX: Final = (
    "v2:strategy_supply:authenticated_output:receipt:latest:"
)

MAX_STRATEGY_OUTPUT_BYTES: Final = 4 * 1024 * 1024
MAX_STRATEGY_OUTPUT_RECEIPT_BYTES: Final = 256 * 1024
MAX_STRATEGY_OUTPUT_POINTER_BYTES: Final = 96
MAX_JSON_DEPTH: Final = 24
MAX_JSON_NODES: Final = 16_384
MAX_JSON_CONTAINER_ITEMS: Final = 4_096
MAX_JSON_STRING_BYTES: Final = 4 * 1024 * 1024

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_OUTPUT_ID_RE = re.compile(r"^v2_sout_[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]*[mhd]$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_AUTHORITY_FIELDS = (
    "strategy_output_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
)
_UPSTREAM_AUTHORITY_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    *_AUTHORITY_FIELDS,
)

_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "output_id",
        "symbol",
        "timeframe",
        "feature_cutoff",
        "max_source_available_at",
        "writer_publication_available_at",
        "capture_generated_at",
        "transform_generated_at",
        "generated_at",
        "upstream_strategy_ta_schema_version",
        "upstream_semantic_content_sha256",
        "upstream_semantic_content_byte_count",
        "upstream_audit_manifest_sha256",
        "upstream_exact_payload_sha256",
        "upstream_writer_receipt_sha256",
        "upstream_composite_manifest_sha256",
        "upstream_transform_implementation_sha256",
        "upstream_transform_configuration_sha256",
        "upstream_transform_module_code_sha256",
        "upstream_transform_dependency_code_root_sha256",
        "upstream_talib_environment_sha256",
        "reference_price",
        "indicator_count",
        "strategy_candidates",
        "authenticated_adaptive_policy_receipt_sha256",
        "market_performance_thresholds_applied",
        "unreceipted_external_economics_consumed",
        "available_at",
        "decision_time",
        "execution_time",
        *_AUTHORITY_FIELDS,
    }
)

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "output_id",
        "symbol",
        "timeframe",
        "archive_key",
        "latest_projection_key",
        "receipt_key",
        "latest_receipt_pointer_key",
        "output_payload_sha256",
        "output_payload_byte_count",
        "feature_cutoff",
        "generated_at",
        "available_at",
        "available_at_clock_source",
        "upstream_strategy_ta_semantic_sha256",
        "upstream_strategy_ta_audit_sha256",
        "upstream_writer_receipt_sha256",
        "upstream_composite_manifest_sha256",
        "publication_module_code_sha256",
        "publication_implementation_sha256",
        "publication_configuration_sha256",
        "postcommit_archive_reopen_required",
        "postcommit_latest_projection_reopen_required",
        "postcommit_receipt_reopen_required",
        "postcommit_pointer_reopen_required",
        "publication_binding_authenticated",
        "upstream_transform_authenticated",
        "authenticated_adaptive_policy_attached",
        "strategy_candidate_count",
        *_AUTHORITY_FIELDS,
        "receipt_sha256",
    }
)

_ADMISSION_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "output_id",
        "output_payload_sha256",
        "publication_receipt_sha256",
        "feature_cutoff",
        "generated_at",
        "available_at",
        "receipt_postcommit_observed_at",
        "consumer_reopened_at",
        "decision_time",
        "execution_time",
        "rejection_reasons",
        "assessed",
        "accepted",
        "paper_only",
        "authenticated_adaptive_policy_attached",
        "strategy_candidate_attached",
        "market_static_threshold_used",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
    }
)

_PUBLICATION_IMPLEMENTATION_MANIFEST = {
    "schema_version": "authenticated_strategy_output_publication_implementation_v1",
    "publication_protocol": "PREPARE_COMMIT_ATOMIC_FOUR_OBJECT_REOPEN",
    "authoritative_objects": ["immutable_archive", "immutable_receipt"],
    "mutable_projections": ["latest_output", "latest_receipt_pointer"],
    "availability_clock": "REDIS_TIME_AFTER_ARCHIVE_AND_LATEST_SET",
    "consumer_contract": "EXACT_ARCHIVE_LATEST_RECEIPT_POINTER_REOPEN",
    "policy_state": "AUTHENTICATED_ADAPTIVE_POLICY_NOT_ATTACHED",
}
_PUBLICATION_CONFIGURATION = {
    "schema_version": "authenticated_strategy_output_publication_configuration_v1",
    "maximum_output_bytes": MAX_STRATEGY_OUTPUT_BYTES,
    "maximum_receipt_bytes": MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    "maximum_pointer_bytes": MAX_STRATEGY_OUTPUT_POINTER_BYTES,
    "archive_ttl_must_exceed_receipt_ttl": True,
    "strategy_candidate_count": 0,
    "market_performance_thresholds": [],
    "unreceipted_external_economics": "FORBIDDEN",
    "execution_time": None,
    "live_execution_authorized": False,
}


def _static_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


STRATEGY_OUTPUT_PUBLICATION_IMPLEMENTATION_SHA256: Final = _static_sha256(
    _PUBLICATION_IMPLEMENTATION_MANIFEST
)
STRATEGY_OUTPUT_PUBLICATION_CONFIGURATION_SHA256: Final = _static_sha256(_PUBLICATION_CONFIGURATION)

_PREPARE_PUBLICATION_LUA = r"""
-- authenticated_strategy_output_prepare_v1
local archive_key = KEYS[1]
local latest_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local payload = ARGV[1]
local archive_ttl = tonumber(ARGV[2])
local receipt_ttl = tonumber(ARGV[3])
local max_output = tonumber(ARGV[4])
local feature_cutoff_us = tonumber(ARGV[5])
local generated_at_us = tonumber(ARGV[6])
local output_id = ARGV[7]
local max_pointer = tonumber(ARGV[8])

if not archive_ttl or not receipt_ttl or archive_ttl <= receipt_ttl
   or archive_ttl ~= math.floor(archive_ttl)
   or receipt_ttl ~= math.floor(receipt_ttl) then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL"}
end
if not feature_cutoff_us or feature_cutoff_us < 0
   or not generated_at_us or generated_at_us < feature_cutoff_us then
  return {"ERROR", "STRATEGY_OUTPUT_PREPUBLICATION_CLOCKS_INVALID"}
end
if string.len(payload) > max_output then
  return {"ERROR", "STRATEGY_OUTPUT_ARGUMENT_OVERSIZED"}
end
local before = redis.call("TIME")
local before_us = tonumber(before[1]) * 1000000 + tonumber(before[2])
if feature_cutoff_us > before_us then
  return {"ERROR", "STRATEGY_OUTPUT_FEATURE_CUTOFF_AFTER_REDIS_PREWRITE_CLOCK"}
end
if generated_at_us > before_us then
  return {"ERROR", "STRATEGY_OUTPUT_GENERATED_AT_AFTER_REDIS_PREWRITE_CLOCK"}
end
local archive_type = redis.call("TYPE", archive_key)["ok"]
if archive_type ~= "none" and archive_type ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_TYPE_INVALID"}
end
local latest_type = redis.call("TYPE", latest_key)["ok"]
if latest_type ~= "none" and latest_type ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_LATEST_TYPE_INVALID"}
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_TYPE_INVALID"}
end
if receipt_type == "string" then
  if archive_type ~= "string" then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_RECEIPT_ARCHIVE_MISSING"}
  end
  if latest_type ~= "string" then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_RECEIPT_LATEST_MISSING"}
  end
  if redis.call("STRLEN", archive_key) > max_output
     or redis.call("STRLEN", latest_key) > max_output then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_PAYLOAD_OVERSIZED"}
  end
  if redis.call("GET", archive_key) ~= payload
     or redis.call("GET", latest_key) ~= payload then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_PAYLOAD_IDENTITY_MISMATCH"}
  end
  if redis.call("TYPE", pointer_key)["ok"] ~= "string" then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_POINTER_IDENTITY_MISMATCH"}
  end
  if redis.call("STRLEN", pointer_key) > max_pointer
     or redis.call("GET", pointer_key) ~= output_id then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_POINTER_IDENTITY_MISMATCH"}
  end
  local receipt_remaining = redis.call("PTTL", receipt_key)
  if receipt_remaining <= 0 or redis.call("PTTL", archive_key) <= receipt_remaining then
    return {"ERROR", "STRATEGY_OUTPUT_EXISTING_TTL_ORDER_INVALID"}
  end
  local existing_observed = redis.call("TIME")
  return {"EXISTING", existing_observed[1], existing_observed[2]}
end
if archive_type == "string" then
  local archive_len = redis.call("STRLEN", archive_key)
  if archive_len > max_output then
    return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_OVERSIZED"}
  end
  if redis.call("GET", archive_key) ~= payload then
    return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_IDENTITY_CONFLICT"}
  end
  if redis.call("EXPIRE", archive_key, archive_ttl) ~= 1 then
    return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_TTL_REFRESH_FAILED"}
  end
else
  redis.call("SET", archive_key, payload, "EX", archive_ttl)
end
redis.call("SET", latest_key, payload, "EX", receipt_ttl)
if redis.call("PTTL", archive_key) <= receipt_ttl * 1000 then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
if redis.call("GET", archive_key) ~= payload then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_PREPARE_READBACK_MISMATCH"}
end
if redis.call("GET", latest_key) ~= payload then
  return {"ERROR", "STRATEGY_OUTPUT_LATEST_PREPARE_READBACK_MISMATCH"}
end
local observed = redis.call("TIME")
return {"PREPARED", observed[1], observed[2]}
"""

_COMMIT_RECEIPT_LUA = r"""
-- authenticated_strategy_output_commit_receipt_v1
local archive_key = KEYS[1]
local latest_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local output_payload = ARGV[1]
local receipt_payload = ARGV[2]
local ttl = tonumber(ARGV[3])
local max_output = tonumber(ARGV[4])
local max_receipt = tonumber(ARGV[5])
local output_id = ARGV[6]
local max_pointer = tonumber(ARGV[7])

if string.len(output_payload) > max_output then
  return {"ERROR", "STRATEGY_OUTPUT_ARGUMENT_OVERSIZED"}
end
if string.len(receipt_payload) > max_receipt then
  return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_ARGUMENT_OVERSIZED"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_MISSING"}
end
if redis.call("TYPE", latest_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_LATEST_MISSING"}
end
if redis.call("STRLEN", archive_key) > max_output
   or redis.call("STRLEN", latest_key) > max_output then
  return {"ERROR", "STRATEGY_OUTPUT_PERSISTED_PAYLOAD_OVERSIZED"}
end
if redis.call("GET", archive_key) ~= output_payload then
  return {"ERROR", "STRATEGY_OUTPUT_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("GET", latest_key) ~= output_payload then
  return {"ERROR", "STRATEGY_OUTPUT_LATEST_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("PTTL", archive_key) <= ttl * 1000 then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_TYPE_INVALID"}
end
if receipt_type == "string" then
  if redis.call("STRLEN", receipt_key) > max_receipt then
    return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_OVERSIZED"}
  end
  if redis.call("GET", receipt_key) ~= receipt_payload then
    return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_IDENTITY_CONFLICT"}
  end
else
  redis.call("SET", receipt_key, receipt_payload, "EX", ttl)
end
local pointer_type = redis.call("TYPE", pointer_key)["ok"]
if pointer_type ~= "none" and pointer_type ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_POINTER_TYPE_INVALID"}
end
if string.len(output_id) > max_pointer then
  return {"ERROR", "STRATEGY_OUTPUT_POINTER_ARGUMENT_OVERSIZED"}
end
redis.call("SET", pointer_key, output_id, "EX", ttl)
local observed = redis.call("TIME")
return {receipt_type == "string" and "IDEMPOTENT" or "COMMITTED", observed[1], observed[2]}
"""

_REOPEN_PUBLICATION_LUA = r"""
-- authenticated_strategy_output_reopen_v1
local archive_key = KEYS[1]
local latest_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local output_id = ARGV[1]
local max_output = tonumber(ARGV[2])
local max_receipt = tonumber(ARGV[3])
local max_pointer = tonumber(ARGV[4])

if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_ARCHIVE_MISSING"}
end
if redis.call("TYPE", latest_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_LATEST_MISSING"}
end
if redis.call("TYPE", receipt_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_MISSING"}
end
if redis.call("TYPE", pointer_key)["ok"] ~= "string" then
  return {"ERROR", "STRATEGY_OUTPUT_POINTER_MISSING"}
end
if redis.call("STRLEN", archive_key) > max_output
   or redis.call("STRLEN", latest_key) > max_output then
  return {"ERROR", "STRATEGY_OUTPUT_PERSISTED_PAYLOAD_OVERSIZED"}
end
if redis.call("STRLEN", receipt_key) > max_receipt then
  return {"ERROR", "STRATEGY_OUTPUT_RECEIPT_OVERSIZED"}
end
if redis.call("STRLEN", pointer_key) > max_pointer then
  return {"ERROR", "STRATEGY_OUTPUT_POINTER_OVERSIZED"}
end
local archive_payload = redis.call("GET", archive_key)
local latest_payload = redis.call("GET", latest_key)
local receipt_payload = redis.call("GET", receipt_key)
local pointer = redis.call("GET", pointer_key)
if pointer ~= output_id then
  return {"ERROR", "STRATEGY_OUTPUT_POINTER_IDENTITY_MISMATCH"}
end
local observed = redis.call("TIME")
return {"REOPENED", archive_payload, latest_payload, receipt_payload, pointer,
        observed[1], observed[2]}
"""


class RedisStrategyOutputClient(Protocol):
    """Minimal synchronous Redis surface for the atomic publication protocol."""

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class StrategyOutputPublicationV1Error(RuntimeError):
    """Base fail-closed output publication error."""


class StrategyOutputPublicationV1ValidationError(StrategyOutputPublicationV1Error):
    """A caller, clock, TTL, or authenticated input violates the contract."""


class StrategyOutputPublicationV1IntegrityError(StrategyOutputPublicationV1Error):
    """Persisted bytes, identities, clocks, or factory provenance do not bind."""


class StrategyOutputPublicationV1TransportError(StrategyOutputPublicationV1Error):
    """Redis did not execute the bounded atomic protocol."""


@dataclass(frozen=True, slots=True)
class VerifiedStrategyOutputPublicationV1:
    """Factory-issued result after exact four-object post-commit reopen."""

    output_id: str
    symbol: str
    timeframe: str
    archive_key: str
    latest_projection_key: str
    receipt_key: str
    latest_receipt_pointer_key: str
    feature_cutoff: str
    generated_at: str
    available_at: str
    receipt_postcommit_observed_at: str
    consumer_reopened_at: str
    output_payload_sha256: str
    output_payload_byte_count: int
    receipt_sha256: str
    upstream_semantic_content_sha256: str
    upstream_audit_manifest_sha256: str
    _envelope_json: str = field(repr=False, compare=False)
    _receipt_json: str = field(repr=False, compare=False)
    _upstream_transform: AuthenticatedStrategyTaTransformV1 = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    output_postcommit_readback_receipt_emitted: bool = field(default=True, init=False)
    publication_binding_authenticated: bool = field(default=True, init=False)
    upstream_transform_authenticated: bool = field(default=True, init=False)
    authenticated_adaptive_policy_attached: bool = field(default=False, init=False)
    strategy_candidate_count: int = field(default=0, init=False)
    strategy_output_authorized: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    decision_time: None = field(default=None, init=False)
    execution_time: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        _validate_publication_result(self)

    @property
    def envelope(self) -> dict[str, Any]:
        _validate_publication_result(self)
        return cast(dict[str, Any], json.loads(self._envelope_json))

    @property
    def receipt(self) -> dict[str, Any]:
        _validate_publication_result(self)
        return cast(dict[str, Any], json.loads(self._receipt_json))


@dataclass(frozen=True, slots=True)
class StrategyOutputPaperAdmissionV1:
    """Factory-issued paper assessment; this version must remain rejected."""

    output_id: str
    output_payload_sha256: str
    publication_receipt_sha256: str
    feature_cutoff: str
    generated_at: str
    available_at: str
    receipt_postcommit_observed_at: str
    consumer_reopened_at: str
    decision_time: str
    rejection_reasons: tuple[str, ...]
    evidence_sha256: str
    _evidence_json: str = field(repr=False, compare=False)
    _publication: VerifiedStrategyOutputPublicationV1 = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)
    assessed: bool = field(default=True, init=False)
    accepted: bool = field(default=False, init=False)
    paper_only: bool = field(default=True, init=False)
    authenticated_adaptive_policy_attached: bool = field(default=False, init=False)
    strategy_candidate_attached: bool = field(default=False, init=False)
    market_static_threshold_used: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    execution_time: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        _validate_admission_result(self)

    @property
    def evidence(self) -> dict[str, Any]:
        _validate_admission_result(self)
        return cast(dict[str, Any], json.loads(self._evidence_json))


def _validation_error(reason: str) -> NoReturn:
    raise StrategyOutputPublicationV1ValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise StrategyOutputPublicationV1IntegrityError(reason) from None


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
        _integrity_error("strategy_output_canonical_json_invalid")
    if not encoded or len(encoded) > maximum:
        _integrity_error("strategy_output_canonical_json_size_invalid")
    return encoded


def _json_budget(value: object, *, depth: int = 0) -> tuple[int, int]:
    if depth > MAX_JSON_DEPTH:
        _integrity_error("strategy_output_json_depth_exceeded")
    if value is None or type(value) in (bool, int, float):
        if type(value) is float and not math.isfinite(value):
            _integrity_error("strategy_output_json_nonfinite")
        return 1, 0
    if type(value) is str:
        return 1, len(cast(str, value).encode("utf-8"))
    if isinstance(value, Mapping):
        if len(value) > MAX_JSON_CONTAINER_ITEMS:
            _integrity_error("strategy_output_json_container_oversized")
        nodes = 1
        strings = 0
        for key, nested in value.items():
            if type(key) is not str:
                _integrity_error("strategy_output_json_key_invalid")
            strings += len(cast(str, key).encode("utf-8"))
            child_nodes, child_strings = _json_budget(nested, depth=depth + 1)
            nodes += child_nodes
            strings += child_strings
        return nodes, strings
    if isinstance(value, list):
        if len(value) > MAX_JSON_CONTAINER_ITEMS:
            _integrity_error("strategy_output_json_container_oversized")
        nodes = 1
        strings = 0
        for nested in value:
            child_nodes, child_strings = _json_budget(nested, depth=depth + 1)
            nodes += child_nodes
            strings += child_strings
        return nodes, strings
    _integrity_error("strategy_output_json_type_invalid")


def _parse_object(value: object, *, maximum: int) -> tuple[dict[str, Any], bytes]:
    if type(value) is bytes:
        raw = cast(bytes, value)
    elif type(value) is str:
        try:
            raw = cast(str, value).encode("ascii")
        except UnicodeEncodeError:
            _integrity_error("strategy_output_json_encoding_invalid")
    else:
        _integrity_error("strategy_output_json_transport_type_invalid")
    if not raw or len(raw) > maximum:
        _integrity_error("strategy_output_json_size_invalid")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, ValueError):
        _integrity_error("strategy_output_json_decode_invalid")
    if not isinstance(parsed, dict):
        _integrity_error("strategy_output_json_object_required")
    nodes, strings = _json_budget(parsed)
    if nodes > MAX_JSON_NODES or strings > MAX_JSON_STRING_BYTES:
        _integrity_error("strategy_output_json_budget_exceeded")
    canonical = _canonical_json_bytes(parsed, maximum=maximum)
    if not hmac.compare_digest(canonical, raw):
        _integrity_error("strategy_output_json_not_canonical")
    return cast(dict[str, Any], parsed), raw


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(cast(str, value)) is not None


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(cast(str, value)) is None:
        _validation_error(reason)
    try:
        parsed = datetime.strptime(cast(str, value), _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _validation_error(reason)
    if parsed.strftime(_CLOCK_FORMAT) != value:
        _validation_error(reason)
    return parsed


def _clock_to_us(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _sample_clock(clock: Callable[[], datetime]) -> str:
    if not callable(clock):
        _validation_error("strategy_output_decision_clock_not_callable")
    try:
        observed = clock()
    except Exception:  # noqa: BLE001 - hostile clock detail must not escape
        _validation_error("strategy_output_decision_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is None:
        _validation_error("strategy_output_decision_clock_invalid")
    return observed.astimezone(UTC).strftime(_CLOCK_FORMAT)


def _decode_scalar(value: object, *, reason: str) -> str:
    if type(value) is bytes:
        try:
            return cast(bytes, value).decode("ascii")
        except UnicodeDecodeError:
            _integrity_error(reason)
    if type(value) is str:
        return cast(str, value)
    if type(value) is int:
        return str(value)
    _integrity_error(reason)


def _redis_clock(seconds: object, microseconds: object) -> str:
    seconds_text = _decode_scalar(seconds, reason="strategy_output_redis_clock_invalid")
    micros_text = _decode_scalar(microseconds, reason="strategy_output_redis_clock_invalid")
    if not seconds_text.isdigit() or not micros_text.isdigit():
        _integrity_error("strategy_output_redis_clock_invalid")
    seconds_value = int(seconds_text)
    micros_value = int(micros_text)
    if seconds_value < 0 or not 0 <= micros_value < 1_000_000:
        _integrity_error("strategy_output_redis_clock_invalid")
    try:
        observed = datetime.fromtimestamp(seconds_value, tz=UTC).replace(microsecond=micros_value)
    except (OverflowError, OSError, ValueError):
        _integrity_error("strategy_output_redis_clock_invalid")
    return observed.strftime(_CLOCK_FORMAT)


def _module_code_sha256() -> str:
    try:
        source = Path(__file__).read_bytes()
    except OSError:
        _integrity_error("strategy_output_publication_module_code_unavailable")
    if not source:
        _integrity_error("strategy_output_publication_module_code_unavailable")
    return hashlib.sha256(source).hexdigest()


def _validated_transform(
    value: object,
) -> tuple[AuthenticatedStrategyTaTransformV1, Mapping[str, Any]]:
    if type(value) is not AuthenticatedStrategyTaTransformV1:
        _validation_error("strategy_output_authenticated_ta_transform_required")
    transform = cast(AuthenticatedStrategyTaTransformV1, value)
    try:
        semantic = transform.semantic_content
        _ = transform.audit_manifest
        indicators = transform.indicators
    except Exception as exc:
        raise StrategyOutputPublicationV1IntegrityError(
            "strategy_output_upstream_transform_revalidation_failed"
        ) from exc
    if (
        transform.schema_version != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION
        or transform.available_at is not None
        or transform.decision_time is not None
        or transform.execution_time is not None
        or transform.writer_authenticated_source_verified is not True
        or transform.deterministic_semantic_identity_verified is not True
        or transform.transform_dependencies_verified is not True
        or transform.semantic_and_audit_cas_reopened is not True
        or transform.unreceipted_external_economics_consumed is not False
        or transform.market_performance_thresholds_applied is not False
        or any(getattr(transform, name) is not False for name in _UPSTREAM_AUTHORITY_FIELDS)
        or not _valid_sha256(transform.semantic_content_sha256)
        or not _valid_sha256(transform.audit_manifest_sha256)
        or not _valid_sha256(transform.writer_receipt_sha256)
        or not _valid_sha256(transform.upstream_composite_manifest_sha256)
        or _SYMBOL_RE.fullmatch(transform.symbol) is None
        or _TIMEFRAME_RE.fullmatch(transform.timeframe) is None
        or transform.indicator_count != len(indicators)
        or not indicators
    ):
        _integrity_error("strategy_output_upstream_transform_contract_invalid")
    _parse_clock(transform.feature_cutoff, reason="strategy_output_feature_cutoff_invalid")
    return transform, semantic


def _build_envelope(
    transform: AuthenticatedStrategyTaTransformV1,
    *,
    generated_at: str,
) -> dict[str, Any]:
    transform, _semantic = _validated_transform(transform)
    generated = _parse_clock(
        generated_at,
        reason="strategy_output_generated_at_invalid",
    )
    upstream_clocks = tuple(
        _parse_clock(value, reason="strategy_output_upstream_clock_invalid")
        for value in (
            transform.feature_cutoff,
            transform.max_source_available_at,
            transform.writer_publication_available_at,
            transform.capture_generated_at,
            transform.transform_generated_at,
        )
    )
    if any(left > right for left, right in zip(upstream_clocks, upstream_clocks[1:], strict=False)):
        _integrity_error("strategy_output_upstream_clock_order_invalid")
    if upstream_clocks[-1] > generated:
        _validation_error("strategy_output_generated_before_transform")
    unsigned: dict[str, Any] = {
        "schema_version": STRATEGY_OUTPUT_ENVELOPE_SCHEMA_VERSION,
        "evidence_classification": STRATEGY_OUTPUT_EVIDENCE_CLASSIFICATION,
        "downstream_status": STRATEGY_OUTPUT_DOWNSTREAM_STATUS,
        "symbol": transform.symbol,
        "timeframe": transform.timeframe,
        "feature_cutoff": transform.feature_cutoff,
        "max_source_available_at": transform.max_source_available_at,
        "writer_publication_available_at": transform.writer_publication_available_at,
        "capture_generated_at": transform.capture_generated_at,
        "transform_generated_at": transform.transform_generated_at,
        "generated_at": generated_at,
        "upstream_strategy_ta_schema_version": transform.schema_version,
        "upstream_semantic_content_sha256": transform.semantic_content_sha256,
        "upstream_semantic_content_byte_count": transform.semantic_content_byte_count,
        "upstream_audit_manifest_sha256": transform.audit_manifest_sha256,
        "upstream_exact_payload_sha256": transform.exact_payload_sha256,
        "upstream_writer_receipt_sha256": transform.writer_receipt_sha256,
        "upstream_composite_manifest_sha256": transform.upstream_composite_manifest_sha256,
        "upstream_transform_implementation_sha256": transform.implementation_sha256,
        "upstream_transform_configuration_sha256": transform.configuration_sha256,
        "upstream_transform_module_code_sha256": transform.module_code_sha256,
        "upstream_transform_dependency_code_root_sha256": (transform.dependency_code_root_sha256),
        "upstream_talib_environment_sha256": transform.deployed_talib_environment_sha256,
        "reference_price": transform.reference_price,
        "indicator_count": transform.indicator_count,
        "strategy_candidates": [],
        "authenticated_adaptive_policy_receipt_sha256": None,
        "market_performance_thresholds_applied": [],
        "unreceipted_external_economics_consumed": [],
        "available_at": None,
        "decision_time": None,
        "execution_time": None,
        "strategy_output_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
    }
    identity_sha256 = hashlib.sha256(
        _canonical_json_bytes(unsigned, maximum=MAX_STRATEGY_OUTPUT_BYTES)
    ).hexdigest()
    return {**unsigned, "output_id": f"v2_sout_{identity_sha256}"}


def _keys(output_id: str, symbol: str, timeframe: str) -> tuple[str, str, str, str]:
    return (
        f"{STRATEGY_OUTPUT_ARCHIVE_KEY_PREFIX}{output_id}",
        f"{STRATEGY_OUTPUT_LATEST_KEY_PREFIX}{symbol}:{timeframe}",
        f"{STRATEGY_OUTPUT_RECEIPT_KEY_PREFIX}{output_id}",
        f"{STRATEGY_OUTPUT_RECEIPT_LATEST_KEY_PREFIX}{symbol}:{timeframe}",
    )


def _build_receipt(
    *,
    transform: AuthenticatedStrategyTaTransformV1,
    envelope: Mapping[str, Any],
    envelope_bytes: bytes,
    archive_key: str,
    latest_key: str,
    receipt_key: str,
    pointer_key: str,
    generated_at: str,
    available_at: str,
) -> dict[str, Any]:
    unsigned = {
        "schema_version": STRATEGY_OUTPUT_PUBLICATION_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": STRATEGY_OUTPUT_EVIDENCE_CLASSIFICATION,
        "downstream_status": STRATEGY_OUTPUT_DOWNSTREAM_STATUS,
        "output_id": envelope["output_id"],
        "symbol": transform.symbol,
        "timeframe": transform.timeframe,
        "archive_key": archive_key,
        "latest_projection_key": latest_key,
        "receipt_key": receipt_key,
        "latest_receipt_pointer_key": pointer_key,
        "output_payload_sha256": hashlib.sha256(envelope_bytes).hexdigest(),
        "output_payload_byte_count": len(envelope_bytes),
        "feature_cutoff": transform.feature_cutoff,
        "generated_at": generated_at,
        "available_at": available_at,
        "available_at_clock_source": "REDIS_TIME_AFTER_ATOMIC_ARCHIVE_AND_LATEST_SET",
        "upstream_strategy_ta_semantic_sha256": transform.semantic_content_sha256,
        "upstream_strategy_ta_audit_sha256": transform.audit_manifest_sha256,
        "upstream_writer_receipt_sha256": transform.writer_receipt_sha256,
        "upstream_composite_manifest_sha256": transform.upstream_composite_manifest_sha256,
        "publication_module_code_sha256": _module_code_sha256(),
        "publication_implementation_sha256": (STRATEGY_OUTPUT_PUBLICATION_IMPLEMENTATION_SHA256),
        "publication_configuration_sha256": (STRATEGY_OUTPUT_PUBLICATION_CONFIGURATION_SHA256),
        "postcommit_archive_reopen_required": True,
        "postcommit_latest_projection_reopen_required": True,
        "postcommit_receipt_reopen_required": True,
        "postcommit_pointer_reopen_required": True,
        "publication_binding_authenticated": True,
        "upstream_transform_authenticated": True,
        "authenticated_adaptive_policy_attached": False,
        "strategy_candidate_count": 0,
        "strategy_output_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
    }
    return {**unsigned, "receipt_sha256": _static_sha256(unsigned)}


def _eval(
    client: RedisStrategyOutputClient,
    script: str,
    keys: Sequence[str],
    args: Sequence[object],
) -> list[object]:
    try:
        result = client.eval(script, len(keys), *keys, *args)
    except Exception as exc:  # noqa: BLE001 - transport detail is contained
        raise StrategyOutputPublicationV1TransportError(
            "strategy_output_redis_eval_failed"
        ) from exc
    if not isinstance(result, list | tuple):
        raise StrategyOutputPublicationV1TransportError("strategy_output_redis_reply_invalid")
    return list(result)


def _eval_status(result: Sequence[object], *, expected_size: int) -> str:
    if not result:
        raise StrategyOutputPublicationV1TransportError("strategy_output_redis_reply_empty")
    status = _decode_scalar(result[0], reason="strategy_output_redis_status_invalid")
    if status == "ERROR":
        if len(result) != 2:
            raise StrategyOutputPublicationV1TransportError(
                "strategy_output_redis_error_reply_invalid"
            )
        _integrity_error(
            _decode_scalar(result[1], reason="strategy_output_redis_error_reason_invalid")
        )
    if len(result) != expected_size:
        raise StrategyOutputPublicationV1TransportError("strategy_output_redis_reply_size_invalid")
    return status


def _reopen_exact_publication(
    redis_client: RedisStrategyOutputClient,
    *,
    archive_key: str,
    latest_key: str,
    receipt_key: str,
    pointer_key: str,
    output_id: str,
    expected_envelope: Mapping[str, Any],
    expected_envelope_bytes: bytes,
) -> tuple[dict[str, Any], bytes, str]:
    reopened = _eval(
        redis_client,
        _REOPEN_PUBLICATION_LUA,
        (archive_key, latest_key, receipt_key, pointer_key),
        (
            output_id,
            MAX_STRATEGY_OUTPUT_BYTES,
            MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
            MAX_STRATEGY_OUTPUT_POINTER_BYTES,
        ),
    )
    if _eval_status(reopened, expected_size=7) != "REOPENED":
        _integrity_error("strategy_output_publication_reopen_status_invalid")
    reopened_envelope, reopened_envelope_bytes = _parse_object(
        reopened[1],
        maximum=MAX_STRATEGY_OUTPUT_BYTES,
    )
    reopened_latest, reopened_latest_bytes = _parse_object(
        reopened[2],
        maximum=MAX_STRATEGY_OUTPUT_BYTES,
    )
    reopened_receipt, reopened_receipt_bytes = _parse_object(
        reopened[3],
        maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    )
    reopened_pointer = _decode_scalar(
        reopened[4],
        reason="strategy_output_publication_pointer_invalid",
    )
    consumer_reopened_at = _redis_clock(reopened[5], reopened[6])
    if (
        reopened_envelope != expected_envelope
        or reopened_latest != expected_envelope
        or not hmac.compare_digest(reopened_envelope_bytes, expected_envelope_bytes)
        or not hmac.compare_digest(reopened_latest_bytes, expected_envelope_bytes)
        or reopened_pointer != output_id
    ):
        _integrity_error("strategy_output_publication_postcommit_reopen_mismatch")
    return reopened_receipt, reopened_receipt_bytes, consumer_reopened_at


def _publication_result(
    *,
    transform: AuthenticatedStrategyTaTransformV1,
    envelope: Mapping[str, Any],
    envelope_bytes: bytes,
    receipt: Mapping[str, Any],
    receipt_bytes: bytes,
    archive_key: str,
    latest_key: str,
    receipt_key: str,
    pointer_key: str,
    generated_at: str,
    available_at: str,
    receipt_postcommit_observed_at: str,
    consumer_reopened_at: str,
) -> VerifiedStrategyOutputPublicationV1:
    return VerifiedStrategyOutputPublicationV1(
        output_id=cast(str, envelope["output_id"]),
        symbol=transform.symbol,
        timeframe=transform.timeframe,
        archive_key=archive_key,
        latest_projection_key=latest_key,
        receipt_key=receipt_key,
        latest_receipt_pointer_key=pointer_key,
        feature_cutoff=transform.feature_cutoff,
        generated_at=generated_at,
        available_at=available_at,
        receipt_postcommit_observed_at=receipt_postcommit_observed_at,
        consumer_reopened_at=consumer_reopened_at,
        output_payload_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
        output_payload_byte_count=len(envelope_bytes),
        receipt_sha256=cast(str, receipt["receipt_sha256"]),
        upstream_semantic_content_sha256=transform.semantic_content_sha256,
        upstream_audit_manifest_sha256=transform.audit_manifest_sha256,
        _envelope_json=envelope_bytes.decode("ascii"),
        _receipt_json=receipt_bytes.decode("ascii"),
        _upstream_transform=transform,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _validate_publication_result(result: object) -> None:
    if type(result) is not VerifiedStrategyOutputPublicationV1:
        _integrity_error("strategy_output_publication_exact_result_type_required")
    publication = cast(VerifiedStrategyOutputPublicationV1, result)
    if publication._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("strategy_output_publication_factory_construction_required")
    transform, _semantic = _validated_transform(publication._upstream_transform)
    expected_envelope = _build_envelope(
        transform,
        generated_at=publication.generated_at,
    )
    envelope_bytes = _canonical_json_bytes(
        expected_envelope,
        maximum=MAX_STRATEGY_OUTPUT_BYTES,
    )
    try:
        retained_envelope = publication._envelope_json.encode("ascii")
        retained_receipt = publication._receipt_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("strategy_output_publication_retained_json_invalid")
    if not hmac.compare_digest(retained_envelope, envelope_bytes):
        _integrity_error("strategy_output_publication_envelope_binding_invalid")
    envelope, parsed_envelope_bytes = _parse_object(
        retained_envelope,
        maximum=MAX_STRATEGY_OUTPUT_BYTES,
    )
    receipt, parsed_receipt_bytes = _parse_object(
        retained_receipt,
        maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    )
    if frozenset(envelope) != _ENVELOPE_FIELDS or envelope != expected_envelope:
        _integrity_error("strategy_output_publication_envelope_contract_invalid")
    output_id = cast(str, envelope["output_id"])
    if _OUTPUT_ID_RE.fullmatch(output_id) is None:
        _integrity_error("strategy_output_publication_output_id_invalid")
    archive_key, latest_key, receipt_key, pointer_key = _keys(
        output_id,
        transform.symbol,
        transform.timeframe,
    )
    expected_receipt = _build_receipt(
        transform=transform,
        envelope=envelope,
        envelope_bytes=parsed_envelope_bytes,
        archive_key=archive_key,
        latest_key=latest_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        generated_at=publication.generated_at,
        available_at=publication.available_at,
    )
    if (
        frozenset(receipt) != _RECEIPT_FIELDS
        or receipt != expected_receipt
        or not hmac.compare_digest(
            parsed_receipt_bytes,
            _canonical_json_bytes(
                expected_receipt,
                maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
            ),
        )
    ):
        _integrity_error("strategy_output_publication_receipt_binding_invalid")
    cutoff = _parse_clock(
        publication.feature_cutoff,
        reason="strategy_output_publication_feature_cutoff_invalid",
    )
    generated = _parse_clock(
        publication.generated_at,
        reason="strategy_output_publication_generated_at_invalid",
    )
    available = _parse_clock(
        publication.available_at,
        reason="strategy_output_publication_available_at_invalid",
    )
    committed = _parse_clock(
        publication.receipt_postcommit_observed_at,
        reason="strategy_output_publication_commit_clock_invalid",
    )
    reopened = _parse_clock(
        publication.consumer_reopened_at,
        reason="strategy_output_publication_reopen_clock_invalid",
    )
    if not cutoff <= generated <= available <= committed <= reopened:
        _integrity_error("strategy_output_publication_clock_order_invalid")
    if (
        publication.output_id != output_id
        or publication.symbol != transform.symbol
        or publication.timeframe != transform.timeframe
        or publication.archive_key != archive_key
        or publication.latest_projection_key != latest_key
        or publication.receipt_key != receipt_key
        or publication.latest_receipt_pointer_key != pointer_key
        or publication.feature_cutoff != transform.feature_cutoff
        or publication.generated_at != envelope["generated_at"]
        or publication.output_payload_sha256 != hashlib.sha256(parsed_envelope_bytes).hexdigest()
        or publication.output_payload_byte_count != len(parsed_envelope_bytes)
        or publication.receipt_sha256 != receipt["receipt_sha256"]
        or publication.upstream_semantic_content_sha256 != transform.semantic_content_sha256
        or publication.upstream_audit_manifest_sha256 != transform.audit_manifest_sha256
        or publication.output_postcommit_readback_receipt_emitted is not True
        or publication.publication_binding_authenticated is not True
        or publication.upstream_transform_authenticated is not True
        or publication.authenticated_adaptive_policy_attached is not False
        or publication.strategy_candidate_count != 0
        or publication.decision_time is not None
        or publication.execution_time is not None
        or any(getattr(publication, name) is not False for name in _AUTHORITY_FIELDS)
    ):
        _integrity_error("strategy_output_publication_result_binding_invalid")


def _paper_rejection_reasons(
    publication: VerifiedStrategyOutputPublicationV1,
    decision_time: str,
) -> tuple[str, ...]:
    cutoff = _parse_clock(
        publication.feature_cutoff,
        reason="strategy_output_admission_cutoff_invalid",
    )
    available = _parse_clock(
        publication.available_at,
        reason="strategy_output_admission_available_at_invalid",
    )
    committed = _parse_clock(
        publication.receipt_postcommit_observed_at,
        reason="strategy_output_admission_commit_clock_invalid",
    )
    reopened = _parse_clock(
        publication.consumer_reopened_at,
        reason="strategy_output_admission_reopen_clock_invalid",
    )
    decision = _parse_clock(
        decision_time,
        reason="strategy_output_admission_decision_time_invalid",
    )
    reasons = {
        "authenticated_adaptive_strategy_policy_missing",
        "strategy_candidate_missing",
    }
    if cutoff > available:
        reasons.add("feature_cutoff_after_output_available_at")
    if available > decision:
        reasons.add("output_available_at_after_decision_time")
    if committed > decision:
        reasons.add("publication_receipt_committed_after_decision_time")
    if reopened > decision:
        reasons.add("publication_reopened_after_decision_time")
    return tuple(sorted(reasons))


def _validate_admission_result(result: object) -> None:
    if type(result) is not StrategyOutputPaperAdmissionV1:
        _integrity_error("strategy_output_admission_exact_result_type_required")
    admission = cast(StrategyOutputPaperAdmissionV1, result)
    if admission._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("strategy_output_admission_factory_construction_required")
    _validate_publication_result(admission._publication)
    try:
        evidence_bytes = admission._evidence_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("strategy_output_admission_evidence_json_invalid")
    evidence, canonical = _parse_object(
        evidence_bytes,
        maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    )
    expected_reasons = _paper_rejection_reasons(
        admission._publication,
        admission.decision_time,
    )
    if (
        admission.output_id != admission._publication.output_id
        or admission.output_payload_sha256 != admission._publication.output_payload_sha256
        or admission.publication_receipt_sha256 != admission._publication.receipt_sha256
        or admission.feature_cutoff != admission._publication.feature_cutoff
        or admission.generated_at != admission._publication.generated_at
        or admission.available_at != admission._publication.available_at
        or admission.receipt_postcommit_observed_at
        != admission._publication.receipt_postcommit_observed_at
        or admission.consumer_reopened_at != admission._publication.consumer_reopened_at
        or admission.rejection_reasons != expected_reasons
        or admission.evidence_sha256 != hashlib.sha256(canonical).hexdigest()
        or frozenset(evidence) != _ADMISSION_EVIDENCE_FIELDS
        or evidence.get("schema_version") != STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION
        or evidence.get("output_id") != admission.output_id
        or evidence.get("output_payload_sha256") != admission.output_payload_sha256
        or evidence.get("publication_receipt_sha256") != admission.publication_receipt_sha256
        or evidence.get("feature_cutoff") != admission.feature_cutoff
        or evidence.get("generated_at") != admission.generated_at
        or evidence.get("available_at") != admission.available_at
        or evidence.get("receipt_postcommit_observed_at")
        != admission.receipt_postcommit_observed_at
        or evidence.get("consumer_reopened_at") != admission.consumer_reopened_at
        or evidence.get("decision_time") != admission.decision_time
        or evidence.get("execution_time") is not None
        or evidence.get("rejection_reasons") != list(expected_reasons)
        or evidence.get("assessed") is not True
        or evidence.get("accepted") is not False
        or evidence.get("paper_only") is not True
        or evidence.get("authenticated_adaptive_policy_attached") is not False
        or evidence.get("strategy_candidate_attached") is not False
        or evidence.get("market_static_threshold_used") is not False
        or any(evidence.get(name) is not False for name in _AUTHORITY_FIELDS[2:])
        or admission.assessed is not True
        or admission.accepted is not False
        or admission.paper_only is not True
        or admission.authenticated_adaptive_policy_attached is not False
        or admission.strategy_candidate_attached is not False
        or admission.market_static_threshold_used is not False
        or admission.paper_trading_authorized is not False
        or admission.live_execution_authorized is not False
        or admission.order_submission_authorized is not False
        or admission.execution_time is not None
    ):
        _integrity_error("strategy_output_admission_result_binding_invalid")
    _parse_clock(admission.feature_cutoff, reason="strategy_output_admission_cutoff_invalid")
    _parse_clock(admission.generated_at, reason="strategy_output_admission_generated_at_invalid")
    _parse_clock(admission.available_at, reason="strategy_output_admission_available_at_invalid")
    _parse_clock(
        admission.receipt_postcommit_observed_at,
        reason="strategy_output_admission_commit_clock_invalid",
    )
    _parse_clock(
        admission.consumer_reopened_at,
        reason="strategy_output_admission_reopen_clock_invalid",
    )
    _parse_clock(admission.decision_time, reason="strategy_output_admission_decision_time_invalid")


def publish_and_verify_authenticated_strategy_output_v1(
    redis_client: RedisStrategyOutputClient,
    transform: AuthenticatedStrategyTaTransformV1,
    *,
    archive_ttl_seconds: int,
    receipt_ttl_seconds: int,
    publication_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> VerifiedStrategyOutputPublicationV1:
    """Publish the exact held output, receipt it, then reopen all four objects."""

    if (
        type(archive_ttl_seconds) is not int
        or type(receipt_ttl_seconds) is not int
        or archive_ttl_seconds <= 0
        or receipt_ttl_seconds <= 0
        or archive_ttl_seconds <= receipt_ttl_seconds
    ):
        _validation_error("strategy_output_publication_ttl_invalid")
    transform, _semantic = _validated_transform(transform)
    generated_at = _sample_clock(publication_clock)
    envelope = _build_envelope(transform, generated_at=generated_at)
    if frozenset(envelope) != _ENVELOPE_FIELDS:
        _integrity_error("strategy_output_publication_envelope_fields_invalid")
    envelope_bytes = _canonical_json_bytes(
        envelope,
        maximum=MAX_STRATEGY_OUTPUT_BYTES,
    )
    output_id = cast(str, envelope["output_id"])
    archive_key, latest_key, receipt_key, pointer_key = _keys(
        output_id,
        transform.symbol,
        transform.timeframe,
    )
    cutoff = _parse_clock(
        transform.feature_cutoff,
        reason="strategy_output_feature_cutoff_invalid",
    )
    prepared = _eval(
        redis_client,
        _PREPARE_PUBLICATION_LUA,
        (archive_key, latest_key, receipt_key, pointer_key),
        (
            envelope_bytes,
            archive_ttl_seconds,
            receipt_ttl_seconds,
            MAX_STRATEGY_OUTPUT_BYTES,
            _clock_to_us(cutoff),
            _clock_to_us(
                _parse_clock(
                    generated_at,
                    reason="strategy_output_generated_at_invalid",
                )
            ),
            output_id,
            MAX_STRATEGY_OUTPUT_POINTER_BYTES,
        ),
    )
    prepare_status = _eval_status(prepared, expected_size=3)
    if prepare_status not in {"PREPARED", "EXISTING"}:
        _integrity_error("strategy_output_publication_prepare_status_invalid")
    prepare_observed_at = _redis_clock(prepared[1], prepared[2])
    if prepare_status == "EXISTING":
        reopened_receipt, reopened_receipt_bytes, consumer_reopened_at = _reopen_exact_publication(
            redis_client,
            archive_key=archive_key,
            latest_key=latest_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            output_id=output_id,
            expected_envelope=envelope,
            expected_envelope_bytes=envelope_bytes,
        )
        available_value = reopened_receipt.get("available_at")
        if type(available_value) is not str:
            _integrity_error("strategy_output_existing_receipt_available_at_invalid")
        available_at = cast(str, available_value)
        expected_receipt = _build_receipt(
            transform=transform,
            envelope=envelope,
            envelope_bytes=envelope_bytes,
            archive_key=archive_key,
            latest_key=latest_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            generated_at=generated_at,
            available_at=available_at,
        )
        expected_receipt_bytes = _canonical_json_bytes(
            expected_receipt,
            maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
        )
        if reopened_receipt != expected_receipt or not hmac.compare_digest(
            reopened_receipt_bytes, expected_receipt_bytes
        ):
            _integrity_error("strategy_output_existing_receipt_binding_invalid")
        cutoff_clock = _parse_clock(
            transform.feature_cutoff,
            reason="strategy_output_publication_feature_cutoff_invalid",
        )
        generated_clock = _parse_clock(
            generated_at,
            reason="strategy_output_publication_generated_at_invalid",
        )
        available_clock = _parse_clock(
            available_at,
            reason="strategy_output_publication_available_at_invalid",
        )
        existing_observed_clock = _parse_clock(
            prepare_observed_at,
            reason="strategy_output_publication_existing_clock_invalid",
        )
        reopen_clock = _parse_clock(
            consumer_reopened_at,
            reason="strategy_output_publication_reopen_clock_invalid",
        )
        if not (
            cutoff_clock
            <= generated_clock
            <= available_clock
            <= existing_observed_clock
            <= reopen_clock
        ):
            _integrity_error("strategy_output_publication_clock_order_invalid")
        return _publication_result(
            transform=transform,
            envelope=envelope,
            envelope_bytes=envelope_bytes,
            receipt=expected_receipt,
            receipt_bytes=expected_receipt_bytes,
            archive_key=archive_key,
            latest_key=latest_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            generated_at=generated_at,
            available_at=available_at,
            receipt_postcommit_observed_at=prepare_observed_at,
            consumer_reopened_at=consumer_reopened_at,
        )
    available_at = prepare_observed_at
    receipt = _build_receipt(
        transform=transform,
        envelope=envelope,
        envelope_bytes=envelope_bytes,
        archive_key=archive_key,
        latest_key=latest_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        generated_at=generated_at,
        available_at=available_at,
    )
    receipt_bytes = _canonical_json_bytes(
        receipt,
        maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    )
    committed = _eval(
        redis_client,
        _COMMIT_RECEIPT_LUA,
        (archive_key, latest_key, receipt_key, pointer_key),
        (
            envelope_bytes,
            receipt_bytes,
            receipt_ttl_seconds,
            MAX_STRATEGY_OUTPUT_BYTES,
            MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
            output_id,
            MAX_STRATEGY_OUTPUT_POINTER_BYTES,
        ),
    )
    if _eval_status(committed, expected_size=3) not in {"COMMITTED", "IDEMPOTENT"}:
        _integrity_error("strategy_output_publication_commit_status_invalid")
    receipt_postcommit_observed_at = _redis_clock(committed[1], committed[2])
    reopened_receipt, reopened_receipt_bytes, consumer_reopened_at = _reopen_exact_publication(
        redis_client,
        archive_key=archive_key,
        latest_key=latest_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        output_id=output_id,
        expected_envelope=envelope,
        expected_envelope_bytes=envelope_bytes,
    )
    if reopened_receipt != receipt or not hmac.compare_digest(
        reopened_receipt_bytes, receipt_bytes
    ):
        _integrity_error("strategy_output_publication_postcommit_reopen_mismatch")
    cutoff_clock = _parse_clock(
        transform.feature_cutoff,
        reason="strategy_output_publication_feature_cutoff_invalid",
    )
    generated_clock = _parse_clock(
        generated_at,
        reason="strategy_output_publication_generated_at_invalid",
    )
    available_clock = _parse_clock(
        available_at,
        reason="strategy_output_publication_available_at_invalid",
    )
    commit_clock = _parse_clock(
        receipt_postcommit_observed_at,
        reason="strategy_output_publication_commit_clock_invalid",
    )
    reopen_clock = _parse_clock(
        consumer_reopened_at,
        reason="strategy_output_publication_reopen_clock_invalid",
    )
    if not cutoff_clock <= generated_clock <= available_clock <= commit_clock <= reopen_clock:
        _integrity_error("strategy_output_publication_clock_order_invalid")
    return _publication_result(
        transform=transform,
        envelope=envelope,
        envelope_bytes=envelope_bytes,
        receipt=receipt,
        receipt_bytes=receipt_bytes,
        archive_key=archive_key,
        latest_key=latest_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        generated_at=generated_at,
        available_at=available_at,
        receipt_postcommit_observed_at=receipt_postcommit_observed_at,
        consumer_reopened_at=consumer_reopened_at,
    )


def assess_authenticated_strategy_output_for_paper_v1(
    publication: VerifiedStrategyOutputPublicationV1,
    *,
    decision_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> StrategyOutputPaperAdmissionV1:
    """Assess temporal eligibility while retaining the adaptive-policy hold.

    This version cannot return ``accepted=True``.  Its purpose is to make the
    paper boundary explicit and hash-bound without laundering the current
    static legacy policy into an authenticated candidate.
    """

    _validate_publication_result(publication)
    decision_time = _sample_clock(decision_clock)
    ordered_reasons = _paper_rejection_reasons(publication, decision_time)
    evidence: dict[str, Any] = {
        "schema_version": STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION,
        "output_id": publication.output_id,
        "output_payload_sha256": publication.output_payload_sha256,
        "publication_receipt_sha256": publication.receipt_sha256,
        "feature_cutoff": publication.feature_cutoff,
        "generated_at": publication.generated_at,
        "available_at": publication.available_at,
        "receipt_postcommit_observed_at": publication.receipt_postcommit_observed_at,
        "consumer_reopened_at": publication.consumer_reopened_at,
        "decision_time": decision_time,
        "execution_time": None,
        "rejection_reasons": list(ordered_reasons),
        "assessed": True,
        "accepted": False,
        "paper_only": True,
        "authenticated_adaptive_policy_attached": False,
        "strategy_candidate_attached": False,
        "market_static_threshold_used": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
    }
    evidence_bytes = _canonical_json_bytes(
        evidence,
        maximum=MAX_STRATEGY_OUTPUT_RECEIPT_BYTES,
    )
    return StrategyOutputPaperAdmissionV1(
        output_id=publication.output_id,
        output_payload_sha256=publication.output_payload_sha256,
        publication_receipt_sha256=publication.receipt_sha256,
        feature_cutoff=publication.feature_cutoff,
        generated_at=publication.generated_at,
        available_at=publication.available_at,
        receipt_postcommit_observed_at=publication.receipt_postcommit_observed_at,
        consumer_reopened_at=publication.consumer_reopened_at,
        decision_time=decision_time,
        rejection_reasons=ordered_reasons,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        _evidence_json=evidence_bytes.decode("ascii"),
        _publication=publication,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "STRATEGY_OUTPUT_ARCHIVE_KEY_PREFIX",
    "STRATEGY_OUTPUT_DOWNSTREAM_STATUS",
    "STRATEGY_OUTPUT_ENVELOPE_SCHEMA_VERSION",
    "STRATEGY_OUTPUT_EVIDENCE_CLASSIFICATION",
    "STRATEGY_OUTPUT_LATEST_KEY_PREFIX",
    "STRATEGY_OUTPUT_PAPER_ADMISSION_SCHEMA_VERSION",
    "STRATEGY_OUTPUT_PUBLICATION_CONFIGURATION_SHA256",
    "STRATEGY_OUTPUT_PUBLICATION_IMPLEMENTATION_SHA256",
    "STRATEGY_OUTPUT_PUBLICATION_RECEIPT_SCHEMA_VERSION",
    "STRATEGY_OUTPUT_RECEIPT_KEY_PREFIX",
    "STRATEGY_OUTPUT_RECEIPT_LATEST_KEY_PREFIX",
    "StrategyOutputPaperAdmissionV1",
    "StrategyOutputPublicationV1Error",
    "StrategyOutputPublicationV1IntegrityError",
    "StrategyOutputPublicationV1TransportError",
    "StrategyOutputPublicationV1ValidationError",
    "VerifiedStrategyOutputPublicationV1",
    "assess_authenticated_strategy_output_for_paper_v1",
    "publish_and_verify_authenticated_strategy_output_v1",
]
