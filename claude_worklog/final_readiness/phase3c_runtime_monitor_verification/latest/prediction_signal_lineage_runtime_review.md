# Prediction / Signal Lineage Runtime Review

Latest executed analysis:

```json
{
  "adjust_leverage_rows": 0,
  "cross_margin_pos_before_hits": 397,
  "duplicate_exchange_order_id_rows": 19,
  "executed_sample_size": 400,
  "high_leverage_pos_ge_25": 84,
  "latency_buckets": {
    "0": 60,
    "1-5s": 4,
    "30-300s": 319,
    "5-30s": 16,
    ">300s": 1
  },
  "lineage_tuple_incomplete_rows": 400,
  "missing_confidence": 40,
  "missing_feature_snapshot_id": 400,
  "missing_prediction_id": 400,
  "missing_signal_id": 46,
  "risk_add_like_success_rows": 307,
  "stale_executed_ts_ms_gt_5m": 400
}
```

Latest attribution completeness:

```json
{
  "execution_lineage_completeness_pct": 0.0,
  "execution_sample_size": 400,
  "missing_confidence": 0,
  "missing_feature_snapshot_id": 100,
  "missing_feature_snapshot_id_prediction_rows": 0,
  "missing_lineage_tuple_execution_rows": 400,
  "missing_lineage_tuple_signal_rows": 100,
  "missing_prediction_id": 100,
  "missing_prediction_id_prediction_rows": 0,
  "missing_signal_id": 0,
  "prediction_sample_size": 0,
  "signal_attribution_completeness_pct": 50.0,
  "signal_sample_size": 100
}
```

Evidence pointer: `claude_worklog/monitoring/snapshots.jsonl`.
