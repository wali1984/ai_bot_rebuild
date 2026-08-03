"""Symbol-adaptive round-trip trading cost model (paper-only).

Replaces the flat 12.0 bps round-trip cost assumption
(``2 * (5 fee + 1 slippage)`` from
``services/native_trainer/hybrid_cuda_trainer/config.py`` and
``services/rl_core/trainer_output.py::DEFAULT_ROUND_TRIP_COST_BPS``)
with per-symbol live evidence:

    round_trip_cost_bps =
        2 * taker_fee_bps_per_side              (fee floor; never lowered)
      + live full bid/ask spread_bps            (cross half-spread per side)
      + 2 * depth-aware impact_per_side_bps     (notional vs top-of-book depth)

Evidence source: ``v2:orderbook:features:binance:{SYMBOL}`` (full-universe
Binance depth WSS, commit fdedec6d16) with a freshness gate.

Fallback policy (missing/stale book): CONSERVATIVE. The estimate is floored
at the legacy flat baseline (12.0 bps) so a data gap can never make a symbol
look cheaper than the old model did. Majors only get cheaper when live depth
evidence proves it; wide-spread tail symbols get honestly more expensive.

Every estimate carries provenance fields and is publishable to
``v2:costs:round_trip_bps:{SYMBOL}`` for Signal Explainability.

This module is paper/shadow only. It never places orders and never writes
outside the v2: namespace.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Callable, Mapping, Optional

ESTIMATOR_VERSION = "adaptive_cost_model_v1"

ORDERBOOK_FEATURES_KEY_TEMPLATE = "v2:orderbook:features:binance:{symbol}"
COST_KEY_TEMPLATE = "v2:costs:round_trip_bps:{symbol}"
COST_KEY_TTL_SECONDS = 600

# Legacy flat assumption: 2 * (5 fee + 1 slippage). This is the conservative
# fallback floor, NOT the primary model.
FLAT_BASELINE_ROUND_TRIP_BPS = 12.0
# Per-side taker fee the system already assumes
# (hybrid_cuda_trainer/config.py: fee_bps_per_side = 5.0). Do not lower
# without raw evidence of the actual configured exchange fee tier.
DEFAULT_TAKER_FEE_BPS_PER_SIDE = 5.0
FEE_SOURCE_DEFAULT = (
    "CONFIGURED_PAPER_FEE_SCHEDULE:"
    "adaptive_capital_allocator.AllocationInput.fee_bps"
)
# Typical paper entry notional upper bound (paper loop sizes ~$25-250).
DEFAULT_NOTIONAL_USD = 250.0
DEFAULT_MAX_ORDERBOOK_AGE_SECONDS = 60.0
# Legacy flat model's per-side slippage reserve, reused in the conservative
# fallback path only.
FALLBACK_SLIPPAGE_RESERVE_BPS_PER_SIDE = 1.0

FRESHNESS_FRESH_ORDERBOOK = "FRESH_ORDERBOOK"
FRESHNESS_FALLBACK_CONSERVATIVE = "FALLBACK_CONSERVATIVE"

SPREAD_SOURCE_LIVE_ORDERBOOK = "orderbook_features_binance_live_spread_bps"
SPREAD_SOURCE_OBSERVED_PROXY = "observed_spread_proxy_bps"
SPREAD_SOURCE_MISSING = "missing"

IMPACT_SOURCE_EXCHANGE_ESTIMATE = "orderbook_estimated_price_impact_bps_scaled_linear"
IMPACT_SOURCE_DEPTH_RATIO = "notional_over_top5_depth_times_half_spread"
IMPACT_SOURCE_RESERVE = "fallback_flat_slippage_reserve"

_ENV_FEE = "V2_COST_TAKER_FEE_BPS_PER_SIDE"
_ENV_NOTIONAL = "V2_COST_MODEL_NOTIONAL_USD"
_ENV_MAX_AGE = "V2_COST_MODEL_MAX_ORDERBOOK_AGE_SECONDS"

# Process-local observation state used only to prove an adaptive source cadence.
# A restart intentionally removes the proof and pauses exact PPO sampling until
# three positive cadence intervals (normally four distinct availability
# clocks) have been observed again. Ordinary
# predictions continue through the conservative cost path while proof rebuilds.
_ORDERBOOK_AVAILABILITY_STATE: dict[str, dict[str, Any]] = {}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def configured_taker_fee_bps_per_side() -> tuple[float, str]:
    raw = os.environ.get(_ENV_FEE)
    if raw not in (None, ""):
        try:
            value = float(raw)
            if value > 0:
                return value, f"env:{_ENV_FEE}"
        except (TypeError, ValueError):
            pass
    return DEFAULT_TAKER_FEE_BPS_PER_SIDE, FEE_SOURCE_DEFAULT


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _strict_utc(value: Any) -> Optional[datetime]:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        if abs(number) > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(payload: Mapping[str, Any]) -> str | None:
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _adaptive_source_cadence(
    symbol: str,
    available_at: datetime | None,
) -> tuple[float | None, int, str]:
    """Return a robust recent source-cadence window with no age constant."""

    if available_at is None:
        return None, 0, "SOURCE_AVAILABLE_AT_MISSING"
    state = _ORDERBOOK_AVAILABILITY_STATE.get(symbol)
    if state is None:
        _ORDERBOOK_AVAILABILITY_STATE[symbol] = {
            "last_available_at": available_at,
            "recent_intervals_seconds": deque(maxlen=31),
            "distinct_clock_count": 1,
        }
        return None, 0, "AWAITING_ROBUST_SOURCE_CADENCE_SAMPLE"
    previous = state.get("last_available_at")
    if not isinstance(previous, datetime):
        _ORDERBOOK_AVAILABILITY_STATE.pop(symbol, None)
        return _adaptive_source_cadence(symbol, available_at)
    if available_at < previous:
        _ORDERBOOK_AVAILABILITY_STATE[symbol] = {
            "last_available_at": available_at,
            "recent_intervals_seconds": deque(maxlen=31),
            "distinct_clock_count": 1,
        }
        return None, 0, "SOURCE_AVAILABLE_AT_REGRESSION"
    if available_at > previous:
        interval = (available_at - previous).total_seconds()
        state["last_available_at"] = available_at
        intervals = state.get("recent_intervals_seconds")
        if not isinstance(intervals, deque):
            intervals = deque(maxlen=31)
            state["recent_intervals_seconds"] = intervals
        if interval > 0.0:
            intervals.append(interval)
        state["distinct_clock_count"] = int(
            state.get("distinct_clock_count") or 1
        ) + 1
    intervals = state.get("recent_intervals_seconds")
    samples = (
        [float(value) for value in intervals if _finite(value) is not None]
        if isinstance(intervals, deque)
        else []
    )
    sample_count = len(samples)
    adaptive_window = None
    if sample_count >= 3:
        cadence_median = median(samples)
        cadence_mad = median(
            [abs(value - cadence_median) for value in samples]
        )
        adaptive_window = cadence_median + cadence_mad
    return (
        adaptive_window,
        sample_count,
        "RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"
        if adaptive_window is not None and adaptive_window > 0.0
        else "AWAITING_ROBUST_SOURCE_CADENCE_SAMPLE",
    )


def _utc_iso(now: datetime) -> str:
    # Preserve the same precision used to calculate spread_age_seconds.  Truncating
    # this clock to milliseconds while retaining a microsecond-precision age makes
    # the published envelope internally inconsistent and causes the strict exact-
    # cost consumer to reject genuine live evidence.
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class CostEstimate:
    """One symbol's round-trip cost estimate with full provenance."""

    symbol: str
    round_trip_cost_bps: float
    taker_fee_bps_per_side: float
    fee_source: str
    fee_schedule_evidence: Mapping[str, Any]
    fee_schedule_evidence_sha256: str
    spread_bps: Optional[float]
    spread_source: str
    spread_age_seconds: Optional[float]
    impact_per_side_bps: Optional[float]
    impact_source: str
    depth_used_usd: Optional[float]
    notional_usd_assumed: float
    notional_configuration_evidence: Mapping[str, Any]
    notional_configuration_evidence_sha256: str
    freshness_status: str
    conservative_floor_applied: bool
    flat_baseline_round_trip_bps: float
    orderbook_key: str
    computed_utc: str
    orderbook_schema_version: str | None
    orderbook_source_payload_sha256: str | None
    orderbook_source_payload: Mapping[str, Any] | None
    orderbook_observed_at: str | None
    orderbook_available_at: str | None
    orderbook_generated_at: str | None
    orderbook_source_clock_field: str | None
    orderbook_sequence_gap_flag: bool | None
    source_future_clock_invalid: bool
    adaptive_max_age_seconds: float | None
    adaptive_freshness_sample_count: int
    adaptive_freshness_method: str
    adaptive_freshness_proven: bool
    expires_at: str | None
    funding_bps_at_decision_time: float | None = None
    funding_source: str | None = None
    estimator_version: str = ESTIMATOR_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_fresh(self) -> bool:
        return self.freshness_status == FRESHNESS_FRESH_ORDERBOOK

    def to_payload(self) -> dict[str, Any]:
        def _round(value: Optional[float]) -> Optional[float]:
            # Exact-cost consumers recompute the estimate from the embedded
            # orderbook readback.  Decimal truncation breaks that identity for
            # real spreads/impacts, so publish the native finite float.
            return None if value is None else float(value)

        source_payload_sha256 = self.orderbook_source_payload_sha256
        source_readback_sha256 = (
            _canonical_sha256(self.orderbook_source_payload)
            if isinstance(self.orderbook_source_payload, Mapping)
            else None
        )

        return {
            "symbol": self.symbol,
            "round_trip_cost_bps": _round(self.round_trip_cost_bps),
            "taker_fee_bps_per_side": _round(self.taker_fee_bps_per_side),
            "fee_source": self.fee_source,
            "fee_schedule_evidence": dict(self.fee_schedule_evidence),
            "fee_schedule_evidence_sha256": self.fee_schedule_evidence_sha256,
            "spread_bps": _round(self.spread_bps),
            "spread_source": self.spread_source,
            "spread_age_seconds": _round(self.spread_age_seconds),
            "impact_per_side_bps": _round(self.impact_per_side_bps),
            "impact_source": self.impact_source,
            "depth_used_usd": _round(self.depth_used_usd),
            "notional_usd_assumed": _round(self.notional_usd_assumed),
            "notional_configuration_evidence": dict(
                self.notional_configuration_evidence
            ),
            "notional_configuration_evidence_sha256": (
                self.notional_configuration_evidence_sha256
            ),
            "freshness_status": self.freshness_status,
            "conservative_floor_applied": self.conservative_floor_applied,
            "flat_baseline_round_trip_bps": _round(self.flat_baseline_round_trip_bps),
            "orderbook_key": self.orderbook_key,
            "computed_utc": self.computed_utc,
            "available_at": self.computed_utc,
            "source_event_time": self.orderbook_observed_at,
            "producer_generated_at": self.computed_utc,
            "record_available_at": self.computed_utc,
            "fee_bps_per_side": _round(self.taker_fee_bps_per_side),
            "slippage_bps_per_side": _round(self.impact_per_side_bps),
            "funding_bps_at_decision_time": _round(
                self.funding_bps_at_decision_time
            ),
            "funding_source": self.funding_source,
            "source_payload_sha256": source_payload_sha256,
            "source_readback_sha256": source_readback_sha256,
            "source_readback_verified": bool(
                source_payload_sha256
                and source_readback_sha256
                and source_payload_sha256 == source_readback_sha256
            ),
            "orderbook_schema_version": self.orderbook_schema_version,
            "orderbook_source_payload_sha256": (
                self.orderbook_source_payload_sha256
            ),
            "orderbook_source_payload": (
                dict(self.orderbook_source_payload)
                if isinstance(self.orderbook_source_payload, Mapping)
                else None
            ),
            "orderbook_observed_at": self.orderbook_observed_at,
            "orderbook_available_at": self.orderbook_available_at,
            "orderbook_generated_at": self.orderbook_generated_at,
            "orderbook_source_clock_field": self.orderbook_source_clock_field,
            "orderbook_sequence_gap_flag": self.orderbook_sequence_gap_flag,
            "source_future_clock_invalid": self.source_future_clock_invalid,
            "adaptive_max_age_seconds": _round(self.adaptive_max_age_seconds),
            "adaptive_freshness_sample_count": int(
                self.adaptive_freshness_sample_count
            ),
            "adaptive_freshness_method": self.adaptive_freshness_method,
            "adaptive_freshness_proven": self.adaptive_freshness_proven,
            "expires_at": self.expires_at,
            "estimator_version": self.estimator_version,
            "notes": list(self.notes),
            "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
        }


def _orderbook_source_provenance(
    symbol: str,
    book: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(book, Mapping):
        return {
            "age_seconds": None,
            "source_future_clock_invalid": False,
            "adaptive_max_age_seconds": None,
            "adaptive_freshness_sample_count": 0,
            "adaptive_freshness_method": "ORDERBOOK_SOURCE_MISSING",
            "adaptive_freshness_proven": False,
            "expires_at": None,
        }
    available_at = _strict_utc(book.get("available_at"))
    observed_at = _strict_utc(book.get("event_time"))
    generated_at = _strict_utc(
        book.get("generated_at") or book.get("generated_utc")
    )
    future_clock_invalid = any(
        clock is not None and clock > now
        for clock in (observed_at, available_at, generated_at)
    )
    clock_order_valid = bool(
        observed_at is not None
        and available_at is not None
        and generated_at is not None
        and observed_at <= available_at <= generated_at <= now
    )
    age_seconds = (
        (now - available_at).total_seconds()
        if clock_order_valid and available_at is not None
        else None
    )
    cadence_seconds, cadence_samples, cadence_method = _adaptive_source_cadence(
        symbol,
        available_at if clock_order_valid else None,
    )
    expires_at = (
        available_at + timedelta(seconds=cadence_seconds)
        if available_at is not None
        and cadence_seconds is not None
        and cadence_seconds > 0.0
        else None
    )
    sequence_gap = book.get("sequence_gap_flag")
    sequence_gap_flag = (
        bool(float(sequence_gap) != 0.0)
        if _finite(sequence_gap) is not None
        else None
    )
    adaptive_proven = bool(
        clock_order_valid
        and not future_clock_invalid
        and cadence_samples >= 3
        and cadence_seconds is not None
        and cadence_seconds > 0.0
        and expires_at is not None
        and now <= expires_at
        and sequence_gap_flag is False
        and _canonical_sha256(book) is not None
        and str(book.get("schema_version") or "").strip()
    )

    def iso(clock: datetime | None) -> str | None:
        return (
            clock.isoformat(timespec="microseconds").replace("+00:00", "Z")
            if clock is not None
            else None
        )

    return {
        "age_seconds": age_seconds,
        "orderbook_schema_version": str(book.get("schema_version") or "") or None,
        "orderbook_source_payload_sha256": _canonical_sha256(book),
        "orderbook_source_payload": dict(book),
        "orderbook_observed_at": iso(observed_at),
        "orderbook_available_at": iso(available_at),
        "orderbook_generated_at": iso(generated_at),
        "orderbook_source_clock_field": "available_at",
        "orderbook_sequence_gap_flag": sequence_gap_flag,
        "source_future_clock_invalid": future_clock_invalid,
        "adaptive_max_age_seconds": cadence_seconds,
        "adaptive_freshness_sample_count": cadence_samples,
        "adaptive_freshness_method": cadence_method,
        "adaptive_freshness_proven": adaptive_proven,
        "expires_at": iso(expires_at),
    }


def _depth_aware_impact_per_side(
    book: Mapping[str, Any],
    *,
    notional_usd: float,
    spread_bps: Optional[float],
) -> tuple[Optional[float], str, Optional[float], list[str]]:
    """Return (impact_per_side_bps, impact_source, depth_used_usd, notes).

    Preference order:
    1. Exchange-book-derived ``estimated_price_impact_bps`` at its reference
       notional, scaled linearly to our notional (slightly conservative for
       notionals below the reference).
    2. Ratio of our notional to the thinner top-5 depth side, scaled by the
       half-spread (walking-the-book proxy). Near zero when notional << depth.
    """
    notes: list[str] = []
    est = _finite(book.get("estimated_price_impact_bps"))
    ref = _finite(
        book.get("price_impact_notional_usd")
        or book.get("impact_reference_notional_usd")
    )
    depth_total = _finite(book.get("depth_total_usd"))
    if est is not None and est >= 0.0 and ref is not None and ref > 0.0:
        impact = est * (notional_usd / ref)
        return impact, IMPACT_SOURCE_EXCHANGE_ESTIMATE, depth_total, notes

    depth_bid = _finite(book.get("depth_5_bid_usd")) or _finite(
        book.get("depth_20_bid_usd")
    )
    depth_ask = _finite(book.get("depth_5_ask_usd")) or _finite(
        book.get("depth_20_ask_usd")
    )
    sides = [d for d in (depth_bid, depth_ask) if d is not None and d > 0.0]
    thin_side = min(sides) if sides else None
    if thin_side is not None and spread_bps is not None:
        ratio = notional_usd / thin_side
        impact = 0.5 * spread_bps * ratio
        return impact, IMPACT_SOURCE_DEPTH_RATIO, thin_side, notes

    notes.append("depth_evidence_missing_used_flat_slippage_reserve")
    return (
        FALLBACK_SLIPPAGE_RESERVE_BPS_PER_SIDE,
        IMPACT_SOURCE_RESERVE,
        None,
        notes,
    )


def estimate_round_trip_cost_bps(
    symbol: str,
    *,
    get_json: Callable[[str], Optional[Mapping[str, Any]]],
    notional_usd: Optional[float] = None,
    max_orderbook_age_seconds: Optional[float] = None,
    observed_spread_proxy_bps: Optional[float] = None,
    funding_bps_at_decision_time: Optional[float] = None,
    funding_source: Optional[str] = None,
    flat_baseline_bps: float = FLAT_BASELINE_ROUND_TRIP_BPS,
    now_utc: Optional[datetime] = None,
) -> CostEstimate:
    """Estimate the symbol's round-trip cost from live orderbook evidence.

    ``get_json`` is an injected JSON getter (redis-backed in production).
    Missing/stale evidence NEVER yields an optimistic estimate: the fallback
    path is floored at ``flat_baseline_bps``.
    """
    now = now_utc or datetime.now(timezone.utc)
    symbol_norm = str(symbol or "").strip().upper()
    fee_per_side, fee_source = configured_taker_fee_bps_per_side()
    notional = (
        float(notional_usd)
        if notional_usd is not None and notional_usd > 0
        else _env_float(_ENV_NOTIONAL, DEFAULT_NOTIONAL_USD)
    )
    fee_schedule_evidence = {
        "schema_version": "paper_cost_fee_schedule_evidence_v1",
        "configuration_kind": "CONFIGURED_TAKER_FEE_BPS_PER_SIDE",
        "taker_fee_bps_per_side": fee_per_side,
        "fee_source": fee_source,
    }
    fee_schedule_evidence_sha256 = _canonical_sha256(fee_schedule_evidence)
    assert fee_schedule_evidence_sha256 is not None
    notional_source = (
        "CALLER_EXPLICIT_COST_MODEL_NOTIONAL_USD"
        if notional_usd is not None and notional_usd > 0
        else (
            f"env:{_ENV_NOTIONAL}"
            if os.environ.get(_ENV_NOTIONAL) not in (None, "")
            else "DEFAULT_COST_MODEL_NOTIONAL_USD"
        )
    )
    notional_configuration_evidence = {
        "schema_version": "paper_cost_notional_configuration_evidence_v1",
        "configuration_kind": "COST_MODEL_REFERENCE_NOTIONAL_USD",
        "notional_usd": notional,
        "notional_source": notional_source,
    }
    notional_configuration_evidence_sha256 = _canonical_sha256(
        notional_configuration_evidence
    )
    assert notional_configuration_evidence_sha256 is not None
    max_age = (
        float(max_orderbook_age_seconds)
        if max_orderbook_age_seconds is not None and max_orderbook_age_seconds > 0
        else _env_float(_ENV_MAX_AGE, DEFAULT_MAX_ORDERBOOK_AGE_SECONDS)
    )
    orderbook_key = ORDERBOOK_FEATURES_KEY_TEMPLATE.format(symbol=symbol_norm)

    book: Optional[Mapping[str, Any]] = None
    notes: list[str] = []
    try:
        raw = get_json(orderbook_key)
        if isinstance(raw, Mapping):
            book = raw
    except Exception as exc:  # noqa: BLE001 - estimator must never raise upstream
        notes.append(f"orderbook_read_failed:{type(exc).__name__}")

    source_provenance = _orderbook_source_provenance(symbol_norm, book, now)
    age = _finite(source_provenance.get("age_seconds"))
    spread_bps = _finite(book.get("spread_bps")) if book is not None else None

    live_components_available = (
        book is not None
        and age is not None
        and source_provenance.get("source_future_clock_invalid") is False
        and spread_bps is not None
        and spread_bps >= 0.0
    )
    # Ordinary operation retains its legacy/static safety fallback while exact
    # evidence may independently prove freshness from observed source cadence.
    # The static max-age setting therefore cannot veto an otherwise valid
    # adaptive proof.
    fresh = bool(
        live_components_available
        and (
            age <= max_age
            or source_provenance.get("adaptive_freshness_proven") is True
        )
    )

    source_fields = {
        field: source_provenance.get(field)
        for field in (
            "orderbook_schema_version",
            "orderbook_source_payload_sha256",
            "orderbook_source_payload",
            "orderbook_observed_at",
            "orderbook_available_at",
            "orderbook_generated_at",
            "orderbook_source_clock_field",
            "orderbook_sequence_gap_flag",
            "source_future_clock_invalid",
            "adaptive_max_age_seconds",
            "adaptive_freshness_sample_count",
            "adaptive_freshness_method",
            "adaptive_freshness_proven",
            "expires_at",
        )
    }

    if fresh:
        impact, impact_source, depth_used, impact_notes = _depth_aware_impact_per_side(
            book,  # type: ignore[arg-type]
            notional_usd=notional,
            spread_bps=spread_bps,
        )
        notes.extend(impact_notes)
        round_trip = 2.0 * fee_per_side + spread_bps + 2.0 * float(impact or 0.0)
        return CostEstimate(
            symbol=symbol_norm,
            round_trip_cost_bps=round_trip,
            taker_fee_bps_per_side=fee_per_side,
            fee_source=fee_source,
            fee_schedule_evidence=fee_schedule_evidence,
            fee_schedule_evidence_sha256=fee_schedule_evidence_sha256,
            spread_bps=spread_bps,
            spread_source=SPREAD_SOURCE_LIVE_ORDERBOOK,
            spread_age_seconds=age,
            impact_per_side_bps=impact,
            impact_source=impact_source,
            depth_used_usd=depth_used,
            notional_usd_assumed=notional,
            notional_configuration_evidence=notional_configuration_evidence,
            notional_configuration_evidence_sha256=(
                notional_configuration_evidence_sha256
            ),
            freshness_status=FRESHNESS_FRESH_ORDERBOOK,
            conservative_floor_applied=False,
            flat_baseline_round_trip_bps=flat_baseline_bps,
            orderbook_key=orderbook_key,
            computed_utc=_utc_iso(now),
            funding_bps_at_decision_time=_finite(
                funding_bps_at_decision_time
            ),
            funding_source=(
                str(funding_source).strip() if funding_source else None
            ),
            **source_fields,
            notes=tuple(notes),
        )

    # Conservative fallback: never below the legacy flat baseline.
    if book is None:
        notes.append("orderbook_payload_missing")
    elif age is None:
        notes.append("orderbook_timestamp_missing")
    elif age > max_age and source_provenance.get("adaptive_freshness_proven") is not True:
        notes.append(f"orderbook_stale_age_{age:.1f}s_gt_{max_age:.0f}s")
    if source_provenance.get("source_future_clock_invalid") is True:
        notes.append("orderbook_source_clock_in_future")
    if book is not None and spread_bps is None:
        notes.append("orderbook_spread_missing")

    proxy = _finite(observed_spread_proxy_bps)
    if proxy is not None and proxy < 0:
        proxy = None
    spread_source = (
        SPREAD_SOURCE_OBSERVED_PROXY if proxy is not None else SPREAD_SOURCE_MISSING
    )
    base = (
        2.0 * fee_per_side
        + (proxy or 0.0)
        + 2.0 * FALLBACK_SLIPPAGE_RESERVE_BPS_PER_SIDE
    )
    round_trip = max(float(flat_baseline_bps), base)
    return CostEstimate(
        symbol=symbol_norm,
        round_trip_cost_bps=round_trip,
        taker_fee_bps_per_side=fee_per_side,
        fee_source=fee_source,
        fee_schedule_evidence=fee_schedule_evidence,
        fee_schedule_evidence_sha256=fee_schedule_evidence_sha256,
        spread_bps=proxy,
        spread_source=spread_source,
        spread_age_seconds=None,
        impact_per_side_bps=FALLBACK_SLIPPAGE_RESERVE_BPS_PER_SIDE,
        impact_source=IMPACT_SOURCE_RESERVE,
        depth_used_usd=None,
        notional_usd_assumed=notional,
        notional_configuration_evidence=notional_configuration_evidence,
        notional_configuration_evidence_sha256=(
            notional_configuration_evidence_sha256
        ),
        freshness_status=FRESHNESS_FALLBACK_CONSERVATIVE,
        conservative_floor_applied=round_trip > base or round_trip == float(flat_baseline_bps),
        flat_baseline_round_trip_bps=flat_baseline_bps,
        orderbook_key=orderbook_key,
        computed_utc=_utc_iso(now),
        funding_bps_at_decision_time=_finite(funding_bps_at_decision_time),
        funding_source=str(funding_source).strip() if funding_source else None,
        **source_fields,
        notes=tuple(notes),
    )


def after_cost_for_action(
    expected_move_bps: Any,
    selected_action: Any,
    round_trip_cost_bps: Any,
) -> Optional[float]:
    """Signed after-cost edge under the trainer's sign convention.

    long  -> move - cost (favorable when positive)
    short -> move + cost (favorable when negative)
    hold/other -> None (caller keeps the trainer's value)
    """
    move = _finite(expected_move_bps)
    cost = _finite(round_trip_cost_bps)
    if move is None or cost is None:
        return None
    action = str(selected_action or "").strip().lower()
    if action == "long":
        return move - abs(cost)
    if action == "short":
        return move + abs(cost)
    return None


def publish_cost_estimate(
    estimate: CostEstimate,
    *,
    client: Any = None,
    set_json: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    ttl_seconds: int = COST_KEY_TTL_SECONDS,
) -> bool:
    """Write the per-symbol cost estimate to v2:costs:round_trip_bps:{SYMBOL}.

    Requires an acknowledged raw Redis write with native TTL support.  A
    fallback JSON writer cannot prove expiry and therefore must not publish a
    payload that advertises ``publication_ttl_seconds``. Never raises.
    """
    key = COST_KEY_TEMPLATE.format(symbol=estimate.symbol)
    payload = estimate.to_payload()
    effective_ttl_seconds = max(1, int(ttl_seconds))
    if estimate.adaptive_freshness_proven is True:
        computed_at = _strict_utc(estimate.computed_utc)
        expires_at = _strict_utc(estimate.expires_at)
        if computed_at is None or expires_at is None or expires_at <= computed_at:
            return False
        remaining_seconds = (expires_at - computed_at).total_seconds()
        effective_ttl_seconds = max(
            1,
            min(effective_ttl_seconds, int(math.ceil(remaining_seconds))),
        )
    payload["publication_ttl_seconds"] = effective_ttl_seconds
    try:
        if client is not None and hasattr(client, "set"):
            acknowledged = client.set(
                key,
                json.dumps(payload, sort_keys=True),
                ex=effective_ttl_seconds,
            )
            return acknowledged is True
        # Keep the argument for caller compatibility, but do not degrade an
        # expiring evidence contract into an immortal last-write-wins key.
        del set_json
    except Exception:  # noqa: BLE001 - cost publication must never break callers
        return False
    return False
