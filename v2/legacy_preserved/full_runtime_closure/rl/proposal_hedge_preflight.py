"""
Shared hedge preflight helpers: emit scale-hedge proposals to the orchestrator bus.

Used by orchestrator_worker (profit-close preflight) and trading/trader (ROI-kill escalation).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional


def emit_scale_hedge_proposal(
    redis_client: Any,
    *,
    account_id: str,
    symbol: str,
    hedge_action: str,
    margin_usd: float,
    source: str,
    reason: str,
    stream: Optional[str] = None,
    timeframe: str = "multi",
) -> bool:
    """
    Emit a TRADE_PROPOSAL-shaped payload to wma:proposals (or `stream`).
    hedge_action: e.g. ADD_HEDGE_SHORT, OPEN_HEDGE_SHORT
    """
    if redis_client is None:
        return False
    try:
        from config import ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM
    except Exception:
        ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM = "wma:proposals"
    stream = str(stream or ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM or "wma:proposals")
    sym_u = str(symbol or "").upper().strip()
    acct = str(account_id or "primary").strip().lower()
    act_u = str(hedge_action or "").upper().strip()
    now_ms = int(time.time() * 1000)
    margin = max(0.0, float(margin_usd or 0.0))
    proposal: Dict[str, Any] = {
        "event": "TRADE_PROPOSAL",
        "proposal_id": str(uuid.uuid4()),
        "ts_ms": now_ms,
        "created_ts_ms": now_ms,
        "account_id": acct,
        "symbol": sym_u,
        "action": act_u,
        "action_name": act_u,
        "action_category": "HEDGE",
        "category": "HEDGE",
        "source_module": str(source or "hedge_preflight"),
        "source": str(source or "hedge_preflight"),
        "confidence": 0.85,
        "model_confidence": 0.85,
        "margin_usd": round(margin, 4),
        "notional_usd": 0.0,
        "leverage": 1.0,
        "risk_add": 0,
        "hedge_intent": True,
        "no_loss_compliant": True,
        "profit_intent": False,
        "reduce_only": False,
        "timeframe": str(timeframe or "multi"),
        "trigger_reason": str(reason or "")[:500],
        "priority": 3,
    }
    try:
        redis_client.xadd(stream, {"data": json.dumps(proposal, separators=(",", ":"), default=str)})
        return True
    except Exception:
        return False
