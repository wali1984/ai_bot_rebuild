from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot, LivenessSLAConfig


@pytest.fixture
def healthy_snapshot() -> LivenessSignalSnapshot:
    return LivenessSignalSnapshot(
        trainer_pid=1234,
        trainer_rss_bytes=512_000_000,
        trainer_heartbeat_ts_ms=9_900,
        prediction_worker_pid=2345,
        prediction_worker_alive=True,
        last_prediction_ts_ms=9_950,
        last_gpu_batch_ts_ms=9_930,
        last_deconflict_ts_ms=9_920,
        last_proposal_ts_ms=9_940,
        prediction_stream_id_growth=4,
        proposal_stream_id_growth=3,
        fatal_log_signature_observed=False,
        observation_ts_ms=10_000,
    )


@pytest.fixture
def liveness_sla() -> LivenessSLAConfig:
    return LivenessSLAConfig(
        prediction_age_max_ms=500,
        gpu_batch_age_max_ms=750,
        proposal_age_max_ms=600,
        prediction_stream_zero_growth_window_ms=1_000,
    )
