#!/usr/bin/env python3
"""
Day 5: Phase C Feature Builder Integration Test
Tests unified feature building with all 4 new data sources
"""

import sys
import json
import time
import redis
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add service path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from v2.backend.app.services.enhanced_unified_feature_builder import EnhancedUnifiedFeatureBuilder

class Day5IntegrationTest:
    """Test Phase C feature integration"""

    def __init__(self, redis_url="redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis = None
        self.builder = None
        self.connect()

    def connect(self) -> bool:
        """Connect to Redis and initialize feature builder"""
        try:
            parts = self.redis_url.replace("redis://", "").split(":")
            host = parts[0] if parts else "localhost"
            port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379

            self.redis = redis.Redis(
                host=host,
                port=port,
                db=0,
                decode_responses=True,
                socket_connect_timeout=5
            )
            self.redis.ping()
            logger.info(f"✅ Connected to Redis: {host}:{port}")

            self.builder = EnhancedUnifiedFeatureBuilder(
                redis_host=host,
                redis_port=port,
                redis_db=0
            )
            logger.info("✅ Initialized EnhancedUnifiedFeatureBuilder")
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False

    def check_phase_c_data_sources(self, symbol: str = "BTCUSDT") -> Dict[str, bool]:
        """Check if Phase C data sources have data in Redis"""
        results = {}

        sources = {
            "CoinAPI Orderbook": f"v2:microstructure:orderbook:{symbol}",
            "TokenMetrics OnChain": f"v2:onchain:tokenmetrics:{symbol}",
            "CrossExchange Analysis": f"v2:crossexchange:analysis:{symbol}",
            "Enhanced Liquidation": f"v2:liquidation:enhanced:{symbol}",
        }

        for name, key in sources.items():
            data = self.redis.get(key)
            results[name] = bool(data)
            status = "✅" if data else "❌"
            if data:
                try:
                    parsed = json.loads(data)
                    field_count = len(parsed)
                    logger.info(f"{status} {name}: {key} ({field_count} fields)")
                except:
                    logger.info(f"{status} {name}: {key} (invalid JSON)")
            else:
                logger.warning(f"{status} {name}: {key} (no data)")

        return results

    def test_unified_feature_build(self, symbol: str = "BTCUSDT", timeframe: str = "5m"):
        """Test building unified features with Phase C sources"""
        logger.info(f"\n📊 Testing unified feature build: {symbol} {timeframe}")

        try:
            # Fetch OHLCV data
            ohlcv_key = f"binance:ohlcv:{symbol}:{timeframe}:history"
            ohlcv_history = self.redis.lrange(ohlcv_key, -50, -1)

            if not ohlcv_history:
                logger.warning(f"No OHLCV history found for {symbol} {timeframe}")
                # Create dummy OHLCV for testing
                ohlcv_window = [
                    {
                        "open": 65000 + i * 10,
                        "high": 65100 + i * 10,
                        "low": 64900 + i * 10,
                        "close": 65050 + i * 10,
                        "volume": 100 + i
                    }
                    for i in range(50)
                ]
            else:
                ohlcv_window = [json.loads(x) for x in ohlcv_history]

            # Dummy bid/ask
            bid_ask = {
                "bid_price": 65000,
                "ask_price": 65050,
                "bid_size": 10,
                "ask_size": 15
            }

            # Build features
            features = self.builder.build_features(
                symbol=symbol,
                timeframe=timeframe,
                ohlcv_window=ohlcv_window,
                bid_ask=bid_ask,
                liquidation_data={},
                paper_position=None
            )

            logger.info(f"✅ Built unified features: {len(features)} fields")

            # Check Phase C fields
            phase_c_fields = {
                "orderbook": sum(1 for k in features.keys() if "phase_c_orderbook" in k),
                "onchain": sum(1 for k in features.keys() if "phase_c_onchain" in k),
                "crossex": sum(1 for k in features.keys() if "phase_c_crossex" in k),
                "liquidation": sum(1 for k in features.keys() if "phase_c_liq" in k),
            }

            logger.info(f"   Phase C Orderbook fields: {phase_c_fields['orderbook']}")
            logger.info(f"   Phase C OnChain fields: {phase_c_fields['onchain']}")
            logger.info(f"   Phase C CrossEx fields: {phase_c_fields['crossex']}")
            logger.info(f"   Phase C Liquidation fields: {phase_c_fields['liquidation']}")
            logger.info(f"   Total Phase C fields: {sum(phase_c_fields.values())}")
            logger.info(f"   Data completeness: {features.get('data_completeness_pct', 0):.1f}%")

            return features

        except Exception as e:
            logger.error(f"❌ Feature build failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def write_test_results(self, results: Dict[str, Any]):
        """Write results to Redis for monitoring"""
        try:
            results_key = "v2:test:day5_integration:latest"
            self.redis.setex(
                results_key,
                3600,
                json.dumps(results, indent=2, default=str)
            )
            logger.info(f"✅ Results written to {results_key}")
        except Exception as e:
            logger.error(f"❌ Failed to write results: {e}")

    def run_full_test(self):
        """Run complete integration test"""
        logger.info("\n" + "=" * 80)
        logger.info("🚀 Day 5 Phase C Integration Test")
        logger.info("=" * 80)

        # Check data sources
        logger.info("\n1️⃣ Checking Phase C Data Sources...")
        sources_status = self.check_phase_c_data_sources("BTCUSDT")

        # Test feature building
        logger.info("\n2️⃣ Testing Unified Feature Building...")
        features = self.test_unified_feature_build("BTCUSDT", "5m")

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("📋 Test Summary")
        logger.info("=" * 80)

        if not any(sources_status.values()):
            logger.warning("⚠️  No Phase C data sources have data yet")
            logger.info("   (Ingestors may still be starting up)")
        else:
            active = [k for k, v in sources_status.items() if v]
            logger.info(f"✅ Active data sources: {', '.join(active)}")

        if features:
            logger.info(f"✅ Unified features built successfully: {len(features)} fields")
        else:
            logger.warning("❌ Feature building encountered errors")

        logger.info("\n" + "=" * 80)
        logger.info("✅ Test Complete")
        logger.info("=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Day 5 Integration Test")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0", help="Redis URL")
    parser.add_argument("--symbol", default="BTCUSDT", help="Test symbol")
    parser.add_argument("--timeframe", default="5m", help="Test timeframe")
    parser.add_argument("--wait-for-data", type=int, default=0, help="Wait N seconds for ingestor data")

    args = parser.parse_args()

    tester = Day5IntegrationTest(redis_url=args.redis_url)

    if not tester.redis:
        logger.error("Failed to connect to Redis")
        sys.exit(1)

    if args.wait_for_data > 0:
        logger.info(f"⏳ Waiting {args.wait_for_data}s for ingestor data...")
        time.sleep(args.wait_for_data)

    tester.run_full_test()


if __name__ == "__main__":
    main()
