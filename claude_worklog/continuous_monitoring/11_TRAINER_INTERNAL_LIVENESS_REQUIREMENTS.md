# 11 Trainer Internal Liveness Requirements

## New first-class failure class
`TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`

## New first-class alert
`TRAINER_INTERNAL_LIVENESS_CRITICAL`

## Requirement intent
Continuous read-only monitoring must detect trainer false-green conditions where process and heartbeat remain alive while prediction production has stopped.

## Mandatory detection fields
1. trainer process alive
2. trainer heartbeat fresh
3. prediction worker alive
4. last prediction timestamp
5. last GPU_BATCH timestamp
6. last DECONFLICT timestamp
7. last proposal timestamp
8. prediction stream growth rate
9. proposal stream growth rate
10. fatal trainer log signature

## Mandatory decision rule
Raise `TRAINER_INTERNAL_LIVENESS_CRITICAL` if:
- process alive = true
- heartbeat fresh = true
- AND (prediction worker alive = false OR prediction/proposal growth rate flatline over threshold window OR fatal trainer log signature present).

## Mandatory packet evidence additions
Include in hourly/alert packets:
- `trainer_internal_liveness` object with all fields above
- threshold window and breach duration
- raw evidence pointers for trainer log excerpt and stream growth counters

## Dashboard requirements
Dashboard must render all 10 mandatory fields and show a computed state:
- HEALTHY
- DEGRADED
- CRITICAL (`TRAINER_INTERNAL_LIVENESS_CRITICAL`)

## Pre-V2 gate
This requirement is mandatory before any V2 build go decision.
