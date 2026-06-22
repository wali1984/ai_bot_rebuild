# V2 Top-10 Market + Alt-Data Dashboard Rendering

**Generated:** 2026-05-21 (UTC)
**GO_NO_GO:** `V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_RENDERING_READY`

## What this packet shipped

A read-only renderer that reads V2 Redis keys, classifies each of
the 10 dashboards into exactly one of five states, and emits a
single JSON payload the frontend renders without making any
provider network call.

### Files shipped

- [v2/backend/app/cli/v2_top10_dashboards_renderer.py](v2/backend/app/cli/v2_top10_dashboards_renderer.py)
  — renderer CLI. Reads `v2:market:*`, `v2:dashboards:*`,
  `v2:altdata:*`, `v2:market:liquidations:*`. Writes payload to:
  - `claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_rendering/latest/dashboard_payload.json`
  - `v2/frontend/public/v2_top10_dashboards/latest/dashboard_payload.json`
- [v2/backend/tests/integration/cli/test_v2_top10_dashboards_renderer.py](v2/backend/tests/integration/cli/test_v2_top10_dashboards_renderer.py)
  — **17 tests**, all pass. Cover OK_ROWS_PRESENT, KEY_PRESENT_NO_CLIENT_YET,
  KEY_MISSING, STALE, BUDGET_LIMITED, no-network-call guarantee,
  and no-raw-credential-leak.
- [v2/frontend/src/components/realtimeWebsite/index.tsx](v2/frontend/src/components/realtimeWebsite/index.tsx)
  — new `Top10Panel` component that renders a panel with explicit
  state chip + per-state explainer + columns appropriate to the
  metric.
- [v2/frontend/src/data/realtimeUserWebsitePayloads.ts](v2/frontend/src/data/realtimeUserWebsitePayloads.ts)
  — `useTop10Dashboards()` hook, typed `Top10Panel` interface.
- [v2/frontend/src/pages/market/index.tsx](v2/frontend/src/pages/market/index.tsx)
  — rewires the Top-10 grid to render the 10 panels from the
  renderer payload. The prior Binance feed status panel is kept as
  a cross-reference but no longer carries the only Binance-Top10
  data on the page.

## The 10 dashboards

| # | Panel | Data source | Current runtime state |
| --- | --- | --- | --- |
| 1 | Binance Spot 12h Volume Leaders | `v2:dashboards:binance_top10:spot_volume_12h` | reflected from Redis |
| 2 | Binance Futures 12h Volume Leaders | `v2:dashboards:binance_top10:futures_volume_12h` | reflected from Redis |
| 3 | Binance Spot 12h Most Traded | `v2:dashboards:binance_top10:spot_trades_12h` | reflected from Redis |
| 4 | Binance Futures 12h Most Traded | `v2:dashboards:binance_top10:futures_trades_12h` | reflected from Redis |
| 5 | Binance Spot 12h Volatility Leaders | `v2:dashboards:binance_top10:spot_volatility_12h` | reflected from Redis |
| 6 | Binance Futures 12h Volatility Leaders | `v2:dashboards:binance_top10:futures_volatility_12h` | reflected from Redis |
| 7 | Liquidation Tape Top Symbols | `v2:market:liquidations:heartbeat` + `v2:market:liquidations:top_symbols` | reflected from Redis |
| 8 | Funding/OI Movers | `v2:market:funding:{symbol}` + `v2:market:open_interest:{symbol}` for BTCUSDT / ETHUSDT / SOLUSDT, ranked by `abs(last_funding_rate)` | reflected from Redis |
| 9 | Nansen Smart Money Top Symbols | `v2:altdata:nansen:status` + `v2:altdata:nansen:top_symbols` | reflected from Redis |
| 10 | LunarCrush Social Momentum Top Symbols | `v2:altdata:lunarcrush:status` + `v2:altdata:lunarcrush:top_symbols` | reflected from Redis |

## Current runtime payload (snapshot)

```
panels_total=10
panels_ok_rows_present=4
panels_key_present_no_client_yet=4
panels_key_missing=2
panels_stale=0
panels_budget_limited=0
```

The frontend renders each panel's state-chip directly from the
payload, so any future change in Redis state is visible in the SPA
within the next 60-second polling tick — without any frontend
provider knowledge or network call.

## Panel state classification rules

| State | When the renderer emits it |
| --- | --- |
| `OK_ROWS_PRESENT` | Required Redis key present, payload fresh, rows extracted. |
| `KEY_PRESENT_NO_CLIENT_YET` | Status/heartbeat exists but the upstream exporter/client has not produced row data yet (e.g. liquidation daemon is alive but the per-symbol aggregator is not running). |
| `KEY_MISSING` | Required Redis key is absent entirely. |
| `STALE` | Payload exists but its `generated_utc` is older than the panel's freshness window (600 s default; 900 s for funding/OI; 1800 s for alt-data status). |
| `BUDGET_LIMITED` | Alt-data status's `source_status_counts` carries a budget / rate-limit / cooldown label; rows are intentionally absent until the next provider window. |

## Safety pins (every payload, every tick)

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `dry_run=true`
- `live_enabled=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `no_provider_network_calls_from_renderer=true`
- `no_provider_network_calls_from_frontend=true`
- `no_live_buttons=true`
- `no_order_buttons=true`
- `no_shutdown_claim=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `display_only=true`

The renderer's own test
`test_renderer_makes_no_network_call` monkeypatches
`urllib.request.urlopen` to raise; the test confirms zero calls to
the spy even with all 10 panels constructed.

## Tests

- `test_v2_top10_dashboards_renderer.py` — **17 passed**.
- Frontend `npm run typecheck` — **PASS**.
- Frontend `npm run build` — **PASS** (215 modules, 532 kB minified).
- Live-canary validation sweep (independent suite): PASS at 22
  files (the renderer is in a separate package).

## What this packet did NOT do

- Did NOT make any provider network call (Binance, Nansen,
  LunarCrush, CoinAnk, etc.) from either backend or frontend.
- Did NOT write any Redis key.
- Did NOT add any live-trading button.
- Did NOT add any order button.
- Did NOT add any shutdown control.
- Did NOT call `/fapi/v1/order` or `/fapi/v1/order/test`.
- Did NOT change leverage or margin mode.
- Did NOT enable live trading.
- Did NOT modify the legacy bot tree.
- Did NOT write any legacy Redis namespace.
- Did NOT serialize any raw credential value.
- Did NOT touch the live-canary execution adapter, permission
  probe, dry-run service, or website backend service.

## Operator next steps (optional)

1. Schedule the renderer on a systemd timer (template not shipped
   in this packet; can be installed later when the operator wants
   a sub-60-second cadence). The renderer is idempotent and
   read-only; it is safe to run as frequently as the operator
   wants.
2. Wire upstream exporters for the panels currently in
   `KEY_MISSING` / `KEY_PRESENT_NO_CLIENT_YET`:
   - Binance Top-10 exporter to populate `v2:dashboards:binance_top10:*` rows.
   - Liquidation aggregator to populate `v2:market:liquidations:top_symbols`.
   - Nansen client to populate `v2:altdata:nansen:status` + `v2:altdata:nansen:top_symbols`.
   - LunarCrush per-symbol aggregator to populate `v2:altdata:lunarcrush:top_symbols`.

   Each of these is tracked as a separate audit-tracker lane (see
   [V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md](claude_worklog/trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md)
   AUD-001 lane); the renderer's state-chip is the operator-facing
   signal that the upstream lane has not yet produced rows.

## Cross-references

- Source: [v2_top10_dashboards_renderer.py](v2/backend/app/cli/v2_top10_dashboards_renderer.py)
- Component: [Top10Panel in realtimeWebsite/index.tsx](v2/frontend/src/components/realtimeWebsite/index.tsx)
- Page wiring: [pages/market/index.tsx](v2/frontend/src/pages/market/index.tsx)
- Hook: `useTop10Dashboards` in [realtimeUserWebsitePayloads.ts](v2/frontend/src/data/realtimeUserWebsitePayloads.ts)
- Tests: [test_v2_top10_dashboards_renderer.py](v2/backend/tests/integration/cli/test_v2_top10_dashboards_renderer.py)
