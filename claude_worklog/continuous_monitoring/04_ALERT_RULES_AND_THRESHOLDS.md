# 04 Alert Rules and Thresholds

## Alert severity model
- INFO: informational variance, no immediate risk.
- WARN: degraded behavior requiring watch.
- HIGH: actionable degradation, triage required.
- CRITICAL: strong risk signal, immediate investigation required.

## Required thresholds

### Redis memory
- >85%: WARN (`redis_memory_warning`)
- >90%: HIGH (`redis_memory_elevated`)
- >95%: CRITICAL (`redis_memory_critical`)

### Data/lineage integrity
- Missing feature lineage (`feature_snapshot_id` absent where required): HIGH
- Missing `signal_id` in executed sample above tolerance: HIGH
- Missing confidence in executed sample above tolerance: HIGH

### Heartbeat/type
- Any heartbeat WRONGTYPE event: HIGH (CRITICAL if persistent > N consecutive cycles)

### Freshness
- Stale ingestor keys beyond SLA: HIGH
- Stale feature keys beyond SLA: HIGH

### Stream behavior
- Trainer prediction stream gaps beyond configured interval: HIGH
- Signal stream empty while executions continue: HIGH/CRITICAL depending persistence

### Network path
- VPN/IP routing anomaly detected: HIGH (CRITICAL if exchange path mismatch)

### System memory pressure
- RAM available low-watermark breach: HIGH
- sustained low available RAM + Redis high memory: CRITICAL

## Alert packet minimum payload
Each alert must carry:
- raw evidence pointer,
- timestamp range,
- affected component,
- metric values,
- anomaly classification,
- verification command,
- missing evidence,
- confidence level.
