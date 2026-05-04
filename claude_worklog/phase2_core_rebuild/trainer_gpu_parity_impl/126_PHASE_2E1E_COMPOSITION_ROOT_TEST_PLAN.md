# Phase 2E1.E — Trainer Parity Composition Root Test Plan

The test plan enumerates the canonical 25 test files under
`v2/backend/tests/unit/composition/trainer_parity/`. Each test file
contains exactly one test function whose name starts with `test_` and
mirrors the file basename. Tests use inline hand-written fakes; no
shared `conftest` is created.

## Required test files (25)

1. `test_public_surface.py` — imports `__all__` from
   `v2.backend.app.composition.trainer_parity`; asserts it is exactly
   the tuple
   `("build_trainer_liveness_evaluator", "TrainerLivenessEvaluator",
    "TrainerParityCompositionError")` in that order; asserts each name
   is bound to the same object as the corresponding direct module
   attribute.

2. `test_calls_factory_with_url_kwarg.py` — monkeypatches
   `v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader`
   to a fake that records `(args, kwargs)` and returns a hand-written
   fake reader exposing `latest_stream_id`. Calls
   `build_trainer_liveness_evaluator(url="redis://h:6379/0",
   ...other valid config)`. Asserts the fake factory was called
   exactly once with `kwargs == {"url": "redis://h:6379/0",
   "env": None}` and `args == ()`.

3. `test_calls_factory_with_env_kwarg.py` — same pattern; passes
   `env={"V2_REDIS_URL": "redis://h:6379/0"}` (a hand-written dict
   with `.get` available); asserts factory called with
   `kwargs == {"url": None, "env": <that dict>}` and `args == ()`.

4. `test_calls_factory_with_both_kwargs.py` — passes both `url` and
   `env`; asserts factory called with both kwargs threaded through.

5. `test_factory_called_exactly_once_per_build.py` — calls
   `build_trainer_liveness_evaluator(...)` once; asserts the patched
   factory's call count is exactly 1 immediately after build.

6. `test_factory_not_called_again_by_evaluator.py` — calls the
   evaluator returned by build; asserts the patched factory's call
   count is still exactly 1 (i.e., the closure does not re-build the
   reader).

7. `test_returns_callable_evaluator.py` — asserts
   `callable(build_trainer_liveness_evaluator(...))` is `True`.

8. `test_evaluator_forwards_reader_to_service.py` — monkeypatches
   `v2.backend.app.composition.trainer_parity.runtime.evaluate_trainer_liveness`
   to a fake that records its leading positional argument. Calls
   build → evaluator → asserts the captured leading arg is the same
   object as the fake reader returned by the patched factory.

9. `test_evaluator_forwards_static_config_to_service.py` — patches
   `evaluate_trainer_liveness` to record its kwargs. Calls build with
   distinct sentinel-tagged values for `base_inputs`, `growth_config`,
   `now_ms_clock`, `prediction_stream_name`, `proposal_stream_name`,
   `max_history_per_stream`. Calls evaluator. Asserts each kwarg
   reaches the service unchanged.

10. `test_evaluator_forwards_supplied_histories_to_service.py` —
    patches `evaluate_trainer_liveness` to record its
    `prediction_history` and `proposal_history` kwargs. Calls evaluator
    with `pred = (obs1,)` and `prop = (obs2,)`. Asserts the captured
    kwargs are those exact tuples (identity preserved).

11. `test_evaluator_returns_service_result_unchanged.py` — patches
    `evaluate_trainer_liveness` to return a sentinel
    `TrainerLivenessEvaluation` instance. Calls evaluator. Asserts
    the returned object is the same identity as the sentinel.

12. `test_evaluator_propagates_service_error.py` — patches
    `evaluate_trainer_liveness` to raise
    `TrainerParityServiceError("forced", field="reader")`. Calls
    evaluator inside a `pytest.raises(TrainerParityServiceError)`
    block; asserts the exception's `code == "forced"` and
    `field == "reader"` post-catch.

13. `test_evaluator_does_not_mutate_supplied_histories.py` —
    patches `evaluate_trainer_liveness` to a fake that returns a
    valid `TrainerLivenessEvaluation`. Builds evaluator. Captures
    input tuple ids and per-element ids before calling the evaluator.
    Calls evaluator with the captured tuples. Asserts the original
    tuples still equal pre-call values, that `id(pred_history)` is
    unchanged, and that each element's `id` is unchanged.

14. `test_validates_base_inputs.py` — calls build with
    `base_inputs=object()`; asserts
    `TrainerParityCompositionError("must_be_liveness_snapshot_base_inputs",
    field="base_inputs")` is raised; asserts the patched factory was
    NEVER called.

15. `test_validates_growth_config.py` — calls build with
    `growth_config=object()`; asserts
    `TrainerParityCompositionError("must_be_growth_window_config",
    field="growth_config")`; asserts factory not called.

16. `test_validates_now_ms_clock_callable.py` — calls build with
    `now_ms_clock=42`; asserts
    `TrainerParityCompositionError("must_be_callable",
    field="now_ms_clock")`; asserts factory not called.

17. `test_validates_prediction_stream_name_nonempty_str.py` —
    parametrizes via two `with pytest.raises(...)` blocks INSIDE the
    same single test function: one for
    `prediction_stream_name=42` (raises
    `must_be_nonempty_str`), one for `prediction_stream_name=""`
    (raises `must_be_nonempty_str`). Asserts `field ==
    "prediction_stream_name"` in both. Asserts factory never called.

18. `test_validates_proposal_stream_name_nonempty_str.py` — mirror
    of 17 for `proposal_stream_name`.

19. `test_validates_stream_names_differ.py` — calls build with both
    names equal to `"trainer:predictions"`; asserts
    `TrainerParityCompositionError("stream_names_must_differ",
    field="proposal_stream_name")`; asserts factory not called.

20. `test_validates_max_history_per_stream_int.py` — calls build with
    `max_history_per_stream=True` (a `bool` is technically an `int`
    subclass but `type(...) is not int` rejects it); asserts
    `TrainerParityCompositionError("must_be_int",
    field="max_history_per_stream")`; asserts factory not called.

21. `test_validates_max_history_per_stream_positive.py` — uses a
    single test function with two `with pytest.raises(...)` blocks:
    `max_history_per_stream=0` and `max_history_per_stream=-1`.
    Both raise `must_be_positive`; asserts factory not called.

22. `test_factory_error_propagates_unchanged.py` — patches
    `make_real_redis_stream_latest_id_reader` to raise
    `RedisStreamReaderError("must_be_set", field="V2_REDIS_URL")`.
    Calls build inside `pytest.raises(RedisStreamReaderError)`.
    Asserts the caught exception's `code` and `field` match the raise.

23. `test_runtime_module_loads_redis_when_imported.py` — pops
    `redis`, `v2.backend.app.adapters.redis_v2.factory`, and
    `v2.backend.app.composition.trainer_parity` (and its `runtime`
    submodule) from `sys.modules`. Then imports
    `v2.backend.app.composition.trainer_parity`. Asserts that
    `redis` IS in `sys.modules` after the import, AND that
    `v2.backend.app.adapters.redis_v2.factory` IS in `sys.modules`.
    This is the inverse-direction wiring assertion.

24. `test_composition_milestone_forbidden_tokens.py` — builds every
    forbidden literal from spec 125 § "Forbidden tokens" at runtime
    via string concatenation. Iterates over the three authored
    source files (`__init__.py`, `errors.py`, `runtime.py`) and the
    24 sibling test files (this file is excluded from its own scan
    to avoid self-reference); for every `(file, token)` pair, asserts
    zero substring occurrences EXCEPT the explicit single
    `from v2.backend.app.adapters.redis_v2.factory` exemption in
    `runtime.py`. The exemption is implemented by counting that
    specific literal in `runtime.py` and asserting the count equals 1
    BEFORE excluding that literal from the runtime.py forbidden-token
    pass; for every other file the literal is forbidden absolutely.

25. `test_composition_does_not_import_url_env_directly.py` — pops
    `v2.backend.app.adapters.redis_v2.url_env`,
    `v2.backend.app.adapters.redis_v2.factory`, and
    `v2.backend.app.composition.trainer_parity` from `sys.modules`.
    Imports the composition package. Asserts that
    `v2.backend.app.adapters.redis_v2.url_env` IS in `sys.modules`
    (because the factory imports it), but the composition package
    does NOT have a direct attribute reference to `url_env` (i.e.,
    `getattr(v2.backend.app.composition.trainer_parity.runtime,
    "url_env", None) is None` AND the composition runtime module's
    source does not contain the literal `url_env`).

## Validation commands (executed in this order; abort on first non-zero exit)

1. `python -m py_compile v2/backend/app/composition/__init__.py
   v2/backend/app/composition/trainer_parity/__init__.py
   v2/backend/app/composition/trainer_parity/errors.py
   v2/backend/app/composition/trainer_parity/runtime.py`
2. `.venv/bin/python -m pytest
   v2/backend/tests/unit/composition/trainer_parity/ -q`
   — expected: `25 passed`.
3. `.venv/bin/python -m pytest
   v2/backend/tests/unit/services/trainer_parity/ -q`
   — expected: `34 passed` (existing 2E1.D suite must remain green).
4. `.venv/bin/python -m pytest
   v2/backend/tests/unit/adapters/redis_v2/ -q`
   — expected: `49 passed` (existing γ.real/γ.real.factory suite
   must remain green).
5. `git status -s v2/backend/app/services/ v2/backend/app/adapters/
   v2/backend/app/domain/ v2/backend/app/api/ v2/backend/app/cli/
   v2/backend/app/jobs/ v2/backend/app/main.py v2/frontend/
   v2/backend/tests/unit/services/ v2/backend/tests/unit/adapters/
   v2/backend/tests/unit/domain/ v2/backend/tests/unit/feature_snapshots/
   v2/backend/tests/unit/symbol_universe/`
   — MUST return zero lines.
6. Forbidden-token self-grep loop:
   `rg --fixed-strings --case-sensitive '<TOKEN>'
   v2/backend/app/composition/trainer_parity/
   v2/backend/tests/unit/composition/trainer_parity/`
   for each token in spec 125 § "Forbidden tokens", with a single
   permitted hit for
   `from v2.backend.app.adapters.redis_v2.factory` in `runtime.py`
   only. Every other token must produce zero hits.
7. End-file marker self-scan:
   `rg "^END_FILE_SENTINEL:"
   v2/backend/app/composition/trainer_parity/
   v2/backend/tests/unit/composition/trainer_parity/
   claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/129_2E1E_COMPOSITION_ROOT_IMPLEMENTATION_REPORT.md
   claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md`
   — MUST return zero lines.

## Final test count addendum

The canonical authored test count is 25. The 116-style implementation
report (129) MUST list each test file basename and assert the disk
count is exactly 25.

PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_TEST_PLAN_READY
