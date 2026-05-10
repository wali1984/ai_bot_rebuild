```
# Phase 2Z — GO/NO-GO Request

## Rubric

For `07_GO_NO_GO.md` to flip to
`PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED`,
every row below must be PASS based on the operator and Codex audit of
`00_PHASE_2Z_SCOPE.md` through `06_IMPLEMENTATION_REPORT.md`:

1. Every entry in `required_output_files` exists at the exact path.
2. Every authored module imports compile cleanly:
   `python3 -c "from v2.backend.app.domain.degraded_state_fail_closed_gates import ...; from v2.backend.app.services.degraded_state_fail_closed_gates import ...; from v2.backend.app.composition.degraded_state_fail_closed_gates import ..."`
   prints `ok`.
3. Every authored unit test passes under the trainer venv when run via
   `pytest`.
4. No module imports `redis`, `aioredis`, or `redis.asyncio`.
5. No module imports `fastapi` or `starlette`.
6. No `__init__.py` registers a FastAPI lifespan.
7. The runtime closure invokes the captured clock zero times per call.
8. The `fail_closed` invariant holds for every per-source state
   combination, including the six matrix rows in the test plan.
9. No byte outside the three new V2 source directories, the three new
   V2 test directories, and the new
   `degraded_state_fail_closed_gates_impl/` docs directory is modified.
10. No execution-side surface is introduced.
11. No new lineage ID is introduced (`degraded_state_id` is a
    deterministic derivation of `decision_id`).
12. The live gate remains blocked and human-only.
13. No markdown fence wrapper is left on any required output.
14. `07_GO_NO_GO.md` contains exactly one non-empty line.

If any rubric row fails, `07_GO_NO_GO.md` instead contains
`PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED`
and `06_IMPLEMENTATION_REPORT.md` carries the per-row blocker list so
the planner can author a targeted Codex autofix recovery task per
REQ_0007 / REQ_0014.

PHASE_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_GO_NO_GO_REQUEST_READY
```
