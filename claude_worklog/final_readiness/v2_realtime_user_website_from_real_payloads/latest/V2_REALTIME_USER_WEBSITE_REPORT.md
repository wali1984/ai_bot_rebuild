# V2 Realtime User Website (From Real Payloads) Report

GO/NO-GO: V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT call exchange endpoints. It does NOT enable live. It does NOT
expose raw API keys. It does NOT use mock or static-fixture data as
current truth. It does NOT claim checkpoint compatibility or policy
architecture parity. It does NOT start the policy architecture port.

## Honest scope

This packet emits the **contract specification + visibility matrix**
for the V2 realtime user/admin website. Actual TSX route / page
wiring is a follow-up packet. The reason is bounded turn-by-turn
budget: shipping the full contract correctly is more valuable than
half-shipping component code that would then need rework.

Every panel in the contract binds to a real V2 payload (Redis key
or worklog/public JSON), with an explicit render rule for the
absent / stale / forbidden cases. The follow-up frontend packet must
implement readers that obey those render rules verbatim; no mock
data and no static proof fixture may stand in for current truth.

## Document artifacts

- `ROUTE_PRODUCT_MAP.md` — every user / admin route × panel × real source.
- `route_product_matrix.json` — machine-readable version of the route-product map.
- `SUBSYSTEM_VISIBILITY_MATRIX.md` — every V2 subsystem × current state × visible route × real source × missing-evidence render.
- `subsystem_visibility_matrix.json` — machine-readable version of the visibility matrix.
- `VISUAL_SYSTEM_AND_LAYOUT_REPORT.md` — dark institutional theme, layout primitives, accessibility, mobile responsiveness, per-panel anatomy.
- `CHART_AND_MARKET_WIDGET_REPORT.md` — TradingView (with labeled fallback), Binance top-10 dashboards, liquidation tape, funding/OI movers, Nansen / LunarCrush status panels, symbol-universe alt-data ranking.
- `TRAINER_AND_SIGNAL_EXPLAINABILITY_UI_REPORT.md` — trainer prediction monitor, full-observation builder progress panel, feature missing/stale flags, paper-fill gate block reasons, per-prediction explainability drawer, audit chain pointers.
- `operator_dashboard_payload.json` — public mirror summarizing this packet's scope.

## User-facing routes (5)

| Route | Purpose | Panels |
|---|---|---|
| /market | Market overview | TradingView chart + 6 Binance dashboards + funding/OI movers + liquidation tape + Nansen status + LunarCrush status + symbol-universe ranking |
| /bot-intelligence | Trainer + signal explainability | trainer feed + current predictions + full-observation progress + feature missing/stale flags + checkpoint blocker + paper-fill gate reasons |
| /paper | Paper trading | paper positions + intents + held-by-gate reasons + ledger + PnL with explicit MISSING_ENTRY_PRICE chips |
| /risk | Risk + safety | live blocker matrix + risk gate status + strict paper-fill gate + liquidation WSS health + zero-old-Redis / zero-exchange-mutation status |
| /automation | Automation status | war-room cycle timeline + governor status + legacy log observer + comparator + Codex review queue |

## Admin-only routes (6, RBAC L2+)

- `/admin/task-queue` — `claude_worklog/agent_supervisor/tasks/*.json`
- `/admin/codex-reviews` — CODEX_GO_NO_GO.md files + codex_review_queue.json
- `/admin/raw-payload-explorer` — every `v2:*` key + every public payload
- `/admin/safety-scan` — governor safety-scan outputs
- `/admin/frontend-truth-builder` — frontend-truth payloads
- `/admin/approval-status` — must show zero active live/canary/legacy-shutdown/Redis-trim approvals

## Persistent must-show on every route

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false`
- `shutdown_status = blocked`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`
- `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` (until target dim 1911 is genuinely present)
- Nansen / LunarCrush `KEY_MISSING_NO_NETWORK` or `API_FORBIDDEN_403` with per-symbol scores `null` — never fabricate a score

## Missing-evidence render contract

Every panel reader follows this rule:

1. Attempt to read the bound source payload.
2. If absent → render a `MISSING` chip with the source key name.
3. If older than the freshness window → render a `STALE` chip with the last-seen UTC + the source key name.
4. If the payload has an explicit `source_status` sentinel (e.g.
   `API_FORBIDDEN_403`, `KEY_MISSING_NO_NETWORK`,
   `MISSING_ENTRY_PRICE`, `FLAT_NO_OPEN_POSITION`,
   `MACD_ZERO_RATIO_UNDEFINED`), surface that sentinel verbatim.
5. Never zero-fill. Never fabricate.

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy. Does not pause V2 runtime.
- Does not call exchange endpoints. Does not write old Redis keys.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not create live/canary/legacy-shutdown/Redis-trim approval
  tokens.
- Does not expose raw API keys.
- Does not use mock/static data as current truth.
- Does not ship TSX route / page code changes. The follow-up
  packet implements panel readers against this contract.
- Does not start the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.

## Outputs

- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/V2_REALTIME_USER_WEBSITE_REPORT.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/ROUTE_PRODUCT_MAP.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/route_product_matrix.json
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/SUBSYSTEM_VISIBILITY_MATRIX.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/subsystem_visibility_matrix.json
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/VISUAL_SYSTEM_AND_LAYOUT_REPORT.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/CHART_AND_MARKET_WIDGET_REPORT.md
- claude_worklog/final_readiness/v2_realtime_user_website_from_real_payloads/latest/TRAINER_AND_SIGNAL_EXPLAINABILITY_UI_REPORT.md
- v2/frontend/public/operator_runtime/v2_realtime_user_website_from_real_payloads/latest/operator_dashboard_payload.json
