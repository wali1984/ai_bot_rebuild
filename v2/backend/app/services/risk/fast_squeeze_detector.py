"""Fast squeeze / liquidation-sweep detector.

Fuses orderbook imbalance, taker flow, liquidation clusters, OI/funding
shock, mark-index divergence, and provider confluence into an early squeeze
probability — BEFORE a large move, not after. Read-only over Redis context.

Behavioral contract (enforced by callers, asserted in tests):
- squeeze adverse to an open position => hedge_required / reduce_required
- squeeze aligned with a late entry => do not chase (entry_block_required)
- liquidation cluster near price => avoid static visible stops there
"""

from __future__ import annotations

from typing import Any, Mapping

SCHEMA_VERSION = "fast_squeeze_detector_v1"


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _dig(payload: Any, *names: str) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    for name in names:
        v = _float(payload.get(name))
        if v is not None:
            return v
    features = payload.get("features")
    if isinstance(features, Mapping):
        for name in names:
            v = _float(features.get(name))
            if v is not None:
                return v
    return None


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def detect_squeeze(
    *,
    symbol: str,
    timeframe: str,
    context: Mapping[str, Any],
    open_position_side: str | None = None,
    liquidation_buffer_usd: float | None = None,
    generated_utc: str,
) -> dict[str, Any]:
    """context keys: orderbook, agg_trades, coinglass, coinank, microstructure,
    confluence, moralis, mark_index, funding, open_interest, current_price."""
    ob = context.get("orderbook")
    cg = context.get("coinglass")
    micro = context.get("microstructure")
    conf = context.get("confluence")
    mo = context.get("moralis")

    depth_imbalance = _dig(ob, "depth_imbalance", "orderbook_depth_imbalance")
    taker_imbalance = _dig(micro, "tape_imbalance", "order_flow_imbalance") or _dig(cg, "coinglass_trade_imbalance_usd")
    liq_cascade = _dig(cg, "coinglass_liquidation_cascade_score")
    liq_imbalance = _dig(cg, "coinglass_liquidation_imbalance_usd")
    oi_delta = _dig(cg, "coinglass_open_interest_delta_usd_5m", "coinglass_open_interest_delta_usd_1h")
    funding_z = _dig(cg, "coinglass_funding_rate_zscore")
    mark_index_div = _dig(context.get("mark_index"), "mark_index_divergence_bps", "basis_bps")
    spread_bps = _dig(ob, "spread_bps", "bid_ask_spread_bps")
    sweep_conf = _dig(conf, "altdata_liquidation_sweep_risk_score")
    mo_inflow = _dig(mo, "moralis_net_exchange_flow_usd")

    signals = []
    direction_votes = 0.0  # +ve => upward squeeze (short pain), -ve => downward

    if depth_imbalance is not None and abs(depth_imbalance) >= 0.3:
        signals.append(_clip01(abs(depth_imbalance)))
        direction_votes += depth_imbalance
    if taker_imbalance is not None and abs(taker_imbalance) >= 0.3:
        signals.append(_clip01(abs(taker_imbalance)))
        direction_votes += taker_imbalance if abs(taker_imbalance) <= 1 else (1 if taker_imbalance > 0 else -1)
    if liq_cascade is not None and liq_cascade >= 0.4:
        signals.append(_clip01(liq_cascade))
        if liq_imbalance is not None:
            direction_votes += -1.0 if liq_imbalance > 0 else 1.0
    if funding_z is not None and abs(funding_z) >= 1.5:
        signals.append(_clip01(abs(funding_z) / 3.0))
        direction_votes += -1.0 if funding_z > 0 else 1.0  # crowded longs -> down squeeze
    if oi_delta is not None and abs(oi_delta) >= 1e6:
        signals.append(_clip01(abs(oi_delta) / 1e7))
    if mark_index_div is not None and abs(mark_index_div) >= 5:
        signals.append(_clip01(abs(mark_index_div) / 20.0))
    if spread_bps is not None and spread_bps >= 5:
        signals.append(_clip01(spread_bps / 20.0))
    if sweep_conf is not None:
        signals.append(_clip01(sweep_conf))
    if mo_inflow is not None and mo_inflow > 0:
        signals.append(_clip01(abs(mo_inflow) / 1e7))
        direction_votes += -0.5  # exchange inflow = sell pressure

    squeeze_probability = _clip01(sum(signals) / max(len(signals), 1)) if signals else 0.0
    squeeze_direction = "up" if direction_votes > 0 else ("down" if direction_votes < 0 else "unclear")

    # sweep risk in USD is scaled by liquidation imbalance magnitude
    sweep_risk_usd = abs(liq_imbalance) if liq_imbalance is not None else 0.0

    thin_side = None
    if depth_imbalance is not None:
        thin_side = "ask" if depth_imbalance > 0 else "bid"

    # Behavioral outputs
    adverse_to_position = False
    if open_position_side == "long" and squeeze_direction == "down":
        adverse_to_position = True
    elif open_position_side == "short" and squeeze_direction == "up":
        adverse_to_position = True

    high_squeeze = squeeze_probability >= 0.6
    buffer_thin = liquidation_buffer_usd is not None and liquidation_buffer_usd < 50.0

    hedge_required = bool(open_position_side and adverse_to_position and (high_squeeze or buffer_thin))
    reduce_required = bool(open_position_side and adverse_to_position and squeeze_probability >= 0.5)
    # Entry into an obvious sweep zone (aligned but late) must be blocked.
    entry_block_required = bool(high_squeeze and squeeze_direction != "unclear")
    market_maker_trap_score = _clip01((squeeze_probability + (sweep_conf or 0.0)) / 2.0)

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "generated_utc": generated_utc,
        "squeeze_probability": round(squeeze_probability, 4),
        "squeeze_direction": squeeze_direction,
        "sweep_risk_usd": round(sweep_risk_usd, 2),
        "liquidation_cluster_distance_usd": _dig(conf, "altdata_liquidation_cluster_distance_usd"),
        "orderbook_thin_side": thin_side,
        "oi_delta_usd": oi_delta,
        "taker_imbalance": taker_imbalance,
        "funding_pressure": funding_z,
        "market_maker_trap_score": round(market_maker_trap_score, 4),
        "adverse_to_open_position": adverse_to_position,
        "entry_block_required": entry_block_required,
        "hedge_required": hedge_required,
        "reduce_required": reduce_required,
        "avoid_static_stops_near_cluster": bool(sweep_conf and sweep_conf >= 0.5),
        "signal_count": len(signals),
        "raw_key_exposed": False,
    }
