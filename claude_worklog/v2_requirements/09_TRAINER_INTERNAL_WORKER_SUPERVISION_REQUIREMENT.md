# 09 Trainer Internal Worker Supervision Requirement

## Requirement ID
V2-TRAINER-LIVENESS-001

## Requirement
Before V2 build, monitoring must supervise trainer internal prediction-worker liveness independently of process and heartbeat liveness.

## Failure class (must be detectable)
`TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`

## Alert (must be emitted)
`TRAINER_INTERNAL_LIVENESS_CRITICAL`

## Minimum required observability set
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

## Exit criterion for pre-V2
A read-only validation run must prove detection of worker-dead/process-alive conditions and alerting with evidence packet output. Without this, V2 build remains NO-GO.
