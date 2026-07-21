from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import isclose, isfinite
from typing import Any

try:
    from v2.backend.app.services.market_state_integrity.trust import (
        ENFORCEMENT_EPOCH,
        TRUST_PRODUCER_VERSION,
        TRUST_SCHEMA_VERSION,
    )
except ModuleNotFoundError:  # pragma: no cover - supports app.* test imports
    from app.services.market_state_integrity.trust import (
        ENFORCEMENT_EPOCH,
        TRUST_PRODUCER_VERSION,
        TRUST_SCHEMA_VERSION,
    )


SCHEMA_VERSION = "v2_coinapi_wsds_compat_status_v3"
PROVIDER_IDENTITY_SCHEMA_VERSION = "v2_coinapi_provider_identity_v1"
V2_QUARANTINE_KEY_TEMPLATE = "v2:quarantine:coinapi:wsds:raw:v4:{coinapi_symbol_id}:{symbol}"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m")
APPROVED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})
RUNTIME_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
COINAPI_SYMBOL_ID_RE = re.compile(
    r"^(?P<exchange_id>[A-Z0-9]+)_(?P<market_type>PERP|SPOT)_" r"(?P<base_asset>[A-Z0-9]+)_USDT$"
)
OPTIONAL_SOURCE_FIELDS = {
    "optional_enrichment": True,
    "required_for_trainer_admission": False,
    "system_availability_blocking": False,
    "absence_blocks_trainer": False,
}
WSDS_RAW_TRUST_BLOCK_REASONS = (
    "RAW_PROVIDER_QUARANTINE",
    "MISSING_CANONICAL_POSTCOMMIT_RECEIPT",
    "STREAM_CADENCE_NOT_ATTESTED_BY_RECORD",
)
WSDS_RAW_QUARANTINE_FIELDS = frozenset(
    {
        "schema_version",
        "provider_identity_schema_version",
        "trust_schema_version",
        "enforcement_epoch",
        "producer",
        "producer_version",
        "symbol",
        "coinapi_symbol_id",
        "coinapi_exchange_id",
        "coinapi_market_type",
        "source",
        "quarantine_only",
        "canonical_receipt_resolver_present",
        "updated_ts_ms",
        "source_event_time",
        "source_event_ts_ms",
        "source_event_ts_ns",
        "provider_received_time",
        "observed_at",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "best_bid_px",
        "best_ask_px",
        "best_bid_sz",
        "best_ask_sz",
        "mid_px",
        "spread_bps",
        "microprice",
        "book_bid_sum_5",
        "book_ask_sum_5",
        "imbalance_5",
        "postcommit_receipt_present",
        "feature_eligible",
        "trainer_consumable",
        "prediction_eligible",
        "trust_block_reasons",
        "live_gate",
        "live_symbols",
        *OPTIONAL_SOURCE_FIELDS,
    }
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PROVIDER_TIMESTAMP_RE = re.compile(
    r"^(?P<second>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def build_coinapi_wsds_status(
    *,
    credential_env_present: bool = False,
    operator_paid_streaming_approved: bool = False,
) -> dict[str, Any]:
    client_constructed = bool(credential_env_present and operator_paid_streaming_approved)
    blockers = []
    if not credential_env_present:
        blockers.append("coinapi_api_key_not_present_by_env_name")
    if not operator_paid_streaming_approved:
        blockers.append("coinapi_wsds_paid_streaming_not_operator_approved")
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": "V2_COINAPI_WSDS_OPERATOR_READY"
        if client_constructed
        else "V2_COINAPI_WSDS_OPERATOR_GATED",
        "source": "v2.backend.app.services.native_ingestors.coinapi_wsds",
        "client_constructed": client_constructed,
        "credential_env_name": "COINAPI_API_KEY",
        "credential_value_read": False,
        "operator_paid_streaming_approved": operator_paid_streaming_approved,
        "target_redis_key_patterns": [V2_QUARANTINE_KEY_TEMPLATE],
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "quarantine_namespace_version": "v4",
        "legacy_namespace_reads_enabled": False,
        "legacy_namespace_migration_mode": "COLD_BOOTSTRAP_REQUIRED",
        "canonical_receipt_resolver_present": False,
        "trainer_consumable": False,
        "blockers": blockers,
        **OPTIONAL_SOURCE_FIELDS,
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "trader_execution_enabled": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }


def normalize_wsds_snapshot(
    *,
    symbol: str,
    snapshot: Mapping[str, Any],
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
) -> dict[str, Any]:
    """Validate one provider snapshot and return a raw quarantine record.

    ``timeframes`` remains in the callable contract for callers that haven't yet
    removed their old microfeature configuration. It is deliberately not used:
    CoinAPI wire data cannot enter a feature namespace until a canonical
    post-commit receipt resolver exists.
    """

    if (
        type(symbol) is not str
        or symbol != symbol.strip()
        or not symbol.isascii()
        or RUNTIME_SYMBOL_RE.fullmatch(symbol) is None
    ):
        raise ValueError("symbol must exactly match uppercase [A-Z0-9]+USDT")
    if not isinstance(timeframes, tuple) or any(
        type(timeframe) is not str or timeframe not in APPROVED_TIMEFRAMES
        for timeframe in timeframes
    ):
        raise ValueError("timeframes must contain only approved exact values")
    row = dict(snapshot)
    coinapi_symbol_id = row.get("coinapi_symbol_id")
    coinapi_exchange_id = row.get("coinapi_exchange_id")
    coinapi_market_type = row.get("coinapi_market_type")
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        identity is None
        or type(coinapi_exchange_id) is not str
        or type(coinapi_market_type) is not str
        or identity != (coinapi_exchange_id, coinapi_market_type, symbol)
    ):
        raise ValueError(
            "CoinAPI provider identity must exactly bind exchange, market type, and symbol"
        )
    best_bid_px = _required_float(row, "best_bid_px", positive=True)
    best_ask_px = _required_float(row, "best_ask_px", positive=True)
    best_bid_sz = _required_float(row, "best_bid_sz", nonnegative=True)
    best_ask_sz = _required_float(row, "best_ask_sz", nonnegative=True)
    book_bid_sum_5 = _required_float(row, "book_bid_sum_5", nonnegative=True)
    book_ask_sum_5 = _required_float(row, "book_ask_sum_5", nonnegative=True)
    if best_ask_px < best_bid_px:
        raise ValueError("best_ask_px must be greater than or equal to best_bid_px")

    source_event = _required_provider_timestamp(row, "source_event_time")
    provider_received = _required_provider_timestamp(row, "provider_received_time")
    observed = _required_datetime(row, "observed_at")
    ingested = _required_datetime(row, "ingested_at")
    generated = _required_datetime(row, "generated_at")
    observed_ns = _datetime_epoch_ns(observed)
    ingested_ns = _datetime_epoch_ns(ingested)
    generated_ns = _datetime_epoch_ns(generated)
    if row.get("available_at") is not None:
        raise ValueError("available_at must remain null before a postcommit receipt")
    if not (source_event[1] <= provider_received[1] <= observed_ns < ingested_ns < generated_ns):
        raise ValueError(
            "clocks must satisfy source_event <= provider_received <= observed "
            "< ingested < generated"
        )

    source_event_ts_ns = _required_exact_int(row, "source_event_ts_ns")
    source_event_ts_ms = _required_exact_int(row, "source_event_ts_ms")
    if source_event_ts_ns != source_event[1]:
        raise ValueError("source_event_ts_ns does not match source_event_time")
    if source_event_ts_ms != source_event_ts_ns // 1_000_000:
        raise ValueError("source_event_ts_ms does not match source_event_time")

    source_event_time = _iso_utc_ns(source_event_ts_ns)
    provider_received_time = _iso_utc_ns(provider_received[1])
    observed_at = _iso_utc(observed)
    ingested_at = _iso_utc(ingested)
    generated_at = _iso_utc(generated)
    trust_block_reasons = list(WSDS_RAW_TRUST_BLOCK_REASONS)
    quarantine_payload = {
        "schema_version": "v2_coinapi_wsds_raw_quarantine_v3",
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": ENFORCEMENT_EPOCH,
        "producer": "coinapi_wsds",
        "producer_version": TRUST_PRODUCER_VERSION,
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol_id,
        "coinapi_exchange_id": coinapi_exchange_id,
        "coinapi_market_type": coinapi_market_type,
        "source": "coinapi_wsds",
        "quarantine_only": True,
        "canonical_receipt_resolver_present": False,
        "updated_ts_ms": source_event_ts_ms,
        "source_event_time": source_event_time,
        "source_event_ts_ms": source_event_ts_ms,
        "source_event_ts_ns": source_event_ts_ns,
        "provider_received_time": provider_received_time,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "available_at": None,
        "generated_at": generated_at,
        "feature_cutoff": None,
        "best_bid_px": best_bid_px,
        "best_ask_px": best_ask_px,
        "best_bid_sz": best_bid_sz,
        "best_ask_sz": best_ask_sz,
        "mid_px": _optional_float(row, "mid_px"),
        "spread_bps": _optional_float(row, "spread_bps"),
        "microprice": _optional_float(row, "microprice"),
        "book_bid_sum_5": book_bid_sum_5,
        "book_ask_sum_5": book_ask_sum_5,
        "imbalance_5": _optional_float(row, "imbalance_5"),
        "postcommit_receipt_present": False,
        "feature_eligible": False,
        "trainer_consumable": False,
        "prediction_eligible": False,
        "trust_block_reasons": trust_block_reasons,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        **OPTIONAL_SOURCE_FIELDS,
    }
    if not validate_wsds_quarantine_payload(quarantine_payload):
        raise ValueError("normalized WSDS quarantine payload failed canonical validation")
    return {
        "quarantine_key": V2_QUARANTINE_KEY_TEMPLATE.format(
            coinapi_symbol_id=coinapi_symbol_id,
            symbol=symbol,
        ),
        "quarantine_payload": quarantine_payload,
        "event_identity_ns": str(source_event_ts_ns),
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
            **OPTIONAL_SOURCE_FIELDS,
        },
    }


def parse_coinapi_symbol_id(value: Any) -> tuple[str, str, str] | None:
    """Return exact ``(exchange_id, market_type, runtime_symbol)`` identity."""

    if type(value) is not str or value != value.strip() or not value.isascii():
        return None
    match = COINAPI_SYMBOL_ID_RE.fullmatch(value)
    if match is None:
        return None
    runtime_symbol = f"{match.group('base_asset')}USDT"
    if RUNTIME_SYMBOL_RE.fullmatch(runtime_symbol) is None:
        return None
    return match.group("exchange_id"), match.group("market_type"), runtime_symbol


def parse_provider_timestamp(value: Any) -> tuple[datetime, int] | None:
    """Parse a CoinAPI timestamp without losing its sub-microsecond identity."""

    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        try:
            parsed = value.astimezone(UTC)
            return parsed, _datetime_epoch_ns(parsed)
        except OverflowError:
            return None
    if not isinstance(value, str):
        return None
    match = _PROVIDER_TIMESTAMP_RE.fullmatch(value.strip())
    if match is None:
        return None
    zone = "+00:00" if match.group("zone") == "Z" else match.group("zone")
    try:
        whole_second = datetime.fromisoformat(f"{match.group('second')}{zone}")
        if whole_second.tzinfo is None:
            return None
        whole_second = whole_second.astimezone(UTC)
    except (OverflowError, ValueError):
        return None
    fraction = (match.group("fraction") or "").ljust(9, "0")
    event_ns = _datetime_epoch_ns(whole_second) + int(fraction or "0")
    parsed = whole_second + timedelta(microseconds=int(fraction[:6] or "0"))
    return parsed, event_ns


def iso_utc_ns(value: int) -> str:
    return _iso_utc_ns(value)


def datetime_epoch_ns(value: datetime) -> int:
    return _datetime_epoch_ns(value)


def validate_wsds_quarantine_payload(payload: Mapping[str, Any]) -> bool:
    """Validate the complete canonical WSDS raw record at its commit boundary."""

    if set(payload) != WSDS_RAW_QUARANTINE_FIELDS:
        return False
    symbol = payload.get("symbol")
    identity = parse_coinapi_symbol_id(payload.get("coinapi_symbol_id"))
    if (
        type(symbol) is not str
        or RUNTIME_SYMBOL_RE.fullmatch(symbol) is None
        or identity is None
        or identity[2] != symbol
        or payload.get("coinapi_exchange_id") != identity[0]
        or payload.get("coinapi_market_type") != identity[1]
        or payload.get("schema_version") != "v2_coinapi_wsds_raw_quarantine_v3"
        or payload.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or payload.get("trust_schema_version") != TRUST_SCHEMA_VERSION
        or payload.get("enforcement_epoch") != ENFORCEMENT_EPOCH
        or payload.get("producer") != "coinapi_wsds"
        or payload.get("producer_version") != TRUST_PRODUCER_VERSION
        or payload.get("source") != "coinapi_wsds"
        or payload.get("quarantine_only") is not True
        or payload.get("canonical_receipt_resolver_present") is not False
        or payload.get("available_at") is not None
        or payload.get("feature_cutoff") is not None
        or payload.get("postcommit_receipt_present") is not False
        or payload.get("feature_eligible") is not False
        or payload.get("trainer_consumable") is not False
        or payload.get("prediction_eligible") is not False
        or payload.get("trust_block_reasons") != list(WSDS_RAW_TRUST_BLOCK_REASONS)
        or payload.get("live_gate") != "blocked_human_only"
        or payload.get("live_symbols") != []
        or any(payload.get(key) is not value for key, value in OPTIONAL_SOURCE_FIELDS.items())
    ):
        return False

    source_event_ns = _canonical_timestamp_ns(payload.get("source_event_time"))
    provider_received_ns = _canonical_timestamp_ns(payload.get("provider_received_time"))
    observed_ns = _canonical_timestamp_ns(payload.get("observed_at"), local_clock=True)
    ingested_ns = _canonical_timestamp_ns(payload.get("ingested_at"), local_clock=True)
    generated_ns = _canonical_timestamp_ns(payload.get("generated_at"), local_clock=True)
    source_event_ts_ns = payload.get("source_event_ts_ns")
    source_event_ts_ms = payload.get("source_event_ts_ms")
    updated_ts_ms = payload.get("updated_ts_ms")
    if (
        source_event_ns is None
        or provider_received_ns is None
        or observed_ns is None
        or ingested_ns is None
        or generated_ns is None
        or type(source_event_ts_ns) is not int
        or source_event_ts_ns < 0
        or type(source_event_ts_ms) is not int
        or type(updated_ts_ms) is not int
        or source_event_ts_ns != source_event_ns
        or source_event_ts_ms != source_event_ns // 1_000_000
        or updated_ts_ms != source_event_ts_ms
        or not (source_event_ns <= provider_received_ns <= observed_ns < ingested_ns < generated_ns)
    ):
        return False

    best_bid_px = _exact_finite_number(payload.get("best_bid_px"))
    best_ask_px = _exact_finite_number(payload.get("best_ask_px"))
    best_bid_sz = _exact_finite_number(payload.get("best_bid_sz"))
    best_ask_sz = _exact_finite_number(payload.get("best_ask_sz"))
    book_bid_sum = _exact_finite_number(payload.get("book_bid_sum_5"))
    book_ask_sum = _exact_finite_number(payload.get("book_ask_sum_5"))
    if (
        best_bid_px is None
        or best_ask_px is None
        or best_bid_sz is None
        or best_ask_sz is None
        or book_bid_sum is None
        or book_ask_sum is None
        or best_bid_px <= 0
        or best_ask_px <= 0
        or best_ask_px < best_bid_px
        or best_bid_sz < 0
        or best_ask_sz < 0
        or book_bid_sum < 0
        or book_ask_sum < 0
        or _materially_less(book_bid_sum, best_bid_sz)
        or _materially_less(book_ask_sum, best_ask_sz)
    ):
        return False

    expected_mid = (best_bid_px + best_ask_px) / 2.0
    expected_spread_bps = (best_ask_px - best_bid_px) / expected_mid * 10_000.0
    mid_valid, mid_px = _optional_exact_finite_number(payload, "mid_px")
    spread_valid, spread_bps = _optional_exact_finite_number(payload, "spread_bps")
    if not mid_valid or not spread_valid:
        return False
    if (mid_px is None) != (spread_bps is None):
        return False
    if mid_px is not None and (
        not _derived_number_matches(mid_px, expected_mid)
        or mid_px < best_bid_px
        or mid_px > best_ask_px
    ):
        return False
    if spread_bps is not None and (
        spread_bps < 0 or not _derived_number_matches(spread_bps, expected_spread_bps)
    ):
        return False

    top_total = best_bid_sz + best_ask_sz
    microprice_valid, microprice = _optional_exact_finite_number(payload, "microprice")
    if not microprice_valid:
        return False
    if top_total == 0:
        if microprice is not None:
            return False
    elif microprice is not None:
        expected_microprice = (
            (best_bid_px * best_ask_sz) + (best_ask_px * best_bid_sz)
        ) / top_total
        if (
            microprice < best_bid_px
            or microprice > best_ask_px
            or not _derived_number_matches(microprice, expected_microprice)
        ):
            return False

    book_total = book_bid_sum + book_ask_sum
    imbalance_valid, imbalance = _optional_exact_finite_number(payload, "imbalance_5")
    if not imbalance_valid:
        return False
    if book_total == 0:
        return imbalance is None
    if imbalance is None:
        return True
    expected_imbalance = (book_bid_sum - book_ask_sum) / book_total
    return -1.0 <= imbalance <= 1.0 and _derived_number_matches(imbalance, expected_imbalance)


def _canonical_timestamp_ns(value: Any, *, local_clock: bool = False) -> int | None:
    if type(value) is not str:
        return None
    parsed = parse_provider_timestamp(value)
    if parsed is None:
        return None
    canonical = _iso_utc(parsed[0]) if local_clock else _iso_utc_ns(parsed[1])
    if value != canonical:
        return None
    return parsed[1]


def _exact_finite_number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _optional_exact_finite_number(
    payload: Mapping[str, Any],
    key: str,
) -> tuple[bool, float | None]:
    value = payload.get(key)
    if value is None:
        return True, None
    parsed = _exact_finite_number(value)
    return (parsed is not None), parsed


def _derived_number_matches(actual: float, expected: float) -> bool:
    return isfinite(expected) and isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _materially_less(left: float, right: float) -> bool:
    return left < right and not isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _optional_float(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    parsed = _safe_float(value)
    if parsed is None:
        raise ValueError(f"{key} must be finite when present")
    return parsed


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
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
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_utc_ns(value: int) -> str:
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    whole_second = _EPOCH + timedelta(seconds=seconds)
    base = whole_second.strftime("%Y-%m-%dT%H:%M:%S")
    if nanoseconds == 0:
        return f"{base}Z"
    return f"{base}.{nanoseconds:09d}".rstrip("0") + "Z"


def _datetime_epoch_ns(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _required_datetime(row: Mapping[str, Any], key: str) -> datetime:
    value = _parse_datetime(row.get(key))
    if value is None:
        raise ValueError(f"{key} must be a timezone-aware ISO timestamp")
    return value


def _required_provider_timestamp(
    row: Mapping[str, Any],
    key: str,
) -> tuple[datetime, int]:
    value = parse_provider_timestamp(row.get(key))
    if value is None:
        raise ValueError(f"{key} must be a timezone-aware provider timestamp")
    return value


def _required_exact_int(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if value is None or isinstance(value, bool):
        raise ValueError(f"{key} must be an exact nonnegative integer")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{key} must be an exact nonnegative integer") from None
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        raise ValueError(f"{key} must be an exact nonnegative integer")
    return int(parsed)


def _required_float(
    row: Mapping[str, Any],
    key: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    value = _safe_float(row.get(key))
    if value is None:
        raise ValueError(f"{key} is required and must be finite")
    if positive and value <= 0:
        raise ValueError(f"{key} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{key} must be nonnegative")
    return value
