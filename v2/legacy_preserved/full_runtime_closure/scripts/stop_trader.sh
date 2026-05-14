#!/bin/bash
# AI BOT - Stop Trading Engine
# Stops trading operations and cleans up positions/locks safely

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

# Check and close open positions safely
close_open_positions() {
    log "Checking for open trading positions..."
    
    $PYTHON_BIN -c "
import redis
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path('$PROJECT_ROOT')
sys.path.insert(0, str(project_root))

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Get open positions
    positions = r.hgetall('trading:positions') or {}
    
    if positions:
        print(f'⚠️  Found {len(positions)} open positions:')
        
        total_value = 0
        for symbol, position in positions.items():
            try:
                pos_data = json.loads(position) if isinstance(position, str) else position
                side = pos_data.get('side', 'UNKNOWN')
                size = float(pos_data.get('size', 0))
                entry_price = float(pos_data.get('entry_price', 0))
                value = size * entry_price
                total_value += abs(value)
                
                print(f'  {symbol}: {side} \${size:.2f} @ \${entry_price:.4f} (Value: \${value:.2f})')
            except Exception as e:
                print(f'  {symbol}: Invalid position data - {e}')
        
        print(f'📊 Total position value: \${total_value:.2f}')
        print('')
        print('🚨 IMPORTANT: Open positions detected!')
        print('   These positions will remain open after stopping the trader.')
        print('   You may want to manually close them or restart the trader.')
        print('   Check your exchange accounts for position status.')
        print('')
        
        # Mark positions as orphaned
        for symbol in positions.keys():
            r.hset('trading:orphaned_positions', symbol, positions[symbol])
        
        print('✅ Positions marked as orphaned for manual review')
        
    else:
        print('✅ No open positions found')
        
except redis.ConnectionError:
    print('⚠️  Redis not available - cannot check positions')
except Exception as e:
    print(f'❌ Position check failed: {e}')
"
    
    # Ask for confirmation if positions exist
    read -p "Do you want to continue stopping the trader? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "Trader stop cancelled by user"
        exit 0
    fi
}

# Stop trader process
stop_trader() {
    local pid_file="$PROJECT_ROOT/logs/trader.pid"
    
    log "Stopping Trading Engine..."
    
    local stopped=0
    
    # Stop by PID file if exists
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            log "Sending SIGTERM to trader (PID: $pid)"
            
            # Send graceful shutdown signal
            kill -TERM "$pid" 2>/dev/null || true
            
            # Wait for graceful shutdown (position cleanup)
            log "Waiting for position cleanup and order cancellation..."
            for i in {1..20}; do  # Wait up to 20 seconds
                if ! kill -0 "$pid" 2>/dev/null; then
                    success "Trader stopped gracefully"
                    stopped=1
                    break
                fi
                if [ $i -eq 10 ]; then
                    log "Still waiting for order cleanup... (10s)"
                fi
                sleep 1
            done
            
            # Force kill if still running after cleanup timeout
            if [ $stopped -eq 0 ] && kill -0 "$pid" 2>/dev/null; then
                warning "Cleanup timeout - force killing trader (PID: $pid)"
                kill -KILL "$pid" 2>/dev/null || true
                sleep 2
                if ! kill -0 "$pid" 2>/dev/null; then
                    warning "Trader force stopped (cleanup may be incomplete)"
                    stopped=1
                fi
            fi
        else
            warning "PID file exists but process not running"
        fi
        rm -f "$pid_file"
    fi
    
    # Stop by process pattern if PID method didn't work
    if [ $stopped -eq 0 ]; then
        local pids=$(pgrep -f "trading/trader.py\|trader.py" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            log "Stopping trader by process pattern..."
            echo "$pids" | while read pid; do
                if [ -n "$pid" ]; then
                    kill -TERM "$pid" 2>/dev/null || true
                fi
            done
            
            sleep 5
            
            # Force kill remaining processes
            pids=$(pgrep -f "trading/trader.py\|trader.py" 2>/dev/null || true)
            if [ -n "$pids" ]; then
                warning "Force killing remaining trader processes"
                echo "$pids" | while read pid; do
                    if [ -n "$pid" ]; then
                        kill -KILL "$pid" 2>/dev/null || true
                    fi
                done
            fi
            stopped=1
        fi
    fi
    
    if [ $stopped -eq 1 ]; then
        success "Trading Engine stopped"
    else
        warning "Trading Engine was not running"
    fi
}

# Clean trading locks and resources
clean_trading_locks() {
    log "Cleaning trading locks and resources..."
    
    $PYTHON_BIN -c "
import redis
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path('$PROJECT_ROOT')
sys.path.insert(0, str(project_root))

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Archive current session metrics before cleanup
    session_end = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save trading metrics to archive
    metrics = r.hgetall('trading:metrics') or {}
    if metrics:
        archive_key = f'trading:session:{session_end}'
        r.hmset(archive_key, metrics)
        r.expire(archive_key, 86400 * 30)  # Keep for 30 days
        print(f'✅ Archived trading session metrics: {archive_key}')
    
    # Clean trading locks
    trading_locks = r.keys('trading:*:lock') + r.keys('trade:*:lock')
    if trading_locks:
        r.delete(*trading_locks)
        print(f'✅ Cleaned {len(trading_locks)} trading locks')
    
    # Clean order locks
    order_locks = r.keys('order:*:lock') + r.keys('orders:*:lock')
    if order_locks:
        r.delete(*order_locks)
        print(f'✅ Cleaned {len(order_locks)} order locks')
    
    # Clean active order tracking (but preserve executed orders)
    active_orders = r.keys('trading:active_orders:*')
    if active_orders:
        r.delete(*active_orders)
        print(f'✅ Cleaned {len(active_orders)} active order entries')
    
    # Clean trading status
    status_keys = r.keys('trading:*:status') + r.keys('trader:*:status')
    if status_keys:
        r.delete(*status_keys)
        print(f'✅ Cleaned {len(status_keys)} trading status entries')
    
    # Clean interrupt signals for trader
    interrupt_keys = r.keys('interrupt:trader*') + r.keys('interrupt:trading*')
    if interrupt_keys:
        r.delete(*interrupt_keys)
        print(f'✅ Cleaned {len(interrupt_keys)} trader interrupt signals')
    
    # Keep recent trade history but clean old entries (older than 7 days)
    trade_history_keys = r.keys('trading:history:*')
    old_keys = []
    for key in trade_history_keys:
        try:
            # Extract timestamp from key
            timestamp = key.split(':')[-1]
            if len(timestamp) == 8:  # YYYYMMDD format
                key_date = datetime.strptime(timestamp, '%Y%m%d')
                days_old = (datetime.now() - key_date).days
                if days_old > 7:
                    old_keys.append(key)
        except:
            pass
    
    if old_keys:
        r.delete(*old_keys)
        print(f'✅ Cleaned {len(old_keys)} old trade history entries')
    
    print('✅ Trading Redis cleanup completed')
    
except redis.ConnectionError:
    print('⚠️  Redis not available - skipping Redis cleanup')
except Exception as e:
    print(f'❌ Trading Redis cleanup failed: {e}')
" || warning "Trading Redis cleanup had issues"
}

# Clean file locks and temporary files
clean_file_locks() {
    log "Cleaning trading file locks..."
    
    # Remove trading lock files
    find "$PROJECT_ROOT" -name "trader*.lock" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "trading*.lock" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "order*.lock" -type f -delete 2>/dev/null || true
    
    # Clean temporary trading files
    find "$PROJECT_ROOT" -name "trade_*.tmp" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "order_*.tmp" -type f -delete 2>/dev/null || true
    
    success "Trading file locks cleaned"
}

# Generate trading summary
generate_summary() {
    log "Generating trading session summary..."
    
    $PYTHON_BIN -c "
import redis
import json
from datetime import datetime

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Get final metrics
    metrics = r.hgetall('trading:metrics') or {}
    positions = r.hgetall('trading:positions') or {}
    orphaned = r.hgetall('trading:orphaned_positions') or {}
    
    print('📊 Trading Session Summary:')
    print('=' * 40)
    print(f'Session End: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}')
    print(f'Total Trades: {metrics.get(\"total_trades\", 0)}')
    print(f'Winning Trades: {metrics.get(\"winning_trades\", 0)}')
    print(f'Win Rate: {metrics.get(\"win_rate\", 0)}%')
    print(f'Total PnL: \${metrics.get(\"total_pnl\", 0)}')
    print(f'Portfolio Value: \${metrics.get(\"portfolio_value\", 0)}')
    print(f'Active Positions: {len(positions)}')
    print(f'Orphaned Positions: {len(orphaned)}')
    print('=' * 40)
    
    if orphaned:
        print('⚠️  Orphaned positions require manual review!')
        
except Exception as e:
    print(f'❌ Could not generate summary: {e}')
"
}

# Main execution
main() {
    log "🛑 Stopping AI BOT Trading Engine"
    echo "=================================="
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Check for open positions
    close_open_positions
    
    # Stop trader process
    stop_trader
    
    # Clean up resources
    log "Cleaning up trading resources..."
    clean_trading_locks
    clean_file_locks
    
    # Verify trader is stopped
    log "Verifying trader is stopped..."
    local remaining=$(pgrep -f "trading/trader.py\|trader.py" | wc -l)
    if [ "$remaining" -eq 0 ]; then
        success "Trading Engine stopped successfully"
    else
        warning "$remaining trader processes may still be running"
        pgrep -f "trading/trader.py\|trader.py" | while read pid; do
            ps -p $pid -o pid,cmd --no-headers
        done
    fi
    
    # Generate session summary
    generate_summary
    
    # Summary
    echo "=================================="
    success "Trading Engine stopped"
    success "Trading locks and resources cleaned"
    success "Session metrics archived"
    
    warning "IMPORTANT REMINDERS:"
    trade_info "Check exchange accounts for any remaining open positions"
    trade_info "Review orphaned positions in Redis: trading:orphaned_positions"
    trade_info "Trading logs available in: $PROJECT_ROOT/logs/trader.log"
    
    log "Trading session ended safely"
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"
