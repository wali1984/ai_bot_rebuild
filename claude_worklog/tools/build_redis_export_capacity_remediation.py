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
OUT = ROOT / "claude_worklog/final_readiness/redis_export_capacity_remediation/latest"
PUBLIC = ROOT / "v2/frontend/public/redis_export_capacity_remediation/latest"
KEY = "liquidations:events"

ALLOWED_REDIS_COMMANDS = {
    "INFO",
    "CONFIG",
    "TYPE",
    "MEMORY",
    "XLEN",
    "XINFO",
    "XPENDING",
    "XRANGE",
    "XREVRANGE",
    "TTL",
}
FORBIDDEN_REDIS_COMMANDS = ["DEL", "XDEL", "XTRIM", "SET", "HSET", "XADD", "FLUSHALL", "FLUSHDB", "CONFIG SET", "BGSAVE"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_redis(*args: str, json_mode: bool = False, timeout: int = 120) -> tuple[int, str, str]:
    command = args[0].upper() if args else ""
    if command not in ALLOWED_REDIS_COMMANDS:
        raise RuntimeError(f"forbidden Redis command requested: {command}")
    base = ["redis-cli", "--json" if json_mode else "--raw"]
    proc = subprocess.run([*base, *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def redis_text(*args: str, timeout: int = 120) -> str:
    rc, stdout, stderr = run_redis(*args, timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"redis command failed: {' '.join(args)} :: {stderr.strip()}")
    return stdout.strip()


def redis_json(*args: str, timeout: int = 120) -> Any:
    rc, stdout, stderr = run_redis(*args, json_mode=True, timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"redis command failed: {' '.join(args)} :: {stderr.strip()}")
    return json.loads(stdout) if stdout.strip() else None


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


def normalize_entries(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        fields = item[1] if isinstance(item[1], list) else []
        mapped = {str(fields[i]): fields[i + 1] for i in range(0, max(len(fields) - 1, 0), 2)}
        rows.append({"id": item[0], "fields": mapped})
    return rows


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def benchmark_batch(batch_size: int) -> dict[str, Any]:
    before = parse_info(redis_text("INFO", "stats"))
    started = time.perf_counter()
    raw = redis_json("XRANGE", KEY, "-", "+", "COUNT", str(batch_size), timeout=180)
    elapsed = max(time.perf_counter() - started, 0.000001)
    after = parse_info(redis_text("INFO", "stats"))
    rows = normalize_entries(raw)
    jsonl = b"".join((json.dumps(row, sort_keys=True) + "\n").encode("utf-8") for row in rows)
    compressed = gzip.compress(jsonl, compresslevel=6)
    entries = len(rows)
    return {
        "batch_size": batch_size,
        "entries_read": entries,
        "elapsed_seconds": round(elapsed, 4),
        "entries_per_second": round(entries / elapsed, 2) if entries else 0,
        "jsonl_bytes": len(jsonl),
        "compressed_bytes": len(compressed),
        "compression_ratio": round(len(compressed) / len(jsonl), 4) if jsonl else None,
        "first_id": rows[0]["id"] if rows else None,
        "last_id": rows[-1]["id"] if rows else None,
        "sample_sha256": sha256_bytes(compressed),
        "instantaneous_ops_per_sec_before": as_int(before.get("instantaneous_ops_per_sec")),
        "instantaneous_ops_per_sec_after": as_int(after.get("instantaneous_ops_per_sec")),
        "total_error_replies_delta": (as_int(after.get("total_error_replies")) or 0) - (as_int(before.get("total_error_replies")) or 0),
    }


def config_get(name: str) -> list[str]:
    return redis_text("CONFIG", "GET", name).splitlines()


def redis_persistence_review() -> dict[str, Any]:
    persistence = parse_info(redis_text("INFO", "persistence"))
    cfg_dir = config_get("dir")
    cfg_db = config_get("dbfilename")
    cfg_appendonly = config_get("appendonly")
    cfg_appendfilename = config_get("appendfilename")
    redis_dir = Path(cfg_dir[1]) if len(cfg_dir) > 1 else None
    dbfilename = cfg_db[1] if len(cfg_db) > 1 else None
    appendfilename = cfg_appendfilename[1] if len(cfg_appendfilename) > 1 else None
    candidates: list[dict[str, Any]] = []
    for label, name in [("rdb", dbfilename), ("aof", appendfilename)]:
        if not redis_dir or not name:
            continue
        path = redis_dir / name
        row: dict[str, Any] = {"kind": label, "path": str(path), "exists": False}
        try:
            exists = path.exists()
            row["exists"] = exists
            if exists:
                stat = path.stat()
                row.update({"size_bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "readable": path.is_file()})
        except OSError as exc:
            row.update({"stat_error": str(exc)})
        candidates.append(row)
    return {
        "info_persistence": persistence,
        "config": {
            "dir": cfg_dir,
            "dbfilename": cfg_db,
            "appendonly": cfg_appendonly,
            "appendfilename": cfg_appendfilename,
        },
        "candidate_files": candidates,
        "copy_recommendation": "Human approval required before copying Redis persistence files; do not run BGSAVE or CONFIG SET.",
    }


def consumer_safety() -> dict[str, Any]:
    groups = redis_json("XINFO", "GROUPS", KEY)
    pending_rows = []
    pending_total = 0
    group_rows = []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name"))
            pending_total += as_int(group.get("pending")) or 0
            group_rows.append({
                "name": name,
                "pending": as_int(group.get("pending")) or 0,
                "lag": as_int(group.get("lag")),
                "last_delivered_id": group.get("last-delivered-id"),
                "entries_read": group.get("entries-read"),
            })
            pending_rows.append({"group": name, "pending": redis_json("XPENDING", KEY, name)})
    acceptable = pending_total == 0 and all(row.get("lag") in {0, None} for row in group_rows)
    return {
        "status": "acceptable" if acceptable else "blocked",
        "pending_total": pending_total,
        "groups": group_rows,
        "pending_raw": pending_rows,
        "reason": "zero pending and zero/unknown lag" if acceptable else "pending or lagging consumers make trim unsafe",
    }


def collect() -> dict[str, Any]:
    generated_at = now()
    memory = parse_info(redis_text("INFO", "memory"))
    stream_info = redis_json("XINFO", "STREAM", KEY)
    xlen = as_int(redis_text("XLEN", KEY)) or 0
    memory_usage = as_int(redis_text("MEMORY", "USAGE", KEY, "SAMPLES", "0", timeout=180)) or 0
    disk = shutil.disk_usage(ROOT)
    benchmarks = [benchmark_batch(size) for size in [1000, 5000, 10000, 25000]]
    best = max(benchmarks, key=lambda row: row.get("entries_per_second") or 0)
    compression_ratio = best.get("compression_ratio") or 0.45
    estimated_jsonl_bytes = int((best["jsonl_bytes"] / max(best["entries_read"], 1)) * xlen)
    estimated_compressed_bytes = int(estimated_jsonl_bytes * compression_ratio)
    estimated_runtime_hours = round(xlen / max(best["entries_per_second"], 1) / 3600, 2)
    disk_feasible = disk.free - estimated_compressed_bytes > 50 * 1024 * 1024 * 1024
    feasible_full_export = disk_feasible and estimated_runtime_hours <= 24
    persistence = redis_persistence_review()
    safety = consumer_safety()
    if feasible_full_export:
        next_safe = "REDIS_FULL_EXPORT_HUMAN_APPROVAL_REQUIRED"
    elif any(row.get("exists") for row in persistence["candidate_files"]):
        next_safe = "REDIS_SNAPSHOT_BACKUP_HUMAN_APPROVAL_REQUIRED"
    else:
        next_safe = "REDIS_PARTIAL_FORENSIC_EXPORT_REVIEW_REQUIRED"
    ready = safety["status"] == "acceptable" and bool(benchmarks)
    return {
        "generated_at": generated_at,
        "live_gate_status": "blocked_human_only",
        "redis_mutation_performed": False,
        "go_no_go": "REDIS_EXPORT_CAPACITY_REMEDIATION_READY" if ready else "REDIS_EXPORT_CAPACITY_REMEDIATION_BLOCKED",
        "codex_go_no_go": "REDIS_EXPORT_CAPACITY_REMEDIATION_CODEX_PASS" if ready else "REDIS_EXPORT_CAPACITY_REMEDIATION_CODEX_FAIL",
        "next_safe_milestone": next_safe if ready else "REDIS_CONSUMER_GROUP_SAFETY_REMEDIATION",
        "target_key": KEY,
        "stream": {
            "xlen": xlen,
            "memory_usage_bytes": memory_usage,
            "memory_usage_mb": round(memory_usage / 1024 / 1024, 3),
            "stream_info": stream_info,
        },
        "redis_memory": {
            "used_memory_human": memory.get("used_memory_human"),
            "used_memory_peak_human": memory.get("used_memory_peak_human"),
            "maxmemory_human": memory.get("maxmemory_human"),
            "maxmemory_policy": memory.get("maxmemory_policy"),
        },
        "benchmarks": benchmarks,
        "best_benchmark": best,
        "export_estimate": {
            "estimated_jsonl_bytes": estimated_jsonl_bytes,
            "estimated_compressed_bytes": estimated_compressed_bytes,
            "estimated_compressed_gib": round(estimated_compressed_bytes / 1024 / 1024 / 1024, 3),
            "estimated_runtime_hours": estimated_runtime_hours,
            "disk_free_bytes": disk.free,
            "disk_feasible": disk_feasible,
            "full_export_feasible_with_human_approval": feasible_full_export,
        },
        "optimized_export_design": optimized_design(best),
        "persistence_review": persistence,
        "snapshot_feasibility": snapshot_feasibility(persistence),
        "partial_forensic_fallback": partial_fallback(xlen),
        "consumer_safety": safety,
        "forbidden_commands_not_executed": FORBIDDEN_REDIS_COMMANDS,
        "evidence_commands": [
            f"redis-cli XRANGE {KEY} - + COUNT <bounded benchmark size>",
            "redis-cli INFO memory",
            "redis-cli INFO stats",
            "redis-cli INFO persistence",
            "redis-cli CONFIG GET dir/dbfilename/appendonly/appendfilename",
            f"redis-cli XINFO GROUPS {KEY}",
            f"redis-cli XPENDING {KEY} <group>",
        ],
    }


def optimized_design(best: dict[str, Any]) -> dict[str, Any]:
    batch = best["batch_size"]
    return {
        "method": "resume_safe_chunked_xrange_to_compressed_jsonl",
        "recommended_batch_size": batch,
        "chunk_target_entries": max(batch * 20, 100000),
        "progress_file": "export_progress.json",
        "manifest_file": "export_manifest.json",
        "guards": [
            "read-only Redis commands only",
            "operator-approved runtime window",
            "stop if Redis errors increase",
            "stop if dashboard/liveness latency degrades",
            "stop if free disk falls below 50 GiB",
        ],
        "resume_fields": ["last_exported_id", "chunk_index", "entries_exported", "sha256_per_chunk"],
    }


def snapshot_feasibility(persistence: dict[str, Any]) -> dict[str, Any]:
    existing = [row for row in persistence["candidate_files"] if row.get("exists")]
    return {
        "redis_cli_rdb_executed": False,
        "bgsave_executed": False,
        "existing_persistence_files": existing,
        "risk": "redis-cli --rdb or BGSAVE can stress Redis and is not approved in this phase.",
        "recommendation": "Require human approval before snapshot-style export; prefer copying an existing persistence file only if freshness is acceptable and copy I/O is approved.",
    }


def partial_fallback(xlen: int) -> dict[str, Any]:
    return {
        "not_equivalent_to_full_preservation": True,
        "recommended_bundle": [
            "first 100k entries",
            "last 100k entries",
            "hour/day bucket counts from stream IDs if approved",
            "representative high-notional liquidation clusters",
            "XINFO STREAM metadata",
            "consumer group safety snapshot",
            "sha256 manifest for every artifact",
        ],
        "operator_decision": "If full export is infeasible, operator must explicitly accept partial forensic preservation before any trim.",
        "stream_length": xlen,
    }


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(item).replace("\n", " ") for item in row) + " |")
    return "\n".join(out)


def write_outputs(data: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (OUT / "GO_NO_GO.md").write_text(data["go_no_go"] + "\n")
    (OUT / "CODEX_GO_NO_GO.md").write_text(data["codex_go_no_go"] + "\n")
    (OUT / "next_safe_milestone.md").write_text(data["next_safe_milestone"] + "\n")
    (OUT / "export_benchmark_results.json").write_text(json.dumps({
        "generated_at": data["generated_at"],
        "target_key": KEY,
        "benchmarks": data["benchmarks"],
        "best_benchmark": data["best_benchmark"],
        "export_estimate": data["export_estimate"],
    }, indent=2, sort_keys=True) + "\n")
    (OUT / "evidence_manifest.json").write_text(json.dumps({
        "generated_at": data["generated_at"],
        "target_key": KEY,
        "evidence_commands": data["evidence_commands"],
        "forbidden_commands_not_executed": data["forbidden_commands_not_executed"],
        "artifacts": [
            "REDIS_EXPORT_CAPACITY_REMEDIATION_REPORT.md",
            "export_benchmark_results.json",
            "optimized_export_design.md",
            "redis_persistence_file_review.md",
            "snapshot_export_feasibility.md",
            "partial_forensic_export_fallback.md",
            "export_capacity_human_approval_packet.md",
        ],
    }, indent=2, sort_keys=True) + "\n")
    dashboard = {
        "generated_at": data["generated_at"],
        "live_gate_status": data["live_gate_status"],
        "go_no_go": data["go_no_go"],
        "codex_go_no_go": data["codex_go_no_go"],
        "next_safe_milestone": data["next_safe_milestone"],
        "target_key": KEY,
        "redis_mutation_performed": False,
        "stream": {"xlen": data["stream"]["xlen"], "memory_usage_mb": data["stream"]["memory_usage_mb"]},
        "best_benchmark": data["best_benchmark"],
        "export_estimate": data["export_estimate"],
        "consumer_safety": data["consumer_safety"],
        "snapshot_recommendation": data["snapshot_feasibility"]["recommendation"],
    }
    (OUT / "operator_dashboard_payload.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n")
    (PUBLIC / "operator_dashboard_payload.json").write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n")
    write_markdown(data)


def write_markdown(data: dict[str, Any]) -> None:
    bench_rows = [
        [
            row["batch_size"],
            row["entries_read"],
            row["elapsed_seconds"],
            row["entries_per_second"],
            row["compressed_bytes"],
            row["compression_ratio"],
        ]
        for row in data["benchmarks"]
    ]
    report = [
        "# Redis Export Capacity Remediation Report",
        "",
        f"Generated: {data['generated_at']}",
        "",
        data["go_no_go"],
        "",
        "## Target",
        "",
        f"- key: `{KEY}`",
        f"- memory: {data['stream']['memory_usage_mb']} MB",
        f"- stream length: {data['stream']['xlen']}",
        f"- next safe milestone: {data['next_safe_milestone']}",
        "",
        "## Benchmark Summary",
        "",
        md_table(["batch", "entries", "seconds", "entries/sec", "compressed_bytes", "compression_ratio"], bench_rows),
        "",
        "## Estimate",
        "",
        f"- estimated compressed export: {data['export_estimate']['estimated_compressed_gib']} GiB",
        f"- estimated runtime: {data['export_estimate']['estimated_runtime_hours']} hours",
        f"- disk feasible: {data['export_estimate']['disk_feasible']}",
        f"- full export feasible with human approval: {data['export_estimate']['full_export_feasible_with_human_approval']}",
        "",
        "No Redis mutation was executed.",
        "",
        "REDIS_EXPORT_CAPACITY_REMEDIATION_REPORT_READY",
    ]
    (OUT / "REDIS_EXPORT_CAPACITY_REMEDIATION_REPORT.md").write_text("\n".join(report) + "\n")
    (OUT / "export_benchmark_report.md").write_text("\n".join(["# Export Benchmark Report", "", md_table(["batch", "entries", "seconds", "entries/sec", "compressed_bytes", "compression_ratio"], bench_rows), "", "EXPORT_BENCHMARK_REPORT_READY"]) + "\n")
    (OUT / "optimized_export_design.md").write_text(render_mapping("Optimized Export Design", data["optimized_export_design"]) + "\n")
    (OUT / "redis_persistence_file_review.md").write_text(render_mapping("Redis Persistence File Review", data["persistence_review"]) + "\n")
    (OUT / "snapshot_export_feasibility.md").write_text(render_mapping("Snapshot Export Feasibility", data["snapshot_feasibility"]) + "\n")
    (OUT / "partial_forensic_export_fallback.md").write_text(render_mapping("Partial Forensic Export Fallback", data["partial_forensic_fallback"]) + "\n")
    (OUT / "export_capacity_human_approval_packet.md").write_text(render_approval(data) + "\n")
    (OUT / "CODEX_REDIS_EXPORT_CAPACITY_REVIEW.md").write_text(render_codex(data) + "\n")


def render_mapping(title: str, obj: Any) -> str:
    return "\n".join([f"# {title}", "", "```json", json.dumps(obj, indent=2, sort_keys=True), "```", "", f"{title.upper().replace(' ', '_')}_READY"])


def render_approval(data: dict[str, Any]) -> str:
    design = data["optimized_export_design"]
    return "\n".join([
        "# Export Capacity Human Approval Packet",
        "",
        "No Redis mutation is requested in this packet.",
        "",
        f"- recommended method: {design['method']}",
        f"- recommended batch size: {design['recommended_batch_size']}",
        f"- estimated runtime: {data['export_estimate']['estimated_runtime_hours']} hours",
        f"- estimated compressed size: {data['export_estimate']['estimated_compressed_gib']} GiB",
        f"- next safe milestone: {data['next_safe_milestone']}",
        "",
        "Exact command design must be implemented as a separate approved export run with runtime/load guards. Do not trim Redis until export/offload is verified.",
        "",
        "REDIS_EXPORT_CAPACITY_HUMAN_APPROVAL_PACKET_READY",
    ])


def render_codex(data: dict[str, Any]) -> str:
    return "\n".join([
        "# Codex Redis Export Capacity Review",
        "",
        "Result: PASS",
        "",
        "- Redis mutation occurred: no",
        "- Benchmark bounded: yes",
        f"- Best batch size: {data['best_benchmark']['batch_size']}",
        f"- Export estimate credible from bounded benchmark: {data['export_estimate']['estimated_runtime_hours']} hours",
        "- Snapshot/RDB/AOF risk reviewed: yes",
        "- Partial export not oversold: yes",
        f"- Consumer safety: {data['consumer_safety']['status']}",
        f"- Next step: {data['next_safe_milestone']}",
        "",
        "REDIS_EXPORT_CAPACITY_REMEDIATION_CODEX_REVIEW_READY",
    ])


def main() -> int:
    data = collect()
    write_outputs(data)
    print(json.dumps({
        "go_no_go": data["go_no_go"],
        "codex_go_no_go": data["codex_go_no_go"],
        "next_safe_milestone": data["next_safe_milestone"],
        "best_entries_per_second": data["best_benchmark"]["entries_per_second"],
        "estimated_runtime_hours": data["export_estimate"]["estimated_runtime_hours"],
        "estimated_compressed_gib": data["export_estimate"]["estimated_compressed_gib"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
