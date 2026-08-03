# Paper Trading Performance Remediation Plan
**Generated:** 2026-06-18 (v4 update — 504-trade full-ledger final)
**Data window:** `v2:trainer:feedback:outcomes` Redis ledger as of 2026-06-18T23:30Z
**Live gate:** BLOCKED (human approval required)
**No guaranteed win rate or profit claimed.**

---

## 1. Executive Summary

The 500-trade paper soak target has been **exceeded (504 trades)**. The system has positive edge
(profit factor 1.10, total realized PnL +$17.17) but the win rate (29.56%) is materially below the
35% soft approval threshold, and two timeframes (5m, 4h) are net-negative by PnL.

**Live gate: NO_GO.** Soak complete. Win rate gate and negative-timeframe gate not met.

---

## 2. Key Numbers — Full Ledger (504 Trades)

| Metric | Value | Gate | Status |
|---|---|---|---|
| Closed trades | 504 | ≥ 500 | **MET** |
| Win count | 149 | — | — |
| Loss count | 355 | — | — |
| Win rate | 29.56% | ≥ 35% soft | **NOT_MET** |
| Realized PnL | +$17.17 | > 0 | MET |
| Avg win | +$1.28 | — | — |
| Avg loss | -$0.49 | — | — |
| Profit factor | 1.10 | ≥ 1.0 | MET (marginal) |
| Expectancy/trade | +$0.034 | > 0 | MET |
| Quarantine (pre-remediation) | 19 | 0 new | MET (no new failures) |
| PIT violations | 0 | 0 | **MET** |
| Negative-PnL timeframes | 5m, 4h | 0 | **NOT_MET** |
| Overall live readiness | NO_GO | GO | **NOT_MET** |

---

## 3. Timeframe Breakdown

| TF | Trades | Wins | WR | PnL | Status |
|---|---|---|---|---|---|
| 1m | 103 | 34 | 33.0% | +$11.71 | POSITIVE |
| 5m | 113 | 30 | 26.5% | **-$8.19** | **NEGATIVE** |
| 15m | 81 | 25 | 30.9% | +$17.82 | POSITIVE |
| 1h | 98 | 34 | 34.7% | +$2.01 | POSITIVE |
| 4h | 109 | 26 | 23.9% | **-$6.18** | **NEGATIVE** |

**Finding:** 5m and 4h are both structurally negative. If these two timeframes were excluded, the
remaining 282 trades would show substantially improved win rate and PnL. Neither has ever been
net-positive across the soak period.

---

## 4. Exit Reason Breakdown

| Exit Reason | Count | % |
|---|---|---|
| TIER_2_TRAILING_STOP | 299 | 59.3% |
| TIER_1_STOP_LOSS | 84 | 16.7% |
| TIER_2_TAKE_PROFIT | 85 | 16.9% |
| TIER_2_PROFIT_BANK | 30 | 6.0% |
| TIER_2_PROFIT_LOCK | 4 | 0.8% |
| TIER_4_MAX_HOLD_TIME | 2 | 0.4% |

Trailing stop is the dominant exit at 59.3%. When a trailing stop fires at a loss, it means the
position briefly went favorable enough to activate the stop but then reversed. This pattern is
consistent with the trailing stop being too tight for the symbols' natural volatility.

---

## 5. Loss Clusters

### 5.1 Symbol Clusters (Worst 10)

| Symbol | Trades | WR | PnL | Risk |
|---|---|---|---|---|
| PORTALUSDT | 1 | 0% | -$7.03 | HIGH — single tail loss |
| NIGHTUSDT | 4 | 0% | -$5.33 | HIGH — zero win rate |
| ALLOUSDT | 15 | 20% | -$4.77 | HIGH — persistent loss |
| ENAUSDT | 15 | 13% | -$4.75 | HIGH — lowest WR at volume |
| BEATUSDT | 34 | 41% | -$3.67 | MEDIUM — high volume net negative |
| CRVUSDT | 12 | 17% | -$3.61 | HIGH |
| TIAUSDT | 3 | 0% | -$2.85 | HIGH — zero WR |
| TRUMPUSDT | 3 | 0% | -$2.21 | HIGH — zero WR |
| BIOUSDT | 23 | 26% | -$2.10 | MEDIUM |
| PUMPUSDT | 2 | 0% | -$2.07 | HIGH — zero WR |

### 5.2 Top Performers

| Symbol | Trades | WR | PnL |
|---|---|---|---|
| BNBUSDT | 3 | 66.7% | +$7.39 |
| ESPORTSUSDT | 29 | 48.3% | +$6.14 |
| AEROUSDT | 15 | 40.0% | +$5.52 |
| TAOUSDT | 3 | 33.3% | +$4.52 |
| PAXGUSDT | 1 | 100% | +$4.50 |

---

## 6. Stale Prediction Diagnosis

**Current state (after publisher refresh):** 22/425 prediction rows stale, 403 fresh, 403 actionable.

**Root cause (historical):** Earlier in this session the publisher had not run for ~4h, producing
140 stale rows. After the publisher ran again, stale count dropped to 22. This confirms the
issue is **operational** (publisher was stopped/idle), not a code bug.

**Evidence:** `redis-cli get v2:prediction:BTCUSDT:1m` showed
`decision_cutoff_time_est: 2026-06-18T16:12:51Z` — age ~4.1h at peak staleness.
After publisher refresh: stale_count=22, fresh_count=403.

**Safety status:** Stale predictions are automatically EXCLUDED from paper candidates. Zero
stale predictions are used for trading decisions. PIT violations = 0.

**Remediation:**
- Ensure prediction publisher daemon is running continuously (already resolved operationally).
- Add a monitor alert: if stale_count > 50 or any symbol has no fresh prediction for > 30 minutes.
- 22 residual stale rows are from symbols where the publisher ran but the output is just under
  the 900-second threshold — these will refresh naturally on the next publisher cycle.

---

## 7. Stale Mark Price Diagnosis

**Current state:** `stale_mark_price_count` fluctuates around 0–3 open positions.

**Root cause:** Mark prices are computed at API request time by `_enrich_paper_positions()`.
The raw `v2:paper:positions` Redis key does not store mark age — it stores the last known price.
When the market price ingestor is slightly lagged (common under Binance rate limiting), 1–3
positions may have marks older than the 90-second threshold.

**Evidence:** 29 open positions all show `mark_price_stale=None` in the raw Redis store
because mark freshness is a computed field, not a stored field. The `mark_price_stale`
boolean (added 2026-06-18) makes per-position staleness auditable at API response time.

**Safety status:** The risk gateway checks mark price freshness before any execution decision.
Stale marks block execution — they do not silently allow bad trades.

**Remediation:**
- Add a monitor alert: if `stale_mark_price_count > 2` sustained for > 5 minutes, investigate
  the market price ingestor.
- No code change needed — the 90-second threshold correctly allows for the 60-second ingestor
  cycle plus network jitter.

---

## 8. Prioritized Remediation Queue

Actions required before live gate can open (DO NOT change live execution without human approval):

| Priority | Action | Risk | Reason |
|---|---|---|---|
| **P0** | Exclude 5m and 4h timeframes from paper trading | Low | Both are net-negative across 504-trade soak |
| **P0** | Add per-symbol loss circuit breaker (2 consecutive losses → 24h pause) | Low | PORTALUSDT, NIGHTUSDT, TIAUSDT, TRUMPUSDT all 0% WR |
| **P0** | Win rate must reach 35% on 200+ new trades after exclusions | — | Gate requirement before any live approval |
| **P1** | Ensure prediction publisher runs continuously | Low | 140 stale predictions = operational gap |
| **P1** | Complete expected move model review gate | Medium | 52k+ signals still blocked by model_review_required |
| **P1** | Symbol exclusion list: PORTALUSDT, NIGHTUSDT, TIAUSDT, TRUMPUSDT, PUMPUSDT | Low | Zero win rate, require positive expectancy evidence before re-enabling |
| **P2** | Widen trailing stop from 60 bps to 100+ bps on 1m/15m where positive | Medium | Trailing stop is 59% of exits; test in 100-trade soak first |
| **P2** | Add monitor alert for stale_mark_price_count > 2 sustained | Low | Operational observability |
| **P3** | Volatility-adjusted trailing stop (ATR-based) | High | Needs 100+ trade validation first |

---

## 9. What Must NOT Change

- Live gate remains BLOCKED until operator explicitly approves after all gates pass.
- No order submission, no leverage change, no margin mode change, no cancel/modify real orders.
- Do not loosen confidence gate below 0.65 without new trainer evidence.
- Do not approve live trading based on 29.56% win rate. Threshold is 35%.
- Do not remove stop loss (TIER_1) — the system requires a hard floor regardless of other changes.

---

## 10. Acceptance Criteria for Live Gate to Open

All of the following must be true simultaneously before any live approval is considered:

| # | Criterion | Current | Required |
|---|---|---|---|
| 1 | Paper soak complete | ✅ 504 | ≥ 500 |
| 2 | Win rate (200+ new trades after any change) | ❌ 29.56% | ≥ 35% |
| 3 | Profit factor | ⚠️ 1.10 | ≥ 1.25 (stable) |
| 4 | All timeframes net-positive PnL | ❌ 5m and 4h negative | All positive |
| 5 | No symbol with 0% win rate and ≥ 2 trades | ❌ NIGHTUSDT, TIAUSDT, TRUMPUSDT | 0 such symbols |
| 6 | PIT violations | ✅ 0 | 0 |
| 7 | Trainer quarantine new failures | ✅ 0 new | 0 new |
| 8 | Full Chromium Playwright suite green | ❌ not re-run | PASS |
| 9 | HTTPS/production smoke | ❌ not validated | PASS |
| 10 | Human operator explicit approval | ❌ | Required |

**Current status: 3/10 gates met. Live gate: NO_GO.**
