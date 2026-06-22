# V2_ADAPTIVE_CAPITAL_PRODUCTIVITY_COMPOUNDING_AND_1000X_FEASIBILITY GO/NO-GO

Generated UTC: `2026-06-22T00:23:05Z`

Overall status: **NO_GO**

## P0 Freeze

- Frozen P0 baseline: `True`
- P0 policy version: `PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1`
- P0 validator: `PASSED` at `2026-06-19T20:28:45Z`
- Live gate: `blocked_human_only`

## Remaining Blockers

- `capital_productivity_runtime_status`
- `one_thousand_x_feasibility_status`
- `out_of_sample_live_grade_reverify_status`

## Evidence To GO

- Closed outcomes needed: `0`; after current open positions close `0`
- Evidence acquisition status: `NO_GO_EVIDENCE_ACQUISITION_IN_PROGRESS`; observed rate `96.14594102` closed outcomes/day; ETA to 300 `1.20649919` days; ETA after current open positions close `1.20649919` days
- Runtime acquisition status: `NO_CURRENT_INTENTS`; current intents built `0`, accepted `0`, blocked `0`, stale `False`; safety real orders `False`, legacy Redis writes `False`
- Additional symbols needed: `0`
- A-grade replay evidence needed: `0`
- Counterfactual best configurations needed: `0`
- Selection attribution rows needed: `0`
- Leverage attribution rows needed: `0`
- Margin-mode attribution rows needed: `0`
- Hedge-budget attribution rows needed: `0`
- Closest A-grade confidence gap: `0.00012396`
- Closest A-grade edge gap bps: `0.0`
- Counterfactual configurations considered: `5462640` / `5462640`; reconciled `True`
- Counterfactual next evidence: `['CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME']`
- Strict A-grade acquisition burn-down: `PASSED`; confidence gap `0.00012396`; edge gap `0.0`; market-cost-ready near-A-grade `12037`; counts as gate `False`
- External audit blocker burn-down: `NO_GO_EXTERNAL_AUDIT_BLOCKERS_REMAIN`; remaining actions `['ACCUMULATE_AT_LEAST_300_POST_POLICY_CLOSED_OUTCOMES']`
- Live-grade reverify: `NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE`; blockers `['HOLDOUT_REVERIFY_NOT_PASSED', 'REALTIME_PAPER_REVERIFY_NOT_PASSED', 'MISSING_REALTIME_EXPECTANCY_FOR_REPLAY_COMPARISON']`

## Pass Conditions

- No fixed runtime size: `PASSED`
- No fixed runtime leverage: `PASSED`
- Adaptive capital selection attribution complete: `PASSED`
- 100% mandatory per-trade margin/leverage accounting: `PASSED`
- Policy activation timestamps and funding PnL accounted: `PASSED`
- Idle capital classification distinguishes no-edge and allocator underdeployment: `PASSED`
- Positive net return on deployed margin: `PASSED`
- Positive after-cost expectancy: `PASSED`
- Minimum post-allocator profit factor: `PASSED`
- Acceptable drawdown and expected shortfall: `PASSED`
- Rare-event capital stress passes: `PASSED`
- Counterfactual replay complete for A-grade signals: `PASSED`
- At least 300 post-policy or qualified replay economic outcomes: `PASSED`
- Both LONG and SHORT outcome evidence: `PASSED`
- Minimum post-policy or qualified replay symbol diversity: `PASSED`
- Paper/live pre-submit parity without exchange mutation: `PASSED`
- Frozen selector passes untouched holdout and realtime paper reverify: `NO_GO`
- No real order or exchange mutation: `PASSED`
- Compounding evidence passes: `PASSED`
- 1000x feasibility classified against explicit horizon without guarantee: `PASSED`

## Capital Productivity

- Status: `NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE`
- Closed post-allocator outcomes: `184` / `300`; deficit `116`
- Closed outcome progress: `0.61333333`; projected after open positions close `184` / `300`; projected deficit `116`
- Evidence acquisition window: `2026-06-20T01:06:12Z` to `2026-06-21T22:47:02Z` over `1.90335648` days; latest close age `1.60083333` hours; timed closed outcomes `184`
- Closed outcome evidence funnel: raw `1645`, P0 closed `669`, adaptive-policy closed `203`, complete `184`
- Unversioned complete P0 closed rows: `1`; potential complete outcomes after safe lineage `185`; remaining need `115`
- Symbol diversity progress: `30` / `30`; deficit `0`
- Potential symbol count after safe unversioned lineage: `30`; remaining symbol need `0`
- Current closed symbols sample: `['AEROUSDT', 'AVNTUSDT', 'BEATUSDT', 'BSBUSDT', 'CHZUSDT', 'CRVUSDT', 'EIGENUSDT', 'ENAUSDT', 'EPICUSDT', 'FETUSDT', 'FILUSDT', 'HEIUSDT', 'HUSDT', 'HYPEUSDT', 'INJUSDT', 'IPUSDT', 'JTOUSDT', 'LABUSDT', 'MEGAUSDT', 'NEARUSDT', 'ONDOUSDT', 'OPGUSDT', 'OPUSDT', 'POLUSDT', 'RIVERUSDT', 'SUIUSDT', 'TAOUSDT', 'TRXUSDT', 'XLMUSDT', 'XPLUSDT']`
- Open-ready new symbols not yet counted: `0`; sample `[]`
- Signal/prediction universe symbols without closed outcomes: `121`; sample `['1000BONKUSDT', '1000FLOKIUSDT', '1000LUNCUSDT', '1000PEPEUSDT', '1000SHIBUSDT', '1INCHUSDT', 'AAVEUSDT', 'ADAUSDT', 'ALGOUSDT', 'ALICEUSDT', 'ALLOUSDT', 'APTUSDT', 'ARBUSDT', 'ARUSDT', 'ASRUSDT', 'ASTERUSDT', 'ATOMUSDT', 'AUCTIONUSDT', 'AVAXUSDT', 'AXLUSDT', 'BABYUSDT', 'BANANAS31USDT', 'BANKUSDT', 'BARDUSDT', 'BCHUSDT', 'BILLUSDT', 'BIOUSDT', 'BNBUSDT', 'BTCUSDT', 'CAKEUSDT']`
- Positive-edge candidate symbols without closed outcomes: `95`; sample `['1000BONKUSDT', '1000LUNCUSDT', '1000PEPEUSDT', '1000SHIBUSDT', '1INCHUSDT', 'ADAUSDT', 'ALGOUSDT', 'ALICEUSDT', 'ALLOUSDT', 'APTUSDT', 'ARBUSDT', 'ARUSDT', 'ASRUSDT', 'ASTERUSDT', 'ATOMUSDT', 'AVAXUSDT', 'AXLUSDT', 'BABYUSDT', 'BANANAS31USDT', 'BANKUSDT', 'BARDUSDT', 'BIOUSDT', 'CELRUSDT', 'CHIPUSDT', 'COAIUSDT', 'DASHUSDT', 'DEXEUSDT', 'DOTUSDT', 'ENJUSDT', 'ESPORTSUSDT']`
- Near-A-grade candidate symbols without closed outcomes: `6`; sample `['ALICEUSDT', 'HBARUSDT', 'MONUSDT', 'PENGUUSDT', 'SOLUSDT', 'UNIUSDT']`
- Potential symbol count if open-ready and positive-edge candidates close: `125`; remaining need `0`
- Symbol diversity gate note: `Only complete post-policy closed outcomes count toward symbol diversity. Open positions and signal/prediction candidates are burn-down leads, not pass evidence.`
- Candidate `paper_signal` `SOLUSDT` `1h` `short`: confidence `0.68863012`, edge `10.72099495` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `prediction` `SOLUSDT` `1h` `short`: confidence `0.68863012`, edge `10.72099495` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `paper_signal` `UNIUSDT` `5m` `short`: confidence `0.68728914`, edge `7.85722637` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `prediction` `UNIUSDT` `5m` `short`: confidence `0.68728914`, edge `7.85722637` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `paper_signal` `PENGUUSDT` `15m` `short`: confidence `0.67403602`, edge `18.85903358` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Accepted-fill reconciled closed outcomes: `0`
- Post-allocator realized PnL: `106.12734377`
- Closed deployed margin: `89601.81755461`
- Return on deployed margin: `0.00118443`
- Break-even realized PnL gap: `0.0`; return gap to zero `0.0`
- After-cost expectancy bps: `29.01185251`
- Profit factor: `1.35487206` vs minimum `1.176`; status `PASSED`; win rate `0.28804348`; gross profit/loss `405.18538345` / `299.05803968`
- Profit factor burn-down: additional gross profit needed `0.0` assuming no added gross loss; target gross profit `351.69225466`; cohort `184` / `300`; sample status `NO_GO_PROFIT_FACTOR_COHORT_BELOW_300_OUTCOMES`

## Adaptive Field Selection

- Selection attribution status: `PASSED`
- Selection attribution blockers: `[]`
- Complete selection model-input coverage: `0.84236453` from `171` / `203` rows
- Selection attribution missing counts: `{'leverage_selection_model_input': 32, 'margin_mode_selection_model_input': 32, 'hedge_budget_selection_model_input': 32, 'complete_selection_model_input': 32}`
- Required selection field coverage: `0.90640394` from `203` rows
- Current pre-submit field coverage: `0.0` from `0` rows
- Runtime leverage model-input coverage: `0.84236453`
- Runtime margin-mode model-input coverage: `0.84236453`
- Runtime hedge-budget model-input coverage: `0.84236453`
- Gross notional unique count: `154`
- Current pre-submit gross notional unique count: `0`
- Allocated margin unique count: `164`
- Current pre-submit allocated margin unique count: `0`
- Effective leverage values: `[1.0, 2.0]`
- Current pre-submit effective leverage values: `[]`
- Recommended margin modes: `['isolated_paper_simulated']`
- Current pre-submit margin modes: `[]`
- Margin-mode selection reason counts: `{'__missing__': 32, 'isolated_limits_tail_contagion_for_current_risk': 171}`
- Current pre-submit margin-mode reason counts: `{}`
- Hedge-budget values sample: `[0.0, 0.00017689, 0.00091825, 0.00207746, 0.00340907, 0.00892842, 0.00951379, 0.01413748, 0.0158134, 0.0192227, 0.02145652, 0.02153993, 0.0224824, 0.02267336, 0.03557855, 0.03977375, 0.04298607, 0.04704191, 0.04724249, 0.04734461]`
- Current pre-submit hedge-budget values sample: `[]`
- Hedge-budget selection reason counts: `{'__missing__': 32, 'correlation_drawdown_volatility_cost_pressure': 120, 'hedge_budget_not_required_for_current_risk': 51}`
- Current pre-submit hedge-budget reason counts: `{}`

## Allocator Calibration

- Status: `READY`
- Gap reasons: `[]`
- Policy rows: `441`; liquidity adjustments `[0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0]`; liquidity scores `[0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0]`
- Policy regime adjustments `[0.2, 0.75, 1.0]`; regime scores `[0.2, 0.75, 1.0]`
- Current intent observation: `NO_CURRENT_INTENT_CALIBRATION_OBSERVED` from `0` versioned intents; sized `0`, blocked `0`
- Current intent liquidity adjustments `[]`; liquidity scores `[]`
- Current intent regime adjustments `[]`; regime scores `[]`
- Current intent counts as policy outcome gate: `False`

## Policy Activation And Funding

- Status: `PASSED`
- Blocker reasons: `[]`
- Policy activation timestamp coverage: `441` / `441`; missing `0`
- Funding PnL accounted closed outcomes: `202` / `203`; unaccounted `1`; nonzero `52`
- Funding PnL reconstruction diagnostic: `NO_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC`; reconstructable `0`; total `0.0`; counts as accounted `False`
- Forward funding accounting contract: `READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT`; ready `238` / `238` accepted/open rows; missing `{}`; counts as closed-outcome gate `False`
- Funding PnL source counts: `{'FUNDING_RATE': 202, '__missing__': 1}`
- Funding PnL accounting versions: `{'PAPER_FUNDING_ACCRUAL_V1': 202, '__missing__': 1}`; statuses `{'READY_FUNDING_PNL_ACCRUED': 202, '__missing__': 1}`
- Named order counter status: `READY`; missing `[]`; live orders `0.0`, test orders `0.0`, exchange mutations `0.0`
- External audit policy/funding counters: policy timestamps `441` / `441`; funding accounted `202` with unaccounted `1`; named counters `READY`
- External audit calibration/liquidation: calibration `READY` gaps `[]`; liquidation buffer verified `True`

## PnL History

- `1d` PnL: `88.48565205` from `86` closed trades; win rate `0.25581395`, profit factor `1.62774542`
- `7d` PnL: `195.34615974` from `1645` closed trades; win rate `0.29908815`, profit factor `1.25209776`
- `30d` PnL: `195.34615974` from `1645` closed trades; win rate `0.29908815`, profit factor `1.25209776`

## Signal/Prediction Accuracy

- Status: `READY`
- Overall accuracy: `0.29981718` from `1641` evaluated rows
- Symbol universe count: `151`
- Required symbol/timeframe cells without evaluated outcomes: `452`
- `1m` accuracy: `0.28030303` from `264` evaluated rows; PnL `4.13047021`
- `5m` accuracy: `0.31343284` from `201` evaluated rows; PnL `4.98282854`
- `15m` accuracy: `0.29142857` from `350` evaluated rows; PnL `-26.10537168`
- `1h` accuracy: `0.31197302` from `593` evaluated rows; PnL `202.99534988`
- `4h` accuracy: `0.29184549` from `233` evaluated rows; PnL `10.12001621`

## Dashboard/Web Visibility

- Status: `READY`
- Required PnL windows published: `True`; windows `['1d', '7d', '30d']`
- All symbol/timeframe accuracy cells published: `True`
- Accuracy cells published/evaluated/missing evaluated: `755` / `303` / `452`
- Web surface count: `16`
- All tracked surfaces show capital productivity status: `True`
- All tracked surfaces show 1D/1W/30D PnL windows: `True`
- All tracked surfaces show signal/prediction accuracy: `True`
- All tracked surfaces show all symbol/TF accuracy matrix: `True`
- Row-level accuracy/PnL surface count: `3`
- `dashboard` `/dashboard`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `signals` `/signals`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `True`
- `ai_predictions` `/ai-predictions`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `True`
- `trainer_prediction_monitor` `/admin/trainer-prediction-monitor`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `True`
- `trainer_admin` `/admin/trainer-admin`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `signal_explainability` `/admin/signal-explainability`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `history` `/history`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `positions` `/positions`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `paper_trading` `/admin/paper-trading`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `executions` `/admin/executions`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `trade_terminal` `/trade`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `binance_terminal` `/binance`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `mission_control` `/admin/mission-control`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `operator_proof_dashboard` `/admin/evidence`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `market_intelligence` `/research`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`
- `technical_analysis` `/admin/technical-analysis`: capital `True`, PnL windows `True`, accuracy `True`, all symbol/TF matrix `True`, row accuracy/PnL `False`

## Out-of-Sample Live-Grade Reverify

- Status: `NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE`
- Gate ID: `V2_ADAPTIVE_CAPITAL_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY`
- Honest interpretation: `{'adaptive_capital_replay_gate': 'PASS', 'broad_model_edge': 'NOT_PROVEN', 'out_of_sample_generalization': 'NOT_PROVEN', 'one_thousand_x_trajectory': 'NOT_PROVEN', 'live_readiness': 'blocked_human_only', 'live_grade_profitability': 'NOT_PROVEN'}`
- Frozen selector fingerprint: `c4b8fb1ed12aabcb87224723f1758563eefff10de90288be09866d2bf3fa74b5`
- Holdout status: `NO_GO_HOLDOUT_REVERIFY_INCOMPLETE`; valid rows `0` / required `100`; symbols `0` / `30`; PF `None`; expectancy `None` bps
- Realtime paper status: `NO_GO_REALTIME_REVERIFY_INCOMPLETE`; valid rows `0` / required `100`; symbols `0` / `30`; PF `None`; expectancy `None` bps
- Realtime vs replay projection: `NO_GO_REPLAY_REALTIME_COMPARISON_INCOMPLETE`; replay expectancy `41.76153327` bps; realtime expectancy `None` bps; blockers `['MISSING_REALTIME_EXPECTANCY_FOR_REPLAY_COMPARISON']`
- Holdout source: `/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/v2_adaptive_capital_productivity/latest/out_of_sample_holdout_reverify_rows.jsonl` exists `True`
- Realtime source: `/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/v2_adaptive_capital_productivity/latest/out_of_sample_realtime_paper_reverify_rows.jsonl` exists `True`

## Stop-Waiting A-grade Calibration Phase

- Phase status: `V2_STOP_WAITING_A_GRADE_CALIBRATION_ACCELERATED_REPLAY_AND_CAPITAL_DEPLOYMENT_BLOCKED`
- Phase blockers: `['OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_NOT_PASSED']`
- Dynamic calibration: `PASSED`; blockers `[]`
- Evaluated outcome buckets: `5` eligible / `2162` total from `21445` evaluated outcomes
- Dynamic A-grade candidates: `229`; strict candidates `10116`; positive-edge candidates `14023`
- Positive-edge resolution: `READY_EXPLORATION_TIERS_ASSIGNED`; counts `{'A_GRADE_EXECUTION_PAPER': 229, 'B_GRADE_EXPLORATION_PAPER': 13545, 'NO_TRADE': 6532, 'SHADOW_ONLY': 249}`
- B-grade exploration candidates: `13545`; fixed dollar budget used `False`
- Accelerated replay: `PASSED`; replayed economic candidates `19800` / `10000`; symbols `90` / `50`; blockers `[]`
- Efficient frontier: `PASSED`; best configs `10116`; sweep results `3327120`
- Fast evidence gate: `{'minimum_replay_outcomes': 10000, 'replayed_economic_candidate_count': 19800, 'minimum_replay_symbols': 50, 'replay_symbol_count': 90, 'replay_symbol_diversity_pass': True, 'minimum_realtime_paper_economic_outcomes': 100, 'realtime_paper_economic_outcome_count': 184, 'minimum_realtime_paper_symbols': 30, 'realtime_paper_symbol_count': 30, 'realtime_symbol_diversity_pass': True, 'phase_symbol_diversity_pass': True, 'phase_symbol_diversity_basis': 'realtime_paper', 'realtime_symbol_diversity_still_counts_for_operator_go': False, 'minimum_realtime_long_closes': 25, 'realtime_long_close_count': 76, 'minimum_realtime_short_closes': 25, 'realtime_short_close_count': 108, 'positive_replay_expectancy_after_cost': True, 'positive_realtime_expectancy_after_cost': True, 'capital_deployment_reconciliation_pass': True, 'rare_event_stress_pass': True}`

## Counterfactual Sweep

- Status: `PASSED`
- Blocker reasons: `[]`
- Next evidence gaps: `['CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME']`
- A-grade signal gap count: `0`; best configuration gap count `0`
- Strict A-grade acquisition burn-down: `PASSED`; historical strict signals `10116`; event-time-valid `10116`; best configs `10116`; required next evidence `['CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME']`
- Closest `closed_candle_replay` `CHIPUSDT` `1m` `short`: confidence `0.74987604` gap `0.00012396`, edge `63.79816607` bps, reasons `['LOW_CONFIDENCE']`, market-cost `None`
- Closest `closed_candle_replay` `CHIPUSDT` `1m` `long`: confidence `0.74987604` gap `0.00012396`, edge `20.83352953` bps, reasons `['LOW_CONFIDENCE']`, market-cost `None`
- Closest `closed_candle_replay` `LITUSDT` `5m` `short`: confidence `0.7498229` gap `0.0001771`, edge `52.12053434` bps, reasons `['LOW_CONFIDENCE']`, market-cost `None`
- Closest `closed_candle_replay` `LITUSDT` `5m` `long`: confidence `0.7498229` gap `0.0001771`, edge `5.39445748` bps, reasons `['LOW_CONFIDENCE']`, market-cost `None`
- Closest `closed_candle_replay` `NEOUSDT` `1h` `short`: confidence `0.74977895` gap `0.00022105`, edge `52.07981007` bps, reasons `['LOW_CONFIDENCE']`, market-cost `None`
- A-grade blocker analysis: `NO_GO_A_GRADE_INTERSECTION_INCOMPLETE`; blockers `['NO_STRICT_A_GRADE_INTERSECTION', 'POSITIVE_EDGE_ROWS_BELOW_CONFIDENCE_THRESHOLD']`
- A-grade intersection counts: confidence >= threshold `0`, positive edge `718`, both `0`, blocked-both `0`, strict before temporal `0`, event-time-valid `0`
- A-grade blocker reason counts: `{'LOW_CONFIDENCE': 990, 'MISSING_AFTER_COST_EDGE': 480, 'MISSING_CONFIDENCE': 479, 'NON_DIRECTIONAL_ACTION': 254, 'NON_POSITIVE_AFTER_COST_EDGE': 271}`
- A-grade blocker `paper_signal` `SOLUSDT` `1h` `short`: confidence `0.68863012`, edge `10.72099495` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `UNIUSDT` `5m` `short`: confidence `0.68728914`, edge `7.85722637` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `PENGUUSDT` `15m` `short`: confidence `0.67403602`, edge `18.85903358` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `UNIUSDT` `1h` `short`: confidence `0.67403602`, edge `10.91474152` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `SOLUSDT` `1m` `long`: confidence `0.67403602`, edge `5.68947983` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `UNIUSDT` `15m` `short`: confidence `0.67403602`, edge `5.01949501` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Near-A-grade explicit market-cost evidence: `12037` / `12051`; missing `{'MISSING_ACTUAL_SPREAD': 12, 'MISSING_FEES': 12, 'MISSING_FUNDING': 12, 'MISSING_MARKET_DEPTH': 14, 'MISSING_SLIPPAGE': 12}`; PIT rejects `{'FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME': 8, 'FEATURE_CUTOFF_AFTER_DECISION_TIME': 4, 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME': 8, 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE': 8, 'MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE': 4}`
- Counterfactual evidence acquisition: `PASSED`; blockers `['POSITIVE_EDGE_BELOW_CONFIDENCE_THRESHOLD']`; strict gate relaxed `False`
- Market-cost-ready near-A-grade candidates if confidence improves: `12037`; capture-required near-A-grade candidates `14`
- Ready `OPUSDT` `1h` `short`: decision `2026-06-20T09:38:11Z`, snapshot `v2_fsnap_c8433f2ddf5a1bbb4642f2d2148ab9a6a99393fed097a498a8dc3883eec5b199`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `OPUSDT` `1h` `short`: decision `2026-06-20T10:13:53Z`, snapshot `v2_fsnap_10508d4d25b25ceeccbddb6823f028442e2b253d0ffe4acca493b514eae3be68`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `JTOUSDT` `15m` `short`: decision `2026-06-20T15:49:02Z`, snapshot `v2_fsnap_866662e911fa049ba7c61fbff197382df8fde60757b594f980b27e371f7bffb5`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `ONDOUSDT` `1h` `long`: decision `2026-06-20T16:55:08Z`, snapshot `v2_fsnap_682c9eef1ffe04088b34766cd2394bdfdf1abcdaff6d108c7c8ca4588996f129`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `OPUSDT` `1h` `long`: decision `2026-06-20T17:33:39Z`, snapshot `v2_fsnap_9abe966c636fc345228895103fafa3f3215c8d0bbdf4ea8b6a6b7b364308f311`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Capture `UNIUSDT` `15m` `short`: decision `2026-06-21T16:13:18-04:00`, snapshot `v2_fsnap_27b5e0f3c535da07122018920da87db3c696a01a1f56a575f77e1e3cfd8a9885`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_CUTOFF_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `UNIUSDT` `1h` `short`: decision `2026-06-21T16:13:18-04:00`, snapshot `v2_fsnap_3e98c133c3514129b75b4f11773f2cbcff82e21a8b8e8312814d741e5c8df946`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `SOLUSDT` `1h` `short`: decision `2026-06-21T16:07:31Z`, snapshot `v2_fsnap_e0250e7f17e4e984f5216a3a2231cfffaed16e8e4585b2b5fa9cc77d1e7c50f2`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `ALICEUSDT` `1h` `short`: decision `2026-06-21T20:12:20Z`, snapshot `v2_fsnap_255292ca285266098b8632ebd95978c3a598306702ade0ec634440644e78984c`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `PENGUUSDT` `15m` `short`: decision `2026-06-21T16:07:22Z`, snapshot `v2_fsnap_e9e910edb0ef4f167c8c2ae086eb5ea714f53b04a0740edf0fbf55276323cd3e`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_CUTOFF_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Near-A-grade pruned configuration reasons: `{'LIQUIDATION_PROBABILITY_LIMIT_BREACH': 2227560, 'MISSING_MARKET_DEPTH': 5400}`
- Source coverage: `PASSED` at `1.0`
- Durable accepted counterfactual rows: `238` from `4481` accepted candidates; bounded to current source cells `True`; excluded `{'NOT_ADAPTIVE_CAPITAL_POLICY_ROW': 4243}`
- Required symbol/timeframe cells: `770` / `770`; missing `0`
- Exact feature snapshot lookup: `NO_GO_EXACT_FEATURE_SNAPSHOT_GAPS`; requested `764`, available `281`, archived `281`, missing `483`
- A-grade signals: `10116`
- Prediction rows probed: `755`; probe status `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE`; participates in pass gate `False`
- Near-A-grade probe status: `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE` at confidence threshold `0.65`; best configs `12037`; participates in pass gate `False`
- Near-A-grade temporal-invalid count: `4`
- A-grade replay progress: `1.0`; deficit `0`
- Configuration-space reconciliation: `True`
- Event-time-valid candidates: `10116`
- Best configurations: `10116`
- Market depth requirement: `required_actual_depth_usd_or_orderbook_levels`
- Market cost requirement: `required_explicit_spread_slippage_fee_funding_bps_or_usd`
- Market cost evidence coverage: `PASSED` with `10116` / `10116` complete A-grade candidates; missing `{}`
- Prediction market cost evidence coverage: `NO_CANDIDATES` with `0` / `0` complete candidates; missing `{}`
- Near-A-grade market cost evidence coverage: `NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE` with `12037` / `12051` complete candidates; missing `{'MISSING_ACTUAL_SPREAD': 12, 'MISSING_FEES': 12, 'MISSING_FUNDING': 12, 'MISSING_MARKET_DEPTH': 14, 'MISSING_SLIPPAGE': 12}`

## A-grade Readiness

- Confidence threshold: `0.75`
- After-cost edge threshold bps: `0.0`
- Source kind counts: `{'closed_candle_replay': 19800, 'paper_ledger': 669, 'paper_ledger_accepted': 238, 'paper_signal': 755}`
- Readiness blockers: `[]`
- `closed_candle_replay` rows `19800`; confidence >= threshold `13842`; positive edge `13540`; A-grade before temporal `10116`; event-time-valid `10116`; best configs `10116`; confidence gap `0.0`; reasons `{'LOW_CONFIDENCE': 5958, 'NON_POSITIVE_AFTER_COST_EDGE': 6260}`
- `paper_ledger` rows `669`; confidence >= threshold `0`; positive edge `63`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `None`; reasons `{'MISSING_AFTER_COST_EDGE': 606, 'MISSING_CONFIDENCE': 669}`
- `paper_ledger_accepted` rows `238`; confidence >= threshold `0`; positive edge `238`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.09021926`; reasons `{'LOW_CONFIDENCE': 238}`
- `paper_signal` rows `755`; confidence >= threshold `0`; positive edge `483`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.001993`; reasons `{'LOW_CONFIDENCE': 755, 'MISSING_AFTER_COST_EDGE': 1, 'NON_DIRECTIONAL_ACTION': 254, 'NON_POSITIVE_AFTER_COST_EDGE': 271}`
- Prediction probe is readiness-only and does not participate in the actionable counterfactual pass gate.
- Prediction source kind counts: `{'prediction': 755}`
- Prediction readiness blockers: `['NO_A_GRADE_SIGNALS']`
- `prediction` rows `755`; confidence >= threshold `0`; positive edge `469`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; no feasible config `0`; reasons `{'LOW_CONFIDENCE': 755, 'NON_DIRECTIONAL_ACTION': 271, 'NON_POSITIVE_AFTER_COST_EDGE': 286}`

## Compounding Evidence

- Status: `PASSED`
- Closed outcomes: `184` / `300`; deficit `116`
- Accepted-fill reconciled closed outcomes: `0`
- Symbol diversity: `30` / `30`; deficit `0`
- Direction outcomes: long `76`, short `108`
- Positive deployed-margin return: `True`
- Counterfactual status: `PASSED`
- Counterfactual efficient frontier ready: `True`

## 1000x Classification

- Status: `NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY`
- Classification: `FEASIBLE_ON_CURRENT_WINDOW_PROJECTION_UNVERIFIED`
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
