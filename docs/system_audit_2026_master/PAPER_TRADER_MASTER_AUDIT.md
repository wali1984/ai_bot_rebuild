# Paper Trader Master Audit — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01T22:56:31Z

## How the Paper Trader Works

The primary paper trader is **v2_trade_management_paper_loop** (service: ai-bot-v2-trade-management-paper-loop.service).

It is the **sole paper owner** as of 2026-06-27 (paper_online_runtime.py was disabled on that date).

## Runtime Status (from `v2:paper:heartbeat`)

```json
{
  "worker_id": "v2_trade_management_paper_loop",
  "schema_version": "v2_trade_management_paper_heartbeat_v2",
  "cycle_state": "RUNNING_CYCLE",
  "paper_only": true,
  "routes_to_live": false,
  "places_real_order": false,
  "writes_legacy_redis": false,
  "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
  "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
  "current_allowed_paper_owner": "challenger_v2",
  "canonical_paper_writer_count": 1,
  "forbidden_entry_process_count": 0
}
```

## Paper Ledger Status (from `v2:paper:ledger`)

| Metric | Value |
|--------|-------|
| accepted_count (total fills) | 456 |
| blocked_count | 462 |
| closed_trade_count | 743 |
| outcome_label_count | 754 |
| trainer_feedback_total_row_count | 741 |
| **trainer_feedback_quarantined_row_count** | **741 (CRITICAL: 100%)** |
| **trainer_feedback_consumable_row_count** | **0 (CRITICAL: NONE)** |
| realized_pnl_usd | -253.49 |
| unrealized_pnl_usd | -46.14 |
| total_open_notional | $5,826.38 |
| open_position_count | 0 |
| held_by_paper_fill_gate_count | 0 |

## Critical Finding — Trainer Feedback Fully Quarantined

**741 of 741 feedback rows are quarantined (100%). Zero rows are consumable by trainer.**

This means the paper trading outcomes are not feeding the trainer for learning. The feedback loop is broken at the quarantine level. This is a **P0 blocker** for training improvement.

Likely causes:
- Outcome labels missing required fields (outcome_label incomplete)
- Forward window not completed (trades closed before future window evaluated)
- Quarantine predicate rejecting all rows (timestamp or data quality check failing)

## How Paper Trader Simulates Fills

1. Reads orchestrator decisions from `v2:signals:paper`
2. Checks paper fill gate (intents may be held)
3. Simulates fill at current mark price (from `v2:market:kline:{sym}:1m`)
4. Applies fee model (taker fee ~0.04%), slippage model
5. Records fill in `v2:paper:ledger`
6. Manages position lifecycle (LONG / SHORT open → hold → close)

## Trade Lifecycle

### LONG
1. OPEN: Buy at mark + slippage; debit fee
2. HOLD: MTM at mark price; unrealized PnL tracked
3. CLOSE: Sell on exit signal or stop/TP; realize PnL

### SHORT
1. OPEN: Sell at mark - slippage; debit fee
2. HOLD: MTM at mark price; unrealized PnL tracked
3. CLOSE: Buy on exit signal or stop/TP; realize PnL (shown in sample: TIER_2_TAKE_PROFIT exit)

## PnL Accounting
- **Realized PnL**: -$253.49 (current run)
- **Unrealized PnL**: -$46.14
- **Total Open Notional**: $5,826.38
- Fees deducted per trade
- Funding: tracked via CoinAnk funding rate data

## Outcome Labels and Trainer Feedback
- Paper trader writes `v2:paper:outcome_labels` (754 rows)
- Writes `v2:paper:closed_trades` (743 rows)
- Feedback loop converts these to `v2:trainer:feedback:outcomes`
- **CURRENT STATUS**: 741 of 741 rows quarantined; 0 consumable
- **Impact**: Trainer is not receiving paper trade feedback

## Same-Symbol Netting / Reduce/Close/Flip
- Same symbol: existing position is closed before new position opens (netting enforced)
- Reduce mode: partial close if new signal reduces exposure
- Flip: if LONG and SHORT signal arrives, closes LONG and opens SHORT (or vice versa)

## Strategy Attribution
- All trades attributed to `challenger_v2_cuda_exitless` policy
- policy_fingerprint: 83d35e31...
- paper_policy_owner: challenger_v2

## Safety Invariants
- `places_real_order`: false
- `routes_to_live`: false
- `writes_legacy_redis`: false
- `canonical_paper_writer_count`: 1 (no duplicate owners)
- `forbidden_entry_process_count`: 0
