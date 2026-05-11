# Local Website Sanity Check

Dev server:

- Expected cwd: `$HOME/Desktop/AI BOT REBUILD/v2/frontend`
- Expected URL: `http://localhost:5173/`
- Current root behavior: `/` redirects to `/admin/mission-control?role=admin`
- `/admin` behavior: redirects to `/admin/mission-control?role=admin`
- `/landing`: public landing retained for comparison only

Smoke evidence:

- Root route reached Mission Control.
- `AI BOT V2 Modern Dashboard Loaded` marker was visible.
- `mission-command-hero` was visible.
- global live-block banner contained blocked status.
- TradingView widget was visible.
- old SVG fallback was not visible on the healthy path.
- Operator Proof Dashboard rendered separately.

Service worker/cache:

- Dev build unregisters local service workers through `registerServiceWorker()` in development.
- If a browser still shows the old shell, hard refresh, unregister service workers for `localhost:5173`, clear site data, and restart the Vite dev server from `v2/frontend`.
