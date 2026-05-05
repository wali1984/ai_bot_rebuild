def test_evaluate_does_not_mutate_supplied_snapshot() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot_id = id(snapshot)
    before = (
        snapshot.trainer_pid,
        snapshot.trainer_rss_bytes,
        snapshot.trainer_heartbeat_ts_ms,
        snapshot.prediction_worker_pid,
        snapshot.prediction_worker_alive,
        snapshot.last_prediction_ts_ms,
        snapshot.last_gpu_batch_ts_ms,
        snapshot.last_deconflict_ts_ms,
        snapshot.last_proposal_ts_ms,
        snapshot.prediction_stream_id_growth,
        snapshot.proposal_stream_id_growth,
        snapshot.fatal_log_signature_observed,
        snapshot.observation_ts_ms,
    )

    evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    after = (
        snapshot.trainer_pid,
        snapshot.trainer_rss_bytes,
        snapshot.trainer_heartbeat_ts_ms,
        snapshot.prediction_worker_pid,
        snapshot.prediction_worker_alive,
        snapshot.last_prediction_ts_ms,
        snapshot.last_gpu_batch_ts_ms,
        snapshot.last_deconflict_ts_ms,
        snapshot.last_proposal_ts_ms,
        snapshot.prediction_stream_id_growth,
        snapshot.proposal_stream_id_growth,
        snapshot.fatal_log_signature_observed,
        snapshot.observation_ts_ms,
    )
    assert id(snapshot) == snapshot_id
    assert after == before
