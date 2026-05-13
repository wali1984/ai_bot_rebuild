from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli.legacy_v2_function_gap_detector import (
    CategorySpec,
    build_legacy_v2_function_gap,
)


def _write(path: Path, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_runnable_category_is_classified_without_counting_backlog(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "legacy_reference/feature_pipeline.py", "def build_features():\n    return {}\n")
    _write(tmp_path / "v2/backend/app/cli/v2_feature_snapshot_builder.py", "def main():\n    return 0\n")
    _write(tmp_path / "v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json", "{}")
    _write(
        tmp_path / "claude_worklog/final_readiness/script_migration_backlog/latest/script_migration_backlog.json",
        '{"items":[{"category":"feature_snapshot_builder"}]}',
    )
    monkeypatch.setattr("v2.backend.app.cli.legacy_v2_function_gap_detector.process_lines", lambda: [])
    specs = (
        CategorySpec(
            "feature_snapshot_builder",
            "feature",
            ("legacy_reference/feature_pipeline.py",),
            ("v2/backend/app/cli/v2_feature_snapshot_builder.py",),
            "python3 -m v2.backend.app.cli.v2_feature_snapshot_builder --once",
            "v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json",
            backlog_terms=("feature_snapshot_builder",),
        ),
    )

    result = build_legacy_v2_function_gap(tmp_path, specs=specs)
    category = result["categories"][0]

    assert category["status"] == "RUNNABLE"
    assert category["is_migration"] is True
    assert result["backlog_counted_as_migration"] is False


def test_backlog_only_is_not_migration(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "legacy_reference/risk/shared_risk_gate.py", "class SharedRiskGate:\n    pass\n")
    _write(
        tmp_path / "claude_worklog/agent_supervisor/tasks/claude_port_v2_risk_gateway_runtime_worker.json",
        '{"task_id":"claude_port_v2_risk_gateway_runtime_worker"}',
    )
    monkeypatch.setattr("v2.backend.app.cli.legacy_v2_function_gap_detector.process_lines", lambda: [])
    specs = (
        CategorySpec(
            "risk_gateway_runtime_worker",
            "risk",
            ("legacy_reference/risk/*.py",),
            ("v2/backend/app/composition/risk_gateway/runtime.py",),
            backlog_terms=("risk_gateway_runtime_worker",),
        ),
    )

    result = build_legacy_v2_function_gap(tmp_path, specs=specs)
    category = result["categories"][0]

    assert category["status"] == "BACKLOG_ONLY"
    assert category["is_migration"] is False


def test_missing_legacy_category_is_reported(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "legacy_reference/trading/dynamic_margin_manager.py", "def adjust_margin():\n    return None\n")
    monkeypatch.setattr("v2.backend.app.cli.legacy_v2_function_gap_detector.process_lines", lambda: [])
    specs = (
        CategorySpec(
            "dynamic_margin_manager",
            "margin",
            ("legacy_reference/trading/dynamic_margin_manager.py",),
            (),
            backlog_terms=("dynamic_margin_manager",),
        ),
    )

    result = build_legacy_v2_function_gap(tmp_path, specs=specs)

    assert result["categories"][0]["status"] == "MISSING"
    assert "dynamic_margin_manager" in result["missing_categories"]
