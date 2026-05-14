"""
Microstructure Overlay - Spoof & Fast-Move Detection
=====================================================
Detects spoofing and fast-move conditions to gate entries and adjust sizing.

Features:
- Spoof score: Detects fake liquidity and orderbook manipulation
- Fast-move score: Detects volatile/cascading conditions
- Gating mode: Block/reduce based on scores (NEVER blocks protective actions)
- Ingestor router integration: Uses canonical orderbook from best source

Author: WMA AI Trading System
Date: December 24, 2025
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class OverlayDecision(Enum):
    """Overlay decision types."""
    PASS = "PASS"           # Signal passes unchanged
    BLOCK = "BLOCK"         # Signal blocked
    SIZE_REDUCE = "SIZE_REDUCE"  # Size reduced
    CONF_RAISE = "CONF_RAISE"    # Confidence threshold raised
    INPUTS_UNHEALTHY = "INPUTS_UNHEALTHY"  # Cannot evaluate, inputs missing


class BlockReason(Enum):
    """Reason codes for blocks/modifications."""
    SPOOF_RISK_BLOCK = "SPOOF_RISK_BLOCK"
    SPOOF_SIZE_REDUCE = "SPOOF_SIZE_REDUCE"
    SPOOF_UNVERIFIED_BLOCK = "SPOOF_UNVERIFIED_BLOCK"
    FAST_MOVE_ENTRY_BLOCK = "FAST_MOVE_ENTRY_BLOCK"
    FAST_MOVE_PROTECTIVE_PRIORITY = "FAST_MOVE_PROTECTIVE_PRIORITY"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    DEPTH_TOO_THIN = "DEPTH_TOO_THIN"
    OVERLAY_INPUTS_UNHEALTHY = "OVERLAY_INPUTS_UNHEALTHY"


@dataclass
class MicrostructureSnapshot:
    """Snapshot of microstructure state."""
    symbol: str
    timestamp_ms: int
    
    # Orderbook metrics
    bid_price: float = 0.0
    ask_price: float = 0.0
    spread_pct: float = 0.0
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    # Prefer top-5 depth sums when available (more stable than top-1 sizes)
    book_bid_sum_5: float = 0.0
    book_ask_sum_5: float = 0.0
    imbalance: float = 0.0
    
    # Derived metrics
    microprice: float = 0.0
    depth_ratio: float = 1.0

    # Tape / divergence proxies (optional; present when trade feed is enabled)
    trade_total_notional_1s: float = 0.0
    trade_imbalance_1s: float = 0.0
    impact_bps_1s: float = 0.0
    impact_per_musd_1s: float = 0.0
    p_false_move: float = 0.0
    
    # Source info
    source: str = ""
    is_healthy: bool = True
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp_ms': self.timestamp_ms,
            'spread_pct': round(self.spread_pct, 4),
            'imbalance': round(self.imbalance, 4),
            'depth_ratio': round(self.depth_ratio, 4),
            'source': self.source,
            'is_healthy': self.is_healthy,
        }


@dataclass
class SpoofScore:
    """Spoof detection score and components."""
    score: float = 0.0  # 0-1, higher = more likely spoofing
    
    # Components
    imbalance_snapback: float = 0.0  # Strong pressure then reversal
    pressure_persistence: float = 0.0  # How long imbalance sustained
    size_churn: float = 0.0  # Top-of-book size volatility
    cancellation_ratio: float = 0.0  # Estimated cancellation rate
    churn_score: float = 0.0  # Order book churn from CoinAPI
    snapback_score: float = 0.0  # Price snapback from CoinAPI
    ghost_liquidity: float = 0.0  # Depth surge then pull (proxy)
    tape_divergence: float = 0.0  # Displayed vs executed mismatch (if tape available)
    imbalance_to_impact: float = 0.0  # High displayed pressure but low impact
    p_false_move: float = 0.0  # 0..1 heuristic from ingestor (if provided)
    tape_total_notional_1s: float = 0.0
    tape_available: bool = False
    
    is_high: bool = False
    threshold: float = 0.6
    inputs_valid: bool = True
    
    def to_dict(self) -> Dict:
        return {
            'score': round(self.score, 3),
            'imbalance_snapback': round(self.imbalance_snapback, 3),
            'pressure_persistence': round(self.pressure_persistence, 3),
            'size_churn': round(self.size_churn, 3),
            'churn_score': round(self.churn_score, 3),
            'snapback_score': round(self.snapback_score, 3),
            'ghost_liquidity': round(self.ghost_liquidity, 3),
            'tape_divergence': round(self.tape_divergence, 3),
            'imbalance_to_impact': round(self.imbalance_to_impact, 3),
            'p_false_move': round(self.p_false_move, 3),
            'tape_total_notional_1s': round(self.tape_total_notional_1s, 3),
            'tape_available': bool(self.tape_available),
            'is_high': self.is_high,
            'inputs_valid': self.inputs_valid,
        }


@dataclass
class FastMoveScore:
    """Fast-move detection score and components."""
    score: float = 0.0  # 0-1, higher = more volatile/cascading
    
    # Components
    vol_spike_1m: float = 0.0  # 1m realized vol spike
    vol_spike_5m: float = 0.0  # 5m realized vol spike
    spread_widening: float = 0.0  # Spread widening rate
    microprice_jump: float = 0.0  # Microprice jump magnitude
    liquidation_burst: float = 0.0  # Liquidation cascade signal
    
    is_high: bool = False
    threshold: float = 0.7
    inputs_valid: bool = True
    
    def to_dict(self) -> Dict:
        return {
            'score': round(self.score, 3),
            'vol_spike_1m': round(self.vol_spike_1m, 3),
            'vol_spike_5m': round(self.vol_spike_5m, 3),
            'spread_widening': round(self.spread_widening, 3),
            'microprice_jump': round(self.microprice_jump, 3),
            'liquidation_burst': round(self.liquidation_burst, 3),
            'is_high': self.is_high,
            'inputs_valid': self.inputs_valid,
        }


@dataclass
class OverlayResult:
    """Result of overlay evaluation."""
    symbol: str
    decision: OverlayDecision
    reason_code: Optional[BlockReason] = None
    
    # Input action
    action_in: str = ""
    conf_in: float = 0.0
    size_in: float = 0.0
    
    # Output (modified) action
    action_out: str = ""
    conf_required: float = 0.0
    size_out: float = 0.0
    size_multiplier: float = 1.0
    
    # Classification
    is_protective: bool = False
    is_entry: bool = False
    has_position: bool = False
    
    # Scores
    spoof_score: Optional[SpoofScore] = None
    fast_move_score: Optional[FastMoveScore] = None
    
    # Health
    inputs_healthy: bool = True
    data_source: str = ""
    
    timestamp_ms: int = 0
    
    def to_log_line(self) -> str:
        spoof = self.spoof_score.score if self.spoof_score else 0
        fast = self.fast_move_score.score if self.fast_move_score else 0
        reason = self.reason_code.value if self.reason_code else "none"
        return (
            f"MICRO_OVERLAY | {self.symbol} | spoof={spoof:.2f} | fast={fast:.2f} | "
            f"action_in={self.action_in} | is_protective={self.is_protective} | "
            f"size_in={self.size_in:.1f}% | size_out={self.size_out:.1f}% | "
            f"decision={self.decision.value} | reason={reason} | "
            f"inputs_healthy={self.inputs_healthy} | source={self.data_source}"
        )
    
    def to_skip_event(self) -> Dict[str, Any]:
        """Convert to skip event payload for Redis."""
        return {
            "symbol": self.symbol,
            "action": self.action_in,
            "reason_code": self.reason_code.value if self.reason_code else "UNKNOWN",
            "spoof_score": self.spoof_score.score if self.spoof_score else 0,
            "fast_move_score": self.fast_move_score.score if self.fast_move_score else 0,
            "size_multiplier": self.size_multiplier,
            "inputs_healthy": self.inputs_healthy,
            "ts_ms": self.timestamp_ms,
        }


class MicrostructureOverlay:
    """
    Overlay for detecting spoofing and fast-move conditions.
    
    CRITICAL: Protective actions (CLOSE, DECREASE, PARTIAL_CLOSE, REDUCE) are NEVER blocked.
    """
    
    # Rolling window for orderbook snapshots (for spoof detection)
    MAX_SNAPSHOT_HISTORY = 20
    
    # Protective action keywords
    PROTECTIVE_KEYWORDS = frozenset(['CLOSE', 'DECREASE', 'REDUCE', 'PARTIAL'])
    ENTRY_KEYWORDS = frozenset(['OPEN', 'INCREASE', 'FLIP', 'AND_OPEN'])
    
    def __init__(
        self,
        redis_client: Any = None,
        observe_mode: bool = False,
        spoof_threshold: float = 0.35,  # Lowered from 0.6 - more sensitive detection
        fast_move_threshold: float = 0.5,  # Lowered from 0.7 - catch faster moves
        spoof_action: str = "size_reduce",  # "block" or "size_reduce"
        size_reduction_factor: float = 0.5,
        min_conf_raise: float = 0.1,
        promotion_controller=None,
    ):
        self.redis = redis_client
        self.observe_mode = observe_mode
        self.spoof_threshold = spoof_threshold
        self.fast_move_threshold = fast_move_threshold
        self.spoof_action = spoof_action
        self.size_reduction_factor = size_reduction_factor
        self.min_conf_raise = min_conf_raise
        self.promotion_controller = promotion_controller
        
        # Per-symbol snapshot history
        self._snapshot_history: Dict[str, deque] = {}
        
        # Ingestor router (lazy-loaded)
        self._ingestor_router = None
        
        # Load from env (only override explicit params if env is set)
        mode_env = os.getenv("MICROSTRUCTURE_OVERLAY_MODE")
        if mode_env is not None and str(mode_env).strip() != "":
            mode = str(mode_env).lower()
        else:
            mode = "observe" if observe_mode else "gating"
        self.observe_mode = (mode == "observe")
        self.spoof_threshold = float(os.getenv("MICROSTRUCTURE_SPOOF_THRESHOLD", str(spoof_threshold)))
        self.fast_move_threshold = float(os.getenv("MICROSTRUCTURE_FAST_MOVE_THRESHOLD", str(fast_move_threshold)))
        self.spoof_action = os.getenv("MICROSTRUCTURE_SPOOF_ACTION", spoof_action)
        self.size_reduction_factor = float(os.getenv("MICROSTRUCTURE_SIZE_REDUCTION_FACTOR", str(size_reduction_factor)))
        
        mode_str = 'observe' if self.observe_mode else 'gating'
        logger.info(
            f"MicrostructureOverlay initialized | "
            f"mode={mode_str} | "
            f"spoof_threshold={self.spoof_threshold} | fast_move_threshold={self.fast_move_threshold} | "
            f"spoof_action={self.spoof_action} | size_factor={self.size_reduction_factor}"
        )
    
    def set_promotion_controller(self, controller):
        """Set the promotion controller for dynamic mode control."""
        self.promotion_controller = controller
    
    def _get_effective_mode(self, symbol: str) -> str:
        """
        Get effective overlay mode for a symbol, considering promotion controller.
        
        Returns: "off" | "observe" | "gating_size_reduce" | "gating_block"
        """
        # If no promotion controller, use static config
        if self.promotion_controller is None:
            if self.observe_mode:
                return "observe"
            return "gating_size_reduce" if self.spoof_action == "size_reduce" else "gating_block"
        
        # Use promotion controller's mode
        try:
            from rl.promotion_controller import OverlayMode
            mode = self.promotion_controller.overlay_mode()
            
            # Check if this symbol should be gated (canary targeting)
            if mode in (OverlayMode.GATING_SIZE_REDUCE, OverlayMode.GATING_BLOCK):
                if not self.promotion_controller.apply_to_symbol(symbol):
                    # Not in canary set - fall back to observe
                    return "observe"
            
            return mode.value
        except Exception as e:
            logger.debug(f"[MICRO] Promotion controller error: {e}")
            return "observe" if self.observe_mode else "gating_size_reduce"
    
    def _get_ingestor_router(self):
        """Get ingestor quality router (lazy load)."""
        if self._ingestor_router is None:
            try:
                from rl.ingestor_quality_router import get_ingestor_router
                self._ingestor_router = get_ingestor_router(self.redis)
            except ImportError:
                logger.debug("[MICRO] Ingestor router not available, using direct Redis reads")
        return self._ingestor_router
    
    def _get_snapshot_history(self, symbol: str) -> deque:
        """Get snapshot history for symbol."""
        if symbol not in self._snapshot_history:
            self._snapshot_history[symbol] = deque(maxlen=self.MAX_SNAPSHOT_HISTORY)
        return self._snapshot_history[symbol]
    
    def _classify_action(self, action: str) -> Tuple[bool, bool]:
        """Classify action as (is_entry, is_protective)."""
        action_upper = str(action).upper()
        is_entry = any(kw in action_upper for kw in self.ENTRY_KEYWORDS)
        # Hedges are risk-reducing actions and must NEVER be blocked by microstructure gating.
        # Treat any action containing "HEDGE" as protective (even if it is OPEN-like).
        is_protective = any(kw in action_upper for kw in self.PROTECTIVE_KEYWORDS) or ("HEDGE" in action_upper)
        return is_entry, is_protective
    
    def _get_source_router(self):
        """Get microstructure source router (lazy load)."""
        if not hasattr(self, '_source_router') or self._source_router is None:
            try:
                from rl.microstructure_source_router import get_source_router
                self._source_router = get_source_router(self.redis)
            except ImportError:
                logger.debug("[MICRO] Source router not available")
                self._source_router = None
        return self._source_router
    
    def _load_msnap_scores(self, symbol: str) -> Optional[Dict[str, float]]:
        """
        Load pre-computed scores from msnap (CoinAPI or other sources).
        
        Returns dict with spoof_score, fast_move_score, etc., or None if not available.
        """
        source_router = self._get_source_router()
        if source_router:
            snapshot, source = source_router.get_best_snapshot(symbol)
            if snapshot and snapshot.is_healthy:
                return {
                    'spoof_score': snapshot.spoof_score,
                    'fast_move_score': snapshot.fast_move_score,
                    'churn_score': snapshot.churn_score,
                    'snapback_score': snapshot.snapback_score,
                    'imbalance': snapshot.imbalance_5,
                    'spread': snapshot.spread,
                    'source': snapshot.source,
                    'staleness_ms': snapshot.src_staleness_ms,
                }
        return None
    
    def _load_canonical_orderbook(self, symbol: str) -> Tuple[Dict[str, Any], bool]:
        """
        Load canonical orderbook from best source.
        
        Priority:
        1. Microstructure source router (CoinAPI, Binance WS, etc.)
        2. Ingestor quality router canonical
        3. orderbook:top:{symbol}
        4. unified_features ob_* fields
        
        Returns:
            (orderbook_data, is_healthy)
        """
        data = {}
        is_healthy = False
        source = "none"
        
        # Try microstructure source router first (includes CoinAPI)
        source_router = self._get_source_router()
        if source_router:
            snapshot, micro_source = source_router.get_best_snapshot(symbol)
            if snapshot and snapshot.is_healthy:
                data = {
                    'bid': snapshot.best_bid_px,
                    'ask': snapshot.best_ask_px,
                    'bid_price': snapshot.best_bid_px,
                    'ask_price': snapshot.best_ask_px,
                    'bid_depth': snapshot.best_bid_sz,
                    'ask_depth': snapshot.best_ask_sz,
                    'spread': snapshot.spread,
                    'imbalance': snapshot.imbalance_5,
                    'microprice': snapshot.microprice,
                    # Prefer top-5 depth sums when available (more stable than top-1 sizes)
                    'book_bid_sum_5': getattr(snapshot, "book_bid_sum_5", 0.0),
                    'book_ask_sum_5': getattr(snapshot, "book_ask_sum_5", 0.0),
                    'source': snapshot.source,
                    'is_healthy': True,
                    'updated_ts': snapshot.updated_ts_ms,
                    # Pre-computed scores from msnap
                    'spoof_score': snapshot.spoof_score,
                    'spoof_score_v1': getattr(snapshot, "spoof_score_v1", 0.0),
                    'spoof_score_v2': getattr(snapshot, "spoof_score_v2", 0.0),
                    'p_false_move': getattr(snapshot, "p_false_move", 0.0),
                    'fast_move_score': snapshot.fast_move_score,
                    'fast_move_max_1m': snapshot.fast_move_max_1m,  # Rolling max for trainer
                    'fast_move_max_5m': snapshot.fast_move_max_5m,  # Rolling max for trainer
                    'churn_score': snapshot.churn_score,
                    'snapback_score': snapshot.snapback_score,
                    # Tape confirmation / divergence proxies (may be 0 if trade feed disabled)
                    'trade_total_notional_1s': getattr(snapshot, "trade_total_notional_1s", 0.0),
                    'trade_imbalance_1s': getattr(snapshot, "trade_imbalance_1s", 0.0),
                    'impact_bps_1s': getattr(snapshot, "impact_bps_1s", 0.0),
                    'impact_per_musd_1s': getattr(snapshot, "impact_per_musd_1s", 0.0),
                }
                return data, True
        
        # Try ingestor router 
        router = self._get_ingestor_router()
        if router:
            canonical = router.get_canonical_orderbook(symbol)
            if canonical.get('is_healthy'):
                data = canonical
                source = canonical.get('source', 'router')
                is_healthy = True
                return data, is_healthy
        
        # Fallback: Direct Redis reads
        if self.redis:
            # Try orderbook:top first (may be JSON string or hash)
            try:
                key = f"orderbook:top:{symbol}"
                key_type = self.redis.type(key)
                key_type = key_type.decode() if isinstance(key_type, bytes) else key_type
                
                if key_type == 'string':
                    # JSON string format (newer format)
                    raw = self.redis.get(key)
                    if raw:
                        raw_str = raw.decode('utf-8') if isinstance(raw, bytes) else raw
                        data = json.loads(raw_str)
                        if data.get('bid') or data.get('ask'):
                            source = data.get('source', 'orderbook:top')
                            is_healthy = True
                elif key_type == 'hash':
                    # Hash format (older format)
                    raw = self.redis.hgetall(key)
                    if raw:
                        for k, v in raw.items():
                            k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                            v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                            data[k_str] = v_str
                        
                        if data.get('bid') or data.get('bid_price'):
                            source = "orderbook:top"
                            is_healthy = True
            except Exception as e:
                logger.debug(f"[MICRO] Failed to read orderbook:top:{symbol}: {e}")
            
            # Fallback to unified_features
            if not is_healthy:
                try:
                    for tf in ['5m', '1m', '15m']:
                        raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                        if raw:
                            for k, v in raw.items():
                                k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                                v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                                if k_str.startswith('ob_'):
                                    data[k_str] = v_str
                            
                            if data:
                                source = f"unified_features:{tf}"
                                is_healthy = True
                                break
                except Exception as e:
                    logger.debug(f"[MICRO] Failed to read unified_features for {symbol}: {e}")
        
        data['source'] = source
        data['is_healthy'] = is_healthy
        
        return data, is_healthy
    
    def update_snapshot(self, symbol: str, orderbook_data: Dict[str, Any]) -> MicrostructureSnapshot:
        """Update snapshot from orderbook data."""
        now_ms = int(time.time() * 1000)
        
        snapshot = MicrostructureSnapshot(
            symbol=symbol,
            timestamp_ms=now_ms,
            source=str(orderbook_data.get('source', '')),
            is_healthy=bool(orderbook_data.get('is_healthy', False)),
        )
        
        try:
            # Parse bid/ask from various field naming conventions
            snapshot.bid_price = float(
                orderbook_data.get('bid', 0) or 
                orderbook_data.get('bid_price', 0) or 
                orderbook_data.get('ob_bid_price', 0) or 0
            )
            snapshot.ask_price = float(
                orderbook_data.get('ask', 0) or 
                orderbook_data.get('ask_price', 0) or 
                orderbook_data.get('ob_ask_price', 0) or 0
            )
            snapshot.bid_depth = float(
                orderbook_data.get('bid_qty', 0) or 
                orderbook_data.get('bid_depth', 0) or 
                orderbook_data.get('ob_bid_depth', 0) or 0
            )
            snapshot.ask_depth = float(
                orderbook_data.get('ask_qty', 0) or 
                orderbook_data.get('ask_depth', 0) or 
                orderbook_data.get('ob_ask_depth', 0) or 0
            )

            # Prefer depth sums over top-1 sizes when available
            snapshot.book_bid_sum_5 = float(
                orderbook_data.get('book_bid_sum_5', 0) or
                orderbook_data.get('bid_sum_5', 0) or
                snapshot.bid_depth or 0
            )
            snapshot.book_ask_sum_5 = float(
                orderbook_data.get('book_ask_sum_5', 0) or
                orderbook_data.get('ask_sum_5', 0) or
                snapshot.ask_depth or 0
            )

            # Tape / divergence proxies (optional)
            snapshot.trade_total_notional_1s = float(orderbook_data.get('trade_total_notional_1s', 0) or 0)
            snapshot.trade_imbalance_1s = float(orderbook_data.get('trade_imbalance_1s', 0) or 0)
            snapshot.impact_bps_1s = float(orderbook_data.get('impact_bps_1s', 0) or 0)
            snapshot.impact_per_musd_1s = float(orderbook_data.get('impact_per_musd_1s', 0) or 0)
            snapshot.p_false_move = float(orderbook_data.get('p_false_move', 0) or 0)
            
            # Compute derived metrics
            if snapshot.bid_price > 0 and snapshot.ask_price > 0:
                snapshot.spread_pct = (snapshot.ask_price - snapshot.bid_price) / snapshot.bid_price * 100
                total_depth = snapshot.book_bid_sum_5 + snapshot.book_ask_sum_5
                if total_depth > 0:
                    snapshot.microprice = (
                        snapshot.bid_price * snapshot.book_ask_sum_5 + 
                        snapshot.ask_price * snapshot.book_bid_sum_5
                    ) / total_depth
                    snapshot.imbalance = (snapshot.book_bid_sum_5 - snapshot.book_ask_sum_5) / total_depth
                    snapshot.depth_ratio = snapshot.book_bid_sum_5 / snapshot.book_ask_sum_5 if snapshot.book_ask_sum_5 > 0 else 1.0
                
                snapshot.is_healthy = True
            else:
                snapshot.is_healthy = False
            
        except Exception as e:
            logger.debug(f"[MICRO] Error parsing orderbook for {symbol}: {e}")
            snapshot.is_healthy = False
        
        # Add to history
        history = self._get_snapshot_history(symbol)
        history.append(snapshot)
        
        return snapshot
    
    def compute_spoof_score(self, symbol: str) -> SpoofScore:
        """Compute spoof detection score from snapshot history."""
        score = SpoofScore(threshold=self.spoof_threshold)
        
        history = self._get_snapshot_history(symbol)
        if len(history) < 3:
            score.inputs_valid = False
            return score
        
        # Check if recent snapshots are healthy
        recent = list(history)[-5:]
        healthy_count = sum(1 for s in recent if s.is_healthy)
        if healthy_count < 2:
            score.inputs_valid = False
            return score
        
        try:
            snapshots = [s for s in history if s.is_healthy]
            if len(snapshots) < 3:
                score.inputs_valid = False
                return score
            
            # 1. Imbalance snapback: Strong imbalance followed by reversal
            imbalances = [s.imbalance for s in snapshots]
            if len(imbalances) >= 5:
                recent_imbalance = imbalances[-1]
                prev_imbalance = sum(imbalances[-5:-1]) / 4
                if abs(prev_imbalance) > 0.3 and abs(recent_imbalance - prev_imbalance) > 0.4:
                    score.imbalance_snapback = min(1.0, abs(recent_imbalance - prev_imbalance))
            
            # 2. Pressure persistence: fraction of recent samples with strong imbalance (higher = more persistent)
            recent_window = imbalances[-10:] if len(imbalances) >= 10 else imbalances
            strong = [imb for imb in recent_window if abs(imb) > 0.3]
            score.pressure_persistence = float(len(strong)) / float(max(1, len(recent_window)))
            
            # 3. Size churn: Volatility of near-touch depth (prefer top5 sums when available)
            depths = [
                (float(getattr(s, "book_bid_sum_5", 0.0) or 0.0) + float(getattr(s, "book_ask_sum_5", 0.0) or 0.0))
                for s in snapshots
            ]
            depths = [d for d in depths if d > 0]
            if len(depths) >= 3:
                mean_depth = sum(depths) / len(depths)
                if mean_depth > 0:
                    depth_std = (sum((d - mean_depth)**2 for d in depths) / len(depths)) ** 0.5
                    score.size_churn = min(1.0, depth_std / mean_depth)

            # 4. Ghost liquidity proxy: surge then pull in top5 depth
            try:
                if len(snapshots) >= 4:
                    b_hist = [float(getattr(s, "book_bid_sum_5", 0.0) or 0.0) for s in snapshots[-4:]]
                    a_hist = [float(getattr(s, "book_ask_sum_5", 0.0) or 0.0) for s in snapshots[-4:]]
                    bid_prev, bid_curr = b_hist[-2], b_hist[-1]
                    ask_prev, ask_curr = a_hist[-2], a_hist[-1]
                    bid_drop = max(0.0, (bid_prev - bid_curr) / (bid_prev + 1e-9))
                    ask_drop = max(0.0, (ask_prev - ask_curr) / (ask_prev + 1e-9))
                    bid_base = sum(b_hist[:-1]) / max(1, len(b_hist[:-1]))
                    ask_base = sum(a_hist[:-1]) / max(1, len(a_hist[:-1]))
                    bid_surge = 1.0 if bid_prev > (bid_base * 1.5 + 1e-9) else 0.0
                    ask_surge = 1.0 if ask_prev > (ask_base * 1.5 + 1e-9) else 0.0
                    ghost = max(bid_drop * bid_surge, ask_drop * ask_surge)
                    score.ghost_liquidity = min(1.0, ghost / 0.5)  # 50% pull ~= 1.0
            except Exception:
                score.ghost_liquidity = 0.0

            # 5. Tape divergence + imbalance-to-impact proxies (only if tape/impact fields exist)
            try:
                last = snapshots[-1]
                score.tape_total_notional_1s = float(getattr(last, "trade_total_notional_1s", 0.0) or 0.0)
                min_tape = float(os.getenv("MICRO_SPOOF_MIN_TAPE_NOTIONAL_1S", "20000"))
                score.tape_available = bool(score.tape_total_notional_1s >= min_tape)

                disp_imb = float(getattr(last, "imbalance", 0.0) or 0.0)
                tape_imb = float(getattr(last, "trade_imbalance_1s", 0.0) or 0.0)
                if score.tape_available and abs(disp_imb) > 0.35 and abs(tape_imb) > 0.10 and disp_imb * tape_imb < 0:
                    score.tape_divergence = min(1.0, abs(disp_imb) + abs(tape_imb))
                elif score.tape_available and abs(disp_imb) > 0.6 and abs(tape_imb) < 0.05:
                    score.tape_divergence = 0.35

                impact_bps = float(getattr(last, "impact_bps_1s", 0.0) or 0.0)
                impact_norm = min(1.0, max(0.0, impact_bps / 10.0))
                score.imbalance_to_impact = min(1.0, abs(disp_imb) / 0.8) * (1.0 - impact_norm)

                score.p_false_move = float(getattr(last, "p_false_move", 0.0) or 0.0)
            except Exception:
                pass
            
            # Combine scores (precision-oriented). Low persistence increases suspicion.
            persistence_susp = 1.0 - float(score.pressure_persistence or 0.0)
            score.score = (
                score.imbalance_snapback * 0.25 +
                persistence_susp * 0.15 +
                score.size_churn * 0.20 +
                score.ghost_liquidity * 0.15 +
                score.tape_divergence * 0.15 +
                score.imbalance_to_impact * 0.10
            )

            # If the ingestor already computed a strong false-move probability, respect it.
            if score.p_false_move > 0:
                score.score = max(float(score.score), min(1.0, 0.8 * float(score.p_false_move)))

            score.is_high = score.score >= score.threshold
            
        except Exception as e:
            logger.debug(f"[MICRO] Error computing spoof score for {symbol}: {e}")
            score.inputs_valid = False
        
        return score
    
    def compute_fast_move_score(
        self, 
        symbol: str,
        features_1m: Optional[Dict] = None,
        features_5m: Optional[Dict] = None,
    ) -> FastMoveScore:
        """Compute fast-move detection score."""
        score = FastMoveScore(threshold=self.fast_move_threshold)
        
        history = self._get_snapshot_history(symbol)
        
        # Check input validity
        if len(history) < 3:
            score.inputs_valid = False
        
        healthy_history = [s for s in history if s.is_healthy]
        
        try:
            # 1. Volatility spikes from features
            # FIX: Check actual Redis keys - ind_ta_volatility_{tf}, ccxt_volatility_{tf}
            if features_1m:
                vol_1m = float(
                    features_1m.get('realized_vol', 0) or 
                    features_1m.get('volatility', 0) or 
                    features_1m.get('ind_ta_volatility_1m', 0) or
                    features_1m.get('ccxt_volatility_1m', 0) or 0
                )
                avg_vol_1m = float(
                    features_1m.get('avg_volatility', 0) or 
                    features_1m.get('ind_ta_volatility_5m', 0) or  # Use 5m as baseline for 1m
                    vol_1m * 0.8
                )  # Fallback
                if avg_vol_1m > 0:
                    score.vol_spike_1m = min(1.0, max(0, vol_1m / avg_vol_1m - 1))
            
            if features_5m:
                vol_5m = float(
                    features_5m.get('realized_vol', 0) or 
                    features_5m.get('volatility', 0) or 
                    features_5m.get('ind_ta_volatility_5m', 0) or
                    features_5m.get('ccxt_volatility_5m', 0) or 0
                )
                avg_vol_5m = float(
                    features_5m.get('avg_volatility', 0) or 
                    features_5m.get('ind_ta_volatility_1h', 0) or  # Use 1h as baseline for 5m
                    vol_5m * 0.8
                )
                if avg_vol_5m > 0:
                    score.vol_spike_5m = min(1.0, max(0, vol_5m / avg_vol_5m - 1))
            
            # 2. Spread widening
            if len(healthy_history) >= 5:
                recent_spread = healthy_history[-1].spread_pct
                old_spreads = [s.spread_pct for s in healthy_history[-5:-1]]
                old_spread = sum(old_spreads) / len(old_spreads) if old_spreads else recent_spread
                if old_spread > 0:
                    score.spread_widening = min(1.0, max(0, (recent_spread - old_spread) / old_spread))
            
            # 3. Microprice jump
            if len(healthy_history) >= 3:
                microprices = [s.microprice for s in healthy_history if s.microprice > 0]
                if len(microprices) >= 3:
                    recent_mp = microprices[-1]
                    old_mps = microprices[-5:-1] if len(microprices) > 4 else microprices[:-1]
                    old_mp = sum(old_mps) / len(old_mps) if old_mps else recent_mp
                    if old_mp > 0:
                        mp_change = abs(recent_mp - old_mp) / old_mp * 100
                        score.microprice_jump = min(1.0, mp_change / 0.5)  # Normalize by 0.5% move
            
            # 4. Liquidation burst (from features if available)
            if features_1m:
                liq_long = float(features_1m.get('liquidation_long', 0) or 0)
                liq_short = float(features_1m.get('liquidation_short', 0) or 0)
                total_liq = liq_long + liq_short
                if total_liq > 0:
                    score.liquidation_burst = min(1.0, total_liq / 1e6)  # Normalize by $1M
            
            # Combine scores
            score.score = (
                max(score.vol_spike_1m, score.vol_spike_5m) * 0.4 +
                score.spread_widening * 0.2 +
                score.microprice_jump * 0.2 +
                score.liquidation_burst * 0.2
            )
            score.is_high = score.score >= score.threshold
            
        except Exception as e:
            logger.debug(f"[MICRO] Error computing fast-move score for {symbol}: {e}")
        
        return score
    
    def evaluate(
        self,
        symbol: str,
        action: str,
        confidence: float,
        position_size_pct: float,
        orderbook_data: Optional[Dict] = None,
        features_1m: Optional[Dict] = None,
        features_5m: Optional[Dict] = None,
        has_position: bool = False,
    ) -> OverlayResult:
        """
        Evaluate a signal through the microstructure overlay.
        
        CRITICAL:
        - Protective actions (CLOSE, DECREASE, REDUCE) are NEVER blocked
        - Observe mode logs but doesn't block
        - Gating mode blocks/reduces entries only
        
        Returns:
            OverlayResult with decision and modified parameters
        """
        now_ms = int(time.time() * 1000)
        is_entry, is_protective = self._classify_action(action)
        
        result = OverlayResult(
            symbol=symbol,
            decision=OverlayDecision.PASS,
            action_in=action,
            conf_in=confidence,
            size_in=position_size_pct,
            action_out=action,
            conf_required=confidence,
            size_out=position_size_pct,
            timestamp_ms=now_ms,
            is_entry=is_entry,
            is_protective=is_protective,
            has_position=has_position,
        )
        
        # Load canonical orderbook if not provided
        if orderbook_data is None:
            orderbook_data, inputs_healthy = self._load_canonical_orderbook(symbol)
            result.inputs_healthy = inputs_healthy
            result.data_source = str(orderbook_data.get('source', 'none'))
        else:
            result.inputs_healthy = orderbook_data.get('is_healthy', bool(orderbook_data))
            result.data_source = str(orderbook_data.get('source', 'provided'))
        
        # Update snapshot
        if orderbook_data:
            snapshot = self.update_snapshot(symbol, orderbook_data)
            result.inputs_healthy = snapshot.is_healthy
        
        # Compute scores - use pre-computed from msnap if available
        # Prefer v2 score when provided by ingestors.
        precomputed_spoof = None
        if orderbook_data:
            try:
                v2 = orderbook_data.get('spoof_score_v2')
                if v2 is not None and float(v2 or 0) > 0:
                    precomputed_spoof = v2
                else:
                    precomputed_spoof = orderbook_data.get('spoof_score')
            except Exception:
                precomputed_spoof = orderbook_data.get('spoof_score')
        precomputed_fast = orderbook_data.get('fast_move_score') if orderbook_data else None
        
        # CRITICAL: Use rolling max values instead of instantaneous for trainer consumption
        # Fast moves happen in milliseconds but trainer runs every 30s - rolling max captures them
        precomputed_fast_max_1m = orderbook_data.get('fast_move_max_1m') if orderbook_data else None
        precomputed_fast_max_5m = orderbook_data.get('fast_move_max_5m') if orderbook_data else None
        
        # Prefer rolling max over instantaneous (rolling max persists the signal)
        effective_fast_score = 0.0
        if precomputed_fast_max_1m is not None:
            effective_fast_score = max(effective_fast_score, float(precomputed_fast_max_1m or 0))
        if precomputed_fast is not None:
            effective_fast_score = max(effective_fast_score, float(precomputed_fast or 0))
        
        # Always compute local v2 components from snapshot history (ghost liquidity, divergence, etc.)
        local_spoof = self.compute_spoof_score(symbol)

        if precomputed_spoof is not None and float(precomputed_spoof or 0) > 0:
            # Blend: keep precomputed as primary, but incorporate local components for robustness.
            try:
                pre = float(precomputed_spoof or 0.0)
            except Exception:
                pre = 0.0
            try:
                p_false = float(orderbook_data.get('p_false_move', 0) or 0) if orderbook_data else 0.0
            except Exception:
                p_false = 0.0
            blended = min(1.0, 0.6 * pre + 0.4 * float(local_spoof.score or 0.0))
            final_score = max(pre, blended, p_false)

            # Attach components + msnap fields
            local_spoof.score = float(final_score)
            local_spoof.churn_score = float(orderbook_data.get('churn_score', 0) or 0) if orderbook_data else 0.0
            local_spoof.snapback_score = float(orderbook_data.get('snapback_score', 0) or 0) if orderbook_data else 0.0
            local_spoof.p_false_move = float(orderbook_data.get('p_false_move', 0) or 0) if orderbook_data else 0.0
            local_spoof.tape_total_notional_1s = float(orderbook_data.get('trade_total_notional_1s', 0) or 0) if orderbook_data else 0.0
            local_spoof.tape_available = bool(local_spoof.tape_total_notional_1s >= float(os.getenv("MICRO_SPOOF_MIN_TAPE_NOTIONAL_1S", "20000")))
            local_spoof.is_high = local_spoof.score >= self.spoof_threshold
            local_spoof.threshold = self.spoof_threshold
            result.spoof_score = local_spoof
        else:
            # No msnap score available -> use local score
            result.spoof_score = local_spoof
        
        if effective_fast_score > 0:
            # Use rolling max fast-move score from CoinAPI (persists across 30s trainer cycles)
            result.fast_move_score = FastMoveScore(
                score=effective_fast_score,
                is_high=effective_fast_score >= self.fast_move_threshold,
                threshold=self.fast_move_threshold,
                inputs_valid=True,
            )
        else:
            result.fast_move_score = self.compute_fast_move_score(symbol, features_1m, features_5m)
        
        # Handle unhealthy inputs
        if not result.inputs_healthy or (not result.spoof_score.inputs_valid and not result.fast_move_score.inputs_valid):
            result.decision = OverlayDecision.INPUTS_UNHEALTHY
            result.reason_code = BlockReason.OVERLAY_INPUTS_UNHEALTHY
            # NEVER block protective actions even with unhealthy inputs.
            # Also: in observe mode, we must never block (tests + contract).
            if is_protective or self.observe_mode:
                result.decision = OverlayDecision.PASS
                result.reason_code = None
            logger.info(result.to_log_line())
            return result
        
        # CRITICAL: Protective actions are NEVER blocked
        if is_protective:
            # Check if fast-move is high - give protective priority
            if result.fast_move_score.is_high:
                result.reason_code = BlockReason.FAST_MOVE_PROTECTIVE_PRIORITY
            result.decision = OverlayDecision.PASS
            logger.info(result.to_log_line())
            return result
        
        # Get effective mode for this symbol (considering promotion controller and canary)
        effective_mode = self._get_effective_mode(symbol)
        
        # Apply overlay rules based on effective mode
        if effective_mode not in ("off", "observe") and is_entry:
            # --------------------------------------------------------------
            # Selective validation / abstention (high precision mode)
            #
            # If enabled, we refuse to open fresh exposure when tape confirmation
            # is unavailable (UNVERIFIED). Protective actions are handled above.
            # --------------------------------------------------------------
            try:
                abstain_no_tape = os.getenv("MICROSTRUCTURE_ABSTAIN_NO_TAPE", "false").lower() in ("1", "true", "yes", "on")
            except Exception:
                abstain_no_tape = False
            if abstain_no_tape and (not has_position) and (not bool(getattr(result.spoof_score, "tape_available", False))):
                result.decision = OverlayDecision.BLOCK
                result.reason_code = BlockReason.SPOOF_UNVERIFIED_BLOCK
                logger.info(result.to_log_line())
                return result

            # Rule 1: Spoof detection for entries
            if result.spoof_score.is_high:
                # Check if blocking is allowed by mode and score severity
                if effective_mode == "gating_block" and result.spoof_score.score >= 0.8:
                    # Very high spoof risk - block entry
                    result.decision = OverlayDecision.BLOCK
                    result.reason_code = BlockReason.SPOOF_RISK_BLOCK
                else:
                    # Reduce size (for both gating_size_reduce and lower spoof scores)
                    result.decision = OverlayDecision.SIZE_REDUCE
                    result.reason_code = BlockReason.SPOOF_SIZE_REDUCE
                    result.size_multiplier = self.size_reduction_factor
                    result.size_out = position_size_pct * result.size_multiplier
                    # Also raise confidence requirement
                    result.conf_required = min(0.95, confidence + self.min_conf_raise)
            
            # Rule 2: Fast-move detection - block new entries (not increases on existing)
            if result.fast_move_score.is_high and not has_position:
                # Only block if mode allows it
                if effective_mode == "gating_block":
                    result.decision = OverlayDecision.BLOCK
                    result.reason_code = BlockReason.FAST_MOVE_ENTRY_BLOCK
                else:
                    # In gating_size_reduce mode, just reduce size instead
                    if result.decision != OverlayDecision.BLOCK:
                        result.decision = OverlayDecision.SIZE_REDUCE
                        result.reason_code = BlockReason.FAST_MOVE_ENTRY_BLOCK  # Keep reason for logging
                        result.size_multiplier = self.size_reduction_factor * 0.5  # Extra reduction
                        result.size_out = position_size_pct * result.size_multiplier
        
        # Log result
        logger.info(result.to_log_line())
        
        # Publish intent to stream
        if self.redis:
            self.publish_intent(result)
        
        return result
    
    def evaluate_1m_action(
        self,
        symbol: str,
        action: str,
        confidence: float,
        has_position: bool,
        **kwargs,
    ) -> OverlayResult:
        """
        Special evaluation for 1m timeframe.
        
        Rule: 1m is learning-only when flat. Overlay MUST NOT open fresh risk on 1m.
        Only protective/management actions allowed when flat.
        """
        is_entry, is_protective = self._classify_action(action)
        
        # If flat and 1m wants to open, block it
        if not has_position and is_entry:
            result = OverlayResult(
                symbol=symbol,
                decision=OverlayDecision.BLOCK,
                reason_code=BlockReason.FAST_MOVE_ENTRY_BLOCK,  # Reuse reason
                action_in=action,
                conf_in=confidence,
                size_in=kwargs.get('position_size_pct', 0),
                action_out="HOLD",
                is_entry=True,
                is_protective=False,
                has_position=False,
                timestamp_ms=int(time.time() * 1000),
            )
            logger.info(f"MICRO_OVERLAY | {symbol} | 1m_entry_blocked (flat) | action={action}")
            return result
        
        # Otherwise, normal evaluation
        return self.evaluate(
            symbol=symbol,
            action=action,
            confidence=confidence,
            has_position=has_position,
            **kwargs,
        )
    
    def publish_intent(self, result: OverlayResult):
        """Publish overlay intent to Redis stream."""
        if self.redis is None:
            return
        
        try:
            from utils.signal_publish import publish_overlay_intent

            publish_overlay_intent(
                self.redis,
                {
                    "symbol": result.symbol,
                    "decision": result.decision.value,
                    "reason_code": result.reason_code.value if result.reason_code else "none",
                    "spoof_score": str(result.spoof_score.score if result.spoof_score else 0),
                    "fast_move_score": str(result.fast_move_score.score if result.fast_move_score else 0),
                    "action_in": result.action_in,
                    "action_out": result.action_out,
                    "size_multiplier": str(result.size_multiplier),
                    "is_protective": str(result.is_protective),
                    "inputs_healthy": str(result.inputs_healthy),
                    "ts_ms": str(result.timestamp_ms),
                },
                stream="signals:overlay:intents",
                maxlen=1000,
                approximate=True,
            )
        except Exception as e:
            logger.debug(f"[MICRO] Failed to publish intent: {e}")
    
    def publish_skip_event(self, result: OverlayResult, stream_name: str = "signals:execution:skips"):
        """Publish skip event to Redis."""
        if self.redis is None or result.decision == OverlayDecision.PASS:
            return
        
        try:
            self.redis.xadd(
                stream_name,
                result.to_skip_event(),
                maxlen=5000,
                approximate=True,
            )
        except Exception as e:
            logger.debug(f"[MICRO] Failed to publish skip event: {e}")


# Global instance
_microstructure_overlay: Optional[MicrostructureOverlay] = None


def get_microstructure_overlay(
    redis_client: Any = None,
    force_new: bool = False,
) -> MicrostructureOverlay:
    """Get global microstructure overlay instance."""
    global _microstructure_overlay
    if _microstructure_overlay is None or force_new:
        # Config-backed defaults (env overrides win)
        try:
            import config as _cfg
            cfg_enabled = bool(getattr(_cfg, "ENABLE_MICROSTRUCTURE_OVERLAY", True))
            cfg_mode = str(getattr(_cfg, "MICROSTRUCTURE_OVERLAY_MODE", "gating"))
            cfg_spoof_thr = float(getattr(_cfg, "MICROSTRUCTURE_SPOOF_THRESHOLD", 0.6))
            cfg_fast_thr = float(getattr(_cfg, "MICROSTRUCTURE_FAST_MOVE_THRESHOLD", 0.7))
            cfg_spoof_action = str(getattr(_cfg, "MICROSTRUCTURE_SPOOF_ACTION", "size_reduce"))
            cfg_size_factor = float(getattr(_cfg, "MICROSTRUCTURE_SPOOF_SIZE_MULTIPLIER", 0.5))
        except Exception:
            cfg_enabled = True
            cfg_mode = "gating"
            cfg_spoof_thr = 0.6
            cfg_fast_thr = 0.7
            cfg_spoof_action = "size_reduce"
            cfg_size_factor = 0.5

        enabled_env = os.getenv("ENABLE_MICROSTRUCTURE_OVERLAY")
        enabled = cfg_enabled if enabled_env is None else (str(enabled_env).lower() in ("1", "true", "yes", "on"))

        mode_env = os.getenv("MICROSTRUCTURE_OVERLAY_MODE")
        mode = (cfg_mode if mode_env is None else str(mode_env)).lower()
        observe_mode = (mode == "observe") or (not enabled)
        _microstructure_overlay = MicrostructureOverlay(
            redis_client=redis_client,
            observe_mode=observe_mode,
            spoof_threshold=cfg_spoof_thr,
            fast_move_threshold=cfg_fast_thr,
            spoof_action=cfg_spoof_action,
            size_reduction_factor=cfg_size_factor,
        )
    elif redis_client is not None and _microstructure_overlay.redis is None:
        _microstructure_overlay.redis = redis_client
    return _microstructure_overlay


def is_overlay_enabled() -> bool:
    """Check if overlay is enabled."""
    enabled_env = os.getenv("ENABLE_MICROSTRUCTURE_OVERLAY")
    if enabled_env is not None:
        return str(enabled_env).lower() in ("1", "true", "yes", "on")
    try:
        import config as _cfg
        return bool(getattr(_cfg, "ENABLE_MICROSTRUCTURE_OVERLAY", True))
    except Exception:
        return True


def is_gating_mode() -> bool:
    """Check if overlay is in gating mode."""
    return os.getenv("MICROSTRUCTURE_OVERLAY_MODE", "gating").lower() == "gating"
