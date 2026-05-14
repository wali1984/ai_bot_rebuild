"""
Base Executor - Shared Trading Logic
Pure execution components without decision-making logic

This module contains all shared functionality for live trading executors:
- Order validation and execution
- Position tracking and management
- Balance monitoring
- Redis communication
- Error handling and rate limiting
- Exchange API wrappers

Decision-making logic (market analysis, signals, strategies) belongs in hybrid_trainer.py
"""

import os
import sys
import time
import json
import logging
import redis
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from collections import defaultdict, deque
import numpy as np
from decimal import Decimal, ROUND_DOWN, ROUND_UP

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_live_config
from utils.binance_rate_limiter import (
    BinanceRateLimiter,
    RedisBinanceRateLimiter,
    is_banned,
    set_ban,
    maybe_clear_ban,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Binance imports
try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    Client = None
    BinanceAPIException = Exception
    BinanceOrderException = Exception

# Telegram imports
try:
    from telegram_alerts import TelegramNotifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    TelegramNotifier = None


class OfflineBinanceClient:
    """Lightweight stub to allow offline/demo operation when Binance is unreachable."""

    def __init__(self):
        self._order_counter = 0

    def futures_account(self):
        return {
            "totalWalletBalance": "1000",
            "availableBalance": "1000",
            "totalUnrealizedProfit": "0",
            "totalMarginBalance": "1000",
            "totalPositionInitialMargin": "0",
            "totalOpenOrderInitialMargin": "0",
            "maxWithdrawAmount": "1000",
            "canTrade": False,
            "canDeposit": False,
            "canWithdraw": False,
        }

    def futures_change_position_mode(self, **kwargs):
        return {"dualSidePosition": True}

    def futures_change_margin_type(self, **kwargs):
        return {}

    def futures_change_leverage(self, **kwargs):
        return {}

    def futures_position_information(self, symbol: Optional[str] = None):
        return []

    def futures_symbol_ticker(self, symbol: str):
        return {"symbol": symbol, "price": "0"}

    def futures_create_order(self, **kwargs):
        self._order_counter += 1
        quantity = kwargs.get("quantity", 0)
        price = kwargs.get("price", 0)
        return {
            "orderId": self._order_counter,
            "executedQty": quantity,
            "avgPrice": price,
        }

    def futures_get_open_orders(self, symbol: Optional[str] = None):
        return []

    def futures_exchange_info(self):
        return {"symbols": [], "rateLimits": []}


# ── Order Fill Reconciliation ──────────────────────────────────────────────
# Binance MARKET order acks often return avgPrice="0", executedQty="0",
# status="NEW" because the fill settles milliseconds later.  This helper
# polls futures_get_order() until a real fill appears or the deadline expires.

def reconcile_order_fill(client, symbol: str, order: dict,
                         max_sec: float = 2.0, interval: float = 0.25) -> dict:
    """
    Poll Binance for fill data when an order ack has executedQty == 0.

    Parameters
    ----------
    client   : Binance Client (must have futures_get_order)
    symbol   : Trading pair e.g. "BTCUSDT"
    order    : Raw order dict from futures_create_order
    max_sec  : Max seconds to keep polling (default 2.0)
    interval : Sleep between polls (default 0.25s)

    Returns
    -------
    Updated order dict with fill fields from Binance (or original if timeout).
    """
    try:
        import config as _cfg
        if not getattr(_cfg, "ORDER_FILL_RECONCILE_ENABLED", True):
            return order
        max_sec = float(getattr(_cfg, "ORDER_FILL_POLL_MAX_SEC", max_sec))
        interval = float(getattr(_cfg, "ORDER_FILL_POLL_INTERVAL_SEC", interval))
    except Exception:
        pass

    if not isinstance(order, dict):
        return order

    order_id = order.get("orderId")
    if not order_id:
        return order

    # Only reconcile when qty is zero/missing (unfilled ack)
    try:
        exec_qty = float(order.get("executedQty") or 0)
    except (ValueError, TypeError):
        exec_qty = 0.0

    if exec_qty > 0:
        return order  # Already filled — nothing to reconcile

    deadline = time.time() + max_sec
    poll_count = 0
    last_status = None

    while time.time() < deadline:
        time.sleep(interval)
        poll_count += 1
        try:
            refreshed = client.futures_get_order(symbol=symbol, orderId=order_id)
            if not isinstance(refreshed, dict):
                continue

            last_status = refreshed.get("status", "")
            r_qty = float(refreshed.get("executedQty") or 0)
            r_price = float(refreshed.get("avgPrice") or 0)

            if r_qty > 0 and r_price > 0:
                # Merge fill data back into original order dict
                order["executedQty"] = refreshed["executedQty"]
                order["avgPrice"] = refreshed["avgPrice"]
                order["status"] = refreshed.get("status", order.get("status", ""))
                order["cumQuote"] = refreshed.get("cumQuote", order.get("cumQuote", "0"))
                order["updateTime"] = refreshed.get("updateTime", order.get("updateTime"))
                order["_fill_reconciled"] = True
                order["_fill_poll_count"] = poll_count
                logger.info(
                    "ORDER_FILL_RECONCILED | symbol=%s | orderId=%s | "
                    "avgPrice=%s | executedQty=%s | polls=%d | elapsed=%.2fs",
                    symbol, order_id, refreshed["avgPrice"],
                    refreshed["executedQty"], poll_count,
                    max_sec - (deadline - time.time()),
                )
                return order

            # If terminal status with qty=0, stop early (e.g. CANCELED, REJECTED, EXPIRED)
            if last_status in ("CANCELED", "EXPIRED", "REJECTED"):
                logger.warning(
                    "ORDER_FILL_RECONCILE_TERMINAL | symbol=%s | orderId=%s | "
                    "status=%s | polls=%d",
                    symbol, order_id, last_status, poll_count,
                )
                order["_fill_reconciled"] = False
                order["_fill_terminal_status"] = last_status
                order["_fill_poll_count"] = poll_count
                return order

        except Exception as e:
            logger.debug(
                "ORDER_FILL_RECONCILE_POLL_ERR | symbol=%s | orderId=%s | err=%s",
                symbol, order_id, e,
            )

    # Timeout — return original with annotation
    logger.warning(
        "ORDER_FILL_RECONCILE_TIMEOUT | symbol=%s | orderId=%s | "
        "polls=%d | max_sec=%.1f | last_status=%s",
        symbol, order_id, poll_count, max_sec, last_status,
    )
    order["_fill_reconciled"] = False
    order["_fill_poll_count"] = poll_count
    return order


class CircuitBreaker:
    """
    Circuit Breaker for Trading Safety
    Automatically halts trading on excessive losses to prevent catastrophic drawdowns
    
    ENHANCED: Now persists starting balance in Redis to survive restarts
    ENHANCED: Uses equity (with unrealized PnL) instead of wallet balance
    ENHANCED: Can be disabled via CIRCUIT_BREAKER_ENABLED config flag
    """

    # Redis keys for persistence
    REDIS_KEY_PREFIX = "wma:circuit_breaker"
    
    def __init__(self, daily_loss_threshold: float = 0.20, redis_client=None, telegram_notifier=None, account_id: str = "primary"):
        """
        Initialize circuit breaker
        
        Args:
            daily_loss_threshold: Maximum allowed daily loss as fraction (0.20 = 20%)
            redis_client: Redis client for persistence
            telegram_notifier: Telegram notifier for alerts
            account_id: Account identifier for Redis key isolation
        """
        self.daily_loss_threshold = daily_loss_threshold
        self.redis = redis_client
        self.telegram = telegram_notifier
        self.account_id = account_id
        
        # Check if circuit breaker is enabled
        try:
            import config
            self.enabled = getattr(config, 'CIRCUIT_BREAKER_ENABLED', True)
        except Exception:
            self.enabled = True
        
        # Auto-recovery cooldown (seconds) before re-enabling trading
        try:
            self.auto_reset_seconds = int(os.getenv("CIRCUIT_BREAKER_AUTO_RESET_SECONDS", "60"))
        except Exception:
            self.auto_reset_seconds = 60
        
        # Track daily P&L
        self.daily_start_balance = None
        self.current_balance = None
        self.daily_reset_time = None
        
        # Circuit breaker state
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time = None
        
        # Recovery tracking
        self.recovery_mode = False
        self.position_size_multiplier = 1.0
        
        # Position size reduction for caution mode (alias for recovery_mode for backwards compatibility)
        self.position_size_reduction = 1.0
        
        # Try to restore state from Redis on initialization
        if self.enabled:
            self._restore_from_redis()
            logger.info(f"🛡️ Circuit Breaker initialized: {daily_loss_threshold*100:.1f}% daily loss limit (account: {account_id})")
        else:
            logger.warning(f"⚠️ Circuit Breaker DISABLED via config (account: {account_id})")
    
    @property
    def caution_mode(self) -> bool:
        """Alias for recovery_mode for backwards compatibility"""
        return self.recovery_mode
    
    @property
    def starting_balance(self) -> Optional[float]:
        """Alias for daily_start_balance for backwards compatibility"""
        return self.daily_start_balance
    
    @property
    def max_loss_pct(self) -> float:
        """Alias for daily_loss_threshold for backwards compatibility"""
        return self.daily_loss_threshold
    
    def _get_redis_key(self, suffix: str) -> str:
        """Get Redis key with account-specific prefix"""
        return f"{self.REDIS_KEY_PREFIX}:{self.account_id}:{suffix}"
    
    def _restore_from_redis(self):
        """Restore circuit breaker state from Redis on startup"""
        if not self.redis:
            return
            
        try:
            # Get persisted starting balance for today
            key = self._get_redis_key("daily_start")
            data = self.redis.get(key)
            
            if data:
                stored = json.loads(data)
                stored_date = stored.get('date')
                today = datetime.utcnow().strftime('%Y-%m-%d')
                
                if stored_date == today:
                    # Same day - restore the original starting balance
                    self.daily_start_balance = stored.get('balance')
                    self.daily_reset_time = datetime.utcnow().date()
                    logger.info(f"🔄 Circuit Breaker: Restored starting balance ${self.daily_start_balance:.2f} from Redis (set at {stored.get('set_time', 'unknown')})")
                else:
                    # New day - will be set fresh
                    logger.info(f"📅 Circuit Breaker: New day detected, will set fresh starting balance")
            
            # Check if circuit breaker was tripped
            trip_key = self._get_redis_key("tripped")
            trip_data = self.redis.get(trip_key)
            if trip_data:
                trip_info = json.loads(trip_data)
                if trip_info.get('tripped'):
                    self.is_tripped = True
                    self.trip_reason = trip_info.get('reason', 'Restored from Redis')
                    logger.warning(f"⚠️ Circuit Breaker: Restored TRIPPED state from Redis - {self.trip_reason}")
                    
        except Exception as e:
            logger.warning(f"⚠️ Could not restore circuit breaker state from Redis: {e}")
    
    def _persist_to_redis(self):
        """Persist circuit breaker state to Redis"""
        if not self.redis:
            return
            
        try:
            # Persist starting balance with date
            key = self._get_redis_key("daily_start")
            data = {
                'balance': self.daily_start_balance,
                'date': datetime.utcnow().strftime('%Y-%m-%d'),
                'set_time': datetime.utcnow().strftime('%H:%M:%S'),
                'account_id': self.account_id
            }
            # Expire at end of day (24 hours max)
            self.redis.setex(key, 86400, json.dumps(data))
            
        except Exception as e:
            logger.warning(f"⚠️ Could not persist circuit breaker state to Redis: {e}")
    
    def set_starting_balance(self, balance: float, force_new: bool = False):
        """
        Set the starting balance for the day.
        
        ENHANCED: Now checks Redis for existing starting balance to survive restarts.
        Only sets new balance if:
        1. No existing balance for today in Redis, OR
        2. force_new=True is passed, OR
        3. It's a new day (midnight UTC reset)
        
        Args:
            balance: Current balance from exchange
            force_new: Force setting new balance (ignore Redis)
        """
        current_date = datetime.utcnow().date()
        
        # Check if we already have a starting balance for today (from Redis restore)
        if self.daily_start_balance is not None and self.daily_reset_time == current_date and not force_new:
            if float(self.daily_start_balance) <= 0.0:
                if balance > 0:
                    logger.warning(
                        f"💰 Circuit Breaker: Starting balance was ${self.daily_start_balance:.2f} (invalid) — "
                        f"resetting to current equity ${balance:.2f}"
                    )
                    self.daily_start_balance = balance
                    self.current_balance = balance
                    self._persist_to_redis()
                else:
                    logger.warning(
                        f"💰 Circuit Breaker: Both starting balance (${self.daily_start_balance:.2f}) and "
                        f"current equity (${balance:.2f}) are zero — waiting for funding"
                    )
                    self.current_balance = balance
                return
            _loss_pct = ((balance - self.daily_start_balance) / self.daily_start_balance * 100) if self.daily_start_balance > 0 else 0.0
            logger.info(
                f"💰 Circuit Breaker: Keeping existing starting balance ${self.daily_start_balance:.2f} "
                f"(current: ${balance:.2f}, loss: {_loss_pct:+.2f}%)"
            )
            self.current_balance = balance
            return
        
        # Check if it's a new day
        if self.daily_reset_time is not None and self.daily_reset_time != current_date:
            logger.info(f"📅 Circuit Breaker: New day - resetting starting balance")
            # Reset tripped state for new day
            self.is_tripped = False
            self.trip_reason = None
            self.trip_time = None
        
        # Set new starting balance
        self.daily_start_balance = balance
        self.current_balance = balance
        self.daily_reset_time = current_date
        
        # Persist to Redis
        self._persist_to_redis()
        
        logger.info(f"💰 Circuit Breaker: Starting balance set to ${balance:.2f} (persisted to Redis)")
    
    def check_daily_loss(self, current_balance: float, starting_balance: Optional[float] = None) -> Tuple[bool, float]:
        """
        Check if daily loss limit exceeded
        
        Args:
            current_balance: Current account balance
            starting_balance: Starting balance for the day (optional)
        
        Returns:
            Tuple of (should_trip, daily_loss_pct)
        """
        # Reset daily tracking at midnight UTC
        current_date = datetime.utcnow().date()
        if self.daily_reset_time != current_date:
            self.daily_reset_time = current_date
            self.daily_start_balance = starting_balance or current_balance
            logger.info(f"📅 Daily tracking reset: Starting balance = ${self.daily_start_balance:.2f}")
        
        self.current_balance = current_balance
        
        if self.daily_start_balance is None or self.daily_start_balance == 0:
            self.daily_start_balance = current_balance
            return False, 0.0
        
        # Prevent division by zero
        if self.daily_start_balance == 0:
            logger.warning(f"⚠️ Starting balance is 0, cannot calculate daily loss percentage")
            return False, 0.0
        
        # ── FIX Apr 14 2026: Sanity guard for stale/incorrect starting balance ──
        # If daily_start_balance is > 2.5x current equity, it's likely a stale
        # placeholder ($10,000 default) rather than a real starting balance.
        # This caused permanent circuit breaker trips (-73%) on $2,683 accounts.
        if self.daily_start_balance > 2.5 * current_balance and current_balance > 100:
            logger.warning(
                f"⚠️ Circuit Breaker: Starting balance ${self.daily_start_balance:.2f} is >2.5x "
                f"current equity ${current_balance:.2f} — resetting to current equity "
                f"(stale/placeholder starting balance detected)"
            )
            self.daily_start_balance = current_balance
            self._persist_to_redis()
            return False, 0.0
        
        # Calculate daily loss
        daily_loss_pct = (current_balance - self.daily_start_balance) / self.daily_start_balance
        
        # Check if threshold exceeded
        if daily_loss_pct <= -self.daily_loss_threshold:
            return True, daily_loss_pct
        
        # Check for recovery mode adjustment
        # Use configurable threshold (default 15% if not set)
        try:
            import config as cfg
            caution_threshold = getattr(cfg, 'CIRCUIT_BREAKER_CAUTION_THRESHOLD', 0.15)
        except Exception:
            caution_threshold = 0.15
        
        if daily_loss_pct < -caution_threshold:  # e.g., more than 15% loss
            self.recovery_mode = True
            # Reduce position size based on loss severity
            loss_severity = abs(daily_loss_pct) / self.daily_loss_threshold
            self.position_size_multiplier = max(0.3, 1.0 - loss_severity * 0.5)
            self.position_size_reduction = self.position_size_multiplier  # Keep in sync
        else:
            self.recovery_mode = False
            self.position_size_multiplier = 1.0
            self.position_size_reduction = 1.0  # Keep in sync
        
        return False, daily_loss_pct
    
    def check(self, current_balance: float) -> bool:
        """
        Simple check method - returns True if trading should continue
        
        Args:
            current_balance: Current account balance
        
        Returns:
            True if trading should continue, False if circuit breaker tripped
        """
        # ========================================================================
        # CIRCUIT BREAKER DISABLED CHECK
        # ========================================================================
        if not self.enabled:
            return True  # Always allow trading when disabled
        
        # ========================================================================
        # SANITY CHECK: Reject obviously wrong balance values
        # ========================================================================
        if current_balance <= 0:
            logger.warning(f"⚠️ Circuit Breaker: Invalid balance ${current_balance:.2f}, skipping check")
            return True  # Don't trip on bad data
        
        # Check for unrealistic loss (>100% would mean negative balance which is impossible)
        if self.daily_start_balance and self.daily_start_balance > 0:
            loss_pct = (current_balance - self.daily_start_balance) / self.daily_start_balance
            if loss_pct < -1.0:  # More than 100% loss is impossible
                logger.warning(f"⚠️ Circuit Breaker: Impossible loss calculation ({loss_pct*100:.2f}%), "
                             f"balance=${current_balance:.2f}, start=${self.daily_start_balance:.2f} - skipping check")
                return True  # Don't trip on bad data
        
        if self.is_tripped:
            # DYNAMIC AUTO-RELEASE: Check if loss has recovered below threshold
            should_trip, daily_loss_pct = self.check_daily_loss(current_balance)
            
            # Calculate recovery threshold (5% safety margin below trip threshold)
            recovery_threshold = -(self.daily_loss_threshold - 0.05)  # e.g., -25% for 30% threshold
            
            # Auto-release if:
            # 1. Loss recovered above recovery threshold (dynamic), OR
            # 2. Time-based cooldown expired (backup)
            time_since_trip = (datetime.utcnow() - self.trip_time).total_seconds() if self.trip_time else 0
            
            if daily_loss_pct > recovery_threshold:
                # Loss recovered! Auto-release
                logger.info(f"🟢 Circuit Breaker DYNAMIC AUTO-RELEASE: Loss recovered to {daily_loss_pct*100:.2f}% "
                           f"(above {recovery_threshold*100:.2f}% threshold) (account: {self.account_id})")
                self.reset()
                return True
            elif time_since_trip >= self.auto_reset_seconds:
                # Time-based backup auto-release
                logger.info(f"🟢 Circuit Breaker TIME-BASED AUTO-RELEASE after {self.auto_reset_seconds}s cooldown "
                           f"(current loss: {daily_loss_pct*100:.2f}%) (account: {self.account_id})")
                self.reset()
                return True
            else:
                # Still tripped
                remaining_time = int(self.auto_reset_seconds - time_since_trip)
                logger.debug(f"🔴 Circuit Breaker still tripped: Loss={daily_loss_pct*100:.2f}%, "
                            f"Need recovery to {recovery_threshold*100:.2f}% or wait {remaining_time}s (account: {self.account_id})")
                return False
        
        should_trip, daily_loss_pct = self.check_daily_loss(current_balance)
        
        if should_trip:
            self.trip(f"Daily loss threshold exceeded: {daily_loss_pct*100:.2f}%")
            return False
        
        return True
    
    def trip(self, reason: str):
        """
        Trip the circuit breaker
        
        Args:
            reason: Reason for tripping
        """
        if self.is_tripped:
            return  # Already tripped
        
        self.is_tripped = True
        self.trip_reason = reason
        self.trip_time = datetime.utcnow()
        
        # Store in Redis
        if self.redis:
            status_key = self._get_redis_key("status")
            self.redis.setex(
                status_key,
                3600 * 24,  # 24 hour expiry
                json.dumps({
                    "tripped": True,
                    "reason": reason,
                    "trip_time": self.trip_time.isoformat(),
                    "daily_loss_pct": ((self.current_balance - self.daily_start_balance) / self.daily_start_balance) if self.daily_start_balance else 0
                })
            )
        
        # Send alert - handle both sync and async contexts
        if self.telegram:
            alert_msg = (
                f"🚨 CIRCUIT BREAKER TRIPPED 🚨\n\n"
                f"Reason: {reason}\n"
                f"Time: {self.trip_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"Daily Loss: {((self.current_balance - self.daily_start_balance) / self.daily_start_balance * 100):.2f}%\n\n"
                f"All trading has been HALTED.\n"
                f"Manual intervention required to resume."
            )
            try:
                # Try to get running loop
                loop = asyncio.get_running_loop()
                loop.create_task(self.telegram.send_system_alert(alert_msg, alert_type="CRITICAL"))
            except RuntimeError:
                # No running loop - create new one
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.telegram.send_system_alert(alert_msg, alert_type="CRITICAL"))
                    loop.close()
                except Exception as e:
                    logger.error(f"Failed to send circuit breaker alert: {e}")
        
        logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {reason}")
    
    def reset(self):
        """Reset circuit breaker (manual intervention required)"""
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time = None
        
        if self.redis:
            self.redis.delete(self._get_redis_key("status"))
        
        if self.telegram:
            reset_msg = (
                "✅ Circuit Breaker RESET\n\n"
                "Trading has been re-enabled.\n"
                "Monitoring will continue."
            )
            try:
                # Try to get running loop
                loop = asyncio.get_running_loop()
                loop.create_task(self.telegram.send_message(reset_msg))
            except RuntimeError:
                # No running loop - create new one
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.telegram.send_message(reset_msg))
                    loop.close()
                except Exception as e:
                    logger.error(f"Failed to send circuit breaker reset notification: {e}")
        
        logger.info("✅ Circuit breaker reset - trading re-enabled")
    
    def get_position_size_multiplier(self) -> float:
        """Get current position size multiplier based on recovery mode"""
        if self.is_tripped:
            return 0.0  # No trading allowed
        return self.position_size_multiplier
    
    def get_current_mode(self) -> str:
        """Get current circuit breaker mode"""
        if self.is_tripped:
            return "TRIPPED"
        elif self.recovery_mode:
            return "RECOVERY"
        else:
            return "NORMAL"


class BaseExecutor:
    """
    Base executor with shared trading logic (no decision making)
    
    This class handles pure execution tasks:
    - Order placement and tracking
    - Position synchronization
    - Balance monitoring
    - Redis reporting
    - Error handling
    
    Decision-making (what/when to trade) is done by hybrid_trainer.py
    """
    
    def __init__(self, account_id: str = "primary"):
        """
        Initialize base executor
        
        Args:
            account_id: Account identifier for multi-account support
        """
        self.account_id = account_id
        
        # Load configuration
        self.config = get_live_config()

        # Execution mode guard: dry-run is harness-only
        try:
            from utils.runtime_flags import get_flag_bool_env
            dry_run_exec = get_flag_bool_env(None, "DRY_RUN_EXECUTION", False)
            harness_flag = get_flag_bool_env(None, "FORCE_PATHS_HARNESS", False)
        except Exception:
            dry_run_exec = os.getenv("DRY_RUN_EXECUTION", "0").lower() in ("1", "true", "yes", "on")
            harness_flag = os.getenv("FORCE_PATHS_HARNESS", "0").lower() in ("1", "true", "yes", "on")

        exec_mode = "DRY_RUN" if dry_run_exec else "LIVE"
        exec_mode_line = f"EXECUTION_MODE | dry_run={1 if dry_run_exec else 0} | harness={1 if harness_flag else 0} | mode={exec_mode}"
        logger.info(exec_mode_line)
        try:
            log_dir = Path(__file__).resolve().parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "execution_mode.log", "a", encoding="utf-8") as f:
                f.write(exec_mode_line + "\n")
        except Exception:
            pass
        if dry_run_exec and not harness_flag:
            forbidden_line = "DRY_RUN_FORBIDDEN | reason=harness_flag_required | action=exit"
            logger.error(forbidden_line)
            try:
                log_dir = Path(__file__).resolve().parent.parent / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "execution_mode.log", "a", encoding="utf-8") as f:
                    f.write(forbidden_line + "\n")
            except Exception:
                pass
            raise SystemExit(1)

        # Execution attribution (disabled by default)
        self.execution_attribution_enabled = bool(getattr(self.config, "ENABLE_EXECUTION_ATTRIBUTION", False))
        self.execution_attribution_stream = getattr(self.config, "EXECUTION_ATTRIBUTION_STREAM", "trades:attribution")
        self.execution_attribution_summary_prefix = getattr(
            self.config,
            "EXECUTION_ATTRIBUTION_SUMMARY_PREFIX",
            "trades:attribution:summary",
        )
        
        # Initialize Redis
        self.redis = self._init_redis()
        
        # Initialize Telegram
        self.telegram = self._init_telegram()

        # Lightweight notifier hook (Telegram preferred, fallback to logger)
        # NOTE: TelegramNotifier.send_message is async; use sync-safe wrapper to avoid coroutine warnings.
        self._notifier = (lambda msg: self.telegram.send_message_sync(msg)) if self.telegram else (lambda msg: logger.warning(msg))
        
        # Initialize circuit breaker with account_id for Redis key isolation
        # UPDATED: 50% threshold since we have hedge protection now
        self.circuit_breaker = CircuitBreaker(
            daily_loss_threshold=0.50,
            redis_client=self.redis,
            telegram_notifier=self.telegram,
            account_id=self.account_id
        )
        
        # Position and balance tracking
        self.positions = {}  # symbol -> position_dict
        self.balance = 0.0
        self.unrealized_pnl = 0.0
        
        # Order tracking
        self.pending_orders = {}  # order_id -> order_dict
        self.filled_orders = deque(maxlen=1000)
        
        # Rate limiting
        self.last_api_call = 0
        self.api_call_count = 0
        self.api_call_window_start = time.time()
        self.max_api_calls_per_minute = int(os.getenv("BINANCE_API_MAX_CALLS_PER_MINUTE", "1200"))
        safe_max = int(os.getenv("BINANCE_API_SAFE_CALLS_PER_MINUTE", "300"))
        safe_burst = int(os.getenv("BINANCE_API_BURST", "30"))
        # IMPORTANT: Use the same limiter key across all Binance REST-using processes (ingestors + traders),
        # otherwise each process will think it has its own budget and the combined IP usage will get banned.
        limiter_key = os.getenv("BINANCE_LIMITER_KEY", "binance:limits:rest")
        try:
            # Shared limiter across processes (IP-level). If Redis unavailable, fallback to local limiter.
            self.api_rate_limiter = RedisBinanceRateLimiter(redis_key=limiter_key, max_per_minute=safe_max, burst=safe_burst)
        except Exception:
            self.api_rate_limiter = BinanceRateLimiter(max_per_minute=safe_max, burst=safe_burst)
        
        # Performance tracking
        self.trade_history = deque(maxlen=100)
        self.last_sync_time = 0
        
        logger.info(f"✅ BaseExecutor initialized: account_id={account_id}")

    def get_account_display_name(self) -> str:
        """
        Human-friendly account label used in alerts/logs.
        Defaults:
          - primary -> Wajid
          - asjad   -> Asjad
        Can be overridden via env:
          - TRADER_DISPLAY_NAME (global)
          - TRADER_DISPLAY_NAME_PRIMARY / TRADER_DISPLAY_NAME_ASJAD (per-account)
        """
        try:
            key_specific = f"TRADER_DISPLAY_NAME_{str(self.account_id).upper()}"
            override = (os.getenv(key_specific) or os.getenv("TRADER_DISPLAY_NAME") or "").strip()
            if override:
                return override
        except Exception:
            pass

        aid = str(self.account_id or "").strip().lower()
        if aid == "primary":
            return "Wajid"
        if aid == "asjad":
            return "Asjad"
        return str(self.account_id)

    def infer_leg_role(
        self,
        symbol: str,
        position_side: str,
        positions_by_side: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        """
        Infer whether a position leg is MAIN vs HEDGE for alerting/audit.

        Priority:
        1) Redis hedge marker `hedge:active:{SYMBOL}:{account_id}` if present
        2) Runtime `positions_by_side` sizing (smaller leg => hedge)

        Returns: "HEDGE" | "MAIN" | "" (unknown)
        """
        side = str(position_side or "").upper()
        if side not in ("LONG", "SHORT"):
            return ""

        # 1) Redis hedge marker
        try:
            if self.redis:
                key = f"hedge:active:{str(symbol).upper()}:{self.account_id}"
                raw = self.redis.get(key)
                if raw:
                    data = json.loads(raw)
                    hedge_side = str(
                        data.get("hedge_position_side")
                        or data.get("hedge_side")
                        or ""
                    ).upper()

                    # Some writers store hedge_side as BUY/SELL
                    if hedge_side in ("BUY", "SELL"):
                        hedge_side = "LONG" if hedge_side == "BUY" else "SHORT"

                    if hedge_side in ("LONG", "SHORT"):
                        return "HEDGE" if side == hedge_side else "MAIN"
        except Exception:
            pass

        # 2) Fallback: infer from current sizes (smaller leg => hedge)
        try:
            if positions_by_side and symbol in positions_by_side:
                sides = positions_by_side.get(symbol) or {}
                long_pos = sides.get("LONG")
                short_pos = sides.get("SHORT")
                if long_pos and short_pos:
                    long_size = float(long_pos.get("size", 0) or 0)
                    short_size = float(short_pos.get("size", 0) or 0)
                    if long_size > 0 and short_size > 0 and long_size != short_size:
                        hedge_side = "LONG" if long_size < short_size else "SHORT"
                        return "HEDGE" if side == hedge_side else "MAIN"
        except Exception:
            pass

        return ""
    
    def _init_redis(self) -> redis.Redis:
        """Initialize Redis connection"""
        try:
            redis_client = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True
            )
            redis_client.ping()
            logger.info("✅ Redis connected")
            # region agent log
            try:
                import json as _aj
                _ts = int(time.time() * 1000)
                _info = {}
                try:
                    _info = redis_client.info() or {}
                except Exception:
                    _info = {}
                _kw = {}
                try:
                    _kw = getattr(getattr(redis_client, "connection_pool", None), "connection_kwargs", {}) or {}
                except Exception:
                    _kw = {}
                _payload = {
                    "sessionId": "53deb7",
                    "id": f"log_{_ts}_trader_redis_identity_{getattr(self, 'account_id', 'na')}",
                    "timestamp": _ts,
                    "location": "trading/base_executor.py:_init_redis",
                    "message": "trader_redis_identity",
                    "runId": "post-fix",
                    "hypothesisId": "H4",
                    "data": {
                        "pid": int(os.getpid()),
                        "account_id": str(getattr(self, "account_id", "") or ""),
                        "redis_url_env_present": bool(os.getenv("REDIS_URL")),
                        "redis_host_conn": _kw.get("host"),
                        "redis_port_conn": _kw.get("port"),
                        "redis_db_conn": _kw.get("db"),
                        "redis_server_run_id": _info.get("run_id") if isinstance(_info, dict) else None,
                        "redis_server_tcp_port": _info.get("tcp_port") if isinstance(_info, dict) else None,
                        "redis_version": _info.get("redis_version") if isinstance(_info, dict) else None,
                    },
                }
                with open(
                    "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                    "a",
                    encoding="utf-8",
                ) as _f:
                    _f.write(_aj.dumps(_payload, separators=(",", ":")) + "\n")
            except Exception:
                pass
            # endregion
            return redis_client
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            raise
    
    def _init_telegram(self) -> Optional[TelegramNotifier]:
        """Initialize Telegram notifier with per-account trade channel support"""
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram alerts not available")
            return None
        
        try:
            # Per-account trade channel: TELEGRAM_TRADE_CHANNEL_PRIMARY or TELEGRAM_TRADE_CHANNEL_ASJAD
            account_key = str(self.account_id or "primary").upper()
            trade_channel = os.getenv(
                f"TELEGRAM_TRADE_CHANNEL_{account_key}",
                self.config.TRADE_CHANNEL_ID  # fallback to default
            )
            
            notifier = TelegramNotifier(
                bot_token=self.config.TELEGRAM_BOT_TOKEN,
                bot_chat_id=self.config.TELEGRAM_CHAT_ID,
                channel_id=self.config.PRIVATE_CHANNEL_ID,
                portfolio_channel_id=self.config.PORTFOLIO_CHANNEL_ID,
                trade_channel_id=trade_channel,
                ai_signals_channel_id=self.config.AI_SIGNALS_CHANNEL_ID,
                redis_client=self.redis
            )
            logger.info(f"✅ Telegram notifications enabled [{account_key}] trade_channel={trade_channel}")
            return notifier
        except Exception as e:
            logger.warning(f"Telegram initialization failed: {e}")
            return None
    
    def rate_limit_check(self, operation_type: str = "default") -> bool:
        """
        Check if we can make an API call within rate limits
        
        Args:
            operation_type: Type of operation (for tracking purposes, currently not used)
        
        Returns:
            True if call is allowed, False if we should wait
        """
        # Shared ban gate (auto-clears expired)
        try:
            maybe_clear_ban(self.redis, notifier=self._notifier)
            banned, remaining_ms = is_banned(self.redis, notifier=self._notifier)
            if banned:
                logger.warning(f"🚫 [GLOBAL BAN] Skipping REST call ({operation_type}); remaining ~{remaining_ms/1000:.0f}s")
                return False
        except Exception:
            pass

        try:
            delay = self.api_rate_limiter.maybe_sleep()
            if delay > 0:
                logger.debug(
                    f"⏳ Rate limit throttle ({operation_type}): slept {delay:.2f}s"
                )
        except Exception:
            # Fallback to legacy counter if limiter unavailable
            current_time = time.time()
            if current_time - self.api_call_window_start >= 60:
                self.api_call_count = 0
                self.api_call_window_start = current_time
            if self.api_call_count >= self.max_api_calls_per_minute:
                logger.warning(
                    f"⚠️ Rate limit reached ({operation_type}): {self.api_call_count}/{self.max_api_calls_per_minute} calls/min"
                )
                return False
            self.api_call_count += 1
            self.last_api_call = current_time
            return True

        self.last_api_call = time.time()
        return True

    def record_ban(self, until_ms: int, reason: str = ""):
        """Record a shared ban so all services pause REST."""
        try:
            set_ban(self.redis, until_ms, source=f"trader:{self.account_id}", reason=reason, notifier=self._notifier)
        except Exception:
            pass
    
    def validate_order_params(self, symbol: str, side: str, quantity: float, price: Optional[float] = None) -> Tuple[bool, str]:
        """
        Validate order parameters before submission
        
        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            quantity: Order quantity
            price: Order price (optional for market orders)
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check circuit breaker
        if self.circuit_breaker.is_tripped:
            return False, "Circuit breaker is tripped - trading halted"
        
        # Validate symbol
        if not symbol or not isinstance(symbol, str):
            return False, f"Invalid symbol: {symbol}"
        
        # Validate side
        if side not in ['BUY', 'SELL']:
            return False, f"Invalid side: {side} (must be BUY or SELL)"
        
        # Validate quantity
        if quantity <= 0:
            return False, f"Invalid quantity: {quantity} (must be positive)"
        
        # Validate price if provided
        if price is not None and price <= 0:
            return False, f"Invalid price: {price} (must be positive)"
        
        # Check balance (placeholder - override in subclass)
        # This should check if we have sufficient balance/margin
        
        return True, ""

    # ==================================================================================
    # MAKER-FIRST EXECUTION (shared helper)
    # ==================================================================================

    def _get_orderbook_top(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch best bid/ask from Redis (`orderbook:top:{symbol}`) if available."""
        if not getattr(self, "redis", None):
            return None
        try:
            raw = self.redis.get(f"orderbook:top:{symbol}")
            if not raw:
                return None
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            bid = float(data.get("bid") or 0.0)
            ask = float(data.get("ask") or 0.0)
            ts_ms = int(data.get("ts") or 0)
            if bid <= 0 or ask <= 0:
                return None
            return {"bid": bid, "ask": ask, "ts_ms": ts_ms, "raw": data}
        except Exception:
            return None

    def _get_symbol_info_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch symbol exchange info with a short in-process cache to avoid REST spam."""
        if not hasattr(self, "client") or self.client is None:
            return None
        ttl = int(os.getenv("EXCHANGE_INFO_CACHE_TTL_SEC", "300"))
        now = time.time()
        try:
            cache_ts = float(getattr(self, "_exchange_info_cache_ts", 0.0) or 0.0)
        except Exception:
            cache_ts = 0.0
        by_symbol = getattr(self, "_exchange_info_by_symbol", None)
        if isinstance(by_symbol, dict) and (now - cache_ts) < ttl and symbol in by_symbol:
            return by_symbol.get(symbol)
        try:
            info = self.client.futures_exchange_info()
            symbols = info.get("symbols", []) if isinstance(info, dict) else []
            by_symbol = {s.get("symbol"): s for s in symbols if isinstance(s, dict) and s.get("symbol")}
            self._exchange_info_by_symbol = by_symbol
            self._exchange_info_cache_ts = now
            return by_symbol.get(symbol)
        except Exception:
            return None

    @staticmethod
    def _extract_tick_size(symbol_info: Optional[Dict[str, Any]]) -> Tuple[float, int]:
        """Return (tick_size, price_precision)."""
        tick = 0.0
        price_precision = 8
        try:
            if symbol_info and "pricePrecision" in symbol_info:
                price_precision = int(symbol_info.get("pricePrecision") or price_precision)
            for f in (symbol_info or {}).get("filters", []) or []:
                if (f or {}).get("filterType") == "PRICE_FILTER":
                    tick = float(f.get("tickSize") or 0.0)
                    break
        except Exception:
            tick = 0.0
        if tick <= 0:
            # Best-effort fallback
            try:
                tick = float(10 ** (-int(price_precision)))
            except Exception:
                tick = 0.0
        return tick, price_precision

    @staticmethod
    def _quantize_price(price: float, tick_size: float, order_side: str, price_precision: int) -> float:
        """Quantize price to tick size; BUY rounds DOWN, SELL rounds UP to stay post-only."""
        if price <= 0:
            return 0.0
        if tick_size and tick_size > 0:
            try:
                p = Decimal(str(price))
                t = Decimal(str(tick_size))
                q = (p / t).to_integral_value(rounding=ROUND_DOWN if order_side == "BUY" else ROUND_UP)
                price = float(q * t)
            except Exception:
                # Fallback to float math
                steps = price / tick_size
                if order_side == "BUY":
                    steps = int(steps + 1e-9)
                else:
                    steps = int(steps + 0.999999999)
                price = steps * tick_size
        try:
            return float(round(price, int(price_precision)))
        except Exception:
            return float(price)

    def _compute_post_only_limit_price(
        self,
        symbol: str,
        order_side: str,
        current_price: float,
        maker_price_offset_bps: float,
        symbol_info: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Compute a maker (post-only) limit price using Redis orderbook if available.
        BUY: place at (ask - tick). SELL: place at (bid + tick).
        Falls back to current_price +/- offset when orderbook missing/stale.
        """
        symbol_info = symbol_info or self._get_symbol_info_cached(symbol)
        tick_size, price_precision = self._extract_tick_size(symbol_info)

        ob = self._get_orderbook_top(symbol)
        now_ms = int(time.time() * 1000)
        ob_stale_sec = int(os.getenv("MAKER_ORDERBOOK_STALE_SECONDS", "5"))
        if ob and ob.get("ts_ms") and (now_ms - int(ob["ts_ms"])) > (ob_stale_sec * 1000):
            ob = None

        bid = float(ob.get("bid")) if ob else 0.0
        ask = float(ob.get("ask")) if ob else 0.0

        # Primary: inside-spread post-only anchor
        if bid > 0 and ask > 0 and tick_size > 0:
            if order_side == "BUY":
                target = ask - tick_size
                # ensure strictly below ask when tick available
                if target <= 0:
                    target = bid
            else:
                target = bid + tick_size
                if target <= 0:
                    target = ask
        else:
            # Fallback: move away from current price
            offset = max(0.0, float(maker_price_offset_bps or 0.0)) / 10000.0
            if current_price <= 0:
                return 0.0
            target = current_price * (1 - offset) if order_side == "BUY" else current_price * (1 + offset)

        return self._quantize_price(float(target), tick_size, order_side, price_precision)

    def execute_maker_first_order(
        self,
        *,
        symbol: str,
        order_side: str,
        position_side: str,
        quantity: float,
        reduce_only: bool,
        action_label: str,
        allow_market_fallback: bool = True,
        # Per-call overrides (used by fastlane / urgent protective actions)
        maker_enabled_override: Optional[bool] = None,
        wait_total_override: Optional[int] = None,
        attempts_override: Optional[int] = None,
        price_offset_bps_override: Optional[float] = None,
        # Trainer target price: when set, use this as the limit price anchor
        # instead of the live orderbook / current price offset.  This places
        # maker orders at the model's predicted entry level.
        target_price: Optional[float] = None,
        # Execution hint: optional mode selector (e.g. "IOC", "MARKET_OR_IOC")
        execution_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Maker-first: place POST_ONLY LIMIT (GTX) and wait; retry with repricing; optional MARKET fallback.
        When target_price is provided (from trainer signal), the first attempt uses it
        exactly; subsequent reprices blend toward current market price.

        Returns:
            dict with keys:
              - ok: bool
              - order: dict (synthetic combined order-like payload) when ok
              - liquidity: MAKER|TAKER|MIXED
              - execution_path: string
              - error / skip_reason
        """
        if not hasattr(self, "client") or self.client is None:
            # Allow dry-run execution without a live client
            try:
                from utils.runtime_flags import get_flag_bool_env
                dry_run_exec = get_flag_bool_env(self.redis, "DRY_RUN_EXECUTION", False)
            except Exception:
                dry_run_exec = False
            if not dry_run_exec:
                return {"ok": False, "skip_reason": "no_binance_client"}
        if quantity <= 0:
            return {"ok": False, "skip_reason": "invalid_quantity"}

        # Read config (from config.py if available, env fallback)
        try:
            from config import (
                MAKER_FIRST_ENABLED,
                MAKER_WAIT_TIMEOUT_SECONDS,
                MAKER_PRICE_OFFSET_BPS,
                MAKER_REPRICE_ATTEMPTS,
                MAKER_REPRICE_ATTEMPTS_OPEN,
                MAKER_REPRICE_ATTEMPTS_REDUCE,
                MAKER_ALLOW_MARKET_FALLBACK,
                FAST_EXIT_IN_STRESS,
            )
            maker_enabled = bool(MAKER_FIRST_ENABLED)
            wait_total = int(MAKER_WAIT_TIMEOUT_SECONDS)
            price_offset_bps = float(MAKER_PRICE_OFFSET_BPS)
            attempts_default = int(MAKER_REPRICE_ATTEMPTS)
            attempts_open = int(MAKER_REPRICE_ATTEMPTS_OPEN)
            attempts_reduce = int(MAKER_REPRICE_ATTEMPTS_REDUCE)
            allow_market_fallback = bool(MAKER_ALLOW_MARKET_FALLBACK) and bool(allow_market_fallback)
            fast_exit_in_stress = bool(FAST_EXIT_IN_STRESS)
        except Exception:
            maker_enabled = os.getenv("MAKER_FIRST_ENABLED", "true").lower() in ("1", "true", "yes")
            wait_total = int(os.getenv("MAKER_WAIT_TIMEOUT_SECONDS", "30"))
            price_offset_bps = float(os.getenv("MAKER_PRICE_OFFSET_BPS", "1.0"))
            attempts_default = int(os.getenv("MAKER_REPRICE_ATTEMPTS", "3"))
            attempts_open = int(os.getenv("MAKER_REPRICE_ATTEMPTS_OPEN", "3"))
            attempts_reduce = int(os.getenv("MAKER_REPRICE_ATTEMPTS_REDUCE", "1"))
            allow_market_fallback = os.getenv("MAKER_ALLOW_MARKET_FALLBACK", "true").lower() in ("1", "true", "yes") and bool(allow_market_fallback)
            fast_exit_in_stress = os.getenv("FAST_EXIT_IN_STRESS", "true").lower() in ("1", "true", "yes")

        try:
            from utils.runtime_flags import get_flag_env
            forced_mode = str(get_flag_env(self.redis, "FORCE_PORTFOLIO_MODE", "") or "").upper()
        except Exception:
            forced_mode = str(os.getenv("FORCE_PORTFOLIO_MODE", "") or "").upper()

        mode_for_policy = forced_mode if forced_mode else "AGGRESSIVE"
        is_reduce = bool(reduce_only)
        attempts = attempts_reduce if is_reduce else attempts_open
        if attempts <= 0:
            attempts = attempts_default

        if is_reduce and fast_exit_in_stress and mode_for_policy in ("STRESS", "EMERGENCY"):
            maker_enabled = False

        policy = "fast_exit" if (is_reduce and fast_exit_in_stress and mode_for_policy in ("STRESS", "EMERGENCY")) else "maker_first"
        fallback_label = "taker" if allow_market_fallback else "none"
        logger.info(
            f"MAKER_POLICY_SELECT | action={action_label} | symbol={symbol} | reduce_only={1 if is_reduce else 0} | "
            f"policy={policy} | max_attempts={attempts} | fallback={fallback_label} | mode={mode_for_policy}"
        )

        # Apply per-call overrides (safe clamps below)
        try:
            if maker_enabled_override is not None:
                maker_enabled = bool(maker_enabled_override)
            if wait_total_override is not None:
                wait_total = int(wait_total_override)
            if attempts_override is not None:
                attempts = int(attempts_override)
            if price_offset_bps_override is not None:
                price_offset_bps = float(price_offset_bps_override)
        except Exception:
            pass

        # region agent log
        try:
            _symu = str(symbol or "").upper().strip()
            if _symu in ("BANKUSDT", "ASTERUSDT") and (bool(reduce_only) or bool(execution_mode) or maker_enabled_override is not None):
                import json as _aj
                _ts = int(time.time() * 1000)
                _payload = {
                    "sessionId": "868108",
                    "id": f"log_{_ts}_exec_policy_{_symu}_{str(action_label or '')[:24]}",
                    "timestamp": _ts,
                    "location": "trading/base_executor.py:execute_maker_first_order",
                    "message": "execution_policy_selected",
                    "runId": "pre-fix",
                    "hypothesisId": "H4",
                    "data": {
                        "symbol": _symu,
                        "action_label": str(action_label or ""),
                        "order_side": str(order_side or ""),
                        "position_side": str(position_side or ""),
                        "reduce_only": bool(reduce_only),
                        "quantity": float(quantity),
                        "maker_enabled": bool(maker_enabled),
                        "maker_enabled_override": maker_enabled_override,
                        "wait_total_s": int(wait_total),
                        "attempts": int(attempts),
                        "allow_market_fallback": bool(allow_market_fallback),
                        "execution_mode": str(execution_mode or ""),
                        "forced_mode": str(forced_mode or ""),
                        "policy": str(policy or ""),
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

        # Dry-run execution path (no Binance orders, but simulate maker attempts/fallbacks)
        try:
            from utils.runtime_flags import get_flag_bool_env
            dry_run_exec = get_flag_bool_env(self.redis, "DRY_RUN_EXECUTION", False)
        except Exception:
            dry_run_exec = False

        if dry_run_exec:
            attempts = max(1, int(attempts))
            wait_total = max(1, int(wait_total))
            wait_per_attempt = max(1, int(wait_total / attempts))

            if not maker_enabled:
                logger.info(
                    f"DRY_RUN_EXEC | action={action_label} | symbol={symbol} | mode=MARKET_DIRECT | "
                    f"reduce_only={bool(reduce_only)} | maker_attempts={attempts} | result=SIM_OK"
                )
                synthetic = {
                    "orderId": f"DRYRUN-MARKET-{int(time.time() * 1000)}",
                    "executedQty": str(float(quantity)),
                    "avgPrice": "0",
                    "_execution_path": "MARKET_DIRECT",
                    "_liquidity": "TAKER",
                    "_dry_run": True,
                }
                return {"ok": True, "order": synthetic, "liquidity": "TAKER", "execution_path": "MARKET_DIRECT"}

            logger.info(
                f"MAKER_FIRST_START | action={action_label} | symbol={symbol} side={order_side} posSide={position_side} "
                f"qty={float(quantity):.8f} reduce_only={bool(reduce_only)} attempts={attempts} "
                f"wait_total_s={wait_total} wait_per_attempt_s={wait_per_attempt} market_fallback={allow_market_fallback}"
            )
            logger.info(
                f"DRY_RUN_EXEC | action={action_label} | symbol={symbol} | mode=MAKER_FIRST | "
                f"reduce_only={bool(reduce_only)} | maker_attempts={attempts} | result=SIM_START"
            )

            total_executed_qty = 0.0
            total_notional = 0.0
            maker_filled_qty = 0.0
            taker_filled_qty = 0.0
            order_ids: List[Any] = []

            for attempt_idx in range(attempts):
                remaining = float(quantity) - float(total_executed_qty)
                if remaining <= 0:
                    break

                limit_price = 1.0
                logger.info(
                    f"MAKER_FIRST_LIMIT_ATTEMPT | action={action_label} | symbol={symbol} side={order_side} posSide={position_side} "
                    f"qty_remaining={remaining:.8f} limit_price={limit_price:.8f} attempt={attempt_idx+1}/{attempts}"
                )

                order_id = f"DRYRUN-LIMIT-{attempt_idx+1}-{int(time.time() * 1000)}"
                order_ids.append(order_id)
                status = {"status": "NEW", "executedQty": "0", "avgPrice": str(limit_price)}
                logger.info(
                    f"MAKER_FIRST_LIMIT_STATUS | action={action_label} | symbol={symbol} orderId={order_id} "
                    f"status={status.get('status')} executedQty={status.get('executedQty')} avgPrice={status.get('avgPrice')}"
                )

            remaining = float(quantity) - float(total_executed_qty)
            if remaining > 0 and allow_market_fallback:
                logger.warning(
                    f"MAKER_FIRST_MARKET_FALLBACK | action={action_label} | symbol={symbol} side={order_side} "
                    f"qty_remaining={remaining:.8f} maker_filled_qty={maker_filled_qty:.8f} attempts={attempts} wait_total_s={wait_total}"
                )
                logger.info(
                    f"DRY_RUN_EXEC | action={action_label} | symbol={symbol} | mode=MARKET_FALLBACK | "
                    f"reduce_only={bool(reduce_only)} | maker_attempts={attempts} | result=SIM_OK"
                )
                synthetic = {
                    "orderId": f"DRYRUN-MARKET-{int(time.time() * 1000)}",
                    "executedQty": str(float(remaining)),
                    "avgPrice": "0",
                    "_order_ids": order_ids,
                    "_execution_path": "MAKER_FIRST_MARKET_FALLBACK",
                    "_liquidity": "TAKER",
                    "_dry_run": True,
                }
                return {
                    "ok": True,
                    "order": synthetic,
                    "liquidity": "TAKER",
                    "execution_path": "MAKER_FIRST_MARKET_FALLBACK",
                }

            logger.info(
                f"DRY_RUN_EXEC | action={action_label} | symbol={symbol} | mode=MAKER_ONLY | "
                f"reduce_only={bool(reduce_only)} | maker_attempts={attempts} | result=SIM_PARTIAL_NO_MARKET"
            )
            synthetic = {
                "orderId": f"DRYRUN-LIMIT-{int(time.time() * 1000)}",
                "executedQty": str(float(total_executed_qty)),
                "avgPrice": "0",
                "_order_ids": order_ids,
                "_execution_path": "MAKER_FIRST_PARTIAL_NO_MARKET",
                "_liquidity": "MAKER",
                "_dry_run": True,
            }
            return {"ok": True, "order": synthetic, "liquidity": "MAKER", "execution_path": "MAKER_FIRST_PARTIAL_NO_MARKET"}

        if not maker_enabled:
            # direct market (legacy behavior)
            exec_mode_u = ""
            try:
                exec_mode_u = str(execution_mode or "").upper().strip()
            except Exception:
                exec_mode_u = ""

            # Optional: IOC limit first (bounded slippage), then market fallback.
            # Intended for survival exits where we want an immediate fill but with a price cap.
            if exec_mode_u in ("IOC", "IOC_THEN_MARKET", "MARKET_OR_IOC"):
                try:
                    # Best-effort current price anchor
                    cur_px = 0.0
                    try:
                        getter = getattr(self, "get_current_price", None)
                        if callable(getter):
                            cur_px = float(getter(symbol) or 0.0)
                    except Exception:
                        cur_px = 0.0

                    if cur_px > 0:
                        symbol_info = self._get_symbol_info_cached(symbol)
                        tick_size, price_prec = self._extract_tick_size(symbol_info)

                        # Default IOC aggression: 10 bps. Configurable via env.
                        try:
                            ioc_bps = float(os.getenv("IOC_PRICE_OFFSET_BPS", "10.0"))
                        except Exception:
                            ioc_bps = 10.0
                        ioc_bps = max(2.0, min(100.0, float(ioc_bps)))
                        offset = float(ioc_bps) / 10000.0

                        raw_ioc_price = cur_px * (1 + offset) if order_side == "BUY" else cur_px * (1 - offset)
                        ioc_price = self._quantize_price(float(raw_ioc_price), tick_size, order_side, price_prec)

                        logger.warning(
                            "IOC_EXEC_START | action=%s | symbol=%s side=%s posSide=%s | qty=%.8f | px=%.8f | bps=%.1f",
                            action_label, symbol, order_side, position_side, float(quantity), float(ioc_price), float(ioc_bps),
                        )

                        ioc_params = {
                            "symbol": symbol,
                            "side": order_side,
                            "positionSide": position_side,
                            "type": "LIMIT",
                            "timeInForce": "IOC",
                            "price": float(ioc_price),
                            "quantity": float(quantity),
                            "newOrderRespType": "RESULT",
                        }
                        if reduce_only:
                            ioc_params["reduceOnly"] = True

                        try:
                            ioc_order = self.client.futures_create_order(**ioc_params)
                        except Exception as e:
                            # Some modes/endpoints reject reduceOnly with -1106 ("not required").
                            err_str = str(e)
                            if reduce_only and ("-1106" in err_str or "reduceonly" in err_str.lower()):
                                ioc_params.pop("reduceOnly", None)
                                ioc_order = self.client.futures_create_order(**ioc_params)
                            else:
                                raise

                        if isinstance(ioc_order, dict):
                            ioc_order["_liquidity"] = "TAKER"
                            ioc_order["_execution_path"] = "IOC_LIMIT"
                            ioc_order = reconcile_order_fill(self.client, symbol, ioc_order)

                        try:
                            ioc_filled = float((ioc_order or {}).get("executedQty") or 0.0)
                        except Exception:
                            ioc_filled = 0.0
                        try:
                            ioc_avg_px = float((ioc_order or {}).get("avgPrice") or 0.0)
                        except Exception:
                            ioc_avg_px = 0.0

                        if ioc_filled > 0:
                            # Full or partial IOC fill.
                            total_executed_qty = float(ioc_filled)
                            total_notional = float(ioc_filled) * float(ioc_avg_px or cur_px)
                            order_ids: List[Any] = [((ioc_order or {}).get("orderId") if isinstance(ioc_order, dict) else None)]

                            remaining = float(quantity) - float(ioc_filled)
                            if remaining > 0 and allow_market_fallback:
                                logger.warning(
                                    "IOC_PARTIAL_MARKET_FALLBACK | action=%s | symbol=%s | remaining=%.8f filled=%.8f",
                                    action_label, symbol, remaining, ioc_filled,
                                )
                                market_params = {
                                    "symbol": symbol,
                                    "side": order_side,
                                    "positionSide": position_side,
                                    "type": "MARKET",
                                    "quantity": float(remaining),
                                    "priceProtect": True,
                                    "newOrderRespType": "RESULT",
                                }
                                if reduce_only:
                                    market_params["reduceOnly"] = True
                                try:
                                    market = self.client.futures_create_order(**market_params)
                                except Exception as e:
                                    err_str = str(e)
                                    if reduce_only and ("-1106" in err_str or "reduceonly" in err_str.lower()):
                                        market_params.pop("reduceOnly", None)
                                        market = self.client.futures_create_order(**market_params)
                                    else:
                                        raise
                                if isinstance(market, dict):
                                    market = reconcile_order_fill(self.client, symbol, market)
                                try:
                                    m_qty = float((market or {}).get("executedQty") or remaining)
                                except Exception:
                                    m_qty = remaining
                                try:
                                    m_px = float((market or {}).get("avgPrice") or 0.0)
                                except Exception:
                                    m_px = 0.0
                                if m_qty > 0 and m_px > 0:
                                    total_executed_qty += m_qty
                                    total_notional += m_qty * m_px
                                order_ids.append((market or {}).get("orderId") if isinstance(market, dict) else None)

                                synthetic = dict(market or ioc_order or {})
                                if total_executed_qty > 0:
                                    synthetic["executedQty"] = str(total_executed_qty)
                                    synthetic["avgPrice"] = str(total_notional / total_executed_qty) if total_notional > 0 else str(m_px or ioc_avg_px or cur_px)
                                synthetic["_order_ids"] = order_ids
                                synthetic["_execution_path"] = "IOC_THEN_MARKET"
                                synthetic["_liquidity"] = "TAKER"
                                return {"ok": True, "order": synthetic, "liquidity": "TAKER", "execution_path": "IOC_THEN_MARKET"}

                            # IOC filled enough (or no market fallback requested).
                            synthetic = dict(ioc_order or {})
                            if total_executed_qty > 0:
                                synthetic["executedQty"] = str(total_executed_qty)
                                if total_notional > 0:
                                    synthetic["avgPrice"] = str(total_notional / total_executed_qty)
                            synthetic["_order_ids"] = order_ids
                            synthetic["_execution_path"] = "IOC_LIMIT_FILLED"
                            synthetic["_liquidity"] = "TAKER"
                            return {"ok": True, "order": synthetic, "liquidity": "TAKER", "execution_path": "IOC_LIMIT_FILLED"}
                except Exception as _ioc_err:
                    logger.warning(
                        "IOC_EXEC_ERR | action=%s | symbol=%s | err=%s",
                        action_label, symbol, str(_ioc_err)[:220],
                    )
            try:
                market_params = {
                    "symbol": symbol,
                    "side": order_side,
                    "positionSide": position_side,
                    "type": "MARKET",
                    "quantity": float(quantity),
                    "priceProtect": True,
                    "newOrderRespType": "RESULT",
                }
                if reduce_only:
                    market_params["reduceOnly"] = True
                try:
                    order = self.client.futures_create_order(**market_params)
                except Exception as e:
                    # Some modes/endpoints reject reduceOnly with -1106 ("not required").
                    # Retry without reduceOnly to avoid blocking protective exits.
                    err_str = str(e)
                    if reduce_only and ("-1106" in err_str or "reduceonly" in err_str.lower()):
                        market_params.pop("reduceOnly", None)
                        order = self.client.futures_create_order(**market_params)
                    else:
                        raise
                if isinstance(order, dict):
                    order["_liquidity"] = "TAKER"
                    order["_execution_path"] = "MARKET_DIRECT"
                    # ── Fill reconciliation: poll if ack returned qty=0 ──
                    order = reconcile_order_fill(self.client, symbol, order)
                return {"ok": True, "order": order, "liquidity": "TAKER", "execution_path": "MARKET_DIRECT"}
            except Exception as e:
                return {"ok": False, "error": f"market_direct_failed:{e}"}

        attempts = max(1, attempts)
        wait_total = max(1, wait_total)
        wait_per_attempt = max(1, int(wait_total / attempts))

        logger.info(
            f"MAKER_FIRST_START | action={action_label} | symbol={symbol} side={order_side} posSide={position_side} "
            f"qty={float(quantity):.8f} reduce_only={bool(reduce_only)} attempts={attempts} "
            f"wait_total_s={wait_total} wait_per_attempt_s={wait_per_attempt} market_fallback={allow_market_fallback}"
        )

        symbol_info = self._get_symbol_info_cached(symbol)
        total_executed_qty = 0.0
        total_notional = 0.0
        maker_filled_qty = 0.0
        taker_filled_qty = 0.0
        order_ids: List[Any] = []
        last_err: Optional[str] = None

        # Helper to get current price (best-effort)
        def _current_price() -> float:
            try:
                getter = getattr(self, "get_current_price", None)
                if callable(getter):
                    px = getter(symbol)
                    return float(px or 0.0)
            except Exception:
                return 0.0
            return 0.0

        for attempt_idx in range(attempts):
            remaining = float(quantity) - float(total_executed_qty)
            if remaining <= 0:
                break

            cur_px = _current_price()
            # ── Target price from trainer signal: use it for the first attempt,
            # then blend toward current market price on reprices so we don't
            # sit at a stale price forever.
            if target_price and float(target_price) > 0:
                _tp = float(target_price)
                _tick, _prec = self._extract_tick_size(symbol_info)
                if attempt_idx == 0:
                    # First attempt: use trainer target exactly (quantized)
                    limit_price = self._quantize_price(_tp, _tick, order_side, _prec)
                    logger.info(
                        f"MAKER_TARGET_PRICE | action={action_label} | symbol={symbol} | "
                        f"target_price={_tp:.8f} | attempt=1/{attempts}"
                    )
                else:
                    # Subsequent attempts: blend 50% target + 50% current market
                    blend = (_tp + cur_px) / 2.0 if cur_px > 0 else _tp
                    limit_price = self._compute_post_only_limit_price(
                        symbol=symbol,
                        order_side=order_side,
                        current_price=float(blend),
                        maker_price_offset_bps=float(price_offset_bps),
                        symbol_info=symbol_info,
                    )
                    logger.info(
                        f"MAKER_TARGET_BLEND | action={action_label} | symbol={symbol} | "
                        f"target={_tp:.8f} market={cur_px:.8f} blend={blend:.8f} | attempt={attempt_idx+1}/{attempts}"
                    )
            else:
                limit_price = self._compute_post_only_limit_price(
                    symbol=symbol,
                    order_side=order_side,
                    current_price=float(cur_px or 0.0),
                    maker_price_offset_bps=float(price_offset_bps),
                    symbol_info=symbol_info,
                )
            if limit_price <= 0:
                last_err = "limit_price_invalid"
                break

            logger.info(
                f"MAKER_FIRST_LIMIT_ATTEMPT | action={action_label} | symbol={symbol} side={order_side} posSide={position_side} "
                f"qty_remaining={remaining:.8f} limit_price={limit_price:.8f} attempt={attempt_idx+1}/{attempts}"
            )

            # Place post-only LIMIT
            limit_params = {
                "symbol": symbol,
                "side": order_side,
                "positionSide": position_side,
                "type": "LIMIT",
                "price": float(limit_price),
                "quantity": float(remaining),
                "timeInForce": "GTX",  # Post-only
                "newOrderRespType": "RESULT",
            }
            if reduce_only:
                limit_params["reduceOnly"] = True

            try:
                created = self.client.futures_create_order(**limit_params)
            except Exception as e:
                err_str = str(e)
                # reduceOnly can be rejected in some modes; retry without
                if reduce_only and ("-1106" in err_str or "reduceonly" in err_str.lower()):
                    try:
                        limit_params.pop("reduceOnly", None)
                        created = self.client.futures_create_order(**limit_params)
                    except Exception as e2:
                        last_err = f"limit_create_failed:{e2}"
                        logger.warning(f"MAKER_FIRST_LIMIT_CREATE_FAIL | action={action_label} | symbol={symbol} err={last_err}")
                        continue
                else:
                    # GTX reject (-5022) means it would cross; for reduce-only closes, fallback fast.
                    if ("-5022" in err_str or "post only" in err_str.lower()) and reduce_only and allow_market_fallback:
                        last_err = f"post_only_rejected:{e}"
                        logger.warning(
                            "MAKER_FIRST_GTX_REJECT_FAST_FALLBACK | action=%s | symbol=%s | reduce_only=1 | err=%s",
                            action_label, symbol, last_err,
                        )
                        break
                    last_err = f"limit_create_failed:{e}"
                    logger.warning(f"MAKER_FIRST_LIMIT_CREATE_FAIL | action={action_label} | symbol={symbol} err={last_err}")
                    continue

            order_id = (created or {}).get("orderId") if isinstance(created, dict) else None
            order_ids.append(order_id)

            # Wait, then check status once (low API pressure)
            time.sleep(wait_per_attempt)
            status = None
            try:
                status = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            except Exception as e:
                last_err = f"limit_status_failed:{e}"
                status = None

            logger.info(
                f"MAKER_FIRST_LIMIT_STATUS | action={action_label} | symbol={symbol} orderId={order_id} "
                f"status={(status or {}).get('status')} executedQty={(status or {}).get('executedQty')} avgPrice={(status or {}).get('avgPrice')}"
            )

            # Parse fill
            try:
                filled_qty = float((status or {}).get("executedQty") or 0.0)
            except Exception:
                filled_qty = 0.0
            try:
                avg_price = float((status or {}).get("avgPrice") or 0.0)
            except Exception:
                avg_price = 0.0
            order_status = str((status or {}).get("status") or "").upper()

            if filled_qty > 0 and avg_price > 0:
                maker_filled_qty += filled_qty
                total_executed_qty += filled_qty
                total_notional += filled_qty * avg_price

            # If fully filled, we are done.
            remaining_after = float(quantity) - float(total_executed_qty)
            if remaining_after <= max(1e-12, float(quantity) * 1e-6):
                synthetic = dict(status or created or {})
                synthetic["executedQty"] = str(total_executed_qty)
                synthetic["avgPrice"] = str(total_notional / total_executed_qty) if total_executed_qty > 0 else str(avg_price or limit_price)
                synthetic["_liquidity"] = "MAKER"
                synthetic["_execution_path"] = "MAKER_FIRST_LIMIT_FILLED"
                synthetic["_order_ids"] = order_ids
                return {"ok": True, "order": synthetic, "liquidity": "MAKER", "execution_path": "MAKER_FIRST_LIMIT_FILLED"}

            # Not fully filled: cancel remainder
            try:
                self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            except Exception:
                pass

            # If exchange says order is CANCELED/EXPIRED/REJECTED, continue attempts
            if order_status in ("CANCELED", "EXPIRED", "REJECTED"):
                continue
            # If still NEW/PARTIALLY_FILLED, we cancelled anyway; proceed to next attempt.

        # If we reach here, remaining exists
        remaining = float(quantity) - float(total_executed_qty)
        if remaining > 0 and allow_market_fallback:
            logger.warning(
                f"MAKER_FIRST_MARKET_FALLBACK | action={action_label} | symbol={symbol} side={order_side} "
                f"qty_remaining={remaining:.8f} maker_filled_qty={maker_filled_qty:.8f} attempts={attempts} wait_total_s={wait_total}"
            )
            try:
                market_params = {
                    "symbol": symbol,
                    "side": order_side,
                    "positionSide": position_side,
                    "type": "MARKET",
                    "quantity": float(remaining),
                    "priceProtect": True,
                    "newOrderRespType": "RESULT",
                }
                if reduce_only:
                    market_params["reduceOnly"] = True
                try:
                    market = self.client.futures_create_order(**market_params)
                except Exception as e:
                    # Some endpoints/modes reject reduceOnly with -1106 ("not required").
                    # Retry without reduceOnly to avoid blocking protective exits.
                    err_str = str(e)
                    if reduce_only and ("-1106" in err_str or "reduceonly" in err_str.lower()):
                        try:
                            market_params.pop("reduceOnly", None)
                            market = self.client.futures_create_order(**market_params)
                        except Exception as e2:
                            raise e2
                    else:
                        raise e
                order_ids.append((market or {}).get("orderId") if isinstance(market, dict) else None)
                # ── Fill reconciliation: poll if market fallback ack returned qty=0 ──
                if isinstance(market, dict):
                    market = reconcile_order_fill(self.client, symbol, market)
                try:
                    m_qty = float((market or {}).get("executedQty") or remaining)
                except Exception:
                    m_qty = remaining
                try:
                    m_px = float((market or {}).get("avgPrice") or 0.0)
                except Exception:
                    m_px = 0.0
                if m_qty > 0 and m_px > 0:
                    taker_filled_qty += m_qty
                    total_executed_qty += m_qty
                    total_notional += m_qty * m_px

                synthetic = dict(market or {})
                if total_executed_qty > 0 and total_notional > 0:
                    synthetic["executedQty"] = str(total_executed_qty)
                    synthetic["avgPrice"] = str(total_notional / total_executed_qty)
                synthetic["_order_ids"] = order_ids
                synthetic["_execution_path"] = "MAKER_FIRST_MARKET_FALLBACK"
                synthetic["_liquidity"] = "MIXED" if maker_filled_qty > 0 else "TAKER"
                return {
                    "ok": True,
                    "order": synthetic,
                    "liquidity": ("MIXED" if maker_filled_qty > 0 else "TAKER"),
                    "execution_path": "MAKER_FIRST_MARKET_FALLBACK",
                }
            except Exception as e:
                return {"ok": False, "error": f"market_fallback_failed:{e}", "partial_executed_qty": total_executed_qty}

        # No market fallback allowed → report as not executed (or partial)
        if total_executed_qty > 0:
            # Partial execution occurred (maker fills). Return synthetic.
            synthetic = {
                "orderId": order_ids[-1] if order_ids else None,
                "executedQty": str(total_executed_qty),
                "avgPrice": str(total_notional / total_executed_qty) if total_executed_qty > 0 else "0",
                "status": "PARTIALLY_FILLED",
                "type": "LIMIT",
                "timeInForce": "GTX",
                "_order_ids": order_ids,
                "_execution_path": "MAKER_FIRST_PARTIAL_NO_MARKET",
                "_liquidity": "MAKER",
            }
            return {"ok": True, "order": synthetic, "liquidity": "MAKER", "execution_path": "MAKER_FIRST_PARTIAL_NO_MARKET"}

        return {"ok": False, "skip_reason": last_err or "maker_first_no_fill"}
    
    def get_redis_key(self, key_type: str, *args) -> str:
        """
        Generate Redis key with account namespace
        
        Args:
            key_type: Type of key (positions, balance, orders, etc.)
            *args: Additional key components
        
        Returns:
            Namespaced Redis key
        """
        key_parts = ["wma", self.account_id, key_type] + list(args)
        return ":".join(str(part) for part in key_parts)
    
    def report_position(self, symbol: str, position: Dict[str, Any]):
        """
        Report position to Redis for trainer consumption
        
        Args:
            symbol: Trading symbol
            position: Position dictionary with current state
        """
        try:
            key = self.get_redis_key("positions", symbol)
            self.redis.setex(
                key,
                300,  # 5 minute expiry
                json.dumps({
                    **position,
                    "timestamp": time.time(),
                    "account_id": self.account_id
                })
            )
        except Exception as e:
            logger.error(f"Failed to report position: {e}")
    
    def report_balance(self, balance_data: Optional[Dict[str, float]] = None):
        """
        Report balance to Redis for trainer consumption
        
        Args:
            balance_data: Dictionary with balance information (optional)
        """
        try:
            key = self.get_redis_key("balance")
            
            if balance_data:
                # Use provided balance data
                data = {
                    "balance": balance_data.get("balance", 0),
                    "available": balance_data.get("available", 0),
                    "unrealized_pnl": balance_data.get("unrealized_pnl", 0),
                    "timestamp": time.time(),
                    "account_id": self.account_id
                }
            else:
                # Use internal state (for compatibility)
                data = {
                    "balance": getattr(self, 'balance', 0),
                    "unrealized_pnl": getattr(self, 'unrealized_pnl', 0),
                    "timestamp": time.time(),
                    "account_id": self.account_id
                }
            
            self.redis.setex(key, 300, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to report balance: {e}")
    
    def report_fill(self, order: Dict[str, Any]):
        """
        Report filled order to Redis for trainer consumption
        
        Args:
            order: Order dictionary with fill information
        """
        try:
            key = self.get_redis_key("fills", order.get("orderId", "unknown"))
            self.redis.setex(
                key,
                3600,  # 1 hour expiry
                json.dumps({
                    **order,
                    "timestamp": time.time(),
                    "account_id": self.account_id
                })
            )
            
            # Also publish to fills stream for real-time updates
            stream_key = self.get_redis_key("stream", "fills")
            self.redis.xadd(
                stream_key,
                {
                    "order_id": order.get("orderId", ""),
                    "symbol": order.get("symbol", ""),
                    "side": order.get("side", ""),
                    "quantity": order.get("executedQty", 0),
                    "price": order.get("avgPrice", 0),
                    "timestamp": time.time()
                },
                maxlen=1000
            )
        except Exception as e:
            logger.error(f"Failed to report fill: {e}")

    def _record_attribution(self, payload: Dict[str, Any]):
        """Publish execution attribution to Redis when enabled."""
        if not self.execution_attribution_enabled:
            return
        if not payload:
            return
        try:
            payload.setdefault("ts_ms", int(time.time() * 1000))
            payload.setdefault("account_id", self.account_id)
            stream = self.execution_attribution_stream or "trades:attribution"
            data = json.dumps(payload, separators=(",", ":"), default=str)
            self.redis.xadd(stream, {"data": data}, maxlen=5000, approximate=True)
            self._update_attribution_summary(payload)
        except Exception as exc:
            logger.debug(f"[ATTRIB] failed to publish: {exc}")

    def _update_attribution_summary(self, payload: Dict[str, Any]) -> None:
        """Maintain a rolling per-symbol realized attribution summary for dashboards."""
        try:
            if not self.redis or not payload:
                return

            symbol = str(payload.get("symbol") or "").upper().strip()
            if not symbol:
                return

            account_id = str(payload.get("account_id") or self.account_id or "")
            prefix = self.execution_attribution_summary_prefix or "trades:attribution:summary"
            key = f"{prefix}:{account_id}:{symbol}"
            index_key = f"{prefix}:symbols:{account_id}"

            action = str(payload.get("action") or "").upper()
            source = str(payload.get("source") or "")
            result = str(payload.get("execution_result") or "")
            ts_ms = int(payload.get("ts_ms") or int(time.time() * 1000))

            realized = payload.get("realized_pnl_usd")
            pnl_pct = payload.get("pnl_pct")
            realized_f = None
            pnl_pct_f = None
            try:
                if realized is not None:
                    realized_f = float(realized)
            except Exception:
                realized_f = None
            try:
                if pnl_pct is not None:
                    pnl_pct_f = float(pnl_pct)
            except Exception:
                pnl_pct_f = None

            pipe = self.redis.pipeline()
            pipe.sadd(index_key, symbol)
            pipe.expire(index_key, 86400 * 30)
            pipe.hset(key, "symbol", symbol)
            pipe.hset(key, "account_id", account_id)
            pipe.hset(key, "last_ts_ms", str(ts_ms))
            pipe.hset(key, "last_action", action)
            pipe.hset(key, "last_source", source)
            pipe.hset(key, "last_result", result)
            pipe.hincrby(key, "event_count", 1)

            if action in {"CLOSE", "PARTIAL_CLOSE"}:
                pipe.hincrby(key, "close_events", 1)
            if action in {"OPEN", "INCREASE", "OPEN_LONG", "OPEN_SHORT", "INCREASE_LONG", "INCREASE_SHORT"}:
                pipe.hincrby(key, "open_events", 1)

            if realized_f is not None:
                pipe.hincrbyfloat(key, "realized_pnl_usd_total", realized_f)
                if action in {"CLOSE", "PARTIAL_CLOSE"}:
                    pipe.hincrby(key, "realized_event_count", 1)
                if realized_f > 0:
                    pipe.hincrby(key, "win_events", 1)
                    pipe.hincrbyfloat(key, "realized_pnl_usd_positive", realized_f)
                elif realized_f < 0:
                    pipe.hincrby(key, "loss_events", 1)
                    pipe.hincrbyfloat(key, "realized_pnl_usd_negative", realized_f)
            if pnl_pct_f is not None:
                pipe.hset(key, "last_realized_pnl_pct", f"{pnl_pct_f:.8f}")

            pipe.expire(key, 86400 * 30)
            pipe.execute()
        except Exception as exc:
            logger.debug(f"[ATTRIB_SUMMARY] failed to update: {exc}")
    
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """
        Get current position for symbol
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Position dictionary
        """
        return self.positions.get(symbol, {
            "symbol": symbol,
            "position_amt": 0.0,
            "entry_price": 0.0,
            "unrealized_profit": 0.0,
            "leverage": 1,
            "position_side": "BOTH"
        })
    
    def update_trade_history(self, trade: Dict[str, Any]):
        """
        Update trade history for performance tracking
        
        Args:
            trade: Trade dictionary with execution details
        """
        self.trade_history.append({
            **trade,
            "timestamp": time.time()
        })
        
        # Calculate performance metrics
        if len(self.trade_history) >= 10:
            recent_pnls = [t.get("pnl", 0) for t in list(self.trade_history)[-10:] if "pnl" in t]
            if recent_pnls:
                win_rate = len([p for p in recent_pnls if p > 0]) / len(recent_pnls)
                avg_win = np.mean([p for p in recent_pnls if p > 0]) if any(p > 0 for p in recent_pnls) else 0
                avg_loss = np.mean([abs(p) for p in recent_pnls if p < 0]) if any(p < 0 for p in recent_pnls) else 0
                
                # Store metrics in Redis
                metrics_key = self.get_redis_key("metrics", "performance")
                self.redis.setex(
                    metrics_key,
                    300,
                    json.dumps({
                        "win_rate": win_rate,
                        "avg_win": avg_win,
                        "avg_loss": avg_loss,
                        "profit_factor": (avg_win * win_rate) / (avg_loss * (1 - win_rate)) if avg_loss > 0 and win_rate < 1 else 0,
                        "trade_count": len(self.trade_history),
                        "timestamp": time.time()
                    })
                )


# Export classes
__all__ = [
    'OfflineBinanceClient',
    'CircuitBreaker',
    'BaseExecutor'
]
