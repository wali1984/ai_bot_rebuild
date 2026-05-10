BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260510_181535_04_paper_execution_ledger_REPORT.md
# Codex Parallel Review - Paper Execution Ledger MVP

Status: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl`

Safety posture:
- No live exchange action path found in the paper execution ledger domain/service/composition source.
- The implementation hard-codes `live_blocked=True` at assembly time and validates that ledger entries cannot be constructed with `live_blocked=False`.
- The composition root only captures an injected clock and forwards a `RiskDecisionRecord`; it does not place/cancel orders, change leverage/margin, import Redis, persist ledger state, or call exchange adapters.

Concrete blockers:

1. Ledger event taxonomy does not cover the requested MVP events.
   - Required review surface: paper open, close, reduce, hedge, and block ledger events.
   - Actual domain constants are limited to `record_allow` and `record_deny` actions plus five mirror risk reasons: `mirror_allow_proceed_long`, `mirror_allow_proceed_short`, `mirror_deny_orchestrator_abstained`, `mirror_deny_orchestrator_held`, and `mirror_deny_default`.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:8` through `v2/backend/app/domain/paper_execution_ledger/record.py:30`.
   - Impact: close/reduce/hedge/block outcomes cannot be represented as first-class paper execution ledger events. Existing lab hedge unwind tests collapse close and reduce into the same mirror-allow sequence, so they do not prove distinct paper close/reduce semantics.

2. PnL accounting is absent.
   - `PaperExecutionLedgerEntry` has identifiers, symbol, timestamp, action/reason, input risk action/reason, and `live_blocked`; it has no quantity, side, entry price, exit/fill price, fees, slippage, realized PnL, unrealized PnL, or position state fields.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103`.
   - The milestone safety docs explicitly forbid PnL, position sizing, quantity, price, fees, and slippage in this phase.
   - Evidence: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md:111` through `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md:127`.
   - Impact: the ledger cannot audit paper execution accounting or validate realized/unrealized PnL.

3. `execution_intent_id` linkage is missing.
   - The ledger entry does not carry `execution_intent_id`.
   - The assembler accepts only `decision: RiskDecisionRecord` and `now_ms_clock`; it derives `paper_trade_id` from `risk_decision_id` and copies risk/decision/prediction/feature identifiers.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:26` through `v2/backend/app/services/paper_execution_ledger/service.py:93`.
   - The composition recorder accepts only `decision`.
   - Evidence: `v2/backend/app/composition/paper_execution_ledger/runtime.py:15` through `v2/backend/app/composition/paper_execution_ledger/runtime.py:27`.
   - Impact: a paper ledger entry cannot be joined directly to an execution intent, despite `execution_intent_id` existing in the API schema.

4. Risk decision linkage is present but too narrow for execution ledger accountability.
   - Present: `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `input_risk_action`, and `input_risk_reason_code` are propagated from `RiskDecisionRecord`.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `v2/backend/app/services/paper_execution_ledger/service.py:92`.
   - Missing: linkage from risk allow/deny to a concrete paper execution intent/fill/position transition.
   - Impact: the current implementation records a risk mirror decision, not a paper execution ledger event.

5. Existing tests validate the narrow mirror-risk ledger, not the requested MVP ledger.
   - Unit tests cover `record_allow`/`record_deny`, risk reason mirroring, timestamp validation, frozen records, non-live import boundaries, and live-blocked enforcement.
   - I found no paper execution ledger tests proving distinct open/close/reduce/hedge/block event construction, PnL accounting, or `execution_intent_id` propagation.

Proposed non-live autofix tasks:

1. Extend the paper execution ledger domain with a non-live `PaperExecutionLedgerEvent` or compatible expansion that includes:
   - `execution_intent_id`
   - `event_type` with at least `open`, `close`, `reduce`, `hedge`, `block`
   - side/direction, quantity, fill price, fees, slippage, realized PnL, unrealized PnL or position snapshot fields as required by the paper accounting contract
   - existing lineage fields: `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`
   - `live_blocked=True` invariant

2. Add a pure paper accounting assembler that accepts already-approved risk decision data plus an execution intent and deterministic paper fill/position inputs. It must compute PnL in-memory only, return typed records, and avoid Redis, exchange adapters, HTTP, service restarts, order placement, leverage, margin, or live trading switches.

3. Add tests for:
   - distinct open, close, reduce, hedge, and block event creation
   - realized PnL on close/reduce
   - unrealized/position snapshot accounting after open/hedge
   - block events carrying risk denial linkage without fills
   - `execution_intent_id` propagation
   - no import or token use for exchange order placement, Redis writes, leverage/margin mutation, or live enablement

4. Add a projection/integration harness that joins `RiskDecisionRecord -> ExecutionIntent -> PaperExecutionLedgerEvent` and asserts the full lineage survives through paper-mode evidence without performing any real exchange action.

Review decision:
- BLOCKED for the requested Paper Execution Ledger MVP because the current implementation is a safe, narrow risk-decision mirror ledger, not a paper execution/accounting ledger with first-class paper event semantics.
END_FILE: claude_worklog/codex_parallel_reviews/20260510_181535_04_paper_execution_ledger_REPORT.md
