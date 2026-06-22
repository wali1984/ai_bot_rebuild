# Lane C — Risk/Trader Action Parity DENY-Path Report

## Scope

Eight-hour trade readiness sprint, Lane C: verify that the v2 risk_gateway
service exposes legacy-equivalent DENY behavior across at least nine distinct
risk action paths from the legacy trader/risk action ontology
(`claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/trader_risk_action_path_map.json`)
without ever reaching a mutating exchange or old-Redis writer codepath.

The runtime gate stays BLOCKED. The runtime symbols list stays empty. Tests do
not import exchange clients, networking libraries, or invoke any forbidden
mutating callable.

## Test File

`v2/backend/tests/integration/cli/test_v2_risk_trader_action_parity_deny_paths.py`

Tests reuse the actual exported evaluator entry points discovered by reading
the risk_gateway service source directly (no fabricated callables):

| Action path (legacy ontology)                  | V2 entry point                                                                                                   | Status     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------- |
| `kill_switch`                                  | `v2.backend.app.services.risk_gateway.kill_switch.evaluate_kill_switch_state`                                    | COVERED    |
| `halt_manager`                                 | `v2.backend.app.services.risk_gateway.halt_manager.evaluate_halt_state`                                          | COVERED    |
| `reduce_only_latch`                            | `v2.backend.app.services.risk_gateway.reduce_only_latch.evaluate_latch_state`                                    | COVERED    |
| `intelligent_close_guard`                      | `v2.backend.app.services.risk_gateway.intelligent_close_guard.evaluate_close_guard`                              | COVERED    |
| `auto_deleverager`                             | `v2.backend.app.services.risk_gateway.auto_deleverager.evaluate_adl_state`                                       | COVERED    |
| `shared_risk_gate`                             | `v2.backend.app.services.risk_gateway.shared_risk_gate.evaluate_budget_state`                                    | COVERED    |
| `margin_governor`                              | `v2.backend.app.services.risk_gateway.margin_governor.evaluate_margin_state`                                     | COVERED    |
| `phase_controller`                             | `v2.backend.app.services.risk_gateway.phase_controller.evaluate_phase_gate`                                      | COVERED    |
| `adaptive_gate` (toxicity / microstructure)    | `v2.backend.app.services.risk_gateway.adaptive_gate.evaluate_toxicity_block`                                     | COVERED    |
| `orchestrator_hold` (via assemble record)      | `v2.backend.app.services.risk_gateway.assemble_risk_decision_record`                                             | COVERED    |
| `orchestrator_abstain` (via assemble record)   | `v2.backend.app.services.risk_gateway.assemble_risk_decision_record`                                             | COVERED    |
| `fee_ratio_gate`                               | (legacy executor-layer guard; no v2 risk_gateway entry)                                                          | PARITY_GAP |
| `churn_veto`                                   | (legacy lifecycle-layer veto; no v2 risk_gateway entry)                                                          | PARITY_GAP |
| `minimum_hold_time`                            | (paper-runtime hold-seconds field; no v2 risk_gateway evaluator)                                                 | PARITY_GAP |

## Action Path Coverage Summary

- 9 of the 9 required risk_gateway-service action paths are covered with
  positive DENY assertions on the actual exported evaluators.
- 2 additional orchestrator-decision DENY paths
  (`deny_orchestrator_held`, `deny_orchestrator_abstained`) are covered
  through `assemble_risk_decision_record`.
- 3 legacy ontology paths (`fee_ratio_gate`, `churn_veto`,
  `minimum_hold_time`) are flagged as `PARITY_GAP_NOT_FOUND` via
  `pytest.skip` with a clear reason, per the lane charter — these tests
  document the gap without fabricating behavior.

## Non-Mutation Guarantees Asserted in the Test File

- No exchange client import (ccxt / binance / websocket / requests / httpx /
  aiohttp) — verified by an in-file scan assertion.
- No mutating callable tokens (the forbidden order-placement,
  order-cancellation, leverage-change, and margin-type-change legacy method
  names) — verified by an in-file scan assertion using runtime-constructed
  token fragments so the test source itself does not contain the bare
  literals.
- No old-Redis writer call (`.set(`, `.hset(`, `.xadd(`, `.publish(` on
  redis clients) — verified by an in-file scan assertion.
- The runtime-gate sentinel (`blocked_human_only`) and an empty
  runtime-symbols tuple are asserted as test-file invariants and re-asserted
  in the lane status JSON.

## Pytest Result

Command (from repo root): the pytest CLI was invoked under the project venv
against the lane test file with `-q`.

Result:

```
22 passed, 3 skipped in 0.09s
```

- `tests_total = 25`
- `tests_passed = 22`
- `tests_skipped = 3` (all skips are documented PARITY_GAP_NOT_FOUND markers)
- `tests_failed = 0`

## GO/NO-GO

`LANE_C_RISK_TRADER_PARITY_DENY_TESTS_PASS`

- runtime-gate = "blocked_human_only"
- runtime-symbols = []
- approves-runtime = false
- approves-canary = false

This lane does NOT approve runtime trading and does NOT approve canary. It
verifies that the v2 risk_gateway DENY behavior is in place across the
required legacy action paths and that the test surface itself contains no
mutation pathway.
