# Codex Review: V2 Position-History Persistent Tracker

Generated: `2026-05-21T05:00:49Z`

GO/NO-GO: `V2_POSITION_HISTORY_TRACKER_CODEX_FAIL`

## Decision

Codex fails the position-history persistent tracker packet because the required heartbeat is absent at review time. The implementation and tests show the intended V2-only paper/shadow boundaries, but the live Redis evidence does not show a current persistent tracker heartbeat or per-symbol tracker keys.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Fail Blocker

`POSITION_HISTORY_HEARTBEAT_ABSENT_OR_EXPIRED`

Runtime Redis evidence:

- `EXISTS v2:paper:position_history:heartbeat` returned `0`
- `TTL v2:paper:position_history:heartbeat` returned `-2`
- `v2:paper:position_history*` key count: `0`
- `v2:paper:position_price_track*` key count: `0`
- no `v2_position_history_persistent_tracker` process was running

The worklog/public status mirrors exist, but they are one-shot payloads generated at `2026-05-21T04:00:00Z`, not current persistent-daemon evidence:

- `go_no_go=V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_READY`
- `process_mode=one_shot`
- `cycle_count=1`
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `full_observation_consumption_allowed=false`

The requested review explicitly required a heartbeat to exist. Codex did not run the tracker to create a fresh heartbeat during review, because doing so would mask the current runtime absence.

## Positive Findings

Codex reviewed:

- `v2/backend/app/services/rl_core/position_history_persistent_tracker.py`
- `v2/backend/app/cli/v2_position_history_persistent_tracker.py`
- `v2/backend/tests/integration/cli/test_v2_position_history_persistent_tracker.py`
- `v2/backend/app/services/rl_core/position_price_tracking_recorder.py`
- `claude_worklog/final_readiness/v2_position_history_persistent_tracker/latest/V2_POSITION_HISTORY_PERSISTENT_TRACKER_REPORT.md`
- worklog/public tracker status payloads

The implementation reads V2-owned inputs only:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:market:prices:{symbol}`
- `v2:prediction:{symbol}:1m`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`

The prediction payload is passed through the existing recorder shape path, and the recorder discards it with `del prediction`; it is not used to synthesize accepted positions.

## Write Boundary

The tracker writes only through the recorder `safe_redis_set` helper. The allowlist permits:

- `v2:paper:position_history:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:heartbeat`

Codex found no direct production `redis_client.set(...)`, `hset`, `xadd`, `lpush`, `rpush`, or `publish` write path in the new service/CLI outside that helper. Test-only `FakeRedis.set(...)` calls are fixture setup and assertions.

## Fabrication Checks

Codex verified the code and tests pin these safety properties:

- no accepted-position synthesis when `v2:paper:positions` has no symbol row;
- `position_state=NO_OPEN_POSITION` when there is no V2 paper position;
- shadow, held, and blocked rows are counted separately and not as accepted;
- MFE, MAE, and unrealized/ROE remain `null` when no open V2 paper position or price evidence exists;
- `full_observation_consumption_allowed=false` is present in per-symbol and heartbeat/status payloads;
- the CLI refuses `V2_LIVE_GATE_OVERRIDE` values other than `blocked_human_only`.

## Full Observation Status

The full-observation builder remains partial and does not consume this tracker as a completed source:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target full-observation dimension: `1911`
- generated dimensions: `BTCUSDT=157`, `ETHUSDT=157`, `SOLUSDT=151`
- missing dimensions: `BTCUSDT=1754`, `ETHUSDT=1754`, `SOLUSDT=1760`
- `zero_filled_field_count=0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Safety

Codex verified:

- no old Redis write path in the reviewed new service/CLI;
- no old Redis keys appeared in the current tracker Redis scan;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed new service/CLI;
- no live/canary/shutdown/Redis-trim approval drift;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `live_enabled=false`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for old Redis key strings were tests asserting refusal of forbidden prefixes, not executable production writes.

## Validation

- Focused persistent-tracker tests: `12 passed`.
- Existing recorder plus TA burndown tests: `43 passed`.
- `py_compile`: PASS.
- V2-only input inspection: PASS.
- V2-only write allowlist inspection: PASS.
- No accepted-position fabrication tests: PASS.
- No MFE/MAE/ROE fabrication tests: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Full-observation partial-status check: PASS.
- Runtime heartbeat existence: FAIL.

## Required Remediation

Start or schedule the tracker in a reviewed paper/shadow mode so `v2:paper:position_history:heartbeat` remains present and fresh, with a TTL longer than the cycle interval. The runtime should publish only the allowed `v2:paper:position_history:*`, `v2:paper:position_price_track:*`, and heartbeat keys, and the status mirrors should show persistent or otherwise fresh runtime evidence.

Then rerun this Codex review.

## Final Decision

`V2_POSITION_HISTORY_TRACKER_CODEX_FAIL`
