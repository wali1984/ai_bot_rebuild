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

## Safety constraints
- Read-only only.
- No Redis writes/deletes.
- No process restart/stop/start.
- No live bot mutation.
