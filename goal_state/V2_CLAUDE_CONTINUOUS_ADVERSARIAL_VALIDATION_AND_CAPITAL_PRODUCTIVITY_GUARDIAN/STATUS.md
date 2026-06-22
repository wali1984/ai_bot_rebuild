# Guardian Status — V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN

**Last Updated:** 2026-06-20T05:36:03Z
**State:** ACTIVE
**Completion Allowed:** FALSE
**Completion Gates Passed:** 3/18

---

## CURRENT PORTFOLIO STATE (2026-06-20T05:36Z — LIVE)

| Metric | Value |
|--------|-------|
| Open Positions | 8 (LONG=4, SHORT=4) |
| Total Notional | $246.76 |
| Gross Leverage | 0.025x |
| Realized PnL | +$49.00 |
| Unrealized PnL | -$0.24 |
| Estimated Equity | ~$10,049 |
| V1 Policy Trades | 441 |
| V1 Win Rate | 25.2% |
| V1 Net PnL | -$9.68 |
| V1 ATR Stop Rate | 71.9% |
| Closed Trades Total | 1,417 |
| Outcome Memory Blocks | 1h, 15m, 4h, 1m, 5m (ALL 5) |
| Audit Gate Blocks | 4h, 5m ONLY (1h/15m/1m still allowed) |

NOTE: Prior readings showing 87 positions/$143K notional were stale v2:portfolio:state snapshots.
Current live state from v2:paper:ledger: 8 positions, $247 notional, 0.025x gross leverage.

---

## SAFETY STATUS

- places_real_order: false — confirmed via /health API
- live_gate: blocked_human_only — confirmed
- No exchange mutations. No real orders. No leverage changes.
- LIVE TRADING: PERMANENTLY BLOCKED until all gates pass.

---

## ALL 18 FINDINGS

### CRITICAL (5)
| ID | Summary | Status |
|----|---------|--------|
| CG-F001 | LONG trades net negative (WR=26.6%, Net=-$20.56). Entry quality failure. | OPEN |
| CG-F002 | ATR stop dominates 71.9% of V1 exits. All at 0% WR. | OPEN |
| CG-F009 | mean_reversion_mode LONG WR=21%, PF=0.25 in all regimes. | OPEN |
| CG-F013 | mean_reversion_mode monopoly 68.8%. Strategy weight adaptation broken. | OPEN |
| CG-F014 | Outcome memory blocks NOT wired to admission gate. Static audit_entry_gate blocks 4h/5m only; 1h/15m/1m STILL ALLOWED despite outcome_memory blocking all 5. | OPEN |

### HIGH (8)
| ID | Summary | Status |
|----|---------|--------|
| CG-F003 | Leverage not tracked per-trade. Mechanism broken, not currently violated (8 pos, 0.025x). | OPEN |
| CG-F004 | VALIDATION_LEDGER PASSED vs FINAL_BLOCKERS NO_GO — contradiction. | OPEN |
| CG-F005 | bid_ask_spread_bps absent from all 1417 closed trades. | OPEN |
| CG-F010 | realized_slippage_bps constant 2.0 in 100% of trades and training feedback. | OPEN |
| CG-F011 | recommended_leverage constant 1.0. Phase 8 not implemented. | OPEN |
| CG-F015 | Trailing activation bug: Set A (36: flag+no price), Set B (48: price in loss territory). -$49.33 on 84 MFE>=30bps trades. | OPEN |
| CG-F016 | Exposure cap cycle-reset bug: checks cycle notional (starts 0) not portfolio notional. | OPEN |
| CG-F017 | Training direction label INVERTED for SHORT trades (55.5% of feedback). Profitable SHORT -> LONG label. Self-reinforcing SHORT bias. | OPEN |

### MEDIUM (5)
| ID | Summary | Status |
|----|---------|--------|
| CG-F006 | squeeze_evidence_score 33.7% populated. | OPEN |
| CG-F007 | drawdown_at_entry 12.8% non-zero. | OPEN |
| CG-F008 | WR=25.2%, PF unchanged. No improvement from audit baseline. | OPEN |
| CG-F012 | expected_move_after_cost_bps not persisted in closed trade records. | OPEN |
| CG-F018 | 71% of signals use 5-day-old features (2026-06-15 cutoff). | OPEN |

---

## REMEDIATION PACKETS WRITTEN (for Codex)

1. REMEDIATION_CG_F001_LONG_ENTRY_QUALITY.md
2. REMEDIATION_CG_F002_ATR_STOP_DOMINANCE.md
3. REMEDIATION_CG_F014_OUTCOME_MEMORY_BLOCK_NOT_WIRED.md — HIGHEST PRIORITY
4. REMEDIATION_CG_F017_TRAINING_LABEL_INVERSION.md

---

## CODEX PRIORITY ORDER

1. CG-F014 (CRITICAL): Wire outcome_memory.degraded dynamic blocks into audit_entry_gate. Replace static ['4h','5m'] with Redis lookup. Current: 1h/15m/1m still admitted.
2. CG-F017 (HIGH): Fix training label: multiply realized_pnl_bps by (-1) for SHORT trades before _label_action.
3. CG-F015 (HIGH): Fix trailing activation in same eval pass; clamp trailing price to at-cost minimum.
4. CG-F013 (CRITICAL): Wire strategy weight adaptation — mean_reversion_mode should down-weight after losses.
5. CG-F009 (CRITICAL): Block mean_reversion_mode LONG in admission gate (WR=21%, PF=0.25).

---

## RUNTIME OBSERVATIONS

| ID | Time | Key Finding |
|----|------|-------------|
| RO-001 | 2026-06-20T02:49Z | Initial snapshot: 86 open SHORT, equity $11,695, 13.95x leverage (stale) |
| RO-002 | 2026-06-20T02:49Z | Codex state: VALIDATION_LEDGER contradicts FINAL_BLOCKERS |
| RO-003 | 2026-06-20T05:06Z | Portfolio deterioration: equity -$564, new trades 89% on blocked TFs |
| RO-004 | 2026-06-20T05:23Z | All 5 TFs now blocked in outcome_memory. CG-F016 discovered. |
| RO-005 | 2026-06-20T05:36Z | RECALIBRATION: 8 positions (was 87 stale). CG-F014 gate = static list not dynamic. CG-F017 confirmed. |

---

## COMPLETION GATE ASSESSMENT

| Gate | Status | Evidence |
|------|--------|----------|
| G01: F01 direction symmetry (LONG WR>=40%) | FAIL | LONG WR=26.6% |
| G02: V1 policy net positive | FAIL | V1 Net=-$9.68 |
| G03: Notional/leverage populated | FAIL | 66.1% missing |
| G04: Capital allocation optimized | FAIL | leverage=1.0 constant |
| G05: Execution cost model live | FAIL | slippage=2.0 constant |
| G06: Spread field populated | FAIL | 0% populated |
| G07: Squeeze field populated | PARTIAL | 33.7% |
| G08: Drawdown at entry | PARTIAL | 12.8% |
| G09: ATR stop <50% of V1 exits | FAIL | 71.9% |
| G10: 50+ profitable LONG closes | FAIL | ~14 profitable LONGs |
| G11: LONG/SHORT WR within 5% | FAIL | LONG=26.6% vs SHORT=23.2% (3.4% gap but both failing) |
| G12: LIVE GATE blocked | PASS | blocked_human_only |
| G13: No real orders | PASS | confirmed |
| G14: No exchange mutations | PASS | confirmed |
| G15: Outcome memory blocks honored | FAIL | 1h/15m/1m still allowed |
| G16: Rare event stress matrix | NOT_STARTED | Phase 10 pending |
| G17: Counterfactual capital sweep | PARTIAL | MFE done, margin utilization pending |
| G18: All findings CLOSED | FAIL | 18 open findings |

Gates passed: 3/18 (G12, G13, G14)
