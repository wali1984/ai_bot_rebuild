# Phase 2E1.C.β — Test Plan

This is the authoring spec for the unit-test surface that 2E1.C.β
implementers must produce in
`v2/backend/tests/unit/domain/liveness_stream_growth/`.

The test surface is local-only, deterministic, free of network /
subprocess / Redis / clock reads, and fully synchronous.

## Test files (exact set, no extras)

1. `__init__.py` — empty marker.
2. `test_stream_observation_validation.py` — `StreamIdObservation`
   `__post_init__` invariants.
3. `test_stream_observation_parsed_id.py` — `parsed_id()` helper
   correctness.
4. `test_growth_window_config_validation.py` — `GrowthWindowConfig`
   `__post_init__` invariants.
5. `test_growth_calculator_input_validation.py` — argument-type
   validation in `compute_stream_id_growth_in_window`.
6. `test_growth_calculator_window_boundary.py` — strict-`>` boundary
   default, inclusive-`>=` boundary opt-in.
7. `test_growth_calculator_distinctness.py` — distinct-stream-id
   counting, including duplicate detection.
8. `test_growth_calculator_stream_name_filter.py` — mixed-stream
   tuples are filtered by `stream_name`.
9. `test_growth_calculator_future_observation.py` — future-stamped
   observation raises, regardless of position in the tuple.
10. `test_growth_calculator_zero_growth_cases.py` — empty input
    tuple, all-out-of-window, all-other-stream — each returns `0`
    without raising.
11. `test_public_surface.py` — `__all__` is exactly the four declared
    names; no submodule re-export; α package is not imported by β.
12. `test_forbidden_tokens.py` — recursive token grep against
    β source and test trees.

## Required rubric coverage (each row maps to at least one test case)

### `StreamIdObservation` validation

| Rubric | Required behavior |
| --- | --- |
| O-1 | Empty `stream_name` raises. |
| O-2 | `stream_name` with whitespace raises. |
| O-3 | `stream_name` containing `/` or `\` raises. |
| O-4 | `stream_name` with control chars raises. |
| O-5 | `stream_id` lacking a `-` raises. |
| O-6 | `stream_id` with multiple `-` raises. |
| O-7 | `stream_id` parts that are not pure decimal raise (e.g. `0x1-0`, `1.0-0`, `-1-0`, `1--0`). |
| O-8 | `stream_id` with leading whitespace raises. |
| O-9 | `stream_id` with very large parts (> 2**63) is accepted. |
| O-10 | Negative `observation_ts_ms` raises. |
| O-11 | Non-int `observation_ts_ms` (`float`, `bool`, `str`) raises; `bool` is treated as non-int. |
| O-12 | Frozen-dataclass mutation raises `dataclasses.FrozenInstanceError`. |

### `parsed_id` helper

| Rubric | Required behavior |
| --- | --- |
| P-1 | `parsed_id()` returns `(ms, seq)` with both `int`. |
| P-2 | `parsed_id()` accepts canonical Redis-stream-id literals from real-world traces (large ms, zero seq, large seq). |
| P-3 | `parsed_id()` raises if state has been bypassed (impossible by construction; sanity test against monkey-patched private state confirms that the helper does not silently coerce floats). |

### `GrowthWindowConfig` validation

| Rubric | Required behavior |
| --- | --- |
| W-1 | `window_ms == 0` raises. |
| W-2 | Negative `window_ms` raises. |
| W-3 | Non-int `window_ms` raises. |
| W-4 | `boundary_inclusive` of type `int` (e.g. `1`) raises (must be exactly `bool`). |
| W-5 | Default `boundary_inclusive` is `False`. |

### `compute_stream_id_growth_in_window` argument validation

| Rubric | Required behavior |
| --- | --- |
| A-1 | `observations` as `list` raises `observations_not_tuple`. |
| A-2 | `observations` as generator raises. |
| A-3 | `config` as a non-`GrowthWindowConfig` instance raises. |
| A-4 | `now_ms` negative raises. |
| A-5 | `now_ms` non-int (`float`, `bool`) raises. |
| A-6 | `stream_name` empty raises. |
| A-7 | `stream_name` containing whitespace raises. |
| A-8 | `stream_name` is keyword-only (positional call raises `TypeError`). |

### Window boundary semantics

| Rubric | Required behavior |
| --- | --- |
| B-1 | Default `boundary_inclusive=False`: an observation with `observation_ts_ms == now_ms - window_ms` is **excluded**. |
| B-2 | Default `boundary_inclusive=False`: an observation with `observation_ts_ms == now_ms - window_ms + 1` is **included**. |
| B-3 | `boundary_inclusive=True`: an observation with `observation_ts_ms == now_ms - window_ms` is **included**. |
| B-4 | An observation with `observation_ts_ms == now_ms` is **included** for both boundary policies. |
| B-5 | An observation with `observation_ts_ms == 0` and `now_ms < window_ms` is included iff inside the window per chosen policy. |

### Distinctness counting

| Rubric | Required behavior |
| --- | --- |
| D-1 | Two observations with the same `stream_id` literal in the window count once. |
| D-2 | Two observations with semantically equal but textually different `stream_id` (e.g. `100-0` vs `0100-0`) count as distinct (β counts on the literal string per spec). |
| D-3 | Two observations with the same `stream_id` but different `observation_ts_ms` count once if both are in window; if only one is in window, count is one. |
| D-4 | Distinctness is per-stream: same `stream_id` literal under two different `stream_name` values does not collapse (filter applies first, distinctness applies second). |

### `stream_name` filter

| Rubric | Required behavior |
| --- | --- |
| F-1 | Mixed-stream tuple is filtered: only the matching `stream_name` rows participate. |
| F-2 | A tuple with zero matching rows returns `0` without raising. |
| F-3 | Filter happens regardless of `observation_ts_ms` (an out-of-window matching row is filtered in by name then filtered out by window). |

### Future-observation rejection

| Rubric | Required behavior |
| --- | --- |
| FT-1 | A single observation with `observation_ts_ms == now_ms + 1` raises. |
| FT-2 | A future-stamped observation at the **end** of the tuple still raises (no early return). |
| FT-3 | A future-stamped observation **of a non-matching stream** still raises (the future check runs before the stream-name filter). |
| FT-4 | A future-stamped observation at `now_ms == 0` raises. |

### Zero-growth cases

| Rubric | Required behavior |
| --- | --- |
| Z-1 | Empty observations tuple returns `0`. |
| Z-2 | All observations out of window returns `0`. |
| Z-3 | All observations of other streams returns `0`. |
| Z-4 | Mix of out-of-window and other-stream returns `0`. |

### Public surface

| Rubric | Required behavior |
| --- | --- |
| PS-1 | `__all__` is exactly `("StreamIdObservation", "GrowthWindowConfig", "compute_stream_id_growth_in_window", "LivenessStreamGrowthDomainError")`. |
| PS-2 | β package import does NOT trigger import of `v2.backend.app.domain.trainer_liveness` (verified via `sys.modules` snapshot diff). |
| PS-3 | `parsed_id` helper is NOT in `__all__`. |
| PS-4 | Internal `_` -prefixed helpers are NOT in `__all__`. |

### Forbidden-token grep

`test_forbidden_tokens.py` recursively greps the β source tree
(`v2/backend/app/domain/liveness_stream_growth/`) and the β test tree
(`v2/backend/tests/unit/domain/liveness_stream_growth/`) for each
forbidden token below. Every count MUST be zero. Any non-zero count
is a hard test failure.

Tokens (case-sensitive unless noted):

- `import redis`
- `from redis`
- `aioredis`
- `subprocess`
- `os.system`
- `os.popen`
- `socket`
- `requests` (case-sensitive — Python package import name)
- `httpx`
- `urllib`
- `legacy_reference`
- `/home/wali/Desktop/AI BOT/`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `time.time(`
- `datetime.now(`
- `datetime.utcnow(`
- `numpy`
- `torch`
- `tensorflow`
- `XLEN`
- `xlen` (case-sensitive)
- `asyncio`
- `async def`
- `from v2.backend.app.domain.trainer_liveness` (β must not import α).

## Test invocation contract

Tests run via:

```
v2/.venv-control-plane/bin/python -m pytest \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  -q --no-header --maxfail=1
```

The validation task captures the raw stdout / stderr in the
validation run-log file and asserts:

- exit code 0;
- summary line shows zero failures;
- summary line shows ≥ 1 collected test per rubric class above
  (counts mapped in the validation report).

No network access. No Redis access. No subprocess beyond pytest itself.
No file I/O outside the v2 tests subtree. The validation task MUST NOT
import the legacy trainer venv.

PHASE2E1C_BETA_TRAINER_LIVENESS_TEST_PLAN_READY
