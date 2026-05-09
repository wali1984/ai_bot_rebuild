# Replay / Backtest Result

- generated_at: `2026-05-08T00:00:00Z`
- live_gate_status: `blocked_human_only`

## Operator Summary

- scenarios: 5
- allowed: 1
- blocked: 4

## JSON Payload

```json
{
  "allowed_count": 1,
  "blocked_count": 4,
  "generated_at": "2026-05-08T00:00:00Z",
  "gross_paper_pnl": "+12.40",
  "live_gate_status": "blocked_human_only",
  "max_drawdown_placeholder": "0.00",
  "mode": "offline_fixture",
  "run_id": "non_live_replay_backtest_fixture_run",
  "scenario_count": 5,
  "scenarios": [
    {
      "block_or_allow_reason": "not_blocked",
      "confidence": 0.82,
      "decision_id": "dec_safe_long_paper_intent",
      "direction": "long",
      "execution_intent_id": "intent_safe_long_paper_intent",
      "explanation_payload": {
        "causes": [
          "feature_freshness=fresh",
          "duplicate_signal=False",
          "squeeze_context=none",
          "requested_action=open_long"
        ],
        "no_live_side_effects": true,
        "operator_visible": true,
        "summary": "BTCUSDT open_long -> allow_paper_open_long"
      },
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
      "legacy_action": "open_long",
      "live_gate_status": "blocked_human_only",
      "paper_pnl": "+12.40",
      "paper_trade_id": "paper_safe_long_paper_intent",
      "prediction_id": "pred_safe_long_paper_intent",
      "requested_action": "open_long",
      "risk_decision": "allow",
      "risk_decision_id": "rd_safe_long_paper_intent",
      "scenario_id": "safe_long_paper_intent",
      "shadow_decision_id": "shadow_safe_long_paper_intent",
      "side": "long",
      "symbol": "BTCUSDT",
      "v2_action": "allow_paper_open_long"
    },
    {
      "block_or_allow_reason": "stale_feature_snapshot",
      "confidence": 0.78,
      "decision_id": "dec_stale_data_blocked",
      "direction": "long",
      "execution_intent_id": "intent_stale_data_blocked",
      "explanation_payload": {
        "causes": [
          "feature_freshness=stale",
          "duplicate_signal=False",
          "squeeze_context=none",
          "requested_action=open_long"
        ],
        "no_live_side_effects": true,
        "operator_visible": true,
        "summary": "ETHUSDT open_long -> block"
      },
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
      "legacy_action": "open_long",
      "live_gate_status": "blocked_human_only",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_stale_data_blocked",
      "prediction_id": "pred_stale_data_blocked",
      "requested_action": "open_long",
      "risk_decision": "deny",
      "risk_decision_id": "rd_stale_data_blocked",
      "scenario_id": "stale_data_blocked",
      "shadow_decision_id": "shadow_stale_data_blocked",
      "side": "long",
      "symbol": "ETHUSDT",
      "v2_action": "block"
    },
    {
      "block_or_allow_reason": "duplicate_signal",
      "confidence": 0.74,
      "decision_id": "dec_duplicate_signal_blocked",
      "direction": "short",
      "execution_intent_id": "intent_duplicate_signal_blocked",
      "explanation_payload": {
        "causes": [
          "feature_freshness=fresh",
          "duplicate_signal=True",
          "squeeze_context=none",
          "requested_action=open_short"
        ],
        "no_live_side_effects": true,
        "operator_visible": true,
        "summary": "SOLUSDT open_short -> block"
      },
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
      "legacy_action": "open_short",
      "live_gate_status": "blocked_human_only",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_duplicate_signal_blocked",
      "prediction_id": "pred_duplicate_signal_blocked",
      "requested_action": "open_short",
      "risk_decision": "deny",
      "risk_decision_id": "rd_duplicate_signal_blocked",
      "scenario_id": "duplicate_signal_blocked",
      "shadow_decision_id": "shadow_duplicate_signal_blocked",
      "side": "short",
      "symbol": "SOLUSDT",
      "v2_action": "block"
    },
    {
      "block_or_allow_reason": "hedge_close_would_leave_naked_short",
      "confidence": 0.69,
      "decision_id": "dec_hedge_close_residual_exposure_blocked",
      "direction": "short",
      "execution_intent_id": "intent_hedge_close_residual_exposure_blocked",
      "explanation_payload": {
        "causes": [
          "feature_freshness=fresh",
          "duplicate_signal=False",
          "squeeze_context=residual_short_exposure",
          "requested_action=close_protective_long"
        ],
        "no_live_side_effects": true,
        "operator_visible": true,
        "summary": "BNBUSDT close_protective_long -> block_or_reduce"
      },
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
      "legacy_action": "close_protective_long",
      "live_gate_status": "blocked_human_only",
      "paper_pnl": "0.00",
      "paper_trade_id": "paper_hedge_close_residual_exposure_blocked",
      "prediction_id": "pred_hedge_close_residual_exposure_blocked",
      "requested_action": "close_protective_long",
      "risk_decision": "deny",
      "risk_decision_id": "rd_hedge_close_residual_exposure_blocked",
      "scenario_id": "hedge_close_residual_exposure_blocked",
      "shadow_decision_id": "shadow_hedge_close_residual_exposure_blocked",
      "side": "short",
      "symbol": "BNBUSDT",
      "v2_action": "block_or_reduce"
    },
    {
      "block_or_allow_reason": "short_squeeze_and_hedge_unwind_residual_exposure",
      "confidence": 0.66,
      "decision_id": "dec_lab_hedge_unwind_short_squeeze",
      "direction": "short",
      "execution_intent_id": "intent_lab_hedge_unwind_short_squeeze",
      "explanation_payload": {
        "causes": [
          "feature_freshness=fresh",
          "duplicate_signal=False",
          "squeeze_context=eighty_percent_pump_against_short",
          "requested_action=close_protective_long",
          "legacy_failure_case=LAB hedge unwind short squeeze"
        ],
        "no_live_side_effects": true,
        "operator_visible": true,
        "summary": "LABUSDT close_protective_long -> block_or_reduce"
      },
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
      "legacy_action": "close_long_leave_short_exposed",
      "live_gate_status": "blocked_human_only",
      "paper_pnl": "legacy_loss_avoided",
      "paper_trade_id": "paper_lab_hedge_unwind_short_squeeze",
      "prediction_id": "pred_lab_hedge_unwind_short_squeeze",
      "requested_action": "close_protective_long",
      "risk_decision": "deny",
      "risk_decision_id": "rd_lab_hedge_unwind_short_squeeze",
      "scenario_id": "lab_hedge_unwind_short_squeeze",
      "shadow_decision_id": "shadow_lab_hedge_unwind_short_squeeze",
      "side": "short",
      "symbol": "LABUSDT",
      "v2_action": "block_or_reduce"
    }
  ]
}
```
