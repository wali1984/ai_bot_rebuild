# Planner Turn 2Z - Re-Invoked at HEAD `927fc65`, Task 197 Awaiting Watchdog Cleanup and Dispatch

## Date
2026-05-10

## HEAD at planner turn open
`927fc65 Codex watchdog recover dirty non-live automation artifacts`

## Recent commit chain visible in `git log --oneline -8`
```
927fc65 Codex watchdog recover dirty non-live automation artifacts
c50805e Codex watchdog recover dirty non-live automation artifacts
1769f8a Codex watchdog recover dirty non-live automation artifacts
7c94d6e Add Codex parallel review batch results
ba2c70e Create Codex parallel review batch
9df524a Export Redis liquidations stream with verified manifest
c653745 Add Codex parallel review batch results
22fbb14 Create Codex parallel review batch
```

No new commit has landed since the prior planner turn at HEAD `927fc65`. This planner invocation is a re-invocation at the same HEAD that the prior planner turn `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` opened on. The Codex watchdog's three consecutive recovery cycles at `1769f8a` / `c50805e` / `927fc65` closed out the Phase 2Y.B END_FILE leakage and the prior dirty-tree backlog described across the four `PLANNER_TURN_2Y_REINVOKED_*` notes.

## Worktree state at planner turn open
`git status --porcelain` returns:
```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json
?? claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md
```

Classified dirty paths:
- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` is the operator-managed planner-prompt rotation. Already excluded from task 197 by `worktree_excluded_paths`.
- `claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` is the prior planner turn's authored Phase 2Z domain implementation task definition. Untracked.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` is the prior planner-turn narrative note that opened Phase 2Z. Already excluded from task 197 by `worktree_excluded_paths`. Untracked.

No other path is dirty. No active Claude/Codex/Ollama child is running per `claude_worklog/agent_supervisor/status/queue_status.json` (`current_running_task: null`, `pending: 14`, `running: 0`, `human_attention_required_count: 0`) and `claude_worklog/agent_supervisor/status/current_status.json` (`task_id: null`, `status: pending`, `summary: dry-run queue check completed`). The Codex parallel-review batch at HEAD `7c94d6e` is fully drained and committed; no `claude_worklog/codex_parallel_reviews/` artifact is dirty.

## On-disk gate evidence read at planner turn open
- `claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json` -> `active_requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`, `active_milestone: master_planner_requirement_intake`, `active_task: null`, `active_lane: paper_backtest_mvp`, `planner_lane_lock_enabled: false`, `human_attention_required: false`, `next_action: run Claude planner for active requirement`, `last_commit: 927fc65 Codex watchdog recover dirty non-live automation artifacts`, `final_live_gate_status: blocked_human_only`, `current_mvp_milestone: REPLAY_BACKTEST_RUNNER_MVP`, `distance_to_v2_backtest_and_paper_mvp_ready.remaining_count: 3`, `codex_recovery_active: false`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` -> `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` -> `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `claude_worklog/final_readiness/04_GO_NO_GO.md` -> `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (human-only; not flipped by this turn).
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` -> `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED` (REQ_0013 prerequisite 1 of 3 closed).
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` -> `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` (REQ_0013 prerequisite 2 of 3 closed).
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` -> `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md` -> `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` -> `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/` does not yet exist on disk. The `v2/backend/app/{domain,services,composition}/degraded_state_fail_closed_gates/` source directories and the `v2/backend/tests/unit/{domain,services,composition}/degraded_state_fail_closed_gates/` test directories do not yet exist on disk. Phase 2Z implementation has not yet started.

## Task 197 authoring evidence
`claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` was authored by the prior planner turn (`PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md`). Re-invocation reads it on disk:
- `task_id`: `197_phase2z_degraded_state_fail_closed_gates_domain_implementation`
- `agent`: `claude`
- `risk_level`: `L1`
- `status`: `pending`
- `lane`: `legacy_parity`
- `secondary_lane`: `paper_backtest_mvp`
- `next_gate`: `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED`
- `predecessor_required_marker`: `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` (PASS on disk at HEAD `927fc65`).
- `requires_clean_worktree`: `true`
- `worktree_excluded_paths`: includes `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`, `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md`, and seven prior `parallel_capacity_readonly_review_*` task files.
- `allowed_output_prefixes`: the three new V2 source directories (`v2/backend/app/{domain,services,composition}/degraded_state_fail_closed_gates/`), the three new V2 test directories (`v2/backend/tests/unit/{domain,services,composition}/degraded_state_fail_closed_gates/`), and the new docs directory `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/`.
- `required_output_files`: 41 paths covering the V2 source layer, the V2 test layer, and the eight Phase 2Z documentation files (00 scope, 01 legacy evidence review, 02 spec, 03 test plan, 04 safety boundaries, 05 GO/NO-GO request, 06 implementation report, 07 GO/NO-GO).

## REQ_0010 / REQ_0014 / REQ_0015 / REQ_0016 classification of task 197 JSON marker leakage
Reading the last bytes of `claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` via `tail -3 ... | cat -A`:
```
...prompt: "..." text ending with the literal closing $
}$
```

The closing JSON `}` is followed by a stray `END_FILE: claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` line that the materialization harness should have stripped. This is exactly the failure class enumerated by:
- REQ_0010 § "Required safety rules" -> the materialization-pipeline reliability boundary.
- REQ_0014 § "Human attention recovery loop" classification: `validation failure` (END_FILE marker leakage in materialized output) and `path mismatch` (the harness wrote the sentinel into file content rather than treating it as a sentinel).
- REQ_0015 § "Codex watchdog lane" -> trigger `materialization path mismatch occurs`. The leaked END_FILE line is a materialization defect, not a semantic JSON content defect.
- REQ_0016 § "Operating loop" step 7: "Remove standalone END_FILE leakage."

A markdown stray END_FILE line is harmless because markdown tolerates trailing literal text — the prior planner-turn note `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` carries the same harness leak on its last line and that does not block dispatch. A JSON stray END_FILE line is harmful because it breaks JSON parser validity (`python3 -c "import json; json.load(open(<path>))"` raises `json.JSONDecodeError: Extra data`). The supervisor's pre-dispatch JSON validation will refuse to enqueue task 197 until the trailing line is stripped.

This is a surgical, non-functional fix that the Codex watchdog has explicit REQ_0010 / REQ_0014 / REQ_0015 / REQ_0016 authority to perform. The fix:
- Read `claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json`.
- If the last non-empty line matches `^END_FILE: claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation\.json$` (literal sentinel), delete that single line.
- Re-validate with `python3 -c "import json; json.load(open('claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json')); print('ok')"` -> stdout `ok`.
- The same surgical fix may optionally be applied to the prior planner-turn note `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` for byte-cleanliness, though it does not block dispatch because the note is a markdown file.

## Failure classification per REQ_0014 § "Human attention recovery loop"
- Class: `validation failure` (END_FILE marker leakage in materialized JSON output) plus `dispatch hold` (worktree dirty with two untracked artifacts that are not yet in the supervisor's `worktree_excluded_paths` set for any other task and would block `requires_clean_worktree: true` evaluation for task 197 itself unless the excluded-paths set covers them).
- Not a path mismatch in the safe-remap sense, not a stale runtime state in the dispatch sense, not a quota/auth issue, and not a safety issue.
- Root cause: the prior planner turn's BEGIN_FILE / END_FILE materialization wrote the closing sentinel into JSON file content rather than stripping it. This is a recurring harness behavior already covered by REQ_0010 and REQ_0016 § step 7 ("Remove standalone END_FILE leakage") and observed previously in task 196.
- Resolution: the Codex watchdog (1) confirms no active Claude/Codex child, (2) strips the stray trailing line from `197_…json`, (3) commits the cleaned task 197 plus the planner-turn 2Z open note plus this re-invoked note in one commit, then (4) dispatches task 197.

## This turn's authored output
This planner turn authors **one** file:

1. This planner-turn narrative note `PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md` recording the re-invocation snapshot at HEAD `927fc65`, the no-active-child idle state, the task 197 authoring evidence on disk, the REQ_0010 / REQ_0014 / REQ_0015 / REQ_0016 classification of the JSON END_FILE marker leakage, and the explicit no-new-task-authoring decision for this turn.

This turn does **not**:
- re-emit task 197. Task 197 is already on disk. Re-emission risks re-introducing the same END_FILE materialization leak that the watchdog is authorized to strip surgically. Re-emission would also race the Codex watchdog's pending cleanup-and-commit cycle.
- modify task 197 byte content directly. The Codex watchdog has explicit REQ_0010 / REQ_0014 / REQ_0015 / REQ_0016 authority for this surgical fix.
- author task 198 (Codex review of Phase 2Z implementation). Task 198 is authored by the next planner turn after `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` lands at `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md`. Speculative authoring of task 198 ahead of the 2Z PASS marker would re-introduce the kind of out-of-sequence authoring that the prior 2Y reconciliation cycle taught the planner to avoid.
- author or modify any V2 source under `v2/` or any V2 test under `v2/backend/tests/`. The Phase 2Z V2 source and test layer is authored by task 197 when the supervisor dispatches it under the trainer venv. The planner does not pre-author any of the 41 `required_output_files` paths, and Claude Code task 197 is the sole authoring actor.
- author or modify any Phase 2Z documentation file under `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/`. Those eight docs are authored by task 197.
- author or modify any Phase 2Y documentation file under `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`.
- author or modify any Phase 2X documentation file under `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/`.
- modify any prior-milestone artifact byte content under `claude_worklog/phase2_core_rebuild/` outside this single new note.
- modify the master planner prompt body. The planner-prompt rotation is operator-managed; the rotation observed in the dirty tree was already prepared for the 2Z lane and is excluded from task 197.
- modify any other task definition under `claude_worklog/agent_supervisor/tasks/`.
- modify any supervisor status JSON under `claude_worklog/agent_supervisor/status/`.
- modify any committed Codex parallel-review report or GO/NO-GO file under `claude_worklog/codex_parallel_reviews/`.
- introduce any new lineage ID, value-object surface, FastAPI surface, adapter, ledger persistence, replay engine, scheduler, paper trader process, paper executor, shadow executor, live trader process, strategy library, or background loop.
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- dispatch any Binance read-only account-history endpoint or any other live exchange API.
- flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- open SMC/liquidity feature shadow-mode work (REQ_0013 prerequisite 3 of 3 is in-flight via task 197; SMC opens only on Phase 2Z Codex PASS).
- modify the cockpit / frontend byte content.
- override any prior planner turn's narrative or task-authoring decisions.

## Lane / MVP relevance / next gate (REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0018 / REQ_0020 / REQ_0021 / REQ_0025)
- `lane`: `codex_watchdog` (this turn produces only a planner-turn narrative note that informs the watchdog's next-cycle classification and dispatch decision for the already-authored task 197).
- `secondary_lane`: `legacy_parity` (the planner-turn note confirms the Phase 2Z typed-contract surface preservation posture mirrors the REQ_0019 / REQ_0023 read-only legacy audit posture and the Phase 2W deferral order placing 2Z third behind 2X and 2Y).
- `mvp_relevance`: lives strictly downstream of `V2_BACKTEST_AND_PAPER_MVP_READY` (committed PASS at `06_GO_NO_GO.md` and Codex PASS at `10_GO_NO_GO_CODEX.md`). Records the readiness state of task 197 (the third of three REQ_0013 SMC/liquidity feature shadow-mode prerequisites: Phase 2X Codex-fail-reconciled at HEAD `927fc65` ancestry, Phase 2Y typed-contract surface Codex-fail-reconciled at HEAD `927fc65` ancestry, Phase 2Z typed-contract surface authored as task 197 awaiting watchdog cleanup and dispatch).
- `next_gate`: still `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md` via the already-authored task 197.
- `predecessor_required_marker`: `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` (PASS on disk at HEAD `927fc65`).
- `blocked_by`: the Codex watchdog's REQ_0010 / REQ_0014 / REQ_0015 / REQ_0016 cleanup-and-commit cycle stripping the stray trailing line from task 197 JSON and committing the cleaned task 197 plus the prior planner-turn 2Z open note plus this re-invoked note.

## Recommended Codex watchdog cleanup-and-dispatch sequence
1. Confirm no active Claude/Codex/Ollama child via `claude_worklog/agent_supervisor/status/current_status.json` (`task_id: null`, `status: pending`) and `claude_worklog/agent_supervisor/status/queue_status.json` (`current_running_task: null`, `running: 0`, `human_attention_required_count: 0`).
2. Strip the stray trailing line `END_FILE: claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` from `claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json`. Validate with `python3 -c "import json; json.load(open('claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json')); print('ok')"` -> stdout `ok`. Optionally apply the same surgical strip to the prior planner-turn note `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` last line for byte-cleanliness, and to this re-invoked note's last line if the same harness leakage recurs at materialization.
3. Stage and commit the cleaned `197_…json`, the prior planner-turn note `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md`, and this re-invoked planner-turn note `PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md` in one commit. Do **not** stage the modified `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`; that path is operator-managed and remains in task 197's `worktree_excluded_paths`. Suggested commit message: `Codex watchdog clean task 197 END_FILE leakage and stage Phase 2Z open notes`.
4. Optionally update task 197's `worktree_excluded_paths` to also list this new planner-turn note `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH.md`. This is a defensive measure; once the note is committed in step 3 it is no longer in the dirty-tree set, so the update is not strictly required for dispatch.
5. Dispatch task 197. The supervisor's `requires_clean_worktree: true` evaluation excludes the planner-prompt path and the prior planner-turn 2Z open note path; after step 3 the worktree is clean for all other paths.
6. Local Claude Code executes task 197 Steps 1 through 14 per the on-disk prompt: reads the legacy and planning evidence, authors the eight Phase 2Z documentation files, authors the V2 source layer (3 modules per layer × 3 layers = 9 plus the 3 `__init__.py` and 3 `errors.py` for 12 source files plus the existing `degraded_source_state.py` and `degraded_state_record.py` and `service.py` and `runtime.py` for the 11 declared in `required_output_files`), authors the unit tests across the three layers, runs pytest under the trainer venv, runs the smoke import, runs the no-redis-import grep, runs the no-fastapi-import grep, runs the diff-stat exclude-pathspec audit, authors `06_IMPLEMENTATION_REPORT.md`, and emits the single-line `07_GO_NO_GO.md` marker `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` on success or `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED` on any rubric failure.
7. The next planner turn opens task 198 to dispatch the Codex review of the Phase 2Z implementation under the `codex_watchdog` lane on `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED`, or authors a targeted Codex autofix recovery task constrained to the same `allowed_output_prefixes` per REQ_0007 / REQ_0014 on `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED`.

## Recommended next planner action
After the Codex watchdog completes the cleanup-and-dispatch sequence above and Claude Code task 197 emits `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md`:
- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED`: the next planner turn authors task 198 to dispatch the Codex review of the Phase 2Z implementation under the `codex_watchdog` lane. On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_PASS` at the resulting `09_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_GO_NO_GO.md`, the three REQ_0013 prerequisites are all PASS (Phase 2X Codex-fail-reconciled, Phase 2Y typed-contract surface Codex-fail-reconciled, Phase 2Z degraded-state fail-closed gates Codex PASS) and the planner may then open SMC/liquidity feature shadow-mode work in shadow-only mode under REQ_0013 § "Initial implementation mode" (`smc_shadow_enabled = true`, `smc_affects_execution = false`).
- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED`: the next planner turn inspects `06_IMPLEMENTATION_REPORT.md` for the precise per-row blocker list and authors a targeted Codex autofix recovery task constrained to the same `allowed_output_prefixes` per REQ_0007 / REQ_0014.
- On a planner-level `human_attention_required` event during cleanup or dispatch (e.g. a new harness defect not classifiable as the standard END_FILE leakage): the Codex watchdog applies REQ_0014 § "Human attention recovery loop" classification, fixes the blocker if non-live and safe, validates, secret-scans, commits, re-reviews, and resumes; the planner re-invokes only after the watchdog records a clean dispatch.

## Hard safety
- No live trading.
- No legacy mutation under `/home/wali/Desktop/AI BOT`.
- No Redis read or write or delete.
- No live service restart.
- No exchange order, leverage, or margin change.
- No deployment, no production migration.
- No secret exposure or commit.
- Final live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains human-only.
- No SMC/liquidity feature shadow-mode work opened (REQ_0013 prerequisite 3 of 3 is in-flight via task 197; SMC opens only on Phase 2Z Codex PASS).
- No interference with the prior committed Codex parallel-review batch artifacts at HEAD `7c94d6e` ancestry or any prior committed Codex parallel-review output.
- No re-emission of task 197 (the watchdog has surgical authority over the END_FILE marker leakage; re-emission risks reproducing the leak and racing the watchdog).
- No speculative authoring of task 198 (Codex review) ahead of the 2Z PASS marker.
- No pre-authoring of any Phase 2Z `required_output_files` path; task 197 is the sole authoring actor for the V2 source layer, the V2 test layer, and the Phase 2Z documentation layer.

PLANNER_TURN_2Z_REINVOKED_TASK_197_AWAITING_WATCHDOG_CLEANUP_AND_DISPATCH_READY
