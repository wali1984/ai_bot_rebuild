"""Canonical, fail-closed paper market-price evidence.

This module is deliberately paper-only.  It reads no exchange, submits no
orders, and owns no leverage or margin decisions.  Its only job is to turn a
V2 Redis market-price observation into a self-verifying evidence envelope.

Freshness is derived from the requested timeframe.  There is no independent
wall-clock market staleness threshold: a ``1m`` request must bind an event (or
final candle close) no more than one requested interval before the lookup.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MARKET_PRICE_EVIDENCE_SCHEMA_VERSION = "V2_PAPER_MARKET_PRICE_EVIDENCE_V1"
MARKET_PRICE_EVIDENCE_SOURCE_TICKER = "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE"
MARKET_PRICE_EVIDENCE_SOURCE_FEATURE = "V2_FEATURES_LATEST_FRESH_CLOSE_PRICE"
MARKET_PRICE_EVIDENCE_MISSING = "MISSING_V2_MARKET_PRICE_FOR_FILL"

_TICKER_KIND = "TICKER_POINT_EVENT"
_FEATURE_KIND = "FINAL_CLOSED_CANDLE_FEATURE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMEFRAME_RE = re.compile(r"^([1-9][0-9]*)([mhd])$")


def utc_now_iso() -> str:
    """Return the consumer lookup clock in canonical UTC."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_or_none(value: Any) -> str | None:
    try:
        return _sha256(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _evidence_binding_material(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return all consumer-authoritative fields covered by the receipt hash."""

    return {
        field: evidence.get(field)
        for field in (
            "schema_version",
            "requested_redis_key",
            "requested_symbol",
            "requested_timeframe",
            "source_kind",
            "source_label",
            "selected_field",
            "price",
            "source_event_time",
            "candle_close_time",
            "available_at",
            "lookup_observed_at",
            "source_available_at_field",
            "freshness_basis",
            "freshness_interval_seconds",
            "source_hash_sha256",
            "source_payload_hash_sha256",
            "paper_only",
            "routes_to_live",
            "places_real_order",
        )
    }


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


def _timeframe_seconds(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    matched = _TIMEFRAME_RE.fullmatch(text)
    if matched is None:
        return None
    amount = int(matched.group(1))
    unit_seconds = {"m": 60, "h": 3_600, "d": 86_400}[matched.group(2)]
    return amount * unit_seconds


def _epoch_decimal(value: str) -> datetime | None:
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    # Current epoch milliseconds are much larger than current epoch seconds.
    seconds = number / Decimal(1_000) if number >= Decimal("100000000000") else number
    try:
        return datetime.fromtimestamp(float(seconds), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _strict_utc_datetime(value: Any) -> datetime | None:
    """Parse only unambiguous, UTC-aware clocks.

    Integer/decimal epoch clocks are intrinsically UTC.  ISO text must carry
    an explicit UTC offset and must resolve to UTC; naive timestamps and local
    offsets are rejected rather than silently normalized.
    """

    if value in (None, "") or isinstance(value, bool | float):
        return None
    if type(value) is int:
        return _epoch_decimal(str(value))
    if isinstance(value, Decimal):
        return _epoch_decimal(str(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    numeric = _epoch_decimal(text)
    if numeric is not None:
        return numeric
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    if parsed.utcoffset().total_seconds() != 0.0:
        return None
    return parsed.astimezone(UTC)


def _utc_iso(value: Any) -> str | None:
    parsed = _strict_utc_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _decode_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    return dict(raw) if isinstance(raw, Mapping) else None


def _base_evidence(
    *,
    source_kind: str,
    source_label: str,
    requested_key: str,
    requested_symbol: str,
    requested_timeframe: str,
    payload: Mapping[str, Any],
    selected_field: str,
    selected_value: Any,
    source_event_time: Any,
    source_available_at: Any,
    source_available_at_field: str,
    lookup_observed_at: Any,
    source_material_extra: Mapping[str, Any],
) -> dict[str, Any]:
    event_iso = _utc_iso(source_event_time)
    available_iso = _utc_iso(source_available_at)
    observed_iso = _utc_iso(lookup_observed_at)
    price = _finite_positive(selected_value)
    source_material = {
        "requested_redis_key": requested_key,
        "requested_symbol": requested_symbol,
        "requested_timeframe": requested_timeframe,
        "source_kind": source_kind,
        "selected_field": selected_field,
        "selected_value": price,
        "source_event_time": event_iso,
        "source_available_at": available_iso,
        "source_available_at_field": source_available_at_field,
        **dict(source_material_extra),
    }
    evidence = {
        "schema_version": MARKET_PRICE_EVIDENCE_SCHEMA_VERSION,
        # Validation below recomputes every binding; this provisional value is
        # replaced with REJECTED when any check fails.
        "evidence_status": "VALID",
        "rejection_reasons": [],
        "requested_redis_key": requested_key,
        "requested_symbol": requested_symbol,
        "requested_timeframe": requested_timeframe,
        "source_kind": source_kind,
        "source_label": source_label,
        "selected_field": selected_field,
        "price": price,
        "source_event_time": event_iso,
        "candle_close_time": event_iso if source_kind == _FEATURE_KIND else None,
        "available_at": available_iso,
        "lookup_observed_at": observed_iso,
        "source_available_at_field": source_available_at_field,
        "freshness_basis": "REQUESTED_TIMEFRAME_PIT_WINDOW",
        "freshness_interval_seconds": _timeframe_seconds(requested_timeframe),
        "source_material": source_material,
        "source_hash_sha256": _sha256_or_none(source_material),
        "source_payload_hash_sha256": _sha256_or_none(payload),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    evidence["evidence_hash_sha256"] = _sha256(_evidence_binding_material(evidence))
    verification = verify_market_price_evidence(
        evidence,
        expected_symbol=requested_symbol,
        expected_timeframe=requested_timeframe,
    )
    evidence["evidence_status"] = "VALID" if verification["valid"] else "REJECTED"
    evidence["rejection_reasons"] = verification["reasons"]
    return evidence


def build_ticker_price_evidence(
    *,
    payload: Mapping[str, Any],
    requested_key: str,
    requested_symbol: str,
    requested_timeframe: str,
    lookup_observed_at: Any,
) -> dict[str, Any]:
    ticker = payload.get("ticker_24hr")
    ticker = dict(ticker) if isinstance(ticker, Mapping) else {}
    available_field = (
        "available_at" if payload.get("available_at") not in (None, "") else "fetched_utc"
    )
    available_value = payload.get(available_field)
    return _base_evidence(
        source_kind=_TICKER_KIND,
        source_label=MARKET_PRICE_EVIDENCE_SOURCE_TICKER,
        requested_key=requested_key,
        requested_symbol=requested_symbol,
        requested_timeframe=requested_timeframe,
        payload=payload,
        selected_field="ticker_24hr.lastPrice",
        selected_value=ticker.get("lastPrice"),
        source_event_time=ticker.get("closeTime"),
        source_available_at=available_value,
        source_available_at_field=available_field,
        lookup_observed_at=lookup_observed_at,
        source_material_extra={
            "payload_symbol": payload.get("symbol"),
            "nested_symbol": ticker.get("symbol"),
            "payload_timeframe": payload.get("timeframe"),
            "nested_timeframe": ticker.get("timeframe"),
            "available_at_alias": _utc_iso(payload.get("available_at")),
            "fetched_utc_alias": _utc_iso(payload.get("fetched_utc")),
            "finality_state": "POINT_EVENT_OBSERVED_BEFORE_LOOKUP",
        },
    )


def build_feature_price_evidence(
    *,
    payload: Mapping[str, Any],
    requested_key: str,
    requested_symbol: str,
    requested_timeframe: str,
    lookup_observed_at: Any,
) -> dict[str, Any]:
    features = payload.get("features")
    features = dict(features) if isinstance(features, Mapping) else {}
    selected_field = "features.close_price"
    selected_value = features.get("close_price")
    if selected_value in (None, ""):
        selected_field = "features.last_price"
        selected_value = features.get("last_price")
    if selected_value in (None, ""):
        selected_field = "features.lastPrice"
        selected_value = features.get("lastPrice")
    return _base_evidence(
        source_kind=_FEATURE_KIND,
        source_label=MARKET_PRICE_EVIDENCE_SOURCE_FEATURE,
        requested_key=requested_key,
        requested_symbol=requested_symbol,
        requested_timeframe=requested_timeframe,
        payload=payload,
        selected_field=selected_field,
        selected_value=selected_value,
        source_event_time=payload.get("candle_close_time"),
        source_available_at=payload.get("available_at"),
        source_available_at_field="available_at",
        lookup_observed_at=lookup_observed_at,
        source_material_extra={
            "payload_symbol": payload.get("symbol"),
            "nested_symbol": None,
            "payload_timeframe": payload.get("timeframe"),
            "nested_timeframe": None,
            "feature_cutoff": _utc_iso(payload.get("feature_cutoff")),
            "feature_freshness_state": payload.get("feature_freshness_state"),
            "candle_closed_confirmed": payload.get("candle_closed_confirmed"),
            "latest_candle_temporally_valid": payload.get("latest_candle_temporally_valid"),
            "finality_state": "FINAL_CLOSED_CANDLE",
        },
    )


def verify_market_price_evidence(
    evidence: Any,
    *,
    expected_symbol: str | None = None,
    expected_timeframe: str | None = None,
) -> dict[str, Any]:
    """Recompute every binding needed before a paper fill or lifecycle mark."""

    if not isinstance(evidence, Mapping):
        return {"valid": False, "reasons": ["MARKET_PRICE_EVIDENCE_REQUIRED"]}
    reasons: list[str] = []
    if evidence.get("schema_version") != MARKET_PRICE_EVIDENCE_SCHEMA_VERSION:
        reasons.append("MARKET_PRICE_EVIDENCE_SCHEMA_INVALID")
    if evidence.get("evidence_status") != "VALID":
        reasons.append("MARKET_PRICE_EVIDENCE_STATUS_NOT_VALID")

    symbol = str(evidence.get("requested_symbol") or "").upper()
    timeframe = str(evidence.get("requested_timeframe") or "").lower()
    if not symbol:
        reasons.append("REQUESTED_SYMBOL_MISSING")
    if expected_symbol is not None and symbol != str(expected_symbol).upper():
        reasons.append("REQUESTED_SYMBOL_BINDING_MISMATCH")
    if _timeframe_seconds(timeframe) is None:
        reasons.append("REQUESTED_TIMEFRAME_INVALID")
    if expected_timeframe is not None and timeframe != str(expected_timeframe).lower():
        reasons.append("REQUESTED_TIMEFRAME_BINDING_MISMATCH")

    source_kind = str(evidence.get("source_kind") or "")
    expected_key = None
    expected_field = None
    expected_label = None
    if source_kind == _TICKER_KIND:
        expected_key = f"v2:market:prices:{symbol}"
        expected_field = "ticker_24hr.lastPrice"
        expected_label = MARKET_PRICE_EVIDENCE_SOURCE_TICKER
    elif source_kind == _FEATURE_KIND:
        expected_key = f"v2:features:latest:{symbol}:{timeframe}"
        expected_label = MARKET_PRICE_EVIDENCE_SOURCE_FEATURE
    else:
        reasons.append("MARKET_PRICE_SOURCE_KIND_INVALID")
    if expected_key is not None and evidence.get("requested_redis_key") != expected_key:
        reasons.append("REQUESTED_REDIS_KEY_BINDING_MISMATCH")
    if expected_label is not None and evidence.get("source_label") != expected_label:
        reasons.append("MARKET_PRICE_SOURCE_LABEL_MISMATCH")
    selected_field = str(evidence.get("selected_field") or "")
    if source_kind == _TICKER_KIND and selected_field != expected_field:
        reasons.append("TICKER_SELECTED_FIELD_INVALID")
    if source_kind == _FEATURE_KIND and selected_field not in {
        "features.close_price",
        "features.last_price",
        "features.lastPrice",
    }:
        reasons.append("FEATURE_SELECTED_FIELD_INVALID")

    material = evidence.get("source_material")
    if not isinstance(material, Mapping):
        reasons.append("SOURCE_MATERIAL_REQUIRED")
        material = {}
    source_hash = str(evidence.get("source_hash_sha256") or "")
    if not _SHA256_RE.fullmatch(source_hash):
        reasons.append("SOURCE_HASH_INVALID")
    else:
        try:
            recomputed_hash = _sha256(material)
        except (TypeError, ValueError):
            recomputed_hash = None
        if recomputed_hash != source_hash:
            reasons.append("SOURCE_HASH_MISMATCH")
    if not _SHA256_RE.fullmatch(str(evidence.get("source_payload_hash_sha256") or "")):
        reasons.append("SOURCE_PAYLOAD_HASH_INVALID")
    evidence_hash = str(evidence.get("evidence_hash_sha256") or "")
    if not _SHA256_RE.fullmatch(evidence_hash):
        reasons.append("MARKET_PRICE_EVIDENCE_HASH_INVALID")
    else:
        try:
            recomputed_evidence_hash = _sha256(_evidence_binding_material(evidence))
        except (TypeError, ValueError):
            recomputed_evidence_hash = None
        if recomputed_evidence_hash != evidence_hash:
            reasons.append("MARKET_PRICE_EVIDENCE_HASH_MISMATCH")

    for field in (
        "requested_redis_key",
        "requested_symbol",
        "requested_timeframe",
        "source_kind",
        "selected_field",
    ):
        if material.get(field) != evidence.get(field):
            reasons.append(f"SOURCE_MATERIAL_{field.upper()}_MISMATCH")

    price = _finite_positive(evidence.get("price"))
    material_price = _finite_positive(material.get("selected_value"))
    if price is None:
        reasons.append("MARKET_PRICE_MISSING_OR_INVALID")
    if material_price is None or price != material_price:
        reasons.append("SELECTED_PRICE_BINDING_MISMATCH")

    payload_symbol = str(material.get("payload_symbol") or "").upper()
    nested_symbol = str(material.get("nested_symbol") or "").upper()
    if payload_symbol != symbol:
        reasons.append("SOURCE_PAYLOAD_SYMBOL_BINDING_MISMATCH")
    if nested_symbol and nested_symbol != symbol:
        reasons.append("SOURCE_NESTED_SYMBOL_BINDING_MISMATCH")
    for field in ("payload_timeframe", "nested_timeframe"):
        value = material.get(field)
        if value not in (None, "") and str(value).lower() != timeframe:
            reasons.append(f"SOURCE_{field.upper()}_BINDING_MISMATCH")

    event_time = _strict_utc_datetime(evidence.get("source_event_time"))
    available_at = _strict_utc_datetime(evidence.get("available_at"))
    observed_at = _strict_utc_datetime(evidence.get("lookup_observed_at"))
    if event_time is None:
        reasons.append("SOURCE_EVENT_TIME_MISSING_OR_NOT_STRICT_UTC")
    if available_at is None:
        reasons.append("SOURCE_AVAILABLE_AT_MISSING_OR_NOT_STRICT_UTC")
    if observed_at is None:
        reasons.append("LOOKUP_OBSERVED_AT_MISSING_OR_NOT_STRICT_UTC")
    if evidence.get("source_event_time") != material.get("source_event_time"):
        reasons.append("SOURCE_EVENT_TIME_BINDING_MISMATCH")
    if evidence.get("available_at") != material.get("source_available_at"):
        reasons.append("SOURCE_AVAILABLE_AT_BINDING_MISMATCH")
    if evidence.get("source_available_at_field") != material.get("source_available_at_field"):
        reasons.append("SOURCE_AVAILABLE_AT_FIELD_BINDING_MISMATCH")
    if event_time is not None and available_at is not None and event_time > available_at:
        reasons.append("SOURCE_EVENT_TIME_AFTER_AVAILABLE_AT")
    if available_at is not None and observed_at is not None and available_at > observed_at:
        reasons.append("SOURCE_AVAILABLE_AT_AFTER_LOOKUP_OBSERVED_AT")

    interval_seconds = _timeframe_seconds(timeframe)
    if evidence.get("freshness_interval_seconds") != interval_seconds:
        reasons.append("FRESHNESS_INTERVAL_NOT_DERIVED_FROM_REQUESTED_TIMEFRAME")
    if evidence.get("freshness_basis") != "REQUESTED_TIMEFRAME_PIT_WINDOW":
        reasons.append("FRESHNESS_BASIS_INVALID")
    if event_time is not None and observed_at is not None and interval_seconds is not None:
        if (observed_at - event_time).total_seconds() > interval_seconds:
            reasons.append("SOURCE_EVENT_STALE_FOR_REQUESTED_TIMEFRAME")

    if source_kind == _FEATURE_KIND:
        if evidence.get("candle_close_time") != evidence.get("source_event_time"):
            reasons.append("FINAL_CANDLE_CLOSE_BINDING_MISMATCH")
        if material.get("feature_cutoff") != evidence.get("candle_close_time"):
            reasons.append("FEATURE_CUTOFF_NOT_BOUND_TO_FINAL_CANDLE_CLOSE")
        if material.get("candle_closed_confirmed") is not True:
            reasons.append("FEATURE_CANDLE_NOT_CONFIRMED_FINAL")
        if material.get("latest_candle_temporally_valid") is not True:
            reasons.append("FEATURE_LATEST_CANDLE_NOT_TEMPORALLY_VALID")
        if str(material.get("feature_freshness_state") or "").upper() != "CURRENT":
            reasons.append("FEATURE_FRESHNESS_NOT_CURRENT")
        if material.get("finality_state") != "FINAL_CLOSED_CANDLE":
            reasons.append("FEATURE_FINALITY_STATE_INVALID")
    elif source_kind == _TICKER_KIND:
        if evidence.get("candle_close_time") is not None:
            reasons.append("TICKER_EVENT_MUST_NOT_MASQUERADE_AS_CANDLE_CLOSE")
        if material.get("finality_state") != "POINT_EVENT_OBSERVED_BEFORE_LOOKUP":
            reasons.append("TICKER_EVENT_FINALITY_STATE_INVALID")
        available_alias = material.get("available_at_alias")
        fetched_alias = material.get("fetched_utc_alias")
        if available_alias and fetched_alias and available_alias != fetched_alias:
            reasons.append("TICKER_AVAILABILITY_CLOCK_ALIASES_DISAGREE")

    if evidence.get("paper_only") is not True:
        reasons.append("MARKET_PRICE_EVIDENCE_NOT_PAPER_ONLY")
    if evidence.get("routes_to_live") is not False:
        reasons.append("MARKET_PRICE_EVIDENCE_ROUTES_TO_LIVE")
    if evidence.get("places_real_order") is not False:
        reasons.append("MARKET_PRICE_EVIDENCE_PLACES_REAL_ORDER")
    return {"valid": not reasons, "reasons": sorted(set(reasons)), "price": price}


def _attempt_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "requested_redis_key": evidence.get("requested_redis_key"),
        "source_kind": evidence.get("source_kind"),
        "source_hash_sha256": evidence.get("source_hash_sha256"),
        "source_payload_hash_sha256": evidence.get("source_payload_hash_sha256"),
        "rejection_reasons": list(evidence.get("rejection_reasons") or []),
    }


def read_market_price_evidence(
    redis_client: Any,
    symbol: str,
    *,
    timeframe: str = "1m",
    clock: Callable[[], Any] = utc_now_iso,
) -> dict[str, Any]:
    """Read ticker then feature evidence, capturing lookup time after each get."""

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_timeframe = str(timeframe or "").strip().lower()
    attempts: list[dict[str, Any]] = []
    aggregate_reasons: list[str] = []
    if redis_client is None:
        aggregate_reasons.append("REDIS_CLIENT_MISSING")
    if not normalized_symbol:
        aggregate_reasons.append("REQUESTED_SYMBOL_MISSING")
    if _timeframe_seconds(normalized_timeframe) is None:
        aggregate_reasons.append("REQUESTED_TIMEFRAME_INVALID")

    if not aggregate_reasons:
        ticker_key = f"v2:market:prices:{normalized_symbol}"
        try:
            ticker_raw = redis_client.get(ticker_key)
            ticker_observed_at = clock()
        except Exception as exc:  # noqa: BLE001 - Redis failure is evidence, not a crash
            ticker_raw = None
            ticker_observed_at = clock()
            aggregate_reasons.append(f"TICKER_REDIS_READ_ERROR:{type(exc).__name__}")
        ticker_payload = _decode_payload(ticker_raw)
        if ticker_payload is not None:
            ticker_evidence = build_ticker_price_evidence(
                payload=ticker_payload,
                requested_key=ticker_key,
                requested_symbol=normalized_symbol,
                requested_timeframe=normalized_timeframe,
                lookup_observed_at=ticker_observed_at,
            )
            if ticker_evidence.get("evidence_status") == "VALID":
                ticker_evidence["source_attempt_count"] = 1
                return ticker_evidence
            attempts.append(_attempt_summary(ticker_evidence))
            aggregate_reasons.extend(ticker_evidence.get("rejection_reasons") or [])
        elif ticker_raw not in (None, "", b""):
            aggregate_reasons.append("TICKER_PAYLOAD_INVALID_JSON_OR_SHAPE")
        else:
            aggregate_reasons.append("TICKER_PAYLOAD_MISSING")

        feature_key = f"v2:features:latest:{normalized_symbol}:{normalized_timeframe}"
        try:
            feature_raw = redis_client.get(feature_key)
            feature_observed_at = clock()
        except Exception as exc:  # noqa: BLE001 - Redis failure is evidence, not a crash
            feature_raw = None
            feature_observed_at = clock()
            aggregate_reasons.append(f"FEATURE_REDIS_READ_ERROR:{type(exc).__name__}")
        feature_payload = _decode_payload(feature_raw)
        if feature_payload is not None:
            feature_evidence = build_feature_price_evidence(
                payload=feature_payload,
                requested_key=feature_key,
                requested_symbol=normalized_symbol,
                requested_timeframe=normalized_timeframe,
                lookup_observed_at=feature_observed_at,
            )
            if feature_evidence.get("evidence_status") == "VALID":
                feature_evidence["source_attempt_count"] = 2
                feature_evidence["rejected_prior_sources"] = attempts
                return feature_evidence
            attempts.append(_attempt_summary(feature_evidence))
            aggregate_reasons.extend(feature_evidence.get("rejection_reasons") or [])
        elif feature_raw not in (None, "", b""):
            aggregate_reasons.append("FEATURE_PAYLOAD_INVALID_JSON_OR_SHAPE")
        else:
            aggregate_reasons.append("FEATURE_PAYLOAD_MISSING")

    return {
        "schema_version": MARKET_PRICE_EVIDENCE_SCHEMA_VERSION,
        "evidence_status": "REJECTED",
        "rejection_reasons": sorted(set(aggregate_reasons or [MARKET_PRICE_EVIDENCE_MISSING])),
        "requested_symbol": normalized_symbol,
        "requested_timeframe": normalized_timeframe,
        "source_attempt_count": len(attempts),
        "source_attempts": attempts,
        "price": None,
        "source_label": MARKET_PRICE_EVIDENCE_MISSING,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def verified_market_price_tuple(
    evidence: Any,
    *,
    expected_symbol: str | None = None,
    expected_timeframe: str | None = None,
) -> tuple[float | None, str, str | None]:
    verification = verify_market_price_evidence(
        evidence,
        expected_symbol=expected_symbol,
        expected_timeframe=expected_timeframe,
    )
    if verification["valid"] is not True:
        return None, MARKET_PRICE_EVIDENCE_MISSING, None
    assert isinstance(evidence, Mapping)
    return (
        verification["price"],
        str(evidence.get("source_label") or MARKET_PRICE_EVIDENCE_MISSING),
        str(evidence.get("available_at")) if evidence.get("available_at") else None,
    )
