# Prediction, Signal, and Actionability Audit — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01T22:56:31Z

## Summary

- **Total prediction keys in Redis**: 1,070 (v2:prediction:{sym}:{tf})
- **Symbols with predictions**: ~93 (5 timeframes each = ~465 keys; excess = prior runs)
- **Timeframes**: 1m, 5m, 15m, 1h, 4h
- **Sample prediction age**: BTCUSDT 1h fresh at 2026-07-01T23:09:10Z
- **Model source**: V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA
- **Checkpoint**: v2_hybrid_ckpt_6d9f8817bed9ead40229baf7

## Sample Prediction — BTCUSDT 1h (Live Data at Audit Time)

```json
{
  "selected_action": "short",
  "confidence_calibrated": 0.7224,
  "confidence_raw": 0.9999999997,
  "expected_move_bps": -13.88,
  "expected_move_after_cost_bps": -1.88,
  "market_state_integrity_score": 96.25,
  "data_coverage_percent": 80.89,
  "missing_feature_count": 30,
  "checkpoint_id": "v2_hybrid_ckpt_6d9f8817bed9ead40229baf7",
  "feature_snapshot_id": "v2_fsnap_891a1...",
  "feature_vector_hash": "v2_hybrid_tensor_8562a4c6...",
  "decision_time": "2026-07-01T23:09:10.352Z",
  "available_at": "2026-07-01T23:06:05.074Z",
  "feature_cutoff": "2026-07-01T22:59:59.999Z",
  "live_gate": "blocked_human_only",
  "exchange_mutation": false,
  "cuda_active": true,
  "model_consumable": true
}
```

## How A Prediction Becomes A Signal

1. **Trainer** publishes prediction to `v2:prediction:{sym}:{tf}` every cycle
2. **Orchestrator** reads all `v2:prediction:*` keys → arbitration
3. Orchestrator selects 1 winner per (symbol, side) bucket (deconflict: OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS)
4. Winner written to `v2:orchestrator:decisions` + `v2:signals:paper`
5. **Risk gateway** reads orchestrator decision, evaluates risk rules
6. Risk decision written to `v2:risk:gateway:decisions`
7. **Paper trader** reads risk decision → if ALLOW → opens paper position
8. Current: ALL risk decisions = DENY (deny_default, live gate blocked)

## Actionability Status

| Condition | Status |
|-----------|--------|
| Predictions published | YES — 1,070 keys |
| Predictions fresh | YES — BTCUSDT 1h age < 4 minutes |
| LONG predictions alive | YES — model outputs long/short/no_trade |
| SHORT predictions alive | YES (BTCUSDT 1h: short selected) |
| NO_TRADE predictions alive | YES (action_probabilities includes no_trade) |
| Paper actionable | BLOCKED — deny_default (live gate blocks all) |
| Live actionable | BLOCKED — live_gate = blocked_human_only |
| Stale predictions can enter paper | NO — paper fill gate checks feature freshness |
| All symbols covered | YES — all 93 active symbols have predictions |

## Block Reasons (from orchestrator heartbeat)

- **LIVE_GATE_NOT_ENABLED** — live_gate ≠ live_enabled
- **TRADER_EXECUTION_ENABLED_NOT_TRUE** — order_transport_submit_enabled = false
- **LIVE_SYMBOL_SETS_DO_NOT_MATCH_ACCEPTED_SYMBOLS** — no live symbols configured
- **ORDER_TRANSPORT_SUBMIT_NOT_ENABLED** — submit guard active
- **LIVE_GATE_RUNTIME_STATE_STALE** — live gate state age > 1.6M seconds (stale by design)

## RL Core Sidecar Rows
- Written to `v2:rl_core:inference:{sym}:{tf}` (advisory only)
- Not used in paper or live decisions
- Compared against native predictions for research

## Confidence Calibration
- **confidence_raw**: raw model output probability (often near 1.0 — needs calibration)
- **confidence_calibrated**: post-calibration (0.72 for BTCUSDT 1h) — this is the actionable value
- Calibration applied to map raw model confidence → realistic win probability

## Missing Evidence
- **paper_actionable** field: not populated in sample prediction (field may be set by orchestrator, not publisher)
- **live_actionable** field: not populated in sample prediction
- **strategy assignment** fields: not surfaced in sample prediction
- **Win rate aggregate**: not in prediction keys; requires closed trade analysis
