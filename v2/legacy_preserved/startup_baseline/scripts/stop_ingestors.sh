#!/bin/bash
# AI BOT - Stop All Ingestors
# Stops all data ingestion services and cleans up locks

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

# Stop ingestor by name
stop_ingestor() {
    local name=$1
    local script_pattern=$2
    local pid_file="$PROJECT_ROOT/logs/${name}.pid"
    
    log "Stopping $name ingestor..."
    
    local stopped=0
    
    # Stop by PID file if exists
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            log "Sending SIGTERM to $name (PID: $pid)"
            kill -TERM "$pid" 2>/dev/null || true
            
            # Wait for graceful shutdown
            for i in {1..10}; do
                if ! kill -0 "$pid" 2>/dev/null; then
                    success "$name stopped gracefully"
                    stopped=1
                    break
                fi
                sleep 1
            done
            
            # Force kill if still running
            if [ $stopped -eq 0 ] && kill -0 "$pid" 2>/dev/null; then
                warning "Force killing $name (PID: $pid)"
                kill -KILL "$pid" 2>/dev/null || true
                sleep 1
                if ! kill -0 "$pid" 2>/dev/null; then
                    success "$name force stopped"
                    stopped=1
                fi
            fi
        fi
        rm -f "$pid_file"
    fi
    
    # Stop by process pattern if PID method didn't work
    if [ $stopped -eq 0 ]; then
        local pids=$(pgrep -f "$script_pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            log "Stopping $name by process pattern..."
            echo "$pids" | while read pid; do
                if [ -n "$pid" ]; then
                    kill -TERM "$pid" 2>/dev/null || true
                fi
            done
            
            sleep 3
            
            # Force kill remaining processes
            pids=$(pgrep -f "$script_pattern" 2>/dev/null || true)
            if [ -n "$pids" ]; then
                warning "Force killing remaining $name processes"
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
        success "$name ingestor stopped"
    else
        warning "$name ingestor was not running"
    fi
}

# Clean Redis locks and data
clean_redis_locks() {
    log "Cleaning Redis locks and interrupt signals..."
    
    $PYTHON_BIN -c "
import redis
import sys
from pathlib import Path

# Add project root to path
project_root = Path('$PROJECT_ROOT')
sys.path.insert(0, str(project_root))

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Clean interrupt locks
    interrupt_keys = r.keys('interrupt:*')
    if interrupt_keys:
        r.delete(*interrupt_keys)
        print(f'✅ Cleaned {len(interrupt_keys)} interrupt locks')
    
    # Clean heartbeat locks
    heartbeat_keys = r.keys('heartbeat:*')
    if heartbeat_keys:
        r.delete(*heartbeat_keys)
        print(f'✅ Cleaned {len(heartbeat_keys)} heartbeat entries')
    
    # Clean process locks
    lock_keys = r.keys('*:lock') + r.keys('lock:*')
    if lock_keys:
        r.delete(*lock_keys)
        print(f'✅ Cleaned {len(lock_keys)} process locks')
    
    # Clean running status
    status_keys = r.keys('*:running') + r.keys('running:*')
    if status_keys:
        r.delete(*status_keys)
        print(f'✅ Cleaned {len(status_keys)} running status entries')
    
    print('✅ Redis cleanup completed')
    
except redis.ConnectionError:
    print('⚠️  Redis not available - skipping Redis cleanup')
except Exception as e:
    print(f'❌ Redis cleanup failed: {e}')
" || warning "Redis cleanup had issues"
}

# Clean file locks
clean_file_locks() {
    log "Cleaning file-based locks..."
    
    # Remove lock files
    find "$PROJECT_ROOT" -name "*.lock" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "*.pid" -path "*/logs/*" -type f -delete 2>/dev/null || true
    
    # Clean temporary files
    find "$PROJECT_ROOT" -name "*.tmp" -type f -delete 2>/dev/null || true
    
    success "File locks cleaned"
}

# Clean log rotation locks
clean_log_locks() {
    log "Cleaning log rotation locks..."
    
    # Remove log locks
    find "$PROJECT_ROOT/logs" -name "*.lock" -type f -delete 2>/dev/null || true
    
    # Truncate large log files (keep last 1000 lines)
    if [ -d "$PROJECT_ROOT/logs" ]; then
        for log_file in "$PROJECT_ROOT/logs"/*.log; do
            if [ -f "$log_file" ] && [ $(wc -l < "$log_file") -gt 10000 ]; then
                tail -n 1000 "$log_file" > "$log_file.tmp"
                mv "$log_file.tmp" "$log_file"
                log "Truncated large log file: $(basename "$log_file")"
            fi
        done
    fi
}

# Main execution
main() {
    log "🛑 Stopping AI BOT Data Ingestors"
    echo "=================================="
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Define ingestors to stop
    declare -A INGESTORS=(
        ["binance"]="live_binance.py"
        ["tokenmetrics"]="live_tokenmetrics.py"
        ["coinank"]="live_coinank.py"
        ["kucoin"]="live_kucoin.py"
        ["alphavantage_news"]="live_alphavantage_news.py"
    )
    
    # Stop each ingestor
    local stopped=0
    for name in "${!INGESTORS[@]}"; do
        stop_ingestor "$name" "${INGESTORS[$name]}"
        ((stopped++))
    done
    
    # Clean up locks and resources
    log "Cleaning up locks and resources..."
    clean_redis_locks
    clean_file_locks
    clean_log_locks
    
    # Verify no ingestors are still running
    log "Verifying all ingestors are stopped..."
    local remaining=$(pgrep -f "live_.*\.py" | wc -l)
    if [ "$remaining" -eq 0 ]; then
        success "All ingestors stopped successfully"
    else
        warning "$remaining ingestor processes may still be running"
        pgrep -f "live_.*\.py" | while read pid; do
            ps -p $pid -o pid,cmd --no-headers
        done
    fi
    
    # Summary
    echo "=================================="
    success "Stopped $stopped ingestors"
    success "Cleaned Redis locks and file locks"
    log "All data ingestion services have been stopped"
    
    # Check system status
    log "System status:"
    log "  Redis: $(redis-cli ping 2>/dev/null || echo 'Not responding')"
    log "  Ingestor processes: $(pgrep -f 'live_.*\.py' | wc -l) running"
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"
