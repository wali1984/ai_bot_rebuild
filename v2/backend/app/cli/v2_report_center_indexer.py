"""V2 Report Center indexer.

Builds the realtime report index from worklog/public artifacts and
writes sanitized JSON payloads under
``v2/frontend/public/v2_report_center/latest/`` for the frontend
ReportCenterPage. Read-only with respect to legacy, Redis writes
outside ``v2:*``, exchange endpoints, approval tokens, and shutdown /
live state.

Modes: default one-shot. ``--loop`` runs a poll loop with a fixed
interval (default 60 s). ``--dry-run`` prints what would be written.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running from any cwd.
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.report_center.report_registry import (  # noqa: E402
    LANES,
    REPO_ROOT as REGISTRY_REPO_ROOT,
    index_lanes,
)
from v2.backend.app.services.report_center.safe_summary import (  # noqa: E402
    sanitize_text,
)

PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest"
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_report_center"
    / "latest"
)
SAFE_SUMMARIES_DIR = PUBLIC_DIR / "safe_summaries"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _build_aggregates(entries: list[dict[str, Any]]) -> dict[str, Any]:
    stale = sum(1 for e in entries if e["stale"])
    fail = sum(1 for e in entries if e["status"] == "FAIL")
    blocked = sum(1 for e in entries if e["status"] == "BLOCKED")
    codex_pass = sum(1 for e in entries if e["codex_passed"] is True)
    codex_fail = sum(1 for e in entries if e["codex_passed"] is False)
    op_dec = sum(1 for e in entries if e["status"] == "OPERATOR_DECISION_REQUIRED")

    blocks_live = any(e["blocks_live"] for e in entries) or True
    blocks_shutdown = any(e["blocks_shutdown"] for e in entries) or True
    blocks_pe = any(e["blocks_production_equivalence"] for e in entries) or True

    top_blockers: list[dict[str, Any]] = []
    for e in entries:
        if e["status"] in ("FAIL", "BLOCKED", "OPERATOR_DECISION_REQUIRED", "MISSING_PAYLOAD"):
            top_blockers.append({
                "report_id": e["report_id"],
                "title": e["title"],
                "status": e["status"],
                "go_no_go": e["go_no_go"],
                "next_action": e["next_action"],
                "blocks_live": e["blocks_live"],
                "blocks_shutdown": e["blocks_shutdown"],
                "blocks_production_equivalence": e["blocks_production_equivalence"],
                "blocks_recovery": e["blocks_recovery"],
                "current_blockers": e["current_blockers"],
                "owner": e["owner"],
            })
    next_automatable: list[dict[str, Any]] = []
    next_operator: list[dict[str, Any]] = []
    for e in entries:
        if e["owner"] in ("OPERATOR",) and e["status"] in (
            "BLOCKED", "OPERATOR_DECISION_REQUIRED", "MISSING_PAYLOAD"
        ):
            next_operator.append({
                "report_id": e["report_id"],
                "title": e["title"],
                "owner": e["owner"],
                "next_action": e["next_action"],
            })
        elif e["owner"] in ("CLAUDE", "CODEX") and e["status"] not in ("PASS", "READY"):
            next_automatable.append({
                "report_id": e["report_id"],
                "title": e["title"],
                "owner": e["owner"],
                "next_action": e["next_action"],
                "status": e["status"],
            })

    return {
        "report_count": len(entries),
        "stale_report_count": stale,
        "fail_count": fail,
        "blocked_count": blocked,
        "codex_pass_count": codex_pass,
        "codex_fail_count": codex_fail,
        "operator_decision_required_count": op_dec,
        "top_blockers": top_blockers[:16],
        "next_automatable_actions": next_automatable[:8],
        "next_operator_decisions": next_operator[:8],
    }


def _load_optional_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Executive clarity layer
# ---------------------------------------------------------------------------
# Built for V2_REPORT_CENTER_EXECUTIVE_CLARITY_REMEDIATION_READY. This is a
# clarity layer only: it does not change migration state, does not gate live
# trading, and does not create approvals. It re-states the same blocked facts
# in plain English so executives can answer five questions at a glance:
#   1. Are we migrated?
#   2. Can legacy shut down?
#   3. Can we go live?
#   4. What is blocking?
#   5. What is the next action?

_MARKER_GLOSSARY: dict[str, str] = {
    "live_gate=blocked_human_only":
        "Live trading switch is off. Only a human operator can enable it.",
    "live_symbols=[]":
        "No symbol is approved for live trading. The live universe is empty.",
    "approves_live=false":
        "This report does not approve enabling live trading.",
    "approves_canary=false":
        "This report does not approve enabling a canary (single-order live) run.",
    "approves_legacy_shutdown=false":
        "Legacy bot must keep running. We are not approving its shutdown.",
    "approves_redis_trim=false":
        "We are not approving deletion of legacy Redis keys.",
    "shutdown_blocked=true":
        "Legacy shutdown is blocked because V2 is not yet a production replacement.",
    "production_equivalence_blocked=true":
        "V2 has not yet been proven to match legacy in production behavior.",
    "MISSING_PAYLOAD":
        "We expected a status file for this lane but did not find one.",
    "OPERATOR_DECISION_REQUIRED":
        "A human decision is required before this lane can advance.",
    "BLOCKED":
        "This lane is blocked by an open issue.",
    "PASS":
        "This lane has passed its own gate.",
    "READY":
        "This lane is ready (in its narrow sense; does not imply live readiness).",
    "automation_executing":
        "True only when a worker is actively holding a lease on a task right now.",
    "worker_capacity_ready":
        "Daemon workers are running but they may have zero active leases.",
    "paper_edge_proven":
        "Paper trading has produced a statistically significant positive after-cost edge.",
    "migration_complete":
        "V2 fully replaces legacy in production. Currently NO.",
    "legacy_shutdown_ready":
        "It is safe to turn off the legacy bot. Currently NO.",
    "live_ready":
        "V2 is safe to enable for live trading. Currently NO.",
}


def _load_worker_pool_snapshot() -> dict[str, Any]:
    snap = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_worker_pool_mission_progress"
        / "latest"
        / "worker_pool_mission_progress_status.json"
    ) or {}
    ref = snap.get("worker_pool_reference") or {}
    return {
        "active_leases_count": ref.get("active_leases_count", 0),
        "worker_count_busy": ref.get("worker_count_busy", 0),
        "worker_count_idle_ready": ref.get("worker_count_idle_ready", 0),
        "active_claude_workers": ref.get("active_claude_workers", 0),
        "active_codex_workers": ref.get("active_codex_workers", 0),
        "current_automatable_count": ref.get("current_automatable_count", 0),
        "mission_progress_state": snap.get("mission_progress_state"),
        "active_task_count": len(snap.get("current_active_tasks") or []),
        "snapshot_path": (
            "claude_worklog/final_readiness/v2_worker_pool_mission_progress/"
            "latest/worker_pool_mission_progress_status.json"
        ),
    }


def _load_progress_signals() -> dict[str, Any]:
    dyn = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_native_dynamic_ingestor_runtime_and_symbol_expansion"
        / "latest"
        / "phase_5_coverage_and_downstream_refresh.json"
    ) or {}
    pub = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_native_trainer_prediction_publisher"
        / "latest"
        / "publisher_audit.json"
    ) or {}
    base = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_native_trainer_dataset_and_baseline_model"
        / "latest"
        / "v2_native_baseline_model_status.json"
    ) or {}
    sym = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "symbol_universe_public_payload"
        / "latest"
        / "symbol_universe_status.json"
    ) or {}
    paper = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "paper_edge_post_filter_observation_window"
        / "latest"
        / "paper_edge_post_filter_observation_status.json"
    ) or {}
    return {
        "dynamic_coverage": {
            "currently_active_symbols": dyn.get("currently_active_symbols") or [],
            "active_symbol_count": len(dyn.get("currently_active_symbols") or []),
            "families": dyn.get("families") or [],
            "family_count": len(dyn.get("families") or []),
            "did_not_claim_full_migration": dyn.get("did_not_claim_full_migration"),
        },
        "prediction_publisher": {
            "redis_connected": pub.get("redis_connected"),
            "writes_succeeded": pub.get("writes_succeeded"),
            "writes_failed": pub.get("writes_failed"),
            "old_redis_write_attempts": pub.get("old_redis_write_attempts"),
            "key_count": pub.get("key_count"),
        },
        "dataset_baseline_model": {
            "checkpoint_compatibility_claimed": base.get(
                "checkpoint_compatibility_claimed"
            ),
            "claimed_trainer_native_readiness": not (
                base.get("did_not_claim_trainer_native_readiness", True)
            ),
        },
        "symbol_universe": {
            "binance_usdm_confirmed_symbols":
                sym.get("binance_usdm_confirmed_symbols") or [],
            "discovered_symbol_count":
                len(sym.get("discovered_symbols") or []),
            "coinank_symbols_directly_tradable":
                sym.get("coinank_symbols_directly_tradable", False),
        },
        "paper_edge_observation": {
            "after_cost_expectancy_bps": paper.get("after_cost_expectancy_bps"),
            "trade_count": paper.get("trade_count"),
            "edge_proven": False,
        },
    }


def _category_score(scorecard: dict[str, Any], name: str) -> int | None:
    cats = (scorecard.get("categories") or {})
    v = cats.get(name)
    if not v:
        return None
    s = v.get("score")
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _build_executive_summary(
    aggregates: dict[str, Any],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    scorecard = current_state.get("current_scorecard") or {}
    workers = _load_worker_pool_snapshot()
    progress = _load_progress_signals()

    # Truth derivations. We default to NO and only flip to YES when we have
    # explicit, verified evidence. This is a clarity layer; it must never
    # claim YES on its own.
    paper_edge_score = _category_score(scorecard, "paper_edge_readiness")
    paper_edge_proven = (paper_edge_score or 0) >= 80
    risk_score = _category_score(scorecard, "risk_readiness") or 0
    decision_match_score = _category_score(scorecard, "decision_match_readiness") or 0
    model_policy_score = _category_score(scorecard, "model_policy_readiness") or 0
    checkpoint_score = _category_score(scorecard, "checkpoint_readiness") or 0
    observation_score = _category_score(scorecard, "observation_completeness") or 0

    migration_complete = False  # production_equivalence_blocked is always True today
    legacy_shutdown_ready = False
    live_ready = False
    automation_executing = (workers.get("active_leases_count") or 0) > 0
    worker_queue_size = workers.get("current_automatable_count") or 0

    big_state_banner = [
        {
            "key": "MIGRATION_COMPLETE",
            "value": "YES" if migration_complete else "NO",
            "plain_english": (
                "V2 has not fully replaced legacy yet. Production-equivalence "
                "is still blocked."
            ),
        },
        {
            "key": "LEGACY_SHUTDOWN_READY",
            "value": "YES" if legacy_shutdown_ready else "NO",
            "plain_english": (
                "Legacy bot must keep running. Shutdown is blocked until V2 "
                "is a verified replacement."
            ),
        },
        {
            "key": "LIVE_READY",
            "value": "YES" if live_ready else "NO",
            "plain_english": (
                "V2 is not approved for live trading. Live gate is blocked "
                "human-only and the live symbol list is empty."
            ),
        },
        {
            "key": "PAPER_EDGE_PROVEN",
            "value": "YES" if paper_edge_proven else "NO",
            "plain_english": (
                "Paper trading has not yet produced a statistically significant "
                "positive after-cost edge."
            ),
        },
        {
            "key": "AUTOMATION_EXECUTING",
            "value": "YES" if automation_executing else "NO",
            "plain_english": (
                "Workers are currently leasing tasks." if automation_executing
                else (
                    "Worker daemons are up and the current automatable queue "
                    "is empty; no active execution is expected."
                    if worker_queue_size == 0 else
                    "Worker daemons are up, but no worker is currently leasing "
                    "a task. Queue capacity is ready, but no active execution."
                )
            ),
            "evidence": {
                "active_leases_count": workers.get("active_leases_count"),
                "worker_count_busy": workers.get("worker_count_busy"),
                "worker_count_idle_ready": workers.get("worker_count_idle_ready"),
                "source": workers.get("snapshot_path"),
                "note": (
                    "AUTOMATION_EXECUTING is derived from active worker "
                    "leases, NOT from worker heartbeats. Idle daemons do "
                    "not count as execution."
                ),
            },
        },
    ]

    top_blockers_plain = [
        {
            "key": "native_trainer_model_not_production_ready",
            "plain_english": (
                "The native V2 trainer/model is not production-ready. "
                "Policy architecture has not started; baseline model has "
                "no positive after-cost expectancy yet."
            ),
            "evidence": {
                "model_policy_score": model_policy_score,
                "decision_match_score": decision_match_score,
            },
        },
        {
            "key": "paper_edge_not_proven",
            "plain_english": (
                "Paper trading has not produced a positive, statistically "
                "significant after-cost edge."
            ),
            "evidence": {"paper_edge_score": paper_edge_score},
        },
        {
            "key": "checkpoint_not_loaded",
            "plain_english": (
                "Legacy checkpoint is not loaded. Deserialization is "
                "forbidden without operator approval."
            ),
            "evidence": {"checkpoint_score": checkpoint_score},
        },
        {
            "key": "risk_caps_unset",
            "plain_english": (
                "Operator risk caps (daily/weekly loss, position notional, "
                "consecutive losses, canary size) are not set."
            ),
            "evidence": {"risk_readiness_score": risk_score},
        },
        {
            "key": "legacy_shutdown_blocked",
            "plain_english": (
                "Legacy bot must keep running. V2 has not been certified as "
                "a production replacement."
            ),
        },
        {
            "key": "worker_queue_executing_or_idle",
            "plain_english": (
                "Workers are leasing tasks." if automation_executing
                else (
                    "Workers are idle because the current automatable queue "
                    "is empty."
                    if worker_queue_size == 0 else
                    "Workers are idle. Queue capacity exists but no task "
                    "is being executed right now."
                )
            ),
            "evidence": {
                "active_leases_count": workers.get("active_leases_count"),
                "automatable_queue_size": workers.get("current_automatable_count"),
            },
        },
    ]

    current_progress = {
        "dynamic_market_coverage": {
            "active_symbol_count": progress["dynamic_coverage"]["active_symbol_count"],
            "active_symbols": progress["dynamic_coverage"]["currently_active_symbols"],
            "family_count": progress["dynamic_coverage"]["family_count"],
            "plain_english": (
                f"Dynamic market data covers "
                f"{progress['dynamic_coverage']['active_symbol_count']} symbols "
                f"across {progress['dynamic_coverage']['family_count']} feature "
                "families. Symbol adoption beyond this list still requires "
                "operator approval."
            ),
        },
        "prediction_publisher": {
            "redis_connected": progress["prediction_publisher"]["redis_connected"],
            "writes_succeeded": progress["prediction_publisher"]["writes_succeeded"],
            "writes_failed": progress["prediction_publisher"]["writes_failed"],
            "old_redis_write_attempts":
                progress["prediction_publisher"]["old_redis_write_attempts"],
            "plain_english": (
                "V2 prediction publisher is writing payloads to v2:* Redis "
                "keys only. It is not approved as a live trading source."
            ),
        },
        "dataset_baseline_model": {
            "claimed_trainer_native_readiness":
                progress["dataset_baseline_model"]["claimed_trainer_native_readiness"],
            "plain_english": (
                "A baseline model exists but is not certified as production "
                "trainer-native. Edge has not been demonstrated."
            ),
        },
        "symbol_universe": {
            "binance_usdm_confirmed_count":
                len(progress["symbol_universe"]["binance_usdm_confirmed_symbols"]),
            "discovered_symbol_count":
                progress["symbol_universe"]["discovered_symbol_count"],
            "coinank_symbols_directly_tradable":
                progress["symbol_universe"]["coinank_symbols_directly_tradable"],
            "plain_english": (
                "Discovered symbols are intelligence-only until Binance USD-M "
                "confirms tradability AND an operator approves adoption."
            ),
        },
        "worker_pool": {
            "active_leases_count": workers.get("active_leases_count"),
            "worker_count_busy": workers.get("worker_count_busy"),
            "worker_count_idle_ready": workers.get("worker_count_idle_ready"),
            "current_automatable_queue_size":
                workers.get("current_automatable_count"),
            "mission_progress_state": workers.get("mission_progress_state"),
            "plain_english": (
                "Worker daemons are running. With "
                f"{workers.get('active_leases_count', 0)} active leases right "
                "now, this is "
                + ("active execution." if automation_executing
                   else (
                       "idle because the current automatable queue is empty."
                       if worker_queue_size == 0 else
                       "capacity-ready but not executing."
                   ))
            ),
        },
    }

    plain_english_truth = (
        "V2 has dynamic market data coverage, a working prediction publisher, "
        "and a baseline model, but the model is not production-ready and "
        "paper trading has not yet proven a positive after-cost edge. "
        "Legacy must stay on. Live trading and legacy shutdown both remain "
        "blocked and require explicit human approval."
    )

    next_required_actions = [
        {
            "key": "queue_consumption_remediation",
            "owner": "AUTOMATION",
            "plain_english": (
                "Current queue consumption is clean: no automatable queue "
                "items are waiting without a lease/blocker."
                if worker_queue_size == 0 else
                "Get the automatable queue actually consumed by workers so "
                "that AUTOMATION_EXECUTING flips to YES."
            ),
            "blocks": [] if worker_queue_size == 0 else [
                "migration_complete", "legacy_shutdown_ready"
            ],
        },
        {
            "key": "model_improvement_and_baseline_edge_proof",
            "owner": "AUTOMATION",
            "plain_english": (
                "Improve the native model and prove a positive, after-cost, "
                "statistically significant paper edge."
            ),
            "blocks": ["paper_edge_proven", "live_ready"],
        },
        {
            "key": "threshold_decision_packet",
            "owner": "OPERATOR",
            "plain_english": (
                "Operator decides the numeric thresholds that count as 'edge' "
                "(min trades, min after-cost expectancy, max drawdown)."
            ),
            "blocks": ["paper_edge_proven"],
        },
        {
            "key": "checkpoint_and_operator_decisions_later",
            "owner": "OPERATOR",
            "plain_english": (
                "Later, the operator decides whether to load the legacy "
                "checkpoint and set risk caps. Do not act on these yet."
            ),
            "blocks": ["live_ready"],
        },
    ]

    return {
        "schema_version": "v2_report_center_executive_summary_v1",
        "headline": (
            "MIGRATION_COMPLETE=NO, LEGACY_SHUTDOWN_READY=NO, LIVE_READY=NO, "
            f"PAPER_EDGE_PROVEN=NO, AUTOMATION_EXECUTING="
            f"{'YES' if automation_executing else 'NO'}"
        ),
        "big_state_banner": big_state_banner,
        "top_blockers_plain": top_blockers_plain,
        "current_progress": current_progress,
        "plain_english_truth": plain_english_truth,
        "next_required_actions": next_required_actions,
        "marker_glossary": _MARKER_GLOSSARY,
        "safety_invariants_plain_english": [
            "Live trading stays off until a human turns it on.",
            "Legacy keeps running.",
            "No symbol is auto-adopted into live trading.",
            "This page is a clarity layer only; it cannot approve anything.",
        ],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _build_current_state_block() -> dict[str, Any]:
    sh = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_autonomous_full_rebuild_self_healing"
        / "latest"
        / "autonomous_full_rebuild_self_healing_status.json"
    ) or {}
    scorecard = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_executive_command_center"
        / "latest"
        / "production_readiness_scorecard.json"
    ) or {}
    watchdog = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_autonomous_full_rebuild_self_healing"
        / "latest"
        / "pending_task_watchdog_status.json"
    ) or {}
    issues = _load_optional_json(
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_autonomous_full_rebuild_self_healing"
        / "latest"
        / "latest_issues.json"
    ) or {}
    return {
        "current_scorecard": {
            "overall_score": scorecard.get("overall_score"),
            "categories": (
                {
                    k: {"score": v.get("score"), "blockers": v.get("blockers"),
                        "next_action": v.get("next_action")}
                    for k, v in (scorecard.get("categories") or {}).items()
                }
            ),
        },
        "current_autonomous_controller_state": {
            "go_no_go": sh.get("go_no_go"),
            "selector_status": sh.get("selector_status"),
            "selected_work": sh.get("selected_work"),
            "automatable_issue_count": sh.get("automatable_issue_count"),
            "operator_owned_issue_count": sh.get("operator_owned_issue_count"),
        },
        "current_pending_tasks": {
            "claude": watchdog.get("pending_claude_count", 0),
            "codex": watchdog.get("pending_codex_count", 0),
        },
        "current_stalled_tasks": {
            "claude": watchdog.get("stale_claude_count", 0),
            "codex": watchdog.get("stale_codex_count", 0),
        },
        "current_codex_failures": (issues.get("summary_by_category") or {}).get(
            "CODEX_REVIEW_FAIL", 0
        ),
    }


def run_once(*, stale_age_seconds: int = 30 * 60, dry_run: bool = False) -> dict[str, Any]:
    index = index_lanes(stale_age_seconds=stale_age_seconds)
    entries = index["entries"]
    aggregates = _build_aggregates(entries)
    current_state = _build_current_state_block()
    executive_summary = _build_executive_summary(aggregates, current_state)

    operator_dashboard = {
        "schema_version": "v2_report_center_operator_dashboard_v1",
        "generated_at": _utc_iso(),
        "go_no_go": "V2_REPORT_CENTER_EXECUTIVE_CLARITY_REMEDIATION_READY",
        "executive_summary": executive_summary,
        **aggregates,
        **current_state,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "shutdown_blocked": True,
        "live_blocked": True,
        "production_equivalence_blocked": True,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "required_visible_text": [
            "Live trading is blocked.",
            "Legacy shutdown is blocked.",
            "Candidate symbols are not adopted automatically.",
            "Recovery requires proof of edge before scaling.",
            "No fake readiness."
        ],
        "honesty_invariants": [
            "missing payloads are shown with status MISSING_PAYLOAD and stale=true",
            "no fake ready state when underlying lanes are blocked",
            "secrets are redacted",
        ],
    }

    report_index = {
        "schema_version": "v2_report_center_report_index_v1",
        "generated_at": _utc_iso(),
        "lanes": entries,
        **aggregates,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    summary_view = {
        "schema_version": "v2_report_center_report_summary_v1",
        "generated_at": _utc_iso(),
        "report_summaries": [
            {
                "report_id": e["report_id"],
                "title": e["title"],
                "status": e["status"],
                "go_no_go": e["go_no_go"],
                "owner": e["owner"],
                "freshness_seconds": e["freshness_seconds"],
                "stale": e["stale"],
                "next_action": e["next_action"],
                "current_blockers": e["current_blockers"],
            }
            for e in entries
        ],
        **{k: aggregates[k] for k in (
            "report_count", "stale_report_count", "fail_count",
            "blocked_count", "codex_pass_count", "codex_fail_count",
            "operator_decision_required_count",
        )},
    }
    latest_blockers = {
        "schema_version": "v2_report_center_latest_blockers_v1",
        "generated_at": _utc_iso(),
        "blockers": aggregates["top_blockers"],
    }
    latest_codex_failures = {
        "schema_version": "v2_report_center_latest_codex_failures_v1",
        "generated_at": _utc_iso(),
        "codex_failures": [
            {
                "report_id": e["report_id"],
                "title": e["title"],
                "go_no_go": e["go_no_go"],
                "next_action": e["next_action"],
            }
            for e in entries
            if e["codex_passed"] is False
        ],
        "count": aggregates["codex_fail_count"],
    }
    latest_next_actions = {
        "schema_version": "v2_report_center_latest_next_actions_v1",
        "generated_at": _utc_iso(),
        "next_automatable_actions": aggregates["next_automatable_actions"],
        "next_operator_decisions": aggregates["next_operator_decisions"],
    }

    if not dry_run:
        # Public payloads (frontend reads these).
        _write_json(PUBLIC_DIR / "report_index.json", report_index)
        _write_json(PUBLIC_DIR / "report_summary.json", summary_view)
        _write_json(PUBLIC_DIR / "latest_blockers.json", latest_blockers)
        _write_json(PUBLIC_DIR / "latest_codex_failures.json", latest_codex_failures)
        _write_json(PUBLIC_DIR / "latest_next_actions.json", latest_next_actions)
        _write_json(PUBLIC_DIR / "operator_dashboard_payload.json", operator_dashboard)
        # Executive clarity layer payload (consumed by /admin/executive-status
        # and embedded in /admin/report-center top banner).
        _write_json(
            PUBLIC_DIR / "executive_status_payload.json",
            {
                "schema_version": "v2_report_center_executive_status_v1",
                "go_no_go": "V2_REPORT_CENTER_EXECUTIVE_CLARITY_REMEDIATION_READY",
                "generated_at": _utc_iso(),
                "executive_summary": executive_summary,
                "report_aggregates": {
                    k: aggregates[k] for k in (
                        "report_count", "stale_report_count", "fail_count",
                        "blocked_count", "operator_decision_required_count",
                    )
                },
                "current_scorecard_overall_score":
                    (current_state.get("current_scorecard") or {}).get("overall_score"),
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
            },
        )
        # Per-lane sanitized safe summaries.
        SAFE_SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
        for e in entries:
            slim = {
                "report_id": e["report_id"],
                "title": e["title"],
                "status": e["status"],
                "go_no_go": e["go_no_go"],
                "owner": e["owner"],
                "stale": e["stale"],
                "freshness_seconds": e["freshness_seconds"],
                "sanitized_summary": e["sanitized_summary"],
                "redaction_applied": e["redaction_applied"],
                "live_gate": e["live_gate"],
                "live_symbols": e["live_symbols"],
            }
            _write_json(SAFE_SUMMARIES_DIR / f"{e['report_id']}.json", slim)
        # Worklog snapshot for the report center status itself.
        _write_json(WORKLOG_DIR / "report_center_status.json", operator_dashboard)

    return operator_dashboard


def main() -> int:
    p = argparse.ArgumentParser(prog="v2_report_center_indexer")
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=60)
    p.add_argument("--stale-seconds", type=int, default=30 * 60)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.loop:
        try:
            while True:
                run_once(stale_age_seconds=args.stale_seconds, dry_run=args.dry_run)
                time.sleep(max(15, args.interval_seconds))
        except KeyboardInterrupt:
            return 0
    state = run_once(stale_age_seconds=args.stale_seconds, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps({
            "generated_at": state["generated_at"],
            "report_count": state["report_count"],
            "stale_report_count": state["stale_report_count"],
            "fail_count": state["fail_count"],
            "blocked_count": state["blocked_count"],
            "codex_pass_count": state["codex_pass_count"],
            "codex_fail_count": state["codex_fail_count"],
            "operator_decision_required_count": state["operator_decision_required_count"],
            "live_blocked": state["live_blocked"],
            "shutdown_blocked": state["shutdown_blocked"],
            "production_equivalence_blocked": state["production_equivalence_blocked"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
