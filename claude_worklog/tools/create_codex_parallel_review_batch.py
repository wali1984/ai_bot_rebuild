#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
REVIEWS = ROOT / "claude_worklog/codex_parallel_reviews"
RECENT_WINDOW_SECONDS = 5 * 60 * 60

TOPICS = [
    {
        "id": "trainer_prediction_output",
        "title": "Trainer Prediction Output MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl",
            "claude_worklog/historical_pnl_audit",
            "claude_worklog/legacy_readonly_audit",
        ],
        "checks": [
            "prediction_id and feature_snapshot_id lineage",
            "confidence/explainability payload",
            "stale/missing/unused feature flags",
            "historical PnL evidence impact",
            "no live/Redis/legacy/exchange behavior",
        ],
    },
    {
        "id": "orchestrator_decision",
        "title": "Orchestrator Decision MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/orchestrator_decision_impl",
            "claude_worklog/legacy_readonly_audit",
        ],
        "checks": [
            "decision_id lineage",
            "risk gateway handoff completeness",
            "stale/duplicate signal handling",
            "legacy orchestrator behavior mapping",
            "no direct trade execution",
        ],
    },
    {
        "id": "risk_gateway_default_deny",
        "title": "Risk Gateway Default Deny MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/risk_gateway_impl",
            "claude_worklog/phase2_core_rebuild/risk_gateway",
            "claude_worklog/legacy_failure_cases",
        ],
        "checks": [
            "default deny behavior",
            "stale data blocks",
            "hedge unwind residual exposure blocks",
            "manual/external position quarantine",
            "LAB-like failure case coverage",
        ],
    },
    {
        "id": "paper_execution_ledger",
        "title": "Paper Execution Ledger MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl",
            "claude_worklog/phase2_core_rebuild/paper_mode_impl",
        ],
        "checks": [
            "paper open/close/reduce/hedge/block ledger events",
            "PnL accounting",
            "risk decision linkage",
            "execution_intent_id linkage",
            "no real exchange actions",
        ],
    },
    {
        "id": "replay_backtest_runner",
        "title": "Replay Backtest Runner MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl",
            "claude_worklog/historical_pnl_audit",
        ],
        "checks": [
            "replay input contracts",
            "backtest output metrics",
            "PnL/drawdown calculation",
            "historical PnL comparison",
            "large winner/loser attribution",
        ],
    },
    {
        "id": "paper_mode",
        "title": "Paper Mode MVP",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/paper_mode_impl",
        ],
        "checks": [
            "paper mode flag composition",
            "no live execution",
            "paper ledger integration",
            "risk gateway enforcement",
            "decision explainability",
        ],
    },
    {
        "id": "shadow_readiness",
        "title": "Shadow Mode Readiness",
        "inputs": [
            "v2/backend/app",
            "v2/backend/tests",
            "claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl",
            "claude_worklog/legacy_readonly_audit",
        ],
        "checks": [
            "legacy-vs-V2 comparison readiness",
            "shadow decisions do not affect live",
            "same-symbol same-snapshot comparison",
            "audit output for divergence",
            "live gate remains blocked",
        ],
    },
    {
        "id": "historical_pnl_integration",
        "title": "Historical PnL / Trade Audit Integration",
        "inputs": [
            "claude_worklog/historical_pnl_audit",
            "claude_worklog/legacy_failure_cases",
            "claude_worklog/phase2_core_rebuild",
        ],
        "checks": [
            "30-day audit status",
            "PnL by symbol/day",
            "fee/funding drag",
            "LAB hedge failure integration",
            "V2 risk/backtest requirements derived from evidence",
        ],
    },
    {
        "id": "website_explainability_contracts",
        "title": "Website Explainability Contract Readiness",
        "inputs": [
            "v2/frontend",
            "v2/backend/app",
            "claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md",
        ],
        "checks": [
            "feature_snapshot_id visibility",
            "prediction_id visibility",
            "risk_decision_id visibility",
            "paper/shadow comparison visibility",
            "no fake reasoning",
        ],
    },
    {
        "id": "no_live_side_effects",
        "title": "No Live Side Effects Audit",
        "inputs": [
            "v2",
            "claude_worklog/tools",
            "claude_worklog/agent_supervisor",
        ],
        "checks": [
            "no Redis writes",
            "no live service restart",
            "no exchange order action",
            "no deployment",
            "live gate remains blocked",
        ],
    },
]


def now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def reviewed_recently(topic_id: str, window_seconds: int) -> bool:
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
    for path in REVIEWS.glob(f"*_{topic_id}_GO_NO_GO.md"):
        try:
            if path.stat().st_mtime >= cutoff:
                return True
        except FileNotFoundError:
            continue
    return False


def build_task(tag: str, idx: int, topic: dict[str, object]) -> tuple[str, dict[str, object]]:
    topic_id = str(topic["id"])
    task_id = f"codex_parallel_review_{tag}_{idx:02d}_{topic_id}"
    report = f"claude_worklog/codex_parallel_reviews/{tag}_{idx:02d}_{topic_id}_REPORT.md"
    go = f"claude_worklog/codex_parallel_reviews/{tag}_{idx:02d}_{topic_id}_GO_NO_GO.md"
    inputs = "\n".join(f"- {item}" for item in topic["inputs"])
    checks = "\n".join(f"- {item}" for item in topic["checks"])

    prompt = f"""You are local Codex CLI in /home/wali/Desktop/AI BOT REBUILD.

READ-ONLY PARALLEL REVIEW MODE.

Do not modify /home/wali/Desktop/AI BOT.
Do not write Redis.
Do not delete Redis keys.
Do not restart live services.
Do not place/cancel orders.
Do not change leverage/margin.
Do not enable live trading.
Do not deploy.
Do not expose secrets.

Review topic: {topic['title']}

Inputs to inspect:
{inputs}

Checks:
{checks}

Write exactly two BEGIN_FILE blocks:
1. {report}
2. {go}

The GO/NO-GO file must contain exactly one line:
CODEX_PARALLEL_REVIEW_READY or CODEX_PARALLEL_REVIEW_BLOCKED

If blocked, the report must include concrete blockers and proposed non-live autofix tasks.
"""

    task = {
        "task_id": task_id,
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "cwd": "/home/wali/Desktop/AI BOT REBUILD",
        "emit_files": True,
        "allowed_output_prefixes": ["claude_worklog/codex_parallel_reviews/"],
        "required_output_files": [report, go],
        "prompt": prompt,
        "lane": "codex_watchdog",
        "mvp_relevance": f"Parallel review of {topic['title']} to accelerate V2_BACKTEST_AND_PAPER_MVP_READY.",
        "blocked_by": [],
        "next_gate": "CODEX_PARALLEL_REVIEW_READY",
        "legacy_evidence_consulted": [
            "legacy_readonly_audit",
            "historical_pnl_audit",
            "phase2_core_rebuild artifacts",
        ],
        "legacy_failure_addressed": [
            "under-reviewed MVP milestone risk",
            "manual review bottleneck",
        ],
        "next_recommended_action": "If READY, continue. If BLOCKED, create non-live Codex autofix task.",
    }
    return task_id, task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Create tasks even if a topic was reviewed in the last 5 hours.")
    args = parser.parse_args()

    TASKS.mkdir(parents=True, exist_ok=True)
    REVIEWS.mkdir(parents=True, exist_ok=True)
    tag = now_tag()

    created: list[str] = []
    skipped_recent: list[str] = []
    for idx, topic in enumerate(TOPICS, start=1):
        topic_id = str(topic["id"])
        if not args.force and reviewed_recently(topic_id, RECENT_WINDOW_SECONDS):
            skipped_recent.append(topic_id)
            continue
        task_id, task = build_task(tag, idx, topic)
        path = TASKS / f"{task_id}.json"
        path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
        created.append(str(path.relative_to(ROOT)))

    print(json.dumps({"created": created, "skipped_recent": skipped_recent}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
