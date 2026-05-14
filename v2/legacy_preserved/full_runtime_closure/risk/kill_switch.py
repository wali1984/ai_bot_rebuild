import json
import logging
import time
import inspect
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

KILL_SWITCH_KEY = "wma:kill_switch"


def _default_global_allowlist() -> set:
    # Only true systemic events should be global.
    raw = os.getenv(
        "KILL_SWITCH_GLOBAL_ALLOWLIST",
        "ORCH_STALLED,SYSTEMIC_EMERGENCY,REDIS_DOWN,MARKET_DATA_DOWN,INFRA_EMERGENCY",
    )
    out = set()
    for tok in str(raw or "").split(","):
        t = str(tok or "").strip().upper()
        if t:
            out.add(t)
    return out


def _default_ttl_seconds() -> int:
    try:
        import config as _cfg  # type: ignore

        v = int(getattr(_cfg, "KILL_SWITCH_TTL_SECONDS", 180) or 180)
    except Exception:
        try:
            v = int(os.getenv("KILL_SWITCH_TTL_SECONDS", "180") or 180)
        except Exception:
            v = 180
    return max(30, min(3600, int(v)))


def _caller_provenance() -> Dict[str, Any]:
    try:
        for fr in inspect.stack()[2:14]:
            fn = str(getattr(fr, "filename", "") or "").replace("\\", "/")
            if "/risk/kill_switch.py" in fn:
                continue
            return {
                "source_file": fn,
                "source_line": int(getattr(fr, "lineno", 0) or 0),
                "source_func": str(getattr(fr, "function", "") or ""),
            }
    except Exception:
        pass
    return {"source_file": "", "source_line": 0, "source_func": ""}


def _kill_switch_key(scope: str, account: Optional[str] = None, symbol: Optional[str] = None) -> str:
    scope_u = str(scope or "GLOBAL").upper()
    acct = str(account or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    if scope_u == "ACCOUNT" and acct:
        return f"{KILL_SWITCH_KEY}:{acct}"
    if scope_u == "SYMBOL" and sym:
        return f"{KILL_SWITCH_KEY}:{sym}"
    return KILL_SWITCH_KEY


def _now_ms() -> int:
    return int(time.time() * 1000)


def set_kill_switch(
    redis_client,
    *,
    scope: str,
    code: str,
    details: Any,
    account: Optional[str] = None,
    symbol: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    scope_u = str(scope or "GLOBAL").upper()
    code_u = str(code or "UNKNOWN").upper()
    acct = str(account or "").strip().lower() or None

    # Enforce strict global allowlist; downgrade to ACCOUNT when possible.
    if scope_u == "GLOBAL" and code_u not in _default_global_allowlist():
        if acct:
            scope_u = "ACCOUNT"
        else:
            logger.warning(
                "KILL_SWITCH_SCOPE_DOWNGRADE_FAILED | requested=GLOBAL | code=%s | reason=no_account_for_non_global_code",
                code_u,
            )

    ttl = int(ttl_seconds or _default_ttl_seconds())
    ttl = max(30, min(3600, ttl))
    prov = _caller_provenance()

    payload = {
        "active": True,
        "ts_ms": _now_ms(),
        "scope": scope_u,
        "account": acct,
        "symbol": str(symbol or "") or None,
        "code": str(code or "UNKNOWN"),
        "reason": str(code or "UNKNOWN"),
        "details": details if details is not None else "",
        "ttl_seconds": ttl,
        **prov,
    }
    if redis_client:
        try:
            key = _kill_switch_key(payload.get("scope"), payload.get("account"), payload.get("symbol"))
            redis_client.setex(key, ttl, json.dumps(payload, separators=(",", ":")))
        except Exception as e:
            logger.warning(f"KILL_SWITCH_SET_FAILED | err={e}")
    logger.warning(
        f"KILL_SWITCH_SET | scope={payload['scope']} | account={payload.get('account')} | "
        f"symbol={payload.get('symbol')} | code={payload['code']} | ttl={ttl} | src={prov.get('source_file')}:{prov.get('source_line')}"
    )
    return payload


def clear_kill_switch(redis_client, *, scope: str = "GLOBAL", account: Optional[str] = None, symbol: Optional[str] = None) -> None:
    if redis_client:
        try:
            key = _kill_switch_key(scope, account, symbol)
            redis_client.delete(key)
        except Exception as e:
            logger.warning(f"KILL_SWITCH_CLEAR_FAILED | err={e}")
            return
    logger.info("KILL_SWITCH_CLEAR")


def get_kill_switch(
    redis_client,
    *,
    account: Optional[str] = None,
    symbol: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if not redis_client:
        return False, None

    keys_to_try = []
    acct = str(account or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    if acct:
        keys_to_try.append(_kill_switch_key("ACCOUNT", acct, None))
    if sym:
        keys_to_try.append(_kill_switch_key("SYMBOL", None, sym))
    keys_to_try.append(KILL_SWITCH_KEY)

    for key in keys_to_try:
        try:
            raw = redis_client.get(key)
        except Exception:
            raw = None
        if not raw:
            continue
        try:
            raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(data, dict):
                return True, {"active": True, "code": "KILL_SWITCH_CORRUPT", "scope": "GLOBAL", "key": key}
            data.setdefault("key", key)
            return bool(data.get("active")), data
        except Exception:
            return True, {"active": True, "code": "KILL_SWITCH_CORRUPT", "scope": "GLOBAL", "key": key}

    return False, None


def kill_switch_blocks(
    data: Optional[Dict[str, Any]],
    *,
    account: Optional[str] = None,
    symbol: Optional[str] = None,
) -> bool:
    if not data or not bool(data.get("active")):
        return False
    scope = str(data.get("scope") or "GLOBAL").upper()
    if scope == "GLOBAL":
        return True
    if scope == "ACCOUNT":
        if not account:
            return True
        return str(account).lower() == str(data.get("account") or "").lower()
    if scope == "SYMBOL":
        if not symbol:
            return True
        return str(symbol).upper() == str(data.get("symbol") or "").upper()
    return True
