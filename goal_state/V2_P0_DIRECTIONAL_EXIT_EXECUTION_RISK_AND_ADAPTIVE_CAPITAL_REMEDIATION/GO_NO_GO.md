# V2_ADAPTIVE_CAPITAL_PRODUCTIVITY_COMPOUNDING_AND_1000X_FEASIBILITY GO/NO-GO

Generated UTC: `2026-06-20T18:00:27Z`

Overall status: **NO_GO**

## P0 Freeze

- Frozen P0 baseline: `True`
- P0 policy version: `PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1`
- P0 validator: `PASSED` at `2026-06-19T20:28:45Z`
- Live gate: `blocked_human_only`

## Remaining Blockers

- `capital_productivity_runtime_status`
- `counterfactual_capital_sweep_status`
- `adaptive_capital_policy_status`
- `compounding_equity_status`
- `one_thousand_x_feasibility_status`

## Evidence To GO

- Closed outcomes needed: `197`; after current open positions close `195`
- Additional symbols needed: `6`
- A-grade replay evidence needed: `1`
- Counterfactual best configurations needed: `1`
- Selection attribution rows needed: `0`
- Leverage attribution rows needed: `0`
- Margin-mode attribution rows needed: `0`
- Hedge-budget attribution rows needed: `0`
- Closest A-grade confidence gap: `0.07758598`
- Closest A-grade edge gap bps: `0.0`
- Counterfactual configurations considered: `0` / `0`; reconciled `True`

## Pass Conditions

- No fixed runtime size: `PASSED`
- No fixed runtime leverage: `PASSED`
- Adaptive capital selection attribution complete: `PASSED`
- 100% mandatory per-trade margin/leverage accounting: `PASSED`
- Idle capital classification distinguishes no-edge and allocator underdeployment: `PASSED`
- Positive net return on deployed margin: `PASSED`
- Positive after-cost expectancy: `PASSED`
- Acceptable drawdown and expected shortfall: `PASSED`
- Rare-event capital stress passes: `PASSED`
- Counterfactual replay complete for A-grade signals: `NO_GO`
- At least 300 post-policy economic outcomes: `NO_GO`
- Both LONG and SHORT outcome evidence: `PASSED`
- Minimum post-policy symbol diversity: `NO_GO`
- Paper/live pre-submit parity without exchange mutation: `PASSED`
- No real order or exchange mutation: `PASSED`
- Compounding evidence passes: `NO_GO`
- 1000x feasibility classified against explicit horizon without guarantee: `PASSED`

## Capital Productivity

- Status: `NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE`
- Closed post-allocator outcomes: `103` / `300`; deficit `197`
- Closed outcome progress: `0.34333333`; projected after open positions close `105` / `300`; projected deficit `195`
- Symbol diversity progress: `24` / `30`; deficit `6`
- Accepted-fill reconciled closed outcomes: `16`
- Post-allocator realized PnL: `34.43214804`
- Closed deployed margin: `46018.60496721`
- Return on deployed margin: `0.00074822`
- Break-even realized PnL gap: `0.0`; return gap to zero `0.0`
- After-cost expectancy bps: `25.71084155`

## Adaptive Field Selection

- Selection attribution status: `PASSED`
- Selection attribution blockers: `[]`
- Complete selection model-input coverage: `0.72380952` from `76` / `105` rows
- Selection attribution missing counts: `{'leverage_selection_model_input': 29, 'margin_mode_selection_model_input': 29, 'hedge_budget_selection_model_input': 29, 'complete_selection_model_input': 29}`
- Required selection field coverage: `1.0` from `105` rows
- Current pre-submit field coverage: `0.0` from `0` rows
- Runtime leverage model-input coverage: `0.72380952`
- Runtime margin-mode model-input coverage: `0.72380952`
- Runtime hedge-budget model-input coverage: `0.72380952`
- Gross notional unique count: `91`
- Current pre-submit gross notional unique count: `0`
- Allocated margin unique count: `96`
- Current pre-submit allocated margin unique count: `0`
- Effective leverage values: `[1.0, 2.0]`
- Current pre-submit effective leverage values: `[]`
- Recommended margin modes: `['isolated_paper_simulated']`
- Current pre-submit margin modes: `[]`
- Margin-mode selection reason counts: `{'__missing__': 29, 'isolated_limits_tail_contagion_for_current_risk': 76}`
- Current pre-submit margin-mode reason counts: `{}`
- Hedge-budget values sample: `[0.0, 0.0158134, 0.02145652, 0.03557855, 0.04734461, 0.04806386, 0.11542453, 0.13066619, 0.13265687, 0.13755203, 0.14449103, 0.17249512, 0.17311174, 0.18531213, 0.21114386, 0.2215776, 0.30351625, 0.31123151, 0.33154316, 0.34531849]`
- Current pre-submit hedge-budget values sample: `[]`
- Hedge-budget selection reason counts: `{'__missing__': 29, 'correlation_drawdown_volatility_cost_pressure': 66, 'hedge_budget_not_required_for_current_risk': 10}`
- Current pre-submit hedge-budget reason counts: `{}`

## PnL History

- `1d` PnL: `32.01552723` from `372` closed trades; win rate `0.26075269`, profit factor `1.13417126`
- `7d` PnL: `111.61218118` from `1548` closed trades; win rate `0.30167959`, profit factor `1.17907267`
- `30d` PnL: `111.61218118` from `1548` closed trades; win rate `0.30167959`, profit factor `1.17907267`

## Signal/Prediction Accuracy

- Status: `READY`
- Overall accuracy: `0.3018746` from `1547` evaluated rows
- Symbol universe count: `151`
- Required symbol/timeframe cells without evaluated outcomes: `455`
- `1m` accuracy: `0.28514056` from `249` evaluated rows; PnL `16.32089661`
- `5m` accuracy: `0.31313131` from `198` evaluated rows; PnL `4.25457273`
- `15m` accuracy: `0.29032258` from `341` evaluated rows; PnL `-21.14400862`
- `1h` accuracy: `0.31460674` from `534` evaluated rows; PnL `96.63776606`
- `4h` accuracy: `0.29777778` from `225` evaluated rows; PnL `15.55790736`

## Counterfactual Sweep

- Status: `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE`
- Source coverage: `PASSED` at `1.0`
- Required symbol/timeframe cells: `755` / `755`; missing `0`
- A-grade signals: `0`
- Prediction rows probed: `755`; probe status `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE`; participates in pass gate `False`
- Near-A-grade probe status: `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE` at confidence threshold `0.65`; best configs `0`; participates in pass gate `False`
- Near-A-grade temporal-invalid count: `0`
- A-grade replay progress: `0.0`; deficit `1`
- Configuration-space reconciliation: `True`
- Event-time-valid candidates: `0`
- Best configurations: `0`
- Market depth requirement: `required_actual_depth_usd_or_orderbook_levels`
- Market cost requirement: `required_explicit_spread_slippage_fee_funding_bps_or_usd`
- Market cost evidence coverage: `NO_CANDIDATES` with `0` / `0` complete A-grade candidates; missing `{}`
- Prediction market cost evidence coverage: `NO_CANDIDATES` with `0` / `0` complete candidates; missing `{}`
- Near-A-grade market cost evidence coverage: `NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE` with `0` / `17` complete candidates; missing `{'MISSING_ACTUAL_SPREAD': 17, 'MISSING_FEES': 17, 'MISSING_FUNDING': 17, 'MISSING_MARKET_DEPTH': 17, 'MISSING_SLIPPAGE': 17}`

## A-grade Readiness

- Confidence threshold: `0.75`
- After-cost edge threshold bps: `0.0`
- Source kind counts: `{'__unspecified__': 2, 'paper_ledger': 802, 'paper_signal': 755}`
- Readiness blockers: `['NO_A_GRADE_SIGNALS']`
- `__unspecified__` rows `2`; confidence >= threshold `0`; positive edge `0`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `None`; reasons `{'MISSING_AFTER_COST_EDGE': 2, 'MISSING_CONFIDENCE': 2}`
- `paper_ledger` rows `802`; confidence >= threshold `0`; positive edge `28`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.08314229`; reasons `{'ALLOCATOR_BLOCK_DRAWDOWN_GUARD': 19, 'ALLOCATOR_BLOCK_LOW_CONFIDENCE': 3, 'ALLOCATOR_BLOCK_NO_EDGE': 199, 'ALLOCATOR_BLOCK_SPREAD_SLIPPAGE': 9, 'LOW_CONFIDENCE': 230, 'MISSING_AFTER_COST_EDGE': 572, 'MISSING_CONFIDENCE': 572, 'NON_DIRECTIONAL_ACTION': 198, 'NON_POSITIVE_AFTER_COST_EDGE': 202}`
- `paper_signal` rows `755`; confidence >= threshold `0`; positive edge `392`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.03361563`; reasons `{'LOW_CONFIDENCE': 755, 'MISSING_AFTER_COST_EDGE': 1, 'NON_DIRECTIONAL_ACTION': 338, 'NON_POSITIVE_AFTER_COST_EDGE': 362}`
- Prediction probe is readiness-only and does not participate in the actionable counterfactual pass gate.
- Prediction source kind counts: `{'prediction': 755}`
- Prediction readiness blockers: `['NO_A_GRADE_SIGNALS']`
- `prediction` rows `755`; confidence >= threshold `0`; positive edge `391`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; no feasible config `0`; reasons `{'LOW_CONFIDENCE': 755, 'NON_DIRECTIONAL_ACTION': 342, 'NON_POSITIVE_AFTER_COST_EDGE': 364}`

## Compounding Evidence

- Status: `NO_GO_COMPOUNDING_EVIDENCE_INSUFFICIENT`
- Closed outcomes: `103` / `300`; deficit `197`
- Accepted-fill reconciled closed outcomes: `16`
- Symbol diversity: `24` / `30`; deficit `6`
- Direction outcomes: long `44`, short `59`
- Positive deployed-margin return: `True`
- Counterfactual status: `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE`
- Counterfactual efficient frontier ready: `False`

## 1000x Classification

- Status: `UNSUPPORTED_CURRENT_EVIDENCE`
- Classification: `UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED`
- Horizon years: `5.0`
- Horizon days: `1825.0`
- Required CAGR: `2.981071705535`
- Required monthly return: `0.12201845`
- Required daily return: `0.00379224`
- Explicit horizon classification: `True`
- No guaranteed-return claim: `True`
- Dependency-gated by current evidence: `True`
- Current evidence supports feasibility status: `False`
- Guaranteed-return claim: `False`

## Safety

- No real orders, test orders, leverage mutation, margin-mode mutation, withdrawals, transfers, old Redis writes, legacy restart, or trainer bridge unmask are approved by this status.
- Any live canary remains a separate operator-approved phase.
