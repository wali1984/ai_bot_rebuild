"""Read-only regime and directional-bias mining for Phase 3 recovery."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping


SCHEMA_VERSION = "phase3_regime_miscalibration_miner_v1"
DEFAULT_MIN_BUCKET_SAMPLES = 2


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _realized_bps(row: Mapping[str, Any]) -> float | None:
    for key in (
        "realized_after_cost_return_bps",
        "realized_net_pnl_bps",
        "realized_pnl_bps",
        "pnl_effect_bps",
    ):
        value = _float(row.get(key))
        if value is not None:
            return value
    outcome = _as_dict(_as_dict(row.get("outcome_windows")).get(row.get("primary_outcome_window") or "5m"))
    return _float(outcome.get("after_cost_return_bps"))


def _side(row: Mapping[str, Any]) -> str:
    side = str(row.get("counterfactual_side") or row.get("selected_action") or row.get("side") or "").lower()
    return side if side in {"long", "short"} else "unknown"


def _regime(row: Mapping[str, Any]) -> str:
    return str(
        row.get("market_regime")
        or row.get("market_regime_at_entry")
        or row.get("strategy_market_regime")
        or "UNKNOWN"
    )


def _strategy(row: Mapping[str, Any]) -> str:
    return str(
        row.get("strategy_id")
        or row.get("strategy_mode")
        or row.get("strategy_family")
        or "UNKNOWN"
    )


def _bucket_values(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    values = [value for value in (_realized_bps(row) for row in rows) if value is not None]
    wins = [value for value in values if value > 0.0]
    losses = [value for value in values if value < 0.0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "sample_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "expectancy_bps": sum(values) / len(values) if values else None,
        "profit_factor": (
            None if not values else "INF" if gross_loss == 0.0 and gross_win > 0.0 else gross_win / gross_loss if gross_loss else 0.0
        ),
    }


def _summaries(
    rows: list[Mapping[str, Any]],
    *,
    key_fields: tuple[str, ...],
    min_bucket_samples: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key_parts: list[str] = []
        for field in key_fields:
            if field == "regime":
                key_parts.append(_regime(row))
            elif field == "strategy":
                key_parts.append(_strategy(row))
            elif field == "side":
                key_parts.append(_side(row))
            else:
                key_parts.append(str(row.get(field) or "UNKNOWN"))
        grouped[tuple(key_parts)].append(row)
    out: list[dict[str, Any]] = []
    for key, bucket_rows in sorted(grouped.items()):
        metrics = _bucket_values(bucket_rows)
        expectancy = _float(metrics.get("expectancy_bps"))
        sample_count = int(metrics.get("sample_count") or 0)
        negative_bucket = (
            sample_count >= min_bucket_samples
            and expectancy is not None
            and expectancy <= 0.0
        )
        out.append(
            {
                "bucket": "|".join(key),
                "key_fields": list(key_fields),
                **metrics,
                "negative_bucket": negative_bucket,
                "quarantine_recommended": negative_bucket,
                "quarantine_reason": (
                    "NEGATIVE_EXPECTANCY_BUCKET" if negative_bucket else None
                ),
            }
        )
    return out


def mine_regime_miscalibration(
    rows: list[Mapping[str, Any]],
    *,
    min_bucket_samples: int = DEFAULT_MIN_BUCKET_SAMPLES,
) -> dict[str, Any]:
    normalized = [_as_dict(row) for row in rows]
    completed = [row for row in normalized if _realized_bps(row) is not None]
    regime_buckets = _summaries(
        completed,
        key_fields=("regime",),
        min_bucket_samples=min_bucket_samples,
    )
    strategy_regime_buckets = _summaries(
        completed,
        key_fields=("strategy", "regime"),
        min_bucket_samples=min_bucket_samples,
    )
    side_buckets = _summaries(
        completed,
        key_fields=("side",),
        min_bucket_samples=min_bucket_samples,
    )
    timeframe_buckets = _summaries(
        completed,
        key_fields=("timeframe",),
        min_bucket_samples=min_bucket_samples,
    )
    negative = [
        bucket
        for bucket in [*regime_buckets, *strategy_regime_buckets, *side_buckets, *timeframe_buckets]
        if bucket.get("negative_bucket") is True
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "REGIME_MISCALIBRATION_MINING_READY",
        "row_count": len(normalized),
        "completed_outcome_count": len(completed),
        "min_bucket_samples": min_bucket_samples,
        "regime_buckets": regime_buckets,
        "strategy_regime_buckets": strategy_regime_buckets,
        "side_buckets": side_buckets,
        "timeframe_buckets": timeframe_buckets,
        "negative_bucket_count": len(negative),
        "negative_buckets": negative,
        "long_viable": any(
            bucket.get("bucket") == "long"
            and (_float(bucket.get("expectancy_bps")) or 0.0) > 0.0
            for bucket in side_buckets
        ),
        "short_viable": any(
            bucket.get("bucket") == "short"
            and (_float(bucket.get("expectancy_bps")) or 0.0) > 0.0
            for bucket in side_buckets
        ),
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }
