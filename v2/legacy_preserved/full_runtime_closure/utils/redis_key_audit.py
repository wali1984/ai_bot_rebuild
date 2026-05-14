import os
import re
import json
import inspect
import threading
import time

_LOG_PATH = os.environ.get("REDIS_KEY_AUDIT_LOG", "logs/redis_key_audit.log")
_CONTROL_PATH = os.environ.get("REDIS_KEY_AUDIT_CONTROLPLANE_LOG", "logs/redis_key_audit_controlplane.log")
_LOCK = threading.Lock()
_CONTROL_RE = re.compile(r"^(signals:(trading|overlay|trainer):|wma:|executed_signals)")

_METHODS = [
    "xadd",
    "xreadgroup",
    "xread",
    "xrange",
    "xrevrange",
    "get",
    "set",
    "setex",
    "mget",
    "mset",
    "delete",
    "expire",
    "hget",
    "hset",
    "hmget",
    "hmset",
    "publish",
    "subscribe",
    "lpush",
    "rpush",
    "lrange",
]

_CONTROL_OPS = {
    "xadd",
    "xread",
    "xreadgroup",
    "xrange",
    "xrevrange",
    "set",
    "setex",
    "mset",
    "delete",
    "expire",
}

# Max log size: 100MB per file, rotate to .1 backup
_MAX_LOG_SIZE = int(os.environ.get("REDIS_KEY_AUDIT_MAX_SIZE", 100 * 1024 * 1024))
_last_size_check_main = 0
_last_size_check_ctrl = 0


def _rotate_if_needed(path: str, check_attr: str):
    """Rotate log file if it exceeds _MAX_LOG_SIZE. Checks at most once/minute."""
    global _last_size_check_main, _last_size_check_ctrl
    now = time.monotonic()
    last = _last_size_check_main if check_attr == "main" else _last_size_check_ctrl
    if now - last < 60:
        return
    if check_attr == "main":
        _last_size_check_main = now
    else:
        _last_size_check_ctrl = now
    try:
        if os.path.getsize(path) > _MAX_LOG_SIZE:
            backup = path + ".1"
            try:
                os.remove(backup)
            except OSError:
                pass
            os.rename(path, backup)
    except OSError:
        pass


def _log(op: str, key):
    try:
        k = str(key)
    except Exception:
        k = repr(key)
    line = f"ts={int(time.time() * 1000)} pid={os.getpid()} op={op} key={k}\n"
    with _LOCK:
        os.makedirs(os.path.dirname(_LOG_PATH) or ".", exist_ok=True)
        _rotate_if_needed(_LOG_PATH, "main")
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def _find_callsite() -> dict:
    try:
        for fr in inspect.stack()[2:12]:
            fn = str(getattr(fr, "filename", "") or "")
            fn_norm = fn.replace("\\", "/")
            if "/utils/" in fn_norm or "/site-packages/redis" in fn_norm:
                continue
            return {
                "file": fn_norm,
                "line": int(getattr(fr, "lineno", 0) or 0),
                "func": str(getattr(fr, "function", "") or ""),
            }
    except Exception:
        pass
    return {"file": "", "line": 0, "func": ""}


def _log_controlplane(op: str, key):
    op_l = str(op).lower()
    if op_l not in _CONTROL_OPS:
        return
    try:
        k = str(key)
    except Exception:
        k = repr(key)
    if not _CONTROL_RE.match(k):
        return

    rec = {
        "ts": int(time.time() * 1000),
        "pid": os.getpid(),
        "op": op_l,
        "key": k,
    }
    rec.update(_find_callsite())

    with _LOCK:
        os.makedirs(os.path.dirname(_CONTROL_PATH) or ".", exist_ok=True)
        _rotate_if_needed(_CONTROL_PATH, "ctrl")
        with open(_CONTROL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")


def _extract_keys(op: str, args, kwargs):
    op_l = str(op).lower()
    keys = []
    try:
        if op_l in ("xrange", "xrevrange", "xadd"):
            if args:
                keys.append(args[0])
            elif "name" in kwargs:
                keys.append(kwargs.get("name"))
            elif "key" in kwargs:
                keys.append(kwargs.get("key"))
            return keys

        if op_l == "xread":
            streams = None
            if args:
                streams = args[0]
            if streams is None:
                streams = kwargs.get("streams")
            if isinstance(streams, dict):
                keys.extend(list(streams.keys()))
            elif streams is not None:
                keys.append(streams)
            return keys

        if op_l == "xreadgroup":
            streams = kwargs.get("streams")
            if streams is None and len(args) >= 3:
                streams = args[2]
            if isinstance(streams, dict):
                keys.extend(list(streams.keys()))
            elif streams is not None:
                keys.append(streams)
            return keys

        if op_l == "mset":
            mapping = args[0] if args else kwargs.get("mapping")
            if isinstance(mapping, dict):
                keys.extend(list(mapping.keys()))
            return keys

        if op_l == "delete":
            if args:
                keys.extend(list(args))
            elif "names" in kwargs and isinstance(kwargs.get("names"), (list, tuple)):
                keys.extend(list(kwargs.get("names") or []))
            return keys

        if op_l in ("set", "setex", "expire"):
            if args:
                keys.append(args[0])
            elif "name" in kwargs:
                keys.append(kwargs.get("name"))
            elif "key" in kwargs:
                keys.append(kwargs.get("key"))
            return keys

        if args:
            keys.append(args[0])
    except Exception:
        pass
    return keys


def wrap_redis_client(client):
    """Wrap redis methods to audit key/stream/channel args without changing behavior."""
    if client is None:
        return client

    if getattr(client, "_redis_key_audit_wrapped", False):
        return client

    for name in _METHODS:
        if not hasattr(client, name):
            continue
        orig = getattr(client, name)
        if not callable(orig):
            continue

        def make_wrapper(_name, _orig):
            def wrapper(*args, **kwargs):
                keys = _extract_keys(_name, args, kwargs)
                if keys:
                    for k in keys:
                        _log(_name, k)
                        _log_controlplane(_name, k)
                return _orig(*args, **kwargs)

            return wrapper

        setattr(client, name, make_wrapper(name, orig))

    try:
        setattr(client, "_redis_key_audit_wrapped", True)
    except Exception:
        pass

    return client
