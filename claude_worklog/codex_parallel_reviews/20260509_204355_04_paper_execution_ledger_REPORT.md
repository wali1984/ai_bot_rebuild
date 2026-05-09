# Paper Execution Ledger MVP Review

Status: BLOCKED for the requested MVP checklist.

## Scope Reviewed

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- relevant risk gateway records/services feeding the ledger
- `v2/backend/tests/unit/domain/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Verification Run

Command:

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/paper_execution_ledger v2/backend/tests/unit/services/paper_execution_ledger v2/backend/tests/unit/composition/paper_execution_ledger -q`

Result: `83 passed in 0.34s`.

The current narrow Phase 2H contract is internally green, but it does not satisfy the broader Paper Execution Ledger MVP checklist in this review request.

## Findings

### Blocker 1: Ledger does not model paper open/close/reduce/hedge/block events

`v2/backend/app/domain/paper_execution_ledger/record.py` only allows two ledger actions: `record_allow` and `record_deny`. The service maps five risk reasons into those two mirror actions. There are no ledger event types or records for `open`, `close`, `reduce`, `hedge`, or `block`.

Evidence:

- `v2/backend/app/domain/paper_execution_ledger/record.py:8-31` defines only `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`, and five mirror risk reasons.
- `v2/backend/app/services/paper_execution_ledger/service.py:59-78` maps risk reasons only to `record_allow` / `record_deny`.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:65-88` explicitly scopes the domain to the two record actions and five mirror reasons.

Impact: the current ledger can prove risk-decision mirroring, but it cannot represent paper execution lifecycle events required by the MVP checklist.

### Blocker 2: No PnL accounting exists in the ledger surface

The ledger record has no price, quantity, fee, slippage, realized PnL, unrealized PnL, or paper PnL fields. The Phase 2H specs explicitly forbid PnL computation in this milestone.

Evidence:

- `v2/backend/app/domain/paper_execution_ledger/record.py:91-103` defines the full `PaperExecutionLedgerEntry` field set; no PnL or fill/accounting field exists.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` constructs only lineage, mirror action/reason, timestamp, and `live_blocked=True`.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:5` says the package does not compute PnL, quantity, price, fees, or slippage.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/19_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC.md:5` repeats that the composition root does not compute PnL, position sizing, quantity, price, fees, or slippage.

Impact: paper close/reduce accounting and aggregate ledger PnL cannot be audited from this implementation.

### Blocker 3: No execution_intent_id linkage

The ledger links `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`, but not `execution_intent_id`. The execution intent domain is still a placeholder.

Evidence:

- `v2/backend/app/domain/paper_execution_ledger/record.py:91-103` has no `execution_intent_id` field.
- `v2/backend/app/domain/execution/intent.py:1` is only a placeholder docstring.
- `v2/backend/app/domain/execution/paper.py:1` is only a placeholder docstring.

Impact: the ledger cannot trace a paper event to the execution intent that caused it, which fails the requested linkage check.

### Blocker 4: Risk decision linkage is present but only at mirror-decision level

The current implementation propagates risk linkage correctly for the narrow mirror record: `risk_decision_id`, `risk_action`, and `risk_reason_code` are carried into the ledger entry and cross-validated. This is a partial pass, not a full MVP pass, because the linkage is not attached to actual paper execution events.

Evidence:

- `v2/backend/app/services/paper_execution_ledger/service.py:80-92` propagates risk lineage and input risk fields.
- `v2/backend/app/domain/paper_execution_ledger/record.py:156-223` enforces action/reason consistency between ledger mirror records and risk decisions.

Impact: useful foundation, but insufficient for open/close/reduce/hedge/block execution ledger auditability.

### Blocker 5: No real exchange actions found in this surface

No real exchange order actions were found in the paper ledger domain/service/composition source. The relevant code has no exchange adapter imports, no Redis writes, no HTTP calls, and no live execution calls.

Evidence:

- `v2/backend/app/composition/paper_execution_ledger/runtime.py:1-27` imports only `Callable`, the paper ledger domain type, the risk decision type, and the assembler service.
- `v2/backend/app/services/paper_execution_ledger/service.py:1-93` performs pure validation and value-object construction only.
- `v2/backend/app/services/execution_router.py:1-4` remains a no-behavior placeholder stating live order calls remain blocked until a later milestone.

Impact: this part passes the safety check; the blocker is missing non-live paper-ledger functionality, not live-exchange leakage.

## Proposed Non-Live Autofix Tasks

1. Add a new non-live paper execution event domain model with explicit event types: `open`, `close`, `reduce`, `hedge`, and `block`; include `execution_intent_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, side, quantity, price, fee, slippage, realized PnL, event timestamp, and `live_blocked=True`.
2. Add pure PnL accounting service tests for long and short open/close, partial reduce, hedge open/close, blocked intent with zero PnL, fees, and deterministic rounding. Keep it free of exchange, Redis, HTTP, and wall-clock access except an injected clock.
3. Add a pure assembler that consumes a validated execution intent plus risk decision and emits paper ledger events without persistence or exchange calls.
4. Add linkage tests proving every event carries both `risk_decision_id` and `execution_intent_id`, and rejects mismatched symbol/lineage inputs.
5. Add forbidden-action tests over the new paper execution packages for `create_order`, `cancel_order`, `set_leverage`, `set_margin`, `ccxt`, exchange clients, Redis writes, HTTP clients, and live-mode enablement tokens.
6. Add fixture-backed lifecycle tests covering at least one full paper trade: open -> reduce -> close, one hedge lifecycle, and one blocked intent.

## Conclusion

The current Phase 2H implementation is a safe, pure, risk-decision mirror ledger. It is not yet a Paper Execution Ledger MVP under the review checklist because it lacks execution lifecycle events, PnL accounting, and execution-intent linkage.
