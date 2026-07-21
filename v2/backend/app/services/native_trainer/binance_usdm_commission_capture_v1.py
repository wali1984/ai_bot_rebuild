"""Factory-only Binance USD-M commission-rate capture evidence.

This module performs one read-only, signed ``GET /fapi/v1/commissionRate``
only after the repository's explicit REST-fallback policy reserves the exact
published request weight in the host-shared budget.  It never calls an order,
leverage, margin, transfer, or cancellation endpoint and has no service loop.

Successful response bytes are durably content-addressed before JSON parsing.
The resulting fee artifact and receipt intentionally match the detached fee
contract consumed by :mod:`causal_cost_evidence_v1`.  They grant no trainer,
prediction, paper, or live authority.  Evidence expiry is derived only from a
separately built durable adaptive refresh-policy receipt; there is no fee or
freshness fallback.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, NoReturn, cast
from urllib.parse import urlencode, urlsplit

import httpx

from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_rest_fallback_decision,
    report_binance_rest_response,
    resolve_binance_credential_binding,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
    CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION: Final = (
    "binance_usdm_commission_capture_token_v1"
)
BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION: Final = (
    "binance_usdm_commission_adaptive_refresh_policy_v1"
)
BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "binance_usdm_commission_adaptive_refresh_policy_receipt_v1"
)
BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION: Final = (
    "STRUCTURALLY_VALIDATED_DETACHED_SIGNED_COMMISSION_RESPONSE_UNWIRED"
)
BINANCE_USDM_COMMISSION_CAPTURE_DOWNSTREAM_STATUS: Final = (
    "UNWIRED_NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
BINANCE_USDM_COMMISSION_ENDPOINT: Final = "/fapi/v1/commissionRate"
BINANCE_USDM_COMMISSION_METHOD: Final = "GET"
BINANCE_USDM_COMMISSION_REQUEST_WEIGHT: Final = 20
BINANCE_USDM_COMMISSION_SHARED_BUDGET_REQUIRED: Final = True
BINANCE_USDM_COMMISSION_SECURITY_TYPE: Final = "USER_DATA"
BINANCE_USDM_COMMISSION_SOURCE_TRANSPORT: Final = (
    "DETACHED_SIGNED_BINANCE_USDM_COMMISSION_RESPONSE_UNWIRED"
)
BINANCE_USDM_MAINNET_ORIGIN: Final = "https://fapi.binance.com"
BINANCE_USDM_TESTNET_ORIGIN: Final = "https://testnet.binancefuture.com"
BINANCE_USDM_ALLOWED_ORIGINS: Final = frozenset(
    {BINANCE_USDM_MAINNET_ORIGIN, BINANCE_USDM_TESTNET_ORIGIN}
)

# Fees can change independently of market data.  An adaptive producer chooses
# the actual refresh interval and must bind it to a durable input receipt.  The
# only hard interval here is a conservative evidence-validity safety ceiling;
# it is not a market, strategy, risk, sizing, or admission threshold.
IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS: Final = 3_600
IMMUTABLE_MAX_HTTP_TIMEOUT_SECONDS: Final = 30.0
MIN_CREDENTIAL_FINGERPRINT_HMAC_KEY_BYTES: Final = 32
MAX_RAW_RESPONSE_BYTES: Final = 64 * 1024

_FINGERPRINT_DOMAIN: Final = b"AI_BOT_BINANCE_USDM_COMMISSION_BINDING_V1\x00"
_REQUEST_IDENTITY_DOMAIN: Final = "AI_BOT_BINANCE_USDM_COMMISSION_REQUEST_V1"
_CONSTRUCTION_TOKEN = object()
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$", re.ASCII)
_RATE_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{1,18}$", re.ASCII)
_RESPONSE_FIELDS = frozenset(
    {
        "symbol",
        "makerCommissionRate",
        "takerCommissionRate",
        "rpiCommissionRate",
    }
)

_REFRESH_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "policy_version",
        "symbol",
        "refresh_interval_seconds",
        "immutable_maximum_safety_horizon_seconds",
        "adaptive_input_receipt_sha256",
        "adaptive_basis",
        "generated_at",
        "available_at",
        "authority_scope",
        "fallback_used",
        "static_market_threshold_used",
        "trainer_authority",
        "prediction_authority",
        "paper_authority",
        "live_authority",
    }
)
_REFRESH_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_kind",
        "artifact_payload_sha256",
        "artifact_payload_byte_count",
        "artifact_cas_address",
        "policy_id",
        "policy_version",
        "symbol",
        "refresh_interval_seconds",
        "adaptive_input_receipt_sha256",
        "generated_at",
        "available_at",
        "recorded_at",
        "authority_scope",
        "receipt_sha256",
    }
)


class BinanceUSDMCommissionCaptureV1Error(RuntimeError):
    """Base fail-closed error with a stable, credential-safe reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BinanceUSDMCommissionCaptureV1ValidationError(BinanceUSDMCommissionCaptureV1Error):
    """Configuration, policy, response, or clock input is invalid."""


class BinanceUSDMCommissionCaptureV1IntegrityError(BinanceUSDMCommissionCaptureV1Error):
    """A factory token, receipt, hash, or durable CAS object was changed."""


class BinanceUSDMCommissionCaptureV1TransportError(BinanceUSDMCommissionCaptureV1Error):
    """The one authorized HTTP read failed without exposing its exception."""


class BinanceUSDMCommissionCaptureV1RateLimitError(BinanceUSDMCommissionCaptureV1Error):
    """Binance returned 418/429 and the shared cooldown was handled."""


@dataclass(frozen=True, slots=True)
class BinanceUSDMCommissionRefreshPolicyTokenV1:
    """Factory-sealed durable adaptive refresh policy."""

    artifact_bytes: bytes = field(repr=False)
    artifact_address: SourcePayloadAddress
    receipt_bytes: bytes = field(repr=False)
    receipt_address: SourcePayloadAddress
    receipt_sha256: str
    symbol: str
    refresh_interval_seconds: int
    generated_at: str
    available_at: str
    recorded_at: str
    adaptive_input_receipt_sha256: str
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def artifact(self) -> dict[str, Any]:
        artifact, _ = _validate_refresh_policy_token(self)
        return artifact

    @property
    def receipt(self) -> dict[str, Any]:
        _, receipt = _validate_refresh_policy_token(self)
        return receipt


@dataclass(frozen=True, slots=True)
class BinanceUSDMCommissionCaptureTokenV1:
    """Immutable output from the only commission-capture factory."""

    schema_version: str
    symbol: str
    raw_response_bytes: bytes = field(repr=False)
    raw_response_address: SourcePayloadAddress
    raw_response_sha256: str
    sanitized_request_identity_bytes: bytes = field(repr=False)
    sanitized_request_identity_address: SourcePayloadAddress
    sanitized_request_identity_sha256: str
    credential_binding_fingerprint_sha256: str
    request_started_at: str
    response_observed_at: str
    available_at: str
    expires_at: str
    maker_commission_bps: float
    taker_commission_bps: float
    rpi_commission_bps: float
    fee_artifact_bytes: bytes = field(repr=False)
    fee_artifact_address: SourcePayloadAddress
    fee_receipt_bytes: bytes = field(repr=False)
    fee_receipt_address: SourcePayloadAddress
    fee_receipt_sha256: str
    refresh_policy_receipt_sha256: str
    request_weight: int
    shared_budget_required: bool
    read_only: bool
    trainer_authority: bool
    prediction_authority: bool
    paper_authority: bool
    live_authority: bool
    _refresh_policy: BinanceUSDMCommissionRefreshPolicyTokenV1 = field(
        repr=False,
        compare=False,
    )
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def contract(self) -> dict[str, Any]:
        return _validate_capture_token(self)

    @property
    def fee_artifact(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.contract["fee_artifact"])

    @property
    def fee_schedule_receipt(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.contract["fee_schedule_receipt"])


def _validation(reason: str) -> NoReturn:
    raise BinanceUSDMCommissionCaptureV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise BinanceUSDMCommissionCaptureV1IntegrityError(reason) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation(reason)
    if not encoded or len(encoded) > MAX_RAW_RESPONSE_BYTES:
        _validation(reason)
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _put_exact(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
    *,
    reason: str,
) -> SourcePayloadAddress:
    if type(store) is not ImmutableSourcePayloadStore:
        _validation("COMMISSION_CAPTURE_IMMUTABLE_STORE_REQUIRED")
    digest = _sha256_bytes(payload)
    try:
        address = store.put(
            payload,
            expected_sha256=digest,
            expected_byte_count=len(payload),
        )
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise BinanceUSDMCommissionCaptureV1IntegrityError(reason) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != digest
        or address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(reason)
    return address


def _readback_exact(
    store: ImmutableSourcePayloadStore,
    address: object,
    expected: object,
    *,
    reason: str,
) -> None:
    if type(address) is not SourcePayloadAddress or type(expected) is not bytes:
        _integrity(reason)
    typed_address = cast(SourcePayloadAddress, address)
    typed_expected = cast(bytes, expected)
    digest = _sha256_bytes(typed_expected)
    if (
        typed_address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or typed_address.payload_sha256 != digest
        or typed_address.payload_byte_count != len(typed_expected)
    ):
        _integrity(reason)
    try:
        readback = store.get(digest, expected_byte_count=len(typed_expected))
    except SourcePayloadStoreError as exc:
        raise BinanceUSDMCommissionCaptureV1IntegrityError(reason) from exc
    if not hmac.compare_digest(readback, typed_expected):
        _integrity(reason)


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value.endswith("Z") and value == value.strip():
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except (OverflowError, ValueError):
            _validation(reason)
    else:
        _validation(reason)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _validation(reason)
    parsed = parsed.astimezone(UTC)
    if parsed <= _EPOCH:
        _validation(reason)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _now(now_fn: Callable[[], datetime], *, reason: str) -> tuple[str, datetime]:
    if not callable(now_fn):
        _validation(reason)
    try:
        value = now_fn()
    except Exception:
        _validation(reason)
    return _clock(value, reason=reason)


def _safe_id(value: object, *, reason: str) -> str:
    if type(value) is not str or value != value.strip() or _SAFE_ID_RE.fullmatch(value) is None:
        _validation(reason)
    return value


def _symbol(value: object) -> str:
    if type(value) is not str or value != value.strip() or _SYMBOL_RE.fullmatch(value) is None:
        _validation("COMMISSION_CAPTURE_SYMBOL_INVALID")
    return value


def _sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _validation(reason)
    return value


def _origin(value: object) -> str:
    if type(value) is not str or not value:
        _validation("COMMISSION_CAPTURE_BASE_URL_INVALID")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        _validation("COMMISSION_CAPTURE_BASE_URL_INVALID")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.hostname is None
        or port not in {None, 443}
    ):
        _validation("COMMISSION_CAPTURE_BASE_URL_INVALID")
    resolved = f"https://{parsed.hostname.lower()}"
    if resolved not in BINANCE_USDM_ALLOWED_ORIGINS:
        _validation("COMMISSION_CAPTURE_BASE_URL_NOT_OFFICIAL_USDM")
    return resolved


def _positive_interval(value: object) -> int:
    if (
        type(value) is not int
        or not 1 <= value <= IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
    ):
        _validation("COMMISSION_REFRESH_INTERVAL_OUTSIDE_IMMUTABLE_SAFETY_HORIZON")
    return value


def _parse_exact_canonical_object(payload: object, *, reason: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > MAX_RAW_RESPONSE_BYTES:
        _validation(reason)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _validation(reason)
            result[key] = value
        return result

    def reject_constant(_: str) -> NoReturn:
        _validation(reason)

    try:
        parsed = json.loads(
            cast(bytes, payload).decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except BinanceUSDMCommissionCaptureV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation(reason)
    if type(parsed) is not dict:
        _validation(reason)
    expected = _canonical_bytes(parsed, reason=reason)
    if not hmac.compare_digest(expected, cast(bytes, payload)):
        _validation(reason)
    return cast(dict[str, Any], parsed)


def _parse_response(
    payload: object, *, expected_symbol: str
) -> tuple[dict[str, Any], float, float, float]:
    if type(payload) is not bytes or not payload or len(payload) > MAX_RAW_RESPONSE_BYTES:
        _validation("COMMISSION_CAPTURE_RAW_RESPONSE_BYTES_INVALID")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _validation("COMMISSION_CAPTURE_RESPONSE_JSON_INVALID")
            result[key] = value
        return result

    def reject_constant(_: str) -> NoReturn:
        _validation("COMMISSION_CAPTURE_RESPONSE_JSON_INVALID")

    try:
        decoded = json.loads(
            cast(bytes, payload).decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except BinanceUSDMCommissionCaptureV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation("COMMISSION_CAPTURE_RESPONSE_JSON_INVALID")
    if type(decoded) is not dict or frozenset(decoded) != _RESPONSE_FIELDS:
        _validation("COMMISSION_CAPTURE_RESPONSE_EXACT_FOUR_FIELD_SHAPE_REQUIRED")
    typed = cast(dict[str, Any], decoded)
    if typed.get("symbol") != expected_symbol:
        _validation("COMMISSION_CAPTURE_RESPONSE_SYMBOL_MISMATCH")

    def rate_bps(name: str) -> float:
        value = typed.get(name)
        if type(value) is not str or _RATE_RE.fullmatch(value) is None:
            _validation(f"COMMISSION_CAPTURE_{name.upper()}_INVALID")
        try:
            parsed = Decimal(value)
            bps = float(parsed * Decimal(10_000))
        except (InvalidOperation, OverflowError, ValueError):
            _validation(f"COMMISSION_CAPTURE_{name.upper()}_INVALID")
        if not parsed.is_finite() or parsed < 0 or not math.isfinite(bps):
            _validation(f"COMMISSION_CAPTURE_{name.upper()}_INVALID")
        return 0.0 if bps == 0.0 else bps

    return (
        typed,
        rate_bps("makerCommissionRate"),
        rate_bps("takerCommissionRate"),
        rate_bps("rpiCommissionRate"),
    )


def _self_hashed_receipt(payload: object, *, fields: frozenset[str], reason: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _validation(reason)
    result = dict(payload)
    if frozenset(result) != fields:
        _validation(reason)
    supplied = result.pop("receipt_sha256", None)
    if type(supplied) is not str or _SHA256_RE.fullmatch(supplied) is None:
        _validation(reason)
    expected = _sha256_bytes(_canonical_bytes(result, reason=reason))
    if not hmac.compare_digest(supplied, expected):
        _validation(reason)
    return {**result, "receipt_sha256": supplied}


def build_binance_usdm_commission_refresh_policy_v1(
    *,
    store: ImmutableSourcePayloadStore,
    symbol: object,
    policy_id: object,
    policy_version: object,
    refresh_interval_seconds: object,
    adaptive_input_receipt_sha256: object,
    generated_at: object,
    available_at: object,
    recorded_at: object,
) -> BinanceUSDMCommissionRefreshPolicyTokenV1:
    """Durably seal an explicit adaptive evidence-refresh decision."""

    resolved_symbol = _symbol(symbol)
    resolved_policy_id = _safe_id(policy_id, reason="COMMISSION_REFRESH_POLICY_ID_INVALID")
    resolved_policy_version = _safe_id(
        policy_version,
        reason="COMMISSION_REFRESH_POLICY_VERSION_INVALID",
    )
    interval = _positive_interval(refresh_interval_seconds)
    adaptive_receipt = _sha256(
        adaptive_input_receipt_sha256,
        reason="COMMISSION_REFRESH_ADAPTIVE_INPUT_RECEIPT_INVALID",
    )
    generated_iso, generated_clock = _clock(
        generated_at,
        reason="COMMISSION_REFRESH_GENERATED_AT_INVALID",
    )
    available_iso, available_clock = _clock(
        available_at,
        reason="COMMISSION_REFRESH_AVAILABLE_AT_INVALID",
    )
    recorded_iso, recorded_clock = _clock(
        recorded_at,
        reason="COMMISSION_REFRESH_RECORDED_AT_INVALID",
    )
    if not generated_clock <= available_clock <= recorded_clock:
        _validation("COMMISSION_REFRESH_POLICY_CLOCK_ORDER_INVALID")

    artifact = {
        "schema_version": BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION,
        "policy_id": resolved_policy_id,
        "policy_version": resolved_policy_version,
        "symbol": resolved_symbol,
        "refresh_interval_seconds": interval,
        "immutable_maximum_safety_horizon_seconds": (
            IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
        ),
        "adaptive_input_receipt_sha256": adaptive_receipt,
        "adaptive_basis": "DURABLE_UPSTREAM_ADAPTIVE_REFRESH_INPUT_RECEIPT",
        "generated_at": generated_iso,
        "available_at": available_iso,
        "authority_scope": "FEE_EVIDENCE_EXPIRY_ONLY",
        "fallback_used": False,
        "static_market_threshold_used": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    artifact_bytes = _canonical_bytes(
        artifact,
        reason="COMMISSION_REFRESH_POLICY_ARTIFACT_JSON_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        reason="COMMISSION_REFRESH_POLICY_ARTIFACT_CAS_FAILED",
    )
    receipt_without_hash = {
        "schema_version": BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DURABLE_CAS_APPEND",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "artifact_cas_address": _address_mapping(artifact_address),
        "policy_id": resolved_policy_id,
        "policy_version": resolved_policy_version,
        "symbol": resolved_symbol,
        "refresh_interval_seconds": interval,
        "adaptive_input_receipt_sha256": adaptive_receipt,
        "generated_at": generated_iso,
        "available_at": available_iso,
        "recorded_at": recorded_iso,
        "authority_scope": "FEE_EVIDENCE_EXPIRY_ONLY",
    }
    receipt_sha256 = _sha256_bytes(
        _canonical_bytes(
            receipt_without_hash,
            reason="COMMISSION_REFRESH_POLICY_RECEIPT_JSON_INVALID",
        )
    )
    receipt = {**receipt_without_hash, "receipt_sha256": receipt_sha256}
    receipt_bytes = _canonical_bytes(
        receipt,
        reason="COMMISSION_REFRESH_POLICY_RECEIPT_JSON_INVALID",
    )
    receipt_address = _put_exact(
        store,
        receipt_bytes,
        reason="COMMISSION_REFRESH_POLICY_RECEIPT_CAS_FAILED",
    )
    token = BinanceUSDMCommissionRefreshPolicyTokenV1(
        artifact_bytes=artifact_bytes,
        artifact_address=artifact_address,
        receipt_bytes=receipt_bytes,
        receipt_address=receipt_address,
        receipt_sha256=receipt_sha256,
        symbol=resolved_symbol,
        refresh_interval_seconds=interval,
        generated_at=generated_iso,
        available_at=available_iso,
        recorded_at=recorded_iso,
        adaptive_input_receipt_sha256=adaptive_receipt,
        _store=store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_refresh_policy_token(token)
    return token


def _validate_refresh_policy_token(
    token: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(token) is not BinanceUSDMCommissionRefreshPolicyTokenV1
        or token._construction_token is not _CONSTRUCTION_TOKEN
        or type(token._store) is not ImmutableSourcePayloadStore
    ):
        _integrity("COMMISSION_REFRESH_POLICY_FACTORY_TOKEN_REQUIRED")
    typed = cast(BinanceUSDMCommissionRefreshPolicyTokenV1, token)
    artifact = _parse_exact_canonical_object(
        typed.artifact_bytes,
        reason="COMMISSION_REFRESH_POLICY_ARTIFACT_INVALID",
    )
    receipt = _parse_exact_canonical_object(
        typed.receipt_bytes,
        reason="COMMISSION_REFRESH_POLICY_RECEIPT_INVALID",
    )
    if frozenset(artifact) != _REFRESH_POLICY_FIELDS:
        _integrity("COMMISSION_REFRESH_POLICY_ARTIFACT_FIELDS_INVALID")
    if frozenset(receipt) != _REFRESH_RECEIPT_FIELDS:
        _integrity("COMMISSION_REFRESH_POLICY_RECEIPT_FIELDS_INVALID")
    validated_receipt = _self_hashed_receipt(
        receipt,
        fields=_REFRESH_RECEIPT_FIELDS,
        reason="COMMISSION_REFRESH_POLICY_RECEIPT_SELF_HASH_INVALID",
    )
    symbol = _symbol(typed.symbol)
    interval = _positive_interval(typed.refresh_interval_seconds)
    adaptive_receipt = _sha256(
        typed.adaptive_input_receipt_sha256,
        reason="COMMISSION_REFRESH_ADAPTIVE_INPUT_RECEIPT_INVALID",
    )
    generated_iso, generated_at = _clock(
        typed.generated_at,
        reason="COMMISSION_REFRESH_GENERATED_AT_INVALID",
    )
    available_iso, available_at = _clock(
        typed.available_at,
        reason="COMMISSION_REFRESH_AVAILABLE_AT_INVALID",
    )
    recorded_iso, recorded_at = _clock(
        typed.recorded_at,
        reason="COMMISSION_REFRESH_RECORDED_AT_INVALID",
    )
    if not generated_at <= available_at <= recorded_at:
        _integrity("COMMISSION_REFRESH_POLICY_CLOCK_ORDER_INVALID")
    expected_artifact = {
        "schema_version": BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION,
        "policy_id": artifact.get("policy_id"),
        "policy_version": artifact.get("policy_version"),
        "symbol": symbol,
        "refresh_interval_seconds": interval,
        "immutable_maximum_safety_horizon_seconds": (
            IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
        ),
        "adaptive_input_receipt_sha256": adaptive_receipt,
        "adaptive_basis": "DURABLE_UPSTREAM_ADAPTIVE_REFRESH_INPUT_RECEIPT",
        "generated_at": generated_iso,
        "available_at": available_iso,
        "authority_scope": "FEE_EVIDENCE_EXPIRY_ONLY",
        "fallback_used": False,
        "static_market_threshold_used": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    _safe_id(expected_artifact["policy_id"], reason="COMMISSION_REFRESH_POLICY_ID_INVALID")
    _safe_id(
        expected_artifact["policy_version"],
        reason="COMMISSION_REFRESH_POLICY_VERSION_INVALID",
    )
    if artifact != expected_artifact:
        _integrity("COMMISSION_REFRESH_POLICY_ARTIFACT_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.artifact_address,
        typed.artifact_bytes,
        reason="COMMISSION_REFRESH_POLICY_ARTIFACT_CAS_FAILED",
    )
    expected_receipt = {
        "schema_version": BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DURABLE_CAS_APPEND",
        "artifact_payload_sha256": typed.artifact_address.payload_sha256,
        "artifact_payload_byte_count": typed.artifact_address.payload_byte_count,
        "artifact_cas_address": _address_mapping(typed.artifact_address),
        "policy_id": artifact["policy_id"],
        "policy_version": artifact["policy_version"],
        "symbol": symbol,
        "refresh_interval_seconds": interval,
        "adaptive_input_receipt_sha256": adaptive_receipt,
        "generated_at": generated_iso,
        "available_at": available_iso,
        "recorded_at": recorded_iso,
        "authority_scope": "FEE_EVIDENCE_EXPIRY_ONLY",
    }
    if any(validated_receipt.get(key) != value for key, value in expected_receipt.items()):
        _integrity("COMMISSION_REFRESH_POLICY_RECEIPT_BINDING_INVALID")
    if typed.receipt_sha256 != validated_receipt["receipt_sha256"]:
        _integrity("COMMISSION_REFRESH_POLICY_RECEIPT_SHA_INVALID")
    _readback_exact(
        typed._store,
        typed.receipt_address,
        typed.receipt_bytes,
        reason="COMMISSION_REFRESH_POLICY_RECEIPT_CAS_FAILED",
    )
    return artifact, validated_receipt


def _fingerprint_key(value: object, *, api_key: str, api_secret: str) -> bytes:
    if isinstance(value, str):
        resolved = value.encode("utf-8")
    elif isinstance(value, bytes | bytearray):
        resolved = bytes(value)
    else:
        resolved = b""
    if len(resolved) < MIN_CREDENTIAL_FINGERPRINT_HMAC_KEY_BYTES:
        _validation("COMMISSION_CAPTURE_CREDENTIAL_FINGERPRINT_HMAC_KEY_TOO_SHORT")
    if hmac.compare_digest(resolved, api_key.encode("utf-8")) or hmac.compare_digest(
        resolved,
        api_secret.encode("utf-8"),
    ):
        _validation("COMMISSION_CAPTURE_FINGERPRINT_KEY_MUST_DIFFER_FROM_CREDENTIALS")
    return resolved


def _credential_fingerprint(
    *,
    binding: Any,
    origin: str,
    hmac_key: bytes,
) -> str:
    public_binding = {
        "account_specific": True,
        "api_key_name": binding.api_key_name,
        "api_secret_name": binding.api_secret_name,
        "credential_ref": binding.credential_ref,
        "origin": origin,
        "read_only_ref": True,
        "trader_id": binding.trader_id,
    }
    public_bytes = _canonical_bytes(
        public_binding,
        reason="COMMISSION_CAPTURE_CREDENTIAL_BINDING_METADATA_INVALID",
    )
    # The separate local key authenticates a one-way binding to both exchange
    # credential values.  Neither credential nor their raw hashes are kept.
    message = (
        _FINGERPRINT_DOMAIN
        + public_bytes
        + b"\x00"
        + binding.api_key.encode("utf-8")
        + b"\x00"
        + binding.api_secret.encode("utf-8")
    )
    return hmac.new(hmac_key, message, hashlib.sha256).hexdigest()


def _retry_after_seconds(headers: object) -> float | None:
    if not isinstance(headers, Mapping):
        return None
    raw: object = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = value
            break
    try:
        parsed = float(cast(Any, raw))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _default_http_get(
    *,
    method: str,
    url: str,
    params: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Any:
    if method != BINANCE_USDM_COMMISSION_METHOD:
        _integrity("COMMISSION_CAPTURE_NON_GET_TRANSPORT_FORBIDDEN")
    with httpx.Client(timeout=timeout_seconds) as client:
        return client.get(url, params=params, headers=headers)


def _response_bytes(response: object) -> tuple[int, bytes, object]:
    typed_response = cast(Any, response)
    try:
        status_code = typed_response.status_code
        raw_bytes = typed_response.content
        headers = getattr(typed_response, "headers", {})
    except Exception:
        raise BinanceUSDMCommissionCaptureV1TransportError(
            "COMMISSION_CAPTURE_HTTP_RESPONSE_UNREADABLE"
        ) from None
    if type(status_code) is not int or isinstance(status_code, bool):
        _validation("COMMISSION_CAPTURE_HTTP_STATUS_INVALID")
    if type(raw_bytes) is not bytes:
        _validation("COMMISSION_CAPTURE_RAW_RESPONSE_BYTES_INVALID")
    return status_code, raw_bytes, headers


def capture_binance_usdm_commission_rate_v1(
    *,
    store: ImmutableSourcePayloadStore,
    symbol: object,
    refresh_policy: object,
    fallback_reason: object,
    credential_fingerprint_hmac_key: object,
    base_url: object = BINANCE_USDM_MAINNET_ORIGIN,
    timeout_seconds: object = 10.0,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    http_get: Callable[..., Any] = _default_http_get,
) -> BinanceUSDMCommissionCaptureTokenV1:
    """Execute exactly one policy-authorized signed commission GET."""

    resolved_symbol = _symbol(symbol)
    origin = _origin(base_url)
    reason = _safe_id(
        fallback_reason,
        reason="COMMISSION_CAPTURE_EXPLICIT_FALLBACK_REASON_REQUIRED",
    )
    if type(timeout_seconds) not in {int, float}:
        _validation("COMMISSION_CAPTURE_HTTP_TIMEOUT_INVALID")
    timeout = float(cast(int | float, timeout_seconds))
    if not math.isfinite(timeout) or not 0.0 < timeout <= IMMUTABLE_MAX_HTTP_TIMEOUT_SECONDS:
        _validation("COMMISSION_CAPTURE_HTTP_TIMEOUT_INVALID")
    if not callable(http_get):
        _validation("COMMISSION_CAPTURE_HTTP_GET_FACTORY_INVALID")

    _validate_refresh_policy_token(refresh_policy)
    policy_token = cast(BinanceUSDMCommissionRefreshPolicyTokenV1, refresh_policy)
    if policy_token.symbol != resolved_symbol:
        _validation("COMMISSION_CAPTURE_REFRESH_POLICY_SYMBOL_MISMATCH")

    binding = resolve_binance_credential_binding()
    if not binding.is_configured:
        _validation("COMMISSION_CAPTURE_CREDENTIAL_BINDING_NOT_CONFIGURED")
    if binding.account_specific is not True:
        _validation("COMMISSION_CAPTURE_ACCOUNT_SPECIFIC_CREDENTIAL_REQUIRED")
    if binding.read_only_ref is not True:
        _validation("COMMISSION_CAPTURE_READ_ONLY_CREDENTIAL_REF_REQUIRED")
    for value, failure in (
        (binding.trader_id, "COMMISSION_CAPTURE_TRADER_ID_INVALID"),
        (binding.credential_ref, "COMMISSION_CAPTURE_CREDENTIAL_REF_INVALID"),
        (binding.api_key, "COMMISSION_CAPTURE_API_KEY_MISSING"),
        (binding.api_secret, "COMMISSION_CAPTURE_API_SECRET_MISSING"),
    ):
        if type(value) is not str or not value:
            _validation(failure)
    fingerprint_key = _fingerprint_key(
        credential_fingerprint_hmac_key,
        api_key=binding.api_key,
        api_secret=binding.api_secret,
    )
    fingerprint = _credential_fingerprint(
        binding=binding,
        origin=origin,
        hmac_key=fingerprint_key,
    )

    request_started_iso, request_started_at = _now(
        now_fn,
        reason="COMMISSION_CAPTURE_REQUEST_STARTED_CLOCK_INVALID",
    )
    _, policy_recorded_at = _clock(
        policy_token.recorded_at,
        reason="COMMISSION_REFRESH_RECORDED_AT_INVALID",
    )
    if policy_recorded_at > request_started_at:
        _validation("COMMISSION_CAPTURE_REFRESH_POLICY_NOT_AVAILABLE_AT_REQUEST")
    timestamp_ms = int(request_started_at.timestamp() * 1_000)
    unsigned_params: dict[str, Any] = {
        "symbol": resolved_symbol,
        "timestamp": timestamp_ms,
    }
    query = urlencode(unsigned_params)
    signature = hmac.new(
        binding.api_secret.encode("utf-8"),
        query.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    signed_params = {**unsigned_params, "signature": signature}
    headers = {"X-MBX-APIKEY": binding.api_key}

    decision = binance_rest_fallback_decision(
        endpoint=f"{BINANCE_USDM_COMMISSION_METHOD} {BINANCE_USDM_COMMISSION_ENDPOINT}",
        fallback_reason=reason,
        role="signed_read_recovery",
        request_weight=BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        require_shared_budget=BINANCE_USDM_COMMISSION_SHARED_BUDGET_REQUIRED,
    )
    if not isinstance(decision, Mapping) or decision.get("request_allowed") is not True:
        _validation("COMMISSION_CAPTURE_REST_FALLBACK_OR_SHARED_BUDGET_BLOCKED")
    if (
        decision.get("request_weight") != BINANCE_USDM_COMMISSION_REQUEST_WEIGHT
        or decision.get("shared_budget_required") is not True
        or decision.get("budget_scope") != "host_redis"
        or decision.get("rest_used_as_primary") is not False
        or decision.get("transport_role") != "fallback_only"
    ):
        _integrity("COMMISSION_CAPTURE_SHARED_BUDGET_DECISION_INVALID")

    try:
        response = http_get(
            method=BINANCE_USDM_COMMISSION_METHOD,
            url=f"{origin}{BINANCE_USDM_COMMISSION_ENDPOINT}",
            params=signed_params,
            headers=headers,
            timeout_seconds=timeout,
        )
    except BinanceUSDMCommissionCaptureV1Error:
        raise
    except Exception:
        # Never chain a transport exception: request objects commonly contain
        # the API key and signed query string.
        raise BinanceUSDMCommissionCaptureV1TransportError(
            "COMMISSION_CAPTURE_HTTP_GET_FAILED"
        ) from None

    status_code, raw_response_bytes, response_headers = _response_bytes(response)
    response_observed_iso, response_observed_at = _now(
        now_fn,
        reason="COMMISSION_CAPTURE_RESPONSE_OBSERVED_CLOCK_INVALID",
    )
    if response_observed_at < request_started_at:
        _validation("COMMISSION_CAPTURE_RESPONSE_CLOCK_PRECEDES_REQUEST")

    if status_code in {418, 429}:
        cooldown_recorded = report_binance_rest_response(
            status_code=status_code,
            retry_after_seconds=_retry_after_seconds(response_headers),
        )
        if cooldown_recorded is not True:
            raise BinanceUSDMCommissionCaptureV1RateLimitError(
                "COMMISSION_CAPTURE_SHARED_COOLDOWN_PERSISTENCE_FAILED"
            ) from None
        raise BinanceUSDMCommissionCaptureV1RateLimitError(
            f"COMMISSION_CAPTURE_BINANCE_HTTP_{status_code}_SHARED_COOLDOWN_ARMED"
        ) from None
    if status_code != 200:
        _validation("COMMISSION_CAPTURE_HTTP_200_REQUIRED")
    if not raw_response_bytes or len(raw_response_bytes) > MAX_RAW_RESPONSE_BYTES:
        _validation("COMMISSION_CAPTURE_RAW_RESPONSE_BYTES_INVALID")

    # This durable write intentionally precedes every JSON decode operation.
    raw_address = _put_exact(
        store,
        raw_response_bytes,
        reason="COMMISSION_CAPTURE_RAW_RESPONSE_CAS_FAILED",
    )
    raw_sha256 = _sha256_bytes(raw_response_bytes)
    response_payload, maker_bps, taker_bps, rpi_bps = _parse_response(
        raw_response_bytes,
        expected_symbol=resolved_symbol,
    )

    available_iso, available_at = _now(
        now_fn,
        reason="COMMISSION_CAPTURE_AVAILABLE_AT_CLOCK_INVALID",
    )
    if available_at < response_observed_at:
        _validation("COMMISSION_CAPTURE_AVAILABLE_CLOCK_PRECEDES_RESPONSE")
    expires_at = available_at + timedelta(seconds=policy_token.refresh_interval_seconds)
    immutable_max_expiry = available_at + timedelta(
        seconds=IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
    )
    if expires_at > immutable_max_expiry:
        _integrity("COMMISSION_CAPTURE_EXPIRY_EXCEEDS_IMMUTABLE_SAFETY_HORIZON")
    expires_iso = expires_at.isoformat(timespec="microseconds").replace("+00:00", "Z")

    sanitized_request_identity = {
        "domain": _REQUEST_IDENTITY_DOMAIN,
        "method": BINANCE_USDM_COMMISSION_METHOD,
        "origin": origin,
        "path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "security_type": BINANCE_USDM_COMMISSION_SECURITY_TYPE,
        "symbol": resolved_symbol,
        "timestamp_ms": timestamp_ms,
        "signed_parameter_names": ["signature", "symbol", "timestamp"],
        "api_key_header_present": True,
        "api_key_value_stored": False,
        "signature_value_stored": False,
        "fallback_reason_sha256": hashlib.sha256(reason.encode("ascii")).hexdigest(),
        "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "shared_budget_required": True,
        "shared_budget_scope": "host_redis",
        "refresh_policy_artifact_sha256": policy_token.artifact_address.payload_sha256,
        "refresh_policy_receipt_sha256": policy_token.receipt_sha256,
        "refresh_interval_seconds": policy_token.refresh_interval_seconds,
        "immutable_maximum_safety_horizon_seconds": (
            IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
        ),
        "expires_at": expires_iso,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    request_identity_bytes = _canonical_bytes(
        sanitized_request_identity,
        reason="COMMISSION_CAPTURE_SANITIZED_REQUEST_IDENTITY_INVALID",
    )
    request_identity_address = _put_exact(
        store,
        request_identity_bytes,
        reason="COMMISSION_CAPTURE_REQUEST_IDENTITY_CAS_FAILED",
    )
    request_identity_sha256 = request_identity_address.payload_sha256

    artifact = {
        "schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "capture_classification": BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION,
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": resolved_symbol,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS",
        "taker_fee_bps_per_side": taker_bps,
        "effective_at": available_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "source_key": f"v2:account:fee_schedule:{resolved_symbol}",
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "source_revision": raw_sha256,
        "raw_response_sha256": raw_sha256,
        "raw_response_byte_count": len(raw_response_bytes),
        "raw_response_cas_address": _address_mapping(raw_address),
        "sanitized_request_identity_sha256": request_identity_sha256,
        "credential_binding_fingerprint_sha256": fingerprint,
        "http_status": 200,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "response_observed_at": response_observed_iso,
        "rpi_commission_rate_decimal": response_payload["rpiCommissionRate"],
        "rpi_commission_bps": rpi_bps,
    }
    artifact_bytes = _canonical_bytes(
        artifact,
        reason="COMMISSION_CAPTURE_FEE_ARTIFACT_JSON_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        reason="COMMISSION_CAPTURE_FEE_ARTIFACT_CAS_FAILED",
    )
    receipt_without_hash = {
        "schema_version": CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "source_key": f"v2:account:fee_schedule:{resolved_symbol}",
        "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": BINANCE_USDM_COMMISSION_SOURCE_TRANSPORT,
        "symbol": resolved_symbol,
        "effective_at": available_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "capture_classification": BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION,
        "raw_response_sha256": raw_sha256,
        "raw_response_byte_count": len(raw_response_bytes),
        "raw_response_cas_address": _address_mapping(raw_address),
        "sanitized_request_identity_sha256": request_identity_sha256,
        "credential_binding_fingerprint_sha256": fingerprint,
        "http_status": 200,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "response_observed_at": response_observed_iso,
        "rpi_commission_rate_decimal": response_payload["rpiCommissionRate"],
        "rpi_commission_bps": rpi_bps,
    }
    receipt_sha256 = _sha256_bytes(
        _canonical_bytes(
            receipt_without_hash,
            reason="COMMISSION_CAPTURE_FEE_RECEIPT_JSON_INVALID",
        )
    )
    receipt = {**receipt_without_hash, "receipt_sha256": receipt_sha256}
    receipt_bytes = _canonical_bytes(
        receipt,
        reason="COMMISSION_CAPTURE_FEE_RECEIPT_JSON_INVALID",
    )
    receipt_address = _put_exact(
        store,
        receipt_bytes,
        reason="COMMISSION_CAPTURE_FEE_RECEIPT_CAS_FAILED",
    )

    token = BinanceUSDMCommissionCaptureTokenV1(
        schema_version=BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION,
        symbol=resolved_symbol,
        raw_response_bytes=raw_response_bytes,
        raw_response_address=raw_address,
        raw_response_sha256=raw_sha256,
        sanitized_request_identity_bytes=request_identity_bytes,
        sanitized_request_identity_address=request_identity_address,
        sanitized_request_identity_sha256=request_identity_sha256,
        credential_binding_fingerprint_sha256=fingerprint,
        request_started_at=request_started_iso,
        response_observed_at=response_observed_iso,
        available_at=available_iso,
        expires_at=expires_iso,
        maker_commission_bps=maker_bps,
        taker_commission_bps=taker_bps,
        rpi_commission_bps=rpi_bps,
        fee_artifact_bytes=artifact_bytes,
        fee_artifact_address=artifact_address,
        fee_receipt_bytes=receipt_bytes,
        fee_receipt_address=receipt_address,
        fee_receipt_sha256=receipt_sha256,
        refresh_policy_receipt_sha256=policy_token.receipt_sha256,
        request_weight=BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        shared_budget_required=True,
        read_only=True,
        trainer_authority=False,
        prediction_authority=False,
        paper_authority=False,
        live_authority=False,
        _refresh_policy=policy_token,
        _store=store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_capture_token(token)
    return token


def _validate_capture_token(token: object) -> dict[str, Any]:
    if (
        type(token) is not BinanceUSDMCommissionCaptureTokenV1
        or token._construction_token is not _CONSTRUCTION_TOKEN
        or type(token._store) is not ImmutableSourcePayloadStore
    ):
        _integrity("COMMISSION_CAPTURE_FACTORY_TOKEN_REQUIRED")
    typed = cast(BinanceUSDMCommissionCaptureTokenV1, token)
    policy_artifact, policy_receipt = _validate_refresh_policy_token(typed._refresh_policy)
    if typed.schema_version != BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION:
        _integrity("COMMISSION_CAPTURE_TOKEN_SCHEMA_INVALID")
    symbol = _symbol(typed.symbol)
    if typed._refresh_policy.symbol != symbol:
        _integrity("COMMISSION_CAPTURE_POLICY_SYMBOL_BINDING_INVALID")
    if typed.refresh_policy_receipt_sha256 != typed._refresh_policy.receipt_sha256:
        _integrity("COMMISSION_CAPTURE_POLICY_RECEIPT_BINDING_INVALID")
    for address, payload, reason in (
        (
            typed.raw_response_address,
            typed.raw_response_bytes,
            "COMMISSION_CAPTURE_RAW_RESPONSE_CAS_FAILED",
        ),
        (
            typed.sanitized_request_identity_address,
            typed.sanitized_request_identity_bytes,
            "COMMISSION_CAPTURE_REQUEST_IDENTITY_CAS_FAILED",
        ),
        (
            typed.fee_artifact_address,
            typed.fee_artifact_bytes,
            "COMMISSION_CAPTURE_FEE_ARTIFACT_CAS_FAILED",
        ),
        (
            typed.fee_receipt_address,
            typed.fee_receipt_bytes,
            "COMMISSION_CAPTURE_FEE_RECEIPT_CAS_FAILED",
        ),
    ):
        _readback_exact(typed._store, address, payload, reason=reason)

    response_payload, maker_bps, taker_bps, rpi_bps = _parse_response(
        typed.raw_response_bytes,
        expected_symbol=symbol,
    )
    if typed.raw_response_sha256 != _sha256_bytes(typed.raw_response_bytes):
        _integrity("COMMISSION_CAPTURE_RAW_RESPONSE_SHA_INVALID")
    if any(
        not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12)
        for observed, expected in (
            (typed.maker_commission_bps, maker_bps),
            (typed.taker_commission_bps, taker_bps),
            (typed.rpi_commission_bps, rpi_bps),
        )
    ):
        _integrity("COMMISSION_CAPTURE_DERIVED_RATE_BINDING_INVALID")

    request_iso, request_at = _clock(
        typed.request_started_at,
        reason="COMMISSION_CAPTURE_REQUEST_STARTED_CLOCK_INVALID",
    )
    observed_iso, observed_at = _clock(
        typed.response_observed_at,
        reason="COMMISSION_CAPTURE_RESPONSE_OBSERVED_CLOCK_INVALID",
    )
    available_iso, available_at = _clock(
        typed.available_at,
        reason="COMMISSION_CAPTURE_AVAILABLE_AT_CLOCK_INVALID",
    )
    expires_iso, expires_at = _clock(
        typed.expires_at,
        reason="COMMISSION_CAPTURE_EXPIRES_AT_CLOCK_INVALID",
    )
    expected_expires = available_at + timedelta(
        seconds=typed._refresh_policy.refresh_interval_seconds
    )
    if not (
        request_at <= observed_at <= available_at < expires_at
        and expires_at == expected_expires
        and expires_at
        <= available_at
        + timedelta(seconds=IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS)
    ):
        _integrity("COMMISSION_CAPTURE_CLOCK_OR_EXPIRY_BINDING_INVALID")

    request_identity = _parse_exact_canonical_object(
        typed.sanitized_request_identity_bytes,
        reason="COMMISSION_CAPTURE_SANITIZED_REQUEST_IDENTITY_INVALID",
    )
    expected_request_identity = {
        "domain": _REQUEST_IDENTITY_DOMAIN,
        "method": BINANCE_USDM_COMMISSION_METHOD,
        "origin": request_identity.get("origin"),
        "path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "security_type": BINANCE_USDM_COMMISSION_SECURITY_TYPE,
        "symbol": symbol,
        "timestamp_ms": int(request_at.timestamp() * 1_000),
        "signed_parameter_names": ["signature", "symbol", "timestamp"],
        "api_key_header_present": True,
        "api_key_value_stored": False,
        "signature_value_stored": False,
        "fallback_reason_sha256": request_identity.get("fallback_reason_sha256"),
        "request_weight": BINANCE_USDM_COMMISSION_REQUEST_WEIGHT,
        "shared_budget_required": True,
        "shared_budget_scope": "host_redis",
        "refresh_policy_artifact_sha256": typed._refresh_policy.artifact_address.payload_sha256,
        "refresh_policy_receipt_sha256": typed._refresh_policy.receipt_sha256,
        "refresh_interval_seconds": typed._refresh_policy.refresh_interval_seconds,
        "immutable_maximum_safety_horizon_seconds": (
            IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS
        ),
        "expires_at": expires_iso,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }
    _origin(expected_request_identity["origin"])
    _sha256(
        expected_request_identity["fallback_reason_sha256"],
        reason="COMMISSION_CAPTURE_FALLBACK_REASON_SHA_INVALID",
    )
    if request_identity != expected_request_identity:
        _integrity("COMMISSION_CAPTURE_REQUEST_IDENTITY_BINDING_INVALID")
    request_identity_sha = _sha256_bytes(typed.sanitized_request_identity_bytes)
    if (
        typed.sanitized_request_identity_sha256 != request_identity_sha
        or typed.sanitized_request_identity_address.payload_sha256 != request_identity_sha
    ):
        _integrity("COMMISSION_CAPTURE_REQUEST_IDENTITY_SHA_INVALID")
    _sha256(
        typed.credential_binding_fingerprint_sha256,
        reason="COMMISSION_CAPTURE_CREDENTIAL_FINGERPRINT_INVALID",
    )

    artifact = _parse_exact_canonical_object(
        typed.fee_artifact_bytes,
        reason="COMMISSION_CAPTURE_FEE_ARTIFACT_INVALID",
    )
    expected_artifact = {
        "schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "capture_classification": BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION,
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": symbol,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS",
        "taker_fee_bps_per_side": taker_bps,
        "effective_at": available_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "source_key": f"v2:account:fee_schedule:{symbol}",
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "source_revision": typed.raw_response_sha256,
        "raw_response_sha256": typed.raw_response_sha256,
        "raw_response_byte_count": len(typed.raw_response_bytes),
        "raw_response_cas_address": _address_mapping(typed.raw_response_address),
        "sanitized_request_identity_sha256": request_identity_sha,
        "credential_binding_fingerprint_sha256": typed.credential_binding_fingerprint_sha256,
        "http_status": 200,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "response_observed_at": observed_iso,
        "rpi_commission_rate_decimal": response_payload["rpiCommissionRate"],
        "rpi_commission_bps": rpi_bps,
    }
    if artifact != expected_artifact:
        _integrity("COMMISSION_CAPTURE_FEE_ARTIFACT_BINDING_INVALID")

    receipt = _parse_exact_canonical_object(
        typed.fee_receipt_bytes,
        reason="COMMISSION_CAPTURE_FEE_RECEIPT_INVALID",
    )
    expected_receipt_without_hash = {
        "schema_version": CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": typed.fee_artifact_address.payload_sha256,
        "artifact_payload_byte_count": typed.fee_artifact_address.payload_byte_count,
        "source_key": f"v2:account:fee_schedule:{symbol}",
        "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": BINANCE_USDM_COMMISSION_SOURCE_TRANSPORT,
        "symbol": symbol,
        "effective_at": available_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "capture_classification": BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION,
        "raw_response_sha256": typed.raw_response_sha256,
        "raw_response_byte_count": len(typed.raw_response_bytes),
        "raw_response_cas_address": _address_mapping(typed.raw_response_address),
        "sanitized_request_identity_sha256": request_identity_sha,
        "credential_binding_fingerprint_sha256": typed.credential_binding_fingerprint_sha256,
        "http_status": 200,
        "request_method": BINANCE_USDM_COMMISSION_METHOD,
        "request_path": BINANCE_USDM_COMMISSION_ENDPOINT,
        "response_observed_at": observed_iso,
        "rpi_commission_rate_decimal": response_payload["rpiCommissionRate"],
        "rpi_commission_bps": rpi_bps,
    }
    expected_receipt_sha = _sha256_bytes(
        _canonical_bytes(
            expected_receipt_without_hash,
            reason="COMMISSION_CAPTURE_FEE_RECEIPT_INVALID",
        )
    )
    expected_receipt = {
        **expected_receipt_without_hash,
        "receipt_sha256": expected_receipt_sha,
    }
    if receipt != expected_receipt or typed.fee_receipt_sha256 != expected_receipt_sha:
        _integrity("COMMISSION_CAPTURE_FEE_RECEIPT_BINDING_INVALID")

    if (
        typed.request_weight != BINANCE_USDM_COMMISSION_REQUEST_WEIGHT
        or typed.shared_budget_required is not True
        or typed.read_only is not True
        or typed.trainer_authority is not False
        or typed.prediction_authority is not False
        or typed.paper_authority is not False
        or typed.live_authority is not False
    ):
        _integrity("COMMISSION_CAPTURE_FIXED_AUTHORITY_CONTRACT_INVALID")
    return {
        "schema_version": typed.schema_version,
        "classification": BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION,
        "downstream_status": BINANCE_USDM_COMMISSION_CAPTURE_DOWNSTREAM_STATUS,
        "symbol": symbol,
        "raw_response_sha256": typed.raw_response_sha256,
        "raw_response_byte_count": len(typed.raw_response_bytes),
        "raw_response_cas_address": _address_mapping(typed.raw_response_address),
        "sanitized_request_identity_sha256": request_identity_sha,
        "sanitized_request_identity_cas_address": _address_mapping(
            typed.sanitized_request_identity_address
        ),
        "credential_binding_fingerprint_sha256": (typed.credential_binding_fingerprint_sha256),
        "request_started_at": request_iso,
        "response_observed_at": observed_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "maker_commission_bps": maker_bps,
        "taker_commission_bps": taker_bps,
        "rpi_commission_bps": rpi_bps,
        "fee_artifact": artifact,
        "fee_artifact_cas_address": _address_mapping(typed.fee_artifact_address),
        "fee_schedule_receipt": receipt,
        "fee_receipt_cas_address": _address_mapping(typed.fee_receipt_address),
        "refresh_policy_artifact": policy_artifact,
        "refresh_policy_receipt": policy_receipt,
        "request_weight": typed.request_weight,
        "shared_budget_required": typed.shared_budget_required,
        "read_only": typed.read_only,
        "places_real_order": False,
        "order_submitted": False,
        "order_cancelled": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "trainer_authority": typed.trainer_authority,
        "prediction_authority": typed.prediction_authority,
        "paper_authority": typed.paper_authority,
        "live_authority": typed.live_authority,
    }


__all__ = [
    "BINANCE_USDM_COMMISSION_CAPTURE_CLASSIFICATION",
    "BINANCE_USDM_COMMISSION_CAPTURE_DOWNSTREAM_STATUS",
    "BINANCE_USDM_COMMISSION_CAPTURE_V1_SCHEMA_VERSION",
    "BINANCE_USDM_COMMISSION_ENDPOINT",
    "BINANCE_USDM_COMMISSION_METHOD",
    "BINANCE_USDM_COMMISSION_REFRESH_POLICY_V1_SCHEMA_VERSION",
    "BINANCE_USDM_COMMISSION_REFRESH_RECEIPT_V1_SCHEMA_VERSION",
    "BINANCE_USDM_COMMISSION_REQUEST_WEIGHT",
    "BINANCE_USDM_COMMISSION_SHARED_BUDGET_REQUIRED",
    "IMMUTABLE_MAX_COMMISSION_EVIDENCE_SAFETY_HORIZON_SECONDS",
    "BinanceUSDMCommissionCaptureTokenV1",
    "BinanceUSDMCommissionCaptureV1Error",
    "BinanceUSDMCommissionCaptureV1IntegrityError",
    "BinanceUSDMCommissionCaptureV1RateLimitError",
    "BinanceUSDMCommissionCaptureV1TransportError",
    "BinanceUSDMCommissionCaptureV1ValidationError",
    "BinanceUSDMCommissionRefreshPolicyTokenV1",
    "build_binance_usdm_commission_refresh_policy_v1",
    "capture_binance_usdm_commission_rate_v1",
]
