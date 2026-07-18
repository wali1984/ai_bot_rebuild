#!/usr/bin/env python3
"""Publish Phase 8 synthetic, non-runtime trade-gate contract tests."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.a_plus_phase8_trade_gate import (  # noqa: E402
    CONTRACT_TEST_PASSED,
    GOAL_ID,
    write_phase8_a_plus_gate_artifacts,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--goal-dir", default=None)
    parser.add_argument(
        "--public-dir",
        default="v2/frontend/public/operator_runtime/a_plus_phase8_trade_gate/latest",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    goal_dir = Path(args.goal_dir) if args.goal_dir else repo_root / "goal_state" / GOAL_ID
    if not goal_dir.is_absolute():
        goal_dir = repo_root / goal_dir
    public_dir = Path(args.public_dir) if args.public_dir else None
    if public_dir is not None and not public_dir.is_absolute():
        public_dir = repo_root / public_dir
    status = write_phase8_a_plus_gate_artifacts(goal_dir=goal_dir, public_dir=public_dir)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": status["status"],
                    "contract_test_conditions": status["contract_test_conditions"],
                    "canonical_runtime_ready": status["canonical_runtime_ready"],
                },
                sort_keys=True,
            )
        )
    return 0 if status["status"] == CONTRACT_TEST_PASSED else 2


if __name__ == "__main__":
    raise SystemExit(main())
