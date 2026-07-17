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

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
FEE_SOURCE_DEFAULT = "hybrid_cuda_trainer_config_fee_bps_per_side_5.0"
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


def _utc_iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class CostEstimate:
    """One symbol's round-trip cost estimate with full provenance."""

    symbol: str
    round_trip_cost_bps: float
    taker_fee_bps_per_side: float
    fee_source: str
    spread_bps: Optional[float]
    spread_source: str
    spread_age_seconds: Optional[float]
    impact_per_side_bps: Optional[float]
    impact_source: str
    depth_used_usd: Optional[float]
    notional_usd_assumed: float
    freshness_status: str
    conservative_floor_applied: bool
    flat_baseline_round_trip_bps: float
    orderbook_key: str
    computed_utc: str
    estimator_version: str = ESTIMATOR_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_fresh(self) -> bool:
        return self.freshness_status == FRESHNESS_FRESH_ORDERBOOK

    def to_payload(self) -> dict[str, Any]:
        def _round(value: Optional[float]) -> Optional[float]:
            return None if value is None else round(float(value), 8)

        return {
            "symbol": self.symbol,
            "round_trip_cost_bps": _round(self.round_trip_cost_bps),
            "taker_fee_bps_per_side": _round(self.taker_fee_bps_per_side),
            "fee_source": self.fee_source,
            "spread_bps": _round(self.spread_bps),
            "spread_source": self.spread_source,
            "spread_age_seconds": _round(self.spread_age_seconds),
            "impact_per_side_bps": _round(self.impact_per_side_bps),
            "impact_source": self.impact_source,
            "depth_used_usd": _round(self.depth_used_usd),
            "notional_usd_assumed": _round(self.notional_usd_assumed),
            "freshness_status": self.freshness_status,
            "conservative_floor_applied": self.conservative_floor_applied,
            "flat_baseline_round_trip_bps": _round(self.flat_baseline_round_trip_bps),
            "orderbook_key": self.orderbook_key,
            "computed_utc": self.computed_utc,
            "estimator_version": self.estimator_version,
            "notes": list(self.notes),
            "scope": "PAPER_ONLY_ADAPTIVE_COST_MODEL",
        }


def _orderbook_age_seconds(book: Mapping[str, Any], now: datetime) -> Optional[float]:
    for fld in ("generated_at", "available_at", "event_time", "received_at"):
        parsed = _parse_utc(book.get(fld))
        if parsed is not None:
            return max(0.0, (now - parsed).total_seconds())
    return None


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
    ref = _finite(book.get("price_impact_notional_usd"))
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

    age = _orderbook_age_seconds(book, now) if book is not None else None
    spread_bps = _finite(book.get("spread_bps")) if book is not None else None

    fresh = (
        book is not None
        and age is not None
        and age <= max_age
        and spread_bps is not None
        and spread_bps >= 0.0
    )

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
            spread_bps=spread_bps,
            spread_source=SPREAD_SOURCE_LIVE_ORDERBOOK,
            spread_age_seconds=age,
            impact_per_side_bps=impact,
            impact_source=impact_source,
            depth_used_usd=depth_used,
            notional_usd_assumed=notional,
            freshness_status=FRESHNESS_FRESH_ORDERBOOK,
            conservative_floor_applied=False,
            flat_baseline_round_trip_bps=flat_baseline_bps,
            orderbook_key=orderbook_key,
            computed_utc=_utc_iso(now),
            notes=tuple(notes),
        )

    # Conservative fallback: never below the legacy flat baseline.
    if book is None:
        notes.append("orderbook_payload_missing")
    elif age is None:
        notes.append("orderbook_timestamp_missing")
    elif age > max_age:
        notes.append(f"orderbook_stale_age_{age:.1f}s_gt_{max_age:.0f}s")
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
        spread_bps=proxy,
        spread_source=spread_source,
        spread_age_seconds=None,
        impact_per_side_bps=FALLBACK_SLIPPAGE_RESERVE_BPS_PER_SIDE,
        impact_source=IMPACT_SOURCE_RESERVE,
        depth_used_usd=None,
        notional_usd_assumed=notional,
        freshness_status=FRESHNESS_FALLBACK_CONSERVATIVE,
        conservative_floor_applied=round_trip > base or round_trip == float(flat_baseline_bps),
        flat_baseline_round_trip_bps=flat_baseline_bps,
        orderbook_key=orderbook_key,
        computed_utc=_utc_iso(now),
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

    Prefers a raw redis client (TTL supported); falls back to an injected
    ``set_json``. Never raises.
    """
    key = COST_KEY_TEMPLATE.format(symbol=estimate.symbol)
    payload = estimate.to_payload()
    try:
        if client is not None and hasattr(client, "set"):
            client.set(key, json.dumps(payload, sort_keys=True), ex=int(ttl_seconds))
            return True
        if set_json is not None:
            set_json(key, payload)
            return True
    except Exception:  # noqa: BLE001 - cost publication must never break callers
        return False
    return False
