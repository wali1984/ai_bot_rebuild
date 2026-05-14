from __future__ import annotations

from typing import Any, Dict, Tuple
import time

REQUIRED_FIELDS = (
    "account_id",
    "symbol",
    "timeframe",
    "action",
    "created_ts_ms",
)

VALID_ACTIONS = {
    "OPEN_LONG",
    "OPEN_SHORT",
    "CLOSE_LONG",
    "CLOSE_SHORT",
    "PARTIAL_CLOSE",
    "PARTIAL_CLOSE_LONG",
    "PARTIAL_CLOSE_SHORT",
    "OPEN_HEDGE_LONG",
    "OPEN_HEDGE_SHORT",
    "ADD_HEDGE_LONG",
    "ADD_HEDGE_SHORT",
    "HEDGE_ADD",
    "HEDGE_REDUCE",
    "SET_TAKE_PROFIT",
    "SET_STOP_LOSS",
    "UPDATE_TP",
    "UPDATE_SL",
    "ARM_TP",
    "ARM_SL",
    "SET_TRAILING",
    "CANARY",
    "NOOP",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_signal(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    p.setdefault("created_ts_ms", _now_ms())
    if "action" in p and p["action"] is not None:
        p["action"] = str(p["action"]).strip().upper()
    if "account_id" in p and p["account_id"] is not None:
        p["account_id"] = str(p["account_id"]).strip()
    if "symbol" in p and p["symbol"] is not None:
        p["symbol"] = str(p["symbol"]).strip().upper()
    if "timeframe" in p and p["timeframe"] is not None:
        p["timeframe"] = str(p["timeframe"]).strip()
    if not p.get("timeframe"):
        try:
            meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
            tf = meta.get("timeframe") or meta.get("tf") or meta.get("interval")
        except Exception:
            tf = None
        if tf:
            p["timeframe"] = str(tf).strip()

    for k in ("margin_usd", "notional_usd", "leverage"):
        if k in p and p[k] is not None:
            try:
                p[k] = float(p[k])
            except Exception:
                pass
    return p


def validate_signal(payload: Dict[str, Any]) -> Tuple[bool, str]:
    p = payload or {}
    for f in REQUIRED_FIELDS:
        if f not in p or p[f] is None or str(p[f]).strip() == "":
            return False, f"SCHEMA_MISSING:{f}"
    action = str(p.get("action", "")).strip().upper()
    if action not in VALID_ACTIONS:
        return False, f"SCHEMA_BAD_ACTION:{action}"
    try:
        int(p.get("created_ts_ms"))
    except Exception:
        return False, "SCHEMA_BAD_CREATED_TS"
    return True, "OK"
