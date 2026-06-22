# V2 Full Observation Missing-Feature Source Map Report

GO/NO-GO: `V2_FULL_OBSERVATION_MISSING_FEATURE_SOURCE_MAP_READY`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
checkpoint compatibility, or policy architecture port implementation.
It does NOT load any pickle/torch blob. It does NOT touch legacy.

## Purpose

Map every missing/partial slot of the legacy V3 1911-dim observation
into one of:

- `V2_SOURCE_EXISTS` (already filled by `full_observation_builder`)
- `V2_SOURCE_EXISTS_PARTIAL` (some V2-native dims already filled; more
  available from existing V2 data with extra projection work)
- `V2_SOURCE_MISSING_BUT_BUILDABLE` (V2 has the raw data, needs a new
  V2-native projection module)
- `EXTERNAL_SOURCE_REQUIRED` (no V2-native source today; needs a new
  external feed and operator approval before adoption)
- `OPERATOR_DECISION_REQUIRED` (adoption requires explicit operator
  choice)

## Live result this cycle

```
go_no_go = V2_FULL_OBSERVATION_MISSING_FEATURE_SOURCE_MAP_READY
status_counts = {
  "V2_SOURCE_MISSING_BUT_BUILDABLE": 5,
  "V2_SOURCE_EXISTS_PARTIAL": 3,
  "EXTERNAL_SOURCE_REQUIRED": 3,
  "OPERATOR_DECISION_REQUIRED": 1
}
narrow_tasks_required_count = 9
narrow_tasks_created_count   = 9 (first run) / 0 (idempotent re-run)
narrow_tasks_existing_count  = 0 (first run) / 9 (idempotent re-run)
```

## Family-level rollup (unified_features 1430 decomposition)

| Family | legacy size/source | V2 source status | Notes |
| ------ | ------------------: | ---------------- | ----- |
| `binance_klines` | 20 | `V2_SOURCE_MISSING_BUT_BUILDABLE` | v2:market:* binance live klines already ingested; need ohlcv-derived expansion. |
| `binance_orderbook` | 15 | `V2_SOURCE_MISSING_BUT_BUILDABLE` | depth_imbalance/bid_ask_spread_bps already in v2:features; full depth slice needs new V2 module. |
| `ccxt_ohlcv` | 10 | `OPERATOR_DECISION_REQUIRED` | Secondary-exchange OHLCV; V2 keeps native binance canonical. |
| `liquidations` | 12 | `V2_SOURCE_MISSING_BUT_BUILDABLE` | v2_native_ingestors_live_loop already ingests liquidations; needs 12-dim aggregator. |
| `technical_analysis` | 25 | `V2_SOURCE_EXISTS_PARTIAL` | ~15 TA fields in v2:features; ~10 remain. |
| `token_metrics` | 18 | `EXTERNAL_SOURCE_REQUIRED` | On-chain/sentiment; no V2 source. |
| `coinank` | 22 | `V2_SOURCE_EXISTS_PARTIAL` | Funding/OI fields present; needs 22-field expansion. |
| `portfolio_state_unified` | 15 | `V2_SOURCE_EXISTS_PARTIAL` | 12-of-15 paper aggregate counters; extend with margin/leverage/exposure. |

Plus larger slices outside `unified_features`:

| Family | Target dim | V2 source status |
| ------ | ---------: | ---------------- |
| `portfolio_state.extended` | 401 | `V2_SOURCE_MISSING_BUT_BUILDABLE` (project from v2:paper:* + v2:risk:*) |
| `position_context.extended` | 50 | `V2_SOURCE_MISSING_BUT_BUILDABLE` (MFE/MAE/ROE/hold-time from v2:paper:positions history) |
| `onchain_btc` | 15 | `EXTERNAL_SOURCE_REQUIRED` |
| `onchain_eth` | 15 | `EXTERNAL_SOURCE_REQUIRED` |

## Narrow task pairs created (one per family, idempotent)

Each pair is `OPERATOR_DECISION_REQUIRED`, `auto_apply_allowed_by_this_loop=false`,
with `forbidden_actions` covering legacy mutation, exchange mutation, old
Redis writes, live/canary/shutdown approvals, checkpoint blob commits,
and zero-fill fabrication:

- `claude_fix_v2_gap_unified_feature_family_binance_klines_source` ⇄ codex pair
- `claude_fix_v2_gap_unified_feature_family_binance_orderbook_source` ⇄ codex pair
- `claude_fix_v2_gap_unified_feature_family_ccxt_ohlcv_source` ⇄ codex pair
- `claude_fix_v2_gap_unified_feature_family_liquidations_source` ⇄ codex pair
- `claude_fix_v2_gap_unified_feature_family_token_metrics_source` ⇄ codex pair
- `claude_fix_v2_gap_portfolio_state_extended_source` ⇄ codex pair
- `claude_fix_v2_gap_position_context_extended_source` ⇄ codex pair
- `claude_fix_v2_gap_onchain_btc_source` ⇄ codex pair
- `claude_fix_v2_gap_onchain_eth_source` ⇄ codex pair

`technical_analysis` and `coinank` are already classified
`V2_SOURCE_EXISTS_PARTIAL` (extra dims available within existing V2-native
flow) so no new task pair is required for them — extending the existing
feature pipeline modules in-place is the path. `portfolio_state_unified`
similarly counts as partial within the existing flow.

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `policy_architecture_port_implementation_claimed = false`
- `checkpoint_compatibility_claimed = false`
- no torch import in any module here
- no pickle deserialization
- no legacy filesystem modification (legacy obs contract parsed from V2-owned mirror)
- no checkpoint blob committed to Git (`.local_models/` gitignored)

## What this packet does NOT do

- Does not implement any of the 9 family expansions.
- Does not approve external on-chain feed adoption.
- Does not modify the V2 runtime policy input (compact 26-dim remains).
- Does not claim full observation builder COMPLETE.
- Does not claim policy port complete.
- Does not start live/canary/shutdown work.
- Does not start a broad audit.

## Outputs

- [GO_NO_GO.md](claude_worklog/final_readiness/v2_full_observation_missing_feature_source_map/latest/GO_NO_GO.md)
- [missing_feature_source_map_status.json](claude_worklog/final_readiness/v2_full_observation_missing_feature_source_map/latest/missing_feature_source_map_status.json)
- [operator_dashboard_payload.json](v2/frontend/public/v2_full_observation_missing_feature_source_map/latest/operator_dashboard_payload.json)
- 9 paired Claude+Codex narrow tasks in [claude_worklog/agent_supervisor/tasks/](claude_worklog/agent_supervisor/tasks/)
