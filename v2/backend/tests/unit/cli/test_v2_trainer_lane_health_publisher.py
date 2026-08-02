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
