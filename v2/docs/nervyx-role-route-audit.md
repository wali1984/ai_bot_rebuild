# NERVYX Role Route Audit

## Backend-Authenticated Audit

- Generated artifact: `artifacts/nervyx-role-route-audit-backend-auth.json`
- Generated at: `2026-06-23T18:03:57.951Z`
- Screenshot directory: `artifacts/nervyx-role-route-audit-backend-auth-screenshots/`
- Artifact screenshot paths: `580`
- Files currently in screenshot directory: `690` because prior captures are retained in the same directory.
- Status: `IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT`
- Final goal proof: `false`
- Auth mode: `backend_login`
- Auth fixture kind: `backend_login_cookie_session_isolated_user_store`
- Backend auth gate proven: `true`
- `?role=` used for authorization proof: `false`

This audit used an isolated temporary backend auth store and real backend
`POST /api/auth/login` plus cookie-backed `GET /api/auth/me` sessions. It did
not modify the real auth store and did not touch live execution paths.

| Role | Rows | Backend auth proof |
|---|---:|---|
| guest | 116 | `/api/auth/me` returned `401` |
| viewer | 116 | login `200`, `/api/auth/me` `viewer` |
| trader | 116 | login `200`, `/api/auth/me` `trader` |
| admin | 116 | login `200`, `/api/auth/me` `admin` |
| superadmin | 116 | login `200`, `/api/auth/me` `superadmin` |

| Metric | Count |
|---|---:|
| Total route-role rows | 580 |
| Roles | 5 |
| Routes per role | 116 |
| Canonical routes | 51 |
| Legacy redirects | 65 |
| Rendered | 133 |
| Restricted | 156 |
| Redirected | 291 |
| Loading/error states | 0 |
| Rows with WebSocket URLs | 314 |
| Rows with frames received/sent | 297 |
| Rows with failed requests | 0 |
| Failed request count | 0 |
| Rows with navigation-aborted requests | 90 |
| Navigation-aborted request count | 266 |
| Rows with console errors | 0 |
| Console error count | 0 |
| Rows with expected guest-auth console challenges | 116 |
| Expected guest-auth console challenge count | 117 |
| Rows with horizontal overflow | 0 |
| Rows with clipped text | 0 |
| Rows with visible old branding | 0 |
| Rows with unauthorized content leakage | 0 |

## Role Group Coverage

The refreshed audit contract now uses the live `/admin/...` canonical routes
from the current product navigation instead of treating legacy `/system/...`
paths as canonical admin pages.

| Role | Public canonical | Trader canonical | Admin canonical | Superadmin canonical |
|---|---:|---:|---:|---:|
| guest | 5 rendered | 2 rendered / 18 redirected | 24 redirected | 1 redirected |
| viewer | 5 rendered | 10 rendered / 6 restricted / 4 redirected | 24 restricted | 1 restricted |
| trader | 5 rendered | 15 rendered / 5 redirected | 24 restricted | 1 restricted |
| admin | 5 rendered | 15 rendered / 5 redirected | 24 rendered | 1 restricted |
| superadmin | 5 rendered | 15 rendered / 5 redirected | 24 rendered | 1 rendered |

## Current Findings

- Backend-authenticated route coverage is now proven for guest, viewer, trader, admin, and superadmin.
- Admin and superadmin pages rendered under real backend-issued sessions in the isolated audit lane. Admin rendered all 24 canonical admin pages and was restricted from the canonical superadmin page; superadmin rendered all 24 admin pages plus the canonical superadmin page.
- Unauthorized content leakage remains clear in this backend-authenticated audit: `0` rows.
- Old visible wording patterns remain clear in this backend-authenticated audit: `0` rows matched the audit's legacy branding/misleading execution phrases.
- Realtime transport is materially exercised: `314` route-role rows opened WebSocket URLs and `297` rows received or sent frames, including market, portfolio, signals, risk, orchestrator, paper activity, adaptive-capital, and liquidation heatmap streams.
- Presentation status improved: horizontal overflow is `0` rows and clipped text is `0` rows after scoped wrapping, table, status-pill, and source-badge fixes. During this continuation the backend-auth audit moved from `132` clipped rows to `24`, then `15`, then `0`.
- Runtime request and console classification is cleaner in the current artifact: `0` rows recorded real failed requests and `0` rows recorded real console errors.
- The audit separately records `90` rows with `266` navigation-aborted requests. These are rapid route-transition cancellations such as cancelled streams during audit navigation, not backend request failures.
- The audit separately records `116` guest rows with `117` expected auth challenge console events from the deliberate unauthenticated `/api/auth/me` probe.
- Field-level validity remains unproven. WebSocket activity proves streams opened; it does not prove every displayed value is fresh, semantically valid, non-stale, and not a fabricated zero.

## Secondary Fixture Audit

- Generated artifact: `artifacts/nervyx-role-route-audit.json`
- Generated at: `2026-06-23T04:49:08.310Z`
- Screenshot directory: `artifacts/nervyx-role-route-audit-screenshots/`
- Status: `IN_PROGRESS_PARTIAL_FIXTURE_AUDIT`
- Auth fixture kind: `playwright_api_auth_me_fixture_not_backend_login`

The fixture audit is retained as historical comparison evidence only. The
backend-authenticated artifact above supersedes it for role authorization proof.

## Current Clipped-Text Hotspots

No clipped-text rows remain in the latest backend-authenticated route audit.

## Remaining Gate

The full requested role-route gate remains `IN PROGRESS` until stale fields,
missing fields, and per-field value validity are classified or fixed. The
broader NERVYX ONE goal also still requires lane-isolation proof, 100% data
parity, full test suites, native iOS/watchOS macOS validation, TestFlight
readiness, and OpenAPI compatibility evidence.
