# Phase 2E1.C.β — Stream-Id Growth Windowing Domain Spec

This document is the authoring spec for Phase 2E1.C.β of REQ_0006.

It is the second sub-phase of the trainer prediction-worker liveness
detector. It is non-live, non-Redis, non-subprocess, non-network,
non-legacy-mutating, and non-deploying. The domain layer authored here
is a pure-function calculator over a pre-collected sequence of stream-id
observations. The actual read-only Redis adapter that **collects** those
observations is deferred to Phase 2E1.C.γ; β does not touch Redis.

The β layer exists because the α evaluator treats
`LivenessSignalSnapshot.prediction_stream_id_growth` as already measured
over the SLA window. The window-correctness contract therefore lives in
β. β is the canonical home for that contract.

## Predecessor gates

- Trainer GPU parity plan:
  `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS`
  (`trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md`).
- Liveness fix spec:
  `PHASE2_TRAINER_GPU_PARITY_PREDICTION_WORKER_LIVENESS_READY`
  (`trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`).
- Trainer worker supervision requirement:
  `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.
- 2E1.A subprocess adapter:
  `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract:
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`)
  AND `PHASE2E1B_LOCAL_VALIDATION_PASSED`
  (`trainer_gpu_parity_impl/38_2E1B_VALIDATION_GO_NO_GO.md`).
- 2E1.C.α liveness domain layer:
  `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/51_2E1C_ALPHA_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.C.β. The 2E1.C.β implementation task itself encodes the
`PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS` marker as its
predecessor.

## Surface to create

Package: `v2/backend/app/domain/liveness_stream_growth/`

Files (exact set, no extras):

- `__init__.py` — public surface only.
- `errors.py` — domain-specific exception type.
- `stream_observation.py` — `StreamIdObservation` value object.
- `growth_window_config.py` — `GrowthWindowConfig` value object.
- `growth_calculator.py` — pure function
  `compute_stream_id_growth_in_window`.

Tests live in `v2/backend/tests/unit/domain/liveness_stream_growth/`.

The β package is a **sibling** of the existing α package
`v2/backend/app/domain/trainer_liveness/`. β does NOT import from α
and α MUST NOT be modified by this phase. The composition that joins β
output into an α `LivenessSignalSnapshot.prediction_stream_id_growth`
field is deferred to Phase 2E1.C.δ.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `StreamIdObservation`
2. `GrowthWindowConfig`
3. `compute_stream_id_growth_in_window`
4. `LivenessStreamGrowthDomainError`

No other names are re-exported. No re-export of submodules. No
re-export of internal `_` -prefixed helpers.

## `StreamIdObservation` (`stream_observation.py`)

Dataclass `StreamIdObservation` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order, with these types:

- `stream_name: str` — non-empty, lowercase or snake-case identifier,
  no whitespace, no path separator. Validated by post-init.
- `stream_id: str` — non-empty Redis stream-id literal of the form
  `<ms>-<seq>` where `<ms>` is a non-negative integer string and
  `<seq>` is a non-negative integer string. Validated by parsing both
  parts; both must be `>= 0`. The full literal MAY exceed 19 digits in
  either component; β does not impose width caps.
- `observation_ts_ms: int` — when V2 saw this stream-id. `>= 0`.

`__post_init__` invariants:

- `stream_name` is a non-empty `str`, no leading/trailing whitespace,
  contains no whitespace at all, contains no `/` or `\`, and matches
  `^[A-Za-z0-9_:.-]+$`.
- `stream_id` is non-empty, contains exactly one `-`, and both parts
  parse as non-negative `int` via `int(part, 10)`. Float, signed, or
  hex literals raise. `"-"`, `""`, `"1-"`, `"-1"` raise.
- `observation_ts_ms` is `int` and `>= 0`.

Violations raise `LivenessStreamGrowthDomainError`.

`StreamIdObservation` exposes a single helper:

```
def parsed_id(self) -> tuple[int, int]: ...
```

returning `(ms, seq)` parsed once at call time using `int(part, 10)`.
The helper does no caching; β stays free of mutable state. The helper
MUST NOT be re-exported from `__init__.py`; tests import it from the
module directly.

## `GrowthWindowConfig` (`growth_window_config.py`)

Dataclass `GrowthWindowConfig` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order:

- `window_ms: int` — width of the sliding window. `>= 1`.
- `boundary_inclusive: bool` — whether observations at exactly
  `now_ms - window_ms` belong to the window. Default `False`. β
  requires the explicit boundary policy to make Codex review
  unambiguous; the α evaluator's strict-`>` SLA semantics imply
  `False` for parity, so the implementation MUST default to `False`
  but MUST accept `True` for callers that explicitly choose the
  inclusive variant.

`__post_init__` invariants:

- `window_ms >= 1`. Zero or negative values raise.
- `boundary_inclusive` is exactly `bool` (not truthy `int`); validate
  with `type(self.boundary_inclusive) is bool`.

Violations raise `LivenessStreamGrowthDomainError`.

## `compute_stream_id_growth_in_window` (`growth_calculator.py`)

Single pure function:

```
def compute_stream_id_growth_in_window(
    observations: tuple[StreamIdObservation, ...],
    config: GrowthWindowConfig,
    now_ms: int,
    *,
    stream_name: str,
) -> int: ...
```

Behavior:

- Validate inputs:
  - `observations` is a `tuple`. `list`, generator, set, or other
    iterables raise `LivenessStreamGrowthDomainError(reason="observations_not_tuple")`.
  - `config` is a `GrowthWindowConfig` instance. Other types raise.
  - `now_ms` is `int` and `>= 0`. Otherwise raise.
  - `stream_name` is `str` and matches the same character class as
    `StreamIdObservation.stream_name`. Otherwise raise.
- Compute the window lower bound `lo = now_ms - config.window_ms`.
- Iterate `observations`. An observation `o` is **in window** when:
  - `o.stream_name == stream_name`, AND
  - `o.observation_ts_ms <= now_ms`, AND
  - either `o.observation_ts_ms > lo` (strict, when
    `config.boundary_inclusive is False`) or
    `o.observation_ts_ms >= lo` (inclusive, when
    `config.boundary_inclusive is True`).
- Reject any observation with `o.observation_ts_ms > now_ms` by
  raising `LivenessStreamGrowthDomainError(reason="observation_in_future")`.
  The β layer treats future-stamped observations as a corruption
  signal, never as a silent drop.
- Among the in-window observations, count **distinct** `stream_id`
  literals. Distinctness is computed on the literal string (after
  `__post_init__` validation) — not on `parsed_id()` — because Redis
  stream-id strings are canonical for distinctness. Return the count
  as an `int`.
- Observations whose `stream_name` does not match `stream_name` are
  silently ignored (a single observations tuple may carry mixed
  streams; β filters by name). This is **not** a corruption signal.
- The function MUST NOT short-circuit on the first match. It MUST
  iterate the full input tuple to surface any future-stamped
  observation regardless of position.

The function MUST:

- Be pure: no I/O, no clock read, no subprocess, no Redis, no
  network, no random.
- Not import legacy modules.
- Not import α package (`v2.backend.app.domain.trainer_liveness`).
- Not write to mutable state outside the local frame.
- Use only `int`, `str`, `bool`, `tuple`, `set`, `frozenset`,
  `dataclasses`, `typing` from the stdlib.

## `errors.py`

Single exception:

- `LivenessStreamGrowthDomainError(ValueError)`

It carries `reason: str` and `field: str | None` attributes. Constructor
signature is `__init__(self, reason: str, *, field: str | None = None)`.
This is a separate class from α's `LivenessDomainError`; β does not
re-use α's error type to keep the two packages decoupled.

## Hard exclusions for Phase 2E1.C.β

- No subprocess / shell calls.
- No file I/O.
- No network.
- No Redis import or client construction.
- No legacy module import.
- No environment variable reads.
- No reliance on the subprocess adapter from Phase 2E1.A.
- No reliance on the trainer-output contract from Phase 2E1.B.
- No reliance on the α liveness domain from Phase 2E1.C.α (β stays
  self-contained; the join with α happens only in 2E1.C.δ).
- No live trainer call.
- No model loading or checkpoint loading.
- No GPU code.
- No async I/O. β is fully synchronous.
- No use of `time.time()` / `datetime.now()` / `datetime.utcnow()`
  inside the module (timestamps come in as int args).
- No `numpy` import.
- No emission to V2 Redis namespace; the β API returns an `int`
  in-process only.
- No `xlen` / `XLEN` literal in source (per the liveness fix spec
  out-of-band requirement that bans `XLEN`-style growth measurement).

## END_FILE marker hygiene

The 2E1.B regression class — a leaked `END_FILE: <path>` text marker
inside a Python source file — MUST NOT recur. Authoring tooling MUST
emit exactly one trailing newline at end-of-file and MUST NOT include
any `END_FILE:` marker in the source body. Validation includes a
recursive `rg "^END_FILE:"` over the β source and test trees with a
required hit count of zero.

## Cross-references

- α evaluator's deferred-window contract:
  `trainer_gpu_parity_impl/42_PHASE_2E1C_ALPHA_LIVENESS_DOMAIN_SPEC.md`,
  rule 4 of `evaluate_liveness`.
- Liveness fix spec out-of-band requirement that bans `XLEN`:
  `trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`,
  "Out-of-band requirements".
- Trainer worker supervision requirement source:
  `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.
- Authoring shape parallels:
  `trainer_gpu_parity_impl/42_PHASE_2E1C_ALPHA_LIVENESS_DOMAIN_SPEC.md`.

PHASE2E1C_BETA_TRAINER_LIVENESS_GROWTH_SPEC_READY
