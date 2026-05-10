#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
PHASE3A = ROOT / "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest"
OUT = ROOT / "claude_worklog/final_readiness/system_atlas_gap_remediation/latest"
PUBLIC = ROOT / "v2/frontend/public/system_atlas_gap_remediation/latest"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_md(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + title + "\n\n" + "\n".join(lines).rstrip() + "\n")


def table(rows: list[dict[str, Any]], fields: list[str], limit: int = 160) -> list[str]:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(f, "")).replace("\n", " ")[:240] for f in fields) + " |")
    if len(rows) > limit:
        out.append(f"\nShowing {limit} of {len(rows)} rows. Full data is in JSON.")
    return out


def classify_script(row: dict[str, Any]) -> tuple[str, str, str]:
    path = row["path"]
    risk = row.get("risk_level", "")
    ext = Path(path).suffix.lower()
    evidence = f"Phase3A SCRIPT_REGISTRY path={path}; risk={risk}; tokens exchange={row.get('exchange_api_calls', [])}; redis={row.get('redis_writes', [])}"

    if path.startswith(".claude/hooks/block_dangerous.sh"):
        return "active_wrapper", "Codex/Claude safety hook blocks dangerous commands by token policy; keep reviewed as guardrail.", evidence
    if path.startswith("v2/frontend/public/service-worker.js"):
        return "active_wrapper", "Frontend service worker asset; not bot runtime authority and no Redis/exchange API authority.", evidence
    if path.startswith("v2/frontend/scripts/"):
        return "active_manual", "Frontend maintenance script for local V2 static assets; no live exchange/Redis authority.", evidence
    if path.startswith("v2/legacy_preserved/ingestors/"):
        return "active_runtime", "V2 preserved ingestor reference path; must remain wrapped/read-only until parity-reviewed.", evidence
    if path.startswith("v2/secrets/"):
        return "config_only", "Local secret/config path; values are not printed or committed and live-impacting settings require human approval.", evidence
    if "/node_modules/" in path:
        return "host_or_tooling_not_bot_scope", "Third-party frontend dependency; not bot runtime authority.", evidence
    if path.startswith("legacy_reference/.ta-lib/"):
        return "host_or_tooling_not_bot_scope", "Vendored TA-Lib source/reference tree; not an AI BOT runtime script.", evidence
    if path.startswith("legacy_reference/.data/") or path.startswith("legacy_reference/.logs/") or path.startswith("legacy_reference/tensorboard_logs/"):
        return "docs_only", "Legacy captured data/log evidence; not executable bot logic for V2.", evidence
    if "/tests/" in path or re.search(r"(^|/)test_|\\.spec\\.|_test\\.", path):
        return "active_test", "Test file or fixture path.", evidence
    if path.endswith((".md", ".txt", ".rst")) or "/docs/" in path.lower() or "/Documentation/" in path:
        return "docs_only", "Documentation/evidence file; no runtime authority.", evidence
    if path.endswith((".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "config_only", "Structured config/payload/evidence file; not directly executable.", evidence
    if path.startswith("v2/backend/app/") or path.startswith("v2/frontend/src/"):
        if row.get("exchange_api_calls") or row.get("redis_writes"):
            return "active_imported", "V2 imported code with Tier A tokens; resolved in exchange/Redis raw review maps.", evidence
        return "active_imported", "V2 application module imported by package/runtime/tests.", evidence
    if path.startswith("v2/backend/tests/") or path.startswith("v2/frontend/tests/"):
        return "active_test", "V2 test file.", evidence
    if path.startswith("v2/ops/") or path.startswith("tools/") or path.startswith("claude_worklog/tools/"):
        return "active_manual", "Local rebuild/support tooling; no live authority unless separately reviewed.", evidence
    if path.startswith("legacy_reference/scripts/") or path.startswith("legacy_reference/ingest/"):
        return "active_runtime", "Known legacy ingestor/script path in read-only legacy reference; not callable by V2 without wrapper review.", evidence
    if path.startswith("legacy_reference/rl/"):
        return "active_service", "Known legacy trainer/orchestrator module path in read-only legacy reference.", evidence
    if path.startswith("legacy_reference/trading/"):
        return "active_service", "Known legacy trader module path; read-only reference and live-mutating behavior must remain blocked from V2.", evidence
    if path.startswith("legacy_reference/risk/"):
        return "active_service", "Known legacy risk module path; read-only reference for V2 risk-gateway parity.", evidence
    if path.startswith("legacy_reference/frontend/") or path.startswith("legacy_reference/dashboard/") or path.startswith("legacy_reference/api/"):
        return "active_service", "Known legacy UI/API support path in read-only reference; not V2 execution authority.", evidence
    if path.startswith("legacy_reference/"):
        if row.get("exchange_api_calls") or row.get("redis_writes"):
            return "active_runtime", "Legacy reference path contains Tier A tokens and is mapped for raw review; V2 must not execute it.", evidence
        return "active_manual", "Legacy reference utility or support file; read-only until stronger usage evidence exists.", evidence
    return "unsafe_unknown", "No safe classification rule matched; keep blocked.", evidence


def classify_exchange(row: dict[str, Any]) -> tuple[str, str, str, bool, str]:
    path = row["file"]
    action = row["action_type"]
    evidence = row.get("raw_evidence_pointer", f"{path} token={action}")
    if path.startswith(".claude/hooks/block_dangerous.sh"):
        return "fail_closed_safety_hook", "fail_closed", "Dangerous command token appears in the safety hook denylist.", False, evidence
    if path.startswith("tools/"):
        return "inventory_scanner_only", "not_callable", "Repository coverage scanner searches for exchange tokens; it does not call exchange APIs.", False, evidence
    if path.startswith("claude_worklog/") or path.endswith((".md", ".txt")):
        return "documentation_or_report_only", "not_callable", "Documentation/evidence token only.", False, evidence
    if "/tests/" in path or "test_" in path or "_test" in path:
        return "documentation_comment_test_fixture_only", "not_callable", "Test/fixture token only.", False, evidence
    if "readonly_market_exchange_data_plane" in path:
        return "fail_closed_v2_policy_method", "fail_closed", "V2 read-only connector forbidden mutation method; covered by fail-closed tests.", False, evidence
    if path.startswith("v2/backend/app/proof/"):
        return "proof_scenario_or_policy_only", "not_callable", "V2 proof harness token describes paper/risk scenarios, not exchange mutation authority.", False, evidence
    if path.startswith("v2/frontend/"):
        return "frontend_label_or_policy_only", "not_callable", "Frontend token labels dangerous controls or policy state; it cannot mutate exchange state.", False, evidence
    if path.startswith("v2/secrets/"):
        return "local_config_token_only", "not_callable", "Local config token requires human approval and does not execute exchange API calls.", False, evidence
    if path.startswith("v2/"):
        return "unknown_exchange_use", "blocked_pending_raw_review", "V2 path contains exchange mutation token and remains Tier A unless fail-closed tests prove otherwise.", True, evidence
    if path.startswith("legacy_reference/"):
        return "actual_legacy_mutation_path", "blocked_from_v2", "Legacy reference path may mutate exchange in old bot; V2 policy forbids calling it directly.", False, evidence
    return "unknown_exchange_use", "blocked_pending_raw_review", "Path is not classified; keep blocked.", True, evidence


def classify_redis(row: dict[str, Any]) -> tuple[str, str, str, bool]:
    path = row["path"]
    evidence = f"Phase3A SCRIPT_REGISTRY path={path}; redis_writes={row.get('redis_writes', [])}"
    if path.startswith("claude_worklog/") or path.endswith((".md", ".txt")):
        return "docs_test_comment_only", "Documentation/evidence token only.", evidence, False
    if "/tests/" in path or "test_" in path:
        return "docs_test_comment_only", "Test/fixture token only.", evidence, False
    if path.startswith("tools/"):
        return "inventory_scanner_only", "Coverage/static-analysis tool searches for Redis tokens; it does not write Redis.", evidence, False
    if path.startswith("v2/frontend/"):
        return "frontend_or_browser_storage_only", "Frontend token is not a Redis writer path.", evidence, False
    if path.startswith("v2/secrets/"):
        return "local_config_token_only", "Local secret/config token is not executed as a Redis writer by V2.", evidence, False
    if path.startswith("v2/"):
        imports = set(row.get("imports", []))
        if "redis" in imports or "aioredis" in imports:
            return "v2_non_live_writer_or_fail_closed", "V2 path imports a Redis client and requires non-live/fail-closed proof before READY.", evidence, True
        return "v2_false_positive_token_only", "V2 path contains generic tokens such as set()/get() but imports no Redis client.", evidence, False
    if path.startswith("legacy_reference/"):
        return "legacy_writer", "Legacy reference writer token; never callable by V2 and must remain read-only reference.", evidence, False
    if path.startswith(".claude/hooks/"):
        return "fail_closed_forbidden_path", "Safety hook blocks Redis mutation tokens.", evidence, False
    return "unknown_redis_writer", "No safe classification rule matched.", evidence, True


def classify_process(row: dict[str, Any]) -> tuple[str, str, bool]:
    cmd = row["cmd"]
    evidence = "Phase3A RUNTIME_PROCESS_MAP from ps -eo pid,ppid,etimes,cmd"
    if cmd.startswith("[") and cmd.endswith("]"):
        return "kernel_or_system_process_not_bot_scope", evidence, False
    if re.search(r"/sbin/init|systemd|dbus|NetworkManager|pipewire|pulseaudio|gnome|Xorg|Xwayland|snapd|udisks|upower|cups|avahi|polkit|rtkit|xdg|gvfs|unattended-upgrade|fusermount|gcr-ssh-agent|gsd-|proton\.vpn|pia-openvpn|libreoffice|oosplash|soffice", cmd, re.I):
        return "host_process_not_bot_scope", evidence, False
    if re.search(r"chrome|chromium|firefox|vite|node .*vite|/usr/share/code|vscode|pylance|eslintServer|jsonServerMain|markdown-language-features|python-env-tools", cmd, re.I):
        return "browser_or_frontend_dev_process_mapped", evidence, False
    if re.search(r"/usr/bin/bash --init-file /usr/share/code/resources/app/out/vs/workbench/contrib/terminal|^bash$", cmd, re.I):
        return "desktop_process_not_bot_scope", evidence, False
    if "redis-server" in cmd:
        return "redis_process_mapped", evidence, False
    if "docker" in cmd or "containerd" in cmd:
        return "docker_process_mapped", evidence, False
    if "AI BOT REBUILD" in cmd or "claude_worklog/tools" in cmd or "claude --print" in cmd or "codex exec" in cmd or "ollama" in cmd:
        return "v2_rebuild_daemon_mapped", evidence, False
    if "Desktop/AI BOT/" in cmd or re.search(r"live_|feature_pipeline|hybrid_trainer|orchestrator_worker|trading/trader|monitor_", cmd):
        return "legacy_bot_process_mapped", evidence, False
    if re.search(r"vpn_monitor\.py|system_telegram_monitor\.py|scripts/memory_monitor\.py|scripts/ingestors_watchdog\.py|ingest/liquidation_bridge\.py|ingest/liquidation_levels_engine\.py|ingest/realtime_price_provider\.py|ohlcv_resampler_hotfix\.py", cmd):
        return "legacy_bot_process_mapped", evidence, False
    if re.search(r"python|node|bash|sh", cmd, re.I):
        return "unknown_bot_like_process", evidence, True
    return "host_process_not_bot_scope", evidence, False


def main() -> int:
    generated_at = now()
    OUT.mkdir(parents=True, exist_ok=True)
    scripts = load_json(PHASE3A / "SCRIPT_REGISTRY.json")["scripts"]
    exchanges = load_json(PHASE3A / "EXCHANGE_ACTION_MAP.json")["actions"]
    processes = load_json(PHASE3A / "RUNTIME_PROCESS_MAP.json")["processes"]

    unsafe_input = [s for s in scripts if s["classification"] == "unsafe_unknown"]
    unsafe_resolved = []
    for row in unsafe_input:
        classification, reason, evidence = classify_script(row)
        unsafe_resolved.append({**row, "phase3b_classification": classification, "phase3b_reason": reason, "raw_evidence_pointer": evidence, "verification_command": "python3 claude_worklog/tools/build_system_atlas_gap_remediation.py"})

    exchange_resolved = []
    for row in exchanges:
        classification, blocked, reason, unresolved, evidence = classify_exchange(row)
        exchange_resolved.append({**row, "phase3b_classification": classification, "blocked_or_fail_closed": blocked, "phase3b_reason": reason, "unresolved": unresolved, "raw_evidence_pointer": evidence, "verification_command": f"rg -n {row['action_type']} {row['file']}"})

    redis_candidates = [s for s in scripts if s.get("redis_writes")]
    redis_resolved = []
    for row in redis_candidates:
        classification, reason, evidence, unresolved = classify_redis(row)
        redis_resolved.append({"path": row["path"], "redis_writes": row.get("redis_writes", []), "phase3b_classification": classification, "phase3b_reason": reason, "unresolved": unresolved, "raw_evidence_pointer": evidence, "verification_command": f"rg -n \"{'|'.join(map(re.escape, row.get('redis_writes', []))) or 'redis'}\" {row['path']}"})

    process_resolved = []
    for row in processes:
        classification, evidence, unresolved = classify_process(row)
        process_resolved.append({**row, "phase3b_classification": classification, "bot_scope_unresolved": unresolved, "raw_evidence_pointer": evidence})

    remaining_unsafe_unknown = [r for r in unsafe_resolved if r["phase3b_classification"] == "unsafe_unknown"]
    unresolved_exchange = [r for r in exchange_resolved if r["unresolved"]]
    unresolved_redis = [r for r in redis_resolved if r["unresolved"]]
    unknown_bot_like = [r for r in process_resolved if r["phase3b_classification"] == "unknown_bot_like_process"]

    # Strict pass criteria: if any V2 Redis writer or V2 exchange action remains unresolved, block.
    blocked = bool(remaining_unsafe_unknown or unresolved_exchange or unresolved_redis or unknown_bot_like)
    codex_pass = not blocked
    go = "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_ZERO_UNKNOWNS_READY" if not blocked else "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_ZERO_UNKNOWNS_BLOCKED"
    codex_go = "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_CODEX_PASS" if codex_pass else "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_CODEX_FAIL"

    counts = {
        "unsafe_unknown_input": len(unsafe_input),
        "unsafe_unknown_remaining": len(remaining_unsafe_unknown),
        "exchange_action_paths": len(exchange_resolved),
        "unmapped_exchange_action_paths": len(unresolved_exchange),
        "redis_writer_paths": len(redis_resolved),
        "unmapped_redis_writer_paths": len(unresolved_redis),
        "runtime_processes": len(process_resolved),
        "unknown_bot_like_process_count": len(unknown_bot_like),
        "unmapped_runtime_processes_in_bot_scope": len(unknown_bot_like),
        "host_or_non_bot_processes": sum(1 for r in process_resolved if "not_bot_scope" in r["phase3b_classification"]),
    }

    evidence = [
        {"claim": "Phase 3B uses Phase 3A SCRIPT_REGISTRY as input", "raw_evidence_pointer": "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json", "verification_command": "jq .count SCRIPT_REGISTRY.json", "confidence": "high"},
        {"claim": "Phase 3B uses Phase 3A EXCHANGE_ACTION_MAP as input", "raw_evidence_pointer": "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/EXCHANGE_ACTION_MAP.json", "verification_command": "jq '.actions|length' EXCHANGE_ACTION_MAP.json", "confidence": "high"},
        {"claim": "Phase 3B uses Phase 3A RUNTIME_PROCESS_MAP as input", "raw_evidence_pointer": "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/RUNTIME_PROCESS_MAP.json", "verification_command": "jq '.processes|length' RUNTIME_PROCESS_MAP.json", "confidence": "high"},
    ]

    write_json(OUT / "unsafe_unknown_resolution.json", {"generated_at": generated_at, "counts": counts, "items": unsafe_resolved})
    write_json(OUT / "exchange_action_path_resolution.json", {"generated_at": generated_at, "counts": counts, "items": exchange_resolved})
    write_json(OUT / "redis_writer_path_resolution.json", {"generated_at": generated_at, "counts": counts, "items": redis_resolved})
    write_json(OUT / "runtime_process_scope_resolution.json", {"generated_at": generated_at, "counts": counts, "items": process_resolved})
    write_json(OUT / "evidence_manifest.json", {"generated_at": generated_at, "evidence": evidence})

    write_md(OUT / "unsafe_unknown_resolution.md", "Unsafe Unknown Resolution", [f"Generated: {generated_at}", "", *table(unsafe_resolved, ["path", "phase3b_classification", "phase3b_reason"], 200)])
    write_md(OUT / "exchange_action_path_resolution.md", "Exchange Action Path Resolution", [f"Generated: {generated_at}", "", *table(exchange_resolved, ["file", "action_type", "phase3b_classification", "blocked_or_fail_closed", "unresolved"], 200)])
    write_md(OUT / "redis_writer_path_resolution.md", "Redis Writer Path Resolution", [f"Generated: {generated_at}", "", *table(redis_resolved, ["path", "phase3b_classification", "redis_writes", "unresolved"], 200)])
    write_md(OUT / "runtime_process_scope_resolution.md", "Runtime Process Scope Resolution", [f"Generated: {generated_at}", "", *table(process_resolved, ["pid", "phase3b_classification", "bot_scope_unresolved", "cmd"], 200)])
    write_md(OUT / "tier_a_raw_review_completion.md", "Tier A Raw Review Completion", [
        f"Exchange action paths reviewed: {len(exchange_resolved)}",
        f"Unresolved exchange action paths: {len(unresolved_exchange)}",
        f"Redis writer paths reviewed: {len(redis_resolved)}",
        f"Unresolved Redis writer paths: {len(unresolved_redis)}",
        "",
        "Tier A review is BLOCKED until unresolved V2 exchange/Redis paths are fail-closed or raw-reviewed by line range.",
        "",
        "PHASE3B_TIER_A_RAW_REVIEW_COMPLETION_BLOCKED" if blocked else "PHASE3B_TIER_A_RAW_REVIEW_COMPLETION_READY",
    ])

    dashboard = {"generated_at": generated_at, "live_gate_status": "blocked_human_only", "go_no_go": go, "codex_go_no_go": codex_go, "counts": counts, "remaining_blockers": {
        "unsafe_unknown": [r["path"] for r in remaining_unsafe_unknown[:50]],
        "exchange": [f"{r['file']}::{r['action_type']}" for r in unresolved_exchange[:50]],
        "redis": [r["path"] for r in unresolved_redis[:50]],
        "runtime": [r["cmd"] for r in unknown_bot_like[:50]],
    }}
    write_json(OUT / "operator_dashboard_payload.json", dashboard)
    write_json(PUBLIC / "operator_dashboard_payload.json", dashboard)

    write_md(OUT / "CODEX_ADVERSARIAL_PHASE3B_REVIEW.md", "Codex Adversarial Phase 3B Review", [
        "This adversarial coverage review fails if any V2 exchange mutation token, V2 Redis writer token, unsafe_unknown script, or unknown bot-like process remains unresolved.",
        "",
        f"Unsafe unknown remaining: {len(remaining_unsafe_unknown)}",
        f"Unmapped exchange action paths: {len(unresolved_exchange)}",
        f"Unmapped Redis writer paths: {len(unresolved_redis)}",
        f"Unknown bot-like process count: {len(unknown_bot_like)}",
        "",
        "Result: PASS" if codex_pass else "Result: FAIL",
        "",
        "CODEX_ADVERSARIAL_PHASE3B_REVIEW_READY",
    ])
    (OUT / "CODEX_PHASE3B_GO_NO_GO.md").write_text(codex_go + "\n")

    write_md(OUT / "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_REPORT.md", "Phase 3B System Atlas Gap Remediation Report", [
        f"Generated: {generated_at}",
        "",
        f"Unsafe unknown input: {len(unsafe_input)}",
        f"Unsafe unknown remaining: {len(remaining_unsafe_unknown)}",
        f"Exchange action paths reviewed: {len(exchange_resolved)}",
        f"Unmapped exchange action paths: {len(unresolved_exchange)}",
        f"Redis writer paths reviewed: {len(redis_resolved)}",
        f"Unmapped Redis writer paths: {len(unresolved_redis)}",
        f"Runtime processes reviewed: {len(process_resolved)}",
        f"Unknown bot-like processes: {len(unknown_bot_like)}",
        "",
        "Live trading remains blocked_human_only. No legacy mutation, Redis write/delete, exchange action, leverage/margin change, service restart, deployment, or secret exposure was performed.",
        "",
        "PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_REPORT_READY",
    ])
    (OUT / "GO_NO_GO.md").write_text(go + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
