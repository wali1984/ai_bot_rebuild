# Codex Review: V2 Full-Observation Position-History Consumption After Tracker Pass

Generated: `2026-05-21T17:28:09Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_HISTORY_CONSUMPTION_CODEX_FAIL`

## Decision

Codex fails this packet. The tracker daemon PASS marker exists, the tracker heartbeat is fresh, the full-observation status remains partial with `zero_filled_field_count=0`, and the safety posture is blocked. However, the full-observation builder does not yet consume only the tracker-owned position-history and price-track keys for the tracker-derived position-context fields.

The current implementation still passes raw `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, and `v2:paper:intents_held_by_paper_fill_gate` inputs into the position-history aggregator. Codex proved that a tracker-derived output field can be sourced from raw `paper_ledger` while the tracker `position_history` payload says no accepted intents. That violates the review contract requiring consumption only from:

- `v2:paper:position_history:*`
- `v2:paper:position_price_track:*`

This review does not approve checkpoint compatibility, policy architecture parity, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, production equivalence, or legacy shutdown.

## Fail Blocker

`POSITION_HISTORY_CONSUMPTION_STILL_USES_RAW_V2_PAPER_INPUTS`

Codex verified these source reads in `v2/backend/app/services/rl_core/full_observation_builder.py`:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:{symbol}`

The builder then passes those raw paper inputs into `position_history_aggregator.aggregate_symbol(...)` for the tracker-derived position-context fields.

Proof with no Redis write and no exchange call:

- `position_history_consumption_allowed=True`
- `position_history={"position_state": "NO_OPEN_POSITION", "accepted_intent_count": 0}`
- raw `paper_ledger={"accepted": [{"symbol": "BTCUSDT"}]}`
- output `position_context.v2_intents_accepted_count=1.0`
- output source: `V2_POSITION_HISTORY_AGGREGATOR`

The inverse proof also shows the builder is not consuming the tracker history payload count:

- `position_history={"accepted_intent_count": 7, "held_intent_count": 3}`
- raw `paper_ledger={}`
- output `position_context.v2_intents_accepted_count=0.0`
- output `position_context.v2_intents_held_count=0.0`

So the advertised tracker-consumption boundary is not enforced yet.

## Positive Findings

Codex verified the tracker daemon remediation marker exists:

`V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`

Current full-observation status reports:

- `position_history_consumption_allowed=true`
- `position_history_consumption_state=ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT`
- tracker heartbeat present: `true`
- tracker heartbeat fresh: `true`
- tracker heartbeat TTL sample: `866`
- tracker heartbeat age sample: `34`
- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

The live tracker heartbeat also reports:

- `process_mode=persistent_daemon`
- `service_active=true`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `no_synthesized_accepted_positions=true`
- `no_fabricated_excursion_metrics=true`
- `no_shadow_observations_counted_as_accepted=true`
- `full_observation_consumption_allowed=false`

## NO_OPEN_POSITION And Zero Fill

The existing tests and source pin the intended behavior:

- `NO_OPEN_POSITION` does not fabricate MFE/MAE/ROE;
- MFE/MAE/ROE remain `None` without V2-owned open-position evidence;
- blocked tracker consumption masks fields with explicit `V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>` sources;
- `zero_filled_field_count` remains `0`.

These are positive, but they do not clear the raw-paper-input consumption blocker above.

## Safety

Codex verified:

- no Redis write call in the reviewed full-observation builder or aggregator path;
- no old Redis write path in the reviewed full-observation consumption files;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed path;
- no live/canary/shutdown/Redis-trim approval drift;
- raw credential-value scan over reviewed source and payloads found `0` hits outside `.local_secrets`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan matches for `v2:prediction:*` are V2-native full-observation reads outside the position-history tracker-consumption boundary, not old Redis writes.

## Validation

- New position-history consumption tests: `12 passed`.
- `py_compile`: PASS.
- Tracker heartbeat freshness check: PASS.
- Full-observation partial-status check: PASS.
- No-zero-fill check: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Raw credential scan: PASS, `0` hits.
- Tracker-only consumption boundary proof: FAIL BLOCKER.

## Required Remediation

Patch the full-observation position-history consumption path so tracker-derived position-context fields are computed only from the tracker payloads:

- `v2:paper:position_history:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:paper:position_history:heartbeat`

The builder should not use raw `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:intents`, or `v2:paper:intents_held_by_paper_fill_gate` for the tracker-derived fields after the tracker-consumption gate is allowed. If those raw keys remain useful for other non-tracker observation slices, keep them outside the tracker-derived field calculation.

Add regression tests proving:

- raw `paper_ledger` accepted rows cannot affect `v2_intents_accepted_count` when tracker history says zero;
- tracker history accepted/held/block counts are consumed when present;
- `NO_OPEN_POSITION` still leaves MFE/MAE/ROE null;
- `zero_filled_field_count` remains `0`;
- the gate still blocks without a fresh tracker heartbeat.

Then rerun this Codex review.

## Final Decision

`V2_FULL_OBSERVATION_POSITION_HISTORY_CONSUMPTION_CODEX_FAIL`
