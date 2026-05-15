#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.decision_comparator import build_legacy_v2_decision_comparator_status
from v2.backend.app.services.decision_improvement import build_decision_improvement_recommendations
from v2.backend.app.services.decision_quality import build_decision_quality_scoreboard_status
from v2.backend.app.services.legacy_runtime_observer import build_legacy_runtime_observer_status
from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    first_json,
    load_json,
    utc_now,
    write_json,
    write_text,
)
from v2.backend.app.services.signal_outcome_observer import build_legacy_signal_outcome_observer_status


OBS_ID = "legacy_v2_realtime_decision_observatory"
OBS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / OBS_ID
    / "latest"
)
PUBLIC_OBS_DIR = REPO_ROOT / "v2" / "frontend" / "public" / OBS_ID / "latest"
PUBLIC_RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime"
GO_NO_GO_FILE = OBS_DIR / "GO_NO_GO.md"
REPORT_FILE = OBS_DIR / "LEGACY_V2_REALTIME_DECISION_OBSERVATORY_REPORT.md"
WORKLOG_PAYLOAD_FILE = OBS_DIR / "operator_dashboard_payload.json"
PUBLIC_PAYLOAD_FILE = PUBLIC_OBS_DIR / "operator_dashboard_payload.json"
STATUS_FILE = OBS_DIR / "codex_legacy_v2_realtime_decision_observatory_status.json"
NEXT_TASKS_FILE = OBS_DIR / "next_decision_improvement_tasks.json"
NEXT_TASKS_MD = OBS_DIR / "NEXT_DECISION_IMPROVEMENT_TASKS.md"


def _load_first(paths: list[Path]) -> dict[str, Any]:
    payload, _ = first_json(paths)
    return payload if isinstance(payload, dict) else {}


def _payload_paths() -> dict[str, list[Path]]:
    public = REPO_ROOT / "v2" / "frontend" / "public"
    return {
        "paper": [
            public / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json",
        ],
        "trainer": [
            public / "operator_runtime" / "v2_trainer_bridge" / "latest" / "v2_trainer_bridge_status.json",
        ],
        "symbol": [
            public / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
            public / "operator_runtime" / "v2_symbol_universe" / "latest" / "symbol_universe_status.json",
        ],
        "risk": [
            public
            / "operator_runtime"
            / "v2_risk_gateway_runtime_worker"
            / "latest"
            / "v2_risk_gateway_runtime_worker_status.json",
        ],
        "paper_exec": [
            public
            / "operator_runtime"
            / "v2_paper_execution_worker"
            / "latest"
            / "v2_paper_execution_worker_status.json",
        ],
        "paper_loss": [
            REPO_ROOT
            / "claude_worklog"
            / "final_readiness"
            / "paper_loss_attribution"
            / "latest"
            / "paper_loss_attribution_status.json",
        ],
        "paper_edge": [
            REPO_ROOT
            / "claude_worklog"
            / "final_readiness"
            / "paper_edge_recovery"
            / "latest"
            / "paper_edge_recovery_status.json",
        ],
        "paper_shadow_outcome": [
            public
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
        ],
        "paper_shadow_outcome_learning": [
            REPO_ROOT
            / "claude_worklog"
            / "final_readiness"
            / "paper_shadow_outcome_learning"
            / "latest"
            / "shadow_outcome_learning_status.json",
            public
            / "paper_shadow_outcome_learning"
            / "latest"
            / "operator_dashboard_payload.json",
        ],
        "protective_behavior": [
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
            public / "paper_edge_recovery" / "latest" / "operator_dashboard_payload.json",
        ],
        "shutdown": [
            REPO_ROOT
            / "claude_worklog"
            / "final_readiness"
            / "codex_shutdown_readiness_takeover"
            / "latest"
            / "current_recommendation.json",
        ],
    }


def _write_runtime(worker_id: str, filename: str, payload: dict[str, Any]) -> None:
    write_json(PUBLIC_RUNTIME_DIR / worker_id / "latest" / filename, payload)
    write_json(OBS_DIR / filename, payload)


def _safety_findings(payloads: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        name = payload.get("worker_id") or payload.get("service_id") or "payload"
        live_gate = payload.get("live_gate") or payload.get("live_gate_status")
        if live_gate not in (None, LIVE_GATE_STATUS):
            findings.append(f"{name}: live_gate_not_blocked_human_only")
        live_symbols = payload.get("live_symbols")
        if live_symbols not in (None, []):
            findings.append(f"{name}: live_symbols_not_empty")
        for key, blocker in (
            ("old_redis_write_performed", "old_redis_write_observed"),
            ("exchange_action_taken", "exchange_action_observed"),
            ("approval_token_created", "approval_token_created"),
            ("redis_trim_approval_created", "redis_trim_approval_created"),
            ("legacy_mutation_performed", "legacy_mutation_observed"),
        ):
            if payload.get(key) is True:
                findings.append(f"{name}: {blocker}")
    return findings


def _next_tasks_markdown(recommendations: dict[str, Any]) -> str:
    lines = [
        "# Next Decision Improvement Tasks",
        "",
        f"Generated: `{recommendations['generated_at']}`",
        "",
        "This queue is V2 paper/shadow only and does not approve live trading or legacy shutdown.",
        "",
    ]
    for task in recommendations.get("next_tasks", []):
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


def _report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Legacy V2 Realtime Decision Observatory Report",
            "",
            f"Generated: `{payload['generated_at']}`",
            "",
            "This observatory is read-only against legacy evidence. It does not approve live trading, canary trading, or legacy shutdown.",
            "",
            "## Runtime Health",
            "",
            f"- legacy ingestion health: `{payload['legacy_ingestion_health']}`",
            f"- legacy trainer health: `{payload['legacy_trainer_health']}`",
            f"- legacy signal health: `{payload['legacy_signal_health']}`",
            f"- V2 decision quality: `{payload['v2_decision_quality']}`",
            f"- legacy-vs-V2 agreement: `{payload['legacy_v2_agreement']}`",
            f"- after-cost correctness: `{payload['after_cost_correctness']}`",
            f"- no-trade correctness: `{payload['no_trade_correctness']}`",
            f"- paper/shadow outcome: `{payload['paper_shadow_outcome']}`",
            "",
            "## Safety",
            "",
            f"- live_gate: `{payload['live_gate']}`",
            f"- live_symbols: `{payload['live_symbols']}`",
            f"- old Redis write status: `{payload['old_redis_write_status']}`",
            f"- exchange action status: `{payload['exchange_action_status']}`",
            f"- approval token status: `{payload['approval_token_status']}`",
            "",
            "## Current Decision",
            "",
            f"- shutdown recommendation: `{payload['legacy_shutdown_recommendation']}`",
            f"- GO/NO-GO: `{payload['go_no_go']}`",
            "",
            "## Recommendations",
            "",
            f"- recommendations generated: `{len(payload['recommendations_generated'])}`",
            f"- Claude tasks dispatched: `{payload['claude_tasks_dispatched']}`",
            f"- Codex reviews passed/failed: `{payload['codex_reviews_passed_failed']}`",
            "",
            "Primary next task remains cost-aware paper trade selection and shadow outcome learning. Post-filter no-fill is not being called positive edge.",
            "",
        ]
    )


def run_once(*, dry_run: bool = False) -> dict[str, Any]:
    paths = _payload_paths()
    paper = _load_first(paths["paper"])
    trainer = _load_first(paths["trainer"])
    symbol = _load_first(paths["symbol"])
    risk = _load_first(paths["risk"])
    paper_exec = _load_first(paths["paper_exec"])
    paper_loss = _load_first(paths["paper_loss"])
    paper_edge = _load_first(paths["paper_edge"])
    paper_shadow_outcome = _load_first(paths["paper_shadow_outcome"])
    paper_shadow_outcome_learning = _load_first(paths["paper_shadow_outcome_learning"])
    protective_behavior = _load_first(paths["protective_behavior"])
    shutdown = _load_first(paths["shutdown"])

    legacy = build_legacy_runtime_observer_status()
    comparator = build_legacy_v2_decision_comparator_status(
        legacy_status=legacy,
        paper_status=paper,
        trainer_status=trainer,
        symbol_status=symbol,
        risk_status=risk,
        paper_exec_status=paper_exec,
    )
    outcome = build_legacy_signal_outcome_observer_status(
        comparator_status=comparator,
        paper_status=paper,
    )
    scoreboard = build_decision_quality_scoreboard_status(
        comparator_status=comparator,
        outcome_status=outcome,
        paper_loss_status=paper_loss,
        paper_exec_status=paper_exec,
    )
    recommendations = build_decision_improvement_recommendations(
        scoreboard_status=scoreboard,
        paper_loss_status=paper_loss,
        trainer_status=trainer,
        paper_edge_status=paper_edge,
        shadow_outcome_status=paper_shadow_outcome,
        shadow_learning_status=paper_shadow_outcome_learning,
        protective_behavior_status=protective_behavior,
        symbol_status=symbol,
        risk_status=risk,
    )
    safety_findings = _safety_findings(
        [
            legacy,
            comparator,
            outcome,
            scoreboard,
            recommendations,
            paper,
            trainer,
            symbol,
            risk,
            paper_exec,
            paper_shadow_outcome,
            paper_shadow_outcome_learning,
            protective_behavior,
        ]
    )
    go_no_go = (
        "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_BLOCKED"
        if safety_findings
        else "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY"
    )
    shutdown_recommendation = (
        shutdown.get("current_recommendation")
        or shutdown.get("recommendation")
        or "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE"
    )
    dashboard = {
        "worker_id": "codex_legacy_v2_realtime_decision_observatory",
        "generated_at": utc_now(),
        "go_no_go": go_no_go,
        "safety_findings": safety_findings,
        "legacy_ingestion_health": legacy.get("ingestor_freshness", {}).get("state"),
        "legacy_trainer_health": legacy.get("legacy_trainer_process_state", {}).get("state"),
        "legacy_signal_health": legacy.get("signal_log", {}).get("freshness", {}).get("state"),
        "legacy_trader_process_state": legacy.get("legacy_trader_process_state"),
        "v2_decision_quality": scoreboard.get("primary_metric_status"),
        "legacy_v2_agreement": comparator.get("legacy_v2_agreement_status"),
        "after_cost_correctness": scoreboard.get("after_cost_accuracy"),
        "no_trade_correctness": scoreboard.get("no_trade_correct_rate"),
        "paper_shadow_outcome": outcome.get("outcome_status"),
        "recommendations_generated": recommendations.get("next_tasks", []),
        "claude_tasks_dispatched": [],
        "codex_reviews_passed_failed": {"passed": 0, "failed": 0, "pending": ["paper_edge_recovery"]},
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "old_redis_write_status": "ABSENT",
        "exchange_action_status": "ABSENT",
        "approval_token_status": "ABSENT",
        "legacy_shutdown_recommendation": shutdown_recommendation,
        "paper_pnl_visible": paper_loss.get("current_cumulative_paper_pnl")
        or paper_loss.get("current_cumulative_pnl")
        or (paper_loss.get("pnl_waterfall") or {}).get("current_cumulative_paper_pnl_usdt")
        or paper_exec.get("current_paper_pnl"),
        "paper_edge_status": paper_edge.get("edge_status")
        or paper_edge.get("classification")
        or "POST_FILTER_EDGE_PENDING",
        "paper_shadow_outcome_observer_status": paper_shadow_outcome.get("outcome_status")
        or paper_shadow_outcome.get("status")
        or "MISSING_EVIDENCE",
        "paper_shadow_false_block_count": paper_shadow_outcome.get("false_block_count", 0),
        "trainer_parity_gaps": trainer.get("remaining_parity_gaps")
        or trainer.get("trainer_full_parity_blockers")
        or [],
        "read_only_legacy_reference": True,
        "does_not_approve_live": True,
        "does_not_approve_legacy_shutdown": True,
    }
    if not dry_run:
        _write_runtime(
            "legacy_runtime_observer",
            "legacy_runtime_observer_status.json",
            legacy,
        )
        _write_runtime(
            "legacy_v2_decision_comparator",
            "legacy_v2_decision_comparator_status.json",
            comparator,
        )
        _write_runtime(
            "legacy_signal_outcome_observer",
            "legacy_signal_outcome_observer_status.json",
            outcome,
        )
        _write_runtime(
            "decision_quality_scoreboard",
            "decision_quality_scoreboard_status.json",
            scoreboard,
        )
        write_json(NEXT_TASKS_FILE, recommendations)
        write_text(NEXT_TASKS_MD, _next_tasks_markdown(recommendations))
        write_json(STATUS_FILE, dashboard)
        write_json(WORKLOG_PAYLOAD_FILE, dashboard)
        write_json(PUBLIC_PAYLOAD_FILE, dashboard)
        write_text(GO_NO_GO_FILE, go_no_go + "\n")
        write_text(REPORT_FILE, _report(dashboard))
    return dashboard


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=120)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.status:
        payload = load_json(STATUS_FILE) or load_json(PUBLIC_PAYLOAD_FILE) or {}
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.daemon:
        while True:
            run_once(dry_run=args.dry_run)
            time.sleep(max(5, args.poll_seconds))
    payload = run_once(dry_run=args.dry_run)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
