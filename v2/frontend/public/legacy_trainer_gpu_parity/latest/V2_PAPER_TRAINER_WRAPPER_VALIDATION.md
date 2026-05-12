# V2 Paper Trainer Wrapper Validation

Generated: 2026-05-12T06:11:36Z

Source payload: `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`

Source age at validation: `24` seconds.

Current IDs:

- prediction_id: `pred_paper_tick_1778566272462`
- feature_snapshot_id: `fs_paper_tick_1778566272462`
- signal_id: `sig_paper_tick_1778566272462`
- orchestrator_decision_id: `orch_paper_tick_1778566272462`
- risk_decision_id: `risk_paper_tick_1778566272462`
- execution_intent_id: `pei_paper_tick_1778566272462`
- paper ledger result: `NO_FILL_RISK_BLOCKED`

Classification: `V2_PAPER_TRAINER_WRAPPER_INCOMPLETE`.

Missing fields for this parity contract:

```json
[
  "model_id",
  "top_positive_features",
  "top_negative_features",
  "missing_feature_flags",
  "stale_feature_flags"
]
```

Finding: the V2 wrapper is current and paper-online, but it is not complete enough to claim legacy trainer parity.
