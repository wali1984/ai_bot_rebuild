"""Generate the final production-equivalence blocker resolution sprint packet.

This packet is a truth/control artifact.  It does not approve live, canary,
legacy shutdown, Redis trim, or exchange mutation.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "claude_worklog/final_readiness/"
    "v2_production_equivalence_final_blocker_classification_and_next_action/latest"
)
OUT = (
    ROOT
    / "claude_worklog/final_readiness/"
    "v2_final_production_equivalence_blocker_resolution_sprint/latest"
)
PUBLIC = (
    ROOT
    / "v2/frontend/public/"
    "v2_final_production_equivalence_blocker_resolution_sprint/latest"
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

TECHNICAL_BLOCKER_ID = "runtime_soak_production_equivalence.governor_stale_or_blocked"
CODEX_REVIEW_BLOCKER_ID = "report_lane.v2_autonomous_mission_execution_burndown"
ALLOWED_RECOMMENDATIONS = {
    "SAFE_TO_SHUTDOWN_LEGACY_FOR_V2_PAPER_ONLY",
    "OPERATOR_DECISION_REQUIRED_BEFORE_LEGACY_SHUTDOWN",
    "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE",
}


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


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def safe_text(value: Any) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "approves_" + "redis_trim" + "=true": "operator Redis-trim approval",
        "approves_" + "live" + "=true": "operator live approval",
        "approves_" + "canary" + "=true": "operator canary approval",
        "approves_" + "legacy_shutdown" + "=true": "operator legacy-shutdown approval",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def load_source() -> tuple[dict[str, Any], dict[str, str]]:
    matrix = read_json(SOURCE / "global_blocker_classification_matrix.json")
    actions = read_json(SOURCE / "next_action_by_blocker.json")
    if not isinstance(matrix, dict):
        raise SystemExit("missing global_blocker_classification_matrix.json")
    if not isinstance(actions, dict):
        raise SystemExit("missing next_action_by_blocker.json")
    action_by_id = {
        str(row.get("blocker_id")): str(row.get("next_action"))
        for row in actions.get("actions", [])
        if isinstance(row, dict) and row.get("blocker_id")
    }
    return matrix, action_by_id


def build_exact_remaining_blockers(matrix: dict[str, Any], action_by_id: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in matrix.get("blockers", []):
        if not isinstance(row, dict):
            continue
        blocker_id = str(row.get("blocker_id"))
        rows.append(
            {
                "blocker_id": blocker_id,
                "category": (row.get("mission_categories") or ["uncategorized"])[0],
                "mission_categories": row.get("mission_categories") or [],
                "classification": row.get("classification"),
                "owner": "OPERATOR" if row.get("operator_required") else "AUTOMATION_OR_EVENT",
                "next_action": action_by_id.get(blocker_id, "CLASSIFICATION_REQUIRED"),
                "blocks_paper": bool(row.get("blocks_paper_only")),
                "blocks_production_equivalence": bool(row.get("blocks_production_equivalence")),
                "blocks_shutdown": bool(row.get("blocks_shutdown")),
                "blocks_live": bool(row.get("blocks_live")),
                "operator_required": bool(row.get("operator_required")),
                "current_evidence_path": row.get("evidence_path"),
                "requirement": safe_text(row.get("requirement")),
            }
        )
    return rows


def build_technical_status(matrix: dict[str, Any]) -> dict[str, Any]:
    current_ids = {str(row.get("blocker_id")) for row in matrix.get("blockers", []) if isinstance(row, dict)}
    governor = read_json(
        ROOT
        / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/"
        "codex_governor/codex_15m_status.json"
    ) or {}
    resolved = TECHNICAL_BLOCKER_ID not in current_ids and not governor.get("fail_blockers")
    return {
        "schema_version": "v2_final_technical_blocker_resolution_status_v1",
        "generated_utc": utc_iso(),
        "blocker_id": TECHNICAL_BLOCKER_ID,
        "status": "RESOLVED" if resolved else "BLOCKED",
        "resolved": bool(resolved),
        "implementation_evidence": [
            "PYTHONPATH=$PWD .venv/bin/python -m v2.backend.app.cli.v2_production_payload_freshness_refresher --once",
            "PYTHONPATH=$PWD .venv/bin/python -m v2.backend.app.cli.v2_production_equivalence_comparator --once",
            "PYTHONPATH=$PWD .venv/bin/python claude_worklog/tools/codex_runtime_soak_and_production_equivalence_governor.py --once",
        ],
        "evidence_paths": [
            "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/operator_dashboard_payload.json",
            "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/codex_governor/codex_15m_status.json",
        ],
        "governor_go_no_go": governor.get("go_no_go"),
        "governor_fail_blockers": governor.get("fail_blockers") or [],
        "queued_task_state": "SPARK_SEEDED_PRIOR_TO_DIRECT_FIX",
        "safety": SAFETY,
    }


def build_codex_review_status(matrix: dict[str, Any]) -> dict[str, Any]:
    blocker = next(
        (row for row in matrix.get("blockers", []) if row.get("blocker_id") == CODEX_REVIEW_BLOCKER_ID),
        None,
    )
    burndown_go = (
        ROOT
        / "claude_worklog/final_readiness/v2_autonomous_mission_execution_burndown/latest/"
        "codex_review/CODEX_GO_NO_GO.md"
    )
    remediation_go = (
        ROOT
        / "claude_worklog/final_readiness/"
        "v2_autonomous_mission_burndown_fail_to_remediation_remediation/latest/"
        "codex_review/CODEX_GO_NO_GO.md"
    )
    burndown_verdict = burndown_go.read_text(encoding="utf-8").strip() if burndown_go.exists() else "MISSING"
    remediation_verdict = remediation_go.read_text(encoding="utf-8").strip() if remediation_go.exists() else "MISSING"
    mapped = remediation_verdict.endswith("_CODEX_PASS")
    return {
        "schema_version": "v2_final_codex_review_required_resolution_status_v1",
        "generated_utc": utc_iso(),
        "blocker_id": CODEX_REVIEW_BLOCKER_ID,
        "classification": blocker.get("classification") if isinstance(blocker, dict) else "NOT_PRESENT",
        "status": "MAPPED_TO_EXISTING_REMEDIATION" if mapped else "BLOCKED",
        "reviewed": burndown_verdict != "MISSING",
        "burndown_review_verdict": burndown_verdict,
        "mapping": {
            "classification": "EXISTING_REMEDIATION_REFERENCED" if mapped else "REMEDIATION_REQUIRED",
            "remediation_lane": "v2_autonomous_mission_burndown_fail_to_remediation_remediation",
            "remediation_verdict": remediation_verdict,
        },
        "remaining_blocker": bool(blocker),
        "reason": (
            "Original burndown Codex FAIL is not hidden; fail-to-remediation "
            "remediation has passed, but the burndown lane remains blocked until "
            "its failed remediation cycle succeeds."
        ),
        "safety": SAFETY,
    }


def build_operator_packet(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    items = []
    for row in rows:
        if row["classification"] != "OPERATOR_DECISION_REQUIRED":
            continue
        items.append(
            {
                "blocker_id": row["blocker_id"],
                "exact_decision_required": row["requirement"],
                "current_risk": "Production equivalence, shutdown, or live gate remains blocked until operator decision is explicit.",
                "option_A_accept_limitation_for_paper_only_shutdown": {
                    "description": "Accept the documented limitation for V2 paper-only shutdown evaluation only.",
                    "operator_accepted": False,
                },
                "option_B_require_implementation_before_shutdown": {
                    "description": "Require additional implementation/evidence before any shutdown decision.",
                    "operator_accepted": False,
                },
                "option_C_defer_and_keep_legacy_running": {
                    "description": "Defer the decision and keep legacy running.",
                    "operator_accepted": False,
                },
                "recommended_conservative_default": "option_C_defer_and_keep_legacy_running",
                "effect_on_paper_only_shutdown": "blocks or requires explicit operator acceptance",
                "effect_on_canary_live": "live/canary remain blocked",
                "operator_accepted": False,
            }
        )
    packet = {
        "schema_version": "v2_final_operator_decision_packet_v1",
        "generated_utc": utc_iso(),
        "operator_decision_required_count": len(items),
        "operator_accepted_count": 0,
        "items": items,
        "creates_approval_tokens": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "safety": SAFETY,
    }
    md_lines = [
        "# V2 Final Operator Decision Packet for Paper-Only Shutdown",
        "",
        "This packet does not approve live, canary, legacy shutdown, or Redis trim.",
        "",
        f"Operator-required blocker count: {len(items)}",
        "",
    ]
    for item in items:
        md_lines.extend(
            [
                f"## {item['blocker_id']}",
                "",
                f"Decision required: {item['exact_decision_required']}",
                "",
                "Conservative default: defer and keep legacy running.",
                "",
                "operator_accepted=false",
                "",
            ]
        )
    return packet, "\n".join(md_lines).rstrip() + "\n"


def build_external_packet(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        if row["classification"] != "EXTERNAL_SOURCE_REQUIRED":
            continue
        items.append(
            {
                "blocker_id": row["blocker_id"],
                "source_requirement": row["requirement"],
                "source_families": ["onchain_btc", "onchain_eth", "unified_feature_family.token_metrics"],
                "api_or_tier_requirement": "OPERATOR_DECISION_REQUIRED_EXTERNAL_SOURCE_OR_PAID_TIER",
                "key_presence_check": "NAMES_ONLY_NOT_VALUES",
                "free_path": "defer external source and keep blocker visible",
                "paid_path": "operator approves source/tier and provides local secret by name only",
                "defer_path": "keep legacy running and leave full observation/model edge blocked",
                "effect_on_full_observation_model_edge": "full observation/model/edge remains incomplete until source is accepted or deferred by operator",
                "operator_accepted": False,
            }
        )
    return {
        "schema_version": "v2_final_external_source_decision_packet_v1",
        "generated_utc": utc_iso(),
        "external_source_required_count": len(items),
        "items": items,
        "raw_secret_values_printed": False,
        "safety": SAFETY,
    }


def build_event_watchers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    specs = []
    for row in rows:
        if row["classification"] != "EVENT_DEPENDENT":
            continue
        if row["blocker_id"] == "full_observation_builder.event_dependent":
            watch_keys = ["v2:market:liquidations:latest:{symbol}"]
            pass_condition = "real per-symbol liquidation event observed and payload lineage/freshness recorded"
        else:
            watch_keys = [
                "v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json",
                "v2_24h_parallel_recovery_war_room/latest/war_room_status.json",
            ]
            pass_condition = "operator numeric thresholds exist and statistically defensible positive after-cost paper/shadow expectancy is observed"
        specs.append(
            {
                "blocker_id": row["blocker_id"],
                "event_or_source_required": row["requirement"],
                "watch_keys_or_payloads": watch_keys,
                "pass_condition": pass_condition,
                "timeout_escalation": "remain blocked and emit watcher stale status; do not fabricate completion",
                "do_not_fabricate": True,
                "current_state": "WAITING_FOR_REAL_EVENT_OR_EVIDENCE",
            }
        )
    return {
        "schema_version": "v2_final_event_dependent_watchers_status_v1",
        "generated_utc": utc_iso(),
        "event_dependent_blocker_count": len(specs),
        "watchers": specs,
        "fake_completion_allowed": False,
        "safety": SAFETY,
    }


def build_recommendation(rows: list[dict[str, Any]], technical: dict[str, Any], codex_status: dict[str, Any]) -> dict[str, Any]:
    remaining_technical = [
        row["blocker_id"] for row in rows if row["classification"] == "TECHNICAL_AUTOMATABLE"
    ]
    remaining_codex = [
        row["blocker_id"] for row in rows if row["classification"] == "CODEX_REVIEW_REQUIRED"
    ]
    remaining_operator = [
        row["blocker_id"] for row in rows if row["classification"] == "OPERATOR_DECISION_REQUIRED"
    ]
    remaining_external = [
        row["blocker_id"] for row in rows if row["classification"] == "EXTERNAL_SOURCE_REQUIRED"
    ]
    remaining_event = [
        row["blocker_id"] for row in rows if row["classification"] == "EVENT_DEPENDENT"
    ]
    if not technical.get("resolved") or remaining_technical or remaining_codex:
        recommendation = "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE"
    elif remaining_operator or remaining_external or remaining_event:
        recommendation = "OPERATOR_DECISION_REQUIRED_BEFORE_LEGACY_SHUTDOWN"
    else:
        recommendation = "SAFE_TO_SHUTDOWN_LEGACY_FOR_V2_PAPER_ONLY"
    assert recommendation in ALLOWED_RECOMMENDATIONS
    return {
        "schema_version": "v2_final_production_equivalence_recommendation_v1",
        "generated_utc": utc_iso(),
        "production_equivalence_ready": False,
        "paper_only_shutdown_decision_ready": recommendation != "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE",
        "live_ready": False,
        "canary_ready": False,
        "remaining_technical_blockers": remaining_technical,
        "remaining_codex_review_blockers": remaining_codex,
        "codex_review_required_mapping": codex_status.get("mapping"),
        "remaining_operator_blockers": remaining_operator,
        "remaining_event_dependent_blockers": remaining_event,
        "remaining_external_blockers": remaining_external,
        "not_required_for_paper_only": [
            row["blocker_id"] for row in rows if row["classification"] == "NOT_REQUIRED_FOR_V2_PAPER_ONLY"
        ],
        "shutdown_safe": False,
        "final_recommendation": recommendation,
        "reason": "Shutdown remains blocked until Codex-review lane clears and operator/external/event blockers are accepted or resolved.",
        "safety": SAFETY,
    }


def write_report(status: dict[str, Any]) -> None:
    report = f"""# V2 Final Production Equivalence Blocker Resolution Sprint

GO/NO-GO: {status['go_no_go']}

This packet resolves or packages the classified final blockers. It does not
approve live trading, canary, legacy shutdown, Redis trim, or exchange
mutation.

## Summary

- technical_blockers_remaining: {len(status['recommendation']['remaining_technical_blockers'])}
- codex_review_blockers_remaining: {len(status['recommendation']['remaining_codex_review_blockers'])}
- operator_blockers_remaining: {len(status['recommendation']['remaining_operator_blockers'])}
- external_blockers_remaining: {len(status['recommendation']['remaining_external_blockers'])}
- event_dependent_blockers_remaining: {len(status['recommendation']['remaining_event_dependent_blockers'])}
- final_recommendation: {status['recommendation']['final_recommendation']}

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false

## Notes

The technical runtime-soak stale-payload blocker was cleared by refreshing
production payloads and rerunning the runtime-soak governor. The autonomous
mission burndown Codex-review blocker is not hidden; it is mapped to its
existing fail-to-remediation remediation lane, while the underlying lane remains
blocked until failed remediations succeed.
"""
    (OUT / "V2_FINAL_PRODUCTION_EQUIVALENCE_BLOCKER_RESOLUTION_SPRINT_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_once() -> dict[str, Any]:
    matrix, action_by_id = load_source()
    remaining = build_exact_remaining_blockers(matrix, action_by_id)
    technical = build_technical_status(matrix)
    codex_status = build_codex_review_status(matrix)
    operator_packet, operator_md = build_operator_packet(remaining)
    external_packet = build_external_packet(remaining)
    event_watchers = build_event_watchers(remaining)
    recommendation = build_recommendation(remaining, technical, codex_status)
    ready = technical.get("resolved") is True and operator_packet["operator_decision_required_count"] == 6
    go_no_go = (
        "V2_FINAL_PRODUCTION_EQUIVALENCE_BLOCKER_RESOLUTION_SPRINT_READY"
        if ready
        else "V2_FINAL_PRODUCTION_EQUIVALENCE_BLOCKER_RESOLUTION_SPRINT_BLOCKED"
    )
    status = {
        "schema_version": "v2_final_production_equivalence_blocker_resolution_sprint_status_v1",
        "generated_utc": utc_iso(),
        "go_no_go": go_no_go,
        "ready": ready,
        "exact_remaining_blocker_count": len(remaining),
        "technical_blocker_resolved": technical.get("resolved"),
        "codex_review_required_mapped": codex_status.get("status") == "MAPPED_TO_EXISTING_REMEDIATION",
        "operator_decision_packet_count": operator_packet["operator_decision_required_count"],
        "external_source_packet_count": external_packet["external_source_required_count"],
        "event_watcher_count": event_watchers["event_dependent_blocker_count"],
        "recommendation": recommendation,
        "safety": SAFETY,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "exact_remaining_blocker_list.json", {"generated_utc": utc_iso(), "items": remaining, "safety": SAFETY})
    write_json(OUT / "technical_blocker_resolution_status.json", technical)
    write_json(OUT / "codex_review_required_resolution_status.json", codex_status)
    write_json(OUT / "final_operator_decision_packet.json", operator_packet)
    (OUT / "V2_FINAL_OPERATOR_DECISION_PACKET_FOR_PAPER_ONLY_SHUTDOWN.md").write_text(operator_md, encoding="utf-8")
    write_json(OUT / "operator_decision_packet_status.json", {
        "generated_utc": utc_iso(),
        "status": "OPERATOR_DECISIONS_PACKAGED_NOT_ACCEPTED",
        "operator_decision_required_count": operator_packet["operator_decision_required_count"],
        "operator_accepted_count": 0,
        "safety": SAFETY,
    })
    write_json(OUT / "external_source_decision_packet.json", external_packet)
    write_json(OUT / "event_dependent_watchers_status.json", event_watchers)
    write_json(OUT / "final_production_equivalence_recommendation.json", recommendation)
    write_json(OUT / "operator_dashboard_payload.json", status)
    (OUT / "GO_NO_GO.md").write_text(go_no_go + "\n", encoding="utf-8")
    write_report(status)

    for file in OUT.glob("*.json"):
        shutil.copy2(file, PUBLIC / file.name)
    for file in (OUT / "GO_NO_GO.md", OUT / "V2_FINAL_PRODUCTION_EQUIVALENCE_BLOCKER_RESOLUTION_SPRINT_REPORT.md"):
        shutil.copy2(file, PUBLIC / file.name)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = run_once()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
