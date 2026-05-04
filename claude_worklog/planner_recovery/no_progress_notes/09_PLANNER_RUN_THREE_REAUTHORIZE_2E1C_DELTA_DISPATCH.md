# Planner Directive — Run-Three Re-Authorization of 2E1.C.δ Dispatch (2026-05-03)

This is a Master Non-Live Rebuild Planner run-three turn-stamp. It re-authorizes
the dispatch sequence already ordered in
`claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`,
re-affirmed in
`claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`,
and re-authorized once already in
`claude_worklog/phase2_core_rebuild/decision_explainability/08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`,
under a fresh planner-turn boundary so the agent_supervisor's run-once mode
can attribute the Lane A δ-dispatch commit to a verified planner authorization
read on this run rather than to a previous run.

This directive does NOT supersede directives 06, 07, or 08. It is a turn-stamp
only. No new task definitions, V2 source files, spec files, status markers,
or task prompt edits are introduced this turn. No legacy under
`/home/wali/Desktop/AI BOT/` is touched. No Redis write or delete is
performed. No live trading is enabled. The δ composition layer remains
pure-Python, sync, no-async, no-Redis, no-subprocess, no-network, no-clock,
no-legacy by construction; γ (read-only Redis observation collector) remains
deliberately deferred until δ is Codex-passed so the in-process safety
boundary stays intact for as long as possible.

## Why a third turn-stamp is required

Verified at this turn's read time:

- `git rev-parse --short HEAD` returns `7eefb89` (`Avoid frontend inventory live-trading safety false positive`), unchanged from the head observed by directives 07 and 08.
- `git status -s` reports the `M` entry on `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (concurrent process, out of scope) plus exactly ten `??` entries:
  - `claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
  - `claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`
  - `claude_worklog/phase2_core_rebuild/decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md`
  - `claude_worklog/phase2_core_rebuild/decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md`
  - `claude_worklog/phase2_core_rebuild/decision_explainability/08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md`
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md`
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md`
  - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md`

Directive 08 itself (`08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`) is
present in that untracked set, which establishes that the Run-2 commit ordered
by directive 08 §"Lane A re-authorization" step 1 was not materialized between
the prior planner turn and this one. The supervisor's run-once driver re-polled
the planner for a fresh turn boundary without an intervening commit. This file
IS that turn boundary; it intentionally adds no new specification beyond
re-authorization plus a bounded Run-4 escalation rule.

## Verified state at this turn's read time (delta from directive 08)

| Verification | Path | Result |
| --- | --- | --- |
| 2E1.A Codex pass marker | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` present (unchanged) |
| 2E1.B Codex pass marker | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` present (unchanged) |
| 2E1.C.α final Codex pass marker | `trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` present (unchanged) |
| 2E1.C.β final Codex pass marker | `trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md` | `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` present (unchanged) |
| 2E1.C.δ composition spec | `trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md` | `PHASE2E1C_DELTA_COMPOSITION_SPEC_READY` second-to-last non-empty line; canonical trailer present (1 hit); body byte-identical to directive 07/08 attestation |
| 2E1.C.δ test plan | `trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md` | `PHASE2E1C_DELTA_TEST_PLAN_READY` second-to-last non-empty line; canonical trailer present (1 hit); per-section END_FILE leak self-check scope remains narrowed to four δ-only paths per directive 06 §3 |
| 2E1.C.δ safety boundaries | `trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md` | `PHASE2E1C_DELTA_SAFETY_BOUNDARIES_READY` second-to-last non-empty line; canonical trailer present (1 hit) |
| 2E1.C.δ GO request | `trainer_gpu_parity_impl/83_PHASE_2E1C_DELTA_GO_NO_GO_REQUEST.md` | `PHASE2E1C_DELTA_GO_NO_GO_REQUEST_RECORDED` second-to-last non-empty line; canonical trailer present (1 hit) |
| 2E1.C.δ implementation task | `agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json` | `status = "pending"`; step-4 grep scope narrowed to four δ-only scopes per directive 06 §3; trailer per JSON-task strip-on-commit precedent |
| 2E1.C.δ Codex review task | `agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json` | `status = "pending"`; rubric item 10 grep scope narrowed accordingly per directive 06 §4 |
| Directive 06 trailer | `decision_explainability/06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md` | `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_SANITY_CHECK_CORRECTION_RECORDED` second-to-last non-empty line; canonical trailer present (1 hit) |
| Directive 07 trailer | `decision_explainability/07_PLANNER_TURN_NO_CHANGE_CONFIRMATION_2E1C_DELTA.md` | `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_DISPATCH_AUTHORIZED` second-to-last non-empty line; canonical trailer present (1 hit) |
| Directive 08 trailer | `decision_explainability/08_PLANNER_RUN_TWO_REAUTHORIZE_2E1C_DELTA_DISPATCH.md` | `PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RUN_TWO_REAUTHORIZED` second-to-last non-empty line; canonical trailer present (1 hit) |
| Repo head | `git rev-parse --short HEAD` | `7eefb89` (unchanged from directive 08 attestation) |
| Lane B slot state | `frontend_design/06_CLAUDE_DESIGN_OUTPUT.md` | `CLAUDE_DESIGN_OUTPUT_PENDING` (manual session not yet completed); task `063` still `blocked_approval` (unchanged) |
| Lane C predecessor marker | `decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md` | `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` present (unchanged) |
| Lane C required outputs | `decision_explainability/05_DECISION_LINEAGE_INVENTORY_REPORT.md`, `…/06_…GAP_MATRIX.md`, `…/07_…GO_NO_GO.md` | absent (unchanged) |

Nothing in the verified state has shifted in a way that contradicts directives
06, 07, or 08. The factual corrections those directives carried — canonical
trailer accounting, sanity check #2 narrowing, and the four-scope δ-only END_FILE
self-check — remain in force; this turn does NOT re-correct them.

## Lane A re-authorization (REQ_0006 trainer parity, sub-phase 2E1.C.δ)

The agent_supervisor is re-authorized to perform the dispatch sequence
already specified in directive 08 §"Lane A re-authorization", in the same
order, without further planner intervention until a stop condition fires.
The Run-3 commit batch supersedes the Run-2 batch by extending it with
directive 08 and this directive 09:

1. Stage and commit, in a single non-live milestone commit, exactly the ten
   untracked δ artifacts enumerated in §"Why a third turn-stamp is required"
   PLUS this file
   (`09_PLANNER_RUN_THREE_REAUTHORIZE_2E1C_DELTA_DISPATCH.md`) as the eleventh
   artifact in the same commit. Commit message SHOULD follow Lane A style
   (e.g. `Add Phase 2E1.C.δ trainer parity composition specs and tasks`)
   with the standard `Co-Authored-By` trailer. The commit MUST NOT include
   the `M`-modified
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
   The commit MUST be created via the standard supervisor commit hook so
   JSON task files have their canonical harness `END_FILE` trailer stripped
   at commit time (matching `060`/`064`/`078` precedent); Markdown spec
   files retain the canonical trailer as plain text (matching `70_…`,
   `06_…`, `07_…`, `08_…` precedent).

2. Run the canonical sanity check #2 from directive 07 §2 (as narrowed by
   directive 06 §3) against files 80–83 (read-only). The same
   accept-canonical-trailer / reject-leak semantics apply. On any deviation
   HALT Lane A and open a REQ_0014 Codex human-attention recovery task
   scoped to the offending file only.

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

## Run-4 escalation rule (new this turn)

Run-1 (directive 06) ordered the dispatch. Run-2 (directives 07 then 08)
re-authorized it. Run-3 (this directive) re-authorizes it once more. If a
fourth planner polling turn occurs against a head still at `7eefb89` with
the same δ artifacts still untracked AND directive 09 itself untracked,
the recurring no-progress is itself a stop condition independent of any
δ task content. In that case the supervisor MUST:

- HALT the Run-4 Lane A dispatch sequence,
- open a REQ_0014 Codex human-attention recovery task targeting the
  agent_supervisor commit-hook diagnostic path
  (`claude_worklog/agent_supervisor_reliability/` and
  `claude_worklog/tools/` only for safety/status/review tooling, per the
  REQ_0011 parallel scope),
- attach the supervisor's most recent `master_rebuild_planner_status.json`,
  `queue_status.json`, and the most recent commit-hook stderr/stdout to
  the recovery task,
- NOT emit a Run-4 re-authorization directive,
- surface to the planner only after Codex diagnoses why the Run-3 commit
  did not materialize and either repairs the supervisor commit hook or
  records a safe manual commit path.

This rule bounds the polling loop. It is the only Run-4 stop condition
introduced by this directive; all other Run-4 behavior remains governed
by directive 06 §"Stop conditions (planner-binding)" and the per-task
specs.

## Lane B re-authorization (REQ_0008 frontend) — unchanged

Lane B remains parked exactly as recorded in directives 05, 06, 07, and 08.
Tasks `063`, `067`, `068` remain blocked. The `7eefb89` commit suppressed
an unrelated false-positive safety pattern in supervisor pre-dispatch
scanning; it did NOT resolve the slot conflict between the manual Claude
Design handoff (`06_CLAUDE_DESIGN_OUTPUT.md` still
`CLAUDE_DESIGN_OUTPUT_PENDING`) and the automated `063` inventory. The
current `063` `blocked_approval` status reflects an older safety hit
recorded prior to `7eefb89`; the new suppression has not been re-tested
against `063`. The planner does NOT advance Lane B this turn. Resolution
still requires the human choice between Path B1 (complete the manual
session) and Path B2 (archive the manual brief into
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

1. Lane A — commit-and-sanity-check the eleven artifacts (the ten
   untracked entries plus this directive 09), then `079` → `080` per the
   sequence above. The Run-4 escalation rule applies if Run-3 fails to
   commit.
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
  enforces this gate. Note that the ten untracked δ artifacts plus this
  directive constitute "dirty Claude output" until committed; Codex Pro
  therefore MUST wait until the Lane A commit lands before resuming
  parallel work this turn.

## Stop conditions (planner-binding) — unchanged from directives 06/07/08, plus the Run-4 rule above

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
  `08_…`, `09_…` directives in `decision_explainability/`) containing
  more than one `^END_FILE:` line, or an `^END_FILE:` line that is not
  the file's final non-empty line, or whose final-line text does not
  match the file's repo-relative path (the body-bleed regression); the
  canonical exactly-one trailing `END_FILE: <path>` line is NOT a leak
  and MUST NOT be flagged;
- any write attempt outside the per-task `allowed_output_prefixes`;
- α or β cross-isolation regression inside Lane A (the δ implementation
  modifies any byte under `v2/backend/app/domain/trainer_liveness/` or
  `v2/backend/app/domain/liveness_stream_growth/`);
- the Run-4 no-progress condition defined in §"Run-4 escalation rule";
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change this. The
δ composition layer remains pure-Python, sync, no-async, no-Redis, no-
subprocess, no-network, no-clock, no-legacy by construction; γ remains
deferred.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA_RUN_THREE_REAUTHORIZED
