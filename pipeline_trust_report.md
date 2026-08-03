# Pipeline Trust Verification Report

Generated UTC: `2026-06-23T22:55:28.595562+00:00`
Mode: `read_only`
Data sources: `0`

## Summary

| Metric | Count |
|---|---:|
| Total findings | 8 |
| Critical failures | 0 |
| Failures | 1 |
| Warnings | 7 |
| Passes | 0 |

## Findings

| Status | Severity | Check | Title | Affected modules | Recommended fix |
|---|---|---|---|---|---|
| WARN | High | `candle_integrity.no_data` | no candle records found | v2/backend/app/services/market_ingest/service.py<br>v2/backend/app/cli/v2_binance_kline_wss_loop.py<br>v2/backend/app/cli/v2_feature_pipeline_native_loop.py<br>v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py | Provide JSON/JSONL snapshots or Redis access containing OHLCV candle records. |
| WARN | High | `mtf_alignment.no_decisions` | no decision records found for multi-timeframe alignment | v2/backend/app/services/feature_pipeline_native/service.py<br>v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py<br>v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py | Provide prediction/orchestrator/risk decision records with decision_time or generated_at fields. |
| WARN | High | `feature_integrity.no_data` | no feature vectors found | v2/backend/app/services/feature_pipeline_native/service.py<br>v2/backend/app/cli/v2_feature_pipeline_native_loop.py<br>v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py | Provide feature snapshot records such as v2:features:latest:* or JSON exports. |
| WARN | High | `masa_ppo.no_decisions` | no model decision records found for MASA/PPO consistency | v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py<br>v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py<br>v2/backend/app/services/rl_core/observation_schema.py | Provide prediction records containing MASA and PPO metadata. |
| WARN | High | `training_samples.no_data` | no training sample records found | v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py<br>v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py<br>v2/backend/app/services/market_state_integrity/sample_rejection.py | Provide trainer dataset/sample manifests or JSON exports with sample-level cutoffs and labels. |
| WARN | High | `execution.no_data` | no trade/order/decision execution records found | v2/backend/app/cli/v2_paper_execution_worker.py<br>v2/backend/app/services/live_gate/binance_live_order_transport.py<br>v2/backend/app/services/account_position_monitor/service.py | Provide paper ledger, risk decision, live transport, or order records. |
| WARN | High | `config.no_data` | no config/admin records found | v2/backend/app/api/v1/config_admin.py<br>v2/backend/app/cli/v2_config_admin_manager.py<br>v2/backend/app/services/config_admin/service.py<br>v2/backend/app/api/v2/trainer.py | Provide config-admin status payloads so staged dangerous settings, approvals, secrets, and mutation flags can be audited. |
| FAIL | High | `parity.known_differences` | live, paper, and backtest parity differences detected | v2/backend/app/services/replay_backtest_runner/service.py<br>v2/backend/app/services/edge_proof/replay_miner.py<br>v2/backend/app/cli/v2_paper_execution_worker.py<br>v2/backend/app/services/live_gate/binance_live_order_transport.py | Create one explicit execution-assumption contract consumed by live, paper, replay, training, and reporting. |

## Example records

### `parity.known_differences`

```json
[
  {
    "area": "fees",
    "backtest": "paper projection or edge-proof defaults",
    "live": "exchange fill fees not fully reconciled by verifier unless provided in records",
    "paper": "deterministic/default bps fields are expected",
    "recommended_fix": "Use one cost model contract with actual fill fee override when live data exists.",
    "severity": "High"
  },
  {
    "area": "slippage_latency_spread",
    "backtest": "post-hoc/default assumptions",
    "live": "real market order slippage, latency, and spread",
    "paper": "deterministic assumptions",
    "recommended_fix": "Record and replay bid/ask, latency, and fill price assumptions per decision.",
    "severity": "High"
  },
  {
    "area": "candle_finality",
    "backtest": "may use corrected/post-hoc candles unless source snapshots are supplied",
    "live": "trusts upstream finality metadata",
    "paper": "trusts upstream finality metadata",
    "recommended_fix": "Replay from immutable source snapshots with closed-candle proof.",
    "severity": "High"
  },
  {
    "area": "order_fill_assumptions",
    "backtest": "ledger projection/post-hoc fills",
    "live": "exchange lifecycle and partial fills required",
    "paper": "immediate simulated fills",
    "recommended_fix": "Use a shared order lifecycle model and mark assumptions by mode.",
    "severity": "High"
  },
  {
    "area": "liquidation_funding_position_transitions",
    "backtest": "projection from paper/replay records",
    "live": "exchange state is authoritative",
    "paper": "local state and simplified costs",
    "recommended_fix": "Persist funding, liquidation distance, margin mode, hedge mode, and transition state in every mode.",
    "severity": "Medium"
  }
]
```

## Section summaries

```json
{
  "candle_integrity": {
    "groups": [],
    "total_candles": 0
  },
  "config_admin": {
    "examples": [],
    "records_checked": 0
  },
  "feature_integrity": {
    "examples": [],
    "feature_vectors_checked": 0
  },
  "live_vs_backtest_parity": {
    "differences": [
      {
        "area": "fees",
        "backtest": "paper projection or edge-proof defaults",
        "live": "exchange fill fees not fully reconciled by verifier unless provided in records",
        "paper": "deterministic/default bps fields are expected",
        "recommended_fix": "Use one cost model contract with actual fill fee override when live data exists.",
        "severity": "High"
      },
      {
        "area": "slippage_latency_spread",
        "backtest": "post-hoc/default assumptions",
        "live": "real market order slippage, latency, and spread",
        "paper": "deterministic assumptions",
        "recommended_fix": "Record and replay bid/ask, latency, and fill price assumptions per decision.",
        "severity": "High"
      },
      {
        "area": "candle_finality",
        "backtest": "may use corrected/post-hoc candles unless source snapshots are supplied",
        "live": "trusts upstream finality metadata",
        "paper": "trusts upstream finality metadata",
        "recommended_fix": "Replay from immutable source snapshots with closed-candle proof.",
        "severity": "High"
      },
      {
        "area": "order_fill_assumptions",
        "backtest": "ledger projection/post-hoc fills",
        "live": "exchange lifecycle and partial fills required",
        "paper": "immediate simulated fills",
        "recommended_fix": "Use a shared order lifecycle model and mark assumptions by mode.",
        "severity": "High"
      },
      {
        "area": "liquidation_funding_position_transitions",
        "backtest": "projection from paper/replay records",
        "live": "exchange state is authoritative",
        "paper": "local state and simplified costs",
        "recommended_fix": "Persist funding, liquidation distance, margin mode, hedge mode, and transition state in every mode.",
        "severity": "Medium"
      }
    ]
  },
  "masa_ppo_consistency": {
    "decisions_checked": 0,
    "examples": []
  },
  "multi_timeframe_alignment": {
    "decisions_checked": 0,
    "violations": []
  },
  "position_execution": {
    "examples": [],
    "records_checked": 0
  },
  "training_samples": {
    "examples": [],
    "samples_checked": 0
  }
}
```
