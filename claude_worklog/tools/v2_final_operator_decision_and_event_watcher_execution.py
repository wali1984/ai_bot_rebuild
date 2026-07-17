"""Generate final operator-decision and event-watcher execution artifacts.

This packet turns the final blocker sprint into operational decision/watch
surfaces. It does not approve live, canary, legacy shutdown, Redis trim, or
exchange mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "claude_worklog/final_readiness/"
    "v2_final_production_equivalence_blocker_resolution_sprint/latest"
)
OUT = (
    ROOT
    / "claude_worklog/final_readiness/"
    "v2_final_operator_decision_and_event_watcher_execution/latest"
)
PUBLIC = (
    ROOT
    / "v2/frontend/public/"
    "v2_final_operator_decision_and_event_watcher_execution/latest"
)

SAFETY = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
    "creates_approval_tokens": False,
    "fabricates_edge": False,
    "fabricates_missing_observations": False,
    "modifies_legacy_repo": False,
}

ALLOWED_RECOMMENDATIONS = {
    "SAFE_TO_SHUTDOWN_LEGACY_FOR_V2_PAPER_ONLY",
    "OPERATOR_DECISION_REQUIRED_BEFORE_LEGACY_SHUTDOWN",
    "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE",
}

SOURCE_ENV_NAMES = {
    # santiment removed by operator directive 2026-07-16.
    "onchain_btc": ("GLASSNODE_API_KEY", "CRYPTOQUANT_API_KEY"),
    "onchain_eth": ("GLASSNODE_API_KEY", "CRYPTOQUANT_API_KEY"),
    "unified_feature_family.token_metrics": ("TOKENMETRICS_API_KEY", "TM_API_KEY"),
}
FREE_TIER_CONFIRM_ENV_NAMES = (
    "V2_EXTERNAL_SOURCE_FREE_TIER_CONFIRMED",
    "V2_EXTERNAL_SOURCE_CODEX_SAFE_CONFIRMED",
)
TASK_MIRROR_DIR = (
    ROOT / "claude_worklog/final_readiness/v2_closed_loop_execution/latest/tasks"
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def env_name_present(name: str) -> bool:
    """Return presence only; do not read, print, or persist env var values."""
    return name in os.environ


def safe_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def load_inputs() -> dict[str, Any]:
    inputs = {
        "operator_packet": read_json(SOURCE / "final_operator_decision_packet.json"),
        "external_packet": read_json(SOURCE / "external_source_decision_packet.json"),
        "event_watchers": read_json(SOURCE / "event_dependent_watchers_status.json"),
        "sprint_status": read_json(SOURCE / "operator_dashboard_payload.json"),
        "sprint_recommendation": read_json(SOURCE / "final_production_equivalence_recommendation.json"),
    }
    missing = [name for name, payload in inputs.items() if not isinstance(payload, dict)]
    if missing:
        raise SystemExit(f"missing required sprint inputs: {', '.join(missing)}")
    return inputs


def decision_label(blocker_id: str) -> str:
    if blocker_id == "checkpoint_promotion":
        return "checkpoint/model limitation"
    if blocker_id == "risk_caps_canary_hard_gates_unset":
        return "risk/capital caps"
    if blocker_id == "legacy_shutdown.legacy_runtime_owner":
        return "legacy runtime stop acceptance"
    if blocker_id == "legacy_shutdown.legacy_redis_keys_active":
        return "legacy Redis trim / retention decision"
    if blocker_id == "capital_recovery_gate_unset":
        return "capital recovery threshold / risk guard acceptance"
    if blocker_id == "full_observation_builder.operator_decision_families":
        return "paper-edge threshold and unified-feature acceptance"
    return "operator decision"


def build_operator_decision_center(operator_packet: dict[str, Any]) -> tuple[dict[str, Any], str]:
    decisions: list[dict[str, Any]] = []
    for item in operator_packet.get("items", []):
        if not isinstance(item, dict):
            continue
        blocker_id = str(item.get("blocker_id"))
        decisions.append(
            {
                "blocker_id": blocker_id,
                "decision_label": decision_label(blocker_id),
                "current_status": "PENDING_OPERATOR_DECISION",
                "why_it_blocks_shutdown_live": item.get("current_risk")
                or "Shutdown/live remain blocked until operator decision is explicit.",
                "option_A_accept_for_paper_only_shutdown": {
                    "description": "Accept the documented limitation for paper-only shutdown evaluation only.",
                    "operator_accepted": False,
                },
                "option_B_require_implementation_before_shutdown": {
                    "description": "Require implementation or stronger evidence before shutdown.",
                    "operator_accepted": False,
                },
                "option_C_defer_and_keep_legacy_running": {
                    "description": "Defer this blocker and keep legacy running.",
                    "operator_accepted": False,
                },
                "recommended_conservative_default": item.get("recommended_conservative_default")
                or "option_C_defer_and_keep_legacy_running",
                "risk_if_accepted": "Paper-only shutdown could proceed with an explicitly accepted limitation, but live/canary remain blocked.",
                "risk_if_deferred": "Legacy remains running and V2 production-equivalence remains incomplete.",
                "operator_accepted": False,
                "operator_selected_option": None,
                "approval_artifact_present": False,
                "creates_approval_token": False,
            }
        )
    center = {
        "schema_version": "v2_final_operator_decision_center_v1",
        "generated_utc": utc_iso(),
        "operator_decision_count": len(decisions),
        "operator_accepted_count": 0,
        "operator_selected_count": 0,
        "decisions": decisions,
        "creates_approval_tokens": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "safety": SAFETY,
    }
    lines = [
        "# Final Operator Decision Center",
        "",
        "This surface records required decisions only. It does not approve live, canary, legacy shutdown, or Redis trim.",
        "",
        f"Pending operator decisions: {len(decisions)}",
        "",
    ]
    for decision in decisions:
        lines.extend(
            [
                f"## {decision['blocker_id']}",
                "",
                f"Decision: {decision['decision_label']}",
                "",
                f"Current status: {decision['current_status']}",
                "",
                f"Why it blocks shutdown/live: {decision['why_it_blocks_shutdown_live']}",
                "",
                f"Recommended conservative default: {decision['recommended_conservative_default']}",
                "",
                "operator_accepted=false",
                "operator_selected_option=null",
                "",
            ]
        )
    return center, "\n".join(lines).rstrip() + "\n"


def build_external_execution(external_packet: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in external_packet.get("items", []):
        if not isinstance(item, dict):
            continue
        family_rows = []
        present_any = False
        missing_any = False
        for family in item.get("source_families", []):
            names = SOURCE_ENV_NAMES.get(str(family), ())
            present_names = [name for name in names if env_name_present(name)]
            missing_names = [name for name in names if not env_name_present(name)]
            present_any = present_any or bool(present_names)
            missing_any = missing_any or bool(missing_names)
            family_rows.append(
                {
                    "source_family": family,
                    "env_var_names_checked": list(names),
                    "present_env_var_names": present_names,
                    "missing_env_var_names": missing_names,
                    "raw_values_read": False,
                    "raw_values_printed": False,
                }
            )
        free_tier_codex_safe = all(env_name_present(name) for name in FREE_TIER_CONFIRM_ENV_NAMES)
        if not present_any:
            classification = "SOURCE_MISSING_KEY_OPERATOR_REQUIRED"
        elif free_tier_codex_safe:
            classification = "SOURCE_READY_FREE_TIER"
        elif missing_any:
            classification = "SOURCE_READY_PAID_TIER_OPERATOR_REQUIRED"
        else:
            classification = "SOURCE_READY_PAID_TIER_OPERATOR_REQUIRED"
        seed_status = seed_external_source_task_if_safe(item.get("blocker_id"), classification)
        items.append(
            {
                "blocker_id": item.get("blocker_id"),
                "classification": classification,
                "source_requirement": item.get("source_requirement"),
                "family_key_presence": family_rows,
                "free_tier_confirmation_env_names": list(FREE_TIER_CONFIRM_ENV_NAMES),
                "free_tier_codex_safe_confirmed_by_env_name_presence": free_tier_codex_safe,
                "operator_accepted": False,
                "implementation_task_seeded": seed_status["seeded"],
                "implementation_task_id": seed_status.get("implementation_task_id"),
                "codex_review_task_id": seed_status.get("codex_review_task_id"),
                "implementation_task_seed_status": seed_status["status"],
                "implementation_task_seed_blocker": seed_status.get("blocker"),
                "free_path": item.get("free_path"),
                "paid_path": item.get("paid_path"),
                "defer_path": item.get("defer_path"),
                "raw_key_values_exposed": False,
            }
        )
    return {
        "schema_version": "v2_external_source_decision_execution_status_v1",
        "generated_utc": utc_iso(),
        "external_source_blocker_count": len(items),
        "items": items,
        "raw_key_values_exposed": False,
        "raw_values_read": False,
        "safety": SAFETY,
    }


def seed_external_source_task_if_safe(blocker_id: Any, classification: str) -> dict[str, Any]:
    if classification != "SOURCE_READY_FREE_TIER":
        return {
            "seeded": False,
            "status": "NOT_SEEDED_OPERATOR_OR_SOURCE_BLOCKED",
            "blocker": "OPERATOR_APPROVAL_REQUIRED_BEFORE_EXTERNAL_SOURCE_ADOPTION",
        }
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore

    blocker = safe_id(str(blocker_id or "external_source"))
    impl_id = f"final_external_source_free_tier_impl_{blocker}"
    codex_id = f"codex_review_{impl_id}"
    lock_group = f"external_source_free_tier_{blocker}"
    safe_envelope = {
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    impl_task = {
        "task_id": impl_id,
        "task_type": "CLAUDE_IMPLEMENTATION",
        "lane_type": "CLAUDE_IMPLEMENTATION",
        "mission_category": "observation_completeness",
        "lane_group": "proof-claude",
        "owner": "CLAUDE",
        "agent": "claude",
        "status": "pending",
        "file_lock_group": lock_group,
        "paired_task_id": codex_id,
        "safe_envelope": safe_envelope,
        "scope_paths": [
            "v2/backend/app/services",
            "claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution",
        ],
        "prompt": (
            "Implement the free-tier external-source V2 observation adapter for "
            f"{blocker_id}. Do not read or print raw secret values. Do not write "
            "old Redis. Do not call exchange mutation. live_gate=blocked_human_only "
            "and live_symbols=[] must remain."
        ),
    }
    codex_task = {
        "task_id": codex_id,
        "task_type": "CODEX_REVIEW",
        "lane_type": "CODEX_REVIEW",
        "mission_category": "observation_completeness",
        "lane_group": "proof-codex",
        "owner": "CODEX",
        "agent": "codex",
        "status": "pending",
        "file_lock_group": lock_group,
        "paired_task_id": impl_id,
        "depends_on_task_id": impl_id,
        "safe_envelope": safe_envelope,
        "scope_paths": [
            "claude_worklog/final_readiness/v2_final_operator_decision_and_event_watcher_execution"
        ],
        "prompt": (
            "Review the free-tier external-source V2 observation adapter. Fail on "
            "raw key exposure, old Redis writes, exchange mutation, approval drift, "
            "fake observation data, or live_symbols mutation."
        ),
    }
    store = SQLiteLeaseStore()
    try:
        existing_impl = store.get_task(impl_id)
        existing_codex = store.get_task(codex_id)
        if existing_impl or existing_codex:
            return {
                "seeded": False,
                "status": "EXISTING_TASK_REFERENCED",
                "implementation_task_id": impl_id,
                "codex_review_task_id": codex_id,
            }
        store.create_task(impl_task, status="pending")
        store.create_task(codex_task, status="pending")
    finally:
        store.close()
    TASK_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    (TASK_MIRROR_DIR / f"{impl_id}.json").write_text(
        json.dumps(impl_task, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (TASK_MIRROR_DIR / f"{codex_id}.json").write_text(
        json.dumps(codex_task, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "seeded": True,
        "status": "NEW_PAIRED_TASKS_SEEDED",
        "implementation_task_id": impl_id,
        "codex_review_task_id": codex_id,
    }


def freshness_from_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("generated_utc", "generated_at", "generated"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return None


def build_liquidation_watcher(spec: dict[str, Any]) -> dict[str, Any]:
    source_path = ROOT / "v2/frontend/public/v2_per_symbol_liquidation_source/latest/operator_dashboard_payload.json"
    burndown_path = (
        ROOT
        / "v2/frontend/public/v2_full_observation_liquidation_burndown/latest/"
        "liquidation_aggregator_status.json"
    )
    source = read_json(source_path) or {}
    burndown = read_json(burndown_path) or {}
    populated = int(source.get("symbols_with_any_v2_liquidation_key_populated_count") or 0)
    aggregator_available = bool(burndown.get("v2_liquidation_aggregator_per_symbol_source_available"))
    complete = populated > 0 and aggregator_available and source.get("no_synthetic_liquidation_events") is True
    return {
        "watcher_id": "event_watcher_1_liquidation_source",
        "blocker_id": spec.get("blocker_id"),
        "exact_event_source_required": spec.get("event_or_source_required"),
        "redis_key_or_public_payload_watched": [
            "v2:market:liquidations:latest:{symbol}",
            "v2/frontend/public/v2_per_symbol_liquidation_source/latest/operator_dashboard_payload.json",
            "v2/frontend/public/v2_full_observation_liquidation_burndown/latest/liquidation_aggregator_status.json",
        ],
        "current_observed_state": "REAL_EVENT_OBSERVED" if complete else "WAITING_FOR_REAL_LIQUIDATION_EVENT_OR_SOURCE",
        "last_observed_at": freshness_from_payload(source) or freshness_from_payload(burndown),
        "observed_evidence": {
            "symbols_with_any_v2_liquidation_key_populated_count": populated,
            "v2_liquidation_aggregator_per_symbol_source_available": aggregator_available,
            "no_synthetic_liquidation_events": source.get("no_synthetic_liquidation_events"),
        },
        "pass_condition": spec.get("pass_condition"),
        "pass_condition_satisfied": complete,
        "fail_condition": "source missing, stale, or synthetic; keep blocker open",
        "timeout_escalation": spec.get("timeout_escalation"),
        "fake_completion_allowed": False,
        "completed": complete,
    }


def build_paper_edge_watcher(spec: dict[str, Any]) -> dict[str, Any]:
    miner_path = ROOT / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json"
    war_room_path = ROOT / "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/war_room_status.json"
    miner = read_json(miner_path) or {}
    war_room = read_json(war_room_path) or {}
    metric = miner.get("evaluator_metric_summary") if isinstance(miner.get("evaluator_metric_summary"), dict) else {}
    edge_summary = war_room.get("edge_gate_summary") if isinstance(war_room.get("edge_gate_summary"), dict) else {}
    edge_claimed = bool(edge_summary.get("edge_claimed")) or metric.get("verdict") == "EDGE_CLAIMED"
    complete = edge_claimed and miner.get("no_fabricated_outcomes") is True
    return {
        "watcher_id": "event_watcher_2_paper_edge_evidence",
        "blocker_id": spec.get("blocker_id"),
        "exact_event_source_required": spec.get("event_or_source_required"),
        "redis_key_or_public_payload_watched": [
            "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json",
            "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/war_room_status.json",
        ],
        "current_observed_state": "EDGE_PROVEN" if complete else "WAITING_FOR_EDGE_PROOF_AND_OPERATOR_THRESHOLDS",
        "last_observed_at": freshness_from_payload(miner) or freshness_from_payload(war_room),
        "observed_evidence": {
            "edge_claimed": bool(edge_summary.get("edge_claimed")),
            "edge_claim_blocked_reason": edge_summary.get("edge_claim_blocked_reason"),
            "miner_verdict": metric.get("verdict"),
            "expected_move_after_cost_bps": metric.get("expected_move_after_cost_bps"),
            "after_cost_ci_lower_bps": metric.get("after_cost_ci_lower_bps"),
            "minimum_sample_satisfied": metric.get("minimum_sample_satisfied"),
            "no_fabricated_outcomes": miner.get("no_fabricated_outcomes"),
        },
        "pass_condition": spec.get("pass_condition"),
        "pass_condition_satisfied": complete,
        "fail_condition": "thresholds missing, negative after-cost evidence, insufficient sample, or fabricated outcome",
        "timeout_escalation": spec.get("timeout_escalation"),
        "fake_completion_allowed": False,
        "completed": complete,
    }


def build_event_runtime(event_specs: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    watchers: list[dict[str, Any]] = []
    for spec in event_specs.get("watchers", []):
        if not isinstance(spec, dict):
            continue
        if spec.get("blocker_id") == "full_observation_builder.event_dependent":
            watchers.append(build_liquidation_watcher(spec))
        elif spec.get("blocker_id") == "paper_edge_not_proven":
            watchers.append(build_paper_edge_watcher(spec))
    runtime = {
        "schema_version": "v2_event_dependent_watcher_runtime_status_v1",
        "generated_utc": utc_iso(),
        "event_watcher_count": len(watchers),
        "active_watcher_count": len(watchers),
        "completed_watcher_count": sum(1 for watcher in watchers if watcher.get("completed")),
        "fake_completion_allowed": False,
        "watchers": watchers,
        "safety": SAFETY,
    }
    return runtime, watchers


def build_final_recommendation(
    decision_center: dict[str, Any],
    external_status: dict[str, Any],
    watcher_runtime: dict[str, Any],
) -> dict[str, Any]:
    remaining_operator = [
        item["blocker_id"]
        for item in decision_center.get("decisions", [])
        if not item.get("operator_accepted")
    ]
    remaining_external = [
        item["blocker_id"]
        for item in external_status.get("items", [])
        if item.get("classification") not in ("SOURCE_DEFERRED", "SOURCE_NOT_REQUIRED_FOR_PAPER_ONLY")
    ]
    remaining_event = [
        item["blocker_id"]
        for item in watcher_runtime.get("watchers", [])
        if not item.get("completed")
    ]
    remaining_technical: list[str] = []
    if remaining_external or remaining_event:
        recommendation = "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE"
        decision_ready = False
    elif remaining_operator:
        recommendation = "OPERATOR_DECISION_REQUIRED_BEFORE_LEGACY_SHUTDOWN"
        decision_ready = True
    else:
        recommendation = "SAFE_TO_SHUTDOWN_LEGACY_FOR_V2_PAPER_ONLY"
        decision_ready = True
    assert recommendation in ALLOWED_RECOMMENDATIONS
    if recommendation == "SAFE_TO_SHUTDOWN_LEGACY_FOR_V2_PAPER_ONLY":
        # This packet is not allowed to create approvals; fail closed.
        recommendation = "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE"
        decision_ready = False
    return {
        "schema_version": "v2_final_operator_event_shutdown_recommendation_v1",
        "generated_utc": utc_iso(),
        "production_equivalence_ready": False,
        "paper_only_shutdown_decision_ready": decision_ready,
        "live_ready": False,
        "canary_ready": False,
        "remaining_operator_blockers": remaining_operator,
        "remaining_external_blockers": remaining_external,
        "remaining_event_blockers": remaining_event,
        "remaining_technical_blockers": remaining_technical,
        "shutdown_safe": False,
        "final_recommendation": recommendation,
        "safe_to_shutdown_requires_operator_acceptance_and_codex_verification": True,
        "reason": (
            "Operator decisions are pending and event/external evidence is not resolved; "
            "legacy shutdown remains blocked."
        ),
        "safety": SAFETY,
    }


def write_report(status: dict[str, Any]) -> None:
    report = f"""# V2 Final Operator Decision and Event Watcher Execution

GO/NO-GO: {status['go_no_go']}

This packet makes the remaining final blockers operationally visible. It does
not approve live trading, canary, legacy shutdown, Redis trim, or exchange
mutation.

## Summary

- operator_decision_count: {status['operator_decision_count']}
- operator_accepted_count: {status['operator_accepted_count']}
- external_source_state: {status['external_source_state']}
- event_watcher_count: {status['event_watcher_count']}
- event_watchers_completed: {status['event_watchers_completed']}
- final_recommendation: {status['final_recommendation']}

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false

## Current Truth

Migration is not complete. Legacy shutdown and live trading remain blocked.
Operator decisions are explicit and unaccepted, external-source adoption is
operator-gated, and event-dependent watchers do not mark completion without
real evidence.
"""
    (OUT / "V2_FINAL_OPERATOR_DECISION_AND_EVENT_WATCHER_EXECUTION_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_once() -> dict[str, Any]:
    inputs = load_inputs()
    decision_center, decision_md = build_operator_decision_center(inputs["operator_packet"])
    external_status = build_external_execution(inputs["external_packet"])
    watcher_runtime, watchers = build_event_runtime(inputs["event_watchers"])
    recommendation = build_final_recommendation(decision_center, external_status, watcher_runtime)

    external_states = sorted({item["classification"] for item in external_status.get("items", [])})
    go_no_go = "V2_FINAL_OPERATOR_DECISION_AND_EVENT_WATCHER_EXECUTION_READY"
    status = {
        "schema_version": "v2_final_operator_decision_event_watcher_execution_status_v1",
        "generated_utc": utc_iso(),
        "go_no_go": go_no_go,
        "ready": True,
        "migration_complete": False,
        "legacy_shutdown_ready": False,
        "live_ready": False,
        "paper_edge_proven": False,
        "operator_decision_count": decision_center["operator_decision_count"],
        "operator_accepted_count": decision_center["operator_accepted_count"],
        "operator_decisions_pending": [
            item["blocker_id"] for item in decision_center.get("decisions", [])
        ],
        "external_source_state": ",".join(external_states) if external_states else "NO_EXTERNAL_BLOCKER",
        "event_watcher_count": watcher_runtime["event_watcher_count"],
        "event_watchers_completed": watcher_runtime["completed_watcher_count"],
        "final_recommendation": recommendation["final_recommendation"],
        "next_action": "OPERATOR_DECISION_OR_WAIT_FOR_WATCHER_EVIDENCE",
        "safety": SAFETY,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "final_operator_decision_center.json", decision_center)
    (OUT / "FINAL_OPERATOR_DECISION_CENTER.md").write_text(decision_md, encoding="utf-8")
    write_json(OUT / "external_source_decision_execution_status.json", external_status)
    write_json(OUT / "event_dependent_watcher_runtime_status.json", watcher_runtime)
    for idx, watcher in enumerate(watchers, start=1):
        write_json(OUT / f"event_watcher_{idx}_status.json", watcher)
    write_json(OUT / "final_shutdown_recommendation.json", recommendation)
    write_json(OUT / "operator_dashboard_payload.json", status)
    (OUT / "GO_NO_GO.md").write_text(go_no_go + "\n", encoding="utf-8")
    write_report(status)

    for file in OUT.glob("*.json"):
        shutil.copy2(file, PUBLIC / file.name)
    for file in (
        OUT / "GO_NO_GO.md",
        OUT / "FINAL_OPERATOR_DECISION_CENTER.md",
        OUT / "V2_FINAL_OPERATOR_DECISION_AND_EVENT_WATCHER_EXECUTION_REPORT.md",
    ):
        shutil.copy2(file, PUBLIC / file.name)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = run_once()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
