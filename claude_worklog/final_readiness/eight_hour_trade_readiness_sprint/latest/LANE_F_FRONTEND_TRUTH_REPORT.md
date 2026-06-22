# Lane F — Frontend Truth Page (Simple Status) — Truth Report

Lane: F
Sprint: EIGHT_HOUR_TRADE_READINESS_IMPLEMENTATION_SPRINT
Status: LANE_F_FRONTEND_TRUTH_PAGE_READY
Live gate: blocked_human_only
Live symbols: []
Approves live: false

## What was added

A new public-surface page rendered in plain English ("simple mode") for non-technical
viewers, located at route `/status-simple`.

Page id: `user-status`
Surface: `public`
Min role: `viewer`
Route path: `/status-simple`
Test id: `page-user-status`

New files:
- `v2/frontend/src/pages/user-status/meta.ts`
- `v2/frontend/src/pages/user-status/route.ts`
- `v2/frontend/src/pages/user-status/rbac.ts`
- `v2/frontend/src/pages/user-status/index.tsx`

Wiring touched (append-only, no existing entries reordered or removed):
- `v2/frontend/src/pages/registry.ts` — added 4 imports for the new page and a single
  `PAGES` array entry placed between `publicStatusMeta` and `loginMeta`.
- `v2/frontend/tests/e2e/_shared.ts` — added `'/status-simple'` to `PUBLIC_PAGE_PATHS`
  while preserving the existing public entries `'/'`, `'/status'`, `'/login'`.

## What data the page consumes

The page consumes only the V2 frontend truth payload via
`useFrontendTruthPayload` from `v2/frontend/src/data/runtimePayloads.ts`,
which fetches:

  `/operator_runtime/frontend_truth/latest/frontend_truth_payload.json`

Fields rendered:
- `plain_english_summary` — one-line headline
- `current_goal` — today's goal
- Status badges (plain English):
  - Live gate: hard-coded "Bot is not allowed to trade live" (color red),
    reinforcing `live_gate=blocked_human_only`
  - `paper_edge_status`
  - `trainer_parity_status`
  - `decision_quality_status`
  - `shutdown_recommendation`
- `blockers_simple` — bullet list in plain English
- `page_cards[]` — rendered via `SimpleCard` from
  `v2/frontend/src/components/status-simple/StatusBadge.tsx`
- `stale_payloads` and `missing_payloads` — surfaced as a "Some evidence is old or
  missing" section

If the truth payload cannot be loaded, the page renders the literal text
`MISSING_EVIDENCE. We cannot show a status because the truth file is not here yet.
We will not invent values.` and a red `StatusBadge`.

## Components used

- `StatusBadge` from `v2/frontend/src/components/status-simple/StatusBadge`
- `SimpleCard` from `v2/frontend/src/components/status-simple/StatusBadge`

No other UI components are used. No legacy Redis fetches. No mock current data.
No internal IDs are surfaced. No live controls are rendered.

## Typecheck

Command:

  cd v2/frontend && npx tsc -b --noEmit

Result: clean (exit 0). No errors, no warnings.

## What is explicitly NOT done

- No backend route, FastAPI handler, or HTTP endpoint was added — the page is a
  pure client-side consumer of an already-published JSON artifact.
- No edits to `v2/frontend/src/pages/permanent-migration/` — the existing
  permanent-migration page is untouched.
- No edits to any non-Lane-F file outside the four allowed files
  (`registry.ts`, `_shared.ts`, plus the four new files inside
  `pages/user-status/`).
- No change to live gate; `live_gate` remains `blocked_human_only` and
  `approves_live=false`.
- No additions to `ADMIN_PAGE_PATHS`, `REVIEWER_ONLY_ADMIN_PATHS`, or
  `VIEWER_VISIBLE_ADMIN_PATHS` in `_shared.ts` — only `PUBLIC_PAGE_PATHS` was
  appended, because the new surface is `public`.
- No e2e Playwright spec file was added; existing public-route coverage in
  `_shared.ts` will pick up the new path because it is now in
  `PUBLIC_PAGE_PATHS` / `ALL_PAGE_PATHS`.
- No new dependency, no package.json change, no build-tool change.
- No documentation file outside this report and the JSON status was created.
- No mobile/iPhone-specific styling beyond the responsive `maxWidth: 960` and
  flex-wrap on the badge row already present in the existing simple-status
  component family.

## Sources verified by direct read

- `v2/frontend/src/data/runtimePayloads.ts` — confirmed
  `useFrontendTruthPayload` shape and that it fetches the JSON via no-store
  fetch, with `stale_payloads` / `missing_payloads` fields available.
- `v2/frontend/src/components/status-simple/StatusBadge.tsx` — confirmed
  exported names: `StatusBadge`, `SimpleCard`, `StatusBadgeProps`,
  `SimpleCardProps`.
- `v2/frontend/src/pages/permanent-migration/{index.tsx,meta.ts,rbac.ts,route.ts}` —
  used as pattern reference for the new page.
- `v2/frontend/src/types/page.ts` — confirmed `PageMeta`, `PageRbac`,
  `PageRoute` shape.
- `v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json` —
  confirmed real payload exists and the fields used by this page are present.
- `v2/frontend/src/pages/registry.ts` — confirmed import + PAGES pattern;
  appended without modifying existing entries.
- `v2/frontend/tests/e2e/_shared.ts` — confirmed `PUBLIC_PAGE_PATHS`
  structure; appended without modifying existing entries.

## GO / NO-GO

GO_NO_GO: LANE_F_FRONTEND_TRUTH_PAGE_READY
