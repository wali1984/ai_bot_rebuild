# V2 Position Price Tracking Recorder Report

Generated: `2026-05-18T20:49:06Z`

GO/NO-GO: `V2_POSITION_PRICE_TRACKING_RECORDER_READY`

Burndown GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`

This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.

## Scope

The recorder reads V2 paper positions, ledger, intents, predictions, and market prices, then writes only V2 paper position price-track/history keys.

## Per-Symbol State

| Symbol | State | Entry | EntrySrc | Latest | Exit | ExitSrc | MFE bps | MAE bps | ROE bps | Missing |
| --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| BTCUSDT | FLAT | None | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | None | None | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | FLAT_NO_OPEN_POSITION |
| ETHUSDT | FLAT | None | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | None | None | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | FLAT_NO_OPEN_POSITION |
| SOLUSDT | FLAT | None | MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS | None | None | NO_REALIZED_EXIT_RECORDED_YET | None | None | None | FLAT_NO_OPEN_POSITION |

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`
- `no_fake_price_tracks`: `true`
- `no_silent_zero_fill`: `true`

## Final Decision

`V2_POSITION_PRICE_TRACKING_RECORDER_READY`
