# Paper Execution Ledger MVP Parallel Review

Review mode: read-only against implementation and tests; no Redis, live service, exchange, order, leverage, margin, or deploy action was performed.

Result: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- `v2/backend/app/domain/execution/paper.py`
- `v2/backend/app/services/paper_loop.py`
- `v2/backend/app/services/execution_router.py`
- `v2/backend/app/api/v1/paper.py`
- focused tests under `v2/backend/tests/unit/**/paper_execution_ledger/`
- non-live and historical proof harnesses under `v2/backend/app/proof/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Findings

### Blocker 1: Typed ledger cannot represent paper open/close/reduce/hedge/block events

`PaperExecutionLedgerEntry` only allows `record_allow` and `record_deny` actions. The allowed constants and frozenset are defined in `v2/backend/app/domain/paper_execution_ledger/record.py:8-30`.

The entry fields are limited to `paper_trade_id`, upstream risk/decision/prediction/feature IDs, symbol, timestamp, mirror action/reason, input risk action/reason, and `live_blocked`; see `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`. There is no `ledger_event_type`, no side, no position action, and no support for `open`, `close`, `reduce`, `hedge`, or `block`.

The assembler maps five risk-gateway reason codes to mirror allow/deny entries only; see `v2/backend/app/services/paper_execution_ledger/service.py:59-78`. The composition root just forwards to that assembler; see `v2/backend/app/composition/paper_execution_ledger/runtime.py:15-27`.

The proof harness emits plain dictionary events for `open`, `close`, `reduce`, and `block` in `v2/backend/app/proof/non_live_operational_proof.py:275-287` and historical fixture events in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:365-376`, but those rows are not constructed from the typed paper execution ledger domain/service. No typed hedge ledger event path was found.

### Blocker 2: PnL accounting is not implemented in the typed ledger

The typed entry has no PnL, quantity, price, fee, slippage, realized PnL, unrealized PnL, cumulative PnL, or position-basis fields; see `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`.

The assembler accepts only a `RiskDecisionRecord` and a clock, then returns a mirror entry; see `v2/backend/app/services/paper_execution_ledger/service.py:26-30` and `v2/backend/app/services/paper_execution_ledger/service.py:80-93`. It cannot calculate or validate PnL for open, reduce, close, hedge, or block events.

The proof harness carries fixture strings such as `paper_pnl` and fixture summary totals in `v2/backend/app/proof/non_live_operational_proof.py:196-219` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:187-222`. That is evidence-harness data, not ledger-level accounting.

### Blocker 3: execution_intent_id linkage is absent from the typed ledger

`PaperExecutionLedgerEntry` does not include `execution_intent_id`; see `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`.

The assembler signature accepts only `decision: RiskDecisionRecord` and `now_ms_clock`; see `v2/backend/app/services/paper_execution_ledger/service.py:26-30`. It has no execution intent input and cannot validate or propagate execution-intent lineage.

The API scaffold acknowledges that paper trades should be lineage-bearing and require `execution_intent_id` in route metadata, but it is scaffold-only; see `v2/backend/app/api/v1/paper.py:11-25`. The proof harness includes `execution_intent_id` in plain dictionaries at `v2/backend/app/proof/non_live_operational_proof.py:196-204` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:365-376`, but that linkage is outside the typed ledger MVP surface.

### Blocker 4: risk-decision linkage exists only for risk mirrors, not execution ledger events

The typed entry does carry `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`; see `v2/backend/app/domain/paper_execution_ledger/record.py:92-97`. The assembler propagates those fields from the risk decision; see `v2/backend/app/services/paper_execution_ledger/service.py:80-91`.

That linkage is currently attached to a mirror allow/deny record, not to a concrete paper execution event. Because the typed ledger lacks event type, execution intent, PnL, side, quantity, and price fields, it cannot explain which risk decision caused a specific paper open, close, reduce, hedge, or block event.

### Non-blocker: no real exchange action path found in the inspected ledger surface

The paper ledger domain/service/composition packages are pure value-object, assembler, and binder code. They import no exchange adapter and expose no order-placement path.

`v2/backend/app/services/execution_router.py` and `v2/backend/app/services/paper_loop.py` are placeholders. `v2/backend/app/domain/execution/paper.py` is also a pure placeholder. The paper route is scaffold-only metadata and OPTIONS; see `v2/backend/app/api/v1/paper.py:1-31`.

Focused inspection found no live order placement, cancellation, leverage/margin mutation, Redis write, live-trading enablement, service restart, or deployment path in the reviewed ledger implementation.

## Proposed Non-Live Autofix Tasks

1. Add a typed non-live paper execution event domain model with explicit `open`, `close`, `reduce`, `hedge`, and `block` event constants. Require `live_blocked=True` and `non_live_only=True`.

2. Add `execution_intent_id` to the paper ledger event model and assembler boundary. Validate it with the same identifier rules used for existing lineage IDs.

3. Add deterministic PnL accounting fields and validation: side, quantity, entry price, event price, realized PnL, cumulative realized PnL, and optional fee/slippage placeholders if required. Keep all calculations pure and fixture/in-memory.

4. Add service tests for each event type, including explicit `hedge` and `block` cases, proving risk-decision linkage and execution-intent linkage are present on every event.

5. Project the proof-harness ledger JSON from typed domain objects instead of standalone dictionaries, while keeping output writes limited to approved non-live artifact paths.

6. Add negative safety tests proving the paper ledger event assembler imports no exchange client, has no create/cancel/order mutation methods, performs no Redis writes, and rejects any caller attempt to set `live_blocked=False` or `non_live_only=False`.

## Decision

The implementation is non-live and safe in the inspected surface, but it is not ready for the Paper Execution Ledger MVP checklist. It should remain blocked until the typed ledger supports paper execution events, PnL accounting, event-level risk linkage, and execution-intent linkage without introducing live side effects.
