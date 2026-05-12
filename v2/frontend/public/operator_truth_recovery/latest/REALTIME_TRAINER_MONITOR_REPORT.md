# Realtime Trainer Monitor Report

Generated at: 2026-05-12T00:03:53.853Z

Status: TRAINER_RUNTIME_EVIDENCE_MISSING

- Trainer processes observed: 0
- Trainer monitor payload age seconds: 58676
- Latest trainer status from monitor payload: DEGRADED
- Prediction worker alive from monitor payload: true
- Prediction lineage gap: runtime evidence still has missing prediction/feature snapshot links

Latest prediction shown in UI:

- Classification: STATIC_PROOF_FIXTURE
- prediction_id: hist_pred_day03_btc_winner_preserved
- symbol: BTCUSDT
- model/checkpoint: hybrid_trainer_v2026_05 / ckpt_btc_fixture
- warning: This is proof fixture data, not real-time trainer output.

Conclusion:

TRAINER_RUNTIME_EVIDENCE_MISSING. The dashboard must not imply current trainer predictions are live.
