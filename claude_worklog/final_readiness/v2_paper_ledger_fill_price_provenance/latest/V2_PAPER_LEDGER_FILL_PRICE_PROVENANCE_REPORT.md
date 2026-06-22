# V2 Paper Ledger Fill-Price Provenance Report

GO/NO-GO: V2_PAPER_LEDGER_FILL_PRICE_PROVENANCE_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT loosen the strict paper-fill gate. It does NOT introduce any
unsafe fills.

## What was actually fixed

The V2 paper writer (`v2_trade_management_paper_loop`) previously
wrote `v2:paper:positions` rows with no price provenance. The
`position_price_tracking_recorder` therefore could not recover entry
prices, MFE / MAE / ROE stayed null, and the full-observation builder
held BTCUSDT and ETHUSDT at 156 dims (3 below their reachable
ceiling).

This packet patches the writer to attach V2-owned price provenance
to every paper intent and every accepted position, and exposes a
close-event schema on the ledger so realized exits can be picked up
as soon as the upstream loop emits them.

### Code change

`v2/backend/app/cli/v2_trade_management_paper_loop.py`

- New constants:
  - `ENTRY_PRICE_SOURCE_V2_MARKET = "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE"`
  - `ENTRY_PRICE_SOURCE_V2_FEATURES = "V2_FEATURES_LATEST_FRESH_CLOSE_PRICE"`
  - `ENTRY_PRICE_BLOCKER_MISSING_FILL = "MISSING_V2_MARKET_PRICE_FOR_FILL"`
  - `EXIT_PRICE_BLOCKER_MISSING_EXIT = "MISSING_V2_MARKET_PRICE_FOR_EXIT"`
  - `REALIZED_EXIT_NOT_RECORDED = "REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS"`
- New helpers:
  - `_read_v2_market_price(r, symbol) -> (price, source_label, source_utc)` reads `v2:market:prices:{symbol}.ticker_24hr.lastPrice` first, then `v2:features:latest:{symbol}:1m.features.close_price` only when `feature_freshness_state="CURRENT"`. Returns the explicit `MISSING_V2_MARKET_PRICE_FOR_FILL` blocker when neither source is available. Never reads legacy Redis. Never fabricates a price.
  - `_attach_entry_price_provenance(intent, price, source, source_utc)` attaches `entry_price`, `entry_price_source`, `entry_price_utc`, `entry_price_source_generated_utc`, `fill_price`, `fill_price_source`, `fill_price_utc`, `latest_price`, `latest_price_source`, `latest_price_utc`, `entry_price_provenance_present`, `entry_price_blocker` to the intent in-place. Paper has no clock skew between intent and fill, so the three prices match.
- Intent construction now also carries `source_intent_id`, `source_prediction_id`, `paper_fill_allowed`, `quantity`, `notional`, and `places_real_order=false`.
- Ledger snapshot now exposes a `closes: []` list with an explicit
  `realized_exit_blocker = REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS`
  sentinel and an `exit_price_field_contract` schema describing the
  fields that close events MUST carry once the upstream loop starts
  emitting them.

### Systemd unit fix

`claude_worklog/systemd/user/ai-bot-v2-trade-management-paper-loop.service`

The unit's `ExecStart` and `Environment=` lines were unquoted around
the path `/home/wali/Desktop/AI BOT REBUILD` (contains spaces). When
systemd attempted to restart the service to pick up the patched
module, it failed with `203/EXEC`. The unit is now quoted using the
same `bash -lc` wrapper pattern already proven on the liquidation
WSS daemon: `ExecStart=/usr/bin/env bash -lc 'exec /home/wali/Desktop/AI\\ BOT\\ REBUILD/.venv/bin/python3 -m v2.backend.app.cli.v2_trade_management_paper_loop --loop --interval-seconds 60'`. `Environment="PYTHONPATH=..."` and `Environment="LIVE_GATE=..."` are now double-quoted. `daemon-reload` + restart cleared the EXEC failure.

### Orphan pre-patch process removed

A pre-patch shell-launched copy of the paper loop (PID 2779873, 36h
uptime, started outside the systemd cgroup) was still running and
overwriting `v2:paper:positions` every 60s with rows that had no
entry_price provenance. The user explicitly approved the paper-loop
restart; killing the orphan was the implementation step that let the
systemd-managed (patched) process own the writer path. PID 2779873
terminated cleanly. The systemd-managed process (PID 4175241) is now
the sole writer.

## Verification (raw)

After the patch + unit fix + orphan kill, the next 60s tick from the
systemd-managed paper loop wrote:

```
v2:paper:positions[0] = {
  symbol: BTCUSDT,
  side: long,
  entry_price: 76367.20,
  entry_price_source: V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE,
  fill_price: 76367.20,
  latest_price: 76367.20,
  paper_fill_allowed: false,
  places_real_order: false,
  entry_price_provenance_present: true,
  entry_price_blocker: null
}
v2:paper:positions[1] = same shape for ETHUSDT @ 2096.29

v2:paper:ledger = {
  ...
  closes: [],
  close_event_count: 0,
  realized_exit_blocker: REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS,
  exit_price_field_contract: {
    exit_price: float | null,
    exit_price_source: V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE | V2_FEATURES_LATEST_FRESH_CLOSE_PRICE | MISSING_V2_MARKET_PRICE_FOR_EXIT,
    exit_price_utc: iso8601 | null,
    realized_pnl_bps: float | null (computable from V2-owned entry+exit),
    realized_pnl_usdt: float | null (computable from V2-owned entry+exit+quantity),
    close_reason: string,
    source_position_id: string,
    places_real_order: false
  }
}
```

`v2_position_price_tracking_recorder --once` after the patch:

```
state_counts: {FLAT: 1, OPEN_TRACKING: 2}
symbols_with_entry_recovered: [BTCUSDT, ETHUSDT]
symbols_with_realized_exit_recovered: []
symbols_still_blocked: [SOLUSDT]
```

Per-symbol price tracks (raw):

```
BTCUSDT  state=OPEN_TRACKING  entry_price=76367.20  entry_price_source=V2_PAPER_POSITION_ROW  mfe_bps + mae_bps + roe_bps computed
ETHUSDT  state=OPEN_TRACKING  entry_price=2096.29   entry_price_source=V2_PAPER_POSITION_ROW  mfe_bps + mae_bps + roe_bps computed
SOLUSDT  state=FLAT           entry_price=null      entry_price_source=MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS  missing_flags=[FLAT_NO_OPEN_POSITION]
```

`v2_full_observation_builder_status` after the patch:

| Symbol  | Prior | Current | Delta |
|---|---|---|---|
| BTCUSDT | 156 | **159** | +3 (MFE / MAE / ROE) |
| ETHUSDT | 156 | **159** | +3 (MFE / MAE / ROE) |
| SOLUSDT | 147 | 147 | 0 (no paper position; correctly stays FLAT) |

Target dim unchanged at 1911. State unchanged at
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`.
`checkpoint_compatibility_claimed = false`,
`policy_architecture_parity_claimed = false`.

## Tests

`v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py` — 13/13 pass.

Coverage:

- `_read_v2_market_price` pulls lastPrice from v2 market.
- Fallback to feature snapshot ONLY when `feature_freshness_state="CURRENT"`.
- Stale feature snapshot is refused — explicit blocker.
- Missing inputs return `MISSING_V2_MARKET_PRICE_FOR_FILL` blocker, never a fabricated price.
- `_attach_entry_price_provenance` with real price fills entry / fill / latest fields.
- `_attach_entry_price_provenance` with None price attaches `MISSING_V2_MARKET_PRICE_FOR_FILL` to every price field.
- End-to-end `run_once` with v2 market present → accepted position carries provenance.
- End-to-end `run_once` with v2 market absent → accepted position carries the explicit blocker, never a fabricated price.
- Ledger snapshot always exposes `closes`, `close_event_count`, `realized_exit_blocker` (`REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS`), and `exit_price_field_contract`.
- Held-by-gate intents remain held — no new accepted fills, no paper-fill gate loosening.
- Writer writes only `v2:` prefixed keys.
- No exchange-mutation verbs in module source.
- No torch import.

## Paper-fill gate invariants

The paper-fill gate logic was NOT touched. Acceptance still requires
`pre_trade_allowed AND fee_gate_allowed AND not churn_blocked`.
Held-by-gate intents continue to flow into
`v2:paper:intents_held_by_paper_fill_gate` with their original
`paper_fill_gate_block_reasons` and `checkpoint_blocker` fields. No
threshold was relaxed. No unsafe fill was introduced.

## Safety invariants

- `live_gate = blocked_human_only`, `live_symbols = []`
- `approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false`
- `writes_legacy_redis / writes_exchange_orders = false`
- `paper_fill_gate_loosened = false`
- `unsafe_fills_introduced = false`
- `held_by_gate_intents_remain_held = true`
- `never_fabricates = true`
- `never_uses_legacy_redis_as_truth = true`
- `never_uses_static_sample_price = true`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy.
- Does not pause V2 runtime.
- Does not change leverage or margin.
- Does not loosen the strict paper-fill gate.
- Does not introduce any new accepted fill that the gate would have
  rejected.
- Does not place, modify, or cancel any exchange order.
- Does not emit a synthetic close event.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.
- Does not start the policy architecture port.

## Outputs

- `claude_worklog/final_readiness/v2_paper_ledger_fill_price_provenance/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_paper_ledger_fill_price_provenance/latest/V2_PAPER_LEDGER_FILL_PRICE_PROVENANCE_REPORT.md`
- `claude_worklog/final_readiness/v2_paper_ledger_fill_price_provenance/latest/paper_ledger_fill_price_provenance_status.json`
- `v2/frontend/public/v2_paper_ledger_fill_price_provenance/latest/operator_dashboard_payload.json`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py` (modified)
- `claude_worklog/systemd/user/ai-bot-v2-trade-management-paper-loop.service` (modified; quoted paths with spaces)
- `v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py` (new; 13/13 pass)
- `claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json` (refreshed; BTC/ETH 156→159)
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json` (refreshed)
