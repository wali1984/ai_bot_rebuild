from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.trainer_corpus_sprint.sprint_arm_v1 import (
    MAX_DISK_GROWTH_BYTES,
    MAX_DURATION_SECONDS,
    SPRINT_ARM_KEY,
    create_sprint_arm,
    disarm_sprint,
    estimate_commits_needed,
    paper_recovery_train_gate,
    sprint_cycle_seconds,
    sprint_disable_decision,
    validate_sprint_arm,
)

NOW = datetime(2026, 7, 25, 6, 0, tzinfo=UTC)
MIN_FREE = 40 * 1024**3


class FakeRedis:
    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def set(self, k, v, ex=None, nx=False):  # noqa: ANN001
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True

    def get(self, k):  # noqa: ANN001
        return self.d.get(k)

    def delete(self, k):  # noqa: ANN001
        self.d.pop(k, None)
        return True


def _arm(r, **kw):
    return create_sprint_arm(
        r, arm_id="sprint1", now=NOW, minimum_free_disk_bytes=MIN_FREE, **kw
    )


def test_arm_created_with_ttl_and_bounds():
    r = FakeRedis()
    arm = _arm(r)
    assert arm.maximum_duration_seconds == MAX_DURATION_SECONDS
    assert arm.maximum_disk_growth_bytes == MAX_DISK_GROWTH_BYTES
    assert arm.paper_only is True and arm.live_eligible is False
    stored = json.loads(r.d[SPRINT_ARM_KEY])
    assert stored["operator_authorized"] is True


def test_arm_requires_operator_authorization():
    r = FakeRedis()
    with pytest.raises(ValueError, match="OPERATOR_AUTHORIZATION"):
        create_sprint_arm(
            r, arm_id="x", now=NOW, minimum_free_disk_bytes=MIN_FREE, operator_authorized=False
        )


def test_arm_duration_and_disk_capped_to_hard_limits():
    r = FakeRedis()
    arm = _arm(r, maximum_duration_seconds=999_999, maximum_disk_growth_bytes=10**15)
    assert arm.maximum_duration_seconds == MAX_DURATION_SECONDS
    assert arm.maximum_disk_growth_bytes == MAX_DISK_GROWTH_BYTES


def test_validate_accepts_live_arm_within_guards():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_sprint_arm(
        redis_client=r,
        now=NOW + timedelta(hours=1),
        current_free_disk_bytes=MIN_FREE + 1,
        current_disk_growth_bytes=1024,
        publisher_restart_count=0,
    )
    assert reject is None and arm is not None


def test_validate_absent_arm():
    r = FakeRedis()
    arm, reject = validate_sprint_arm(redis_client=r, now=NOW)
    assert arm is None and reject == "SPRINT_ARM_ABSENT_OR_EXPIRED"


def test_validate_expired_arm():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_sprint_arm(
        redis_client=r, now=NOW + timedelta(seconds=MAX_DURATION_SECONDS + 1)
    )
    assert arm is None and reject == "SPRINT_ARM_EXPIRED"


def test_validate_publisher_restart_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_sprint_arm(
        redis_client=r, now=NOW + timedelta(minutes=5), publisher_restart_count=1
    )
    assert arm is None and reject == "SPRINT_ARM_PUBLISHER_RESTARTED"


def test_validate_disk_growth_cap_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_sprint_arm(
        redis_client=r,
        now=NOW + timedelta(minutes=5),
        current_disk_growth_bytes=MAX_DISK_GROWTH_BYTES + 1,
    )
    assert arm is None and reject == "SPRINT_ARM_DISK_GROWTH_CAP_EXCEEDED"


def test_validate_free_disk_reserve_rejected():
    r = FakeRedis()
    _arm(r)
    arm, reject = validate_sprint_arm(
        redis_client=r,
        now=NOW + timedelta(minutes=5),
        current_free_disk_bytes=MIN_FREE - 1,
    )
    assert arm is None and reject == "SPRINT_ARM_FREE_DISK_BELOW_RESERVE"


def test_validate_live_marker_rejected():
    r = FakeRedis()
    _arm(r)
    data = json.loads(r.d[SPRINT_ARM_KEY])
    data["live_eligible"] = True
    r.d[SPRINT_ARM_KEY] = json.dumps(data)
    arm, reject = validate_sprint_arm(redis_client=r, now=NOW + timedelta(minutes=1))
    assert arm is None and reject == "SPRINT_ARM_LIVE_MARKER_PRESENT"


def test_cycle_backoff():
    assert sprint_cycle_seconds() == 180
    assert sprint_cycle_seconds(last_cycle_elapsed_seconds=90) == 180
    assert sprint_cycle_seconds(last_cycle_elapsed_seconds=121) == 300


def test_disable_decision_rules():
    disable, pause, reasons = sprint_disable_decision(publisher_restart_count=1)
    assert disable is True and "PUBLISHER_RESTARTED" in reasons
    disable, _, reasons = sprint_disable_decision(
        disk_growth_bytes=MAX_DISK_GROWTH_BYTES + 1
    )
    assert disable is True and "DISK_GROWTH_CAP_EXCEEDED" in reasons
    disable, _, reasons = sprint_disable_decision(
        free_disk_bytes=1, minimum_free_disk_bytes=MIN_FREE
    )
    assert disable is True and "FREE_DISK_BELOW_RESERVE" in reasons
    _, pause, reasons = sprint_disable_decision(low_success_consecutive_cycles=3)
    assert pause is True and "PUBLICATION_SUCCESS_RATIO_LOW_THREE_CYCLES" in reasons
    disable, pause, reasons = sprint_disable_decision()
    assert disable is False and pause is False and reasons == []


def test_estimate_commits_needed():
    assert (
        estimate_commits_needed(strict_train_rows_remaining=728, admission_yield_ratio=0.5)
        == 1456
    )
    assert estimate_commits_needed(strict_train_rows_remaining=0, admission_yield_ratio=0.5) == 0
    assert (
        estimate_commits_needed(strict_train_rows_remaining=100, admission_yield_ratio=0.0)
        is None
    )


def test_paper_recovery_gate_pass_and_pending():
    g = paper_recovery_train_gate(train_rows=272, min_train_rows=256)
    assert g["paper_recovery_train_gate_satisfied"] is True
    assert g["display"] == "paper recovery: 272/256 PASS"
    g2 = paper_recovery_train_gate(train_rows=100, min_train_rows=256)
    assert g2["paper_recovery_train_gate_satisfied"] is False
    assert "PENDING" in g2["display"]
    g3 = paper_recovery_train_gate(train_rows=None, min_train_rows=256)
    assert g3["paper_recovery_train_gate_satisfied"] is False


def test_disarm():
    r = FakeRedis()
    _arm(r)
    assert disarm_sprint(r) is True
    arm, reject = validate_sprint_arm(redis_client=r, now=NOW + timedelta(minutes=1))
    assert arm is None and reject == "SPRINT_ARM_ABSENT_OR_EXPIRED"
