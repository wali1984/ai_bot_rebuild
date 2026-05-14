"""risk/reduce_only_latch.py – Standalone reduce-only latch module.

After any deleverage execution, sets a Redis key blocking all risk-add
signals for N seconds. Only CLOSE / TP / stop-loss actions pass through.

Redis key format:  risk:reduce_only_until:{account_id}
Value format:      "{until_epoch_ms}|{reason}"
TTL:               latch_seconds + 10s buffer

Consumers:
  - rl/orchestrator_worker.py  (pre-publish gate)
  - trading/trader.py          (pre-execution gate + post-deleverage set)
  - risk/auto_deleverager.py   (post-deleverage set)
"""

import time
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_KEY_PREFIX = "risk:reduce_only_until"


def _cfg(name: str, default):
    """Safe config lookup — never crashes."""
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


# ── Public API ──────────────────────────────────────────────────────────


def set_latch(
    redis_client,
    account_id: str,
    seconds: int = 900,
    reason: str = "DELEVERAGE_EXECUTED",
) -> Optional[int]:
    """
    Set reduce-only latch for *account_id*.

    Args:
        redis_client: Redis connection
        account_id:   Account identifier
        seconds:      Latch duration (default 900 = 15 min)
        reason:       Human-readable reason string

    Returns:
        Expiry timestamp (ms) if set, None on error / disabled.
    """
    try:
        enabled = bool(_cfg("REDUCE_ONLY_LATCH_ENABLED", True))
        if not enabled or not redis_client:
            return None

        prefix = str(_cfg("REDUCE_ONLY_LATCH_KEY_PREFIX", _DEFAULT_KEY_PREFIX))
        key = f"{prefix}:{account_id}"
        until_ms = int(time.time() * 1000) + (seconds * 1000)
        value = f"{until_ms}|{reason}"
        redis_client.set(key, value, ex=seconds + 10)  # +10s TTL buffer

        logger.warning(
            "REDUCE_ONLY_LATCH_SET | account=%s | duration=%ds | reason=%s | expires_ms=%d",
            account_id, seconds, reason, until_ms,
        )
        return until_ms
    except Exception as e:
        logger.debug("REDUCE_ONLY_LATCH_SET_ERR | %s", e)
        return None


def get_latch(
    redis_client,
    account_id: str,
) -> Tuple[bool, int, str]:
    """
    Check if reduce-only latch is active.

    Returns:
        (active, until_ms, reason)
        If not active: (False, 0, "")
    """
    try:
        enabled = bool(_cfg("REDUCE_ONLY_LATCH_ENABLED", True))
        if not enabled or not redis_client:
            return (False, 0, "")

        prefix = str(_cfg("REDUCE_ONLY_LATCH_KEY_PREFIX", _DEFAULT_KEY_PREFIX))
        key = f"{prefix}:{account_id}"
        val = redis_client.get(key)
        if val is None:
            return (False, 0, "")

        val_str = val if isinstance(val, str) else val.decode("utf-8", errors="replace")

        # Parse "until_ms|reason" format (backward compat with old "until_ms" only)
        if "|" in val_str:
            parts = val_str.split("|", 1)
            until_ms = int(parts[0])
            reason = parts[1]
        else:
            until_ms = int(val_str)
            reason = "UNKNOWN"

        now_ms = int(time.time() * 1000)
        if now_ms < until_ms:
            return (True, until_ms, reason)

        # Expired — clean up
        try:
            redis_client.delete(key)
        except Exception:
            pass
        return (False, 0, "")
    except Exception:
        return (False, 0, "")  # Fail-open


def clear_latch(redis_client, account_id: str) -> bool:
    """Manually clear an active latch (admin / kill-switch use)."""
    try:
        prefix = str(_cfg("REDUCE_ONLY_LATCH_KEY_PREFIX", _DEFAULT_KEY_PREFIX))
        key = f"{prefix}:{account_id}"
        deleted = redis_client.delete(key)
        if deleted:
            logger.warning("REDUCE_ONLY_LATCH_CLEARED | account=%s", account_id)
        return bool(deleted)
    except Exception as e:
        logger.debug("REDUCE_ONLY_LATCH_CLEAR_ERR | %s", e)
        return False


def set_latch_per_symbol(
    redis_client,
    account_id: str,
    symbol: str,
    seconds: int = 180,
    reason: str = "SYMBOL_KILL_EVENT",
) -> Optional[int]:
    """Set reduce-only latch scoped to a single symbol (does NOT block other symbols)."""
    try:
        key = f"risk:reduce_only_symbol:{account_id}:{symbol}"
        until_ms = int(time.time() * 1000) + (seconds * 1000)
        value = f"{until_ms}|{reason}"
        redis_client.set(key, value, ex=seconds + 10)
        logger.warning(
            "REDUCE_ONLY_LATCH_SYMBOL_SET | account=%s symbol=%s duration=%ds reason=%s",
            account_id, symbol, seconds, reason,
        )
        return until_ms
    except Exception as e:
        logger.debug("REDUCE_ONLY_LATCH_SYMBOL_SET_ERR | %s", e)
        return None


def get_latch_per_symbol(
    redis_client,
    account_id: str,
    symbol: str,
) -> Tuple[bool, int, str]:
    """Check per-symbol reduce-only latch. Returns (active, until_ms, reason)."""
    try:
        key = f"risk:reduce_only_symbol:{account_id}:{symbol}"
        val = redis_client.get(key)
        if val is None:
            return (False, 0, "")
        val_str = val if isinstance(val, str) else val.decode("utf-8", errors="replace")
        if "|" in val_str:
            parts = val_str.split("|", 1)
            until_ms = int(parts[0])
            reason = parts[1]
        else:
            until_ms = int(val_str)
            reason = "UNKNOWN"
        now_ms = int(time.time() * 1000)
        if now_ms < until_ms:
            return (True, until_ms, reason)
        try:
            redis_client.delete(key)
        except Exception:
            pass
        return (False, 0, "")
    except Exception:
        return (False, 0, "")
