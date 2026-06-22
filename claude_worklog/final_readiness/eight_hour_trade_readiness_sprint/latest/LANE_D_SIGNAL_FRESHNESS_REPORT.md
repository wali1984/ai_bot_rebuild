# Lane D — Signal/Orchestrator Freshness (8h Sprint)

Generated: 2026-05-15
Lane: D
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Inputs (read-only)

- `v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json`
- `v2/frontend/public/operator_runtime/v2_signal_lineage_worker/latest/v2_signal_lineage_worker_status.json`
- `v2/frontend/public/operator_runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json`
- `v2/frontend/public/operator_runtime/v2_signal_publisher/latest/v2_signal_publisher_status.json`
- `v2/frontend/public/operator_runtime/legacy_runtime_observer/latest/legacy_runtime_observer_status.json`
- `v2/frontend/public/operator_runtime/legacy_signal_outcome_observer/latest/legacy_signal_outcome_observer_status.json`

## Freshness table

| Payload | Age (s) | Fresh (< 24h)? |
|---------|---------|----------------|
| legacy_v2_decision_comparator | recent | YES |
| v2_signal_lineage_worker | 81,298 | NO (~22.6h, near 24h boundary) |
| v2_orchestrator_adapter | 135,908 | **NO** (~37.7h, STALE) |
| v2_signal_publisher | 134,967 | **NO** (~37.5h, STALE) |
| legacy_runtime_observer | recent | YES |
| legacy_signal_outcome_observer | recent | YES |

## Findings

1. **Observatory is up to date.** The legacy_v2 decision comparator and the
   legacy outcome observer publish recent timestamps. They confirm:
   - `legacy_mutation_performed: false`
   - `old_redis_write_performed: false`
   - `exchange_action_taken: false`
   - `approval_token_created: false`
   - `live_blocked: true`
   - `live_gate: blocked_human_only`
   - `live_symbols: []`
2. **Orchestrator adapter payload is stale (~37.7h).** The V2 orchestrator
   adapter has not republished in over 24h. This is a freshness-guard hit and
   the router should classify it as `FRESHNESS_GUARD_BLOCKED_ON_STALE_PUBLIC_ARTIFACTS`.
3. **Signal publisher payload is stale (~37.5h).** Same freshness issue.
4. **Signal lineage worker is approaching staleness (~22.6h).** Not stale yet
   but near the 24h boundary.
5. **No invented outcomes.** Decision comparator reports
   `MISSING_EVIDENCE_CANNOT_COMPARE` where the legacy signal sample is too small
   or stale, in line with the observatory rule. No 99% correctness claim.

## Honest comparison status

Per the observatory and outcome observer:

- Acted-trade sample is **insufficient**: the bot is in paper-only shadow soak
  and most decisions are blocks, not allows. Decision quality cannot be claimed
  beyond `INSUFFICIENT_SAMPLE`.
- Legacy signals are read as **stale source-limited** for many symbols; the
  comparator correctly emits `MISSING_EVIDENCE_CANNOT_COMPARE`.

## What this lane does NOT do

- Does not start legacy signal publisher.
- Does not restart V2 orchestrator adapter or V2 signal publisher.
- Does not invent decision quality numbers for symbols with stale legacy signals.
- Does not authorize live, canary, legacy shutdown, or Redis trim.

## Remediation suggestion (for downstream lanes)

The two stale V2 payloads (`v2_orchestrator_adapter`, `v2_signal_publisher`)
need a republish. That's a job for the worker porting orchestrator or the
permanent objective router to dispatch — outside this read-only lane.

## GO/NO-GO for Lane D

`LANE_D_SIGNAL_FRESHNESS_READ_ONLY_REPORT_READY_TWO_STALE_PAYLOADS`

Live remains `blocked_human_only`.
