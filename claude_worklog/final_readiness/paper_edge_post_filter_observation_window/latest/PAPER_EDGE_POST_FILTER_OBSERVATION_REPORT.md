# Paper Edge Post-Filter Observation Report

Generated: `2026-05-15T11:23:25Z`

## Decision

`POST_FILTER_EDGE_PENDING`

This report does not approve live trading, canary trading, or legacy shutdown.

## Current Post-Filter Window

| Metric | Value |
| --- | ---: |
| current cumulative paper PnL | -49.228096 |
| post-filter PnL delta | -0.108096 |
| post-filter fills | 6 |
| post-filter fees | 0.06 |
| fills with expected_move_after_cost | 5 |
| fills with trainer source | 5 |
| fills with feature freshness | 5 |

Post-filter behavior is source-limited and edge remains unproven. The latest strict gate is fail-closed, but the cumulative post-filter window includes earlier fills and the latest stop-loss event, so this cannot be labeled positive edge.

## Safety State

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- old Redis write events in parsed paper JSONL: `0`
- exchange order events in parsed paper JSONL: `0`
- approval token: `absent`

## Remaining Blockers

- `PAPER_EDGE_UNPROVEN`
- `POST_FILTER_FILLS_OBSERVED_LOSS_SOURCE_LIMITED`
- trainer derived evidence still requires explicit operator decision for paper-only shutdown evaluation
- trade permission remains live/canary blocked
