# Codex Review: Paper Expected-Move Coverage

Reviewed task: `claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks`

Result: `PASS_FOR_NATIVE_COVERAGE_READY_EDGE_STILL_UNPROVEN`

Codex extended the prior honest blocked packet by wiring native read-only legacy trainer target evidence into V2 paper:

- `prediction:{symbol}:{timeframe}` hashes are read with read-only Redis commands only.
- Legacy `price_target` / `entry_price` or `price_target_pct` is mapped to native `expected_move_bps`.
- V2 paper forwards only native expected-move evidence into the paper gate.
- V2 paper now also applies the strict `paper_edge_scoring` gate, including the `8.0` bps after-cost threshold, before a fill can be recorded.
- The latest paper gate blocks as `expected_edge_below_costs`, not as missing edge.

Validation performed:

- `.venv/bin/python3 -m py_compile v2/backend/app/services/trainer_bridge/service.py v2/backend/app/cli/v2_trainer_bridge.py v2/backend/app/cli/paper_online_runtime.py v2/backend/app/services/paper_shadow_outcome_observer/service.py`
- `.venv/bin/pytest v2/backend/tests/integration/cli/test_paper_shadow_outcome_observer.py v2/backend/tests/unit/cli/test_paper_online_runtime_weekly_loss.py v2/backend/tests/integration/cli/test_v2_trainer_bridge.py v2/backend/tests/unit/composition/test_paper_expected_move_coverage.py v2/backend/tests/unit/services/test_decision_improvement.py v2/backend/tests/unit/composition/test_paper_edge_scoring.py v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py`

Evidence:

- Focused tests passed: `80 passed`.
- Latest trainer bridge native expected move: `4.36588893` bps.
- Latest paper runtime after-cost expected move: `-1.63411107` bps.
- Latest paper block reason: `expected_edge_below_costs`.
- Latest strict paper edge classification: `EDGE_AFTER_COSTS_NEGATIVE_BLOCK`.
- No paper fill was permitted by this change.
- Live remains `blocked_human_only`; `live_symbols` remains `[]`.

Remaining blockers:

- Positive post-filter edge is still unproven.
- Current native expected move is below the strict after-cost paper edge threshold.
- Trainer feature snapshot, confidence calibration, and feature attribution remain derived/incomplete.
- Historical missing-edge false blocks remain visible in the shadow outcome window.
