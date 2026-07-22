"""Adaptive, authenticated Binance USD-M commission-evidence broker.

This is a read-only companion to the account-scoped leverage-bracket evidence
service.  Each invocation may execute at most one signed
``GET /fapi/v1/commissionRate``.  The underlying capture factory owns the
host-shared Binance request-weight reservation (weight 20) and persists the
exact response bytes in immutable CAS *before* decoding JSON.

The broker adds three boundaries which the detached capture intentionally did
not provide:

* an adaptive, one-symbol-at-a-time rotation plan derived from the configured
  host rate budget and the authenticated cache state;
* a Redis pacing claim plus monotonic compare-and-set publication, so multiple
  workers or restarts cannot turn a universe refresh into a request burst or
  replace newer evidence with older evidence; and
* a credentialless consumer interface.  Consumers need the independent local
  evidence HMAC key and read-only CAS access, never Binance API credentials.

The returned evidence grants no trainer, prediction, paper, or live authority.
Downstream cost construction must still bind it to a prospective decision and
perform its own feature/source admission.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_BUDGET_PER_MINUTE_DEFAULT,
    REST_FALLBACK_BUDGET_PER_MINUTE_ENV,
    BinanceCredentialBinding,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    AUTH_ALGORITHM,
    EvidenceSecurityContext,
    LeverageBracketEvidenceError,
    build_evidence_security_context,
    exchange_environment_from_base_url,
    normalize_symbol,
)
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION,
    BINANCE_USDM_COMMISSION_ENDPOINT,
    BINANCE_USDM_COMMISSION_METHOD,
    BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION,
    BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION,
    BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
    BINANCE_USDM_COMMISSION_SHARED_BUDGET_REQUIRED,
    IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS,
    BinanceUSDMCommissionCaptureTokenV1,
    build_binance_usdm_commission_refresh_policy_v1,
    capture_binance_usdm_commission_rate_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

SCHEMA_VERSION: Final = "v2_binance_usdm_commission_evidence_broker_v1"
ROTATION_ARTIFACT_SCHEMA_VERSION: Final = (
    "v2_binance_usdm_commission_rotation_artifact_v1"
)
ROTATION_RECEIPT_SCHEMA_VERSION: Final = (
    "v2_binance_usdm_commission_rotation_receipt_v1"
)
CONSUMER_READ_RECEIPT_SCHEMA_VERSION: Final = (
    "v2_binance_usdm_commission_consumer_read_receipt_v1"
)
PRODUCER: Final = "v2_binance_usdm_commission_evidence_broker"
SOURCE: Final = "BINANCE_USDM_USER_DATA_GET_FAPI_V1_COMMISSION_RATE"
SECURITY_TYPE: Final = "USER_DATA"
FALLBACK_REASON: Final = "SIGNED_USER_DATA_COMMISSION_RATE_HAS_NO_SUPPORTED_WS_API_METHOD"
POLICY_ID: Final = "binance-usdm-commission-host-budget-rotation-v1"
POLICY_VERSION: Final = "v1"

REDIS_KEY_PREFIX: Final = "v2:binance_usdm:commission_evidence:"
REDIS_VERSION_KEY_PREFIX: Final = "v2:binance_usdm:commission_evidence_version:"
REDIS_CLAIM_KEY_PREFIX: Final = "v2:binance_usdm:commission_rotation_claim:"
DYNAMIC_COMMISSION_UNIVERSE_KEY: Final = (
    "v2:symbol_universe:dynamic_discovered_symbols"
)

# Computational/resource bounds, never market, strategy, leverage, or risk
# thresholds.  The evidence expiry ceiling is owned by the capture factory.
MAX_ROTATION_SYMBOLS: Final = 1_024
MAX_REDIS_EVIDENCE_BYTES: Final = 256 * 1_024
MAX_ROTATION_RECEIPT_BYTES: Final = 64 * 1_024
MAX_DYNAMIC_UNIVERSE_PAYLOAD_BYTES: Final = 256 * 1_024
MAX_REDIS_TTL_MS: Final = (1 << 53) - 1

_BROKER_HMAC_DOMAIN: Final = b"AI_BOT_BINANCE_USDM_COMMISSION_BROKER_V1\x00"
_ROTATION_RECEIPT_DOMAIN: Final = (
    b"AI_BOT_BINANCE_USDM_COMMISSION_ROTATION_RECEIPT_V1\x00"
)
_CONSUMER_READ_RECEIPT_HMAC_DOMAIN: Final = (
    b"AI_BOT_BINANCE_USDM_COMMISSION_CONSUMER_READ_RECEIPT_V1\x00"
)
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ENVELOPE_FIELDS = frozenset(
    """
    schema_version producer source request_method request_path security_type symbol
    exchange_environment base_url_origin trader_id credential_ref credential_binding_id
    credential_binding_fingerprint_sha256 credential_ref_read_only_assertion
    credential_ref_read_only_assertion_semantics exchange_key_permissions_proven_by_connector
    evidence_auth_algorithm evidence_auth_key_id request_started_at response_observed_at
    source_available_at broker_generated_at broker_available_at broker_available_at_semantics
    expires_at raw_response_sha256 raw_response_byte_count raw_response_cas_address
    raw_response_stored_in_redis sanitized_request_identity_sha256
    sanitized_request_identity_cas_address fee_artifact_sha256 fee_artifact_cas_address
    fee_receipt_sha256 fee_receipt_payload_sha256 fee_receipt_cas_address
    refresh_policy_artifact_cas_address refresh_policy_receipt_sha256
    refresh_policy_receipt_payload_sha256 refresh_policy_receipt_cas_address
    rotation_artifact_cas_address rotation_receipt_sha256 rotation_receipt_cas_address
    taker_commission_bps maker_commission_bps rpi_commission_bps request_weight
    shared_budget_required shared_budget_scope
    exchange_credentials_stored read_only trainer_authority prediction_authority
    paper_authority live_authority places_real_order order_submitted leverage_mutated
    margin_mutated content_checksum_sha256 evidence_hmac_sha256
    """.split()
)

_PUBLISH_CAS_LUA: Final = """
local prior_version = redis.call('GET', KEYS[2])
if prior_version then
  local separator = string.find(prior_version, ':', 1, true)
  if not separator then
    return -3
  end
  local prior_clock = tonumber(string.sub(prior_version, 1, separator - 1))
  local proposed_clock = tonumber(ARGV[1])
  if not prior_clock or not proposed_clock then
    return -3
  end
  if prior_clock > proposed_clock then
    return -1
  end
  if prior_clock == proposed_clock then
    local prior_payload = redis.call('GET', KEYS[1])
    if prior_payload == ARGV[3] and prior_version == ARGV[2] then
      return 2
    end
    return -2
  end
end
redis.call('PSETEX', KEYS[1], ARGV[4], ARGV[3])
redis.call('PSETEX', KEYS[2], ARGV[4], ARGV[2])
return 1
"""

_CLAIM_LUA: Final = """
local ttl = redis.call('PTTL', KEYS[1])
if ttl == -1 then
  return {-2, ttl}
end
if ttl > 0 then
  return {0, ttl}
end
local written = redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX')
if not written then
  local raced_ttl = redis.call('PTTL', KEYS[1])
  return {0, raced_ttl}
end
return {1, tonumber(ARGV[2])}
"""

_DYNAMIC_UNIVERSE_READ_LUA: Final = """
local redis_type = redis.call('TYPE', KEYS[1])
local payload_bytes = redis.call('STRLEN', KEYS[1])
local payload = ''
if redis_type == 'string' and payload_bytes <= tonumber(ARGV[1]) then
  payload = redis.call('GET', KEYS[1])
end
local ttl = redis.call('PTTL', KEYS[1])
local server_time = redis.call('TIME')
return {redis_type, payload_bytes, payload, ttl, server_time[1], server_time[2]}
"""


class CommissionEvidenceBrokerError(RuntimeError):
    """Stable, credential-safe fail-closed broker error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class CommissionRotationPlan:
    """One durable adaptive scheduling decision for exactly one symbol."""

    symbols: tuple[str, ...]
    selected_symbol: str
    priority_symbols: tuple[str, ...]
    cache_current_count: int
    cache_missing_count: int
    cache_invalid_count: int
    cache_expired_count: int
    budget_per_minute: int
    calls_per_minute: int
    pacing_ms: int
    observed_capture_sample_count: int
    observed_capture_max_ms: int
    projected_turn_ms: int
    projected_revisit_ms: int
    refresh_interval_seconds: int
    continuous_coverage_feasible: bool
    observed_at: str
    universe_sha256: str


@dataclass(frozen=True, slots=True)
class CredentiallessCommissionEvidence:
    """Authenticated inputs readable without either Binance credential."""

    symbol: str
    fee_artifact_bytes: bytes = field(repr=False)
    raw_response_bytes: bytes = field(repr=False)
    fee_schedule_receipt: dict[str, Any] = field(repr=False)
    broker_envelope_bytes: bytes = field(repr=False)
    broker_consumer_receipt_bytes: bytes = field(repr=False)
    source_available_at: str
    broker_available_at: str
    consumer_observed_at: str
    available_at: str
    decision_time: str
    expires_at: str
    raw_response_sha256: str
    fee_artifact_sha256: str
    fee_receipt_sha256: str
    broker_envelope_sha256: str
    broker_consumer_receipt_sha256: str
    credential_binding_fingerprint_sha256: str
    request_weight: int
    exchange_credentials_read: bool = False
    trainer_authority: bool = False
    prediction_authority: bool = False
    paper_authority: bool = False
    live_authority: bool = False


def _fail(reason: str) -> NoReturn:
    raise CommissionEvidenceBrokerError(reason)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError):
        _fail("COMMISSION_BROKER_CANONICAL_JSON_INVALID")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object(
    payload: bytes,
    *,
    canonical: bool,
    reason: str,
) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(reason)
            result[key] = value
        return result

    try:
        parsed = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda _value: _fail(reason),
        )
    except CommissionEvidenceBrokerError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _fail(reason)
    if type(parsed) is not dict:
        _fail(reason)
    result = cast(dict[str, Any], parsed)
    if canonical and not hmac.compare_digest(_canonical_bytes(result), payload):
        _fail(reason)
    return result


def _sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _HEX_SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return cast(str, value)


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            _fail(reason)
    else:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    parsed = parsed.astimezone(UTC)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _now(now_fn: Callable[[], datetime], *, reason: str) -> tuple[str, datetime]:
    try:
        value = now_fn()
    except Exception:
        _fail(reason)
    return _clock(value, reason=reason)


def _context(value: object) -> EvidenceSecurityContext:
    if type(value) is not EvidenceSecurityContext:
        _fail("COMMISSION_BROKER_SECURITY_CONTEXT_REQUIRED")
    typed = cast(EvidenceSecurityContext, value)
    try:
        rebuilt = build_evidence_security_context(
            trader_id=typed.trader_id,
            credential_ref=typed.credential_ref,
            base_url=typed.base_url_origin,
            credential_account_specific=typed.credential_account_specific,
            hmac_key=typed.hmac_key,
            auth_key_id=typed.auth_key_id,
        )
    except LeverageBracketEvidenceError:
        _fail("COMMISSION_BROKER_SECURITY_CONTEXT_INVALID")
    if rebuilt != typed:
        _fail("COMMISSION_BROKER_SECURITY_CONTEXT_INVALID")
    return typed


def _symbols(values: Iterable[object]) -> tuple[str, ...]:
    try:
        result = tuple(sorted({normalize_symbol(item) for item in values}))
    except (LeverageBracketEvidenceError, TypeError):
        _fail("COMMISSION_BROKER_SYMBOL_UNIVERSE_INVALID")
    if not result or len(result) > MAX_ROTATION_SYMBOLS:
        _fail("COMMISSION_BROKER_SYMBOL_UNIVERSE_SIZE_INVALID")
    return result


def _lua_text(value: object, *, reason: str) -> str:
    if type(value) is bytes:
        try:
            return cast(bytes, value).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _fail(reason)
    if type(value) is str:
        return cast(str, value)
    _fail(reason)


def _lua_int(value: object, *, reason: str) -> int:
    if type(value) is int:
        return cast(int, value)
    text = _lua_text(value, reason=reason)
    if re.fullmatch(r"-?[0-9]+", text, re.ASCII) is None:
        _fail(reason)
    try:
        return int(text)
    except ValueError:
        _fail(reason)


def read_adaptive_commission_rotation_universe(
    redis_client: Any,
    *,
    source_key: str = DYNAMIC_COMMISSION_UNIVERSE_KEY,
) -> dict[str, Any]:
    """Read the expiring trainer universe atomically as scheduling metadata.

    The source selects which symbols receive fee evidence; it is never copied
    into a training row and grants no trainer or trading authority. Invalid
    symbol strings are reported and excluded exactly as they are by the
    profiled publisher's own dynamic-universe boundary.
    """

    if source_key != DYNAMIC_COMMISSION_UNIVERSE_KEY:
        _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_KEY_INVALID")
    if redis_client is None:
        return {
            "status": "DYNAMIC_COMMISSION_UNIVERSE_REDIS_UNAVAILABLE",
            "symbols": (),
            "rejected_symbols": (),
        }
    try:
        reply = redis_client.eval(
            _DYNAMIC_UNIVERSE_READ_LUA,
            1,
            source_key,
            MAX_DYNAMIC_UNIVERSE_PAYLOAD_BYTES,
        )
    except Exception:
        return {
            "status": "DYNAMIC_COMMISSION_UNIVERSE_REDIS_READ_FAILED",
            "symbols": (),
            "rejected_symbols": (),
        }
    try:
        if type(reply) not in {list, tuple} or len(reply) != 6:
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_REPLY_INVALID")
        redis_type = _lua_text(
            reply[0], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_TYPE_INVALID"
        )
        payload_byte_count = _lua_int(
            reply[1], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_SIZE_INVALID"
        )
        payload_text = _lua_text(
            reply[2], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_PAYLOAD_INVALID"
        )
        pttl_ms = _lua_int(
            reply[3], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_PTTL_INVALID"
        )
        server_seconds = _lua_int(
            reply[4], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_CLOCK_INVALID"
        )
        server_microseconds = _lua_int(
            reply[5], reason="COMMISSION_BROKER_DYNAMIC_UNIVERSE_CLOCK_INVALID"
        )
        if redis_type == "none" and payload_byte_count == 0 and pttl_ms == -2:
            return {
                "status": "DYNAMIC_COMMISSION_UNIVERSE_MISSING",
                "symbols": (),
                "rejected_symbols": (),
            }
        payload_bytes = payload_text.encode("utf-8", errors="strict")
        if (
            redis_type != "string"
            or not 0 < payload_byte_count <= MAX_DYNAMIC_UNIVERSE_PAYLOAD_BYTES
            or len(payload_bytes) != payload_byte_count
            or pttl_ms <= 0
            or server_seconds < 0
            or not 0 <= server_microseconds < 1_000_000
        ):
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_SOURCE_INVALID")

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, value in pairs:
                if key in parsed:
                    raise ValueError("duplicate")
                parsed[key] = value
            return parsed

        decoded = json.loads(
            payload_text,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("nonfinite")
            ),
        )
        if type(decoded) is not dict or set(decoded) != {"generated_utc", "symbols"}:
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_PAYLOAD_INVALID")
        raw_symbols = decoded.get("symbols")
        generated_text = decoded.get("generated_utc")
        if (
            type(raw_symbols) is not list
            or not 1 <= len(raw_symbols) <= MAX_ROTATION_SYMBOLS
            or any(type(item) is not str for item in raw_symbols)
            or len(set(raw_symbols)) != len(raw_symbols)
            or type(generated_text) is not str
        ):
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_PAYLOAD_INVALID")
        server_at = _EPOCH + timedelta(
            seconds=server_seconds,
            microseconds=server_microseconds,
        )
        generated_at = datetime.strptime(
            generated_text,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=UTC)
        if generated_at > server_at:
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_CLOCK_INVALID")
        accepted: list[str] = []
        rejected: list[str] = []
        for candidate in raw_symbols:
            try:
                accepted.append(normalize_symbol(candidate))
            except LeverageBracketEvidenceError:
                rejected.append(candidate)
        if not accepted or len(set(accepted)) != len(accepted):
            _fail("COMMISSION_BROKER_DYNAMIC_UNIVERSE_SYMBOLS_INVALID")
        server_observed_at = server_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        expires_at = (server_at + timedelta(milliseconds=pttl_ms)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        return {
            "status": "READY",
            "source_key": source_key,
            "source_payload_sha256": _sha256_bytes(payload_bytes),
            "source_payload_byte_count": payload_byte_count,
            "source_pttl_ms": pttl_ms,
            "server_observed_at": server_observed_at,
            "source_expires_at": expires_at,
            "symbols": tuple(sorted(accepted)),
            "rejected_symbols": tuple(sorted(rejected)),
            "selection_metadata_only": True,
            "trainer_authority": False,
            "prediction_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
    except (
        CommissionEvidenceBrokerError,
        json.JSONDecodeError,
        OverflowError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        reason = (
            exc.reason
            if isinstance(exc, CommissionEvidenceBrokerError)
            else "COMMISSION_BROKER_DYNAMIC_UNIVERSE_PAYLOAD_INVALID"
        )
        return {"status": reason, "symbols": (), "rejected_symbols": ()}


def _prefix(context: EvidenceSecurityContext) -> str:
    return (
        f"{context.exchange_environment}:{context.trader_id}:"
        f"{context.credential_ref}:"
    )


def redis_key(symbol: object, *, security_context: EvidenceSecurityContext) -> str:
    context = _context(security_context)
    return f"{REDIS_KEY_PREFIX}{_prefix(context)}{normalize_symbol(symbol)}"


def redis_version_key(symbol: object, *, security_context: EvidenceSecurityContext) -> str:
    context = _context(security_context)
    return f"{REDIS_VERSION_KEY_PREFIX}{_prefix(context)}{normalize_symbol(symbol)}"


def redis_claim_key(*, security_context: EvidenceSecurityContext) -> str:
    context = _context(security_context)
    return f"{REDIS_CLAIM_KEY_PREFIX}{_prefix(context).removesuffix(':')}"


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _address(value: object, *, maximum: int, reason: str) -> SourcePayloadAddress:
    if not isinstance(value, Mapping) or frozenset(value) != {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }:
        _fail(reason)
    schema = value.get("schema_version")
    digest = _sha256(value.get("payload_sha256"), reason=reason)
    count = value.get("payload_byte_count")
    relative = value.get("relative_path")
    expected_relative = f"sha256/{digest[:2]}/{digest}"
    if (
        schema != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or type(count) is not int
        or not 0 < count <= maximum
        or relative != expected_relative
    ):
        _fail(reason)
    return SourcePayloadAddress(
        schema_version=cast(str, schema),
        payload_sha256=digest,
        payload_byte_count=count,
        relative_path=cast(str, relative),
    )


def _read_cas(
    store: ImmutableSourcePayloadStore,
    value: object,
    *,
    maximum: int,
    reason: str,
) -> bytes:
    if type(store) is not ImmutableSourcePayloadStore:
        _fail("COMMISSION_BROKER_IMMUTABLE_STORE_REQUIRED")
    address = _address(value, maximum=maximum, reason=reason)
    try:
        result = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError:
        _fail(reason)
    if _sha256_bytes(result) != address.payload_sha256:
        _fail(reason)
    return result


def _budget_per_minute(environ: Mapping[str, str] | None) -> int:
    values = os.environ if environ is None else environ
    raw = values.get(REST_FALLBACK_BUDGET_PER_MINUTE_ENV)
    if raw is None:
        return REST_FALLBACK_BUDGET_PER_MINUTE_DEFAULT
    if type(raw) is not str or not raw.isascii() or not raw.isdigit():
        _fail("COMMISSION_BROKER_RATE_BUDGET_INVALID")
    budget = int(raw)
    if budget < BINANCE_USDM_COMMISSION_REQUEST_WEIGHT:
        _fail("COMMISSION_BROKER_RATE_BUDGET_BELOW_ONE_REQUEST")
    return budget


def adaptive_commission_request_pacing_ms(
    environ: Mapping[str, str] | None = None,
) -> int:
    """Derive the minimum request spacing from the host-shared weight budget."""

    calls_per_minute = _budget_per_minute(environ) // BINANCE_USDM_COMMISSION_REQUEST_WEIGHT
    if calls_per_minute < 1:
        _fail("COMMISSION_BROKER_RATE_BUDGET_BELOW_ONE_REQUEST")
    return math.ceil(60_000 / calls_per_minute)


def _content_checksum(payload: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in payload.items()
        if key not in {"content_checksum_sha256", "evidence_hmac_sha256"}
    }
    return _sha256_bytes(_canonical_bytes(material))


def _evidence_hmac(
    payload: Mapping[str, Any], *, security_context: EvidenceSecurityContext
) -> str:
    material = {key: value for key, value in payload.items() if key != "evidence_hmac_sha256"}
    return hmac.new(
        security_context.hmac_key,
        _BROKER_HMAC_DOMAIN + _canonical_bytes(material),
        hashlib.sha256,
    ).hexdigest()


def _consumer_read_receipt(
    *,
    envelope: Mapping[str, Any],
    envelope_bytes: bytes,
    decision_time: str,
    consumer_observed_at: str,
    consumer_checked_at: str,
    security_context: EvidenceSecurityContext,
) -> tuple[bytes, str]:
    """Seal the exact successful consumer verification for durable lineage."""

    material: dict[str, Any] = {
        "schema_version": CONSUMER_READ_RECEIPT_SCHEMA_VERSION,
        "receipt_kind": "AUTHENTICATED_BROKER_CONSUMER_READ",
        "broker_schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "source": SOURCE,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "symbol": envelope["symbol"],
        "decision_time": decision_time,
        "source_available_at": envelope["source_available_at"],
        "broker_available_at": envelope["broker_available_at"],
        "consumer_observed_at": consumer_observed_at,
        "consumer_checked_at": consumer_checked_at,
        "expires_at": envelope["expires_at"],
        "broker_envelope_sha256": _sha256_bytes(envelope_bytes),
        "broker_envelope_evidence_hmac_sha256": envelope[
            "evidence_hmac_sha256"
        ],
        "rotation_receipt_sha256": envelope["rotation_receipt_sha256"],
        "raw_response_sha256": envelope["raw_response_sha256"],
        "fee_artifact_sha256": envelope["fee_artifact_sha256"],
        "fee_receipt_sha256": envelope["fee_receipt_sha256"],
        "credential_binding_fingerprint_sha256": envelope[
            "credential_binding_fingerprint_sha256"
        ],
        "evidence_auth_algorithm": AUTH_ALGORITHM,
        "evidence_auth_key_id": security_context.auth_key_id,
        "verification_checks": [
            "CANONICAL_REDIS_ENVELOPE",
            "ENVELOPE_CONTENT_CHECKSUM",
            "ENVELOPE_HMAC",
            "EIGHT_IMMUTABLE_CAS_READBACKS",
            "CAS_ENVELOPE_HASH_BINDINGS",
            "FEE_REFRESH_ROTATION_CONTENT_BINDINGS",
            "BROKER_SOURCE_CONSUMER_DECISION_CLOCK_ORDER",
            "EVIDENCE_EXPIRY",
        ],
        "broker_cas_object_count": 8,
        "exchange_credentials_read": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    material["content_checksum_sha256"] = _sha256_bytes(_canonical_bytes(material))
    material["evidence_hmac_sha256"] = hmac.new(
        security_context.hmac_key,
        _CONSUMER_READ_RECEIPT_HMAC_DOMAIN + _canonical_bytes(material),
        hashlib.sha256,
    ).hexdigest()
    encoded = _canonical_bytes(material)
    return encoded, _sha256_bytes(encoded)


def _seal(payload: dict[str, Any], *, security_context: EvidenceSecurityContext) -> None:
    payload["content_checksum_sha256"] = _content_checksum(payload)
    payload["evidence_hmac_sha256"] = _evidence_hmac(
        payload,
        security_context=security_context,
    )


def _decode_envelope(
    raw: object,
    *,
    symbol: str,
    security_context: EvidenceSecurityContext,
) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw_bytes = raw.encode("ascii", errors="strict")
        except UnicodeError:
            _fail("COMMISSION_BROKER_REDIS_EVIDENCE_INVALID")
    elif type(raw) is bytes:
        raw_bytes = cast(bytes, raw)
    else:
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_INVALID")
    if not raw_bytes or len(raw_bytes) > MAX_REDIS_EVIDENCE_BYTES:
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_SIZE_INVALID")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail("COMMISSION_BROKER_REDIS_EVIDENCE_JSON_INVALID")
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw_bytes.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda _value: _fail(
                "COMMISSION_BROKER_REDIS_EVIDENCE_JSON_INVALID"
            ),
        )
    except CommissionEvidenceBrokerError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_JSON_INVALID")
    if type(payload) is not dict:
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_JSON_INVALID")
    typed = cast(dict[str, Any], payload)
    if frozenset(typed) != _ENVELOPE_FIELDS:
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_FIELDS_INVALID")
    expected_literals = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "source": SOURCE,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "security_type": SECURITY_TYPE,
        "symbol": symbol,
        "exchange_environment": security_context.exchange_environment,
        "base_url_origin": security_context.base_url_origin,
        "trader_id": security_context.trader_id,
        "credential_ref": security_context.credential_ref,
        "credential_binding_id": security_context.binding_id,
        "credential_ref_read_only_assertion": True,
        "credential_ref_read_only_assertion_semantics": (
            "OPERATOR_USAGE_LABEL_NOT_BINANCE_PERMISSION_PROOF"
        ),
        "exchange_key_permissions_proven_by_connector": False,
        "evidence_auth_algorithm": AUTH_ALGORITHM,
        "evidence_auth_key_id": security_context.auth_key_id,
        "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "shared_budget_required": True,
        "shared_budget_scope": "host_redis",
        "raw_response_stored_in_redis": False,
        "exchange_credentials_stored": False,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if any(typed.get(name) != value for name, value in expected_literals.items()):
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_IDENTITY_INVALID")
    supplied_checksum = _sha256(
        typed.get("content_checksum_sha256"),
        reason="COMMISSION_BROKER_CONTENT_CHECKSUM_INVALID",
    )
    if not hmac.compare_digest(supplied_checksum, _content_checksum(typed)):
        _fail("COMMISSION_BROKER_CONTENT_CHECKSUM_MISMATCH")
    supplied_hmac = _sha256(
        typed.get("evidence_hmac_sha256"),
        reason="COMMISSION_BROKER_EVIDENCE_HMAC_INVALID",
    )
    expected_hmac = _evidence_hmac(typed, security_context=security_context)
    if not hmac.compare_digest(supplied_hmac, expected_hmac):
        _fail("COMMISSION_BROKER_EVIDENCE_HMAC_MISMATCH")
    request_iso, request_at = _clock(
        typed.get("request_started_at"), reason="COMMISSION_BROKER_REQUEST_CLOCK_INVALID"
    )
    observed_iso, observed_at = _clock(
        typed.get("response_observed_at"),
        reason="COMMISSION_BROKER_RESPONSE_CLOCK_INVALID",
    )
    source_iso, source_at = _clock(
        typed.get("source_available_at"),
        reason="COMMISSION_BROKER_SOURCE_AVAILABLE_CLOCK_INVALID",
    )
    generated_iso, generated_at = _clock(
        typed.get("broker_generated_at"),
        reason="COMMISSION_BROKER_GENERATED_CLOCK_INVALID",
    )
    available_iso, available_at = _clock(
        typed.get("broker_available_at"),
        reason="COMMISSION_BROKER_AVAILABLE_CLOCK_INVALID",
    )
    expires_iso, expires_at = _clock(
        typed.get("expires_at"), reason="COMMISSION_BROKER_EXPIRES_CLOCK_INVALID"
    )
    if not request_at <= observed_at <= source_at <= generated_at <= available_at < expires_at:
        _fail("COMMISSION_BROKER_EVIDENCE_CLOCK_ORDER_INVALID")
    if expires_at > source_at + timedelta(
        seconds=IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
    ):
        _fail("COMMISSION_BROKER_EVIDENCE_EXPIRY_LIMIT_INVALID")
    if any(
        typed.get(name) != value
        for name, value in (
            ("request_started_at", request_iso),
            ("response_observed_at", observed_iso),
            ("source_available_at", source_iso),
            ("broker_generated_at", generated_iso),
            ("broker_available_at", available_iso),
            ("expires_at", expires_iso),
        )
    ):
        _fail("COMMISSION_BROKER_EVIDENCE_CLOCK_CANONICALIZATION_INVALID")
    return typed


def build_adaptive_rotation_plan(
    redis_client: Any,
    *,
    security_context: EvidenceSecurityContext,
    symbols: Iterable[object],
    priority_symbols: Iterable[object] = (),
    environ: Mapping[str, str] | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CommissionRotationPlan:
    """Select exactly one symbol using cache state and the host weight budget."""

    context = _context(security_context)
    universe = _symbols(symbols)
    try:
        priority_values = tuple(priority_symbols)
        priority = (
            tuple(symbol for symbol in _symbols(priority_values) if symbol in set(universe))
            if priority_values
            else ()
        )
    except CommissionEvidenceBrokerError:
        _fail("COMMISSION_BROKER_PRIORITY_SYMBOLS_INVALID")
    budget = _budget_per_minute(environ)
    calls_per_minute = budget // BINANCE_USDM_COMMISSION_REQUEST_WEIGHT
    pacing_ms = adaptive_commission_request_pacing_ms(environ)
    observed_iso, observed_at = _now(
        now_fn,
        reason="COMMISSION_BROKER_ROTATION_OBSERVED_CLOCK_INVALID",
    )
    if redis_client is None:
        _fail("COMMISSION_BROKER_REDIS_REQUIRED")
    candidates: list[tuple[int, datetime, str]] = []
    current_count = missing_count = invalid_count = expired_count = 0
    observed_capture_durations_ms: list[int] = []
    priority_set = set(priority)
    for symbol in universe:
        try:
            raw = redis_client.get(redis_key(symbol, security_context=context))
        except Exception:
            _fail("COMMISSION_BROKER_REDIS_READ_FAILED")
        if raw in (None, b"", ""):
            missing_count += 1
            candidates.append((0 if symbol in priority_set else 1, _EPOCH, symbol))
            continue
        try:
            envelope = _decode_envelope(
                raw,
                symbol=symbol,
                security_context=context,
            )
            _, available_at = _clock(
                envelope["broker_available_at"],
                reason="COMMISSION_BROKER_AVAILABLE_CLOCK_INVALID",
            )
            _, expires_at = _clock(
                envelope["expires_at"], reason="COMMISSION_BROKER_EXPIRES_CLOCK_INVALID"
            )
            _, request_started_at = _clock(
                envelope["request_started_at"],
                reason="COMMISSION_BROKER_REQUEST_CLOCK_INVALID",
            )
        except CommissionEvidenceBrokerError:
            invalid_count += 1
            candidates.append((0 if symbol in priority_set else 1, _EPOCH, symbol))
            continue
        if available_at > observed_at:
            invalid_count += 1
            candidates.append((0 if symbol in priority_set else 1, _EPOCH, symbol))
        elif observed_at >= expires_at:
            expired_count += 1
            candidates.append((0 if symbol in priority_set else 1, expires_at, symbol))
        else:
            current_count += 1
            observed_capture_durations_ms.append(
                math.ceil((available_at - request_started_at).total_seconds() * 1_000)
            )
            candidates.append((2, expires_at, symbol))
    candidates.sort()
    selected = candidates[0][2]
    universe_sha = _sha256_bytes(_canonical_bytes(list(universe)))
    observed_capture_max_ms = max(observed_capture_durations_ms, default=0)
    projected_turn_ms = pacing_ms + observed_capture_max_ms
    projected_revisit_ms = projected_turn_ms * len(universe)
    proposed_refresh_seconds = math.ceil(
        (projected_revisit_ms + projected_turn_ms) / 1_000
    )
    refresh_seconds = min(
        IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS,
        max(1, proposed_refresh_seconds),
    )
    return CommissionRotationPlan(
        symbols=universe,
        selected_symbol=selected,
        priority_symbols=priority,
        cache_current_count=current_count,
        cache_missing_count=missing_count,
        cache_invalid_count=invalid_count,
        cache_expired_count=expired_count,
        budget_per_minute=budget,
        calls_per_minute=calls_per_minute,
        pacing_ms=pacing_ms,
        observed_capture_sample_count=len(observed_capture_durations_ms),
        observed_capture_max_ms=observed_capture_max_ms,
        projected_turn_ms=projected_turn_ms,
        projected_revisit_ms=projected_revisit_ms,
        refresh_interval_seconds=refresh_seconds,
        continuous_coverage_feasible=(
            current_count == len(universe)
            and proposed_refresh_seconds
            <= IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
        ),
        observed_at=observed_iso,
        universe_sha256=universe_sha,
    )


def _persist_rotation_plan(
    store: ImmutableSourcePayloadStore,
    plan: CommissionRotationPlan,
    *,
    recorded_at: str,
) -> tuple[dict[str, Any], SourcePayloadAddress, str, SourcePayloadAddress]:
    artifact = {
        "schema_version": ROTATION_ARTIFACT_SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "selected_symbol": plan.selected_symbol,
        "symbol_count": len(plan.symbols),
        "universe_sha256": plan.universe_sha256,
        "priority_symbols": list(plan.priority_symbols),
        "cache_current_count": plan.cache_current_count,
        "cache_missing_count": plan.cache_missing_count,
        "cache_invalid_count": plan.cache_invalid_count,
        "cache_expired_count": plan.cache_expired_count,
        "host_budget_per_minute": plan.budget_per_minute,
        "endpoint_request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "calls_per_minute": plan.calls_per_minute,
        "pacing_ms": plan.pacing_ms,
        "observed_capture_sample_count": plan.observed_capture_sample_count,
        "observed_capture_max_ms": plan.observed_capture_max_ms,
        "projected_turn_ms": plan.projected_turn_ms,
        "projected_revisit_ms": plan.projected_revisit_ms,
        "refresh_interval_seconds": plan.refresh_interval_seconds,
        "continuous_coverage_feasible": plan.continuous_coverage_feasible,
        "adaptive_basis": "HOST_RATE_BUDGET_AND_AUTHENTICATED_CACHE_EXPIRY_ROTATION",
        "static_market_threshold_used": False,
        "observed_at": plan.observed_at,
        "authority_scope": "COMMISSION_CAPTURE_SCHEDULING_ONLY",
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    artifact_bytes = _canonical_bytes(artifact)
    if len(artifact_bytes) > MAX_ROTATION_RECEIPT_BYTES:
        _fail("COMMISSION_BROKER_ROTATION_ARTIFACT_SIZE_INVALID")
    try:
        artifact_address = store.put(artifact_bytes)
    except SourcePayloadStoreError:
        _fail("COMMISSION_BROKER_ROTATION_ARTIFACT_CAS_FAILED")
    receipt_without_hash = {
        "schema_version": ROTATION_RECEIPT_SCHEMA_VERSION,
        "receipt_kind": "DURABLE_CAS_APPEND",
        "artifact_cas_address": _address_mapping(artifact_address),
        "selected_symbol": plan.selected_symbol,
        "universe_sha256": plan.universe_sha256,
        "observed_at": plan.observed_at,
        "recorded_at": recorded_at,
        "authority_scope": "COMMISSION_CAPTURE_SCHEDULING_ONLY",
    }
    # This public self-hash is domain separated from every other receipt.  The
    # secret HMAC boundary is applied to the final Redis envelope below.
    receipt_sha = _sha256_bytes(
        _ROTATION_RECEIPT_DOMAIN + _canonical_bytes(receipt_without_hash)
    )
    receipt = {**receipt_without_hash, "receipt_sha256": receipt_sha}
    receipt_bytes = _canonical_bytes(receipt)
    try:
        receipt_address = store.put(receipt_bytes)
    except SourcePayloadStoreError:
        _fail("COMMISSION_BROKER_ROTATION_RECEIPT_CAS_FAILED")
    return artifact, artifact_address, receipt_sha, receipt_address


def credential_binding_for_adapter(
    adapter: Any,
    *,
    security_context: EvidenceSecurityContext,
) -> BinanceCredentialBinding:
    """Build the capture binding from the already-loaded protected adapter."""

    context = _context(security_context)
    api_key = getattr(adapter, "api_key", None)
    api_secret = getattr(adapter, "api_secret", None)
    base_url = getattr(adapter, "base_url", None)
    try:
        environment = exchange_environment_from_base_url(base_url)
    except LeverageBracketEvidenceError:
        _fail("COMMISSION_BROKER_ADAPTER_ORIGIN_INVALID")
    if environment != context.exchange_environment or base_url != context.base_url_origin:
        _fail("COMMISSION_BROKER_ADAPTER_CONTEXT_MISMATCH")
    if type(api_key) is not str or not api_key or type(api_secret) is not str or not api_secret:
        _fail("COMMISSION_BROKER_ADAPTER_CREDENTIALS_MISSING")
    return BinanceCredentialBinding(
        trader_id=context.trader_id,
        credential_ref=context.credential_ref,
        api_key=api_key,
        api_secret=api_secret,
        api_key_name=f"systemd:{context.binding_id}:api_key",
        api_secret_name=f"systemd:{context.binding_id}:api_secret",
        api_key_source="already_loaded_account_specific_adapter",
        api_secret_source=(  # noqa: S106 - safe source label, never secret material
            "already_loaded_account_specific_adapter"
        ),
        account_specific=True,
        read_only_ref=True,
    )


def _claim_rotation(
    redis_client: Any,
    *,
    security_context: EvidenceSecurityContext,
    plan_receipt_sha256: str,
    pacing_ms: int,
) -> tuple[bool, int]:
    if type(pacing_ms) is not int or not 0 < pacing_ms <= MAX_REDIS_TTL_MS:
        _fail("COMMISSION_BROKER_PACING_INVALID")
    try:
        reply = redis_client.eval(
            _CLAIM_LUA,
            1,
            redis_claim_key(security_context=security_context),
            plan_receipt_sha256,
            pacing_ms,
        )
    except Exception:
        _fail("COMMISSION_BROKER_ROTATION_CLAIM_FAILED")
    if not isinstance(reply, list | tuple) or len(reply) != 2:
        _fail("COMMISSION_BROKER_ROTATION_CLAIM_REPLY_INVALID")
    try:
        code, ttl = (int(item) for item in reply)
    except (TypeError, ValueError, OverflowError):
        _fail("COMMISSION_BROKER_ROTATION_CLAIM_REPLY_INVALID")
    if code == -2:
        _fail("COMMISSION_BROKER_ROTATION_CLAIM_PERSISTENT_KEY_INVALID")
    if code not in {0, 1} or ttl < 0:
        _fail("COMMISSION_BROKER_ROTATION_CLAIM_REPLY_INVALID")
    return code == 1, ttl


def _publication_payload(
    capture: BinanceUSDMCommissionCaptureTokenV1,
    *,
    security_context: EvidenceSecurityContext,
    rotation_artifact_address: SourcePayloadAddress,
    rotation_receipt_sha256: str,
    rotation_receipt_address: SourcePayloadAddress,
    generated_at: str,
    available_at: str,
) -> dict[str, Any]:
    contract = capture.contract
    if (
        contract.get("schema_version") != BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION
        or contract.get("symbol") != capture.symbol
        or contract.get("request_weight") != BINANCE_USDM_COMMISSION_REQUEST_WEIGHT
        or contract.get("shared_budget_required") is not True
        or contract.get("read_only") is not True
    ):
        _fail("COMMISSION_BROKER_CAPTURE_CONTRACT_INVALID")
    artifact = cast(dict[str, Any], contract["fee_artifact"])
    receipt = cast(dict[str, Any], contract["fee_schedule_receipt"])
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "source": SOURCE,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "security_type": SECURITY_TYPE,
        "symbol": capture.symbol,
        "exchange_environment": security_context.exchange_environment,
        "base_url_origin": security_context.base_url_origin,
        "trader_id": security_context.trader_id,
        "credential_ref": security_context.credential_ref,
        "credential_binding_id": security_context.binding_id,
        "credential_binding_fingerprint_sha256": (
            capture.credential_binding_fingerprint_sha256
        ),
        "credential_ref_read_only_assertion": True,
        "credential_ref_read_only_assertion_semantics": (
            "OPERATOR_USAGE_LABEL_NOT_BINANCE_PERMISSION_PROOF"
        ),
        "exchange_key_permissions_proven_by_connector": False,
        "evidence_auth_algorithm": AUTH_ALGORITHM,
        "evidence_auth_key_id": security_context.auth_key_id,
        "request_started_at": capture.request_started_at,
        "response_observed_at": capture.response_observed_at,
        "source_available_at": capture.available_at,
        "broker_generated_at": generated_at,
        "broker_available_at": available_at,
        "broker_available_at_semantics": (
            "PRE_REDIS_CAS_PUBLICATION_CLOCK;CONSUMER_POST_VALIDATION_CLOCK_REQUIRED"
        ),
        "expires_at": capture.expires_at,
        "raw_response_sha256": capture.raw_response_sha256,
        "raw_response_byte_count": len(capture.raw_response_bytes),
        "raw_response_cas_address": _address_mapping(capture.raw_response_address),
        "raw_response_stored_in_redis": False,
        "sanitized_request_identity_sha256": (
            capture.sanitized_request_identity_sha256
        ),
        "sanitized_request_identity_cas_address": _address_mapping(
            capture.sanitized_request_identity_address
        ),
        "fee_artifact_sha256": capture.fee_artifact_address.payload_sha256,
        "fee_artifact_cas_address": _address_mapping(capture.fee_artifact_address),
        "fee_receipt_sha256": capture.fee_receipt_sha256,
        "fee_receipt_payload_sha256": capture.fee_receipt_address.payload_sha256,
        "fee_receipt_cas_address": _address_mapping(capture.fee_receipt_address),
        "refresh_policy_artifact_cas_address": _address_mapping(
            capture._refresh_policy.artifact_address  # noqa: SLF001 - factory token provenance
        ),
        "refresh_policy_receipt_sha256": capture.refresh_policy_receipt_sha256,
        "refresh_policy_receipt_payload_sha256": (
            capture._refresh_policy.receipt_address.payload_sha256  # noqa: SLF001
        ),
        "refresh_policy_receipt_cas_address": _address_mapping(
            capture._refresh_policy.receipt_address  # noqa: SLF001
        ),
        "rotation_artifact_cas_address": _address_mapping(rotation_artifact_address),
        "rotation_receipt_sha256": rotation_receipt_sha256,
        "rotation_receipt_cas_address": _address_mapping(rotation_receipt_address),
        "taker_commission_bps": artifact.get("taker_fee_bps_per_side"),
        "maker_commission_bps": capture.maker_commission_bps,
        "rpi_commission_bps": receipt.get("rpi_commission_bps"),
        "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "shared_budget_required": BINANCE_USDM_COMMISSION_SHARED_BUDGET_REQUIRED,
        "shared_budget_scope": "host_redis",
        "exchange_credentials_stored": False,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    _seal(payload, security_context=security_context)
    return payload


def _publish_cas(
    redis_client: Any,
    *,
    security_context: EvidenceSecurityContext,
    symbol: str,
    payload: Mapping[str, Any],
    ttl_ms: int,
) -> str:
    encoded = _canonical_bytes(payload)
    if not encoded or len(encoded) > MAX_REDIS_EVIDENCE_BYTES:
        _fail("COMMISSION_BROKER_REDIS_EVIDENCE_SIZE_INVALID")
    available_iso, available_at = _clock(
        payload.get("broker_available_at"),
        reason="COMMISSION_BROKER_AVAILABLE_CLOCK_INVALID",
    )
    if type(ttl_ms) is not int or not 0 < ttl_ms <= MAX_REDIS_TTL_MS:
        _fail("COMMISSION_BROKER_REDIS_TTL_INVALID")
    delta = available_at - _EPOCH
    available_us = (
        delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    )
    payload_sha = _sha256_bytes(encoded)
    version = f"{available_us}:{payload_sha}"
    try:
        result = redis_client.eval(
            _PUBLISH_CAS_LUA,
            2,
            redis_key(symbol, security_context=security_context),
            redis_version_key(symbol, security_context=security_context),
            available_us,
            version,
            encoded.decode("ascii"),
            ttl_ms,
        )
    except Exception:
        _fail("COMMISSION_BROKER_REDIS_CAS_FAILED")
    try:
        code = int(result)
    except (TypeError, ValueError, OverflowError):
        _fail("COMMISSION_BROKER_REDIS_CAS_REPLY_INVALID")
    if code == 1:
        return "PUBLISHED"
    if code == 2:
        return "IDEMPOTENT"
    if code == -1:
        _fail("COMMISSION_BROKER_REDIS_CAS_OLDER_THAN_CURRENT")
    if code == -2:
        _fail("COMMISSION_BROKER_REDIS_CAS_EQUAL_CLOCK_CONFLICT")
    _fail("COMMISSION_BROKER_REDIS_CAS_STATE_INVALID")


def capture_and_publish_next_commission_evidence(
    *,
    adapter: Any,
    redis_client: Any,
    store: ImmutableSourcePayloadStore,
    security_context: EvidenceSecurityContext,
    symbols: Iterable[object],
    priority_symbols: Iterable[object] = (),
    environ: Mapping[str, str] | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    capture_function: Callable[..., BinanceUSDMCommissionCaptureTokenV1] = (
        capture_binance_usdm_commission_rate_v1
    ),
    policy_builder: Callable[..., Any] = build_binance_usdm_commission_refresh_policy_v1,
) -> dict[str, Any]:
    """Capture and publish no more than one adaptive rotation candidate."""

    context = _context(security_context)
    if type(store) is not ImmutableSourcePayloadStore:
        _fail("COMMISSION_BROKER_IMMUTABLE_STORE_REQUIRED")
    if not callable(capture_function) or not callable(policy_builder):
        _fail("COMMISSION_BROKER_FACTORY_INVALID")
    binding = credential_binding_for_adapter(adapter, security_context=context)
    plan = build_adaptive_rotation_plan(
        redis_client,
        security_context=context,
        symbols=symbols,
        priority_symbols=priority_symbols,
        environ=environ,
        now_fn=now_fn,
    )
    recorded_iso, recorded_at = _now(
        now_fn,
        reason="COMMISSION_BROKER_ROTATION_RECORDED_CLOCK_INVALID",
    )
    _, observed_at = _clock(
        plan.observed_at, reason="COMMISSION_BROKER_ROTATION_OBSERVED_CLOCK_INVALID"
    )
    if recorded_at < observed_at:
        _fail("COMMISSION_BROKER_ROTATION_CLOCK_REGRESSION")
    (
        _rotation_artifact,
        rotation_artifact_address,
        rotation_receipt_sha,
        rotation_receipt_address,
    ) = _persist_rotation_plan(store, plan, recorded_at=recorded_iso)
    claimed, claim_ttl_ms = _claim_rotation(
        redis_client,
        security_context=context,
        plan_receipt_sha256=rotation_receipt_sha,
        pacing_ms=plan.pacing_ms,
    )
    if not claimed:
        return {
            "status": "DEFERRED",
            "reason": "ADAPTIVE_ROTATION_PACING_CLAIM_ACTIVE",
            "selected_symbol": plan.selected_symbol,
            "claim_ttl_ms": claim_ttl_ms,
            "request_executed": False,
            "request_count": 0,
            "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
            "places_real_order": False,
            "order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    policy_iso, policy_at = _now(
        now_fn,
        reason="COMMISSION_BROKER_POLICY_CLOCK_INVALID",
    )
    if policy_at < recorded_at:
        _fail("COMMISSION_BROKER_POLICY_CLOCK_REGRESSION")
    policy = policy_builder(
        store=store,
        symbol=plan.selected_symbol,
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        refresh_interval_seconds=plan.refresh_interval_seconds,
        adaptive_input_receipt_sha256=rotation_receipt_sha,
        generated_at=policy_iso,
        available_at=policy_iso,
        recorded_at=policy_iso,
    )
    capture = capture_function(
        store=store,
        symbol=plan.selected_symbol,
        refresh_policy=policy,
        fallback_reason=FALLBACK_REASON,
        credential_fingerprint_hmac_key=context.hmac_key,
        credential_binding=binding,
        base_url=context.base_url_origin,
        now_fn=now_fn,
    )
    if type(capture) is not BinanceUSDMCommissionCaptureTokenV1:
        _fail("COMMISSION_BROKER_CAPTURE_FACTORY_TOKEN_REQUIRED")
    generated_iso, generated_at = _now(
        now_fn,
        reason="COMMISSION_BROKER_GENERATED_CLOCK_INVALID",
    )
    available_iso, available_at = _now(
        now_fn,
        reason="COMMISSION_BROKER_AVAILABLE_CLOCK_INVALID",
    )
    _, source_at = _clock(
        capture.available_at, reason="COMMISSION_BROKER_SOURCE_AVAILABLE_CLOCK_INVALID"
    )
    _, expires_at = _clock(
        capture.expires_at, reason="COMMISSION_BROKER_EXPIRES_CLOCK_INVALID"
    )
    if not source_at <= generated_at <= available_at < expires_at:
        _fail("COMMISSION_BROKER_PUBLICATION_CLOCK_ORDER_INVALID")
    ttl_ms = math.floor((expires_at - available_at).total_seconds() * 1_000)
    payload = _publication_payload(
        capture,
        security_context=context,
        rotation_artifact_address=rotation_artifact_address,
        rotation_receipt_sha256=rotation_receipt_sha,
        rotation_receipt_address=rotation_receipt_address,
        generated_at=generated_iso,
        available_at=available_iso,
    )
    publication_status = _publish_cas(
        redis_client,
        security_context=context,
        symbol=plan.selected_symbol,
        payload=payload,
        ttl_ms=ttl_ms,
    )
    return {
        "status": "READY",
        "reason": "AUTHENTICATED_COMMISSION_EVIDENCE_PUBLISHED",
        "publication_status": publication_status,
        "selected_symbol": plan.selected_symbol,
        "symbol_count": len(plan.symbols),
        "cache_current_count": plan.cache_current_count,
        "cache_missing_count": plan.cache_missing_count,
        "cache_invalid_count": plan.cache_invalid_count,
        "cache_expired_count": plan.cache_expired_count,
        "pacing_ms": plan.pacing_ms,
        "observed_capture_sample_count": plan.observed_capture_sample_count,
        "observed_capture_max_ms": plan.observed_capture_max_ms,
        "projected_turn_ms": plan.projected_turn_ms,
        "projected_revisit_ms": plan.projected_revisit_ms,
        "continuous_coverage_feasible": plan.continuous_coverage_feasible,
        "request_executed": True,
        "request_count": 1,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "shared_budget_required": True,
        "raw_response_sha256": capture.raw_response_sha256,
        "raw_response_byte_count": len(capture.raw_response_bytes),
        "rotation_receipt_sha256": rotation_receipt_sha,
        "broker_available_at": available_iso,
        "expires_at": capture.expires_at,
        "read_only": True,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def read_authenticated_commission_evidence(
    redis_client: Any,
    *,
    store: ImmutableSourcePayloadStore,
    security_context: EvidenceSecurityContext,
    symbol: object,
    decision_time: object,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Read one PIT-safe fee input without loading Binance credentials."""

    context = _context(security_context)
    try:
        canonical_symbol = normalize_symbol(symbol)
    except LeverageBracketEvidenceError:
        return {"status": "SYMBOL_INVALID", "evidence": None}
    try:
        decision_iso, decision_at = _clock(
            decision_time,
            reason="COMMISSION_BROKER_DECISION_CLOCK_INVALID",
        )
    except CommissionEvidenceBrokerError as exc:
        return {"status": exc.reason, "evidence": None}
    if redis_client is None:
        return {"status": "COMMISSION_EVIDENCE_MISSING", "evidence": None}
    try:
        raw = redis_client.get(redis_key(canonical_symbol, security_context=context))
    except Exception:
        return {"status": "COMMISSION_EVIDENCE_REDIS_READ_FAILED", "evidence": None}
    try:
        observed_iso, observed_at = _now(
            now_fn,
            reason="COMMISSION_BROKER_CONSUMER_OBSERVED_CLOCK_INVALID",
        )
    except CommissionEvidenceBrokerError as exc:
        return {"status": exc.reason, "evidence": None}
    if raw in (None, b"", ""):
        return {"status": "COMMISSION_EVIDENCE_MISSING", "evidence": None}
    try:
        if isinstance(raw, str):
            try:
                redis_envelope_bytes = raw.encode("ascii", errors="strict")
            except UnicodeError:
                _fail("COMMISSION_BROKER_REDIS_EVIDENCE_INVALID")
        elif type(raw) is bytes:
            redis_envelope_bytes = cast(bytes, raw)
        else:
            _fail("COMMISSION_BROKER_REDIS_EVIDENCE_INVALID")
        envelope = _decode_envelope(
            raw,
            symbol=canonical_symbol,
            security_context=context,
        )
        canonical_envelope_bytes = _canonical_bytes(envelope)
        if not hmac.compare_digest(redis_envelope_bytes, canonical_envelope_bytes):
            _fail("COMMISSION_BROKER_REDIS_EVIDENCE_NOT_CANONICAL")
        raw_bytes = _read_cas(
            store,
            envelope.get("raw_response_cas_address"),
            maximum=64 * 1_024,
            reason="COMMISSION_BROKER_RAW_RESPONSE_CAS_INVALID",
        )
        artifact_bytes = _read_cas(
            store,
            envelope.get("fee_artifact_cas_address"),
            maximum=64 * 1_024,
            reason="COMMISSION_BROKER_FEE_ARTIFACT_CAS_INVALID",
        )
        receipt_bytes = _read_cas(
            store,
            envelope.get("fee_receipt_cas_address"),
            maximum=64 * 1_024,
            reason="COMMISSION_BROKER_FEE_RECEIPT_CAS_INVALID",
        )
        request_identity_bytes = _read_cas(
            store,
            envelope.get("sanitized_request_identity_cas_address"),
            maximum=64 * 1_024,
            reason="COMMISSION_BROKER_REQUEST_IDENTITY_CAS_INVALID",
        )
        refresh_artifact_bytes = _read_cas(
            store,
            envelope.get("refresh_policy_artifact_cas_address"),
            maximum=MAX_ROTATION_RECEIPT_BYTES,
            reason="COMMISSION_BROKER_REFRESH_ARTIFACT_CAS_INVALID",
        )
        refresh_receipt_bytes = _read_cas(
            store,
            envelope.get("refresh_policy_receipt_cas_address"),
            maximum=MAX_ROTATION_RECEIPT_BYTES,
            reason="COMMISSION_BROKER_REFRESH_RECEIPT_CAS_INVALID",
        )
        rotation_artifact_bytes = _read_cas(
            store,
            envelope.get("rotation_artifact_cas_address"),
            maximum=MAX_ROTATION_RECEIPT_BYTES,
            reason="COMMISSION_BROKER_ROTATION_ARTIFACT_CAS_INVALID",
        )
        rotation_receipt_bytes = _read_cas(
            store,
            envelope.get("rotation_receipt_cas_address"),
            maximum=MAX_ROTATION_RECEIPT_BYTES,
            reason="COMMISSION_BROKER_ROTATION_RECEIPT_CAS_INVALID",
        )
        if (
            _sha256_bytes(raw_bytes) != envelope.get("raw_response_sha256")
            or len(raw_bytes) != envelope.get("raw_response_byte_count")
            or _sha256_bytes(artifact_bytes) != envelope.get("fee_artifact_sha256")
            or _sha256_bytes(receipt_bytes)
            != envelope.get("fee_receipt_payload_sha256")
            or _sha256_bytes(request_identity_bytes)
            != envelope.get("sanitized_request_identity_sha256")
            or _sha256_bytes(refresh_receipt_bytes)
            != envelope.get("refresh_policy_receipt_payload_sha256")
        ):
            _fail("COMMISSION_BROKER_CAS_ENVELOPE_BINDING_INVALID")
        raw_payload = _json_object(
            raw_bytes,
            canonical=False,
            reason="COMMISSION_BROKER_RAW_RESPONSE_JSON_INVALID",
        )
        artifact = _json_object(
            artifact_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_FEE_ARTIFACT_JSON_INVALID",
        )
        receipt = _json_object(
            receipt_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_FEE_RECEIPT_JSON_INVALID",
        )
        request_identity = _json_object(
            request_identity_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_REQUEST_IDENTITY_JSON_INVALID",
        )
        refresh_artifact = _json_object(
            refresh_artifact_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_REFRESH_ARTIFACT_JSON_INVALID",
        )
        refresh_receipt = _json_object(
            refresh_receipt_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_REFRESH_RECEIPT_JSON_INVALID",
        )
        rotation_artifact = _json_object(
            rotation_artifact_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_ROTATION_ARTIFACT_JSON_INVALID",
        )
        rotation_receipt = _json_object(
            rotation_receipt_bytes,
            canonical=True,
            reason="COMMISSION_BROKER_ROTATION_RECEIPT_JSON_INVALID",
        )
        fee_receipt_without_hash = {
            key: value for key, value in receipt.items() if key != "receipt_sha256"
        }
        refresh_receipt_without_hash = {
            key: value
            for key, value in refresh_receipt.items()
            if key != "receipt_sha256"
        }
        rotation_receipt_without_hash = {
            key: value
            for key, value in rotation_receipt.items()
            if key != "receipt_sha256"
        }
        if (
            raw_payload.get("symbol") != canonical_symbol
            or frozenset(raw_payload)
            != {
                "symbol",
                "makerCommissionRate",
                "takerCommissionRate",
                "rpiCommissionRate",
            }
            or artifact.get("symbol") != canonical_symbol
            or receipt.get("symbol") != canonical_symbol
            or artifact.get("request_method") != BINANCE_USDM_COMMISSION_METHOD
            or artifact.get("request_path") != BINANCE_USDM_COMMISSION_ENDPOINT
            or artifact.get("raw_response_sha256") != envelope.get("raw_response_sha256")
            or receipt.get("artifact_payload_sha256")
            != envelope.get("fee_artifact_sha256")
            or receipt.get("receipt_sha256") != envelope.get("fee_receipt_sha256")
            or receipt.get("receipt_sha256")
            != _sha256_bytes(_canonical_bytes(fee_receipt_without_hash))
            or request_identity.get("method") != BINANCE_USDM_COMMISSION_METHOD
            or request_identity.get("path") != BINANCE_USDM_COMMISSION_ENDPOINT
            or request_identity.get("origin") != context.base_url_origin
            or request_identity.get("symbol") != canonical_symbol
            or refresh_artifact.get("schema_version")
            != BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION
            or refresh_receipt.get("schema_version")
            != BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION
            or refresh_artifact.get("symbol") != canonical_symbol
            or refresh_receipt.get("symbol") != canonical_symbol
            or refresh_receipt.get("artifact_payload_sha256")
            != _sha256_bytes(refresh_artifact_bytes)
            or refresh_receipt.get("receipt_sha256")
            != envelope.get("refresh_policy_receipt_sha256")
            or refresh_receipt.get("receipt_sha256")
            != _sha256_bytes(_canonical_bytes(refresh_receipt_without_hash))
            or refresh_artifact.get("adaptive_input_receipt_sha256")
            != envelope.get("rotation_receipt_sha256")
            or rotation_artifact.get("schema_version")
            != ROTATION_ARTIFACT_SCHEMA_VERSION
            or rotation_artifact.get("selected_symbol") != canonical_symbol
            or rotation_receipt.get("schema_version")
            != ROTATION_RECEIPT_SCHEMA_VERSION
            or rotation_receipt.get("selected_symbol") != canonical_symbol
            or rotation_receipt.get("artifact_cas_address")
            != envelope.get("rotation_artifact_cas_address")
            or rotation_receipt.get("receipt_sha256")
            != envelope.get("rotation_receipt_sha256")
            or rotation_receipt.get("receipt_sha256")
            != _sha256_bytes(
                _ROTATION_RECEIPT_DOMAIN
                + _canonical_bytes(rotation_receipt_without_hash)
            )
            or artifact.get("credential_binding_fingerprint_sha256")
            != envelope.get("credential_binding_fingerprint_sha256")
        ):
            _fail("COMMISSION_BROKER_CAS_CONTENT_BINDING_INVALID")
        _, source_at = _clock(
            envelope.get("source_available_at"),
            reason="COMMISSION_BROKER_SOURCE_AVAILABLE_CLOCK_INVALID",
        )
        _, broker_at = _clock(
            envelope.get("broker_available_at"),
            reason="COMMISSION_BROKER_AVAILABLE_CLOCK_INVALID",
        )
        expires_iso, expires_at = _clock(
            envelope.get("expires_at"),
            reason="COMMISSION_BROKER_EXPIRES_CLOCK_INVALID",
        )
        refresh_interval = refresh_artifact.get("refresh_interval_seconds")
        if (
            type(refresh_interval) is not int
            or not 0 < refresh_interval
            <= IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
            or source_at + timedelta(seconds=refresh_interval) != expires_at
        ):
            _fail("COMMISSION_BROKER_REFRESH_EXPIRY_BINDING_INVALID")
        checked_iso, checked_at = _now(
            now_fn,
            reason="COMMISSION_BROKER_CURRENT_CHECKED_CLOCK_INVALID",
        )
        if not source_at <= broker_at <= observed_at <= checked_at <= decision_at < expires_at:
            _fail("COMMISSION_BROKER_DECISION_TEMPORAL_ADMISSION_FAILED")
        if artifact.get("available_at") != envelope.get("source_available_at") or artifact.get(
            "expires_at"
        ) != expires_iso:
            _fail("COMMISSION_BROKER_FEE_ARTIFACT_CLOCK_BINDING_INVALID")
        consumer_receipt_bytes, consumer_receipt_sha256 = _consumer_read_receipt(
            envelope=envelope,
            envelope_bytes=canonical_envelope_bytes,
            decision_time=decision_iso,
            consumer_observed_at=observed_iso,
            consumer_checked_at=checked_iso,
            security_context=context,
        )
    except (
        CommissionEvidenceBrokerError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        reason = (
            exc.reason
            if isinstance(exc, CommissionEvidenceBrokerError)
            else "COMMISSION_BROKER_CAS_JSON_INVALID"
        )
        return {"status": reason, "evidence": None}
    evidence = CredentiallessCommissionEvidence(
        symbol=canonical_symbol,
        fee_artifact_bytes=artifact_bytes,
        raw_response_bytes=raw_bytes,
        fee_schedule_receipt=cast(dict[str, Any], receipt),
        broker_envelope_bytes=canonical_envelope_bytes,
        broker_consumer_receipt_bytes=consumer_receipt_bytes,
        source_available_at=cast(str, envelope["source_available_at"]),
        broker_available_at=cast(str, envelope["broker_available_at"]),
        consumer_observed_at=observed_iso,
        available_at=checked_iso,
        decision_time=decision_iso,
        expires_at=cast(str, envelope["expires_at"]),
        raw_response_sha256=cast(str, envelope["raw_response_sha256"]),
        fee_artifact_sha256=cast(str, envelope["fee_artifact_sha256"]),
        fee_receipt_sha256=cast(str, envelope["fee_receipt_sha256"]),
        broker_envelope_sha256=_sha256_bytes(canonical_envelope_bytes),
        broker_consumer_receipt_sha256=consumer_receipt_sha256,
        credential_binding_fingerprint_sha256=cast(
            str, envelope["credential_binding_fingerprint_sha256"]
        ),
        request_weight=BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
    )
    return {
        "status": "READY",
        "evidence": evidence,
        "symbol": canonical_symbol,
        "source_available_at": evidence.source_available_at,
        "broker_available_at": evidence.broker_available_at,
        "consumer_observed_at": evidence.consumer_observed_at,
        "available_at": evidence.available_at,
        "decision_time": evidence.decision_time,
        "expires_at": evidence.expires_at,
        "exchange_credentials_read": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }


def default_commission_broker_store(data_root: Path) -> ImmutableSourcePayloadStore:
    """Return the shared bounded immutable store used by producer and reader."""

    if not isinstance(data_root, Path) or not data_root.is_absolute():
        _fail("COMMISSION_BROKER_DATA_ROOT_INVALID")
    return ImmutableSourcePayloadStore(data_root / "commission-evidence-cas")


__all__ = [
    "CONSUMER_READ_RECEIPT_SCHEMA_VERSION",
    "DYNAMIC_COMMISSION_UNIVERSE_KEY",
    "FALLBACK_REASON",
    "MAX_REDIS_EVIDENCE_BYTES",
    "POLICY_ID",
    "PRODUCER",
    "REDIS_CLAIM_KEY_PREFIX",
    "REDIS_KEY_PREFIX",
    "REDIS_VERSION_KEY_PREFIX",
    "ROTATION_ARTIFACT_SCHEMA_VERSION",
    "ROTATION_RECEIPT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SOURCE",
    "CommissionEvidenceBrokerError",
    "CommissionRotationPlan",
    "CredentiallessCommissionEvidence",
    "adaptive_commission_request_pacing_ms",
    "build_adaptive_rotation_plan",
    "capture_and_publish_next_commission_evidence",
    "credential_binding_for_adapter",
    "default_commission_broker_store",
    "read_authenticated_commission_evidence",
    "read_adaptive_commission_rotation_universe",
    "redis_claim_key",
    "redis_key",
    "redis_version_key",
]
