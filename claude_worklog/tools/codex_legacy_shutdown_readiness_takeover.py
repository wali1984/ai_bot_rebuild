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
PAPER_EDGE = ROOT / "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/paper_shadow_24h_continuation.json"
TRADE_PERMISSION = ROOT / "claude_worklog/final_readiness/paper_strategy_edge_tightening/latest/account_permission_margin_blockers_status.json"
TRAINER_BRIDGE = ROOT / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json"
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
QUEUE_STATUS = ROOT / "claude_worklog/agent_supervisor/status/queue_status.json"
CURRENT_STATUS = ROOT / "claude_worklog/agent_supervisor/status/current_status.json"
NON_DRIFT_LOCK = ROOT / "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json"

ACTIVE_PUBLIC_FRESHNESS_PREFIXES = (
    "codex_shutdown_readiness_takeover/latest/",
    "codex_independent_v2_support/latest/public_payload_freshness_guard.json",
    "operator_runtime/coinank_market_intelligence/latest/",
    "operator_runtime/paper_online/latest/",
    "operator_runtime/paper_shadow_observation/latest/",
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
    "ai-bot-v2-paper-online-runtime.service",
    "ai-bot-v2-paper-shadow-observation.service",
    "ai-bot-v2-feature-snapshot-builder.service",
    "ai-bot-v2-symbol-universe-publisher.service",
    "ai-bot-v2-trainer-bridge.service",
]

TIMER_UNITS = ["ai-bot-v2-codex-shutdown-readiness-takeover.timer"]

REMEDIATION_PRIORITY = [
    "claude_resolve_remaining_unresolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map",
    "claude_port_v2_trainer_bridge_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema",
    "claude_remediate_v2_orchestrator_adapter_legacy_parity",
    "claude_remediate_v2_market_ingestor_full_runtime_sha_backfill",
    "claude_remediate_v2_coinank_liquidation_full_runtime_sha_backfill",
    "claude_remediate_v2_feature_pipeline_ta_full_runtime_sha_backfill",
    "claude_remediate_account_position_monitor_shutdown_parity",
    "claude_audit_stale_public_payloads_and_freshness_guard",
    "claude_replay_paper_edge_repair_from_legacy_trainer_output",
]

TEMPLATE_TASKS = [
    "claude_resolve_remaining_unresolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map",
    "claude_port_v2_trainer_bridge_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema",
    "claude_audit_stale_public_payloads_and_freshness_guard",
]

CODEX_REVIEW_IDS = {
    "claude_resolve_remaining_unresolved_local_imports": "codex_review_resolved_local_imports",
    "claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map": "codex_review_v2_risk_gateway_legacy_gate_implementations",
    "claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map": "codex_review_v2_risk_gateway_legacy_action_parity_tests",
    "claude_port_v2_trainer_bridge_full_legacy_parity": "codex_review_v2_trainer_full_legacy_parity",
    TRAINER_LINEAGE_ATTRIBUTION_TASK_ID: TRAINER_LINEAGE_ATTRIBUTION_REVIEW_ID,
    "claude_port_v2_signal_publisher_from_legacy_schema": "codex_review_v2_signal_publisher_legacy_schema_parity",
    "claude_audit_stale_public_payloads_and_freshness_guard": "codex_review_public_payload_freshness_shutdown_readiness",
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
    if latest.get("paper_action") == "PAPER_NOOP_BLOCKED" or latest.get("fill_price") is None:
        blockers.append("current_paper_intent_blocked_or_unfilled")
    total_recent_fills = recent_fill_stats.get("total_recent_fills")
    fills_last_hour = recent_fill_stats.get("fills_last_hour")
    if total_recent_fills == 0 or fills_last_hour == 0:
        blockers.append("fills_flat_recent_window")
    return {
        "path": rel(PAPER_RUNTIME),
        "generated_at": generated_at,
        "age_seconds": age,
        "status": "fresh" if age is not None and age <= 180 else "stale",
        "realized_pnl": realized,
        "unrealized_pnl": account.get("unrealized_pnl"),
        "latest_paper_action": latest.get("paper_action"),
        "latest_fill_price": latest.get("fill_price"),
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


def trade_permission_evidence() -> Dict[str, Any]:
    payload = read_json(TRADE_PERMISSION)
    if not isinstance(payload, dict):
        return {"path": rel(TRADE_PERMISSION), "status": "missing", "blockers": ["trade_permission_payload_missing"]}
    blockers = []
    trade_status = str(payload.get("trade_permission_status") or "")
    readonly_status = str(payload.get("readonly_account_evidence_status") or "")
    classes = payload.get("classifications") if isinstance(payload.get("classifications"), list) else []
    if "UNKNOWN" in trade_status or "UNKNOWN" in " ".join(map(str, classes)):
        blockers.append("trade_permission_readonly_unknown")
    if "STALE" in readonly_status or "STALE" in " ".join(map(str, classes)):
        blockers.append("readonly_account_evidence_stale")
    return {
        "path": rel(TRADE_PERMISSION),
        "generated_at": payload.get("generated_at"),
        "age_seconds": age_seconds(payload.get("generated_at")),
        "trade_permission_status": trade_status,
        "readonly_account_evidence_status": readonly_status,
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
    for item in trainer.get("blockers", []):
        blocker_id = "WRAPPER_NOT_LEGACY_HYBRID_PARITY" if "wrapper" in item or "legacy_hybrid" in item else item.upper()
        task_id = (
            TRAINER_LINEAGE_ATTRIBUTION_TASK_ID
            if blocker_id in TRAINER_LINEAGE_ATTRIBUTION_BLOCKERS
            else "claude_port_v2_trainer_bridge_full_legacy_parity"
        )
        blockers.append(
            blocker(
                blocker_id,
                "P0_SHUTDOWN_BLOCKER",
                f"trainer_bridge: {item}",
                task_id,
            )
        )

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
    for item in paper.get("blockers", []):
        if item == "paper_realized_pnl_negative":
            bid = "PAPER_PNL_NEGATIVE_BLOCKS_CANARY"
        elif "fill" in item:
            bid = "PAPER_EDGE_UNPROVEN"
        else:
            bid = item.upper()
        blockers.append(blocker(bid, "P0_SHUTDOWN_BLOCKER", f"paper_runtime: {item}", "claude_replay_paper_edge_repair_from_legacy_trainer_output"))

    paper_shadow = evidence["paper_shadow"]
    for item in paper_shadow.get("blockers", []):
        blockers.append(blocker(item.upper(), "P0_SHUTDOWN_BLOCKER", f"paper_shadow: {item}", "claude_audit_stale_public_payloads_and_freshness_guard"))

    edge = evidence["paper_edge"]
    for item in edge.get("blockers", []):
        bid = "PAPER_PNL_NEGATIVE_BLOCKS_CANARY" if "negative" in item else "PAPER_EDGE_UNPROVEN"
        blockers.append(blocker(bid, "P0_SHUTDOWN_BLOCKER", f"paper_edge: {item}", "claude_replay_paper_edge_repair_from_legacy_trainer_output"))

    trade = evidence["trade_permission"]
    for item in trade.get("blockers", []):
        blockers.append(
            blocker(
                "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY" if "permission" in item else item.upper(),
                "P0_SHUTDOWN_BLOCKER",
                f"trade_permission: {item}",
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
    return OUT / "claude_tasks" / task_id


def review_task_id_for(task_id: str) -> str:
    return CODEX_REVIEW_IDS.get(task_id, f"codex_review_{task_id}")


def codex_output_dir(task_id: str) -> Path:
    if task_id == TRAINER_LINEAGE_ATTRIBUTION_TASK_ID:
        return ROOT / "claude_worklog/final_readiness/trainer_lineage_attribution_parity/latest/codex_review"
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
            + "Task: Build V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_REMEDIATION_READY honestly. "
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
                if not dry_run:
                    write_task_descriptors([followup_task_id])
                    set_task_pending(followup_task_id)
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
        "trainer_external_packages": package_profile(),
        "paper_runtime": paper_runtime_evidence(),
        "paper_shadow": paper_shadow_evidence(),
        "paper_edge": paper_edge_evidence(),
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
    trainer = state["evidence"]["trainer_bridge"]
    lines.append(f"- trainer bridge: `{trainer.get('runtime_evidence_status')}`, accepted=`{trainer.get('accepted_as_legacy_hybrid_prediction')}`")
    trade = state["evidence"]["trade_permission"]
    lines.append(f"- trade permission: `{trade.get('trade_permission_status')}`")
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
        "trainer_parity_state": evidence["trainer_bridge"],
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
