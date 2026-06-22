# V2 Endpoint + Script Working-Status Audit (real keys, live-probed)

Generated EST: 2026-06-01T18:40:00-0400
Generated UTC: 2026-06-01T22:40:00Z
LIVE_GATE: blocked_human_only | live_symbols: [] | read-only probes only
Order placed: NO | leverage/margin changed: NO | CoinAnk: skipped per operator

Scope: every V2 script + each configured endpoint, verified LIVE with the REAL
key from `v2/.env.local` (data-provider keys auto-bootstrapped; Binance api+secret
bound read-only for this probe). CoinAnk and intentionally-disabled endpoints
excluded per instruction.

Raw evidence: `claude_worklog/tools/v2_live_endpoint_probe.py` →
`claude_worklog/final_readiness/credential_env_local_sourcing/v2_live_endpoint_probe_status.json`
(19/21 OK). Re-run: `PYTHONPATH=$PWD ./.venv/bin/python3 claude_worklog/tools/v2_live_endpoint_probe.py`

## Live endpoint matrix (real keys)
| Provider | Endpoint | Kind | Auth | Status | Verdict |
|---|---|---|---|---|---|
| Binance | time/klines/depth/openInterest/premiumIndex/ticker24hr/openInterestHist | REST | public | 200 | ✅ working |
| Binance | /fapi/v1/apiTradingStatus | REST | **signed (api+secret)** | 200 | ✅ real key+secret valid |
| Binance | /fapi/v3/account | REST | **signed (api+secret)** | 200 | ✅ real key+secret valid |
| Binance | aggTrade | WS | public | 101 connected | ✅ working |
| Binance | !forceOrder@arr (liquidations) | WS | public | 101 connected | ✅ working |
| Binance | listenKey (open user-data stream) | REST | **signed (api-key)** | 200 | ✅ token issued |
| Binance | userDataStream | **WS** | **signed (api-key)** | 101 connected | ✅ **auth WS works** |
| KuCoin | timestamp / allTickers / futures contracts | REST | public | 200 | ✅ working |
| CoinAPI | exchangerate/BTC/USD | REST | x-api-key | 200 | ✅ real key valid |
| CoinGecko | ping | REST | x-cg-demo-api-key | 200 | ✅ key valid (no V2 client yet) |
| CoinGlass | futures/supported-coins | REST | CG-API-KEY | 200 | ✅ key valid (no V2 client yet) |
| LunarCrush | api4/public/coins/list/v1 | REST | Bearer | 402 | ⚠️ key valid, endpoint now PAID-gated |
| Nansen | smart-money/holdings | REST | apikey | 405 | ⚠️ key reaches API; client GET method stale |
| CoinAnk | — | — | — | — | ⏭️ skipped per operator |

**Binance answer to the explicit ask:** real api+secret authenticate on BOTH
REST (signed account/permission = 200) AND WebSocket (user-data stream via
listenKey = 200, WS frame 101). No order/leverage/margin call was made.

## Script inventory highlights (from full code audit)
- **Binance** (14 connected files): market-data ingestors are public/keyless
  (sufficient — Binance market data needs no key); signed scripts exist for
  account-read (`binance_readonly_probe`, `account_position_monitor`,
  `permission_probe`) and the operator-gated canary executor (order path stays
  blocked). No standing authenticated user-data-stream worker exists yet (the
  probe proves the path works; a worker can be added if live account telemetry
  is wanted).
- **KuCoin**: `v2_kucoin_ingestor_worker` is config/metadata only — public
  endpoints all reachable (200) but the worker performs **no fetch / no Redis
  write** → real fetcher not implemented.
- **CoinAPI**: key valid (200) but **no V2 ingestor CLI exists** (only a symbol
  source adapter). Needs `v2_coinapi_v1` ingestor.
- **LunarCrush / Nansen**: clients exist and send correct auth headers, but
  (a) not scheduled (no systemd timer), and (b) live API contracts are
  stale/paid: LunarCrush free path dropped (402), Nansen GET rejected (405).
- **Arkham**: presence-only placeholder (no client).
- **CoinGlass / CoinGecko / TokenMetrics**: keys present + valid, but **no V2
  client implemented**.

## Trainer (running + data availability)
- **Running**: YES. `ai-bot-v2-rl-core-inference-loop` + `ai-bot-v2-trainer-bridge`
  both `active`; `v2:trainer:heartbeat` fresh (ttl≈268s),
  `v2:trainer:status = V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`; 52
  `v2:prediction:*` keys.
- **Data available**: YES. `v2:features:latest:*:1m` = **25/25 REAL, 0 missing,
  trainer_consumable=true**; 26-dim observation tensor READY.
- **Real PPO/MASA training**: NOT active — it is an inference **wrapper**
  (`v2_paper_readonly_momentum_wrapper_v1`, `confidence_raw` null on some
  symbols). Full training is blocked by operator-gated items per CLAUDE.md
  (checkpoint weight blob, GPU training loop, gymnasium env step/reset). These
  CANNOT be enabled without an operator decision and are out of non-live scope.

## Verdict vs the ask
- "All scripts run with real API keys" → ✅ data-provider keys auto-load from
  `env.local`; Binance api+secret verified read-only.
- "All endpoints/APIs/WebSockets working (Binance real api+secret REST+WS)" →
  ✅ for Binance (REST+WS signed), KuCoin, CoinAPI, CoinGecko, CoinGlass.
- "Data available for trainer and trainer running" → ✅ trainer running + fed
  (25/25 real features); real training remains operator-gated.
- **Exceptions remaining** (not CoinAnk, not intentionally-disabled):
  1. KuCoin ingestor is a stub (no fetch) — endpoints work, worker doesn't.
  2. CoinAPI has no V2 ingestor CLI (key valid).
  3. CoinGlass / CoinGecko / TokenMetrics have no V2 client (keys valid).
  4. LunarCrush (402 paid) + Nansen (405 stale) — client/plan updates needed.
  5. LunarCrush/Nansen unscheduled (no systemd timer).
