# V2 Website Loading — Diagnosis + Fix Report

GO/NO-GO: V2_WEBSITE_LOADING_DIAGNOSIS_RESOLVED

## Symptom

Operator reported the website was not loading after the recent Phase-1
contract updates. Codex Phase-1 review also flagged a route-mismatch
FAIL: declared contract routes did not match actual frontend route
files.

## Diagnosis (read-only)

1. The FastAPI public website backend
   ai-bot-v2-public-website-backend.service was active and listening
   on 127.0.0.1:8000.
2. The served HTML referenced the previous bundle hash; a fresh build
   was needed to bake in the new pages.
3. The Phase-1 page contract declared routes that the frontend route
   registry did not have (/markets, /admin/config, plus three brand-new
   pages /ai-brain, /trader, /history that had no frontend module).

The site was NOT broken; it was serving an older bundle and the
contract was ahead of the actual route registry.

## Fixes applied (this cycle)

1. Reconciled page contract routes with the actual frontend route files
   by editing v2/backend/app/services/website/page_contracts.py:
   - public-landing canonical route now /landing with alias /
     (router.tsx redirect)
   - markets canonical route now /market with alias /markets
   - config-admin canonical route now /admin/config-admin with alias
     /admin/config
2. Added three frontend page modules so the contract aliases resolve to
   real components:
   - v2/frontend/src/pages/ai-brain/{meta,rbac,route,index}.tsx
   - v2/frontend/src/pages/trader/{meta,rbac,route,index}.tsx
   - v2/frontend/src/pages/history/{meta,rbac,route,index}.tsx
3. Added alias page modules for /markets and /admin/config so the
   declared contract aliases match the registry:
   - v2/frontend/src/pages/markets/* (alias to market page)
   - v2/frontend/src/pages/config/*  (alias to config-admin page)
4. Registered all five new modules in v2/frontend/src/pages/registry.ts.
5. Extended the reconciliation test
   v2/backend/tests/unit/services/website/test_website_contracts.py so
   the contracts cannot drift from the frontend route files without a
   CI failure (test_phase_1_routes_match_actual_frontend_route_files
   plus test_route_reconciliation_status_is_clean plus
   test_route_aliases_are_registered_and_point_to_components).
6. Rebuilt the frontend (npx tsc --noEmit + npx vite build). New
   bundle hash dist/assets/index-DNV8U_1q.js.

## Validation evidence

- Frontend typecheck: PASS (no errors).
- Frontend production build: PASS (240 modules transformed,
  556 KB minified, 144 KB gzipped).
- Backend served bundle confirmed to be the new hash
  index-DNV8U_1q.js.
- HTTP probe of all 15 Phase-1 routes against
  http://127.0.0.1:8000 returned 200 for every route, including
  /, /landing, /market, /markets, /admin/mission-control,
  /admin/report-center, /admin/config-admin, /admin/config,
  /ai-brain, /trader, /history, /admin/exchange-manager,
  /admin/paper-trading, /admin/risk-control, /status.
- Public payloads continue to serve correctly. Example:
  /v2_website_rebuild_phase_1/latest/operator_dashboard_payload.json
  loaded with frontend_registered=true and missing_frontend_routes=[].
- Combined regression: pytest v2/backend/tests/unit/services/website/
  + v2/backend/tests/unit/services/report_center/
  + v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py
  -> 49 of 49 passed.

## Required visible safety text (still present in Phase-1 payloads)

- Live trading is blocked.
- Legacy shutdown is blocked.
- Recovery requires proof of edge before scaling.
- No fake readiness.
- Candidate symbols are not adopted automatically.

## What this cycle did NOT do

- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop V2 runtime, continuous remediation, Codex governors,
  the report-center indexer timer, the legacy log observer, the
  V2-vs-legacy comparator, the liquidation WSS daemon, the
  position-history persistent tracker, or the public-website
  backend service.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not create any approval marker or shutdown-acceptance file.
- Did not add any live, order, shutdown, or adopt-symbol control.
- Did not enable live or canary.
- Did not adopt any Symbol Universe candidate.
- Did not adopt any external feed.
- Did not expose any raw API key or .local_secrets content.

## Safety scoreboard

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- frontend_must_not_read_redis_directly = true
- did_not_remove_admin_report_center_route = true

## Operator next step (manual)

Hard refresh the browser (Ctrl+Shift+R) on http://127.0.0.1:8000/ so
the new bundle hash index-DNV8U_1q.js is fetched instead of any cached
copy. The site loads at:

- /                       (auto-redirects to /landing)
- /landing
- /market or /markets
- /status
- /ai-brain
- /trader
- /history
- /admin/mission-control
- /admin/report-center
- /admin/risk-control
- /admin/paper-trading
- /admin/exchange-manager
- /admin/config-admin or /admin/config
