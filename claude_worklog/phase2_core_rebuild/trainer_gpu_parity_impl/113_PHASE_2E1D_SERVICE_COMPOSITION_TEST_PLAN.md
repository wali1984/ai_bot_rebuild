# Phase 2E1.D — Trainer Parity Service Composition Test Plan

All tests live under
`v2/backend/tests/unit/services/trainer_parity/`. One assertion
narrative per file; no parametrize, no shared fixtures across files
beyond hand-written fakes. Tests run via the shared `.venv` pytest.

## Hand-written fakes (defined inline in each test that uses them)

- `_FakeReader`: a class exposing only `latest_stream_id(stream_name: str) -> str | None`.
  Backed by a per-instance `dict[str, str | None]`. No other methods.
  Never opens a socket. Never imports `redis`.
- `_FixedClock`: a callable returning a constant `int`.
- `_RecordingClock`: a callable that records each invocation in a list
  and returns a fixed `int`.
- `_RaisingClock`: a callable that raises `RuntimeError("clock_called_more_than_once")`
  on the second call.

`StreamIdObservation`, `GrowthWindowConfig`, and `LivenessSnapshotBaseInputs`
are imported from their canonical domain packages.

## Required test files (32 — exact set)

### Public surface

1. `test_public_surface.py` — asserts
   `v2.backend.app.services.trainer_parity.__all__ ==
   ("evaluate_trainer_liveness", "TrainerLivenessEvaluation",
   "TrainerParityServiceError")` and that each name resolves to the
   expected callable / class.
2. `test_init_module_does_not_load_redis_when_imported.py` —
   `sys.modules.pop("redis", None); sys.modules.pop("v2.backend.app.services.trainer_parity", None);
   import v2.backend.app.services.trainer_parity; assert "redis" not in sys.modules`.

### Reader validation

3. `test_evaluate_rejects_reader_without_latest_stream_id.py` — passes
   `object()`; asserts `TrainerParityServiceError` with code
   `"must_be_stream_latest_id_reader"` and `field="reader"`.
4. `test_evaluate_rejects_reader_with_non_callable_latest_stream_id.py` —
   passes a class whose `latest_stream_id` attribute is the integer `42`;
   asserts the same error.

### Base inputs validation

5. `test_evaluate_rejects_non_base_inputs_object.py` — passes a plain
   dict; asserts `TrainerParityServiceError` with code
   `"must_be_liveness_snapshot_base_inputs"` and
   `field="base_inputs"`.

### History validation

6. `test_evaluate_rejects_non_tuple_prediction_history.py` — passes a
   list; asserts `"must_be_tuple"` with `field="prediction_history"`.
7. `test_evaluate_rejects_non_tuple_proposal_history.py` — passes a
   list; asserts `"must_be_tuple"` with `field="proposal_history"`.
8. `test_evaluate_rejects_non_observation_in_prediction_history.py` —
   passes `(StreamIdObservation(...), object())`; asserts
   `"must_be_stream_id_observation"` with `field="prediction_history"`.
9. `test_evaluate_rejects_non_observation_in_proposal_history.py` —
   passes `(object(),)`; asserts
   `"must_be_stream_id_observation"` with `field="proposal_history"`.

### Growth config validation

10. `test_evaluate_rejects_non_growth_window_config.py` — passes a
    plain dict; asserts `"must_be_growth_window_config"` with
    `field="growth_config"`.

### Clock validation

11. `test_evaluate_rejects_non_callable_clock.py` — passes integer
    `12345` for `now_ms_clock`; asserts `"must_be_callable"` with
    `field="now_ms_clock"`.
12. `test_evaluate_rejects_clock_returning_non_int.py` — passes
    `lambda: "not-an-int"`; asserts `"must_be_int"` with
    `field="now_ms_clock"`.
13. `test_evaluate_rejects_clock_returning_negative_int.py` — passes
    `lambda: -1`; asserts `"must_be_nonnegative"` with
    `field="now_ms_clock"`.
14. `test_evaluate_calls_clock_exactly_once.py` — passes a
    `_RecordingClock`; runs a successful evaluation; asserts the
    recording list has length exactly 1.

### Stream name validation

15. `test_evaluate_rejects_non_str_prediction_stream_name.py` — passes
    integer `1`; asserts `"must_be_nonempty_str"` with
    `field="prediction_stream_name"`.
16. `test_evaluate_rejects_empty_prediction_stream_name.py` — passes
    `""`; asserts the same error code with the same field.
17. `test_evaluate_rejects_non_str_proposal_stream_name.py` — passes
    integer `2`; asserts `"must_be_nonempty_str"` with
    `field="proposal_stream_name"`.
18. `test_evaluate_rejects_empty_proposal_stream_name.py` — passes
    `""`; asserts the same error code with the same field.
19. `test_evaluate_rejects_identical_stream_names.py` — passes
    `prediction_stream_name="s"` and `proposal_stream_name="s"`;
    asserts `"stream_names_must_differ"` with
    `field="proposal_stream_name"`.

### Max-history validation

20. `test_evaluate_rejects_non_int_max_history.py` — passes
    `max_history_per_stream="10"`; asserts `"must_be_int"` with
    `field="max_history_per_stream"`.
21. `test_evaluate_rejects_zero_max_history.py` — passes `0`; asserts
    `"must_be_positive"` with `field="max_history_per_stream"`.
22. `test_evaluate_rejects_negative_max_history.py` — passes `-3`;
    asserts the same error.

### Behavior

23. `test_evaluate_appends_prediction_observation_to_prediction_history.py`
    — `_FakeReader` returns a non-None id only for the prediction
    stream; asserts `result.prediction_history[-1].stream_name ==
    prediction_stream_name` and `len(result.prediction_history) ==
    len(prior_prediction_history) + 1`.
24. `test_evaluate_appends_proposal_observation_to_proposal_history.py`
    — symmetric to test 23 for the proposal stream.
25. `test_evaluate_skips_streams_with_none_latest_id.py` —
    `_FakeReader` returns `None` for both streams; asserts both new
    histories are equal to the supplied prior histories (no growth).
26. `test_evaluate_caps_prediction_history_at_max.py` — supplies
    `max_history_per_stream=2` and a prior history of length 2;
    `_FakeReader` returns a new id for the prediction stream;
    asserts `len(result.prediction_history) == 2` and the OLDEST
    prior observation has been dropped.
27. `test_evaluate_caps_proposal_history_at_max.py` — symmetric to
    test 26 for the proposal stream.
28. `test_evaluate_does_not_mutate_supplied_histories.py` — supplies
    nonempty prior histories; runs evaluation; asserts the original
    `prediction_history` and `proposal_history` tuples are byte-for-byte
    equal to a pre-call snapshot (`tuple()` of the inputs taken before
    the call).
29. `test_evaluate_returns_trainer_liveness_evaluation_dataclass.py` —
    asserts `type(result) is TrainerLivenessEvaluation`,
    `dataclasses.is_dataclass(result)`, and that the dataclass is
    frozen (`pytest.raises(FrozenInstanceError)` on field assignment).
30. `test_evaluate_passes_now_ms_into_compose.py` — uses a
    `_FixedClock` returning `1_000_000`, supplies a prior history of
    length 1 with `observation_ts_ms=999_500` for the prediction
    stream, supplies a `GrowthWindowConfig` whose window is exactly
    1000ms; asserts that the resulting snapshot's
    `prediction_stream_id_growth` reflects exactly the observations
    inside that 1000ms window relative to `now_ms = 1_000_000` (i.e.
    the function used the same `now_ms` for compose).
31. `test_evaluate_returns_snapshot_with_growth_from_history.py` —
    supplies prior histories with two observations per stream that
    have distinct `stream_id` values; supplies fresh observations from
    `_FakeReader`; asserts
    `result.snapshot.prediction_stream_id_growth` and
    `result.snapshot.proposal_stream_id_growth` are nonnegative ints
    and equal what β's `compute_stream_id_growth_in_window` would
    return for the new histories.
32. `test_evaluate_propagates_collector_errors.py` — passes
    `prediction_stream_name=""` (collector itself rejects empty
    stream names) — but since the service rejects empty names FIRST,
    construct the error path differently: pass a `_FakeReader` whose
    `latest_stream_id` returns the integer `42` (not a str, not None).
    Assert that the collector-level error propagates as
    `ObservationCollectorError` (because the collector's contract
    accepts whatever the reader returns; if the reader contract
    requires `str | None`, the resulting StreamIdObservation
    construction inside the collector raises). NOTE: if the existing
    collector does NOT raise on a non-str id and instead constructs
    a `StreamIdObservation` with `stream_id=42`, this test must be
    rewritten in the implementation report to instead exercise
    `extend_observation_history`'s error path: pass an invalid
    `prior_history` element AFTER the service's own validation
    succeeds — which is impossible because the service validates
    first. In that case this test asserts that the service's
    validation order matches the spec by inducing
    `ObservationCollectorError` via a deliberate mismatch in collector
    arguments (e.g., monkeypatch
    `v2.backend.app.services.trainer_parity.liveness_service.collect_stream_id_observations`
    to a stub that raises `ObservationCollectorError("forced", field="reader")`)
    and asserts the error propagates unchanged.

### Forbidden tokens & cross-isolation

(Test 32 above plus the following two completes the 32-file count by
folding 33 and 34 into a unified guard pair below.)

33. `test_service_milestone_forbidden_tokens.py` — builds every
    forbidden literal from the canonical spec list (112 §
    "Forbidden tokens") at runtime via string concatenation and
    scans the four authored source files plus the 32 new test files.
    Asserts every literal has zero hits across every scanned file.
34. `test_service_does_not_import_factory_or_url_env.py` —
    `import v2.backend.app.services.trainer_parity` then asserts
    `"v2.backend.app.adapters.redis_v2.factory" not in sys.modules`
    and `"v2.backend.app.adapters.redis_v2.url_env" not in sys.modules`.

The implementation task creates exactly 32 test files. The plan above
lists 34 test names; the implementation report MUST resolve the
final 32 by either consolidating tests 23/24/25 into a smaller set
OR by dropping test 32's nested branch into a single deterministic
monkeypatch case. The implementation task records the final 32 file
names in 116 (implementation report); Codex review (092) treats the
116 list as authoritative for rubric line counts.

## Validation commands (run by 091 implementation task)

- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ v2/backend/tests/unit/domain/liveness_stream_growth/ v2/backend/tests/unit/domain/trainer_liveness_composition/ v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ -q`
- `python -m py_compile v2/backend/app/services/trainer_parity/__init__.py v2/backend/app/services/trainer_parity/errors.py v2/backend/app/services/trainer_parity/evaluation.py v2/backend/app/services/trainer_parity/liveness_service.py`
- `git status -s v2/backend/app/adapters/ v2/backend/app/domain/ v2/backend/app/api/ v2/backend/app/cli/ v2/backend/app/jobs/ v2/backend/app/main.py v2/frontend/`

All commands MUST exit 0 and report zero failures / zero errors. Any
non-zero pytest exit, any extra modified file in `git status`, or any
failed `py_compile` is a hard fail; the task emits a FAIL marker.

## Pass criteria

091 emits
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`
to 117 only when:

1. All 32 test files exist and pass.
2. All four authored source files compile via `py_compile`.
3. The forbidden-token guard reports zero hits.
4. `git status -s` over the cross-isolation paths returns zero lines.
5. The 116 implementation report enumerates the exact 32 test file
   names actually created and the per-rubric pass evidence.
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/113_PHASE_2E1D_SERVICE_COMPOSITION_TEST_PLAN.md
