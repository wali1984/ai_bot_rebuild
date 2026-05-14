#!/bin/bash
# AI BOT - Start Trading Engine
# Launches the trading engine with risk management

set -e  # Exit on any error

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="/usr/bin/python3"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1${NC}"
}

warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

trade_info() {
    echo -e "${CYAN}[$(date '+%Y-%m-%d %H:%M:%S')] TRADE: $1${NC}"
}

# Check if Redis is running
check_redis() {
    log "Checking Redis connection..."
    if $PYTHON_BIN -c "import redis; r=redis.Redis(host='localhost', port=6379); r.ping()" 2>/dev/null; then
        success "Redis is running"
    else
        error "Redis is not running! Please start Redis first."
        exit 1
    fi
}

# Check if trained model exists
check_trained_model() {
    log "Checking for trained DQN model..."
    
    local checkpoint_dir="$PROJECT_ROOT/checkpoints"
    local model_file="$checkpoint_dir/dqn_model_latest.pth"
    
    if [ -f "$model_file" ]; then
        local model_age=$(stat -c %Y "$model_file")
        local current_time=$(date +%s)
        local age_hours=$(( (current_time - model_age) / 3600 ))
        
        success "Trained model found (${age_hours} hours old)"
        trade_info "Model: $model_file"
    else
        warning "No trained model found at $model_file"
        warning "Please train the model first using 'scripts/start_trainer.sh'"
        
        error "No trained model available. Live trading requires a trained model."
        exit 1
    fi
}

# Check API keys
check_api_keys() {
    log "Verifying trading API keys..."
    
    $PYTHON_BIN -c "
import os
from pathlib import Path
import sys

# Add project root to path
project_root = Path('$PROJECT_ROOT')
sys.path.insert(0, str(project_root))

try:
    from config import get_live_config
    config = get_live_config()
    
    # Check required API keys for trading
    required_keys = [
        ('BINANCE_API_KEY', config.BINANCE_API_KEY),
        ('BINANCE_SECRET_KEY', getattr(config, 'BINANCE_SECRET_KEY', config.BINANCE_API_SECRET)),
        ('KUCOIN_API_KEY', getattr(config, 'KUCOIN_API_KEY', '')),
        ('KUCOIN_SECRET_KEY', getattr(config, 'KUCOIN_SECRET_KEY', '')),
        ('KUCOIN_PASSPHRASE', getattr(config, 'KUCOIN_PASSPHRASE', ''))
    ]
    
    missing_keys = []
    for key_name, key_value in required_keys:
        if not key_value or key_value == 'your_key_here':
            missing_keys.append(key_name)
    
    if missing_keys:
        print(f'ERROR: Missing API keys: {missing_keys}')
        print('Please configure API keys in .env file')
        sys.exit(1)
    else:
        print('✅ All required API keys configured')
        
except Exception as e:
    print(f'ERROR: Configuration check failed: {e}')
    sys.exit(1)
" || {
        error "API key verification failed"
        exit 1
    }
}

# Set trading environment variables
set_trading_env() {
    log "Setting trading environment..."
    
    # Trading mode settings
    export AI_BOT_TRADING_MODE="PRODUCTION"
    export AI_BOT_RISK_LEVEL="CONSERVATIVE"
    export AI_BOT_MAX_POSITION_SIZE="1000"  # USD
    export AI_BOT_STOP_LOSS_PCT="2.0"       # 2% stop loss
    export AI_BOT_TAKE_PROFIT_PCT="5.0"     # 5% take profit
    
    # Portfolio management
    export AI_BOT_MAX_OPEN_POSITIONS="5"
    export AI_BOT_PORTFOLIO_RESERVE="0.2"   # 20% cash reserve
    
    # Performance monitoring
    export AI_BOT_LOG_TRADES="1"
    export AI_BOT_METRICS_ENABLED="1"
    
    success "Trading environment configured"
    trade_info "Risk Level: CONSERVATIVE, Max Position: $1000 USD"
}

# Start the trader
start_trader() {
    local log_file="$PROJECT_ROOT/logs/trader.log"
    local pid_file="$PROJECT_ROOT/logs/trader.pid"
    
    # Create logs directory
    mkdir -p "$PROJECT_ROOT/logs"
    
    log "Starting Trading Engine..."
    
    # Check if already running
    if [ -f "$pid_file" ] && pgrep -F "$pid_file" > /dev/null 2>&1; then
        warning "Trader is already running (PID: $(cat $pid_file))"
        return 0
    fi
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Start trader in background
    nohup $PYTHON_BIN -u trading/trader.py \
        --production \
        --risk-management \
        --portfolio-optimization \
        > "$log_file" 2>&1 &
    
    local pid=$!
    
    # Save PID
    echo "$pid" > "$pid_file"
    
    # Wait and verify startup
    sleep 3
    if kill -0 $pid 2>/dev/null; then
        success "Trading Engine started (PID: $pid)"
        trade_info "Production mode with risk management active"
        
        # Show initial status
        sleep 2
        log "Initial trading status:"
        tail -n 5 "$log_file" | while read line; do
            trade_info "$line"
        done
        
    else
        error "Failed to start trader"
        tail -n 20 "$log_file"
        rm -f "$pid_file"
        return 1
    fi
}

# Monitor trading status
monitor_trading() {
    log "Monitoring trading status..."
    
    # Check Redis for trading metrics
    $PYTHON_BIN -c "
import redis
import json
from datetime import datetime

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Get trading metrics
    metrics = r.hgetall('trading:metrics') or {}
    positions = r.hgetall('trading:positions') or {}
    
    print(f'📊 Trading Metrics:')
    print(f'  Active Positions: {len(positions)}')
    print(f'  Total Trades: {metrics.get(\"total_trades\", 0)}')
    print(f'  Win Rate: {metrics.get(\"win_rate\", 0)}%')
    print(f'  Portfolio Value: \${metrics.get(\"portfolio_value\", 0)}')
    
    if positions:
        print(f'🔄 Active Positions:')
        for symbol, position in positions.items():
            pos_data = json.loads(position) if isinstance(position, str) else position
            print(f'  {symbol}: {pos_data.get(\"side\", \"N/A\")} \${pos_data.get(\"size\", 0)}')
    
except Exception as e:
    print(f'❌ Could not retrieve trading metrics: {e}')
"
}

# Main execution
main() {
    log "💰 Starting AI BOT Trading Engine"
    echo "=================================="
    
    # System checks
    check_redis
    check_trained_model
    check_api_keys
    
    # Set trading environment
    set_trading_env
    
    # Start trader
    start_trader
    
    # Monitor initial status
    sleep 5
    monitor_trading
    
    # Final status
    echo "=================================="
    success "Trading Engine is running"
    log "Log file: $PROJECT_ROOT/logs/trader.log"
    log "Use 'scripts/stop_trader.sh' to stop the trader"
    log "Monitor trades with: tail -f $PROJECT_ROOT/logs/trader.log"
    
    # Show running process
    local pid_file="$PROJECT_ROOT/logs/trader.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        log "Trader PID: $pid"
        ps -p $pid -o pid,cmd --no-headers | head -c 100
        echo "..."
    fi
    
    # Safety reminder
    warning "TRADING WITH REAL MONEY - Monitor positions carefully!"
    trade_info "Use proper risk management and stop losses"
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"
