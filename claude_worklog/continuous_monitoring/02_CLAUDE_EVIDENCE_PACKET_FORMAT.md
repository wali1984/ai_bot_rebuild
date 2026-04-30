# 02 Claude Evidence Packet Format

## Purpose
Standard packet format for Claude to review hourly/daily/alert states with minimal prompt tokens.

## Packet schema (required fields)
- `packet_id`
- `packet_type` (`hourly`, `daily`, `alert`)
- `generated_ts_utc`
- `timestamp_range` (`start_ts_utc`, `end_ts_utc`)
- `raw_evidence_pointer[]` (file + line/range pointers)
- `affected_component[]` (ingestor, feature pipeline, trainer, orchestrator, risk, execution, infra)
- `metric_values` (named metrics and values)
- `anomaly_classification[]`
- `verification_command[]`
- `missing_evidence[]`
- `confidence_level` (`high`, `medium`, `low`)
- `recommended_operator_action`

## Required anomaly classes
- memory_warning, memory_elevated, memory_critical
- lineage_missing
- signal_id_missing
- confidence_missing
- heartbeat_wrongtype
- key_stale
- trainer_gap
- stream_divergence
- vpn_route_anomaly

## Claude output contract
Claude review must include:
- clear risk posture,
- what changed since previous packet,
- whether escalation is required,
- explicit no-mutation reminder.
