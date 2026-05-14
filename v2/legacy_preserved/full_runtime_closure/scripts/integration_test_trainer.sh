#!/bin/bash
# Integration Test for Trainer
# Tests with local Redis and seeded data

set -e

echo "=" | head -c 80
echo ""
echo "🧪 INTEGRATION TEST - Trainer with Local Redis"
echo "=" | head -c 80
echo ""

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "❌ Redis is not running. Please start Redis first:"
    echo "   redis-server --port 6379"
    exit 1
fi

echo "✅ Redis is running"

# Seed test data
echo "📝 Seeding test data..."
python3 << 'EOF'
import redis
import json
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Seed unified_features for BTCUSDT:5m
key = "unified_features:BTCUSDT:5m"
data = {
    'ccxt_open': '50000.0',
    'ccxt_high': '51000.0',
    'ccxt_low': '49000.0',
    'ccxt_close': '50500.0',
    'ccxt_volume': '1000.0',
    'coinank_liquidation_long': '1000000.0',
    'coinank_liquidation_short': '800000.0',
    'tm_grade': 'B',
    'ob_bid_depth': '500000.0',
    'ob_ask_depth': '500000.0',
    'ob_spread': '0.001',
    'ob_imbalance': '0.0',
    'ind_rsi': '55.0',
    'ind_macd': '100.0',
    'ts_ms': str(int(time.time() * 1000))
}

r.hset(key, mapping=data)
print(f"✅ Seeded {key}")

# Seed price feed
price_key = "market:BTCUSDT:1m"
price_data = json.dumps({'close': 50500.0, 'timestamp': int(time.time() * 1000)})
r.set(price_key, price_data)
print(f"✅ Seeded {price_key}")

print("✅ Test data seeded successfully")
EOF

# Run trainer in live mode
echo ""
echo "🚀 Starting trainer in live mode..."
echo ""

python3 -m rl.hybrid_trainer --mode predict --training-mode live --enhanced-features &
TRAINER_PID=$!

# Wait for trainer to start
sleep 10

# Check if trainer is still running
if ! kill -0 $TRAINER_PID 2>/dev/null; then
    echo "❌ Trainer crashed during startup"
    exit 1
fi

echo "✅ Trainer started successfully (PID: $TRAINER_PID)"
echo "⏳ Running for 60 seconds..."

# Wait and monitor
sleep 60

# Check if trainer is still running
if ! kill -0 $TRAINER_PID 2>/dev/null; then
    echo "❌ Trainer crashed during test"
    exit 1
fi

# Stop trainer
kill $TRAINER_PID 2>/dev/null || true
wait $TRAINER_PID 2>/dev/null || true

echo ""
echo "=" | head -c 80
echo ""
echo "✅ INTEGRATION TEST PASSED"
echo "=" | head -c 80
echo ""









































