# V2 Admin Realtime Layout Refresh

Generated: `2026-05-23T04:43:46Z`

GO/NO-GO: `V2_ADMIN_REALTIME_LAYOUT_REFRESH_READY`

## Decision

The admin website layout and realtime payload refresh path have been
updated. The report center now renders as a denser operational dashboard
with safety status, freshness indicators, KPI cards, chart-style meters,
work cards, stale-report cards, and a lane matrix. The admin shell/sidebar
also received visual refinements that apply across the admin pages without
changing trading behavior.

This work does not approve live trading, canary trading, exchange
mutation, leverage/margin changes, Redis trim, approval creation,
checkpoint compatibility, policy architecture parity, production
equivalence, automatic Symbol Universe adoption, or legacy shutdown.

## Realtime Fixes

Codex found two concrete realtime defects:

- the service worker was caching public JSON/report payloads even though
  the comment said only static assets were cached;
- `usePollingQuery` depended directly on inline fetcher functions, which
  could cause continuous resubscribe/refetch loops instead of stable
  interval polling.

Fixes applied:

- runtime/report payloads, `.json`, `.md`, `/latest/`, and V2 public
  payload namespaces now bypass the service-worker cache;
- public JSON fetches now use `cache: no-store`, no-cache headers, and an
  `_rt` cache-busting query parameter;
- the polling hook now stores the fetcher in a ref so inline fetchers do
  not restart the polling effect on every render.

## Files Updated

- `v2/frontend/public/service-worker.js`
- `v2/frontend/src/hooks/usePollingQuery.ts`
- `v2/frontend/src/hooks/usePayloadFile.ts`
- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts`
- `v2/frontend/src/pages/operatorTruthData.ts`
- `v2/frontend/src/pages/cockpitData.ts`
- `v2/frontend/src/pages/report-center/index.tsx`
- `v2/frontend/src/styles.css`

## Validation

- Frontend typecheck: PASS.
- Frontend production build: PASS.
- Service-worker realtime bypass check: PASS.
- Browser probe for `/admin/report-center?role=admin`: PASS.
- Sidebar/admin page smoke probe: PASS.
- Report-center controls scan: PASS, no form controls.
- Secret scan: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Report-center, self-healing controller, and pending-task watchdog timers
  remained active.

## Safety

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not stop legacy.
- Did not stop V2 runtime.
- Did not write old Redis.
- Did not call exchange mutation.
- Did not enable live.
- Did not create approvals.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.

## Final Decision

`V2_ADMIN_REALTIME_LAYOUT_REFRESH_READY`
