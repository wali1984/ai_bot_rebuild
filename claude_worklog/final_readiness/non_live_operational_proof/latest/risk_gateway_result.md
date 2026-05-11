# Risk Gateway Result

- generated_at: `2026-05-08T00:00:00Z`
- live_gate_status: `blocked_human_only`

## Operator Summary

- risk_decisions: 5

## JSON Payload

```json
{
  "decisions": [
    {
      "block_or_allow_reason": "not_blocked",
      "checkpoint_id": "ckpt_safe_long_paper_intent_2026_05",
      "confidence": 0.82,
      "confidence_calibrated": 0.82,
      "confidence_raw": 0.86,
      "decision_id": "dec_safe_long_paper_intent",
      "direction": "long",
      "execution_intent_id": "intent_safe_long_paper_intent",
      "feature_flags": {
        "missing": [],
        "stale": [],
        "unused": [
          "live_execution_adapter",
          "redis_stream_writer",
          "exchange_order_client"
        ]
      },
      "feature_snapshot_id": "fs_safe_long_paper_intent",
      "live_gate_status": "blocked_human_only",
      "model_version": "hybrid_trainer_v2026_05",
      "paper_pnl": "+12.40",
      "paper_trade_id": "paper_safe_long_paper_intent",
      "prediction_id": "pred_safe_long_paper_intent",
      "requested_action": "open_long",
      "risk_action": "allow",
      "risk_decision": "allow",
      "risk_decision_id": "rd_safe_long_paper_intent",
      "risk_reason": "not_blocked",
      "scenario_id": "safe_long_paper_intent",
      "shadow_decision_id": "shadow_safe_long_paper_intent",
      "side": "long",
      "symbol": "BTCUSDT",
      "trainer_worker_liveness": "alive"
    },
    {
      "block_or_allow_reason": "stale_feature_snapshot",
      "checkpoint_id": "ckpt_stale_data_blocked_2026_05",
      "confidence": 0.78,
      "confidence_calibrated": 0.78,
      "confidence_raw": 0.81,
      "decision_id": "dec_stale_data_blocked",
      "direction": "long",
      "execution_intent_id": "intent_stale_data_blocked",
      "feature_flags": {
        "missing": [],
        "stale": [
          "feature_snapshot"
        ],
        "unused": [
          "live_execution_adapter",
          "redis_stream_writer",
          "exchange_order_client"
        ]
      },
      "feature_snapshot_id": "fs_stale_data_blocked",
      "live_gate_status": "blocked_human_only",
      "model_version": "hybrid_trainer_v2026_05",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_stale_data_blocked",
      "prediction_id": "pred_stale_data_blocked",
      "requested_action": "open_long",
      "risk_action": "deny",
      "risk_decision": "deny",
      "risk_decision_id": "rd_stale_data_blocked",
      "risk_reason": "stale_feature_snapshot",
      "scenario_id": "stale_data_blocked",
      "shadow_decision_id": "shadow_stale_data_blocked",
      "side": "long",
      "symbol": "ETHUSDT",
      "trainer_worker_liveness": "degraded"
    },
    {
      "block_or_allow_reason": "duplicate_signal",
      "checkpoint_id": "ckpt_duplicate_signal_blocked_2026_05",
      "confidence": 0.74,
      "confidence_calibrated": 0.74,
      "confidence_raw": 0.77,
      "decision_id": "dec_duplicate_signal_blocked",
      "direction": "short",
      "execution_intent_id": "intent_duplicate_signal_blocked",
      "feature_flags": {
        "missing": [],
        "stale": [],
        "unused": [
          "live_execution_adapter",
          "redis_stream_writer",
          "exchange_order_client"
        ]
      },
      "feature_snapshot_id": "fs_duplicate_signal_blocked",
      "live_gate_status": "blocked_human_only",
      "model_version": "hybrid_trainer_v2026_05",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_duplicate_signal_blocked",
      "prediction_id": "pred_duplicate_signal_blocked",
      "requested_action": "open_short",
      "risk_action": "deny",
      "risk_decision": "deny",
      "risk_decision_id": "rd_duplicate_signal_blocked",
      "risk_reason": "duplicate_signal",
      "scenario_id": "duplicate_signal_blocked",
      "shadow_decision_id": "shadow_duplicate_signal_blocked",
      "side": "short",
      "symbol": "SOLUSDT",
      "trainer_worker_liveness": "alive"
    },
    {
      "block_or_allow_reason": "hedge_close_would_leave_naked_short",
      "checkpoint_id": "ckpt_hedge_close_residual_exposure_blocked_2026_05",
      "confidence": 0.69,
      "confidence_calibrated": 0.69,
      "confidence_raw": 0.72,
      "decision_id": "dec_hedge_close_residual_exposure_blocked",
      "direction": "short",
      "execution_intent_id": "intent_hedge_close_residual_exposure_blocked",
      "feature_flags": {
        "missing": [],
        "stale": [],
        "unused": [
          "live_execution_adapter",
          "redis_stream_writer",
          "exchange_order_client"
        ]
      },
      "feature_snapshot_id": "fs_hedge_close_residual_exposure_blocked",
      "live_gate_status": "blocked_human_only",
      "model_version": "hybrid_trainer_v2026_05",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_hedge_close_residual_exposure_blocked",
      "prediction_id": "pred_hedge_close_residual_exposure_blocked",
      "requested_action": "close_protective_long",
      "risk_action": "deny",
      "risk_decision": "deny",
      "risk_decision_id": "rd_hedge_close_residual_exposure_blocked",
      "risk_reason": "hedge_close_would_leave_naked_short",
      "scenario_id": "hedge_close_residual_exposure_blocked",
      "shadow_decision_id": "shadow_hedge_close_residual_exposure_blocked",
      "side": "short",
      "symbol": "BNBUSDT",
      "trainer_worker_liveness": "alive"
    },
    {
      "block_or_allow_reason": "short_squeeze_and_hedge_unwind_residual_exposure",
      "checkpoint_id": "ckpt_lab_hedge_unwind_short_squeeze_2026_05",
      "confidence": 0.66,
      "confidence_calibrated": 0.66,
      "confidence_raw": 0.69,
      "decision_id": "dec_lab_hedge_unwind_short_squeeze",
      "direction": "short",
      "execution_intent_id": "intent_lab_hedge_unwind_short_squeeze",
      "feature_flags": {
        "missing": [],
        "stale": [],
        "unused": [
          "live_execution_adapter",
          "redis_stream_writer",
          "exchange_order_client"
        ]
      },
      "feature_snapshot_id": "fs_lab_hedge_unwind_short_squeeze",
      "live_gate_status": "blocked_human_only",
      "model_version": "hybrid_trainer_v2026_05",
      "paper_pnl": "legacy_loss_avoided",
      "paper_trade_id": "paper_lab_hedge_unwind_short_squeeze",
      "prediction_id": "pred_lab_hedge_unwind_short_squeeze",
      "requested_action": "close_protective_long",
      "risk_action": "deny",
      "risk_decision": "deny",
      "risk_decision_id": "rd_lab_hedge_unwind_short_squeeze",
      "risk_reason": "short_squeeze_and_hedge_unwind_residual_exposure",
      "scenario_id": "lab_hedge_unwind_short_squeeze",
      "shadow_decision_id": "shadow_lab_hedge_unwind_short_squeeze",
      "side": "short",
      "symbol": "LABUSDT",
      "trainer_worker_liveness": "worker_dead"
    }
  ],
  "generated_at": "2026-05-08T00:00:00Z",
  "live_gate_status": "blocked_human_only",
  "policy": "default_deny_non_live_operator_proof"
}
```
