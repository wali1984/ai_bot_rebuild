# V2 Full Observation Vector Builder P0 Report

GO/NO-GO: `V2_FULL_OBSERVATION_BUILDER_PARTIAL_READY_FOR_MISSING_FEATURE_BURNDOWN`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
checkpoint compatibility, or policy architecture parity. It does NOT
load any pickle/torch blob.

## What got built

[v2/backend/app/services/rl_core/full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py)
- Reads only V2-native runtime inputs from Redis:
  `v2:features:latest:{sym}:{tf}`, `v2:paper:positions`,
  `v2:paper:ledger`, `v2:risk:decisions`, `v2:orchestrator:decisions`,
  `v2:trainer:heartbeat`, `v2:prediction:{sym}:{tf}`.
- Preserves the existing 26-dim compact observation as
  `compact_observation_v1` — V2 runtime policy input stays unchanged.
- Builds a parallel 1911-dim `full_observation_v1` tensor matching the
  legacy V3 slice layout (`unified_features=1430`, `portfolio_state=401`,
  `onchain_btc=15`, `onchain_eth=15`, `position_context=50`).
- For every position emits a `(value, name, source)` triple; positions
  with no V2-native source remain `None` with the source label
  `MISSING_FROM_*` or `ONCHAIN_FEATURE_SOURCE_MISSING`. **Nothing is
  zero-filled silently.**

[v2/backend/app/cli/v2_full_observation_builder_status.py](v2/backend/app/cli/v2_full_observation_builder_status.py)
- One-shot CLI emitting the worklog, the `v2_rl_core/latest` mirror, and
  the `v2_full_observation_builder/latest` operator dashboard.

[v2/backend/tests/integration/cli/test_v2_full_observation_builder_status.py](v2/backend/tests/integration/cli/test_v2_full_observation_builder_status.py)
- 9 cases covering: target dim 1911 + compact 26; no silent zero-fill;
  partial state when categories missing; deterministic outputs from
  identical inputs; onchain slices reported as `ONCHAIN_FEATURE_SOURCE_MISSING`;
  complete state requires all 1911 dims; payload safety invariants;
  guard that no torch import occurs; CLI writes identical worklog +
  rl_core + dashboard payloads.

## Live builder result (this cycle)

```
target_full_observation_dim = 1911
compact_observation_dim     = 26
state                       = FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS
checkpoint_compatibility_claimed = false
policy_architecture_parity_claimed = false
no_zero_fill_for_unknown_fields = true
no_legacy_features_consumed_as_current_truth = true
```

Per-symbol counts (raw):
- BTCUSDT: generated=44, missing=1867
- ETHUSDT: generated=44, missing=1867
- SOLUSDT: generated=39, missing=1872 (strict gate blocked, fewer present fields)

Category-level breakdown (all 3 symbols):
- `present`: (none)
- `partial`: `unified_features`, `portfolio_state`, `position_context`
- `explicit_missing`: `onchain_btc`, `onchain_eth`

## Category implementation status

### unified_features (target 1430)
V2-native source: `v2:features:latest:{sym}:{tf}`. 23 of 1430 dims filled
from the V2 feature snapshot (ohlcv-derived, TA, multi-timeframe,
microstructure, funding/OI/liquidation, portfolio-aware).
Missing: 1407 dims with explicit `MISSING_FROM_V2_NATIVE_FEATURE_SNAPSHOT`
source label per position.

### portfolio_state (target 401)
V2-native source: aggregate counters derived from `v2:paper:positions`,
`v2:paper:ledger`, `v2:risk:decisions`, `v2:orchestrator:decisions`,
`v2:trainer:heartbeat`. 12 of 401 dims filled.
Missing: 389 dims labeled `MISSING_FROM_V2_PAPER_RISK_REDIS`.

### onchain_btc (target 15) — `ONCHAIN_FEATURE_SOURCE_MISSING`
No V2-native source today. All 15 positions explicitly marked
`ONCHAIN_FEATURE_SOURCE_MISSING`. No fake values written. A narrow
follow-up task is recorded in the model-parity sprint (operator must
decide whether to add a V2-native on-chain ingestor; no source path
exists yet so no implementation task is auto-created).

### onchain_eth (target 15) — `ONCHAIN_FEATURE_SOURCE_MISSING`
Same as BTC.

### position_context (target 50)
V2-native source: per-symbol projection from `v2:paper:positions`,
`v2:risk:decisions`, `v2:prediction:{sym}:{tf}`. 9 of 50 dims filled.
Missing: 41 dims labeled `MISSING_FROM_V2_PAPER_RISK_REDIS`.

## What is NOT yet done

This packet stops at `PARTIAL_READY_FOR_MISSING_FEATURE_BURNDOWN`:

- Does NOT implement the full V2-native unified_features expansion
  (1407 missing dims).
- Does NOT implement the V2-native portfolio_state expansion
  (389 missing dims).
- Does NOT implement V2-native on-chain ingestors (30 missing dims).
- Does NOT implement the policy architecture port.
- Does NOT claim checkpoint compatibility.
- Does NOT load any legacy `.pt`/`.pkl`/`.ckpt`.
- Does NOT touch legacy at /home/wali/Desktop/AI BOT.
- Does NOT modify the V2 runtime policy input (still 26-dim compact).

## Continuous remediation integration

The continuous remediation tool's gap matrix remains driven by mismatch
causes from the comparator + legacy log observer; the model-parity
sprint surfaces these as separate tasks at the agent_supervisor level so
no duplicate checkpoint task is created. The current task pair
inventory:

- existing checkpoint blocker pair (`trainer_missing_checkpoint_weight_shape_contract`) — preserved
- existing paper-fill passthrough pair (`paper_fill_gate_block_reason_passthrough_missing`) — Codex PASS, completed
- new pair (this sprint family): `claude_fix_v2_gap_full_observation_vector_builder` ⇄ `codex_review_fix_v2_gap_full_observation_vector_builder` (operator-decision-required, auto_apply_allowed_by_this_loop=false)
- new pair (this sprint family): `claude_fix_v2_gap_policy_architecture_shape_contract` ⇄ `codex_review_fix_v2_gap_policy_architecture_shape_contract` (operator-decision-required)

No duplicate checkpoint task created. `checkpoint_weight_missing` remains
visible as `BLOCKS_PRODUCTION_EQUIVALENCE` in the gap matrix.

## Soak / runtime preservation

- soak `minutes_observed = 1051+`, `soak_6h_ready = true`, `all_v2_processes_uninterrupted = true`.
- continuous remediation `V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY`.
- Codex 5M `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY` (per last run).
- live_gate = `blocked_human_only`; live_symbols = `[]`.

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- no torch import in the builder module or CLI
- no pickle deserialization
- no legacy filesystem read (legacy obs contract is read from the V2-owned legacy mirror only)
- no legacy `features:*` consumed as current truth
- no checkpoint blob committed to Git (`.local_models/` gitignored)
- `no_zero_fill_for_unknown_fields = true` (no silent fabrication)

## Required next work (operator path)

1. Decide whether to extend V2-native unified_features beyond the current
   23-of-1430 fields — and whether to add a V2-native on-chain ingestor.
2. Once additional category fields are sourced, re-run the builder; once
   `generated_full_observation_dim == 1911`, state will flip to
   `FULL_OBSERVATION_BUILDER_COMPLETE` and the policy-port lane becomes
   the next review target.
3. Only after `COMPLETE` should the policy architecture port be
   evaluated as a parity candidate, per Codex's review of the
   model-parity sprint.

Until then, this packet remains exactly:
`V2_FULL_OBSERVATION_BUILDER_PARTIAL_READY_FOR_MISSING_FEATURE_BURNDOWN`.
