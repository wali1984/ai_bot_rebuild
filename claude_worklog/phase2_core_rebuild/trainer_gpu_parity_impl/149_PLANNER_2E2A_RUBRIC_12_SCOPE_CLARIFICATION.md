# Planner Directive — Phase 2E2.A Rubric 12 Scope Clarification

## Context

- Implementation marker: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/146_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO.md` = `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex review: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/147_2E2A_WORKER_HEALTH_DOMAIN_CODEX_REVIEW.md` reports 23 PASS rows and exactly one FAIL on rubric row 12.
- Codex GO/NO-GO: `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md` = `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL`.

## Defect classification

The defect is in the test plan's prefatory paragraph, not in the implementation, not in the authored tests, and not in the safety boundaries.

`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/142_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN.md` lines 7-9 state:

> Tests use inline hand-written `LivenessSignalSnapshot` and `TrainerWorkerHealthThresholds` objects constructed directly via their dataclass constructors.

That sentence reads as a universal rule when applied literally. Codex applied it literally and flagged three test files that intrinsically cannot use those objects:

- `v2/backend/tests/unit/domain/trainer_worker_health/test_public_surface.py` only asserts the package `__all__` shape (test plan §"Required test files (24 plus package marker)" item 1, lines 16-20).
- `v2/backend/tests/unit/domain/trainer_worker_health/test_errors_invariants.py` only constructs `TrainerWorkerHealthDomainError` instances and asserts message/field behavior (test plan item 2, lines 22-27).
- `v2/backend/tests/unit/domain/trainer_worker_health/test_health_status_constants.py` only asserts the value, distinctness, and disjointness of the status and reason string constants (test plan item 3, lines 29-34).

The same test plan's per-test enumerations (items 1, 2, 3, and the import-isolation items 27 and 28) do not require either object. Items 27 and 28 in the same enumeration cannot use those objects either, because their entire scope is reading authored source files for forbidden literals.

The prefatory rule is therefore inconsistent with the test plan's own per-test specifications.

## Decision

The planner is the rule-source for the test plan and resolves the inconsistency in favor of the per-test enumerations.

Rubric 12 must be scoped to test files whose specification (per the test plan's per-test enumeration) includes constructing or exercising a `LivenessSignalSnapshot` value or a `TrainerWorkerHealthThresholds` value beyond the construction-validation tests for thresholds themselves.

Test files that are intrinsically out of Rubric 12 scope:

- `test_public_surface.py` (item 1).
- `test_errors_invariants.py` (item 2).
- `test_health_status_constants.py` (item 3).
- `test_worker_health_domain_does_not_import_redis.py` (item 27).
- `test_worker_health_domain_does_not_import_url_env.py` (item 28).

Test files that exercise threshold construction-validation invariants only and therefore must construct `TrainerWorkerHealthThresholds` directly but not `LivenessSignalSnapshot`:

- `test_health_thresholds_invariants_must_be_int.py` (item 4).
- `test_health_thresholds_invariants_must_be_at_least_one.py` (item 5).
- `test_health_thresholds_invariants_critical_must_be_greater_than_degraded.py` (item 6).

All remaining authored test files must construct both `LivenessSignalSnapshot` and `TrainerWorkerHealthThresholds` inline. They are the snapshot-invariant tests (items 7-11) and the evaluator behavior tests (items 12-26).

The 23 other rubric rows already PASS. Source code and authored tests are byte-identical to the post-implementation tree.

## Action

The planner issues:

1. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/150_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM.md` — formal scope clarification authoritative for re-review.
2. `claude_worklog/agent_supervisor/tasks/102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json` — Codex re-review task that reads 142 plus 150 as authoritative test plan and re-applies all 24 rubric rows.

No `v2/` source or test files are modified. No prior-milestone files are modified. No legacy is touched. No Redis access. No live behavior. No release intent. No deployment.

## Why an addendum and not an autofix

The autofix path would require adding inline constructions of `LivenessSignalSnapshot` and `TrainerWorkerHealthThresholds` to the three Codex-flagged test files even though those tests do not exercise the snapshot or thresholds. That would add unused or marginally-used constructions to test files that exist to assert package shape, error class behavior, and constant values respectively. That contradicts the test plan's per-test enumerations and degrades the precision of the test isolation that 2E2.A established.

The addendum path keeps source and tests byte-identical, removes the prefatory inconsistency, and asks Codex to re-evaluate Rubric 12 against the corrected scope.

## Forbidden

- modify `/home/wali/Desktop/AI BOT`
- modify any source under `v2/backend/app/`
- modify any authored test under `v2/backend/tests/unit/domain/trainer_worker_health/`
- modify any prior-milestone source or test
- write or delete Redis keys
- restart any live service
- place or cancel exchange orders
- change leverage or margin
- enable live trading
- deploy or run production migrations
- expose or commit secrets

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_RUBRIC_12_SCOPE_CLARIFICATION_READY
