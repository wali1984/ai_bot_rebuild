"""Tests for the V2 AI throughput acceleration packet executor."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.throughput.ai_throughput_acceleration import (
    LIVE_GATE_BLOCKED,
    build_ai_execution_mode_inventory,
    build_cloud_acceleration_options,
    build_gpu_usage_plan,
    build_high_throughput_scheduler_design,
    build_local_speedup_plan,
    build_operator_dashboard_payload,
    build_parallel_lane_matrix,
    build_throughput_sla,
    default_paths,
    run_throughput_packet,
)


# ---------------------------------------------------------------------------
# Stub hardware inventory so tests are hermetic.
# ---------------------------------------------------------------------------


def _stub_inventory(repo_root: Path) -> dict:
    return {
        "schema_version": "test_inventory",
        "generated_utc": "2026-05-23T18:00:00Z",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "cpu": {
            "model_name": "Test CPU",
            "physical_cores_observed": 16,
            "logical_cpus": 32,
            "loadavg_1_5_15": [0.5, 0.4, 0.3],
        },
        "memory": {
            "mem_total_kb": 128 * 1024 * 1024,
            "mem_available_kb": 64 * 1024 * 1024,
            "swap_total_kb": 8 * 1024 * 1024,
        },
        "disk_repo_root": {
            "path": str(repo_root),
            "total_bytes": 1_000_000_000,
            "free_bytes": 500_000_000,
        },
        "gpu": {
            "devices": [
                {
                    "name": "TEST GPU",
                    "memory_total_mib": 16000,
                    "memory_used_mib": 1000,
                    "driver_version": "999.99",
                }
            ],
            "device_count": 1,
            "nvidia_smi_available": True,
            "cuda_libs_observed": [],
            "cuda_libs_count": 0,
            "torch_import_attempted": False,
            "torch_import_attempted_reason": "test",
        },
        "redis": {
            "available": True,
            "used_memory_human": "7.78G",
            "maxmemory_human": "8.00G",
        },
        "processes": {"v2_runtime_processes": [], "ai_assistant_processes": []},
        "env_paths": {},
        "raw_secrets_exposed": False,
    }


# ---------------------------------------------------------------------------
# Phase-specific builders
# ---------------------------------------------------------------------------


def test_execution_mode_inventory_lists_eight_lanes_and_blocks_production():
    inv = build_ai_execution_mode_inventory()
    assert inv["approves_live"] is False
    assert inv["live_gate"] == LIVE_GATE_BLOCKED
    assert len(inv["lanes"]) == 8
    lane_ids = {l["lane_id"] for l in inv["lanes"]}
    assert "claude_code_terminal_local" in lane_ids
    assert "codex_cloud_web_app" in lane_ids
    assert "gpu_local_native_training_or_eval" in lane_ids


def test_throughput_sla_carries_minimum_three_active_lanes_target():
    sla = build_throughput_sla()
    targets = sla["targets"]
    assert targets["claude_implementation_lanes_min_active_when_work_exists"] == 3
    assert targets["codex_review_lanes_min_active_when_work_exists"] == 3
    assert targets["max_pending_minutes_for_automatable_task"] == 10
    assert sla["approves_live"] is False


def test_parallel_lane_matrix_has_eight_lanes_with_owners():
    matrix = build_parallel_lane_matrix()
    assert len(matrix["lanes"]) == 8
    owners = {l["owner"] for l in matrix["lanes"]}
    assert "claude" in owners and "codex" in owners
    for lane in matrix["lanes"]:
        assert lane["file_locks"], lane["lane_id"]
        assert lane["test_command"], lane["lane_id"]
        assert lane["codex_review_command"], lane["lane_id"]


def test_local_speedup_plan_marks_active_replay_miner_append():
    plan = build_local_speedup_plan()
    by_id = {it["id"]: it for it in plan["items"]}
    assert by_id["replay_miner_incremental_timeline_append"]["status"] == "ACTIVE"
    assert by_id["avoid_stopping_v2_during_builds"]["status"] == "ACTIVE"


def test_gpu_usage_plan_defaults_off_and_requires_operator_decision():
    inv = _stub_inventory(Path("/tmp"))
    plan = build_gpu_usage_plan(inv)
    assert plan["gpu_available"] is True
    assert plan["scheduling"]["default_runlevel"] == "OFF"
    assert plan["scheduling"]["activation_requires"] == "operator_explicit_decision"
    assert plan["principles"]["trainer_venv_torch_install_protected"] is True


def test_cloud_acceleration_options_lists_all_documented_paths():
    opts = build_cloud_acceleration_options()
    ids = {o["id"] for o in opts["options"]}
    assert "codex_fast_mode_for_supported_models" in ids
    assert "codex_non_interactive_exec" in ids
    assert "codex_cloud_web_app_tasks" in ids
    assert "claude_code_background_agents_and_routines" in ids
    assert "claude_code_local_terminal_multi_pane" in ids
    assert "cloud_runner_for_isolated_ci_gpu" in ids


def test_scheduler_design_is_design_only_and_lists_all_responsibilities():
    sched = build_high_throughput_scheduler_design()
    assert sched["scheduler_name"] == "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER"
    assert "DESIGN_ONLY" in sched["implementation_status"]
    expected = {
        "keep_3_plus_claude_lanes_active_when_automatable_work_exists",
        "keep_3_plus_codex_lanes_active_when_review_work_exists",
        "enforce_file_locks",
        "monitor_stale_tasks",
        "redispatch_stale_tasks",
        "codex_takeover_safe_scoped_work",
        "stop_on_safety_drift",
        "show_utilization_dashboard",
    }
    assert expected.issubset(set(sched["responsibilities"]))


def test_operator_dashboard_payload_marks_idle_when_lanes_zero_with_work():
    inv = _stub_inventory(Path("/tmp"))
    sla = build_throughput_sla()
    gpu_plan = build_gpu_usage_plan(inv)
    cloud = build_cloud_acceleration_options()
    payload = build_operator_dashboard_payload(
        inventory=inv,
        sla=sla,
        gpu_plan=gpu_plan,
        cloud_options=cloud,
        war_room_utilization={"active_lanes": 0, "completed_lanes": 7, "stalled_lanes": 0},
        war_room_next_tasks={"tasks": [{"task_id": "demo"}]},
        war_room_operator_queue={"items": [{"title": "Approve thresholds"}]},
    )
    assert payload["safety_scoreboard"]["approves_live"] is False
    assert payload["controls_present"] is False
    assert payload["fake_readiness"] is False
    assert any(
        "WAR_ROOM_ACTIVE_LANES_BELOW_MINIMUM" in r
        for r in payload["idle_reasons"]
    )


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def _write_synthetic_war_room(tmp_root: Path) -> None:
    base = tmp_root / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest"
    (base / "lane6").mkdir(parents=True, exist_ok=True)
    (base / "lane6" / "war_room_utilization_status.json").write_text(
        json.dumps({"active_lanes": 0, "completed_lanes": 7, "stalled_lanes": 0}),
        encoding="utf-8",
    )
    (base / "next_automatable_tasks.json").write_text(
        json.dumps({"tasks": [{"task_id": "demo_task"}]}),
        encoding="utf-8",
    )
    (base / "operator_decision_queue.json").write_text(
        json.dumps({"items": [{"decision_id": "demo", "title": "Approve demo decision"}]}),
        encoding="utf-8",
    )


def test_run_throughput_packet_emits_all_required_artifacts(tmp_path: Path):
    _write_synthetic_war_room(tmp_path)
    paths = default_paths(tmp_path)
    result = run_throughput_packet(paths, inventory_collector=_stub_inventory)

    assert result.go_no_go == "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY"
    go_file = paths.packet_dir / "GO_NO_GO.md"
    assert go_file.read_text().strip() == result.go_no_go

    for required in [
        "V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_REPORT.md",
        "local_resource_inventory.json",
        "ai_execution_mode_inventory.json",
        "throughput_sla.json",
        "parallel_lane_matrix.json",
        "local_speedup_plan.json",
        "gpu_usage_plan.json",
        "cloud_acceleration_options.json",
        "high_throughput_scheduler_design.json",
    ]:
        assert (paths.packet_dir / required).exists(), required

    assert (paths.public_dir / "operator_dashboard_payload.json").exists()
    dashboard = json.loads(
        (paths.public_dir / "operator_dashboard_payload.json").read_text()
    )
    assert dashboard["safety_scoreboard"]["live_gate"] == LIVE_GATE_BLOCKED
    assert dashboard["safety_scoreboard"]["approves_live"] is False
    assert dashboard["controls_present"] is False
    assert dashboard["fake_readiness"] is False


def test_run_throughput_packet_artifacts_carry_no_truthy_approval_tokens(tmp_path: Path):
    _write_synthetic_war_room(tmp_path)
    paths = default_paths(tmp_path)
    run_throughput_packet(paths, inventory_collector=_stub_inventory)

    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
    ]
    for f in paths.packet_dir.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
    for f in paths.public_dir.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
