```markdown
# Online Readiness Banner API Wire Report

- task: `claude_primary_online_readiness_banner_api_wire`
- generated_at: `2026-05-11T00:00:00+00:00`
- lane: `online_readiness`
- live_gate_status: `blocked_human_only`
- upstream aggregate marker (read-only consumer):
  `CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_*`

## Slice

Wire `GET /api/v1/live-readiness/banner` so the V2 GUI can read the
online-readiness rollup in-process, without re-running the write-side
aggregator. The endpoint is the read-only view layer that sits on top of
`app.proof.online_readiness_aggregator.build_online_readiness_rollup`
(materialized in the prior 069DC2 slice that produced the
`online_readiness_aggregator` module and its proof tests).

UI-only polish was explicitly avoided. The slice is the smallest wire-up
that converts the existing scaffold OPTIONS shim into a functional
read-only banner endpoint.

## Changes

- `v2/backend/app/api/v1/live_readiness.py`
  - imports `build_online_readiness_rollup` from
    `app.proof.online_readiness_aggregator`
  - adds `_resolve_repo_root()` honoring `V2_ONLINE_READINESS_REPO_ROOT`
    for fixtures and falling back to `Path(__file__).parents[5]`
  - adds `GET /banner` that calls
    `build_online_readiness_rollup(_resolve_repo_root())` and returns
    the rollup dict as JSON
  - preserves the existing `ROUTE_METADATA` constant (already advertises
    `/banner`) and the OPTIONS shim that returns it
  - intentionally does NOT import `write_online_readiness_rollup`, so no
    file is ever produced by the API handler
- `v2/backend/tests/unit/api/__init__.py` — new test package
- `v2/backend/tests/unit/api/test_live_readiness_banner.py` — new
  - five tests through FastAPI `TestClient`:
    1. READY path: all five lane markers seeded → 200, READY marker,
       `all_required_matched=True`, empty `blocking_lanes`
    2. BLOCKED-missing path: first lane marker deleted → 200, BLOCKED
       marker, lane id present in `blocking_lanes`, lane reports
       `error="missing"`
    3. BLOCKED-divergent path: last lane marker text replaced with
       `SOMETHING_ELSE` → 200, BLOCKED marker, divergent lane reports
       `actual_marker="SOMETHING_ELSE"`
    4. read-only snapshot test: three consecutive GETs leave the
       `tmp_path` tree byte-stable (size + mtime)
    5. source-level forbidden-import scan: handler source contains
       neither Redis / ccxt / websockets / requests / subprocess
       references nor a call to `write_online_readiness_rollup`

## Safety Surfaces

The handler is strictly read-only:

- no Redis client is imported or constructed
- no exchange / websocket / HTTP client is imported or invoked
- no child process is spawned (no `subprocess`, `os.system`, or
  `asyncio.create_subprocess_*`)
- no file is opened in write / append / truncate mode by this handler;
  the aggregator only reads marker files via `Path.read_text(...)`
- `write_online_readiness_rollup` is NOT imported or called from this
  endpoint, so no rollup artifacts on disk are regenerated as a side
  effect of an API request
- the router still sits outside `/live/`, so the live-block guard does
  not gate it; live trading remains `blocked_human_only`

`live_gate_status` in every response body is always
`blocked_human_only`, sourced from
`online_readiness_aggregator.LIVE_GATE_STATUS`.

## Tests Run

Intended pytest invocation from `v2/`:

```
pytest backend/tests/unit/api/test_live_readiness_banner.py -q
```

Five cases:

1. `test_banner_returns_ready_when_all_lane_markers_match`
2. `test_banner_returns_blocked_when_required_marker_missing`
3. `test_banner_returns_blocked_when_marker_text_diverges`
4. `test_banner_does_not_write_inside_repo_root`
5. `test_banner_handler_imports_no_live_runtime_clients`

## Evidence Pointers

- read-only aggregator surface (called by this endpoint):
  `v2/backend/app/proof/online_readiness_aggregator.py:176` —
  `build_online_readiness_rollup`
- write-side surface (intentionally NOT called by this endpoint):
  `v2/backend/app/proof/online_readiness_aggregator.py:269` —
  `write_online_readiness_rollup`
- lane spec used by both aggregator and these tests:
  `v2/backend/app/proof/online_readiness_aggregator.py:87` — `LANES`
- aggregator unit tests this endpoint piggybacks on:
  `v2/backend/tests/unit/proof/test_online_readiness_aggregator.py`
- router mount under app factory:
  `v2/backend/app/main.py:118` — `live_readiness.router` mounted under
  `/api/v1`
- forbidden-operation surface enumerated by the aggregator:
  `v2/backend/app/proof/online_readiness_aggregator.py:53` —
  `FORBIDDEN_OPERATIONS`

## Out of Scope

- No change to `write_online_readiness_rollup` or to the on-disk rollup
  artifacts under
  `claude_worklog/final_readiness/online_readiness/latest/`
- No change to live-gate status; live trading remains
  `blocked_human_only`
- No new middleware, RBAC tier change, or live-block-guard edit; the
  router is still outside `/live/` so the guard does not match it
- No edit to `/home/wali/Desktop/AI BOT/**` (legacy bot is untouched)
- No Redis read or write
```
Four files emitted: the updated router with the read-only `/banner` handler (calling `build_online_readiness_rollup` only), an empty `__init__.py` for the new `tests/unit/api/` package, five-case TestClient unit suite (READY, BLOCKED-missing, BLOCKED-divergent, no-write snapshot, source-level forbidden-import scan), and the `BANNER_API_WIRE_REPORT.md` documenting changes, tests, and evidence pointers.
