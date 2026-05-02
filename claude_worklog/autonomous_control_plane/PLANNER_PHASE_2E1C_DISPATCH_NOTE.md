# Planner Dispatch Note — Phase 2E1.C.α

## Active requirement

`REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE`.

## State of the trainer parity service rebuild as of 2026-05-02

| Phase | Subject | Latest marker | File |
| --- | --- | --- | --- |
| 2E (plan) | Trainer GPU parity plan | `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS` | `trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md` |
| 2E1.A | Subprocess adapter foundation | `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md` |
| 2E1.B | Trainer output contract / domain records | `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS` | `trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md` |
| 2E1.B (validation) | Local pytest validation | `PHASE2E1B_LOCAL_VALIDATION_PASSED` | `trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md` |

The 2E1.B impl tree is therefore Codex-passed and locally validated.

## Stale task auto-stalled

`tasks/059_trainer_parity_2e1b_endfile_marker_remediation.json` declares a
predecessor marker of `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED`. The actual
marker in `32_2E1B_GO_NO_GO.md` reads
`PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`. The supervisor
cannot dispatch task 059. No planner action is required to retire it; it
is auto-blocked and may be archived in a later hygiene sweep. The
remediation it describes was already executed inline by the implementer
of task 056 before validation passed.

## Chosen next non-live milestone

**Phase 2E1.C.α — Trainer Internal Liveness Monitor — DOMAIN LAYER ONLY.**

Pure-Python value objects, evaluator function, and unit tests. No Redis
client, no subprocess call, no legacy import, no GPU code, no I/O, no
clock reads. Mirrors the 2E1.B authoring shape exactly.

The full 2E1.C track decomposes as:

| Sub-phase | Subject | Layer |
| --- | --- | --- |
| 2E1.C.α | Liveness signal/SLA/alert dataclasses + pure evaluator | domain |
| 2E1.C.β | Read-only Redis stream-id growth probe (no write) | adapter |
| 2E1.C.γ | Subprocess-adapter liveness probe (uses 2E1.A) | adapter |
| 2E1.C.δ | Service composition + health endpoint stub | service |
| 2E1.C.ε | Validation-evidence-packet authoring run | validation |

This dispatch note covers 2E1.C.α only. β through ε are deferred until α
is Codex-passed and locally validated, matching the cadence used for
2E1.A and 2E1.B.

## Source of truth for 2E1.C.α scope

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`
  ("Required signals", "Required alert", "Out-of-band requirements").
- `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`
  (referenced by 05 spec).
- Architectural pattern from 2E1.B
  (`26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`).

## Hard exclusions for 2E1.C.α (mirrors 2E1.B)

- No Redis client, no `redis`/`aioredis`/`redis.asyncio` import.
- No `subprocess`, `os.system`, `os.popen`, `pty`, `socket`.
- No network: no `urllib`, `requests`, `httpx`, `aiohttp`.
- No GPU code: no `torch`, `tensorflow`, `cuda`.
- No `numpy.random`.
- No legacy import: no `legacy_reference.*`, no path injection.
- No environment variable reads.
- No reliance on `time.time()` / `datetime.now()` / `datetime.utcnow()`
  inside module body. `now_ms` is an int argument to the evaluator.
- No async I/O. Domain layer is fully synchronous.
- No reliance on the subprocess adapter from 2E1.A (the evaluator
  receives a pre-built snapshot; the adapter probe lives in 2E1.C.γ).
- No live trainer call.
- No Redis write. (V2 emission to `V2_REDIS_PREFIX` is deferred per
  05 spec "Out-of-band requirements".)

## END_FILE marker authoring discipline (carried forward from 2E1.B)

Phase 2E1.C.α implementer MUST use the `Write` tool to author each
Python source file and test file. Implementer MUST NOT emit Python
files via `BEGIN_FILE` / `END_FILE` blocks. The harness has a known
defect that materializes the trailing `END_FILE: <path>` marker as
bare top-level text inside the Python file, producing a `SyntaxError`
at compile time. Worklog `*.md` and `tasks/*.json` files MAY use
`BEGIN_FILE` / `END_FILE` because Markdown / JSON parsers tolerate (or
reject in JSON's case explicitly visible) the stray marker — the
implementer's local validation step will catch any leak in JSON.

## Dispatch chain

1. `tasks/060_trainer_parity_2e1c_alpha_implementation.json`
   (predecessor: `PHASE2E1B_LOCAL_VALIDATION_PASSED`).
2. `tasks/061_trainer_parity_2e1c_alpha_local_validation.json`
   (predecessor: `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`).
3. `tasks/062_trainer_parity_2e1c_alpha_codex_review.json`
   (predecessor: `PHASE2E1C_ALPHA_LOCAL_VALIDATION_PASSED`).

PLANNER_PHASE_2E1C_DISPATCH_NOTE_RECORDED
