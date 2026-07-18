#!/usr/bin/env python3
"""Publish A+ Phase 7 ATR/adaptive-exit repair evidence artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.a_plus_phase7_exit_repair import (  # noqa: E402
    GOAL_ID,
    write_phase7_exit_repair_artifacts,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--goal-dir", default=None)
    parser.add_argument(
        "--public-dir",
        default="v2/frontend/public/operator_runtime/a_plus_phase7_exit_repair/latest",
    )
    parser.add_argument("--repair-deployed-utc", default=None)
    parser.add_argument("--generated-utc", default=None)
    parser.add_argument("--evidence-run-id", default=None)
    parser.add_argument(
        "--execution-receipt",
        default=None,
        help="Explicit JSON receipt from the external Phase 7 contract-test runner.",
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
    execution_receipt = None
    if args.execution_receipt:
        receipt_path = Path(args.execution_receipt)
        if not receipt_path.is_absolute():
            receipt_path = repo_root / receipt_path
        loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("phase7_execution_receipt_must_be_json_object")
        execution_receipt = loaded
    status = write_phase7_exit_repair_artifacts(
        repo_root=repo_root,
        goal_dir=goal_dir,
        public_dir=public_dir,
        repair_deployed_utc=args.repair_deployed_utc,
        generated_utc=args.generated_utc,
        evidence_run_id=args.evidence_run_id,
        execution_receipt=execution_receipt,
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({"status": status["status"], "pass_conditions": status["pass_conditions"]}, sort_keys=True))
    return 0 if status["repair_test_passed"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
