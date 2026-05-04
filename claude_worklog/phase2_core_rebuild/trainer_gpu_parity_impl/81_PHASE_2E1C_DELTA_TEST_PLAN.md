# Phase 2E1.C.δ — Test Plan

Tests live under
`v2/backend/tests/unit/domain/trainer_liveness_composition/`.

Test runner: `.venv/bin/python -m pytest
v2/backend/tests/unit/domain/trainer_liveness_composition/ -q`.

Tests use only stdlib + pytest. No mocks of Redis, no network mocks,
no monkey-patches that touch system clock or filesystem.

## Required test files (exact set, no extras)

- `__init__.py` — empty package marker.
- `test_public_surface.py`
- `test_composition_inputs_validation.py`
- `test_compose_input_type_checks.py`
- `test_compose_now_ms_validation.py`
- `test_compose_stream_name_validation.py`
- `test_compose_stream_names_must_differ.py`
- `test_compose_calls_beta_calculator_for_prediction_stream.py`
- `test_compose_calls_beta_calculator_for_proposal_stream.py`
- `test_compose_zero_growth_when_no_observations.py`
- `test_compose_returns_alpha_snapshot_dataclass.py`
- `test_compose_does_not_mutate_inputs.py`
- `test_compose_propagates_alpha_validation_errors.py`
- `test_compose_propagates_beta_validation_errors.py`
- `test_compose_distinct_stream_names_handled_independently.py`
- `test_forbidden_tokens.py`

## Required rubric coverage

| # | Rubric | Test file |
| --- | --- | --- |
| 1 | `__init__` exports exactly the three documented names and nothing else | `test_public_surface.py` |
| 2 | `LivenessSnapshotBaseInputs.__post_init__` rejects non-bool `prediction_worker_alive`, non-bool `fatal_log_signature_observed`, negative `observation_ts_ms`, non-int `observation_ts_ms` | `test_composition_inputs_validation.py` |
| 3 | `compose_liveness_snapshot_with_growth` rejects non-`LivenessSnapshotBaseInputs`, non-tuple observations (one test per stream), non-`GrowthWindowConfig` config | `test_compose_input_type_checks.py` |
| 4 | `compose_liveness_snapshot_with_growth` rejects `now_ms` that is `bool`, `float`, `str`, or negative int | `test_compose_now_ms_validation.py` |
| 5 | `compose_liveness_snapshot_with_growth` rejects empty stream names, non-string stream names | `test_compose_stream_name_validation.py` |
| 6 | `compose_liveness_snapshot_with_growth` rejects when prediction and proposal stream names are equal | `test_compose_stream_names_must_differ.py` |
| 7 | `compose_liveness_snapshot_with_growth` populates `prediction_stream_id_growth` from β output for the prediction stream | `test_compose_calls_beta_calculator_for_prediction_stream.py` |
| 8 | `compose_liveness_snapshot_with_growth` populates `proposal_stream_id_growth` from β output for the proposal stream | `test_compose_calls_beta_calculator_for_proposal_stream.py` |
| 9 | Empty observation tuples produce 0 growth on each stream | `test_compose_zero_growth_when_no_observations.py` |
| 10 | Returned object is an instance of α `LivenessSignalSnapshot` and is frozen (mutation raises `dataclasses.FrozenInstanceError`) | `test_compose_returns_alpha_snapshot_dataclass.py` |
| 11 | δ MUST NOT mutate `base_inputs` or observation tuples (compare object identity and contents pre/post) | `test_compose_does_not_mutate_inputs.py` |
| 12 | α-side errors propagate unchanged when α `LivenessSignalSnapshot.__post_init__` rejects a base-input cross-field rule (e.g. `rss_requires_trainer_pid`) | `test_compose_propagates_alpha_validation_errors.py` |
| 13 | β-side errors propagate unchanged when β rejects observations (e.g. future-observation, wrong type) — pytest.raises with the β `LivenessStreamGrowthDomainError` | `test_compose_propagates_beta_validation_errors.py` |
| 14 | Observations that match only the prediction stream produce 0 proposal growth and vice versa, even if both tuples are supplied | `test_compose_distinct_stream_names_handled_independently.py` |
| 15 | Forbidden-token grep: zero hits for the tokens listed in spec 80 'Forbidden in this sub-phase' across the δ source and test trees | `test_forbidden_tokens.py` (uses pathlib + pure-Python text scan; no subprocess) |

## Forbidden-token grep (canonical list)

The δ source and test trees MUST contain zero hits for each of the
following tokens, using case-sensitive substring match:

- `redis`
- `aioredis`
- `redis.asyncio`
- `subprocess`
- `os.system`
- `os.popen`
- `pty`
- `socket`
- `urllib`
- `requests`
- `httpx`
- `aiohttp`
- `numpy`
- `torch`
- `tensorflow`
- `cuda`
- `legacy_reference`
- `/home/wali/Desktop/AI BOT/`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `live_trading_enabled = true`
- `XLEN`
- `xlen`
- `time.time(`
- `datetime.now(`
- `datetime.utcnow(`

The implementer MUST run this grep across both
`v2/backend/app/domain/trainer_liveness_composition/` and
`v2/backend/tests/unit/domain/trainer_liveness_composition/` and
record the per-token counts in the implementation report.

`test_forbidden_tokens.py` MUST be a self-contained pytest test that
walks the δ source and test trees with `pathlib.Path.rglob('*.py')`
and asserts zero matches per token. The test file itself MUST NOT
contain any of the listed tokens as bare literals; reference each
token via a tuple of fragments concatenated at runtime
(e.g. `"red" + "is"`) so that the grep over the test tree also
returns zero.

## END_FILE marker leak self-check

Self-check scope is intentionally narrow: the implementer MUST run

```
rg "^END_FILE:" v2/backend/app/domain/trainer_liveness_composition/
rg "^END_FILE:" v2/backend/tests/unit/domain/trainer_liveness_composition/
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/84_2E1C_DELTA_GO_NO_GO.md
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/85_2E1C_DELTA_IMPLEMENTATION_REPORT.md
```

All four counts MUST be zero. Any non-zero count is a hard fail.

The grep is deliberately scoped to the four δ-authored output sets
(δ source tree, δ test tree, and the two implementer-authored status
markdown files). Older planner directives in the same
`trainer_gpu_parity_impl/` tree (e.g. file 70) may legitimately
contain `END_FILE:` lines from prior planner-emit format; those are
out of scope for this sub-phase's self-check and must not be
modified.

## py_compile check

Every authored Python file MUST pass `python -m py_compile <path>`
without warnings or errors.

## pytest invocation contract

The implementer MUST run:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ -q
```

The summary line MUST show zero failures and zero errors. Any
failure or error is a hard fail.

## Cross-isolation regression check

After authoring δ, re-run α and β tests:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ -q
```

These suites MUST remain green. δ MUST NOT have modified α or β.
Authoring δ MUST NOT have caused any α or β file to change. The
implementer MUST capture `git status -s
v2/backend/app/domain/trainer_liveness/
v2/backend/app/domain/liveness_stream_growth/` and confirm both
return zero modified lines, and record that proof in the
implementation report.

PHASE2E1C_DELTA_TEST_PLAN_READY
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/81_PHASE_2E1C_DELTA_TEST_PLAN.md
