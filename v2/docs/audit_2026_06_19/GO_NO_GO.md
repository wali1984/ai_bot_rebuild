# GO / NO-GO GATE DETERMINATION
**Audit ID:** V2_FULL_UNIVERSE_ADAPTIVE_TRADING_TRUTH_AND_90P_EXECUTION_TIER_AUDIT  
**Auditor:** claude-sonnet-4-6 (independent mode)  
**Audit date:** 2026-06-19  
**Dataset:** v2:paper:closed_trades — 645 closed trades  
**Live gate status:** `blocked_human_only`  
**Places real orders:** NO  

---

## VERDICT: NO-GO

**Live trading is CONFIRMED BLOCKED.**  
**Paper trading system remains active and in paper-only mode.**  
**No production action required.**

---

## Gate Scorecard

| Gate | Required | Actual | Status |
|------|----------|--------|--------|
| G01 — Paper soak complete | ≥ 500 trades | 645 trades | **PASS** |
| G02 — Win rate | ≥ 35% | 30.39% | **FAIL** |
| G03 — Profit factor stable | ≥ 1.25 | 1.11 (declining) | **FAIL** |
| G04 — All timeframes net-positive | all positive | 5m: -$10.15, 4h: -$3.65 | **FAIL** |
| G05 — PIT violations | 0 | 0 | **PASS** |
| G06 — New quarantine failures | 0 | 0 | **PASS** |
| G07 — LONG path exercised | ≥ 50 LONG trades | 0 LONG trades | **FAIL** |
| G08 — Trailing stop WR | ≥ 40% | 10.1% | **FAIL** |
| G09 — squeeze_evidence_score | populated | null on 100% trades | **FAIL** |
| G10 — Real bid-ask spread | market-observed | hardcoded 2.0 bps | **FAIL** |
| G11 — Drawdown guard | functional | always 0.0 (non-functional) | **FAIL** |
| G12 — Portfolio equity accuracy | includes closed PnL | missing $22.23 | **FAIL** |
| G13 — Playwright suite | PASS | not re-run | **NOT VERIFIED** |
| G14 — Human operator approval | explicit | not given | **NOT MET** |

**Gates passing: 3/14 (21%)**

---

## Critical Blockers (must fix before any live consideration)

### B01 — PPO model outputs SHORT only (CRITICAL)
645/645 trades are SHORT. LONG action path has never executed a single paper trade. The model's `action_probabilities[1]` (LONG) is near 0 for all symbols sampled. The system cannot participate in bull markets, long-side reversals, or oversold bounces.

**Evidence:** `v2:prediction:LITUSDT:15m → action_probabilities=[2.42e-7, 1.40e-7, 0.9999996]`

### B02 — Trailing stop fires at loss 89.9% of the time (CRITICAL)
TIER_2_TRAILING_STOP: 395 exits (61.2%), WR=10.1%, total_pnl=-$135.97. The trailing stop distance (~60 bps) is too tight for symbol natural volatility. Positions briefly move favorably to activate the stop then reverse, triggering a loss exit.

**Evidence:** ts_count=395, ts_wins=40, ts_losses=355, ts_total=-$135.97

### B03 — Portfolio realized PnL not accumulated (CRITICAL)
`v2:portfolio:state.realized_pnl_usd = 0.0` despite $22.23 net realized PnL from 645 closed trades. Reported equity ($10,719.36) excludes closed trade PnL. Gap: $22.23.

---

## Summary: Why NO-GO

The system has **positive mathematical edge** (profit factor 1.11, net +$22.23 over 645 trades) but fails on multiple structural gates:

1. **Model bias**: System only knows how to SHORT. LONG path is dead code from a paper trading perspective.
2. **Exit management**: The trailing stop is the dominant exit path (61.2%) with 89.9% loss rate — it is the primary value destroyer.
3. **Feature gaps**: squeeze detection non-functional, spread hardcoded, drawdown guard non-functional.
4. **Win rate**: 30.39% < 35% threshold. Gate requires 35% on 200+ new trades after any parameter change.
5. **Structural timeframe losses**: 5m and 4h remain net-negative across the entire soak.

---

## Path to GO

The minimum required changes before re-evaluation (in order):

1. **Disable 5m and 4h** timeframes from paper trading (P0, immediate)
2. **Symbol exclusion list**: NIGHTUSDT, TIAUSDT, TRUMPUSDT, PUMPUSDT, PORTALUSDT (P0)
3. **Widen trailing stop** from ~60 bps to 100-150 bps; or implement ATR-based dynamic stop (P0)
4. **Add MFE/MAE recording** per trade to enable proper stop optimization (P1)
5. **Fix portfolio equity accumulation** — add closed trade realized PnL to equity calculation (P1)
6. **Fix drawdown tracker** — compute current_drawdown_bps from equity vs HWM and pass to router (P1)
7. **Wire real bid-ask spread** from Binance orderbook to microstructure_context (P1)
8. **Retrain PPO** with balanced LONG/SHORT reward to enable LONG trades (P0 — blocks gate G07)
9. Run **200-trade new soak** after changes 1-3 and verify WR ≥ 35%
10. **Human operator explicit approval** after all gates pass

---

## What Must Not Change

- Live gate remains `blocked_human_only` — only explicit human operator action can open it
- No real orders, no leverage/margin changes, no exchange calls
- Do not weaken confidence gate below 0.65 without new trainer evidence
- Do not approve live trading based on 30.39% win rate — threshold is 35%
- Maintain TIER_1_STOP_LOSS — hard floor must exist regardless of TS changes
- No guaranteed win rate or profit claim is made

---

*This determination is based on raw Redis evidence from v2:paper:closed_trades (645 rows), v2:portfolio:state, and sampled prediction keys. No finding is based on summaries alone. All raw evidence verification commands are in claude_commands_run.md.*
