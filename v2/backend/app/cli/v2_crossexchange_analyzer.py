#!/usr/bin/env python3
"""Phase C Day 3: Cross-Exchange Analyzer

Arbitrage detection, funding rate spreads, volume divergence analysis.
Feeds 15+ cross-exchange metrics into v2 feature pipeline.

Output: Redis v2:crossexchange:analysis:{symbol}
  - Arbitrage spreads (3 fields)
  - Funding rate analysis (4 fields)
  - Volume divergence (4 fields)
  - Exchange-specific metrics (4 fields)

Integration: Feature builder reads v2:crossexchange:analysis:* keys
             and includes in consolidated v2:features:latest:*

Primary exchanges: Binance (spot + futures), KuCoin
Update frequency: Every 300 seconds (5 minutes)
TTL: 600 seconds (10 minutes, slightly longer for data consistency)

Fail-closed default: this file must not publish simulated/random exchange data
into actual runtime feature keys. Use --allow-synthetic only for local/manual
tests; synthetic data is written to v2:crossexchange:analysis:synthetic:{symbol}.
"""

import json, logging, time, signal, sys, random
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT']

REDIS_URL = "redis://localhost:6379/0"
TTL_SECONDS = 600  # 10 minutes
REQUIRED_EXCHANGE_FIELDS = ("price", "volume_24h", "funding_rate", "spread_bps")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CrossExchangeAnalyzer:
    """Analyze price and funding rate spreads across exchanges."""

    def calculate_metrics(self, binance_data: Dict, kucoin_data: Dict) -> Dict[str, float]:
        """
        Calculate cross-exchange metrics.
        
        15+ fields:
        - Arbitrage spreads (3)
        - Funding rates (4)
        - Volume divergence (4)
        - Exchange-specific (4)
        """
        metrics = {}
        
        try:
            missing = []
            for exchange, data in (("binance", binance_data), ("kucoin", kucoin_data)):
                missing.extend(
                    f"{exchange}.{field}"
                    for field in REQUIRED_EXCHANGE_FIELDS
                    if data.get(field) is None
                )
            if missing:
                logger.warning(f"Missing cross-exchange fields: {missing}")
                return {}

            def value(data: Dict[str, Any], field: str) -> float:
                return float(data[field])

            # 1. Arbitrage Spreads (3 fields)
            # Binance spot vs KuCoin spot
            binance_price = value(binance_data, 'price')
            kucoin_price = value(kucoin_data, 'price')
            
            if binance_price <= 0 or kucoin_price <= 0:
                logger.warning("Invalid cross-exchange price payload")
                return {}

            price_diff = kucoin_price - binance_price
            price_diff_pct = (price_diff / binance_price) * 100
            
            metrics['arb_spread_pct'] = price_diff_pct
            metrics['arb_spread_abs'] = price_diff
            metrics['arb_direction'] = 1.0 if price_diff_pct > 0 else -1.0
            
            # 2. Funding Rate Analysis (4 fields)
            binance_funding = value(binance_data, 'funding_rate')
            kucoin_funding = value(kucoin_data, 'funding_rate')
            
            metrics['funding_rate_spread_bps'] = (binance_funding - kucoin_funding) * 10000
            metrics['binance_funding_rate_pct'] = binance_funding * 100
            metrics['kucoin_funding_rate_pct'] = kucoin_funding * 100
            
            # Funding arbitrage opportunity (if spreads exceed threshold)
            if abs(metrics['funding_rate_spread_bps']) > 10:  # > 10 bps is significant
                metrics['funding_arb_opportunity'] = 1.0
            else:
                metrics['funding_arb_opportunity'] = 0.0
            
            # 3. Volume Divergence (4 fields)
            binance_volume = value(binance_data, 'volume_24h')
            kucoin_volume = value(kucoin_data, 'volume_24h')
            total_volume = binance_volume + kucoin_volume
            if total_volume <= 0:
                logger.warning("Invalid cross-exchange volume payload")
                return {}
            
            metrics['binance_volume_pct'] = binance_volume / total_volume * 100
            metrics['kucoin_volume_pct'] = kucoin_volume / total_volume * 100
            metrics['volume_concentration'] = max(metrics['binance_volume_pct'], metrics['kucoin_volume_pct'])
            
            # Volume shift indicator (if one exchange has >60% of volume)
            metrics['volume_shift_indicator'] = 1.0 if metrics['volume_concentration'] > 60 else 0.0
            
            # 4. Exchange-Specific Metrics (4 fields)
            binance_bid_ask_spread = value(binance_data, 'spread_bps')
            kucoin_bid_ask_spread = value(kucoin_data, 'spread_bps')
            if binance_bid_ask_spread < 0 or kucoin_bid_ask_spread < 0:
                logger.warning("Invalid cross-exchange spread payload")
                return {}
            
            metrics['binance_spread_bps'] = binance_bid_ask_spread
            metrics['kucoin_spread_bps'] = kucoin_bid_ask_spread
            metrics['spread_differential'] = abs(kucoin_bid_ask_spread - binance_bid_ask_spread)
            
            # Liquidity quality (tighter spread = better liquidity)
            better_liquidity = "binance" if binance_bid_ask_spread < kucoin_bid_ask_spread else "kucoin"
            metrics['better_liquidity_exchange'] = 1.0 if better_liquidity == "binance" else 0.0
            
            # Timestamp
            metrics['timestamp'] = _utc_iso()
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating cross-exchange metrics: {e}")
            return {}


class CrossExchangeIngestor:
    """Fetch price and funding data from multiple exchanges."""

    def __init__(self, redis_url: str = REDIS_URL, *, allow_synthetic: bool = False):
        self.redis_url = redis_url
        self.allow_synthetic = allow_synthetic
        self.redis = None
        self.analyzer = CrossExchangeAnalyzer()
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

    def fetch_exchange_data(self, symbol: str, exchange: str) -> Dict[str, Any]:
        """
        Fetch price and funding data from exchange.
        
        In production: Use ccxt or exchange APIs. This implementation has no
        real exchange fetcher yet, so it fails closed unless --allow-synthetic
        is explicitly set for local/manual testing.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            exchange: Exchange name (binance, kucoin)
            
        Returns:
            Dict with price, volume, funding, spread
        """
        try:
            if not self.allow_synthetic:
                return {}

            # TODO: Replace with actual exchange API calls:
            # import ccxt
            # binance = ccxt.binance()
            # ticker = binance.fetch_ticker(symbol)
            # funding = binance.fetch_funding_rate(symbol)
            
            # Synthetic local-test data only.
            base_price = 62500
            
            if exchange == "binance":
                return {
                    'price': base_price + random.uniform(-100, 100),
                    'volume_24h': random.uniform(500000, 2000000),
                    'funding_rate': random.uniform(0.00008, 0.00015),
                    'spread_bps': random.uniform(1.0, 2.5),
                }
            elif exchange == "kucoin":
                return {
                    'price': base_price + random.uniform(-200, 200),
                    'volume_24h': random.uniform(100000, 500000),
                    'funding_rate': random.uniform(0.00003, 0.00010),
                    'spread_bps': random.uniform(2.0, 4.0),
                }
            else:
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching {exchange} data for {symbol}: {e}")
            return {}

    def process_symbol(self, symbol: str) -> bool:
        """Process one symbol across exchanges"""
        try:
            # Fetch from both exchanges
            binance_data = self.fetch_exchange_data(symbol, "binance")
            kucoin_data = self.fetch_exchange_data(symbol, "kucoin")
            
            if not binance_data or not kucoin_data:
                self._publish_status(
                    symbol,
                    status="BLOCKED_REAL_CROSSEXCHANGE_SOURCE_NOT_CONFIGURED",
                    message="No real cross-exchange source is wired; synthetic data was not published.",
                )
                return False
            
            # Analyze
            metrics = self.analyzer.calculate_metrics(binance_data, kucoin_data)
            if not metrics:
                return False
            
            # Write to Redis
            metrics.update({
                "synthetic_data": True,
                "actual_payload_present": False,
                "excluded_from_training": True,
                "exclusion_reason": "SYNTHETIC_CROSSEXCHANGE_LOCAL_TEST_ONLY",
            })
            key = f"v2:crossexchange:analysis:synthetic:{symbol}"
            self.redis.setex(key, TTL_SECONDS, json.dumps(metrics))
            self._publish_status(
                symbol,
                status="SYNTHETIC_CROSSEXCHANGE_PUBLISHED_TO_NON_FEATURE_KEY",
                message=f"Synthetic metrics written to {key}; actual feature key was not updated.",
            )
            
            logger.info(f"✅ Wrote {len(metrics)} synthetic cross-exchange metrics for {symbol} to {key}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            return False

    def _publish_status(self, symbol: str, *, status: str, message: str) -> None:
        if not self.redis:
            return
        payload = {
            "schema_version": "crossexchange_analyzer_status_v1",
            "symbol": symbol,
            "status": status,
            "message": message,
            "actual_payload_present": False,
            "synthetic_data_written_to_actual_key": False,
            "actual_feature_key": f"v2:crossexchange:analysis:{symbol}",
            "synthetic_key": f"v2:crossexchange:analysis:synthetic:{symbol}",
            "generated_at": _utc_iso(),
        }
        self.redis.setex(
            f"v2:crossexchange:analysis_status:{symbol}",
            TTL_SECONDS,
            json.dumps(payload),
        )

    def run_cycle(self, symbols: List[str]) -> Tuple[int, int]:
        """Run one cycle for all symbols"""
        successful = sum(1 for s in symbols if self.process_symbol(s))
        return successful, len(symbols) - successful

    def run(self, symbols: List[str], interval: int = 300):
        """
        Main loop.
        
        Args:
            symbols: List of trading pairs
            interval: Seconds between cycles (default 300s = 5 min)
        """
        logger.info(f"🚀 Starting Cross-Exchange Analyzer")
        logger.info(f"   Symbols: {len(symbols)}")
        logger.info(f"   Interval: {interval}s ({interval//60} min)")
        logger.info(f"   Output: v2:crossexchange:analysis:{{symbol}}")
        logger.info(f"   TTL: {TTL_SECONDS}s")
        
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
        
        logger.info("✅ Analyzer stopped")

    def close(self):
        """Close connections"""
        if self.redis:
            self.redis.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Cross-Exchange Analyzer")
    parser.add_argument("--symbols", help="Comma-separated symbol list")
    parser.add_argument("--all-symbols", action="store_true", help="Use default symbols")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds (default 300s)")
    parser.add_argument("--loop", action="store_true", help="Run continuous loop")
    parser.add_argument("--redis-url", default=REDIS_URL, help="Redis URL")
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Write synthetic local-test data to v2:crossexchange:analysis:synthetic:* only",
    )
    
    args = parser.parse_args()
    
    # Parse symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    elif args.all_symbols:
        symbols = DEFAULT_SYMBOLS
    else:
        symbols = DEFAULT_SYMBOLS[:5]
    
    # Create analyzer
    analyzer = CrossExchangeIngestor(
        redis_url=args.redis_url,
        allow_synthetic=args.allow_synthetic,
    )
    
    if not analyzer.redis:
        logger.error("Failed to connect to Redis")
        sys.exit(1)
    
    # Run
    if args.loop:
        try:
            analyzer.run(symbols, interval=args.interval)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            analyzer.close()
    else:
        # Single cycle
        successful, failed = analyzer.run_cycle(symbols)
        logger.info(f"Results: {successful}/{len(symbols)} success")
        analyzer.close()


if __name__ == "__main__":
    main()
