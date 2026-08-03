# NO_GO_LIVE_UNTIL_PAPER_EDGE_VALIDATED

**Status: LIVE TRADING BLOCKED**
Generated: 2026-06-17 (updated: wiring sprint complete)
Audit sprint: 10-phase paper trading system remediation + wiring sprint

---

## Current Paper Quality Verdict

The V2 paper trading system has completed a full 10-phase audit and remediation sprint.
All 4402 unit and integration tests pass (4390 prior + 12 new). All four safety scans are clean.

**The system is paper-ready but not live-ready.**

Reasons below.

---

## What Was Completed (This Sprint)

| Phase | Scope | Result |
|-------|-------|--------|
| 1 | Signal→risk→orchestrator lineage — every actionable signal now carries full decision IDs; blocked signals carry exact block reason | COMPLETE |
| 2 | Feature-family completeness gate — critical families missing → hard block; no silent masking | COMPLETE |
| 3 | Static soak lists replaced with dynamic outcome-memory controls (rolling win rate, EV, drawdown, slippage, reversal rate) | COMPLETE |
| 4 | High-precision gate tightened — multi-TF agreement, OB liquidity check, positive expected move after costs, no stale family, no degraded bucket | COMPLETE |
| 5 | DataLoader zombie fix — persistent_workers forced to False, worker cap=4, del loader in finally; 18 existing zombie PIDs are Z-state (kernel-harmless) until trainer natural restart | COMPLETE |
| 6 | Prediction schema enriched — direction/data_coverage_pct normalization, realized-outcome back-fill path, accuracy report grouped by symbol/TF/direction/strategy_family/regime | COMPLETE |
| 7 | Hedge engine enriched with hedge_recommendation / hedge_cost_bps / hedge_benefit_bps / unwind_reason; exits upgraded with ATR-based volatility stop and liquidity-aware TP | COMPLETE |
| 8 | Per-trade leverage recommendation service — isolated margin only, max 3x, $50 max loss budget, never ALL_SYMBOLS aggregate | COMPLETE |
| 9 | Anti-market-maker detectors — all 6 implemented: sweep, spoof/wall-pull, liquidity hunt, depth-tape divergence, toxic flow, stop-run risk | COMPLETE |
| 10 | All modules compile clean; 4352/4352 tests pass; 4 safety scans clean | COMPLETE |
| Wiring | All deferred services wired into paper_online_runtime.py (Phases 3/4/6/7/8/9); BLOCKER-1 resolved; BLOCKER-2 resolved | COMPLETE |
| Continuous Monitor | Hourly monitor + loss recovery loop + outcome memory updater (12 stores) + 9 final artifacts; BLOCKER-4 partially resolved; 4390 tests | COMPLETE |
| Runtime Hygiene | Duplicate paper_online_runtime killed (1 instance); hourly monitor loop scheduled (3600s); timeframe/side/feedback_sent/leverage_recommendation fields added to paper events; feedback_consumed=7 (fixed from 0); 4402 tests | COMPLETE |

---

## Remaining Blockers Before Live

### ~~BLOCKER-1: New services not yet wired into paper_online_runtime.py~~ RESOLVED

**RESOLVED** (wiring sprint 2026-06-17): All 3 services are now wired into `paper_online_runtime.py` via the new `apply_paper_entry_gates()` function:

- `anti_market_maker_detector.evaluate_all_detectors()` — wired in `apply_paper_entry_gates` (Phase 9 entry block) and `build_position_lifecycle_entry` (Phase 7 exit acceleration)
- `prediction_accuracy_tracker.enrich_prediction_for_phase6()` — wired in `build_runtime_payload` after building trainer_prediction
- `leverage_recommendation.recommend_leverage_for_signal()` — wired in `apply_paper_entry_gates` (advisory; never blocks)
- `trade_management_paper.hedge_engine.evaluate_hedge()` — wired in `build_position_lifecycle_entry` (advisory, fail-closed)

Evidence: `raw_evidence/phase3_9_wiring_sprint_status.json`

---

### ~~BLOCKER-2: Realized outcome back-fill not wired~~ RESOLVED

**RESOLVED** (wiring sprint 2026-06-17): `prediction_accuracy_tracker.backfill_realized_outcome()` is now called in `_push_decisions_to_redis` whenever `paper_result == POSITION_CLOSED_PAPER_ONLY`.

The accuracy report `realized_count` will now increment as paper positions close. Live readiness still requires at least 200 closed paper trades with realized outcomes before accuracy report can be trusted.

Evidence: `raw_evidence/phase3_9_wiring_sprint_status.json`

---

### BLOCKER-3: Paper soak minimum not met

Minimum required before any live consideration:
- 500 closed paper trades across at least 5 symbols
- Rolling 30-trade win rate ≥ 55% per active symbol/TF bucket
- Rolling 30-trade EV ≥ 5 bps per active bucket (after estimated costs)
- Zero liquidation events in paper mode
- Drawdown contribution < 15% per single position
- All six anti-MM detectors producing entries blocked at non-trivial rate (confirms signals are flowing through)

Current paper trade count: **7/500** (1.4%) as of 2026-06-17.
Win rate: 14.3% (1 TP, 6 SL) — well below 55% threshold.
Continuous hourly monitor is now active and tracking progress.
Outcome memory buckets updated: 1 (BTCUSDT:1m).
Hourly loss recovery loop active: no tightening triggered (3h windows had 0 closed trades).

---

### BLOCKER-4: SHAP / feature attribution gap — PARTIALLY RESOLVED

**PARTIALLY RESOLVED** (continuous monitor sprint 2026-06-17): `_attribution_fallback()` implemented in `prediction_accuracy_tracker.py`. Uses gradient-sign heuristic (feature value × predicted direction) to classify each feature in `top_features` as supporting or contradicting. Returns codes prefixed with `__gradient_sign_heuristic__` so the method is auditable.

`top_positive_feature_codes` and `top_negative_feature_codes` now **non-empty** for any prediction that has `top_features` in the payload.

**Still required before live**: Real SHAP from the trainer checkpoint export. The heuristic is sufficient for paper mode signal explainability and can be waived by operator for paper operation with documented reason.

---

### BLOCKER-5: DataLoader zombies not yet cleared

18 `pt_data_worker` zombie processes exist under trainer PID 1037427.

Root cause is fixed in code (`persistent_workers=False`), but fix takes effect only on next natural trainer restart. Protected ML runtime cannot be restarted manually.

Current zombie state: Z-state (no CPU/memory consumed). Not a live blocker, but must be verified cleared before live evaluation begins.

---

### BLOCKER-6: Accuracy evidence insufficient

No live operator has confirmed the following from paper mode evidence:
- High-precision gate is filtering correctly (fewer but better trades)
- Dynamic outcome-memory controls are blocking degraded symbol/TF buckets
- ATR-based exit fires before static stop in high-volatility conditions
- Anti-MM detectors are blocking entries at a non-zero rate in production feature flow

These require live paper observation, not just unit tests.

---

## Safety Invariants (Verified Clean)

| Invariant | Status |
|-----------|--------|
| No real exchange calls in paper services | VERIFIED CLEAN |
| No leverage/margin mutation in V2 | VERIFIED CLEAN |
| No hardcoded position sizes | VERIFIED CLEAN |
| No guaranteed-profit wording | VERIFIED CLEAN |
| All new services: `mutates_exchange=False` | VERIFIED |
| All new services: `live_gate="blocked_human_only"` | VERIFIED |
| All new services: `paper_only=True` | VERIFIED |
| Hedge: `operator_paper_hedge_engine_approved=False` default | VERIFIED |
| Leverage: CROSS margin never recommended | VERIFIED |
| Leverage: max 3x, max loss $50 | VERIFIED |

---

## Enabling Live Trading Requires (Not Yet Attempted)

These steps must happen in order and each requires explicit operator action in the GUI:

1. ~~BLOCKER-1 wiring complete~~ **DONE** (all services wired 2026-06-17)
2. ~~BLOCKER-2 back-fill wired~~ **DONE** (wired 2026-06-17); accumulate ≥200 closed trades with realized outcomes
3. BLOCKER-3 soak criteria met (500 closed trades, win rate ≥55%, EV ≥5 bps, zero liquidations)
4. BLOCKER-4 SHAP wired (or waived by operator with documented reason)
5. BLOCKER-5 zombie processes cleared after natural trainer restart
6. BLOCKER-6 operator reviews paper accuracy report and signs off
7. Operator manually enables live trading gate in GUI (default: BLOCKED)
8. Operator adds and activates live API keys via GUI Admin
9. Live canary test: single small-size trade on one symbol with full audit trace
10. Risk gateway live review: confirm kill switch active, stop loss active, leverage ≤ approved level

**No automated path to live. Every step requires explicit human approval.**

---

## Evidence Artifacts

All 10 phase evidence artifacts + wiring sprint + continuous monitor artifacts are at:

```
raw_evidence/phase1_signal_lineage_remediation_status.json
raw_evidence/phase2_feature_family_completeness_status.json
raw_evidence/phase3_entry_gate_dynamic_controls_status.json
raw_evidence/phase4_high_precision_paper_mode_status.json
raw_evidence/phase5_masa_worker_scaling_status.json
raw_evidence/phase6_prediction_validation_status.json
raw_evidence/phase7_hedge_exit_risk_status.json
raw_evidence/phase8_dynamic_leverage_margin_recommendation_status.json
raw_evidence/phase9_anti_market_maker_detection_status.json
raw_evidence/phase10_final_validation_status.json
raw_evidence/phase3_9_wiring_sprint_status.json    ← BLOCKER-1 + BLOCKER-2 resolution evidence
raw_evidence/continuous_hourly_monitor_status.json ← hourly monitor run summary
raw_evidence/paper_soak_500_trade_status.json      ← soak progress (7/500)
raw_evidence/paper_loss_recovery_status.json       ← loss recovery evaluation
raw_evidence/shap_attribution_status.json          ← BLOCKER-4 partial resolution
raw_evidence/latest_3h_paper_quality_status.json   ← 3H window quality verdict
raw_evidence/NO_GO_UNTIL_3H_EDGE_VALIDATED.md      ← continuous monitor final marker
```

---

*This document is a live blocker list, not a roadmap. It must be updated as blockers are resolved.*
*Live trading remains BLOCKED until all blockers above are cleared and operator enables the gate via GUI.*
