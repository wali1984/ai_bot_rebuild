"""Versioned, non-consumable provenance for paper-position membership state.

This module is deliberately not wired into a runtime.  It builds a bounded
membership generation from the exact legacy payload and the exact authoritative
``v2:paper:session`` payload supplied by a future caller.  Publication uses
Redis scripts as one transport-level predecessor/head compare-and-set (CAS):

* a generation is written with ``SET NX`` and exactly read back;
* the current session, both legacy aliases, the generation, and predecessor
  head are checked before the latest pointer and head move atomically;
* a generation-scoped Redis clock receipt is observed only after the pointer
  commit and all dependencies are exactly rechecked; and
* a blocked-evidence write is attempt scoped and never mutates the latest
  pointer or head; its result separately reports any preceding commit outcome,
  so neither a failure nor its evidence can hide a newer READY state.

Redis ``SET NX`` is expiring transport evidence, not durable immutability, CAS
storage, point-in-time source evidence, a ledger receipt, or trainer admission.
Every artifact remains literally non-consumable and no live route is exposed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import InitVar, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol, TypeAlias

PAPER_POSITION_STATE_ENVELOPE_SCHEMA_VERSION = "paper_open_position_state_envelope_v2"
PAPER_POSITION_STATE_MATERIAL_SCHEMA_VERSION = "paper_open_position_state_material_v2"
PAPER_POSITION_GENERATION_IDENTITY_SCHEMA_VERSION = "paper_open_position_generation_identity_v2"
PAPER_POSITION_GENERATION_SCHEMA_VERSION = "paper_open_position_generation_v2"
PAPER_POSITION_POINTER_SCHEMA_VERSION = "paper_open_position_state_pointer_v2"
PAPER_POSITION_POINTER_GENERATION_SCHEMA_VERSION = (
    "paper_open_position_pointer_generation_binding_v2"
)
PAPER_POSITION_POINTER_LEGACY_SCHEMA_VERSION = (
    "paper_open_position_pointer_legacy_payload_binding_v2"
)
PAPER_POSITION_POINTER_STATE_SCHEMA_VERSION = "paper_open_position_pointer_state_binding_v2"
PAPER_POSITION_SESSION_BINDING_SCHEMA_VERSION = "paper_session_exact_key_binding_v1"
PAPER_POSITION_SESSION_TRANSITION_SCHEMA_VERSION = "paper_position_state_session_transition_v1"
PAPER_POSITION_HEAD_TOKEN_SCHEMA_VERSION = "paper_position_state_head_token_v1"  # noqa: S105 - hash-chain token, not a secret
PAPER_POSITION_AVAILABILITY_BINDING_SCHEMA_VERSION = (
    "paper_position_state_available_at_receipt_binding_v1"
)
PAPER_POSITION_BLOCKED_ATTEMPT_SCHEMA_VERSION = "paper_position_state_blocked_attempt_v1"
PAPER_POSITION_SAFETY_SCHEMA_VERSION = "paper_open_position_nonconsumable_safety_v2"

PAPER_POSITION_STATE_KIND = "FULL_REPLACEMENT_OPEN_PAPER_POSITION_MEMBERSHIP_SET"
PAPER_POSITION_PRODUCER_ID = "v2_trade_management_paper_loop"
PAPER_POSITION_PRODUCER_VERSION = "paper_open_position_state_publisher_v2"
PAPER_POSITION_STATE_EVENT_SEMANTICS = "FINAL_IN_MEMORY_POSITION_MEMBERSHIP_TRANSITION"
PAPER_POSITION_STATE_AVAILABLE_AT_SOURCE = (
    "GENERATION_SCOPED_REDIS_TIME_AFTER_COMMITTED_POINTER_HEAD_AND_EXACT_DEPENDENCY_READS"
)
PAPER_POSITION_STATE_AVAILABLE_AT_PENDING_SOURCE = (
    "GENERATION_SCOPED_REDIS_RECEIPT_REQUIRED_AFTER_POINTER_HEAD_COMMIT"
)
RAW_REDIS_SCRIPT_RESPONSE_MODE = "REDIS_EVAL_RAW_BYTES_DECODE_RESPONSES_FALSE_V1"
GENESIS_ABSENT_HEAD = "GENESIS_ABSENT_HEAD"
SAME_SESSION_SUCCESSOR_HEAD_CAS = "SAME_SESSION_SUCCESSOR_HEAD_CAS"
AUTHORIZED_SESSION_RESET_HEAD_CAS = "AUTHORIZED_SESSION_RESET_HEAD_CAS"

PAPER_POSITIONS_LEGACY_KEY = "v2:paper:positions"
PAPER_OPEN_POSITIONS_LEGACY_KEY = "v2:paper:open_positions"
PAPER_SESSION_REDIS_KEY = "v2:paper:session"
PAPER_POSITION_STATE_GENERATION_PREFIX = "v2:paper:positions:state:v2:generation:"
PAPER_POSITION_STATE_POINTER_KEY = "v2:paper:positions:state:v2:latest"
PAPER_POSITION_STATE_HEAD_KEY = "v2:paper:positions:state:v2:head"
PAPER_POSITION_STATE_AVAILABILITY_PREFIX = "v2:paper:positions:state:v2:available_at:"
PAPER_POSITION_STATE_BLOCKED_ATTEMPT_PREFIX = "v2:paper:positions:state:v2:blocked:"

MAX_LEGACY_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_SESSION_PAYLOAD_BYTES = 256 * 1024
MAX_GENERATION_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_POINTER_PAYLOAD_BYTES = 256 * 1024
MAX_ATTEMPT_PAYLOAD_BYTES = 256 * 1024
MAX_POSITION_ROWS = 4_096
MAX_JSON_DEPTH = 48
MAX_JSON_NODES = 262_144
MAX_JSON_STRING_BYTES = 2 * 1024 * 1024
MAX_JSON_CONTAINER_ITEMS = 65_536
MAX_TTL_SECONDS = 366 * 24 * 60 * 60
MAX_REJECTION_REASONS = 64
MAX_REJECTION_REASON_BYTES = 512
MAX_REDIS_RESPONSE_BYTES = MAX_LEGACY_PAYLOAD_BYTES

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_GENERATION_ID_RE = re.compile(r"^paper_positions_state_v2_[0-9a-f]{64}$")
_REDIS_TIME_RECEIPT_RE = re.compile(rb"^([0-9]{1,12}):([0-9]{1,6})$")
_ABSENT_HEAD_SENTINEL = b"PAPER_POSITION_STATE_HEAD_MUST_BE_ABSENT_V1"
_HEAD_TOKEN_FIELDS = frozenset(
    {
        "schema_version",
        "paper_session_id",
        "session_binding_token_sha256",
        "producer_generation_id",
    }
)

_MEMBERSHIP_ROW_FIELDS = frozenset(
    {
        "position_id",
        "position_generation_id",
        "symbol",
        "side",
        "position_state",
        "hedge_parent_id",
        "hedge_child_id",
        "paper_session_id",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)

ScriptArgument: TypeAlias = str | bytes | int


class AtomicScriptExecutor(Protocol):
    """Raw Redis EVAL adapter; decoded-response clients do not satisfy it."""

    redis_response_mode: str

    def __call__(
        self,
        script: str,
        keys: tuple[str, ...],
        args: tuple[ScriptArgument, ...],
    ) -> object: ...


GENERATION_PUBLISH_LUA = """
local created = redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX')
local payload = redis.call('GET', KEYS[1])
local ttl = redis.call('PTTL', KEYS[1])
return {created and 1 or 0, payload or false, ttl}
""".strip()


READY_POINTER_PUBLISH_LUA = """
local generation = redis.call('GET', KEYS[1])
local legacy_positions = redis.call('GET', KEYS[2])
local legacy_open_positions = redis.call('GET', KEYS[3])
local session_payload = redis.call('GET', KEYS[4])
local code = 0
if not generation then code = 1
elseif generation ~= ARGV[1] then code = 2
elseif not legacy_positions then code = 3
elseif legacy_positions ~= ARGV[2] then code = 4
elseif not legacy_open_positions then code = 5
elseif legacy_open_positions ~= ARGV[2] then code = 6
elseif not session_payload then code = 7
elseif session_payload ~= ARGV[3] then code = 8
end
local generation_ttl = redis.call('PTTL', KEYS[1])
local positions_ttl = redis.call('PTTL', KEYS[2])
local open_positions_ttl = redis.call('PTTL', KEYS[3])
local session_ttl = redis.call('PTTL', KEYS[4])
local dependency_ttl = math.min(generation_ttl, positions_ttl, open_positions_ttl)
if code == 0 and session_ttl ~= -1 then
  if session_ttl <= 2 then code = 9
  else dependency_ttl = math.min(dependency_ttl, session_ttl) end
end
if code == 0 and dependency_ttl <= 2 then code = 9 end

local current_head = redis.call('GET', KEYS[5])
local current_pointer = redis.call('GET', KEYS[6])
local idempotent = 0
if code == 0 and current_head == ARGV[5] then
  if not current_pointer then code = 13
  elseif current_pointer ~= ARGV[6] then code = 14
  else idempotent = 1 end
elseif code == 0 and ARGV[4] == ARGV[7] then
  if current_head then code = 11
  elseif current_pointer then code = 19 end
elseif code == 0 then
  if not current_head then code = 10
  elseif current_head ~= ARGV[4] then code = 12 end
end

local applied_ttl = -2
if code == 0 and idempotent == 0 then
  applied_ttl = dependency_ttl - 1
  redis.call('SET', KEYS[6], ARGV[6], 'PX', applied_ttl)
  redis.call('SET', KEYS[5], ARGV[5], 'PX', applied_ttl)
elseif code == 0 then
  applied_ttl = math.min(redis.call('PTTL', KEYS[5]), redis.call('PTTL', KEYS[6]))
  if applied_ttl <= 1 or applied_ttl > dependency_ttl then code = 15 end
end

local pointer_readback = redis.call('GET', KEYS[6])
local head_readback = redis.call('GET', KEYS[5])
local pointer_ttl = redis.call('PTTL', KEYS[6])
local head_ttl = redis.call('PTTL', KEYS[5])
if code == 0 and pointer_readback ~= ARGV[6] then code = 16 end
if code == 0 and head_readback ~= ARGV[5] then code = 17 end
local now = redis.call('TIME')
return {code, idempotent, pointer_readback or false, head_readback or false,
        applied_ttl, pointer_ttl, head_ttl, now[1], now[2]}
""".strip()


AVAILABLE_AT_OBSERVE_LUA = """
local generation = redis.call('GET', KEYS[1])
local legacy_positions = redis.call('GET', KEYS[2])
local legacy_open_positions = redis.call('GET', KEYS[3])
local session_payload = redis.call('GET', KEYS[4])
local head = redis.call('GET', KEYS[5])
local pointer = redis.call('GET', KEYS[6])
local code = 0
if not generation then code = 1
elseif generation ~= ARGV[1] then code = 2
elseif not legacy_positions then code = 3
elseif legacy_positions ~= ARGV[2] then code = 4
elseif not legacy_open_positions then code = 5
elseif legacy_open_positions ~= ARGV[2] then code = 6
elseif not session_payload then code = 7
elseif session_payload ~= ARGV[3] then code = 8
elseif not head then code = 10
elseif head ~= ARGV[4] then code = 12
elseif not pointer then code = 13
elseif pointer ~= ARGV[5] then code = 14
end
local session_ttl = redis.call('PTTL', KEYS[4])
local dependency_ttl = math.min(
  redis.call('PTTL', KEYS[1]), redis.call('PTTL', KEYS[2]),
  redis.call('PTTL', KEYS[3]), redis.call('PTTL', KEYS[5]),
  redis.call('PTTL', KEYS[6]))
if code == 0 and session_ttl ~= -1 then
  if session_ttl <= 1 then code = 18
  else dependency_ttl = math.min(dependency_ttl, session_ttl) end
end
if code == 0 and dependency_ttl <= 1 then code = 18 end
local created = 0
local receipt = redis.call('GET', KEYS[7])
if code == 0 and not receipt then
  local available = redis.call('TIME')
  local value = available[1] .. ':' .. available[2]
  local written = redis.call('SET', KEYS[7], value, 'PX', dependency_ttl - 1, 'NX')
  created = written and 1 or 0
  receipt = redis.call('GET', KEYS[7])
end
local receipt_ttl = redis.call('PTTL', KEYS[7])
local observed = redis.call('TIME')
return {code, created, receipt or false, receipt_ttl, observed[1], observed[2]}
""".strip()


BLOCKED_ATTEMPT_PUBLISH_LUA = """
local head_before = redis.call('GET', KEYS[2])
local created = redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX')
local payload = redis.call('GET', KEYS[1])
local ttl = redis.call('PTTL', KEYS[1])
local head_after = redis.call('GET', KEYS[2])
local now = redis.call('TIME')
return {created and 1 or 0, payload or false, ttl, head_before or false,
        head_after or false, now[1], now[2]}
""".strip()


_READY_FAILURE_CODES = {
    1: "GENERATION_KEY_MISSING_AT_POINTER_COMMIT",
    2: "GENERATION_BYTES_CHANGED_AT_POINTER_COMMIT",
    3: "LEGACY_POSITIONS_KEY_MISSING",
    4: "LEGACY_POSITIONS_BYTES_MISMATCH",
    5: "LEGACY_OPEN_POSITIONS_KEY_MISSING",
    6: "LEGACY_OPEN_POSITIONS_BYTES_MISMATCH",
    7: "PAPER_SESSION_KEY_MISSING",
    8: "PAPER_SESSION_EXACT_BYTES_MISMATCH",
    9: "POINTER_DEPENDENCY_TTL_INVALID",
    10: "EXPECTED_PREDECESSOR_HEAD_MISSING",
    11: "GENESIS_REQUIRES_ABSENT_HEAD",
    12: "EXPECTED_PREDECESSOR_HEAD_MISMATCH",
    13: "IDEMPOTENT_TARGET_POINTER_MISSING",
    14: "IDEMPOTENT_TARGET_POINTER_MISMATCH",
    15: "IDEMPOTENT_POINTER_HEAD_TTL_INVALID",
    16: "READY_POINTER_EXACT_READBACK_MISMATCH",
    17: "READY_HEAD_EXACT_READBACK_MISMATCH",
    18: "AVAILABLE_AT_DEPENDENCY_TTL_INVALID",
    19: "GENESIS_REQUIRES_ABSENT_POINTER",
}
_READY_PREMUTATION_FAILURE_CODES = frozenset((*range(1, 15), 19))

_HEAD_CAS_STATUSES = frozenset(
    {
        "NOT_ATTEMPTED",
        "REJECTED_BEFORE_MUTATION",
        "COMMIT_OUTCOME_UNKNOWN",
        "COMMITTED_TO_TARGET",
        "IDEMPOTENT_TARGET_CONFIRMED",
    }
)
_LATEST_POINTER_MUTATION_STATUSES = frozenset(
    {"NOT_MUTATED", "UNKNOWN", "MUTATED_TO_TARGET", "ALREADY_TARGET"}
)
_AVAILABILITY_RECEIPT_STATUSES = frozenset(
    {
        "NOT_ATTEMPTED",
        "REJECTED_BEFORE_WRITE",
        "OUTCOME_UNKNOWN",
        "PRESENT_UNVERIFIED",
        "VERIFIED",
    }
)


class PaperPositionStateError(RuntimeError):
    """Base fail-closed paper-position state error."""


class PaperPositionStateValidationError(PaperPositionStateError):
    """Input or canonical state violates the bounded membership contract."""

    def __init__(self, reasons: str | Sequence[str]) -> None:
        normalized = (reasons,) if isinstance(reasons, str) else tuple(reasons)
        self.reasons = _normalize_reasons(normalized)
        super().__init__("|".join(self.reasons) or "PAPER_POSITION_STATE_INVALID")


class PaperPositionStatePublicationError(PaperPositionStateError):
    """Atomic transport or exact-readback validation failed."""


@dataclass(frozen=True, slots=True)
class PaperPositionStateGeneration:
    """Recomputable generation plus exact external legacy/session bindings."""

    paper_session_id: str
    session_binding_key: str
    session_payload_sha256: str
    session_payload_byte_count: int
    session_payload_bytes: bytes
    session_binding_token_sha256: str
    producer_generation_id: str
    producer_generation_sha256: str
    generation_key: str
    previous_generation_id: str
    session_transition_mode: str
    expected_head_token_bytes: bytes | None
    authorized_reset_predecessor_head_token_sha256: str | None
    target_head_token_sha256: str
    target_head_token_bytes: bytes
    availability_receipt_key: str
    state_event_time: str
    state_generated_at: str
    state_material_sha256: str
    generation_payload_sha256: str
    generation_payload_bytes: bytes
    legacy_payload_sha256: str
    legacy_payload_byte_count: int
    legacy_payload_bytes: bytes
    empty_state: bool
    row_count: int
    symbols: tuple[str, ...]


_RESULT_FACTORY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class PaperPositionStatePublicationResult:
    """Factory-only, fail-closed publication result.

    ``dataclasses.replace`` and direct construction are rejected.  A READY
    result proves only the bounded Redis transport facts represented here; all
    trainer/durable-ledger capabilities stay false.
    """

    status: str
    rejection_reasons: tuple[str, ...]
    paper_session_id: str
    producer_generation_id: str
    generation_key: str
    generation_created: bool | None
    generation_ttl_ms: int | None
    publication_attempted_at: str
    state_available_at: str | None
    pointer_payload_sha256: str | None
    pointer_payload_bytes: bytes | None
    pointer_ttl_ms: int | None
    pointer_readback_verified_at: str | None
    availability_receipt_observed_at: str | None
    head_cas_status: str
    attempt_evidence_key: str | None
    attempt_evidence_payload_sha256: str | None
    attempt_evidence_payload_bytes: bytes | None
    attempt_evidence_ttl_ms: int | None
    attempt_evidence_readback_verified_at: str | None
    attempt_evidence_written: bool
    latest_pointer_mutation_status: str
    latest_pointer_mutated_by_publication: bool | None
    availability_receipt_status: str
    blocked_evidence_mutated_latest_pointer: bool
    redis_generation_set_nx_exact_readback_verified: bool
    redis_atomic_predecessor_head_cas_verified: bool
    trainer_consumable: bool = False
    durable_pit_evidence: bool = False
    durable_generation_immutability_verified: bool = False
    cas_readback_verified: bool = False
    ledger_postcommit_readback_verified: bool = False
    _factory_token: InitVar[object | None] = None

    def __post_init__(self, _factory_token: object | None) -> None:
        if _factory_token is not _RESULT_FACTORY_TOKEN:
            raise PaperPositionStatePublicationError("PUBLICATION_RESULT_FACTORY_REQUIRED")
        _validate_publication_result(self)


def _fail(reason: str) -> NoReturn:
    raise PaperPositionStateValidationError(reason)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safety_flags() -> dict[str, object]:
    """Return fresh, non-shared safety material for every artifact."""

    return {
        "schema_version": PAPER_POSITION_SAFETY_SCHEMA_VERSION,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "trainer_consumable": False,
        "durable_pit_evidence": False,
        "durable_generation_immutability_verified": False,
        "cas_readback_verified": False,
        "ledger_postcommit_readback_verified": False,
    }


def _normalize_reasons(reasons: Sequence[object]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for reason in reasons:
        if type(reason) is not str or not reason or reason != reason.strip():
            continue
        if len(reason.encode("utf-8")) > MAX_REJECTION_REASON_BYTES:
            continue
        normalized.add(reason)
    if len(normalized) > MAX_REJECTION_REASONS:
        normalized = set(sorted(normalized)[:MAX_REJECTION_REASONS])
    return tuple(sorted(normalized))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("PAYLOAD_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> NoReturn:
    _fail(f"PAYLOAD_NONFINITE_JSON_NUMBER:{value}")


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            _fail("JSON_NODE_COUNT_EXCEEDED")
        if depth > MAX_JSON_DEPTH:
            _fail("JSON_DEPTH_EXCEEDED")
        if current is None or type(current) in {bool, int}:
            continue
        if type(current) is float:
            if not math.isfinite(current):
                _fail("JSON_NONFINITE_NUMBER")
            continue
        if type(current) is str:
            if len(current.encode("utf-8")) > MAX_JSON_STRING_BYTES:
                _fail("JSON_STRING_BYTES_EXCEEDED")
            continue
        if type(current) is list:
            if len(current) > MAX_JSON_CONTAINER_ITEMS:
                _fail("JSON_LIST_ITEMS_EXCEEDED")
            stack.extend((item, depth + 1) for item in current)
            continue
        if type(current) is dict:
            if len(current) > MAX_JSON_CONTAINER_ITEMS:
                _fail("JSON_MAPPING_ITEMS_EXCEEDED")
            for key, item in current.items():
                if type(key) is not str:
                    _fail("JSON_MAPPING_KEY_NOT_STRING")
                if len(key.encode("utf-8")) > MAX_JSON_STRING_BYTES:
                    _fail("JSON_MAPPING_KEY_BYTES_EXCEEDED")
                stack.append((item, depth + 1))
            continue
        _fail("JSON_VALUE_TYPE_INVALID")


def _canonical_bytes(value: object, *, maximum: int) -> bytes:
    _validate_json_tree(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise PaperPositionStateValidationError("CANONICAL_JSON_SERIALIZATION_FAILED") from exc
    if not encoded or len(encoded) > maximum:
        _fail("CANONICAL_JSON_BYTES_EXCEEDED")
    return encoded


def _parse_json_bytes(payload: bytes, *, maximum: int, require_canonical: bool) -> object:
    if type(payload) is not bytes:
        _fail("EXACT_PAYLOAD_BYTES_REQUIRED")
    if not payload:
        _fail("PAYLOAD_EMPTY")
    if len(payload) > maximum:
        _fail("PAYLOAD_BYTES_EXCEEDED")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PaperPositionStateValidationError("PAYLOAD_UTF8_INVALID") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except PaperPositionStateValidationError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise PaperPositionStateValidationError("PAYLOAD_JSON_INVALID") from exc
    _validate_json_tree(parsed)
    if require_canonical and not hmac.compare_digest(
        payload, _canonical_bytes(parsed, maximum=maximum)
    ):
        _fail("PAYLOAD_NOT_CANONICAL_JSON")
    return parsed


def _strict_identity(value: object, *, field: str) -> str:
    if type(value) is not str or _IDENTITY_RE.fullmatch(value) is None:
        _fail(f"POSITION_{field.upper()}_INVALID")
    return value


def _strict_optional_identity(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _strict_identity(value, field=field)


def _strict_session(value: object) -> str:
    if type(value) is not str or _SESSION_RE.fullmatch(value) is None:
        _fail("PAPER_SESSION_ID_INVALID")
    return value


def _strict_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _canonical_utc(value: object, *, field: str) -> tuple[str, datetime]:
    if type(value) is not str or not value or value != value.strip():
        _fail(f"{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise PaperPositionStateValidationError(f"{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{field.upper()}_TIMEZONE_REQUIRED")
    parsed_utc = parsed.astimezone(UTC)
    canonical = parsed_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        _fail(f"{field.upper()}_NOT_CANONICAL_UTC")
    return canonical, parsed_utc


def _redis_time_receipt(value: object) -> tuple[str, datetime]:
    receipt = _exact_response_bytes(
        value,
        maximum=32,
        reason="REDIS_TIME_RECEIPT_RESPONSE_INVALID",
    )
    matched = _REDIS_TIME_RECEIPT_RE.fullmatch(receipt)
    if matched is None:
        raise PaperPositionStatePublicationError("REDIS_TIME_RECEIPT_RESPONSE_INVALID")
    return _redis_time_parts(matched.group(1), matched.group(2))


def _redis_time_parts(seconds: object, microseconds: object) -> tuple[str, datetime]:
    if type(seconds) is not bytes or type(microseconds) is not bytes:
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID")
    if not 1 <= len(seconds) <= 12 or not 1 <= len(microseconds) <= 6:
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID")
    if not seconds.isdigit() or not microseconds.isdigit():
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID")
    second_value = int(seconds)
    microsecond_value = int(microseconds)
    if second_value <= 0 or not 0 <= microsecond_value <= 999_999:
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID")
    try:
        parsed = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            seconds=second_value,
            microseconds=microsecond_value,
        )
    except OverflowError as exc:
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID") from exc
    if parsed.year > 9999:
        raise PaperPositionStatePublicationError("REDIS_TIME_RESPONSE_INVALID")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _exact_response_bytes(value: object, *, maximum: int, reason: str) -> bytes:
    if type(value) is not bytes or not value or len(value) > maximum:
        raise PaperPositionStatePublicationError(reason)
    return value


def _exact_optional_response_bytes(value: object, *, maximum: int, reason: str) -> bytes | None:
    if value is None:
        return None
    return _exact_response_bytes(value, maximum=maximum, reason=reason)


def _exact_response_int(value: object, *, reason: str) -> int:
    if type(value) is not int:
        raise PaperPositionStatePublicationError(reason)
    return value


def _script_list(value: object, *, length: int, reason: str) -> list[object]:
    if type(value) is not list or len(value) != length:
        raise PaperPositionStatePublicationError(reason)
    return value


def _membership_projection(
    legacy_payload_bytes: bytes, *, paper_session_id: str
) -> tuple[list[dict[str, object]], bytes]:
    parsed = _parse_json_bytes(
        legacy_payload_bytes,
        maximum=MAX_LEGACY_PAYLOAD_BYTES,
        require_canonical=False,
    )
    if type(parsed) is not list:
        _fail("LEGACY_PAYLOAD_NOT_LIST")
    if len(parsed) > MAX_POSITION_ROWS:
        _fail("POSITION_ROW_COUNT_EXCEEDED")

    projected: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for row in parsed:
        if type(row) is not dict:
            _fail("POSITION_ROW_NOT_MAPPING")
        position_id = _strict_identity(row.get("position_id"), field="position_id")
        generation_id = _strict_identity(
            row.get("position_generation_id"), field="position_generation_id"
        )
        symbol = row.get("symbol")
        if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
            _fail("POSITION_SYMBOL_INVALID")
        side = row.get("side")
        if type(side) is not str or side not in ("long", "short"):
            _fail("POSITION_SIDE_INVALID")
        if row.get("position_state") != "OPEN_POSITION":
            _fail("POSITION_STATE_NOT_OPEN")
        if row.get("paper_session_id") != paper_session_id:
            _fail("POSITION_PAPER_SESSION_MISMATCH")
        for alias in ("session_id", "reset_session_id"):
            if row.get(alias) not in (None, paper_session_id):
                _fail("POSITION_PAPER_SESSION_ALIAS_CONFLICT")
        if row.get("paper_only") is not True:
            _fail("POSITION_NOT_EXPLICITLY_PAPER_ONLY")
        if row.get("routes_to_live") is not False:
            _fail("POSITION_ROUTES_TO_LIVE_NOT_FALSE")
        if row.get("places_real_order") is not False:
            _fail("POSITION_PLACES_REAL_ORDER_NOT_FALSE")
        identity = (generation_id, position_id)
        if identity in identities:
            _fail("POSITION_IDENTITY_DUPLICATE")
        identities.add(identity)
        projected.append(
            {
                "position_id": position_id,
                "position_generation_id": generation_id,
                "symbol": symbol,
                "side": side,
                "position_state": "OPEN_POSITION",
                "hedge_parent_id": _strict_optional_identity(
                    row.get("hedge_parent_id"), field="hedge_parent_id"
                ),
                "hedge_child_id": _strict_optional_identity(
                    row.get("hedge_child_id"), field="hedge_child_id"
                ),
                "paper_session_id": paper_session_id,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
        )

    def sort_key(item: Mapping[str, object]) -> tuple[str, str, str, str]:
        row_bytes = _canonical_bytes(item, maximum=MAX_GENERATION_PAYLOAD_BYTES)
        return (
            str(item["symbol"]),
            str(item["position_generation_id"]),
            str(item["position_id"]),
            _sha256(row_bytes),
        )

    projected.sort(key=sort_key)
    rows_bytes = _canonical_bytes(projected, maximum=MAX_GENERATION_PAYLOAD_BYTES)
    return projected, rows_bytes


def _session_binding(session_payload_bytes: bytes, *, paper_session_id: str) -> tuple[str, str]:
    parsed = _parse_json_bytes(
        session_payload_bytes,
        maximum=MAX_SESSION_PAYLOAD_BYTES,
        require_canonical=False,
    )
    if type(parsed) is not dict:
        _fail("PAPER_SESSION_PAYLOAD_NOT_MAPPING")
    identity_values = [
        value
        for field in ("paper_session_id", "reset_session_id", "session_id")
        if (value := parsed.get(field)) not in (None, "")
    ]
    if not identity_values:
        _fail("PAPER_SESSION_PAYLOAD_IDENTITY_MISSING")
    if any(type(value) is not str for value in identity_values):
        _fail("PAPER_SESSION_PAYLOAD_IDENTITY_INVALID")
    identities = set(identity_values)
    if len(identities) != 1:
        _fail("PAPER_SESSION_PAYLOAD_IDENTITY_CONFLICT")
    if parsed.get("paper_session_id") != paper_session_id or identities != {paper_session_id}:
        _fail("PAPER_SESSION_PAYLOAD_IDENTITY_MISMATCH")
    if parsed.get("paper_only") is not True:
        _fail("PAPER_SESSION_PAYLOAD_NOT_EXPLICITLY_PAPER_ONLY")
    if parsed.get("routes_to_live") is not False:
        _fail("PAPER_SESSION_PAYLOAD_ROUTES_TO_LIVE_NOT_FALSE")
    if parsed.get("places_real_order") is not False:
        _fail("PAPER_SESSION_PAYLOAD_PLACES_REAL_ORDER_NOT_FALSE")
    payload_hash = _sha256(session_payload_bytes)
    token_material = {
        "schema_version": PAPER_POSITION_SESSION_BINDING_SCHEMA_VERSION,
        "paper_session_id": paper_session_id,
        "session_key": PAPER_SESSION_REDIS_KEY,
        "session_payload_sha256": payload_hash,
        "session_payload_byte_count": len(session_payload_bytes),
    }
    return payload_hash, _sha256(
        _canonical_bytes(token_material, maximum=MAX_SESSION_PAYLOAD_BYTES)
    )


def _previous_generation_id(value: object) -> str:
    if value == "GENESIS":
        return "GENESIS"
    if type(value) is not str or _GENERATION_ID_RE.fullmatch(value) is None:
        _fail("PREVIOUS_GENERATION_ID_INVALID")
    return value


def _head_token_bytes(
    *, paper_session_id: str, session_binding_token_sha256: str, generation_id: str
) -> bytes:
    return _canonical_bytes(
        {
            "schema_version": PAPER_POSITION_HEAD_TOKEN_SCHEMA_VERSION,
            "paper_session_id": paper_session_id,
            "session_binding_token_sha256": session_binding_token_sha256,
            "producer_generation_id": generation_id,
        },
        maximum=MAX_POINTER_PAYLOAD_BYTES,
    )


def _validated_authorized_reset_head_token(
    value: object,
    *,
    requested_paper_session_id: str,
    current_session_binding_token_sha256: str,
) -> bytes:
    """Validate an exact old-session head used to authorize one reset CAS.

    Authorization is deliberately transport-local: the new generation binds
    the exact old head bytes, the READY script compares those bytes atomically,
    and the same script also proves the exact new session payload.  A token from
    the current session cannot be used to disguise a same-session chain reset.
    """

    if type(value) is not bytes:
        _fail("AUTHORIZED_RESET_PREDECESSOR_HEAD_EXACT_BYTES_REQUIRED")
    parsed = _parse_json_bytes(
        value,
        maximum=MAX_POINTER_PAYLOAD_BYTES,
        require_canonical=True,
    )
    if type(parsed) is not dict or set(parsed) != _HEAD_TOKEN_FIELDS:
        _fail("AUTHORIZED_RESET_PREDECESSOR_HEAD_SHAPE_INVALID")
    if parsed.get("schema_version") != PAPER_POSITION_HEAD_TOKEN_SCHEMA_VERSION:
        _fail("AUTHORIZED_RESET_PREDECESSOR_HEAD_SCHEMA_INVALID")
    current_paper_session_id = _strict_session(parsed.get("paper_session_id"))
    if current_paper_session_id == requested_paper_session_id:
        _fail("AUTHORIZED_RESET_REQUIRES_DIFFERENT_PAPER_SESSION_ID")
    old_session_token = _strict_sha256(
        parsed.get("session_binding_token_sha256"),
        reason="AUTHORIZED_RESET_PREDECESSOR_SESSION_TOKEN_INVALID",
    )
    old_generation_id = parsed.get("producer_generation_id")
    if type(old_generation_id) is not str or _GENERATION_ID_RE.fullmatch(old_generation_id) is None:
        _fail("AUTHORIZED_RESET_PREDECESSOR_GENERATION_ID_INVALID")
    if hmac.compare_digest(old_session_token, current_session_binding_token_sha256):
        _fail("AUTHORIZED_RESET_REQUIRES_DIFFERENT_SESSION_BINDING")
    return value


def build_paper_position_state_generation(
    *,
    legacy_payload_bytes: bytes,
    session_payload_bytes: bytes,
    paper_session_id: str,
    state_event_time: str,
    state_generated_at: str,
    previous_generation_id: str = "GENESIS",
    authorized_reset_predecessor_head_token_bytes: bytes | None = None,
) -> PaperPositionStateGeneration:
    """Build one bounded generation bound to exact authoritative session bytes."""

    session_id = _strict_session(paper_session_id)
    previous_id = _previous_generation_id(previous_generation_id)
    session_payload_hash, session_token_hash = _session_binding(
        session_payload_bytes, paper_session_id=session_id
    )
    if previous_id != "GENESIS" and authorized_reset_predecessor_head_token_bytes is not None:
        _fail("AUTHORIZED_RESET_REQUIRES_GENESIS_GENERATION")
    if previous_id == "GENESIS" and authorized_reset_predecessor_head_token_bytes is not None:
        expected_head = _validated_authorized_reset_head_token(
            authorized_reset_predecessor_head_token_bytes,
            requested_paper_session_id=session_id,
            current_session_binding_token_sha256=session_token_hash,
        )
        transition_mode = AUTHORIZED_SESSION_RESET_HEAD_CAS
        authorized_reset_head_hash: str | None = _sha256(expected_head)
    elif previous_id == "GENESIS":
        expected_head = None
        transition_mode = GENESIS_ABSENT_HEAD
        authorized_reset_head_hash = None
    else:
        expected_head = _head_token_bytes(
            paper_session_id=session_id,
            session_binding_token_sha256=session_token_hash,
            generation_id=previous_id,
        )
        transition_mode = SAME_SESSION_SUCCESSOR_HEAD_CAS
        authorized_reset_head_hash = None
    canonical_event, event_dt = _canonical_utc(state_event_time, field="state_event_time")
    canonical_generated, generated_dt = _canonical_utc(
        state_generated_at, field="state_generated_at"
    )
    if event_dt > generated_dt:
        _fail("STATE_EVENT_TIME_AFTER_STATE_GENERATED_AT")
    projected_rows, canonical_rows_bytes = _membership_projection(
        legacy_payload_bytes, paper_session_id=session_id
    )
    symbols = tuple(sorted({str(row["symbol"]) for row in projected_rows}))
    session_material = {
        "schema_version": PAPER_POSITION_SESSION_BINDING_SCHEMA_VERSION,
        "paper_session_id": session_id,
        "session_key": PAPER_SESSION_REDIS_KEY,
        "session_payload_sha256": session_payload_hash,
        "session_payload_byte_count": len(session_payload_bytes),
        "session_binding_token_sha256": session_token_hash,
        "exact_session_key_read_required_at_pointer_commit": True,
    }
    session_transition_material = {
        "schema_version": PAPER_POSITION_SESSION_TRANSITION_SCHEMA_VERSION,
        "mode": transition_mode,
        "authorized_reset_predecessor_head_token_sha256": authorized_reset_head_hash,
        "exact_predecessor_head_cas_required": True,
        "exact_new_session_payload_cas_required": True,
    }
    state_material: dict[str, object] = {
        "schema_version": PAPER_POSITION_STATE_MATERIAL_SCHEMA_VERSION,
        "state_kind": PAPER_POSITION_STATE_KIND,
        "paper_session_id": session_id,
        "paper_session_binding": session_material,
        "producer_id": PAPER_POSITION_PRODUCER_ID,
        "producer_version": PAPER_POSITION_PRODUCER_VERSION,
        "previous_generation_id": previous_id,
        "session_transition": session_transition_material,
        "state_event_time": canonical_event,
        "state_event_time_semantics": PAPER_POSITION_STATE_EVENT_SEMANTICS,
        "state_generated_at": canonical_generated,
        "state_available_at": None,
        "state_available_at_source": PAPER_POSITION_STATE_AVAILABLE_AT_PENDING_SOURCE,
        "empty_state": not projected_rows,
        "row_count": len(projected_rows),
        "symbols": list(symbols),
        "rows": projected_rows,
        "canonical_rows_sha256": _sha256(canonical_rows_bytes),
        "canonical_rows_byte_count": len(canonical_rows_bytes),
        "safety": _safety_flags(),
    }
    state_material_bytes = _canonical_bytes(state_material, maximum=MAX_GENERATION_PAYLOAD_BYTES)
    state_material_sha256 = _sha256(state_material_bytes)
    generation_identity = {
        "schema_version": PAPER_POSITION_GENERATION_IDENTITY_SCHEMA_VERSION,
        "paper_session_id": session_id,
        "session_binding_token_sha256": session_token_hash,
        "producer_id": PAPER_POSITION_PRODUCER_ID,
        "producer_version": PAPER_POSITION_PRODUCER_VERSION,
        "previous_generation_id": previous_id,
        "session_transition": session_transition_material,
        "state_event_time": canonical_event,
        "state_generated_at": canonical_generated,
        "state_material_sha256": state_material_sha256,
    }
    generation_sha256 = _sha256(
        _canonical_bytes(generation_identity, maximum=MAX_GENERATION_PAYLOAD_BYTES)
    )
    generation_id = f"paper_positions_state_v2_{generation_sha256}"
    envelope = {
        "schema_version": PAPER_POSITION_STATE_ENVELOPE_SCHEMA_VERSION,
        "state_material": state_material,
        "state_material_sha256": state_material_sha256,
        "producer_generation": {
            "schema_version": PAPER_POSITION_GENERATION_SCHEMA_VERSION,
            "producer_generation_id": generation_id,
            "producer_generation_sha256": generation_sha256,
            "identity_material": generation_identity,
        },
    }
    envelope_bytes = _canonical_bytes(envelope, maximum=MAX_GENERATION_PAYLOAD_BYTES)
    target_head = _head_token_bytes(
        paper_session_id=session_id,
        session_binding_token_sha256=session_token_hash,
        generation_id=generation_id,
    )
    target_head_hash = _sha256(target_head)
    return PaperPositionStateGeneration(
        paper_session_id=session_id,
        session_binding_key=PAPER_SESSION_REDIS_KEY,
        session_payload_sha256=session_payload_hash,
        session_payload_byte_count=len(session_payload_bytes),
        session_payload_bytes=session_payload_bytes,
        session_binding_token_sha256=session_token_hash,
        producer_generation_id=generation_id,
        producer_generation_sha256=generation_sha256,
        generation_key=f"{PAPER_POSITION_STATE_GENERATION_PREFIX}{generation_sha256}",
        previous_generation_id=previous_id,
        session_transition_mode=transition_mode,
        expected_head_token_bytes=expected_head,
        authorized_reset_predecessor_head_token_sha256=authorized_reset_head_hash,
        target_head_token_sha256=target_head_hash,
        target_head_token_bytes=target_head,
        availability_receipt_key=(f"{PAPER_POSITION_STATE_AVAILABILITY_PREFIX}{target_head_hash}"),
        state_event_time=canonical_event,
        state_generated_at=canonical_generated,
        state_material_sha256=state_material_sha256,
        generation_payload_sha256=_sha256(envelope_bytes),
        generation_payload_bytes=envelope_bytes,
        legacy_payload_sha256=_sha256(legacy_payload_bytes),
        legacy_payload_byte_count=len(legacy_payload_bytes),
        legacy_payload_bytes=legacy_payload_bytes,
        empty_state=not projected_rows,
        row_count=len(projected_rows),
        symbols=symbols,
    )


def _validate_generation_artifact(artifact: PaperPositionStateGeneration) -> None:
    if type(artifact) is not PaperPositionStateGeneration:
        _fail("GENERATION_ARTIFACT_EXACT_TYPE_REQUIRED")
    authorized_reset_head = (
        artifact.expected_head_token_bytes
        if artifact.session_transition_mode == AUTHORIZED_SESSION_RESET_HEAD_CAS
        else None
    )
    rebuilt = build_paper_position_state_generation(
        legacy_payload_bytes=artifact.legacy_payload_bytes,
        session_payload_bytes=artifact.session_payload_bytes,
        paper_session_id=artifact.paper_session_id,
        state_event_time=artifact.state_event_time,
        state_generated_at=artifact.state_generated_at,
        previous_generation_id=artifact.previous_generation_id,
        authorized_reset_predecessor_head_token_bytes=authorized_reset_head,
    )
    for field in artifact.__dataclass_fields__:
        if getattr(artifact, field) != getattr(rebuilt, field):
            _fail("GENERATION_ARTIFACT_RECOMPUTATION_MISMATCH")


def _ttl_ms(ttl_seconds: int) -> int:
    if type(ttl_seconds) is not int or ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        _fail("PUBLICATION_TTL_SECONDS_INVALID")
    return ttl_seconds * 1_000


def _ready_pointer_bytes(artifact: PaperPositionStateGeneration) -> bytes:
    expected_head_hash = (
        None
        if artifact.expected_head_token_bytes is None
        else _sha256(artifact.expected_head_token_bytes)
    )
    material = {
        "schema_version": PAPER_POSITION_POINTER_SCHEMA_VERSION,
        "status": "READY",
        "producer_id": PAPER_POSITION_PRODUCER_ID,
        "producer_version": PAPER_POSITION_PRODUCER_VERSION,
        "generation": {
            "schema_version": PAPER_POSITION_POINTER_GENERATION_SCHEMA_VERSION,
            "generation_key": artifact.generation_key,
            "producer_generation_id": artifact.producer_generation_id,
            "producer_generation_sha256": artifact.producer_generation_sha256,
            "state_material_sha256": artifact.state_material_sha256,
            "state_envelope_payload_sha256": artifact.generation_payload_sha256,
            "state_envelope_payload_byte_count": len(artifact.generation_payload_bytes),
            "redis_set_nx_exact_readback_verified": True,
            "durable_generation_immutability_verified": False,
        },
        "head_cas": {
            "head_key": PAPER_POSITION_STATE_HEAD_KEY,
            "previous_generation_id": artifact.previous_generation_id,
            "session_transition_mode": artifact.session_transition_mode,
            "expected_head_token_sha256": expected_head_hash,
            "expected_head_absent": artifact.expected_head_token_bytes is None,
            "authorized_reset_predecessor_head_token_sha256": (
                artifact.authorized_reset_predecessor_head_token_sha256
            ),
            "target_head_token_sha256": artifact.target_head_token_sha256,
            "atomic_predecessor_head_cas_verified": True,
        },
        "paper_session_binding": {
            "schema_version": PAPER_POSITION_SESSION_BINDING_SCHEMA_VERSION,
            "paper_session_id": artifact.paper_session_id,
            "session_key": artifact.session_binding_key,
            "session_payload_sha256": artifact.session_payload_sha256,
            "session_payload_byte_count": artifact.session_payload_byte_count,
            "session_binding_token_sha256": artifact.session_binding_token_sha256,
            "exact_session_key_read_verified_in_head_cas": True,
        },
        "legacy_payload": {
            "schema_version": PAPER_POSITION_POINTER_LEGACY_SCHEMA_VERSION,
            "payload_sha256": artifact.legacy_payload_sha256,
            "payload_byte_count": artifact.legacy_payload_byte_count,
            "keys": [PAPER_POSITIONS_LEGACY_KEY, PAPER_OPEN_POSITIONS_LEGACY_KEY],
        },
        "state": {
            "schema_version": PAPER_POSITION_POINTER_STATE_SCHEMA_VERSION,
            "paper_session_id": artifact.paper_session_id,
            "state_event_time": artifact.state_event_time,
            "state_generated_at": artifact.state_generated_at,
            "state_available_at": None,
            "state_available_at_source": PAPER_POSITION_STATE_AVAILABLE_AT_PENDING_SOURCE,
            "availability_receipt": {
                "schema_version": PAPER_POSITION_AVAILABILITY_BINDING_SCHEMA_VERSION,
                "receipt_key": artifact.availability_receipt_key,
                "target_head_token_sha256": artifact.target_head_token_sha256,
                "required_after_pointer_head_commit": True,
            },
            "empty_state": artifact.empty_state,
            "row_count": artifact.row_count,
            "symbols": list(artifact.symbols),
        },
        "safety": _safety_flags(),
    }
    pointer_hash = _sha256(_canonical_bytes(material, maximum=MAX_POINTER_PAYLOAD_BYTES))
    return _canonical_bytes(
        {**material, "pointer_material_sha256": pointer_hash},
        maximum=MAX_POINTER_PAYLOAD_BYTES,
    )


def _attempt_evidence(
    artifact: PaperPositionStateGeneration,
    *,
    publication_attempted_at: str,
    rejection_reasons: Sequence[str],
    head_cas_status: str,
    latest_pointer_mutation_status: str,
    latest_pointer_mutated_by_publication: bool | None,
    availability_receipt_status: str,
) -> tuple[str, bytes]:
    normalized = _normalize_reasons(rejection_reasons)
    material = {
        "schema_version": PAPER_POSITION_BLOCKED_ATTEMPT_SCHEMA_VERSION,
        "status": "BLOCKED_ATTEMPT",
        "paper_session_id": artifact.paper_session_id,
        "session_binding_token_sha256": artifact.session_binding_token_sha256,
        "attempted_generation_id": artifact.producer_generation_id,
        "previous_generation_id": artifact.previous_generation_id,
        "session_transition_mode": artifact.session_transition_mode,
        "authorized_reset_predecessor_head_token_sha256": (
            artifact.authorized_reset_predecessor_head_token_sha256
        ),
        "expected_head_token_sha256": (
            None
            if artifact.expected_head_token_bytes is None
            else _sha256(artifact.expected_head_token_bytes)
        ),
        "target_head_token_sha256": artifact.target_head_token_sha256,
        "publication_attempted_at": publication_attempted_at,
        "rejection_reasons": list(normalized),
        "head_cas_status": head_cas_status,
        "latest_pointer_mutation_status": latest_pointer_mutation_status,
        "latest_pointer_mutated_by_publication": (latest_pointer_mutated_by_publication),
        "availability_receipt_status": availability_receipt_status,
        "blocked_evidence_mutated_latest_pointer": False,
        "blocked_evidence_mutated_head": False,
        "safety": _safety_flags(),
    }
    evidence_hash = _sha256(_canonical_bytes(material, maximum=MAX_ATTEMPT_PAYLOAD_BYTES))
    payload = _canonical_bytes(
        {**material, "attempt_material_sha256": evidence_hash},
        maximum=MAX_ATTEMPT_PAYLOAD_BYTES,
    )
    return f"{PAPER_POSITION_STATE_BLOCKED_ATTEMPT_PREFIX}{_sha256(payload)}", payload


def _validate_publication_result(result: PaperPositionStatePublicationResult) -> None:
    if type(result.status) is not str or result.status not in {"READY", "BLOCKED"}:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_STATUS_INVALID")
    if type(result.rejection_reasons) is not tuple or result.rejection_reasons != tuple(
        sorted(set(result.rejection_reasons))
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_REASONS_INVALID")
    _strict_session(result.paper_session_id)
    if (
        type(result.producer_generation_id) is not str
        or _GENERATION_ID_RE.fullmatch(result.producer_generation_id) is None
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_GENERATION_ID_INVALID")
    if type(result.generation_key) is not str or not result.generation_key.startswith(
        PAPER_POSITION_STATE_GENERATION_PREFIX
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_GENERATION_KEY_INVALID")
    attempted_at, attempted_dt = _canonical_utc(
        result.publication_attempted_at,
        field="publication_attempted_at",
    )
    if attempted_at != result.publication_attempted_at:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_ATTEMPT_CLOCK_INVALID")
    for value in (
        result.trainer_consumable,
        result.durable_pit_evidence,
        result.durable_generation_immutability_verified,
        result.cas_readback_verified,
        result.ledger_postcommit_readback_verified,
        result.blocked_evidence_mutated_latest_pointer,
    ):
        if value is not False:
            raise PaperPositionStatePublicationError(
                "PUBLICATION_RESULT_NONCONSUMABLE_INVARIANT_VIOLATED"
            )
    if result.generation_created is not None and type(result.generation_created) is not bool:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_CREATED_FLAG_INVALID")
    if result.generation_ttl_ms is not None and (
        type(result.generation_ttl_ms) is not int or result.generation_ttl_ms <= 0
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_GENERATION_TTL_INVALID")
    if type(result.redis_generation_set_nx_exact_readback_verified) is not bool:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_GENERATION_PROOF_INVALID")
    if type(result.redis_atomic_predecessor_head_cas_verified) is not bool:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_HEAD_PROOF_INVALID")
    if result.head_cas_status not in _HEAD_CAS_STATUSES:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_HEAD_CAS_STATUS_INVALID")
    if result.latest_pointer_mutation_status not in _LATEST_POINTER_MUTATION_STATUSES:
        raise PaperPositionStatePublicationError(
            "PUBLICATION_RESULT_POINTER_MUTATION_STATUS_INVALID"
        )
    if result.availability_receipt_status not in _AVAILABILITY_RECEIPT_STATUSES:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_AVAILABILITY_STATUS_INVALID")
    if (
        result.latest_pointer_mutated_by_publication is not None
        and type(result.latest_pointer_mutated_by_publication) is not bool
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_POINTER_MUTATION_FLAG_INVALID")
    expected_outcome = {
        "NOT_ATTEMPTED": ("NOT_MUTATED", False, False),
        "REJECTED_BEFORE_MUTATION": ("NOT_MUTATED", False, False),
        "COMMIT_OUTCOME_UNKNOWN": ("UNKNOWN", None, False),
        "COMMITTED_TO_TARGET": ("MUTATED_TO_TARGET", True, True),
        "IDEMPOTENT_TARGET_CONFIRMED": ("ALREADY_TARGET", False, True),
    }[result.head_cas_status]
    if (
        result.latest_pointer_mutation_status,
        result.latest_pointer_mutated_by_publication,
        result.redis_atomic_predecessor_head_cas_verified,
    ) != expected_outcome:
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_COMMIT_OUTCOME_INCONSISTENT")
    if (
        result.head_cas_status
        in {"NOT_ATTEMPTED", "REJECTED_BEFORE_MUTATION", "COMMIT_OUTCOME_UNKNOWN"}
        and result.availability_receipt_status != "NOT_ATTEMPTED"
    ):
        raise PaperPositionStatePublicationError("PUBLICATION_RESULT_AVAILABILITY_WITHOUT_COMMIT")

    if result.status == "READY":
        if result.rejection_reasons:
            raise PaperPositionStatePublicationError("READY_RESULT_HAS_REJECTION_REASONS")
        if result.head_cas_status not in {
            "COMMITTED_TO_TARGET",
            "IDEMPOTENT_TARGET_CONFIRMED",
        }:
            raise PaperPositionStatePublicationError("READY_RESULT_HEAD_CAS_STATUS_INVALID")
        if result.availability_receipt_status != "VERIFIED":
            raise PaperPositionStatePublicationError(
                "READY_RESULT_AVAILABILITY_RECEIPT_NOT_VERIFIED"
            )
        if not result.redis_generation_set_nx_exact_readback_verified:
            raise PaperPositionStatePublicationError("READY_RESULT_GENERATION_PROOF_MISSING")
        if not result.redis_atomic_predecessor_head_cas_verified:
            raise PaperPositionStatePublicationError("READY_RESULT_HEAD_PROOF_MISSING")
        if type(result.pointer_payload_bytes) is not bytes:
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_BYTES_MISSING")
        if len(result.pointer_payload_bytes) > MAX_POINTER_PAYLOAD_BYTES:
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_BYTES_INVALID")
        if result.pointer_payload_sha256 != _sha256(result.pointer_payload_bytes):
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_HASH_MISMATCH")
        parsed = _parse_json_bytes(
            result.pointer_payload_bytes,
            maximum=MAX_POINTER_PAYLOAD_BYTES,
            require_canonical=True,
        )
        if type(parsed) is not dict or parsed.get("status") != "READY":
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_SEMANTICS_INVALID")
        generation = parsed.get("generation")
        session = parsed.get("paper_session_binding")
        safety = parsed.get("safety")
        if (
            type(generation) is not dict
            or generation.get("producer_generation_id") != result.producer_generation_id
            or generation.get("generation_key") != result.generation_key
            or type(session) is not dict
            or session.get("paper_session_id") != result.paper_session_id
            or safety != _safety_flags()
        ):
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_BINDING_INVALID")
        if (
            result.state_available_at is None
            or result.pointer_readback_verified_at is None
            or result.availability_receipt_observed_at is None
        ):
            raise PaperPositionStatePublicationError("READY_RESULT_REDIS_CLOCK_MISSING")
        available_dt = _canonical_utc(result.state_available_at, field="state_available_at")[1]
        readback_dt = _canonical_utc(
            result.pointer_readback_verified_at,
            field="pointer_readback_verified_at",
        )[1]
        observed_dt = _canonical_utc(
            result.availability_receipt_observed_at,
            field="availability_receipt_observed_at",
        )[1]
        if not attempted_dt <= readback_dt <= available_dt <= observed_dt:
            raise PaperPositionStatePublicationError("READY_RESULT_CLOCK_ORDER_INVALID")
        if type(result.pointer_ttl_ms) is not int or result.pointer_ttl_ms <= 0:
            raise PaperPositionStatePublicationError("READY_RESULT_POINTER_TTL_INVALID")
        if (
            any(
                value is not None
                for value in (
                    result.attempt_evidence_key,
                    result.attempt_evidence_payload_sha256,
                    result.attempt_evidence_payload_bytes,
                    result.attempt_evidence_ttl_ms,
                    result.attempt_evidence_readback_verified_at,
                )
            )
            or result.attempt_evidence_written
        ):
            raise PaperPositionStatePublicationError("READY_RESULT_ATTEMPT_EVIDENCE_INVALID")
        return

    if not result.rejection_reasons:
        raise PaperPositionStatePublicationError("BLOCKED_RESULT_REASONS_MISSING")
    if result.availability_receipt_status == "VERIFIED":
        raise PaperPositionStatePublicationError("BLOCKED_RESULT_AVAILABILITY_RECEIPT_OVERCLAIMED")
    if any(
        value is not None
        for value in (
            result.state_available_at,
            result.pointer_payload_sha256,
            result.pointer_payload_bytes,
            result.pointer_ttl_ms,
            result.pointer_readback_verified_at,
            result.availability_receipt_observed_at,
        )
    ):
        raise PaperPositionStatePublicationError("BLOCKED_RESULT_POINTER_CLAIM_INVALID")
    evidence_fields = (
        result.attempt_evidence_key,
        result.attempt_evidence_payload_sha256,
        result.attempt_evidence_payload_bytes,
        result.attempt_evidence_ttl_ms,
        result.attempt_evidence_readback_verified_at,
    )
    if result.attempt_evidence_written:
        if any(value is None for value in evidence_fields):
            raise PaperPositionStatePublicationError("BLOCKED_RESULT_EVIDENCE_INCOMPLETE")
        assert result.attempt_evidence_payload_bytes is not None
        if (
            type(result.attempt_evidence_payload_bytes) is not bytes
            or len(result.attempt_evidence_payload_bytes) > MAX_ATTEMPT_PAYLOAD_BYTES
        ):
            raise PaperPositionStatePublicationError("BLOCKED_RESULT_EVIDENCE_BYTES_INVALID")
        if result.attempt_evidence_payload_sha256 != _sha256(result.attempt_evidence_payload_bytes):
            raise PaperPositionStatePublicationError("BLOCKED_RESULT_EVIDENCE_HASH_MISMATCH")
        parsed = _parse_json_bytes(
            result.attempt_evidence_payload_bytes,
            maximum=MAX_ATTEMPT_PAYLOAD_BYTES,
            require_canonical=True,
        )
        if (
            type(parsed) is not dict
            or parsed.get("status") != "BLOCKED_ATTEMPT"
            or parsed.get("head_cas_status") != result.head_cas_status
            or parsed.get("publication_attempted_at") != result.publication_attempted_at
            or parsed.get("latest_pointer_mutation_status") != result.latest_pointer_mutation_status
            or parsed.get("latest_pointer_mutated_by_publication")
            is not result.latest_pointer_mutated_by_publication
            or parsed.get("availability_receipt_status") != result.availability_receipt_status
            or parsed.get("blocked_evidence_mutated_latest_pointer") is not False
            or parsed.get("blocked_evidence_mutated_head") is not False
            or parsed.get("safety") != _safety_flags()
        ):
            raise PaperPositionStatePublicationError("BLOCKED_RESULT_EVIDENCE_INVALID")
    elif any(value is not None for value in evidence_fields):
        raise PaperPositionStatePublicationError("BLOCKED_RESULT_EVIDENCE_OVERCLAIMED")


def _make_result(**values: Any) -> PaperPositionStatePublicationResult:
    return PaperPositionStatePublicationResult(
        **values,
        _factory_token=_RESULT_FACTORY_TOKEN,
    )


def _blocked_result(
    artifact: PaperPositionStateGeneration,
    *,
    execute_script: AtomicScriptExecutor,
    ttl_ms: int,
    publication_attempted_at: str,
    reasons: Sequence[str],
    generation_created: bool | None,
    generation_ttl_ms: int | None,
    generation_verified: bool,
    head_cas_status: str,
    latest_pointer_mutation_status: str,
    latest_pointer_mutated_by_publication: bool | None,
    availability_receipt_status: str,
) -> PaperPositionStatePublicationResult:
    normalized = _normalize_reasons(reasons) or ("PAPER_POSITION_PUBLICATION_BLOCKED",)
    evidence_key, evidence_bytes = _attempt_evidence(
        artifact,
        publication_attempted_at=publication_attempted_at,
        rejection_reasons=normalized,
        head_cas_status=head_cas_status,
        latest_pointer_mutation_status=latest_pointer_mutation_status,
        latest_pointer_mutated_by_publication=(latest_pointer_mutated_by_publication),
        availability_receipt_status=availability_receipt_status,
    )
    evidence_written = False
    evidence_ttl: int | None = None
    evidence_observed_at: str | None = None
    try:
        raw = execute_script(
            BLOCKED_ATTEMPT_PUBLISH_LUA,
            (evidence_key, PAPER_POSITION_STATE_HEAD_KEY),
            (evidence_bytes, ttl_ms),
        )
        result = _script_list(raw, length=7, reason="BLOCKED_ATTEMPT_SCRIPT_RESPONSE_INVALID")
        created = _exact_response_int(result[0], reason="BLOCKED_ATTEMPT_CREATED_FLAG_INVALID")
        if created not in {0, 1}:
            raise PaperPositionStatePublicationError("BLOCKED_ATTEMPT_CREATED_FLAG_INVALID")
        readback = _exact_response_bytes(
            result[1],
            maximum=MAX_ATTEMPT_PAYLOAD_BYTES,
            reason="BLOCKED_ATTEMPT_READBACK_TYPE_INVALID",
        )
        evidence_ttl = _exact_response_int(result[2], reason="BLOCKED_ATTEMPT_TTL_INVALID")
        head_before = _exact_optional_response_bytes(
            result[3],
            maximum=MAX_POINTER_PAYLOAD_BYTES,
            reason="BLOCKED_ATTEMPT_HEAD_RESPONSE_INVALID",
        )
        head_after = _exact_optional_response_bytes(
            result[4],
            maximum=MAX_POINTER_PAYLOAD_BYTES,
            reason="BLOCKED_ATTEMPT_HEAD_RESPONSE_INVALID",
        )
        evidence_observed_at, _ = _redis_time_parts(result[5], result[6])
        if not hmac.compare_digest(readback, evidence_bytes):
            raise PaperPositionStatePublicationError("BLOCKED_ATTEMPT_EXACT_READBACK_MISMATCH")
        if evidence_ttl <= 0 or evidence_ttl > ttl_ms:
            raise PaperPositionStatePublicationError("BLOCKED_ATTEMPT_TTL_INVALID")
        if head_before != head_after:
            raise PaperPositionStatePublicationError("BLOCKED_ATTEMPT_MUTATED_HEAD")
        evidence_written = True
    except Exception:
        normalized = _normalize_reasons((*normalized, "BLOCKED_ATTEMPT_EVIDENCE_WRITE_FAILED"))

    return _make_result(
        status="BLOCKED",
        rejection_reasons=normalized,
        paper_session_id=artifact.paper_session_id,
        producer_generation_id=artifact.producer_generation_id,
        generation_key=artifact.generation_key,
        generation_created=generation_created,
        generation_ttl_ms=generation_ttl_ms,
        publication_attempted_at=publication_attempted_at,
        state_available_at=None,
        pointer_payload_sha256=None,
        pointer_payload_bytes=None,
        pointer_ttl_ms=None,
        pointer_readback_verified_at=None,
        availability_receipt_observed_at=None,
        head_cas_status=head_cas_status,
        attempt_evidence_key=evidence_key if evidence_written else None,
        attempt_evidence_payload_sha256=_sha256(evidence_bytes) if evidence_written else None,
        attempt_evidence_payload_bytes=evidence_bytes if evidence_written else None,
        attempt_evidence_ttl_ms=evidence_ttl if evidence_written else None,
        attempt_evidence_readback_verified_at=(evidence_observed_at if evidence_written else None),
        attempt_evidence_written=evidence_written,
        latest_pointer_mutation_status=latest_pointer_mutation_status,
        latest_pointer_mutated_by_publication=latest_pointer_mutated_by_publication,
        availability_receipt_status=availability_receipt_status,
        blocked_evidence_mutated_latest_pointer=False,
        redis_generation_set_nx_exact_readback_verified=generation_verified,
        redis_atomic_predecessor_head_cas_verified=(
            head_cas_status in {"COMMITTED_TO_TARGET", "IDEMPOTENT_TARGET_CONFIRMED"}
        ),
    )


def publish_paper_position_state_generation(
    artifact: PaperPositionStateGeneration,
    *,
    execute_script: AtomicScriptExecutor,
    ttl_seconds: int,
    publication_attempted_at: str,
) -> PaperPositionStatePublicationResult:
    """Publish one exact generation under an atomic predecessor/head CAS.

    ``execute_script`` must be a raw-byte Redis adapter backed by a client with
    ``decode_responses=False`` and must expose ``redis_response_mode`` equal to
    :data:`RAW_REDIS_SCRIPT_RESPONSE_MODE`.  READY is transport evidence only.
    A blocked-evidence write never replaces the latest pointer or head; if an
    earlier READY script may have committed, the result reports that outcome
    independently instead of claiming the head remained unchanged.
    """

    _validate_generation_artifact(artifact)
    if not callable(execute_script):
        _fail("ATOMIC_SCRIPT_EXECUTOR_REQUIRED")
    if getattr(execute_script, "redis_response_mode", None) != RAW_REDIS_SCRIPT_RESPONSE_MODE:
        _fail("RAW_REDIS_SCRIPT_EXECUTOR_REQUIRED")
    ttl_ms = _ttl_ms(ttl_seconds)
    attempted_at, attempted_dt = _canonical_utc(
        publication_attempted_at, field="publication_attempted_at"
    )
    _, generated_dt = _canonical_utc(artifact.state_generated_at, field="state_generated_at")
    if generated_dt > attempted_dt:
        _fail("STATE_GENERATED_AT_AFTER_PUBLICATION_ATTEMPTED_AT")

    generation_created: bool | None = None
    generation_ttl: int | None = None
    generation_verified = False
    try:
        raw_generation = execute_script(
            GENERATION_PUBLISH_LUA,
            (artifact.generation_key,),
            (artifact.generation_payload_bytes, ttl_ms),
        )
        generation_result = _script_list(
            raw_generation, length=3, reason="GENERATION_SCRIPT_RESPONSE_INVALID"
        )
        created_code = _exact_response_int(
            generation_result[0], reason="GENERATION_CREATED_FLAG_INVALID"
        )
        if created_code not in {0, 1}:
            raise PaperPositionStatePublicationError("GENERATION_CREATED_FLAG_INVALID")
        generation_created = bool(created_code)
        generation_readback = _exact_response_bytes(
            generation_result[1],
            maximum=MAX_GENERATION_PAYLOAD_BYTES,
            reason="GENERATION_READBACK_TYPE_INVALID",
        )
        generation_ttl = _exact_response_int(generation_result[2], reason="GENERATION_TTL_INVALID")
        if not hmac.compare_digest(generation_readback, artifact.generation_payload_bytes):
            raise PaperPositionStatePublicationError(
                "GENERATION_EXACT_READBACK_MISMATCH"
                if generation_created
                else "GENERATION_SET_NX_COLLISION"
            )
        if generation_ttl <= 0 or generation_ttl > ttl_ms:
            raise PaperPositionStatePublicationError("GENERATION_TTL_INVALID")
        generation_verified = True
    except PaperPositionStatePublicationError as exc:
        return _blocked_result(
            artifact,
            execute_script=execute_script,
            ttl_ms=ttl_ms,
            publication_attempted_at=attempted_at,
            reasons=(str(exc),),
            generation_created=generation_created,
            generation_ttl_ms=generation_ttl,
            generation_verified=False,
            head_cas_status="NOT_ATTEMPTED",
            latest_pointer_mutation_status="NOT_MUTATED",
            latest_pointer_mutated_by_publication=False,
            availability_receipt_status="NOT_ATTEMPTED",
        )
    except Exception:
        return _blocked_result(
            artifact,
            execute_script=execute_script,
            ttl_ms=ttl_ms,
            publication_attempted_at=attempted_at,
            reasons=("GENERATION_SCRIPT_EXECUTION_FAILED",),
            generation_created=generation_created,
            generation_ttl_ms=generation_ttl,
            generation_verified=False,
            head_cas_status="NOT_ATTEMPTED",
            latest_pointer_mutation_status="NOT_MUTATED",
            latest_pointer_mutated_by_publication=False,
            availability_receipt_status="NOT_ATTEMPTED",
        )

    pointer_bytes = _ready_pointer_bytes(artifact)
    expected_head = artifact.expected_head_token_bytes or _ABSENT_HEAD_SENTINEL
    head_cas_status = "COMMIT_OUTCOME_UNKNOWN"
    latest_pointer_mutation_status = "UNKNOWN"
    latest_pointer_mutated_by_publication: bool | None = None
    availability_receipt_status = "NOT_ATTEMPTED"
    try:
        raw_pointer = execute_script(
            READY_POINTER_PUBLISH_LUA,
            (
                artifact.generation_key,
                PAPER_POSITIONS_LEGACY_KEY,
                PAPER_OPEN_POSITIONS_LEGACY_KEY,
                artifact.session_binding_key,
                PAPER_POSITION_STATE_HEAD_KEY,
                PAPER_POSITION_STATE_POINTER_KEY,
            ),
            (
                artifact.generation_payload_bytes,
                artifact.legacy_payload_bytes,
                artifact.session_payload_bytes,
                expected_head,
                artifact.target_head_token_bytes,
                pointer_bytes,
                _ABSENT_HEAD_SENTINEL,
            ),
        )
        pointer_result = _script_list(
            raw_pointer, length=9, reason="READY_POINTER_SCRIPT_RESPONSE_INVALID"
        )
        code = _exact_response_int(pointer_result[0], reason="READY_POINTER_STATUS_CODE_INVALID")
        idempotent_code = _exact_response_int(
            pointer_result[1], reason="READY_POINTER_IDEMPOTENT_FLAG_INVALID"
        )
        if idempotent_code not in {0, 1}:
            raise PaperPositionStatePublicationError("READY_POINTER_IDEMPOTENT_FLAG_INVALID")
        if code != 0:
            if code in _READY_PREMUTATION_FAILURE_CODES:
                head_cas_status = "REJECTED_BEFORE_MUTATION"
                latest_pointer_mutation_status = "NOT_MUTATED"
                latest_pointer_mutated_by_publication = False
            elif code == 15 and idempotent_code == 1:
                head_cas_status = "IDEMPOTENT_TARGET_CONFIRMED"
                latest_pointer_mutation_status = "ALREADY_TARGET"
                latest_pointer_mutated_by_publication = False
            raise PaperPositionStatePublicationError(
                _READY_FAILURE_CODES.get(code, "READY_POINTER_STATUS_CODE_INVALID")
            )
        pointer_readback = _exact_response_bytes(
            pointer_result[2],
            maximum=MAX_POINTER_PAYLOAD_BYTES,
            reason="READY_POINTER_READBACK_TYPE_INVALID",
        )
        head_readback = _exact_response_bytes(
            pointer_result[3],
            maximum=MAX_POINTER_PAYLOAD_BYTES,
            reason="READY_HEAD_READBACK_TYPE_INVALID",
        )
        applied_ttl = _exact_response_int(
            pointer_result[4], reason="READY_POINTER_APPLIED_TTL_INVALID"
        )
        pointer_ttl = _exact_response_int(
            pointer_result[5], reason="READY_POINTER_READBACK_TTL_INVALID"
        )
        head_ttl = _exact_response_int(pointer_result[6], reason="READY_HEAD_READBACK_TTL_INVALID")
        if not hmac.compare_digest(pointer_readback, pointer_bytes):
            raise PaperPositionStatePublicationError("READY_POINTER_EXACT_READBACK_MISMATCH")
        if not hmac.compare_digest(head_readback, artifact.target_head_token_bytes):
            raise PaperPositionStatePublicationError("READY_HEAD_EXACT_READBACK_MISMATCH")
        if idempotent_code:
            head_cas_status = "IDEMPOTENT_TARGET_CONFIRMED"
            latest_pointer_mutation_status = "ALREADY_TARGET"
            latest_pointer_mutated_by_publication = False
        else:
            head_cas_status = "COMMITTED_TO_TARGET"
            latest_pointer_mutation_status = "MUTATED_TO_TARGET"
            latest_pointer_mutated_by_publication = True
        if applied_ttl <= 0 or applied_ttl > generation_ttl:
            raise PaperPositionStatePublicationError("READY_POINTER_APPLIED_TTL_INVALID")
        if pointer_ttl <= 0 or pointer_ttl > applied_ttl:
            raise PaperPositionStatePublicationError("READY_POINTER_READBACK_TTL_INVALID")
        if head_ttl <= 0 or head_ttl > applied_ttl:
            raise PaperPositionStatePublicationError("READY_HEAD_READBACK_TTL_INVALID")
        pointer_readback_at, pointer_readback_dt = _redis_time_parts(
            pointer_result[7], pointer_result[8]
        )
        if generated_dt > pointer_readback_dt:
            raise PaperPositionStatePublicationError("STATE_GENERATED_AT_AFTER_POINTER_READBACK")
        if attempted_dt > pointer_readback_dt:
            raise PaperPositionStatePublicationError(
                "PUBLICATION_ATTEMPTED_AT_AFTER_POINTER_READBACK"
            )

        availability_receipt_status = "OUTCOME_UNKNOWN"
        raw_available = execute_script(
            AVAILABLE_AT_OBSERVE_LUA,
            (
                artifact.generation_key,
                PAPER_POSITIONS_LEGACY_KEY,
                PAPER_OPEN_POSITIONS_LEGACY_KEY,
                artifact.session_binding_key,
                PAPER_POSITION_STATE_HEAD_KEY,
                PAPER_POSITION_STATE_POINTER_KEY,
                artifact.availability_receipt_key,
            ),
            (
                artifact.generation_payload_bytes,
                artifact.legacy_payload_bytes,
                artifact.session_payload_bytes,
                artifact.target_head_token_bytes,
                pointer_bytes,
            ),
        )
        available_result = _script_list(
            raw_available, length=6, reason="AVAILABLE_AT_SCRIPT_RESPONSE_INVALID"
        )
        available_code = _exact_response_int(
            available_result[0], reason="AVAILABLE_AT_STATUS_CODE_INVALID"
        )
        if available_code != 0:
            availability_receipt_status = "REJECTED_BEFORE_WRITE"
            raise PaperPositionStatePublicationError(
                _READY_FAILURE_CODES.get(available_code, "AVAILABLE_AT_STATUS_CODE_INVALID")
            )
        available_created = _exact_response_int(
            available_result[1], reason="AVAILABLE_AT_CREATED_FLAG_INVALID"
        )
        if available_created not in {0, 1}:
            raise PaperPositionStatePublicationError("AVAILABLE_AT_CREATED_FLAG_INVALID")
        state_available_at, available_dt = _redis_time_receipt(available_result[2])
        availability_receipt_status = "PRESENT_UNVERIFIED"
        available_ttl = _exact_response_int(available_result[3], reason="AVAILABLE_AT_TTL_INVALID")
        observed_at, observed_dt = _redis_time_parts(available_result[4], available_result[5])
        if available_ttl <= 0 or available_ttl > pointer_ttl:
            raise PaperPositionStatePublicationError("AVAILABLE_AT_TTL_INVALID")
        if pointer_readback_dt > available_dt or available_dt > observed_dt:
            raise PaperPositionStatePublicationError("AVAILABLE_AT_CLOCK_ORDER_INVALID")
        availability_receipt_status = "VERIFIED"
        # The authoritative availability receipt is a clock, not a mutable
        # field in the deterministic pointer.  Keep the observation local to
        # this strict factory result while the pointer binds its receipt key.
        _ = observed_at
    except PaperPositionStatePublicationError as exc:
        return _blocked_result(
            artifact,
            execute_script=execute_script,
            ttl_ms=ttl_ms,
            publication_attempted_at=attempted_at,
            reasons=(str(exc),),
            generation_created=generation_created,
            generation_ttl_ms=generation_ttl,
            generation_verified=generation_verified,
            head_cas_status=head_cas_status,
            latest_pointer_mutation_status=latest_pointer_mutation_status,
            latest_pointer_mutated_by_publication=(latest_pointer_mutated_by_publication),
            availability_receipt_status=availability_receipt_status,
        )
    except Exception:
        execution_reason = (
            "AVAILABLE_AT_SCRIPT_EXECUTION_FAILED"
            if availability_receipt_status != "NOT_ATTEMPTED"
            else "READY_POINTER_SCRIPT_EXECUTION_FAILED"
        )
        return _blocked_result(
            artifact,
            execute_script=execute_script,
            ttl_ms=ttl_ms,
            publication_attempted_at=attempted_at,
            reasons=(execution_reason,),
            generation_created=generation_created,
            generation_ttl_ms=generation_ttl,
            generation_verified=generation_verified,
            head_cas_status=head_cas_status,
            latest_pointer_mutation_status=latest_pointer_mutation_status,
            latest_pointer_mutated_by_publication=(latest_pointer_mutated_by_publication),
            availability_receipt_status=availability_receipt_status,
        )

    return _make_result(
        status="READY",
        rejection_reasons=(),
        paper_session_id=artifact.paper_session_id,
        producer_generation_id=artifact.producer_generation_id,
        generation_key=artifact.generation_key,
        generation_created=generation_created,
        generation_ttl_ms=generation_ttl,
        publication_attempted_at=attempted_at,
        state_available_at=state_available_at,
        pointer_payload_sha256=_sha256(pointer_bytes),
        pointer_payload_bytes=pointer_bytes,
        pointer_ttl_ms=pointer_ttl,
        pointer_readback_verified_at=pointer_readback_at,
        availability_receipt_observed_at=observed_at,
        head_cas_status=head_cas_status,
        attempt_evidence_key=None,
        attempt_evidence_payload_sha256=None,
        attempt_evidence_payload_bytes=None,
        attempt_evidence_ttl_ms=None,
        attempt_evidence_readback_verified_at=None,
        attempt_evidence_written=False,
        latest_pointer_mutation_status=latest_pointer_mutation_status,
        latest_pointer_mutated_by_publication=latest_pointer_mutated_by_publication,
        availability_receipt_status="VERIFIED",
        blocked_evidence_mutated_latest_pointer=False,
        redis_generation_set_nx_exact_readback_verified=True,
        redis_atomic_predecessor_head_cas_verified=True,
    )


__all__ = [
    "AUTHORIZED_SESSION_RESET_HEAD_CAS",
    "AVAILABLE_AT_OBSERVE_LUA",
    "AtomicScriptExecutor",
    "BLOCKED_ATTEMPT_PUBLISH_LUA",
    "GENERATION_PUBLISH_LUA",
    "GENESIS_ABSENT_HEAD",
    "MAX_LEGACY_PAYLOAD_BYTES",
    "PAPER_OPEN_POSITIONS_LEGACY_KEY",
    "PAPER_POSITIONS_LEGACY_KEY",
    "PAPER_POSITION_STATE_HEAD_KEY",
    "PAPER_POSITION_STATE_POINTER_KEY",
    "PAPER_SESSION_REDIS_KEY",
    "PaperPositionStateError",
    "PaperPositionStateGeneration",
    "PaperPositionStatePublicationError",
    "PaperPositionStatePublicationResult",
    "PaperPositionStateValidationError",
    "READY_POINTER_PUBLISH_LUA",
    "RAW_REDIS_SCRIPT_RESPONSE_MODE",
    "SAME_SESSION_SUCCESSOR_HEAD_CAS",
    "ScriptArgument",
    "build_paper_position_state_generation",
    "publish_paper_position_state_generation",
]
