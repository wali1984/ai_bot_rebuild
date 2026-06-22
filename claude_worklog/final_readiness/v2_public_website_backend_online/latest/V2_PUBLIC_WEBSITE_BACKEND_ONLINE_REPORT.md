# Lane 2 — V2 Public Website Backend Online

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_PUBLIC_WEBSITE_BACKEND_ONLINE_READY`
**Closes audit findings:** AUD-008 (backend not running) + AUD-009 (REDIS_URL unset)

## What shipped

1. **FastAPI backend now runs under systemd**
   ([ai-bot-v2-public-website-backend.service](claude_worklog/systemd/user/ai-bot-v2-public-website-backend.service))
   bound to `127.0.0.1:8000`, `Type=simple`, `Restart=on-failure`.
   `REDIS_URL` + `LEGACY_REDIS_URL` + `V2_REDIS_PREFIX=v2:` injected
   via `Environment=` in the unit file. Startup script:
   [start_v2_backend_uvicorn.sh](v2/backend/scripts/start_v2_backend_uvicorn.sh).

2. **Frontend dist built** via `npm run build` (215 modules, 530 kB
   minified JS + 68 kB CSS). Output at `v2/frontend/dist/`.

3. **SPA + public payload mirror mounted inside FastAPI**
   ([v2/backend/app/main.py](v2/backend/app/main.py) — new
   `_mount_frontend_spa()` helper). Three mounts wired:
   - `/assets/*` → SPA static assets (chunked JS + CSS).
   - `/public/*` → `v2/frontend/public/` JSON payload tree.
   - `/{full_path:path}` → SPA catch-all returns `index.html` for
     any unmatched route so React Router handles `/market`,
     `/admin/war-room`, etc. via HTML5 history mode.
   The catch-all explicitly refuses to serve the SPA for `api/*`
   and `public/*` prefixes (those 404 if the underlying file is
   missing) so API routes stay authoritative.

4. **Reverse-proxy template for `dashboard.wajidali.us`**
   ([nginx.dashboard.wajidali.us.conf.template](v2/backend/scripts/nginx.dashboard.wajidali.us.conf.template))
   — operator-applied. Includes:
   - 80→443 redirect.
   - HTTPS server block.
   - Security headers (X-Frame-Options DENY, X-Content-Type-Options
     nosniff, Referrer-Policy strict-origin-when-cross-origin,
     HSTS 2y).
   - Hard `403` refusals for `^/api/v1/live/`, intent
     create/cancel/modify shapes, and any `leverage`/`margin`
     mutation under `/api/v1/exchanges/.*/`. This is
     defense-in-depth on top of the FastAPI `live_block_guard`
     middleware.
   - DNS prerequisite documented (A record →
     operator's public IPv4). The script does NOT auto-install
     nginx, does NOT obtain a TLS cert, does NOT touch system
     services.

## Runtime proof

After backend restart with the new SPA mount, all probed routes
return HTTP 200:

| Endpoint | Status |
| --- | --- |
| `GET /` | **200** (SPA `<title>AI BOT V2 — Control Plane</title>`) |
| `GET /market` | **200** (SPA catch-all serves index.html) |
| `GET /admin/war-room` | **200** (SPA catch-all serves index.html) |
| `GET /api/v1/_meta/agent-health` | **200** (JSON) |
| `GET /api/v1/_meta/queue-status` | **200** (JSON) |
| `GET /assets/index-bQWIz72d.js` | **200** (minified SPA bundle) |
| `GET /public/v2_live_canary_dry_run_service/latest/operator_dashboard_payload.json` | **200** (JSON payload mirror) |

Total: 7/7 reachable. FastAPI app route count: **49**.

## Safety invariants (unchanged)

- Backend binds `127.0.0.1:8000` only — no external port opened by
  this packet.
- `LIVE_GATE=blocked_human_only` injected via systemd Environment.
- `live_block_guard` middleware in the FastAPI app rejects every
  live-trading endpoint at request time.
- nginx template adds defense-in-depth hard refusals for live /
  intent-mutation / leverage / margin paths.
- No order button is in the SPA. No live-enablement endpoint is
  reachable. No raw credential is ever serialized into the payload
  surface; `raw_credential_in_payload="NEVER"` is pinned in every
  dashboard payload the SPA renders.
- Frontend dist is a static build — there is no client-side code
  path that can place an order. The SPA only renders the JSON
  payloads served by the backend's read-only routes.

## What this packet did NOT do

- Did NOT install nginx or obtain a TLS certificate (template only;
  operator applies).
- Did NOT modify `/etc/hosts` or any DNS configuration.
- Did NOT open any external port. Backend stays on `127.0.0.1`.
- Did NOT enable live trading.
- Did NOT add any control button to the SPA.
- Did NOT modify the legacy bot tree.
- Did NOT write to legacy Redis keys.
- Did NOT call any exchange endpoint.
- Did NOT install missing pip packages (those remain tracked as
  AUD-014 through AUD-019).

## Operator next steps (out of scope for this packet)

1. Install nginx + certbot, copy the template into
   `/etc/nginx/sites-available/`, symlink to
   `sites-enabled/`, run `nginx -t && systemctl reload nginx`,
   then `certbot --nginx -d dashboard.wajidali.us`.
2. Confirm DNS A record points to the operator's public IPv4.
3. (Optional) Switch FastAPI `--workers 1` → `--workers 4` once
   the operator runs sustained load.

## Source pointers

- [v2/backend/app/main.py](v2/backend/app/main.py) —
  `_mount_frontend_spa()` adds three read-only mounts.
- [v2/backend/scripts/start_v2_backend_uvicorn.sh](v2/backend/scripts/start_v2_backend_uvicorn.sh)
  — startup wrapper.
- [v2/backend/scripts/nginx.dashboard.wajidali.us.conf.template](v2/backend/scripts/nginx.dashboard.wajidali.us.conf.template)
  — reverse-proxy template.
- [claude_worklog/systemd/user/ai-bot-v2-public-website-backend.service](claude_worklog/systemd/user/ai-bot-v2-public-website-backend.service)
  — systemd unit (active + enabled).
