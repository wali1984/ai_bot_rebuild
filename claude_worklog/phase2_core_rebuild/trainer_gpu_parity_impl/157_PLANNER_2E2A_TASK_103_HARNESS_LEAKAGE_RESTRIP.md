# Planner Directive — Phase 2E2.A Task 103 Harness Leakage Restrip

## Context

The prior planner turn (file 156) correctly retired task 103 as
`superseded_by_evidence`. However, the harness materialized the
emitted bodies of the following two files with a trailing
`END_FILE: <path>` literal line inside the file content — confirmed
this turn via `tail -c 200 <path> | od -c`:

- `claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
  — last bytes
  `}\nEND_FILE: claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json\n`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md`
  — last bytes
  `..._BY_EVIDENCE\nEND_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md\n`

The trailing `END_FILE: <path>` literal is the documented
harness-emission leakage pattern that the codex watchdog lane has
been recovering for prior 2E2.A artifacts (147, 148, 149, 150, 153,
102) across twelve commits enumerated in directive 156. The leakage
is reintroduced any time a planner emit uses the `END_FILE: <path>`
form rather than the bare `END_FILE` form documented in task 103's
original step 11 sentence:

> Use bare `END_FILE` (no trailing path) only when emitting via the
> harness BEGIN_FILE/END_FILE protocol.

## Impact

For 156 the leakage is markdown-cosmetic only — the directive still
parses as readable markdown and the terminal marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TASK_103_SUPERSEDED_BY_EVIDENCE`
is still present.

For 103 the leakage is parse-breaking. The trailing
`END_FILE: <path>` line follows the closing `}` of the top-level JSON
object, so `python -c "import json; json.load(open('103.json'))"`
raises `json.decoder.JSONDecodeError: Extra data` and the supervisor's
task loader cannot parse 103. While 103 is loaded, the supervisor
cannot honor the `superseded_by_evidence` short-circuit at
`claude_worklog/tools/agent_supervisor.py:2331-2344`, and 102 cannot
be dispatched because the loader fails before reaching the dispatch
phase.

## Decision

This planner turn re-emits the three affected files with bare
`END_FILE` so the harness writes a clean body for each:

1. `claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
   — body content unchanged from the prior turn's intent (status
   `superseded_by_evidence`, supersede marker
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_RECOVERY_COMPLETED_BY_PRIOR_WATCHDOG_COMMITS`,
   empty `scope_dirty_paths` and `required_output_files`, sanitized
   prompt with no `LIVE_FORBIDDEN_PATTERNS` literal). Only difference
   versus the prior emission is the elimination of the trailing
   `END_FILE: <path>` line inside the file body. The closing `}` is
   now the absolute last non-empty line.
2. `claude_worklog/agent_supervisor/state/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
   — runtime state flipped from `blocked_approval` to
   `superseded_by_evidence`, history row appended with reason
   `planner-issued supersede: PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_RECOVERY_COMPLETED_BY_PRIOR_WATCHDOG_COMMITS; restrip turn re-emitted clean 103.json`,
   `last_status_change_ts` and `last_event_ts` set to
   `2026-05-05T13:00:00.000000+00:00`. The closing `}` is the
   absolute last non-empty line.
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md`
   — body content unchanged from the prior turn's intent. Only
   difference versus the prior emission is the elimination of the
   trailing `END_FILE: <path>` line. The terminal marker
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TASK_103_SUPERSEDED_BY_EVIDENCE`
   is now the absolute last non-empty line.

The dirty
`claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
is harness-managed inline-requirements accumulation and remains
untouched by this turn; the codex watchdog commits it on the next
cycle alongside the four files this turn emits.

## Forbidden under this directive

- modify `/home/wali/Desktop/AI BOT`
- modify any file under `v2/backend/app/` or `v2/backend/tests/` or
  `v2/frontend/`
- modify any file under `legacy_reference/`
- modify any prior-milestone artifact byte-content other than the
  three files enumerated above (and the modification on those three
  files is the trailing `END_FILE: <path>` line elision only)
- modify
  `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
- author any new task definition under
  `claude_worklog/agent_supervisor/tasks/` other than the three
  files enumerated above
- write or delete Redis keys
- restart any live service
- place or cancel exchange orders
- change leverage or margin
- enable live trading
- ship or release to production
- run a production migration
- expose or commit credential material
- approve the live gate

## Verification commands the next supervisor tick must run

1. `python -c "import json; obj = json.load(open('claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json')); print(obj['status'])"`
   — MUST print `superseded_by_evidence` with exit code 0.
2. `python -c "import json; obj = json.load(open('claude_worklog/agent_supervisor/state/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json')); print(obj['status'])"`
   — MUST print `superseded_by_evidence` with exit code 0.
3. `python -c "import json; obj = json.load(open('claude_worklog/agent_supervisor/tasks/102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json')); print(obj['status'])"`
   — MUST print `pending` with exit code 0.
4. `tail -c 200 claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json | od -c | tail -5`
   — MUST show the closing `}` followed by a single trailing newline
   and no `END_FILE:` literal.
5. `tail -c 200 claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md | od -c | tail -5`
   — MUST show
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TASK_103_SUPERSEDED_BY_EVIDENCE`
   followed by a single trailing newline and no `END_FILE:` literal.
6. `git status --short`
   — MUST show only paths inside this turn's emit set plus
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.

If any of (1)–(5) fails, the next supervisor tick must NOT commit;
the codex watchdog must restrip the offending file and retry.

## Next supervisor action

On the next reconciliation tick:

1. Verify the five `tail -c 200 | od -c` commands above all show no
   `END_FILE:` literal at the end of any of the three files.
2. Verify `python -m json.tool` passes for both 103.json files.
3. `git add` the four files this turn emits plus the dirty planner
   prompt accumulation, with one explicit `git add <path>` per path.
4. `git commit -m 'Codex watchdog 2E2A task 103 harness leakage restrip'`.
5. `git push origin master`.
6. With the working tree clean and 103 parseable as
   `superseded_by_evidence`, the supervisor short-circuits 103 and
   dispatches
   `102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`
   to local Codex CLI.

## Next planner action

The planner takes no further action this turn. The next planner turn
fires on
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` or
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` from task 102 (the
supervisor will write one of those markers to file 152). On PASS the
planner opens the next consolidated 2E2 sub-phase under a fresh
consolidated milestone turn (worker health observation collector
domain or worker health composition, picked by dependency order per
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md`). On FAIL with concrete
non-Rubric-12 blockers, surface to human attention; the planner does
not chain a second addendum layer.

## Safety review

- live behavior: none observed
- Redis read access: none observed
- Redis mutation access: none observed
- Redis commands: none observed
- legacy mutation: none observed
- release intent: none observed
- credential-shaped strings: none observed
- URL logging: none observed
- exchange action: none observed
- leverage or margin change: none observed
- production rollout: none observed
- secret leakage: none observed
- v2/ source modification: none observed
- v2/ test modification: none observed
- prior-milestone byte-content modification beyond the trailing
  `END_FILE: <path>` line elision: none observed
- FastAPI lifespan or router or background task addition: none observed
- module-level singleton or cache or lock addition: none observed
- wall-clock helper call addition: none observed

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TASK_103_HARNESS_LEAKAGE_RESTRIP_READY
