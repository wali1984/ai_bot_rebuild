# Phase 2E1.E Composition Root Codex Review

## Files reviewed
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/125_PHASE_2E1E_COMPOSITION_ROOT_SPEC.md` lines 1-366.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/126_PHASE_2E1E_COMPOSITION_ROOT_TEST_PLAN.md` lines 1-215.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/127_PHASE_2E1E_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md` lines 1-174.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/129_2E1E_COMPOSITION_ROOT_IMPLEMENTATION_REPORT.md` lines 1-127.
- `v2/backend/app/composition/__init__.py` lines 1-1.
- `v2/backend/app/composition/trainer_parity/__init__.py` lines 1-8.
- `v2/backend/app/composition/trainer_parity/errors.py` lines 1-13.
- `v2/backend/app/composition/trainer_parity/runtime.py` lines 1-99.
- `v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_both_kwargs.py` lines 1-38.
- `v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_env_kwarg.py` lines 1-37.
- `v2/backend/tests/unit/composition/trainer_parity/test_calls_factory_with_url_kwarg.py` lines 1-36.
- `v2/backend/tests/unit/composition/trainer_parity/test_composition_does_not_import_url_env_directly.py` lines 1-37.
- `v2/backend/tests/unit/composition/trainer_parity/test_composition_milestone_forbidden_tokens.py` lines 1-93.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_does_not_mutate_supplied_histories.py` lines 1-47.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_forwards_reader_to_service.py` lines 1-42.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_forwards_static_config_to_service.py` lines 1-46.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_forwards_supplied_histories_to_service.py` lines 1-44.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_propagates_service_error.py` lines 1-42.
- `v2/backend/tests/unit/composition/trainer_parity/test_evaluator_returns_service_result_unchanged.py` lines 1-35.
- `v2/backend/tests/unit/composition/trainer_parity/test_factory_called_exactly_once_per_build.py` lines 1-35.
- `v2/backend/tests/unit/composition/trainer_parity/test_factory_error_propagates_unchanged.py` lines 1-32.
- `v2/backend/tests/unit/composition/trainer_parity/test_factory_not_called_again_by_evaluator.py` lines 1-40.
- `v2/backend/tests/unit/composition/trainer_parity/test_public_surface.py` lines 1-19.
- `v2/backend/tests/unit/composition/trainer_parity/test_returns_callable_evaluator.py` lines 1-29.
- `v2/backend/tests/unit/composition/trainer_parity/test_runtime_module_loads_redis_when_imported.py` lines 1-34.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_base_inputs.py` lines 1-29.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_growth_config.py` lines 1-30.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_max_history_per_stream_int.py` lines 1-31.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_max_history_per_stream_positive.py` lines 1-43.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_now_ms_clock_callable.py` lines 1-31.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_prediction_stream_name_nonempty_str.py` lines 1-43.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_proposal_stream_name_nonempty_str.py` lines 1-43.
- `v2/backend/tests/unit/composition/trainer_parity/test_validates_stream_names_differ.py` lines 1-31.

## Rubric findings
| # | Result | Evidence |
|---|---|---|
| 1 | PASS | `trainer_parity/__init__.py` re-exports only the runtime names and error at lines 1-2, and `__all__` is exactly `("build_trainer_liveness_evaluator", "TrainerLivenessEvaluator", "TrainerParityCompositionError")` at lines 4-8. |
| 2 | PASS | `errors.py` imports only `__future__` at line 1 and defines `TrainerParityCompositionError(Exception)` with `__init__(self, code: str, *, field: str \| None = None)` at lines 4-8. |
| 3 | PASS | `runtime.py` defines `TrainerLivenessEvaluator = Callable[[tuple[StreamIdObservation, ...], tuple[StreamIdObservation, ...]], TrainerLivenessEvaluation]` at lines 21-24, matching spec 125 lines 140-149. |
| 4 | PASS | `runtime.py` signature has the leading `*` and parameters in spec order at lines 27-37; validation steps 1-8 execute at lines 38-71, factory build is step 9 at line 73, local capture is step 10 at lines 75-81, and returned closure forwards/returns service output at lines 83-99. |
| 5 | PASS | The factory import appears exactly once as `from v2.backend.app.adapters.redis_v2.factory import make_real_redis_stream_latest_id_reader` at `runtime.py` line 5; targeted `rg` over the authored source found no other redis_v2 adapter import, no `url_env`, and no direct redis import. |
| 6 | PASS | `runtime.py` imports only `__future__`, `Callable`, the factory, `GrowthWindowConfig`, `StreamIdObservation`, `LivenessSnapshotBaseInputs`, `TrainerLivenessEvaluation`, `evaluate_trainer_liveness`, and `.errors.TrainerParityCompositionError` at lines 1-18, matching safety boundary 127 lines 109-122. |
| 7 | PASS | Direct forbidden-token `rg --fixed-strings --case-sensitive` over `runtime.py` showed zero source hits for the 125 forbidden set except the factory exemption at line 5, exactly once. |
| 8 | FAIL | Direct `rg --fixed-strings --case-sensitive 'datetime.now('` finds `test_composition_milestone_forbidden_tokens.py` line 33, and direct `rg --fixed-strings --case-sensitive 'datetime.utcnow('` finds line 34. The same forbidden-token set is therefore not absent from every test file. |
| 9 | FAIL | The guard test builds most literals by concatenation at lines 19-81 and applies the factory exemption at lines 82-93, but lines 33-34 contain static substrings `.datetime.now(` and `.datetime.utcnow(`, which include the forbidden 125 literals `datetime.now(` and `datetime.utcnow(` in the test source. |
| 10 | PASS | `test_runtime_module_loads_redis_when_imported.py` saves and pops `redis`, the factory module, package, and runtime at lines 5-18, imports the package at line 21, and asserts `redis` and factory module presence in `sys.modules` at lines 23-24. |
| 11 | PASS | `test_composition_does_not_import_url_env_directly.py` builds the url_env module name by concatenation at line 7, imports the package at line 23, and asserts transitive load plus no runtime attribute/source literal at lines 25-27. |
| 12 | PASS | `test_public_surface.py` asserts exact `__all__` name and order at lines 12-16 and object identity of exported bindings at lines 17-19. |
| 13 | PASS | `find` shows exactly 25 `test_*.py` files and `rg '^def test_'` shows exactly 25 test functions; each file has one `test_` function, examples include `test_public_surface.py` line 1 and `test_calls_factory_with_both_kwargs.py` line 8. `find v2/backend/tests/unit/composition -name conftest.py` returned zero lines. |
| 14 | PASS | `test_evaluator_does_not_mutate_supplied_histories.py` captures tuple values, tuple ids, and per-element ids at lines 25-30 and asserts equality, tuple identity, and element identity at lines 42-47. |
| 15 | PASS | `test_factory_called_exactly_once_per_build.py` records factory calls at lines 15-17 and asserts one call immediately after build at line 35; `test_factory_not_called_again_by_evaluator.py` invokes the evaluator at line 38 and still asserts one call at line 40. |
| 16 | PASS | `test_evaluator_propagates_service_error.py` monkeypatches `runtime.evaluate_trainer_liveness` at lines 23-26 to raise `TrainerParityServiceError` at lines 16-17, then asserts the propagated type, code, and field at lines 38-42. |
| 17 | PASS | `test_factory_error_propagates_unchanged.py` monkeypatches the runtime factory reference at lines 15-18 to raise `RedisStreamReaderError` at lines 12-13 and asserts the same type, code, and field at lines 21-32. |
| 18 | PASS | `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q` exited 0 with `25 passed in 0.10s`. |
| 19 | PASS | `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q` exited 0 with `34 passed in 0.04s`; `.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q` exited 0 with `49 passed in 0.07s`. |
| 20 | PASS | `python -m py_compile v2/backend/app/composition/__init__.py v2/backend/app/composition/trainer_parity/__init__.py v2/backend/app/composition/trainer_parity/errors.py v2/backend/app/composition/trainer_parity/runtime.py` exited 0. |
| 21 | PASS | `git status -s` over the cross-isolation paths in 127 lines 126-144 exited 0 with zero output lines. |
| 22 | PASS | Authored source files contain only package exports, error definition, imports, validation, factory construction, and closure forwarding at `__init__.py` lines 1-8, `errors.py` lines 1-13, and `runtime.py` lines 1-99; targeted source `rg` for FastAPI/lifespan/dependency/router/background task/singleton/cache/lock/time/logging/url_env returned zero lines. |
| 23 | PASS | Implementation report lists authored app files only under the new composition package at lines 3-7, and `git status -s` over `v2/backend/app/services/`, `v2/backend/app/adapters/`, `v2/backend/app/domain/`, `v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`, `v2/backend/app/main.py`, and `v2/frontend/` returned zero lines. |
| 24 | FAIL | No credential-shaped URL was observed, but not every test URL uses the required placeholder `redis://h:6379/0`: `test_calls_factory_with_both_kwargs.py` line 10 uses `redis://env:6379/0`. Other URL uses at `test_calls_factory_with_url_kwarg.py` lines 33 and 36, `test_calls_factory_with_env_kwarg.py` line 10, and `test_calls_factory_with_both_kwargs.py` lines 35 and 38 use the required `redis://h:6379/0` shape. |

## Validation commands run
- `grep -Fx 'PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED' claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md | wc -l && wc -l claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md` — exit code 0; marker count 1 and file line count 1.
- `python -m py_compile v2/backend/app/composition/__init__.py v2/backend/app/composition/trainer_parity/__init__.py v2/backend/app/composition/trainer_parity/errors.py v2/backend/app/composition/trainer_parity/runtime.py` — exit code 0; compilation passed.
- `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q` — exit code 0; `25 passed in 0.10s`.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q` — exit code 0; `34 passed in 0.04s`.
- `.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q` — exit code 0; `49 passed in 0.07s`.
- `git status -s v2/backend/app/services/ v2/backend/app/adapters/ v2/backend/app/domain/ v2/backend/app/api/ v2/backend/app/cli/ v2/backend/app/jobs/ v2/backend/app/main.py v2/frontend/ v2/backend/tests/unit/services/ v2/backend/tests/unit/adapters/ v2/backend/tests/unit/domain/ v2/backend/tests/unit/feature_snapshots/ v2/backend/tests/unit/symbol_universe/` — exit code 0; zero output lines.
- `rg "^END_FILE_SENTINEL:" v2/backend/app/composition/trainer_parity/ v2/backend/tests/unit/composition/trainer_parity/ claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/129_2E1E_COMPOSITION_ROOT_IMPLEMENTATION_REPORT.md claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md` — exit code 1; zero matches.
- `rg "^def test_" v2/backend/tests/unit/composition/trainer_parity/` — exit code 0; 25 test functions found.
- `find v2/backend/tests/unit/composition -name 'conftest.py' -print` — exit code 0; zero output lines.
- `rg --fixed-strings --case-sensitive <token> v2/backend/app/composition/trainer_parity/ v2/backend/tests/unit/composition/trainer_parity/` for every 125 forbidden token plus the factory exemption — exit code 0 for the loop; all counts were zero except `datetime.now(` count 1, `datetime.utcnow(` count 1, and factory exemption count 1.
- `rg --fixed-strings --case-sensitive -n 'datetime.now(' v2/backend/app/composition/trainer_parity/ v2/backend/tests/unit/composition/trainer_parity/` — exit code 0; hit at `test_composition_milestone_forbidden_tokens.py:33`.
- `rg --fixed-strings --case-sensitive -n 'datetime.utcnow(' v2/backend/app/composition/trainer_parity/ v2/backend/tests/unit/composition/trainer_parity/` — exit code 0; hit at `test_composition_milestone_forbidden_tokens.py:34`.
- `rg -n "redis://" v2/backend/app/composition/trainer_parity/ v2/backend/tests/unit/composition/trainer_parity/ claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/129_2E1E_COMPOSITION_ROOT_IMPLEMENTATION_REPORT.md` — exit code 0; one nonconforming placeholder at `test_calls_factory_with_both_kwargs.py:10`.

## Concrete blockers
- Forbidden-token blocker: `test_composition_milestone_forbidden_tokens.py` lines 33-34 contain the static forbidden substrings `datetime.now(` and `datetime.utcnow(` inside `.datetime.now(` and `.datetime.utcnow(` string fragments. This violates rubric items 8 and 9 and the 125/127 forbidden-token contract.
- URL-placeholder blocker: `test_calls_factory_with_both_kwargs.py` line 10 uses `redis://env:6379/0` instead of the required placeholder shape `redis://h:6379/0`, violating rubric item 24.

## Safety review
- live behavior: none observed.
- Redis read access at construction: none observed.
- Redis mutation access: none observed.
- Redis commands at construction: none observed.
- legacy mutation: none observed.
- release intent: none observed.
- secret-shaped strings: none observed; the URL-placeholder blocker is noncredential-shaped but nonconforming.
- URL logging: none observed.
- prior-milestone modification: none observed.
- url_env import: none observed in authored source.
- FastAPI lifespan registration: none observed.
- module-level singleton: none observed.
- wall-clock helper use: none observed in authored source; forbidden wall-clock literal substrings were observed in the guard test source as listed under blockers.

## Recommendation
FAIL

PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_REVIEW_READY
