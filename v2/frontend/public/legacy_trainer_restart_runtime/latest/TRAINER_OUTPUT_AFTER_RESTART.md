# Trainer Output After Restart

Generated: 2026-05-12T16:50:13Z

Classification: `LEGACY_TRAINER_OUTPUT_CURRENT`

Latest legacy PPO log evidence:

```text
2026-05-12 12:50:10,969 - INFO - hybrid_trainer - PPO_DECISION_RAW | account=primary | symbol=ALICEUSDT | tf=15m | action_id=1 | action=OPEN_LONG | ppo_conf=0.6154 | top1=0.4437 | top2=0.4270 | top1_id=1 | top2_id=2
```

Trainer-origin stream observation during window:

```json
{
  "age_seconds": 1,
  "data_excerpt": "{\"account_id\": \"primary\", \"action\": \"HOLD\", \"category\": \"OPEN_RISK\", \"confidence\": 0.01, \"created_ts_ms\": 1778602159924, \"ctx_id\": \"\", \"current_price\": 0.0, \"cycle_id\": \"c_3557204319\", \"event\": \"TRADE_PROPOSAL\", \"expected_edge_net\": 0.0, \"expected_pnl_usd\": 0.0, \"hedge_intent\": false, \"hedge_necessity_class\": 0, \"leverage\": 10.0, \"liqmap_ts_ms\": 1778602102236, \"margin_usd\": 86.60904363920001, \"metadata\": {\"_aggregation_key\": \"1000PEPEUSDT:OPEN_RISK\", \"_broadcast_model_multi_account\": true, \"_broadcast_open_multi_account\": true, \"_majority_score\": 0.0897641122341156, \"_minority_score\": 0.0, \"_original_ts_ms\": 1778602152482, \"_scores\": {\"capital_efficiency\": 0.0, \"data_quality\": 1.0, \"edge_net_usd\": 0.0, \"fill_prob\": 0.5, \"liq_risk\": 0.0, \"regime\": \"IMPULSE\", \"toxicity_score\": 0.0, \"utility\": 2.5}, \"_universe_score\": 0.598427414894104, \"_utility\": 2.5, \"account_id\": \"primary\", \"action\": \"HOLD\", \"action_category\": \"PROTECTIVE\", \"action_name\": \"HOLD\", \"action_space\": \"trade\", \"bias_dir\": 0, \"blended_logit\": 0.058802515268325806, \"blocked_action\": \"OPEN_LONG\", \"blocked_action_category\": \"OPEN_RISK\", \"builder_version\": \"v2_open_risk\", \"category\": \"PROTECTIVE\", \"confidence\": 0.01, \"conflict_score\": 0.5, \"constraints_applied\": [\"WARNING_LOW_LIQUIDITY (Reduced liquidity: depth $38372 < $75000)\"], \"contrary_htf_bias\": false, \"created_ts_ms\": 1778602159918, \"decision_id\": \"1778602159918-1000PEPEUSDT-multi-primary\", \"deconflicted\": true, \"dq_liq_updated_age_ms\": 57688, \"dq_liqmap_age_ms\": 57688, \"dq_liqmap_source_key\": \"unified_features:1000PEPEUSDT:1m\", \"dq_ob_age_ms\": 68, \"dq_ob_source_key\": \"msnap:coinapi_wsds:1000PEPEUSDT\", \"drift_feature_psi\": 0.008767505883284355, \"drift_policy_kl\": 0.18795316603400505, \"exec_depth_usd\": 0.0, \"exec_hist_p95_slippage_bps\": 0.0, \"exec_hist_slippage_bps\": 0.0, \"exec_spread_bps\": 0.0, \"exec_strategy\": \"TAKER\", \"exec_twap_interval_sec\": 0, \"exec_twap_slices\": 1, \"exec_urgency\": 0.597, \"fast_move_score\": 0.3953, \"final_action\": \"OPEN_LONG\", \"he",
  "sampled_at": "2026-05-12T16:09:21Z",
  "stream": "wma:proposals",
  "stream_id": "1778602159926-0",
  "summary": {
    "action": "HOLD",
    "confidence": 0.01,
    "created_ts_ms": 1778602159924,
    "decision_id": "1778602159918-1000PEPEUSDT-multi-primary",
    "event": "TRADE_PROPOSAL",
    "exchange_order_id": null,
    "feature_snapshot_id": null,
    "features_age_ms": null,
    "proposal_id": "fd130f56-03cc-40f0-bdd4-2246b19cf8c0",
    "signal_id": "0138e54a-9e40-48f5-b11c-85e48ae0b0a6",
    "source": "trainer",
    "source_module": "trainer",
    "symbol": "1000PEPEUSDT"
  }
}
```

Findings:
- Legacy trainer process is observed and GPU-backed.
- Current trainer log output exists.
- Explicit `prediction_id`, `feature_snapshot_id`, `model/checkpoint`, and calibrated confidence were not present in the captured current legacy log row.
- Legacy publish path activity was observed in Redis streams.
