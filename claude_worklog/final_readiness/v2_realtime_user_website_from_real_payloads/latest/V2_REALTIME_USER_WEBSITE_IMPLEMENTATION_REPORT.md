# V2 Realtime User Website Implementation Report

GO/NO-GO: V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_IMPLEMENTATION_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT enable provider one-shots under 403. It does NOT expose raw API
keys. It does NOT use mock or static-fixture data as current truth.
It does NOT claim checkpoint compatibility or policy architecture
parity. It does NOT start the policy architecture port.

## Codex fail blockers cleared

- `WEBSITE_READY_PACKET_IS_CONTRACT_ONLY_NO_FRONTEND_WIRING` — fixed.
  This packet ships real TSX routes, real typed payload-fetch hooks,
  real shared UI components, real registry entries.
- `WEBSITE_CURRENT_PUBLIC_SURFACE_NOT_PROVEN_FROM_REAL_PAYLOADS` —
  fixed. Every panel binds to one V2 public payload path (15 sources
  + auxiliary). When the payload is absent, the panel renders
  `PayloadMissingCard` with the exact path — never a mock fixture.

## Files created

### Data + components

- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts` — 22 typed
  `usePollingQuery`-shape hooks, one per source payload, with
  freshness rules. Centralised `PAYLOAD_PATHS` constant.
- `v2/frontend/src/components/realtimeWebsite/index.tsx` —
  `FreshnessBadge`, `SourceBadge`, `BlockerChip`,
  `PayloadMissingCard`, `SafetyInvariantStrip`, `MetricCard`,
  `Top10Table`, `CoverageDonut`, `PanelHeader`. Pure components, no
  new npm dependencies.

### Pages

- `v2/frontend/src/pages/market/{index.tsx, meta.ts, route.ts, rbac.ts}` — public route `/market`.
- `v2/frontend/src/pages/admin-war-room/{index.tsx, meta.ts, route.ts, rbac.ts}` — admin route `/admin/war-room` (RBAC L4 `admin`).

### Registry

- `v2/frontend/src/pages/registry.ts` — both pages imported + registered. Public/admin split flows through the existing `surface` filter.

## `/market` panels (real V2 payload bound)

| # | Panel | Source payload |
|---|---|---|
| 1 | Hero safety strip | war-room dashboard + frontend truth + full obs builder |
| 1b | Hero runtime strip | full obs builder + paper online + liquidation WSS |
| 2 | TradingView chart (BTCUSDT/ETHUSDT/SOLUSDT selector) | TradingView embed + in-house labeled fallback when embed unreachable |
| 3 | Binance Top-10 grid (6 dashboards) | `top10_binance_dashboard_feed` (window_size_actual chip on futures) |
| 4 | Futures liquidation tape | `liquidation_wss_client` (process_mode, sessions, events, last_event_utc, no_synthetic flag) |
| 5 | Funding / OI intelligence | `war_room_dashboard` (governor + runtime) |
| 6 | Nansen provider panel | `war_room_alt_provider.providers.nansen` (go_no_go, key_present, source_status_counts, rate_limit_state) |
| 7 | LunarCrush provider panel | `war_room_alt_provider.providers.lunarcrush` (same fields, Bearer scheme documented only) |
| 8 | Symbol Universe alt-data ranking | `war_room_alt_universe_gap` (paper_symbols_expanded=false, may_not_override gate, live_symbols=[]) |
| 9 | V2 trainer / paper trader / orchestrator feed | `trainer_bridge`, `trade_management_paper_live`, `orchestrator_arbitration_live` |
| 10 | Coverage donut (generated vs target dim) | `full_observation_builder` (per_symbol generated + target 1911) |

## `/admin/war-room` panels (real V2 payload bound)

| # | Panel | Source payload |
|---|---|---|
| 1 | War-room cycle table | war-room dashboard + actions_applied |
| 2 | Model signal gap matrix | war-room gap matrix (aggregated counts + per-symbol classifications) |
| 3 | Raw blocker matrix | full obs + war-room dashboard (live/shutdown blocked, checkpoint/policy false) |
| 4 | Legacy log observer | `legacy_log_intelligence` |
| 5 | Codex review queue | `war_room_codex_queue` (pending + pre_existing_not_eligible) |
| 6 | Safety scan | war-room dashboard (writes_legacy_redis=false, writes_exchange_orders=false, approvals all false) |
| 7 | Raw payload explorer | every source path the page reads, with status + last `generated_utc`; never raw secret values |

## Missing-evidence render contract (verbatim)

Every panel reader follows:

1. Attempt to read the bound source payload (HTTP GET with `cache: 'no-store'`).
2. If absent or HTTP error → render `PayloadMissingCard` with the path + error message.
3. If older than the freshness window → `FreshnessBadge` flips to `STALE` with last-seen age.
4. If the payload has an explicit source-status sentinel
   (`API_FORBIDDEN_403`, `KEY_MISSING_NO_NETWORK`,
   `MISSING_ENTRY_PRICE`, `FLAT_NO_OPEN_POSITION`,
   `MACD_ZERO_RATIO_UNDEFINED`, etc.), surface that sentinel
   verbatim via `BlockerChip`.
5. Never zero-fill. Never fabricate. Never substitute mock data.

## Persistent must-show

- `live_gate = blocked_human_only` — sticky bad chip in `SafetyInvariantStrip`.
- `live_symbols = []` — ok chip when empty.
- `Shutdown = blocked` — bad chip.
- `checkpoint_compatibility_claimed = false` — ok chip.
- `policy_architecture_parity_claimed = false` — ok chip.
- `approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false` — single "all false" ok chip.

When any underlying payload's invariant flips, the chip flips
correspondingly. There is no UI mechanism on either page to set any
of these to true. There is no order entry button, no live trading
button, no shutdown-ready button, no fake "all migrated" claim.

## Build + scans (raw)

```
npm --prefix v2/frontend run typecheck    → exit 0 (no errors)
npm --prefix v2/frontend run build        → vite build OK
  • 210 modules transformed
  • dist/index.html 0.54 kB
  • dist/assets/index-*.css 40.33 kB
  • dist/assets/index-*.js 476.98 kB
```

```
Raw secret pattern scan over new files                → 0 hits
Approval-token-true scan over new files               → 0 hits
Legacy-Redis-write scan over new files                → 0 hits
Exchange-mutation-verb scan over new files            → 0 hits
Mock-as-current-truth scan (STATIC_PROOF_FIXTURE,
  "104328.41", "1.84B", literal sample fixture text)  → 0 hits
```

## Runtime continuity (raw)

After the implementation, all watched services + the war-room timer
remain `active`:

- `ai-bot-v2-liquidation-wss-paper-shadow.service` active
- `ai-bot-v2-continuous-legacy-log-remediation.service` active
- `ai-bot-v2-legacy-log-intelligence-observer.service` active
- `ai-bot-v2-paper-online-runtime.service` active
- `ai-bot-v2-paper-shadow-observation.service` active
- `ai-bot-v2-feature-snapshot-builder.service` active
- `ai-bot-v2-symbol-universe-publisher.service` active
- `ai-bot-v2-8h-war-room.timer` active

Heartbeats:
- `v2:market:liquidations:heartbeat` TTL=155 (positive)
- `v2:war_room:heartbeat` TTL=581 (positive)

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy. Does not pause V2 runtime.
- Does not call exchange endpoints. Does not write old Redis keys.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not create approval tokens.
- Does not expose raw API keys.
- Does not use mock/static fixture data as current truth.
- Does not start the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.
- Does not add a "shutdown ready" button anywhere.
- Does not add an order-entry surface anywhere.

## Outputs

- `claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/V2_REALTIME_USER_WEBSITE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/website_payload_source_matrix.json`
- `claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/website_route_implementation_matrix.json`
- `v2/frontend/public/v2_realtime_user_website_from_real_payloads/latest/operator_dashboard_payload.json`
- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts` (new)
- `v2/frontend/src/components/realtimeWebsite/index.tsx` (new)
- `v2/frontend/src/pages/market/*` (new)
- `v2/frontend/src/pages/admin-war-room/*` (new)
- `v2/frontend/src/pages/registry.ts` (modified)
