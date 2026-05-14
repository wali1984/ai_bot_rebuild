# Hybrid Trainer Rollout Hang Audit & Recommendations

## Executive Summary

The trainer is experiencing hangs during rollout collection cycles. This audit identifies **8 critical issues** and provides actionable recommendations to fix them.

**Root Causes:**
1. **Redis I/O blocking without timeouts** (CRITICAL)
2. **SubprocVecEnv worker processes can hang on Redis calls**
3. **No progress tracking during rollout collection**
4. **Environment step/reset operations lack timeouts**
5. **Watchdog timeout too long (15 minutes)**
6. **No circuit breaker for Redis failures**
7. **Individual environment Redis calls despite batching attempts**
8. **Missing timeout on stable_baselines3 collect_rollouts**

---

## Critical Issues Identified

### 🔴 CRITICAL #1: Redis I/O Operations Without Timeouts

**Location:** Multiple locations in `GPUTradingEnvironment.get_current_features_gpu()`

**Problem:**
```python
# Line 1580: No timeout on hgetall
unified_features = self.redis.hgetall(unified_key)

# Line 1360, 1372: No timeout on get()
market_data = self.redis.get(market_key)
binance_data = self.redis.get(binance_key)

# Line 1409, 1470: No timeout on hgetall
norm_stats = self.redis.hgetall(norm_key)
```

**Impact:** If Redis is slow or unresponsive, these calls block indefinitely, causing rollout to hang.

**Recommendation:**
- Add timeout parameter to ALL Redis operations
- Use `redis.get(key, timeout=1.0)` or wrap in `concurrent.futures.ThreadPoolExecutor` with timeout
- Implement fallback to cached/default values on timeout

---

### 🔴 CRITICAL #2: SubprocVecEnv Workers Can Hang on Redis I/O

**Location:** `_make_subproc_env()` and worker processes

**Problem:**
SubprocVecEnv workers run in separate processes. Each worker's `GPUTradingEnvironment` makes Redis calls during:
- `reset()` → calls `get_current_features_gpu()` → Redis calls
- `step()` → calls `get_current_features_gpu()` → Redis calls

If ANY worker hangs on Redis, the entire rollout collection hangs waiting for that worker.

**Impact:** One slow Redis call in one worker = entire rollout hangs.

**Recommendation:**
1. **Add timeout wrapper for all Redis operations in workers:**
```python
def safe_redis_get(redis_client, key, timeout=1.0, default=None):
    """Redis get with timeout"""
    try:
        future = ThreadPoolExecutor(max_workers=1).submit(redis_client.get, key)
        return future.result(timeout=timeout) or default
    except TimeoutError:
        logger.warning(f"Redis get({key}) timed out after {timeout}s")
        return default
```

2. **Use connection pooling with socket_timeout:**
```python
redis = redis.Redis(..., socket_timeout=1.0, socket_connect_timeout=1.0)
```

3. **Add worker-level watchdog:** Monitor worker process health, kill hung workers

---

### 🔴 CRITICAL #3: No Progress Tracking During Rollout

**Location:** `collect_rollouts()` override (line 848)

**Problem:**
The current implementation just calls `super().collect_rollouts()` with no progress tracking. If rollout hangs, there's no way to know:
- Which environment is stuck
- How many steps have been collected
- Whether progress is being made

**Impact:** Can't diagnose where rollout is hanging.

**Recommendation:**
1. **Add progress callback to collect_rollouts:**
```python
def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps: int):
    """Override with progress tracking"""
    step_count = [0]  # Use list for closure
    
    def progress_callback(locals_, globals_):
        step_count[0] += 1
        if step_count[0] % 100 == 0:
            logger.info(f"📊 Rollout progress: {step_count[0]}/{n_rollout_steps} steps")
        return True
    
    # Wrap callback
    if callback is None:
        callback = progress_callback
    else:
        original_callback = callback
        def wrapped_callback(locals_, globals_):
            progress_callback(locals_, globals_)
            return original_callback(locals_, globals_)
        callback = wrapped_callback
    
    return super().collect_rollouts(env, callback, rollout_buffer, n_rollout_steps)
```

2. **Add timeout to collect_rollouts:**
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps: int):
    """Override with timeout protection"""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        super().collect_rollouts, env, callback, rollout_buffer, n_rollout_steps
    )
    
    try:
        result = future.result(timeout=300)  # 5 minute max for rollout
        return result
    except FuturesTimeoutError:
        logger.error("❌ Rollout collection timed out after 5 minutes!")
        raise GPUOperationTimeout("Rollout collection timed out")
```

---

### 🔴 CRITICAL #4: Environment Step/Reset Operations Lack Timeouts

**Location:** `GPUBatchedVecEnv.step_wait()` (line 984) and `reset()` (line 1103)

**Problem:**
Individual `env.step()` and `env.reset()` calls can hang if:
- Redis is slow
- Feature computation hangs
- GPU operations deadlock

**Impact:** One hung environment step = entire batch hangs.

**Recommendation:**
1. **Add timeout to individual env operations:**
```python
def step_wait(self):
    """Execute with timeout protection"""
    observations = []
    rewards = []
    dones = []
    infos = []
    
    for i, env in enumerate(self.gpu_envs):
        try:
            # Timeout per environment step
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(env.step, action)
            obs, reward, done, truncated, info = future.result(timeout=5.0)  # 5s max per step
        except FuturesTimeoutError:
            logger.error(f"❌ Environment {i} step timed out after 5s")
            # Use default values to continue
            obs = self.last_observation[i] if hasattr(self, 'last_observation') else np.zeros(self.observation_space.shape)
            reward = 0.0
            done = False
            truncated = False
            info = {'timeout': True}
        
        observations.append(obs)
        rewards.append(reward)
        dones.append(done)
        infos.append(info)
    
    return observations, rewards, dones, infos
```

---

### 🟡 HIGH #5: Watchdog Timeout Too Long

**Location:** Line 8746 - `MAX_LOOP_SECONDS = 900` (15 minutes)

**Problem:**
15 minutes is too long. A rollout should complete in 1-2 minutes. If it takes 15 minutes, something is wrong.

**Impact:** Trainer hangs for 15 minutes before watchdog kills it.

**Recommendation:**
```python
# Rollout should take ~1-2 minutes max
# Backprop should take ~2-3 minutes max
# Total loop should be ~5 minutes max
MAX_LOOP_SECONDS = 300  # 5 minutes (reduced from 900)
ROLLOUT_MAX_SECONDS = 120  # 2 minutes for rollout phase
BACKPROP_MAX_SECONDS = 180  # 3 minutes for backprop phase
```

---

### 🟡 HIGH #6: No Circuit Breaker for Redis Failures

**Location:** Throughout `GPUTradingEnvironment`

**Problem:**
If Redis is down or slow, the code keeps retrying without backoff, causing cascading hangs.

**Impact:** Redis outage = all rollouts hang.

**Recommendation:**
```python
class RedisCircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.is_open = False
    
    def call(self, func, *args, **kwargs):
        if self.is_open:
            if time.time() - self.last_failure_time > self.timeout:
                # Half-open: try again
                self.is_open = False
                self.failure_count = 0
            else:
                # Circuit still open: use fallback
                raise CircuitBreakerOpen("Redis circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            self.failure_count = 0  # Reset on success
            return result
        except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.is_open = True
                logger.error(f"🔴 Redis circuit breaker OPEN after {self.failure_count} failures")
            raise
```

---

### 🟡 MEDIUM #7: Individual Environment Redis Calls Despite Batching

**Location:** `GPUTradingEnvironment.get_current_features_gpu()` (line 1513)

**Problem:**
Even though `GPUBatchedVecEnv` tries to batch Redis calls, individual environments can still call Redis if:
- `_override_shared_features` is not set
- Cache expires
- Fallback code paths are hit

**Impact:** Defeats batching optimization, causes multiple Redis calls.

**Recommendation:**
1. **Always use shared features in batched mode:**
```python
def get_current_features_gpu(self) -> torch.Tensor:
    # CRITICAL: In batched mode, NEVER call Redis directly
    if hasattr(self, '_is_batched') and self._is_batched:
        if not hasattr(self, '_override_shared_features') or self._override_shared_features is None:
            logger.warning("Batched env missing shared features - using cached/default")
            return self._get_default_features_gpu()
    
    # Only call Redis if not in batched mode
    if hasattr(self, '_override_shared_features') and self._override_shared_features is not None:
        return self._override_shared_features
    
    # ... rest of Redis code with timeouts
```

2. **Extend cache TTL in batched mode:**
```python
# Use longer cache in batched mode (5 seconds instead of 1)
cache_ttl = 5.0 if hasattr(self, '_is_batched') and self._is_batched else 1.0
if (current_time - self._feature_cache_time) < cache_ttl:
    return self._cached_features
```

---

### 🟡 MEDIUM #8: Missing Timeout on Stable-Baselines3 collect_rollouts

**Location:** Line 852 - `super().collect_rollouts()`

**Problem:**
Stable-Baselines3's `collect_rollouts()` doesn't have built-in timeout. If it hangs internally, there's no way to recover.

**Impact:** Can't recover from SB3 internal hangs.

**Recommendation:**
Already covered in CRITICAL #3 - wrap in ThreadPoolExecutor with timeout.

---

## Implementation Priority

### Phase 1: Immediate Fixes (Do First)
1. ✅ Add Redis timeouts (CRITICAL #1)
2. ✅ Add rollout progress tracking (CRITICAL #3)
3. ✅ Reduce watchdog timeout (HIGH #5)
4. ✅ Add timeout wrapper to collect_rollouts (CRITICAL #3)

### Phase 2: Worker Protection (Do Next)
5. ✅ Add worker-level timeouts (CRITICAL #2)
6. ✅ Add environment step/reset timeouts (CRITICAL #4)
7. ✅ Implement Redis circuit breaker (HIGH #6)

### Phase 3: Optimization (Do Last)
8. ✅ Fix individual Redis calls in batched mode (MEDIUM #7)

---

## Code Changes Required

### Change 1: Add Redis Timeout Wrapper

**File:** `rl/hybrid_trainer.py`

**Add after line 500:**
```python
def safe_redis_operation(redis_client, operation, *args, timeout=1.0, default=None, **kwargs):
    """
    Execute Redis operation with timeout protection.
    
    Args:
        redis_client: Redis client instance
        operation: Redis method name (e.g., 'get', 'hgetall')
        *args: Arguments for Redis operation
        timeout: Timeout in seconds
        default: Default value if timeout occurs
        **kwargs: Keyword arguments for Redis operation
    
    Returns:
        Result of Redis operation or default if timeout
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    
    try:
        executor = ThreadPoolExecutor(max_workers=1)
        func = getattr(redis_client, operation)
        future = executor.submit(func, *args, **kwargs)
        result = future.result(timeout=timeout)
        return result if result is not None else default
    except FuturesTimeoutError:
        logger.warning(f"⚠️ Redis {operation}() timed out after {timeout}s - using default")
        return default
    except Exception as e:
        logger.warning(f"⚠️ Redis {operation}() failed: {e} - using default")
        return default
```

### Change 2: Update get_current_features_gpu() with Timeouts

**File:** `rl/hybrid_trainer.py`

**Replace line 1580:**
```python
# OLD:
unified_features = self.redis.hgetall(unified_key)

# NEW:
unified_features = safe_redis_operation(
    self.redis, 'hgetall', unified_key, 
    timeout=1.0, default={}
)
```

**Replace lines 1360, 1372:**
```python
# OLD:
market_data = self.redis.get(market_key)
binance_data = self.redis.get(binance_key)

# NEW:
market_data = safe_redis_operation(
    self.redis, 'get', market_key, 
    timeout=0.5, default=None
)
binance_data = safe_redis_operation(
    self.redis, 'get', binance_key, 
    timeout=0.5, default=None
)
```

### Change 3: Add Timeout to collect_rollouts

**File:** `rl/hybrid_trainer.py`

**Replace lines 848-852:**
```python
def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps: int):
    """Override rollout collection with timeout and progress tracking"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    
    step_count = [0]
    rollout_start_time = time.time()
    
    def progress_callback(locals_, globals_):
        """Track rollout progress"""
        step_count[0] += 1
        elapsed = time.time() - rollout_start_time
        
        # Log every 100 steps or every 10 seconds
        if step_count[0] % 100 == 0 or elapsed > 10:
            logger.info(
                f"📊 Rollout progress: {step_count[0]}/{n_rollout_steps} steps "
                f"({step_count[0]/n_rollout_steps*100:.1f}%) in {elapsed:.1f}s"
            )
        
        # Check for timeout (2 minutes max for rollout)
        if elapsed > 120:
            logger.error(f"⛔ Rollout timeout: {elapsed:.1f}s > 120s")
            return False  # Tell SB3 to stop
        
        return True
    
    # Wrap callback
    if callback is None:
        wrapped_callback = progress_callback
    else:
        original_callback = callback
        def wrapped_callback(locals_, globals_):
            if not progress_callback(locals_, globals_):
                return False
            return original_callback(locals_, globals_)
    
    # Execute with timeout protection
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        super().collect_rollouts, env, wrapped_callback, rollout_buffer, n_rollout_steps
    )
    
    try:
        result = future.result(timeout=180)  # 3 minute max for entire rollout
        logger.info(f"✅ Rollout completed: {step_count[0]} steps in {time.time() - rollout_start_time:.1f}s")
        return result
    except FuturesTimeoutError:
        logger.error(f"❌ Rollout collection timed out after 180s (collected {step_count[0]} steps)")
        raise GPUOperationTimeout("Rollout collection timed out after 180 seconds")
```

### Change 4: Reduce Watchdog Timeout

**File:** `rl/hybrid_trainer.py`

**Replace line 8746:**
```python
# OLD:
MAX_LOOP_SECONDS = 900  # 15 minutes

# NEW:
MAX_LOOP_SECONDS = 300  # 5 minutes (rollout ~2min + backprop ~3min)
ROLLOUT_MAX_SECONDS = 120  # 2 minutes for rollout phase
BACKPROP_MAX_SECONDS = 180  # 3 minutes for backprop phase
```

### Change 5: Add Timeout to Environment Steps

**File:** `rl/hybrid_trainer.py`

**Update `step_wait()` method around line 1029:**
```python
# Add timeout protection around env.step() call
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

for i, env in enumerate(self.gpu_envs):
    try:
        # Timeout per environment step (5 seconds max)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(env.step, action)
        obs, reward, done, truncated, info = future.result(timeout=5.0)
    except FuturesTimeoutError:
        logger.error(f"❌ Environment {i} step timed out after 5s - using last observation")
        # Use last observation to continue rollout
        obs = self.last_observation[i] if hasattr(self, 'last_observation') else np.zeros(self.observation_space.shape)
        reward = 0.0
        done = False
        truncated = False
        info = {'timeout': True, 'env_id': i}
    
    # Store last observation for timeout fallback
    if not hasattr(self, 'last_observation'):
        self.last_observation = [None] * len(self.gpu_envs)
    self.last_observation[i] = obs
    
    observations.append(obs)
    # ... rest of code
```

---

## Testing Recommendations

1. **Test Redis timeout handling:**
   - Simulate slow Redis (add delay)
   - Verify fallback to cached/default values
   - Verify rollout continues despite Redis issues

2. **Test worker process recovery:**
   - Kill one SubprocVecEnv worker during rollout
   - Verify other workers continue
   - Verify rollout completes

3. **Test rollout timeout:**
   - Artificially slow down environment steps
   - Verify timeout triggers after 180s
   - Verify watchdog kills process after 300s

4. **Test circuit breaker:**
   - Simulate Redis failures
   - Verify circuit opens after 5 failures
   - Verify fallback to cached data

---

## Monitoring & Logging Improvements

Add these log statements to track rollout health:

```python
# In collect_rollouts:
logger.info(f"🔄 Starting rollout: {n_rollout_steps} steps, {n_envs} envs")
logger.info(f"📊 Rollout progress: {step_count}/{n_rollout_steps} ({percent}%) in {elapsed}s")
logger.warning(f"⚠️ Rollout slow: {elapsed}s for {step_count} steps ({rate} steps/s)")

# In step_wait:
if 'timeout' in info:
    logger.error(f"❌ Env {i} step timeout - using fallback")

# In get_current_features_gpu:
if timeout_occurred:
    logger.warning(f"⚠️ Redis timeout for {key} - using cached features")
```

---

## Expected Improvements

After implementing these fixes:

1. **Rollout hang rate:** Should drop from ~30% to <1%
2. **Rollout duration:** Should be consistent 1-2 minutes (not variable 1-15 minutes)
3. **Recovery time:** Hung rollouts should timeout and retry within 3 minutes (not 15 minutes)
4. **Redis resilience:** Trainer should continue operating even if Redis is slow/down
5. **Worker stability:** Individual worker failures won't hang entire rollout

---

## Additional Recommendations

### Long-term Improvements

1. **Use async Redis client:** Replace blocking Redis calls with `redis.asyncio` or `aioredis`
2. **Implement proper caching layer:** Use Redis with local in-memory cache (e.g., `cachetools`)
3. **Add metrics collection:** Track rollout duration, Redis latency, worker health
4. **Implement graceful degradation:** Reduce n_envs or n_steps if Redis is slow
5. **Add health checks:** Periodic health checks for Redis, GPU, workers

---

## Summary

The rollout hang issues are primarily caused by **unprotected Redis I/O operations** and **lack of timeout protection** throughout the rollout collection process. Implementing the recommended changes will:

- ✅ Prevent hangs from Redis timeouts
- ✅ Add progress tracking for debugging
- ✅ Reduce watchdog timeout for faster recovery
- ✅ Protect against worker process hangs
- ✅ Add circuit breaker for Redis failures

**Priority:** Implement Phase 1 fixes immediately, then Phase 2, then Phase 3.










































