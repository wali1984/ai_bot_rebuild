"""V2 Arkham presence-only worker (no external HTTP, no value leakage).

Arkham is reachable by API in production via ``ARKHAM_API_KEY``. The full
Arkham client adapter is **not** implemented yet for V2; this worker
only proves the credential is present **by name**, emits a public status
payload, and registers a future-placeholder slot in the parity matrix so
the operator can see exactly what is and is not active.

This worker:
  * does NOT make any external network request
  * does NOT read or print any raw credential value
  * writes only ``v2:alt_data:arkham:presence`` to Redis (one key, TTL'd)
  * writes a public payload under
    ``v2/frontend/public/v2_arkham_presence_only/latest/``
  * keeps ``LIVE_GATE = blocked_human_only``

When Arkham's client adapter is implemented in a future lane, this worker
should be replaced (not extended) by a real read-only ingestor that goes
through ``v2.backend.app.services.safe_env_loader`` and emits redacted
status only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
sys.path.insert(0, str(REPO))

from v2.backend.app.services.safe_env_loader import load_credentials  # noqa: E402


EST = ZoneInfo("America/New_York")
LIVE_GATE = "blocked_human_only"
PUBLIC_OUT = REPO / "v2/frontend/public/v2_arkham_presence_only/latest"
OPERATOR_RUNTIME_OUT = REPO / "v2/frontend/public/operator_runtime/arkham_presence_only/latest"
ARKHAM_KEY_NAME = "ARKHAM_API_KEY"


def _est_iso() -> str:
    return datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _redis_client():
    try:
        import redis  # type: ignore
    except ImportError:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def build_status() -> Dict[str, Any]:
    report = load_credentials()
    key_sentinel = report["keys"].get(ARKHAM_KEY_NAME, "KEY_ABSENT_BY_NAME")
    return {
        "ts_est": _est_iso(),
        "generated_at_est": _est_iso(),
        "worker": "v2_arkham_presence_only_worker",
        "provider": "arkham",
        "credential_env_name": ARKHAM_KEY_NAME,
        "credential_status_by_name": key_sentinel,
        "raw_credential_value_read": False,
        "raw_credential_value_exposed": False,
        "http_request_made": False,
        "exchange_endpoints_called": [],
        "client_status": (
            "FUTURE_PLACEHOLDER_AWAITING_CLIENT_ADAPTER"
            if key_sentinel == "KEY_PRESENT_BY_NAME"
            else "BLOCKED_CREDENTIAL_ABSENT_BY_NAME"
        ),
        "running_status": "PRESENCE_ONLY_PUBLISHED",
        "redis_keys_written": ["v2:alt_data:arkham:presence"],
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "writes_exchange_orders": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "notes": (
            "Presence-only worker: confirms ARKHAM_API_KEY is present by name "
            "and publishes a public status payload. No external HTTP request is "
            "made and no raw value is read. Replace with a real client adapter "
            "in a future lane."
        ),
    }


def write_redis(r, status: Dict[str, Any], *, ttl_s: int) -> int:
    if r is None:
        return 0
    try:
        r.set(
            "v2:alt_data:arkham:presence",
            json.dumps(status, separators=(",", ":"), sort_keys=True),
            ex=ttl_s,
        )
        return 1
    except Exception:
        return 0


def _write_json(target: Path, status: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as fh:
        json.dump(status, fh, indent=2, sort_keys=True)
        fh.write("\n")


def write_public_payload(status: Dict[str, Any]) -> Path:
    public_target = PUBLIC_OUT / "operator_dashboard_payload.json"
    runtime_target = OPERATOR_RUNTIME_OUT / "arkham_presence_only_status.json"
    _write_json(public_target, status)
    _write_json(runtime_target, status)
    return public_target


def run_once(ttl_s: int) -> Dict[str, Any]:
    r = _redis_client()
    status = build_status()
    status["redis_available"] = r is not None
    status["redis_keys_written_count"] = write_redis(r, status, ttl_s=ttl_s)
    write_public_payload(status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=60)
    p.add_argument("--ttl-seconds", type=int, default=300)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if not (args.once or args.loop):
        args.once = True
    if args.loop:
        while True:
            status = run_once(args.ttl_seconds)
            if args.json:
                print(json.dumps(status))
            try:
                time.sleep(max(15, args.interval_seconds))
            except KeyboardInterrupt:
                return 0
    else:
        status = run_once(args.ttl_seconds)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            print("WROTE", PUBLIC_OUT / "operator_dashboard_payload.json")
            print(f"status: client_status={status['client_status']} "
                  f"redis_keys_written={status['redis_keys_written_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
