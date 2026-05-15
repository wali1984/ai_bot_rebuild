from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.decision_quality import build_decision_quality_scoreboard_status
from v2.backend.app.services.legacy_v2_observatory_common import first_json, load_json, repo_root, write_json


WORKER_ID = "decision_quality_scoreboard"
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
OUTCOME_CANDIDATES = [
    OBS_DIR / "legacy_signal_outcome_observer_status.json",
    V2_PUBLIC / "operator_runtime" / "legacy_signal_outcome_observer" / "latest" / "legacy_signal_outcome_observer_status.json",
]
PAPER_LOSS_CANDIDATES = [
    REPO_ROOT / "claude_worklog" / "final_readiness" / "paper_loss_attribution" / "latest" / "paper_loss_attribution_status.json",
]
PAPER_EXEC_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_paper_execution_worker" / "latest" / "v2_paper_execution_worker_status.json",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--comparator-status-file", type=Path)
    parser.add_argument("--outcome-status-file", type=Path)
    parser.add_argument("--paper-loss-status-file", type=Path)
    parser.add_argument("--paper-exec-status-file", type=Path)
    return parser.parse_args(argv)


def _load(path: Path | None, candidates: list[Path]) -> dict[str, Any]:
    if path is not None:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}
    payload, _ = first_json(candidates)
    return payload if isinstance(payload, dict) else {}


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or parse_args(["--once"])
    status = build_decision_quality_scoreboard_status(
        comparator_status=_load(args.comparator_status_file, COMPARATOR_CANDIDATES),
        outcome_status=_load(args.outcome_status_file, OUTCOME_CANDIDATES),
        paper_loss_status=_load(args.paper_loss_status_file, PAPER_LOSS_CANDIDATES),
        paper_exec_status=_load(args.paper_exec_status_file, PAPER_EXEC_CANDIDATES),
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
