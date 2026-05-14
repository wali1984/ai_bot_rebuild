#!/bin/bash
# AI BOT - Start Hybrid PPO+MASA Trainer with RTX 5080 Optimization
# Hybrid mode: Continuous training + real-time predictions with MASA ensemble

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

# Check RTX 5080 availability
check_rtx5080() {
    log "Checking RTX 5080 availability..."
    
    # Check if nvidia-smi is available
    if ! command -v nvidia-smi &> /dev/null; then
        error "nvidia-smi not found. GPU drivers may not be installed."
        exit 1
    fi
    
    # Check GPU info
    local gpu_info=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits)
    if echo "$gpu_info" | grep -q "RTX 5080"; then
        local memory=$(echo "$gpu_info" | grep "RTX 5080" | cut -d',' -f2)
        success "RTX 5080 detected with ${memory}MB VRAM"
        gpu_info "Target: 80% GPU utilization, 12GB VRAM usage"
    else
        warning "RTX 5080 not detected. Available GPUs:"
        nvidia-smi --query-gpu=name --format=csv,noheader
    fi
}

# Check PyTorch CUDA support
check_pytorch_cuda() {
    log "Verifying PyTorch CUDA support..."
    
    $PYTHON_BIN -c "
import torch
import sys

if not torch.cuda.is_available():
    print('ERROR: CUDA not available in PyTorch')
    sys.exit(1)

device_count = torch.cuda.device_count()
print(f'✅ CUDA available with {device_count} device(s)')

for i in range(device_count):
    name = torch.cuda.get_device_name(i)
    capability = torch.cuda.get_device_capability(i)
    print(f'  Device {i}: {name} (SM_{capability[0]}{capability[1]})')
    
    if 'RTX 5080' in name and capability == (12, 0):
        print('  🔥 RTX 5080 with SM_120 Blackwell architecture detected!')
    elif capability[0] >= 12:
        print('  ✅ Blackwell architecture supported!')

print(f'✅ PyTorch version: {torch.__version__}')
print(f'✅ CUDA version: {torch.version.cuda}')
" || {
        error "PyTorch CUDA verification failed"
        exit 1
    }
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

# Set RTX 5080 optimization environment variables
set_gpu_optimization() {
    log "Setting RTX 5080 optimization parameters..."
    
    # CUDA optimization for RTX 5080
    export CUDA_VISIBLE_DEVICES=0
    export CUDA_DEVICE_ORDER=PCI_BUS_ID
    
    # Memory optimization (reduce fragmentation / allocator OOM in long-running training)
    # Keep conservative split size; allow segments to grow; encourage GC of cached blocks.
    export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True,max_split_size_mb:128,garbage_collection_threshold:0.8"
    export CUDA_MODULE_LOADING=LAZY
    
    # Enable RTX 5080 optimizations
    export TORCH_CUDNN_V8_API_ENABLED=1
    export TORCH_CUDNN_V8_API_DEBUG=0
    
    # RTX 5080 specific optimizations
    export CUDA_LAUNCH_BLOCKING=0  # For performance
    # Device-side assertions (DSA) are a debug feature and can hurt performance; keep OFF by default.
    export TORCH_USE_CUDA_DSA=${TORCH_USE_CUDA_DSA:-0}
    
    # Training optimization for 80% GPU utilization
    export OMP_NUM_THREADS=8       # Optimize CPU threads for RTX 5080
    export CUDA_CACHE_DISABLE=0    # Enable CUDA cache
    
    # AI BOT specific training parameters
    export AI_BOT_TRAINING_MODE="ULTRA_PRODUCTION"
    export AI_BOT_GPU_TARGET_UTIL="80"
    export AI_BOT_VRAM_TARGET_GB="12"
    export AI_BOT_BATCH_SIZE_MULTIPLIER="2.0"  # Increase batch size for RTX 5080
    export AI_BOT_LEARNING_RATE_SCALE="1.5"    # Scale learning rate for larger batches
    
    success "RTX 5080 optimization parameters set"
    gpu_info "Target: 80% GPU utilization, 12GB VRAM usage"
}

# Start the trainer
start_trainer() {
    local log_file="$PROJECT_ROOT/logs/trainer.log"
    local pid_file="$PROJECT_ROOT/logs/trainer.pid"
    
    # Create logs directory
    mkdir -p "$PROJECT_ROOT/logs"
    
    log "Starting Hybrid PPO+MASA Trainer with RTX 5080 optimization..."
    
    # Check if already running
    if [ -f "$pid_file" ] && pgrep -F "$pid_file" > /dev/null 2>&1; then
        warning "Trainer is already running (PID: $(cat $pid_file))"
        return 0
    fi
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Start hybrid trainer in background with correct CLI arguments
    # ✅ CRITICAL: Use --mode hybrid --training-mode live for backward compatibility
    nohup $PYTHON_BIN -u rl/hybrid_trainer.py --mode hybrid --training-mode live \
        > "$log_file" 2>&1 &
    
    local pid=$!
    
    # Save PID
    echo "$pid" > "$pid_file"
    
    # Wait and verify startup
    sleep 5
    if kill -0 $pid 2>/dev/null; then
        success "Hybrid PPO+MASA Trainer started with RTX 5080 optimization (PID: $pid)"
        gpu_info "Ultra/Production mode active"
        
        # Show initial GPU usage
        log "Initial GPU status:"
        nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | \
        while IFS=',' read -r util mem_used mem_total; do
            gpu_info "GPU Utilization: ${util}%, VRAM: ${mem_used}MB/${mem_total}MB"
        done
        
    else
        error "Failed to start trainer"
        tail -n 30 "$log_file"
        rm -f "$pid_file"
        return 1
    fi
}

# Monitor GPU usage
monitor_gpu() {
    log "Monitoring GPU usage for 30 seconds..."
    
    for i in {1..6}; do
        sleep 5
        nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits | \
        while IFS=',' read -r util mem_used mem_total temp; do
            local vram_gb=$((mem_used / 1024))
            gpu_info "GPU: ${util}% util, VRAM: ${vram_gb}GB/${mem_total}MB total, Temp: ${temp}°C"
            
            # Check if we're hitting our targets
            if [ "$util" -gt 70 ] && [ "$vram_gb" -gt 8 ]; then
                success "RTX 5080 optimization targets being met!"
            fi
        done
    done
}

# Main execution
main() {
    log "🔥 Starting AI BOT Hybrid PPO+MASA Trainer - RTX 5080 Ultra Mode"
    echo "=================================================="
    
    # System checks
    check_rtx5080
    check_pytorch_cuda
    check_redis
    
    # Set optimization parameters
    set_gpu_optimization
    
    # Start trainer
    start_trainer
    
    # Monitor initial performance
    monitor_gpu
    
    # Final status
    echo "=================================================="
    success "Hybrid PPO+MASA Trainer running in RTX 5080 Ultra/Production mode"
    log "Log file: $PROJECT_ROOT/logs/trainer.log"
    log "Use 'scripts/stop_trainer.sh' to stop the trainer"
    log "Use 'nvidia-smi' to monitor GPU usage"
    
    # Show running process
    local pid_file="$PROJECT_ROOT/logs/trainer.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        log "Trainer PID: $pid"
        ps -p $pid -o pid,cmd --no-headers | head -c 100
        echo "..."
    fi
}

# Handle script interruption
trap 'error "Script interrupted"; exit 1' INT TERM

# Run main function
main "$@"
