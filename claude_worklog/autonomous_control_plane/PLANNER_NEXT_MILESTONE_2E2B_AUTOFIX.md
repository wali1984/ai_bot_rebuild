# Planner Next Milestone — 2E2.B Worker Health Service Autofix

## Context

Phase 2E2.B worker health service reached implementation+validation
PASS at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md`
(`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_PASSED`),
but Codex review 105 returned FAIL at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/165_2E2B_WORKER_HEALTH_SERVICE_CODEX_GO_NO_GO.md`
(`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_FAIL`).

The Codex review report at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/164_2E2B_WORKER_HEALTH_SERVICE_CODEX_REVIEW.md`
enumerates two concrete non-live blockers under 'Concrete blockers'
and an all-clean 'Safety review' (every safety row marked 'none
observed'). All three authored source files
(`__init__.py`, `errors.py`, `service.py`) under
`v2/backend/app/services/trainer_worker_health/` and 20 of the 22
authored test files plus the package marker are unaffected by the
blockers.

## Concrete blockers from 164

### Blocker 6 — rubric item 6

`v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_redis.py`
constructs the runtime literal `prefix = "red" + "is"` and asserts
the post-reimport `sys.modules` invariant, but does NOT scan the
three authored source files
(`v2/backend/app/services/trainer_worker_health/__init__.py`,
`errors.py`, `service.py`) for the runtime-assembled forbidden
literal. The 105 review rubric (row 6) requires the source-file
scan in addition to the `sys.modules` invariant.

### Blocker 7 — rubric item 7

`v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_url_env.py`
constructs the runtime literal `marker = "url" + "_env"` and asserts
the post-reimport `sys.modules` invariant, but does NOT scan the
three authored source files for the runtime-assembled forbidden
literal. The 105 review rubric (row 7) requires the source-file
scan in addition to the `sys.modules` invariant.

## Why both blockers fall in the autofix path

Both blockers are confined to two of the 22 authored test files
under
`v2/backend/tests/unit/services/trainer_worker_health/`. Zero
service source change is required
(`v2/backend/app/services/trainer_worker_health/` is byte-identical
through the autofix). Zero prior-milestone touch is required
(`v2/backend/app/services/trainer_parity/`,
`v2/backend/app/composition/trainer_parity/`,
`v2/backend/app/domain/trainer_worker_health/`,
`v2/backend/app/domain/trainer_liveness/`, and
`v2/backend/app/adapters/redis_v2/` all remain byte-identical).
Zero new test file is created. The 164 'Safety review' confirms
zero live behavior, zero Redis access, zero Redis command, zero
legacy mutation, zero release intent, zero secret leak, zero URL
logging, zero prior-milestone modification, zero `url_env` import,
zero FastAPI lifespan registration, zero module-level singleton,
zero wall-clock helper use, zero logging or stdout call, zero
`os.environ` read, zero subprocess, zero socket, and zero direct
redis import.

The remediation therefore matches the REQ_0007 / REQ_0014 autofix
path exactly: concrete non-safety blockers, narrow scope confined
to the milestone's own authored test files, and explicit
prior-milestone isolation already proven by 164 rubric rows 12,
14, and 16.

## Module-location decision

The autofix touches only two test files under
`v2/backend/tests/unit/services/trainer_worker_health/`. No new
package, module, or file is introduced. No `app/` source is
modified. The worker-health service surface remains byte-identical
at `v2/backend/app/services/trainer_worker_health/__init__.py`,
`v2/backend/app/services/trainer_worker_health/errors.py`, and
`v2/backend/app/services/trainer_worker_health/service.py`.

## Why consolidated rather than split

Per the Claude Code Max20 consolidated-default profile and the
prior 2E1.D (094/095) and 2E1.E (098/099) autofix precedents, the
autofix is dispatched as ONE remediation+validation task (106) plus
ONE Codex re-review task (107). The remediation surface is two
test files and a small, self-contained insert per file. There is
no plausible split fallback; splitting one test file from another
would not reduce risk; both edits are independent and trivial. If
106 returns FAIL with concrete non-safety blockers, the planner
does NOT chain a second autofix layer (per 094/095 and 098/099
precedent and the autofix prompt stop conditions); the failure is
surfaced to human attention.

## Files emitted by the autofix milestone

Authored by the supervisor task 106 (Codex autofix):

- v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_redis.py (insert source-file scan after `prefix = "red" + "is"` and before sys.modules purge)
- v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_url_env.py (insert source-file scan after `marker = "url" + "_env"` and before `blocked_prefix`)
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/166_2E2B_AUTOFIX_REPORT.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/167_2E2B_AUTOFIX_GO_NO_GO.md

Authored by the supervisor task 107 (Codex re-review after autofix):

- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/168_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md

The planner does NOT author a separate autofix spec, safety
boundaries, or GO/NO-GO request document; per the 098/099 autofix
precedent, the autofix contract is encoded directly in the 106
task prompt.

## Codex parallel lane status during this milestone

After the supervisor commits this turn's planner artifacts, the
working tree returns to clean (only the supervisor's prior-existing
prompt-file modification persists, which the watchdog handles).
With the dirty tree resolved, the Codex parallel lane may continue
read-only review of older committed trainer 2E1.A / 2E1.B / 2E1.C
artifacts under `v2/backend/app/services/trainer_parity/`,
`v2/backend/tests/unit/services/trainer_parity/`,
`v2/backend/app/adapters/redis_v2/`,
`v2/backend/app/composition/trainer_parity/`, or
`v2/backend/app/domain/trainer_liveness*` and 2E2.A artifacts under
`v2/backend/app/domain/trainer_worker_health/`. Codex parallel
review MUST NOT touch
`v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_redis.py`,
`v2/backend/tests/unit/services/trainer_worker_health/test_init_module_does_not_load_url_env.py`,
or any file under
`v2/backend/app/services/trainer_worker_health/` while 106 is
active; that surface is exclusively the property of the active
Codex autofix child.

## Hard stops not triggered

- No legacy mutation (`/home/wali/Desktop/AI BOT` untouched).
- No Redis read or write.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.
- All emitted-by-planner writes are inside the planner's allowed
  materializer prefixes
  (`claude_worklog/agent_supervisor/tasks/` and
  `claude_worklog/autonomous_control_plane/`).
- No prior-milestone trainer-parity, trainer-liveness, or
  worker-health-domain source or test file is touched by either
  106 or 107 (forbidden_output_paths enforced).
- No file under `v2/backend/app/services/trainer_worker_health/`,
  `v2/backend/app/composition/`, `v2/backend/app/adapters/`,
  `v2/backend/app/domain/`, `v2/backend/app/api/`,
  `v2/backend/app/cli/`, `v2/backend/app/jobs/`,
  `v2/backend/app/main.py`, `v2/frontend/`,
  `claude_worklog/security/`, or
  `claude_worklog/requirements_inbox/` is touched by 106 or 107.

## Next planner turn trigger

The planner re-fires after one of:

- 106 emits
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_AUTOFIX_PASSED` in 167
  (continue dispatch chain to 107).
- 106 emits
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_AUTOFIX_FAILED` in 167
  with concrete non-safety blockers (surface to human attention;
  no second autofix layer).
- 107 emits
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS` in 169
  (close Phase 2E2.B and open the next REQ_0006 sub-phase
  Phase 2E2.C — worker health composition root — under a fresh
  consolidated milestone turn).
- 107 emits
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_FAIL` in 169 with
  concrete non-safety blockers (surface to human attention; no
  second autofix layer).
- A safety stop or human-attention condition is detected.

PHASE2E2B_PLANNER_NEXT_MILESTONE_AUTOFIX_READY
