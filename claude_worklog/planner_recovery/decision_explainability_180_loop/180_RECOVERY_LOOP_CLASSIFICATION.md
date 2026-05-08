# 180 Recovery Loop Classification

## Classification

Non-live recovery loop.

Task:
`180_phase2u_decision_explainability_orchestrator_decision_projection_implementation`

The Codex watchdog reached its recovery attempt limit and did not close the blocker.

## Required decision

Codex must decide whether 180 is:

1. required for the current `V2_BACKTEST_AND_PAPER_MVP_READY` gate, or
2. an explainability-ui projection task that can be explicitly deferred without blocking core paper/backtest readiness.

## Required recovery

- If required: implement/recover missing files, validate, secret-scan, mark ready.
- If optional/deferable: create explicit deferral evidence and mark runtime state `superseded_by_evidence` / deferred to `explainability_ui`.

## Safety

No legacy bot mutation.
No Redis writes/deletes.
No live service restart.
No exchange action.
No deployment.
No live trading.

180_RECOVERY_LOOP_CLASSIFIED
