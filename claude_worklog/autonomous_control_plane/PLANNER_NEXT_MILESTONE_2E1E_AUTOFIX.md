# Planner Next Milestone — 2E1.E Composition Root Autofix

## Context

Phase 2E1.E composition root reached implementation+validation PASS at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md`
(`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`),
but Codex review 097 returned FAIL at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/132_2E1E_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
(`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_FAIL`).

The Codex review report at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/131_2E1E_COMPOSITION_ROOT_CODEX_REVIEW.md`
enumerates two concrete non-live blockers under 'Concrete blockers'
and an all-clean 'Safety review' (every safety row marked 'none
observed'). All composition source files (`__init__.py` package
markers, `errors.py`, `runtime.py`) and 23 of the 25 authored test
files are unaffected by the blockers.

## Concrete blockers from 131

### Blocker A — rubric items 8 and 9

`v2/backend/tests/unit/composition/trainer_parity/test_composition_milestone_forbidden_tokens.py`
lines 33-34 are currently:

```
        "datetime" + ".datetime.now(",
        "datetime" + ".datetime.utcnow(",
```

The static substrings `.datetime.now(` and `.datetime.utcnow(`
contain the literal forbidden contiguous sequences `datetime.now(`
and `datetime.utcnow(`. Codex's external
`rg --fixed-strings --case-sensitive 'datetime.now('` and
`rg --fixed-strings --case-sensitive 'datetime.utcnow('` therefore
finds those literals inside the guard test source itself, violating
the 125 forbidden-token contract for the test file.

The runtime guard test passes only because the guard excludes itself
from its own scan (lines 11-16 filter out
`test_composition_milestone_forbidden_tokens.py`). The contract is
that the source text of every test file under the milestone directory
must not contain the forbidden contiguous substring; the guard's
self-exclusion does not satisfy the rubric.

### Blocker B — rubric item 24

`v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_both_kwargs.py`
line 10 is currently:

```
    env = {"V2_REDIS_URL": "redis://env:6379/0"}
```

The required canonical placeholder shape is `redis://h:6379/0`. The
non-canonical shape `redis://env:6379/0` is non-credential and
non-live but does not match the rubric placeholder requirement.

## Why both blockers fall in the autofix path

Both blockers are confined to the 25 authored test files (in fact
only 2 of them) under
`v2/backend/tests/unit/composition/trainer_parity/`. Zero composition
source change is required (`v2/backend/app/composition/` is untouched
by the autofix). Zero prior-milestone touch is required
(`v2/backend/app/services/`, `v2/backend/app/adapters/`,
`v2/backend/app/domain/`, and the corresponding test trees remain
byte-identical). Zero new test file is created. The 131 'Safety
review' confirms zero live behavior, zero Redis access, zero Redis
command, zero legacy mutation, zero release intent, zero secret leak,
zero URL logging, zero prior-milestone modification, zero url_env
import, zero FastAPI lifespan registration, zero module-level
singleton, and zero wall-clock helper use.

The remediation therefore matches the REQ_0007 / REQ_0014 autofix
path exactly: concrete non-safety blockers, narrow scope confined to
the milestone's own authored test files, and explicit prior-milestone
isolation already proven by 131 rubric rows 19, 21, 22, and 23.

## Module-location decision

The autofix touches only test files under
`v2/backend/tests/unit/composition/trainer_parity/`. No new package,
module, or file is introduced. No `app/` source is modified. The
composition root assembly remains byte-identical at
`v2/backend/app/composition/__init__.py`,
`v2/backend/app/composition/trainer_parity/__init__.py`,
`v2/backend/app/composition/trainer_parity/errors.py`, and
`v2/backend/app/composition/trainer_parity/runtime.py`.

## Why consolidated rather than split

Per the Claude Code Max20 consolidated-default profile and the prior
2E1.D autofix precedent (094/095), the autofix is dispatched as ONE
remediation+validation task (098) plus ONE Codex re-review task
(099). The remediation surface is two test files and four lines of
edit total. There is no plausible split fallback, since splitting one
test file from another would not reduce risk; both edits are
independent and trivial. If 098 returns FAIL with concrete
non-safety blockers, the planner does NOT chain a second autofix
layer (per 094/095 precedent and the autofix prompt stop conditions);
the failure is surfaced to human attention.

## Files emitted by the autofix milestone

Authored by the supervisor task 098 (Codex autofix):

- v2/backend/tests/unit/composition/trainer_parity/test_composition_milestone_forbidden_tokens.py (2-line edit at lines 33-34)
- v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_both_kwargs.py (1-line edit at line 10)
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/136_2E1E_AUTOFIX_REPORT.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/137_2E1E_AUTOFIX_GO_NO_GO.md

Authored by the supervisor task 099 (Codex re-review after autofix):

- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/138_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md

The planner does NOT author a separate autofix spec, safety
boundaries, or GO/NO-GO request document; per the 2E1.D autofix
precedent (no spec/safety/request authored for 094/095), the autofix
contract is encoded directly in the 098 task prompt.

## Codex parallel lane status during this milestone

After the supervisor commits this turn's planner artifacts, the
working tree returns to clean (only the supervisor's prior-existing
prompt-file modification persists). With the dirty tree resolved, the
Codex parallel lane may continue read-only review of older committed
trainer 2E1.A / 2E1.B / 2E1.C artifacts under
`v2/backend/app/services/trainer_parity/`,
`v2/backend/tests/unit/services/trainer_parity/`,
`v2/backend/app/adapters/redis_v2/`, or
`v2/backend/app/domain/trainer_liveness*`. Codex parallel review MUST
NOT touch
`v2/backend/tests/unit/composition/trainer_parity/test_composition_milestone_forbidden_tokens.py`,
`v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_both_kwargs.py`,
or any file under `v2/backend/app/composition/` while 098 is active;
that surface is exclusively the property of the active Codex autofix
child.

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
- No prior-milestone trainer-parity source or test file is touched
  by either 098 or 099 (forbidden_output_paths enforced).
- No file under `v2/backend/app/composition/`,
  `v2/backend/app/services/`, `v2/backend/app/adapters/`,
  `v2/backend/app/domain/`, `v2/frontend/`,
  `claude_worklog/security/`, or `claude_worklog/requirements_inbox/`
  is touched by 098 or 099.

## Next planner turn trigger

The planner re-fires after one of:

- 098 emits
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_AUTOFIX_PASSED` in 137
  (continue dispatch chain to 099).
- 098 emits
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_AUTOFIX_FAILED` in 137
  with concrete non-safety blockers (surface to human attention; no
  second autofix layer).
- 099 emits
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS` in 139
  (close Phase 2E1, open the next REQ_0006 sub-phase under a fresh
  consolidated milestone turn).
- 099 emits
  `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_FAIL` in 139 with
  concrete non-safety blockers (surface to human attention; no second
  autofix layer).
- A safety stop or human-attention condition is detected.

PHASE2E1E_PLANNER_NEXT_MILESTONE_AUTOFIX_READY
