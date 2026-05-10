# Planner Turn 2Z — Third Re-Invocation at HEAD `927fc65`, Authored Codex Watchdog Cleanup Task

## Date
2026-05-10

## HEAD at planner turn open
`927fc65 Codex watchdog recover dirty non-live automation artifacts`

This is the third planner re-invocation at the same HEAD that the prior two Phase 2Z planner-turn notes opened on. No new commit has landed since `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` and `PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md` were authored, and no Codex watchdog cycle has run.

## Worktree state at planner turn open
`git status --porcelain` returns:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json
?? claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md
?? claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md
```

The same four-path dirty tree the prior re-invocation observed. No active Claude/Codex/Ollama child is running.

## Why the prior surgical-fix-deferred decision is no longer the right move
The prior planner turn (`PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md`) explicitly deferred the surgical END_FILE strip on task 197 JSON to the Codex watchdog and refused to re-emit task 197 in order to avoid racing the watchdog. The deferral was correct as a single decision but is no longer correct as a repeated decision: the watchdog has not run for two planner turns, the dirty tree has not been resolved, and the planner is now emitting consecutive standby narrative notes without forward progress.

REQ_0015 § "Codex watchdog lane" enumerates the watchdog's automatic-trigger conditions, including:
- `human_attention_required appears`
- `planner emits no-progress/halt loop`
- `git dirty with no active process`
- `materialization path mismatch occurs`
- `Codex FAIL marker appears`
- `stale status conflicts with PASS evidence`

The current state hits three of these triggers simultaneously: planner no-progress halt loop (this third consecutive re-invocation is the loop), git dirty with no active process (four-path dirty tree at HEAD `927fc65`), and materialization path mismatch (the JSON parser-breaking END_FILE leakage at end of task 197 JSON body). REQ_0016 § "Operating loop" step 7 explicitly enumerates "Remove standalone END_FILE leakage" as part of every watchdog cycle. The cleanup is squarely within Lane C `codex_watchdog` authority.

## What this turn does instead of another standby note
This turn authors an **explicit Codex watchdog recovery task** that names the exact files, the exact literal END_FILE sentinel lines, the exact validation command, the exact commit message, and the exact stop conditions. The task is a Lane C `codex_watchdog` "dispatch bridge fix" per REQ_0018 § "Approved parallel lanes" and a "validation failure" recovery per REQ_0014 § "Human attention recovery loop". It is a non-functional, byte-level, single-line surgical strip on three text files (one JSON, two markdown) and a single commit; it does not touch any V2 source, any V2 test, any prior-milestone GO/NO-GO marker file, any prior committed Codex parallel-review report, the master planner prompt body, or any supervisor status JSON.

## On-disk gate evidence read at planner turn open (unchanged from prior turn)
- `claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json` — `active_requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`, `active_lane: paper_backtest_mvp`, `human_attention_required: false`, `last_commit: 927fc65 Codex watchdog recover dirty non-live automation artifacts`, `final_live_gate_status: blocked_human_only`, `current_mvp_milestone: REPLAY_BACKTEST_RUNNER_MVP`, `distance_to_v2_backtest_and_paper_mvp_ready.remaining_count: 3`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — `V2_BACKTEST_AND_PAPER_MVP_READY` (PASS).
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` (PASS).
- `claude_worklog/final_readiness/04_GO_NO_GO.md` — `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (human-only; not flipped by this turn or by the new watchdog task).
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED` (REQ_0013 prerequisite 1 of 3 closed).
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` (REQ_0013 prerequisite 2 of 3 closed).
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` — `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`.

## Authored task definition summary
`claude_worklog/agent_supervisor/tasks/codex_watchdog_clean_task_197_end_file_leakage_and_dispatch.json`:
- `task_id`: `codex_watchdog_clean_task_197_end_file_leakage_and_dispatch`
- `agent`: `codex`
- `risk_level`: `L1`
- `lane`: `codex_watchdog`
- `secondary_lane`: `legacy_parity`
- `requires_clean_worktree`: `false` (the task itself operates on the dirty tree to clean it)
- `worktree_excluded_paths`: `[claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt]`
- `allowed_output_prefixes`: `[claude_worklog/agent_supervisor/tasks/, claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/, claude_worklog/codex_parallel_reviews/]`
- `next_gate`: `TASK_197_DISPATCHABLE_AND_DISPATCHED`

The task prompt enumerates ten explicit steps: (1) confirm no active child, (2) surgical strip on task 197 JSON plus json.load() smoke validation, (3) optional surgical strip on the two prior planner-turn notes plus on this task definition file and this turn's planner-turn note if the same defect leaks at materialization, (4) high-confidence secret scan, (5) stage and commit with message `Codex watchdog clean task 197 END_FILE leakage and stage Phase 2Z open notes`, (6) do not dispatch task 197 directly (supervisor is the dispatcher), (7) do not pre-author task 198, (8) do not pre-author any Phase 2Z `required_output_files` path, (9) do not flip the final live-readiness gate, (10) stop conditions enumerated.

## Lane / MVP relevance / next gate (REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0018 / REQ_0020 / REQ_0021 / REQ_0025)
- `lane`: `codex_watchdog` (this turn authors a Lane C dispatch-bridge-fix task that resolves the no-progress halt loop and clears the JSON parser-breaking END_FILE leakage on task 197).
- `secondary_lane`: `legacy_parity` (the unblocked Phase 2Z is the third REQ_0013 prerequisite and preserves the deterministic per-source freshness gate the legacy bot lacked).
- `mvp_relevance`: lives strictly downstream of `V2_BACKTEST_AND_PAPER_MVP_READY` (committed PASS at `06_GO_NO_GO.md` and Codex PASS at `10_GO_NO_GO_CODEX.md`). Resolves the dispatch hold preventing the third REQ_0013 SMC/liquidity feature shadow-mode prerequisite from advancing.
- `next_gate`: `TASK_197_DISPATCHABLE_AND_DISPATCHED` for the watchdog cleanup task itself. Downstream still: `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md` via the dispatched task 197.
- `predecessor_required_marker`: `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` (PASS on disk at HEAD `927fc65`).
- `blocked_by`: nothing on disk; the watchdog cleanup task itself is the unblocker.
- `legacy_evidence_consulted`: REQ_0007, REQ_0010, REQ_0011, REQ_0014, REQ_0015 (both variants), REQ_0016, REQ_0021, REQ_0025; the on-disk task 197 JSON; the two prior Phase 2Z planner-turn notes; the supervisor status JSON triple.
- `legacy_failure_addressed`: closes the recurring harness END_FILE materialization defect class (previously observed on task 196, now recurring on task 197) by directing the watchdog to perform the surgical strip and commit so the supervisor's pre-dispatch JSON validation accepts task 197 and the dispatch cycle resumes.

## This turn's authored output
This planner turn authors **two** files:

1. The Codex watchdog recovery task definition `claude_worklog/agent_supervisor/tasks/codex_watchdog_clean_task_197_end_file_leakage_and_dispatch.json` instructing the local Codex watchdog to perform the ten-step surgical cleanup, secret scan, commit, and push.

2. This planner-turn narrative note `PLANNER_TURN_2Z_THIRD_REINVOKE_AUTHORED_CODEX_WATCHDOG_CLEAN_TASK_197.md` recording the third re-invocation snapshot at HEAD `927fc65`, the no-progress halt loop classification, the Codex watchdog authority citations, and the explicit no-task-197-re-emission and no-task-198-pre-authoring decisions for this turn.

This turn does **not**:
- re-emit task 197. Task 197 is already on disk; re-emission risks reproducing the same END_FILE materialization leak. The watchdog task above performs the surgical strip directly.
- modify task 197 byte content directly from the planner. The Codex watchdog task is the authorized actor.
- author task 198 (Codex review of Phase 2Z implementation). Task 198 is the next planner turn's authoring after `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` lands.
- author or modify any V2 source under `v2/` or any V2 test under `v2/backend/tests/`.
- author or modify any Phase 2Z documentation file under `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/`. Those eight docs are authored by task 197.
- author or modify any prior-milestone documentation file under `claude_worklog/phase2_core_rebuild/` outside this single new note.
- modify the master planner prompt body. The planner-prompt rotation is operator-managed.
- modify any other task definition under `claude_worklog/agent_supervisor/tasks/` beyond authoring this single new watchdog task.
- modify any supervisor status JSON under `claude_worklog/agent_supervisor/status/`.
- modify any committed Codex parallel-review report or GO/NO-GO file under `claude_worklog/codex_parallel_reviews/`.
- introduce any new lineage ID, value-object surface, FastAPI surface, adapter, ledger persistence, replay engine, scheduler, paper trader process, paper executor, shadow executor, live trader process, strategy library, or background loop.
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- dispatch any Binance read-only account-history endpoint or any other live exchange API.
- flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- open SMC/liquidity feature shadow-mode work (REQ_0013 prerequisite 3 of 3 is in-flight via task 197; SMC opens only on Phase 2Z Codex PASS).
- override any prior planner turn's narrative or task-authoring decisions other than upgrading the prior surgical-fix-deferred decision to an explicit named-task dispatch.

## Recommended next planner action
After the supervisor dispatches the new Codex watchdog cleanup task and Codex completes the ten-step cycle, the supervisor's next dispatch cycle picks up task 197. After Claude Code task 197 emits `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md`:

- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED`: the next planner turn authors task 198 to dispatch the Codex review of the Phase 2Z implementation under the `codex_watchdog` lane. On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_PASS` at the resulting `09_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_GO_NO_GO.md`, the three REQ_0013 prerequisites are all PASS and the planner may then open SMC/liquidity feature shadow-mode work in shadow-only mode under REQ_0013 § "Initial implementation mode".
- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED`: the next planner turn inspects `06_IMPLEMENTATION_REPORT.md` for the precise per-row blocker list and authors a targeted Codex autofix recovery task constrained to the same `allowed_output_prefixes` per REQ_0007 / REQ_0014.
- If the watchdog cleanup task itself stops mid-cycle for a non-trivial reason (e.g. the harness defect class has changed and the surgical strip is no longer safe, or an active child is observed mid-cycle, or a secret scan fails), the watchdog leaves a one-paragraph diagnosis under `claude_worklog/codex_parallel_reviews/` and the next planner turn classifies it under REQ_0014 § "Human attention recovery loop" and authors a narrower targeted recovery task.

## Hard safety
- No live trading.
- No legacy mutation under `/home/wali/Desktop/AI BOT`.
- No Redis read or write or delete.
- No live service restart.
- No exchange order, leverage, or margin change.
- No deployment, no production migration.
- No secret exposure or commit.
- Final live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains human-only and is not flipped by this turn or by the new watchdog cleanup task.
- No SMC/liquidity feature shadow-mode work opened (REQ_0013 prerequisite 3 of 3 is in-flight via task 197; SMC opens only on Phase 2Z Codex PASS).
- No interference with the prior committed Codex parallel-review batch artifacts at HEAD `7c94d6e` ancestry or any prior committed Codex parallel-review output.
- No re-emission of task 197 (the watchdog has surgical authority over the END_FILE marker leakage; re-emission risks reproducing the leak and racing the watchdog).
- No speculative authoring of task 198 (Codex review) ahead of the 2Z PASS marker.
- No pre-authoring of any Phase 2Z `required_output_files` path; task 197 is the sole authoring actor for the V2 source layer, the V2 test layer, and the Phase 2Z documentation layer.
- No modification of the master planner prompt body; the planner-prompt rotation observed in the dirty tree is operator-managed.
- No modification of any supervisor status JSON; the supervisor manages its own status updates.
- No modification of any other task definition under `claude_worklog/agent_supervisor/tasks/` beyond authoring this single new watchdog cleanup task.

PLANNER_TURN_2Z_THIRD_REINVOKE_AUTHORED_CODEX_WATCHDOG_CLEAN_TASK_197_READY
