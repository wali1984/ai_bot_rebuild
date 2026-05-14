# v2_execution_ledger_worker — worker report

Generated: 2026-05-14T05:01:00Z

## Status

**MIGRATED_AND_RUNNABLE**. The worker is a standalone CLI execution
ledger worker. It is a downstream paper-only subscriber to the V2
paper execution worker. It appends accepted events to a durable
append-only JSONL ledger and exposes a tail in its public_runtime
payload. Live remains `blocked_human_only`.

## Trigger

`codex_review_v2_execution_ledger_worker` on emit.

## Runnable commands

```text
python3 -m v2.backend.app.cli.v2_execution_ledger_worker --once --source-file ./paper_status.json
python3 -m v2.backend.app.cli.v2_execution_ledger_worker --once
python3 -m v2.backend.app.cli.v2_execution_ledger_worker --loop --interval 30 --tail-size 20
```

## Ledger

- Path: `v2/runtime/v2_execution_ledger_worker/latest/paper_events.jsonl`
- Format: one JSON object per line; UTF-8; trailing newline.
- Mode: append-only; never opened in write/truncate mode.
- Dedup: by `event_id == paper_trade_id` (= `"pt_" + risk_decision_id`).
- Empty initial state at seed time; no events recorded yet because the
  upstream paper worker reports `MISSING_RUNTIME_EVIDENCE` at seeding.

## Public payload

Payloads are written to:

- `v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json`
- `v2/runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_execution_ledger_worker_status.json`

Required operator fields are present:

- `worker_id`
- `ledger_file_path`
- `ledger_path_writable`
- `entries_appended_this_run`
- `entries_total`
- `duplicate_skipped`
- `tail` (last N events, default N=20)
- `tail_size`
- `last_appended_event_id`
- `last_appended_ts`
- `current_gate_state`
- `gate_always_blocked_invariant`
- `exchange_call_invariant`
- `live_blocked`
- `runtime_evidence_status`
- `input_risk_action_accepted_set` = `["allow", "deny"]`

Current seeded status is fail-closed because no upstream paper-worker
payload was available at generation time:

- `runtime_evidence_status`: `MISSING_RUNTIME_EVIDENCE`
- `current_gate_state`: `blocked_human_only`
- `entries_total`: `0`
- `tail`: `[]`

## Behavior

- `input_risk_action ∈ {allow, deny}` are accepted; any other action
  fail-closes with `runtime_evidence_status="INVALID_ACTION"`.
- Allow events append a row with `fill_recorded=true`, deterministic
  side/notional/fee/slippage copied from the upstream `simulated_fill`.
- Deny events append a row with `fill_recorded=false`, side=`none`,
  zero notional/fee/slippage — audit-visible.
- Repeat invocations against the same upstream `paper_trade_id` are
  idempotent: the second run sets `duplicate_skipped=true`, appends
  nothing, and does not modify the existing ledger bytes.
- An unwritable ledger directory fail-closes with
  `runtime_evidence_status="UNWRITABLE_LEDGER_DIR"`; no exception
  bubbles out; the status payload is still emitted.
- Upstream `MISSING_RUNTIME_EVIDENCE` propagates through this worker as
  the same status; no event is appended.
- The worker reads symbol scope from the V2 Symbol Universe service or
  public payload when available.

## Symbol Universe Contract

`SYMBOL_UNIVERSE_CONTRACT_REQUIRED` is emitted. The worker keeps
distinct:

- `legacy_active_symbols`
- `discovered_symbols`
- `dynamic_discovered_symbols`
- `observed_symbols`
- `training_symbols`
- `paper_symbols`
- `live_symbols`
- `live_blocked_symbols`

The legacy 25-symbol set is preserved as a scoped subset, not the full
universe. `live_symbols` is empty while live is `blocked_human_only`.
CoinAnk symbols are market-intelligence-only until Binance USD-M
confirmation exists.

## Validation

```text
.venv/bin/python3 -m py_compile v2/backend/app/cli/v2_execution_ledger_worker.py
.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_execution_ledger_worker.py -q
```

Result:

```text
28 passed
```

The test suite includes:

1. append-only invariant (repeat is no-op; bytes preserved)
2. tail payload reflects last N events
3. fail-closed on unwritable ledger directory
4. no-truncation (pre-existing seed lines byte-preserved across runs)
5. worker source never opens ledger in write mode
6. action-set rejection (action outside {allow, deny} → fail-closed)
7. fail-closed on missing source (CLI rc 2)
8. fail-closed when upstream paper worker reports missing evidence
9. required public payload fields present (in status and on disk)
10. gate-always-blocked invariant across allow/deny matrix
11. Symbol Universe contract emitted
12. no real exchange-mutation method names in source
13. no Binance/ccxt/Redis imports / Redis writer calls in source
14. no codepath unblocks the live gate
15. no exchange-client attribute reachable on the worker module
16. event_id == paper_trade_id
17. deny entries appended (audit visibility)
18. tail reflects freshly appended event
19. successful allow/deny/duplicate statuses publish `fail_closed=false`
20. public Symbol Universe payload branch is exercised and preserves
    selected training/paper scopes separately from discovered scope

## Hard-constraint compliance

- Legacy repository mutation: none.
- Old Redis writes: none.
- Exchange actions: none.
- Leverage or margin changes: none.
- Final live approval token: absent.
- Redis trim approval: absent.
- Live gate: `blocked_human_only`.
- Legacy reference reads: yes (paper_trader, base_executor, trader,
  config, monitor_trader_execution under `legacy_reference/`).
- Greenfield decision: this worker fulfils a durable append-only
  ledger responsibility that legacy did not implement (legacy held
  orders in-process and in Redis). The legacy baseline analysis
  documents the legacy state and explains the V2 lift.

## Legacy-first artefacts

- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_execution_ledger_worker_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_execution_ledger_worker_legacy_behavior_mapping.json`

Both files are required by the LEGACY-FIRST MANDATE and were emitted
before the implementation code.
Files emitted. Summary of what was produced:

- **Legacy baseline (mandated first):** `v2_execution_ledger_worker_LEGACY_BASELINE_ANALYSIS.md` + `v2_execution_ledger_worker_legacy_behavior_mapping.json` — cite paper_trader.py:691 (in-process order storage), monitor_trader_execution.py (operator tail view), and document the greenfield decision for the durable append-only JSONL (legacy lacked one; it only had in-process state + `wma:paper:*` Redis).
- **Worker CLI:** `v2/backend/app/cli/v2_execution_ledger_worker.py` — subscribes to the paper execution worker's public status payload, validates `input_risk_action ∈ {allow, deny}`, appends events to `v2/runtime/v2_execution_ledger_worker/latest/paper_events.jsonl` in append-only mode, dedupes by `event_id == paper_trade_id`, exposes last-N tail, fail-closes on unwritable dir / missing evidence / invalid action, keeps live gate `blocked_human_only`, follows Symbol Universe contract.
- **Tests:** `test_v2_execution_ledger_worker.py` — covers all 5 mandated test cases (append-only invariant, tail reflects last N, fail-closed on unwritable dir, no-truncation, action-set rejection) plus parity tests (gate-always-blocked, Symbol Universe contract, source-string contracts, exchange-spy, deny audit visibility, event_id derivation).
- **Seeded ledger:** empty `paper_events.jsonl` at `v2/runtime/v2_execution_ledger_worker/latest/`.
- **Seeded status payloads:** public + worker-status JSON, both showing `MISSING_RUNTIME_EVIDENCE` (no paper-worker output yet) with live gate locked.
- **Worker report:** `v2_execution_ledger_worker_report.md`.
