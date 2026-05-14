"""
Proposal Bus (Redis Streams)
============================

Single format for trader-side systems to propose actions to the Orchestrator.

Design constraints:
- Must be non-blocking / robust (publish failures must not crash traders).
- No static decision thresholds: the bus does not decide, only transports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple


def emit_proposal(redis_client: Any, *, stream: str, proposal: Dict[str, Any]) -> bool:
    if redis_client is None:
        return False
    try:
        payload = dict(proposal or {})
        payload["event"] = payload.get("event") or "TRADE_PROPOSAL"
        data = json.dumps(payload, separators=(",", ":"), default=str)
        redis_client.xadd(str(stream), {"data": data})
        return True
    except Exception:
        return False


def drain_stream(
    redis_client: Any,
    *,
    stream: str,
    last_id_key: str,
    max_read: int = 2000,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], Optional[str]]:
    """
    Drain a redis stream using XRANGE from last_id_key (inclusive).
    Returns (rows, newest_id).
    """
    if redis_client is None:
        return [], None
    try:
        last_id = redis_client.get(last_id_key) or "0-0"
        rows = redis_client.xrange(stream, min=last_id, max="+", count=int(max_read)) or []
    except Exception:
        return [], None

    out: List[Tuple[str, Dict[str, Any]]] = []
    newest_id: Optional[str] = None
    for sid, fields in rows:
        try:
            if str(sid) == str(last_id):
                continue
        except Exception:
            pass
        newest_id = str(sid)
        out.append((str(sid), fields))
    return out, newest_id


def commit_last_id(redis_client: Any, *, last_id_key: str, newest_id: Optional[str]) -> None:
    if redis_client is None or not newest_id:
        return
    try:
        redis_client.set(str(last_id_key), str(newest_id))
    except Exception:
        return

