"""
Portfolio Policy Manager
========================
Enforces portfolio-level constraints for position slots, exposure budgets, and reserve.

Used by:
- Trainer publish gate (must block before signals:trading)
- Trader preflight (must block before any close/open sequence for flips)

Implements Addendum A: Portfolio Constraints
- Max 5 LONG / 5 SHORT positions (10 total)
- Ultra-high confidence (>=0.98) allows up to 12 total with reserve
- LONG/SHORT budget caps at 25% of equity each
- 20% equity reserve for ultra-high confidence only
- Fail-closed on stale equity data

Author: WMA AI Trading System
Date: December 24, 2025
"""

import logging
import time
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

logger = logging.getLogger(__name__)


class PolicyBlockReason(Enum):
    """Structured block reasons for telemetry and skip streams."""
    PORTFOLIO_SLOT_BLOCK = "PORTFOLIO_SLOT_BLOCK"
    PORTFOLIO_BUDGET_BLOCK = "PORTFOLIO_BUDGET_BLOCK"
    PORTFOLIO_RESERVE_BLOCK = "PORTFOLIO_RESERVE_BLOCK"
    PORTFOLIO_STALE_EQUITY_BLOCK = "PORTFOLIO_STALE_EQUITY_BLOCK"
    PORTFOLIO_TOTAL_MARGIN_BLOCK = "PORTFOLIO_TOTAL_MARGIN_BLOCK"


@dataclass
class PortfolioSnapshot:
    """Current portfolio state snapshot for policy decisions."""
    equity: float = 0.0
    long_slots_used: int = 0
    short_slots_used: int = 0
    total_positions: int = 0
    long_margin_used: float = 0.0
    short_margin_used: float = 0.0
    total_margin_used: float = 0.0
    reserve_remaining: float = 0.0
    snapshot_ts_ms: int = 0
    positions: Dict[str, Dict] = field(default_factory=dict)
    account_id: str = "all"  # Which account this snapshot is for: 'all', 'primary', 'asjad'
    
    @property
    def long_margin_pct(self) -> float:
        return (self.long_margin_used / self.equity * 100) if self.equity > 0 else 0
    
    @property
    def short_margin_pct(self) -> float:
        return (self.short_margin_used / self.equity * 100) if self.equity > 0 else 0
    
    @property
    def total_margin_pct(self) -> float:
        return (self.total_margin_used / self.equity * 100) if self.equity > 0 else 0
    
    def get_long_margin_usage(self) -> float:
        """Get current LONG margin usage in USD"""
        return self.long_margin_used
    
    def get_short_margin_usage(self) -> float:
        """Get current SHORT margin usage in USD"""
        return self.short_margin_used
    
    def get_total_margin_usage(self) -> float:
        """Get current total margin usage in USD"""
        return self.total_margin_used


@dataclass
class PolicyDecision:
    """Result of a policy check."""
    allowed: bool
    block_reason: Optional[PolicyBlockReason] = None
    block_detail: str = ""
    snapshot: Optional[PortfolioSnapshot] = None
    ultra_mode: bool = False  # True if using ultra reserve
    hedge_allowed: bool = False  # True if allowed as HEDGE_V2 bypass


class PortfolioPolicyManager:
    """
    Manages portfolio-level policy enforcement for the trading system.
    
    Features:
    - Position slot limits (5 LONG / 5 SHORT, 10 total)
    - Ultra-high confidence exception (12 total for conf >= 0.98)
    - Exposure budgets (25% per side, 50% total normal, 70% with ultra)
    - Reserve buffer (20% for ultra-confidence only)
    - Fail-closed on stale equity data
    """
    
    def __init__(self, redis_client=None, config=None):
        """
        Initialize the Portfolio Policy Manager.
        
        Args:
            redis_client: Redis client for position/equity lookup
            config: LiveConfig object (or uses get_live_config())
        """
        # Auto-create Redis client if not provided
        if redis_client is None:
            try:
                from utils.redis_client import get_redis_client
                redis_client = get_redis_client()
                logger.info("[PORTFOLIO_POLICY] Auto-created Redis client")
            except Exception as e:
                logger.warning(f"[PORTFOLIO_POLICY] Failed to auto-create Redis client: {e}")
        self.redis = redis_client
        
        # Load config
        if config is None:
            from config import get_live_config
            config = get_live_config()
        self.config = config
        
        # Load policy parameters from config module (for env overrides)
        from config import (
            PORTFOLIO_MAX_LONG_SLOTS, PORTFOLIO_MAX_SHORT_SLOTS,
            PORTFOLIO_MAX_TOTAL_POSITIONS, PORTFOLIO_ULTRA_CONF_THRESHOLD,
            PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS, PORTFOLIO_LONG_BUDGET_PCT,
            PORTFOLIO_SHORT_BUDGET_PCT, PORTFOLIO_RESERVE_PCT,
            PORTFOLIO_NORMAL_MAX_MARGIN_PCT, PORTFOLIO_ULTRA_MAX_MARGIN_PCT,
            PORTFOLIO_EQUITY_MAX_AGE_MS,
            PORTFOLIO_RESERVE_MIN_CONF, PORTFOLIO_BASE_MAX_POSITIONS, 
            PORTFOLIO_RESERVE_MAX_POSITIONS,
            PORTFOLIO_HIGH_CONF_BUDGET_BONUS_PCT, PORTFOLIO_HIGH_CONF_THRESHOLD,
        )
        
        self.max_long_slots = PORTFOLIO_MAX_LONG_SLOTS
        self.max_short_slots = PORTFOLIO_MAX_SHORT_SLOTS
        self.max_total_positions = PORTFOLIO_MAX_TOTAL_POSITIONS
        self.ultra_conf_threshold = PORTFOLIO_ULTRA_CONF_THRESHOLD
        self.ultra_max_total_positions = PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS
        self.long_budget_pct = PORTFOLIO_LONG_BUDGET_PCT
        self.short_budget_pct = PORTFOLIO_SHORT_BUDGET_PCT
        self.reserve_pct = PORTFOLIO_RESERVE_PCT
        
        # High-confidence budget bonus (0.90+ conf gets extra 10% per side)
        self.high_conf_budget_bonus_pct = PORTFOLIO_HIGH_CONF_BUDGET_BONUS_PCT
        self.high_conf_threshold = PORTFOLIO_HIGH_CONF_THRESHOLD
        self.normal_max_margin_pct = PORTFOLIO_NORMAL_MAX_MARGIN_PCT
        self.ultra_max_margin_pct = PORTFOLIO_ULTRA_MAX_MARGIN_PCT
        self.equity_max_age_ms = PORTFOLIO_EQUITY_MAX_AGE_MS
        
        # Reserve usage is an EQUITY allocation (e.g., +20% equity headroom), NOT a "20% confidence" concept.
        # Confidence is only used to decide WHEN the reserve is allowed to be used.
        self.reserve_min_conf = float(PORTFOLIO_RESERVE_MIN_CONF)
        self.base_max_positions = PORTFOLIO_BASE_MAX_POSITIONS
        self.reserve_max_positions = PORTFOLIO_RESERVE_MAX_POSITIONS
        
        # ---------------------------------------------------------------------
        # INVARIANTS (safety): keep caps consistent with side budgets + reserve
        # ---------------------------------------------------------------------
        # Users expect:
        # - 25% LONG + 25% SHORT = 50% normal total budget
        # - +20% reserve (ultra / special conditions) = 70% max
        #
        # Even if env overrides set larger totals, clamp to a safe, consistent envelope.
        try:
            base_total_pct = float(self.long_budget_pct) + float(self.short_budget_pct)
        except Exception:
            base_total_pct = 0.50
        if base_total_pct <= 0:
            base_total_pct = 0.50

        try:
            ultra_total_cap = float(base_total_pct) + float(self.reserve_pct)
        except Exception:
            ultra_total_cap = float(base_total_pct) + 0.20

        # Normal cap cannot exceed sum of side budgets
        if float(self.normal_max_margin_pct) > float(base_total_pct):
            logger.warning(
                "[PORTFOLIO_POLICY] Clamp normal_max_margin_pct %.2f -> %.2f (must not exceed long+short budgets)",
                float(self.normal_max_margin_pct),
                float(base_total_pct),
            )
            self.normal_max_margin_pct = float(base_total_pct)

        # Ultra cap cannot exceed base + reserve
        if float(self.ultra_max_margin_pct) > float(ultra_total_cap):
            logger.warning(
                "[PORTFOLIO_POLICY] Clamp ultra_max_margin_pct %.2f -> %.2f (must not exceed base+reserve)",
                float(self.ultra_max_margin_pct),
                float(ultra_total_cap),
            )
            self.ultra_max_margin_pct = float(ultra_total_cap)

        # Ensure ordering (ultra >= normal)
        if float(self.ultra_max_margin_pct) < float(self.normal_max_margin_pct):
            self.ultra_max_margin_pct = float(self.normal_max_margin_pct)
        
        # Reserve eligibility threshold:
        # - The reserve is +reserve_pct equity headroom (e.g., +20%).
        # - We only allow OPEN_RISK to use this reserve under ULTRA-high confidence by default.
        #
        # NOTE: HEDGE actions may still use reserve (risk-reducing), but are capped by ultra_max_margin_pct.
        try:
            from config import RESERVE_CONFIDENCE_THRESHOLD  # default 0.97
            reserve_floor = float(RESERVE_CONFIDENCE_THRESHOLD)
        except Exception:
            reserve_floor = 0.97
        if reserve_floor <= 0:
            reserve_floor = 0.97
        # Enforce a high-confidence floor for reserve usage.
        self.reserve_min_conf = max(float(self.reserve_min_conf), float(reserve_floor))
        
        # Cache
        self._last_snapshot: Optional[PortfolioSnapshot] = None
        self._last_snapshot_ts: float = 0
        self._cache_ttl_sec: float = 5.0  # Refresh every 5s max
        
        logger.info(f"[PORTFOLIO_POLICY] Initialized: max_slots={self.max_long_slots}L/{self.max_short_slots}S, "
                   f"budgets={self.long_budget_pct*100:.0f}%L/{self.short_budget_pct*100:.0f}%S, "
                   f"reserve={self.reserve_pct*100:.0f}%, reserve_min_conf={self.reserve_min_conf:.2f}, "
                   f"base_max={self.base_max_positions}, reserve_max={self.reserve_max_positions}")

    def _log_contract(self, event: str, **fields):
        field_str = " | ".join(f"{k}={v}" for k, v in fields.items())
        logger.info(f"[{event}] | {field_str}" if field_str else f"[{event}]")
    
    def get_portfolio_snapshot(self, force_refresh: bool = False, account_id: str = None) -> PortfolioSnapshot:
        """
        Get current portfolio snapshot from Redis/exchange.
        
        Args:
            force_refresh: Force refresh even if cache is fresh
            account_id: Optional account filter ('primary', 'asjad', or None for all)
                       When set, only positions from that account are counted for slot limits.
                       This allows each trader to have independent position caps.
            
        Returns:
            PortfolioSnapshot with current state
        """
        now = time.time()
        
        # Cache key includes account_id for per-account caching
        cache_key = f"snapshot_{account_id or 'all'}"
        
        # Return cached if fresh (use per-account cache)
        if not force_refresh:
            cached = getattr(self, f'_cached_{cache_key}', None)
            cached_ts = getattr(self, f'_cached_{cache_key}_ts', 0)
            if cached and (now - cached_ts) < self._cache_ttl_sec:
                return cached
        
        snapshot = PortfolioSnapshot()
        snapshot.snapshot_ts_ms = int(now * 1000)
        snapshot.account_id = account_id or "all"
        
        try:
            # Hedge-mode fix: slot limits should count UNIQUE symbols, not legs.
            # We still track per-side slots as legs (LONG/SHORT) for side caps.
            from config import HEDGE_V2_ENABLED
            # Dust policy (Jan 2026): use **margin used**, not notional.
            try:
                from config import MICRO_POSITION_MIN_LEG_MARGIN_USD
                dust_leg_margin_usd = float(MICRO_POSITION_MIN_LEG_MARGIN_USD or 25.0)
            except Exception:
                dust_leg_margin_usd = 25.0
            dust_leg_margin_usd = max(0.0, float(dust_leg_margin_usd))

            # Normalize account id (multi-account live uses explicit ids).
            try:
                acct = str(account_id).strip().lower() if account_id is not None else None
            except Exception:
                acct = None

            # Get equity and positions directly from Binance API for the CORRECT account
            try:
                from binance.client import Client  # type: ignore
                import os
                
                # ================================================================
                # PRIORITY 1: Use Redis cached data from traders' WebSocket updates
                # This avoids rate limiting - traders update Redis every ~30 seconds
                # ================================================================
                account_name = "ASJAD" if acct == "asjad" else ("PRIMARY" if acct == "primary" else "ALL")
                redis_key = f"portfolio:equity:{acct}" if acct in ("primary", "asjad") else None
                
                if self.redis is None:
                    try:
                        from utils.redis_client import get_redis_client
                        self.redis = get_redis_client()
                    except Exception:
                        pass
                
                if self.redis and redis_key:
                    try:
                        import json
                        equity_json = self.redis.get(redis_key)
                        if equity_json:
                            eq_data = json.loads(equity_json)
                            ts_val = eq_data.get('timestamp', 0)
                            # Accept data up to 60 seconds old (trader updates every 30s)
                            if ts_val and (time.time() - float(ts_val)) < 60:
                                snapshot.equity = float(eq_data.get('equity_usd', 0))
                                snapshot.total_margin_used = float(eq_data.get('used_margin_usd', 0))
                                snapshot.snapshot_ts_ms = int(float(ts_val) * 1000)
                                logger.debug(f"[PORTFOLIO_POLICY] Redis cache ({account_name}): equity=${snapshot.equity:.2f}")
                    except Exception as e:
                        logger.debug(f"[PORTFOLIO_POLICY] Redis cache read failed: {e}")
                
                # PRIORITY 2: Only fall back to REST API if Redis data is stale/missing
                if snapshot.equity <= 0:
                    # Skip asjad API calls when disabled (invalid key / intentionally unfunded)
                    _disable_asjad_api = os.getenv("DISABLE_ASJAD_TRAINER_API", "false").lower() in ("1", "true", "yes")
                    if acct == 'asjad' and _disable_asjad_api:
                        logger.debug(f"[PORTFOLIO_POLICY] Skipping asjad REST API (DISABLE_ASJAD_TRAINER_API=true)")
                        api_key = None
                        api_secret = None
                    elif acct == 'asjad':
                        api_key = os.getenv("BINANCE_API_KEY_ASJAD")
                        api_secret = os.getenv("BINANCE_API_SECRET_ASJAD")
                    else:
                        api_key = os.getenv("BINANCE_API_KEY")
                        api_secret = os.getenv("BINANCE_API_SECRET")
                    
                    if api_key and api_secret:
                        client = Client(api_key, api_secret)
                        account = client.futures_account()
                        # Binance Futures:
                        # - totalWalletBalance = wallet (realized PnL only) - INCORRECT for caps
                        # - totalMarginBalance = equity (wallet + unrealized PnL) - CORRECT
                        # - totalUnrealizedProfit = unrealized PnL
                        # Portfolio budgets/caps MUST use totalMarginBalance (equity) to account for current drawdowns.
                        try:
                            snapshot.equity = float(
                                account.get("totalMarginBalance")
                                or (
                                    float(account.get("totalWalletBalance", 0) or 0)
                                    + float(account.get("totalUnrealizedProfit", 0) or 0)
                                )
                                or 0.0
                            )
                        except Exception:
                            snapshot.equity = float(account.get("totalMarginBalance", 0) or 0)
                        snapshot.total_margin_used = float(account.get('totalPositionInitialMargin', 0))
                        snapshot.snapshot_ts_ms = int(time.time() * 1000)
                        
                        # Also get positions from Binance API
                        symbols_with_position = set()
                        # Slot accounting should ignore micro/dust legs so they don't block higher-confidence symbols.
                        symbols_for_slot_count = set()
                        symbol_sides = {}
                        for pos in account.get('positions', []):
                            try:
                                pos_amt = float(pos.get('positionAmt', 0) or 0)
                                if pos_amt != 0:
                                    symbol = pos.get('symbol', '')
                                    side = 'LONG' if pos_amt > 0 else 'SHORT'
                                    margin = abs(float(pos.get('initialMargin', 0) or 0))
                                    # Dust: based on margin used (initialMargin) for the leg.
                                    is_dust = (dust_leg_margin_usd > 0.0) and (float(margin) > 0.0) and (float(margin) < dust_leg_margin_usd)
                                    
                                    snapshot.positions[symbol] = pos
                                    symbols_with_position.add(symbol)
                                    if not is_dust:
                                        symbols_for_slot_count.add(symbol)
                                    try:
                                        symbol_sides.setdefault(symbol, set()).add(str(side).upper())
                                    except Exception:
                                        pass
                                    # Legacy behavior: count legs when not in hedge-mode
                                    if not HEDGE_V2_ENABLED:
                                        snapshot.total_positions += 1
                                    
                                    if side == 'LONG':
                                        if not is_dust:
                                            snapshot.long_slots_used += 1
                                        snapshot.long_margin_used += margin
                                    else:
                                        if not is_dust:
                                            snapshot.short_slots_used += 1
                                        snapshot.short_margin_used += margin
                            except Exception:
                                pass
                        
                        # CRITICAL FIX: In hedge-mode, total_positions = unique symbols (not legs)
                        if HEDGE_V2_ENABLED:
                            # Use slot-count symbols (dust legs ignored)
                            snapshot.total_positions = len(symbols_for_slot_count)
                            try:
                                snapshot.symbol_sides = symbol_sides
                            except Exception:
                                pass
                        
                        if snapshot.equity > 0:
                            logger.info(f"[PORTFOLIO_POLICY] Binance API ({account_name}): equity=${snapshot.equity:.2f}, positions={snapshot.total_positions} "
                                       f"(L={snapshot.long_slots_used}, S={snapshot.short_slots_used})")
            except ImportError:
                logger.debug("[PORTFOLIO_POLICY] Binance client not installed, using Redis fallback")
            except Exception as binance_err:
                logger.debug(f"[PORTFOLIO_POLICY] Binance API failed: {binance_err}")
            
            # FALLBACK 1: Redis portfolio:equity:{account} (JSON from traders - most reliable)
            if snapshot.equity <= 0:
                # Ensure Redis client exists
                if self.redis is None:
                    try:
                        from utils.redis_client import get_redis_client
                        self.redis = get_redis_client()
                        logger.info("[PORTFOLIO_POLICY] Lazy-initialized Redis client")
                    except Exception as e:
                        logger.warning(f"[PORTFOLIO_POLICY] Failed to lazy-init Redis: {e}")
                
                if self.redis:
                    try:
                        import json
                        eq_key = None
                        try:
                            # Never cross-read another account's equity when a specific account is requested.
                            if acct in ("primary", "asjad"):
                                eq_key = f"portfolio:equity:{acct}"
                            else:
                                # Legacy callers (no account_id) default to primary (observability only).
                                eq_key = "portfolio:equity:primary"
                        except Exception:
                            eq_key = "portfolio:equity:primary"

                        equity_json = self.redis.get(eq_key) if eq_key else None
                        if equity_json:
                            eq_data = json.loads(equity_json)
                            snapshot.equity = float(eq_data.get('equity_usd', 0))
                            snapshot.total_margin_used = float(eq_data.get('used_margin_usd', 0))
                            ts_val = eq_data.get('timestamp', 0)
                            if ts_val:
                                snapshot.snapshot_ts_ms = int(float(ts_val) * 1000)
                            if snapshot.equity > 0:
                                logger.info(f"[PORTFOLIO_POLICY] Redis {eq_key} fallback: equity=${snapshot.equity:.2f}")
                    except Exception as e:
                        logger.debug(f"[PORTFOLIO_POLICY] Failed to read portfolio:equity fallback: {e}")
            
            # FALLBACK 2: Redis portfolio:primary:state (hash format)
            if snapshot.equity <= 0 and self.redis:
                equity_data = self.redis.hgetall("portfolio:primary:state")
                if equity_data:
                    # CRITICAL: Use margin_balance (equity = wallet + unrealized), NOT total_balance (wallet only)
                    # margin_balance includes unrealized PnL, which is required for accurate cap calculations
                    snapshot.equity = float(
                        equity_data.get(b'margin_balance', equity_data.get('margin_balance', 
                        equity_data.get(b'total_balance', equity_data.get('total_balance', 0)))) or 0
                    )
                    snapshot.total_margin_used = float(equity_data.get(b'total_margin_used', equity_data.get('total_margin_used', 0)) or 0)
                    ts_raw = equity_data.get(b'updated_ts_ms', equity_data.get('updated_ts_ms', 0))
                    try:
                        snapshot.snapshot_ts_ms = int(ts_raw)
                    except Exception:
                        pass
                    if snapshot.equity > 0:
                        logger.info(f"[PORTFOLIO_POLICY] Redis portfolio:primary:state fallback: equity=${snapshot.equity:.2f}")
                
            # NOTE: We intentionally do NOT cross-fallback to another account's equity here.
            # If acct='asjad' we read portfolio:equity:asjad; if acct='primary' we read portfolio:equity:primary.
            # All-account behavior (acct=None) is handled via the legacy default above.
            
            # ONLY load positions from Redis if Binance API didn't provide them
            # This prevents stale Redis data from overriding accurate Binance data
            binance_positions_loaded = snapshot.total_positions > 0
            
            if not binance_positions_loaded:
                if self.redis is None:
                    try:
                        from utils.redis_client import get_redis
                        self.redis = get_redis()
                    except:
                        pass
            
            if self.redis and not binance_positions_loaded:
                # Determine which position keys to check based on account_id
                if account_id == 'primary':
                    position_keys_to_check = ["portfolio:positions:primary", "positions:primary:all"]
                    wma_pattern = "wma:primary:positions:*"
                elif account_id == 'asjad':
                    position_keys_to_check = ["portfolio:positions:asjad"]
                    wma_pattern = "wma:asjad:positions:*"
                else:
                    # All accounts (default behavior)
                    position_keys_to_check = ["portfolio:positions:primary", "positions:primary:all", "portfolio:positions:asjad"]
                    wma_pattern = "wma:*:positions:*"
                
                # Try portfolio:positions keys first
                for positions_key in position_keys_to_check:
                    positions_raw = self.redis.hgetall(positions_key)
                    if positions_raw:
                        import json
                        now_ms = int(time.time() * 1000)
                        symbols_with_position = set()
                        symbols_for_slot_count = set()
                        symbol_sides = {}
                        for key, value in positions_raw.items():
                            try:
                                key_str = key.decode() if isinstance(key, bytes) else key
                                value_str = value.decode() if isinstance(value, bytes) else value
                                
                                # Skip if key looks like a symbol:side combo and value is the actual data
                                if ':' in key_str:
                                    # Format: "BTCUSDT:LONG" -> "{"size":...}"
                                    parts = key_str.split(':')
                                    symbol = parts[0]
                                    side = parts[1].upper() if len(parts) > 1 else 'UNKNOWN'
                                    pos_data = json.loads(value_str) if value_str.startswith('{') else {'size': 0}
                                else:
                                    pos_data = json.loads(value_str)
                                    symbol = pos_data.get('symbol', key_str)
                                    side = pos_data.get('side', 'UNKNOWN').upper()
                                
                                size = abs(float(pos_data.get('size', pos_data.get('positionAmt', 0)) or 0))
                                if size > 0 or pos_data.get('has_position', False):
                                    margin = abs(float(pos_data.get('margin_used', pos_data.get('initialMargin', pos_data.get('margin', 0))) or 0))
                                    # Dust leg detection (best-effort)
                                    notional = 0.0
                                    try:
                                        notional = abs(float(pos_data.get("notional", pos_data.get("notional_usd", 0)) or 0))
                                    except Exception:
                                        notional = 0.0
                                    if notional <= 0.0:
                                        try:
                                            mp = float(pos_data.get("mark_price", pos_data.get("markPrice", 0)) or 0)
                                        except Exception:
                                            mp = 0.0
                                        notional = float(size) * float(mp or 0.0)
                                    is_dust = (dust_leg_margin_usd > 0.0) and (float(margin) > 0.0) and (float(margin) < dust_leg_margin_usd)
                                    
                                    snapshot.positions[symbol] = pos_data
                                    # Track unique symbols + sides for HEDGE_V2 correctness
                                    symbols_with_position.add(symbol)
                                    if not is_dust:
                                        symbols_for_slot_count.add(symbol)
                                    try:
                                        symbol_sides.setdefault(symbol, set()).add(str(side).upper())
                                    except Exception:
                                        pass
                                    # Legacy behavior: count legs when not in hedge-mode
                                    if not HEDGE_V2_ENABLED:
                                        snapshot.total_positions += 1
                                    
                                    if side == 'LONG':
                                        if not is_dust:
                                            snapshot.long_slots_used += 1
                                        snapshot.long_margin_used += margin
                                    elif side == 'SHORT':
                                        if not is_dust:
                                            snapshot.short_slots_used += 1
                                        snapshot.short_margin_used += margin
                                        
                                    logger.debug(f"[PORTFOLIO_POLICY] Position: {symbol} {side} margin=${margin:.2f} (account={account_id or 'all'})")
                            except Exception as e:
                                logger.debug(f"[PORTFOLIO_POLICY] Error parsing position {key}: {e}")
                        
                        # CRITICAL FIX: In hedge-mode, total_positions = unique symbols (not legs)
                        if HEDGE_V2_ENABLED:
                            snapshot.total_positions = len(symbols_for_slot_count)
                            try:
                                # Attach side-map for correct same-side detection in admission checks
                                snapshot.symbol_sides = symbol_sides
                            except Exception:
                                pass

                        try:
                            snapshot.snapshot_ts_ms = now_ms
                            last_log = getattr(self, "_last_snapshot_log_ts", 0)
                            if (time.time() - float(last_log)) >= 30:
                                logger.info(
                                    "[PORTFOLIO_SNAPSHOT] key=%s ok=1 positions=%s longs=%s shorts=%s age_ms=%s",
                                    positions_key,
                                    len(symbols_for_slot_count) if symbols_for_slot_count else len(symbols_with_position),
                                    snapshot.long_slots_used,
                                    snapshot.short_slots_used,
                                    0,
                                )
                                self._last_snapshot_log_ts = time.time()
                        except Exception:
                            pass

                        if snapshot.total_positions > 0:
                            logger.info(f"[PORTFOLIO_POLICY] Loaded {snapshot.total_positions} positions from {positions_key} (account={account_id or 'all'}): "
                                       f"LONG={snapshot.long_slots_used} (${snapshot.long_margin_used:.2f}), "
                                       f"SHORT={snapshot.short_slots_used} (${snapshot.short_margin_used:.2f})")
                            break  # Found positions, don't check other keys
                
                # If no positions found from portfolio:positions keys, try wma:account:positions keys
                if snapshot.total_positions == 0:
                    import json
                    try:
                        for wma_key in self.redis.scan_iter(wma_pattern, count=100):
                            key_str = wma_key.decode() if isinstance(wma_key, bytes) else wma_key
                            # Extract account from key: wma:primary:positions:BTCUSDT
                            parts = key_str.split(':')
                            if len(parts) >= 4:
                                key_account = parts[1]  # 'primary' or 'asjad'
                                
                                # Skip if account filter is set and doesn't match
                                if account_id and key_account != account_id:
                                    continue
                                
                                pos_hash = self.redis.hgetall(key_str)
                                if pos_hash:
                                    # Parse nested JSON from 'short' or 'long' field
                                    for fk, fv in pos_hash.items():
                                        fk_str = fk.decode() if isinstance(fk, bytes) else fk
                                        fv_str = fv.decode() if isinstance(fv, bytes) else fv
                                        
                                        if fk_str.lower() in ('short', 'long'):
                                            try:
                                                pos_data = json.loads(fv_str)
                                                symbol = parts[3] if len(parts) > 3 else pos_data.get('symbol', 'UNKNOWN')
                                                side = fk_str.upper()
                                                size = abs(float(pos_data.get('size', 0) or 0))
                                                
                                                if size > 0 or pos_data.get('has_position', False):
                                                    margin = abs(float(pos_data.get('margin_used', 0) or 0))
                                                    
                                                    snapshot.positions[symbol] = pos_data
                                                    snapshot.total_positions += 1
                                                    
                                                    if side == 'LONG':
                                                        snapshot.long_slots_used += 1
                                                        snapshot.long_margin_used += margin
                                                    elif side == 'SHORT':
                                                        snapshot.short_slots_used += 1
                                                        snapshot.short_margin_used += margin
                                                    
                                                    logger.debug(f"[PORTFOLIO_POLICY] WMA Position: {symbol} {side} margin=${margin:.2f} (account={key_account})")
                                            except Exception as parse_err:
                                                logger.debug(f"[PORTFOLIO_POLICY] Error parsing wma position {key_str}: {parse_err}")
                    except Exception as scan_err:
                        logger.debug(f"[PORTFOLIO_POLICY] Error scanning wma positions: {scan_err}")
                    
                    if snapshot.total_positions > 0:
                        logger.info(f"[PORTFOLIO_POLICY] Loaded {snapshot.total_positions} positions from wma:*:positions (account={account_id or 'all'}): "
                                   f"LONG={snapshot.long_slots_used} (${snapshot.long_margin_used:.2f}), "
                                   f"SHORT={snapshot.short_slots_used} (${snapshot.short_margin_used:.2f})")
                
                # Calculate reserve remaining
                normal_budget = snapshot.equity * self.normal_max_margin_pct
                snapshot.reserve_remaining = max(0, snapshot.equity * self.reserve_pct - max(0, snapshot.total_margin_used - normal_budget))
        
        except Exception as e:
            logger.error(f"[PORTFOLIO_POLICY] Error getting snapshot: {e}")
        
        # Cache per-account snapshot
        setattr(self, f'_cached_{cache_key}', snapshot)
        setattr(self, f'_cached_{cache_key}_ts', now)

        try:
            last_contract_log = getattr(self, '_last_contract_snapshot_log_ts', 0.0)
            if (time.time() - float(last_contract_log)) >= 30.0:
                age_ms = max(0, int(time.time() * 1000) - int(snapshot.snapshot_ts_ms or 0))
                issues = []
                if float(snapshot.equity or 0.0) <= 0.0:
                    issues.append('equity_missing')
                if int(snapshot.snapshot_ts_ms or 0) <= 0:
                    issues.append('timestamp_missing')
                if age_ms > int(self.equity_max_age_ms or 0):
                    issues.append('snapshot_stale')

                self._log_contract(
                    'PORTFOLIO_SNAPSHOT_INCOMPLETE' if issues else 'PORTFOLIO_SNAPSHOT_OK',
                    account=account_id or 'all',
                    equity=f"{float(snapshot.equity or 0.0):.2f}",
                    positions=int(snapshot.total_positions or 0),
                    longs=int(snapshot.long_slots_used or 0),
                    shorts=int(snapshot.short_slots_used or 0),
                    age_ms=age_ms,
                    reasons=','.join(issues) if issues else 'none',
                )
                self._last_contract_snapshot_log_ts = time.time()
        except Exception:
            pass
        
        # Also update legacy cache for backwards compatibility
        self._last_snapshot = snapshot
        self._last_snapshot_ts = now
        
        return snapshot
    
    def check_admission(
        self,
        symbol: str,
        side: str,
        confidence: float,
        margin_required: float,
        action_type: str = "open",
        is_hedge: bool = False,
        account_id: str = None,
        action_category: str = None,
        bypass_portfolio_caps: bool = False,
        signal_source: str = None,
        hedge_necessity_class: int = 0,
        pds: float = 0.0
    ) -> PolicyDecision:
        """
        Check if a new entry/increase is allowed by portfolio policy.
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            confidence: Signal confidence (0.0 - 1.0)
            margin_required: Margin required for this position
            action_type: 'open', 'increase', 'flip_open'
            is_hedge: If True, this is a hedge against existing opposite position
            account_id: Optional account filter ('primary', 'asjad') for per-account slot limits
            action_category: Action category (PROTECTIVE/RECOVERY/HEDGE can bypass caps)
            bypass_portfolio_caps: If True, recovery systems bypass normal caps and use full 85%
            
        Returns:
            PolicyDecision with allowed/blocked status and reason
        """
        from config import ENABLE_PORTFOLIO_POLICY, HEDGE_V2_ENABLED
        
        # Skip if disabled
        if not ENABLE_PORTFOLIO_POLICY:
            return PolicyDecision(allowed=True)
        
        # Get per-account snapshot if account_id specified (each trader has independent caps)
        snapshot = self.get_portfolio_snapshot(force_refresh=True, account_id=account_id)
        decision = PolicyDecision(allowed=True, snapshot=snapshot)
        
        # URC + Hedge Harvest ALWAYS bypass portfolio policy (no-loss critical systems)
        # These systems are essential for protecting positions and must never be blocked
        source_str = str(signal_source or "").lower()
        is_urc_or_harvest = "urc" in source_str or "hedge_harvest" in source_str
        if is_urc_or_harvest or action_category in {"PROTECTIVE", "RECOVERY"}:
            decision.allowed = True
            decision.ultra_mode = True
            decision.hedge_allowed = True
            decision.block_reason = None
            decision.block_detail = f"bypass_allowed | source={source_str} | category={action_category}"
            logger.info(f"🛡️ [PORTFOLIO_POLICY_BYPASS] URC/Harvest/Recovery | {symbol} | {decision.block_detail}")
            return decision

        # Addendum v3: Hedge bypass should be need-based (PDS / necessity class), not blanket.
        try:
            pds_f = float(pds or 0.0)
        except Exception:
            pds_f = 0.0
        try:
            hnc = int(hedge_necessity_class or 0)
        except Exception:
            hnc = 0
        need_based_bypass = bool(is_hedge) and (hnc >= 2 or pds_f >= 0.85)
        if need_based_bypass and action_category in {"HEDGE"}:
            decision.allowed = True
            decision.ultra_mode = True
            decision.hedge_allowed = True
            decision.block_reason = None
            decision.block_detail = f"need_based_bypass | pds={pds_f:.2f} class={hnc}"
            logger.info(f"🛡️ [PORTFOLIO_POLICY_BYPASS] HEDGE need-based | {symbol} | {decision.block_detail}")
            return decision
        
        # Check equity staleness (fail-closed)
        now_ms = int(time.time() * 1000)
        equity_age_ms = now_ms - snapshot.snapshot_ts_ms
        if equity_age_ms > self.equity_max_age_ms or snapshot.equity <= 0:
            decision.allowed = False
            decision.block_reason = PolicyBlockReason.PORTFOLIO_STALE_EQUITY_BLOCK
            decision.block_detail = f"equity_age={equity_age_ms}ms (max={self.equity_max_age_ms}ms), equity={snapshot.equity:.2f}"
            logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
            return decision
        
        # Determine if reserve buffer can be used.
        # - OPEN_RISK: requires ultra-high confidence
        # - HEDGE: allowed to use reserve slice (still capped by ultra_max_margin_pct)
        # - PROTECTIVE/RECOVERY: can bypass caps to use full 85% in emergencies
        is_protective_or_recovery = action_category in {"PROTECTIVE", "RECOVERY", "HEDGE"} if action_category else False
        can_use_reserve = bool(is_hedge) or (confidence >= self.reserve_min_conf) or bool(bypass_portfolio_caps) or is_protective_or_recovery
        # Ultra mode for legacy compatibility (conf >= 0.98)
        is_ultra = confidence >= self.ultra_conf_threshold
        decision.ultra_mode = can_use_reserve
        
        # Check position slot limits - use reserve if confidence allows
        max_total = self.reserve_max_positions if can_use_reserve else self.base_max_positions

        # ------------------------------------------------------------------
        # Diversification slot expansion for ultra-high confidence
        #
        # In cross/multi-asset hedge mode, strict symbol caps can unintentionally
        # block high-conviction diversification entries that are meant to hedge
        # the portfolio (cross-asset) or deploy reserve efficiently.
        #
        # This keeps Jan6 "base max symbols" intact, but allows the configured
        # ultra slot cap when the signal is truly ultra-high confidence.
        # Budgets (25/25/50 + reserve) still apply and remain the primary guardrail.
        # ------------------------------------------------------------------
        if is_ultra:
            try:
                max_total = max(int(max_total), int(self.ultra_max_total_positions))
            except Exception:
                pass
        
        # FIXED: Per-side slots also get +1 buffer for high confidence (>= reserve_min_conf)
        base_max_side = self.max_long_slots if side == 'LONG' else self.max_short_slots
        max_side = base_max_side + 1 if can_use_reserve else base_max_side  # +1 per-side for high confidence
        current_side = snapshot.long_slots_used if side == 'LONG' else snapshot.short_slots_used

        # HEDGE_V2: In hedge-mode, per-side slots MUST NOT be smaller than total-symbol slots.
        # Otherwise hedged books (LONG+SHORT legs across many symbols) look "full" too early and
        # block healthy diversification/participation (common cause of primary-only routing).
        if HEDGE_V2_ENABLED:
            try:
                max_side = max(int(max_side), int(max_total))
            except Exception:
                pass
        
        # Allow if same symbol already has position (increase case)
        #
        # CRITICAL FIX (HEDGE_V2):
        # In hedge-mode, opening the opposite leg for an *existing* symbol is protective and must not
        # be blocked by portfolio slot limits. The snapshot stores a single side per symbol, so
        # hedges often look like a "new position" (e.g., snapshot has SOLUSDT:SHORT and we want OPEN_HEDGE_LONG).
        # Determine per-symbol side presence (handle hedged symbols correctly)
        symbol_in_portfolio = False
        symbol_has_same_side = False
        try:
            ss = getattr(snapshot, "symbol_sides", None)
            if isinstance(ss, dict):
                sides = ss.get(symbol) or set()
                if isinstance(sides, (list, tuple)):
                    sides = {str(x).upper() for x in sides}
                elif isinstance(sides, set):
                    sides = {str(x).upper() for x in sides}
                else:
                    sides = {str(sides).upper()} if sides else set()
                symbol_in_portfolio = len(sides) > 0
                symbol_has_same_side = side in sides
            else:
                symbol_in_portfolio = symbol in snapshot.positions
                symbol_has_same_side = symbol_in_portfolio and str(snapshot.positions[symbol].get('side', '')).upper() == side
        except Exception:
            symbol_in_portfolio = symbol in snapshot.positions
            try:
                symbol_has_same_side = symbol_in_portfolio and str(snapshot.positions[symbol].get('side', '')).upper() == side
            except Exception:
                symbol_has_same_side = False
        symbol_has_position_for_slots = bool(symbol_has_same_side or (is_hedge and symbol_in_portfolio))
        
        if not symbol_has_position_for_slots:
            # Check total slots
            if snapshot.total_positions >= max_total:
                decision.allowed = False
                decision.block_reason = PolicyBlockReason.PORTFOLIO_SLOT_BLOCK
                decision.block_detail = f"total_positions={snapshot.total_positions}/{max_total}, ultra={is_ultra}"
                logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
                return decision
            
            # Check side slots
            if current_side >= max_side:
                decision.allowed = False
                decision.block_reason = PolicyBlockReason.PORTFOLIO_SLOT_BLOCK
                decision.block_detail = f"{side}_slots={current_side}/{max_side}"
                logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
                return decision
        
        # Check side budget
        # Reserve can expand per-side budget by half the reserve (e.g., 30% -> 42.5% when reserve=25%).
        # HIGH-CONFIDENCE BONUS: conf >= 0.90 gets extra 10% per side (30% -> 40%, or 42.5% -> 52.5% with reserve)
        base_side_budget_pct = (self.long_budget_pct if side == 'LONG' else self.short_budget_pct)
        reserve_side_extra_pct = (self.reserve_pct / 2.0) if can_use_reserve else 0.0
        
        # Apply high-confidence budget bonus (0.90+ conf gets extra 10%)
        high_conf_bonus_pct = 0.0
        is_high_conf = confidence >= self.high_conf_threshold
        if is_high_conf:
            high_conf_bonus_pct = float(self.high_conf_budget_bonus_pct)
        
        side_budget = snapshot.equity * (float(base_side_budget_pct) + float(reserve_side_extra_pct) + float(high_conf_bonus_pct))
        side_margin_used = snapshot.long_margin_used if side == 'LONG' else snapshot.short_margin_used
        new_side_margin = side_margin_used + margin_required

        # Enforce side budgets (30%/30% base, +reserve when allowed, +10% for 0.90+ confidence).
        # CRITICAL FIX (Jan 2026): Hedge actions bypass side budget caps entirely.
        # Hedges are risk-reducing and should not be blocked by tight budget constraints.
        if new_side_margin > side_budget:
            if is_hedge:
                # Hedges bypass side budget caps - they reduce directional risk
                logger.info(f"[PORTFOLIO_POLICY] HEDGE_BYPASS_SIDE_BUDGET | {symbol} | {side}_margin=${new_side_margin:.2f} > budget=${side_budget:.2f} - ALLOWED (hedge)")
                # Don't return, continue to total margin check
            else:
                decision.allowed = False
                decision.block_reason = PolicyBlockReason.PORTFOLIO_BUDGET_BLOCK
                bonus_str = f" +high_conf_bonus={high_conf_bonus_pct*100:.0f}%" if is_high_conf else ""
                decision.block_detail = (
                    f"{side}_margin=${new_side_margin:.2f} > budget=${side_budget:.2f} "
                    f"(base={float(base_side_budget_pct)*100:.0f}% reserve={'on' if can_use_reserve else 'off'}{bonus_str})"
                )
                logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
                return decision
        
        # Check total margin budget
        # HEDGE_CAP_FIX (Jan 2026): Hedges should use HEDGE cap (70%), not OPEN cap (50%)
        # This allows protective hedges to deploy when margin is between 50-70%
        if is_hedge:
            try:
                from config import MAX_MARGIN_UTIL_HEDGE_PCT
                hedge_cap_pct = float(MAX_MARGIN_UTIL_HEDGE_PCT) / 100.0  # Convert 70 -> 0.70
            except Exception:
                hedge_cap_pct = 0.70  # Default hedge cap
            max_margin_pct = max(hedge_cap_pct, self.normal_max_margin_pct)  # At least hedge cap
        elif is_ultra:
            max_margin_pct = self.ultra_max_margin_pct
        else:
            max_margin_pct = self.normal_max_margin_pct
        max_total_margin = snapshot.equity * max_margin_pct
        new_total_margin = snapshot.total_margin_used + margin_required
        
        # NOTE: Hedges are still capped by total margin (hedge/ultra), and can use the reserve slice.
        # Operator override (no-loss systems): allow hedges to bypass total margin caps, but rely on
        # hedge sizing governors (trainer-side) to downsize and prevent runaway risk.
        try:
            from config import HEDGE_BYPASS_TOTAL_MARGIN_CAP
            hedge_bypass_total_cap = bool(HEDGE_BYPASS_TOTAL_MARGIN_CAP)
        except Exception:
            hedge_bypass_total_cap = False
        if is_hedge and HEDGE_V2_ENABLED:
            decision.hedge_allowed = True
        
        if new_total_margin > max_total_margin:
            # ------------------------------------------------------------------
            # Reserve-zone micro entry (Jan 2026):
            #
            # When the account is already above the normal total-margin cap but still has
            # real free margin (e.g. ~$300 available), we allow *small* high-confidence
            # entries/increases as long as:
            # - The incremental margin fits inside actual available margin
            # - The resulting total margin remains under the absolute (ultra) cap
            # - Confidence meets MIN_CONF_ENTRY (operator threshold), without requiring 0.97+
            #
            # This fixes the "I have $300 free but zero OPEN_RISK" paradox caused by strict
            # percentage caps when the account is in the 70–85% utilization band.
            # ------------------------------------------------------------------
            try:
                micro_enabled = str(os.getenv("PORTFOLIO_MICRO_ENTRY_RESERVE_ZONE_ENABLED", "1")).strip() == "1"
            except Exception:
                micro_enabled = True

            if micro_enabled and (not is_hedge) and action_type in ("open", "increase", "flip_open"):
                try:
                    from config import MIN_CONF_ENTRY as _MIN_CONF_ENTRY
                    min_conf_entry = float(_MIN_CONF_ENTRY)
                except Exception:
                    min_conf_entry = 0.87

                try:
                    micro_cap_usd = float(os.getenv("PORTFOLIO_MICRO_ENTRY_MAX_MARGIN_USD", "120"))
                except Exception:
                    micro_cap_usd = 120.0
                micro_cap_usd = max(10.0, min(500.0, float(micro_cap_usd)))

                # Estimate available margin from per-account equity snapshot.
                avail_eff = 0.0
                try:
                    rc = getattr(self, "redis", None)
                    aid = str(account_id or "").strip().lower()
                    if rc is not None and aid:
                        import json as _json
                        raw = rc.get(f"portfolio:equity:{aid}")
                        raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                        eqd = _json.loads(raw) if raw else {}
                        wallet = float(eqd.get("wallet_balance_usd") or 0.0)
                        used = float(eqd.get("used_margin_usd") or eqd.get("initial_margin_usd") or 0.0)
                        avail = float(eqd.get("available_margin_usd") or eqd.get("available_balance_usd") or 0.0)
                        avail_calc = max(0.0, wallet - used) if wallet > 0 else 0.0
                        avail_eff = max(avail, avail_calc)
                except Exception:
                    avail_eff = 0.0

                if (
                    float(confidence) >= float(min_conf_entry)
                    and float(margin_required) > 0.0
                    and float(margin_required) <= float(micro_cap_usd)
                    and float(avail_eff) >= float(margin_required)
                    and float(new_total_margin) <= float(snapshot.equity) * float(self.ultra_max_margin_pct)
                ):
                    decision.allowed = True
                    decision.ultra_mode = True
                    decision.block_reason = None
                    decision.block_detail = (
                        f"micro_entry_reserve_zone margin=${float(margin_required):.2f}<=${micro_cap_usd:.2f} "
                        f"avail≈${float(avail_eff):.2f} | total=${new_total_margin:.2f}<=ultra_cap=${(float(snapshot.equity)*float(self.ultra_max_margin_pct)):.2f} "
                        f"conf={float(confidence):.3f}>=min_entry={float(min_conf_entry):.2f}"
                    )
                    logger.warning(f"[PORTFOLIO_POLICY] MICRO_ENTRY_ALLOW | {symbol} | {decision.block_detail}")
                    return decision

            if is_hedge and hedge_bypass_total_cap:
                # Allow hedge to proceed (risk-reducing), even if above cap.
                decision.allowed = True
                decision.block_reason = None
                decision.block_detail = f"hedge_bypass_total_margin_cap new_total=${new_total_margin:.2f} cap=${max_total_margin:.2f}"
                logger.warning(f"[PORTFOLIO_POLICY] HEDGE_BYPASS_TOTAL_MARGIN_CAP | {symbol} | {decision.block_detail}")
                return decision

            # If we're trying to exceed the normal cap without reserve eligibility, emit reserve block.
            if (not can_use_reserve) and (new_total_margin > snapshot.equity * self.normal_max_margin_pct):
                decision.allowed = False
                decision.block_reason = PolicyBlockReason.PORTFOLIO_RESERVE_BLOCK
                decision.block_detail = (
                    f"requires_reserve | margin=${new_total_margin:.2f} | "
                    f"conf={confidence:.3f} < reserve_min_conf={self.reserve_min_conf:.2f} | "
                    f"cap_normal={self.normal_max_margin_pct*100:.0f}% cap_ultra={self.ultra_max_margin_pct*100:.0f}%"
                )
                logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
                return decision

            decision.allowed = False
            decision.block_reason = PolicyBlockReason.PORTFOLIO_TOTAL_MARGIN_BLOCK
            decision.block_detail = f"total_margin=${new_total_margin:.2f} > max=${max_total_margin:.2f} ({max_margin_pct*100:.0f}%)"
            logger.warning(f"[PORTFOLIO_POLICY] {decision.block_reason.value} | {symbol} | {decision.block_detail}")
            return decision
        
        # Allowed
        logger.debug(f"[PORTFOLIO_POLICY] ALLOWED | {symbol} {side} | slots={snapshot.total_positions+1}/{max_total}, "
                    f"side_margin=${new_side_margin:.2f}/${side_budget:.2f}, total=${new_total_margin:.2f}/${max_total_margin:.2f}")
        return decision
    
    def log_snapshot(self):
        """Log current portfolio policy snapshot for telemetry."""
        snapshot = self.get_portfolio_snapshot()
        logger.info(
            f"PORTFOLIO_SNAPSHOT | "
            f"longs={snapshot.long_slots_used}/{self.max_long_slots} | "
            f"shorts={snapshot.short_slots_used}/{self.max_short_slots} | "
            f"total={snapshot.total_positions}/{self.base_max_positions}(+{self.reserve_max_positions - self.base_max_positions}) | "
            f"long_budget_used={snapshot.long_margin_pct:.1f}%/{self.long_budget_pct*100:.0f}% | "
            f"short_budget_used={snapshot.short_margin_pct:.1f}%/{self.short_budget_pct*100:.0f}% | "
            f"total_margin={snapshot.total_margin_pct:.1f}% | "
            f"reserve_min_conf={self.reserve_min_conf:.2f} | "
            f"equity=${snapshot.equity:.2f}"
        )
    
    def get_policy_status(self) -> Dict[str, Any]:
        """Get policy status dict for API/monitoring."""
        snapshot = self.get_portfolio_snapshot()
        return {
            'enabled': True,
            'long_slots_used': snapshot.long_slots_used,
            'long_slots_max': self.max_long_slots,
            'short_slots_used': snapshot.short_slots_used,
            'short_slots_max': self.max_short_slots,
            'total_positions': snapshot.total_positions,
            'total_positions_max': self.max_total_positions,
            'ultra_positions_max': self.ultra_max_total_positions,
            'long_margin_used': snapshot.long_margin_used,
            'long_margin_pct': snapshot.long_margin_pct,
            'long_budget_pct': self.long_budget_pct * 100,
            'short_margin_used': snapshot.short_margin_used,
            'short_margin_pct': snapshot.short_margin_pct,
            'short_budget_pct': self.short_budget_pct * 100,
            'total_margin_used': snapshot.total_margin_used,
            'total_margin_pct': snapshot.total_margin_pct,
            'normal_max_margin_pct': self.normal_max_margin_pct * 100,
            'ultra_max_margin_pct': self.ultra_max_margin_pct * 100,
            'reserve_remaining': snapshot.reserve_remaining,
            'equity': snapshot.equity,
            'snapshot_age_ms': int(time.time() * 1000) - snapshot.snapshot_ts_ms,
        }


# Global singleton instance
_portfolio_policy_manager: Optional[PortfolioPolicyManager] = None


def get_portfolio_policy_manager(redis_client=None) -> PortfolioPolicyManager:
    """Get or create the global PortfolioPolicyManager instance."""
    global _portfolio_policy_manager
    
    if _portfolio_policy_manager is None:
        _portfolio_policy_manager = PortfolioPolicyManager(redis_client=redis_client)
    elif redis_client is not None and _portfolio_policy_manager.redis is None:
        # If singleton exists but has no Redis client, set it now
        _portfolio_policy_manager.redis = redis_client
        logger.info("[PORTFOLIO_POLICY] Attached Redis client to existing manager instance")
    
    return _portfolio_policy_manager


def check_portfolio_admission(
    symbol: str,
    side: str,
    confidence: float,
    margin_required: float,
    action_type: str = "open",
    redis_client=None,
    is_hedge: bool = False,
    account_id: str = None,
    action_category: str = None,
    signal_source: str = None,
    hedge_necessity_class: int = 0,
    pds: float = 0.0
) -> PolicyDecision:
    """
    Convenience function to check portfolio admission.
    
    Args:
        symbol: Trading symbol
        side: LONG or SHORT
        confidence: Signal confidence
        margin_required: Margin needed for this position
        action_type: open, increase, flip
        redis_client: Redis connection
        is_hedge: True if this is a hedge against existing opposite position
        account_id: Optional account filter ('primary', 'asjad') for per-account slot limits
        action_category: Action category (PROTECTIVE/RECOVERY/HEDGE can bypass caps)
        signal_source: Source of the signal (urc*, hedge_harvest* bypass all caps)
    
    Returns PolicyDecision with allowed/blocked status.
    """
    manager = get_portfolio_policy_manager(redis_client)
    return manager.check_admission(
        symbol,
        side,
        confidence,
        margin_required,
        action_type,
        is_hedge=is_hedge,
        account_id=account_id,
        action_category=action_category,
        signal_source=signal_source,
        hedge_necessity_class=hedge_necessity_class,
        pds=pds,
    )

