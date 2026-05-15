from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.legacy_runtime_observer import build_legacy_runtime_observer_status
from v2.backend.app.services.legacy_v2_observatory_common import repo_root, write_json


WORKER_ID = "legacy_runtime_readonly_observer"
REPO_ROOT = repo_root()
PUBLIC_RUNTIME_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
)
WORKLOG_RUNTIME_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_v2_realtime_decision_observatory"
    / "latest"
)
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKLOG_STATUS_FILE = WORKLOG_RUNTIME_DIR / f"{WORKER_ID}_status.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one read-only observation")
    parser.add_argument("--write", action="store_true", help="Write public/worklog status JSON")
    return parser.parse_args(argv)


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    status = build_legacy_runtime_observer_status()
    if args is not None and args.write:
        write_json(PUBLIC_STATUS_FILE, status)
        write_json(WORKLOG_STATUS_FILE, status)
    return status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_once(args)
    json.dump(status, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
