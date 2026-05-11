# Paper Execution Ledger MVP Parallel Review

Review mode: read-only against implementation and tests, with only this report artifact written.

Result: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- focused unit tests under `v2/backend/tests/unit/{domain,services,composition}/paper_execution_ledger/`
- non-live proof/replay harnesses under `v2/backend/app/proof/`
- planning artifacts under `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- paper-mode artifacts under `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Findings

### Blocker 1: Ledger domain cannot represent paper open/close/reduce/hedge/block events

The typed `PaperExecutionLedgerEntry` only supports `ledger_action` values `record_allow` and `record_deny`; the allowed set is fixed at `v2/backend/app/domain/paper_execution_ledger/record.py:8-21`.

The dataclass has no field for an execution event type. Its fields are limited to paper/risk/decision/prediction/feature IDs, symbol, timestamp, mirror allow/deny action/reason, input risk action/reason, and `live_blocked`; see `record.py:90-103`.

The service assembler only maps five risk-gateway reasons to mirror allow/deny entries; see `v2/backend/app/services/paper_execution_ledger/service.py:59-78`. There is no branch for `open`, `close`, `reduce`, `hedge`, or `block`.

The proof harness emits fixture events for `open`, `close`, `reduce`, and `block` at `v2/backend/app/proof/non_live_operational_proof.py:275-287`, but those are plain dictionaries produced by `_ledger_event` at `non_live_operational_proof.py:351-360`, not instances of the MVP ledger domain or service.

No concrete hedge ledger event is emitted. Search found hedge-unwind scenarios and tests, but no `ledger_event_type == "hedge"` support in the typed ledger or proof event set.

### Blocker 2: PnL accounting is not implemented in the typed ledger

The real domain entry has no PnL field; see `record.py:90-103`. The assembler returns that object directly with no accounting inputs or calculation; see `service.py:80-93`.

The planning specs explicitly state that Phase 2H does not compute PnL, quantity, price, fees, or slippage. The non-live proof harness carries `paper_pnl` as fixture strings, e.g. base lineage at `non_live_operational_proof.py:196-219`, gross fixture PnL at `non_live_operational_proof.py:263-273`, and historical event PnL copied from fixture values at `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:365-376`.

This is insufficient for the review check "PnL accounting" because there is no typed accounting model, realized/unrealized distinction, fees/slippage handling, signed numeric validation, reduce/close accounting, or tests proving ledger-level sums.

### Blocker 3: execution_intent_id linkage is absent from the typed ledger

`PaperExecutionLedgerEntry` does not include `execution_intent_id`; see `record.py:90-103`.

The assembler accepts only a `RiskDecisionRecord` plus a clock; see `service.py:26-30`. It cannot link an execution intent because no intent record or ID is accepted, validated, or propagated.

Fixture proof rows include `execution_intent_id` in plain dictionaries at `non_live_operational_proof.py:196-204` and historical proof events at `historical_30d_replay_and_paper_proof.py:365-376`, but the actual paper execution ledger MVP type cannot carry it.

### Blocker 4: risk decision linkage is present but only for mirror allow/deny, not execution events

The typed ledger does carry `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`; see `record.py:92-97` and the assembler propagation at `service.py:80-91`.

However, because the entry has no execution event type, PnL fields, quantity/price fields, or execution intent linkage, this risk linkage cannot currently explain a concrete paper open/close/reduce/hedge/block event. It only records that a risk decision was mirrored as allow or deny.

### Non-blocker: no real exchange action path found in inspected implementation

The focused paper ledger domain/service/composition packages are pure value-object/assembler/binder code. The composition root only closes over a clock and forwards to the assembler at `v2/backend/app/composition/paper_execution_ledger/runtime.py:15-27`.

A forbidden live-action token scan over the focused paper ledger implementation, proof harnesses, and focused tests found no literal `create_order`, `cancel_order`, `change_leverage`, `change_margin`, `LIVE_TRADING_ENABLED`, `redis-cli`, `XADD`, `XDEL`, `FLUSHDB`, or `FLUSHALL`.

## Proposed Non-Live Autofix Tasks

1. Add a typed non-live paper execution event model, separate from exchange execution, with an explicit enum or constants for `open`, `close`, `reduce`, `hedge`, and `block`. Require `live_blocked=True` and `non_live_only=True`.

2. Extend the assembler boundary to accept a validated execution intent reference or explicit `execution_intent_id`, and propagate it into every paper ledger event. Keep the function pure and dependency-injected; do not add Redis, exchange adapters, API routes, or persistence.

3. Add deterministic PnL accounting fields with numeric validation for paper events: side, quantity, entry price, event price, realized PnL, cumulative realized PnL, fee/slippage placeholders if required by the spec, and reduce/close accounting rules. Keep all inputs fixture/in-memory and non-live.

4. Add service tests proving each event type can be assembled and linked to `risk_decision_id` and `execution_intent_id`, including explicit `hedge` and `block` cases.

5. Replace or supplement the proof-harness plain dict ledger rows with typed paper ledger event construction, then assert the emitted JSON is a projection of validated domain objects.

6. Add negative safety tests proving paper event assembly has no exchange client, no order-placement method, no leverage/margin mutation path, no Redis write path, and rejects any caller attempt to set `live_blocked=False`.

## Decision

The implementation is safe/non-live in the inspected surface, but it is not ready for the Paper Execution Ledger MVP checklist as stated. It should remain blocked until the typed ledger supports paper execution events, PnL accounting, risk-decision linkage at the event level, and execution-intent linkage without live side effects.
