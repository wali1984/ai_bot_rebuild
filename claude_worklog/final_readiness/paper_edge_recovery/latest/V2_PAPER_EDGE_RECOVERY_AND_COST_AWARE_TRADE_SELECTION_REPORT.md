# V2 Paper Edge Recovery And Cost-Aware Trade Selection Report

Generated: `2026-05-15T05:39:50Z`
Task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
Implementation owner for this pass: `Codex direct fix after Claude report-only blocked packet`

## Decision

`V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`

This does not approve live, canary, or legacy shutdown. Positive edge is still not proven because post-filter fills remain `0`. The change made here is narrower and important: V2 paper execution now fail-closes before any fill when required edge/provenance/symbol-scope evidence is missing.

## What Changed

- Added pure scorer `v2/backend/app/composition/paper_edge_scoring/runtime.py`.
- Integrated the scorer into `v2/backend/app/cli/v2_paper_execution_worker.py` before the paper ledger recorder is called.
- Extended worker status fields for edge/provenance/freshness/symbol-scope and shadow-observation request metadata.
- Added tests proving missing edge-after-costs, trainer source, feature freshness, paper symbol eligibility, and confidence-only admission cannot record fills.

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

If any condition fails, the worker returns `ledger_action=denied_by_paper_edge_gate`, `fills_recorded_total=0`, `fill_allowed=false`, and emits a `shadow_observation_request` instead of calling the ledger recorder.

## Preserved Loss Evidence

| Metric | Value |
| --- | --- |
| Current cumulative paper PnL | `-49.12` USDT |
| Source-limited prior baseline | `-26.37` USDT |
| Observed pre-filter loss | `-22.75` USDT |
| Post-filter PnL delta | `0.0` USDT |
| Post-filter fills | `0` |
| Post-filter unsafe fills | `0` |
| Explicit booked fees pre-filter | `22.69` USDT |
| Estimated slippage pre-filter | `11.345` USDT |
| Gross PnL if fees added back | `-0.06` USDT |
| 0.75+ confidence bucket pre-filter PnL | `-12.79` USDT |

Old pre-filter loss remains visible. Zero post-filter fills are classified as safety/edge-pending, not profitable edge.

## Validation

- `py_compile`: PASS
- Focused tests: `.venv/bin/pytest v2/backend/tests/unit/composition/test_paper_edge_scoring.py v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py` -> `44 passed`
- Manual adversarial dry run: PASS, an allow decision missing `expected_move_after_cost_bps`, `trainer_source`, `feature_freshness_state`, and paper symbol scope produced `denied_by_paper_edge_gate`, `fills_recorded_total=0`.

## Remaining Work

- `paper_shadow_outcome_observer.py` CLI is still pending; the worker now emits request metadata for blocked intents.
- Threshold replay has not been rerun against new edge fields; old pre-filter events are source-limited.
- Dynamic TP/stop, lifecycle, close-guard, reduce-only, and microstructure equivalents remain explicit paper-only pending mappings.
- Trainer parity derived/native evidence and trade-permission classification remain outside this paper-edge fix.

## Safety

`live_gate` remains `blocked_human_only`; `live_symbols` remains `[]`. This task created no approval token, no Redis trim approval, no old Redis write path, no exchange mutation path, and no leverage/margin change.
