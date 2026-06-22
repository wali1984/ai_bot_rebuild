# V2 Admin Control Inventory

Date: 2026-06-15
Status: Initial inventory. No admin control is accepted for production mutation.

## Control safety policy

- All admin controls must be under `/admin/*` canonical routes.
- All controls require backend-confirmed admin/superadmin role.
- Mutating controls require confirmation, reason, backend authorization, audit event, and visible result.
- Real live trading controls remain disabled unless separate live-gate/superadmin approval process is completed.

## Current observed control areas

| Area | Current route family | Required canonical route | Current control status | Missing safety evidence | Status |
| --- | --- | --- | --- | --- | --- |
| Admin dashboard/system | `/system`, `/system/control-center` | `/admin`, `/admin/system` | read-only/partial | backend monitoring APIs and route health | BLOCKED |
| Ingestors | `/system/ingestors` | `/admin/ingestors` | controls not accepted | start/stop/restart/resync/backfill authorization/audit | BLOCKED |
| Trainer | `/system/trainer` | `/admin/trainer` | controls not accepted | start/pause/cancel/promote/rollback audit and RBAC | BLOCKED |
| Orchestrator | `/system/orchestrator` | `/admin/orchestrator` | controls not accepted | queue/job controls audit | BLOCKED |
| Risk | `/system/risk-controllers` | `/admin/risk` | controls must remain fail-closed | kill switch/override confirmation and audit | BLOCKED |
| Strategy controls | `/system/strategy-controls` | admin-only or remove | not accepted | explicit approval required before strategy/risk edits | BLOCKED |
| Execution | `/system/execution` | `/admin/execution` | no live mutation accepted | order router controls must remain blocked | BLOCKED |
| Exchanges | `/system/exchanges` | `/admin/exchanges` | read-only connectivity only | masked credentials, permission proof, no mutation | BLOCKED |
| Config | `/system/config` | `/admin/config` | not accepted | reason-required config changes and audit | BLOCKED |
| Users | `/system/users` | `/admin/users` | not accepted | durable auth/RBAC audit | BLOCKED |
| Logs | `/system/logs` | `/admin/logs` | read-only partial | structured log source and secret scan | BLOCKED |
| Readiness/live gate | `/system/readiness` | `/admin/readiness` | final live approval disabled | MFA/step-up/superadmin/legal/risk/live-gate evidence | BLOCKED |
| Audit/evidence/scripts/build/coverage/migrations/ai-tools | `/system/*` | `/admin/*` superadmin | hidden/protected requirement not fully proven | superadmin-only route proof | BLOCKED |

## Current safe assertion

No new live order submit/cancel/leverage/margin mutation was added in this pass. Real live trading remains blocked.

## 2026-06-15 default-deny admin control route remediation

Status: PARTIAL REMEDIATION, not launch-ready.

Changed route ownership for dangerous-control pages back to protected `/admin/*` surfaces:
- `/admin/risk-control`
- `/admin/config-admin`
- `/admin/strategy-admin`
- `/admin/execution-admin`
- `/admin/live-readiness`

Reason:
- These pages were being resolved to `/system/*` paths by `productNavigation` overrides. The `/admin/*` compatibility routes therefore did not mount the page components, and reviewers were redirected to `/` instead of seeing disabled controls.
- The V2 redesign standard requires admin/system controls to remain under `/admin/*`, backend-protected, visible as default-deny, confirmed/audited before any action, and never leaked to public/trader users.

Validation evidence:
- `npm run typecheck` passed from `v2/frontend`.
- Focused Playwright default-deny inventory passed: 5/5 pages rendered `dangerous-control-panel`, disabled dangerous buttons, and approval badges.

Remaining blockers:
- Full Chromium suite is still not green.
- Admin pages still need broader visual redesign and backend action/audit wiring validation beyond disabled UI evidence.
- Real live trading remains blocked.

## 2026-06-15 Mission Control readiness banner fetch remediation

Status: PARTIAL REMEDIATION, not launch-ready.

Changed Mission Control readiness banner behavior:
- Always performs a read-only `GET /api/v1/live-readiness/banner` when mounted.
- Removed frontend env gating that prevented the admin readiness endpoint from being called during local validation.
- Keeps safe fallback behavior: if the endpoint is unavailable, the banner remains loaded with a blocked/default payload plus an error indicator.

Validation evidence:
- `npm run typecheck` passed from `v2/frontend`.
- Focused Playwright Mission Control readiness banner suite passed: 4/4 tests.
- Verified READY, BLOCKED missing-lane, BLOCKED divergent-lane, and read-only GET-only request behavior.

Remaining blockers:
- Mission Control still needs broader visual/product cleanup beyond the readiness banner.
- Full Chromium suite and backend pytest remain launch blockers.
- Real live trading remains blocked.

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

- Data-contract primitives are EXISTS/PARTIAL, not MISSING: `ValidatedDataEnvelope`, `useRealtimeResource`, `useDataFreshness`, `DataQualityBadge`, `FreshnessBadge`, `SourceBadge`, `EvidenceDrawer`, `RealtimeStatusBar`, `ProTable`, `MetricCard`, and `KPIGrid` exist in `frontend/src`.
- Adoption is PARTIAL. Any public/trader page or visible component still importing `usePayloadFile`, `operatorTruthData`, raw `/operator_runtime/*` paths, raw payload filenames, or legacy cockpit/operator surfaces remains DATA-BLOCKED until rewired to `/api/v2/*` envelopes/realtime streams or gated behind admin incident views.
- Backend collection currently succeeds: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/pytest v2/backend/tests/ --collect-only -q` collected `4093` tests with no collection/import errors.
- Local viewing is restored with Vite on `5173`, Cloudflare serving the Vite shell, and FastAPI on `8000` using detached 4-worker Uvicorn. This is local smoke evidence only, not launch readiness.
- `/` redirects to `/landing`; `/market` redirects to `/markets`; `/dashboard` redirects to `/trade`; unauthenticated `/trade` fails closed to `/login?returnTo=%2Ftrade`.
- Full backend pytest, full Chromium, route-by-route data coverage, and screenshot matrix are still UNPROVEN in the current pass.
- Do not mark Phase 14, Phase 15, `/trade`, `/market/:symbol`, realtime data, paper/read-only launch, admin security, or real live trading as PASS from this evidence.
- Real live trading remains BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- This is targeted evidence only. Full backend pytest, full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.
- Real live trading remains BLOCKED.

