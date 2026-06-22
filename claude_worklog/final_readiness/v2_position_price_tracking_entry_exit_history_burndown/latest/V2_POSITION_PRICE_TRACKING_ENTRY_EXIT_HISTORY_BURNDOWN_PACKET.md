# V2_POSITION_PRICE_TRACKING_ENTRY_PRICE_AND_EXIT_HISTORY_BURNDOWN — Final Readiness Packet

Generated: `2026-05-18T17:41:22Z`

Packet GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS`

Runtime evidence GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`

This packet does NOT approve real trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.

`live_gate=blocked_human_only` · `live_symbols=[]`

## Purpose

Continue core full-observation migration while the website implementation runs. The previous TA + position-history pass confirmed MFE/MAE/ROE were uncomputable because the V2-owned price-track recorder had no way to recover an entry price when `v2:paper:positions` rows did not carry one (BTC/ETH OPEN_MISSING_PRICE_INPUTS, SOL FLAT), and had no realized-exit detection at all. This packet burns down both gaps in the V2 recorder code and exposes the exact remaining writer gap as an explicit blocker.

## Deliverable

V2-only changes to the recorder and CLI add two recovery paths and a per-symbol burndown decision, while the no-fake-prices and no-silent-zero-fill invariants stay intact.

### Code changes

- `v2/backend/app/services/rl_core/position_price_tracking_recorder.py`
  - `_extract_entry_price` now scans, in V2-only order:
    1. the `v2:paper:positions` row (`entry_price`/`entryPrice`/`fill_price`/`filled_price`/`open_price`/`fillPrice`/`filledPrice`/`avg_entry_price`)
    2. `v2:paper:ledger.last_closed_position`, then `accepted`/`held_by_paper_fill_gate`/`blocked`, then any other symbol-matched ledger entry
    3. `v2:paper:intents` and `v2:paper:intents_held_by_paper_fill_gate`
    4. the previous V2 price-track payload (recorder-carryover)
  - Returns the source provenance (`V2_PAPER_POSITION_ROW`, `V2_PAPER_LEDGER_*`, `V2_PAPER_INTENTS*`, `V2_PREVIOUS_TRACK_RECORDER_CARRYOVER`, or `MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS`) on every track so downstream consumers can quote where the price came from.
  - `_extract_realized_exit` recovers `realized_exit_price` from V2-owned close events: `paper_ledger.last_closed_position`, plus any list under `closed`/`closed_positions`/`events`/`history`/`accepted`/`blocked` whose row is a close event (`ledger_action` in `{PAPER_POSITION_CLOSED, POSITION_CLOSED, POSITION_CLOSED_PAPER_ONLY}` or `paper_result` in `{POSITION_CLOSED_PAPER_ONLY, POSITION_CLOSED}`, with an `exit_price`/`realized_exit_price`/`close_price` field > 0). Also scans `paper_intents` for close events. Persists realized exit via `previous_track` so it remains visible once the symbol returns to FLAT.
  - New `CLOSED_REALIZED` state: when the V2 paper position row is gone but a realized exit price is recoverable, the track is `CLOSED_REALIZED` and MFE/MAE/ROE are computed against the realized exit + previous-track entry/min/max without inventing prices.
  - `PositionTrack` dataclass gains `entry_price_source`, `realized_exit_source`, `realized_exit_utc`; heartbeat payload surfaces per-symbol provenance maps (`entry_price_source_by_symbol`, `realized_exit_source_by_symbol`, `realized_exit_price_by_symbol`).
  - No new Redis keys. `safe_redis_set` allowlist unchanged: only `v2:paper:position_price_track:{symbol}`, `v2:paper:position_history:{symbol}`, `v2:paper:position_history:heartbeat`.
- `v2/backend/app/cli/v2_position_price_tracking_recorder.py`
  - Emits a separate burndown decision (`V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS` vs `..._BLOCKED`) computed from per-symbol entry/exit recovery, and the lists `symbols_with_entry_recovered` / `symbols_with_realized_exit_recovered` / `symbols_still_blocked`.
  - Writes a parallel runbook artifact set under `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/` and a public dashboard payload under `v2/frontend/public/v2_position_price_tracking_entry_exit_history_burndown/latest/`.
  - Original recorder GO_NO_GO and packet locations remain unchanged.

### Test evidence

`v2/backend/tests/integration/cli/test_v2_position_price_tracking_recorder.py` — `19 passed in 0.12s` via pytest in the repo venv.

New burndown coverage:

- `test_entry_price_recovered_from_paper_ledger_accepted_fill_price` — verifies recovery from `paper_ledger.accepted[fill_price]` with source tag `V2_PAPER_LEDGER_ACCEPTED`.
- `test_entry_price_recovered_from_paper_intents_fill_price` — verifies recovery from `paper_intents[fill_price]` with source tag `V2_PAPER_INTENTS`.
- `test_entry_price_recovered_from_ledger_last_closed_position` — verifies recovery from `paper_ledger.last_closed_position` with source tag `V2_PAPER_LEDGER_LAST_CLOSED_POSITION`.
- `test_entry_price_source_marks_missing_when_no_v2_evidence_present` — verifies the exact `MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS` blocker is emitted and `missing_flags` still carries `MISSING_ENTRY_PRICE`.
- `test_realized_exit_recovered_from_paper_ledger_close_event` — verifies a closed-only symbol becomes `CLOSED_REALIZED` with exit-source `V2_PAPER_LEDGER_LAST_CLOSED_POSITION`.
- `test_realized_exit_recovered_from_close_event_with_carryover_entry` — verifies MFE/MAE/ROE are computed against the realized exit using the carried-over entry from the previous track (ROE=1000 bps on a 100→110 long close).
- `test_realized_exit_persists_via_previous_track_when_symbol_flat` — verifies realized exit survives across runs.
- `test_flat_without_any_exit_history_remains_flat` — verifies the recorder does not fabricate state when neither input exists.
- `test_cli_emits_burndown_partial_progress_when_entry_recovered` — verifies the CLI flips to PARTIAL_PROGRESS once a symbol has recovered evidence.
- `test_cli_emits_burndown_blocked_when_no_entry_or_exit_evidence` — verifies the CLI emits BLOCKED honestly when no symbol has evidence.
- `test_recorder_never_writes_unrelated_keys_even_with_close_event` — verifies only the three allowlisted V2 keys are written.
- `test_heartbeat_surfaces_per_symbol_provenance_maps` — verifies provenance maps in the heartbeat payload.

The companion suite `v2/backend/tests/integration/cli/test_v2_full_observation_ta_position_history_burndown.py` (`22 passed in 0.11s`) still passes against the upgraded recorder payload schema.

## Runtime evidence (raw)

Snapshot 2026-05-18T17:41:22Z, V2 paper Redis keyspace:

- `v2:paper:positions` carries two intent rows (BTCUSDT/ETHUSDT) with `paper_only: true`, `places_real_order: false`, `live_gate: blocked_human_only`, but no `entry_price`/`fill_price`. Sample:
  ```
  [{"intent_id":"v2_native_pred_...","symbol":"BTCUSDT","side":"long",
    "expected_move_after_cost_bps":108.57,"confidence_calibrated":0.68,
    "pre_trade_allowed":true,"fee_gate_allowed":true,"churn_blocked":false,
    "paper_only":true,"places_real_order":false,
    "generated_utc":"2026-05-18T17:40:50Z","live_symbols":[]}, ...]
  ```
- `v2:paper:ledger.accepted` mirrors the same intent rows; no `fill_price`/`exit_price` present.
- No `last_closed_position`, no `closed[]`, no `events[]` entries on either key.

Recorder per-symbol output (live):

- `BTCUSDT`: `position_state=OPEN_MISSING_PRICE_INPUTS`, `entry_price=null`, `entry_price_source=MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS`, `latest_price=76628.0`, `realized_exit_source=NO_REALIZED_EXIT_RECORDED_YET`, blockers `[ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS, REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS]`.
- `ETHUSDT`: same shape, `latest_price=2106.03`.
- `SOLUSDT`: `position_state=FLAT`, no open V2 position row and no recoverable close event.

Result: `burndown_go_no_go = V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED` at this moment, with the exact narrow blocker surfaced per symbol.

## Exact remaining blocker

The recorder is now ready to compute MFE/MAE/ROE the instant any V2-owned writer starts populating `fill_price`/`entry_price` on the rows it already writes. The remaining gap is in the writer, not the recorder:

- `v2/backend/app/cli/v2_trade_management_paper_loop.py` writes `v2:paper:positions` and `v2:paper:ledger` from intent rows that intentionally omit fill / exit fields today (paper-only ledger, no exchange touch).
- The lifecycle / fill plumbing that does produce `fill_price` and `exit_price` lives in `v2/backend/app/cli/paper_online_runtime.py` (`build_paper_ledger_entry` line 699, `build_position_lifecycle_entry` line 748, `paper_position_lifecycle_from_entry` line 880) but is currently emitted to `paper_runtime_status.json`, not to the V2 paper Redis keys this recorder reads.

The follow-on writer change (out of scope for this packet) is to have a V2-owned writer publish either:

1. `fill_price` / `entry_price` on `v2:paper:positions[*]` and `v2:paper:ledger.accepted[*]`, and `exit_price` on `v2:paper:ledger.last_closed_position` (or under `paper_ledger.closed[]`), OR
2. a separate V2-owned bridge that copies the lifecycle rows from `paper_runtime_status.json` into the existing V2 Redis keys without mutating legacy state.

Either shape is already recognized by `_extract_entry_price` / `_extract_realized_exit`; no further recorder change required.

## Hard constraints — verified

- Legacy unchanged: no edits under `legacy_reference/` or the sibling legacy bot tree.
- No legacy Redis writes: `safe_redis_set` allowlist enforced; `test_safe_redis_set_refuses_old_and_unrelated_keys` and `test_recorder_never_writes_unrelated_keys_even_with_close_event` cover it.
- No exchange mutation: recorder/CLI import no exchange SDKs; CLI prints `writes_exchange_orders=false`.
- Real trading disabled: every payload carries `live_gate=blocked_human_only`, `live_symbols=[]`, `approves_live=false`, `approves_canary=false`, `approves_legacy_shutdown=false`, `approves_redis_trim=false`.
- Inputs: only `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, `v2:paper:intents_held_by_paper_fill_gate`, `v2:market:prices:{symbol}`, `v2:prediction:{symbol}:1m`, and the recorder's own prior `v2:paper:position_price_track:{symbol}` snapshot.
- Outputs: only `v2:paper:position_price_track:{symbol}`, `v2:paper:position_history:{symbol}`, `v2:paper:position_history:heartbeat`.
- No fake price history: every recovered price names its source; missing prices emit an explicit blocker rather than a default.
- No silent zero-fill: MFE/MAE/ROE remain `null` when inputs are missing; `no_silent_zero_fill=true` and `no_fake_price_tracks=true` invariants present on every payload.

## Artifacts

- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/burndown_status.json`
- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_REPORT.md`
- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/GO_NO_GO.md` (runtime evidence decision)
- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_PACKET.md` (this packet)
- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/FINAL_READINESS_GO_NO_GO.md` (packet decision)
- `v2/frontend/public/v2_position_price_tracking_entry_exit_history_burndown/latest/operator_dashboard_payload.json`
- `claude_worklog/final_readiness/v2_position_price_tracking_recorder/latest/position_price_tracking_recorder_status.json` (recorder status, updated schema)

## Final Decision

Packet (deliverable): `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS`
Runtime (current V2 paper Redis): `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`
