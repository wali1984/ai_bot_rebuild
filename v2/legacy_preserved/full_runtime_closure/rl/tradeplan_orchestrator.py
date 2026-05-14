"""
TradePlan Orchestrator (Jan 2026)
================================

Goal: make the system single-publisher without losing trigger reasons.

This module takes multiple candidate payloads (from different features/modules)
and selects ONE final action per (account_id, symbol) per cycle.

Key properties:
- Deterministic: same inputs -> same outputs (for auditability).
- Trader-aligned feasibility: prevents publish→reject loops by enforcing pair-cap
  and resizing/dropping unexecutable hedge/entry adds at publish time.
- Proof chain: emits a structured explanation of why an action won/lost.

Note: In "shadow" mode the orchestrator computes the decision but does NOT
change what is published; it only emits proofs.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


HEDGE_ACTION_PREFIXES = (
    "OPEN_HEDGE_",
    "ADD_HEDGE_",
    "SCALE_HEDGE",
    "UNWIND_HEDGE",
)


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v
    except Exception:
        return default


def _norm_conf(conf: Any) -> float:
    c = _to_float(conf, 0.0)
    if c > 1.0:
        c = c / 100.0
    return max(0.0, min(1.0, c))


def _is_hedge_action(action_name: str) -> bool:
    a = str(action_name or "").upper()
    if a in {"SCALE_HEDGE", "UNWIND_HEDGE"}:
        return True
    return any(a.startswith(p) for p in HEDGE_ACTION_PREFIXES)


def _action_key(payload: Dict[str, Any]) -> str:
    raw = payload.get("final_action") or payload.get("action_name") or payload.get("action") or ""
    return str(raw or "").upper()

def _is_sidecar_action(action_name: str) -> bool:
    """
    Sidecar actions do not change exposure immediately (they arm/update local stop engines).
    They should not compete with trade actions in winner-take-all arbitration.
    """
    a = str(action_name or "").upper()
    return a.startswith("SET_") or a.startswith("ARM_") or a.startswith("UPDATE_")


def _payload_symbol(payload: Dict[str, Any]) -> str:
    return str(payload.get("symbol") or "").upper().strip()


def _payload_account(payload: Dict[str, Any]) -> str:
    return str(payload.get("account_id") or payload.get("account") or "primary").strip()


def _compute_pair_margin(redis_client: Any, account_id: str, symbol: str) -> float:
    """
    Uses portfolio:positions:{account_id} hash fields {symbol}:LONG / {symbol}:SHORT.
    """
    if redis_client is None:
        return 0.0
    try:
        key = f"portfolio:positions:{account_id}"
        if hasattr(redis_client, "pipeline"):
            pipe = redis_client.pipeline()
            pipe.hget(key, f"{symbol}:LONG")
            pipe.hget(key, f"{symbol}:SHORT")
            raw_long, raw_short = pipe.execute()
        else:
            raw_long = redis_client.hget(key, f"{symbol}:LONG")
            raw_short = redis_client.hget(key, f"{symbol}:SHORT")
        total = 0.0
        for raw in (raw_long, raw_short):
            if not raw:
                continue
            try:
                if isinstance(raw, dict):
                    d = raw
                else:
                    s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    d = json.loads(s) if isinstance(s, str) else {}
                m = _to_float(d.get("margin_used", 0.0) or d.get("initialMargin", 0.0) or 0.0, 0.0)
                total += abs(m)
            except Exception:
                continue
        return float(total)
    except Exception:
        return 0.0


def _has_any_position(redis_client: Any, account_id: str, symbol: str) -> bool:
    """
    True if either {symbol}:LONG or {symbol}:SHORT has non-zero size.
    Reads portfolio:positions:{account_id} fields "{symbol}:LONG"/"{symbol}:SHORT".
    """
    if redis_client is None:
        return False
    try:
        key = f"portfolio:positions:{account_id}"
        if hasattr(redis_client, "pipeline"):
            pipe = redis_client.pipeline()
            pipe.hget(key, f"{symbol}:LONG")
            pipe.hget(key, f"{symbol}:SHORT")
            raw_long, raw_short = pipe.execute()
        else:
            raw_long = redis_client.hget(key, f"{symbol}:LONG")
            raw_short = redis_client.hget(key, f"{symbol}:SHORT")

        for raw in (raw_long, raw_short):
            if not raw:
                continue
            try:
                if isinstance(raw, dict):
                    d = raw
                else:
                    s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    d = json.loads(s) if isinstance(s, str) else {}
                # common size keys across our writers / binance formats
                for k in ("size", "positionAmt", "position_amount", "qty", "amount"):
                    if k in d:
                        if abs(_to_float(d.get(k), 0.0)) > 0.0:
                            return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _compute_pair_cap(
    redis_client: Any,
    account_id: str,
    symbol: str,
    cfg: Any,
    *,
    hedge_necessity_class: int = 0,
    pds: float = 0.0,
) -> float:
    """
    Pair cap = max(max_margin_usd, max_equity_pct * wallet_balance_usd)
    
    Per-account caps (Jan 24, 2026):
    - Uses PER_ACCOUNT_PAIR_CAPS if available for the account
    - Falls back to STACK_OPEN_MAX_MARGIN_USD / STACK_OPEN_MAX_EQUITY_PCT

    Uses portfolio:equity:{account_id} if available; falls back to base_cap.
    """
    # Get per-account caps or defaults
    per_account_caps = getattr(cfg, "PER_ACCOUNT_PAIR_CAPS", {})
    acct_caps = per_account_caps.get(str(account_id).lower(), {})
    
    base_cap = float(acct_caps.get("max_margin_usd") or getattr(cfg, "STACK_OPEN_MAX_MARGIN_USD", 300.0))
    pct = float(acct_caps.get("max_equity_pct") or getattr(cfg, "STACK_OPEN_MAX_EQUITY_PCT", 0.10))
    
    if redis_client is None:
        return base_cap
    try:
        raw = redis_client.get(f"portfolio:equity:{account_id}")
        if not raw:
            return base_cap
        if isinstance(raw, dict):
            snap = raw
        else:
            s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            snap = json.loads(s) if isinstance(s, str) else {}
        wallet = _to_float(
            snap.get("wallet_balance_usd", 0.0)
            or snap.get("wallet_balance", 0.0)
            or snap.get("balance", 0.0),
            0.0,
        )
        eq_basis = _to_float(
            snap.get("equity_usd", 0.0)
            or snap.get("margin_balance_usd", 0.0)
            or wallet,
            0.0,
        )
        if eq_basis <= 0:
            eq_basis = wallet
        if eq_basis <= 0:
            return base_cap
        # Operator rule: cap is whichever is higher:
        # - fixed USD floor (default $300)
        # - equity percentage (default 10% of wallet balance)
        cap = float(max(base_cap, eq_basis * pct))

        # Tier-3 hard cap (operator request)
        try:
            tier3 = set(getattr(cfg, "TIER3_SYMBOLS", []) or [])
            if str(symbol).upper() in tier3:
                cap = min(float(cap), float(getattr(cfg, "TIER3_PAIR_CAP_MAX_USD", 200.0)))
        except Exception:
            pass

        # Manual override: if a manual leg already exceeds base cap, allow hedges up to 50% equity
        try:
            if bool(getattr(cfg, "MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED", False)):
                exclude = set(getattr(cfg, "MANUAL_HEDGE_PAIR_CAP_EXCLUDE_SYMBOLS", []) or [])
                sym_u = str(symbol).upper()
                if sym_u not in exclude:
                    pos_key = f"portfolio:positions:{account_id}"
                    leg_margins = {"LONG": 0.0, "SHORT": 0.0}
                    for leg_side in ("LONG", "SHORT"):
                        raw = redis_client.hget(pos_key, f"{sym_u}:{leg_side}")
                        if raw:
                            raw = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                            data = json.loads(raw) if isinstance(raw, str) else {}
                            leg_margins[leg_side] = abs(_to_float(data.get("margin_used") or data.get("initialMargin"), 0.0))

                    origin_prefix = str(getattr(cfg, "POSITION_ORIGIN_KEY_PREFIX", "wma:position_origin"))
                    for leg_side, m_usd in leg_margins.items():
                        if m_usd <= 0:
                            continue
                        raw_origin = redis_client.get(f"{origin_prefix}:{account_id}:{sym_u}:{leg_side}")
                        if raw_origin:
                            raw_origin = raw_origin.decode() if isinstance(raw_origin, (bytes, bytearray)) else raw_origin
                            try:
                                origin_val = json.loads(raw_origin).get("origin") if isinstance(raw_origin, str) else None
                            except Exception:
                                origin_val = str(raw_origin)
                            if str(origin_val or "").lower() == "manual" and float(m_usd) > float(cap):
                                cap = max(float(cap), float(eq_basis) * float(getattr(cfg, "MANUAL_HEDGE_PAIR_CAP_EQUITY_PCT", 0.50)))
                                break
        except Exception:
            pass

        return float(cap)
    except Exception:
        return base_cap


def _expected_edge_net(payload: Dict[str, Any]) -> float:
    """
    Lightweight edge estimate from payload fields if available.
    Prefer explicit effective_edge / expected_edge_net fields when present.
    """
    for k in ("expected_edge_net", "effective_edge", "edge_net", "net_edge"):
        if k in payload:
            return _to_float(payload.get(k), 0.0)
    # fallback: use price_target_pct if available
    pt = payload.get("price_target_pct")
    if pt is None:
        return 0.0
    return _to_float(pt, 0.0)


def _expected_profit_usd(payload: Dict[str, Any]) -> float:
    for k in ("expected_profit_usd", "net_profit_usd", "realized_pnl_usd"):
        if k in payload:
            return _to_float(payload.get(k), 0.0)
    return 0.0


def _urgency_score(payload: Dict[str, Any]) -> float:
    # Prefer explicit urgency_score; fall back to trainer's trade_urgency if present.
    u = _to_float(payload.get("urgency_score", None), None)
    if u is None:
        u = _to_float(payload.get("trade_urgency", None), 0.0)
    # clamp 0..1
    if u > 1.0:
        u = u / 100.0
    return max(0.0, min(1.0, float(u)))


def _is_close_like(action_name: str) -> bool:
    a = str(action_name or "").upper()
    return any(tok in a for tok in ("CLOSE", "DECREASE", "PARTIAL_CLOSE", "TAKE_PROFIT", "STOP_LOSS"))


def _get_leg_pnl_usd(redis_client: Any, account_id: str, symbol: str, side: str) -> Optional[float]:
    """
    Best-effort PnL read from portfolio:positions:{account_id} field "{symbol}:{SIDE}" JSON.
    """
    if redis_client is None:
        return None
    try:
        key = f"portfolio:positions:{account_id}"
        field = f"{symbol}:{str(side or '').upper()}"
        raw = redis_client.hget(key, field)
        if not raw:
            return None
        if isinstance(raw, dict):
            d = raw
        else:
            s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            d = json.loads(s) if isinstance(s, str) else {}
        # prefer unrealized_pnl / unrealizedPnl if present
        for k in ("unrealized_pnl", "unrealizedPnl", "pnl_usd"):
            if k in d:
                return float(_to_float(d.get(k), 0.0))
        return None
    except Exception:
        return None


def _loss_realization_enabled(redis_client: Any, account_id: str, cfg: Any) -> bool:
    """
    Runtime override: risk:loss_realization_enabled:{account_id} == "1"
    """
    try:
        if bool(getattr(cfg, "LOSS_REALIZATION_MODE_ENABLED", False)):
            return True
    except Exception:
        pass
    if redis_client is None:
        return False
    try:
        prefix = str(getattr(cfg, "LOSS_REALIZATION_MODE_REDIS_KEY_PREFIX", "risk:loss_realization_enabled"))
        raw = redis_client.get(f"{prefix}:{account_id}")
        if not raw:
            return False
        s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        return str(s).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return False


def _profit_bank_balance(redis_client: Any, account_id: str) -> float:
    """
    Best-effort: read profit_bank:state:{account_id}.balance_usd
    """
    if redis_client is None:
        return 0.0
    try:
        raw = redis_client.get(f"profit_bank:state:{str(account_id).strip().lower()}")
        if not raw:
            return 0.0
        s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        d = json.loads(s) if isinstance(s, str) else {}
        return float(_to_float(d.get("balance_usd"), 0.0))
    except Exception:
        return 0.0

@dataclass
class OrchestratorDecision:
    winner: Dict[str, Any]
    losers: List[Dict[str, Any]]
    resized: bool
    dropped: bool
    reason: str
    proof: Dict[str, Any]


class TradePlanOrchestrator:
    def __init__(self, redis_client: Any, cfg: Any):
        self.redis = redis_client
        self.cfg = cfg
        self._market_context_provider = None
    
    def _get_market_context(self, symbol: str, account_id: str):
        """Get or create MarketContext for utility scoring."""
        try:
            from rl.market_context import get_market_context
            return get_market_context(self.redis, symbol, account_id)
        except Exception:
            return None

    def orchestrate_group(
        self,
        proposals: List[Dict[str, Any]],
    ) -> OrchestratorDecision:
        """
        Pick one proposal among a set of proposals for the same (account, symbol).
        
        Uses UTILITY-BASED SCORING:
        - Computes comparable scores using MarketContext
        - Applies regime-weighted utility function
        - Selects winner with highest utility
        - Records detailed proof of why winner won and losers lost
        """
        proposals = list(proposals or [])
        if not proposals:
            raise ValueError("no proposals")
        
        # Get symbol and account for market context
        sample = proposals[0]
        sym = _payload_symbol(sample)
        acct = _payload_account(sample)
        
        # ========================================================================
        # STEP 1: Compute utility scores using MarketContext
        # ========================================================================
        market_ctx = self._get_market_context(sym, acct)
        scored_proposals = []
        
        for p in proposals:
            # Copy to avoid mutating original
            p2 = dict(p)
            
            # Check if proposal already has scores
            existing_scores = p2.get("scores") or {}
            if existing_scores and "utility" in existing_scores:
                # Use pre-computed scores
                p2["_utility"] = float(existing_scores.get("utility", 0))
                p2["_scores"] = existing_scores
            elif market_ctx:
                # Compute scores using market context
                scores = self._compute_proposal_scores(p2, market_ctx)
                p2["_utility"] = scores.get("utility", 0)
                p2["_scores"] = scores
            else:
                # Fallback: use legacy scoring
                p2["_utility"] = self._legacy_utility(p2)
                p2["_scores"] = {"utility": p2["_utility"], "method": "legacy"}
            
            scored_proposals.append(p2)
        
        # ========================================================================
        # STEP 2: Apply hard safety vetoes BEFORE sorting
        # ========================================================================
        vetoed = []
        eligible = []
        
        for p in scored_proposals:
            veto_reason = self._check_vetoes(p, market_ctx)
            if veto_reason:
                p["_veto_reason"] = veto_reason
                vetoed.append(p)
            else:
                eligible.append(p)
        
        # If all vetoed, use highest utility vetoed as "winner" but mark dropped
        if not eligible:
            scored_proposals.sort(key=lambda p: p.get("_utility", 0), reverse=True)
            winner = scored_proposals[0]
            return OrchestratorDecision(
                winner=winner,
                losers=scored_proposals[1:],
                resized=False,
                dropped=True,
                reason=f"ALL_VETOED|{winner.get('_veto_reason', 'unknown')}",
                proof=self._build_proof(winner, scored_proposals[1:], market_ctx, all_vetoed=True)
            )
        
        # ========================================================================
        # STEP 3: Sort by utility and select winner
        # ========================================================================
        eligible.sort(key=lambda p: p.get("_utility", 0), reverse=True)
        
        winner = eligible[0]
        losers = eligible[1:] + vetoed
        
        # Continue with winner validation
        action = _action_key(winner)

        # Extract hedge priority indicators for dynamic pair cap
        hedge_necessity_class = int(_to_float(winner.get("hedge_necessity_class"), 0))
        pds = _to_float(winner.get("pds") or winner.get("protection_demand_score"), 0.0)
        _is_hedge_early = _is_hedge_action(action)
        if pds < 0.01 and _is_hedge_early and self.redis:
            try:
                _pos_key = f"portfolio:positions:{acct}"
                _leg_roes = {}
                for _side_chk in ("LONG", "SHORT"):
                    _rp = self.redis.hget(_pos_key, f"{sym}:{_side_chk}")
                    if _rp:
                        _rp_s = _rp.decode() if isinstance(_rp, (bytes, bytearray)) else str(_rp)
                        _rp_d = json.loads(_rp_s) if isinstance(_rp_s, str) and _rp_s.strip().startswith("{") else {}
                        _roe = float(_rp_d.get("roe_pct", 0) or _rp_d.get("percentage", 0) or _rp_d.get("roi_pct", 0) or _rp_d.get("unrealizedProfit", 0) or 0)
                        _leg_roes[_side_chk] = _roe
                if len(_leg_roes) == 2 and all(r < 0 for r in _leg_roes.values()):
                    pds = 0.98
                elif len(_leg_roes) >= 1 and any(r < -30.0 for r in _leg_roes.values()):
                    pds = 0.95
            except Exception:
                pass

        pair_margin = _compute_pair_margin(self.redis, acct, sym)
        pair_cap = _compute_pair_cap(
            self.redis, acct, sym, self.cfg,
            hedge_necessity_class=hedge_necessity_class,
            pds=pds,
        )
        headroom = max(0.0, float(pair_cap - pair_margin))

        margin_usd = _to_float(winner.get("margin_usd"), 0.0)
        notional_usd = _to_float(winner.get("notional_usd"), 0.0)
        lev = max(1.0, _to_float(winner.get("leverage"), 1.0))

        resized = False
        dropped = False
        reason = "OK"

        # --------------------------------------------------------------------
        # STRICT NO-LOSS (operator requirement):
        # - Any close-like proposal that would realize loss is rejected ALWAYS.
        # - Recovery-mode overrides allowed only for reduce-only repair intents
        #   when repair mode is enabled.
        # - FLIP actions (CLOSE_*_OPEN_*, CLOSE_*_AND_*) are exempt because
        #   they represent directional reversals backed by multi-TF trainer
        #   confidence, not discretionary loss-taking exits.
        # --------------------------------------------------------------------
        try:
            _action_u_noloss = str(action or "").upper()
            _is_flip = (
                ("CLOSE" in _action_u_noloss and "OPEN" in _action_u_noloss)
                or "FLIP" in _action_u_noloss
            )
            if _is_close_like(action) and not _is_flip:
                target_side = "LONG" if "LONG" in action else ("SHORT" if "SHORT" in action else "")
                pnl = _get_leg_pnl_usd(self.redis, acct, sym, target_side) if target_side else None
                if pnl is not None and float(pnl) < 0.0:
                    try:
                        repair_enabled = bool(getattr(self.cfg, "REPAIR_MODE_ENABLED", False))
                    except Exception:
                        repair_enabled = False
                    meta = winner.get("metadata") if isinstance(winner.get("metadata"), dict) else {}
                    reduce_only = bool(winner.get("reduce_only", False) or meta.get("reduce_only", False))
                    action_category = str(
                        winner.get("action_category")
                        or meta.get("action_category")
                        or meta.get("category")
                        or ""
                    ).upper()
                    recovery_intent = bool(
                        winner.get("trainer_recovery_mode")
                        or winner.get("repair_intent")
                        or meta.get("trainer_recovery_mode")
                        or meta.get("repair_intent")
                        or meta.get("recovery_rebalance")
                    )
                    source_module = str(
                        winner.get("source")
                        or winner.get("source_module")
                        or meta.get("source")
                        or meta.get("source_module")
                        or ""
                    ).lower()
                    is_repair_source = "hedge_manager_v3" in source_module
                    is_deleverage_cat = action_category in (
                        "DELEVERAGE", "GOVERNOR_DELEVERAGE", "BUDGET_TRIM",
                        "MARGIN_GOVERNOR", "AUTO_DELEVERAGE", "PER_LEG_ROI_KILL",
                    )
                    is_deleverage_src = any(
                        tok in source_module
                        for tok in ("auto_deleverager", "margin_governor", "risk_governor", "per_leg_roi_kill")
                    )
                    # Trainer-sourced close signals bypass no-loss guard:
                    # The trainer's model has decided based on multi-TF analysis that
                    # this position should be closed. Blocking these signals keeps the
                    # system in losing positions indefinitely.
                    is_trainer_close = source_module in ("trainer", "") and action_category == "PROTECTIVE"
                    # Explicit override flags set by trainer or ROI kill pipeline
                    has_override = bool(
                        winner.get("override_profit_guard")
                        or winner.get("proactive_override")
                        or winner.get("override_safety_block")
                        or meta.get("override_profit_guard")
                        or meta.get("proactive_override")
                    )
                    allow_recovery_loss = bool(
                        (
                            repair_enabled
                            and reduce_only
                            and (
                                recovery_intent
                                or action_category == "RECOVERY"
                                or (is_repair_source and action.startswith("PARTIAL_CLOSE_"))
                            )
                        )
                        or (reduce_only and (is_deleverage_cat or is_deleverage_src))
                        or is_trainer_close  # Trainer model exit decisions bypass no-loss
                        or has_override      # Explicit override flags
                    )
                    if not allow_recovery_loss:
                        dropped = True
                        reason = "DROP_NO_LOSS_ALWAYS"

        except Exception:
            pass

        # Feasibility: enforce pair cap for exposure-increasing adds (hedge + entries)
        #
        # Policy (Jan 2026):
        # - Hedges follow the same cap discipline as entries by default.
        # - Emergency bypass is allowed only under strict conditions and NEVER drains headroom reserve.
        # - Avoid publishing "dust" orders (min-notional enforcement after any resize).
        signal_source = str(winner.get("source") or winner.get("source_module") or "").lower()
        action_category = str(winner.get("action_category") or "").upper()
        is_urc_or_harvest = ("urc" in signal_source) or ("hedge_harvest" in signal_source)
        is_hedge = _is_hedge_action(action)

        # Hard safety: never publish hedge-intent opens/adds when the symbol is flat.
        # This prevents downstream HEDGE_FROM_FLAT_BLOCK spam and keeps hedge semantics correct.
        try:
            if is_hedge and action.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")):
                if not _has_any_position(self.redis, acct, sym):
                    dropped = True
                    reason = "DROP_HEDGE_FROM_FLAT"
        except Exception:
            pass

        # Min-notional floor for this symbol (avoid dust publishes)
        try:
            base_min_notional = float(getattr(self.cfg, "MIN_NOTIONAL_USD", 5.0))
        except Exception:
            base_min_notional = 5.0
        try:
            per_sym_min = getattr(self.cfg, "BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL", {}) or {}
            min_notional_usd = float(per_sym_min.get(sym, base_min_notional))
        except Exception:
            min_notional_usd = base_min_notional

        # Headroom reserve:
        # Reserve was previously applied to hedges (subtracting from headroom), which can
        # silently drop hedges when headroom is near the reserve (e.g., head=149 reserve=150).
        # Hedges are the survival action — they must be allowed to use available headroom.
        # (Emergency bypass already uses reserve_for_calc=0 explicitly.)
        reserve_usd = 0.0
        effective_headroom = max(0.0, float(headroom) - float(reserve_usd))

        # Emergency hedge bypass (hedges only)
        bypass_pair_cap = False
        margin_util_pct = 0.0
        if is_hedge:
            try:
                bypass_enabled = bool(getattr(self.cfg, "HEDGE_BYPASS_ENABLED", True))
            except Exception:
                bypass_enabled = True
            if bypass_enabled:
                try:
                    raw_eq = self.redis.get(f"portfolio:equity:{acct}") if self.redis is not None else None
                    if raw_eq:
                        s_eq = raw_eq.decode() if isinstance(raw_eq, (bytes, bytearray)) else raw_eq
                        snap = json.loads(s_eq) if isinstance(s_eq, str) else {}
                        wallet = _to_float(snap.get("wallet_balance_usd", 0.0), 0.0)
                        used = _to_float(snap.get("used_margin_usd", 0.0) or snap.get("initial_margin_usd", 0.0), 0.0)
                        if wallet > 0:
                            margin_util_pct = (used / wallet) * 100.0
                except Exception:
                    margin_util_pct = 0.0

                try:
                    emerg_util = float(getattr(self.cfg, "EMERGENCY_MARGIN_UTIL_PCT", 85.0))
                except Exception:
                    emerg_util = 85.0
                try:
                    min_pds = float(getattr(self.cfg, "HEDGE_BYPASS_MIN_PDS", 0.85))
                except Exception:
                    min_pds = 0.85
                try:
                    min_class = int(getattr(self.cfg, "HEDGE_BYPASS_MIN_NECESSITY_CLASS", 2))
                except Exception:
                    min_class = 2

                min_pds = max(float(min_pds), 0.95)
                min_class = max(int(min_class), 3)
                if (margin_util_pct >= float(emerg_util)) and (int(hedge_necessity_class) >= int(min_class) or float(pds) >= float(min_pds)):
                    bypass_pair_cap = True
                elif float(pds) >= 0.95:
                    bypass_pair_cap = True
        else:
            # Non-hedge: legacy URC/harvest bypass (typically reduce-only systems)
            bypass_pair_cap = bool(is_urc_or_harvest)

        # Reduce-only actions must never be pair-cap blocked.
        reduce_only = bool(winner.get("reduce_only"))
        if not reduce_only:
            action_u = str(action or "").upper()
            if action_u.startswith("CLOSE") and not action_u.startswith("CLOSE_AND"):
                reduce_only = True
            elif "TAKE_PROFIT" in action_u or "STOP_LOSS" in action_u:
                reduce_only = True
            elif action_u.startswith(("SET_TAKE_PROFIT", "SET_STOP", "SET_TRAILING")):
                reduce_only = True
        if reduce_only:
            winner = dict(winner)
            winner["reduce_only"] = True
            bypass_pair_cap = True

        # Risk-reducing hedge override: if proposal explicitly reports non-positive risk_delta,
        # allow pair-cap bypass (protective hedge without weakening leverage policy).
        # GUARD: Only bypass when hedge margin is proportionally reasonable vs. the
        # primary (non-hedge) leg.  When the hedge side already dwarfs the primary
        # leg, further adds increase directional risk rather than reducing it.
        try:
            risk_delta_val = None
            raw_risk_delta = winner.get("risk_delta")
            if raw_risk_delta is not None:
                risk_delta_val = float(raw_risk_delta)
        except Exception:
            risk_delta_val = None
        _hedge_ratio_ok = True
        _hedge_ratio = 0.0
        _primary_margin = 0.0
        _hedge_margin_side = 0.0
        if is_hedge and not bypass_pair_cap:
            try:
                _pos_key = f"portfolio:positions:{acct}"
                _act_up_hr = str(action or "").upper()
                _h_side = "SHORT" if "SHORT" in _act_up_hr else "LONG"
                _p_side = "LONG" if _h_side == "SHORT" else "SHORT"
                for _ls in (_h_side, _p_side):
                    _raw_pos = self.redis.hget(_pos_key, f"{sym}:{_ls}") if self.redis else None
                    _m_val = 0.0
                    if _raw_pos:
                        _rp_s = _raw_pos.decode() if isinstance(_raw_pos, (bytes, bytearray)) else str(_raw_pos)
                        try:
                            _pos_d = json.loads(_rp_s) if isinstance(_rp_s, str) and _rp_s.strip().startswith("{") else {}
                        except Exception:
                            _pos_d = {}
                        for _mf in ("margin_used", "initialMargin", "isolatedWallet", "margin_usd"):
                            _mv = _pos_d.get(_mf)
                            if _mv is not None:
                                _m_val = abs(float(_mv))
                                break
                    if _ls == _h_side:
                        _hedge_margin_side = _m_val
                    else:
                        _primary_margin = _m_val
                if _primary_margin > 0:
                    _hedge_ratio = _hedge_margin_side / _primary_margin
                else:
                    _hedge_ratio = 999.0 if _hedge_margin_side > 50.0 else 0.0
                _max_ratio = 3.0
                try:
                    _rr = self.redis.get(f"regime:{sym}") if self.redis else None
                    if _rr:
                        _rr_s = _rr.decode() if isinstance(_rr, (bytes, bytearray)) else str(_rr)
                        _rr_d = json.loads(_rr_s) if isinstance(_rr_s, str) else {}
                        _mr = str(_rr_d.get("move_regime", "")).upper()
                        if _mr in ("FAST", "IMPULSE"):
                            _max_ratio = 5.0
                        elif _mr in ("TRENDING",):
                            _max_ratio = 4.0
                except Exception:
                    pass
                if _hedge_ratio > _max_ratio:
                    _hedge_ratio_ok = False
            except Exception:
                pass
        if not bypass_pair_cap and is_hedge and bool(winner.get("hedge_intent")) and risk_delta_val is not None:
            if float(risk_delta_val) <= 0.0 and _hedge_ratio_ok:
                bypass_pair_cap = True

        # One-line audit log for per-pair cap discipline (operator request).
        # Includes bypass + reserve context so we can diagnose "why no opens / why hedge dropped".
        try:
            logger.info(
                f"[PAIR_CAP_AUDIT] acct={acct} sym={sym} action={action} cat={str(winner.get('action_category') or '')} "
                f"m_usd={margin_usd:.2f} pair_m={pair_margin:.2f} cap={pair_cap:.2f} head={headroom:.2f} "
                f"reserve={reserve_usd:.2f} util={margin_util_pct:.1f}% bypass={int(bool(bypass_pair_cap))} "
                f"hnc={int(hedge_necessity_class)} pds={float(pds):.3f}"
            )
            logger.info(
                f"ORCH_PAIR_CAP_CHECK sym={sym} is_hedge={int(bool(is_hedge))} desired_usd={margin_usd:.2f} "
                f"cap_usd={pair_cap:.2f} used_usd={pair_margin:.2f} headroom_usd={headroom:.2f} "
                f"decision=pending"
            )
        except Exception:
            pass
        
        exposure_increasing = (not reduce_only) and (
            _is_hedge_action(action)
            or action.startswith("OPEN_")
            or action.startswith("INCREASE_")
            or action.startswith("ADD_")
        )
        if exposure_increasing and margin_usd > 0.0 and not dropped:
            if bypass_pair_cap:
                # Emergency hedge bypass: expand cap, but still respect the reserve.
                try:
                    mult = float(getattr(self.cfg, "HEDGE_BYPASS_MULTIPLIER", 1.5))
                except Exception:
                    mult = 1.5
                effective_cap = float(pair_cap) * float(mult)
                # In true emergency bypass, do NOT hold back headroom reserve; the hedge is the survival action.
                reserve_for_calc = 0.0
                usable_headroom = max(0.0, float(effective_cap - float(pair_margin)) - float(reserve_for_calc))
                if margin_usd > usable_headroom and usable_headroom > 0.0:
                    scale = usable_headroom / margin_usd if margin_usd > 0 else 0.0
                    winner = dict(winner)
                    winner["_orch_resized"] = True
                    winner["_orch_resize_reason"] = f"EMERGENCY_HEADROOM:{usable_headroom:.2f}<req:{margin_usd:.2f}|reserve_usd=0"
                    winner["_orch_pair_margin_usd"] = float(pair_margin)
                    winner["_orch_pair_cap_usd"] = float(effective_cap)
                    winner["_orch_pair_headroom_usd"] = float(usable_headroom)
                    winner["margin_usd"] = float(usable_headroom)
                    if notional_usd > 0:
                        winner["notional_usd"] = float(notional_usd * scale)
                    else:
                        winner["notional_usd"] = float(usable_headroom * lev)
                    resized = True
                    reason = "RESIZED_EMERGENCY_CAP"
                elif margin_usd > usable_headroom and usable_headroom <= 0.0:
                    dropped = True
                    reason = "DROP_EMERGENCY_NO_HEADROOM"
                else:
                    reason = f"BYPASS_PAIR_CAP_EMERGENCY|mult={mult:.2f}|reserve_usd=0"
            else:
                # Default cap path: allow hedges to use full headroom (no reserve subtraction).
                usable_headroom = float(headroom)
                headroom_for_resize = usable_headroom
                if is_hedge and usable_headroom > 0.0:
                    headroom_for_resize = float(usable_headroom) * 0.98
                if margin_usd > headroom_for_resize and headroom_for_resize > 0.0:
                    scale = headroom_for_resize / margin_usd if margin_usd > 0 else 0.0
                    winner = dict(winner)
                    winner["_orch_resized"] = True
                    winner["_orch_resize_reason"] = (
                        f"PAIR_CAP_HEADROOM:{headroom_for_resize:.2f}<req:{margin_usd:.2f}|"
                        f"reserve_usd={reserve_usd:.2f}"
                    )
                    winner["_orch_pair_margin_usd"] = float(pair_margin)
                    winner["_orch_pair_cap_usd"] = float(pair_cap)
                    winner["_orch_pair_headroom_usd"] = float(headroom_for_resize)
                    winner["margin_usd"] = float(headroom_for_resize)
                    if notional_usd > 0:
                        winner["notional_usd"] = float(notional_usd * scale)
                    else:
                        winner["notional_usd"] = float(headroom_for_resize * lev)
                    resized = True
                    reason = "RESIZED_PAIR_CAP"
                elif margin_usd > usable_headroom and usable_headroom <= 0.0:
                    # Optional trim-to-hedge: free headroom by reducing main leg (strict gating).
                    trim_emitted = False
                    if is_hedge:
                        try:
                            min_roe = float(getattr(self.cfg, "TRIM_FOR_HEDGE_MIN_ROE_PCT", 10.0))
                        except Exception:
                            min_roe = 10.0
                        try:
                            max_trim = float(getattr(self.cfg, "TRIM_FOR_HEDGE_MAX_CLOSE_FRACTION", 0.10))
                        except Exception:
                            max_trim = 0.10
                        try:
                            cooldown_s = int(getattr(self.cfg, "TRIM_FOR_HEDGE_COOLDOWN_SEC", 900))
                        except Exception:
                            cooldown_s = 900

                        # Extract ROE from proposal metadata if provided.
                        roe = None
                        for k in ("main_roe_pct", "roe_pct", "current_roe_pct", "mfe_roe", "mfe_roe_pct"):
                            try:
                                if k in winner and winner.get(k) is not None:
                                    roe = float(winner.get(k))
                                    break
                            except Exception:
                                pass
                        if roe is None and isinstance(winner.get("metadata"), dict):
                            for k in ("main_roe_pct", "roe_pct", "current_roe_pct", "mfe_roe", "mfe_roe_pct"):
                                try:
                                    if k in winner.get("metadata") and winner.get("metadata").get(k) is not None:
                                        roe = float(winner.get("metadata").get(k))
                                        break
                                except Exception:
                                    pass

                        can_trim = bool(roe is not None and roe >= float(min_roe))
                        if can_trim and self.redis is not None:
                            try:
                                key = f"orch:trim_for_hedge:{acct}:{sym}"
                                if self.redis.get(key):
                                    can_trim = False
                            except Exception:
                                pass

                        if can_trim:
                            # Infer main side from hedge action
                            act_u = str(action or "").upper()
                            close_action = None
                            if "HEDGE_SHORT" in act_u:
                                close_action = "CLOSE_LONG"
                            elif "HEDGE_LONG" in act_u:
                                close_action = "CLOSE_SHORT"

                            if close_action:
                                winner = dict(winner)
                                winner["action"] = close_action
                                winner["action_name"] = close_action
                                winner["action_category"] = "PROTECTIVE"
                                winner["close_fraction"] = max(0.01, min(0.50, float(max_trim)))
                                winner["reduce_only"] = True
                                winner["risk_add"] = 0
                                winner["reasoning"] = "TRIM_FOR_HEDGE_HEADROOM"
                                winner["timeframe"] = str(winner.get("timeframe") or "multi")
                                winner["created_ts_ms"] = int(time.time() * 1000)
                                trim_emitted = True
                                reason = "TRIM_FOR_HEDGE_HEADROOM"
                                dropped = False
                                try:
                                    if self.redis is not None:
                                        self.redis.setex(f"orch:trim_for_hedge:{acct}:{sym}", int(cooldown_s), "1")
                                except Exception:
                                    pass
                                logger.warning(
                                    f"ORCH_TRIM_FOR_HEDGE sym={sym} roe={float(roe):.2f} close_fraction={float(winner.get('close_fraction')):.3f} "
                                    f"cap_usd={pair_cap:.2f} used_usd={pair_margin:.2f} headroom_usd={headroom:.2f}"
                                )

                    if not trim_emitted:
                        dropped = True
                        reason = "DROP_PAIR_CAP_NO_HEADROOM_RESERVE" if is_hedge and reserve_usd > 0 else "DROP_PAIR_CAP_NO_HEADROOM"
                        try:
                            logger.warning(
                                f"ORCH_PAIR_CAP_CHECK sym={sym} is_hedge={int(bool(is_hedge))} desired_usd={margin_usd:.2f} "
                                f"cap_usd={pair_cap:.2f} used_usd={pair_margin:.2f} headroom_usd={headroom:.2f} "
                                f"decision={reason}"
                            )
                        except Exception:
                            pass

            # Dust guard (min-notional): drop unexecutable tiny orders.
            try:
                final_notional = _to_float(winner.get("notional_usd"), notional_usd)
                if final_notional > 0.0 and float(final_notional) < float(min_notional_usd):
                    dropped = True
                    if is_hedge and resized:
                        reason = (
                            f"DROP_HEDGE_DOWNSIZED_BELOW_MIN|notional={final_notional:.2f}<min={min_notional_usd:.2f}"
                        )
                    else:
                        reason = f"DROP_MIN_NOTIONAL|notional={final_notional:.2f}<min={min_notional_usd:.2f}"
            except Exception:
                pass

        # Build detailed proof with score vectors and why others lost
        proof = self._build_detailed_proof(
            winner=winner,
            losers=losers,
            market_ctx=market_ctx,
            pair_margin=pair_margin,
            pair_cap=pair_cap,
            headroom=headroom,
            resized=resized,
            dropped=dropped,
            bypass_pair_cap=bypass_pair_cap,
            reason=reason,
        )

        return OrchestratorDecision(
            winner=winner,
            losers=losers,
            resized=resized,
            dropped=dropped,
            reason=reason,
            proof=proof,
        )
    
    def _compute_proposal_scores(self, proposal: Dict[str, Any], market_ctx: Any) -> Dict[str, float]:
        """
        Compute comparable utility scores for a proposal using MarketContext.
        
        Returns dict with:
        - edge_net_usd: Expected value after fees + slippage
        - fill_prob: Conditional fill probability
        - toxicity_score: Order book toxicity
        - liq_risk: Liquidation risk
        - capital_efficiency: Expected profit per margin-hour
        - utility: Final combined score
        """
        scores = {}
        
        try:
            # Base edge from proposal
            base_edge = _to_float(proposal.get("expected_edge_net") or proposal.get("edge_score"), 0.0)
            notional = _to_float(proposal.get("notional_usd"), 0.0)
            margin = _to_float(proposal.get("margin_usd"), 0.0)
            
            # Get market context values
            if market_ctx:
                spread_bps = _to_float(getattr(getattr(market_ctx, 'orderbook', None), 'spread_bps', 0), 0)
                toxicity = _to_float(getattr(getattr(market_ctx, 'orderbook', None), 'toxicity_score', 0), 0)
                liq_risk = _to_float(getattr(getattr(market_ctx, 'liquidation', None), 'liq_risk_score', 0), 0) if hasattr(market_ctx, 'liquidation') else 0
                imbalance = _to_float(getattr(getattr(market_ctx, 'orderbook', None), 'imbalance', 0), 0)
                data_quality = _to_float(getattr(market_ctx, 'data_quality_score', 1.0), 1.0)
                regime = getattr(getattr(market_ctx, 'regime', None), 'regime', 'unknown') if hasattr(market_ctx, 'regime') else 'unknown'
            else:
                spread_bps = 5.0  # Default
                toxicity = 0.2
                liq_risk = 0.2
                imbalance = 0.0
                data_quality = 0.7
                regime = 'unknown'
            
            # 1. Edge net USD (subtract slippage)
            slippage_penalty = spread_bps / 10000 * abs(notional)
            scores["edge_net_usd"] = base_edge - slippage_penalty
            
            # 2. Fill probability
            action = _action_key(proposal)
            if "CLOSE" in action or proposal.get("reduce_only"):
                scores["fill_prob"] = max(0.8, 0.99 - spread_bps / 1000)  # Taker
            else:
                scores["fill_prob"] = max(0.3, 0.5 + imbalance * 0.2 - toxicity * 0.3)  # Maker
            
            # 3. Toxicity
            scores["toxicity_score"] = toxicity
            
            # 4. Liquidation risk
            scores["liq_risk"] = liq_risk
            
            # 5. Capital efficiency
            if margin > 0 and scores["edge_net_usd"] > 0:
                scores["capital_efficiency"] = scores["edge_net_usd"] / margin
            else:
                scores["capital_efficiency"] = 0.0
            
            # 6. Regime-weighted utility
            weights = self._get_regime_weights(regime)
            
            utility = (
                weights["edge_weight"] * scores["edge_net_usd"] * 10
                + weights["fill_prob_weight"] * scores["fill_prob"] * 5
                - weights["toxicity_weight"] * scores["toxicity_score"] * 3
                - weights["liq_risk_weight"] * scores["liq_risk"] * 3
                + weights["capital_eff_weight"] * scores["capital_efficiency"] * 2
            )
            
            # Adjust for data quality
            utility *= data_quality
            
            # Boost for priority
            priority = int(proposal.get("priority") or 1)
            if priority >= 3:  # CRITICAL
                utility += 10
            elif priority >= 2:  # HIGH
                utility += 3
            
            scores["utility"] = utility
            scores["regime"] = regime
            scores["data_quality"] = data_quality
            
        except Exception as e:
            logger.debug(f"[ORCH_SCORE] Error computing scores: {e}")
            scores["utility"] = self._legacy_utility(proposal)
            scores["method"] = "fallback"
        
        return scores
    
    def _get_regime_weights(self, regime: str) -> Dict[str, float]:
        """Get regime-dependent weight multipliers."""
        if regime in ("trend_up", "trend_down"):
            return {
                "edge_weight": 1.2,
                "fill_prob_weight": 0.8,
                "toxicity_weight": 0.7,
                "liq_risk_weight": 1.0,
                "capital_eff_weight": 0.9,
            }
        elif regime == "range":
            return {
                "edge_weight": 0.9,
                "fill_prob_weight": 1.0,
                "toxicity_weight": 1.2,
                "liq_risk_weight": 1.1,
                "capital_eff_weight": 1.1,
            }
        elif regime == "squeeze":
            return {
                "edge_weight": 0.8,
                "fill_prob_weight": 1.3,
                "toxicity_weight": 1.4,
                "liq_risk_weight": 1.2,
                "capital_eff_weight": 0.8,
            }
        else:
            return {
                "edge_weight": 1.0,
                "fill_prob_weight": 1.0,
                "toxicity_weight": 1.0,
                "liq_risk_weight": 1.0,
                "capital_eff_weight": 1.0,
            }
    
    def _legacy_utility(self, proposal: Dict[str, Any]) -> float:
        """Fallback utility when market context unavailable."""
        urgency = _urgency_score(proposal)
        conf = _norm_conf(proposal.get("confidence") or proposal.get("model_confidence"))
        edge = _expected_edge_net(proposal)
        profit = _expected_profit_usd(proposal)
        
        return urgency * 5 + conf * 3 + edge * 2 + profit * 0.1
    
    def _check_vetoes(self, proposal: Dict[str, Any], market_ctx: Any) -> Optional[str]:
        """
        Check hard safety vetoes before utility comparison.
        Returns veto reason string if vetoed, None if OK.
        """
        action = _action_key(proposal)
        
        # 1. Data staleness veto (configurable)
        if market_ctx and getattr(market_ctx, 'is_stale', False):
            stale_reason = getattr(market_ctx, 'stale_reason', 'unknown')
            # Only veto for exposure-increasing actions in stale data
            if _is_hedge_action(action) or action.startswith("OPEN_") or action.startswith("INCREASE_"):
                # Allow if protective category (safety-critical)
                category = str(proposal.get("action_category") or "").upper()
                if category not in ("PROTECTIVE", "RECOVERY"):
                    # Allow stealth-stop STOP_LOSS hedges even when features/DQ are stale.
                    # These are safety actions and should not be fully suppressed by stale feature context.
                    try:
                        _src = str(proposal.get("source") or proposal.get("source_module") or "").lower()
                        _mc = proposal.get("market_context") or {}
                        _stop_type = str(_mc.get("stop_type") or "").upper() if isinstance(_mc, dict) else ""
                        _symu = str(proposal.get("symbol") or "").upper().strip()
                        if _stop_type == "STOP_LOSS" and "stealth" in _src and _is_hedge_action(action):
                            # region agent log
                            try:
                                if _symu in ("BANKUSDT", "ASTERUSDT"):
                                    import json as _aj
                                    _ts = int(time.time() * 1000)
                                    _payload = {
                                        "sessionId": "868108",
                                        "id": f"log_{_ts}_orch_stale_bypass_{_symu}",
                                        "timestamp": _ts,
                                        "location": "rl/tradeplan_orchestrator.py:_check_vetoes",
                                        "message": "stale_data_veto_bypassed_for_stoploss_hedge",
                                        "runId": "post-fix",
                                        "hypothesisId": "H6",
                                        "data": {
                                            "symbol": _symu,
                                            "action": str(action),
                                            "category": str(category),
                                            "source": str(_src),
                                            "stop_type": str(_stop_type),
                                            "stale_reason": str(stale_reason)[:160],
                                        },
                                    }
                                    with open(
                                        "/home/wali/Desktop/AI BOT/.cursor/debug-868108.log",
                                        "a",
                                        encoding="utf-8",
                                    ) as _f:
                                        _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
                            except Exception:
                                pass
                            # endregion
                            return None
                    except Exception:
                        pass
                    return f"STALE_DATA|{stale_reason}"
        
        # 2. No-loss compliance (for closes)
        if not proposal.get("no_loss_compliant", True):
            _cat_upper = str(proposal.get("action_category") or "").upper()
            _src_lower = str(proposal.get("source") or "").lower()
            _mc = proposal.get("market_context") or {}
            if not isinstance(_mc, dict):
                _mc = {}
            _roi_pct = float(
                proposal.get("roi_pct")
                or proposal.get("roe_pct")
                or proposal.get("pnl_pct")
                or _mc.get("roi_pct")
                or _mc.get("pnl_pct")
                or 0.0
            )
            _leverage = max(1.0, float(
                proposal.get("leverage")
                or proposal.get("effective_leverage")
                or _mc.get("leverage")
                or 1.0
            ))
            _deep_loss_thresh = -5.0 / max(1.0, _leverage / 10.0)
            _is_close_action = action.startswith("CLOSE")
            _is_roi_kill = _cat_upper == "PER_LEG_ROI_KILL" or _src_lower == "per_leg_roi_kill"
            if _is_roi_kill:
                logger.info(
                    "NO_LOSS_BYPASS_ROI_KILL | sym=%s roi=%.2f%% cat=%s — PER_LEG_ROI_KILL always bypasses no-loss",
                    proposal.get("symbol"), _roi_pct, _cat_upper,
                )
            elif _is_close_action and _roi_pct < _deep_loss_thresh:
                _icg_allows = True
                try:
                    from risk.intelligent_close_guard import evaluate_close
                    _icg_v = evaluate_close(
                        self.redis if hasattr(self, 'redis') else None,
                        proposal.get("symbol") or "",
                        str(proposal.get("side") or ("LONG" if "LONG" in action else ("SHORT" if "SHORT" in action else "")) or "").upper(),
                        close_reason=f"ORCH_DEEP_LOSS_OVERRIDE roi={_roi_pct:.2f} lev={_leverage:.1f} action={action}",
                        is_hard_emergency=False,
                    )
                    _icg_allows = (not _icg_v.should_defer) if _icg_v else True
                except Exception:
                    _icg_allows = True
                if _icg_allows:
                    logger.info(
                        "NO_LOSS_OVERRIDE | sym=%s roi=%.2f%% < %.2f%% (lev=%.0fx) — ICG allows emergency close",
                        proposal.get("symbol"), _roi_pct, _deep_loss_thresh, _leverage,
                    )
                else:
                    return "NO_LOSS_VIOLATION"
            else:
                return "NO_LOSS_VIOLATION"
        
        # 3. Execution feasibility (placeholder for future fill-prob checks)
        # scores = proposal.get("_scores") or {}
        # if scores.get("fill_prob", 1.0) < 0.1:
        #     return "LOW_FILL_PROB"
        
        return None
    
    def _build_detailed_proof(
        self,
        winner: Dict[str, Any],
        losers: List[Dict[str, Any]],
        market_ctx: Any,
        pair_margin: float,
        pair_cap: float,
        headroom: float,
        resized: bool,
        dropped: bool,
        bypass_pair_cap: bool,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Build detailed proof including:
        - Winner score vector
        - Context pointers
        - Why losers lost (top 2)
        """
        acct = _payload_account(winner)
        sym = _payload_symbol(winner)
        action = _action_key(winner)
        signal_source = str(winner.get("source") or winner.get("source_module") or "").lower()
        action_category = str(winner.get("action_category") or "").upper()
        
        # Winner scores
        winner_scores = winner.get("_scores") or {}
        
        # Context pointers
        ctx_id = winner.get("ctx_id") or (market_ctx.ctx_id if market_ctx and hasattr(market_ctx, 'ctx_id') else "")
        orderbook_ts = winner.get("orderbook_ts_ms") or (market_ctx.price_ts_ms if market_ctx and hasattr(market_ctx, 'price_ts_ms') else 0)
        liqmap_ts = winner.get("liqmap_ts_ms") or (market_ctx.created_ts_ms if market_ctx and hasattr(market_ctx, 'created_ts_ms') else 0)
        
        # Why losers lost (top 2)
        loser_reasons = []
        for p in losers[:2]:
            loser_scores = p.get("_scores") or {}
            winner_utility = winner_scores.get("utility", 0)
            loser_utility = loser_scores.get("utility", 0)
            
            # Determine main penalty
            if p.get("_veto_reason"):
                main_penalty = f"VETOED|{p.get('_veto_reason')}"
            elif loser_scores.get("toxicity_score", 0) > winner_scores.get("toxicity_score", 0) + 0.1:
                main_penalty = "lost_on_toxicity"
            elif loser_scores.get("liq_risk", 0) > winner_scores.get("liq_risk", 0) + 0.1:
                main_penalty = "lost_on_liq_risk"
            elif loser_scores.get("fill_prob", 0) < winner_scores.get("fill_prob", 0) - 0.1:
                main_penalty = "lost_on_fill_prob"
            elif loser_scores.get("edge_net_usd", 0) < winner_scores.get("edge_net_usd", 0):
                main_penalty = "lost_on_edge"
            else:
                main_penalty = "lost_on_utility"
            
            loser_reasons.append({
                "action": _action_key(p),
                "source": str(p.get("source") or p.get("source_module") or ""),
                "utility": round(loser_utility, 4),
                "utility_diff": round(winner_utility - loser_utility, 4),
                "main_penalty": main_penalty,
                "scores": {
                    k: round(v, 4) if isinstance(v, float) else v
                    for k, v in (loser_scores or {}).items()
                },
            })
        
        return {
            "ts_ms": int(time.time() * 1000),
            "account_id": acct,
            "symbol": sym,
            # Winner info
            "winner_action": action,
            "winner_source": signal_source,
            "winner_category": action_category,
            "winner_utility": round(winner_scores.get("utility", 0), 4),
            # Score vector
            "winner_scores": {
                "edge_net_usd": round(winner_scores.get("edge_net_usd", 0), 4),
                "fill_prob": round(winner_scores.get("fill_prob", 0), 4),
                "toxicity_score": round(winner_scores.get("toxicity_score", 0), 4),
                "liq_risk": round(winner_scores.get("liq_risk", 0), 4),
                "capital_efficiency": round(winner_scores.get("capital_efficiency", 0), 6),
                "utility": round(winner_scores.get("utility", 0), 4),
                "regime": winner_scores.get("regime", "unknown"),
                "data_quality": round(winner_scores.get("data_quality", 1.0), 2),
            },
            # Context pointers
            "ctx_id": ctx_id,
            "orderbook_ts_ms": orderbook_ts,
            "liqmap_ts_ms": liqmap_ts,
            "featureset_version": market_ctx.featureset_version if market_ctx and hasattr(market_ctx, 'featureset_version') else "",
            # Legacy fields
            "winner_conf": _norm_conf(winner.get("confidence") or winner.get("model_confidence")),
            "winner_edge": float(_expected_edge_net(winner)),
            "winner_urgency": float(_urgency_score(winner)),
            "winner_profit_usd": float(_expected_profit_usd(winner)),
            # Pair cap info
            "pair_margin_usd": float(pair_margin),
            "pair_cap_usd": float(pair_cap),
            "pair_headroom_usd": float(headroom),
            # Decision info
            "resized": bool(resized),
            "dropped": bool(dropped),
            "bypass_pair_cap": bool(bypass_pair_cap),
            "reason": reason,
            "proposal_count": 1 + len(losers),
            # Why others lost
            "losers": loser_reasons,
        }
    
    def _build_proof(self, winner, losers, market_ctx, all_vetoed=False):
        """Simplified proof builder for edge cases."""
        return self._build_detailed_proof(
            winner=winner,
            losers=losers,
            market_ctx=market_ctx,
            pair_margin=0,
            pair_cap=0,
            headroom=0,
            resized=False,
            dropped=all_vetoed,
            bypass_pair_cap=False,
            reason="ALL_VETOED" if all_vetoed else "OK",
        )

    def orchestrate_payloads(
        self,
        payloads: List[Dict[str, Any]],
        *,
        mode: str,
        canary_accounts: Optional[List[str]] = None,
        canary_symbols: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Returns: (final_payloads, proofs)

        - mode == "shadow": final_payloads == original payloads (no behavior change)
        - mode == "publish": final_payloads is 1-per-(acct,symbol) with feasibility resizing
        """
        mode = str(mode or "shadow").strip().lower()
        if mode in {"off", "disabled", "false", "0"}:
            return payloads, []

        canary_accounts_set = set([str(a).strip() for a in (canary_accounts or []) if str(a).strip()])
        canary_symbols_set = set([str(s).upper().strip() for s in (canary_symbols or []) if str(s).strip()])

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        passthrough: List[Dict[str, Any]] = []
        sidecars: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        for p in (payloads or []):
            acct = _payload_account(p)
            sym = _payload_symbol(p)
            act = _action_key(p)
            # Sidecar stop-management actions are allowed alongside trade actions.
            if _is_sidecar_action(act):
                # Deduplicate by (acct,sym,act): keep latest ts_ms if present (deterministic tie-breaker).
                key = (acct, sym, act)
                prev = sidecars.get(key)
                try:
                    prev_ts = _to_float((prev or {}).get("ts_ms") or (prev or {}).get("timestamp") or 0.0, 0.0)
                    cur_ts = _to_float(p.get("ts_ms") or p.get("timestamp") or 0.0, 0.0)
                except Exception:
                    prev_ts, cur_ts = 0.0, 0.0
                if prev is None or cur_ts >= prev_ts:
                    sidecars[key] = p
                continue
            if canary_accounts_set and acct not in canary_accounts_set:
                passthrough.append(p)
                continue
            if canary_symbols_set and sym not in canary_symbols_set:
                passthrough.append(p)
                continue
            grouped.setdefault((acct, sym), []).append(p)

        proofs: List[Dict[str, Any]] = []
        selected: List[Dict[str, Any]] = []

        for (acct, sym), props in sorted(grouped.items(), key=lambda t: (t[0][0], t[0][1])):
            try:
                dec = self.orchestrate_group(props)
                proofs.append(dec.proof)
                if dec.dropped:
                    # Drop publishing for this symbol this cycle (prevents publish→reject spam).
                    continue
                selected.append(dec.winner)
            except Exception as e:
                # In case of orchestrator failure, fall back safely.
                proofs.append(
                    {
                        "ts_ms": int(time.time() * 1000),
                        "account_id": acct,
                        "symbol": sym,
                        "reason": f"ORCH_ERROR:{e}",
                    }
                )
                selected.extend(props)

        if mode == "shadow":
            # Shadow: publish original payloads, only emit proofs
            return payloads, proofs

        # Publish: replace selected groups, plus passthrough groups
        final = passthrough + selected + list(sidecars.values())
        return final, proofs

