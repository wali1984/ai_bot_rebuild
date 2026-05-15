from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.legacy_v2_observatory_common import first_json, load_json, repo_root, write_json
from v2.backend.app.services.signal_outcome_observer import build_legacy_signal_outcome_observer_status


WORKER_ID = "legacy_signal_outcome_observer"
REPO_ROOT = repo_root()
V2_PUBLIC = REPO_ROOT / "v2" / "frontend" / "public"
OBS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_v2_realtime_decision_observatory"
    / "latest"
)
PUBLIC_RUNTIME_DIR = V2_PUBLIC / "operator_runtime" / WORKER_ID / "latest"
PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKLOG_STATUS_FILE = OBS_DIR / f"{WORKER_ID}_status.json"
COMPARATOR_CANDIDATES = [
    OBS_DIR / "legacy_v2_decision_comparator_status.json",
    V2_PUBLIC / "operator_runtime" / "legacy_v2_decision_comparator" / "latest" / "legacy_v2_decision_comparator_status.json",
]
PAPER_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--comparator-status-file", type=Path)
    parser.add_argument("--paper-status-file", type=Path)
    return parser.parse_args(argv)


def _load(path: Path | None, candidates: list[Path]) -> dict[str, Any]:
    if path is not None:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}
    payload, _ = first_json(candidates)
    return payload if isinstance(payload, dict) else {}


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or parse_args(["--once"])
    status = build_legacy_signal_outcome_observer_status(
        comparator_status=_load(args.comparator_status_file, COMPARATOR_CANDIDATES),
        paper_status=_load(args.paper_status_file, PAPER_STATUS_CANDIDATES),
    )
    if args.write:
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
