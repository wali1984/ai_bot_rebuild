# PLANNER TURN — 2J.B END_FILE Marker Leakage Recovery (Lane C codex_watchdog)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0014/0015/0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), and REQ_0011/0021 (parallel Codex review and capacity scheduler).

## Active milestone

REQ_0017 milestone 6 `PAPER_MODE_MVP`, sub-phase 2J.B `PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE`. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` remains 2 milestones (PAPER_MODE_MVP → SHADOW_MODE_READINESS → V2_BACKTEST_AND_PAPER_MVP_READY).

## Trigger

Six 2J.B planner-emission files plus supervisor task 152 and 153 contain trailing END_FILE marker leakage from the prior planner emission turn:

1. `claude_worklog/phase2_core_rebuild/paper_mode_impl/10_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SPEC.md` — final body line is `END_FILE: claude_worklog/phase2_core_rebuild/paper_mode_impl/10_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SPEC.md`.
2. `claude_worklog/phase2_core_rebuild/paper_mode_impl/11_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md` — final body line is `END_FILE: …/11_PHASE_2J_B_…TEST_PLAN.md`.
3. `claude_worklog/phase2_core_rebuild/paper_mode_impl/12_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` — final body line is `END_FILE: …/12_PHASE_2J_B_…SAFETY_BOUNDARIES.md`.
4. `claude_worklog/phase2_core_rebuild/paper_mode_impl/13_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md` — final body line is `END_FILE: …/13_PHASE_2J_B_…GO_NO_GO_REQUEST.md`.
5. `claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_B_OPEN_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE.md` — final body line is `END_FILE: …/PLANNER_TURN_2J_B_OPEN_…`.
6. `claude_worklog/agent_supervisor/tasks/152_paper_mode_2jb_runtime_flag_assembler_service_implementation.json` — final byte sequence is `}\nEND_FILE: …/152_paper_mode_2jb_…implementation.json` immediately after the JSON closing brace, parsing only because the leakage is past the brace but failing the supervisor's "no standalone framing-marker line" invariant.
7. `claude_worklog/agent_supervisor/tasks/153_paper_mode_2jb_runtime_flag_assembler_service_codex_review.json` — same `}\nEND_FILE: …/153_…codex_review.json` leakage as 152, **plus** an additional planner-closure paragraph past the END_FILE line. Because the post-brace bytes are not whitespace-only, this file fails `json.load` strict-tail checks if the supervisor or any downstream loader reads past the JSON object end (e.g. via repeated `json.load` on a stream, or via a strict tail-equals-whitespace check).

## Classification

- Lane: `codex_watchdog`
- Recovery type: planner emit-leakage cleanup (REQ_0014 planner-level human-attention autorecovery + REQ_0016 Codex non-live human-replacement watchdog)
- Risk level: L1 (surgical trailing-bytes strip on supervisor task definitions and planner-emission docs; no v2/ source touched)
- Predecessor evidence intact:
  - `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` byte-equals `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`
  - `claude_worklog/phase2_core_rebuild/paper_mode_impl/07_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO.md` byte-equals `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` reconciled `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` per 26-addendum

## Pre-recovery state

`git status --porcelain` shows exactly thirteen entries inside AI BOT REBUILD:

- ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (planner-prompt drift, intentionally NOT committed by this recovery)
- `?? claude_worklog/agent_supervisor/tasks/152_paper_mode_2jb_runtime_flag_assembler_service_implementation.json` (END_FILE leakage)
- `?? claude_worklog/agent_supervisor/tasks/153_paper_mode_2jb_runtime_flag_assembler_service_codex_review.json` (END_FILE + post-JSON paragraph leakage)
- `?? claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2j_a_paper_mode_runtime_flag_domain_codex_pass.json` (clean; bundled in this commit)
- `?? claude_worklog/agent_supervisor/tasks/codex_recover_2j_b_planner_emission_end_file_marker_leakage_cleanup.json` (this recovery task definition; bundled in this commit)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/10_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SPEC.md` (END_FILE leakage)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/11_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md` (END_FILE leakage)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/12_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` (END_FILE leakage)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/13_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md` (END_FILE leakage)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_B_OPEN_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE.md` (END_FILE leakage)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_B_END_FILE_MARKER_LEAKAGE_RECOVERY.md` (this planner-turn doc; bundled in this commit)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/parallel_capacity_readonly_review_phase2j_a_paper_mode_runtime_flag_domain_codex_pass_GO_NO_GO.md` (clean one-liner CODEX_PARALLEL_READONLY_REVIEW_READY; bundled)
- `?? claude_worklog/phase2_core_rebuild/paper_mode_impl/parallel_capacity_readonly_review_phase2j_a_paper_mode_runtime_flag_domain_codex_pass_REPORT.md` (clean; bundled)

Tasks 152 and 153 both set `requires_clean_worktree: true` and list `worktree_excluded_paths` containing exactly two entries:
- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
- `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2j_a_paper_mode_runtime_flag_domain_codex_pass.json`

This means after this recovery commits, the only residual dirty entry must be the planner-prompt drift (covered by exclusion); the parallel-capacity readonly-review JSON also gets covered either way because we commit it. The eight other dirty entries that this turn closes are NOT in worktree_excluded_paths, so without this recovery the supervisor cannot dispatch 152 and the dispatch chain stalls at REQ_0017 milestone 6 sub-step 2/3.

## Recovery action

Lane C codex_watchdog dispatches `codex_recover_2j_b_planner_emission_end_file_marker_leakage_cleanup`:

1. Snapshot the thirteen-entry dirty set; abort on any deviation.
2. Verify three predecessor PASS markers (09, 07, 25-with-26-addendum); abort on missing.
3. Strip pass A — for the six `strip_targets_trailing_end_file_line` files, surgically remove the trailing `\nEND_FILE: <repo-relative-path>\n?\Z` regex match exactly once per file. Preserve terminal-newline policy.
4. Strip pass B — for `153_…codex_review.json`, scan top-level `{}` balance (string-aware) to locate the byte position immediately past the closing brace, verify post-brace content matches the expected `\n?END_FILE: …/153_….json\n+<one or more paragraphs of prose>\n?` shape, truncate to the closing-brace boundary, and re-validate `json.load` strict.
5. Validate per file: diff shows exactly one removed hunk, `json.load` succeeds for 152 and 153, no remaining standalone `END_FILE: …` or `BEGIN_FILE: …` framing marker line.
6. Cross-file invariants: planner-prompt body unchanged; recovery-task body unchanged; this planner-turn doc body unchanged; parallel-capacity 2J.A readonly-review trio bodies unchanged; v2/ tree clean; legacy `/home/wali/Desktop/AI BOT` untouched.
7. Secret scan over the twelve to-be-committed dirty entries plus the two report outputs; high-confidence rules only (AWS / OpenAI / Anthropic / GitHub PAT / Slack webhook / JWT / RSA key block / Binance api_key+api_secret pair / KuCoin api_key+api_secret pair).
8. Commit `Codex watchdog recover 2J.B planner emission END_FILE marker leakage` with twelve `git add` paths plus the two report outputs; explicitly **exclude** the planner-prompt drift from `git add`. Push without `--force`. Verify post-commit `git status --porcelain` is exactly one line for the planner-prompt drift.
9. Emit two BEGIN_FILE blocks for the report and GO/NO-GO; GO/NO-GO is exactly one line: `CODEX_NON_LIVE_RECOVERY_READY` or `CODEX_NON_LIVE_RECOVERY_BLOCKED`.

## Safety review

- No `/home/wali/Desktop/AI BOT` mutation
- No Redis read/write/delete or Redis command
- No live service restart
- No exchange order action
- No leverage/margin change
- No live trading enablement
- No deployment / production migration
- No secret exposure or commit
- No prior-milestone artifact byte change (2J.A files 00–09 untouched; 2I.C files 25/26 untouched; all earlier 2E/2F/2G/2H/2I.A/2I.B artifacts untouched)
- No 2J.B planning artifact body change other than the surgical trailing-bytes strip rules
- No v2/ source or test modification
- No new task definition outside the recovery task, the existing 152/153 set, and the parallel-capacity readonly-review JSON

## Lane lock fields

- lane: `codex_watchdog`
- mvp_relevance: unblocks Lane A `paper_backtest_mvp` dispatch of 152 and downstream 153 by restoring a clean worktree (modulo the planner-prompt drift covered by 152/153 worktree_excluded_paths) so that REQ_0017 milestone 6 `PAPER_MODE_MVP` advances from sub-step 1/3 (2J.A closed) to sub-step 2/3 (2J.B in flight)
- blocked_by: none (recovery is unblocked at recovery-task creation; predecessor markers 09 / 07 / 25-with-26-addendum are intact)
- next_gate: `PHASE2J_B_PLANNER_EMISSION_END_FILE_MARKER_LEAKAGE_RECOVERY_PASS` materialized as `CODEX_NON_LIVE_RECOVERY_READY` in `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_2j_b_planner_emission_end_file_marker_leakage_cleanup_GO_NO_GO.md`
- legacy_evidence_consulted: precedent 2E3.C and 2H.B END_FILE leakage recovery patterns (committed); 152/153 requires_clean_worktree contracts; predecessor PASS markers 09 / 07 / 25-with-26-addendum
- legacy_failure_addressed: planner emission writing the END_FILE: <path> closing-marker as file body (six files) plus an additional post-JSON-object planner-closure paragraph (153.json), which together prevent supervisor dispatch under the current 152/153 worktree_excluded_paths surface

## Post-recovery dispatch sequence

After the recovery commit lands cleanly:

1. Supervisor sees `git status --porcelain` reports exactly one residual line (the planner-prompt drift, covered by 152.worktree_excluded_paths and 153.worktree_excluded_paths). The clean-worktree precondition for 152 is satisfied.
2. Supervisor dispatches `152_paper_mode_2jb_runtime_flag_assembler_service_implementation` (Lane A `paper_backtest_mvp`). Predecessor marker `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` (file 09) and `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` (file 25 + 26-addendum) are intact and consumed by 152.
3. On `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` materialized at `claude_worklog/phase2_core_rebuild/paper_mode_impl/15_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md`, supervisor dispatches `153_paper_mode_2jb_runtime_flag_assembler_service_codex_review`.
4. On `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`, planner authors the 2J.C composition-root planning bundle (sub-step 3/3 of REQ_0017 milestone 6) and emits the two follow-on supervisor tasks (consolidated implementation + Codex review) under the existing consolidated_default granularity policy.
5. On `PHASE2J_C_PAPER_MODE_COMPOSITION_ROOT_CODEX_PASS`, REQ_0017 milestone 6 `PAPER_MODE_MVP` closes. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` becomes 1 milestone (`SHADOW_MODE_READINESS`).

## MVP relevance and parallel-capacity status

- Lane A (paper_backtest_mvp): unblocks 152 dispatch.
- Lane C (codex_watchdog): this recovery itself; also bundles the parallel-capacity 2J.A readonly-review JSON+REPORT+GO_NO_GO into the durable commit so the parallel-review evidence becomes referenceable from future Codex review tasks.
- Lane B (explainability_ui): not advanced this turn; explicitly deferred per REQ_0018 lane-lock until backed by paper-mode runtime-flag assembler-service contracts that 2J.B emits.
- Lane D (legacy_parity): not advanced this turn; the hedge-unwind/squeeze risk evidence (REQ_0022) is consumed in the 2J.B SPEC's mvp_relevance prose but no new legacy-parity task is opened.

Codex parallel-capacity utilization remains aligned with REQ_0021: while Claude planner authored the 2J.B planning bundle and 152/153 in the prior turn, Codex Pro produced the parallel-capacity 2J.A readonly review (CODEX_PARALLEL_READONLY_REVIEW_READY) without touching the dirty Claude output. This recovery turn is itself a Codex Lane C action that operates on the now-static dirty Claude output.

## Stop conditions honored

- No live action requested
- No legacy mutation
- No Redis access
- No exchange/leverage/margin action
- No deployment
- No secret exposure
- No L4/L5 escalation
- Final live gate remains human-only and BLOCKED

PLANNER_TURN_2J_B_END_FILE_MARKER_LEAKAGE_RECOVERY_READY

Two files emitted as BEGIN_FILE/END_FILE blocks with no trailing in-body END_FILE marker leakage:

1. `claude_worklog/agent_supervisor/tasks/codex_recover_2j_b_planner_emission_end_file_marker_leakage_cleanup.json` — Lane C codex_watchdog recovery task. Strips the trailing `END_FILE: <path>` line from six 2J.B planner-emission files plus task 152.json (Step 3, regex-bounded); separately strips the post-JSON-object planner-closure paragraph from task 153.json (Step 4, brace-balance scan with strict `json.load` re-validation); validates JSON loadability and absence of standalone framing markers; secret-scans high-confidence; commits twelve dirty paths plus two report outputs in one durable non-live commit while explicitly excluding the planner-prompt drift; pushes without `--force`. The recovery's GO/NO-GO file at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_2j_b_planner_emission_end_file_marker_leakage_cleanup_GO_NO_GO.md` materializes `CODEX_NON_LIVE_RECOVERY_READY` on success.

2. `claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_B_END_FILE_MARKER_LEAKAGE_RECOVERY.md` — companion planner-turn doc recording the trigger (seven contaminated files), classification (Lane C, REQ_0014 + REQ_0016, L1), predecessor PASS marker integrity (09 / 07 / 25-with-26-addendum), the thirteen-entry pre-recovery dirty snapshot, the nine-step recovery action, the safety review (no live / no Redis / no legacy / no v2 / no secret), and the post-recovery dispatch chain 152 → 153 → 2J.C-planning-bundle → REQ_0017-milestone-6-close → SHADOW_MODE_READINESS → V2_BACKTEST_AND_PAPER_MVP_READY (1 milestone remaining after PAPER_MODE_MVP closes).

Hard stops honored: no `/home/wali/Desktop/AI BOT` mutation, no Redis access, no live service restart, no exchange order action, no leverage/margin change, no live trading enablement, no deployment, no production migration, no secret exposure. Live gate remains BLOCKED.
