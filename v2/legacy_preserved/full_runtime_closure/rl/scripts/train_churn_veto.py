#!/usr/bin/env python3
"""
Train Churn Veto (Option 3) from Redis history.

Outputs: models/churn_veto.json

This script is intentionally dependency-free (no sklearn). It trains a tiny
logistic regression model via batch gradient descent over simple features.

Dataset (best-effort, forward-compatible):
- Reads entry-like signals from per-account signal streams.
- Uses features embedded in the signal payload (toxicity + microstructure fields),
  and labels churn_bad from subsequent short-horizon behavior when available.

Important:
- Historical data may not include toxicity/micro fields until the new pipeline is running.
  In that case this script will warn and emit the default heuristic model.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import redis


FEATURES = ["confidence", "toxicity", "spread_norm", "fast_move", "churn", "snapback", "entropy"]


def _sigmoid(z: float) -> float:
    try:
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)
    except Exception:
        return 0.5


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return max(0.0, min(1.0, float(x)))


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _extract_features(sig: Dict) -> Dict[str, float]:
    conf = _f(sig.get("model_confidence", sig.get("confidence", 0.0)), 0.0)
    if conf > 1.0:
        conf /= 100.0
    conf = _clamp01(conf)

    tox = _clamp01(_f(sig.get("toxicity", 0.0), 0.0))
    spread = _f(sig.get("spread_bps", sig.get("spread", 0.0)), 0.0)
    spread_norm = _clamp01(spread / 20.0) if spread > 0 else 0.0

    micro = sig.get("micro") if isinstance(sig.get("micro"), dict) else {}
    fast = _clamp01(_f(sig.get("fast_move_score", micro.get("fast_move_score", 0.0)), 0.0))
    churn = _clamp01(_f(sig.get("churn_score", micro.get("churn_score", 0.0)), 0.0))
    snap = _clamp01(_f(sig.get("snapback_score", micro.get("snapback_score", 0.0)), 0.0))
    ent = _clamp01(_f(sig.get("entropy", 0.0), 0.0))

    return {
        "confidence": conf,
        "toxicity": tox,
        "spread_norm": spread_norm,
        "fast_move": fast,
        "churn": churn,
        "snapback": snap,
        "entropy": ent,
    }


def _dot(w: Dict[str, float], x: Dict[str, float], b: float) -> float:
    z = float(b)
    for k in FEATURES:
        z += float(w.get(k, 0.0)) * float(x.get(k, 0.0))
    return z


def _read_stream_json(rc: redis.Redis, stream: str, start_ms: int, max_count: int = 80000) -> List[Dict]:
    out: List[Dict] = []
    rows = rc.xrevrange(stream, count=max_count)
    for sid, fields in rows:
        ts = int(str(sid).split("-", 1)[0])
        if ts < start_ms:
            break
        raw = fields.get("data") or "{}"
        try:
            p = json.loads(raw)
        except Exception:
            continue
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0, help="Lookback window for training samples")
    ap.add_argument("--lr", type=float, default=0.3, help="Learning rate")
    ap.add_argument("--epochs", type=int, default=120, help="Epochs")
    ap.add_argument("--out", type=str, default="rl/churn_veto_trained.json", help="Output model path")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    rc = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - int(args.hours * 3600 * 1000)

    # Read per-account signal streams (best-effort)
    streams = ["signals:trading:primary", "signals:trading:asjad"]
    signals: List[Dict] = []
    for s in streams:
        try:
            signals.extend(_read_stream_json(rc, s, start_ms))
        except Exception:
            pass

    # Filter entry-like signals; focus on timing entries if present
    entry = []
    for sig in signals:
        a = str(sig.get("action_name") or sig.get("action") or "").upper()
        if not a:
            continue
        if any(tok in a for tok in ("OPEN_", "INCREASE_", "CLOSE_SHORT_AND_OPEN_LONG", "CLOSE_LONG_AND_OPEN_SHORT")):
            entry.append(sig)
    if not entry:
        print("No entry-like signals found in window; writing default heuristic model.")
        model = {
            "weights": {"confidence": -2.0, "toxicity": 3.0, "spread_norm": 2.0, "fast_move": 0.7, "churn": 1.2, "snapback": 1.2, "entropy": 0.8},
            "bias": 0.0,
            "meta": {"trained": False, "reason": "no_samples", "hours": args.hours, "features": FEATURES},
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(model, f, indent=2)
        print(f"Wrote {args.out}")
        return 0

    # Labels (best-effort):
    # If signal includes explicit outcome fields from future telemetry, use them.
    # Otherwise we default to "unknown" and train only when labels exist.
    X: List[Dict[str, float]] = []
    Y: List[int] = []
    for sig in entry:
        y = sig.get("churn_bad")
        if y is None:
            continue
        yv = 1 if bool(y) else 0
        X.append(_extract_features(sig))
        Y.append(yv)

    if len(X) < 50:
        print(f"Not enough labeled samples ({len(X)}). Writing default heuristic model; run again after telemetry accumulates.")
        model = {
            "weights": {"confidence": -2.0, "toxicity": 3.0, "spread_norm": 2.0, "fast_move": 0.7, "churn": 1.2, "snapback": 1.2, "entropy": 0.8},
            "bias": 0.0,
            "meta": {"trained": False, "reason": "insufficient_labels", "labeled": len(X), "hours": args.hours, "features": FEATURES},
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(model, f, indent=2)
        print(f"Wrote {args.out}")
        return 0

    # Initialize weights
    w = {k: 0.0 for k in FEATURES}
    b = 0.0

    lr = float(args.lr)
    for epoch in range(int(args.epochs)):
        # Full-batch gradient
        gw = {k: 0.0 for k in FEATURES}
        gb = 0.0
        loss = 0.0
        n = len(X)
        for x, y in zip(X, Y):
            z = _dot(w, x, b)
            p = _sigmoid(z)
            # logistic loss
            p = min(max(p, 1e-6), 1.0 - 1e-6)
            loss += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            dz = (p - y)
            for k in FEATURES:
                gw[k] += dz * float(x.get(k, 0.0))
            gb += dz
        # Update
        for k in FEATURES:
            w[k] -= lr * (gw[k] / n)
        b -= lr * (gb / n)

        if epoch % 20 == 0:
            print(f"epoch={epoch} loss={(loss/n):.4f}")

    model = {
        "weights": w,
        "bias": b,
        "meta": {"trained": True, "labeled": len(X), "hours": args.hours, "features": FEATURES, "ts_ms": int(time.time() * 1000)},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

