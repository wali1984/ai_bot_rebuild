#!/bin/bash
# Nightly Trainer Restart - Memory Leak Prevention
# Runs at 3:00 AM daily to reclaim memory from 125 PPO SubprocVecEnv workers.
#
# ROOT CAUSE (2026-03-31): Previous version only killed the main trainer process,
# leaving 125+ SubprocVecEnv child workers as orphans holding IPC resources
# (shared memory, file descriptors). The new trainer then crashed with:
#   "RuntimeError: received 0 items of ancdata"
# because stale children blocked IPC channel creation.
#
# FIX: Kill entire process tree, reap orphan SubprocVecEnv workers, clean /dev/shm,
# wait for all IPC resources to release, then start with retry + deep health check.
#
# Crontab: 0 3 * * * /home/wali/Desktop/AI\ BOT/scripts/nightly_restart_trainer.sh >> /home/wali/Desktop/AI\ BOT/logs/nightly_restart_trainer.log 2>&1

BASE_DIR="/home/wali/Desktop/AI BOT"
LOG="$BASE_DIR/logs/nightly_restart_trainer.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
MAX_RETRIES=3

echo ""
echo "========================================================"
echo "  NIGHTLY TRAINER RESTART — $TIMESTAMP"
echo "========================================================"

cd "$BASE_DIR" || { echo "ERROR: Cannot cd to $BASE_DIR"; exit 1; }
export PYTHONPATH="$BASE_DIR:${PYTHONPATH}"
source "$BASE_DIR/venv/bin/activate" 2>/dev/null || true

# ── Helper: send Telegram alert ────────────────────────────
send_alert() {
    python3 -c "
import sys; sys.path.insert(0, '$BASE_DIR')
try:
    from utils.telegram_alerts import send_telegram_message
    send_telegram_message('🔄 NIGHTLY RESTART\n\n$1', channel='monitoring')
except Exception:
    pass
" 2>/dev/null || true
}

# ── 1. Memory snapshot BEFORE ──────────────────────────────
MEM_BEFORE=$(free -h | awk '/^Mem:/ {print "Used: "$3" / Total: "$2" | Available: "$7}')
VRAM_BEFORE=$(nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "N/A")
echo "[1/9] Memory BEFORE: RAM=$MEM_BEFORE | VRAM used/free=${VRAM_BEFORE}MB"

# ── Helper: recursively collect all descendant PIDs of a given PID ──────────
# After killing the parent, children reparent to PID 1 and become invisible to
# pgrep -P. This function walks the process tree BEFORE killing anything so
# that every SubprocVecEnv worker is captured while the tree is still intact.
collect_descendants() {
    local root_pid="$1"
    local all_pids=""
    local queue="$root_pid"
    while [ -n "$queue" ]; do
        local current=""
        current=$(echo "$queue" | awk '{print $1}')
        queue=$(echo "$queue" | awk '{$1=""; print}' | xargs)
        local children
        children=$(ps -eo pid,ppid --no-headers 2>/dev/null | awk -v p="$current" '$2 == p {print $1}')
        if [ -n "$children" ]; then
            all_pids="$all_pids $children"
            queue="$queue $children"
        fi
    done
    echo "$all_pids" | xargs
}

# ── 2. Kill entire trainer process tree (main + ALL children) ──
echo "[2/9] Stopping trainer process tree..."

# 2a. Find the main trainer PID(s)
TRAINER_PIDS=$(pgrep -f "rl[./]hybrid_trainer|hybrid_trainer\.py" 2>/dev/null || true)
if [ -n "$TRAINER_PIDS" ]; then
    echo "       Main trainer PIDs: $TRAINER_PIDS"

    # 2b. Collect ALL descendants BEFORE killing parent (critical fix!)
    # SubprocVecEnv workers are plain "python3" processes — after parent dies
    # they reparent to PID 1 and can't be found by name. Walk the tree first.
    ALL_DESCENDANTS=""
    for TPID in $TRAINER_PIDS; do
        DESC=$(collect_descendants "$TPID")
        if [ -n "$DESC" ]; then
            ALL_DESCENDANTS="$ALL_DESCENDANTS $DESC"
        fi
    done
    ALL_DESCENDANTS=$(echo "$ALL_DESCENDANTS" | xargs -n1 2>/dev/null | sort -un | xargs)
    DESC_COUNT=$(echo "$ALL_DESCENDANTS" | wc -w)
    echo "       Found $DESC_COUNT descendant worker PIDs"

    # 2c. SIGTERM the entire set: parents + all descendants
    ALL_KILL="$TRAINER_PIDS $ALL_DESCENDANTS"
    echo "       Sending SIGTERM to $(echo "$ALL_KILL" | wc -w) processes..."
    kill $ALL_KILL 2>/dev/null || true
    sleep 5

    # 2d. SIGKILL anything still alive
    REMAINING=""
    for PID in $ALL_KILL; do
        if kill -0 "$PID" 2>/dev/null; then
            REMAINING="$REMAINING $PID"
        fi
    done
    if [ -n "$REMAINING" ]; then
        echo "       Force killing $(echo "$REMAINING" | wc -w) surviving processes..."
        kill -9 $REMAINING 2>/dev/null || true
        sleep 3
    fi
else
    echo "       No trainer process found (already dead)"
fi

# 2e. Final sweep: any python process with hybrid_trainer in its command
STALE=$(pgrep -f "hybrid_trainer" 2>/dev/null || true)
if [ -n "$STALE" ]; then
    echo "       Final sweep: killing stale PIDs: $STALE"
    kill -9 $STALE 2>/dev/null || true
    sleep 2
fi

echo "       Trainer process tree stopped ✅"

# 2f. Verify ALL trainer-related processes are truly dead
echo "       Verifying clean kill..."
VERIFY_ATTEMPTS=0
while [ $VERIFY_ATTEMPTS -lt 10 ]; do
    REMAINING_ANY=$(pgrep -f "hybrid_trainer" 2>/dev/null || true)
    if [ -z "$REMAINING_ANY" ]; then
        echo "       ✅ No trainer processes remaining"
        break
    fi
    VERIFY_ATTEMPTS=$((VERIFY_ATTEMPTS + 1))
    echo "       ⏳ Still ${REMAINING_ANY} alive — waiting ($VERIFY_ATTEMPTS/10)..."
    kill -9 $REMAINING_ANY 2>/dev/null || true
    sleep 2
done

# 2g. Wait for kernel to fully release IPC resources from dead workers
echo "       Waiting 10s for OS to release IPC file descriptors..."
sleep 10

# ── 3. Clean shared memory (IPC resources from SubprocVecEnv) ──
echo "[3/9] Cleaning shared memory and IPC resources..."
# Remove ALL Python/PyTorch/multiprocessing shared memory files
# The trainer uses 125 SubprocVecEnv workers that create IPC resources.
# Stale files cause "received 0 items of ancdata" on restart.
SHM_BEFORE=$(ls /dev/shm/ 2>/dev/null | wc -l)
SHM_CLEANED=0
for shm_file in /dev/shm/torch_* /dev/shm/psm_* /dev/shm/*SubprocVec* \
                /dev/shm/sem.* /dev/shm/mp-* /dev/shm/shm-* \
                /dev/shm/*python* /dev/shm/*stable_baselines*; do
    if [ -e "$shm_file" ]; then
        rm -f "$shm_file" 2>/dev/null && SHM_CLEANED=$((SHM_CLEANED + 1))
    fi
done
# Also clean any shared memory owned by the current user that's >10MB (likely SubprocVecEnv)
find /dev/shm -maxdepth 1 -user "$(whoami)" -size +10M -delete 2>/dev/null || true
SHM_AFTER=$(ls /dev/shm/ 2>/dev/null | wc -l)
echo "       Removed $SHM_CLEANED shared memory files ($SHM_BEFORE -> $SHM_AFTER remaining)"

# Wait for IPC resources to fully release
sleep 3

# ── 4. Clear Python cache ──────────────────────────────────
echo "[4/9] Clearing Python cache..."
find "$BASE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BASE_DIR" -name "*.pyc" -delete 2>/dev/null || true
echo "       Cache cleared"

# ── 5. Drop Linux RAM cache ───────────────────────────────
echo "[5/9] Dropping Linux RAM cache..."
sync
timeout 5 sudo -n sh -c "echo 3 > /proc/sys/vm/drop_caches" 2>/dev/null && \
    echo "       RAM cache dropped (sync + drop_caches=3)" || \
    echo "       WARNING: Could not drop RAM cache (needs passwordless sudo)"
MEM_POST_DROP=$(free -h | awk '/^Mem:/ {print "Used: "$3" | Available: "$7}')
echo "       RAM after drop: $MEM_POST_DROP"

# ── 6. Rotate log ─────────────────────────────────────────
echo "[6/9] Rotating hybrid_trainer.log..."
if [ -f "$BASE_DIR/logs/hybrid_trainer.log" ]; then
    mv "$BASE_DIR/logs/hybrid_trainer.log" \
       "$BASE_DIR/logs/hybrid_trainer.$(date +%Y%m%d_%H%M%S).log.bak"
    # Keep only last 5 backups
    ls -t "$BASE_DIR/logs/hybrid_trainer."*.log.bak 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
    echo "       Log rotated"
else
    echo "       No log to rotate"
fi

# ── 7. Start trainer with retry loop ──────────────────────
echo "[7/9] Starting trainer (max $MAX_RETRIES attempts)..."
TRAINER_PID=""
ATTEMPT=0
START_SUCCESS=false

while [ $ATTEMPT -lt $MAX_RETRIES ]; do
    ATTEMPT=$((ATTEMPT + 1))
    echo "       Attempt $ATTEMPT/$MAX_RETRIES..."

    nohup python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features \
        > "$BASE_DIR/logs/hybrid_trainer.log" 2>&1 &
    TRAINER_PID=$!
    echo "       Spawned PID $TRAINER_PID"

    # ── Polling health check ──────────────────────────────────
    # Trainer needs ~280s for first CYCLE_TIMING (30s env + 120s GPU batch + 85s rollout + 91s PPO learn).
    # Poll every 30s so there's regular output. Total budget: 420s (14 checks × 30s).
    POLL_INTERVAL=30
    MAX_POLLS=14           # 14 × 30s = 420s total
    POLL=0
    ATTEMPT_OK=false

    echo "       Polling every ${POLL_INTERVAL}s for up to $((MAX_POLLS * POLL_INTERVAL))s..."
    while [ $POLL -lt $MAX_POLLS ]; do
        sleep $POLL_INTERVAL
        POLL=$((POLL + 1))
        ELAPSED=$((POLL * POLL_INTERVAL))

        # 1. Is the process still alive?
        if ! kill -0 "$TRAINER_PID" 2>/dev/null; then
            echo "       ❌ [$ELAPSED/${MAX_POLLS}×${POLL_INTERVAL}s] Trainer PID $TRAINER_PID died"
            LAST_ERR=$(tail -20 "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null | grep -i "error\|failed\|exception\|ancdata\|RuntimeError" | tail -3)
            echo "       Last errors:"
            echo "$LAST_ERR" | while IFS= read -r line; do echo "         $line"; done
            break
        fi

        # 2. Check for crash signatures
        CRASH_SIGS=$(grep -c "ancdata\|Worker exiting after\|HARD EXIT\|CRITICAL.*crashed" "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null || true)
        CRASH_SIGS=${CRASH_SIGS:-0}
        if [ "$CRASH_SIGS" -gt 0 ]; then
            echo "       ❌ [$ELAPSED s] Crash signatures detected ($CRASH_SIGS matches)"
            grep "ancdata\|Worker exiting after\|HARD EXIT\|CRITICAL.*crashed" "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null | tail -3 | while IFS= read -r line; do echo "         $line"; done
            kill -9 "$TRAINER_PID" 2>/dev/null || true
            break
        fi

        # 3. Check for CYCLE_TIMING (success!)
        CYCLE_COUNT=$(grep -c "CYCLE_TIMING" "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null || true)
        CYCLE_COUNT=${CYCLE_COUNT:-0}
        if [ "$CYCLE_COUNT" -gt 0 ]; then
            echo "       ✅ [$ELAPSED s] Trainer healthy — $CYCLE_COUNT prediction cycle(s) completed"
            ATTEMPT_OK=true
            break
        fi

        # 4. Report intermediate progress so user sees activity
        PROGRESS=$(grep -cE "GPU_BATCH|ROLLOUT|PPO learn|SubprocVecEnv|prediction_worker|REWARD_INIT" "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null || true)
        PROGRESS=${PROGRESS:-0}
        LOG_LINES=$(wc -l < "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null || echo 0)
        echo "       ⏳ [$ELAPSED s] Alive, no CYCLE_TIMING yet | log=${LOG_LINES} lines | progress_markers=${PROGRESS}"
    done

    if $ATTEMPT_OK; then
        START_SUCCESS=true
        break
    fi

    # Attempt failed — clean up before retry
    echo "       Cleaning up failed attempt $ATTEMPT..."
    # Kill the spawned trainer AND all its SubprocVecEnv children
    if [ -n "$TRAINER_PID" ] && kill -0 "$TRAINER_PID" 2>/dev/null; then
        FAIL_DESC=$(collect_descendants "$TRAINER_PID")
        kill -9 $TRAINER_PID $FAIL_DESC 2>/dev/null || true
    fi
    pkill -9 -f "hybrid_trainer" 2>/dev/null || true
    sleep 5
    # Wait for IPC fd release from dead workers
    echo "       Waiting 10s for IPC resource release..."
    sleep 10
    [ -f "$BASE_DIR/logs/hybrid_trainer.log" ] && \
        mv "$BASE_DIR/logs/hybrid_trainer.log" \
           "$BASE_DIR/logs/hybrid_trainer.failed_attempt${ATTEMPT}.$(date +%Y%m%d_%H%M%S).log.bak"
done

if ! $START_SUCCESS; then
    echo "       ❌ FAILED: Trainer could not start after $MAX_RETRIES attempts"
    send_alert "❌ CRITICAL: Nightly trainer restart FAILED after $MAX_RETRIES attempts. Manual intervention required."
fi

# ── 8. Set OOM score ──────────────────────────────────────
echo "[8/9] Setting OOM score..."
if [ -n "$TRAINER_PID" ] && kill -0 "$TRAINER_PID" 2>/dev/null; then
    # Use timeout to avoid hanging on sudo password prompt in non-interactive mode
    timeout 5 sudo -n sh -c "echo 200 > /proc/$TRAINER_PID/oom_score_adj" 2>/dev/null && \
        echo "       OOM score +200 set on PID $TRAINER_PID" || \
        echo "       WARNING: Could not set OOM score (non-fatal, needs passwordless sudo)"
else
    echo "       Skipped (trainer not running)"
fi

# ── 9. Final status ───────────────────────────────────────
MEM_AFTER=$(free -h | awk '/^Mem:/ {print "Used: "$3" / Total: "$2" | Available: "$7}')
VRAM_AFTER=$(nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "N/A")

if [ -n "$TRAINER_PID" ] && kill -0 "$TRAINER_PID" 2>/dev/null; then
    TRAINER_STATUS="✅ UP"
    CYCLE_FINAL=$(grep -c "CYCLE_TIMING" "$BASE_DIR/logs/hybrid_trainer.log" 2>/dev/null || true)
    CYCLE_FINAL=${CYCLE_FINAL:-0}
else
    TRAINER_STATUS="❌ DOWN"
    CYCLE_FINAL=0
fi

echo "[9/9] Memory AFTER:  RAM=$MEM_AFTER | VRAM used/free=${VRAM_AFTER}MB"
echo ""
echo "  Trainer status    : $TRAINER_STATUS (PID ${TRAINER_PID:-N/A})"
echo "  Prediction cycles : $CYCLE_FINAL"
echo "  Attempts used     : $ATTEMPT / $MAX_RETRIES"
echo "  Completed at      : $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"

if $START_SUCCESS; then
    send_alert "✅ Trainer restarted successfully\nPID: $TRAINER_PID\nCycles: $CYCLE_FINAL\nAttempts: $ATTEMPT/$MAX_RETRIES\nRAM: $MEM_AFTER"
fi
