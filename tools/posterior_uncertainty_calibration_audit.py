#!/usr/bin/env python3
"""Posterior-uncertainty / confidence calibration audit (operator directive #5).

READ-ONLY. Audits whether the model's confidence/uncertainty is empirically
calibrated against realized, authenticated paper closes — to distinguish:

  (A) model is well-calibrated & genuinely sees no edge  -> exploration correctly
      declines; the blocker is real (no opportunity), fix is the trainer/edge.
  (B) model is over-confident / uncertainty under-dispersed -> a calibration
      defect is suppressing exploration; recalibrate uncertainty from held-out
      residuals (NOT by an arbitrary multiplier).

Counterfactual / non-executed rows are excluded (no counterfactual counted as
realized execution profit). Uses only v2:paper:closed_trades authenticated closes.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

import redis


def _r():
    return redis.Redis(decode_responses=True)


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def audit() -> dict:
    r = _r()
    ct = json.loads(r.get("v2:paper:closed_trades") or "[]")
    rows = []
    for t in ct:
        if not isinstance(t, dict):
            continue
        # exclude counterfactual / non-executed rows
        if t.get("counterfactual_counts_as_realized_paper_profit") is True:
            continue
        conf = _f(t.get("confidence_calibrated"))
        conf_raw = _f(t.get("confidence_raw"))
        exp = _f(t.get("expected_move_after_cost_bps"))
        realized = _f(t.get("realized_pnl_bps"))
        if realized is None:
            continue
        rows.append({
            "conf": conf, "conf_raw": conf_raw, "exp": exp, "realized": realized,
            "mae": _f(t.get("mae_bps")), "mfe": _f(t.get("mfe_bps")),
            "side": str(t.get("side") or "?").lower(),
            "tf": str(t.get("timeframe") or "?"),
            "regime": str(t.get("market_regime_at_entry") or "?"),
            "win": 1 if realized > 0 else 0,
            "dir_correct": (1 if (exp is not None and ((exp > 0) == (realized > 0))) else 0) if exp is not None else None,
        })
    n = len(rows)
    if n == 0:
        return {"error": "no authenticated closes"}

    # 1. Reliability: calibrated confidence bucket -> realized win rate
    buckets = defaultdict(list)
    for x in rows:
        if x["conf"] is None:
            continue
        b = min(9, int(x["conf"] * 10))
        buckets[b].append(x["win"])
    reliability = []
    ece = 0.0  # expected calibration error
    for b in sorted(buckets):
        wins = buckets[b]
        conf_mid = (b + 0.5) / 10.0
        emp = sum(wins) / len(wins)
        reliability.append({"conf_bucket": f"{b/10:.1f}-{(b+1)/10:.1f}", "n": len(wins),
                            "predicted_conf": round(conf_mid, 3), "realized_win_rate": round(emp, 3),
                            "gap": round(emp - conf_mid, 3)})
        ece += (len(wins) / n) * abs(emp - conf_mid)

    # 2. Aggregate over/under-confidence
    confs = [x["conf"] for x in rows if x["conf"] is not None]
    mean_conf = sum(confs) / len(confs) if confs else None
    win_rate = sum(x["win"] for x in rows) / n
    dir_rows = [x for x in rows if x["dir_correct"] is not None]
    dir_acc = (sum(x["dir_correct"] for x in dir_rows) / len(dir_rows)) if dir_rows else None

    # 3. Expected vs realized move: does expected_move predict realized?
    paired = [(x["exp"], x["realized"]) for x in rows if x["exp"] is not None]
    exp_vs_real = None
    if len(paired) >= 3:
        ex = [p[0] for p in paired]; re_ = [p[1] for p in paired]
        mex = sum(ex) / len(ex); mre = sum(re_) / len(re_)
        cov = sum((a - mex) * (b - mre) for a, b in paired) / len(paired)
        vex = sum((a - mex) ** 2 for a in ex) / len(ex)
        vre = sum((b - mre) ** 2 for b in re_) / len(re_)
        corr = cov / math.sqrt(vex * vre) if vex > 0 and vre > 0 else 0.0
        # realized dispersion vs the tiny posterior uncertainty implied
        exp_vs_real = {"n": len(paired), "mean_expected_bps": round(mex, 2),
                       "mean_realized_bps": round(mre, 2), "corr_expected_realized": round(corr, 4),
                       "realized_std_bps": round(math.sqrt(vre), 2)}

    # 4. Breakdown by side/timeframe/regime
    def breakdown(keyfn):
        g = defaultdict(list)
        for x in rows:
            g[keyfn(x)].append(x)
        out = {}
        for k, xs in sorted(g.items()):
            wr = sum(x["win"] for x in xs) / len(xs)
            mc = [x["conf"] for x in xs if x["conf"] is not None]
            out[k] = {"n": len(xs), "win_rate": round(wr, 3),
                      "mean_conf": round(sum(mc) / len(mc), 3) if mc else None,
                      "mean_realized_bps": round(sum(x["realized"] for x in xs) / len(xs), 2)}
        return out

    # effective independent sample size (naive: distinct symbols x sessions is not
    # tracked here; report raw n and unique regimes/timeframes as a coarse proxy)
    verdict = {
        "schema": "posterior_uncertainty_calibration_audit_v1",
        "paper_only": True, "live_gate": "blocked_human_only",
        "n_authenticated_closes": n,
        "aggregate": {
            "mean_calibrated_confidence": round(mean_conf, 3) if mean_conf else None,
            "realized_win_rate": round(win_rate, 3),
            "directional_accuracy_vs_expected_sign": round(dir_acc, 3) if dir_acc is not None else None,
            "expected_calibration_error_ece": round(ece, 3),
            "overconfidence_gap": round((mean_conf - win_rate), 3) if mean_conf else None,
        },
        "reliability_diagram": reliability,
        "expected_vs_realized": exp_vs_real,
        "by_timeframe": breakdown(lambda x: x["tf"]),
        "by_side": breakdown(lambda x: x["side"]),
        "diagnosis": None,
    }
    # diagnosis
    oc = verdict["aggregate"]["overconfidence_gap"]
    if oc is not None and oc > 0.05:
        diag = ("OVER_CONFIDENT: mean calibrated confidence exceeds realized win rate by "
                f"{oc:.3f} (>0.05). Uncertainty is UNDER-dispersed -> a calibration defect plausibly "
                "suppresses exploration (posterior_uncertainty too small). Recalibrate from held-out residuals.")
    elif oc is not None and oc < -0.05:
        diag = ("UNDER_CONFIDENT: realized win rate exceeds confidence; uncertainty over-dispersed.")
    else:
        diag = ("WELL_CALIBRATED_AGGREGATE: confidence ~ realized win rate (|gap|<=0.05). If exploration still "
                "declines, the model genuinely sees low edge/uncertainty -> the blocker is real edge, not a "
                "calibration defect. Confirm with per-bucket ECE and directional accuracy.")
    verdict["diagnosis"] = diag
    return verdict


def main(argv):
    v = audit()
    from pathlib import Path
    ev = Path(__file__).resolve().parents[1] / "raw_evidence" / "posterior_uncertainty_calibration_audit.json"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n")
    print(json.dumps(v, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
