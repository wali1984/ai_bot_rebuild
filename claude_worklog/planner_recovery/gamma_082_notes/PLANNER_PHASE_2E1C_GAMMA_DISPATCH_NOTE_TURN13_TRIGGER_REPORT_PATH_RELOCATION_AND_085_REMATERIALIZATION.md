# Planner Turn 13 — REQ_0015 trigger report path relocation and 085 re-materialization

Turn 13 fixes two issues that prevented turns 8 through 12 from successfully clearing the planner-level dirty-tree dispatch hold.

## Issue 1 — Trigger report path was outside ALLOWED_MATERIALIZE_PREFIXES

Turns 8 through 12 attempted to emit the REQ_0015 trigger report at `claude_worklog/agent_supervisor_reliability/PLANNER_DIRTY_TREE_DISPATCH_HOLD_REQ0015_TRIGGER_REPORT_2026_05_04.md`. That prefix is not on `claude_master_rebuild_planner.py`'s `ALLOWED_MATERIALIZE_PREFIXES` tuple at `claude_worklog/tools/claude_master_rebuild_planner.py:44-51`. The allowed prefixes are `claude_worklog/agent_supervisor/tasks/`, `claude_worklog/phase2_core_rebuild/`, `claude_worklog/v2_scaffold_reviews/`, `claude_worklog/security/`, `claude_worklog/autonomous_control_plane/`, and `v2/`. The planner refused materialization at the agent_supervisor_reliability path regardless of whether the emit block was nested or top-level.

Turn 13 relocates the trigger report to `claude_worklog/autonomous_control_plane/PLANNER_DIRTY_TREE_DISPATCH_HOLD_REQ0015_TRIGGER_REPORT_2026_05_04.md`, which is on the allowed list and is the canonical home of every other planner artifact in this dirty set.

## Issue 2 — Protocol terminator line leaked into emitted file bodies

The harness's strict emit regex `^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$` (re.S | re.M) at `claude_worklog/tools/claude_master_rebuild_planner.py:293` requires a bare protocol terminator line containing only the literal text `END_FILE` followed by optional trailing whitespace. Turns 2 through 12 emitted terminator lines of the form `END_FILE: <path>`. The strict regex did not match, the fallback parser at `claude_worklog/tools/claude_master_rebuild_planner.py:299-308` ran instead, and the trailing `END_FILE: <path>` line was written into the file body as the final line of every materialized file. For markdown files this was a harmless stray line; for the 085 JSON it broke `json.load` because the supervisor's `load_json` helper at `claude_worklog/tools/agent_supervisor.py:234-236` calls `json.load` directly on the file and does not tolerate extra data after the closing brace.

Turn 13 emits all three new files with bare protocol terminators (the literal text matching `^END_FILE\s*$`) so the strict regex matches and the protocol terminator is consumed cleanly without leaking into the file body.

## Files materialized this turn (three top-level emit blocks)

1. `claude_worklog/autonomous_control_plane/PLANNER_DIRTY_TREE_DISPATCH_HOLD_REQ0015_TRIGGER_REPORT_2026_05_04.md` — the previously missing REQ_0015 step 1 + step 2 trigger report referenced by `085.predecessor_marker_files`, now under an allowed prefix. Final marker line: `PLANNER_DIRTY_TREE_DISPATCH_HOLD_REQ0015_TRIGGER_REPORT_READY`.

2. `claude_worklog/agent_supervisor/tasks/085_codex_recover_planner_dirty_tree_dispatch_hold.json` — re-emitted with no trailing protocol terminator leakage so `json.load` succeeds. `predecessor_marker_files` updated from the old `claude_worklog/agent_supervisor_reliability/...` path to the new `claude_worklog/autonomous_control_plane/...` path. `scope_dirty_paths` raised from 15 entries to 16 by adding this turn 13 acknowledgment AND moving the trigger-report entry to the new path. The `prompt` text updated from "fifteen paths" / "fifteen scope_dirty_paths" wording to "sixteen paths" / "sixteen scope_dirty_paths" wording, and from the old `agent_supervisor_reliability/` trigger-report path to the new `autonomous_control_plane/` path. `next_recommended_action` updated from "bundled fifteen paths" to "bundled sixteen paths". `task_id`, `agent`, `risk_level`, `status`, `cwd`, `emit_files`, `predecessor_marker`, `dispatch_bridge_clean_tree_override_authority`, `dispatch_bridge_clean_tree_override_scope`, `allowed_output_prefixes`, `required_output_files`, and `forbidden_actions` carry forward verbatim.

3. This turn 13 acknowledgment note. Added to `085.scope_dirty_paths` so the bundled commit covers all 16 dirty paths.

## What turn 13 does NOT emit

Turn 13 emits no new gamma spec, test plan, safety boundary, or GO/NO-GO artifact, no trainer parity implementation, no validation or remediation report against `082`, no new gamma Codex review request, no new requirement file, no edit to the planner prompt beyond its current on-disk content, and no new task JSON beyond the `085` re-emit. Tasks `082` and `083` remain queued unchanged. The committed gamma planning chain (`88_PHASE_2E1C_GAMMA_SPEC.md`, `89_PHASE_2E1C_GAMMA_TEST_PLAN.md`, `90_PHASE_2E1C_GAMMA_SAFETY_BOUNDARIES.md`, `91_PHASE_2E1C_GAMMA_GO_NO_GO_REQUEST.md`) and the gamma materialization recovery artifacts (`84_CODEX_GAMMA_MATERIALIZATION_RECOVERY_REPORT.md`, `84_CODEX_GAMMA_MATERIALIZATION_RECOVERY_GO_NO_GO.md`) remain unchanged. Turn 13 does not author any new requirement file, does not modify REQ_0006 / REQ_0007 / REQ_0008 / REQ_0009 / REQ_0010 / REQ_0011 / REQ_0013 / REQ_0014 / REQ_0015, and does not re-classify the active requirement (still `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE`).

## Dispatch sequencing after turn 13

Once the harness materializes turn 13's three top-level emit blocks:

- the trigger report exists at the new allowed-prefix path, satisfying `085.predecessor_marker_files`;
- the 085 JSON parses cleanly under `json.load`;
- the working tree carries exactly 16 dirty paths matching the new `085.scope_dirty_paths` exactly.

Per `085.dispatch_bridge_clean_tree_override_authority`, the supervisor's Master Planner Dispatch Bridge Policy "git is clean or only ignored runtime files are dirty" precondition is narrowly overridden for `085` and only `085`. The supervisor or operator may now invoke:

    python3 claude_worklog/tools/agent_supervisor.py \
      --task-id 085_codex_recover_planner_dirty_tree_dispatch_hold

Codex executes the 16-path safety re-audit, the high-confidence secret scan (raw output written to `claude_worklog/security/CODEX_085_SECRET_SCAN_2026_05_04.txt`), the bundled commit, and the push. After push, the working tree is clean modulo `085`'s own emitted recovery report and GO/NO-GO under `claude_worklog/agent_supervisor_reliability/`, which the supervisor commits via the normal post-task commit step (matching how `084` and `081` were handled). The next reconciliation tick then dispatches `082_trainer_parity_2e1c_gamma_implementation.json` automatically.

## Hard exclusions for the recovery (verbatim)

The recovery may not:

- modify `/home/wali/Desktop/AI BOT`
- write or delete Redis keys
- restart live services
- place or cancel orders
- change leverage or margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets
- bypass final live approval

The recovery may not widen scope beyond the 16 enumerated dirty paths in `085.scope_dirty_paths`. The recovery may not re-author the gamma planning chain or the gamma recovery artifacts. The recovery may not modify task `082` or task `083` definitions. The recovery may not modify `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` beyond its current on-disk content.

## Hard exclusions for gamma (unchanged)

All gamma-lane hard exclusions from turns 3, 4, 7, 8, 9, 10, 11, and 12 still apply verbatim (no live trading enable, no Redis client construction in gamma source/tests, no exchange API call, no legacy module import, no subprocess against the legacy trainer venv, no production secret read, no deployment, no production migration, no write under `/home/wali/Desktop/AI BOT/`, no write under `legacy_reference/`, no Claude or Codex modification of the planner prompt inside the gamma lane, and no modification of alpha, beta, or delta trees from inside `082`).

## Parallel Codex lane status

The parallel Codex review and autofix lane stays paused until `085` lands its commit and push, at which point the precondition `git_clean_and_no_active_dirty_claude_output` becomes true and the lane resumes automatically. While the lane is paused, Codex must not pre-review the gamma planning chain, must not pre-fix the queued `082` task, and must not run autofix passes on any other in-flight planner artifact.

## Stop conditions

REQ_0015's stop conditions remain in force. Codex must leave `human_attention_required` unresolved and stop on:

- live action
- legacy mutation
- Redis write or delete
- service restart
- exchange action
- deployment
- secret scan failure
- ambiguous business or trading decision
- L4 or L5 action
- final live approval

If `085` emits `CODEX_DIRTY_TREE_DISPATCH_HOLD_RECOVERY_BLOCKED`, the planner remains in `human_attention_required` with that explicit blocker line, and turn 14 will treat the new blocker as the next REQ_0015 trigger only if it is itself recoverable.

PLANNER_PHASE_2E1C_GAMMA_DISPATCH_NOTE_TURN13_TRIGGER_REPORT_PATH_RELOCATION_AND_085_REMATERIALIZATION_RECORDED
