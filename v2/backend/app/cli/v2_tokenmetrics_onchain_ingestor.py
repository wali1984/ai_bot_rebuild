#!/usr/bin/env python3
"""Phase C Day 2: TokenMetrics On-Chain Analytics Ingestor

Whale tracking, dev activity, social sentiment, exchange flows.
Feeds 18 on-chain metrics into v2 feature pipeline.

Output: Redis v2:onchain:tokenmetrics:{symbol}
  - Whale accumulation/distribution (4 fields)
  - Exchange inflows/outflows (3 fields)
  - Development activity (3 fields)
  - Social sentiment (3 fields)
  - Network metrics (5 fields)

Integration: Feature builder reads v2:onchain:tokenmetrics:* keys
             and includes in consolidated v2:features:latest:*

Update frequency: 5-60 minutes (TokenMetrics rate limits)
TTL: 3600 seconds (1 hour, since data is slower)

Fail-closed default: this file must not publish simulated/random on-chain data
into actual runtime feature keys. Use --allow-synthetic only for local/manual
tests; synthetic data is written to v2:onchain:tokenmetrics:synthetic:{symbol}.
"""

import json, logging, time, signal, sys, random
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = {
    'BTC': 'Bitcoin',
    'ETH': 'Ethereum', 
    'BNB': 'Binance Coin',
    'SOL': 'Solana',
    'XRP': 'Ripple',
    'ADA': 'Cardano',
    'DOGE': 'Dogecoin',
    'MATIC': 'Polygon',
    'LINK': 'Chainlink',
    'AVAX': 'Avalanche',
}

REDIS_URL = "redis://localhost:6379/0"
TTL_SECONDS = 3600  # 1 hour (slower update rate than orderbook)
REQUIRED_TOKENMETRICS_FIELDS = (
    "whale_transactions_24h",
    "large_tx_volume_usd",
    "whale_ratio",
    "accumulation_score",
    "exchange_inflow_24h",
    "exchange_outflow_24h",
    "dev_commits_30d",
    "dev_activity_score",
    "developers_active",
    "social_sentiment_twitter",
    "social_volume_24h",
    "active_addresses_24h",
    "transaction_count_24h",
    "concentration_index",
    "token_velocity",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OnChainMetricsCalculator:
    """Calculate 18 on-chain metrics from TokenMetrics data."""

    def calculate_metrics(self, symbol_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Calculate on-chain metrics.
        
        18 fields:
        - Whale metrics (4)
        - Exchange flow (3)
        - Development (3)
        - Social sentiment (3)
        - Network metrics (5)
        """
        metrics = {}
        
        try:
            missing = [
                field
                for field in REQUIRED_TOKENMETRICS_FIELDS
                if symbol_data.get(field) is None
            ]
            if missing:
                logger.warning(f"Missing TokenMetrics fields: {missing}")
                return {}

            def value(field: str) -> float:
                return float(symbol_data[field])

            # 1. Whale Accumulation/Distribution (4 fields)
            metrics['whale_transactions_24h'] = value('whale_transactions_24h')
            metrics['large_tx_volume_usd'] = value('large_tx_volume_usd')
            metrics['whale_ratio'] = value('whale_ratio')
            metrics['accumulation_score'] = value('accumulation_score')
            
            # 2. Exchange Inflows/Outflows (3 fields)
            metrics['exchange_inflow_24h'] = value('exchange_inflow_24h')
            metrics['exchange_outflow_24h'] = value('exchange_outflow_24h')
            
            # Net flow: negative = accumulation, positive = distribution
            inflow = metrics['exchange_inflow_24h']
            outflow = metrics['exchange_outflow_24h']
            if inflow + outflow > 0:
                metrics['exchange_netflow_pct'] = ((outflow - inflow) / (inflow + outflow)) * 100
            else:
                metrics['exchange_netflow_pct'] = 0
            
            # 3. Development Activity (3 fields)
            metrics['dev_commits_30d'] = value('dev_commits_30d')
            metrics['dev_activity_score'] = value('dev_activity_score')
            metrics['developers_active'] = value('developers_active')
            
            # 4. Social Sentiment (3 fields)
            metrics['social_sentiment_twitter'] = value('social_sentiment_twitter')
            metrics['social_volume_24h'] = value('social_volume_24h')
            
            # Sentiment composite
            sentiment = metrics['social_sentiment_twitter']
            volume = min(metrics['social_volume_24h'] / 10000, 1.0)  # Normalize volume
            metrics['social_sentiment_composite'] = (sentiment * 0.7) + (volume * 0.3)
            
            # 5. Network Metrics (5 fields)
            metrics['active_addresses_24h'] = value('active_addresses_24h')
            metrics['transaction_count_24h'] = value('transaction_count_24h')
            
            # Transaction velocity (change from baseline)
            baseline_tx = 100000
            actual_tx = metrics['transaction_count_24h']
            metrics['tx_velocity_change_pct'] = ((actual_tx - baseline_tx) / baseline_tx) * 100
            
            # Token concentration (Gini coefficient proxy)
            metrics['concentration_index'] = value('concentration_index')
            
            # Token velocity (how many times token changes hands)
            metrics['token_velocity'] = value('token_velocity')
            
            # Timestamp
            metrics['timestamp'] = _utc_iso()
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating on-chain metrics: {e}")
            return {}


class TokenMetricsIngestor:
    """Fetch on-chain metrics from TokenMetrics (or simulated data)."""

    def __init__(self, redis_url: str = REDIS_URL, *, allow_synthetic: bool = False):
        self.redis_url = redis_url
        self.allow_synthetic = allow_synthetic
        self.redis = None
        self.calc = OnChainMetricsCalculator()
        self.connect()

    def connect(self) -> bool:
        """Connect to Redis"""
        try:
            parts = self.redis_url.replace("redis://", "").split(":")
            host = parts[0] if parts else "localhost"
            port = int(parts[1].split('/')[0]) if len(parts) > 1 else 6379
            
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=0,
                decode_responses=True,
                socket_connect_timeout=5
            )
            self.redis.ping()
            logger.info(f"✅ Connected to Redis: {host}:{port}")
            return True
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return False

    def fetch_onchain_data(self, symbol: str, symbol_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch on-chain data from TokenMetrics API.
        
        In production: Use tokenmetrics-api SDK. This implementation has no
        real TokenMetrics client yet, so it fails closed unless --allow-synthetic
        is explicitly set for local/manual testing.
        
        Args:
            symbol: Ticker (BTC, ETH, etc)
            symbol_name: Full name for API
            
        Returns:
            Dict of on-chain metrics or None
        """
        try:
            if not self.allow_synthetic:
                return None

            # TODO: Replace with actual TokenMetrics API calls:
            # from tokenmetrics import Client
            # client = Client(api_key=TM_KEY)
            # data = client.get_whale_tracking(symbol_name)
            # data.update(client.get_exchange_flow(symbol_name))
            # etc.
            
            # Synthetic local-test data only.
            data = {
                'whale_transactions_24h': random.randint(5, 100),
                'large_tx_volume_usd': random.uniform(1e7, 1e10),
                'whale_ratio': random.uniform(0.1, 0.9),
                'accumulation_score': random.uniform(0, 1),
                
                'exchange_inflow_24h': random.uniform(100, 50000),
                'exchange_outflow_24h': random.uniform(100, 50000),
                
                'dev_commits_30d': random.randint(0, 1000),
                'dev_activity_score': random.uniform(0, 1),
                'developers_active': random.randint(5, 200),
                
                'social_sentiment_twitter': random.uniform(-1, 1),
                'social_volume_24h': random.randint(100, 100000),
                
                'active_addresses_24h': random.randint(10000, 10000000),
                'transaction_count_24h': random.randint(10000, 1000000),
                'concentration_index': random.uniform(0, 1),
                'token_velocity': random.uniform(0.1, 20),
            }
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching on-chain data for {symbol}: {e}")
            return None

    def process_symbol(self, symbol: str, symbol_name: str) -> bool:
        """Process one symbol"""
        try:
            data = self.fetch_onchain_data(symbol, symbol_name)
            if not data:
                self._publish_status(
                    symbol,
                    status="BLOCKED_REAL_TOKENMETRICS_SOURCE_NOT_CONFIGURED",
                    message="No real TokenMetrics source is wired; synthetic data was not published.",
                )
                return False
            
            metrics = self.calc.calculate_metrics(data)
            if not metrics:
                return False
            
            metrics.update({
                "synthetic_data": True,
                "actual_payload_present": False,
                "excluded_from_training": True,
                "exclusion_reason": "SYNTHETIC_TOKENMETRICS_LOCAL_TEST_ONLY",
            })
            key = f"v2:onchain:tokenmetrics:synthetic:{symbol}"
            self.redis.setex(key, TTL_SECONDS, json.dumps(metrics))
            self._publish_status(
                symbol,
                status="SYNTHETIC_TOKENMETRICS_PUBLISHED_TO_NON_FEATURE_KEY",
                message=f"Synthetic metrics written to {key}; actual feature key was not updated.",
            )
            
            logger.info(f"✅ Wrote {len(metrics)} synthetic on-chain metrics for {symbol} to {key}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            return False

    def _publish_status(self, symbol: str, *, status: str, message: str) -> None:
        if not self.redis:
            return
        payload = {
            "schema_version": "tokenmetrics_onchain_ingestor_status_v1",
            "symbol": symbol,
            "status": status,
            "message": message,
            "actual_payload_present": False,
            "synthetic_data_written_to_actual_key": False,
            "actual_feature_key": f"v2:onchain:tokenmetrics:{symbol}",
            "synthetic_key": f"v2:onchain:tokenmetrics:synthetic:{symbol}",
            "generated_at": _utc_iso(),
        }
        self.redis.setex(
            f"v2:onchain:tokenmetrics_status:{symbol}",
            TTL_SECONDS,
            json.dumps(payload),
        )

    def run_cycle(self, symbols: Dict[str, str]) -> Tuple[int, int]:
        """Run one cycle for all symbols"""
        successful = 0
        failed = 0
        
        for symbol, symbol_name in symbols.items():
            if self.process_symbol(symbol, symbol_name):
                successful += 1
            else:
                failed += 1
        
        return successful, failed

    def run(self, symbols: Dict[str, str], interval: int = 3600):
        """
        Main loop.
        
        Args:
            symbols: Dict of {symbol: name}
            interval: Seconds between cycles (default 1 hour for slower data)
        """
        logger.info(f"🚀 Starting TokenMetrics on-chain ingestor")
        logger.info(f"   Symbols: {len(symbols)}")
        logger.info(f"   Interval: {interval}s ({interval//60} minutes)")
        logger.info(f"   Output: v2:onchain:tokenmetrics:{{symbol}}")
        logger.info(f"   TTL: {TTL_SECONDS}s (1 hour)")
        
        running = True
        
        def signal_handler(sig, frame):
            nonlocal running
            logger.info("⏹️ Shutdown signal received")
            running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        cycle = 0
        while running:
            cycle += 1
            start_time = time.time()
            
            try:
                successful, failed = self.run_cycle(symbols)
                elapsed = time.time() - start_time
                
                logger.info(
                    f"Cycle {cycle}: {successful}/{len(symbols)} success ({elapsed:.2f}s)"
                )
                
                # Wait before next cycle
                remaining = interval - elapsed
                if remaining > 0:
                    logger.info(f"Next cycle in {remaining:.0f}s...")
                    time.sleep(remaining)
                
            except Exception as e:
                logger.error(f"Cycle error: {e}")
                time.sleep(interval)
        
        logger.info("✅ Ingestor stopped")

    def close(self):
        """Close connections"""
        if self.redis:
            self.redis.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="TokenMetrics On-Chain Ingestor")
    parser.add_argument("--symbols", help="Comma-separated symbol list (e.g., BTC,ETH,SOL)")
    parser.add_argument("--all-symbols", action="store_true", help="Use default symbols")
    parser.add_argument("--interval", type=int, default=3600, help="Interval in seconds (default 1 hour)")
    parser.add_argument("--loop", action="store_true", help="Run continuous loop")
    parser.add_argument("--redis-url", default=REDIS_URL, help="Redis URL")
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Write synthetic local-test data to the non-feature synthetic namespace.",
    )
    
    args = parser.parse_args()
    
    # Parse symbols
    if args.symbols:
        symbol_list = [s.strip() for s in args.symbols.split(",")]
        symbols = {s: s for s in symbol_list}  # Use symbol as name for demo
    elif args.all_symbols:
        symbols = DEFAULT_SYMBOLS
    else:
        # Default to first 5
        symbols = dict(list(DEFAULT_SYMBOLS.items())[:5])
    
    # Create ingestor
    ingestor = TokenMetricsIngestor(redis_url=args.redis_url, allow_synthetic=args.allow_synthetic)
    
    if not ingestor.redis:
        logger.error("Failed to connect to Redis")
        sys.exit(1)
    
    # Run
    if args.loop:
        try:
            ingestor.run(symbols, interval=args.interval)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            ingestor.close()
    else:
        # Single cycle
        successful, failed = ingestor.run_cycle(symbols)
        logger.info(f"Results: {successful}/{len(symbols)} success")
        ingestor.close()


if __name__ == "__main__":
    main()
