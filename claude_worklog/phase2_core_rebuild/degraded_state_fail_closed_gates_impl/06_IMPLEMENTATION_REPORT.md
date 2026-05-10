```
# Phase 2Z — Implementation Report

## Authored modules

### Domain (`v2/backend/app/domain/degraded_state_fail_closed_gates/`)

- `__init__.py` — public surface re-exports the four
  `DEGRADED_SOURCE_*` constants, `DegradedStateRecord`, and
  `DegradedStateFailClosedGatesDomainError`.
- `errors.py` — `DegradedStateFailClosedGatesDomainError(ValueError)`
  with `reason` / `field` attributes mirroring
  `ProvenanceDedupeAttributionDomainError`.
- `degraded_source_state.py` — module-level constants
  `DEGRADED_SOURCE_OK`, `DEGRADED_SOURCE_STALE`,
  `DEGRADED_SOURCE_MISSING`, `DEGRADED_SOURCE_UNUSED`, plus the frozen
  sets `_ALLOWED_DEGRADED_SOURCE_STATES` and
  `_FAIL_CLOSED_TRIGGER_STATES`.
- `degraded_state_record.py` — `@dataclass(frozen=True, slots=True)
  DegradedStateRecord` with `__post_init__` validation per the spec
  (per-source states, ages, `fail_closed` derivation invariant,
  lineage IDs, Phase 2V trainer-parity fields, `live_blocked is True`).

### Services (`v2/backend/app/services/degraded_state_fail_closed_gates/`)

- `__init__.py` — re-exports `DegradedStateFailClosedGatesServiceError`
  and `assemble_degraded_state_record`.
- `errors.py` — `DegradedStateFailClosedGatesServiceError(ValueError)`
  mirroring `ProvenanceServiceError`.
- `service.py` — pure function
  `assemble_degraded_state_record(*, ...)` validating
  `upstream_record` is `RiskDecisionRecord`, deriving
  `degraded_state_id` deterministically, deriving `fail_closed` from
  per-source states, propagating Phase 2V trainer-parity fields, and
  setting `live_blocked=True`. Domain construction failures re-raise as
  `DegradedStateFailClosedGatesServiceError("invalid_degraded_state_record",
  field="upstream_record")`.

### Composition (`v2/backend/app/composition/degraded_state_fail_closed_gates/`)

- `__init__.py` — re-exports `DegradedStateFailClosedGatesRuntime`,
  `build_degraded_state_fail_closed_gates_runtime`, and
  `DegradedStateFailClosedGatesRuntimeCompositionError`.
- `errors.py` —
  `DegradedStateFailClosedGatesRuntimeCompositionError(ValueError)`
  mirroring `ProvenanceDedupeAttributionRuntimeCompositionError`.
- `runtime.py` —
  `class DegradedStateFailClosedGatesRuntime` with
  `__slots__ = ("degraded_state_now",)`, plus
  `build_degraded_state_fail_closed_gates_runtime(*, now_ms_clock)`
  factory that validates the clock, never invokes it at build time,
  and returns a runtime whose closure invokes the clock zero times per
  call.

## Test counts

| Layer | Test files | Test functions |
| --- | --- | --- |
| domain | 9 (plus `__init__.py`) | 19 |
| services | 9 (plus `__init__.py`) | 14 |
| composition | 8 (plus `__init__.py`) | 8 |

Total: 41 test functions across 26 test files plus 3 empty test
package `__init__.py` files.

## Validation outputs (to be filled by harness on materialization)

- `pytest` summary line:
  `<filled by harness>`
- Smoke import stdout:
  `<filled by harness — expected: ok>`
- `grep -nR "redis\|aioredis\|redis.asyncio" v2/backend/app/{domain,services,composition}/degraded_state_fail_closed_gates/`:
  `<filled by harness — expected: empty>`
- `grep -nR "fastapi\|starlette" v2/backend/app/{domain,services,composition}/degraded_state_fail_closed_gates/`:
  `<filled by harness — expected: empty>`
- No-prior-milestone-mutation diff:
  `<filled by harness — expected: empty>`

## Partial gaps

None. The milestone authors only the typed-contract surface plus
non-live unit tests. The downstream risk-gateway extension that
consumes per-source state and emits typed
`deny_smc_stale` / `deny_liq_missing` / `deny_oi_stale` /
`deny_orderbook_missing` reason codes is a future Phase 2Z-follow-up
milestone outside this turn's scope.

PHASE_2Z_IMPLEMENTATION_REPORT_READY
```
