"""Frontend truth payload builder.

Aggregates V2 runtime payloads into a single
v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json
that the frontend's admin and user pages consume. Keeps the frontend simple
and prevents every page from inventing its own truth.

This builder:
- Reads only V2 public payloads and worklog readiness JSON.
- Never authorizes fills, live trades, canary, legacy shutdown, or Redis trim.
- Never writes back into legacy Redis or legacy state.
- Marks any missing payload as MISSING_EVIDENCE and any stale payload as STALE.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]

LIVE_GATE_STATUS = "blocked_human_only"

OUTPUT_PATH = REPO_ROOT / "v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json"


SOURCES: dict[str, Path | tuple[Path, ...]] = {
    "operator_truth": (
        REPO_ROOT / "v2/frontend/public/operator_truth/latest/operator_truth_payload.json",
        REPO_ROOT / "v2/frontend/public/operator_truth/latest/operator_truth_bridge_payload.json",
        REPO_ROOT / "v2/frontend/public/operator_truth/latest/operator_truth.json",
    ),
    "v2_symbol_universe": REPO_ROOT / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json",
    "paper_edge_recovery": REPO_ROOT / "v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json",
    "paper_shadow_outcome_observer": REPO_ROOT / "v2/frontend/public/paper_shadow_outcome_observer/latest/operator_dashboard_payload.json",
    "expected_move_model_review": REPO_ROOT / "v2/frontend/public/expected_move_model_review/latest/operator_dashboard_payload.json",
    "v2_trainer_bridge": REPO_ROOT / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json",
    "legacy_v2_realtime_decision_observatory": REPO_ROOT / "v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json",
    "codex_shutdown_readiness_takeover": REPO_ROOT / "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json",
    "v2_worker_porting_orchestrator": REPO_ROOT / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json",
    "paper_loss_attribution": REPO_ROOT / "v2/frontend/public/paper_loss_attribution/latest/operator_dashboard_payload.json",
    "account_position_monitor": REPO_ROOT / "v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json",
    "risk_gateway": REPO_ROOT / "v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json",
    "signal_lineage": REPO_ROOT / "v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json",
    "execution_ledger": REPO_ROOT / "v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json",
    "permanent_migration_router": REPO_ROOT / "v2/frontend/public/permanent_migration_runtime/latest/router_status.json",
}


STALE_AFTER_SECONDS = 24 * 60 * 60  # 24h


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _resolve_source_path(path_or_paths: Path | tuple[Path, ...]) -> Path:
    if isinstance(path_or_paths, tuple):
        for candidate in path_or_paths:
            if candidate.exists():
                return candidate
        return path_or_paths[0]
    return path_or_paths


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _payload_age_seconds(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
        return int((_utc_now() - mtime).total_seconds())
    except Exception:
        return None


def load_sources() -> tuple[dict[str, Any], dict[str, str], list[str], list[str]]:
    """Return (payloads, status_per_source, stale_payloads, missing_payloads)."""
    payloads: dict[str, Any] = {}
    status: dict[str, str] = {}
    stale: list[str] = []
    missing: list[str] = []

    for key, path_or_paths in SOURCES.items():
        path = _resolve_source_path(path_or_paths)
        data = _read_json(path)
        age = _payload_age_seconds(path)
        if data is None:
            payloads[key] = None
            status[key] = "MISSING_EVIDENCE"
            missing.append(key)
            continue
        payloads[key] = data
        if age is not None and age > STALE_AFTER_SECONDS:
            status[key] = "STALE"
            stale.append(key)
        else:
            status[key] = "FRESH"

    return payloads, status, stale, missing


def _safe(payload: Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return default


def derive_simple_summary(payloads: dict[str, Any]) -> dict[str, Any]:
    """Plain-English summary the frontend renders on every page."""
    em = payloads.get("expected_move_model_review") or {}
    tb = payloads.get("v2_trainer_bridge") or {}
    paper = payloads.get("paper_edge_recovery") or {}
    shutdown = payloads.get("codex_shutdown_readiness_takeover") or {}
    router = payloads.get("permanent_migration_router") or {}

    plain_english_summary = "The bot is watching only. It is not allowed to trade live."
    current_goal = "Prove paper edge and finish migrating the trainer before changing the live block."
    shutdown_rec = shutdown.get("current_recommendation") or "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE"

    paper_edge_status = em.get("edge_status") or "EDGE_PENDING_MODEL_REVIEW_REQUIRED"
    trainer_parity_status = tb.get("trainer_parity_status") or em.get("trainer_parity_status") or "BLOCKS_LEGACY_SHUTDOWN"

    blockers_simple: list[str] = []
    if "EDGE_PENDING" in str(paper_edge_status):
        blockers_simple.append("Paper edge has not proven it can beat fees.")
    if "BLOCKS_LEGACY_SHUTDOWN" in str(trainer_parity_status):
        blockers_simple.append("Trainer evidence is not complete.")
    if shutdown_rec and "BLOCK_LEGACY_SHUTDOWN" in shutdown_rec:
        blockers_simple.append("Legacy shutdown is blocked until parity is proven.")
    if router and router.get("routing", {}).get("p0_blockers_remaining", 0) > 0:
        blockers_simple.append("There are P0 runtime blockers still open.")

    blockers_technical = []
    selected = (router or {}).get("routing", {}).get("selected_blocker") or {}
    if selected:
        blockers_technical.append({
            "id": selected.get("id"),
            "category": selected.get("category"),
            "remediation_task_id": selected.get("remediation_task_id"),
            "source": selected.get("source"),
            "evidence": selected.get("evidence"),
        })

    active_claude_task = (router or {}).get("routing", {}).get("next_task_id") or "n/a"

    return {
        "plain_english_summary": plain_english_summary,
        "current_goal": current_goal,
        "shutdown_recommendation": shutdown_rec,
        "live_gate": LIVE_GATE_STATUS,
        "paper_edge_status": paper_edge_status,
        "trainer_parity_status": trainer_parity_status,
        "decision_quality_status": (payloads.get("legacy_v2_realtime_decision_observatory") or {}).get("decision_quality_status") or "INSUFFICIENT_SAMPLE",
        "active_claude_task": active_claude_task,
        "active_codex_task": "codex_shutdown_readiness_takeover",
        "last_completed_fix": "expected_move_false_block_calibration_review",
        "next_fix": active_claude_task,
        "blockers_simple": blockers_simple,
        "blockers_technical": blockers_technical,
    }


def page_cards(payloads: dict[str, Any], status: dict[str, str]) -> list[dict[str, Any]]:
    """One card per route. Frontend renders by id."""
    def s(name: str) -> str:
        return status.get(name, "MISSING_EVIDENCE")

    em = payloads.get("expected_move_model_review") or {}
    paper = payloads.get("paper_edge_recovery") or {}
    tb = payloads.get("v2_trainer_bridge") or {}

    cards = [
        {
            "id": "admin.mission_control",
            "title": "Mission Control",
            "color": "yellow",
            "summary": "Bot is watching only. Live is blocked.",
            "why_it_matters": "Mission Control is the single source of truth for what Claude and Codex are doing right now.",
            "what_needs_to_happen_next": "Close P0 blockers in the router.",
            "evidence_paths": [
                "v2/frontend/public/permanent_migration_runtime/latest/router_status.json",
            ],
            "source_status": s("permanent_migration_router"),
        },
        {
            "id": "admin.migration",
            "title": "Migration Progress",
            "color": "yellow",
            "summary": "No workers are MIGRATED_CODEX_PASS yet.",
            "why_it_matters": "The migration completion contract requires 13 clauses per worker.",
            "what_needs_to_happen_next": "Resolve parity matrix gaps for trainer, risk, orchestrator, account monitor.",
            "evidence_paths": [
                "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
                "claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/v2_parity_gap_matrix.json",
            ],
            "source_status": "FRESH",
        },
        {
            "id": "admin.shutdown_readiness",
            "title": "Shutdown Readiness",
            "color": "red",
            "summary": (payloads.get("codex_shutdown_readiness_takeover") or {}).get("current_recommendation") or "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE",
            "why_it_matters": "Legacy cannot be turned off until V2 is proven at parity.",
            "what_needs_to_happen_next": "Clear all P0 blockers in the takeover matrix.",
            "evidence_paths": [
                "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json",
            ],
            "source_status": s("codex_shutdown_readiness_takeover"),
        },
        {
            "id": "admin.paper_edge",
            "title": "Paper Edge",
            "color": "yellow",
            "summary": f"{em.get('edge_status', 'EDGE_PENDING_MODEL_REVIEW_REQUIRED')}; false_block_count={em.get('false_block_count')}",
            "why_it_matters": "Until paper proves it can beat fees, the bot is not allowed to trade live.",
            "what_needs_to_happen_next": "Run the false-block calibration replay until a safe threshold candidate appears.",
            "evidence_paths": [
                "v2/frontend/public/expected_move_model_review/latest/operator_dashboard_payload.json",
                "v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json",
            ],
            "source_status": s("expected_move_model_review"),
        },
        {
            "id": "admin.trainer_parity",
            "title": "Trainer Parity",
            "color": "red",
            "summary": (tb.get("trainer_parity_status") or "BLOCKS_LEGACY_SHUTDOWN"),
            "why_it_matters": "The trainer must produce native predictions before we can claim live parity.",
            "what_needs_to_happen_next": "Build full hybrid trainer parity artifacts.",
            "evidence_paths": [
                "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json",
                "claude_worklog/final_readiness/permanent_migration_runtime/latest/TRAINER_PARITY_BLOCKER_PACKET.md",
            ],
            "source_status": s("v2_trainer_bridge"),
        },
        {
            "id": "admin.decision_quality",
            "title": "Decision Quality",
            "color": "yellow",
            "summary": (payloads.get("legacy_v2_realtime_decision_observatory") or {}).get("decision_quality_status") or "INSUFFICIENT_SAMPLE",
            "why_it_matters": "We cannot claim 99% correctness until enough acted trades exist.",
            "what_needs_to_happen_next": "Keep no-trade / outcome observation running.",
            "evidence_paths": [
                "v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json",
            ],
            "source_status": s("legacy_v2_realtime_decision_observatory"),
        },
        {
            "id": "admin.codex_claude_control",
            "title": "Codex / Claude Control",
            "color": "green",
            "summary": "Codex takeover loop and Claude observatory are active.",
            "why_it_matters": "The dispatcher must keep running while runtime work is in flight.",
            "what_needs_to_happen_next": "Keep watching the router status.",
            "evidence_paths": [
                "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/codex_shutdown_takeover_status.json",
            ],
            "source_status": "FRESH",
        },
        {
            "id": "user.markets",
            "title": "Markets",
            "color": "green",
            "summary": "Read-only market intelligence from V2 payloads.",
            "why_it_matters": "User pages must consume V2 payloads only, never legacy Redis directly.",
            "what_needs_to_happen_next": "n/a",
            "evidence_paths": [
                "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json",
            ],
            "source_status": s("v2_symbol_universe"),
        },
        {
            "id": "user.bots_trainer",
            "title": "Trainer Decisions",
            "color": "yellow",
            "summary": "Predictions are derived from legacy logs, not native trainer output yet.",
            "why_it_matters": "Until native trainer evidence is produced, decisions cannot be claimed as full parity.",
            "what_needs_to_happen_next": "Build full trainer parity artifacts.",
            "evidence_paths": [
                "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json",
            ],
            "source_status": s("v2_trainer_bridge"),
        },
        {
            "id": "user.paper_trading",
            "title": "Paper Trading",
            "color": "yellow",
            "summary": "Paper edge is unproven; fills are blocked by the strict gate.",
            "why_it_matters": "We never claim positive edge until evidence supports it.",
            "what_needs_to_happen_next": "Continue paper shadow soak.",
            "evidence_paths": [
                "v2/frontend/public/paper_shadow_outcome_observer/latest/operator_dashboard_payload.json",
            ],
            "source_status": s("paper_shadow_outcome_observer"),
        },
    ]
    return cards


def build_payload() -> dict[str, Any]:
    payloads, status, stale, missing = load_sources()
    summary = derive_simple_summary(payloads)
    cards = page_cards(payloads, status)
    return {
        "schema_version": "1.0.0",
        "generated_utc": _utc_now().isoformat(timespec="seconds"),
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "plain_english_summary": summary["plain_english_summary"],
        "current_goal": summary["current_goal"],
        "shutdown_recommendation": summary["shutdown_recommendation"],
        "paper_edge_status": summary["paper_edge_status"],
        "trainer_parity_status": summary["trainer_parity_status"],
        "decision_quality_status": summary["decision_quality_status"],
        "active_claude_task": summary["active_claude_task"],
        "active_codex_task": summary["active_codex_task"],
        "last_completed_fix": summary["last_completed_fix"],
        "next_fix": summary["next_fix"],
        "blockers_simple": summary["blockers_simple"],
        "blockers_technical": summary["blockers_technical"],
        "page_cards": cards,
        "stale_payloads": stale,
        "missing_payloads": missing,
        "source_status": status,
        "evidence_paths": {
            "migration_contract": "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
            "router_status": "v2/frontend/public/permanent_migration_runtime/latest/router_status.json",
            "shutdown_matrix": "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json",
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Frontend truth payload builder")
    p.add_argument("--dry-run", action="store_true", help="Print payload without writing.")
    p.add_argument("--out", type=Path, default=OUTPUT_PATH, help="Output path override.")
    args = p.parse_args(argv)

    payload = build_payload()

    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"frontend_truth_payload_written path={args.out} live_gate={payload['live_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
