# Phase 2E1.D — Trainer Parity Service Composition Spec

This document is the authoring spec for Phase 2E1.D of REQ_0006. It is
the first milestone under `v2/backend/app/services/trainer_parity/` and
the closing milestone of the trainer-liveness assembly stack: it
composes the γ observation collector, the γ observation-history
extender, and the δ snapshot composer into a single in-process callable
that turns a `StreamLatestIdReader` plus prior per-stream observation
histories into a fully-populated `LivenessSignalSnapshot` and the
updated histories.

The service is non-live, non-Redis-write, non-network-at-call,
non-legacy-mutating, and non-deploying. The service does not import any
Redis client. The service does not import the γ.real factory. The
service receives a reader through dependency injection. The factory
remains the single trainer-parity module that contains the literal text
`import redis`; constructing the reader is the responsibility of an
external composition root that is out of scope for this milestone and
will be authored under 2E1.E.

## Predecessor gates

- 2E1.A subprocess adapter:
  `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract:
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`).
- 2E1.C.α liveness signal snapshot:
  `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`).
- 2E1.C.β stream-id growth domain:
  `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`).
- 2E1.C.γ observation collector:
  `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`).
- 2E1.C.δ snapshot composition:
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`).
- 2E1.C.γ.real reader:
  `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md`).
- 2E1.C.γ.real.factory:
  `PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/111_2E1C_GAMMA_REAL_FACTORY_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.D. The implementation task encodes the gamma.real.factory Codex
pass as its primary additional marker.

## Scope (additive only — no edits to existing trainer-parity surface)

Files to create (exact set, no extras):

- `v2/backend/app/services/__init__.py` — only if missing; otherwise unchanged.
- `v2/backend/app/services/trainer_parity/__init__.py` — public surface only.
- `v2/backend/app/services/trainer_parity/errors.py` — service-specific exception type.
- `v2/backend/app/services/trainer_parity/evaluation.py` — `TrainerLivenessEvaluation` frozen dataclass.
- `v2/backend/app/services/trainer_parity/liveness_service.py` — `evaluate_trainer_liveness` orchestrator.
- `v2/backend/tests/unit/services/__init__.py` — only if missing; empty package marker.
- `v2/backend/tests/unit/services/trainer_parity/__init__.py` — empty package marker.
- The 32 test files listed in the test plan (113).

Files that MUST NOT be modified:

- `v2/backend/app/adapters/redis_v2/__init__.py`
- `v2/backend/app/adapters/redis_v2/errors.py`
- `v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py`
- `v2/backend/app/adapters/redis_v2/factory.py`
- `v2/backend/app/adapters/redis_v2/url_env.py`
- `v2/backend/app/adapters/redis_v2/client.py`
- `v2/backend/app/adapters/redis_v2/streams.py`
- `v2/backend/app/adapters/redis_v2/retention.py`
- every existing file under `v2/backend/tests/unit/adapters/redis_v2/`
- every file under α, β, γ, δ source and test trees.
- every other file under `v2/backend/app/services/` (the trainer_parity
  subpackage is the only service authored here).

The service milestone does NOT extend `v2/backend/app/adapters/redis_v2`
or any domain package. Importing `v2.backend.app.services.trainer_parity`
MUST remain free of `redis` import side-effects.

## `TrainerLivenessEvaluation` (`evaluation.py`)

A frozen-slots dataclass with exactly three fields, in this order:

```
@dataclass(frozen=True, slots=True)
class TrainerLivenessEvaluation:
    snapshot: LivenessSignalSnapshot
    prediction_history: tuple[StreamIdObservation, ...]
    proposal_history: tuple[StreamIdObservation, ...]
```

`evaluation.py` MUST NOT import `redis`, `aioredis`, `redis.asyncio`,
`hiredis`, or any Redis client. `evaluation.py` MUST NOT import the
γ.real factory or the γ.real `url_env`. `evaluation.py` MUST NOT import
any module under `v2/backend/app/services/` other than its sibling
`errors.py`. `evaluation.py` MUST NOT call any wall-clock helper.

## `evaluate_trainer_liveness` (`liveness_service.py`)

Signature:

```
def evaluate_trainer_liveness(
    reader: StreamLatestIdReader,
    *,
    base_inputs: LivenessSnapshotBaseInputs,
    prediction_history: tuple[StreamIdObservation, ...],
    proposal_history: tuple[StreamIdObservation, ...],
    growth_config: GrowthWindowConfig,
    now_ms_clock: Callable[[], int],
    prediction_stream_name: str,
    proposal_stream_name: str,
    max_history_per_stream: int,
) -> TrainerLivenessEvaluation
```

Behavior contract (executed in this exact order; deviation is a hard fail):

1. If `reader` does not expose a callable `latest_stream_id` attribute,
   raise `TrainerParityServiceError("must_be_stream_latest_id_reader",
   field="reader")`.
2. If `base_inputs` is not an instance of `LivenessSnapshotBaseInputs`,
   raise `TrainerParityServiceError("must_be_liveness_snapshot_base_inputs",
   field="base_inputs")`.
3. If `prediction_history` is not a `tuple`, raise
   `TrainerParityServiceError("must_be_tuple", field="prediction_history")`.
4. If `proposal_history` is not a `tuple`, raise
   `TrainerParityServiceError("must_be_tuple", field="proposal_history")`.
5. If any element of `prediction_history` is not a `StreamIdObservation`,
   raise `TrainerParityServiceError("must_be_stream_id_observation",
   field="prediction_history")`.
6. If any element of `proposal_history` is not a `StreamIdObservation`,
   raise `TrainerParityServiceError("must_be_stream_id_observation",
   field="proposal_history")`.
7. If `growth_config` is not a `GrowthWindowConfig`, raise
   `TrainerParityServiceError("must_be_growth_window_config",
   field="growth_config")`.
8. If `now_ms_clock` is not callable, raise
   `TrainerParityServiceError("must_be_callable", field="now_ms_clock")`.
9. If `prediction_stream_name` is not a non-empty `str`, raise
   `TrainerParityServiceError("must_be_nonempty_str",
   field="prediction_stream_name")`.
10. If `proposal_stream_name` is not a non-empty `str`, raise
    `TrainerParityServiceError("must_be_nonempty_str",
    field="proposal_stream_name")`.
11. If `prediction_stream_name == proposal_stream_name`, raise
    `TrainerParityServiceError("stream_names_must_differ",
    field="proposal_stream_name")`.
12. If `type(max_history_per_stream) is not int`, raise
    `TrainerParityServiceError("must_be_int",
    field="max_history_per_stream")`.
13. If `max_history_per_stream < 1`, raise
    `TrainerParityServiceError("must_be_positive",
    field="max_history_per_stream")`.
14. Read `now_ms = now_ms_clock()`. If `type(now_ms) is not int`, raise
    `TrainerParityServiceError("must_be_int", field="now_ms_clock")`.
    If `now_ms < 0`, raise
    `TrainerParityServiceError("must_be_nonnegative",
    field="now_ms_clock")`. The clock is read EXACTLY ONCE per call.
15. Build `cached_clock = lambda: now_ms`.
16. Call
    `fresh = collect_stream_id_observations(reader,
    stream_names=(prediction_stream_name, proposal_stream_name),
    clock_ms=cached_clock)`.
    Any `ObservationCollectorError` propagates unchanged.
17. Partition `fresh` into:
    - `fresh_prediction = tuple(o for o in fresh if o.stream_name == prediction_stream_name)`
    - `fresh_proposal = tuple(o for o in fresh if o.stream_name == proposal_stream_name)`
18. Compute
    `new_prediction_history = extend_observation_history(prediction_history,
    fresh_prediction, max_total=max_history_per_stream)`.
    Any `ObservationCollectorError` propagates unchanged.
19. Compute
    `new_proposal_history = extend_observation_history(proposal_history,
    fresh_proposal, max_total=max_history_per_stream)`.
20. Call
    `snapshot = compose_liveness_snapshot_with_growth(
    base_inputs,
    prediction_observations=new_prediction_history,
    proposal_observations=new_proposal_history,
    growth_config=growth_config,
    now_ms=now_ms,
    prediction_stream_name=prediction_stream_name,
    proposal_stream_name=proposal_stream_name)`.
    Any `TrainerLivenessCompositionError` propagates unchanged.
21. Return
    `TrainerLivenessEvaluation(snapshot=snapshot,
    prediction_history=new_prediction_history,
    proposal_history=new_proposal_history)`.

`liveness_service.py` MUST NOT import `redis`, `aioredis`,
`redis.asyncio`, or `hiredis`. `liveness_service.py` MUST NOT import
`v2.backend.app.adapters.redis_v2.factory` or
`v2.backend.app.adapters.redis_v2.url_env`. `liveness_service.py` MAY
import `StreamLatestIdReader` from
`v2.backend.app.domain.trainer_liveness_observation_collector` only
(the protocol type — no Redis dependency). `liveness_service.py` MUST
NOT call `time.time(`, `datetime.now(`, `datetime.utcnow(`, any
`time.monotonic`, or any module-level wall-clock helper. The supplied
`now_ms_clock` is the sole time source.

`liveness_service.py` MUST NOT log, print, or emit any input value.
`liveness_service.py` MUST NOT mutate any supplied tuple or dataclass.
`liveness_service.py` MUST NOT install module-level singletons.
`liveness_service.py` MUST NOT register a FastAPI startup hook,
lifespan handler, background task, or thread. `liveness_service.py`
MUST NOT open a socket, run a subprocess, or read environment
variables.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `evaluate_trainer_liveness`
2. `TrainerLivenessEvaluation`
3. `TrainerParityServiceError`

The `__init__.py` MUST NOT re-export anything else from this milestone
or from any other milestone. Importing
`v2.backend.app.services.trainer_parity` MUST NOT pull `redis` into
`sys.modules`.

## Cross-isolation

The service milestone MUST NOT modify any file under
`v2/backend/app/domain/`, `v2/backend/app/adapters/`,
`v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`,
`v2/backend/app/main.py`, `v2/frontend/`, or any other service module
outside `v2/backend/app/services/trainer_parity/`. The milestone MUST
NOT modify any existing test file.

## Forbidden tokens (canonical list — see safety boundaries 114)

The following literal strings MUST NOT appear anywhere in
`v2/backend/app/services/trainer_parity/` source or test files:

- `import redis`
- `from redis`
- `redis.asyncio`
- `redis.Redis(`
- `redis.Redis.from_url(`
- `aioredis`
- `hiredis`
- `time.time(`
- `time.monotonic(`
- `datetime.now(`
- `datetime.utcnow(`
- `os.environ`
- `subprocess.`
- `socket.`
- `requests.`
- `httpx.`
- `aiohttp.`
- `urllib.request`
- `urllib.parse`
- `print(`
- `logger.`
- `logging.`
- `xadd`
- `xdel`
- `xtrim`
- `xgroup_`
- `xack`
- `delete`
- `unlink`
- `flushdb`
- `flushall`
- `script_load`
- `evalsha`
- `eval(`
- `pubsub`
- `publish(`
- `connection_pool`
- `from v2.backend.app.adapters.redis_v2.factory`
- `from v2.backend.app.adapters.redis_v2.url_env`
- `v2.backend.app.adapters.redis_v2.factory`
- `v2.backend.app.adapters.redis_v2.url_env`

The forbidden-token guard test (`test_service_milestone_forbidden_tokens.py`)
constructs every literal at runtime via string concatenation and scans
only the four service source files plus the 32 new test files. It does
NOT scan any prior-milestone file. It does NOT apply any per-file
exemption — the service milestone has zero exemptions.

## Marker

On successful implementation and local validation, 091 emits
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`
to `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/117_2E1D_SERVICE_COMPOSITION_GO_NO_GO.md`.

On Codex PASS, 092 emits
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`
to `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/119_2E1D_SERVICE_COMPOSITION_CODEX_GO_NO_GO.md`.
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/112_PHASE_2E1D_SERVICE_COMPOSITION_SPEC.md
