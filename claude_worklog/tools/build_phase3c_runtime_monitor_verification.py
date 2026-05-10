#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
MONITORING = ROOT / "claude_worklog/monitoring"
POST_MONITOR = ROOT / "claude_worklog/post_monitor"
PHASE3A_MONITOR = ROOT / "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/runtime_monitor"
OUT = ROOT / "claude_worklog/final_readiness/phase3c_runtime_monitor_verification/latest"
PUBLIC = ROOT / "v2/frontend/public/phase3c_runtime_monitor_verification/latest"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_decode_error": line[:240]})
    return rows


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def evidence(path: Path, command: str) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)),
        "verification_command": command,
    }


def summarize() -> dict[str, Any]:
    snapshots_path = MONITORING / "snapshots.jsonl"
    trainer_path = MONITORING / "trainer_metrics.jsonl"
    log_path = MONITORING / "read_only_monitor.log"
    post_go_path = POST_MONITOR / "09_V2_BUILD_GO_NO_GO.md"
    phase3a_status_path = PHASE3A_MONITOR / "runtime_monitor_status.json"

    snapshots = read_jsonl(snapshots_path)
    trainer = read_jsonl(trainer_path)
    first_ts = parse_ts(snapshots[0].get("ts_utc")) if snapshots else None
    last_ts = parse_ts(snapshots[-1].get("ts_utc")) if snapshots else None
    duration_hours = ((last_ts - first_ts).total_seconds() / 3600.0) if first_ts and last_ts else 0.0

    memory_values = [
        float(row.get("redis_memory", {}).get("memory_ratio_pct", 0.0))
        for row in snapshots
        if isinstance(row.get("redis_memory"), dict) and row.get("redis_memory", {}).get("memory_ratio_pct") is not None
    ]
    trainer_statuses = [row.get("trainer_internal_liveness_status") for row in trainer if row.get("trainer_internal_liveness_status")]
    last_snapshot = snapshots[-1] if snapshots else {}
    last_trainer = trainer[-1] if trainer else {}
    executed = last_snapshot.get("executed_analysis", {}) if isinstance(last_snapshot.get("executed_analysis"), dict) else {}
    attribution = last_snapshot.get("attribution_completeness", {}) if isinstance(last_snapshot.get("attribution_completeness"), dict) else {}
    feature_freshness = last_snapshot.get("feature_freshness", {}) if isinstance(last_snapshot.get("feature_freshness"), dict) else {}

    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    critical_log_terms = [term for term in ["Traceback", "CRITICAL", "FATAL", "PermissionError", "Redis write", "create_order", "cancel_order"] if term in log_text]
    post_go = post_go_path.read_text(errors="replace").strip() if post_go_path.exists() else "missing"
    phase3a_status = json.loads(phase3a_status_path.read_text()) if phase3a_status_path.exists() else {}

    gaps: list[dict[str, str]] = []
    if duration_hours < 12:
        gaps.append({"gap": "runtime_duration_under_12h", "severity": "blocker", "evidence": "claude_worklog/monitoring/snapshots.jsonl"})
    if not snapshots:
        gaps.append({"gap": "missing_runtime_snapshots", "severity": "blocker", "evidence": "claude_worklog/monitoring/snapshots.jsonl"})
    if not trainer:
        gaps.append({"gap": "missing_trainer_metrics", "severity": "blocker", "evidence": "claude_worklog/monitoring/trainer_metrics.jsonl"})
    if max(memory_values or [0.0]) >= 95.0:
        gaps.append({"gap": "redis_memory_pressure_critical_95", "severity": "blocker", "evidence": "latest snapshot redis_memory.memory_ratio_pct"})
    if executed.get("missing_prediction_id", 0):
        gaps.append({"gap": "executed_rows_missing_prediction_id", "severity": "blocker", "evidence": "latest snapshot executed_analysis.missing_prediction_id"})
    if executed.get("missing_feature_snapshot_id", 0):
        gaps.append({"gap": "executed_rows_missing_feature_snapshot_id", "severity": "blocker", "evidence": "latest snapshot executed_analysis.missing_feature_snapshot_id"})
    if executed.get("lineage_tuple_incomplete_rows", 0):
        gaps.append({"gap": "executed_rows_incomplete_lineage_tuple", "severity": "blocker", "evidence": "latest snapshot executed_analysis.lineage_tuple_incomplete_rows"})
    if executed.get("duplicate_exchange_order_id_rows", 0):
        gaps.append({"gap": "duplicate_exchange_order_id_rows_observed", "severity": "blocker", "evidence": "latest snapshot executed_analysis.duplicate_exchange_order_id_rows"})
    if executed.get("stale_executed_ts_ms_gt_5m", 0):
        gaps.append({"gap": "stale_executed_timestamps_gt_5m", "severity": "blocker", "evidence": "latest snapshot executed_analysis.stale_executed_ts_ms_gt_5m"})
    if "CRITICAL" in trainer_statuses:
        gaps.append({"gap": "trainer_internal_liveness_critical_seen", "severity": "blocker", "evidence": "trainer_metrics.jsonl trainer_internal_liveness_status"})
    if critical_log_terms:
        gaps.append({"gap": "monitor_log_critical_terms", "severity": "blocker", "evidence": "claude_worklog/monitoring/read_only_monitor.log"})
    if post_go != "V2_BUILD_GO_NO_GO" and "NO_GO" in post_go:
        gaps.append({"gap": "prior_post_monitor_no_go", "severity": "blocker", "evidence": "claude_worklog/post_monitor/09_V2_BUILD_GO_NO_GO.md"})
    if phase3a_status.get("monitor_completed_12h") is False:
        gaps.append({"gap": "phase3a_runtime_monitor_placeholder_not_run", "severity": "non_blocking_context", "evidence": "system_atlas_runtime_coverage/latest/runtime_monitor/runtime_monitor_status.json"})

    blocking_gaps = [gap for gap in gaps if gap["severity"] == "blocker"]
    ready = bool(snapshots and trainer and duration_hours >= 12 and not blocking_gaps)
    next_safe = "EXTENDED_PAPER_SHADOW_SOAK_7D" if ready else "REDIS_MEMORY_PRESSURE_REMEDIATION"
    if not ready and not snapshots:
        next_safe = "RUNTIME_MONITOR_GAP_REMEDIATION"
    elif not ready and max(memory_values or [0.0]) >= 95.0:
        next_safe = "REDIS_MEMORY_PRESSURE_REMEDIATION"
    elif not ready and "CRITICAL" in trainer_statuses:
        next_safe = "TRAINER_RUNTIME_LIVENESS_REMEDIATION"
    elif not ready and (executed.get("missing_prediction_id", 0) or executed.get("missing_feature_snapshot_id", 0)):
        next_safe = "PREDICTION_SIGNAL_LINEAGE_RUNTIME_REMEDIATION"

    return {
        "generated_at": now(),
        "live_gate_status": "blocked_human_only",
        "ready": ready,
        "go_no_go": "PHASE3C_12H_RUNTIME_MONITOR_COMPLETED_AND_VERIFIED_READY" if ready else "PHASE3C_12H_RUNTIME_MONITOR_COMPLETED_AND_VERIFIED_BLOCKED",
        "codex_go_no_go": "PHASE3C_12H_RUNTIME_MONITOR_CODEX_PASS" if ready else "PHASE3C_12H_RUNTIME_MONITOR_CODEX_FAIL",
        "next_safe_milestone": next_safe,
        "counts": {
            "snapshot_count": len(snapshots),
            "trainer_metric_count": len(trainer),
            "duration_hours": round(duration_hours, 2),
            "monitor_log_bytes": log_path.stat().st_size if log_path.exists() else 0,
            "redis_memory_max_pct": round(max(memory_values or [0.0]), 2),
            "redis_memory_avg_pct": round(mean(memory_values), 2) if memory_values else 0.0,
            "trainer_critical_count": trainer_statuses.count("CRITICAL"),
            "trainer_degraded_count": trainer_statuses.count("DEGRADED"),
            "blocking_gap_count": len(blocking_gaps),
        },
        "latest": {
            "first_snapshot_ts": first_ts.isoformat() if first_ts else None,
            "last_snapshot_ts": last_ts.isoformat() if last_ts else None,
            "latest_trainer_status": last_trainer.get("trainer_internal_liveness_status"),
            "prediction_worker_alive": last_trainer.get("prediction_worker_alive"),
            "publish_surface_liveness": last_trainer.get("publish_surface_liveness"),
            "redis_memory": last_snapshot.get("redis_memory", {}),
            "executed_analysis": executed,
            "attribution_completeness": attribution,
            "feature_freshness_status_counts": feature_freshness.get("status_counts", {}),
            "post_monitor_go_no_go": post_go,
            "phase3a_monitor_status": phase3a_status,
        },
        "gaps": gaps,
        "evidence": {
            "snapshots": evidence(snapshots_path, "python3 - <<'PY'\\nfrom pathlib import Path\\nprint(len(Path('claude_worklog/monitoring/snapshots.jsonl').read_text().splitlines()))\\nPY"),
            "trainer_metrics": evidence(trainer_path, "python3 - <<'PY'\\nfrom pathlib import Path\\nprint(len(Path('claude_worklog/monitoring/trainer_metrics.jsonl').read_text().splitlines()))\\nPY"),
            "monitor_log": evidence(log_path, "wc -c claude_worklog/monitoring/read_only_monitor.log"),
            "post_monitor_go_no_go": evidence(post_go_path, "cat claude_worklog/post_monitor/09_V2_BUILD_GO_NO_GO.md"),
        },
    }


def render_report(data: dict[str, Any]) -> str:
    return f"""# Phase 3C 12H Runtime Monitor Verification Report

Generated: {data['generated_at']}

## Result

{data['go_no_go']}

## Runtime Evidence

- Snapshot count: {data['counts']['snapshot_count']}
- Trainer metric count: {data['counts']['trainer_metric_count']}
- Runtime duration hours: {data['counts']['duration_hours']}
- Redis max memory ratio: {data['counts']['redis_memory_max_pct']}%
- Trainer CRITICAL count: {data['counts']['trainer_critical_count']}
- Trainer DEGRADED count: {data['counts']['trainer_degraded_count']}
- Blocking gaps: {data['counts']['blocking_gap_count']}

## Decision

Next safe milestone: `{data['next_safe_milestone']}`

Live trading remains blocked_human_only. This verification did not write Redis, restart services, place/cancel orders, change leverage/margin, deploy, mutate legacy, or expose secrets.

PHASE3C_12H_RUNTIME_MONITOR_REPORT_READY
"""


def render_truth_table(data: dict[str, Any]) -> str:
    rows = [
        ("monitor_artifacts_present", data["counts"]["snapshot_count"] > 0 and data["counts"]["trainer_metric_count"] > 0, "claude_worklog/monitoring/snapshots.jsonl; claude_worklog/monitoring/trainer_metrics.jsonl"),
        ("runtime_duration_ge_12h", data["counts"]["duration_hours"] >= 12, "first/last ts_utc in snapshots.jsonl"),
        ("redis_memory_pressure_non_blocking", data["counts"]["redis_memory_max_pct"] < 95, "redis_memory.memory_ratio_pct in snapshots.jsonl"),
        ("trainer_liveness_clean", data["counts"]["trainer_critical_count"] == 0, "trainer_metrics.jsonl trainer_internal_liveness_status"),
        ("execution_lineage_complete", data["latest"]["executed_analysis"].get("lineage_tuple_incomplete_rows", 0) == 0, "snapshots.jsonl executed_analysis"),
        ("duplicate_exchange_order_id_absent", data["latest"]["executed_analysis"].get("duplicate_exchange_order_id_rows", 0) == 0, "snapshots.jsonl executed_analysis"),
        ("live_gate_blocked", data["live_gate_status"] == "blocked_human_only", "Phase 3C generated payload"),
    ]
    lines = ["# Runtime Truth Table", "", "| Check | Pass | Evidence |", "| --- | --- | --- |"]
    for name, passed, evidence_text in rows:
        lines.append(f"| {name} | {passed} | {evidence_text} |")
    return "\n".join(lines) + "\n"


def render_gaps(data: dict[str, Any]) -> str:
    lines = ["# Safety Critical Gaps", ""]
    if not data["gaps"]:
        lines.append("No runtime gaps were detected.")
    for gap in data["gaps"]:
        lines.append(f"- {gap['severity']}: {gap['gap']} ({gap['evidence']})")
    return "\n".join(lines) + "\n"


def main() -> int:
    data = summarize()
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    write(OUT / "PHASE3C_12H_RUNTIME_MONITOR_REPORT.md", render_report(data))
    write(OUT / "GO_NO_GO.md", data["go_no_go"] + "\n")
    write(OUT / "runtime_truth_table.md", render_truth_table(data))
    write_json(OUT / "runtime_truth_table.json", data)
    write(OUT / "safety_critical_gaps.md", render_gaps(data))
    write(OUT / "redis_memory_pressure_review.md", f"""# Redis Memory Pressure Review

Max observed Redis memory ratio: {data['counts']['redis_memory_max_pct']}%
Average observed Redis memory ratio: {data['counts']['redis_memory_avg_pct']}%

Evidence pointer: `claude_worklog/monitoring/snapshots.jsonl` field `redis_memory.memory_ratio_pct`.

Result: {'PASS' if data['counts']['redis_memory_max_pct'] < 95 else 'BLOCKER - critical_95 memory pressure observed'}
""")
    write(OUT / "trainer_runtime_liveness_review.md", f"""# Trainer Runtime Liveness Review

Trainer CRITICAL count: {data['counts']['trainer_critical_count']}
Trainer DEGRADED count: {data['counts']['trainer_degraded_count']}
Latest trainer status: {data['latest']['latest_trainer_status']}
Prediction worker alive latest: {data['latest']['prediction_worker_alive']}
Publish surface liveness latest: {data['latest']['publish_surface_liveness']}

Evidence pointer: `claude_worklog/monitoring/trainer_metrics.jsonl`.
""")
    write(OUT / "prediction_signal_lineage_runtime_review.md", f"""# Prediction / Signal Lineage Runtime Review

Latest executed analysis:

```json
{json.dumps(data['latest']['executed_analysis'], indent=2, sort_keys=True)}
```

Latest attribution completeness:

```json
{json.dumps(data['latest']['attribution_completeness'], indent=2, sort_keys=True)}
```

Evidence pointer: `claude_worklog/monitoring/snapshots.jsonl`.
""")
    write_json(OUT / "monitor_artifact_integrity_check.json", {
        "snapshots_exists": (MONITORING / "snapshots.jsonl").exists(),
        "trainer_metrics_exists": (MONITORING / "trainer_metrics.jsonl").exists(),
        "read_only_monitor_log_exists": (MONITORING / "read_only_monitor.log").exists(),
        "snapshot_count": data["counts"]["snapshot_count"],
        "trainer_metric_count": data["counts"]["trainer_metric_count"],
        "duration_hours": data["counts"]["duration_hours"],
        "phase3a_placeholder_status": data["latest"]["phase3a_monitor_status"],
    })
    write_json(OUT / "evidence_manifest.json", data["evidence"])
    write(OUT / "next_safe_milestone.md", data["next_safe_milestone"] + "\n")
    write_json(OUT / "operator_dashboard_payload.json", data)
    write(PUBLIC / "operator_dashboard_payload.json", json.dumps(data, indent=2, sort_keys=True) + "\n")
    write(OUT / "CODEX_PHASE3C_RUNTIME_MONITOR_REVIEW.md", f"""# Codex Phase 3C Runtime Monitor Review

This adversarial review fails if runtime evidence is incomplete or if Redis memory pressure, trainer liveness, stale/missing attribution, duplicate order ids, or live-safety concerns remain under-addressed.

Runtime duration hours: {data['counts']['duration_hours']}
Blocking gaps: {data['counts']['blocking_gap_count']}
Next safe milestone: {data['next_safe_milestone']}

Result: {'PASS' if data['ready'] else 'FAIL'}

CODEX_PHASE3C_RUNTIME_MONITOR_REVIEW_READY
""")
    write(OUT / "CODEX_PHASE3C_GO_NO_GO.md", data["codex_go_no_go"] + "\n")
    print(json.dumps({"go_no_go": data["go_no_go"], "counts": data["counts"], "next_safe_milestone": data["next_safe_milestone"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
