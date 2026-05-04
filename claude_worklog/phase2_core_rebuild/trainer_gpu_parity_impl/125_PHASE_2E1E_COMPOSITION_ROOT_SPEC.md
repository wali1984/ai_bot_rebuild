# Phase 2E1.E — Trainer Parity Composition Root Spec

This document is the authoring spec for Phase 2E1.E of REQ_0006. It is
the closing wiring milestone of the trainer-liveness assembly stack: it
joins the γ.real Redis factory (`make_real_redis_stream_latest_id_reader`)
to the redis-clean trainer-parity service callable
(`evaluate_trainer_liveness`) inside a single composition function that
returns a static-config-bound evaluator closure.

The composition root is the FIRST trainer-parity milestone that is
allowed to import the γ.real factory and therefore the first trainer-
parity milestone whose import surface transitively pulls `redis` into
`sys.modules`. To preserve the redis-clean invariant of the 2E1.D
service (`v2.backend.app.services.trainer_parity` MUST remain free of
`redis` import side-effects), the composition root MUST NOT live under
`v2/backend/app/services/trainer_parity/`. It lives under a new
top-level package `v2/backend/app/composition/trainer_parity/`.

The composition root is non-live, non-Redis-write, non-network-at-call,
non-legacy-mutating, and non-deploying. The composition root MAY import
the γ.real factory function at module load time. The composition root
MUST NOT call any Redis command at import time, at build-time
construction, or inside the returned evaluator closure (the only Redis
command path is `RedisStreamLatestIdReader.latest_stream_id` invoked
via the service's `collect_stream_id_observations` callable, which is
already a 2E1.C.γ.real-gated path).

## Predecessor gates

- 2E1.A subprocess adapter: `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract: `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`).
- 2E1.C.α liveness signal snapshot: `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`).
- 2E1.C.β stream-id growth domain: `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`).
- 2E1.C.γ observation collector: `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`).
- 2E1.C.δ snapshot composition: `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`).
- 2E1.C.γ.real reader: `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md`).
- 2E1.C.γ.real.factory: `PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/111_2E1C_GAMMA_REAL_FACTORY_CODEX_GO_NO_GO.md`).
- 2E1.D trainer parity service composition (post-autofix Codex re-review):
  `PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS`
  (`trainer_gpu_parity_impl/124_2E1D_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.E. The implementation task encodes the 2E1.D Codex pass as its
primary additional marker.

## Module location decision

Composition root files land under a NEW top-level package:

- `v2/backend/app/composition/__init__.py` — empty package marker (only
  if missing).
- `v2/backend/app/composition/trainer_parity/__init__.py` — public
  surface only.
- `v2/backend/app/composition/trainer_parity/errors.py` — composition
  root exception type.
- `v2/backend/app/composition/trainer_parity/runtime.py` —
  `build_trainer_liveness_evaluator` factory function and
  `TrainerLivenessEvaluator` callable type alias.

This location is deliberate. Placing the composition root under the
existing 2E1.D service directory (`v2/backend/app/services/trainer_parity/`)
would force the 2E1.D forbidden-token guard (`test_service_milestone_forbidden_tokens.py`)
to grow per-file exemptions and would break the 2E1.D import-isolation
test (`test_service_does_not_import_factory_or_url_env.py`), both of
which are explicit cross-isolation invariants of the just-passed
milestone. A separate top-level `composition/` package keeps the
service's redis-clean invariant intact while still giving us a single
authoritative wiring file.

## Scope (additive only — no edits to existing trainer-parity surface)

Files to create (exact set, no extras):

- `v2/backend/app/composition/__init__.py` — only if missing; empty
  package marker.
- `v2/backend/app/composition/trainer_parity/__init__.py` — public
  surface only.
- `v2/backend/app/composition/trainer_parity/errors.py` —
  `TrainerParityCompositionError` exception type.
- `v2/backend/app/composition/trainer_parity/runtime.py` —
  `build_trainer_liveness_evaluator` and `TrainerLivenessEvaluator`.
- `v2/backend/tests/unit/composition/__init__.py` — only if missing;
  empty package marker.
- `v2/backend/tests/unit/composition/trainer_parity/__init__.py` —
  empty package marker.
- The 25 test files listed in the test plan (126).

Files that MUST NOT be modified:

- every file under `v2/backend/app/adapters/redis_v2/`.
- every file under `v2/backend/app/services/trainer_parity/`.
- every file under `v2/backend/app/domain/`.
- every file under `v2/backend/app/api/`, `v2/backend/app/cli/`,
  `v2/backend/app/jobs/`.
- `v2/backend/app/main.py`.
- every file under `v2/frontend/`.
- every existing test file under `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/domain/`, `v2/backend/tests/unit/services/`,
  `v2/backend/tests/unit/feature_snapshots/`, and
  `v2/backend/tests/unit/symbol_universe/`.

The composition milestone does NOT modify the 2E1.D service or any
prior trainer-liveness milestone. The composition milestone does NOT
extend any domain package. Importing
`v2.backend.app.composition.trainer_parity` IS expected to load
`redis` into `sys.modules` because the runtime module imports the
γ.real factory at module load time; this is the authoritative wiring
and is the inverse of the 2E1.D service's redis-clean invariant.

## `TrainerParityCompositionError` (`errors.py`)

A standalone exception type defined exactly as:

```
class TrainerParityCompositionError(Exception):
    def __init__(self, code: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.field is not None:
            return f"{self.code} ({self.field})"
        return self.code
```

`errors.py` MUST NOT subclass any prior-milestone error type.
`errors.py` MUST import only the standard library. `errors.py` MUST
NOT import `redis`, `aioredis`, `redis.asyncio`, `hiredis`, the γ.real
factory, the γ.real `url_env`, or any `v2/` module.

## `TrainerLivenessEvaluator` (`runtime.py`)

A `Callable` type alias:

```
TrainerLivenessEvaluator = Callable[
    [tuple[StreamIdObservation, ...], tuple[StreamIdObservation, ...]],
    TrainerLivenessEvaluation,
]
```

The alias is defined at module scope. The alias is exported via the
package `__init__.py`. The alias is NOT a runtime class; tests that
need to assert "callable" use `callable(evaluator)`.

## `build_trainer_liveness_evaluator` (`runtime.py`)

Signature (keyword-only after the leading positional-or-keyword
boundary; the leading `*` enforces keyword-only):

```
def build_trainer_liveness_evaluator(
    *,
    base_inputs: LivenessSnapshotBaseInputs,
    growth_config: GrowthWindowConfig,
    now_ms_clock: Callable[[], int],
    prediction_stream_name: str,
    proposal_stream_name: str,
    max_history_per_stream: int,
    env: object | None = None,
    url: str | None = None,
) -> TrainerLivenessEvaluator
```

Behavior contract (executed in this exact order; deviation is a hard
fail):

1. If `base_inputs` is not an instance of `LivenessSnapshotBaseInputs`,
   raise `TrainerParityCompositionError("must_be_liveness_snapshot_base_inputs",
   field="base_inputs")`.
2. If `growth_config` is not a `GrowthWindowConfig`, raise
   `TrainerParityCompositionError("must_be_growth_window_config",
   field="growth_config")`.
3. If `now_ms_clock` is not callable, raise
   `TrainerParityCompositionError("must_be_callable",
   field="now_ms_clock")`.
4. If `prediction_stream_name` is not a non-empty `str`, raise
   `TrainerParityCompositionError("must_be_nonempty_str",
   field="prediction_stream_name")`.
5. If `proposal_stream_name` is not a non-empty `str`, raise
   `TrainerParityCompositionError("must_be_nonempty_str",
   field="proposal_stream_name")`.
6. If `prediction_stream_name == proposal_stream_name`, raise
   `TrainerParityCompositionError("stream_names_must_differ",
   field="proposal_stream_name")`.
7. If `type(max_history_per_stream) is not int`, raise
   `TrainerParityCompositionError("must_be_int",
   field="max_history_per_stream")`.
8. If `max_history_per_stream < 1`, raise
   `TrainerParityCompositionError("must_be_positive",
   field="max_history_per_stream")`.
9. Call
   `reader = make_real_redis_stream_latest_id_reader(url=url, env=env)`
   exactly once. Any `RedisStreamReaderError` propagates unchanged.
   The reader is bound into the closure returned by step 11 and is
   NOT re-built when the closure is called.
10. Capture the static config locally:
    `_base_inputs = base_inputs`,
    `_growth_config = growth_config`,
    `_now_ms_clock = now_ms_clock`,
    `_prediction_stream_name = prediction_stream_name`,
    `_proposal_stream_name = proposal_stream_name`,
    `_max_history_per_stream = max_history_per_stream`,
    `_reader = reader`.
11. Define and return a closure
    `def _evaluator(prediction_history, proposal_history)` that:
    - forwards `_reader` as the leading positional argument to
      `evaluate_trainer_liveness`;
    - forwards `_base_inputs`, `_growth_config`, `_now_ms_clock`,
      `_prediction_stream_name`, `_proposal_stream_name`,
      `_max_history_per_stream` as the corresponding keyword arguments;
    - forwards the supplied `prediction_history` and `proposal_history`
      tuples unchanged as the corresponding keyword arguments;
    - returns the resulting `TrainerLivenessEvaluation` unchanged.
    Any `TrainerParityServiceError` from the service propagates
    unchanged. Any `ObservationCollectorError`,
    `TrainerLivenessCompositionError`, or other domain error from
    deeper layers also propagates unchanged.

`runtime.py` MAY import the γ.real factory function exactly once (as
`from v2.backend.app.adapters.redis_v2.factory import
make_real_redis_stream_latest_id_reader`). `runtime.py` MUST NOT import
`v2.backend.app.adapters.redis_v2.url_env`, `redis` directly,
`aioredis`, `hiredis`, or `redis.asyncio` directly. `runtime.py` MUST
NOT call `time.time(`, `datetime.now(`, `datetime.utcnow(`, any
`time.monotonic` helper, or any module-level wall-clock helper. The
supplied `now_ms_clock` is the sole time source. `runtime.py` MUST
NOT log, print, or emit any input value (no `print(`, no `logger.`,
no `logging.`). `runtime.py` MUST NOT mutate any supplied tuple or
dataclass. `runtime.py` MUST NOT install module-level singletons,
caches, or locks. `runtime.py` MUST NOT register a FastAPI startup
hook, lifespan handler, dependency, router, background task, or
thread. `runtime.py` MUST NOT open a socket directly, run a
subprocess, or read environment variables (`os.environ`). The factory
itself reads `V2_REDIS_URL` via `read_v2_redis_url(env=...)`; the
composition root delegates that read entirely to the factory and does
NOT re-implement it.

`runtime.py` MUST NOT import any other module under
`v2/backend/app/services/`, `v2/backend/app/api/`,
`v2/backend/app/cli/`, `v2/backend/app/jobs/`, or
`v2/backend/app/main`. `runtime.py` MAY import
`v2.backend.app.services.trainer_parity` symbols
(`evaluate_trainer_liveness`, `TrainerLivenessEvaluation`).
`runtime.py` MAY import the protocol type
`StreamLatestIdReader` from
`v2.backend.app.domain.trainer_liveness_observation_collector` and the
domain types `StreamIdObservation`, `GrowthWindowConfig` from
`v2.backend.app.domain.liveness_stream_growth` and
`LivenessSnapshotBaseInputs` from
`v2.backend.app.domain.trainer_liveness_composition`.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `build_trainer_liveness_evaluator`
2. `TrainerLivenessEvaluator`
3. `TrainerParityCompositionError`

The `__init__.py` MUST NOT re-export anything else from this milestone
or from any other milestone. The `__init__.py` MUST set `__all__` to
the exact ordered tuple of those three names. Importing
`v2.backend.app.composition.trainer_parity` is EXPECTED to load
`redis` into `sys.modules` via the factory import in `runtime.py`;
this is the authoritative composition wiring and is asserted by
`test_runtime_module_loads_redis_when_imported.py`.

## Cross-isolation

The composition milestone MUST NOT modify any file under
`v2/backend/app/services/`, `v2/backend/app/adapters/`,
`v2/backend/app/domain/`, `v2/backend/app/api/`,
`v2/backend/app/cli/`, `v2/backend/app/jobs/`,
`v2/backend/app/main.py`, or `v2/frontend/`. The milestone MUST NOT
modify any existing test file under
`v2/backend/tests/unit/services/`,
`v2/backend/tests/unit/adapters/`,
`v2/backend/tests/unit/domain/`,
`v2/backend/tests/unit/feature_snapshots/`, or
`v2/backend/tests/unit/symbol_universe/`.

The implementation task's `git status -s` zero-line gate (validation
command 5 in 126) covers every cross-isolation path above.

## Forbidden tokens (canonical list — see safety boundaries 127)

The following literal strings MUST NOT appear anywhere in
`v2/backend/app/composition/trainer_parity/` source files OR test
files, with one explicit exemption: `runtime.py` MAY contain
`from v2.backend.app.adapters.redis_v2.factory` exactly once, on the
single import line that pulls `make_real_redis_stream_latest_id_reader`
into the runtime module.

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
- `from v2.backend.app.adapters.redis_v2.url_env`
- `v2.backend.app.adapters.redis_v2.url_env`
- `v2.backend.app.adapters.redis_v2.client`
- `v2.backend.app.adapters.redis_v2.streams`
- `v2.backend.app.adapters.redis_v2.retention`
- `v2.backend.app.adapters.redis_v2.stream_latest_id_reader`

The forbidden-token guard test
(`test_composition_milestone_forbidden_tokens.py`) constructs every
literal at runtime via string concatenation and scans only the three
authored source files (`__init__.py`, `errors.py`, `runtime.py`) plus
the 25 new test files. The guard applies the SINGLE explicit exemption
described above (the factory import in `runtime.py`) by counting
occurrences of `from v2.backend.app.adapters.redis_v2.factory` in
`runtime.py` and asserting the count is exactly 1, then scanning the
remaining files with no exemption.

## Marker

On successful implementation and local validation, 096 emits
`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`
to `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/130_2E1E_COMPOSITION_ROOT_GO_NO_GO.md`.

On Codex PASS, 097 emits
`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`
to `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/132_2E1E_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_SPEC_READY
