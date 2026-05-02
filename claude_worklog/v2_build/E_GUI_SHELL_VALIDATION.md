# E — Enterprise GUI Shell Validation (milestone E)

## 1. Scope
Materialize the V2 enterprise frontend shell with placeholder pages for all 26
admin/operator pages plus the 3 public pages enumerated in
`claude_worklog/v2_scaffold_planning/05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md` §3.
The shell renders a non-dismissible `LIVE TRADING: BLOCKED` banner on every
route, default-denies every dangerous control with a `RequiresApprovalBadge`,
implements RBAC nav visibility via `auth/rbac.ts`, ships a lineage block
component, registers a cache-only PWA service worker, and freezes a
TypeScript-only mobile bridge contract. Playwright e2e tests are added for
nav smoke, live-block banner, RBAC visibility, and dangerous-control inventory.

## 2. Boundaries observed
- Wrote only under `v2/frontend/**` and `claude_worklog/v2_build/**`.
- Did not edit `legacy_reference/**`, `../AI BOT/**`, any `.env`, or any
  secrets file.
- Did not place or cancel exchange orders.
- Did not change leverage or margin mode.
- Did not write to legacy Redis keys.
- Did not restart the live trader, live trainer, or any live service.
- Did not enable live trading. Banner is hard-coded to fail-safe to BLOCKED.
- Did not import legacy trainer modules into the FastAPI process or into the
  frontend bundle.
- Did not pip install into the trainer venv.
- Did not register a background-sync or push handler in the service worker;
  the cache-only contract is enforced.
- LIVE TRADING: BLOCKED (default).

## 3. Stack chosen at scaffold time
Per `05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md` §2 the router choice was deferred to
scaffold time. This validation fixes it.

- Router: `react-router-dom@6.26.2` (`createBrowserRouter` + `RouterProvider`).
- React 18.3.1, TypeScript 5.6.2, Vite 5.4.8 (unchanged from milestone B).
- Routing surface split: PublicShell at `/`, `/status`, `/login`; AdminShell
  at `/admin/**`. The router redirects unknown paths to `/`.
- Tailwind/Radix/Zustand/React Query/RHF/Zod/axe-core are NOT installed in
  this milestone — see §13 deviation log.

## 4. Page inventory materialized (29 pages × 4 files = 116 page files)
Each page folder under `v2/frontend/src/pages/<page>/` contains exactly four
files: `index.tsx`, `route.ts`, `rbac.ts`, `meta.ts`. The 29 pages cover the
26 admin/operator pages plus the 3 public pages. `pages/registry.ts`
imports each module statically so the router and nav consume one source.

| # | Page id | Path | Surface | Min role | Dangerous controls |
|---|---------|------|---------|----------|--------------------|
| 1 | mission-control | /admin/mission-control | admin | viewer | — |
| 2 | monitor-center | /admin/monitor-center | admin | viewer | — |
| 3 | coverage-system-atlas | /admin/coverage-system-atlas | admin | reviewer | — |
| 4 | script-registry | /admin/script-registry | admin | reviewer | — |
| 5 | trainer-prediction-monitor | /admin/trainer-prediction-monitor | admin | viewer | — |
| 6 | signal-explainability | /admin/signal-explainability | admin | viewer | — |
| 7 | symbols | /admin/symbols | admin | viewer | — |
| 8 | signals | /admin/signals | admin | viewer | — |
| 9 | executions | /admin/executions | admin | viewer | — |
| 10 | positions | /admin/positions | admin | viewer | — |
| 11 | risk-control | /admin/risk-control | admin | reviewer | disable_kill_switch (L5), disable_mandatory_stop (L5), increase_daily_loss_limit (L4) |
| 12 | config-admin | /admin/config-admin | admin | reviewer | enable_live_trading (L5), enable_adjust_leverage (L4), switch_paper_to_live (L5), enable_cross_margin (L4) |
| 13 | strategy-admin | /admin/strategy-admin | admin | reviewer | enable_hedge_dca (L4) |
| 14 | trainer-admin | /admin/trainer-admin | admin | reviewer | — |
| 15 | orchestrator-admin | /admin/orchestrator-admin | admin | reviewer | — |
| 16 | execution-admin | /admin/execution-admin | admin | reviewer | switch_paper_to_live (L5), increase_max_position_size (L4), add_live_api_keys (L5) |
| 17 | paper-trading | /admin/paper-trading | admin | viewer | — |
| 18 | replay | /admin/replay | admin | viewer | — |
| 19 | audit-ledger | /admin/audit-ledger | admin | reviewer | — |
| 20 | system-health | /admin/system-health | admin | viewer | — |
| 21 | live-readiness | /admin/live-readiness | admin | reviewer | enable_live_trading (L5), increase_leverage (L4) |
| 22 | claude-admin-ai | /admin/claude-admin-ai | admin | reviewer | — |
| 23 | ollama-local-assistant | /admin/ollama-local-assistant | admin | reviewer | — |
| 24 | codex-review-center | /admin/codex-review-center | admin | reviewer | — |
| 25 | build-validation-status | /admin/build-validation-status | admin | viewer | — |
| 26 | mobile-iphone-readiness | /admin/mobile-iphone-readiness | admin | reviewer | — |
| P1 | public-landing | / | public | public | — |
| P2 | public-status | /status | public | public | — |
| P3 | login | /login | public | public | — |

Page count matches `CLAUDE.md` Required V2 GUI Pages (26) plus the 3 public
pages enumerated in §3 of the scaffold plan. Adding a page still requires
updating `CLAUDE.md` first.

## 5. LiveBlockBanner contract
`v2/frontend/src/components/banners/LiveBlockBanner.tsx`:

- Mounted by `AdminShell` and `PublicShell` so every routed view renders
  exactly one banner instance regardless of surface.
- `data-testid="live-block-banner"` and `data-live-state="blocked|pending|active"`
  for deterministic e2e selection.
- Fetches `/api/v1/risk/live-readiness` on mount. On any non-200, network
  error, missing `state`, or `state='active'` without `live_mode_envelope`,
  the banner falls back to BLOCKED. Default state is BLOCKED before fetch.
- Three labels are emitted exactly: `LIVE TRADING: BLOCKED`,
  `LIVE TRADING: PENDING APPROVAL`, `LIVE TRADING: ACTIVE (bounded)` per
  scaffold plan §7.
- No dismiss button is rendered. Tests assert the absence of any
  dismiss/close control inside the banner.

## 6. Default-deny on dangerous controls
`v2/frontend/src/constants/dangerousControls.ts` declares the 11-item catalog
exactly matching `CLAUDE.md` Admin Control Rule:
`enable_live_trading`, `add_live_api_keys`, `increase_leverage`,
`enable_cross_margin`, `increase_max_position_size`, `increase_daily_loss_limit`,
`disable_kill_switch`, `disable_mandatory_stop`, `enable_hedge_dca`,
`enable_adjust_leverage`, `switch_paper_to_live`. Each carries a level
(L4 or L5) and a rationale.

`DangerousControlPanel` renders one disabled `<button>` per control with
`disabled` and `aria-disabled="true"`, paired with a `RequiresApprovalBadge`.
The badge opens a placeholder approval modal; the modal documents that it
would emit `governance.approvals.create` and that the mutation never fires
from the GUI without a backend-issued approval token. No mutation code path
exists in the shell.

## 7. RBAC nav visibility
`v2/frontend/src/auth/rbac.ts` exports `Role`, `canSee`, `canSeePage`, and a
`useRoles()` hook backed by `auth/session.ts`. The hierarchy is
`public(0) < viewer(1) < operator(2) < reviewer(3) < admin(4) < live_approver(5)`.

- `Nav` filters `ADMIN_PAGES` by `canSeePage(actor, page.rbac.minRole)`.
- `AdminShell` rejects `public` actors with a redirect to `/` (no 401 leak)
  and rejects per-page RBAC failures by redirecting to `/`.
- For the milestone E shell, the actor role is determined by
  `?role=<role>` (one-shot) or `sessionStorage['v2.session.role.shell']`.
  This is a test-only mechanism; the production session resolver lands in a
  later milestone.

## 8. Lineage block component
`v2/frontend/src/lineage/block.tsx` renders the canonical lineage chain for
a payload. Missing fields render as `missing` and surface
`lineage_gap_reason` when present. Present fields with a known entity type
(`prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`,
`intent_id`) render as click-throughs to the corresponding admin page with
`?id=<value>`. The component is exported and ready to be wired to the
Signal Explainability page in a follow-up.

## 9. PWA + service worker
- `v2/frontend/public/manifest.webmanifest` declares `display: standalone`,
  `start_url: /`, dark theme, and two icon entries.
- `v2/frontend/public/service-worker.js` implements a cache-only strategy:
  - GET-only requests are eligible.
  - All `/api/**` responses are passed straight through without caching.
  - Background sync, push handlers, and any retry queue are intentionally
    NOT registered.
  - Comment block at the top of the file restates the contract:
    `NEVER caches mutating responses. NEVER performs background sync of
    trade actions. NEVER replays POST/PUT/PATCH/DELETE.`
- `v2/frontend/src/pwa/registerServiceWorker.ts` registers the worker on
  `window.load` with scope `/`. Registration failure is logged and
  non-fatal.

## 10. Mobile bridge contract (TypeScript-only)
`v2/frontend/src/mobile/bridge.ts` defines four interfaces:
`MobileNavigationBridge`, `MobileRbacBridge`,
`MobilePushNotificationBridge`, `MobileApprovalBridge`, plus a composite
`MobileBridge`. A `MOBILE_BRIDGE_FEATURES` constant freezes the milestone
posture: `pushNotificationsEnabled: false`,
`reactNativeBridgeShipped: false`, `swiftUiBridgeShipped: false`. No
concrete bridge code is shipped, matching `16_MOBILE_IPHONE_AND_PWA_READINESS.md`.

## 11. Playwright e2e tests
`v2/frontend/tests/e2e/`:

- `nav_smoke.spec.ts` — opens every page (29 paths) and asserts the banner
  and an `<h1>` are visible.
- `live_block_banner.spec.ts` — for every page, asserts banner text equals
  `LIVE TRADING: BLOCKED`, `data-live-state="blocked"`, and that no
  dismiss/close button exists inside the banner.
- `rbac_visibility.spec.ts` — verifies viewer sees only viewer-eligible nav
  entries; reviewer sees viewer + reviewer entries; public actor is
  redirected from `/admin/**` to `/`; viewer hitting a reviewer-only page
  is redirected to `/`.
- `default_deny_inventory.spec.ts` — for the 5 pages with dangerous
  controls, asserts every listed control is disabled, has
  `aria-disabled="true"`, and renders its `RequiresApprovalBadge`.

`playwright.config.ts` reuses an existing dev server when present and
otherwise launches `npm run dev` on port 5173. Suite execution is gated
on `npm install` having been run; this milestone emits the test sources
and the configuration only.

## 12. CSS / layout
A single plain-CSS file (`src/styles.css`) styles the shell. It is small
enough to read end-to-end and avoids pulling in Tailwind plumbing in this
milestone — see §13.

## 13. Deviations from `05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md`
- Tailwind CSS, Radix UI, Zustand, React Query, React Hook Form, Zod, and
  axe-core are NOT installed in milestone E. The shell uses plain CSS and
  React's `useSyncExternalStore`/`useState`/`useEffect`. These additions
  are deferred to milestone F (functional pages); they do not affect any
  safety property listed in §6 or §9.
- The service worker is hand-rolled rather than Workbox-based. The
  cache-only contract is enforced explicitly in `service-worker.js`
  comments + code; no Workbox dependency was added. Migration to Workbox
  is permissible later as long as the cache-only contract is preserved.
- A11y is structurally supported (semantic landmarks, `aria-disabled`,
  `aria-live`) but axe-core CI gating is deferred to milestone F.

None of these deviations weaken safety or remove any requirement from
this milestone's deliverable list.

## 14. Files written
- `v2/frontend/index.html`
- `v2/frontend/package.json` (overwritten — added `react-router-dom`,
  `@playwright/test`, `@types/node`)
- `v2/frontend/tsconfig.json` (overwritten — `include` now `["src","tests"]`,
  added `types: ["node"]`)
- `v2/frontend/playwright.config.ts`
- `v2/frontend/public/manifest.webmanifest`
- `v2/frontend/public/service-worker.js`
- `v2/frontend/src/main.tsx`
- `v2/frontend/src/App.tsx`
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/styles.css`
- `v2/frontend/src/auth/rbac.ts`
- `v2/frontend/src/auth/session.ts`
- `v2/frontend/src/constants/dangerousControls.ts`
- `v2/frontend/src/constants/liveReadiness.ts`
- `v2/frontend/src/types/page.ts`
- `v2/frontend/src/components/banners/LiveBlockBanner.tsx`
- `v2/frontend/src/components/controls/RequiresApprovalBadge.tsx`
- `v2/frontend/src/components/controls/DangerousControlPanel.tsx`
- `v2/frontend/src/components/layout/AdminShell.tsx`
- `v2/frontend/src/components/layout/PublicShell.tsx`
- `v2/frontend/src/components/layout/Nav.tsx`
- `v2/frontend/src/components/layout/PageShell.tsx`
- `v2/frontend/src/components/api/ApiError.tsx`
- `v2/frontend/src/lineage/block.tsx`
- `v2/frontend/src/mobile/bridge.ts`
- `v2/frontend/src/pwa/registerServiceWorker.ts`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/<page>/{index.tsx,route.ts,rbac.ts,meta.ts}` for the
  29 pages enumerated in §4 (116 page files total)
- `v2/frontend/tests/e2e/_shared.ts`
- `v2/frontend/tests/e2e/nav_smoke.spec.ts`
- `v2/frontend/tests/e2e/live_block_banner.spec.ts`
- `v2/frontend/tests/e2e/rbac_visibility.spec.ts`
- `v2/frontend/tests/e2e/default_deny_inventory.spec.ts`
- `claude_worklog/v2_build/E_GUI_SHELL_VALIDATION.md` (this file)

## 15. Verification (planning-level for this headless emission)
This artifact was emitted as `BEGIN_FILE` blocks per the headless contract
used for milestones B/C/D. Concrete CI runs (`tsc -b`, `vite build`,
`playwright test`) are the gate for promoting this artifact to a
post-install validated state in a tool-enabled follow-up. The page count
(29), dangerous-control catalog cardinality (11), banner determinism
(default BLOCKED), and service-worker cache-only contract are auditable
directly from the emitted source.

## 16. Status
E_GUI_SHELL_VALIDATION_READY
