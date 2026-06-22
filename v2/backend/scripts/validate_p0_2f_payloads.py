"""Validate the P0.2F-related JSON payloads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGETS = [
    Path("v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json"),
    Path(
        "claude_worklog/final_readiness/v2_native_rl_masa_ppo_p0_2f/latest/trainer_output_status.json"
    ),
    Path(
        "v2/frontend/public/operator_runtime/v2_owned_non_live_startup/latest/v2_owned_non_live_startup_status.json"
    ),
    Path("v2/frontend/public/12h_native_core_sprint/latest/pages_truth_overlay.json"),
]


def main() -> int:
    bad = 0
    for p in TARGETS:
        try:
            json.loads(p.read_text())
            print("OK", p)
        except Exception as exc:
            print("FAIL", p, type(exc).__name__, exc)
            bad += 1
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
