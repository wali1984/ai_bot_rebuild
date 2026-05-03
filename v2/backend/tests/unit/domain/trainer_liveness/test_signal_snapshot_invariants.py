from __future__ import annotations

from dataclasses import replace

import pytest

from v2.backend.app.domain.trainer_liveness import LivenessDomainError, LivenessSignalSnapshot


def test_signal_snapshot_accepts_complete_worker_health(healthy_snapshot: LivenessSignalSnapshot) -> None:
    assert healthy_snapshot.trainer_pid == 1234
    assert healthy_snapshot.prediction_worker_alive is True
    assert healthy_snapshot.prediction_stream_id_growth == 4


def test_signal_snapshot_rejects_worker_alive_without_pid(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="alive_requires_worker_pid"):
        replace(healthy_snapshot, prediction_worker_pid=None)


def test_signal_snapshot_rejects_negative_growth(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="prediction_stream_id_growth"):
        replace(healthy_snapshot, prediction_stream_id_growth=-1)


def test_signal_snapshot_rejects_non_bool_flags(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="prediction_worker_alive"):
        replace(healthy_snapshot, prediction_worker_alive="yes")
