# Paper Expected-Move After-Cost Coverage Remediation Report

Status: `PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_READY`

Generated at: `2026-05-15T08:11:06Z`

Live gate: `blocked_human_only`
Live symbols: `[]`
Approves live: `false`
Approves canary: `false`
Approves legacy shutdown: `false`

## Result

Native expected-move coverage is now wired from read-only legacy trainer prediction hashes into the V2 trainer bridge and paper runtime.

Current latest evidence:

- trainer source: `LEGACY_HYBRID_TRAINER_REDIS_READONLY`
- expected move source: `native_trainer_expected_move_bps`
- native expected move: `4.36588893` bps
- expected move after estimated costs: `-1.63411107` bps
- paper gate block: `expected_edge_below_costs`
- paper edge gate classification: `EDGE_AFTER_COSTS_NEGATIVE_BLOCK`
- paper edge minimum after-cost threshold: `8.0` bps
- paper fill: `false`

This is the desired safety behavior: the system no longer treats the latest decision as missing edge evidence, but it still blocks the paper fill because the native edge estimate is below the strict after-cost paper edge threshold.

## What Changed

- `v2_trainer_bridge` reads legacy `prediction:{symbol}:{timeframe}` hashes with read-only Redis commands only.
- The bridge maps legacy `price_target` / `entry_price` or `price_target_pct` into native `expected_move_bps`.
- The bridge keeps trainer lineage blockers intact for derived feature snapshot, derived confidence calibration, and incomplete feature attribution.
- `paper_online_runtime` forwards only native expected-move evidence into the canary/profile paper gate.
- `paper_online_runtime` now also applies the same `paper_edge_scoring` gate used by the execution worker, so a native but insufficient after-cost edge cannot become a paper fill if confidence/cooldown later pass.
- `paper_shadow_outcome_observer` records native expected move from paper runtime decisions even when risk blocks before a fill.

## Safety Invariants

- Missing expected move cannot permit a paper fill.
- Proxy expected move cannot permit a paper fill.
- Native expected move below `8.0` bps after costs cannot permit a paper fill.
- Future shadow outcomes are not used as entry signals.
- Legacy Redis is read-only reference evidence.
- No exchange mutation path is added.
- `live_gate` remains `blocked_human_only`.
- `live_symbols` remains `[]`.

## Remaining Blockers

- Current native expected move is below the strict after-cost paper edge threshold.
- No qualified post-filter paper fill has proven positive net edge.
- Trainer feature snapshot, confidence calibration, and attribution evidence remain derived/incomplete.
- Historical shadow false-blocks remain visible and are not erased.

## Validation

- `py_compile` passed for changed Python files.
- Focused tests passed: `80 passed`.
- V2 paper/trainer services were restarted only after safety preflight succeeded.

This report does not approve live trading, canary trading, or legacy shutdown.
