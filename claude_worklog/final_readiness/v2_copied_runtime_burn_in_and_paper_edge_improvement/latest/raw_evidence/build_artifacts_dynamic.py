#!/usr/bin/env python3
"""Refresh V2 copied-runtime burn-in and paper-edge evidence.

This is an observer only. It writes filesystem JSON/Markdown artifacts for the
operator dashboard and never writes Redis, calls exchange endpoints, enables
live/canary, changes leverage/margin, or touches the legacy root runtime.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASK_ID = "v2_copied_runtime_burn_in_and_paper_edge_improvement"
READY = "V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_READY"
BLOCKED = "V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_BLOCKED"

WORKLOG = ROOT / "claude_worklog" / "final_readiness" / TASK_ID / "latest"
PUBLIC = ROOT / "v2" / "frontend" / "public" / TASK_ID / "latest"
RAW = WORKLOG / "raw_evidence"
TZ = ZoneInfo("America/New_York")

COPIED_UNITS = (
    "ai-bot-v2-liquidation-bridge.service",
    "ai-bot-v2-liquidation-levels-engine.service",
    "ai-bot-v2-liquidation-wss-paper-shadow.service",
)

REQUIRED_RUNTIME_UNITS = (
    "ai-bot-v2-native-ingestors-live-loop.service",
    "ai-bot-v2-feature-pipeline-native-loop.service",
    "ai-bot-v2-rl-core-inference-loop.service",
    "ai-bot-v2-trainer-bridge.service",
    "ai-bot-v2-orchestrator-arbitration-loop.service",
    "ai-bot-v2-paper-online-runtime.service",
    "ai-bot-v2-trade-management-paper-loop.service",
    "ai-bot-v2-paper-shadow-observation.service",
    "ai-bot-v2-feature-snapshot-builder.service",
    "ai-bot-v2-liquidation-bridge.service",
    "ai-bot-v2-liquidation-levels-engine.service",
    "ai-bot-v2-liquidation-wss-paper-shadow.service",
    "ai-bot-v2-public-website-backend.service",
    "ai-bot-v2-parallel-spark-automation.service",
)

STALE_MAX_SECONDS = 180
PROTECTED_OLD_REDIS_PATTERNS = (
    "orchestrator:*",
    "live_orders:*",
    "exchange:order:*",
    "order:*",
    "leverage:*",
    "margin:*",
    "*:leverage:*",
    "*:margin:*",
)

REDIS_COUNT_PATTERNS = (
    "v2:*",
    "v2:market:*",
    "v2:features:*",
    "v2:unified_features:*",
    "v2:prediction:*",
    "v2:trainer:*",
    "v2:paper:*",
    "v2:risk:*",
    "v2:orchestrator:*",
    "v2:liquidations:*",
    "v2:market:liquidation_levels:*",
    *PROTECTED_OLD_REDIS_PATTERNS,
)

PAYLOAD_PATHS = {
    "symbol_universe": ROOT
    / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json",
    "feature_snapshot": ROOT
    / "v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json",
    "trainer_bridge": ROOT
    / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json",
    "paper_runtime": ROOT
    / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
    "paper_shadow_observation": ROOT
    / "v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json",
    "liquidation_wss": ROOT
    / "v2/frontend/public/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json",
    "post_hoc_replay": ROOT
    / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/operator_dashboard_payload.json",
    "war_room": ROOT / "v2/frontend/public/v2_8h_war_room/latest/operator_dashboard_payload.json",
    "post_filter_edge": ROOT
    / "v2/frontend/public/paper_edge_post_filter_observation_window/latest/operator_dashboard_payload.json",
    "copied_restart_route_matrix": ROOT
    / "v2/frontend/public/v2_full_copied_runtime_and_trading_platform_restart/latest/production_route_matrix_codex_after.json",
}


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def run_out(cmd: list[str], timeout: int = 20) -> str:
    proc = run(cmd, timeout=timeout)
    return proc.stdout.strip()


def now_values() -> tuple[dt.datetime, dt.datetime, str, str]:
    now_est = dt.datetime.now(TZ)
    now_utc = now_est.astimezone(dt.timezone.utc)
    return (
        now_est,
        now_utc,
        now_est.strftime("%Y-%m-%dT%H:%M:%S%z"),
        now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_json(name: str, payload: dict[str, Any]) -> None:
    for root in (WORKLOG, PUBLIC):
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_text(name: str, text: str) -> None:
    for root in (WORKLOG, PUBLIC):
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def parse_ts(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%a %Y-%m-%d %H:%M:%S %Z"):
        try:
            parsed = dt.datetime.strptime(str(value), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TZ)
            return parsed
        except ValueError:
            continue
    parts = str(value).split()
    if len(parts) >= 3 and re.match(r"\d{4}-\d{2}-\d{2}", parts[1]):
        try:
            return dt.datetime.strptime(
                f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=TZ)
        except ValueError:
            return None
    return None


def payload_age_seconds(payload: dict[str, Any], path: Path, now_utc: dt.datetime) -> int | None:
    for key in (
        "generated_utc",
        "generated_at",
        "last_run_ts",
        "last_snapshot_ts",
        "heartbeat_at",
        "finished_at",
    ):
        parsed = parse_ts(payload.get(key))
        if parsed is not None:
            return max(0, int((now_utc - parsed.astimezone(dt.timezone.utc)).total_seconds()))
    if path.exists():
        return max(0, int(now_utc.timestamp() - path.stat().st_mtime))
    return None


def git_head() -> str:
    out = run_out(["git", "rev-parse", "HEAD"], timeout=10)
    return out or "UNKNOWN"


def list_systemd_services() -> list[str]:
    out = run_out(
        [
            "systemctl",
            "--user",
            "list-units",
            "ai-bot-v2-*",
            "--type=service",
            "--all",
            "--no-legend",
            "--plain",
        ],
        timeout=20,
    )
    units: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].startswith("ai-bot-v2-"):
            units.append(parts[0])
    return sorted(set(units))


def list_systemd_timers() -> list[str]:
    out = run_out(
        [
            "systemctl",
            "--user",
            "list-timers",
            "ai-bot-v2-*",
            "--all",
            "--no-legend",
            "--plain",
        ],
        timeout=20,
    )
    timers: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        for part in parts:
            if part.startswith("ai-bot-v2-") and part.endswith(".timer"):
                timers.append(part)
                break
    return sorted(set(timers))


def show_unit(unit: str, now_est: dt.datetime) -> dict[str, Any]:
    props = (
        "Id,Description,LoadState,ActiveState,SubState,MainPID,NRestarts,"
        "ExecMainStatus,ActiveEnterTimestamp,FragmentPath"
    )
    out = run_out(["systemctl", "--user", "show", unit, f"--property={props}"], timeout=10)
    data: dict[str, Any] = {"unit": unit}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    for key in ("MainPID", "NRestarts", "ExecMainStatus"):
        try:
            data[key] = int(str(data.get(key) or 0))
        except ValueError:
            data[key] = 0
    active_ts = parse_ts(data.get("ActiveEnterTimestamp"))
    data["uptime_seconds"] = (
        max(0, int((now_est - active_ts.astimezone(TZ)).total_seconds())) if active_ts else None
    )
    data["active"] = data.get("ActiveState") == "active"
    return data


def journal_error_count(unit: str) -> int:
    proc = run(
        [
            "journalctl",
            "--user",
            "-u",
            unit,
            "--since",
            "1 hour ago",
            "--no-pager",
            "--output=cat",
            "-n",
            "500",
        ],
        timeout=15,
    )
    text = f"{proc.stdout}\n{proc.stderr}"
    return len(re.findall(r"\b(error|exception|traceback|failed|failure)\b", text, re.I))


def redis_scan_count(pattern: str) -> int:
    if not shutil.which("redis-cli"):
        return -1
    proc = run(["redis-cli", "--raw", "--scan", "--pattern", pattern], timeout=30)
    if proc.returncode != 0:
        return -1
    return sum(1 for line in proc.stdout.splitlines() if line.strip())


def redis_get(key: str) -> str:
    if not shutil.which("redis-cli"):
        return ""
    return run_out(["redis-cli", "--raw", "GET", key], timeout=10)


def redis_xlen(key: str) -> int:
    if not shutil.which("redis-cli"):
        return -1
    out = run_out(["redis-cli", "--raw", "XLEN", key], timeout=10)
    try:
        return int(out or "0")
    except ValueError:
        return -1


def redis_ttl(key: str) -> int:
    if not shutil.which("redis-cli"):
        return -2
    out = run_out(["redis-cli", "--raw", "TTL", key], timeout=10)
    try:
        return int(out or "-2")
    except ValueError:
        return -2


def redis_family_counts() -> dict[str, int]:
    return {pattern: redis_scan_count(pattern) for pattern in REDIS_COUNT_PATTERNS}


def probe_url(path: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:5173{path}"
    proc = run(
        ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", url],
        timeout=8,
    )
    try:
        status = int(proc.stdout.strip() or "0")
    except ValueError:
        status = 0
    return {
        "path": path,
        "url": url,
        "http_status": status,
        "ok": 200 <= status < 400,
        "stderr": proc.stderr.strip()[:500],
    }


def process_scan() -> dict[str, Any]:
    proc = run(["ps", "-eo", "pid,etimes,args"], timeout=10)
    legacy_root_matches = []
    live_liq_matches = []
    exchange_mutation_terms = []
    for line in proc.stdout.splitlines():
        if "/home/wali/Desktop/AI BOT/" in line and "AI BOT REBUILD" not in line:
            legacy_root_matches.append(line.strip())
        if "live_binance_liquidations.py" in line:
            live_liq_matches.append(line.strip())
        lowered = line.lower()
        if (
            "test-order" in lowered
            or "change_leverage" in lowered
            or "change_margin" in lowered
            or "fapi/v1/order" in lowered
        ):
            exchange_mutation_terms.append(line.strip())
    return {
        "legacy_root_runtime_matches": legacy_root_matches[:20],
        "live_binance_liquidations_matches": live_liq_matches[:20],
        "exchange_mutation_process_terms": exchange_mutation_terms[:20],
    }


def load_payloads(now_utc: dt.datetime) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for name, path in PAYLOAD_PATHS.items():
        payload = load_json(path)
        loaded[name] = {
            "path": str(path.relative_to(ROOT)),
            "exists": path.exists(),
            "age_seconds": payload_age_seconds(payload, path, now_utc),
            "payload": payload,
        }
    return loaded


def resolve_symbol_evidence() -> dict[str, Any]:
    try:
        from v2.backend.app.services.v2_symbol_runtime_universe import (
            BASELINE_25_SYMBOLS,
            SMOKE_TEST_SYMBOLS,
            resolve_symbols,
        )

        symbols = list(resolve_symbols())
        baseline = list(BASELINE_25_SYMBOLS)
        smoke = list(SMOKE_TEST_SYMBOLS)
    except Exception as exc:
        return {
            "resolver_error": str(exc),
            "resolved_symbols": [],
            "resolved_count": 0,
            "baseline_25_retained": False,
            "smoke_test_default": True,
        }
    return {
        "resolved_symbols": symbols,
        "resolved_count": len(symbols),
        "baseline_25_symbols": baseline,
        "baseline_25_retained": set(baseline).issubset(set(symbols)),
        "smoke_test_symbols": smoke,
        "smoke_test_default": symbols == smoke,
        "symbol_profile": "dynamic_or_baseline" if len(symbols) >= 25 and symbols != smoke else "smoke_or_invalid",
    }


def build_artifacts() -> dict[str, Any]:
    now_est, now_utc, generated_est, generated_utc = now_values()
    WORKLOG.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    service_units = list_systemd_services()
    timer_units = list_systemd_timers()
    services = {unit: show_unit(unit, now_est) for unit in service_units}
    missing_required = [unit for unit in REQUIRED_RUNTIME_UNITS if unit not in services]
    inactive_required = [
        unit
        for unit in REQUIRED_RUNTIME_UNITS
        if unit in services and services[unit].get("ActiveState") != "active"
    ]
    error_counts = {unit: journal_error_count(unit) for unit in REQUIRED_RUNTIME_UNITS if unit in services}
    counts = redis_family_counts()
    payloads = load_payloads(now_utc)
    proc_scan = process_scan()
    symbol_evidence = resolve_symbol_evidence()

    core_uptimes = [
        int(services[unit]["uptime_seconds"])
        for unit in REQUIRED_RUNTIME_UNITS
        if unit in services
        and services[unit].get("ActiveState") == "active"
        and services[unit].get("uptime_seconds") is not None
    ]
    min_core_uptime = min(core_uptimes) if core_uptimes else 0
    copied_uptimes = [
        int(services[unit]["uptime_seconds"])
        for unit in COPIED_UNITS
        if unit in services
        and services[unit].get("ActiveState") == "active"
        and services[unit].get("uptime_seconds") is not None
    ]
    min_copied_uptime = min(copied_uptimes) if copied_uptimes else 0

    windows = {
        "1h": min_core_uptime >= 3600 and min_copied_uptime >= 3600,
        "6h": min_core_uptime >= 6 * 3600 and min_copied_uptime >= 6 * 3600,
        "12h": min_core_uptime >= 12 * 3600 and min_copied_uptime >= 12 * 3600,
    }

    active_services = [u for u, s in services.items() if s.get("ActiveState") == "active"]
    nonzero_restart_services = [
        {
            "unit": u,
            "n_restarts": s.get("NRestarts", 0),
            "active_state": s.get("ActiveState"),
            "sub_state": s.get("SubState"),
            "uptime_seconds": s.get("uptime_seconds"),
            "expected_cycle": (
                "position_history_600s_session"
                if "position-history" in u
                else "liquidation_wss_86400s_total_seconds_session"
                if "liquidation-wss-paper-shadow" in u
                else False
            ),
        }
        for u, s in services.items()
        if int(s.get("NRestarts") or 0) > 0 and s.get("ActiveState") == "active"
    ]

    protected_old_counts = {p: counts.get(p, -1) for p in PROTECTED_OLD_REDIS_PATTERNS}
    old_redis_detected = any(v > 0 for v in protected_old_counts.values())
    exchange_mutation_detected = (
        old_redis_detected
        or bool(proc_scan["exchange_mutation_process_terms"])
        or counts.get("exchange:order:*", 0) > 0
    )

    liq_wss = payloads["liquidation_wss"]["payload"]
    heartbeat_raw = redis_get("v2:market:liquidations:heartbeat")
    heartbeat_payload = {}
    if heartbeat_raw:
        try:
            heartbeat_payload = json.loads(heartbeat_raw)
        except Exception:
            heartbeat_payload = {"raw": heartbeat_raw[:1000]}
    liq_xlen = redis_xlen("v2:liquidations:events")
    liq_levels_keys = counts.get("v2:market:liquidation_levels:*", 0)
    liq_events_written = int(
        (heartbeat_payload.get("events_written") if isinstance(heartbeat_payload, dict) else 0)
        or liq_wss.get("events_written")
        or 0
    )
    liq_events_received = int(
        (heartbeat_payload.get("events_received") if isinstance(heartbeat_payload, dict) else 0)
        or liq_wss.get("events_received")
        or 0
    )

    symbol_payload = payloads["symbol_universe"]["payload"]
    discovered_symbols = (
        symbol_payload.get("dynamic_discovered_symbols")
        or symbol_payload.get("discovered_symbols")
        or symbol_evidence["resolved_symbols"]
    )

    feature_payload = payloads["feature_snapshot"]["payload"]
    trainer_payload = payloads["trainer_bridge"]["payload"]
    paper_payload = payloads["paper_shadow_observation"]["payload"]
    paper_runtime_payload = payloads["paper_runtime"]["payload"]
    post_hoc_payload = payloads["post_hoc_replay"]["payload"]
    war_room_payload = payloads["war_room"]["payload"]
    post_filter_payload = payloads["post_filter_edge"]["payload"]
    route_matrix = payloads["copied_restart_route_matrix"]["payload"]

    route_probe_paths = (
        "/healthz",
        "/",
        "/trader",
        "/paper-trading",
        "/risk-control",
        "/monitor-center",
        "/market",
        "/admin/report-center",
        "/admin/operator-proof-dashboard",
    )
    route_probes = [probe_url(path) for path in route_probe_paths]
    route_probe_failures = [p for p in route_probes if not p["ok"]]

    expected_move_after_cost_bps = post_hoc_payload.get("expected_move_after_cost_bps")
    paper_pnl_current = paper_payload.get("paper_pnl_current_usdt")
    paper_edge_positive = bool(post_filter_payload.get("paper_edge_positive_proven") is True)
    edge_thresholds_set = not any(
        value == "OPERATOR_DECISION_REQUIRED"
        for value in (post_hoc_payload.get("thresholds_satisfied") or {}).values()
    )
    post_hoc_edge_claimed = str(post_hoc_payload.get("verdict") or "").startswith("EDGE_PROVEN")
    paper_edge_proven = paper_edge_positive or post_hoc_edge_claimed

    safety = {
        "live_gate": "blocked_human_only",
        "live_gate_status": "blocked_human_only",
        "live_symbols": [],
        "v2_live": 0,
        "v2_canary": 0,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "exchange_action_taken": False,
        "places_real_order": False,
        "old_redis_writes_detected": old_redis_detected,
        "leverage_change": False,
        "margin_mode_change": False,
        "legacy_root_runtime_active": bool(proc_scan["legacy_root_runtime_matches"]),
        "live_binance_liquidations_active": bool(proc_scan["live_binance_liquidations_matches"]),
    }

    block_reasons: list[str] = []
    if missing_required:
        block_reasons.append("required_runtime_services_missing")
    if inactive_required:
        block_reasons.append("required_runtime_services_inactive")
    if any(error_counts.get(unit, 0) > 0 for unit in REQUIRED_RUNTIME_UNITS):
        block_reasons.append("required_runtime_recent_errors_present")
    if not windows["12h"]:
        block_reasons.append("burn_in_12h_window_not_complete")
    if not symbol_evidence["baseline_25_retained"] or symbol_evidence["smoke_test_default"]:
        block_reasons.append("dynamic_symbol_baseline_not_held")
    if liq_xlen <= 0 and liq_events_written <= 0:
        block_reasons.append("liquidation_bridge_levels_no_events_observed")
    if liq_levels_keys <= 0:
        block_reasons.append("v2_market_liquidation_levels_zero_keys")
    if not paper_edge_proven:
        block_reasons.append("paper_edge_not_proven")
    if isinstance(paper_pnl_current, (int, float)) and paper_pnl_current < 0:
        block_reasons.append("paper_pnl_negative")
    if not edge_thresholds_set:
        block_reasons.append("operator_edge_thresholds_not_set")
    if route_probe_failures:
        block_reasons.append("trading_platform_route_probe_failure")
    if old_redis_detected:
        block_reasons.append("old_redis_write_boundary_failed")
    if exchange_mutation_detected:
        block_reasons.append("exchange_mutation_boundary_failed")
    if safety["legacy_root_runtime_active"]:
        block_reasons.append("legacy_root_runtime_active")
    if safety["live_binance_liquidations_active"]:
        block_reasons.append("live_binance_liquidations_active")

    go_no_go = READY if not block_reasons else BLOCKED

    common = {
        "milestone": TASK_ID,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "git_head": git_head(),
        "go_no_go": go_no_go,
        "live_safety": safety,
    }

    burn_in_status = {
        "schema_version": "v2_copied_runtime_burn_in_status_v3",
        **common,
        "phase": 1,
        "runtime_summary": {
            "active_ai_bot_v2_user_services_count": len(active_services),
            "loaded_ai_bot_v2_user_services_count": len(services),
            "active_ai_bot_v2_user_timers_count": len(timer_units),
            "required_runtime_units": list(REQUIRED_RUNTIME_UNITS),
            "missing_required_units": missing_required,
            "inactive_required_units": inactive_required,
            "min_required_runtime_uptime_seconds": min_core_uptime,
            "min_copied_component_uptime_seconds": min_copied_uptime,
            "min_required_runtime_uptime_hours": round(min_core_uptime / 3600.0, 2),
            "min_copied_component_uptime_hours": round(min_copied_uptime / 3600.0, 2),
            "burn_in_windows": windows,
            "services_with_nonzero_restart": nonzero_restart_services,
            "required_unit_error_counts_last_1h": error_counts,
        },
        "copied_runtime_components": [services.get(unit, {"unit": unit, "missing": True}) for unit in COPIED_UNITS],
        "v2_runtime_components": [
            services.get(unit, {"unit": unit, "missing": True}) for unit in REQUIRED_RUNTIME_UNITS
        ],
        "process_safety_scan": proc_scan,
        "raw_evidence_sources": {
            "services": "raw_evidence/systemd_services.json",
            "timers": "raw_evidence/systemd_timers.json",
            "redis_counts": "raw_evidence/redis_family_counts.json",
        },
    }

    liquidation_impact = {
        "schema_version": "v2_liquidation_bridge_levels_runtime_impact_v3",
        **common,
        "phase": 2,
        "services": [services.get(unit, {"unit": unit, "missing": True}) for unit in COPIED_UNITS],
        "event_stream": {
            "key": "v2:liquidations:events",
            "xlen": liq_xlen,
            "events_received": liq_events_received,
            "events_written": liq_events_written,
            "heartbeat_key": "v2:market:liquidations:heartbeat",
            "heartbeat_ttl_seconds": redis_ttl("v2:market:liquidations:heartbeat"),
            "heartbeat_age_seconds": payload_age_seconds(heartbeat_payload, Path(), now_utc)
            if isinstance(heartbeat_payload, dict)
            else None,
            "heartbeat_payload_present": bool(heartbeat_payload),
        },
        "levels": {
            "v2_market_liquidation_levels_key_count": liq_levels_keys,
            "unified_feature_key_count": counts.get("v2:unified_features:*", 0),
            "output_namespace": "v2:unified_features:*",
        },
        "operational_proof_status": (
            "MEASURED_EVENTS_OBSERVED"
            if liq_xlen > 0 or liq_events_written > 0
            else "NOT_PROVEN_NO_EVENTS_OBSERVED"
        ),
        "live_binance_liquidations_excluded": not proc_scan["live_binance_liquidations_matches"],
    }

    dynamic_symbols = {
        "schema_version": "v2_dynamic_symbol_runtime_evidence_v3",
        **common,
        "phase": 3,
        "resolver": symbol_evidence,
        "public_payload": {
            "path": payloads["symbol_universe"]["path"],
            "age_seconds": payloads["symbol_universe"]["age_seconds"],
            "dynamic_discovered_count": len(discovered_symbols),
            "dynamic_discovered_symbols": discovered_symbols,
            "legacy_active_symbols_count": len(symbol_payload.get("legacy_active_symbols") or []),
            "baseline_25_retained": symbol_evidence["baseline_25_retained"],
            "live_symbols": symbol_payload.get("live_symbols", []),
            "live_gate": symbol_payload.get("live_gate") or symbol_payload.get("live_gate_status"),
        },
        "active_runtime_default_state": {
            "btc_only_default_active": False,
            "btc_eth_sol_only_default_active": False,
            "smoke_test_profile_active": symbol_evidence["smoke_test_default"],
            "default_profile": symbol_evidence["symbol_profile"],
        },
    }

    feature_ta_trainer = {
        "schema_version": "v2_feature_ta_trainer_runtime_impact_v3",
        **common,
        "phase": 4,
        "redis_family_counts": {
            "v2:market:*": counts.get("v2:market:*", 0),
            "v2:features:*": counts.get("v2:features:*", 0),
            "v2:unified_features:*": counts.get("v2:unified_features:*", 0),
            "v2:prediction:*": counts.get("v2:prediction:*", 0),
            "v2:trainer:*": counts.get("v2:trainer:*", 0),
            "v2:paper:*": counts.get("v2:paper:*", 0),
            "v2:risk:*": counts.get("v2:risk:*", 0),
            "v2:orchestrator:*": counts.get("v2:orchestrator:*", 0),
        },
        "feature_snapshot": {
            "path": payloads["feature_snapshot"]["path"],
            "age_seconds": payloads["feature_snapshot"]["age_seconds"],
            "fresh": (payloads["feature_snapshot"]["age_seconds"] or 999999) <= STALE_MAX_SECONDS,
            "trainer_readiness": feature_payload.get("trainer_readiness"),
            "feature_categories_present": feature_payload.get("feature_categories_present", []),
            "missing_features": feature_payload.get("missing_features", []),
            "stale_features": feature_payload.get("stale_features", []),
        },
        "trainer": {
            "path": payloads["trainer_bridge"]["path"],
            "age_seconds": payloads["trainer_bridge"]["age_seconds"],
            "fresh": (payloads["trainer_bridge"]["age_seconds"] or 999999) <= STALE_MAX_SECONDS,
            "role_label": "copied_parity_baseline_bridge",
            "called_v2_native_readiness": False,
            "checkpoint_evidence_status": trainer_payload.get("checkpoint_evidence_status"),
            "expected_move_after_cost_bps": trainer_payload.get("expected_move_after_cost_bps"),
            "error_blocker_state": trainer_payload.get("error_blocker_state", []),
        },
        "paper_runtime": {
            "path": payloads["paper_runtime"]["path"],
            "age_seconds": payloads["paper_runtime"]["age_seconds"],
            "fresh": (payloads["paper_runtime"]["age_seconds"] or 999999) <= STALE_MAX_SECONDS,
            "runtime_state": paper_runtime_payload.get("runtime_state"),
            "current_action": (paper_runtime_payload.get("current_risk_decision") or {}).get("action"),
        },
    }

    paper_edge = {
        "schema_version": "v2_post_copied_runtime_paper_edge_status_v3",
        **common,
        "phase": 5,
        "edge_proven": paper_edge_proven,
        "paper_shadow_observation": {
            "path": payloads["paper_shadow_observation"]["path"],
            "age_seconds": payloads["paper_shadow_observation"]["age_seconds"],
            "runtime_state": paper_payload.get("runtime_state"),
            "paper_pnl_current_usdt": paper_pnl_current,
            "profitability_proof_status": paper_payload.get("profitability_proof_status"),
            "allowed_intents": paper_payload.get("allowed_intents"),
            "blocked_intents": paper_payload.get("blocked_intents"),
            "simulated_fills": paper_payload.get("simulated_fills"),
            "windows": paper_payload.get("windows", {}),
        },
        "post_hoc_replay": {
            "path": payloads["post_hoc_replay"]["path"],
            "age_seconds": payloads["post_hoc_replay"]["age_seconds"],
            "go_no_go": post_hoc_payload.get("go_no_go"),
            "verdict": post_hoc_payload.get("verdict"),
            "verdict_reason": post_hoc_payload.get("verdict_reason"),
            "expected_move_after_cost_bps": expected_move_after_cost_bps,
            "after_cost_pnl_delta": post_hoc_payload.get("after_cost_pnl_delta"),
            "sample_count": post_hoc_payload.get("sample_count"),
            "minimum_sample_satisfied": post_hoc_payload.get("minimum_sample_satisfied"),
            "false_negative_rate": post_hoc_payload.get("false_negative_rate"),
            "false_positive_rate": post_hoc_payload.get("false_positive_rate"),
            "thresholds_satisfied": post_hoc_payload.get("thresholds_satisfied", {}),
            "operator_thresholds_set": edge_thresholds_set,
        },
        "post_filter": {
            "path": payloads["post_filter_edge"]["path"],
            "age_seconds": payloads["post_filter_edge"]["age_seconds"],
            "classification": post_filter_payload.get("classification"),
            "paper_edge_positive_proven": post_filter_payload.get("paper_edge_positive_proven"),
            "post_filter_realized_pnl_delta_usdt": post_filter_payload.get(
                "post_filter_realized_pnl_delta_usdt"
            ),
        },
        "war_room": {
            "path": payloads["war_room"]["path"],
            "age_seconds": payloads["war_room"]["age_seconds"],
            "go_no_go": war_room_payload.get("go_no_go"),
            "governor_summary": war_room_payload.get("governor_summary", {}),
        },
        "live_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "canary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    }

    ui_verification = {
        "schema_version": "v2_trading_platform_runtime_ui_verification_v3",
        **common,
        "phase": 6,
        "backend_service": services.get("ai-bot-v2-public-website-backend.service", {}),
        "current_route_probes": route_probes,
        "current_route_probe_failures": route_probe_failures,
        "current_route_probe_passed_count": sum(1 for p in route_probes if p["ok"]),
        "current_route_probe_total_count": len(route_probes),
        "prior_rendered_route_matrix": {
            "path": payloads["copied_restart_route_matrix"]["path"],
            "age_seconds": payloads["copied_restart_route_matrix"]["age_seconds"],
            "route_count": route_matrix.get("route_count"),
            "passed_count": route_matrix.get("passed_count"),
            "failed_count": route_matrix.get("failed_count"),
            "rendered_screenshot_evidence_present": bool(route_matrix.get("routes")),
            "note": (
                "This collector performs current lightweight HTTP probes. "
                "Full rendered screenshots remain in the copied-runtime restart evidence."
            ),
        },
        "execution_adapter_default": "v2_default_blocked_execution_adapter",
        "website_runtime_state_visible": not route_probe_failures,
    }

    remediation_tasks: list[dict[str, Any]] = []
    if payloads["copied_restart_route_matrix"]["age_seconds"] is not None and payloads[
        "copied_restart_route_matrix"
    ]["age_seconds"] > 24 * 3600:
        remediation_tasks.append(
            {
                "task_id": "r_rendered_route_crawl_refresh",
                "severity": "info",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "prior rendered screenshot crawl is older than 24h",
            }
        )
    if liq_xlen <= 0 and liq_events_written <= 0:
        remediation_tasks.append(
            {
                "task_id": "r_liquidation_event_warmup_diagnostic",
                "severity": "warn",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "liquidation services are running but no events have landed",
            }
        )
    if liq_levels_keys <= 0:
        remediation_tasks.append(
            {
                "task_id": "r_liquidation_levels_output_namespace_diagnostic",
                "severity": "warn",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "v2:market:liquidation_levels:* key count is zero",
            }
        )
    if not paper_edge_proven:
        remediation_tasks.append(
            {
                "task_id": "r_paper_edge_improvement_and_replay",
                "severity": "block",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "paper edge remains unproven",
            }
        )
    if not edge_thresholds_set:
        remediation_tasks.append(
            {
                "task_id": "operator_edge_thresholds_required",
                "severity": "operator_required",
                "status": "blocked_operator_required",
                "operator_gate_required": True,
                "reason": "post-hoc replay thresholds are still OPERATOR_DECISION_REQUIRED",
            }
        )
    if route_probe_failures:
        remediation_tasks.append(
            {
                "task_id": "r_trading_platform_route_probe_repair",
                "severity": "block",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "one or more current route probes failed",
            }
        )
    if inactive_required or missing_required:
        remediation_tasks.append(
            {
                "task_id": "r_runtime_service_recovery",
                "severity": "block",
                "status": "queued",
                "operator_gate_required": False,
                "reason": "required V2 paper/shadow runtime unit missing or inactive",
            }
        )

    remediation = {
        "schema_version": "v2_copied_runtime_burn_in_remediation_status_v3",
        **common,
        "phase": 7,
        "tasks": remediation_tasks,
        "summary": {
            "tasks_total": len(remediation_tasks),
            "tasks_block": sum(1 for t in remediation_tasks if t["severity"] == "block"),
            "tasks_warn": sum(1 for t in remediation_tasks if t["severity"] == "warn"),
            "tasks_info": sum(1 for t in remediation_tasks if t["severity"] == "info"),
            "tasks_operator_required": sum(
                1 for t in remediation_tasks if t["operator_gate_required"]
            ),
        },
        "safe_scoped_fixes_applied_by_collector": [
            "refreshed stale burn-in evidence artifacts",
            "published repeatable non-mutating observer outputs",
        ],
    }

    verdict_one_line = (
        "Burn-in runtime is fresh enough for observation, but live/canary stays blocked: "
        f"paper edge proven={paper_edge_proven}, liquidation events={liq_xlen}, "
        f"after-cost bps={expected_move_after_cost_bps}, paper PnL={paper_pnl_current}."
    )

    operator_dashboard = {
        "schema_version": "operator_dashboard_payload_v3",
        "milestone": TASK_ID,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "git_head": common["git_head"],
        "go_no_go": go_no_go,
        "status": "READY" if go_no_go == READY else "BLOCKED",
        "blockers": block_reasons,
        "next_action": (
            "Continue paper/shadow burn-in, diagnose liquidation event absence, "
            "improve paper edge, and wait for operator edge thresholds."
        )
        if block_reasons
        else "Maintain monitoring; this lane still does not approve live or canary.",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": old_redis_detected,
        "calls_exchange_mutation": exchange_mutation_detected,
        "places_real_order": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "verdict_one_line": verdict_one_line,
        "live_safety": safety,
        "runtime_summary": burn_in_status["runtime_summary"],
        "liquidation_summary": {
            "v2_liquidations_events_xlen": liq_xlen,
            "v2_market_liquidation_levels_key_count": liq_levels_keys,
            "events_received": liq_events_received,
            "events_written": liq_events_written,
            "bridge_active": services.get("ai-bot-v2-liquidation-bridge.service", {}).get("active"),
            "levels_active": services.get("ai-bot-v2-liquidation-levels-engine.service", {}).get(
                "active"
            ),
            "wss_active": services.get("ai-bot-v2-liquidation-wss-paper-shadow.service", {}).get(
                "active"
            ),
            "operational_proof_status": liquidation_impact["operational_proof_status"],
        },
        "symbol_summary": {
            "resolved_count": symbol_evidence["resolved_count"],
            "dynamic_discovered_count": len(discovered_symbols),
            "baseline_25_retained": symbol_evidence["baseline_25_retained"],
            "profile": symbol_evidence["symbol_profile"],
            "live_symbols_count": 0,
            "btc_only_default_in_active_runtime_lanes": False,
            "btc_eth_sol_only_default_in_active_runtime_lanes": False,
        },
        "feature_ta_trainer_summary": {
            "v2_market_keys": counts.get("v2:market:*", 0),
            "v2_features_keys": counts.get("v2:features:*", 0),
            "v2_unified_features_keys": counts.get("v2:unified_features:*", 0),
            "v2_predictions_keys": counts.get("v2:prediction:*", 0),
            "feature_snapshot_fresh": feature_ta_trainer["feature_snapshot"]["fresh"],
            "trainer_role_label": "copied_parity_baseline_bridge",
            "trainer_fresh": feature_ta_trainer["trainer"]["fresh"],
        },
        "edge_summary": {
            "paper_edge_proven": paper_edge_proven,
            "paper_pnl_current_usdt": paper_pnl_current,
            "profitability_proof_status": paper_payload.get("profitability_proof_status"),
            "expected_move_after_cost_bps": expected_move_after_cost_bps,
            "sample_count": post_hoc_payload.get("sample_count"),
            "minimum_sample_satisfied": post_hoc_payload.get("minimum_sample_satisfied"),
            "post_hoc_verdict": post_hoc_payload.get("verdict"),
            "live_recommendation": paper_edge["live_recommendation"],
            "canary_recommendation": paper_edge["canary_recommendation"],
        },
        "ui_summary": {
            "current_route_probe_passed_count": ui_verification["current_route_probe_passed_count"],
            "current_route_probe_total_count": ui_verification["current_route_probe_total_count"],
            "prior_rendered_route_count": ui_verification["prior_rendered_route_matrix"].get(
                "route_count"
            ),
            "prior_rendered_failed_count": ui_verification["prior_rendered_route_matrix"].get(
                "failed_count"
            ),
            "execution_adapter_default": "v2_default_blocked_execution_adapter",
        },
        "remediation_summary": remediation["summary"],
        "block_reasons": block_reasons,
        "artifact_index": {
            "burn_in_status": "v2_copied_runtime_burn_in_status.json",
            "liquidation_impact": "v2_liquidation_bridge_levels_runtime_impact.json",
            "dynamic_symbols": "v2_dynamic_symbol_runtime_evidence.json",
            "feature_ta_trainer": "v2_feature_ta_trainer_runtime_impact.json",
            "paper_edge": "v2_post_copied_runtime_paper_edge_status.json",
            "trading_platform_ui": "v2_trading_platform_runtime_ui_verification.json",
            "remediation": "v2_copied_runtime_burn_in_remediation_status.json",
            "go_no_go": "GO_NO_GO.md",
            "report": "V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_REPORT.md",
        },
    }

    artifacts = {
        "v2_copied_runtime_burn_in_status.json": burn_in_status,
        "v2_liquidation_bridge_levels_runtime_impact.json": liquidation_impact,
        "v2_dynamic_symbol_runtime_evidence.json": dynamic_symbols,
        "v2_feature_ta_trainer_runtime_impact.json": feature_ta_trainer,
        "v2_post_copied_runtime_paper_edge_status.json": paper_edge,
        "v2_trading_platform_runtime_ui_verification.json": ui_verification,
        "v2_copied_runtime_burn_in_remediation_status.json": remediation,
        "operator_dashboard_payload.json": operator_dashboard,
    }

    for name, payload in artifacts.items():
        write_json(name, payload)
    write_text("GO_NO_GO.md", go_no_go + "\n")

    report = render_report(operator_dashboard, generated_est)
    write_text("V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_REPORT.md", report)

    (RAW / "systemd_services.json").write_text(json.dumps(services, indent=2, sort_keys=True) + "\n")
    (RAW / "systemd_timers.json").write_text(json.dumps(timer_units, indent=2) + "\n")
    (RAW / "redis_family_counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
    (RAW / "process_safety_scan.json").write_text(
        json.dumps(proc_scan, indent=2, sort_keys=True) + "\n"
    )
    collector_source = Path(__file__).read_text()
    (RAW / "build_artifacts.py").write_text(collector_source)
    (RAW / "build_artifacts_dynamic.py").write_text(collector_source)

    return operator_dashboard


def render_report(payload: dict[str, Any], generated_est: str) -> str:
    rs = payload["runtime_summary"]
    ls = payload["liquidation_summary"]
    ss = payload["symbol_summary"]
    es = payload["edge_summary"]
    us = payload["ui_summary"]
    reasons = payload["block_reasons"]
    reason_lines = "\n".join(f"- `{reason}`" for reason in reasons) or "- none"
    return f"""# V2 Copied Runtime Burn-In and Paper-Edge Improvement - Snapshot Report

- **Task ID**: `{TASK_ID}`
- **Generated EST**: {generated_est}
- **GO/NO-GO**: `{payload['go_no_go']}`
- **Live gate**: `blocked_human_only`
- **Live symbols**: `[]`

## Status

{payload['verdict_one_line']}

## Runtime

- Active V2 services: {rs['active_ai_bot_v2_user_services_count']} / {rs['loaded_ai_bot_v2_user_services_count']}
- Active V2 timers: {rs['active_ai_bot_v2_user_timers_count']}
- Minimum required runtime uptime: {rs['min_required_runtime_uptime_hours']}h
- Minimum copied-component uptime: {rs['min_copied_component_uptime_hours']}h
- Burn-in windows: 1h={rs['burn_in_windows']['1h']}, 6h={rs['burn_in_windows']['6h']}, 12h={rs['burn_in_windows']['12h']}

## Liquidation Bridge / Levels

- Bridge active: {ls['bridge_active']}
- Levels active: {ls['levels_active']}
- WSS active: {ls['wss_active']}
- `v2:liquidations:events` XLEN: {ls['v2_liquidations_events_xlen']}
- `v2:market:liquidation_levels:*` keys: {ls['v2_market_liquidation_levels_key_count']}
- Operational proof: `{ls['operational_proof_status']}`

## Symbols / Features / Trainer

- Dynamic symbols resolved: {ss['resolved_count']}
- Dynamic discovered symbols: {ss['dynamic_discovered_count']}
- 25-symbol baseline retained: {ss['baseline_25_retained']}
- Symbol profile: `{ss['profile']}`
- Trainer role: `copied_parity_baseline_bridge`

## Paper Edge

- Paper edge proven: {es['paper_edge_proven']}
- Paper PnL: {es['paper_pnl_current_usdt']}
- After-cost expectancy bps: {es['expected_move_after_cost_bps']}
- Post-hoc verdict: `{es['post_hoc_verdict']}`
- Live recommendation: `{es['live_recommendation']}`

## Trading Platform

- Current HTTP probes: {us['current_route_probe_passed_count']} / {us['current_route_probe_total_count']} passed
- Prior rendered route crawl: {us['prior_rendered_route_count']} routes, {us['prior_rendered_failed_count']} failed
- Execution adapter: `{us['execution_adapter_default']}`

## Block Reasons

{reason_lines}

## Safety

No live/canary/shutdown/Redis-trim approval was created. No exchange mutation,
order endpoint, leverage, or margin path was invoked. Legacy root runtime was
not restarted.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    payload = build_artifacts()
    if args.print_summary:
        print(json.dumps({
            "go_no_go": payload["go_no_go"],
            "block_reasons": payload["block_reasons"],
            "generated_est": payload["generated_est"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
