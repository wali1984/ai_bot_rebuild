# Root Route Mission Control Report

Generated at: 2026-05-11T22:49:45Z

## Result

`http://localhost:5173/` now opens the V2 enterprise Mission Control cockpit by redirecting to:

`/admin/mission-control?role=admin`

## Root Cause

The historical root route `/` was owned by the public landing route. That made the browser default URL look like the old/public website even though the real operator cockpit was already available at `/admin/mission-control?role=admin`.

## Implementation

- Root `/` redirects to `/admin/mission-control?role=admin`.
- `/admin` redirects to `/admin/mission-control?role=admin`.
- `/admin/mission-control?role=admin` remains the main cockpit.
- `/admin/operator-proof-dashboard?role=admin` remains the proof/evidence page.
- The public landing route is retained at `/landing`, not `/`.
- The admin shell honors a valid `role` query parameter before RBAC redirect checks, preventing a public-role redirect loop.
- TradingView remains the primary chart; the local SVG proof chart is fallback-only.

## Safety

No legacy bot, Redis, exchange, leverage, margin, live-key, live-trading, deployment, or external execution path was touched. Live trading remains `blocked_human_only`.
