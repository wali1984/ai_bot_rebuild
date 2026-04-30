# Trainer Liveness Monitor False-Positive Fix Report

## Scope
Implemented root-cause audit fixes in read-only monitoring tooling only.

Updated files:
- claude_worklog/tools/read_only_monitor.py
- claude_worklog/tools/runtime_monitor_dashboard.py

## Fixes implemented

### 1) Log timestamp parsing (timezone correctness)
- Naive trainer log timestamps are no longer forced to UTC.
- Monitor now interprets naive log timestamps as monitor-host local timezone (`LOCAL_LOG_TZ`).
- Added explicit in-code assumption comment and exported `log_timestamp_assumption` field for observability.

### 2) Stream-growth liveness (capped-stream safe)
- Replaced primary growth evidence from `XLEN` deltas to latest stream ID timestamp progression.
- Added read-only stream metadata collection via `XREVRANGE` + `XINFO STREAM`.
- Added required `latest_stream_id` / `latest_stream_id_ts_ms` (+ age/xlen) for:
  - `wma:proposals`
  - `signals:trading:primary`
  - `signals:trading:asjad`
  - `signals:trading`
  - `wma:trainer:predictions`
- Added `capped_stream_warning` when stream IDs advance while `XLEN` remains flat on high-cardinality streams.

### 3) Liveness classification separation
- Separated liveness dimensions:
  - `trainer_process_liveness`
  - `heartbeat_liveness`
  - `prediction_loop_liveness`
  - `publish_surface_liveness`
  - `stream_growth_evidence_quality`
- Added `publish_surface_used`, `global_stream_idle_non_fatal`, and `liveness_confidence_level`.
- `signals:trading=0` is non-fatal when proposal/account surfaces are active.

### 4) Dashboard updates
Added display for:
- corrected log timestamp age
- stream latest ID age (all required streams)
- capped-stream warning
- publish surface used
- liveness confidence level

## Validation executed

### A) Python compile check
Command:
- `python3 -m py_compile claude_worklog/tools/read_only_monitor.py claude_worklog/tools/runtime_monitor_dashboard.py`

Result:
- pass (exit code 0)

### B) Dry validation
Command:
- `python3 claude_worklog/tools/read_only_monitor.py --validate-continuous-dry`

Result:
- pass (exit code 0)

### C) One-shot dashboard
Command:
- `python3 claude_worklog/tools/runtime_monitor_dashboard.py --once --root .`

Result:
- pass; dashboard rendered new fields including corrected timestamp age, stream latest ID ages, capped warning, publish surface, and liveness confidence.

## Read-only and safety constraints
- No modifications under `/home/wali/Desktop/AI BOT`.
- No trainer/trader/orchestrator/Redis/VPN restart performed.
- No Redis key write/delete operations by this fix implementation path.
- No order placement/cancel, leverage/margin changes, or V2 build actions.
