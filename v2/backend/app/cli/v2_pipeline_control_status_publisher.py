"""Publish the V2 pipeline control status contract for the static website.

This reads V2 Redis and existing public V2 chart payloads, then writes JSON
under ``v2/frontend/public``. It never queues trainer/replay/backtest work,
never writes Redis, and never calls an exchange.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.pipeline_control.service import build_pipeline_status


WORKER_ID = "v2_pipeline_control_status_publisher"
DEFAULT_OUTPUT_DIR = Path("v2/frontend/public/operator_runtime/v2_pipeline_control/latest")


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


def _csv(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    out = [part.strip() for part in raw.split(",") if part.strip()]
    return out or None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def publish(*, output_dir: Path, symbols: list[str] | None, timeframes: list[str] | None) -> dict[str, Any]:
    redis_client = _connect_redis()
    payload = build_pipeline_status(redis_client, symbols=symbols, timeframes=timeframes)
    payload.update(
        {
            "worker_id": WORKER_ID,
            "generated_est": _est_iso(),
            "source_type": "STATIC_V2_EVIDENCE_FROM_REDIS_AND_CHART_PAYLOADS",
            "endpoint": "/operator_runtime/v2_pipeline_control/latest/pipeline_control_status.json",
            "api_endpoint": "/api/v2/pipeline/status",
            "api_required_for_queue_actions": True,
            "static_payload_can_queue_jobs": False,
            "redis_read_ok": redis_client is not None,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
            "safety": {
                "writes_redis": False,
                "writes_old_redis": False,
                "writes_exchange_orders": False,
                "calls_test_order_endpoint": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
                "approves_live": False,
                "approves_canary": False,
                "redis_trim_performed": False,
            },
        }
    )
    _write_json(output_dir / "pipeline_control_status.json", payload)
    _write_json(output_dir / "operator_dashboard_payload.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--timeframes", default=None)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    symbols = _csv(args.symbols)
    timeframes = _csv(args.timeframes)
    if args.loop:
        while True:
            payload = publish(output_dir=output_dir, symbols=symbols, timeframes=timeframes)
            print(
                json.dumps(
                    {
                        "status": "V2_PIPELINE_CONTROL_STATUS_READY",
                        "generated_est": payload.get("generated_est"),
                        "row_count": (payload.get("compatibility") or {}).get("row_count"),
                        "chart_visible_symbol_count": (payload.get("compatibility") or {}).get("chart_visible_symbol_count"),
                        "live_gate": payload.get("live_gate"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            time.sleep(max(1.0, float(args.interval_seconds)))

    payload = publish(output_dir=output_dir, symbols=symbols, timeframes=timeframes)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
