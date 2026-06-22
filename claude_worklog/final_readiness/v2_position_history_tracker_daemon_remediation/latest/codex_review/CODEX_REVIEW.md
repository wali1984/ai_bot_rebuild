# Codex Review: V2 Position-History Tracker Persistent Daemon Remediation

Generated: `2026-05-21T05:58:08Z`

GO/NO-GO: `V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`

## Decision

Codex passes the position-history tracker persistent-daemon remediation. The prior fail blocker is cleared: the systemd user service is active/running, the tracker process is present, the Redis heartbeat exists with positive fresh TTL, and per-symbol history/track keys now exist.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Prior Fail Blocker Cleared

Prior fail blocker:

`POSITION_HISTORY_HEARTBEAT_ABSENT_OR_EXPIRED`

Current evidence:

- service: `ai-bot-v2-position-history-persistent-tracker.service`
- systemd user state: `active/running`
- enabled: `enabled`
- MainPID: `2222389`
- process command: `python3 -m v2.backend.app.cli.v2_position_history_persistent_tracker --loop`
- working directory: `/home/wali/Desktop/AI BOT REBUILD`
- `PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD`
- `LIVE_GATE=blocked_human_only`
- `V2_LIVE_GATE_OVERRIDE=blocked_human_only`

Redis heartbeat:

- key: `v2:paper:position_history:heartbeat`
- exists: `1`
- sample TTL: `870` seconds
- generated: `2026-05-21T05:57:16Z`
- sample age: about `30` seconds
- `cycle_count=8`
- `process_mode=persistent_daemon`
- `service_active=true`

The heartbeat is present, fresh, and has positive TTL. The daemon uses a 60-second cycle and writes with a TTL above the cycle interval.

## Per-Symbol Runtime Payloads

Observed tracker keys:

- `v2:paper:position_history:heartbeat`
- `v2:paper:position_history:BTCUSDT`
- `v2:paper:position_history:ETHUSDT`
- `v2:paper:position_history:SOLUSDT`
- `v2:paper:position_price_track:BTCUSDT`
- `v2:paper:position_price_track:ETHUSDT`
- `v2:paper:position_price_track:SOLUSDT`

All three symbols currently report explicit no-position state:

- `position_state=NO_OPEN_POSITION` in persistent history payloads
- track state: `FLAT`
- side: `null`
- entry price: `null`
- latest price: `null`
- MFE / MAE / ROE / unrealized: `null`
- `no_fabricated_excursion_metrics=true`
- `no_synthesized_accepted_positions=true`

No open paper position is treated as a failure. It is surfaced as explicit `NO_OPEN_POSITION`.

## Intent Separation

The live heartbeat and per-symbol payloads keep accepted, held, and shadow counts separate:

- accepted: `BTCUSDT=0`, `ETHUSDT=0`, `SOLUSDT=0`
- shadow: `BTCUSDT=1`, `ETHUSDT=1`, `SOLUSDT=0`
- held: `BTCUSDT=0`, `ETHUSDT=0`, `SOLUSDT=2`
- block reasons: all `0`

Shadow and held intents are not counted as accepted. Accepted positions are not synthesized from shadow, held, blocked, or no-position evidence.

## Write Boundary

The tracker writes only through the recorder `safe_redis_set` allowlist. Allowed outputs are:

- `v2:paper:position_history:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:heartbeat`

The current tracker key set matches those outputs. Other existing `v2:paper:*` keys are V2 paper runtime inputs or unrelated V2 paper shadow state; they are not old Redis namespaces and are not part of this daemon's write output.

Codex found no old Redis write path in the reviewed daemon/service files. Source-scan hits for old Redis key names are regression tests asserting refusal of those keys.

## Full Observation Gate

Tracker payloads and status mirrors preserve:

- `full_observation_consumption_allowed=false`
- `full_observation_consumption_unblocked_after=V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS`

The full-observation builder remains partial:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target dimension: `1911`
- generated dimensions: `BTCUSDT=157`, `ETHUSDT=157`, `SOLUSDT=151`
- missing dimensions: `BTCUSDT=1754`, `ETHUSDT=1754`, `SOLUSDT=1760`
- `zero_filled_field_count=0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

The daemon has not converted missing/no-position tracker data into completion, checkpoint compatibility, or policy parity.

## Safety

Codex verified:

- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed daemon/service path;
- no old Redis namespace write in the reviewed daemon/service path;
- no old Redis key appeared in the targeted runtime scan;
- no live/canary/shutdown/Redis-trim approval drift;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `live_enabled=false`;
- `writes_exchange_orders=false`;
- `writes_legacy_redis=false`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

## Validation

- Systemd user service active/running: PASS.
- Systemd user service enabled: PASS.
- Tracker process running: PASS.
- Heartbeat exists and is fresh: PASS.
- Heartbeat TTL positive: PASS.
- Per-symbol history/track keys present: PASS.
- No-open-position status explicit: PASS.
- MFE/MAE/ROE null with no V2-owned open-position evidence: PASS.
- Shadow/held intents not counted as accepted: PASS.
- Accepted positions not synthesized: PASS.
- Focused tracker/recorder/TA tests: `55 passed`.
- `py_compile`: PASS.
- Redis write boundary scan: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Full-observation partial-status check: PASS.

## Final Decision

`V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`
