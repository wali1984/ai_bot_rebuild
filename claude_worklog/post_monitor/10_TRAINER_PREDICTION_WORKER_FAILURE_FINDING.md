# 10 Trainer Prediction Worker Failure Finding

## Classification
PARTIALLY_CAPTURED

## Failure class
`TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`

## Alert class required
`TRAINER_INTERNAL_LIVENESS_CRITICAL`

## Read-only inputs inspected
- claude_worklog/monitoring/snapshots.jsonl (not present in current working tree)
- claude_worklog/monitoring/trainer_metrics.jsonl (not present in current working tree)
- claude_worklog/monitoring_summary.md (not present in current working tree)
- claude_worklog/post_monitor/*.md (present; used as retained evidence)
- /home/wali/Desktop/AI BOT/.logs/hybrid_trainer.log
- /home/wali/Desktop/AI BOT/logs/hybrid_trainer.log (and rotated variants)

## Evidence summary
1. Retained post-monitor evidence confirms runtime flatline signals were visible:
   - `predictions_stream_xlen` observed as `0` across sampled trainer metrics in post-monitor findings.
   - `stream_xlen.signals:trading == 0` across 720 ticks in runtime truth table.
   - heartbeat remained populated, creating an "alive" appearance.
2. This is consistent with a false-green pattern where process/heartbeat can remain alive while proposal flow is stalled.
3. Current monitor/dash implementation does not include direct trainer-internal probes for:
   - prediction worker alive/dead state
   - last prediction timestamp
   - last GPU_BATCH timestamp
   - last DECONFLICT timestamp
   - fatal trainer log signature
4. Direct string search in current monitor/dashboard code found no explicit handling for `GPU_BATCH`, `DECONFLICT`, `prediction worker`, or `Broken pipe` signatures.
5. The specific April 30 strings provided in failure evidence (`Worker exiting after 23 cycles`, `Prediction worker stopped`, `Session failed: [Errno 32] Broken pipe`) were not found in currently retained active trainer logs at validation time. Historical rotated logs do contain related signatures (`Prediction worker stopped`, `Broken pipe`) in prior incidents.

## Capture decision rationale
- Not `FULLY_CAPTURED`: root-cause and trainer-internal liveness failure were not first-class monitored.
- Not `MISSED`: downstream stall symptoms (stream flatline while heartbeat alive) were indirectly visible.
- Therefore: `PARTIALLY_CAPTURED`.

## Mandatory dashboard fields for this failure class
- trainer process alive
- trainer heartbeat fresh
- prediction worker alive
- last prediction timestamp
- last GPU_BATCH timestamp
- last DECONFLICT timestamp
- last proposal timestamp
- prediction stream growth rate
- proposal stream growth rate
- fatal trainer log signature

## Required future alert
Emit `TRAINER_INTERNAL_LIVENESS_CRITICAL` when:
- process alive = true
- heartbeat fresh = true
- AND any of:
  - prediction worker alive = false
  - last prediction age breaches threshold
  - prediction/proposal growth rates flatline over threshold window
  - fatal trainer log signature detected (e.g., broken pipe + worker stop)
