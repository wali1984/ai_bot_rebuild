"""Atomic publication receipts for prospective liquidation surfaces.

The model deliberately emits a non-authoritative candidate.  This module
authenticates storage and exact consumer reopen only.  It never grants trainer
authority; a later source-admission boundary must independently validate the
per-source provenance and decision-time clocks after Redis has:

1. immutably stored the exact canonical candidate bytes;
2. committed a receipt while those archive bytes still match;
3. advanced a symbol/timeframe latest pointer without clock regression; and
4. atomically reopened the same archive, receipt, and pointer bytes.

The persisted candidate and receipt always retain ``trainer_authority=false``.
The factory-created result remains non-authoritative and deeply immutable.
Missing or degraded inputs are still publishable for diagnostics, but neither
a receipt nor a trainer-eligible pointer can upgrade semantic eligibility.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, Protocol, cast

from . import model as surface_model
from .model import MODEL_VERSION, SCHEMA_VERSION, SEMANTIC_KIND

PUBLICATION_RECEIPT_SCHEMA_VERSION = (
    "v2_prospective_liquidation_surface_postcommit_receipt_v2"
)
PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION = (
    "v2_liquidation_surface_prepared_source_bundle_v1"
)
PUBLICATION_EVIDENCE_CLASSIFICATION = (
    "CONTENT_ADDRESSED_ARCHIVE_RECEIPT_AND_EXACT_CONSUMER_REOPEN_VERIFIED"
)
ARCHIVE_KEY_PREFIX = "v2:liquidation_surface:archive:"
RECEIPT_KEY_PREFIX = "v2:liquidation_surface:receipt:"
OBSERVATION_POINTER_KEY_PREFIX = "v2:liquidation_surface:latest_observation:"
TRAINER_POINTER_KEY_PREFIX = "v2:liquidation_surface:latest_trainer_eligible:"
SURFACE_ID_PREFIX = "v2_lsurf_"

# Resource-integrity ceilings only.  They are not market admission, risk,
# leverage, confidence, or freshness thresholds.
MAX_SURFACE_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_POINTER_BYTES = 256
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 500_000
MAX_JSON_CONTAINER_ITEMS = 250_000
DEFAULT_ARCHIVE_TTL_SECONDS = 86_400
DEFAULT_RECEIPT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 31 * 86_400

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,30}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]{0,14}[smhdw]$", re.ASCII)
_SURFACE_ID_RE = re.compile(r"^v2_lsurf_[0-9a-f]{64}$", re.ASCII)
_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", re.ASCII)
_POINTER_RE = re.compile(
    r"^([0-9]{19}):([0-9]{19}):(v2_lsurf_[0-9a-f]{64})$",
    re.ASCII,
)
_MAX_SIGNED_64_BIT = (1 << 63) - 1
_CONSTRUCTION_TOKEN = object()
_SECURITY_CONTEXT_TOKEN = object()
_VERIFIED_GUARD_TOKEN = object()
MIN_HMAC_KEY_BYTES = 32

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "surface_id",
        "surface_archive_key",
        "surface_receipt_key",
        "observation_pointer_key",
        "trainer_pointer_key",
        "publication_scope_sha256",
        "publication_auth_key_id",
        "archive_payload_sha256",
        "archive_payload_byte_count",
        "model_candidate_archive_payload_sha256",
        "model_candidate_archive_payload_byte_count",
        "model_surface_payload_sha256",
        "trainer_source_bundle_schema_version",
        "trainer_source_bundle_sha256",
        "trainer_storage_candidate_eligible",
        "source_input_sha256",
        "source_input_counts_sha256",
        "model_version",
        "open_interest_source_timeframe",
        "accuracy_class",
        "adaptive_source_valid_until",
        "adaptive_source_valid_until_inclusive",
        "bracket_valid_until",
        "bracket_valid_until_exclusive",
        "publisher_code_sha256",
        "model_code_sha256",
        "publication_config_sha256",
        "archive_ttl_seconds",
        "receipt_ttl_seconds",
        "venue",
        "symbol",
        "timeframe",
        "event_time",
        "feature_cutoff",
        "ingested_at",
        "source_available_at",
        "surface_as_of",
        "generated_at",
        "archive_postcommit_at",
        "trainer_semantic_eligible",
        "archived_trainer_authority",
        "trainer_authority",
        "trainer_authority_reason",
        "postcommit_consumer_reopen_required",
        "receipt_sha256",
        "receipt_hmac_sha256",
    }
)

_PREPARE_ARCHIVE_LUA = r"""
-- liquidation_surface_prepare_archive_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local payload = ARGV[1]
local archive_ttl = tonumber(ARGV[2])
local receipt_ttl = tonumber(ARGV[3])
local max_archive = tonumber(ARGV[4])
local max_receipt = tonumber(ARGV[5])
if not archive_ttl or not receipt_ttl or archive_ttl <= receipt_ttl
   or archive_ttl ~= math.floor(archive_ttl)
   or receipt_ttl ~= math.floor(receipt_ttl) then
  return {"ERROR", "SURFACE_ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL"}
end
if string.len(payload) > max_archive then
  return {"ERROR", "SURFACE_ARCHIVE_ARGUMENT_OVERSIZED"}
end
local archive_type = redis.call("TYPE", archive_key)["ok"]
local status = "PREPARED"
if archive_type == "none" then
  redis.call("SET", archive_key, payload, "EX", archive_ttl)
elseif archive_type == "string" then
  if redis.call("STRLEN", archive_key) > max_archive then
    return {"ERROR", "SURFACE_ARCHIVE_OVERSIZED"}
  end
  if redis.call("GET", archive_key) ~= payload then
    return {"ERROR", "SURFACE_ARCHIVE_IDENTITY_CONFLICT"}
  end
  if redis.call("EXPIRE", archive_key, archive_ttl) ~= 1 then
    return {"ERROR", "SURFACE_ARCHIVE_TTL_REFRESH_FAILED"}
  end
  status = "ADOPTED"
else
  return {"ERROR", "SURFACE_ARCHIVE_TYPE_INVALID"}
end
local existing_receipt = ""
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type == "string" then
  if redis.call("STRLEN", receipt_key) > max_receipt then
    return {"ERROR", "SURFACE_RECEIPT_OVERSIZED"}
  end
  existing_receipt = redis.call("GET", receipt_key)
elseif receipt_type ~= "none" then
  return {"ERROR", "SURFACE_RECEIPT_TYPE_INVALID"}
end
local observed = redis.call("TIME")
return {status, existing_receipt, observed[1], observed[2]}
"""

_COMMIT_RECEIPT_LUA = r"""
-- liquidation_surface_commit_receipt_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local observation_pointer_key = KEYS[3]
local trainer_pointer_key = KEYS[4]
local archive_payload = ARGV[1]
local receipt_payload = ARGV[2]
local pointer_payload = ARGV[3]
local pointer_sort_prefix = ARGV[4]
local expected_observation_pointer = ARGV[5]
local expected_trainer_pointer = ARGV[6]
local trainer_eligible = ARGV[7]
local receipt_ttl = tonumber(ARGV[8])
local max_archive = tonumber(ARGV[9])
local max_receipt = tonumber(ARGV[10])
local max_pointer = tonumber(ARGV[11])
local missing = "__MISSING__"
if string.len(archive_payload) > max_archive then
  return {"ERROR", "SURFACE_ARCHIVE_ARGUMENT_OVERSIZED"}
end
if string.len(receipt_payload) > max_receipt then
  return {"ERROR", "SURFACE_RECEIPT_ARGUMENT_OVERSIZED"}
end
if string.len(pointer_payload) > max_pointer then
  return {"ERROR", "SURFACE_POINTER_ARGUMENT_OVERSIZED"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "SURFACE_ARCHIVE_MISSING"}
end
if redis.call("STRLEN", archive_key) > max_archive then
  return {"ERROR", "SURFACE_ARCHIVE_OVERSIZED"}
end
if redis.call("GET", archive_key) ~= archive_payload then
  return {"ERROR", "SURFACE_ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("PTTL", archive_key) <= receipt_ttl * 1000 then
  return {"ERROR", "SURFACE_ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local function current_pointer(key)
  local pointer_type = redis.call("TYPE", key)["ok"]
  if pointer_type == "none" then
    return missing
  end
  if pointer_type ~= "string" then
    return "__TYPE_INVALID__"
  end
  if redis.call("STRLEN", key) > max_pointer then
    return "__OVERSIZED__"
  end
  return redis.call("GET", key)
end
local current_observation = current_pointer(observation_pointer_key)
if current_observation == "__TYPE_INVALID__" then
  return {"ERROR", "SURFACE_OBSERVATION_POINTER_TYPE_INVALID"}
end
if current_observation == "__OVERSIZED__" then
  return {"ERROR", "SURFACE_OBSERVATION_POINTER_OVERSIZED"}
end
if current_observation ~= expected_observation_pointer then
  return {"ERROR", "SURFACE_OBSERVATION_POINTER_PREDECESSOR_MISMATCH"}
end
local current_trainer = current_pointer(trainer_pointer_key)
if current_trainer == "__TYPE_INVALID__" then
  return {"ERROR", "SURFACE_TRAINER_POINTER_TYPE_INVALID"}
end
if current_trainer == "__OVERSIZED__" then
  return {"ERROR", "SURFACE_TRAINER_POINTER_OVERSIZED"}
end
if trainer_eligible == "1" and current_trainer ~= expected_trainer_pointer then
  return {"ERROR", "SURFACE_TRAINER_POINTER_PREDECESSOR_MISMATCH"}
end
local function monotonic_pointer(current)
  if current == missing or current == pointer_payload then
    return nil
  end
  local current_prefix = string.sub(current, 1, string.len(pointer_sort_prefix))
  if current ~= pointer_payload then
    if current_prefix > pointer_sort_prefix then
      return "SURFACE_LATEST_POINTER_REGRESSION_REJECTED"
    end
    if current_prefix == pointer_sort_prefix then
      return "SURFACE_LATEST_POINTER_EQUAL_CLOCK_CONFLICT"
    end
  end
end
local monotonic_error = monotonic_pointer(current_observation)
if monotonic_error then
  return {"ERROR", monotonic_error}
end
if trainer_eligible == "1" then
  monotonic_error = monotonic_pointer(current_trainer)
  if monotonic_error then
    return {"ERROR", monotonic_error}
  end
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
local status = "COMMITTED"
if receipt_type == "none" then
  redis.call("SET", receipt_key, receipt_payload, "EX", receipt_ttl)
elseif receipt_type == "string" then
  if redis.call("STRLEN", receipt_key) > max_receipt then
    return {"ERROR", "SURFACE_RECEIPT_OVERSIZED"}
  end
  if redis.call("GET", receipt_key) ~= receipt_payload then
    return {"ERROR", "SURFACE_RECEIPT_IDENTITY_CONFLICT"}
  end
  if redis.call("EXPIRE", receipt_key, receipt_ttl) ~= 1 then
    return {"ERROR", "SURFACE_RECEIPT_TTL_REFRESH_FAILED"}
  end
  status = "IDEMPOTENT"
else
  return {"ERROR", "SURFACE_RECEIPT_TYPE_INVALID"}
end
-- Bind pointer expiry to the receipt's exact absolute millisecond deadline.
-- Setting both keys with equal relative TTLs in separate commands can let the
-- later pointer outlive the receipt by a millisecond under load.
local expiry_clock = redis.call("TIME")
local receipt_pttl = redis.call("PTTL", receipt_key)
if receipt_pttl <= 0 then
  return {"ERROR", "SURFACE_RECEIPT_TTL_REFRESH_FAILED"}
end
local receipt_deadline_ms = tonumber(expiry_clock[1]) * 1000
  + math.floor(tonumber(expiry_clock[2]) / 1000)
  + receipt_pttl
redis.call("SET", observation_pointer_key, pointer_payload)
if redis.call("PEXPIREAT", observation_pointer_key, receipt_deadline_ms) ~= 1 then
  return {"ERROR", "SURFACE_OBSERVATION_POINTER_TTL_BINDING_FAILED"}
end
if trainer_eligible == "1" then
  redis.call("SET", trainer_pointer_key, pointer_payload)
  if redis.call("PEXPIREAT", trainer_pointer_key, receipt_deadline_ms) ~= 1 then
    return {"ERROR", "SURFACE_TRAINER_POINTER_TTL_BINDING_FAILED"}
  end
end
local observed = redis.call("TIME")
return {status, observed[1], observed[2]}
"""

_READ_POINTER_LUA = r"""
-- liquidation_surface_read_pointer_v1
local pointer_key = KEYS[1]
local maximum = tonumber(ARGV[1])
local pointer_type = redis.call("TYPE", pointer_key)["ok"]
if pointer_type == "none" then
  local missing_observed = redis.call("TIME")
  return {"MISSING", "", missing_observed[1], missing_observed[2]}
end
if pointer_type ~= "string" then
  return {"ERROR", "SURFACE_LATEST_POINTER_TYPE_INVALID"}
end
if redis.call("STRLEN", pointer_key) > maximum then
  return {"ERROR", "SURFACE_POINTER_OVERSIZED"}
end
local pointer = redis.call("GET", pointer_key)
local observed = redis.call("TIME")
return {"POINTER", pointer, observed[1], observed[2]}
"""

_REOPEN_PUBLICATION_LUA = r"""
-- liquidation_surface_reopen_publication_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local pointer_key = KEYS[3]
local expected_pointer = ARGV[1]
local max_archive = tonumber(ARGV[2])
local max_receipt = tonumber(ARGV[3])
local max_pointer = tonumber(ARGV[4])
if redis.call("TYPE", pointer_key)["ok"] ~= "string" then
  return {"ERROR", "SURFACE_LATEST_POINTER_MISSING"}
end
if redis.call("STRLEN", pointer_key) > max_pointer then
  return {"ERROR", "SURFACE_POINTER_OVERSIZED"}
end
if redis.call("GET", pointer_key) ~= expected_pointer then
  return {"ERROR", "SURFACE_LATEST_POINTER_CHANGED_DURING_REOPEN"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "SURFACE_ARCHIVE_MISSING"}
end
if redis.call("TYPE", receipt_key)["ok"] ~= "string" then
  return {"ERROR", "SURFACE_RECEIPT_MISSING"}
end
if redis.call("STRLEN", archive_key) > max_archive then
  return {"ERROR", "SURFACE_ARCHIVE_OVERSIZED"}
end
if redis.call("STRLEN", receipt_key) > max_receipt then
  return {"ERROR", "SURFACE_RECEIPT_OVERSIZED"}
end
local archive = redis.call("GET", archive_key)
local receipt = redis.call("GET", receipt_key)
local archive_ttl = redis.call("PTTL", archive_key)
local receipt_ttl = redis.call("PTTL", receipt_key)
local pointer_ttl = redis.call("PTTL", pointer_key)
local observed = redis.call("TIME")
return {
  "REOPENED", archive, receipt, archive_ttl, receipt_ttl, pointer_ttl,
  observed[1], observed[2]
}
"""

_POSTVALIDATION_CONFIRM_LUA = r"""
-- liquidation_surface_postvalidation_confirm_v1
local archive_key = KEYS[1]
local receipt_key = KEYS[2]
local pointer_key = KEYS[3]
local expected_pointer = ARGV[1]
local expected_archive = ARGV[2]
local expected_receipt = ARGV[3]
local max_archive = tonumber(ARGV[4])
local max_receipt = tonumber(ARGV[5])
local max_pointer = tonumber(ARGV[6])
if redis.call("TYPE", pointer_key)["ok"] ~= "string"
   or redis.call("STRLEN", pointer_key) > max_pointer
   or redis.call("GET", pointer_key) ~= expected_pointer then
  return {"ERROR", "SURFACE_POINTER_CHANGED_AFTER_VALIDATION"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string"
   or redis.call("STRLEN", archive_key) > max_archive
   or redis.call("GET", archive_key) ~= expected_archive then
  return {"ERROR", "SURFACE_ARCHIVE_CHANGED_AFTER_VALIDATION"}
end
if redis.call("TYPE", receipt_key)["ok"] ~= "string"
   or redis.call("STRLEN", receipt_key) > max_receipt
   or redis.call("GET", receipt_key) ~= expected_receipt then
  return {"ERROR", "SURFACE_RECEIPT_CHANGED_AFTER_VALIDATION"}
end
local archive_ttl = redis.call("PTTL", archive_key)
local receipt_ttl = redis.call("PTTL", receipt_key)
local pointer_ttl = redis.call("PTTL", pointer_key)
if archive_ttl <= receipt_ttl or archive_ttl <= pointer_ttl
   or receipt_ttl < pointer_ttl or receipt_ttl <= 0 or pointer_ttl <= 0 then
  return {"ERROR", "SURFACE_PUBLICATION_TTL_RELATIONSHIP_INVALID"}
end
local observed = redis.call("TIME")
return {"CONFIRMED", observed[1], observed[2]}
"""


class RedisSurfacePublicationClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class SurfacePublicationError(RuntimeError):
    """Base publication failure."""


class SurfacePublicationValidationError(SurfacePublicationError):
    """Caller-supplied surface or identity violates the contract."""


class SurfacePublicationIntegrityError(SurfacePublicationError):
    """Persisted Redis state is missing, conflicting, or malformed."""


class SurfacePublicationTransportError(SurfacePublicationError):
    """Redis did not execute the bounded atomic protocol."""


@dataclass(frozen=True, slots=True)
class SurfacePublicationSecurityContext:
    """Secret-safe account scope plus an unpublished receipt-auth key."""

    publication_scope_sha256: str
    auth_key_id: str
    hmac_key: bytes = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _SECURITY_CONTEXT_TOKEN:
            _validation_error("SURFACE_PUBLICATION_SECURITY_CONTEXT_FACTORY_REQUIRED")


@dataclass(frozen=True, slots=True)
class _VerifiedSurfaceGuard:
    expected_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def verify(self, value: VerifiedLiquidationSurface) -> bool:
        return bool(
            self._construction_token is _VERIFIED_GUARD_TOKEN
            and _valid_sha256(self.expected_sha256)
            and hmac.compare_digest(
                self.expected_sha256,
                _verified_surface_sha256(_verified_surface_material(value)),
            )
        )


@dataclass(frozen=True, slots=True)
class VerifiedLiquidationSurface:
    """Factory-only, non-authoritative exact archive/receipt/pointer reopen."""

    surface_id: str
    surface_archive_key: str
    surface_receipt_key: str
    latest_pointer_key: str
    publication_scope_sha256: str
    pointer_class: str
    archive_payload_sha256: str
    receipt_sha256: str
    archive_postcommit_at_ms: int
    redis_reopened_at_ms: int
    consumer_reopened_at_ms: int
    trainer_authority: bool
    trainer_authority_reason: str
    payload: Mapping[str, Any] = field(repr=False)
    receipt: Mapping[str, Any] = field(repr=False)
    _integrity_guard: _VerifiedSurfaceGuard | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _construction_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _validation_error("SURFACE_PUBLICATION_FACTORY_CONSTRUCTION_REQUIRED")
        if (
            self.payload.get("postcommit_receipt_bound") is not True
            or self.payload.get("trainer_authority") is not self.trainer_authority
            or self.payload.get("available_at") != self.consumer_reopened_at_ms
            or self.redis_reopened_at_ms > self.consumer_reopened_at_ms
            or self.consumer_reopened_at_ms < self.archive_postcommit_at_ms
            or self.pointer_class not in {"trainer_eligible", "observation"}
            or self.trainer_authority is not False
            or not isinstance(self._integrity_guard, _VerifiedSurfaceGuard)
            or not self._integrity_guard.verify(self)
        ):
            _validation_error("VERIFIED_SURFACE_AUTHORITY_OR_CLOCK_INVALID")


def _validation_error(reason: str) -> NoReturn:
    raise SurfacePublicationValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise SurfacePublicationIntegrityError(reason) from None


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
        _validation_error("SURFACE_PUBLICATION_CANONICAL_JSON_INVALID")
    if not encoded or len(encoded) > maximum:
        _validation_error("SURFACE_PUBLICATION_CANONICAL_JSON_SIZE_INVALID")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum=MAX_SURFACE_BYTES))


def _plain_frozen_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            cast(str, key): _plain_frozen_json(nested)
            for key, nested in value.items()
        }
    if isinstance(value, tuple | list):
        return [_plain_frozen_json(nested) for nested in value]
    return value


def _verified_surface_material(value: VerifiedLiquidationSurface) -> dict[str, Any]:
    return {
        "surface_id": value.surface_id,
        "surface_archive_key": value.surface_archive_key,
        "surface_receipt_key": value.surface_receipt_key,
        "latest_pointer_key": value.latest_pointer_key,
        "publication_scope_sha256": value.publication_scope_sha256,
        "pointer_class": value.pointer_class,
        "archive_payload_sha256": value.archive_payload_sha256,
        "receipt_sha256": value.receipt_sha256,
        "archive_postcommit_at_ms": value.archive_postcommit_at_ms,
        "redis_reopened_at_ms": value.redis_reopened_at_ms,
        "consumer_reopened_at_ms": value.consumer_reopened_at_ms,
        "trainer_authority": value.trainer_authority,
        "trainer_authority_reason": value.trainer_authority_reason,
        "payload": _plain_frozen_json(value.payload),
        "receipt": _plain_frozen_json(value.receipt),
    }


def _verified_surface_sha256(value: object) -> str:
    return _sha256_bytes(
        _canonical_json_bytes(
            value,
            maximum=MAX_SURFACE_BYTES + MAX_RECEIPT_BYTES + 16_384,
        )
    )


def _verified_surface_guard(material: Mapping[str, Any]) -> _VerifiedSurfaceGuard:
    return _VerifiedSurfaceGuard(
        expected_sha256=_verified_surface_sha256(_plain_frozen_json(material)),
        _construction_token=_VERIFIED_GUARD_TOKEN,
    )


def _model_stable_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation_error("SURFACE_PUBLICATION_MODEL_CANONICAL_JSON_INVALID")
    if not encoded or len(encoded) > MAX_SURFACE_BYTES:
        _validation_error("SURFACE_PUBLICATION_MODEL_CANONICAL_JSON_SIZE_INVALID")
    return _sha256_bytes(encoded)


def _freeze_json(value: object) -> object:
    """Return an immutable JSON tree for post-verification consumption."""

    if type(value) is dict:
        return MappingProxyType(
            {
                cast(str, key): _freeze_json(nested)
                for key, nested in cast(dict[object, object], value).items()
            }
        )
    if type(value) is list:
        return tuple(_freeze_json(nested) for nested in cast(list[object], value))
    return value


def derive_publication_scope_sha256(scope_metadata: Mapping[str, Any]) -> str:
    """Hash the secret-free authenticated bracket-account scope metadata."""

    if not isinstance(scope_metadata, Mapping):
        _validation_error("SURFACE_PUBLICATION_SCOPE_METADATA_MAPPING_REQUIRED")
    material = dict(scope_metadata)
    required = {
        "credential_binding_id",
        "exchange_environment",
        "base_url_origin",
        "evidence_auth_key_id",
        "credential_account_specific",
    }
    if not required.issubset(material) or material.get("credential_account_specific") is not True:
        _validation_error("SURFACE_PUBLICATION_SCOPE_METADATA_INCOMPLETE")
    if any(
        token in str(key).strip().lower()
        for key in material
        for token in ("secret", "api_key", "hmac_key", "password", "token")
    ):
        _validation_error("SURFACE_PUBLICATION_SCOPE_METADATA_CONTAINS_SECRET_FIELD")
    _validate_json_tree(material)
    return _stable_sha256(material)


def build_surface_publication_security_context(
    *,
    scope_metadata: Mapping[str, Any],
    hmac_key: str | bytes | bytearray,
    auth_key_id: str,
) -> SurfacePublicationSecurityContext:
    scope = derive_publication_scope_sha256(scope_metadata)
    if type(auth_key_id) is not str or _AUTH_KEY_ID_RE.fullmatch(auth_key_id) is None:
        _validation_error("SURFACE_PUBLICATION_AUTH_KEY_ID_INVALID")
    if isinstance(hmac_key, str):
        key = hmac_key.encode("utf-8")
    elif isinstance(hmac_key, bytes | bytearray):
        key = bytes(hmac_key)
    else:
        key = b""
    if len(key) < MIN_HMAC_KEY_BYTES:
        _validation_error("SURFACE_PUBLICATION_HMAC_KEY_MISSING_OR_TOO_SHORT")
    return SurfacePublicationSecurityContext(
        publication_scope_sha256=scope,
        auth_key_id=auth_key_id,
        hmac_key=key,
        _construction_token=_SECURITY_CONTEXT_TOKEN,
    )


def _security_context(value: object) -> SurfacePublicationSecurityContext:
    if (
        not isinstance(value, SurfacePublicationSecurityContext)
        or value._construction_token is not _SECURITY_CONTEXT_TOKEN
        or len(value.hmac_key) < MIN_HMAC_KEY_BYTES
        or _AUTH_KEY_ID_RE.fullmatch(value.auth_key_id) is None
    ):
        _validation_error("SURFACE_PUBLICATION_SECURITY_CONTEXT_INVALID")
    _publication_scope(value.publication_scope_sha256)
    return value


def _publication_scope(value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(cast(str, value)) is None:
        _validation_error("SURFACE_PUBLICATION_SCOPE_SHA256_INVALID")
    return cast(str, value)


def _source_file_sha256(path: object) -> str:
    try:
        return _sha256_bytes(Path(cast(str, path)).read_bytes())
    except (OSError, TypeError, ValueError) as exc:
        raise SurfacePublicationValidationError(
            "SURFACE_PUBLICATION_CODE_HASH_UNAVAILABLE"
        ) from exc


def _publication_code_hashes() -> tuple[str, str]:
    return _source_file_sha256(__file__), _source_file_sha256(surface_model.__file__)


def _publication_config_sha256(
    *,
    publication_scope_sha256: str,
    archive_ttl_seconds: int,
    receipt_ttl_seconds: int,
) -> str:
    return _stable_sha256(
        {
            "schema_version": PUBLICATION_RECEIPT_SCHEMA_VERSION,
            "publication_scope_sha256": publication_scope_sha256,
            "archive_ttl_seconds": archive_ttl_seconds,
            "receipt_ttl_seconds": receipt_ttl_seconds,
            "max_surface_bytes": MAX_SURFACE_BYTES,
            "max_receipt_bytes": MAX_RECEIPT_BYTES,
            "max_pointer_bytes": MAX_POINTER_BYTES,
            "archive_key_prefix": ARCHIVE_KEY_PREFIX,
            "receipt_key_prefix": RECEIPT_KEY_PREFIX,
            "observation_pointer_key_prefix": OBSERVATION_POINTER_KEY_PREFIX,
            "trainer_pointer_key_prefix": TRAINER_POINTER_KEY_PREFIX,
            "degraded_surface_pointer_policy": "OBSERVATION_ONLY",
        }
    )


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _validation_error("SURFACE_PUBLICATION_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    _validation_error("SURFACE_PUBLICATION_JSON_NONFINITE")


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            _validation_error("SURFACE_PUBLICATION_JSON_RESOURCE_LIMIT")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > MAX_JSON_CONTAINER_ITEMS:
                _validation_error("SURFACE_PUBLICATION_JSON_RESOURCE_LIMIT")
            for key, nested in mapping.items():
                if type(key) is not str:
                    _validation_error("SURFACE_PUBLICATION_JSON_KEY_INVALID")
                stack.append((nested, depth + 1))
        elif type(item) is list:
            sequence = cast(list[object], item)
            if len(sequence) > MAX_JSON_CONTAINER_ITEMS:
                _validation_error("SURFACE_PUBLICATION_JSON_RESOURCE_LIMIT")
            stack.extend((nested, depth + 1) for nested in sequence)
        elif item is None or type(item) in (str, bool, int, float):
            if type(item) is float and not math.isfinite(cast(float, item)):
                _validation_error("SURFACE_PUBLICATION_JSON_NONFINITE")
        else:
            _validation_error("SURFACE_PUBLICATION_JSON_TYPE_INVALID")


def _parse_json_object(raw_value: object, *, maximum: int) -> tuple[dict[str, Any], bytes]:
    if type(raw_value) is bytes:
        raw = cast(bytes, raw_value)
    elif type(raw_value) is str:
        try:
            raw = cast(str, raw_value).encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _validation_error("SURFACE_PUBLICATION_JSON_UTF8_INVALID")
    else:
        _validation_error("SURFACE_PUBLICATION_JSON_PAYLOAD_TYPE_INVALID")
    if not raw or len(raw) > maximum:
        _validation_error("SURFACE_PUBLICATION_JSON_PAYLOAD_SIZE_INVALID")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        _validation_error("SURFACE_PUBLICATION_JSON_PARSE_FAILED")
    if type(parsed) is not dict:
        _validation_error("SURFACE_PUBLICATION_JSON_OBJECT_REQUIRED")
    _validate_json_tree(parsed)
    canonical = _canonical_json_bytes(parsed, maximum=maximum)
    if raw != canonical:
        _validation_error("SURFACE_PUBLICATION_JSON_NOT_CANONICAL")
    return cast(dict[str, Any], parsed), raw


def _positive_int(value: object, *, name: str) -> int:
    if type(value) is not int or not 0 < cast(int, value) <= _MAX_SIGNED_64_BIT:
        _validation_error(f"{name}_NOT_POSITIVE_SIGNED_64_BIT_INTEGER")
    return cast(int, value)


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(cast(str, value)) is not None


def _identity(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    venue = payload.get("venue")
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe")
    if venue != "binance_usdm":
        _validation_error("SURFACE_PUBLICATION_VENUE_INVALID")
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(cast(str, symbol)) is None:
        _validation_error("SURFACE_PUBLICATION_SYMBOL_INVALID")
    if type(timeframe) is not str or _TIMEFRAME_RE.fullmatch(cast(str, timeframe)) is None:
        _validation_error("SURFACE_PUBLICATION_TIMEFRAME_INVALID")
    return cast(str, venue), cast(str, symbol), cast(str, timeframe)


def _model_candidate_and_source_bundle_metadata(
    payload: Mapping[str, Any],
) -> tuple[bytes, str | None, bool]:
    """Separate the model candidate from its non-model exact-source archive."""

    candidate = dict(payload)
    raw_bundle = candidate.pop("trainer_source_bundle", None)
    candidate_raw = _canonical_json_bytes(candidate, maximum=MAX_SURFACE_BYTES)
    if raw_bundle is None:
        return candidate_raw, None, False
    if type(raw_bundle) is not dict:
        _validation_error("SURFACE_PREPARED_SOURCE_BUNDLE_OBJECT_REQUIRED")
    bundle = cast(dict[str, Any], raw_bundle)
    bundle_sha = bundle.get("bundle_sha256")
    unsigned = dict(bundle)
    unsigned.pop("bundle_sha256", None)
    if (
        bundle.get("schema_version") != PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION
        or not _valid_sha256(bundle_sha)
        or bundle_sha != _stable_sha256(unsigned)
        or bundle.get("candidate_archive_payload_sha256")
        != _sha256_bytes(candidate_raw)
        or bundle.get("candidate_surface_payload_sha256")
        != payload.get("surface_payload_sha256")
        or bundle.get("source_input_sha256") != payload.get("source_input_sha256")
        or bundle.get("trainer_authority") is not False
        or bundle.get("prediction_authority") is not False
        or bundle.get("paper_trading_authority") is not False
        or bundle.get("live_execution_authority") is not False
    ):
        _validation_error("SURFACE_PREPARED_SOURCE_BUNDLE_BINDING_INVALID")
    return candidate_raw, cast(str, bundle_sha), True


def _validate_surface_payload(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("model_version") != MODEL_VERSION
        or payload.get("liquidation_semantic_kind") != SEMANTIC_KIND
        or payload.get("market_scope") != "modeled_aggregate_open_position_cohorts"
        or payload.get("not_position_exact") is not True
        or payload.get("forced_liquidation_events_used_as_level_source") is not False
        or payload.get("trainer_authority") is not False
        or payload.get("available_at") is not None
        or payload.get("postcommit_receipt_bound") is not False
    ):
        _validation_error("SURFACE_PUBLICATION_CANDIDATE_CONTRACT_INVALID")
    _identity(payload)
    stack: list[object] = [payload]
    scanned = 0
    while stack:
        current = stack.pop()
        scanned += 1
        if scanned > MAX_JSON_NODES:
            _validation_error("SURFACE_PUBLICATION_AUTHORITY_SCAN_RESOURCE_LIMIT")
        if isinstance(current, Mapping):
            for raw_key, nested in current.items():
                key = str(raw_key).strip().lower()
                if (key == "authority" or key.endswith("_authority")) and nested is not False:
                    _validation_error("SURFACE_PUBLICATION_UNVERIFIED_AUTHORITY_CLAIM")
                if isinstance(nested, Mapping | list | tuple):
                    stack.append(nested)
        elif isinstance(current, list | tuple):
            stack.extend(
                nested for nested in current if isinstance(nested, Mapping | list | tuple)
            )
    if not _valid_sha256(payload.get("source_input_sha256")):
        _validation_error("SURFACE_PUBLICATION_SOURCE_INPUT_SHA256_INVALID")
    source_counts = payload.get("source_input_counts")
    if type(source_counts) is not dict or not source_counts or any(
        type(value) is not int or cast(int, value) < 0
        for value in cast(dict[object, object], source_counts).values()
    ):
        _validation_error("SURFACE_PUBLICATION_SOURCE_INPUT_COUNTS_INVALID")
    model_hash = payload.get("surface_payload_sha256")
    if not _valid_sha256(model_hash):
        _validation_error("SURFACE_PUBLICATION_MODEL_PAYLOAD_SHA256_INVALID")
    unsigned = dict(payload)
    unsigned.pop("surface_payload_sha256", None)
    unsigned.pop("trainer_source_bundle", None)
    if model_hash != _model_stable_sha256(unsigned):
        _validation_error("SURFACE_PUBLICATION_MODEL_PAYLOAD_SHA256_MISMATCH")
    _model_candidate_and_source_bundle_metadata(payload)
    clocks = {
        name: _positive_int(payload.get(name), name=f"SURFACE_PUBLICATION_{name.upper()}")
        for name in (
            "event_time",
            "feature_cutoff",
            "ingested_at",
            "source_available_at",
            "surface_as_of",
            "generated_at",
        )
    }
    if not (
        clocks["event_time"] <= clocks["ingested_at"]
        and clocks["feature_cutoff"] <= clocks["ingested_at"]
        and clocks["ingested_at"] <= clocks["source_available_at"]
        and clocks["source_available_at"] <= clocks["surface_as_of"]
        and clocks["surface_as_of"] <= clocks["generated_at"]
    ):
        _validation_error("SURFACE_PUBLICATION_SOURCE_CLOCK_ORDER_INVALID")
    long_levels = payload.get("long_levels")
    short_levels = payload.get("short_levels")
    if type(long_levels) is not list or type(short_levels) is not list:
        _validation_error("SURFACE_PUBLICATION_LEVEL_LIST_INVALID")
    if (
        payload.get("long_level_count") != len(cast(list[object], long_levels))
        or payload.get("short_level_count") != len(cast(list[object], short_levels))
    ):
        _validation_error("SURFACE_PUBLICATION_LEVEL_COUNT_MISMATCH")
    eligible = payload.get("trainer_semantic_eligible")
    if type(eligible) is not bool:
        _validation_error("SURFACE_PUBLICATION_SEMANTIC_ELIGIBILITY_INVALID")
    if eligible is True:
        adaptive_valid_until = payload.get("adaptive_source_valid_until")
        bracket_valid_until = payload.get("bracket_valid_until")
        if (
            not long_levels
            or not short_levels
            or payload.get("trainer_authority_reason")
            != "POSTCOMMIT_CONSUMER_RECEIPT_REQUIRED"
            or payload.get("accuracy_class")
            != "EXCHANGE_GEOMETRY_MARKET_COHORT_ESTIMATE"
            or type(adaptive_valid_until) is not int
            or cast(int, adaptive_valid_until) < clocks["generated_at"]
            or payload.get("adaptive_source_valid_until_inclusive") is not True
            or type(bracket_valid_until) is not int
            or cast(int, bracket_valid_until) <= clocks["generated_at"]
            or payload.get("bracket_valid_until_exclusive") is not True
        ):
            _validation_error("SURFACE_PUBLICATION_ELIGIBLE_CANDIDATE_INVALID")
    for name in ("adaptive_source_valid_until", "bracket_valid_until"):
        value = payload.get(name)
        if value is not None and (
            type(value) is not int or not 0 < cast(int, value) <= _MAX_SIGNED_64_BIT
        ):
            _validation_error(f"SURFACE_PUBLICATION_{name.upper()}_INVALID")


def _surface_bytes(surface: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    if not isinstance(surface, Mapping):
        _validation_error("SURFACE_PUBLICATION_MAPPING_REQUIRED")
    material = dict(surface)
    _validate_json_tree(material)
    _validate_surface_payload(material)
    raw = _canonical_json_bytes(material, maximum=MAX_SURFACE_BYTES)
    return material, raw


def _surface_id(raw: bytes) -> str:
    return f"{SURFACE_ID_PREFIX}{_sha256_bytes(raw)}"


def _keys(
    surface_id: str,
    *,
    publication_scope_sha256: str,
    symbol: str,
    timeframe: str,
) -> tuple[str, str, str, str]:
    if _SURFACE_ID_RE.fullmatch(surface_id) is None:
        _validation_error("SURFACE_PUBLICATION_ID_INVALID")
    scope = _publication_scope(publication_scope_sha256)
    return (
        f"{ARCHIVE_KEY_PREFIX}{surface_id}",
        f"{RECEIPT_KEY_PREFIX}{scope}:{surface_id}",
        f"{OBSERVATION_POINTER_KEY_PREFIX}{scope}:{symbol}:{timeframe}",
        f"{TRAINER_POINTER_KEY_PREFIX}{scope}:{symbol}:{timeframe}",
    )


def _pointer(payload: Mapping[str, Any], surface_id: str) -> tuple[str, str]:
    surface_as_of = _positive_int(
        payload.get("surface_as_of"), name="SURFACE_PUBLICATION_SURFACE_AS_OF"
    )
    generated_at = _positive_int(
        payload.get("generated_at"), name="SURFACE_PUBLICATION_GENERATED_AT"
    )
    value = f"{surface_as_of:019d}:{generated_at:019d}:{surface_id}"
    return value, value[:39]


def _parse_pointer(value: object) -> tuple[str, int, int, str]:
    if isinstance(value, bytes):
        try:
            text = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            _integrity_error("SURFACE_POINTER_ENCODING_INVALID")
    elif type(value) is str:
        text = cast(str, value)
    else:
        _integrity_error("SURFACE_POINTER_TYPE_INVALID")
    if len(text.encode("ascii", errors="ignore")) > MAX_POINTER_BYTES:
        _integrity_error("SURFACE_POINTER_OVERSIZED")
    matched = _POINTER_RE.fullmatch(text)
    if matched is None:
        _integrity_error("SURFACE_POINTER_CONTRACT_INVALID")
    as_of = int(matched.group(1))
    generated = int(matched.group(2))
    if not 0 < as_of <= generated <= _MAX_SIGNED_64_BIT:
        _integrity_error("SURFACE_POINTER_CLOCK_ORDER_INVALID")
    return text, as_of, generated, matched.group(3)


def _ttl(value: object, *, name: str) -> int:
    if type(value) is not int or not 0 < cast(int, value) <= MAX_TTL_SECONDS:
        _validation_error(f"{name}_INVALID")
    return cast(int, value)


def _build_receipt(
    *,
    payload: Mapping[str, Any],
    raw: bytes,
    surface_id: str,
    archive_key: str,
    receipt_key: str,
    observation_pointer_key: str,
    trainer_pointer_key: str,
    security_context: SurfacePublicationSecurityContext,
    archive_ttl_seconds: int,
    receipt_ttl_seconds: int,
    archive_postcommit_at_ms: int,
) -> tuple[dict[str, Any], bytes]:
    context = _security_context(security_context)
    publication_scope_sha256 = context.publication_scope_sha256
    eligible = cast(bool, payload["trainer_semantic_eligible"])
    candidate_raw, source_bundle_sha256, source_bundle_present = (
        _model_candidate_and_source_bundle_metadata(payload)
    )
    source_bundle = payload.get("trainer_source_bundle")
    if source_bundle_present and cast(Mapping[str, Any], source_bundle).get(
        "publication_scope_sha256"
    ) != publication_scope_sha256:
        _validation_error("SURFACE_PREPARED_SOURCE_BUNDLE_SCOPE_MISMATCH")
    trainer_storage_candidate_eligible = eligible and source_bundle_present
    reason = (
        "POSTCOMMIT_CONSUMER_REOPEN_REQUIRED"
        if trainer_storage_candidate_eligible
        else "TRAINER_EXACT_SOURCE_BUNDLE_REQUIRED"
        if eligible
        else cast(str, payload.get("trainer_authority_reason"))
    )
    publisher_code_sha256, model_code_sha256 = _publication_code_hashes()
    receipt: dict[str, Any] = {
        "schema_version": PUBLICATION_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": PUBLICATION_EVIDENCE_CLASSIFICATION,
        "surface_id": surface_id,
        "surface_archive_key": archive_key,
        "surface_receipt_key": receipt_key,
        "observation_pointer_key": observation_pointer_key,
        "trainer_pointer_key": trainer_pointer_key,
        "publication_scope_sha256": publication_scope_sha256,
        "publication_auth_key_id": context.auth_key_id,
        "archive_payload_sha256": _sha256_bytes(raw),
        "archive_payload_byte_count": len(raw),
        "model_candidate_archive_payload_sha256": _sha256_bytes(candidate_raw),
        "model_candidate_archive_payload_byte_count": len(candidate_raw),
        "model_surface_payload_sha256": payload["surface_payload_sha256"],
        "trainer_source_bundle_schema_version": (
            PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION if source_bundle_present else None
        ),
        "trainer_source_bundle_sha256": source_bundle_sha256,
        "trainer_storage_candidate_eligible": trainer_storage_candidate_eligible,
        "source_input_sha256": payload["source_input_sha256"],
        "source_input_counts_sha256": _stable_sha256(payload["source_input_counts"]),
        "model_version": payload["model_version"],
        "open_interest_source_timeframe": payload["open_interest_source_timeframe"],
        "accuracy_class": payload["accuracy_class"],
        "adaptive_source_valid_until": payload["adaptive_source_valid_until"],
        "adaptive_source_valid_until_inclusive": payload[
            "adaptive_source_valid_until_inclusive"
        ],
        "bracket_valid_until": payload["bracket_valid_until"],
        "bracket_valid_until_exclusive": payload["bracket_valid_until_exclusive"],
        "publisher_code_sha256": publisher_code_sha256,
        "model_code_sha256": model_code_sha256,
        "publication_config_sha256": _publication_config_sha256(
            publication_scope_sha256=publication_scope_sha256,
            archive_ttl_seconds=archive_ttl_seconds,
            receipt_ttl_seconds=receipt_ttl_seconds,
        ),
        "archive_ttl_seconds": archive_ttl_seconds,
        "receipt_ttl_seconds": receipt_ttl_seconds,
        "venue": payload["venue"],
        "symbol": payload["symbol"],
        "timeframe": payload["timeframe"],
        "event_time": payload["event_time"],
        "feature_cutoff": payload["feature_cutoff"],
        "ingested_at": payload["ingested_at"],
        "source_available_at": payload["source_available_at"],
        "surface_as_of": payload["surface_as_of"],
        "generated_at": payload["generated_at"],
        "archive_postcommit_at": archive_postcommit_at_ms,
        "trainer_semantic_eligible": eligible,
        "archived_trainer_authority": False,
        "trainer_authority": False,
        "trainer_authority_reason": reason,
        "postcommit_consumer_reopen_required": True,
    }
    receipt["receipt_sha256"] = _stable_sha256(receipt)
    receipt["receipt_hmac_sha256"] = hmac.new(
        context.hmac_key,
        _canonical_json_bytes(receipt, maximum=MAX_RECEIPT_BYTES),
        hashlib.sha256,
    ).hexdigest()
    return receipt, _canonical_json_bytes(receipt, maximum=MAX_RECEIPT_BYTES)


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    raw: bytes,
    surface_id: str,
    archive_key: str,
    receipt_key: str,
    observation_pointer_key: str,
    trainer_pointer_key: str,
    security_context: SurfacePublicationSecurityContext,
) -> None:
    context = _security_context(security_context)
    publication_scope_sha256 = context.publication_scope_sha256
    if set(receipt) != _RECEIPT_FIELDS:
        _integrity_error("SURFACE_RECEIPT_FIELDS_INVALID")
    receipt_hash = receipt.get("receipt_sha256")
    receipt_hmac = receipt.get("receipt_hmac_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    unsigned.pop("receipt_hmac_sha256", None)
    if not _valid_sha256(receipt_hash) or receipt_hash != _stable_sha256(unsigned):
        _integrity_error("SURFACE_RECEIPT_SHA256_INVALID")
    hmac_material = dict(receipt)
    hmac_material.pop("receipt_hmac_sha256", None)
    expected_hmac = hmac.new(
        context.hmac_key,
        _canonical_json_bytes(hmac_material, maximum=MAX_RECEIPT_BYTES),
        hashlib.sha256,
    ).hexdigest()
    if (
        not _valid_sha256(receipt_hmac)
        or not hmac.compare_digest(cast(str, receipt_hmac), expected_hmac)
    ):
        _integrity_error("SURFACE_RECEIPT_HMAC_INVALID")
    archive_ttl_seconds = receipt.get("archive_ttl_seconds")
    receipt_ttl_seconds = receipt.get("receipt_ttl_seconds")
    if (
        type(archive_ttl_seconds) is not int
        or type(receipt_ttl_seconds) is not int
        or not 0 < cast(int, receipt_ttl_seconds) < cast(int, archive_ttl_seconds)
        or cast(int, archive_ttl_seconds) > MAX_TTL_SECONDS
    ):
        _integrity_error("SURFACE_RECEIPT_TTL_CONFIG_INVALID")
    publisher_code_sha256, model_code_sha256 = _publication_code_hashes()
    candidate_raw, source_bundle_sha256, source_bundle_present = (
        _model_candidate_and_source_bundle_metadata(payload)
    )
    source_bundle = payload.get("trainer_source_bundle")
    if source_bundle_present and cast(Mapping[str, Any], source_bundle).get(
        "publication_scope_sha256"
    ) != publication_scope_sha256:
        _integrity_error("SURFACE_PREPARED_SOURCE_BUNDLE_SCOPE_MISMATCH")
    trainer_storage_candidate_eligible = bool(
        payload["trainer_semantic_eligible"] is True and source_bundle_present
    )
    expected = {
        "schema_version": PUBLICATION_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": PUBLICATION_EVIDENCE_CLASSIFICATION,
        "surface_id": surface_id,
        "surface_archive_key": archive_key,
        "surface_receipt_key": receipt_key,
        "observation_pointer_key": observation_pointer_key,
        "trainer_pointer_key": trainer_pointer_key,
        "publication_scope_sha256": publication_scope_sha256,
        "publication_auth_key_id": context.auth_key_id,
        "archive_payload_sha256": _sha256_bytes(raw),
        "archive_payload_byte_count": len(raw),
        "model_candidate_archive_payload_sha256": _sha256_bytes(candidate_raw),
        "model_candidate_archive_payload_byte_count": len(candidate_raw),
        "model_surface_payload_sha256": payload["surface_payload_sha256"],
        "trainer_source_bundle_schema_version": (
            PREPARED_SOURCE_BUNDLE_SCHEMA_VERSION if source_bundle_present else None
        ),
        "trainer_source_bundle_sha256": source_bundle_sha256,
        "trainer_storage_candidate_eligible": trainer_storage_candidate_eligible,
        "source_input_sha256": payload["source_input_sha256"],
        "source_input_counts_sha256": _stable_sha256(payload["source_input_counts"]),
        "model_version": payload["model_version"],
        "open_interest_source_timeframe": payload["open_interest_source_timeframe"],
        "accuracy_class": payload["accuracy_class"],
        "adaptive_source_valid_until": payload["adaptive_source_valid_until"],
        "adaptive_source_valid_until_inclusive": payload[
            "adaptive_source_valid_until_inclusive"
        ],
        "bracket_valid_until": payload["bracket_valid_until"],
        "bracket_valid_until_exclusive": payload["bracket_valid_until_exclusive"],
        "publisher_code_sha256": publisher_code_sha256,
        "model_code_sha256": model_code_sha256,
        "publication_config_sha256": _publication_config_sha256(
            publication_scope_sha256=publication_scope_sha256,
            archive_ttl_seconds=cast(int, archive_ttl_seconds),
            receipt_ttl_seconds=cast(int, receipt_ttl_seconds),
        ),
        "archive_ttl_seconds": archive_ttl_seconds,
        "receipt_ttl_seconds": receipt_ttl_seconds,
        "venue": payload["venue"],
        "symbol": payload["symbol"],
        "timeframe": payload["timeframe"],
        "event_time": payload["event_time"],
        "feature_cutoff": payload["feature_cutoff"],
        "ingested_at": payload["ingested_at"],
        "source_available_at": payload["source_available_at"],
        "surface_as_of": payload["surface_as_of"],
        "generated_at": payload["generated_at"],
        "trainer_semantic_eligible": payload["trainer_semantic_eligible"],
        "archived_trainer_authority": False,
        "trainer_authority": False,
        "postcommit_consumer_reopen_required": True,
    }
    if any(receipt.get(name) != value for name, value in expected.items()):
        _integrity_error("SURFACE_RECEIPT_BINDING_INVALID")
    expected_reason = (
        "POSTCOMMIT_CONSUMER_REOPEN_REQUIRED"
        if trainer_storage_candidate_eligible
        else "TRAINER_EXACT_SOURCE_BUNDLE_REQUIRED"
        if payload["trainer_semantic_eligible"] is True
        else payload.get("trainer_authority_reason")
    )
    if receipt.get("trainer_authority_reason") != expected_reason:
        _integrity_error("SURFACE_RECEIPT_AUTHORITY_REASON_INVALID")
    archive_clock = receipt.get("archive_postcommit_at")
    if (
        type(archive_clock) is not int
        or not cast(int, archive_clock) >= cast(int, payload["generated_at"])
        or cast(int, archive_clock) > _MAX_SIGNED_64_BIT
    ):
        _integrity_error("SURFACE_RECEIPT_ARCHIVE_CLOCK_INVALID")


def _response_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _integrity_error("SURFACE_PUBLICATION_REDIS_RESPONSE_ENCODING_INVALID")
    if type(value) is str:
        return cast(str, value)
    _integrity_error("SURFACE_PUBLICATION_REDIS_RESPONSE_TYPE_INVALID")


def _eval(
    redis_client: RedisSurfacePublicationClient,
    script: str,
    keys: Sequence[str],
    arguments: Sequence[object],
) -> list[object]:
    if redis_client is None:
        _validation_error("SURFACE_PUBLICATION_REDIS_CLIENT_REQUIRED")
    try:
        response = redis_client.eval(script, len(keys), *keys, *arguments)
    except Exception as exc:
        raise SurfacePublicationTransportError(
            "SURFACE_PUBLICATION_REDIS_EVAL_FAILED"
        ) from exc
    if type(response) not in (list, tuple):
        _integrity_error("SURFACE_PUBLICATION_REDIS_RESPONSE_INVALID")
    return list(cast(Sequence[object], response))


def _status(response: Sequence[object], *, expected_size: int) -> str:
    if len(response) < 2:
        _integrity_error("SURFACE_PUBLICATION_REDIS_RESPONSE_INVALID")
    status = _response_text(response[0])
    if status == "ERROR":
        _integrity_error(_response_text(response[1]))
    if len(response) != expected_size:
        _integrity_error("SURFACE_PUBLICATION_REDIS_RESPONSE_INVALID")
    return status


def _redis_time_ms(seconds: object, microseconds: object) -> int:
    try:
        if isinstance(seconds, bytes):
            seconds = seconds.decode("ascii", errors="strict")
        if isinstance(microseconds, bytes):
            microseconds = microseconds.decode("ascii", errors="strict")
        if type(seconds) not in (str, int) or type(microseconds) not in (str, int):
            raise ValueError
        second_value = int(cast(str | int, seconds))
        microsecond_value = int(cast(str | int, microseconds))
        if (
            str(second_value) != str(seconds)
            or str(microsecond_value) != str(microseconds)
            or second_value < 0
            or not 0 <= microsecond_value <= 999_999
        ):
            raise ValueError
        result = second_value * 1000 + (microsecond_value + 999) // 1000
    except (OverflowError, UnicodeDecodeError, ValueError):
        _integrity_error("SURFACE_PUBLICATION_REDIS_TIME_INVALID")
    if not 0 < result <= _MAX_SIGNED_64_BIT:
        _integrity_error("SURFACE_PUBLICATION_REDIS_TIME_INVALID")
    return result


def _redis_integer(value: object, *, name: str) -> int:
    try:
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="strict")
        if type(value) not in (str, int):
            raise ValueError
        parsed = int(cast(str | int, value))
        if str(parsed) != str(value):
            raise ValueError
    except (UnicodeDecodeError, ValueError):
        _integrity_error(f"{name}_INVALID")
    return parsed


def _read_pointer(
    redis_client: RedisSurfacePublicationClient,
    *,
    pointer_key: str,
    allow_missing: bool,
) -> tuple[str, int]:
    response = _eval(
        redis_client,
        _READ_POINTER_LUA,
        (pointer_key,),
        (MAX_POINTER_BYTES,),
    )
    status = _status(response, expected_size=4)
    observed_at = _redis_time_ms(response[2], response[3])
    if status == "MISSING":
        if not allow_missing:
            _integrity_error("SURFACE_LATEST_POINTER_MISSING")
        return "__MISSING__", observed_at
    if status != "POINTER":
        _integrity_error("SURFACE_PUBLICATION_POINTER_READ_STATUS_INVALID")
    pointer_text, _as_of, _generated, _surface = _parse_pointer(response[1])
    return pointer_text, observed_at


def _reopen_expected(
    redis_client: RedisSurfacePublicationClient,
    *,
    expected_pointer: str,
    security_context: SurfacePublicationSecurityContext,
    expected_symbol: str,
    expected_timeframe: str,
    pointer_class: str,
    minimum_observed_at_ms: int | None = None,
) -> VerifiedLiquidationSurface:
    context = _security_context(security_context)
    scope = context.publication_scope_sha256
    if pointer_class not in {"trainer_eligible", "observation"}:
        _validation_error("SURFACE_PUBLICATION_POINTER_CLASS_INVALID")
    pointer_text, pointer_as_of, pointer_generated, surface_id = _parse_pointer(
        expected_pointer
    )
    archive_key, receipt_key, observation_pointer_key, trainer_pointer_key = _keys(
        surface_id,
        publication_scope_sha256=scope,
        symbol=expected_symbol,
        timeframe=expected_timeframe,
    )
    pointer_key = (
        trainer_pointer_key if pointer_class == "trainer_eligible" else observation_pointer_key
    )
    response = _eval(
        redis_client,
        _REOPEN_PUBLICATION_LUA,
        (archive_key, receipt_key, pointer_key),
        (expected_pointer, MAX_SURFACE_BYTES, MAX_RECEIPT_BYTES, MAX_POINTER_BYTES),
    )
    if _status(response, expected_size=8) != "REOPENED":
        _integrity_error("SURFACE_PUBLICATION_REOPEN_STATUS_INVALID")
    archive_pttl = _redis_integer(response[3], name="SURFACE_ARCHIVE_PTTL")
    receipt_pttl = _redis_integer(response[4], name="SURFACE_RECEIPT_PTTL")
    pointer_pttl = _redis_integer(response[5], name="SURFACE_POINTER_PTTL")
    if (
        receipt_pttl <= 0
        or pointer_pttl <= 0
        or archive_pttl <= receipt_pttl
        or archive_pttl <= pointer_pttl
        or receipt_pttl < pointer_pttl
    ):
        _integrity_error("SURFACE_PUBLICATION_TTL_RELATIONSHIP_INVALID")
    reopened_at = _redis_time_ms(response[6], response[7])
    if minimum_observed_at_ms is not None and reopened_at < minimum_observed_at_ms:
        _integrity_error("SURFACE_PUBLICATION_REOPEN_CLOCK_REGRESSION")
    try:
        payload, raw = _parse_json_object(response[1], maximum=MAX_SURFACE_BYTES)
        receipt, receipt_raw = _parse_json_object(response[2], maximum=MAX_RECEIPT_BYTES)
        _validate_surface_payload(payload)
    except SurfacePublicationValidationError as exc:
        raise SurfacePublicationIntegrityError(
            f"SURFACE_PUBLICATION_PERSISTED_PAYLOAD_INVALID:{exc}"
        ) from exc
    venue, symbol, timeframe = _identity(payload)
    if (
        venue != "binance_usdm"
        or symbol != expected_symbol
        or timeframe != expected_timeframe
        or payload["surface_as_of"] != pointer_as_of
        or payload["generated_at"] != pointer_generated
        or _surface_id(raw) != surface_id
    ):
        _integrity_error("SURFACE_PUBLICATION_POINTER_PAYLOAD_BINDING_INVALID")
    _validate_receipt(
        receipt,
        payload=payload,
        raw=raw,
        surface_id=surface_id,
        archive_key=archive_key,
        receipt_key=receipt_key,
        observation_pointer_key=observation_pointer_key,
        trainer_pointer_key=trainer_pointer_key,
        security_context=context,
    )
    archive_postcommit = cast(int, receipt["archive_postcommit_at"])
    if reopened_at < archive_postcommit or reopened_at < cast(int, payload["generated_at"]):
        _integrity_error("SURFACE_PUBLICATION_CONSUMER_CLOCK_INVALID")
    if pointer_class == "trainer_eligible" and (
        payload["trainer_semantic_eligible"] is not True
        or receipt.get("trainer_storage_candidate_eligible") is not True
    ):
        _integrity_error("SURFACE_TRAINER_POINTER_NAMES_UNADMITTED_STORAGE_PAYLOAD")
    confirmed = _eval(
        redis_client,
        _POSTVALIDATION_CONFIRM_LUA,
        (archive_key, receipt_key, pointer_key),
        (
            pointer_text,
            raw,
            receipt_raw,
            MAX_SURFACE_BYTES,
            MAX_RECEIPT_BYTES,
            MAX_POINTER_BYTES,
        ),
    )
    if _status(confirmed, expected_size=3) != "CONFIRMED":
        _integrity_error("SURFACE_PUBLICATION_POSTVALIDATION_STATUS_INVALID")
    available_at = _redis_time_ms(confirmed[1], confirmed[2])
    if available_at < reopened_at:
        _integrity_error("SURFACE_PUBLICATION_POSTVALIDATION_CLOCK_REGRESSION")
    trainer_candidate = bool(
        pointer_class == "trainer_eligible"
        and payload["trainer_semantic_eligible"] is True
        and receipt.get("trainer_storage_candidate_eligible") is True
    )
    if trainer_candidate:
        adaptive_valid_until = cast(int, payload["adaptive_source_valid_until"])
        bracket_valid_until = cast(int, payload["bracket_valid_until"])
        if available_at > adaptive_valid_until:
            _integrity_error("SURFACE_ADAPTIVE_SOURCE_FRESHNESS_EXPIRED")
        if available_at >= bracket_valid_until:
            _integrity_error("SURFACE_BRACKET_EVIDENCE_EXPIRED")
    trainer_authority = False
    if trainer_candidate:
        authority_reason = "TRAINER_SOURCE_ADMISSION_AND_DECISION_TIME_REVALIDATION_REQUIRED"
    elif (
        payload["trainer_semantic_eligible"] is True
        and receipt.get("trainer_storage_candidate_eligible") is not True
    ):
        authority_reason = "TRAINER_EXACT_SOURCE_BUNDLE_REQUIRED"
    elif payload["trainer_semantic_eligible"] is True:
        authority_reason = "TRAINER_ELIGIBLE_POINTER_REOPEN_REQUIRED"
    else:
        authority_reason = cast(str, payload.get("trainer_authority_reason"))
    resolved = {
        **payload,
        "available_at": available_at,
        "postcommit_receipt_bound": True,
        "trainer_authority": trainer_authority,
        "trainer_authority_reason": authority_reason,
        "surface_id": surface_id,
        "surface_archive_key": archive_key,
        "surface_receipt_key": receipt_key,
        "publication_scope_sha256": scope,
        "publication_pointer_class": pointer_class,
        "publication_archive_payload_sha256": _sha256_bytes(raw),
        "publication_receipt_sha256": receipt["receipt_sha256"],
        "publication_archive_postcommit_at": archive_postcommit,
        "publication_redis_reopened_at": reopened_at,
        "publication_consumer_reopened_at": available_at,
    }
    values: dict[str, Any] = {
        "surface_id": surface_id,
        "surface_archive_key": archive_key,
        "surface_receipt_key": receipt_key,
        "latest_pointer_key": pointer_key,
        "publication_scope_sha256": scope,
        "pointer_class": pointer_class,
        "archive_payload_sha256": _sha256_bytes(raw),
        "receipt_sha256": cast(str, receipt["receipt_sha256"]),
        "archive_postcommit_at_ms": archive_postcommit,
        "redis_reopened_at_ms": reopened_at,
        "consumer_reopened_at_ms": available_at,
        "trainer_authority": trainer_authority,
        "trainer_authority_reason": authority_reason,
        "payload": cast(Mapping[str, Any], _freeze_json(resolved)),
        "receipt": cast(Mapping[str, Any], _freeze_json(receipt)),
    }
    return VerifiedLiquidationSurface(
        **values,
        _integrity_guard=_verified_surface_guard(values),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def publish_liquidation_surface(
    redis_client: RedisSurfacePublicationClient,
    surface: Mapping[str, Any],
    *,
    security_context: SurfacePublicationSecurityContext,
    archive_ttl_seconds: int = DEFAULT_ARCHIVE_TTL_SECONDS,
    receipt_ttl_seconds: int = DEFAULT_RECEIPT_TTL_SECONDS,
) -> VerifiedLiquidationSurface:
    """Publish and immediately reopen one exact surface, failing closed."""

    archive_ttl = _ttl(archive_ttl_seconds, name="SURFACE_ARCHIVE_TTL_SECONDS")
    receipt_ttl = _ttl(receipt_ttl_seconds, name="SURFACE_RECEIPT_TTL_SECONDS")
    if archive_ttl <= receipt_ttl:
        _validation_error("SURFACE_ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL")
    context = _security_context(security_context)
    scope = context.publication_scope_sha256
    payload, raw = _surface_bytes(surface)
    _candidate_raw, _source_bundle_sha, source_bundle_present = (
        _model_candidate_and_source_bundle_metadata(payload)
    )
    trainer_storage_candidate_eligible = bool(
        payload["trainer_semantic_eligible"] is True and source_bundle_present
    )
    _venue, symbol, timeframe = _identity(payload)
    surface_id = _surface_id(raw)
    archive_key, receipt_key, observation_pointer_key, trainer_pointer_key = _keys(
        surface_id,
        publication_scope_sha256=scope,
        symbol=symbol,
        timeframe=timeframe,
    )
    pointer_value, pointer_sort_prefix = _pointer(payload, surface_id)
    expected_observation_pointer, observation_read_at = _read_pointer(
        redis_client,
        pointer_key=observation_pointer_key,
        allow_missing=True,
    )
    expected_trainer_pointer, trainer_read_at = _read_pointer(
        redis_client,
        pointer_key=trainer_pointer_key,
        allow_missing=True,
    )
    prepared = _eval(
        redis_client,
        _PREPARE_ARCHIVE_LUA,
        (archive_key, receipt_key),
        (raw, archive_ttl, receipt_ttl, MAX_SURFACE_BYTES, MAX_RECEIPT_BYTES),
    )
    if _status(prepared, expected_size=4) not in {"PREPARED", "ADOPTED"}:
        _integrity_error("SURFACE_PUBLICATION_PREPARE_STATUS_INVALID")
    prepare_observed_at = _redis_time_ms(prepared[2], prepared[3])
    if prepare_observed_at < max(observation_read_at, trainer_read_at):
        _integrity_error("SURFACE_PUBLICATION_PREPARE_CLOCK_REGRESSION")
    existing_receipt_raw = prepared[1]
    if existing_receipt_raw not in (b"", ""):
        try:
            existing_receipt, receipt_raw = _parse_json_object(
                existing_receipt_raw,
                maximum=MAX_RECEIPT_BYTES,
            )
        except SurfacePublicationValidationError as exc:
            raise SurfacePublicationIntegrityError(
                f"SURFACE_PUBLICATION_PERSISTED_RECEIPT_INVALID:{exc}"
            ) from exc
        _validate_receipt(
            existing_receipt,
            payload=payload,
            raw=raw,
            surface_id=surface_id,
            archive_key=archive_key,
            receipt_key=receipt_key,
            observation_pointer_key=observation_pointer_key,
            trainer_pointer_key=trainer_pointer_key,
            security_context=context,
        )
        if (
            existing_receipt["archive_ttl_seconds"] != archive_ttl
            or existing_receipt["receipt_ttl_seconds"] != receipt_ttl
        ):
            _integrity_error("SURFACE_RECEIPT_IDEMPOTENT_CONFIG_CONFLICT")
        archive_postcommit_at = cast(int, existing_receipt["archive_postcommit_at"])
    else:
        archive_postcommit_at = prepare_observed_at
        _receipt, receipt_raw = _build_receipt(
            payload=payload,
            raw=raw,
            surface_id=surface_id,
            archive_key=archive_key,
            receipt_key=receipt_key,
            observation_pointer_key=observation_pointer_key,
            trainer_pointer_key=trainer_pointer_key,
            security_context=context,
            archive_ttl_seconds=archive_ttl,
            receipt_ttl_seconds=receipt_ttl,
            archive_postcommit_at_ms=archive_postcommit_at,
        )
    if archive_postcommit_at < cast(int, payload["generated_at"]):
        _integrity_error("SURFACE_PUBLICATION_ARCHIVE_CLOCK_BEFORE_GENERATION")
    if trainer_storage_candidate_eligible:
        if archive_postcommit_at > cast(int, payload["adaptive_source_valid_until"]):
            _integrity_error("SURFACE_ADAPTIVE_SOURCE_FRESHNESS_EXPIRED")
        if archive_postcommit_at >= cast(int, payload["bracket_valid_until"]):
            _integrity_error("SURFACE_BRACKET_EVIDENCE_EXPIRED")
    committed = _eval(
        redis_client,
        _COMMIT_RECEIPT_LUA,
        (archive_key, receipt_key, observation_pointer_key, trainer_pointer_key),
        (
            raw,
            receipt_raw,
            pointer_value,
            pointer_sort_prefix,
            expected_observation_pointer,
            expected_trainer_pointer,
            "1" if trainer_storage_candidate_eligible else "0",
            receipt_ttl,
            MAX_SURFACE_BYTES,
            MAX_RECEIPT_BYTES,
            MAX_POINTER_BYTES,
        ),
    )
    if _status(committed, expected_size=3) not in {"COMMITTED", "IDEMPOTENT"}:
        _integrity_error("SURFACE_PUBLICATION_COMMIT_STATUS_INVALID")
    receipt_commit_at = _redis_time_ms(committed[1], committed[2])
    if receipt_commit_at < archive_postcommit_at:
        _integrity_error("SURFACE_PUBLICATION_RECEIPT_COMMIT_CLOCK_REGRESSION")
    return _reopen_expected(
        redis_client,
        expected_pointer=pointer_value,
        security_context=context,
        expected_symbol=symbol,
        expected_timeframe=timeframe,
        pointer_class=(
            "trainer_eligible"
            if trainer_storage_candidate_eligible
            else "observation"
        ),
        minimum_observed_at_ms=receipt_commit_at,
    )


def reopen_latest_liquidation_surface(
    redis_client: RedisSurfacePublicationClient,
    *,
    symbol: str,
    timeframe: str,
    security_context: SurfacePublicationSecurityContext,
    trainer_eligible_only: bool = True,
) -> VerifiedLiquidationSurface:
    """Resolve and exactly reopen the current symbol/timeframe publication."""

    identity_payload = {
        "venue": "binance_usdm",
        "symbol": symbol,
        "timeframe": timeframe,
    }
    _venue, canonical_symbol, canonical_timeframe = _identity(identity_payload)
    context = _security_context(security_context)
    scope = context.publication_scope_sha256
    if type(trainer_eligible_only) is not bool:
        _validation_error("SURFACE_PUBLICATION_TRAINER_POINTER_FLAG_INVALID")
    prefix = (
        TRAINER_POINTER_KEY_PREFIX
        if trainer_eligible_only
        else OBSERVATION_POINTER_KEY_PREFIX
    )
    pointer_key = f"{prefix}{scope}:{canonical_symbol}:{canonical_timeframe}"
    pointer_text, pointer_read_at = _read_pointer(
        redis_client,
        pointer_key=pointer_key,
        allow_missing=False,
    )
    return _reopen_expected(
        redis_client,
        expected_pointer=pointer_text,
        security_context=context,
        expected_symbol=canonical_symbol,
        expected_timeframe=canonical_timeframe,
        pointer_class="trainer_eligible" if trainer_eligible_only else "observation",
        minimum_observed_at_ms=pointer_read_at,
    )


__all__ = [
    "ARCHIVE_KEY_PREFIX",
    "DEFAULT_ARCHIVE_TTL_SECONDS",
    "DEFAULT_RECEIPT_TTL_SECONDS",
    "MAX_POINTER_BYTES",
    "MAX_RECEIPT_BYTES",
    "MAX_SURFACE_BYTES",
    "MIN_HMAC_KEY_BYTES",
    "OBSERVATION_POINTER_KEY_PREFIX",
    "PUBLICATION_EVIDENCE_CLASSIFICATION",
    "PUBLICATION_RECEIPT_SCHEMA_VERSION",
    "RECEIPT_KEY_PREFIX",
    "RedisSurfacePublicationClient",
    "SurfacePublicationError",
    "SurfacePublicationIntegrityError",
    "SurfacePublicationSecurityContext",
    "SurfacePublicationTransportError",
    "SurfacePublicationValidationError",
    "TRAINER_POINTER_KEY_PREFIX",
    "VerifiedLiquidationSurface",
    "build_surface_publication_security_context",
    "derive_publication_scope_sha256",
    "publish_liquidation_surface",
    "reopen_latest_liquidation_surface",
]
