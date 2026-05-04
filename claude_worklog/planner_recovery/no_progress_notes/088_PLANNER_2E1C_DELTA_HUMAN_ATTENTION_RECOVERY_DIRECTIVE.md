# Planner Directive — 2E1.C.δ Human-Attention Recovery via Codex (REQ_0014)

## Trigger

Task `079_trainer_parity_2e1c_delta_implementation` (Claude implementer) exited
`human_attention_required` at `2026-05-04T05:26:56Z`. The supervisor
`summary.json` records `attention_reason = "max_attempts 3 exhausted; last
reason: task_failed"` and `materialized_files = []`. The 079 `stdout.txt`
documents the root cause as a Claude harness write-permission block on the new
δ source/test directory subtrees:

- `v2/backend/app/domain/trainer_liveness_composition/`
- `v2/backend/tests/unit/domain/trainer_liveness_composition/`

No δ source, test, or 84/85 marker file was authored. The 080 Codex review task
remains pending and is gated behind
`PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` in
`84_2E1C_DELTA_GO_NO_GO.md`, which does not yet exist.

## Classification

This is a **non-live, recoverable harness emit-permission failure**, not a
spec / safety / Codex blocker. The δ specs (80/81/82/83) and predecessor
codex passes (alpha 53, beta 69) are all in place. The δ work is purely
in-process domain code with zero Redis, network, subprocess, clock, or legacy
imports. No live or legacy mutation is required to complete it.

## Authority invoked

REQ_0014 — *Codex Autonomous Recovery for Non-Live Human Attention*. Codex has
explicit authority to inspect `human_attention_required` state, patch
implementation code, run local validation, and emit recovery artifacts inside
allowed non-live paths. The same authority was exercised successfully for the
064 → 076 recovery on `2026-05-03T23:45:49Z`.

## Decision

Dispatch a single consolidated Codex autonomous-recovery task,
`081_codex_recover_079_human_attention.json`, that:

1. Reads specs 80/81/82/83 and the α/β read-only public surfaces.
2. Authors the four δ source files and sixteen δ test files at the
   canonical paths the 079 task originally listed in `required_output_files`.
3. Runs the forbidden-token grep, END_FILE leak self-check, `py_compile`,
   δ pytest, and α+β cross-isolation regression gates documented in spec 81.
4. Emits `84_2E1C_DELTA_GO_NO_GO.md` with the canonical
   `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED` marker (or
   `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED` on any gate failure) so
   that the already-defined 080 Codex review task's predecessor marker is
   satisfied without authoring a new gating chain.
5. Emits `85_2E1C_DELTA_IMPLEMENTATION_REPORT.md` with full evidence rows.
6. Emits `081_CODEX_RECOVERY_079_REPORT.md` and
   `081_CODEX_RECOVERY_079_GO_NO_GO.md` as the recovery audit trail.

The recovery task does **not** dispatch 080 itself; the supervisor commits the
recovery artifacts and 080 fires under its existing predecessor-marker gate.

## Hard safety reaffirmed

- LIVE TRADING: BLOCKED.
- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis read or write.
- No subprocess other than the documented `pytest`, `python -m py_compile`,
  `python -c`, `git status -s`, `rg`, and `grep`.
- No network, no clock, no legacy import, no `.env` access.
- No L4/L5 action, no live approval, no deployment, no production migration.
- No secret-shaped string in any authored file.
- No modification of the α (`trainer_liveness/`) or β
  (`liveness_stream_growth/`) packages.
- No modification of `v2/backend/app/adapters/`, `services/`, `api/`, or
  `main.py`.
- No modification of the master planner prompt under
  `claude_worklog/autonomous_control_plane/`.

## Continuation map

- On `CODEX_079_HUMAN_ATTENTION_RECOVERY_READY` **and**
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED`: supervisor
  commits the δ artifacts and dispatches
  `080_trainer_parity_2e1c_delta_codex_review.json` under its existing
  predecessor-marker gate. On 080 PASS the planner opens 2E1.C.γ
  (read-only Redis observation collector) under a fresh spec turn.
- On `CODEX_079_HUMAN_ATTENTION_RECOVERY_BLOCKED`: supervisor leaves an
  explicit blocker; no retry without a fresh planner directive turn.
- On `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_BLOCKED` with recovery READY: a
  separate REQ_0007/REQ_0014 autofix task scoped to the δ package only is
  authorized; α and β remain untouched.

## Evidence pointers

- `claude_worklog/agent_supervisor/runs/079_trainer_parity_2e1c_delta_implementation/summary.json`
- `claude_worklog/agent_supervisor/runs/079_trainer_parity_2e1c_delta_implementation/stdout.txt`
- `claude_worklog/agent_supervisor/tasks/079_trainer_parity_2e1c_delta_implementation.json`
- `claude_worklog/agent_supervisor/tasks/080_trainer_parity_2e1c_delta_codex_review.json`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/076_CODEX_RECOVERY_064_GO_NO_GO.md` (precedent: `CODEX_064_HUMAN_ATTENTION_RECOVERY_READY`)
- `claude_worklog/requirements_inbox/REQ_0014_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY.md`

PHASE2E1C_DELTA_HUMAN_ATTENTION_RECOVERY_DIRECTIVE_READY
