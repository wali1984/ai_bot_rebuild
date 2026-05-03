# Phase 2E1.C.β — Safety Boundaries

## Allowed write scope

The 2E1.C.β implementer may write **only** under:

- `v2/backend/app/domain/liveness_stream_growth/` (new package).
- `v2/backend/tests/unit/domain/liveness_stream_growth/` (new tests).
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
  (the implementation report, validation log, GO/NO-GO files).

Any write outside this list is a hard fail. The supervisor MUST refuse
to commit any diff outside the allowed prefix.

## Forbidden mutations

- Any change under `/home/wali/Desktop/AI BOT/`.
- Any change under `legacy_reference/`.
- Any change under `v2/backend/app/domain/trainer_liveness/`
  (the α package). β does not modify α.
- Any change under `v2/backend/app/domain/trainer_parity/`
  (the 2E1.B package). β does not modify 2E1.B.
- Any change under `v2/backend/app/adapters/trainer/`
  (the 2E1.A subprocess adapter). β does not modify 2E1.A.
- Any change to `.env`, `secrets/`, or any file matched by the
  configured secret-scan patterns.
- Any modification to existing supervisor task definitions for
  predecessor sub-phases (060–062, 063).

## Forbidden runtime behavior

- No live trading enable. `LIVE TRADING: BLOCKED` semantics MUST
  remain unchanged.
- No Redis client construction. No Redis read. No Redis write.
- No exchange API call.
- No subprocess invocation other than pytest, py_compile, and
  text-search tools.
- No legacy module import.
- No legacy venv use.
- No GPU code path. No CUDA init.
- No `time.time()`, `datetime.now()`, `datetime.utcnow()` clock read
  inside the β source. Tests MAY use `pytest.MonkeyPatch` to inject a
  fake clock value into a *test fixture*, but MUST NOT call real-clock
  APIs from the β package itself.
- No async / `asyncio`.
- No network access (no `socket`, `urllib`, `requests`, `httpx`).
- No file system I/O from β source or β tests.
- No environment variable reads from β source.
- No `time.sleep()` from β source or β tests.

## Forbidden artifacts

- No emission to V2 Redis namespace. β returns an `int` in process.
- No emission of `LIVENESS_ALERT_CODE` from β. β does not even import α.
- No persistence layer. β is stateless.
- No `XLEN` / `xlen` literal in source (per liveness fix spec
  out-of-band requirement).
- No `END_FILE:` marker leak inside any authored Python file. Refer
  to the 2E1.B regression report
  (`trainer_gpu_parity_impl/39_PHASE_2E1B_END_FILE_MARKER_REMEDIATION_REQUEST.md`)
  and the 21_SUPERVISOR_TASK_HARNESS_FORMAT_FIX_NOTE for context.

## Required artifacts

- The β package source files exactly as enumerated in
  `52_PHASE_2E1C_BETA_GROWTH_WINDOW_SPEC.md` "Surface to create".
- The β test files exactly as enumerated in
  `53_PHASE_2E1C_BETA_TEST_PLAN.md` "Test files".
- An implementation report at
  `trainer_gpu_parity_impl/57_2E1C_BETA_IMPLEMENTATION_REPORT.md`.
- A validation run-log at
  `trainer_gpu_parity_impl/59_2E1C_BETA_VALIDATION_RUN_LOG.md`.
- A validation GO/NO-GO at
  `trainer_gpu_parity_impl/58_2E1C_BETA_VALIDATION_GO_NO_GO.md`.
- A Codex review at
  `trainer_gpu_parity_impl/60_2E1C_BETA_CODEX_REVIEW.md`.
- A Codex GO/NO-GO at
  `trainer_gpu_parity_impl/61_2E1C_BETA_CODEX_GO_NO_GO.md`.

(File numbering: 56 reserved for the implementation GO/NO-GO request
the implementer emits at hand-off; 57 is the implementation report;
58 is validation GO/NO-GO; 59 is validation run-log; 60 is Codex
review; 61 is Codex GO/NO-GO. The supervisor materializes these in
order.)

## Stop conditions

The β implementer halts immediately on any of:

- a forbidden token leak detected during self-grep;
- a write attempt outside the allowed prefix;
- a `python -m py_compile` failure on any β file;
- any directive that would require Redis, subprocess (beyond pytest /
  py_compile / grep), network, GPU, legacy import, deployment, or
  live behavior;
- any directive that requires modifying α, 2E1.B, or 2E1.A;
- any `END_FILE:` marker leak in an authored Python file;
- any pre-existing Codex finding from α that would block the joining
  composition (β still proceeds, but flags the finding for δ).

## Live-trading status

LIVE TRADING: BLOCKED. No phase 2E1.C.β artifact may change this.

PHASE2E1C_BETA_TRAINER_LIVENESS_SAFETY_BOUNDARIES_READY
