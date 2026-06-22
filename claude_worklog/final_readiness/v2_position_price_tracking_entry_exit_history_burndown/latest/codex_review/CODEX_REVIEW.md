# Codex Review: V2 Position Price Tracking Entry/Exit History Burndown

Generated: `2026-05-18T18:09:35Z`

GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_CODEX_PASS_PARTIAL_PROGRESS_WRITER_GAP`

## Decision

Codex passes this packet as partial progress with a writer-side gap. The recorder code is ready to consume V2-owned entry/fill and realized-exit price evidence, but the current V2 paper Redis payloads do not yet contain those fields, so runtime MFE/MAE/ROE remain blocked and explicit.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Runtime Evidence

Refreshed recorder one-shot:

- recorder GO/NO-GO: `V2_POSITION_PRICE_TRACKING_RECORDER_READY`
- burndown GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`
- `symbols_with_entry_recovered=[]`
- `symbols_with_realized_exit_recovered=[]`
- `symbols_still_blocked=["BTCUSDT", "ETHUSDT", "SOLUSDT"]`

Current per-symbol state:

| Symbol | State | Entry Source | Exit Source | MFE | MAE | ROE |
| --- | --- | --- | --- | ---: | ---: | ---: |
| `BTCUSDT` | `OPEN_MISSING_PRICE_INPUTS` | `MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS` | `NO_REALIZED_EXIT_RECORDED_YET` | `null` | `null` | `null` |
| `ETHUSDT` | `OPEN_MISSING_PRICE_INPUTS` | `MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS` | `NO_REALIZED_EXIT_RECORDED_YET` | `null` | `null` | `null` |
| `SOLUSDT` | `FLAT` | `MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS` | `NO_REALIZED_EXIT_RECORDED_YET` | `null` | `null` | `null` |

The runtime V2 paper inputs are present, but `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, and `v2:paper:intents_held_by_paper_fill_gate` currently contain no entry/fill or exit price fields. The packet honestly reports `ENTRY_PRICE_NOT_RECOVERABLE_FROM_V2_INPUTS` and `REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS`.

## Source Review

Reviewed:

- `v2/backend/app/services/rl_core/position_price_tracking_recorder.py`
- `v2/backend/app/cli/v2_position_price_tracking_recorder.py`
- `v2/backend/tests/integration/cli/test_v2_position_price_tracking_recorder.py`
- `claude_worklog/final_readiness/v2_position_price_tracking_entry_exit_history_burndown/latest/`
- `v2/frontend/public/v2_position_price_tracking_entry_exit_history_burndown/latest/operator_dashboard_payload.json`

The recorder attempts entry-price recovery only from V2-owned sources:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- prior `v2:paper:position_price_track:{symbol}` recorder output

Realized-exit recovery is also V2-only: V2 paper close events, V2 paper intents that are close events, or prior recorder carryover. No legacy Redis key or legacy filesystem current-truth source is used.

## No Fabrication

Codex verified:

- no fake `entry_price` or `realized_exit_price`;
- no fabricated `mfe_bps`, `mae_bps`, or `roe_bps`;
- missing values remain `null`;
- `no_fake_price_tracks=true`;
- `no_silent_zero_fill=true`;
- MFE/MAE/ROE are computed only when a positive V2-owned entry price and latest/exit price are present.

The position-history aggregator is wired to consume `v2:paper:position_price_track:{symbol}` and keeps missing MFE/MAE/ROE explicit when the recorder payload lacks computable values.

## Redis Boundary

The recorder writes only:

- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:{symbol}`
- `v2:paper:position_history:heartbeat`

Focused safe-set tests prove old Redis keys such as `prediction:*` and unrelated V2 namespaces are refused. The refreshed one-shot wrote only the allowlisted V2 position-history keys.

## Next Writer-Side Fix

The next required fix is not in the recorder. A V2-owned paper writer must persist fill/entry and realized-exit prices into the V2 paper keys the recorder already reads:

- add `fill_price` or `entry_price` to accepted/open rows in `v2:paper:positions` and/or `v2:paper:ledger.accepted`;
- add `exit_price` or `realized_exit_price` to `v2:paper:ledger.last_closed_position` or `v2:paper:ledger.closed[]` when paper positions close.

The existing recorder source tags already recognize these fields. Until that writer-side evidence exists, runtime burndown must remain blocked.

## Runtime Governor

The Codex 8h war-room review governor remains healthy:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`
- V2/remediation processes: `13/13`
- 6h soak remains passed.
- full observation remains `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- full observation dims remain `BTCUSDT=156`, `ETHUSDT=156`, `SOLUSDT=147`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

## Safety

Codex verified:

- no old Redis write path in the reviewed recorder/CLI;
- no exchange order placement/cancel/modify, leverage, or margin surface;
- no live/canary/shutdown/Redis-trim approval drift;
- no raw API key exposure in reviewed artifacts;
- no checkpoint or policy parity claim.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Validation

- Recorder one-shot refresh: PASS.
- Focused recorder tests: `19 passed`.
- Companion TA/position-history tests: `22 passed`.
- Combined focused sweep: `41 passed`.
- `py_compile`: PASS.
- JSON validation: PASS.
- Raw secret scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- `git diff --check`: PASS for reviewed artifacts.

## Final Decision

`V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_CODEX_PASS_PARTIAL_PROGRESS_WRITER_GAP`
