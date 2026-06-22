# Paper Trading Full Audit — All Trades, Signals, Predictions, System Decisions
**Generated:** 2026-06-18T23:30Z  
**Source:** `v2:paper:closed_trades` Redis key + `v2:paper:heartbeat` + `v2:paper:strategy_router_report`  
**Total closed trades:** 595  
**Live gate:** blocked_human_only — no real orders submitted.

---

## Contents
1. [System Configuration](#1-system-configuration)
2. [Data Schema — Every Field Explained](#2-data-schema--every-field-explained)
3. [Executive Summary — Full Ledger Stats](#3-executive-summary)
4. [Root Cause Analysis — Why Win Rate Is Low](#4-root-cause-analysis)
5. [Strategy × Timeframe Cross-Analysis](#5-strategy--timeframe-cross-analysis)
6. [Exit Reason Analysis](#6-exit-reason-analysis)
7. [Per-Symbol Full Results (All 83 Symbols)](#7-per-symbol-full-results)
8. [Per-Timeframe Full Results](#8-per-timeframe-full-results)
9. [Per-Strategy Full Results](#9-per-strategy-full-results)
10. [Worst-10 Trades — Full Detail](#10-worst-10-trades)
11. [Best-10 Trades — Full Detail](#11-best-10-trades)
12. [Full Per-Trade Ledger (All 595 Trades)](#12-full-per-trade-ledger)

---

## 1. System Configuration

Values from `v2:paper:heartbeat` and `v2:paper:strategy_router_report`.

| Parameter | Value | Where |
|---|---|---|
| Portfolio equity at heartbeat | $10,634.70 | heartbeat.paper_position_exposure_cap_status |
| Starting equity (baseline) | $10,000.00 | configured |
| Realized PnL at heartbeat | +$21.71 | heartbeat.realized_pnl_usd |
| Unrealized PnL (open positions) | +$11.43 | heartbeat.unrealized_pnl_usd |
| Open positions at last heartbeat | 24 | heartbeat.open_position_count |
| Max single symbol exposure | 8% of equity (~$850 max) | max_single_symbol_exposure_pct=0.08 |
| Max total paper exposure | 60% of equity (~$6,381 max) | max_total_paper_exposure_pct=0.6 |
| Max open positions total | 32 | max_open_positions_total=32 |
| Max open positions per symbol | 1 | max_open_positions_per_symbol=1 |
| Exposure model | PERCENTAGE_BASED_EQUITY_ENVELOPE | operator_envelope_type |
| Leverage | ~1x implied (size = equity fraction, not margin-leveraged) | no leverage field in records |
| Paper only | true | paper_only=true on every record |
| Places real orders | false | places_real_order=false on every record |
| Live gate | blocked_human_only | permanent — cannot be changed without human approval |
| Trade direction | SHORT ONLY — 100% of all trades | derived from action field |
| Intents built | 754 | heartbeat.intents_built |
| Intents accepted (fills) | 81 | heartbeat.intents_accepted — 10.7% fill rate |
| Intents blocked | 135 | heartbeat.intents_blocked |
| Primary block reason | confidence_below_threshold | v2:paper:block_reasons |
| Shadow observations | 232 | heartbeat.shadow_observation_count |
| Strategy router signals seen | 2,581 | strategy_router_report.total_rows |
| Mode distribution | trend_mode=2101, mean_reversion_mode=443, reduce_size_mode=32, no_trade_mode=5 | strategy_router_report.mode_counts |

### Bid-Ask Spread
The `microstructure_context.bid_ask_spread_bps` was consistently **2.0 bps** across all recorded
trades. This is the modeled market microstructure cost basis at entry.

### Position Sizing Example
ESPORTSUSDT entry at $0.08893, closed_quantity=1,258 units → notional ~$112. This is well within
the 8% cap ($850) meaning the system sized most positions conservatively.

---

## 2. Data Schema — Every Field Explained

Every record in `v2:paper:closed_trades` has the following fields. All fields were present
in all 595 records (some may be null for pre-remediation rows).

| Field | Type | Nullable | Description |
|---|---|---|---|
| `close_id` | string | no | Unique close event ID. Format: `paper_close_{position_id}_{seq}_{pnl_int}`. |
| `position_id` | string | no | Paper position ID. Format: `paper_pos_{SYMBOL}`. One per symbol. |
| `symbol` | string | no | USDM futures pair. Example: `BTCUSDT`, `ESPORTSUSDT`. |
| `side` | string | no | Position side: `short` or `long`. **All 595 records are `short`.** |
| `action` | string | no | PPO model action output. All `short`. LONG never fired. |
| `timeframe` | string | no | Prediction timeframe used: `1m`, `5m`, `15m`, `1h`, `4h`. |
| `strategy_id` | string | no | Strategy identifier. Values: `trend_mode`, `mean_reversion_mode`, `reduce_size_mode`. |
| `strategy_family` | string | no | Same as strategy_id (audit redundancy field). |
| `strategy_subtype` | string | no | Sub-type within strategy. Same as strategy_id in current build. |
| `strategy_selected_mode` | string | no | The mode the strategy router chose for this signal. Canonical field. |
| `entry_reason` | string | no | Why the position was opened. Same as strategy_selected_mode. |
| `entry_price` | float | no | Paper fill price at entry in USD. This is the simulated execution price. |
| `exit_price` | float | no | Paper fill price at exit in USD. |
| `exit_price_source` | string | no | How exit price was obtained. Always `V2_MARKET_PRICE_MARK_TO_MARKET`. |
| `exit_price_utc` | string | no | ISO-8601 UTC timestamp of position close. |
| `closed_quantity` | float | no | Number of contract units closed (not USD notional). |
| `gross_realized_pnl_usd` | float | no | PnL before subtracting fees and slippage. |
| `fees` | float | no | Simulated trading fees in USD (modeled from Binance fee schedule). |
| `slippage` | float | no | Simulated slippage cost in USD. Modeled, not exchange-measured. |
| `realized_pnl_usd` | float | no | **Net PnL** = gross - fees - slippage. The definitive profit/loss per trade. |
| `realized_pnl_usdt` | float | no | Same as realized_pnl_usd (USDT denomination, same value). |
| `realized_pnl_bps` | float | no | PnL in basis points. Formula: (exit-entry)/entry * 10000 * side_mult. |
| `winner` | bool | no | true if realized_pnl_usd > 0, else false. |
| `exit_reason` | string | no | Why position was closed. See exit reason table below. |
| `close_reason` | string | no | Same as exit_reason (redundant field). |
| `hold_time_seconds` | int | no | Duration the position was held from fill to close. |
| `market_regime_at_entry` | string | no | Regime classifier output at entry: `TREND`, `RANGE`, `NO_TRADE`. |
| `market_regime_at_exit` | string | no | Regime classifier output at exit. May differ from entry. |
| `hedge_state` | string | no | Hedge status: `NO_HEDGE`, `HEDGED`, `PARTIAL_HEDGE`. All 595 are `NO_HEDGE`. |
| `hedge_reason` | string | no | Why hedge state is what it is. All `NO_HEDGE_CONTEXT`. |
| `drawdown_at_entry` | float | no | Portfolio drawdown % at the moment of entry. All 0.0 in this soak. |
| `entry_signal_id` | string | no | ID of the signal that triggered entry. Matches entry_prediction_id in most cases. |
| `entry_prediction_id` | string | no | ID of the PPO prediction that produced the entry signal. Links to `v2:prediction:*` keys. |
| `exit_signal_id` | string/null | yes | Signal at exit. null = exit was rule-based (stop/TP), not model-driven. |
| `exit_prediction_id` | string/null | yes | Prediction at exit. null for all rule-based exits. |
| `entry_feature_snapshot_id` | string/null | yes | Hash ID of the feature vector used for the entry prediction. null = pre-remediation trade. |
| `feature_snapshot_id` | string/null | yes | Feature snapshot at close. Usually same as entry_feature_snapshot_id. |
| `entry_market_state_id` | string | no | Market integrity state ID at entry. Links to market state assessment. |
| `market_state_id` | string | no | Market state at close. |
| `outcome_label_id` | string | no | ID of the training outcome label written for this trade. |
| `trainer_feedback_id` | string | no | ID in `v2:trainer:feedback:outcomes` (if not quarantined). |
| `source_fill_ids` | list | no | All signal/intent IDs that filled into this position. Multiple if position was added to. |
| `squeeze_evidence_score` | float/null | yes | Squeeze detection score. null across all 595 trades = squeeze detection inactive. |
| `major_move_signal_id` | string/null | yes | Major move event signal ID. null = no major move detected at entry. |
| `future_window_label_source` | string | no | Always `closed_trade_outcome`. |
| `paper_only` | bool | no | Always true. |
| `places_real_order` | bool | no | Always false. |
| `liquidity_zone_context` | object | no | Liquidity zone features at entry. Contains `source`, `source_labels`, `missing_feature_names`. |
| `liquidation_distance_context` | object | no | Liquidation distance context. Missing features present. |
| `liquidation_context` | object | no | Liquidation level context. |
| `microstructure_context` | object | no | Bid-ask spread (2.0 bps), volatility (null = missing). |
| `oi_funding_context` | object | no | Open interest and funding rate context. |
| `public_intel_context` | object | no | Alt data / sentiment context. |

### Exit Reason Codes

| Exit Reason Code | Meaning | Is Winner? | Notes |
|---|---|---|---|
| `TIER_1_STOP_LOSS` | Hard stop loss hit. Maximum allowed loss per position reached. | Always LOSS | Avg hold 463s, avg PnL -$0.71 |
| `TIER_2_TRAILING_STOP` | Trailing stop fired. Position was profitable enough to activate trailing stop, then reversed below stop. | 9.8% WIN | 356 trades. Dominant failure. Avg hold 1,585s, avg PnL -$0.35 |
| `TIER_2_TAKE_PROFIT` | Fixed take-profit price target reached. | Always WIN | Avg hold 1,357s, avg PnL +$1.38 |
| `TIER_2_PROFIT_BANK` | Partial profit banking (size reduction to lock in gains). | Always WIN | Avg hold 481s, avg PnL +$1.50 |
| `TIER_2_PROFIT_LOCK` | Profit lock level activated. | Always WIN | 4 trades only |
| `TIER_4_MAX_HOLD_TIME` | Position forced-closed after maximum hold time exceeded. | Always WIN | 3 trades, avg +$3.46 — longest holds are profitable |

### Strategy Mode Codes

| Strategy Mode | Trigger Condition | Dominant TF | WR | Net PnL |
|---|---|---|---|---|
| `trend_mode` | PPO model detects TREND regime + high short confidence | 4h, 5m (most) | 27.1% | -$22.15 |
| `mean_reversion_mode` | PPO model detects RANGE regime + mean reversion signal | 1h, 15m | 78.3% | -$0.77 |
| `reduce_size_mode` | Risk manager initiates position reduction / partial exit | 1m, 5m | 62.5% | +$44.62 |

---

## 3. Executive Summary — Full Ledger Stats

### 3.1 Top-Line Numbers

| Metric | Value |
|---|---|
| Total closed trades | **595** |
| Win trades | **184** |
| Loss trades | **411** |
| Win rate | **30.92%** |
| Gross PnL (before fees/slip) | **+$56.8250** |
| Total fees | **-$23.5686** |
| Total slippage | **-$11.7843** |
| Fee + slippage total | **-$35.3530** (62.2% of gross PnL) |
| Net PnL | **+$21.4721** |
| Profit factor | **1.1096** |
| Avg win (net) | **+$1.1819** |
| Avg loss (net) | **$-0.4769** |
| Largest single win | **+$8.7343** (ESPORTSUSDT, 15m, reduce_size_mode) |
| Largest single loss | **$-7.0249** (PORTALUSDT, 1h, mean_reversion_mode) |
| Avg hold time | **1406s (0.39h)** |
| Max hold time | **21612s (6.00h)** |
| Min hold time | **1s** |
| Direction | **SHORT ONLY (100% of 595 trades)** |
| Unique symbols | **83** |
| Break-even cost/trade | **$0.0594 gross PnL/trade required just to cover fees** |

### 3.2 Fee Drag Analysis

The system generated +$56.83 gross PnL. After fees ($23.57) and slippage ($11.78),
only +$21.47 remains. Every trade must generate at least $0.0594 gross just
to break even. Trades with small wins (e.g., +$0.03 gross) become net losers after fees.

### 3.3 The Short-Only Structural Problem

All 595 closed trades are `action=short`. The system has no LONG exposure whatsoever.
The PPO model either:
1. Never produces a `long` action with confidence above the threshold, or
2. The strategy router blocks LONG before execution.

This means the system systematically loses during upward price moves regardless of signal quality.

---

## 4. Root Cause Analysis — Why Win Rate Is Low

### RC-1: TIER_2_TRAILING_STOP Fires at Loss 90.2% of the Time [CRITICAL]

**Impact:** 356 trades, -$124.82 cumulative PnL, 9.8% win rate.

The trailing stop is the system's single largest source of losses — more than stop losses
and more than take-profit exits (in trade count). The mechanism:

1. Position opens at entry price.
2. Price moves favorably enough to activate the trailing stop.
3. Price retraces within the symbol's natural noise range.
4. Trailing stop fires at a price lower than entry (net loss).

This pattern proves the trailing stop activation threshold is tighter than the symbol's
typical intraday noise. The position enters "trailing" mode at exactly the wrong level.

**Evidence:** Avg hold for trailing stop exits = 1,585s (26 min). Avg hold for stop-loss
exits = 463s (8 min). Trailing stops are held 3x longer, meaning the position was alive long
enough to go to profit, but the trailing stop then captured a loss.

**Fix:** Widen trailing stop distance. Consider ATR-based trailing stop (e.g., 1.5×ATR(14)).
A fixed bps trailing stop ignores the fact that BTCUSDT and ESPORTSUSDT have vastly different
volatility profiles.

### RC-2: trend_mode Loses Money in 5m and 4h [CRITICAL]

**Impact:** trend_mode|5m: 118 trades, -$16.90 net. trend_mode|4h: 119 trades, -$15.07 net.
Combined: 237 trades, -$31.97 net. These two cells are responsible for ALL system losses.

The remaining 358 trades across all other strategy/timeframe combinations show +$53.68 net PnL.

**Root cause hypothesis:**
- 5m signals are too noisy — small-timeframe trend predictions do not persist long enough
  to generate profit before the trailing stop fires on a normal retracement.
- 4h signals have large position hold times, but the 4h trend model appears to be calling
  direction incorrectly (WR=21.8%), possibly because the market is range-bound at larger TF
  while the 4h model sees micro-trends.

### RC-3: Zero LONG Trades [CRITICAL]

The system has placed 0 LONG trades in 595 closed positions. In any bull market phase, every
open short loses by construction. The PPO model either:
- Has a structural bias toward SHORT from its training distribution
- Has LONG blocked at the strategy router level (`PPO_ACTION_NOT_TRADABLE` for `long`)

This is likely the single biggest contributor to the 31% win rate being below 50% — in a
market that moves both ways, a short-only system has structural headwinds.

### RC-4: Fees and Slippage Consume 61% of Gross PnL [HIGH]

Gross: +$56.83. After fees ($23.57) + slippage ($11.78) = $35.35 cost.
Net: +$21.47.

On 595 trades, the average cost drag is $0.0594/trade. A trade that earns
+$0.05 gross becomes a -$0.01 net loser after costs. Many small-profit trailing stop exits
(9.8% winner) are erased entirely by the cost structure.

### RC-5: Missing Critical Features in All Trades [MEDIUM]

Every trade record shows missing features in the liquidation and liquidity contexts:
- `nearest_liquidation_level_above` / `_below`
- `liquidation_cascade_risk`
- `liquidation_pressure_direction`
- `nearest_bid_wall_distance_bps` / `_ask_wall_distance_bps`
- `volatility` (null in microstructure_context)

The model enters positions without knowing where the nearest liquidation cascade wall is.
When a position moves against the short, a liquidation cascade can accelerate the move.

### RC-6: Squeeze Evidence Score Is Null for All Trades [MEDIUM]

`squeeze_evidence_score` is null in all 595 records. The squeeze detection subsystem is not
operational. Short squeezes are the primary risk for short positions — the system has no
defense against them and no signal for when one is likely.

### RC-7: mean_reversion_mode 1h Has 80% WR But -$4.21 PnL (Fat Tail) [MEDIUM]

The 5 `mean_reversion_mode|1h` trades show 80% win rate but -$4.21 net PnL. This is
because one large loss (PORTALUSDT: -$7.02 at -2,699 bps) overwhelmed 4 wins. The mean
reversion model was correct 80% of the time but one position had no effective stop at a
small-enough level to prevent an extreme loss.

---

## 5. Strategy × Timeframe Cross-Analysis

| Strategy | TF | Trades | Wins | Losses | WR | Gross$ | Fees | Slip | Net$ | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| mean_reversion_mode | 15m | 6 | 5 | 1 | 83.3% | $1.364 | $0.119 | $0.059 | $1.185 | 4.623 |
| mean_reversion_mode | 1h | 5 | 4 | 1 | 80.0% | $-4.123 | $0.057 | $0.029 | $-4.209 ❌ | **0.401** |
| mean_reversion_mode | 1m | 5 | 5 | 0 | 100.0% | $1.277 | $0.047 | $0.024 | $1.206 | — |
| mean_reversion_mode | 4h | 2 | 2 | 0 | 100.0% | $0.654 | $0.019 | $0.010 | $0.625 | — |
| mean_reversion_mode | 5m | 5 | 2 | 3 | 40.0% | $0.534 | $0.072 | $0.036 | $0.426 | 2.420 |
| reduce_size_mode | 15m | 3 | 3 | 0 | 100.0% | $10.689 | $0.231 | $0.115 | $10.343 | — |
| reduce_size_mode | 1h | 3 | 2 | 1 | 66.7% | $11.023 | $0.438 | $0.219 | $10.366 | 6.860 |
| reduce_size_mode | 1m | 15 | 7 | 8 | 46.7% | $12.177 | $1.516 | $0.758 | $9.903 | 2.160 |
| reduce_size_mode | 4h | 3 | 3 | 0 | 100.0% | $8.583 | $0.333 | $0.166 | $8.084 | — |
| reduce_size_mode | 5m | 8 | 5 | 3 | 62.5% | $7.238 | $0.875 | $0.438 | $5.925 | 2.046 |
| trend_mode | 15m | 95 | 24 | 71 | 25.3% | $10.744 | $4.012 | $2.006 | $4.727 | 1.152 |
| trend_mode | 1h | 111 | 39 | 72 | 35.1% | $6.326 | $3.275 | $1.637 | $1.414 | 1.048 |
| trend_mode | 1m | 97 | 29 | 68 | 29.9% | $8.929 | $3.655 | $1.828 | $3.447 | 1.130 |
| trend_mode | 4h | 119 | 26 | 93 | 21.8% | $-7.800 | $4.846 | $2.423 | $-15.069 ❌ | **0.677** |
| trend_mode | 5m | 118 | 28 | 90 | 23.7% | $-10.790 | $4.074 | $2.037 | $-16.901 ❌ | **0.566** |

❌ = negative net PnL

---

## 6. Exit Reason Analysis

| Exit Reason | Count | % | WR | Avg Hold | Avg PnL | Total PnL |
|---|---|---|---|---|---|---|
| TIER_1_STOP_LOSS | 90 | 15.1% | 0.0% | 463s | $-0.7135 | $-64.2144 |
| TIER_2_TRAILING_STOP | 356 | 59.8% | 9.8% | 1585s | $-0.3510 | $-124.9726 |
| TIER_2_TAKE_PROFIT | 107 | 18.0% | 100.0% | 1357s | $1.3803 | $147.6893 |
| TIER_2_PROFIT_BANK | 35 | 5.9% | 100.0% | 481s | $1.4959 | $52.3562 |
| TIER_2_PROFIT_LOCK | 4 | 0.7% | 100.0% | 992s | $0.0549 | $0.2196 |
| TIER_4_MAX_HOLD_TIME | 3 | 0.5% | 100.0% | 21610s | $3.4647 | $10.3940 |

### Exit Reason × Strategy (top 15)

| Exit Reason | Strategy | Count |
|---|---|---|
| TIER_2_TRAILING_STOP | trend_mode | 339 |
| TIER_1_STOP_LOSS | trend_mode | 85 |
| TIER_2_TAKE_PROFIT | trend_mode | 80 |
| TIER_2_PROFIT_BANK | trend_mode | 30 |
| TIER_2_TAKE_PROFIT | mean_rever | 15 |
| TIER_2_TAKE_PROFIT | reduce_siz | 12 |
| TIER_2_TRAILING_STOP | reduce_siz | 12 |
| TIER_2_TRAILING_STOP | mean_rever | 5 |
| TIER_2_PROFIT_BANK | reduce_siz | 4 |
| TIER_1_STOP_LOSS | reduce_siz | 3 |
| TIER_2_PROFIT_LOCK | trend_mode | 3 |
| TIER_4_MAX_HOLD_TIME | trend_mode | 3 |
| TIER_1_STOP_LOSS | mean_rever | 2 |
| TIER_2_PROFIT_LOCK | reduce_siz | 1 |
| TIER_2_PROFIT_BANK | mean_rever | 1 |

---

## 7. Per-Symbol Full Results

Sorted by net PnL (worst first). ❌ = net loss.

| Symbol | Trades | Wins | Losses | WR | Gross$ | Fees | Slip | Net$ | Timeframes | Strategies |
|---|---|---|---|---|---|---|---|---|---|---|
| PORTALUSDT | 1 | 0 | 1 | 0.0% | $-7.0052 | $0.0132 | $0.0066 | $-7.0249 ❌ | 1h:1 | mean_r:1 |
| NIGHTUSDT | 5 | 0 | 5 | 0.0% | $-5.1570 | $0.3212 | $0.1606 | $-5.6387 ❌ | 1h:2,4h:2,5m:1 | trend:5 |
| ALLOUSDT | 18 | 4 | 14 | 22.2% | $-4.5654 | $0.5796 | $0.2898 | $-5.4348 ❌ | 15m:3,1h:4,1m:5,4h:6 | reduce:1,trend:17 |
| CRVUSDT | 14 | 2 | 12 | 14.3% | $-3.0838 | $0.6311 | $0.3155 | $-4.0304 ❌ | 15m:2,1h:3,1m:3,4h:3,5m:3 | reduce:1,trend:13 |
| DOTUSDT | 10 | 3 | 7 | 30.0% | $-1.9615 | $0.6304 | $0.3152 | $-2.9070 ❌ | 15m:1,1h:2,1m:4,4h:1,5m:2 | reduce:1,trend:9 |
| TIAUSDT | 3 | 0 | 3 | 0.0% | $-2.5824 | $0.1787 | $0.0894 | $-2.8505 ❌ | 1m:1,4h:1,5m:1 | trend:3 |
| ENAUSDT | 18 | 3 | 15 | 16.7% | $-1.8014 | $0.6077 | $0.3038 | $-2.7128 ❌ | 15m:1,1h:3,1m:6,4h:5,5m:3 | reduce:1,trend:17 |
| BIOUSDT | 28 | 8 | 20 | 28.6% | $-1.4992 | $0.7358 | $0.3679 | $-2.6030 ❌ | 15m:5,1h:7,1m:5,4h:6,5m:5 | reduce:1,trend:27 |
| TRUMPUSDT | 3 | 0 | 3 | 0.0% | $-1.8722 | $0.2230 | $0.1115 | $-2.2068 ❌ | 15m:2,5m:1 | trend:3 |
| PUMPUSDT | 2 | 0 | 2 | 0.0% | $-1.8566 | $0.1433 | $0.0717 | $-2.0716 ❌ | 1h:1,5m:1 | trend:2 |
| NEARUSDT | 10 | 2 | 8 | 20.0% | $-1.4922 | $0.3541 | $0.1770 | $-2.0233 ❌ | 1h:4,1m:4,4h:2 | trend:10 |
| HUSDT | 21 | 8 | 13 | 38.1% | $-1.1239 | $0.4314 | $0.2157 | $-1.7711 ❌ | 15m:3,1h:2,1m:8,4h:2,5m:6 | reduce:1,trend:20 |
| SEIUSDT | 2 | 0 | 2 | 0.0% | $-1.5441 | $0.1432 | $0.0716 | $-1.7589 ❌ | 1h:1,4h:1 | trend:2 |
| RENDERUSDT | 2 | 0 | 2 | 0.0% | $-1.4893 | $0.1316 | $0.0658 | $-1.6866 ❌ | 4h:1,5m:1 | trend:2 |
| TRXUSDT | 1 | 0 | 1 | 0.0% | $-1.1478 | $0.3340 | $0.1670 | $-1.6489 ❌ | 4h:1 | trend:1 |
| SUIUSDT | 2 | 0 | 2 | 0.0% | $-1.3459 | $0.1566 | $0.0783 | $-1.5808 ❌ | 15m:1,5m:1 | trend:2 |
| AAVEUSDT | 17 | 2 | 15 | 11.8% | $-0.2322 | $0.8359 | $0.4179 | $-1.4861 ❌ | 15m:5,1h:2,1m:2,4h:5,5m:3 | reduce:1,trend:16 |
| OPUSDT | 5 | 1 | 4 | 20.0% | $-0.9985 | $0.1845 | $0.0922 | $-1.2752 ❌ | 15m:1,1m:1,4h:1,5m:2 | trend:5 |
| VIRTUALUSDT | 2 | 0 | 2 | 0.0% | $-1.0649 | $0.1200 | $0.0600 | $-1.2448 ❌ | 1m:1,4h:1 | trend:2 |
| XPLUSDT | 1 | 0 | 1 | 0.0% | $-1.1312 | $0.0579 | $0.0289 | $-1.2180 ❌ | 5m:1 | trend:1 |
| MEGAUSDT | 9 | 3 | 6 | 33.3% | $-0.6909 | $0.3361 | $0.1680 | $-1.1950 ❌ | 15m:3,1h:1,4h:2,5m:3 | trend:9 |
| BEATUSDT | 42 | 19 | 23 | 45.2% | $-0.2348 | $0.6322 | $0.3161 | $-1.1831 ❌ | 15m:5,1h:13,1m:13,4h:5,5m:6 | reduce:1,trend:41 |
| XLMUSDT | 1 | 0 | 1 | 0.0% | $-0.9474 | $0.0551 | $0.0276 | $-1.0301 ❌ | 5m:1 | trend:1 |
| PENDLEUSDT | 3 | 0 | 3 | 0.0% | $-0.6286 | $0.1585 | $0.0793 | $-0.8664 ❌ | 15m:1,4h:1,5m:1 | trend:3 |
| LDOUSDT | 7 | 1 | 6 | 14.3% | $-0.0386 | $0.3887 | $0.1944 | $-0.6217 ❌ | 15m:1,1h:1,1m:1,4h:2,5m:2 | reduce:1,trend:6 |
| 1000BONKUSDT | 1 | 0 | 1 | 0.0% | $-0.5174 | $0.0360 | $0.0180 | $-0.5714 ❌ | 5m:1 | trend:1 |
| 1000SHIBUSDT | 3 | 0 | 3 | 0.0% | $-0.3022 | $0.0655 | $0.0327 | $-0.4004 ❌ | 1h:1,5m:2 | trend:3 |
| BTCUSDT | 1 | 0 | 1 | 0.0% | $-0.2311 | $0.0641 | $0.0320 | $-0.3272 ❌ | 15m:1 | mean_r:1 |
| BARDUSDT | 2 | 1 | 1 | 50.0% | $-0.2036 | $0.0295 | $0.0148 | $-0.2479 ❌ | 1m:1,5m:1 | mean_r:1,trend:1 |
| PIPPINUSDT | 1 | 0 | 1 | 0.0% | $-0.1925 | $0.0084 | $0.0042 | $-0.2050 ❌ | 5m:1 | mean_r:1 |
| 1000FLOKIUSDT | 3 | 1 | 2 | 33.3% | $-0.0888 | $0.0580 | $0.0290 | $-0.1757 ❌ | 5m:3 | mean_r:1,trend:2 |
| POLUSDT | 1 | 0 | 1 | 0.0% | $-0.1253 | $0.0276 | $0.0138 | $-0.1667 ❌ | 5m:1 | trend:1 |
| 1000PEPEUSDT | 2 | 1 | 1 | 50.0% | $-0.0889 | $0.0391 | $0.0195 | $-0.1475 ❌ | 1m:1,5m:1 | mean_r:1,trend:1 |
| ARBUSDT | 18 | 5 | 13 | 27.8% | $1.0216 | $0.7416 | $0.3708 | $-0.0908 ❌ | 15m:2,1h:5,4h:3,5m:8 | reduce:1,trend:17 |
| BANKUSDT | 2 | 1 | 1 | 50.0% | $-0.0218 | $0.0429 | $0.0214 | $-0.0861 ❌ | 4h:1,5m:1 | trend:2 |
| UNIUSDT | 1 | 0 | 1 | 0.0% | $-0.0297 | $0.0183 | $0.0092 | $-0.0572 ❌ | 5m:1 | mean_r:1 |
| WIFUSDT | 1 | 0 | 1 | 0.0% | $-0.0054 | $0.0219 | $0.0109 | $-0.0382 ❌ | 5m:1 | mean_r:1 |
| INJUSDT | 8 | 2 | 6 | 25.0% | $0.6662 | $0.3978 | $0.1989 | $0.0695 | 15m:3,1h:1,1m:1,4h:2,5m:1 | reduce:1,trend:7 |
| LTCUSDT | 1 | 1 | 0 | 100.0% | $0.1263 | $0.0168 | $0.0084 | $0.1011 | 1m:1 | mean_r:1 |
| XRPUSDT | 1 | 1 | 0 | 100.0% | $0.1594 | $0.0132 | $0.0066 | $0.1396 | 15m:1 | mean_r:1 |
| SOLUSDT | 1 | 1 | 0 | 100.0% | $0.2479 | $0.0072 | $0.0036 | $0.2371 | 15m:1 | mean_r:1 |
| LINKUSDT | 1 | 1 | 0 | 100.0% | $0.2732 | $0.0079 | $0.0040 | $0.2613 | 4h:1 | mean_r:1 |
| ETCUSDT | 3 | 1 | 2 | 33.3% | $0.4404 | $0.1191 | $0.0595 | $0.2617 | 1h:1,4h:2 | mean_r:1,trend:2 |
| AUCTIONUSDT | 2 | 2 | 0 | 100.0% | $0.3560 | $0.0345 | $0.0172 | $0.3043 | 1h:1,5m:1 | mean_r:1,trend:1 |
| DOGEUSDT | 1 | 1 | 0 | 100.0% | $0.3207 | $0.0099 | $0.0049 | $0.3058 | 1h:1 | mean_r:1 |
| FETUSDT | 10 | 3 | 7 | 30.0% | $1.1370 | $0.5420 | $0.2710 | $0.3240 | 15m:1,1h:1,1m:5,5m:3 | reduce:1,trend:9 |
| RAVEUSDT | 1 | 1 | 0 | 100.0% | $0.3671 | $0.0120 | $0.0060 | $0.3491 | 5m:1 | mean_r:1 |
| AVNTUSDT | 2 | 1 | 1 | 50.0% | $0.4073 | $0.0365 | $0.0182 | $0.3526 | 4h:1,5m:1 | mean_r:1,trend:1 |
| RIVERUSDT | 1 | 1 | 0 | 100.0% | $0.3908 | $0.0103 | $0.0052 | $0.3753 | 1m:1 | mean_r:1 |
| FARTCOINUSDT | 1 | 1 | 0 | 100.0% | $0.4386 | $0.0114 | $0.0057 | $0.4216 | 15m:1 | mean_r:1 |
| PENGUUSDT | 1 | 1 | 0 | 100.0% | $0.5095 | $0.0153 | $0.0076 | $0.4866 | 15m:1 | mean_r:1 |
| APTUSDT | 20 | 7 | 13 | 35.0% | $1.6885 | $0.7829 | $0.3914 | $0.5141 | 15m:3,1h:2,1m:5,4h:4,5m:6 | reduce:1,trend:19 |
| DASHUSDT | 9 | 2 | 7 | 22.2% | $1.2994 | $0.4745 | $0.2372 | $0.5877 | 15m:1,1h:2,1m:2,4h:2,5m:2 | reduce:1,trend:8 |
| ASTERUSDT | 3 | 2 | 1 | 66.7% | $0.7145 | $0.0400 | $0.0200 | $0.6545 | 15m:1,5m:2 | mean_r:1,trend:2 |
| ETHUSDT | 1 | 1 | 0 | 100.0% | $0.7498 | $0.0194 | $0.0097 | $0.7207 | 1h:1 | mean_r:1 |
| ALICEUSDT | 3 | 2 | 1 | 66.7% | $0.8153 | $0.0530 | $0.0265 | $0.7358 | 1m:1,5m:2 | mean_r:1,trend:2 |
| AVAXUSDT | 11 | 5 | 6 | 45.5% | $1.7609 | $0.5788 | $0.2894 | $0.8927 | 15m:2,1h:2,4h:5,5m:2 | reduce:1,trend:10 |
| JTOUSDT | 10 | 1 | 9 | 10.0% | $1.5069 | $0.3855 | $0.1927 | $0.9287 | 15m:1,1h:3,1m:1,4h:3,5m:2 | reduce:1,trend:9 |
| MITOUSDT | 7 | 2 | 5 | 28.6% | $1.3686 | $0.1796 | $0.0898 | $1.0992 | 15m:3,1h:1,1m:1,4h:1,5m:1 | trend:7 |
| ICPUSDT | 7 | 2 | 5 | 28.6% | $1.9763 | $0.5185 | $0.2593 | $1.1985 | 15m:1,1h:1,1m:1,4h:3,5m:1 | reduce:1,trend:6 |
| ALGOUSDT | 18 | 4 | 14 | 22.2% | $2.3239 | $0.6467 | $0.3234 | $1.3538 | 15m:2,1h:3,1m:5,4h:6,5m:2 | reduce:1,trend:17 |
| LABUSDT | 10 | 4 | 6 | 40.0% | $1.9433 | $0.3588 | $0.1794 | $1.4051 | 15m:2,1h:1,1m:3,4h:2,5m:2 | reduce:1,trend:9 |
| FILUSDT | 18 | 4 | 14 | 22.2% | $2.5415 | $0.6356 | $0.3178 | $1.5881 | 15m:6,1h:1,1m:2,4h:5,5m:4 | reduce:1,trend:17 |
| CHZUSDT | 15 | 2 | 13 | 13.3% | $2.5322 | $0.5312 | $0.2656 | $1.7355 | 15m:4,1h:1,1m:2,4h:5,5m:3 | reduce:1,trend:14 |
| ZECUSDT | 1 | 1 | 0 | 100.0% | $1.8567 | $0.0374 | $0.0187 | $1.8006 | 1m:1 | trend:1 |
| ADAUSDT | 11 | 2 | 9 | 18.2% | $2.9025 | $0.6495 | $0.3247 | $1.9283 | 15m:2,1h:2,1m:4,4h:3 | reduce:1,trend:10 |
| ATOMUSDT | 5 | 1 | 4 | 20.0% | $2.7297 | $0.4729 | $0.2364 | $2.0204 | 1m:2,4h:1,5m:2 | reduce:1,trend:4 |
| ONDOUSDT | 5 | 3 | 2 | 60.0% | $2.5413 | $0.3220 | $0.1610 | $2.0583 | 15m:1,1h:2,1m:1,5m:1 | trend:5 |
| HBARUSDT | 7 | 2 | 5 | 28.6% | $2.9459 | $0.5627 | $0.2813 | $2.1019 | 15m:1,1h:1,1m:2,4h:2,5m:1 | reduce:1,trend:6 |
| LITUSDT | 9 | 2 | 7 | 22.2% | $2.8787 | $0.3607 | $0.1804 | $2.3376 | 15m:5,1h:2,4h:1,5m:1 | reduce:1,trend:8 |
| WLDUSDT | 1 | 1 | 0 | 100.0% | $2.6139 | $0.0840 | $0.0420 | $2.4879 | 15m:1 | trend:1 |
| SUNUSDT | 1 | 1 | 0 | 100.0% | $3.1098 | $0.3190 | $0.1595 | $2.6313 | 1m:1 | trend:1 |
| XMRUSDT | 1 | 1 | 0 | 100.0% | $2.7640 | $0.0866 | $0.0433 | $2.6341 | 4h:1 | trend:1 |
| BSBUSDT | 21 | 8 | 13 | 38.1% | $3.2069 | $0.3707 | $0.1853 | $2.6508 | 15m:5,1h:6,1m:3,4h:3,5m:4 | reduce:1,trend:20 |
| HYPEUSDT | 13 | 4 | 9 | 30.8% | $3.5080 | $0.5245 | $0.2623 | $2.7212 | 15m:3,1h:3,1m:3,4h:1,5m:3 | reduce:1,trend:12 |
| BCHUSDT | 11 | 2 | 9 | 18.2% | $4.1585 | $0.6361 | $0.3181 | $3.2043 | 1h:5,1m:2,4h:1,5m:3 | reduce:1,trend:10 |
| XAUTUSDT | 1 | 1 | 0 | 100.0% | $3.7460 | $0.3191 | $0.1596 | $3.2673 | 15m:1 | trend:1 |
| HOMEUSDT | 19 | 7 | 12 | 36.8% | $4.7628 | $0.4972 | $0.2486 | $4.0170 | 15m:1,1h:5,1m:3,4h:4,5m:6 | reduce:1,trend:18 |
| PAXGUSDT | 1 | 1 | 0 | 100.0% | $4.9821 | $0.3245 | $0.1622 | $4.4954 | 15m:1 | trend:1 |
| TAOUSDT | 3 | 1 | 2 | 33.3% | $4.9548 | $0.2903 | $0.1451 | $4.5194 | 15m:2,5m:1 | trend:3 |
| AEROUSDT | 16 | 6 | 10 | 37.5% | $6.1542 | $0.6988 | $0.3494 | $5.1059 | 15m:3,1h:4,1m:2,4h:4,5m:3 | reduce:1,trend:15 |
| ESPORTSUSDT | 37 | 17 | 20 | 45.9% | $7.9575 | $0.4519 | $0.2260 | $7.2796 | 15m:7,1h:12,1m:6,4h:8,5m:4 | reduce:1,trend:36 |
| BNBUSDT | 3 | 2 | 1 | 66.7% | $8.2703 | $0.5859 | $0.2929 | $7.3915 | 1h:1,4h:1,5m:1 | reduce:1,trend:2 |

---

## 8. Per-Timeframe Full Results

| TF | Trades | Wins | Losses | WR | Gross$ | Fees | Slip | Net$ | PF | Avg Hold |
|---|---|---|---|---|---|---|---|---|---|---|
| 1m | 117 | 41 | 76 | 35.0% | $22.3832 | $5.2182 | $2.6091 | $14.5558 | 1.416 | 1417s |
| 5m | 131 | 35 | 96 | 26.7% | $-3.0179 | $5.0211 | $2.5106 | $-10.5496 ❌ | 0.765 | 1338s |
| 15m | 104 | 32 | 72 | 30.8% | $22.7972 | $4.3615 | $2.1807 | $16.2550 | 1.519 | 1636s |
| 1h | 119 | 45 | 74 | 37.8% | $13.2253 | $3.7698 | $1.8849 | $7.5706 | 1.199 | 1108s |
| 4h | 124 | 31 | 93 | 25.0% | $1.4372 | $5.1980 | $2.5990 | $-6.3598 ❌ | 0.864 | 1562s |

---

## 9. Per-Strategy Full Results

| Strategy | Trades | Wins | Losses | WR | Gross$ | Fees | Slip | Net$ | PF | Top Exit Reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| reduce_size_mode | 32 | 20 | 12 | 62.5% | $49.7092 | $3.3921 | $1.6960 | $44.6212 | 3.795 | TIER_2_TAKE_PROFIT:12, TIER_2_TRAILING_STOP:12, TIER_2_PROFIT_BANK:4 |
| mean_reversion_mode | 23 | 18 | 5 | 78.3% | $-0.2933 | $0.3149 | $0.1574 | $-0.7656 ❌ | 0.900 | TIER_2_TAKE_PROFIT:15, TIER_2_TRAILING_STOP:5, TIER_1_STOP_LOSS:2 |
| trend_mode | 540 | 146 | 394 | 27.0% | $7.4091 | $19.8617 | $9.9309 | $-22.3835 ❌ | 0.870 | TIER_2_TRAILING_STOP:339, TIER_1_STOP_LOSS:85, TIER_2_TAKE_PROFIT:80 |

---

## 10. Worst-10 Trades — Full Detail

### Worst #1: PORTALUSDT — Net $-7.0249 USD (-2698.8 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_PORTALUSDT_1_7024949` |
| Position ID | `paper_pos_PORTALUSDT` |
| Symbol | **PORTALUSDT** |
| Side / Action | short / short |
| Timeframe | 1h |
| Strategy Mode | mean_reversion_mode |
| Entry Reason | mean_reversion_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | RANGE |
| Market Regime at Exit | RANGE |
| Entry Price | **$0.01182** |
| Exit Price | **$0.01501** |
| Price Move (% adverse to short) | **+26.988%** |
| Quantity | 2195.9787 units |
| Gross PnL | $-7.005172 |
| Fees | -$0.013185 |
| Slippage | -$0.006592 |
| Net PnL | **$-7.024949** |
| Net PnL (bps) | **-2698.82 bps** |
| Winner | False |
| Hold Time | 194s (0.054h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `sig_f2a3473209644759585797f9` |
| Entry Prediction ID | `v2h_ffda9a8d28b971b6713540d389f7626d` |
| Entry Feature Snapshot ID | `None` |
| Entry Market State ID | `mstate_8b6a84ea165068cec8e6` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T17:44:15Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_PORTALUSDT_1_7024949` |
| Source Fill IDs | 1 fills: `v2_paper_intent_PORTALUSDT` |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features |  |

### Worst #2: NIGHTUSDT — Net $-4.0888 USD (-115.4 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_NIGHTUSDT_12_4088783` |
| Position ID | `paper_pos_NIGHTUSDT` |
| Symbol | **NIGHTUSDT** |
| Side / Action | short / short |
| Timeframe | 4h |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.030191698** |
| Exit Price | **$0.03054** |
| Price Move (% adverse to short) | **+1.154%** |
| Quantity | 11152.4605 units |
| Gross PnL | $-3.884426 |
| Fees | -$0.136238 |
| Slippage | -$0.068119 |
| Net PnL | **$-4.088784** |
| Net PnL (bps) | **-115.36 bps** |
| Winner | False |
| Hold Time | 2930s (0.814h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_00ae414347964f9202073b869e7c052f` |
| Entry Prediction ID | `v2h_00ae414347964f9202073b869e7c052f` |
| Entry Feature Snapshot ID | `v2_fsnap_d1a06da78be3befaf011ada466041e119eaca1788a7c6d9f0f83e2f3b112a5a4` |
| Entry Market State ID | `mstate_75f42e707e316216d5d8` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T14:32:48Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_NIGHTUSDT_12_4088783` |
| Source Fill IDs | 12 fills: `v2h_00ae414347964f9202073b869e7c052f`, `v2_paper_intent_NIGHTUSDT`, `v2h_1fe69e730e19098779070b25e1db7c9c`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features |  |

### Worst #3: CRVUSDT — Net $-2.8348 USD (-165.6 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_CRVUSDT_4_2834842` |
| Position ID | `paper_pos_CRVUSDT` |
| Symbol | **CRVUSDT** |
| Side / Action | short / short |
| Timeframe | 5m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.2244828** |
| Exit Price | **$0.2282** |
| Price Move (% adverse to short) | **+1.656%** |
| Quantity | 735.5355 units |
| Gross PnL | $-2.734133 |
| Fees | -$0.067140 |
| Slippage | -$0.033570 |
| Net PnL | **$-2.834842** |
| Net PnL (bps) | **-165.59 bps** |
| Winner | False |
| Hold Time | 386s (0.107h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_a32a1b6a6eecab41a68868074ee26825` |
| Entry Prediction ID | `v2h_a32a1b6a6eecab41a68868074ee26825` |
| Entry Feature Snapshot ID | `v2_fsnap_6f275f613a98c27676c05c5a2004c7174d773828852ec0751e0a0afcc14d6bd4` |
| Entry Market State ID | `mstate_fef51d995b35f1b62332` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:30:09Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_CRVUSDT_4_2834842` |
| Source Fill IDs | 4 fills: `v2h_a32a1b6a6eecab41a68868074ee26825`, `v2_paper_intent_CRVUSDT`, `v2h_0cdf46c362c72b217d01900b7cdfb69d`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #4: HUSDT — Net $-2.3495 USD (-165.7 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_HUSDT_3_2349489` |
| Position ID | `paper_pos_HUSDT` |
| Symbol | **HUSDT** |
| Side / Action | short / short |
| Timeframe | 1m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.25039** |
| Exit Price | **$0.25454** |
| Price Move (% adverse to short) | **+1.657%** |
| Quantity | 546.0470 units |
| Gross PnL | $-2.266095 |
| Fees | -$0.055596 |
| Slippage | -$0.027798 |
| Net PnL | **$-2.349490** |
| Net PnL (bps) | **-165.74 bps** |
| Winner | False |
| Hold Time | 127s (0.035h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_17a603afa05be33970486b0deb852945` |
| Entry Prediction ID | `v2h_17a603afa05be33970486b0deb852945` |
| Entry Feature Snapshot ID | `v2_fsnap_a7170c63c2d42947a756bddab335073f0c04496f3281e0f98425960601d1adb7` |
| Entry Market State ID | `mstate_c43f24317747f7292d12` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:25:50Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_HUSDT_3_2349489` |
| Source Fill IDs | 3 fills: `v2h_17a603afa05be33970486b0deb852945`, `v2_paper_intent_HUSDT`, `v2h_4ec0d1c47f9b99fb5c5ac97f9c0ef5b2` |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #5: LABUSDT — Net $-2.2117 USD (-74.5 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_LABUSDT_9_2211683` |
| Position ID | `paper_pos_LABUSDT` |
| Symbol | **LABUSDT** |
| Side / Action | short / short |
| Timeframe | 1m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_TRAILING_STOP** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$15.590782** |
| Exit Price | **$15.707** |
| Price Move (% adverse to short) | **+0.745%** |
| Quantity | 17.6030 units |
| Gross PnL | $-2.045789 |
| Fees | -$0.110596 |
| Slippage | -$0.055298 |
| Net PnL | **$-2.211684** |
| Net PnL (bps) | **-74.54 bps** |
| Winner | False |
| Hold Time | 1404s (0.390h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_0d33eba19fc47af2cdf5bbb811d9c13e` |
| Entry Prediction ID | `v2h_0d33eba19fc47af2cdf5bbb811d9c13e` |
| Entry Feature Snapshot ID | `v2_fsnap_f2a5ea23a234b030f067f0b9356658663d9f3476ffb4c46b34441d2d53fce125` |
| Entry Market State ID | `mstate_ea0cb70262837dcd0b04` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:47:07Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_LABUSDT_9_2211683` |
| Source Fill IDs | 9 fills: `v2h_0d33eba19fc47af2cdf5bbb811d9c13e`, `v2_paper_intent_LABUSDT`, `v2h_7107423149abedf64179172f2473a0e9`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #6: BIOUSDT — Net $-2.1334 USD (-196.9 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_BIOUSDT_3_2133444` |
| Position ID | `paper_pos_BIOUSDT` |
| Symbol | **BIOUSDT** |
| Side / Action | short / short |
| Timeframe | 4h |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.034108442** |
| Exit Price | **$0.03478** |
| Price Move (% adverse to short) | **+1.969%** |
| Quantity | 3081.1152 units |
| Gross PnL | $-2.069147 |
| Fees | -$0.042864 |
| Slippage | -$0.021432 |
| Net PnL | **$-2.133444** |
| Net PnL (bps) | **-196.89 bps** |
| Winner | False |
| Hold Time | 839s (0.233h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_d27b7c9d8650391eb89e1df0e41ca35e` |
| Entry Prediction ID | `v2h_d27b7c9d8650391eb89e1df0e41ca35e` |
| Entry Feature Snapshot ID | `v2_fsnap_39929d1de85dd50356e699c3f466af93d4eed62d35ef26ec46cf954b95608e43` |
| Entry Market State ID | `mstate_5c3abbd5002ffb1d3f37` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T16:05:06Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_BIOUSDT_3_2133444` |
| Source Fill IDs | 3 fills: `v2h_d27b7c9d8650391eb89e1df0e41ca35e`, `v2h_10e1f076490c6662ba13d1138b33c105`, `v2h_21049386a2620330d30b2d9ecc588b0e` |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #7: ESPORTSUSDT — Net $-1.8021 USD (-544.1 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_ESPORTSUSDT_1_1802138` |
| Position ID | `paper_pos_ESPORTSUSDT` |
| Symbol | **ESPORTSUSDT** |
| Side / Action | short / short |
| Timeframe | 1h |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.07682** |
| Exit Price | **$0.081** |
| Price Move (% adverse to short) | **+5.441%** |
| Quantity | 426.1785 units |
| Gross PnL | $-1.781426 |
| Fees | -$0.013808 |
| Slippage | -$0.006904 |
| Net PnL | **$-1.802138** |
| Net PnL (bps) | **-544.13 bps** |
| Winner | False |
| Hold Time | 27s (0.007h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_10fabff17f97f02127f534bff22e9965` |
| Entry Prediction ID | `v2h_10fabff17f97f02127f534bff22e9965` |
| Entry Feature Snapshot ID | `v2_fsnap_7fdfaafc814c3359cabb718773b7741ce1b7e48be3693a13ef19474cc4d8e7ce` |
| Entry Market State ID | `mstate_f47203f3b0c05b000faf` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:57:08Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_ESPORTSUSDT_1_1802138` |
| Source Fill IDs | 1 fills: `v2h_10fabff17f97f02127f534bff22e9965` |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #8: ALLOUSDT — Net $-1.7690 USD (-124.8 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_ALLOUSDT_4_1769024` |
| Position ID | `paper_pos_ALLOUSDT` |
| Symbol | **ALLOUSDT** |
| Side / Action | short / short |
| Timeframe | 1h |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_1_STOP_LOSS** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.38842177** |
| Exit Price | **$0.39327** |
| Price Move (% adverse to short) | **+1.248%** |
| Quantity | 347.9458 units |
| Gross PnL | $-1.686923 |
| Fees | -$0.054735 |
| Slippage | -$0.027367 |
| Net PnL | **$-1.769025** |
| Net PnL (bps) | **-124.82 bps** |
| Winner | False |
| Hold Time | 255s (0.071h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_50d2c2947ab4200a523e552bba371f5f` |
| Entry Prediction ID | `v2h_50d2c2947ab4200a523e552bba371f5f` |
| Entry Feature Snapshot ID | `v2_fsnap_c30471640586a832d50a927df3bf98624afe53481144ad6e6103372267b25a2c` |
| Entry Market State ID | `mstate_80bf82e133be6f142874` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:27:58Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_ALLOUSDT_4_1769024` |
| Source Fill IDs | 4 fills: `v2h_50d2c2947ab4200a523e552bba371f5f`, `v2_paper_intent_ALLOUSDT`, `v2h_0c622e63742789671bac1a4a17540918`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

### Worst #9: PUMPUSDT — Net $-1.7587 USD (-66.8 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_PUMPUSDT_8_1758651` |
| Position ID | `paper_pos_PUMPUSDT` |
| Symbol | **PUMPUSDT** |
| Side / Action | short / short |
| Timeframe | 5m |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TRAILING_STOP** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.0014711741** |
| Exit Price | **$0.001481** |
| Price Move (% adverse to short) | **+0.668%** |
| Quantity | 164138.1782 units |
| Gross PnL | $-1.612798 |
| Fees | -$0.097235 |
| Slippage | -$0.048618 |
| Net PnL | **$-1.758651** |
| Net PnL (bps) | **-66.79 bps** |
| Winner | False |
| Hold Time | 1600s (0.444h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_274196e1c37cbb0d60c0b8c272253986` |
| Entry Prediction ID | `v2h_274196e1c37cbb0d60c0b8c272253986` |
| Entry Feature Snapshot ID | `v2_fsnap_99fac667cbcd0a70bed9cea7ca3fd2db8281c66c6ac698785940e0b29e264086` |
| Entry Market State ID | `mstate_af1590cab7d62e9b089e` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T14:19:02Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_PUMPUSDT_8_1758651` |
| Source Fill IDs | 8 fills: `v2h_274196e1c37cbb0d60c0b8c272253986`, `v2_paper_intent_PUMPUSDT`, `v2h_0a6f28e77491d562804c76f4deae30a9`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features |  |

### Worst #10: BNBUSDT — Net $-1.7083 USD (-29.6 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_BNBUSDT_21_1708255` |
| Position ID | `paper_pos_BNBUSDT` |
| Symbol | **BNBUSDT** |
| Side / Action | short / short |
| Timeframe | 4h |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TRAILING_STOP** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$576.82052** |
| Exit Price | **$578.53** |
| Price Move (% adverse to short) | **+0.296%** |
| Quantity | 0.8306 units |
| Gross PnL | $-1.419932 |
| Fees | -$0.192216 |
| Slippage | -$0.096108 |
| Net PnL | **$-1.708255** |
| Net PnL (bps) | **-29.64 bps** |
| Winner | False |
| Hold Time | 12155s (3.376h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_05db20b1359cc86f6131b99422775aab` |
| Entry Prediction ID | `v2h_05db20b1359cc86f6131b99422775aab` |
| Entry Feature Snapshot ID | `v2_fsnap_2662a0bb466b48eb1e94545b508fed46bc653bbb53bb62c8c731250b8df4d720` |
| Entry Market State ID | `mstate_ea60e19efaf087847e52` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T19:44:52Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_BNBUSDT_21_1708255` |
| Source Fill IDs | 21 fills: `v2h_05db20b1359cc86f6131b99422775aab`, `v2h_01aeee1a834ab62435a8dd3e90478a1f`, `v2h_18501fe87affba6225f49d99eb41e8da`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |
| Missing Features | nearest_liquidation_level_above, nearest_liquidation_level_below, liquidation_cascade_risk, liquidation_pressure_direction, liquidation_count_5m |

---

## 11. Best-10 Trades — Full Detail

### Best #1: BNBUSDT — Net +$8.7343 USD (+123.3 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_BNBUSDT_27_8734279` |
| Position ID | `paper_pos_BNBUSDT` |
| Symbol | **BNBUSDT** |
| Side / Action | short / short |
| Timeframe | 1h |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$590.44222** |
| Exit Price | **$583.16** |
| Price Move (% favorable to short) | **-1.233%** |
| Quantity | 1.2599 units |
| Gross PnL | +$9.175126 |
| Fees | -$0.293898 |
| Slippage | -$0.146949 |
| Net PnL | **+$8.734280** |
| Net PnL (bps) | **+123.34 bps** |
| Winner | True |
| Hold Time | 7290s (2.025h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_0cc5fdce750b2dbe72a4897bbceff942` |
| Entry Prediction ID | `v2h_0cc5fdce750b2dbe72a4897bbceff942` |
| Entry Feature Snapshot ID | `v2_fsnap_cd58f1fbafe2e0b6290b1b484d0fcf02c6727656efdedef31c9fe179e71c1c5f` |
| Entry Market State ID | `mstate_7f8b7a57933f4c4b5fcc` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T15:25:13Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_BNBUSDT_27_8734279` |
| Source Fill IDs | 27 fills: `v2h_0cc5fdce750b2dbe72a4897bbceff942`, `v2_paper_intent_BNBUSDT`, `v2h_551e85c22eb55bc5d51ec15c51790308`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #2: TAOUSDT — Net +$5.6194 USD (+123.8 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_TAOUSDT_17_5619401` |
| Position ID | `paper_pos_TAOUSDT` |
| Symbol | **TAOUSDT** |
| Side / Action | short / short |
| Timeframe | 15m |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$239.13044** |
| Exit Price | **$236.17** |
| Price Move (% favorable to short) | **-1.238%** |
| Quantity | 1.9936 units |
| Gross PnL | +$5.901897 |
| Fees | -$0.188330 |
| Slippage | -$0.094165 |
| Net PnL | **+$5.619402** |
| Net PnL (bps) | **+123.80 bps** |
| Winner | True |
| Hold Time | 5006s (1.391h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_1302aab206760db964130671970dade4` |
| Entry Prediction ID | `v2h_1302aab206760db964130671970dade4` |
| Entry Feature Snapshot ID | `v2_fsnap_c7ddf69cd7ecdfa3d1b2bcdfa382cf1f7651a0b4813654296341e90bf6de00ae` |
| Entry Market State ID | `mstate_98657db6c3a16ccc7b37` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T15:44:32Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_TAOUSDT_17_5619401` |
| Source Fill IDs | 17 fills: `v2h_1302aab206760db964130671970dade4`, `v2h_0dd89c97cc27e68ae852dabdc67f030d`, `v2h_3dd338851766b40ab81a56b4f447a445`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #3: AEROUSDT — Net +$5.3068 USD (+266.6 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_AEROUSDT_6_5306759` |
| Position ID | `paper_pos_AEROUSDT` |
| Symbol | **AEROUSDT** |
| Side / Action | short / short |
| Timeframe | 1m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_PROFIT_BANK** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.47732789** |
| Exit Price | **$0.4646** |
| Price Move (% favorable to short) | **-2.666%** |
| Quantity | 426.2756 units |
| Gross PnL | +$5.425589 |
| Fees | -$0.079219 |
| Slippage | -$0.039610 |
| Net PnL | **+$5.306760** |
| Net PnL (bps) | **+266.65 bps** |
| Winner | True |
| Hold Time | 767s (0.213h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_15846d9ded67dd2d612385b486f6f0e7` |
| Entry Prediction ID | `v2h_15846d9ded67dd2d612385b486f6f0e7` |
| Entry Feature Snapshot ID | `v2_fsnap_806f527cf3bc7b9a48094be82a14deb2dd1cbb345409559af945a59c2c6aa08d` |
| Entry Market State ID | `mstate_5a741c8619093dcd86b7` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:36:30Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_AEROUSDT_6_5306759` |
| Source Fill IDs | 6 fills: `v2h_15846d9ded67dd2d612385b486f6f0e7`, `v2_paper_intent_AEROUSDT`, `v2h_219e190e3147be579286bd9d3e955cc7`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #4: PAXGUSDT — Net +$4.4954 USD (+61.0 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_PAXGUSDT_28_4495440` |
| Position ID | `paper_pos_PAXGUSDT` |
| Symbol | **PAXGUSDT** |
| Side / Action | short / short |
| Timeframe | 15m |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_4_MAX_HOLD_TIME** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$4237.8393** |
| Exit Price | **$4211.97** |
| Price Move (% favorable to short) | **-0.610%** |
| Quantity | 0.1926 units |
| Gross PnL | +$4.982149 |
| Fees | -$0.324472 |
| Slippage | -$0.162236 |
| Net PnL | **+$4.495441** |
| Net PnL (bps) | **+61.04 bps** |
| Winner | True |
| Hold Time | 21609s (6.003h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_48a95b0d0c0882a02c2a6cd14ec19276` |
| Entry Prediction ID | `v2h_48a95b0d0c0882a02c2a6cd14ec19276` |
| Entry Feature Snapshot ID | `v2_fsnap_fc687064a54b9cf1274ff7472b5695e2853f6c96400114f3153bee0583f94bcd` |
| Entry Market State ID | `mstate_1e736b5f8bb61e00bc60` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T19:52:31Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_PAXGUSDT_28_4495440` |
| Source Fill IDs | 28 fills: `v2h_48a95b0d0c0882a02c2a6cd14ec19276`, `v2_paper_intent_PAXGUSDT`, `v2h_36315675a53bc8c25d221b8d4f94169a`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #5: CHZUSDT — Net +$4.4610 USD (+209.9 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_CHZUSDT_8_4461004` |
| Position ID | `paper_pos_CHZUSDT` |
| Symbol | **CHZUSDT** |
| Side / Action | short / short |
| Timeframe | 1m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_PROFIT_BANK** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.023288895** |
| Exit Price | **$0.0228** |
| Price Move (% favorable to short) | **-2.099%** |
| Quantity | 9387.3365 units |
| Gross PnL | +$4.589423 |
| Fees | -$0.085613 |
| Slippage | -$0.042806 |
| Net PnL | **+$4.461004** |
| Net PnL (bps) | **+209.93 bps** |
| Winner | True |
| Hold Time | 1152s (0.320h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_87a4711489f16edd8c43c4747f4ab765` |
| Entry Prediction ID | `v2h_87a4711489f16edd8c43c4747f4ab765` |
| Entry Feature Snapshot ID | `v2_fsnap_15db7401385ad7abe89430f0d0e63fc42f5ed8b0936bb3898ed4247224c4c1c3` |
| Entry Market State ID | `mstate_63c7de8d583d4bbccb47` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:42:55Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_CHZUSDT_8_4461004` |
| Source Fill IDs | 8 fills: `v2h_87a4711489f16edd8c43c4747f4ab765`, `v2_paper_intent_CHZUSDT`, `v2h_63431b859b505d2c51e8b64262c7ad6c`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #6: ATOMUSDT — Net +$4.3932 USD (+168.7 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_ATOMUSDT_12_4393242` |
| Position ID | `paper_pos_ATOMUSDT` |
| Symbol | **ATOMUSDT** |
| Side / Action | short / short |
| Timeframe | 4h |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$1.8298633** |
| Exit Price | **$1.799** |
| Price Move (% favorable to short) | **-1.687%** |
| Quantity | 147.5037 units |
| Gross PnL | +$4.552458 |
| Fees | -$0.106144 |
| Slippage | -$0.053072 |
| Net PnL | **+$4.393242** |
| Net PnL (bps) | **+168.66 bps** |
| Winner | True |
| Hold Time | 4501s (1.250h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_15fcf82e76a82658411792508a1ef825` |
| Entry Prediction ID | `v2h_15fcf82e76a82658411792508a1ef825` |
| Entry Feature Snapshot ID | `v2_fsnap_6dadd91e84deea38163e1c6a077583fc7dbd26591fc72590ce3dd5a52dc1e42c` |
| Entry Market State ID | `mstate_03c6ab7e2f4ee9091ad4` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T15:41:22Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_ATOMUSDT_12_4393242` |
| Source Fill IDs | 12 fills: `v2h_15fcf82e76a82658411792508a1ef825`, `v2h_012b91556323439a8a75af28213ccd29`, `v2h_2acd4019f755b77e1bb2be2d1c5a08f9`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #7: ICPUSDT — Net +$4.3653 USD (+134.1 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_ICPUSDT_12_4365253` |
| Position ID | `paper_pos_ICPUSDT` |
| Symbol | **ICPUSDT** |
| Side / Action | short / short |
| Timeframe | 1m |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$2.2755174** |
| Exit Price | **$2.245** |
| Price Move (% favorable to short) | **-1.341%** |
| Quantity | 149.6466 units |
| Gross PnL | +$4.566827 |
| Fees | -$0.134383 |
| Slippage | -$0.067191 |
| Net PnL | **+$4.365253** |
| Net PnL (bps) | **+134.11 bps** |
| Winner | True |
| Hold Time | 4327s (1.202h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_699375a9e57ddf4add6511ab85cdf1f3` |
| Entry Prediction ID | `v2h_699375a9e57ddf4add6511ab85cdf1f3` |
| Entry Feature Snapshot ID | `v2_fsnap_ad6c2421e999a9f31ac59234702c80d9577be936bb7e44648bd968b4b7142cd3` |
| Entry Market State ID | `mstate_8810b6b57bf414511a1b` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T15:31:08Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_ICPUSDT_12_4365253` |
| Source Fill IDs | 12 fills: `v2h_699375a9e57ddf4add6511ab85cdf1f3`, `v2h_3e3591fbfd20de016d38c1c6ec580880`, `v2h_1a78d00717e87668ed3aa35d5bf37439`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #8: BSBUSDT — Net +$4.1537 USD (+195.9 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_BSBUSDT_8_4153657` |
| Position ID | `paper_pos_BSBUSDT` |
| Symbol | **BSBUSDT** |
| Side / Action | short / short |
| Timeframe | 4h |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_PROFIT_BANK** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.5761347** |
| Exit Price | **$0.56485** |
| Price Move (% favorable to short) | **-1.959%** |
| Quantity | 379.4753 units |
| Gross PnL | +$4.282266 |
| Fees | -$0.085739 |
| Slippage | -$0.042869 |
| Net PnL | **+$4.153658** |
| Net PnL (bps) | **+195.87 bps** |
| Winner | True |
| Hold Time | 1262s (0.351h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_1b72639b485e222a9caa86c8a90e7a13` |
| Entry Prediction ID | `v2h_1b72639b485e222a9caa86c8a90e7a13` |
| Entry Feature Snapshot ID | `v2_fsnap_04e71a6f4b9f6e6e848b4d911e0fe5162e6468e46fd1d54097b9c85ae83ff657` |
| Entry Market State ID | `mstate_a20feee7e3d0aa5a2ebc` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:44:45Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_BSBUSDT_8_4153657` |
| Source Fill IDs | 8 fills: `v2h_1b72639b485e222a9caa86c8a90e7a13`, `v2_paper_intent_BSBUSDT`, `v2h_27d777e849ef9b348008e5069440bd87`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #9: HBARUSDT — Net +$3.7156 USD (+125.2 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_HBARUSDT_12_3715594` |
| Position ID | `paper_pos_HBARUSDT` |
| Symbol | **HBARUSDT** |
| Side / Action | short / short |
| Timeframe | 5m |
| Strategy Mode | trend_mode |
| Entry Reason | trend_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$0.079768372** |
| Exit Price | **$0.07877** |
| Price Move (% favorable to short) | **-1.252%** |
| Quantity | 3906.5862 units |
| Gross PnL | +$3.900227 |
| Fees | -$0.123089 |
| Slippage | -$0.061544 |
| Net PnL | **+$3.715594** |
| Net PnL (bps) | **+125.16 bps** |
| Winner | True |
| Hold Time | 4313s (1.198h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_25484cc41fa5d13e1f227d346cf57267` |
| Entry Prediction ID | `v2h_25484cc41fa5d13e1f227d346cf57267` |
| Entry Feature Snapshot ID | `v2_fsnap_c04d8450e2fdf2c005e7a9398da0da1fbbb29c759371e591e9ffab05f77b55f1` |
| Entry Market State ID | `mstate_65ae96013a4557d65141` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T15:54:20Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_HBARUSDT_12_3715594` |
| Source Fill IDs | 12 fills: `v2h_25484cc41fa5d13e1f227d346cf57267`, `v2h_1c533c55fdee25d569288312fc88f72b`, `v2h_07aae63433928e8bf55e3eaab6d6251b`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

### Best #10: HYPEUSDT — Net +$3.6145 USD (+168.1 bps)

| Field | Value |
|---|---|
| Close ID | `paper_close_paper_pos_HYPEUSDT_6_3614518` |
| Position ID | `paper_pos_HYPEUSDT` |
| Symbol | **HYPEUSDT** |
| Side / Action | short / short |
| Timeframe | 15m |
| Strategy Mode | reduce_size_mode |
| Entry Reason | reduce_size_mode |
| Exit Reason | **TIER_2_TAKE_PROFIT** |
| Market Regime at Entry | TREND |
| Market Regime at Exit | TREND |
| Entry Price | **$71.924351** |
| Exit Price | **$70.715** |
| Price Move (% favorable to short) | **-1.681%** |
| Quantity | 3.0975 units |
| Gross PnL | +$3.745941 |
| Fees | -$0.087615 |
| Slippage | -$0.043808 |
| Net PnL | **+$3.614518** |
| Net PnL (bps) | **+168.14 bps** |
| Winner | True |
| Hold Time | 767s (0.213h) |
| Drawdown at Entry | 0.0000 |
| Hedge State | NO_HEDGE |
| Squeeze Evidence Score | None |
| Major Move Signal ID | None |
| Entry Signal ID | `v2h_5c5b2bd8bea3e97503c068a4b00d0734` |
| Entry Prediction ID | `v2h_5c5b2bd8bea3e97503c068a4b00d0734` |
| Entry Feature Snapshot ID | `v2_fsnap_e7fadc5aa6fe857fdeccd754f05f631fc62ed8f10a2b98749714932a99ca7d4f` |
| Entry Market State ID | `mstate_e9fbeb971c517be3ed86` |
| Exit Price Source | V2_MARKET_PRICE_MARK_TO_MARKET |
| Exit Time (UTC) | 2026-06-18T13:36:30Z |
| Trainer Feedback ID | `trainer_feedback_paper_close_paper_pos_HYPEUSDT_6_3614518` |
| Source Fill IDs | 6 fills: `v2h_5c5b2bd8bea3e97503c068a4b00d0734`, `v2_paper_intent_HYPEUSDT`, `v2h_2dd87954f1568fa065b5f3034bf26d76`... |
| Liquidity Score | 1.0 |
| Bid-Ask Spread | 2.0 bps |

---

## 12. Full Per-Trade Ledger (All 595 Trades)

Sorted by exit time (UTC). Feat Snap = first 16 chars of entry_feature_snapshot_id.

| # | Exit UTC | Symbol | Side | TF | Strategy | Reg↑ | Reg↓ | Entry$ | Exit$ | Move% | Qty | Gross$ | Fees | Slip | Net$ | bps | W/L | Exit Reason | Hold(s) | Prediction ID | Feat Snap (prefix) | MktState ID | Hedge | Fills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-18T13:25:50 | BEATUSDT | short | 1m | reduce_size_mod | TREND | TREND | 1.635 | 1.615 | -1.22% | 72.15 | 1.4431 | 0.0466 | 0.0233 | 1.3732 | 122.3 | WIN | TIER_2_TAKE_PROFIT | 127 | v2h_2063feef75182588ee58b31429472f7a | v2_fsnap_a9b24ee | mstate_69e01d2e094c6 | NO_HEDGE | 3 |
| 2 | 2026-06-18T13:25:50 | ESPORTSUSDT | short | 15m | reduce_size_mod | TREND | TREND | 0.08893 | 0.08601 | -3.28% | 1258.42 | 3.6746 | 0.0433 | 0.0216 | 3.6097 | 328.3 | WIN | TIER_2_PROFIT_BANK | 127 | v2h_0375219533ce4b1a92e726ff13c88e5a | v2_fsnap_9bc67fb | mstate_ab4a05cd9a33d | NO_HEDGE | 3 |
| 3 | 2026-06-18T13:25:50 | HUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.25039 | 0.25454 | +1.66% | 546.05 | -2.2661 | 0.0556 | 0.0278 | -2.3495 | -165.7 | LOSS | TIER_1_STOP_LOSS | 127 | v2h_17a603afa05be33970486b0deb852945 | v2_fsnap_a7170c6 | mstate_c43f24317747f | NO_HEDGE | 3 |
| 4 | 2026-06-18T13:27:58 | ALLOUSDT | short | 1h | reduce_size_mod | TREND | TREND | 0.388422 | 0.39327 | +1.25% | 347.95 | -1.6869 | 0.0547 | 0.0274 | -1.7690 | -124.8 | LOSS | TIER_1_STOP_LOSS | 255 | v2h_50d2c2947ab4200a523e552bba371f5f | v2_fsnap_c304716 | mstate_80bf82e133be6 | NO_HEDGE | 4 |
| 5 | 2026-06-18T13:27:58 | BIOUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.0355161 | 0.03574 | +0.63% | 4648.33 | -1.0406 | 0.0665 | 0.0332 | -1.1403 | -63.0 | LOSS | TIER_2_TRAILING_STOP | 255 | v2h_3b846e482763630f0528e686337bce67 | v2_fsnap_76bae32 | mstate_881191135dab6 | NO_HEDGE | 4 |
| 6 | 2026-06-18T13:27:58 | MITOUSDT | short | 1m | trend_mode | TREND | TREND | 0.02638 | 0.02675 | +1.40% | 2921.66 | -1.0810 | 0.0313 | 0.0156 | -1.1279 | -140.3 | LOSS | TIER_1_STOP_LOSS | 65 | v2h_29008e14cf3ca1ead2d60c5b33ae3c7d | v2_fsnap_346678d | mstate_fec2ee12c2b15 | NO_HEDGE | 3 |
| 7 | 2026-06-18T13:30:09 | CRVUSDT | short | 5m | reduce_size_mod | TREND | TREND | 0.224483 | 0.2282 | +1.66% | 735.54 | -2.7341 | 0.0671 | 0.0336 | -2.8348 | -165.6 | LOSS | TIER_1_STOP_LOSS | 386 | v2h_a32a1b6a6eecab41a68868074ee26825 | v2_fsnap_6f275f6 | mstate_fef51d995b35f | NO_HEDGE | 4 |
| 8 | 2026-06-18T13:30:09 | ENAUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.0918341 | 0.09244 | +0.66% | 1797.69 | -1.0892 | 0.0665 | 0.0332 | -1.1889 | -66.0 | LOSS | TIER_2_TRAILING_STOP | 386 | v2h_e0e40ef67348a5cfe162512442a8354d | v2_fsnap_6119f1c | mstate_c97c71ecb07cd | NO_HEDGE | 4 |
| 9 | 2026-06-18T13:33:58 | ALGOUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.102794 | 0.1013 | -1.45% | 1707.84 | 2.5513 | 0.0692 | 0.0346 | 2.4475 | 145.3 | WIN | TIER_2_TAKE_PROFIT | 615 | v2h_bcb1ab8e2f12091e89f316657ab9d128 | v2_fsnap_eccc2f1 | mstate_563d86e27de81 | NO_HEDGE | 6 |
| 10 | 2026-06-18T13:34:24 | LDOUSDT | short | 5m | reduce_size_mod | TREND | TREND | 0.283431 | 0.2794 | -1.42% | 717.89 | 2.8938 | 0.0802 | 0.0401 | 2.7734 | 142.2 | WIN | TIER_2_TAKE_PROFIT | 641 | v2h_0b6ba7283db6f0747c7a68ab53341047 | v2_fsnap_85ca0dc | mstate_f720538119b13 | NO_HEDGE | 6 |
| 11 | 2026-06-18T13:34:24 | HUSDT | short | 1h | trend_mode | TREND | TREND | 0.25327 | 0.25425 | +0.39% | 233.57 | -0.2289 | 0.0238 | 0.0119 | -0.2645 | -38.7 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_0ceb5a81129cccbaeaedbe275d46514a | v2_fsnap_f74e2cd | mstate_2196dcdb5b737 | NO_HEDGE | 3 |
| 12 | 2026-06-18T13:36:30 | AEROUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.477328 | 0.4646 | -2.67% | 426.28 | 5.4256 | 0.0792 | 0.0396 | 5.3068 | 266.6 | WIN | TIER_2_PROFIT_BANK | 767 | v2h_15846d9ded67dd2d612385b486f6f0e7 | v2_fsnap_806f527 | mstate_5a741c8619093 | NO_HEDGE | 6 |
| 13 | 2026-06-18T13:36:30 | HYPEUSDT | short | 15m | reduce_size_mod | TREND | TREND | 71.9244 | 70.715 | -1.68% | 3.10 | 3.7459 | 0.0876 | 0.0438 | 3.6145 | 168.1 | WIN | TIER_2_TAKE_PROFIT | 767 | v2h_5c5b2bd8bea3e97503c068a4b00d0734 | v2_fsnap_e7fadc5 | mstate_e9fbeb971c517 | NO_HEDGE | 6 |
| 14 | 2026-06-18T13:36:30 | NEARUSDT | short | 1m | trend_mode | TREND | TREND | 2.29073 | 2.259 | -1.39% | 61.31 | 1.9454 | 0.0554 | 0.0277 | 1.8623 | 138.5 | WIN | TIER_2_TAKE_PROFIT | 577 | v2h_080d5c796ab8285d5e775cfaf533c1f3 | v2_fsnap_53b9e66 | mstate_37b4f7f8fc87c | NO_HEDGE | 5 |
| 15 | 2026-06-18T13:36:30 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0846596 | 0.08296 | -2.01% | 571.95 | 0.9721 | 0.0190 | 0.0095 | 0.9436 | 200.8 | WIN | TIER_2_PROFIT_BANK | 447 | v2h_111f671b73292e76e4aef2a71cedad49 | v2_fsnap_66ab2d7 | mstate_14923a3a3ad3e | NO_HEDGE | 3 |
| 16 | 2026-06-18T13:36:30 | BIOUSDT | short | 1m | trend_mode | TREND | TREND | 0.0356999 | 0.03565 | -0.14% | 1074.46 | 0.0536 | 0.0153 | 0.0077 | 0.0306 | 14.0 | WIN | TIER_2_TRAILING_STOP | 317 | v2h_310c90b2fd44c085ec9d2221b870d565 | v2_fsnap_505cac5 | mstate_3b4b284102d63 | NO_HEDGE | 2 |
| 17 | 2026-06-18T13:38:39 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.08296 | 0.08183 | -1.36% | 228.16 | 0.2578 | 0.0075 | 0.0037 | 0.2466 | 136.2 | WIN | TIER_2_TAKE_PROFIT | 66 | v2h_53d0eb370fa3064067a30102bf6c2361 | v2_fsnap_45a4f50 | mstate_84deb12ae7dda | NO_HEDGE | 1 |
| 18 | 2026-06-18T13:40:50 | AAVEUSDT | short | 5m | reduce_size_mod | TREND | TREND | 74.0364 | 73.14 | -1.21% | 3.35 | 3.0038 | 0.0980 | 0.0490 | 2.8567 | 121.1 | WIN | TIER_2_TAKE_PROFIT | 1027 | v2h_1a3226e25acec51b540e989de53dd647 | v2_fsnap_50525d9 | mstate_57e1b0031a667 | NO_HEDGE | 7 |
| 19 | 2026-06-18T13:40:50 | APTUSDT | short | 5m | reduce_size_mod | TREND | TREND | 0.651503 | 0.6435 | -1.23% | 347.81 | 2.7836 | 0.0895 | 0.0448 | 2.6493 | 122.8 | WIN | TIER_2_TAKE_PROFIT | 1027 | v2h_5f4c85214d9ecc2638c1f21db5f9ede9 | v2_fsnap_a7ac80e | mstate_213605f81a237 | NO_HEDGE | 7 |
| 20 | 2026-06-18T13:40:50 | HOMEUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.0286637 | 0.0288 | +0.48% | 7538.25 | -1.0271 | 0.0868 | 0.0434 | -1.1573 | -47.5 | LOSS | TIER_2_TRAILING_STOP | 1027 | v2h_dfe672c4d9717610dd14d64f1920d4f4 | v2_fsnap_6e220fb | mstate_131bae76d61c7 | NO_HEDGE | 7 |
| 21 | 2026-06-18T13:40:50 | LITUSDT | short | 1h | reduce_size_mod | TREND | TREND | 1.64018 | 1.6146 | -1.56% | 138.15 | 3.5344 | 0.0892 | 0.0446 | 3.4006 | 156.0 | WIN | TIER_2_TAKE_PROFIT | 1027 | v2h_0ddcd20df335f59da16f33e09a9067f6 | v2_fsnap_f21e309 | mstate_663bfafb861c0 | NO_HEDGE | 7 |
| 22 | 2026-06-18T13:40:50 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.25238 | 0.25123 | -0.46% | 91.63 | 0.1054 | 0.0092 | 0.0046 | 0.0916 | 45.6 | WIN | TIER_2_TRAILING_STOP | 197 | v2h_48dbc09a4163ef75f8ab8225eecb4d4a | v2_fsnap_661f553 | mstate_a1d768685a5ef | NO_HEDGE | 1 |
| 23 | 2026-06-18T13:42:55 | ARBUSDT | short | 5m | reduce_size_mod | TREND | TREND | 0.0852169 | 0.08409 | -1.32% | 2972.67 | 3.3499 | 0.1000 | 0.0500 | 3.1999 | 132.2 | WIN | TIER_2_TAKE_PROFIT | 1152 | v2h_873a9a5f0ecca47ba42c1a7b2e4d2127 | v2_fsnap_2be19d9 | mstate_8dfa13e01a860 | NO_HEDGE | 8 |
| 24 | 2026-06-18T13:42:55 | CHZUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.0232889 | 0.0228 | -2.10% | 9387.34 | 4.5894 | 0.0856 | 0.0428 | 4.4610 | 209.9 | WIN | TIER_2_PROFIT_BANK | 1152 | v2h_87a4711489f16edd8c43c4747f4ab765 | v2_fsnap_15db740 | mstate_63c7de8d583d4 | NO_HEDGE | 8 |
| 25 | 2026-06-18T13:42:55 | FILUSDT | short | 4h | reduce_size_mod | TREND | TREND | 0.792748 | 0.783 | -1.23% | 349.96 | 3.4113 | 0.1096 | 0.0548 | 3.2469 | 123.0 | WIN | TIER_2_TAKE_PROFIT | 1152 | v2h_080066d74f983a83316ae0e072d10e96 | v2_fsnap_0b3d71d | mstate_d6ae5c9668d25 | NO_HEDGE | 8 |
| 26 | 2026-06-18T13:42:55 | JTOUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.714457 | 0.7043 | -1.42% | 354.61 | 3.6016 | 0.0999 | 0.0499 | 3.4517 | 142.2 | WIN | TIER_2_TAKE_PROFIT | 1152 | v2h_5aa51b156ff735e1c06e05774360eb2c | v2_fsnap_e536d0d | mstate_dafac4682eb64 | NO_HEDGE | 8 |
| 27 | 2026-06-18T13:42:55 | MITOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0267043 | 0.02601 | -2.60% | 2057.33 | 1.4284 | 0.0214 | 0.0107 | 1.3963 | 260.0 | WIN | TIER_2_PROFIT_BANK | 449 | v2h_142466f50be0364b90eda77eb652fe4e | v2_fsnap_4c58275 | mstate_5f08ba06f3b91 | NO_HEDGE | 3 |
| 28 | 2026-06-18T13:42:55 | HOMEUSDT | short | 1m | trend_mode | TREND | TREND | 0.0288 | 0.02914 | +1.18% | 886.81 | -0.3015 | 0.0103 | 0.0052 | -0.3170 | -118.1 | LOSS | TIER_1_STOP_LOSS | 63 | v2h_185753995c97c483769a88fe5e72317b | v2_fsnap_eba1c2d | mstate_d186999a3ee12 | NO_HEDGE | 1 |
| 29 | 2026-06-18T13:44:45 | BSBUSDT | short | 4h | reduce_size_mod | TREND | TREND | 0.576135 | 0.56485 | -1.96% | 379.48 | 4.2823 | 0.0857 | 0.0429 | 4.1537 | 195.9 | WIN | TIER_2_PROFIT_BANK | 1262 | v2h_1b72639b485e222a9caa86c8a90e7a13 | v2_fsnap_04e71a6 | mstate_a20feee7e3d0a | NO_HEDGE | 8 |
| 30 | 2026-06-18T13:44:45 | INJUSDT | short | 15m | reduce_size_mod | TREND | TREND | 5.26292 | 5.195 | -1.29% | 48.13 | 3.2688 | 0.1000 | 0.0500 | 3.1188 | 129.1 | WIN | TIER_2_TAKE_PROFIT | 1262 | v2h_6947b50e9a021064fd47563a789ab857 | v2_fsnap_1d20932 | mstate_6d13a7addaeab | NO_HEDGE | 8 |
| 31 | 2026-06-18T13:44:45 | AEROUSDT | short | 1h | trend_mode | TREND | TREND | 0.461741 | 0.4552 | -1.42% | 108.09 | 0.7069 | 0.0197 | 0.0098 | 0.6774 | 141.7 | WIN | TIER_2_TAKE_PROFIT | 432 | v2h_174292ae927c91c0666d0efc466f1a46 | v2_fsnap_77bcd55 | mstate_1fe3aa5a1d52f | NO_HEDGE | 2 |
| 32 | 2026-06-18T13:47:07 | LABUSDT | short | 1m | reduce_size_mod | TREND | TREND | 15.5908 | 15.707 | +0.75% | 17.60 | -2.0458 | 0.1106 | 0.0553 | -2.2117 | -74.5 | LOSS | TIER_2_TRAILING_STOP | 1404 | v2h_0d33eba19fc47af2cdf5bbb811d9c13e | v2_fsnap_f2a5ea2 | mstate_ea0cb70262837 | NO_HEDGE | 9 |
| 33 | 2026-06-18T13:47:07 | MEGAUSDT | short | 5m | trend_mode | TREND | TREND | 0.0658679 | 0.06611 | +0.37% | 3218.74 | -0.7792 | 0.0851 | 0.0426 | -0.9069 | -36.8 | LOSS | TIER_2_TRAILING_STOP | 1214 | v2h_644ec27ca42bac5a9ad7b677f9c00df1 | v2_fsnap_0e3e19d | mstate_ac7b1c7405790 | NO_HEDGE | 8 |
| 34 | 2026-06-18T13:47:07 | BEATUSDT | short | 15m | trend_mode | TREND | TREND | 1.61143 | 1.631 | +1.21% | 76.83 | -1.5035 | 0.0501 | 0.0251 | -1.5787 | -121.4 | LOSS | TIER_1_STOP_LOSS | 1084 | v2h_1e9165002d1c2cd2f0ccef94bc46a187 | v2_fsnap_bdca2fd | mstate_45ed5f93609b3 | NO_HEDGE | 6 |
| 35 | 2026-06-18T13:49:13 | NEARUSDT | short | 1m | trend_mode | TREND | TREND | 2.24669 | 2.254 | +0.33% | 46.45 | -0.3396 | 0.0419 | 0.0209 | -0.4024 | -32.5 | LOSS | TIER_2_TRAILING_STOP | 315 | v2h_077b9f7e2e0a175d1f04a914f1425d88 | v2_fsnap_7e98666 | mstate_97a1d30b25755 | NO_HEDGE | 3 |
| 36 | 2026-06-18T13:49:13 | ONDOUSDT | short | 5m | trend_mode | TREND | TREND | 0.368115 | 0.3696 | +0.40% | 359.28 | -0.5335 | 0.0531 | 0.0266 | -0.6131 | -40.3 | LOSS | TIER_2_TRAILING_STOP | 315 | v2h_313a0cd8dc99e55982cfb8b10ce0d086 | v2_fsnap_8441638 | mstate_1af6a1a76a103 | NO_HEDGE | 4 |
| 37 | 2026-06-18T13:49:13 | BSBUSDT | short | 1m | trend_mode | TREND | TREND | 0.565824 | 0.56711 | +0.23% | 92.41 | -0.1188 | 0.0210 | 0.0105 | -0.1503 | -22.7 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_23c8921f3533b269382c750abc887207 | v2_fsnap_c4f8400 | mstate_51acdda05f2ce | NO_HEDGE | 2 |
| 38 | 2026-06-18T13:50:44 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.0823308 | 0.0808 | -1.86% | 868.75 | 1.3299 | 0.0281 | 0.0140 | 1.2877 | 185.9 | WIN | TIER_2_PROFIT_BANK | 532 | v2h_15afa75bbadcd768d9c4f3b071e39754 | v2_fsnap_c7e2a74 | mstate_7d7c4d39fab70 | NO_HEDGE | 3 |
| 39 | 2026-06-18T13:51:20 | DOTUSDT | short | 4h | reduce_size_mod | TREND | TREND | 0.977529 | 0.975 | -0.26% | 351.68 | 0.8896 | 0.1372 | 0.0686 | 0.6838 | 25.9 | WIN | TIER_2_TRAILING_STOP | 1657 | v2h_223b44c5de056d7f9c39042995e75b08 | v2_fsnap_adc833d | mstate_b99d1dd0e2c4c | NO_HEDGE | 10 |
| 40 | 2026-06-18T13:51:20 | FETUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.198347 | 0.198 | -0.17% | 1365.83 | 0.4736 | 0.1082 | 0.0541 | 0.3113 | 17.5 | WIN | TIER_2_TRAILING_STOP | 1657 | v2h_4ebd3b70f7b26e2256eefdbbfe7c444c | v2_fsnap_fe43ece | mstate_b049b8c1416bb | NO_HEDGE | 10 |
| 41 | 2026-06-18T13:51:20 | ICPUSDT | short | 5m | reduce_size_mod | TREND | TREND | 2.26658 | 2.276 | +0.42% | 151.67 | -1.4285 | 0.1381 | 0.0690 | -1.6356 | -41.6 | LOSS | TIER_2_TRAILING_STOP | 1657 | v2h_4fe880dfe95b4082bf0e822f782b75ee | v2_fsnap_d80f9cb | mstate_00d6aae021dbe | NO_HEDGE | 10 |
| 42 | 2026-06-18T13:51:20 | CRVUSDT | short | 1h | trend_mode | TREND | TREND | 0.224981 | 0.2256 | +0.28% | 535.61 | -0.3314 | 0.0483 | 0.0242 | -0.4039 | -27.5 | LOSS | TIER_2_TRAILING_STOP | 1017 | v2h_51113489c1df24a3821788a8bc0f40d1 | v2_fsnap_a986162 | mstate_aefd91b224591 | NO_HEDGE | 5 |
| 43 | 2026-06-18T13:51:20 | ENAUSDT | short | 5m | trend_mode | TREND | TREND | 0.0914584 | 0.09203 | +0.62% | 1358.79 | -0.7766 | 0.0500 | 0.0250 | -0.8516 | -62.5 | LOSS | TIER_2_TRAILING_STOP | 954 | v2h_00abd314c55a242b1dc77bd7a4043514 | v2_fsnap_a52f6f7 | mstate_ff35f9c879103 | NO_HEDGE | 5 |
| 44 | 2026-06-18T13:51:20 | BIOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0355136 | 0.03562 | +0.30% | 3111.72 | -0.3312 | 0.0443 | 0.0222 | -0.3977 | -30.0 | LOSS | TIER_2_TRAILING_STOP | 827 | v2h_1b862d3bdfd41e1c77615088bdb04ab8 | v2_fsnap_3a13eca | mstate_69b06acbc192d | NO_HEDGE | 4 |
| 45 | 2026-06-18T13:51:20 | HYPEUSDT | short | 4h | trend_mode | TREND | TREND | 70.5099 | 71.212 | +1.00% | 1.56 | -1.0944 | 0.0444 | 0.0222 | -1.1610 | -99.6 | LOSS | TIER_1_STOP_LOSS | 695 | v2h_0c004c97f0080da5df8681b1bd58bef6 | v2_fsnap_a7a4e1a | mstate_2ee86eb128275 | NO_HEDGE | 4 |
| 46 | 2026-06-18T13:51:20 | APTUSDT | short | 4h | trend_mode | TREND | TREND | 0.64085 | 0.6445 | +0.57% | 136.36 | -0.4976 | 0.0352 | 0.0176 | -0.5504 | -56.9 | LOSS | TIER_2_TRAILING_STOP | 568 | v2h_2e7cd8d7d077f1dd9c27255ba99d68ed | v2_fsnap_c7d730e | mstate_5227c34ce7c2f | NO_HEDGE | 3 |
| 47 | 2026-06-18T13:51:20 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.250505 | 0.25087 | +0.15% | 348.83 | -0.1274 | 0.0350 | 0.0175 | -0.1799 | -14.6 | LOSS | TIER_2_TRAILING_STOP | 568 | v2h_1a32e518d50d49ab3aaaf6674d6fe5e4 | v2_fsnap_ecbddc6 | mstate_f7aeba56f2117 | NO_HEDGE | 3 |
| 48 | 2026-06-18T13:51:20 | LDOUSDT | short | 4h | trend_mode | TREND | TREND | 0.276839 | 0.2784 | +0.56% | 329.69 | -0.5146 | 0.0367 | 0.0184 | -0.5697 | -56.4 | LOSS | TIER_2_TRAILING_STOP | 442 | v2h_07d1e3d5bb649ad8af398dd0c9f0b74a | v2_fsnap_c19a6d1 | mstate_556712b19f4ee | NO_HEDGE | 3 |
| 49 | 2026-06-18T13:51:20 | LITUSDT | short | 5m | trend_mode | TREND | TREND | 1.60208 | 1.6015 | -0.04% | 56.97 | 0.0329 | 0.0365 | 0.0182 | -0.0218 | 3.6 | LOSS | TIER_2_TRAILING_STOP | 442 | v2h_116c88e52930e7db07ab61a05efd8fc1 | v2_fsnap_8e4ec39 | mstate_28afe9ab43c9a | NO_HEDGE | 3 |
| 50 | 2026-06-18T13:51:20 | OPUSDT | short | 5m | trend_mode | TREND | TREND | 0.107415 | 0.1082 | +0.73% | 1072.35 | -0.8421 | 0.0464 | 0.0232 | -0.9117 | -73.1 | LOSS | TIER_2_TRAILING_STOP | 442 | v2h_794e9e7d7fcf27289fd57954d3e61ee1 | v2_fsnap_a9caa3f | mstate_a02b1f1620d06 | NO_HEDGE | 4 |
| 51 | 2026-06-18T13:51:20 | ARBUSDT | short | 1h | trend_mode | TREND | TREND | 0.0840314 | 0.08453 | +0.59% | 721.17 | -0.3596 | 0.0244 | 0.0122 | -0.3962 | -59.3 | LOSS | TIER_2_TRAILING_STOP | 379 | v2h_6099bcdeeb0af6628e645e57f31c0dd6 | v2_fsnap_d22b141 | mstate_ce9e781533223 | NO_HEDGE | 2 |
| 52 | 2026-06-18T13:51:20 | FILUSDT | short | 4h | trend_mode | TREND | TREND | 0.783511 | 0.788 | +0.57% | 74.83 | -0.3359 | 0.0236 | 0.0118 | -0.3713 | -57.3 | LOSS | TIER_2_TRAILING_STOP | 191 | v2h_1f7fa999b05fabff4cea44a385c3cb1c | v2_fsnap_b56dd48 | mstate_4473dfb68c607 | NO_HEDGE | 2 |
| 53 | 2026-06-18T13:53:30 | AAVEUSDT | short | 4h | trend_mode | TREND | TREND | 73.1178 | 73.4 | +0.39% | 1.75 | -0.4950 | 0.0515 | 0.0258 | -0.5723 | -38.6 | LOSS | TIER_2_TRAILING_STOP | 698 | v2h_5506125cfe4ac8cdc3c1f36ead7f74ed | v2_fsnap_824094c | mstate_46266e8e59068 | NO_HEDGE | 4 |
| 54 | 2026-06-18T13:53:30 | CHZUSDT | short | 15m | trend_mode | TREND | TREND | 0.0226065 | 0.0227 | +0.41% | 3179.96 | -0.2973 | 0.0289 | 0.0144 | -0.3406 | -41.3 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_440eb6c78fab1df41dfc3e2b1f23bfbf | v2_fsnap_bd26938 | mstate_23ce3811a62af | NO_HEDGE | 3 |
| 55 | 2026-06-18T13:53:30 | JTOUSDT | short | 5m | trend_mode | TREND | TREND | 0.709837 | 0.7124 | +0.36% | 67.67 | -0.1735 | 0.0193 | 0.0096 | -0.2024 | -36.1 | LOSS | TIER_2_TRAILING_STOP | 194 | v2h_446514f116a26464354ae5320ef1ac84 | v2_fsnap_cebf348 | mstate_cd0f3a2be25a7 | NO_HEDGE | 2 |
| 56 | 2026-06-18T13:54:41 | AVAXUSDT | short | 5m | reduce_size_mod | TREND | TREND | 6.63388 | 6.628 | -0.09% | 56.74 | 0.3337 | 0.1504 | 0.0752 | 0.1081 | 8.9 | WIN | TIER_2_PROFIT_LOCK | 1858 | v2h_941e00ba25274562f0c415b825a2cc0c | v2_fsnap_5fb6195 | mstate_77587cf1876e3 | NO_HEDGE | 11 |
| 57 | 2026-06-18T13:54:41 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.62614 | 1.602 | -1.48% | 25.49 | 0.6153 | 0.0163 | 0.0082 | 0.5908 | 148.4 | WIN | TIER_2_TAKE_PROFIT | 265 | v2h_6ac33b82be5d27fe459d0e7cc6e8ed79 | v2_fsnap_36a87c8 | mstate_8885c9bd8e9f3 | NO_HEDGE | 2 |
| 58 | 2026-06-18T13:55:38 | ADAUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.165266 | 0.1652 | -0.04% | 2277.38 | 0.1513 | 0.1505 | 0.0752 | -0.0744 | 4.0 | LOSS | TIER_2_TRAILING_STOP | 1915 | v2h_1c453afe8c19ffa9346f92f1598392a9 | v2_fsnap_73428c6 | mstate_491c0c4915291 | NO_HEDGE | 11 |
| 59 | 2026-06-18T13:55:38 | DASHUSDT | short | 1m | reduce_size_mod | TREND | TREND | 35.9228 | 35.94 | +0.05% | 9.12 | -0.1568 | 0.1312 | 0.0656 | -0.3535 | -4.8 | LOSS | TIER_2_TRAILING_STOP | 1915 | v2h_0a85badc49fef25b69ca061bf26769e4 | v2_fsnap_e0e1f06 | mstate_7f95ee4717b1b | NO_HEDGE | 11 |
| 60 | 2026-06-18T13:55:38 | ALGOUSDT | short | 1m | trend_mode | TREND | TREND | 0.100641 | 0.1009 | +0.26% | 1202.66 | -0.3110 | 0.0485 | 0.0243 | -0.3838 | -25.7 | LOSS | TIER_2_TRAILING_STOP | 1085 | v2h_1ba48860025bf6d99c2d05c4ba34b829 | v2_fsnap_b27a7e7 | mstate_6bfae56f4f7a1 | NO_HEDGE | 5 |
| 61 | 2026-06-18T13:55:38 | LABUSDT | short | 1m | trend_mode | TREND | TREND | 15.7108 | 15.809 | +0.63% | 2.91 | -0.2860 | 0.0184 | 0.0092 | -0.3136 | -62.5 | LOSS | TIER_2_TRAILING_STOP | 259 | v2h_3848ce4c655db8c7a18590dd28252c07 | v2_fsnap_da3f084 | mstate_a4e343e8d8858 | NO_HEDGE | 2 |
| 62 | 2026-06-18T13:55:38 | MITOUSDT | short | 15m | trend_mode | TREND | TREND | 0.026236 | 0.02639 | +0.59% | 2547.61 | -0.3924 | 0.0269 | 0.0134 | -0.4327 | -58.7 | LOSS | TIER_2_TRAILING_STOP | 196 | v2h_1632ae05b197259b8a468b785e6149d6 | v2_fsnap_a24f5cd | mstate_1eb72632e40c5 | NO_HEDGE | 2 |
| 63 | 2026-06-18T13:55:38 | TAOUSDT | short | 5m | trend_mode | TREND | TREND | 239.514 | 240.85 | +0.56% | 0.52 | -0.6879 | 0.0496 | 0.0248 | -0.7623 | -55.8 | LOSS | TIER_2_TRAILING_STOP | 196 | v2h_0cdcfead8fe762bc31f8241d37945e42 | v2_fsnap_06b2599 | mstate_84a5513fab0ce | NO_HEDGE | 3 |
| 64 | 2026-06-18T13:57:08 | MEGAUSDT | short | 4h | trend_mode | TREND | TREND | 0.0660067 | 0.06515 | -1.30% | 1173.57 | 1.0054 | 0.0306 | 0.0153 | 0.9595 | 129.8 | WIN | TIER_2_TAKE_PROFIT | 286 | v2h_84e5b0dc350985f6527d915344c19f50 | v2_fsnap_640731f | mstate_c7cacb6759d4b | NO_HEDGE | 2 |
| 65 | 2026-06-18T13:57:08 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.07682 | 0.081 | +5.44% | 426.18 | -1.7814 | 0.0138 | 0.0069 | -1.8021 | -544.1 | LOSS | TIER_1_STOP_LOSS | 27 | v2h_10fabff17f97f02127f534bff22e9965 | v2_fsnap_7fdfaaf | mstate_f47203f3b0c05 | NO_HEDGE | 1 |
| 66 | 2026-06-18T13:57:44 | ALLOUSDT | short | 1m | trend_mode | TREND | TREND | 0.390287 | 0.39083 | +0.14% | 454.97 | -0.2471 | 0.0711 | 0.0356 | -0.3538 | -13.9 | LOSS | TIER_2_TRAILING_STOP | 1591 | v2h_2183c7d1dc46ba0d06d6ed6e7377825f | v2_fsnap_0c32fb0 | mstate_dcd32738607dd | NO_HEDGE | 8 |
| 67 | 2026-06-18T14:01:27 | BSBUSDT | short | 5m | trend_mode | TREND | TREND | 0.570549 | 0.5634 | -1.25% | 95.78 | 0.6848 | 0.0216 | 0.0108 | 0.6524 | 125.3 | WIN | TIER_2_TAKE_PROFIT | 349 | v2h_1d47de8014d5db1476246b91482c94c5 | v2_fsnap_b9844c9 | mstate_eeb2282cd7687 | NO_HEDGE | 2 |
| 68 | 2026-06-18T14:05:10 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.100199 | 0.1007 | +0.50% | 399.63 | -0.2004 | 0.0161 | 0.0080 | -0.2245 | -50.0 | LOSS | TIER_2_TRAILING_STOP | 383 | v2h_001779669267c4e6832dc2992248c3ac | v2_fsnap_e92eb4e | mstate_7966512aa91ca | NO_HEDGE | 2 |
| 69 | 2026-06-18T14:06:14 | HOMEUSDT | short | 1h | trend_mode | TREND | TREND | 0.0288055 | 0.02837 | -1.51% | 4798.23 | 2.0894 | 0.0545 | 0.0272 | 2.0077 | 151.2 | WIN | TIER_2_TAKE_PROFIT | 1085 | v2h_0b7b7d13e6d647dc767cef63566bca41 | v2_fsnap_4da26f4 | mstate_b6bbca885f00e | NO_HEDGE | 5 |
| 70 | 2026-06-18T14:06:14 | BIOUSDT | short | 15m | trend_mode | TREND | TREND | 0.0355041 | 0.03565 | +0.41% | 2292.61 | -0.3344 | 0.0327 | 0.0163 | -0.3835 | -41.1 | LOSS | TIER_2_TRAILING_STOP | 699 | v2h_18b71d80d798a1ef85fb80b96dacc353 | v2_fsnap_76b7182 | mstate_3cdb0bf380615 | NO_HEDGE | 3 |
| 71 | 2026-06-18T14:06:14 | ENAUSDT | short | 5m | trend_mode | TREND | TREND | 0.0919972 | 0.09214 | +0.16% | 1104.66 | -0.1578 | 0.0407 | 0.0204 | -0.2188 | -15.5 | LOSS | TIER_2_TRAILING_STOP | 573 | v2h_21c3fd036103e822b27137bc3f060045 | v2_fsnap_83a4bb4 | mstate_f9ebe177cb70e | NO_HEDGE | 3 |
| 72 | 2026-06-18T14:06:14 | HUSDT | short | 15m | trend_mode | TREND | TREND | 0.253327 | 0.2553 | +0.78% | 401.16 | -0.7914 | 0.0410 | 0.0205 | -0.8529 | -77.9 | LOSS | TIER_2_TRAILING_STOP | 573 | v2h_148a0fed982f749272a7df27989695ff | v2_fsnap_b53a8f1 | mstate_db91659e4801d | NO_HEDGE | 3 |
| 73 | 2026-06-18T14:07:21 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.54621 | 0.55363 | +1.36% | 29.86 | -0.2216 | 0.0066 | 0.0033 | -0.2315 | -135.8 | LOSS | TIER_1_STOP_LOSS | 5 | v2h_0dbedfcd755dcf05bbcdf1411852de0a | v2_fsnap_1ff86bb | mstate_96724c7c786cb | NO_HEDGE | 1 |
| 74 | 2026-06-18T14:08:19 | PENDLEUSDT | short | 15m | trend_mode | TREND | TREND | 1.44092 | 1.4412 | +0.02% | 140.99 | -0.0399 | 0.0813 | 0.0406 | -0.1618 | -2.0 | LOSS | TIER_2_TRAILING_STOP | 957 | v2h_12c83de90258a812b54e297202b21795 | v2_fsnap_298ad45 | mstate_d7cfdda287bc9 | NO_HEDGE | 6 |
| 75 | 2026-06-18T14:08:19 | TIAUSDT | short | 1m | trend_mode | TREND | TREND | 0.384762 | 0.3868 | +0.53% | 527.98 | -1.0762 | 0.0817 | 0.0408 | -1.1987 | -53.0 | LOSS | TIER_2_TRAILING_STOP | 957 | v2h_1c0b87585fed88640676586932e2e090 | v2_fsnap_d083bfe | mstate_0532e1025faa1 | NO_HEDGE | 6 |
| 76 | 2026-06-18T14:09:23 | BSBUSDT | short | 5m | trend_mode | TREND | TREND | 0.55363 | 0.55856 | +0.89% | 24.53 | -0.1209 | 0.0055 | 0.0027 | -0.1292 | -89.0 | LOSS | TIER_1_STOP_LOSS | 1 | v2h_7aa24ae19e61ce0892d5c250e4d77805 | v2_fsnap_197f4a6 | mstate_404ced928ef3e | NO_HEDGE | 1 |
| 77 | 2026-06-18T14:10:26 | TRUMPUSDT | short | 5m | trend_mode | TREND | TREND | 1.85606 | 1.86 | +0.21% | 119.84 | -0.4722 | 0.0892 | 0.0446 | -0.6059 | -21.2 | LOSS | TIER_2_TRAILING_STOP | 1084 | v2h_1cb2870f5925bf3bf0f836dd1675891e | v2_fsnap_3a37423 | mstate_4803e9afda10d | NO_HEDGE | 6 |
| 78 | 2026-06-18T14:10:26 | VIRTUALUSDT | short | 1m | trend_mode | TREND | TREND | 0.594721 | 0.5962 | +0.25% | 341.58 | -0.5051 | 0.0815 | 0.0407 | -0.6273 | -24.9 | LOSS | TIER_2_TRAILING_STOP | 1084 | v2h_504c081b2eed6b385b0f65786393b872 | v2_fsnap_31c98ce | mstate_173f02ab8de93 | NO_HEDGE | 6 |
| 79 | 2026-06-18T14:10:26 | FILUSDT | short | 1h | trend_mode | TREND | TREND | 0.786818 | 0.789 | +0.28% | 166.67 | -0.3636 | 0.0526 | 0.0263 | -0.4425 | -27.7 | LOSS | TIER_2_TRAILING_STOP | 825 | v2h_43a871b819ff00826d08453193f2df7e | v2_fsnap_e9ff271 | mstate_798f1df13264b | NO_HEDGE | 4 |
| 80 | 2026-06-18T14:11:31 | CRVUSDT | short | 4h | trend_mode | TREND | TREND | 0.225363 | 0.2262 | +0.37% | 465.06 | -0.3891 | 0.0421 | 0.0210 | -0.4522 | -37.1 | LOSS | TIER_2_TRAILING_STOP | 953 | v2h_1c437faa3b906729941fa8d6fc0a8049 | v2_fsnap_dff5317 | mstate_8e22b1a65a51c | NO_HEDGE | 4 |
| 81 | 2026-06-18T14:12:39 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.258664 | 0.25944 | +0.30% | 183.63 | -0.1425 | 0.0191 | 0.0095 | -0.1711 | -30.0 | LOSS | TIER_2_TRAILING_STOP | 68 | v2h_2a85724fa89b935cc27463b017fa8abc | v2_fsnap_0d1b908 | mstate_213831408d02e | NO_HEDGE | 2 |
| 82 | 2026-06-18T14:15:53 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.076 | 0.07415 | -2.43% | 511.54 | 0.9464 | 0.0152 | 0.0076 | 0.9236 | 243.4 | WIN | TIER_2_PROFIT_BANK | 262 | v2h_4cdbbd89b1cb4d6e067e47c7c7ca1890 | v2_fsnap_b9ad46c | mstate_a0e8f00fa15bd | NO_HEDGE | 2 |
| 83 | 2026-06-18T14:17:59 | INJUSDT | short | 1h | trend_mode | TREND | TREND | 5.21883 | 5.238 | +0.37% | 31.84 | -0.6103 | 0.0667 | 0.0334 | -0.7104 | -36.7 | LOSS | TIER_2_TRAILING_STOP | 1663 | v2h_25d6ac267782bd00f7f6a5efc2dd399e | v2_fsnap_2194d3a | mstate_9f506ba75a67f | NO_HEDGE | 7 |
| 84 | 2026-06-18T14:17:59 | APTUSDT | short | 4h | trend_mode | TREND | TREND | 0.64443 | 0.6466 | +0.34% | 213.95 | -0.4644 | 0.0553 | 0.0277 | -0.5474 | -33.7 | LOSS | TIER_2_TRAILING_STOP | 1404 | v2h_084bf13ad78ee9dcf5d3bc29e3940487 | v2_fsnap_4697f3e | mstate_16c5becf8844c | NO_HEDGE | 6 |
| 85 | 2026-06-18T14:17:59 | ALLOUSDT | short | 15m | trend_mode | TREND | TREND | 0.392737 | 0.39575 | +0.77% | 144.43 | -0.4351 | 0.0229 | 0.0114 | -0.4694 | -76.7 | LOSS | TIER_2_TRAILING_STOP | 706 | v2h_55bed80535f674bb8776b2c3cbc58759 | v2_fsnap_7ac6e66 | mstate_d7c57901bf06c | NO_HEDGE | 4 |
| 86 | 2026-06-18T14:17:59 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.10121 | 0.1021 | +0.88% | 481.49 | -0.4284 | 0.0197 | 0.0098 | -0.4579 | -87.9 | LOSS | TIER_1_STOP_LOSS | 580 | v2h_111dcfa7d85b103bc0cd125e793478b0 | v2_fsnap_737b7d0 | mstate_13f1fb02ac2d1 | NO_HEDGE | 3 |
| 87 | 2026-06-18T14:17:59 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0357745 | 0.03599 | +0.60% | 1511.35 | -0.3257 | 0.0218 | 0.0109 | -0.3583 | -60.2 | LOSS | TIER_2_TRAILING_STOP | 517 | v2h_1cf15ed71cd77bf447d32012a023c330 | v2_fsnap_465aaba | mstate_03fe6c5443bbf | NO_HEDGE | 3 |
| 88 | 2026-06-18T14:17:59 | ENAUSDT | short | 4h | trend_mode | TREND | TREND | 0.0924446 | 0.09283 | +0.42% | 581.35 | -0.2240 | 0.0216 | 0.0108 | -0.2564 | -41.7 | LOSS | TIER_2_TRAILING_STOP | 453 | v2h_215c377f9c957470c712ef5201c410f7 | v2_fsnap_ea481dd | mstate_1ebc58460c332 | NO_HEDGE | 3 |
| 89 | 2026-06-18T14:17:59 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.787436 | 0.791 | +0.45% | 40.13 | -0.1430 | 0.0127 | 0.0063 | -0.1621 | -45.3 | LOSS | TIER_2_TRAILING_STOP | 63 | v2h_279e5caeed0f290c863c0366c410ef0e | v2_fsnap_7b45aef | mstate_10bca2a37e158 | NO_HEDGE | 2 |
| 90 | 2026-06-18T14:19:02 | PUMPUSDT | short | 5m | trend_mode | TREND | TREND | 0.00147117 | 0.001481 | +0.67% | 164138.18 | -1.6128 | 0.0972 | 0.0486 | -1.7587 | -66.8 | LOSS | TIER_2_TRAILING_STOP | 1600 | v2h_274196e1c37cbb0d60c0b8c272253986 | v2_fsnap_99fac66 | mstate_af1590cab7d62 | NO_HEDGE | 8 |
| 91 | 2026-06-18T14:19:02 | RENDERUSDT | short | 4h | trend_mode | TREND | TREND | 1.70023 | 1.708 | +0.46% | 122.55 | -0.9519 | 0.0837 | 0.0419 | -1.0775 | -45.7 | LOSS | TIER_2_TRAILING_STOP | 1600 | v2h_0f7a8703dcb21e7974009175c8b007dc | v2_fsnap_128f77b | mstate_d79502672f1c8 | NO_HEDGE | 8 |
| 92 | 2026-06-18T14:19:02 | SEIUSDT | short | 4h | trend_mode | TREND | TREND | 0.0539596 | 0.05427 | +0.58% | 4475.12 | -1.3890 | 0.0971 | 0.0486 | -1.5347 | -57.5 | LOSS | TIER_2_TRAILING_STOP | 1600 | v2h_0bc25c4b26f9cba81a9bf53b57c63035 | v2_fsnap_5a37c60 | mstate_7026151ab9602 | NO_HEDGE | 8 |
| 93 | 2026-06-18T14:19:02 | SUIUSDT | short | 15m | trend_mode | TREND | TREND | 0.737585 | 0.7402 | +0.35% | 358.46 | -0.9373 | 0.1061 | 0.0531 | -1.0965 | -35.5 | LOSS | TIER_2_TRAILING_STOP | 1600 | v2h_13e86ff7ac75672b227b98e5c4516785 | v2_fsnap_816ea57 | mstate_4f6f9e3c045c6 | NO_HEDGE | 8 |
| 94 | 2026-06-18T14:20:04 | HBARUSDT | short | 1m | reduce_size_mod | TREND | TREND | 0.0806678 | 0.08043 | -0.29% | 5725.30 | 1.3617 | 0.1842 | 0.0921 | 1.0854 | 29.5 | WIN | TIER_2_TRAILING_STOP | 3381 | v2h_f11cbb0dd355b8d77e1bce7fe6f98e4b | v2_fsnap_f7adbed | mstate_fbcc7c272bd74 | NO_HEDGE | 16 |
| 95 | 2026-06-18T14:20:04 | AEROUSDT | short | 1m | trend_mode | TREND | TREND | 0.455651 | 0.4568 | +0.25% | 457.53 | -0.5258 | 0.0836 | 0.0418 | -0.6512 | -25.2 | LOSS | TIER_2_TRAILING_STOP | 2103 | v2h_142eda8fb43a8cf655de59a8301087ff | v2_fsnap_00047c0 | mstate_8e875a1274e24 | NO_HEDGE | 8 |
| 96 | 2026-06-18T14:20:04 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0845403 | 0.08505 | +0.60% | 1630.88 | -0.8312 | 0.0555 | 0.0277 | -0.9144 | -60.3 | LOSS | TIER_2_TRAILING_STOP | 1529 | v2h_4abc5e1d084e20de19a099a5a0a0e657 | v2_fsnap_f06273b | mstate_23fdba9b4f134 | NO_HEDGE | 6 |
| 97 | 2026-06-18T14:20:04 | DOTUSDT | short | 1m | trend_mode | TREND | TREND | 0.974032 | 0.98 | +0.61% | 177.72 | -1.0607 | 0.0697 | 0.0348 | -1.1652 | -61.3 | LOSS | TIER_2_TRAILING_STOP | 1403 | v2h_86f99b9e9eaaf9bde7212642680977a7 | v2_fsnap_281ffdd | mstate_b1e0696565e4e | NO_HEDGE | 6 |
| 98 | 2026-06-18T14:20:04 | FETUSDT | short | 15m | trend_mode | TREND | TREND | 0.197507 | 0.1982 | +0.35% | 690.70 | -0.4785 | 0.0548 | 0.0274 | -0.5606 | -35.1 | LOSS | TIER_2_TRAILING_STOP | 1403 | v2h_2b7c8ac981108c388839c9a812385b88 | v2_fsnap_a840392 | mstate_ea2652294b88e | NO_HEDGE | 6 |
| 99 | 2026-06-18T14:20:04 | AAVEUSDT | short | 4h | trend_mode | TREND | TREND | 73.3188 | 73.68 | +0.49% | 1.76 | -0.6371 | 0.0520 | 0.0260 | -0.7151 | -49.3 | LOSS | TIER_2_TRAILING_STOP | 1340 | v2h_06ded7d0da66d09a38bde8a35f5265a9 | v2_fsnap_403d3ea | mstate_e1167089b43a6 | NO_HEDGE | 5 |
| 100 | 2026-06-18T14:20:04 | ADAUSDT | short | 4h | trend_mode | TREND | TREND | 0.164682 | 0.1652 | +0.31% | 785.24 | -0.4066 | 0.0519 | 0.0259 | -0.4845 | -31.4 | LOSS | TIER_2_TRAILING_STOP | 1340 | v2h_1c8ca32fc42f55be16dc6fd5f86b8736 | v2_fsnap_cfaec5e | mstate_5172053cb8d63 | NO_HEDGE | 5 |
| 101 | 2026-06-18T14:20:04 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.62235 | 1.628 | +0.35% | 40.09 | -0.2266 | 0.0261 | 0.0131 | -0.2657 | -34.8 | LOSS | TIER_2_TRAILING_STOP | 768 | v2h_2d817f1f2ac6e728c3fae1a664aa7d2c | v2_fsnap_c7c0dbc | mstate_9a950c33699b8 | NO_HEDGE | 4 |
| 102 | 2026-06-18T14:20:04 | CHZUSDT | short | 1h | trend_mode | TREND | TREND | 0.0227206 | 0.02286 | +0.61% | 2862.73 | -0.3990 | 0.0262 | 0.0131 | -0.4383 | -61.3 | LOSS | TIER_2_TRAILING_STOP | 768 | v2h_7bd109a0194cb6c9cafb3c1929f3d5fa | v2_fsnap_bc4cfe9 | mstate_5c18505f6f78a | NO_HEDGE | 4 |
| 103 | 2026-06-18T14:20:04 | DASHUSDT | short | 5m | trend_mode | TREND | TREND | 35.905 | 36.14 | +0.65% | 2.00 | -0.4705 | 0.0289 | 0.0145 | -0.5139 | -65.4 | LOSS | TIER_2_TRAILING_STOP | 768 | v2h_4eb3a4552f964ca9699d4f422ea9a79b | v2_fsnap_27338ed | mstate_878516290897e | NO_HEDGE | 4 |
| 104 | 2026-06-18T14:20:04 | CRVUSDT | short | 1m | trend_mode | TREND | TREND | 0.225702 | 0.2276 | +0.84% | 124.93 | -0.2371 | 0.0114 | 0.0057 | -0.2541 | -84.1 | LOSS | TIER_1_STOP_LOSS | 379 | v2h_808d1607c9972a7a03b277776caa258c | v2_fsnap_6b95e3a | mstate_5427fecd62f31 | NO_HEDGE | 2 |
| 105 | 2026-06-18T14:20:04 | HUSDT | short | 4h | trend_mode | TREND | TREND | 0.25617 | 0.25834 | +0.85% | 59.48 | -0.1291 | 0.0061 | 0.0031 | -0.1383 | -84.7 | LOSS | TIER_1_STOP_LOSS | 63 | v2h_19b6c08a789a40213b02b69ee256a371 | v2_fsnap_c3c8cdd | mstate_4fca88bd86749 | NO_HEDGE | 1 |
| 106 | 2026-06-18T14:22:10 | ATOMUSDT | short | 5m | reduce_size_mod | TREND | TREND | 1.82933 | 1.834 | +0.26% | 206.65 | -0.9646 | 0.1516 | 0.0758 | -1.1920 | -25.5 | LOSS | TIER_2_TRAILING_STOP | 3507 | v2h_2e69f5b561f576a3dac024073b9fbb1c | v2_fsnap_b5b4a24 | mstate_6344bbdb72965 | NO_HEDGE | 16 |
| 107 | 2026-06-18T14:22:10 | AVAXUSDT | short | 1h | trend_mode | TREND | TREND | 6.61625 | 6.643 | +0.40% | 17.13 | -0.4583 | 0.0455 | 0.0228 | -0.5266 | -40.4 | LOSS | TIER_2_TRAILING_STOP | 1215 | v2h_2dfd012407995051e2456f81c83dbe1b | v2_fsnap_78d2d73 | mstate_bf23fa129b968 | NO_HEDGE | 5 |
| 108 | 2026-06-18T14:22:10 | HOMEUSDT | short | 4h | trend_mode | TREND | TREND | 0.028538 | 0.02862 | +0.29% | 2062.67 | -0.1691 | 0.0236 | 0.0118 | -0.2045 | -28.7 | LOSS | TIER_2_TRAILING_STOP | 639 | v2h_704bba4e0972d52586345b9151afbf1f | v2_fsnap_fea2c1e | mstate_da12c3f721896 | NO_HEDGE | 3 |
| 109 | 2026-06-18T14:22:10 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.563408 | 0.56245 | -0.17% | 58.70 | 0.0562 | 0.0132 | 0.0066 | 0.0364 | 17.0 | WIN | TIER_2_TRAILING_STOP | 572 | v2h_1317647b5a38430b3f9b97b22fd3a700 | v2_fsnap_66c4ab3 | mstate_76063e7da242f | NO_HEDGE | 2 |
| 110 | 2026-06-18T14:24:15 | BCHUSDT | short | 1m | reduce_size_mod | TREND | TREND | 206.066 | 205.97 | -0.05% | 2.13 | 0.2044 | 0.1752 | 0.0876 | -0.0584 | 4.7 | LOSS | TIER_2_TRAILING_STOP | 3632 | v2h_35c43b5c5e72959c3a1f15737a83571c | v2_fsnap_8669b1c | mstate_eba6a6da023e4 | NO_HEDGE | 17 |
| 111 | 2026-06-18T14:24:15 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.0740377 | 0.07469 | +0.88% | 677.75 | -0.4421 | 0.0202 | 0.0101 | -0.4725 | -88.1 | LOSS | TIER_1_STOP_LOSS | 314 | v2h_082838d2b85cc6a2e7bc969a4f494356 | v2_fsnap_abe6c86 | mstate_a8b8d9ab42caf | NO_HEDGE | 2 |
| 112 | 2026-06-18T14:24:40 | TIAUSDT | short | 4h | trend_mode | TREND | TREND | 0.389044 | 0.3925 | +0.89% | 246.10 | -0.8504 | 0.0386 | 0.0193 | -0.9084 | -88.8 | LOSS | TIER_1_STOP_LOSS | 214 | v2h_19837e7ed9bd393e1e2a6208a2a35f69 | v2_fsnap_930b8ea | mstate_20e61d866c412 | NO_HEDGE | 2 |
| 113 | 2026-06-18T14:25:18 | OPUSDT | short | 15m | trend_mode | TREND | TREND | 0.109152 | 0.11 | +0.78% | 836.44 | -0.7094 | 0.0368 | 0.0184 | -0.7646 | -77.7 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_1f5051312c5b54de034bf08aed2cd0db | v2_fsnap_c267b10 | mstate_55a7bfb71ea66 | NO_HEDGE | 2 |
| 114 | 2026-06-18T14:25:18 | PENDLEUSDT | short | 5m | trend_mode | TREND | TREND | 1.44191 | 1.4496 | +0.53% | 66.40 | -0.5106 | 0.0385 | 0.0193 | -0.5684 | -53.3 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_00f870b134022eb33cd8b7cca402a170 | v2_fsnap_ee851bf | mstate_3e5b0f8cdcb6b | NO_HEDGE | 2 |
| 115 | 2026-06-18T14:25:18 | VIRTUALUSDT | short | 4h | trend_mode | TREND | TREND | 0.597407 | 0.6009 | +0.58% | 160.26 | -0.5597 | 0.0385 | 0.0193 | -0.6175 | -58.5 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_51d350b83710c02affbf6b64958cd7a2 | v2_fsnap_897d5e2 | mstate_2f71033a4b08a | NO_HEDGE | 2 |
| 116 | 2026-06-18T14:25:18 | XLMUSDT | short | 5m | trend_mode | TREND | TREND | 0.248371 | 0.25009 | +0.69% | 551.16 | -0.9474 | 0.0551 | 0.0276 | -1.0301 | -69.2 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_01efb9925256a6825a5c07a1e2d77a09 | v2_fsnap_d6b5cfb | mstate_93fa5b1cab5a0 | NO_HEDGE | 3 |
| 117 | 2026-06-18T14:25:18 | XPLUSDT | short | 5m | trend_mode | TREND | TREND | 0.101212 | 0.10201 | +0.79% | 1418.34 | -1.1312 | 0.0579 | 0.0289 | -1.2180 | -78.8 | LOSS | TIER_2_TRAILING_STOP | 252 | v2h_2a0b3bff80834aaac1a388e29b6744e9 | v2_fsnap_78aefbc | mstate_730b2e3a6b7d4 | NO_HEDGE | 3 |
| 118 | 2026-06-18T14:28:21 | ALLOUSDT | short | 1m | trend_mode | TREND | TREND | 0.39349 | 0.38865 | -1.23% | 68.27 | 0.3304 | 0.0106 | 0.0053 | 0.3145 | 123.0 | WIN | TIER_2_TAKE_PROFIT | 183 | v2h_2dccbb87ad572d7e65d8773470962732 | v2_fsnap_93a84a9 | mstate_5fd509c780e84 | NO_HEDGE | 1 |
| 119 | 2026-06-18T14:28:35 | MITOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0260184 | 0.02516 | -3.30% | 2444.48 | 2.0982 | 0.0246 | 0.0123 | 2.0613 | 329.9 | WIN | TIER_2_PROFIT_BANK | 511 | v2h_12490423af61d3b46396c6c75c4f3598 | v2_fsnap_88b4dcb | mstate_d99406ab8f75a | NO_HEDGE | 2 |
| 120 | 2026-06-18T14:30:41 | LITUSDT | short | 15m | trend_mode | TREND | TREND | 1.63859 | 1.6172 | -1.31% | 68.40 | 1.4630 | 0.0442 | 0.0221 | 1.3967 | 130.5 | WIN | TIER_2_TAKE_PROFIT | 637 | v2h_1821f604f918e02c76afa211c8b1fe8b | v2_fsnap_fe7becc | mstate_68c6b86e12f0a | NO_HEDGE | 3 |
| 121 | 2026-06-18T14:32:48 | NIGHTUSDT | short | 4h | trend_mode | TREND | TREND | 0.0301917 | 0.03054 | +1.15% | 11152.46 | -3.8844 | 0.1362 | 0.0681 | -4.0888 | -115.4 | LOSS | TIER_1_STOP_LOSS | 2930 | v2h_00ae414347964f9202073b869e7c052f | v2_fsnap_d1a06da | mstate_75f42e707e316 | NO_HEDGE | 12 |
| 122 | 2026-06-18T14:32:48 | LABUSDT | short | 15m | trend_mode | TREND | TREND | 16.0219 | 16.104 | +0.51% | 5.93 | -0.4869 | 0.0382 | 0.0191 | -0.5443 | -51.2 | LOSS | TIER_2_TRAILING_STOP | 827 | v2h_0bb6151575b9094ad118330dcb990944 | v2_fsnap_b8b43e1 | mstate_42b04392c71e0 | NO_HEDGE | 3 |
| 123 | 2026-06-18T14:32:48 | MEGAUSDT | short | 15m | trend_mode | TREND | TREND | 0.0657218 | 0.06491 | -1.24% | 1705.34 | 1.3843 | 0.0443 | 0.0221 | 1.3179 | 123.5 | WIN | TIER_2_TAKE_PROFIT | 764 | v2h_1bafb4fce6615a024b1b89776a3f94db | v2_fsnap_2e5c3ea | mstate_fc13150fb6f27 | NO_HEDGE | 3 |
| 124 | 2026-06-18T14:34:55 | WLDUSDT | short | 15m | trend_mode | TREND | TREND | 0.62822 | 0.6205 | -1.23% | 338.61 | 2.6139 | 0.0840 | 0.0420 | 2.4879 | 122.9 | WIN | TIER_2_TAKE_PROFIT | 829 | v2h_27d6be400109444fa2f5d5d33c8a7d69 | v2_fsnap_1f067cc | mstate_e54cbe1657297 | NO_HEDGE | 5 |
| 125 | 2026-06-18T14:38:55 | ONDOUSDT | short | 1h | trend_mode | TREND | TREND | 0.37504 | 0.3747 | -0.09% | 477.40 | 0.1625 | 0.0716 | 0.0358 | 0.0552 | 9.1 | WIN | TIER_2_PROFIT_LOCK | 1069 | v2h_1cf564fc34c095235921ede9cf5698df | v2_fsnap_3327447 | mstate_b9fd6f3c6e172 | NO_HEDGE | 4 |
| 126 | 2026-06-18T14:39:17 | NEARUSDT | short | 1m | trend_mode | TREND | TREND | 2.26955 | 2.277 | +0.33% | 71.29 | -0.5314 | 0.0649 | 0.0325 | -0.6288 | -32.8 | LOSS | TIER_2_TRAILING_STOP | 1153 | v2h_0621cafab18873709ce68bfd2b81ed53 | v2_fsnap_67a5747 | mstate_ef7a9368634cd | NO_HEDGE | 4 |
| 127 | 2026-06-18T14:39:17 | BEATUSDT | short | 4h | trend_mode | TREND | TREND | 1.62003 | 1.627 | +0.43% | 67.86 | -0.4733 | 0.0442 | 0.0221 | -0.5396 | -43.1 | LOSS | TIER_2_TRAILING_STOP | 776 | v2h_17dbd5e3983f7e720767b436609e8839 | v2_fsnap_184a332 | mstate_dbeae0b1079d8 | NO_HEDGE | 4 |
| 128 | 2026-06-18T14:41:05 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.07852 | 0.07687 | -2.10% | 226.75 | 0.3741 | 0.0070 | 0.0035 | 0.3637 | 210.1 | WIN | TIER_2_PROFIT_BANK | 45 | v2h_4d8bfa6eedf45f2520df1554c840b27b | v2_fsnap_8dd1444 | mstate_2e2d1032f3cc2 | NO_HEDGE | 1 |
| 129 | 2026-06-18T14:41:24 | APTUSDT | short | 1m | trend_mode | TREND | TREND | 0.649864 | 0.6519 | +0.31% | 218.12 | -0.4440 | 0.0569 | 0.0284 | -0.5293 | -31.3 | LOSS | TIER_2_TRAILING_STOP | 966 | v2h_3809543553a62c64a07b4932c0f78b9a | v2_fsnap_f2d4feb | mstate_b8bb034d116f0 | NO_HEDGE | 5 |
| 130 | 2026-06-18T14:41:24 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0851782 | 0.08532 | +0.17% | 1430.74 | -0.2029 | 0.0488 | 0.0244 | -0.2762 | -16.7 | LOSS | TIER_2_TRAILING_STOP | 966 | v2h_27df72beabb70fc5abdeffe12fed4fa4 | v2_fsnap_eba2f5e | mstate_5b1c6abe1d240 | NO_HEDGE | 4 |
| 131 | 2026-06-18T14:41:24 | BSBUSDT | short | 5m | trend_mode | TREND | TREND | 0.570747 | 0.57422 | +0.61% | 162.57 | -0.5646 | 0.0373 | 0.0187 | -0.6206 | -60.8 | LOSS | TIER_2_TRAILING_STOP | 903 | v2h_181b2a2581020e0c07584317bba282b6 | v2_fsnap_9bc0920 | mstate_94376847577e0 | NO_HEDGE | 3 |
| 132 | 2026-06-18T14:41:24 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.388089 | 0.38859 | +0.13% | 187.81 | -0.0941 | 0.0292 | 0.0146 | -0.1379 | -12.9 | LOSS | TIER_2_TRAILING_STOP | 706 | v2h_2e37bdfa2324bfa6ac08362733279070 | v2_fsnap_af73582 | mstate_4853c020faf00 | NO_HEDGE | 3 |
| 133 | 2026-06-18T14:41:24 | CHZUSDT | short | 4h | trend_mode | TREND | TREND | 0.0229444 | 0.02306 | +0.50% | 3802.12 | -0.4395 | 0.0351 | 0.0175 | -0.4921 | -50.4 | LOSS | TIER_2_TRAILING_STOP | 453 | v2h_201b0a84ed621183249b3ec32b5244a8 | v2_fsnap_4ae6f39 | mstate_4078bc43b1aa0 | NO_HEDGE | 4 |
| 134 | 2026-06-18T14:43:30 | BSBUSDT | short | 1m | trend_mode | TREND | TREND | 0.57422 | 0.57974 | +0.96% | 31.05 | -0.1714 | 0.0072 | 0.0036 | -0.1822 | -96.1 | LOSS | TIER_1_STOP_LOSS | 63 | v2h_0767c7566f28c859cc73048c9b330f56 | v2_fsnap_5f235d7 | mstate_cbd48d7f4296d | NO_HEDGE | 1 |
| 135 | 2026-06-18T14:43:30 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.07687 | 0.0782 | +1.73% | 220.05 | -0.2927 | 0.0069 | 0.0034 | -0.3030 | -173.0 | LOSS | TIER_1_STOP_LOSS | 63 | v2h_03d752c1c8aa8844cfc4f8a915b9b2c6 | v2_fsnap_56a54dc | mstate_b0a27dee124c3 | NO_HEDGE | 1 |
| 136 | 2026-06-18T14:47:42 | HYPEUSDT | short | 5m | trend_mode | TREND | TREND | 70.0971 | 69.744 | -0.50% | 2.66 | 0.9390 | 0.0742 | 0.0371 | 0.8277 | 50.4 | WIN | TIER_2_TRAILING_STOP | 1721 | v2h_1bc43bfeeae78e22295400d5e4e81c19 | v2_fsnap_789ccc4 | mstate_2c3cc0a5a5990 | NO_HEDGE | 6 |
| 137 | 2026-06-18T14:47:42 | TRUMPUSDT | short | 15m | trend_mode | TREND | TREND | 1.8647 | 1.874 | +0.50% | 108.50 | -1.0090 | 0.0813 | 0.0407 | -1.1310 | -49.9 | LOSS | TIER_2_TRAILING_STOP | 1596 | v2h_23f07c68c54608c0051190be1023ff1e | v2_fsnap_97f4fdd | mstate_a86ce288d7494 | NO_HEDGE | 5 |
| 138 | 2026-06-18T14:47:42 | ENAUSDT | short | 1m | trend_mode | TREND | TREND | 0.093172 | 0.09428 | +1.19% | 421.50 | -0.4670 | 0.0159 | 0.0079 | -0.4909 | -118.9 | LOSS | TIER_1_STOP_LOSS | 506 | v2h_2f967dd3d5fcac757f4c318e36ce3fce | v2_fsnap_a1c1d53 | mstate_81c01f5e939c9 | NO_HEDGE | 2 |
| 139 | 2026-06-18T14:47:42 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.637 | 1.644 | +0.43% | 22.10 | -0.1547 | 0.0145 | 0.0073 | -0.1765 | -42.8 | LOSS | TIER_2_TRAILING_STOP | 379 | v2h_3eb549303542315b7b548e0925df73ad | v2_fsnap_bf7176b | mstate_323994fc73130 | NO_HEDGE | 2 |
| 140 | 2026-06-18T14:47:42 | HOMEUSDT | short | 1m | trend_mode | TREND | TREND | 0.02811 | 0.02751 | -2.13% | 510.54 | 0.3063 | 0.0056 | 0.0028 | 0.2979 | 213.4 | WIN | TIER_2_PROFIT_BANK | 190 | v2h_01d62c48d8f79b43e0c751b57b41b8db | v2_fsnap_6268ba4 | mstate_cacc22e6d8b70 | NO_HEDGE | 1 |
| 141 | 2026-06-18T14:49:54 | AEROUSDT | short | 1h | trend_mode | TREND | TREND | 0.458431 | 0.4613 | +0.63% | 386.70 | -1.1093 | 0.0714 | 0.0357 | -1.2163 | -62.6 | LOSS | TIER_2_TRAILING_STOP | 1602 | v2h_13a533ee6fcac324f7d1651fc9db5f37 | v2_fsnap_10e856d | mstate_88e63fc3d4c2e | NO_HEDGE | 6 |
| 142 | 2026-06-18T14:49:54 | FILUSDT | short | 4h | trend_mode | TREND | TREND | 0.79749 | 0.798 | +0.06% | 57.88 | -0.0295 | 0.0185 | 0.0092 | -0.0572 | -6.4 | LOSS | TIER_2_TRAILING_STOP | 447 | v2h_20bf6192a404c9d94e0a25b5063c9ebe | v2_fsnap_fd85b10 | mstate_c8fa89ab90ffd | NO_HEDGE | 2 |
| 143 | 2026-06-18T14:49:54 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.247737 | 0.25194 | +1.70% | 147.51 | -0.6199 | 0.0149 | 0.0074 | -0.6422 | -169.6 | LOSS | TIER_1_STOP_LOSS | 322 | v2h_393436a1fd655dca1ee96f7a8e174bba | v2_fsnap_5d64b81 | mstate_f3aca5f19365b | NO_HEDGE | 2 |
| 144 | 2026-06-18T14:49:54 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.644 | 1.75 | +6.45% | 11.28 | -1.1958 | 0.0079 | 0.0039 | -1.2076 | -644.8 | LOSS | TIER_1_STOP_LOSS | 69 | v2h_2619bdb0f19d22a5cf285cb38dc34ba4 | v2_fsnap_2fae822 | mstate_97b642be6b6a7 | NO_HEDGE | 1 |
| 145 | 2026-06-18T14:52:02 | XMRUSDT | short | 4h | trend_mode | TREND | TREND | 331.337 | 327.16 | -1.26% | 0.66 | 2.7640 | 0.0866 | 0.0433 | 2.6341 | 126.1 | WIN | TIER_2_TAKE_PROFIT | 1856 | v2h_358eff4da8884ad173c02ae36d9867f1 | v2_fsnap_ab9604d | mstate_a327cd869a77e | NO_HEDGE | 7 |
| 146 | 2026-06-18T14:52:02 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.58019 | 0.58643 | +1.08% | 31.97 | -0.1995 | 0.0075 | 0.0037 | -0.2107 | -107.6 | LOSS | TIER_1_STOP_LOSS | 197 | v2h_42a8a5ff0de308feda6fc429ea4ce18a | v2_fsnap_a04563c | mstate_7b8b86e40eb0a | NO_HEDGE | 1 |
| 147 | 2026-06-18T14:52:02 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.08012 | 0.07799 | -2.66% | 158.56 | 0.3377 | 0.0049 | 0.0025 | 0.3303 | 265.9 | WIN | TIER_2_PROFIT_BANK | 65 | v2h_22eda3e10013152700ac6a71cb7e9048 | v2_fsnap_9c45302 | mstate_6b62d110c6f83 | NO_HEDGE | 1 |
| 148 | 2026-06-18T14:58:24 | JTOUSDT | short | 5m | trend_mode | TREND | TREND | 0.71714 | 0.7198 | +0.37% | 264.13 | -0.7026 | 0.0760 | 0.0380 | -0.8167 | -37.1 | LOSS | TIER_2_TRAILING_STOP | 2363 | v2h_0fd996fe02e5d4c58683198b3f1426a0 | v2_fsnap_0a47531 | mstate_34b98c9452af8 | NO_HEDGE | 7 |
| 149 | 2026-06-18T14:58:24 | LDOUSDT | short | 4h | trend_mode | TREND | TREND | 0.280069 | 0.281 | +0.33% | 821.11 | -0.7642 | 0.0923 | 0.0461 | -0.9026 | -33.2 | LOSS | TIER_2_TRAILING_STOP | 2363 | v2h_281355cfb55954b6d9a3378d98c1634e | v2_fsnap_25615c3 | mstate_fe6c640964002 | NO_HEDGE | 9 |
| 150 | 2026-06-18T14:58:24 | CHZUSDT | short | 15m | trend_mode | TREND | TREND | 0.0229985 | 0.02301 | +0.05% | 1462.40 | -0.0167 | 0.0135 | 0.0067 | -0.0369 | -5.0 | LOSS | TIER_2_TRAILING_STOP | 579 | v2h_043bd410e8193f4ac4dcb37977b39797 | v2_fsnap_2e34306 | mstate_2185709332f8f | NO_HEDGE | 2 |
| 151 | 2026-06-18T14:58:24 | ENAUSDT | short | 1m | trend_mode | TREND | TREND | 0.0941871 | 0.09456 | +0.40% | 351.40 | -0.1310 | 0.0133 | 0.0066 | -0.1510 | -39.6 | LOSS | TIER_2_TRAILING_STOP | 447 | v2h_4aa4f1f994a13ea11883b940a10eb5d5 | v2_fsnap_55714c2 | mstate_296b91f5e2253 | NO_HEDGE | 2 |
| 152 | 2026-06-18T14:58:24 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.0273184 | 0.02741 | +0.34% | 1185.17 | -0.1086 | 0.0130 | 0.0065 | -0.1281 | -33.5 | LOSS | TIER_2_TRAILING_STOP | 447 | v2h_4275c15c3e5197e4c8d93ee23f940b67 | v2_fsnap_102984f | mstate_19d3be0a6f218 | NO_HEDGE | 2 |
| 153 | 2026-06-18T14:58:24 | LITUSDT | short | 15m | trend_mode | TREND | TREND | 1.62972 | 1.642 | +0.75% | 22.40 | -0.2750 | 0.0147 | 0.0074 | -0.2971 | -75.3 | LOSS | TIER_2_TRAILING_STOP | 319 | v2h_2b56f23c520d3952a9487577b0497824 | v2_fsnap_c21ca77 | mstate_97ce25bf0fa0e | NO_HEDGE | 2 |
| 154 | 2026-06-18T14:59:28 | AAVEUSDT | short | 1m | trend_mode | TREND | TREND | 73.6816 | 73.8 | +0.16% | 2.90 | -0.3428 | 0.0855 | 0.0427 | -0.4710 | -16.1 | LOSS | TIER_2_TRAILING_STOP | 2176 | v2h_3af2bc4fd577ac98ef47f85b06b8e51a | v2_fsnap_ef71485 | mstate_98fe0acf6c6e8 | NO_HEDGE | 7 |
| 155 | 2026-06-18T14:59:28 | CRVUSDT | short | 5m | trend_mode | TREND | TREND | 0.22613 | 0.2264 | +0.12% | 531.97 | -0.1438 | 0.0482 | 0.0241 | -0.2161 | -12.0 | LOSS | TIER_2_TRAILING_STOP | 1537 | v2h_1147fe9edb0de86bbddb743c2118cf2c | v2_fsnap_a7db990 | mstate_fdeea19a77293 | NO_HEDGE | 5 |
| 156 | 2026-06-18T14:59:28 | DOTUSDT | short | 1m | trend_mode | TREND | TREND | 0.977602 | 0.979 | +0.14% | 89.23 | -0.1247 | 0.0349 | 0.0175 | -0.1771 | -14.3 | LOSS | TIER_2_TRAILING_STOP | 1411 | v2h_0000f20e93f41e5ef901e755587a7550 | v2_fsnap_4f58e7e | mstate_e28085414bf55 | NO_HEDGE | 4 |
| 157 | 2026-06-18T14:59:28 | APTUSDT | short | 1m | trend_mode | TREND | TREND | 0.649042 | 0.6493 | +0.04% | 92.04 | -0.0238 | 0.0239 | 0.0120 | -0.0596 | -4.0 | LOSS | TIER_2_TRAILING_STOP | 1021 | v2h_2592cefaea661c47ff06fe32cba9e2c2 | v2_fsnap_b2b6ec2 | mstate_c18b1e140b14b | NO_HEDGE | 3 |
| 158 | 2026-06-18T14:59:28 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0850748 | 0.08547 | +0.46% | 459.25 | -0.1815 | 0.0157 | 0.0079 | -0.2051 | -46.5 | LOSS | TIER_2_TRAILING_STOP | 643 | v2h_66cd402dcab76eb9a363b86ae452a442 | v2_fsnap_83a3ff6 | mstate_112a8d59fa17d | NO_HEDGE | 2 |
| 159 | 2026-06-18T14:59:28 | ESPORTSUSDT | short | 5m | trend_mode | TREND | TREND | 0.08327 | 0.085 | +2.08% | 176.58 | -0.3055 | 0.0060 | 0.0030 | -0.3145 | -207.8 | LOSS | TIER_1_STOP_LOSS | 1 | v2h_0e7842606bad5e1b9ee7cc1c8de78137 | v2_fsnap_65fde2f | mstate_69c0f9e8ee758 | NO_HEDGE | 1 |
| 160 | 2026-06-18T15:01:39 | ALGOUSDT | short | 15m | trend_mode | TREND | TREND | 0.101632 | 0.1002 | -1.41% | 1822.28 | 2.6097 | 0.0730 | 0.0365 | 2.5001 | 140.9 | WIN | TIER_2_TAKE_PROFIT | 2307 | v2h_25aceb1f20019f78e3d1ee189a0df678 | v2_fsnap_6fca687 | mstate_5a5de1979c002 | NO_HEDGE | 8 |
| 161 | 2026-06-18T15:01:39 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0359079 | 0.03539 | -1.44% | 5250.55 | 2.7193 | 0.0743 | 0.0372 | 2.6078 | 144.2 | WIN | TIER_2_TAKE_PROFIT | 2118 | v2h_2dfa68ca37b789d1466b7f10bf3929bb | v2_fsnap_cbdea35 | mstate_d9c1e582c41a7 | NO_HEDGE | 7 |
| 162 | 2026-06-18T15:01:39 | BEATUSDT | short | 4h | trend_mode | TREND | TREND | 1.708 | 1.733 | +1.46% | 8.61 | -0.2152 | 0.0060 | 0.0030 | -0.2242 | -146.4 | LOSS | TIER_1_STOP_LOSS | 133 | v2h_0885207706a68e0428b16a2848a2d9bb | v2_fsnap_03799e7 | mstate_887bfb8c52cc3 | NO_HEDGE | 1 |
| 163 | 2026-06-18T15:01:39 | BSBUSDT | short | 15m | trend_mode | TREND | TREND | 0.59446 | 0.60658 | +2.04% | 24.74 | -0.2998 | 0.0060 | 0.0030 | -0.3088 | -203.9 | LOSS | TIER_1_STOP_LOSS | 133 | v2h_1a296e6e407138840b2f4c5c55464aa5 | v2_fsnap_b3ef0b9 | mstate_cc5f77b33dbba | NO_HEDGE | 1 |
| 164 | 2026-06-18T15:02:14 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.25133 | 0.25491 | +1.42% | 68.16 | -0.2440 | 0.0069 | 0.0035 | -0.2544 | -142.4 | LOSS | TIER_1_STOP_LOSS | 167 | v2h_2ae6607eb9c78a07f6811519446cb623 | v2_fsnap_6206e93 | mstate_7f5922df0013a | NO_HEDGE | 1 |
| 165 | 2026-06-18T15:03:46 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.384254 | 0.38558 | +0.34% | 146.63 | -0.1944 | 0.0226 | 0.0113 | -0.2283 | -34.5 | LOSS | TIER_2_TRAILING_STOP | 901 | v2h_285de3c26a35d0d3da227da02d261c33 | v2_fsnap_efb6ea9 | mstate_413f65b770e64 | NO_HEDGE | 3 |
| 166 | 2026-06-18T15:03:46 | AEROUSDT | short | 5m | trend_mode | TREND | TREND | 0.459449 | 0.4528 | -1.45% | 100.20 | 0.6662 | 0.0181 | 0.0091 | 0.6390 | 144.7 | WIN | TIER_2_TAKE_PROFIT | 260 | v2h_01584d5b1084ddb646e6632944f73eaf | v2_fsnap_3c83321 | mstate_6141f777e0e14 | NO_HEDGE | 2 |
| 167 | 2026-06-18T15:03:46 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.733 | 1.76 | +1.56% | 14.39 | -0.3886 | 0.0101 | 0.0051 | -0.4038 | -155.8 | LOSS | TIER_1_STOP_LOSS | 64 | v2h_1c3509d0b1d594109ef999ba706b28ad | v2_fsnap_296d34c | mstate_05d2e066aaa29 | NO_HEDGE | 1 |
| 168 | 2026-06-18T15:05:53 | HYPEUSDT | short | 1h | trend_mode | TREND | TREND | 69.3274 | 68.466 | -1.24% | 0.98 | 0.8442 | 0.0268 | 0.0134 | 0.8039 | 124.2 | WIN | TIER_2_TAKE_PROFIT | 896 | v2h_36f9ffadc5d7cb689287bce4f8eabf1f | v2_fsnap_9bad51b | mstate_c2c700a8e17b3 | NO_HEDGE | 3 |
| 169 | 2026-06-18T15:08:01 | INJUSDT | short | 15m | trend_mode | TREND | TREND | 5.20524 | 5.231 | +0.49% | 12.57 | -0.3237 | 0.0263 | 0.0131 | -0.3631 | -49.5 | LOSS | TIER_2_TRAILING_STOP | 896 | v2h_210e76d7a088196c2e7fac41e733e10b | v2_fsnap_4479b1e | mstate_4eb5dab1592e1 | NO_HEDGE | 3 |
| 170 | 2026-06-18T15:08:01 | LABUSDT | short | 5m | trend_mode | TREND | TREND | 16.0817 | 15.788 | -1.83% | 3.93 | 1.1541 | 0.0248 | 0.0124 | 1.1168 | 182.6 | WIN | TIER_2_PROFIT_BANK | 896 | v2h_1b6dd60e1dfc48ce84fe3eadbc0e990d | v2_fsnap_1c5f394 | mstate_cb7c20e2d56ed | NO_HEDGE | 3 |
| 171 | 2026-06-18T15:08:50 | MITOUSDT | short | 15m | trend_mode | TREND | TREND | 0.0252556 | 0.02549 | +0.93% | 1763.34 | -0.4133 | 0.0180 | 0.0090 | -0.4403 | -92.8 | LOSS | TIER_1_STOP_LOSS | 496 | v2h_327065ab5ac795ceb6ab7180ca66128c | v2_fsnap_1d0b8fa | mstate_2de97db13db20 | NO_HEDGE | 2 |
| 172 | 2026-06-18T15:08:50 | ONDOUSDT | short | 1h | trend_mode | TREND | TREND | 0.374793 | 0.3735 | -0.35% | 151.32 | 0.1957 | 0.0226 | 0.0113 | 0.1618 | 34.5 | WIN | TIER_2_TRAILING_STOP | 496 | v2h_448c5c226f66d63d8e09547d50f1ec10 | v2_fsnap_f529c92 | mstate_2a63e2af1d732 | NO_HEDGE | 2 |
| 173 | 2026-06-18T15:09:11 | NEARUSDT | short | 1m | trend_mode | TREND | TREND | 2.26777 | 2.274 | +0.27% | 25.01 | -0.1559 | 0.0227 | 0.0114 | -0.1900 | -27.5 | LOSS | TIER_2_TRAILING_STOP | 517 | v2h_7f26f2e2de8e78ee2b9a3638c370a8d7 | v2_fsnap_5867b35 | mstate_7028ce78aa37a | NO_HEDGE | 2 |
| 174 | 2026-06-18T15:10:15 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0354059 | 0.03554 | +0.38% | 1139.65 | -0.1528 | 0.0162 | 0.0081 | -0.1771 | -37.9 | LOSS | TIER_2_TRAILING_STOP | 326 | v2h_153354e04517c2e60d55e994db565e10 | v2_fsnap_652933c | mstate_3a865c2045556 | NO_HEDGE | 2 |
| 175 | 2026-06-18T15:10:15 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.594235 | 0.59932 | +0.86% | 58.59 | -0.2980 | 0.0140 | 0.0070 | -0.3190 | -85.6 | LOSS | TIER_1_STOP_LOSS | 326 | v2h_03a1cff0ab868012b2013c30ec3c31a5 | v2_fsnap_e7f9410 | mstate_4c99a15e0d2b7 | NO_HEDGE | 2 |
| 176 | 2026-06-18T15:16:38 | AVAXUSDT | short | 15m | trend_mode | TREND | TREND | 6.61229 | 6.529 | -1.26% | 34.52 | 2.8753 | 0.0902 | 0.0451 | 2.7400 | 126.0 | WIN | TIER_2_TAKE_PROFIT | 3017 | v2h_06ebe0ef27b0970e1a87e56c16683fd3 | v2_fsnap_2879bae | mstate_ff76cfd3c7004 | NO_HEDGE | 8 |
| 177 | 2026-06-18T15:16:38 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.715 | 1.71 | -0.29% | 7.27 | 0.0363 | 0.0050 | 0.0025 | 0.0289 | 29.2 | WIN | TIER_2_TRAILING_STOP | 319 | v2h_036b77790103509b591b1d12fff98d29 | v2_fsnap_7ab3896 | mstate_6a83f83349015 | NO_HEDGE | 1 |
| 178 | 2026-06-18T15:18:51 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.791553 | 0.782 | -1.21% | 116.90 | 1.1167 | 0.0366 | 0.0183 | 1.0619 | 120.7 | WIN | TIER_2_TAKE_PROFIT | 1164 | v2h_1a23935aceeae7ce07b4704679c6dea3 | v2_fsnap_ad34fc0 | mstate_b09660ee9af21 | NO_HEDGE | 4 |
| 179 | 2026-06-18T15:20:57 | AVAXUSDT | short | 4h | trend_mode | TREND | TREND | 6.48 | 6.396 | -1.30% | 2.04 | 0.1710 | 0.0052 | 0.0026 | 0.1632 | 129.6 | WIN | TIER_2_TAKE_PROFIT | 64 | v2h_161c5a908a87399b60d260cfc0b2e3e3 | v2_fsnap_9eb3a3c | mstate_2eec6b340c698 | NO_HEDGE | 1 |
| 180 | 2026-06-18T15:23:05 | MEGAUSDT | short | 15m | trend_mode | TREND | TREND | 0.0644648 | 0.06439 | -0.12% | 1398.53 | 0.1046 | 0.0360 | 0.0180 | 0.0506 | 11.6 | WIN | TIER_2_TRAILING_STOP | 1351 | v2h_0acc7197e4eaa67ff8c75299370b1889 | v2_fsnap_ec7b19a | mstate_edf8871ff7ff1 | NO_HEDGE | 4 |
| 181 | 2026-06-18T15:24:09 | ALICEUSDT | short | 1m | mean_reversion_ | RANGE | RANGE | 0.1038 | 0.1022 | -1.54% | 183.73 | 0.2940 | 0.0075 | 0.0038 | 0.2827 | 154.1 | WIN | TIER_2_TAKE_PROFIT | 900 | v2h_3876e0a00ab566f47bae60055e932e3f | null | mstate_e83314e957253 | NO_HEDGE | 1 |
| 182 | 2026-06-18T15:24:09 | 1000PEPEUSDT | short | 1m | mean_reversion_ | RANGE | RANGE | 0.0028741 | 0.0028339 | -1.40% | 6971.07 | 0.2802 | 0.0079 | 0.0040 | 0.2684 | 139.9 | WIN | TIER_2_TAKE_PROFIT | 900 | v2h_e7730171777d26ead0408bdbdabec3d6 | null | mstate_c77ac2c1c59c5 | NO_HEDGE | 1 |
| 183 | 2026-06-18T15:25:13 | BNBUSDT | short | 1h | reduce_size_mod | TREND | TREND | 590.442 | 583.16 | -1.23% | 1.26 | 9.1751 | 0.2939 | 0.1469 | 8.7343 | 123.3 | WIN | TIER_2_TAKE_PROFIT | 7290 | v2h_0cc5fdce750b2dbe72a4897bbceff942 | v2_fsnap_cd58f1f | mstate_7f8b7a57933f4 | NO_HEDGE | 27 |
| 184 | 2026-06-18T15:25:13 | ADAUSDT | short | 4h | trend_mode | TREND | TREND | 0.164792 | 0.1628 | -1.21% | 1605.02 | 3.1966 | 0.1045 | 0.0523 | 3.0398 | 120.9 | WIN | TIER_2_TAKE_PROFIT | 3721 | v2h_642351defd4c8ea7a847959ae8465915 | v2_fsnap_09a26ab | mstate_1898550e975ff | NO_HEDGE | 9 |
| 185 | 2026-06-18T15:25:13 | FETUSDT | short | 1m | trend_mode | TREND | TREND | 0.197156 | 0.1946 | -1.30% | 743.96 | 1.9017 | 0.0579 | 0.0290 | 1.8149 | 129.7 | WIN | TIER_2_TAKE_PROFIT | 2693 | v2h_2156f24670aec0ed7487aee8b685cebb | v2_fsnap_46ef786 | mstate_4218266279036 | NO_HEDGE | 8 |
| 186 | 2026-06-18T15:25:13 | OPUSDT | short | 4h | trend_mode | TREND | TREND | 0.10826 | 0.1069 | -1.26% | 931.18 | 1.2665 | 0.0398 | 0.0199 | 1.2068 | 125.6 | WIN | TIER_2_TAKE_PROFIT | 1479 | v2h_1215a22631554b824f92661dec35aafb | v2_fsnap_bd0a4d6 | mstate_c4eb803b24d73 | NO_HEDGE | 5 |
| 187 | 2026-06-18T15:25:13 | APTUSDT | short | 4h | trend_mode | TREND | TREND | 0.645391 | 0.6342 | -1.73% | 104.33 | 1.1676 | 0.0265 | 0.0132 | 1.1279 | 173.4 | WIN | TIER_2_TAKE_PROFIT | 1351 | v2h_5232e53597c7beca8e412d21c2a46a6a | v2_fsnap_db170b0 | mstate_235a3f7fb2288 | NO_HEDGE | 3 |
| 188 | 2026-06-18T15:26:16 | ASTERUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 0.6626 | 0.6546 | -1.21% | 29.92 | 0.2394 | 0.0078 | 0.0039 | 0.2276 | 120.7 | WIN | TIER_2_TAKE_PROFIT | 513 | v2h_1b6864124db02b3dc433ff449eee040e | null | mstate_46fec46f7d85f | NO_HEDGE | 1 |
| 189 | 2026-06-18T15:27:21 | DASHUSDT | short | 1h | trend_mode | TREND | TREND | 35.8971 | 35.44 | -1.27% | 6.14 | 2.8064 | 0.0870 | 0.0435 | 2.6758 | 127.3 | WIN | TIER_2_TAKE_PROFIT | 3210 | v2h_49e2b629f44ffd85f2f413ed2ac8946c | v2_fsnap_c9aa6f4 | mstate_df0f48904b1e9 | NO_HEDGE | 11 |
| 190 | 2026-06-18T15:29:14 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.70523 | 1.747 | +2.45% | 22.78 | -0.9514 | 0.0159 | 0.0080 | -0.9753 | -244.9 | LOSS | TIER_1_STOP_LOSS | 433 | v2h_44c719eeed16e35d8a4b08b620b7f3aa | v2_fsnap_1749789 | mstate_32af30412277a | NO_HEDGE | 2 |
| 191 | 2026-06-18T15:29:14 | BSBUSDT | short | 15m | trend_mode | TREND | TREND | 0.57338 | 0.58951 | +2.81% | 33.36 | -0.5382 | 0.0079 | 0.0039 | -0.5500 | -281.3 | LOSS | TIER_1_STOP_LOSS | 115 | v2h_0665e3ad601fe78d2f016d6f07d352f2 | v2_fsnap_1dafaeb | mstate_c4b864f0fea46 | NO_HEDGE | 1 |
| 192 | 2026-06-18T15:31:08 | ICPUSDT | short | 1m | trend_mode | TREND | TREND | 2.27552 | 2.245 | -1.34% | 149.65 | 4.5668 | 0.1344 | 0.0672 | 4.3653 | 134.1 | WIN | TIER_2_TAKE_PROFIT | 4327 | v2h_699375a9e57ddf4add6511ab85cdf1f3 | v2_fsnap_ad6c242 | mstate_8810b6b57bf41 | NO_HEDGE | 12 |
| 193 | 2026-06-18T15:31:08 | ARBUSDT | short | 1h | trend_mode | TREND | TREND | 0.0845736 | 0.08343 | -1.35% | 1192.67 | 1.3640 | 0.0398 | 0.0199 | 1.3043 | 135.2 | WIN | TIER_2_TAKE_PROFIT | 1706 | v2h_19f3a2091fabe8c7eca6408d611c4adb | v2_fsnap_a2f5eb9 | mstate_5fe994bb3761b | NO_HEDGE | 4 |
| 194 | 2026-06-18T15:32:46 | ALGOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0995156 | 0.0995 | -0.02% | 999.85 | 0.0156 | 0.0398 | 0.0199 | -0.0441 | 1.6 | LOSS | TIER_2_TRAILING_STOP | 1804 | v2h_4c81f87ee700bf944f6e79086cfb6bb1 | v2_fsnap_25813a3 | mstate_0fbe9cdf22ea2 | NO_HEDGE | 5 |
| 195 | 2026-06-18T15:32:46 | ALLOUSDT | short | 1h | trend_mode | TREND | TREND | 0.384826 | 0.38546 | +0.16% | 137.47 | -0.0872 | 0.0212 | 0.0106 | -0.1190 | -16.5 | LOSS | TIER_2_TRAILING_STOP | 1287 | v2h_1405ee0ede08b2c98dff15d326246374 | v2_fsnap_b58e538 | mstate_581cc84567b66 | NO_HEDGE | 3 |
| 196 | 2026-06-18T15:33:49 | ESPORTSUSDT | short | 5m | trend_mode | TREND | TREND | 0.06281 | 0.0646 | +2.85% | 326.72 | -0.5848 | 0.0084 | 0.0042 | -0.5975 | -285.0 | LOSS | TIER_1_STOP_LOSS | 255 | v2h_69850a9abd5c33a71540e9ebd519f393 | v2_fsnap_11ae67d | mstate_bcb828a11fa7a | NO_HEDGE | 1 |
| 197 | 2026-06-18T15:35:56 | NIGHTUSDT | short | 1h | trend_mode | TREND | TREND | 0.029792 | 0.02982 | +0.09% | 6243.89 | -0.1750 | 0.0745 | 0.0372 | -0.2867 | -9.4 | LOSS | TIER_2_TRAILING_STOP | 2122 | v2h_0483e756830c29b66dc332d3699146a1 | v2_fsnap_dee02f2 | mstate_b55e9be935d79 | NO_HEDGE | 8 |
| 198 | 2026-06-18T15:36:52 | SOLUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 70.6 | 69.64 | -1.36% | 0.26 | 0.2479 | 0.0072 | 0.0036 | 0.2371 | 136.0 | WIN | TIER_2_TAKE_PROFIT | 1149 | v2h_9fbd8ed1909a8f7d790821a7cc32e5c5 | synth_fsid_v2h_9 | mstate_abd253d7d61e2 | NO_HEDGE | 1 |
| 199 | 2026-06-18T15:37:01 | BCHUSDT | short | 5m | trend_mode | TREND | TREND | 204.322 | 201.87 | -1.20% | 1.29 | 3.1661 | 0.1043 | 0.0521 | 3.0097 | 120.0 | WIN | TIER_2_TAKE_PROFIT | 3917 | v2h_4094282602aff76017313c4da9b5bd49 | v2_fsnap_3117010 | mstate_da10e459b72c0 | NO_HEDGE | 13 |
| 200 | 2026-06-18T15:38:10 | CHZUSDT | short | 5m | trend_mode | TREND | TREND | 0.0227942 | 0.02249 | -1.33% | 4668.07 | 1.4199 | 0.0420 | 0.0210 | 1.3569 | 133.4 | WIN | TIER_2_TAKE_PROFIT | 2001 | v2h_0d32b18df83ebf35a19e0ceff69a084e | v2_fsnap_4fbc18b | mstate_ba2389204660f | NO_HEDGE | 5 |
| 201 | 2026-06-18T15:38:10 | ENAUSDT | short | 4h | trend_mode | TREND | TREND | 0.093002 | 0.09187 | -1.22% | 622.10 | 0.7042 | 0.0229 | 0.0114 | 0.6699 | 121.7 | WIN | TIER_2_TAKE_PROFIT | 516 | v2h_077dee684c71b3c89b7af8bf0df72011 | v2_fsnap_42e0813 | mstate_95db075d567ff | NO_HEDGE | 2 |
| 202 | 2026-06-18T15:39:15 | AAVEUSDT | short | 4h | trend_mode | TREND | TREND | 73.0307 | 71.95 | -1.48% | 2.37 | 2.5573 | 0.0681 | 0.0341 | 2.4552 | 148.0 | WIN | TIER_2_TAKE_PROFIT | 2193 | v2h_42c214a91828d96be6d14338e477123d | v2_fsnap_416ee35 | mstate_f9a8dc6515607 | NO_HEDGE | 6 |
| 203 | 2026-06-18T15:39:15 | CRVUSDT | short | 1h | trend_mode | TREND | TREND | 0.22349 | 0.2193 | -1.87% | 660.43 | 2.7673 | 0.0579 | 0.0290 | 2.6804 | 187.5 | WIN | TIER_2_PROFIT_BANK | 1939 | v2h_4c0b3b5aaf30ea8d40412dff504f2d86 | v2_fsnap_08214aa | mstate_af6847fe93d8b | NO_HEDGE | 6 |
| 204 | 2026-06-18T15:39:15 | LINKUSDT | short | 4h | mean_reversion_ | RANGE | RANGE | 7.993 | 7.884 | -1.36% | 2.51 | 0.2732 | 0.0079 | 0.0040 | 0.2613 | 136.4 | WIN | TIER_2_TAKE_PROFIT | 1806 | v2h_f0e1318da2f9a15a8abf77a7353c0322 | null | mstate_3ad680aa49501 | NO_HEDGE | 1 |
| 205 | 2026-06-18T15:39:15 | DOGEUSDT | short | 1h | mean_reversion_ | RANGE | RANGE | 0.08363 | 0.08256 | -1.28% | 299.70 | 0.3207 | 0.0099 | 0.0049 | 0.3058 | 127.9 | WIN | TIER_2_TAKE_PROFIT | 1806 | v2h_c6ef4e09d819c2044f541888126c4c14 | null | mstate_7649c5b20c421 | NO_HEDGE | 1 |
| 206 | 2026-06-18T15:39:15 | AEROUSDT | short | 4h | trend_mode | TREND | TREND | 0.441695 | 0.4341 | -1.72% | 324.60 | 2.4653 | 0.0564 | 0.0282 | 2.3808 | 171.9 | WIN | TIER_2_TAKE_PROFIT | 1740 | v2h_89480c304dda91dab68658889eae150b | v2_fsnap_d6d503b | mstate_4d2bea22ab295 | NO_HEDGE | 6 |
| 207 | 2026-06-18T15:39:15 | BIOUSDT | short | 1m | trend_mode | TREND | TREND | 0.0353548 | 0.03458 | -2.19% | 2559.85 | 1.9834 | 0.0354 | 0.0177 | 1.9303 | 219.2 | WIN | TIER_2_PROFIT_BANK | 779 | v2h_7a5ee5c3f74b5e1fc6337ab8472e4f99 | v2_fsnap_c65a580 | mstate_f46145f43ad97 | NO_HEDGE | 3 |
| 208 | 2026-06-18T15:39:15 | RIVERUSDT | short | 1m | mean_reversion_ | RANGE | RANGE | 4.622 | 4.553 | -1.49% | 5.66 | 0.3908 | 0.0103 | 0.0052 | 0.3753 | 149.3 | WIN | TIER_2_TAKE_PROFIT | 454 | v2h_ec36eafa671d3a7180943ce258eec007 | null | mstate_3472119c5d979 | NO_HEDGE | 1 |
| 209 | 2026-06-18T15:39:15 | BSBUSDT | short | 5m | trend_mode | TREND | TREND | 0.57949 | 0.57159 | -1.36% | 30.77 | 0.2431 | 0.0070 | 0.0035 | 0.2325 | 136.3 | WIN | TIER_2_TAKE_PROFIT | 135 | v2h_507d8499af17937786b5c8043464217d | v2_fsnap_fe21201 | mstate_c1add7330dcba | NO_HEDGE | 1 |
| 210 | 2026-06-18T15:41:22 | ATOMUSDT | short | 4h | trend_mode | TREND | TREND | 1.82986 | 1.799 | -1.69% | 147.50 | 4.5525 | 0.1061 | 0.0531 | 4.3932 | 168.7 | WIN | TIER_2_TAKE_PROFIT | 4501 | v2h_15fcf82e76a82658411792508a1ef825 | v2_fsnap_6dadd91 | mstate_03c6ab7e2f4ee | NO_HEDGE | 12 |
| 211 | 2026-06-18T15:41:22 | APTUSDT | short | 5m | trend_mode | TREND | TREND | 0.635178 | 0.6268 | -1.32% | 142.48 | 1.1937 | 0.0357 | 0.0179 | 1.1401 | 131.9 | WIN | TIER_2_TAKE_PROFIT | 906 | v2h_130400d4459c2e72dc5ebd357557e535 | v2_fsnap_e3c0875 | mstate_8fd937a34458c | NO_HEDGE | 3 |
| 212 | 2026-06-18T15:41:22 | AVAXUSDT | short | 5m | trend_mode | TREND | TREND | 6.36019 | 6.278 | -1.29% | 9.94 | 0.8166 | 0.0250 | 0.0125 | 0.7792 | 129.2 | WIN | TIER_2_TAKE_PROFIT | 906 | v2h_1947c7cb01695b37ae974b472db04863 | v2_fsnap_7f2c8ec | mstate_a4d19e6694cbb | NO_HEDGE | 2 |
| 213 | 2026-06-18T15:41:22 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0996271 | 0.0981 | -1.53% | 493.38 | 0.7534 | 0.0194 | 0.0097 | 0.7244 | 153.3 | WIN | TIER_2_TAKE_PROFIT | 454 | v2h_4810fd14c0de9dba841d7a19c2142f2c | v2_fsnap_d6b3229 | mstate_34bb7eb3d1aa8 | NO_HEDGE | 2 |
| 214 | 2026-06-18T15:41:22 | ARBUSDT | short | 1h | trend_mode | TREND | TREND | 0.08381 | 0.08262 | -1.42% | 288.52 | 0.3433 | 0.0095 | 0.0048 | 0.3290 | 142.0 | WIN | TIER_2_TAKE_PROFIT | 390 | v2h_09d9e84d914bcd6a5d67777f3f719119 | v2_fsnap_c26a5ca | mstate_df41a1704ea71 | NO_HEDGE | 1 |
| 215 | 2026-06-18T15:42:53 | BARDUSDT | short | 1m | mean_reversion_ | RANGE | RANGE | 0.1532 | 0.1509 | -1.50% | 80.94 | 0.1862 | 0.0049 | 0.0024 | 0.1788 | 150.1 | WIN | TIER_2_TAKE_PROFIT | 1061 | v2h_6d0083ec7357516d5648f366b2027222 | synth_fsid_v2h_6 | mstate_243f33bb916b3 | NO_HEDGE | 1 |
| 216 | 2026-06-18T15:42:53 | AUCTIONUSDT | short | 1h | mean_reversion_ | RANGE | RANGE | 3.747 | 3.683 | -1.71% | 3.31 | 0.2117 | 0.0049 | 0.0024 | 0.2044 | 170.8 | WIN | TIER_2_TAKE_PROFIT | 1061 | v2h_53ff9d1a48ce3269d2a131b9be99d9e1 | synth_fsid_v2h_5 | mstate_46b212e403aa9 | NO_HEDGE | 1 |
| 217 | 2026-06-18T15:42:53 | 1000FLOKIUSDT | short | 5m | mean_reversion_ | RANGE | RANGE | 0.02637 | 0.02601 | -1.37% | 1096.87 | 0.3949 | 0.0114 | 0.0057 | 0.3778 | 136.5 | WIN | TIER_2_TAKE_PROFIT | 155 | v2h_cc69354156b49ce277d444f43a2cdc46 | synth_fsid_v2h_c | mstate_4900b0a2ed603 | NO_HEDGE | 1 |
| 218 | 2026-06-18T15:43:29 | UNIUSDT | short | 5m | mean_reversion_ | RANGE | RANGE | 3.077 | 3.079 | +0.06% | 14.86 | -0.0297 | 0.0183 | 0.0092 | -0.0572 | -6.5 | LOSS | TIER_2_TRAILING_STOP | 191 | v2h_b7f095523f5c3c0c9bb9fd08dde664c6 | null | mstate_c1e6157f67ed6 | NO_HEDGE | 1 |
| 219 | 2026-06-18T15:44:32 | TAOUSDT | short | 15m | trend_mode | TREND | TREND | 239.13 | 236.17 | -1.24% | 1.99 | 5.9019 | 0.1883 | 0.0942 | 5.6194 | 123.8 | WIN | TIER_2_TAKE_PROFIT | 5006 | v2h_1302aab206760db964130671970dade4 | v2_fsnap_c7ddf69 | mstate_98657db6c3a16 | NO_HEDGE | 17 |
| 220 | 2026-06-18T15:47:54 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.74604 | 1.769 | +1.32% | 30.00 | -0.6888 | 0.0212 | 0.0106 | -0.7207 | -131.5 | LOSS | TIER_1_STOP_LOSS | 655 | v2h_25cfd8150292eb9eea4a78cd4a88aa84 | v2_fsnap_8dbe266 | mstate_5bd94e9e41faa | NO_HEDGE | 2 |
| 221 | 2026-06-18T15:47:54 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0600872 | 0.061 | +1.52% | 917.09 | -0.8371 | 0.0224 | 0.0112 | -0.8706 | -151.9 | LOSS | TIER_1_STOP_LOSS | 520 | v2h_032739eba87dec691096578d6e838fb7 | v2_fsnap_8bcc636 | mstate_838e96d14ee77 | NO_HEDGE | 2 |
| 222 | 2026-06-18T15:47:54 | AVNTUSDT | short | 4h | mean_reversion_ | RANGE | RANGE | 0.1061 | 0.1047 | -1.32% | 272.19 | 0.3811 | 0.0114 | 0.0057 | 0.3640 | 132.0 | WIN | TIER_2_TAKE_PROFIT | 456 | v2h_a6faf038a0b14f152e7eaa91c0bb00a2 | null | mstate_938700053b764 | NO_HEDGE | 1 |
| 223 | 2026-06-18T15:47:54 | FARTCOINUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 0.1253 | 0.1234 | -1.52% | 230.87 | 0.4386 | 0.0114 | 0.0057 | 0.4216 | 151.6 | WIN | TIER_2_TAKE_PROFIT | 456 | v2h_c94f75de367c0dd0b46011cc97967786 | null | mstate_a1341cfa0341f | NO_HEDGE | 1 |
| 224 | 2026-06-18T15:48:37 | ZECUSDT | short | 1m | trend_mode | TREND | TREND | 466.119 | 457.04 | -1.95% | 0.20 | 1.8567 | 0.0374 | 0.0187 | 1.8006 | 194.8 | WIN | TIER_2_PROFIT_BANK | 1468 | v2h_8ec2ead4776c00be87fe061a1620ed07 | v2_fsnap_3078610 | mstate_b2e8ca42fa1ab | NO_HEDGE | 4 |
| 225 | 2026-06-18T15:52:11 | RAVEUSDT | short | 5m | mean_reversion_ | RANGE | RANGE | 0.274 | 0.2707 | -1.20% | 111.26 | 0.3671 | 0.0120 | 0.0060 | 0.3491 | 120.4 | WIN | TIER_2_TAKE_PROFIT | 713 | v2h_ac29a8184952585a6cecc1b7e5df48d7 | null | mstate_705d16a303531 | NO_HEDGE | 1 |
| 226 | 2026-06-18T15:52:11 | BSBUSDT | short | 1m | trend_mode | TREND | TREND | 0.572218 | 0.57604 | +0.67% | 100.83 | -0.3854 | 0.0232 | 0.0116 | -0.4202 | -66.8 | LOSS | TIER_2_TRAILING_STOP | 64 | v2h_b64f5757fdfbb535a55abd826b3abc7a | v2_fsnap_cc28227 | mstate_55edaac5f9fd2 | NO_HEDGE | 2 |
| 227 | 2026-06-18T15:53:55 | ETHUSDT | short | 1h | mean_reversion_ | RANGE | RANGE | 1712.72 | 1686.69 | -1.52% | 0.03 | 0.7498 | 0.0194 | 0.0097 | 0.7207 | 152.0 | WIN | TIER_2_TAKE_PROFIT | 817 | v2h_0dda9a6d15d1fe96d81d9a570f470cb0 | synth_fsid_v2h_0 | mstate_105792b7ae258 | NO_HEDGE | 1 |
| 228 | 2026-06-18T15:53:55 | PENGUUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 0.00661 | 0.006523 | -1.32% | 5856.17 | 0.5095 | 0.0153 | 0.0076 | 0.4866 | 131.6 | WIN | TIER_2_TAKE_PROFIT | 817 | v2h_0510647847fc03239192367974a964b8 | synth_fsid_v2h_0 | mstate_50dc5e88ea083 | NO_HEDGE | 1 |
| 229 | 2026-06-18T15:53:55 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.77149 | 1.747 | -1.38% | 32.57 | 0.7977 | 0.0228 | 0.0114 | 0.7636 | 138.3 | WIN | TIER_2_TAKE_PROFIT | 168 | v2h_9bb952b46cfd969860029067b4215a5d | v2_fsnap_3ad1eff | mstate_e42569bdf122b | NO_HEDGE | 2 |
| 230 | 2026-06-18T15:54:20 | HBARUSDT | short | 5m | trend_mode | TREND | TREND | 0.0797684 | 0.07877 | -1.25% | 3906.59 | 3.9002 | 0.1231 | 0.0615 | 3.7156 | 125.2 | WIN | TIER_2_TAKE_PROFIT | 4313 | v2h_25484cc41fa5d13e1f227d346cf57267 | v2_fsnap_c04d845 | mstate_65ae96013a455 | NO_HEDGE | 12 |
| 231 | 2026-06-18T15:56:32 | APTUSDT | short | 5m | trend_mode | TREND | TREND | 0.625955 | 0.6243 | -0.26% | 127.17 | 0.2105 | 0.0318 | 0.0159 | 0.1629 | 26.4 | WIN | TIER_2_TRAILING_STOP | 784 | v2h_1c7499946e3cb51d0cfb2a3f78639a1c | v2_fsnap_b7ada35 | mstate_3e61c54cbbf8e | NO_HEDGE | 2 |
| 232 | 2026-06-18T15:58:39 | ADAUSDT | short | 1m | trend_mode | TREND | TREND | 0.161858 | 0.1598 | -1.27% | 1150.70 | 2.3679 | 0.0736 | 0.0368 | 2.2576 | 127.1 | WIN | TIER_2_TAKE_PROFIT | 1943 | v2h_697127ad5e0496cac723cc25168f5ddf | v2_fsnap_913c88f | mstate_704b2a8c476f9 | NO_HEDGE | 5 |
| 233 | 2026-06-18T15:58:39 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.38356 | 0.38316 | -0.10% | 239.84 | 0.0959 | 0.0368 | 0.0184 | 0.0408 | 10.4 | WIN | TIER_2_TRAILING_STOP | 1491 | v2h_0627cb8b48256fca866737302e060f2e | v2_fsnap_3214737 | mstate_a063ec1448535 | NO_HEDGE | 3 |
| 234 | 2026-06-18T15:58:39 | AEROUSDT | short | 5m | trend_mode | TREND | TREND | 0.430892 | 0.4249 | -1.39% | 248.11 | 1.4867 | 0.0422 | 0.0211 | 1.4234 | 139.1 | WIN | TIER_2_TAKE_PROFIT | 911 | v2h_0c8ca827ac6d414aae075cb4cb211676 | v2_fsnap_19a460e | mstate_a21ebae8e50a0 | NO_HEDGE | 3 |
| 235 | 2026-06-18T15:58:39 | ARBUSDT | short | 15m | trend_mode | TREND | TREND | 0.0822806 | 0.08128 | -1.22% | 967.44 | 0.9680 | 0.0315 | 0.0157 | 0.9209 | 121.6 | WIN | TIER_2_TAKE_PROFIT | 911 | v2h_3307740733970bb6142c88b3d653d4a8 | v2_fsnap_0be55b4 | mstate_dbaa3f16c35a5 | NO_HEDGE | 2 |
| 236 | 2026-06-18T15:58:39 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.06085 | 0.06136 | +0.84% | 324.73 | -0.1656 | 0.0080 | 0.0040 | -0.1776 | -83.8 | LOSS | TIER_1_STOP_LOSS | 325 | v2h_33127b151885be01a159cb73ccce1280 | v2_fsnap_3aebc22 | mstate_ede06c5625bd2 | NO_HEDGE | 1 |
| 237 | 2026-06-18T15:58:39 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.02742 | 0.02777 | +1.28% | 903.16 | -0.3161 | 0.0100 | 0.0050 | -0.3312 | -127.6 | LOSS | TIER_1_STOP_LOSS | 261 | v2h_4fc303ee6706ecfed26b202fa7bc3131 | v2_fsnap_85b9400 | mstate_425aaedb81467 | NO_HEDGE | 1 |
| 238 | 2026-06-18T16:00:47 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.23519 | 0.23065 | -1.93% | 272.94 | 1.2390 | 0.0252 | 0.0126 | 1.2013 | 193.0 | WIN | TIER_2_PROFIT_BANK | 389 | v2h_559bbf4fa9da1eb34e2bd1fc2407d0b0 | v2_fsnap_91b1027 | mstate_7902841d65244 | NO_HEDGE | 2 |
| 239 | 2026-06-18T16:02:58 | DASHUSDT | short | 5m | trend_mode | TREND | TREND | 34.8876 | 34.85 | -0.11% | 4.21 | 0.1580 | 0.0586 | 0.0293 | 0.0700 | 10.8 | WIN | TIER_2_TRAILING_STOP | 1489 | v2h_55c392b9338af25260f357a278da63af | v2_fsnap_cca7e7c | mstate_caaa61c9584d5 | NO_HEDGE | 5 |
| 240 | 2026-06-18T16:02:58 | FETUSDT | short | 1m | trend_mode | TREND | TREND | 0.190759 | 0.1908 | +0.02% | 779.87 | -0.0318 | 0.0595 | 0.0298 | -0.1211 | -2.1 | LOSS | TIER_2_TRAILING_STOP | 1424 | v2h_18675c39b60561c0c99abbe02f651c6e | v2_fsnap_c610952 | mstate_a3cbeabc58911 | NO_HEDGE | 5 |
| 241 | 2026-06-18T16:02:58 | ALGOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0979857 | 0.0984 | +0.42% | 1277.98 | -0.5294 | 0.0503 | 0.0252 | -0.6049 | -42.3 | LOSS | TIER_2_TRAILING_STOP | 1170 | v2h_05a9efcfe34ab5461b8b8425cbc010a1 | v2_fsnap_5be1cd0 | mstate_fe5b2be8c6e9d | NO_HEDGE | 4 |
| 242 | 2026-06-18T16:02:58 | ATOMUSDT | short | 5m | trend_mode | TREND | TREND | 1.79412 | 1.797 | +0.16% | 66.21 | -0.1907 | 0.0476 | 0.0238 | -0.2621 | -16.1 | LOSS | TIER_2_TRAILING_STOP | 1170 | v2h_1ea4c74894c26d6dc6564eafab5bb14b | v2_fsnap_6d29c13 | mstate_779dc9f4aef7a | NO_HEDGE | 4 |
| 243 | 2026-06-18T16:02:58 | BCHUSDT | short | 1h | trend_mode | TREND | TREND | 194.673 | 195.89 | +0.63% | 0.50 | -0.6123 | 0.0394 | 0.0197 | -0.6714 | -62.5 | LOSS | TIER_2_TRAILING_STOP | 1043 | v2h_64186d61b6041c7bb1c0464bbd919e4d | v2_fsnap_5cbd607 | mstate_b7f2a5ed14ca3 | NO_HEDGE | 3 |
| 244 | 2026-06-18T16:02:58 | CRVUSDT | short | 5m | trend_mode | TREND | TREND | 0.21693 | 0.2181 | +0.54% | 484.45 | -0.5668 | 0.0423 | 0.0211 | -0.6302 | -53.9 | LOSS | TIER_2_TRAILING_STOP | 711 | v2h_3057f140c72f59b60c7cf06180b01500 | v2_fsnap_616f0f7 | mstate_f5e22162639c5 | NO_HEDGE | 3 |
| 245 | 2026-06-18T16:02:58 | ENAUSDT | short | 1h | trend_mode | TREND | TREND | 0.0903382 | 0.09111 | +0.85% | 690.32 | -0.5328 | 0.0252 | 0.0126 | -0.5705 | -85.4 | LOSS | TIER_1_STOP_LOSS | 584 | v2h_074b63843901de54c578a1e44d77850d | v2_fsnap_f4b2b55 | mstate_65cc5d8af432c | NO_HEDGE | 2 |
| 246 | 2026-06-18T16:02:58 | FILUSDT | short | 5m | trend_mode | TREND | TREND | 0.756808 | 0.763 | +0.82% | 92.87 | -0.5751 | 0.0283 | 0.0142 | -0.6176 | -81.8 | LOSS | TIER_1_STOP_LOSS | 520 | v2h_1836f126bb9b00a7daea665f01074b33 | v2_fsnap_21afea3 | mstate_f0f16e9cfc090 | NO_HEDGE | 2 |
| 247 | 2026-06-18T16:02:58 | HYPEUSDT | short | 1m | trend_mode | TREND | TREND | 67.7159 | 68.033 | +0.47% | 1.09 | -0.3470 | 0.0298 | 0.0149 | -0.3916 | -46.8 | LOSS | TIER_2_TRAILING_STOP | 451 | v2h_7f238edbc37c821687d9080257e16758 | v2_fsnap_5dc9a4c | mstate_36711c37967b8 | NO_HEDGE | 2 |
| 248 | 2026-06-18T16:02:58 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.736 | 1.783 | +2.71% | 19.00 | -0.8929 | 0.0135 | 0.0068 | -0.9132 | -270.7 | LOSS | TIER_1_STOP_LOSS | 196 | v2h_1da262b3e13fce4a9a61e0e99d678257 | v2_fsnap_b0fb736 | mstate_ac39729fb4007 | NO_HEDGE | 1 |
| 249 | 2026-06-18T16:04:02 | XRPUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 1.1468 | 1.1413 | -0.48% | 28.99 | 0.1594 | 0.0132 | 0.0066 | 0.1396 | 48.0 | WIN | TIER_2_TRAILING_STOP | 1941 | v2h_06a39d9028f27f5ed04aa50140004b44 | null | mstate_fc10a21ccfa2d | NO_HEDGE | 1 |
| 250 | 2026-06-18T16:04:07 | AEROUSDT | short | 15m | trend_mode | TREND | TREND | 0.4249 | 0.4305 | +1.32% | 89.96 | -0.5038 | 0.0155 | 0.0077 | -0.5270 | -131.8 | LOSS | TIER_1_STOP_LOSS | 265 | v2h_2a201382d032ffb48129e6a030e868ec | v2_fsnap_1691691 | mstate_7da1abdfad6b3 | NO_HEDGE | 1 |
| 251 | 2026-06-18T16:05:06 | DOTUSDT | short | 1h | trend_mode | TREND | TREND | 0.950855 | 0.95 | -0.09% | 223.91 | 0.1914 | 0.0851 | 0.0425 | 0.0637 | 9.0 | WIN | TIER_2_TRAILING_STOP | 2198 | v2h_3b99513000450599ee9d16414946847c | v2_fsnap_c2e5ca6 | mstate_78a15ff3469bb | NO_HEDGE | 6 |
| 252 | 2026-06-18T16:05:06 | AVAXUSDT | short | 1h | trend_mode | TREND | TREND | 6.24922 | 6.274 | +0.40% | 16.58 | -0.4110 | 0.0416 | 0.0208 | -0.4734 | -39.7 | LOSS | TIER_2_TRAILING_STOP | 1234 | v2h_860b22be25a5bd110ef0bdc87838550d | v2_fsnap_9f40fd2 | mstate_05e37d0763ec8 | NO_HEDGE | 3 |
| 253 | 2026-06-18T16:05:06 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0341084 | 0.03478 | +1.97% | 3081.12 | -2.0691 | 0.0429 | 0.0214 | -2.1334 | -196.9 | LOSS | TIER_1_STOP_LOSS | 839 | v2h_d27b7c9d8650391eb89e1df0e41ca35e | v2_fsnap_39929d1 | mstate_5c3abbd5002ff | NO_HEDGE | 3 |
| 254 | 2026-06-18T16:05:06 | CHZUSDT | short | 4h | trend_mode | TREND | TREND | 0.0219458 | 0.02205 | +0.47% | 3058.35 | -0.3186 | 0.0270 | 0.0135 | -0.3591 | -47.5 | LOSS | TIER_2_TRAILING_STOP | 839 | v2h_69dabe833f0f7c3030d46aa9616edd2e | v2_fsnap_e15080a | mstate_1f1a03ba1eced | NO_HEDGE | 2 |
| 255 | 2026-06-18T16:06:10 | LTCUSDT | short | 1m | mean_reversion_ | RANGE | RANGE | 43.41 | 43.28 | -0.30% | 0.97 | 0.1263 | 0.0168 | 0.0084 | 0.1011 | 29.9 | WIN | TIER_2_TRAILING_STOP | 1552 | v2h_9f028b3aee96db9c3735926fdb9169af | null | mstate_9a21b5a478b0d | NO_HEDGE | 1 |
| 256 | 2026-06-18T16:06:10 | ADAUSDT | short | 15m | trend_mode | TREND | TREND | 0.1598 | 0.1611 | +0.81% | 261.89 | -0.3405 | 0.0169 | 0.0084 | -0.3658 | -81.4 | LOSS | TIER_1_STOP_LOSS | 388 | v2h_010c9fb9c6673c77b198d4f5dc3ba299 | v2_fsnap_7b69e5f | mstate_1cc70b26cbbcc | NO_HEDGE | 1 |
| 257 | 2026-06-18T16:06:10 | APTUSDT | short | 5m | trend_mode | TREND | TREND | 0.6199 | 0.6262 | +1.02% | 61.66 | -0.3884 | 0.0154 | 0.0077 | -0.4116 | -101.6 | LOSS | TIER_1_STOP_LOSS | 388 | v2h_1018f59b807b3df698ec6a0b7513f8b9 | v2_fsnap_40f3281 | mstate_61d414fb5932f | NO_HEDGE | 1 |
| 258 | 2026-06-18T16:06:10 | ARBUSDT | short | 1h | trend_mode | TREND | TREND | 0.08128 | 0.08208 | +0.98% | 470.25 | -0.3762 | 0.0154 | 0.0077 | -0.3994 | -98.4 | LOSS | TIER_1_STOP_LOSS | 388 | v2h_09147308a23a2045204272cdca640cb2 | v2_fsnap_b2b111e | mstate_f5c950dcc012d | NO_HEDGE | 1 |
| 259 | 2026-06-18T16:07:14 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.06085 | 0.06177 | +1.51% | 323.65 | -0.2978 | 0.0080 | 0.0040 | -0.3098 | -151.2 | LOSS | TIER_1_STOP_LOSS | 324 | v2h_19da583c97ca659e01e6dbc91173125a | v2_fsnap_2f8a96d | mstate_b6d6a59105189 | NO_HEDGE | 1 |
| 260 | 2026-06-18T16:07:14 | ICPUSDT | short | 4h | trend_mode | TREND | TREND | 2.198 | 2.221 | +1.05% | 18.31 | -0.4212 | 0.0163 | 0.0081 | -0.4456 | -104.6 | LOSS | TIER_1_STOP_LOSS | 192 | v2h_0bbc2b297f0b76840c9dcdea77126f47 | v2_fsnap_ec66735 | mstate_74b6e58df7e52 | NO_HEDGE | 1 |
| 261 | 2026-06-18T16:08:18 | BANKUSDT | short | 4h | trend_mode | TREND | TREND | 0.03733 | 0.03688 | -1.21% | 1069.51 | 0.4813 | 0.0158 | 0.0079 | 0.4576 | 120.5 | WIN | TIER_2_TAKE_PROFIT | 5983 | v2h_abd85066cc67e4a9029a28809d59736c | null | mstate_bc92b572287db | NO_HEDGE | 1 |
| 262 | 2026-06-18T16:09:23 | BNBUSDT | short | 5m | trend_mode | TREND | TREND | 578.452 | 577.26 | -0.21% | 0.43 | 0.5151 | 0.0997 | 0.0499 | 0.3654 | 20.6 | WIN | TIER_2_TRAILING_STOP | 2587 | v2h_13431a0d44cc244d15197feabc173c08 | v2_fsnap_c72dfb6 | mstate_1be636899ca71 | NO_HEDGE | 7 |
| 263 | 2026-06-18T16:09:23 | BSBUSDT | short | 4h | trend_mode | TREND | TREND | 0.567619 | 0.57245 | +0.85% | 121.26 | -0.5858 | 0.0278 | 0.0139 | -0.6274 | -85.1 | LOSS | TIER_1_STOP_LOSS | 581 | v2h_180359e707f6b1af513f8d4a4989b040 | v2_fsnap_ba1ce23 | mstate_9f2051d502f87 | NO_HEDGE | 2 |
| 264 | 2026-06-18T16:09:23 | HOMEUSDT | short | 1h | trend_mode | TREND | TREND | 0.0279668 | 0.02808 | +0.40% | 2670.18 | -0.3022 | 0.0300 | 0.0150 | -0.3472 | -40.5 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_1f3fdd75548b6db584c47278da963033 | v2_fsnap_9bb7d01 | mstate_547f2d061e1e5 | NO_HEDGE | 2 |
| 265 | 2026-06-18T16:09:23 | INJUSDT | short | 4h | trend_mode | TREND | TREND | 5.12667 | 5.146 | +0.38% | 15.28 | -0.2952 | 0.0314 | 0.0157 | -0.3424 | -37.7 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_0e646cc21bf335b6fe1a1a041c83484e | v2_fsnap_30f4290 | mstate_f367bd473f1ee | NO_HEDGE | 2 |
| 266 | 2026-06-18T16:09:23 | JTOUSDT | short | 1h | trend_mode | TREND | TREND | 0.709489 | 0.7109 | +0.20% | 110.38 | -0.1558 | 0.0314 | 0.0157 | -0.2029 | -19.9 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_1a631eac9e9828a577b5e4049ecf9c42 | v2_fsnap_ab3484b | mstate_885fa3e6ec2d0 | NO_HEDGE | 2 |
| 267 | 2026-06-18T16:11:21 | MEGAUSDT | short | 1h | trend_mode | TREND | TREND | 0.0632948 | 0.06389 | +0.94% | 1237.24 | -0.7364 | 0.0316 | 0.0158 | -0.7838 | -94.0 | LOSS | TIER_1_STOP_LOSS | 439 | v2h_4a09e1848456685c4a3d2af585fe8ea8 | v2_fsnap_324256c | mstate_c5e677e2cbec7 | NO_HEDGE | 2 |
| 268 | 2026-06-18T16:12:37 | AAVEUSDT | short | 4h | trend_mode | TREND | TREND | 71.3321 | 71.65 | +0.45% | 2.45 | -0.7777 | 0.0701 | 0.0351 | -0.8828 | -44.6 | LOSS | TIER_2_TRAILING_STOP | 1749 | v2h_15ab039e8050a09b7fdc08e7d17cfe24 | v2_fsnap_3b476ad | mstate_38562f30c438d | NO_HEDGE | 4 |
| 269 | 2026-06-18T16:12:37 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.814 | 1.839 | +1.38% | 13.84 | -0.3460 | 0.0102 | 0.0051 | -0.3613 | -137.8 | LOSS | TIER_1_STOP_LOSS | 66 | v2h_0df96e3f74d98ea3616134910abd3bdc | v2_fsnap_49b901b | mstate_1304829c990cd | NO_HEDGE | 1 |
| 270 | 2026-06-18T16:14:50 | 1000SHIBUSDT | short | 1h | trend_mode | TREND | TREND | 0.00467891 | 0.00468 | +0.02% | 19738.27 | -0.0215 | 0.0370 | 0.0185 | -0.0769 | -2.3 | LOSS | TIER_2_TRAILING_STOP | 1945 | v2h_4db41c3b2bca3f6eb30dbea602cd1ad9 | v2_fsnap_d4901ea | mstate_4260efc0f6a51 | NO_HEDGE | 2 |
| 271 | 2026-06-18T16:19:05 | LABUSDT | short | 4h | trend_mode | TREND | TREND | 16.032 | 16.046 | +0.09% | 6.59 | -0.0923 | 0.0423 | 0.0212 | -0.1558 | -8.7 | LOSS | TIER_2_TRAILING_STOP | 903 | v2h_1cbeea714f389a11a23b071706680b8e | v2_fsnap_95be4aa | mstate_d96bfd3b92809 | NO_HEDGE | 3 |
| 272 | 2026-06-18T16:19:05 | BIOUSDT | short | 15m | trend_mode | TREND | TREND | 0.0347465 | 0.03487 | +0.36% | 1845.95 | -0.2280 | 0.0257 | 0.0129 | -0.2666 | -35.6 | LOSS | TIER_2_TRAILING_STOP | 321 | v2h_4045ad0da3ee657b8b1a76e4d7777281 | v2_fsnap_38f229a | mstate_20f7f987bf198 | NO_HEDGE | 2 |
| 273 | 2026-06-18T16:21:04 | AEROUSDT | short | 15m | trend_mode | TREND | TREND | 0.431886 | 0.4361 | +0.98% | 171.60 | -0.7231 | 0.0299 | 0.0150 | -0.7680 | -97.6 | LOSS | TIER_1_STOP_LOSS | 702 | v2h_260b71d708c99acdd839b518dd2cad53 | v2_fsnap_16fe0a7 | mstate_a34cddcdf46cc | NO_HEDGE | 2 |
| 274 | 2026-06-18T16:21:13 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.382941 | 0.38374 | +0.21% | 240.11 | -0.1919 | 0.0369 | 0.0184 | -0.2471 | -20.9 | LOSS | TIER_2_TRAILING_STOP | 1291 | v2h_0f1d0f62e30caab7488b26c2a5a5ac25 | v2_fsnap_1b2545d | mstate_10a15c4ba3bac | NO_HEDGE | 3 |
| 275 | 2026-06-18T16:21:13 | LITUSDT | short | 15m | trend_mode | TREND | TREND | 1.58218 | 1.5919 | +0.61% | 70.08 | -0.6812 | 0.0446 | 0.0223 | -0.7481 | -61.4 | LOSS | TIER_2_TRAILING_STOP | 1031 | v2h_1a3cf6ac8af6ed0430f1832ebc92e3fd | v2_fsnap_a5f4876 | mstate_42764719f82c4 | NO_HEDGE | 3 |
| 276 | 2026-06-18T16:21:13 | APTUSDT | short | 15m | trend_mode | TREND | TREND | 0.626043 | 0.628 | +0.31% | 118.38 | -0.2317 | 0.0297 | 0.0149 | -0.2763 | -31.3 | LOSS | TIER_2_TRAILING_STOP | 711 | v2h_04233251ba90988736c2c934cbf76b88 | v2_fsnap_a40b952 | mstate_e1134fd04b938 | NO_HEDGE | 2 |
| 277 | 2026-06-18T16:23:28 | MITOUSDT | short | 15m | trend_mode | TREND | TREND | 0.0255044 | 0.0255 | -0.02% | 3751.04 | 0.0163 | 0.0383 | 0.0191 | -0.0411 | 1.7 | LOSS | TIER_2_TRAILING_STOP | 1166 | v2h_01ad29215c090f9eb6ff6ace010f135d | v2_fsnap_289ba51 | mstate_9c589954ec1fc | NO_HEDGE | 3 |
| 278 | 2026-06-18T16:23:28 | NEARUSDT | short | 4h | trend_mode | TREND | TREND | 2.20209 | 2.213 | +0.50% | 52.71 | -0.5751 | 0.0467 | 0.0233 | -0.6450 | -49.5 | LOSS | TIER_2_TRAILING_STOP | 1102 | v2h_99dd541664275abfbb1c4858e897b7bf | v2_fsnap_6966f0f | mstate_c03bb3f68d52c | NO_HEDGE | 3 |
| 279 | 2026-06-18T16:23:28 | BANKUSDT | short | 5m | trend_mode | TREND | TREND | 0.036993 | 0.03727 | +0.75% | 1816.23 | -0.5031 | 0.0271 | 0.0135 | -0.5437 | -74.9 | LOSS | TIER_2_TRAILING_STOP | 781 | v2h_6ef78335d935fc47077edf0a65d0b68a | v2_fsnap_675fa95 | mstate_7c4f4d6c723ef | NO_HEDGE | 2 |
| 280 | 2026-06-18T16:25:26 | ALGOUSDT | short | 1m | trend_mode | TREND | TREND | 0.098456 | 0.0995 | +1.06% | 649.52 | -0.6781 | 0.0259 | 0.0129 | -0.7168 | -106.0 | LOSS | TIER_1_STOP_LOSS | 964 | v2h_22eb656bc7019e496c317cddf9efd2a3 | v2_fsnap_cbb392d | mstate_951ea0117c879 | NO_HEDGE | 2 |
| 281 | 2026-06-18T16:25:26 | ASTERUSDT | short | 5m | trend_mode | TREND | TREND | 0.6352 | 0.6403 | +0.80% | 40.53 | -0.2067 | 0.0104 | 0.0052 | -0.2223 | -80.3 | LOSS | TIER_1_STOP_LOSS | 253 | v2h_12b7aefe467369b33d3f6c5292d3d356 | v2_fsnap_d377c57 | mstate_62a1658eb6871 | NO_HEDGE | 1 |
| 282 | 2026-06-18T16:25:37 | NIGHTUSDT | short | 1h | trend_mode | TREND | TREND | 0.029611 | 0.02976 | +0.50% | 3413.93 | -0.5088 | 0.0406 | 0.0203 | -0.5697 | -50.3 | LOSS | TIER_2_TRAILING_STOP | 1231 | v2h_0c56d72bcdb273074adca5041f26684a | v2_fsnap_782713f | mstate_4cf49ed0d7af6 | NO_HEDGE | 3 |
| 283 | 2026-06-18T16:25:37 | 1000BONKUSDT | short | 5m | trend_mode | TREND | TREND | 0.00444134 | 0.004467 | +0.58% | 20158.16 | -0.5174 | 0.0360 | 0.0180 | -0.5714 | -57.8 | LOSS | TIER_2_TRAILING_STOP | 975 | v2h_1ed9a3f12caf264e334dec37a346a94b | v2_fsnap_ab463e5 | mstate_63c746a175b12 | NO_HEDGE | 3 |
| 284 | 2026-06-18T16:25:37 | 1000FLOKIUSDT | short | 5m | trend_mode | TREND | TREND | 0.0258888 | 0.02601 | +0.47% | 2729.90 | -0.3309 | 0.0284 | 0.0142 | -0.3735 | -46.8 | LOSS | TIER_2_TRAILING_STOP | 975 | v2h_e29eed79f3901cac7dfe7c65bba13c69 | v2_fsnap_467d6d7 | mstate_7856cb4b13b00 | NO_HEDGE | 2 |
| 285 | 2026-06-18T16:25:37 | CHZUSDT | short | 4h | trend_mode | TREND | TREND | 0.0220475 | 0.02213 | +0.37% | 2510.19 | -0.2071 | 0.0222 | 0.0111 | -0.2404 | -37.4 | LOSS | TIER_2_TRAILING_STOP | 713 | v2h_024c467a42e0b15cdb87156acaa25235 | v2_fsnap_419b02d | mstate_6e64cdaa0f657 | NO_HEDGE | 2 |
| 286 | 2026-06-18T16:25:37 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.853 | 1.865 | +0.65% | 10.73 | -0.1287 | 0.0080 | 0.0040 | -0.1407 | -64.8 | LOSS | TIER_2_TRAILING_STOP | 200 | v2h_3abbebe1722575e23e91f911f7353484 | v2_fsnap_3f8c166 | mstate_7db90b0854a87 | NO_HEDGE | 1 |
| 287 | 2026-06-18T16:27:47 | BARDUSDT | short | 5m | trend_mode | TREND | TREND | 0.150044 | 0.151 | +0.64% | 407.66 | -0.3898 | 0.0246 | 0.0123 | -0.4267 | -63.7 | LOSS | TIER_2_TRAILING_STOP | 1040 | v2h_760b9a18a3de448e0083dfd0bb7460b1 | v2_fsnap_f13a7b6 | mstate_ee4cd148b8925 | NO_HEDGE | 2 |
| 288 | 2026-06-18T16:27:47 | BCHUSDT | short | 1h | trend_mode | TREND | TREND | 195.861 | 196.5 | +0.33% | 0.28 | -0.1764 | 0.0217 | 0.0109 | -0.2089 | -32.6 | LOSS | TIER_2_TRAILING_STOP | 1040 | v2h_7767fab37ffc7aa86c7c4237848939b4 | v2_fsnap_28de099 | mstate_efa556b739a50 | NO_HEDGE | 2 |
| 289 | 2026-06-18T16:27:47 | AAVEUSDT | short | 1h | trend_mode | TREND | TREND | 71.1 | 71.67 | +0.80% | 0.31 | -0.1739 | 0.0087 | 0.0044 | -0.1870 | -80.2 | LOSS | TIER_1_STOP_LOSS | 459 | v2h_159d226d61fdad00d3f74dbafe79f101 | v2_fsnap_6b8639d | mstate_119a9a6e47317 | NO_HEDGE | 1 |
| 290 | 2026-06-18T16:32:18 | BSBUSDT | short | 15m | trend_mode | TREND | TREND | 0.566026 | 0.5773 | +1.99% | 86.19 | -0.9716 | 0.0199 | 0.0100 | -1.0015 | -199.2 | LOSS | TIER_1_STOP_LOSS | 601 | v2h_02bfb7fa06bf79f677dea256acdf95a9 | v2_fsnap_f740962 | mstate_485342461e19c | NO_HEDGE | 2 |
| 291 | 2026-06-18T16:32:18 | BEATUSDT | short | 15m | trend_mode | TREND | TREND | 1.813 | 1.786 | -1.49% | 15.94 | 0.4305 | 0.0114 | 0.0057 | 0.4134 | 148.9 | WIN | TIER_2_TAKE_PROFIT | 207 | v2h_36a89a5088f21cff203187401a548748 | v2_fsnap_9318c5b | mstate_45d2dace065b8 | NO_HEDGE | 1 |
| 292 | 2026-06-18T16:35:39 | WIFUSDT | short | 5m | mean_reversion_ | RANGE | RANGE | 0.160984 | 0.161 | +0.01% | 339.31 | -0.0054 | 0.0219 | 0.0109 | -0.0382 | -1.0 | LOSS | TIER_2_TRAILING_STOP | 1186 | v2h_d9d2ccc96321beee8a09fba42b889212 | null | mstate_74c2f8d17db83 | NO_HEDGE | 2 |
| 293 | 2026-06-18T16:35:39 | PIPPINUSDT | short | 5m | mean_reversion_ | RANGE | RANGE | 0.01613 | 0.01628 | +0.93% | 1283.31 | -0.1925 | 0.0084 | 0.0042 | -0.2050 | -93.0 | LOSS | TIER_1_STOP_LOSS | 667 | v2h_dc190520a0a4ffe093efb05ee4e13efb | null | mstate_9dcd7456304a5 | NO_HEDGE | 1 |
| 294 | 2026-06-18T16:35:39 | AEROUSDT | short | 4h | trend_mode | TREND | TREND | 0.4372 | 0.4352 | -0.46% | 76.63 | 0.1533 | 0.0133 | 0.0067 | 0.1333 | 45.7 | WIN | TIER_2_TRAILING_STOP | 408 | v2h_3d8a715f8b329be2f59b74e0d564a040 | v2_fsnap_1c977cc | mstate_14b242651c846 | NO_HEDGE | 1 |
| 295 | 2026-06-18T16:35:39 | APTUSDT | short | 5m | trend_mode | TREND | TREND | 0.6287 | 0.6277 | -0.16% | 53.29 | 0.0533 | 0.0134 | 0.0067 | 0.0332 | 15.9 | WIN | TIER_2_TRAILING_STOP | 408 | v2h_1939c0e9ac3c11a27063b211302e3937 | v2_fsnap_e01719c | mstate_3597a6b035936 | NO_HEDGE | 1 |
| 296 | 2026-06-18T16:35:39 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.03505 | 0.03526 | +0.60% | 955.87 | -0.2007 | 0.0135 | 0.0067 | -0.2210 | -59.9 | LOSS | TIER_2_TRAILING_STOP | 408 | v2h_40f3e5158016e539296e50660fb3f183 | v2_fsnap_f00dd0f | mstate_b48b2e0a588d7 | NO_HEDGE | 1 |
| 297 | 2026-06-18T16:38:51 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.385013 | 0.38636 | +0.35% | 128.31 | -0.1728 | 0.0198 | 0.0099 | -0.2026 | -35.0 | LOSS | TIER_2_TRAILING_STOP | 600 | v2h_3bf7f97efcfcfe87a8ac670e6f8419b5 | v2_fsnap_64f9751 | mstate_e078ea78668a3 | NO_HEDGE | 2 |
| 298 | 2026-06-18T16:42:02 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.853 | 1.827 | -1.40% | 12.50 | 0.3251 | 0.0091 | 0.0046 | 0.3114 | 140.3 | WIN | TIER_2_TAKE_PROFIT | 191 | v2h_05abae2a0dc5ef9b5a5b5418f67a08f4 | v2_fsnap_eac3c24 | mstate_739d5ea4bfb7c | NO_HEDGE | 1 |
| 299 | 2026-06-18T16:42:02 | BSBUSDT | short | 4h | trend_mode | TREND | TREND | 0.57073 | 0.56331 | -1.30% | 40.59 | 0.3012 | 0.0091 | 0.0046 | 0.2875 | 130.0 | WIN | TIER_2_TAKE_PROFIT | 191 | v2h_0ee2499bcacfbb08a5d50d298dc002ff | v2_fsnap_c5f2ebd | mstate_9e98c29c35639 | NO_HEDGE | 1 |
| 300 | 2026-06-18T16:44:19 | CHZUSDT | short | 5m | trend_mode | TREND | TREND | 0.0221177 | 0.02216 | +0.19% | 2354.53 | -0.0995 | 0.0209 | 0.0104 | -0.1308 | -19.1 | LOSS | TIER_2_TRAILING_STOP | 928 | v2h_99db460b81bc1eeefacbb74ff46b4b28 | v2_fsnap_3610a4d | mstate_3ae7bea01ae7b | NO_HEDGE | 2 |
| 301 | 2026-06-18T16:46:26 | BTCUSDT | short | 15m | mean_reversion_ | RANGE | RANGE | 62659.4 | 62749.9 | +0.14% | 0.00 | -0.2311 | 0.0641 | 0.0320 | -0.3272 | -14.4 | LOSS | TIER_2_TRAILING_STOP | 3841 | v2h_d232e3abe6ef918204cfdfb893e17c1b | null | mstate_c7a45d7535f82 | NO_HEDGE | 3 |
| 302 | 2026-06-18T16:46:26 | AVNTUSDT | short | 5m | trend_mode | TREND | TREND | 0.105044 | 0.105 | -0.04% | 596.69 | 0.0262 | 0.0251 | 0.0125 | -0.0114 | 4.2 | LOSS | TIER_2_TRAILING_STOP | 2159 | v2h_a8d45af6b142aea44aed8decc87ea531 | v2_fsnap_f89ec56 | mstate_8a84f0d3d78f1 | NO_HEDGE | 2 |
| 303 | 2026-06-18T16:46:26 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0989976 | 0.0991 | +0.10% | 526.04 | -0.0539 | 0.0209 | 0.0104 | -0.0852 | -10.3 | LOSS | TIER_2_TRAILING_STOP | 1055 | v2h_3a77479cf48957d2f101d053c355e3bb | v2_fsnap_600f137 | mstate_ad6ed95853dbf | NO_HEDGE | 2 |
| 304 | 2026-06-18T16:50:49 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.0625549 | 0.06275 | +0.31% | 644.86 | -0.1258 | 0.0162 | 0.0081 | -0.1501 | -31.2 | LOSS | TIER_2_TRAILING_STOP | 718 | v2h_4896536de9189ae289b37688900d59e6 | v2_fsnap_ee850f4 | mstate_1c6d0dc7a2661 | NO_HEDGE | 2 |
| 305 | 2026-06-18T16:50:49 | HOMEUSDT | short | 4h | trend_mode | TREND | TREND | 0.0278339 | 0.02797 | +0.49% | 1400.12 | -0.1906 | 0.0157 | 0.0078 | -0.2141 | -48.9 | LOSS | TIER_2_TRAILING_STOP | 521 | v2h_094b530c3334c245c54811d397dc11c8 | v2_fsnap_36a2a64 | mstate_b8e19e25d36d6 | NO_HEDGE | 2 |
| 306 | 2026-06-18T16:52:56 | ADAUSDT | short | 1m | trend_mode | TREND | TREND | 0.160891 | 0.1614 | +0.32% | 1067.74 | -0.5431 | 0.0689 | 0.0345 | -0.6465 | -31.6 | LOSS | TIER_2_TRAILING_STOP | 2614 | v2h_010fc2e7e647902cec45092b767feeb7 | v2_fsnap_24221dc | mstate_6bf78c2774ec8 | NO_HEDGE | 5 |
| 307 | 2026-06-18T16:52:56 | AAVEUSDT | short | 5m | trend_mode | TREND | TREND | 71.5269 | 71.77 | +0.34% | 1.27 | -0.3080 | 0.0364 | 0.0182 | -0.3626 | -34.0 | LOSS | TIER_2_TRAILING_STOP | 1445 | v2h_209b9b6c29a4ba09fa282f5514623aeb | v2_fsnap_fed232a | mstate_e8ecb558da6cc | NO_HEDGE | 3 |
| 308 | 2026-06-18T16:52:56 | DASHUSDT | short | 15m | trend_mode | TREND | TREND | 34.982 | 35.04 | +0.17% | 2.04 | -0.1185 | 0.0286 | 0.0143 | -0.1614 | -16.6 | LOSS | TIER_2_TRAILING_STOP | 1445 | v2h_249a54fe476a2be89e55d8206d79dc09 | v2_fsnap_8c19b51 | mstate_2fc833c61a036 | NO_HEDGE | 3 |
| 309 | 2026-06-18T16:52:56 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.889 | 1.838 | -2.70% | 10.25 | 0.5226 | 0.0075 | 0.0038 | 0.5113 | 270.0 | WIN | TIER_2_PROFIT_BANK | 263 | v2h_2370a697eb471a07c4920e545c330ed4 | v2_fsnap_41e9ed9 | mstate_91ab84d1678de | NO_HEDGE | 1 |
| 310 | 2026-06-18T16:52:56 | HUSDT | short | 15m | trend_mode | TREND | TREND | 0.23564 | 0.23094 | -1.99% | 63.99 | 0.3007 | 0.0059 | 0.0030 | 0.2919 | 199.5 | WIN | TIER_2_PROFIT_BANK | 64 | v2h_1526d84afcae51b29f2a650d1edea7c8 | v2_fsnap_cdddec0 | mstate_c643974c463ad | NO_HEDGE | 1 |
| 311 | 2026-06-18T16:55:06 | LDOUSDT | short | 1h | trend_mode | TREND | TREND | 0.267614 | 0.2677 | +0.03% | 723.66 | -0.0626 | 0.0775 | 0.0387 | -0.1788 | -3.2 | LOSS | TIER_2_TRAILING_STOP | 3064 | v2h_4aa3c95859bf13017e91fa0e19744b1d | v2_fsnap_6f595d7 | mstate_3b541eabaae5c | NO_HEDGE | 6 |
| 312 | 2026-06-18T16:55:06 | 1000PEPEUSDT | short | 5m | trend_mode | TREND | TREND | 0.00278864 | 0.0028019 | +0.48% | 27828.98 | -0.3691 | 0.0312 | 0.0156 | -0.4159 | -47.6 | LOSS | TIER_2_TRAILING_STOP | 2744 | v2h_b5055aa0fc8b3a8f663b9d2c47cfde87 | v2_fsnap_2d3d632 | mstate_85cbc7dab2c4c | NO_HEDGE | 2 |
| 313 | 2026-06-18T16:55:06 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0819971 | 0.08252 | +0.64% | 1913.48 | -1.0006 | 0.0632 | 0.0316 | -1.0953 | -63.8 | LOSS | TIER_2_TRAILING_STOP | 2744 | v2h_23e1c200507f919897399021490c0a1d | v2_fsnap_7fc4b97 | mstate_bb381ce2b05cb | NO_HEDGE | 5 |
| 314 | 2026-06-18T16:55:06 | ATOMUSDT | short | 1m | trend_mode | TREND | TREND | 1.79845 | 1.805 | +0.36% | 72.62 | -0.4756 | 0.0524 | 0.0262 | -0.5543 | -36.4 | LOSS | TIER_2_TRAILING_STOP | 2744 | v2h_7ae85737524d5ea1445c82e553835989 | v2_fsnap_723b91c | mstate_3cf21d9e8e5ff | NO_HEDGE | 5 |
| 315 | 2026-06-18T16:55:06 | AVAXUSDT | short | 4h | trend_mode | TREND | TREND | 6.29317 | 6.323 | +0.47% | 25.31 | -0.7549 | 0.0640 | 0.0320 | -0.8509 | -47.4 | LOSS | TIER_2_TRAILING_STOP | 2679 | v2h_175ccbb0acfda333df4affbab2f9bd27 | v2_fsnap_a5276c6 | mstate_ee6bb73210de3 | NO_HEDGE | 5 |
| 316 | 2026-06-18T16:55:06 | 1000SHIBUSDT | short | 5m | trend_mode | TREND | TREND | 0.004673 | 0.004687 | +0.30% | 5055.65 | -0.0708 | 0.0095 | 0.0047 | -0.0850 | -30.0 | LOSS | TIER_2_TRAILING_STOP | 2098 | v2h_331161a7d8575bceeddcb8741fdaafc0 | v2_fsnap_acedc4f | mstate_22bb64e0ea63f | NO_HEDGE | 1 |
| 317 | 2026-06-18T16:55:06 | DOTUSDT | short | 1h | trend_mode | TREND | TREND | 0.952668 | 0.956 | +0.35% | 95.15 | -0.3171 | 0.0364 | 0.0182 | -0.3716 | -35.0 | LOSS | TIER_2_TRAILING_STOP | 1575 | v2h_08fa69fd2a8b527a54aa510eb031e1e9 | v2_fsnap_2bbdebf | mstate_bf85a12ab2cff | NO_HEDGE | 3 |
| 318 | 2026-06-18T16:55:06 | APTUSDT | short | 1m | trend_mode | TREND | TREND | 0.627055 | 0.6309 | +0.61% | 78.59 | -0.3022 | 0.0198 | 0.0099 | -0.3320 | -61.3 | LOSS | TIER_2_TRAILING_STOP | 975 | v2h_021d1f8e659d4397e4e7797b23ab4c59 | v2_fsnap_81c06bf | mstate_77b0554033a69 | NO_HEDGE | 2 |
| 319 | 2026-06-18T16:55:06 | BIOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0351436 | 0.03554 | +1.13% | 1402.33 | -0.5558 | 0.0199 | 0.0100 | -0.5857 | -112.8 | LOSS | TIER_1_STOP_LOSS | 975 | v2h_738402a501df893907fdb33cacbf594b | v2_fsnap_f533160 | mstate_ab34149c340d5 | NO_HEDGE | 2 |
| 320 | 2026-06-18T16:55:06 | ENAUSDT | short | 1h | trend_mode | TREND | TREND | 0.0896869 | 0.09037 | +0.76% | 549.50 | -0.3754 | 0.0199 | 0.0099 | -0.4052 | -76.2 | LOSS | TIER_2_TRAILING_STOP | 975 | v2h_68e58679a762689fe30288a56fb0bb5e | v2_fsnap_0fa91a3 | mstate_55836d02164d1 | NO_HEDGE | 2 |
| 321 | 2026-06-18T16:55:06 | FETUSDT | short | 1m | trend_mode | TREND | TREND | 0.190922 | 0.1922 | +0.67% | 182.46 | -0.2332 | 0.0140 | 0.0070 | -0.2542 | -66.9 | LOSS | TIER_2_TRAILING_STOP | 911 | v2h_0c6ed11e187848cc469ba605a2050191 | v2_fsnap_05de1ae | mstate_25f54c1d03ba3 | NO_HEDGE | 2 |
| 322 | 2026-06-18T16:55:06 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.763 | 0.769 | +0.79% | 58.65 | -0.3519 | 0.0180 | 0.0090 | -0.3789 | -78.6 | LOSS | TIER_2_TRAILING_STOP | 778 | v2h_8936002fdce7ce9155845bddcf309b51 | v2_fsnap_354f4f3 | mstate_3a37aa2cb9291 | NO_HEDGE | 2 |
| 323 | 2026-06-18T16:55:06 | ALGOUSDT | short | 15m | trend_mode | TREND | TREND | 0.0989 | 0.0998 | +0.91% | 195.70 | -0.1761 | 0.0078 | 0.0039 | -0.1879 | -91.0 | LOSS | TIER_1_STOP_LOSS | 393 | v2h_0fa0cfc0d67d2305f5a8005efa543829 | v2_fsnap_f0b4336 | mstate_39ad5642722a8 | NO_HEDGE | 1 |
| 324 | 2026-06-18T16:57:19 | BCHUSDT | short | 1m | trend_mode | TREND | TREND | 196.157 | 196.86 | +0.36% | 0.36 | -0.2558 | 0.0287 | 0.0143 | -0.2989 | -35.8 | LOSS | TIER_2_TRAILING_STOP | 1708 | v2h_199ec3ad196edaf799ba991c779e0853 | v2_fsnap_0ec2e7d | mstate_430bbd71fbc1d | NO_HEDGE | 3 |
| 325 | 2026-06-18T16:58:23 | ALICEUSDT | short | 5m | trend_mode | TREND | TREND | 0.100612 | 0.1006 | -0.01% | 736.63 | 0.0089 | 0.0296 | 0.0148 | -0.0356 | 1.2 | LOSS | TIER_2_TRAILING_STOP | 2941 | v2h_45d1f8fa5fc5d1ec83aa3351b13c9b67 | v2_fsnap_a2efa27 | mstate_71cdd3daf4f6b | NO_HEDGE | 2 |
| 326 | 2026-06-18T16:58:23 | CHZUSDT | short | 1m | trend_mode | TREND | TREND | 0.0223063 | 0.02235 | +0.20% | 2010.69 | -0.0879 | 0.0180 | 0.0090 | -0.1149 | -19.6 | LOSS | TIER_2_TRAILING_STOP | 391 | v2h_2f3952f9054eb78f0393c8e8a9d4eafb | v2_fsnap_1cbc2fe | mstate_148a0100a9a3b | NO_HEDGE | 2 |
| 327 | 2026-06-18T17:01:31 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.84 | 1.804 | -1.96% | 17.30 | 0.6230 | 0.0125 | 0.0062 | 0.6042 | 195.7 | WIN | TIER_2_PROFIT_BANK | 188 | v2h_0c1e23804f43f875b3916cef4a927ff6 | v2_fsnap_842a803 | mstate_995db4360bd4d | NO_HEDGE | 1 |
| 328 | 2026-06-18T17:01:31 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.23355 | 0.23047 | -1.32% | 158.00 | 0.4867 | 0.0146 | 0.0073 | 0.4648 | 131.9 | WIN | TIER_2_TAKE_PROFIT | 188 | v2h_09c785549a9d0ea675e852cdf8ac26c0 | v2_fsnap_2c176db | mstate_d5d434b3d0809 | NO_HEDGE | 1 |
| 329 | 2026-06-18T17:03:25 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.06604 | 0.06442 | -2.45% | 245.68 | 0.3980 | 0.0063 | 0.0032 | 0.3885 | 245.3 | WIN | TIER_2_PROFIT_BANK | 110 | v2h_199f01ac07457c92a7d3b721802ca56c | v2_fsnap_087d518 | mstate_1cca3b593389e | NO_HEDGE | 1 |
| 330 | 2026-06-18T17:03:46 | ALLOUSDT | short | 1m | trend_mode | TREND | TREND | 0.38566 | 0.38701 | +0.35% | 125.93 | -0.1700 | 0.0195 | 0.0097 | -0.1992 | -35.0 | LOSS | TIER_2_TRAILING_STOP | 913 | v2h_2baf2109ff8ca64da2d3b40b5733a159 | v2_fsnap_bf8172d | mstate_2c7c47572c401 | NO_HEDGE | 2 |
| 331 | 2026-06-18T17:06:01 | BSBUSDT | short | 15m | trend_mode | TREND | TREND | 0.566105 | 0.56601 | -0.02% | 126.83 | 0.0120 | 0.0287 | 0.0144 | -0.0311 | 1.7 | LOSS | TIER_2_TRAILING_STOP | 1048 | v2h_13d094dbd8f0b1b61973b3b675d53ff8 | v2_fsnap_3c07fd5 | mstate_a395ee2fc73ff | NO_HEDGE | 3 |
| 332 | 2026-06-18T17:08:11 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0357246 | 0.03527 | -1.27% | 1701.44 | 0.7734 | 0.0240 | 0.0120 | 0.7374 | 127.2 | WIN | TIER_2_TAKE_PROFIT | 588 | v2h_bd108da6f1628baaa692642e8a741981 | v2_fsnap_ecbb6dd | mstate_ea0becdf5d71f | NO_HEDGE | 2 |
| 333 | 2026-06-18T17:09:13 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0996932 | 0.1001 | +0.41% | 726.27 | -0.2954 | 0.0291 | 0.0145 | -0.3391 | -40.8 | LOSS | TIER_2_TRAILING_STOP | 650 | v2h_31efab422d59e9a6a2e3a62746bd2b6c | v2_fsnap_e4fc850 | mstate_3cb4986411cd5 | NO_HEDGE | 3 |
| 334 | 2026-06-18T17:10:18 | HOMEUSDT | short | 4h | trend_mode | TREND | TREND | 0.0279941 | 0.02742 | -2.05% | 2858.39 | 1.6410 | 0.0314 | 0.0157 | 1.5940 | 205.1 | WIN | TIER_2_PROFIT_BANK | 715 | v2h_93748f4967370d049d10de42f4544a18 | v2_fsnap_911c3b3 | mstate_1edfb488b037e | NO_HEDGE | 3 |
| 335 | 2026-06-18T17:11:21 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.742 | 1.721 | -1.21% | 11.46 | 0.2406 | 0.0079 | 0.0039 | 0.2288 | 120.6 | WIN | TIER_2_TAKE_PROFIT | 129 | v2h_6ed418fe927519fffa608c5c17d64306 | v2_fsnap_8782c5b | mstate_b2e7a1b6ab265 | NO_HEDGE | 1 |
| 336 | 2026-06-18T17:12:13 | BSBUSDT | short | 15m | trend_mode | TREND | TREND | 0.56526 | 0.55526 | -1.77% | 35.31 | 0.3531 | 0.0078 | 0.0039 | 0.3413 | 176.9 | WIN | TIER_2_TAKE_PROFIT | 181 | v2h_00610073f4de265f395974a7014342d1 | v2_fsnap_d78f161 | mstate_c193a5a36d1a7 | NO_HEDGE | 1 |
| 337 | 2026-06-18T17:13:35 | BIOUSDT | short | 15m | trend_mode | TREND | TREND | 0.03527 | 0.03579 | +1.47% | 655.79 | -0.3410 | 0.0094 | 0.0047 | -0.3551 | -147.4 | LOSS | TIER_1_STOP_LOSS | 263 | v2h_0d6c1d7aed65169109a3183e1a3d515a | v2_fsnap_29d712a | mstate_3aada11c43cbe | NO_HEDGE | 1 |
| 338 | 2026-06-18T17:13:35 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.06496 | 0.06395 | -1.55% | 181.77 | 0.1836 | 0.0046 | 0.0023 | 0.1766 | 155.5 | WIN | TIER_2_TAKE_PROFIT | 198 | v2h_1c444137b4cb73c6f94a89941b325608 | v2_fsnap_a6f9c31 | mstate_57dfaa28f1739 | NO_HEDGE | 1 |
| 339 | 2026-06-18T17:14:39 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.23106 | 0.23209 | +0.45% | 68.43 | -0.0705 | 0.0064 | 0.0032 | -0.0800 | -44.6 | LOSS | TIER_2_TRAILING_STOP | 198 | v2h_44c4bf9b7d88e82813a8c024cd6370b0 | v2_fsnap_7b12729 | mstate_f4e8b993580de | NO_HEDGE | 1 |
| 340 | 2026-06-18T17:17:54 | HBARUSDT | short | 1m | trend_mode | TREND | TREND | 0.0793349 | 0.07952 | +0.23% | 3498.76 | -0.6476 | 0.1113 | 0.0556 | -0.8145 | -23.3 | LOSS | TIER_2_TRAILING_STOP | 4432 | v2h_242567989765e5077a811f7405237961 | v2_fsnap_f288cac | mstate_31bb06374285a | NO_HEDGE | 9 |
| 341 | 2026-06-18T17:22:19 | BEATUSDT | short | 15m | trend_mode | TREND | TREND | 1.683 | 1.635 | -2.85% | 10.75 | 0.5161 | 0.0070 | 0.0035 | 0.5055 | 285.2 | WIN | TIER_2_PROFIT_BANK | 129 | v2h_2bda51b0395f0ba62394cb3a9906d1a9 | v2_fsnap_e32bb26 | mstate_c3668c3e8715d | NO_HEDGE | 1 |
| 342 | 2026-06-18T17:22:19 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.51962 | 0.47612 | -8.37% | 34.82 | 1.5149 | 0.0066 | 0.0033 | 1.5049 | 837.2 | WIN | TIER_2_PROFIT_BANK | 129 | v2h_5be5626d058ff4aa578fb9260e86d45e | v2_fsnap_d3da3ec | mstate_823ebe05e90e1 | NO_HEDGE | 1 |
| 343 | 2026-06-18T17:24:28 | ENAUSDT | short | 5m | trend_mode | TREND | TREND | 0.0898084 | 0.08845 | -1.51% | 901.96 | 1.2252 | 0.0319 | 0.0160 | 1.1773 | 151.3 | WIN | TIER_2_TAKE_PROFIT | 1565 | v2h_716bf85b42f11af2a69a9ebb315cb827 | v2_fsnap_2f75da4 | mstate_d44adfb21ce54 | NO_HEDGE | 3 |
| 344 | 2026-06-18T17:24:28 | ALLOUSDT | short | 1m | trend_mode | TREND | TREND | 0.388751 | 0.38405 | -1.21% | 92.86 | 0.4365 | 0.0143 | 0.0071 | 0.4151 | 120.9 | WIN | TIER_2_TAKE_PROFIT | 916 | v2h_06c58f2a69a050dcc97b8fce80d2c669 | v2_fsnap_1b48018 | mstate_f4cd090550f53 | NO_HEDGE | 2 |
| 345 | 2026-06-18T17:24:28 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.06474 | 0.06548 | +1.14% | 178.61 | -0.1322 | 0.0047 | 0.0023 | -0.1392 | -114.3 | LOSS | TIER_1_STOP_LOSS | 64 | v2h_82bb354763a0a2be4c17f12cabdc5eb9 | v2_fsnap_f39aed5 | mstate_0979f7161fa04 | NO_HEDGE | 1 |
| 346 | 2026-06-18T17:28:50 | FETUSDT | short | 1m | trend_mode | TREND | TREND | 0.191781 | 0.1894 | -1.24% | 471.89 | 1.1234 | 0.0358 | 0.0179 | 1.0698 | 124.1 | WIN | TIER_2_TAKE_PROFIT | 1827 | v2h_3091a79c97025d9276bd5ba4653fd8b4 | v2_fsnap_7526ac7 | mstate_6baf5233a72de | NO_HEDGE | 4 |
| 347 | 2026-06-18T17:28:50 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.03571 | 0.03517 | -1.51% | 587.29 | 0.3171 | 0.0083 | 0.0041 | 0.3047 | 151.2 | WIN | TIER_2_TAKE_PROFIT | 520 | v2h_3b6fa70dfcb0acbef7383b56af1a0df0 | v2_fsnap_72c1bcb | mstate_4da19f91bdb99 | NO_HEDGE | 1 |
| 348 | 2026-06-18T17:29:55 | AUCTIONUSDT | short | 5m | trend_mode | TREND | TREND | 3.65612 | 3.649 | -0.19% | 20.27 | 0.1444 | 0.0296 | 0.0148 | 0.1000 | 19.5 | WIN | TIER_2_TRAILING_STOP | 4833 | v2h_4d12eb2c9ef692c0fd721eb4d211bcb8 | v2_fsnap_647fe8d | mstate_5b9969fa380eb | NO_HEDGE | 2 |
| 349 | 2026-06-18T17:30:28 | APTUSDT | short | 15m | trend_mode | TREND | TREND | 0.62902 | 0.6265 | -0.40% | 128.78 | 0.3245 | 0.0323 | 0.0161 | 0.2761 | 40.1 | WIN | TIER_2_TRAILING_STOP | 1925 | v2h_2b27ce40bdc8461842e5b9eb13799b0d | v2_fsnap_e756a2b | mstate_2377f47d2b51c | NO_HEDGE | 3 |
| 350 | 2026-06-18T17:30:28 | ARBUSDT | short | 1h | trend_mode | TREND | TREND | 0.0823444 | 0.08209 | -0.31% | 983.72 | 0.2502 | 0.0323 | 0.0162 | 0.2018 | 30.9 | WIN | TIER_2_TRAILING_STOP | 1925 | v2h_4d8621e3d2109f70d0792b1ad1d4d3d9 | v2_fsnap_63065b5 | mstate_fff0cc29c37ba | NO_HEDGE | 3 |
| 351 | 2026-06-18T17:30:28 | ALGOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0994 | 0.0992 | -0.20% | 182.05 | 0.0364 | 0.0072 | 0.0036 | 0.0256 | 20.1 | WIN | TIER_2_PROFIT_LOCK | 618 | v2h_3cada6300023a0fc4e8c87dc740fde81 | v2_fsnap_72f0590 | mstate_58e52243f8532 | NO_HEDGE | 1 |
| 352 | 2026-06-18T17:30:59 | AAVEUSDT | short | 5m | trend_mode | TREND | TREND | 71.9324 | 72.13 | +0.27% | 1.54 | -0.3043 | 0.0444 | 0.0222 | -0.3709 | -27.5 | LOSS | TIER_2_TRAILING_STOP | 1956 | v2h_1ebb12a194968b9259a649efc1cf2088 | v2_fsnap_4651f65 | mstate_7977334113542 | NO_HEDGE | 4 |
| 353 | 2026-06-18T17:30:59 | DASHUSDT | short | 4h | trend_mode | TREND | TREND | 35.0873 | 35.08 | -0.02% | 3.08 | 0.0226 | 0.0431 | 0.0216 | -0.0422 | 2.1 | LOSS | TIER_2_TRAILING_STOP | 1956 | v2h_2feb3c65b80641974e51abd5aea09d1f | v2_fsnap_dcc1b3f | mstate_3fa1f257861c8 | NO_HEDGE | 5 |
| 354 | 2026-06-18T17:30:59 | DOTUSDT | short | 5m | trend_mode | TREND | TREND | 0.953624 | 0.952 | -0.17% | 143.57 | 0.2332 | 0.0547 | 0.0273 | 0.1512 | 17.0 | WIN | TIER_2_TRAILING_STOP | 1956 | v2h_ad558577e3395fb9f7101ed03945ac28 | v2_fsnap_9f32b8e | mstate_cdbb99700c817 | NO_HEDGE | 5 |
| 355 | 2026-06-18T17:30:59 | FILUSDT | short | 1m | trend_mode | TREND | TREND | 0.76589 | 0.764 | -0.25% | 176.46 | 0.3335 | 0.0539 | 0.0270 | 0.2527 | 24.7 | WIN | TIER_2_TRAILING_STOP | 1956 | v2h_d876481a6d7063ce71ce8878a0d076c4 | v2_fsnap_fdeffcb | mstate_297539b54f0a9 | NO_HEDGE | 5 |
| 356 | 2026-06-18T17:30:59 | HYPEUSDT | short | 15m | trend_mode | TREND | TREND | 67.1939 | 67.258 | +0.10% | 2.04 | -0.1305 | 0.0548 | 0.0274 | -0.2128 | -9.5 | LOSS | TIER_2_TRAILING_STOP | 1956 | v2h_e1982fd4f9dbcacb1cdcd76872bed81a | v2_fsnap_dc6d33b | mstate_34188a8d046d5 | NO_HEDGE | 5 |
| 357 | 2026-06-18T17:30:59 | INJUSDT | short | 1m | trend_mode | TREND | TREND | 5.1214 | 5.116 | -0.11% | 19.75 | 0.1066 | 0.0404 | 0.0202 | 0.0459 | 10.5 | WIN | TIER_2_TRAILING_STOP | 1956 | v2h_0c1d8dfe48eec1f3d85f2599892fb25d | v2_fsnap_430661d | mstate_130a891085fb8 | NO_HEDGE | 4 |
| 358 | 2026-06-18T17:30:59 | JTOUSDT | short | 4h | trend_mode | TREND | TREND | 0.700385 | 0.7017 | +0.19% | 120.06 | -0.1579 | 0.0337 | 0.0168 | -0.2084 | -18.8 | LOSS | TIER_2_TRAILING_STOP | 1764 | v2h_66a35b8e568dee4eae82736cd4b87e24 | v2_fsnap_60838e2 | mstate_f809916ebb5ab | NO_HEDGE | 4 |
| 359 | 2026-06-18T17:30:59 | LDOUSDT | short | 5m | trend_mode | TREND | TREND | 0.266653 | 0.2673 | +0.24% | 217.47 | -0.1408 | 0.0233 | 0.0116 | -0.1757 | -24.3 | LOSS | TIER_2_TRAILING_STOP | 1114 | v2h_4291e3acfa9165acbb7a572fc1559edd | v2_fsnap_ad7887a | mstate_4e2d830b2e141 | NO_HEDGE | 3 |
| 360 | 2026-06-18T17:33:08 | CRVUSDT | short | 1m | trend_mode | TREND | TREND | 0.217944 | 0.2178 | -0.07% | 844.03 | 0.1213 | 0.0735 | 0.0368 | 0.0110 | 6.6 | WIN | TIER_2_TRAILING_STOP | 3857 | v2h_460031ecda031811382eb55afafc59b2 | v2_fsnap_3e66c5b | mstate_59a51f29e8b85 | NO_HEDGE | 7 |
| 361 | 2026-06-18T17:33:08 | AEROUSDT | short | 1h | trend_mode | TREND | TREND | 0.434704 | 0.4346 | -0.02% | 401.03 | 0.0417 | 0.0697 | 0.0349 | -0.0628 | 2.4 | LOSS | TIER_2_TRAILING_STOP | 3257 | v2h_040971884d1b75860abeb5b9ca037d7a | v2_fsnap_c621233 | mstate_f313df10ef78a | NO_HEDGE | 7 |
| 362 | 2026-06-18T17:33:08 | ADAUSDT | short | 1m | trend_mode | TREND | TREND | 0.161707 | 0.1618 | +0.06% | 846.68 | -0.0790 | 0.0548 | 0.0274 | -0.1612 | -5.8 | LOSS | TIER_2_TRAILING_STOP | 2085 | v2h_4fd456a012905daf6a73fa5d027313d6 | v2_fsnap_ba92e96 | mstate_2e7184ce439cc | NO_HEDGE | 5 |
| 363 | 2026-06-18T17:33:08 | BCHUSDT | short | 1h | trend_mode | TREND | TREND | 196.095 | 196.03 | -0.03% | 0.45 | 0.0289 | 0.0349 | 0.0175 | -0.0235 | 3.3 | LOSS | TIER_2_TRAILING_STOP | 2085 | v2h_0f305371e6eee3e8154087f6d02a525f | v2_fsnap_42d7ef9 | mstate_f93d8cf20133a | NO_HEDGE | 4 |
| 364 | 2026-06-18T17:33:08 | ICPUSDT | short | 4h | trend_mode | TREND | TREND | 2.21656 | 2.218 | +0.07% | 49.97 | -0.0721 | 0.0443 | 0.0222 | -0.1386 | -6.5 | LOSS | TIER_2_TRAILING_STOP | 2085 | v2h_6163baf47b5d90312566c32964844967 | v2_fsnap_7ffaab8 | mstate_e8e6683c3968c | NO_HEDGE | 4 |
| 365 | 2026-06-18T17:33:08 | AVAXUSDT | short | 15m | trend_mode | TREND | TREND | 6.30676 | 6.302 | -0.08% | 15.30 | 0.0728 | 0.0386 | 0.0193 | 0.0149 | 7.5 | WIN | TIER_2_TRAILING_STOP | 2022 | v2h_06c63823aae32c5037d522d02e203b42 | v2_fsnap_ecdce99 | mstate_1375da7c129b2 | NO_HEDGE | 4 |
| 366 | 2026-06-18T17:33:08 | CHZUSDT | short | 5m | trend_mode | TREND | TREND | 0.0223402 | 0.02236 | +0.09% | 3404.40 | -0.0675 | 0.0304 | 0.0152 | -0.1132 | -8.9 | LOSS | TIER_2_TRAILING_STOP | 2022 | v2h_222da1e1b4d9ce6bb703b4197bf16771 | v2_fsnap_6d489af | mstate_4c13087d0e4bb | NO_HEDGE | 4 |
| 367 | 2026-06-18T17:33:08 | HBARUSDT | short | 15m | trend_mode | TREND | TREND | 0.0795876 | 0.07988 | +0.37% | 430.82 | -0.1260 | 0.0138 | 0.0069 | -0.1466 | -36.7 | LOSS | TIER_2_TRAILING_STOP | 584 | v2h_9ce8487d429ee40ae795b2a1962088d6 | v2_fsnap_4d43ecb | mstate_9dc25e3889dba | NO_HEDGE | 2 |
| 368 | 2026-06-18T17:33:08 | BSBUSDT | short | 1h | trend_mode | TREND | TREND | 0.50598 | 0.49915 | -1.35% | 34.38 | 0.2348 | 0.0069 | 0.0034 | 0.2245 | 135.0 | WIN | TIER_2_TAKE_PROFIT | 129 | v2h_20c50e257cef125377dd2bb55750bab5 | v2_fsnap_f569cb2 | mstate_d1530cfa2ff8f | NO_HEDGE | 1 |
| 369 | 2026-06-18T17:33:08 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.06704 | 0.06499 | -3.06% | 246.15 | 0.5046 | 0.0064 | 0.0032 | 0.4950 | 305.8 | WIN | TIER_2_PROFIT_BANK | 129 | v2h_09b49cd478bf7b62a0ece073308c85c2 | v2_fsnap_cf5c288 | mstate_d3745b3de0959 | NO_HEDGE | 1 |
| 370 | 2026-06-18T17:35:30 | LABUSDT | short | 4h | trend_mode | TREND | TREND | 16.3636 | 16.38 | +0.10% | 5.15 | -0.0846 | 0.0337 | 0.0169 | -0.1352 | -10.1 | LOSS | TIER_2_TRAILING_STOP | 1385 | v2h_0676a6c4409a82d4153eac7b4b33bc20 | v2_fsnap_4da8c6d | mstate_3fcff65502249 | NO_HEDGE | 4 |
| 371 | 2026-06-18T17:35:30 | ALLOUSDT | short | 1m | trend_mode | TREND | TREND | 0.38505 | 0.38698 | +0.50% | 42.86 | -0.0827 | 0.0066 | 0.0033 | -0.0927 | -50.1 | LOSS | TIER_2_TRAILING_STOP | 271 | v2h_151de284eb3ef6bcbeff084d5618516f | v2_fsnap_3cd2e00 | mstate_dda409da413bd | NO_HEDGE | 1 |
| 372 | 2026-06-18T17:37:48 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.23112 | 0.2328 | +0.73% | 105.56 | -0.1773 | 0.0098 | 0.0049 | -0.1921 | -72.7 | LOSS | TIER_2_TRAILING_STOP | 345 | v2h_25bfa864a9de34ad0bd34405fd056fa4 | v2_fsnap_228651d | mstate_0fd1bdda66418 | NO_HEDGE | 1 |
| 373 | 2026-06-18T17:38:54 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.64896 | 1.654 | +0.31% | 26.41 | -0.1331 | 0.0175 | 0.0087 | -0.1593 | -30.6 | LOSS | TIER_2_TRAILING_STOP | 475 | v2h_243c4b07187ca03770cf73f49e220012 | v2_fsnap_866899d | mstate_1262731729b57 | NO_HEDGE | 2 |
| 374 | 2026-06-18T17:38:54 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.0274 | 0.02705 | -1.28% | 849.11 | 0.2972 | 0.0092 | 0.0046 | 0.2834 | 127.7 | WIN | TIER_2_TAKE_PROFIT | 411 | v2h_0e775276f89a1fc35e0ac99d6d65b7dc | v2_fsnap_f13e539 | mstate_940639e49ec84 | NO_HEDGE | 1 |
| 375 | 2026-06-18T17:41:02 | LITUSDT | short | 15m | trend_mode | TREND | TREND | 1.5725 | 1.5839 | +0.72% | 15.52 | -0.1769 | 0.0098 | 0.0049 | -0.1916 | -72.5 | LOSS | TIER_2_TRAILING_STOP | 539 | v2h_7f065772292492e0547426d1bc08f989 | v2_fsnap_8f7879d | mstate_cdf9e2b9f4073 | NO_HEDGE | 1 |
| 376 | 2026-06-18T17:43:10 | BIOUSDT | short | 1m | trend_mode | TREND | TREND | 0.0354849 | 0.0356 | +0.32% | 1442.36 | -0.1660 | 0.0205 | 0.0103 | -0.1968 | -32.4 | LOSS | TIER_2_TRAILING_STOP | 731 | v2h_4164dec4c976d5ac757e9c4527a17939 | v2_fsnap_79adc80 | mstate_43b90b329be47 | NO_HEDGE | 2 |
| 377 | 2026-06-18T17:43:10 | ETCUSDT | short | 1h | mean_reversion_ | RANGE | RANGE | 7.486 | 7.026 | -6.14% | 3.48 | 1.5999 | 0.0098 | 0.0049 | 1.5852 | 614.5 | WIN | TIER_2_PROFIT_BANK | 129 | v2h_b6961846ace4a6a2d0f0f5634449fa8e | null | mstate_19bf60e102e7f | NO_HEDGE | 1 |
| 378 | 2026-06-18T17:44:15 | NIGHTUSDT | short | 4h | trend_mode | TREND | TREND | 0.030118 | 0.03032 | +0.67% | 1754.66 | -0.3545 | 0.0213 | 0.0106 | -0.3864 | -67.1 | LOSS | TIER_2_TRAILING_STOP | 732 | v2h_20f0339d9c128ff281686dfd4bff588e | v2_fsnap_3a44c11 | mstate_89051757d0b1f | NO_HEDGE | 2 |
| 379 | 2026-06-18T17:44:15 | PORTALUSDT | short | 1h | mean_reversion_ | RANGE | RANGE | 0.01182 | 0.01501 | +26.99% | 2195.98 | -7.0052 | 0.0132 | 0.0066 | -7.0249 | -2698.8 | LOSS | TIER_1_STOP_LOSS | 194 | v2h_ffda9a8d28b971b6713540d389f7626d | null | mstate_8b6a84ea16506 | NO_HEDGE | 1 |
| 380 | 2026-06-18T17:46:28 | NEARUSDT | short | 1h | trend_mode | TREND | TREND | 2.16199 | 2.182 | +0.93% | 28.76 | -0.5756 | 0.0251 | 0.0126 | -0.6133 | -92.6 | LOSS | TIER_1_STOP_LOSS | 865 | v2h_2ac2dc08ca788ef76307c660773a304a | v2_fsnap_d99c948 | mstate_8b52b89e68656 | NO_HEDGE | 2 |
| 381 | 2026-06-18T17:47:36 | MEGAUSDT | short | 4h | trend_mode | TREND | TREND | 0.062995 | 0.06305 | +0.09% | 879.73 | -0.0484 | 0.0222 | 0.0111 | -0.0817 | -8.7 | LOSS | TIER_2_TRAILING_STOP | 933 | v2h_4abad29fd86c08000d6cd687bd936fba | v2_fsnap_903c5b6 | mstate_d270e97de4828 | NO_HEDGE | 2 |
| 382 | 2026-06-18T17:51:55 | MITOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0252482 | 0.0254 | +0.60% | 1893.92 | -0.2876 | 0.0192 | 0.0096 | -0.3164 | -60.1 | LOSS | TIER_2_TRAILING_STOP | 1192 | v2h_34bc50d83e86d7c3416fc77e7beb9a0b | v2_fsnap_40bc1f0 | mstate_453486da861ce | NO_HEDGE | 2 |
| 383 | 2026-06-18T17:53:00 | OPUSDT | short | 1m | trend_mode | TREND | TREND | 0.104772 | 0.1052 | +0.41% | 621.12 | -0.2658 | 0.0261 | 0.0131 | -0.3050 | -40.8 | LOSS | TIER_2_TRAILING_STOP | 1122 | v2h_1caba7313918dc440d4635e4f89fd976 | v2_fsnap_34ee070 | mstate_935b2f3d90a9f | NO_HEDGE | 2 |
| 384 | 2026-06-18T17:53:00 | PENDLEUSDT | short | 4h | trend_mode | TREND | TREND | 1.34971 | 1.3508 | +0.08% | 71.74 | -0.0780 | 0.0388 | 0.0194 | -0.1362 | -8.1 | LOSS | TIER_2_TRAILING_STOP | 1122 | v2h_1a5ad746570486c6c28a9f1bd2fecd1d | v2_fsnap_7fea409 | mstate_527ae4dbfbe97 | NO_HEDGE | 3 |
| 385 | 2026-06-18T17:56:22 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.69536 | 1.707 | +0.69% | 22.82 | -0.2657 | 0.0156 | 0.0078 | -0.2891 | -68.7 | LOSS | TIER_2_TRAILING_STOP | 663 | v2h_0052c7709a09eb2f7e3bb7adf64be5d9 | v2_fsnap_3c02a30 | mstate_91cd690ca8a7a | NO_HEDGE | 2 |
| 386 | 2026-06-18T18:00:50 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0610123 | 0.06156 | +0.90% | 412.71 | -0.2261 | 0.0102 | 0.0051 | -0.2413 | -89.8 | LOSS | TIER_1_STOP_LOSS | 203 | v2h_34f9bb9a91026c71d9a4a91a0bda4140 | v2_fsnap_6392e70 | mstate_b1a16a14f25e8 | NO_HEDGE | 2 |
| 387 | 2026-06-18T18:07:21 | ALGOUSDT | short | 1m | trend_mode | TREND | TREND | 0.0988132 | 0.0989 | +0.09% | 896.51 | -0.0778 | 0.0355 | 0.0177 | -0.1310 | -8.8 | LOSS | TIER_2_TRAILING_STOP | 2182 | v2h_0b69604c0628a98e54c8fe6cb3be68fe | v2_fsnap_1c1a414 | mstate_0260e25023567 | NO_HEDGE | 5 |
| 388 | 2026-06-18T18:07:21 | TRUMPUSDT | short | 15m | trend_mode | TREND | TREND | 1.84649 | 1.852 | +0.30% | 70.90 | -0.3910 | 0.0525 | 0.0263 | -0.4698 | -29.9 | LOSS | TIER_2_TRAILING_STOP | 1983 | v2h_011df6da473941e830cb4fbec1bd1faf | v2_fsnap_abe43df | mstate_83ec1418f621e | NO_HEDGE | 5 |
| 389 | 2026-06-18T18:07:21 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0361756 | 0.03636 | +0.51% | 993.02 | -0.1832 | 0.0144 | 0.0072 | -0.2048 | -51.0 | LOSS | TIER_2_TRAILING_STOP | 725 | v2h_1be40d8d475fc9a41964df774c417300 | v2_fsnap_8c7d433 | mstate_9ed736d541fe4 | NO_HEDGE | 2 |
| 390 | 2026-06-18T18:09:32 | APTUSDT | short | 1m | trend_mode | TREND | TREND | 0.625968 | 0.6281 | +0.34% | 164.02 | -0.3497 | 0.0412 | 0.0206 | -0.4115 | -34.1 | LOSS | TIER_2_TRAILING_STOP | 2313 | v2h_0a53c995185b25cb768f509fd5cbe0c6 | v2_fsnap_6d1abd2 | mstate_ebb99e83a408e | NO_HEDGE | 5 |
| 391 | 2026-06-18T18:09:32 | ENAUSDT | short | 1m | trend_mode | TREND | TREND | 0.0893737 | 0.08966 | +0.32% | 1487.91 | -0.4260 | 0.0534 | 0.0267 | -0.5060 | -32.0 | LOSS | TIER_2_TRAILING_STOP | 2313 | v2h_1f360550ad6069768854c12b5d0674af | v2_fsnap_0d86bf5 | mstate_dea91077bcc6b | NO_HEDGE | 6 |
| 392 | 2026-06-18T18:09:32 | AEROUSDT | short | 4h | trend_mode | TREND | TREND | 0.433957 | 0.4358 | +0.42% | 190.13 | -0.3505 | 0.0331 | 0.0166 | -0.4002 | -42.5 | LOSS | TIER_2_TRAILING_STOP | 1646 | v2h_7dd45348b437d9694a42bf9d682cf63a | v2_fsnap_95f4e59 | mstate_330af970ee990 | NO_HEDGE | 4 |
| 393 | 2026-06-18T18:11:22 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.723 | 1.696 | -1.57% | 5.73 | 0.1547 | 0.0039 | 0.0019 | 0.1489 | 156.7 | WIN | TIER_2_TAKE_PROFIT | 242 | v2h_0920e03e9cdb93fabe6e5f8bd0e7e871 | v2_fsnap_1e2ff66 | mstate_b1e4dac8e8f39 | NO_HEDGE | 1 |
| 394 | 2026-06-18T18:13:50 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.06149 | 0.06186 | +0.60% | 147.44 | -0.0546 | 0.0036 | 0.0018 | -0.0600 | -60.2 | LOSS | TIER_2_TRAILING_STOP | 323 | v2h_0bd995df9563388cc7333f6826cc5b79 | v2_fsnap_b5a42af | mstate_f705ea6943522 | NO_HEDGE | 1 |
| 395 | 2026-06-18T18:20:45 | ARBUSDT | short | 15m | trend_mode | TREND | TREND | 0.0820255 | 0.08233 | +0.37% | 1214.15 | -0.3697 | 0.0400 | 0.0200 | -0.4297 | -37.1 | LOSS | TIER_2_TRAILING_STOP | 2986 | v2h_03867f873824313bd5383348a3057fd8 | v2_fsnap_6ac2a7e | mstate_1c2bacd59a76f | NO_HEDGE | 5 |
| 396 | 2026-06-18T18:20:45 | FETUSDT | short | 5m | trend_mode | TREND | TREND | 0.190391 | 0.1908 | +0.21% | 745.91 | -0.3052 | 0.0569 | 0.0285 | -0.3906 | -21.5 | LOSS | TIER_2_TRAILING_STOP | 2922 | v2h_3f3718eb40ac1d238e3544b85717e024 | v2_fsnap_8ba96e8 | mstate_73f6ca6b60b62 | NO_HEDGE | 8 |
| 397 | 2026-06-18T18:20:45 | PUMPUSDT | short | 1h | trend_mode | TREND | TREND | 0.001415 | 0.001418 | +0.21% | 81219.41 | -0.2438 | 0.0461 | 0.0230 | -0.3129 | -21.2 | LOSS | TIER_2_TRAILING_STOP | 2787 | v2h_91d8f72e5aaf06659577f58dcfc1474b | v2_fsnap_d920899 | mstate_81d5b09ee959b | NO_HEDGE | 5 |
| 398 | 2026-06-18T18:20:45 | RENDERUSDT | short | 5m | trend_mode | TREND | TREND | 1.64059 | 1.648 | +0.45% | 72.56 | -0.5374 | 0.0478 | 0.0239 | -0.6091 | -45.1 | LOSS | TIER_2_TRAILING_STOP | 2787 | v2h_5ffc1c988b2c73242ad576569bc4e761 | v2_fsnap_33611e1 | mstate_b69b8b8d33a54 | NO_HEDGE | 6 |
| 399 | 2026-06-18T18:20:45 | SEIUSDT | short | 1h | trend_mode | TREND | TREND | 0.0531982 | 0.05327 | +0.14% | 2160.32 | -0.1552 | 0.0460 | 0.0230 | -0.2242 | -13.5 | LOSS | TIER_2_TRAILING_STOP | 2787 | v2h_4fe0034636080487ce21049fa9c43190 | v2_fsnap_5fd6588 | mstate_91958f48e7a3a | NO_HEDGE | 5 |
| 400 | 2026-06-18T18:20:45 | TIAUSDT | short | 5m | trend_mode | TREND | TREND | 0.375407 | 0.3771 | +0.45% | 387.24 | -0.6558 | 0.0584 | 0.0292 | -0.7434 | -45.1 | LOSS | TIER_2_TRAILING_STOP | 2787 | v2h_2784b59cdfc03801bcba161816215a20 | v2_fsnap_0806ccd | mstate_5b4d852a2795c | NO_HEDGE | 7 |
| 401 | 2026-06-18T18:20:45 | HYPEUSDT | short | 15m | trend_mode | TREND | TREND | 67.2939 | 67.873 | +0.86% | 0.45 | -0.2607 | 0.0122 | 0.0061 | -0.2790 | -86.1 | LOSS | TIER_1_STOP_LOSS | 609 | v2h_76a4a9065bb23dd29e93ab90a40808e1 | v2_fsnap_429ea51 | mstate_2d73bd159f8ff | NO_HEDGE | 2 |
| 402 | 2026-06-18T18:20:45 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.732 | 1.753 | +1.21% | 13.64 | -0.2863 | 0.0096 | 0.0048 | -0.3007 | -121.2 | LOSS | TIER_1_STOP_LOSS | 135 | v2h_dbb062ccc133c34646a389d015208b12 | v2_fsnap_37c924d | mstate_fabd5fc1c9967 | NO_HEDGE | 2 |
| 403 | 2026-06-18T18:22:54 | TAOUSDT | short | 15m | trend_mode | TREND | TREND | 232.179 | 232.64 | +0.20% | 0.56 | -0.2592 | 0.0523 | 0.0261 | -0.3376 | -19.9 | LOSS | TIER_2_TRAILING_STOP | 2916 | v2h_443d959d8510f869c279d7fcde0908db | v2_fsnap_e7ce0a7 | mstate_fec30f59c4eff | NO_HEDGE | 6 |
| 404 | 2026-06-18T18:22:54 | ADAUSDT | short | 1h | trend_mode | TREND | TREND | 0.160983 | 0.1618 | +0.51% | 540.24 | -0.4415 | 0.0350 | 0.0175 | -0.4940 | -50.8 | LOSS | TIER_2_TRAILING_STOP | 2448 | v2h_02025a1b02cf5de9944fe5e4dcb437c7 | v2_fsnap_1d6bff8 | mstate_a0b587cdf361e | NO_HEDGE | 4 |
| 405 | 2026-06-18T18:22:54 | CRVUSDT | short | 15m | trend_mode | TREND | TREND | 0.218889 | 0.2199 | +0.46% | 292.26 | -0.2954 | 0.0257 | 0.0129 | -0.3339 | -46.2 | LOSS | TIER_2_TRAILING_STOP | 1658 | v2h_2ce325d60b9cf9cecac159b356dd6391 | v2_fsnap_f79b198 | mstate_7ed6f721e37db | NO_HEDGE | 4 |
| 406 | 2026-06-18T18:22:54 | DOTUSDT | short | 5m | trend_mode | TREND | TREND | 0.953447 | 0.957 | +0.37% | 73.46 | -0.2610 | 0.0281 | 0.0141 | -0.3032 | -37.3 | LOSS | TIER_2_TRAILING_STOP | 1658 | v2h_2ba96795c520bfbef36cfdd9702b8564 | v2_fsnap_d8fc94c | mstate_61a3c927225ae | NO_HEDGE | 4 |
| 407 | 2026-06-18T18:22:54 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.76747 | 0.771 | +0.46% | 33.62 | -0.1187 | 0.0104 | 0.0052 | -0.1342 | -46.0 | LOSS | TIER_2_TRAILING_STOP | 867 | v2h_2b59714297a36bb0d689f1130dec17dd | v2_fsnap_86409ec | mstate_9c99b48bd262c | NO_HEDGE | 2 |
| 408 | 2026-06-18T18:25:09 | SUIUSDT | short | 5m | trend_mode | TREND | TREND | 0.715477 | 0.7178 | +0.32% | 175.87 | -0.4086 | 0.0505 | 0.0252 | -0.4843 | -32.5 | LOSS | TIER_2_TRAILING_STOP | 3051 | v2h_0fece22484128815f7001a93aa5793b0 | v2_fsnap_3aa95d1 | mstate_94d4c9e9504b7 | NO_HEDGE | 5 |
| 409 | 2026-06-18T18:25:09 | AAVEUSDT | short | 15m | trend_mode | TREND | TREND | 71.7629 | 71.98 | +0.30% | 1.21 | -0.2631 | 0.0349 | 0.0174 | -0.3154 | -30.2 | LOSS | TIER_2_TRAILING_STOP | 2583 | v2h_20044138425ab8990d0628d5e6cc8024 | v2_fsnap_403a242 | mstate_5a9a34df5540f | NO_HEDGE | 4 |
| 410 | 2026-06-18T18:25:09 | HOMEUSDT | short | 1h | trend_mode | TREND | TREND | 0.027335 | 0.02751 | +0.64% | 1048.82 | -0.1835 | 0.0115 | 0.0058 | -0.2008 | -64.0 | LOSS | TIER_2_TRAILING_STOP | 873 | v2h_3cf227d382ef9a4a58ef7ecdab88e497 | v2_fsnap_ceacea3 | mstate_71ec6c2e68d7f | NO_HEDGE | 2 |
| 411 | 2026-06-18T18:27:18 | AVAXUSDT | short | 4h | trend_mode | TREND | TREND | 6.28037 | 6.306 | +0.41% | 11.86 | -0.3039 | 0.0299 | 0.0150 | -0.3488 | -40.8 | LOSS | TIER_2_TRAILING_STOP | 2584 | v2h_361752437d4cf9688c126afbd9e84b83 | v2_fsnap_7454342 | mstate_02c054df23c6c | NO_HEDGE | 4 |
| 412 | 2026-06-18T18:27:18 | CHZUSDT | short | 4h | trend_mode | TREND | TREND | 0.022377 | 0.02246 | +0.37% | 3040.69 | -0.2524 | 0.0273 | 0.0137 | -0.2934 | -37.1 | LOSS | TIER_2_TRAILING_STOP | 1922 | v2h_22e7b0bdcc8da23aff61cbb0b5163fec | v2_fsnap_f823c2d | mstate_484ff931556e4 | NO_HEDGE | 5 |
| 413 | 2026-06-18T18:27:18 | DASHUSDT | short | 1m | trend_mode | TREND | TREND | 35.0906 | 35.22 | +0.37% | 1.19 | -0.1540 | 0.0168 | 0.0084 | -0.1791 | -36.9 | LOSS | TIER_2_TRAILING_STOP | 1922 | v2h_2133b1d91d7c30871a53f927210a78e4 | v2_fsnap_ca75220 | mstate_0a855066154e0 | NO_HEDGE | 3 |
| 414 | 2026-06-18T18:27:18 | BIOUSDT | short | 15m | trend_mode | TREND | TREND | 0.03635 | 0.03661 | +0.72% | 546.64 | -0.1421 | 0.0080 | 0.0040 | -0.1541 | -71.5 | LOSS | TIER_2_TRAILING_STOP | 330 | v2h_09fea9fd8b1ca054fb919337f2eee92d | v2_fsnap_2f22b50 | mstate_cf35dd38729e5 | NO_HEDGE | 1 |
| 415 | 2026-06-18T18:27:18 | JTOUSDT | short | 4h | trend_mode | TREND | TREND | 0.7068 | 0.7164 | +1.36% | 28.11 | -0.2699 | 0.0081 | 0.0040 | -0.2820 | -135.8 | LOSS | TIER_1_STOP_LOSS | 329 | v2h_266cf731cbc5599b24df3c1611b886af | v2_fsnap_c7fc767 | mstate_6b8036138f6fd | NO_HEDGE | 1 |
| 416 | 2026-06-18T18:31:42 | ESPORTSUSDT | short | 5m | trend_mode | TREND | TREND | 0.0616 | 0.06086 | -1.20% | 264.03 | 0.1954 | 0.0064 | 0.0032 | 0.1857 | 120.1 | WIN | TIER_2_TAKE_PROFIT | 594 | v2h_3958755156f50c0e35faf74cda88b6e8 | v2_fsnap_a3adde4 | mstate_7f8042786bec5 | NO_HEDGE | 1 |
| 417 | 2026-06-18T18:32:48 | ALLOUSDT | short | 1h | trend_mode | TREND | TREND | 0.385712 | 0.38678 | +0.28% | 205.43 | -0.2194 | 0.0318 | 0.0159 | -0.2671 | -27.7 | LOSS | TIER_2_TRAILING_STOP | 3042 | v2h_246c8d83fcfbba02b54bb5011a697b69 | v2_fsnap_0f0cfb4 | mstate_5f84777981a86 | NO_HEDGE | 4 |
| 418 | 2026-06-18T18:32:48 | BCHUSDT | short | 5m | trend_mode | TREND | TREND | 196.277 | 196.93 | +0.33% | 0.44 | -0.2877 | 0.0347 | 0.0174 | -0.3398 | -33.2 | LOSS | TIER_2_TRAILING_STOP | 2914 | v2h_2ccc927096ddddb6848a145366c7c0ff | v2_fsnap_cd4d3e6 | mstate_6ca9d82f7d9a9 | NO_HEDGE | 5 |
| 419 | 2026-06-18T18:32:48 | APTUSDT | short | 1h | trend_mode | TREND | TREND | 0.628521 | 0.632 | +0.55% | 91.06 | -0.3168 | 0.0230 | 0.0115 | -0.3513 | -55.3 | LOSS | TIER_2_TRAILING_STOP | 858 | v2h_a6710bb33bd93a51a278d5f0913ba637 | v2_fsnap_a211bca | mstate_fc707bdf0332c | NO_HEDGE | 3 |
| 420 | 2026-06-18T18:33:52 | HUSDT | short | 15m | trend_mode | TREND | TREND | 0.228031 | 0.22424 | -1.66% | 317.56 | 1.2038 | 0.0285 | 0.0142 | 1.1611 | 166.2 | WIN | TIER_2_TAKE_PROFIT | 1396 | v2h_027ced540a5526f450815da9b9d3a202 | v2_fsnap_9863df3 | mstate_3440f2da783d6 | NO_HEDGE | 4 |
| 421 | 2026-06-18T18:38:12 | ONDOUSDT | short | 1m | trend_mode | TREND | TREND | 0.358087 | 0.3521 | -1.67% | 590.32 | 3.5345 | 0.0831 | 0.0416 | 3.4098 | 167.2 | WIN | TIER_2_TAKE_PROFIT | 3834 | v2h_3e0912b89fab95e7ea16a5150776ec7f | v2_fsnap_73383e4 | mstate_64dd591ebba6f | NO_HEDGE | 8 |
| 422 | 2026-06-18T18:38:12 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.792 | 1.825 | +1.84% | 23.41 | -0.7725 | 0.0171 | 0.0085 | -0.7981 | -184.2 | LOSS | TIER_1_STOP_LOSS | 391 | v2h_dedd7c17e592a7250fdb066f2f3fe5ee | v2_fsnap_1d4b908 | mstate_0666981e92b65 | NO_HEDGE | 2 |
| 423 | 2026-06-18T18:44:09 | ENAUSDT | short | 15m | trend_mode | TREND | TREND | 0.0890331 | 0.09007 | +1.16% | 558.59 | -0.5792 | 0.0201 | 0.0101 | -0.6094 | -116.5 | LOSS | TIER_1_STOP_LOSS | 1341 | v2h_11cca86d1027ee2d6016c4098d218b29 | v2_fsnap_957f669 | mstate_1f563f34ede59 | NO_HEDGE | 2 |
| 424 | 2026-06-18T18:44:49 | HYPEUSDT | short | 1h | trend_mode | TREND | TREND | 68.0383 | 68.133 | +0.14% | 0.78 | -0.0743 | 0.0214 | 0.0107 | -0.1063 | -13.9 | LOSS | TIER_2_TRAILING_STOP | 788 | v2h_05bb0e1f6f5f65fa3a5c93bf51f91a7c | v2_fsnap_f250331 | mstate_e917066f95dd0 | NO_HEDGE | 2 |
| 425 | 2026-06-18T18:44:49 | JTOUSDT | short | 15m | trend_mode | TREND | TREND | 0.718967 | 0.7189 | -0.01% | 100.31 | 0.0068 | 0.0288 | 0.0144 | -0.0365 | 0.9 | LOSS | TIER_2_TRAILING_STOP | 788 | v2h_c14b8f1d55caa3d242342972be8c0f39 | v2_fsnap_06d4c60 | mstate_0f5521237d796 | NO_HEDGE | 3 |
| 426 | 2026-06-18T18:44:49 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0615862 | 0.06177 | +0.30% | 564.56 | -0.1038 | 0.0139 | 0.0070 | -0.1247 | -29.8 | LOSS | TIER_2_TRAILING_STOP | 657 | v2h_2f22ac6fe9e8e9117c04dde029390163 | v2_fsnap_196a273 | mstate_ea62b818a6326 | NO_HEDGE | 2 |
| 427 | 2026-06-18T18:45:57 | ALGOUSDT | short | 1m | trend_mode | TREND | TREND | 0.0992049 | 0.0995 | +0.30% | 636.98 | -0.1880 | 0.0254 | 0.0127 | -0.2260 | -29.7 | LOSS | TIER_2_TRAILING_STOP | 1449 | v2h_464b361c44a394e4980fffe019c4ec11 | v2_fsnap_8a81f59 | mstate_631c429139b34 | NO_HEDGE | 3 |
| 428 | 2026-06-18T18:45:57 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0364844 | 0.03641 | -0.20% | 1976.73 | 0.1471 | 0.0288 | 0.0144 | 0.1039 | 20.4 | WIN | TIER_2_TRAILING_STOP | 856 | v2h_21d78ad9cbd717241fe6bca28c9b4cb5 | v2_fsnap_018645f | mstate_e98e0e9d74fc4 | NO_HEDGE | 3 |
| 429 | 2026-06-18T18:47:01 | HBARUSDT | short | 1h | trend_mode | TREND | TREND | 0.0796877 | 0.07994 | +0.32% | 965.38 | -0.2435 | 0.0309 | 0.0154 | -0.2898 | -31.7 | LOSS | TIER_2_TRAILING_STOP | 2314 | v2h_00a026c679372d7903d49599ddc57422 | v2_fsnap_3518e55 | mstate_2be1564bc9df1 | NO_HEDGE | 4 |
| 430 | 2026-06-18T18:47:01 | HOMEUSDT | short | 4h | trend_mode | TREND | TREND | 0.027532 | 0.02761 | +0.28% | 1848.38 | -0.1442 | 0.0204 | 0.0102 | -0.1748 | -28.3 | LOSS | TIER_2_TRAILING_STOP | 920 | v2h_4952c01f32e12c006677f21b778ed76e | v2_fsnap_b160df7 | mstate_5dcb830278eb5 | NO_HEDGE | 2 |
| 431 | 2026-06-18T18:48:06 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.776 | 1.792 | +0.90% | 8.07 | -0.1292 | 0.0058 | 0.0029 | -0.1378 | -90.1 | LOSS | TIER_1_STOP_LOSS | 130 | v2h_31366b18cafee0d66a695dfbc391217e | v2_fsnap_034b5c6 | mstate_38c38d8d7f97a | NO_HEDGE | 1 |
| 432 | 2026-06-18T18:49:11 | LABUSDT | short | 1m | trend_mode | TREND | TREND | 17.0918 | 16.88 | -1.24% | 2.37 | 0.5019 | 0.0160 | 0.0080 | 0.4779 | 123.9 | WIN | TIER_2_TAKE_PROFIT | 919 | v2h_7eafb59f178c2f6b343cf4803081d7ff | v2_fsnap_9e15fef | mstate_62d29fb5ca048 | NO_HEDGE | 2 |
| 433 | 2026-06-18T18:51:35 | FILUSDT | short | 1m | trend_mode | TREND | TREND | 0.771663 | 0.774 | +0.30% | 100.48 | -0.2349 | 0.0311 | 0.0156 | -0.2815 | -30.3 | LOSS | TIER_2_TRAILING_STOP | 1194 | v2h_44d49689f77cf56cb40ffdb8fccff4fc | v2_fsnap_f3ef5c2 | mstate_ce0f672401fd0 | NO_HEDGE | 3 |
| 434 | 2026-06-18T18:51:35 | MEGAUSDT | short | 5m | trend_mode | TREND | TREND | 0.06118 | 0.06209 | +1.49% | 317.34 | -0.2888 | 0.0079 | 0.0039 | -0.3006 | -148.7 | LOSS | TIER_1_STOP_LOSS | 209 | v2h_75b971190a602564e8c0c0c74e68d39a | v2_fsnap_1587a77 | mstate_d85d9d940ddf8 | NO_HEDGE | 1 |
| 435 | 2026-06-18T18:52:42 | ADAUSDT | short | 15m | trend_mode | TREND | TREND | 0.161876 | 0.1626 | +0.45% | 360.96 | -0.2614 | 0.0235 | 0.0117 | -0.2966 | -44.7 | LOSS | TIER_2_TRAILING_STOP | 1261 | v2h_519a5b3da00a8881c98afd4ff309d440 | v2_fsnap_eac9262 | mstate_9c7e5c5cbb1b8 | NO_HEDGE | 2 |
| 436 | 2026-06-18T18:52:42 | ARBUSDT | short | 4h | trend_mode | TREND | TREND | 0.0824916 | 0.08278 | +0.35% | 646.93 | -0.1866 | 0.0214 | 0.0107 | -0.2187 | -35.0 | LOSS | TIER_2_TRAILING_STOP | 1261 | v2h_2c0ed90c5cd93757f8b2831d2f691d73 | v2_fsnap_9d3e123 | mstate_0cbd3319d4e8d | NO_HEDGE | 2 |
| 437 | 2026-06-18T18:52:42 | HUSDT | short | 4h | trend_mode | TREND | TREND | 0.22807 | 0.22396 | -1.80% | 78.22 | 0.3215 | 0.0070 | 0.0035 | 0.3110 | 180.2 | WIN | TIER_2_PROFIT_BANK | 342 | v2h_10d3570e1b16cb17853664e120632e25 | v2_fsnap_5ecc06b | mstate_7cc1c5f598f29 | NO_HEDGE | 1 |
| 438 | 2026-06-18T19:01:24 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.06213 | 0.06235 | +0.35% | 308.20 | -0.0678 | 0.0077 | 0.0038 | -0.0793 | -35.4 | LOSS | TIER_2_TRAILING_STOP | 194 | v2h_6355cf84e7c459d3b7e68051ba813f66 | v2_fsnap_7287733 | mstate_f433706712f8a | NO_HEDGE | 1 |
| 439 | 2026-06-18T19:03:33 | BEATUSDT | short | 15m | trend_mode | TREND | TREND | 1.795 | 1.814 | +1.06% | 11.25 | -0.2137 | 0.0082 | 0.0041 | -0.2259 | -105.8 | LOSS | TIER_1_STOP_LOSS | 323 | v2h_0806cfbe166747485adf7d56ffd7ec89 | v2_fsnap_bd64d67 | mstate_7c3e5c394f7f4 | NO_HEDGE | 1 |
| 440 | 2026-06-18T19:07:58 | LITUSDT | short | 1h | trend_mode | TREND | TREND | 1.59279 | 1.6023 | +0.60% | 25.89 | -0.2461 | 0.0166 | 0.0083 | -0.2710 | -59.7 | LOSS | TIER_2_TRAILING_STOP | 1258 | v2h_0ee9eb82b7fbfc48d9b6fc00c4a9d624 | v2_fsnap_a97fc6f | mstate_f5d9dba092518 | NO_HEDGE | 2 |
| 441 | 2026-06-18T19:07:58 | NEARUSDT | short | 1h | trend_mode | TREND | TREND | 2.17633 | 2.175 | -0.06% | 22.49 | 0.0298 | 0.0196 | 0.0098 | 0.0005 | 6.1 | WIN | TIER_2_TRAILING_STOP | 1192 | v2h_c1e1848d5dd7cdcb5cc8c83974a38ece | v2_fsnap_f54ab83 | mstate_dbc106d539c11 | NO_HEDGE | 2 |
| 442 | 2026-06-18T19:07:58 | ALGOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0994 | 0.1 | +0.60% | 203.08 | -0.1218 | 0.0081 | 0.0041 | -0.1340 | -60.4 | LOSS | TIER_2_TRAILING_STOP | 588 | v2h_1e20340601a6aa41f0488b6632b4ab33 | v2_fsnap_8f81037 | mstate_977c3bbf653a6 | NO_HEDGE | 1 |
| 443 | 2026-06-18T19:07:58 | BIOUSDT | short | 5m | trend_mode | TREND | TREND | 0.03634 | 0.0369 | +1.54% | 643.76 | -0.3605 | 0.0095 | 0.0048 | -0.3748 | -154.1 | LOSS | TIER_1_STOP_LOSS | 588 | v2h_25ee00cabf6672ef3c912174c1e5e42d | v2_fsnap_beb3852 | mstate_779a3ebd41baf | NO_HEDGE | 1 |
| 444 | 2026-06-18T19:11:19 | FILUSDT | short | 5m | trend_mode | TREND | TREND | 0.771599 | 0.774 | +0.31% | 44.51 | -0.1069 | 0.0138 | 0.0069 | -0.1275 | -31.1 | LOSS | TIER_2_TRAILING_STOP | 531 | v2h_41dd6c1298c6bd50afd6a46570a73a73 | v2_fsnap_45f4561 | mstate_302031aff689b | NO_HEDGE | 2 |
| 445 | 2026-06-18T19:16:45 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.06018 | 0.06125 | +1.78% | 222.44 | -0.2380 | 0.0054 | 0.0027 | -0.2462 | -177.8 | LOSS | TIER_1_STOP_LOSS | 327 | v2h_0c3de27ffd0df918fd53878825a5b381 | v2_fsnap_f224025 | mstate_e3e5db18244fa | NO_HEDGE | 1 |
| 446 | 2026-06-18T19:18:22 | BEATUSDT | short | 15m | trend_mode | TREND | TREND | 1.804 | 1.799 | -0.28% | 7.82 | 0.0391 | 0.0056 | 0.0028 | 0.0307 | 27.7 | WIN | TIER_2_PROFIT_LOCK | 424 | v2h_1b58bfb97731d969012e3ce6d5ab0107 | v2_fsnap_49bfc25 | mstate_0ea1587d7920a | NO_HEDGE | 1 |
| 447 | 2026-06-18T19:23:34 | CRVUSDT | short | 1m | trend_mode | TREND | TREND | 0.219816 | 0.2205 | +0.31% | 423.60 | -0.2896 | 0.0374 | 0.0187 | -0.3457 | -31.1 | LOSS | TIER_2_TRAILING_STOP | 3113 | v2h_1372c9a2f78d072c61864d1c25ec0bbc | v2_fsnap_1744e60 | mstate_40d15b545581f | NO_HEDGE | 4 |
| 448 | 2026-06-18T19:23:34 | AVAXUSDT | short | 4h | trend_mode | TREND | TREND | 6.30322 | 6.317 | +0.22% | 14.24 | -0.1962 | 0.0360 | 0.0180 | -0.2502 | -21.9 | LOSS | TIER_2_TRAILING_STOP | 3047 | v2h_75ebcbcdbfee1f3f5f7478fe7fecc651 | v2_fsnap_a5b24f0 | mstate_4d65e47ad9551 | NO_HEDGE | 4 |
| 449 | 2026-06-18T19:23:34 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.03678 | 0.03726 | +1.31% | 444.66 | -0.2134 | 0.0066 | 0.0033 | -0.2234 | -130.5 | LOSS | TIER_1_STOP_LOSS | 736 | v2h_2c8a3dc6f1c2438c333f0eb5559f44fb | v2_fsnap_d83a453 | mstate_6a5c4a65152ab | NO_HEDGE | 1 |
| 450 | 2026-06-18T19:24:45 | AAVEUSDT | short | 4h | trend_mode | TREND | TREND | 72.0385 | 72.22 | +0.25% | 1.62 | -0.2939 | 0.0468 | 0.0234 | -0.3641 | -25.2 | LOSS | TIER_2_TRAILING_STOP | 3184 | v2h_3497e618f33c1288f8c365577d791a17 | v2_fsnap_eeb109e | mstate_42dca0dff0ec9 | NO_HEDGE | 5 |
| 451 | 2026-06-18T19:24:45 | ADAUSDT | short | 4h | trend_mode | TREND | TREND | 0.16204 | 0.1623 | +0.16% | 359.32 | -0.0934 | 0.0233 | 0.0117 | -0.1283 | -16.0 | LOSS | TIER_2_TRAILING_STOP | 1595 | v2h_189fd4ea609facefea7d9fb4a56434db | v2_fsnap_784bb48 | mstate_39074dcbf5920 | NO_HEDGE | 3 |
| 452 | 2026-06-18T19:25:30 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0605 | 0.05902 | -2.45% | 181.68 | 0.2689 | 0.0043 | 0.0021 | 0.2625 | 244.6 | WIN | TIER_2_PROFIT_BANK | 48 | v2h_003b260aac796552b53db3748acc330d | v2_fsnap_a59da58 | mstate_79429408ba9fb | NO_HEDGE | 1 |
| 453 | 2026-06-18T19:27:10 | AEROUSDT | short | 4h | trend_mode | TREND | TREND | 0.436641 | 0.4381 | +0.33% | 332.46 | -0.4852 | 0.0583 | 0.0291 | -0.5726 | -33.4 | LOSS | TIER_2_TRAILING_STOP | 3922 | v2h_4a0742b06e74aa2d1ea85b21507bdb15 | v2_fsnap_0a3335c | mstate_4292eaa107854 | NO_HEDGE | 7 |
| 454 | 2026-06-18T19:27:10 | INJUSDT | short | 5m | trend_mode | TREND | TREND | 5.14856 | 5.17 | +0.42% | 24.55 | -0.5263 | 0.0508 | 0.0254 | -0.6025 | -41.6 | LOSS | TIER_2_TRAILING_STOP | 3922 | v2h_319e57cf8241f5c33589449530d52c47 | v2_fsnap_686b68a | mstate_bcb5343d8836b | NO_HEDGE | 6 |
| 455 | 2026-06-18T19:27:10 | DOTUSDT | short | 1m | trend_mode | TREND | TREND | 0.957366 | 0.959 | +0.17% | 109.40 | -0.1788 | 0.0420 | 0.0210 | -0.2417 | -17.1 | LOSS | TIER_2_TRAILING_STOP | 3198 | v2h_12def6ff34859a8a6c838d96362d7877 | v2_fsnap_edfb843 | mstate_8a503ce41f564 | NO_HEDGE | 5 |
| 456 | 2026-06-18T19:28:16 | POLUSDT | short | 5m | trend_mode | TREND | TREND | 0.0770797 | 0.07722 | +0.18% | 893.18 | -0.1253 | 0.0276 | 0.0138 | -0.1667 | -18.2 | LOSS | TIER_2_TRAILING_STOP | 2281 | v2h_f6c51a93738d97427eb474d0b1eb6e45 | null | mstate_8a7efd1219a8b | NO_HEDGE | 4 |
| 457 | 2026-06-18T19:29:21 | ICPUSDT | short | 15m | trend_mode | TREND | TREND | 2.23539 | 2.245 | +0.43% | 71.10 | -0.6834 | 0.0639 | 0.0319 | -0.7792 | -43.0 | LOSS | TIER_2_TRAILING_STOP | 4053 | v2h_09c4f0e177d7b607799c108fce41f070 | v2_fsnap_9312ecb | mstate_6aa0242ba6e1f | NO_HEDGE | 7 |
| 458 | 2026-06-18T19:29:21 | APTUSDT | short | 1h | trend_mode | TREND | TREND | 0.6304 | 0.6318 | +0.22% | 121.64 | -0.1703 | 0.0307 | 0.0154 | -0.2164 | -22.2 | LOSS | TIER_2_TRAILING_STOP | 2673 | v2h_01918f011afb07ef52966f918ee28397 | v2_fsnap_db24f14 | mstate_f546254a7da85 | NO_HEDGE | 4 |
| 459 | 2026-06-18T19:29:21 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0824956 | 0.08276 | +0.32% | 644.61 | -0.1704 | 0.0213 | 0.0107 | -0.2024 | -32.0 | LOSS | TIER_2_TRAILING_STOP | 1871 | v2h_543ec3b984b1eb357ec1d8fc0d875e32 | v2_fsnap_eb4dd58 | mstate_e05d6d15fa55b | NO_HEDGE | 3 |
| 460 | 2026-06-18T19:29:21 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.23295 | 0.22939 | -1.53% | 46.37 | 0.1651 | 0.0043 | 0.0021 | 0.1587 | 152.8 | WIN | TIER_2_TAKE_PROFIT | 201 | v2h_0c28c57fba7dc9fad07e5be4358b4451 | v2_fsnap_f91009a | mstate_c5741b5cff0f5 | NO_HEDGE | 1 |
| 461 | 2026-06-18T19:31:37 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.837 | 1.848 | +0.60% | 6.31 | -0.0694 | 0.0047 | 0.0023 | -0.0764 | -59.9 | LOSS | TIER_2_TRAILING_STOP | 415 | v2h_09255435b110e80e3c5a011b7fbdcb38 | v2_fsnap_7611a1e | mstate_f5eddf805bd57 | NO_HEDGE | 1 |
| 462 | 2026-06-18T19:31:37 | BIOUSDT | short | 5m | trend_mode | TREND | TREND | 0.03726 | 0.03767 | +1.10% | 360.41 | -0.1478 | 0.0054 | 0.0027 | -0.1559 | -110.0 | LOSS | TIER_1_STOP_LOSS | 415 | v2h_0e66b00d187bbbd2ad1e207e38401c99 | v2_fsnap_ef9fcfe | mstate_5b9d6afceb314 | NO_HEDGE | 1 |
| 463 | 2026-06-18T19:31:37 | JTOUSDT | short | 4h | trend_mode | TREND | TREND | 0.7403 | 0.7424 | +0.28% | 20.91 | -0.0439 | 0.0062 | 0.0031 | -0.0532 | -28.4 | LOSS | TIER_2_TRAILING_STOP | 202 | v2h_264ae7828390d01c57d3346fc011a990 | v2_fsnap_60d4831 | mstate_de60197f2fb16 | NO_HEDGE | 1 |
| 464 | 2026-06-18T19:33:47 | DASHUSDT | short | 4h | trend_mode | TREND | TREND | 35.1817 | 35.31 | +0.36% | 3.07 | -0.3943 | 0.0434 | 0.0217 | -0.4594 | -36.5 | LOSS | TIER_2_TRAILING_STOP | 3726 | v2h_b6841dd01e91e6795392ee17129b1ae9 | v2_fsnap_152be9c | mstate_227dcff764540 | NO_HEDGE | 6 |
| 465 | 2026-06-18T19:33:47 | LDOUSDT | short | 15m | trend_mode | TREND | TREND | 0.270379 | 0.2722 | +0.67% | 354.99 | -0.6465 | 0.0387 | 0.0193 | -0.7045 | -67.4 | LOSS | TIER_2_TRAILING_STOP | 3531 | v2h_0f25fff26b07774f19f3083696f39e01 | v2_fsnap_f01afd8 | mstate_ae4ac278bd051 | NO_HEDGE | 5 |
| 466 | 2026-06-18T19:33:47 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.02782 | 0.028 | +0.65% | 822.68 | -0.1481 | 0.0092 | 0.0046 | -0.1619 | -64.7 | LOSS | TIER_2_TRAILING_STOP | 1284 | v2h_5098d5aa7b85b72a1823eb199d9a21d8 | v2_fsnap_9e70476 | mstate_c347b6d6c2d6d | NO_HEDGE | 2 |
| 467 | 2026-06-18T19:34:52 | TRXUSDT | short | 4h | trend_mode | TREND | TREND | 0.319131 | 0.31957 | +0.14% | 2613.14 | -1.1478 | 0.3340 | 0.1670 | -1.6489 | -13.8 | LOSS | TIER_2_TRAILING_STOP | 20550 | v2h_0f5d2d5512a99b3f3d176e500d0b2062 | v2_fsnap_899439e | mstate_89633768b79ea | NO_HEDGE | 29 |
| 468 | 2026-06-18T19:35:57 | LABUSDT | short | 5m | trend_mode | TREND | TREND | 17.271 | 17.546 | +1.59% | 0.85 | -0.2351 | 0.0060 | 0.0030 | -0.2441 | -159.2 | LOSS | TIER_1_STOP_LOSS | 462 | v2h_3d2d5596e065d57bfdc31608d43f8178 | v2_fsnap_525ff9e | mstate_67e5dd953ef49 | NO_HEDGE | 1 |
| 469 | 2026-06-18T19:38:14 | ENAUSDT | short | 4h | trend_mode | TREND | TREND | 0.0894844 | 0.08948 | -0.00% | 1192.96 | 0.0053 | 0.0427 | 0.0213 | -0.0588 | 0.5 | LOSS | TIER_2_TRAILING_STOP | 3138 | v2h_4590c17cf26cb67512f8cf2eeb192955 | v2_fsnap_2fc2f97 | mstate_821d16a3ec9fc | NO_HEDGE | 5 |
| 470 | 2026-06-18T19:38:14 | HYPEUSDT | short | 5m | trend_mode | TREND | TREND | 68.2799 | 68.387 | +0.16% | 0.70 | -0.0749 | 0.0191 | 0.0096 | -0.1036 | -15.7 | LOSS | TIER_2_TRAILING_STOP | 734 | v2h_098486b873c9391270c00ab8d41018ea | v2_fsnap_9293764 | mstate_19ae899704092 | NO_HEDGE | 2 |
| 471 | 2026-06-18T19:40:24 | ATOMUSDT | short | 1m | trend_mode | TREND | TREND | 1.78681 | 1.788 | +0.07% | 160.92 | -0.1918 | 0.1151 | 0.0575 | -0.3645 | -6.7 | LOSS | TIER_2_TRAILING_STOP | 9721 | v2h_5ff39347626224d16d9bb020011df26e | v2_fsnap_1a7a85b | mstate_1ea008b6953f4 | NO_HEDGE | 15 |
| 472 | 2026-06-18T19:40:24 | FETUSDT | short | 5m | trend_mode | TREND | TREND | 0.19151 | 0.1921 | +0.31% | 646.55 | -0.3811 | 0.0497 | 0.0248 | -0.4557 | -30.8 | LOSS | TIER_2_TRAILING_STOP | 4123 | v2h_4877099f3177a0e10d39d72191ffbf5a | v2_fsnap_e12f01a | mstate_fcc6c3206c31c | NO_HEDGE | 6 |
| 473 | 2026-06-18T19:40:24 | FILUSDT | short | 4h | trend_mode | TREND | TREND | 0.777092 | 0.779 | +0.25% | 67.29 | -0.1284 | 0.0210 | 0.0105 | -0.1599 | -24.6 | LOSS | TIER_2_TRAILING_STOP | 864 | v2h_3cbd3d83dc2f54dbea56a1b5e633b5ba | v2_fsnap_3de999b | mstate_2db542b1fef4f | NO_HEDGE | 2 |
| 474 | 2026-06-18T19:40:24 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.832 | 1.857 | +1.36% | 17.41 | -0.4352 | 0.0129 | 0.0065 | -0.4546 | -136.5 | LOSS | TIER_1_STOP_LOSS | 131 | v2h_283fa7f7254510cb60ea848319a57e18 | v2_fsnap_061af0d | mstate_a83441c0824f4 | NO_HEDGE | 1 |
| 475 | 2026-06-18T19:42:34 | BCHUSDT | short | 1h | trend_mode | TREND | TREND | 196.941 | 197.8 | +0.44% | 0.50 | -0.4276 | 0.0394 | 0.0197 | -0.4867 | -43.6 | LOSS | TIER_2_TRAILING_STOP | 3466 | v2h_0e53a45ca96b48603242607f5a42d2a4 | v2_fsnap_82ab6df | mstate_d2e043ec08b0e | NO_HEDGE | 5 |
| 476 | 2026-06-18T19:42:34 | ESPORTSUSDT | short | 1m | trend_mode | TREND | TREND | 0.05835 | 0.057 | -2.31% | 518.44 | 0.6999 | 0.0118 | 0.0059 | 0.6822 | 231.4 | WIN | TIER_2_PROFIT_BANK | 261 | v2h_4b569700edff466e036bcfc8d827f502 | v2_fsnap_66030af | mstate_1c8c229613bfa | NO_HEDGE | 1 |
| 477 | 2026-06-18T19:42:34 | HUSDT | short | 1h | trend_mode | TREND | TREND | 0.23043 | 0.22709 | -1.45% | 160.39 | 0.5357 | 0.0146 | 0.0073 | 0.5138 | 144.9 | WIN | TIER_2_TAKE_PROFIT | 261 | v2h_15f2dd9ccc8b3b13e51dd92c6a2a059f | v2_fsnap_ecc77d0 | mstate_3ddea18a34c59 | NO_HEDGE | 1 |
| 478 | 2026-06-18T19:44:52 | BNBUSDT | short | 4h | trend_mode | TREND | TREND | 576.821 | 578.53 | +0.30% | 0.83 | -1.4199 | 0.1922 | 0.0961 | -1.7083 | -29.6 | LOSS | TIER_2_TRAILING_STOP | 12155 | v2h_05db20b1359cc86f6131b99422775aab | v2_fsnap_2662a0b | mstate_ea60e19efaf08 | NO_HEDGE | 21 |
| 479 | 2026-06-18T19:44:52 | CHZUSDT | short | 15m | trend_mode | TREND | TREND | 0.0224048 | 0.02247 | +0.29% | 6248.74 | -0.4075 | 0.0562 | 0.0281 | -0.4918 | -29.1 | LOSS | TIER_2_TRAILING_STOP | 4391 | v2h_439e993accacda747e66ba3082f09517 | v2_fsnap_156ab27 | mstate_e5068e330a35e | NO_HEDGE | 7 |
| 480 | 2026-06-18T19:44:52 | ETCUSDT | short | 4h | trend_mode | TREND | TREND | 7.08709 | 7.129 | +0.59% | 12.33 | -0.5167 | 0.0352 | 0.0176 | -0.5694 | -59.1 | LOSS | TIER_2_TRAILING_STOP | 3536 | v2h_226751b10781e42fb258d24068c11b53 | v2_fsnap_06ed335 | mstate_9e0b8b60abb62 | NO_HEDGE | 5 |
| 481 | 2026-06-18T19:44:52 | CRVUSDT | short | 1h | trend_mode | TREND | TREND | 0.221306 | 0.2223 | +0.45% | 227.68 | -0.2264 | 0.0202 | 0.0101 | -0.2567 | -44.9 | LOSS | TIER_2_TRAILING_STOP | 1210 | v2h_0ee088ad0138a7c1c09910bc3121c6cd | v2_fsnap_35c102f | mstate_e885cfa0f95ce | NO_HEDGE | 2 |
| 482 | 2026-06-18T19:44:52 | AEROUSDT | short | 15m | trend_mode | TREND | TREND | 0.4397 | 0.4435 | +0.86% | 84.05 | -0.3194 | 0.0149 | 0.0075 | -0.3418 | -86.4 | LOSS | TIER_1_STOP_LOSS | 399 | v2h_3d938f4de153dd99a5f89df99756c541 | v2_fsnap_e8dc093 | mstate_4f8ec96414afb | NO_HEDGE | 1 |
| 483 | 2026-06-18T19:44:52 | NEARUSDT | short | 4h | trend_mode | TREND | TREND | 2.182 | 2.203 | +0.96% | 15.97 | -0.3353 | 0.0141 | 0.0070 | -0.3564 | -96.2 | LOSS | TIER_1_STOP_LOSS | 203 | v2h_361d43ff25c5fb82d81c82ab8fe4d5d2 | v2_fsnap_ae67ad7 | mstate_53b8f0a14c36c | NO_HEDGE | 1 |
| 484 | 2026-06-18T19:47:01 | HBARUSDT | short | 4h | trend_mode | TREND | TREND | 0.0798719 | 0.08034 | +0.59% | 835.61 | -0.3911 | 0.0269 | 0.0134 | -0.4314 | -58.6 | LOSS | TIER_2_TRAILING_STOP | 2143 | v2h_0ae3a0f4ff3a557b90c6f9a1be1f8fde | v2_fsnap_22a309a | mstate_4a74054eb0e99 | NO_HEDGE | 3 |
| 485 | 2026-06-18T19:47:01 | AAVEUSDT | short | 15m | trend_mode | TREND | TREND | 72.33 | 73 | +0.93% | 0.56 | -0.3748 | 0.0163 | 0.0082 | -0.3993 | -92.6 | LOSS | TIER_1_STOP_LOSS | 528 | v2h_1fd61eb08f3bdcdecd4233ea3279ebaa | v2_fsnap_8014334 | mstate_b515d1cbd4f8e | NO_HEDGE | 1 |
| 486 | 2026-06-18T19:51:26 | LABUSDT | short | 1h | trend_mode | TREND | TREND | 17.592 | 17.37 | -1.26% | 1.65 | 0.3666 | 0.0115 | 0.0057 | 0.3494 | 126.2 | WIN | TIER_2_TAKE_PROFIT | 597 | v2h_0a2c3bb2cf11408b5954cd7e40b0e30e | v2_fsnap_cbffc41 | mstate_fee5465f14b43 | NO_HEDGE | 1 |
| 487 | 2026-06-18T19:52:31 | PAXGUSDT | short | 15m | trend_mode | TREND | TREND | 4237.84 | 4211.97 | -0.61% | 0.19 | 4.9821 | 0.3245 | 0.1622 | 4.4954 | 61.0 | WIN | TIER_4_MAX_HOLD_TIME | 21609 | v2h_48a95b0d0c0882a02c2a6cd14ec19276 | v2_fsnap_fc68706 | mstate_1e736b5f8bb61 | NO_HEDGE | 28 |
| 488 | 2026-06-18T19:52:31 | SUNUSDT | short | 1m | trend_mode | TREND | TREND | 0.017003 | 0.016937 | -0.39% | 47089.54 | 3.1098 | 0.3190 | 0.1595 | 2.6313 | 38.8 | WIN | TIER_4_MAX_HOLD_TIME | 21609 | v2h_0a29985cc3539ea1883efb6ea9a601f4 | v2_fsnap_ff739b3 | mstate_9332e866fa625 | NO_HEDGE | 28 |
| 489 | 2026-06-18T19:52:59 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.08282 | 0.08365 | +1.00% | 446.25 | -0.3704 | 0.0149 | 0.0075 | -0.3928 | -100.2 | LOSS | TIER_1_STOP_LOSS | 886 | v2h_0507d820dbe055dd50c47294e99dc505 | v2_fsnap_0df5def | mstate_7e380eefbdb9c | NO_HEDGE | 1 |
| 490 | 2026-06-18T19:53:36 | APTUSDT | short | 4h | trend_mode | TREND | TREND | 0.633923 | 0.6355 | +0.25% | 167.10 | -0.2636 | 0.0425 | 0.0212 | -0.3273 | -24.9 | LOSS | TIER_2_TRAILING_STOP | 923 | v2h_041db1e3efda2b062025221c70717a5f | v2_fsnap_5394c3d | mstate_9173057cf4e3e | NO_HEDGE | 2 |
| 491 | 2026-06-18T19:53:36 | ICPUSDT | short | 4h | trend_mode | TREND | TREND | 2.25174 | 2.257 | +0.23% | 51.51 | -0.2707 | 0.0465 | 0.0233 | -0.3405 | -23.3 | LOSS | TIER_2_TRAILING_STOP | 923 | v2h_0a14c72f78c18a7a37f3bb12627ed058 | v2_fsnap_68e6ef4 | mstate_462de799648d1 | NO_HEDGE | 2 |
| 492 | 2026-06-18T19:53:36 | INJUSDT | short | 15m | trend_mode | TREND | TREND | 5.20711 | 5.219 | +0.23% | 17.82 | -0.2118 | 0.0372 | 0.0186 | -0.2676 | -22.8 | LOSS | TIER_2_TRAILING_STOP | 857 | v2h_0c703de4f3d470beb3ff4dfb3544b430 | v2_fsnap_0d7e19f | mstate_b8b210f82213f | NO_HEDGE | 2 |
| 493 | 2026-06-18T19:55:59 | MEGAUSDT | short | 5m | trend_mode | TREND | TREND | 0.0613493 | 0.06191 | +0.91% | 1620.88 | -0.9088 | 0.0401 | 0.0201 | -0.9690 | -91.4 | LOSS | TIER_1_STOP_LOSS | 870 | v2h_08a719a1c09c655af9c797da3ced4d09 | v2_fsnap_19010db | mstate_e7092a61894bf | NO_HEDGE | 2 |
| 494 | 2026-06-18T19:58:10 | AVAXUSDT | short | 4h | trend_mode | TREND | TREND | 6.33937 | 6.358 | +0.29% | 20.62 | -0.3842 | 0.0524 | 0.0262 | -0.4628 | -29.4 | LOSS | TIER_2_TRAILING_STOP | 2008 | v2h_c42d4607cdac94315221d152508ae04a | v2_fsnap_476716d | mstate_14e8622a2efc3 | NO_HEDGE | 3 |
| 495 | 2026-06-18T19:58:10 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.0278302 | 0.02737 | -1.65% | 3629.67 | 1.6702 | 0.0397 | 0.0199 | 1.6106 | 165.3 | WIN | TIER_2_TAKE_PROFIT | 1197 | v2h_06464f50330149bfc56f3b6ac298a455 | v2_fsnap_e876ba5 | mstate_05fe30fd26deb | NO_HEDGE | 2 |
| 496 | 2026-06-18T19:58:10 | JTOUSDT | short | 1h | trend_mode | TREND | TREND | 0.748997 | 0.7538 | +0.64% | 123.89 | -0.5950 | 0.0374 | 0.0187 | -0.6510 | -64.1 | LOSS | TIER_2_TRAILING_STOP | 1131 | v2h_454b117fa273d849813bfbc2a340c1d4 | v2_fsnap_6437842 | mstate_e36f3ce44761b | NO_HEDGE | 2 |
| 497 | 2026-06-18T20:00:22 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.916 | 1.912 | -0.21% | 31.06 | 0.1242 | 0.0238 | 0.0119 | 0.0886 | 20.9 | WIN | TIER_2_TRAILING_STOP | 407 | v2h_86f56297f208189b5d0d8a71448d534d | v2_fsnap_6e33668 | mstate_af6afa6cde424 | NO_HEDGE | 1 |
| 498 | 2026-06-18T20:01:31 | AAVEUSDT | short | 1h | trend_mode | TREND | TREND | 73.07 | 74.16 | +1.49% | 1.03 | -1.1265 | 0.0307 | 0.0153 | -1.1725 | -149.2 | LOSS | TIER_1_STOP_LOSS | 476 | v2h_390dfaf88bba4d36f4c74ea18d7fdca1 | v2_fsnap_fb92d8a | mstate_7d7ce54394fa6 | NO_HEDGE | 1 |
| 499 | 2026-06-18T20:02:36 | ALLOUSDT | short | 4h | trend_mode | TREND | TREND | 0.385771 | 0.3893 | +0.91% | 387.46 | -1.3672 | 0.0603 | 0.0302 | -1.4577 | -91.5 | LOSS | TIER_1_STOP_LOSS | 4668 | v2h_6ec21371bb335cff52b0b0c5910ff9e0 | v2_fsnap_82f16e3 | mstate_b8a5a858cb659 | NO_HEDGE | 6 |
| 500 | 2026-06-18T20:02:36 | ALGOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0999886 | 0.1005 | +0.51% | 1171.14 | -0.5989 | 0.0471 | 0.0235 | -0.6696 | -51.1 | LOSS | TIER_2_TRAILING_STOP | 3079 | v2h_1dbf9dc53256b307d8e8fa5be012683b | v2_fsnap_d4e527a | mstate_075405833e971 | NO_HEDGE | 4 |
| 501 | 2026-06-18T20:02:36 | LITUSDT | short | 15m | trend_mode | TREND | TREND | 1.60774 | 1.6103 | +0.16% | 75.52 | -0.1931 | 0.0486 | 0.0243 | -0.2661 | -15.9 | LOSS | TIER_2_TRAILING_STOP | 2061 | v2h_0862af4e82648697daae15406bea9d1b | v2_fsnap_6019430 | mstate_eb92aeaa04569 | NO_HEDGE | 3 |
| 502 | 2026-06-18T20:02:36 | ADAUSDT | short | 1h | trend_mode | TREND | TREND | 0.16289 | 0.1638 | +0.56% | 712.04 | -0.6478 | 0.0467 | 0.0233 | -0.7178 | -55.9 | LOSS | TIER_2_TRAILING_STOP | 1463 | v2h_09790b0598d93691814fc05cced39a25 | v2_fsnap_1e5f7df | mstate_046ede977ca23 | NO_HEDGE | 2 |
| 503 | 2026-06-18T20:02:36 | DASHUSDT | short | 1h | trend_mode | TREND | TREND | 35.4175 | 35.57 | +0.43% | 2.58 | -0.3935 | 0.0367 | 0.0184 | -0.4486 | -43.1 | LOSS | TIER_2_TRAILING_STOP | 1463 | v2h_0f3822d2debb6dbbab59454359c095f6 | v2_fsnap_f5b1dc0 | mstate_f0ad2991b966d | NO_HEDGE | 2 |
| 504 | 2026-06-18T20:02:36 | DOTUSDT | short | 1m | trend_mode | TREND | TREND | 0.96325 | 0.968 | +0.49% | 120.41 | -0.5720 | 0.0466 | 0.0233 | -0.6419 | -49.3 | LOSS | TIER_2_TRAILING_STOP | 1463 | v2h_035ca3d30c5880934a94276fa052a751 | v2_fsnap_1428ddf | mstate_ca5ee67adadae | NO_HEDGE | 2 |
| 505 | 2026-06-18T20:02:36 | LDOUSDT | short | 1m | trend_mode | TREND | TREND | 0.273093 | 0.2753 | +0.81% | 364.13 | -0.8037 | 0.0401 | 0.0200 | -0.8638 | -80.8 | LOSS | TIER_1_STOP_LOSS | 1267 | v2h_42cbd0ddcbd876289fcfe95d9f2acfce | v2_fsnap_6bc3f88 | mstate_86ae4cec14567 | NO_HEDGE | 2 |
| 506 | 2026-06-18T20:02:36 | ARBUSDT | short | 4h | trend_mode | TREND | TREND | 0.08365 | 0.08403 | +0.45% | 824.54 | -0.3133 | 0.0277 | 0.0139 | -0.3549 | -45.4 | LOSS | TIER_2_TRAILING_STOP | 541 | v2h_38c1b3a54ca5e991fe41901cdbed4c97 | v2_fsnap_080088b | mstate_61304732c1032 | NO_HEDGE | 1 |
| 507 | 2026-06-18T20:02:36 | ENAUSDT | short | 1h | trend_mode | TREND | TREND | 0.09174 | 0.09246 | +0.78% | 751.83 | -0.5413 | 0.0278 | 0.0139 | -0.5830 | -78.5 | LOSS | TIER_2_TRAILING_STOP | 541 | v2h_6b26e744570932d0c8b8eaf600692746 | v2_fsnap_daa781e | mstate_1e7bec2993cf5 | NO_HEDGE | 1 |
| 508 | 2026-06-18T20:02:36 | FILUSDT | short | 5m | trend_mode | TREND | TREND | 0.785 | 0.788 | +0.38% | 96.20 | -0.2886 | 0.0303 | 0.0152 | -0.3341 | -38.2 | LOSS | TIER_2_TRAILING_STOP | 541 | v2h_189c2ff044c105ec66142529c0da1120 | v2_fsnap_69acb40 | mstate_09cd5905befc0 | NO_HEDGE | 1 |
| 509 | 2026-06-18T20:02:36 | NEARUSDT | short | 1h | trend_mode | TREND | TREND | 2.2 | 2.214 | +0.64% | 22.48 | -0.3147 | 0.0199 | 0.0100 | -0.3446 | -63.6 | LOSS | TIER_2_TRAILING_STOP | 332 | v2h_1d4b4d6e3a57d7c02c8d6da452812bb7 | v2_fsnap_13b6232 | mstate_38b73f6a0cf0a | NO_HEDGE | 1 |
| 510 | 2026-06-18T20:04:46 | HYPEUSDT | short | 1h | trend_mode | TREND | TREND | 68.542 | 68.726 | +0.27% | 0.64 | -0.1183 | 0.0177 | 0.0088 | -0.1449 | -26.8 | LOSS | TIER_2_TRAILING_STOP | 605 | v2h_0ce2bdcb2b9e807879fa5933466bd3f8 | v2_fsnap_d4191f8 | mstate_55d3b775c5bc6 | NO_HEDGE | 1 |
| 511 | 2026-06-18T20:06:57 | AEROUSDT | short | 5m | trend_mode | TREND | TREND | 0.445498 | 0.4469 | +0.31% | 298.94 | -0.4192 | 0.0534 | 0.0267 | -0.4994 | -31.5 | LOSS | TIER_2_TRAILING_STOP | 802 | v2h_0ce609157acf43e4498265c75633ecae | v2_fsnap_0e0c2db | mstate_7936bd5177854 | NO_HEDGE | 2 |
| 512 | 2026-06-18T20:06:57 | BCHUSDT | short | 5m | trend_mode | TREND | TREND | 198.617 | 199.23 | +0.31% | 0.58 | -0.3546 | 0.0461 | 0.0231 | -0.4237 | -30.9 | LOSS | TIER_2_TRAILING_STOP | 802 | v2h_14fdb4f07a533096ba906ebcd269250a | v2_fsnap_b0ceef0 | mstate_1deaaf0cd02c2 | NO_HEDGE | 2 |
| 513 | 2026-06-18T20:06:57 | CHZUSDT | short | 4h | trend_mode | TREND | TREND | 0.0225281 | 0.02258 | +0.23% | 5100.74 | -0.2647 | 0.0461 | 0.0230 | -0.3338 | -23.0 | LOSS | TIER_2_TRAILING_STOP | 802 | v2h_3a965ed9a1fd752ca22c7c4995cbbdf0 | v2_fsnap_7c88e19 | mstate_5a312aaf48887 | NO_HEDGE | 2 |
| 514 | 2026-06-18T20:06:57 | CRVUSDT | short | 4h | trend_mode | TREND | TREND | 0.223168 | 0.224 | +0.37% | 596.75 | -0.4962 | 0.0535 | 0.0267 | -0.5764 | -37.3 | LOSS | TIER_2_TRAILING_STOP | 802 | v2h_0236028aa88f048d9e3b6d918cc3ea33 | v2_fsnap_06559ca | mstate_346da271eac7b | NO_HEDGE | 2 |
| 515 | 2026-06-18T20:06:57 | FETUSDT | short | 5m | trend_mode | TREND | TREND | 0.194081 | 0.1946 | +0.27% | 592.07 | -0.3074 | 0.0461 | 0.0230 | -0.3765 | -26.8 | LOSS | TIER_2_TRAILING_STOP | 802 | v2h_0007c5cd95219723f9ea3597d0446fc1 | v2_fsnap_0b98536 | mstate_10cfb13452574 | NO_HEDGE | 2 |
| 516 | 2026-06-18T20:06:57 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.229203 | 0.22991 | +0.31% | 472.45 | -0.3342 | 0.0434 | 0.0217 | -0.3994 | -30.9 | LOSS | TIER_2_TRAILING_STOP | 736 | v2h_06afb7499b1f571b7efa34097cb221e1 | v2_fsnap_736f6da | mstate_8ead4f80227f4 | NO_HEDGE | 2 |
| 517 | 2026-06-18T20:08:05 | BEATUSDT | short | 5m | trend_mode | TREND | TREND | 1.933 | 1.908 | -1.29% | 28.66 | 0.7165 | 0.0219 | 0.0109 | 0.6837 | 129.3 | WIN | TIER_2_TAKE_PROFIT | 70 | v2h_470ca2784090db1ce5601e368796125e | v2_fsnap_e51723c | mstate_7302d3033ff51 | NO_HEDGE | 1 |
| 518 | 2026-06-18T20:09:10 | ESPORTSUSDT | short | 4h | trend_mode | TREND | TREND | 0.0564262 | 0.05529 | -2.01% | 1931.84 | 2.1949 | 0.0427 | 0.0214 | 2.1308 | 201.4 | WIN | TIER_2_PROFIT_BANK | 935 | v2h_302299be80db8574da3d2ef2eca4aa3d | v2_fsnap_431611d | mstate_ff8617768f621 | NO_HEDGE | 2 |
| 519 | 2026-06-18T20:13:31 | BIOUSDT | short | 4h | trend_mode | TREND | TREND | 0.0372855 | 0.03737 | +0.23% | 4562.99 | -0.3856 | 0.0682 | 0.0341 | -0.4879 | -22.7 | LOSS | TIER_2_TRAILING_STOP | 2118 | v2h_0594dfbb2e590d5a2acfcfe19d24a18a | v2_fsnap_c278d80 | mstate_d588df0591b44 | NO_HEDGE | 3 |
| 520 | 2026-06-18T20:13:31 | ENAUSDT | short | 4h | trend_mode | TREND | TREND | 0.09262 | 0.09358 | +1.04% | 693.18 | -0.6655 | 0.0259 | 0.0130 | -0.7044 | -103.6 | LOSS | TIER_1_STOP_LOSS | 396 | v2h_0eec40f605a172f8130c4e8309f688c2 | v2_fsnap_d093ed8 | mstate_27abc9942a35a | NO_HEDGE | 1 |
| 521 | 2026-06-18T20:15:34 | LABUSDT | short | 15m | trend_mode | TREND | TREND | 17.1884 | 16.818 | -2.16% | 8.51 | 3.1514 | 0.0572 | 0.0286 | 3.0655 | 215.5 | WIN | TIER_2_PROFIT_BANK | 1253 | v2h_1310079132f8635588b3b5d7f292eaa1 | v2_fsnap_dcc5b86 | mstate_bb329f13ddfdc | NO_HEDGE | 3 |
| 522 | 2026-06-18T20:21:18 | XAUTUSDT | short | 15m | trend_mode | TREND | TREND | 4222.02 | 4202.29 | -0.47% | 0.19 | 3.7460 | 0.3191 | 0.1596 | 3.2673 | 46.7 | WIN | TIER_4_MAX_HOLD_TIME | 21612 | v2h_530f1461d28cbc9fe001c214cffc0d0a | v2_fsnap_06dc183 | mstate_2de491e3ab0c0 | NO_HEDGE | 27 |
| 523 | 2026-06-18T20:21:18 | AAVEUSDT | short | 15m | trend_mode | TREND | TREND | 74.1357 | 74.32 | +0.25% | 1.65 | -0.3040 | 0.0490 | 0.0245 | -0.3775 | -24.9 | LOSS | TIER_2_TRAILING_STOP | 863 | v2h_265ad1c1d1b0357e42044a392724d932 | v2_fsnap_847c6ab | mstate_1cdd0957515c4 | NO_HEDGE | 2 |
| 524 | 2026-06-18T20:22:23 | JTOUSDT | short | 1h | trend_mode | TREND | TREND | 0.74168 | 0.7417 | +0.00% | 150.58 | -0.0030 | 0.0447 | 0.0223 | -0.0700 | -0.3 | LOSS | TIER_2_TRAILING_STOP | 928 | v2h_01579e045a4d45c84327343c89131af3 | v2_fsnap_103a052 | mstate_7cb76924ab942 | NO_HEDGE | 2 |
| 525 | 2026-06-18T20:24:34 | MEGAUSDT | short | 15m | trend_mode | TREND | TREND | 0.0620441 | 0.06232 | +0.44% | 1535.11 | -0.4236 | 0.0383 | 0.0191 | -0.4810 | -44.5 | LOSS | TIER_2_TRAILING_STOP | 989 | v2h_1769b2d30298a9209f9cfd2c901f662a | v2_fsnap_8e0e950 | mstate_b53e12dee4874 | NO_HEDGE | 2 |
| 526 | 2026-06-18T20:26:49 | NIGHTUSDT | short | 5m | trend_mode | TREND | TREND | 0.031 | 0.03106 | +0.19% | 3905.22 | -0.2343 | 0.0485 | 0.0243 | -0.3071 | -19.4 | LOSS | TIER_2_TRAILING_STOP | 1124 | v2h_083bd7baa9e02468b0f78a8cac78f303 | v2_fsnap_21c522c | mstate_0fd76a45f25b3 | NO_HEDGE | 3 |
| 527 | 2026-06-18T20:27:57 | HBARUSDT | short | 4h | trend_mode | TREND | TREND | 0.0802766 | 0.08068 | +0.50% | 2250.36 | -0.9078 | 0.0726 | 0.0363 | -1.0168 | -50.3 | LOSS | TIER_2_TRAILING_STOP | 2062 | v2h_1b7126c6f08c726d82cca90d7bd12f48 | v2_fsnap_8a4f3f3 | mstate_76a1c97e7a090 | NO_HEDGE | 3 |
| 528 | 2026-06-18T20:27:57 | INJUSDT | short | 4h | trend_mode | TREND | TREND | 5.29185 | 5.327 | +0.66% | 21.10 | -0.7418 | 0.0450 | 0.0225 | -0.8093 | -66.4 | LOSS | TIER_2_TRAILING_STOP | 1262 | v2h_158a6a634f67980d7e58963d98082e55 | v2_fsnap_4902d6c | mstate_db7b9731c0d5d | NO_HEDGE | 2 |
| 529 | 2026-06-18T20:30:06 | ARBUSDT | short | 5m | trend_mode | TREND | TREND | 0.0844373 | 0.08468 | +0.29% | 1322.63 | -0.3210 | 0.0448 | 0.0224 | -0.3882 | -28.7 | LOSS | TIER_2_TRAILING_STOP | 1391 | v2h_1a6dad7a35fedf7e408f6a1a6c7a6d16 | v2_fsnap_b1560a4 | mstate_be3542e54dbb1 | NO_HEDGE | 2 |
| 530 | 2026-06-18T20:30:06 | FILUSDT | short | 5m | trend_mode | TREND | TREND | 0.790849 | 0.796 | +0.65% | 154.62 | -0.7964 | 0.0492 | 0.0246 | -0.8703 | -65.1 | LOSS | TIER_2_TRAILING_STOP | 1391 | v2h_1ec08a08c0c724867e5de71548f3b72f | v2_fsnap_5a39826 | mstate_654b13045a52c | NO_HEDGE | 2 |
| 531 | 2026-06-18T20:30:06 | LITUSDT | short | 4h | trend_mode | TREND | TREND | 1.6214 | 1.6281 | +0.41% | 86.53 | -0.5794 | 0.0564 | 0.0282 | -0.6639 | -41.3 | LOSS | TIER_2_TRAILING_STOP | 1321 | v2h_23a6c4b2ccb823299c9e32778fc52365 | v2_fsnap_e4679bc | mstate_7bdd714723587 | NO_HEDGE | 3 |
| 532 | 2026-06-18T20:32:18 | ETCUSDT | short | 4h | trend_mode | TREND | TREND | 7.17005 | 7.195 | +0.35% | 25.77 | -0.6428 | 0.0742 | 0.0371 | -0.7540 | -34.8 | LOSS | TIER_2_TRAILING_STOP | 2323 | v2h_20d26b755f98a0b9aa1dde18bb4c3eea | v2_fsnap_4771b98 | mstate_c422c1480392a | NO_HEDGE | 4 |
| 533 | 2026-06-18T20:33:31 | NEARUSDT | short | 1h | trend_mode | TREND | TREND | 2.213 | 2.226 | +0.59% | 49.21 | -0.6399 | 0.0438 | 0.0219 | -0.7056 | -58.8 | LOSS | TIER_2_TRAILING_STOP | 1526 | v2h_a7af397d7e2680fea768fd1d902b4cf4 | v2_fsnap_d21c02d | mstate_44fb31f63a9ee | NO_HEDGE | 2 |
| 534 | 2026-06-18T20:33:31 | OPUSDT | short | 5m | trend_mode | TREND | TREND | 0.108845 | 0.1094 | +0.51% | 807.04 | -0.4478 | 0.0353 | 0.0177 | -0.5007 | -51.0 | LOSS | TIER_2_TRAILING_STOP | 1461 | v2h_307766b192d5f18dc3f74f1af86ef512 | v2_fsnap_8228226 | mstate_df91f5c3dda08 | NO_HEDGE | 2 |
| 535 | 2026-06-18T20:34:42 | APTUSDT | short | 1m | trend_mode | TREND | TREND | 0.640394 | 0.6439 | +0.55% | 174.39 | -0.6113 | 0.0449 | 0.0225 | -0.6787 | -54.7 | LOSS | TIER_2_TRAILING_STOP | 1667 | v2h_1def608a7b9186ef988001afbbdc2030 | v2_fsnap_3dc7047 | mstate_633c0854aa173 | NO_HEDGE | 2 |
| 536 | 2026-06-18T20:34:42 | HOMEUSDT | short | 15m | trend_mode | TREND | TREND | 0.0274318 | 0.0273 | -0.48% | 3882.21 | 0.5115 | 0.0424 | 0.0212 | 0.4479 | 48.0 | WIN | TIER_2_TRAILING_STOP | 1667 | v2h_1a462945545f8ffabf70be82a7b255fb | v2_fsnap_49e9dc4 | mstate_d5b76149af865 | NO_HEDGE | 2 |
| 537 | 2026-06-18T20:36:57 | ICPUSDT | short | 1h | trend_mode | TREND | TREND | 2.26844 | 2.265 | -0.15% | 82.89 | 0.2853 | 0.0751 | 0.0375 | 0.1727 | 15.2 | WIN | TIER_2_TRAILING_STOP | 1802 | v2h_102a193be36694ca8015821f5187b41b | v2_fsnap_4d7e587 | mstate_4f80876a4f781 | NO_HEDGE | 3 |
| 538 | 2026-06-18T20:39:14 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.893 | 1.866 | -1.43% | 27.37 | 0.7390 | 0.0204 | 0.0102 | 0.7084 | 142.6 | WIN | TIER_2_TAKE_PROFIT | 138 | v2h_24b90e81e1d64e0f25054460f58c98e0 | v2_fsnap_1ca37df | mstate_df9a9b566e537 | NO_HEDGE | 1 |
| 539 | 2026-06-18T20:41:32 | ALLOUSDT | short | 15m | trend_mode | TREND | TREND | 0.391648 | 0.39248 | +0.21% | 358.90 | -0.2985 | 0.0563 | 0.0282 | -0.3830 | -21.2 | LOSS | TIER_2_TRAILING_STOP | 2077 | v2h_02dfb199c570103ace13aeb2f3b380e5 | v2_fsnap_e3ace95 | mstate_f162b6e32ddf0 | NO_HEDGE | 3 |
| 540 | 2026-06-18T20:41:32 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.05124 | 0.05183 | +1.15% | 959.23 | -0.5659 | 0.0199 | 0.0099 | -0.5958 | -115.1 | LOSS | TIER_1_STOP_LOSS | 276 | v2h_a09aee84a646d047affc70f3c4e45e9e | v2_fsnap_e0176d7 | mstate_1f65fa8014bfe | NO_HEDGE | 1 |
| 541 | 2026-06-18T20:43:43 | AEROUSDT | short | 1h | trend_mode | TREND | TREND | 0.446111 | 0.4477 | +0.36% | 223.69 | -0.3555 | 0.0401 | 0.0200 | -0.4156 | -35.6 | LOSS | TIER_2_TRAILING_STOP | 1280 | v2h_2d079bb25443c908808fd267ade3abba | v2_fsnap_7d93f73 | mstate_a68c7ced58082 | NO_HEDGE | 2 |
| 542 | 2026-06-18T20:55:57 | DOTUSDT | short | 15m | trend_mode | TREND | TREND | 0.970902 | 0.974 | +0.32% | 245.75 | -0.7612 | 0.0957 | 0.0479 | -0.9048 | -31.9 | LOSS | TIER_2_TRAILING_STOP | 2942 | v2h_52cb6c58aa4560438c2222cdf3712645 | v2_fsnap_496b49e | mstate_c509fdf095139 | NO_HEDGE | 4 |
| 543 | 2026-06-18T20:55:57 | 1000FLOKIUSDT | short | 5m | trend_mode | TREND | TREND | 0.02668 | 0.02677 | +0.34% | 1696.88 | -0.1527 | 0.0182 | 0.0091 | -0.1800 | -33.7 | LOSS | TIER_2_TRAILING_STOP | 2080 | v2h_2f03e4762b9c5982c92b7352ba2619f7 | v2_fsnap_1ad2baf | mstate_2fce3520942ae | NO_HEDGE | 1 |
| 544 | 2026-06-18T20:55:57 | BEATUSDT | short | 4h | trend_mode | TREND | TREND | 1.835 | 1.839 | +0.22% | 21.72 | -0.0869 | 0.0160 | 0.0080 | -0.1108 | -21.8 | LOSS | TIER_2_TRAILING_STOP | 273 | v2h_1757da59b394e5e663aef72481f3a7c9 | v2_fsnap_850fa54 | mstate_c6bc5560fda92 | NO_HEDGE | 1 |
| 545 | 2026-06-18T20:57:13 | ONDOUSDT | short | 15m | trend_mode | TREND | TREND | 0.359312 | 0.3606 | +0.36% | 634.93 | -0.8180 | 0.0916 | 0.0458 | -0.9554 | -35.9 | LOSS | TIER_2_TRAILING_STOP | 2948 | v2h_4758af798f66992d1345137b89ea465b | v2_fsnap_fddf16b | mstate_1e0fb091bd79a | NO_HEDGE | 4 |
| 546 | 2026-06-18T21:00:33 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0375621 | 0.03776 | +0.53% | 2828.42 | -0.5598 | 0.0427 | 0.0214 | -0.6238 | -52.7 | LOSS | TIER_2_TRAILING_STOP | 1417 | v2h_2b6a26c8ff85ce37e2f3b7491512cfa1 | v2_fsnap_c1709c3 | mstate_b560e170e96c5 | NO_HEDGE | 2 |
| 547 | 2026-06-18T21:05:01 | HYPEUSDT | short | 1m | trend_mode | TREND | TREND | 68.8682 | 68.957 | +0.13% | 3.16 | -0.2811 | 0.0873 | 0.0436 | -0.4121 | -12.9 | LOSS | TIER_2_TRAILING_STOP | 3486 | v2h_04f0f6c843819f049c9bdccb0b15c8b9 | v2_fsnap_8addaba | mstate_96e990be7c24c | NO_HEDGE | 4 |
| 548 | 2026-06-18T21:05:01 | ALLOUSDT | short | 1h | trend_mode | TREND | TREND | 0.39308 | 0.38741 | -1.44% | 96.19 | 0.5454 | 0.0149 | 0.0075 | 0.5230 | 144.2 | WIN | TIER_2_TAKE_PROFIT | 817 | v2h_0fa9ded5761981bed7f2c69472017c15 | v2_fsnap_c09b50e | mstate_4d0e7c6fe2abb | NO_HEDGE | 1 |
| 549 | 2026-06-18T21:07:12 | ASTERUSDT | short | 5m | trend_mode | TREND | TREND | 0.6396 | 0.6317 | -1.24% | 86.31 | 0.6819 | 0.0218 | 0.0109 | 0.6491 | 123.5 | WIN | TIER_2_TAKE_PROFIT | 2493 | v2h_9f67e022d30ff29ef343148a9c0e1219 | v2_fsnap_b4d1937 | mstate_37dac3de85615 | NO_HEDGE | 1 |
| 550 | 2026-06-18T21:07:12 | ESPORTSUSDT | short | 5m | trend_mode | TREND | TREND | 0.05635 | 0.05714 | +1.40% | 632.36 | -0.4996 | 0.0145 | 0.0072 | -0.5212 | -140.2 | LOSS | TIER_1_STOP_LOSS | 65 | v2h_0d6b264e23e83fa61955ecf489cf8834 | v2_fsnap_a20768d | mstate_9d465fef6700f | NO_HEDGE | 1 |
| 551 | 2026-06-18T21:11:38 | CHZUSDT | short | 15m | trend_mode | TREND | TREND | 0.0224325 | 0.02254 | +0.48% | 5760.99 | -0.6192 | 0.0519 | 0.0260 | -0.6971 | -47.9 | LOSS | TIER_2_TRAILING_STOP | 2082 | v2h_0b7cf859077e2affb4d4737ecbf11914 | v2_fsnap_8b7f5aa | mstate_2bc5908403f27 | NO_HEDGE | 3 |
| 552 | 2026-06-18T21:11:38 | BEATUSDT | short | 4h | trend_mode | TREND | TREND | 1.798 | 1.766 | -1.78% | 20.89 | 0.6685 | 0.0148 | 0.0074 | 0.6464 | 178.0 | WIN | TIER_2_TAKE_PROFIT | 331 | v2h_1bf19b49e0c4ab696f6a28b310d4eecc | v2_fsnap_2d6ee78 | mstate_978230f129caa | NO_HEDGE | 1 |
| 553 | 2026-06-18T21:11:38 | BIOUSDT | short | 1m | trend_mode | TREND | TREND | 0.03744 | 0.03698 | -1.23% | 1162.77 | 0.5349 | 0.0172 | 0.0086 | 0.5091 | 122.9 | WIN | TIER_2_TAKE_PROFIT | 331 | v2h_69a1576061edb048bc64683e8394f241 | v2_fsnap_9dc77b1 | mstate_c1ff751f36c09 | NO_HEDGE | 1 |
| 554 | 2026-06-18T21:13:49 | ENAUSDT | short | 1m | trend_mode | TREND | TREND | 0.0935167 | 0.09203 | -1.59% | 1601.59 | 2.3811 | 0.0590 | 0.0295 | 2.2926 | 159.0 | WIN | TIER_2_TAKE_PROFIT | 2213 | v2h_0ca267c5c22b6bc7158d85541d6b2282 | v2_fsnap_3acb634 | mstate_8cd619c35fca4 | NO_HEDGE | 3 |
| 555 | 2026-06-18T21:13:49 | HYPEUSDT | short | 5m | trend_mode | TREND | TREND | 68.963 | 68.024 | -1.36% | 0.43 | 0.3992 | 0.0116 | 0.0058 | 0.3818 | 136.2 | WIN | TIER_2_TAKE_PROFIT | 332 | v2h_15fe96890dcf246789e0e5e6849962c9 | v2_fsnap_01ec38f | mstate_0ac6fa5e89417 | NO_HEDGE | 1 |
| 556 | 2026-06-18T21:15:47 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.796631 | 0.787 | -1.21% | 180.36 | 1.7372 | 0.0568 | 0.0284 | 1.6520 | 120.9 | WIN | TIER_2_TAKE_PROFIT | 2128 | v2h_763e9619657f71d23bd42872b4e3c603 | v2_fsnap_dbdf0ae | mstate_72f5bd73641b5 | NO_HEDGE | 3 |
| 557 | 2026-06-18T21:18:15 | HOMEUSDT | short | 1h | trend_mode | TREND | TREND | 0.02717 | 0.02741 | +0.88% | 1527.92 | -0.3667 | 0.0168 | 0.0084 | -0.3918 | -88.3 | LOSS | TIER_1_STOP_LOSS | 728 | v2h_02c06a4de8d59df165c56d4a9d6000ad | v2_fsnap_9d687ee | mstate_2df8f2c167f75 | NO_HEDGE | 1 |
| 558 | 2026-06-18T21:22:47 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.05244 | 0.04977 | -5.09% | 618.22 | 1.6506 | 0.0123 | 0.0062 | 1.6322 | 509.2 | WIN | TIER_2_PROFIT_BANK | 73 | v2h_17278b357ef131ce41fdba116efaf895 | v2_fsnap_6044da0 | mstate_6dcac816b62e8 | NO_HEDGE | 1 |
| 559 | 2026-06-18T21:25:09 | ALGOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0995064 | 0.0995 | -0.01% | 2610.59 | 0.0167 | 0.1039 | 0.0520 | -0.1391 | 0.6 | LOSS | TIER_2_TRAILING_STOP | 4694 | v2h_61cc31c7edb8f852c9cf8714ffde830e | v2_fsnap_9515ce5 | mstate_1d4b62f4fdc21 | NO_HEDGE | 6 |
| 560 | 2026-06-18T21:25:09 | CRVUSDT | short | 4h | trend_mode | TREND | TREND | 0.224699 | 0.2247 | +0.00% | 842.83 | -0.0012 | 0.0758 | 0.0379 | -0.1148 | -0.1 | LOSS | TIER_2_TRAILING_STOP | 2893 | v2h_13b22b32f96679fcba13ae4364a40562 | v2_fsnap_f3f7dad | mstate_a1ed54782173b | NO_HEDGE | 4 |
| 561 | 2026-06-18T21:25:09 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.769 | 1.732 | -2.09% | 19.32 | 0.7148 | 0.0134 | 0.0067 | 0.6947 | 209.2 | WIN | TIER_2_PROFIT_BANK | 215 | v2h_3286c1f78baec317fe1f52834e764a35 | v2_fsnap_570114d | mstate_09741194a469e | NO_HEDGE | 1 |
| 562 | 2026-06-18T21:35:04 | AAVEUSDT | short | 15m | trend_mode | TREND | TREND | 74.3444 | 74.33 | -0.02% | 2.79 | 0.0403 | 0.0829 | 0.0415 | -0.0841 | 1.9 | LOSS | TIER_2_TRAILING_STOP | 3488 | v2h_04de1f17fff9854a5885029f10cfd68c | v2_fsnap_71a53e2 | mstate_19bad02bf8b71 | NO_HEDGE | 4 |
| 563 | 2026-06-18T21:35:04 | APTUSDT | short | 15m | trend_mode | TREND | TREND | 0.64044 | 0.6387 | -0.27% | 295.71 | 0.5144 | 0.0755 | 0.0378 | 0.4011 | 27.2 | WIN | TIER_2_TRAILING_STOP | 3488 | v2h_0b43a2ca22894acb9c9cf37d040cb661 | v2_fsnap_5a83741 | mstate_e4eaa1bbdf926 | NO_HEDGE | 4 |
| 564 | 2026-06-18T21:35:04 | FETUSDT | short | 1h | trend_mode | TREND | TREND | 0.195273 | 0.1961 | +0.42% | 754.69 | -0.6244 | 0.0592 | 0.0296 | -0.7132 | -42.4 | LOSS | TIER_2_TRAILING_STOP | 3418 | v2h_3d9e19df6195078d55501edd52802866 | v2_fsnap_2e23600 | mstate_b7bbedb14c714 | NO_HEDGE | 4 |
| 565 | 2026-06-18T21:35:04 | BIOUSDT | short | 15m | trend_mode | TREND | TREND | 0.03696 | 0.03712 | +0.43% | 1071.63 | -0.1715 | 0.0159 | 0.0080 | -0.1953 | -43.3 | LOSS | TIER_2_TRAILING_STOP | 810 | v2h_58fd8b4602c67d271ba5d19f197cc3ba | v2_fsnap_13d88b8 | mstate_067608cc96ecf | NO_HEDGE | 1 |
| 566 | 2026-06-18T21:36:10 | FILUSDT | short | 4h | trend_mode | TREND | TREND | 0.792477 | 0.795 | +0.32% | 108.79 | -0.2745 | 0.0346 | 0.0173 | -0.3264 | -31.8 | LOSS | TIER_2_TRAILING_STOP | 876 | v2h_98e838700388b11294b6f33e03487f0e | v2_fsnap_9e451c8 | mstate_6debe0f2d121c | NO_HEDGE | 2 |
| 567 | 2026-06-18T21:39:32 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.0512 | 0.0491 | -4.10% | 625.55 | 1.3137 | 0.0123 | 0.0061 | 1.2952 | 410.2 | WIN | TIER_2_PROFIT_BANK | 203 | v2h_318684ae675acc03f3869a1d9013f4b8 | v2_fsnap_5f0d2e3 | mstate_1db64caa010f3 | NO_HEDGE | 1 |
| 568 | 2026-06-18T21:43:53 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.728 | 1.723 | -0.29% | 19.54 | 0.0977 | 0.0135 | 0.0067 | 0.0775 | 28.9 | WIN | TIER_2_TRAILING_STOP | 464 | v2h_65abf1c334cdfafe8bbb295412c6c099 | v2_fsnap_87845c8 | mstate_14722fd6134c5 | NO_HEDGE | 1 |
| 569 | 2026-06-18T21:50:35 | HUSDT | short | 5m | trend_mode | TREND | TREND | 0.225595 | 0.22608 | +0.21% | 478.96 | -0.2321 | 0.0433 | 0.0217 | -0.2970 | -21.5 | LOSS | TIER_2_TRAILING_STOP | 2538 | v2h_63cb62f866fe84e5083aa35762e2662f | v2_fsnap_f59e666 | mstate_7a249b0f508dc | NO_HEDGE | 3 |
| 570 | 2026-06-18T21:57:18 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.04307 | 0.04536 | +5.32% | 567.24 | -1.2990 | 0.0103 | 0.0051 | -1.3144 | -531.7 | LOSS | TIER_1_STOP_LOSS | 266 | v2h_16d110baa8182bda5710bd7fb0bcac8e | v2_fsnap_0d2201d | mstate_bae57ef5ff139 | NO_HEDGE | 1 |
| 571 | 2026-06-18T21:57:22 | ENAUSDT | short | 1m | trend_mode | TREND | TREND | 0.0922137 | 0.09222 | +0.01% | 1177.54 | -0.0075 | 0.0434 | 0.0217 | -0.0726 | -0.7 | LOSS | TIER_2_TRAILING_STOP | 2148 | v2h_3e7a9836029c92482390adc04c86c54b | v2_fsnap_58db309 | mstate_5888a28d4c12e | NO_HEDGE | 3 |
| 572 | 2026-06-18T21:57:22 | HYPEUSDT | short | 1m | trend_mode | TREND | TREND | 68.0067 | 68.035 | +0.04% | 1.38 | -0.0391 | 0.0376 | 0.0188 | -0.0956 | -4.2 | LOSS | TIER_2_TRAILING_STOP | 2005 | v2h_32dae29d0bee3ebe39d7bf9f988f52b0 | v2_fsnap_8d32620 | mstate_5e421454d5cf7 | NO_HEDGE | 3 |
| 573 | 2026-06-18T21:57:22 | BIOUSDT | short | 1h | trend_mode | TREND | TREND | 0.0369852 | 0.03709 | +0.28% | 1865.00 | -0.1954 | 0.0277 | 0.0138 | -0.2369 | -28.3 | LOSS | TIER_2_TRAILING_STOP | 1273 | v2h_1662f122fe139b53f5af8d7b116a7ff4 | v2_fsnap_ae0d386 | mstate_915d6e776a1fd | NO_HEDGE | 2 |
| 574 | 2026-06-18T21:57:22 | CRVUSDT | short | 15m | trend_mode | TREND | TREND | 0.225545 | 0.2264 | +0.38% | 305.82 | -0.2613 | 0.0277 | 0.0138 | -0.3029 | -37.9 | LOSS | TIER_2_TRAILING_STOP | 1273 | v2h_5134362650e9bdd383e6eeebedb83c44 | v2_fsnap_acb0d22 | mstate_11678d3f43392 | NO_HEDGE | 2 |
| 575 | 2026-06-18T21:59:33 | ALLOUSDT | short | 15m | trend_mode | TREND | TREND | 0.38744 | 0.3897 | +0.58% | 321.37 | -0.7264 | 0.0501 | 0.0250 | -0.8015 | -58.3 | LOSS | TIER_2_TRAILING_STOP | 3206 | v2h_574e139545d05b2ded1267c2f2f49852 | v2_fsnap_48a399c | mstate_fac017009f924 | NO_HEDGE | 4 |
| 576 | 2026-06-18T22:09:31 | ALICEUSDT | short | 5m | trend_mode | TREND | TREND | 0.1018 | 0.1005 | -1.28% | 394.19 | 0.5125 | 0.0158 | 0.0079 | 0.4887 | 127.7 | WIN | TIER_2_TAKE_PROFIT | 6363 | v2h_f211f585665f43c18d6bfc3e276abbce | v2_fsnap_4bbdaef | mstate_9ffe2278cf730 | NO_HEDGE | 1 |
| 577 | 2026-06-18T22:12:48 | HOMEUSDT | short | 1h | trend_mode | TREND | TREND | 0.0272124 | 0.02688 | -1.22% | 4697.46 | 1.5615 | 0.0505 | 0.0253 | 1.4858 | 122.2 | WIN | TIER_2_TAKE_PROFIT | 3074 | v2h_10c0c731cde84e2377033cc9b659540e | v2_fsnap_2f1f1e5 | mstate_78398861be91e | NO_HEDGE | 4 |
| 578 | 2026-06-18T22:13:55 | BEATUSDT | short | 1h | trend_mode | TREND | TREND | 1.72545 | 1.704 | -1.24% | 27.66 | 0.5934 | 0.0189 | 0.0094 | 0.5652 | 124.3 | WIN | TIER_2_TAKE_PROFIT | 1263 | v2h_0d575bac9356687a53380f509ee63b3c | v2_fsnap_0838ef1 | mstate_9b06a4d74f6f5 | NO_HEDGE | 2 |
| 579 | 2026-06-18T22:14:27 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.04329 | 0.04132 | -4.55% | 481.51 | 0.9486 | 0.0080 | 0.0040 | 0.9366 | 455.1 | WIN | TIER_2_PROFIT_BANK | 369 | v2h_1117059b4e0bbdd850d35dc230d25d15 | v2_fsnap_4e430da | mstate_b174f8fc19bb7 | NO_HEDGE | 1 |
| 580 | 2026-06-18T22:16:10 | AAVEUSDT | short | 1m | trend_mode | TREND | TREND | 74.0477 | 74.17 | +0.17% | 1.40 | -0.1708 | 0.0414 | 0.0207 | -0.2329 | -16.5 | LOSS | TIER_2_TRAILING_STOP | 2401 | v2h_21ea36ac59a179aa5b6b21ab95fd73cf | v2_fsnap_946b4d8 | mstate_cf6699549e638 | NO_HEDGE | 3 |
| 581 | 2026-06-18T22:22:53 | BCHUSDT | short | 4h | trend_mode | TREND | TREND | 199.193 | 196.72 | -1.24% | 1.23 | 3.0409 | 0.0967 | 0.0484 | 2.8958 | 124.2 | WIN | TIER_2_TAKE_PROFIT | 6357 | v2h_0baafa3f04c3ee33c9c8d4d8d5971280 | v2_fsnap_d7c3e1e | mstate_2e8b83b724db9 | NO_HEDGE | 7 |
| 582 | 2026-06-18T22:31:57 | ESPORTSUSDT | short | 1h | trend_mode | TREND | TREND | 0.04122 | 0.04166 | +1.07% | 519.14 | -0.2284 | 0.0087 | 0.0043 | -0.2414 | -106.7 | LOSS | TIER_1_STOP_LOSS | 479 | v2h_2603317506a1f05c1fa3750b50c2a968 | v2_fsnap_005bef0 | mstate_d01d5a0406676 | NO_HEDGE | 1 |
| 583 | 2026-06-18T22:34:09 | HUSDT | short | 1m | trend_mode | TREND | TREND | 0.226696 | 0.22733 | +0.28% | 186.56 | -0.1183 | 0.0170 | 0.0085 | -0.1438 | -28.0 | LOSS | TIER_2_TRAILING_STOP | 1413 | v2h_043b7e08cd60c3d056befaed86e078f3 | v2_fsnap_f9add1c | mstate_0b25c1a906f2e | NO_HEDGE | 2 |
| 584 | 2026-06-18T22:34:09 | BEATUSDT | short | 4h | trend_mode | TREND | TREND | 1.677 | 1.68 | +0.18% | 13.45 | -0.0404 | 0.0090 | 0.0045 | -0.0539 | -17.9 | LOSS | TIER_2_TRAILING_STOP | 611 | v2h_6f9fcad5a2c4b5814c1e2641b2cb0e62 | v2_fsnap_22e8dfc | mstate_cea62d1f9ffcb | NO_HEDGE | 1 |
| 585 | 2026-06-18T22:38:35 | BIOUSDT | short | 5m | trend_mode | TREND | TREND | 0.0368747 | 0.03682 | -0.15% | 1399.59 | 0.0765 | 0.0206 | 0.0103 | 0.0456 | 14.8 | WIN | TIER_2_TRAILING_STOP | 1817 | v2h_68e4c440c78ef1e0bb3abb1c87884c83 | v2_fsnap_c7f2099 | mstate_7f454765451a5 | NO_HEDGE | 2 |
| 586 | 2026-06-18T22:40:47 | ENAUSDT | short | 4h | trend_mode | TREND | TREND | 0.0917081 | 0.0919 | +0.21% | 749.35 | -0.1438 | 0.0275 | 0.0138 | -0.1851 | -20.9 | LOSS | TIER_2_TRAILING_STOP | 1949 | v2h_97984803185a2a30e363d2efa55fa98d | v2_fsnap_aef34a5 | mstate_8f8c8c4b9e322 | NO_HEDGE | 3 |
| 587 | 2026-06-18T22:45:13 | BEATUSDT | short | 1m | trend_mode | TREND | TREND | 1.678 | 1.682 | +0.24% | 8.80 | -0.0352 | 0.0059 | 0.0030 | -0.0441 | -23.8 | LOSS | TIER_2_TRAILING_STOP | 334 | v2h_021b4c16bbcba6ce5997ae755521b2a8 | v2_fsnap_9767d5f | mstate_ba4430c463c0b | NO_HEDGE | 1 |
| 588 | 2026-06-18T22:47:29 | HOMEUSDT | short | 5m | trend_mode | TREND | TREND | 0.026224 | 0.02626 | +0.14% | 1572.91 | -0.0567 | 0.0165 | 0.0083 | -0.0815 | -13.7 | LOSS | TIER_2_TRAILING_STOP | 1411 | v2h_0f3619c65a3c3cf8df45b77800b14254 | v2_fsnap_d25154f | mstate_1cbf3828970fc | NO_HEDGE | 2 |
| 589 | 2026-06-18T22:49:47 | FILUSDT | short | 15m | trend_mode | TREND | TREND | 0.796137 | 0.799 | +0.36% | 108.25 | -0.3099 | 0.0346 | 0.0173 | -0.3618 | -36.0 | LOSS | TIER_2_TRAILING_STOP | 2489 | v2h_188c745d8417561bfad00002b9280771 | v2_fsnap_4a214e8 | mstate_95f029c75e620 | NO_HEDGE | 4 |
| 590 | 2026-06-18T22:49:47 | ESPORTSUSDT | short | 15m | trend_mode | TREND | TREND | 0.04201 | 0.04226 | +0.60% | 180.86 | -0.0452 | 0.0031 | 0.0015 | -0.0498 | -59.5 | LOSS | TIER_2_TRAILING_STOP | 473 | v2h_233de0c1c5e5ed626bc3810a21b66d40 | v2_fsnap_5951979 | mstate_4b247c1f627c9 | NO_HEDGE | 1 |
| 591 | 2026-06-18T22:50:54 | ARBUSDT | short | 4h | trend_mode | TREND | TREND | 0.0846271 | 0.08477 | +0.17% | 3991.82 | -0.5704 | 0.1354 | 0.0677 | -0.7734 | -16.9 | LOSS | TIER_2_TRAILING_STOP | 8038 | v2h_1d25d2e7150f14014596327f754bf39b | v2_fsnap_1883e68 | mstate_8d67631f6c660 | NO_HEDGE | 10 |
| 592 | 2026-06-18T22:50:54 | BCHUSDT | short | 1h | trend_mode | TREND | TREND | 197.055 | 197.94 | +0.45% | 0.19 | -0.1675 | 0.0150 | 0.0075 | -0.1900 | -44.9 | LOSS | TIER_2_TRAILING_STOP | 1616 | v2h_162d9ca0d00e88f016b2112cd185aaaf | v2_fsnap_9f7a627 | mstate_8d35ecafbd65c | NO_HEDGE | 2 |
| 593 | 2026-06-18T22:53:09 | APTUSDT | short | 5m | trend_mode | TREND | TREND | 0.636676 | 0.6388 | +0.33% | 233.14 | -0.4953 | 0.0596 | 0.0298 | -0.5846 | -33.4 | LOSS | TIER_2_TRAILING_STOP | 4620 | v2h_6a16ae94d64dc8f21e28cdf83c677095 | v2_fsnap_e2dbd78 | mstate_0a901ced9f4c7 | NO_HEDGE | 6 |
| 594 | 2026-06-18T22:53:09 | AAVEUSDT | short | 15m | trend_mode | TREND | TREND | 73.8719 | 74.28 | +0.55% | 0.64 | -0.2617 | 0.0190 | 0.0095 | -0.2902 | -55.2 | LOSS | TIER_2_TRAILING_STOP | 1751 | v2h_2fed8af8dc70905d0058859c74be6774 | v2_fsnap_015391c | mstate_2265d8f4edbbc | NO_HEDGE | 2 |
| 595 | 2026-06-18T22:55:19 | 1000SHIBUSDT | short | 5m | trend_mode | TREND | TREND | 0.004741 | 0.004762 | +0.44% | 9997.07 | -0.2099 | 0.0190 | 0.0095 | -0.2385 | -44.3 | LOSS | TIER_2_TRAILING_STOP | 9176 | v2h_c1ce76e530b7a9c6a96c5de52db5287b | v2_fsnap_9c870fd | mstate_586db41ed77b0 | NO_HEDGE | 1 |
