# Phase 2E1.C.δ — Safety Boundaries

This sub-phase is L1 non-live domain authoring. The boundaries below
are binding for both Claude (implementer) and Codex (reviewer/autofix)
on this sub-phase.

## Allowed paths (write)

- `v2/backend/app/domain/trainer_liveness_composition/`
- `v2/backend/tests/unit/domain/trainer_liveness_composition/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  (status reports only; specifically files 84 and 85 for the
  implementer, files 86 and 87 for the Codex reviewer).

## Forbidden paths (write)

- `/home/wali/Desktop/AI BOT/` (legacy bot root). Never modify.
- `v2/backend/app/domain/trainer_liveness/` (α — read-only this sub-phase).
- `v2/backend/app/domain/liveness_stream_growth/` (β — read-only this sub-phase).
- `v2/backend/app/adapters/`, `v2/backend/app/services/`,
  `v2/backend/app/api/`, `v2/backend/app/main.py`.
- Anything under `v2/frontend/`.
- Any `.env` or secrets file.
- Older planner directives under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  (anything other than 84 and 85 for the implementer, 86 and 87 for
  Codex reviewer). Older files are out of scope.

## Forbidden actions

- Place or cancel exchange orders.
- Change leverage or margin.
- Read or write Redis (no Redis client may be imported).
- Restart any live service (trainer, trader, orchestrator, Redis,
  VPN, monitor).
- Call subprocess.
- Open network sockets.
- Import legacy modules under `legacy_reference/` or
  `/home/wali/Desktop/AI BOT/`.
- Read system clock (`time.time`, `datetime.now`,
  `datetime.utcnow`); the now-cursor is an injected integer.
- Enable final-live mode.
- Deploy.
- Run production migrations.
- Expose or commit secrets.
- Modify the master planner prompt
  (`claude_worklog/autonomous_control_plane/`) from this sub-phase.

## Allowed subprocesses (implementer only)

- `python -m py_compile <authored .py file>`.
- `python -m pytest v2/backend/tests/unit/domain/trainer_liveness_composition/`.
- `python -m pytest` for cross-isolation re-runs of the α and β
  test trees explicitly listed in the test plan.
- `rg` and `grep` for the forbidden-token / END_FILE leak self-checks
  scoped per the test plan.
- `git status -s` for the cross-isolation regression proof. No `git
  add`, `git commit`, or `git push` from the implementer; the
  supervisor handles commits.

## Stop conditions

The implementer MUST stop and emit
`PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED` to the GO/NO-GO file
if any of:

- forbidden token returns a non-zero hit;
- `END_FILE:` marker leaks into a δ source or test file, or into the
  implementer-authored status files 84 / 85;
- pytest reports any failure or error;
- py_compile fails on any authored file;
- α or β cross-isolation re-run fails;
- the δ author would need to modify any file under α or β;
- a write attempt targets a path outside the allowed list;
- any secret-shaped string appears in the diff;
- the implementer detects a request that would violate the
  forbidden-actions list above.

## Live-trading status

FINAL LIVE GATE: BLOCKED. No δ artifact may change this.

PHASE2E1C_DELTA_SAFETY_BOUNDARIES_READY
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/82_PHASE_2E1C_DELTA_SAFETY_BOUNDARIES.md
