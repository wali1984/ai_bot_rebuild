# Planner Turn — 2E2.A Open Trainer Worker Health Domain

## Turn date

2026-05-04

## Active requirement

REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md

## Predecessor closure (Phase 2E1 fully closed)

Phase 2E1.E composition root closed PASS at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`
with marker
`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`. With that
marker the trainer-liveness assembly stack is fully wired end-to-end:

- 2E1.A subprocess adapter — Codex PASS (22).
- 2E1.B trainer output contract dataclasses — Codex PASS (34).
- 2E1.C.alpha liveness signal snapshot — Codex PASS (53).
- 2E1.C.beta stream-id growth domain — Codex PASS (69).
- 2E1.C.gamma observation collector — Codex PASS (95).
- 2E1.C.gamma.real Redis reader — Codex PASS (103).
- 2E1.C.gamma.real factory — Codex PASS (111).
- 2E1.C.delta snapshot composition — Codex PASS (87).
- 2E1.D trainer parity service composition (post-autofix) — Codex PASS (124).
- 2E1.E trainer parity composition root (post-autofix) — Codex PASS (139).

Phase 2E1 is closed.

## Active milestone selected for this turn

Phase 2E2.A — Trainer Worker Health Domain. This is the first
sub-phase of the second REQ_0006 milestone group ("trainer prediction
worker health"). Per the Claude Code Max20 consolidated-default
profile, "trainer prediction worker health as one task" describes the
group; the planner stages the group as 2E2.A (domain), 2E2.B (service),
2E2.C (composition root), each as its own consolidated implementation
task plus one Codex review task. 2E2.A is opened first.

## Why this milestone next, and why pure-domain first

REQ_0006 calls for prediction worker health metrics in addition to
the binary liveness alert already produced by Phase 2E1. The 2E1
evaluator returns a single boolean alert and a flat reasons tuple.
The application layer (and downstream explainability per REQ_0009)
requires a richer per-snapshot status with three severity bands and a
distinct "no signals observed" bucket so the GUI can render
HEALTHY / DEGRADED / CRITICAL / UNKNOWN states and surface degraded
breaches before they become critical. That richer status model is a
separate, additive domain layer; it consumes the existing
`LivenessSignalSnapshot` without modification and produces a new
`TrainerWorkerHealthSnapshot`.

The pure-domain layer is staged first (2E2.A) because the existing
2E1 stack already proves the value of testing pure-domain logic in
isolation before adding service or composition wiring. 2E2.B (service)
and 2E2.C (composition root) follow as separate milestones, and only
after 2E2.A passes Codex review.

## Decision for this turn

Open Phase 2E2.A. Author the sub-phase breakdown (140), domain spec
(141), test plan (142), safety boundaries (143), and GO/NO-GO request
(144) under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`. Author
the consolidated implementation+validation supervisor task (100) and
the Codex review supervisor task (101) under
`claude_worklog/agent_supervisor/tasks/`. Author this turn note under
`claude_worklog/autonomous_control_plane/`.

Phase 2E2.A authors a NEW package
`v2/backend/app/domain/trainer_worker_health/` with six source files
and a sibling test directory under
`v2/backend/tests/unit/domain/trainer_worker_health/` with 24 unit
tests plus a package marker. The package consumes the existing
`v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot` as an
input only; the snapshot is treated as a fixed external contract and
no 2E1 file is modified.

## Why consolidated rather than split

Per Claude Code Max20 consolidated-default, this milestone is
dispatched as ONE implementation+validation task (100) plus ONE Codex
review task (101). The 2E2.A surface is small (six source files, 24
test files, no Redis, no service, no composition root). If 100
returns FAIL with concrete blockers, the supervisor falls back to a
narrow REQ_0007 / REQ_0014 autofix task scoped to the six authored
source files plus the 24 new test files only. Same fallback for 101.

## Codex parallel lane status this turn

After the supervisor commits this turn's planner artifacts, the
working tree returns to clean and `099` becomes evidence-superseded
(its required outputs 138/139 already exist with PASS). With the
dirty tree resolved, the Codex parallel lane may resume read-only
review of any older committed artifact. Codex MUST NOT run the 101
review before 100 emits its impl GO/NO-GO marker (146) with
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_PASSED`.

## Hard stops not crossed by this turn

- No legacy mutation. `/home/wali/Desktop/AI BOT` untouched.
- No Redis read or write at any layer.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No exchange action.
- No leverage or margin change.
- No live trading enabled.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.

## Files emitted by this planner turn

- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E2A_OPEN_WORKER_HEALTH_DOMAIN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/141_PHASE_2E2A_WORKER_HEALTH_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/142_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/143_PHASE_2E2A_WORKER_HEALTH_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/144_PHASE_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/100_trainer_parity_2e2a_worker_health_domain_implementation.json`
- `claude_worklog/agent_supervisor/tasks/101_trainer_parity_2e2a_worker_health_domain_codex_review.json`

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_PLANNER_TURN_READY
