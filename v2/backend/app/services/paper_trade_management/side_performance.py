"""Side-level (LONG/SHORT) performance buckets, calibration, and trade gate.

Phase 2 of V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE.

The trainer's historical corpus is short-heavy (audit: 2701 short vs 632 long
labels; ~6.8% long signals). Class-weighted loss addresses the model side;
this module addresses the trading side:

- per-side PF / expectancy / win-rate buckets built from closed-trade
  trainer feedback rows of the CURRENT paper session only,
- per-side confidence calibration (Brier score, reliability bins),
- a side gate: a side whose bucket expectancy is <= 0 with enough evidence
  cannot open new paper entries; each side carries its own confidence floor.

Paper-only. Read-only against market state. Places no orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SIDE_PERFORMANCE_SCHEMA_VERSION = "paper_side_performance_v1"
SIDE_PERFORMANCE_REDIS_KEY = "v2:paper:side_performance"

SIDES = ("LONG", "SHORT")


@dataclass(frozen=True)
class SideGateConfig:
    # Evidence needed before a non-positive expectancy hard-blocks the side.
    # Below this the side keeps a viable (exploration) paper path.
    min_trades_for_expectancy_block: int = 8
    # Base confidence floors per side; poor calibration raises them.
    long_confidence_floor: float = 0.55
    short_confidence_floor: float = 0.55
    # Brier score above this adds a calibration penalty to the floor.
    calibration_brier_penalty_start: float = 0.25
    calibration_penalty_scale: float = 0.5
    max_confidence_floor: float = 0.80


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_side(row: Mapping[str, Any]) -> str | None:
    for key in ("side", "action", "selected_action"):
        raw = str(row.get(key) or "").strip().upper()
        if raw in SIDES:
            return raw
    return None


def _empty_bucket() -> dict[str, Any]:
    return {
        "trade_count": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "gross_profit_bps": 0.0,
        "gross_loss_bps": 0.0,
        "profit_factor": None,
        "expectancy_bps": None,
        "expectancy_usd": None,
        "net_pnl_usd": 0.0,
        "avg_win_bps": None,
        "avg_loss_bps": None,
        "avg_confidence": None,
        "brier_score": None,
        "calibration_bins": [],
        "trade_ids": [],
    }


def build_side_performance(
    feedback_rows: Iterable[Mapping[str, Any]],
    *,
    paper_session_id: str | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Aggregate closed-trade feedback rows into LONG/SHORT buckets."""
    buckets: dict[str, dict[str, Any]] = {side: _empty_bucket() for side in SIDES}
    pnl_by_side: dict[str, list[float]] = {side: [] for side in SIDES}
    usd_by_side: dict[str, list[float]] = {side: [] for side in SIDES}
    conf_outcome: dict[str, list[tuple[float, float]]] = {side: [] for side in SIDES}
    skipped = 0
    for row in feedback_rows:
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        if paper_session_id and str(row.get("paper_session_id") or "") != paper_session_id:
            skipped += 1
            continue
        if row.get("trainer_consumable") is not True:
            skipped += 1
            continue
        side = _row_side(row)
        pnl_bps = _finite(row.get("realized_net_pnl_bps"))
        if pnl_bps is None:
            pnl_bps = _finite(row.get("realized_pnl_bps"))
        if side is None or pnl_bps is None:
            skipped += 1
            continue
        bucket = buckets[side]
        bucket["trade_count"] += 1
        bucket["trade_ids"].append(
            str(row.get("trainer_feedback_id") or row.get("prediction_id") or "")
        )
        pnl_by_side[side].append(pnl_bps)
        pnl_usd = _finite(row.get("realized_pnl_usd")) or _finite(row.get("realized_net_pnl_usd"))
        if pnl_usd is not None:
            usd_by_side[side].append(pnl_usd)
        if pnl_bps > 0:
            bucket["wins"] += 1
            bucket["gross_profit_bps"] += pnl_bps
        else:
            bucket["losses"] += 1
            bucket["gross_loss_bps"] += abs(pnl_bps)
        confidence = _finite(row.get("confidence_calibrated"))
        if confidence is not None and 0.0 <= confidence <= 1.0:
            conf_outcome[side].append((confidence, 1.0 if pnl_bps > 0 else 0.0))

    for side in SIDES:
        bucket = buckets[side]
        count = bucket["trade_count"]
        if count > 0:
            bucket["win_rate"] = round(bucket["wins"] / count, 6)
            bucket["expectancy_bps"] = round(sum(pnl_by_side[side]) / count, 6)
            if usd_by_side[side]:
                bucket["expectancy_usd"] = round(
                    sum(usd_by_side[side]) / len(usd_by_side[side]), 6
                )
                bucket["net_pnl_usd"] = round(sum(usd_by_side[side]), 6)
            if bucket["gross_loss_bps"] > 0:
                bucket["profit_factor"] = round(
                    bucket["gross_profit_bps"] / bucket["gross_loss_bps"], 6
                )
            elif bucket["gross_profit_bps"] > 0:
                bucket["profit_factor"] = float("inf")
            wins = [p for p in pnl_by_side[side] if p > 0]
            losses = [p for p in pnl_by_side[side] if p <= 0]
            bucket["avg_win_bps"] = round(sum(wins) / len(wins), 6) if wins else None
            bucket["avg_loss_bps"] = round(sum(losses) / len(losses), 6) if losses else None
        pairs = conf_outcome[side]
        if pairs:
            bucket["avg_confidence"] = round(sum(c for c, _ in pairs) / len(pairs), 6)
            bucket["brier_score"] = round(
                sum((c - o) ** 2 for c, o in pairs) / len(pairs), 6
            )
            bins: list[dict[str, Any]] = []
            for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
                hi = lo + 0.2
                members = [(c, o) for c, o in pairs if lo <= c < hi or (hi == 1.0 and c == 1.0)]
                if members:
                    bins.append(
                        {
                            "bin": f"{lo:.1f}-{hi:.1f}",
                            "count": len(members),
                            "avg_confidence": round(sum(c for c, _ in members) / len(members), 6),
                            "win_rate": round(sum(o for _, o in members) / len(members), 6),
                        }
                    )
            bucket["calibration_bins"] = bins
        # JSON-safe profit factor
        if bucket["profit_factor"] == float("inf"):
            bucket["profit_factor_uncapped"] = "INF_NO_LOSSES"
            bucket["profit_factor"] = None
        bucket["trade_ids"] = bucket["trade_ids"][:50]

    return {
        "schema_version": SIDE_PERFORMANCE_SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "paper_session_id": paper_session_id,
        "sides": buckets,
        "rows_skipped": skipped,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
    }


def evaluate_side_gate(
    side_performance: Mapping[str, Any] | None,
    *,
    side: str | None,
    confidence_calibrated: float | None,
    config: SideGateConfig | None = None,
) -> dict[str, Any]:
    """Per-side trade gate.

    Hard rule: a side cannot open new entries when its bucket expectancy is
    <= 0 with at least min_trades_for_expectancy_block closed trades. Each
    side also carries its own confidence floor, raised when that side's
    calibration (Brier) is poor. A side with insufficient evidence keeps a
    viable exploration paper path (not blocked), flagged as such.
    """
    cfg = config or SideGateConfig()
    normalized = str(side or "").strip().upper()
    result: dict[str, Any] = {
        "side": normalized or None,
        "allowed": True,
        "reasons": [],
        "confidence_floor": None,
        "expectancy_bps": None,
        "profit_factor": None,
        "trade_count": 0,
        "exploration_path": False,
        "places_real_order": False,
    }
    if normalized not in SIDES:
        result["allowed"] = False
        result["reasons"].append(f"SIDE_UNKNOWN:{side}")
        return result
    bucket: Mapping[str, Any] = {}
    if isinstance(side_performance, Mapping):
        sides = side_performance.get("sides")
        if isinstance(sides, Mapping) and isinstance(sides.get(normalized), Mapping):
            bucket = sides[normalized]
    trade_count = int(bucket.get("trade_count") or 0)
    expectancy = _finite(bucket.get("expectancy_bps"))
    brier = _finite(bucket.get("brier_score"))
    result["trade_count"] = trade_count
    result["expectancy_bps"] = expectancy
    result["profit_factor"] = _finite(bucket.get("profit_factor"))

    floor = (
        cfg.long_confidence_floor if normalized == "LONG" else cfg.short_confidence_floor
    )
    if brier is not None and brier > cfg.calibration_brier_penalty_start:
        floor += (brier - cfg.calibration_brier_penalty_start) * cfg.calibration_penalty_scale
    floor = min(floor, cfg.max_confidence_floor)
    result["confidence_floor"] = round(floor, 6)

    if trade_count >= cfg.min_trades_for_expectancy_block and expectancy is not None and expectancy <= 0.0:
        result["allowed"] = False
        result["reasons"].append(
            f"SIDE_BUCKET_EXPECTANCY_NON_POSITIVE:{normalized}:{expectancy:.2f}bps:n={trade_count}"
        )
    if trade_count < cfg.min_trades_for_expectancy_block:
        result["exploration_path"] = True

    confidence = _finite(confidence_calibrated)
    if confidence is not None and confidence < floor:
        result["allowed"] = False
        result["reasons"].append(
            f"SIDE_CONFIDENCE_BELOW_FLOOR:{normalized}:{confidence:.3f}<{floor:.3f}"
        )
    return result
