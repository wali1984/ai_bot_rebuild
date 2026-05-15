# V2 Paper Edge Recovery And Cost-Aware Trade Selection Report

Generated: `2026-05-15T08:25:55Z`
Task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`

## Decision

`V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`

This does not approve live, canary, or legacy shutdown. The paper fill boundary is now strict and cost-aware, but positive edge is still not proven.

## Current Runtime Evidence

The previous packet was generated before live paper events accumulated under the strict gate. Current JSONL evidence now shows:

| Window | Start | Fills | Unsafe fills | PnL delta | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| Original post-canary filter | `2026-05-14T22:40:46Z` | 2 | 1 | -0.02 | Canary filter alone allowed one source-limited fill before strict edge gate |
| Strict cost-aware gate | `2026-05-15T08:11:06Z` | 1 | 0 | -0.01 | One qualified paper-only fill; edge still pending |

The strict-gate fill at `2026-05-15T08:20:27Z` had native trainer expected move, accepted trainer source, current feature freshness, paper symbol eligibility, no exchange order, no old Redis write, `live_gate=blocked_human_only`, and `live_symbols=[]`.

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

If any condition fails, the worker records a blocked paper intent and emits shadow-observation metadata instead of recording a fill.

## Preserved Loss Evidence

| Metric | Value |
| --- | --- |
| Current cumulative paper PnL | `-49.14` USDT |
| Source-limited prior baseline | `-26.37` USDT |
| Observed pre-filter loss | `-22.75` USDT |
| Original post-canary PnL delta | `-0.02` USDT |
| Strict cost-aware gate PnL delta | `-0.01` USDT |
| Strict cost-aware gate fills | `1` |
| Strict cost-aware gate unsafe fills | `0` |
| Explicit booked fees pre-filter | `22.69` USDT |
| Estimated slippage pre-filter | `11.345` USDT |
| Gross PnL if fees added back | `-0.06` USDT |

Old pre-filter loss and the source-limited post-canary fill remain visible. The strict-gate sample is not enough to prove profitable edge.

## Validation

- `py_compile`: PASS from implementation validation.
- Focused tests: `.venv/bin/pytest v2/backend/tests/unit/composition/test_paper_edge_scoring.py v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py` -> `44 passed` during implementation validation.
- Runtime JSONL audit: strict cost-aware gate has `0` unsafe fills as of `2026-05-15T08:25:55Z`.

## Remaining Work

- Continue paper shadow outcome observation for blocked intents and qualified fills.
- Do not loosen the gate just because strict fills are sparse.
- Threshold replay remains source-limited until enough new edge/provenance fields accumulate.
- Trainer parity derived/native evidence and trade-permission classification remain outside this paper-edge fix.

## Safety

`live_gate` remains `blocked_human_only`; `live_symbols` remains `[]`. This task created no approval token, no Redis trim approval, no old Redis write path, no exchange mutation path, and no leverage/margin change.
