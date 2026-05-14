"""
risk/auto_deleverager.py — Automatic Position Deleverager (Layer 2).

Layer 1 (MarginGovernor) blocks new risk-adds when caps are breached.
Layer 2 (AutoDeleverager) **actively reduces** existing positions that already
exceed caps.  This is the only mathematically correct way to maintain a
%-of-equity cap under changing equity (CROSS margin, PnL drift, etc.).

Policy (deterministic, no model):
  1. If account IM/equity > cap  OR  MU > mu_cap:
       → reduce the worst-margin symbol's largest leg first
  2. If any symbol IM/equity > sym_cap:
       → reduce that symbol's largest leg
  3. **HEDGE-AWARE** (v2): When both legs exist on a symbol:
       → PAIR_REDUCE: reduce both legs proportionally to free margin
         without flipping net exposure (hedge_leg gets 60%, main 40%)
       → Uses main_leg tracking to know which leg is alpha-driven
  4. Reduction sizing:
       → Just enough to bring metric under (cap − hysteresis)
       → Clamped to a max % of leg notional per action (safety)
  5. Cadence:
       → At most 1 reduce per GOV_DELEVERAGE_CADENCE_SEC seconds
       → Stops as soon as healthy

Execution constraints:
  - reduce_only = True always
  - Never opens positions
  - Never flips
  - min cooldown between actions
  - Max reduction per action (configurable)
  - Overrides profit-only guard and SAFETY_BLOCK_PROTECTIVE_LOSS (configurable)

Kill-switch:  config.GOV_AUTO_DELEVERAGE_ENABLED  (default: True)

Usage in trader:
    from risk.auto_deleverager import AutoDeleverager, DeleverageOrder
    dlv = AutoDeleverager(redis_client)
    order = dlv.check_and_plan(account_id="primary")
    if order:
        # execute order.symbol, order.side, order.reduce_qty, ...
    # For hedge cages, check for pair-reduce orders too:
    pair = dlv.check_and_plan_pair(account_id="primary")
    if pair:
        # execute pair.hedge_leg_side, pair.main_leg_side ...
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

try:
    from risk.hedge_cage_manager import (
        HedgeCageDetector,
        MainLegTracker,
        HedgeCage,
        PairReduceOrder,
    )
except ImportError:
    HedgeCageDetector = None  # type: ignore[assignment,misc]
    MainLegTracker = None  # type: ignore[assignment,misc]
    HedgeCage = None  # type: ignore[assignment,misc]
    PairReduceOrder = None  # type: ignore[assignment,misc]

try:
    from risk.risk_state_machine import (
        RiskStateMachine,
        RiskStateSnapshot,
        RiskState,
        EdgeSignal,
    )
except ImportError:
    RiskStateMachine = None  # type: ignore[assignment,misc]
    RiskStateSnapshot = None  # type: ignore[assignment,misc]
    RiskState = None  # type: ignore[assignment,misc]
    EdgeSignal = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _cfg(key: str, default):
    if config is not None:
        val = getattr(config, key, None)
        if val is not None:
            return val
    return default


def _sf(v, default: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        if v is None:
            return default
        out = float(v)
        return default if out != out else out  # NaN guard
    except Exception:
        return default


# ─── data classes ───────────────────────────────────────────────────────────

@dataclass
class PositionLeg:
    symbol: str
    side: str           # "LONG" or "SHORT"
    size: float         # absolute quantity
    entry_price: float
    mark_price: float
    initial_margin: float
    notional_usd: float
    unrealized_pnl: float
    leverage: float
    roe_pct: float


@dataclass
class DeleverageOrder:
    """Instruction for the trader to execute a reduce-only partial close."""
    symbol: str
    side: str               # "LONG" or "SHORT" — the leg to reduce
    reduce_qty: float       # absolute qty to close
    reduce_margin_usd: float  # approximate margin freed
    reduce_pct: float       # fraction of leg being closed (0.0-1.0)
    reason_code: str        # machine-readable
    reason: str             # human-readable
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def action_name(self) -> str:
        return f"PARTIAL_CLOSE_{self.side}"

    @property
    def is_pair_reduce(self) -> bool:
        return bool(self.meta.get("pair_reduce"))

    @property
    def override_profit_guard(self) -> bool:
        """Deleverage orders must bypass profit-only guard."""
        return bool(_cfg("GOV_DELEVERAGE_OVERRIDE_PROFIT_GUARD", True))

    @property
    def override_safety_block(self) -> bool:
        """Deleverage orders must bypass SAFETY_BLOCK_PROTECTIVE_LOSS."""
        return bool(_cfg("GOV_DELEVERAGE_OVERRIDE_SAFETY_BLOCK", True))


@dataclass
class DeleverageCheckResult:
    """Full diagnostic result from a deleverager check."""
    needed: bool
    orders: List[DeleverageOrder]
    account_margin_pct: float
    mu_pct: float
    equity: float
    violations: List[str]
    meta: Dict[str, Any] = field(default_factory=dict)


# ─── core deleverager ──────────────────────────────────────────────────────

class AutoDeleverager:
    """
    Periodically checks account/symbol margin caps and produces
    reduce-only orders to bring the account back under limits.

    v2: Hedge-aware — detects hedge cages and uses PAIR_REDUCE
    to reduce both legs proportionally instead of blindly picking
    the largest leg (which could accidentally expose the main leg).
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._last_action_ts: float = 0.0
        self._action_count: int = 0

        # Hedge cage awareness
        self._main_leg_tracker = None
        self._cage_detector = None
        try:
            if MainLegTracker is not None:
                self._main_leg_tracker = MainLegTracker(redis_client)
            if HedgeCageDetector is not None:
                self._cage_detector = HedgeCageDetector(redis_client, self._main_leg_tracker)
        except Exception:
            pass

        # Risk state machine (v3: stateful enforcement). When disabled in config,
        # do not attach RSM — otherwise evaluate() returns legacy "always EMERGENCY"
        # and state_machine mode bypasses hard thresholds (equity bleed from churn).
        self._risk_sm: Optional[Any] = None
        try:
            if RiskStateMachine is not None and bool(_cfg("RISK_STATE_MACHINE_ENABLED", True)):
                self._risk_sm = RiskStateMachine(redis_client)
        except Exception:
            pass

    # ── reduce-only latch (Fix #1) ─────────────────────────────────────

    def _set_reduce_only_latch(self, account_id: str) -> None:
        """Set Redis latch blocking all risk-adds for N seconds after deleverage."""
        try:
            latch_enabled = bool(_cfg("REDUCE_ONLY_LATCH_ENABLED", True))
            if not latch_enabled or not self.redis:
                return
            latch_sec = int(_cfg("REDUCE_ONLY_LATCH_SECONDS", 900))
            prefix = str(_cfg("REDUCE_ONLY_LATCH_KEY_PREFIX", "risk:reduce_only_until"))
            key = f"{prefix}:{account_id}"
            expiry_ms = int(time.time() * 1000) + (latch_sec * 1000)
            self.redis.set(key, str(expiry_ms), ex=latch_sec + 10)  # +10s buffer on TTL
            logger.warning(
                "REDUCE_ONLY_LATCH_SET | account=%s | duration=%ds | key=%s | expires_ms=%d",
                account_id, latch_sec, key, expiry_ms,
            )
        except Exception as e:
            logger.debug("REDUCE_ONLY_LATCH_SET_ERR | %s", e)

    @staticmethod
    def check_reduce_only_latch(redis_client, account_id: str) -> bool:
        """
        Check if reduce-only latch is active.
        Returns True if risk-adds should be BLOCKED (latch active).
        Static method so orchestrator/trader can call without instantiation.
        """
        try:
            latch_enabled = bool(_cfg("REDUCE_ONLY_LATCH_ENABLED", True))
            if not latch_enabled or not redis_client:
                return False
            prefix = str(_cfg("REDUCE_ONLY_LATCH_KEY_PREFIX", "risk:reduce_only_until"))
            key = f"{prefix}:{account_id}"
            val = redis_client.get(key)
            if val is None:
                return False
            expiry_ms = int(val)
            now_ms = int(time.time() * 1000)
            if now_ms < expiry_ms:
                return True  # Latch still active
            # Expired — clean up
            redis_client.delete(key)
            return False
        except Exception:
            return False  # Fail-open

    # ── public API ──────────────────────────────────────────────────────

    def check_and_plan(
        self,
        account_id: str,
        *,
        # Caller can pass pre-fetched balance data to avoid extra Redis reads
        equity: Optional[float] = None,
        total_initial_margin: Optional[float] = None,
        margin_used_pct: Optional[float] = None,
        margin_ratio_pct: Optional[float] = None,
    ) -> Optional[DeleverageOrder]:
        """
        Check if deleveraging is needed and return the single best order.

        v3: Gated by Risk State Machine.
          - NORMAL/STRESSED: returns None (no deleverage)
          - EMERGENCY: only fires after breach_streak >= N consecutive checks
          - Edge-aware: uses regime data to decide which leg to cut

        Returns None if no deleveraging needed, not in EMERGENCY, or on cooldown.
        Returns a DeleverageOrder for the highest-priority reduction.
        """
        enabled = bool(_cfg("GOV_AUTO_DELEVERAGE_ENABLED", True))
        if not enabled:
            return None

        # Cadence gate (still needed — prevents execution spam within EMERGENCY)
        cadence_sec = float(_cfg("GOV_DELEVERAGE_CADENCE_SEC", 30.0))
        now = time.time()
        if (now - self._last_action_ts) < cadence_sec:
            return None

        # Fetch account state
        acct = self._get_account_state(
            account_id,
            equity_override=equity,
            total_im_override=total_initial_margin,
            mu_override=margin_used_pct,
            mr_override=margin_ratio_pct,
        )

        eq = acct["equity"]
        total_im = acct["total_initial_margin"]
        mu_pct = acct["margin_used_pct"]

        if eq <= 0:
            logger.debug("DELEVERAGER_SKIP | no equity data for %s", account_id)
            return None

        current_acct_pct = total_im / eq if eq > 0 else 0.0

        # ── RISK STATE MACHINE GATE ────────────────────────────────────
        # This is the key change: only fire in EMERGENCY state with
        # persistent breach streak, not on every snapshot breach.
        risk_snap = None
        if self._risk_sm is not None:
            risk_snap = self._risk_sm.evaluate(
                account_id=account_id,
                mu_pct=mu_pct,
                acct_im_pct=current_acct_pct,
                equity=eq,
                total_im=total_im,
            )
            if not risk_snap.deleverage_allowed:
                # NORMAL or STRESSED — no deleverage, just observe
                return None
            # EMERGENCY with sufficient breach streak — proceed

        # Thresholds (reuse governor caps for violation detection)
        max_acct_pct = float(_cfg("GOV_MAX_ACCOUNT_MARGIN_PCT", 0.45))
        mu_cap = float(_cfg("GOV_MAX_ACCOUNT_MU_PCT", 50.0))
        max_sym_pct = float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT", 0.20))
        hysteresis = float(_cfg("GOV_DELEVERAGE_HYSTERESIS_PCT", 0.03))  # 3pp below cap

        # ── FIX #2: Hard-emergency only — soft breaches block (governor),
        # only hard breaches force-close (deleverager) ─────────────────
        deleverage_mode = str(_cfg("GOV_DELEVERAGE_MODE", "hard_only")).lower()
        soft_only_block = bool(_cfg("DELEVERAGE_SOFT_ONLY_BLOCK", True))
        hard_mu_threshold = float(_cfg("DELEVERAGE_HARD_MU_THRESHOLD", 85.0))
        hard_im_threshold = float(_cfg("DELEVERAGE_HARD_IM_THRESHOLD", 0.85))

        # GOV_DELEVERAGE_MODE gate:
        #   "state_machine" = trust RSM EMERGENCY decision, skip hard threshold
        #   "hard_only"     = force soft_only_block True (old behavior)
        rsm_emergency = (risk_snap is not None and risk_snap.deleverage_allowed)
        if deleverage_mode == "state_machine" and rsm_emergency:
            # RSM says EMERGENCY with sufficient breach streak — bypass hard threshold
            soft_only_block = False
            logger.info(
                "DELEVERAGER_RSM_BYPASS | account=%s | mode=state_machine | "
                "risk_state=EMERGENCY | streak=%d/%d | mu=%.1f%% | im=%.1f%% | "
                "action=BYPASS_HARD_THRESHOLD",
                account_id,
                risk_snap.breach_streak, risk_snap.breach_streak_required,
                mu_pct, current_acct_pct * 100,
            )
        elif deleverage_mode == "hard_only":
            soft_only_block = True

        if soft_only_block:
            # Only proceed if we're in hard-emergency territory
            is_hard_mu = mu_pct >= hard_mu_threshold if mu_pct > 0 else False
            is_hard_im = current_acct_pct >= hard_im_threshold
            if not (is_hard_mu or is_hard_im):
                # Soft breach — governor handles by blocking entries, don't force-close
                if current_acct_pct > max_acct_pct or (mu_pct > mu_cap if mu_pct > 0 else False):
                    logger.warning(
                        "DELEVERAGER_SOFT_BREACH_SKIP | account=%s | "
                        "acct_im=%.1f%% (soft_cap=%.0f%% hard=%.0f%%) | mu=%.1f%% (soft_cap=%.0f%% hard=%.0f%%) | "
                        "risk_state=%s | action=BLOCK_ONLY (proactive health monitor handles soft zone)",
                        account_id,
                        current_acct_pct * 100, max_acct_pct * 100, hard_im_threshold * 100,
                        mu_pct, mu_cap, hard_mu_threshold,
                        risk_snap.state.value if risk_snap and hasattr(risk_snap, 'state') else "N/A",
                    )
                return None

        violations: List[str] = []

        # ── I1: Account-level check ────────────────────────────────────
        acct_breach = current_acct_pct > max_acct_pct
        mu_breach = mu_pct > mu_cap if mu_pct > 0 else False

        if acct_breach:
            violations.append(
                f"ACCOUNT_IM: {current_acct_pct*100:.1f}% > {max_acct_pct*100:.0f}%"
            )
        if mu_breach:
            violations.append(
                f"ACCOUNT_MU: {mu_pct:.1f}% > {mu_cap:.0f}%"
            )

        # ── I2: Symbol-level check ─────────────────────────────────────
        positions = self._get_all_positions(account_id)
        sym_violations: Dict[str, float] = {}  # symbol -> current_pct

        for pos in positions:
            sym_pct = pos.initial_margin / eq if eq > 0 else 0.0
            if sym_pct > max_sym_pct:
                sym_violations[pos.symbol] = sym_pct
                violations.append(
                    f"SYMBOL_{pos.symbol}_{pos.side}: {sym_pct*100:.1f}% > {max_sym_pct*100:.0f}%"
                )

        if not violations:
            return None

        # Per-symbol IM/equity over cap alone is a *soft* structural issue: MarginGovernor
        # should block new risk-adds. Auto-deleverage in EMERGENCY used to bypass
        # DELEVERAGE_HARD_* and cut anyway → fee bleed. Require hard MU/IM unless opted out.
        _sym_only = bool(sym_violations) and (not acct_breach) and (not mu_breach)
        if _sym_only and bool(_cfg("DELEVERAGE_SYMBOL_VIOLATION_REQUIRES_HARD_EMERGENCY", True)):
            _hm = float(_cfg("DELEVERAGE_HARD_MU_THRESHOLD", 90.0))
            _hi = float(_cfg("DELEVERAGE_HARD_IM_THRESHOLD", 0.90))
            _hard = (mu_pct >= _hm if mu_pct > 0 else False) or (current_acct_pct >= _hi)
            if not _hard:
                logger.info(
                    "DELEVERAGER_SKIP_SYMBOL_ONLY | account=%s | mu=%.1f%% im=%.1f%% | "
                    "symbols=%s | hard requires mu>=%.0f%% or im>=%.0f%%",
                    account_id,
                    mu_pct,
                    current_acct_pct * 100,
                    list(sym_violations.keys())[:8],
                    _hm,
                    _hi * 100,
                )
                return None

        # ── Phase 4: ICG aggregate hold-score deferral ─────────────────────
        # Before planning deleverage, check if positions are in favorable trends.
        # Only proceed with deleverage if ICG agrees or if HARD EMERGENCY.
        _dlv_hard_mu = float(_cfg("DELEVERAGE_HARD_MU_THRESHOLD", 85.0))
        _dlv_hard_im = float(_cfg("DELEVERAGE_HARD_IM_THRESHOLD", 0.85))
        _is_dlv_hard = (mu_pct >= _dlv_hard_mu) or (current_acct_pct >= _dlv_hard_im)
        if not _is_dlv_hard and positions:
            try:
                from risk.intelligent_close_guard import evaluate_close as _dlv_icg_eval
                _hold_scores = []
                for _pos in positions[:5]:
                    try:
                        _icg_v = _dlv_icg_eval(
                            self.redis, _pos.symbol, _pos.side,
                            close_reason=f"DELEVERAGER_PLAN mu={mu_pct:.1f}%",
                            is_hard_emergency=False,
                        )
                        _hold_scores.append(_icg_v.hold_score)
                    except Exception:
                        pass
                if _hold_scores:
                    _avg_hold = sum(_hold_scores) / len(_hold_scores)
                    _defer_thresh = float(_cfg("ICG_DEFER_THRESHOLD", 0.55))
                    if _avg_hold >= _defer_thresh:
                        logger.info(
                            "DELEVERAGER_ICG_DEFER | account=%s | avg_hold=%.3f >= %.2f | "
                            "mu=%.1f%% | positions in favorable trends — deferring",
                            account_id, _avg_hold, _defer_thresh, mu_pct,
                        )
                        return None
            except Exception as _dlv_icg_err:
                logger.debug("DELEVERAGER_ICG_ERR | %s", _dlv_icg_err)

        # ── Pick the worst offender (HEDGE-AWARE v2) ───────────────────────
        # Priority: account-level breach first (more dangerous), then symbol-level
        # When both legs exist on a symbol → use pair-reduce instead of single leg

        if not positions:
            logger.warning(
                "DELEVERAGER_NO_POSITIONS | account=%s | violations=%s",
                account_id, violations,
            )
            return None

        # Sort by initial_margin descending — reduce the biggest first
        positions_sorted = sorted(positions, key=lambda p: p.initial_margin, reverse=True)

        # ── Hedge-aware: detect cages ───────────────────────────────────
        hedge_aware = bool(_cfg("GOV_DELEVERAGE_HEDGE_AWARE", True))
        cages_by_sym: Dict[str, Any] = {}
        if hedge_aware and self._cage_detector:
            try:
                cages = self._cage_detector.detect_cages(account_id)
                cages_by_sym = {c.symbol: c for c in cages}
            except Exception as e:
                logger.debug("DELEVERAGER_CAGE_DETECT_ERR | %s", e)

        # If there are symbol-level violations, prioritize those symbols
        # Otherwise take the largest position globally
        target_leg: Optional[PositionLeg] = None
        pair_reduce_order: Optional[Any] = None  # PairReduceOrder if cage

        if sym_violations:
            # Pick the worst symbol violation's largest leg
            worst_sym = max(sym_violations, key=sym_violations.get)  # type: ignore[arg-type]

            # ── If worst symbol is a cage → pair-reduce ─────────────────
            if worst_sym in cages_by_sym:
                cage = cages_by_sym[worst_sym]
                sym_pct = sym_violations[worst_sym]
                target_sym_pct = max_sym_pct - hysteresis
                desired_sym_im = eq * target_sym_pct
                margin_excess = cage.gross_im - desired_sym_im
                if margin_excess > 0:
                    pair_reduce_order = self._cage_detector.compute_pair_reduce(
                        cage, margin_to_free=margin_excess, equity=eq,
                    )
                    if pair_reduce_order:
                        self._last_action_ts = time.time()
                        self._action_count += 1
                        self._set_reduce_only_latch(account_id)  # Fix #1
                        logger.warning(
                            "DELEVERAGER_PAIR_REDUCE | account=%s | #%d | symbol=%s | "
                            "hedge(%s)=%.1f%% main(%s)=%.1f%% | margin_freed=$%.2f | "
                            "violations=%s | reduce_only_latch=SET",
                            account_id, self._action_count, worst_sym,
                            pair_reduce_order.hedge_leg_side, pair_reduce_order.hedge_leg_reduce_pct * 100,
                            pair_reduce_order.main_leg_side, pair_reduce_order.main_leg_reduce_pct * 100,
                            pair_reduce_order.total_margin_freed_est, violations,
                        )
                        # Return the hedge leg reduction as the primary order
                        # (the pair reduce is stored in meta for the trader to execute both)
                        return DeleverageOrder(
                            symbol=worst_sym,
                            side=pair_reduce_order.hedge_leg_side,
                            reduce_qty=pair_reduce_order.hedge_leg_reduce_qty,
                            reduce_margin_usd=round(pair_reduce_order.total_margin_freed_est * 0.6, 2),
                            reduce_pct=round(pair_reduce_order.hedge_leg_reduce_pct, 6),
                            reason_code="GOV_PAIR_REDUCE",
                            reason=pair_reduce_order.reason,
                            meta={
                                "account_id": account_id,
                                "equity": round(eq, 2),
                                "total_im": round(total_im, 2),
                                "mu_pct": round(mu_pct, 2),
                                "pair_reduce": True,
                                "main_leg_side": pair_reduce_order.main_leg_side,
                                "main_leg_reduce_pct": pair_reduce_order.main_leg_reduce_pct,
                                "main_leg_reduce_qty": pair_reduce_order.main_leg_reduce_qty,
                                "cage_age_sec": round(cages_by_sym[worst_sym].cage_age_sec, 0),
                                "violations": violations,
                                "action_number": self._action_count,
                            },
                        )

            # Fallback: single-leg reduction on worst symbol
            sym_legs = [p for p in positions_sorted if p.symbol == worst_sym]
            if sym_legs:
                ranked_sym = self._rank_sym_legs_for_deleverage(
                    sym_legs, is_hard_emergency=_is_dlv_hard
                )
                # In a cage, prefer reducing the hedge leg (non-main)
                if worst_sym in cages_by_sym and self._main_leg_tracker:
                    hedge_side = self._main_leg_tracker.get_hedge_side(account_id, worst_sym)
                    if hedge_side:
                        hedge_legs = [p for p in ranked_sym if p.side == hedge_side]
                        target_leg = hedge_legs[0] if hedge_legs else ranked_sym[0]
                    else:
                        target_leg = ranked_sym[0]
                else:
                    target_leg = ranked_sym[0]

        # Account-level breach: check for cages among top margin positions
        if target_leg is None and acct_breach:
            # Check if the biggest margin consumer is a cage
            top_sym = positions_sorted[0].symbol if positions_sorted else None
            if top_sym and top_sym in cages_by_sym:
                cage = cages_by_sym[top_sym]
                target_acct = max_acct_pct - hysteresis
                desired_im = eq * target_acct
                margin_excess = total_im - desired_im
                if margin_excess > 0:
                    pair_reduce_order = self._cage_detector.compute_pair_reduce(
                        cage, margin_to_free=margin_excess, equity=eq,
                    )
                    if pair_reduce_order:
                        self._last_action_ts = time.time()
                        self._action_count += 1
                        self._set_reduce_only_latch(account_id)  # Fix #1
                        logger.warning(
                            "DELEVERAGER_PAIR_REDUCE | account=%s | #%d | symbol=%s | "
                            "hedge(%s)=%.1f%% main(%s)=%.1f%% | margin_freed=$%.2f | "
                            "violations=%s | reduce_only_latch=SET",
                            account_id, self._action_count, top_sym,
                            pair_reduce_order.hedge_leg_side, pair_reduce_order.hedge_leg_reduce_pct * 100,
                            pair_reduce_order.main_leg_side, pair_reduce_order.main_leg_reduce_pct * 100,
                            pair_reduce_order.total_margin_freed_est, violations,
                        )
                        return DeleverageOrder(
                            symbol=top_sym,
                            side=pair_reduce_order.hedge_leg_side,
                            reduce_qty=pair_reduce_order.hedge_leg_reduce_qty,
                            reduce_margin_usd=round(pair_reduce_order.total_margin_freed_est * 0.6, 2),
                            reduce_pct=round(pair_reduce_order.hedge_leg_reduce_pct, 6),
                            reason_code="GOV_PAIR_REDUCE",
                            reason=pair_reduce_order.reason,
                            meta={
                                "account_id": account_id,
                                "equity": round(eq, 2),
                                "total_im": round(total_im, 2),
                                "mu_pct": round(mu_pct, 2),
                                "pair_reduce": True,
                                "main_leg_side": pair_reduce_order.main_leg_side,
                                "main_leg_reduce_pct": pair_reduce_order.main_leg_reduce_pct,
                                "main_leg_reduce_qty": pair_reduce_order.main_leg_reduce_qty,
                                "cage_age_sec": round(cages_by_sym[top_sym].cage_age_sec, 0),
                                "violations": violations,
                                "action_number": self._action_count,
                            },
                        )

        if target_leg is None:
            # ── Edge-aware single-leg selection ────────────────────────
            # When no specific target, use edge feed to prefer cutting
            # the leg that opposes current market edge.
            target_leg = self._pick_leg_by_edge(positions_sorted, account_id)

        # Prefer not to cut legs that match fresh high-confidence trainer:intent
        # (unless hard MU/IM — survival). Reduces churn vs model direction.
        target_leg = self._trainer_aware_resolved_target(
            target_leg, positions_sorted, is_hard_emergency=_is_dlv_hard
        )

        # ── Compute reduction size ──────────────────────────────────────
        order = self._compute_reduction(
            target_leg=target_leg,
            equity=eq,
            total_im=total_im,
            mu_pct=mu_pct,
            max_acct_pct=max_acct_pct,
            mu_cap=mu_cap,
            max_sym_pct=max_sym_pct,
            hysteresis=hysteresis,
            acct_breach=acct_breach or mu_breach,
            sym_breach=target_leg.symbol in sym_violations,
            violations=violations,
            account_id=account_id,
        )

        if order:
            self._last_action_ts = now
            self._action_count += 1

            # Enrich meta with risk state + edge info
            state_label = risk_snap.state.value if risk_snap else "LEGACY"
            streak_label = f"{risk_snap.breach_streak}/{risk_snap.breach_streak_required}" if risk_snap else "n/a"
            edge = self._get_edge_for_symbol(order.symbol)
            order.meta["risk_state"] = state_label
            order.meta["breach_streak"] = streak_label
            order.meta["edge_direction"] = edge.direction if edge else "UNKNOWN"
            order.meta["edge_confidence"] = round(edge.confidence, 3) if edge else 0.0

            # ── FIX #1: SET reduce-only latch ─────────────────────────
            # Blocks ALL risk-adds for REDUCE_ONLY_LATCH_SECONDS after
            # any deleverage action. Stops the churn loop.
            self._set_reduce_only_latch(account_id)

            logger.warning(
                "DELEVERAGER_ORDER | account=%s | #%d | state=%s | streak=%s | "
                "symbol=%s | side=%s | edge=%s | "
                "reduce_qty=%.6f | reduce_margin=$%.2f | reduce_pct=%.1f%% | "
                "reason=%s | violations=%s | reduce_only_latch=SET",
                account_id, self._action_count, state_label, streak_label,
                order.symbol, order.side,
                edge.direction if edge else "UNKNOWN",
                order.reduce_qty, order.reduce_margin_usd, order.reduce_pct * 100,
                order.reason_code, violations,
            )

        return order

    def check_full_diagnostic(
        self,
        account_id: str,
        *,
        equity: Optional[float] = None,
        total_initial_margin: Optional[float] = None,
        margin_used_pct: Optional[float] = None,
    ) -> DeleverageCheckResult:
        """
        Full diagnostic — returns all violations and all possible orders.
        Used for monitoring/alerting, NOT for execution (use check_and_plan).
        """
        enabled = bool(_cfg("GOV_AUTO_DELEVERAGE_ENABLED", True))
        acct = self._get_account_state(
            account_id,
            equity_override=equity,
            total_im_override=total_initial_margin,
            mu_override=margin_used_pct,
        )
        eq = acct["equity"]
        total_im = acct["total_initial_margin"]
        mu_pct = acct["margin_used_pct"]

        if eq <= 0:
            return DeleverageCheckResult(
                needed=False, orders=[], account_margin_pct=0.0,
                mu_pct=0.0, equity=0.0, violations=["no_equity_data"],
            )

        max_acct_pct = float(_cfg("GOV_MAX_ACCOUNT_MARGIN_PCT", 0.45))
        mu_cap = float(_cfg("GOV_MAX_ACCOUNT_MU_PCT", 50.0))
        max_sym_pct = float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT", 0.20))
        current_acct_pct = total_im / eq if eq > 0 else 0.0

        violations: List[str] = []
        if current_acct_pct > max_acct_pct:
            violations.append(f"ACCOUNT_IM={current_acct_pct*100:.1f}%>{max_acct_pct*100:.0f}%")
        if mu_pct > mu_cap:
            violations.append(f"MU={mu_pct:.1f}%>{mu_cap:.0f}%")

        positions = self._get_all_positions(account_id)
        for pos in positions:
            sym_pct = pos.initial_margin / eq if eq > 0 else 0.0
            if sym_pct > max_sym_pct:
                violations.append(f"{pos.symbol}_{pos.side}={sym_pct*100:.1f}%>{max_sym_pct*100:.0f}%")

        return DeleverageCheckResult(
            needed=len(violations) > 0 and enabled,
            orders=[],  # Full order computation only via check_and_plan
            account_margin_pct=round(current_acct_pct * 100, 2),
            mu_pct=round(mu_pct, 2),
            equity=round(eq, 2),
            violations=violations,
            meta={
                "total_im": round(total_im, 2),
                "positions_count": len(positions),
                "enabled": enabled,
            },
        )

    # ── private: trainer-aware leg resolution ───────────────────────────────

    def _trainer_leg_aligns_with_intent(self, leg: PositionLeg) -> bool:
        """True if this leg matches fresh high-confidence trainer:intent (defer cut)."""
        if not self.redis or not bool(_cfg("GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT", True)):
            return False
        try:
            from risk.trainer_intent import position_aligns_with_intent

            aligns, _ = position_aligns_with_intent(self.redis, leg.symbol, leg.side)
            return bool(aligns)
        except Exception:
            return False

    def _rank_sym_legs_for_deleverage(
        self, sym_legs: List[PositionLeg], *, is_hard_emergency: bool
    ) -> List[PositionLeg]:
        """
        Prefer cutting legs that are NOT trainer-aligned (same min-confidence rules as ROI kill).
        Tie-break by larger initial margin (legacy behavior).
        """
        if not sym_legs:
            return sym_legs
        if is_hard_emergency or not bool(_cfg("GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT", True)):
            return sorted(sym_legs, key=lambda p: p.initial_margin, reverse=True)

        def sort_key(p: PositionLeg) -> tuple:
            aligned = self._trainer_leg_aligns_with_intent(p)
            # misaligned first: aligned=False → 0, aligned=True → 1
            return (1 if aligned else 0, -float(p.initial_margin or 0.0))

        return sorted(sym_legs, key=sort_key)

    def _trainer_aware_resolved_target(
        self,
        target: PositionLeg,
        positions_sorted: List[PositionLeg],
        *,
        is_hard_emergency: bool,
    ) -> PositionLeg:
        """
        If the chosen cut leg is trainer-aligned, swap to another leg when possible:
        1) other side on same symbol that is not aligned
        2) another symbol's leg that is not aligned
        Hard emergency: no swap (survival).
        """
        if is_hard_emergency or not bool(_cfg("GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT", True)):
            return target
        if not self._trainer_leg_aligns_with_intent(target):
            return target
        try:
            for p in positions_sorted:
                if p.symbol == target.symbol and p.side != target.side:
                    if float(p.initial_margin or 0.0) <= 0 or float(p.size or 0.0) <= 0:
                        continue
                    if not self._trainer_leg_aligns_with_intent(p):
                        logger.info(
                            "DELEVERAGER_TRAINER_LEG_SWAP | sym=%s | avoid=%s (trainer-aligned) → cut=%s",
                            target.symbol,
                            target.side,
                            p.side,
                        )
                        return p
            for p in positions_sorted:
                if p.symbol == target.symbol:
                    continue
                if float(p.initial_margin or 0.0) <= 0 or float(p.size or 0.0) <= 0:
                    continue
                if not self._trainer_leg_aligns_with_intent(p):
                    logger.info(
                        "DELEVERAGER_TRAINER_LEG_SWAP_SYM | avoid=%s:%s → cut=%s:%s",
                        target.symbol,
                        target.side,
                        p.symbol,
                        p.side,
                    )
                    return p
        except Exception as e:
            logger.debug("DELEVERAGER_TRAINER_SWAP_ERR | %s", e)
        return target

    def _clamp_cut_side_for_trainer(
        self,
        symbol: str,
        preferred_cut_side: str,
        positions_sorted: List[PositionLeg],
    ) -> str:
        """
        If votes/edge say "cut LONG" but trainer (high-confidence) says LONG, and the
        symbol is hedged, cut the other leg instead so we do not fight the model.
        """
        if not self.redis or not bool(_cfg("GOV_DELEVERAGE_TRAINER_AWARE_LEG_SELECT", True)):
            return preferred_cut_side
        try:
            from risk.trainer_intent import get_intent

            intent = get_intent(self.redis, symbol)
            if (
                not intent
                or not intent.is_directional
                or intent.is_stale
                or not intent.is_high_confidence
            ):
                return preferred_cut_side
            keep_side = str(intent.direction).upper()
            pcs = str(preferred_cut_side or "").upper()
            if pcs != keep_side:
                return preferred_cut_side
            same_sym = [p for p in positions_sorted if p.symbol == symbol]
            if len(same_sym) < 2:
                return preferred_cut_side
            for p in same_sym:
                if str(p.side).upper() != keep_side:
                    logger.info(
                        "DELEVERAGER_TRAINER_VOTE_CLAMP | sym=%s | trainer_keep=%s | cut→%s",
                        symbol,
                        keep_side,
                        p.side,
                    )
                    return str(p.side).upper()
        except Exception:
            pass
        return preferred_cut_side

    # ── private: edge-aware leg selection ───────────────────────────────

    def _pick_leg_by_edge(
        self, positions_sorted: List[PositionLeg], account_id: str,
    ) -> PositionLeg:
        """
        Edge-aware leg selection for single-leg reduction.

        Uses regime, unified features (2000+ keys), CoinAPI orderbook, and
        trainer intent to determine which leg to cut.  Prefers cutting the
        leg opposing the strongest market signal.

        Fallback: largest leg (v1 behavior).
        """
        if not positions_sorted:
            raise ValueError("No positions to pick from")

        top = positions_sorted[0]

        # Gather directional signals from multiple data sources
        direction_votes = 0.0  # positive = bullish, negative = bearish
        vote_count = 0

        # Source 1: Regime edge (existing)
        edge = self._get_edge_for_symbol(top.symbol)
        if edge and edge.direction != "NEUTRAL" and edge.confidence >= 0.25:
            vote_count += 1
            direction_votes += edge.tf_alignment  # already signed

        # Source 2: Unified features — momentum indicators
        if self.redis:
            try:
                for tf in ["5m", "15m", "1h"]:
                    raw = self.redis.hgetall(f"unified_features:{top.symbol}:{tf}")
                    if not raw:
                        continue
                    feat = {}
                    for k, v in raw.items():
                        kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                        try:
                            feat[kk] = float(v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v)
                        except (ValueError, TypeError):
                            pass

                    rsi = feat.get("rsi_14", 50.0)
                    if rsi > 0:
                        vote_count += 1
                        direction_votes += (rsi - 50.0) / 50.0 * 0.3

                    macd_h = feat.get("macd_histogram", 0.0)
                    if macd_h != 0:
                        vote_count += 1
                        direction_votes += (1.0 if macd_h > 0 else -1.0) * 0.2

                    book_imb = feat.get("book_imbalance") or feat.get("bid_ask_imbalance") or feat.get("micro_book_imbalance")
                    if book_imb is not None and book_imb != 0:
                        vote_count += 1
                        direction_votes += min(1.0, max(-1.0, book_imb)) * 0.3

                    taker_buy = feat.get("taker_buy_ratio", 0.5)
                    if taker_buy > 0:
                        vote_count += 1
                        direction_votes += (taker_buy - 0.5) * 0.4
            except Exception as _feat_err:
                logger.debug("DELEVERAGER_FEATURE_ERR | %s | %s", top.symbol, _feat_err)

        # Source 3: CoinAPI orderbook
        if self.redis:
            try:
                msnap = self.redis.hgetall(f"msnap:coinapi_wsds:{top.symbol}")
                if msnap:
                    snap = {}
                    for k, v in msnap.items():
                        kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                        try:
                            snap[kk] = float(v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v)
                        except (ValueError, TypeError):
                            pass
                    bid_d = snap.get("book_bid_sum_5") or snap.get("bid_depth") or snap.get("bid_volume") or 0
                    ask_d = snap.get("book_ask_sum_5") or snap.get("ask_depth") or snap.get("ask_volume") or 0
                    total_d = bid_d + ask_d
                    if total_d > 0:
                        vote_count += 1
                        ob_ratio = (bid_d - ask_d) / total_d
                        direction_votes += ob_ratio * 0.3

                    _imb5 = snap.get("imbalance_5")
                    if _imb5 is not None and _imb5 != 0:
                        vote_count += 1
                        direction_votes += min(1.0, max(-1.0, _imb5)) * 0.25

                    _fast_m = snap.get("fast_move_score", 0)
                    _p_false = snap.get("p_false_move", 0)
                    if _fast_m > 0.3 and _p_false < 0.4:
                        vote_count += 1
                        _micro_px = snap.get("microprice", 0)
                        _mid_px = snap.get("mid_px", 0)
                        if _micro_px > 0 and _mid_px > 0:
                            _px_skew = (_micro_px - _mid_px) / _mid_px
                            direction_votes += min(0.5, max(-0.5, _px_skew * 1000)) * 0.2
            except Exception as _ob_err:
                logger.debug("DELEVERAGER_OB_ERR | %s | %s", top.symbol, _ob_err)

        # Source 4: Trainer intent + target price
        if self.redis:
            try:
                from risk.trainer_alignment import get_trainer_view
                _tv = get_trainer_view(self.redis, top.symbol)
                if _tv and _tv.is_directional and not _tv.stale:
                    vote_count += 1
                    sign = 1.0 if _tv.consensus_direction == "LONG" else -1.0
                    direction_votes += sign * _tv.consensus_confidence * 0.5
                    if _tv.best_target_price > 0 and top.mark_price > 0:
                        _tgt_pct = (_tv.best_target_price - top.mark_price) / top.mark_price
                        vote_count += 1
                        direction_votes += min(0.5, max(-0.5, _tgt_pct * 10)) * 0.3
            except Exception:
                try:
                    from risk.trainer_intent import get_intent
                    intent = get_intent(self.redis, top.symbol)
                    if intent and intent.is_directional and not intent.is_stale:
                        vote_count += 1
                        sign = 1.0 if intent.direction == "LONG" else -1.0
                        direction_votes += sign * intent.confidence * 0.5
                except Exception:
                    pass

        # Source 5: Liquidation cluster proximity
        if self.redis:
            try:
                for _ltf in ("5m", "1m"):
                    _lfr = self.redis.hgetall(f"unified_features:{top.symbol}:{_ltf}")
                    if not _lfr:
                        continue
                    _lfd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _lfr.items()}
                    _long_liq_d = _sf(_lfd.get("liquidation_long_distance_pct", 100))
                    _short_liq_d = _sf(_lfd.get("liquidation_short_distance_pct", 100))
                    _long_liq_s = _sf(_lfd.get("liquidation_long_strength", 0))
                    _short_liq_s = _sf(_lfd.get("liquidation_short_strength", 0))
                    if _long_liq_d < 3.0 and _long_liq_s > 0.3:
                        vote_count += 1
                        direction_votes -= _long_liq_s * 0.3
                    if _short_liq_d < 3.0 and _short_liq_s > 0.3:
                        vote_count += 1
                        direction_votes += _short_liq_s * 0.3
                    break
            except Exception:
                pass


        # Determine preferred side to cut
        if vote_count >= 2 and abs(direction_votes) > 0.1:
            market_dir = "LONG" if direction_votes > 0 else "SHORT"
            preferred_cut_side = "SHORT" if market_dir == "LONG" else "LONG"
            preferred_cut_side = self._clamp_cut_side_for_trainer(
                top.symbol, preferred_cut_side, positions_sorted
            )

            same_sym = [p for p in positions_sorted if p.symbol == top.symbol]
            opposing = [p for p in same_sym if p.side == preferred_cut_side]
            if opposing:
                logger.info(
                    "EDGE_AWARE_LEG_SELECT | symbol=%s | market_dir=%s | "
                    "dir_votes=%.3f | vote_count=%d | cutting=%s (preserving %s)",
                    top.symbol, market_dir, direction_votes, vote_count,
                    preferred_cut_side, market_dir,
                )
                return opposing[0]

        # Fallback: existing edge-only logic then main_leg tracker
        if edge and edge.direction != "NEUTRAL" and edge.confidence >= 0.25:
            preferred_cut_side = "SHORT" if edge.direction == "LONG" else "LONG"
            preferred_cut_side = self._clamp_cut_side_for_trainer(
                top.symbol, preferred_cut_side, positions_sorted
            )
            same_sym = [p for p in positions_sorted if p.symbol == top.symbol]
            opposing = [p for p in same_sym if p.side == preferred_cut_side]
            if opposing:
                return opposing[0]

        if self._main_leg_tracker:
            hedge_side = self._main_leg_tracker.get_hedge_side(account_id, top.symbol)
            if hedge_side:
                same_sym = [p for p in positions_sorted if p.symbol == top.symbol]
                hedge_legs = [p for p in same_sym if p.side == hedge_side]
                if hedge_legs:
                    return hedge_legs[0]

        return top

    def _get_edge_for_symbol(self, symbol: str) -> Optional[Any]:
        """Get edge signal for a symbol from the risk state machine."""
        if self._risk_sm is not None:
            try:
                return self._risk_sm.get_edge(symbol)
            except Exception:
                pass
        return None

    # ── private: compute reduction ──────────────────────────────────────

    def _compute_reduction(
        self,
        target_leg: PositionLeg,
        equity: float,
        total_im: float,
        mu_pct: float,
        max_acct_pct: float,
        mu_cap: float,
        max_sym_pct: float,
        hysteresis: float,
        acct_breach: bool,
        sym_breach: bool,
        violations: List[str],
        account_id: str,
    ) -> Optional[DeleverageOrder]:
        """
        Compute exact reduction quantity for the target leg.

        Strategy: reduce just enough margin to bring the violated metric
        under (cap − hysteresis).  Clamp to max_reduce_pct of the leg.
        """
        max_reduce_pct = float(_cfg("GOV_DELEVERAGE_MAX_REDUCE_PCT", 0.20))  # max 20% of leg per action
        min_reduce_margin = float(_cfg("GOV_DELEVERAGE_MIN_REDUCE_USD", 5.0))  # don't bother below $5

        if target_leg.initial_margin <= 0 or target_leg.size <= 0:
            return None

        # ── Compute how much margin to shed ─────────────────────────────
        # Target: bring the breached metric to (cap − hysteresis)
        target_margin_shed = 0.0

        if acct_breach:
            # Account-level: need total_im / equity <= (max_acct_pct - hysteresis)
            target_acct = max_acct_pct - hysteresis
            desired_im = equity * target_acct
            margin_excess = total_im - desired_im
            if margin_excess > 0:
                target_margin_shed = max(target_margin_shed, margin_excess)

            # Also check MU breach: MU is margin_used/margin_balance
            # We can't directly control margin_balance, but reducing IM reduces margin_used
            if mu_pct > mu_cap:
                # Approximate: margin_used_pct ≈ total_im / equity * 100
                # Need mu to reach (mu_cap - hysteresis*100)
                target_mu = mu_cap - (hysteresis * 100)
                desired_im_mu = equity * (target_mu / 100.0)
                mu_excess = total_im - desired_im_mu
                if mu_excess > 0:
                    target_margin_shed = max(target_margin_shed, mu_excess)

        if sym_breach:
            # Symbol-level: need sym_margin / equity <= (max_sym_pct - hysteresis)
            target_sym = max_sym_pct - hysteresis
            desired_sym_im = equity * target_sym
            sym_excess = target_leg.initial_margin - desired_sym_im
            if sym_excess > 0:
                target_margin_shed = max(target_margin_shed, sym_excess)

        if target_margin_shed < min_reduce_margin:
            logger.debug(
                "DELEVERAGER_TOO_SMALL | symbol=%s | shed_needed=$%.2f | min=$%.2f",
                target_leg.symbol, target_margin_shed, min_reduce_margin,
            )
            return None

        # ── Clamp to max % of this leg ──────────────────────────────────
        max_margin_reduce = target_leg.initial_margin * max_reduce_pct
        actual_margin_reduce = min(target_margin_shed, max_margin_reduce)

        # ── Convert margin to quantity ──────────────────────────────────
        # margin = qty * mark_price / leverage  →  qty = margin * leverage / mark_price
        if target_leg.mark_price <= 0 or target_leg.leverage <= 0:
            return None

        reduce_qty = (actual_margin_reduce * target_leg.leverage) / target_leg.mark_price
        reduce_pct = reduce_qty / target_leg.size if target_leg.size > 0 else 0.0

        # Safety: never reduce more than max_reduce_pct of the leg in one action
        if reduce_pct > max_reduce_pct:
            reduce_pct = max_reduce_pct
            reduce_qty = target_leg.size * max_reduce_pct

        if reduce_qty <= 0:
            return None

        # Build reason
        reason_parts = []
        if acct_breach:
            reason_parts.append(f"acct_im={total_im/equity*100:.1f}%>{max_acct_pct*100:.0f}%")
        if mu_pct > mu_cap:
            reason_parts.append(f"mu={mu_pct:.1f}%>{mu_cap:.0f}%")
        if sym_breach:
            sym_pct = target_leg.initial_margin / equity * 100 if equity > 0 else 0
            reason_parts.append(f"sym={sym_pct:.1f}%>{max_sym_pct*100:.0f}%")

        return DeleverageOrder(
            symbol=target_leg.symbol,
            side=target_leg.side,
            reduce_qty=reduce_qty,
            reduce_margin_usd=round(actual_margin_reduce, 2),
            reduce_pct=round(reduce_pct, 6),
            reason_code="GOV_AUTO_DELEVERAGE",
            reason=f"Cap breach: {'; '.join(reason_parts)}. "
                   f"Reducing {target_leg.symbol} {target_leg.side} by {reduce_pct*100:.1f}% "
                   f"(~${actual_margin_reduce:.2f} margin)",
            meta={
                "account_id": account_id,
                "equity": round(equity, 2),
                "total_im": round(total_im, 2),
                "mu_pct": round(mu_pct, 2),
                "target_margin_shed": round(target_margin_shed, 2),
                "actual_margin_reduce": round(actual_margin_reduce, 2),
                "leg_initial_margin": round(target_leg.initial_margin, 2),
                "leg_notional": round(target_leg.notional_usd, 2),
                "leg_unrealized_pnl": round(target_leg.unrealized_pnl, 4),
                "leg_roe_pct": round(target_leg.roe_pct, 2),
                "violations": violations,
                "action_number": self._action_count + 1,
            },
        )

    # ── private: fetch account state ────────────────────────────────────

    def _get_account_state(
        self,
        account_id: str,
        *,
        equity_override: Optional[float] = None,
        total_im_override: Optional[float] = None,
        mu_override: Optional[float] = None,
        mr_override: Optional[float] = None,
    ) -> Dict[str, float]:
        """Fetch equity, IM, MU, MR from Redis or overrides."""
        state = {
            "equity": _sf(equity_override),
            "total_initial_margin": _sf(total_im_override),
            "margin_used_pct": _sf(mu_override),
            "margin_ratio_pct": _sf(mr_override),
        }

        if self.redis:
            try:
                raw = self.redis.get(f"wma:account_margin:{account_id}")
                if raw:
                    snap_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    snap = json.loads(snap_str)
                    if state["margin_ratio_pct"] <= 0:
                        state["margin_ratio_pct"] = _sf(snap.get("margin_ratio_pct"))
                    if state["margin_used_pct"] <= 0:
                        state["margin_used_pct"] = _sf(snap.get("margin_used_pct"))
                    if state["equity"] <= 0:
                        state["equity"] = _sf(snap.get("margin_balance"))
                    if state["total_initial_margin"] <= 0 and state["margin_used_pct"] > 0 and state["equity"] > 0:
                        state["total_initial_margin"] = state["equity"] * (state["margin_used_pct"] / 100.0)
            except Exception as e:
                logger.debug("DELEVERAGER_REDIS_ERR | key=wma:account_margin:%s | err=%s", account_id, e)

        # Fallback: portfolio:equity:{account_id}
        if self.redis and state["equity"] <= 0:
            try:
                raw = self.redis.get(f"portfolio:equity:{account_id}")
                if raw:
                    snap_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    eq_snap = json.loads(snap_str)
                    state["equity"] = _sf(
                        eq_snap.get("equity_usd")
                        or eq_snap.get("margin_balance_usd")
                        or eq_snap.get("wallet_balance_usd")
                    )
                    if state["total_initial_margin"] <= 0:
                        state["total_initial_margin"] = _sf(
                            eq_snap.get("used_margin_usd") or eq_snap.get("initial_margin_usd")
                        )
            except Exception:
                pass

        return state

    # ── private: fetch all position legs ────────────────────────────────

    def _get_all_positions(self, account_id: str) -> List[PositionLeg]:
        """Fetch all position legs for the account from Redis."""
        if not self.redis:
            return []

        legs: List[PositionLeg] = []

        try:
            sym_set = self.redis.smembers(f"positions:live:symbols:{account_id}")
            if not sym_set:
                return []

            for sym_raw in sym_set:
                sym = sym_raw.decode("utf-8") if isinstance(sym_raw, (bytes, bytearray)) else str(sym_raw)
                try:
                    raw = self.redis.hgetall(f"positions:live:{sym}")
                    if not raw:
                        continue

                    for side_key in ("long", "short", b"long", b"short"):
                        val = raw.get(side_key)
                        if not val:
                            continue
                        val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
                        try:
                            leg_data = json.loads(val_str)
                        except Exception:
                            continue

                        size = _sf(leg_data.get("size"))
                        if size <= 0:
                            continue

                        side_str = side_key.decode("utf-8") if isinstance(side_key, (bytes, bytearray)) else str(side_key)
                        im = _sf(leg_data.get("initialMargin") or leg_data.get("margin_used"))
                        mark = _sf(leg_data.get("mark_price") or leg_data.get("current_price"))
                        lev = _sf(leg_data.get("leverage"), 1.0)
                        notional = size * mark if mark > 0 else im * lev

                        legs.append(PositionLeg(
                            symbol=sym,
                            side=side_str.upper(),
                            size=size,
                            entry_price=_sf(leg_data.get("entry_price")),
                            mark_price=mark,
                            initial_margin=im,
                            notional_usd=notional,
                            unrealized_pnl=_sf(leg_data.get("unrealized_pnl")),
                            leverage=lev,
                            roe_pct=_sf(leg_data.get("roi_pct")),
                        ))
                except Exception as e:
                    logger.debug("DELEVERAGER_POS_ERR | symbol=%s | err=%s", sym, e)

        except Exception as e:
            logger.debug("DELEVERAGER_SYMBOLS_ERR | account=%s | err=%s", account_id, e)

        return legs

    # ── utility ─────────────────────────────────────────────────────────

    @property
    def last_action_ts(self) -> float:
        return self._last_action_ts

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def main_leg_tracker(self) -> Optional[Any]:
        return self._main_leg_tracker

    @property
    def cage_detector(self) -> Optional[Any]:
        return self._cage_detector

    @property
    def risk_state_machine(self) -> Optional[Any]:
        return self._risk_sm

    # ── trainer signal reader (shared with hedge_manager_v3 pattern) ────

    def _read_trainer_signal(self, symbol: str):
        """
        Best-effort: read trainer direction + confidence from Redis.
        Returns (direction, confidence) — direction is 'LONG'|'SHORT'|'NONE'.
        """
        sym_u = str(symbol or "").upper().strip()
        r = self.redis
        if r is None or not sym_u:
            return "NONE", 0.0

        try:
            d = r.hgetall(f"prediction:{sym_u}:multi")
            if d:
                _raw = d if isinstance(d, dict) else {}
                if isinstance(list(_raw.values())[0] if _raw else "", bytes):
                    _raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _raw.items()}
                conf = max(0.0, min(1.0, _sf(_raw.get("confidence", _raw.get("model_confidence", 0.0)))))
                direction = str(_raw.get("direction") or "").upper()
                if direction in ("LONG", "SHORT") and conf > 0:
                    return direction, conf
        except Exception:
            pass

        best_dir, best_conf = "NONE", 0.0
        for tf in ("1h", "4h", "15m", "5m"):
            try:
                d = r.hgetall(f"prediction:{sym_u}:{tf}")
                if not d:
                    continue
                _raw = d if isinstance(d, dict) else {}
                if isinstance(list(_raw.values())[0] if _raw else "", bytes):
                    _raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _raw.items()}
                conf = max(0.0, min(1.0, _sf(_raw.get("confidence", _raw.get("model_confidence", 0.0)))))
                direction = str(_raw.get("direction") or "").upper()
                if direction in ("LONG", "SHORT") and conf > best_conf:
                    best_dir, best_conf = direction, conf
            except Exception:
                continue
        return best_dir, best_conf

    # ── cage timeout (trainer + PnL aware) ───────────────────────────────

    def check_cage_timeouts(self, account_id: str, equity: float = 0.0) -> List[DeleverageOrder]:
        """
        Purely data-driven hedge cage resolution — no timers, no static thresholds.

        Acts ONLY when there is a material change in the trainer signal:
          - Direction change (LONG→SHORT or vice versa) triggers immediate action.
          - Significant confidence increase (>5pp above last actioned level)
            triggers a new reduction.
          - Same direction at similar confidence → no action (prevents churn).
          - No trainer signal → no action.
          - Direction FLIP cooldown: After a direction change, wait before acting
            again to prevent flip-flop destruction of both hedge legs.

        When acting: close ONLY the opposing leg. Never touch the aligned leg.
        Never close a leg that is already losing money (hedge preservation).

        Returns list of DeleverageOrders.
        """
        if not _cfg("HEDGE_CAGE_ENABLED", True):
            return []
        if not self._cage_detector:
            return []

        if not hasattr(self, '_cage_last_action'):
            self._cage_last_action = {}
        if not hasattr(self, '_cage_last_action_ts'):
            self._cage_last_action_ts = {}
        if not hasattr(self, '_cage_total_reduced_pct'):
            self._cage_total_reduced_pct = {}  # {sym: float} cumulative reduction

        orders: List[DeleverageOrder] = []
        try:
            cages = self._cage_detector.detect_cages(account_id)
            for cage in cages:
                sym = cage.symbol
                max_pct = float(_cfg("GOV_DELEVERAGE_MAX_REDUCE_PCT", 0.20))
                trainer_min_conf = float(_cfg("CAGE_TIMEOUT_TRAINER_MIN_CONF", 0.55))

                # Urgency scaling: increase reduction ceiling under margin stress
                _cage_ceil = 0.35
                try:
                    _cage_acct = self._get_account_state(account_id)
                    _cage_mu = float(_cage_acct.get("margin_used_pct", 0) or 0)
                    if _cage_mu >= 80:
                        _cage_ceil = 0.65
                        max_pct = max(max_pct, 0.40)
                    elif _cage_mu >= 70:
                        _cage_ceil = 0.50
                        max_pct = max(max_pct, 0.30)
                    elif _cage_mu >= 60:
                        _cage_ceil = 0.40
                        max_pct = max(max_pct, 0.25)
                    # #region agent log
                    try:
                        import json as _jmod; open("/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log","a").write(_jmod.dumps({"sessionId":"53deb7","hypothesisId":"enhance2","location":"auto_deleverager.py:CAGE_URGENCY","message":"cage urgency scaling","data":{"symbol":sym,"mu_pct":round(_cage_mu,1),"max_pct":round(max_pct,3),"cage_ceil":round(_cage_ceil,3)},"timestamp":__import__('time').time()*1000})+"\n")
                    except Exception:
                        pass
                    # #endregion
                except Exception:
                    _cage_ceil = 0.35

                trainer_dir, trainer_conf = self._read_trainer_signal(sym)
                long_pnl = cage.long_leg.unrealized_pnl
                short_pnl = cage.short_leg.unrealized_pnl

                if trainer_dir not in ("LONG", "SHORT") or trainer_conf < trainer_min_conf:
                    logger.debug(
                        "CAGE_HOLD | %s | %s | trainer=%s@%.2f < min=%.2f — no signal",
                        account_id, sym, trainer_dir, trainer_conf, trainer_min_conf,
                    )
                    continue

                # ── DIRECTION FLIP COOLDOWN ──────────────────────────────
                # If the trainer direction has CHANGED since last action,
                # enforce a cooldown to prevent flip-flop destruction of both
                # hedge legs within minutes.
                _cage_flip_cooldown = float(_cfg("CAGE_DIRECTION_FLIP_COOLDOWN_SEC", 600))
                last = self._cage_last_action.get(sym)
                _now_cage = time.time()
                if last is not None:
                    last_dir, last_conf = last
                    same_direction = (trainer_dir == last_dir)

                    if not same_direction:
                        # Direction changed! Enforce cooldown
                        _last_ts = self._cage_last_action_ts.get(sym, 0)
                        _elapsed = _now_cage - _last_ts
                        if _elapsed < _cage_flip_cooldown:
                            logger.warning(
                                "CAGE_FLIP_COOLDOWN | %s | trainer flipped %s→%s | "
                                "elapsed=%.0fs < cooldown=%.0fs — BLOCKING to prevent flip-flop",
                                sym, last_dir, trainer_dir, _elapsed, _cage_flip_cooldown,
                            )
                            continue
                        # Also reset cumulative reduction counter on direction change
                        self._cage_total_reduced_pct[sym] = 0.0
                        logger.info(
                            "CAGE_DIRECTION_CHANGE | %s | %s→%s (cooldown passed: %.0fs)",
                            sym, last_dir, trainer_dir, _elapsed,
                        )
                    else:
                        # Same direction: suppress if confidence hasn't meaningfully increased
                        conf_delta = trainer_conf - last_conf
                        if conf_delta < 0.05:
                            logger.debug(
                                "CAGE_SUPPRESS | %s | %s | trainer=%s@%.2f vs last=%s@%.2f "
                                "delta=%.3f < 0.05 — suppressed",
                                account_id, sym, trainer_dir, trainer_conf,
                                last_dir, last_conf, conf_delta,
                            )
                            continue

                # ── CUMULATIVE REDUCTION CAP ─────────────────────────────
                # Don't reduce more than 60% of a leg's original size per
                # direction cycle to preserve hedge protection.
                _cage_max_total_pct = float(_cfg("CAGE_MAX_TOTAL_REDUCE_PCT", 0.60))
                _cum_reduced = self._cage_total_reduced_pct.get(sym, 0.0)
                if _cum_reduced >= _cage_max_total_pct:
                    logger.info(
                        "CAGE_CUMULATIVE_CAP | %s | total_reduced=%.1f%% >= cap=%.1f%% — no more reductions",
                        sym, _cum_reduced * 100, _cage_max_total_pct * 100,
                    )
                    continue

                opposing_side = "SHORT" if trainer_dir == "LONG" else "LONG"
                close_leg = cage.long_leg if opposing_side == "LONG" else cage.short_leg

                if close_leg.size <= 0 or close_leg.initial_margin <= 0:
                    continue

                # ── LOSS-LEG PROTECTION ──────────────────────────────────
                # Never close a hedge leg that is currently protecting against
                # losses on the other side. Only close the opposing leg if:
                #  a) It is itself at a loss (dead weight), OR
                #  b) The ALIGNED leg is at a profit (the hedge is winning)
                # This prevents the classic bleed: close profitable hedge leg,
                # leaving the losing main leg exposed.
                _close_leg_pnl = close_leg.unrealized_pnl
                _aligned_side = "LONG" if trainer_dir == "LONG" else "SHORT"
                _aligned_leg = cage.long_leg if _aligned_side == "LONG" else cage.short_leg
                _aligned_pnl = _aligned_leg.unrealized_pnl
                _net_cage_pnl = long_pnl + short_pnl

                # Block if: closing a profitable leg while aligned leg is losing
                # (this destroys the hedge for nothing)
                if _close_leg_pnl > 0 and _aligned_pnl < 0:
                    logger.warning(
                        "CAGE_LOSS_LEG_BLOCK | %s | close_leg=%s pnl=$%.2f (PROFIT) "
                        "but aligned=%s pnl=$%.2f (LOSS) | net=$%.2f | "
                        "BLOCKING: would close profitable protection while keeping loser",
                        sym, opposing_side, _close_leg_pnl,
                        _aligned_side, _aligned_pnl, _net_cage_pnl,
                    )
                    continue

                # Also block if both legs are losing — closing either just realizes losses
                if _close_leg_pnl < -1.0 and _aligned_pnl < -1.0 and _net_cage_pnl < -2.0:
                    logger.warning(
                        "CAGE_BOTH_LOSING_BLOCK | %s | close=%s@$%.2f aligned=%s@$%.2f "
                        "net=$%.2f | BLOCKING: both legs underwater, hold hedge",
                        sym, opposing_side, _close_leg_pnl,
                        _aligned_side, _aligned_pnl, _net_cage_pnl,
                    )
                    continue

                # Block if close-leg has meaningful loss — CAGE should not realize losses.
                # Only allow CAGE to close legs at breakeven/profit or de-minimis loss (<$2).
                _cage_max_close_loss = float(_cfg("CAGE_MAX_CLOSE_LOSS_USD", 2.0))
                if _close_leg_pnl < -_cage_max_close_loss:
                    logger.warning(
                        "CAGE_CLOSE_LOSS_BLOCK | %s | close=%s pnl=$%.2f > max_loss=$%.2f | "
                        "BLOCKING: CAGE should not realize losses beyond de minimis",
                        sym, opposing_side, _close_leg_pnl, _cage_max_close_loss,
                    )
                    continue

                # ── Data-driven reduction sizing ──────────────────────────
                # Scale reduction % using regime, microstructure, volatility,
                # liquidation, and PnL divergence instead of a static 20%.
                _reduce_pct = max_pct
                _regime_str = ""
                _micro_valid = True
                _vol_score = 0.5
                try:
                    if self.redis:
                        # 1. Regime: stronger alignment → larger reduction
                        _reg_raw = self.redis.get(f"regime:{sym}")
                        if _reg_raw:
                            _rj = json.loads(_reg_raw.decode("utf-8") if isinstance(_reg_raw, (bytes, bytearray)) else str(_reg_raw))
                            _regime_str = str(_rj.get("move_regime", "")).upper()
                            _trend_dir = str(_rj.get("trend_direction", "")).upper()
                            _tf_align = float(_rj.get("tf_alignment", 0) or 0)
                            _vol_score = float(_rj.get("volatility_score", 0.5) or 0.5)

                            _trainer_matches_regime = (
                                (trainer_dir == "LONG" and _trend_dir in ("LONG", "BULLISH", "UP"))
                                or (trainer_dir == "SHORT" and _trend_dir in ("SHORT", "BEARISH", "DOWN"))
                            )
                            _align_strength = abs(_tf_align)
                            if _trainer_matches_regime and _align_strength > 0.5:
                                _reduce_pct = min(0.35, _reduce_pct + _align_strength * 0.10)
                            elif not _trainer_matches_regime:
                                _reduce_pct = max(0.10, _reduce_pct * 0.6)

                        # 2a. Real-time price momentum check: reject if price is
                        # moving AGAINST the trainer direction (market disagrees)
                        _price_confirms = True
                        try:
                            for _ptf in ("5m", "1m"):
                                _pf = self.redis.hgetall(f"unified_features:{sym}:{_ptf}")
                                if not _pf:
                                    continue
                                _pfd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _pf.items()}
                                # Check recent price change (close vs open of recent candle)
                                _close = float(_pfd.get("close", 0) or 0)
                                _open = float(_pfd.get("open", 0) or 0)
                                _ema_fast = float(_pfd.get("ema_9", 0) or _pfd.get("ema_fast", 0) or 0)
                                _ema_slow = float(_pfd.get("ema_21", 0) or _pfd.get("ema_slow", 0) or 0)
                                if _close > 0 and _open > 0:
                                    _candle_dir = "LONG" if _close > _open else "SHORT"
                                    _candle_pct = abs(_close - _open) / _open * 100.0
                                    # EMA trend: fast > slow = LONG bias
                                    _ema_dir = None
                                    if _ema_fast > 0 and _ema_slow > 0:
                                        _ema_dir = "LONG" if _ema_fast > _ema_slow else "SHORT"
                                    # If both candle AND EMA oppose trainer, block
                                    if _candle_dir != trainer_dir and _ema_dir and _ema_dir != trainer_dir:
                                        if _candle_pct > 0.1:  # Non-trivial move
                                            _price_confirms = False
                                            logger.info(
                                                "CAGE_PRICE_REJECT | %s | trainer=%s but candle=%s (%.2f%%) "
                                                "ema=%s — market disagrees, skipping",
                                                sym, trainer_dir, _candle_dir, _candle_pct, _ema_dir,
                                            )
                                    elif _candle_dir != trainer_dir and _candle_pct > 0.3:
                                        # Strong candle opposing trainer → halve reduction
                                        _reduce_pct = max(0.05, _reduce_pct * 0.5)
                                        logger.info(
                                            "CAGE_PRICE_DAMPEN | %s | trainer=%s candle=%s (%.2f%%) — halving reduce",
                                            sym, trainer_dir, _candle_dir, _candle_pct,
                                        )
                                break  # Use first available TF
                        except Exception as _pe:
                            logger.debug("CAGE_PRICE_CHECK_ERR | %s | %s", sym, _pe)

                        if not _price_confirms:
                            _micro_valid = False

                        # 2b. Orderbook imbalance: reject if OB imbalance opposes trainer
                        try:
                            _ob_raw = self.redis.hgetall(f"orderbook:{sym}")
                            if _ob_raw:
                                _ob = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _ob_raw.items()}
                                _bid_vol = float(_ob.get("bid_volume", 0) or 0)
                                _ask_vol = float(_ob.get("ask_volume", 0) or 0)
                                if _bid_vol > 0 and _ask_vol > 0:
                                    _ob_ratio = _bid_vol / (_bid_vol + _ask_vol)
                                    # Trainer says LONG but OB heavily ask-dominated (< 0.35)
                                    # Trainer says SHORT but OB heavily bid-dominated (> 0.65)
                                    if (trainer_dir == "LONG" and _ob_ratio < 0.30) or \
                                       (trainer_dir == "SHORT" and _ob_ratio > 0.70):
                                        _reduce_pct = max(0.05, _reduce_pct * 0.5)
                                        logger.info(
                                            "CAGE_OB_DAMPEN | %s | trainer=%s ob_ratio=%.2f — OB opposes, halving",
                                            sym, trainer_dir, _ob_ratio,
                                        )
                        except Exception:
                            pass

                        # 2c. Microstructure: reject if move is spoofed/false
                        _ms_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{sym}")
                        if _ms_raw:
                            _ms = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _ms_raw.items()}
                            _p_false = float(_ms.get("p_false_move", 0) or 0)
                            _snapback = float(_ms.get("snapback_score", 0) or 0)
                            _fast_move = float(_ms.get("fast_move_score", 0) or 0)
                            if _p_false > 0.5 and _snapback > 0.4:
                                _micro_valid = False
                            elif _fast_move > 0.5:
                                _reduce_pct = min(0.35, _reduce_pct * 1.2)

                        # 3. Volatility: high vol → smaller reduction (avoid selling dip)
                        if _vol_score > 0.7:
                            _reduce_pct = max(0.10, _reduce_pct * (1.0 - (_vol_score - 0.7)))

                        # 4. Liquidation proximity: close to liq → more urgent
                        for _ltf in ("5m", "1m"):
                            _lf = self.redis.hgetall(f"unified_features:{sym}:{_ltf}")
                            if not _lf:
                                continue
                            _lfd = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _lf.items()}
                            _liq_key = "liquidation_long_distance_pct" if opposing_side == "LONG" else "liquidation_short_distance_pct"
                            _ld = float(_lfd.get(_liq_key, 100) or 100)
                            if _ld < 3.0:
                                _reduce_pct = min(0.35, _reduce_pct * 1.3)
                            break

                        # 5. Trainer confidence scaling
                        _reduce_pct *= min(1.3, 0.7 + trainer_conf * 0.6)

                        # 6. PnL divergence: bigger gap → larger reduction
                        _pnl_diff = abs(long_pnl - short_pnl)
                        if _pnl_diff > 5.0:
                            _reduce_pct = min(0.35, _reduce_pct * 1.15)

                        # 7. ICG hold-score check: don't reduce if ICG says hold
                        try:
                            from risk.intelligent_close_guard import evaluate_close as _cage_icg
                            _icg_r = _cage_icg(
                                self.redis, sym, close_leg.side,
                                close_reason=f"CAGE_REDUCE trainer={trainer_dir}@{trainer_conf:.0%}",
                                is_hard_emergency=False,
                            )
                            if _icg_r and _icg_r.hold_score >= 0.65:
                                _micro_valid = False
                                logger.info(
                                    "CAGE_ICG_DEFER | %s | %s | hold=%.3f >= 0.65 | trainer=%s@%.2f",
                                    sym, close_leg.side, _icg_r.hold_score, trainer_dir, trainer_conf,
                                )
                        except Exception:
                            pass

                except Exception as _dd_err:
                    logger.debug("CAGE_DATA_SIZING_ERR | %s | %s", sym, _dd_err)

                if not _micro_valid:
                    logger.info(
                        "CAGE_MICRO_REJECT | %s | move likely false/spoofed or ICG deferred — skipping",
                        sym,
                    )
                    continue

                _reduce_pct = max(0.05, min(_cage_ceil, _reduce_pct))

                # Ensure cumulative cap isn't exceeded
                _remaining_budget = _cage_max_total_pct - _cum_reduced
                if _reduce_pct > _remaining_budget:
                    _reduce_pct = max(0.05, _remaining_budget)

                self._cage_last_action[sym] = (trainer_dir, trainer_conf)
                self._cage_last_action_ts[sym] = _now_cage
                self._cage_total_reduced_pct[sym] = _cum_reduced + _reduce_pct


                cage_orders: List[DeleverageOrder] = []
                cage_orders.append(DeleverageOrder(
                    symbol=sym,
                    side=close_leg.side,
                    reduce_qty=close_leg.size * _reduce_pct,
                    reduce_margin_usd=round(close_leg.initial_margin * _reduce_pct, 2),
                    reduce_pct=_reduce_pct,
                    reason_code="CAGE_DATA_DRIVEN",
                    reason=(
                        f"GOV_DELEVERAGE: Trainer signal change — closing {close_leg.side} by "
                        f"{_reduce_pct*100:.0f}% [trainer={trainer_dir}@{trainer_conf:.0%} "
                        f"regime={_regime_str} vol={_vol_score:.2f} "
                        f"long_pnl=${long_pnl:.2f} short_pnl=${short_pnl:.2f}]"
                    ),
                    meta={
                        "account_id": account_id,
                        "cage_age_sec": round(cage.cage_age_sec, 0),
                        "cage_gross_im": round(cage.gross_im, 2),
                        "main_side": cage.main_side,
                        "pair_reduce": False,
                        "cage_timeout": False,
                        "strategy": "TRAINER_ALIGNED_DATA_DRIVEN",
                        "trainer_dir": trainer_dir,
                        "trainer_conf": round(trainer_conf, 4),
                        "regime": _regime_str,
                        "vol_score": round(_vol_score, 3),
                        "reduce_pct_computed": round(_reduce_pct, 4),
                    },
                ))

                if cage_orders:
                    logger.warning(
                        "CAGE_DATA_REDUCE | account=%s | symbol=%s | "
                        "trainer=%s@%.2f | long_pnl=$%.2f short_pnl=$%.2f | "
                        "closing %s by %.0f%%",
                        account_id, sym,
                        trainer_dir, trainer_conf, long_pnl, short_pnl,
                        close_leg.side, _reduce_pct * 100,
                    )
                    orders.extend(cage_orders)

        except Exception as e:
            logger.debug("CAGE_CHECK_ERR | %s", e)

        return orders

    def reset_cooldown(self):
        """Allow immediate next action (for testing)."""
        self._last_action_ts = 0.0
