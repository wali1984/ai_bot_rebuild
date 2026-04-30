# 03 Packet Output Schema

## Packet classes
- `hourly_packet`
- `daily_packet`
- `alert_packet`

## Common required fields
- `packet_id`
- `packet_type`
- `generated_ts_utc`
- `timestamp_range` (`start_ts_utc`, `end_ts_utc`)
- `raw_evidence_pointer[]`
- `affected_component[]`
- `metric_values`
- `anomaly_classification[]`
- `verification_command[]`
- `missing_evidence[]`
- `confidence_level`

## Additional required blocks

### Feature flow block
- `ingestor_key_freshness`
- `feature_key_freshness`
- `feature_snapshot_presence_rate`
- `confidence_movement_causes[]`
- `source_redis_refs[]` (key/pattern)

### Signal attribution block
- `missing_signal_id_rate`
- `missing_confidence_rate`
- `lineage_chain_complete_rate`
- `execution_lineage_complete_rate`

### Redis memory block
- `used_memory`
- `maxmemory`
- `memory_ratio_pct`
- `memory_trend_1h`
- `memory_trend_6h`
- `memory_trend_24h`
- `threshold_class`

## File layout
- `claude_worklog/continuous_monitoring/packets/hourly/YYYYMMDD_HH.json`
- `claude_worklog/continuous_monitoring/packets/daily/YYYYMMDD.json`
- `claude_worklog/continuous_monitoring/packets/alerts/YYYYMMDD_HHMMSS_<class>.json`
