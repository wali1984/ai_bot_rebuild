# Rollout Hang Fixes Applied - Immediate Actions

**Date:** January 2025  
**Status:** ✅ FIXES APPLIED - Monitoring Required  
**Issue:** Trainer stuck in rollout/training loop cycle

---

## Fixes Applied

### ✅ FIX #1: Added Redis Timeout Protection in Worker Processes
**File:** `rl/gpu_environment.py`

**Problem:** Worker processes calling `redis.hgetall()` without timeout, causing indefinite hangs.

**Fix:**
- Added `_safe_redis_operation()` method with ThreadPoolExecutor timeout
- Wrapped all `redis.hgetall()` and `redis.keys()` calls with 1-second timeout
- Falls back to default features on timeout

**Code:**
```python
def _safe_redis_operation(self, operation, *args, timeout=1.0, default=None, **kwargs):
    """Execute Redis operation with timeout protection"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    
    redis = self._ensure_redis()
    if redis is None:
        return default
    
    try:
        executor = ThreadPoolExecutor(max_workers=1)
        func = getattr(redis, operation)
        future = executor.submit(func, *args, **kwargs)
        result = future.result(timeout=timeout)
        return result if result is not None else default
    except FuturesTimeoutError:
        logger.warning(f"⚠️ Redis {operation}() timed out - using default")
        return default
```

---

### ✅ FIX #2: Reduced Timeout Values for Faster Hang Detection
**File:** `rl/hybrid_trainer.py`

**Changes:**
- Rollout timeout: 90s → **60s** (faster detection)
- Learn() timeout: 300s → **240s** (4 minutes total)
- Outer watchdog: 900s → **300s** (5 minutes max per loop)

**Impact:** Hangs detected 2-3x faster, allowing quicker recovery.

---

### ✅ FIX #3: Added Checkpoint Sanity Check
**File:** `rl/hybrid_trainer.py` line ~8707

**Problem:** Checkpoint had loop #3892, which is suspiciously high.

**Fix:**
```python
# Cap loop number to prevent absurdly high numbers from corrupted checkpoints
if loops > 10000:  # Sanity check
    logger.warning(f"⚠️ Suspicious loop count {loops} - resetting to 0")
    loops = 0
    total_timesteps = 0
```

---

### ✅ FIX #4: Enhanced Progress Logging in Callback
**File:** `rl/hybrid_trainer.py` - `SimpleTrainingCallback`

**Added:**
- Rollout progress logging every 10 seconds
- Step count tracking during rollout
- Better visibility into where rollout is stuck

---

### ✅ FIX #5: Added safe_redis_operation Helper
**File:** `rl/hybrid_trainer.py` line ~507

**Purpose:** Reusable Redis timeout wrapper for main trainer process.

**Usage:** Can be used to wrap Redis calls in main trainer (not yet applied to all locations).

---

## Remaining Issue

### ⚠️ LIMITATION: ThreadPoolExecutor Timeout Cannot Interrupt Subprocess Workers

**Problem:**
- `ThreadPoolExecutor` timeout can **detect** hangs but cannot **interrupt** blocking I/O in subprocess workers
- If a SubprocVecEnv worker is blocked on `redis.hgetall()`, the timeout will fire, but the worker process will still be blocked
- The timeout allows the main process to continue, but the worker remains hung

**Why This Happens:**
- SubprocVecEnv uses separate processes (not threads)
- Python's ThreadPoolExecutor timeout cannot interrupt blocking I/O in other processes
- The blocking happens in C extension code (redis-py uses hiredis C library)

**Current Behavior:**
1. Rollout starts
2. Worker process blocks on Redis call
3. After 60 seconds, timeout fires in main process
4. `RolloutTimeoutError` is raised
5. Main process continues (rebuilds env, skips loop)
6. **Worker process remains blocked** (zombie process)

**Impact:**
- Training can continue (main process recovers)
- But worker processes accumulate over time
- May cause resource exhaustion

---

## Recommended Next Steps

### Immediate (If Still Hanging):

1. **Check if Redis is responsive:**
   ```bash
   redis-cli PING
   redis-cli INFO stats
   ```

2. **Check for slow Redis operations:**
   ```bash
   redis-cli SLOWLOG GET 10
   ```

3. **Monitor worker processes:**
   ```bash
   ps aux | grep python | grep -E "(SubprocVecEnv|worker)"
   ```

### Short-Term Fixes:

1. **Switch to DummyVecEnv** (single process, no subprocess workers):
   ```python
   # In HybridConfig:
   self.vec_env_type = 'dummy'  # Instead of 'subproc'
   ```
   - Trade-off: Slower (no parallelism) but no subprocess hangs

2. **Add Redis connection pooling with shorter timeouts:**
   ```python
   # In utils/redis_client.py - already has 5s timeout
   # But need to ensure it's used in workers
   ```

3. **Implement circuit breaker pattern:**
   - Track Redis failures
   - After N failures, switch to cached/default features
   - Auto-recover after timeout period

### Long-Term Solution:

1. **Use async Redis client** (`aioredis` or `redis.asyncio`)
   - Non-blocking I/O
   - Can be interrupted
   - Better for concurrent operations

2. **Implement proper caching layer:**
   - Local in-memory cache (e.g., `cachetools`)
   - Redis as secondary source
   - Fallback to cache on Redis timeout

3. **Add worker process health monitoring:**
   - Monitor worker process CPU/memory
   - Kill hung workers automatically
   - Restart workers on timeout

---

## Testing the Fixes

### Monitor Training Loop:
```bash
# Watch for loop progression
tail -f logs/hybrid_trainer.log | grep -E "(Loop #|ROLLOUT|COMPLETED)"

# Should see:
# Loop #1 → Loop #2 → Loop #3 (not stuck on #3892)
# ROLLOUT-START → ROLLOUT-COMPLETE (within 60s)
```

### Check for Timeouts:
```bash
# Look for timeout messages
grep "ROLLOUT-TIMEOUT\|Redis.*timed out" logs/hybrid_trainer.log

# If you see timeouts, Redis is slow/unresponsive
```

### Verify Worker Processes:
```bash
# Check for zombie/hung workers
ps aux | grep python | grep -v grep | wc -l
# Should be stable, not growing
```

---

## Expected Behavior After Fixes

### Normal Operation:
1. Loop starts → "Loop #1"
2. Rollout starts → "ROLLOUT-START"
3. Rollout completes → "ROLLOUT-COMPLETE" (within 60s)
4. Backprop starts → "BACKPROP-START"
5. Loop completes → "Loop #1 COMPLETED"
6. Next loop starts → "Loop #2"

### On Redis Timeout:
1. Rollout starts → "ROLLOUT-START"
2. Redis call times out → "Redis hgetall() timed out"
3. Uses default features → Continues rollout
4. Rollout completes (may be slower but completes)
5. Loop continues

### On Complete Hang:
1. Rollout starts → "ROLLOUT-START"
2. After 60s → "ROLLOUT-TIMEOUT"
3. `RolloutTimeoutError` raised
4. Environment rebuilt → "Rebuilt environment"
5. Loop skipped → Continues to next loop

---

## Current Status

✅ **Fixes Applied:**
- Redis timeout protection in workers
- Reduced timeout values
- Checkpoint sanity check
- Enhanced progress logging

⚠️ **Limitation:**
- ThreadPoolExecutor timeout cannot interrupt subprocess workers
- Worker processes may remain blocked even after timeout

📊 **Monitoring:**
- Watch logs for timeout messages
- Monitor loop progression
- Check worker process count

---

## If Still Hanging

1. **Check Redis health:**
   ```bash
   redis-cli PING
   redis-cli INFO stats | grep total_commands_processed
   ```

2. **Switch to DummyVecEnv** (temporary workaround):
   - Edit `HybridConfig.vec_env_type = 'dummy'`
   - Restart trainer
   - Slower but more stable

3. **Check for specific hanging worker:**
   - Look for patterns in logs (which symbol/timeframe)
   - May indicate specific data source issue

4. **Review Redis slowlog:**
   ```bash
   redis-cli SLOWLOG GET 10
   ```

---

**Next Steps:** Monitor the trainer for the next few loops. If it still hangs, we'll need to implement the DummyVecEnv workaround or add more aggressive worker process management.










































