#!/bin/bash
# AI Trading Bot - Real-time Monitoring Dashboard
# Shows live status of all services in a clean terminal UI

BASE_DIR="/home/wali/Desktop/AI BOT"
cd "$BASE_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

while true; do
    clear
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   🤖 AI TRADING BOT - LIVE MONITORING DASHBOARD              ║${NC}"
    echo -e "${BLUE}║   $(date '+%Y-%m-%d %H:%M:%S')                                        ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # ============================================================================
    # PROCESS STATUS
    # ============================================================================
    echo -e "${CYAN}📊 SERVICE STATUS (11 services)${NC}"
    echo "════════════════════════════════════════════════════════════════"
    
    check_service() {
        local name=$1
        local pattern=$2
        
        if pgrep -f "$pattern" > /dev/null; then
            local pid=$(pgrep -f "$pattern" | head -1)
            local cpu=$(ps -p $pid -o %cpu= 2>/dev/null | tr -d ' ')
            local mem=$(ps -p $pid -o %mem= 2>/dev/null | tr -d ' ')
            echo -e "${GREEN}✅${NC} $name (PID $pid) - CPU: ${cpu}% MEM: ${mem}%"
        else
            echo -e "${RED}❌${NC} $name - NOT RUNNING"
        fi
    }
    
    echo -e "${YELLOW}Data Ingestors:${NC}"
    check_service "  Binance        " "live_binance.py"
    check_service "  KuCoin         " "live_kucoin.py"
    check_service "  Coinank        " "live_coinank.py"
    check_service "  TokenMetrics   " "live_tokenmetrics.py"
    check_service "  CCXT           " "live_ccxt.py"
    check_service "  Liquidations   " "live_binance_liquidations.py"
    
    echo ""
    echo -e "${YELLOW}Feature Processing:${NC}"
    check_service "  OHLCV Resampler" "ohlcv_resampler_hotfix.py"
    check_service "  Feature Pipeline" "feature_pipeline.py"
    
    echo ""
    echo -e "${YELLOW}Trading System:${NC}"
    check_service "  Hybrid Trainer " "hybrid_trainer.py"
    check_service "  Trader (Primary)" "trading/trader.py"
    check_service "  Trader (Asjad)  " "trading/trader-asjad.py"
    
    # ============================================================================
    # REDIS DATA STATUS
    # ============================================================================
    echo ""
    echo -e "${CYAN}📡 LATEST DATA (from Redis)${NC}"
    echo "════════════════════════════════════════════════════════════════"
    
    # Latest prices
    echo -e "${YELLOW}Latest Prices:${NC}"
    for symbol in BTCUSDT ETHUSDT SOLUSDT LTCUSDT; do
        price=$(redis-cli --raw GET "market:${symbol}:1m" 2>/dev/null | jq -r '.close // "N/A"' 2>/dev/null)
        if [ "$price" != "N/A" ] && [ ! -z "$price" ]; then
            echo "  $symbol: \$$price"
        else
            echo -e "  $symbol: ${RED}No data${NC}"
        fi
    done
    
    # Signal stream
    echo ""
    echo -e "${YELLOW}Signal Stream:${NC}"
    signal_count=$(redis-cli XLEN wma:trainer:predictions 2>/dev/null || echo "0")
    echo "  Stream length: $signal_count messages"
    
    if [ "$signal_count" -gt "0" ]; then
        latest_signal=$(redis-cli XREVRANGE wma:trainer:predictions + - COUNT 1 2>/dev/null | grep -o '"symbol":"[^"]*"' | head -1 | cut -d'"' -f4)
        latest_action=$(redis-cli XREVRANGE wma:trainer:predictions + - COUNT 1 2>/dev/null | grep -o '"action_name":"[^"]*"' | head -1 | cut -d'"' -f4)
        latest_conf=$(redis-cli XREVRANGE wma:trainer:predictions + - COUNT 1 2>/dev/null | grep -o '"model_confidence":[0-9.]*' | head -1 | cut -d':' -f2)
        
        if [ ! -z "$latest_signal" ]; then
            echo "  Latest: $latest_signal $latest_action (${latest_conf})"
        fi
    fi
    
    # ============================================================================
    # RESOURCE USAGE
    # ============================================================================
    echo ""
    echo -e "${CYAN}💻 RESOURCE USAGE${NC}"
    echo "════════════════════════════════════════════════════════════════"
    
    # GPU
    gpu_info=$(nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null)
    if [ ! -z "$gpu_info" ]; then
        vram_used=$(echo $gpu_info | cut -d',' -f1 | tr -d ' ')
        vram_total=$(echo $gpu_info | cut -d',' -f2 | tr -d ' ')
        gpu_util=$(echo $gpu_info | cut -d',' -f3 | tr -d ' ')
        echo -e "${YELLOW}GPU:${NC} VRAM: ${vram_used}MB/${vram_total}MB | Util: ${gpu_util}%"
    fi
    
    # RAM
    mem_info=$(free -g | grep Mem:)
    mem_total=$(echo $mem_info | awk '{print $2}')
    mem_used=$(echo $mem_info | awk '{print $3}')
    mem_avail=$(echo $mem_info | awk '{print $7}')
    echo -e "${YELLOW}RAM:${NC} ${mem_used}GB/${mem_total}GB used (${mem_avail}GB available)"
    
    # ============================================================================
    # RECENT LOG ENTRIES
    # ============================================================================
    echo ""
    echo -e "${CYAN}📝 RECENT LOG ACTIVITY (last 30 seconds)${NC}"
    echo "════════════════════════════════════════════════════════════════"
    
    # Get recent errors/warnings from all logs
    recent_logs=$(find logs -name "*.log" -type f -mmin -1 2>/dev/null | head -3)
    if [ ! -z "$recent_logs" ]; then
        for log in $recent_logs; do
            service_name=$(basename $log .log)
            last_line=$(tail -1 "$log" 2>/dev/null | cut -c1-60)
            if [ ! -z "$last_line" ]; then
                echo "  ${service_name}: ${last_line}..."
            fi
        done
    else
        echo "  (No recent activity)"
    fi
    
    # ============================================================================
    # FOOTER
    # ============================================================================
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo -e "${BLUE}Press Ctrl+C to exit | Refreshes every 5 seconds${NC}"
    echo -e "${BLUE}Detailed logs: tail -f logs/<service>.log${NC}"
    echo "════════════════════════════════════════════════════════════════"
    
    sleep 5
done
