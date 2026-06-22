# Codex Review: V2 Top-10 Market And Alternative-Data Dashboard Rendering

Generated: `2026-05-21T20:04:58Z`

GO/NO-GO: `V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_RENDERING_CODEX_PASS`

## Decision

Codex passes the top-10 market and alternative-data dashboard rendering packet. The renderer produces exactly 10 display-only panels, each panel either has rows or an explicit state, and the frontend renders those states from static public payloads without provider calls or trading authority.

This review does not approve provider-client adoption, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Rendering Evidence

Reviewed:

- `v2/backend/app/cli/v2_top10_dashboards_renderer.py`
- `v2/backend/tests/integration/cli/test_v2_top10_dashboards_renderer.py`
- `v2/backend/app/services/alternative_data/top10_dashboard_contracts.py`
- `v2/backend/tests/integration/cli/test_v2_top10_market_and_altdata_dashboard_contracts.py`
- `v2/frontend/src/components/realtimeWebsite/index.tsx`
- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts`
- `v2/frontend/src/pages/market/index.tsx`
- `claude_worklog/final_readiness/v2_top10_market_and_altdata_dashboard_rendering/latest/dashboard_payload.json`
- `v2/frontend/public/v2_top10_dashboards/latest/dashboard_payload.json`
- `v2/frontend/public/v2_top10_market_and_altdata_dashboard_rendering/latest/operator_dashboard_payload.json`

The prior dashboard contract review exists and is PASS:

`V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_CODEX_PASS`

## Panel Set

The renderer emits exactly 10 panels:

1. Binance Spot 12h Volume Leaders - `KEY_PRESENT_NO_CLIENT_YET`
2. Binance Futures 12h Volume Leaders - `OK_ROWS_PRESENT`, 10 rows
3. Binance Spot 12h Most Traded - `KEY_PRESENT_NO_CLIENT_YET`
4. Binance Futures 12h Most Traded - `OK_ROWS_PRESENT`, 10 rows
5. Binance Spot 12h Volatility Leaders - `KEY_PRESENT_NO_CLIENT_YET`
6. Binance Futures 12h Volatility Leaders - `OK_ROWS_PRESENT`, 10 rows
7. Liquidation Tape Top Symbols - `KEY_PRESENT_NO_CLIENT_YET`
8. Funding / OI Movers - `OK_ROWS_PRESENT`, 3 rows
9. Nansen Smart Money Top Symbols - `KEY_MISSING`
10. LunarCrush Social Momentum Top Symbols - `KEY_MISSING`

Current counts:

- `panels_total=10`
- `panels_ok_rows_present=4`
- `panels_key_present_no_client_yet=4`
- `panels_key_missing=2`
- `panels_stale=0`
- `panels_budget_limited=0`

No panel fabricates rows. Empty panels show state labels and `rank_count=0`.

## Frontend Rendering

The market page reads only:

`/v2_top10_dashboards/latest/dashboard_payload.json`

The `Top10Panel` component renders:

- `state` chips for `OK_ROWS_PRESENT`, `KEY_PRESENT_NO_CLIENT_YET`, `KEY_MISSING`, `STALE`, and `BUDGET_LIMITED`;
- state explanations for missing, stale, and budget-limited conditions;
- `missing_symbols` when present;
- `source_status_counts` when present;
- table rows only when the payload contains rows.

The frontend does not contain Nansen/LunarCrush provider URLs and does not call provider APIs. Its only fetch path is the static public JSON hook.

## Safety

Current payload safety pins:

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
- `no_provider_network_calls_from_frontend=true`
- `no_provider_network_calls_from_renderer=true`
- `no_live_buttons=true`
- `no_order_buttons=true`
- `no_shutdown_claim=true`
- `display_only=true`

Codex verified:

- no raw credential-value hits in reviewed source, worklog/public payloads, or current relevant Redis values;
- no Redis write call in the renderer;
- no old Redis write path in the reviewed renderer/frontend path;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path in the reviewed renderer/frontend path;
- no live/canary/shutdown/Redis-trim approval drift.

Source-scan hits for provider names are panel labels and local public JSON hook wiring, not provider network calls.

## Validation

- Renderer CLI refresh: PASS.
- Focused renderer tests: `17 passed`.
- Dashboard contract tests: `7 passed`.
- Combined top-10 focused tests: `24 passed`.
- Frontend typecheck: PASS.
- `py_compile`: PASS.
- Exact panel count and state inspection: PASS.
- Raw credential scan: PASS, `0` file hits and `0` Redis hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_RENDERING_CODEX_PASS`
