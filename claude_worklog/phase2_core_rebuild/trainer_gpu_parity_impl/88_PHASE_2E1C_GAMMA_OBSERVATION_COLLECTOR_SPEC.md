# Phase 2E1.C.γ — Trainer Liveness Stream-ID Observation Collector Domain Spec

This document is the authoring spec for Phase 2E1.C.γ of REQ_0006.

It is the fourth and final pure-domain sub-phase of the trainer
prediction-worker liveness detector, and the seam between the
(future, separately-spec'd) read-only Redis client adapter and the
existing β stream-id growth window calculator. γ is non-live,
non-Redis, non-subprocess, non-network, non-legacy-mutating, and
non-deploying. The domain layer authored here defines a structural
Reader port, a deterministic in-memory fake of that port, a pure
collection function that turns a Reader plus an injected clock into
a tuple of β `StreamIdObservation` values, and a pure rolling-history
helper that bounds the in-process observation buffer used by δ.

The γ layer exists because β requires `tuple[StreamIdObservation, ...]`
and δ requires both prediction- and proposal-stream observation
tuples, but no in-process caller can produce them today without
re-implementing or coupling to a Redis client. By authoring γ as a
pure adapter-shaped domain layer with a `runtime_checkable` Protocol
Reader port and an in-memory fake, the future real Redis-backed
reader becomes a single drop-in implementation under
`v2/backend/app/adapters/redis_v2/` without modifying γ, δ, β, or α.

## Predecessor gates

- 2E1.A subprocess adapter:
  `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract:
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`).
- 2E1.C.α liveness domain layer:
  `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`).
- 2E1.C.β stream-id growth domain layer:
  `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`).
- 2E1.C.δ snapshot composition layer:
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.C.γ. The γ implementation task encodes the δ Codex pass as its
primary additional marker.

## Position in 2E1.C breakdown

- 2E1.C.α — α liveness signal snapshot dataclass plus evaluator. Done.
- 2E1.C.β — β stream-id growth window calculator. Done.
- 2E1.C.δ — δ snapshot composition (α plus β) layer. Done.
- 2E1.C.γ — γ stream-id observation collector adapter-shaped pure
  domain layer (this spec).
- 2E1.C.γ.real — future, separately-spec'd, real-Redis-backed
  `StreamLatestIdReader` implementation living under
  `v2/backend/app/adapters/redis_v2/`. γ.real implements the γ
  Reader Protocol; γ.real does NOT modify γ, δ, β, or α. γ.real is
  out of scope for this spec turn.

The deliberate α/β/δ/γ ordering keeps the in-process safety boundary
intact for as long as possible: every milestone before γ.real is
zero-Redis, zero-network, zero-clock, zero-subprocess.

## Surface to create

Package: `v2/backend/app/domain/trainer_liveness_observation_collector/`

Files (exact set, no extras):

- `__init__.py` — public surface only.
- `errors.py` — domain-specific exception type.
- `reader_protocol.py` — `StreamLatestIdReader` Protocol port.
- `in_memory_reader.py` — `InMemoryStreamLatestIdReader` deterministic
  test fake of the Reader port.
- `observation_collector.py` — pure function
  `collect_stream_id_observations`.
- `observation_history.py` — pure function
  `extend_observation_history`.

Tests live in
`v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`.

The γ package is a sibling of the α package
`v2/backend/app/domain/trainer_liveness/`, the β package
`v2/backend/app/domain/liveness_stream_growth/`, and the δ package
`v2/backend/app/domain/trainer_liveness_composition/`.

γ MAY import the public symbols `StreamIdObservation` and
`LivenessStreamGrowthDomainError` from β
(`v2.backend.app.domain.liveness_stream_growth`).

γ MUST NOT import from α. γ MUST NOT import from δ. γ MUST NOT modify
α, β, or δ. γ MUST NOT import any module under
`v2/backend/app/adapters/`, `v2/backend/app/services/`,
`v2/backend/app/api/`, `v2/backend/app/cli/`,
`v2/backend/app/jobs/`, or `v2/backend/app/main.py`.

γ MUST NOT import any Redis client (the canonical forbidden tokens
appear in spec 89), subprocess module, network module,
numerical/ML module, legacy module, or wall-clock helper. The clock
is injected into γ exclusively as a `Callable[[], int]`.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `StreamLatestIdReader`
2. `InMemoryStreamLatestIdReader`
3. `collect_stream_id_observations`
4. `extend_observation_history`
5. `ObservationCollectorError`

No other names are re-exported. No re-export of submodules. No
re-export of internal `_`-prefixed helpers. No re-export of α, β,
or δ public symbols. The `__init__.py` MUST declare an explicit
`__all__` tuple containing exactly these five names in this exact
order.

## ObservationCollectorError (`errors.py`)

A `class ObservationCollectorError(Exception)` whose
`__init__(self, code: str, *, field: str | None = None) -> None`
stores `code` and `field` on `self`. `__str__` returns
`f"{code} ({field})"` when `field` is non-None, else just `code`.
No inheritance from α, β, or δ error types.

## StreamLatestIdReader (`reader_protocol.py`)

The module exposes a `runtime_checkable` Protocol with one method:

- `latest_stream_id(self, stream_name: str) -> str | None`

Contract:

- The implementation returns the most recent Redis-style stream ID
  string of the form `<ms>-<seq>` for the given stream name, or
  `None` when the stream does not exist or has zero entries.
- The implementation MUST be read-only and side-effect-free from the
  caller's perspective.
- The Protocol permits the implementation to raise on transport or
  configuration errors; γ does NOT catch such errors and does NOT
  translate them. γ.real (future sub-phase) will define its own
  error policy.
- The Protocol is `runtime_checkable` so γ tests can assert
  structural conformance via `isinstance`.

The `reader_protocol.py` module MUST NOT import any Redis client.
It imports only `typing.Protocol` and `typing.runtime_checkable`
(plus `from __future__ import annotations`).

## InMemoryStreamLatestIdReader (`in_memory_reader.py`)

`class InMemoryStreamLatestIdReader`:

- `__init__(self, latest_ids: dict[str, str | None]) -> None`
  - If `latest_ids` is not a `dict`, raise
    `ObservationCollectorError("must_be_dict", field="latest_ids")`.
  - For each item, if the key is not a `str`, raise
    `ObservationCollectorError("must_be_str", field="latest_ids")`.
  - For each item, if the value is neither a `str` nor `None`, raise
    `ObservationCollectorError("must_be_str_or_none", field="latest_ids")`.
  - Store a defensive copy: `self._latest_ids = dict(latest_ids)`.
- `latest_stream_id(self, stream_name: str) -> str | None`
  - If `stream_name` is not a `str` or is empty, raise
    `ObservationCollectorError("must_be_nonempty_str", field="stream_name")`.
  - Return `self._latest_ids.get(stream_name, None)`.

It MUST satisfy `isinstance(reader, StreamLatestIdReader)` because
the Protocol is `runtime_checkable`.

`InMemoryStreamLatestIdReader` MUST NOT mutate the caller-supplied
`latest_ids` dict. The defensive `dict(...)` copy is the only
storage path.

## collect_stream_id_observations (`observation_collector.py`)

Signature (one positional arg, all others keyword-only):

- positional: `reader: StreamLatestIdReader`
- keyword-only: `stream_names: tuple[str, ...]`
- keyword-only: `clock_ms: Callable[[], int]`
- returns: `tuple[StreamIdObservation, ...]`

Behavior contract (executed in this exact order):

1. If `reader` does not have a callable attribute `latest_stream_id`,
   raise
   `ObservationCollectorError("must_be_stream_latest_id_reader", field="reader")`.
2. If `stream_names` is not a `tuple`, raise
   `ObservationCollectorError("must_be_tuple", field="stream_names")`.
3. For each entry in `stream_names`, if it is not a `str` or is
   empty, raise
   `ObservationCollectorError("must_be_nonempty_str", field="stream_names")`.
   γ does NOT enforce β's stricter character set here; β's
   `StreamIdObservation.__post_init__` rejects names with whitespace,
   path separators, or disallowed characters at observation
   construction time, and γ propagates that β error unchanged.
4. If `clock_ms` is not callable, raise
   `ObservationCollectorError("must_be_callable", field="clock_ms")`.
5. Capture exactly one clock value: `now_ms = clock_ms()`. The
   collector MUST NOT call `clock_ms` more than once per invocation.
6. If `type(now_ms) is not int`, raise
   `ObservationCollectorError("must_be_int", field="now_ms")`.
7. If `now_ms < 0`, raise
   `ObservationCollectorError("must_be_nonnegative", field="now_ms")`.
8. Iterate `stream_names` in input order. For each `stream_name`:
   a. Call `latest_id = reader.latest_stream_id(stream_name)`.
   b. If `latest_id is None`, skip this stream and continue.
   c. Otherwise, construct
      `StreamIdObservation(stream_name=stream_name, stream_id=latest_id, observation_ts_ms=now_ms)`
      from β. If β's `__post_init__` raises any
      `LivenessStreamGrowthDomainError`, propagate the error
      unchanged. γ does NOT catch or translate β errors.
   d. Append the observation to a local list.
9. Return `tuple(local_list)` preserving input order across the
   surviving entries.

Determinism: every observation produced by a single invocation of
`collect_stream_id_observations` shares the same
`observation_ts_ms`.

Idempotency: γ MUST NOT mutate `reader`, `stream_names`, the
β-owned `StreamIdObservation` instances, or any other input.

No I/O: γ MUST NOT import or call any wall-clock helper or any
module under `v2/backend/app/adapters/`. The clock is provided
exclusively through `clock_ms`.

## extend_observation_history (`observation_history.py`)

Signature:

- positional: `history: tuple[StreamIdObservation, ...]`
- positional: `new: tuple[StreamIdObservation, ...]`
- keyword-only: `max_total: int`
- returns: `tuple[StreamIdObservation, ...]`

Behavior contract (executed in this exact order):

1. If `history` is not a `tuple`, raise
   `ObservationCollectorError("must_be_tuple", field="history")`.
2. If `new` is not a `tuple`, raise
   `ObservationCollectorError("must_be_tuple", field="new")`.
3. For each entry of `history`, if it is not an instance of β's
   `StreamIdObservation`, raise
   `ObservationCollectorError("must_be_stream_id_observation", field="history")`.
4. For each entry of `new`, if it is not an instance of β's
   `StreamIdObservation`, raise
   `ObservationCollectorError("must_be_stream_id_observation", field="new")`.
5. If `type(max_total) is not int`, raise
   `ObservationCollectorError("must_be_int", field="max_total")`.
6. If `max_total < 1`, raise
   `ObservationCollectorError("must_be_positive", field="max_total")`.
7. Build `combined = history + new`.
8. If `len(combined) <= max_total`, return `combined` unchanged.
9. Otherwise return `combined[-max_total:]` (drop the oldest entries
   from the front).

Idempotency: the function MUST NOT mutate `history` or `new`.

`extend_observation_history` is a pure data-shape helper. It does
NOT validate `observation_ts_ms` ordering across `history` and
`new`; that responsibility belongs to the caller (β's growth
calculator already tolerates unordered observations within its
window).

## Cross-isolation

γ MUST NOT modify any file under
`v2/backend/app/domain/trainer_liveness/` (α),
`v2/backend/app/domain/liveness_stream_growth/` (β),
`v2/backend/app/domain/trainer_liveness_composition/` (δ),
`v2/backend/app/adapters/`, `v2/backend/app/services/`,
`v2/backend/app/api/`, `v2/backend/app/cli/`,
`v2/backend/app/main.py`, or `v2/frontend/`.

γ MUST NOT modify any file under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
other than the implementer-authored
`92_2E1C_GAMMA_GO_NO_GO.md` and
`93_2E1C_GAMMA_IMPLEMENTATION_REPORT.md`.

After γ is added, the existing α, β, and δ pytest suites MUST remain
green. Cross-isolation regression command:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ \
  -q
```

`git status -s` over the α, β, and δ source trees MUST return zero
modified lines.

## Live-trading status

FINAL LIVE GATE: BLOCKED. No γ artifact may change this.

PHASE2E1C_GAMMA_OBSERVATION_COLLECTOR_SPEC_READY
