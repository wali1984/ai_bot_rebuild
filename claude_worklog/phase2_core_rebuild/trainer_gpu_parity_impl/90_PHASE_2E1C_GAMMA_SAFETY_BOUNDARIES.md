# Phase 2E1.C.γ — Safety Boundaries

This sub-phase is L1 non-live domain authoring. The boundaries below
are binding for both Claude (implementer) and Codex (reviewer /
autofix) on this sub-phase.

## Allowed paths (write)

- `v2/backend/app/domain/trainer_liveness_observation_collector/`
- `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  (status reports only; specifically files 92 and 93 for the
  implementer, files 94 and 95 for the Codex reviewer).

## Forbidden paths (write)

- `/home/wali/Desktop/AI BOT/` (legacy bot root). Never modify.
- `v2/backend/app/domain/trainer_liveness/` (α — read-only this sub-phase).
- `v2/backend/app/domain/liveness_stream_growth/` (β — read-only this sub-phase).
- `v2/backend/app/domain/trainer_liveness_composition/` (δ — read-only this sub-phase).
- `v2/backend/app/adapters/`, `v2/backend/app/services/`,
  `v2/backend/app/api/`, `v2/backend/app/cli/`,
  `v2/backend/app/jobs/`, `v2/backend/app/main.py`.
- Anything under `v2/frontend/`.
- Any `.env` or secrets file.
- Older planner directives under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  (anything other than 92 and 93 for the implementer, 94 and 95 for
  the Codex reviewer). Older files are out of scope.
- `claude_worklog/autonomous_control_plane/` (master planner prompt
  is owned by the planner role only; sub-phase tasks MUST NOT
  modify it).

## Forbidden actions

- Place or cancel exchange orders.
- Change leverage or margin.
- Read or write Redis (no Redis client may be imported; the γ
  Reader port is a structural Protocol with no transport binding,
  and the in-memory fake is the only γ-owned implementation).
- Restart any live service (trainer, trader, orchestrator, Redis,
  VPN, monitor).
- Call subprocess (other than the explicitly allowed validation
  subprocesses listed below).
- Open network sockets.
- Import legacy modules under `legacy_reference/` or
  `/home/wali/Desktop/AI BOT/`.
- Read system clock (`time.time`, `time.monotonic`,
  `datetime.now`, `datetime.utcnow`); the now-cursor is an injected
  `Callable[[], int]`.
- Enable final-live mode.
- Deploy.
- Run production migrations.
- Expose or commit secrets.
- Modify the master planner prompt
  (`claude_worklog/autonomous_control_plane/`) from this sub-phase.
- Run `git add`, `git commit`, or `git push`; the supervisor handles
  commits after `92_2E1C_GAMMA_GO_NO_GO.md` records
  `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`.

## Allowed subprocesses (implementer only)

- `python -m py_compile <authored .py file>`.
- `python -m pytest v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`.
- `python -m pytest` for cross-isolation re-runs of the α, β, and
  δ test trees explicitly listed in the test plan.
- `rg` and `grep` for the forbidden-token / END_FILE leak
  self-checks scoped per the test plan.
- `git status -s` for the cross-isolation regression proof.

## Stop conditions

The implementer MUST stop and emit
`PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_BLOCKED` to the GO/NO-GO file
if any of:

- a forbidden token returns a non-zero hit;
- an `END_FILE:` marker leaks into a γ source or test file, or into
  the implementer-authored status files 92 / 93;
- pytest reports any failure or error;
- `py_compile` fails on any authored file;
- α, β, or δ cross-isolation re-run fails;
- the γ author would need to modify any file under α, β, or δ;
- a write attempt targets a path outside the allowed list;
- any secret-shaped string appears in the diff;
- the implementer detects a request that would violate the
  forbidden-actions list above.

## Live-trading status

FINAL LIVE GATE: BLOCKED. No γ artifact may change this.

PHASE2E1C_GAMMA_SAFETY_BOUNDARIES_READY
