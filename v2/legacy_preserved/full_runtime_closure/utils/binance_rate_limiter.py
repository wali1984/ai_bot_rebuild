import asyncio
import inspect
import time
import threading
import os
import sys
import socket
from datetime import datetime
from typing import Optional, Tuple

try:
    # Local redis helper keeps connection pooling consistent
    from utils.redis_client import get_redis
except Exception:
    get_redis = None

class BinanceRateLimiter:
    """
    Token-bucket rate limiter to throttle Binance REST calls safely below account/IP limits.

    Default limits are conservative to account for multiple cooperating processes.
    """

    def __init__(self, max_per_minute: int = 300, burst: int = 30):
        self.capacity = max(burst, 1)
        self.fill_rate = max_per_minute / 60.0 if max_per_minute > 0 else 0.0
        self.tokens = float(self.capacity)
        self.last_check = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self, now: float) -> None:
        if self.fill_rate <= 0:
            return
        elapsed = now - self.last_check
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
        self.last_check = now

    def acquire_delay(self, cost: int = 1) -> float:
        """Return required delay (seconds) to stay within the bucket; 0 if allowed now."""
        if cost <= 0:
            return 0.0
        now = time.monotonic()
        with self.lock:
            self._refill(now)
            if self.tokens >= cost:
                self.tokens -= cost
                return 0.0
            deficit = cost - self.tokens
            delay = deficit / self.fill_rate if self.fill_rate > 0 else 0.0
            # Reserve tokens after the delay to avoid concurrent overshoot
            self.tokens = 0.0
            self.last_check = now
            return delay

    def maybe_sleep(self, cost: int = 1) -> float:
        """
        Sleep if needed to respect the bucket. Returns the sleep duration performed.
        """
        delay = self.acquire_delay(cost)
        if delay > 0:
            time.sleep(delay)
        return delay

# Singleton helper for simple usage without wiring through classes
_default_limiter: Optional[BinanceRateLimiter] = None

def get_default_limiter(max_per_minute: int = 300, burst: int = 30) -> BinanceRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = BinanceRateLimiter(max_per_minute=max_per_minute, burst=burst)
    return _default_limiter


class RedisBinanceRateLimiter:
    """Distributed token bucket using Redis so multiple processes share one budget."""

    LUA_SCRIPT = """
    local key = KEYS[1]
    local now_ms = tonumber(ARGV[1])
    local capacity = tonumber(ARGV[2])
    local fill_rate = tonumber(ARGV[3])
    local cost = tonumber(ARGV[4])

    local data = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
    local tokens = tonumber(data[1]) or capacity
    local last_refill = tonumber(data[2]) or now_ms

    local elapsed = now_ms - last_refill
    if elapsed < 0 then
      elapsed = 0
    end

    if fill_rate > 0 then
      tokens = math.min(capacity, tokens + (elapsed / 1000.0) * fill_rate)
    end

    last_refill = now_ms
    local allowed = 0
    local delay_ms = 0

    if cost <= 0 then
      allowed = 1
    elseif tokens >= cost then
      tokens = tokens - cost
      allowed = 1
    else
      local deficit = cost - tokens
      if fill_rate > 0 then
        delay_ms = math.ceil((deficit / fill_rate) * 1000)
      else
        delay_ms = 0
      end
      tokens = 0
    end

    redis.call('HMSET', key, 'tokens', tokens, 'last_refill_ms', last_refill)
    redis.call('PEXPIRE', key, 120000)
    return {allowed, delay_ms, tokens}
    """

    def __init__(
        self,
        redis_key: str = "binance:limits:rest",
        max_per_minute: int = 120,
        burst: int = 15,
    ):
        self.redis_key = redis_key
        self.capacity = max(burst, 1)
        self.fill_rate = max_per_minute / 60.0 if max_per_minute > 0 else 0.0
        self.redis = get_redis() if get_redis else None
        self.script_sha: Optional[str] = None
        self._load_script()

    def _load_script(self) -> None:
        if self.redis is None:
            return
        try:
            self.script_sha = self.redis.script_load(self.LUA_SCRIPT)
        except Exception:
            self.script_sha = None

    def _eval(self, cost: int, now_ms: int) -> Optional[Tuple[int, int, float]]:
        if self.redis is None:
            return None
        if self.script_sha is None:
            self._load_script()
        try:
            return self.redis.evalsha(
                self.script_sha,
                1,
                self.redis_key,
                now_ms,
                self.capacity,
                self.fill_rate,
                cost,
            )
        except Exception:
            # Script may have been flushed; reload once.
            try:
                self._load_script()
                return self.redis.evalsha(
                    self.script_sha,
                    1,
                    self.redis_key,
                    now_ms,
                    self.capacity,
                    self.fill_rate,
                    cost,
                )
            except Exception:
                return None

    def acquire_delay(self, cost: int = 1) -> float:
        now_ms = int(time.time() * 1000)
        result = self._eval(cost, now_ms)
        if not result:
            return 0.0
        allowed, delay_ms, _ = result
        if allowed == 1:
            return 0.0
        return max(delay_ms, 0) / 1000.0

    def maybe_sleep(self, cost: int = 1) -> float:
        delay = self.acquire_delay(cost)
        if delay > 0:
            time.sleep(delay)
        return delay


# Ban flag helpers shared across services
BAN_KEY = "binance:ban"


def _safe_notify(notifier, message: str) -> None:
    """Invoke notifier and ensure coroutine results get scheduled."""
    if not callable(notifier):
        return
    try:
        result = notifier(message)
        if inspect.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(result)
            except RuntimeError:
                asyncio.run(result)
    except Exception:
        return


def set_ban(redis_client, until_ms: int, source: str = "unknown", reason: str = "", notifier=None, details: Optional[dict] = None) -> None:
    if not redis_client or until_ms <= 0:
        return
    now_ms = int(time.time() * 1000)
    ttl_seconds = max(int((until_ms - now_ms) / 1000) + 30, 60)
    mapping = {
        "until_ms": until_ms,
        "source": source,
        "reason": reason,
        "updated_ms": now_ms,
    }
    event = {
        "ts_ms": now_ms,
        "until_ms": until_ms,
        "source": source,
        "reason": reason,
        "pid": os.getpid(),
        "script": os.path.basename(sys.argv[0]) if sys.argv else "",
        "hostname": socket.gethostname(),
    }
    if details:
        try:
            event.update(details)
        except Exception:
            pass
    try:
        pipe = redis_client.pipeline()
        pipe.hset(BAN_KEY, mapping=mapping)
        pipe.expire(BAN_KEY, ttl_seconds)
        # Push a short-lived audit trail to attribute bans to processes
        pipe.lpush(f"{BAN_KEY}:events", str(event))
        pipe.ltrim(f"{BAN_KEY}:events", 0, 199)
        pipe.expire(f"{BAN_KEY}:events", ttl_seconds)
        pipe.execute()

        human_until = datetime.fromtimestamp(until_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
        detail_keys = ""
        if details:
            try:
                detail_keys = ",".join(sorted(str(k) for k in details.keys()))
            except Exception:
                detail_keys = ""
        detail_suffix = f" details_keys={detail_keys}" if detail_keys else ""
        notify_msg = (
            f"🚫 Binance ban set until {human_until} ({until_ms} ms). "
            f"source={source} reason={reason or 'unspecified'} "
            f"host={event.get('hostname')} pid={event.get('pid')} script={event.get('script')}{detail_suffix}"
        )
        _safe_notify(notifier, notify_msg)
    except Exception:
        return


def clear_ban(redis_client, notifier=None) -> None:
    if not redis_client:
        return
    try:
        redis_client.delete(BAN_KEY)
        _safe_notify(notifier, "✅ Binance ban cleared")
    except Exception:
        return


def get_ban(redis_client) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        data = redis_client.hgetall(BAN_KEY)
        if not data:
            return None
        parsed = {}
        for k, v in data.items():
            try:
                parsed[k] = int(v)
            except Exception:
                parsed[k] = v
        return parsed
    except Exception:
        return None


def is_banned(redis_client, now_ms: Optional[int] = None, notifier=None) -> Tuple[bool, int]:
    now_ms = now_ms or int(time.time() * 1000)
    data = get_ban(redis_client)
    if not data or "until_ms" not in data:
        return False, 0
    remaining = int(data.get("until_ms", 0)) - now_ms
    if remaining > 0:
        return True, remaining
    # Auto-clear expired bans
    try:
        clear_ban(redis_client, notifier=notifier)
    except Exception:
        pass
    return False, 0


def maybe_clear_ban(redis_client, notifier=None, now_ms: Optional[int] = None) -> None:
    now_ms = now_ms or int(time.time() * 1000)
    data = get_ban(redis_client)
    if not data or "until_ms" not in data:
        return
    if int(data.get("until_ms", 0)) <= now_ms:
        clear_ban(redis_client, notifier=notifier)
