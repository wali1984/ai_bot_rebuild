"""
Canonical portfolio state publisher for trainer/trader contract.

Pushes fresh portfolio state into Redis hash `portfolio:state` (and optional stream)
on a cadence determined by the caller (recommend 1–2s). Use this from trader loops.
"""

import json
import time
from typing import Dict, Any, Iterable, Optional

try:
    from utils.redis_client import get_redis
except ImportError:
    get_redis = None  # type: ignore


def _serialize_positions(positions: Iterable[Dict[str, Any]]) -> str:
    """Serialize positions to JSON with safe fallbacks."""
    try:
        return json.dumps(list(positions))
    except Exception:
        return "[]"


def publish_portfolio_state(
    state: Dict[str, Any],
    redis_client=None,
    ttl_seconds: int = 30,
    stream: bool = True,
    account_id: str = "main",
) -> None:
    """
    Publish portfolio state to Redis for trainer consumption.

    Expected fields in `state` (caller responsibility):
      total_balance, available_balance, total_margin_used, margin_utilization_pct,
      unrealized_pnl, positions (list of dicts), position_count, source, mode (live),
      timestamp (epoch seconds)
    """
    rc = redis_client or (get_redis() if get_redis else None)
    if rc is None:
        return

    ts = state.get("timestamp", time.time())

    payload = {
        "total_balance": float(state.get("total_balance", 0.0)),
        "available_balance": float(state.get("available_balance", 0.0)),
        "total_margin_used": float(state.get("total_margin_used", 0.0)),
        "margin_utilization_pct": float(state.get("margin_utilization_pct", 0.0)),
        "unrealized_pnl": float(state.get("unrealized_pnl", 0.0)),
        "position_count": int(state.get("position_count", 0)),
        "positions": _serialize_positions(state.get("positions", [])),
        "source": state.get("source", "trader"),
        # Live-only system: force mode to "live".
        "mode": "live",
        "timestamp": ts,
        # Aliases for clarity in risk logic
        "equity_usd": float(
            state.get("equity_usd")
            or state.get("total_balance")
            or state.get("equity")
            or 0.0
        ),
        "available_margin_usd": float(
            state.get("available_margin_usd")
            or state.get("available_balance")
            or state.get("available_margin")
            or 0.0
        ),
        "used_margin_usd": float(state.get("used_margin_usd") or state.get("total_margin_used") or 0.0),
    }

    key = f"portfolio:state:{account_id}"
    try:
        rc.hset(key, mapping=payload)
        rc.expire(key, ttl_seconds)
        # pointer to active account (can be overridden elsewhere)
        rc.set("portfolio:state:active_account", account_id, ex=ttl_seconds)
        if stream:
            rc.xadd(
                f"portfolio:state:stream:{account_id}",
                {"data": json.dumps(payload)},
                maxlen=2000,
                approximate=True,
            )
    except Exception:
        return
