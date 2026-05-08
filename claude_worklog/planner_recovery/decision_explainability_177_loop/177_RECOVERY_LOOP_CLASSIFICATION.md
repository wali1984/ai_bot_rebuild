# 177 Decision Explainability Recovery Loop Classification

## Classification

Non-live automation loop.

Task:
`177_phase2t_decision_explainability_replay_backtest_projection_implementation`

The Codex watchdog repeatedly attempted recovery, but recovery did not close the loop. Required outputs remained missing and the same blocker recurred.

## Required fix

Codex must perform closed-loop recovery:

1. Inspect 177 task definition.
2. Verify every required output file.
3. Recover or generate missing non-live files.
4. Run validation.
5. Secret scan.
6. Produce PASS/FAIL evidence.
7. Normalize stale runtime state only after required outputs and validation pass.
8. Patch watchdog so repeated ineffective recovery does not loop indefinitely.

## Safety

No legacy bot mutation.
No Redis writes/deletes.
No live service restart.
No exchange action.
No deployment.
No live trading.

177_RECOVERY_LOOP_CLASSIFIED
