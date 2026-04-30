# 02 Required Code Changes

## Target files
- `claude_worklog/tools/read_only_monitor.py` (extend)
- `claude_worklog/tools/runtime_monitor_dashboard.py` (extend)
- Optional new helper modules under `claude_worklog/tools/` for packet compile/schema validation.

## Changes in `read_only_monitor.py`
1. Add continuous mode args (planning):
   - `--continuous`
   - `--packet-output-dir`
   - `--hourly-packet-interval`
   - `--daily-cutoff-utc`
2. Add packet writer functions:
   - `write_hourly_packet()`
   - `write_daily_packet()`
   - `write_alert_packet()`
3. Add feature freshness collectors:
   - per key pattern freshness age
   - stale/missing counts
4. Add lineage/anomaly collectors:
   - missing `feature_snapshot_id`
   - missing `signal_id`
   - missing `confidence`
   - execution lineage incompleteness
5. Add memory trend collectors:
   - rolling memory ratio history
   - threshold band classification

## Changes in `runtime_monitor_dashboard.py`
1. Add packet readiness fields:
   - `hourly_ready`
   - `daily_ready`
   - `alert_ready`
2. Add latest alert display:
   - severity/classification
   - affected component
   - age
3. Add attribution completeness summary:
   - signal attribution completeness %
   - execution lineage completeness %
4. Add trainer prediction health panel:
   - prediction stream gap indicator

## Non-goals
- No change to live trading services.
- No direct writes to Redis.
- No V2 build activation.
