# Full Non-Trader Production Runtime Status - 2026-06-03

Generated UTC: 2026-06-03T23:50:29Z

## Verdict

GO for non-trader production real-time signal pipeline. NO-GO for live trader/exchange mutation.

`live` here means real-time public/external market data feeding production signal and controller loops. It does **not** mean order placement.

## End-to-End Chain

1. Ingestors: active for Binance/native public data, legacy KuCoin, KuCoin REST, CoinAPI WSS, CoinAPI REST, CoinAnk, liquidation WSS/bridge/levels.
2. Feature pipeline: active; `v2:features:latest:*=38`, `v2:features:ta:*=24`.
3. Trainer: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`; predictions=27; production_signal_only=True; market_data_mode=`REALTIME_PUBLIC_MARKET_DATA`; routes_to_orchestrator=True; routes_to_risk_gateway=True; trader_execution_enabled=False.
4. Orchestrator: `V2_ORCHESTRATOR_PRODUCTION_OK`; proposals=2; winners=2.
5. Risk controller: `V2_RISK_GATEWAY_LIVE_OK`; decisions=2; latest=allow/allow_proceed_long; exchange_action_taken=False; places_real_order=False.
6. Trader: not live-enabled. Paper trade management is active: `V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK`; signals=2; intents=2; accepted=0.

## Redis Evidence Counts

- Binance/native price/OHLCV/orderbook: prices=27, ohlcv=48, orderbook=37.
- KuCoin: legacy keys=150, features=116, REST=109.
- CoinAPI: WSS OHLCV=6, normalized=6, REST=53, REST features=25.
- CoinAnk: global=12, market=11, features=11.
- Liquidation: active services; event keys=0 (event-dependent).
- Trainer/orchestrator/risk: trainer keys=6, predictions=52, orchestrator=3, risk_gateway=3.

## Legacy Scripts

The legacy-owned script inventory remains validated: 708 scripts inventoried; Python/bash syntax/import validation passed, with only PowerShell syntax not checked because `pwsh` is unavailable. Safe runtime probes were rerun and passed 5/5 at `2026-06-03T23:47:55Z`.

Not every legacy file is supposed to be a daemon. One-shot repair, audit, migration, test, and destructive/live-trading utilities are validated but not run continuously. The continuous production-equivalent non-trader capabilities are running as managed `ai-bot-v2-*` services.

## Safety State

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `trader_execution_enabled=false`
- `exchange_mutation_performed=false`
- `old_redis_write_performed=false`
- no old live trainer/trader restart performed
