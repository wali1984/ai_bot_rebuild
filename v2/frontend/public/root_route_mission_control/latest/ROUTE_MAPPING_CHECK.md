# Route Mapping Check

Generated at: 2026-05-11T22:49:45Z

## Routes

- `/`: redirects to `/admin/mission-control?role=admin`
- `/admin`: redirects to `/admin/mission-control?role=admin`
- `/admin/mission-control?role=admin`: renders Mission Control in `AdminShell`
- `/admin/operator-proof-dashboard?role=admin`: renders the proof/evidence dashboard in `AdminShell`
- `/landing`: retained public shell route, not the default operator experience

## Files

- `v2/frontend/src/router.tsx`: owns root/admin/wildcard redirects.
- `v2/frontend/src/pages/mission-control/route.ts`: owns `/admin/mission-control`.
- `v2/frontend/src/pages/operator-proof-dashboard/route.ts`: owns `/admin/operator-proof-dashboard`.
- `v2/frontend/src/pages/public-landing/route.ts`: moved to `/landing`.

## Contract

The default route no longer serves the public landing as the primary operator experience.
