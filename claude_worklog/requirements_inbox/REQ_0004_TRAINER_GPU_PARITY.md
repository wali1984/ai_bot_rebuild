# Requirement 0004 - Trainer GPU Parity

The V2 trainer must be rebuilt from current legacy trainer behavior and GPU assumptions, not as a basic trainer.

Rules:
- Preserve GPU utilization assumptions.
- Preserve batching behavior.
- Preserve checkpoint behavior.
- Preserve model-loading behavior.
- Preserve hybrid trainer architecture lessons.
- Preserve confidence/reward behavior where useful.
- Fix prediction-worker liveness.
- Fix process-alive/worker-dead blind spot.
- Add feature_snapshot_id, prediction_id, confidence attribution, freshness flags, and worker health telemetry.
- Trainer changes require Codex review and non-live validation.

REQ_TRAINER_GPU_PARITY_READY
