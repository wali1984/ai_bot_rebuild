"""
Portfolio State Service for Hedge Recovery
Aggregates live positions/balances with account tags

Features:
- Read positions from Binance futures account
- Maintain symbol→{long_qty, short_qty, net} view for hedge mode
- Cache in Redis for trainer and trader access
- Support portfolio-aware feature inputs
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import redis

# Binance imports
try:
    from binance.client import Client as BinanceClient
    from binance.exceptions import BinanceAPIException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False

from utils.logger import get_logger
from utils.redis_client import get_redis

logger = get_logger("portfolio_state")


class AccountType(Enum):
    """Account type for tagging positions"""
    LIVE = "live"


@dataclass
class PositionState:
    """Individual position state for a symbol"""
    symbol: str
    side: str  # "LONG" or "SHORT" 
    size: float  # Position size (quantity)
    notional: float  # Position notional value (USD)
    entry_price: float  # Average entry price
    mark_price: float  # Current mark price
    unrealized_pnl: float  # Unrealized PnL
    pnl_percentage: float  # PnL as percentage
    margin_type: str  # "isolated" or "cross"
    leverage: float  # Current leverage
    account_type: AccountType  # Which account this position is from
    last_update: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        d = asdict(self)
        d['account_type'] = self.account_type.value
        d['last_update'] = self.last_update.isoformat()
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PositionState':
        """Create from Redis dictionary"""
        data['account_type'] = AccountType(data['account_type'])
        data['last_update'] = datetime.fromisoformat(data['last_update'])
        return cls(**data)


@dataclass
class SymbolHedgeView:
    """Hedge view for a symbol showing long + short positions"""
    symbol: str
    long_qty: float  # Total long quantity across accounts
    short_qty: float  # Total short quantity across accounts  
    net_qty: float  # Net position (long_qty - short_qty)
    long_notional: float  # Long notional value
    short_notional: float  # Short notional value
    net_notional: float  # Net notional exposure
    long_pnl: float  # Unrealized PnL from long positions
    short_pnl: float  # Unrealized PnL from short positions
    total_pnl: float  # Total unrealized PnL
    is_hedged: bool  # True if both long and short positions exist
    accounts: List[AccountType]  # Which accounts have positions
    last_update: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        d = asdict(self)
        d['accounts'] = [acc.value for acc in self.accounts]
        d['last_update'] = self.last_update.isoformat()
        return d
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SymbolHedgeView':
        """Create from Redis dictionary"""
        data['accounts'] = [AccountType(acc) for acc in data['accounts']]
        data['last_update'] = datetime.fromisoformat(data['last_update'])
        return cls(**data)


@dataclass 
class PortfolioSummary:
    """Overall portfolio state summary"""
    total_balance: float  # Total balance across accounts (USDT)
    free_margin: float  # Available margin
    used_margin: float  # Used margin
    total_pnl: float  # Total unrealized PnL
    daily_pnl: float  # PnL since start of day
    total_exposure: float  # Total notional exposure
    num_positions: int  # Number of open positions
    num_symbols: int  # Number of symbols with positions
    num_hedged_symbols: int  # Number of symbols with both long+short
    max_symbols_allowed: int  # Current max symbols (3 base, 5 boosted)
    leverage_used: float  # Effective leverage ratio
    accounts_active: List[AccountType]  # Which accounts are active
    last_update: datetime


class PortfolioStateService:
    """
    Centralized portfolio state management for hedge recovery.
    
    Responsibilities:
    - Query positions from Binance futures account
    - Merge into unified hedge view per symbol
    - Cache in Redis with TTL for fast access
    - Provide portfolio-aware features for model input
    """
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        cache_ttl: int = 30,  # Cache TTL in seconds
        max_symbols_base: int = 3,
        max_symbols_boosted: int = 5
    ):
        """
        Initialize portfolio state service.
        
        Args:
            redis_client: Redis client for caching
            cache_ttl: Cache time-to-live in seconds
            max_symbols_base: Base max symbols limit
            max_symbols_boosted: Boosted max symbols limit
        """
        self.redis = redis_client or get_redis()
        self.cache_ttl = cache_ttl
        self.max_symbols_base = max_symbols_base
        self.max_symbols_boosted = max_symbols_boosted
        
        # Initialize Binance client
        self.mainnet_client = None
        self._initialize_clients()
        
        # Cache keys
        self.positions_key = "portfolio_state:positions"
        self.hedge_view_key = "portfolio_state:hedge_view"
        self.summary_key = "portfolio_state:summary"
        
        logger.info(f"✅ PortfolioStateService initialized - Cache TTL: {cache_ttl}s, Max symbols: {max_symbols_base}/{max_symbols_boosted}")
    
    def _initialize_clients(self):
        """Initialize Binance client (live only)"""
        if not BINANCE_AVAILABLE:
            logger.warning("⚠️ Binance client not available - portfolio state will use mock data")
            return
            
        import os
        
        live_key = os.getenv('BINANCE_API_KEY')
        live_secret = os.getenv('BINANCE_API_SECRET')
        if live_key and live_secret:
            try:
                self.mainnet_client = BinanceClient(
                    api_key=live_key,
                    api_secret=live_secret,
                )
                logger.info("✅ Binance client initialized (live)")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Binance client: {e}")
    
    async def get_positions(self, force_refresh: bool = False) -> Dict[str, PositionState]:
        """
        Get all positions from Binance futures (live).
        
        Args:
            force_refresh: Force refresh from API (bypass cache)
            
        Returns:
            Dict mapping position_id -> PositionState
        """
        # Check cache first
        if not force_refresh:
            cached = self._get_cached_positions()
            if cached:
                return cached
        
        # Fetch fresh data from API
        all_positions = {}

        if self.mainnet_client:
            try:
                mainnet_positions = await self._fetch_mainnet_positions()
                all_positions.update(mainnet_positions)
            except Exception as e:
                logger.error(f"❌ Failed to fetch mainnet positions: {e}")
        
        # Cache results
        self._cache_positions(all_positions)
        
        return all_positions
    
    def get_balance(self) -> Dict[str, float]:
        """
        Get merged balance across accounts.
        
        Returns:
            Dict with balance information
        """
        # NOTE: This service is currently position-focused; balance aggregation can be added if needed.
        # For now, return mock data.
        return {
            'total_balance': 10000.0,
            'free_margin': 8000.0,
            'used_margin': 2000.0
        }
    
    async def get_hedge_view(self, force_refresh: bool = False) -> Dict[str, SymbolHedgeView]:
        """
        Get hedge view of positions per symbol.
        
        Args:
            force_refresh: Force refresh from API
            
        Returns:
            Dict mapping symbol -> SymbolHedgeView
        """
        # Check cache first
        if not force_refresh:
            cached = self._get_cached_hedge_view()
            if cached:
                return cached
        
        # Get all positions
        positions = await self.get_positions(force_refresh)
        
        # Group by symbol and create hedge views
        symbol_positions = {}
        for pos_id, position in positions.items():
            symbol = position.symbol
            if symbol not in symbol_positions:
                symbol_positions[symbol] = []
            symbol_positions[symbol].append(position)
        
        # Create hedge views
        hedge_views = {}
        for symbol, symbol_pos_list in symbol_positions.items():
            hedge_view = self._create_symbol_hedge_view(symbol, symbol_pos_list)
            hedge_views[symbol] = hedge_view
        
        # Cache results
        self._cache_hedge_view(hedge_views)
        
        return hedge_views
    
    def get_exposure_by_symbol(self) -> Dict[str, float]:
        """
        Get total exposure (notional) per symbol.
        
        Returns:
            Dict mapping symbol -> total_notional_exposure
        """
        # This would be implemented to return exposure from hedge view
        # For now, return mock data
        return {
            'BTCUSDT': 5000.0,
            'ETHUSDT': 3000.0,
            'SOLUSDT': 2000.0
        }
    
    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Get overall portfolio summary"""
        hedge_views = await self.get_hedge_view()
        balance = self.get_balance()
        
        # Calculate summary metrics
        total_pnl = sum(hv.total_pnl for hv in hedge_views.values())
        total_exposure = sum(abs(hv.net_notional) for hv in hedge_views.values())
        num_positions = sum(1 for hv in hedge_views.values() if hv.net_qty != 0)
        num_hedged = sum(1 for hv in hedge_views.values() if hv.is_hedged)
        
        return PortfolioSummary(
            total_balance=balance['total_balance'],
            free_margin=balance['free_margin'],
            used_margin=balance['used_margin'],
            total_pnl=total_pnl,
            daily_pnl=0.0,  # TODO: Calculate daily PnL
            total_exposure=total_exposure,
            num_positions=num_positions,
            num_symbols=len(hedge_views),
            num_hedged_symbols=num_hedged,
            max_symbols_allowed=self.max_symbols_base,  # TODO: Apply boost logic
            leverage_used=total_exposure / balance['total_balance'] if balance['total_balance'] > 0 else 0,
            accounts_active=[AccountType.LIVE],  # TODO: Detect active accounts
            last_update=datetime.now()
        )
    
    async def _fetch_mainnet_positions(self) -> Dict[str, PositionState]:
        """Fetch positions from Binance futures (live)"""
        if not self.mainnet_client:
            return {}
        try:
            account_info = self.mainnet_client.futures_account()
            positions: Dict[str, PositionState] = {}

            for pos in account_info.get('positions', []) or []:
                try:
                    amt = float(pos.get('positionAmt', 0) or 0)
                except Exception:
                    amt = 0.0
                if amt == 0.0:
                    continue

                symbol = pos.get('symbol')
                side = pos.get('positionSide') or ('LONG' if amt > 0 else 'SHORT')
                position_id = f"live_{symbol}_{side}"

                # Some fields may not exist depending on endpoint/version; use safe defaults.
                positions[position_id] = PositionState(
                    symbol=symbol,
                    side=str(side).upper(),
                    size=abs(amt),
                    notional=float(pos.get('notional', 0) or 0),
                    entry_price=float(pos.get('entryPrice', 0) or 0),
                    mark_price=float(pos.get('markPrice', 0) or 0),
                    unrealized_pnl=float(pos.get('unRealizedProfit', pos.get('unrealizedProfit', 0)) or 0),
                    pnl_percentage=float(pos.get('percentage', 0) or 0),
                    margin_type=str(pos.get('marginType', 'cross') or 'cross'),
                    leverage=float(pos.get('leverage', 1) or 1),
                    account_type=AccountType.LIVE,
                    last_update=datetime.now()
                )

            return positions
        except Exception as e:
            logger.error(f"❌ Error fetching live positions: {e}")
            return {}
    
    def _create_symbol_hedge_view(self, symbol: str, positions: List[PositionState]) -> SymbolHedgeView:
        """Create hedge view for a symbol from its positions"""
        long_qty = sum(pos.size for pos in positions if pos.side == 'LONG')
        short_qty = sum(abs(pos.size) for pos in positions if pos.side == 'SHORT')
        
        long_notional = sum(pos.notional for pos in positions if pos.side == 'LONG')
        short_notional = sum(abs(pos.notional) for pos in positions if pos.side == 'SHORT')
        
        long_pnl = sum(pos.unrealized_pnl for pos in positions if pos.side == 'LONG')
        short_pnl = sum(pos.unrealized_pnl for pos in positions if pos.side == 'SHORT')
        
        return SymbolHedgeView(
            symbol=symbol,
            long_qty=long_qty,
            short_qty=short_qty,
            net_qty=long_qty - short_qty,
            long_notional=long_notional,
            short_notional=short_notional,
            net_notional=long_notional - short_notional,
            long_pnl=long_pnl,
            short_pnl=short_pnl,
            total_pnl=long_pnl + short_pnl,
            is_hedged=(long_qty > 0 and short_qty > 0),
            accounts=list(set(pos.account_type for pos in positions)),
            last_update=datetime.now()
        )
    
    def _get_cached_positions(self) -> Optional[Dict[str, PositionState]]:
        """Get positions from Redis cache"""
        try:
            cached_data = self.redis.get(self.positions_key)
            if cached_data:
                data = json.loads(cached_data)
                return {k: PositionState.from_dict(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"❌ Error reading cached positions: {e}")
        return None
    
    def _cache_positions(self, positions: Dict[str, PositionState]):
        """Cache positions in Redis"""
        try:
            data = {k: v.to_dict() for k, v in positions.items()}
            self.redis.setex(
                self.positions_key,
                self.cache_ttl,
                json.dumps(data, default=str)
            )
        except Exception as e:
            logger.error(f"❌ Error caching positions: {e}")
    
    def _get_cached_hedge_view(self) -> Optional[Dict[str, SymbolHedgeView]]:
        """Get hedge view from Redis cache"""
        try:
            cached_data = self.redis.get(self.hedge_view_key)
            if cached_data:
                data = json.loads(cached_data)
                return {k: SymbolHedgeView.from_dict(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"❌ Error reading cached hedge view: {e}")
        return None
    
    def _cache_hedge_view(self, hedge_views: Dict[str, SymbolHedgeView]):
        """Cache hedge view in Redis"""
        try:
            data = {k: v.to_dict() for k, v in hedge_views.items()}
            self.redis.setex(
                self.hedge_view_key,
                self.cache_ttl,
                json.dumps(data, default=str)
            )
        except Exception as e:
            logger.error(f"❌ Error caching hedge view: {e}")


# Global instance for easy access
_portfolio_service = None


def get_portfolio_service() -> PortfolioStateService:
    """Get global portfolio service instance"""
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = PortfolioStateService()
    return _portfolio_service


# Utility functions for quick access
async def get_current_positions() -> Dict[str, PositionState]:
    """Quick access to current positions"""
    service = get_portfolio_service()
    return await service.get_positions()


async def get_symbol_hedge_status(symbol: str) -> Optional[SymbolHedgeView]:
    """Get hedge status for a specific symbol"""
    service = get_portfolio_service()
    hedge_views = await service.get_hedge_view()
    return hedge_views.get(symbol)


def is_symbol_hedged(symbol: str) -> bool:
    """Check if symbol has both long and short positions"""
    # Sync wrapper - would use asyncio.run in practice
    # For now, return False (implement proper async handling later)
    return False


def get_portfolio_features() -> Dict[str, float]:
    """
    Get portfolio state as feature vector for model input.
    
    Returns:
        Dict with portfolio features for ML model
    """
    # This will be implemented to return features like:
    # - total_balance, free_margin, used_margin
    # - total_pnl, daily_pnl, drawdown
    # - num_positions, num_symbols, leverage_used
    # - per-symbol exposure, pnl, hedge status
    
    # For now, return mock features
    return {
        'total_balance': 10000.0,
        'free_margin_ratio': 0.8,
        'total_pnl_pct': 0.05,
        'num_positions': 3,
        'num_symbols': 2,
        'leverage_used': 2.5,
        'is_any_hedged': 0.0,
        'daily_pnl_pct': 0.01
    }