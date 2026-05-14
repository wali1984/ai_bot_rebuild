"""
Contract Enrichment Module
==========================
Adds required contract fields to signal payloads for auditability.

Fields added:
- intent: Action intent classification
- close_reason_code / hedge_reason_code
- roe_pct, mfe_pct, mae_pct
- hot_monitor: 1 when 1m/5m lane is active

Implements Addendum D: Contract and Telemetry Requirements

Author: WMA AI Trading System
Date: December 24, 2025
"""

import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class IntentCode:
    """Action intent classification codes."""
    ENTRY = "ENTRY"
    MANAGE_PROFIT = "MANAGE_PROFIT"
    MANAGE_LOSS = "MANAGE_LOSS"
    HEDGE_OPEN = "HEDGE_OPEN"
    HEDGE_SCALE = "HEDGE_SCALE"
    HEDGE_UNWIND = "HEDGE_UNWIND"
    EXIT_EMERGENCY = "EXIT_EMERGENCY"
    EXIT_NORMAL = "EXIT_NORMAL"
    FLIP = "FLIP"
    REBALANCE = "REBALANCE"
    HOLD = "HOLD"


def classify_intent(action_name: str, roe_pct: float = 0.0, is_emergency: bool = False) -> str:
    """
    Classify action intent based on action name and context.
    
    Args:
        action_name: The action name (e.g., "OPEN_LONG", "PARTIAL_CLOSE")
        roe_pct: Current ROE percentage for the position
        is_emergency: Whether this is an emergency action
        
    Returns:
        Intent code string
    """
    action_upper = action_name.upper()
    
    # Emergency takes precedence
    if is_emergency:
        return IntentCode.EXIT_EMERGENCY
    
    # Hedge actions
    if "HEDGE" in action_upper:
        if "OPEN" in action_upper:
            return IntentCode.HEDGE_OPEN
        elif "SCALE" in action_upper:
            return IntentCode.HEDGE_SCALE
        elif "UNWIND" in action_upper or "CLOSE" in action_upper:
            return IntentCode.HEDGE_UNWIND
        return IntentCode.HEDGE_OPEN
    
    # Entry actions
    if any(x in action_upper for x in ["OPEN_LONG", "OPEN_SHORT"]):
        return IntentCode.ENTRY
    
    # Flip actions
    if any(x in action_upper for x in ["FLIP", "CLOSE_AND_LONG", "CLOSE_AND_SHORT"]):
        return IntentCode.FLIP
    
    # Profit/loss management (partial close, decrease)
    if any(x in action_upper for x in ["PARTIAL", "DECREASE"]):
        if roe_pct >= 0:
            return IntentCode.MANAGE_PROFIT
        else:
            return IntentCode.MANAGE_LOSS
    
    # Full close
    if any(x in action_upper for x in ["CLOSE_LONG", "CLOSE_SHORT", "CLOSE"]):
        return IntentCode.EXIT_NORMAL
    
    # Increase position
    if "INCREASE" in action_upper:
        return IntentCode.ENTRY
    
    # Hold/no action
    if any(x in action_upper for x in ["HOLD", "NO_ACTION", "WAIT"]):
        return IntentCode.HOLD
    
    # Rebalancing
    if "REBALANCE" in action_upper:
        return IntentCode.REBALANCE
    
    return IntentCode.ENTRY


def enrich_payload_with_contract(
    payload: Dict[str, Any],
    position_tracker: Optional[Any] = None,
    is_emergency: bool = False,
    is_hot_monitor: bool = False
) -> Dict[str, Any]:
    """
    Enrich a signal payload with required contract fields.
    
    Args:
        payload: Original signal payload
        position_tracker: PositionTracker from dynamic_runner_hedge module
        is_emergency: Whether this is an emergency action
        is_hot_monitor: Whether hot monitor lane is active
        
    Returns:
        Enriched payload with contract fields
    """
    action_name = str(payload.get("action_name") or payload.get("action") or "")
    
    # Get ROE from tracker or payload
    roe_pct = 0.0
    mfe_pct = 0.0
    mae_pct = 0.0
    
    if position_tracker:
        roe_pct = getattr(position_tracker, 'roe_pct', 0.0)
        mfe_pct = getattr(position_tracker, 'mfe_pct', 0.0)
        mae_pct = getattr(position_tracker, 'mae_pct', 0.0)
        is_hot_monitor = is_hot_monitor or getattr(position_tracker, 'hot_monitor_active', False)
    else:
        # Try to get from payload
        roe_pct = float(payload.get('roe_pct', 0))
        mfe_pct = float(payload.get('mfe_pct', 0))
        mae_pct = float(payload.get('mae_pct', 0))
    
    # Classify intent
    intent = classify_intent(action_name, roe_pct, is_emergency)
    
    # Add contract fields
    payload['intent'] = intent
    payload['roe_pct'] = round(roe_pct, 2)
    payload['mfe_pct'] = round(mfe_pct, 2)
    payload['mae_pct'] = round(mae_pct, 2)
    payload['hot_monitor'] = 1 if is_hot_monitor else 0
    
    # Close/hedge reason codes (may already be set)
    if 'close_reason_code' not in payload:
        if "CLOSE" in action_name.upper() and intent != IntentCode.EXIT_EMERGENCY:
            payload['close_reason_code'] = "MODEL_CLOSE"
        elif is_emergency:
            payload['close_reason_code'] = "CIRCUIT_BREAKER"
    
    if 'hedge_reason_code' not in payload and "HEDGE" in action_name.upper():
        if abs(roe_pct) >= 20:
            payload['hedge_reason_code'] = "ROE_THRESHOLD"
        else:
            payload['hedge_reason_code'] = "PROTECTIVE"
    
    return payload


def get_position_metrics(symbol: str, side: str) -> Dict[str, float]:
    """
    Get position metrics from the dynamic runner overlay.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        
    Returns:
        Dict with roe_pct, mfe_pct, mae_pct, time_in_trade_s, hot_monitor
    """
    metrics = {
        'roe_pct': 0.0,
        'mfe_pct': 0.0,
        'mae_pct': 0.0,
        'time_in_trade_s': 0.0,
        'hot_monitor': 0
    }
    
    try:
        from rl.dynamic_runner_hedge import get_dynamic_runner_overlay
        overlay = get_dynamic_runner_overlay()
        tracker = overlay.get_tracker(symbol, side)
        
        if tracker:
            metrics['roe_pct'] = round(tracker.roe_pct, 2)
            metrics['mfe_pct'] = round(tracker.mfe_pct, 2)
            metrics['mae_pct'] = round(tracker.mae_pct, 2)
            metrics['time_in_trade_s'] = round(tracker.time_in_trade_seconds(), 0)
            metrics['hot_monitor'] = 1 if tracker.hot_monitor_active else 0
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[CONTRACT] Failed to get position metrics: {e}")
    
    return metrics


def format_telemetry_log(
    symbol: str,
    action: str,
    intent: str,
    roe_pct: float,
    mfe_pct: float,
    mae_pct: float,
    close_reason: str = "",
    hedge_reason: str = "",
    hot_monitor: bool = False
) -> str:
    """
    Format a telemetry log line for contract audit.
    
    Returns:
        Formatted log string
    """
    parts = [
        f"symbol={symbol}",
        f"action={action}",
        f"intent={intent}",
        f"roe={roe_pct:.1f}%",
        f"mfe={mfe_pct:.1f}%",
        f"mae={mae_pct:.1f}%",
    ]
    
    if close_reason:
        parts.append(f"close_reason={close_reason}")
    if hedge_reason:
        parts.append(f"hedge_reason={hedge_reason}")
    if hot_monitor:
        parts.append("hot_monitor=1")
    
    return "CONTRACT_TELEMETRY | " + " | ".join(parts)

