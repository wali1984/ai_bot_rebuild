"""V2 checkpoint promotion status CLI.

Paper-only. Read-only scan of the approved ``.local_models/`` directory.
Never loads weights, never imports torch, never touches legacy.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.rl_core.checkpoint_promotion import (
    OPERATOR_INSTRUCTION,
    STATE_OPERATOR_REQUIRED,
    STATE_READY,
    STATE_SHAPE_MISMATCH,
    scan_local_models,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_checkpoint_promotion/latest/checkpoint_promotion_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_checkpoint_promotion/latest/operator_dashboard_payload.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _go_no_go_for(overall_state: str) -> str:
    if overall_state == STATE_READY:
        return "V2_CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW"
    if overall_state == STATE_OPERATOR_REQUIRED:
        return "V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED"
    return "V2_CHECKPOINT_PROMOTION_BLOCKED"


def run_once(root: Path | None = None) -> dict:
    base = scan_local_models(root)
    base["generated_utc"] = _utc_iso()
    base["go_no_go"] = _go_no_go_for(base["overall_state"])
    if base["overall_state"] == STATE_OPERATOR_REQUIRED:
        base["operator_instruction"] = OPERATOR_INSTRUCTION
    return base


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_checkpoint_promotion_status")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--out-worklog",
        type=Path,
        default=WORKLOG_STATUS,
        help="Worklog status path (default points at v2_checkpoint_promotion/latest).",
    )
    parser.add_argument(
        "--out-public",
        type=Path,
        default=PUBLIC_DASHBOARD,
        help="Public operator dashboard path (default points at the v2_checkpoint_promotion frontend payload).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override approved root (testing only).",
    )
    args = parser.parse_args(argv)
    payload = run_once(args.root)
    _write_json(args.out_worklog, payload)
    _write_json(args.out_public, payload)
    print(json.dumps({
        "go_no_go": payload["go_no_go"],
        "overall_state": payload["overall_state"],
        "candidate_count": payload["candidate_count"],
        "approved_root_status": payload["approved_root_status"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
