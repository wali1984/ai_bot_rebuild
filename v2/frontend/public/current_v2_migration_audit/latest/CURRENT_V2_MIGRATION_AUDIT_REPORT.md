# Current V2 Migration Audit

GO/NO-GO: `V2_CURRENT_MIGRATION_AUDIT_BLOCKED`

Generated UTC: `2026-05-26T03:50:28Z`
Generated local: `2026-05-25 23:50:28 EDT`

V2 is running as the primary paper/shadow runtime, but it is not ready for full live trading.

Keep `live_gate=blocked_human_only`, `live_symbols=[]`, no real exchange mutation, no legacy Redis trim, and no legacy data deletion.

## Current Evidence

| Area | Evidence |
| --- | --- |
| Legacy runtime | `0` legacy bot processes under `/home/wali/Desktop/AI BOT/`. |
| V2 runtime | `29` active `ai-bot-v2*` services, `0` failed, `0` activating. |
| GNOME panels | Visible runtime report shows `32` terminals. |
| Redis | `v2:* = 265`; old order/risk patterns checked here are `0`. |
| Report Center | `62` reports, `42` stale, `6` blocked, `1` operator decision required. |
| Exchange | Binance read-only probes are proven; mutation endpoints remain uncalled/frozen. |

## Done

- Legacy process freeze and paper/shadow cutover.
- V2 visible GNOME runtime panels.
- Read-only Binance connectivity and credential/balance redaction.
- Exchange mutation freeze wrapper.
- V2-only Redis write boundary.
- Active/fresh market, feature, TA, trainer bridge, RL core, orchestrator, risk, paper, liquidation WSS, and automation lanes.

## Remaining

- Full legacy OHLCV/price/orderbook parity.
- Full TA parity: legacy had 150 `ta:{SYMBOL}:{TF}` hashes with 160 fields each.
- Full 562-field `unified_features:{SYMBOL}:{TF}` parity.
- CoinAnk, KuCoin, CoinAPI WS microstructure, TokenMetrics/alt-data, regime/toxicity, liquidation feature, PnL, and live-position parity.
- Legacy hybrid trainer/checkpoint parity and after-cost paper edge proof.
- Production-equivalence soak, durable risk/execution lineage, and operator checkpoint/canary/live approvals.

## Blockers

- `live_gate=blocked_human_only` and `live_symbols=[]`.
- Production equivalence/runtime soak remains blocked.
- Checkpoint promotion requires operator decision.
- Live canary one-order preflight remains blocked.
- Liquidation WSS is active but has `0` current events and no populated liquidation feature keys.
- Report Center has `42` stale lanes.
- Exchange mutation path is intentionally frozen.

Final status: `V2_CURRENT_MIGRATION_AUDIT_BLOCKED`.
