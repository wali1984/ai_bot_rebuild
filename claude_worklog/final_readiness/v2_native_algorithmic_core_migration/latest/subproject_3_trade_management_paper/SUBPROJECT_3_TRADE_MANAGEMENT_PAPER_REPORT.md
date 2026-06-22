# Subproject 3 — Trade Management Paper Engine Report

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Outcome

Subproject 3 delivered a V2-native paper-only trade management engine that
covers stealth stops, dynamic ATR stops, dynamic TP ladders, churn veto,
fee-ratio gate, and a fail-closed hedge/DCA evaluator.

## Test result

19/19 tests pass under
`v2/backend/tests/integration/cli/test_v2_trade_management_paper_worker.py`.

## Components ported

- `compute_stealth_stop_schedule` with time-decay buffer.
- `compute_dynamic_stop_plan` with ATR fallback.
- `compute_dynamic_take_profit_ladder` with fraction-sum validation.
- `churn_veto` minimum-hold rule.
- `evaluate_fee_ratio_gate` blocking when expected_move_after_cost_bps is
  missing or ratio exceeds max.
- `evaluate_hedge_dca` — explicit `FAIL_CLOSED_STUB`.
- `TradeManagementPaperService.plan_for_position` and `evaluate_pre_trade`.
- CLI worker emits the public status payload.

## Components missing (under contract)

- Full legacy stealth stops state machine.
- Full dynamic TP engine regime-adaptive ladders.
- Full dynamic adaptive stops regime-adaptive distance.
- Adaptive hedge builder, dynamic adaptive hedge, hedge pair coordinator.
- Leg manager, exit coordinator, stealth dynamic integration.
- Live order routing (intentionally fail-closed).

## Migration completion contract classification

`PARTIALLY_MIGRATED` with hedge/DCA `FAIL_CLOSED_STUB`. NOT
`MIGRATED_CODEX_PASS`.

## Safety invariants verified

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live` / `approves_canary` / `approves_legacy_shutdown` /
  `approves_redis_trim`: all `false`
- No old Redis writes.
- No exchange mutation.
- No network IO in tests.

## GO/NO-GO

`SUBPROJECT_3_TRADE_MANAGEMENT_PAPER_PARTIALLY_MIGRATED_PAPER_ONLY`
