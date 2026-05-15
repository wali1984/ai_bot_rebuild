# V2 Paper Edge Recovery And Cost-Aware Trade Selection Report

Generated: `2026-05-15T08:34:00Z`
Task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`

## Decision

`V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`

This does not approve live, canary, or legacy shutdown. Positive edge is still not proven.

## Current Runtime Evidence

Current JSONL evidence after the strict edge gate and the new fee-bleed guard:

| Window | Start | Fills | Unsafe fills | PnL delta | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| Original post-canary filter | `2026-05-14T22:40:46Z` | 2+ | 1 | source-limited | Canary filter alone allowed one source-limited fill before strict edge gate |
| Strict cost-aware gate before outcome guard | `2026-05-15T08:11:06Z` | 2 | 0 | -0.02 | Qualified paper fills still booked fee-only loss because the runtime lacked an exit/outcome model |
| Outcome-model fee-bleed guard | `2026-05-15T08:32:56Z` | 0 | 0 | 0.0 | Qualified intents are blocked for shadow observation while paper outcome model is missing |

The new guard prevents fee-only paper PnL drift. Even if the edge/provenance/freshness gate passes, paper fill recording is denied until V2 has a non-live exit/outcome simulator.

## Hard Fill Boundary

A V2 paper fill is blocked unless all of these pass:

- `expected_move_after_cost_bps >= 8`
- `confidence_calibrated >= 0.70`
- `trainer_source` is present and accepted
- `feature_freshness_state == CURRENT`
- `symbol` is in `paper_symbols`
- `live_symbols == []`
- `live_gate == blocked_human_only`
- cooldown / flip / churn guards are clear
- risk gateway action is `allow`
- paper exit/outcome simulator is ready

The last condition is currently false, so qualified intents are shadow-observe only.

## Preserved Loss Evidence

| Metric | Value |
| --- | --- |
| Current cumulative paper PnL | `-49.15` USDT |
| Source-limited prior baseline | `-26.37` USDT |
| Observed pre-filter loss | `-22.75` USDT |
| Strict cost-aware gate fills before outcome guard | `2` |
| Strict cost-aware gate fee-only PnL delta before outcome guard | `-0.02` USDT |
| Outcome-model guard fills | `0` |
| Outcome-model guard PnL delta | `0.0` USDT |
| Explicit booked fees pre-filter | `22.69` USDT |
| Estimated slippage pre-filter | `11.345` USDT |
| Gross PnL if fees added back | `-0.06` USDT |

Old pre-filter loss and the source-limited post-canary fill remain visible. The strict-gate qualified fills showed the paper simulator still had fee-only drift, so they are not positive edge proof.

## Validation

- `py_compile`: PASS for `v2/backend/app/cli/paper_online_runtime.py`.
- Focused tests: `18 passed`.
- Runtime verification after V2 paper runtime restart: post-guard events = `2`, fills = `0`, blocked = `2`, fee = `0.0`, old Redis writes = `false`, exchange orders = `false`.

## Remaining Work

- Build/enable a non-live paper exit/outcome simulator before any further fee-charging paper fill is allowed.
- Continue shadow outcome observation for blocked qualified intents.
- Do not loosen the gate just because fills are blocked.
- Trainer parity derived/native evidence and trade-permission classification remain unresolved.

## Safety

`live_gate` remains `blocked_human_only`; `live_symbols` remains `[]`. This task created no approval token, no Redis trim approval, no old Redis write path, no exchange mutation path, and no leverage/margin change.
