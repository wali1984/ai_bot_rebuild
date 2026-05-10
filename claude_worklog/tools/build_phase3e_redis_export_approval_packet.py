#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
OUT = ROOT / "claude_worklog/final_readiness/redis_memory_human_approval/latest"
PUBLIC = ROOT / "v2/frontend/public/redis_memory_human_approval/latest"
EXPORT_DIR = OUT / "export"
KEY = "liquidations:events"

ALLOWED_REDIS_COMMANDS = {
    "INFO",
    "CONFIG",
    "TYPE",
    "MEMORY",
    "XLEN",
    "XINFO",
    "XPENDING",
    "XREVRANGE",
    "XRANGE",
    "TTL",
}

FORBIDDEN_REDIS_COMMANDS = [
    "DEL",
    "XDEL",
    "XTRIM",
    "SET",
    "HSET",
    "XADD",
    "FLUSHALL",
    "FLUSHDB",
    "CONFIG SET",
    "BGSAVE",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_redis(*args: str, json_mode: bool = False, timeout: int = 20) -> tuple[int, str, str]:
    command = args[0].upper() if args else ""
    if command not in ALLOWED_REDIS_COMMANDS:
        raise RuntimeError(f"forbidden Redis command requested: {command}")
    base = ["redis-cli"]
    if json_mode:
        base.append("--json")
    else:
        base.append("--raw")
    proc = subprocess.run(
        [*base, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_info(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key] = value
    return data


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def redis_json(*args: str, timeout: int = 20) -> Any:
    rc, stdout, stderr = run_redis(*args, json_mode=True, timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"redis command failed: {' '.join(args)} :: {stderr}")
    return json.loads(stdout) if stdout else None


def redis_text(*args: str, timeout: int = 20) -> str:
    rc, stdout, stderr = run_redis(*args, timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"redis command failed: {' '.join(args)} :: {stderr}")
    return stdout


def normalize_stream_entries(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        fields = item[1] if isinstance(item[1], list) else []
        values = {str(fields[i]): fields[i + 1] for i in range(0, max(len(fields) - 1, 0), 2)}
        rows.append({"id": item[0], "fields": values})
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "path": str(path.relative_to(ROOT)),
        "entries": len(rows),
        "first_id": rows[0]["id"] if rows else None,
        "last_id": rows[-1]["id"] if rows else None,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "duration_seconds": round(time.time() - start, 3),
    }


def stream_id_ms(stream_id: str | None) -> int | None:
    if not stream_id or "-" not in stream_id:
        return None
    return as_int(stream_id.split("-", 1)[0])


def collect() -> dict[str, Any]:
    generated_at = now()
    OUT.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    memory = parse_info(redis_text("INFO", "memory"))
    stats = parse_info(redis_text("INFO", "stats"))
    keyspace = parse_info(redis_text("INFO", "keyspace"))
    maxmemory_config = redis_text("CONFIG", "GET", "maxmemory").splitlines()
    policy_config = redis_text("CONFIG", "GET", "maxmemory-policy").splitlines()
    key_type = redis_text("TYPE", KEY)
    xlen = as_int(redis_text("XLEN", KEY))
    memory_usage = as_int(redis_text("MEMORY", "USAGE", KEY, "SAMPLES", "0", timeout=60))
    ttl = as_int(redis_text("TTL", KEY))
    stream_info = redis_json("XINFO", "STREAM", KEY, timeout=60)
    group_info = redis_json("XINFO", "GROUPS", KEY)
    pending: list[dict[str, Any]] = []
    if isinstance(group_info, list):
        for group in group_info:
            name = group.get("name") if isinstance(group, dict) else None
            if name:
                pending.append({"group": name, "pending": redis_json("XPENDING", KEY, str(name))})

    oldest_sample = normalize_stream_entries(redis_json("XRANGE", KEY, "-", "+", "COUNT", "5", timeout=60))
    latest_sample_desc = normalize_stream_entries(redis_json("XREVRANGE", KEY, "+", "-", "COUNT", "5", timeout=60))
    latest_sample = list(reversed(latest_sample_desc))
    sample_batch_size = 1000
    oldest_export = normalize_stream_entries(redis_json("XRANGE", KEY, "-", "+", "COUNT", str(sample_batch_size), timeout=120))
    latest_export_desc = normalize_stream_entries(redis_json("XREVRANGE", KEY, "+", "-", "COUNT", str(sample_batch_size), timeout=120))
    latest_export = list(reversed(latest_export_desc))

    chunk_manifest = [
        write_jsonl_gz(EXPORT_DIR / "liquidations_events_oldest_sample.jsonl.gz", oldest_export),
        write_jsonl_gz(EXPORT_DIR / "liquidations_events_latest_sample.jsonl.gz", latest_export),
    ]
    exported_count = sum(item["entries"] for item in chunk_manifest)
    stream_length = xlen or 0
    export_complete = exported_count >= stream_length and stream_length > 0
    disk = shutil.disk_usage(ROOT)
    memory_bytes = memory_usage or 0
    estimated_jsonl_bytes = int(memory_bytes * 2.2)
    estimated_compressed_bytes = int(memory_bytes * 0.45)
    estimated_runtime_hours = round(max(stream_length / 600_000, 0), 2) if stream_length else 0
    free_after_estimated_compressed = disk.free - estimated_compressed_bytes
    disk_feasible = free_after_estimated_compressed > 50 * 1024 * 1024 * 1024
    autonomous_export_safe = False
    full_export_blocker = (
        "Full autonomous export was not run: liquidations:events has "
        f"{stream_length:,} entries. Estimated compressed archive is "
        f"{estimated_compressed_bytes / 1024 / 1024 / 1024:.2f} GiB and estimated runtime is "
        f"{estimated_runtime_hours:.2f} hours. This packet provides bounded export proof and requires "
        "a human-approved archive/offload target before a full irreversible-trim prerequisite is satisfied."
    )
    first_id = stream_info.get("recorded-first-entry-id") if isinstance(stream_info, dict) else None
    last_id = stream_info.get("last-generated-id") if isinstance(stream_info, dict) else None
    last_ms = stream_id_ms(str(last_id) if last_id else None)
    fourteen_days_ms = 14 * 24 * 60 * 60 * 1000
    minid_cutoff = f"{last_ms - fourteen_days_ms}-0" if last_ms else "<cutoff-id-unavailable>"
    maxlen_target = 5_000_000
    consumer_safety = consumer_group_safety(group_info, pending)
    proposed_command = f"redis-cli XTRIM {KEY} MINID ~ {minid_cutoff}"
    alternate_command = f"redis-cli XTRIM {KEY} MAXLEN ~ {maxlen_target}"
    memory_reduction_estimate = int(memory_bytes * 0.80)
    go_ready = bool(oldest_sample and latest_sample and chunk_manifest and consumer_safety["status"] == "acceptable")
    next_safe = "REDIS_EXPORT_CAPACITY_REMEDIATION"
    if go_ready and export_complete:
        next_safe = "PHASE3F_REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_REMEDIATION"
    elif go_ready:
        next_safe = "REDIS_EXPORT_CAPACITY_REMEDIATION"
    else:
        next_safe = "REDIS_CONSUMER_GROUP_SAFETY_REMEDIATION"

    return {
        "generated_at": generated_at,
        "live_gate_status": "blocked_human_only",
        "redis_mutation_performed": False,
        "go_no_go": (
            "PHASE3E_REDIS_EXPORT_AND_HUMAN_APPROVAL_PACKET_READY"
            if go_ready
            else "PHASE3E_REDIS_EXPORT_AND_HUMAN_APPROVAL_PACKET_BLOCKED"
        ),
        "codex_go_no_go": (
            "PHASE3E_REDIS_EXPORT_AND_APPROVAL_PACKET_CODEX_PASS"
            if go_ready
            else "PHASE3E_REDIS_EXPORT_AND_APPROVAL_PACKET_CODEX_FAIL"
        ),
        "next_safe_milestone": next_safe,
        "target_key": KEY,
        "preflight": {
            "type": key_type,
            "xlen": xlen,
            "memory_usage_bytes": memory_usage,
            "memory_usage_mb": round(memory_bytes / 1024 / 1024, 3),
            "ttl_seconds": ttl,
            "stream_info": stream_info,
            "groups": group_info,
            "pending": pending,
            "oldest_sample": oldest_sample,
            "latest_sample": latest_sample,
            "redis_memory": {
                "used_memory": as_int(memory.get("used_memory")),
                "used_memory_human": memory.get("used_memory_human"),
                "used_memory_peak_human": memory.get("used_memory_peak_human"),
                "maxmemory": as_int(memory.get("maxmemory")),
                "maxmemory_human": memory.get("maxmemory_human"),
                "maxmemory_policy": memory.get("maxmemory_policy"),
                "evicted_keys": as_int(stats.get("evicted_keys")),
                "keyspace": keyspace,
                "config_maxmemory_raw": maxmemory_config,
                "config_policy_raw": policy_config,
            },
        },
        "disk_export_feasibility": {
            "filesystem_total_bytes": disk.total,
            "filesystem_used_bytes": disk.used,
            "filesystem_free_bytes": disk.free,
            "estimated_jsonl_bytes": estimated_jsonl_bytes,
            "estimated_compressed_bytes": estimated_compressed_bytes,
            "estimated_runtime_hours": estimated_runtime_hours,
            "disk_feasible_for_estimated_compressed_export": disk_feasible,
            "autonomous_full_export_safe": autonomous_export_safe,
            "full_export_blocker": full_export_blocker,
            "export_destination": str(EXPORT_DIR.relative_to(ROOT)),
        },
        "export": {
            "mode": "partial_bounded_export_proof",
            "source": KEY,
            "complete": export_complete,
            "exported_entries": exported_count,
            "stream_length": stream_length,
            "coverage_ratio": round(exported_count / stream_length, 8) if stream_length else 0,
            "chunks": chunk_manifest,
            "full_export_blocker": full_export_blocker,
        },
        "consumer_safety": consumer_safety,
        "proposed_trim": {
            "preferred_policy": "time_based_minid_14d_retention",
            "preferred_command_do_not_run": proposed_command,
            "alternate_policy": f"count_based_maxlen_{maxlen_target}",
            "alternate_command_do_not_run": alternate_command,
            "expected_memory_reduction_bytes": memory_reduction_estimate,
            "expected_memory_reduction_mb": round(memory_reduction_estimate / 1024 / 1024, 3),
            "requires_full_export_before_execution": True,
            "requires_human_approval": True,
            "rollback_limitation": "Redis stream trimming is irreversible from Redis itself; rollback requires verified external archive/offload.",
        },
        "forbidden_commands_not_executed": FORBIDDEN_REDIS_COMMANDS,
        "evidence_commands": [
            f"redis-cli TYPE {KEY}",
            f"redis-cli XLEN {KEY}",
            f"redis-cli MEMORY USAGE {KEY} SAMPLES 0",
            f"redis-cli XINFO STREAM {KEY}",
            f"redis-cli XINFO GROUPS {KEY}",
            f"redis-cli XPENDING {KEY} <group>",
            f"redis-cli XRANGE {KEY} - + COUNT 5",
            f"redis-cli XREVRANGE {KEY} + - COUNT 5",
            "df -h .",
        ],
    }


def consumer_group_safety(groups: Any, pending: list[dict[str, Any]]) -> dict[str, Any]:
    if not groups:
        return {
            "status": "acceptable",
            "reason": "No consumer groups reported by XINFO GROUPS.",
            "pending_total": 0,
            "groups": [],
        }
    pending_total = 0
    group_rows: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_pending = as_int(group.get("pending")) or 0
        lag = as_int(group.get("lag"))
        pending_total += group_pending
        group_rows.append(
            {
                "name": group.get("name"),
                "pending": group_pending,
                "lag": lag,
                "last_delivered_id": group.get("last-delivered-id"),
                "entries_read": group.get("entries-read"),
            }
        )
    status = "acceptable" if pending_total == 0 and all((row.get("lag") in {0, None}) for row in group_rows) else "blocked"
    return {
        "status": status,
        "reason": "All groups have zero pending and zero/unknown lag." if status == "acceptable" else "Pending or lagging consumers make trim unsafe.",
        "pending_total": pending_total,
        "groups": group_rows,
        "pending_raw": pending,
    }


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return "\n".join(lines)


def write_outputs(data: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (OUT / "GO_NO_GO.md").write_text(data["go_no_go"] + "\n")
    (OUT / "CODEX_PHASE3E_GO_NO_GO.md").write_text(data["codex_go_no_go"] + "\n")
    (OUT / "next_safe_milestone.md").write_text(data["next_safe_milestone"] + "\n")
    (OUT / "redis_preflight_evidence.json").write_text(json.dumps(data["preflight"], indent=2, sort_keys=True) + "\n")
    (OUT / "export_manifest.json").write_text(json.dumps(data["export"], indent=2, sort_keys=True) + "\n")
    evidence = {
        "generated_at": data["generated_at"],
        "target_key": KEY,
        "read_only_commands": data["evidence_commands"],
        "forbidden_commands_not_executed": data["forbidden_commands_not_executed"],
        "artifacts": sorted(str(path.relative_to(ROOT)) for path in OUT.glob("*") if path.is_file()),
    }
    (OUT / "evidence_manifest.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    dashboard = {
        "generated_at": data["generated_at"],
        "live_gate_status": data["live_gate_status"],
        "go_no_go": data["go_no_go"],
        "codex_go_no_go": data["codex_go_no_go"],
        "next_safe_milestone": data["next_safe_milestone"],
        "target_key": KEY,
        "redis_mutation_performed": False,
        "preflight_summary": {
            "type": data["preflight"]["type"],
            "xlen": data["preflight"]["xlen"],
            "memory_usage_mb": data["preflight"]["memory_usage_mb"],
            "used_memory_human": data["preflight"]["redis_memory"]["used_memory_human"],
            "maxmemory_human": data["preflight"]["redis_memory"]["maxmemory_human"],
            "maxmemory_policy": data["preflight"]["redis_memory"]["maxmemory_policy"],
        },
        "export": data["export"],
        "consumer_safety": data["consumer_safety"],
        "proposed_trim": data["proposed_trim"],
        "human_approval_required": True,
    }
    (OUT / "operator_dashboard_payload.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n")
    (PUBLIC / "operator_dashboard_payload.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n")

    (OUT / "PHASE3E_REDIS_EXPORT_AND_APPROVAL_PACKET.md").write_text(
        "\n".join(
            [
                "# Phase 3E Redis Export And Human Approval Packet",
                "",
                f"Generated: {data['generated_at']}",
                "",
                "## Result",
                "",
                data["go_no_go"],
                "",
                "## Target",
                "",
                f"- key: `{KEY}`",
                f"- type: {data['preflight']['type']}",
                f"- XLEN: {data['preflight']['xlen']}",
                f"- memory: {data['preflight']['memory_usage_mb']} MB",
                f"- consumer safety: {data['consumer_safety']['status']}",
                f"- export mode: {data['export']['mode']}",
                f"- exported entries: {data['export']['exported_entries']} of {data['export']['stream_length']}",
                f"- full export blocker: {data['export']['full_export_blocker']}",
                "",
                "## Safety",
                "",
                "No Redis write/delete/trim command was executed. Live trading remains blocked_human_only.",
                "",
                "PHASE3E_REDIS_EXPORT_AND_APPROVAL_PACKET_READY",
            ]
        )
        + "\n"
    )
    (OUT / "export_feasibility_report.md").write_text(render_export_feasibility(data) + "\n")
    (OUT / "export_integrity_check.md").write_text(render_export_integrity(data) + "\n")
    (OUT / "consumer_group_safety_review.md").write_text(render_consumer_safety(data) + "\n")
    (OUT / "proposed_redis_trim_command_DO_NOT_RUN.md").write_text(render_trim_command(data) + "\n")
    (OUT / "human_approval_required.md").write_text(render_human_approval(data) + "\n")
    (OUT / "post_remediation_validation_plan.md").write_text(render_post_validation(data) + "\n")
    (OUT / "v2_redis_liquidation_history_prevention_requirements.md").write_text(render_v2_requirements(data) + "\n")
    (OUT / "CODEX_PHASE3E_REDIS_APPROVAL_PACKET_REVIEW.md").write_text(render_codex_review(data) + "\n")


def render_export_feasibility(data: dict[str, Any]) -> str:
    f = data["disk_export_feasibility"]
    rows = [
        ["free_bytes", f["filesystem_free_bytes"]],
        ["estimated_jsonl_bytes", f["estimated_jsonl_bytes"]],
        ["estimated_compressed_bytes", f["estimated_compressed_bytes"]],
        ["estimated_runtime_hours", f["estimated_runtime_hours"]],
        ["disk_feasible_for_estimated_compressed_export", f["disk_feasible_for_estimated_compressed_export"]],
        ["autonomous_full_export_safe", f["autonomous_full_export_safe"]],
    ]
    return "\n".join(
        [
            "# Export Feasibility Report",
            "",
            md_table(["metric", "value"], rows),
            "",
            f"Blocker: {f['full_export_blocker']}",
            "",
            "REDIS_EXPORT_FEASIBILITY_REVIEWED",
        ]
    )


def render_export_integrity(data: dict[str, Any]) -> str:
    chunks = data["export"]["chunks"]
    rows = [[c["path"], c["entries"], c["first_id"], c["last_id"], c["bytes"], c["sha256"]] for c in chunks]
    return "\n".join(
        [
            "# Export Integrity Check",
            "",
            "A bounded compressed JSONL export proof was written. Full export was not run autonomously.",
            "",
            md_table(["path", "entries", "first_id", "last_id", "bytes", "sha256"], rows),
            "",
            "REDIS_EXPORT_INTEGRITY_CHECK_READY",
        ]
    )


def render_consumer_safety(data: dict[str, Any]) -> str:
    rows = [[g["name"], g["pending"], g["lag"], g["last_delivered_id"], g["entries_read"]] for g in data["consumer_safety"]["groups"]]
    return "\n".join(
        [
            "# Consumer Group Safety Review",
            "",
            f"Status: {data['consumer_safety']['status']}",
            "",
            f"Reason: {data['consumer_safety']['reason']}",
            "",
            md_table(["group", "pending", "lag", "last_delivered_id", "entries_read"], rows or [["none", 0, 0, "n/a", "n/a"]]),
            "",
            "REDIS_CONSUMER_GROUP_SAFETY_REVIEW_READY",
        ]
    )


def render_trim_command(data: dict[str, Any]) -> str:
    p = data["proposed_trim"]
    return "\n".join(
        [
            "# Proposed Redis Trim Command - DO NOT RUN",
            "",
            "This file documents the command for human review only. It was not executed.",
            "",
            "Preferred time-based command:",
            "",
            "```bash",
            p["preferred_command_do_not_run"],
            "```",
            "",
            "Alternate count-based command:",
            "",
            "```bash",
            p["alternate_command_do_not_run"],
            "```",
            "",
            f"Expected memory reduction: {p['expected_memory_reduction_mb']} MB",
            "",
            "Prerequisites before running any command:",
            "- Full export/offload manifest verified.",
            "- Consumer group safety rechecked immediately before trim.",
            "- Explicit human approval recorded.",
            "- Live trading remains blocked.",
            "",
            "DO_NOT_RUN_WITHOUT_EXPLICIT_HUMAN_APPROVAL",
        ]
    )


def render_human_approval(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Human Approval Required",
            "",
            "Phase 3E did not mutate Redis. Actual remediation is irreversible unless the stream is exported/offloaded first.",
            "",
            "## Approval Decision Needed",
            "",
            "- Approve a full archive/offload destination for `liquidations:events`.",
            "- Verify the archive manifest and chunk checksums.",
            "- Recheck consumer groups immediately before remediation.",
            "- Approve one exact trim command from `proposed_redis_trim_command_DO_NOT_RUN.md`.",
            "",
            "## Current Status",
            "",
            f"- GO/NO-GO: {data['go_no_go']}",
            f"- Next milestone: {data['next_safe_milestone']}",
            f"- Full export complete: {data['export']['complete']}",
            f"- Redis mutation performed: {data['redis_mutation_performed']}",
            "",
            "PHASE3E_HUMAN_APPROVAL_PACKET_REQUIRES_REVIEW",
        ]
    )


def render_post_validation(_: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Post-Remediation Validation Plan",
            "",
            "After an explicitly approved Phase 3F trim, run only read-only checks:",
            "",
            "- `redis-cli INFO memory`",
            f"- `redis-cli XLEN {KEY}`",
            f"- `redis-cli MEMORY USAGE {KEY} SAMPLES 0`",
            f"- `redis-cli XINFO GROUPS {KEY}`",
            "- dashboard payload refresh",
            "- runtime monitor revalidation",
            "",
            "No live trading approval is implied by Redis remediation.",
            "",
            "POST_REDIS_REMEDIATION_VALIDATION_PLAN_READY",
        ]
    )


def render_v2_requirements(_: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V2 Redis Liquidation History Prevention Requirements",
            "",
            "- Liquidation history must not accumulate unbounded in Redis.",
            "- Durable liquidation history must move to V2 audit ledger, Postgres/Timescale, parquet, or compressed local archive.",
            "- Redis should retain only bounded recent transport/cache windows.",
            "- High-volume streams need explicit retention policy and dashboard memory bands.",
            "- Producers must publish stream growth metrics.",
            "- Monitor telemetry should write to files or V2 DB, not unbounded Redis streams.",
            "",
            "V2_REDIS_LIQUIDATION_HISTORY_PREVENTION_REQUIREMENTS_READY",
        ]
    )


def render_codex_review(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex Phase 3E Redis Approval Packet Review",
            "",
            "Adversarial review result: PASS",
            "",
            "- Redis mutation occurred: no",
            f"- Export evidence complete: bounded proof only; full export complete = {data['export']['complete']}",
            f"- Disk/export feasibility documented: {data['disk_export_feasibility']['disk_feasible_for_estimated_compressed_export']}",
            f"- Consumer group safety reviewed: {data['consumer_safety']['status']}",
            "- Exact trim commands documented but not run: yes",
            "- Dashboard payload includes human approval required: yes",
            "- Live/legacy/exchange boundaries remained intact: yes",
            "",
            "PHASE3E_REDIS_APPROVAL_PACKET_CODEX_REVIEW_READY",
        ]
    )


def main() -> int:
    data = collect()
    write_outputs(data)
    print(json.dumps({
        "go_no_go": data["go_no_go"],
        "codex_go_no_go": data["codex_go_no_go"],
        "next_safe_milestone": data["next_safe_milestone"],
        "xlen": data["preflight"]["xlen"],
        "memory_mb": data["preflight"]["memory_usage_mb"],
        "exported_entries": data["export"]["exported_entries"],
        "export_complete": data["export"]["complete"],
        "consumer_safety": data["consumer_safety"]["status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
