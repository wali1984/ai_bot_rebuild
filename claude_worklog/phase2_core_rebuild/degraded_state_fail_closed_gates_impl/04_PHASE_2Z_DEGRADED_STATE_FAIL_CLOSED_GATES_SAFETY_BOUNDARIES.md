```
# Phase 2Z — Safety Boundaries

## Hard non-live boundaries

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not read or write any Redis key.
- Do not invoke any Redis command.
- Do not import `redis`, `aioredis`, or `redis.asyncio` in any new
  module.
- Do not import `fastapi` or `starlette` in any new module.
- Do not register any FastAPI lifespan in any `__init__.py`.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run a production migration.
- Do not expose or commit credentials.
- Do not approve the live gate.
- Do not invoke any Binance HTTP API or any other live exchange API.
- Do not perform any network call, any environment-variable read, or
  any heavyweight ML import in any new module.

## Forbidden output paths

- `/home/wali/Desktop/AI BOT`
- `v2/backend/app/proof/`, `cli/`, `adapters/`, `api/`, `jobs/`,
  `main.py`
- `v2/frontend/`
- `claude_worklog/tools/`,
  `claude_worklog/autonomous_control_plane/`,
  `claude_worklog/agent_supervisor/`,
  `claude_worklog/security/`,
  `claude_worklog/requirements_inbox/`,
  `claude_worklog/historical_pnl_audit/`,
  `claude_worklog/legacy_readonly_audit/`,
  `claude_worklog/legacy_runtime_audit/`,
  `claude_worklog/final_readiness/`
- Any prior-milestone subdirectory under `v2/backend/app/domain/`,
  `v2/backend/app/services/`, `v2/backend/app/composition/`,
  `v2/backend/tests/`, or
  `claude_worklog/phase2_core_rebuild/` outside
  `degraded_state_fail_closed_gates_impl/`. Including the now-prior
  `external_manual_position_quarantine` and
  `provenance_dedupe_attribution` directories.

## Explicit no-execution-side-surface

Phase 2Z authors no paper trader process, paper executor, shadow trader
process, shadow executor, live trader process, replay engine,
scheduler, background loop, FastAPI surface, Redis adapter, GPU runner,
model-loading subsystem, or strategy library.

## Explicit no-new-lineage-ID

`degraded_state_id` is a deterministic derivation of the existing
`decision_id` via `f"degraded_state:{decision_id}"[:128]` and is not a
new lineage ID.

## Live gate

The live gate remains blocked and human-only. Phase 2Z does not flip
the final live-readiness gate or substitute for
`FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.

## No prior-milestone byte mutation

No byte under `v2/backend/app/domain/external_manual_position_quarantine/`,
`v2/backend/app/services/external_manual_position_quarantine/`,
`v2/backend/app/composition/external_manual_position_quarantine/`,
`v2/backend/app/domain/provenance_dedupe_attribution/`,
`v2/backend/app/services/provenance_dedupe_attribution/`,
`v2/backend/app/composition/provenance_dedupe_attribution/`,
`claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/`,
or
`claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`
is modified.

## No Redis import; no FastAPI lifespan registration

Verified by:

- domain / services / composition `test_*_module_does_not_load_redis*`
  tests
- domain / services / composition
  `test_*_does_not_register_fastapi_lifespan` tests
- post-implementation `grep` for `redis`, `aioredis`, `redis.asyncio`,
  `fastapi`, `starlette`.

## Markdown / GO-NO-GO discipline

- No markdown fence wrapper around any required output.
- `07_GO_NO_GO.md` contains exactly one non-empty line.
- No standalone marker line equal to the BEGIN/END output sentinel
  inside any authored file body.

PHASE_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_SAFETY_BOUNDARIES_READY
```
