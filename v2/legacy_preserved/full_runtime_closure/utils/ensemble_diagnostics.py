import time
import json
import traceback
from utils.redis_client import get_redis

r = get_redis()

DIAG_STREAM = "signals:ensemble:diagnostic"
_LAST_ERR_TS = 0.0


def _log_diag_error(exc: Exception) -> None:
    global _LAST_ERR_TS
    now = time.time()
    try:
        with open("logs/ensemble_diagnostics.log", "a", encoding="utf-8") as fh:
            fh.write(f"\n[{int(now * 1000)}] publish_ensemble_diagnostic failed: {exc}\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass
    # Throttle console visibility to avoid spam
    if now - _LAST_ERR_TS >= 30.0:
        _LAST_ERR_TS = now
        try:
            print(f"[ENSEMBLE_DIAG_ERROR] {exc}")
        except Exception:
            pass


def _redis_safe_payload(payload: dict) -> dict:
    safe = {}
    for k, v in (payload or {}).items():
        key = str(k)
        if isinstance(v, (str, int, float, bytes)):
            safe[key] = v
        elif v is None:
            safe[key] = ""
        else:
            safe[key] = json.dumps(v, separators=(",", ":"), default=str)
    return safe


def publish_ensemble_diagnostic(payload: dict):
    try:
        payload = _redis_safe_payload(dict(payload))
        payload["ts"] = int(time.time() * 1000)
        r.xadd(DIAG_STREAM, payload, maxlen=10000, approximate=True)
    except Exception as exc:
        _log_diag_error(exc)
