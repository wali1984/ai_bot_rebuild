"""
HedgePairCoordinator — Hedge HEALTH monitor, NOT a hedge adder.

PURPOSE: Hedges are PROTECTIVE — temporary shields to prevent premature closes
while the market decides direction. They should NEVER reach 1:1 ratio.

This coordinator:
1. DETECTS hedge bloat (ratio approaching 1:1) → trims hedge back to target
2. DETECTS both-sides-red → closes the worse leg to free margin
3. DETECTS market-aligned opportunities → reduces the counter-trend hedge
4. ENFORCES max hedge coverage ratio per symbol

It does NOT add hedges. That's GRADUATED_KILL_HEDGE, ADAPTIVE_HEDGE,
and TREND_HEDGE_SCALE's job.

Kill switch: config.HEDGE_PAIR_COORDINATOR_ENABLED = false
            or Redis key  killswitch:hedge_pair_coordinator = 1
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hedge_pair_coordinator")


@dataclass
class PairAction:
    symbol: str
    action_type: str   # TRIM_HEDGE, CLOSE_LOSER, HOLD
    target_side: str   # Side to close/reduce
    reduce_pct: float = 0.0  # For TRIM_HEDGE: % of hedge to close (0-100)
    reason: str = ""
    priority: int = 5
    confidence: float = 0.5


class HedgePairCoordinator:
    """Monitor hedge health. Trim bloated hedges, close dead-weight pairs."""

    def __init__(self, redis_client: Any, account_id: str = "primary"):
        self.redis = redis_client
        self.account_id = account_id
        self._last_action_ts: Dict[str, float] = {}
        self._hedge_ctx = None
        try:
            from trading.hedge_context import get_hedge_context
            self._hedge_ctx = get_hedge_context(redis_client)
        except Exception:
            pass
        self._load_config()

    def _load_config(self):
        try:
            import config as cfg
            self.enabled = getattr(cfg, "HEDGE_PAIR_COORDINATOR_ENABLED", True)
            self.cooldown_sec = float(getattr(cfg, "HEDGE_PAIR_COORD_COOLDOWN_SEC", 300))
            # Max hedge coverage — hedge side should NOT exceed this % of main side
            self.max_hedge_coverage_pct = float(getattr(cfg, "HEDGE_PAIR_MAX_COVERAGE_PCT", 60.0))
            # Target hedge when trimming — trim back to this %
            self.target_hedge_coverage_pct = float(getattr(cfg, "HEDGE_PAIR_TARGET_COVERAGE_PCT", 35.0))
            # Both-sides-red minimum net loss to act
            self.both_red_min_net_loss = float(getattr(cfg, "HEDGE_PAIR_BOTH_RED_MIN_NET_LOSS", 5.0))
        except Exception:
            self.enabled = True
            self.cooldown_sec = 300
            self.max_hedge_coverage_pct = 60.0
            self.target_hedge_coverage_pct = 35.0
            self.both_red_min_net_loss = 5.0

    def is_enabled(self) -> bool:
        if not self.enabled:
            return False
        try:
            ks = self.redis.get("killswitch:hedge_pair_coordinator")
            if ks and ks.decode().strip() in ("1", "true"):
                return False
            ks2 = self.redis.get("killswitch:all_april_plan")
            if ks2 and ks2.decode().strip() in ("1", "true"):
                return False
        except Exception:
            pass
        return True

    def evaluate(self, positions: Dict[str, Dict]) -> List[PairAction]:
        """Main entry: scan hedged pairs, return trim/close actions."""
        if not self.is_enabled():
            return []

        actions = []
        now = time.time()
        seen = set()

        for key in positions:
            if ":" not in key:
                continue
            sym = key.rsplit(":", 1)[0]
            if sym in seen:
                continue
            seen.add(sym)

            long_pos = positions.get(f"{sym}:LONG")
            short_pos = positions.get(f"{sym}:SHORT")
            if not (isinstance(long_pos, dict) and isinstance(short_pos, dict)):
                continue

            # Cooldown
            last = self._last_action_ts.get(sym, 0)
            if (now - last) < self.cooldown_sec:
                continue

            action = self._evaluate_pair(sym, long_pos, short_pos)
            if action and action.action_type != "HOLD":
                actions.append(action)

        return actions

    def _evaluate_pair(self, sym: str, long_pos: dict, short_pos: dict) -> Optional[PairAction]:

        def _f(d, *keys, default=0.0):
            for k in keys:
                v = d.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        pass
            return default

        l_margin = _f(long_pos, "margin_used", "initialMargin", "margin")
        s_margin = _f(short_pos, "margin_used", "initialMargin", "margin")
        l_roi = _f(long_pos, "roi_pct", "pnl_pct")
        s_roi = _f(short_pos, "roi_pct", "pnl_pct")
        l_pnl = _f(long_pos, "unrealized_pnl", "unrealizedProfit")
        s_pnl = _f(short_pos, "unrealized_pnl", "unrealizedProfit")
        net_pnl = l_pnl + s_pnl

        if l_margin < 1 or s_margin < 1:
            return None

        # Determine MAIN (larger margin) vs HEDGE (smaller margin, protective)
        if l_margin >= s_margin:
            main_side, hedge_side = "LONG", "SHORT"
            main_margin, hedge_margin = l_margin, s_margin
            main_roi, hedge_roi = l_roi, s_roi
        else:
            main_side, hedge_side = "SHORT", "LONG"
            main_margin, hedge_margin = s_margin, l_margin
            main_roi, hedge_roi = s_roi, l_roi

        coverage_pct = (hedge_margin / main_margin * 100) if main_margin > 0 else 0

        # ── MARKET CONTEXT (awareness only, no logic change) ──
        _ctx_info = ""
        try:
            if self._hedge_ctx and self._hedge_ctx.is_enabled():
                _snap = self._hedge_ctx.get_snapshot(sym)
                _ctx_info = (
                    f"dir={_snap.direction_score():+.2f} rsi15={_snap.rsi_15m:.0f} "
                    f"natr={_snap.natr_15m:.2f} funding={_snap.funding_rate:.5f} "
                    f"peer_adds={_snap.total_hedge_adds_last_5m} "
                    f"trainer={_snap.trainer.consensus_direction if _snap.trainer else 'N/A'}"
                )
                logger.debug(
                    "🧠 COORD_CTX | %s | cov=%.0f%% | %s",
                    sym, coverage_pct, _ctx_info,
                )
        except Exception:
            pass

        # ── RULE 1: BOTH SIDES RED → close the deeper loser ──
        if l_roi < -1.0 and s_roi < -1.0 and abs(net_pnl) >= self.both_red_min_net_loss:
            worse_side = "LONG" if l_roi < s_roi else "SHORT"
            return PairAction(
                symbol=sym,
                action_type="CLOSE_LOSER",
                target_side=worse_side,
                reason=(
                    f"BOTH_RED: L={l_roi:+.1f}% S={s_roi:+.1f}% "
                    f"net=${net_pnl:+.1f} coverage={coverage_pct:.0f}%"
                ),
                priority=2,
                confidence=0.80,
            )

        # ── RULE 2: HEDGE BLOAT → trim hedge back to target ratio ──
        if coverage_pct > self.max_hedge_coverage_pct:
            target_hedge_margin = main_margin * (self.target_hedge_coverage_pct / 100.0)
            excess_margin = hedge_margin - target_hedge_margin
            reduce_pct = (excess_margin / hedge_margin * 100) if hedge_margin > 0 else 0

            if reduce_pct > 5:
                return PairAction(
                    symbol=sym,
                    action_type="TRIM_HEDGE",
                    target_side=hedge_side,
                    reduce_pct=reduce_pct,
                    reason=(
                        f"HEDGE_BLOAT: {hedge_side} coverage={coverage_pct:.0f}% > "
                        f"max={self.max_hedge_coverage_pct:.0f}% → trim to "
                        f"{self.target_hedge_coverage_pct:.0f}% (reduce {reduce_pct:.0f}%)"
                    ),
                    priority=3,
                    confidence=0.70,
                )

        # ── RULE 3: Hedge served purpose + market confirmed → trim ──
        if main_roi > 5.0 and hedge_roi < -5.0 and coverage_pct > 30:
            market_favors = self._get_market_direction(sym)
            if market_favors == main_side:
                reduce_pct = min(50.0, coverage_pct - 20.0)
                if reduce_pct > 10:
                    return PairAction(
                        symbol=sym,
                        action_type="TRIM_HEDGE",
                        target_side=hedge_side,
                        reduce_pct=reduce_pct,
                        reason=(
                            f"HEDGE_SERVED: main {main_side} roi={main_roi:+.1f}% "
                            f"hedge {hedge_side} roi={hedge_roi:+.1f}% "
                            f"market={market_favors} → trim {reduce_pct:.0f}%"
                        ),
                        priority=4,
                        confidence=0.65,
                    )

        return None

    def _get_market_direction(self, sym: str) -> Optional[str]:
        try:
            feat_key = f"unified_features:{sym}:15m"
            pipe = self.redis.pipeline(transaction=False)
            pipe.hget(feat_key, "ind_ind_15m_pressure")
            pipe.hget(feat_key, "ind_ta_RSI_14_15m")
            results = pipe.execute()
            pressure = float(results[0]) if results[0] else 0
            rsi = float(results[1]) if results[1] else 50
            score = 0
            if abs(pressure) > 0.05:
                score += pressure * 2.0
            if rsi < 40:
                score -= 1.0
            elif rsi > 60:
                score += 1.0
            if score > 0.3:
                return "LONG"
            elif score < -0.3:
                return "SHORT"
        except Exception:
            pass
        return None

    def execute_actions(self, actions: List[PairAction]) -> int:
        count = 0
        for action in actions:
            try:
                success = False
                if action.action_type == "CLOSE_LOSER":
                    success = self._emit_close(action)
                elif action.action_type == "TRIM_HEDGE":
                    success = self._emit_reduce(action)
                if success:
                    self._last_action_ts[action.symbol] = time.time()
                    count += 1
                    logger.warning(
                        "🔄 HEDGE_PAIR_COORD | %s | %s | side=%s | %s",
                        action.symbol, action.action_type, action.target_side, action.reason,
                    )
                    # Record peer action for cross-system awareness
                    try:
                        if self._hedge_ctx:
                            act = "TRIM" if "TRIM" in action.action_type else "CLOSE"
                            self._hedge_ctx.record_peer_action(
                                action.symbol, "coordinator", act, action.target_side,
                            )
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("HEDGE_PAIR_COORD_ERR | %s | %s", action.symbol, e)
        return count

    def _emit_close(self, action: PairAction) -> bool:
        return self._emit_proposal(
            action.symbol, f"CLOSE_{action.target_side}",
            confidence=action.confidence, reason=action.reason, priority=action.priority,
        )

    def _emit_reduce(self, action: PairAction) -> bool:
        return self._emit_proposal(
            action.symbol, f"DECREASE_{action.target_side}",
            confidence=action.confidence,
            reason=f"{action.reason} reduce_pct={action.reduce_pct:.0f}%",
            priority=action.priority,
        )

    def _emit_proposal(self, symbol, action, confidence, reason, priority) -> bool:
        try:
            now_ms = int(time.time() * 1000)
            proposal = {
                "event": "TRADE_PROPOSAL",
                "proposal_id": str(uuid.uuid4()),
                "ts_ms": now_ms,
                "created_ts_ms": now_ms,
                "account_id": self.account_id,
                "symbol": symbol,
                "action": action,
                "action_name": action,
                "action_category": "PROTECTIVE",
                "category": "PROTECTIVE",
                "source_module": "hedge_pair_coordinator",
                "source": "hedge_pair_coordinator",
                "confidence": confidence,
                "model_confidence": confidence,
                "margin_usd": 0.0,
                "notional_usd": 0.0,
                "leverage": 1.0,
                "risk_add": 0,
                "hedge_intent": False,
                "no_loss_compliant": True,
                "reduce_only": True,
                "timeframe": "multi",
                "trigger_reason": str(reason)[:500],
                "priority": priority,
            }
            try:
                from config import ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM
                stream = ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM
            except Exception:
                stream = "wma:proposals"
            self.redis.xadd(stream, {"data": json.dumps(proposal, separators=(",", ":"), default=str)})
            return True
        except Exception as e:
            logger.debug("HEDGE_PAIR_COORD_EMIT_ERR | %s | %s", symbol, e)
            return False
