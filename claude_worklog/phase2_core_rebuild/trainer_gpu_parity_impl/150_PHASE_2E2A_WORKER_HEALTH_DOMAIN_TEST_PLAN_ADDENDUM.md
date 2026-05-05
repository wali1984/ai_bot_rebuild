# Phase 2E2.A — Worker Health Domain Test Plan Addendum

This addendum amends the prefatory paragraph of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/142_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN.md`
lines 7-9 to resolve an internal inconsistency between that paragraph
and the per-test enumerations in items 1, 2, 3, 27, and 28 of the
same document.

For all subsequent reviews and re-reviews of Phase 2E2.A, this
addendum is authoritative whenever it conflicts with the prefatory
paragraph.

## Rubric 12 — revised scope

Rubric 12 of the Codex review rubric for Phase 2E2.A is to be
evaluated as follows.

Rubric 12 (revised): Every authored test file under
`v2/backend/tests/unit/domain/trainer_worker_health/` contains
exactly one `test_` function whose name mirrors the file basename.
No `conftest.py` exists under that directory. No fixture is shared
across test files.

Inline-construction sub-rule: Test files whose test plan specification
exercises a `LivenessSignalSnapshot` value, a
`TrainerWorkerHealthSnapshot` value, or a
`TrainerWorkerHealthThresholds` value beyond simple construction-
validation of thresholds, MUST construct those values inline via
their dataclass constructors and MUST NOT use shared fixtures.

The inline-construction sub-rule does NOT apply to the following
files because those files do not exercise the evaluator path or any
snapshot field beyond their own narrow scope:

1. `test_public_surface.py` — asserts package `__all__` shape only.
2. `test_errors_invariants.py` — asserts
   `TrainerWorkerHealthDomainError` message/field behavior only.
3. `test_health_status_constants.py` — asserts string constants
   only.
4. `test_worker_health_domain_does_not_import_redis.py` — reads
   authored source for forbidden Redis tokens only.
5. `test_worker_health_domain_does_not_import_url_env.py` — reads
   authored source for forbidden adapter/env/wallclock tokens only.

The inline-construction sub-rule applies only to
`TrainerWorkerHealthThresholds` (and not to `LivenessSignalSnapshot`)
in the following files because those files exercise threshold
construction-validation invariants only and never call the evaluator:

6. `test_health_thresholds_invariants_must_be_int.py`.
7. `test_health_thresholds_invariants_must_be_at_least_one.py`.
8. `test_health_thresholds_invariants_critical_must_be_greater_than_degraded.py`.

The inline-construction sub-rule applies in full (both
`LivenessSignalSnapshot` and `TrainerWorkerHealthThresholds`) to all
remaining authored test files. They are the snapshot-invariant tests
(items 7-11 in 142) and the evaluator behavior tests (items 12-26
in 142):

9. `test_health_snapshot_invariants_status_in_allowed.py`.
10. `test_health_snapshot_invariants_observation_ts_must_match.py`.
11. `test_health_snapshot_invariants_reasons_unique.py`.
12. `test_health_snapshot_invariants_healthy_requires_empty.py`.
13. `test_health_snapshot_invariants_unknown_requires_no_signals_reason.py`.
14. `test_evaluator_healthy_when_all_fresh.py`.
15. `test_evaluator_unknown_when_no_signals.py`.
16. `test_evaluator_degraded_prediction_age.py`.
17. `test_evaluator_degraded_gpu_batch_age.py`.
18. `test_evaluator_degraded_proposal_age.py`.
19. `test_evaluator_critical_prediction_age.py`.
20. `test_evaluator_critical_gpu_batch_age.py`.
21. `test_evaluator_critical_proposal_age.py`.
22. `test_evaluator_critical_when_worker_dead.py`.
23. `test_evaluator_critical_when_fatal_log_signature.py`.
24. `test_evaluator_critical_when_zero_stream_growth_with_alive_parent.py`.
25. `test_evaluator_status_precedence_critical_over_degraded.py`.
26. `test_evaluator_threshold_boundary_strict.py`.
27. `test_evaluator_now_before_observation_rejected.py`.
28. `test_evaluator_does_not_mutate_inputs.py`.

## Out-of-scope clarifications

The following items are unchanged from 142 and remain authoritative:

- Test count (24 authored test files plus the `__init__.py` package
  marker), as enumerated in 142 lines 12-207.
- Per-test specifications in 142 items 1-28.
- Validation commands in 142 lines 211-225.
- The cross-isolation `git status -s` zero-line requirement in 142
  line 226.

## Files unchanged by this addendum

- `v2/backend/app/domain/trainer_worker_health/__init__.py`.
- `v2/backend/app/domain/trainer_worker_health/errors.py`.
- `v2/backend/app/domain/trainer_worker_health/health_status.py`.
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`.
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`.
- `v2/backend/app/domain/trainer_worker_health/health_evaluator.py`.
- All 24 authored test files plus the package marker under
  `v2/backend/tests/unit/domain/trainer_worker_health/`.
- All prior-milestone files under `v2/backend/app/services/`,
  `v2/backend/app/adapters/`, `v2/backend/app/composition/`,
  `v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`,
  `v2/backend/app/main.py`, `v2/frontend/`,
  `v2/backend/tests/unit/services/`, `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/composition/`,
  `v2/backend/tests/unit/feature_snapshots/`,
  `v2/backend/tests/unit/symbol_universe/`,
  `v2/backend/app/domain/trainer_liveness/`,
  `v2/backend/app/domain/trainer_liveness_composition/`,
  `v2/backend/app/domain/trainer_liveness_observation_collector/`,
  `v2/backend/app/domain/liveness_stream_growth/`, and
  `v2/backend/tests/unit/domain/trainer_liveness/`.

## Safety

- No live behavior introduced.
- No Redis access introduced.
- No legacy mutation.
- No release intent.
- No deployment.
- No secret exposure.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM_READY
