# V2 Build Impact Map From Legacy Evidence

Generated: 2026-05-06T20:09:58.386463+00:00

| Legacy evidence | V2 requirement impact | MVP lane |
|---|---|---|
| Trainer worker health gaps | trainer liveness, worker health, prediction output | paper_backtest_mvp |
| LAB hedge unwind failure | risk gateway, paper ledger, replay scenario, explainability | paper_backtest_mvp |
| Ingestor/process map | source freshness, feature snapshots, symbol aliases | legacy_parity |
| Redis stream/key metadata | replay/backtest input discovery, no live writes | paper_backtest_mvp |
| Orchestrator/trader process map | decision_id, risk_decision_id, execution_intent_id | paper_backtest_mvp |
