# Adaptive Capital / Leverage / Margin Master Audit — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01T22:56:31Z

## System Overview

The adaptive capital allocator is implemented in:
- `v2/backend/app/services/adaptive_capital_allocator/` (8 modules)
- `v2/backend/app/cli/v2_adaptive_capital_productivity_status.py` (13,098 lines — comprehensive status)

## Current Capital State

From paper ledger:
- **Total Open Notional**: $5,826.38
- **Realized PnL**: -$253.49
- **Unrealized PnL**: -$46.14
- **Max Leverage at Gate**: 1.0x (hard cap in live_gate:state)

## Key Questions Answered

### Is System Stuck at 1x Leverage?
**YES — by design.** The live gate sets `max_leverage: 1.0`. This is the paper-mode safety constraint.
The adaptive allocator may compute higher leverage recommendations internally, but they are capped at 1.0x until live gate enables it.

### Is Leverage Recorded?
YES — The risk gateway records effective_leverage, allocated_margin, and recommended_leverage in decision payloads.

### Is Capital Allocation Adaptive?
The allocator service (`adaptive_capital_allocator/allocator.py`) contains:
- `sizing_model.py` — dynamic position sizing
- `risk_budget.py` — risk budget allocation
- `strategy_weights.py` — per-strategy weight assignment
- `counterfactual.py` — counterfactual capital sweep
- `exchange_filters.py` — exchange min notional enforcement
- `contracts.py` — allocation contracts

**In paper mode**: Allocator is constrained to paper-safe sizes (not maximally deployed).

### Why Is Capital Idle / Low?
Three possible reasons:
1. **By design**: max_leverage = 1.0 in paper mode
2. **Risk denials**: All signals currently denied (deny_default) — no new positions opening
3. **Negative PnL context**: System conservatively sized to preserve capital

### Is This a Bug?
- deny_default blocking all paper fills is expected (live gate off)
- But in pure paper mode, paper fills should be able to proceed with ALLOW risk decisions
- Current state: 0 open positions, 0 accepted fills in current cycle
- This suggests paper fills are also being blocked, possibly due to lack of ALLOW risk decisions for paper

### 1000x Feasibility Status
- Not evaluated at this time; negative realized PnL at -$253.49 does not support aggressive scaling
- Capital compounding requires positive expectancy first

### Adaptive Allocator Subsystem Structure

| Module | Purpose |
|--------|---------|
| allocator.py | Main allocation logic |
| sizing_model.py | Dynamic position sizing (confidence-weighted) |
| risk_budget.py | Portfolio risk budget management |
| strategy_weights.py | Per-strategy capital weighting |
| counterfactual.py | Counterfactual capital efficiency sweep |
| exchange_filters.py | Binance min notional / lot size filters |
| explanation.py | Human-readable allocation explanation |
| contracts.py | Allocation data contracts |

## Capital Productivity Status Script
`v2_adaptive_capital_productivity_status.py` at 13,098 lines is the most comprehensive capital analysis script. It computes:
- Return on deployed margin
- Capital utilization by strategy
- Dynamic leverage proof
- Counterfactual sweep results
- Fixed sizing regression test

This script should be run as a one-shot status check to get current capital efficiency metrics.
