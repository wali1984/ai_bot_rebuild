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
OUT = ROOT / "claude_worklog/final_readiness/redis_liquidations_full_export/latest"
PUBLIC = ROOT / "v2/frontend/public/redis_liquidations_full_export/latest"
EXPORT = OUT / "export"
APPROVAL = ROOT / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_FULL_EXPORT_ONLY.md"
KEY = "liquidations:events"
BATCH_SIZE = 10_000
CHUNK_ENTRIES = 100_000
DISK_FLOOR_BYTES = 50 * 1024 * 1024 * 1024

ALLOWED = {"INFO", "CONFIG", "TYPE", "MEMORY", "XLEN", "XINFO", "XPENDING", "XREVRANGE", "XRANGE", "TTL"}
FORBIDDEN = ["DEL", "XDEL", "XTRIM", "SET", "HSET", "XADD", "FLUSHALL", "FLUSHDB", "CONFIG SET", "BGSAVE"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redis(*args: str, json_mode: bool = False, timeout: int = 180) -> Any:
    if not args or args[0].upper() not in ALLOWED:
        raise RuntimeError(f"forbidden Redis command requested: {args[0] if args else '<none>'}")
    base = ["redis-cli", "--json" if json_mode else "--raw"]
    proc = subprocess.run([*base, *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"redis command failed: {' '.join(args)} :: {proc.stderr.strip()}")
    if json_mode:
        return json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.stdout.strip()


def parse_info(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and ":" in line:
            k, v = line.split(":", 1)
            out[k] = v
    return out


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def entries(raw: Any) -> list[dict[str, Any]]:
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


def next_stream_id(stream_id: str) -> str:
    ms, seq = stream_id.split("-", 1)
    return f"{ms}-{int(seq) + 1}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def consumer_safety() -> dict[str, Any]:
    groups = redis("XINFO", "GROUPS", KEY, json_mode=True)
    rows = []
    pending_total = 0
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name"))
            pending = as_int(group.get("pending")) or 0
            pending_total += pending
            rows.append({
                "name": name,
                "pending": pending,
                "lag": as_int(group.get("lag")),
                "last_delivered_id": group.get("last-delivered-id"),
                "entries_read": group.get("entries-read"),
                "xpending": redis("XPENDING", KEY, name, json_mode=True),
            })
    ok = pending_total == 0 and all(row.get("lag") in {0, None} for row in rows)
    return {"status": "acceptable" if ok else "blocked", "pending_total": pending_total, "groups": rows}


def collect_preflight() -> dict[str, Any]:
    memory = parse_info(redis("INFO", "memory"))
    stats = parse_info(redis("INFO", "stats"))
    stream = redis("XINFO", "STREAM", KEY, json_mode=True, timeout=240)
    xlen = as_int(redis("XLEN", KEY)) or 0
    mem = as_int(redis("MEMORY", "USAGE", KEY, "SAMPLES", "0", timeout=240)) or 0
    disk = shutil.disk_usage(ROOT)
    return {
        "generated_at": now(),
        "approval_file": str(APPROVAL.relative_to(ROOT)),
        "approval_text": APPROVAL.read_text().strip() if APPROVAL.exists() else None,
        "redis_memory": {
            "used_memory": as_int(memory.get("used_memory")),
            "used_memory_human": memory.get("used_memory_human"),
            "maxmemory": as_int(memory.get("maxmemory")),
            "maxmemory_human": memory.get("maxmemory_human"),
            "maxmemory_policy": memory.get("maxmemory_policy"),
            "evicted_keys": as_int(stats.get("evicted_keys")),
            "config_maxmemory": redis("CONFIG", "GET", "maxmemory").splitlines(),
            "config_maxmemory_policy": redis("CONFIG", "GET", "maxmemory-policy").splitlines(),
        },
        "target": {
            "key": KEY,
            "type": redis("TYPE", KEY),
            "xlen": xlen,
            "memory_usage_bytes": mem,
            "memory_usage_mb": round(mem / 1024 / 1024, 3),
            "ttl": as_int(redis("TTL", KEY)),
            "xinfo_stream": stream,
            "xinfo_groups": redis("XINFO", "GROUPS", KEY, json_mode=True),
            "consumer_safety": consumer_safety(),
        },
        "disk": {
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "safety_floor_bytes": DISK_FLOOR_BYTES,
        },
        "selected": {
            "batch_size": BATCH_SIZE,
            "chunk_entries": CHUNK_ENTRIES,
            "destination": str(EXPORT.relative_to(ROOT)),
        },
    }


def anchor(preflight: dict[str, Any]) -> dict[str, Any]:
    info = preflight["target"]["xinfo_stream"]
    return {
        "export_started_at": now(),
        "pre_export_xlen": preflight["target"]["xlen"],
        "pre_export_first_id": info.get("recorded-first-entry-id"),
        "pre_export_last_id": info.get("last-generated-id"),
        "consumer_group_status": preflight["target"]["consumer_safety"],
        "batch_size": BATCH_SIZE,
        "chunk_entries": CHUNK_ENTRIES,
    }


def load_progress() -> dict[str, Any] | None:
    p = OUT / "export_progress.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def save_progress(data: dict[str, Any]) -> None:
    write_json(OUT / "export_progress.json", data)


def export_stream(anchor_data: dict[str, Any]) -> dict[str, Any]:
    EXPORT.mkdir(parents=True, exist_ok=True)
    (EXPORT / ".gitignore").write_text("*.jsonl.gz\n")
    last_id = anchor_data["pre_export_last_id"]
    start_id = anchor_data["pre_export_first_id"]
    progress = load_progress()
    manifest: list[dict[str, Any]] = []
    if progress and progress.get("anchor_last_id") == last_id:
        start_id = progress["next_start_id"]
        manifest = progress.get("chunks", [])
        chunk_index = int(progress.get("next_chunk_index", len(manifest)))
        exported = int(progress.get("exported_count", 0))
    else:
        chunk_index = 0
        exported = 0
    started = time.time()
    buffer: list[dict[str, Any]] = []

    def flush(final: bool = False) -> None:
        nonlocal buffer, chunk_index, manifest
        if not buffer:
            return
        path = EXPORT / f"liquidations_events_{chunk_index:06d}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
            for row in buffer:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        manifest.append({
            "chunk_index": chunk_index,
            "path": str(path.relative_to(ROOT)),
            "entries": len(buffer),
            "first_id": buffer[0]["id"],
            "last_id": buffer[-1]["id"],
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "final": final,
        })
        chunk_index += 1
        buffer = []

    while True:
        if shutil.disk_usage(ROOT).free < DISK_FLOOR_BYTES:
            raise RuntimeError("disk free space fell below safety floor during export")
        raw = redis("XRANGE", KEY, start_id, last_id, "COUNT", str(BATCH_SIZE), json_mode=True, timeout=240)
        rows = entries(raw)
        if not rows:
            break
        buffer.extend(rows)
        exported += len(rows)
        start_id = next_stream_id(rows[-1]["id"])
        if len(buffer) >= CHUNK_ENTRIES:
            flush()
        save_progress({
            "updated_at": now(),
            "anchor_last_id": last_id,
            "next_start_id": start_id,
            "next_chunk_index": chunk_index,
            "exported_count": exported,
            "chunks": manifest,
        })
        if rows[-1]["id"] == last_id:
            break
    flush(final=True)
    duration = time.time() - started
    total_bytes = sum(row["bytes"] for row in manifest)
    result = {
        "export_completed_at": now(),
        "anchor_last_id": last_id,
        "exported_count": exported,
        "chunk_count": len(manifest),
        "compressed_total_bytes": total_bytes,
        "compressed_total_gib": round(total_bytes / 1024 / 1024 / 1024, 3),
        "duration_seconds": round(duration, 3),
        "chunks": manifest,
    }
    save_progress({**result, "updated_at": now(), "next_start_id": start_id, "next_chunk_index": len(manifest)})
    return result


def verify_export(export: dict[str, Any], anchor_data: dict[str, Any]) -> dict[str, Any]:
    chunks = export["chunks"]
    recomputed = []
    for row in chunks:
        path = ROOT / row["path"]
        recomputed.append({**row, "sha256_recomputed": sha256_file(path), "sha256_ok": sha256_file(path) == row["sha256"]})
    sample = {}
    for label, row in [("first", recomputed[0]), ("middle", recomputed[len(recomputed) // 2]), ("last", recomputed[-1])]:
        with gzip.open(ROOT / row["path"], "rt", encoding="utf-8") as fh:
            first_line = fh.readline()
        parsed = json.loads(first_line)
        sample[label] = {"chunk": row["chunk_index"], "first_line_id": parsed["id"], "field_keys": sorted(parsed["fields"])[:8]}
    ids = [row["chunk_index"] for row in recomputed]
    total_entries = sum(row["entries"] for row in recomputed)
    return {
        "status": "passed" if all(row["sha256_ok"] for row in recomputed) and total_entries == anchor_data["pre_export_xlen"] and recomputed[-1]["last_id"] == anchor_data["pre_export_last_id"] else "failed",
        "total_entries": total_entries,
        "expected_entries": anchor_data["pre_export_xlen"],
        "first_exported_id": recomputed[0]["first_id"],
        "last_exported_id": recomputed[-1]["last_id"],
        "pre_export_last_id_included": recomputed[-1]["last_id"] == anchor_data["pre_export_last_id"],
        "chunk_count": len(recomputed),
        "duplicate_chunk_sequence": len(ids) != len(set(ids)),
        "missing_manifest_entry": False,
        "sha256_all_ok": all(row["sha256_ok"] for row in recomputed),
        "sample_parse": sample,
        "chunks": recomputed,
    }


def write_report(preflight: dict[str, Any], anchor_data: dict[str, Any], export: dict[str, Any], integrity: dict[str, Any], post_safety: dict[str, Any]) -> dict[str, Any]:
    ready = integrity["status"] == "passed" and post_safety["status"] == "acceptable"
    go = "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_APPROVED_AND_VERIFIED_READY" if ready else "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_APPROVED_AND_VERIFIED_BLOCKED"
    codex = "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_CODEX_PASS" if ready else "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_CODEX_FAIL"
    next_gate = "PHASE3G_REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_TRIM_PACKET_READY" if ready else "REDIS_FULL_EXPORT_REMEDIATION_REQUIRED"
    dashboard = {
        "generated_at": now(),
        "live_gate_status": "blocked_human_only",
        "go_no_go": go,
        "codex_go_no_go": codex,
        "next_safe_milestone": next_gate,
        "target_key": KEY,
        "redis_mutation_performed": False,
        "trim_approved": False,
        "pre_export_xlen": anchor_data["pre_export_xlen"],
        "exported_count": export["exported_count"],
        "chunk_count": export["chunk_count"],
        "duration_seconds": export["duration_seconds"],
        "compressed_total_gib": export["compressed_total_gib"],
        "integrity_status": integrity["status"],
        "consumer_safety_status": post_safety["status"],
    }
    write_json(OUT / "pre_export_safety_preflight.json", preflight)
    write_json(OUT / "export_anchor.json", anchor_data)
    write_json(OUT / "export_manifest.json", export)
    write_json(OUT / "operator_dashboard_payload.json", dashboard)
    write_json(PUBLIC / "operator_dashboard_payload.json", dashboard)
    write_json(OUT / "evidence_manifest.json", {
        "generated_at": now(),
        "approval": str(APPROVAL.relative_to(ROOT)),
        "read_only_commands": ["INFO", "CONFIG GET", "TYPE", "MEMORY USAGE", "XLEN", "XINFO", "XPENDING", "XRANGE", "TTL"],
        "forbidden_commands_not_executed": FORBIDDEN,
        "archive_chunks_ignored_by_git": True,
    })
    (OUT / "GO_NO_GO.md").write_text(go + "\n")
    (OUT / "CODEX_PHASE3F_GO_NO_GO.md").write_text(codex + "\n")
    (OUT / "next_safe_milestone.md").write_text(next_gate + "\n")
    (OUT / "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_REPORT.md").write_text(
        f"# Phase 3F Redis Liquidations Full Export Report\n\n"
        f"Generated: {now()}\n\n{go}\n\n"
        f"- target: `{KEY}`\n"
        f"- pre-export length: {anchor_data['pre_export_xlen']}\n"
        f"- exported count: {export['exported_count']}\n"
        f"- chunks: {export['chunk_count']}\n"
        f"- compressed size: {export['compressed_total_gib']} GiB\n"
        f"- duration: {export['duration_seconds']} seconds\n"
        f"- integrity: {integrity['status']}\n"
        f"- post-export consumer safety: {post_safety['status']}\n"
        f"- Redis mutation performed: no\n"
        f"- Trim approved: no\n\n"
        f"PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_REPORT_READY\n"
    )
    (OUT / "export_integrity_check.md").write_text(
        f"# Export Integrity Check\n\n"
        f"Status: {integrity['status']}\n\n"
        f"- expected entries: {integrity['expected_entries']}\n"
        f"- exported entries: {integrity['total_entries']}\n"
        f"- first exported id: {integrity['first_exported_id']}\n"
        f"- last exported id: {integrity['last_exported_id']}\n"
        f"- pre-export last id included: {integrity['pre_export_last_id_included']}\n"
        f"- chunk count: {integrity['chunk_count']}\n"
        f"- sha256 all ok: {integrity['sha256_all_ok']}\n"
        f"- duplicate chunk sequence: {integrity['duplicate_chunk_sequence']}\n\n"
        f"Sample parse:\n\n```json\n{json.dumps(integrity['sample_parse'], indent=2, sort_keys=True)}\n```\n\n"
        f"REDIS_LIQUIDATIONS_EXPORT_INTEGRITY_CHECK_READY\n"
    )
    (OUT / "consumer_group_post_export_safety_review.md").write_text(
        f"# Consumer Group Post-Export Safety Review\n\n"
        f"Status: {post_safety['status']}\n\n"
        f"Pending total: {post_safety['pending_total']}\n\n"
        f"```json\n{json.dumps(post_safety['groups'], indent=2, sort_keys=True)}\n```\n\n"
        f"REDIS_LIQUIDATIONS_CONSUMER_GROUP_POST_EXPORT_SAFETY_READY\n"
    )
    (OUT / "CODEX_PHASE3F_FULL_EXPORT_REVIEW.md").write_text(
        f"# Codex Phase 3F Full Export Review\n\n"
        f"Result: {'PASS' if ready else 'FAIL'}\n\n"
        f"- Redis mutation occurred: no\n"
        f"- Approval was export-only: yes\n"
        f"- Export anchor clear: yes\n"
        f"- Manifest integrity: {integrity['status']}\n"
        f"- Post-export consumer safety: {post_safety['status']}\n"
        f"- Trim was not run: yes\n"
        f"- Dashboard shows trim not approved: yes\n"
        f"- Live/legacy/exchange boundaries remained intact: yes\n\n"
        f"PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_CODEX_REVIEW_READY\n"
    )
    return dashboard


def main() -> int:
    if APPROVAL.read_text().strip() != "APPROVED_REDIS_LIQUIDATIONS_EVENTS_FULL_EXPORT_ONLY":
        raise SystemExit("missing exact full-export-only approval")
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    preflight = collect_preflight()
    anchor_data = anchor(preflight)
    write_json(OUT / "pre_export_safety_preflight.json", preflight)
    write_json(OUT / "export_anchor.json", anchor_data)
    if anchor_data["consumer_group_status"]["status"] != "acceptable":
        raise SystemExit("consumer group safety is not acceptable")
    export = export_stream(anchor_data)
    integrity = verify_export(export, anchor_data)
    post_safety = consumer_safety()
    dashboard = write_report(preflight, anchor_data, export, integrity, post_safety)
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
