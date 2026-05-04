# Files reviewed

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/112_PHASE_2E1D_SERVICE_COMPOSITION_SPEC.md` lines 1-296
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/113_PHASE_2E1D_SERVICE_COMPOSITION_TEST_PLAN.md` lines 1-227
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/114_PHASE_2E1D_SERVICE_COMPOSITION_SAFETY_BOUNDARIES.md` lines 1-182
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/116_2E1D_SERVICE_COMPOSITION_IMPLEMENTATION_REPORT.md` lines 1-133
- `v2/backend/app/services/trainer_parity/__init__.py` lines 1-10
- `v2/backend/app/services/trainer_parity/errors.py` lines 1-14
- `v2/backend/app/services/trainer_parity/evaluation.py` lines 1-13
- `v2/backend/app/services/trainer_parity/liveness_service.py` lines 1-116
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_appends_prediction_observation_to_prediction_history.py` lines 1-28
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_appends_proposal_observation_to_proposal_history.py` lines 1-29
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_calls_clock_exactly_once.py` lines 1-37
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_caps_prediction_history_at_max.py` lines 1-29
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_caps_proposal_history_at_max.py` lines 1-29
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_does_not_mutate_supplied_histories.py` lines 1-31
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_passes_now_ms_into_compose.py` lines 1-31
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_propagates_collector_errors.py` lines 1-36
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_clock_returning_negative_int.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_clock_returning_non_int.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_empty_prediction_stream_name.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_empty_proposal_stream_name.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_identical_stream_names.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_negative_max_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_base_inputs_object.py` lines 1-26
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_callable_clock.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_growth_window_config.py` lines 1-26
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_int_max_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_observation_in_prediction_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_observation_in_proposal_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_str_prediction_stream_name.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_str_proposal_stream_name.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_tuple_prediction_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_non_tuple_proposal_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_reader_with_non_callable_latest_stream_id.py` lines 1-26
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_reader_without_latest_stream_id.py` lines 1-22
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_rejects_zero_max_history.py` lines 1-27
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_returns_snapshot_with_growth_from_history.py` lines 1-50
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_returns_trainer_liveness_evaluation_dataclass.py` lines 1-30
- `v2/backend/tests/unit/services/trainer_parity/test_evaluate_skips_streams_with_none_latest_id.py` lines 1-29
- `v2/backend/tests/unit/services/trainer_parity/test_init_module_does_not_load_redis_when_imported.py` lines 1-10
- `v2/backend/tests/unit/services/trainer_parity/test_public_surface.py` lines 1-11
- `v2/backend/tests/unit/services/trainer_parity/test_service_does_not_import_factory_or_url_env.py` lines 1-17
- `v2/backend/tests/unit/services/trainer_parity/test_service_milestone_forbidden_tokens.py` lines 1-141

# Rubric findings

| # | Result | Evidence |
|---|---|---|
| 1 | PASS | `__init__.py` re-exports only the three names at lines 1-3, and `__all__` is the exact ordered tuple at lines 6-10. `test_public_surface.py` asserts the same ordering at lines 4-8. |
| 2 | PASS | `errors.py` imports only `__future__` at line 1 and defines `TrainerParityServiceError(Exception)` with `__init__(self, code: str, *, field: str)` at lines 4-8. |
| 3 | PASS | `evaluation.py` defines `@dataclass(frozen=True, slots=True)` at line 9 with fields in spec order at lines 11-13. `test_evaluate_returns_trainer_liveness_evaluation_dataclass.py` asserts `FrozenInstanceError` on assignment at lines 27-30. |
| 4 | PASS | `liveness_service.py` signature matches spec at lines 23-34. The 21-step contract is implemented in order: reader validation lines 35-37, base inputs lines 39-40, history type checks lines 42-46, history element checks lines 48-54, growth config lines 56-57, clock callable lines 59-60, stream names lines 62-69, max history lines 71-75, clock read and validation lines 77-81, cached clock lines 83-84, collect lines 86-90, partition lines 91-92, extend lines 93-102, compose lines 103-111, return lines 112-116. |
| 5 | PASS | Inspection shows the only `now_ms_clock()` call at `liveness_service.py` line 77; the other references are type/signature or validation at lines 30, 59-60, 79, 81. `test_evaluate_calls_clock_exactly_once.py` records calls and asserts length 1 at lines 14-21 and 24-37. |
| 6 | PASS | `liveness_service.py` imports only `Callable` from the standard library at line 3, the allowed domain names at lines 5-17, and sibling service names at lines 19-20. No third-party import or non-allowed v2 import is present. |
| 7 | PASS | Direct `rg --fixed-strings --case-sensitive` over the specified forbidden-token set against `v2/backend/app/services/trainer_parity/` and service tests returned zero hits. Source inspection also shows no forbidden imports or calls in `liveness_service.py` lines 1-116. |
| 8 | PASS | Direct forbidden-token `rg` over `__init__.py`, `errors.py`, `evaluation.py`, and every service test returned zero hits. The authored source and tests reviewed above show no forbidden literals. |
| 9 | FAIL | The guard constructs forbidden literals at runtime at `test_service_milestone_forbidden_tokens.py` lines 44-137 and applies no per-file exemption at lines 138-141, but it does not scan every authored test enumerated by report 116. Report 116 lists `test_evaluate_appends_proposal_observation_to_proposal_history.py` at line 32 and `test_evaluate_skips_streams_with_none_latest_id.py` at line 33; the guard scan list at lines 11-42 omits both files. |
| 10 | PASS | `test_service_does_not_import_factory_or_url_env.py` pops `redis`, factory, url_env, and the service package from `sys.modules` at lines 5-11, imports the service at line 13, and asserts all three forbidden modules are absent at lines 15-17. |
| 11 | PASS | `test_init_module_does_not_load_redis_when_imported.py` pops `redis` and the service package at lines 5-6, imports the service at line 8, and asserts `redis` is absent at line 10. |
| 12 | PASS | `test_public_surface.py` asserts the exact `__all__` names and ordering at lines 4-8. |
| 13 | PASS | `rg "^def test_"` found exactly one test function in each of the 34 authored `test_*.py` files, with definitions at their respective reviewed line ranges. `rg "conftest"` under `v2/backend/tests/unit/services/` returned zero lines. |
| 14 | FAIL | `test_evaluate_does_not_mutate_supplied_histories.py` captures tuple copies at lines 17-18 and asserts equality at lines 30-31, but it does not assert reference equality of the input tuples or identity of element objects after the call as required. |
| 15 | FAIL | `test_evaluate_passes_now_ms_into_compose.py` uses the boundary input at lines 23-26 and asserts a literal growth value at line 31, but it does not compare the snapshot value to `compute_stream_id_growth_in_window` for the new history at the same `now_ms`. |
| 16 | PASS | `test_evaluate_propagates_collector_errors.py` monkeypatches `v2.backend.app.services.trainer_parity.liveness_service.collect_stream_id_observations` to raise `ObservationCollectorError` at lines 14-21, then asserts that error type propagates and retains code/field/string at lines 22-36. |
| 17 | FAIL | The service test suite passes with zero failures, but there are 34 authored test files, not the required 32. Report 116 enumerates 34 test files at lines 9-42 and states all 34 exist and pass at lines 91-128; the local pytest run reported `34 passed`. |
| 18 | PASS | The existing adapter and domain suites passed locally: redis_v2 reported `49 passed`; trainer_liveness, liveness_stream_growth, trainer_liveness_composition, and trainer_liveness_observation_collector reported `164 passed`. These correspond to test-plan validation commands at 113 lines 205-207. |
| 19 | PASS | `python -m py_compile` over the four authored source files exited 0. Source files are `__init__.py` lines 1-10, `errors.py` lines 1-14, `evaluation.py` lines 1-13, and `liveness_service.py` lines 1-116. |
| 20 | PASS | `git status -s` over the cross-isolation paths listed in 113 lines 205-209 and expanded by 114 lines 132-151 returned zero lines. |
| 21 | PASS | The four authored source files contain no FastAPI startup hook, lifespan handler, dependency, router registration, module-level singleton, module-level cache, module-level lock, or background task. Source inspection covers `__init__.py` lines 1-10, `errors.py` lines 1-14, `evaluation.py` lines 1-13, and `liveness_service.py` lines 1-116; supplemental `rg` for FastAPI/concurrency/cache/logging patterns returned no relevant hits. |
| 22 | PASS | Cross-isolation `git status -s` over `v2/backend/app/adapters/`, `v2/backend/app/domain/`, `v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`, `v2/backend/app/main.py`, `v2/frontend/`, and the listed prior test paths returned zero lines, satisfying the path boundaries in 112 lines 225-232 and 114 lines 132-151. |
| 23 | PASS | Secret-shaped string scan over the four service files, service tests, and implementation report found no high-confidence secret values. The only matches were the literal word fragments in the forbidden-token test name/report text, not secret-shaped credentials. |
| 24 | FAIL | The happy-path coverage is not precise enough. `test_evaluate_returns_snapshot_with_growth_from_history.py` checks consistency with beta at lines 39-50, but only asserts nonnegative values at lines 37-38, not positive integers. It also uses one evaluation with a fixed `now_ms_clock` at line 32, not sequential string IDs across two clock advances. `test_evaluate_passes_now_ms_into_compose.py` similarly asserts only a literal at line 31. |

# Validation commands run

- `sed -n '1,220p' claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/117_2E1D_SERVICE_COMPOSITION_GO_NO_GO.md` exit code 0; predecessor marker was exactly `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`.
- `git status -s` exit code 0; showed one pre-existing modified file outside this review scope: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- `find v2/backend/tests/unit/services/trainer_parity -maxdepth 1 -type f -name 'test_*.py' | sort` exit code 0; listed 34 authored service test files.
- `find v2/backend/tests/unit/services/trainer_parity -maxdepth 1 -type f -name 'test_*.py' | wc -l` exit code 0; output `34`.
- `rg --line-number "^def test_" v2/backend/tests/unit/services/trainer_parity/` exit code 0; found one test function per authored test file.
- `rg --line-number "conftest" v2/backend/tests/unit/services/trainer_parity v2/backend/tests/unit/services || true` exit code 0; returned zero lines.
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q` exit code 0; `34 passed in 0.04s`.
- `.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q` exit code 0; `49 passed in 0.07s`.
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ v2/backend/tests/unit/domain/liveness_stream_growth/ v2/backend/tests/unit/domain/trainer_liveness_composition/ v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ -q` exit code 0; `164 passed in 0.09s`.
- `python -m py_compile v2/backend/app/services/trainer_parity/__init__.py v2/backend/app/services/trainer_parity/errors.py v2/backend/app/services/trainer_parity/evaluation.py v2/backend/app/services/trainer_parity/liveness_service.py` exit code 0; no output.
- `git status -s v2/backend/app/adapters/ v2/backend/app/domain/ v2/backend/app/api/ v2/backend/app/cli/ v2/backend/app/jobs/ v2/backend/app/main.py v2/frontend/ v2/backend/tests/unit/adapters/ v2/backend/tests/unit/domain/ v2/backend/tests/unit/feature_snapshots/ v2/backend/tests/unit/symbol_universe/` exit code 0; returned zero lines.
- `rg "^END_FILE_SENTINEL:" v2/backend/app/services/trainer_parity/ v2/backend/tests/unit/services/trainer_parity/ claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/116_2E1D_SERVICE_COMPOSITION_IMPLEMENTATION_REPORT.md claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/117_2E1D_SERVICE_COMPOSITION_GO_NO_GO.md` exit code 1; returned zero lines.
- `rg --fixed-strings --case-sensitive` loop over the forbidden-token set against `v2/backend/app/services/trainer_parity/` and `v2/backend/tests/unit/services/trainer_parity/` exit code 0; no token produced a hit.
- `rg --line-number "FastAPI|startup|lifespan|Depends|APIRouter|include_router|BackgroundTasks|create_task|Thread|Lock|global |cache|singleton|logger|logging|print\\(|os\\.environ|subprocess\\.|socket\\.|requests\\.|httpx\\.|aiohttp\\.|urllib\\." v2/backend/app/services/trainer_parity/` exit code 0; only `cached_clock` references appeared, no prohibited FastAPI/I/O/logging/concurrency pattern.
- `rg --line-number "api_key|apikey|secret|token|password|passwd|private_key|BEGIN .*PRIVATE|sk-|xox[baprs]-|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}" v2/backend/app/services/trainer_parity/ v2/backend/tests/unit/services/trainer_parity/ claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/116_2E1D_SERVICE_COMPOSITION_IMPLEMENTATION_REPORT.md` exit code 0; only benign occurrences in forbidden-token test/report names and prose, no secret-shaped value.

# Concrete blockers

- `test_service_milestone_forbidden_tokens.py` does not scan every authored service test file. It omits `test_evaluate_appends_proposal_observation_to_proposal_history.py` and `test_evaluate_skips_streams_with_none_latest_id.py`, even though report 116 enumerates them as authored.
- The authored test set contains 34 `test_*.py` files, while the review rubric and test plan require the 32 authored test files.
- `test_evaluate_does_not_mutate_supplied_histories.py` does not assert tuple reference equality or identity of element objects after evaluation.
- `test_evaluate_passes_now_ms_into_compose.py` does not assert equality to `compute_stream_id_growth_in_window` for the new history at the same `now_ms`.
- The happy-path growth coverage is not precise enough for rubric item 24: it does not assert positive growth and does not model sequential string IDs across two clock advances.

# Safety review

- live behavior: none observed
- Redis read access: none observed
- Redis mutation access: none observed
- Redis commands at construction: none observed
- legacy mutation: none observed
- release intent: none observed
- secret-shaped strings: none observed
- URL logging: none observed
- prior-milestone modification: none observed in the required cross-isolation status paths
- factory / url_env import: none observed
- FastAPI lifespan registration: none observed
- module-level singleton: none observed
- wall-clock helper use: none observed

# Recommendation

FAIL

PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_REVIEW_READY
