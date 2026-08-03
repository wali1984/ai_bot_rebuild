"""Publish compact enterprise UI snapshots to V2 Redis keys.

This worker writes only ``v2:ui:snapshot:*`` materialized read models. It does
not trim Redis, call exchanges, place orders, or mutate live trading state.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from app.api.v2._common import get_redis
from app.services.realtime.resource_registry import RESOURCE_CONTRACTS
from app.services.ui_snapshot import build_all_ui_snapshots


def _cadence(resource: str) -> int:
    for contract in RESOURCE_CONTRACTS:
        if contract.name == resource:
            return contract.cadence_seconds
    return 10


def publish_once(client: Any) -> dict[str, Any]:
    snapshots = build_all_ui_snapshots(client)
    published: list[str] = []
    errors: dict[str, str] = {}
    for resource, payload in snapshots.items():
        key = f"v2:ui:snapshot:{resource}"
        try:
            client.set(key, json.dumps(payload, sort_keys=True, separators=(",", ":")))
            published.append(key)
        except Exception as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"
    return {
        "schema_version": "v2_ui_snapshot_publisher_status_v1",
        "status": "OK" if not errors else "PARTIAL",
        "published_keys": published,
        "errors": errors,
        "routes_to_live": False,
        "places_real_order": False,
    }


def run_loop(client: Any) -> None:
    last_publish: dict[str, float] = {}
    while True:
        now = time.monotonic()
        snapshots = build_all_ui_snapshots(client)
        for resource, payload in snapshots.items():
            cadence = _cadence(resource)
            if now - last_publish.get(resource, 0.0) < cadence:
                continue
            key = f"v2:ui:snapshot:{resource}"
            client.set(key, json.dumps(payload, sort_keys=True, separators=(",", ":")))
            last_publish[resource] = now
        time.sleep(float(os.environ.get("V2_UI_SNAPSHOT_PUBLISHER_SLEEP_SECONDS", "1")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="publish one snapshot cycle and exit")
    args = parser.parse_args()
    client = get_redis()
    if client is None:
        print(json.dumps({
            "schema_version": "v2_ui_snapshot_publisher_status_v1",
            "status": "REDIS_UNAVAILABLE",
            "published_keys": [],
            "errors": {"redis": "unavailable"},
            "routes_to_live": False,
            "places_real_order": False,
        }, sort_keys=True))
        return 1
    if args.once:
        print(json.dumps(publish_once(client), sort_keys=True))
        return 0
    run_loop(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
