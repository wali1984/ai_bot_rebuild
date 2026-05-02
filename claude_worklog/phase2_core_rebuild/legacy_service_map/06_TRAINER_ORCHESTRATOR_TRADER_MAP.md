# Trainer / Orchestrator / Trader Map

Trainer:
- Legacy command: `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`.
- GPU-oriented behavior and batching assumptions must be preserved.
- Do not replace with a basic trainer.
- Required fixes: worker liveness, broken pipe/stdout fragility, feature_snapshot_id, prediction_id, confidence attribution, explainability.

Orchestrator:
- Legacy command: `python3 -m rl.orchestrator_worker`.
- Conditional on `ORCHESTRATOR_WORKER_ENABLED`.
- V2 strategy: preserve useful decision logic, add `decision_id`, link to signal/prediction IDs, and route through risk gateway.

Trader:
- Legacy command: `trading/trader.py`; `trading/trader-asjad.py` is in startup script but not currently running.
- V2 strategy: trader fleet paper adapter first, then shadow, then final human live gate.
- Risk gateway is final authority.

TRAINER_ORCHESTRATOR_TRADER_MAP_READY
