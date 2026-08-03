#!/bin/bash
# Day 5: Start Phase C Data Source Ingestors
# Launches all 4 new ingestors in parallel and monitors their startup

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CLI_DIR="$REPO_ROOT/v2/backend/app/cli"
LOG_DIR="$REPO_ROOT/v2/runtime/phase_c_ingestors"

echo "================================"
echo "🚀 Phase C Data Source Startup"
echo "================================"
echo ""

if [ "${V2_PHASE_C_ALLOW_RUNTIME_START:-0}" != "1" ]; then
    echo "Runtime start is blocked by default."
    echo "Set V2_PHASE_C_ALLOW_RUNTIME_START=1 only after provider credentials, budgets, and actual-data checks are configured."
    echo ""
    echo "Read-only Redis checks:"
    echo "  redis-cli --scan --pattern 'v2:microstructure:*' | wc -l"
    echo "  redis-cli --scan --pattern 'v2:onchain:*' | wc -l"
    echo "  redis-cli --scan --pattern 'v2:crossexchange:*' | wc -l"
    echo "  redis-cli --scan --pattern 'v2:liquidation:enhanced:*' | wc -l"
    exit 2
fi

mkdir -p "$LOG_DIR"

# Configuration
SYMBOLS="BTCUSDT,ETHUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,SOLUSDT,MATICUSDT,LINKUSDT,AVAXUSDT"
ORDERBOOK_INTERVAL=60
LIQUIDATION_INTERVAL=60
CROSSEXCHANGE_INTERVAL=300
TOKENMETRICS_INTERVAL=3600

if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
        PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
    else
        PYTHON_BIN="python3"
    fi
fi
export PYTHONPATH="$REPO_ROOT/v2/backend${PYTHONPATH:+:$PYTHONPATH}"

# Function to start an ingestor
start_ingestor() {
    local name=$1
    local script=$2
    local interval=$3
    local log_file="$LOG_DIR/${name}.log"

    echo "📍 Starting: $name"
    echo "   Script: $script"
    echo "   Interval: ${interval}s"
    echo "   Log: $log_file"

    cd "$REPO_ROOT"
    "$PYTHON_BIN" "$script" \
        --symbols "$SYMBOLS" \
        --interval "$interval" \
        --loop \
        >> "$log_file" 2>&1 &

    local pid=$!
    echo "   PID: $pid"
    echo "$pid" > "$LOG_DIR/${name}.pid"
    echo ""
}

# Start all 4 ingestors
start_ingestor "coinapi_orderbook_ingestor" "$CLI_DIR/v2_coinapi_orderbook_ingestor.py" "$ORDERBOOK_INTERVAL"
start_ingestor "tokenmetrics_onchain_ingestor" "$CLI_DIR/v2_tokenmetrics_onchain_ingestor.py" "$TOKENMETRICS_INTERVAL"
start_ingestor "crossexchange_analyzer" "$CLI_DIR/v2_crossexchange_analyzer.py" "$CROSSEXCHANGE_INTERVAL"
start_ingestor "liquidation_enhanced" "$CLI_DIR/v2_liquidation_enhanced.py" "$LIQUIDATION_INTERVAL"

echo "✅ All ingestors started"
echo ""

# Monitor startup
echo "📊 Monitoring startup..."
sleep 5

# Check if processes are running
for name in coinapi_orderbook_ingestor tokenmetrics_onchain_ingestor crossexchange_analyzer liquidation_enhanced; do
    pid_file="$LOG_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "✅ $name (PID $pid) - RUNNING"
        else
            echo "❌ $name (PID $pid) - FAILED"
        fi
    fi
done

echo ""
echo "📁 Log files:"
for log in "$LOG_DIR"/*.log; do
    if [ -f "$log" ]; then
        echo "   $(basename "$log"): $(wc -l < "$log") lines"
    fi
done

echo ""
echo "================================"
echo "✅ Phase C Startup Complete"
echo "================================"
echo ""
echo "Next: Test Redis data flow with:"
echo "  redis-cli --scan --pattern 'v2:microstructure:*' | wc -l"
echo "  redis-cli --scan --pattern 'v2:onchain:*' | wc -l"
echo "  redis-cli --scan --pattern 'v2:crossexchange:*' | wc -l"
echo "  redis-cli --scan --pattern 'v2:liquidation:enhanced:*' | wc -l"
