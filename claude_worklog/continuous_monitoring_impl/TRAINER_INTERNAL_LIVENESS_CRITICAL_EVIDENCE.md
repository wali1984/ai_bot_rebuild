# Trainer Internal Liveness CRITICAL Evidence

## Capture time (UTC)
2026-04-30

## 1) Runtime process/session confirmation
- `tmux ls`:
  - `ai_bot_read_only_monitor` present
  - `ai_bot_runtime_dashboard` present
- `pgrep -af "read_only_monitor.py|runtime_monitor_dashboard.py"`:
  - `read_only_monitor.py` running
  - `runtime_monitor_dashboard.py` running

## 2) Latest 5 snapshots (trainer internal liveness fields)
Observed from `claude_worklog/monitoring/snapshots.jsonl`:

1. `ts_utc=2026-04-30T21:03:51.867581+00:00`
   - trainer_process_alive: `true`
   - trainer_heartbeat_fresh: `true`
   - prediction_worker_alive: `false`
   - last_prediction_entry_ts: `2026-04-30T17:03:50.875000+00:00`
   - last_gpu_batch_ts: `2026-04-30T17:03:50.875000+00:00`
   - last_deconflict_ts: `2026-04-30T17:03:50.875000+00:00`
   - last_proposal_ts: `2026-04-30T20:26:14.538000+00:00`
   - prediction_stream_growth_rate: `0.0`
   - proposal_stream_growth_rate: `0.0`
   - fatal_trainer_log_signature: `NONE`
   - trainer_internal_liveness_status: `CRITICAL`

2. `ts_utc=2026-04-30T21:04:53.901494+00:00`
   - trainer_process_alive: `true`
   - trainer_heartbeat_fresh: `true`
   - prediction_worker_alive: `false`
   - last_prediction_entry_ts: `2026-04-30T17:04:45.324000+00:00`
   - last_gpu_batch_ts: `2026-04-30T17:04:46.813000+00:00`
   - last_deconflict_ts: `2026-04-30T17:04:42.285000+00:00`
   - last_proposal_ts: `2026-04-30T20:26:14.538000+00:00`
   - prediction_stream_growth_rate: `0.0`
   - proposal_stream_growth_rate: `0.0`
   - fatal_trainer_log_signature: `NONE`
   - trainer_internal_liveness_status: `CRITICAL`

3. `ts_utc=2026-04-30T21:05:55.761477+00:00`
   - trainer_process_alive: `true`
   - trainer_heartbeat_fresh: `true`
   - prediction_worker_alive: `false`
   - last_prediction_entry_ts: `2026-04-30T17:05:34.690000+00:00`
   - last_gpu_batch_ts: `2026-04-30T17:05:35.660000+00:00`
   - last_deconflict_ts: `2026-04-30T17:05:31.663000+00:00`
   - last_proposal_ts: `2026-04-30T20:26:14.538000+00:00`
   - prediction_stream_growth_rate: `0.0`
   - proposal_stream_growth_rate: `0.0`
   - fatal_trainer_log_signature: `NONE`
   - trainer_internal_liveness_status: `CRITICAL`

4. `ts_utc=2026-04-30T21:06:57.339052+00:00`
   - trainer_process_alive: `true`
   - trainer_heartbeat_fresh: `true`
   - prediction_worker_alive: `false`
   - last_prediction_entry_ts: `2026-04-30T17:06:51.976000+00:00`
   - last_gpu_batch_ts: `2026-04-30T17:06:53.338000+00:00`
   - last_deconflict_ts: `2026-04-30T17:06:48.944000+00:00`
   - last_proposal_ts: `2026-04-30T20:26:14.538000+00:00`
   - prediction_stream_growth_rate: `0.0`
   - proposal_stream_growth_rate: `0.0`
   - fatal_trainer_log_signature: `NONE`
   - trainer_internal_liveness_status: `CRITICAL`

5. `ts_utc=2026-04-30T21:07:58.844801+00:00`
   - trainer_process_alive: `true`
   - trainer_heartbeat_fresh: `true`
   - prediction_worker_alive: `false`
   - last_prediction_entry_ts: `2026-04-30T17:07:53.484000+00:00`
   - last_gpu_batch_ts: `2026-04-30T17:07:54.341000+00:00`
   - last_deconflict_ts: `2026-04-30T17:07:50.465000+00:00`
   - last_proposal_ts: `2026-04-30T20:26:14.538000+00:00`
   - prediction_stream_growth_rate: `0.0`
   - proposal_stream_growth_rate: `0.0`
   - fatal_trainer_log_signature: `NONE`
   - trainer_internal_liveness_status: `CRITICAL`

## 3) Trainer log last-seen evidence (read-only)
Sources inspected:
- `/home/wali/Desktop/AI BOT/.logs/hybrid_trainer.log`
- `/home/wali/Desktop/AI BOT/logs/hybrid_trainer.log`

Last-seen results (same in both files):
- `Prediction worker stopped`: **NOT_FOUND**
- `Worker exiting`: **NOT_FOUND**
- `Broken pipe`: **NOT_FOUND**
- `_generate_realtime_predictions`:
  - `2026-04-30 17:08:49,986 - INFO - hybrid_trainer - [DEBUG] ENTRY _generate_realtime_predictions`
- `GPU_BATCH`:
  - `2026-04-30 17:08:51,461 - WARNING - hybrid_trainer - [GPU_BATCH] Drift alerts: ['POLICY_DRIFT']`
- `DECONFLICT`:
  - `2026-04-30 17:08:46,959 - INFO - hybrid_trainer - [DECONFLICT] Step 4/4: Published 0 deconflicted signals ✅`
- `[PROPOSAL]`: **NOT_FOUND**
- `PROMOTION_HEALTH`:
  - `2026-04-30 17:08:45,208 - INFO - rl.promotion_controller - PROMOTION_HEALTH | level=2 | eligible=True | ws_connected=True | p50=277ms | p95=545ms | completeness=100.0% | rest_used=0 | ws_gb=7.02 | canary=[] | reasons=none`

## 4) Stream/key state (read-only)
`XLEN` values:
- `wma:trainer:predictions`: `0`
- `signals:trading`: `0`
- `signals:trading:primary`: `50000`
- `wma:proposals`: `50001`
- `executed_signals`: `1015`

Latest `XREVRANGE ... COUNT 1`:
- `wma:trainer:predictions`: empty
- `signals:trading`: empty
- `signals:trading:primary`: id `1777580779209-0`
- `wma:proposals`: id `1777580774538-0`
- `executed_signals`: id `1777558846793-0`

## 5) Interpretation
- Trainer process appears alive: **YES**
- Trainer heartbeat appears fresh: **YES**
- Prediction worker appears alive: **NO** (from snapshot field)
- Last prediction/GPU_BATCH/DECONFLICT timestamps are stale relative to snapshot times.
- Proposal timestamp is also stale and growth rates are repeatedly `0.0`.
- Fatal log signature in snapshot is currently `NONE`.

## 6) Classification
`TRAINER_PROCESS_ALIVE_PREDICTION_WORKER_CRITICAL`

## 7) Recommended next step (not executed)
Perform controlled trainer-side investigation focused on prediction worker lifecycle and proposal publishing path, then run a supervised recovery plan with explicit pre/post liveness checks and post-recovery monitor verification. Do not proceed toward V2 build while this critical liveness condition persists.
