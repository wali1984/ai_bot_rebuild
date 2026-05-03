from __future__ import annotations

from dataclasses import replace

import pytest

from v2.backend.app.domain.trainer_liveness import LivenessDomainError, LivenessSignalSnapshot


def test_signal_snapshot_accepts_complete_worker_health(healthy_snapshot: LivenessSignalSnapshot) -> None:
    assert healthy_snapshot.trainer_pid == 1234
    assert healthy_snapshot.prediction_worker_alive is True
    assert healthy_snapshot.prediction_stream_id_growth == 4


def test_signal_snapshot_accepts_never_observed_optional_fields() -> None:
    snapshot = LivenessSignalSnapshot(
        trainer_pid=None,
        trainer_rss_bytes=None,
        trainer_heartbeat_ts_ms=None,
        prediction_worker_pid=None,
        prediction_worker_alive=False,
        last_prediction_ts_ms=None,
        last_gpu_batch_ts_ms=None,
        last_deconflict_ts_ms=None,
        last_proposal_ts_ms=None,
        prediction_stream_id_growth=1,
        proposal_stream_id_growth=1,
        fatal_log_signature_observed=False,
        observation_ts_ms=0,
    )

    assert snapshot.last_prediction_ts_ms is None
    assert snapshot.prediction_worker_alive is False


def test_signal_snapshot_rejects_worker_alive_without_pid(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="alive_requires_worker_pid"):
        replace(healthy_snapshot, prediction_worker_pid=None)


def test_signal_snapshot_rejects_negative_growth(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="prediction_stream_id_growth"):
        replace(healthy_snapshot, prediction_stream_id_growth=-1)


def test_signal_snapshot_rejects_negative_proposal_growth(
    healthy_snapshot: LivenessSignalSnapshot,
) -> None:
    with pytest.raises(LivenessDomainError, match="proposal_stream_id_growth"):
        replace(healthy_snapshot, proposal_stream_id_growth=-1)


def test_signal_snapshot_rejects_negative_observation_ts(
    healthy_snapshot: LivenessSignalSnapshot,
) -> None:
    with pytest.raises(LivenessDomainError, match="observation_ts_ms"):
        replace(healthy_snapshot, observation_ts_ms=-1)


def test_signal_snapshot_rejects_negative_rss(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="trainer_rss_bytes"):
        replace(healthy_snapshot, trainer_rss_bytes=-1)


def test_signal_snapshot_rejects_nonpositive_process_ids(
    healthy_snapshot: LivenessSignalSnapshot,
) -> None:
    with pytest.raises(LivenessDomainError, match="trainer_pid"):
        replace(healthy_snapshot, trainer_pid=0)
    with pytest.raises(LivenessDomainError, match="prediction_worker_pid"):
        replace(healthy_snapshot, prediction_worker_pid=0)


def test_signal_snapshot_rejects_rss_without_trainer_pid(
    healthy_snapshot: LivenessSignalSnapshot,
) -> None:
    with pytest.raises(LivenessDomainError, match="trainer_rss_bytes"):
        replace(healthy_snapshot, trainer_pid=None)


@pytest.mark.parametrize(
    "field",
    [
        "trainer_heartbeat_ts_ms",
        "last_prediction_ts_ms",
        "last_gpu_batch_ts_ms",
        "last_deconflict_ts_ms",
        "last_proposal_ts_ms",
    ],
)
def test_signal_snapshot_rejects_negative_optional_timestamps(
    healthy_snapshot: LivenessSignalSnapshot,
    field: str,
) -> None:
    with pytest.raises(LivenessDomainError, match=field):
        replace(healthy_snapshot, **{field: -1})


def test_signal_snapshot_rejects_non_bool_flags(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="prediction_worker_alive"):
        replace(healthy_snapshot, prediction_worker_alive="yes")
    with pytest.raises(LivenessDomainError, match="fatal_log_signature_observed"):
        replace(healthy_snapshot, fatal_log_signature_observed=1)
