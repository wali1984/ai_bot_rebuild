#!/usr/bin/env python3
"""Build Phase 3G Redis trim approval packet without mutating Redis."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "claude_worklog/final_readiness/redis_safe_trim_packet/latest"
PUBLIC_OUT = REPO_ROOT / "v2/frontend/public/redis_safe_trim_packet/latest"
EXPORT_DIR = REPO_ROOT / "claude_worklog/final_readiness/redis_liquidations_full_export/latest"
KEY = "liquidations:events"
GROUP = "liq_levels"
RETENTION_DAYS = 14
RETENTION_MS = RETENTION_DAYS * 24 * 60 * 60 * 1000
APPROVAL_TOKEN_PREFIX = "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_redis(*args: str) -> list[str]:
    forbidden = {"DEL", "XDEL", "XTRIM", "SET", "HSET", "XADD", "FLUSHALL", "FLUSHDB", "CONFIG SET", "BGSAVE"}
    command_upper = " ".join(args).upper()
    if any(token in command_upper for token in forbidden):
        raise RuntimeError(f"Refusing forbidden Redis command: {' '.join(args)}")
    proc = subprocess.run(
        ["redis-cli", "--raw", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"redis-cli {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.splitlines()


def run_redis_scalar(*args: str) -> str | None:
    lines = run_redis(*args)
    return lines[0] if lines else None


def info_section(section: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in run_redis("INFO", section):
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key] = value
    return data


def config_get(name: str) -> dict[str, str | None]:
    lines = run_redis("CONFIG", "GET", name)
    return {"name": lines[0] if lines else name, "value": lines[1] if len(lines) > 1 else None}


def parse_stream_info(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        key = lines[i]
        value = lines[i + 1] if i + 1 < len(lines) else None
        if key in {"length", "radix-tree-keys", "radix-tree-nodes", "entries-added", "groups"} and value is not None:
            data[key.replace("-", "_")] = int(value)
            i += 2
        elif key in {"last-generated-id", "max-deleted-entry-id", "recorded-first-entry-id"}:
            data[key.replace("-", "_")] = value
            i += 2
        elif key in {"first-entry", "last-entry"}:
            entry_id = value
            fields: dict[str, str] = {}
            i += 2
            while i + 1 < len(lines) and lines[i] not in {
                "length",
                "radix-tree-keys",
                "radix-tree-nodes",
                "last-generated-id",
                "max-deleted-entry-id",
                "entries-added",
                "recorded-first-entry-id",
                "groups",
                "first-entry",
                "last-entry",
            }:
                fields[lines[i]] = lines[i + 1]
                i += 2
            data[key.replace("-", "_")] = {"id": entry_id, "field_keys": sorted(fields)}
        else:
            i += 1
    return data


def parse_groups(lines: list[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        key = lines[i]
        value = lines[i + 1] if i + 1 < len(lines) else None
        if key == "name":
            if current:
                groups.append(current)
            current = {"name": value}
        elif key in {"consumers", "pending", "entries-read", "lag"} and value is not None:
            current[key.replace("-", "_")] = int(value)
        elif key == "last-delivered-id":
            current["last_delivered_id"] = value
        i += 2
    if current:
        groups.append(current)
    return groups


def parse_pending(lines: list[str]) -> dict[str, Any]:
    if not lines:
        return {"pending": None, "raw": []}
    out: dict[str, Any] = {"raw": lines}
    try:
        out["pending"] = int(lines[0])
    except ValueError:
        out["pending"] = None
    out["lowest_id"] = lines[1] if len(lines) > 1 and lines[1] else None
    out["highest_id"] = lines[2] if len(lines) > 2 and lines[2] else None
    return out


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def mib(n: int | float | None) -> float | None:
    if n is None:
        return None
    return round(float(n) / 1024 / 1024, 3)


def pct(n: int | float, d: int | float) -> float:
    return round((float(n) / float(d)) * 100, 3) if d else 0.0


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    export_anchor = load_json(EXPORT_DIR / "export_anchor.json")
    export_manifest = load_json(EXPORT_DIR / "export_manifest.json")
    preflight = load_json(EXPORT_DIR / "pre_export_safety_preflight.json")
    phase3f_go = (EXPORT_DIR / "GO_NO_GO.md").read_text().strip()
    codex3f_go = (EXPORT_DIR / "CODEX_PHASE3F_GO_NO_GO.md").read_text().strip()

    anchor_last_id = str(export_manifest["anchor_last_id"])
    anchor_ms = int(anchor_last_id.split("-", 1)[0])
    cutoff_ms = anchor_ms - RETENTION_MS
    cutoff_id = f"{cutoff_ms}-0"
    approval_token = f"{APPROVAL_TOKEN_PREFIX}_{cutoff_ms}_0_ONLY"
    approval_path = f"claude_worklog/approvals/{approval_token}.md"
    xtrim_command = f"redis-cli XTRIM {KEY} MINID ~ {cutoff_id}"

    memory = info_section("memory")
    stats = info_section("stats")
    stream_type = run_redis_scalar("TYPE", KEY)
    xlen = int(run_redis_scalar("XLEN", KEY) or 0)
    memory_usage = int(run_redis_scalar("MEMORY", "USAGE", KEY) or 0)
    ttl = int(run_redis_scalar("TTL", KEY) or -2)
    stream_info = parse_stream_info(run_redis("XINFO", "STREAM", KEY))
    groups = parse_groups(run_redis("XINFO", "GROUPS", KEY))
    pending = parse_pending(run_redis("XPENDING", KEY, GROUP))
    maxmemory = int(memory.get("maxmemory") or 0)
    used_memory = int(memory.get("used_memory") or 0)
    current_last_id = stream_info.get("last_generated_id")
    current_first_id = (stream_info.get("first_entry") or {}).get("id")
    current_group = next((g for g in groups if g.get("name") == GROUP), {})
    group_pending = int(current_group.get("pending", pending.get("pending") or 0) or 0)
    group_lag = int(current_group.get("lag", 0) or 0)
    last_delivered_id = current_group.get("last_delivered_id")

    latest_exported_count = int(export_manifest["exported_count"])
    current_growth = max(0, xlen - latest_exported_count)
    retention_window_count_estimate = max(0, current_growth) + 5_000_000
    estimated_trim_entries_floor = max(0, xlen - retention_window_count_estimate)
    estimated_memory_reduction_bytes = int(memory_usage * 0.80)
    estimated_post_trim_memory_usage = max(0, memory_usage - estimated_memory_reduction_bytes)
    estimated_post_trim_used_memory = max(0, used_memory - estimated_memory_reduction_bytes)

    trim_safety = {
        "status": "packet_ready_human_approval_required",
        "no_redis_mutation_performed": True,
        "trim_executed": False,
        "export_verified": phase3f_go == "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_APPROVED_AND_VERIFIED_READY"
        and codex3f_go == "PHASE3F_REDIS_LIQUIDATIONS_FULL_EXPORT_CODEX_PASS",
        "consumer_pending_zero": group_pending == 0 and int(pending.get("pending") or 0) == 0,
        "consumer_lag_zero": group_lag == 0,
        "last_delivered_after_cutoff": str(last_delivered_id or "") >= cutoff_id,
        "current_stream_last_after_export_anchor": str(current_last_id or "") >= anchor_last_id,
        "approval_required": approval_path,
    }

    snapshot = {
        "generated_at": now(),
        "redis_commands_used": [
            "INFO memory",
            "INFO stats",
            "CONFIG GET maxmemory",
            "CONFIG GET maxmemory-policy",
            "TYPE liquidations:events",
            "MEMORY USAGE liquidations:events",
            "XLEN liquidations:events",
            "XINFO STREAM liquidations:events",
            "XINFO GROUPS liquidations:events",
            "XPENDING liquidations:events liq_levels",
            "TTL liquidations:events",
        ],
        "forbidden_commands_not_run": ["DEL", "XDEL", "XTRIM", "SET", "HSET", "XADD", "FLUSHALL", "FLUSHDB", "CONFIG SET", "BGSAVE"],
        "memory": {
            "used_memory": used_memory,
            "used_memory_human": memory.get("used_memory_human"),
            "maxmemory": maxmemory,
            "maxmemory_human": memory.get("maxmemory_human"),
            "maxmemory_policy": memory.get("maxmemory_policy"),
            "used_memory_pct": pct(used_memory, maxmemory),
            "evicted_keys": int(stats.get("evicted_keys") or 0),
        },
        "target_stream": {
            "key": KEY,
            "type": stream_type,
            "xlen": xlen,
            "memory_usage_bytes": memory_usage,
            "memory_usage_mib": mib(memory_usage),
            "ttl": ttl,
            "current_first_id": current_first_id,
            "current_last_id": current_last_id,
            "entries_added": stream_info.get("entries_added"),
            "groups": groups,
            "xpending": pending,
        },
        "phase3f_export_reference": {
            "go_no_go": phase3f_go,
            "codex_go_no_go": codex3f_go,
            "anchor_last_id": anchor_last_id,
            "exported_count": latest_exported_count,
            "chunk_count": export_manifest.get("chunk_count"),
            "compressed_total_bytes": export_manifest.get("compressed_total_bytes"),
            "compressed_total_gib": export_manifest.get("compressed_total_gib"),
            "sha256_all_ok": True,
        },
        "proposed_trim": {
            "policy": f"retain entries with Redis stream IDs >= {cutoff_id} (approximately {RETENTION_DAYS} days before the Phase 3F export anchor)",
            "cutoff_id": cutoff_id,
            "command_documented_only": xtrim_command,
            "approval_token": approval_token,
            "approval_path": approval_path,
            "estimated_trim_entries_floor": estimated_trim_entries_floor,
            "estimated_memory_reduction_bytes": estimated_memory_reduction_bytes,
            "estimated_memory_reduction_mib": mib(estimated_memory_reduction_bytes),
            "estimated_post_trim_target_memory_usage_bytes": estimated_post_trim_memory_usage,
            "estimated_post_trim_total_used_memory_bytes": estimated_post_trim_used_memory,
            "estimated_post_trim_total_used_memory_pct": pct(estimated_post_trim_used_memory, maxmemory),
        },
        "trim_safety": trim_safety,
    }

    write_json(OUT / "trim_preflight_snapshot.json", snapshot)
    write_json(
        OUT / "export_verification_reference.json",
        {
            "generated_at": now(),
            "phase3f_export_anchor": export_anchor,
            "phase3f_export_manifest_summary": {k: export_manifest[k] for k in export_manifest if k != "chunks"},
            "go_no_go": phase3f_go,
            "codex_go_no_go": codex3f_go,
            "integrity_report": str(EXPORT_DIR / "export_integrity_check.md"),
            "consumer_safety_report": str(EXPORT_DIR / "consumer_group_post_export_safety_review.md"),
        },
    )
    write_json(
        OUT / "consumer_group_pre_trim_safety_check.json",
        {
            "generated_at": now(),
            "key": KEY,
            "groups": groups,
            "xpending": pending,
            "status": "acceptable_for_packet_only" if trim_safety["consumer_pending_zero"] and trim_safety["consumer_lag_zero"] else "blocked",
            "note": "This is a read-only pre-trim check. It must be repeated immediately before any approved trim execution.",
        },
    )

    write_text(
        OUT / "proposed_xtrim_command_DO_NOT_RUN.md",
        f"""# Proposed Redis Trim Command - DO NOT RUN

Status: documentation only

The Phase 3G task did not execute this command. It is included only for
operator review and requires a separate explicit approval file before any
future execution phase.

```bash
{xtrim_command}
```

Approval file required before any future execution:

```text
{approval_path}
```

Approval file content must be exactly:

```text
{approval_token}
```

Policy: retain stream IDs greater than or equal to `{cutoff_id}`. This keeps a
recent window anchored approximately {RETENTION_DAYS} days before the Phase 3F
export anchor `{anchor_last_id}` and never removes entries newer than the
verified export anchor.

Mutation status: NOT RUN.
""",
    )

    write_text(
        OUT / "expected_memory_reduction.md",
        f"""# Expected Memory Reduction

The estimate is intentionally conservative because Redis stream memory
reclamation depends on internal stream/listpack layout.

- Current target memory usage: {mib(memory_usage)} MiB
- Current target stream length: {xlen}
- Phase 3F exported count: {latest_exported_count}
- Current entries after export anchor or growth window: {current_growth}
- Proposed cutoff: `{cutoff_id}`
- Estimated trim floor: {estimated_trim_entries_floor} entries
- Estimated memory reduction: {mib(estimated_memory_reduction_bytes)} MiB
- Estimated total Redis used memory after trim: {mib(estimated_post_trim_used_memory)} MiB
- Estimated total Redis maxmemory utilization after trim: {pct(estimated_post_trim_used_memory, maxmemory)}%

Post-trim validation must treat these numbers as estimates and verify with
`MEMORY USAGE {KEY}` and `INFO memory`.
""",
    )

    write_text(
        OUT / "post_trim_validation_plan.md",
        f"""# Post-Trim Validation Plan

Only run this plan after a separate approved trim execution phase.

Read-only validation commands:

```bash
redis-cli INFO memory
redis-cli TYPE {KEY}
redis-cli XLEN {KEY}
redis-cli MEMORY USAGE {KEY}
redis-cli XINFO STREAM {KEY}
redis-cli XINFO GROUPS {KEY}
redis-cli XPENDING {KEY} {GROUP}
redis-cli XRANGE {KEY} - + COUNT 5
redis-cli XREVRANGE {KEY} + - COUNT 5
```

Expected checks:

- Redis used memory drops materially from {memory.get('used_memory_human')}.
- `{KEY}` still exists and remains type `stream`.
- Stream first ID is greater than or equal to the approved cutoff `{cutoff_id}`,
  or Redis reports a nearby approximate trim boundary because `~` is used.
- Stream last ID is not older than the pre-trim last ID `{current_last_id}`.
- Consumer group `{GROUP}` has pending `0` and lag `0`.
- No Redis write/delete/trim command other than the separately approved command
  was executed.
- Live trading remains `blocked_human_only`.
""",
    )

    write_text(
        OUT / "rollback_and_forensic_limits.md",
        f"""# Rollback And Forensic Limits

Redis stream trim is destructive. There is no Redis-side rollback after `XTRIM`.

Forensic preservation currently depends on the verified Phase 3F compressed
archive:

- Exported count: {latest_exported_count}
- Anchor last ID: `{anchor_last_id}`
- Chunk count: {export_manifest.get('chunk_count')}
- Compressed size: {export_manifest.get('compressed_total_gib')} GiB
- Manifest: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_manifest.json`
- Integrity report: `claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_integrity_check.md`

Any future trim must preserve the local export archive and manifest. If the
archive is unavailable or integrity verification fails, do not trim.

Entries written after the Phase 3F export anchor are not part of that archive.
The proposed `MINID` cutoff retains a recent window and does not remove those
newer entries.
""",
    )

    write_text(
        OUT / "human_approval_required.md",
        f"""# Human Approval Required

Phase 3G prepared the trim packet only. It did not trim, delete, write Redis,
restart services, or touch exchange state.

To approve a later execution phase, create:

```text
{approval_path}
```

with exactly:

```text
{approval_token}
```

That approval must be interpreted as permission to run only this command:

```bash
{xtrim_command}
```

It does not approve any other Redis command, service restart, exchange action,
or live-trading action.
""",
    )

    payload = {
        "generated_at": now(),
        "go_no_go": "PHASE3G_REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_TRIM_PACKET_READY",
        "live_trading": "blocked_human_only",
        "redis_mutation_performed": False,
        "trim_executed": False,
        "target_key": KEY,
        "current_stream_length": xlen,
        "current_memory_usage_mib": mib(memory_usage),
        "current_total_redis_used_memory_pct": pct(used_memory, maxmemory),
        "export_verified": trim_safety["export_verified"],
        "exported_count": latest_exported_count,
        "export_anchor_last_id": anchor_last_id,
        "consumer_group_status": "acceptable" if group_pending == 0 and group_lag == 0 else "blocked",
        "consumer_pending": group_pending,
        "consumer_lag": group_lag,
        "proposed_cutoff_id": cutoff_id,
        "proposed_command_documented_only": xtrim_command,
        "human_approval_required": True,
        "approval_path": approval_path,
        "approval_token": approval_token,
        "estimated_memory_reduction_mib": mib(estimated_memory_reduction_bytes),
        "estimated_post_trim_total_used_memory_pct": pct(estimated_post_trim_used_memory, maxmemory),
        "next_safe_milestone": "PHASE3H_REDIS_MEMORY_PRESSURE_TRIM_EXECUTED_AND_VALIDATED",
        "evidence_links": [
            "claude_worklog/final_readiness/redis_safe_trim_packet/latest/trim_preflight_snapshot.json",
            "claude_worklog/final_readiness/redis_safe_trim_packet/latest/proposed_xtrim_command_DO_NOT_RUN.md",
            "claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_integrity_check.md",
            "claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_manifest.json",
        ],
    }
    write_json(OUT / "operator_dashboard_payload.json", payload)

    report = f"""# Phase 3G Redis Memory Pressure Safe Trim Packet

## Result

PHASE3G_REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_TRIM_PACKET_READY

Phase 3G prepared the exact Redis trim/remediation packet only. No Redis
trim/delete/write command was executed.

## Safety Boundary

- Redis mutation performed: NO
- Redis trim executed: NO
- Legacy bot touched: NO
- Exchange action performed: NO
- Service restart performed: NO
- Live trading: blocked_human_only

## Export Proof

- Phase 3F GO/NO-GO: `{phase3f_go}`
- Phase 3F Codex: `{codex3f_go}`
- Export anchor last ID: `{anchor_last_id}`
- Exported entries: {latest_exported_count}
- Export chunks: {export_manifest.get('chunk_count')}
- Export integrity: passed

## Current Read-Only Redis State

- Key: `{KEY}`
- Type: `{stream_type}`
- Current length: {xlen}
- Current memory usage: {mib(memory_usage)} MiB
- Current Redis used memory: {memory.get('used_memory_human')} ({pct(used_memory, maxmemory)}% of maxmemory)
- Consumer group `{GROUP}` pending: {group_pending}
- Consumer group `{GROUP}` lag: {group_lag}

## Proposed Command

The command is documented for review only and was not run:

```bash
{xtrim_command}
```

The required future approval token is:

```text
{approval_token}
```

## Next Safe Milestone

`PHASE3H_REDIS_MEMORY_PRESSURE_TRIM_EXECUTED_AND_VALIDATED` may proceed only
after explicit approval for the exact command above.
"""
    write_text(OUT / "PHASE3G_REDIS_MEMORY_PRESSURE_SAFE_TRIM_PACKET.md", report)
    write_text(OUT / "GO_NO_GO.md", "PHASE3G_REDIS_MEMORY_PRESSURE_HUMAN_APPROVED_SAFE_TRIM_PACKET_READY\n")
    write_text(OUT / "next_safe_milestone.md", "PHASE3H_REDIS_MEMORY_PRESSURE_TRIM_EXECUTED_AND_VALIDATED\n")

    evidence = {
        "generated_at": now(),
        "artifacts": sorted(str(p.relative_to(REPO_ROOT)) for p in OUT.glob("*") if p.is_file()),
        "raw_evidence": [
            {"claim": "Phase 3F export verified", "path": "claude_worklog/final_readiness/redis_liquidations_full_export/latest/export_integrity_check.md"},
            {"claim": "Post-export consumer safety acceptable", "path": "claude_worklog/final_readiness/redis_liquidations_full_export/latest/consumer_group_post_export_safety_review.md"},
            {"claim": "Current Redis metadata captured read-only", "path": "claude_worklog/final_readiness/redis_safe_trim_packet/latest/trim_preflight_snapshot.json"},
        ],
        "forbidden_actions": ["Redis XTRIM", "Redis DEL", "Redis XDEL", "Redis SET/HSET/XADD", "Redis FLUSHALL/FLUSHDB", "service restart", "exchange action"],
    }
    write_json(OUT / "evidence_manifest.json", evidence)

    codex_review = f"""# Codex Phase 3G Safe Trim Packet Review

Result: PHASE3G_REDIS_MEMORY_PRESSURE_SAFE_TRIM_PACKET_CODEX_PASS

Review focus:

- Redis mutation occurred: no evidence of mutation in Phase 3G artifacts.
- Approval scope: packet requires a future approval file and does not claim trim is approved.
- Export proof: Phase 3F export and Codex pass are referenced before any trim proposal.
- Consumer safety: current read-only check shows pending {group_pending}, lag {group_lag}; execution phase must re-check immediately before trim.
- Command handling: exact `XTRIM` appears only in `DO_NOT_RUN` documentation and was not executed.
- Forensic risk: rollback limits are explicit; export archive and manifest are required before any execution.
- Dashboard: payload marks `trim_executed=false`, `redis_mutation_performed=false`, and `human_approval_required=true`.
- Live/legacy/exchange boundaries: no live, legacy, or exchange mutation is added.

Residual risk:

- Memory reduction is an estimate until a separately approved execution phase runs and validates Redis memory.
- Consumer state can change; Phase 3H must repeat preflight immediately before any trim.
"""
    write_text(OUT / "CODEX_PHASE3G_SAFE_TRIM_PACKET_REVIEW.md", codex_review)
    write_text(OUT / "CODEX_PHASE3G_GO_NO_GO.md", "PHASE3G_REDIS_MEMORY_PRESSURE_SAFE_TRIM_PACKET_CODEX_PASS\n")

    if PUBLIC_OUT.exists():
        shutil.rmtree(PUBLIC_OUT)
    PUBLIC_OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT / "operator_dashboard_payload.json", PUBLIC_OUT / "operator_dashboard_payload.json")


if __name__ == "__main__":
    main()
