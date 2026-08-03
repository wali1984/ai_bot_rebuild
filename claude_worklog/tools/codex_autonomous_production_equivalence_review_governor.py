#!/usr/bin/env python3
"""Codex autonomous production-equivalence review governor.

This governor is read-only with respect to Redis, legacy, and exchange
systems. It writes only Codex review status artifacts for the autonomous
production-equivalence burndown lane.
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

OUT = (
    ROOT
    / "claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/"
    "latest/codex_governor"
)
CLAUDE_CONTROLLER = (
    ROOT / "claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/latest"
)
QUEUE_DIR = (
    ROOT / "claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest"
)
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"

SOAK_STATUS = (
    ROOT / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/soak_status.json"
)
CONTINUOUS_CODEX_STATUS = (
    ROOT
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/"
    "continuous_remediation/codex_review/codex_5m_status.json"
)
LEGACY_LOG_STATUS = (
    ROOT
    / "v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/"
    "legacy_log_intelligence_status.json"
)
COMPARATOR_STATUS = (
    ROOT
    / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/"
    "production_equivalence_comparison.json"
)
FULL_OBSERVATION_STATUS = (
    ROOT / "v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"
)

QUEUE_GO_NO_GO = QUEUE_DIR / "codex_review/CODEX_GO_NO_GO.md"
QUEUE_JSON = QUEUE_DIR / "remaining_dim_execution_queue.json"
NEXT_TASKS_JSON = QUEUE_DIR / "next_10_feature_tasks.json"
QUEUE_PUBLIC_JSON = (
    ROOT
    / "v2/frontend/public/v2_full_observation_remaining_dim_execution_queue/latest/"
    "remaining_dim_execution_queue.json"
)

CONTROLLER_GO_NO_GO = CLAUDE_CONTROLLER / "GO_NO_GO.md"
CONTROLLER_STATUS = CLAUDE_CONTROLLER / "autonomous_burndown_status.json"

GO_READY = "CODEX_AUTONOMOUS_PRODUCTION_EQUIVALENCE_REVIEW_GOVERNOR_READY"
GO_BLOCKED = "CODEX_AUTONOMOUS_PRODUCTION_EQUIVALENCE_REVIEW_GOVERNOR_BLOCKED"
LIVE_GATE = "blocked_human_only"

QUEUE_REMEDIATED_READY = "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY"
CONTINUOUS_READY = "CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY"
CONTROLLER_READY = "V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY"

LIQUIDATION_HEARTBEAT_KEY = "v2:market:liquidations:heartbeat"
POSITION_HISTORY_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"
HEARTBEAT_MAX_AGE_SECONDS = 180

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("1m",)

BROAD_BUILDABLE_GROUP_RE = re.compile(
    r"^(?:portfolio_state|portfolio_state\[\*\]|.*reserved.*)$",
    re.I,
)
GENERIC_SOURCE_RE = re.compile(
    r"\bv2:\*\b|review builder code for exact source|portfolio_state\[\*\]",
    re.I,
)
BROAD_AUDIT_RE = re.compile(
    r"\bbroad audit\b|\baudit everything\b|\bfull audit loop\b|\baudit all\b",
    re.I,
)
POLICY_IMPL_RE = re.compile(
    r"policy_architecture_parity_claimed[\"']?\s*[:=]\s*true|"
    r"did_not_start_policy_architecture[\"']?\s*[:=]\s*false|"
    r"policy_architecture_(?:started|implementation_started)[\"']?\s*[:=]\s*true",
    re.I,
)
POLICY_NATURAL_RE = re.compile(
    r"\bstart(?:ed|ing)? policy architecture\b|\bimplement(?:ed|ing)? policy architecture\b",
    re.I,
)
CHECKPOINT_CLAIM_RE = re.compile(
    r"checkpoint_compatibility_claimed[\"']?\s*[:=]\s*true|"
    r"checkpoint compatibility (?:claimed|true|approved)",
    re.I,
)
APPROVAL_TRUE_RE = re.compile(
    r'"(?:approves_live|approves_canary|approves_legacy_shutdown|approves_redis_trim)"\s*:\s*true|'
    r'"(?:live_canary_shutdown_redis_trim_approval_tokens_created|paper_only_shutdown_acceptance_created)"\s*:\s*true',
    re.I,
)
EXCHANGE_MUTATION_RE = re.compile(
    r"create_order|cancel_order|cancel_all|set_leverage|set_margin_mode|"
    r"futures_create_order|futures_cancel|private_post|sapi_post|"
    r"\bplace_order\s*\(|\bmodify_order\s*\(|/fapi/",
    re.I,
)
OLD_REDIS_WRITE_RE = re.compile(
    r"(?:redis.*\.(?:set|hset|xadd|lpush|rpush|publish|delete|xtrim)\()|"
    r"(?:features:|market_price:|prediction:|risk:|paper:)",
    re.I,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def path_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def slugify_field_group(group: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", group.lower()).strip("_")


def marker_stem_for_slug(slug: str) -> str:
    stem = slug.upper()
    if stem.startswith("PORTFOLIO_STATE_PORTFOLIO_"):
        stem = "PORTFOLIO_STATE_" + stem[len("PORTFOLIO_STATE_PORTFOLIO_"):]
    return f"V2_FULL_OBSERVATION_{stem}"


def completed_codex_marker_for_group(group: str) -> str | None:
    slug = slugify_field_group(group)
    marker_stem = marker_stem_for_slug(slug)
    marker_path = (
        CLAUDE_CONTROLLER.parent
        / "per_task"
        / slug
        / "codex_review"
        / "CODEX_GO_NO_GO.md"
    )
    marker = read_text(marker_path)
    expected = {
        f"{marker_stem}_CODEX_PASS",
        f"{marker_stem}_BURNDOWN_CODEX_PASS",
        f"V2_FULL_OBSERVATION_{slug.upper()}_CODEX_PASS",
        f"V2_FULL_OBSERVATION_{slug.upper()}_BURNDOWN_CODEX_PASS",
    }
    if marker in expected:
        return path_label(marker_path)
    return None


def inflight_descriptor_for_group(group: str) -> str | None:
    slug = slugify_field_group(group)
    if not TASKS_DIR.exists():
        return None
    pattern = re.compile(
        rf"^\d+_(?:claude_fix|codex_review)_v2_full_observation_{re.escape(slug)}\.json$"
    )
    for path in sorted(TASKS_DIR.iterdir()):
        if not pattern.match(path.name):
            continue
        payload = read_json(path)
        if payload.get("status") in {"pending", "in_progress"}:
            return path_label(path)
    return None


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


def payload_age_seconds(payload: dict[str, Any]) -> int | None:
    for key in ("generated_utc", "generated_at", "heartbeat_at", "last_observed_utc", "finished_at"):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    cycle = payload.get("cycle")
    if isinstance(cycle, dict):
        parsed = parse_time(cycle.get("finished_at"))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    return None


def redis_get(key: str) -> str:
    try:
        proc = run(["redis-cli", "get", key], timeout=8)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def redis_get_json(key: str) -> dict[str, Any]:
    raw = redis_get(key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def redis_ttl(key: str) -> int | None:
    try:
        proc = run(["redis-cli", "ttl", key], timeout=8)
    except Exception:
        return None
    try:
        return int(proc.stdout.strip())
    except Exception:
        return None


def redis_exists(key: str) -> bool:
    try:
        proc = run(["redis-cli", "exists", key], timeout=8)
        return proc.stdout.strip() == "1"
    except Exception:
        return False


def redis_scan_count(pattern: str, limit: int = 20000) -> int:
    try:
        proc = run(["redis-cli", "--scan", "--pattern", pattern], timeout=20)
    except Exception:
        return 0
    if proc.returncode != 0:
        return 0
    return min(limit, len([line for line in proc.stdout.splitlines() if line.strip()]))


def pgrep_count(pattern: str) -> int:
    try:
        proc = run(["pgrep", "-af", pattern], timeout=8)
    except Exception:
        return 0
    if proc.returncode not in (0, 1):
        return 0
    return len(
        [
            line
            for line in proc.stdout.splitlines()
            if line.strip() and "codex_autonomous_production_equivalence_review_governor.py" not in line
        ]
    )


def heartbeat_probe(key: str, max_age_seconds: int = HEARTBEAT_MAX_AGE_SECONDS) -> dict[str, Any]:
    payload = redis_get_json(key)
    ttl = redis_ttl(key)
    age = payload_age_seconds(payload)
    return {
        "key": key,
        "present": bool(payload),
        "ttl_seconds": ttl,
        "age_seconds": age,
        "fresh": bool(payload) and ttl is not None and ttl > 0 and age is not None and age <= max_age_seconds,
        "generated_utc": payload.get("generated_utc") or payload.get("heartbeat_at"),
        "live_gate": payload.get("live_gate"),
        "live_symbols": payload.get("live_symbols"),
        "process_mode": payload.get("process_mode"),
        "service_active": payload.get("service_active"),
    }


def runtime_guard() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    soak = read_json(SOAK_STATUS)
    continuous = read_json(CONTINUOUS_CODEX_STATUS)
    legacy_log = read_json(LEGACY_LOG_STATUS)
    comparator = read_json(COMPARATOR_STATUS)
    full_observation = read_json(FULL_OBSERVATION_STATUS)
    liquidation = heartbeat_probe(LIQUIDATION_HEARTBEAT_KEY)
    position_history = heartbeat_probe(POSITION_HISTORY_HEARTBEAT_KEY)

    process_patterns = {
        "continuous_remediation_loop": "v2_continuous_legacy_log_to_rebuild_remediation.py",
        "legacy_log_observer": "v2_legacy_log_intelligence_observer",
        "comparator": "v2_production_equivalence_comparator",
        "liquidation_wss": "v2_liquidation_wss_loop",
        "position_history": "v2_position_history_persistent_tracker",
    }
    processes = {name: pgrep_count(pattern) for name, pattern in process_patterns.items()}
    v2_key_count = redis_scan_count("v2:*")

    if not soak.get("soak_6h_ready"):
        blockers.append("RUNTIME_SOAK_6H_NOT_READY")
    if continuous.get("go_no_go") != CONTINUOUS_READY or continuous.get("fail_blockers"):
        blockers.append("CONTINUOUS_REMEDIATION_GOVERNOR_NOT_READY")
    if not liquidation["fresh"]:
        blockers.append("LIQUIDATION_WSS_HEARTBEAT_NOT_FRESH")
    if not position_history["fresh"]:
        blockers.append("POSITION_HISTORY_HEARTBEAT_NOT_FRESH")
    if payload_age_seconds(legacy_log) is None or (payload_age_seconds(legacy_log) or 999999) > 600:
        blockers.append("LEGACY_LOG_OBSERVER_PAYLOAD_NOT_FRESH")
    if payload_age_seconds(comparator) is None or (payload_age_seconds(comparator) or 999999) > 900:
        blockers.append("COMPARATOR_PAYLOAD_NOT_FRESH")
    if payload_age_seconds(full_observation) is None or (payload_age_seconds(full_observation) or 999999) > 900:
        blockers.append("FULL_OBSERVATION_PAYLOAD_NOT_FRESH")
    if v2_key_count <= 0:
        blockers.append("V2_REDIS_NAMESPACE_EMPTY")
    for name, count in processes.items():
        if count <= 0:
            blockers.append(f"PROCESS_MISSING_{name.upper()}")

    live_gate_values = {
        "soak": soak.get("live_gate"),
        "full_observation": full_observation.get("live_gate"),
        "liquidation": liquidation.get("live_gate"),
        "position_history": position_history.get("live_gate"),
    }
    live_symbols_values = {
        "soak": soak.get("live_symbols"),
        "full_observation": full_observation.get("live_symbols"),
        "liquidation": liquidation.get("live_symbols"),
        "position_history": position_history.get("live_symbols"),
    }
    for name, value in live_gate_values.items():
        if value is not None and value != LIVE_GATE:
            blockers.append(f"LIVE_GATE_DRIFT_{name.upper()}")
    for name, value in live_symbols_values.items():
        if value is not None and value != []:
            blockers.append(f"LIVE_SYMBOLS_DRIFT_{name.upper()}")

    return (
        {
            "soak_6h_ready": soak.get("soak_6h_ready"),
            "soak_minutes_observed": soak.get("soak_minutes_observed"),
            "continuous_go_no_go": continuous.get("go_no_go"),
            "continuous_fail_blockers": continuous.get("fail_blockers") or [],
            "legacy_log_age_seconds": payload_age_seconds(legacy_log),
            "comparator_age_seconds": payload_age_seconds(comparator),
            "full_observation_age_seconds": payload_age_seconds(full_observation),
            "full_observation_state": full_observation.get("state"),
            "v2_redis_key_count_sample": v2_key_count,
            "process_counts": processes,
            "liquidation_heartbeat": liquidation,
            "position_history_heartbeat": position_history,
            "live_gate_values": live_gate_values,
            "live_symbols_values": live_symbols_values,
        },
        blockers,
    )


def expand_source_key(key: str, symbol: str) -> list[str]:
    keys = [key.replace("{symbol}", symbol)]
    expanded: list[str] = []
    for item in keys:
        if "{timeframe}" in item:
            expanded.extend(item.replace("{timeframe}", timeframe) for timeframe in TIMEFRAMES)
        else:
            expanded.append(item)
    return expanded


def exact_source_key_status(raw_key: str, symbol: str | None) -> dict[str, Any]:
    generic = bool(GENERIC_SOURCE_RE.search(raw_key))
    expanded: list[str] = []
    missing: list[str] = []
    if not generic:
        if "{symbol}" in raw_key:
            symbols = [symbol] if symbol else list(SYMBOLS)
            for sym in symbols:
                expanded.extend(expand_source_key(raw_key, sym))
        else:
            expanded.append(raw_key)
        for key in expanded:
            if not redis_exists(key):
                missing.append(key)
    return {
        "source_key": raw_key,
        "generic": generic,
        "expanded_keys": expanded,
        "missing_runtime_keys": missing,
        "runtime_present": bool(expanded) and not missing,
    }


def policy_architecture_drift(text: str) -> bool:
    if POLICY_IMPL_RE.search(text):
        return True
    for line in text.splitlines():
        lower = line.lower()
        if (
            "do not" in lower
            or "never" in lower
            or "must_not" in lower
            or "not start" in lower
            or "no policy architecture" in lower
        ):
            continue
        if POLICY_NATURAL_RE.search(line):
            return True
    return False


def queue_guard() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    queue_go = read_text(QUEUE_GO_NO_GO)
    queue = read_json(QUEUE_JSON)
    next_tasks = read_json(NEXT_TASKS_JSON)
    public_queue = read_json(QUEUE_PUBLIC_JSON)

    queue_doc_go = queue.get("go_no_go") if isinstance(queue, dict) else None
    strict_contract = queue.get("strict_source_contract_pass") is True
    aggregate_check_pass = queue.get("aggregate_total_check") == "PASS"
    generic_hint_count = int(queue.get("generic_source_hint_hits") or 0) if queue else 0
    broad_bucket_emitted = queue.get("portfolio_state_broad_bucket_emitted") is True
    queue_remediated_ready = (
        queue_doc_go == QUEUE_REMEDIATED_READY
        and strict_contract
        and aggregate_check_pass
        and generic_hint_count == 0
        and not broad_bucket_emitted
    )
    if not queue_remediated_ready:
        blockers.append("REMAINING_DIM_QUEUE_REMEDIATION_NOT_READY")
    if not queue:
        blockers.append("REMAINING_DIM_QUEUE_ARTIFACT_MISSING")
    if not next_tasks:
        blockers.append("NEXT_10_FEATURE_TASKS_ARTIFACT_MISSING")

    category_counts = queue.get("aggregate_category_counts") if isinstance(queue, dict) else {}
    per_symbol = queue.get("per_symbol") if isinstance(queue, dict) else []
    sourced_today = sum(
        int(row.get("generated_full_observation_dim") or 0)
        for row in per_symbol
        if isinstance(row, dict)
    )
    missing_classified = sum(int(v or 0) for v in (category_counts or {}).values())
    aggregate_target = int(queue.get("aggregate_target_dim") or 0)
    aggregate_reconciles = bool(aggregate_target) and sourced_today + missing_classified == aggregate_target
    if queue and not aggregate_reconciles:
        blockers.append("QUEUE_AGGREGATE_MATH_DOES_NOT_RECONCILE")

    buildable_groups = ((queue.get("field_groups_by_category") or {}).get("V2_BUILDABLE_NOW") or {})
    field_metadata_by_group = queue.get("field_metadata_by_group") or {}
    broad_buildable_groups: list[str] = []
    buildable_groups_missing_metadata: list[str] = []
    buildable_groups_missing_exact_source: list[str] = []
    if isinstance(buildable_groups, dict):
        broad_buildable_groups = [
            f"{name}:{count}"
            for name, count in buildable_groups.items()
            if BROAD_BUILDABLE_GROUP_RE.search(str(name)) or int(count or 0) > 100
        ]
        if isinstance(field_metadata_by_group, dict):
            for name in buildable_groups:
                metadata = field_metadata_by_group.get(name)
                if not isinstance(metadata, dict):
                    buildable_groups_missing_metadata.append(str(name))
                    continue
                if not metadata.get("exact_v2_source_keys"):
                    buildable_groups_missing_exact_source.append(str(name))
        else:
            buildable_groups_missing_metadata = [str(name) for name in buildable_groups]
    if broad_buildable_groups:
        blockers.append("V2_BUILDABLE_NOW_CONTAINS_BROAD_RESERVED_BUCKET")
    if buildable_groups_missing_metadata:
        blockers.append("V2_BUILDABLE_NOW_FIELD_METADATA_MISSING")
    if buildable_groups_missing_exact_source:
        blockers.append("V2_BUILDABLE_NOW_EXACT_SOURCE_METADATA_MISSING")

    task_rows = next_tasks.get("tasks") if isinstance(next_tasks, dict) else []
    buildable_task_checks: list[dict[str, Any]] = []
    top_valid_task_id: str | None = None
    valid_task_field_groups: list[str] = []
    for index, task in enumerate(task_rows if isinstance(task_rows, list) else [], start=1):
        if not isinstance(task, dict):
            continue
        if task.get("category") != "V2_BUILDABLE_NOW":
            continue
        field_group = str(task.get("task_field_group") or task.get("field_group") or task.get("field_id") or "")
        source_keys = task.get("v2_source_keys_to_consume") or task.get("exact_source_keys") or []
        if not isinstance(source_keys, list):
            source_keys = []
        task_symbol = task.get("symbol") if isinstance(task.get("symbol"), str) else None
        source_statuses = [exact_source_key_status(str(key), task_symbol) for key in source_keys]
        has_generic_source = any(item["generic"] for item in source_statuses)
        missing_runtime_keys = [
            key
            for item in source_statuses
            for key in item.get("missing_runtime_keys", [])
        ]
        missing_concrete_payload_path = not source_keys or any(
            not status["generic"] and not status["expanded_keys"] for status in source_statuses
        )
        broad = bool(BROAD_BUILDABLE_GROUP_RE.search(field_group)) or int(task.get("aggregate_dim_gap") or 0) > 100
        has_field_id = bool(task.get("field_id") or (field_group and "." in field_group))
        valid = (
            not broad
            and has_field_id
            and not has_generic_source
            and not missing_runtime_keys
            and not missing_concrete_payload_path
            and not task.get("blocked_on_external_source")
            and not task.get("blocked_on_operator_decision")
            and not task.get("blocked_on_policy_architecture")
            and not task.get("blocked_on_checkpoint_artifact")
        )
        if valid and top_valid_task_id is None:
            top_valid_task_id = task.get("task_id") or field_group or f"task_{index}"
        if valid and field_group:
            valid_task_field_groups.append(field_group)
        buildable_task_checks.append(
            {
                "rank": index,
                "task_id": task.get("task_id"),
                "field_group": field_group,
                "aggregate_dim_gap": task.get("aggregate_dim_gap"),
                "has_field_id": has_field_id,
                "broad_reserved_bucket": broad,
                "has_generic_source_hint": has_generic_source,
                "missing_runtime_keys": missing_runtime_keys[:20],
                "missing_concrete_payload_path": missing_concrete_payload_path,
                "valid_exact_source_task": valid,
                "source_statuses": source_statuses,
            }
        )
        if broad:
            blockers.append(f"BROAD_BUILDABLE_TASK_{index}_{field_group or 'UNKNOWN'}")
        if not has_field_id:
            blockers.append(f"BUILDABLE_TASK_{index}_MISSING_FIELD_ID")
        if has_generic_source:
            blockers.append(f"BUILDABLE_TASK_{index}_GENERIC_SOURCE_HINT")
        if missing_runtime_keys:
            blockers.append(f"BUILDABLE_TASK_{index}_SOURCE_KEY_ABSENT")
        if missing_concrete_payload_path:
            blockers.append(f"BUILDABLE_TASK_{index}_NO_CONCRETE_PAYLOAD_PATH")

    if public_queue and queue:
        public_counts = public_queue.get("aggregate_category_counts")
        if public_counts != category_counts:
            blockers.append("QUEUE_PUBLIC_MIRROR_CATEGORY_COUNTS_MISMATCH")
    elif queue:
        blockers.append("QUEUE_PUBLIC_MIRROR_MISSING")

    return (
        {
            "queue_codex_marker": queue_go,
            "queue_go_no_go": queue_doc_go,
            "queue_remediated_ready": queue_remediated_ready,
            "strict_source_contract_pass": strict_contract,
            "generic_source_hint_hits": generic_hint_count,
            "portfolio_state_broad_bucket_emitted": broad_bucket_emitted,
            "queue_exists": bool(queue),
            "next_tasks_exists": bool(next_tasks),
            "public_mirror_exists": bool(public_queue),
            "sourced_today": sourced_today,
            "missing_classified": missing_classified,
            "aggregate_target": aggregate_target,
            "aggregate_reconciles": aggregate_reconciles,
            "aggregate_category_counts": category_counts or {},
            "broad_buildable_groups": broad_buildable_groups,
            "buildable_groups_missing_metadata": buildable_groups_missing_metadata,
            "buildable_groups_missing_exact_source": buildable_groups_missing_exact_source,
            "field_metadata_by_group_count": (
                len(field_metadata_by_group) if isinstance(field_metadata_by_group, dict) else 0
            ),
            "buildable_task_checks": buildable_task_checks[:25],
            "top_valid_task_id": top_valid_task_id,
            "valid_task_field_groups": valid_task_field_groups[:50],
        },
        sorted(set(blockers)),
    )


def controller_guard(queue_state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    marker = read_text(CONTROLLER_GO_NO_GO)
    status = read_json(CONTROLLER_STATUS)
    if marker != CONTROLLER_READY:
        blockers.append("AUTONOMOUS_BURNDOWN_CONTROLLER_READY_MARKER_MISSING")
    if not status:
        blockers.append("AUTONOMOUS_BURNDOWN_CONTROLLER_STATUS_MISSING")

    selected_task_id = status.get("selected_task_id") if status else None
    active_task = status.get("active_task") if status else None
    duplicates = int(status.get("duplicate_suppression_count") or 0) if status else 0
    skipped = status.get("skipped_tasks_with_reasons") if status else []
    skipped_groups: set[str] = set()
    if isinstance(skipped, list):
        for item in skipped:
            if isinstance(item, dict) and item.get("task_field_group"):
                skipped_groups.add(str(item["task_field_group"]))
    valid_groups = queue_state.get("valid_task_field_groups") or []
    expected_field_group = None
    suppressed_groups: dict[str, str] = {}
    if isinstance(valid_groups, list):
        for group in valid_groups:
            group_str = str(group)
            if group_str in skipped_groups:
                suppressed_groups[group_str] = "controller skipped duplicate"
                continue
            completed_marker = completed_codex_marker_for_group(group_str)
            if completed_marker:
                suppressed_groups[group_str] = f"completed Codex marker: {completed_marker}"
                continue
            inflight_descriptor = inflight_descriptor_for_group(group_str)
            if inflight_descriptor:
                suppressed_groups[group_str] = f"in-flight descriptor: {inflight_descriptor}"
                continue
            if expected_field_group is None:
                expected_field_group = group_str
                break

    selected_field_group = status.get("selected_field_group") if status else None
    if status and expected_field_group and selected_field_group and selected_field_group != expected_field_group:
        blockers.append("CLAUDE_SELECTED_NON_TOP_BUILDABLE_TASK")
    if status and not expected_field_group and selected_task_id:
        blockers.append("CLAUDE_SELECTED_TASK_WHILE_QUEUE_HAS_NO_VALID_EXACT_TASK")
    if status and duplicates < 0:
        blockers.append("DUPLICATE_SUPPRESSION_COUNT_INVALID")

    return (
        {
            "controller_marker": marker,
            "controller_status_exists": bool(status),
            "selected_task_id": selected_task_id,
            "selected_field_group": selected_field_group,
            "active_task": active_task,
            "duplicate_suppression_count": duplicates,
            "skipped_tasks_with_reasons": skipped[:20] if isinstance(skipped, list) else skipped,
            "top_valid_task_id": queue_state.get("top_valid_task_id"),
            "valid_task_field_groups": valid_groups[:50] if isinstance(valid_groups, list) else valid_groups,
            "skipped_duplicate_field_groups": sorted(skipped_groups),
            "suppressed_field_groups": suppressed_groups,
            "expected_selected_field_group": expected_field_group,
        },
        blockers,
    )


def relevant_task_files() -> list[Path]:
    if not TASKS_DIR.exists():
        return []
    patterns = [
        "*autonomous*production*equivalence*.json",
        "*full_observation*.json",
        "claude_fix_v2_full_observation_*.json",
        "codex_review_v2_full_observation_*.json",
    ]
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(path for path in TASKS_DIR.glob(pattern) if path.is_file())
    return sorted(paths)


def task_hygiene_guard() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    files = relevant_task_files()
    broad_audit_hits: list[str] = []
    policy_hits: list[str] = []
    checkpoint_hits: list[str] = []
    approval_hits: list[str] = []
    exchange_hits: list[str] = []
    duplicates: dict[str, int] = {}

    for path in files:
        text = read_text(path)
        if BROAD_AUDIT_RE.search(text):
            broad_audit_hits.append(path_label(path))
        if policy_architecture_drift(text):
            policy_hits.append(path_label(path))
        if CHECKPOINT_CLAIM_RE.search(text):
            checkpoint_hits.append(path_label(path))
        if APPROVAL_TRUE_RE.search(text):
            approval_hits.append(path_label(path))
        if EXCHANGE_MUTATION_RE.search(text):
            exchange_hits.append(path_label(path))
        try:
            payload = json.loads(text)
        except Exception:
            payload = {}
        key = ""
        if isinstance(payload, dict):
            key = str(payload.get("task_id") or payload.get("field_group") or payload.get("selected_task_id") or "")
        key = key or path.stem
        duplicates[key] = duplicates.get(key, 0) + 1

    duplicate_groups = {key: count for key, count in duplicates.items() if count > 1}
    if broad_audit_hits:
        blockers.append("BROAD_AUDIT_TASK_PRESENT")
    if policy_hits:
        blockers.append("POLICY_ARCHITECTURE_TASK_PRESENT_BEFORE_GATE")
    if checkpoint_hits:
        blockers.append("CHECKPOINT_COMPATIBILITY_CLAIM_PRESENT")
    if approval_hits:
        blockers.append("LIVE_OR_SHUTDOWN_APPROVAL_PRESENT")
    if exchange_hits:
        blockers.append("EXCHANGE_MUTATION_TASK_PRESENT")
    if duplicate_groups:
        blockers.append("DUPLICATE_AUTONOMOUS_TASKS_PRESENT")

    return (
        {
            "reviewed_task_files": [path_label(path) for path in files],
            "broad_audit_hits": broad_audit_hits,
            "policy_architecture_hits": policy_hits,
            "checkpoint_claim_hits": checkpoint_hits,
            "approval_hits": approval_hits,
            "exchange_mutation_hits": exchange_hits,
            "duplicate_task_groups": duplicate_groups,
        },
        blockers,
    )


def safety_guard() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    reviewed_paths = [
        QUEUE_JSON,
        NEXT_TASKS_JSON,
        CONTROLLER_STATUS,
        FULL_OBSERVATION_STATUS,
        SOAK_STATUS,
        CONTINUOUS_CODEX_STATUS,
    ]
    approval_hits: list[str] = []
    exchange_hits: list[str] = []
    old_redis_write_hits: list[str] = []
    checkpoint_claim_hits: list[str] = []
    policy_hits: list[str] = []

    for path in reviewed_paths:
        if not path.exists():
            continue
        text = read_text(path)
        if APPROVAL_TRUE_RE.search(text):
            approval_hits.append(path_label(path))
        if EXCHANGE_MUTATION_RE.search(text):
            exchange_hits.append(path_label(path))
        if CHECKPOINT_CLAIM_RE.search(text):
            checkpoint_claim_hits.append(path_label(path))
        if policy_architecture_drift(text):
            policy_hits.append(path_label(path))
        if path.suffix == ".py" and OLD_REDIS_WRITE_RE.search(text):
            old_redis_write_hits.append(path_label(path))

    statuses = [read_json(path) for path in (SOAK_STATUS, FULL_OBSERVATION_STATUS, CONTROLLER_STATUS)]
    live_gate_values = [
        status.get("live_gate")
        for status in statuses
        if isinstance(status, dict) and status.get("live_gate") is not None
    ]
    live_symbols_values = [
        status.get("live_symbols")
        for status in statuses
        if isinstance(status, dict) and status.get("live_symbols") is not None
    ]

    if any(value != LIVE_GATE for value in live_gate_values):
        blockers.append("LIVE_GATE_DRIFT")
    if any(value != [] for value in live_symbols_values):
        blockers.append("LIVE_SYMBOLS_DRIFT")
    if approval_hits:
        blockers.append("LIVE_CANARY_SHUTDOWN_APPROVAL_DRIFT")
    if exchange_hits:
        blockers.append("EXCHANGE_MUTATION_DRIFT")
    if old_redis_write_hits:
        blockers.append("OLD_REDIS_WRITE_DRIFT")
    if checkpoint_claim_hits:
        blockers.append("CHECKPOINT_COMPATIBILITY_CLAIM_DRIFT")
    if policy_hits:
        blockers.append("POLICY_ARCHITECTURE_DRIFT")

    return (
        {
            "reviewed_paths": [path_label(path) for path in reviewed_paths if path.exists()],
            "live_gate_values": live_gate_values,
            "live_symbols_values": live_symbols_values,
            "approval_hits": approval_hits,
            "exchange_mutation_hits": exchange_hits,
            "old_redis_write_hits": old_redis_write_hits,
            "checkpoint_claim_hits": checkpoint_claim_hits,
            "policy_architecture_hits": policy_hits,
        },
        blockers,
    )


def build_markdown(status: dict[str, Any]) -> str:
    runtime = status["runtime_health"]
    queue = status["queue_guard"]
    controller = status["controller_guard"]
    safety = status["safety"]
    blockers = status["fail_blockers"]
    lines = [
        "# Codex Status: Autonomous Production-Equivalence Review Governor",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
    ]
    if blockers:
        lines.extend(
            [
                "Codex autonomous production-equivalence review is blocked for the current cycle.",
                "The governor is active, but the remediated exact-source execution queue and Claude controller are not yet ready.",
            ]
        )
    else:
        lines.append("Codex autonomous production-equivalence review governor is ready.")
    lines.extend(
        [
            "",
            "This status does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.",
            "",
            "## Runtime",
            "",
            f"- 6h soak ready: `{runtime.get('soak_6h_ready')}`",
            f"- continuous remediation governor: `{runtime.get('continuous_go_no_go')}`",
            f"- V2 Redis key count sample: `{runtime.get('v2_redis_key_count_sample')}`",
            f"- full observation state: `{runtime.get('full_observation_state')}`",
            f"- liquidation heartbeat fresh: `{(runtime.get('liquidation_heartbeat') or {}).get('fresh')}`",
            f"- position-history heartbeat fresh: `{(runtime.get('position_history_heartbeat') or {}).get('fresh')}`",
            f"- live_gate values: `{runtime.get('live_gate_values')}`",
            f"- live_symbols values: `{runtime.get('live_symbols_values')}`",
            "",
            "## Queue Guard",
            "",
            f"- queue implementation marker: `{queue.get('queue_go_no_go')}`",
            f"- queue remediated ready: `{queue.get('queue_remediated_ready')}`",
            f"- prior standalone queue Codex marker: `{queue.get('queue_codex_marker')}`",
            f"- strict source contract: `{queue.get('strict_source_contract_pass')}`",
            f"- aggregate reconciles: `{queue.get('aggregate_reconciles')}`",
            f"- sourced today: `{queue.get('sourced_today')}`",
            f"- missing classified: `{queue.get('missing_classified')}`",
            f"- aggregate target: `{queue.get('aggregate_target')}`",
            f"- top valid exact-source task: `{queue.get('top_valid_task_id')}`",
            f"- broad buildable groups: `{queue.get('broad_buildable_groups')}`",
            "",
            "## Controller Guard",
            "",
            f"- controller marker: `{controller.get('controller_marker')}`",
            f"- controller status exists: `{controller.get('controller_status_exists')}`",
            f"- selected task: `{controller.get('selected_task_id')}`",
            f"- active task: `{controller.get('active_task')}`",
            "",
            "## Safety",
            "",
            f"- live_gate values: `{safety.get('live_gate_values')}`",
            f"- live_symbols values: `{safety.get('live_symbols_values')}`",
            f"- approval hits: `{safety.get('approval_hits')}`",
            f"- exchange mutation hits: `{safety.get('exchange_mutation_hits')}`",
            f"- checkpoint claim hits: `{safety.get('checkpoint_claim_hits')}`",
            f"- policy architecture hits: `{safety.get('policy_architecture_hits')}`",
            "",
            "## Fail Blockers",
            "",
        ]
    )
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Next Action",
            "",
            status.get("next_action", ""),
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_once() -> dict[str, Any]:
    runtime, runtime_blockers = runtime_guard()
    queue, queue_blockers = queue_guard()
    controller, controller_blockers = controller_guard(queue)
    task_hygiene, task_blockers = task_hygiene_guard()
    safety, safety_blockers = safety_guard()

    fail_blockers = sorted(
        set(runtime_blockers + queue_blockers + controller_blockers + task_blockers + safety_blockers)
    )
    go_no_go = GO_BLOCKED if fail_blockers else GO_READY
    if "REMAINING_DIM_QUEUE_REMEDIATION_NOT_READY" in fail_blockers:
        next_action = (
            "Remediate the remaining-dim execution queue first: split broad buildable buckets into "
            "exact field specs with exact source keys, rerun the queue Codex review, then start the "
            "Claude autonomous controller."
        )
    elif "AUTONOMOUS_BURNDOWN_CONTROLLER_READY_MARKER_MISSING" in fail_blockers:
        next_action = (
            "Create or refresh the Claude autonomous burndown controller after the exact-source queue passes."
        )
    elif fail_blockers:
        next_action = "Resolve the listed fail blockers before allowing autonomous implementation to continue."
    else:
        next_action = "Codex governor can review the selected exact-source task and continue the cycle."

    status = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "go_no_go": go_no_go,
        "fail_blockers": fail_blockers,
        "runtime_health": runtime,
        "queue_guard": queue,
        "controller_guard": controller,
        "task_hygiene": task_hygiene,
        "safety": safety,
        "next_action": next_action,
    }

    write_json(OUT / "codex_autonomous_governor_status.json", status)
    write_text(OUT / "CODEX_STATUS.md", build_markdown(status))
    write_text(OUT / "CODEX_GO_NO_GO.md", go_no_go + "\n")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one governor cycle")
    parser.add_argument("--status", action="store_true", help="print current generated status")
    parser.add_argument("--loop", action="store_true", help="run governor cycles continuously")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()

    if args.status and not args.once and not args.loop:
        print(json.dumps(read_json(OUT / "codex_autonomous_governor_status.json"), indent=2, sort_keys=True))
        return 0

    if args.loop:
        while True:
            status = evaluate_once()
            print(f"{status['generated_utc']} {status['go_no_go']} blockers={len(status['fail_blockers'])}")
            time.sleep(max(30, args.interval_seconds))

    status = evaluate_once()
    print(f"{status['go_no_go']} blockers={len(status['fail_blockers'])}")
    for blocker in status["fail_blockers"]:
        print(f"- {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
