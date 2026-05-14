"""
SMART ENTRY GATE (V2)
=====================
Intelligent entry timing to exploit market maker moves instead of chasing them.

Core Strategy:
1. Detect fast moves (pump/dump spikes) - likely MM manipulation
2. Wait for pullback/retracement (30-50% of move)
3. Enter WITH the trend on retracement, not during the spike
4. Or counter-trade if HTF suggests reversal

This turns "stop hunt traps" into "entry opportunities".

Kill Switch: SMART_ENTRY_GATE_ENABLED must be true to use this gate.
"""

import json
import logging
import time
import redis
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

# Import config - fail gracefully if not available
try:
    from config import (
        REDIS_URL,
        SMART_ENTRY_GATE_ENABLED,
        SMART_ENTRY_VELOCITY_THRESHOLD,
        SMART_ENTRY_RETRACEMENT_MIN,
        SMART_ENTRY_RETRACEMENT_MAX,
        SMART_ENTRY_COOLDOWN_SECONDS,
        SMART_ENTRY_HUNTING_ZONE_TTL,
        SMART_ENTRY_REVERSAL_FASTPATH_ENABLED,
        SMART_ENTRY_REVERSAL_MIN_SCORE,
        SMART_ENTRY_REVERSAL_SIZE_MULT,
    )
except ImportError:
    REDIS_URL = "redis://localhost:6379/0"
    SMART_ENTRY_GATE_ENABLED = False
    SMART_ENTRY_VELOCITY_THRESHOLD = 0.3  # 0.3% move triggers detection
    SMART_ENTRY_RETRACEMENT_MIN = 0.30  # 30% retracement minimum
    SMART_ENTRY_RETRACEMENT_MAX = 0.618  # 61.8% Fibonacci
    SMART_ENTRY_COOLDOWN_SECONDS = 120  # 2 min cooldown after fast move
    SMART_ENTRY_HUNTING_ZONE_TTL = 900  # 15 min hunting zone window
    SMART_ENTRY_REVERSAL_FASTPATH_ENABLED = False
    SMART_ENTRY_REVERSAL_MIN_SCORE = 0.80
    SMART_ENTRY_REVERSAL_SIZE_MULT = 0.7

logger = logging.getLogger(__name__)


class EntryDecision(Enum):
    """Smart entry decision types."""
    ENTER_NOW = "ENTER_NOW"  # Good to enter
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"  # Fast move detected, wait
    ENTER_ON_RETRACEMENT = "ENTER_ON_RETRACEMENT"  # Retracement hit, enter
    COUNTER_ENTRY = "COUNTER_ENTRY"  # HTF says opposite, counter-trade
    COOLDOWN = "COOLDOWN"  # In cooldown period
    PASS = "PASS"  # No special handling needed


@dataclass
class MoveTracker:
    """Tracks a fast move for retracement analysis."""
    symbol: str
    direction: str  # 'UP' or 'DOWN'
    move_start_price: float
    move_peak_price: float
    move_magnitude_pct: float
    detected_ts: int  # Unix timestamp ms
    retracement_target_38: float = 0.0
    retracement_target_50: float = 0.0
    retracement_target_61: float = 0.0
    retracement_hit: bool = False
    retracement_level: float = 0.0
    expired: bool = False
    
    def calculate_retracement_levels(self):
        """Calculate Fibonacci retracement levels."""
        move_size = abs(self.move_peak_price - self.move_start_price)
        
        if self.direction == 'UP':
            # For up moves, retracement is below peak
            self.retracement_target_38 = self.move_peak_price - (move_size * 0.382)
            self.retracement_target_50 = self.move_peak_price - (move_size * 0.50)
            self.retracement_target_61 = self.move_peak_price - (move_size * 0.618)
        else:
            # For down moves, retracement is above trough
            self.retracement_target_38 = self.move_peak_price + (move_size * 0.382)
            self.retracement_target_50 = self.move_peak_price + (move_size * 0.50)
            self.retracement_target_61 = self.move_peak_price + (move_size * 0.618)
    
    def check_retracement(self, current_price: float) -> Tuple[bool, float]:
        """Check if price has retraced to entry zone."""
        if self.direction == 'UP':
            # For up moves, we want price to pull back (go down)
            if current_price <= self.retracement_target_38:
                if current_price >= self.retracement_target_61:
                    # In the golden zone (38-61%)
                    retracement_pct = (self.move_peak_price - current_price) / (self.move_peak_price - self.move_start_price)
                    return True, retracement_pct
        else:
            # For down moves, we want price to bounce (go up)
            if current_price >= self.retracement_target_38:
                if current_price <= self.retracement_target_61:
                    retracement_pct = (current_price - self.move_peak_price) / (self.move_start_price - self.move_peak_price)
                    return True, retracement_pct
        
        return False, 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'move_start_price': self.move_start_price,
            'move_peak_price': self.move_peak_price,
            'move_magnitude_pct': self.move_magnitude_pct,
            'detected_ts': self.detected_ts,
            'retracement_target_38': self.retracement_target_38,
            'retracement_target_50': self.retracement_target_50,
            'retracement_target_61': self.retracement_target_61,
            'retracement_hit': self.retracement_hit,
            'retracement_level': self.retracement_level,
        }


@dataclass 
class SmartEntryResult:
    """Result of smart entry analysis."""
    decision: EntryDecision
    original_action: str
    modified_action: Optional[str] = None
    delay_seconds: int = 0
    size_multiplier: float = 1.0
    entry_price_target: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    move_tracker: Optional[MoveTracker] = None
    htf_aligned: bool = True
    continuation_probability: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision': self.decision.value,
            'original_action': self.original_action,
            'modified_action': self.modified_action,
            'delay_seconds': self.delay_seconds,
            'size_multiplier': self.size_multiplier,
            'entry_price_target': self.entry_price_target,
            'reasons': self.reasons,
            'htf_aligned': self.htf_aligned,
            'continuation_probability': self.continuation_probability,
        }


class SmartEntryGate:
    """
    Intelligent entry timing gate that exploits market maker moves.
    
    Strategy:
    1. Detect fast moves (potential MM manipulation)
    2. Create "hunting zone" with retracement levels
    3. Wait for pullback to golden zone (38-61% Fib)
    4. Enter with HTF confirmation
    5. If HTF conflicts, consider counter-trade
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize the smart entry gate."""
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # Track active moves per symbol
        self.active_moves: Dict[str, MoveTracker] = {}
        
        # Cooldown tracking
        self.cooldowns: Dict[str, int] = {}  # symbol -> expiry_ts
        
        # Price history for move detection
        self.price_history: Dict[str, List[Tuple[int, float]]] = {}
        self.max_history_points = 60  # 1 minute at 1s intervals
        
        # Statistics
        self.stats = {
            'moves_detected': 0,
            'retracements_hit': 0,
            'entries_on_retracement': 0,
            'chases_blocked': 0,
            'counter_entries': 0,
        }
        
        logger.info(f"[SmartEntryGate] Initialized - ENABLED={SMART_ENTRY_GATE_ENABLED}")
    
    def analyze_entry(
        self,
        symbol: str,
        action: str,
        side: str,
        current_price: float,
        timeframe: str = "5m"
    ) -> SmartEntryResult:
        """
        Analyze if this is a good entry point or if we should wait.
        
        Args:
            symbol: Trading pair
            action: Proposed action (OPEN_LONG, OPEN_SHORT, etc.)
            side: BUY or SELL
            current_price: Current market price
            timeframe: Analysis timeframe
            
        Returns:
            SmartEntryResult with decision and modifications
        """
        # If gate is disabled, always pass through
        if not SMART_ENTRY_GATE_ENABLED:
            return SmartEntryResult(
                decision=EntryDecision.PASS,
                original_action=action,
                reasons=['GATE_DISABLED'],
            )
        
        # Skip non-entry actions
        if not self._is_entry_action(action):
            return SmartEntryResult(
                decision=EntryDecision.PASS,
                original_action=action,
                reasons=['NON_ENTRY_ACTION'],
            )
        
        # Update price history
        self._update_price_history(symbol, current_price)
        
        # Check cooldown
        if self._in_cooldown(symbol):
            remaining = (self.cooldowns[symbol] - int(time.time() * 1000)) // 1000
            return SmartEntryResult(
                decision=EntryDecision.COOLDOWN,
                original_action=action,
                delay_seconds=remaining,
                reasons=[f'COOLDOWN:{remaining}s'],
            )
        
        # Get market data
        features = self._get_features(symbol, timeframe)
        htf_bias = self._get_htf_bias(symbol)

        # Reversal fast-path: when microstructure + near-term price action indicates a reversal,
        # do NOT wait for a perfect retracement (often too late).
        try:
            if SMART_ENTRY_REVERSAL_FASTPATH_ENABLED:
                rev = self._reversal_fastpath_signal(symbol=symbol, current_price=current_price, features=features)
                if rev and float(rev.get("score", 0.0)) >= float(SMART_ENTRY_REVERSAL_MIN_SCORE):
                    entry_direction = 'LONG' if 'LONG' in action.upper() or side == 'BUY' else 'SHORT'
                    # Only trigger when the reversal points AGAINST the proposed direction (avoid over-trigger).
                    if rev.get("direction") and str(rev["direction"]).upper() != entry_direction:
                        # Suggest an explicit action override so downstream can avoid late reversal traps.
                        # We keep this scoped to simple entry actions; for other action shapes, we just
                        # provide COUNTER_ENTRY sizing guidance.
                        modified_action = None
                        a_u = str(action or "").upper()
                        if a_u in ("OPEN_LONG", "OPEN_SHORT"):
                            modified_action = "OPEN_LONG" if str(rev["direction"]).upper() == "LONG" else "OPEN_SHORT"
                        elif a_u in ("INCREASE_LONG", "INCREASE_SHORT"):
                            # Do not increase into reversal; prefer HOLD.
                            modified_action = "HOLD"

                        size_mult = float(SMART_ENTRY_REVERSAL_SIZE_MULT)
                        size_mult = max(0.25, min(1.0, size_mult))
                        return SmartEntryResult(
                            decision=EntryDecision.COUNTER_ENTRY,
                            original_action=action,
                            modified_action=modified_action,
                            size_multiplier=size_mult,
                            reasons=[
                                "REVERSAL_FASTPATH",
                                f"REV_SCORE:{float(rev.get('score', 0.0)):.2f}",
                                f"REV_DIR:{str(rev.get('direction'))}",
                                f"MS_IMB:{float(rev.get('imbalance_5', 0.0)):.2f}",
                                f"MS_SPOOF:{float(rev.get('spoof_score', 0.0)):.2f}",
                                f"MS_CHURN:{float(rev.get('churn_score', 0.0)):.2f}",
                            ],
                            htf_aligned=False,  # explicitly a counter / override
                            continuation_probability=float(rev.get("confidence", 0.4) or 0.4),
                        )
        except Exception:
            pass
        
        # Detect fast move
        fast_move = self._detect_fast_move(symbol, features, current_price)
        
        if fast_move:
            # Fast move detected - create/update hunting zone
            self._create_hunting_zone(symbol, fast_move, current_price)
            self.stats['moves_detected'] += 1
        
        # Check if we have an active hunting zone
        if symbol in self.active_moves:
            move = self.active_moves[symbol]
            
            # Check if expired
            age_sec = (int(time.time() * 1000) - move.detected_ts) / 1000
            if age_sec > SMART_ENTRY_HUNTING_ZONE_TTL:
                del self.active_moves[symbol]
                logger.info(f"[SmartEntry] {symbol} hunting zone expired after {age_sec:.0f}s")
            else:
                # Check for retracement
                return self._analyze_hunting_zone(
                    symbol, action, side, current_price, move, htf_bias, features
                )
        
        # No active hunting zone - check if entering during spike
        if fast_move:
            entry_direction = 'LONG' if 'LONG' in action.upper() or side == 'BUY' else 'SHORT'
            
            # Check if chasing the move
            is_chasing = (
                (fast_move['direction'] == 'UP' and entry_direction == 'LONG') or
                (fast_move['direction'] == 'DOWN' and entry_direction == 'SHORT')
            )
            
            if is_chasing:
                self.stats['chases_blocked'] += 1
                # Set cooldown
                self._set_cooldown(symbol, SMART_ENTRY_COOLDOWN_SECONDS)
                
                return SmartEntryResult(
                    decision=EntryDecision.WAIT_FOR_PULLBACK,
                    original_action=action,
                    delay_seconds=SMART_ENTRY_COOLDOWN_SECONDS,
                    size_multiplier=0.0,  # Block entry
                    reasons=[
                        f"CHASE_BLOCKED:{fast_move['direction']}",
                        f"VELOCITY:{fast_move['magnitude']:.2f}%",
                        "WAIT_FOR_RETRACEMENT"
                    ],
                )
        
        # Check if HTF aligned for normal entry
        entry_direction = 'LONG' if 'LONG' in action.upper() or side == 'BUY' else 'SHORT'
        htf_aligned = self._check_htf_alignment(entry_direction, htf_bias)
        
        if not htf_aligned:
            # HTF conflicts - reduce size or suggest counter
            return SmartEntryResult(
                decision=EntryDecision.ENTER_NOW,
                original_action=action,
                size_multiplier=0.5,  # Reduce size
                reasons=['HTF_MISALIGNED', f'HTF_BIAS:{htf_bias}'],
                htf_aligned=False,
            )
        
        # All clear - good entry
        return SmartEntryResult(
            decision=EntryDecision.ENTER_NOW,
            original_action=action,
            size_multiplier=1.0,
            reasons=['CLEAR_ENTRY'],
            htf_aligned=True,
        )
    
    def _analyze_hunting_zone(
        self,
        symbol: str,
        action: str,
        side: str,
        current_price: float,
        move: MoveTracker,
        htf_bias: int,
        features: Dict[str, Any]
    ) -> SmartEntryResult:
        """Analyze entry within an active hunting zone."""
        
        entry_direction = 'LONG' if 'LONG' in action.upper() or side == 'BUY' else 'SHORT'
        
        # Check if price has retraced
        retracement_hit, retracement_level = move.check_retracement(current_price)
        
        if retracement_hit:
            move.retracement_hit = True
            move.retracement_level = retracement_level
            self.stats['retracements_hit'] += 1
            
            # Determine entry logic based on move direction and HTF
            if move.direction == 'UP':
                # Move was UP, retracement means price pulled back
                # Good for LONG if HTF is bullish (continuation)
                # Good for SHORT if HTF is bearish (reversal)
                
                if htf_bias > 0 and entry_direction == 'LONG':
                    # Perfect setup: pullback in uptrend, entering long
                    self.stats['entries_on_retracement'] += 1
                    return SmartEntryResult(
                        decision=EntryDecision.ENTER_ON_RETRACEMENT,
                        original_action=action,
                        size_multiplier=1.2,  # Increased size for high-probability setup
                        entry_price_target=move.retracement_target_50,
                        reasons=[
                            'PULLBACK_ENTRY',
                            f'RETRACEMENT:{retracement_level*100:.1f}%',
                            'HTF_CONFIRMS_CONTINUATION',
                        ],
                        move_tracker=move,
                        htf_aligned=True,
                        continuation_probability=0.7,
                    )
                elif htf_bias < 0 and entry_direction == 'SHORT':
                    # Counter-trade: uptrend exhausted, entering short
                    self.stats['counter_entries'] += 1
                    return SmartEntryResult(
                        decision=EntryDecision.COUNTER_ENTRY,
                        original_action=action,
                        size_multiplier=0.8,  # Slightly reduced for counter
                        entry_price_target=move.retracement_target_38,
                        reasons=[
                            'COUNTER_ENTRY',
                            f'RETRACEMENT:{retracement_level*100:.1f}%',
                            'HTF_SUGGESTS_REVERSAL',
                        ],
                        move_tracker=move,
                        htf_aligned=True,
                        continuation_probability=0.4,
                    )
            else:
                # Move was DOWN, retracement means price bounced
                # Good for SHORT if HTF is bearish (continuation)
                # Good for LONG if HTF is bullish (reversal)
                
                if htf_bias < 0 and entry_direction == 'SHORT':
                    # Perfect setup: bounce in downtrend, entering short
                    self.stats['entries_on_retracement'] += 1
                    return SmartEntryResult(
                        decision=EntryDecision.ENTER_ON_RETRACEMENT,
                        original_action=action,
                        size_multiplier=1.2,
                        entry_price_target=move.retracement_target_50,
                        reasons=[
                            'BOUNCE_ENTRY',
                            f'RETRACEMENT:{retracement_level*100:.1f}%',
                            'HTF_CONFIRMS_CONTINUATION',
                        ],
                        move_tracker=move,
                        htf_aligned=True,
                        continuation_probability=0.7,
                    )
                elif htf_bias > 0 and entry_direction == 'LONG':
                    # Counter-trade: downtrend exhausted, entering long
                    self.stats['counter_entries'] += 1
                    return SmartEntryResult(
                        decision=EntryDecision.COUNTER_ENTRY,
                        original_action=action,
                        size_multiplier=0.8,
                        entry_price_target=move.retracement_target_38,
                        reasons=[
                            'COUNTER_ENTRY',
                            f'RETRACEMENT:{retracement_level*100:.1f}%',
                            'HTF_SUGGESTS_REVERSAL',
                        ],
                        move_tracker=move,
                        htf_aligned=True,
                        continuation_probability=0.4,
                    )
        
        # Not yet at retracement - wait
        age_sec = (int(time.time() * 1000) - move.detected_ts) / 1000
        
        return SmartEntryResult(
            decision=EntryDecision.WAIT_FOR_PULLBACK,
            original_action=action,
            delay_seconds=min(60, int(SMART_ENTRY_HUNTING_ZONE_TTL - age_sec)),
            size_multiplier=0.0,  # Don't enter yet
            entry_price_target=move.retracement_target_50,
            reasons=[
                f'HUNTING_ZONE_ACTIVE:{move.direction}',
                f'WAIT_FOR_RETRACEMENT_TO:{move.retracement_target_50:.4f}',
                f'ZONE_AGE:{age_sec:.0f}s',
            ],
            move_tracker=move,
        )
    
    def _detect_fast_move(
        self,
        symbol: str,
        features: Dict[str, Any],
        current_price: float
    ) -> Optional[Dict[str, Any]]:
        """Detect if a fast move just occurred."""
        
        # Method 1: Use depth_fast_move features
        fast_move_score = float(features.get('depth_fast_move_score', 0))
        fast_move_1m = float(features.get('depth_fast_move_1m', 0))
        fast_move_5m = float(features.get('depth_fast_move_5m', 0))
        
        # Method 2: Calculate from ROC
        roc_10 = float(features.get('ind_ta_ROC_10_5m', 0))
        
        # Method 3: Use price history
        if symbol in self.price_history and len(self.price_history[symbol]) > 10:
            history = self.price_history[symbol]
            oldest_price = history[0][1]
            price_change_pct = (current_price - oldest_price) / oldest_price * 100
        else:
            price_change_pct = 0
        
        # Combine signals
        velocity = max(fast_move_score, fast_move_1m, abs(roc_10), abs(price_change_pct))
        
        if velocity >= SMART_ENTRY_VELOCITY_THRESHOLD:
            # Determine direction
            if roc_10 > 0 or price_change_pct > 0:
                direction = 'UP'
            else:
                direction = 'DOWN'
            
            # Get move start/peak from history
            if symbol in self.price_history and len(self.price_history[symbol]) > 5:
                prices = [p[1] for p in self.price_history[symbol]]
                if direction == 'UP':
                    start_price = min(prices)
                    peak_price = max(prices)
                else:
                    start_price = max(prices)
                    peak_price = min(prices)
            else:
                start_price = current_price * (1 - velocity/100)
                peak_price = current_price
            
            return {
                'direction': direction,
                'magnitude': velocity,
                'start_price': start_price,
                'peak_price': peak_price,
                'fast_move_score': fast_move_score,
                'roc': roc_10,
            }
        
        return None

    def _get_msnap(self, symbol: str) -> Dict[str, Any]:
        """Best-effort microstructure snapshot from Redis (CoinAPI WSDS)."""
        try:
            d = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}") or {}
        except Exception:
            d = {}
        # decode responses may already be str; tolerate bytes too.
        out: Dict[str, Any] = {}
        for k, v in (d or {}).items():
            try:
                ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                vs = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                out[ks] = vs
            except Exception:
                continue
        return out

    def _short_term_return_pct(self, symbol: str, horizon_s: int = 15) -> float:
        """Compute short-term return over last ~horizon seconds from internal price history."""
        try:
            now_ms = int(time.time() * 1000)
            hist = list(self.price_history.get(symbol) or [])
            if len(hist) < 3:
                return 0.0
            cutoff = now_ms - int(max(5, horizon_s) * 1000)
            recent = [p for (ts, p) in hist if ts >= cutoff and p and p > 0]
            if len(recent) < 2:
                return 0.0
            p0 = float(recent[0])
            p1 = float(recent[-1])
            if p0 <= 0:
                return 0.0
            return (p1 - p0) / p0 * 100.0
        except Exception:
            return 0.0

    def _reversal_fastpath_signal(self, *, symbol: str, current_price: float, features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Detect a likely reversal using microstructure + short-term return.
        This is intentionally *not* ML; it is an execution-time guardrail to prevent being late at reversals.
        Returns dict with: direction (LONG/SHORT), score (0..1) or None.
        """
        ms = self._get_msnap(symbol)
        def _f(x, default=0.0):
            try:
                return float(x)
            except Exception:
                return float(default)
        imb = _f(ms.get("imbalance_5", 0.0), 0.0)
        spoof = _f(ms.get("spoof_score", 0.0), 0.0)
        churn = _f(ms.get("churn_score", 0.0), 0.0)
        fast = _f(ms.get("fast_move_score", 0.0), 0.0)
        fast_max = _f(ms.get("fast_move_max_1m", 0.0), 0.0)
        # Short-term return (captures snapback even when snapback_score is absent/zero)
        r15 = self._short_term_return_pct(symbol, horizon_s=15)

        # Depth-vs-Tape divergence from unified_features (spoof detection upgrade)
        dvt_div = 0.0
        tape_imb_5s = 0.0
        try:
            if self.redis:
                _uf_key = f"unified_features:{symbol}:5m"
                dvt_div = _f(self.redis.hget(_uf_key, "depth_vs_tape_divergence"), 0.0)
                tape_imb_5s = _f(self.redis.hget(_uf_key, "tape_imbalance_5s"), 0.0)
        except Exception:
            pass

        # Normalize inputs
        imb01 = max(0.0, min(1.0, abs(imb)))
        spoof01 = max(0.0, min(1.0, spoof))
        churn01 = max(0.0, min(1.0, churn))
        fast01 = max(0.0, min(1.0, max(fast, fast_max)))

        # Reversal heuristics:
        # - require a snapback impulse (r15) plus either imbalance magnitude or spoof/churn stress
        # - direction from sign(r15) with confirmation from imbalance sign when available
        if abs(r15) < 0.08:  # <8 bps over 15s => ignore (noise)
            return None

        dir_from_r = "LONG" if r15 > 0 else "SHORT"
        # Confirmation: if imbalance sign contradicts return sign strongly, treat as absorption (still reversal).
        # If imbalance agrees, even better.
        agree = 1.0
        try:
            if imb != 0:
                agree = 1.0 if (imb > 0 and r15 > 0) or (imb < 0 and r15 < 0) else 0.7
        except Exception:
            agree = 1.0

        # Score: emphasize snapback impulse + stress (spoof/churn/fast-move)
        r01 = max(0.0, min(1.0, abs(r15) / 0.60))  # 0.6% in 15s saturates
        stress = max(spoof01, churn01, fast01)
        # Depth-vs-Tape divergence boosts stress (confirmed manipulation)
        dvt01 = max(0.0, min(1.0, dvt_div))
        combined_stress = max(stress, dvt01) if dvt01 > 0.3 else stress
        score = (0.55 * r01) + (0.25 * combined_stress) + (0.20 * imb01)
        score = max(0.0, min(1.0, score * agree))

        return {
            "direction": dir_from_r,
            "score": float(score),
            "imbalance_5": float(imb),
            "spoof_score": float(spoof),
            "churn_score": float(churn),
            "fast_move": float(fast01),
            "r15_pct": float(r15),
            "depth_vs_tape_divergence": float(dvt_div),
            "tape_imbalance_5s": float(tape_imb_5s),
            "confidence": float(0.4 + 0.5 * score),
        }
    
    def _create_hunting_zone(
        self,
        symbol: str,
        fast_move: Dict[str, Any],
        current_price: float
    ):
        """Create a hunting zone for retracement entry."""
        
        move = MoveTracker(
            symbol=symbol,
            direction=fast_move['direction'],
            move_start_price=fast_move['start_price'],
            move_peak_price=fast_move['peak_price'],
            move_magnitude_pct=fast_move['magnitude'],
            detected_ts=int(time.time() * 1000),
        )
        
        move.calculate_retracement_levels()
        
        self.active_moves[symbol] = move
        
        # Persist to Redis
        try:
            redis_key = f"smart_entry:hunting_zone:{symbol}"
            self.redis.setex(
                redis_key,
                SMART_ENTRY_HUNTING_ZONE_TTL,
                json.dumps(move.to_dict())
            )
        except Exception as e:
            logger.warning(f"[SmartEntry] Error persisting hunting zone: {e}")
        
        logger.info(
            f"[SmartEntry] Created hunting zone for {symbol}: "
            f"dir={fast_move['direction']} mag={fast_move['magnitude']:.2f}% "
            f"targets: 38%={move.retracement_target_38:.4f} "
            f"50%={move.retracement_target_50:.4f} "
            f"61%={move.retracement_target_61:.4f}"
        )
    
    def _get_htf_bias(self, symbol: str) -> int:
        """Get higher timeframe bias (-1 bearish, 0 neutral, 1 bullish)."""
        def _bias_from_pred(pred: dict) -> int:
            if not pred:
                return 0
            action = ""
            for k in ("action", "direction"):
                raw = pred.get(k, b"") if pred else b""
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                raw = str(raw).upper()
                if raw:
                    action = raw
                    break
            if any(t in action for t in ("LONG", "BUY", "INCREASE_LONG")):
                return 1
            if any(t in action for t in ("SHORT", "SELL", "INCREASE_SHORT")):
                return -1
            return 0

        try:
            pred_1h = self.redis.hgetall(f"prediction:{symbol}:1h")
            pred_4h = self.redis.hgetall(f"prediction:{symbol}:4h")
            
            bias_1h = _bias_from_pred(pred_1h)
            bias_4h = _bias_from_pred(pred_4h)
            
            if bias_1h == bias_4h:
                return bias_1h
            
            return bias_4h if bias_4h != 0 else bias_1h
            
        except Exception:
            pass
        
        # Fallback: calculate from features
        try:
            uf_1h = self.redis.hgetall(f"unified_features:{symbol}:1h")
            if uf_1h:
                rsi = float(uf_1h.get('ind_ta_RSI_14_1h', 50))
                macd = float(uf_1h.get('ind_ta_MACD_macd_fastperiod12_slowperiod26_signalperiod9_1h', 0))
                
                if rsi > 55 and macd > 0:
                    return 1  # Bullish
                elif rsi < 45 and macd < 0:
                    return -1  # Bearish
        except Exception:
            pass
        
        return 0  # Neutral
    
    def _check_htf_alignment(self, entry_direction: str, htf_bias: int) -> bool:
        """Check if entry direction aligns with HTF bias."""
        if htf_bias == 0:
            return True  # Neutral allows any direction
        
        if entry_direction == 'LONG' and htf_bias > 0:
            return True
        if entry_direction == 'SHORT' and htf_bias < 0:
            return True
        
        return False
    
    def _is_entry_action(self, action: str) -> bool:
        """Check if action is an entry type."""
        entry_keywords = ['OPEN', 'LONG', 'SHORT', 'ADD', 'INCREASE']
        action_upper = action.upper()
        
        # Skip close/reduce actions
        if any(k in action_upper for k in ['CLOSE', 'REDUCE', 'EXIT', 'TP', 'SL', 'HEDGE']):
            return False
        
        return any(k in action_upper for k in entry_keywords)
    
    def _get_features(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Get features from Redis."""
        try:
            return self.redis.hgetall(f"unified_features:{symbol}:{timeframe}") or {}
        except Exception:
            return {}
    
    def _update_price_history(self, symbol: str, price: float):
        """Update price history for velocity calculation."""
        now_ms = int(time.time() * 1000)
        
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        
        self.price_history[symbol].append((now_ms, price))
        
        # Trim old entries
        cutoff = now_ms - (self.max_history_points * 1000)
        self.price_history[symbol] = [
            (ts, p) for ts, p in self.price_history[symbol]
            if ts > cutoff
        ]
    
    def _in_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in cooldown."""
        if symbol not in self.cooldowns:
            return False
        
        now_ms = int(time.time() * 1000)
        if now_ms >= self.cooldowns[symbol]:
            del self.cooldowns[symbol]
            return False
        
        return True
    
    def _set_cooldown(self, symbol: str, seconds: int):
        """Set cooldown for a symbol."""
        expiry_ms = int(time.time() * 1000) + (seconds * 1000)
        self.cooldowns[symbol] = expiry_ms
    
    def get_hunting_zones(self) -> Dict[str, Dict]:
        """Get all active hunting zones."""
        return {
            symbol: move.to_dict()
            for symbol, move in self.active_moves.items()
        }
    
    def get_stats(self) -> Dict[str, int]:
        """Get gate statistics."""
        return self.stats.copy()
    
    def clear_hunting_zone(self, symbol: str):
        """Manually clear a hunting zone."""
        if symbol in self.active_moves:
            del self.active_moves[symbol]
        
        try:
            self.redis.delete(f"smart_entry:hunting_zone:{symbol}")
        except Exception:
            pass


# Singleton instance
_smart_entry_gate: Optional[SmartEntryGate] = None


def get_smart_entry_gate() -> SmartEntryGate:
    """Get or create the singleton SmartEntryGate instance."""
    global _smart_entry_gate
    if _smart_entry_gate is None:
        _smart_entry_gate = SmartEntryGate()
    return _smart_entry_gate


# Test code
if __name__ == "__main__":
    import os
    os.chdir("/home/wali/Desktop/AI BOT")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    gate = SmartEntryGate()
    
    # Test with current prices
    test_cases = [
        ("BTCUSDT", "OPEN_LONG", "BUY", 90500.0),
        ("ETHUSDT", "OPEN_SHORT", "SELL", 3090.0),
        ("WIFUSDT", "OPEN_LONG", "BUY", 0.378),
    ]
    
    for symbol, action, side, price in test_cases:
        result = gate.analyze_entry(symbol, action, side, price)
        print(f"\n{symbol} {action}:")
        print(f"  Decision: {result.decision.value}")
        print(f"  Size Multiplier: {result.size_multiplier}")
        print(f"  Reasons: {result.reasons}")
        if result.entry_price_target:
            print(f"  Target: {result.entry_price_target}")
