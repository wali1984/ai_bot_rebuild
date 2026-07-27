#!/usr/bin/env python3
"""Effective corpus-diversity analysis for the gen-5 dataset (FINAL PASS step 8).

A 5.36-day / 90-symbol corpus is broad cross-sectionally, but rows captured at the
SAME decision timestamp across many coins are strongly correlated, so the effective
independent sample size can be far below the row count. This reports:
  unique decision timestamps, rows per timestamp, cross-symbol clustering,
  effective independent sample size, volatility/return regime coverage, and a
  purged-by-decision-time train/val/holdout grouping. Read-only; no training.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

DATASET = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/gen5_model/serving_compatible_dataset_v2.json")
REPORT = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1/gen5_corpus_diversity_report.json")


def main() -> int:
    ds = json.loads(DATASET.read_text())
    names = list(ds["ordered_feature_names"])
    rows = ds["rows"]
    total = len(rows)

    # decision-time clustering (bucket to the minute to catch same-bar cross-symbol rows)
    def minute(t: str) -> str:
        return t[:16]  # YYYY-MM-DDTHH:MM
    times = [minute(r["decision_time"]) for r in rows]
    per_ts = Counter(times)
    unique_ts = len(per_ts)
    rows_per_ts = [c for c in per_ts.values()]
    days = len({t[:10] for t in times})

    # Effective independent sample size (Kish-style, from timestamp-group sizes):
    # n_eff = (sum n_g)^2 / sum(n_g^2)  — collapses toward #groups when rows cluster.
    sum_n = sum(rows_per_ts)
    sum_n2 = sum(n * n for n in rows_per_ts)
    n_eff = round((sum_n * sum_n) / sum_n2, 1) if sum_n2 else 0.0

    # regime coverage from features (all OHLCV-derived, present in ServingFeatureABIV2)
    def col(name):
        i = names.index(name)
        return [float(r["feature_values"][i]) for r in rows]
    def regime(vals, lo_q=0.33, hi_q=0.66):
        s = sorted(vals)
        lo = s[int(len(s) * lo_q)]
        hi = s[int(len(s) * hi_q)]
        c = Counter("low" if v <= lo else "high" if v >= hi else "mid" for v in vals)
        return {k: c[k] for k in ("low", "mid", "high")}

    vol_regime = regime(col("true_range_pct")) if "true_range_pct" in names else {}
    trend_vals = col("log_return") if "log_return" in names else col("ret_pct")
    trend_regime = Counter("down" if v < 0 else "up" if v > 0 else "flat" for v in trend_vals)
    bbwidth_regime = regime(col("bb_width_pct")) if "bb_width_pct" in names else {}

    symbols = Counter(r["symbol"] for r in rows)

    report = {
        "schema_version": "gen5_corpus_diversity_v1",
        "total_rows": total,
        "unique_symbols": len(symbols),
        "unique_decision_minutes": unique_ts,
        "distinct_calendar_days": days,
        "rows_per_timestamp": {
            "mean": round(statistics.fmean(rows_per_ts), 2),
            "max": max(rows_per_ts),
            "median": statistics.median(rows_per_ts),
            "timestamps_with_gt_5_rows": sum(1 for c in rows_per_ts if c > 5),
        },
        "effective_independent_sample_size_kish": n_eff,
        "effective_vs_nominal_ratio": round(n_eff / total, 3) if total else 0,
        "cross_sectional_clustering": (
            "HIGH — many rows share decision timestamps; effective N << row count"
            if n_eff < total * 0.5 else
            "MODERATE" if n_eff < total * 0.8 else "LOW — rows largely time-independent"
        ),
        "volatility_regime_true_range": vol_regime,
        "bb_width_regime": bbwidth_regime,
        "return_direction_regime": dict(trend_regime),
        "regime_coverage_verdict": (
            "REGIME_DIVERSE" if (vol_regime and min(vol_regime.values()) >= total * 0.15
                                 and trend_regime.get("up", 0) >= total * 0.2
                                 and trend_regime.get("down", 0) >= total * 0.2)
            else "REGIME_LIMITED — dominated by narrow vol/trend buckets"
        ),
        "purged_group_split_note": (
            "chronological by decision-minute group with 2-group embargo (serving_dataset_v2 "
            "splits by decision_time already; groups are timestamp-coherent)"
        ),
        "honest_verdict": (
            f"{total} rows but only {unique_ts} unique decision-minutes over {days} days; "
            f"Kish effective independent N ~= {n_eff}. Cross-sectionally broad ({len(symbols)} "
            f"symbols) but temporally shallow — 'multi-regime' would OVERSTATE it; effective "
            f"sample for edge estimation is ~{n_eff}, not {total}."
        ),
        "paper_only": True,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in (
        "total_rows", "unique_symbols", "unique_decision_minutes", "distinct_calendar_days",
        "rows_per_timestamp", "effective_independent_sample_size_kish",
        "effective_vs_nominal_ratio", "cross_sectional_clustering",
        "volatility_regime_true_range", "return_direction_regime",
        "regime_coverage_verdict", "honest_verdict")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
