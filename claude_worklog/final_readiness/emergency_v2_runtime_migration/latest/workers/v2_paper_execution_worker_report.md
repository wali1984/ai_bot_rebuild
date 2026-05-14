# v2_paper_execution_worker — worker report

Generated: 2026-05-14T04:40:48Z

## Status

**MIGRATED_AND_RUNNABLE**. The worker is a standalone CLI paper execution
worker and remains a paper-only V2 support path. Live remains
`blocked_human_only`.

## Runnable commands

```text
python3 -m v2.backend.app.cli.v2_paper_execution_worker --once --decision-file ./risk_decision.json
python3 -m v2.backend.app.cli.v2_paper_execution_worker --once
python3 -m v2.backend.app.cli.v2_paper_execution_worker --loop --interval 30
```

## Public payload

Payloads are written to:

- `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
- `v2/runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_status.json`

Required operator fields are present:

- `worker_id`
- `last_fill_ts`
- `fills_processed_total`
- `current_paper_equity`
- `current_paper_pnl`
- `current_gate_state`

Current seeded status is fail-closed because no upstream risk decision payload
was available at generation time:

- `runtime_evidence_status`: `MISSING_RUNTIME_EVIDENCE`
- `current_gate_state`: `blocked_human_only`
- `fills_processed_total`: `0`
- `current_paper_equity`: `10000.0`
- `current_paper_pnl`: `0.0`

## Behavior

- `allow_proceed_long` and `allow_proceed_short` produce paper-only simulated
  fills with deterministic notional, fee, slippage, fill timestamp, fill count,
  and paper PnL/equity impact.
- Denials produce no fill and preserve zero PnL impact.
- Missing or invalid runtime evidence fail-closes with no synthesized trade.
- The worker never opens the live gate and does not call exchange mutation APIs.
- It reads symbol scope from the V2 Symbol Universe service or public payload
  when available.

## Symbol Universe Contract

`SYMBOL_UNIVERSE_CONTRACT_REQUIRED` is emitted. The worker keeps distinct:

- `legacy_active_symbols`
- `discovered_symbols`
- `dynamic_discovered_symbols`
- `observed_symbols`
- `training_symbols`
- `paper_symbols`
- `live_symbols`
- `live_blocked_symbols`

The legacy 25-symbol set is preserved as a scoped subset, not the full universe.
`live_symbols` is empty while live is `blocked_human_only`. CoinAnk symbols are
market-intelligence-only until Binance USD-M confirmation exists.

## Validation

```text
.venv/bin/python3 -m py_compile v2/backend/app/cli/v2_paper_execution_worker.py
.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py -q
```

Result:

```text
28 passed in 0.13s
```

The test suite includes happy long/short fills, no-fill denials, missing and
invalid evidence fail-close, required public payload fields, Symbol Universe
scope separation, bridge-format input, paper trade ID derivation, source-level
no-exchange-client checks, and a fake exchange spy proving the paper path does
not invoke exchange mutation methods.

## Hard-constraint compliance

- Legacy repository mutation: none.
- Old Redis writes: none.
- Exchange actions: none.
- Leverage or margin changes: none.
- Final live approval token: absent.
- Redis trim approval: absent.
- Live gate: `blocked_human_only`.

## Files

- `v2/backend/app/cli/v2_paper_execution_worker.py`
- `v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py`
- `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_report.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_legacy_behavior_mapping.json`
