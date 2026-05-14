from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any, Dict


DECISION_STREAM = "wma:decisions"


def _decision_bus_log_path() -> str:
    """Resolve project-local decision bus failure log path."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_dir = os.path.join(root_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(log_dir, "decision_bus.log")


def _log_decision_bus_failure(msg: str) -> None:
    """Best-effort append-only failure log for decision bus write errors."""
    try:
        path = _decision_bus_log_path()
        ts = int(time.time() * 1000)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _safe(obj: Any) -> Any:
    """Best-effort JSON-safety for Redis stream payloads."""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    return str(obj)


def publish_decision_record(redis_client, record: Dict[str, Any], *, stream: str = DECISION_STREAM, maxlen: int = 50000) -> str | None:
    """
    Publish a normalized decision record to the always-on decision bus.

    Contract:
    - Stream: `wma:decisions`
    - Payload field: `data` (JSON object)
    """
    if redis_client is None or not isinstance(record, dict):
        _log_decision_bus_failure("invalid_publish_args redis_client_or_record")
        return None

    out = dict(record)
    out.setdefault("ts_ms", int(time.time() * 1000))
    out.setdefault("kind", "trainer_decision")
    out = _safe(out)

    try:
        return redis_client.xadd(
            stream,
            {"data": json.dumps(out, separators=(",", ":"))},
            maxlen=int(maxlen),
            approximate=True,
        )
    except Exception as e:
        _log_decision_bus_failure(
            f"xadd_failed stream={stream} kind={out.get('kind')} stage={out.get('stage')} "
            f"decision_id={out.get('decision_id')} err={e}\n{traceback.format_exc()}"
        )
        return None
