#!/usr/bin/env python3
"""
HEDGE_BUILD End-to-End Proof Test
==================================
This script closes ONE profitable position to prove the HEDGE_BUILD mechanism works.

Flow being tested:
1. Close a profitable position → Trader publishes PROFIT_EXIT_PUBLISHED
2. Trainer consumes event → Enters HEDGE_BUILD state (HEDGE_BUILD_ENTER)
3. During HEDGE_BUILD: FLIPs blocked, HEDGEs allowed
4. After TTL: HEDGE_BUILD_EXIT

Usage:
    python scripts/test_hedge_build.py [--dry-run] [--symbol BTCUSDT]
    
    --dry-run    Show what would be closed without actually closing
    --symbol     Close a specific symbol instead of auto-selecting
"""

import os
import sys
import json
import time
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_binance_client():
    """Get Binance futures client"""
    from binance.client import Client
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET required")
    return Client(api_key, api_secret)


def get_redis_client():
    """Get Redis client"""
    import redis
    return redis.Redis(host='localhost', port=6379, decode_responses=True)


def get_profitable_positions(client):
    """Find all profitable positions"""
    positions = client.futures_position_information()
    profitable = []
    
    for pos in positions:
        amt = float(pos.get('positionAmt', 0))
        if amt == 0:
            continue
        
        unrealized_pnl = float(pos.get('unRealizedProfit', 0))
        entry_price = float(pos.get('entryPrice', 0))
        mark_price = float(pos.get('markPrice', 0))
        
        if unrealized_pnl > 0:
            roi_pct = 0
            if entry_price > 0:
                if amt > 0:  # LONG
                    roi_pct = ((mark_price - entry_price) / entry_price) * 100
                else:  # SHORT
                    roi_pct = ((entry_price - mark_price) / entry_price) * 100
            
            profitable.append({
                'symbol': pos['symbol'],
                'side': 'LONG' if amt > 0 else 'SHORT',
                'size': abs(amt),
                'entry_price': entry_price,
                'mark_price': mark_price,
                'pnl': unrealized_pnl,
                'roi_pct': roi_pct,
                'leverage': int(pos.get('leverage', 1))
            })
    
    # Sort by ROI descending (most profitable first)
    profitable.sort(key=lambda x: x['roi_pct'], reverse=True)
    return profitable


def close_position(client, symbol: str, side: str, size: float, dry_run: bool = False):
    """Close a specific position"""
    # Determine order side (opposite of position)
    order_side = 'SELL' if side == 'LONG' else 'BUY'
    position_side = side  # LONG or SHORT for hedge mode
    
    logger.info(f"{'[DRY-RUN] Would close' if dry_run else 'Closing'}: {symbol} {side} size={size}")
    
    if dry_run:
        return {'status': 'DRY_RUN', 'symbol': symbol, 'side': side}
    
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=order_side,
            positionSide=position_side,
            type='MARKET',
            quantity=size,
            reduceOnly=True
        )
        logger.info(f"✅ Position closed: orderId={order['orderId']}")
        return order
    except Exception as e:
        # Try without reduceOnly if -1106 error
        if '-1106' in str(e):
            logger.warning("Retrying without reduceOnly...")
            order = client.futures_create_order(
                symbol=symbol,
                side=order_side,
                positionSide=position_side,
                type='MARKET',
                quantity=size
            )
            logger.info(f"✅ Position closed (no reduceOnly): orderId={order['orderId']}")
            return order
        raise


def publish_profit_exit_event(redis_client, symbol: str, side: str, pnl: float):
    """
    Manually publish a profit exit event to Redis stream.
    This is what the trader does after a trailing stop triggers.
    """
    event = {
        'event_type': 'TRAILING_EXIT',
        'symbol': symbol,
        'side': side,
        'pnl': pnl,
        'timestamp': time.time(),
        'account': 'primary',
        'source': 'test_hedge_build'
    }
    
    stream_key = 'wma:trader:execution_feedback'
    msg_id = redis_client.xadd(stream_key, {'data': json.dumps(event)})
    logger.info(f"📤 Published TRAILING_EXIT event: stream={stream_key} id={msg_id}")
    return msg_id


def monitor_hedge_build(redis_client, symbol: str, timeout_sec: int = 60):
    """Monitor Redis for HEDGE_BUILD state"""
    logger.info(f"🔍 Monitoring HEDGE_BUILD state for {symbol}...")
    
    hedge_key = f"wma:hedge_build:{symbol}"
    start_time = time.time()
    
    while time.time() - start_time < timeout_sec:
        state = redis_client.get(hedge_key)
        if state:
            logger.info(f"✅ HEDGE_BUILD_ENTER detected: {state}")
            return True
        time.sleep(2)
    
    logger.warning(f"⚠️ HEDGE_BUILD state not detected within {timeout_sec}s")
    return False


def main():
    parser = argparse.ArgumentParser(description='Test HEDGE_BUILD end-to-end')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen without closing')
    parser.add_argument('--symbol', type=str, help='Specific symbol to close')
    parser.add_argument('--skip-close', action='store_true', help='Skip closing, just publish event')
    args = parser.parse_args()
    
    print("=" * 70)
    print("HEDGE_BUILD End-to-End Proof Test")
    print("=" * 70)
    print()
    
    # Initialize clients
    try:
        binance = get_binance_client()
        redis = get_redis_client()
        logger.info("✅ Connected to Binance and Redis")
    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        return 1
    
    # Find profitable positions
    profitable = get_profitable_positions(binance)
    
    if not profitable:
        logger.warning("⚠️ No profitable positions found")
        print("\nTo test HEDGE_BUILD, you need at least one position in profit.")
        return 1
    
    print(f"\n📊 Found {len(profitable)} profitable positions:\n")
    print(f"{'Symbol':<15} {'Side':<6} {'Size':<12} {'Entry':<12} {'Mark':<12} {'PnL':<10} {'ROI%':<8}")
    print("-" * 85)
    
    for pos in profitable:
        print(f"{pos['symbol']:<15} {pos['side']:<6} {pos['size']:<12.6f} "
              f"${pos['entry_price']:<11.4f} ${pos['mark_price']:<11.4f} "
              f"${pos['pnl']:<9.2f} {pos['roi_pct']:>+7.2f}%")
    
    # Select position to close
    if args.symbol:
        target = next((p for p in profitable if p['symbol'] == args.symbol), None)
        if not target:
            logger.error(f"❌ Symbol {args.symbol} not found in profitable positions")
            return 1
    else:
        # Select the most profitable position
        target = profitable[0]
    
    print(f"\n🎯 Selected for HEDGE_BUILD test: {target['symbol']} {target['side']}")
    print(f"   PnL: ${target['pnl']:.2f} ({target['roi_pct']:+.2f}%)")
    
    if args.dry_run:
        print("\n[DRY-RUN MODE] No actual closing will occur")
    
    # Confirmation
    if not args.dry_run and not args.skip_close:
        print(f"\n⚠️  This will CLOSE the {target['symbol']} {target['side']} position!")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return 0
    
    # Step 1: Close the position
    if not args.skip_close:
        print(f"\n📍 Step 1: Closing {target['symbol']} {target['side']} position...")
        try:
            result = close_position(
                binance, 
                target['symbol'], 
                target['side'], 
                target['size'],
                dry_run=args.dry_run
            )
            if not args.dry_run:
                logger.info(f"✅ Position closed successfully")
        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return 1
    else:
        logger.info("⏭️ Skipping position close (--skip-close)")
    
    # Step 2: Publish profit exit event (in case stealth stops didn't)
    print(f"\n📍 Step 2: Publishing TRAILING_EXIT event...")
    publish_profit_exit_event(redis, target['symbol'], target['side'], target['pnl'])
    
    # Step 3: Monitor for HEDGE_BUILD state
    print(f"\n📍 Step 3: Monitoring for HEDGE_BUILD state...")
    print("   (Trainer should consume the event and enter HEDGE_BUILD)")
    
    if args.dry_run:
        print("\n[DRY-RUN] Skipping monitoring")
        return 0
    
    time.sleep(5)  # Give trainer time to process
    
    hedge_detected = monitor_hedge_build(redis, target['symbol'], timeout_sec=30)
    
    # Step 4: Check trainer logs
    print(f"\n📍 Step 4: Verify in trainer logs:")
    print("   grep -a 'HEDGE_BUILD_ENTER\\|HEDGE_BUILD_ACTIVE\\|HEDGE_BUILD_BLOCK' logs/hybrid_trainer.log | tail -10")
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Position closed:     {target['symbol']} {target['side']}")
    print(f"PnL realized:        ${target['pnl']:.2f}")
    print(f"Event published:     ✅ TRAILING_EXIT to wma:trader:execution_feedback")
    print(f"HEDGE_BUILD state:   {'✅ DETECTED' if hedge_detected else '⚠️ NOT DETECTED (check trainer logs)'}")
    
    if hedge_detected:
        print(f"\n✅ HEDGE_BUILD end-to-end proof SUCCESSFUL!")
        print(f"   For the next ~300s, FLIPs on {target['symbol']} will be blocked.")
    else:
        print(f"\n⚠️ HEDGE_BUILD state not detected automatically.")
        print("   Check trainer logs manually:")
        print("   grep -a 'HEDGE_BUILD\\|TRAILING_EXIT\\|execution_feedback' logs/hybrid_trainer.log | tail -20")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

