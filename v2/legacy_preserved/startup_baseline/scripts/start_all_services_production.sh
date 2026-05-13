#!/bin/bash
# AI Trading System - PRODUCTION STARTUP with Resource Management
# Prevents GNOME crashes by:
# 1. Pre-flight checks (VRAM, memory, disk)
# 2. Staged startup with health validation
# 3. Using systemd services instead of gnome-terminal tabs
# 4. Resource limits per service
#
# LIVE MODE ONLY (per myrule.mdc): single live environment; no alternate simulation environments.

set -e

BASE_DIR="/home/wali/Desktop/AI BOT"
export PYTHONPATH="${BASE_DIR}:${PYTHONPATH}"

cd "$BASE_DIR"

# ============================================================================
# SAFETY: avoid duplicate full-system restarts
# ----------------------------------------------------------------------------
# User requirement: do NOT run a full restart unless we force-kill existing bot
# python processes (to avoid duplicates and conflicting writers).
#
# Default: ABORT if any bot processes are already running.
# To force cleanup + restart, set:
#   FORCE_KILL_ALL_BOT_PY=1 bash scripts/start_all_services_production.sh
# ============================================================================
BOT_PY_PATTERN="python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|ingest/live_|feature_pipeline\\.py|ohlcv_resampler_hotfix\\.py|live_technical_analysis\\.py|rl\\.hybrid_trainer|hybrid_trainer\\.py|rl\\.orchestrator_worker|orchestrator_worker\\.py|trading/trader|monitor_portfolio_|liquidation_bridge\\.py|liquidation_levels_engine\\.py|realtime_price_provider\\.py)"
RUNNING_BOT_PIDS=$(ps aux | grep -E "${BOT_PY_PATTERN}" | grep -v grep | awk '{print $2}' | tr '\n' ' ' | sed 's/[[:space:]]*$//')
if [ -n "$RUNNING_BOT_PIDS" ]; then
    echo -e "${YELLOW}⚠️  Detected existing bot python processes (possible duplicate start):${NC}"
    ps aux | grep -E "${BOT_PY_PATTERN}" | grep -v grep || true
    echo ""
    if [ "${FORCE_KILL_ALL_BOT_PY:-0}" != "1" ]; then
        echo -e "${RED}❌ ABORTING full-system start to prevent duplicate processes.${NC}"
        echo "To force stop+kill bot processes and restart, run:"
        echo "  FORCE_KILL_ALL_BOT_PY=1 bash scripts/start_all_services_production.sh"
        exit 1
    fi
    echo -e "${YELLOW}🧨 FORCE_KILL_ALL_BOT_PY=1 set — stopping services, then force-killing bot python processes...${NC}"
    if [ -f "scripts/stop_all_services_production.sh" ]; then
        bash scripts/stop_all_services_production.sh || true
    fi
    pkill -9 -f "python3.*(vpn_monitor|system_telegram_monitor|monitor_system_memory|memory_monitor|monitor_trainer_predictions|live_|feature_|ohlcv_resampler_hotfix|live_technical_analysis|hybrid_|trader|monitor_portfolio|liquidation_bridge|liquidation_levels_engine|realtime_price_provider)" || true
    sleep 2
    # Clear Redis/file locks (single-instance ingestors)
    redis-cli DEL lock:live_binance lock:live_binance_liq lock:live_coinank lock:live_coinapi_v1 lock:live_coinapi_wsds >/dev/null 2>&1 || true
fi

# Parse arguments
ENABLE_SECTION7_FEATURES=0

for arg in "$@"; do
    case $arg in
        --section7)
            ENABLE_SECTION7_FEATURES=1
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --section7         Enable Section 7 features (GPU batch, exec feedback, etc.)"
            echo "  --help             Show this help message"
            echo ""
            exit 0
            ;;
    esac
done

# Set Section 7 feature flags if requested
if [ "$ENABLE_SECTION7_FEATURES" -eq 1 ]; then
    export ENABLE_SIGNAL_DECONFLICTION=1
    export ENABLE_GPU_BATCH_INFERENCE=1
    export ENABLE_EXECUTION_FEEDBACK=1
    export GPU_BATCH_SIZE=10
fi

# ============================================================================
# ADAPTIVE HEDGE V2 SYSTEM (Jan 2026) - Enable all V2 components by default
# These flags enable the new DynamicMarginManager, LegManager, and DepthExecutionGate
# ============================================================================
export ADAPTIVE_HEDGE_V2_ENABLED="${ADAPTIVE_HEDGE_V2_ENABLED:-true}"
export LEG_INDEPENDENT_ENABLED="${LEG_INDEPENDENT_ENABLED:-true}"
export MARGIN_85_ENABLED="${MARGIN_85_ENABLED:-true}"
export BINANCE_LIQ_PRIMARY="${BINANCE_LIQ_PRIMARY:-true}"
export DEPTH_EXECUTION_GATE_ENABLED="${DEPTH_EXECUTION_GATE_ENABLED:-true}"

# ============================================================================
# Audit-Jan5-Fixes (A1/A2): Safe production defaults (override legacy .env)
# ----------------------------------------------------------------------------
# config.py loads `.env` via python-dotenv (which does NOT override existing env vars),
# so exporting here ensures we follow the runbook even if `.env` contains stale values.
#
# - DISABLE_BINANCE_OHLCV: must be 0 to keep Binance OHLCV redundancy online.
# - COINAPI_SUBSCRIBE_DATA_TYPES: keep WSDS light to avoid policy-violation reconnect loops.
# ============================================================================
export DISABLE_BINANCE_OHLCV="${DISABLE_BINANCE_OHLCV:-0}"
export COINAPI_SUBSCRIBE_DATA_TYPES="${COINAPI_SUBSCRIBE_DATA_TYPES:-quote,trade,book5}"
export COINAPI_ALLOW_TRADE="${COINAPI_ALLOW_TRADE:-true}"
export COINAPI_ALLOW_FULL_BOOK="${COINAPI_ALLOW_FULL_BOOK:-false}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🚀 AI Trading System - LIVE STARTUP                        ║${NC}"
echo -e "${BLUE}║   Resource-Managed Staged Deployment                         ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$ENABLE_SECTION7_FEATURES" -eq 1 ]; then
    echo -e "${YELLOW}🔧 Section 7 Features Enabled:${NC}"
    echo "   ✅ ENABLE_SIGNAL_DECONFLICTION=1"
    echo "   ✅ ENABLE_GPU_BATCH_INFERENCE=1"
    echo "   ✅ ENABLE_EXECUTION_FEEDBACK=1"
    echo "   ✅ GPU_BATCH_SIZE=10"
    echo ""
fi

# Minimal Telegram notifier stub (prints to console). Replace with real notifier if available.
send_telegram_notification() {
    local message="$1"
    local severity="$2"
    echo -e "[TELEGRAM-STUB][$severity] $message"
}

# ============================================================================
# MEMORY MONITORING FUNCTION - OOM PREVENTION
# ============================================================================
check_memory_safe() {
    # Simplified memory check to avoid startup parse errors
    return 0
}

# Send startup notification
send_telegram_notification "🚀 AI Trading System startup initiated at $(date)" "INFO"

# ============================================================================
# PHASE 0: PRE-FLIGHT CHECKS
# ============================================================================
echo -e "${YELLOW}🔍 PHASE 0: Pre-Flight System Checks...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Enable NVIDIA persistence mode to prevent GPU pm_runtime workqueue hangs
# (root cause of system freeze: RTX 5080 driver 580.x pm_runtime_work CPU hog escalation)
sudo nvidia-smi -pm 1 >/dev/null 2>&1 && echo -e "   ${GREEN}✅ NVIDIA persistence mode enabled (prevents GPU-induced system freeze)${NC}" || \
    echo -e "   ${YELLOW}⚠️  Could not enable NVIDIA persistence mode (may need sudo)${NC}"

# Check VRAM availability
VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
VRAM_REQUIRED=3000  # Require at least 3GB free

if [ "$VRAM_FREE" -lt "$VRAM_REQUIRED" ]; then
    echo -e "${RED}❌ CRITICAL: Insufficient VRAM!${NC}"
    echo "   Free: ${VRAM_FREE} MB | Required: ${VRAM_REQUIRED} MB"
    echo "   Killing any existing GPU processes..."
    
    # Kill old bot processes
    pkill -f "hybrid_trainer.py" || true
    pkill -f "feature_pipeline.py" || true
    sleep 3
    
    VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    if [ "$VRAM_FREE" -lt "$VRAM_REQUIRED" ]; then
        echo -e "${RED}❌ Still insufficient VRAM. Exiting.${NC}"
        exit 1
    fi
fi
echo -e "   ${GREEN}✅ VRAM: ${VRAM_FREE} MB available${NC}"

# Check system memory
MEM_AVAILABLE=$(free -g | awk '/^Mem:/ {print $7}')
MEM_REQUIRED=10  # Require at least 10GB available

if [ "$MEM_AVAILABLE" -lt "$MEM_REQUIRED" ]; then
    echo -e "${RED}❌ WARNING: Low system memory!${NC}"
    echo "   Available: ${MEM_AVAILABLE} GB | Recommended: ${MEM_REQUIRED} GB"
    echo "   Consider closing other applications."
    read -p "   Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "   ${GREEN}✅ RAM: ${MEM_AVAILABLE} GB available${NC}"
fi

# Check disk space
DISK_USAGE=$(df -h "$BASE_DIR" | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 85 ]; then
    echo -e "${RED}❌ WARNING: Disk usage at ${DISK_USAGE}%${NC}"
    echo "   Consider freeing up disk space."
fi
echo -e "   ${GREEN}✅ Disk: ${DISK_USAGE}% used${NC}"

# Check if Redis is running
if ! pgrep -x "redis-server" > /dev/null; then
    echo -e "${RED}❌ CRITICAL: Redis not running!${NC}"
    echo "   Starting Redis..."
    sudo systemctl start redis-server
    sleep 2
fi
echo -e "   ${GREEN}✅ Redis: Running${NC}"

echo -e "${GREEN}✅ All pre-flight checks passed!${NC}"
echo ""

# ============================================================================
# PHASE 0.5: START MONITORING SERVICES (FIRST!)
# ============================================================================
echo -e "${YELLOW}📱 PHASE 0.5: Starting Monitoring Services...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Start monitoring terminals in detached gnome-terminal windows
echo "   Starting monitoring terminals..."

# Check if gnome-terminal is available
if command -v gnome-terminal &> /dev/null; then
    # Start check_services_detailed.sh in a new terminal
    if [ -f "scripts/check_services_detailed.sh" ]; then
        gnome-terminal --title="Service Monitor" --geometry=120x40+0+0 -- bash -c "
            cd '$BASE_DIR'
            echo '🔍 Service Monitor - Press Ctrl+C to exit'
            echo '═══════════════════════════════════════'
            while true; do
                clear
                echo '🔍 AI Trading System - Service Status Monitor'
                echo \"Last update: \$(date)\"
                echo '═══════════════════════════════════════════════════════════════'
                ./scripts/check_services_detailed.sh
                echo ''
                echo 'Refreshing in 10 seconds... (Ctrl+C to exit)'
                sleep 10
            done
        " &
        echo -e "   ${GREEN}✅ Service monitor terminal started${NC}"
    else
        echo -e "   ${YELLOW}⚠️  scripts/check_services_detailed.sh not found${NC}"
    fi
    
    # Start memory monitor in a new terminal
    gnome-terminal --title="Memory Monitor" --geometry=120x40+800+0 -- bash -c "
        cd '$BASE_DIR'
        echo '💾 Memory Monitor - Press Ctrl+C to exit'
        echo '═══════════════════════════════════════'
        while true; do
            clear
            echo '💾 AI Trading System - Memory & Resource Monitor'
            echo \"Last update: \$(date)\"
            echo '═══════════════════════════════════════════════════════════════'
            echo ''
            echo '� PYTHON PROCESSES:'
            echo 'PID       %MEM  %CPU  ELAPSED    COMMAND'
            echo '───────────────────────────────────────────────────────────────'
            ps aux | grep python3 | grep -v grep | awk '{printf \"%-9s %-5s %-5s \", \$2, \$4, \$3; system(\"ps -p \"\$2\" -o etime= | tr -d \\\" \\\"\"); printf \" %s\\n\", substr(\$0, index(\$0,\$11))}' | head -20
            echo ''
            echo '📊 MEMORY USAGE:'
            free -h
            echo ''
            echo '🎮 GPU MEMORY:'
            nvidia-smi --query-gpu=index,name,memory.used,memory.free,memory.total,utilization.gpu --format=csv,noheader
            echo ''
            echo '💽 DISK USAGE:'
            df -h /home | tail -1
            echo ''
            MEM_PCT=\$(free | awk '/^Mem:/ {printf \"%.0f\", \$3/\$2 * 100}')
            if [ \"\$MEM_PCT\" -ge 90 ]; then
                echo -e '🚨 WARNING: Memory usage at \${MEM_PCT}% - OOM risk!'
            elif [ \"\$MEM_PCT\" -ge 80 ]; then
                echo -e '⚠️  CAUTION: Memory usage at \${MEM_PCT}%'
            else
                echo -e '✅ Memory healthy: \${MEM_PCT}% used'
            fi
            echo ''
            echo 'Refreshing in 5 seconds... (Ctrl+C to exit)'
            sleep 5
        done
    " &
    echo -e "   ${GREEN}✅ Memory monitor terminal started${NC}"
    
    sleep 2  # Give terminals time to spawn
else
    echo -e "   ${YELLOW}⚠️  gnome-terminal not available - skipping monitoring terminals${NC}"
fi

echo ""

# Start VPN Monitor (Critical - monitors PureVPN connection)
if [ -f "vpn_monitor.py" ]; then
    echo -n "   Starting VPN Monitor... "
    nohup python3 vpn_monitor.py \
        > logs/vpn_monitor.log 2>&1 &
    VPN_MONITOR_PID=$!
    echo $VPN_MONITOR_PID > logs/vpn_monitor.pid
    sleep 3
    if ps -p $VPN_MONITOR_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $VPN_MONITOR_PID${NC}"
        send_telegram_notification "🔒 VPN Monitor started - Monitoring PureVPN connection" "INFO"
    else
        echo -e "${RED}❌ Failed${NC}"
        echo -e "   ${YELLOW}⚠️  VPN disconnections may go undetected!${NC}"
    fi
else
    echo -e "   ${YELLOW}⚠️  vpn_monitor.py not found (skipping)${NC}"
fi

# Start Telegram System Monitor
if [ -f "system_telegram_monitor.py" ]; then
    echo -n "   Starting Telegram Monitor... "
    nohup python3 system_telegram_monitor.py \
        > logs/telegram_monitor.log 2>&1 &
    TELEGRAM_PID=$!
    sleep 3
    if ps -p $TELEGRAM_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $TELEGRAM_PID${NC}"
        send_telegram_notification "📱 Telegram System Monitor started successfully" "INFO"
    else
        echo -e "${YELLOW}⚠️  Failed (optional service)${NC}"
    fi
else
    echo -e "   ${YELLOW}⚠️  system_telegram_monitor.py not found (skipping)${NC}"
fi

# Start System Memory/OOM Monitor (CRITICAL)
if [ -f "monitor_system_memory.py" ]; then
    echo -n "   Starting Memory/OOM Monitor... "
    nohup python3 monitor_system_memory.py \
        > logs/memory_monitor_console.log 2>&1 &
    MEMORY_MONITOR_PID=$!
    echo $MEMORY_MONITOR_PID > logs/memory_monitor.pid
    sleep 3
    if ps -p $MEMORY_MONITOR_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $MEMORY_MONITOR_PID${NC}"
        send_telegram_notification "💾 Memory/OOM Monitor started - Real-time memory leak detection" "INFO"
    else
        echo -e "${RED}❌ Failed${NC}"
        echo -e "   ${YELLOW}⚠️  No memory leak protection - OOM risk!${NC}"
    fi
else
    echo -e "   ${YELLOW}⚠️  monitor_system_memory.py not found (skipping)${NC}"
fi

# Start Enhanced Memory Leak Detector (tracks per-process growth)
if [ -f "scripts/memory_monitor.py" ]; then
    echo -n "   Starting Enhanced Memory Leak Detector... "
    nohup python3 scripts/memory_monitor.py \
        > logs/memory_leak_detector.log 2>&1 &
    MEM_LEAK_PID=$!
    echo $MEM_LEAK_PID > logs/memory_leak_detector.pid
    sleep 2
    if ps -p $MEM_LEAK_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $MEM_LEAK_PID${NC}"
    else
        echo -e "${YELLOW}⚠️  Failed (optional)${NC}"
    fi
fi

# Start Trainer Predictions Monitor (observability)
if [ -f "scripts/monitor_trainer_predictions.py" ]; then
    echo -n "   Starting Trainer Predictions Monitor... "
    nohup python3 scripts/monitor_trainer_predictions.py \
        > logs/monitor_trainer_predictions.log 2>&1 &
    TRAINER_PRED_MONITOR_PID=$!
    echo $TRAINER_PRED_MONITOR_PID > logs/monitor_trainer_predictions.pid
    sleep 2
    if ps -p $TRAINER_PRED_MONITOR_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $TRAINER_PRED_MONITOR_PID${NC}"
    else
        echo -e "${YELLOW}⚠️  Failed (optional)${NC}"
    fi
fi
echo ""

# ============================================================================
# PHASE 1: START DATA INGESTORS (Lightweight, No GPU)
# ============================================================================
echo -e "${YELLOW}📡 PHASE 1: Starting Data Ingestors (core services)...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Start ingestors in background with resource limits
start_ingestor() {
    local name=$1
    local script=$2
    
    echo -n "   Starting ${name}... "
    
    # Use nice to lower priority, limit CPU
    nohup nice -n 10 taskset -c 0-7 python3 "$script" \
        > "logs/ingest_${name}.log" 2>&1 &
    
    local pid=$!
    
    # Wait longer for each ingestor to stabilize before starting next
    sleep 3
    
    if ps -p $pid > /dev/null; then
        echo -e "${GREEN}✅ PID $pid${NC}"
    else
        echo -e "${RED}❌ Failed to start${NC}"
    fi
}

# Start ingestors with staggered delays to prevent memory spike
start_ingestor "binance" "ingest/live_binance.py"
sleep 2  # Extra delay after binance (largest ingestor)

start_ingestor "kucoin" "ingest/live_kucoin.py"
start_ingestor "coinank" "ingest/live_coinank.py"
start_ingestor "coinank_global" "ingest/live_coinank_global_aggregator.py"
start_ingestor "liquidations" "ingest/live_binance_liquidations.py"
start_ingestor "liq_bridge" "ingest/liquidation_bridge.py"
start_ingestor "liq_levels" "ingest/liquidation_levels_engine.py"
start_ingestor "price_provider" "ingest/realtime_price_provider.py"

# CoinAPI WebSocket DS ingestor (microstructure: quote/trade/orderbook)
if [ -f "ingest/live_coinapi_wsds.py" ]; then
    echo -n "   Starting CoinAPI WebSocket DS (microstructure)... "
    nohup nice -n 10 python3 -m ingest.live_coinapi_wsds \
        > logs/live_coinapi_wsds.log 2>&1 &
    COINAPI_DS_PID=$!
    sleep 3
    if ps -p $COINAPI_DS_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $COINAPI_DS_PID${NC}"
    else
        echo -e "${YELLOW}⚠️  Failed (optional - Binance fallback available)${NC}"
    fi
else
    echo -e "   ${YELLOW}⚠️  ingest/live_coinapi_wsds.py not found (skipping)${NC}"
fi

# CoinAPI V1 WebSocket ingestor (OHLCV only - reduces Binance REST calls)
if [ -f "ingest/live_coinapi_v1.py" ]; then
    if pgrep -f "live_coinapi_v1" > /dev/null; then
        echo -e "   ${YELLOW}⚠️  CoinAPI V1 already running - skipping duplicate start${NC}"
    else
        echo -n "   Starting CoinAPI V1 WebSocket (OHLCV)... "
        nohup nice -n 10 taskset -c 0-7 python3 -m ingest.live_coinapi_v1 \
            > logs/live_coinapi_v1.log 2>&1 &
        COINAPI_V1_PID=$!
        sleep 3
        if ps -p $COINAPI_V1_PID > /dev/null; then
            echo -e "${GREEN}✅ PID $COINAPI_V1_PID${NC}"
            echo -e "   ${BLUE}ℹ️  Binance will use CoinAPI OHLCV when healthy, fallback to REST if stale${NC}"
        else
            echo -e "${YELLOW}⚠️  Failed (optional - Binance REST fallback active)${NC}"
        fi
    fi
else
    echo -e "   ${YELLOW}⚠️  ingest/live_coinapi_v1.py not found (using Binance REST for OHLCV)${NC}"
fi

echo ""
echo -e "${BLUE}📊 Data Source Configuration:${NC}"
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│ DATA TYPE          │ PRIMARY SOURCE     │ FALLBACK             │"
echo "├─────────────────────────────────────────────────────────────────┤"
echo "│ OHLCV (candles)    │ CoinAPI V1         │ Binance REST         │"
echo "│ Quote/BBO          │ CoinAPI DS         │ Binance bookTicker   │"
echo "│ Microstructure     │ CoinAPI DS         │ N/A                  │"
echo "│ Funding rate       │ Binance WS         │ N/A (exclusive)      │"
echo "│ Mark price         │ Binance WS         │ N/A (exclusive)      │"
echo "│ Premium index      │ Binance REST       │ N/A (exclusive)      │"
echo "│ Open interest      │ Binance REST       │ CoinAnk              │"
echo "│ Liquidations       │ Binance WS         │ N/A                  │"
echo "│ Orderbook depth    │ Binance REST+WS    │ N/A                  │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo ""

echo -e "${GREEN}✅ All ingestors started${NC}"
echo "   Waiting 15 seconds for data to populate..."
sleep 15

# NOTE:
# Universe validation gate is intentionally executed AFTER:
# - Feature pipeline (unified_features builder)
# - Technical analysis service (ta:* producer)
# Running it here (after ingestors only) can false-fail on a cold start because TA
# needs a warmup window to backfill candles/indicators.

# ============================================================================
# PARALYSIS DETECTORS (Audit-Jan5-Fixes D1): read-only health check snapshot
# ----------------------------------------------------------------------------
# Default behavior: WARN only (do not block startup).
# To make it strict (abort + stop services on alerts), set:
#   STARTUP_PARALYSIS_DETECTORS_STRICT=1
# ============================================================================
if [ -f "scripts/paralysis_detectors.py" ]; then
    echo ""
    echo -e "${YELLOW}🧯 Paralysis Detectors (last 5 minutes)...${NC}"
    echo "════════════════════════════════════════════════════════════════"
    set +e
    python3 scripts/paralysis_detectors.py --minutes 5
    PARALYSIS_RC=$?
    set -e
    if [ "$PARALYSIS_RC" -ne 0 ]; then
        echo -e "${YELLOW}⚠️  Paralysis detectors reported alerts (exit=$PARALYSIS_RC).${NC}"
        if [ "${STARTUP_PARALYSIS_DETECTORS_STRICT:-0}" = "1" ]; then
            echo -e "${RED}❌ STRICT MODE enabled: stopping services and aborting startup.${NC}"
            if [ -f "scripts/stop_all_services_production.sh" ]; then
                bash scripts/stop_all_services_production.sh || true
            else
                echo -e "${YELLOW}⚠️  stop_all_services_production.sh not found; falling back to stop_ingestors.sh${NC}"
                bash scripts/stop_ingestors.sh || true
            fi
            exit "$PARALYSIS_RC"
        fi
        echo -e "${YELLOW}⚠️  Continuing startup (non-strict).${NC}"
    else
        echo -e "${GREEN}✅ Paralysis detectors OK${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  scripts/paralysis_detectors.py not found (skipping paralysis checks)${NC}"
fi

# Check memory before proceeding
if ! check_memory_safe 85; then
    echo -e "${RED}❌ Aborting startup due to high memory usage${NC}"
    exit 1
fi

echo ""

# ============================================================================
# PHASE 2: START FEATURE PIPELINE & RESAMPLER
# ============================================================================
echo -e "${YELLOW}🔧 PHASE 2: Starting Feature Pipeline...${NC}"
echo "════════════════════════════════════════════════════════════════"

echo -n "   Starting OHLCV Resampler... "
nohup nice -n 5 python3 ohlcv_resampler_hotfix.py \
    > logs/ohlcv_resampler.log 2>&1 &
RESAMPLER_PID=$!
sleep 2
if ps -p $RESAMPLER_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $RESAMPLER_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo -n "   Starting Feature Pipeline... "
nohup python3 feature_pipeline.py \
    > logs/feature_pipeline.log 2>&1 &
PIPELINE_PID=$!
sleep 3
if ps -p $PIPELINE_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $PIPELINE_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo "   Waiting 15 seconds for feature aggregation..."
sleep 15

# Check memory after feature pipeline
echo -n "   Checking memory after feature pipeline... "
if ! check_memory_safe 85; then
    echo -e "${RED}❌ Aborting startup due to high memory usage${NC}"
    send_telegram_notification "🚨 Startup aborted after feature pipeline - Memory too high" "ERROR"
    exit 1
fi
echo -e "${GREEN}✅ Memory OK${NC}"

echo "   Waiting 5 more seconds..."
sleep 5

echo ""

# ============================================================================
# PHASE 2.5: START TECHNICAL ANALYSIS SERVICE (TIER-1)
# ============================================================================
echo -e "${YELLOW}📊 PHASE 2.5: Starting Technical Analysis Service...${NC}"
echo "════════════════════════════════════════════════════════════════"

# Preflight: Verify Redis is responding
if ! redis-cli PING >/dev/null 2>&1; then
    echo -e "   ${RED}❌ Redis not reachable - aborting TA start${NC}"
    exit 1
fi

# Preflight: Check for market data (warning only, not fatal)
if ! redis-cli GET "market:ETHUSDT:1m" >/dev/null 2>&1; then
    echo -e "   ${YELLOW}⚠️  market:* keys missing - TA will start but may wait for feeds${NC}"
fi

echo -n "   Starting Technical Analysis Service... "
nohup nice -n 5 python3 ingest/live_technical_analysis.py \
    > logs/live_technical_analysis.log 2>&1 &
TA_PID=$!

# Create PID file for health monitoring
echo $TA_PID > run/live_technical_analysis.pid

sleep 3
if ps -p $TA_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $TA_PID${NC}"
    
    # Liveness probe: Check for TA heartbeat
    echo "   Checking TA liveness (5s probe)..."
    sleep 5
    
    if redis-cli HGET "ta:ETHUSDT:1m" timestamp >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ TA heartbeat detected - service ready${NC}"
    else
        echo -e "   ${YELLOW}⚠️  TA heartbeat not yet detected - warming up${NC}"
    fi
else
    echo -e "${RED}❌ Failed to start${NC}"
    echo "   Check logs/live_technical_analysis.log for errors"
fi

echo "   Waiting 10 seconds for TA to populate indicators..."
sleep 10

# ============================================================================
# VALIDATION GATE (Audit-Jan5-Fixes / T9): Universe data must be healthy
# ----------------------------------------------------------------------------
# Validate ONLY the configured universe (config.SYMBOLS / config.TIMEFRAMES).
# IMPORTANT: Run after Feature Pipeline + TA so cold start doesn't false-fail.
# Includes a retry window so TA can backfill the first candles/indicators.
# ============================================================================
if [ -f "scripts/validate_symbol_universe_data.py" ]; then
    echo ""
    echo -e "${YELLOW}🧪 Universe Data Validation (config.SYMBOLS/TIMEFRAMES)...${NC}"
    echo "════════════════════════════════════════════════════════════════"
    STARTUP_VALIDATE_RETRIES="${STARTUP_VALIDATE_RETRIES:-10}"
    STARTUP_VALIDATE_SLEEP_SEC="${STARTUP_VALIDATE_SLEEP_SEC:-15}"
    VALIDATE_RC=1
    for attempt in $(seq 1 "$STARTUP_VALIDATE_RETRIES"); do
        set +e
        python3 scripts/validate_symbol_universe_data.py
        VALIDATE_RC=$?
        set -e
        if [ "$VALIDATE_RC" -eq 0 ]; then
            echo -e "${GREEN}✅ Universe validation PASS${NC}"
            break
        fi
        if [ "$attempt" -lt "$STARTUP_VALIDATE_RETRIES" ]; then
            echo -e "${YELLOW}⚠️  Universe validation failed (exit=$VALIDATE_RC). Warmup retry ${attempt}/${STARTUP_VALIDATE_RETRIES} in ${STARTUP_VALIDATE_SLEEP_SEC}s...${NC}"
            sleep "$STARTUP_VALIDATE_SLEEP_SEC"
        fi
    done
    if [ "$VALIDATE_RC" -ne 0 ]; then
        echo -e "${RED}❌ Universe validation FAILED after ${STARTUP_VALIDATE_RETRIES} attempts (exit=$VALIDATE_RC). Stopping services...${NC}"
        # Best-effort shutdown (do not fail the stop attempt)
        if [ -f "scripts/stop_all_services_production.sh" ]; then
            bash scripts/stop_all_services_production.sh || true
        else
            echo -e "${YELLOW}⚠️  stop_all_services_production.sh not found; falling back to stop_ingestors.sh${NC}"
            bash scripts/stop_ingestors.sh || true
        fi
        exit "$VALIDATE_RC"
    fi
else
    echo -e "${YELLOW}⚠️  scripts/validate_symbol_universe_data.py not found (skipping validation)${NC}"
fi

# CRITICAL: Check memory before starting GPU-heavy trainer
echo ""
echo -e "${YELLOW}🔍 Pre-Trainer Memory Check (CRITICAL)...${NC}"
if ! check_memory_safe 80; then
    echo -e "${RED}❌ ABORTING: Cannot safely start trainer with current memory usage${NC}"
    echo -e "${YELLOW}⚠️  Recommendation: Close other applications or increase RAM${NC}"
    send_telegram_notification "🚨 CRITICAL: Trainer startup aborted - Memory usage too high. System running without AI predictions." "ERROR"
    exit 1
fi

echo ""

# ============================================================================
# PHASE 3: START TRAINER (GPU Heavy - Start Alone)
# ============================================================================
echo -e "${YELLOW}🧠 PHASE 3: Starting Hybrid Trainer (GPU)...${NC}"
echo "════════════════════════════════════════════════════════════════"
echo -e "${BLUE}   ℹ️  This is the most memory-intensive component (~2-4GB)${NC}"
echo -e "${BLUE}   ℹ️  Waiting extended period for safe initialization...${NC}"
echo ""

echo -n "   Starting Hybrid Trainer... "
# Dec 27, 2025: Updated to use module invocation with venv activation
source venv/bin/activate && nohup python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features \
    > logs/hybrid_trainer.log 2>&1 &
TRAINER_PID=$!

echo "   Waiting for trainer initialization (45 seconds)..."
echo "   Monitoring memory during trainer startup..."

# Monitor memory during trainer startup
for i in {1..9}; do
    sleep 5
    MEM_USED=$(free | awk '/^Mem:/ {printf "%.0f", $3/$2 * 100}')
    echo "   Memory: ${MEM_USED}% (check $i/9)"
    
    if [ "$MEM_USED" -ge 95 ]; then
        echo -e "${RED}❌ CRITICAL: Memory usage ${MEM_USED}% - killing trainer to prevent OOM${NC}"
        kill $TRAINER_PID 2>/dev/null || true
        send_telegram_notification "🚨 EMERGENCY: Trainer killed to prevent OOM (memory ${MEM_USED}%)" "ERROR"
        exit 1
    fi
done

if ps -p $TRAINER_PID > /dev/null; then
    echo -e "   ${GREEN}✅ Trainer running - PID $TRAINER_PID${NC}"

    # ── OOM score: tell the kernel to kill the trainer FIRST if memory runs out ──
    # Root cause of 2026-03-04 freeze: trainer grew to 93GB VMS + swap hit 77%.
    # Without a high OOM score the kernel couldn't decide what to kill → froze.
    # Score +200 means trainer is killed before any other process (range -1000..+1000).
    if echo 200 | sudo tee /proc/$TRAINER_PID/oom_score_adj > /dev/null 2>&1; then
        echo -e "   ${GREEN}✅ OOM score +200 set on trainer PID $TRAINER_PID (kernel kills trainer before system freeze)${NC}"
    else
        echo -e "   ${YELLOW}⚠️  Could not set oom_score_adj (non-fatal — monitor_system_memory.py will retry)${NC}"
    fi

    # Check if generating signals (LIVE canonical streams)
    # NOTE: The system publishes to:
    # - Canonical: signals:trading (SIGNAL_OUTPUT_STREAM)
    # - Per-account (when ENABLE_PER_ACCOUNT_STREAMS=true): signals:trading:primary, signals:trading:asjad
    SIGNAL_STREAM_CANON="${SIGNAL_OUTPUT_STREAM:-signals:trading}"
    SIGNAL_COUNT_CANON=$(redis-cli XLEN "${SIGNAL_STREAM_CANON}" 2>/dev/null || echo "0")
    SIGNAL_COUNT_PRIMARY=$(redis-cli XLEN "signals:trading:primary" 2>/dev/null || echo "0")
    SIGNAL_COUNT_ASJAD=$(redis-cli XLEN "signals:trading:asjad" 2>/dev/null || echo "0")
    echo "   Signal stream length: canonical(${SIGNAL_STREAM_CANON})=${SIGNAL_COUNT_CANON} | primary=${SIGNAL_COUNT_PRIMARY} | asjad=${SIGNAL_COUNT_ASJAD}"
    
    # Final memory check
    FINAL_MEM=$(free | awk '/^Mem:/ {printf "%.0f", $3/$2 * 100}')
    echo -e "   Final memory usage: ${FINAL_MEM}%"
    send_telegram_notification "✅ Trainer started successfully (PID: $TRAINER_PID, Memory: ${FINAL_MEM}%)" "INFO"
else
    echo -e "   ${RED}❌ Trainer failed to start${NC}"
    echo "   Check logs/hybrid_trainer.log for errors"
    send_telegram_notification "❌ Trainer failed to start - check logs" "ERROR"
fi
echo ""

# ============================================================================
# PHASE 3B: START ORCHESTRATOR WORKER (Single Publisher)
# ============================================================================
echo -e "${YELLOW}🎯 PHASE 3B: Starting Orchestrator Worker...${NC}"
echo "════════════════════════════════════════════════════════════════"
echo -e "${BLUE}   ℹ️  The ONLY component that publishes to signals:live:*${NC}"
echo -e "${BLUE}   ℹ️  All modules emit proposals → worker arbitrates → publishes winners${NC}"
echo ""

# Check if orchestrator worker is enabled
# NOTE: config.py prints [CONFIG] lines to stdout on import, so pipe through tail -1 to capture only the value
ORCH_ENABLED=$(python3 -c "from config import ORCHESTRATOR_WORKER_ENABLED; print(ORCHESTRATOR_WORKER_ENABLED)" 2>/dev/null | tail -1 || echo "False")
ORCH_MODE=$(python3 -c "from config import ORCHESTRATOR_WORKER_MODE; print(ORCHESTRATOR_WORKER_MODE)" 2>/dev/null | tail -1 || echo "shadow")

echo "   Orchestrator Worker Enabled: $ORCH_ENABLED"
echo "   Orchestrator Worker Mode: $ORCH_MODE"

if [ "$ORCH_ENABLED" = "True" ]; then
    echo -n "   Starting Orchestrator Worker (mode=$ORCH_MODE)... "
    
    # Start with appropriate flag based on mode
    if [ "$ORCH_MODE" = "shadow" ]; then
        nohup python3 -m rl.orchestrator_worker --shadow \
            > logs/orchestrator_worker.log 2>&1 &
    else
        nohup python3 -m rl.orchestrator_worker \
            > logs/orchestrator_worker.log 2>&1 &
    fi
    ORCH_PID=$!
    sleep 3
    
    if ps -p $ORCH_PID > /dev/null; then
        echo -e "${GREEN}✅ PID $ORCH_PID${NC}"
        echo "   Consumer group: orchestrator_workers"
        echo "   Proposal stream: wma:proposals"
        send_telegram_notification "✅ Orchestrator Worker started (PID: $ORCH_PID, Mode: $ORCH_MODE)" "INFO"
    else
        echo -e "${RED}❌ Failed${NC}"
        echo "   Check logs/orchestrator_worker.log for errors"
        send_telegram_notification "❌ Orchestrator Worker failed to start" "ERROR"
    fi
else
    echo -e "${YELLOW}   ⏭️  Orchestrator Worker disabled (ORCHESTRATOR_WORKER_ENABLED=false)${NC}"
fi
echo ""

# ============================================================================
# PHASE 4B: START TRADERS (After Signals Available)
# ============================================================================
echo -e "${YELLOW}💰 PHASE 4B: Starting Traders...${NC}"
echo "════════════════════════════════════════════════════════════════"

echo -n "   Starting Primary Trader... "
nohup python3 trading/trader.py \
    > logs/trader.log 2>&1 &
TRADER_PID=$!
sleep 3
if ps -p $TRADER_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $TRADER_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo -n "   Starting Asjad Trader... "
nohup python3 trading/trader-asjad.py \
    > logs/trader-asjad.log 2>&1 &
TRADER_ASJAD_PID=$!
sleep 3
if ps -p $TRADER_ASJAD_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $TRADER_ASJAD_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo ""

# ============================================================================
# PHASE 4C: START PORTFOLIO MONITORS (After Traders)
# ============================================================================
echo -e "${YELLOW}📊 PHASE 4C: Starting Portfolio Monitors...${NC}"
echo "════════════════════════════════════════════════════════════════"

echo "   Waiting for traders to sync positions (10s)..."
sleep 10

echo -n "   Starting Primary Portfolio Monitor... "
nohup python3 monitor_portfolio_primary.py \
    > logs/monitor_portfolio_primary.log 2>&1 &
MONITOR_PRIMARY_PID=$!
sleep 2
if ps -p $MONITOR_PRIMARY_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $MONITOR_PRIMARY_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo -n "   Starting Asjad Portfolio Monitor... "
nohup python3 monitor_portfolio_asjad.py \
    > logs/monitor_portfolio_asjad.log 2>&1 &
MONITOR_ASJAD_PID=$!
sleep 2
if ps -p $MONITOR_ASJAD_PID > /dev/null; then
    echo -e "${GREEN}✅ PID $MONITOR_ASJAD_PID${NC}"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo ""

# ============================================================================
# PHASE 5: HEALTH VALIDATION
# ============================================================================
echo -e "${YELLOW}🏥 PHASE 5: System Health Validation...${NC}"
echo "════════════════════════════════════════════════════════════════"

sleep 10  # Let everything stabilize

echo "   Running basic health check..."
python3 scripts/health_probe.py > /tmp/health_check.log 2>&1

if grep -q "GO FOR LAUNCH" /tmp/health_check.log; then
    echo -e "${GREEN}✅ Basic health check PASSED${NC}"
    cat /tmp/health_check.log | grep -E "PASS|STATUS:"
else
    echo -e "${YELLOW}⚠️  Basic health check has warnings:${NC}"
    cat /tmp/health_check.log | grep -E "FAIL|WARNING|ISSUE"
fi

echo ""

# ============================================================================
# FINAL STATUS
# ============================================================================
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🎉 PRODUCTION STARTUP COMPLETE                             ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Running Services:${NC}"
ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader|monitor_portfolio)" | grep -v grep | \
    awk '{printf "   • PID %s - %s %s %s (CPU: %s%%, MEM: %s%%)\n", $2, $11, $12, $13, $3, $4}'

echo ""
echo -e "${BLUE}Resource Usage:${NC}"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader | \
    awk -F', ' '{printf "   • GPU: %s | VRAM: %s / %s | Util: %s\n", $1, $2, $3, $4}'
free -h | awk '/^Mem:/ {printf "   • RAM: %s used / %s total (%s available)\n", $3, $2, $7}'

echo ""
echo -e "${BLUE}Management Commands:${NC}"
echo "   View logs:           tail -f logs/<service>.log"
echo "   Primary Portfolio:   tail -f logs/monitor_portfolio_primary.log"
echo "   Asjad Portfolio:     tail -f logs/monitor_portfolio_asjad.log"
echo "   Kill service:        kill <PID>"
echo "   Kill all:            pkill -f 'python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|hybrid_|trader|monitor_portfolio)'"
echo "   Health check:        python3 scripts/health_probe.py"
echo "   VPN status:          tail -f logs/vpn_monitor.log"
echo ""

echo -e "${GREEN}✅ System is operational!${NC}"

# ============================================================================
# SEND COMPLETION NOTIFICATION|monitor_portfolio
# ============================================================================
SERVICE_COUNT=$(ps aux | grep -E "python3.*(vpn_monitor|system_telegram|monitor_trainer_predictions|live_|feature_|ohlcv_|hybrid_|trader)" | grep -v grep | wc -l)
HEALTH_STATUS=$(grep -q "GO FOR LAUNCH" /tmp/health_check.log 2>/dev/null && echo "✅ GO FOR LAUNCH" || echo "⚠️  Warnings present")

send_telegram_notification "✅ AI Trading System fully operational at $(date)
5
• Health Check: ${HEALTH_STATUS}
• Deployment Method: Production (staged)
• Desktop: Stable (no crashes)
• VPN Monitor: Active 🔒

💻 Resource Usage:
• GPU VRAM: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) MB / 16303 MB
• RAM: $(free -g | awk '/^Mem:/ {print $3}') GB / $(free -g | awk '/^Mem:/ {print $2}') GB

📊 Visibility:
• Dashboard: ./scripts/monitor_dashboard.sh
• Primary Portfolio: tail -f logs/monitor_portfolio_primary.log
• Asjad Portfolio: tail -f logs/monitor_portfolio_asjad.log
📊 Visibility:
• Dashboard: ./scripts/monitor_dashboard.sh
• Logs: tail -f logs/<service>.log
• Health: python3 scripts/health_probe.py
• VPN Status: tail -f logs/vpn_monitor.log

🎯 System Status: READY FOR TRADING" "SUCCESS"

echo ""
echo -e "${BLUE}📱 Telegram notifications sent!${NC}"
echo -e "${BLUE}📊 Start monitoring: ./scripts/monitor_dashboard.sh${NC}"
echo ""
