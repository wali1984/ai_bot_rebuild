"""
Signal Router for Multi-Account Trading
========================================
Routes signals from trainer to account-specific streams
Supports account-specific filtering and routing rules

Flow:
1. Trainer publishes to: wma:signals:all
2. Router reads and routes to: wma:signals:{ACCOUNT_ID}
3. Traders consume from their account-specific streams

Usage:
    python3 trading/signal_router.py
    
    Or with specific accounts:
    ROUTE_ACCOUNTS="primary,brother" python3 trading/signal_router.py
"""
import os
import sys
import time
import json
import logging
import redis
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import get_live_config
from utils.redis_key_audit import wrap_redis_client
from config_accounts import (
    ACCOUNTS, get_account_config, get_enabled_accounts,
    get_risk_limits, get_preferences, validate_account_config
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SignalRouter:
    """
    Routes trading signals from trainer to account-specific streams
    Applies account-specific filtering and risk checks
    """
    
    def __init__(self, account_ids: List[str] = None):
        """
        Initialize signal router
        
        Args:
            account_ids: List of account IDs to route signals to (default: all enabled)
        """
        self.config = get_live_config()
        
        # Initialize Redis connection
        self.redis = redis.Redis(
            host=self.config.REDIS_HOST,
            port=self.config.REDIS_PORT,
            db=self.config.REDIS_DB,
            password=self.config.REDIS_PASSWORD if self.config.REDIS_PASSWORD else None,
            decode_responses=True
        )
        self.redis = wrap_redis_client(self.redis)
        
        # Determine which accounts to route to
        if account_ids:
            self.account_ids = account_ids
        else:
            self.account_ids = get_enabled_accounts()
        
        # Validate accounts
        self._validate_accounts()
        
        # Statistics tracking
        self.total_signals_received = 0
        self.signals_routed = {}  # {account_id: count}
        self.signals_filtered = {}  # {account_id: count}
        self.routing_errors = 0
        
        for account_id in self.account_ids:
            self.signals_routed[account_id] = 0
            self.signals_filtered[account_id] = 0
        
        logger.info("=" * 80)
        logger.info("🚀 SIGNAL ROUTER INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"📌 Routing to accounts: {', '.join(self.account_ids)}")
        logger.info(f"⚡ Redis Connected: {self.redis.ping()}")
        logger.info("=" * 80)
    
    def _validate_accounts(self):
        """Validate all configured accounts"""
        logger.info("Validating account configurations...")
        
        for account_id in self.account_ids:
            is_valid, message = validate_account_config(account_id)
            
            if not is_valid:
                logger.error(f"❌ {account_id}: {message}")
                self.account_ids.remove(account_id)
            else:
                logger.info(f"✅ {account_id}: Configuration valid")
        
        if not self.account_ids:
            raise ValueError("No valid accounts to route signals to")
    
    def should_route_signal(self, signal: Dict[str, Any], account_id: str) -> tuple[bool, str]:
        """
        Determine if signal should be routed to account
        
        Args:
            signal: Signal dictionary
            account_id: Target account ID
        
        Returns:
            Tuple of (should_route, reason)
        """
        config = get_account_config(account_id)
        if not config:
            return False, "Account config not found"
        
        # Check if account is enabled
        if not config.get('enabled', False):
            return False, "Account disabled"
        
        # Get preferences
        prefs = get_preferences(account_id)
        if not prefs:
            return False, "Preferences not found"
        
        # Check minimum confidence
        signal_confidence = signal.get('confidence', 0)
        min_confidence = prefs.get('min_confidence', 0.75)
        
        if signal_confidence < min_confidence:
            return False, f"Confidence {signal_confidence:.2f} below minimum {min_confidence:.2f}"
        
        # Check risk limits
        risk_limits = get_risk_limits(account_id)
        if not risk_limits:
            return False, "Risk limits not found"
        
        # Validate leverage
        signal_leverage = signal.get('leverage', 10)
        max_leverage = risk_limits.get('max_leverage', 20)
        
        if signal_leverage > max_leverage:
            # Adjust leverage to max allowed
            signal['leverage'] = max_leverage
            logger.warning(f"⚠️ {account_id}: Adjusted leverage from {signal_leverage}× to {max_leverage}×")
        
        # Validate position size
        signal_size = signal.get('position_size_pct', 0.1)
        max_size = risk_limits.get('max_position_size_pct', 0.3)
        
        if signal_size > max_size:
            # Adjust position size to max allowed
            signal['position_size_pct'] = max_size
            logger.warning(f"⚠️ {account_id}: Adjusted position size from {signal_size*100:.1f}% to {max_size*100:.1f}%")
        
        return True, "Signal approved"
    
    def route_signal(self, signal: Dict[str, Any]):
        """
        Route signal to all appropriate accounts
        
        Args:
            signal: Signal dictionary from trainer
        """
        self.total_signals_received += 1
        
        signal_id = signal.get('signal_id', 'unknown')
        symbol = signal.get('symbol', 'unknown')
        action = signal.get('action', 'unknown')
        
        logger.info("=" * 80)
        logger.info(f"📨 ROUTING SIGNAL: {signal_id}")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Action: {action}")
        logger.info(f"   Confidence: {signal.get('confidence', 0):.2f}")
        logger.info("=" * 80)
        
        routed_count = 0
        
        for account_id in self.account_ids:
            try:
                # Check if signal should be routed to this account
                should_route, reason = self.should_route_signal(signal.copy(), account_id)
                
                if should_route:
                    # Route to account-specific stream
                    stream_key = f"wma:signals:{account_id}"
                    
                    # Add account_id to signal
                    signal_copy = signal.copy()
                    signal_copy['account_id'] = account_id
                    signal_copy['routed_at'] = time.time()
                    
                    self.redis.xadd(
                        stream_key,
                        {'signal': json.dumps(signal_copy)},
                        maxlen=1000
                    )
                    
                    self.signals_routed[account_id] += 1
                    routed_count += 1
                    
                    logger.info(f"✅ Routed to {account_id}: {reason}")
                else:
                    self.signals_filtered[account_id] += 1
                    logger.info(f"❌ Filtered for {account_id}: {reason}")
            
            except Exception as e:
                self.routing_errors += 1
                logger.error(f"❌ Error routing to {account_id}: {e}")
        
        if routed_count == 0:
            logger.warning(f"⚠️ Signal {signal_id} not routed to any accounts")
        else:
            logger.info(f"✅ Signal {signal_id} routed to {routed_count} account(s)")
    
    def run(self, poll_interval: int = 1):
        """
        Main loop - continuously route signals
        
        Args:
            poll_interval: Seconds between polls (default: 1)
        """
        logger.info("=" * 80)
        logger.info("👂 SIGNAL ROUTER RUNNING")
        logger.info("=" * 80)
        logger.info(f"📡 Source Stream: wma:signals:all")
        logger.info(f"🎯 Target Accounts: {', '.join(self.account_ids)}")
        logger.info(f"🔄 Poll Interval: {poll_interval}s")
        logger.info("=" * 80)
        
        source_stream = "wma:signals:all"
        last_id = '$'  # Start from new messages
        last_stats_report = 0
        
        while True:
            try:
                # Read from all signals stream
                streams = self.redis.xread({source_stream: last_id}, count=10, block=poll_interval * 1000)
                
                if streams:
                    for stream, messages in streams:
                        for message_id, message_data in messages:
                            last_id = message_id
                            
                            # Parse and route signal
                            try:
                                signal = json.loads(message_data.get('signal', '{}'))
                                self.route_signal(signal)
                            except Exception as e:
                                logger.error(f"❌ Failed to process signal: {e}")
                                self.routing_errors += 1
                
                # Periodic stats report (every 5 minutes)
                if time.time() - last_stats_report > 300:
                    self.print_statistics()
                    last_stats_report = time.time()
                
            except KeyboardInterrupt:
                logger.info("👋 Shutting down signal router...")
                break
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(5)
        
        # Print final stats
        self.print_statistics()
        logger.info("✅ Signal router stopped")
    
    def print_statistics(self):
        """Print routing statistics"""
        logger.info("=" * 80)
        logger.info("📊 SIGNAL ROUTING STATISTICS")
        logger.info("=" * 80)
        logger.info(f"📨 Total Signals Received: {self.total_signals_received}")
        logger.info(f"❌ Routing Errors: {self.routing_errors}")
        logger.info("")
        logger.info("Per-Account Statistics:")
        
        for account_id in self.account_ids:
            routed = self.signals_routed.get(account_id, 0)
            filtered = self.signals_filtered.get(account_id, 0)
            total = routed + filtered
            
            if total > 0:
                route_pct = (routed / total) * 100
            else:
                route_pct = 0
            
            logger.info(f"  {account_id}:")
            logger.info(f"    ✅ Routed: {routed}")
            logger.info(f"    ❌ Filtered: {filtered}")
            logger.info(f"    📊 Route Rate: {route_pct:.1f}%")
        
        logger.info("=" * 80)


def main():
    """Main entry point"""
    # Get account IDs from environment or use all enabled
    account_ids_str = os.getenv("ROUTE_ACCOUNTS", "")
    
    if account_ids_str:
        account_ids = [aid.strip() for aid in account_ids_str.split(',')]
    else:
        account_ids = None  # Will use all enabled accounts
    
    # Get poll interval
    poll_interval = int(os.getenv("POLL_INTERVAL", "1"))
    
    logger.info("=" * 80)
    logger.info("🚀 STARTING SIGNAL ROUTER")
    logger.info("=" * 80)
    
    if account_ids:
        logger.info(f"📌 Target Accounts: {', '.join(account_ids)}")
    else:
        logger.info(f"📌 Target Accounts: All enabled")
    
    logger.info(f"🔄 Poll Interval: {poll_interval}s")
    logger.info("=" * 80)
    
    try:
        router = SignalRouter(account_ids=account_ids)
        router.run(poll_interval=poll_interval)
    except KeyboardInterrupt:
        logger.info("👋 Signal router stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
