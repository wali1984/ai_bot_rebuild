from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from utils.ensemble_diagnostics import publish_ensemble_diagnostic


def _ensure_decision_id(payload: Dict[str, Any], fallback_stream: str = "") -> str:
    decision_id = payload.get("decision_id")
    if decision_id:
        return str(decision_id)

    ts_ms = int(payload.get("ts_ms") or payload.get("created_ts_ms") or (time.time() * 1000))
    symbol = str(payload.get("symbol") or "UNKNOWN").upper()
    tf = str(payload.get("timeframe") or payload.get("tf") or "na").lower()
    acct = str(payload.get("account_id") or payload.get("account") or "primary").lower()
    if acct == "primary" and isinstance(fallback_stream, str):
        if fallback_stream.endswith(":asjad"):
            acct = "asjad"
        elif fallback_stream.endswith(":primary"):
            acct = "primary"
    decision_id = f"{ts_ms}-{symbol}-{tf}-{acct}"
    payload["decision_id"] = decision_id
    return decision_id


def publish_overlay_intent(
    redis_client,
    payload: Dict[str, Any],
    *,
    stream: str = "signals:overlay:intents",
    maxlen: int = 5000,
    approximate: bool = True,
) -> Optional[str]:
    if redis_client is None:
        return None

    msg = dict(payload or {})
    if "ts_ms" not in msg:
        msg["ts_ms"] = int(time.time() * 1000)
    decision_id = _ensure_decision_id(msg, fallback_stream=stream)

    msg_id = redis_client.xadd(stream, msg, maxlen=maxlen, approximate=approximate)

    publish_ensemble_diagnostic(
        {
            "kind": "publish_overlay",
            "stream": stream,
            "decision_id": decision_id,
            "symbol": msg.get("symbol"),
            "tf": msg.get("timeframe") or msg.get("tf") or "overlay",
            "action": msg.get("action") or msg.get("action_name") or msg.get("decision") or "OVERLAY",
            "confidence": msg.get("confidence") or 0.0,
            "stream_id": str(msg_id),
        }
    )
    return str(msg_id)


def publish_trading_signal(
    redis_client,
    stream: str,
    payload: Dict[str, Any],
    *,
    maxlen: int = 5000,
    approximate: bool = True,
) -> Optional[str]:
    """
    Publish trading signal preserving existing stream schema.

    If payload contains key `data` (JSON string), it remains wrapped as-is,
    except decision_id is injected inside JSON when parseable.
    """
    if redis_client is None:
        return None

    out: Dict[str, Any] = dict(payload or {})
    diag_payload: Dict[str, Any] = {}

    if "data" in out and isinstance(out.get("data"), str):
        raw = out.get("data")
        obj = None
        try:
            obj = json.loads(raw)
        except Exception:
            obj = None

        if isinstance(obj, dict):
            decision_id = _ensure_decision_id(obj, fallback_stream=stream)
            out["data"] = json.dumps(obj, separators=(",", ":"), default=str)
            diag_payload = obj
            _sym = str(obj.get("symbol") or "")
            _tf = str(obj.get("timeframe") or obj.get("tf") or "")
            if _sym:
                out["symbol"] = _sym
            if _tf:
                out["timeframe"] = _tf
        else:
            decision_id = f"{int(time.time()*1000)}-UNKNOWN-na-primary"
            diag_payload = {}
    else:
        decision_id = _ensure_decision_id(out, fallback_stream=stream)
        diag_payload = out

    # Always emit a top-level decision_id for wrappers/consumers that do not parse `data` JSON.
    # This is additive/backward-compatible and strengthens end-to-end proof joins.
    out["decision_id"] = str(decision_id)

    msg_id = redis_client.xadd(stream, out, maxlen=maxlen, approximate=approximate)

    publish_ensemble_diagnostic(
        {
            "kind": "publish_trading",
            "stream": stream,
            "decision_id": decision_id,
            "symbol": diag_payload.get("symbol"),
            "tf": diag_payload.get("timeframe") or diag_payload.get("tf"),
            "action": diag_payload.get("action") or diag_payload.get("action_name"),
            "confidence": diag_payload.get("confidence") or diag_payload.get("model_confidence") or 0.0,
            "stream_id": str(msg_id),
        }
    )
    return str(msg_id)
