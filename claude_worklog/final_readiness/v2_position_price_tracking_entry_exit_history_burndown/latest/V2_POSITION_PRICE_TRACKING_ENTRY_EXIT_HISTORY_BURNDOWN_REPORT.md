# V2 Position Price Tracking Entry/Exit History Burndown Report

Generated: `2026-05-18T20:49:06Z`

GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`

Continues V2 full-observation migration by recovering entry-price and realized-exit evidence from V2-owned paper inputs only. Does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.

## Per-Symbol Burndown

| Symbol | State | Entry Source | Realized Exit Source | Realized Exit Price | MFE bps | MAE bps | ROE bps | Blockers |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| BTCUSDT | FLAT | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | None | ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS,REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS |
| ETHUSDT | FLAT | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | None | ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS,REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS |
| SOLUSDT | FLAT | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | None | ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS,REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS |

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`
- `no_fake_price_tracks`: `true`
- `no_silent_zero_fill`: `true`

## Final Decision

`V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`
