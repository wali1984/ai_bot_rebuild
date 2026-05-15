# Risk / Trader Parity Blocker Packet

Generated: 2026-05-15
Source: V2 Permanent Migration Fix and Professional Frontend Runtime Readiness.

## Inputs

- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/trader_risk_action_path_map.json`
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/v2_parity_gap_matrix.json`
- `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/next_remediation_tasks_for_claude.json`
- `v2/backend/app/services/risk_gateway/service.py`

## State

The parity matrix records `FULLY_MIGRATED=0` across all workers. Risk/trader-side
items are split across `PARTIALLY_MIGRATED`, `BLOCKED_BY_TRAINER_PARITY`,
`MISSING_IN_V2`, `FAIL_CLOSED_STUB`, and `NEEDS_TEST` classifications.

`next_remediation_tasks_for_claude.json` lists nine outstanding risk action paths
that require coverage by `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map`:

- kill switch
- halt manager
- reduce-only latch
- intelligent close guard
- auto deleverager
- shared risk gate
- margin governor
- phase controller
- adaptive/microstructure toxicity gate
- fee ratio gate
- churn veto
- minimum hold time
- dynamic stop simulation
- dynamic TP simulation
- stealth stop simulation
- hedge/DCA fail-closed paper-only behavior

## Contract obligations

Until each of the above action paths has a V2 test exercising legacy-equivalent
behavior (clause 7), a public runtime payload showing the path is engaged
(clause 8), and a Codex PASS (clause 9), the risk gateway worker is classified
`PARTIALLY_MIGRATED`. It is NOT `MIGRATED_CODEX_PASS`.

Every mutating exchange action path remains fail-closed. The default execution
adapter (`v2_default_blocked_execution_adapter`) blocks all order placement,
cancellation, modification, leverage change, and margin-mode change paths.

## What this packet does not do

- It does not authorize live trading.
- It does not authorize canary trading.
- It does not enable hedge/DCA.
- It does not enable ADJUST_LEVERAGE.
- It does not modify the legacy trader or trainer state.
- It does not write to old Redis.

## What the router does with this packet

The permanent objective router publishes the action paths above as a P0 blocker
under id `RISK_TRADER_ACTION_PARITY_INCOMPLETE` when the count of
`NEEDS_TEST + NEEDS_CODE_PORT + PARTIALLY_MIGRATED` items is greater than zero.
The matching remediation task id is
`claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map`.
