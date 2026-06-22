# Codex Review: V2 Full-Observation Post-Tracker Position Feature Expansion

Generated: `2026-05-22T01:48:10Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POST_TRACKER_POSITION_FEATURE_EXPANSION_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the post-tracker position feature expansion as partial progress. The six added position-context fields are tracker-owned and do not use raw paper ledger/intents as fallback. The full-observation builder remains partial, with zero-fill disabled and no checkpoint or policy parity claim.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Prerequisites

Codex verified prerequisite PASS markers:

- `V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`
- `V2_POSITION_HISTORY_TRACKER_GOVERNOR_REGISTRATION_CODEX_PASS`
- `V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_CODEX_PASS_PARTIAL_PROGRESS`

Current position-history runtime evidence:

- service `ai-bot-v2-position-history-persistent-tracker.service`: `active`
- process: `v2_position_history_persistent_tracker --loop`
- heartbeat key: `v2:paper:position_history:heartbeat`
- heartbeat TTL sample: `871`
- process mode: `persistent_daemon`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Tracker-Only Field Boundary

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/app/cli/v2_full_observation_builder_status.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_post_tracker_position_feature_expansion.py`
- packet worklog/public payloads
- current tracker Redis payloads

The six new fields are:

- `v2_tracker_latest_price`
- `v2_tracker_entry_price`
- `v2_tracker_source_freshness_seconds`
- `v2_tracker_missing_flag_count`
- `v2_tracker_stale_flag_count`
- `v2_shadow_observation_count`

`_extract_tracker_extended_fields(...)` accepts only tracker payloads plus the gate decision:

- `position_history`, read from `v2:paper:position_history:{symbol}`
- `position_price_track`, read from `v2:paper:position_price_track:{symbol}`
- heartbeat-backed consumption gate from `v2:paper:position_history:heartbeat`

It does not accept `paper_positions`, `paper_ledger`, `paper_intents`, or held-intent inputs. The prior accepted-position fields also remain tracker-only through `_extract_tracker_history_fields(...)`.

Raw paper-context rate/block-reason fields still exist, but they are separately sourced and labeled `V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY`; they do not feed tracker-derived accepted counts, price fields, MFE, MAE, or ROE.

## Runtime Field Evidence

Current consumption state:

- `position_history_consumption_state=ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT`
- `position_history_tracker_heartbeat_present=true`
- `position_history_tracker_heartbeat_fresh=true`

Current tracker state is flat/no-open for all three symbols:

- position history payloads: `position_state=NO_OPEN_POSITION`
- price-track payloads: `position_state=FLAT`
- `latest_price=null`
- `entry_price=null`
- `source_freshness_seconds=null`
- `mfe_bps=null`
- `mae_bps=null`
- `roe_bps=null`

Direct builder proof from current Redis:

| Symbol | Generated | Missing | `v2_tracker_latest_price` | `v2_tracker_entry_price` | `v2_tracker_source_freshness_seconds` | `v2_tracker_missing_flag_count` | `v2_tracker_stale_flag_count` | `v2_shadow_observation_count` |
| --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: |
| `BTCUSDT` | `160` | `1751` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `1.0` | `0.0` | `1.0` |
| `ETHUSDT` | `160` | `1751` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `1.0` | `0.0` | `1.0` |
| `SOLUSDT` | `154` | `1757` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `None / FIELD_MISSING` | `1.0` | `0.0` | `0.0` |

MFE, MAE, and ROE remain `None` with `V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION`. Accepted-intent counts are `0.0` from `V2_POSITION_HISTORY_TRACKER`; raw ledger/intents do not override them.

## Full-Observation Status

After refreshing `v2_full_observation_builder_status --once`, the canonical worklog and public payloads report:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target full-observation dimension: `1911`
- generated dimensions: `BTCUSDT=160`, `ETHUSDT=160`, `SOLUSDT=154`
- missing dimensions: `BTCUSDT=1751`, `ETHUSDT=1751`, `SOLUSDT=1757`
- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

`FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed by any current status payload. The dimension increase is honest partial progress: the three non-price tracker fields source today; the three price-bearing fields remain missing until real V2-owned open-position evidence exists.

## Safety

Codex verified:

- no Redis write call in the reviewed full-observation builder/status path;
- no old Redis write path in reviewed source;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path in reviewed source;
- no live/canary/shutdown/Redis-trim approval drift;
- raw credential-value scan over reviewed source and payloads found `0` credential hits outside `.local_secrets`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for raw `v2:paper:*` keys are the builder's separate non-tracker paper-context reads, forbidden-boundary comments, and regression tests. They are not used by the tracker-derived extractor for accepted-position fields or the six new tracker-only fields.

## Validation

- Full-observation status refresh: PASS.
- Focused full-observation tests: `45 passed`.
- `py_compile`: PASS.
- Tracker daemon active/running: PASS.
- Tracker heartbeat fresh with positive TTL: PASS.
- Direct current-Redis field-source proof: PASS.
- Zero-fill invariant: PASS.
- Partial-status payload inspection: PASS.
- Raw credential scan: PASS, `0` credential hits.
- Redis write scan: PASS, no writes in reviewed builder path.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_FULL_OBSERVATION_POST_TRACKER_POSITION_FEATURE_EXPANSION_CODEX_PASS_PARTIAL_PROGRESS`
