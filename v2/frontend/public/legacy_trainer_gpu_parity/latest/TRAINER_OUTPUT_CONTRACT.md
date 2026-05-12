# Trainer Output Contract

Generated: 2026-05-12T06:11:36Z

## Legacy Output Surfaces

Evidence from `legacy_reference/rl/hybrid_trainer.py` and `legacy_reference/scripts/monitor_trainer_predictions.py` shows the legacy trainer/monitor uses:

- `prediction:<symbol>:<timeframe>` hashes with direction/action/confidence/timestamp/published flags.
- `wma:proposals` and `signals:trading:primary` streams.
- `signals:debug` stream and `signals:trading:last:<symbol>:<timeframe>` hashes.
- decision/proposal fields such as symbol, timeframe, action, confidence, decision_id, sizing, leverage/position recommendations, and model details.

## Required V2 Paper Wrapper Fields

```json
{
  "confidence_calibrated": 0.559674,
  "confidence_delta": -0.02,
  "confidence_raw": 0.579674,
  "execution_intent_id": "pei_paper_tick_1778566272462",
  "feature_freshness": "CURRENT",
  "feature_snapshot_id": "fs_paper_tick_1778566272462",
  "missing_feature_flags": null,
  "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
  "model_id": null,
  "orchestrator_decision_id": "orch_paper_tick_1778566272462",
  "paper_ledger_result": "NO_FILL_RISK_BLOCKED",
  "prediction_id": "pred_paper_tick_1778566272462",
  "risk_decision_id": "risk_paper_tick_1778566272462",
  "source_data_pointers": {
    "local_runtime_status": "v2/runtime/paper_online/latest/paper_runtime_status.json",
    "public_runtime_status": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json"
  },
  "stale_feature_flags": null,
  "symbol": "BTCUSDT",
  "timeframe": "1m",
  "top_features": [
    {
      "name": "return_5m",
      "value": 7.51e-05
    },
    {
      "name": "return_15m",
      "value": 1.23e-06
    },
    {
      "name": "volatility_10",
      "value": 0.0001439
    }
  ],
  "top_negative_features": null,
  "top_positive_features": null
}
```

Missing required V2 wrapper fields:

```json
[
  "model_id",
  "top_positive_features",
  "top_negative_features",
  "missing_feature_flags",
  "stale_feature_flags"
]
```

Classification: `V2_PAPER_TRAINER_WRAPPER_INCOMPLETE`.

The current wrapper emits current paper lineage, but it is incomplete for this parity task because explicit `model_id`, `top_positive_features`, `top_negative_features`, `missing_feature_flags`, and `stale_feature_flags` are not present as first-class fields.
