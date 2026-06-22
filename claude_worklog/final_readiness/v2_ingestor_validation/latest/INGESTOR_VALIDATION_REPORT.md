# V2 Ingestor Validation — Why CoinAnk Was 114h Old

- **Generated EST**: 2026-05-31T00:18:00-0400
- **Generated UTC**: 2026-05-31T04:18:00Z
- **Trigger**: Operator reported CoinAnk data on website showing 114h old
- **Scope**: Validate CoinAnk + every other V2 ingestor; identify why status payloads are stale

## TL;DR

The CoinAnk status payload was 114h old because **no systemd service or timer
runs the CoinAnk worker**. The `v2_coinank_and_liquidation_bridge` CLI exists
and works (verified by running it in this turn — payload age dropped from
114.17h → 0.02h), but nothing schedules it. Same problem for KuCoin,
LunarCrush, Nansen, v2-market-ingestor, v2-feature-pipeline-and-ta-worker,
v2-owned-ingestors, v2-owned-feature-pipeline, v2-feature-intelligence, and
v2-binance-usdm-adapter. Only `ai-bot-v2-native-ingestors-live-loop.service`
runs continuously and it ONLY pulls Binance public REST (prices/funding/OI).

Even when each ingestor is run manually, most of them produce no real data
because of missing API keys or unwired upstream sources — see the per-ingestor
matrix below.

## Active ingestor services (only 2)

| Service | Active | Restarts | Role | Output |
|---------|--------|----------|------|--------|
| `ai-bot-v2-native-ingestors-live-loop.service` | yes | 0 | Pulls Binance public REST | `v2:market:prices:*` (27), `v2:market:funding:*` (25), `v2:market:open_interest:*` (25) |
| `ai-bot-v2-liquidation-wss-paper-shadow.service` | yes | 1 | Binance Futures forceOrder WSS | `v2:market:liquidations:heartbeat` only |

No other ingestor has a dedicated systemd service or timer. The CLIs exist
but nothing invokes them on a schedule.

## Per-ingestor matrix (after fresh manual run)

| Ingestor | Payload before | Payload after refresh | Has API key? | Network call OK? | Redis output | Health |
|----------|----------------|------------------------|--------------|------------------|--------------|--------|
| **CoinAnk** (`v2_coinank_and_liquidation_bridge`) | 114.17h stale | 0.02h FRESH | not_attempted | `endpoint_freshness_ms.global_aggregator = ts; others = 0` → all zero | `v2:coinank:* = 0`, `v2:raw:coinank:* = 0` | **BROKEN** — global aggregate returns all 0.0; missing_api_blockers reports v2_unified_features_empty, v2_liquidation_event_source_empty, binance_force_order_ws_owner_unbound |
| **KuCoin** (`v2_kucoin_ingestor_worker`) | 341.77h stale | 0.02h FRESH | n/a (contract-only worker) | not_attempted | `v2:market:kucoin:* = 0`, `v2:altdata:kucoin:* = 0` | **DESCRIPTIVE-ONLY** — payload emits contract/scope metadata; does not actually pull KuCoin data |
| **LunarCrush** (`v2_lunarcrush_altdata_ingestor`) | 224.47h stale | 0.01h FRESH | **NO** — `key_present: false` | not_attempted | `v2:altdata:lunarcrush:* = 1` (status only) | **BLOCKED_NO_KEY** — `source_status_counts: {KEY_MISSING_NO_NETWORK: 27}`; 0/27 symbols scored |
| **Nansen** (`v2_nansen_altdata_ingestor`) | 227.64h stale | 0.01h FRESH | **YES** — `key_present: true` | YES — `network_call_attempted: true` | `v2:altdata:nansen:* = 28` (per-symbol status entries) | **AUTH_FAIL** — `source_status_counts: {API_FORBIDDEN_403: 27}`; 0/27 symbols scored (key likely invalid / wrong tier) |
| **v2_market_ingestor** | 389.52h stale | 0.01h FRESH | n/a (public) | yes | shares `v2:market:prices/funding/open_interest/*` namespace with native loop | **OVERLAPS_WITH_NATIVE_LOOP** — duplicate role; native loop already covers this |
| **v2_native_ingestors** (live loop) | 0.03h FRESH | 0.01h FRESH | n/a (public) | yes | `v2:market:prices:* = 27`, `v2:market:funding:* = 25`, `v2:market:open_interest:* = 25` | **HEALTHY** — the only ingestor producing real data continuously |
| **v2_liquidation_ingestor** (`v2_liquidation_ingestor_loop`) | refreshed earlier today | 0.07h FRESH | n/a | n/a (status-only) | `v2:market:liquidations:heartbeat` | **HEALTHY-AS-STATUS-ONLY** — per-symbol liquidation source classified `V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_OPERATOR_DECISION` |
| **v2_feature_pipeline_native** | refreshed earlier today | 0.07h FRESH | n/a | n/a | `v2:unified_features:* = 170` | **HEALTHY** — consumes Binance v2:market:* and writes unified-features |
| **v2_top10_binance_dashboard_feed** | 0.35h FRESH | 0.40h FRESH | n/a (public) | yes | dashboard feed payload only | **HEALTHY** |
| **v2_owned_ingestors** | 362.46h stale | **STILL 362h** | not run | n/a | n/a | UNREFRESHED — no CLI runner identified |
| **v2_owned_feature_pipeline** | 362.46h stale | **STILL 362h** | not run | n/a | n/a | UNREFRESHED |
| **v2_feature_intelligence** | 365.47h stale | **STILL 365h** | not run | n/a | n/a | UNREFRESHED |
| **v2_binance_usdm_adapter** | 402.87h stale | **STILL 402h** | n/a | n/a | n/a | UNREFRESHED |
| **v2_feature_pipeline_and_ta_worker** | 114.23h stale | **STILL 114h** | n/a | n/a | replaced by `v2_feature_pipeline_native` | OBSOLETE — superseded by native pipeline |

## Why CoinAnk specifically showed 114h

1. The `v2_coinank_and_liquidation_bridge` CLI writes
   `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`.
2. The CLI was last invoked manually on 2026-05-26 10:02:55Z, which is
   114h ago.
3. There is **no systemd service** named `ai-bot-v2-coinank*`. There is
   no systemd timer that fires it on a schedule.
4. None of the active services (native-ingestors-live-loop,
   liquidation-wss-paper-shadow, public-website-backend, etc.) re-run
   the CoinAnk CLI as a sub-step.
5. Therefore the payload sat untouched for 114h until I ran the CLI
   in this turn, and now reports `generated_at: 2026-05-31T04:14:44Z`
   (fresh).

Even now (post-refresh) the CoinAnk payload reports a working CLI but
**all aggregate values are 0.0** because:

- `funding_freshness = -1` / `oi_freshness = -1` / `long_short_freshness = -1`
- `total_oi = 0`, `funding_rate_avg = 0`, `long_short_ratio = 0`,
  `n_symbols_observed = 0`
- `missing_api_blockers`:
  1. `v2_unified_features_empty` — "V2 worker does not read legacy Redis"
  2. `v2_liquidation_event_source_empty` — "no coinank liquidation_orders source available this cycle"
  3. `binance_force_order_ws_owner_unbound` — "WS owner = separate_v2_ws_worker"

So even when the CoinAnk worker runs, it has no inputs because:
- It expects `v2:unified_features:*` to already be populated (chicken-and-egg
  with the levels engine that depends on it).
- It expects a CoinAnk REST source key that isn't being populated.
- It expects Binance force-order events that the WSS worker writes to a
  different namespace.

## Why the website rendered "114h"

The frontend reads
`v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`
and computes the age from `generated_at` or file mtime. Both pointed to
~114h ago. After this turn's manual refresh, the website will show ~0h
when its next poll fires — but the underlying data values are still all
zero, so a re-stale clock will resume in 0h (file mtime) plus the dashboard
display logic.

## Apparent root cause shared across all stale ingestors

**Missing scheduler / supervisor**: the V2 ingestor CLI scripts are
designed as one-shot or `--loop` workers, but only `native_ingestors`
was wired into a systemd unit. The other workers exist as code but were
never enabled. The historical pattern of stale ages (114h / 224h / 227h
/ 341h / 365h / 389h / 402h) matches one-off manual invocations during
prior milestones, not a scheduled refresh cadence.

## Remediation options (paper-only, no operator gate)

| Option | Description | Owner | Operator gate? |
|--------|-------------|-------|----------------|
| **A1 add coinank systemd timer** | New `ai-bot-v2-coinank.timer` firing the bridge every 5-10 minutes. Mirrors `symbol-universe-diff-buffer.timer` pattern added today | claude | no |
| **A2 add kucoin systemd timer** | Same pattern for `v2_kucoin_ingestor_worker --write-evidence` | claude | no |
| **A3 add lunarcrush systemd timer** | Same; gracefully reports `KEY_MISSING_NO_NETWORK` when no key | claude | no |
| **A4 add nansen systemd timer** | Same; will surface `API_FORBIDDEN_403` regularly until key is fixed | claude | no |
| **A5 add v2_market_ingestor timer or retire it** | Overlaps with native loop; decide retire vs alternative timeframe coverage | claude | no |
| **A6 wire CoinAnk REST adapter to populate `v2:raw:coinank:liquidation_orders:global`** | Closes the bridge starvation gap (also covers task r4 from the burn-in remediation) | claude | no |
| **A7 retire `v2_feature_pipeline_and_ta_worker` payload** | Already superseded by `v2_feature_pipeline_native`; delete stale path or redirect symlink | claude | no |
| **A8 refresh `v2_owned_*` and `v2_feature_intelligence` payloads** | Identify whether their owning CLIs are still part of the V2 architecture; if not, retire | claude | no |
| **B1 operator: refresh Nansen API key** | `API_FORBIDDEN_403` indicates key invalid / wrong tier | operator | YES — credential rotation |
| **B2 operator: provision LunarCrush API key** | `key_present: false` blocks all altdata signals | operator | YES — credential provisioning |

## Hard constraints still honoured in this validation

- LIVE_GATE=blocked_human_only (held)
- live_symbols=[] (held)
- No orders / leverage / margin / old-Redis writes / legacy restart
- All ingestor invocations were `--once` or `--write-evidence` flagged
  (single-cycle, paper-only)
- No new API key surfaced into any payload (credentials never logged)
- No Nansen/LunarCrush 403 retried beyond what the CLI's natural cooldown
  permits — no provider rate-limit abuse

## Files

- This report: `claude_worklog/final_readiness/v2_ingestor_validation/latest/INGESTOR_VALIDATION_REPORT.md`
- Refreshed CoinAnk payload: `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`
- Refreshed KuCoin payload: `v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json`
- Refreshed LunarCrush payload: `v2/frontend/public/operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json`
- Refreshed Nansen payload: `v2/frontend/public/operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- Refreshed market-ingestor payload: `v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json`
