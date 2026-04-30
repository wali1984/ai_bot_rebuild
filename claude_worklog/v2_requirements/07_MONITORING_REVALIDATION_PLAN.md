# 07 Monitoring Revalidation Plan

## Trigger
Run this revalidation after observability/attribution changes are implemented.

## Required method
- Execute a full read-only monitor cycle again.
- Use dashboard plus JSONL outputs for quantitative validation.
- Do not mutate production services during validation.

## Required pass conditions
1. Feature attribution status is no longer partial.
2. Full lineage tuple present across sampled trainer->signal->orchestrator->risk->execution records.
3. `missing_signal_id` and `missing_confidence` trend to zero in sampled executed analysis.
4. Heartbeat channels show no `WRONGTYPE` events.
5. Redis memory operates below critical threshold for full validation window.
6. Monitor completes naturally without critical errors.

## Required dashboard metrics to review
- monitor completion state
- elapsed runtime hours
- snapshot freshness
- parse error count
- critical error count
- Redis memory ratio
- feature visibility classification
- final recommendation state

## Evidence artifacts
- updated monitor summary,
- updated dashboard report,
- updated feature visibility audit,
- updated truth table with pass/fail marks.
