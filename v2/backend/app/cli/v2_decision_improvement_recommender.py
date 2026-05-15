from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.decision_improvement import build_decision_improvement_recommendations
from v2.backend.app.services.legacy_v2_observatory_common import first_json, load_json, repo_root, write_json


WORKER_ID = "v2_decision_improvement_recommender"
REPO_ROOT = repo_root()
V2_PUBLIC = REPO_ROOT / "v2" / "frontend" / "public"
OBS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_v2_realtime_decision_observatory"
    / "latest"
)
RECOMMENDATIONS_FILE = OBS_DIR / "next_decision_improvement_tasks.json"
RECOMMENDATIONS_MD = OBS_DIR / "NEXT_DECISION_IMPROVEMENT_TASKS.md"
SCOREBOARD_CANDIDATES = [
    OBS_DIR / "decision_quality_scoreboard_status.json",
    V2_PUBLIC / "operator_runtime" / "decision_quality_scoreboard" / "latest" / "decision_quality_scoreboard_status.json",
]
PAPER_LOSS_CANDIDATES = [
    REPO_ROOT / "claude_worklog" / "final_readiness" / "paper_loss_attribution" / "latest" / "paper_loss_attribution_status.json",
]
TRAINER_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_trainer_bridge" / "latest" / "v2_trainer_bridge_status.json",
]
PAPER_EDGE_CANDIDATES = [
    REPO_ROOT / "claude_worklog" / "final_readiness" / "paper_edge_recovery" / "latest" / "paper_edge_recovery_status.json",
]
SHADOW_OUTCOME_CANDIDATES = [
    V2_PUBLIC
    / "operator_runtime"
    / "paper_shadow_outcome_observer"
    / "latest"
    / "paper_shadow_outcome_observer_status.json",
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "paper_shadow_outcome_observer"
    / "latest"
    / "paper_shadow_outcome_observer_status.json",
]
SHADOW_LEARNING_CANDIDATES = [
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "paper_shadow_outcome_learning"
    / "latest"
    / "shadow_outcome_learning_status.json",
    V2_PUBLIC
    / "paper_shadow_outcome_learning"
    / "latest"
    / "operator_dashboard_payload.json",
]
EXPECTED_MOVE_MODEL_REVIEW_CANDIDATES = [
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "expected_move_model_review"
    / "latest"
    / "recommended_paper_gate_changes.json",
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "expected_move_model_review"
    / "latest"
    / "false_block_audit.json",
    V2_PUBLIC
    / "expected_move_model_review"
    / "latest"
    / "operator_dashboard_payload.json",
]
PROTECTIVE_BEHAVIOR_CANDIDATES = [
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "paper_edge_recovery"
    / "latest"
    / "protective_behavior_mapping_status.json",
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "paper_edge_recovery"
    / "latest"
    / "legacy_protective_behavior_to_v2_paper_map.json",
    V2_PUBLIC / "paper_edge_recovery" / "latest" / "operator_dashboard_payload.json",
]
SYMBOL_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
]
RISK_CANDIDATES = [
    V2_PUBLIC / "operator_runtime" / "v2_risk_gateway_runtime_worker" / "latest" / "v2_risk_gateway_runtime_worker_status.json",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args(argv)


def _load(candidates: list[Path]) -> dict[str, Any]:
    payload, _ = first_json(candidates)
    return payload if isinstance(payload, dict) else {}


def _markdown(status: dict[str, Any]) -> str:
    lines = [
        "# Next Decision Improvement Tasks",
        "",
        f"Generated: `{status['generated_at']}`",
        "",
        "This file does not approve live trading or legacy shutdown.",
        "",
    ]
    for task in status["next_tasks"]:
        lines.extend(
            [
                f"## {task['task_id']}",
                "",
                f"- priority: `{task['priority']}`",
                f"- reason: {task['reason']}",
                f"- required result: {task['required_result']}",
                "",
            ]
        )
    return "\n".join(lines)


def run_once(args: argparse.Namespace | None = None) -> dict[str, Any]:
    args = args or parse_args(["--once"])
    status = build_decision_improvement_recommendations(
        scoreboard_status=_load(SCOREBOARD_CANDIDATES),
        paper_loss_status=_load(PAPER_LOSS_CANDIDATES),
        trainer_status=_load(TRAINER_CANDIDATES),
        paper_edge_status=_load(PAPER_EDGE_CANDIDATES),
        shadow_outcome_status=_load(SHADOW_OUTCOME_CANDIDATES),
        shadow_learning_status=_load(SHADOW_LEARNING_CANDIDATES),
        expected_move_model_review_status=_load(EXPECTED_MOVE_MODEL_REVIEW_CANDIDATES),
        protective_behavior_status=_load(PROTECTIVE_BEHAVIOR_CANDIDATES),
        symbol_status=_load(SYMBOL_CANDIDATES),
        risk_status=_load(RISK_CANDIDATES),
    )
    if args.write:
        write_json(RECOMMENDATIONS_FILE, status)
        RECOMMENDATIONS_MD.parent.mkdir(parents=True, exist_ok=True)
        RECOMMENDATIONS_MD.write_text(_markdown(status))
    return status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_once(args)
    json.dump(status, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
