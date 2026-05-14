"""
Position Reporter for WMA AI Bot
=================================
Aggregates position data from all traders and publishes to Redis for trainer consumption
Provides real-time visibility into execution state across all accounts

Responsibilities:
- Subscribe to position updates from all traders
- Aggregate position state across accounts
- Publish formatted data for trainer
- Track price feeds for real-time P&L
- Monitor execution lag and slippage
"""
import os
import sys
import time
import json
import logging
import redis
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_live_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PositionReporter:
    """
    Aggregates and reports position state from all traders to trainer
    """
    
    def __init__(self, account_ids: List[str] = None):
        """
        Initialize position reporter
        
        Args:
            account_ids: List of account IDs to monitor (default: ['primary', 'asjad'])
        """
        self.config = get_live_config()
        
        # Default account IDs if not provided
        self.account_ids = account_ids or ['primary', 'asjad']
        
        # Initialize Redis connection
        self.redis = redis.Redis(
            host=self.config.REDIS_HOST,
            port=self.config.REDIS_PORT,
            db=self.config.REDIS_DB,
            password=self.config.REDIS_PASSWORD if self.config.REDIS_PASSWORD else None,
            decode_responses=True
        )
        
        # State tracking
        self.positions = defaultdict(dict)  # {account_id: {symbol: position_data}}
        self.balances = {}  # {account_id: balance_data}
        self.fills = defaultdict(list)  # {account_id: [fill_data]}
        self.prices = {}  # {symbol: current_price}
        
        # Performance tracking
        self.last_update = {}  # {account_id: timestamp}
        self.update_count = defaultdict(int)
        
        logger.info("=" * 80)
        logger.info("🚀 POSITION REPORTER INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"📌 Monitoring Accounts: {', '.join(self.account_ids)}")
        logger.info(f"⚡ Redis Connected: {self.redis.ping()}")
        logger.info("=" * 80)
    
    def get_redis_key(self, account_id: str, key_type: str, *args) -> str:
        """Generate Redis key with account namespacing"""
        key_parts = ["wma", account_id, key_type] + list(args)
        return ":".join(str(part) for part in key_parts)
    
    def subscribe_to_positions(self, account_id: str):
        """
        Subscribe to position updates from a trader
        
        Reads from: wma:{account_id}:positions:{symbol}
        """
        try:
            pattern = f"wma:{account_id}:positions:*"
            keys = self.redis.keys(pattern)
            
            for key in keys:
                try:
                    position_data = self.redis.get(key)
                    if position_data:
                        position = json.loads(position_data)
                        symbol = position.get('symbol')
                        
                        if symbol:
                            self.positions[account_id][symbol] = position
                            self.update_count[account_id] += 1
                            
                except Exception as e:
                    logger.error(f"Error reading position from {key}: {e}")
            
            # Update last update time
            if keys:
                self.last_update[account_id] = time.time()
            
        except Exception as e:
            logger.error(f"Error subscribing to positions for {account_id}: {e}")
    
    def subscribe_to_balances(self, account_id: str):
        """
        Subscribe to balance updates from a trader
        
        Reads from: wma:{account_id}:balance
        """
        try:
            key = self.get_redis_key(account_id, "balance")
            balance_data = self.redis.get(key)
            
            if balance_data:
                balance = json.loads(balance_data)
                self.balances[account_id] = balance
                
        except Exception as e:
            logger.error(f"Error subscribing to balance for {account_id}: {e}")
    
    def subscribe_to_fills(self, account_id: str):
        """
        Subscribe to fill updates from a trader
        
        Reads from: wma:{account_id}:fills stream
        """
        try:
            stream_key = self.get_redis_key(account_id, "fills")
            
            # Read recent fills (last 100)
            fills = self.redis.xrevrange(stream_key, count=100)
            
            fill_list = []
            for fill_id, fill_data in fills:
                try:
                    fill = json.loads(fill_data.get('fill', '{}'))
                    fill['fill_id'] = fill_id
                    fill_list.append(fill)
                except Exception as e:
                    logger.error(f"Error parsing fill: {e}")
            
            self.fills[account_id] = fill_list
            
        except Exception as e:
            logger.error(f"Error subscribing to fills for {account_id}: {e}")
    
    def subscribe_to_prices(self):
        """
        Subscribe to real-time price feeds
        
        Reads from: wma:price:{symbol}
        """
        try:
            # Get all unique symbols from all positions
            symbols = set()
            for account_positions in self.positions.values():
                symbols.update(account_positions.keys())
            
            # Get current prices
            for symbol in symbols:
                try:
                    key = f"wma:price:{symbol}"
                    price_data = self.redis.get(key)
                    
                    if price_data:
                        price_info = json.loads(price_data)
                        self.prices[symbol] = price_info.get('price', 0)
                except Exception as e:
                    logger.error(f"Error getting price for {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error subscribing to prices: {e}")
    
    def calculate_aggregated_state(self) -> Dict[str, Any]:
        """
        Calculate aggregated state across all accounts
        
        Returns:
            Dictionary with aggregated position and balance data
        """
        total_equity = 0
        total_unrealized_pnl = 0
        total_positions = 0
        position_distribution = defaultdict(int)  # {symbol: count}
        
        account_states = {}
        
        for account_id in self.account_ids:
            # Get balance
            balance = self.balances.get(account_id, {})
            account_balance = balance.get('balance', 0)
            account_unrealized_pnl = balance.get('unrealized_pnl', 0)
            
            total_equity += account_balance
            total_unrealized_pnl += account_unrealized_pnl
            
            # Get positions
            account_positions = self.positions.get(account_id, {})
            account_position_count = len([p for p in account_positions.values() if p.get('size', 0) > 0])
            total_positions += account_position_count
            
            # Count positions by symbol
            for symbol, position in account_positions.items():
                if position.get('size', 0) > 0:
                    position_distribution[symbol] += 1
            
            # Store account state
            account_states[account_id] = {
                'balance': account_balance,
                'unrealized_pnl': account_unrealized_pnl,
                'position_count': account_position_count,
                'positions': account_positions,
                'last_update': self.last_update.get(account_id, 0)
            }
        
        return {
            'timestamp': time.time(),
            'total_equity': total_equity,
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_positions': total_positions,
            'position_distribution': dict(position_distribution),
            'accounts': account_states
        }
    
    def publish_to_trainer(self, aggregated_state: Dict[str, Any]):
        """
        Publish aggregated state to trainer
        
        Publishes to: wma:trainer:positions:all
        """
        try:
            key = "wma:trainer:positions:all"
            self.redis.setex(
                key,
                300,  # 5 minute expiry
                json.dumps(aggregated_state)
            )
            
            logger.debug(f"📤 Published aggregated state to trainer")
            
        except Exception as e:
            logger.error(f"Error publishing to trainer: {e}")
    
    def publish_account_state(self, account_id: str):
        """
        Publish individual account state to trainer
        
        Publishes to: wma:trainer:positions:{account_id}
        """
        try:
            account_positions = self.positions.get(account_id, {})
            balance = self.balances.get(account_id, {})
            
            state = {
                'account_id': account_id,
                'timestamp': time.time(),
                'balance': balance,
                'positions': account_positions,
                'position_count': len([p for p in account_positions.values() if p.get('size', 0) > 0])
            }
            
            key = f"wma:trainer:positions:{account_id}"
            self.redis.setex(
                key,
                300,
                json.dumps(state)
            )
            
        except Exception as e:
            logger.error(f"Error publishing account state for {account_id}: {e}")
    
    def get_execution_lag(self, account_id: str) -> float:
        """
        Calculate execution lag (time since last update)
        
        Returns:
            Lag in seconds
        """
        last_update = self.last_update.get(account_id, 0)
        if last_update == 0:
            return float('inf')
        
        return time.time() - last_update
    
    def check_health(self) -> Dict[str, Any]:
        """
        Check health of all monitored accounts
        
        Returns:
            Health status for each account
        """
        health = {}
        
        for account_id in self.account_ids:
            lag = self.get_execution_lag(account_id)
            
            status = "healthy"
            if lag > 60:
                status = "stale"
            elif lag > 300:
                status = "offline"
            
            health[account_id] = {
                'status': status,
                'lag_seconds': lag,
                'update_count': self.update_count[account_id],
                'position_count': len(self.positions.get(account_id, {}))
            }
        
        return health
    
    def run(self, update_interval: int = 5):
        """
        Main loop - continuously update and publish position state
        
        Args:
            update_interval: Seconds between updates (default: 5)
        """
        logger.info("=" * 80)
        logger.info("👂 POSITION REPORTER RUNNING")
        logger.info("=" * 80)
        logger.info(f"📊 Monitoring: {', '.join(self.account_ids)}")
        logger.info(f"🔄 Update Interval: {update_interval}s")
        logger.info("=" * 80)
        
        last_health_check = 0
        
        while True:
            try:
                # Subscribe to all data sources
                for account_id in self.account_ids:
                    self.subscribe_to_positions(account_id)
                    self.subscribe_to_balances(account_id)
                    self.subscribe_to_fills(account_id)
                
                # Subscribe to prices
                self.subscribe_to_prices()
                
                # Calculate aggregated state
                aggregated_state = self.calculate_aggregated_state()
                
                # Publish to trainer
                self.publish_to_trainer(aggregated_state)
                
                # Publish individual account states
                for account_id in self.account_ids:
                    self.publish_account_state(account_id)
                
                # Periodic health check (every 60 seconds)
                if time.time() - last_health_check > 60:
                    health = self.check_health()
                    
                    logger.info("=" * 80)
                    logger.info("💊 HEALTH CHECK")
                    logger.info("=" * 80)
                    
                    for account_id, status in health.items():
                        logger.info(f"📌 {account_id}:")
                        logger.info(f"   Status: {status['status']}")
                        logger.info(f"   Lag: {status['lag_seconds']:.1f}s")
                        logger.info(f"   Updates: {status['update_count']}")
                        logger.info(f"   Positions: {status['position_count']}")
                    
                    logger.info("=" * 80)
                    logger.info(f"📊 Total Equity: ${aggregated_state['total_equity']:,.2f}")
                    logger.info(f"📊 Total Positions: {aggregated_state['total_positions']}")
                    logger.info(f"📊 Unrealized P&L: ${aggregated_state['total_unrealized_pnl']:,.2f}")
                    logger.info("=" * 80)
                    
                    last_health_check = time.time()
                
                # Sleep until next update
                time.sleep(update_interval)
                
            except KeyboardInterrupt:
                logger.info("👋 Shutting down position reporter...")
                break
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(update_interval)
        
        logger.info("✅ Position reporter stopped")


def main():
    """Main entry point"""
    # Get account IDs from environment or use defaults
    account_ids_str = os.getenv("MONITOR_ACCOUNTS", "primary,asjad")
    account_ids = [aid.strip() for aid in account_ids_str.split(',')]
    
    # Get update interval
    update_interval = int(os.getenv("UPDATE_INTERVAL", "5"))
    
    logger.info("=" * 80)
    logger.info("🚀 STARTING POSITION REPORTER")
    logger.info("=" * 80)
    logger.info(f"📌 Monitoring Accounts: {', '.join(account_ids)}")
    logger.info(f"🔄 Update Interval: {update_interval}s")
    logger.info("=" * 80)
    
    try:
        reporter = PositionReporter(account_ids=account_ids)
        reporter.run(update_interval=update_interval)
    except KeyboardInterrupt:
        logger.info("👋 Position reporter stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
