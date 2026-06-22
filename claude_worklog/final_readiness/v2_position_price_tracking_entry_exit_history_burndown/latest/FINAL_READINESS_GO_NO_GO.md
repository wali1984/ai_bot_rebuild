# V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN — Final Readiness Decision

Generated: `2026-05-18T17:41:22Z`

## Packet Decision

`V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS`

## Runtime Decision

`V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`

## Rationale

- Code path: recorder now recovers entry price from `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, and previous track; recovers realized exit from V2 paper close events; surfaces per-symbol provenance; emits exact narrow blockers when V2 evidence is absent. Covered by 19 passing recorder tests and 22 passing companion full-observation tests.
- Runtime state: V2 paper writers do not yet populate `fill_price`/`exit_price` on the rows the recorder reads, so the current per-symbol output is `[ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS, REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS]` for BTCUSDT/ETHUSDT/SOLUSDT.
- Together: partial progress on the deliverable (recorder is ready); blocked at runtime until a V2-owned writer populates fill/exit fields on existing V2 paper keys. The exact follow-on writer change is documented in the packet.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false` · `approves_canary=false` · `approves_legacy_shutdown=false` · `approves_redis_trim=false`
- `writes_legacy_redis=false` · `writes_exchange_orders=false`
- `no_fake_price_tracks=true` · `no_silent_zero_fill=true`
