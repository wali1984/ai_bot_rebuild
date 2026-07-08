#!/usr/bin/env python3
"""Phase C Day 1: CoinAPI Orderbook Microstructure Ingestor

Real-time orderbook depth analysis.
Feeds 27 microstructure fields: bid/ask levels, spread, imbalance, pressure.

Output: Redis v2:microstructure:orderbook:{symbol}
Integration: Feature builder reads and consolidates into v2:features:latest:*

Fail-closed default: this file must not publish simulated orderbook data into
actual runtime feature keys. Use --allow-synthetic only for local/manual tests;
synthetic data is written to v2:microstructure:orderbook:synthetic:{symbol}.
"""

import json, logging, time, signal, sys
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import redis

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT']
REDIS_URL = "redis://localhost:6379/0"
TTL_SECONDS = 300


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OrderbookMicrostructureCalculator:
    """Calculate 27 microstructure metrics from orderbook depth."""

    def calculate_metrics(self, bids: List[List[float]], asks: List[List[float]]) -> Dict[str, float]:
        """Calculate metrics from bid/ask levels (27 fields)."""
        metrics = {}
        
        try:
            if len(bids) < 5 or len(asks) < 5:
                logger.warning("Orderbook payload missing top-5 bid/ask depth")
                return {}

            def normalize_levels(levels: List[List[float]], side: str) -> List[List[float]]:
                normalized = []
                for index, level in enumerate(levels[:5], start=1):
                    if len(level) < 2:
                        raise ValueError(f"{side} level {index} missing price or size")
                    price = float(level[0])
                    size = float(level[1])
                    if price <= 0 or size <= 0:
                        raise ValueError(f"{side} level {index} has non-positive price or size")
                    normalized.append([price, size])
                return normalized

            bids = normalize_levels(bids, "bid")
            asks = normalize_levels(asks, "ask")

            # 1. Bid/Ask Prices (10 fields)
            for i, (bid, ask) in enumerate(zip(bids, asks)):
                metrics[f'bid_price_{i+1}'] = float(bid[0]) if bid[0] > 0 else 0
                metrics[f'ask_price_{i+1}'] = float(ask[0]) if ask[0] > 0 else 0

            # 2. Spread (3 fields)
            if bids[0][0] > 0 and asks[0][0] > 0:
                bid1, ask1 = float(bids[0][0]), float(asks[0][0])
                mid = (bid1 + ask1) / 2
                metrics['spread_bps'] = ((ask1 - bid1) / mid * 10000) if mid > 0 else 0
                metrics['spread_abs'] = ask1 - bid1
                metrics['mid_price'] = mid
            else:
                metrics['spread_bps'] = metrics['spread_abs'] = metrics['mid_price'] = 0

            # 3. Order Flow (5 fields: volumes + ratio)
            total_bid_vol = sum(float(b[1]) for b in bids if b[0] > 0)
            total_ask_vol = sum(float(a[1]) for a in asks if a[0] > 0)
            
            for i, (bid, ask) in enumerate(zip(bids, asks)):
                metrics[f'bid_vol_{i+1}'] = float(bid[1]) if bid[0] > 0 else 0
                metrics[f'ask_vol_{i+1}'] = float(ask[1]) if ask[0] > 0 else 0

            if total_bid_vol + total_ask_vol > 0:
                metrics['buy_sell_ratio'] = total_bid_vol / (total_bid_vol + total_ask_vol)
            else:
                metrics['buy_sell_ratio'] = 0.5

            # 4. Imbalance Ratios (4 fields)
            l1_bid = float(bids[0][1]) if bids[0][0] > 0 else 0
            l1_ask = float(asks[0][1]) if asks[0][0] > 0 else 0
            metrics['l1_imbalance'] = l1_bid / (l1_bid + l1_ask) if (l1_bid + l1_ask) > 0 else 0.5

            l3_bid = sum(float(b[1]) for b in bids[:3] if b[0] > 0)
            l3_ask = sum(float(a[1]) for a in asks[:3] if a[0] > 0)
            metrics['l3_imbalance'] = l3_bid / (l3_bid + l3_ask) if (l3_bid + l3_ask) > 0 else 0.5

            l5_bid = sum(float(b[1]) for b in bids[:5] if b[0] > 0)
            l5_ask = sum(float(a[1]) for a in asks[:5] if a[0] > 0)
            metrics['l5_imbalance'] = l5_bid / (l5_bid + l5_ask) if (l5_bid + l5_ask) > 0 else 0.5

            metrics['vwap_deviation_pct'] = 0  # Placeholder

            # 5. Pressure (3 fields)
            metrics['bid_pressure'] = l1_bid / max(l1_ask, 0.0001)
            metrics['ask_pressure'] = l1_ask / max(l1_bid, 0.0001)
            
            if total_bid_vol + total_ask_vol > 0:
                metrics['volume_concentration'] = (l1_bid + l1_ask) / (total_bid_vol + total_ask_vol)
            else:
                metrics['volume_concentration'] = 0

            metrics['timestamp'] = _utc_iso()

            return metrics
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {}


class OrderbookIngestor:
    def __init__(self, redis_url: str = REDIS_URL, *, allow_synthetic: bool = False):
        self.redis_url = redis_url
        self.allow_synthetic = allow_synthetic
        self.redis = None
        self.calc = OrderbookMicrostructureCalculator()
        self.connect()

    def connect(self) -> bool:
        try:
            parts = self.redis_url.replace("redis://", "").split(":")
            host = parts[0] if parts else "localhost"
            port_str = parts[1] if len(parts) > 1 else "6379"
            port = int(port_str.split("/")[0])
            self.redis = redis.Redis(host=host, port=port, db=0, decode_responses=True, socket_connect_timeout=5)
            self.redis.ping()
            logger.info(f"✅ Connected to Redis: {host}:{port}")
            return True
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return False

    def process_symbol(self, symbol: str) -> bool:
        try:
            if not self.allow_synthetic:
                self._publish_status(
                    symbol,
                    status="BLOCKED_REAL_ORDERBOOK_SOURCE_NOT_CONFIGURED",
                    message="No real CoinAPI/orderbook source is wired; synthetic data was not published.",
                )
                return False

            # Synthetic orderbook for explicit local tests only.
            mid = 62500
            bids = [[mid - i*5, 10-i] for i in range(5)]
            asks = [[mid + i*5, 10-i] for i in range(5)]
            
            metrics = self.calc.calculate_metrics(bids, asks)
            if not metrics:
                return False

            metrics.update({
                "synthetic_data": True,
                "actual_payload_present": False,
                "excluded_from_training": True,
                "exclusion_reason": "SYNTHETIC_ORDERBOOK_LOCAL_TEST_ONLY",
            })
            key = f"v2:microstructure:orderbook:synthetic:{symbol}"
            self.redis.setex(key, TTL_SECONDS, json.dumps(metrics))
            self._publish_status(
                symbol,
                status="SYNTHETIC_ORDERBOOK_PUBLISHED_TO_NON_FEATURE_KEY",
                message=f"Synthetic metrics written to {key}; actual feature key was not updated.",
            )
            logger.info(f"✅ Wrote {len(metrics)} synthetic metrics for {symbol} to {key}")
            return True
        except Exception as e:
            logger.error(f"Error for {symbol}: {e}")
            return False

    def _publish_status(self, symbol: str, *, status: str, message: str) -> None:
        if not self.redis:
            return
        payload = {
            "schema_version": "orderbook_microstructure_ingestor_status_v1",
            "symbol": symbol,
            "status": status,
            "message": message,
            "actual_payload_present": False,
            "synthetic_data_written_to_actual_key": False,
            "actual_feature_key": f"v2:microstructure:orderbook:{symbol}",
            "synthetic_key": f"v2:microstructure:orderbook:synthetic:{symbol}",
            "generated_at": _utc_iso(),
        }
        self.redis.setex(
            f"v2:microstructure:orderbook_status:{symbol}",
            TTL_SECONDS,
            json.dumps(payload),
        )

    def run_cycle(self, symbols: List[str]) -> Tuple[int, int]:
        successful = sum(1 for s in symbols if self.process_symbol(s))
        return successful, len(symbols) - successful

    def run(self, symbols: List[str], interval: int = 60):
        logger.info(f"🚀 CoinAPI Orderbook Ingestor: {len(symbols)} symbols, {interval}s interval")
        
        running = True
        def signal_handler(sig, frame):
            nonlocal running
            logger.info("⏹️ Shutdown")
            running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        cycle = 0
        while running:
            cycle += 1
            start = time.time()
            successful, failed = self.run_cycle(symbols)
            elapsed = time.time() - start
            logger.info(f"Cycle {cycle}: {successful}/{len(symbols)} success ({elapsed:.2f}s)")
            
            remaining = max(0, interval - elapsed)
            if remaining > 0:
                time.sleep(remaining)
        
        logger.info("✅ Stopped")

    def close(self):
        if self.redis:
            self.redis.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="Comma-separated symbols")
    parser.add_argument("--all-symbols", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--redis-url", default=REDIS_URL)
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Write synthetic local-test data to the non-feature synthetic namespace.",
    )
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    elif args.all_symbols:
        symbols = DEFAULT_SYMBOLS
    else:
        symbols = DEFAULT_SYMBOLS[:5]

    ingestor = OrderbookIngestor(redis_url=args.redis_url, allow_synthetic=args.allow_synthetic)
    if not ingestor.redis:
        sys.exit(1)

    try:
        if args.loop:
            ingestor.run(symbols, interval=args.interval)
        else:
            successful, failed = ingestor.run_cycle(symbols)
            logger.info(f"Results: {successful} success, {failed} failed")
    finally:
        ingestor.close()


if __name__ == "__main__":
    main()
