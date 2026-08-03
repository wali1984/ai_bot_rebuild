from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_trainer_corpus_sprint_arm as cli
from v2.backend.app.services.trainer_corpus_sprint.sprint_arm_v1 import SPRINT_ARM_KEY


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


@pytest.fixture
def patched(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(cli, "_redis", lambda: r)
    monkeypatch.setattr(cli, "_disk_bytes", lambda: (1_000_000, 500 * 1024**3))
    return r


def test_arm_writes_active_status_and_valid_arm(patched):
    rc = cli.main(["arm", "--cycle-seconds", "180"])
    assert rc == 0
    status = json.loads(patched.d[cli.SPRINT_STATUS_KEY])
    assert status["state"] == "STRICT_TRAIN_ROW_SPRINT_ACTIVE"
    # Honest: never falsely claims the publisher is accelerating.
    assert status["publisher_acceleration_active"] is False
    assert status["execution_blockers"]  # non-empty, documents the gating
    # Safety anchors + strict gate unchanged.
    assert status["safety"]["live_gate"] == "blocked_human_only"
    assert status["safety"]["live_eligible"] is False
    assert status["safety"]["strict_champion_min_train_rows_unchanged"] == 1000
    arm = json.loads(patched.d[SPRINT_ARM_KEY])
    assert arm["operator_authorized"] is True
    assert arm["maximum_selected_symbols"] == 74
    assert arm["cycle_seconds"] == 180


def test_disarm_clears_arm_and_status(patched):
    cli.main(["arm"])
    rc = cli.main(["disarm"])
    assert rc == 0
    assert SPRINT_ARM_KEY not in patched.d
    status = json.loads(patched.d[cli.SPRINT_STATUS_KEY])
    assert status["state"] == "STRICT_TRAIN_ROW_SPRINT_DISARMED"
    assert status["execution_blockers"] == []


def test_status_reports_valid_arm(patched):
    cli.main(["arm"])
    rc = cli.main(["status"])
    assert rc == 0
    # The published status round-trips as active + valid.
    status = json.loads(patched.d[cli.SPRINT_STATUS_KEY])
    assert status["state"] == "STRICT_TRAIN_ROW_SPRINT_ACTIVE"
    assert SPRINT_ARM_KEY in patched.d
