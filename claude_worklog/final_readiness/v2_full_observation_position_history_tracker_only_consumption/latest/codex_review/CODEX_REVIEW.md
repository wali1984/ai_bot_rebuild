# Codex Review: V2 Full-Observation Position-History Tracker-Only Consumption Remediation

Generated: `2026-05-21T19:37:32Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the tracker-only position-history consumption remediation as partial progress. The prior fail blocker is cleared: tracker-derived position-context fields no longer source accepted/held/block counts or MFE/MAE/ROE from raw `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, or `v2:paper:intents_held_by_paper_fill_gate`.

The full-observation builder remains partial. This review does not approve checkpoint compatibility, policy architecture parity, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, production equivalence, or legacy shutdown.

## Prior Fail Cleared

Prior Codex fail blocker:

`POSITION_HISTORY_CONSUMPTION_STILL_USES_RAW_V2_PAPER_INPUTS`

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_position_history_tracker_only_consumption.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_position_history_consumption.py`
- `claude_worklog/final_readiness/v2_full_observation_position_history_tracker_only_consumption/latest/position_history_tracker_only_consumption_status.json`
- refreshed full-observation worklog and public payloads

Codex verified the strict tracker-derived fields are produced by `_extract_tracker_history_fields(...)`, whose inputs are only:

- `position_history`, read from `v2:paper:position_history:{symbol}`;
- the tracker consumption gate decision, backed by `v2:paper:position_history:heartbeat`.

The tracker-derived field set is:

- `v2_position_history_present`
- `v2_hold_time_seconds_current`
- `v2_intents_accepted_count`
- `v2_intents_held_count`
- `v2_intents_blocked_count`
- `v2_mfe_bps`
- `v2_mae_bps`
- `v2_roe_bps`
- `v2_position_age_seconds`
- `v2_hold_time_proxy_seconds`

The full-observation status path still reads `v2:paper:position_price_track:{symbol}` as an allowed tracker-owned key, but the current strict tracker extractor sources these fields from the tracker history payload. It does not use raw paper rows for tracker-derived fields.

## Boundary Proofs

Codex reran the prior failing shape with no Redis write and no exchange call:

- `position_history_consumption_allowed=True`
- tracker `position_history={"position_state": "NO_OPEN_POSITION", "accepted_intent_count": 0}`
- raw `paper_ledger={"accepted": [{"symbol": "BTCUSDT"}]}`
- output `position_context.v2_intents_accepted_count=0.0`
- output source: `V2_POSITION_HISTORY_TRACKER`

The inverse proof also passed:

- tracker `accepted_intent_count=7`
- tracker `held_intent_count=3`
- tracker `block_reason_count=2`
- raw `paper_ledger={}`
- output counts: `7.0`, `3.0`, `2.0`
- output source: `V2_POSITION_HISTORY_TRACKER`

For a tracker `NO_OPEN_POSITION` payload, Codex verified:

- `v2_mfe_bps=None`
- `v2_mae_bps=None`
- `v2_roe_bps=None`
- `v2_position_age_seconds=None`
- source: `V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION`

Missing and stale heartbeat checks also block consumption:

- missing heartbeat: `BLOCKED_HEARTBEAT_MISSING`
- stale heartbeat: `BLOCKED_HEARTBEAT_STALE`

## Raw Paper Context

The remaining raw paper-context fields are deliberately separate and relabeled:

- source: `V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY`
- missing source: `MISSING_V2_RAW_PAPER_CONTEXT`

Those fields cover pre-trade/fee/churn rates and granular block-reason counts. They do not feed tracker-derived accepted/held/block counts, MFE, MAE, ROE, position age, hold-time, or position-history presence.

The retired conflated source label `V2_POSITION_HISTORY_AGGREGATOR` is absent from refreshed full-observation worklog and public payloads.

## Current Status

After refreshing `v2_full_observation_builder_status --once`, the full-observation status reports:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `position_history_consumption_allowed=true`
- `position_history_consumption_state=ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT`
- tracker heartbeat present: `true`
- tracker heartbeat fresh: `true`
- heartbeat TTL sample: `845`
- heartbeat age sample: `56`
- generated dimensions: `BTCUSDT=157`, `ETHUSDT=157`, `SOLUSDT=151`
- missing dimensions: `BTCUSDT=1754`, `ETHUSDT=1754`, `SOLUSDT=1760`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Safety

Codex verified:

- no Redis write call in the reviewed full-observation builder or aggregator path;
- no old Redis write path in the reviewed files;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed path;
- no live/canary/shutdown/Redis-trim approval drift;
- raw credential-value scan over reviewed source and payloads found `0` hits outside `.local_secrets`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for `market_price:` and `prediction:` are variable/type annotations in V2 full-observation code, not old Redis writes.

## Validation

- Prior fail-shape proof: PASS.
- Inverse tracker-count proof: PASS.
- `NO_OPEN_POSITION` non-fabrication proof: PASS.
- Missing/stale heartbeat blocking proof: PASS.
- New tracker-only regression tests plus prior gate tests: `22 passed`.
- Broader focused full-observation/position-history sweep: `110 passed`.
- `py_compile`: PASS.
- Full-observation status refresh: PASS.
- Retired source-label scan: PASS, no payload leak.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Raw credential scan: PASS, `0` hits.

## Final Decision

`V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_CODEX_PASS_PARTIAL_PROGRESS`
