# Root Route Redirect To V2 Mission Control

## Result

`/` now redirects to `/admin/mission-control?role=admin`, so the default Vite URL opens the real admin Mission Control cockpit instead of the public shell route.

## Root Cause

The React route registry mapped `/` through `public-landing/route.ts`, so opening `http://localhost:5173/` entered `PublicShell`. The Mission Control page could be rendered there, but it did not use the actual admin shell route that operators expect.

## Fix

- Added an explicit root redirect in `v2/frontend/src/router.tsx`.
- Updated `/admin` and wildcard redirects to preserve `?role=admin`.
- Moved `public-landing` from `/` to `/landing` so there is no root route collision.
- Updated `v2/frontend/README_LOCAL_UI.md`.
- Hardened `TradingViewWidget` initialization so React StrictMode does not remove the embed script container before the external TradingView script runs.

## Service Worker / Stale UI Check

The frontend already unregisters service workers in dev via `registerServiceWorker()` when `import.meta.env.DEV` is true. The local readme now documents clearing service worker/site data if a browser keeps an old shell.

Chromium smoke against the Vite dev server confirmed:

- `/` lands at `/admin/mission-control?role=admin`
- `AdminShell` is active
- `PublicShell` is not active
- `AI BOT V2 Modern Dashboard Loaded` is visible
- `LIVE TRADING: BLOCKED` remains visible
- service-worker registration count is `0`

## Safety

No legacy bot, Redis, exchange, leverage, margin, live-key, or live-trading path was touched. Live trading remains `blocked_human_only`.
