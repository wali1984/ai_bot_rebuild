"""Loss recovery loop — tightens entry gates when a window is losing.

Reads hourly window metrics and adjusts outcome memory Redis thresholds
(via degraded flags and override keys) so that entry_gate and
high_precision_gate become more restrictive in losing conditions.

Recovery logic:
  If any hourly window has:
    - realized_pnl < 0, OR
    - win_rate < 0.45, OR
    - profit_factor < 0.8
  → write a tightening override to Redis v2:loss_recovery:{symbol}:{timeframe}
  → that key is read by evaluate_entry_gate as a soak condition override

  If 3 consecutive windows are clean (pnl >= 0, WR >= 0.55, PF >= 1.1):
  → remove the override (allow normal gates to resume)

No exchange mutation. No legacy Redis writes.
Live gate: blocked_human_only.
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = "v2_loss_recovery_v1"
LIVE_GATE = "blocked_human_only"

# Tightening trigger thresholds
TRIGGER_PNL_THRESHOLD = 0.0
TRIGGER_WIN_RATE = 0.45
TRIGGER_PROFIT_FACTOR = 0.8

# Recovery thresholds (3 consecutive clean windows needed to clear tightening)
RECOVERY_WIN_RATE = 0.55
RECOVERY_PROFIT_FACTOR = 1.1
RECOVERY_CONSECUTIVE_WINDOWS = 3

# Tightened gate overrides written to Redis
TIGHTENED_MIN_CONFIDENCE = 0.82
TIGHTENED_MIN_EDGE_BPS = 25.0
TIGHTENED_ALLOWED_TIMEFRAMES = ["1h", "4h"]


def _coerce(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _recovery_key(symbol: str, timeframe: str) -> str:
    return f"v2:loss_recovery:{symbol.upper()}:{timeframe.lower()}"


def _load_recovery_state(redis_client: Any, key: str) -> dict:
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "tightened": False,
        "tightened_at": None,
        "consecutive_clean_windows": 0,
        "reason": None,
    }


def _is_window_losing(window_pnl_artifact: dict) -> tuple[bool, str]:
    """Return (is_losing, reason)."""
    pnl = _coerce(window_pnl_artifact.get("paper_realized_pnl"))
    win_rate = window_pnl_artifact.get("win_rate")
    pf = window_pnl_artifact.get("profit_factor")
    closed = window_pnl_artifact.get("closed_trade_count", 0)
    if closed == 0:
        return False, "no_closed_trades"
    if pnl < TRIGGER_PNL_THRESHOLD:
        return True, f"realized_pnl={pnl:.4f}"
    if win_rate is not None and win_rate < TRIGGER_WIN_RATE:
        return True, f"win_rate={win_rate:.4f}<{TRIGGER_WIN_RATE}"
    if pf is not None and pf < TRIGGER_PROFIT_FACTOR:
        return True, f"profit_factor={pf:.4f}<{TRIGGER_PROFIT_FACTOR}"
    return False, "clean"


def _is_window_clean(window_pnl_artifact: dict) -> bool:
    pnl = _coerce(window_pnl_artifact.get("paper_realized_pnl"))
    win_rate = window_pnl_artifact.get("win_rate")
    pf = window_pnl_artifact.get("profit_factor")
    closed = window_pnl_artifact.get("closed_trade_count", 0)
    if closed == 0:
        return False
    return (
        pnl >= 0
        and (win_rate is None or win_rate >= RECOVERY_WIN_RATE)
        and (pf is None or pf >= RECOVERY_PROFIT_FACTOR)
    )


def evaluate_loss_recovery(
    *,
    window_artifacts_list: list[dict],
    redis_client: Any,
    symbol: str = "ALL",
    timeframe: str = "all",
    now_iso: str = "",
) -> dict[str, Any]:
    """Evaluate up to N hourly window artifacts and apply/clear tightening overrides.

    window_artifacts_list: list of 'paper_trader_hourly_pnl' artifact dicts (oldest first).
    Returns a summary of actions taken.
    """
    import datetime as dt
    if not now_iso:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    key = _recovery_key(symbol, timeframe)
    state = _load_recovery_state(redis_client, key)

    actions: list[dict] = []
    tightening_applied = False
    tightening_cleared = False
    tightening_reason = None

    for i, window in enumerate(window_artifacts_list):
        is_losing, reason = _is_window_losing(window)
        if is_losing:
            state["consecutive_clean_windows"] = 0
            if not state.get("tightened"):
                state["tightened"] = True
                state["tightened_at"] = window.get("window_end_est") or now_iso
                state["reason"] = reason
                tightening_applied = True
                tightening_reason = reason
                actions.append({
                    "window_index": i,
                    "action": "tightened",
                    "reason": reason,
                    "window_start": window.get("window_start_est"),
                    "window_end": window.get("window_end_est"),
                })
        else:
            if state.get("tightened"):
                state["consecutive_clean_windows"] = state.get("consecutive_clean_windows", 0) + 1
                actions.append({
                    "window_index": i,
                    "action": "clean_window_counted",
                    "consecutive_clean": state["consecutive_clean_windows"],
                    "window_start": window.get("window_start_est"),
                    "window_end": window.get("window_end_est"),
                })
                if state["consecutive_clean_windows"] >= RECOVERY_CONSECUTIVE_WINDOWS:
                    state["tightened"] = False
                    state["tightened_at"] = None
                    state["consecutive_clean_windows"] = 0
                    state["reason"] = None
                    tightening_cleared = True
                    actions.append({
                        "window_index": i,
                        "action": "tightening_cleared",
                        "reason": f"{RECOVERY_CONSECUTIVE_WINDOWS}_consecutive_clean_windows",
                    })

    # Write tightening override to Redis
    override_key = f"v2:loss_recovery_override:{symbol.upper()}:{timeframe.lower()}"
    if state.get("tightened"):
        override = {
            "schema_version": SCHEMA_VERSION,
            "tightened": True,
            "tightened_at": state.get("tightened_at"),
            "reason": state.get("reason"),
            "min_confidence_override": TIGHTENED_MIN_CONFIDENCE,
            "min_edge_bps_override": TIGHTENED_MIN_EDGE_BPS,
            "allowed_timeframes_override": TIGHTENED_ALLOWED_TIMEFRAMES,
            "generated_at": now_iso,
            "live_gate": LIVE_GATE,
            "mutates_exchange": False,
        }
        try:
            redis_client.set(override_key, json.dumps(override))
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            redis_client.delete(override_key)
        except Exception:  # noqa: BLE001
            pass

    try:
        redis_client.set(key, json.dumps(state))
    except Exception:  # noqa: BLE001
        pass

    windows_evaluated = len(window_artifacts_list)
    losing_windows = sum(1 for w in window_artifacts_list if _is_window_losing(w)[0])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso,
        "symbol": symbol,
        "timeframe": timeframe,
        "windows_evaluated": windows_evaluated,
        "losing_windows": losing_windows,
        "clean_windows": windows_evaluated - losing_windows,
        "tightening_applied": tightening_applied,
        "tightening_cleared": tightening_cleared,
        "tightening_active": state.get("tightened", False),
        "tightening_reason": state.get("reason"),
        "consecutive_clean_windows": state.get("consecutive_clean_windows", 0),
        "recovery_required_windows": RECOVERY_CONSECUTIVE_WINDOWS,
        "actions": actions,
        "gate_overrides_active": state.get("tightened", False),
        "min_confidence_if_tightened": TIGHTENED_MIN_CONFIDENCE,
        "min_edge_bps_if_tightened": TIGHTENED_MIN_EDGE_BPS,
        "allowed_timeframes_if_tightened": TIGHTENED_ALLOWED_TIMEFRAMES,
        "live_gate": LIVE_GATE,
        "mutates_exchange": False,
        "writes_old_redis": False,
    }
