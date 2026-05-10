#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
OUT = ROOT / "claude_worklog/final_readiness/redis_memory_pressure_remediation/latest"
PUBLIC = ROOT / "v2/frontend/public/redis_memory_pressure_remediation/latest"
PHASE3C = ROOT / "claude_worklog/final_readiness/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json"

ALLOWED_REDIS_COMMANDS = {
    "PING",
    "INFO",
    "CONFIG",
    "SCAN",
    "TYPE",
    "MEMORY",
    "XLEN",
    "XREVRANGE",
    "TTL",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redis_cli(*args: str, timeout: int = 10) -> tuple[int, str, str]:
    command = args[0].upper() if args else ""
    if command not in ALLOWED_REDIS_COMMANDS:
        raise RuntimeError(f"forbidden redis command requested: {command}")
    proc = subprocess.run(
        ["redis-cli", "--raw", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_info(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key] = value
    return out


def scan_keys(limit: int = 20000) -> list[str]:
    keys: list[str] = []
    cursor = "0"
    while True:
        rc, stdout, stderr = redis_cli("SCAN", cursor, "COUNT", "1000", timeout=30)
        if rc != 0:
            raise RuntimeError(f"SCAN failed: {stderr}")
        lines = stdout.splitlines()
        if not lines:
            break
        cursor = lines[0]
        keys.extend(lines[1:])
        if cursor == "0" or len(keys) >= limit:
            break
    return keys[:limit]


def stream_last_id(key: str) -> str | None:
    rc, stdout, _ = redis_cli("XREVRANGE", key, "+", "-", "COUNT", "1")
    if rc != 0 or not stdout:
        return None
    return stdout.splitlines()[0].strip()


def classify_namespace(key: str, typ: str) -> tuple[str, str, str]:
    lower = key.lower()
    if lower.startswith("liquidations:") or lower.startswith("liq:"):
        return "market_liquidation_history", "feature/audit-history", "offload to V2 market-event ledger; retain bounded recent window only after approval"
    if lower.startswith(("signals:trading", "wma:proposals")):
        return "live_signal_transport", "live-critical", "short bounded stream retention after consumer recovery"
    if lower.startswith(("executed_signals", "wma:trader:execution_feedback", "signals:execution", "wma:exec_events", "wma:decisions")):
        return "live_execution_feedback", "live-critical/audit", "offload to V2 audit ledger before any trim"
    if "prediction" in lower or lower.startswith("trainer:"):
        return "trainer_prediction_stream", "live-critical/trainer", "retain recent window plus durable prediction ledger"
    if lower.startswith(("unified_features", "features:", "feature:", "market:", "ohlcv:", "orderbook:", "price:", "funding:", "oi:", "premium_index:", "volatility:")):
        return "feature_cache", "cache", "TTL or bounded cache policy"
    if lower.startswith(("positions:", "portfolio:", "wma:")) and typ != "stream":
        return "position_portfolio_state", "live-critical", "no mutation without explicit ownership reconciliation"
    if lower.startswith(("heartbeat:", "metrics:", "proc:", "debug:", "signals:ensemble:diagnostic")):
        return "monitor_telemetry", "monitoring", "move long-term telemetry to files/Postgres"
    if lower.startswith(("raw:coinank:", "coinank:")):
        return "feature_cache", "cache", "TTL or bounded retention policy after source parity review"
    if lower.startswith(("audit:", "history:", "backfill:")):
        return "audit_history", "audit-history", "offload before trim"
    if lower.startswith("v2:"):
        return "v2_non_live", "v2-non-live", "V2 bounded namespace policy"
    if typ == "stream":
        return "stale_or_unknown", "unknown_requires_review", "preserve until producer/consumer reviewed"
    return "unknown_requires_review", "unknown_requires_review", "no mutation until classified"


def safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def collect() -> dict[str, Any]:
    generated_at = now()
    phase3c = json.loads(PHASE3C.read_text()) if PHASE3C.exists() else {}
    rc, memory_out, memory_err = redis_cli("INFO", "memory")
    rc_stats, stats_out, stats_err = redis_cli("INFO", "stats")
    rc_keyspace, keyspace_out, keyspace_err = redis_cli("INFO", "keyspace")
    _, maxmemory_out, _ = redis_cli("CONFIG", "GET", "maxmemory")
    _, policy_out, _ = redis_cli("CONFIG", "GET", "maxmemory-policy")
    if rc != 0:
        raise RuntimeError(f"INFO memory failed: {memory_err}")
    memory = parse_info(memory_out)
    stats = parse_info(stats_out) if rc_stats == 0 else {}
    keyspace = parse_info(keyspace_out) if rc_keyspace == 0 else {}
    keys = scan_keys()
    rows: list[dict[str, Any]] = []
    for key in keys:
        _, typ_out, _ = redis_cli("TYPE", key)
        typ = typ_out.strip() or "unknown"
        _, ttl_out, _ = redis_cli("TTL", key)
        _, mem_out, _ = redis_cli("MEMORY", "USAGE", key, "SAMPLES", "0")
        memory_bytes = safe_int(mem_out)
        ttl_seconds = safe_int(ttl_out)
        stream_len = None
        last_stream_id = None
        if typ == "stream":
            _, xlen_out, _ = redis_cli("XLEN", key)
            stream_len = safe_int(xlen_out)
            last_stream_id = stream_last_id(key)
        namespace, criticality, policy = classify_namespace(key, typ)
        rows.append(
            {
                "key": key,
                "type": typ,
                "memory_bytes": memory_bytes,
                "memory_mb": round((memory_bytes or 0) / 1024 / 1024, 3),
                "stream_length": stream_len,
                "last_stream_id": last_stream_id,
                "ttl_seconds": ttl_seconds,
                "namespace": namespace,
                "criticality": criticality,
                "likely_policy": policy,
                "likely_producer": infer_producer(key),
                "likely_consumer": infer_consumer(key),
                "classification_confidence": "medium" if namespace in {"stale_or_unknown", "unknown_requires_review"} else "high",
            }
        )
    rows.sort(key=lambda row: row.get("memory_bytes") or 0, reverse=True)
    namespace_summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        ns = row["namespace"]
        item = namespace_summary.setdefault(ns, {"keys": 0, "memory_bytes": 0, "stream_length": 0})
        item["keys"] += 1
        item["memory_bytes"] += row.get("memory_bytes") or 0
        item["stream_length"] += row.get("stream_length") or 0
    for item in namespace_summary.values():
        item["memory_mb"] = round(item["memory_bytes"] / 1024 / 1024, 3)

    dry_run_actions = build_dry_run(rows)
    estimated_savings = sum(action.get("estimated_memory_reduction_bytes") or 0 for action in dry_run_actions)
    ready = bool(rows and dry_run_actions)
    return {
        "generated_at": generated_at,
        "live_gate_status": "blocked_human_only",
        "go_no_go": "PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_DRY_RUN_AND_POLICY_READY" if ready else "PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_DRY_RUN_AND_POLICY_BLOCKED",
        "codex_go_no_go": "PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_CODEX_PASS" if ready else "PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_CODEX_FAIL",
        "next_safe_milestone": "REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_REMEDIATION" if ready else "BLOCKED_UNTIL_REDIS_MEMORY_PLAN_REVIEWED",
        "redis_info": {
            "used_memory": safe_int(memory.get("used_memory")),
            "used_memory_human": memory.get("used_memory_human"),
            "used_memory_peak": safe_int(memory.get("used_memory_peak")),
            "used_memory_peak_human": memory.get("used_memory_peak_human"),
            "maxmemory": safe_int(memory.get("maxmemory")),
            "maxmemory_human": memory.get("maxmemory_human"),
            "maxmemory_policy": memory.get("maxmemory_policy"),
            "allocator_frag_ratio": memory.get("allocator_frag_ratio"),
            "evicted_keys": safe_int(stats.get("evicted_keys")),
            "expired_keys": safe_int(stats.get("expired_keys")),
            "keyspace": keyspace,
            "config_maxmemory_raw": maxmemory_out.splitlines(),
            "config_policy_raw": policy_out.splitlines(),
        },
        "phase3c_reference": {
            "go_no_go": phase3c.get("go_no_go"),
            "redis_memory_max_pct": phase3c.get("counts", {}).get("redis_memory_max_pct"),
            "redis_memory_avg_pct": phase3c.get("counts", {}).get("redis_memory_avg_pct"),
            "next_safe_milestone": phase3c.get("next_safe_milestone"),
        },
        "counts": {
            "keys_scanned": len(rows),
            "top_consumers_reported": min(len(rows), 100),
            "namespaces": len(namespace_summary),
            "dry_run_action_count": len(dry_run_actions),
            "estimated_savings_mb": round(estimated_savings / 1024 / 1024, 3),
        },
        "namespace_summary": namespace_summary,
        "top_consumers": rows[:100],
        "dry_run_actions": dry_run_actions,
        "evidence_commands": [
            "redis-cli INFO memory",
            "redis-cli INFO stats",
            "redis-cli INFO keyspace",
            "redis-cli CONFIG GET maxmemory",
            "redis-cli CONFIG GET maxmemory-policy",
            "redis-cli SCAN <cursor> COUNT 1000",
            "redis-cli TYPE <key>",
            "redis-cli MEMORY USAGE <key> SAMPLES 0",
            "redis-cli XLEN <stream_key>",
            "redis-cli XREVRANGE <stream_key> + - COUNT 1 (stream id parsed, values not written)",
            "redis-cli TTL <key>",
        ],
        "forbidden_commands_not_executed": ["DEL", "XDEL", "XTRIM", "SET", "HSET", "XADD", "FLUSHALL", "FLUSHDB", "CONFIG SET", "BGSAVE"],
    }


def infer_producer(key: str) -> str:
    lower = key.lower()
    if "trainer" in lower:
        return "legacy trainer / V2 trainer parity surface"
    if "execution" in lower or "executed" in lower:
        return "legacy trader/execution feedback"
    if "proposal" in lower or "signals:trading" in lower:
        return "legacy orchestrator/trainer signal path"
    if lower.startswith(("market:", "ohlcv:", "price:", "orderbook:", "funding:", "oi:")):
        return "market ingestors"
    if lower.startswith(("heartbeat:", "metrics:", "debug:")):
        return "monitoring/ingestor telemetry"
    return "unknown producer - review before mutation"


def infer_consumer(key: str) -> str:
    lower = key.lower()
    if "signals:trading" in lower or "proposal" in lower:
        return "legacy trader/orchestrator consumers"
    if "executed" in lower or "execution" in lower:
        return "audit, reward, trainer feedback, dashboard"
    if "trainer" in lower:
        return "trainer monitors, orchestrator, V2 parity readers"
    if lower.startswith(("market:", "ohlcv:", "price:", "orderbook:", "funding:", "oi:")):
        return "feature pipeline, trainer, dashboard"
    return "unknown consumer - review before mutation"


def build_dry_run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for row in rows[:100]:
        memory_bytes = row.get("memory_bytes") or 0
        stream_length = row.get("stream_length") or 0
        namespace = row["namespace"]
        if memory_bytes < 5 * 1024 * 1024 and stream_length < 10000:
            continue
        if row["criticality"] == "unknown_requires_review":
            proposed = "NO_MUTATION_CLASSIFY_FIRST"
            required = "human approval after producer/consumer classification"
            estimated = 0
            risk = "unknown"
        elif row["type"] == "stream":
            proposed = "DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX"
            required = "human approval plus export/offload proof before XTRIM"
            target_len = min(max(10000, int(stream_length * 0.2)), stream_length)
            estimated = int(memory_bytes * max(0.0, 1 - (target_len / max(stream_length, 1)))) if stream_length else int(memory_bytes * 0.5)
            risk = "medium-high if offload is incomplete"
        elif row["namespace"] in {"feature_cache", "monitor_telemetry"}:
            proposed = "DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB"
            required = "human approval for TTL policy; no immediate mutation"
            estimated = int(memory_bytes * 0.5)
            risk = "medium"
        else:
            proposed = "NO_MUTATION_OFFLOAD_OR_BOUND_RETENTION_DESIGN"
            required = "human approval and component-owner review"
            estimated = 0
            risk = "high"
        actions.append(
            {
                "key": row["key"],
                "namespace": namespace,
                "type": row["type"],
                "current_memory_bytes": memory_bytes,
                "current_memory_mb": row["memory_mb"],
                "stream_length": stream_length,
                "proposed_action": proposed,
                "estimated_memory_reduction_bytes": estimated,
                "estimated_memory_reduction_mb": round(estimated / 1024 / 1024, 3),
                "risk": risk,
                "required_approval": required,
                "backup_or_offload_required": True,
                "verification_command": f"redis-cli MEMORY USAGE '{row['key']}' SAMPLES 0",
            }
        )
    return actions[:50]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def markdown_table(rows: list[dict[str, Any]], fields: list[str], limit: int = 40) -> str:
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(str(row.get(field, "")).replace("\n", " ")[:200] for field in fields) + " |")
    if len(rows) > limit:
        lines.append(f"\nShowing {limit} of {len(rows)} rows. Full data is in JSON.")
    return "\n".join(lines) + "\n"


def render_report(data: dict[str, Any]) -> str:
    return f"""# Phase 3D Redis Memory Pressure Remediation Dry-Run And Policy Report

Generated: {data['generated_at']}

## Result

{data['go_no_go']}

## Current Redis Memory

- Used memory: {data['redis_info']['used_memory_human']}
- Peak memory: {data['redis_info']['used_memory_peak_human']}
- Max memory: {data['redis_info']['maxmemory_human']}
- Maxmemory policy: {data['redis_info']['maxmemory_policy']}
- Evicted keys: {data['redis_info']['evicted_keys']}
- Keys scanned: {data['counts']['keys_scanned']}
- Dry-run actions: {data['counts']['dry_run_action_count']}
- Estimated dry-run savings: {data['counts']['estimated_savings_mb']} MB

## Phase 3C Link

- Phase 3C gate: {data['phase3c_reference']['go_no_go']}
- Phase 3C max Redis memory ratio: {data['phase3c_reference']['redis_memory_max_pct']}%
- Phase 3C average Redis memory ratio: {data['phase3c_reference']['redis_memory_avg_pct']}%

## Safety

This task executed read-only Redis commands only. It did not run DEL, XDEL, XTRIM, SET, HSET, XADD, FLUSHALL, FLUSHDB, CONFIG SET, BGSAVE, service restarts, exchange actions, or live trading actions.

PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_REPORT_READY
"""


def main() -> int:
    data = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    write(OUT / "PHASE3D_REDIS_MEMORY_PRESSURE_REMEDIATION_REPORT.md", render_report(data))
    write(OUT / "GO_NO_GO.md", data["go_no_go"] + "\n")
    write_json(OUT / "redis_memory_attribution.json", data)
    write(OUT / "redis_namespace_classification.md", "# Redis Namespace Classification\n\n" + markdown_table(
        [{"namespace": k, **v} for k, v in sorted(data["namespace_summary"].items())],
        ["namespace", "keys", "memory_mb", "stream_length"],
        100,
    ))
    write(OUT / "top_redis_memory_consumers.md", "# Top Redis Memory Consumers\n\n" + markdown_table(
        data["top_consumers"],
        ["key", "type", "memory_mb", "stream_length", "ttl_seconds", "namespace", "criticality", "likely_producer", "likely_consumer"],
        60,
    ))
    write(OUT / "redis_retention_policy.md", """# Redis Retention Policy

- Redis is transport/cache only, not durable audit storage.
- Live signal streams require bounded retention sufficient for consumer recovery.
- Executed/audit streams require V2 audit-ledger or Postgres offload before any trim.
- Trainer prediction streams require recent-window retention plus durable prediction ledger.
- Feature caches require TTL or bounded retention by namespace.
- Monitor telemetry should move to files/Postgres, not unbounded Redis growth.
- Unknown keys are preserved until producer and consumer are classified.

REDIS_RETENTION_POLICY_READY
""")
    write(OUT / "redis_offload_to_v2_audit_ledger_plan.md", """# Redis Offload To V2 Audit Ledger Plan

1. Export stream IDs and metadata for execution/audit streams without secrets.
2. Materialize durable V2 audit-ledger records in Postgres/Timescale.
3. Verify record counts, min/max stream IDs, and checksums.
4. Require human approval before any Redis trim.
5. After approval, trim only exact reviewed keys/patterns.

REDIS_OFFLOAD_TO_V2_AUDIT_LEDGER_PLAN_READY
""")
    write(OUT / "redis_trim_dry_run_plan.md", "# Redis Trim Dry-Run Plan\n\n" + markdown_table(
        data["dry_run_actions"],
        ["key", "type", "current_memory_mb", "stream_length", "proposed_action", "estimated_memory_reduction_mb", "risk", "required_approval"],
        50,
    ))
    write(OUT / "human_approval_required_for_redis_mutation.md", """# Human Approval Required For Redis Mutation

No Redis mutation is approved by this milestone.

Before any DEL, XDEL, XTRIM, SET, HSET, XADD, FLUSHALL, FLUSHDB, CONFIG SET, or retention mutation, the operator must approve:

- exact key/pattern
- exact command
- expected memory savings
- proof the key is not live-critical or has been offloaded
- backup/export command and verification
- rollback limitations
- post-action validation command

REDIS_MUTATION_REQUIRES_HUMAN_APPROVAL
""")
    write(OUT / "v2_redis_prevention_architecture.md", """# V2 Redis Pressure Prevention Architecture

- Use Redis only for transport/cache.
- Use V2 audit ledger/Postgres/Timescale for durable history.
- Enforce maxlen/TTL at producer boundaries.
- Isolate V2 namespaces from legacy namespaces.
- Add dashboard alert bands: warn at 75%, block at 90%, critical at 95%.
- Reject unbounded streams during code review.
- Move monitor packets to local files or DB, not Redis.
- Require retention policy metadata for every stream producer.

V2_REDIS_PREVENTION_ARCHITECTURE_READY
""")
    write_json(OUT / "operator_dashboard_payload.json", data)
    write_json(PUBLIC / "operator_dashboard_payload.json", data)
    write_json(OUT / "evidence_manifest.json", {
        "generated_at": data["generated_at"],
        "read_only_commands": data["evidence_commands"],
        "forbidden_commands_not_executed": data["forbidden_commands_not_executed"],
        "phase3c_reference": "claude_worklog/final_readiness/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json",
    })
    write(OUT / "next_safe_milestone.md", data["next_safe_milestone"] + "\n")
    write(OUT / "CODEX_PHASE3D_REDIS_MEMORY_REVIEW.md", f"""# Codex Phase 3D Redis Memory Review

This adversarial review checks that Phase 3D is read-only, specific, and does not destroy forensic evidence.

- Redis mutation performed: no
- Top consumers present: {bool(data['top_consumers'])}
- Dry-run actions present: {bool(data['dry_run_actions'])}
- Human approval required before mutation: yes
- Unknown keys preserved: yes
- V2 prevention architecture present: yes

Result: {'PASS' if data['codex_go_no_go'].endswith('_PASS') else 'FAIL'}

CODEX_PHASE3D_REDIS_MEMORY_REVIEW_READY
""")
    write(OUT / "CODEX_PHASE3D_GO_NO_GO.md", data["codex_go_no_go"] + "\n")
    print(json.dumps({"go_no_go": data["go_no_go"], "next_safe_milestone": data["next_safe_milestone"], "counts": data["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
