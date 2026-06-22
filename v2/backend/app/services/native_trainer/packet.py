"""Packet emitter for the V2 native trainer dataset + baseline model lane.

Consolidates dataset + baseline-model outputs and writes the
operator dashboard payload, GO_NO_GO marker, and the combined
report. The packet's GO_NO_GO is always READY because the lane is
analysis-only and never approves live, canary, shutdown, or Redis
trim. The status payload always carries the safety scoreboard so
the report center cannot promote it past paper/shadow.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .baseline_model import (
    EvaluationResult,
    render_baseline_metrics,
    render_baseline_report_markdown,
    render_baseline_status,
)
from .dataset_builder import (
    DatasetBuildResult,
    DatasetQualityReport,
    LIVE_GATE_BLOCKED,
    _safety_block,
)


SCHEMA_VERSION = "v2_native_trainer_dataset_and_baseline_model_v1"
GO_NO_GO_READY = "V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_READY"
GO_NO_GO_BLOCKED = "V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_BLOCKED"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PacketPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_packet_paths(repo_root: Path) -> PacketPaths:
    return PacketPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_native_trainer_dataset_and_baseline_model/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_native_trainer_dataset_and_baseline_model/latest",
    )


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


@dataclass
class PacketRunResult:
    go_no_go: str
    paths_written: list[Path] = field(default_factory=list)


def build_operator_dashboard_payload(
    *,
    build_result: DatasetBuildResult,
    quality: DatasetQualityReport,
    eval_result: EvaluationResult,
    publisher_result: dict[str, Any] | None,
    go_no_go: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_at": _utc_now_iso(),
        "go_no_go": go_no_go,
        "safety_scoreboard": _safety_block(),
        "dataset_summary": {
            "row_count": len(build_result.rows),
            "train_rows": quality.train_rows,
            "validation_rows": quality.validation_rows,
            "label_missing_rows": quality.label_missing_rows,
            "stale_feature_rows": quality.stale_feature_rows,
            "missing_feature_rows": quality.missing_feature_rows,
            "insufficient_evidence_rows": quality.insufficient_evidence_rows,
            "minimum_sample_satisfied": quality.minimum_sample_satisfied,
            "minimum_train_rows_threshold": quality.minimum_train_rows_threshold,
        },
        "baseline_summary": {
            "train_count": eval_result.train_count,
            "validation_count": eval_result.validation_count,
            "minimum_sample_satisfied": eval_result.minimum_sample_satisfied,
            "publishable_baseline_available": (
                eval_result.publishable_baseline_available
            ),
            "metric_names": [m.name for m in eval_result.metrics],
        },
        "publisher_summary": publisher_result or {
            "published_count": 0,
            "preserved_count": 0,
            "rejected_count": 0,
            "old_redis_write_attempts": 0,
            "writes_succeeded": 0,
            "writes_failed": 0,
        },
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "model_parity_claimed": False,
        "checkpoint_compatibility_claimed": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }


def emit_packet(
    *,
    paths: PacketPaths,
    build_result: DatasetBuildResult,
    quality: DatasetQualityReport,
    eval_result: EvaluationResult,
    publisher_result: dict[str, Any] | None,
) -> PacketRunResult:
    go_no_go = GO_NO_GO_READY  # analysis-only lane is always READY
    paths_written: list[Path] = []

    dashboard = build_operator_dashboard_payload(
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=publisher_result,
        go_no_go=go_no_go,
    )
    baseline_status = render_baseline_status(
        eval_result=eval_result,
        publisher_result=publisher_result,
    )
    baseline_metrics = render_baseline_metrics(eval_result)
    report = render_baseline_report_markdown(
        eval_result=eval_result,
        publisher_result=publisher_result,
    )

    dashboard_path = paths.packet_dir / "operator_dashboard_payload.json"
    _atomic_write_json(dashboard_path, dashboard)
    paths_written.append(dashboard_path)

    baseline_status_path = (
        paths.packet_dir / "v2_native_baseline_model_status.json"
    )
    _atomic_write_json(baseline_status_path, baseline_status)
    paths_written.append(baseline_status_path)

    baseline_metrics_path = (
        paths.packet_dir / "v2_native_baseline_model_metrics.json"
    )
    _atomic_write_json(baseline_metrics_path, baseline_metrics)
    paths_written.append(baseline_metrics_path)

    report_path = (
        paths.packet_dir
        / "V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_REPORT.md"
    )
    _atomic_write_text(report_path, report)
    paths_written.append(report_path)

    go_no_go_path = paths.packet_dir / "GO_NO_GO.md"
    _atomic_write_text(go_no_go_path, go_no_go + "\n")
    paths_written.append(go_no_go_path)

    # Public mirrors.
    public_dashboard_path = (
        paths.public_dir / "operator_dashboard_payload.json"
    )
    _atomic_write_json(public_dashboard_path, dashboard)
    paths_written.append(public_dashboard_path)

    public_metrics_path = (
        paths.public_dir / "v2_native_baseline_model_metrics.json"
    )
    _atomic_write_json(public_metrics_path, baseline_metrics)
    paths_written.append(public_metrics_path)

    public_status_path = (
        paths.public_dir / "v2_native_baseline_model_status.json"
    )
    _atomic_write_json(public_status_path, baseline_status)
    paths_written.append(public_status_path)

    return PacketRunResult(go_no_go=go_no_go, paths_written=paths_written)
