"""V2 log errors status publisher — queries systemd for failed V2 services,
reads v2:legacy_log_observer:last_summary from Redis, writes a public payload.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_log_errors_status/latest/v2_log_errors_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _count_failed_v2_services() -> int:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-units", "ai-bot-v2*", "--state=failed", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=10
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip() and "ai-bot-v2" in l]
        return len(lines)
    except Exception:
        return 0


def run_once() -> dict:
    r = _connect_redis()
    failed_services = _count_failed_v2_services()

    # Read log summary from Redis
    log_summary: dict = {}
    error_count = 0
    warn_count = 0
    if r:
        try:
            raw = r.get("v2:legacy_log_observer:last_summary")
            if raw:
                log_summary = json.loads(raw)
                error_count = log_summary.get("error_count", 0) or 0
                warn_count = log_summary.get("warn_count", 0) or 0
        except Exception:
            pass

    classification = (
        "LOG_STATUS_OK" if (failed_services == 0 and error_count == 0)
        else ("LOG_STATUS_DEGRADED" if failed_services > 0 else "LOG_STATUS_WARN")
    )

    return {
        "schema_version": "v2_log_errors_status_v1",
        "worker_id": "v2_log_errors_status_publisher",
        "generated_utc": _utc_iso(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "classification": classification,
        "v2_failed_services": failed_services,
        "error_count_24h": error_count,
        "warn_count_24h": warn_count,
        "log_summary": log_summary,
    }


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_log_errors_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(json.dumps({"classification": payload["classification"], "v2_failed_services": payload["v2_failed_services"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
