#!/usr/bin/env python3
"""
Counterfactual Capital Sweep — V2 Guardian Gate G11

Tests whether the system's capital allocation logic produces positive
expected outcomes across a range of starting capital scenarios.

Evidence type: raw Redis data + deterministic arithmetic.
No real orders. No exchange mutations. Paper-only.

Gate passes when:
  - At least 3 capital scenarios tested
  - All scenarios show positive after-cost expectancy
  - No scenario produces > 50% max drawdown
  - Results written to COUNTERFACTUAL_CAPITAL_SWEEP_RESULTS.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import redis as redis_lib
    r = redis_lib.Redis(decode_responses=True)
    r.ping()
    REDIS_OK = True
except Exception:
    REDIS_OK = False
    r = None

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
STATE_DIR = ROOT / "goal_state" / (
    "V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_"
    "AND_CAPITAL_PRODUCTIVITY_GUARDIAN"
)

NOW = datetime.now(timezone.utc).isoformat()


def rget(key: str):
    if not REDIS_OK or r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def simulate_equity_curve(
    trades: list[dict],
    starting_capital: float,
    capital_fraction: float,
) -> dict:
    """
    Simulate equity curve using a fixed fraction of capital per trade.
    capital_fraction: fraction of equity risked per trade (e.g. 0.01 = 1%)
    Returns: equity stats for this scenario.
    """
    equity = starting_capital
    peak = equity
    max_dd = 0.0
    winners = 0
    losers = 0
    total_pnl = 0.0
    gross_wins = 0.0
    gross_losses = 0.0

    for t in trades:
        pnl_bps = float(t.get("realized_pnl_bps") or 0)
        # Scale pnl to capital_fraction allocation per trade
        allocated = equity * capital_fraction
        # pnl_bps is against notional; with 1x leverage allocated = notional
        trade_pnl = allocated * pnl_bps / 10000.0
        equity += trade_pnl
        total_pnl += trade_pnl

        if trade_pnl > 0:
            winners += 1
            gross_wins += trade_pnl
        else:
            losers += 1
            gross_losses += abs(trade_pnl)

        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    n = len(trades)
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")
    mean_pnl_bps = sum(float(t.get("realized_pnl_bps") or 0) for t in trades) / n if n > 0 else 0
    cagr_proxy = (equity / starting_capital - 1) * 100 if starting_capital > 0 else 0

    return {
        "starting_capital": starting_capital,
        "capital_fraction": capital_fraction,
        "ending_capital": equity,
        "total_pnl": total_pnl,
        "mean_pnl_bps": mean_pnl_bps,
        "max_drawdown_pct": max_dd,
        "profit_factor": profit_factor,
        "win_rate": winners / n if n > 0 else 0,
        "winners": winners,
        "losers": losers,
        "total_trades": n,
        "cagr_proxy_pct": cagr_proxy,
        "expectancy_positive": mean_pnl_bps > 0,
        "drawdown_within_limit": max_dd < 50.0,
    }


def run_sweep(trades: list[dict]) -> dict:
    if not trades:
        return {"error": "No closed trades available for sweep"}

    scenarios = [
        {"starting_capital": 1000.0, "capital_fraction": 0.05, "label": "1k_5pct"},
        {"starting_capital": 5000.0, "capital_fraction": 0.03, "label": "5k_3pct"},
        {"starting_capital": 10000.0, "capital_fraction": 0.02, "label": "10k_2pct"},
        {"starting_capital": 10000.0, "capital_fraction": 0.01, "label": "10k_1pct"},
        {"starting_capital": 50000.0, "capital_fraction": 0.01, "label": "50k_1pct"},
    ]

    results = []
    for sc in scenarios:
        result = simulate_equity_curve(
            trades=trades,
            starting_capital=sc["starting_capital"],
            capital_fraction=sc["capital_fraction"],
        )
        result["label"] = sc["label"]
        results.append(result)
        icon = "PASS" if result["expectancy_positive"] and result["drawdown_within_limit"] else "FAIL"
        print(f"  [{icon}] {sc['label']}: mean={result['mean_pnl_bps']:.2f}bps "
              f"pf={result['profit_factor']:.2f} dd={result['max_drawdown_pct']:.1f}% "
              f"final={result['ending_capital']:.0f}")

    all_pass = all(r["expectancy_positive"] and r["drawdown_within_limit"] for r in results)
    n_pass = sum(1 for r in results if r["expectancy_positive"] and r["drawdown_within_limit"])

    return {
        "sweep_type": "counterfactual_capital_allocation",
        "scenarios_tested": len(scenarios),
        "scenarios_passed": n_pass,
        "status": "PASS" if all_pass else "FAIL",
        "pass_criteria": "all scenarios: mean_pnl_bps > 0 AND max_drawdown < 50%",
        "trade_count": len(trades),
        "results": results,
        "run_utc": NOW,
    }


print("=" * 60)
print("Counterfactual Capital Sweep — V2 Guardian G11")
print(f"Run: {NOW}")
print("=" * 60)

if not REDIS_OK:
    print("ERROR: Redis unavailable")
    sys.exit(1)

closed_trades = rget("v2:paper:closed_trades") or []
if not isinstance(closed_trades, list):
    closed_trades = []

print(f"Loaded {len(closed_trades)} closed trades from v2:paper:closed_trades")
print()

sweep = run_sweep(closed_trades)

out_path = STATE_DIR / "COUNTERFACTUAL_CAPITAL_SWEEP_RESULTS.json"
out_path.write_text(json.dumps(sweep, indent=2) + "\n")

print()
print(f"Status: {sweep['status']}")
print(f"Scenarios: {sweep['scenarios_passed']}/{sweep['scenarios_tested']} pass")
print(f"Results written to {out_path}")

sys.exit(0 if sweep["status"] == "PASS" else 1)
