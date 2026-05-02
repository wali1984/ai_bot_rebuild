```
# Prediction Worker Liveness Fix Specification

## Failure class to detect

`TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`

The legacy hybrid trainer exhibits a class of failures where the parent
process remains alive but the prediction worker stops emitting predictions,
GPU batches, deconflict events, or proposals. The Phase 2E plan must
guarantee detection without depending on parent-process liveness alone.

Source: `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.

## Required signals (read-only ingestion)

V2 must ingest the following signals via the subprocess adapter and via
read-only Redis observation:

- Trainer process alive (PID present and RSS > 0).
- Trainer heartbeat freshness (last heartbeat ts).
- Prediction worker alive (legacy worker pid file or adapter status probe).
- Last prediction timestamp.
- Last `GPU_BATCH` timestamp.
- Last `DECONFLICT` timestamp.
- Last proposal timestamp.
- Prediction stream growth rate.
- Proposal stream growth rate.
- Fatal trainer log signature.

## Required alert

`TRAINER_INTERNAL_LIVENESS_CRITICAL`

Alert must fire when any one of:

- Last prediction ts age exceeds the configured SLA.
- Last `GPU_BATCH` ts age exceeds the configured SLA.
- Last proposal ts age exceeds the configured SLA.
- Prediction stream growth rate is zero across the configured window while
  parent process is alive.
- Fatal log signature observed.

## Out-of-band requirements

- The liveness monitor must not write to legacy Redis keys.
- The liveness monitor must not restart the legacy trainer.
- The liveness monitor must emit findings to V2 Redis namespace under the
  `V2_REDIS_PREFIX` configured by environment, in a future phase, not in
  this planning phase.
- The liveness monitor must use stream-id growth rather than `XLEN`-style
  counts on capped streams (matches the corrected timezone-aware approach
  recorded in `claude_worklog/continuous_monitoring_impl/`).

## Validation evidence required before V2 build

A read-only validation run must prove detection of worker-dead /
process-alive conditions and emission of the
`TRAINER_INTERNAL_LIVENESS_CRITICAL` alert with an evidence packet, per
`claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.

PHASE2_TRAINER_GPU_PARITY_PREDICTION_WORKER_LIVENESS_READY
```
