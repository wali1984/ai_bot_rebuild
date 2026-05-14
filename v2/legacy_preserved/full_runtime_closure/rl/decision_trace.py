"""
Decision Trace (DAG-ish) Telemetry
=================================

Addendum v3 requirement:
- Emit trace-grade telemetry (not just metrics) so the "trainer brain" can be audited.

We emit compact JSON blobs to a Redis Stream (default: `wma:traces`).
This is intentionally independent from orchestrator proofs and decision funnel logs.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional


def new_trace_id() -> str:
    return str(uuid.uuid4())


def emit_trace(
    redis_client: Any,
    *,
    stream: str = "wma:traces",
    trace: Dict[str, Any],
    maxlen: int = 20000,
) -> bool:
    if redis_client is None:
        return False
    if not isinstance(trace, dict):
        return False
    try:
        obj = dict(trace)
        obj.setdefault("ts_ms", int(time.time() * 1000))
        obj.setdefault("event", "DECISION_TRACE")
        data = json.dumps(obj, separators=(",", ":"), default=str)
        # best-effort bounded stream
        try:
            redis_client.xadd(str(stream), {"data": data}, maxlen=int(maxlen), approximate=True)
        except TypeError:
            # some redis clients don't support named args
            redis_client.xadd(str(stream), {"data": data})
        return True
    except Exception:
        return False


def build_trace(
    *,
    trace_id: Optional[str],
    account_id: str,
    symbol: str,
    phase: str,
    module: str,
    payload: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    t = {
        "trace_id": trace_id or new_trace_id(),
        "account_id": str(account_id or ""),
        "symbol": str(symbol or "").upper().strip(),
        "phase": str(phase or ""),
        "module": str(module or ""),
    }
    if isinstance(payload, dict):
        t["payload"] = payload
    if extra:
        t.update(extra)
    return t

