# 08 Dashboard Requirements

## Objective
Define dashboard fields for real-time operator awareness and packet-readiness state.

## Required dashboard panels
1. Current status
2. Latest alert
3. Feature visibility classification
4. Redis memory ratio
5. Trainer prediction health
6. Signal attribution completeness
7. Execution lineage completeness
8. Claude evidence packet readiness

## Required values
- status enum: `healthy`, `degraded`, `attention_required`, `critical`
- latest alert class + age
- feature visibility class (e.g., partial/complete)
- Redis memory ratio with threshold band coloring
- prediction stream heartbeat and gap indicator
- `%` completeness for signal attribution and execution lineage
- packet generation status (`hourly_ready`, `daily_ready`, `alert_ready`)

## Non-functional requirements
- read-only data sources only,
- refresh interval configurable,
- must not execute mutation commands,
- clearly show verification commands for each anomaly tile.
