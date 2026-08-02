"""Lane-health verdicts must be driven by evidence, never optimism.

A trainer that is resident but producing nothing, or active but publishing no
evidence key, must not be reported as healthy -- that is exactly the failure the
GUI was hiding.
"""

from __future__ import annotations

from v2.backend.app.cli.v2_trainer_lane_health_publisher import (
    HEALTH_FAILED,
    HEALTH_HELD,
    HEALTH_NOT_PUBLISHING,
    HEALTH_OK,
    HEALTH_STALLED,
    HEALTH_STOPPED,
    LaneSpec,
    _idle_gpu_alert,
    _research_lane_runtime,
    build_lane_health,
    evaluate_lane,
)

ACTIVE = {"ActiveState": "active", "SubState": "running", "Result": "success", "LoadState": "loaded"}


def _lane(**kwargs) -> dict:
    spec = kwargs.pop("spec", LaneSpec(lane_id="x", label="X", unit="x.service"))
    return evaluate_lane(
        spec,
        unit_properties=kwargs.pop("unit_properties", dict(ACTIVE)),
        process=kwargs.pop("process", {}),
        artifact=kwargs.pop("artifact", {}),
        redis_key_present=kwargs.pop("redis_key_present", None),
    )


def test_active_unit_without_staleness_policy_is_ok() -> None:
    assert _lane()["health"] == HEALTH_OK


def test_failed_unit_reports_failed_with_result_in_reason() -> None:
    lane = _lane(unit_properties={"ActiveState": "failed", "Result": "exit-code", "ExecMainStatus": "1", "LoadState": "loaded"})
    assert lane["health"] == HEALTH_FAILED
    assert "exit-code" in lane["reason"]


def test_inactive_unit_reports_stopped() -> None:
    lane = _lane(unit_properties={"ActiveState": "inactive", "SubState": "dead", "LoadState": "loaded"})
    assert lane["health"] == HEALTH_STOPPED


def test_inactive_timer_driven_lane_is_held_not_stopped() -> None:
    spec = LaneSpec(lane_id="t", label="T", unit="t.service", timer_driven=True)
    lane = _lane(spec=spec, unit_properties={"ActiveState": "inactive", "SubState": "dead", "LoadState": "loaded"})
    assert lane["health"] == HEALTH_HELD


def test_missing_unit_reports_stopped() -> None:
    lane = _lane(unit_properties={"ActiveState": "inactive", "LoadState": "not-found"})
    assert lane["health"] == HEALTH_STOPPED


def test_active_unit_with_stale_artifact_is_stalled_not_ok() -> None:
    """The regression this publisher exists to catch."""
    spec = LaneSpec(lane_id="offline", label="Offline", unit="o.service", max_artifact_age_seconds=2700)
    lane = _lane(
        spec=spec,
        artifact={"last_artifact_age_seconds": 35_000, "last_artifact_path": "report.json"},
        process={"process_running": True, "process_elapsed_seconds": 34_800},
    )
    assert lane["health"] == HEALTH_STALLED
    assert lane["severity"] == "error"
    assert "threshold" in lane["reason"]
    # The resident-but-unproductive process must be named in the reason.
    assert "resident" in lane["reason"]


def test_active_unit_within_threshold_stays_ok() -> None:
    spec = LaneSpec(lane_id="offline", label="Offline", unit="o.service", max_artifact_age_seconds=2700)
    lane = _lane(spec=spec, artifact={"last_artifact_age_seconds": 60, "last_artifact_path": "report.json"})
    assert lane["health"] == HEALTH_OK


def test_lane_that_never_produced_an_artifact_is_stalled() -> None:
    spec = LaneSpec(lane_id="offline", label="Offline", unit="o.service", max_artifact_age_seconds=2700)
    lane = _lane(spec=spec, artifact={"last_artifact_age_seconds": None})
    assert lane["health"] == HEALTH_STALLED


def test_active_unit_missing_its_redis_evidence_key_is_not_publishing() -> None:
    spec = LaneSpec(lane_id="hybrid", label="Hybrid", unit="h.service", redis_key="v2:trainer:hybrid_cuda:status")
    lane = _lane(spec=spec, redis_key_present=False)
    assert lane["health"] == HEALTH_NOT_PUBLISHING
    assert "renders empty" in lane["reason"]


def test_present_redis_evidence_key_stays_ok() -> None:
    spec = LaneSpec(lane_id="hybrid", label="Hybrid", unit="h.service", redis_key="v2:trainer:hybrid_cuda:status")
    assert _lane(spec=spec, redis_key_present=True)["health"] == HEALTH_OK


def test_build_lane_health_surfaces_alerts_and_worst_severity(tmp_path) -> None:
    specs = (
        LaneSpec(lane_id="ok_lane", label="OK", unit=None),
        LaneSpec(lane_id="bad_lane", label="Bad", unit=None, max_artifact_age_seconds=1),
    )
    payload = build_lane_health(repo_root=tmp_path, redis_client=None, specs=specs)
    assert payload["total_lane_count"] == 2
    # A lane with no systemd evidence is UNKNOWN (warn), a never-produced
    # artifact lane is STALLED (error) -> worst severity must be error.
    assert payload["worst_severity"] == "error"
    assert payload["alert_count"] >= 1
    assert any(a["lane_id"] == "bad_lane" for a in payload["alerts"])
    # Alerts are ordered worst-first so the banner leads with the real failure.
    assert payload["alerts"][0]["severity"] == "error"
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False


# --------------------------------------------------------------------------- #
# A resident trainer can report "cycle in progress" forever while never doing
# any GPU work. Unit state alone reads healthy, so the lane's own claim must be
# checked against its own CUDA counters.
# --------------------------------------------------------------------------- #
def _running_cycle(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status_present": True,
        "cycle_in_progress": True,
        "gpu_name": "NVIDIA GeForce RTX 5080",
        "memory_allocated_bytes": 0,
        "peak_memory_allocated_bytes": 0,
    }
    base.update(overrides)
    return base


def test_cycle_claimed_with_zero_gpu_allocation_raises_error_alert() -> None:
    alert = _idle_gpu_alert(_running_cycle())
    assert alert is not None
    assert alert["severity"] == "error"
    assert alert["code"] == "TRAINER_LANE_CYCLE_CLAIMED_BUT_GPU_NEVER_ALLOCATED"
    assert "never allocated device memory" in alert["message"]
    assert "RTX 5080" in alert["message"]


def test_cycle_that_actually_used_the_gpu_is_not_alerted() -> None:
    assert _idle_gpu_alert(_running_cycle(peak_memory_allocated_bytes=1_048_576)) is None
    assert _idle_gpu_alert(_running_cycle(memory_allocated_bytes=4096)) is None


def test_idle_gpu_alert_requires_a_claimed_running_cycle() -> None:
    # Not claiming a cycle => zero allocation is expected, not a fault.
    assert _idle_gpu_alert(_running_cycle(cycle_in_progress=False)) is None
    assert _idle_gpu_alert(_running_cycle(status_present=False)) is None


def test_idle_gpu_alert_stays_silent_without_counter_evidence() -> None:
    # Absent/unusable counters must not be treated as "zero" -- no evidence is
    # not evidence of failure.
    assert _idle_gpu_alert(_running_cycle(peak_memory_allocated_bytes=None)) is None
    assert _idle_gpu_alert(_running_cycle(memory_allocated_bytes="n/a")) is None


def test_research_lane_runtime_reports_absent_status_honestly(tmp_path, monkeypatch) -> None:
    import v2.backend.app.cli.v2_trainer_lane_health_publisher as mod

    monkeypatch.setattr(mod, "RESEARCH_LANE_STATUS_PATH", tmp_path / "missing.json")
    out = _research_lane_runtime()
    assert out["status_present"] is False
    # Never invents fields the lane did not publish.
    assert "cycle_in_progress" not in out


def test_research_lane_runtime_bridges_real_fields(tmp_path, monkeypatch) -> None:
    import json

    import v2.backend.app.cli.v2_trainer_lane_health_publisher as mod

    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "classification": "LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING",
                "cycle_in_progress": True,
                "runtime_wired": False,
                "local_research_non_promotable": True,
                "prediction_authorized": False,
                "cuda_runtime": {"gpu_name": "RTX 5080", "peak_memory_allocated_bytes": 0},
            }
        )
    )
    monkeypatch.setattr(mod, "RESEARCH_LANE_STATUS_PATH", path)
    out = _research_lane_runtime()
    assert out["status_present"] is True
    assert out["classification"] == "LOCAL_PROFILED_RESEARCH_CYCLE_RUNNING"
    assert out["runtime_wired"] is False
    assert out["non_promotable"] is True
    assert out["gpu_name"] == "RTX 5080"
    assert out["peak_memory_allocated_bytes"] == 0
