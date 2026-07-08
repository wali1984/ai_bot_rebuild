#!/usr/bin/env python3
"""Phase C Day 4: Enhanced Liquidation Detector

Advanced liquidation analysis: cascade detection, velocity, zone prediction.
Enhances existing CoinAnk liquidation data with 8-10 advanced metrics.

Output: Redis v2:liquidation:enhanced:{symbol}
  - Cascade probability (1 field)
  - Liquidation velocity (2 fields)
  - Long/short ratio dynamics (3 fields)
  - Liquidation zones (2 fields)
  - Market stress indicator (1 field)

Integration: Feature builder reads v2:liquidation:enhanced:* keys
             and includes in consolidated v2:features:latest:*

Update frequency: Every 60 seconds (real-time)
TTL: 300 seconds (5 minutes)

Fail-closed default: this file must not publish simulated/random liquidation
data into actual runtime feature keys. Use --allow-synthetic only for
local/manual tests; synthetic data is written to
v2:liquidation:enhanced:synthetic:{symbol}.
"""

import json, logging, time, signal, sys, random, math
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT']

REDIS_URL = "redis://localhost:6379/0"
TTL_SECONDS = 300  # 5 minutes (real-time like orderbook)
REQUIRED_LIQUIDATION_FIELDS = (
    "price",
    "long_oi",
    "short_oi",
    "liq_level_long",
    "liq_level_short",
    "liquidation_count_1m",
    "liquidation_volume_1m",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EnhancedLiquidationCalculator:
    """Calculate advanced liquidation metrics from market data."""

    def __init__(self):
        self.liquidation_history = {}  # Track recent liquidations for velocity

    def calculate_metrics(self, symbol: str, market_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Calculate enhanced liquidation metrics.
        
        8-10 fields:
        - Cascade probability (1)
        - Liquidation velocity (2)
        - Long/short dynamics (3)
        - Liquidation zones (2)
        - Market stress (1)
        """
        metrics = {}
        
        try:
            missing = [
                field
                for field in REQUIRED_LIQUIDATION_FIELDS
                if market_data.get(field) is None
            ]
            if missing:
                logger.warning(f"Missing liquidation fields: {missing}")
                return {}

            def value(field: str) -> float:
                return float(market_data[field])

            # Extract base metrics
            current_price = value('price')
            long_open_interest = value('long_oi')
            short_open_interest = value('short_oi')
            liquidation_level_long = value('liq_level_long')
            liquidation_level_short = value('liq_level_short')
            if (
                current_price <= 0
                or long_open_interest < 0
                or short_open_interest < 0
                or liquidation_level_long <= 0
                or liquidation_level_short <= 0
            ):
                logger.warning("Invalid liquidation market-data payload")
                return {}
            
            # 1. Cascade Probability (1 field)
            # If price is close to liquidation levels, cascade is more likely
            distance_to_long_liq = abs(current_price - liquidation_level_long)
            distance_to_short_liq = abs(current_price - liquidation_level_short)
            
            total_oi = long_open_interest + short_open_interest
            oi_ratio = long_open_interest / max(short_open_interest, 1)
            
            # Imbalanced OI increases cascade risk
            imbalance_factor = abs(oi_ratio - 1.0) / max(oi_ratio, 1.0)
            
            # Distance to liquidation increases risk
            avg_distance = (distance_to_long_liq + distance_to_short_liq) / 2
            distance_factor = max(0, 1.0 - (avg_distance / current_price))
            
            # Cascade probability: combination of imbalance + proximity
            cascade_probability = (imbalance_factor * 0.6 + distance_factor * 0.4)
            metrics['liquidation_cascade_probability'] = min(1.0, cascade_probability)
            
            # 2. Liquidation Velocity (2 fields)
            # Track liquidation frequency
            if symbol not in self.liquidation_history:
                self.liquidation_history[symbol] = {'count': 0, 'volume': 0, 'timestamp': time.time()}
            
            # Liquidations per minute must come from the provider payload. Do
            # not fabricate activity inside the calculator because these fields
            # are consumed as actual features when written to the runtime key.
            liquidation_count_1m = value('liquidation_count_1m')
            liquidation_volume_1m = value('liquidation_volume_1m')
            if liquidation_count_1m < 0 or liquidation_volume_1m < 0:
                logger.warning("Invalid liquidation activity payload")
                return {}
            
            metrics['liquidation_count_1m'] = float(liquidation_count_1m)
            metrics['liquidation_volume_1m'] = liquidation_volume_1m
            
            # Velocity acceleration (increasing trend)
            velocity_trend = 1.0 if liquidation_count_1m > 25 else 0.5 if liquidation_count_1m > 10 else 0.0
            
            # 3. Long/Short Ratio Dynamics (3 fields)
            metrics['long_short_ratio'] = long_open_interest / max(short_open_interest, 1)
            
            # Ratio change indicator (0 = balanced, 1 = extreme long bias, -1 = extreme short bias)
            ratio = metrics['long_short_ratio']
            if ratio > 2.0:
                metrics['ratio_direction'] = 1.0  # Long-heavy
            elif ratio < 0.5:
                metrics['ratio_direction'] = -1.0  # Short-heavy
            else:
                metrics['ratio_direction'] = 0.0  # Balanced
            
            # Ratio strength (how extreme is the imbalance)
            if ratio > 1.0:
                ratio_strength = min(1.0, (ratio - 1.0))
            else:
                ratio_strength = min(1.0, (1.0 - ratio))
            metrics['long_short_ratio_strength'] = ratio_strength
            
            # 4. Liquidation Zones (2 fields)
            # Predict the next liquidation levels
            price_range = current_price * 0.05  # 5% buffer
            
            # Long liquidation zone (below current price)
            long_liq_zone = current_price - price_range
            metrics['predicted_long_liq_zone'] = long_liq_zone
            
            # Short liquidation zone (above current price)
            short_liq_zone = current_price + price_range
            metrics['predicted_short_liq_zone'] = short_liq_zone
            
            # 5. Market Stress Indicator (1 field)
            # Composite of cascade + velocity + ratio imbalance
            cascade_stress = cascade_probability
            velocity_stress = min(1.0, liquidation_count_1m / 100)
            ratio_stress = ratio_strength
            
            market_stress = (cascade_stress * 0.4 + velocity_stress * 0.35 + ratio_stress * 0.25)
            metrics['market_stress_indicator'] = min(1.0, market_stress)
            
            # Timestamp
            metrics['timestamp'] = _utc_iso()
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating liquidation metrics: {e}")
            return {}


class EnhancedLiquidationIngestor:
    """Enhance liquidation data with advanced metrics."""

    def __init__(self, redis_url: str = REDIS_URL, *, allow_synthetic: bool = False):
        self.redis_url = redis_url
        self.allow_synthetic = allow_synthetic
        self.redis = None
        self.calc = EnhancedLiquidationCalculator()
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

    def fetch_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch market data for liquidation analysis.
        
        In production: Read from Binance API + CoinAnk. This implementation has
        no real provider fetcher yet, so it fails closed unless
        --allow-synthetic is explicitly set for local/manual testing.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Dict with price, OI, liquidation levels
        """
        try:
            if not self.allow_synthetic:
                return {}

            # TODO: In production:
            # Read from existing CoinAnk keys: v2:coinank:*
            # Read from Binance: open interest, prices
            
            base_price = 62500
            
            return {
                'price': base_price + random.uniform(-500, 500),
                'long_oi': random.uniform(500000, 2000000),
                'short_oi': random.uniform(400000, 1500000),
                'liq_level_long': base_price - random.uniform(1000, 3000),
                'liq_level_short': base_price + random.uniform(1000, 3000),
                'liquidation_count_1m': random.randint(5, 50),
                'liquidation_volume_1m': random.uniform(100000, 10000000),
            }
            
        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {e}")
            return {}

    def process_symbol(self, symbol: str) -> bool:
        """Process one symbol"""
        try:
            data = self.fetch_market_data(symbol)
            if not data:
                self._publish_status(
                    symbol,
                    status="BLOCKED_REAL_LIQUIDATION_SOURCE_NOT_CONFIGURED",
                    message="No real liquidation source is wired; synthetic data was not published.",
                )
                return False
            
            metrics = self.calc.calculate_metrics(symbol, data)
            if not metrics:
                return False
            
            metrics.update({
                "synthetic_data": True,
                "actual_payload_present": False,
                "excluded_from_training": True,
                "exclusion_reason": "SYNTHETIC_LIQUIDATION_LOCAL_TEST_ONLY",
            })
            key = f"v2:liquidation:enhanced:synthetic:{symbol}"
            self.redis.setex(key, TTL_SECONDS, json.dumps(metrics))
            self._publish_status(
                symbol,
                status="SYNTHETIC_LIQUIDATION_PUBLISHED_TO_NON_FEATURE_KEY",
                message=f"Synthetic metrics written to {key}; actual feature key was not updated.",
            )
            
            logger.info(f"✅ Wrote {len(metrics)} synthetic enhanced liquidation metrics for {symbol} to {key}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            return False

    def run_cycle(self, symbols: List[str]) -> Tuple[int, int]:
        """Run one cycle for all symbols"""
        successful = sum(1 for s in symbols if self.process_symbol(s))
        return successful, len(symbols) - successful

    def _publish_status(self, symbol: str, *, status: str, message: str) -> None:
        if not self.redis:
            return
        payload = {
            "schema_version": "enhanced_liquidation_status_v1",
            "symbol": symbol,
            "status": status,
            "message": message,
            "actual_payload_present": False,
            "synthetic_data_written_to_actual_key": False,
            "actual_feature_key": f"v2:liquidation:enhanced:{symbol}",
            "synthetic_key": f"v2:liquidation:enhanced:synthetic:{symbol}",
            "generated_at": _utc_iso(),
        }
        self.redis.setex(
            f"v2:liquidation:enhanced_status:{symbol}",
            TTL_SECONDS,
            json.dumps(payload),
        )

    def run(self, symbols: List[str], interval: int = 60):
        """
        Main loop.
        
        Args:
            symbols: List of trading pairs
            interval: Seconds between cycles (default 60s, real-time)
        """
        logger.info(f"🚀 Starting Enhanced Liquidation Detector")
        logger.info(f"   Symbols: {len(symbols)}")
        logger.info(f"   Interval: {interval}s")
        logger.info(f"   Output: v2:liquidation:enhanced:{{symbol}}")
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
                    time.sleep(remaining)
                
            except Exception as e:
                logger.error(f"Cycle error: {e}")
                time.sleep(interval)
        
        logger.info("✅ Detector stopped")

    def close(self):
        """Close connections"""
        if self.redis:
            self.redis.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Liquidation Detector")
    parser.add_argument("--symbols", help="Comma-separated symbol list")
    parser.add_argument("--all-symbols", action="store_true", help="Use default symbols")
    parser.add_argument("--interval", type=int, default=60, help="Interval in seconds")
    parser.add_argument("--loop", action="store_true", help="Run continuous loop")
    parser.add_argument("--redis-url", default=REDIS_URL, help="Redis URL")
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Write synthetic local-test data to v2:liquidation:enhanced:synthetic:* only",
    )
    
    args = parser.parse_args()
    
    # Parse symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    elif args.all_symbols:
        symbols = DEFAULT_SYMBOLS
    else:
        symbols = DEFAULT_SYMBOLS[:5]
    
    # Create detector
    detector = EnhancedLiquidationIngestor(
        redis_url=args.redis_url,
        allow_synthetic=args.allow_synthetic,
    )
    
    if not detector.redis:
        logger.error("Failed to connect to Redis")
        sys.exit(1)
    
    # Run
    if args.loop:
        try:
            detector.run(symbols, interval=args.interval)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            detector.close()
    else:
        # Single cycle
        successful, failed = detector.run_cycle(symbols)
        logger.info(f"Results: {successful}/{len(symbols)} success")
        detector.close()


if __name__ == "__main__":
    main()
