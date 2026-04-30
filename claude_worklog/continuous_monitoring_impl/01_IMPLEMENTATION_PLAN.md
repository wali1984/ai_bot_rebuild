# 01 Implementation Plan

## Scope
Implementation plan for continuous 24/7 read-only monitoring with evidence packets. This is planning only; no monitor is started by this document.

## Reuse strategy (existing design)
Reuse current `claude_worklog/tools/read_only_monitor.py` and `claude_worklog/tools/runtime_monitor_dashboard.py` where safe:
- Keep Redis reads via `redis-cli` only.
- Keep JSONL snapshot approach as base telemetry.
- Extend with packet compiler outputs (hourly/daily/alert).
- Keep dashboard as read-only renderer, extended with packet readiness and attribution metrics.

## Phased implementation

### Phase A — Baseline refactor (no behavior risk)
1. Split monitor logic into collectors + analyzers + writers modules (still one executable entrypoint).
2. Preserve current snapshot schema compatibility.
3. Add explicit `mode: continuous_read_only` field in each snapshot row.

### Phase B — Packet generation
1. Add rolling window accumulator for 1h and 24h windows.
2. Generate structured packet files:
   - hourly
   - daily
   - alert-triggered
3. Include required evidence packet fields and pointers to raw files.

### Phase C — Feature flow + attribution gaps
1. Add ingestor/feature freshness probes by configured key patterns.
2. Add checks for `feature_snapshot_id` presence in trainer-linked artifacts.
3. Add missing lineage counters (`signal_id`, confidence, lineage tuple).

### Phase D — Redis memory trend
1. Capture memory ratio per interval.
2. Compute 1h/6h/24h trend slope.
3. Emit threshold alerts at 85/90/95% bands.

### Phase E — Dashboard extension
1. Add packet-readiness panel (hourly/daily/alert).
2. Add attribution completeness panel.
3. Add latest alert summary with severity and age.

### Phase F — Revalidation gate
1. Run read-only validation cycle after implementation.
2. Compare results to post-monitor baseline.
3. Publish GO/NO-GO evidence.

### Phase G — Trainer internal liveness (mandatory)
1. Add first-class failure class: `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE`.
2. Add critical alert: `TRAINER_INTERNAL_LIVENESS_CRITICAL`.
3. Add trainer-internal liveness probes and dashboard fields:
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
4. Detect false-green condition: process/heartbeat alive while prediction worker and proposal flow are stalled.
5. Treat this phase as a hard precondition for V2 build readiness.

## Mandatory pre-V2 gate
- V2 build is blocked until `TRAINER_INTERNAL_LIVENESS_CRITICAL` coverage is implemented and validated by read-only runtime evidence.
- Any monitor run that cannot detect `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE` is `NO_GO` for V2 preparation.

## Safety constraints
- Read-only only.
- No Redis writes/deletes.
- No process restart/stop/start.
- No live bot mutation.
