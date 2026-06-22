# V2_ADAPTIVE_CAPITAL_PRODUCTIVITY_COMPOUNDING_AND_1000X_FEASIBILITY GO/NO-GO

Generated UTC: `2026-06-21T19:58:34Z`

Overall status: **PASSED**

## P0 Freeze

- Frozen P0 baseline: `True`
- P0 policy version: `PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1`
- P0 validator: `PASSED` at `2026-06-19T20:28:45Z`
- Live gate: `blocked_human_only`

## Remaining Blockers


## Evidence To GO

- Closed outcomes needed: `0`; after current open positions close `0`
- Evidence acquisition status: `NO_GO_EVIDENCE_ACQUISITION_IN_PROGRESS`; observed rate `97.57325978` closed outcomes/day; ETA to 300 `1.28108869` days; ETA after current open positions close `1.22984515` days
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
- No real order or exchange mutation: `PASSED`
- Compounding evidence passes: `PASSED`
- 1000x feasibility classified against explicit horizon without guarantee: `PASSED`

## Capital Productivity

- Status: `PASSED`
- Closed post-allocator outcomes: `175` / `300`; deficit `125`
- Closed outcome progress: `0.58333333`; projected after open positions close `180` / `300`; projected deficit `120`
- Evidence acquisition window: `2026-06-20T01:06:12Z` to `2026-06-21T19:54:07Z` over `1.78327546` days; latest close age `0.07416667` hours; timed closed outcomes `175`
- Closed outcome evidence funnel: raw `1636`, P0 closed `660`, adaptive-policy closed `194`, complete `175`
- Unversioned complete P0 closed rows: `1`; potential complete outcomes after safe lineage `176`; remaining need `124`
- Symbol diversity progress: `29` / `30`; deficit `1`
- Potential symbol count after safe unversioned lineage: `29`; remaining symbol need `1`
- Current closed symbols sample: `['AEROUSDT', 'AVNTUSDT', 'BEATUSDT', 'BSBUSDT', 'CRVUSDT', 'EIGENUSDT', 'ENAUSDT', 'EPICUSDT', 'FETUSDT', 'FILUSDT', 'HEIUSDT', 'HUSDT', 'HYPEUSDT', 'INJUSDT', 'IPUSDT', 'JTOUSDT', 'LABUSDT', 'MEGAUSDT', 'NEARUSDT', 'ONDOUSDT', 'OPGUSDT', 'OPUSDT', 'POLUSDT', 'RIVERUSDT', 'SUIUSDT', 'TAOUSDT', 'TRXUSDT', 'XLMUSDT', 'XPLUSDT']`
- Open-ready new symbols not yet counted: `1`; sample `['CHZUSDT']`
- Signal/prediction universe symbols without closed outcomes: `122`; sample `['1000BONKUSDT', '1000FLOKIUSDT', '1000LUNCUSDT', '1000PEPEUSDT', '1000SHIBUSDT', '1INCHUSDT', 'AAVEUSDT', 'ADAUSDT', 'ALGOUSDT', 'ALICEUSDT', 'ALLOUSDT', 'APTUSDT', 'ARBUSDT', 'ARUSDT', 'ASRUSDT', 'ASTERUSDT', 'ATOMUSDT', 'AUCTIONUSDT', 'AVAXUSDT', 'AXLUSDT', 'BABYUSDT', 'BANANAS31USDT', 'BANKUSDT', 'BARDUSDT', 'BCHUSDT', 'BILLUSDT', 'BIOUSDT', 'BNBUSDT', 'BTCUSDT', 'CAKEUSDT']`
- Positive-edge candidate symbols without closed outcomes: `95`; sample `['1000BONKUSDT', '1000FLOKIUSDT', '1000LUNCUSDT', '1000PEPEUSDT', '1000SHIBUSDT', '1INCHUSDT', 'AAVEUSDT', 'ADAUSDT', 'ALGOUSDT', 'ARBUSDT', 'ARUSDT', 'ASRUSDT', 'ASTERUSDT', 'ATOMUSDT', 'AUCTIONUSDT', 'AVAXUSDT', 'AXLUSDT', 'BABYUSDT', 'BANANAS31USDT', 'BANKUSDT', 'BARDUSDT', 'BCHUSDT', 'BIOUSDT', 'BNBUSDT', 'CELRUSDT', 'CHIPUSDT', 'CHZUSDT', 'COAIUSDT', 'DASHUSDT', 'DEXEUSDT']`
- Near-A-grade candidate symbols without closed outcomes: `7`; sample `['AAVEUSDT', 'ADAUSDT', 'HBARUSDT', 'ICPUSDT', 'MONUSDT', 'PENGUUSDT', 'SOLUSDT']`
- Potential symbol count if open-ready and positive-edge candidates close: `124`; remaining need `0`
- Symbol diversity gate note: `Only complete post-policy closed outcomes count toward symbol diversity. Open positions and signal/prediction candidates are burn-down leads, not pass evidence.`
- Candidate `paper_signal` `SOLUSDT` `5m` `short`: confidence `0.70367631`, edge `3.38975334` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `prediction` `SOLUSDT` `5m` `short`: confidence `0.70367631`, edge `3.38975334` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `paper_signal` `SOLUSDT` `15m` `short`: confidence `0.68869667`, edge `7.09703636` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `prediction` `SOLUSDT` `15m` `short`: confidence `0.68869667`, edge `7.09703636` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Candidate `paper_signal` `SOLUSDT` `1h` `short`: confidence `0.68863012`, edge `10.72099495` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Accepted-fill reconciled closed outcomes: `0`
- Post-allocator realized PnL: `104.96812774`
- Closed deployed margin: `88326.29583064`
- Return on deployed margin: `0.00118841`
- Break-even realized PnL gap: `0.0`; return gap to zero `0.0`
- After-cost expectancy bps: `22.73592138`
- Profit factor: `1.35400543` vs minimum `1.176`; status `PASSED`; win rate `0.28`; gross profit/loss `401.48371763` / `296.51558989`
- Profit factor burn-down: additional gross profit needed `0.0` assuming no added gross loss; target gross profit `348.70233371`; cohort `175` / `300`; sample status `NO_GO_PROFIT_FACTOR_COHORT_BELOW_300_OUTCOMES`

## Adaptive Field Selection

- Selection attribution status: `PASSED`
- Selection attribution blockers: `[]`
- Complete selection model-input coverage: `0.83919598` from `167` / `199` rows
- Selection attribution missing counts: `{'leverage_selection_model_input': 32, 'margin_mode_selection_model_input': 32, 'hedge_budget_selection_model_input': 32, 'complete_selection_model_input': 32}`
- Required selection field coverage: `0.90452261` from `199` rows
- Current pre-submit field coverage: `0.0` from `0` rows
- Runtime leverage model-input coverage: `0.83919598`
- Runtime margin-mode model-input coverage: `0.83919598`
- Runtime hedge-budget model-input coverage: `0.83919598`
- Gross notional unique count: `150`
- Current pre-submit gross notional unique count: `0`
- Allocated margin unique count: `160`
- Current pre-submit allocated margin unique count: `0`
- Effective leverage values: `[1.0, 2.0]`
- Current pre-submit effective leverage values: `[]`
- Recommended margin modes: `['isolated_paper_simulated']`
- Current pre-submit margin modes: `[]`
- Margin-mode selection reason counts: `{'__missing__': 32, 'isolated_limits_tail_contagion_for_current_risk': 167}`
- Current pre-submit margin-mode reason counts: `{}`
- Hedge-budget values sample: `[0.0, 0.00091825, 0.00340907, 0.00892842, 0.00951379, 0.0158134, 0.0192227, 0.02145652, 0.02153993, 0.0224824, 0.02267336, 0.03557855, 0.03977375, 0.04298607, 0.04704191, 0.04724249, 0.04734461, 0.04806386, 0.04808815, 0.04886567]`
- Current pre-submit hedge-budget values sample: `[]`
- Hedge-budget selection reason counts: `{'__missing__': 32, 'correlation_drawdown_volatility_cost_pressure': 116, 'hedge_budget_not_required_for_current_risk': 51}`
- Current pre-submit hedge-budget reason counts: `{}`

## Allocator Calibration

- Status: `READY`
- Gap reasons: `[]`
- Policy rows: `432`; liquidity adjustments `[0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0]`; liquidity scores `[0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0]`
- Policy regime adjustments `[0.75, 1.0]`; regime scores `[0.75, 1.0]`
- Current intent observation: `READY_CURRENT_INTENT_CALIBRATION_OBSERVED` from `250` versioned intents; sized `0`, blocked `250`
- Current intent liquidity adjustments `[0.2, 0.35, 0.5, 0.65, 0.78173737, 0.8, 0.8254411, 0.83731813, 0.9, 0.91302614]`; liquidity scores `[0.2, 0.35, 0.5, 0.65, 0.78173737, 0.8, 0.8254411, 0.83731813, 0.9, 0.91302614]`
- Current intent regime adjustments `[0.2]`; regime scores `[0.2]`
- Current intent counts as policy outcome gate: `False`

## Policy Activation And Funding

- Status: `PASSED`
- Blocker reasons: `[]`
- Policy activation timestamp coverage: `432` / `432`; missing `0`
- Funding PnL accounted closed outcomes: `193` / `194`; unaccounted `1`; nonzero `44`
- Funding PnL reconstruction diagnostic: `NO_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC`; reconstructable `0`; total `0.0`; counts as accounted `False`
- Forward funding accounting contract: `READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT`; ready `238` / `238` accepted/open rows; missing `{}`; counts as closed-outcome gate `False`
- Funding PnL source counts: `{'FUNDING_RATE': 193, '__missing__': 1}`
- Funding PnL accounting versions: `{'PAPER_FUNDING_ACCRUAL_V1': 193, '__missing__': 1}`; statuses `{'READY_FUNDING_PNL_ACCRUED': 193, '__missing__': 1}`
- Named order counter status: `READY`; missing `[]`; live orders `0.0`, test orders `0.0`, exchange mutations `0.0`
- External audit policy/funding counters: policy timestamps `432` / `432`; funding accounted `193` with unaccounted `1`; named counters `READY`
- External audit calibration/liquidation: calibration `READY` gaps `[]`; liquidation buffer verified `True`

## PnL History

- `1d` PnL: `84.38529994` from `87` closed trades; win rate `0.24137931`, profit factor `1.57307171`
- `7d` PnL: `194.18694372` from `1636` closed trades; win rate `0.29828851`, profit factor `1.25142673`
- `30d` PnL: `194.18694372` from `1636` closed trades; win rate `0.29828851`, profit factor `1.25142673`

## Signal/Prediction Accuracy

- Status: `READY`
- Overall accuracy: `0.29901961` from `1632` evaluated rows
- Symbol universe count: `151`
- Required symbol/timeframe cells without evaluated outcomes: `452`
- `1m` accuracy: `0.27586207` from `261` evaluated rows; PnL `1.56988024`
- `5m` accuracy: `0.31` from `200` evaluated rows; PnL `4.07161214`
- `15m` accuracy: `0.28939828` from `349` evaluated rows; PnL `-26.17128291`
- `1h` accuracy: `0.31197302` from `593` evaluated rows; PnL `202.99534988`
- `4h` accuracy: `0.29694323` from `229` evaluated rows; PnL `12.49851777`

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

## Stop-Waiting A-grade Calibration Phase

- Phase status: `V2_STOP_WAITING_A_GRADE_CALIBRATION_ACCELERATED_REPLAY_AND_CAPITAL_DEPLOYMENT_READY`
- Phase blockers: `[]`
- Dynamic calibration: `PASSED`; blockers `[]`
- Evaluated outcome buckets: `5` eligible / `2157` total from `21436` evaluated outcomes
- Dynamic A-grade candidates: `229`; strict candidates `10116`; positive-edge candidates `13961`
- Positive-edge resolution: `READY_EXPLORATION_TIERS_ASSIGNED`; counts `{'A_GRADE_EXECUTION_PAPER': 229, 'B_GRADE_EXPLORATION_PAPER': 13575, 'NO_TRADE': 6844, 'SHADOW_ONLY': 157}`
- B-grade exploration candidates: `13575`; fixed dollar budget used `False`
- Accelerated replay: `PASSED`; replayed economic candidates `19800` / `10000`; symbols `90` / `50`; blockers `[]`
- Efficient frontier: `PASSED`; best configs `10116`; sweep results `3327120`
- Fast evidence gate: `{'minimum_replay_outcomes': 10000, 'replayed_economic_candidate_count': 19800, 'minimum_replay_symbols': 50, 'replay_symbol_count': 90, 'replay_symbol_diversity_pass': True, 'minimum_realtime_paper_economic_outcomes': 100, 'realtime_paper_economic_outcome_count': 175, 'minimum_realtime_paper_symbols': 30, 'realtime_paper_symbol_count': 29, 'realtime_symbol_diversity_pass': False, 'phase_symbol_diversity_pass': True, 'phase_symbol_diversity_basis': 'accelerated_replay', 'realtime_symbol_diversity_still_counts_for_operator_go': True, 'minimum_realtime_long_closes': 25, 'realtime_long_close_count': 71, 'minimum_realtime_short_closes': 25, 'realtime_short_close_count': 104, 'positive_replay_expectancy_after_cost': True, 'positive_realtime_expectancy_after_cost': True, 'capital_deployment_reconciliation_pass': True, 'rare_event_stress_pass': True}`

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
- A-grade intersection counts: confidence >= threshold `0`, positive edge `635`, both `0`, blocked-both `0`, strict before temporal `0`, event-time-valid `0`
- A-grade blocker reason counts: `{'ALLOCATOR_BLOCK_DRAWDOWN_GUARD': 12, 'ALLOCATOR_BLOCK_SPREAD_SLIPPAGE': 2, 'LOW_CONFIDENCE': 999, 'MISSING_AFTER_COST_EDGE': 482, 'MISSING_CONFIDENCE': 481, 'NON_DIRECTIONAL_ACTION': 345, 'NON_POSITIVE_AFTER_COST_EDGE': 363}`
- A-grade blocker `paper_signal` `SOLUSDT` `5m` `short`: confidence `0.70367631`, edge `3.38975334` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `SOLUSDT` `15m` `short`: confidence `0.68869667`, edge `7.09703636` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `SOLUSDT` `1h` `short`: confidence `0.68863012`, edge `10.72099495` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `PENGUUSDT` `15m` `short`: confidence `0.67403602`, edge `18.85903358` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `PENGUUSDT` `1h` `short`: confidence `0.67009009`, edge `6.32864523` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- A-grade blocker `paper_signal` `MONUSDT` `15m` `short`: confidence `0.65978074`, edge `132.0` bps, decision `None`, reasons `['LOW_CONFIDENCE']`
- Near-A-grade explicit market-cost evidence: `12037` / `12054`; missing `{'MISSING_ACTUAL_SPREAD': 15, 'MISSING_FEES': 15, 'MISSING_FUNDING': 15, 'MISSING_MARKET_DEPTH': 17, 'MISSING_SLIPPAGE': 15}`; PIT rejects `{'FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME': 11, 'FEATURE_CUTOFF_AFTER_DECISION_TIME': 3, 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME': 11, 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE': 11, 'MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE': 4}`
- Counterfactual evidence acquisition: `PASSED`; blockers `['POSITIVE_EDGE_BELOW_CONFIDENCE_THRESHOLD']`; strict gate relaxed `False`
- Market-cost-ready near-A-grade candidates if confidence improves: `12037`; capture-required near-A-grade candidates `17`
- Ready `OPUSDT` `1h` `short`: decision `2026-06-20T09:38:11Z`, snapshot `v2_fsnap_c8433f2ddf5a1bbb4642f2d2148ab9a6a99393fed097a498a8dc3883eec5b199`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `OPUSDT` `1h` `short`: decision `2026-06-20T10:13:53Z`, snapshot `v2_fsnap_10508d4d25b25ceeccbddb6823f028442e2b253d0ffe4acca493b514eae3be68`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `JTOUSDT` `15m` `short`: decision `2026-06-20T15:49:02Z`, snapshot `v2_fsnap_866662e911fa049ba7c61fbff197382df8fde60757b594f980b27e371f7bffb5`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `ONDOUSDT` `1h` `long`: decision `2026-06-20T16:55:08Z`, snapshot `v2_fsnap_682c9eef1ffe04088b34766cd2394bdfdf1abcdaff6d108c7c8ca4588996f129`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Ready `OPUSDT` `1h` `long`: decision `2026-06-20T17:33:39Z`, snapshot `v2_fsnap_9abe966c636fc345228895103fafa3f3215c8d0bbdf4ea8b6a6b7b364308f311`, sources `{'spread_bps': 'actual_observed_spread_entry_bps', 'slippage_bps': 'expected_slippage_bps', 'fee_bps': 'fee_bps', 'funding_bps': 'expected_funding_bps', 'market_depth_usd': 'market_depth_usd'}`
- Capture `MONUSDT` `1h` `short`: decision `2026-06-17T01:34:46-04:00`, snapshot `v2_fsnap_228dc0da500b0fa86c1522a34405fb7a44f7da4d246cfde78322c61ee4795402`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE']`
- Capture `ADAUSDT` `1m` `short`: decision `2026-06-21T19:44:55Z`, snapshot `v2_fsnap_bec50104f5dbc54b16ee1ded69e5edc7a27d6f27dede7a5d002cb08d8a7510cf`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `MONUSDT` `1m` `short`: decision `2026-06-17T01:34:46-04:00`, snapshot `v2_fsnap_f2fb9fc6234dbb35e6e24efe60675762a6ac056192c0b968589ecb946047a10c`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE']`
- Capture `SOLUSDT` `1h` `short`: decision `2026-06-21T16:07:31Z`, snapshot `v2_fsnap_e0250e7f17e4e984f5216a3a2231cfffaed16e8e4585b2b5fa9cc77d1e7c50f2`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME', 'FEATURE_GENERATED_AT_AFTER_DECISION_TIME', 'FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE']`
- Capture `MONUSDT` `15m` `short`: decision `2026-06-17T01:34:46-04:00`, snapshot `v2_fsnap_f069da72b5714721e1054c3eb36d1c195b0ea7f0d85b49db313a040e919a0449`, missing `['MISSING_ACTUAL_SPREAD', 'MISSING_SLIPPAGE', 'MISSING_FEES', 'MISSING_FUNDING', 'MISSING_MARKET_DEPTH']`, PIT rejects `['MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE']`
- Near-A-grade pruned configuration reasons: `{'LIQUIDATION_PROBABILITY_LIMIT_BREACH': 2227560, 'MISSING_MARKET_DEPTH': 3240}`
- Source coverage: `PASSED` at `1.0`
- Durable accepted counterfactual rows: `233` from `4476` accepted candidates; bounded to current source cells `True`; excluded `{'NOT_ADAPTIVE_CAPITAL_POLICY_ROW': 4243}`
- Required symbol/timeframe cells: `770` / `770`; missing `0`
- Exact feature snapshot lookup: `NO_GO_EXACT_FEATURE_SNAPSHOT_GAPS`; requested `999`, available `265`, archived `46`, missing `734`
- A-grade signals: `10116`
- Prediction rows probed: `755`; probe status `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE`; participates in pass gate `False`
- Near-A-grade probe status: `NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE` at confidence threshold `0.65`; best configs `12037`; participates in pass gate `False`
- Near-A-grade temporal-invalid count: `11`
- A-grade replay progress: `1.0`; deficit `0`
- Configuration-space reconciliation: `True`
- Event-time-valid candidates: `10116`
- Best configurations: `10116`
- Market depth requirement: `required_actual_depth_usd_or_orderbook_levels`
- Market cost requirement: `required_explicit_spread_slippage_fee_funding_bps_or_usd`
- Market cost evidence coverage: `PASSED` with `10116` / `10116` complete A-grade candidates; missing `{}`
- Prediction market cost evidence coverage: `NO_CANDIDATES` with `0` / `0` complete candidates; missing `{}`
- Near-A-grade market cost evidence coverage: `NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE` with `12037` / `12054` complete candidates; missing `{'MISSING_ACTUAL_SPREAD': 15, 'MISSING_FEES': 15, 'MISSING_FUNDING': 15, 'MISSING_MARKET_DEPTH': 17, 'MISSING_SLIPPAGE': 15}`

## A-grade Readiness

- Confidence threshold: `0.75`
- After-cost edge threshold bps: `0.0`
- Source kind counts: `{'__unspecified__': 5, 'closed_candle_replay': 19800, 'paper_ledger': 910, 'paper_ledger_accepted': 233, 'paper_signal': 755}`
- Readiness blockers: `[]`
- `__unspecified__` rows `5`; confidence >= threshold `0`; positive edge `0`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `None`; reasons `{'MISSING_AFTER_COST_EDGE': 5, 'MISSING_CONFIDENCE': 5}`
- `closed_candle_replay` rows `19800`; confidence >= threshold `13842`; positive edge `13540`; A-grade before temporal `10116`; event-time-valid `10116`; best configs `10116`; confidence gap `0.0`; reasons `{'LOW_CONFIDENCE': 5958, 'NON_POSITIVE_AFTER_COST_EDGE': 6260}`
- `paper_ledger` rows `910`; confidence >= threshold `0`; positive edge `84`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.08341691`; reasons `{'ALLOCATOR_BLOCK_DRAWDOWN_GUARD': 17, 'ALLOCATOR_BLOCK_LOW_CONFIDENCE': 11, 'ALLOCATOR_BLOCK_NO_EDGE': 209, 'ALLOCATOR_BLOCK_SPREAD_SLIPPAGE': 13, 'LOW_CONFIDENCE': 250, 'MISSING_AFTER_COST_EDGE': 606, 'MISSING_CONFIDENCE': 660, 'NON_DIRECTIONAL_ACTION': 217, 'NON_POSITIVE_AFTER_COST_EDGE': 220}`
- `paper_ledger_accepted` rows `233`; confidence >= threshold `0`; positive edge `233`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.09021926`; reasons `{'LOW_CONFIDENCE': 233}`
- `paper_signal` rows `755`; confidence >= threshold `0`; positive edge `391`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; confidence gap `0.022953`; reasons `{'LOW_CONFIDENCE': 755, 'MISSING_AFTER_COST_EDGE': 1, 'NON_DIRECTIONAL_ACTION': 345, 'NON_POSITIVE_AFTER_COST_EDGE': 363}`
- Prediction probe is readiness-only and does not participate in the actionable counterfactual pass gate.
- Prediction source kind counts: `{'prediction': 755}`
- Prediction readiness blockers: `['NO_A_GRADE_SIGNALS']`
- `prediction` rows `755`; confidence >= threshold `0`; positive edge `377`; A-grade before temporal `0`; event-time-valid `0`; best configs `0`; no feasible config `0`; reasons `{'LOW_CONFIDENCE': 755, 'NON_DIRECTIONAL_ACTION': 362, 'NON_POSITIVE_AFTER_COST_EDGE': 378}`

## Compounding Evidence

- Status: `PASSED`
- Closed outcomes: `175` / `300`; deficit `125`
- Accepted-fill reconciled closed outcomes: `0`
- Symbol diversity: `29` / `30`; deficit `1`
- Direction outcomes: long `71`, short `104`
- Positive deployed-margin return: `True`
- Counterfactual status: `PASSED`
- Counterfactual efficient frontier ready: `True`

## 1000x Classification

- Status: `PASSED`
- Classification: `FEASIBLE_ON_CURRENT_WINDOW_PROJECTION_UNVERIFIED`
- Horizon years: `5.0`
- Horizon days: `1825.0`
- Required CAGR: `2.981071705535`
- Required monthly return: `0.12201845`
- Required daily return: `0.00379224`
- Explicit horizon classification: `True`
- No guaranteed-return claim: `True`
- Dependency-gated by current evidence: `False`
- Current evidence supports feasibility status: `True`
- Guaranteed-return claim: `False`

## Safety

- No real orders, test orders, leverage mutation, margin-mode mutation, withdrawals, transfers, old Redis writes, legacy restart, or trainer bridge unmask are approved by this status.
- Any live canary remains a separate operator-approved phase.
