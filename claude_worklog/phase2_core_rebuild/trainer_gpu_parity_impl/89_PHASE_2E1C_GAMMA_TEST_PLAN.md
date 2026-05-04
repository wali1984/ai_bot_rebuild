# Phase 2E1.C.gamma - Test Plan

Tests live under
`v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`.

Test runner: `.venv/bin/python -m pytest
v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ -q`.

Tests use only stdlib + pytest + the gamma public surface + the beta
public surface. No Redis mocks, no network mocks, no subprocess
mocks, no monkey-patches that touch system clock or filesystem.

## Required test files (exact set, no extras)

- `__init__.py` - empty package marker.
- `test_public_surface.py`
- `test_observation_collector_error_format.py`
- `test_in_memory_reader_input_validation.py`
- `test_in_memory_reader_returns_configured_id.py`
- `test_in_memory_reader_returns_none_for_unconfigured_stream.py`
- `test_in_memory_reader_returns_none_when_configured_none.py`
- `test_in_memory_reader_satisfies_protocol.py`
- `test_in_memory_reader_does_not_mutate_input_dict.py`
- `test_collect_validates_reader_protocol.py`
- `test_collect_validates_stream_names_tuple.py`
- `test_collect_validates_stream_names_each_nonempty_str.py`
- `test_collect_validates_clock_callable.py`
- `test_collect_validates_clock_returns_int.py`
- `test_collect_validates_clock_nonnegative.py`
- `test_collect_calls_clock_exactly_once_per_invocation.py`
- `test_collect_returns_observations_in_input_order.py`
- `test_collect_skips_stream_with_none_latest_id.py`
- `test_collect_propagates_beta_observation_validation.py`
- `test_collect_does_not_mutate_inputs.py`
- `test_collect_observation_ts_consistent_within_cycle.py`
- `test_extend_history_appends_in_order.py`
- `test_extend_history_returns_unchanged_when_under_max.py`
- `test_extend_history_truncates_oldest_when_exceeding_max.py`
- `test_extend_history_validates_history_tuple.py`
- `test_extend_history_validates_new_tuple.py`
- `test_extend_history_validates_history_entry_types.py`
- `test_extend_history_validates_new_entry_types.py`
- `test_extend_history_validates_max_total_int.py`
- `test_extend_history_validates_max_total_positive.py`
- `test_extend_history_does_not_mutate_inputs.py`
- `test_forbidden_tokens.py`

## Required rubric coverage

| # | Rubric | Test file |
| --- | --- | --- |
| 1 | `__init__` exports exactly the five documented names and nothing else, with `__all__` in the documented order | `test_public_surface.py` |
| 2 | `ObservationCollectorError` stores `code` and `field`, formats with and without field, and does not inherit from alpha, beta, or delta domain errors | `test_observation_collector_error_format.py` |
| 3 | `InMemoryStreamLatestIdReader.__init__` rejects non-dict `latest_ids`, non-string keys, and non-string-or-None values | `test_in_memory_reader_input_validation.py` |
| 4 | `InMemoryStreamLatestIdReader.latest_stream_id` returns a configured latest id | `test_in_memory_reader_returns_configured_id.py` |
| 5 | `InMemoryStreamLatestIdReader.latest_stream_id` returns `None` for an unconfigured stream | `test_in_memory_reader_returns_none_for_unconfigured_stream.py` |
| 6 | `InMemoryStreamLatestIdReader.latest_stream_id` returns `None` when configured with `None` | `test_in_memory_reader_returns_none_when_configured_none.py` |
| 7 | `InMemoryStreamLatestIdReader` satisfies `isinstance(reader, StreamLatestIdReader)` at runtime | `test_in_memory_reader_satisfies_protocol.py` |
| 8 | `InMemoryStreamLatestIdReader` stores a defensive copy and does not mutate or observe later caller dict mutation | `test_in_memory_reader_does_not_mutate_input_dict.py` |
| 9 | `collect_stream_id_observations` rejects a reader without callable `latest_stream_id` before validating later arguments | `test_collect_validates_reader_protocol.py` |
| 10 | `collect_stream_id_observations` rejects non-tuple `stream_names` | `test_collect_validates_stream_names_tuple.py` |
| 11 | `collect_stream_id_observations` rejects non-string and empty entries in `stream_names` | `test_collect_validates_stream_names_each_nonempty_str.py` |
| 12 | `collect_stream_id_observations` rejects non-callable `clock_ms` | `test_collect_validates_clock_callable.py` |
| 13 | `collect_stream_id_observations` rejects `clock_ms` results whose exact type is not `int`, including `bool` | `test_collect_validates_clock_returns_int.py` |
| 14 | `collect_stream_id_observations` rejects negative `now_ms` | `test_collect_validates_clock_nonnegative.py` |
| 15 | `collect_stream_id_observations` calls `clock_ms` exactly once per invocation | `test_collect_calls_clock_exactly_once_per_invocation.py` |
| 16 | `collect_stream_id_observations` returns beta `StreamIdObservation` values in input stream order | `test_collect_returns_observations_in_input_order.py` |
| 17 | `collect_stream_id_observations` skips streams whose reader returns `None` | `test_collect_skips_stream_with_none_latest_id.py` |
| 18 | `collect_stream_id_observations` propagates beta `LivenessStreamGrowthDomainError` unchanged | `test_collect_propagates_beta_observation_validation.py` |
| 19 | `collect_stream_id_observations` does not mutate reader or `stream_names` | `test_collect_does_not_mutate_inputs.py` |
| 20 | All observations produced by one `collect_stream_id_observations` call share the same `observation_ts_ms` | `test_collect_observation_ts_consistent_within_cycle.py` |
| 21 | `extend_observation_history` appends `new` observations after `history` in order | `test_extend_history_appends_in_order.py` |
| 22 | `extend_observation_history` returns the combined tuple unchanged when within `max_total` | `test_extend_history_returns_unchanged_when_under_max.py` |
| 23 | `extend_observation_history` truncates from the front when over `max_total` | `test_extend_history_truncates_oldest_when_exceeding_max.py` |
| 24 | `extend_observation_history` rejects non-tuple `history` | `test_extend_history_validates_history_tuple.py` |
| 25 | `extend_observation_history` rejects non-tuple `new` | `test_extend_history_validates_new_tuple.py` |
| 26 | `extend_observation_history` rejects non-`StreamIdObservation` entries in `history` | `test_extend_history_validates_history_entry_types.py` |
| 27 | `extend_observation_history` rejects non-`StreamIdObservation` entries in `new` | `test_extend_history_validates_new_entry_types.py` |
| 28 | `extend_observation_history` rejects `max_total` whose exact type is not `int`, including `bool` | `test_extend_history_validates_max_total_int.py` |
| 29 | `extend_observation_history` rejects `max_total < 1` | `test_extend_history_validates_max_total_positive.py` |
| 30 | `extend_observation_history` does not mutate `history` or `new` | `test_extend_history_does_not_mutate_inputs.py` |
| 31 | Forbidden-token grep returns zero hits for the canonical list across the gamma source and test trees | `test_forbidden_tokens.py` |

## Forbidden-token grep (canonical list)

The gamma source and test trees MUST contain zero hits for each of
the following tokens, using case-sensitive substring match:

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
- `time.monotonic(`
- `datetime.now(`
- `datetime.utcnow(`

The implementer MUST run this grep across both
`v2/backend/app/domain/trainer_liveness_observation_collector/` and
`v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
and record the per-token counts in the implementation report.

`test_forbidden_tokens.py` MUST be a self-contained pytest test that
walks the gamma source and test trees with `pathlib.Path.rglob('*.py')`
and asserts zero matches per token. The test file itself MUST NOT
contain any of the listed tokens as bare literals; reference each
token via a tuple of fragments concatenated at runtime so that the
grep over the test tree also returns zero.

## END_FILE marker leak self-check

Self-check scope is intentionally narrow: the implementer MUST run

```
rg "^END_FILE:" v2/backend/app/domain/trainer_liveness_observation_collector/
rg "^END_FILE:" v2/backend/tests/unit/domain/trainer_liveness_observation_collector/
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/92_2E1C_GAMMA_GO_NO_GO.md
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/93_2E1C_GAMMA_IMPLEMENTATION_REPORT.md
```

All four counts MUST be zero. Any non-zero count is a hard fail.

The grep is deliberately scoped to the four gamma-authored output
sets (gamma source tree, gamma test tree, and the two
implementer-authored status markdown files). Older planner
directives in the same `trainer_gpu_parity_impl/` tree may
legitimately contain marker lines from prior planner-emit format;
those are out of scope for this sub-phase's self-check and must not
be modified by the implementer.

## py_compile check

Every authored Python file MUST pass `python -m py_compile <path>`
without warnings or errors.

## pytest invocation contract

The implementer MUST run:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ \
  -q
```

The summary line MUST show zero failures and zero errors. Any
failure or error is a hard fail.

## Cross-isolation regression check

After authoring gamma, re-run alpha, beta, and delta tests:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ \
  -q
```

These suites MUST remain green. Gamma MUST NOT have modified alpha,
beta, or delta. Authoring gamma MUST NOT have caused any alpha,
beta, or delta file to change. The implementer MUST capture
`git status -s v2/backend/app/domain/trainer_liveness/
v2/backend/app/domain/liveness_stream_growth/
v2/backend/app/domain/trainer_liveness_composition/` and confirm
all return zero modified lines, and record that proof in the
implementation report.

PHASE2E1C_GAMMA_TEST_PLAN_READY
