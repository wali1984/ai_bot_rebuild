"""
Runtime Feature Flags (Redis-backed)
===================================

Addendum v3 requirement:
- Reduce "restart to change behavior" risk by allowing runtime overrides.

Design:
- Flags are read from Redis key `wma:flags` (either HASH or JSON STRING).
- Env/config values remain the baseline; Redis can override them live.
- Reads are cached briefly to avoid Redis load.
"""

from __future__ import annotations

import json
import time
import os
from typing import Any, Dict, Optional


_CACHE: Dict[str, Any] = {"ts": 0.0, "flags": {}}
_TTL_S = 5.0


def _to_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        # treat 0 as False, nonzero as True
        return bool(v)
    try:
        s = str(v).strip().lower()
    except Exception:
        return None
    if s in ("1", "true", "yes", "on", "enabled"):
        return True
    if s in ("0", "false", "no", "off", "disabled"):
        return False
    return None


def read_flags(redis_client: Any, *, force: bool = False) -> Dict[str, Any]:
    """
    Read flags from Redis key `wma:flags`.
    Supports:
    - HASH: fields are flags
    - STRING: JSON dict
    """
    now = time.time()
    if not force and (now - float(_CACHE.get("ts", 0.0) or 0.0)) < _TTL_S:
        return dict(_CACHE.get("flags") or {})

    flags: Dict[str, Any] = {}
    if redis_client is None:
        _CACHE["ts"] = now
        _CACHE["flags"] = flags
        return dict(flags)

    try:
        # Prefer type check if available; fall back to best-effort.
        t = None
        try:
            t = redis_client.type("wma:flags")
        except Exception:
            t = None

        if t == "hash":
            raw = redis_client.hgetall("wma:flags") or {}
            # Normalize bytes
            for k, v in (raw or {}).items():
                try:
                    kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                except Exception:
                    kk = str(k)
                try:
                    vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
                except Exception:
                    vv = v
                flags[str(kk)] = vv
        else:
            raw = redis_client.get("wma:flags")
            if raw:
                raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                try:
                    obj = json.loads(raw) if raw else {}
                    if isinstance(obj, dict):
                        flags.update(obj)
                except Exception:
                    flags = {}
    except Exception:
        flags = {}

    _CACHE["ts"] = now
    _CACHE["flags"] = dict(flags)
    return dict(flags)


def get_flag(redis_client: Any, name: str, default: Any = None) -> Any:
    flags = read_flags(redis_client)
    if name not in flags:
        return default
    v = flags.get(name)
    # try bool normalization for common patterns
    b = _to_bool(v)
    return b if b is not None else v


def get_flag_bool(redis_client: Any, name: str, default: bool = False) -> bool:
    v = get_flag(redis_client, name, default)
    b = _to_bool(v)
    return bool(default) if b is None else bool(b)


def get_flag_env(redis_client: Any, name: str, default: Any = None, env_name: Optional[str] = None) -> Any:
    """
    Read a flag from environment first (if set), then Redis-backed flags.
    """
    try:
        env_key = env_name or name
        if env_key and env_key in os.environ:
            return os.getenv(env_key)
    except Exception:
        pass
    return get_flag(redis_client, name, default)


def get_flag_bool_env(redis_client: Any, name: str, default: bool = False, env_name: Optional[str] = None) -> bool:
    v = get_flag_env(redis_client, name, default, env_name=env_name)
    b = _to_bool(v)
    return bool(default) if b is None else bool(b)

