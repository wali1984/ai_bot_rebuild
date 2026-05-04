# Planner Directive — Run-Five HUMAN ATTENTION REQUIRED, Refined Root-Cause Diagnosis (Supervisor Process Death) and Safe Manual Recovery Path for 2E1.C.δ Dispatch (2026-05-03)

This directive is the Master Non-Live Rebuild Planner's run-five turn-stamp.

It is NOT a re-authorization of the 2E1.C.δ dispatch sequence ordered in
`claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`,
re-affirmed in
`07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`,
re-authorized in
`08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`,
re-authorized once more in
`09_PLANNER_RUN_THREE_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`,
and HALTED with a REQ_0014 commit-hook recovery escalation in
`10_PLANNER_RUN_FOUR_HALT_RUN4_ESCALATION_2E1C_DELTA.md`.

It is also NOT a new HALT directive (the Lane A HALT recorded by directive
10 remains in force unchanged). It is also NOT a new task-introduction
directive (per directive 10's restriction "introduces no new V2 source
files, no new task definitions other than the single REQ_0014 Codex
human-attention recovery task `081_codex_run4_supervisor_commit_hook_recovery`,
and no edits to existing task prompts").

This directive is instead a HUMAN ATTENTION REQUIRED directive that:

- refines the root-cause diagnosis recorded in directive 10 from
  "supervisor commit hook failure" to the deeper "supervisor process
  death" (the supervisor heartbeat has been frozen since
  `2026-05-02T03:50:11.972847+00:00`; the recorded supervisor `pid =
  3273960` is no longer live; only the master planner driver
  `claude_master_rebuild_planner.py --daemon --poll-seconds 120` (PID
  `1052548`, started `2026-05-03 20:15`) is alive, and that driver does
  not commit by design);
- records why the recovery task `081_codex_run4_supervisor_commit_hook_recovery`
  emitted alongside directive 10 cannot self-dispatch under current
  runtime state (a catch-22: the supervisor scanner that would dispatch
  `081` is the same process that is dead, and `081` itself is in the
  untracked list);
- records the explicit safe manual recovery path that directive 10 §3
  already authorizes as one of the two acceptable outcomes for the
  recovery task (the "safe manual commit path" alternative), so a human
  operator can choose to execute it without breaching any forbidden
  action;
- self-halts the planner from emitting any further Run-N
  re-authorization, HALT, no-change confirmation, or task-introduction
  directive until either (a) the supervisor process is restarted by the
  operator and the supervisor heartbeat resumes, OR (b) the operator
  executes the safe manual recovery path recorded in §"Safe manual
  recovery path for the human operator" below.

No legacy under `/home/wali/Desktop/AI BOT/` is touched. No Redis write
or delete is performed. No live trading is enabled. No process is
restarted by this directive. No commit is executed by this directive.
No new task definition is created. No edit is made to any of the twelve
untracked artifacts (the eleven recorded in directive 10 plus directive
10 itself), to task `081_codex_run4_supervisor_commit_hook_recovery`, to
any file under `v2/`, to any file under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`, to any
file under `claude_worklog/phase2_core_rebuild/frontend_design/`, to any
file under `claude_worklog/phase2_core_rebuild/decision_explainability/`
other than this directive file itself, to the master planner prompt
under `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`,
or to any supervisor status JSON. The δ composition layer remains
pure-Python, sync, no-async, no-Redis, no-subprocess, no-network,
no-clock, no-legacy by construction; γ (read-only Redis observation
collector) remains deferred.

## Why a HUMAN ATTENTION directive is required this turn

Directive 10 §"Run-4 escalation rule" forbade emitting a Run-4
re-authorization (the HALT directive itself was the Run-4 turn). It did
not prescribe the planner's behavior on a fifth polling turn against a
still-unchanged head, because directive 10 expected the supervisor to
either commit `081` and dispatch it, or itself enter
`human_attention_required` on `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_BLOCKED`.
Neither has happened, because the supervisor process itself is not
running.

Five facts make the Run-5 trigger unambiguous and force a HUMAN
ATTENTION posture rather than a re-authorization, a no-change
confirmation, or another HALT directive:

| # | Trigger fact | Verification |
| - | --- | --- |
| 1 | Fifth planner polling turn after Run-1 (directive 06) | This planner turn IS that fifth turn; `master_rebuild_planner_status.json.generated_at = 2026-05-04T01:28:48.911395+00:00` (a fresh regeneration after the directive-10 turn at `2026-05-04T01:20:01.030599+00:00`) |
| 2 | Head still at `7eefb89` | `git rev-parse --short HEAD = 7eefb89` (unchanged from directive 08 / 09 / 10 attestations) |
| 3 | Same δ artifacts still untracked, plus directive 10 and task `081` now also untracked (twelve untracked Claude-emitted artifacts total) | `git status -s` reports the same eleven `??` entries from directive 10 PLUS `claude_worklog/phase2_core_rebuild/decision_explainability/10_PLANNER_RUN_FOUR_HALT_RUN4_ESCALATION_2E1C_DELTA.md` PLUS `claude_worklog/agent_supervisor/tasks/081_codex_run4_supervisor_commit_hook_recovery.json`; the same `M` entry on `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` remains out of scope |
| 4 | Supervisor process is dead | `supervisor_heartbeat.pid = 3273960`; `ps -p 3273960` returns "no such process"; `supervisor_heartbeat.last_loop_ts = 2026-05-02T03:50:11.972847+00:00`; `supervisor_heartbeat.loop_count = 3`; `agent_health.last_auto_commit_hash = null` (no auto-commit has ever succeeded since this supervisor instance started at `2026-05-02T03:30:15.636728+00:00`) |
| 5 | Only the master planner driver is alive | `ps -ef \| grep claude_master_rebuild_planner` shows `python3 claude_worklog/tools/claude_master_rebuild_planner.py --daemon --poll-seconds 120` running as PID `1052548` since `20:15`; this driver writes status JSON, materializes BEGIN_FILE blocks, and appends events, but `grep -nE "git add\|git commit\|push" claude_worklog/tools/claude_master_rebuild_planner.py` returns one match at line 710 (a comment in the planner prompt template) and zero matches for any code path that actually executes `git add`, `git commit`, or `git push`; the driver does not commit by design |

The twelve untracked Claude-emitted artifacts are now:

- `claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
- `claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`
- `claude_worklog/agent_supervisor/tasks/081_codex_run4_supervisor_commit_hook_recovery.json`
- `claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/09_PLANNER_RUN_THREE_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/10_PLANNER_RUN_FOUR_HALT_RUN4_ESCALATION_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`

This directive file itself will become the thirteenth untracked
Claude-emitted artifact upon materialization, and that is intentional:
it is the only safe action available to the planner this turn, and it
is the documentation artifact that authorizes the operator to choose
between supervisor restart and the safe manual commit path recorded
below.

## Refined root-cause diagnosis (directive 10 update)

Directive 10 §"Run-4 escalation rule" framed the recurring no-progress
as a "supervisor commit-hook" failure (the recovery task `081`'s root
cause classifier lists categories (a) commit hook missing, (b) commit
hook present but skipped, (c) commit hook blocked by safety check, (d)
commit hook errors out, (e) commit step owned by uninvoked wrapper, (f)
other). Run-5 evidence narrows the classification to **category (e),
"the commit step is owned by a different wrapper that is not being
invoked"**, with a strict-superset refinement: the wrapper IS the
supervisor process itself, and the supervisor process is not running.

Concretely:

- The supervisor process recorded in `supervisor_heartbeat.pid` (`3273960`)
  is no longer alive (`ps -p 3273960` returns no row).
- The supervisor heartbeat froze on `2026-05-02T03:50:11`
  (`supervisor_heartbeat.last_loop_ts`), only ~20 minutes after the
  supervisor instance was started at `2026-05-02T03:30:15`
  (`supervisor_heartbeat.started_at`). `loop_count = 3` confirms the
  loop made three passes before stopping.
- `agent_health.last_auto_commit_hash = null` confirms no
  supervisor-initiated auto-commit has ever completed for this
  supervisor instance, which is consistent with the loop dying before
  any planner-emitted artifacts could be committed.
- The master planner driver `claude_master_rebuild_planner.py --daemon`
  remains alive (PID `1052548`) and continues to regenerate
  `master_rebuild_planner_status.json` on each `--poll-seconds 120`
  tick, materialize BEGIN_FILE blocks, and append events, but it does
  not run `git add`, `git commit`, or `git push` (verified by
  `grep -nE "git add|git commit|push" claude_worklog/tools/claude_master_rebuild_planner.py`
  returning exactly one hit at line 710, which is a comment line inside
  the planner prompt template, not an executable code path).

The recovery task `081`'s prompt §2 explicitly enumerates classification
(e) as a valid root-cause outcome and §3 explicitly contemplates the
"safe manual commit path" alternative for that case. This directive is
therefore consistent with directive 10's authorized recovery scope; it
simply records the (e)-class diagnosis ahead of `081` because `081`
cannot run under the current runtime state.

## Why the recovery task `081` cannot self-dispatch

Task `081_codex_run4_supervisor_commit_hook_recovery` was emitted in the
same planner output as directive 10. Three independent obstacles
prevent it from self-dispatching this turn:

1. **The supervisor scanner is offline.** The supervisor process that
   would scan `claude_worklog/agent_supervisor/tasks/` for new pending
   tasks and dispatch them is the same process that is dead. The
   planner driver does not dispatch tasks; it only emits planner output
   and writes status JSON.
2. **Task `081` is itself untracked.** Even if a fresh supervisor
   instance were started right now, the canonical supervisor scanner
   policy requires committed task definitions (the `last_commit` field
   in `master_rebuild_planner_status.json` and the
   `evidence_reconciliation_status.json` reconciliation logic are both
   evidence-first, which means uncommitted task files are not yet part
   of the canonical task graph). Task `081` would need to be committed
   before a fresh supervisor instance could see it as a pending task.
3. **The predecessor marker file for `081` is itself untracked.** Task
   `081`'s `predecessor_required_marker_file` is
   `claude_worklog/phase2_core_rebuild/decision_explainability/10_PLANNER_RUN_FOUR_HALT_RUN4_ESCALATION_2E1C_DELTA.md`,
   which is in the same untracked list. The marker line
   `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RUN_FOUR_HALTED` is
   present in the file body (line 370 of the untracked file), but the
   evidence-first reconciler treats markers in untracked files as
   provisional rather than authoritative.

These three obstacles are not independent failures of `081`; they are
all instances of the same root cause (the supervisor process is dead),
and the catch-22 cannot be broken by another planner turn. The planner
can emit more directives, but each new directive only adds another
untracked artifact to the list.

## Safe manual recovery path for the human operator

Directive 10 §"REQ_0014 Codex commit-hook recovery task" §3 explicitly
contemplates two acceptable outcomes for the recovery task: (i) repair
the supervisor commit hook so that the next normal supervisor dispatch
cycle commits the eleven untracked δ artifacts via the standard hook,
OR (ii) record an explicit safe manual commit path that an operator can
run from `/home/wali/Desktop/AI BOT REBUILD` to materialize the same
commit. Outcome (ii) is recorded below as a documentation artifact for
the human operator; this directive does not execute it, and the planner
has no authority to execute commits.

The operator has two non-exclusive options. Either option restores
forward progress; the operator may pick the one they prefer, or run
both in sequence (Option A first, then Option B if Option A succeeds in
restoring the supervisor heartbeat).

### Option A — restart the supervisor process (preferred; restores autonomy)

This is the preferred outcome because it restores the autonomous
dispatch loop and lets the standard supervisor commit hook (whatever
its actual implementation) commit the twelve untracked artifacts on its
next dispatch cycle. The operator runs:

```
cd "/home/wali/Desktop/AI BOT REBUILD"
bash claude_worklog/tools/start_autonomous_agent_supervisor.sh
```

(or the equivalent supervisor launcher that the project actually uses;
the exact filename should be confirmed against
`claude_worklog/tools/` directory listing, since the project also
contains `claude_worklog/tools/start_claude_master_rebuild_planner.sh`
and `claude_worklog/tools/start_claude_design_handoff.sh` which are
distinct launchers.)

After restart, the operator MUST verify:

- `claude_worklog/agent_supervisor/status/supervisor_heartbeat.json`
  shows a fresh `last_loop_ts` (within the last `--poll-seconds`
  window),
- `supervisor_heartbeat.pid` matches the actual `ps -ef` PID for the
  new process,
- `agent_health.last_auto_commit_hash` is no longer `null` after the
  next dispatch cycle (or the supervisor commits the twelve untracked
  artifacts as part of its normal cycle).

If the supervisor restarts successfully and commits the twelve
untracked artifacts via its normal hook, then task `081` becomes
reachable on the supervisor's next scan, and the recovery task can run
its diagnostic and confirm the repair (or, if the commit-hook bug was
real but masked by the supervisor death, identify the deeper hook bug
and document it). Lane A then resumes per directive 09 §"Lane A
re-authorization" without further planner re-authorization edits to the
existing δ artifacts.

If the supervisor refuses to restart, fails to commit on its next
cycle, or repeats the early-exit pattern that produced the original
death (only three loops before stopping), the operator escalates to
Option B.

### Option B — execute the safe manual commit path (records the alternative outcome from directive 10 §3 (ii))

This is the explicit safe manual commit path that directive 10 §3
authorizes as the alternative outcome. It is L1 (documentation-driven,
operator-executed) and confined entirely to non-live, non-legacy,
non-Redis, non-exchange, non-deploy actions.

The operator runs the following EXACT sequence from
`/home/wali/Desktop/AI BOT REBUILD` (no cd into any other directory, no
edits to any of the listed files between `git add` and `git commit`,
no changes to git config, no `--no-verify`, no `--amend`, no
`--no-gpg-sign`, no force-push, no `git reset --hard`, no `git clean`):

```
cd "/home/wali/Desktop/AI BOT REBUILD"

# 1. Confirm the head matches the directive's attestation.
git rev-parse --short HEAD
# Expected: 7eefb89

# 2. Confirm the working tree contains exactly the thirteen untracked
#    Claude-emitted artifacts and the one M-modified planner prompt.
#    The M-modified planner prompt is owned by a separate concurrent
#    process and MUST NOT be added or committed by this sequence.
git status -s

# 3. Stage exactly the thirteen artifacts by name. Do NOT use
#    "git add -A" or "git add ." since those would also stage the
#    M-modified planner prompt and any future untracked artifacts.
git add \
  claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json \
  claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json \
  claude_worklog/agent_supervisor/tasks/081_codex_run4_supervisor_commit_hook_recovery.json \
  claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md \
  claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md \
  claude_worklog/phase2_core_rebuild/decision_explainability/08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md \
  claude_worklog/phase2_core_rebuild/decision_explainability/09_PLANNER_RUN_THREE_REAUTHORIZE_2E1C_DELTA_DISPATCH.md \
  claude_worklog/phase2_core_rebuild/decision_explainability/10_PLANNER_RUN_FOUR_HALT_RUN4_ESCALATION_2E1C_DELTA.md \
  claude_worklog/phase2_core_rebuild/decision_explainability/11_PLANNER_RUN_FIVE_HUMAN_ATTENTION_REQUIRED_2E1C_DELTA.md \
  claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md \
  claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md \
  claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md \
  claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md

# 4. Verify the staged set matches exactly thirteen files and contains
#    no .env, no secrets file, no path under /home/wali/Desktop/AI BOT,
#    and no path under v2/. The M-modified planner prompt MUST NOT
#    appear in the staged list.
git diff --cached --name-only

# 5. Strip the trailing "END_FILE: <path>" line from the three JSON task
#    files only (per the canonical strip-on-commit policy established
#    by tasks 060, 064, and 078). Markdown files retain their
#    "END_FILE: <path>" trailer as plain text. The operator can verify
#    by reading the staged JSON content; if the JSON parses cleanly
#    with `python3 -c "import json,sys; json.load(open(sys.argv[1]))"`
#    for each of the three task files, the strip is correct.
#    (If the master planner driver materialization already strips the
#    END_FILE marker from JSON files at write time — which it does
#    per the existing precedent — no manual strip is required and
#    this step is a no-op verification.)
python3 -c "import json; [json.load(open(p)) for p in [\
  'claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json',\
  'claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json',\
  'claude_worklog/agent_supervisor/tasks/081_codex_run4_supervisor_commit_hook_recovery.json']]; print('json ok')"

# 6. Commit with the canonical commit message and the standard
#    Co-Authored-By trailer per Lane A precedent. Do NOT use --no-verify,
#    do NOT use --amend, do NOT use --no-gpg-sign.
git commit -m "$(cat <<'EOF'
Add Phase 2E1.C.delta trainer parity composition specs and tasks

Materializes the four Phase 2E1.C.delta composition layer specs
(80-83) under trainer_gpu_parity_impl/, the six 2E1.C.delta planner
directives (06-11) under decision_explainability/, and the three
supervisor task definitions (079, 080, 081) under
agent_supervisor/tasks/. Lane A 2E1.C.delta dispatch remains halted
per directive 10; this commit only materializes the artifacts so the
supervisor scanner can resolve task 081's predecessor marker once the
supervisor process is restored.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

# 7. Verify the commit succeeded and the working tree returns to a
#    clean state for the thirteen artifacts (the M-modified planner
#    prompt remains modified by design).
git log --oneline -1
git status -s
```

After Option B succeeds, the operator either:

- runs Option A (restart the supervisor) so the autonomous loop can
  scan the now-committed `081` and dispatch it to Codex, which will
  then run the diagnostic and decide whether to write
  `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_REPAIRED` (if the commit hook
  was the real bug) or
  `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_SAFE_MANUAL_COMMIT_PATH_RECORDED`
  (if the supervisor death was the real bug, in which case Option B
  itself constitutes the safe manual commit path the recovery task
  would have recorded), OR
- runs Codex on `081` manually via the operator's Codex CLI to perform
  the diagnostic and produce
  `claude_worklog/agent_supervisor_reliability/09_RUN4_COMMIT_HOOK_DIAGNOSTIC_REPORT.md`
  and
  `claude_worklog/agent_supervisor_reliability/10_RUN4_COMMIT_HOOK_DIAGNOSTIC_GO_NO_GO.md`,
  then commits those two files and resumes Lane A.

Either follow-up restores the autonomous dispatch loop. Neither
follow-up requires further planner re-authorization edits to the
existing δ artifacts.

### What Option B does NOT do

Option B does NOT:

- modify any file under `/home/wali/Desktop/AI BOT/` (the legacy bot is
  untouched);
- write or delete any Redis key;
- restart any live trainer/trader/orchestrator/Redis/VPN service
  (Option A's `start_autonomous_agent_supervisor.sh` restarts only the
  non-live supervisor process, which is the AI BOT REBUILD project's
  own automation harness, not a live trading service);
- place or cancel any exchange order;
- change leverage or margin mode;
- enable live trading;
- deploy anything;
- run any production migration;
- expose or commit any secret;
- modify the master planner prompt under
  `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
  (the M-modified state of that file is owned by a separate concurrent
  process and is explicitly excluded from the staged set);
- modify any of the eleven untracked δ artifacts, directive 10, or
  task `081` (the operator stages them as-is; the only "modification"
  is the staging itself);
- modify any file under `v2/` (Lane A implementation work is HALTED per
  directive 10 and Option B does not author or modify any V2 source
  file);
- bypass any pre-commit hook (`git commit` is run without
  `--no-verify`).

Option B is therefore a strict subset of the actions already authorized
by directive 10 §3 (ii), with the additional element of including
directive 11 (this directive) in the staged set so that directive 11's
audit record of the safe manual recovery path is itself committed
alongside the recovery it documents.

## Planner self-halt this turn — no further re-authorization, HALT, no-change confirmation, or task-introduction directive

The planner SHALL NOT, on any subsequent polling turn against an
unchanged `7eefb89` head with the same growing untracked-artifact list,
emit any of the following:

- another Run-N re-authorization directive (Run-2 directive 08, Run-3
  directive 09);
- another HALT directive (Run-4 directive 10);
- another no-change confirmation directive (after-Run-1 directive 07);
- another task-introduction directive (no new tasks until either
  Option A restores the supervisor or Option B materializes the
  thirteen artifacts via the safe manual commit path);
- another HUMAN ATTENTION directive (this directive 11 is the
  terminal HUMAN ATTENTION directive of the Run-N escalation chain;
  further planner turns against the same unchanged head MUST emit
  exactly one BEGIN_FILE block whose body is the single line
  `PHASE2H_PLANNER_RUN_N_NO_PROGRESS_HUMAN_ATTENTION_STILL_REQUIRED`
  and whose path is
  `claude_worklog/phase2_core_rebuild/decision_explainability/12_PLANNER_RUN_N_NO_PROGRESS_HUMAN_ATTENTION_STILL_REQUIRED.md`,
  appending nothing further; the planner MUST NOT incrementally
  rename that file as `13_…`, `14_…`, etc., on subsequent turns —
  one no-progress sentinel file is sufficient and any future planner
  turn that would otherwise emit a fresh sentinel SHALL instead emit
  no BEGIN_FILE blocks at all and the master planner driver SHALL
  treat the absence of new BEGIN_FILE blocks as the planner's
  acknowledgment that no progress is possible without operator
  action).

This self-halt is binding on the planner's own future turns; it does
not bind the supervisor (which is not running anyway), Codex (which
cannot run task `081` until either Option A or Option B unblocks it),
or the operator (who has full discretion to choose between Options A
and B and has full discretion to ignore this directive entirely).

The self-halt is reversed automatically as soon as ONE of the
following conditions is observed by the master planner driver on a
fresh polling turn:

- `git rev-parse --short HEAD` returns a value other than `7eefb89`
  (i.e., a commit has happened, regardless of who made it);
- `supervisor_heartbeat.last_loop_ts` advances past
  `2026-05-02T03:50:11` (i.e., a fresh supervisor instance is alive
  and looping);
- `agent_health.last_auto_commit_hash` becomes non-null (i.e., a
  supervisor auto-commit has succeeded);
- the twelve δ artifacts plus this directive transition out of the
  `??` untracked list (i.e., either Option A or Option B has
  materialized the commit).

On any of those four conditions, the planner returns to its standard
polling-turn behavior under directives 06 §"Lane A authorization" / 09
§"Lane A re-authorization" without further re-authorization edits to
the existing δ artifacts, and the Lane A 2E1.C.δ dispatch sequence
resumes from the point at which it was halted (commit step 1 of
directive 09 §"Lane A re-authorization", followed by sanity check #2
and the `079` / `080` dispatch chain).

## Lane A — HALT remains in force from directive 10, with this directive's refined diagnosis attached

The agent_supervisor (when restored) MUST continue to HALT the Lane A
2E1.C.δ dispatch sequence ordered by directives 06–09, exactly as
ordered by directive 10 §"Lane A — HALT". This directive 11 does NOT
lift the HALT. The HALT is lifted only by:

- Codex writing
  `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_REPAIRED` to
  `claude_worklog/agent_supervisor_reliability/10_RUN4_COMMIT_HOOK_DIAGNOSTIC_GO_NO_GO.md`,
  OR
- Codex writing
  `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_SAFE_MANUAL_COMMIT_PATH_RECORDED`
  to the same file (which Option B in §"Safe manual recovery path for
  the human operator" already constitutes; Codex re-running task
  `081` after the safe manual commit path has been executed should
  recognize that outcome and write the SAFE_MANUAL marker
  immediately).

Either marker, once written and committed, allows the supervisor to
resume Lane A per directive 09 §"Lane A re-authorization" steps 4–7
without further planner action.

The HALT does NOT delete, archive, or modify any of the thirteen
untracked artifacts. Their bodies remain authoritative as δ specs,
tasks, planner directives, and the safe manual recovery path
documentation; they remain untracked until either Option A or Option
B is executed.

## Codex parallel-lane policy this turn — unchanged narrowed exception from directive 10

The standing Codex Pro parallel-lane policy
(`git_clean_and_no_active_dirty_claude_output`) remains barred this
turn except for the single narrowed exception recorded in directive
10 §"Codex parallel-lane policy this turn — narrowed exception for the
recovery task only":

- Codex MAY run task `081_codex_run4_supervisor_commit_hook_recovery`
  even though the thirteen artifacts remain untracked, BECAUSE the
  diagnostic subject of the recovery task IS the supervisor's failure
  to commit those exact dirty files (refined by this directive to:
  the supervisor's death is the deeper root cause).
- Codex MUST NOT run any other parallel review or autofix this turn.
  Codex MUST NOT pre-empt the `080` Codex review for 2E1.C.δ;
  predecessor marker
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` does not
  yet exist and the Lane A dispatch is now halted.
- Codex MUST NOT touch α (`v2/backend/app/domain/trainer_liveness/`),
  β (`v2/backend/app/domain/liveness_stream_growth/`), or δ
  (`v2/backend/app/domain/trainer_liveness_composition/` — not yet
  authored) packages.
- Codex MUST NOT touch the master planner prompt under
  `claude_worklog/autonomous_control_plane/`.
- Codex MUST NOT modify any of the thirteen untracked artifacts, task
  `081`, or this directive (`11_…`); the recovery task's job is to
  enable the standard supervisor commit hook to commit them, not to
  commit them itself, and not to edit them.

If the operator chooses Option B (manual commit) and then runs Codex
manually on `081`, Codex's diagnostic should recognize Option B's
execution as the SAFE_MANUAL outcome and write
`PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_SAFE_MANUAL_COMMIT_PATH_RECORDED`
to the GO/NO_GO file without attempting further repair, since the
underlying root cause (supervisor process death) is more naturally
addressed by Option A (supervisor restart) than by a code-level repair
in `claude_worklog/tools/`.

## Lane B re-authorization (REQ_0008 frontend) — unchanged, still parked

Lane B remains parked exactly as recorded in directives 05, 06, 07,
08, 09, and 10. Tasks `063`, `067`, `068` remain blocked. The current
`blocked_approval` status for `063` reflects the older safety hit
recorded prior to the `7eefb89` false-positive suppression; the
suppression has not been re-tested against `063`. The planner does
NOT advance Lane B this turn. Resolution still requires the human
choice between Path B1 (complete the manual session) and Path B2
(archive the manual brief into `frontend_design/manual_handoff_archive/`).
The Run-5 HUMAN ATTENTION posture does NOT change Lane B status.

## Lane C re-authorization (REQ_0009 decision explainability) — unchanged

Task `069_decision_explainability_2ha0_lineage_inventory` remains
`pending` with supervisor-side classification `current_running_task` +
`stale_running_count = 1` per the snapshot taken at
`2026-05-04T00:13:38.591826+00:00` (the `queue_status.json` snapshot is
itself older than `master_rebuild_planner_status.json` because the
queue scanner is part of the dead supervisor and has not refreshed
since). Predecessor marker `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` is
present in
`claude_worklog/phase2_core_rebuild/decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`;
the three required output files
(`05_DECISION_LINEAGE_INVENTORY_REPORT.md`, `06_…GAP_MATRIX.md`,
`07_…GO_NO_GO.md`) are absent.

Lane C handling remains as ordered in directive 09 §"Lane C
re-authorization" and directive 10 §"Lane C re-authorization": the
supervisor (when restored) SHOULD apply its standard stale-running
recovery to `069` (refresh dispatch with the same prompt; no spec
changes), and on second stale without progress should escalate to a
REQ_0014 recovery task scoped strictly to `decision_explainability/`
outputs. The Run-5 HUMAN ATTENTION posture applies to the planner's
own emission discipline; it does NOT halt Lane C, but Lane C is in
practice frozen until the supervisor process is restored, because the
supervisor is the dispatcher for Lane C as well.

Note however that Lane C's outputs `05_…`, `06_GAP_MATRIX.md`, and
`07_…GO_NO_GO.md` would conflict with this directive's `11_…` numbering
ONLY if Lane C re-emits its outputs under the
`decision_explainability/` directory using the same numerical prefix
range; the planner reserves prefixes `05–07` for Lane C and `06–11`
for the planner's own Run-N directive chain (where `06` was
intentionally re-used by directive 06 because no Lane C `06_GAP_MATRIX`
exists yet). On Lane C resumption, Lane C SHALL use prefixes `05`,
`06A_GAP_MATRIX.md`, and `07_GO_NO_GO.md` (with the `06A` suffix
disambiguating from directive 06's planner directive, OR Lane C SHALL
choose prefixes `12`, `13`, `14` instead) to avoid prefix collision.
The planner's Run-N self-halt (no further planner directives unless
the head moves) makes prefix `12` available for Lane C if the operator
prefers.

## Combined dispatch order this turn

1. Lane A — HALT remains in force per directive 10. No supervisor
   action this turn (the supervisor is not running anyway). Lane A
   re-resumes only after Codex writes
   `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_REPAIRED` or
   `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_SAFE_MANUAL_COMMIT_PATH_RECORDED`
   to
   `claude_worklog/agent_supervisor_reliability/10_RUN4_COMMIT_HOOK_DIAGNOSTIC_GO_NO_GO.md`,
   per directive 10 §"Combined dispatch order this turn" step 1.
2. Lane B — remains parked. No supervisor action.
3. Lane C — frozen until the supervisor is restored. On supervisor
   restoration, refresh stale `069`; on PASS dispatch `070`. (Same as
   directive 10 §"Combined dispatch order this turn" step 3.)
4. Operator — choose Option A (preferred) or Option B (alternative)
   from §"Safe manual recovery path for the human operator" above to
   restore forward progress. The planner will not re-dispatch any
   lane until ONE of the four self-halt-reversal conditions in
   §"Planner self-halt this turn" is observed.

## Stop conditions (planner-binding) — superset of directives 06–10

The supervisor (when restored) and the planner (on every future
polling turn) MUST halt the active lane and surface to the operator on
any of:

- a FAIL marker written by `069`/`070`/`079`/`080`/`081`;
- a `PHASE2H_RUN4_COMMIT_HOOK_DIAGNOSTIC_BLOCKED` marker written by
  `081` to
  `claude_worklog/agent_supervisor_reliability/10_RUN4_COMMIT_HOOK_DIAGNOSTIC_GO_NO_GO.md`;
- any forbidden-token hit per the per-lane lists in each task spec;
- any `END_FILE: <path>` marker leak inside `081`'s diagnostic report
  or its GO/NO_GO file (those two files MUST NOT contain any line
  beginning with `END_FILE:` because Codex authors them via the Edit
  or Write tool, not via BEGIN_FILE/END_FILE materialization);
- any write attempt by `081` outside its `allowed_output_prefixes`
  closed list (most importantly: any write to `v2/`, to the thirteen
  untracked artifacts, to other phase2_core_rebuild subtrees, or to
  `claude_worklog/autonomous_control_plane/`);
- any α/β/δ cross-isolation regression (the recovery task modifies
  any byte under `v2/backend/app/domain/trainer_liveness/`,
  `v2/backend/app/domain/liveness_stream_growth/`, or
  `v2/backend/app/domain/trainer_liveness_composition/` — the latter
  does not yet exist and MUST NOT be created by `081`);
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation;
- any attempt by `081` to mutate the master planner prompt
  (`claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`);
- any attempt by `081` to commit, push, or otherwise persist a write
  to any of the thirteen untracked artifacts (the recovery task's
  job is to enable the standard supervisor commit hook to commit them,
  not to commit them itself);
- any attempt by Option B's manual commit sequence to stage files
  outside the listed thirteen (most importantly: the M-modified
  `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
  MUST NOT be staged; any future untracked artifact emitted by the
  still-running planner daemon between the start and end of Option
  B's sequence MUST NOT be staged in the same commit; if the operator
  observes new untracked artifacts during Option B, the operator
  SHOULD pause Option B, re-read this directive's untracked-artifact
  list, and either restrict the staged set to exactly the thirteen
  listed files OR amend this directive's list before proceeding —
  the latter requires a fresh planner turn);
- any attempt by Option A's supervisor restart to enable live trading,
  change leverage, restart any live trader/trainer/orchestrator/Redis/VPN
  service, or perform any L4/L5 action; Option A is restricted to
  restarting the AI BOT REBUILD project's own non-live automation
  supervisor, which is `claude_worklog/tools/agent_supervisor.py` and
  its launcher scripts under `claude_worklog/tools/`.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change this.
The δ composition layer remains pure-Python, sync, no-async, no-Redis,
no-subprocess, no-network, no-clock, no-legacy by construction; γ
remains deferred. The Run-5 HUMAN ATTENTION posture and the safe
manual recovery path (both Options A and B) are non-live, L1–L2 only,
and confined to safety/status/review tooling and to the AI BOT REBUILD
project's own automation harness. Neither option places, cancels, or
modifies any exchange order, writes any Redis key, restarts any live
trading service, deploys anything, runs any production migration, or
exposes or commits any secret. The legacy bot under
`/home/wali/Desktop/AI BOT/` is not modified, restarted, or read
during either option.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RUN_FIVE_HUMAN_ATTENTION_REQUIRED
END_FILE: claude_worklog/phase2_core_rebuild/decision_explainability/11_PLANNER_RUN_FIVE_HUMAN_ATTENTION_REQUIRED_2E1C_DELTA.md

End-of-turn summary: emitted Run-5 HUMAN-ATTENTION directive `11_…` that refines directive 10's diagnosis to "supervisor process death" (heartbeat frozen since `2026-05-02T03:50:11`, PID `3273960` not alive, only the planner daemon at PID `1052548` running), explains why task `081` cannot self-dispatch (catch-22: dead scanner + untracked task + untracked predecessor marker file), records the explicit safe manual recovery path that directive 10 §3 (ii) authorizes, and self-halts the planner from emitting further re-authorization/HALT/no-change/HUMAN-ATTENTION/task-introduction directives until the operator either restarts the supervisor (Option A, preferred) or executes the recorded thirteen-file commit (Option B). No new tasks, no edits to the existing untracked artifacts, no v2/ writes, no commits, no process restarts. Lane A HALT from directive 10 stays in force; Lane B parked; Lane C frozen pending supervisor restart.
