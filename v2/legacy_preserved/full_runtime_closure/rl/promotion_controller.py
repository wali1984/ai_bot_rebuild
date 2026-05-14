"""
Promotion Controller for CoinAPI + Microstructure Stack

Manages staged rollout from OBSERVE to LIVE with:
- Health latches for automatic demotion
- Canary targeting for gradual exposure
- Budget enforcement to prevent quota exhaustion

Promotion Levels:
- LEVEL 0: CoinAPI ingest only (no router, no overlay)
- LEVEL 1: Router + canonicalization ON; overlay OBSERVE (log-only)
- LEVEL 2: Overlay gating ON but "size_reduce only" (no hard blocks)
- LEVEL 3: Overlay gating ON with hard blocks for entries on severe spoof/fast-move
"""

import os
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# EST timezone
EST = timezone(timedelta(hours=-5))


class PromotionLevel(Enum):
    """Promotion levels for staged rollout."""
    LEVEL_0_INGEST_ONLY = 0
    LEVEL_1_ROUTER_OBSERVE = 1
    LEVEL_2_GATING_SIZE_REDUCE = 2
    LEVEL_3_GATING_BLOCK = 3


class OverlayMode(Enum):
    """Overlay operating modes."""
    OFF = "off"
    OBSERVE = "observe"
    GATING_SIZE_REDUCE = "gating_size_reduce"
    GATING_BLOCK = "gating_block"


@dataclass
class HealthStatus:
    """Health status for promotion eligibility."""
    eligible: bool = False
    reasons: List[str] = field(default_factory=list)
    ws_connected: bool = False
    ws_connected_sec: float = 0.0
    ws_staleness_p50_ms: float = 0.0
    ws_staleness_p95_ms: float = 0.0
    msnap_completeness: float = 0.0
    rest_daily_used: int = 0
    ws_bytes_today_gb: float = 0.0
    demoted: bool = False
    demotion_reason: str = ""


@dataclass
class PromotionConfig:
    """Configuration for promotion controller."""
    level: int = 0
    canary_mode: bool = False
    canary_max_symbols: int = 8
    canary_include_open_positions: bool = True
    min_ws_connected_sec: int = 120
    max_ws_p50_staleness_ms: int = 700
    max_ws_p95_staleness_ms: int = 1500
    # Relaxed thresholds for OPEN_RISK during low activity (advisory mode)
    max_ws_p50_staleness_ms_relaxed: int = 60000  # 60s for low activity
    max_ws_p95_staleness_ms_relaxed: int = 90000  # 90s for low activity
    min_msnap_completeness: float = 0.85
    max_rest_daily_used: int = 80000
    max_ws_bytes_today_gb: float = 450.0
    ws_bytes_hard_cap_gb: float = 500.0
    canary_rotation_interval_sec: int = 1800  # 30 minutes


class PromotionController:
    """
    Controls staged promotion of CoinAPI + microstructure stack.
    
    Enforces prerequisites before enabling LIVE gating.
    Supports CANARY mode for gradual rollout.
    Auto-demotes to OBSERVE if health degrades or budgets exceeded.
    """
    
    def __init__(
        self,
        redis_client=None,
        config: Optional[PromotionConfig] = None,
        position_manager=None,
        active_symbols: Optional[List[str]] = None,
    ):
        self.redis = redis_client
        self.config = config or PromotionConfig()
        self.position_manager = position_manager
        self.active_symbols = active_symbols or []
        
        # State
        self._ws_connected_since: Optional[float] = None
        self._last_health_check: float = 0
        self._last_health_log: float = 0
        self._health_status: HealthStatus = HealthStatus()
        self._demoted: bool = False
        self._demotion_reason: str = ""
        self._canary_symbols: Set[str] = set()
        self._last_canary_rotation: float = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Status snapshot emission tracking
        self._last_status_snapshot: float = 0
        self._status_snapshot_interval: float = 60.0  # Emit every 60 seconds
        
        # Background thread for periodic snapshot emission
        self._snapshot_thread: Optional[threading.Thread] = None
        self._snapshot_thread_stop: threading.Event = threading.Event()
        self._start_snapshot_thread()
        
        logger.info(
            f"PromotionController initialized | level={self.config.level} | "
            f"canary_mode={self.config.canary_mode} | max_symbols={self.config.canary_max_symbols}"
        )
    
    def _start_snapshot_thread(self):
        """Start background thread for periodic snapshot emission."""
        if self.redis is None:
            logger.debug("[PROMOTION] No Redis client - snapshot thread not started")
            return
        
        def snapshot_loop():
            logger.info("[PROMOTION] Snapshot thread started - emitting every 60s")
            while not self._snapshot_thread_stop.wait(timeout=60.0):
                try:
                    with self._lock:
                        self._update_canary_symbols()
                        status = self._check_health()
                except Exception as e:
                    logger.warning(f"[PROMOTION] Snapshot thread error: {e}")
            logger.info("[PROMOTION] Snapshot thread stopped")
        
        self._snapshot_thread = threading.Thread(
            target=snapshot_loop,
            name="PromotionSnapshotThread",
            daemon=True,
        )
        self._snapshot_thread.start()
    
    def stop_snapshot_thread(self):
        """Stop the background snapshot thread."""
        if self._snapshot_thread and self._snapshot_thread.is_alive():
            self._snapshot_thread_stop.set()
            self._snapshot_thread.join(timeout=5.0)
    
    @classmethod
    def from_env(cls, redis_client=None, position_manager=None, active_symbols=None):
        """Create controller from environment variables."""
        config = PromotionConfig(
            level=int(os.getenv('PROMOTION_LEVEL', '0')),
            canary_mode=os.getenv('PROMOTION_CANARY_MODE', 'true').lower() in ('true', '1', 'yes'),
            canary_max_symbols=int(os.getenv('PROMOTION_CANARY_MAX_SYMBOLS', '8')),
            canary_include_open_positions=os.getenv('PROMOTION_CANARY_INCLUDE_OPEN_POSITIONS', 'true').lower() in ('true', '1', 'yes'),
            min_ws_connected_sec=int(os.getenv('PROMOTION_MIN_WS_CONNECTED_SEC', '120')),
            max_ws_p50_staleness_ms=int(os.getenv('PROMOTION_MAX_WS_P50_STALENESS_MS', '700')),
            max_ws_p95_staleness_ms=int(os.getenv('PROMOTION_MAX_WS_P95_STALENESS_MS', '1500')),
            max_ws_p50_staleness_ms_relaxed=int(os.getenv('PROMOTION_MAX_WS_P50_STALENESS_MS_RELAXED', '60000')),
            max_ws_p95_staleness_ms_relaxed=int(os.getenv('PROMOTION_MAX_WS_P95_STALENESS_MS_RELAXED', '90000')),
            min_msnap_completeness=float(os.getenv('PROMOTION_MIN_MSNAP_COMPLETENESS', '0.85')),
            max_rest_daily_used=int(os.getenv('PROMOTION_MAX_REST_DAILY_USED', '80000')),
            max_ws_bytes_today_gb=float(os.getenv('PROMOTION_MAX_WS_BYTES_TODAY_GB', '450')),
            ws_bytes_hard_cap_gb=float(os.getenv('PROMOTION_WS_BYTES_HARD_CAP_GB', '500')),
            canary_rotation_interval_sec=int(os.getenv('PROMOTION_CANARY_ROTATION_SEC', '1800')),
        )
        return cls(
            redis_client=redis_client,
            config=config,
            position_manager=position_manager,
            active_symbols=active_symbols,
        )
    
    def update_active_symbols(self, symbols: List[str]):
        """Update the list of active symbols."""
        with self._lock:
            self.active_symbols = symbols
    
    def _get_open_position_symbols(self) -> Set[str]:
        """Get symbols with open positions."""
        if self.position_manager is None:
            return set()
        
        try:
            positions = getattr(self.position_manager, 'get_positions', lambda: {})()
            if isinstance(positions, dict):
                return {sym for sym, pos in positions.items() if pos.get('qty', 0) != 0}
            return set()
        except Exception:
            return set()
    
    def _read_ws_metrics(self) -> Tuple[bool, float, float, float, float]:
        """
        Read WebSocket metrics from Redis.
        Returns: (connected, connected_sec, p50_staleness, p95_staleness, bytes_gb)
        """
        if self.redis is None:
            return False, 0.0, 9999.0, 9999.0, 0.0
        
        try:
            now = time.time()
            
            # Check WS connected state - use explicit connected flag and last_msg_ts
            ws_connected_flag = self.redis.get('metrics:coinapi:ws:connected')
            is_connected_flag = (ws_connected_flag.decode('utf-8') if isinstance(ws_connected_flag, bytes) else str(ws_connected_flag or '')) == '1'
            
            # Get connection timestamp for uptime calculation
            connected_ts = self.redis.get('metrics:coinapi:ws:last_connected_ts')
            if connected_ts:
                connected_ts = float(connected_ts)
                if self._ws_connected_since is None:
                    self._ws_connected_since = connected_ts
                connected_sec = now - connected_ts
            else:
                connected_sec = 0.0
            
            # Check if WS is actually sending data - look at last_msg_ts
            last_msg_ts = self.redis.get('metrics:coinapi:ws:last_msg_ts')
            last_msg_age_sec = 9999.0
            if last_msg_ts:
                last_msg_age_sec = now - float(last_msg_ts)
            
            msg_count = int(self.redis.get('metrics:coinapi:ws:msgs_today') or 0)
            # Consider connected if: explicit flag is set AND we've received messages recently (within 30s)
            connected = is_connected_flag and msg_count > 0 and last_msg_age_sec < 30
            
            # Staleness metrics
            p50_metric = float(self.redis.get('metrics:coinapi:ws:staleness_p50_ms') or 0)
            p95_metric = float(self.redis.get('metrics:coinapi:ws:staleness_p95_ms') or 0)

            # IMPORTANT: Prefer msnap-based staleness for the symbols we actually care about
            # (canary symbols / active symbols). Global percentiles can be skewed by idle symbols.
            p50_msnap, p95_msnap = self._compute_staleness_from_msnap()
            if p50_msnap < 9999.0 and p95_msnap < 9999.0:
                p50, p95 = p50_msnap, p95_msnap
            else:
                p50, p95 = p50_metric, p95_metric
            
            # Bytes usage
            bytes_today = float(self.redis.get('metrics:coinapi:ws:bytes_today') or 0)
            bytes_gb = bytes_today / (1024 ** 3)
            
            return connected, connected_sec, p50, p95, bytes_gb
            
        except Exception as e:
            logger.debug(f"[PROMOTION] Error reading WS metrics: {e}")
            return False, 0.0, 9999.0, 9999.0, 0.0
    
    def _compute_staleness_from_msnap(self) -> Tuple[float, float]:
        """Compute p50/p95 staleness from msnap keys."""
        if self.redis is None:
            return 9999.0, 9999.0
        
        try:
            now_ms = int(time.time() * 1000)
            staleness_values = []
            
            # Check canary symbols or first N active symbols
            symbols_to_check = list(self._canary_symbols) if self._canary_symbols else self.active_symbols[:10]
            if not symbols_to_check:
                # Fallback to config TRAINING_SYMBOLS
                try:
                    from config import TRAINING_SYMBOLS as TRADE_SYMBOLS
                    symbols_to_check = TRADE_SYMBOLS[:10]
                except ImportError:
                    symbols_to_check = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LTCUSDT']
            
            for symbol in symbols_to_check:
                key = f"msnap:coinapi_wsds:{symbol}"
                ts = self.redis.hget(key, 'updated_ts_ms')
                if ts:
                    staleness = now_ms - int(ts)
                    if staleness >= 0:  # Only count valid staleness
                        staleness_values.append(staleness)
            
            if not staleness_values:
                return 9999.0, 9999.0
            
            staleness_values.sort()
            n = len(staleness_values)
            p50 = staleness_values[n // 2]
            p95_idx = min(int(n * 0.95), n - 1)
            p95 = staleness_values[p95_idx]
            
            return float(p50), float(p95)
            
        except Exception:
            return 9999.0, 9999.0
    
    def _read_rest_metrics(self) -> int:
        """Read REST API daily usage."""
        if self.redis is None:
            return 0
        
        try:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            used = self.redis.get(f'metrics:coinapi:rest:daily_used:{today}')
            return int(used) if used else 0
        except Exception:
            return 0
    
    def _compute_msnap_completeness(self) -> float:
        """Compute msnap data completeness for canary symbols."""
        if self.redis is None:
            return 0.0
        
        try:
            # Use canary symbols, active symbols, or fallback to TRADE_SYMBOLS from config
            symbols_to_check = list(self._canary_symbols) if self._canary_symbols else self.active_symbols[:10]
            if not symbols_to_check:
                # Fallback to config TRAINING_SYMBOLS
                try:
                    from config import TRAINING_SYMBOLS as TRADE_SYMBOLS
                    symbols_to_check = TRADE_SYMBOLS[:10]
                except ImportError:
                    symbols_to_check = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'LTCUSDT']
            if not symbols_to_check:
                return 0.0
            
            required_fields = ['updated_ts_ms', 'mid_px', 'best_bid_px', 'best_ask_px']
            now_ms = int(time.time() * 1000)
            complete_count = 0
            
            for symbol in symbols_to_check:
                key = f"msnap:coinapi_wsds:{symbol}"
                data = self.redis.hgetall(key)
                if not data:
                    continue
                
                # Check freshness (within 30 seconds - relaxed for CoinAPI spot data)
                ts = int(data.get(b'updated_ts_ms', data.get('updated_ts_ms', 0)) or 0)
                if now_ms - ts > 30000:
                    continue
                
                # Check required fields
                has_all = all(
                    data.get(f.encode(), data.get(f)) 
                    for f in required_fields
                )
                if has_all:
                    complete_count += 1
            
            return complete_count / len(symbols_to_check)
            
        except Exception:
            return 0.0
    
    def _update_canary_symbols(self):
        """Update canary symbol selection (at most every rotation interval)."""
        now = time.time()
        if now - self._last_canary_rotation < self.config.canary_rotation_interval_sec:
            return  # Don't rotate yet
        
        self._last_canary_rotation = now
        
        # Start with open positions (highest priority)
        new_canary: Set[str] = set()
        
        if self.config.canary_include_open_positions:
            new_canary.update(self._get_open_position_symbols())
        
        # Add from active symbols until we reach max
        remaining_slots = self.config.canary_max_symbols - len(new_canary)
        if remaining_slots > 0 and self.active_symbols:
            for sym in self.active_symbols:
                if sym not in new_canary:
                    new_canary.add(sym)
                    remaining_slots -= 1
                    if remaining_slots <= 0:
                        break
        
        if new_canary != self._canary_symbols:
            self._canary_symbols = new_canary
            logger.info(f"[PROMOTION] Canary symbols updated: {sorted(new_canary)}")
    
    def _check_health(self) -> HealthStatus:
        """Check system health for promotion eligibility."""
        now = time.time()
        
        # Don't check too frequently
        if now - self._last_health_check < 5:
            return self._health_status
        
        self._last_health_check = now
        
        # Read metrics
        ws_connected, ws_connected_sec, ws_p50, ws_p95, ws_bytes_gb = self._read_ws_metrics()
        rest_daily_used = self._read_rest_metrics()
        msnap_completeness = self._compute_msnap_completeness()
        
        # Build health status
        status = HealthStatus(
            eligible=True,
            reasons=[],
            ws_connected=ws_connected,
            ws_connected_sec=ws_connected_sec,
            ws_staleness_p50_ms=ws_p50,
            ws_staleness_p95_ms=ws_p95,
            msnap_completeness=msnap_completeness,
            rest_daily_used=rest_daily_used,
            ws_bytes_today_gb=ws_bytes_gb,
        )
        
        # Check prerequisites
        if not ws_connected:
            status.eligible = False
            status.reasons.append("ws_disconnected")
        
        if ws_connected_sec < self.config.min_ws_connected_sec:
            status.eligible = False
            status.reasons.append(f"ws_connected_too_short:{ws_connected_sec:.0f}s<{self.config.min_ws_connected_sec}s")
        
        if ws_p50 > self.config.max_ws_p50_staleness_ms:
            status.eligible = False
            status.reasons.append(f"ws_p50_stale:{ws_p50:.0f}ms>{self.config.max_ws_p50_staleness_ms}ms")
        
        if ws_p95 > self.config.max_ws_p95_staleness_ms:
            status.eligible = False
            status.reasons.append(f"ws_p95_stale:{ws_p95:.0f}ms>{self.config.max_ws_p95_staleness_ms}ms")
        
        if msnap_completeness < self.config.min_msnap_completeness:
            status.eligible = False
            status.reasons.append(f"msnap_incomplete:{msnap_completeness:.1%}<{self.config.min_msnap_completeness:.1%}")
        
        # Budget checks (trigger demotion, not just eligibility)
        if rest_daily_used >= self.config.max_rest_daily_used:
            status.eligible = False
            status.demoted = True
            status.demotion_reason = f"rest_budget_exceeded:{rest_daily_used}>={self.config.max_rest_daily_used}"
            status.reasons.append(status.demotion_reason)
        
        if ws_bytes_gb >= self.config.ws_bytes_hard_cap_gb:
            status.eligible = False
            status.demoted = True
            status.demotion_reason = f"ws_bytes_hard_cap:{ws_bytes_gb:.1f}GB>={self.config.ws_bytes_hard_cap_gb}GB"
            status.reasons.append(status.demotion_reason)
        
        # Soft cap warning
        if ws_bytes_gb >= self.config.max_ws_bytes_today_gb:
            status.reasons.append(f"ws_bytes_soft_cap_warning:{ws_bytes_gb:.1f}GB")
        
        self._health_status = status
        
        # Log health periodically
        if now - self._last_health_log >= 60:
            self._last_health_log = now
            canary_str = ','.join(sorted(self._canary_symbols)[:5])
            if len(self._canary_symbols) > 5:
                canary_str += f"...+{len(self._canary_symbols)-5}"
            
            logger.info(
                f"PROMOTION_HEALTH | level={self.config.level} | "
                f"eligible={status.eligible} | "
                f"ws_connected={status.ws_connected} | "
                f"p50={status.ws_staleness_p50_ms:.0f}ms | "
                f"p95={status.ws_staleness_p95_ms:.0f}ms | "
                f"completeness={status.msnap_completeness:.1%} | "
                f"rest_used={status.rest_daily_used} | "
                f"ws_gb={status.ws_bytes_today_gb:.2f} | "
                f"canary=[{canary_str}] | "
                f"reasons={status.reasons if status.reasons else 'none'}"
            )
        
        # Emit status snapshot to Redis hash
        self._emit_status_snapshot(status)
        
        return status
    
    def _emit_status_snapshot(self, status: HealthStatus):
        """
        Emit PROMOTION_STATUS snapshot to Redis hash for monitoring/dashboards.
        
        Key: promotion:status
        Fields: level, eligible, reasons, canary_symbols, ws_p95_staleness_ms, 
                rest_used_today, ws_bytes_today
        """
        now = time.time()
        
        # Only emit every 60 seconds
        if now - self._last_status_snapshot < self._status_snapshot_interval:
            return
        
        self._last_status_snapshot = now
        
        if self.redis is None:
            return
        
        try:
            import json
            
            # Build snapshot data
            canary_list = sorted(self._canary_symbols)
            snapshot = {
                'level': str(self.config.level),
                'eligible': '1' if status.eligible else '0',
                'reasons': json.dumps(status.reasons) if status.reasons else '[]',
                'canary_symbols': json.dumps(canary_list),
                'ws_p95_staleness_ms': f'{status.ws_staleness_p95_ms:.0f}',
                'rest_used_today': str(status.rest_daily_used),
                'ws_bytes_today': f'{status.ws_bytes_today_gb * 1024**3:.0f}',  # Store in bytes
                'updated_ts': str(int(now * 1000)),  # epoch ms for freshness check
            }
            
            # Write to Redis hash
            self.redis.hset('promotion:status', mapping=snapshot)
            
            logger.debug(
                f"[PROMOTION] Status snapshot emitted | level={self.config.level} | "
                f"eligible={status.eligible} | p95={status.ws_staleness_p95_ms:.0f}ms"
            )
            
        except Exception as e:
            logger.warning(f"[PROMOTION] Failed to emit status snapshot: {e}")
    
    def should_enable_router(self) -> bool:
        """
        Determine if the ingestor quality router should be enabled.
        Returns True if PROMOTION_LEVEL >= 1 and health prerequisites pass.
        """
        if self.config.level < 1:
            return False
        
        with self._lock:
            self._update_canary_symbols()
            status = self._check_health()
            
            if not status.eligible:
                # Demoted - log once
                if not self._demoted:
                    self._demoted = True
                    self._demotion_reason = ', '.join(status.reasons)
                    logger.warning(
                        f"PROMOTION_DEMOTE | router disabled | "
                        f"level={self.config.level} | reasons={self._demotion_reason}"
                    )
                return False
            
            # Re-promoted
            if self._demoted:
                self._demoted = False
                logger.info(f"PROMOTION_RESTORE | router enabled | level={self.config.level}")
            
            return True
    
    def overlay_mode(self) -> OverlayMode:
        """
        Determine the overlay operating mode based on level and health.
        """
        level = self.config.level
        
        if level < 1:
            return OverlayMode.OFF
        
        with self._lock:
            self._update_canary_symbols()
            status = self._check_health()
            
            # If health fails, demote to observe
            if not status.eligible:
                if not self._demoted:
                    self._demoted = True
                    self._demotion_reason = ', '.join(status.reasons)
                    logger.warning(
                        f"PROMOTION_DEMOTE | overlay->observe | "
                        f"level={level} | reasons={self._demotion_reason}"
                    )
                return OverlayMode.OBSERVE
            
            # Restore if was demoted
            if self._demoted:
                self._demoted = False
                logger.info(f"PROMOTION_RESTORE | overlay mode restored | level={level}")
            
            # Map level to mode
            if level == 1:
                return OverlayMode.OBSERVE
            elif level == 2:
                return OverlayMode.GATING_SIZE_REDUCE
            elif level >= 3:
                return OverlayMode.GATING_BLOCK
            
            return OverlayMode.OBSERVE
    
    def apply_to_symbol(self, symbol: str) -> bool:
        """
        Determine if gating should apply to this symbol.
        In canary mode, only applies to canary symbols.
        """
        # Level 0: never apply
        if self.config.level < 2:
            return False
        
        # If canary mode disabled, apply to all
        if not self.config.canary_mode:
            return True
        
        with self._lock:
            self._update_canary_symbols()
            
            # Always include open positions
            if self.config.canary_include_open_positions:
                if symbol in self._get_open_position_symbols():
                    return True
            
            return symbol in self._canary_symbols
    
    def get_canary_symbols(self) -> Set[str]:
        """Get current canary symbol set."""
        with self._lock:
            self._update_canary_symbols()
            return self._canary_symbols.copy()
    
    def health_status(self) -> Dict:
        """Get current health status as dict."""
        with self._lock:
            status = self._check_health()
            return {
                'level': self.config.level,
                'eligible': status.eligible,
                'demoted': self._demoted,
                'demotion_reason': self._demotion_reason,
                'ws_connected': status.ws_connected,
                'ws_connected_sec': status.ws_connected_sec,
                'ws_staleness_p50_ms': status.ws_staleness_p50_ms,
                'ws_staleness_p95_ms': status.ws_staleness_p95_ms,
                'msnap_completeness': status.msnap_completeness,
                'rest_daily_used': status.rest_daily_used,
                'ws_bytes_today_gb': status.ws_bytes_today_gb,
                'canary_symbols': sorted(self._canary_symbols),
                'reasons': status.reasons,
            }
    
    def should_shed_subscriptions(self) -> bool:
        """Check if we should reduce WS subscriptions due to bandwidth."""
        with self._lock:
            status = self._check_health()
            return status.ws_bytes_today_gb >= self.config.max_ws_bytes_today_gb
    
    def should_restrict_rest_fallback(self) -> bool:
        """Check if REST fallback should be restricted to positions only."""
        with self._lock:
            status = self._check_health()
            # Restrict when nearing budget or WS is unhealthy
            return (
                status.rest_daily_used >= self.config.max_rest_daily_used * 0.8 or
                not status.ws_connected
            )
    
    def get_rest_allowed_symbols(self) -> Set[str]:
        """Get symbols allowed for REST fallback when restricted."""
        with self._lock:
            allowed = self._get_open_position_symbols()
            # Also allow canary symbols if budget permits
            status = self._check_health()
            if status.rest_daily_used < self.config.max_rest_daily_used * 0.5:
                allowed.update(self._canary_symbols)
            return allowed
    
    def is_protective_action(self, action) -> bool:
        """Check if action is protective (never blocked)."""
        protective_actions = {
            'CLOSE_LONG', 'CLOSE_SHORT', 'CLOSE',
            'DECREASE_LONG', 'DECREASE_SHORT', 'DECREASE',
            'PARTIAL_CLOSE_LONG', 'PARTIAL_CLOSE_SHORT', 'PARTIAL_CLOSE',
            'STOP_LOSS', 'TAKE_PROFIT',
            'UNWIND_HEDGE', 'SCALE_HEDGE',  # Overlay protective actions
        }
        # Handle int action indices (from model) - treat as non-protective
        if isinstance(action, (int, float)):
            return False
        if not action:
            return False
        return str(action).upper() in protective_actions
    
    def effective_runner_hedge_execute(self, symbol: str) -> bool:
        """
        Determine if runner/hedge overlay can execute for this symbol.
        
        Returns True if:
        - PROMOTION_LEVEL >= 2 and health OK
        - Symbol is in canary set (if canary mode enabled)
        - DYNAMIC_RUNNER_HEDGE_CANARY_ONLY respected
        
        Used by trainer/trader to gate overlay execution.
        """
        from config import (
            ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE,
            DYNAMIC_RUNNER_HEDGE_CANARY_ONLY,
        )
        
        # Master switch
        if not ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE:
            return False
        
        # Level < 2 means observe-only (no gating)
        if self.config.level < 2:
            return False
        
        with self._lock:
            self._update_canary_symbols()
            status = self._check_health()
            
            # Health must be OK
            if not status.eligible:
                return False
            
            # If canary mode enabled, check if symbol in canary
            if DYNAMIC_RUNNER_HEDGE_CANARY_ONLY:
                return symbol in self._canary_symbols
            
            # Level 3 with canary disabled = all symbols
            return True
    
    def log_effective_flags(self):
        """Log effective overlay/runner flags for telemetry."""
        from config import (
            ENABLE_DYNAMIC_RUNNER_HEDGE,
            ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE,
            DYNAMIC_RUNNER_HEDGE_CANARY_ONLY,
            DYNAMIC_HEDGE_ALLOW_OPEN,
        )
        
        with self._lock:
            self._update_canary_symbols()
            canary_str = ','.join(sorted(self._canary_symbols)[:5])
            if len(self._canary_symbols) > 5:
                canary_str += f"...+{len(self._canary_symbols)-5}"
            
            logger.info(
                f"PROMOTION_EFFECTIVE | level={self.config.level} | "
                f"runner_hedge={ENABLE_DYNAMIC_RUNNER_HEDGE} | "
                f"runner_hedge_execute={ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE} | "
                f"canary_only={DYNAMIC_RUNNER_HEDGE_CANARY_ONLY} | "
                f"hedge_allow_open={DYNAMIC_HEDGE_ALLOW_OPEN} | "
                f"canary_size={len(self._canary_symbols)} | "
                f"canary=[{canary_str}]"
            )
    
    @property
    def microstructure_healthy(self) -> bool:
        """
        Compute microstructure health for fail-closed OPEN_RISK decisions.
        
        Returns True if:
        - eligible AND 
        - ws_connected (inferred from explicit metrics OR msnap staleness) AND
        - msnap_completeness >= threshold AND
        - staleness within bounds
        
        Logs detailed health reasons for debugging.
        """
        with self._lock:
            status = self._check_health()
            
            # Build detailed reasons list for logging
            reasons = []
            
            # Check eligibility
            if not status.eligible:
                reasons.extend(status.reasons)
            
            # Check WebSocket connection with robust inference
            ws_healthy = status.ws_connected
            if not ws_healthy:
                # Try inference from msnap if explicit WS metrics missing
                if self.redis:
                    try:
                        # Check if we have recent msnap updates for canary symbols
                        now_ms = int(time.time() * 1000)
                        recent_msnap_count = 0
                        
                        symbols_to_check = list(self._canary_symbols) if self._canary_symbols else self.active_symbols[:5]
                        if not symbols_to_check:
                            try:
                                from config import TRAINING_SYMBOLS as TRADE_SYMBOLS
                                symbols_to_check = TRADE_SYMBOLS[:5]
                            except ImportError:
                                symbols_to_check = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
                        
                        for symbol in symbols_to_check:
                            key = f"msnap:coinapi_wsds:{symbol}"
                            ts = self.redis.hget(key, 'updated_ts_ms')
                            if ts:
                                staleness_ms = now_ms - int(ts)
                                if staleness_ms < 30000:  # Recent update within 30s
                                    recent_msnap_count += 1
                        
                        # If most symbols have recent msnap, consider WS healthy
                        if recent_msnap_count >= max(1, len(symbols_to_check) // 2):
                            ws_healthy = True
                            reasons.append("ws_inferred_from_msnap")
                        else:
                            reasons.append(f"ws_disconnected_inferred_msnap_stale:{recent_msnap_count}/{len(symbols_to_check)}")
                    except Exception as e:
                        reasons.append(f"ws_inference_failed:{e}")
                        logger.debug(f"[PROMOTION] WS inference error: {e}")
                else:
                    reasons.append("ws_disconnected_no_redis")
            else:
                reasons.append("ws_connected_explicit")
            
            # Check msnap completeness
            msnap_ok = status.msnap_completeness >= self.config.min_msnap_completeness
            if not msnap_ok:
                reasons.append(f"msnap_incomplete:{status.msnap_completeness:.1%}<{self.config.min_msnap_completeness:.1%}")
            else:
                reasons.append(f"msnap_complete:{status.msnap_completeness:.1%}")
            
            # Check staleness bounds
            staleness_ok = (
                status.ws_staleness_p50_ms <= self.config.max_ws_p50_staleness_ms and
                status.ws_staleness_p95_ms <= self.config.max_ws_p95_staleness_ms
            )
            if not staleness_ok:
                reasons.append(f"staleness_high:p50={status.ws_staleness_p50_ms:.0f},p95={status.ws_staleness_p95_ms:.0f}")
            else:
                reasons.append(f"staleness_ok:p50={status.ws_staleness_p50_ms:.0f},p95={status.ws_staleness_p95_ms:.0f}")
            
            # Final health determination
            is_healthy = status.eligible and ws_healthy and msnap_ok and staleness_ok
            
            # Log detailed health status
            logger.info(
                f"MICROSTRUCTURE_HEALTH | "
                f"eligible={status.eligible} | "
                f"ws_connected={ws_healthy} | "
                f"completeness={status.msnap_completeness:.1%} | "
                f"p50={status.ws_staleness_p50_ms:.0f}ms | "
                f"p95={status.ws_staleness_p95_ms:.0f}ms | "
                f"healthy={is_healthy} | "
                f"reasons={','.join(reasons)}"
            )
            
            return is_healthy
    
    def microstructure_healthy_for_open_risk(self) -> tuple[bool, str, dict]:
        """
        Check microstructure health for OPEN_RISK with relaxed thresholds.
        Returns (is_healthy, source, details) where source is 'coinapi_wsds' or 'binance_fallback'.
        
        Tiered approach:
        1. If WSDS meets strict thresholds -> use CoinAPI (preferred)
        2. If WSDS stale but within relaxed thresholds -> advisory mode (use CoinAPI with warning)
        3. If WSDS exceeds relaxed thresholds -> fallback to Binance bookticker
        """
        with self._lock:
            status = self._check_health()
            
            # Tier 1: Strict thresholds met - use CoinAPI (optimal)
            if (status.eligible and 
                status.ws_staleness_p50_ms <= self.config.max_ws_p50_staleness_ms and
                status.ws_staleness_p95_ms <= self.config.max_ws_p95_staleness_ms):
                return (True, 'coinapi_wsds', {
                    'p50_ms': status.ws_staleness_p50_ms,
                    'p95_ms': status.ws_staleness_p95_ms,
                    'completeness': status.msnap_completeness,
                    'tier': 'optimal'
                })
            
            # Tier 2: Relaxed thresholds - advisory mode (low activity, CoinAPI still usable)
            if (status.ws_connected and
                status.ws_staleness_p50_ms <= self.config.max_ws_p50_staleness_ms_relaxed and
                status.ws_staleness_p95_ms <= self.config.max_ws_p95_staleness_ms_relaxed):
                return (True, 'coinapi_wsds', {
                    'p50_ms': status.ws_staleness_p50_ms,
                    'p95_ms': status.ws_staleness_p95_ms,
                    'completeness': status.msnap_completeness,
                    'tier': 'relaxed_low_activity',
                    'warning': f'WSDS stale but within relaxed bounds (p50={status.ws_staleness_p50_ms:.0f}ms)'
                })
            
            # Tier 3: Fallback to Binance bookticker
            return (True, 'binance_fallback', {
                'p50_ms': status.ws_staleness_p50_ms,
                'p95_ms': status.ws_staleness_p95_ms,
                'tier': 'binance_fallback',
                'reason': f'WSDS too stale (p50={status.ws_staleness_p50_ms:.0f}ms > {self.config.max_ws_p50_staleness_ms_relaxed}ms)'
            })


# Module-level singleton for easy access
_controller: Optional[PromotionController] = None


def get_promotion_controller(
    redis_client=None,
    position_manager=None,
    active_symbols=None,
    force_new=False,
) -> PromotionController:
    """Get or create the promotion controller singleton."""
    global _controller
    
    if _controller is None or force_new:
        _controller = PromotionController.from_env(
            redis_client=redis_client,
            position_manager=position_manager,
            active_symbols=active_symbols,
        )
    elif redis_client and _controller.redis is None:
        _controller.redis = redis_client
    
    if active_symbols:
        _controller.update_active_symbols(active_symbols)
    
    return _controller

