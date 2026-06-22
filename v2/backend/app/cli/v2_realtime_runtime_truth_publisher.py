#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

from v2.backend.app.services.operator_truth.realtime_runtime_truth import publish_realtime_runtime_truth


def run_once() -> dict:
    payloads = publish_realtime_runtime_truth()
    summary = {
        "classification": payloads["operator_runtime_truth.json"].get("classification"),
        "paper_pnl": payloads["operator_runtime_truth.json"].get("paper_pnl"),
        "paper_equity": payloads["operator_runtime_truth.json"].get("paper_equity"),
        "paper_minus_49_classification": payloads["paper_pnl_source_of_truth_status.json"].get("paper_minus_49_classification"),
        "market_states_scored": payloads["market_state_integrity_service_status.json"].get("market_states_scored"),
        "generated_est": payloads["operator_runtime_truth.json"].get("generated_est"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 real-time canonical runtime truth publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    while True:
        run_once()
        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    main()
