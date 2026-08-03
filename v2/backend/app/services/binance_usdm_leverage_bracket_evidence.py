"""Authenticated Binance USD-M leverage-bracket evidence for paper sizing.

``GET /fapi/v1/leverageBracket`` is a signed USER_DATA read.  It does not
change leverage, margin mode, or orders.  The response is account-specific,
so cached evidence is namespaced and authenticated for one exact safe
``trader_id`` / ``credential_ref`` / Binance environment binding.

The authentication key is deliberately separate from the Binance API secret.
Missing binding or authentication configuration fails closed.  Redis payloads
never contain either secret.  The SHA-256 field is only a content checksum;
HMAC-SHA256 is the authenticity control within this process/Redis trust model.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from v2.backend.app.services.binance_unified_websocket_transport import (
    resolve_binance_credential_binding,
)

SCHEMA_VERSION = "v2_binance_usdm_leverage_bracket_evidence_v3"
STATUS_SCHEMA_VERSION = "v2_binance_usdm_leverage_bracket_evidence_status_v3"
PRODUCER = "v2_binance_usdm_leverage_bracket_evidence"
SOURCE = "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET"
ENDPOINT = "/fapi/v1/leverageBracket"
SECURITY_TYPE = "USER_DATA"
TRANSPORT_CONTRACT = "BinanceUSDMAdapter.signed_get"
REST_FALLBACK_REASON = "SIGNED_USER_DATA_LEVERAGE_BRACKET_HAS_NO_SUPPORTED_WS_API_METHOD"
# The adapter owns the single shared-budget reservation immediately before its
# signed HTTP GET.  A second guard here would double-charge one exchange call.
# Keep the concrete owner visible to both operators and the repository's
# static REST-call audit.
REST_FALLBACK_BUDGET_GUARD_OWNER = (
    "BinanceUSDMAdapter.signed_get_contract:binance_rest_fallback_decision"
)

MAINNET_BASE_URL = "https://fapi.binance.com"
TESTNET_BASE_URL = "https://testnet.binancefuture.com"
ENVIRONMENT_BY_ORIGIN = {
    MAINNET_BASE_URL: "mainnet",
    TESTNET_BASE_URL: "testnet",
}

HMAC_KEY_ENV = "BINANCE_BRACKET_EVIDENCE_HMAC_KEY"
HMAC_KEY_ID_ENV = "BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID"
AUTH_ALGORITHM = "HMAC-SHA256"
MIN_HMAC_KEY_BYTES = 32

REDIS_KEY_PREFIX = "v2:binance_usdm:leverage_bracket:"
REDIS_STATUS_KEY_PREFIX = "v2:binance_usdm:leverage_bracket_status:"

DEFAULT_FRESHNESS_SECONDS = 600
DEFAULT_CACHE_TTL_SECONDS = 900

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_READ_ONLY_CREDENTIAL_REF_RE = re.compile(r"^[A-Z0-9]+_BINANCE(?:_[A-Z0-9]+)*_READONLY$")


class LeverageBracketEvidenceError(ValueError):
    """Raised when source, security, or cached evidence violates the contract."""


@dataclass(frozen=True)
class EvidenceSecurityContext:
    """Secret-safe binding plus a separate local evidence-authentication key."""

    trader_id: str
    credential_ref: str
    exchange_environment: str
    base_url_origin: str
    auth_key_id: str
    credential_account_specific: bool
    hmac_key: bytes = field(repr=False)

    @property
    def binding_id(self) -> str:
        return f"{self.exchange_environment}:{self.trader_id}:{self.credential_ref}"

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "trader_id": self.trader_id,
            "credential_ref": self.credential_ref,
            "exchange_environment": self.exchange_environment,
            "base_url_origin": self.base_url_origin,
            "credential_binding_id": self.binding_id,
            "credential_account_specific": self.credential_account_specific,
            "credential_ref_read_only_assertion": True,
            "credential_ref_read_only_assertion_semantics": (
                "OPERATOR_USAGE_LABEL_NOT_BINANCE_PERMISSION_PROOF"
            ),
            "exchange_key_permissions_proven_by_connector": False,
            "evidence_auth_algorithm": AUTH_ALGORITHM,
            "evidence_auth_key_id": self.auth_key_id,
            "evidence_auth_key_stored": False,
            "exchange_api_secret_used_for_evidence_auth": False,
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LeverageBracketEvidenceError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware_now(now_fn: Callable[[], datetime], *, field_name: str) -> datetime:
    try:
        value = now_fn()
    except Exception as exc:
        raise LeverageBracketEvidenceError(f"{field_name}_CLOCK_FAILED") from exc
    parsed = _parse_utc(value)
    if parsed is None:
        raise LeverageBracketEvidenceError(f"{field_name}_INVALID_OR_NAIVE")
    return parsed


def _safe_status_time(now_fn: Callable[[], datetime]) -> str | None:
    try:
        return _iso(_aware_now(now_fn, field_name="STATUS_TIME"))
    except LeverageBracketEvidenceError:
        return None


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value in (None, ""):
        raise LeverageBracketEvidenceError(f"{field}_MISSING_OR_BOOLEAN")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LeverageBracketEvidenceError(f"{field}_NOT_NUMERIC") from exc
    if not parsed.is_finite():
        raise LeverageBracketEvidenceError(f"{field}_NOT_FINITE")
    try:
        as_float = float(parsed)
    except (OverflowError, ValueError) as exc:
        raise LeverageBracketEvidenceError(f"{field}_NOT_JSON_NUMBER") from exc
    if not math.isfinite(as_float):
        raise LeverageBracketEvidenceError(f"{field}_NOT_JSON_NUMBER")
    return parsed


def _positive_int(value: Any, *, field: str) -> int:
    parsed = _decimal(value, field=field)
    integral = parsed.to_integral_value()
    if parsed != integral or integral <= 0:
        raise LeverageBracketEvidenceError(f"{field}_NOT_POSITIVE_INTEGER")
    return int(integral)


def _safe_identity(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise LeverageBracketEvidenceError(f"{field_name}_MISSING_OR_NOT_STRING")
    identity = value.strip()
    if identity != value or not _SAFE_ID_RE.fullmatch(identity):
        raise LeverageBracketEvidenceError(f"{field_name}_UNSAFE")
    return identity


def _credential_ref_is_explicitly_read_only(credential_ref: str) -> bool:
    """Accept the case-sensitive, structured read-only usage-label grammar."""

    return _READ_ONLY_CREDENTIAL_REF_RE.fullmatch(credential_ref) is not None


def _canonical_origin(base_url: Any) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise LeverageBracketEvidenceError("BINANCE_BASE_URL_MISSING")
    parsed = urlsplit(base_url.strip())
    try:
        port = parsed.port
    except ValueError as exc:
        raise LeverageBracketEvidenceError("BINANCE_BASE_URL_NOT_SAFE_ORIGIN") from exc
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.hostname is None
        or port not in {None, 443}
    ):
        raise LeverageBracketEvidenceError("BINANCE_BASE_URL_NOT_SAFE_ORIGIN")
    return f"https://{parsed.hostname.lower()}"


def exchange_environment_from_base_url(base_url: Any) -> str:
    origin = _canonical_origin(base_url)
    environment = ENVIRONMENT_BY_ORIGIN.get(origin)
    if environment is None:
        raise LeverageBracketEvidenceError("BINANCE_BASE_URL_ENVIRONMENT_UNRECOGNIZED")
    return environment


def build_evidence_security_context(
    *,
    trader_id: Any,
    credential_ref: Any,
    base_url: Any,
    credential_account_specific: bool,
    hmac_key: str | bytes | bytearray | None,
    auth_key_id: Any,
) -> EvidenceSecurityContext:
    """Build a validated context without storing or accepting exchange secrets."""

    safe_trader_id = _safe_identity(trader_id, field_name="TRADER_ID")
    safe_credential_ref = _safe_identity(credential_ref, field_name="CREDENTIAL_REF")
    safe_key_id = _safe_identity(auth_key_id, field_name="EVIDENCE_AUTH_KEY_ID")
    if credential_account_specific is not True:
        raise LeverageBracketEvidenceError("CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC")
    if not _credential_ref_is_explicitly_read_only(safe_credential_ref):
        raise LeverageBracketEvidenceError("CREDENTIAL_REF_NOT_EXPLICITLY_READ_ONLY")
    origin = _canonical_origin(base_url)
    environment = exchange_environment_from_base_url(origin)
    if isinstance(hmac_key, str):
        key_bytes = hmac_key.encode("utf-8")
    elif isinstance(hmac_key, bytes | bytearray):
        key_bytes = bytes(hmac_key)
    else:
        key_bytes = b""
    if len(key_bytes) < MIN_HMAC_KEY_BYTES:
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MISSING_OR_TOO_SHORT")
    return EvidenceSecurityContext(
        trader_id=safe_trader_id,
        credential_ref=safe_credential_ref,
        exchange_environment=environment,
        base_url_origin=origin,
        auth_key_id=safe_key_id,
        credential_account_specific=True,
        hmac_key=key_bytes,
    )


def evidence_security_context_from_env(
    *,
    trader_id: Any,
    credential_ref: Any,
    base_url: Any,
    credential_account_specific: bool,
    environ: Mapping[str, str] | None = None,
) -> EvidenceSecurityContext:
    values = os.environ if environ is None else environ
    return build_evidence_security_context(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        credential_account_specific=credential_account_specific,
        hmac_key=values.get(HMAC_KEY_ENV),
        auth_key_id=values.get(HMAC_KEY_ID_ENV),
    )


def evidence_security_context_for_adapter(
    adapter: Any,
    *,
    environ: Mapping[str, str] | None = None,
) -> EvidenceSecurityContext:
    """Bind evidence auth to the exact credentials and origin used by an adapter.

    This is the shared producer/consumer boundary.  It resolves the configured
    trader/credential reference, proves the adapter is using that same
    account-specific key pair, and requires a separate local evidence HMAC
    key.  Neither secret is returned in safe metadata or persisted evidence.
    """

    binding = resolve_binance_credential_binding()
    if not binding.is_configured:
        raise LeverageBracketEvidenceError(
            "ACCOUNT_SPECIFIC_BINANCE_CREDENTIAL_BINDING_NOT_CONFIGURED"
        )
    if binding.account_specific is not True:
        raise LeverageBracketEvidenceError("CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC")
    if getattr(binding, "read_only_ref", False) is not True:
        raise LeverageBracketEvidenceError("CREDENTIAL_REF_NOT_EXPLICITLY_READ_ONLY")
    adapter_api_key = getattr(adapter, "api_key", None)
    adapter_api_secret = getattr(adapter, "api_secret", None)
    if not (
        isinstance(adapter_api_key, str)
        and isinstance(adapter_api_secret, str)
        and hmac.compare_digest(adapter_api_key, binding.api_key)
        and hmac.compare_digest(adapter_api_secret, binding.api_secret)
    ):
        raise LeverageBracketEvidenceError("ADAPTER_CREDENTIAL_BINDING_MISMATCH")
    values = os.environ if environ is None else environ
    evidence_hmac_key = values.get(HMAC_KEY_ENV)
    if isinstance(evidence_hmac_key, str):
        evidence_key_bytes = evidence_hmac_key.encode("utf-8")
    elif isinstance(evidence_hmac_key, bytes | bytearray):
        evidence_key_bytes = bytes(evidence_hmac_key)
    else:
        evidence_key_bytes = b""
    if evidence_key_bytes:
        if hmac.compare_digest(evidence_key_bytes, binding.api_key.encode("utf-8")):
            raise LeverageBracketEvidenceError(
                "EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_API_KEY"
            )
        if hmac.compare_digest(evidence_key_bytes, binding.api_secret.encode("utf-8")):
            raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_SECRET")
    return evidence_security_context_from_env(
        trader_id=binding.trader_id,
        credential_ref=binding.credential_ref,
        base_url=getattr(adapter, "base_url", None),
        credential_account_specific=binding.account_specific,
        environ=values,
    )


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise LeverageBracketEvidenceError("SYMBOL_INVALID")
    return symbol


def _require_security_context(value: Any) -> EvidenceSecurityContext:
    if not isinstance(value, EvidenceSecurityContext):
        raise LeverageBracketEvidenceError("EVIDENCE_SECURITY_CONTEXT_REQUIRED")
    # Revalidate public fields in case an object was created without the builder.
    rebuilt = build_evidence_security_context(
        trader_id=value.trader_id,
        credential_ref=value.credential_ref,
        base_url=value.base_url_origin,
        credential_account_specific=value.credential_account_specific,
        hmac_key=value.hmac_key,
        auth_key_id=value.auth_key_id,
    )
    if rebuilt != value:
        raise LeverageBracketEvidenceError("EVIDENCE_SECURITY_CONTEXT_INVALID")
    return value


def redis_key(symbol: Any, *, security_context: EvidenceSecurityContext) -> str:
    context = _require_security_context(security_context)
    return (
        f"{REDIS_KEY_PREFIX}{context.exchange_environment}:"
        f"{context.trader_id}:{context.credential_ref}:{normalize_symbol(symbol)}"
    )


def redis_status_key(*, security_context: EvidenceSecurityContext) -> str:
    context = _require_security_context(security_context)
    return (
        f"{REDIS_STATUS_KEY_PREFIX}{context.exchange_environment}:"
        f"{context.trader_id}:{context.credential_ref}"
    )


def allowed_redis_key(key: str, *, security_context: EvidenceSecurityContext) -> bool:
    try:
        context = _require_security_context(security_context)
        if key == redis_status_key(security_context=context):
            return True
        prefix = (
            f"{REDIS_KEY_PREFIX}{context.exchange_environment}:"
            f"{context.trader_id}:{context.credential_ref}:"
        )
        if not key.startswith(prefix):
            return False
        return key == redis_key(key[len(prefix) :], security_context=context)
    except LeverageBracketEvidenceError:
        return False


def _canonical_brackets(raw_brackets: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_brackets, list) or not raw_brackets:
        raise LeverageBracketEvidenceError("BRACKETS_MISSING_OR_EMPTY")

    parsed_rows: list[tuple[Decimal, Decimal, Decimal, dict[str, Any]]] = []
    seen_bracket_ids: set[int] = set()
    for raw in raw_brackets:
        if not isinstance(raw, Mapping):
            raise LeverageBracketEvidenceError("BRACKET_ROW_NOT_OBJECT")
        bracket_id = _positive_int(raw.get("bracket"), field="bracket")
        initial_leverage = _positive_int(raw.get("initialLeverage"), field="initialLeverage")
        floor = _decimal(raw.get("notionalFloor"), field="notionalFloor")
        cap = _decimal(raw.get("notionalCap"), field="notionalCap")
        ratio = _decimal(raw.get("maintMarginRatio"), field="maintMarginRatio")
        cum = _decimal(raw.get("cum"), field="cum")
        if bracket_id in seen_bracket_ids:
            raise LeverageBracketEvidenceError("BRACKET_ID_DUPLICATE")
        if floor < 0 or cap <= floor:
            raise LeverageBracketEvidenceError("BRACKET_NOTIONAL_RANGE_INVALID")
        if ratio <= 0 or ratio >= 1:
            raise LeverageBracketEvidenceError("MAINT_MARGIN_RATIO_OUT_OF_RANGE")
        if cum < 0:
            raise LeverageBracketEvidenceError("CUM_NEGATIVE")
        seen_bracket_ids.add(bracket_id)
        parsed_rows.append(
            (
                floor,
                cap,
                ratio,
                {
                    "bracket": bracket_id,
                    "initialLeverage": initial_leverage,
                    "notionalFloor": float(floor),
                    "notionalCap": float(cap),
                    "maintMarginRatio": float(ratio),
                    "cum": float(cum),
                },
            )
        )

    parsed_rows.sort(key=lambda item: (item[0], item[3]["bracket"]))
    previous_cap: Decimal | None = None
    previous_leverage: int | None = None
    previous_ratio: Decimal | None = None
    previous_cum: Decimal | None = None
    for index, (floor, cap, ratio, row) in enumerate(parsed_rows, start=1):
        if row["bracket"] != index:
            raise LeverageBracketEvidenceError("BRACKET_SEQUENCE_NOT_CONTIGUOUS")
        if index == 1 and floor != 0:
            raise LeverageBracketEvidenceError("FIRST_BRACKET_FLOOR_NOT_ZERO")
        if previous_cap is not None and floor != previous_cap:
            raise LeverageBracketEvidenceError("BRACKET_RANGES_NOT_CONTIGUOUS")
        if previous_leverage is not None and row["initialLeverage"] > previous_leverage:
            raise LeverageBracketEvidenceError("INITIAL_LEVERAGE_INCREASES_WITH_NOTIONAL")
        if previous_ratio is not None and ratio < previous_ratio:
            raise LeverageBracketEvidenceError("MAINT_MARGIN_RATIO_DECREASES_WITH_NOTIONAL")
        # Binance's cumulative deduction makes maintenance continuous across
        # bracket boundaries.  Validate the reported recurrence before the
        # value can ever be used for exact accounting downstream.
        row_cum = _decimal(row["cum"], field="cum")
        if previous_ratio is None:
            if row_cum != 0:
                raise LeverageBracketEvidenceError("FIRST_BRACKET_CUM_NOT_ZERO")
        else:
            assert previous_cum is not None
            expected_cum = previous_cum + floor * (ratio - previous_ratio)
            if row_cum != expected_cum:
                raise LeverageBracketEvidenceError("BRACKET_CUM_RECURRENCE_INVALID")
        previous_cap = cap
        previous_leverage = row["initialLeverage"]
        previous_ratio = ratio
        previous_cum = row_cum
    return [row for _, _, _, row in parsed_rows]


def _canonical_bytes(payload: Mapping[str, Any], *, excluded_fields: frozenset[str]) -> bytes:
    fields = {str(key): value for key, value in payload.items() if str(key) not in excluded_fields}
    return json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_checksum(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            payload,
            excluded_fields=frozenset({"content_checksum_sha256", "evidence_hmac_sha256"}),
        )
    ).hexdigest()


def _evidence_hmac(payload: Mapping[str, Any], *, security_context: EvidenceSecurityContext) -> str:
    return hmac.new(
        security_context.hmac_key,
        _canonical_bytes(
            payload,
            excluded_fields=frozenset({"evidence_hmac_sha256"}),
        ),
        hashlib.sha256,
    ).hexdigest()


def _seal_payload(payload: dict[str, Any], *, security_context: EvidenceSecurityContext) -> None:
    payload["content_checksum_sha256"] = _content_checksum(payload)
    payload["evidence_hmac_sha256"] = _evidence_hmac(payload, security_context=security_context)


def build_symbol_evidence(
    source_row: Mapping[str, Any],
    *,
    security_context: EvidenceSecurityContext,
    fetched_at: datetime,
    fetch_started_at: datetime | None = None,
    generated_at: datetime | None = None,
    ingested_at: datetime | None = None,
    available_at: datetime | None = None,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """Validate one response row and build a sealed canonical cache value."""

    context = _require_security_context(security_context)
    if not isinstance(source_row, Mapping):
        raise LeverageBracketEvidenceError("SOURCE_ROW_NOT_OBJECT")
    freshness = _positive_int(freshness_seconds, field="freshness_seconds")
    cache_ttl = _positive_int(cache_ttl_seconds, field="cache_ttl_seconds")
    if cache_ttl < freshness:
        raise LeverageBracketEvidenceError("CACHE_TTL_SHORTER_THAN_FRESHNESS")

    fetched = _parse_utc(fetched_at)
    started = _parse_utc(fetch_started_at or fetched_at)
    generated = _parse_utc(generated_at or fetched_at)
    ingested = _parse_utc(ingested_at or generated_at or fetched_at)
    available = _parse_utc(available_at or ingested_at or generated_at or fetched_at)
    if None in (started, fetched, generated, ingested, available):
        raise LeverageBracketEvidenceError("PUBLICATION_TIMESTAMP_INVALID")
    assert started is not None
    assert fetched is not None
    assert generated is not None
    assert ingested is not None
    assert available is not None
    if not (started <= fetched <= generated <= ingested <= available):
        raise LeverageBracketEvidenceError("PUBLICATION_TIMESTAMP_ORDER_INVALID")

    symbol = normalize_symbol(source_row.get("symbol"))
    notional_coef: float | None = None
    if source_row.get("notionalCoef") not in (None, ""):
        coefficient = _decimal(source_row.get("notionalCoef"), field="notionalCoef")
        if coefficient <= 0:
            raise LeverageBracketEvidenceError("NOTIONAL_COEF_NOT_POSITIVE")
        notional_coef = float(coefficient)
    brackets = _canonical_brackets(source_row.get("brackets"))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "symbol": symbol,
        "source": SOURCE,
        "source_endpoint": ENDPOINT,
        "security_type": SECURITY_TYPE,
        "transport_contract": TRANSPORT_CONTRACT,
        **context.safe_metadata(),
        "account_scope": "EXACT_SAFE_TRADER_CREDENTIAL_REF_AND_ENVIRONMENT_BINDING",
        "source_event_time": None,
        "source_event_time_status": "UNAVAILABLE_ENDPOINT_RESPONSE_HAS_NO_EVENT_TIME",
        "fetch_started_at": _iso(started),
        "fetched_at": _iso(fetched),
        "generated_at": _iso(generated),
        "ingested_at": _iso(ingested),
        "available_at": _iso(available),
        "ingested_at_semantics": ("ADMITTED_TO_CONNECTOR_PUBLICATION_PIPELINE_BEFORE_REDIS_SET"),
        "available_at_semantics": (
            "PRODUCER_PUBLICATION_RELEASE_TIME_CAPTURED_AFTER_VALIDATION_"
            "IMMEDIATELY_BEFORE_FINAL_SEAL_AND_ATOMIC_REDIS_SET;"
            "NOT_A_REDIS_COMMIT_ACK;"
            "CONSUMER_OBSERVED_AT_REQUIRED_FOR_USE"
        ),
        "expires_at": _iso(available + timedelta(seconds=freshness)),
        "cache_expires_at": _iso(available + timedelta(seconds=cache_ttl)),
        "freshness_seconds": freshness,
        "cache_ttl_seconds": cache_ttl,
        "notionalCoef": notional_coef,
        "notional_coef_semantics": (
            "UPSTREAM_USER_SYMBOL_BRACKET_MULTIPLIER_METADATA;"
            "REPORTED_BRACKET_FLOOR_AND_CAP_ARE_NOT_RESCALED_BY_THIS_CONNECTOR"
        ),
        "brackets": brackets,
        "candidate_notional_contract": (
            "TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL"
        ),
        "authorization_scope": "PAPER_EVIDENCE_ONLY_NOT_TRADE_ADMISSION",
        "initialLeverage_semantics": (
            "EXCHANGE_REPORTED_BRACKET_CEILING_NOT_A_LEVERAGE_RECOMMENDATION"
        ),
        "maintenance_margin_formula": "MAX(0,NOTIONAL*maintMarginRatio-cum)",
        "freshness_state_at_publish": "CURRENT",
        "read_only": True,
        "raw_response_stored": False,
        "safe_binding_identifiers_stored": True,
        "credential_fields_stored": False,
        "credential_fields_stored_semantics": (
            "NO_EXCHANGE_API_KEY_SECRET_OR_SIGNED_REQUEST_FIELDS;"
            "SAFE_TRADER_AND_CREDENTIAL_REFERENCE_IDENTIFIERS_ARE_STORED"
        ),
        "exchange_api_key_stored": False,
        "exchange_api_secret_stored": False,
        "signed_request_fields_stored": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    _seal_payload(payload, security_context=context)
    return payload


def _safe_redis_set(
    redis_client: Any,
    key: str,
    payload: Mapping[str, Any],
    *,
    ttl_seconds: int,
    security_context: EvidenceSecurityContext,
) -> bool:
    if (
        redis_client is None
        or not allowed_redis_key(key, security_context=security_context)
        or ttl_seconds <= 0
    ):
        return False
    try:
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        redis_client.set(key, encoded, ex=int(ttl_seconds))
        return True
    except Exception:
        return False


def _finalize_publication_time(
    payload: dict[str, Any],
    *,
    available_at: datetime,
    security_context: EvidenceSecurityContext,
) -> None:
    """Apply the last producer timestamp after validation, then reseal."""

    available = _parse_utc(available_at)
    ingested = _parse_utc(payload.get("ingested_at"))
    if available is None or ingested is None or available < ingested:
        raise LeverageBracketEvidenceError("PUBLICATION_TIMESTAMP_ORDER_INVALID")
    freshness_seconds = _positive_int(payload.get("freshness_seconds"), field="freshness_seconds")
    cache_ttl_seconds = _positive_int(payload.get("cache_ttl_seconds"), field="cache_ttl_seconds")
    payload["available_at"] = _iso(available)
    payload["expires_at"] = _iso(available + timedelta(seconds=freshness_seconds))
    payload["cache_expires_at"] = _iso(available + timedelta(seconds=cache_ttl_seconds))
    _seal_payload(payload, security_context=security_context)


def _safe_adapter_status(value: Any) -> str:
    status = re.sub(r"[^A-Z0-9_:-]+", "_", str(value or "MISSING").upper())
    return status[:120]


def _status_base(
    *,
    security_context: EvidenceSecurityContext | None,
    symbols_requested: Sequence[str],
    freshness_seconds: int,
    cache_ttl_seconds: int,
) -> dict[str, Any]:
    try:
        safe_freshness_seconds: int | None = int(freshness_seconds)
    except (TypeError, ValueError, OverflowError):
        safe_freshness_seconds = None
    try:
        safe_cache_ttl_seconds: int | None = int(cache_ttl_seconds)
    except (TypeError, ValueError, OverflowError):
        safe_cache_ttl_seconds = None
    payload: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "producer": PRODUCER,
        "source": SOURCE,
        "source_endpoint": ENDPOINT,
        "security_type": SECURITY_TYPE,
        "transport_contract": TRANSPORT_CONTRACT,
        "symbols_requested": list(symbols_requested),
        "freshness_seconds": safe_freshness_seconds,
        "cache_ttl_seconds": safe_cache_ttl_seconds,
        "read_only": True,
        "raw_response_stored": False,
        "safe_binding_identifiers_stored": True,
        "credential_fields_stored": False,
        "credential_fields_stored_semantics": (
            "NO_EXCHANGE_API_KEY_SECRET_OR_SIGNED_REQUEST_FIELDS;"
            "SAFE_TRADER_AND_CREDENTIAL_REFERENCE_IDENTIFIERS_ARE_STORED"
        ),
        "exchange_api_key_stored": False,
        "exchange_api_secret_stored": False,
        "signed_request_fields_stored": False,
        "evidence_auth_key_stored": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if security_context is not None:
        payload.update(security_context.safe_metadata())
    return payload


def _publish_status(
    redis_client: Any,
    status: Mapping[str, Any],
    *,
    cache_ttl_seconds: int,
    security_context: EvidenceSecurityContext | None,
) -> None:
    if security_context is None:
        return
    _safe_redis_set(
        redis_client,
        redis_status_key(security_context=security_context),
        status,
        ttl_seconds=cache_ttl_seconds,
        security_context=security_context,
    )


def _blocked_status(
    *,
    reason: str,
    security_context: EvidenceSecurityContext | None,
    symbols_requested: Sequence[str],
    freshness_seconds: int,
    cache_ttl_seconds: int,
    now_fn: Callable[[], datetime],
) -> dict[str, Any]:
    status = _status_base(
        security_context=security_context,
        symbols_requested=symbols_requested,
        freshness_seconds=freshness_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    status.update(
        {
            "status": "BLOCKED",
            "reason": reason,
            "generated_at": _safe_status_time(now_fn),
            "symbols_received": [],
            "symbols_published": [],
        }
    )
    return status


def fetch_and_cache_leverage_brackets(
    *,
    adapter: Any,
    redis_client: Any,
    security_context: EvidenceSecurityContext | None,
    symbols: Iterable[Any] = (),
    execute: bool = True,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    now_fn: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Run one signed read and cache authenticated per-symbol evidence."""

    try:
        context = _require_security_context(security_context)
    except LeverageBracketEvidenceError as exc:
        return _blocked_status(
            reason=str(exc),
            security_context=None,
            symbols_requested=(),
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )

    try:
        normalized_freshness_seconds = _positive_int(
            freshness_seconds,
            field="freshness_seconds",
        )
        normalized_cache_ttl_seconds = _positive_int(
            cache_ttl_seconds,
            field="cache_ttl_seconds",
        )
    except LeverageBracketEvidenceError:
        return _blocked_status(
            reason="INVALID_FRESHNESS_OR_CACHE_TTL_CONTRACT",
            security_context=context,
            symbols_requested=(),
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
    if normalized_cache_ttl_seconds < normalized_freshness_seconds:
        return _blocked_status(
            reason="INVALID_FRESHNESS_OR_CACHE_TTL_CONTRACT",
            security_context=context,
            symbols_requested=(),
            freshness_seconds=normalized_freshness_seconds,
            cache_ttl_seconds=normalized_cache_ttl_seconds,
            now_fn=now_fn,
        )
    freshness_seconds = normalized_freshness_seconds
    cache_ttl_seconds = normalized_cache_ttl_seconds

    try:
        adapter_origin = _canonical_origin(getattr(adapter, "base_url", None))
        adapter_environment = exchange_environment_from_base_url(adapter_origin)
    except LeverageBracketEvidenceError as exc:
        status = _blocked_status(
            reason=str(exc),
            security_context=context,
            symbols_requested=(),
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=max(1, cache_ttl_seconds),
            security_context=context,
        )
        return status
    if (
        adapter_origin != context.base_url_origin
        or adapter_environment != context.exchange_environment
    ):
        status = _blocked_status(
            reason="ADAPTER_ENVIRONMENT_BINDING_MISMATCH",
            security_context=context,
            symbols_requested=(),
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=max(1, cache_ttl_seconds),
            security_context=context,
        )
        return status

    try:
        requested = tuple(sorted({normalize_symbol(item) for item in symbols}))
    except LeverageBracketEvidenceError:
        status = _blocked_status(
            reason="REQUESTED_SYMBOL_INVALID",
            security_context=context,
            symbols_requested=(),
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=max(1, cache_ttl_seconds),
            security_context=context,
        )
        return status

    if redis_client is None:
        return _blocked_status(
            reason="REDIS_UNAVAILABLE_NO_FETCH_ATTEMPTED",
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )

    try:
        fetch_started_at = _aware_now(now_fn, field_name="FETCH_STARTED_AT")
    except LeverageBracketEvidenceError as exc:
        return _blocked_status(
            reason=str(exc),
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
    params: dict[str, Any] = {"symbol": requested[0]} if len(requested) == 1 else {}
    try:
        result = adapter.signed_get(
            ENDPOINT,
            params or None,
            execute=bool(execute),
            fallback_reason=REST_FALLBACK_REASON,
        )
    except Exception as exc:
        status = _blocked_status(
            reason=f"ADAPTER_EXCEPTION_{type(exc).__name__.upper()}",
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=cache_ttl_seconds,
            security_context=context,
        )
        return status

    adapter_status = _safe_adapter_status(
        result.get("status") if isinstance(result, Mapping) else None
    )
    if not isinstance(result, Mapping) or adapter_status != "SIGNED_READ_EXECUTED":
        status = _blocked_status(
            reason=f"ADAPTER_STATUS_{adapter_status}",
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        status["adapter_status"] = adapter_status
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=cache_ttl_seconds,
            security_context=context,
        )
        return status

    http_status = result.get("http_status_code")
    if (
        isinstance(http_status, bool)
        or not isinstance(http_status, int)
        or not (200 <= http_status < 300)
    ):
        safe_http_status = http_status if isinstance(http_status, int) else "MISSING"
        status = _blocked_status(
            reason=f"HTTP_STATUS_{safe_http_status}",
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        status.update(
            {
                "adapter_status": adapter_status,
                "http_status_code": safe_http_status,
            }
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=cache_ttl_seconds,
            security_context=context,
        )
        return status

    try:
        fetched_at = _aware_now(now_fn, field_name="FETCHED_AT")
    except LeverageBracketEvidenceError as exc:
        status = _blocked_status(
            reason=str(exc),
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=cache_ttl_seconds,
            security_context=context,
        )
        return status
    if fetched_at < fetch_started_at:
        status = _blocked_status(
            reason="FETCH_CLOCK_REGRESSION",
            security_context=context,
            symbols_requested=requested,
            freshness_seconds=freshness_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            now_fn=now_fn,
        )
        _publish_status(
            redis_client,
            status,
            cache_ttl_seconds=cache_ttl_seconds,
            security_context=context,
        )
        return status

    response = result.get("response_json")
    if isinstance(response, Mapping):
        raw_rows = [response]
        response_variant = "OBJECT"
    elif isinstance(response, list):
        raw_rows = response
        response_variant = "ARRAY"
    else:
        raw_rows = []
        response_variant = "INVALID"

    received_symbols: list[str] = []
    rows_by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    invalid_row_count = 0
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            invalid_row_count += 1
            continue
        try:
            symbol = normalize_symbol(raw.get("symbol"))
        except LeverageBracketEvidenceError:
            invalid_row_count += 1
            continue
        received_symbols.append(symbol)
        rows_by_symbol.setdefault(symbol, []).append(raw)

    target_symbols = set(requested) if requested else set(rows_by_symbol)
    published_symbols: list[str] = []
    invalid_symbols: list[str] = []
    redis_write_failed_symbols: list[str] = []
    for symbol in sorted(target_symbols):
        candidates = rows_by_symbol.get(symbol, [])
        if len(candidates) != 1:
            invalid_symbols.append(symbol)
            continue
        try:
            generated_at = _aware_now(now_fn, field_name="GENERATED_AT")
            ingested_at = _aware_now(now_fn, field_name="INGESTED_AT")
            payload = build_symbol_evidence(
                candidates[0],
                security_context=context,
                fetch_started_at=fetch_started_at,
                fetched_at=fetched_at,
                generated_at=generated_at,
                ingested_at=ingested_at,
                available_at=ingested_at,
                freshness_seconds=freshness_seconds,
                cache_ttl_seconds=cache_ttl_seconds,
            )
            available_at = _aware_now(now_fn, field_name="AVAILABLE_AT")
            _finalize_publication_time(
                payload,
                available_at=available_at,
                security_context=context,
            )
        except LeverageBracketEvidenceError:
            invalid_symbols.append(symbol)
            continue
        if _safe_redis_set(
            redis_client,
            redis_key(symbol, security_context=context),
            payload,
            ttl_seconds=cache_ttl_seconds,
            security_context=context,
        ):
            published_symbols.append(symbol)
        else:
            redis_write_failed_symbols.append(symbol)

    missing_symbols = sorted(set(requested) - set(rows_by_symbol))
    clean_complete = bool(published_symbols) and not (
        invalid_row_count or invalid_symbols or missing_symbols or redis_write_failed_symbols
    )
    if requested:
        clean_complete = clean_complete and set(published_symbols) == set(requested)

    if clean_complete:
        overall = "READY"
        reason = "CURRENT_AUTHENTICATED_ACCOUNT_BRACKET_EVIDENCE_CACHED"
    elif published_symbols:
        overall = "PARTIAL"
        reason = "PARTIAL_EVIDENCE_CACHED_MISSING_OR_MALFORMED_SYMBOLS_FAIL_CLOSED"
    elif response_variant == "INVALID" or not raw_rows:
        overall = "MALFORMED"
        reason = "RESPONSE_NOT_NONEMPTY_OBJECT_OR_ARRAY"
    elif redis_write_failed_symbols:
        overall = "BLOCKED"
        reason = "REDIS_SYMBOL_EVIDENCE_WRITE_FAILED"
    else:
        overall = "MALFORMED"
        reason = "NO_VALID_REQUESTED_SYMBOL_EVIDENCE"

    status = _status_base(
        security_context=context,
        symbols_requested=requested,
        freshness_seconds=freshness_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    status.update(
        {
            "status": overall,
            "reason": reason,
            "adapter_status": adapter_status,
            "http_status_code": http_status,
            "response_variant": response_variant,
            "fetch_started_at": _iso(fetch_started_at),
            "fetched_at": _iso(fetched_at),
            "generated_at": _safe_status_time(now_fn),
            "symbols_received": sorted(set(received_symbols)),
            "symbols_published": published_symbols,
            "missing_symbols": missing_symbols,
            "invalid_symbols": sorted(set(invalid_symbols)),
            "invalid_row_count": invalid_row_count,
            "redis_write_failed_symbols": redis_write_failed_symbols,
        }
    )
    _publish_status(
        redis_client,
        status,
        cache_ttl_seconds=cache_ttl_seconds,
        security_context=context,
    )
    return status


def _validate_cached_evidence(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    security_context: EvidenceSecurityContext,
) -> None:
    context = _require_security_context(security_context)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LeverageBracketEvidenceError("SCHEMA_VERSION_INVALID")
    if payload.get("producer") != PRODUCER:
        raise LeverageBracketEvidenceError("PRODUCER_INVALID")
    if payload.get("source") != SOURCE or payload.get("source_endpoint") != ENDPOINT:
        raise LeverageBracketEvidenceError("SOURCE_INVALID")
    if payload.get("security_type") != SECURITY_TYPE:
        raise LeverageBracketEvidenceError("SECURITY_TYPE_INVALID")
    if payload.get("transport_contract") != TRANSPORT_CONTRACT:
        raise LeverageBracketEvidenceError("TRANSPORT_CONTRACT_INVALID")
    if normalize_symbol(payload.get("symbol")) != symbol:
        raise LeverageBracketEvidenceError("SYMBOL_MISMATCH")
    for field_name, expected in context.safe_metadata().items():
        if payload.get(field_name) != expected:
            raise LeverageBracketEvidenceError(f"SECURITY_BINDING_MISMATCH_{field_name.upper()}")
    if payload.get("account_scope") != ("EXACT_SAFE_TRADER_CREDENTIAL_REF_AND_ENVIRONMENT_BINDING"):
        raise LeverageBracketEvidenceError("ACCOUNT_SCOPE_INVALID")
    if payload.get("read_only") is not True:
        raise LeverageBracketEvidenceError("READ_ONLY_STAMP_MISSING")
    if payload.get("authorization_scope") != "PAPER_EVIDENCE_ONLY_NOT_TRADE_ADMISSION":
        raise LeverageBracketEvidenceError("AUTHORIZATION_SCOPE_INVALID")
    if payload.get("candidate_notional_contract") != (
        "TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL"
    ):
        raise LeverageBracketEvidenceError("CANDIDATE_NOTIONAL_CONTRACT_INVALID")
    if payload.get("maintenance_margin_formula") != ("MAX(0,NOTIONAL*maintMarginRatio-cum)"):
        raise LeverageBracketEvidenceError("MAINTENANCE_MARGIN_FORMULA_INVALID")
    if payload.get("raw_response_stored") is not False:
        raise LeverageBracketEvidenceError("RAW_RESPONSE_STORAGE_STAMP_INVALID")
    if payload.get("credential_fields_stored") is not False:
        raise LeverageBracketEvidenceError("CREDENTIAL_STORAGE_STAMP_INVALID")
    if payload.get("safe_binding_identifiers_stored") is not True:
        raise LeverageBracketEvidenceError("SAFE_BINDING_STORAGE_STAMP_INVALID")
    if payload.get("credential_fields_stored_semantics") != (
        "NO_EXCHANGE_API_KEY_SECRET_OR_SIGNED_REQUEST_FIELDS;"
        "SAFE_TRADER_AND_CREDENTIAL_REFERENCE_IDENTIFIERS_ARE_STORED"
    ):
        raise LeverageBracketEvidenceError("CREDENTIAL_STORAGE_SEMANTICS_INVALID")
    if any(
        payload.get(field_name) is not False
        for field_name in (
            "exchange_api_key_stored",
            "exchange_api_secret_stored",
            "signed_request_fields_stored",
        )
    ):
        raise LeverageBracketEvidenceError("EXCHANGE_CREDENTIAL_MATERIAL_STORAGE_STAMP_INVALID")
    if payload.get("evidence_auth_key_stored") is not False:
        raise LeverageBracketEvidenceError("EVIDENCE_AUTH_KEY_STORAGE_STAMP_INVALID")
    if payload.get("exchange_api_secret_used_for_evidence_auth") is not False:
        raise LeverageBracketEvidenceError("EXCHANGE_SECRET_AUTH_STAMP_INVALID")
    if any(
        payload.get(field_name) is not False
        for field_name in (
            "places_real_order",
            "order_submitted",
            "leverage_mutated",
            "margin_mutated",
        )
    ):
        raise LeverageBracketEvidenceError("MUTATION_STAMP_INVALID")

    checksum = payload.get("content_checksum_sha256")
    signature = payload.get("evidence_hmac_sha256")
    if (
        not isinstance(checksum, str)
        or not _HEX_SHA256_RE.fullmatch(checksum)
        or not hmac.compare_digest(checksum, _content_checksum(payload))
    ):
        raise LeverageBracketEvidenceError("CONTENT_CHECKSUM_MISMATCH")
    if (
        not isinstance(signature, str)
        or not _HEX_SHA256_RE.fullmatch(signature)
        or not hmac.compare_digest(signature, _evidence_hmac(payload, security_context=context))
    ):
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_MISMATCH")

    fetch_started_at = _parse_utc(payload.get("fetch_started_at"))
    fetched_at = _parse_utc(payload.get("fetched_at"))
    generated_at = _parse_utc(payload.get("generated_at"))
    ingested_at = _parse_utc(payload.get("ingested_at"))
    available_at = _parse_utc(payload.get("available_at"))
    expires_at = _parse_utc(payload.get("expires_at"))
    cache_expires_at = _parse_utc(payload.get("cache_expires_at"))
    if None in (
        fetch_started_at,
        fetched_at,
        generated_at,
        ingested_at,
        available_at,
        expires_at,
        cache_expires_at,
    ):
        raise LeverageBracketEvidenceError("TIMESTAMP_LINEAGE_INVALID")
    assert fetch_started_at is not None
    assert fetched_at is not None
    assert generated_at is not None
    assert ingested_at is not None
    assert available_at is not None
    assert expires_at is not None
    assert cache_expires_at is not None
    if not (
        fetch_started_at <= fetched_at <= generated_at <= ingested_at <= available_at < expires_at
    ):
        raise LeverageBracketEvidenceError("TIMESTAMP_ORDER_INVALID")
    if cache_expires_at < expires_at:
        raise LeverageBracketEvidenceError("CACHE_EXPIRES_BEFORE_EVIDENCE")
    if payload.get("available_at_semantics") != (
        "PRODUCER_PUBLICATION_RELEASE_TIME_CAPTURED_AFTER_VALIDATION_"
        "IMMEDIATELY_BEFORE_FINAL_SEAL_AND_ATOMIC_REDIS_SET;"
        "NOT_A_REDIS_COMMIT_ACK;"
        "CONSUMER_OBSERVED_AT_REQUIRED_FOR_USE"
    ):
        raise LeverageBracketEvidenceError("AVAILABLE_AT_SEMANTICS_INVALID")

    freshness = _positive_int(payload.get("freshness_seconds"), field="freshness_seconds")
    cache_ttl = _positive_int(payload.get("cache_ttl_seconds"), field="cache_ttl_seconds")
    if cache_ttl < freshness:
        raise LeverageBracketEvidenceError("CACHE_TTL_SHORTER_THAN_FRESHNESS")
    if abs((expires_at - available_at).total_seconds() - freshness) > 1e-6:
        raise LeverageBracketEvidenceError("FRESHNESS_EXPIRY_MISMATCH")
    if abs((cache_expires_at - available_at).total_seconds() - cache_ttl) > 1e-6:
        raise LeverageBracketEvidenceError("CACHE_EXPIRY_MISMATCH")

    if payload.get("notionalCoef") is not None:
        coefficient = _decimal(payload.get("notionalCoef"), field="notionalCoef")
        if coefficient <= 0:
            raise LeverageBracketEvidenceError("NOTIONAL_COEF_NOT_POSITIVE")
    canonical_brackets = _canonical_brackets(payload.get("brackets"))
    if canonical_brackets != payload.get("brackets"):
        raise LeverageBracketEvidenceError("BRACKETS_NOT_CANONICAL")


def _consumer_result(
    *,
    status: str,
    symbol: str | None,
    candidate_notional: float | None,
    key: str | None,
    security_context: EvidenceSecurityContext | None,
    decision_time: str | None = None,
    consumer_observed_at: str | None = None,
    current_checked_at: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "allowed": False,
        "evidence_usable": False,
        "allowed_semantics": "BRACKET_EVIDENCE_USABLE_ONLY_NOT_TRADE_ADMISSION",
        "paper_only": True,
        "symbol": symbol,
        "candidate_notional": candidate_notional,
        "candidate_notional_contract": (
            "TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL"
        ),
        "evidence_key": key,
        "decision_time": decision_time,
        "consumer_observed_at": consumer_observed_at,
        "current_checked_at": current_checked_at,
        "maintenance_margin_rate": None,
        "maintenance_margin_cum": None,
        "maintenance_margin_estimate_for_candidate_notional": None,
        "max_initial_leverage": None,
        "selected_bracket": None,
        "source": None,
        "available_at": None,
        "expires_at": None,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if security_context is not None:
        result.update(security_context.safe_metadata())
    return result


def select_paper_bracket_evidence(
    redis_client: Any,
    *,
    security_context: EvidenceSecurityContext | None,
    symbol: Any,
    candidate_notional: Any,
    decision_time: Any,
    now_fn: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Select current authenticated evidence for a prospective paper position.

    Temporal order is strict:
    ``available_at <= decision_time <= consumer_observed_at <= current_checked_at``.
    The evidence must remain unexpired at all three later timestamps.  A current
    Redis key is therefore not a historical replay store.
    """

    try:
        context = _require_security_context(security_context)
    except LeverageBracketEvidenceError:
        return _consumer_result(
            status="EVIDENCE_SECURITY_CONTEXT_INVALID",
            symbol=None,
            candidate_notional=None,
            key=None,
            security_context=None,
        )
    try:
        canonical_symbol = normalize_symbol(symbol)
        key = redis_key(canonical_symbol, security_context=context)
    except LeverageBracketEvidenceError:
        return _consumer_result(
            status="SYMBOL_INVALID",
            symbol=None,
            candidate_notional=None,
            key=None,
            security_context=context,
        )
    try:
        notional_decimal = _decimal(candidate_notional, field="candidate_notional")
    except LeverageBracketEvidenceError:
        return _consumer_result(
            status="CANDIDATE_NOTIONAL_INVALID",
            symbol=canonical_symbol,
            candidate_notional=None,
            key=key,
            security_context=context,
        )
    if notional_decimal <= 0:
        return _consumer_result(
            status="CANDIDATE_NOTIONAL_INVALID",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
        )
    decision = _parse_utc(decision_time)
    if decision is None:
        return _consumer_result(
            status="DECISION_TIME_INVALID_OR_NAIVE",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
        )
    if redis_client is None:
        return _consumer_result(
            status="LEVERAGE_BRACKET_EVIDENCE_MISSING",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
        )
    try:
        raw = redis_client.get(key)
    except Exception:
        raw = None
    try:
        consumer_observed = _aware_now(now_fn, field_name="CONSUMER_OBSERVED_AT")
    except LeverageBracketEvidenceError:
        return _consumer_result(
            status="CONSUMER_OBSERVED_AT_INVALID_OR_NAIVE",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
        )
    observed_iso = _iso(consumer_observed)
    if raw in (None, "", b""):
        return _consumer_result(
            status="LEVERAGE_BRACKET_EVIDENCE_MISSING",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
        )
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (UnicodeDecodeError, TypeError, ValueError):
        payload = None
    if not isinstance(payload, Mapping):
        return _consumer_result(
            status="LEVERAGE_BRACKET_EVIDENCE_MALFORMED",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
        )
    try:
        _validate_cached_evidence(
            payload,
            symbol=canonical_symbol,
            security_context=context,
        )
    except LeverageBracketEvidenceError as exc:
        result = _consumer_result(
            status="LEVERAGE_BRACKET_EVIDENCE_MALFORMED",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
        )
        result["validation_error_code"] = str(exc)
        return result
    try:
        current_checked = _aware_now(now_fn, field_name="CURRENT_CHECKED_AT")
    except LeverageBracketEvidenceError:
        return _consumer_result(
            status="CURRENT_CHECKED_AT_INVALID_OR_NAIVE",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
        )
    current_iso = _iso(current_checked)
    available_at = _parse_utc(payload.get("available_at"))
    expires_at = _parse_utc(payload.get("expires_at"))
    assert available_at is not None and expires_at is not None

    temporal_status: str | None = None
    if available_at > decision:
        temporal_status = "LEVERAGE_BRACKET_EVIDENCE_AVAILABLE_AFTER_DECISION_TIME"
    elif decision > consumer_observed:
        temporal_status = "DECISION_TIME_AFTER_CONSUMER_OBSERVED_AT"
    elif available_at > consumer_observed:
        temporal_status = "EVIDENCE_AVAILABLE_AFTER_CONSUMER_OBSERVED_AT"
    elif consumer_observed > current_checked:
        temporal_status = "CONSUMER_CLOCK_REGRESSION"
    elif decision >= expires_at:
        temporal_status = "LEVERAGE_BRACKET_EVIDENCE_STALE_AT_DECISION_TIME"
    elif consumer_observed >= expires_at or current_checked >= expires_at:
        temporal_status = "LEVERAGE_BRACKET_EVIDENCE_STALE_AT_CURRENT_TIME"
    if temporal_status is not None:
        result = _consumer_result(
            status=temporal_status,
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
            current_checked_at=current_iso,
        )
        result.update(
            {
                "source": payload.get("source"),
                "available_at": payload.get("available_at"),
                "expires_at": payload.get("expires_at"),
            }
        )
        return result

    selected: Mapping[str, Any] | None = None
    for bracket in payload.get("brackets", []):
        floor = _decimal(bracket.get("notionalFloor"), field="notionalFloor")
        cap = _decimal(bracket.get("notionalCap"), field="notionalCap")
        if floor <= notional_decimal < cap:
            selected = bracket
            break
    if selected is None:
        result = _consumer_result(
            status="CANDIDATE_NOTIONAL_OUTSIDE_REPORTED_BRACKETS",
            symbol=canonical_symbol,
            candidate_notional=float(notional_decimal),
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
            current_checked_at=current_iso,
        )
        result.update(
            {
                "source": payload.get("source"),
                "available_at": payload.get("available_at"),
                "expires_at": payload.get("expires_at"),
            }
        )
        return result

    rate = float(selected["maintMarginRatio"])
    cum = float(selected["cum"])
    notional = float(notional_decimal)
    return {
        **_consumer_result(
            status="READY",
            symbol=canonical_symbol,
            candidate_notional=notional,
            key=key,
            security_context=context,
            decision_time=_iso(decision),
            consumer_observed_at=observed_iso,
            current_checked_at=current_iso,
        ),
        "allowed": True,
        "evidence_usable": True,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_formula": "MAX(0,NOTIONAL*maintMarginRatio-cum)",
        "maintenance_margin_estimate_for_candidate_notional": max(0.0, notional * rate - cum),
        "max_initial_leverage": selected.get("initialLeverage"),
        "selected_bracket": selected.get("bracket"),
        "bracket_count": len(payload.get("brackets", [])),
        "notional_floor": selected.get("notionalFloor"),
        "notional_cap": selected.get("notionalCap"),
        "notional_coef": payload.get("notionalCoef"),
        "notional_coef_application": (
            "PRESERVED_AS_UPSTREAM_METADATA;REPORTED_FLOOR_AND_CAP_USED_DIRECTLY"
        ),
        "source": payload.get("source"),
        "source_endpoint": payload.get("source_endpoint"),
        "available_at": payload.get("available_at"),
        "expires_at": payload.get("expires_at"),
        "content_checksum_sha256": payload.get("content_checksum_sha256"),
        "evidence_hmac_sha256": payload.get("evidence_hmac_sha256"),
    }


__all__ = [
    "AUTH_ALGORITHM",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_FRESHNESS_SECONDS",
    "ENDPOINT",
    "ENVIRONMENT_BY_ORIGIN",
    "EvidenceSecurityContext",
    "HMAC_KEY_ENV",
    "HMAC_KEY_ID_ENV",
    "MAINNET_BASE_URL",
    "PRODUCER",
    "REDIS_KEY_PREFIX",
    "REDIS_STATUS_KEY_PREFIX",
    "REST_FALLBACK_BUDGET_GUARD_OWNER",
    "REST_FALLBACK_REASON",
    "SCHEMA_VERSION",
    "SOURCE",
    "STATUS_SCHEMA_VERSION",
    "TESTNET_BASE_URL",
    "LeverageBracketEvidenceError",
    "allowed_redis_key",
    "build_evidence_security_context",
    "build_symbol_evidence",
    "evidence_security_context_for_adapter",
    "evidence_security_context_from_env",
    "exchange_environment_from_base_url",
    "fetch_and_cache_leverage_brackets",
    "normalize_symbol",
    "redis_key",
    "redis_status_key",
    "select_paper_bracket_evidence",
]
