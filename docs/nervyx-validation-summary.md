# NERVYX Validation Summary

Generated: 2026-06-21

## Passing Checks

- `npm run typecheck` in `v2/frontend`: passed.
- `npm run brand:tokens:check` in `v2`: passed.
- `npm run build` in `v2/frontend`: passed. Vite reported only the existing chunk-size warning.
- `PYTHONPATH=v2/backend /tmp/nervyx-v2-venv/bin/python -m pytest -q v2/backend/tests/unit/api/test_brand_metadata.py`: passed, 2 tests.
- `swift test` in `v2/mobile`: passed, 6 tests. Linux package tests do not compile SwiftUI iOS screens.
- `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npm run test:e2e -- nervyx_branding.spec.ts`: passed, 3 tests.
- Active source old-brand scan across `v2/frontend/src`, `v2/mobile/Sources`, and `v2/backend/app/api/v2/brand.py`: no matches for old visible brand terms.
- Protected-lane hash comparison: clean. `docs/nervyx-protected-lanes-after.sha256` matches `docs/nervyx-protected-lanes-before.sha256` for the 341 protected source files in the baseline.
- OpenAPI compatibility: clean. `docs/nervyx-openapi-before.json` and `docs/nervyx-openapi-after.json` both contain 112 paths with no removed endpoints, no removed component fields, and no incompatible component type changes.

## Broad-Suite Blockers

- Full Chromium run command:
  `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npm run test:e2e -- --project=chromium`
  Result: failed with 74 failures, 234 passing, 33 not run. Failures were concentrated in pre-existing broad product-contract suites for paper/account endpoint source state, default-deny admin panels, market detail, mission-control readiness banner, public status, runtime-alpha visibility, trader route cleanup, and realtime signal selector panels.
- Full backend run command:
  `PYTHONPATH=v2/backend /tmp/nervyx-v2-venv/bin/python -m pytest -q v2/backend/tests`
  Result: first attempt failed at collection until `numpy` was installed in `/tmp/nervyx-v2-venv`; second attempt was interrupted after about six minutes at roughly 14% progress because it already showed many unrelated failures and was not producing a useful rebrand validation signal.

## Runtime

- Existing local app remains on `http://127.0.0.1:5173`.
- The stale duplicate uvicorn process was removed; one uvicorn process owns port `5173`.
- Live trading remains blocked; this pass did not edit protected execution, risk, strategy, trainer, PPO, MASA, Redis publishing, or database migration behavior.
