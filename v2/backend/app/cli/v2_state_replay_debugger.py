#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v2.backend.app.services.replay_debugger import build_debugger_payload, query_snapshots

REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_replay_debugger/latest"


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def run_once() -> dict[str, Any]:
    payload = build_debugger_payload(_connect_redis())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "replay_debugger_payload.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 state replay debugger")
    parser.add_argument("--decision-id")
    parser.add_argument("--prediction-id")
    parser.add_argument("--symbol")
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    payload = run_once()
    rows = query_snapshots(
        payload,
        decision_id=args.decision_id,
        prediction_id=args.prediction_id,
        symbol=args.symbol,
        latest=args.latest,
    )
    print(json.dumps({"rows": rows, "count": len(rows), "payload_path": str(OUT_DIR / "replay_debugger_payload.json")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
