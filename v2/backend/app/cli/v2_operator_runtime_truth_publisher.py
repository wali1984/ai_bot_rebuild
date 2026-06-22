#!/usr/bin/env python3
"""
v2_operator_runtime_truth_publisher

Publishes one canonical operator runtime truth payload to:
  v2/frontend/public/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json

Usage:
  python3 v2_operator_runtime_truth_publisher.py [--once] [--interval 60]

Safety invariants (enforced by runtime_truth.py):
  Reads V2 runtime/public payloads only.
  No exchange mutation. No legacy Redis. No order placement.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root on path
_ROOT = Path(__file__).resolve().parents[3]
_SERVICES = _ROOT / "backend" / "app" / "services" / "operator_truth"
sys.path.insert(0, str(_ROOT / "backend" / "app" / "services" / "operator_truth"))
sys.path.insert(0, str(_ROOT.parent))

# Self-contained import — load runtime_truth module directly
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("runtime_truth", str(_SERVICES / "runtime_truth.py"))
_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
build_operator_runtime_truth = _mod.build_operator_runtime_truth

_OUT_DIR = _ROOT / "frontend" / "public" / "operator_runtime" / "v2_runtime_truth" / "latest"
_OUT_FILE = _OUT_DIR / "operator_runtime_truth.json"


def run_once() -> dict:
    payload = build_operator_runtime_truth()
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.rename(_OUT_FILE)
    # Compact summary to stdout
    summary = {
        "classification": payload["classification"],
        "live_gate": payload["live_gate"],
        "fresh_payload_count": payload["fresh_payload_count"],
        "stale_payload_count": payload["stale_payload_count"],
        "ingestor_status": payload["ingestor_status"],
        "risk_classification": payload["risk_classification"],
        "paper_classification": payload["paper_classification"],
        "generated_est": payload["generated_est"],
    }
    print(json.dumps(summary))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 Operator Runtime Truth Publisher")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Publish interval in seconds (default 60)")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    print(f"[v2_operator_runtime_truth_publisher] starting loop interval={args.interval}s", flush=True)
    while True:
        try:
            run_once()
        except Exception as exc:
            print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
