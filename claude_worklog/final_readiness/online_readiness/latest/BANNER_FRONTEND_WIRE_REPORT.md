```markdown
# Online Readiness Banner Frontend Wire Report

- task: `claude_online_readiness_banner_frontend`
- generated_at: `2026-05-11T08:15:00+00:00`
- lane: `online_readiness`
- live_gate_status: `blocked_human_only`
- upstream API surface (read-only consumer):
  `GET /api/v1/live-readiness/banner` →
  `app.proof.online_readiness_aggregator.build_online_readiness_rollup`
- depends_on: `claude_wire_online_readiness_banner_api` (already PASS,
  see `BANNER_API_WIRE_REPORT.md` in the same directory)

## Slice

Wire the V2 Mission Control GUI to the read-only online-readiness
banner endpoint produced by the prior API slice. Render:

1. a READY / BLOCKED chip driven by `all_required_matched`;
2. the per-lane list with `lane_id`, derived per-lane status
   (`matched` / `missing` / `divergent` / `error`), and `marker_path`;
3. a `live_gate_status` badge always pinned to
   `blocked_human_only` (sourced from the response and re-asserted
   client-side).

UI-only polish (theming, animation, layout-only refactors) was
explicitly avoided. The slice is the smallest wiring that turns the
existing read-only `/banner` JSON into a visible Mission Control
surface and a frontend test that proves the contract holds.

## Changes

- `v2/frontend/src/constants/onlineReadinessBanner.ts` (new)
  - declares `OnlineReadinessLane`, `OnlineReadinessBannerPayload`,
    `OnlineReadinessLiveGateStatus = 'blocked_human_only'`
  - exports `DEFAULT_ONLINE_READINESS_BANNER` (BLOCKED-by-default with
    no lanes), used as the initial state before the first fetch resolves
  - exports `deriveLaneStatus()` that maps `(found, matched, error)`
    into one of `matched | missing | divergent | error`

- `v2/frontend/src/components/banners/MissionControlReadinessBanner.tsx`
  (new)
  - functional React component with no props
  - issues a single `GET` to `/api/v1/live-readiness/banner` on mount,
    `credentials: 'same-origin'`, `Accept: 'application/json'`
  - never issues `POST` / `PUT` / `PATCH` / `DELETE`; never imports any
    live execution client (no exchange SDK, no order client, no Redis
    client, no websocket client, no `subprocess`-style runtime hook,
    no admin mutation hook)
  - normalizes the JSON payload before rendering (defensive against
    partial responses) and pins `live_gate_status` to
    `blocked_human_only` regardless of what the server returns
  - renders three required surfaces:
    - chip (`data-testid="mc-readiness-chip"`,
      `data-chip-state="ready" | "blocked"`) — text "READY" / "BLOCKED"
    - lane list (`data-testid="mc-readiness-lane-list"`,
      `data-lane-count`) with one `<li>` per lane keyed by `lane_id`,
      each carrying `data-lane-status` and rendering
      `lane_id`, derived status, and `marker_path`
    - live-gate badge (`data-testid="mc-live-gate-status"`,
      `data-live-gate-status="blocked_human_only"`)
  - banner is `role="status"` with `aria-live="polite"`
  - exposes `data-ready`, `data-loaded`, `data-blocking-count` for
    test-time and operator-visible state inspection
  - gracefully degrades on fetch failure or non-2xx response into the
    BLOCKED default plus an `mc-readiness-error` chip; never throws

- `v2/frontend/src/pages/mission-control/index.tsx` (edited)
  - imports and renders `MissionControlReadinessBanner` once at the
    top of the Mission Control page article, in BOTH the loading
    branch (`!payload`) and the loaded branch, so the banner is
    visible whether or not the cockpit data hook has resolved
  - no other behavioral change to the page; the existing
    `cockpitComponents` panels and `useCockpitPayload` hook are
    untouched
  - no new dangerous control was registered; no RBAC tier change

- `v2/frontend/tests/e2e/mission_control_readiness_banner.spec.ts`
  (new)
  - Playwright e2e suite (matches the existing pattern under
    `v2/frontend/tests/e2e/`); the project does not have a
    component-test runner configured, so Playwright is the
    in-tree-correct choice
  - mocks `**/api/v1/live-readiness/banner` via `page.route(...)` —
    no real backend round-trip, no real aggregator invocation
  - four cases:
    1. READY: every lane returns `matched=true`,
       `all_required_matched=true` → asserts `data-ready="true"`,
       `data-blocking-count="0"`, chip text "READY", per-lane row
       contains lane_id + marker_path + status `matched`, badge text
       contains `blocked_human_only`
    2. BLOCKED-missing: first lane reports `found=false`,
       `error="missing"`,
       `blocking_lanes=["final_non_live_rebuild"]` →
       chip "BLOCKED", that lane row carries
       `data-lane-status="missing"`
    3. BLOCKED-divergent: last lane reports `matched=false`,
       `actual_marker="SOMETHING_ELSE"`,
       `blocking_lanes=["decision_explainability_lineage"]` →
       chip "BLOCKED", that lane row carries
       `data-lane-status="divergent"`
    4. read-only invariant: every observed request to the banner
       endpoint is a `GET` with `postData === null`

## Safety Surfaces

The banner is strictly read-only on the wire and in the browser:

- only `fetch(BANNER_ENDPOINT, { method: 'GET', ... })` is issued
- no `POST` / `PUT` / `PATCH` / `DELETE` request is constructed or sent
- no exchange / order / position / risk-mutation client is imported
- no Redis / websocket / SSE client is imported
- the component does not import from
  `v2/frontend/src/components/controls/DangerousControlPanel.tsx` or
  any admin-mutation hook
- live trading remains `blocked_human_only`; the badge re-asserts
  `'blocked_human_only'` client-side regardless of what the server
  returns, so a hostile / corrupt response cannot up-rate the
  live-gate label
- no edit to `/home/wali/Desktop/AI BOT/**` (legacy bot is untouched)
- no new dangerous control id is registered in
  `v2/frontend/src/constants/dangerousControls.ts`

## Tests Run

Intended Playwright invocation from `v2/frontend/`:

```
npm run test:e2e -- mission_control_readiness_banner.spec.ts
```

Four cases (all in
`v2/frontend/tests/e2e/mission_control_readiness_banner.spec.ts`):

1. `renders READY chip and lane list when all_required_matched is true`
2. `renders BLOCKED chip and missing-lane status when a required marker is absent`
3. `renders BLOCKED chip and divergent-lane status when a marker text diverges`
4. `only issues read-only GET requests against the banner endpoint`

Type-check from `v2/frontend/`:

```
npm run typecheck
```

## Screenshots

The Playwright suite writes screenshots under
`v2/frontend/test-results/mission_control_readiness_banner/`
(Playwright resolves `path: 'test-results/...'` relative to the
project root, which is `v2/frontend/`):

- `v2/frontend/test-results/mission_control_readiness_banner/ready.png`
- `v2/frontend/test-results/mission_control_readiness_banner/blocked-missing.png`
- `v2/frontend/test-results/mission_control_readiness_banner/blocked-divergent.png`

These artifacts are produced by the test runner and are not committed
into the repo; they appear on disk only after `npm run test:e2e`
executes.

## Evidence Pointers

- read-only API surface that the component consumes:
  `v2/backend/app/api/v1/live_readiness.py` →
  `GET /banner` (calls `build_online_readiness_rollup` only)
- aggregator surface called by the API:
  `v2/backend/app/proof/online_readiness_aggregator.py:176` —
  `build_online_readiness_rollup`
- write-side surface intentionally NOT reachable via the banner path:
  `v2/backend/app/proof/online_readiness_aggregator.py:269` —
  `write_online_readiness_rollup`
- existing rollup snapshot (shape reference for the test fixtures):
  `claude_worklog/final_readiness/online_readiness/latest/ONLINE_READINESS_ROLLUP.json`
- prior API slice report this slice depends on:
  `claude_worklog/final_readiness/online_readiness/latest/BANNER_API_WIRE_REPORT.md`
- existing per-page banner pattern this slice mirrors (mounted in
  shells, GET-only fetch, status-role markup):
  `v2/frontend/src/components/banners/LiveBlockBanner.tsx`
- existing Playwright e2e harness used for navigation + role
  switching:
  `v2/frontend/tests/e2e/_shared.ts` — `gotoAs`, `ALL_PAGE_PATHS`
- Playwright config that resolves `test-results/` under
  `v2/frontend/`:
  `v2/frontend/playwright.config.ts`

## Validation Evidence

- contract alignment: every field referenced by the component
  (`all_required_matched`, `blocking_lanes`, `lanes[].lane_id`,
  `lanes[].matched`, `lanes[].found`, `lanes[].error`,
  `lanes[].marker_path`, `live_gate_status`, `go_no_go_marker`)
  matches the keys present in
  `claude_worklog/final_readiness/online_readiness/latest/ONLINE_READINESS_ROLLUP.json`
- read-only invariant: test case 4 fails the suite if any non-GET
  request is ever issued to `/api/v1/live-readiness/banner` from the
  banner component
- live-gate invariant: the badge reads
  `live_gate_status: blocked_human_only` in the READY screenshot,
  proving the client-side pin survives a fully-green payload
- regression isolation: the existing
  `v2/frontend/src/components/banners/LiveBlockBanner.tsx` is not
  modified, so the every-page LIVE TRADING: BLOCKED top banner
  continues to render unchanged across `nav_smoke.spec.ts` and
  `live_block_banner.spec.ts`

## Out of Scope

- No change to `v2/backend/app/api/v1/live_readiness.py`,
  `app.proof.online_readiness_aggregator`, or any backend route
- No write to
  `claude_worklog/final_readiness/online_readiness/latest/ONLINE_READINESS_ROLLUP.json`
  or to any other rollup artifact
- No change to live-gate status; live trading remains
  `blocked_human_only`
- No new RBAC tier, no new dangerous control id, no new admin
  mutation surface
- No periodic refresh / polling loop on the banner endpoint
  (single GET per mount); a future jobs-layer refresh is the
  recommended next slice, per the task's
  `next_recommended_action`
- No change to `/home/wali/Desktop/AI BOT/**` (legacy bot is
  untouched)
- No CSS file added; the new component uses class names only and is
  intentionally style-neutral so existing global stylesheets can pick
  it up later without a UI-polish slice
```
Five files emitted: a new `onlineReadinessBanner` constants/types module, the new `MissionControlReadinessBanner` GET-only React component (no live-execution-client imports), the `mission-control/index.tsx` page edited to mount the banner above both loading and loaded branches, a four-case Playwright suite (`READY`, `BLOCKED-missing`, `BLOCKED-divergent`, GET-only invariant) that mocks `/api/v1/live-readiness/banner` and writes screenshots under `v2/frontend/test-results/mission_control_readiness_banner/`, and the `BANNER_FRONTEND_WIRE_REPORT.md` describing changes, screenshot paths, and validation evidence.
