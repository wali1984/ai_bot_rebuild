from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.legacy_v2_observatory_common import (
    first_json,
    load_json,
    repo_root,
    write_json,
    write_text,
)
from v2.backend.app.services.paper_shadow_outcome_observer import (
    build_paper_shadow_outcome_observer_status,
)


WORKER_ID = "paper_shadow_outcome_observer"
REPO_ROOT = repo_root()
V2_PUBLIC = REPO_ROOT / "v2" / "frontend" / "public"
V2_RUNTIME = REPO_ROOT / "v2" / "runtime"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / WORKER_ID / "latest"
PUBLIC_RUNTIME_DIR = V2_PUBLIC / "operator_runtime" / WORKER_ID / "latest"
PUBLIC_DASHBOARD_DIR = V2_PUBLIC / WORKER_ID / "latest"
LOCAL_RUNTIME_DIR = V2_RUNTIME / WORKER_ID / "latest"

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
FINAL_STATUS_FILE = FINAL_DIR / f"{WORKER_ID}_status.json"
FINAL_DASHBOARD_FILE = FINAL_DIR / "operator_dashboard_payload.json"
PUBLIC_DASHBOARD_FILE = PUBLIC_DASHBOARD_DIR / "operator_dashboard_payload.json"
GO_NO_GO_FILE = FINAL_DIR / "GO_NO_GO.md"
REPORT_FILE = FINAL_DIR / "PAPER_SHADOW_OUTCOME_OBSERVER_REPORT.md"

PAPER_WORKER_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_paper_execution_worker" / "latest" / "v2_paper_execution_worker_status.json",
    V2_RUNTIME / "v2_paper_execution_worker" / "latest" / "v2_paper_execution_worker_status.json",
]
PAPER_STATUS_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json",
    V2_RUNTIME / "paper_online" / "latest" / "paper_runtime_status.json",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observe blocked V2 paper intents without creating fills.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--worker-status-file", type=Path)
    parser.add_argument("--paper-status-file", type=Path)
    parser.add_argument("--requests-file", type=Path)
    parser.add_argument("--price-samples-file", type=Path)
    return parser.parse_args(argv)


def _load_dict(path: Path | None, candidates: list[Path]) -> dict[str, Any]:
    if path is not None:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}
    payload, _ = first_json(candidates)
    return payload if isinstance(payload, dict) else {}


def _load_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = load_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("requests") or payload.get("price_samples") or payload.get("observations")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [payload]
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _go_no_go(status: dict[str, Any]) -> str:
    outcome = str(status.get("outcome_status") or "")
    if outcome == "EDGE_PENDING_INSUFFICIENT_SAMPLE":
        return "PAPER_SHADOW_OUTCOME_OBSERVER_READY_EDGE_PENDING_INSUFFICIENT_SAMPLE"
    if outcome == "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED":
        return "PAPER_SHADOW_OUTCOME_OBSERVER_READY_MODEL_REVIEW_REQUIRED"
    if outcome == "NO_TRADE_DECISIONS_CORRECT_SO_FAR":
        return "PAPER_SHADOW_OUTCOME_OBSERVER_READY_NO_TRADE_CORRECT_SO_FAR"
    return "PAPER_SHADOW_OUTCOME_OBSERVER_BLOCKED"


def _dashboard(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": WORKER_ID,
        "generated_at": status.get("generated_at"),
        "go_no_go": _go_no_go(status),
        "outcome_status": status.get("outcome_status"),
        "edge_status": status.get("edge_status"),
        "observations_total": status.get("observations_total"),
        "completed_observations": status.get("completed_observations"),
        "pending_observations": status.get("pending_observations"),
        "false_block_count": status.get("false_block_count"),
        "no_trade_correct_count": status.get("no_trade_correct_count"),
        "minimum_sample_status": status.get("minimum_sample_status"),
        "latest_observation": status.get("latest_observation"),
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "old_redis_write_performed": False,
        "exchange_action_taken": False,
    }


def _report(status: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Paper Shadow Outcome Observer Report",
            "",
            f"Generated: `{status.get('generated_at')}`",
            f"GO/NO-GO: `{_go_no_go(status)}`",
            f"Outcome status: `{status.get('outcome_status')}`",
            "",
            "This observer evaluates blocked V2 paper intents against future price paths.",
            "It never creates fills, charges fees, writes old Redis, calls exchanges, or changes live state.",
            "",
            "## Counts",
            "",
            f"- observations_total: `{status.get('observations_total')}`",
            f"- completed_observations: `{status.get('completed_observations')}`",
            f"- pending_observations: `{status.get('pending_observations')}`",
            f"- no_trade_correct_count: `{status.get('no_trade_correct_count')}`",
            f"- false_block_count: `{status.get('false_block_count')}`",
            f"- minimum_sample_status: `{status.get('minimum_sample_status')}`",
            "",
            "## Decision",
            "",
            "Positive paper edge remains unproven until qualified post-filter fills or enough completed shadow observations show after-cost correctness. Live remains blocked.",
        ]
    )


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or parse_args(["--once"])
    status = build_paper_shadow_outcome_observer_status(
        worker_status=_load_dict(args.worker_status_file, PAPER_WORKER_CANDIDATES),
        paper_status=_load_dict(args.paper_status_file, PAPER_STATUS_CANDIDATES),
        requests=_load_rows(args.requests_file),
        price_samples=_load_rows(args.price_samples_file),
    )
    if args.write:
        dashboard = _dashboard(status)
        for path in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, FINAL_STATUS_FILE):
            write_json(path, status)
        for path in (FINAL_DASHBOARD_FILE, PUBLIC_DASHBOARD_FILE):
            write_json(path, dashboard)
        write_text(GO_NO_GO_FILE, _go_no_go(status) + "\n")
        write_text(REPORT_FILE, _report(status) + "\n")
    return status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_once(args)
    json.dump(status, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
