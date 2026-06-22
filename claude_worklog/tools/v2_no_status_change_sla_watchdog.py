"""No-status-change SLA watchdog for the V2 migration control plane.

The watchdog records comparable snapshots, classifies a flat state as either a
legitimate wait or an automation failure, and seeds remediation through Spark
when the flat state is actionable.  It never treats idle workers or fresh
reports as migration progress by themselves.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from v2_autonomous_no_manual_next_task_policy import (  # noqa: E402
    CLASS_AUTOMATABLE,
    SAFE_ENVELOPE,
    seed_automatable_tasks,
)

LANE_ID = "v2_no_status_change_sla_watchdog"
GO_READY = "V2_NO_STATUS_CHANGE_SLA_WATCHDOG_READY"
GO_BLOCKED = "V2_NO_STATUS_CHANGE_SLA_WATCHDOG_BLOCKED"

WORKLOG_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / LANE_ID / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / LANE_ID / "latest"
SNAPSHOT_HISTORY = WORKLOG_DIR / "no_status_change_snapshot_history.jsonl"

REPORT_INDEX = REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json"
EXECUTIVE_PAYLOAD = REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "executive_status_payload.json"
NO_MANUAL_POLICY = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_no_manual_next_task_policy"
    / "latest"
    / "autonomous_no_manual_next_task_policy_status.json"
)
NO_MANUAL_CLASSIFICATION = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_no_manual_next_task_policy"
    / "latest"
    / "report_center_next_action_classification.json"
)
WORKER_POLICY = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_no_manual_next_task_policy"
    / "latest"
    / "worker_execution_policy_status.json"
)
FINAL_RECOMMENDATION = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_final_operator_decision_and_event_watcher_execution"
    / "latest"
    / "final_shutdown_recommendation.json"
)
EVENT_WATCHERS = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_final_operator_decision_and_event_watcher_execution"
    / "latest"
    / "event_dependent_watcher_runtime_status.json"
)
EXTERNAL_SOURCE = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_final_operator_decision_and_event_watcher_execution"
    / "latest"
    / "external_source_decision_execution_status.json"
)
EXTERNAL_SOURCE_RECONCILIATION = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_external_source_wait_credential_reconciliation"
    / "latest"
    / "operator_dashboard_payload.json"
)
OPERATOR_DECISIONS = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_final_operator_decision_and_event_watcher_execution"
    / "latest"
    / "final_operator_decision_center.json"
)
REPLAY_MINER = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_post_hoc_replay_outcome_miner"
    / "latest"
    / "post_hoc_replay_outcome_status.json"
)

ROOT_CAUSES = (
    "TRUE_OPERATOR_WAIT",
    "TRUE_EXTERNAL_SOURCE_WAIT",
    "TRUE_EVENT_DEPENDENT_WAIT",
    "TRUE_UNSAFE_TO_AUTOMATE",
    "AUTOMATION_STALE",
    "REPORT_CENTER_STALE",
    "REPLAY_MINER_STALE",
    "EVENT_WATCHER_STALE",
    "NEXT_ACTION_CLASSIFIER_STALE",
    "MISCLASSIFIED_AUTOMATABLE_WORK",
    "WORKER_POOL_IDLE_WITH_ELIGIBLE_WORK",
    "UNKNOWN_NO_CHANGE_FAILURE",
)

STALE_SECONDS = 30 * 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_seconds(value: str | None) -> float | None:
    ts = parse_iso(value)
    if ts is None:
        return None
    return max(0.0, (utc_now() - ts).total_seconds())


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def mirror_json(name: str, payload: dict[str, Any]) -> None:
    write_json(WORKLOG_DIR / name, payload)
    write_json(PUBLIC_DIR / name, payload)


def systemd_state(unit: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return (proc.stdout or "").strip() or f"exit_{proc.returncode}"
    except Exception as exc:  # noqa: BLE001
        return f"unknown:{type(exc).__name__}"


def collect_snapshot() -> dict[str, Any]:
    report = read_json(REPORT_INDEX, {})
    executive = read_json(EXECUTIVE_PAYLOAD, {})
    no_manual = read_json(NO_MANUAL_POLICY, {})
    no_manual_class = read_json(NO_MANUAL_CLASSIFICATION, {})
    worker = read_json(WORKER_POLICY, {})
    final = read_json(FINAL_RECOMMENDATION, {})
    watchers = read_json(EVENT_WATCHERS, {})
    external = read_json(EXTERNAL_SOURCE, {})
    external_reconciliation = read_json(EXTERNAL_SOURCE_RECONCILIATION, {})
    operator = read_json(OPERATOR_DECISIONS, {})
    replay = read_json(REPLAY_MINER, {})

    replay_metrics = replay.get("evaluator_metric_summary") or {}
    label_counts = replay.get("label_counts") or {}
    windows_filled = replay.get("windows_filled") or {}
    remaining_operator = final.get("remaining_operator_blockers") or []
    remaining_external = final.get("remaining_external_blockers") or []
    remaining_event = final.get("remaining_event_blockers") or []
    remaining_technical = final.get("remaining_technical_blockers") or []
    classification_counts = no_manual.get("classification_counts") or {}
    seed_status = no_manual.get("seed_status") or {}
    if isinstance(no_manual_class, list):
        classification_rows = no_manual_class
    elif isinstance(no_manual_class, dict):
        classification_rows = (
            no_manual_class.get("rows")
            or no_manual_class.get("classifications")
            or no_manual_class.get("items")
            or []
        )
    else:
        classification_rows = []
    disallowed_classification_count = sum(
        1
        for row in classification_rows
        if isinstance(row, dict) and row.get("allowed_classification") is False
    )

    watcher_rows = watchers.get("watchers") or []
    watcher_generated_at = watchers.get("generated_utc")
    last_observed_values = [
        row.get("last_observed_at")
        for row in watcher_rows
        if isinstance(row, dict) and row.get("last_observed_at")
    ]

    return {
        "snapshot_utc": utc_iso(),
        "production_score": executive.get("current_scorecard_overall_score"),
        "migration_complete": bool(final.get("production_equivalence_ready")),
        "shutdown_ready": bool(final.get("shutdown_safe")),
        "live_ready": bool(final.get("live_ready")),
        "canary_ready": bool(final.get("canary_ready")),
        "paper_edge_proven": bool(
            any(
                (row.get("observed_evidence") or {}).get("edge_claimed") is True
                for row in watcher_rows
                if isinstance(row, dict)
            )
        ),
        "report_center_blocked_count": int(report.get("blocked_count") or 0),
        "global_blocker_count": len(remaining_operator)
        + len(remaining_external)
        + len(remaining_event)
        + len(remaining_technical),
        "remaining_operator_blockers": remaining_operator,
        "remaining_external_blockers": remaining_external,
        "remaining_event_blockers": remaining_event,
        "remaining_technical_blockers": remaining_technical,
        "next_action_classification_counts": classification_counts,
        "disallowed_classification_count": disallowed_classification_count,
        "blocked_automatable_seed_count": int(seed_status.get("blocked_seed_count") or 0),
        "automatable_now_count": int(no_manual.get("automatable_now_count") or 0),
        "queue_empty_with_blockers_reason": no_manual.get("queue_empty_with_blockers_reason"),
        "replay_miner_sample_count": int(
            replay_metrics.get("sample_count") or replay.get("bundles_total") or 0
        ),
        "replay_miner_false_negative_count": int(label_counts.get("false_negative") or 0),
        "replay_miner_windows_filled": windows_filled,
        "replay_miner_expected_move_after_cost_bps": replay_metrics.get(
            "expected_move_after_cost_bps"
        ),
        "worker_active_leases": int(worker.get("active_leases") or 0),
        "worker_busy_workers": int(worker.get("busy_workers") or 0),
        "worker_queued_automatable_tasks": int(worker.get("queued_automatable_tasks") or 0),
        "task_completions_last_hour": int(worker.get("tasks_completed_last_hour") or 0),
        "implementation_completions_last_hour": int(
            worker.get("implementation_tasks_completed_last_hour") or 0
        ),
        "codex_reviews_last_hour": int(worker.get("Codex_reviews_completed_last_hour") or 0),
        "remediations_last_hour": int(worker.get("remediations_created_last_hour") or 0),
        "unmapped_codex_fail_count": int(worker.get("unmapped_codex_fail_count") or 0),
        "event_watcher_generated_at": watcher_generated_at,
        "event_watcher_last_observed_at_values": last_observed_values,
        "event_watcher_count": int(watchers.get("event_watcher_count") or 0),
        "event_watchers_completed": int(watchers.get("completed_watcher_count") or 0),
        "external_source_state": [
            {
                "blocker_id": item.get("blocker_id"),
                "classification": item.get("classification"),
                "implementation_task_seed_status": item.get("implementation_task_seed_status"),
                "missing_env_var_names": sorted(
                    {
                        name
                        for family in item.get("family_key_presence", [])
                        for name in family.get("missing_env_var_names", [])
                    }
                ),
            }
            for item in external.get("items", [])
            if isinstance(item, dict)
        ],
        "external_source_reconciliation": {
            "generated_utc": external_reconciliation.get("generated_utc"),
            "go_no_go": external_reconciliation.get("go_no_go"),
            "alias_mappings_checked": bool(external_reconciliation.get("alias_mappings_checked")),
            "providers_with_key_present_client_missing": external_reconciliation.get(
                "providers_with_key_present_client_missing"
            )
            or [],
            "seeded_or_referenced_count": int(
                external_reconciliation.get("seeded_or_referenced_count") or 0
            ),
            "raw_values_read": bool(external_reconciliation.get("raw_values_read")),
            "raw_key_values_exposed": bool(external_reconciliation.get("raw_key_values_exposed")),
        },
        "operator_decision_count": int(operator.get("operator_decision_count") or 0),
        "operator_accepted_count": int(operator.get("operator_accepted_count") or 0),
        "report_center_generated_at": report.get("generated_at"),
        "executive_generated_at": executive.get("generated_at"),
        "no_manual_generated_at": no_manual.get("generated_utc"),
        "replay_miner_generated_at": replay.get("generated_at"),
        "external_source_generated_at": external.get("generated_utc"),
        "operator_decision_generated_at": operator.get("generated_utc"),
        "systemd_units": {
            "report_center": systemd_state("ai-bot-v2-report-center-indexer.timer"),
            "replay_miner": systemd_state("ai-bot-v2-post-hoc-replay-outcome-miner.timer"),
            "spark_worker_pool": systemd_state("ai-bot-v2-closed-loop-worker-pool.timer"),
            "codex_governor": systemd_state(
                "ai-bot-codex-runtime-soak-production-equivalence-governor.timer"
            ),
            "event_watcher": systemd_state(
                "ai-bot-v2-final-operator-decision-event-watcher.timer"
            ),
            "no_manual_policy": systemd_state(
                "ai-bot-v2-autonomous-no-manual-next-task-policy.timer"
            ),
        },
        "safety": {
            **SAFE_ENVELOPE,
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "writes_old_redis": False,
            "calls_exchange_mutation": False,
            "creates_approval_tokens": False,
        },
    }


def comparable_key(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "production_score": snapshot.get("production_score"),
        "migration_complete": snapshot.get("migration_complete"),
        "shutdown_ready": snapshot.get("shutdown_ready"),
        "live_ready": snapshot.get("live_ready"),
        "paper_edge_proven": snapshot.get("paper_edge_proven"),
        "global_blocker_count": snapshot.get("global_blocker_count"),
        "report_center_blocked_count": snapshot.get("report_center_blocked_count"),
        "next_action_classification_counts": snapshot.get("next_action_classification_counts"),
        "disallowed_classification_count": int(snapshot.get("disallowed_classification_count") or 0),
        "blocked_automatable_seed_count": int(snapshot.get("blocked_automatable_seed_count") or 0),
        "replay_miner_sample_count": snapshot.get("replay_miner_sample_count"),
        "replay_miner_false_negative_count": snapshot.get("replay_miner_false_negative_count"),
        "replay_miner_windows_filled": snapshot.get("replay_miner_windows_filled"),
        "event_watchers_completed": snapshot.get("event_watchers_completed"),
        "external_source_state": snapshot.get("external_source_state"),
    }


def visible_status_key(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Fields that drive the operator-visible production/readiness state.

    Replay/event evidence can continue to move in the background while the
    visible status is still flat.  The SLA timer must not hide that flat state
    just because a miner sample counter advanced.
    """

    return {
        "production_score": snapshot.get("production_score"),
        "migration_complete": snapshot.get("migration_complete"),
        "shutdown_ready": snapshot.get("shutdown_ready"),
        "live_ready": snapshot.get("live_ready"),
        "paper_edge_proven": snapshot.get("paper_edge_proven"),
        "global_blocker_count": snapshot.get("global_blocker_count"),
        "report_center_blocked_count": snapshot.get("report_center_blocked_count"),
        "next_action_classification_counts": snapshot.get("next_action_classification_counts"),
        "event_watchers_completed": snapshot.get("event_watchers_completed"),
        "external_source_state": snapshot.get("external_source_state"),
        "operator_accepted_count": snapshot.get("operator_accepted_count"),
        "disallowed_classification_count": int(snapshot.get("disallowed_classification_count") or 0),
        "blocked_automatable_seed_count": int(snapshot.get("blocked_automatable_seed_count") or 0),
    }


def read_history() -> list[dict[str, Any]]:
    if not SNAPSHOT_HISTORY.exists():
        return []
    rows = []
    for line in SNAPSHOT_HISTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-500:]


def append_snapshot(snapshot: dict[str, Any], *, operator_reported_hours: float = 0.0) -> list[dict[str, Any]]:
    history = read_history()
    if operator_reported_hours > 0:
        oldest_ts = parse_iso(history[0].get("snapshot_utc")) if history else None
        synthetic_exists = any(row.get("operator_reported_no_change_synthetic") for row in history)
        target_oldest = (parse_iso(snapshot["snapshot_utc"]) or utc_now()) - timedelta(
            hours=operator_reported_hours
        )
        if not synthetic_exists and (oldest_ts is None or oldest_ts > target_oldest):
            synthetic = dict(snapshot)
            synthetic["snapshot_utc"] = target_oldest.isoformat().replace("+00:00", "Z")
            synthetic["operator_reported_no_change_synthetic"] = True
            history.insert(0, synthetic)
    history.append(snapshot)
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_HISTORY.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in history[-500:]) + "\n",
        encoding="utf-8",
    )
    return history[-500:]


def nearest_at_or_before(history: list[dict[str, Any]], target: datetime) -> dict[str, Any] | None:
    eligible = []
    for row in history:
        ts = parse_iso(row.get("snapshot_utc"))
        if ts and ts <= target:
            eligible.append((ts, row))
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: item[0], reverse=True)[0][1]


def compare_snapshots(current: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    windows = {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
    }
    now = parse_iso(current["snapshot_utc"]) or utc_now()
    current_key = comparable_key(current)
    current_status_key = visible_status_key(current)
    comparisons: dict[str, Any] = {}
    for label, delta in windows.items():
        prior = nearest_at_or_before(history[:-1], now - delta)
        if prior is None:
            comparisons[label] = {
                "available": False,
                "flat": None,
                "changed_fields": [],
                "observed_signal_changed_fields": [],
            }
            continue
        prior_key = comparable_key(prior)
        prior_status_key = visible_status_key(prior)
        observed_changed = [
            key
            for key, value in current_key.items()
            if json.dumps(value, sort_keys=True) != json.dumps(prior_key.get(key), sort_keys=True)
        ]
        status_changed = [
            key
            for key, value in current_status_key.items()
            if json.dumps(value, sort_keys=True)
            != json.dumps(prior_status_key.get(key), sort_keys=True)
        ]
        comparisons[label] = {
            "available": True,
            "prior_snapshot_utc": prior.get("snapshot_utc"),
            "flat": not status_changed,
            "changed_fields": status_changed,
            "observed_signal_changed_fields": observed_changed,
        }

    last_change_ts = None
    last_observed_change_ts = None
    previous_key = None
    previous_status_key = None
    for row in history:
        key = comparable_key(row)
        status_key = visible_status_key(row)
        ts = parse_iso(row.get("snapshot_utc"))
        if previous_key is not None and json.dumps(key, sort_keys=True) != json.dumps(
            previous_key, sort_keys=True
        ):
            last_observed_change_ts = ts
        if previous_status_key is not None and json.dumps(
            status_key, sort_keys=True
        ) != json.dumps(previous_status_key, sort_keys=True):
            last_change_ts = ts
        previous_key = key
        previous_status_key = status_key
    if last_change_ts is None and history:
        last_change_ts = parse_iso(history[0].get("snapshot_utc"))
    if last_observed_change_ts is None and history:
        last_observed_change_ts = parse_iso(history[0].get("snapshot_utc"))
    flat_seconds = None
    if last_change_ts is not None:
        flat_seconds = max(0.0, (now - last_change_ts).total_seconds())
    observed_flat_seconds = None
    if last_observed_change_ts is not None:
        observed_flat_seconds = max(0.0, (now - last_observed_change_ts).total_seconds())

    return {
        "comparison_windows": comparisons,
        "status_flat_duration_seconds": flat_seconds,
        "status_flat_duration_human": _human_duration(flat_seconds),
        "observed_signal_flat_duration_seconds": observed_flat_seconds,
        "observed_signal_flat_duration_human": _human_duration(observed_flat_seconds),
        "history_snapshot_count": len(history),
        "operator_reported_no_change_synthetic_present": any(
            row.get("operator_reported_no_change_synthetic") for row in history
        ),
    }


def _human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{seconds / 3600:.1f}h"


def _is_stale(timestamp: str | None, threshold_seconds: int = STALE_SECONDS) -> bool:
    age = age_seconds(timestamp)
    return age is None or age > threshold_seconds


def classify_root_cause(snapshot: dict[str, Any]) -> dict[str, Any]:
    stale_flags = {
        "report_center_stale": _is_stale(snapshot.get("report_center_generated_at")),
        "replay_miner_stale": _is_stale(snapshot.get("replay_miner_generated_at")),
        "event_watcher_stale": _is_stale(snapshot.get("event_watcher_generated_at")),
        "next_action_classifier_stale": _is_stale(snapshot.get("no_manual_generated_at")),
    }
    if stale_flags["report_center_stale"]:
        root = "REPORT_CENTER_STALE"
    elif stale_flags["replay_miner_stale"]:
        root = "REPLAY_MINER_STALE"
    elif stale_flags["event_watcher_stale"]:
        root = "EVENT_WATCHER_STALE"
    elif stale_flags["next_action_classifier_stale"]:
        root = "NEXT_ACTION_CLASSIFIER_STALE"
    elif snapshot.get("disallowed_classification_count", 0) > 0:
        root = "MISCLASSIFIED_AUTOMATABLE_WORK"
    elif snapshot.get("blocked_automatable_seed_count", 0) > 0:
        root = "MISCLASSIFIED_AUTOMATABLE_WORK"
    elif snapshot.get("automatable_now_count", 0) > 0 and snapshot.get("worker_active_leases", 0) == 0:
        root = "WORKER_POOL_IDLE_WITH_ELIGIBLE_WORK"
    elif snapshot.get("worker_queued_automatable_tasks", 0) > 0 and snapshot.get("worker_active_leases", 0) == 0:
        root = "WORKER_POOL_IDLE_WITH_ELIGIBLE_WORK"
    elif snapshot.get("unmapped_codex_fail_count", 0) > 0:
        root = "AUTOMATION_STALE"
    elif snapshot.get("remaining_external_blockers"):
        root = "TRUE_EXTERNAL_SOURCE_WAIT"
    elif snapshot.get("remaining_event_blockers"):
        root = "TRUE_EVENT_DEPENDENT_WAIT"
    elif snapshot.get("remaining_operator_blockers"):
        root = "TRUE_OPERATOR_WAIT"
    elif snapshot.get("next_action_classification_counts", {}).get("UNSAFE_TO_AUTOMATE", 0) > 0:
        root = "TRUE_UNSAFE_TO_AUTOMATE"
    else:
        root = "UNKNOWN_NO_CHANGE_FAILURE"

    return {
        "root_cause": root,
        "root_cause_is_allowed": root in {
            "TRUE_OPERATOR_WAIT",
            "TRUE_EXTERNAL_SOURCE_WAIT",
            "TRUE_EVENT_DEPENDENT_WAIT",
            "TRUE_UNSAFE_TO_AUTOMATE",
        },
        "stale_flags": stale_flags,
        "contributing_waits": {
            "operator_decisions": snapshot.get("remaining_operator_blockers", []),
            "external_sources": snapshot.get("remaining_external_blockers", []),
            "event_dependent": snapshot.get("remaining_event_blockers", []),
            "unsafe_to_automate_count": snapshot.get("next_action_classification_counts", {}).get(
                "UNSAFE_TO_AUTOMATE", 0
            ),
            "disallowed_classification_count": snapshot.get("disallowed_classification_count", 0),
            "blocked_automatable_seed_count": snapshot.get("blocked_automatable_seed_count", 0),
        },
    }


def seed_stale_remediation(root: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if root["root_cause_is_allowed"]:
        return {
            "remediation_seeded": False,
            "reason": "ROOT_CAUSE_IS_TRUE_WAIT_NOT_AUTOMATION_FAILURE",
            "generated_pairs": [],
        }
    row = {
        "source": LANE_ID,
        "report_id": LANE_ID,
        "title": "No Status Change SLA Watchdog Remediation",
        "status": "BLOCKED",
        "owner": "SYSTEM",
        "next_action": "remediate stale automation/reporting pipeline",
        "current_blockers": [root["root_cause"]],
        "classification": CLASS_AUTOMATABLE,
        "classification_reason": f"SLA_ROOT_CAUSE_{root['root_cause']}",
        "mission_category": "runtime_stability",
        "source_key": f"{LANE_ID}_{root['root_cause'].lower()}",
        "allowed_classification": True,
    }
    status = seed_automatable_tasks([row])
    return {
        "remediation_seeded": bool(status.get("generated_pair_count")),
        "reason": f"SEEDED_IF_NOT_DUPLICATE_FOR_{root['root_cause']}",
        **status,
    }


def build_action_plan(root: dict[str, Any], snapshot: dict[str, Any], remediation: dict[str, Any]) -> dict[str, Any]:
    root_cause = root["root_cause"]
    if root_cause == "TRUE_OPERATOR_WAIT":
        next_auto = "keep automation timers running; do not create fake technical work"
        next_operator = "decide pending operator blockers"
    elif root_cause == "TRUE_EXTERNAL_SOURCE_WAIT":
        next_auto = "keep source/watchers fresh; seed implementation only if source becomes available"
        next_operator = "approve/defer external source adoption and provide env names if approved"
    elif root_cause == "TRUE_EVENT_DEPENDENT_WAIT":
        next_auto = "keep event watchers running; do not fake event completion"
        next_operator = "wait or change operator thresholds where required"
    elif root_cause == "TRUE_UNSAFE_TO_AUTOMATE":
        next_auto = "none; unsafe actions are refused"
        next_operator = "explicitly decide whether any unsafe action should remain blocked"
    else:
        next_auto = "Spark remediation task seeded or referenced"
        next_operator = "none unless remediation classifies operator-required"

    return {
        "root_cause": root_cause,
        "next_automatic_action": next_auto,
        "next_operator_action": next_operator,
        "operator_decisions_needed": snapshot.get("remaining_operator_blockers", []),
        "external_source_state": snapshot.get("external_source_state", []),
        "external_source_reconciliation": snapshot.get("external_source_reconciliation", {}),
        "event_watchers": snapshot.get("remaining_event_blockers", []),
        "remediation": remediation,
        "do_not_fake_technical_work": root_cause
        in {"TRUE_OPERATOR_WAIT", "TRUE_EXTERNAL_SOURCE_WAIT", "TRUE_EVENT_DEPENDENT_WAIT"},
    }


def build_executive_explanation(
    snapshot: dict[str, Any],
    comparison: dict[str, Any],
    root: dict[str, Any],
    action_plan: dict[str, Any],
) -> dict[str, Any]:
    root_cause = root["root_cause"]
    if root_cause == "TRUE_EXTERNAL_SOURCE_WAIT":
        why = "external source adoption and API/key/tier decisions remain unresolved"
        expected = True
    elif root_cause == "TRUE_OPERATOR_WAIT":
        why = "operator decisions remain unresolved"
        expected = True
    elif root_cause == "TRUE_EVENT_DEPENDENT_WAIT":
        why = "real event-dependent evidence has not occurred yet"
        expected = True
    elif root_cause == "TRUE_UNSAFE_TO_AUTOMATE":
        why = "remaining next actions are unsafe to automate"
        expected = True
    else:
        why = f"the automation control plane reported {root_cause}"
        expected = False
    automation_stalled = not root["root_cause_is_allowed"]
    return {
        "STATUS_FLAT_DURATION": comparison.get("status_flat_duration_human"),
        "WHY_STATUS_IS_FLAT": why,
        "NEXT_OPERATOR_ACTION": action_plan["next_operator_action"],
        "NEXT_AUTOMATIC_ACTION": action_plan["next_automatic_action"],
        "IS_AUTOMATION_STALLED": automation_stalled,
        "IS_THIS_EXPECTED": expected,
        "WHAT_WOULD_CHANGE_SCORE": [
            "positive after-cost paper edge evidence",
            "operator thresholds/caps/checkpoint decisions",
            "approved external source data becoming available",
            "real event-dependent liquidation/edge watcher evidence",
        ],
        "WHAT_WOULD_UNBLOCK_SHUTDOWN": [
            "operator accepts/defer decisions explicitly",
            "external/event/evidence blockers resolve or are accepted/deferred",
            "Codex verifies final shutdown packet",
        ],
        "WHAT_WOULD_UNBLOCK_LIVE": [
            "paper edge proven",
            "checkpoint/model/risk gates accepted and verified",
            "human-only live approval outside this watchdog",
        ],
        "plain_english": [
            f"Production score is flat because {why}.",
            f"Automation is {'stalled' if automation_stalled else 'not stalled'} because {root_cause}.",
            f"The next thing that can change this state is {action_plan['next_operator_action'] if expected else action_plan['next_automatic_action']}.",
        ],
    }


def determine_go_no_go(
    root: dict[str, Any],
    snapshot: dict[str, Any],
    comparison: dict[str, Any],
    remediation: dict[str, Any],
) -> tuple[str, str, list[str]]:
    blockers: list[str] = []
    root_cause = root["root_cause"]
    active_remediation = bool(remediation.get("remediation_seeded")) and not root["root_cause_is_allowed"]
    if root_cause == "UNKNOWN_NO_CHANGE_FAILURE":
        blockers.append("UNKNOWN_NO_CHANGE_FAILURE")
    if not root["root_cause_is_allowed"]:
        blockers.append(root_cause)
    if root["stale_flags"].get("report_center_stale"):
        blockers.append("REPORT_CENTER_STALE")
    if root["stale_flags"].get("replay_miner_stale"):
        blockers.append("REPLAY_MINER_STALE")
    if root["stale_flags"].get("event_watcher_stale"):
        blockers.append("EVENT_WATCHER_STALE")
    if root["stale_flags"].get("next_action_classifier_stale"):
        blockers.append("NEXT_ACTION_CLASSIFIER_STALE")
    if snapshot.get("automatable_now_count", 0) > 0 and snapshot.get("worker_active_leases", 0) == 0:
        blockers.append("AUTOMATABLE_NOW_WITHOUT_ACTIVE_LEASE")
    if active_remediation:
        return GO_BLOCKED, "IN_PROGRESS", sorted(set(blockers or ["ACTIVE_REMEDIATION_RUNNING"]))
    if blockers:
        return GO_BLOCKED, "BLOCKED", sorted(set(blockers))
    return GO_READY, "EXPECTED_WAIT", []


def build_report(status: dict[str, Any], root: dict[str, Any], executive: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V2 No Status Change SLA Watchdog",
            "",
            f"Generated: {status['generated_utc']}",
            f"GO/NO-GO: `{status['go_no_go']}`",
            f"SLA state: `{status['sla_state']}`",
            f"Root cause: `{root['root_cause']}`",
            "",
            "## Executive Explanation",
            "",
            *[f"- {line}" for line in executive["plain_english"]],
            "",
            "## Current Signals",
            "",
            f"- production score: `{status['snapshot']['production_score']}`",
            f"- global blocker count: `{status['snapshot']['global_blocker_count']}`",
            f"- automatable now: `{status['snapshot']['automatable_now_count']}`",
            f"- active leases: `{status['snapshot']['worker_active_leases']}`",
            f"- task completions last hour: `{status['snapshot']['task_completions_last_hour']}`",
            f"- replay miner sample count: `{status['snapshot']['replay_miner_sample_count']}`",
            f"- event watchers completed: `{status['snapshot']['event_watchers_completed']}`",
            "",
            "## Safety",
            "",
            "- `live_gate=blocked_human_only`",
            "- `live_symbols=[]`",
            "- No live/canary/shutdown/Redis-trim approval is created.",
            "- No old Redis write or exchange mutation is allowed.",
            "",
        ]
    )


def write_outputs(
    status: dict[str, Any],
    root: dict[str, Any],
    action_plan: dict[str, Any],
    remediation: dict[str, Any],
    executive: dict[str, Any],
) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WORKLOG_DIR / "GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    (PUBLIC_DIR / "GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    report = build_report(status, root, executive)
    (WORKLOG_DIR / "V2_NO_STATUS_CHANGE_SLA_WATCHDOG_REPORT.md").write_text(
        report, encoding="utf-8"
    )
    (PUBLIC_DIR / "V2_NO_STATUS_CHANGE_SLA_WATCHDOG_REPORT.md").write_text(
        report, encoding="utf-8"
    )
    mirror_json("no_status_change_sla_status.json", status)
    mirror_json("no_change_root_cause.json", root)
    mirror_json("no_change_action_plan.json", action_plan)
    mirror_json("stale_pipeline_remediation_status.json", remediation)
    mirror_json("executive_no_change_explanation.json", executive)
    mirror_json(
        "operator_dashboard_payload.json",
        {
            "schema_version": "v2_no_status_change_sla_operator_dashboard_v1",
            "generated_utc": status["generated_utc"],
            "lane_id": LANE_ID,
            "go_no_go": status["go_no_go"],
            "sla_state": status["sla_state"],
            "root_cause": root["root_cause"],
            "STATUS_FLAT_DURATION": executive["STATUS_FLAT_DURATION"],
            "WHY_STATUS_IS_FLAT": executive["WHY_STATUS_IS_FLAT"],
            "NEXT_OPERATOR_ACTION": executive["NEXT_OPERATOR_ACTION"],
            "NEXT_AUTOMATIC_ACTION": executive["NEXT_AUTOMATIC_ACTION"],
            "IS_AUTOMATION_STALLED": executive["IS_AUTOMATION_STALLED"],
            "IS_THIS_EXPECTED": executive["IS_THIS_EXPECTED"],
            "plain_english": executive["plain_english"],
            "blockers": status["blockers"],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "shutdown_safe": False,
            "live_ready": False,
            "canary_ready": False,
        },
    )


def run_once(*, operator_reported_hours: float = 0.0) -> dict[str, Any]:
    snapshot = collect_snapshot()
    history = append_snapshot(snapshot, operator_reported_hours=operator_reported_hours)
    comparison = compare_snapshots(snapshot, history)
    root = classify_root_cause(snapshot)
    remediation = seed_stale_remediation(root, snapshot)
    action_plan = build_action_plan(root, snapshot, remediation)
    executive = build_executive_explanation(snapshot, comparison, root, action_plan)
    go_no_go, sla_state, blockers = determine_go_no_go(root, snapshot, comparison, remediation)
    status = {
        "schema_version": "v2_no_status_change_sla_watchdog_v1",
        "generated_utc": utc_iso(),
        "lane_id": LANE_ID,
        "go_no_go": go_no_go,
        "ready": go_no_go == GO_READY,
        "sla_state": sla_state,
        "blockers": blockers,
        "root_cause": root["root_cause"],
        "root_cause_is_allowed": root["root_cause_is_allowed"],
        "snapshot": snapshot,
        "comparison": comparison,
        "operator_reported_no_change_hours": operator_reported_hours,
        "STATUS_FLAT_DURATION": comparison.get("status_flat_duration_human"),
        "WHY_STATUS_IS_FLAT": executive["WHY_STATUS_IS_FLAT"],
        "IS_AUTOMATION_STALLED": executive["IS_AUTOMATION_STALLED"],
        "IS_THIS_EXPECTED": executive["IS_THIS_EXPECTED"],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "calls_exchange_mutation": False,
        "creates_approval_tokens": False,
    }
    write_outputs(status, root, action_plan, remediation, executive)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--operator-reported-hours", type=float, default=0.0)
    args = parser.parse_args(argv)
    status = run_once(operator_reported_hours=args.operator_reported_hours)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["go_no_go"] == GO_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
