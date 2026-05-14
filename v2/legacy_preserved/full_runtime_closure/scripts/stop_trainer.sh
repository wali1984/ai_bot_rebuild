#!/bin/bash
# AI BOT - Stop Hybrid PPO+MASA Trainer
# Force kills the training process and cleans up GPU resources

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
PURPLE='\033[0;35m'
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

gpu_info() {
    echo -e "${PURPLE}[$(date '+%Y-%m-%d %H:%M:%S')] GPU: $1${NC}"
}

# Get GPU status before stopping
show_gpu_status() {
    log "Current GPU status:"
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits | \
        while IFS=',' read -r util mem_used mem_total temp; do
            local vram_gb=$((mem_used / 1024))
            gpu_info "GPU: ${util}% util, VRAM: ${vram_gb}GB/${mem_total}MB total, Temp: ${temp}°C"
        done
    else
        warning "nvidia-smi not available"
    fi
}

# Stop trainer process
stop_trainer() {
    local pid_file="$PROJECT_ROOT/logs/trainer.pid"
    
    log "Stopping Hybrid PPO+MASA Trainer..."
    
    local stopped=0
    
    # Stop by PID file if exists
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            log "Sending SIGTERM to trainer (PID: $pid)"
            
            # Send graceful shutdown signal
            kill -TERM "$pid" 2>/dev/null || true
            
            # Wait for graceful shutdown (training checkpoint save)
            log "Waiting for training checkpoint save..."
            for i in {1..30}; do  # Wait up to 30 seconds for checkpoint
                if ! kill -0 "$pid" 2>/dev/null; then
                    success "Trainer stopped gracefully with checkpoint save"
                    stopped=1
                    break
                fi
                if [ $i -eq 15 ]; then
                    log "Still waiting for checkpoint save... (15s)"
                fi
                sleep 1
            done
            
            # Force kill if still running after checkpoint timeout
            if [ $stopped -eq 0 ] && kill -0 "$pid" 2>/dev/null; then
                warning "Checkpoint save timeout - force killing trainer (PID: $pid)"
                kill -KILL "$pid" 2>/dev/null || true
                sleep 2
                if ! kill -0 "$pid" 2>/dev/null; then
                    warning "Trainer force stopped (checkpoint may be incomplete)"
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
        local pids=$(pgrep -f "hybrid_trainer.py" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            log "Force killing trainer by process pattern..."
            echo "$pids" | while read pid; do
                if [ -n "$pid" ]; then
                    kill -KILL "$pid" 2>/dev/null || true
                fi
            done
            sleep 2
            stopped=1
        fi
    fi
    
    if [ $stopped -eq 1 ]; then
        success "DQN Trainer stopped"
    else
        warning "DQN Trainer was not running"
    fi
}

# Clean GPU memory
clean_gpu_memory() {
    log "Cleaning GPU memory..."
    
    $PYTHON_BIN -c "
try:
    import torch
    if torch.cuda.is_available():
        # Clear GPU cache
        torch.cuda.empty_cache()
        
        # Get memory stats
        for i in range(torch.cuda.device_count()):
            allocated = torch.cuda.memory_allocated(i) / 1024**3  # GB
            cached = torch.cuda.memory_reserved(i) / 1024**3      # GB
            print(f'GPU {i}: {allocated:.2f}GB allocated, {cached:.2f}GB cached')
        
        # Additional cleanup
        torch.cuda.synchronize()
        print('✅ GPU memory cleaned')
    else:
        print('⚠️  CUDA not available')
except ImportError:
    print('⚠️  PyTorch not available')
except Exception as e:
    print(f'❌ GPU cleanup failed: {e}')
"
}

# Clean training locks and resources
clean_training_locks() {
    log "Cleaning training locks and resources..."
    
    $PYTHON_BIN -c "
import redis
import sys
from pathlib import Path

# Add project root to path
project_root = Path('$PROJECT_ROOT')
sys.path.insert(0, str(project_root))

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Clean training locks
    training_keys = r.keys('training:*:lock') + r.keys('dqn:*:lock')
    if training_keys:
        r.delete(*training_keys)
        print(f'✅ Cleaned {len(training_keys)} training locks')
    
    # Clean training status
    status_keys = r.keys('training:*:status') + r.keys('dqn:*:status')
    if status_keys:
        r.delete(*status_keys)
        print(f'✅ Cleaned {len(status_keys)} training status entries')
    
    # Clean training metrics (keep last 100 entries)
    metrics_keys = r.keys('training:metrics:*')
    if len(metrics_keys) > 100:
        # Sort by timestamp and remove oldest
        old_keys = sorted(metrics_keys)[:-100]
        if old_keys:
            r.delete(*old_keys)
            print(f'✅ Cleaned {len(old_keys)} old training metrics')
    
    # Clean interrupt signals for trainer
    interrupt_keys = r.keys('interrupt:trainer*') + r.keys('interrupt:dqn*')
    if interrupt_keys:
        r.delete(*interrupt_keys)
        print(f'✅ Cleaned {len(interrupt_keys)} trainer interrupt signals')
    
    print('✅ Training Redis cleanup completed')
    
except redis.ConnectionError:
    print('⚠️  Redis not available - skipping Redis cleanup')
except Exception as e:
    print(f'❌ Training Redis cleanup failed: {e}')
" || warning "Training Redis cleanup had issues"
}

# Clean file locks and temporary files
clean_file_locks() {
    log "Cleaning training file locks..."
    
    # Remove training lock files
    find "$PROJECT_ROOT" -name "trainer*.lock" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "dqn*.lock" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "training*.lock" -type f -delete 2>/dev/null || true
    
    # Clean temporary checkpoint files
    find "$PROJECT_ROOT/checkpoints" -name "*.tmp" -type f -delete 2>/dev/null || true
    find "$PROJECT_ROOT/checkpoints" -name "*temp*" -type f -delete 2>/dev/null || true
    
    # Clean temporary model files older than 1 day
    find "$PROJECT_ROOT/checkpoints" -name "dqn_model_temp_*" -type f -mtime +1 -delete 2>/dev/null || true
    
    success "Training file locks cleaned"
}

# Backup latest checkpoint
backup_checkpoint() {
    local checkpoint_dir="$PROJECT_ROOT/checkpoints"
    local latest_model="$checkpoint_dir/dqn_model_latest.pth"
    
    if [ -f "$latest_model" ]; then
        local backup_name="dqn_model_backup_$(date +%Y%m%d_%H%M%S).pth"
        cp "$latest_model" "$checkpoint_dir/$backup_name"
        log "Latest model backed up as: $backup_name"
        
        # Keep only last 5 backups
        cd "$checkpoint_dir"
        ls -t dqn_model_backup_*.pth 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
    fi
}

# Main execution
main() {
    log "🛑 Stopping AI BOT Hybrid PPO+MASA Trainer"
    echo "=================================="
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Show current GPU status
    show_gpu_status
    
    # Backup current model before stopping
    backup_checkpoint
    
    # Stop trainer process
    stop_trainer
    
    # Clean up resources
    log "Cleaning up training resources..."
    clean_gpu_memory
    clean_training_locks
    clean_file_locks
    
    # Verify trainer is stopped
    log "Verifying trainer is stopped..."
    local remaining=$(pgrep -f "hybrid_trainer.py" | wc -l)
    if [ "$remaining" -eq 0 ]; then
        success "DQN Trainer stopped successfully"
    else
        warning "$remaining trainer processes may still be running"
        pgrep -f "dqn_trainer.py" | while read pid; do
            ps -p $pid -o pid,cmd --no-headers
        done
    fi
    
    # Show final GPU status
    log "Final GPU status:"
    show_gpu_status
    
    # Summary
    echo "=================================="
    success "DQN Trainer stopped"
    success "GPU memory cleaned"
    success "Training locks and resources cleaned"
    log "Training checkpoints preserved in: $PROJECT_ROOT/checkpoints/"
    
    # Check for any remaining PyTorch processes
    local torch_procs=$(pgrep -f "python.*torch" 2>/dev/null | wc -l || echo "0")
    if [ "$torch_procs" -gt 0 ]; then
        warning "$torch_procs PyTorch processes still running"
    else
        success "No remaining PyTorch processes"
    fi
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"
