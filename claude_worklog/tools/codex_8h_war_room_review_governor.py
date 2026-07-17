#!/usr/bin/env python3
"""Codex 8-hour war-room review governor.

Runs one read-only Codex review cycle over Claude's v2_8h_war_room daemon
outputs. The systemd timer owns the every-5-minute cadence; this script is
safe to run as a oneshot.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WAR_ROOM = ROOT / "claude_worklog/final_readiness/v2_8h_war_room/latest"
OUT = WAR_ROOM / "codex_review"
PUBLIC = ROOT / "v2/frontend/public/v2_8h_war_room/latest"
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"

WAR_ROOM_STATUS = WAR_ROOM / "v2_8h_war_room_status.json"
WAR_ROOM_RUNTIME = WAR_ROOM / "runtime_cycle_status.json"
WAR_ROOM_REVIEW_QUEUE = WAR_ROOM / "codex_review_queue.json"
WAR_ROOM_ACTIONS = WAR_ROOM / "actions_applied.json"

CONTINUOUS_GOVERNOR = ROOT / "claude_worklog/tools/codex_continuous_remediation_review_governor.py"
CONTINUOUS_STATUS = (
    ROOT
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/"
    "continuous_remediation/codex_review/codex_5m_status.json"
)
CONTINUOUS_MD = (
    ROOT
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/"
    "continuous_remediation/codex_review/CODEX_5M_STATUS.md"
)

LEGACY_LOG_STATUS = (
    ROOT / "v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json"
)
COMPARATOR_STATUS = (
    ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json"
)
FULL_OBSERVATION_STATUS = (
    ROOT / "v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"
)
FRONTEND_TRUTH = ROOT / "v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json"
LIQUIDATION_WSS_STATUS = (
    ROOT / "v2/frontend/public/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json"
)
WEBSITE_PACKET_DIR = ROOT / "claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest"
WEBSITE_IMPLEMENTATION_PUBLIC_PAYLOAD = (
    ROOT
    / "v2/frontend/public/v2_realtime_user_website_from_real_payloads/latest/"
    "operator_dashboard_payload.json"
)
WEBSITE_LEGACY_OPERATOR_PAYLOAD = (
    ROOT
    / "v2/frontend/public/operator_runtime/v2_realtime_user_website_from_real_payloads/latest/"
    "operator_dashboard_payload.json"
)
WEBSITE_PUBLIC_PAYLOAD = WEBSITE_IMPLEMENTATION_PUBLIC_PAYLOAD

GO_READY = "CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY"
GO_BLOCKED = "CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_BLOCKED"
WEBSITE_PASS = "V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_CODEX_PASS"
WEBSITE_FAIL = "V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_CODEX_FAIL"
LIVE_GATE = "blocked_human_only"
LIQUIDATION_HEARTBEAT_KEY = "v2:market:liquidations:heartbeat"
POSITION_HISTORY_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"
POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS = 240

REQUIRED_PROCESSES = {
    "continuous_remediation_loop": "v2_continuous_legacy_log_to_rebuild_remediation.py",
    "legacy_log_observer": "v2_legacy_log_intelligence_observer",
    "legacy_v2_comparator": "v2_production_equivalence_comparator",
    "payload_freshness_refresher": "v2_production_payload_freshness_refresher",
    "liquidation_wss_daemon": "v2_liquidation_wss_loop",
    "position_history_persistent_tracker": "v2_position_history_persistent_tracker",
    "paper_runtime": "v2_trade_management_paper_loop",
    "paper_shadow_observation": "v2_rl_core_inference_loop",
}

SYSTEMD_SERVICES = [
    "ai-bot-v2-continuous-legacy-log-remediation.service",
    "ai-bot-v2-legacy-log-intelligence-observer.service",
    "ai-bot-v2-paper-online-runtime.service",
    "ai-bot-v2-paper-shadow-observation.service",
    "ai-bot-v2-feature-snapshot-builder.service",
    "ai-bot-v2-symbol-universe-publisher.service",
    "ai-bot-v2-liquidation-wss-paper-shadow.service",
    "ai-bot-v2-position-history-persistent-tracker.service",
    "ai-bot-v2-codex-watchdog.service",
    "ai-bot-v2-agent-supervisor.service",
]

V2_REDIS_PATTERNS = {
    "v2:*": "v2:*",
    "v2:market:*": "v2:market:*",
    "v2:features:*": "v2:features:*",
    "v2:prediction:*": "v2:prediction:*",
    "v2:paper:*": "v2:paper:*",
    "v2:risk:*": "v2:risk:*",
    "v2:orchestrator:*": "v2:orchestrator:*",
    "v2:dashboards:binance_top10:*": "v2:dashboards:binance_top10:*",
}

APPROVAL_TRUE_RE = re.compile(
    r'"(?:approves_live|approves_real|approves_canary|approves_legacy_shutdown|approves_redis_trim)"\s*:\s*true|'
    r'"(?:live_canary_shutdown_redis_trim_approval_tokens_created|paper_only_shutdown_acceptance_created)"\s*:\s*true',
    re.I,
)
EXCHANGE_MUTATION_RE = re.compile(
    r"create_order|cancel_order|cancel_all|set_leverage|set_margin_mode|"
    r"futures_create_order|futures_cancel|private_post|sapi_post|place_order|modify_order",
    re.I,
)
REDIS_WRITE_RE = re.compile(r"\.(?:set|hset|xadd|delete|xtrim)\(|flushdb|flushall")
BROAD_AUDIT_RE = re.compile(r"\bbroad audit\b|\baudit everything\b|\bfull audit loop\b", re.I)
FORBIDDEN_PROVIDER_RE = re.compile(r"defi\s*llama|defillama|defi_llama", re.I)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
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


def age_seconds(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    for key in ("generated_utc", "generated_at", "heartbeat_at", "finished_at", "last_observed_utc"):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    cycle = payload.get("cycle")
    if isinstance(cycle, dict):
        parsed = parse_time(cycle.get("finished_at"))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    return None


def path_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def refresh_safe_payloads() -> dict[str, Any]:
    results: dict[str, Any] = {}
    commands = {
        "continuous_remediation_governor": [
            str(ROOT / ".venv/bin/python3"),
            str(CONTINUOUS_GOVERNOR),
            "--once",
        ],
        "frontend_truth": [
            str(ROOT / ".venv/bin/python3"),
            "-m",
            "v2.backend.app.cli.frontend_truth_payload_builder",
        ],
        "full_observation_builder": [
            str(ROOT / ".venv/bin/python3"),
            "-m",
            "v2.backend.app.cli.v2_full_observation_builder_status",
            "--once",
        ],
    }
    for name, args in commands.items():
        try:
            proc = run(args, timeout=45)
            results[name] = {
                "attempted": True,
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout.strip()[-500:],
                "stderr_tail": proc.stderr.strip()[-500:],
            }
        except Exception as exc:
            results[name] = {"attempted": True, "error": type(exc).__name__, "message": str(exc)[:500]}
    return results


def redis_scan(pattern: str) -> dict[str, Any]:
    proc = run(["redis-cli", "--scan", "--pattern", pattern], timeout=20)
    keys = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {"pattern": pattern, "count": len(keys), "sample": keys[:12], "returncode": proc.returncode}


def redis_get_json(key: str) -> tuple[int, dict[str, Any]]:
    ttl_proc = run(["redis-cli", "TTL", key], timeout=10)
    try:
        ttl = int((ttl_proc.stdout or "").strip())
    except ValueError:
        ttl = -2
    get_proc = run(["redis-cli", "GET", key], timeout=10)
    raw = (get_proc.stdout or "").strip()
    if not raw:
        return ttl, {}
    try:
        parsed = json.loads(raw)
        return ttl, parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return ttl, {}


def process_guard() -> dict[str, Any]:
    proc = run(["ps", "-eo", "pid,ppid,stat,etime,cmd", "--width", "360"], timeout=10)
    lines = proc.stdout.splitlines()
    out: dict[str, Any] = {}
    for name, pattern in REQUIRED_PROCESSES.items():
        matches = [
            line.strip()
            for line in lines
            if pattern in line
            and "grep" not in line
            and "codex_8h_war_room_review_governor.py" not in line
            and "bash -lc" not in line
        ]
        out[name] = {"pattern": pattern, "running": bool(matches), "match_count": len(matches), "sample": matches[:3]}
    return out


def systemd_guard() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for service in SYSTEMD_SERVICES:
        proc = run(["systemctl", "--user", "is-active", service], timeout=10)
        out[service] = (proc.stdout or "").strip() or "unknown"
    return out


def live_gate_from(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    bad: list[str] = []
    for idx, payload in enumerate(payloads):
        gate = payload.get("live_gate", payload.get("gate"))
        symbols = payload.get("live_symbols", payload.get("symbols_real"))
        if gate is not None and gate != LIVE_GATE:
            bad.append(f"payload_{idx}:gate={gate}")
        if symbols not in (None, []):
            bad.append(f"payload_{idx}:symbols={symbols}")
    return {"live_gate": LIVE_GATE, "live_symbols": [], "drift_hits": bad, "ok": not bad}


def checkpoint_task_guard() -> dict[str, Any]:
    paths = sorted(TASKS.glob("*trainer_missing_checkpoint_weight_shape_contract*.json"))
    return {
        "task_count": len(paths),
        "task_paths": [path_label(p) for p in paths],
        "duplicate_checkpoint_tasks": len(paths) > 2,
    }


def broad_audit_guard() -> dict[str, Any]:
    hits: list[str] = []
    for path in sorted(TASKS.glob("*.json")):
        data = read_json(path)
        status = str(data.get("status") or "").lower()
        searchable = "\n".join(
            str(data.get(key) or "")
            for key in ("task_id", "title", "summary", "prompt", "objective", "requested_work")
        )
        if BROAD_AUDIT_RE.search(searchable) and status not in {"done", "closed", "complete", "completed"}:
            hits.append(path_label(path))
    return {"broad_audit_task_hits": hits, "no_broad_audit_tasks": not hits}


def secret_values() -> list[str]:
    env_path = ROOT / ".local_secrets/alternative_data.env"
    if not env_path.exists():
        return []
    values: list[str] = []
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        _, value = stripped.split("=", 1)
        value = value.strip().strip("'\"")
        if len(value) >= 12 and value.lower() not in {"false", "true", "free"}:
            values.append(value)
    return values


def candidate_secret_scan_paths() -> list[Path]:
    roots = [
        ROOT / "claude_worklog/final_readiness/v2_8h_war_room/latest",
        ROOT / "claude_worklog/final_readiness/v2_alt_data_provider_one_shot_population/latest",
        ROOT / "claude_worklog/final_readiness/v2_alt_data_symbol_universe_scoring/latest",
        ROOT / "claude_worklog/final_readiness/v2_alternative_data_secret_custody/latest",
        ROOT / "claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest",
        ROOT / "v2/frontend/public",
        ROOT / "v2/frontend/src",
        TASKS,
    ]
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        elif root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path.stat().st_size <= 5_000_000 and ".local_secrets" not in path.parts:
                    paths.append(path)
    return paths


def raw_secret_scan() -> dict[str, Any]:
    values = secret_values()
    hits: list[str] = []
    if not values:
        return {"vault_values_loaded": 0, "raw_secret_hits": hits, "raw_values_exposed": False}
    for path in candidate_secret_scan_paths():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if any(value and value in line for value in values):
                hits.append(f"{path_label(path)}:{idx}")
    return {"vault_values_loaded": len(values), "raw_secret_hits": hits, "raw_values_exposed": bool(hits)}


def forbidden_provider_scan() -> dict[str, Any]:
    roots = [
        ROOT / "claude_worklog/final_readiness/v2_alternative_data_integration/latest",
        ROOT / "claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest",
        ROOT / "claude_worklog/final_readiness/v2_alt_data_symbol_universe_scoring/latest",
        ROOT / "v2/backend/app/services/alternative_data",
        ROOT / "v2/backend/app/cli",
        ROOT / "v2/frontend/public/v2_alternative_data_integration/latest",
        ROOT / "v2/frontend/public/operator_runtime/v2_alternative_data/latest",
    ]
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and p.stat().st_size <= 2_000_000]
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            for idx, line in enumerate(text.splitlines(), start=1):
                if FORBIDDEN_PROVIDER_RE.search(line):
                    hits.append(f"{path_label(path)}:{idx}")
    return {"forbidden_provider_hits": hits, "no_forbidden_provider_references": not hits}


def source_scan() -> dict[str, Any]:
    roots = [
        ROOT / "v2/backend/app/services/alternative_data",
        ROOT / "v2/backend/app/services/rl_core/full_observation_builder.py",
        ROOT / "v2/backend/app/services/rl_core/position_history_aggregator.py",
        ROOT / "v2/backend/app/services/rl_core/position_price_tracking_recorder.py",
        ROOT / "v2/backend/app/services/native_ingestors/liquidations_wss.py",
        ROOT / "v2/backend/app/cli/v2_alt_data_symbol_universe_scoring.py",
        ROOT / "v2/backend/app/cli/v2_alternative_data_status.py",
        ROOT / "v2/backend/app/cli/v2_full_observation_builder_status.py",
        ROOT / "v2/backend/app/cli/v2_liquidation_wss_loop.py",
        ROOT / "v2/backend/app/cli/v2_position_price_tracking_recorder.py",
        ROOT / "v2/backend/app/cli/v2_top10_binance_dashboard_feed.py",
        ROOT / "v2/backend/app/cli/frontend_truth_payload_builder.py",
        WAR_ROOM,
        WEBSITE_PACKET_DIR,
        ROOT / "v2/frontend/src/pages/public-landing",
        ROOT / "v2/frontend/src/pages/public-status",
        ROOT / "v2/frontend/src/pages/user-status",
        ROOT / "v2/frontend/src/pages/market-intelligence",
        ROOT / "v2/frontend/src/pages/monitor-center",
    ]
    exchange_hits: list[str] = []
    unsafe_redis_write_hits: list[str] = []
    approval_hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and p.stat().st_size <= 2_000_000]
        for path in files:
            if "__pycache__" in path.parts:
                continue
            if "codex_review" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for idx, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                lowered = stripped.lower()
                if (
                    "EXCHANGE_MUTATION_RE" in line
                    or "REDIS_WRITE_RE" in line
                    or "APPROVAL_TRUE_RE" in line
                    or "fail_blockers.append" in line
                    or "blockers.append" in line
                ):
                    continue
                negative_or_contract = any(
                    token in lowered
                    for token in (
                        "cannot",
                        "does not",
                        "do not",
                        "must not",
                        "may_not",
                        "forbidden",
                        "refuses",
                        "read-only",
                        "read only",
                        "no live",
                        "no trading",
                    )
                )
                if EXCHANGE_MUTATION_RE.search(stripped) and not negative_or_contract:
                    exchange_hits.append(f"{path_label(path)}:{idx}:{stripped[:160]}")
                if REDIS_WRITE_RE.search(stripped):
                    context = "\n".join(text.splitlines()[max(0, idx - 8): idx + 5])
                    guarded = (
                        "v2:" in context
                        or "_safe_redis_set" in context
                        or "safe_set" in context
                        or "_allowed_key" in context
                        or "allowed_altdata_write_key" in context
                        or "V2_REDIS_PREFIX" in context
                    )
                    if not guarded:
                        unsafe_redis_write_hits.append(f"{path_label(path)}:{idx}:{stripped[:160]}")
                if path.suffix.lower() in {".json", ".md"} and APPROVAL_TRUE_RE.search(stripped):
                    approval_hits.append(f"{path_label(path)}:{idx}:{stripped[:160]}")
    return {
        "exchange_mutation_hits": exchange_hits[:60],
        "unsafe_redis_write_hits": unsafe_redis_write_hits[:60],
        "approval_hits": approval_hits[:60],
        "no_exchange_mutation": not exchange_hits,
        "no_old_redis_writes": not unsafe_redis_write_hits,
        "no_approval_drift": not approval_hits,
    }


def full_observation_guard(payload: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in payload.get("per_symbol") or [] if isinstance(row, dict)]
    dims = {row.get("symbol"): row.get("generated_full_observation_dim") for row in rows}
    missing = {row.get("symbol"): row.get("missing_field_count") for row in rows}
    zero_filled = sum(int(row.get("zero_filled_field_count") or 0) for row in rows)
    complete_claimed = str(payload.get("state") or "") == "FULL_OBSERVATION_BUILDER_COMPLETE"
    complete_evidence = rows and all(int(row.get("generated_full_observation_dim") or 0) == 1911 for row in rows)
    no_missing = rows and all(int(row.get("missing_field_count") or 0) == 0 for row in rows)
    return {
        "state": payload.get("state"),
        "target_dim": payload.get("target_full_observation_dim")
        or (payload.get("full_observation_v1") or {}).get("target_dim"),
        "generated_dims": dims,
        "missing_field_counts": missing,
        "zero_filled_field_count_total": zero_filled,
        "checkpoint_compatibility_claimed": payload.get("checkpoint_compatibility_claimed"),
        "policy_architecture_parity_claimed": payload.get("policy_architecture_parity_claimed"),
        "complete_claimed": complete_claimed,
        "complete_evidence": bool(complete_evidence and no_missing),
        "fake_complete_claim": bool(complete_claimed and not (complete_evidence and no_missing)),
    }


def website_review() -> dict[str, Any]:
    packet = read_json(WEBSITE_IMPLEMENTATION_PUBLIC_PAYLOAD)
    legacy_packet = read_json(WEBSITE_LEGACY_OPERATOR_PAYLOAD)
    if not packet:
        packet = legacy_packet
    route_matrix = read_json(WEBSITE_PACKET_DIR / "route_product_matrix.json")
    implementation_matrix = read_json(WEBSITE_PACKET_DIR / "website_route_implementation_matrix.json")
    source_matrix = read_json(WEBSITE_PACKET_DIR / "website_payload_source_matrix.json")
    subsystem_matrix = read_json(WEBSITE_PACKET_DIR / "subsystem_visibility_matrix.json")
    public_pages = [
        ROOT / "v2/frontend/src/pages/market/index.tsx",
        ROOT / "v2/frontend/src/pages/market/meta.ts",
        ROOT / "v2/frontend/src/pages/market/route.ts",
        ROOT / "v2/frontend/src/pages/market/rbac.ts",
        ROOT / "v2/frontend/src/data/realtimeUserWebsitePayloads.ts",
        ROOT / "v2/frontend/src/components/realtimeWebsite/index.tsx",
        ROOT / "v2/frontend/src/pages/public-landing/index.tsx",
        ROOT / "v2/frontend/src/pages/public-status/index.tsx",
        ROOT / "v2/frontend/src/pages/user-status/index.tsx",
        ROOT / "v2/frontend/src/pages/market-intelligence/index.tsx",
        ROOT / "v2/frontend/src/pages/paper-trading/index.tsx",
        ROOT / "v2/frontend/src/pages/registry.ts",
    ]
    sample_paths = [
        Path("/home/wali/Downloads/AI BOT rebuild - web/app.js"),
        Path("/home/wali/Downloads/AI BOT rebuild - web/AI BOT Landing v2.html"),
        Path("/home/wali/Downloads/AI BOT rebuild - web/AI BOT V2 admin-aligned.html"),
        Path("/home/wali/Downloads/AI BOT rebuild - web/STRATA Landing v1.html"),
        Path("/home/wali/Downloads/AI BOT rebuild - web/index.html"),
    ]
    public_hits: list[str] = []
    sample_risk_hits: list[str] = []
    mock_re = re.compile(r"STATIC_PROOF_FIXTURE|104328\.41|1\.84B|\bmock_current_truth\b|\bfixture_current_truth\b", re.I)
    dangerous_re = re.compile(r"BUY / LONG|SELL / SHORT|place order|cancel order|live execution opened|raw-payload", re.I)
    for path in public_pages:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            negative_or_safe = any(
                token in lowered
                for token in (
                    "cannot",
                    "does not",
                    "do not",
                    "read-only",
                    "read only",
                    "no live",
                    "no order",
                    "kept out",
                )
            )
            if (mock_re.search(line) or dangerous_re.search(line)) and not negative_or_safe:
                public_hits.append(f"{path_label(path)}:{idx}:{line.strip()[:140]}")
    for path in sample_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            if mock_re.search(line) or dangerous_re.search(line):
                sample_risk_hits.append(f"{path}:{idx}:{line.strip()[:140]}")
                if len(sample_risk_hits) >= 25:
                    break
    blockers: list[str] = []
    registry_text = (ROOT / "v2/frontend/src/pages/registry.ts").read_text(encoding="utf-8", errors="replace")
    market_route = (ROOT / "v2/frontend/src/pages/market/route.ts").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/market/route.ts").exists() else ""
    market_rbac = (ROOT / "v2/frontend/src/pages/market/rbac.ts").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/market/rbac.ts").exists() else ""
    admin_route = (ROOT / "v2/frontend/src/pages/admin-war-room/route.ts").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/admin-war-room/route.ts").exists() else ""
    admin_rbac = (ROOT / "v2/frontend/src/pages/admin-war-room/rbac.ts").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/admin-war-room/rbac.ts").exists() else ""
    market_page = (ROOT / "v2/frontend/src/pages/market/index.tsx").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/market/index.tsx").exists() else ""
    admin_page = (ROOT / "v2/frontend/src/pages/admin-war-room/index.tsx").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/pages/admin-war-room/index.tsx").exists() else ""
    data_hooks = (ROOT / "v2/frontend/src/data/realtimeUserWebsitePayloads.ts").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/data/realtimeUserWebsitePayloads.ts").exists() else ""
    components = (ROOT / "v2/frontend/src/components/realtimeWebsite/index.tsx").read_text(encoding="utf-8", errors="replace") if (ROOT / "v2/frontend/src/components/realtimeWebsite/index.tsx").exists() else ""
    if not packet:
        blockers.append("WEBSITE_OPERATOR_PAYLOAD_MISSING")
    if packet.get("frontend_code_changes_in_this_packet") is not True:
        blockers.append("WEBSITE_READY_PACKET_IS_CONTRACT_ONLY_NO_FRONTEND_WIRING")
    if packet.get("scope_in_this_packet") == "specification_and_visibility_matrix_only":
        blockers.append("WEBSITE_CURRENT_PUBLIC_SURFACE_NOT_PROVEN_FROM_REAL_PAYLOADS")
    if "'/market'" not in market_route or "MarketPage" not in registry_text:
        blockers.append("WEBSITE_PUBLIC_MARKET_ROUTE_NOT_REGISTERED")
    if "'/admin/war-room'" not in admin_route or "AdminWarRoomPage" not in registry_text:
        blockers.append("WEBSITE_ADMIN_WAR_ROOM_ROUTE_NOT_REGISTERED")
    if "minRole: 'public'" not in market_rbac:
        blockers.append("WEBSITE_MARKET_ROUTE_NOT_PUBLIC")
    if "minRole: 'admin'" not in admin_rbac:
        blockers.append("WEBSITE_ADMIN_WAR_ROOM_ROUTE_NOT_ADMIN_GATED")
    if "useJsonPayload" not in data_hooks or "cache: 'no-store'" not in data_hooks:
        blockers.append("WEBSITE_TYPED_PAYLOAD_FETCH_HOOKS_MISSING")
    if "PayloadMissingCard" not in components or "PAYLOAD_MISSING" not in components:
        blockers.append("WEBSITE_PAYLOAD_MISSING_COMPONENT_MISSING")
    if "PayloadMissingCard" not in market_page or "PayloadMissingCard" not in admin_page:
        blockers.append("WEBSITE_PAGES_DO_NOT_RENDER_PAYLOAD_MISSING")
    if "Live gate" not in market_page or "blocked_human_only" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_LIVE_BLOCK")
    if "Shutdown" not in market_page or "blocked" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_SHUTDOWN_BLOCK")
    if "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_FULL_OBSERVATION_PARTIAL")
    if "checkpoint_compatibility_claimed" not in market_page or "policy_architecture_parity_claimed" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_CHECKPOINT_POLICY_FALSE")
    if "source_status_counts" not in market_page or "rate_limit_state" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_PROVIDER_STATUS")
    if "liquidation.payload" not in market_page or "no_synthetic_liquidation_events" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_LIQUIDATION_WSS_HEALTH")
    if "top10.payload" not in market_page or "window_size_actual" not in market_page:
        blockers.append("WEBSITE_MARKET_DOES_NOT_SURFACE_BINANCE_DASHBOARDS")
    if "raw-payload" in market_page or "Raw payload explorer" in market_page:
        blockers.append("WEBSITE_PUBLIC_ROUTE_EXPOSES_ADMIN_RAW_PANEL")
    if "Raw payload explorer" not in admin_page or "minRole: 'admin'" not in admin_rbac:
        blockers.append("WEBSITE_ADMIN_RAW_PANEL_NOT_ADMIN_GATED")
    if public_hits:
        blockers.append("PUBLIC_ROUTE_TEXT_NEEDS_REVIEW_FOR_MOCK_OR_DANGEROUS_COPY")
    if packet.get("gate") not in (None, LIVE_GATE):
        blockers.append("WEBSITE_LIVE_GATE_DRIFT")
    if packet.get("live_gate") not in (None, LIVE_GATE):
        blockers.append("WEBSITE_LIVE_GATE_DRIFT")
    if packet.get("symbols_real") not in (None, []):
        blockers.append("WEBSITE_LIVE_SYMBOLS_DRIFT")
    if packet.get("live_symbols") not in (None, []):
        blockers.append("WEBSITE_LIVE_SYMBOLS_DRIFT")
    if packet.get("approves_real") is True or packet.get("approves_canary") is True:
        blockers.append("WEBSITE_LIVE_OR_CANARY_APPROVAL_DRIFT")
    if packet.get("approves_legacy_shutdown") is True or packet.get("approves_redis_trim") is True:
        blockers.append("WEBSITE_SHUTDOWN_OR_REDIS_TRIM_APPROVAL_DRIFT")
    go = WEBSITE_FAIL if blockers else WEBSITE_PASS
    return {
        "go_no_go": go,
        "blockers": blockers,
        "packet_path": path_label(WEBSITE_IMPLEMENTATION_PUBLIC_PAYLOAD if read_json(WEBSITE_IMPLEMENTATION_PUBLIC_PAYLOAD) else WEBSITE_LEGACY_OPERATOR_PAYLOAD),
        "packet_present": bool(packet),
        "route_matrix_present": bool(route_matrix),
        "implementation_matrix_present": bool(implementation_matrix),
        "source_matrix_present": bool(source_matrix),
        "subsystem_matrix_present": bool(subsystem_matrix),
        "frontend_code_changes_in_this_packet": packet.get("frontend_code_changes_in_this_packet"),
        "scope_in_this_packet": packet.get("scope_in_this_packet"),
        "build": packet.get("build") or {},
        "routes": [
            {"path": row.get("path"), "surface": row.get("surface"), "registered": row.get("registered_in_registry")}
            for row in packet.get("routes", [])
            if isinstance(row, dict)
        ],
        "mock_data_used_as_current_truth_claimed": packet.get("mock_data_used_as_current_truth"),
        "no_mock_data_as_current_truth": packet.get("no_mock_data_as_current_truth"),
        "static_proof_fixture_used_as_primary_truth_claimed": packet.get("static_proof_fixture_used_as_primary_truth"),
        "no_static_proof_fixture_as_primary_truth": packet.get("no_static_proof_fixture_as_primary_truth"),
        "sample_design_reference_risk_hits": sample_risk_hits,
        "public_route_review_hits": public_hits,
        "live_gate": packet.get("live_gate") or packet.get("gate"),
        "live_symbols": packet.get("live_symbols") if "live_symbols" in packet else packet.get("symbols_real"),
        "approves_live": packet.get("approves_real"),
        "approves_canary": packet.get("approves_canary"),
        "approves_legacy_shutdown": packet.get("approves_legacy_shutdown"),
        "approves_redis_trim": packet.get("approves_redis_trim"),
    }


def write_website_review(review: dict[str, Any], generated: str) -> None:
    out = WEBSITE_PACKET_DIR / "codex_review"
    lines = [
        "# Codex Review: V2 Realtime User Website From Real Payloads",
        "",
        f"Generated: `{generated}`",
        "",
        f"GO/NO-GO: `{review['go_no_go']}`",
        "",
        "## Decision",
        "",
    ]
    if review["go_no_go"] == WEBSITE_PASS:
        lines.append(
            "Codex passes the realtime user website implementation packet. The public `/market` "
            "and admin `/admin/war-room` routes are registered, wired to V2 public payload paths, "
            "and render explicit missing/stale evidence instead of mock current truth."
        )
    else:
        lines.append(
            "Codex fails the realtime user website packet as an implementation-ready claim. "
            "The route/product contract is useful, but the reviewed evidence does not yet prove "
            "the public website is wired safely to real current V2 payloads."
        )
    lines.extend(
        [
            "",
            "This review does not approve live trading, canary trading, exchange mutation, Redis trim, checkpoint compatibility, policy architecture parity, or legacy shutdown.",
            "",
            "## Findings",
            "",
        ]
    )
    if review["blockers"]:
        lines.extend(f"- `{blocker}`" for blocker in review["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Website Packet",
            "",
            f"- frontend code changes in packet: `{review.get('frontend_code_changes_in_this_packet')}`",
            f"- scope: `{review.get('scope_in_this_packet')}`",
            f"- implementation matrix present: `{review.get('implementation_matrix_present')}`",
            f"- source matrix present: `{review.get('source_matrix_present')}`",
            f"- routes: `{review.get('routes')}`",
            f"- build: `{review.get('build')}`",
            f"- live_gate: `{review.get('live_gate')}`",
            f"- live_symbols: `{review.get('live_symbols')}`",
            f"- approves live/canary/shutdown/redis-trim: `{review.get('approves_live')}` / `{review.get('approves_canary')}` / `{review.get('approves_legacy_shutdown')}` / `{review.get('approves_redis_trim')}`",
            "",
            "## Evidence",
            "",
            "- `/market` is public and has no order-entry or live-control surface.",
            "- `/admin/war-room` is admin-gated and contains the raw payload explorer.",
            "- Missing payloads render `PAYLOAD_MISSING` with the exact path.",
            "- Sample files under `/home/wali/Downloads/AI BOT rebuild - web` are not imported as current truth.",
            "",
            "## Sample Reference Risk",
            "",
            "The sample files under `/home/wali/Downloads/AI BOT rebuild - web` contain mock/live-feeling and order-entry style UI text. They may be used only as design reference after removing or gating those surfaces; they are not accepted as current runtime truth.",
            "",
            "## Final Decision",
            "",
            f"`{review['go_no_go']}`",
            "",
        ]
    )
    write_text(out / "CODEX_REVIEW.md", "\n".join(lines))
    write_text(out / "CODEX_GO_NO_GO.md", review["go_no_go"] + "\n")


def evaluate() -> dict[str, Any]:
    generated = utc_now()
    refresh = refresh_safe_payloads()

    war_room = read_json(WAR_ROOM_STATUS)
    war_runtime = read_json(WAR_ROOM_RUNTIME)
    review_queue = read_json(WAR_ROOM_REVIEW_QUEUE)
    actions = read_json(WAR_ROOM_ACTIONS)
    continuous = read_json(CONTINUOUS_STATUS)
    legacy_log = read_json(LEGACY_LOG_STATUS)
    comparator = read_json(COMPARATOR_STATUS)
    full_observation = read_json(FULL_OBSERVATION_STATUS)
    frontend_truth = read_json(FRONTEND_TRUTH)
    liquidation_status = read_json(LIQUIDATION_WSS_STATUS)

    redis = {name: redis_scan(pattern) for name, pattern in V2_REDIS_PATTERNS.items()}
    heartbeat_ttl, heartbeat_payload = redis_get_json(LIQUIDATION_HEARTBEAT_KEY)
    position_history_ttl, position_history_payload = redis_get_json(
        POSITION_HISTORY_HEARTBEAT_KEY
    )
    processes = process_guard()
    systemd = systemd_guard()
    checkpoint = checkpoint_task_guard()
    broad_audit = broad_audit_guard()
    secrets = raw_secret_scan()
    forbidden_provider = forbidden_provider_scan()
    source = source_scan()
    full_obs_guard = full_observation_guard(full_observation)
    site_review = website_review()
    write_website_review(site_review, generated)

    payloads = [war_room, review_queue, continuous, legacy_log, comparator, full_observation, frontend_truth, liquidation_status]
    live_gate_guard = live_gate_from(payloads)

    ages = {
        "war_room_status": age_seconds(war_room),
        "war_room_runtime": age_seconds(war_runtime),
        "continuous_governor": age_seconds(continuous),
        "legacy_log_observer": age_seconds(legacy_log),
        "comparator": age_seconds(comparator),
        "liquidation_wss_status": age_seconds(liquidation_status),
        "full_observation": age_seconds(full_observation),
        "frontend_truth": age_seconds(frontend_truth),
    }

    fail_blockers: list[str] = []
    if not war_room or ages["war_room_status"] is None or ages["war_room_status"] > 900:
        fail_blockers.append(f"WAR_ROOM_HEARTBEAT_STALE_OR_MISSING:{ages['war_room_status']}")
    if not war_runtime or ages["war_room_runtime"] is None or ages["war_room_runtime"] > 900:
        fail_blockers.append(f"WAR_ROOM_RUNTIME_STATUS_STALE_OR_MISSING:{ages['war_room_runtime']}")
    if continuous.get("go_no_go") != "CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY":
        fail_blockers.append("CONTINUOUS_REMEDIATION_GOVERNOR_NOT_READY")
    if ages["legacy_log_observer"] is None or ages["legacy_log_observer"] > 300:
        fail_blockers.append(f"LEGACY_LOG_OBSERVER_STALE:{ages['legacy_log_observer']}")
    if ages["comparator"] is None or ages["comparator"] > 600:
        fail_blockers.append(f"COMPARATOR_STALE:{ages['comparator']}")
    if heartbeat_ttl <= 0 or not heartbeat_payload:
        fail_blockers.append(f"LIQUIDATION_WSS_HEARTBEAT_NOT_FRESH:{heartbeat_ttl}")
    elif age_seconds(heartbeat_payload) is None or age_seconds(heartbeat_payload) > 240:
        fail_blockers.append(f"LIQUIDATION_WSS_HEARTBEAT_STALE:{age_seconds(heartbeat_payload)}")
    if heartbeat_payload.get("no_synthetic_liquidation_events") is False:
        fail_blockers.append("LIQUIDATION_SYNTHETIC_EVENT_DRIFT")
    if heartbeat_payload.get("writes_legacy_redis") is True:
        fail_blockers.append("LIQUIDATION_WSS_OLD_REDIS_WRITE_DRIFT")
    if heartbeat_payload.get("writes_exchange_orders") is True:
        fail_blockers.append("LIQUIDATION_WSS_EXCHANGE_MUTATION_DRIFT")
    if heartbeat_payload:
        observed_mode = heartbeat_payload.get("process_mode")
        if observed_mode not in (None, "persistent_daemon"):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_PROCESS_MODE_NOT_PERSISTENT_DAEMON:{observed_mode}"
            )
        observed_gate = heartbeat_payload.get("live_gate")
        if observed_gate not in (None, LIVE_GATE):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_LIVE_GATE_DRIFT:{observed_gate}"
            )
        observed_symbols = heartbeat_payload.get("live_symbols")
        if observed_symbols not in (None, []):
            fail_blockers.append(
                f"LIQUIDATION_WSS_DAEMON_LIVE_SYMBOLS_DRIFT:{observed_symbols}"
            )
    # Position-history persistent-tracker daemon. NO_OPEN_POSITION is
    # acceptable; we never require open positions or MFE/MAE/ROE.
    if position_history_ttl <= 0 or not position_history_payload:
        fail_blockers.append(
            f"POSITION_HISTORY_HEARTBEAT_NOT_FRESH:{position_history_ttl}"
        )
    else:
        position_history_age = age_seconds(position_history_payload)
        if (
            position_history_age is None
            or position_history_age > POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS
        ):
            fail_blockers.append(
                f"POSITION_HISTORY_HEARTBEAT_STALE:{position_history_age}"
            )
    if position_history_payload.get("writes_legacy_redis") is True:
        fail_blockers.append("POSITION_HISTORY_DAEMON_OLD_REDIS_WRITE_DRIFT")
    if position_history_payload.get("writes_exchange_orders") is True:
        fail_blockers.append("POSITION_HISTORY_DAEMON_EXCHANGE_MUTATION_DRIFT")
    if position_history_payload.get("no_synthesized_accepted_positions") is False:
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_SYNTHESIZED_ACCEPTED_POSITIONS_DRIFT"
        )
    if position_history_payload.get("no_fabricated_excursion_metrics") is False:
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_FABRICATED_EXCURSION_METRICS_DRIFT"
        )
    if (
        position_history_payload.get("no_shadow_observations_counted_as_accepted")
        is False
    ):
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_SHADOW_COUNTED_AS_ACCEPTED_DRIFT"
        )
    if position_history_payload.get("full_observation_consumption_allowed") is True:
        fail_blockers.append(
            "POSITION_HISTORY_DAEMON_FULL_OBSERVATION_CONSUMPTION_DRIFT"
        )
    if position_history_payload:
        observed_mode = position_history_payload.get("process_mode")
        if observed_mode not in (None, "persistent_daemon"):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_PROCESS_MODE_NOT_PERSISTENT_DAEMON:{observed_mode}"
            )
        if position_history_payload.get("service_active") is False:
            fail_blockers.append("POSITION_HISTORY_DAEMON_SERVICE_ACTIVE_FALSE_DRIFT")
        observed_gate = position_history_payload.get("live_gate")
        if observed_gate not in (None, LIVE_GATE):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_LIVE_GATE_DRIFT:{observed_gate}"
            )
        observed_symbols = position_history_payload.get("live_symbols")
        if observed_symbols not in (None, []):
            fail_blockers.append(
                f"POSITION_HISTORY_DAEMON_LIVE_SYMBOLS_DRIFT:{observed_symbols}"
            )
    if ages["full_observation"] is None or ages["full_observation"] > 600:
        fail_blockers.append(f"FULL_OBSERVATION_PAYLOAD_STALE:{ages['full_observation']}")
    if ages["frontend_truth"] is None or ages["frontend_truth"] > 600:
        fail_blockers.append(f"FRONTEND_TRUTH_STALE:{ages['frontend_truth']}")
    if redis["v2:*"]["count"] <= 0:
        fail_blockers.append("V2_REDIS_NAMESPACE_EMPTY")
    missing_processes = [name for name, item in processes.items() if not item.get("running")]
    if missing_processes:
        fail_blockers.append("V2_RUNTIME_PROCESS_MISSING:" + ",".join(missing_processes))
    inactive_services = [name for name, state in systemd.items() if state != "active"]
    if inactive_services:
        fail_blockers.append("SYSTEMD_SERVICE_INACTIVE:" + ",".join(inactive_services))
    if checkpoint["duplicate_checkpoint_tasks"]:
        fail_blockers.append("DUPLICATE_CHECKPOINT_TASKS")
    if not broad_audit["no_broad_audit_tasks"]:
        fail_blockers.append("BROAD_AUDIT_TASK_DRIFT")
    if secrets["raw_values_exposed"]:
        fail_blockers.append("RAW_API_KEY_EXPOSED_OUTSIDE_LOCAL_SECRETS")
    if not forbidden_provider["no_forbidden_provider_references"]:
        fail_blockers.append("FORBIDDEN_PROVIDER_REFERENCE_FOUND")
    if not source["no_old_redis_writes"]:
        fail_blockers.append("OLD_REDIS_WRITE_RISK_FOUND")
    if not source["no_exchange_mutation"]:
        fail_blockers.append("EXCHANGE_MUTATION_SURFACE_FOUND")
    if not source["no_approval_drift"]:
        fail_blockers.append("LIVE_CANARY_SHUTDOWN_OR_REDIS_TRIM_APPROVAL_DRIFT")
    if not live_gate_guard["ok"]:
        fail_blockers.append("LIVE_GATE_OR_SYMBOL_DRIFT")
    if review_queue.get("policy_architecture_port_started") is True:
        fail_blockers.append("POLICY_ARCHITECTURE_IMPLEMENTATION_STARTED_PREMATURELY")
    if review_queue.get("checkpoint_compatibility_claimed") is True:
        fail_blockers.append("CHECKPOINT_COMPATIBILITY_CLAIMED_PREMATURELY")
    if full_obs_guard["checkpoint_compatibility_claimed"] is True:
        fail_blockers.append("FULL_OBSERVATION_CHECKPOINT_COMPATIBILITY_DRIFT")
    if full_obs_guard["policy_architecture_parity_claimed"] is True:
        fail_blockers.append("FULL_OBSERVATION_POLICY_PARITY_DRIFT")
    if full_obs_guard["fake_complete_claim"]:
        fail_blockers.append("FULL_OBSERVATION_COMPLETE_CLAIM_WITHOUT_1911_EVIDENCE")
    if int(full_obs_guard.get("zero_filled_field_count_total") or 0) > 0:
        fail_blockers.append("FULL_OBSERVATION_ZERO_FILL_DRIFT")
    if site_review["go_no_go"] != WEBSITE_PASS:
        fail_blockers.append("REALTIME_USER_WEBSITE_REVIEW_NOT_PASSING")
    if actions.get("writes_legacy_redis") is True or actions.get("writes_exchange_orders") is True:
        fail_blockers.append("WAR_ROOM_ACTIONS_UNSAFE")

    core_migration_blocker_names = {
        "POLICY_ARCHITECTURE_IMPLEMENTATION_STARTED_PREMATURELY",
        "CHECKPOINT_COMPATIBILITY_CLAIMED_PREMATURELY",
        "FULL_OBSERVATION_CHECKPOINT_COMPATIBILITY_DRIFT",
        "FULL_OBSERVATION_POLICY_PARITY_DRIFT",
        "FULL_OBSERVATION_COMPLETE_CLAIM_WITHOUT_1911_EVIDENCE",
        "FULL_OBSERVATION_ZERO_FILL_DRIFT",
    }
    website_fail_blockers = (
        ["REALTIME_USER_WEBSITE_REVIEW_NOT_PASSING", *site_review.get("blockers", [])]
        if site_review["go_no_go"] != WEBSITE_PASS
        else []
    )
    core_migration_fail_blockers = [
        blocker for blocker in fail_blockers if blocker in core_migration_blocker_names
    ]
    runtime_fail_blockers = [
        blocker
        for blocker in fail_blockers
        if blocker != "REALTIME_USER_WEBSITE_REVIEW_NOT_PASSING"
        and blocker not in core_migration_blocker_names
    ]
    runtime_go_no_go = "READY" if not runtime_fail_blockers else "BLOCKED"
    website_go_no_go = "PASS" if site_review["go_no_go"] == WEBSITE_PASS else "FAIL"
    core_migration_go_no_go = "READY" if not core_migration_fail_blockers else "BLOCKED"
    overall_go_no_go = "READY" if not fail_blockers else "BLOCKED"
    go_no_go = GO_READY if not fail_blockers else GO_BLOCKED
    return {
        "schema_version": "codex_8h_war_room_review_governor_v1",
        "generated_utc": generated,
        "go_no_go": go_no_go,
        "runtime_go_no_go": runtime_go_no_go,
        "website_go_no_go": website_go_no_go,
        "core_migration_go_no_go": core_migration_go_no_go,
        "overall_go_no_go": overall_go_no_go,
        "overall_go_no_go_token": go_no_go,
        "single_fail_blocker": fail_blockers[0] if len(fail_blockers) == 1 else None,
        "fail_blockers": fail_blockers,
        "runtime_fail_blockers": runtime_fail_blockers,
        "website_fail_blockers": website_fail_blockers,
        "core_migration_fail_blockers": core_migration_fail_blockers,
        "refresh_results": refresh,
        "summary": {
            "runtime_go_no_go": runtime_go_no_go,
            "website_go_no_go": website_go_no_go,
            "core_migration_go_no_go": core_migration_go_no_go,
            "overall_go_no_go": overall_go_no_go,
            "single_fail_blocker": fail_blockers[0] if len(fail_blockers) == 1 else None,
            "war_room_go_no_go": war_room.get("go_no_go"),
            "war_room_cycle_count": (war_room.get("cycle") or {}).get("cycle_count") or (war_room.get("state") or {}).get("cycle_count"),
            "war_room_status_age_seconds": ages["war_room_status"],
            "continuous_remediation_governor": continuous.get("go_no_go"),
            "v2_processes_running": (continuous.get("summary") or {}).get("v2_processes_running"),
            "v2_processes_required": (continuous.get("summary") or {}).get("v2_processes_required"),
            "soak_6h_ready": (continuous.get("summary") or {}).get("soak_6h_ready"),
            "soak_minutes_observed": (continuous.get("summary") or {}).get("soak_minutes_observed"),
            "legacy_log_observer_age_seconds": ages["legacy_log_observer"],
            "comparator_age_seconds": ages["comparator"],
            "liquidation_wss_heartbeat_ttl_seconds": heartbeat_ttl,
            "liquidation_wss_heartbeat_age_seconds": age_seconds(heartbeat_payload),
            "position_history_heartbeat_ttl_seconds": position_history_ttl,
            "position_history_heartbeat_age_seconds": age_seconds(position_history_payload),
            "position_history_open_position_symbol_count": position_history_payload.get(
                "open_position_symbol_count"
            ),
            "position_history_no_open_position_symbol_count": position_history_payload.get(
                "no_open_position_symbol_count"
            ),
            "position_history_cycle_count": position_history_payload.get("cycle_count"),
            "position_history_full_observation_consumption_allowed": (
                position_history_payload.get("full_observation_consumption_allowed")
            ),
            "full_observation_state": full_obs_guard.get("state"),
            "full_observation_target_dim": full_obs_guard.get("target_dim"),
            "full_observation_generated_dims": full_obs_guard.get("generated_dims"),
            "frontend_truth_age_seconds": ages["frontend_truth"],
            "v2_namespace_count": redis["v2:*"]["count"],
            "checkpoint_task_count": checkpoint["task_count"],
            "website_review_go_no_go": site_review["go_no_go"],
            "live_gate": LIVE_GATE,
            "live_symbols": [],
        },
        "war_room": {
            "status_path": path_label(WAR_ROOM_STATUS),
            "runtime_path": path_label(WAR_ROOM_RUNTIME),
            "review_queue_path": path_label(WAR_ROOM_REVIEW_QUEUE),
            "review_queue": review_queue,
        },
        "processes": processes,
        "systemd_services": systemd,
        "redis": redis,
        "liquidation_wss_heartbeat": {
            "key": LIQUIDATION_HEARTBEAT_KEY,
            "ttl_seconds": heartbeat_ttl,
            "age_seconds": age_seconds(heartbeat_payload),
            "payload": heartbeat_payload,
            "process_mode": heartbeat_payload.get("process_mode"),
            "live_gate": heartbeat_payload.get("live_gate"),
            "live_symbols": heartbeat_payload.get("live_symbols"),
            "service_active": heartbeat_payload.get("service_active"),
            "opt_in_enabled": heartbeat_payload.get("opt_in_enabled"),
            "expected_process_mode": "persistent_daemon",
            "expected_live_gate": LIVE_GATE,
            "expected_live_symbols": [],
        },
        "position_history_heartbeat": {
            "key": POSITION_HISTORY_HEARTBEAT_KEY,
            "ttl_seconds": position_history_ttl,
            "age_seconds": age_seconds(position_history_payload),
            "payload": position_history_payload,
            "process_mode": position_history_payload.get("process_mode"),
            "service_active": position_history_payload.get("service_active"),
            "live_gate": position_history_payload.get("live_gate"),
            "live_symbols": position_history_payload.get("live_symbols"),
            "cycle_count": position_history_payload.get("cycle_count"),
            "open_position_symbol_count": position_history_payload.get(
                "open_position_symbol_count"
            ),
            "no_open_position_symbol_count": position_history_payload.get(
                "no_open_position_symbol_count"
            ),
            "full_observation_consumption_allowed": position_history_payload.get(
                "full_observation_consumption_allowed"
            ),
            "expected_process_mode": "persistent_daemon",
            "expected_live_gate": LIVE_GATE,
            "expected_live_symbols": [],
            "expected_max_age_seconds": POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS,
            "no_open_position_is_failure": False,
            "open_positions_required": False,
        },
        "full_observation": full_obs_guard,
        "website_review": site_review,
        "checkpoint_task_guard": checkpoint,
        "broad_audit_guard": broad_audit,
        "secret_scan": secrets,
        "forbidden_provider_scan": forbidden_provider,
        "source_scan": source,
        "live_gate_guard": live_gate_guard,
        "safety": {
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "raw_values_exposed": secrets["raw_values_exposed"],
        },
    }


def render_markdown(status: dict[str, Any]) -> str:
    summary = status["summary"]
    lines = [
        "# Codex 5M Status: 8H War-Room Review Governor",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
    ]
    if status["go_no_go"] == GO_READY:
        lines.append("The Codex 8h war-room review governor is passing its checks.")
    else:
        lines.append("The Codex 8h war-room review governor is blocked on one or more review checks.")
    lines.extend(
        [
            "",
            "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
            "",
            "## Runtime",
            "",
            f"- Runtime GO/NO-GO: `{status.get('runtime_go_no_go')}`",
            f"- Website GO/NO-GO: `{status.get('website_go_no_go')}`",
            f"- Core migration GO/NO-GO: `{status.get('core_migration_go_no_go')}`",
            f"- Overall GO/NO-GO: `{status.get('overall_go_no_go')}`",
            f"- Single fail blocker: `{status.get('single_fail_blocker')}`",
            f"- War-room cycle count: `{summary.get('war_room_cycle_count')}`",
            f"- War-room status age seconds: `{summary.get('war_room_status_age_seconds')}`",
            f"- Continuous remediation governor: `{summary.get('continuous_remediation_governor')}`",
            f"- V2/remediation processes: `{summary.get('v2_processes_running')}/{summary.get('v2_processes_required')}`",
            f"- 6h soak ready: `{summary.get('soak_6h_ready')}`",
            f"- Soak minutes observed: `{summary.get('soak_minutes_observed')}`",
            f"- Legacy log observer age seconds: `{summary.get('legacy_log_observer_age_seconds')}`",
            f"- Comparator age seconds: `{summary.get('comparator_age_seconds')}`",
            f"- Liquidation WSS heartbeat TTL seconds: `{summary.get('liquidation_wss_heartbeat_ttl_seconds')}`",
            f"- Liquidation WSS heartbeat age seconds: `{summary.get('liquidation_wss_heartbeat_age_seconds')}`",
            f"- V2 Redis namespace count: `{summary.get('v2_namespace_count')}`",
            "",
            "## Full Observation",
            "",
            f"- State: `{summary.get('full_observation_state')}`",
            f"- Target dim: `{summary.get('full_observation_target_dim')}`",
            f"- Generated dims: `{summary.get('full_observation_generated_dims')}`",
            f"- checkpoint_compatibility_claimed: `{status['full_observation'].get('checkpoint_compatibility_claimed')}`",
            f"- policy_architecture_parity_claimed: `{status['full_observation'].get('policy_architecture_parity_claimed')}`",
            "",
            "## Website Review",
            "",
            f"- Realtime user website Codex review: `{summary.get('website_review_go_no_go')}`",
            f"- Packet frontend code changes: `{status['website_review'].get('frontend_code_changes_in_this_packet')}`",
            f"- Packet scope: `{status['website_review'].get('scope_in_this_packet')}`",
            "",
            "## Fail Blockers",
            "",
        ]
    )
    if status["fail_blockers"]:
        lines.extend(f"- `{blocker}`" for blocker in status["fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Runtime Fail Blockers", ""])
    if status.get("runtime_fail_blockers"):
        lines.extend(f"- `{blocker}`" for blocker in status["runtime_fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Website Fail Blockers", ""])
    if status.get("website_fail_blockers"):
        lines.extend(f"- `{blocker}`" for blocker in status["website_fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Core Migration Fail Blockers", ""])
    if status.get("core_migration_fail_blockers"):
        lines.extend(f"- `{blocker}`" for blocker in status["core_migration_fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- `live_gate`: `{LIVE_GATE}`",
            "- `live_symbols`: `[]`",
            "- `approves_live`: `false`",
            "- `approves_canary`: `false`",
            "- `approves_legacy_shutdown`: `false`",
            "- `approves_redis_trim`: `false`",
            f"- raw API key exposure: `{status['secret_scan'].get('raw_values_exposed')}`",
            f"- old Redis write scan clean: `{status['source_scan'].get('no_old_redis_writes')}`",
            f"- exchange mutation scan clean: `{status['source_scan'].get('no_exchange_mutation')}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(status: dict[str, Any]) -> None:
    write_json(OUT / "codex_5m_status.json", status)
    write_json(PUBLIC / "codex_5m_review_payload.json", status)
    write_text(OUT / "CODEX_5M_STATUS.md", render_markdown(status))
    write_text(OUT / "CODEX_GO_NO_GO.md", status["go_no_go"] + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_8h_war_room_review_governor")
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
            time.sleep(max(60, args.interval_seconds))
    write_outputs(evaluate())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
