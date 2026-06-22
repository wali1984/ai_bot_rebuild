# V2 Paper Position Acceptance-State Schema Normalization Report

GO/NO-GO: V2_PAPER_POSITION_ACCEPTANCE_STATE_NORMALIZATION_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT loosen the strict paper-fill gate. It does NOT introduce any
unsafe fills. It does NOT claim checkpoint compatibility or policy
architecture parity.

## Codex finding addressed

Codex observed that `v2:paper:positions` carried rows where
`paper_fill_allowed=false`, conflating accepted paper fills with
no-fill provenance observations. This packet normalizes the
acceptance-state schema so the three states are written to three
separate keys with explicit decision markers.

## State split

| Redis key | Contents | Row invariants |
|---|---|---|
| `v2:paper:positions` | Accepted paper fills only | `decision=ACCEPTED_PAPER_FILL`, `paper_fill_allowed=true`, `places_real_order=false`, all local gates pass |
| `v2:paper:shadow_observations` | Local gates pass but upstream paper-fill gate withheld the fill | `decision=SHADOW_OBSERVATION_ONLY`, `paper_fill_allowed=false`, `places_real_order=false`, `counted_as_accepted_position=false`, `counted_as_fill=false`, `counted_as_open_position=false`, `entry_price_provenance_observed=true|false` |
| `v2:paper:intents_held_by_paper_fill_gate` | Orchestrator pre-emptively held the intent before it reached the writer | `decision=HELD_BY_PAPER_FILL_GATE`, `paper_fill_allowed=false`, `places_real_order=false` |
| (blocked[]) | Intent failed local pre-trade / fee-ratio / churn gates | Tracked in ledger.blocked only; never a fill, never a shadow row |

## Ledger normalization

`v2:paper:ledger` now carries three explicit lists and three explicit
counts:

- `accepted_intents` / `accepted_position_count`
- `shadow_observations` / `shadow_observation_count`
- `held_by_paper_fill_gate` / `held_position_count`
- `blocked` / `blocked_count`

A new `schema_split` block on the ledger pins the invariants:

```
schema_split: {
  accepted_positions_must_have_paper_fill_allowed_true: true,
  shadow_observations_have_paper_fill_allowed_false: true,
  held_by_gate_have_paper_fill_allowed_false: true,
  recorder_consumes_v2_paper_positions_only_for_accepted_mfe_mae_roe: true,
}
```

The status payload schema was bumped to
`v2_trade_management_paper_live_v2` and exposes the same counts +
`shadow_observations` list.

## Recorder consumes only accepted positions for MFE/MAE/ROE

The position price tracking recorder already reads
`v2:paper:positions` as its source for accepted MFE/MAE/ROE. After
the writer normalization, that key contains ONLY accepted fills, so
the recorder's accepted-position math is automatically correct
without changing recorder code. Shadow rows never feed MFE/MAE/ROE.
Held rows never feed MFE/MAE/ROE.

Live recorder state after normalization:

```
state_counts: {FLAT: 3}
symbols_with_entry_recovered: []
symbols_with_realized_exit_recovered: []
symbols_still_blocked: [BTCUSDT, ETHUSDT, SOLUSDT]
```

All three symbols correctly read as FLAT because the current upstream
paper-fill gate is not allowing fills — and the recorder no longer
treats shadow rows as positions.

## Full observation builder — truthful regression

Per-symbol generated dim BEFORE vs AFTER normalization:

| Symbol  | Before normalization (counted shadow as positions) | After normalization (truthful) |
|---|---|---|
| BTCUSDT | 156 | **151** |
| ETHUSDT | 156 | **151** |
| SOLUSDT | 147 | **145** |

This is a **truthful regression**. Before normalization, the
position_context slice's derived fields (`v2_position_history_present`,
`v2_intents_accepted_count`, `v2_hold_time_seconds_current`, etc.)
were counting shadow rows as positions, inflating the dim count with
values that did not reflect accepted fills. After normalization, no
accepted fills are present, so position-derived dims are correctly
zero. The dim count is now truthful.

Target dim unchanged at 1911. State unchanged at
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`.
`checkpoint_compatibility_claimed = false`,
`policy_architecture_parity_claimed = false`.

The path to higher dim counts now requires the upstream paper-fill
gate to start emitting `paper_fill_allowed=true` predictions (which
is gated on checkpoint compatibility and other operator-decision
items), not the writer counting shadow rows as positions.

## Live state after restart

```
v2:paper:positions             = []
v2:paper:shadow_observations   = 2 rows (BTCUSDT, ETHUSDT)
v2:paper:intents_held_by_paper_fill_gate = 1 row (SOLUSDT)
v2:paper:ledger.accepted_position_count = 0
v2:paper:ledger.shadow_observation_count = 2
v2:paper:ledger.held_position_count = 1
```

The systemd-managed paper-loop process is the sole writer (orphan
killed in the prior packet). After the restart, the next 60s tick
produced the normalized split.

## Tests

`v2/backend/tests/integration/cli/test_v2_paper_position_acceptance_state_normalization.py` — 10 new tests.
`v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py` — 13 prior tests updated to reflect the new shadow split.
Combined: **23 / 23 pass**.

Coverage:

- accepted row requires `paper_fill_allowed=true`
- `paper_fill_allowed=false` row goes to shadow, NOT positions
- shadow row carries provenance marker when market price missing
- local-gate failure goes to blocked, never to positions or shadow
- held-by-orchestrator-gate row never enters positions or shadow
- ledger carries three lists + three counts + schema_split contract
- strict gate threshold unchanged across a mixed batch (no unsafe fills)
- writer writes only `v2:` prefixed keys after normalization
- module source still contains no exchange-mutation verbs
- module still does not import torch
- prior provenance tests updated to assert against the correct
  destination key (positions vs shadow) based on the upstream
  `paper_fill_allowed` flag

## Strict gate invariants

- `paper_fill_gate_loosened = false`
- `unsafe_fills_introduced = false`
- `strict_gate_threshold_unchanged = true`
- Held intents from the orchestrator continue to flow into
  `v2:paper:intents_held_by_paper_fill_gate` with their original
  block reasons and checkpoint blocker fields.
- No threshold relaxed. No new accepted fill that the gate would have
  rejected.

## Safety invariants

- `live_gate = blocked_human_only`, `live_symbols = []`
- `approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false`
- `writes_legacy_redis / writes_exchange_orders = false`
- `places_real_order = false` on every accepted, shadow, and held row
- `never_fabricates`, `never_uses_legacy_redis_as_truth`,
  `never_uses_static_sample_price` (inherited from the provenance
  packet)
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy.
- Does not pause V2 runtime.
- Does not change leverage or margin.
- Does not loosen the strict paper-fill gate.
- Does not introduce any new accepted fill that the gate would have
  rejected.
- Does not place, modify, or cancel exchange entries.
- Does not synthesize close events.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.
- Does not start the policy architecture port.

## Outputs

- `claude_worklog/final_readiness/v2_paper_position_acceptance_state_normalization/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_paper_position_acceptance_state_normalization/latest/V2_PAPER_POSITION_ACCEPTANCE_STATE_NORMALIZATION_REPORT.md`
- `claude_worklog/final_readiness/v2_paper_position_acceptance_state_normalization/latest/paper_position_acceptance_state_normalization_status.json`
- `v2/frontend/public/v2_paper_position_acceptance_state_normalization/latest/operator_dashboard_payload.json`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py` (modified)
- `v2/backend/tests/integration/cli/test_v2_paper_position_acceptance_state_normalization.py` (new; 10 tests)
- `v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py` (updated; 13 tests)
- `claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json` (refreshed; truthful regression)
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json` (refreshed)
