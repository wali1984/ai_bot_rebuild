# Codex Review: V2 Paper Position Acceptance-State Normalization

Generated: `2026-05-18T20:50:05Z`

GO/NO-GO: `V2_PAPER_POSITION_ACCEPTANCE_STATE_NORMALIZATION_CODEX_PASS`

## Decision

Codex passes the acceptance-state normalization. The prior blocker is cleared: live `v2:paper:positions` no longer contains `paper_fill_allowed=false` rows, BTCUSDT/ETHUSDT local-pass/upstream-blocked rows now land in `v2:paper:shadow_observations`, and held-by-gate SOLUSDT remains held-only.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Live State

Current Redis state after the running systemd paper loop tick:

| Surface | Count | Accepted/Open Position Surface |
| --- | ---: | --- |
| `v2:paper:positions` | `0` | accepted fills only; none active |
| `v2:paper:shadow_observations` | `2` | BTCUSDT/ETHUSDT, shadow-only |
| `v2:paper:intents_held_by_paper_fill_gate` | `1` | SOLUSDT, held-only |
| `v2:paper:ledger.accepted_position_count` | `0` | no accepted fills |
| `v2:paper:ledger.shadow_observation_count` | `2` | shadow-only rows |
| `v2:paper:ledger.held_position_count` | `1` | held-only row |

The shadow rows carry:

- `decision=SHADOW_OBSERVATION_ONLY`
- `paper_fill_allowed=false`
- `counted_as_accepted_position=false`
- `counted_as_fill=false`
- `counted_as_open_position=false`
- `places_real_order=false`

The held row carries `decision=HELD_BY_PAPER_FILL_GATE` and remains outside `v2:paper:positions` and `v2:paper:shadow_observations`. It is not counted as a fill or open position.

## Accepted Fill Boundary

The writer now requires both local gates and upstream paper-fill permission before a row enters `accepted` / `v2:paper:positions`:

`pre_trade_allowed AND fee_gate_allowed AND not churn_blocked AND paper_fill_allowed=true`

No active accepted fill is present in live Redis, so accepted-row fields are live-proven by absence and test-proven for the positive case. The focused tests verify accepted rows include:

- `decision=ACCEPTED_PAPER_FILL`
- `paper_fill_allowed=true`
- `places_real_order=false`

## Ledger Contract

The live ledger carries the required split:

- `accepted_intents` / `accepted_position_count`
- `shadow_observations` / `shadow_observation_count`
- `held_by_paper_fill_gate` / `held_position_count`
- `blocked` / `blocked_count`
- `schema_split`

`schema_split` preserves the intended invariants, including that accepted positions must have `paper_fill_allowed=true` and recorder MFE/MAE/ROE must be sourced from accepted `v2:paper:positions` only.

Note: the live held row is held-only and not counted as a fill/open position. It does not currently include an explicit `paper_fill_allowed=false` field, but it also does not include `paper_fill_allowed=true` and does not enter any accepted-position surface. This is not a blocker for this review; adding the explicit false field would make the held-row schema cleaner.

## Recorder And Full Observation

After refreshing the recorder:

- recorder GO/NO-GO: `V2_POSITION_PRICE_TRACKING_RECORDER_READY`
- burndown GO/NO-GO: `V2_POSITION_PRICE_TRACKING_ENTRY_EXIT_HISTORY_BURNDOWN_BLOCKED`
- state counts: `FLAT=3`
- `symbols_with_entry_recovered=[]`
- `symbols_with_realized_exit_recovered=[]`
- `symbols_still_blocked=["BTCUSDT", "ETHUSDT", "SOLUSDT"]`

The recorder reads `v2:paper:positions` for accepted-position MFE/MAE/ROE. It does not read `v2:paper:shadow_observations`, and shadow/held rows do not feed MFE/MAE/ROE.

After refreshing full-observation status:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target dim: `1911`
- generated dims: `BTCUSDT=151`, `ETHUSDT=151`, `SOLUSDT=145`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

The dimension regression is truthful: the previous higher BTC/ETH counts came from false-gate rows being treated as open accepted positions. With no accepted fills present, position-derived dimensions correctly drop instead of being inflated.

## Runtime And Safety

The systemd-managed paper loop remains active:

- `ai-bot-v2-trade-management-paper-loop.service`: active/running
- `PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD`
- `LIVE_GATE=blocked_human_only`

The Codex 8h war-room governor remains healthy:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_legacy_redis`: `false`
- `writes_exchange_orders`: `false`

## Validation

- Normalization tests: PASS.
- Provenance tests: PASS.
- Recorder tests: PASS.
- TA/position-history tests: PASS.
- Combined focused sweep: `64 passed`.
- `py_compile`: PASS.
- JSON validation: PASS.
- Raw secret scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- `git diff --check`: PASS for reviewed artifacts.

## Final Decision

`V2_PAPER_POSITION_ACCEPTANCE_STATE_NORMALIZATION_CODEX_PASS`
