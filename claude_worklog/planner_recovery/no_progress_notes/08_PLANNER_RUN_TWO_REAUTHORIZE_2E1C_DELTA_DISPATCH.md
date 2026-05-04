# Planner Directive — Run-Two Re-Authorization of 2E1.C.δ Dispatch (2026-05-03)

This is a Master Non-Live Rebuild Planner run-once turn-stamp. It re-authorizes
the dispatch sequence already ordered in
`claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
and re-affirmed in
`claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`,
under a fresh planner-turn boundary so the agent_supervisor's run-once mode
can attribute the eight-artifact δ-dispatch commit to a verified planner
authorization read on this run rather than to a previous run.

This directive does NOT supersede directives 06 or 07. It is a turn-stamp
only. No new task definitions, V2 source files, spec files, status markers,
or task prompt edits are introduced this turn. No legacy under
`/home/wali/Desktop/AI BOT/` is touched. No Redis write or delete is
performed. No live trading is enabled. The δ composition layer remains
pure-Python, sync, no-async, no-Redis, no-subprocess, no-network, no-clock,
no-legacy by construction; γ (read-only Redis observation collector) remains
deliberately deferred until δ is Codex-passed so the in-process safety
boundary stays intact for as long as possible.

## Why a second turn-stamp is required

The agent_supervisor `master_rebuild_planner_status.json` regenerated at
`2026-05-04T01:08:23+00:00` with `mode = "run-once"`,
`next_action = "run Claude planner for active requirement"`, and
`last_commit = 7eefb89 Avoid frontend inventory live-trading safety false positive`
(unchanged). The eight Lane A δ artifacts plus directive 07 itself remain in
the supervisor's serialized `git_status` field as `??` (untracked):

- `claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
- `claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`
- `claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`

The supervisor commit hook applies the canonical strip-on-commit policy
(JSON task files lose the trailing `END_FILE: <path>` line at commit time,
matching the `060`/`064`/`078` precedent; Markdown spec files retain it as
plain text, matching the `70_…` and `06_…` precedent). The `M` entry on
`claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
is owned by a separate concurrent process and remains out of scope for this
turn's commit.

In run-once mode each planner invocation is a discrete turn. Directive 07
authorized the dispatch in the prior run. Because the supervisor has not yet
materialized the dispatch commit, the run-once driver re-polled the planner
for a turn boundary to re-attribute the action to. This file IS that turn
boundary; it intentionally adds no new content beyond re-authorization.

## Verified state at this turn's read time

| Verification | Path | Result |
| --- | --- | --- |
| 2E1.A Codex pass marker | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` present |
| 2E1.B Codex pass marker | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` present |
| 2E1.C.α final Codex pass marker | `trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` present |
| 2E1.C.β final Codex pass marker | `trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` present |
| 2E1.C.δ composition spec body | `trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_COMPOSITION_SPEC_READY`; final non-empty line is the canonical harness `END_FILE` trailer (1 hit) |
| 2E1.C.δ test plan body | `trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_TEST_PLAN_READY`; canonical trailer present (1 hit); per-section END_FILE leak self-check scope narrowed to four δ-only paths per directive 06 §3 |
| 2E1.C.δ safety boundaries body | `trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_SAFETY_BOUNDARIES_READY`; canonical trailer present (1 hit) |
| 2E1.C.δ GO request body | `trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md` | second-to-last non-empty line is `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED`; canonical trailer present (1 hit) |
| 2E1.C.δ implementation task body | `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json` | `status = "pending"`; step-4 grep scope narrowed to four δ-only scopes per directive 06 §3 |
| 2E1.C.δ Codex review task body | `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json` | `status = "pending"`; rubric item 10 grep scope narrowed accordingly per directive 06 §4 |
| Directive 06 trailer | `decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md` | second-to-last non-empty line is `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_SANITY_CHECK_CORRECTION_RECORDED`; canonical trailer present (1 hit) |
| Directive 07 trailer | `decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md` | second-to-last non-empty line is `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_DISPATCH_AUTHORIZED`; canonical trailer present (1 hit) |
| Supervisor planner status freshness | `agent_supervisor/status/master_rebuild_planner_status.json` | `generated_at = 2026-05-04T01:08:23+00:00`; `last_commit = 7eefb89`; `human_attention_required = false`; `blocked_reason = null`; `next_action = "run Claude planner for active requirement"` |
| Supervisor queue snapshot | `agent_supervisor/status/queue_status.json` | `gate = "READY_FOR_CODEX_RERUN"`; `current_running_task = "069_decision_explainability_2ha0_lineage_inventory"` (Lane C, stale_running, count 1); `pending = 4`; tasks 079/080 not yet visible to scanner because they are untracked |
| Supervisor evidence reconciliation | `agent_supervisor/status/evidence_reconciliation_status.json` | `generated_at = 2026-05-04T00:15:43+00:00`; β final pass marker indexed under `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` (supersedes 066, 077, 078); α stack pass indexed under `CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_PASS` (supersedes 060, 060c, 069, 072, 073) |
| Lane B slot state | `frontend_design/06_CLAUDE_DESIGN_OUTPUT.md` | `CLAUDE_DESIGN_OUTPUT_PENDING` (manual session not yet completed); `current_status.json` shows task 063 status `blocked_approval` |
| Lane C predecessor marker | `decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md` | `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` present |
| Lane C required outputs | `decision_explainability/05_DECISION_LINEAGE_INVENTORY_REPORT.md`, `…/06_…GAP_MATRIX.md`, `…/07_…GO_NO_GO.md` | absent |

Nothing in the verified state has shifted in a way that contradicts directive 07.
The two factual corrections that 07 carried over from the prior 06 turn (the
canonical-trailer accounting and the corrected sanity check #2) remain in
force; this turn does NOT re-correct them.

## Lane A re-authorization (REQ_0006 trainer parity, sub-phase 2E1.C.δ)

The agent_supervisor is re-authorized to perform the dispatch sequence
already specified in directive 07 §"Lane A authorization", in the same
order, without further planner intervention until a stop condition fires:

1. Stage and commit, in a single non-live milestone commit, exactly the
   eight untracked δ artifacts enumerated in §"Why a second turn-stamp is
   required" above PLUS this file (`08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`)
   as the ninth artifact in the same commit. Commit message SHOULD follow
   Lane A style (e.g. `Add Phase 2E1.C.δ trainer parity composition specs and tasks`)
   with the standard `Co-Authored-By` trailer. The commit MUST NOT include
   the `M`-modified
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
   The commit MUST be created via the standard supervisor commit hook so
   JSON task files have their canonical harness `END_FILE` trailer stripped
   at commit time (matching `060`/`064`/`078` precedent); Markdown spec
   files retain the canonical trailer as plain text (matching `70_…`,
   `06_…`, `07_…` precedent).

2. Run the canonical sanity check #2 from directive 07 §2 against files
   80–83 (read-only). The same accept-canonical-trailer / reject-leak
   semantics apply. On any deviation HALT Lane A and open a REQ_0014 Codex
   human-attention recovery task scoped to the offending file only.

3. Verify predecessor markers required by task 079 (read-only):
   - `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED` in `83_…`,
   - `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` in `69_…`,
   - `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` in `53_…`.
   All three MUST return at least one match line under `rg -n`.

4. Dispatch
   `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
   as a single Max20-consolidated milestone task. Do NOT split unless the
   task fails for an emit/path/size/timeout reason; the task prompt is
   explicit that implementation, forbidden-token grep, END_FILE leak
   self-check (narrowed to the four δ-only scopes), `py_compile`, `pytest`,
   α/β cross-isolation regression, and status-report authoring all run in
   this single task.

5. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` in
   `trainer_gpu_parity_impl/84_2E1C_DELTA_GO_NO_GO.md`, commit the `84/85`
   artifacts and dispatch
   `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`.

6. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED`, open a REQ_0007 /
   REQ_0014 autofix task scoped strictly to
   `v2/backend/app/domain/trainer_liveness_composition/` and
   `v2/backend/tests/unit/domain/trainer_liveness_composition/`. Autofix
   MUST NOT touch α (`v2/backend/app/domain/trainer_liveness/`) or β
   (`v2/backend/app/domain/liveness_stream_growth/`) packages, the master
   planner prompt, or any file outside the canonical Codex parallel scope.

7. On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS` in
   `trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`, surface to
   the planner so a fresh turn can open 2E1.C.γ (read-only Redis
   observation collector) under a separate spec.

## Lane B re-authorization (REQ_0008 frontend) — unchanged

Lane B remains parked exactly as recorded in
`decision_explainability/05_PLANNER_THREE_LANE_STATUS_DIRECTIVE.md` and
re-confirmed in directives 06 and 07. Tasks `063`, `067`, `068` remain
blocked. The most-recent commit `7eefb89 Avoid frontend inventory
live-trading safety false positive` only suppressed an unrelated
false-positive safety pattern in supervisor pre-dispatch scanning; it did
NOT resolve the slot conflict between the manual Claude Design handoff
(`06_CLAUDE_DESIGN_OUTPUT.md` still `CLAUDE_DESIGN_OUTPUT_PENDING`) and the
automated `063` inventory. The current `063` `blocked_approval` status in
`current_status.json` reflects a separate older safety hit recorded at
`2026-05-04T00:13:38.564365+00:00`; the new `7eefb89` suppression has not
been re-tested against `063`. The planner does NOT advance Lane B this
turn. Resolution still requires the human choice between Path B1 (complete
the manual session) and Path B2 (archive the manual brief into
`frontend_design/manual_handoff_archive/`).

## Lane C re-authorization (REQ_0009 decision explainability) — unchanged

Task `069_decision_explainability_2ha0_lineage_inventory` remains
`pending` in its task definition with supervisor-side classification
`current_running_task` + `stale_running_count = 1`. Predecessor marker
`PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` is present in
`decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`; the three
required output files (`05_DECISION_LINEAGE_INVENTORY_REPORT.md`,
`06_…GAP_MATRIX.md`, `07_…GO_NO_GO.md`) are absent.

The supervisor SHOULD apply its standard stale-running recovery to `069`
(refresh dispatch with the same prompt; no spec changes). If the refreshed
`069` again becomes stale a second time without progress on the three
required output files, escalate to a REQ_0014 Codex human-attention
recovery task scoped strictly to `decision_explainability/` outputs;
Codex MUST NOT modify any file under `v2/` for Lane C.

On `PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED`, dispatch
`070_decision_explainability_2ha0_codex_review` per directive 06 §"Lane C
authorization".

## Combined dispatch order this turn

The supervisor SHOULD execute the two non-blocked lanes in parallel where
Codex Pro capacity allows; both are independent:

1. Lane A — commit-and-sanity-check the nine artifacts (eight + this
   file 08), then `079` → `080` per the sequence above.
2. Lane C — refresh stale `069`; on PASS dispatch `070`.

Lane B remains blocked pending human reconciliation of the slot conflict.

## Codex Pro parallel lane policy this turn — unchanged

- Codex Pro MAY in parallel review the already-committed 2E1.C.β artifacts
  for residual hardening opportunities under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` status
  reports only — no `v2/` source changes.
- Codex Pro MUST NOT pre-empt the `080` Codex review for 2E1.C.δ;
  predecessor marker
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` does not yet
  exist.
- Codex Pro MUST NOT touch α or β packages, the master planner prompt
  under `claude_worklog/autonomous_control_plane/`, or any file outside
  the canonical Codex parallel scope.
- Codex Pro parallel review MAY proceed only when `git status -s` is
  clean of dirty Claude output AND no Claude child or supervisor task is
  actively writing inside the Codex parallel scope. The supervisor
  enforces this gate. Note that the eight untracked δ artifacts plus
  this directive constitute "dirty Claude output" until committed; Codex
  Pro therefore MUST wait until the Lane A commit lands before resuming
  parallel work this turn.

## Stop conditions (planner-binding) — unchanged from directive 06/07

The supervisor MUST halt the active lane and surface to the planner on
any of:

- a FAIL marker written by `069`/`070`/`079`/`080`;
- any forbidden-token hit per the per-lane lists in each task spec;
- any `END_FILE: <path>` marker leak inside the δ source tree
  (`v2/backend/app/domain/trainer_liveness_composition/`), the δ test
  tree (`v2/backend/tests/unit/domain/trainer_liveness_composition/`),
  or the implementer-authored `84` / `85` status files (the canonical
  2E1.B regression class — Python source/test files where the trailer
  breaks `py_compile`, and the implementer-authored markdown the
  implementer is instructed to author cleanly via the Edit or Write
  tool, NOT via BEGIN_FILE/END_FILE materialization);
- any planner-emitted Markdown spec under
  `trainer_gpu_parity_impl/{80,81,82,83}_*.md` (or the `06_…`, `07_…`,
  `08_…` directives in `decision_explainability/`) containing more than
  one `^END_FILE:` line, or an `^END_FILE:` line that is not the file's
  final non-empty line, or whose final-line text does not match the
  file's repo-relative path (the body-bleed regression); the canonical
  exactly-one trailing `END_FILE: <path>` line is NOT a leak and MUST
  NOT be flagged;
- any write attempt outside the per-task `allowed_output_prefixes`;
- α or β cross-isolation regression inside Lane A (the δ implementation
  modifies any byte under `v2/backend/app/domain/trainer_liveness/` or
  `v2/backend/app/domain/liveness_stream_growth/`);
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change this. The
δ composition layer remains pure-Python, sync, no-async, no-Redis, no-
subprocess, no-network, no-clock, no-legacy by construction; γ remains
deferred.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RUN_TWO_REAUTHORIZED
