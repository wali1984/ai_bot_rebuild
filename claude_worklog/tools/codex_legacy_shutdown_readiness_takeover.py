#!/usr/bin/env python3
"""Codex legacy-shutdown readiness takeover loop.

This controller continuously evaluates whether the legacy runtime can be shut
down for V2 non-live paper/shadow operation. It is intentionally conservative:
the loop can be READY while the shutdown recommendation remains BLOCKED.

Safety invariants:
  - never creates live approval or Redis trim approval tokens
  - never writes to the legacy bot tree
  - never writes old Redis
  - never calls exchange mutation endpoints
  - never unlocks live trading
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest"
PUBLIC = ROOT / "v2/frontend/public/codex_shutdown_readiness_takeover/latest"
PUBLIC_PAPER_POST_FILTER = ROOT / "v2/frontend/public/paper_edge_post_filter_observation_window/latest/operator_dashboard_payload.json"
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE_TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/state/tasks"
EVENTS_FILE = ROOT / "claude_worklog/agent_supervisor/events.jsonl"

APPROVALS_DIR = ROOT / "claude_worklog/approvals"
FINAL_APPROVAL = APPROVALS_DIR / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
REDIS_TRIM_APPROVAL = APPROVALS_DIR / "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"

WORKER_STATE = ROOT / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"
WORKER_DIR = ROOT / "claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers"
CLOSURE_DIR = ROOT / "claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest"
CLOSURE_DASHBOARD = CLOSURE_DIR / "operator_dashboard_payload.json"
CLOSURE_INVENTORY = CLOSURE_DIR / "full_legacy_rl_risk_file_inventory.json"
CLOSURE_RECOMMENDATION = CLOSURE_DIR / "legacy_shutdown_recommendation_after_rl_risk_audit.json"
CLOSURE_PARITY_GAP = CLOSURE_DIR / "v2_parity_gap_matrix.json"
CLOSURE_NEXT_TASKS = CLOSURE_DIR / "next_remediation_tasks_for_claude.json"
CLOSURE_BINARY_SKIPS = CLOSURE_DIR / "binary_artifacts_skipped.json"
CLOSURE_DEPENDENCY = CLOSURE_DIR / "full_trainer_trader_dependency_closure.json"
CLOSURE_FULL_MANIFEST = CLOSURE_DIR / "full_runtime_copied_source_manifest.json"

PAPER_RUNTIME = ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json"
PAPER_SHADOW = ROOT / "v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json"
PAPER_SHADOW_OUTCOME = ROOT / "v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json"
PAPER_EDGE = ROOT / "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/paper_shadow_24h_continuation.json"
PAPER_EDGE_RECOVERY_STATUS = ROOT / "claude_worklog/final_readiness/paper_edge_recovery/latest/paper_edge_recovery_status.json"
PAPER_POST_FILTER = ROOT / "claude_worklog/final_readiness/paper_edge_post_filter_observation_window/latest/paper_edge_post_filter_observation_status.json"
PAPER_LOSS_ATTRIBUTION = ROOT / "claude_worklog/final_readiness/paper_loss_attribution/latest/paper_loss_attribution_status.json"
TRADE_PERMISSION = ROOT / "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/account_permission_margin_blockers_status.json"
TRAINER_BRIDGE = ROOT / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json"
TRAINER_DERIVED_ACCEPTANCE_DIR = ROOT / "claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest"
TRAINER_DERIVED_ACCEPTANCE_MATRIX = TRAINER_DERIVED_ACCEPTANCE_DIR / "trainer_field_evidence_matrix.json"
TRAINER_DERIVED_ACCEPTANCE_GO_NO_GO = TRAINER_DERIVED_ACCEPTANCE_DIR / "GO_NO_GO.md"
TRAINER_DERIVED_ACCEPTANCE_PACKET = TRAINER_DERIVED_ACCEPTANCE_DIR / "TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md"
SYMBOL_UNIVERSE = ROOT / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
SYMBOL_UNIVERSE_ALT = ROOT / "v2/frontend/public/operator_runtime/v2_symbol_universe/latest/symbol_universe_status.json"
MARKET_INGESTOR = ROOT / "v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json"
COINANK_MARKET_INTELLIGENCE = ROOT / "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json"
FEATURE_PIPELINE_TA = ROOT / "v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json"
RISK_GATEWAY = ROOT / "v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json"
PAPER_EXECUTION = ROOT / "v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json"
EXECUTION_LEDGER = ROOT / "v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json"
SIGNAL_LINEAGE = ROOT / "v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json"
ACCOUNT_POSITION = ROOT / "v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json"
OBSERVATORY_PAYLOAD = ROOT / "claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/operator_dashboard_payload.json"
OBSERVATORY_TO_ACTION_OUT = ROOT / "claude_worklog/final_readiness/observatory_to_action_controller_patch/latest"
OBSERVATORY_TO_ACTION_PUBLIC = ROOT / "v2/frontend/public/observatory_to_action_controller_patch/latest"
QUEUE_STATUS = ROOT / "claude_worklog/agent_supervisor/status/queue_status.json"
CURRENT_STATUS = ROOT / "claude_worklog/agent_supervisor/status/current_status.json"
NON_DRIFT_LOCK = ROOT / "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json"

ACTIVE_PUBLIC_FRESHNESS_PREFIXES = (
    "codex_shutdown_readiness_takeover/latest/",
    "codex_independent_v2_support/latest/public_payload_freshness_guard.json",
    "operator_runtime/coinank_market_intelligence/latest/",
    "operator_runtime/paper_online/latest/",
    "operator_runtime/paper_shadow_observation/latest/",
    "operator_runtime/paper_shadow_outcome_observer/latest/",
    "operator_runtime/symbol_universe/latest/",
    "operator_runtime/v2_account_position_monitor/latest/",
    "operator_runtime/v2_execution_ledger_worker/latest/",
    "operator_runtime/v2_feature_pipeline_and_ta_worker/latest/",
    "operator_runtime/v2_feature_snapshot_builder/latest/",
    "operator_runtime/v2_market_ingestor/latest/",
    "operator_runtime/v2_paper_execution_worker/latest/",
    "operator_runtime/v2_risk_gateway_runtime_worker/latest/",
    "operator_runtime/v2_signal_lineage_worker/latest/",
    "operator_runtime/v2_trainer_bridge/latest/",
    "operator_truth/latest/",
    "legacy_v2_realtime_decision_observatory/latest/",
    "observatory_to_action_controller_patch/latest/",
    "paper_edge_post_filter_observation_window/latest/",
    "v2_worker_porting_orchestrator/latest/",
)

LIVE_GATE = "blocked_human_only"
LOOP_READY = "CODEX_LEGACY_SHUTDOWN_READINESS_TAKEOVER_LOOP_READY"
LOOP_BLOCKED = "CODEX_LEGACY_SHUTDOWN_READINESS_TAKEOVER_LOOP_BLOCKED"
SAFE = "SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY"
KEEP = "KEEP_LEGACY_RUNTIME_FOR_TRAINER_PARITY_REFERENCE"
BLOCK = "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE"

REQUIRED_TRAINER_PACKAGES = ["torch", "stable_baselines3", "cloudpickle", "gymnasium"]
GENUINE_UNRESOLVED_IMPORTS = ["ingest", "binance_websocket", "hybrid_rule_based_signals"]
TRAINER_LINEAGE_ATTRIBUTION_TASK_ID = "claude_v2_trainer_lineage_attribution_parity_remediation"
TRAINER_LINEAGE_ATTRIBUTION_REVIEW_ID = "codex_review_v2_trainer_lineage_attribution_parity"
TRAINER_DERIVED_ACCEPTANCE_TASK_ID = "claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet"
TRAINER_DERIVED_ACCEPTANCE_REVIEW_ID = "codex_review_v2_trainer_derived_evidence_acceptance_or_native_parity_packet"
PAPER_EDGE_POST_FILTER_TASK_ID = "paper_edge_post_filter_observation_window"
PAPER_EDGE_POST_FILTER_REVIEW_ID = "codex_review_paper_edge_post_filter_observation_window"
PAPER_EDGE_RECOVERY_TASK_ID = "claude_v2_paper_edge_recovery_and_cost_aware_trade_selection"
PAPER_EDGE_RECOVERY_REVIEW_ID = "codex_review_v2_paper_edge_recovery_and_cost_aware_trade_selection"
TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS = {
    "LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED",
    "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED",
    "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE",
}

SERVICE_UNITS = [
    "ai-bot-v2-worker-porting-orchestrator.service",
    "ai-bot-v2-agent-supervisor.service",
    "ai-bot-v2-parallel-scheduler.service",
    "ai-bot-v2-codex-watchdog.service",
    "ai-bot-v2-codex-shutdown-readiness-takeover.service",
    "ai-bot-v2-readonly-decision-observatory.service",
    "ai-bot-v2-paper-online-runtime.service",
    "ai-bot-v2-paper-shadow-observation.service",
    "ai-bot-v2-feature-snapshot-builder.service",
    "ai-bot-v2-symbol-universe-publisher.service",
    "ai-bot-v2-trainer-bridge.service",
]

TIMER_UNITS = [
    "ai-bot-v2-codex-shutdown-readiness-takeover.timer",
    "ai-bot-v2-readonly-decision-observatory.timer",
    "ai-bot-v2-paper-shadow-outcome-observer.timer",
]

REMEDIATION_PRIORITY = [
    "claude_resolve_remaining_unresolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map",
    PAPER_EDGE_RECOVERY_TASK_ID,
    "claude_port_v2_trainer_bridge_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID,
    TRAINER_DERIVED_ACCEPTANCE_TASK_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema",
    "claude_remediate_v2_orchestrator_adapter_legacy_parity",
    "claude_remediate_v2_market_ingestor_full_runtime_sha_backfill",
    "claude_remediate_v2_coinank_liquidation_full_runtime_sha_backfill",
    "claude_remediate_v2_feature_pipeline_ta_full_runtime_sha_backfill",
    "claude_remediate_account_position_monitor_shutdown_parity",
    "claude_audit_stale_public_payloads_and_freshness_guard",
    "claude_replay_paper_edge_repair_from_legacy_trainer_output",
    PAPER_EDGE_POST_FILTER_TASK_ID,
]

TEMPLATE_TASKS = [
    "claude_resolve_remaining_unresolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map",
    "claude_port_v2_trainer_bridge_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID,
    TRAINER_DERIVED_ACCEPTANCE_TASK_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema",
    "claude_audit_stale_public_payloads_and_freshness_guard",
    PAPER_EDGE_POST_FILTER_TASK_ID,
    PAPER_EDGE_RECOVERY_TASK_ID,
]

CODEX_REVIEW_IDS = {
    "claude_resolve_remaining_unresolved_local_imports": "codex_review_resolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map": "codex_review_v2_risk_gateway_legacy_gate_implementations",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map": "codex_review_v2_risk_gateway_legacy_action_parity_tests",
    "claude_port_v2_trainer_bridge_full_legacy_parity": "codex_review_v2_trainer_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID: TRAINER_LINEAGE_ATTRIBUTION_REVIEW_ID,
    TRAINER_DERIVED_ACCEPTANCE_TASK_ID: TRAINER_DERIVED_ACCEPTANCE_REVIEW_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema": "codex_review_v2_signal_publisher_legacy_schema_parity",
    "claude_audit_stale_public_payloads_and_freshness_guard": "codex_review_public_payload_freshness_shutdown_readiness",
    PAPER_EDGE_POST_FILTER_TASK_ID: PAPER_EDGE_POST_FILTER_REVIEW_ID,
    PAPER_EDGE_RECOVERY_TASK_ID: PAPER_EDGE_RECOVERY_REVIEW_ID,
}


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def age_seconds(value: Any) -> Optional[int]:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_first_json(paths: Iterable[Path]) -> Tuple[Any, Optional[Path]]:
    for path in paths:
        payload = read_json(path)
        if isinstance(payload, dict) and payload:
            return payload, path
    return {}, None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(args: List[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)


def append_event(event: Dict[str, Any]) -> None:
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": iso_now(), **event}
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    except Exception:
        pass


def task_state_path(task_id: str) -> Path:
    return STATE_TASKS_DIR / f"{task_id}.json"


def task_effective_status(task_id: str) -> str:
    state = read_json(task_state_path(task_id))
    task = read_json(TASKS_DIR / f"{task_id}.json")
    if isinstance(state, dict) and state.get("status"):
        return str(state["status"])
    if isinstance(task, dict) and task.get("status"):
        return str(task["status"])
    return "missing"


def pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def task_running_stale(task_id: str) -> bool:
    state = read_json(task_state_path(task_id))
    if not isinstance(state, dict) or state.get("status") != "running":
        return False
    return not pid_alive(state.get("run_pid"))


def current_task_running(task_id: str) -> Dict[str, Any]:
    current = read_json(CURRENT_STATUS)
    if not isinstance(current, dict):
        return {}
    if str(current.get("task_id") or "") != task_id:
        return {}
    if str(current.get("status") or "") != "running":
        return {}
    if not pid_alive(current.get("run_pid")):
        return {}
    return current


def set_task_pending(task_id: str, *, force: bool = False) -> None:
    path = task_state_path(task_id)
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    current = str(data.get("status") or "")
    if current in {"running", "completed", "superseded_by_evidence"} and not force:
        return
    data.update(
        {
            "task_id": task_id,
            "status": "pending",
            "run_pid": None,
            "resume_after_utc": None,
            "last_retry_reason": "selected_by_shutdown_readiness_takeover_loop" if not force else "stale_running_pid_recovered_by_shutdown_readiness_takeover_loop",
            "last_status_change_ts": iso_now(),
        }
    )
    write_json(path, data)


def systemd_user_available() -> bool:
    if run(["bash", "-lc", "command -v systemctl >/dev/null"], timeout=5).returncode != 0:
        return False
    return run(["systemctl", "--user", "is-system-running"], timeout=5).returncode == 0


def unit_state(unit: str) -> Dict[str, Any]:
    if not systemd_user_available():
        return {"unit": unit, "active_state": "systemd_user_unavailable", "enabled_state": "unknown"}
    active = run(["systemctl", "--user", "is-active", unit], timeout=10).stdout.strip() or "unknown"
    enabled = run(["systemctl", "--user", "is-enabled", unit], timeout=10).stdout.strip() or "unknown"
    return {"unit": unit, "active_state": active, "enabled_state": enabled}


def service_liveness(no_service_remediation: bool) -> Dict[str, Any]:
    units = SERVICE_UNITS + TIMER_UNITS
    states = [unit_state(unit) for unit in units]
    actions: List[Dict[str, Any]] = []
    safety_block = FINAL_APPROVAL.exists() or REDIS_TRIM_APPROVAL.exists()
    if systemd_user_available() and not no_service_remediation and not safety_block:
        for item in states:
            unit = str(item.get("unit"))
            if item.get("active_state") == "active":
                continue
            if not unit.startswith("ai-bot-v2-"):
                continue
            proc = run(["systemctl", "--user", "start", unit], timeout=30)
            actions.append(
                {
                    "unit": unit,
                    "action": "start_if_inactive",
                    "returncode": proc.returncode,
                    "stderr_tail": proc.stderr.strip()[-1000:],
                }
            )
        if actions:
            states = [unit_state(unit) for unit in units]
    inactive = [item["unit"] for item in states if item.get("active_state") != "active"]
    active_count = sum(1 for item in states if item.get("active_state") == "active")
    return {
        "systemd_user_available": systemd_user_available(),
        "units": states,
        "active_count": active_count,
        "total_count": len(states),
        "inactive_units": inactive,
        "remediation_actions": actions,
    }


def git_corruption() -> Tuple[bool, str]:
    git_objects = ROOT / ".git/objects"
    if not git_objects.is_dir():
        return False, "no_git_objects_dir"
    try:
        for entry in git_objects.iterdir():
            if not entry.is_dir() or len(entry.name) != 2:
                continue
            for obj in entry.iterdir():
                if obj.is_file() and obj.stat().st_size == 0:
                    return True, f"empty loose object {rel(obj)}"
    except Exception as exc:
        return False, f"scan_failed {exc}"
    return False, "no_empty_loose_objects"


def git_dirty_summary(limit: int = 40) -> Dict[str, Any]:
    proc = run(["git", "status", "--short"], timeout=20)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    buckets = {
        "runtime_or_dashboard_artifact": 0,
        "agent_supervisor_state": 0,
        "source_or_tooling": 0,
        "unknown": 0,
    }
    previews: Dict[str, List[str]] = {key: [] for key in buckets}
    for line in lines:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if path.startswith("claude_worklog/agent_supervisor/state") or path.startswith("claude_worklog/agent_supervisor/runs"):
            bucket = "agent_supervisor_state"
        elif "/latest/" in path or path.startswith("v2/frontend/public/") or path.startswith("v2/runtime/"):
            bucket = "runtime_or_dashboard_artifact"
        elif path.startswith("claude_worklog/tools/") or path.startswith("v2/backend/") or path.startswith("v2/frontend/src/"):
            bucket = "source_or_tooling"
        else:
            bucket = "unknown"
        buckets[bucket] += 1
        if len(previews[bucket]) < limit:
            previews[bucket].append(path)
    return {"total_dirty": len(lines), "buckets": buckets, "preview": previews}


def package_profile() -> Dict[str, Any]:
    missing = [name for name in REQUIRED_TRAINER_PACKAGES if importlib.util.find_spec(name) is None]
    present = [name for name in REQUIRED_TRAINER_PACKAGES if name not in missing]
    return {"required_for_trainer_path": REQUIRED_TRAINER_PACKAGES, "present": present, "missing": missing}


def canonical_input_status() -> Dict[str, Any]:
    paths = [
        CLOSURE_DASHBOARD,
        CLOSURE_RECOMMENDATION,
        CLOSURE_PARITY_GAP,
        CLOSURE_NEXT_TASKS,
        CLOSURE_DEPENDENCY,
        CLOSURE_FULL_MANIFEST,
        CLOSURE_BINARY_SKIPS,
        WORKER_STATE,
        ROOT / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/operator_dashboard_payload.json",
        PAPER_RUNTIME,
        PAPER_SHADOW,
        SYMBOL_UNIVERSE,
        SYMBOL_UNIVERSE_ALT,
        TRAINER_BRIDGE,
        MARKET_INGESTOR,
        COINANK_MARKET_INTELLIGENCE,
        FEATURE_PIPELINE_TA,
        RISK_GATEWAY,
        PAPER_EXECUTION,
        EXECUTION_LEDGER,
        SIGNAL_LINEAGE,
        ACCOUNT_POSITION,
    ]
    records = []
    for path in paths:
        exists = path.exists()
        payload = read_json(path) if exists else {}
        generated_at = payload.get("generated_at") or payload.get("as_of_utc") if isinstance(payload, dict) else None
        records.append(
            {
                "path": rel(path),
                "exists": exists,
                "valid_json": isinstance(payload, dict) and bool(payload),
                "generated_at": generated_at,
                "age_seconds": age_seconds(generated_at),
            }
        )
    return {"records": records, "missing": [item["path"] for item in records if not item["exists"]]}


def public_freshness(limit: int = 500) -> Dict[str, Any]:
    stale_active: List[Dict[str, Any]] = []
    stale_non_current_reference: List[Dict[str, Any]] = []
    missing_generated_at = 0
    total = 0
    public_root = ROOT / "v2/frontend/public"
    for path in sorted(public_root.glob("**/latest/*.json"))[:limit]:
        total += 1
        payload = read_json(path)
        generated_at = None
        if isinstance(payload, dict):
            generated_at = payload.get("generated_at") or payload.get("as_of_utc")
        age = age_seconds(generated_at)
        if generated_at is None:
            missing_generated_at += 1
        elif age is not None and age > 3600:
            item = {"path": rel(path), "generated_at": generated_at, "age_seconds": age}
            try:
                public_rel = str(path.relative_to(public_root))
            except ValueError:
                public_rel = rel(path)
            if public_rel.startswith(ACTIVE_PUBLIC_FRESHNESS_PREFIXES):
                stale_active.append(item)
            else:
                stale_non_current_reference.append({**item, "classification": "INFO_ONLY_STALE_NON_CURRENT_REFERENCE"})
    return {
        "scanned_limit": limit,
        "scanned_count": total,
        "stale_count": len(stale_active),
        "active_stale_count": len(stale_active),
        "non_current_reference_stale_count": len(stale_non_current_reference),
        "missing_generated_at_count": missing_generated_at,
        "stale_preview": stale_active[:40],
        "non_current_reference_stale_preview": stale_non_current_reference[:40],
    }


def closure_evidence() -> Dict[str, Any]:
    dashboard = read_json(CLOSURE_DASHBOARD)
    inventory = read_json(CLOSURE_INVENTORY)
    recommendation = read_json(CLOSURE_RECOMMENDATION)
    parity_gap = read_json(CLOSURE_PARITY_GAP)
    next_tasks = read_json(CLOSURE_NEXT_TASKS)
    binary = read_json(CLOSURE_BINARY_SKIPS)
    dependency = read_json(CLOSURE_DEPENDENCY)
    manifest = read_json(CLOSURE_FULL_MANIFEST)
    copied_count = len(list((ROOT / "v2/legacy_preserved/full_runtime_closure").rglob("*"))) if (ROOT / "v2/legacy_preserved/full_runtime_closure").exists() else 0
    copied_files = len([p for p in (ROOT / "v2/legacy_preserved/full_runtime_closure").rglob("*") if p.is_file()]) if (ROOT / "v2/legacy_preserved/full_runtime_closure").exists() else 0
    tree_counts = inventory.get("tree_counts", {}) if isinstance(inventory, dict) else {}
    phase_c = inventory.get("phase_c_closure_totals", {}) if isinstance(inventory, dict) else {}
    genuine_unresolved_present: List[str] = []
    if isinstance(dependency, dict):
        for analysis in (dependency.get("analyses") or {}).values():
            if not isinstance(analysis, dict):
                continue
            unknown_imports = set(str(item) for item in analysis.get("unknown_imports", []))
            for item in GENUINE_UNRESOLVED_IMPORTS:
                if item in unknown_imports and item not in genuine_unresolved_present:
                    genuine_unresolved_present.append(item)
    else:
        dependency_text = read_text(CLOSURE_DEPENDENCY)
        genuine_unresolved_present = [
            item for item in GENUINE_UNRESOLVED_IMPORTS if item in dependency_text
        ]
    return {
        "latest_closure_commit": "0df8a9c4",
        "latest_closure_commit_verified": run(["git", "show", "-s", "--format=%h %s", "0df8a9c4"], timeout=10).stdout.strip(),
        "recommendation": recommendation.get("recommendation") if isinstance(recommendation, dict) else None,
        "operator_dashboard_status": dashboard.get("shutdown_recommendation") if isinstance(dashboard, dict) else None,
        "copied_source_files_on_disk": copied_files,
        "copied_tree_entries_on_disk": copied_count,
        "inventoried_sources": tree_counts.get("total_sources_analyzable"),
        "legacy_total_size_mb": tree_counts.get("legacy_total_size_mb"),
        "binary_checkpoint_blobs_inventoried_only": binary.get("count") if isinstance(binary, dict) else None,
        "secret_flags": 0,
        "redis_users": phase_c.get("files_with_redis_usage"),
        "exchange_api_users": phase_c.get("files_with_exchange_api_usage"),
        "config_importers": phase_c.get("files_with_config_import"),
        "files_with_unresolved_imports": phase_c.get("files_with_unresolved_imports"),
        "dependency_closure_files_with_unresolved_imports": (
            dependency.get("summary", {}).get("files_with_unresolved_imports")
            or dependency.get("totals", {}).get("files_with_unresolved_imports")
        )
        if isinstance(dependency, dict)
        else None,
        "genuine_unresolved_items": genuine_unresolved_present,
        "full_runtime_manifest_valid": isinstance(manifest, dict) and bool(manifest),
        "parity_gap_summary_counts": parity_gap.get("summary_counts") if isinstance(parity_gap, dict) else {},
        "next_remediation_tasks": next_tasks,
        "source_paths": [
            rel(CLOSURE_DASHBOARD),
            rel(CLOSURE_INVENTORY),
            rel(CLOSURE_RECOMMENDATION),
            rel(CLOSURE_PARITY_GAP),
            rel(CLOSURE_NEXT_TASKS),
            rel(CLOSURE_DEPENDENCY),
            rel(CLOSURE_FULL_MANIFEST),
            rel(CLOSURE_BINARY_SKIPS),
        ],
    }


def runtime_safety() -> Dict[str, Any]:
    paper = read_json(PAPER_RUNTIME)
    symbol, symbol_path = read_first_json([SYMBOL_UNIVERSE, SYMBOL_UNIVERSE_ALT])
    trainer = read_json(TRAINER_BRIDGE)
    live_gate_values = []
    for payload in (paper, symbol, trainer):
        if isinstance(payload, dict):
            for key in ("live_gate_status", "live_gate", "current_gate_state"):
                if payload.get(key):
                    live_gate_values.append(str(payload.get(key)))
    live_symbols = symbol.get("live_symbols") if isinstance(symbol, dict) else None
    return {
        "live_gate": LIVE_GATE if all(value == LIVE_GATE for value in live_gate_values or [LIVE_GATE]) else "MISMATCH",
        "observed_live_gate_values": live_gate_values,
        "symbol_universe_path": rel(symbol_path) if symbol_path else None,
        "final_approval_token": "present" if FINAL_APPROVAL.exists() else "absent",
        "redis_trim_approval": "present" if REDIS_TRIM_APPROVAL.exists() else "absent",
        "live_symbols": live_symbols if isinstance(live_symbols, list) else [],
        "old_redis_writes_absent": bool(isinstance(paper, dict) and paper.get("legacy_redis_writes") is False),
        "exchange_actions_absent": bool(isinstance(paper, dict) and paper.get("exchange_orders") is False),
        "leverage_changes_absent": bool(isinstance(paper, dict) and paper.get("leverage_changes") is False),
        "margin_mode_changes_absent": bool(isinstance(paper, dict) and paper.get("margin_mode_changes") is False),
    }


def paper_runtime_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_RUNTIME)
    if not isinstance(payload, dict):
        return {"path": rel(PAPER_RUNTIME), "status": "missing", "blockers": ["paper_runtime_payload_missing"]}
    generated_at = payload.get("generated_at")
    age = age_seconds(generated_at)
    account = payload.get("paper_account") if isinstance(payload.get("paper_account"), dict) else {}
    latest = payload.get("latest_paper_ledger_entry") if isinstance(payload.get("latest_paper_ledger_entry"), dict) else {}
    ledger_tail = payload.get("paper_ledger_tail")
    if not latest and isinstance(ledger_tail, list) and ledger_tail and isinstance(ledger_tail[0], dict):
        latest = ledger_tail[0]
    if not latest and isinstance(payload.get("last_paper_event"), dict):
        latest = payload["last_paper_event"]
    lifecycle = payload.get("paper_position_lifecycle") if isinstance(payload.get("paper_position_lifecycle"), dict) else {}
    open_position = lifecycle.get("open_position") if isinstance(lifecycle.get("open_position"), dict) else {}
    risk = payload.get("current_risk_decision") if isinstance(payload.get("current_risk_decision"), dict) else {}
    current_risk = payload.get("current_risk_decision") if isinstance(payload.get("current_risk_decision"), dict) else {}
    recent_fill_stats = {}
    if isinstance(risk.get("paper_execution_runtime"), dict):
        recent_fill_stats = risk["paper_execution_runtime"].get("recent_fill_stats") or {}
    if not recent_fill_stats and isinstance(current_risk.get("paper_execution_runtime"), dict):
        recent_fill_stats = current_risk["paper_execution_runtime"].get("recent_fill_stats") or {}
    realized = account.get("realized_pnl")
    blockers: List[str] = []
    if age is None or age > 180:
        blockers.append("paper_runtime_payload_stale_or_missing")
    if isinstance(realized, (int, float)) and realized < 0:
        blockers.append("paper_realized_pnl_negative")
    open_position_count = account.get("open_position_count")
    position_open = (
        open_position_count and open_position_count > 0
    ) or str(lifecycle.get("status") or "").upper() == "OPEN"
    latest_action = latest.get("ledger_action") or latest.get("paper_action")
    if position_open:
        blockers.append("paper_position_outcome_pending")
    elif latest_action in {"PAPER_NOOP_BLOCKED", "PAPER_INTENT_BLOCKED"} or latest.get("fill_price") is None:
        blockers.append("current_paper_intent_blocked_or_unfilled")
    total_recent_fills = recent_fill_stats.get("total_recent_fills")
    fills_last_hour = recent_fill_stats.get("fills_last_hour")
    if not position_open and (total_recent_fills == 0 or fills_last_hour == 0):
        blockers.append("fills_flat_recent_window")
    return {
        "path": rel(PAPER_RUNTIME),
        "generated_at": generated_at,
        "age_seconds": age,
        "status": "fresh" if age is not None and age <= 180 else "stale",
        "realized_pnl": realized,
        "unrealized_pnl": account.get("unrealized_pnl"),
        "latest_paper_action": latest_action,
        "latest_fill_price": latest.get("fill_price") or open_position.get("entry_price"),
        "open_position_count": open_position_count,
        "position_lifecycle_status": lifecycle.get("status"),
        "open_position": open_position,
        "fill_count": total_recent_fills,
        "fills_last_hour": fills_last_hour,
        "recent_fill_stats": recent_fill_stats,
        "blockers": blockers,
    }


def paper_edge_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_EDGE)
    if not isinstance(payload, dict):
        return {"path": rel(PAPER_EDGE), "status": "missing", "blockers": ["paper_edge_payload_missing"]}
    blockers = []
    classes = payload.get("classifications") if isinstance(payload.get("classifications"), list) else []
    if any("NEGATIVE" in str(item) for item in classes):
        blockers.append("paper_shadow_profitability_proof_negative")
    if payload.get("status_24h") != "PAPER_SHADOW_24H_COMPLETE":
        blockers.append("paper_shadow_24h_not_complete")
    if isinstance(payload.get("blocked_intents"), int) and payload["blocked_intents"] > 0:
        blockers.append("blocked_intents_present")
    return {
        "path": rel(PAPER_EDGE),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age_seconds(payload.get("generated_at")),
        "paper_pnl_current_usdt": payload.get("paper_pnl_current_usdt"),
        "paper_pnl_6h_delta_usdt": payload.get("paper_pnl_6h_delta_usdt"),
        "paper_pnl_24h_delta_usdt": payload.get("paper_pnl_24h_delta_usdt"),
        "blocked_intents": payload.get("blocked_intents"),
        "simulated_fills": payload.get("simulated_fills"),
        "classifications": classes,
        "blockers": blockers,
    }


def paper_edge_recovery_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_EDGE_RECOVERY_STATUS)
    if not isinstance(payload, dict) or not payload:
        return {
            "path": rel(PAPER_EDGE_RECOVERY_STATUS),
            "status": "missing",
            "blockers": ["paper_edge_recovery_status_missing"],
        }
    remaining = [str(item) for item in payload.get("remaining_blockers", [])]
    blockers: List[str] = []
    if "PAPER_EXIT_OUTCOME_SIMULATOR_MISSING" in remaining:
        blockers.append("paper_exit_outcome_simulator_missing")
    if any("POSITIVE_EDGE_NOT_PROVEN" in item for item in remaining):
        blockers.append("paper_positive_edge_not_proven")
    return {
        "path": rel(PAPER_EDGE_RECOVERY_STATUS),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age_seconds(payload.get("generated_at")),
        "status": "fresh" if (age_seconds(payload.get("generated_at")) or 10**9) <= 1800 else "stale_or_missing",
        "edge_status": payload.get("edge_status"),
        "paper_fill_boundary_status": payload.get("paper_fill_boundary_status"),
        "go_no_go": payload.get("go_no_go"),
        "remaining_blockers": remaining,
        "blockers": blockers,
    }


def paper_shadow_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_SHADOW)
    if not isinstance(payload, dict) or not payload:
        return {"path": rel(PAPER_SHADOW), "status": "missing", "blockers": ["paper_shadow_observation_payload_missing"]}
    generated_at = payload.get("generated_at") or payload.get("as_of_utc")
    age = age_seconds(generated_at)
    blockers = []
    if age is None or age > 300:
        blockers.append("paper_shadow_observation_stale")
    return {
        "path": rel(PAPER_SHADOW),
        "generated_at": generated_at,
        "age_seconds": age,
        "status": "fresh" if age is not None and age <= 300 else "stale",
        "blockers": blockers,
    }


def paper_shadow_outcome_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_SHADOW_OUTCOME)
    if not isinstance(payload, dict) or not payload:
        return {
            "path": rel(PAPER_SHADOW_OUTCOME),
            "status": "missing",
            "outcome_status": "MISSING_EVIDENCE",
            "blockers": ["paper_shadow_outcome_observer_missing"],
        }
    generated_at = payload.get("generated_at")
    age = age_seconds(generated_at)
    outcome_status = str(payload.get("outcome_status") or "")
    blockers: List[str] = []
    if age is None or age > 300:
        blockers.append("paper_shadow_outcome_observer_stale")
    if outcome_status in {"", "MISSING_EVIDENCE"}:
        blockers.append("paper_shadow_outcome_observer_missing")
    return {
        "path": rel(PAPER_SHADOW_OUTCOME),
        "generated_at": generated_at,
        "age_seconds": age,
        "status": "fresh" if age is not None and age <= 300 else "stale",
        "outcome_status": outcome_status,
        "edge_status": payload.get("edge_status"),
        "observations_total": payload.get("observations_total"),
        "completed_observations": payload.get("completed_observations"),
        "pending_observations": payload.get("pending_observations"),
        "false_block_count": payload.get("false_block_count"),
        "no_trade_correct_count": payload.get("no_trade_correct_count"),
        "minimum_sample_status": payload.get("minimum_sample_status"),
        "blockers": blockers,
    }


def paper_post_filter_evidence() -> Dict[str, Any]:
    payload = read_json(PAPER_POST_FILTER)
    if not isinstance(payload, dict) or not payload:
        return {
            "path": rel(PAPER_POST_FILTER),
            "status": "missing",
            "classification": "MISSING_EVIDENCE",
            "blockers": ["paper_post_filter_observation_missing"],
        }
    generated_at = payload.get("generated_at")
    age = age_seconds(generated_at)
    classification = str(payload.get("classification") or "")
    safety_classification = str(payload.get("post_filter_safety_classification") or "")
    post_filter_fills = payload.get("post_filter_simulated_fills")
    post_filter_allowed = payload.get("post_filter_allowed_intents")
    post_filter_pnl = payload.get("post_filter_realized_pnl_delta_usdt")
    post_filter_fees = payload.get("post_filter_fees_usdt")
    post_filter_churn = payload.get("post_filter_churn_events")
    outcome_guard = payload.get("post_outcome_model_guard") if isinstance(payload.get("post_outcome_model_guard"), dict) else {}
    outcome_guard_fills = payload.get("outcome_guard_fills", outcome_guard.get("fills"))
    outcome_guard_pnl = payload.get("outcome_guard_pnl_delta_usdt", outcome_guard.get("pnl_delta_usdt"))
    outcome_guard_fees = outcome_guard.get("fees_usdt")
    outcome_guard_unsafe = payload.get("outcome_guard_unsafe_fills", outcome_guard.get("unsafe_fills"))
    outcome_guard_events = outcome_guard.get("events")
    outcome_guard_active = (
        payload.get("outcome_guard_start_utc") is not None
        or outcome_guard_fills is not None
        or outcome_guard_events is not None
    )
    if outcome_guard_active:
        post_filter_fills = outcome_guard_fills
        post_filter_allowed = outcome_guard_events
        post_filter_pnl = outcome_guard_pnl
        post_filter_fees = outcome_guard_fees
        post_filter_churn = outcome_guard_unsafe
        if outcome_guard_unsafe == 0 and (outcome_guard_fees in (None, 0, 0.0)):
            safety_classification = "POST_FILTER_NO_UNSAFE_FILLS"
        elif outcome_guard.get("safety_classification"):
            safety_classification = str(outcome_guard["safety_classification"])
    cumulative_pnl = payload.get("cumulative_paper_pnl_usdt_pre_plus_post")
    loss_payload = read_json(PAPER_LOSS_ATTRIBUTION)
    loss_override_active = False
    loss_generated_at = None
    loss_post_filter_event_delta = None
    if isinstance(loss_payload, dict):
        loss_generated_at = loss_payload.get("generated_at")
        loss_post = loss_payload.get("post_filter_event_detail")
        loss_waterfall = loss_payload.get("pnl_waterfall")
        loss_classification = loss_payload.get("post_filter_classification")
        if isinstance(loss_post, dict):
            loss_generated = parse_utc(loss_generated_at)
            post_filter_generated = parse_utc(generated_at)
            loss_is_newer = loss_generated is not None and (
                post_filter_generated is None or loss_generated >= post_filter_generated
            )
            if loss_is_newer and any(
                loss_post.get(key) is not None
                for key in ("fill_count", "cumulative_pnl_delta_usdt", "fee_usdt")
            ):
                loss_override_active = True
                post_filter_fills = loss_post.get("fill_count", post_filter_fills)
                post_filter_allowed = loss_post.get("fill_count", post_filter_allowed)
                loss_post_filter_event_delta = loss_post.get("cumulative_pnl_delta_usdt")
                if isinstance(loss_waterfall, dict):
                    cumulative_pnl = loss_waterfall.get("current_cumulative_paper_pnl_usdt", cumulative_pnl)
                    post_filter_pnl = loss_waterfall.get("post_filter_pnl_delta_usdt", post_filter_pnl)
                elif loss_post_filter_event_delta is not None:
                    post_filter_pnl = loss_post_filter_event_delta
                post_filter_fees = loss_post.get("fee_usdt", post_filter_fees)
                blocker_distribution = loss_post.get("canary_profile_tightening_blocker_distribution")
                if isinstance(blocker_distribution, dict):
                    post_filter_churn = blocker_distribution.get("flip_churn_cooldown", post_filter_churn)
                if isinstance(loss_classification, dict):
                    classification = str(loss_classification.get("classification") or classification)
                    safety_classification = str(
                        loss_classification.get("post_filter_safety_classification")
                        or safety_classification
                    )
    blocked_1h = payload.get("post_filter_blocked_intents_1h")
    blocked_6h = payload.get("post_filter_blocked_intents_6h_window")
    no_unsafe_fills = (
        safety_classification == "POST_FILTER_NO_UNSAFE_FILLS"
        or (
            post_filter_fills == 0
            and post_filter_fees == 0
            and post_filter_churn == 0
        )
    )
    zero_fill_observation = post_filter_fills == 0 and (
        blocked_1h
        or blocked_6h
        or (outcome_guard_active and outcome_guard_events)
    )
    positive_edge_proven = classification == "POST_FILTER_POSITIVE_EDGE_PROVEN" and payload.get("paper_edge_positive_proven") is True
    historical_negative_pnl_isolated = (
        isinstance(cumulative_pnl, (int, float))
        and cumulative_pnl < 0
        and isinstance(post_filter_pnl, (int, float))
        and post_filter_pnl >= 0
        and no_unsafe_fills
    )
    if positive_edge_proven:
        paper_only_interpretation = "POST_FILTER_POSITIVE_EDGE_PROVEN"
    elif zero_fill_observation and no_unsafe_fills:
        paper_only_interpretation = "POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING"
    elif classification:
        paper_only_interpretation = classification
    else:
        paper_only_interpretation = "MISSING_EVIDENCE"
    return {
        "path": rel(PAPER_POST_FILTER),
        "generated_at": generated_at,
        "age_seconds": age,
        "status": "fresh" if age is not None and age <= 1800 else "stale_or_missing",
        "classification": classification,
        "post_filter_safety_classification": safety_classification,
        "paper_only_interpretation": paper_only_interpretation,
        "post_filter_window_start_utc": payload.get("post_filter_window_start_utc"),
        "post_filter_window_end_utc": payload.get("post_filter_window_end_utc"),
        "post_filter_window_seconds": payload.get("post_filter_window_seconds"),
        "cumulative_paper_pnl_usdt_pre_plus_post": cumulative_pnl,
        "post_filter_realized_pnl_delta_usdt": post_filter_pnl,
        "post_filter_simulated_fills": post_filter_fills,
        "post_filter_allowed_intents": post_filter_allowed,
        "post_filter_blocked_intents_1h": blocked_1h,
        "post_filter_blocked_intents_6h_window": blocked_6h,
        "post_filter_fees_usdt": post_filter_fees,
        "post_filter_churn_events": post_filter_churn,
        "outcome_guard_active": outcome_guard_active,
        "outcome_guard_start_utc": payload.get("outcome_guard_start_utc") or outcome_guard.get("start_utc"),
        "outcome_guard_fills": outcome_guard_fills,
        "outcome_guard_pnl_delta_usdt": outcome_guard_pnl,
        "outcome_guard_unsafe_fills": outcome_guard_unsafe,
        "paper_loss_attribution_override_active": loss_override_active,
        "paper_loss_attribution_generated_at": loss_generated_at,
        "paper_loss_attribution_post_filter_event_delta_usdt": loss_post_filter_event_delta,
        "no_unsafe_fills": no_unsafe_fills,
        "zero_fill_observation": bool(zero_fill_observation),
        "positive_edge_proven": positive_edge_proven,
        "historical_negative_pnl_isolated": historical_negative_pnl_isolated,
        "approves_live": payload.get("approves_live") is True,
        "approves_legacy_shutdown": payload.get("approves_legacy_shutdown") is True,
        "blockers": [] if classification else ["paper_post_filter_observation_missing"],
    }


def trade_permission_evidence() -> Dict[str, Any]:
    payload = read_json(TRADE_PERMISSION)
    if not isinstance(payload, dict):
        return {"path": rel(TRADE_PERMISSION), "status": "missing", "blockers": ["trade_permission_payload_missing"]}
    account_payload = read_json(ACCOUNT_POSITION)
    blockers = []
    trade_status = str(payload.get("trade_permission_status") or "")
    readonly_status = str(payload.get("readonly_account_evidence_status") or "")
    classes = payload.get("classifications") if isinstance(payload.get("classifications"), list) else []
    account_fail_closed = bool(isinstance(account_payload, dict) and account_payload.get("fail_closed") is True)
    readonly_account_monitor = bool(
        isinstance(account_payload, dict)
        and account_payload.get("exchange_call_invariant") == "READONLY_ACCOUNT_AND_POSITION_ENDPOINTS_ONLY"
        and account_payload.get("exchange_mutation_performed") is False
        and account_payload.get("exchange_action_taken") is False
        and account_payload.get("live_gate") == LIVE_GATE
        and account_payload.get("live_symbols") == []
    )
    if "UNKNOWN" in trade_status or "UNKNOWN" in " ".join(map(str, classes)):
        blockers.append("trade_permission_readonly_unknown")
    if "STALE" in readonly_status or "STALE" in " ".join(map(str, classes)):
        blockers.append("readonly_account_evidence_stale")
    operator_decision_required = "trade_permission_readonly_unknown" in blockers and account_fail_closed and readonly_account_monitor
    return {
        "path": rel(TRADE_PERMISSION),
        "account_position_path": rel(ACCOUNT_POSITION),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age_seconds(payload.get("generated_at")),
        "trade_permission_status": trade_status,
        "readonly_account_evidence_status": readonly_status,
        "account_monitor_fail_closed": account_fail_closed,
        "account_monitor_readonly_no_mutation": readonly_account_monitor,
        "paper_only_operator_decision_required": operator_decision_required,
        "paper_only_classification": "OPERATOR_DECISION_REQUIRED" if operator_decision_required else "BLOCKS_LEGACY_SHUTDOWN",
        "live_canary_classification": "P2_LIVE_ONLY_BLOCKED" if blockers else "INFO_ONLY",
        "margin_leverage_classifications": payload.get("margin_leverage_classifications", []),
        "classifications": classes,
        "blockers": blockers,
    }


def trainer_evidence() -> Dict[str, Any]:
    payload = read_json(TRAINER_BRIDGE)
    if not isinstance(payload, dict):
        return {"path": rel(TRAINER_BRIDGE), "status": "missing", "blockers": ["trainer_bridge_payload_missing"]}
    blockers = []
    runtime_status = str(payload.get("runtime_evidence_status") or payload.get("prediction_evidence_status") or "")
    accepted = payload.get("accepted_as_legacy_hybrid_prediction")
    if accepted is not True:
        blockers.append("trainer_bridge_not_legacy_hybrid_parity")
    if "WRAPPER_NOT_LEGACY_HYBRID_PARITY" in runtime_status:
        blockers.append("wrapper_not_legacy_hybrid_parity")
    if payload.get("checkpoint_evidence_status") in {"MISSING_OR_REJECTED", "MISSING"}:
        blockers.append("checkpoint_evidence_missing_or_rejected")
    for item in payload.get("trainer_full_parity_blockers") or []:
        blockers.append(str(item).lower())
    return {
        "path": rel(TRAINER_BRIDGE),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age_seconds(payload.get("generated_at")),
        "runtime_evidence_status": runtime_status,
        "prediction_evidence_status": payload.get("prediction_evidence_status"),
        "trainer_process_state": payload.get("trainer_process_state"),
        "accepted_as_legacy_hybrid_prediction": accepted,
        "model_checkpoint_id": payload.get("model_checkpoint_id"),
        "model_version": payload.get("model_version"),
        "checkpoint_id": payload.get("checkpoint_id"),
        "lineage_derivation_warnings": payload.get("lineage_derivation_warnings", []),
        "trainer_full_parity_blockers": payload.get("trainer_full_parity_blockers", []),
        "blockers": blockers,
    }


def trainer_derived_acceptance_evidence() -> Dict[str, Any]:
    matrix = read_json(TRAINER_DERIVED_ACCEPTANCE_MATRIX)
    go_no_go = read_text(TRAINER_DERIVED_ACCEPTANCE_GO_NO_GO).strip()
    codex_go_no_go = read_text(codex_output_dir(TRAINER_DERIVED_ACCEPTANCE_TASK_ID) / "CODEX_GO_NO_GO.md").strip()
    remaining_gaps = matrix.get("remaining_parity_gaps", []) if isinstance(matrix, dict) else []
    field_matrix = matrix.get("field_matrix", []) if isinstance(matrix, dict) else []
    operator_acceptance_required = bool(
        isinstance(matrix, dict)
        and matrix.get("operator_acceptance_required") is True
        and go_no_go == "V2_TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED"
        and codex_passed(TRAINER_DERIVED_ACCEPTANCE_TASK_ID)
        and TRAINER_DERIVED_ACCEPTANCE_PACKET.exists()
    )
    native_evidence_ready = bool(
        go_no_go == "V2_TRAINER_NATIVE_PARITY_EVIDENCE_READY"
        and codex_passed(TRAINER_DERIVED_ACCEPTANCE_TASK_ID)
    )
    return {
        "path": rel(TRAINER_DERIVED_ACCEPTANCE_MATRIX),
        "go_no_go_path": rel(TRAINER_DERIVED_ACCEPTANCE_GO_NO_GO),
        "packet_path": rel(TRAINER_DERIVED_ACCEPTANCE_PACKET),
        "codex_review_path": rel(codex_output_dir(TRAINER_DERIVED_ACCEPTANCE_TASK_ID) / "CODEX_GO_NO_GO.md"),
        "generated_at": matrix.get("generated_at") if isinstance(matrix, dict) else None,
        "go_no_go": go_no_go,
        "codex_go_no_go": codex_go_no_go,
        "operator_acceptance_required": operator_acceptance_required,
        "native_evidence_ready": native_evidence_ready,
        "operator_acceptance_scope": matrix.get("operator_acceptance_scope") if isinstance(matrix, dict) else None,
        "remaining_parity_gaps": remaining_gaps,
        "field_matrix": field_matrix,
        "live_ready": False,
        "live_gate": matrix.get("live_gate") if isinstance(matrix, dict) else None,
        "live_symbols": matrix.get("live_symbols") if isinstance(matrix, dict) else None,
    }


def symbol_evidence() -> Dict[str, Any]:
    payload, source_path = read_first_json([SYMBOL_UNIVERSE, SYMBOL_UNIVERSE_ALT])
    if not isinstance(payload, dict):
        return {"path": rel(SYMBOL_UNIVERSE), "status": "missing", "blockers": ["symbol_universe_payload_missing"]}
    blockers = []
    live_symbols = payload.get("live_symbols") if isinstance(payload.get("live_symbols"), list) else []
    age = age_seconds(payload.get("generated_at"))
    if age is None or age > 300:
        blockers.append("symbol_universe_payload_stale")
    if live_symbols:
        blockers.append("live_symbols_not_empty")
    if payload.get("live_gate") != LIVE_GATE:
        blockers.append("symbol_universe_live_gate_not_blocked")
    return {
        "path": rel(source_path) if source_path else rel(SYMBOL_UNIVERSE),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age,
        "live_gate": payload.get("live_gate"),
        "live_symbols": live_symbols,
        "paper_symbols": payload.get("paper_symbols"),
        "training_symbols": payload.get("training_symbols"),
        "blockers": blockers,
    }


def worker_evidence() -> Dict[str, Any]:
    payload = read_json(WORKER_STATE)
    if not isinstance(payload, dict):
        return {"path": rel(WORKER_STATE), "status": "missing", "blockers": ["worker_porting_state_missing"]}
    blockers = []
    if payload.get("live_gate") != LIVE_GATE:
        blockers.append("worker_porting_live_gate_not_blocked")
    if payload.get("final_approval_token") != "absent":
        blockers.append("worker_porting_final_approval_not_absent")
    if payload.get("redis_trim_approval") != "absent":
        blockers.append("worker_porting_redis_trim_approval_not_absent")
    if payload.get("legacy_backfill_required_workers"):
        blockers.append("legacy_baseline_backfill_required")
    if payload.get("blocked_workers"):
        blockers.append("worker_porting_blocked_workers")
    progress_p0 = payload.get("progress_p0") if isinstance(payload.get("progress_p0"), dict) else {}
    if progress_p0.get("complete") != progress_p0.get("total"):
        blockers.append("p0_workers_incomplete")
    return {
        "path": rel(WORKER_STATE),
        "as_of_utc": payload.get("as_of_utc"),
        "age_seconds": age_seconds(payload.get("as_of_utc")),
        "v2_local_online_state": payload.get("v2_local_online_state"),
        "progress_p0": payload.get("progress_p0"),
        "progress_p1": payload.get("progress_p1"),
        "progress_p2": payload.get("progress_p2"),
        "legacy_backfill_required_workers": payload.get("legacy_backfill_required_workers", []),
        "blocked_workers": payload.get("blocked_workers", []),
        "next_action": payload.get("next_action"),
        "blockers": blockers,
    }


def risk_gateway_test_evidence() -> Dict[str, Any]:
    test_paths = [
        ROOT / "v2/backend/tests/integration/cli/test_v2_risk_gateway_runtime_worker.py",
        ROOT / "v2/backend/tests/unit/services/risk_gateway/test_legacy_gate_evaluators.py",
        ROOT / "v2/backend/tests/unit/services/risk_legacy_gates/test_evaluators.py",
    ]
    source_paths = [
        ROOT / "v2/backend/app/services/risk_gateway/kill_switch.py",
        ROOT / "v2/backend/app/services/risk_gateway/halt_manager.py",
        ROOT / "v2/backend/app/services/risk_gateway/reduce_only_latch.py",
        ROOT / "v2/backend/app/services/risk_gateway/intelligent_close_guard.py",
        ROOT / "v2/backend/app/services/risk_gateway/auto_deleverager.py",
        ROOT / "v2/backend/app/services/risk_gateway/shared_risk_gate.py",
        ROOT / "v2/backend/app/services/risk_gateway/margin_governor.py",
        ROOT / "v2/backend/app/services/risk_gateway/phase_controller.py",
        ROOT / "v2/backend/app/services/risk_gateway/adaptive_gate.py",
        ROOT / "v2/backend/app/services/risk_gateway/evaluators.py",
        ROOT / "v2/backend/app/services/risk_legacy_gates/evaluators.py",
        ROOT / "v2/backend/app/services/risk_legacy_gates/inputs.py",
        ROOT / "v2/backend/app/services/risk_legacy_gates/verdict.py",
    ]
    required_terms = {
        "kill_switch": ["kill_switch", "evaluate_kill_switch_state"],
        "halt_manager": ["halt_manager", "evaluate_halt_state"],
        "reduce_only": ["reduce_only", "reduce_only_latch", "evaluate_latch_state"],
        "intelligent_close_guard": ["intelligent_close_guard", "evaluate_close_guard"],
        "auto_deleverager": ["auto_deleverager", "evaluate_adl_state"],
        "shared_risk": ["shared_risk", "shared_risk_gate", "evaluate_budget_state"],
        "margin_governor": ["margin_governor", "evaluate_margin_state"],
        "phase_controller": ["phase_controller", "evaluate_phase_gate"],
        "adaptive_gate": ["adaptive_gate", "microstructure_toxicity", "evaluate_toxicity_block"],
    }
    test_text = "\n".join(read_text(path) for path in test_paths if path.exists())
    source_text = "\n".join(read_text(path) for path in source_paths if path.exists())
    present = []
    missing = []
    for term, aliases in required_terms.items():
        if any(alias in test_text for alias in aliases) and any(alias in source_text for alias in aliases):
            present.append(term)
        else:
            missing.append(term)
    return {
        "path": rel(test_paths[0]),
        "test_paths": [rel(path) for path in test_paths],
        "source_paths": [rel(path) for path in source_paths],
        "exists": any(path.exists() for path in test_paths),
        "required_terms": list(required_terms),
        "present_terms": present,
        "missing_terms": missing,
        "status": "pass_or_present" if any(path.exists() for path in test_paths) and not missing else "missing_or_incomplete",
    }


def worker_parity_marker(worker_id: str) -> Dict[str, Any]:
    candidates = [
        WORKER_DIR / f"codex_{worker_id}_go_no_go.md",
        WORKER_DIR / f"codex_{worker_id}_review.md",
        WORKER_DIR / f"codex_{worker_id}_and_liquidation_bridge_from_legacy_baseline_review.md",
    ]
    text = "\n".join(read_text(path) for path in candidates if path.exists())
    pass_tokens = [
        f"{worker_id.upper()}_CODEX_PASS",
        "GO. ",
        "No blocking findings",
    ]
    return {
        "worker_id": worker_id,
        "candidate_paths": [rel(path) for path in candidates],
        "pass_evidence_present": any(token in text for token in pass_tokens),
    }


def queue_evidence() -> Dict[str, Any]:
    queue = read_json(QUEUE_STATUS)
    current = read_json(CURRENT_STATUS)
    lock = read_json(NON_DRIFT_LOCK)
    return {
        "queue_status_path": rel(QUEUE_STATUS),
        "current_status_path": rel(CURRENT_STATUS),
        "queue_generated_at": queue.get("generated_at") if isinstance(queue, dict) else None,
        "current_task_id": current.get("task_id") if isinstance(current, dict) else None,
        "current_status": current.get("status") if isinstance(current, dict) else None,
        "next_pending_task": queue.get("next_pending_task") if isinstance(queue, dict) else None,
        "human_attention_required_count": queue.get("human_attention_required_count") if isinstance(queue, dict) else None,
        "blocked_quota": queue.get("blocked_quota") if isinstance(queue, dict) else None,
        "non_drift_selected_task": lock.get("selected_task_id") if isinstance(lock, dict) else None,
    }


def observatory_evidence() -> Dict[str, Any]:
    payload = read_json(OBSERVATORY_PAYLOAD)
    if not isinstance(payload, dict) or not payload:
        return {
            "path": rel(OBSERVATORY_PAYLOAD),
            "status": "missing",
            "go_no_go": None,
            "blockers": ["observatory_payload_missing"],
            "edge_action_required": False,
            "trainer_action_required": False,
            "legacy_signal_comparison_classification": "MISSING_EVIDENCE_CANNOT_COMPARE",
        }
    go_no_go = str(payload.get("go_no_go") or "")
    paper_edge_status = str(payload.get("paper_edge_status") or "")
    decision_quality = str(payload.get("v2_decision_quality") or "")
    legacy_signal_health = str(payload.get("legacy_signal_health") or "")
    trainer_gaps = [str(item) for item in payload.get("trainer_parity_gaps") or []]
    edge_action_required = (
        go_no_go == "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY"
        and (
            paper_edge_status in {"EDGE_PENDING", "POST_FILTER_EDGE_PENDING", "POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING"}
            or decision_quality == "EDGE_PENDING_INSUFFICIENT_SAMPLE"
        )
    )
    trainer_status = read_json(TRAINER_BRIDGE)
    trainer_parity_status = (
        str(trainer_status.get("trainer_parity_status") or "")
        if isinstance(trainer_status, dict)
        else ""
    )
    trainer_action_required = (
        trainer_parity_status != "FULL_LEGACY_PARITY_READY"
        or bool(trainer_gaps)
    )
    signal_comparison = (
        "MISSING_EVIDENCE_CANNOT_COMPARE"
        if legacy_signal_health == "STALE"
        else str(payload.get("legacy_v2_agreement") or "MISSING_EVIDENCE_CANNOT_COMPARE")
    )
    blockers: List[str] = []
    if go_no_go != "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY":
        blockers.append("observatory_not_ready")
    if edge_action_required:
        blockers.append("observatory_edge_pending_requires_paper_edge_recovery")
    if trainer_action_required:
        blockers.append("observatory_trainer_full_parity_not_ready")
    if legacy_signal_health == "STALE":
        blockers.append("observatory_legacy_signals_stale")
    return {
        "path": rel(OBSERVATORY_PAYLOAD),
        "status": "present",
        "generated_at": payload.get("generated_at"),
        "go_no_go": go_no_go,
        "legacy_trainer_health": payload.get("legacy_trainer_health"),
        "legacy_signal_health": legacy_signal_health,
        "legacy_signal_comparison_classification": signal_comparison,
        "legacy_v2_agreement": payload.get("legacy_v2_agreement"),
        "v2_decision_quality": decision_quality,
        "paper_pnl_visible": payload.get("paper_pnl_visible"),
        "paper_edge_status": paper_edge_status,
        "paper_edge_pending": edge_action_required,
        "edge_action_required": edge_action_required,
        "trainer_parity_status": trainer_parity_status,
        "trainer_parity_gaps": trainer_gaps,
        "trainer_action_required": trainer_action_required,
        "post_filter_fill_interpretation": (
            "POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING"
            if paper_edge_status in {"EDGE_PENDING", "POST_FILTER_EDGE_PENDING"}
            else paper_edge_status
        ),
        "minimum_sample_policy": "EDGE_PENDING_INSUFFICIENT_SAMPLE cannot claim 99% correctness",
        "blockers": blockers,
    }


def blocker(blocker_id: str, category: str, evidence: str, remediation_task_id: Optional[str] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"id": blocker_id, "category": category, "evidence": evidence}
    if remediation_task_id:
        item["remediation_task_id"] = remediation_task_id
    return item


def collect_blockers(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    safety = evidence["runtime_safety"]
    if safety["final_approval_token"] != "absent":
        blockers.append(blocker("FINAL_APPROVAL_TOKEN_PRESENT", "P0_SHUTDOWN_BLOCKER", "final live approval token exists"))
    if safety["redis_trim_approval"] != "absent":
        blockers.append(blocker("REDIS_TRIM_APPROVAL_PRESENT", "P0_SHUTDOWN_BLOCKER", "Redis trim approval token exists"))
    if safety["live_gate"] != LIVE_GATE:
        blockers.append(blocker("LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY", "P0_SHUTDOWN_BLOCKER", f"observed gates: {safety['observed_live_gate_values']}"))
    if safety["live_symbols"]:
        blockers.append(blocker("LIVE_SYMBOLS_NOT_EMPTY", "P0_SHUTDOWN_BLOCKER", f"live_symbols={safety['live_symbols']}"))
    for key in ("old_redis_writes_absent", "exchange_actions_absent", "leverage_changes_absent", "margin_mode_changes_absent"):
        if not safety.get(key):
            blockers.append(blocker(key.replace("_absent", "_OBSERVED").upper(), "P0_SHUTDOWN_BLOCKER", f"{key}=false"))

    corrupted, corruption_evidence = evidence["git_corruption"]
    if corrupted:
        blockers.append(blocker("GIT_CORRUPTION_DETECTED", "P0_SHUTDOWN_BLOCKER", corruption_evidence))

    closure = evidence["closure"]
    if (closure.get("copied_source_files_on_disk") or 0) < 248:
        blockers.append(blocker("FULL_RUNTIME_CLOSURE_FILE_COUNT_MISMATCH", "P0_SHUTDOWN_BLOCKER", f"copied={closure.get('copied_source_files_on_disk')} expected_at_least=248"))
    if closure.get("binary_checkpoint_blobs_inventoried_only") != 139:
        blockers.append(blocker("BINARY_CHECKPOINT_INVENTORY_MISMATCH", "P0_SHUTDOWN_BLOCKER", f"binary_count={closure.get('binary_checkpoint_blobs_inventoried_only')} expected=139"))
    if not closure.get("full_runtime_manifest_valid"):
        blockers.append(blocker("FULL_RUNTIME_MANIFEST_MISSING_OR_INVALID", "P0_SHUTDOWN_BLOCKER", f"{rel(CLOSURE_FULL_MANIFEST)} missing or invalid"))
    if closure.get("genuine_unresolved_items"):
        blockers.append(
            blocker(
                "UNRESOLVED_LOCAL_IMPORTS",
                "P0_SHUTDOWN_BLOCKER",
                "remaining: " + ", ".join(closure["genuine_unresolved_items"]),
                "claude_resolve_remaining_unresolved_local_imports",
            )
        )

    worker = evidence["worker_porting"]
    for item in worker.get("blockers", []):
        task = "claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis" if item == "legacy_baseline_backfill_required" else None
        if task and codex_passed(task):
            continue
        blockers.append(blocker(item.upper(), "P0_SHUTDOWN_BLOCKER", f"worker_porting: {item}", task))

    risk_tests = evidence["risk_gateway_tests"]
    if risk_tests.get("missing_terms"):
        blockers.append(
            blocker(
                "RISK_GATEWAY_LEGACY_PARITY_TESTS_MISSING",
                "P0_SHUTDOWN_BLOCKER",
                "missing terms: " + ", ".join(risk_tests["missing_terms"]),
                "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map",
            )
        )

    parity_markers = evidence["worker_parity_markers"]
    if not parity_markers.get("v2_signal_publisher", {}).get("pass_evidence_present"):
        blockers.append(
            blocker(
                "SIGNAL_PUBLISHER_PARITY_MISSING_OR_UNPROVEN",
                "P0_SHUTDOWN_BLOCKER",
                "no Codex PASS evidence for v2_signal_publisher legacy schema parity",
                "claude_port_v2_signal_publisher_from_legacy_schema",
            )
        )
    if not parity_markers.get("v2_orchestrator_adapter", {}).get("pass_evidence_present"):
        blockers.append(
            blocker(
                "ORCHESTRATOR_ADAPTER_PARITY_MISSING_OR_UNPROVEN",
                "P1_SHUTDOWN_SUPPORT",
                "no Codex PASS evidence for v2_orchestrator_adapter parity",
                "claude_remediate_v2_orchestrator_adapter_legacy_parity",
            )
        )
    for worker_id, task_id in [
        ("v2_market_ingestor_from_legacy_baseline", "claude_remediate_v2_market_ingestor_full_runtime_sha_backfill"),
        ("v2_coinank_and_liquidation_bridge_from_legacy_baseline", "claude_remediate_v2_coinank_liquidation_full_runtime_sha_backfill"),
        ("v2_feature_pipeline_and_ta_worker_from_legacy_baseline", "claude_remediate_v2_feature_pipeline_ta_full_runtime_sha_backfill"),
    ]:
        if not parity_markers.get(worker_id, {}).get("pass_evidence_present"):
            blockers.append(
                blocker(
                    "BASELINE_INGESTOR_PORTS_NOT_FULLY_SHA_PROVEN",
                    "P0_SHUTDOWN_BLOCKER",
                    f"{worker_id} Codex PASS/full-runtime SHA evidence missing or unproven",
                    task_id,
                )
            )

    trainer = evidence["trainer_bridge"]
    trainer_acceptance = evidence.get("trainer_derived_acceptance", {})
    for item in trainer.get("blockers", []):
        blocker_id = "WRAPPER_NOT_LEGACY_HYBRID_PARITY" if "wrapper" in item or "legacy_hybrid" in item else item.upper()
        if blocker_id in TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS and trainer_acceptance.get("native_evidence_ready"):
            continue
        task_id = (
            TRAINER_DERIVED_ACCEPTANCE_TASK_ID
            if blocker_id in TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS and codex_passed(TRAINER_LINEAGE_ATTRIBUTION_TASK_ID)
            else TRAINER_LINEAGE_ATTRIBUTION_TASK_ID
            if blocker_id in TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS
            else "claude_port_v2_trainer_bridge_full_legacy_parity"
        )
        category = "P0_SHUTDOWN_BLOCKER"
        evidence_text = f"trainer_bridge: {item}"
        if blocker_id in TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS and trainer_acceptance.get("operator_acceptance_required"):
            category = "OPERATOR_DECISION_REQUIRED"
            evidence_text = (
                f"trainer_bridge: {item}; native trainer evidence was not found and "
                "TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET requires explicit operator acceptance "
                "for V2 paper-only shutdown evaluation; live/canary remain blocked"
            )
        item_payload = blocker(
            blocker_id,
            category,
            evidence_text,
            task_id,
        )
        if category == "OPERATOR_DECISION_REQUIRED":
            item_payload["decision_packet"] = trainer_acceptance.get("packet_path")
            item_payload["go_no_go"] = trainer_acceptance.get("go_no_go")
        blockers.append(item_payload)

    packages = evidence["trainer_external_packages"]
    if packages.get("missing"):
        blockers.append(
            blocker(
                "TRAINER_EXTERNAL_DEPS_MISSING_IN_V2_VENV",
                "OPERATOR_DECISION_REQUIRED",
                "missing packages: " + ", ".join(packages["missing"]),
                "claude_port_v2_trainer_bridge_full_legacy_parity",
            )
        )

    paper = evidence["paper_runtime"]
    post_filter = evidence.get("paper_post_filter", {})
    shadow_outcome = evidence.get("paper_shadow_outcome", {})
    if not codex_passed("claude_replay_paper_edge_repair_from_legacy_trainer_output"):
        paper_task_id = "claude_replay_paper_edge_repair_from_legacy_trainer_output"
    elif not codex_passed(PAPER_EDGE_POST_FILTER_TASK_ID):
        paper_task_id = PAPER_EDGE_POST_FILTER_TASK_ID
    else:
        paper_task_id = PAPER_EDGE_RECOVERY_TASK_ID
    for item in paper.get("blockers", []):
        if item == "paper_realized_pnl_negative":
            bid = "PAPER_PNL_NEGATIVE_BLOCKS_CANARY"
        elif item == "paper_position_outcome_pending":
            bid = "PAPER_EDGE_UNPROVEN"
        elif "fill" in item:
            bid = "PAPER_EDGE_UNPROVEN"
        else:
            bid = item.upper()
        category = "P0_SHUTDOWN_BLOCKER"
        evidence_text = f"paper_runtime: {item}"
        if bid == "PAPER_PNL_NEGATIVE_BLOCKS_CANARY" and post_filter.get("historical_negative_pnl_isolated"):
            category = "P2_LIVE_ONLY_BLOCKED"
            evidence_text = (
                f"paper_runtime: {item}; cumulative loss is pre-filter/historical while "
                f"post_filter_pnl_delta={post_filter.get('post_filter_realized_pnl_delta_usdt')} and "
                f"post_filter_safety={post_filter.get('post_filter_safety_classification')}"
            )
        elif bid == "PAPER_EDGE_UNPROVEN" and post_filter.get("no_unsafe_fills") and not post_filter.get("positive_edge_proven"):
            if item == "paper_position_outcome_pending":
                evidence_text = (
                    "paper_position_outcome_pending: a strict-gate paper-only position is open; "
                    "positive edge is not proven until the position closes net-positive after fees/slippage; "
                    f"open_position_count={paper.get('open_position_count')} "
                    f"unrealized_pnl={paper.get('unrealized_pnl')}"
                )
            else:
                evidence_text = (
                    "post_filter_edge_pending: no unsafe post-filter fills observed, but positive edge is not proven; "
                    f"shadow_outcome={shadow_outcome.get('outcome_status') or 'missing'} "
                    f"completed={shadow_outcome.get('completed_observations')} "
                    f"pending={shadow_outcome.get('pending_observations')}"
                )
        blockers.append(blocker(bid, category, evidence_text, paper_task_id))

    paper_shadow = evidence["paper_shadow"]
    for item in paper_shadow.get("blockers", []):
        blockers.append(blocker(item.upper(), "P0_SHUTDOWN_BLOCKER", f"paper_shadow: {item}", "claude_audit_stale_public_payloads_and_freshness_guard"))

    edge = evidence["paper_edge"]
    for item in edge.get("blockers", []):
        bid = "PAPER_PNL_NEGATIVE_BLOCKS_CANARY" if "negative" in item else "PAPER_EDGE_UNPROVEN"
        category = "P0_SHUTDOWN_BLOCKER"
        evidence_text = f"paper_edge: {item}"
        if bid == "PAPER_PNL_NEGATIVE_BLOCKS_CANARY" and post_filter.get("historical_negative_pnl_isolated"):
            category = "P2_LIVE_ONLY_BLOCKED"
            evidence_text = (
                f"paper_edge: {item}; historical negative PnL remains visible, but post-filter "
                f"window has pnl_delta={post_filter.get('post_filter_realized_pnl_delta_usdt')}, "
                f"fills={post_filter.get('post_filter_simulated_fills')}, and no unsafe fills"
            )
        elif bid == "PAPER_EDGE_UNPROVEN" and post_filter.get("no_unsafe_fills") and not post_filter.get("positive_edge_proven"):
            evidence_text = (
                "paper_edge: post-filter no unsafe fills, but edge remains pending because "
                "there are no positive post-filter fill outcomes; "
                f"shadow_outcome={shadow_outcome.get('outcome_status') or 'missing'} "
                f"completed={shadow_outcome.get('completed_observations')} "
                f"pending={shadow_outcome.get('pending_observations')}"
            )
        blockers.append(blocker(bid, category, evidence_text, paper_task_id))

    edge_recovery = evidence.get("paper_edge_recovery", {})
    for item in edge_recovery.get("blockers", []):
        if item == "paper_exit_outcome_simulator_missing":
            blockers.append(
                blocker(
                    "PAPER_EXIT_OUTCOME_SIMULATOR_MISSING",
                    "P0_SHUTDOWN_BLOCKER",
                    "paper_edge_recovery: fee-charging paper fills are blocked until a non-live paper exit/outcome simulator exists",
                    PAPER_EDGE_RECOVERY_TASK_ID,
                )
            )
        elif item == "paper_positive_edge_not_proven":
            blockers.append(
                blocker(
                    "PAPER_EDGE_UNPROVEN",
                    "P0_SHUTDOWN_BLOCKER",
                    "paper_edge_recovery: positive edge is not proven after the cost-aware/outcome guard",
                    PAPER_EDGE_RECOVERY_TASK_ID,
                )
            )
        else:
            blockers.append(
                blocker(
                    item.upper(),
                    "P0_SHUTDOWN_BLOCKER",
                    f"paper_edge_recovery: {item}",
                    PAPER_EDGE_RECOVERY_TASK_ID,
                )
            )

    if shadow_outcome.get("blockers"):
        blockers.append(
            blocker(
                "PAPER_SHADOW_OUTCOME_OBSERVER_STALE_OR_MISSING",
                "P0_SHUTDOWN_BLOCKER",
                "paper_shadow_outcome_observer: " + ", ".join(map(str, shadow_outcome.get("blockers") or [])),
            )
        )

    observatory = evidence.get("observatory", {})
    if observatory.get("edge_action_required") and not codex_passed(PAPER_EDGE_RECOVERY_TASK_ID):
        blockers.append(
            blocker(
                "OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED",
                "P0_SHUTDOWN_BLOCKER",
                "observatory: "
                f"decision_quality={observatory.get('v2_decision_quality')} "
                f"paper_edge={observatory.get('paper_edge_status')} "
                "requires cost-aware paper edge recovery; post-filter no-fill is not positive edge",
                PAPER_EDGE_RECOVERY_TASK_ID,
            )
        )
    if (
        observatory.get("trainer_action_required")
        and not observatory.get("trainer_parity_status") == "FULL_LEGACY_PARITY_READY"
        and not (
            trainer_acceptance.get("operator_acceptance_required")
            and codex_passed(TRAINER_DERIVED_ACCEPTANCE_TASK_ID)
        )
    ):
        trainer_task = (
            TRAINER_DERIVED_ACCEPTANCE_TASK_ID
            if codex_passed("claude_port_v2_trainer_bridge_full_legacy_parity")
            else "claude_port_v2_trainer_bridge_full_legacy_parity"
        )
        blockers.append(
            blocker(
                "OBSERVATORY_TRAINER_FULL_PARITY_REQUIRED",
                "P0_SHUTDOWN_BLOCKER",
                "observatory: trainer parity is not FULL_LEGACY_PARITY_READY; "
                f"remaining_gaps={observatory.get('trainer_parity_gaps')}",
                trainer_task,
            )
        )
    if observatory.get("legacy_signal_health") == "STALE":
        blockers.append(
            blocker(
                "OBSERVATORY_LEGACY_SIGNALS_STALE_SOURCE_LIMITED",
                "INFO_ONLY",
                "observatory: legacy signals are stale; classify comparison as MISSING_EVIDENCE_CANNOT_COMPARE and do not invent outcomes",
            )
        )
    if observatory.get("v2_decision_quality") == "EDGE_PENDING_INSUFFICIENT_SAMPLE":
        blockers.append(
            blocker(
                "OBSERVATORY_DECISION_QUALITY_INSUFFICIENT_SAMPLE",
                "INFO_ONLY",
                "observatory: insufficient acted-trade sample; keep no-trade/outcome observation active and do not claim 99% correctness",
            )
        )

    trade = evidence["trade_permission"]
    for item in trade.get("blockers", []):
        category = "OPERATOR_DECISION_REQUIRED" if trade.get("paper_only_operator_decision_required") else "P0_SHUTDOWN_BLOCKER"
        evidence_text = f"trade_permission: {item}"
        if trade.get("paper_only_operator_decision_required"):
            evidence_text = (
                f"trade_permission: {item}; account monitor is fail-closed/read-only with no exchange mutation, "
                "so this blocks live/canary and requires explicit operator decision for paper-only shutdown"
            )
        blockers.append(
            blocker(
                "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY" if "permission" in item else item.upper(),
                category,
                evidence_text,
                "claude_remediate_account_position_monitor_shutdown_parity",
            )
        )

    symbol = evidence["symbol_universe"]
    for item in symbol.get("blockers", []):
        blockers.append(blocker(item.upper(), "P0_SHUTDOWN_BLOCKER", f"symbol_universe: {item}", "claude_audit_stale_public_payloads_and_freshness_guard"))

    public = evidence["public_freshness"]
    if public.get("stale_count"):
        blockers.append(
            blocker(
                "FRESHNESS_GUARD_BLOCKED_ON_STALE_PUBLIC_ARTIFACTS",
                "P0_SHUTDOWN_BLOCKER",
                f"stale public latest JSON count={public.get('stale_count')}",
                "claude_audit_stale_public_payloads_and_freshness_guard",
            )
        )

    services = evidence["service_liveness"]
    if services.get("inactive_units"):
        blockers.append(blocker("V2_SERVICES_INACTIVE", "P0_SHUTDOWN_BLOCKER", "inactive units: " + ", ".join(services["inactive_units"])))

    return dedupe_blockers(blockers)


def dedupe_blockers(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (item.get("id"), item.get("remediation_task_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def core_v2_paper_ready(evidence: Dict[str, Any]) -> bool:
    safety = evidence["runtime_safety"]
    worker = evidence["worker_porting"]
    paper = evidence["paper_runtime"]
    return (
        safety["live_gate"] == LIVE_GATE
        and safety["final_approval_token"] == "absent"
        and safety["redis_trim_approval"] == "absent"
        and safety["live_symbols"] == []
        and worker.get("v2_local_online_state") == "V2_LOCAL_ONLINE_P0_READY_PAPER_SHADOW_ONLY"
        and paper.get("status") == "fresh"
    )


def classify_shutdown(evidence: Dict[str, Any], blockers: List[Dict[str, Any]]) -> str:
    if not blockers and core_v2_paper_ready(evidence):
        return SAFE
    non_trainer_blockers = [
        item
        for item in blockers
        if item.get("id")
        not in {
            "WRAPPER_NOT_LEGACY_HYBRID_PARITY",
            "TRAINER_BRIDGE_NOT_LEGACY_HYBRID_PARITY",
            "CHECKPOINT_EVIDENCE_MISSING_OR_REJECTED",
            "TRAINER_EXTERNAL_DEPS_MISSING_IN_V2_VENV",
            *TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS,
        }
    ]
    if core_v2_paper_ready(evidence) and not non_trainer_blockers:
        return KEEP
    return BLOCK


def task_output_dir(task_id: str) -> Path:
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/trainer_lineage_attribution_parity/latest"
    if task_id == TRAINER_DERIVED_ACCEPTANCE_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest"
    if task_id == PAPER_EDGE_POST_FILTER_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/paper_edge_post_filter_observation_window/latest"
    if task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/paper_edge_recovery/latest"
    return OUT / "claude_tasks" / task_id


def review_task_id_for(task_id: str) -> str:
    return CODEX_REVIEW_IDS.get(task_id, f"codex_review_{task_id}")


def codex_output_dir(task_id: str) -> Path:
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/trainer_lineage_attribution_parity/latest/codex_review"
    if task_id == TRAINER_DERIVED_ACCEPTANCE_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest/codex_review"
    if task_id == PAPER_EDGE_POST_FILTER_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/paper_edge_post_filter_observation_window/latest/codex_review"
    if task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/paper_edge_recovery/latest/codex_review"
    return OUT / "codex_reviews" / review_task_id_for(task_id)


def upper_token(task_id: str, suffix: str) -> str:
    return task_id.upper().replace("-", "_") + "_" + suffix


def claude_prompt(task_id: str) -> str:
    common = (
        "You are Claude running under the AI BOT REBUILD supervisor.\n"
        "Scope: write only inside /home/wali/Desktop/AI BOT REBUILD. Read the legacy bot tree only as reference evidence. "
        "Use BEGIN_FILE blocks for every file you change; do not attempt direct filesystem writes from headless mode. "
        "Do not mutate legacy files, old Redis, exchange state, leverage, margin mode, or live trading. "
        "Do not create final approval or Redis trim approval tokens. Keep live_gate=blocked_human_only and live_symbols=[] in all payloads.\n\n"
    )
    out = rel(task_output_dir(task_id))
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return (
            common
            + "Task: Implement V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_REMEDIATION_READY honestly. "
            "The V2 trainer bridge has legacy hybrid trainer log evidence, checkpoint evidence, and validated CUDA/GPU dependency evidence, "
            "but shutdown remains blocked by LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED, "
            "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED, and LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE. "
            "Do not fabricate native trainer parity.\n\n"
            "Inspect the V2 trainer bridge implementation, preserved rl/hybrid_trainer.py, rl/confidence_gates.py, "
            "rl/calibrated_confidence.py when present, rl/decision_trace.py, rl/unified_feature_builder.py, rl/obs_schema.py, "
            "rl/feature_health.py, current trainer log evidence read-only, V2 feature snapshot builder payload, "
            "V2 feature pipeline and TA payload, and Symbol Universe payload.\n\n"
            "Build explicit field classifications using only these values: NATIVE_FIELD_PRESENT, DERIVED_FROM_LEGACY_LOG, "
            "MISSING_EVIDENCE, INCOMPLETE_ATTRIBUTION, ACCEPTED_FOR_PAPER_ONLY, BLOCKS_LEGACY_SHUTDOWN. "
            "For feature_snapshot_id, do not invent a native ID. If the legacy trainer log lacks an explicit feature_snapshot_id, "
            "keep DERIVED_FROM_LEGACY_LOG and link prediction evidence to the nearest V2 feature snapshot by timestamp, symbol, "
            "and timeframe only when freshness and symbol scope match. Label that link derived_feature_snapshot_link. "
            "For confidence calibration, map raw and calibrated confidence from preserved code or logs; if calibration is inferred, "
            "label it DERIVED_FROM_LEGACY_LOG. For feature attribution, use actual model or explanation evidence only; otherwise emit "
            "FEATURE_ATTRIBUTION_INCOMPLETE and keep full parity blocked. Add missing, stale, and unused feature flags from the V2 "
            "feature snapshot payload. Never fabricate SHAP or importance values.\n\n"
            "Update v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json with prediction_id, "
            "feature_snapshot_id, feature_snapshot_link_mode, raw_confidence, calibrated_confidence, confidence_calibration_mode, "
            "top_positive_features, top_negative_features, missing_feature_flags, stale_feature_flags, unused_feature_flags, "
            "checkpoint_id, model_version, symbol_universe_scope, trainer_parity_status, and remaining_parity_gaps. "
            "Add or extend trainer bridge tests for derived feature_snapshot_id labeling, derived confidence calibration labeling, "
            "missing attribution blocking full parity, no fake attribution, native evidence clearing only the exact native blocker, "
            "live_gate remaining blocked_human_only, old Redis absence, and exchange method absence.\n\n"
            "If code, test, or payload changes are needed, emit BEGIN_FILE blocks for those files before the report. "
            "Output these required files exactly:\n"
            f"BEGIN_FILE: {out}/V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_REPORT.md\n"
            "...report with inspected evidence, classification table, tests run, and remaining gaps...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/trainer_lineage_attribution_status.json\n"
            "{\"task_id\":\"claude_v2_trainer_lineage_attribution_parity_remediation\",\"live_gate\":\"blocked_human_only\","
            "\"trainer_lineage_attribution_status\":\"BLOCKED_OR_READY\",\"remaining_parity_gaps\":[]}\n"
            "END_FILE\n\n"
            "The GO_NO_GO.md body must contain exactly one line. Use READY only if native evidence clears the blockers; "
            "otherwise keep BLOCKED.\n"
            f"BEGIN_FILE: {out}/GO_NO_GO.md\n"
            "V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_BLOCKED\n"
            "END_FILE\n"
        )
    if task_id == TRAINER_DERIVED_ACCEPTANCE_TASK_ID:
        return (
            common
            + "Task: Implement V2_TRAINER_DERIVED_EVIDENCE_ACCEPTANCE_OR_NATIVE_PARITY_PACKET_READY. "
            "The trainer bridge is no longer blocked by WRAPPER_NOT_LEGACY_HYBRID_PARITY, but shutdown remains blocked because "
            "feature_snapshot_id and confidence calibration are derived from legacy logs and feature attribution is incomplete. "
            "Determine whether native legacy or V2 trainer evidence can be produced. If native evidence is unavailable, create an "
            "explicit operator acceptance packet for V2 paper-only shutdown without claiming full live or canary readiness.\n\n"
            "Inspect: current v2_trainer_bridge payload; preserved rl/hybrid_trainer.py, rl/unified_feature_builder.py, rl/obs_schema.py, "
            "rl/confidence_gates.py, rl/calibrated_confidence.py if present, rl/decision_trace.py, and rl/feature_health.py; preserved "
            "trainer logs/read-only evidence; v2_feature_snapshot_builder payload; v2_feature_pipeline_and_ta_worker payload; and Symbol "
            "Universe payload.\n\n"
            "Try to locate native evidence for feature_snapshot_id, confidence_raw, confidence_calibrated, top positive features, top "
            "negative features, and stale/missing/unused feature flags. Classify each field using only: NATIVE_FIELD_PRESENT, "
            "DERIVED_FROM_LEGACY_LOG, DERIVED_FROM_V2_SNAPSHOT_LINK, MISSING_EVIDENCE, or INCOMPLETE_ATTRIBUTION. If native evidence "
            "exists, wire it into the V2 trainer bridge payload, update tests, and leave live blocked. If native evidence does not exist, "
            "keep blockers honest and write TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md stating clearly that derived evidence "
            "may be acceptable for V2 paper-only shutdown only if the operator explicitly accepts it, is not acceptable for live/canary "
            "readiness, and live remains blocked_human_only. Never fabricate feature attribution and never label derived evidence as native.\n\n"
            "Output these required files exactly:\n"
            f"BEGIN_FILE: {out}/TRAINER_DERIVED_EVIDENCE_ACCEPTANCE_REPORT.md\n"
            "...report with inspected sources, native-evidence search result, tests run, and remaining gaps...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/trainer_field_evidence_matrix.json\n"
            "{\"task_id\":\"claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet\","
            "\"live_gate\":\"blocked_human_only\",\"field_matrix\":[],\"operator_acceptance_required\":true}\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md\n"
            "...operator acceptance packet; no live readiness; no shutdown recommendation without explicit operator acceptance...\n"
            "END_FILE\n\n"
            "The GO_NO_GO.md body must contain exactly one line from the allowed set. Use native READY only if real native evidence clears "
            "the required fields; use ACCEPTANCE_REQUIRED when derived/incomplete evidence remains but an operator paper-only acceptance "
            "packet is complete; use BLOCKED if evidence cannot be classified safely.\n"
            f"BEGIN_FILE: {out}/GO_NO_GO.md\n"
            "V2_TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED\n"
            "END_FILE\n\n"
            "Also emit a public dashboard payload:\n"
            "BEGIN_FILE: v2/frontend/public/trainer_derived_evidence_acceptance/latest/operator_dashboard_payload.json\n"
            "{\"current_gate_state\":\"blocked_human_only\",\"live_symbols\":[],\"shutdown_recommendation\":\"BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE\"}\n"
            "END_FILE\n"
        )
    if task_id == PAPER_EDGE_POST_FILTER_TASK_ID:
        return (
            common
            + "Task: Build paper_edge_post_filter_observation_window. Separate old negative paper fills from behavior after "
            "paper_canary_aligned_filter_v1 started gating paper fills. Prove whether the post-filter window prevents fee bleed and churn. "
            "Do not treat the old -49.12 paper PnL as current post-filter PnL if no new fills are allowed. Do not mark paper edge proven "
            "unless post-filter evidence actually supports it. This task never approves live and never approves legacy shutdown.\n\n"
            "Read current paper runtime, paper shadow observation, paper execution worker status, execution ledger, signal lineage, trainer "
            "payload, and paper_strategy_edge_tightening artifacts. Identify the filter activation evidence, post-filter observation start, "
            "post-filter fills, post-filter denials, blocked intents, fees, churn, and realized/unrealized PnL deltas. Classify the result as "
            "exactly one of: POST_FILTER_EDGE_PENDING, POST_FILTER_NO_UNSAFE_FILLS, POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING, "
            "POST_FILTER_NO_TRADE_CONDITION_CONFIRMED, POST_FILTER_POSITIVE_EDGE_PROVEN, POST_FILTER_EDGE_STILL_UNPROVEN. "
            "Use POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING when unsafe fills are absent but zero fills prevent positive-edge proof.\n\n"
            "Output these required files exactly:\n"
            f"BEGIN_FILE: {out}/PAPER_EDGE_POST_FILTER_OBSERVATION_REPORT.md\n"
            "...report with post-filter window definition, fill/denial counts, PnL split, and blocker impact...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/paper_edge_post_filter_observation_status.json\n"
            "{\"task_id\":\"paper_edge_post_filter_observation_window\",\"live_gate\":\"blocked_human_only\","
            "\"classification\":\"POST_FILTER_EDGE_PENDING\",\"live_symbols\":[]}\n"
            "END_FILE\n\n"
            "The GO_NO_GO.md body must contain exactly one classification token:\n"
            f"BEGIN_FILE: {out}/GO_NO_GO.md\n"
            "POST_FILTER_EDGE_PENDING\n"
            "END_FILE\n\n"
            "Also emit a public dashboard payload:\n"
            "BEGIN_FILE: v2/frontend/public/paper_edge_post_filter_observation_window/latest/operator_dashboard_payload.json\n"
            "{\"live_gate\":\"blocked_human_only\",\"live_symbols\":[],\"classification\":\"POST_FILTER_EDGE_PENDING\"}\n"
            "END_FILE\n"
        )
    if task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        return (
            common
            + "Task: Implement V2_PAPER_EDGE_RECOVERY_AND_COST_AWARE_TRADE_SELECTION_READY.\n\n"
            "Purpose: The paper loss attribution proved that V2 pre-filter paper loss came from high-churn fills with no proven edge "
            "after fees/slippage. Gross PnL was approximately flat before fees, explicit fees and slippage drove the loss, and the "
            "highest confidence bucket still lost money. Post-filter unsafe fills are now stopped, but positive edge is unproven. "
            "Change V2 paper trade selection so no paper fill can happen unless expected move after costs, trainer source, feature "
            "freshness, cooldown, churn, Symbol Universe, and risk gates all pass. This is V2 paper/shadow only; do not approve live, "
            "canary, or legacy shutdown.\n\n"
            "Known evidence to preserve honestly: cumulative paper PnL about -49.12; source-limited prior baseline about -26.37; "
            "observed pre-filter loss about -22.75; post-filter PnL delta 0.0; post-filter fills 0; post-filter unsafe fills 0; "
            "explicit booked fees pre-filter 22.69; estimated slippage pre-filter 11.345; gross PnL if fees added back about -0.06; "
            "0.75_plus confidence bucket lost about -12.79; per-fill trainer source missing; per-fill feature freshness missing; "
            "edge-after-costs missing for pre-filter allowed fills. Read the paper loss attribution packet before changing behavior.\n\n"
            "Phase A - Extend paper event schema. Patch V2 paper execution and paper shadow event schema so every intent, blocked intent, "
            "and fill records: event_id, symbol, side, timeframe, intent_id, prediction_id, feature_snapshot_id, trainer_source, "
            "trainer_bridge_status, model_version, checkpoint_id, confidence_raw, confidence_calibrated, confidence_bucket, "
            "expected_move_bps, expected_move_after_cost_bps, fee_bps, spread_bps, slippage_bps, funding_risk_bps, edge_score, "
            "feature_freshness_state, stale_feature_flags, missing_feature_flags, symbol_universe_state, paper_symbol_allowed, "
            "risk_decision_id, risk_reason, block_reason, fill_allowed, fill_rejected_reason, live_gate, and live_symbols. Missing "
            "trainer source, missing feature freshness, missing expected_move_after_cost_bps, confidence-only permission, non-empty "
            "live_symbols, or live_gate != blocked_human_only must block fills.\n\n"
            "Create v2/backend/app/composition/paper_edge_scoring/ and v2/backend/tests/unit/composition/test_paper_edge_scoring.py. "
            "Implement cost-aware scoring: expected_move_after_cost_bps = predicted_move_bps - fee_bps - spread_bps - slippage_bps - "
            "funding_risk_bps. Hard gate defaults: expected_move_after_cost_bps >= 8 bps, confidence_calibrated >= 0.70, "
            "feature_freshness_state == CURRENT, trainer_source in accepted set, symbol in paper_symbols, live_symbols == [], cooldown "
            "clear, flip/churn clear, and risk gate allows paper. If any fail, do not fill, write blocked intent, and write shadow "
            "observation request. Output classifications include EDGE_AFTER_COSTS_PASS, EDGE_AFTER_COSTS_MISSING_BLOCK, "
            "EDGE_AFTER_COSTS_NEGATIVE_BLOCK, TRAINER_SOURCE_MISSING_BLOCK, FEATURE_FRESHNESS_MISSING_BLOCK, FEATURE_STALE_BLOCK, "
            "CONFIDENCE_TOO_LOW_BLOCK, COOLDOWN_BLOCK, FLIP_CHURN_BLOCK, SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK, and RISK_GATE_BLOCK.\n\n"
            "Phase C - Shadow outcome observations for blocked intents. Create v2/backend/app/cli/paper_shadow_outcome_observer.py, "
            "v2/backend/tests/integration/cli/test_paper_shadow_outcome_observer.py, and "
            "v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json. "
            "Blocked intents should record symbol, side, entry_reference_price, event_ts, horizon_5m, horizon_15m, horizon_30m, "
            "expected_move_bps when available, expected_move_after_cost_bps when available, and block_reason. Later observations should "
            "compute max favorable excursion, max adverse excursion, realized horizon return, would_have_beaten_costs, "
            "would_have_hit_stop, and would_have_hit_take_profit. This must not charge paper fees or create fills.\n\n"
            "Phase D - Pre-filter loss replay and threshold tuning. Create v2/backend/app/cli/paper_edge_threshold_replay.py. Replay "
            "pre-filter paper JSONL and test min_expected_move_after_cost_bps values 4, 6, 8, 10, 12, 15; min_confidence values 0.58, "
            "0.65, 0.70, 0.75; cooldown seconds; flip/churn windows; and max fills per symbol per hour. Output simulated fill count, "
            "simulated fee, simulated PnL, blocked count, win rate, profit factor, edge coverage, and no-trade classification. If all "
            "thresholds block all fills, classify NO_TRADE_EDGE_NOT_FOUND, not failure. Do not optimize to fake live readiness.\n\n"
            "Phase E - Restore legacy protective behavior in paper-only form. Map preserved legacy behavior from trading/churn_prevention.py, "
            "trading/lifecycle_controller.py, trading/exit_coordinator.py, trading/dynamic_tp_engine.py, trading/dynamic_adaptive_stops.py, "
            "trading/stealth_stops.py, trading/fee_ratio_gate.py, trading/adaptive_edge_gate.py, risk/reduce_only_latch.py, "
            "risk/intelligent_close_guard.py, risk/microstructure_toxicity.py, risk/adaptive_gate.py, rl/churn_veto.py, "
            "rl/minimum_hold_time.py, and rl/fee_ratio_reward_shaping.py. Add V2 paper-only equivalents or explicit blockers for "
            "minimum hold time, same-side cooldown, flip cooldown, fee-ratio gate, adaptive edge gate, dynamic TP simulation, dynamic "
            "stop simulation, stealth stop simulation, reduce-only protection, and churn veto. Codex must fail if any behavior is "
            "silently dropped.\n\n"
            "Phase F - Paper payload and dashboard output. Update v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json "
            "and claude_worklog/final_readiness/paper_edge_recovery/latest/operator_dashboard_payload.json with cumulative PnL, pre-filter "
            "PnL, post-filter PnL, post-filter fills, post-filter unsafe fills, edge status, no-trade status, threshold replay best safe "
            "profile, blocked intent counts, shadow observations pending, trainer source coverage, feature freshness coverage, "
            "edge-after-costs coverage, remaining blockers, live_gate, and live_symbols.\n\n"
            "Validation required: py_compile, unit/integration tests, JSON validation, frontend build/typecheck/sync when affected, secret "
            "scan, forbidden-action scan, final approval token absent, Redis trim approval absent, old Redis write absence, exchange action "
            "absence. Do not mark positive edge proven unless post-filter fills exist and produce positive net after fees/slippage.\n\n"
            "Output required files exactly:\n"
            f"BEGIN_FILE: {out}/GO_NO_GO.md\n"
            "V2_PAPER_EDGE_RECOVERY_BLOCKED\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/V2_PAPER_EDGE_RECOVERY_AND_COST_AWARE_TRADE_SELECTION_REPORT.md\n"
            "...implementation report, evidence, tests, safety status, and honest remaining blockers...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/paper_edge_recovery_status.json\n"
            "{\"task_id\":\"claude_v2_paper_edge_recovery_and_cost_aware_trade_selection\","
            "\"live_gate\":\"blocked_human_only\",\"live_symbols\":[],\"approves_live\":false,\"approves_legacy_shutdown\":false}\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/PAPER_EDGE_THRESHOLD_REPLAY_REPORT.md\n"
            "...threshold replay report...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/paper_edge_threshold_replay.json\n"
            "{\"task_id\":\"paper_edge_threshold_replay\",\"classification\":\"NO_TRADE_EDGE_NOT_FOUND_OR_PROFILE_READY\"}\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP.md\n"
            "...SHA-cited legacy protective behavior mapping and V2 paper equivalent/blocker for each behavior...\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/legacy_protective_behavior_to_v2_paper_map.json\n"
            "{\"task_id\":\"legacy_protective_behavior_to_v2_paper_map\",\"behaviors\":[]}\n"
            "END_FILE\n\n"
            f"BEGIN_FILE: {out}/operator_dashboard_payload.json\n"
            "{\"live_gate\":\"blocked_human_only\",\"live_symbols\":[],\"edge_status\":\"EDGE_PENDING\"}\n"
            "END_FILE\n\n"
            "BEGIN_FILE: v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json\n"
            "{\"live_gate\":\"blocked_human_only\",\"live_symbols\":[],\"edge_status\":\"EDGE_PENDING\"}\n"
            "END_FILE\n\n"
            "GO_NO_GO.md must contain exactly one of: V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING, "
            "V2_PAPER_EDGE_RECOVERY_READY_POSITIVE_EDGE_PROVEN, V2_PAPER_EDGE_RECOVERY_BLOCKED_EDGE_NOT_FOUND, or "
            "V2_PAPER_EDGE_RECOVERY_BLOCKED. Use READY_POSITIVE_EDGE_PROVEN only with positive post-filter net fill evidence.\n"
        )
    if task_id == "claude_resolve_remaining_unresolved_local_imports":
        body = (
            "Task: resolve or explicitly classify the remaining full-closure local import gaps: "
            "ingest, binance_websocket, and hybrid_rule_based_signals. Inspect preserved closure artifacts and legacy evidence read-only. "
            "If helper source is found, emit the V2-preserved copy or copier update with SHA evidence. If not found, emit a reasoned "
            "LEGACY_ONLY_DEP_REPLACED_BY_V2_WITH_REASON classification. Re-run or specify the exact closure validation needed.\n"
        )
    elif task_id == "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map":
        body = (
            "Task: implement the missing V2 risk-gateway legacy gate callables needed before parity tests can exist. "
            "Use the preserved full-runtime closure and cite SHA256 for risk/kill_switch.py, risk/halt_manager.py, "
            "risk/reduce_only_latch.py, risk/intelligent_close_guard.py, risk/auto_deleverager.py, "
            "risk/shared_risk_gate.py, risk/margin_governor.py, risk/phase_controller.py, "
            "risk/microstructure_toxicity.py, and risk/adaptive_gate.py. Add fail-closed V2 modules/functions for "
            "evaluate_kill_switch_state, evaluate_halt_state, evaluate_latch_state, evaluate_close_guard, "
            "evaluate_adl_state, evaluate_budget_state, evaluate_margin_state, evaluate_phase_gate, and "
            "evaluate_toxicity_block. Add the corresponding V2 risk reason codes. Do not wire exchange mutation, "
            "old Redis writes, leverage changes, margin-mode changes, or live enablement. Add non-skipped unit tests "
            "that invoke real V2 callables for all nine gates and prove deny/close-only behavior. If exact legacy "
            "behavior is too broad for this cycle, implement the minimal fail-closed paper/shadow parity surface with "
            "an explicit behavior mapping and remaining-gap list.\n"
        )
    elif task_id == "claude_port_v2_trainer_bridge_full_legacy_parity":
        body = (
            "Task: remediate V2 trainer bridge parity. Use the full runtime closure under v2/legacy_preserved/full_runtime_closure "
            "and cite SHA256 for every rl helper consumed. Replace the momentum-wrapper-only status with either a preserved-tree "
            "legacy hybrid trainer bridge or a V2-native implementation that enumerates every changed legacy behavior. If trainer "
            "external modules are unavailable, classify V2_ENV_BLOCKED_MISSING_DEPENDENCY and record the exact package list; install "
            "only safe non-secret V2 .venv packages when required and record the action.\n"
        )
    elif task_id == "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map":
        body = (
            "Task: expand V2 risk gateway parity tests from the legacy action-path map. Add tests for kill switch, halt manager, "
            "reduce-only latch, intelligent close guard, auto deleverager, shared risk budget, margin governor, phase controller, "
            "and adaptive microstructure toxicity. Tests must invoke real V2 gate functions and must not skip.\n"
        )
    elif task_id == "claude_backfill_v2_feature_snapshot_builder_full_closure_baseline_analysis":
        body = (
            "Task: backfill v2_feature_snapshot_builder full-closure LEGACY_BASELINE_ANALYSIS and legacy_behavior_mapping. Cite "
            "full_runtime_copied_source_manifest.json for rl/unified_feature_builder.py and rl/obs_schema.py behavior. Do not change "
            "green worker code unless the backfill exposes an actual parity bug.\n"
        )
    elif task_id == "claude_port_v2_signal_publisher_from_legacy_schema":
        body = (
            "Task: port V2 signal publisher from the legacy schema. Inspect utils/signal_schema.py, utils/signal_publish.py, "
            "trading/signal_router.py, and trading/coinank_signal_adapter.py from the preserved full closure. Adopt the legacy "
            "field schema or explicitly document each changed field with reason. V2 may write only v2:* namespaces; old legacy "
            "streams are read-only references.\n"
        )
    elif task_id == "claude_remediate_v2_orchestrator_adapter_legacy_parity":
        body = (
            "Task: remediate v2_orchestrator_adapter parity against rl/orchestrator_worker.py, rl/tradeplan_orchestrator.py, "
            "rl/proposal_hedge_preflight.py, and rl/decision_trace.py. Preserve proposal/signal/risk-gateway handoff fields or "
            "document explicit behavior changes with SHA-cited evidence.\n"
        )
    elif task_id.startswith("claude_remediate_v2_market_ingestor") or task_id.startswith("claude_remediate_v2_coinank") or task_id.startswith("claude_remediate_v2_feature_pipeline"):
        body = (
            "Task: backfill full-runtime SHA proof for the baseline-anchored V2 ingestor/feature worker. Inspect the existing "
            "LEGACY_BASELINE_ANALYSIS.md and legacy_behavior_mapping.json, cite full_runtime_copied_source_manifest.json for every "
            "full-closure helper consumed, and update worker/public status without changing live or old Redis behavior.\n"
        )
    elif task_id == "claude_remediate_account_position_monitor_shutdown_parity":
        body = (
            "Task: refresh read-only trade-permission, account, margin-mode, and leverage-cap evidence for shutdown readiness. "
            "Classify MISSING_CREDENTIALS, READ_ONLY_CONFIRMED, or TRADE_PERMISSION_UNKNOWN with source paths. Use only read-only "
            "queries or existing artifacts; if evidence cannot be obtained, keep shutdown blocked.\n"
        )
    elif task_id == "claude_replay_paper_edge_repair_from_legacy_trainer_output":
        body = (
            "Task: diagnose and remediate paper/shadow negative PnL, flat recent fills, and rising blocked intents without enabling "
            "live. Produce a paper-only profile or risk-gate adjustment proposal backed by replay or current paper evidence. Any "
            "runtime changes must remain paper/shadow only and live blocked.\n"
        )
    else:
        body = (
            "Task: audit stale public/runtime payloads that affect shutdown readiness and emit MISSING_EVIDENCE labels or freshness "
            "repairs for V2 dashboard payloads only.\n"
        )
    return (
        common
        + body
        + "\nRequired evidence in outputs: LEGACY_BASELINE_ANALYSIS.md content, legacy_behavior_mapping.json content, SHA256 citations "
        + "from full_runtime_copied_source_manifest.json and copied_baseline_manifest.json where relevant, dependency closure status, "
        + "tests or an explicit V2_ENV_BLOCKED/MISSING_EVIDENCE classification, public payload impact if runtime-facing, and a clear GO/NO-GO.\n"
        + "\nEmit at least these two BEGIN_FILE blocks:\n"
        + f"BEGIN_FILE: {out}/{task_id}_REPORT.md\n...report...\nEND_FILE\n\n"
        + f"BEGIN_FILE: {out}/{task_id}_STATUS.json\n{{\"task_id\":\"{task_id}\",\"status\":\"BLOCKED_OR_REMEDIATED\",\"live_gate\":\"blocked_human_only\",\"final_approval_token\":\"absent\"}}\nEND_FILE\n"
        + f"\nBEGIN_FILE: {out}/{task_id}_GO_NO_GO.md\n{task_id.upper()}_BLOCKED_OR_READY\nEND_FILE\n"
        + f"\nBEGIN_FILE: {out}/{task_id}_LEGACY_BASELINE_ANALYSIS.md\n...SHA-cited analysis...\nEND_FILE\n"
        + f"\nBEGIN_FILE: {out}/{task_id}_legacy_behavior_mapping.json\n{{\"task_id\":\"{task_id}\",\"mapping_status\":\"BLOCKED_OR_REMEDIATED\"}}\nEND_FILE\n"
    )


def claude_task_descriptor(task_id: str) -> Dict[str, Any]:
    out = rel(task_output_dir(task_id))
    allowed = [
        out + "/",
        rel(WORKER_DIR) + "/",
        "v2/backend/app/",
        "v2/backend/tests/",
        "v2/frontend/public/operator_runtime/",
        rel(CLOSURE_DIR) + "/",
        "claude_worklog/tools/",
    ]
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        allowed = [
            out + "/",
            "v2/backend/app/",
            "v2/backend/tests/",
            "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/",
            "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/",
        ]
        return {
            "task_id": task_id,
            "agent": "claude",
            "risk_level": "L2",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_paths": ["v2/**", "claude_worklog/**", "requirements/**"],
            "forbidden": [
                "legacy_mutation",
                "old_redis_write",
                "exchange_action",
                "leverage_change",
                "margin_mode_change",
                "live_gate_unlock",
                "approval_token_creation",
                "redis_trim_approval_creation",
                "fabricated_feature_attribution",
                "derived_evidence_mislabeled_native",
                "full_trainer_parity_while_blockers_remain",
            ],
            "allowed_output_prefixes": allowed,
            "required_output_files": [
                f"{out}/V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_REPORT.md",
                f"{out}/trainer_lineage_attribution_status.json",
                f"{out}/GO_NO_GO.md",
            ],
            "task_timeout_seconds": 1800,
            "max_attempts": 1,
            "prompt": claude_prompt(task_id),
        }
    if task_id == TRAINER_DERIVED_ACCEPTANCE_TASK_ID:
        allowed = [
            out + "/",
            "v2/backend/app/",
            "v2/backend/tests/",
            "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/",
            "v2/frontend/public/trainer_derived_evidence_acceptance/latest/",
            rel(CLOSURE_DIR) + "/",
            "claude_worklog/final_readiness/trainer_lineage_attribution_parity/latest/",
        ]
        return {
            "task_id": task_id,
            "agent": "claude",
            "risk_level": "L2",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_paths": ["v2/**", "claude_worklog/**", "requirements/**"],
            "forbidden": [
                "legacy_mutation",
                "old_redis_write",
                "exchange_action",
                "leverage_change",
                "margin_mode_change",
                "live_gate_unlock",
                "approval_token_creation",
                "redis_trim_approval_creation",
                "fabricated_feature_attribution",
                "derived_evidence_mislabeled_native",
                "live_readiness_implied",
                "shutdown_recommended_without_operator_acceptance",
            ],
            "allowed_output_prefixes": allowed,
            "required_output_files": [
                f"{out}/GO_NO_GO.md",
                f"{out}/TRAINER_DERIVED_EVIDENCE_ACCEPTANCE_REPORT.md",
                f"{out}/trainer_field_evidence_matrix.json",
                f"{out}/TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md",
                "v2/frontend/public/trainer_derived_evidence_acceptance/latest/operator_dashboard_payload.json",
            ],
            "task_timeout_seconds": 1800,
            "max_attempts": 1,
            "prompt": claude_prompt(task_id),
        }
    if task_id == PAPER_EDGE_POST_FILTER_TASK_ID:
        allowed = [
            out + "/",
            "v2/frontend/public/paper_edge_post_filter_observation_window/latest/",
            "v2/frontend/public/operator_runtime/",
            "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/",
            "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/",
            "v2/backend/tests/",
        ]
        return {
            "task_id": task_id,
            "agent": "claude",
            "risk_level": "L2",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_paths": ["v2/**", "claude_worklog/**", "requirements/**"],
            "forbidden": [
                "legacy_mutation",
                "old_redis_write",
                "exchange_action",
                "leverage_change",
                "margin_mode_change",
                "live_gate_unlock",
                "approval_token_creation",
                "redis_trim_approval_creation",
                "old_negative_pnl_mislabeled_post_filter",
                "paper_edge_proven_without_post_filter_evidence",
            ],
            "allowed_output_prefixes": allowed,
            "required_output_files": [
                f"{out}/GO_NO_GO.md",
                f"{out}/PAPER_EDGE_POST_FILTER_OBSERVATION_REPORT.md",
                f"{out}/paper_edge_post_filter_observation_status.json",
                "v2/frontend/public/paper_edge_post_filter_observation_window/latest/operator_dashboard_payload.json",
            ],
            "task_timeout_seconds": 1800,
            "max_attempts": 2,
            "prompt": claude_prompt(task_id),
        }
    if task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        allowed = [
            out + "/",
            "v2/backend/app/composition/paper_edge_scoring/",
            "v2/backend/app/cli/",
            "v2/backend/tests/",
            "v2/frontend/public/paper_edge_recovery/latest/",
            "v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/",
            "v2/frontend/public/operator_runtime/paper_online/latest/",
            "claude_worklog/final_readiness/paper_loss_attribution/latest/",
            "claude_worklog/final_readiness/paper_edge_post_filter_observation_window/latest/",
            "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/",
            rel(CLOSURE_DIR) + "/",
        ]
        return {
            "task_id": task_id,
            "agent": "claude",
            "risk_level": "L2",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_paths": ["v2/**", "claude_worklog/**", "requirements/**"],
            "forbidden": [
                "legacy_mutation",
                "old_redis_write",
                "exchange_action",
                "leverage_change",
                "margin_mode_change",
                "live_gate_unlock",
                "approval_token_creation",
                "redis_trim_approval_creation",
                "confidence_only_fill_permission",
                "expected_move_after_costs_missing_fill_permission",
                "trainer_source_missing_fill_permission",
                "feature_freshness_missing_fill_permission",
                "symbol_not_paper_eligible_fill_permission",
                "paper_edge_proven_with_zero_fills",
                "pre_filter_loss_hidden",
                "loss_report_caveats_hidden",
                "legacy_protective_behavior_silently_dropped",
            ],
            "allowed_output_prefixes": allowed,
            "required_output_files": [
                f"{out}/GO_NO_GO.md",
                f"{out}/V2_PAPER_EDGE_RECOVERY_AND_COST_AWARE_TRADE_SELECTION_REPORT.md",
                f"{out}/paper_edge_recovery_status.json",
                f"{out}/PAPER_EDGE_THRESHOLD_REPLAY_REPORT.md",
                f"{out}/paper_edge_threshold_replay.json",
                f"{out}/LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP.md",
                f"{out}/legacy_protective_behavior_to_v2_paper_map.json",
                f"{out}/operator_dashboard_payload.json",
                "v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json",
            ],
            "task_timeout_seconds": 2400,
            "max_attempts": 1,
            "prompt": claude_prompt(task_id),
        }
    return {
        "task_id": task_id,
        "agent": "claude",
        "risk_level": "L2",
        "live_gate": LIVE_GATE,
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "lane": "shutdown_readiness_remediation",
        "managed_by": "codex_legacy_shutdown_readiness_takeover",
        "allowed_paths": ["v2/**", "claude_worklog/**", "requirements/**"],
        "forbidden": [
            "legacy_mutation",
            "old_redis_write",
            "exchange_action",
            "leverage_change",
            "margin_mode_change",
            "live_gate_unlock",
            "approval_token_creation",
            "redis_trim_approval_creation",
            "greenfield_without_legacy_baseline",
            "dropping_legacy_behavior_silently",
            "missing_sha256_citation_from_full_runtime_manifest",
        ],
        "allowed_output_prefixes": allowed,
        "required_output_files": [
            f"{out}/{task_id}_REPORT.md",
            f"{out}/{task_id}_STATUS.json",
            f"{out}/{task_id}_GO_NO_GO.md",
            f"{out}/{task_id}_LEGACY_BASELINE_ANALYSIS.md",
            f"{out}/{task_id}_legacy_behavior_mapping.json",
        ],
        "task_timeout_seconds": 1800,
        "max_attempts": 2,
        "prompt": claude_prompt(task_id),
    }


def codex_review_descriptor(task_id: str) -> Dict[str, Any]:
    review_id = review_task_id_for(task_id)
    out = rel(codex_output_dir(task_id))
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        pass_token = "CODEX_REVIEW_V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_PASS"
        fail_token = "CODEX_REVIEW_V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_FAIL"
        prompt = (
            "You are Codex running the trainer lineage attribution parity review. "
            "Review the Claude remediation outputs, V2 trainer bridge code/tests, current trainer bridge payload, "
            "and read-only preserved legacy trainer evidence. Do not modify source files. Do not mutate legacy, old Redis, "
            "exchange state, leverage, margin mode, or live trading. Keep live_gate=blocked_human_only.\n\n"
            "Fail if derived log evidence is mislabeled as native, feature attribution is fabricated, missing/stale/unused "
            "feature flags are hidden, trainer parity is marked full while any lineage blocker remains, legacy Redis mutation evidence appears, "
            "exchange mutation appears, or live_gate changes. Verify GO_NO_GO.md has exactly one allowed token and that "
            "READY is used only when native evidence genuinely clears the three known blockers.\n\n"
            "Emit exactly two BEGIN_FILE blocks:\n"
            f"BEGIN_FILE: {out}/CODEX_REVIEW.md\n...findings with PASS/FAIL rationale...\nEND_FILE\n\n"
            f"BEGIN_FILE: {out}/CODEX_GO_NO_GO.md\n{fail_token}\nEND_FILE\n"
            f"Use {pass_token} instead only if every review condition passes.\n"
        )
        return {
            "task_id": review_id,
            "agent": "codex",
            "risk_level": "L1",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_output_prefixes": [out + "/"],
            "required_output_files": [f"{out}/CODEX_REVIEW.md", f"{out}/CODEX_GO_NO_GO.md"],
            "depends_on": [task_id],
            "task_timeout_seconds": 1200,
            "max_attempts": 1,
            "prompt": prompt,
        }
    if task_id == TRAINER_DERIVED_ACCEPTANCE_TASK_ID:
        pass_token = upper_token(task_id, "CODEX_PASS")
        fail_token = upper_token(task_id, "CODEX_FAIL")
        prompt = (
            "You are Codex running the trainer derived-evidence/native-parity packet review. "
            "Review the Claude outputs, V2 trainer bridge payload/code/tests, public dashboard payload, current shutdown controller status, "
            "and read-only preserved legacy trainer evidence. Do not modify source files. Do not mutate legacy, old Redis, exchange state, "
            "leverage, margin mode, or live trading. Keep live_gate=blocked_human_only.\n\n"
            "Fail if derived evidence is mislabeled as native, feature attribution is fabricated, live/canary readiness is implied, "
            "shutdown is recommended without explicit operator acceptance, old Redis write evidence appears, exchange mutation evidence appears, "
            "approval tokens appear, live_symbols is non-empty, or GO_NO_GO.md does not contain exactly one allowed token.\n\n"
            "Emit exactly two BEGIN_FILE blocks:\n"
            f"BEGIN_FILE: {out}/CODEX_REVIEW.md\n...findings with PASS/FAIL rationale...\nEND_FILE\n\n"
            f"BEGIN_FILE: {out}/CODEX_GO_NO_GO.md\n{fail_token}\nEND_FILE\n"
            f"Use {pass_token} instead only if every review condition passes.\n"
        )
        return {
            "task_id": review_id,
            "agent": "codex",
            "risk_level": "L1",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_output_prefixes": [out + "/"],
            "required_output_files": [f"{out}/CODEX_REVIEW.md", f"{out}/CODEX_GO_NO_GO.md"],
            "depends_on": [task_id],
            "task_timeout_seconds": 1200,
            "max_attempts": 1,
            "prompt": prompt,
        }
    if task_id == PAPER_EDGE_POST_FILTER_TASK_ID:
        pass_token = upper_token(task_id, "CODEX_PASS")
        fail_token = upper_token(task_id, "CODEX_FAIL")
        prompt = (
            "You are Codex running the paper-edge post-filter observation review. "
            "Review the Claude outputs, current paper runtime/shadow payloads, paper execution worker status, and current shutdown controller state. "
            "Do not modify source files. Do not mutate legacy, old Redis, exchange state, leverage, margin mode, or live trading. "
            "Keep live_gate=blocked_human_only.\n\n"
            "Fail if old negative PnL is mislabeled as post-filter PnL, paper edge is marked proven without post-filter evidence, live readiness is implied, "
            "shutdown is recommended, old Redis write evidence appears, exchange mutation evidence appears, approval tokens appear, live_symbols is non-empty, "
            "or GO_NO_GO.md does not contain exactly one allowed post-filter classification.\n\n"
            "Emit exactly two BEGIN_FILE blocks:\n"
            f"BEGIN_FILE: {out}/CODEX_REVIEW.md\n...findings with PASS/FAIL rationale...\nEND_FILE\n\n"
            f"BEGIN_FILE: {out}/CODEX_GO_NO_GO.md\n{fail_token}\nEND_FILE\n"
            f"Use {pass_token} instead only if every review condition passes.\n"
        )
        return {
            "task_id": review_id,
            "agent": "codex",
            "risk_level": "L1",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_output_prefixes": [out + "/"],
            "required_output_files": [f"{out}/CODEX_REVIEW.md", f"{out}/CODEX_GO_NO_GO.md"],
            "depends_on": [task_id],
            "task_timeout_seconds": 1200,
            "max_attempts": 1,
            "prompt": prompt,
        }
    if task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        pass_token = upper_token(task_id, "CODEX_PASS")
        fail_token = upper_token(task_id, "CODEX_FAIL")
        prompt = (
            "You are Codex running the paper-edge recovery and cost-aware trade-selection review. "
            "Review Claude outputs, V2 source/tests, paper loss attribution, paper post-filter observation, paper runtime/shadow payloads, "
            "and current shutdown controller state. Do not modify source files. Do not mutate legacy, old Redis, exchange state, leverage, "
            "margin mode, or live trading. Keep live_gate=blocked_human_only and live_symbols=[].\n\n"
            "Fail if confidence alone can allow a fill; expected_move_after_cost_bps missing can allow a fill; trainer source missing can "
            "allow a fill; feature freshness missing can allow a fill; symbol not in paper_symbols can allow a fill; old Redis write appears; "
            "exchange mutation appears; live gate changes; live_symbols is not []; paper edge is marked proven with zero fills; old pre-filter "
            "PnL is hidden; loss report caveats are hidden; legacy protective behaviors are silently dropped; GO_NO_GO.md contains a token "
            "outside the allowed set; or positive edge is claimed without positive post-filter net-after-cost fill evidence.\n\n"
            "Allowed GO_NO_GO tokens: V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING, "
            "V2_PAPER_EDGE_RECOVERY_READY_POSITIVE_EDGE_PROVEN, V2_PAPER_EDGE_RECOVERY_BLOCKED_EDGE_NOT_FOUND, "
            "V2_PAPER_EDGE_RECOVERY_BLOCKED. Passing review does not approve live, canary, or legacy shutdown.\n\n"
            "Emit exactly two BEGIN_FILE blocks:\n"
            f"BEGIN_FILE: {out}/CODEX_REVIEW.md\n...findings with PASS/FAIL rationale...\nEND_FILE\n\n"
            f"BEGIN_FILE: {out}/CODEX_GO_NO_GO.md\n{fail_token}\nEND_FILE\n"
            f"Use {pass_token} instead only if every review condition passes.\n"
        )
        return {
            "task_id": review_id,
            "agent": "codex",
            "risk_level": "L1",
            "live_gate": LIVE_GATE,
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "shutdown_readiness_remediation",
            "managed_by": "codex_legacy_shutdown_readiness_takeover",
            "allowed_output_prefixes": [out + "/"],
            "required_output_files": [f"{out}/CODEX_REVIEW.md", f"{out}/CODEX_GO_NO_GO.md"],
            "depends_on": [task_id],
            "task_timeout_seconds": 1200,
            "max_attempts": 1,
            "prompt": prompt,
        }
    pass_token = upper_token(task_id, "CODEX_PASS")
    fail_token = upper_token(task_id, "CODEX_FAIL")
    prompt = (
        "You are Codex running a read-only shutdown-readiness review. "
        "Do not modify source files. Do not mutate legacy, Redis, exchange state, leverage, margin mode, or live trading. "
        f"Review Claude task {task_id}, its emitted files under {rel(task_output_dir(task_id))}, relevant V2 source/tests, and current readiness payloads. "
        "Fail if legacy behavior was silently dropped, old Redis writes or exchange mutations are introduced, live gate is not blocked_human_only, "
        "approval tokens appear, required SHA evidence is missing, or tests are missing for touched behavior.\n\n"
        "Emit exactly two BEGIN_FILE blocks:\n"
        f"BEGIN_FILE: {out}/CODEX_REVIEW.md\n...findings...\nEND_FILE\n\n"
        f"BEGIN_FILE: {out}/CODEX_GO_NO_GO.md\n{pass_token} or {fail_token}\nEND_FILE\n"
    )
    return {
        "task_id": review_id,
        "agent": "codex",
        "risk_level": "L1",
        "live_gate": LIVE_GATE,
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "lane": "shutdown_readiness_remediation",
        "managed_by": "codex_legacy_shutdown_readiness_takeover",
        "allowed_output_prefixes": [out + "/"],
        "required_output_files": [f"{out}/CODEX_REVIEW.md", f"{out}/CODEX_GO_NO_GO.md"],
        "task_timeout_seconds": 1200,
        "max_attempts": 2,
        "prompt": prompt,
    }


def write_task_descriptors(task_ids: Iterable[str]) -> List[str]:
    written: List[str] = []
    for task_id in sorted(set(task_ids)):
        if not task_id:
            continue
        claude_path = TASKS_DIR / f"{task_id}.json"
        codex_path = TASKS_DIR / f"{review_task_id_for(task_id)}.json"
        if not claude_path.exists():
            write_json(claude_path, claude_task_descriptor(task_id))
            written.append(rel(claude_path))
        if not codex_path.exists():
            write_json(codex_path, codex_review_descriptor(task_id))
            written.append(rel(codex_path))
    return written


def required_outputs_exist(descriptor: Dict[str, Any]) -> bool:
    for raw in descriptor.get("required_output_files", []):
        path = ROOT / str(raw)
        if not path.exists():
            return False
    return True


def codex_passed(task_id: str) -> bool:
    path = codex_output_dir(task_id) / "CODEX_GO_NO_GO.md"
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return path.exists() and "CODEX_REVIEW_V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_PASS" in read_text(path)
    return path.exists() and upper_token(task_id, "CODEX_PASS") in read_text(path)


def codex_failed(task_id: str) -> bool:
    path = codex_output_dir(task_id) / "CODEX_GO_NO_GO.md"
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return path.exists() and "CODEX_REVIEW_V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_FAIL" in read_text(path)
    return path.exists() and upper_token(task_id, "CODEX_FAIL") in read_text(path)


def failed_review_followup_task(task_id: str) -> Optional[str]:
    if task_id == "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map":
        return "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map"
    if task_id in {
        PAPER_EDGE_RECOVERY_TASK_ID,
        TRAINER_DERIVED_ACCEPTANCE_TASK_ID,
        TRAINER_LINEAGE_ATTRIBUTION_TASK_ID,
    }:
        return task_id
    return None


def select_next_action(blockers: List[Dict[str, Any]], dry_run: bool) -> Dict[str, Any]:
    task_ids = [str(item.get("remediation_task_id")) for item in blockers if item.get("remediation_task_id")]
    if not dry_run:
        write_task_descriptors(list(TEMPLATE_TASKS) + task_ids)

    completed_task_ids = list(dict.fromkeys(list(REMEDIATION_PRIORITY) + list(TEMPLATE_TASKS) + task_ids))
    for completed_task_id in completed_task_ids:
        claude_descriptor = claude_task_descriptor(completed_task_id)
        if not required_outputs_exist(claude_descriptor):
            continue
        if task_effective_status(completed_task_id) not in {"completed", "superseded_by_evidence"}:
            continue
        if codex_passed(completed_task_id) or codex_failed(completed_task_id):
            continue
        review_id = review_task_id_for(completed_task_id)
        review_descriptor = codex_review_descriptor(completed_task_id)
        review_status = task_effective_status(review_id)
        review_has_required_files = required_outputs_exist(review_descriptor)
        if review_status == "running" and task_running_stale(review_id):
            if not dry_run:
                set_task_pending(review_id, force=True)
            return {
                "kind": "dispatch_codex_review",
                "task_id": review_id,
                "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                "blocker_id": "CLAUDE_RESULT_REVIEW_REQUIRED",
                "follow_up": "stale running pid recovered; rerun Codex review",
            }
        if review_status not in {"running", "completed", "superseded_by_evidence"}:
            if not dry_run:
                write_task_descriptors([completed_task_id])
                set_task_pending(review_id)
            return {
                "kind": "dispatch_codex_review",
                "task_id": review_id,
                "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                "blocker_id": "CLAUDE_RESULT_REVIEW_REQUIRED",
                "follow_up": f"review completed Claude task {completed_task_id}",
            }
        if not review_has_required_files:
            if not dry_run:
                set_task_pending(review_id, force=True)
            return {
                "kind": "dispatch_codex_review",
                "task_id": review_id,
                "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                "blocker_id": "CLAUDE_RESULT_REVIEW_REQUIRED",
                "follow_up": f"review output missing for completed Claude task {completed_task_id}",
            }
        return {
            "kind": "wait_for_codex_review",
            "task_id": review_id,
            "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
            "blocker_id": "CLAUDE_RESULT_REVIEW_REQUIRED",
        }

    priority_index = {task_id: idx for idx, task_id in enumerate(REMEDIATION_PRIORITY)}
    ordered_blockers = sorted(
        blockers,
        key=lambda item: priority_index.get(str(item.get("remediation_task_id") or ""), len(REMEDIATION_PRIORITY)),
    )

    for item in ordered_blockers:
        task_id = item.get("remediation_task_id")
        if not task_id:
            continue
        task_id = str(task_id)
        claude_descriptor = claude_task_descriptor(task_id)
        codex_descriptor = codex_review_descriptor(task_id)
        if not required_outputs_exist(claude_descriptor):
            task_status = task_effective_status(task_id)
            if task_status == "running" and task_running_stale(task_id):
                if not dry_run:
                    set_task_pending(task_id, force=True)
                return {
                    "kind": "dispatch_claude_remediation",
                    "task_id": task_id,
                    "task_descriptor": rel(TASKS_DIR / f"{task_id}.json"),
                    "blocker_id": item["id"],
                    "follow_up": "stale running pid recovered; rerun Claude remediation",
                }
            if task_status not in {"running", "completed", "superseded_by_evidence"}:
                if not dry_run:
                    set_task_pending(task_id)
                return {
                    "kind": "dispatch_claude_remediation",
                    "task_id": task_id,
                    "task_descriptor": rel(TASKS_DIR / f"{task_id}.json"),
                    "blocker_id": item["id"],
                    "follow_up": f"run {review_task_id_for(task_id)} after Claude emits required files",
                }
            return {
                "kind": "wait_for_claude_remediation",
                "task_id": task_id,
                "task_descriptor": rel(TASKS_DIR / f"{task_id}.json"),
                "blocker_id": item["id"],
            }
        if not codex_passed(task_id):
            review_id = review_task_id_for(task_id)
            review_status = task_effective_status(review_id)
            followup_task_id = failed_review_followup_task(task_id) if codex_failed(task_id) else None
            if followup_task_id:
                if current_task_running(followup_task_id):
                    return {
                        "kind": "wait_for_claude_remediation",
                        "task_id": followup_task_id,
                        "task_descriptor": rel(TASKS_DIR / f"{followup_task_id}.json"),
                        "blocker_id": item["id"],
                        "follow_up": f"Codex review {review_id} failed; implementation remediation is already running",
                    }
                followup_status = task_effective_status(followup_task_id)
                if followup_status == "running" and not task_running_stale(followup_task_id):
                    return {
                        "kind": "wait_for_claude_remediation",
                        "task_id": followup_task_id,
                        "task_descriptor": rel(TASKS_DIR / f"{followup_task_id}.json"),
                        "blocker_id": item["id"],
                        "follow_up": f"Codex review {review_id} failed; implementation remediation is already running",
                    }
                if not dry_run:
                    write_task_descriptors([followup_task_id])
                    set_task_pending(followup_task_id, force=True)
                return {
                    "kind": "dispatch_claude_remediation",
                    "task_id": followup_task_id,
                    "task_descriptor": rel(TASKS_DIR / f"{followup_task_id}.json"),
                    "blocker_id": item["id"],
                    "follow_up": f"Codex review {review_id} failed; dispatch implementation remediation before rerunning {task_id}",
                }
            if codex_failed(task_id):
                continue
            if review_status == "running" and task_running_stale(review_id):
                if not dry_run:
                    set_task_pending(review_id, force=True)
                return {
                    "kind": "dispatch_codex_review",
                    "task_id": review_id,
                    "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                    "blocker_id": item["id"],
                    "follow_up": "stale running pid recovered; rerun Codex review",
                }
            if review_status not in {"running", "completed", "superseded_by_evidence"}:
                if not dry_run:
                    set_task_pending(review_id)
                return {
                    "kind": "dispatch_codex_review",
                    "task_id": review_id,
                    "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                    "blocker_id": item["id"],
                    "follow_up": "rerun shutdown readiness controller after Codex review",
                }
            return {
                "kind": "wait_for_codex_review",
                "task_id": review_id,
                "task_descriptor": rel(TASKS_DIR / f"{review_id}.json"),
                "blocker_id": item["id"],
            }
        continue
    if any(item.get("id") == "PAPER_EXIT_OUTCOME_SIMULATOR_MISSING" for item in blockers):
        return {
            "kind": "codex_direct_fix_required",
            "task_id": "paper_exit_outcome_simulator_non_live",
            "blocker_id": "PAPER_EXIT_OUTCOME_SIMULATOR_MISSING",
            "follow_up": "build or validate a non-live paper exit/outcome simulator before fee-charging paper fills can resume",
        }
    if any(
        item.get("id") == "PAPER_EDGE_UNPROVEN"
        and codex_passed(PAPER_EDGE_RECOVERY_TASK_ID)
        for item in blockers
    ):
        return {
            "kind": "monitor_shadow_outcome_observer",
            "task_id": "paper_shadow_outcome_observer",
            "blocker_id": "PAPER_EDGE_UNPROVEN",
            "follow_up": "continue observing blocked paper intents over 5m/15m/30m/1h horizons; do not loosen fill gate or claim positive edge without completed after-cost evidence",
        }

    decision_blockers = [
        item for item in blockers if item.get("category") == "OPERATOR_DECISION_REQUIRED"
    ]
    if decision_blockers:
        primary = decision_blockers[0]
        return {
            "kind": "operator_decision_required",
            "task_id": None,
            "blocker_id": primary.get("id"),
            "decision_packet": primary.get("decision_packet"),
            "follow_up": "operator must explicitly accept or decline paper-only shutdown limitations; live/canary remain blocked",
            "operator_decision_blockers": decision_blockers,
        }
    return {"kind": "monitor_only_no_dispatchable_blocker", "task_id": None}


def build_evidence(no_service_remediation: bool) -> Dict[str, Any]:
    return {
        "as_of_utc": iso_now(),
        "canonical_inputs": canonical_input_status(),
        "runtime_safety": runtime_safety(),
        "git_corruption": git_corruption(),
        "git_dirty_summary": git_dirty_summary(),
        "service_liveness": service_liveness(no_service_remediation),
        "closure": closure_evidence(),
        "worker_porting": worker_evidence(),
        "risk_gateway_tests": risk_gateway_test_evidence(),
        "worker_parity_markers": {
            worker_id: worker_parity_marker(worker_id)
            for worker_id in [
                "v2_market_ingestor_from_legacy_baseline",
                "v2_coinank_and_liquidation_bridge_from_legacy_baseline",
                "v2_feature_pipeline_and_ta_worker_from_legacy_baseline",
                "v2_orchestrator_adapter",
                "v2_signal_publisher",
            ]
        },
        "trainer_bridge": trainer_evidence(),
        "trainer_derived_acceptance": trainer_derived_acceptance_evidence(),
        "trainer_external_packages": package_profile(),
        "paper_runtime": paper_runtime_evidence(),
        "paper_shadow": paper_shadow_evidence(),
        "paper_shadow_outcome": paper_shadow_outcome_evidence(),
        "paper_edge": paper_edge_evidence(),
        "paper_edge_recovery": paper_edge_recovery_evidence(),
        "paper_post_filter": paper_post_filter_evidence(),
        "observatory": observatory_evidence(),
        "trade_permission": trade_permission_evidence(),
        "symbol_universe": symbol_evidence(),
        "public_freshness": public_freshness(),
        "queue": queue_evidence(),
    }


def loop_marker(evidence: Dict[str, Any]) -> str:
    safety = evidence["runtime_safety"]
    corrupted, _ = evidence["git_corruption"]
    if corrupted:
        return LOOP_BLOCKED
    if safety["live_gate"] != LIVE_GATE:
        return LOOP_BLOCKED
    if safety["final_approval_token"] != "absent" or safety["redis_trim_approval"] != "absent":
        return LOOP_BLOCKED
    if safety["live_symbols"]:
        return LOOP_BLOCKED
    return LOOP_READY


def render_report(state: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# CODEX_LEGACY_SHUTDOWN_READINESS_TAKEOVER_LOOP")
    lines.append("")
    lines.append(f"As of: {state['as_of_utc']}")
    lines.append("")
    lines.append(f"Loop marker: `{state['loop_marker']}`")
    lines.append(f"Shutdown recommendation: `{state['shutdown_recommendation']}`")
    lines.append(f"Live gate: `{state['live_gate']}`")
    lines.append(f"Final approval token: `{state['final_approval_token']}`")
    lines.append(f"Redis trim approval: `{state['redis_trim_approval']}`")
    lines.append(f"Live symbols: `{state['live_symbols']}`")
    lines.append("")
    lines.append("## Current decision")
    lines.append("")
    if state["shutdown_recommendation"] == SAFE:
        lines.append("All shutdown criteria pass for V2 paper/shadow only. Live is still not approved.")
    elif state["shutdown_recommendation"] == KEEP:
        lines.append("V2 paper/shadow can continue, but legacy remains needed as trainer/orchestrator parity reference.")
    else:
        lines.append("Legacy shutdown remains blocked because required parity, edge, dependency, or safety evidence is incomplete.")
    lines.append("")
    lines.append("## Blockers")
    lines.append("")
    if not state["blockers"]:
        lines.append("- none")
    else:
        for item in state["blockers"]:
            task = f"; remediation=`{item['remediation_task_id']}`" if item.get("remediation_task_id") else ""
            lines.append(f"- `{item['id']}` [{item['category']}]: {item['evidence']}{task}")
    lines.append("")
    lines.append("## Next action")
    lines.append("")
    action = state["next_action"]
    lines.append(f"- kind: `{action.get('kind')}`")
    if action.get("task_id"):
        lines.append(f"- task_id: `{action['task_id']}`")
    if action.get("task_descriptor"):
        lines.append(f"- descriptor: `{action['task_descriptor']}`")
    if action.get("blocker_id"):
        lines.append(f"- blocker: `{action['blocker_id']}`")
    lines.append("")
    lines.append("## Evidence snapshot")
    lines.append("")
    closure = state["evidence"]["closure"]
    lines.append(f"- closure commit: `{closure.get('latest_closure_commit_verified')}`")
    lines.append(f"- copied full-closure files: `{closure.get('copied_source_files_on_disk')}`")
    lines.append(f"- binary blobs inventoried only: `{closure.get('binary_checkpoint_blobs_inventoried_only')}`")
    lines.append(f"- Redis users / exchange API users / config importers: `{closure.get('redis_users')}` / `{closure.get('exchange_api_users')}` / `{closure.get('config_importers')}`")
    paper = state["evidence"]["paper_runtime"]
    lines.append(f"- paper runtime: `{paper.get('status')}`, PnL=`{paper.get('realized_pnl')}`, action=`{paper.get('latest_paper_action')}`")
    post_filter = state["evidence"].get("paper_post_filter", {})
    lines.append(
        "- post-filter paper: "
        f"`{post_filter.get('paper_only_interpretation')}`, "
        f"delta=`{post_filter.get('post_filter_realized_pnl_delta_usdt')}`, "
        f"fills=`{post_filter.get('post_filter_simulated_fills')}`, "
        f"no_unsafe_fills=`{post_filter.get('no_unsafe_fills')}`"
    )
    trainer = state["evidence"]["trainer_bridge"]
    lines.append(f"- trainer bridge: `{trainer.get('runtime_evidence_status')}`, accepted=`{trainer.get('accepted_as_legacy_hybrid_prediction')}`")
    trainer_acceptance = state["evidence"].get("trainer_derived_acceptance", {})
    lines.append(
        "- trainer derived evidence: "
        f"`{trainer_acceptance.get('go_no_go')}`, "
        f"operator_acceptance_required=`{trainer_acceptance.get('operator_acceptance_required')}`"
    )
    trade = state["evidence"]["trade_permission"]
    lines.append(
        f"- trade permission: `{trade.get('trade_permission_status')}`, "
        f"paper_only=`{trade.get('paper_only_classification')}`, "
        f"live_canary=`{trade.get('live_canary_classification')}`"
    )
    symbol = state["evidence"]["symbol_universe"]
    lines.append(f"- symbol universe age seconds: `{symbol.get('age_seconds')}`, live_symbols=`{symbol.get('live_symbols')}`")
    lines.append("")
    lines.append("## Hard constraints held")
    lines.append("")
    lines.append("- legacy bot tree remains read-only")
    lines.append("- live remains blocked_human_only")
    lines.append("- final approval token remains absent")
    lines.append("- Redis trim approval remains absent")
    lines.append("- old Redis writes remain absent in current V2 runtime payload")
    lines.append("- exchange actions, leverage changes, and margin mode changes remain absent in current V2 runtime payload")
    lines.append("")
    return "\n".join(lines)


def dashboard_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    counts = blocker_counts(state["blockers"])
    evidence = state["evidence"]
    paper = evidence["paper_runtime"]
    edge = evidence["paper_edge"]
    post_filter = evidence.get("paper_post_filter", {})
    services = evidence["service_liveness"]
    active_claude = state["next_action"].get("task_id") if state["next_action"].get("kind") in {"dispatch_claude_remediation", "wait_for_claude_remediation"} else None
    active_codex = state["next_action"].get("task_id") if state["next_action"].get("kind") in {"dispatch_codex_review", "wait_for_codex_review"} else None
    return {
        "task_id": "codex_shutdown_readiness_takeover",
        "as_of_utc": state["as_of_utc"],
        "go_no_go": state["loop_marker"],
        "current_recommendation": state["shutdown_recommendation"],
        "live_gate": state["live_gate"],
        "live_gate_status": state["live_gate"],
        "final_approval_token": state["final_approval_token"],
        "redis_trim_approval": state["redis_trim_approval"],
        "live_symbols": state["live_symbols"],
        "blocker_count": len(state["blockers"]),
        "blocker_counts": counts,
        "blockers": state["blockers"],
        "next_action": state["next_action"],
        "next_automatic_action": state["next_action"],
        "active_claude_task": active_claude,
        "active_codex_task": active_codex,
        "services": services,
        "services_active_count": services.get("active_count"),
        "services_total_count": services.get("total_count"),
        "services_inactive": services.get("inactive_units", []),
        "symbol_universe": evidence["symbol_universe"],
        "symbol_universe_freshness": evidence["symbol_universe"],
        "paper_shadow_freshness": evidence["paper_shadow"],
        "paper_post_filter_observation": post_filter,
        "legacy_v2_realtime_decision_observatory": evidence.get("observatory", {}),
        "observatory_to_action_controller_patch": observatory_to_action_payload(state),
        "paper_pnl_split": {
            "cumulative_paper_pnl_usdt_pre_plus_post": post_filter.get("cumulative_paper_pnl_usdt_pre_plus_post"),
            "post_filter_realized_pnl_delta_usdt": post_filter.get("post_filter_realized_pnl_delta_usdt"),
            "historical_negative_pnl_isolated": post_filter.get("historical_negative_pnl_isolated"),
            "post_filter_no_unsafe_fills": post_filter.get("no_unsafe_fills"),
            "paper_edge_positive_proven": post_filter.get("positive_edge_proven"),
            "paper_loss_attribution_override_active": post_filter.get("paper_loss_attribution_override_active"),
            "paper_loss_attribution_post_filter_event_delta_usdt": post_filter.get(
                "paper_loss_attribution_post_filter_event_delta_usdt"
            ),
        },
        "trainer_parity_state": evidence["trainer_bridge"],
        "trainer_derived_acceptance": evidence.get("trainer_derived_acceptance", {}),
        "paper_pnl": paper.get("realized_pnl") if paper.get("realized_pnl") is not None else edge.get("paper_pnl_current_usdt"),
        "fill_count": paper.get("fill_count") if paper.get("fill_count") is not None else edge.get("simulated_fills"),
        "blocked_intent_count": edge.get("blocked_intents"),
        "old_redis_write_status": "absent" if evidence["runtime_safety"].get("old_redis_writes_absent") else "observed_or_unknown",
        "exchange_action_status": "absent" if evidence["runtime_safety"].get("exchange_actions_absent") else "observed_or_unknown",
        "approval_token_status": {
            "final_approval_token": state["final_approval_token"],
            "redis_trim_approval": state["redis_trim_approval"],
        },
        "last_commit": evidence["closure"].get("latest_closure_commit_verified"),
        "git_dirty_classification": evidence["git_dirty_summary"],
        "source_paths": [
            rel(OUT / "codex_shutdown_takeover_status.json"),
            rel(OUT / "CODEX_SHUTDOWN_TAKEOVER_STATUS.md"),
            rel(WORKER_STATE),
            rel(PAPER_RUNTIME),
            rel(TRAINER_BRIDGE),
            rel(SYMBOL_UNIVERSE),
        ],
    }


def paper_post_filter_public_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    post_filter = state["evidence"].get("paper_post_filter", {})
    return {
        "task_id": "paper_edge_post_filter_observation_window",
        "generated_at": state["as_of_utc"],
        "source_observation_generated_at": post_filter.get("generated_at"),
        "source_status_path": post_filter.get("path"),
        "live_gate": state["live_gate"],
        "live_symbols": state["live_symbols"],
        "classification": post_filter.get("classification"),
        "post_filter_safety_classification": post_filter.get("post_filter_safety_classification"),
        "paper_only_interpretation": post_filter.get("paper_only_interpretation"),
        "post_filter_window_start_utc": post_filter.get("post_filter_window_start_utc"),
        "post_filter_window_end_utc": post_filter.get("post_filter_window_end_utc"),
        "post_filter_window_seconds": post_filter.get("post_filter_window_seconds"),
        "cumulative_paper_pnl_usdt_pre_plus_post": post_filter.get("cumulative_paper_pnl_usdt_pre_plus_post"),
        "post_filter_realized_pnl_delta_usdt": post_filter.get("post_filter_realized_pnl_delta_usdt"),
        "post_filter_simulated_fills": post_filter.get("post_filter_simulated_fills"),
        "post_filter_allowed_intents": post_filter.get("post_filter_allowed_intents"),
        "post_filter_blocked_intents_1h": post_filter.get("post_filter_blocked_intents_1h"),
        "post_filter_blocked_intents_6h_window": post_filter.get("post_filter_blocked_intents_6h_window"),
        "post_filter_fees_usdt": post_filter.get("post_filter_fees_usdt"),
        "post_filter_churn_events": post_filter.get("post_filter_churn_events"),
        "post_filter_no_unsafe_fills": post_filter.get("no_unsafe_fills"),
        "paper_edge_positive_proven": post_filter.get("positive_edge_proven"),
        "historical_negative_pnl_isolated": post_filter.get("historical_negative_pnl_isolated"),
        "paper_loss_attribution_override_active": post_filter.get("paper_loss_attribution_override_active"),
        "paper_loss_attribution_generated_at": post_filter.get("paper_loss_attribution_generated_at"),
        "paper_loss_attribution_post_filter_event_delta_usdt": post_filter.get(
            "paper_loss_attribution_post_filter_event_delta_usdt"
        ),
        "final_approval_token": state["final_approval_token"],
        "redis_trim_approval": state["redis_trim_approval"],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "shutdown_recommendation": state["shutdown_recommendation"],
    }


def observatory_to_action_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    observatory = state["evidence"].get("observatory", {})
    action = state["next_action"]
    paper_edge_task_status = task_effective_status(PAPER_EDGE_RECOVERY_TASK_ID)
    paper_edge_review_id = review_task_id_for(PAPER_EDGE_RECOVERY_TASK_ID)
    paper_edge_review_status = task_effective_status(paper_edge_review_id)
    trainer_full_task_status = task_effective_status("claude_port_v2_trainer_bridge_full_legacy_parity")
    trainer_derived_task_status = task_effective_status(TRAINER_DERIVED_ACCEPTANCE_TASK_ID)
    action_task_id = str(action.get("task_id") or "")
    paper_edge_is_current_action = action_task_id in {PAPER_EDGE_RECOVERY_TASK_ID, paper_edge_review_id}
    action_kind = str(action.get("kind") or "")
    if action_task_id == PAPER_EDGE_RECOVERY_TASK_ID and action_kind == "wait_for_claude_remediation":
        paper_edge_action_state = "implementation_running"
    elif action_task_id == PAPER_EDGE_RECOVERY_TASK_ID:
        paper_edge_action_state = "implementation_dispatch_required"
    elif action_task_id == paper_edge_review_id:
        paper_edge_action_state = "codex_review_required"
    elif paper_edge_task_status == "running":
        paper_edge_action_state = "implementation_running"
    elif paper_edge_review_status == "running":
        paper_edge_action_state = "codex_review_running"
    elif observatory.get("edge_action_required") and codex_failed(PAPER_EDGE_RECOVERY_TASK_ID):
        paper_edge_action_state = "implementation_remediation_required"
    elif observatory.get("edge_action_required") and not codex_passed(PAPER_EDGE_RECOVERY_TASK_ID):
        paper_edge_action_state = "paper_edge_recovery_required"
    else:
        paper_edge_action_state = "not_current_action"
    return {
        "task_id": "observatory_to_action_controller_patch",
        "generated_at": state["as_of_utc"],
        "go_no_go": "OBSERVATORY_TO_ACTION_CONTROLLER_PATCH_READY",
        "observatory_go_no_go": observatory.get("go_no_go"),
        "legacy_trainer_health": observatory.get("legacy_trainer_health"),
        "legacy_signal_health": observatory.get("legacy_signal_health"),
        "legacy_signal_comparison_classification": observatory.get("legacy_signal_comparison_classification"),
        "v2_decision_quality": observatory.get("v2_decision_quality"),
        "paper_edge_status": observatory.get("paper_edge_status"),
        "paper_edge_action_required": observatory.get("edge_action_required"),
        "trainer_parity_status": observatory.get("trainer_parity_status"),
        "trainer_parity_gaps": observatory.get("trainer_parity_gaps"),
        "trainer_action_required": observatory.get("trainer_action_required"),
        "post_filter_fill_interpretation": observatory.get("post_filter_fill_interpretation"),
        "next_action": action,
        "paper_edge_recovery_task_status": paper_edge_task_status,
        "paper_edge_recovery_review_task_id": paper_edge_review_id,
        "paper_edge_recovery_review_status": paper_edge_review_status,
        "paper_edge_recovery_action_state": paper_edge_action_state,
        "trainer_full_parity_task_status": trainer_full_task_status,
        "trainer_derived_acceptance_task_status": trainer_derived_task_status,
        "active_or_next_task_is_paper_edge_recovery": paper_edge_is_current_action
        or paper_edge_task_status == "running"
        or paper_edge_review_status == "running",
        "trainer_full_parity_remains_queued_or_resolved": trainer_full_task_status in {
            "pending",
            "running",
            "completed",
            "superseded_by_evidence",
        }
        or trainer_derived_task_status in {"pending", "running", "completed", "superseded_by_evidence"},
        "shutdown_recommendation": state["shutdown_recommendation"],
        "live_gate": state["live_gate"],
        "live_symbols": state["live_symbols"],
        "final_approval_token": state["final_approval_token"],
        "redis_trim_approval": state["redis_trim_approval"],
        "old_redis_write_status": "absent" if state["evidence"]["runtime_safety"].get("old_redis_writes_absent") else "observed_or_unknown",
        "exchange_action_status": "absent" if state["evidence"]["runtime_safety"].get("exchange_actions_absent") else "observed_or_unknown",
        "approves_live": False,
        "approves_legacy_shutdown": False,
    }


def render_observatory_to_action_report(state: Dict[str, Any]) -> str:
    payload = observatory_to_action_payload(state)
    lines = [
        "# Observatory To Action Controller Patch",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "This patch makes observatory findings actionable. It does not approve live trading, canary trading, or legacy shutdown.",
        "",
        "## Current Findings",
        "",
        f"- observatory: `{payload['observatory_go_no_go']}`",
        f"- legacy trainer: `{payload['legacy_trainer_health']}`",
        f"- legacy signals: `{payload['legacy_signal_health']}`",
        f"- signal comparison classification: `{payload['legacy_signal_comparison_classification']}`",
        f"- V2 decision quality: `{payload['v2_decision_quality']}`",
        f"- paper edge: `{payload['paper_edge_status']}`",
        f"- post-filter interpretation: `{payload['post_filter_fill_interpretation']}`",
        f"- trainer parity: `{payload['trainer_parity_status']}`",
        f"- trainer gaps: `{payload['trainer_parity_gaps']}`",
        "",
        "## Action Routing",
        "",
        f"- next action: `{payload['next_action'].get('kind')}`",
        f"- next task: `{payload['next_action'].get('task_id')}`",
        f"- paper edge recovery status: `{payload['paper_edge_recovery_task_status']}`",
        f"- trainer full parity status: `{payload['trainer_full_parity_task_status']}`",
        f"- trainer derived/native packet status: `{payload['trainer_derived_acceptance_task_status']}`",
        "",
        "Rules now enforced:",
        "",
        "- `EDGE_PENDING` or `EDGE_PENDING_INSUFFICIENT_SAMPLE` dispatches/unsticks paper edge recovery.",
        "- trainer parity not equal to `FULL_LEGACY_PARITY_READY` keeps full parity or derived/native acceptance work queued.",
        "- stale legacy signals are source-limited and classified as `MISSING_EVIDENCE_CANNOT_COMPARE`.",
        "- zero post-filter fills remain `POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING`, not positive edge.",
        "- insufficient sample never claims 99% correctness.",
        "",
        "## Safety",
        "",
        f"- live_gate: `{payload['live_gate']}`",
        f"- live_symbols: `{payload['live_symbols']}`",
        f"- final approval token: `{payload['final_approval_token']}`",
        f"- Redis trim approval: `{payload['redis_trim_approval']}`",
        f"- old Redis write status: `{payload['old_redis_write_status']}`",
        f"- exchange action status: `{payload['exchange_action_status']}`",
        "",
    ]
    return "\n".join(lines)


def blocker_counts(blockers: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "P0_SHUTDOWN_BLOCKER": 0,
        "P1_SHUTDOWN_SUPPORT": 0,
        "P2_LIVE_ONLY_BLOCKED": 0,
        "INFO_ONLY": 0,
        "OPERATOR_DECISION_REQUIRED": 0,
    }
    for item in blockers:
        category = str(item.get("category") or "INFO_ONLY")
        counts.setdefault(category, 0)
        counts[category] += 1
    return counts


def write_outputs(state: Dict[str, Any]) -> None:
    payload = dashboard_payload(state)
    blocker_matrix = {
        "as_of_utc": state["as_of_utc"],
        "current_recommendation": state["shutdown_recommendation"],
        "counts": blocker_counts(state["blockers"]),
        "blockers": state["blockers"],
    }
    recommendation = {
        "as_of_utc": state["as_of_utc"],
        "recommendation": state["shutdown_recommendation"],
        "live_gate": state["live_gate"],
        "final_approval_token": state["final_approval_token"],
        "redis_trim_approval": state["redis_trim_approval"],
        "blocker_count": len(state["blockers"]),
    }
    write_json(OUT / "shutdown_readiness_state.json", state)
    write_json(OUT / "codex_shutdown_takeover_status.json", state)
    write_json(OUT / "blocker_matrix.json", blocker_matrix)
    write_json(OUT / "current_recommendation.json", recommendation)
    write_text(OUT / "current_recommendation.md", state["shutdown_recommendation"] + "\n")
    write_text(OUT / "CODEX_SHUTDOWN_TAKEOVER_STATUS.md", render_report(state))
    write_text(OUT / "CODEX_GO_NO_GO.md", state["loop_marker"] + "\n")
    write_json(OUT / "operator_dashboard_payload.json", dashboard_payload(state))
    write_json(PUBLIC / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC / "codex_shutdown_takeover_status.json", state)
    write_json(PUBLIC / "blocker_matrix.json", blocker_matrix)
    write_text(PUBLIC / "CODEX_SHUTDOWN_TAKEOVER_STATUS.md", render_report(state))
    write_text(PUBLIC / "CODEX_GO_NO_GO.md", state["loop_marker"] + "\n")
    write_json(PUBLIC_PAPER_POST_FILTER, paper_post_filter_public_payload(state))
    observatory_action_payload = observatory_to_action_payload(state)
    write_text(OBSERVATORY_TO_ACTION_OUT / "GO_NO_GO.md", "OBSERVATORY_TO_ACTION_CONTROLLER_PATCH_READY\n")
    write_text(
        OBSERVATORY_TO_ACTION_OUT / "OBSERVATORY_TO_ACTION_CONTROLLER_PATCH_REPORT.md",
        render_observatory_to_action_report(state),
    )
    write_json(OBSERVATORY_TO_ACTION_OUT / "operator_dashboard_payload.json", observatory_action_payload)
    write_json(OBSERVATORY_TO_ACTION_PUBLIC / "operator_dashboard_payload.json", observatory_action_payload)
    if state["next_action"].get("kind", "").startswith("dispatch_"):
        line = {"as_of_utc": state["as_of_utc"], **state["next_action"]}
        with (OUT / "claude_delegation_log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    if state["shutdown_recommendation"] == SAFE:
        write_text(
            OUT / "LEGACY_SHUTDOWN_READY_FOR_OPERATOR.md",
            "# Legacy Shutdown Ready For Operator\n\n"
            "SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY\n\n"
            "Codex has not stopped legacy. Operator action is still required.\n",
        )
        write_text(
            OUT / "LEGACY_SHUTDOWN_SAFE_PAPER_ONLY_PACKET.md",
            render_report(state),
        )
        write_text(
            OUT / "LEGACY_SHUTDOWN_COMMANDS_RECOMMENDED.md",
            "# Legacy Shutdown Commands Recommended\n\n"
            "Codex does not execute these commands. The operator must review and run shutdown commands manually.\n",
        )


def run_once(dry_run: bool = False, no_service_remediation: bool = False, verbose: bool = False) -> Dict[str, Any]:
    evidence = build_evidence(no_service_remediation=no_service_remediation)
    blockers = collect_blockers(evidence)
    recommendation = classify_shutdown(evidence, blockers)
    action = select_next_action(blockers, dry_run=dry_run)
    marker = loop_marker(evidence)
    safety = evidence["runtime_safety"]
    state: Dict[str, Any] = {
        "as_of_utc": evidence["as_of_utc"],
        "loop_marker": marker,
        "shutdown_recommendation": recommendation,
        "live_gate": safety["live_gate"],
        "final_approval_token": safety["final_approval_token"],
        "redis_trim_approval": safety["redis_trim_approval"],
        "live_symbols": safety["live_symbols"],
        "blockers": blockers,
        "next_action": action,
        "evidence": evidence,
        "controller_contract": {
            "never_claim_live_ready": True,
            "never_create_final_live_approval": True,
            "never_enable_live": True,
            "never_write_old_redis": True,
            "never_mutate_exchange": True,
            "legacy_root_read_only": True,
        },
    }
    if not dry_run:
        write_outputs(state)
        append_event(
            {
                "event": "codex_shutdown_readiness_takeover_tick",
                "loop_marker": marker,
                "shutdown_recommendation": recommendation,
                "blocker_count": len(blockers),
                "next_action_kind": action.get("kind"),
                "next_task_id": action.get("task_id"),
            }
        )
    if verbose:
        print(json.dumps({k: v for k, v in state.items() if k != "evidence"}, indent=2, default=str))
    return state


def run_daemon(poll_seconds: int, no_service_remediation: bool) -> None:
    while True:
        try:
            run_once(no_service_remediation=no_service_remediation)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            append_event({"event": "codex_shutdown_readiness_takeover_iteration_failed", "error": repr(exc)})
        time.sleep(max(30, poll_seconds))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="codex_legacy_shutdown_readiness_takeover")
    parser.add_argument("--once", action="store_true", help="run one controller tick")
    parser.add_argument("--daemon", action="store_true", help="run forever")
    parser.add_argument("--poll-seconds", type=int, default=120, help="daemon poll interval")
    parser.add_argument("--dry-run", action="store_true", help="compute state but do not write")
    parser.add_argument("--status", action="store_true", help="print concise state JSON")
    parser.add_argument("--no-service-remediation", action="store_true", help="observe V2 units without starting inactive ones")
    args = parser.parse_args(argv)
    if not (args.once or args.daemon or args.dry_run or args.status):
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.daemon:
        run_daemon(args.poll_seconds, no_service_remediation=args.no_service_remediation)
        return 0
    state = run_once(dry_run=args.dry_run, no_service_remediation=args.no_service_remediation, verbose=args.status)
    if state["loop_marker"] != LOOP_READY:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
