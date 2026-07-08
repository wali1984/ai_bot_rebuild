"""Bucket health from realized session outcomes.

Buckets mirror the paper loop's quarantine dimensions: symbol, side,
timeframe, strategy mode, regime, and the composite of those. Health is
computed from NET realized outcomes (fees/slippage/funding included) so a
bucket cannot look healthy on gross numbers.
"""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _net_usd(row: dict[str, Any]) -> float:
    v = row.get("realized_net_pnl_usd")
    if v is None:
        v = row.get("realized_pnl_usd")
    return _f(v) or 0.0


def _row_confidence(row: dict[str, Any]) -> float | None:
    for field in (
        "confidence_calibrated",
        "score",
        "selected_action_probability",
        "confidence_raw",
    ):
        v = _f(row.get(field))
        if v is not None:
            return v
    return None


def candidate_bucket_keys(
    *,
    symbol: Any,
    side: Any,
    timeframe: Any,
    strategy_mode: Any,
    regime: Any,
) -> list[str]:
    keys = []
    sym = str(symbol or "").strip().upper()
    sd = str(side or "").strip().lower()
    tf = str(timeframe or "").strip().lower()
    mode = str(strategy_mode or "").strip().lower()
    rg = str(regime or "").strip().upper()
    if sym:
        keys.append(f"symbol:{sym}")
    if sd:
        keys.append(f"side:{sd}")
    if tf:
        keys.append(f"timeframe:{tf}")
    if mode:
        keys.append(f"strategy_mode:{mode}")
    if rg:
        keys.append(f"regime:{rg}")
    if sd and tf:
        keys.append(f"side_timeframe:{sd}|{tf}")
    if mode and rg:
        keys.append(f"strategy_regime:{mode}|{rg}")
    return keys


def _row_bucket_keys(row: dict[str, Any]) -> list[str]:
    return candidate_bucket_keys(
        symbol=row.get("symbol"),
        side=row.get("side"),
        timeframe=row.get("timeframe"),
        strategy_mode=row.get("strategy_selected_mode") or row.get("strategy_mode"),
        regime=row.get("market_regime_at_entry") or row.get("market_regime"),
    )


def build_bucket_health(closed_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate net-USD outcomes per bucket key."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in closed_rows:
        if not isinstance(row, dict):
            continue
        net = _net_usd(row)
        bps = _f(row.get("realized_pnl_bps")) or 0.0
        conf = _row_confidence(row)
        atr_stop = str(row.get("exit_reason") or row.get("close_reason") or "") == (
            "TIER_1_ATR_VOLATILITY_STOP"
        )
        hc_loss = (conf or 0.0) >= 0.70 and (bps < 0.0 or net < 0.0)
        for key in _row_bucket_keys(row):
            b = buckets.setdefault(
                key,
                {
                    "count": 0,
                    "wins": 0,
                    "losses": 0,
                    "gross_win_usd": 0.0,
                    "gross_loss_usd": 0.0,
                    "net_sum_usd": 0.0,
                    "notional_sum_usd": 0.0,
                    "high_confidence_loss_count": 0,
                    "atr_stop_count": 0,
                },
            )
            b["count"] += 1
            if net > 0:
                b["wins"] += 1
                b["gross_win_usd"] += net
            elif net < 0:
                b["losses"] += 1
                b["gross_loss_usd"] += abs(net)
            b["net_sum_usd"] += net
            b["notional_sum_usd"] += _f(row.get("gross_notional_usd")) or 0.0
            if hc_loss:
                b["high_confidence_loss_count"] += 1
            if atr_stop:
                b["atr_stop_count"] += 1
    for b in buckets.values():
        losses = b["gross_loss_usd"]
        b["profit_factor"] = (b["gross_win_usd"] / losses) if losses > 0 else (
            float("inf") if b["gross_win_usd"] > 0 else None
        )
        b["win_rate"] = b["wins"] / b["count"] if b["count"] else None
        b["notional_weighted_expectancy_bps"] = (
            b["net_sum_usd"] / b["notional_sum_usd"] * 10000
            if b["notional_sum_usd"] > 0
            else None
        )
        b["high_confidence_loss_rate"] = (
            b["high_confidence_loss_count"] / b["count"] if b["count"] else None
        )
        b["atr_stop_rate"] = b["atr_stop_count"] / b["count"] if b["count"] else None
    return buckets


def candidate_bucket_assessment(
    bucket_health: dict[str, dict[str, Any]],
    *,
    symbol: Any,
    side: Any,
    timeframe: Any,
    strategy_mode: Any,
    regime: Any,
    min_evidence_count: int = 3,
) -> dict[str, Any]:
    """Worst-of assessment over the candidate's buckets.

    A candidate is only as healthy as its weakest evidenced bucket.
    Buckets with fewer than min_evidence_count closes are 'insufficient
    evidence' rather than negative.
    """
    keys = candidate_bucket_keys(
        symbol=symbol, side=side, timeframe=timeframe,
        strategy_mode=strategy_mode, regime=regime,
    )
    matched = {k: bucket_health[k] for k in keys if k in bucket_health}
    negative = []
    insufficient = []
    worst_pf = None
    worst_expectancy = None
    hc_rates = []
    atr_rates = []
    for key, b in matched.items():
        pf = b.get("profit_factor")
        exp = b.get("notional_weighted_expectancy_bps")
        if b["count"] < min_evidence_count:
            insufficient.append(key)
            continue
        if pf is not None and pf != float("inf"):
            worst_pf = pf if worst_pf is None else min(worst_pf, pf)
        if exp is not None:
            worst_expectancy = exp if worst_expectancy is None else min(worst_expectancy, exp)
        if (pf is not None and pf != float("inf") and pf < 1.0) or (
            exp is not None and exp <= 0.0
        ):
            negative.append(key)
        if b.get("high_confidence_loss_rate") is not None:
            hc_rates.append(b["high_confidence_loss_rate"])
        if b.get("atr_stop_rate") is not None:
            atr_rates.append(b["atr_stop_rate"])
    return {
        "candidate_bucket_keys": keys,
        "evidenced_bucket_count": len(matched) - len(insufficient),
        "insufficient_evidence_buckets": insufficient,
        "negative_buckets": negative,
        "bucket_profit_factor": worst_pf,
        "notional_weighted_bucket_expectancy": worst_expectancy,
        "recent_high_confidence_loss_rate": max(hc_rates) if hc_rates else None,
        "recent_ATR_stop_risk": max(atr_rates) if atr_rates else None,
        "bucket_negative": bool(negative),
        "bucket_evidence_missing": len(matched) == 0 or (
            len(matched) == len(insufficient)
        ),
    }
