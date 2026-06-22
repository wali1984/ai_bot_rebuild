# Current V2 Migration Audit

GO/NO-GO: `V2_CURRENT_MIGRATION_AUDIT_BLOCKED`

Generated UTC: `2026-05-26T03:50:28Z`
Generated local: `2026-05-25 23:50:28 EDT`

## Executive Decision

The rebuild is up and acting as the primary paper/shadow runtime. It is not ready for full live trading.

Keep:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- no real exchange mutation
- no legacy Redis trim or deletion
- legacy runtime processes frozen, with legacy data preserved for parity validation

## Evidence Snapshot

| Area | Current evidence | Audit interpretation |
| --- | --- | --- |
| Legacy runtime | Safe process scan found `0` `/home/wali/Desktop/AI BOT/` bot processes. | Legacy runtime is frozen. |
| V2 services | `29` active `ai-bot-v2*` services, `0` failed, `0` activating. | V2 service runtime is up. |
| GNOME runtime | Visible runtime report shows `32` GNOME terminals: 22 service panels and 10 legacy-style monitors. | Operator visibility is in place. |
| Redis namespace | `v2:* = 265`; `orchestrator:* = 0`; `live_orders:* = 0`; `exchange:order:* = 0`; `order:* = 0`; leverage/margin patterns = `0`. | Current runtime writes are bounded to V2-only keys; no old order namespace evidence. |
| Report Center | `62` reports, `42` stale, `6` blocked, `1` operator decision required. | Reporting exists, but not all readiness lanes are fresh or green. |
| Live policy | Report Center and runtime payloads show `live_gate=blocked_human_only`, `live_symbols=[]`. | Live is intentionally blocked. |
| Exchange safety | Binance read-only probes passed; order/test-order/cancel/batch/leverage/margin/transfer/withdraw endpoints were not called. | Connectivity is read-only; mutation path remains frozen. |
| Redis deletion | No trim/flush approval found; current audit did not run destructive Redis commands. | Preserve legacy data until parity is proven. |

## What Has Been Done

| Capability | Current state |
| --- | --- |
| Legacy freeze and cutover | Complete enough for paper/shadow operation. Legacy bot processes are not active. |
| Dedicated V2 GNOME panels | Present. Panels cover Redis, market, features, TA, trainer, risk, orchestrator, paper, liquidation, report center, automation, exchange read-only, and error views. |
| Systemd runtime | Core V2 loops are active: native ingestors, native feature pipeline, feature snapshot builder, liquidation WSS, trainer bridge, RL core inference, orchestrator arbitration, paper online runtime, trade management paper loop, position history tracker, report center/public backend, comparator/guard/watchdog, Claude/Codex workers, and scheduler/orchestrator services. |
| Read-only Binance connectivity | Public and signed read-only probes are proven. Credentials and balances are redacted. |
| Exchange mutation freeze | Wrapper refuses order, test order, cancel, batch, leverage, margin, position-side, transfer, and withdraw paths. |
| Native market loop | Fresh V2 public REST loop is active for `BTCUSDT`, `ETHUSDT`, `SOLUSDT`; writes `v2:market:*`. Current count: `v2:market:* = 60`. |
| Feature pipeline | Fresh native feature loop is active for `BTCUSDT`, `ETHUSDT`, `SOLUSDT`; writes `v2:features:*`. Current count: `v2:features:* = 62`. |
| Technical analysis | TA worker/panel is fresh and `talib` import has been verified earlier. Current count: `v2:technical_analysis:* = 25`. This is not legacy TA parity. |
| Trainer / predictions | Trainer bridge and RL core inference loops are active. Current count: `v2:prediction:* = 50`. Fresh live status reports native inference for `BTCUSDT`, `ETHUSDT`, `SOLUSDT`; some predictions are blocked by expected-move-after-cost policy. |
| Orchestrator | Orchestrator arbitration loop is active. Current count: `v2:orchestrator:* = 3`; paper signals are written under V2 keys. |
| Risk / paper runtime | Paper runtime is fresh. Risk payload evaluates daily/weekly loss gates and remains non-live. Current count: `v2:risk:* = 1`, `v2:paper:* = 39`. |
| Liquidation WSS | Persistent public Binance force-order WSS daemon is active and paper/shadow only. It has `0` events received/written in the current session, so no liquidation feature parity is proven. |
| Automation | Three Claude workers, three Codex workers, Codex watchdog/takeover, parallel scheduler, worker-porting orchestrator, and agent supervisor are active. The Spark automation lane is visible in the GNOME automation monitor; no separate active service named `spark` was observed in the `ai-bot-v2*` systemd list. |
| Public/reporting surface | Report Center, public payloads, operator dashboards, and visible runtime reports exist and are being refreshed for core lanes. |

## What Is Not Yet Equivalent To Legacy

The attached legacy audit states that legacy shutdown required V2 equivalents for every legacy data namespace. That requirement is not met.

| Legacy surface | Legacy audit expectation | Current V2 gap |
| --- | --- | --- |
| OHLCV / price / orderbook | `ohlcv:list:coinapi:*`, realtime price, orderbook top/depth/bids/asks across the legacy universe and timeframes. | V2 has fresh 3-symbol public market loop and some 25-symbol contract/payload work, but always-on full legacy OHLCV/orderbook/multi-timeframe parity is not proven. |
| TA | `ta:{SYMBOL}:{TF}`: 150 keys, 160 fields each. | V2 TA count is `25`, and full legacy indicator/timeframe parity is not proven. |
| Unified features | `unified_features:{SYMBOL}:{TF}`: 250 hashes, 562 fields each. | V2 feature loop is fresh for 3 symbols. Full-observation builder remains partial with missing fields; no 562-field legacy vector parity. |
| CoinAnk | `features:coinank:*` 2,403 keys plus endpoint/global/raw/cursor namespaces. | V2 CoinAnk status is stale and source-blocked; no current full CoinAnk feature feed parity. |
| KuCoin | `kc:*` and `features:kucoin:*`. | V2 KuCoin payload is stale/config-level; no current active KuCoin parity. |
| CoinAPI WS microstructure | `microfeat:{SYMBOL}:{TF}` and normalized WS/DS features. | Not proven as a fresh active V2 source. |
| Liquidations | Legacy liquidation bridge and levels. | WSS daemon is active but current event count is `0`; `v2:market:liquidations* = 0`; per-symbol liquidation feature parity is not proven. |
| Trainer | Legacy hybrid PPO+MASA trainer, training metrics, intent, and checkpoint flow. | V2 trainer bridge/RL inference is active, but native trainer readiness and checkpoint promotion are not approved. |
| Predictions | `prediction:{SYMBOL}:{TF}` around 25 symbols x up to 6 timeframes. | V2 has `50` prediction keys and fresh 3-symbol inference; full symbol/timeframe/legacy field parity is not proven. |
| Orchestrator signals | `signals:trading:primary`, WMA streams, executed signal lineage. | V2 writes V2 paper/arbitration keys; legacy signal stream parity and production equivalence are not proven. |
| Regime/toxicity | `regime:*`, `regime_analysis:*`, `toxicity:*`. | Not fully ported/proven in current V2 runtime. |
| TokenMetrics / alt data | `tm:*` and other external intelligence. | Alt-data registry/client work is scaffolded or dry-run; provider network calls are not active; LunarCrush key absent; TokenMetrics parity is not built. |
| PnL and live position management | `pnl:decomp`, `positions:live:*`, live trade management. | Paper runtime exists, but full live position/trade-management parity is not approved or proven. |
| Execution ledger | Durable execution lineage needed before live. | Some execution-adapter/ledger readiness payloads are stale and still show blocked/fail-closed states. |

## Current Live Blockers

1. Live policy is still blocked by design: `live_gate=blocked_human_only`, `live_symbols=[]`.
2. Report Center has live/production-equivalence blockers: runtime soak/production equivalence is blocked, final production-equivalence blocker sprint is blocked, and checkpoint promotion requires operator decision.
3. Legacy data-plane parity is incomplete: CoinAnk, KuCoin, CoinAPI WS microstructure, full TA, full unified features, liquidation feature keys, regime/toxicity, TokenMetrics/alt-data, PnL, and live-position surfaces are not fully reproduced in fresh V2 runtime.
4. Trainer parity is incomplete: current V2 has bridge/inference behavior, but not approved legacy hybrid trainer equivalence, checkpoint promotion, or after-cost edge proof for live.
5. Paper/live execution proof is incomplete: current runtime is paper/shadow, and live canary one-order preflight remains blocked by missing Codex pass marker / operator approval.
6. Liquidation data is not populated: WSS is active, but no real events have been received or written, and per-symbol liquidation Redis keys are absent.
7. Several readiness lanes are stale: Report Center currently reports `42` stale reports, so a full live decision cannot rely on all lanes as fresh.
8. The exchange mutation path is intentionally frozen: this is correct safety behavior, but it means there is no enabled real-order path.
9. Legacy shutdown is not approved: the legacy audit explicitly says `approves_legacy_shutdown: false`, and the current audit agrees.

## Bottom Line

V2 has made substantial progress: the paper/shadow runtime is live, visible, guarded, writing V2-only keys, and connected to read-only Binance data. It is not a full replacement for the legacy production system yet.

Full live is blocked until V2 proves fresh production-equivalent coverage for the legacy data plane, trainer/model edge, risk/execution lineage, liquidation inputs, paper/canary performance, and final operator approvals.

Required state remains:

`V2_CURRENT_MIGRATION_AUDIT_BLOCKED`
