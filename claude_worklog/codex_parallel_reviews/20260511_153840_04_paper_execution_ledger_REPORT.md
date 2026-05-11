# Paper Execution Ledger MVP Parallel Review

Verdict: BLOCKED

Scope reviewed:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl`

Review mode: static/read-only inspection except for emitting this report pair. I did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart services, did not place/cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets.

## Findings

### Blocker 1 - Ledger does not model paper execution lifecycle events

The implemented ledger taxonomy only supports:
- `record_allow`
- `record_deny`

The only allowed ledger reasons are risk-decision mirror reasons:
- `mirror_allow_proceed_long`
- `mirror_allow_proceed_short`
- `mirror_deny_orchestrator_abstained`
- `mirror_deny_orchestrator_held`
- `mirror_deny_default`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8-30` defines only allow/deny actions and mirror reasons.
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` defines `PaperExecutionLedgerEntry` without execution event type, side, quantity, price, or position lifecycle fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:59-78` maps risk reasons only to `record_allow`/`record_deny`.

This does not satisfy the review requirement for paper open/close/reduce/hedge/block ledger events. It can prove a risk decision was mirrored, but it cannot represent a paper open, close, reduce, hedge, or block execution event as a ledger event.

### Blocker 2 - No PnL accounting exists in the ledger

The ledger entry has no realized PnL, unrealized PnL, fee, slippage, fill price, fill quantity, notional, average entry/exit, or accounting basis fields.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` lists all entry fields and includes no PnL/accounting fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` constructs the ledger entry with lineage and mirror reason only.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md` explicitly states this milestone does not compute PnL, quantity, price, fees, or slippage.

Fixture/proof modules contain synthetic paper PnL strings, but those are proof fixtures, not the `paper_execution_ledger` MVP implementation. They do not provide ledger accounting behavior.

### Blocker 3 - `execution_intent_id` linkage is absent from the ledger entry

Execution-intent schemas and route metadata recognize `execution_intent_id`, but `PaperExecutionLedgerEntry` does not carry it and the service does not derive or require it.

Evidence:
- `v2/backend/app/api/schemas/execution_intent.py:20` defines `execution_intent_id`.
- `v2/backend/app/api/schemas/paper_trade.py:18-22` defines a paper trade ack with lineage, but the current ledger entry is separate from this schema.
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` has no `execution_intent_id` field.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` constructs no `execution_intent_id`.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py:24-25` accepts only a `RiskDecisionRecord` at call time, so there is no intent input available to link.

This fails the requested `execution_intent_id` linkage check.

### Pass - Risk decision linkage is present

The ledger does link back to the risk decision and upstream lineage available on `RiskDecisionRecord`.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:92-96` includes `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-91` copies those fields from the risk decision and mirrors `risk_action` / `risk_reason_code`.

This satisfies risk-decision linkage for the narrow mirror-ledger contract.

### Pass - No real exchange action observed in reviewed ledger layers

The reviewed ledger domain/service/composition code imports no exchange adapters, Redis clients, FastAPI routers, or live order interfaces.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py` imports only dataclasses and its local error.
- `v2/backend/app/services/paper_execution_ledger/service.py` imports only domain records/constants and its local error.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py` only binds an injected clock and calls the assembler.
- Dedicated forbidden-token tests exist for domain, service, and composition layers under `v2/backend/tests/unit/**/paper_execution_ledger/`.

I did not observe place/cancel order calls, leverage/margin mutation, live execution enabling, Redis writes, or service restart/deploy behavior in the reviewed ledger implementation.

## Proposed Non-Live Autofix Tasks

1. Add a non-live `PaperExecutionEvent`/ledger domain model that explicitly supports paper `open`, `close`, `reduce`, `hedge`, and `block` events, preserving `live_blocked=True` invariants and forbidden live-action imports.
2. Add `execution_intent_id` as a required lineage field on paper execution ledger entries and update the assembler boundary so it consumes an intent-linked input rather than only `RiskDecisionRecord`.
3. Add deterministic paper PnL accounting fields and pure calculation helpers for non-live use only: realized PnL, fee, slippage, quantity, fill price, notional, and accounting basis. Keep all inputs explicit; do not use exchange clients or Redis.
4. Add tests proving risk-denied/block decisions create block ledger events with zero realized PnL and preserved risk-decision linkage.
5. Add tests proving allowed paper open/reduce/close/hedge events preserve `risk_decision_id` and `execution_intent_id` and compute deterministic PnL from supplied paper fills only.
6. Add forbidden-token tests for the new event/accounting modules covering exchange clients, order placement/cancel/modify, leverage/margin changes, Redis writes, network clients, schedulers, and live-mode enablement.

## Final Status

CODEX_PARALLEL_REVIEW_BLOCKED
