# Paper / Shadow Results Report

Generated: 2026-05-13T04:43:38.228869Z

Current paper runtime source: `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`

- Runtime state: `PAPER_RUNTIME_ONLINE_ACTIVE`
- Runtime age from payload: `0` seconds
- Runtime age from wall clock: `28` seconds
- Latest prediction_id: `pred_paper_tick_1778647390310`
- Latest feature_snapshot_id: `fs_paper_tick_1778647390310`
- Latest signal_id: `sig_paper_tick_1778647390310`
- Latest orchestrator_decision_id: `orch_paper_tick_1778647390310`
- Latest risk_decision_id: `risk_paper_tick_1778647390310`
- Latest execution_intent_id: `pei_paper_tick_1778647390310`
- Paper loop event count: `2771`
- Allowed paper intents in current tail: `1`
- Blocked paper intents in current tail: `0`
- Equity: `9976.02` from starting `10000.0`
- Realized PnL: `-23.98`

Important limitation: available 1h/6h/24h counts are from current payload `audit_events` and `paper_ledger_tail`, not a full durable 24h ledger. Paper runtime is alive, but this packet does not prove profitable strategy performance.

Latest ledger event:

```json
{
  "exchange_order_id": null,
  "execution_intent_id": "pei_paper_tick_1778647390310",
  "fee_rate": 0.0004,
  "fee_usdt": 0.01,
  "fill_price": 81195.7359,
  "funding_assumption": "zero_until_funding_feed_adapter_current",
  "generated_at": "2026-05-13T04:43:10Z",
  "ledger_action": "PAPER_FILL_SIMULATED",
  "legacy_redis_write": false,
  "live_order": false,
  "notional_usdt": 25.0,
  "paper_ledger_entry_id": "pledger_paper_tick_1778647390310",
  "paper_result": "FILLED_PAPER_ONLY",
  "risk_decision_id": "risk_paper_tick_1778647390310",
  "signal_id": "sig_paper_tick_1778647390310",
  "slippage_bps": 2.0,
  "symbol": "BTCUSDT"
}
```
