# 05 — Enterprise GUI Scaffold Plan

## 1. Authority
`claude_worklog/v2_architecture/06_ENTERPRISE_GUI_UX_ARCHITECTURE.md`, `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`, `16_MOBILE_IPHONE_AND_PWA_READINESS.md`, plus the 26-page list under `Required V2 GUI Pages` in `CLAUDE.md` and `v2_requirements/16_ENTERPRISE_GUI_PAGE_MAP.md`. This plan defines milestone E's deliverable: a routable shell with placeholder pages for all required pages, RBAC-aware navigation, default-deny on dangerous controls, and a default `LIVE TRADING: BLOCKED` banner.

## 2. Frontend stack (frozen for milestone B)
- React 18 + TypeScript 5 + Vite.
- Router: TanStack Router or React Router v6 (chosen at scaffold time; the choice is fixed in `B_SCAFFOLD_VALIDATION.md`).
- State: Zustand for local UI state; React Query for server state (no global mutation singletons).
- Styling: Tailwind CSS + a small primitive component library (Radix UI). No demo theme widgets.
- Forms: React Hook Form + Zod for client-side schema validation that mirrors backend Pydantic shapes.
- Testing: Vitest (unit) + Playwright (e2e) + axe-core (a11y).
- PWA: Workbox-based service worker with cache-only strategy for static assets; no background trade actions.

## 3. Page inventory (26 pages + public surface + mobile readiness)
Each page is a folder under `frontend/src/pages/<page>/` with `index.tsx`, `route.ts`, `rbac.ts`, and `tests/`. The 26 admin/operator pages and the public surface:

| # | Page | Surface | RBAC default | Notes |
|---|------|---------|--------------|-------|
| 1 | Mission Control | admin/operator | viewer+ | global health/alerts/readiness |
| 2 | Monitor Center | admin/operator | viewer+ | every monitor script per CLAUDE.md Monitor Center Requirements |
| 3 | Coverage / System Atlas | admin | reviewer+ | shows file inventory + classification |
| 4 | Script Registry | admin | reviewer+ | scripts + usage evidence |
| 5 | Trainer Prediction Monitor | admin/operator | viewer+ | reads `evidence_packets` + `liveness_confidence_level` |
| 6 | Signal Explainability | admin/operator | viewer+ | per-signal lineage drilldown |
| 7 | Symbols | admin | viewer+ | universe member view |
| 8 | Signals | admin/operator | viewer+ | recent signals + lineage |
| 9 | Executions | admin | viewer+ | paper-only by default |
| 10 | Positions | admin | viewer+ | paper-only by default |
| 11 | Risk Control | admin | reviewer+ | policy bundles, kill switch (L4 to mutate) |
| 12 | Config Admin | admin | reviewer+ | versioned config; L4 for dangerous toggles |
| 13 | Strategy Admin | admin | reviewer+ | strategy registration |
| 14 | Trainer Admin | admin | reviewer+ | trainer adapter calls (read-only modes) |
| 15 | Orchestrator Admin | admin | reviewer+ | orchestrator adapter |
| 16 | Execution Admin | admin | reviewer+ | execution router (paper-only by default) |
| 17 | Paper Trading | admin/operator | viewer+ | paper-mode loop view |
| 18 | Replay | admin/operator | viewer+ | deterministic replay UI |
| 19 | Audit Ledger | admin | reviewer+ | append-only chain |
| 20 | System Health | admin/operator | viewer+ | dimension statuses |
| 21 | Live Readiness | admin | reviewer+ | shows GO inputs, L4/L5 buttons disabled until criteria met |
| 22 | Claude Admin AI | admin | reviewer+ | Claude supervision dashboard |
| 23 | Ollama Local Assistant | admin | reviewer+ | Ollama health + outputs |
| 24 | Codex Review Center | admin | reviewer+ | Codex review status |
| 25 | Build/Validation Status | admin/operator | viewer+ | lists `claude_worklog/v2_build/*` |
| 26 | Mobile/iPhone Readiness | admin | reviewer+ | PWA + future RN bridge readiness |
| P1 | Public Landing | public | none | marketing only; no controls |
| P2 | Public Status | public | none | high-level health only; no internal IDs |
| P3 | Login | public | none | session creation; CSRF-protected |

The page inventory mirrors `CLAUDE.md` Required V2 GUI Pages exactly. Adding pages requires updating `CLAUDE.md` first.

## 4. Admin/public split
- Admin surface mounts at `/admin/**` and is reachable only from allowlisted IPs (per `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`). Admin requests pass `step_up_mfa` middleware.
- Public surface mounts at `/` and `/status`. It carries no internal IDs and reads from `/public/v1/*` only.
- The router refuses to render an admin route if the actor has no admin binding; the response is the public landing page, not a 401 leak.

## 5. RBAC navigation
- `frontend/src/auth/rbac.ts` exports `useRoles()` and `canSee(page)`.
- The nav component reads `canSee(page)` and hides items the actor lacks. Pages that L4/L5 would mutate are visible to reviewers but the action buttons render disabled with a tooltip referencing the approval requirement.
- Roles: `viewer`, `operator`, `reviewer`, `admin`, `live_approver` (L5 only).

## 6. Default-deny on dangerous controls
Per `CLAUDE.md` Admin Control Rule, every dangerous setting is default-deny in the GUI:

- enable live trading
- add/activate live API keys
- increase leverage
- enable CROSS margin
- increase max position size
- increase daily loss limit
- disable kill switch
- disable mandatory stop
- enable hedge/DCA
- enable ADJUST_LEVERAGE
- switch paper to live

Each dangerous control renders as a disabled primary button with a `RequiresApprovalBadge` showing the required level (L4 or L5). Clicking the badge opens an approval-request modal that emits a `governance.approvals.create` request. The actual mutation never fires from the GUI without the approval token returned by the backend.

## 7. LIVE TRADING: BLOCKED banner
A persistent banner component lives in `frontend/src/components/banners/LiveBlockBanner.tsx`. It reads `/api/v1/risk/live-readiness` on each route change. The banner's text and color are deterministic:

- `LIVE TRADING: BLOCKED` — red — default.
- `LIVE TRADING: PENDING APPROVAL` — amber — when an L5 approval is in flight but not consumed.
- `LIVE TRADING: ACTIVE (bounded)` — green — only when `live_readiness_state.state = 'active'` AND `live_mode_envelope` is present. Bounded constraints (single account, single exchange, capped notional, capped leverage) are listed inside the banner.

The banner cannot be dismissed.

## 8. Lineage block UI
`frontend/src/lineage/block.tsx` is the canonical renderer for the lineage chain. Every page that displays a prediction/signal/decision/risk/intent payload uses this component to render the chain. The component shows `lineage_gap_reason` when any field is null and renders a click-through to the corresponding entity page.

## 9. Confidence explainability UI
The Signal Explainability page renders the `confidence_explainability_block` exactly as described in `12C` closure: top contributors with explicit placeholders if the cardinality is below 3, calibration record, model version + checkpoint, and rejection-class banner if the block was rejected.

## 10. PWA + iPhone readiness
- PWA manifest declares standalone display; offline cache is read-only-data-only.
- Service worker NEVER caches mutating responses.
- `frontend/src/mobile/bridge.ts` defines a TypeScript-only contract for a future React Native or SwiftUI bridge: navigation, RBAC, push notifications, and approval flow methods. No concrete bridge code is shipped.
- Push notifications for L4/L5 approval requests are designed in but disabled in milestone E.

## 11. Accessibility
- WCAG 2.1 AA. Color-contrast checks in CI via axe-core.
- Keyboard-only navigation tested in Playwright.

## 12. Error envelope rendering
The shared `ApiError` component renders `response.error.class`, `response.error.message`, and `request_id` for every failure. Lineage rejection classes link to a `LineageError` deep-page that shows the violating block.

## 13. Status
ENTERPRISE GUI SCAFFOLD: PLANNED. PAGES ARE SCAFFOLDED EMPTY IN MILESTONE B; ROUTABLE SHELL + RBAC NAV + BANNER MATERIALIZE IN MILESTONE E.