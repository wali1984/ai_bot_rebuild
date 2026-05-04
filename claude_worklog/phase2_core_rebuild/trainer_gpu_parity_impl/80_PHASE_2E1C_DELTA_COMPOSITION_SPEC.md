# Phase 2E1.C.δ — Trainer Liveness Snapshot Composition Domain Spec

This document is the authoring spec for Phase 2E1.C.δ of REQ_0006.

It is the third sub-phase of the trainer prediction-worker liveness
detector. It is non-live, non-Redis, non-subprocess, non-network,
non-legacy-mutating, and non-deploying. The domain layer authored here
is a pure-function composition that turns a sequence of pre-collected
`StreamIdObservation` values (β) plus base liveness fields into a
fully-populated α `LivenessSignalSnapshot`, by delegating to β's
`compute_stream_id_growth_in_window` for both the prediction and
proposal stream-id growth integers.

The δ layer exists because α evaluator consumes a
`LivenessSignalSnapshot` whose two `*_stream_id_growth` fields are
already integers, while β only produces those integers from a
sequence of observations. Without δ, no in-process caller can produce
a fully-valid α snapshot from raw observations without duplicating β
logic.

## Predecessor gates

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
  (`trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`).
- 2E1.C.β stream-id growth domain layer:
  `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.C.δ. The 2E1.C.δ implementation task itself encodes the
`PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS` marker as its
predecessor.

## Position in 2E1.C breakdown

- 2E1.C.α — α liveness domain (`v2/backend/app/domain/trainer_liveness/`). Done.
- 2E1.C.β — β stream-id growth domain (`v2/backend/app/domain/liveness_stream_growth/`). Done.
- 2E1.C.δ — δ composition domain (this spec). Pure-domain.
- 2E1.C.γ — read-only Redis adapter that supplies `StreamIdObservation`
  tuples to δ. Deferred to a separate, later sub-phase under its own
  spec; γ is not authored here. δ does not import any Redis client.

This deliberately swaps the α/β/γ/δ alphabetical order so that the
pure-domain composition lands before the Redis adapter, keeping the
in-process safety boundary intact for as long as possible.

## Surface to create

Package: `v2/backend/app/domain/trainer_liveness_composition/`

Files (exact set, no extras):

- `__init__.py` — public surface only.
- `errors.py` — domain-specific exception type.
- `composition_inputs.py` — `LivenessSnapshotBaseInputs` value object.
- `snapshot_composer.py` — pure function
  `compose_liveness_snapshot_with_growth`.

Tests live in `v2/backend/tests/unit/domain/trainer_liveness_composition/`.

The δ package is a **sibling** of the α package
`v2/backend/app/domain/trainer_liveness/` and the β package
`v2/backend/app/domain/liveness_stream_growth/`. δ MAY import from
both α and β. δ MUST NOT modify α or β. δ MUST NOT import any module
under `v2/backend/app/adapters/`, `v2/backend/app/services/`, or any
non-domain V2 package.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `LivenessSnapshotBaseInputs`
2. `compose_liveness_snapshot_with_growth`
3. `TrainerLivenessCompositionError`

No other names are re-exported. No re-export of submodules. No
re-export of internal `_`-prefixed helpers. No re-export of α or β
public symbols.

## `TrainerLivenessCompositionError` (`errors.py`)

A `class TrainerLivenessCompositionError(Exception)` whose
`__init__(self, code: str, *, field: str | None = None) -> None`
stores `code` and `field` on `self`. `__str__` returns
`f"{code} ({field})"` when `field` is non-None, else just `code`. No
inheritance from α or β error types.

## `LivenessSnapshotBaseInputs` (`composition_inputs.py`)

Dataclass `LivenessSnapshotBaseInputs` (`@dataclass(frozen=True, slots=True)`).

Field set, in this order, with these types — these mirror every α
`LivenessSignalSnapshot` field EXCEPT the two `*_stream_id_growth`
integers, which δ derives from β:

- `trainer_pid: int | None`
- `trainer_rss_bytes: int | None`
- `trainer_heartbeat_ts_ms: int | None`
- `prediction_worker_pid: int | None`
- `prediction_worker_alive: bool`
- `last_prediction_ts_ms: int | None`
- `last_gpu_batch_ts_ms: int | None`
- `last_deconflict_ts_ms: int | None`
- `last_proposal_ts_ms: int | None`
- `fatal_log_signature_observed: bool`
- `observation_ts_ms: int`

Validation in `__post_init__`:

- `prediction_worker_alive` MUST be `bool` (`isinstance(..., bool)`).
- `fatal_log_signature_observed` MUST be `bool`.
- `observation_ts_ms` MUST be `int` and `>= 0`.
- All other fields are passed through unchanged. The α
  `LivenessSignalSnapshot.__post_init__` performs its own validation
  on the same fields and is the canonical authority; δ MUST NOT
  re-implement α-side cross-field rules (for example
  `rss_requires_trainer_pid`).
- On any δ-side validation failure, raise
  `TrainerLivenessCompositionError(code, field=...)` with code from
  this enumerated set: `"must_be_bool"`, `"must_be_int"`,
  `"must_be_nonnegative"`. δ MUST NOT raise α `LivenessDomainError`
  or β `LivenessStreamGrowthDomainError` directly.

## `compose_liveness_snapshot_with_growth` (`snapshot_composer.py`)

Signature:

```
def compose_liveness_snapshot_with_growth(
    base_inputs: LivenessSnapshotBaseInputs,
    *,
    prediction_observations: tuple[StreamIdObservation, ...],
    proposal_observations: tuple[StreamIdObservation, ...],
    growth_config: GrowthWindowConfig,
    now_ms: int,
    prediction_stream_name: str,
    proposal_stream_name: str,
) -> LivenessSignalSnapshot
```

Behavior contract (in this exact order; deviation is a hard fail):

1. Type-check `base_inputs` is a `LivenessSnapshotBaseInputs`. On
   mismatch, raise `TrainerLivenessCompositionError(
   "must_be_liveness_snapshot_base_inputs", field="base_inputs")`.
2. Type-check `prediction_observations` is a `tuple`. On mismatch,
   raise `TrainerLivenessCompositionError("observations_not_tuple",
   field="prediction_observations")`.
3. Type-check `proposal_observations` is a `tuple`. On mismatch,
   raise `TrainerLivenessCompositionError("observations_not_tuple",
   field="proposal_observations")`.
4. Type-check `growth_config` is a `GrowthWindowConfig`. On mismatch,
   raise `TrainerLivenessCompositionError(
   "must_be_growth_window_config", field="growth_config")`.
5. Type-check `now_ms` with `type(now_ms) is int`. On mismatch, raise
   `TrainerLivenessCompositionError("must_be_int", field="now_ms")`.
   Then check `now_ms >= 0`; on violation raise
   `TrainerLivenessCompositionError("must_be_nonnegative",
   field="now_ms")`.
6. Type-check `prediction_stream_name` and `proposal_stream_name` are
   non-empty `str` instances. On violation raise
   `TrainerLivenessCompositionError("must_be_nonempty_str",
   field="prediction_stream_name")` /
   `field="proposal_stream_name"`.
7. Reject equal stream names: if
   `prediction_stream_name == proposal_stream_name`, raise
   `TrainerLivenessCompositionError(
   "stream_names_must_differ", field="proposal_stream_name")`.
   Rationale: in the live trainer the prediction and proposal Redis
   streams are distinct keys, and δ is the canonical place to enforce
   that invariant before β's per-stream filter runs.
8. Compute `prediction_stream_id_growth = compute_stream_id_growth_in_window(
   prediction_observations, growth_config, now_ms,
   stream_name=prediction_stream_name)`. β-side errors propagate
   unchanged — δ does NOT swallow or rewrap them.
9. Compute `proposal_stream_id_growth` analogously over
   `proposal_observations` and `proposal_stream_name`. β-side errors
   propagate unchanged.
10. Construct and return a NEW
    `LivenessSignalSnapshot(...)` whose every field comes from
    `base_inputs` except the two `*_stream_id_growth` fields, which
    are the β-computed integers from steps 8 and 9. α-side errors
    raised by `LivenessSignalSnapshot.__post_init__` propagate
    unchanged.
11. δ MUST NOT mutate `base_inputs`, the observation tuples, or the
    growth config. The function is referentially transparent.

The composer is pure-Python, sync, no-async, no-clock, no-Redis, no
file I/O, no network, no logging side effect.

## Cross-isolation rules

- δ MUST import α and β only from their public surfaces. Allowed
  imports:
  - `from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot`
    (also `LivenessDomainError` only if needed for explicit
    propagation comments; δ does NOT raise it).
  - `from v2.backend.app.domain.liveness_stream_growth import (
        StreamIdObservation, GrowthWindowConfig,
        compute_stream_id_growth_in_window,
        LivenessStreamGrowthDomainError)`.
- δ MUST NOT touch α or β internal modules
  (`from v2.backend.app.domain.trainer_liveness.evaluator import …`
  and equivalent are forbidden for δ).
- α MUST NOT be modified. β MUST NOT be modified.
- δ MUST NOT add or modify any file under
  `v2/backend/app/adapters/`, `v2/backend/app/services/`,
  `v2/backend/app/api/`, or `v2/backend/app/main.py`.

## Forbidden in this sub-phase

- Redis client of any kind (`redis`, `aioredis`, `redis.asyncio`).
- Subprocess (`subprocess`, `os.system`, `os.popen`, `pty`).
- Network (`socket`, `urllib`, `requests`, `httpx`, `aiohttp`).
- Numerical/ML libraries (`numpy`, `torch`, `tensorflow`, `cuda`).
- Clock (`time.time(`, `datetime.now(`, `datetime.utcnow(`); `now_ms`
  is an injected integer.
- Any reference to `legacy_reference`, `/home/wali/Desktop/AI BOT`,
  `BINANCE_API_KEY`, `BINANCE_API_SECRET`, or
  `live_trading_enabled = true`.
- Any γ-side observation collector. γ is a separate sub-phase.

## Live-trading status

LIVE TRADING: BLOCKED. No δ artifact may change this.

PHASE2E1C_DELTA_COMPOSITION_SPEC_READY
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/80_PHASE_2E1C_DELTA_COMPOSITION_SPEC.md
