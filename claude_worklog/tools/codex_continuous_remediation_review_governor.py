#!/usr/bin/env python3
"""Codex 5-minute continuous remediation review governor.

Reviews Claude's legacy-log-to-V2 remediation loop while the V2 paper/shadow
runtime soak continues. Read-only with respect to legacy and exchange systems.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest"
CONT = BASE / "continuous_remediation"
OUT = CONT / "codex_review"
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
PUBLIC = ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest"

STATUS_PATH = CONT / "continuous_remediation_status.json"
GAP_MATRIX_PATH = CONT / "legacy_log_v2_gap_matrix.json"
SOAK_CODEX_PATH = BASE / "codex_governor/codex_15m_status.json"
SOAK_STATUS_PATH = BASE / "soak_status.json"
FRONTEND_STATUS_PATH = PUBLIC / "continuous_remediation_status.json"
FRONTEND_GAP_PATH = PUBLIC / "legacy_log_v2_gap_matrix.json"
FULL_OBSERVATION_STATUS_PATH = (
    ROOT / "v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"
)
FULL_OBSERVATION_DASHBOARD_PATH = (
    ROOT / "v2/frontend/public/v2_full_observation_builder/latest/operator_dashboard_payload.json"
)
POLICY_CONTRACT_PATH = (
    ROOT / "claude_worklog/final_readiness/v2_policy_architecture_shape_contract/latest/"
    "policy_architecture_shape_contract.json"
)
POLICY_PUBLIC_PATH = (
    ROOT / "v2/frontend/public/v2_policy_architecture_shape_contract/latest/operator_dashboard_payload.json"
)
ALT_DATA_CANDIDATE_PUBLISHER_PUBLIC_PATH = (
    ROOT / "v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
)
ALT_DATA_CANDIDATE_PUBLISHER_CODEX_GO_NO_GO = (
    ROOT
    / "claude_worklog/final_readiness/v2_alt_data_symbol_candidate_publisher/latest/codex_review/CODEX_GO_NO_GO.md"
)
ALT_DATA_CANDIDATE_PUBLISHER_PASS = (
    "V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_CODEX_PASS"
)
MARKET_PAGE_PATH = ROOT / "v2/frontend/src/pages/market/index.tsx"
MONITOR_CENTER_PAGE_PATH = ROOT / "v2/frontend/src/pages/monitor-center/index.tsx"
REALTIME_WEBSITE_COMPONENT_PATH = ROOT / "v2/frontend/src/components/realtimeWebsite/index.tsx"
REALTIME_PAYLOADS_PATH = ROOT / "v2/frontend/src/data/realtimeUserWebsitePayloads.ts"
NEXT_TASK_SELECTION_PATH = ROOT / "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json"
POLICY_CLAUDE_TASK_PATH = TASKS / "claude_fix_v2_gap_policy_architecture_shape_contract.json"
POLICY_CODEX_TASK_PATH = TASKS / "codex_review_fix_v2_gap_policy_architecture_shape_contract.json"

GO_READY = "CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY"
GO_BLOCKED = "CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_BLOCKED"
LIVE_GATE = "blocked_human_only"

REQUIRED_V2_PROCESSES = {
    "v2_native_ingestors_live_loop": "v2_native_ingestors_live_loop",
    "v2_feature_pipeline_native_loop": "v2_feature_pipeline_native_loop",
    "v2_rl_core_inference_loop": "v2_rl_core_inference_loop",
    "v2_orchestrator_arbitration_loop": "v2_orchestrator_arbitration_loop",
    "v2_trade_management_paper_loop": "v2_trade_management_paper_loop",
    "v2_production_replacement_runtime_guard": "v2_production_replacement_runtime_guard.py",
    "legacy_v2_comparator": "v2_legacy_v2_production_comparator.py",
    "production_equivalence_comparator": "v2_production_equivalence_comparator",
    "soak_observer": "v2_production_replacement_soak_observer",
    "payload_freshness_refresher": "v2_production_payload_freshness_refresher",
    "legacy_log_intelligence_observer": "v2_legacy_log_intelligence_observer",
    "continuous_remediation_loop": "v2_continuous_legacy_log_to_rebuild_remediation.py",
    "liquidation_wss_paper_shadow_daemon": "v2_liquidation_wss_loop",
    "position_history_persistent_tracker": "v2_position_history_persistent_tracker",
}

LIQUIDATION_WSS_HEARTBEAT_KEY = "v2:market:liquidations:heartbeat"
LIQUIDATION_WSS_HEARTBEAT_MAX_AGE_SECONDS = 180

POSITION_HISTORY_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"
POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS = 180

V2_REDIS = {
    "v2_all": "v2:*",
    "v2_market": "v2:market:*",
    "v2_features": "v2:features:*",
    "v2_prediction": "v2:prediction:*",
    "v2_trainer": "v2:trainer:*",
    "v2_orchestrator": "v2:orchestrator:*",
    "v2_paper": "v2:paper:*",
    "v2_risk": "v2:risk:*",
    "v2_legacy_log_observer": "v2:legacy_log_observer:*",
}

ACTIVE_FILES = [
    ROOT / "claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py",
    ROOT / "claude_worklog/tools/codex_continuous_remediation_review_governor.py",
    ROOT / "v2/backend/app/services/legacy_log_intelligence/service.py",
    ROOT / "v2/backend/app/cli/v2_legacy_log_intelligence_observer.py",
    ROOT / "v2/backend/app/cli/v2_native_ingestors_live_loop.py",
    ROOT / "v2/backend/app/cli/v2_feature_pipeline_native_loop.py",
    ROOT / "v2/backend/app/cli/v2_rl_core_inference_loop.py",
    ROOT / "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
    ROOT / "v2/backend/app/cli/v2_trade_management_paper_loop.py",
    ROOT / "v2/backend/app/cli/v2_production_equivalence_comparator.py",
    ROOT / "v2/backend/scripts/run_v2_replacement_readiness_scoreboard.py",
    ROOT / "v2/backend/app/services/rl_core/full_observation_builder.py",
    ROOT / "v2/backend/app/cli/v2_full_observation_builder_status.py",
    ROOT / "v2/backend/app/cli/v2_policy_architecture_shape_contract_status.py",
    ROOT / "v2/backend/app/services/alternative_data/symbol_candidate_publisher.py",
    ROOT / "v2/backend/app/cli/v2_alt_data_symbol_candidate_publisher.py",
    REALTIME_PAYLOADS_PATH,
    REALTIME_WEBSITE_COMPONENT_PATH,
    MARKET_PAGE_PATH,
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def age_seconds(payload: dict[str, Any]) -> int | None:
    for key in ("generated_utc", "generated_at", "loop_iteration_at", "heartbeat_at", "last_observed_utc"):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    return None


def refresh_full_observation_payload_if_needed(max_age_seconds: int = 300) -> dict[str, Any]:
    """Refresh the V2-owned full-observation payload when it is stale.

    This writes only worklog/public V2 payload files through the existing
    status CLI. It does not write Redis, touch legacy, or mutate exchange
    state.
    """
    before = read_json(FULL_OBSERVATION_STATUS_PATH)
    before_age = age_seconds(before)
    should_refresh = not before or before_age is None or before_age > max_age_seconds
    result: dict[str, Any] = {
        "path": str(FULL_OBSERVATION_STATUS_PATH.relative_to(ROOT)),
        "before_age_seconds": before_age,
        "refresh_attempted": should_refresh,
        "refresh_returncode": None,
        "refresh_stdout": "",
        "refresh_stderr": "",
    }
    if should_refresh:
        proc = run([
            str(ROOT / ".venv/bin/python"),
            "-m",
            "v2.backend.app.cli.v2_full_observation_builder_status",
            "--once",
        ], timeout=30)
        result.update({
            "refresh_returncode": proc.returncode,
            "refresh_stdout": proc.stdout.strip()[:1000],
            "refresh_stderr": proc.stderr.strip()[:1000],
        })
    after = read_json(FULL_OBSERVATION_STATUS_PATH)
    result["after_age_seconds"] = age_seconds(after)
    result["fresh"] = bool(after) and result["after_age_seconds"] is not None and result["after_age_seconds"] <= max_age_seconds
    result["state"] = after.get("state")
    result["checkpoint_compatibility_claimed"] = after.get("checkpoint_compatibility_claimed")
    result["policy_architecture_parity_claimed"] = after.get("policy_architecture_parity_claimed")
    result["generated_dims"] = {
        row.get("symbol"): row.get("generated_full_observation_dim")
        for row in after.get("per_symbol") or []
        if isinstance(row, dict)
    }
    result["zero_filled_field_count_total"] = sum(
        int(row.get("zero_filled_field_count") or 0)
        for row in after.get("per_symbol") or []
        if isinstance(row, dict)
    )
    return result


def checkpoint_duplicate_guard() -> dict[str, Any]:
    paths = sorted(
        path for path in TASKS.glob("*trainer_missing_checkpoint_weight_shape_contract*.json")
        if path.is_file()
    )
    return {
        "checkpoint_shape_contract_task_paths": [str(path.relative_to(ROOT)) for path in paths],
        "checkpoint_shape_contract_task_count": len(paths),
        "duplicate_checkpoint_tasks": len(paths) > 2,
    }


def alt_data_candidate_publisher_guard() -> dict[str, Any]:
    """Verify the candidate publisher remains proposal-only.

    This lane is allowed to publish candidate recommendations, but it
    must not mutate actual symbol sets or imply adoption in the
    frontend. The check is intentionally payload/source based so it is
    cheap enough for every governor cycle and does not run a browser.
    """
    payload = read_json(ALT_DATA_CANDIDATE_PUBLISHER_PUBLIC_PATH)
    pass_text = ""
    try:
        pass_text = ALT_DATA_CANDIDATE_PUBLISHER_CODEX_GO_NO_GO.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        pass_text = ""
    rows = payload.get("candidates")
    row_key = "candidates"
    if not isinstance(rows, list):
        rows = payload.get("candidate_summary")
        row_key = "candidate_summary"
    if not isinstance(rows, list):
        rows = []
        row_key = "missing"
    candidate_rows_safe = all(
        isinstance(row, dict)
        and row.get("candidate_only_not_adopted") is True
        and row.get("live_symbol_candidate") is False
        and row.get("approves_live") is not True
        and row.get("approves_canary") is not True
        and row.get("approves_legacy_shutdown") is not True
        and row.get("writes_exchange_orders") is not True
        and row.get("writes_old_redis") is not True
        for row in rows
    )
    public_age = age_seconds(payload)
    frontend_payloads = (
        REALTIME_PAYLOADS_PATH.read_text(encoding="utf-8", errors="replace")
        if REALTIME_PAYLOADS_PATH.exists()
        else ""
    )
    frontend_panel = (
        REALTIME_WEBSITE_COMPONENT_PATH.read_text(encoding="utf-8", errors="replace")
        if REALTIME_WEBSITE_COMPONENT_PATH.exists()
        else ""
    )
    market_page = (
        MARKET_PAGE_PATH.read_text(encoding="utf-8", errors="replace")
        if MARKET_PAGE_PATH.exists()
        else ""
    )
    panel_body = frontend_panel
    marker = "export function CandidatePublisherPanel"
    if marker in frontend_panel:
        panel_body = frontend_panel[frontend_panel.index(marker):]
        next_export = re.search(r"\n(export (function|const) [A-Z])", panel_body[10:])
        if next_export:
            panel_body = panel_body[: 10 + next_export.start()]
    forbidden_panel_controls = [
        token
        for token in (
            "<button",
            "<Button",
            "<form",
            "<Form",
            "<input",
            "<Input",
            "<select",
            "<Select",
            "<textarea",
            "<Textarea",
            "onClick=",
            "onSubmit=",
            "onChange=",
            "onMouseDown=",
            "onKeyDown=",
            "fetch(",
            "axios.",
            "XMLHttpRequest",
        )
        if token in panel_body
    ]
    required_labels = [
        "Candidate only",
        "not adopted",
        "Does not change training_symbols",
        "Does not change paper_symbols",
        "Does not change live_symbols",
        "Cannot override strict paper-fill gate",
        "Live trading remains blocked",
    ]
    labels_present = all(label in panel_body for label in required_labels)
    frontend_reads_payload = (
        "alt_data_candidate_publisher" in frontend_payloads
        and "/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
        in frontend_payloads
        and "useAltDataCandidatePublisher" in frontend_payloads
        and "useAltDataCandidatePublisher" in market_page
        and "<CandidatePublisherPanel" in market_page
    )
    frontend_reads_candidates = (
        "dashboard?.candidates" in panel_body
        and "candidate_summary" in panel_body
        and panel_body.find("candidates") < panel_body.find("candidate_summary")
    )
    return {
        "codex_pass_marker_path": str(
            ALT_DATA_CANDIDATE_PUBLISHER_CODEX_GO_NO_GO.relative_to(ROOT)
        ),
        "codex_pass_marker_actual": pass_text,
        "codex_pass_marker_ok": pass_text == ALT_DATA_CANDIDATE_PUBLISHER_PASS,
        "public_payload_path": str(
            ALT_DATA_CANDIDATE_PUBLISHER_PUBLIC_PATH.relative_to(ROOT)
        ),
        "public_payload_present": bool(payload),
        "public_payload_age_seconds": public_age,
        "row_key": row_key,
        "candidate_count": payload.get("candidate_count"),
        "candidate_rows_observed": len(rows),
        "candidate_rows_safe": candidate_rows_safe,
        "candidate_state_counts": payload.get("candidate_state_counts"),
        "candidate_only_not_adopted": payload.get("candidate_only_not_adopted"),
        "live_gate": payload.get("live_gate"),
        "live_symbols": payload.get("live_symbols"),
        "live_symbols_expanded": payload.get("live_symbols_expanded"),
        "paper_symbols_expanded": payload.get("paper_symbols_expanded"),
        "training_symbols_expanded": payload.get("training_symbols_expanded"),
        "provider_network_calls_attempted": payload.get(
            "provider_network_calls_attempted"
        ),
        "may_not_override_strict_paper_fill_gate": payload.get(
            "may_not_override_strict_paper_fill_gate"
        ),
        "may_not_authorize_live_or_canary": payload.get(
            "may_not_authorize_live_or_canary"
        ),
        "may_not_place_orders": payload.get("may_not_place_orders"),
        "writes_legacy_redis": payload.get("writes_legacy_redis"),
        "writes_old_redis": payload.get("writes_old_redis"),
        "writes_exchange_orders": payload.get("writes_exchange_orders"),
        "approves_live": payload.get("approves_live"),
        "approves_canary": payload.get("approves_canary"),
        "approves_legacy_shutdown": payload.get("approves_legacy_shutdown"),
        "approves_redis_trim": payload.get("approves_redis_trim"),
        "frontend_reads_payload": frontend_reads_payload,
        "frontend_reads_candidates": frontend_reads_candidates,
        "frontend_required_labels_present": labels_present,
        "frontend_forbidden_controls": forbidden_panel_controls,
        "candidate_only": (
            pass_text == ALT_DATA_CANDIDATE_PUBLISHER_PASS
            and bool(payload)
            and row_key == "candidates"
            and candidate_rows_safe
            and payload.get("candidate_only_not_adopted") is True
            and payload.get("live_gate") == LIVE_GATE
            and payload.get("live_symbols") == []
            and payload.get("live_symbols_expanded") is False
            and payload.get("paper_symbols_expanded") is False
            and payload.get("training_symbols_expanded") is False
            and payload.get("provider_network_calls_attempted") is False
            and payload.get("may_not_override_strict_paper_fill_gate") is True
            and payload.get("may_not_authorize_live_or_canary") is True
            and payload.get("may_not_place_orders") is True
            and payload.get("writes_legacy_redis") is False
            and payload.get("writes_old_redis") is False
            and payload.get("writes_exchange_orders") is False
            and payload.get("approves_live") is False
            and payload.get("approves_canary") is False
            and payload.get("approves_legacy_shutdown") is False
            and payload.get("approves_redis_trim") is False
            and frontend_reads_payload
            and frontend_reads_candidates
            and labels_present
            and not forbidden_panel_controls
        ),
    }


def policy_architecture_guard(full_observation: dict[str, Any]) -> dict[str, Any]:
    contract = read_json(POLICY_CONTRACT_PATH)
    public = read_json(POLICY_PUBLIC_PATH)
    claude_task = read_json(POLICY_CLAUDE_TASK_PATH)
    codex_task = read_json(POLICY_CODEX_TASK_PATH)
    full_obs_state = str(full_observation.get("state") or "")
    full_obs_complete = full_obs_state == "FULL_OBSERVATION_BUILDER_COMPLETE"
    implementation_claimed = (
        contract.get("policy_port_implementation_claimed") is True
        or contract.get("policy_architecture_parity_claimed") is True
        or public.get("policy_port_implementation_claimed") is True
        or public.get("policy_architecture_parity_claimed") is True
    )
    auto_apply_allowed = claude_task.get("auto_apply_allowed_by_this_loop") is True
    claude_status = str(claude_task.get("status") or "")
    started_status = claude_status.lower() in {
        "in_progress",
        "started",
        "running",
        "implemented",
        "complete",
        "completed",
        "ready_for_codex",
    }
    premature = (not full_obs_complete) and (implementation_claimed or auto_apply_allowed or started_status)
    return {
        "policy_contract_path": str(POLICY_CONTRACT_PATH.relative_to(ROOT)),
        "policy_public_path": str(POLICY_PUBLIC_PATH.relative_to(ROOT)),
        "policy_contract_exists": bool(contract),
        "policy_public_exists": bool(public),
        "full_observation_state": full_obs_state,
        "full_observation_complete": full_obs_complete,
        "policy_port_implementation_claimed": implementation_claimed,
        "policy_task_auto_apply_allowed": auto_apply_allowed,
        "policy_claude_task_status": claude_task.get("status"),
        "policy_codex_task_status": codex_task.get("status"),
        "operator_decision_required_to_implement_port": (
            contract.get("operator_decision_required_to_implement_port") is True
            and public.get("operator_decision_required_to_implement_port") is True
        ),
        "checkpoint_compatibility_claimed": (
            contract.get("checkpoint_compatibility_claimed") is True
            or public.get("checkpoint_compatibility_claimed") is True
        ),
        "premature_policy_architecture_implementation": premature,
    }


def process_status() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, pattern in REQUIRED_V2_PROCESSES.items():
        proc = run(["pgrep", "-af", pattern], timeout=10)
        lines = proc.stdout.splitlines() if proc.returncode in (0, 1) else []
        matches = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if "grep" in stripped or "bash -lc" in stripped:
                continue
            if "codex_continuous_remediation_review_governor.py --once" in stripped:
                continue
            matches.append(stripped)
        out[name] = {
            "pattern": pattern,
            "running": bool(matches),
            "match_count": len(matches),
            "sample": matches[:5],
        }
    return out


def liquidation_wss_heartbeat_probe() -> dict[str, Any]:
    """Probe the V2 liquidation WSS daemon heartbeat key.

    Returns freshness state for the heartbeat:
      - present: True iff the key exists.
      - ttl_seconds: Redis TTL (or -2 if missing, -1 if no TTL).
      - heartbeat_age_seconds: derived from the payload's heartbeat_at /
        generated_utc fields.
      - fresh: True iff present, TTL positive, and age within max.
      - no_synthetic_liquidation_events / writes_legacy_redis /
        writes_exchange_orders mirror the payload fields so the
        governor cannot drift those invariants.
    """
    ttl_proc = run(["redis-cli", "TTL", LIQUIDATION_WSS_HEARTBEAT_KEY], timeout=10)
    ttl_text = (ttl_proc.stdout or "").strip()
    try:
        ttl = int(ttl_text)
    except ValueError:
        ttl = -2
    get_proc = run(["redis-cli", "GET", LIQUIDATION_WSS_HEARTBEAT_KEY], timeout=10)
    raw = (get_proc.stdout or "").strip()
    payload: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except (ValueError, TypeError):
            payload = {}
    age = age_seconds(payload) if payload else None
    present = bool(payload) and ttl > 0
    fresh = (
        present
        and age is not None
        and age <= LIQUIDATION_WSS_HEARTBEAT_MAX_AGE_SECONDS
    )
    return {
        "key": LIQUIDATION_WSS_HEARTBEAT_KEY,
        "present": present,
        "ttl_seconds": ttl,
        "heartbeat_age_seconds": age,
        "fresh": fresh,
        "max_age_seconds": LIQUIDATION_WSS_HEARTBEAT_MAX_AGE_SECONDS,
        "process_mode": payload.get("process_mode"),
        "service_active": payload.get("service_active"),
        "opt_in_enabled": payload.get("opt_in_enabled"),
        "no_synthetic_liquidation_events": payload.get(
            "no_synthetic_liquidation_events"
        ),
        "writes_legacy_redis": payload.get("writes_legacy_redis"),
        "writes_exchange_orders": payload.get("writes_exchange_orders"),
        "live_gate": payload.get("live_gate"),
        "live_symbols": payload.get("live_symbols"),
    }


def position_history_heartbeat_probe() -> dict[str, Any]:
    """Probe the V2 paper position-history persistent tracker heartbeat.

    Returns freshness state for the heartbeat plus the
    persistent-daemon contract fields. NO_OPEN_POSITION is NOT a
    failure: this probe never requires open positions or MFE/MAE/ROE
    to be populated.
    """
    ttl_proc = run(["redis-cli", "TTL", POSITION_HISTORY_HEARTBEAT_KEY], timeout=10)
    ttl_text = (ttl_proc.stdout or "").strip()
    try:
        ttl = int(ttl_text)
    except ValueError:
        ttl = -2
    get_proc = run(["redis-cli", "GET", POSITION_HISTORY_HEARTBEAT_KEY], timeout=10)
    raw = (get_proc.stdout or "").strip()
    payload: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except (ValueError, TypeError):
            payload = {}
    age = age_seconds(payload) if payload else None
    present = bool(payload) and ttl > 0
    fresh = (
        present
        and age is not None
        and age <= POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS
    )
    # ``open_position_symbols`` is a list in the daemon's heartbeat;
    # derive a count for operator visibility. Fall back to a count
    # field if a future schema bumps add it directly.
    open_symbols = payload.get("open_position_symbols")
    no_open_symbols = payload.get("no_open_position_symbols")
    open_count = payload.get("open_position_symbol_count")
    no_open_count = payload.get("no_open_position_symbol_count")
    if open_count is None and isinstance(open_symbols, list):
        open_count = len(open_symbols)
    if no_open_count is None and isinstance(no_open_symbols, list):
        no_open_count = len(no_open_symbols)
    return {
        "key": POSITION_HISTORY_HEARTBEAT_KEY,
        "present": present,
        "ttl_seconds": ttl,
        "heartbeat_age_seconds": age,
        "fresh": fresh,
        "max_age_seconds": POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS,
        "process_mode": payload.get("process_mode"),
        "service_active": payload.get("service_active"),
        "cycle_count": payload.get("cycle_count"),
        "open_position_symbols": open_symbols if isinstance(open_symbols, list) else [],
        "no_open_position_symbols": no_open_symbols if isinstance(no_open_symbols, list) else [],
        "open_position_symbol_count": open_count,
        "no_open_position_symbol_count": no_open_count,
        "no_synthesized_accepted_positions": payload.get(
            "no_synthesized_accepted_positions"
        ),
        "no_fabricated_excursion_metrics": payload.get(
            "no_fabricated_excursion_metrics"
        ),
        "no_shadow_observations_counted_as_accepted": payload.get(
            "no_shadow_observations_counted_as_accepted"
        ),
        "full_observation_consumption_allowed": payload.get(
            "full_observation_consumption_allowed"
        ),
        "writes_legacy_redis": payload.get("writes_legacy_redis"),
        "writes_exchange_orders": payload.get("writes_exchange_orders"),
        "live_gate": payload.get("live_gate"),
        "live_symbols": payload.get("live_symbols"),
    }


def redis_count(pattern: str) -> dict[str, Any]:
    proc = run(["redis-cli", "--scan", "--pattern", pattern], timeout=20)
    keys = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {
        "pattern": pattern,
        "count": len(keys),
        "sample": keys[:10],
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip()[:500],
    }


def task_paths_from_status(status: dict[str, Any]) -> set[Path]:
    paths: set[Path] = set()
    for row in status.get("claude_codex_task_pairs_written_or_existing") or []:
        for key in ("claude_task_path", "codex_task_path"):
            value = row.get(key)
            if value:
                paths.add(ROOT / value)
    for path in TASKS.glob("*legacy_log*.json"):
        paths.add(path)
    for path in TASKS.glob("*production_equivalence*.json"):
        paths.add(path)
    for path in TASKS.glob("*v2_gap*.json"):
        paths.add(path)
    return paths


def task_records(status: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(task_paths_from_status(status)):
        data = read_json(path)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        records.append({
            "path": str(path.relative_to(ROOT)),
            "exists": path.exists(),
            "json_object": bool(data),
            "task_id": data.get("task_id"),
            "kind": data.get("kind") or data.get("agent"),
            "status": data.get("status"),
            "gap_id": data.get("gap_id"),
            "tests_required_count": len(data.get("tests_required") or []),
            "required_v2_files_to_modify_count": len(data.get("required_v2_files_to_modify") or []),
            "forbidden_actions": data.get("forbidden_actions") or [],
            "contains_broad_ready_claim": bool(re.search(r"\b(full migration|shutdown ready|live ready|canary ready)\b", text, re.I)),
            "contains_legacy_mutation_permission": bool(re.search(r"modify /home/wali/Desktop/AI BOT|stop or restart legacy|execute legacy monitor scripts", text, re.I)) is False,
        })
    return records


def broad_audit_task_guard(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Reject broad audit tasks in the active remediation task set.

    The continuous remediation lane must dispatch narrow blocker fixes
    and their Codex reviews. Broad recurring audits belong outside this
    lane while observation/model blockers remain open.
    """
    broad_patterns = (
        "recurring_audit",
        "broad_audit",
        "full_audit",
        "audit_everything",
        "general_audit",
    )
    broad: list[str] = []
    for rec in tasks:
        haystack = " ".join(
            str(rec.get(key) or "")
            for key in ("path", "task_id", "kind", "gap_id", "status")
        ).lower()
        if any(pattern in haystack for pattern in broad_patterns):
            broad.append(rec["path"])
    return {
        "broad_audit_task_paths": broad,
        "broad_audit_task_count": len(broad),
        "no_broad_audit_tasks": not broad,
    }


def ui_drift_guard(
    *,
    full_observation: dict[str, Any],
    classified_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    selection = read_json(NEXT_TASK_SELECTION_PATH)
    selected = str(
        selection.get("selected_task_id")
        or selection.get("selected_primary_task")
        or selection.get("primary_lane")
        or ""
    )
    selection_age = age_seconds(selection)
    observation_or_model_blockers_open = (
        full_observation.get("state") != "FULL_OBSERVATION_BUILDER_COMPLETE"
        or any(
            gap.get("codex_classification")
            in {"BLOCKS_PRODUCTION_EQUIVALENCE", "OPERATOR_DECISION_REQUIRED"}
            for gap in classified_gaps
        )
    )
    ui_terms = ("ui", "frontend", "dashboard", "website", "rendering", "market_page")
    model_terms = (
        "observation",
        "model",
        "rl",
        "trainer",
        "checkpoint",
        "policy",
        "native_core",
        "feature",
        "ingestor",
        "position_history",
        "liquidation",
    )
    selected_lower = selected.lower()
    ui_only_selected = (
        bool(selected_lower)
        and any(term in selected_lower for term in ui_terms)
        and not any(term in selected_lower for term in model_terms)
    )
    selection_current = selection_age is not None and selection_age <= 1800
    drift = bool(
        selection_current
        and observation_or_model_blockers_open
        and ui_only_selected
    )
    return {
        "selection_path": str(NEXT_TASK_SELECTION_PATH.relative_to(ROOT)),
        "selection_age_seconds": selection_age,
        "selection_current": selection_current,
        "selected_task_id": selected,
        "primary_lane": selection.get("primary_lane"),
        "current_primary_blockers": selection.get("current_primary_blockers"),
        "observation_or_model_blockers_open": observation_or_model_blockers_open,
        "selected_task_ui_only": ui_only_selected,
        "ui_only_drift_while_observation_or_model_blockers_open": drift,
    }


def frontend_visibility_guard() -> dict[str, Any]:
    monitor = (
        MONITOR_CENTER_PAGE_PATH.read_text(encoding="utf-8", errors="replace")
        if MONITOR_CENTER_PAGE_PATH.exists()
        else ""
    )
    market = (
        MARKET_PAGE_PATH.read_text(encoding="utf-8", errors="replace")
        if MARKET_PAGE_PATH.exists()
        else ""
    )
    realtime = (
        REALTIME_WEBSITE_COMPONENT_PATH.read_text(encoding="utf-8", errors="replace")
        if REALTIME_WEBSITE_COMPONENT_PATH.exists()
        else ""
    )
    checks = {
        "continuous_remediation_status_visible": (
            "continuous_remediation_status" in monitor
            and "legacy_log_v2_gap_matrix" in monitor
        ),
        "full_observation_builder_visible": "v2_full_observation_builder" in monitor,
        "policy_architecture_blocker_visible": (
            "v2_policy_architecture_shape_contract" in monitor
        ),
        "candidate_publisher_visible": (
            "useAltDataCandidatePublisher" in market
            and "<CandidatePublisherPanel" in market
            and "dashboard?.candidates" in realtime
            and "Candidate only" in realtime
            and "not adopted" in realtime
        ),
    }
    checks["frontend_does_not_hide_blockers"] = all(checks.values())
    return checks


def codex_review_result_for(gap_id: str) -> str | None:
    if not gap_id:
        return None
    candidates = list(ROOT.glob(f"claude_worklog/final_readiness/**/{gap_id}/**/CODEX_GO_NO_GO.md"))
    candidates += list(ROOT.glob(f"claude_worklog/final_readiness/**/*{gap_id}*/**/CODEX_GO_NO_GO.md"))
    for path in candidates[:20]:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text.endswith("_PASS") or "_PASS_" in text:
            return "CODEX_PASS"
        if text.endswith("_FAIL") or "_FAIL" in text:
            return "CODEX_FAIL_REMEDIATION_REQUIRED"
    return None


def classify_gap(gap: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    gap_id = str(gap.get("gap_id") or "")
    cause = str(gap.get("cause") or "")
    severity = str(gap.get("severity") or "")
    review = codex_review_result_for(gap_id)
    related_tasks = [t for t in tasks if t.get("gap_id") == gap_id]
    task_state = "NO_TASK"
    if any((t.get("kind") == "codex_review" or str(t.get("task_id") or "").startswith("codex_review")) for t in related_tasks):
        task_state = "CODEX_REVIEW_PENDING"
    if any((t.get("kind") == "claude_narrow_remediation" or str(t.get("task_id") or "").startswith("claude")) for t in related_tasks):
        task_state = "CLAUDE_FIX_IN_FLIGHT"
    if review:
        classification = review
    elif cause == "missing_legacy_log_action_evidence" and gap.get("legacy_log_action") == "MISSING_EVIDENCE":
        classification = "NO_ACTION_REQUIRED_SAFE_BLOCK"
    elif gap_id == "trainer_missing_checkpoint_weight_shape_contract" and cause == "checkpoint_weight_missing":
        classification = "BLOCKS_PRODUCTION_EQUIVALENCE"
    elif gap_id == "trainer_missing_checkpoint_weight_shape_contract":
        classification = "OPERATOR_DECISION_REQUIRED"
    elif gap_id == "paper_fill_gate_blocked_with_reason" and gap.get("paper_fill_gate_block_reasons"):
        classification = "NO_ACTION_REQUIRED_SAFE_BLOCK"
    elif gap_id == "paper_fill_gate_block_reason_passthrough_missing" and gap.get("paper_fill_gate_block_reasons"):
        classification = "NO_ACTION_REQUIRED_SAFE_BLOCK"
    elif task_state == "CODEX_REVIEW_PENDING":
        classification = "CODEX_REVIEW_PENDING"
    elif task_state == "CLAUDE_FIX_IN_FLIGHT":
        classification = "CLAUDE_FIX_IN_FLIGHT"
    else:
        classification = "CODEX_FAIL_REMEDIATION_REQUIRED"
    return {
        **gap,
        "codex_classification": classification,
        "task_state": task_state,
        "related_task_paths": [t["path"] for t in related_tasks],
        "blocks_production_equivalence": classification == "BLOCKS_PRODUCTION_EQUIVALENCE",
    }


def safety_scan(task_records_: list[dict[str, Any]]) -> dict[str, Any]:
    exchange_pattern = re.compile(
        r"create_order|cancel_order|cancel_all|set_leverage|set_margin_mode|"
        r"futures_create_order|futures_cancel|private_post|sapi_post|place_order|modify_order"
    )
    redis_write_pattern = re.compile(r"\.set\(|\.hset\(|\.xadd\(|\.delete\(|\.xtrim\(|flushdb|flushall")
    exchange_hits: list[str] = []
    unsafe_redis_hits: list[str] = []
    redis_write_hits: list[str] = []
    for path in ACTIVE_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            if path.name == "codex_continuous_remediation_review_governor.py" and (
                "exchange_pattern" in line or line.strip().startswith("r\"")
            ):
                continue
            # Negative safety labels such as ``may_not_place_orders``
            # are expected in payload contracts and must not be
            # treated as executable exchange mutation paths.
            if "may_not_place_orders" in line:
                continue
            if path.name == "codex_continuous_remediation_review_governor.py" and "redis_write_pattern" in line:
                continue
            if exchange_pattern.search(line):
                exchange_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:180]}")
            if redis_write_pattern.search(line):
                redis_write_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:180]}")
                context = "\n".join(text.splitlines()[max(0, idx - 8): idx + 5])
                has_v2_guard = (
                    "key.startswith(\"v2:\")" in context
                    or "startswith(V2_REDIS_PREFIX)" in context
                    or "key.startswith(\"v2:\")" in text
                    or "startswith(V2_REDIS_PREFIX)" in text
                )
                if not has_v2_guard:
                    unsafe_redis_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:180]}")
    approval_hits: list[str] = []
    secret_hits: list[str] = []
    approval_re = re.compile(
        r'"approves_live"\s*:\s*true|"approves_canary"\s*:\s*true|'
        r'"approves_legacy_shutdown"\s*:\s*true|"approves_redis_trim"\s*:\s*true|'
        r"LIVE_APPROVAL_TOKEN|FINAL_LIVE_APPROVAL|REDIS_TRIM_APPROVAL",
        re.I,
    )
    secret_res = [
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
        re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{20,}"),
    ]
    scan_paths = [
        STATUS_PATH,
        GAP_MATRIX_PATH,
        FRONTEND_STATUS_PATH,
        FRONTEND_GAP_PATH,
        FULL_OBSERVATION_STATUS_PATH,
        FULL_OBSERVATION_DASHBOARD_PATH,
        POLICY_CONTRACT_PATH,
        POLICY_PUBLIC_PATH,
    ]
    scan_paths.extend(ROOT / rec["path"] for rec in task_records_ if rec.get("exists"))
    for path in scan_paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            if approval_re.search(line):
                approval_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:160]}")
            if "redacted" in line.lower():
                continue
            if any(pat.search(line) for pat in secret_res):
                secret_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:160]}")
    broad_claim_tasks = [rec["path"] for rec in task_records_ if rec.get("contains_broad_ready_claim")]
    unsafe_task_permissions = [
        rec["path"]
        for rec in task_records_
        if rec.get("task_id", "").startswith("claude") and rec.get("contains_legacy_mutation_permission")
    ]
    return {
        "exchange_mutation_hits": exchange_hits,
        "redis_write_hits": redis_write_hits,
        "unsafe_redis_write_hits": unsafe_redis_hits,
        "approval_hits": approval_hits,
        "secret_hits": secret_hits,
        "broad_claim_tasks": broad_claim_tasks,
        "unsafe_task_permissions": unsafe_task_permissions,
        "no_exchange_mutation": not exchange_hits,
        "no_old_redis_writes": not unsafe_redis_hits,
        "no_live_canary_shutdown_approval": not approval_hits,
        "no_raw_secrets_exposed": not secret_hits,
    }


def ensure_remediation_task(blockers: list[str]) -> str | None:
    if not blockers:
        return None
    TASKS.mkdir(parents=True, exist_ok=True)
    path = TASKS / "claude_continuous_remediation_review_governor_blocker_fix.json"
    payload = {
        "task_id": "claude_continuous_remediation_review_governor_blocker_fix",
        "agent": "claude",
        "status": "pending",
        "risk_level": "L2",
        "cwd": str(ROOT),
        "prompt": (
            "Fix only the current Codex continuous-remediation review blockers. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not stop legacy. Do not execute legacy scripts. "
            "Do not write old Redis. Do not call exchange mutation. Do not enable live. "
            "live_gate remains blocked_human_only and live_symbols remains []. "
            "Current blockers: " + "; ".join(blockers)
        ),
        "created_or_refreshed_utc": utc_now(),
    }
    write_json(path, payload)
    return str(path.relative_to(ROOT))


def evaluate() -> dict[str, Any]:
    generated = utc_now()
    status = read_json(STATUS_PATH)
    matrix = read_json(GAP_MATRIX_PATH)
    soak_codex = read_json(SOAK_CODEX_PATH)
    soak_status = read_json(SOAK_STATUS_PATH)
    processes = process_status()
    redis = {name: redis_count(pattern) for name, pattern in V2_REDIS.items()}
    liquidation_wss_heartbeat = liquidation_wss_heartbeat_probe()
    position_history_heartbeat = position_history_heartbeat_probe()
    tasks = task_records(status)
    classified_gaps = [classify_gap(g, tasks) for g in matrix.get("gaps") or []]
    full_observation = refresh_full_observation_payload_if_needed()
    candidate_publisher = alt_data_candidate_publisher_guard()
    checkpoint_guard = checkpoint_duplicate_guard()
    policy_guard = policy_architecture_guard(read_json(FULL_OBSERVATION_STATUS_PATH))
    broad_audit_guard = broad_audit_task_guard(tasks)
    ui_drift = ui_drift_guard(
        full_observation=full_observation,
        classified_gaps=classified_gaps,
    )
    frontend_visibility = frontend_visibility_guard()
    safety = safety_scan(tasks)

    status_age = age_seconds(status)
    matrix_age = age_seconds(matrix)
    soak_age = age_seconds(soak_status)
    missing_processes = [name for name, item in processes.items() if not item["running"]]
    empty_namespaces = [name for name, item in redis.items() if item["count"] <= 0]
    fail_blockers: list[str] = []
    if not status:
        fail_blockers.append("CONTINUOUS_REMEDIATION_STATUS_MISSING")
    elif status_age is None or status_age > 600:
        fail_blockers.append(f"CONTINUOUS_REMEDIATION_STATUS_STALE:{status_age}")
    if not matrix:
        fail_blockers.append("LEGACY_LOG_V2_GAP_MATRIX_MISSING")
    elif matrix_age is None or matrix_age > 600:
        fail_blockers.append(f"LEGACY_LOG_V2_GAP_MATRIX_STALE:{matrix_age}")
    if missing_processes:
        fail_blockers.append("V2_OR_REMEDIATION_PROCESS_MISSING:" + ",".join(missing_processes))
    if empty_namespaces:
        fail_blockers.append("V2_REDIS_NAMESPACE_EMPTY:" + ",".join(empty_namespaces))
    if not liquidation_wss_heartbeat["present"]:
        fail_blockers.append("LIQUIDATION_WSS_HEARTBEAT_MISSING")
    elif liquidation_wss_heartbeat["ttl_seconds"] <= 0:
        fail_blockers.append(
            f"LIQUIDATION_WSS_HEARTBEAT_TTL_NOT_POSITIVE:{liquidation_wss_heartbeat['ttl_seconds']}"
        )
    elif not liquidation_wss_heartbeat["fresh"]:
        fail_blockers.append(
            "LIQUIDATION_WSS_HEARTBEAT_STALE:"
            f"{liquidation_wss_heartbeat['heartbeat_age_seconds']}"
        )
    if liquidation_wss_heartbeat.get("writes_legacy_redis") is True:
        fail_blockers.append("LIQUIDATION_WSS_DAEMON_WRITES_LEGACY_REDIS_DRIFT")
    if liquidation_wss_heartbeat.get("writes_exchange_orders") is True:
        fail_blockers.append("LIQUIDATION_WSS_DAEMON_WRITES_EXCHANGE_ORDERS_DRIFT")
    if liquidation_wss_heartbeat.get("no_synthetic_liquidation_events") is False:
        fail_blockers.append("LIQUIDATION_WSS_DAEMON_SYNTHETIC_EVENT_DRIFT")
    # Persistent-daemon registration drift checks. We only fail on
    # *wrong* values, never on missing fields (older payloads remain
    # informational). Per-symbol liquidation keys remain optional;
    # no events means no keys, and that is not a fail condition.
    if liquidation_wss_heartbeat["present"]:
        observed_mode = liquidation_wss_heartbeat.get("process_mode")
        if observed_mode not in (None, "persistent_daemon"):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_PROCESS_MODE_NOT_PERSISTENT_DAEMON:{observed_mode}"
            )
        observed_gate = liquidation_wss_heartbeat.get("live_gate")
        if observed_gate not in (None, LIVE_GATE):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_LIVE_GATE_DRIFT:{observed_gate}"
            )
        observed_symbols = liquidation_wss_heartbeat.get("live_symbols")
        if observed_symbols not in (None, []):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_LIVE_SYMBOLS_DRIFT:{observed_symbols}"
            )
    # Position-history persistent-tracker drift checks. The probe is
    # tolerant of NO_OPEN_POSITION (no open positions is not a failure)
    # and never requires MFE/MAE/ROE to be populated. We only fail when
    # the heartbeat is absent, stale, mis-modeled, or carries drifted
    # safety flags.
    if not position_history_heartbeat["present"]:
        fail_blockers.append("POSITION_HISTORY_HEARTBEAT_MISSING")
    elif position_history_heartbeat["ttl_seconds"] <= 0:
        fail_blockers.append(
            f"POSITION_HISTORY_HEARTBEAT_TTL_NOT_POSITIVE:{position_history_heartbeat['ttl_seconds']}"
        )
    elif not position_history_heartbeat["fresh"]:
        fail_blockers.append(
            "POSITION_HISTORY_HEARTBEAT_STALE:"
            f"{position_history_heartbeat['heartbeat_age_seconds']}"
        )
    if position_history_heartbeat.get("writes_legacy_redis") is True:
        fail_blockers.append("POSITION_HISTORY_DAEMON_WRITES_LEGACY_REDIS_DRIFT")
    if position_history_heartbeat.get("writes_exchange_orders") is True:
        fail_blockers.append("POSITION_HISTORY_DAEMON_WRITES_EXCHANGE_ORDERS_DRIFT")
    if position_history_heartbeat.get("no_synthesized_accepted_positions") is False:
        fail_blockers.append("POSITION_HISTORY_DAEMON_SYNTHESIZED_ACCEPTED_POSITIONS_DRIFT")
    if position_history_heartbeat.get("no_fabricated_excursion_metrics") is False:
        fail_blockers.append("POSITION_HISTORY_DAEMON_FABRICATED_EXCURSION_METRICS_DRIFT")
    if (
        position_history_heartbeat.get("no_shadow_observations_counted_as_accepted")
        is False
    ):
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_SHADOW_COUNTED_AS_ACCEPTED_DRIFT"
        )
    if position_history_heartbeat.get("full_observation_consumption_allowed") is True:
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_FULL_OBSERVATION_CONSUMPTION_DRIFT"
        )
    if position_history_heartbeat["present"]:
        observed_mode = position_history_heartbeat.get("process_mode")
        if observed_mode not in (None, "persistent_daemon"):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_PROCESS_MODE_NOT_PERSISTENT_DAEMON:{observed_mode}"
            )
        observed_service_active = position_history_heartbeat.get("service_active")
        if observed_service_active is False:
            fail_blockers.append("POSITION_HISTORY_DAEMON_SERVICE_ACTIVE_FALSE_DRIFT")
        observed_gate = position_history_heartbeat.get("live_gate")
        if observed_gate not in (None, LIVE_GATE):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_LIVE_GATE_DRIFT:{observed_gate}"
            )
        observed_symbols = position_history_heartbeat.get("live_symbols")
        if observed_symbols not in (None, []):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_LIVE_SYMBOLS_DRIFT:{observed_symbols}"
            )
    if not full_observation.get("fresh"):
        fail_blockers.append(f"FULL_OBSERVATION_BUILDER_PAYLOAD_STALE:{full_observation.get('after_age_seconds')}")
    if full_observation.get("refresh_attempted") and full_observation.get("refresh_returncode") not in (0, None):
        fail_blockers.append("FULL_OBSERVATION_BUILDER_REFRESH_FAILED")
    if full_observation.get("checkpoint_compatibility_claimed") is True:
        fail_blockers.append("FULL_OBSERVATION_CHECKPOINT_COMPATIBILITY_DRIFT")
    if full_observation.get("policy_architecture_parity_claimed") is True:
        fail_blockers.append("FULL_OBSERVATION_POLICY_PARITY_DRIFT")
    if int(full_observation.get("zero_filled_field_count_total") or 0) > 0:
        fail_blockers.append("FULL_OBSERVATION_ZERO_FILL_DRIFT")
    if checkpoint_guard.get("duplicate_checkpoint_tasks"):
        fail_blockers.append("DUPLICATE_CHECKPOINT_SHAPE_CONTRACT_TASKS")
    if policy_guard.get("premature_policy_architecture_implementation"):
        fail_blockers.append("POLICY_ARCHITECTURE_IMPLEMENTATION_STARTED_PREMATURELY")
    if policy_guard.get("checkpoint_compatibility_claimed") is True:
        fail_blockers.append("POLICY_ARCHITECTURE_CHECKPOINT_COMPATIBILITY_DRIFT")
    # Continuous-remediation readiness is bound to *runtime* soak health, not
    # the upstream soak governor's shutdown-ready decision. The upstream
    # governor is naturally BLOCKED until 6h soak + legacy shutdown gates
    # clear, but the remediation loop is healthy and useful before then.
    # Shutdown-governor decision remains visible as an informational field
    # below (summary.soak_governor_shutdown_ready) so the operator can see it
    # without conflating with remediation-loop readiness.
    if not soak_status or soak_age is None or soak_age > 600:
        fail_blockers.append(f"SOAK_RUNTIME_STATUS_STALE_OR_MISSING:{soak_age}")
    if soak_status.get("all_v2_processes_uninterrupted") is not True:
        fail_blockers.append("SOAK_RUNTIME_PROCESS_INTERRUPTION_DETECTED")
    if soak_status.get("v2_namespaces_never_empty") is not True:
        fail_blockers.append("SOAK_RUNTIME_V2_NAMESPACE_EMPTY_DETECTED")
    if soak_status.get("soak_1h_ready") is not True:
        fail_blockers.append("SOAK_RUNTIME_1H_NOT_READY")
    if soak_status.get("soak_6h_ready") is not True:
        fail_blockers.append("SOAK_RUNTIME_6H_NOT_READY")
    if not candidate_publisher.get("candidate_only"):
        fail_blockers.append("ALT_DATA_CANDIDATE_PUBLISHER_NOT_CANDIDATE_ONLY")
    if not broad_audit_guard.get("no_broad_audit_tasks"):
        fail_blockers.append("BROAD_AUDIT_TASKS_IN_ACTIVE_REMEDIATION_SCOPE")
    if ui_drift.get("ui_only_drift_while_observation_or_model_blockers_open"):
        fail_blockers.append("CLAUDE_UI_ONLY_DRIFT_WHILE_OBSERVATION_OR_MODEL_BLOCKERS_OPEN")
    if not frontend_visibility.get("frontend_does_not_hide_blockers"):
        fail_blockers.append("FRONTEND_HIDES_BLOCKERS")
    if any(item.get("codex_classification") == "CODEX_FAIL_REMEDIATION_REQUIRED" for item in classified_gaps):
        fail_blockers.append("GAP_CLASSIFICATION_REQUIRES_REMEDIATION")
    if any(t.get("contains_broad_ready_claim") for t in tasks):
        fail_blockers.append("TASK_CONTAINS_BROAD_READY_CLAIM")
    code_tasks_missing_tests = [
        t["path"] for t in tasks
        if str(t.get("task_id") or "").startswith("claude")
        and t.get("required_v2_files_to_modify_count", 0) > 0
        and t.get("tests_required_count", 0) == 0
    ]
    if code_tasks_missing_tests:
        fail_blockers.append("CLAUDE_CODE_TASK_WITHOUT_TESTS:" + ",".join(code_tasks_missing_tests[:5]))
    if not safety["no_exchange_mutation"]:
        fail_blockers.append("EXCHANGE_MUTATION_FOUND")
    if not safety["no_old_redis_writes"]:
        fail_blockers.append("OLD_REDIS_WRITE_RISK_FOUND")
    if not safety["no_live_canary_shutdown_approval"]:
        fail_blockers.append("LIVE_CANARY_SHUTDOWN_OR_REDIS_TRIM_APPROVAL_FOUND")
    if not safety["no_raw_secrets_exposed"]:
        fail_blockers.append("RAW_SECRET_EXPOSURE_FOUND")
    if safety["unsafe_task_permissions"]:
        fail_blockers.append("CLAUDE_TASK_LACKS_FORBIDDEN_LEGACY_MUTATION_GUARD")
    frontend_source = MONITOR_CENTER_PAGE_PATH.read_text(encoding="utf-8", errors="replace")
    if "continuous_remediation_status" not in frontend_source or "legacy_log_v2_gap_matrix" not in frontend_source:
        fail_blockers.append("FRONTEND_DOES_NOT_SURFACE_CONTINUOUS_REMEDIATION_GAPS")
    if "v2_full_observation_builder" not in frontend_source:
        fail_blockers.append("FRONTEND_DOES_NOT_SURFACE_FULL_OBSERVATION_BUILDER")
    if "v2_policy_architecture_shape_contract" not in frontend_source:
        fail_blockers.append("FRONTEND_DOES_NOT_SURFACE_POLICY_ARCHITECTURE_BLOCKER")

    go_no_go = GO_READY if not fail_blockers else GO_BLOCKED
    remediation_task = ensure_remediation_task(fail_blockers)
    classification_counts: dict[str, int] = {}
    for gap in classified_gaps:
        key = str(gap.get("codex_classification"))
        classification_counts[key] = classification_counts.get(key, 0) + 1
    return {
        "schema_version": "codex_continuous_remediation_review_governor_v1",
        "generated_utc": generated,
        "go_no_go": go_no_go,
        "fail_blockers": fail_blockers,
        "summary": {
            "continuous_remediation_status_age_seconds": status_age,
            "gap_matrix_age_seconds": matrix_age,
            "soak_status_age_seconds": soak_age,
            "v2_processes_running": len(REQUIRED_V2_PROCESSES) - len(missing_processes),
            "v2_processes_required": len(REQUIRED_V2_PROCESSES),
            "v2_namespaces_non_empty": not empty_namespaces,
            "liquidation_wss_daemon": liquidation_wss_heartbeat,
            "position_history_daemon": position_history_heartbeat,
            "gaps_total": len(classified_gaps),
            "gap_classification_counts": classification_counts,
            "soak_runtime_active": (
                soak_status.get("all_v2_processes_uninterrupted") is True
                and soak_status.get("v2_namespaces_never_empty") is True
                and soak_status.get("soak_1h_ready") is True
            ),
            "soak_governor_shutdown_ready": soak_codex.get("go_no_go") == "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY",
            "soak_governor_shutdown_decision": soak_codex.get("go_no_go"),
            "soak_minutes_observed": soak_status.get("minutes_observed"),
            "soak_1h_ready": soak_status.get("soak_1h_ready"),
            "soak_6h_ready": soak_status.get("soak_6h_ready"),
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "alt_data_candidate_publisher_candidate_only": candidate_publisher.get("candidate_only"),
            "alt_data_candidate_publisher_candidate_count": candidate_publisher.get("candidate_count"),
            "alt_data_candidate_publisher_row_key": candidate_publisher.get("row_key"),
            "frontend_does_not_hide_blockers": frontend_visibility.get("frontend_does_not_hide_blockers"),
            "broad_audit_task_count": broad_audit_guard.get("broad_audit_task_count"),
            "ui_only_drift_while_observation_or_model_blockers_open": ui_drift.get("ui_only_drift_while_observation_or_model_blockers_open"),
            "full_observation_builder_payload_fresh": full_observation.get("fresh"),
            "full_observation_builder_payload_age_seconds": full_observation.get("after_age_seconds"),
            "full_observation_builder_state": full_observation.get("state"),
            "full_observation_generated_dims": full_observation.get("generated_dims"),
            "checkpoint_shape_contract_task_count": checkpoint_guard.get("checkpoint_shape_contract_task_count"),
            "policy_architecture_implementation_started_prematurely": policy_guard.get("premature_policy_architecture_implementation"),
        },
        "gap_review": classified_gaps,
        "tasks_reviewed": tasks,
        "processes": processes,
        "redis": redis,
        "safety": {
            **safety,
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
        "full_observation_builder": full_observation,
        "alt_data_candidate_publisher": candidate_publisher,
        "checkpoint_duplicate_guard": checkpoint_guard,
        "policy_architecture_guard": policy_guard,
        "broad_audit_task_guard": broad_audit_guard,
        "ui_drift_guard": ui_drift,
        "frontend_visibility_guard": frontend_visibility,
        "source_payloads": {
            "continuous_remediation_status_path": str(STATUS_PATH.relative_to(ROOT)),
            "legacy_log_v2_gap_matrix_path": str(GAP_MATRIX_PATH.relative_to(ROOT)),
            "soak_codex_status_path": str(SOAK_CODEX_PATH.relative_to(ROOT)),
            "full_observation_builder_status_path": str(FULL_OBSERVATION_STATUS_PATH.relative_to(ROOT)),
            "policy_architecture_shape_contract_path": str(POLICY_CONTRACT_PATH.relative_to(ROOT)),
        },
        "remediation_task_path": remediation_task,
    }


def render_markdown(status: dict[str, Any]) -> str:
    lines = [
        "# Codex 5M Status: Continuous Remediation Review Governor",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
        (
            "The continuous remediation review governor is passing its checks."
            if status["go_no_go"] == GO_READY
            else "The continuous remediation review governor is blocked."
        ),
        "",
        "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, or Redis trim.",
        "",
        "## Runtime",
        "",
        f"- V2/remediation processes running: `{status['summary']['v2_processes_running']}/{status['summary']['v2_processes_required']}`",
        f"- V2 Redis namespaces non-empty: `{status['summary']['v2_namespaces_non_empty']}`",
        f"- Soak runtime active: `{status['summary']['soak_runtime_active']}`",
        f"- Soak governor shutdown-ready (informational): `{status['summary']['soak_governor_shutdown_ready']}` ({status['summary'].get('soak_governor_shutdown_decision') or 'unknown'})",
        f"- Soak minutes observed: `{status['summary']['soak_minutes_observed']}`",
        f"- Soak 1h ready: `{status['summary']['soak_1h_ready']}`",
        f"- Soak 6h ready: `{status['summary']['soak_6h_ready']}`",
        f"- Alt-data candidate publisher candidate-only: `{status['summary'].get('alt_data_candidate_publisher_candidate_only')}`",
        f"- Alt-data candidate count / row key: `{status['summary'].get('alt_data_candidate_publisher_candidate_count')}` / `{status['summary'].get('alt_data_candidate_publisher_row_key')}`",
        f"- Frontend does not hide blockers: `{status['summary'].get('frontend_does_not_hide_blockers')}`",
        f"- Broad audit task count in active remediation scope: `{status['summary'].get('broad_audit_task_count')}`",
        f"- UI-only drift while observation/model blockers open: `{status['summary'].get('ui_only_drift_while_observation_or_model_blockers_open')}`",
        f"- Full observation builder payload fresh: `{status['summary'].get('full_observation_builder_payload_fresh')}`",
        f"- Full observation builder state: `{status['summary'].get('full_observation_builder_state')}`",
        f"- Full observation generated dims: `{status['summary'].get('full_observation_generated_dims')}`",
        f"- Checkpoint shape-contract task count: `{status['summary'].get('checkpoint_shape_contract_task_count')}`",
        f"- Premature policy architecture implementation: `{status['summary'].get('policy_architecture_implementation_started_prematurely')}`",
        "",
        "## Gap Classifications",
        "",
    ]
    for key, value in sorted((status["summary"].get("gap_classification_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    if not status["summary"].get("gap_classification_counts"):
        lines.append("- none")
    lines.extend(["", "## Current Gaps", ""])
    for gap in status["gap_review"][:12]:
        lines.append(
            f"- `{gap.get('symbol')}` `{gap.get('gap_id')}` / `{gap.get('cause')}` -> `{gap.get('codex_classification')}`"
        )
    if not status["gap_review"]:
        lines.append("- none")
    lines.extend(["", "## Fail Blockers", ""])
    lines.extend(f"- `{b}`" for b in status["fail_blockers"]) if status["fail_blockers"] else lines.append("- none")
    lines.extend(["", "## Safety", ""])
    lines.append(f"- `live_gate`: `{LIVE_GATE}`")
    lines.append("- `live_symbols`: `[]`")
    lines.append("- `approves_live`: `false`")
    lines.append("- `approves_canary`: `false`")
    lines.append("- `approves_legacy_shutdown`: `false`")
    lines.append("- `approves_redis_trim`: `false`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(status: dict[str, Any]) -> None:
    write_json(OUT / "codex_5m_status.json", status)
    write_text(OUT / "CODEX_5M_STATUS.md", render_markdown(status))
    write_text(OUT / "CODEX_GO_NO_GO.md", status["go_no_go"] + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_continuous_remediation_review_governor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(read_json(OUT / "codex_5m_status.json"), indent=2, sort_keys=True))
        return 0
    if args.loop:
        while True:
            write_outputs(evaluate())
            time.sleep(max(60, int(args.interval_seconds)))
    write_outputs(evaluate())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
