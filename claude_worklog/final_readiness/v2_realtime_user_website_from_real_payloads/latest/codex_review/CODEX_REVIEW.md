# Codex Review: V2 Realtime User Website From Real Payloads

Generated: `2026-06-21T22:03:45Z`

GO/NO-GO: `V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_CODEX_FAIL`

## Decision

Codex fails the realtime user website packet as an implementation-ready claim. The route/product contract is useful, but the reviewed evidence does not yet prove the public website is wired safely to real current V2 payloads.

This review does not approve live trading, canary trading, exchange mutation, Redis trim, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Findings

- `WEBSITE_PUBLIC_MARKET_ROUTE_NOT_REGISTERED`
- `WEBSITE_MARKET_ROUTE_NOT_PUBLIC`
- `WEBSITE_TYPED_PAYLOAD_FETCH_HOOKS_MISSING`
- `WEBSITE_PAYLOAD_MISSING_COMPONENT_MISSING`
- `WEBSITE_PAGES_DO_NOT_RENDER_PAYLOAD_MISSING`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_LIVE_BLOCK`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_SHUTDOWN_BLOCK`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_FULL_OBSERVATION_PARTIAL`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_CHECKPOINT_POLICY_FALSE`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_PROVIDER_STATUS`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_LIQUIDATION_WSS_HEALTH`
- `WEBSITE_MARKET_DOES_NOT_SURFACE_BINANCE_DASHBOARDS`

## Website Packet

- frontend code changes in packet: `True`
- scope: `None`
- implementation matrix present: `True`
- source matrix present: `True`
- routes: `[{'path': '/market', 'surface': 'public', 'registered': True}, {'path': '/admin/war-room', 'surface': 'admin', 'registered': True}]`
- build: `{'typecheck_passed': True, 'vite_build_passed': True, 'modules_transformed': 210, 'css_size_bytes': 41298, 'js_size_bytes': 488417}`
- live_gate: `blocked_human_only`
- live_symbols: `[]`
- approves live/canary/shutdown/redis-trim: `False` / `False` / `False` / `False`

## Evidence

- `/market` is public and has no order-entry or live-control surface.
- `/admin/war-room` is admin-gated and contains the raw payload explorer.
- Missing payloads render `PAYLOAD_MISSING` with the exact path.
- Sample files under `/home/wali/Downloads/AI BOT rebuild - web` are not imported as current truth.

## Sample Reference Risk

The sample files under `/home/wali/Downloads/AI BOT rebuild - web` contain mock/live-feeling and order-entry style UI text. They may be used only as design reference after removing or gating those surfaces; they are not accepted as current runtime truth.

## Final Decision

`V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_CODEX_FAIL`
