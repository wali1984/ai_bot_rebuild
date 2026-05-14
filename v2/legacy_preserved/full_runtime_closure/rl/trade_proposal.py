"""
Trade Proposal Schema (Jan 2026)
================================

Purpose:
- Provide a single, validated schema for ALL non-trainer publishers ("trader-side systems")
  to propose actions to the Orchestrator.
- Keep proposals data-driven: proposals must carry enough real-time market context so the
  orchestrator can arbitrate without static gating thresholds.

Notes:
- Proposals are *NOT* executed by the proposer.
- The Orchestrator is the only publisher to `signals:trading:*` once fully enabled.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        v = float(x)
        return float(v)
    except Exception:
        return float(default)


def _norm_conf(x: Any) -> float:
    c = _f(x, 0.0)
    if c > 1.0:
        c = c / 100.0
    return max(0.0, min(1.0, float(c)))


@dataclass
class TradeProposal:
    # identity
    proposal_id: str
    ts_ms: int
    source: str  # e.g. "stealth_stop", "dynamic_tp", "trailing_stop"

    # routing
    account_id: str
    symbol: str

    # intent
    action_name: str  # e.g. CLOSE_LONG, PARTIAL_CLOSE_SHORT, ADD_HEDGE_LONG, OPEN_LONG...
    action_category: str  # e.g. HEDGE / PROTECTIVE / PROFIT / OPEN_RISK / RECOVERY

    # compatibility fields (signal-schema)
    timeframe: str = "multi"
    created_ts_ms: int = 0

    # sizing / parameters (optional; downstream will validate)
    close_fraction: float = 0.0
    margin_usd: float = 0.0
    notional_usd: float = 0.0
    leverage: float = 0.0

    # dynamic scoring signals (no static thresholds)
    confidence: float = 0.0
    expected_edge_net: float = 0.0
    expected_profit_usd: float = 0.0
    expected_profit_pct: float = 0.0
    urgency_score: float = 0.0  # 0..1 (data-driven)

    # compliance + context
    no_loss_compliant: bool = True
    recovery_mode: bool = False  # if True and loss-realization toggle enabled, may allow loss closes
    reduce_only: bool = False
    risk_add: int = 0
    trigger_reason: str = ""
    market_context: Optional[Dict[str, Any]] = None

    # execution hints
    side: str = ""
    take_profit: float = 0.0

    @classmethod
    def new(
        cls,
        *,
        source: str,
        account_id: str,
        symbol: str,
        action_name: str,
        action_category: str,
        **kwargs: Any,
    ) -> "TradeProposal":
        now_ms = int(time.time() * 1000)
        return cls(
            proposal_id=str(uuid.uuid4()),
            ts_ms=now_ms,
            source=str(source or "unknown"),
            account_id=str(account_id or "primary"),
            symbol=str(symbol or "").upper().strip(),
            action_name=str(action_name or "").upper().strip(),
            action_category=str(action_category or "").upper().strip(),
            **kwargs,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # normalize
        d["symbol"] = str(d.get("symbol") or "").upper().strip()
        d["action_name"] = str(d.get("action_name") or "").upper().strip()
        d["action_category"] = str(d.get("action_category") or "").upper().strip()
        d["confidence"] = float(_norm_conf(d.get("confidence")))
        d["urgency_score"] = max(0.0, min(1.0, float(_f(d.get("urgency_score"), 0.0))))
        d["close_fraction"] = max(0.0, min(1.0, float(_f(d.get("close_fraction"), 0.0))))
        # schema compatibility for orchestrator validators
        d["action"] = d.get("action") or d.get("action_name")
        d["timeframe"] = str(d.get("timeframe") or "multi").strip()
        if not d.get("created_ts_ms"):
            d["created_ts_ms"] = int(d.get("ts_ms") or (time.time() * 1000))
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)


def proposal_to_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a TradeProposal dict into a trainer/trader-compatible payload shape.

    The orchestrator expects trainer-like payloads. We preserve proposal metadata via
    namespaced fields.
    """
    # Minimal compatibility keys used by existing trainer/trader paths.
    symbol = str(p.get("symbol") or "").upper().strip()
    account_id = str(p.get("account_id") or "primary").strip()
    action_name = str(p.get("action_name") or "").upper().strip()
    cat = str(p.get("action_category") or "").upper().strip()
    confidence = _norm_conf(p.get("confidence"))

    action_u = str(action_name or "").upper()
    reduce_only = False
    if action_u.startswith("CLOSE") and not action_u.startswith("CLOSE_AND"):
        reduce_only = True
    elif "TAKE_PROFIT" in action_u or "STOP_LOSS" in action_u:
        reduce_only = True
    elif action_u.startswith(("SET_TAKE_PROFIT", "SET_STOP", "SET_TRAILING")):
        reduce_only = True

    payload: Dict[str, Any] = {
        "timestamp": time.time(),
        "ts_ms": int(p.get("ts_ms") or (time.time() * 1000)),
        "producer": "orchestrator_proposal_bus",
        "exchange": "binance",
        "account_id": account_id,
        "symbol": symbol,
        "timeframe": "multi",
        "action_name": action_name,
        "action": action_name,
        "action_category": cat or "PROTECTIVE",
        "model_confidence": float(confidence),
        "confidence": float(confidence),
        "close_fraction": float(_f(p.get("close_fraction"), 0.0)),
        "margin_usd": float(_f(p.get("margin_usd"), 0.0)),
        "notional_usd": float(_f(p.get("notional_usd"), 0.0)),
        "leverage": float(_f(p.get("leverage"), 0.0)),
        # scoring hints
        "expected_edge_net": float(_f(p.get("expected_edge_net"), 0.0)),
        "expected_profit_usd": float(_f(p.get("expected_profit_usd"), 0.0)),
        "expected_profit_pct": float(_f(p.get("expected_profit_pct"), 0.0)),
        "trade_urgency": float(_f(p.get("urgency_score"), 0.0)),
        # compliance hints
        "no_loss_compliant": bool(p.get("no_loss_compliant", True)),
        "trainer_recovery_mode": bool(p.get("recovery_mode", False)),
        # trace
        "source": str(p.get("source") or "proposal"),
        "reasoning": str(p.get("trigger_reason") or ""),
        "_proposal_id": str(p.get("proposal_id") or ""),
        "_proposal_stream": str(p.get("_proposal_stream") or ""),
        "_proposal_raw": p,
        "reduce_only": bool(p.get("reduce_only") if "reduce_only" in p else reduce_only),
    }
    if "take_profit" in p and "take_profit" not in payload:
        payload["take_profit"] = p.get("take_profit")
    if "side" in p and "side" not in payload:
        payload["side"] = p.get("side")
    if payload.get("reduce_only"):
        payload["risk_add"] = 0
    elif "risk_add" in p:
        try:
            payload["risk_add"] = int(p.get("risk_add") or 0)
        except Exception:
            payload["risk_add"] = 0
    mc = p.get("market_context")
    if isinstance(mc, dict):
        payload["market_context"] = mc
        # Convenience passthrough for trader execution fields (avoid inventing new contracts).
        # These keys are only used if present.
        for k_src, k_dst in (
            ("side", "current_position_side"),
            ("close_fraction", "close_fraction"),
            ("tp_price", "take_profit"),
            ("take_profit", "take_profit"),
            ("stop_price", "stop_loss"),
            ("stop_loss", "stop_loss"),
            ("trailing_callback", "trailing_callback"),
            ("trailing_activation_price", "trailing_activation_price"),
        ):
            if k_src in mc and k_dst not in payload:
                payload[k_dst] = mc.get(k_src)
        # Promote profit-guard override fields to top level so they survive
        # through the orchestrator→trader signal pipeline and are accessible
        # via signal.get("override_profit_guard") without nested lookups.
        for _override_key in ("override_profit_guard", "proactive_override", "override_safety_block"):
            if mc.get(_override_key) and _override_key not in payload:
                payload[_override_key] = mc[_override_key]
        # Promote execution hints for fast risk-reduction (survival mode).
        for _hint_key in ("fastlane", "allow_market_fallback", "urgency", "execution_mode"):
            if mc.get(_hint_key) is not None and _hint_key not in payload:
                payload[_hint_key] = mc.get(_hint_key)
    # MTF audit tags for consumers that read nested metadata on signals
    _mtf_meta: Dict[str, Any] = {}
    for _k in ("mtf_scenario_id", "primary_tf", "contrary_htf_bias", "tf_votes", "tf_conflict_score"):
        _v = p.get(_k)
        if _v is not None:
            _mtf_meta[_k] = _v
    if _mtf_meta:
        ex = payload.get("metadata")
        if isinstance(ex, dict):
            for _k2, _v2 in _mtf_meta.items():
                ex.setdefault(_k2, _v2)
            payload["metadata"] = ex
        else:
            payload["metadata"] = dict(_mtf_meta)
    return payload

