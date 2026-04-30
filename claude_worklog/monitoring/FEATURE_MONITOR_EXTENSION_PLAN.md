# Feature Monitor Extension Plan

## Why extension is needed
Current running read-only monitor captures heartbeat/stream health and attribution fragments (`signal_id`, confidence nulls, stale counters), but does not capture complete feature-key lineage from ingestors to execution decisions.

## No-restart recommendation for current run
- Do **not** change or restart the currently running 12-hour monitor session.
- Apply extension only after the current run completes.
- Preserve continuity of the current dataset (`snapshots.jsonl`, `trainer_metrics.jsonl`).

## Additional fields to capture in future run
Per tick:
- `feature_key_inventory_count`
- `feature_key_inventory_sample`
- `feature_freshness_by_source`
- `stale_feature_sources`
- `missing_feature_sources`
- `trainer_predictions_missing_feature_snapshot_ref`
- `signals_missing_prediction_or_feature_snapshot_ref`
- `orchestrator_decisions_missing_feature_snapshot_ref`
- `trader_actions_missing_upstream_attribution`
- `downstream_unconsumed_feature_keys`

Per event-link sample:
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`
- `order_id` (if present)

## Read-only Redis commands to use
- `SCAN`
- `TYPE`
- `EXISTS`
- `TTL`
- `GET`
- `HGETALL` (limited)
- `XLEN`
- `XREVRANGE` (COUNT-limited)
- `LRANGE` (limited)
- `SCARD`
- `ZCARD`

## Explicitly forbidden operations
- Any Redis write command (`SET`, `HSET`, `XADD`, `DEL`, `XDEL`, `XTRIM`, `PUBLISH`, `FLUSH*`)
- Any service/process control
- Any exchange/trading mutation call

## Proposed output schema additions
- `feature_inventory.jsonl` (per tick namespace inventory)
- `feature_freshness.jsonl` (source freshness deltas)
- `attribution_gaps.jsonl` (missing-link records)
- `data_flow_gap_summary.md` (rollup report)

## Validation gates before adopting extension
1. Static forbidden-command scan in monitor script.
2. Dry run for 5–10 minutes in read-only mode.
3. Confirm no growth in non-monitor files.
4. Confirm schema backward compatibility for existing dashboards/parsers.
