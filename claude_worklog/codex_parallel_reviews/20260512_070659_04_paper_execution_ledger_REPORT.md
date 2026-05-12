BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_070659_04_paper_execution_ledger_REPORT.md
# Paper Execution Ledger MVP Review

Verdict: CODEX_PARALLEL_REVIEW_BLOCKED

Scope inspected:
- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- relevant `v2/backend/tests/unit/**/paper_execution_ledger/`
- `v2/backend/app/cli/paper_online_runtime.py`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

Read-only constraints honored. I did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart services, did not place/cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. I did not run pytest because this review mode was read-only and test execution can create cache artifacts.

## Blockers

1. The reusable typed paper ledger does not model paper open/close/reduce/hedge/block events.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8` through `v2/backend/app/domain/paper_execution_ledger/record.py:30` defines only `record_allow`, `record_deny`, and five mirror allow/deny reason codes.
- `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` defines the full `PaperExecutionLedgerEntry` field set. It has no event type, side, quantity, position id, order intent id, entry/exit/mark price, reduce quantity, hedge relation, or block subtype.
- `v2/backend/app/services/paper_execution_ledger/service.py:59` through `v2/backend/app/services/paper_execution_ledger/service.py:78` maps risk reasons only to `record_allow` or `record_deny`.
- The 2H authoring specs explicitly scoped this as a mirror risk-decision record surface: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:65` through `:88`, `11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md:101` through `:110`, and `19_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC.md:77` through `:95`.

Impact: risk allows and denies are auditable, but the ledger cannot prove a paper execution lifecycle. It cannot distinguish a paper open from a close, reduce, hedge, or risk block in the typed MVP surface.

2. PnL accounting is absent from the typed ledger.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `:103` contains no realized PnL, unrealized PnL, equity, fee, slippage, funding, fill price, quantity, notional, average entry, or position basis fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:26` through `:30` accepts only `decision: RiskDecisionRecord` and `now_ms_clock`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80` through `:93` constructs a mirror record from risk-decision lineage only.
- The specs explicitly prohibit PnL/economics in the 2H surfaces: `02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:5`, `11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md:5`, and `19_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC.md:5`.

Impact: the typed ledger cannot be used as the source of truth for paper PnL accounting. `v2/backend/app/cli/paper_online_runtime.py:390` through `:420` has an ad hoc dict with fee-only equity movement and `unrealized_pnl = 0.0`, but that is not integrated with the typed ledger package and does not account for close/reduce/hedge lifecycle PnL.

3. `execution_intent_id` linkage is missing from the typed ledger.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `:103` includes `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`, but no `execution_intent_id`.
- `v2/backend/app/services/paper_execution_ledger/service.py:26` through `:30` has no execution intent input.
- `v2/backend/app/services/paper_execution_ledger/service.py:80` through `:93` derives `paper_trade_id` directly from `risk_decision_id` and cannot validate or propagate execution-intent lineage.
- The CLI-only runtime dict does include `execution_intent_id` at `v2/backend/app/cli/paper_online_runtime.py:397`, but that is a separate ad hoc payload, not the reusable `PaperExecutionLedgerEntry` contract.

Impact: the MVP ledger cannot prove that a paper open/close/reduce/hedge/block event was tied to a specific execution intent. This breaks the requested execution-intent lineage check.

4. Risk decision linkage is only partial.

Evidence:
- Positive: `v2/backend/app/domain/paper_execution_ledger/record.py:92` through `:103` carries `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `input_risk_action`, and `input_risk_reason_code`.
- Positive: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `:92` copies risk-decision lineage and action/reason fields.
- Gap: the ledger mirrors only the risk decision. Because there is no execution intent, event lifecycle, or paper mode flag field, the record cannot prove the full `paper mode -> risk decision -> execution intent -> paper ledger event` chain required for the MVP.

5. No real exchange action was found in the typed 2H ledger path.

Evidence:
- The domain/service/composition ledger packages are pure dataclass/assembler/binder code.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py:15` through `:27` only captures a clock and returns a recorder that calls the pure assembler.
- `PaperExecutionLedgerEntry.live_blocked` must be true by `v2/backend/app/domain/paper_execution_ledger/record.py:151` through `:154`, and the service hard-codes `live_blocked=True` at `v2/backend/app/services/paper_execution_ledger/service.py:92`.
- `v2/backend/app/cli/paper_online_runtime.py:409` through `:411` marks `exchange_order_id=None`, `live_order=False`, and `legacy_redis_write=False` for its ad hoc runtime ledger payload.

This is a pass for the no-real-exchange-action check, but it does not offset the ledger/PnL/linkage blockers above.

## Proposed Non-Live Autofix Tasks

1. Extend `PaperExecutionLedgerEntry` with an explicit paper event taxonomy: `paper_open`, `paper_close`, `paper_reduce`, `paper_hedge`, and `paper_block`, plus side, position id, optional related hedge id, and deterministic block reason fields.

2. Add `execution_intent_id` as a required ledger field and update the assembler to accept a typed execution-intent record or a narrow validated execution-intent value object. Validate that its `risk_decision_id` matches the input risk decision before emitting any ledger entry.

3. Add deterministic paper accounting fields: quantity, notional, fill price, fee, slippage, realized PnL delta, unrealized PnL snapshot, cumulative realized PnL, equity, and position basis. Keep this local-only and pure; no exchange, Redis, or live service calls.

4. Replace or wrap the ad hoc `paper_online_runtime.py` ledger dict with the typed ledger contract so runtime payloads and reusable ledger tests exercise the same schema.

5. Add unit and harness tests for all five event types, execution-intent/risk mismatch rejection, close/reduce realized PnL math, hedge linkage, block events with zero fill/economics, and no exchange/Redis side effects.

END_FILE: claude_worklog/codex_parallel_reviews/20260512_070659_04_paper_execution_ledger_REPORT.md
