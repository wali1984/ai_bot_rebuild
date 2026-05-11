# Codex Risk Gateway Degraded-State Fail-Closed Boundary Review

## Scope

Read-only parallel Codex review of risk-gateway and degraded-state fail-closed boundaries. The review challenged stale/missing attribution handling, confidence requirements, duplicate execution identifiers, margin/leverage observations, kill-switch behavior, and paths that could bypass the risk gateway.

Safety constraints honored: no edits under `/home/wali/Desktop/AI BOT`; no Redis access; no exchange order placement, cancellation, or mutation; no leverage, margin, or position-mode change; no live execution enablement.

## Verdict

FAIL.

No live order execution path was found, and `/api/v1/live/**` is default-denied. However, the risk gateway itself is not enforcing the stated fail-closed policy. It currently maps upstream orchestrator actions to allow/deny without required gate inputs for attribution, duplicate exchange order IDs, margin/leverage state, kill-switch state, stop-policy state, or degraded-source fail-closed state.

## Findings

1. `assemble_risk_decision_record` allows tradable orchestrator decisions by action mapping alone.
   - `v2/backend/app/services/risk_gateway/service.py:25` accepts only `decision` and `now_ms_clock`.
   - `v2/backend/app/services/risk_gateway/service.py:49` maps `open_long` directly to `allow_proceed_long`.
   - `v2/backend/app/services/risk_gateway/service.py:52` maps `open_short` directly to `allow_proceed_short`.
   - This does not enforce the required blocks listed in `requirements/04_RISK_GATEWAY_REQUIREMENTS.md:3`, including missing attribution/signal/confidence, stale risk-add signals, CROSS margin in live mode, leverage cap, duplicate exchange order ID, missing stop policy, disabled kill switch, and adjust-leverage behavior.

2. Degraded-state fail-closed is observational after the risk decision, not an enforcing gate before allow.
   - `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:14` takes an already-built `RiskDecisionRecord`.
   - `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:37` derives `fail_closed` from stale/missing source states.
   - `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:45` returns a separate `DegradedStateRecord`; it does not convert an upstream `allow` risk decision into `deny`.
   - `v2/backend/app/services/paper_execution_ledger/service.py:26` records from `RiskDecisionRecord` directly, so a risk `allow` can bypass the later degraded-state observation.

3. Duplicate/provenance handling is also downstream and does not deny risk.
   - `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:9` takes an existing `RiskDecisionRecord`.
   - `v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py:24` tracks dedupe state as a separate record.
   - The dedupe model tracks `duplicate_of_decision_id`, not `exchange_order_id` or `execution_intent_id`, and it does not feed back into risk denial.

4. Confidence fail-closed is upstream-only, not enforced by the risk gateway.
   - `v2/backend/app/services/orchestrator_decision/service.py:92` abstains on low confidence before risk.
   - `v2/backend/app/domain/risk_gateway/record.py:56` has no confidence fields.
   - The risk gateway has no threshold or missing-confidence input, so it cannot independently fail closed if a bad or stale upstream decision reaches it.

5. Margin/leverage and kill switch are not implemented as risk-gateway gates.
   - `v2/backend/app/domain/risk/kill_switch.py:1` is a placeholder.
   - `v2/backend/app/domain/risk/policy_bundle.py:1` and `v2/backend/app/domain/risk/live_readiness_state.py:1` are placeholders.
   - `v2/backend/app/api/v1/risk.py:14` is route metadata only.
   - `v2/backend/app/domain/risk_gateway/record.py:56` exposes no margin mode, leverage cap, position mode, stop-policy, adjust-leverage, kill-switch, or policy-bundle state.

6. API execution intent boundary is not implemented beyond schema/metadata.
   - `v2/backend/app/api/schemas/execution_intent.py:15` admits executable intent fields including `qty`, `order_type`, and `mode`.
   - `v2/backend/app/api/v1/intents.py:34` exposes only an OPTIONS metadata shim; there is no POST path enforcing risk-gateway ordering.
   - This is not live-executable today, but the boundary remains unimplemented.

## Positive Controls Observed

1. Live HTTP routes are default-denied before handlers.
   - `v2/backend/app/api/middleware/live_block_guard.py:40` blocks `/api/v1/live` and `/api/v1/live/**` with HTTP 403.
   - `v2/backend/app/main.py:124` constructs the app with middleware registration and order assertion.

2. Exchange adapters are non-executable placeholders.
   - `v2/backend/app/adapters/exchanges/binance/__init__.py`, `bybit/__init__.py`, `okx/__init__.py`, and `generic_ccxt/__init__.py` contain no executable order methods.
   - The proof-only read-only exchange data plane blocks mutation method names in `v2/backend/app/proof/readonly_market_exchange_data_plane.py`.

3. Paper/live-block domain records require `live_blocked=True`.
   - `v2/backend/app/domain/risk_gateway/record.py:214` rejects non-true `live_blocked`.
   - `v2/backend/app/domain/paper_execution_ledger/record.py:151` requires paper ledger entries to remain live-blocked.
   - `v2/backend/app/domain/degraded_state_fail_closed_gates/degraded_state_record.py:156` requires degraded-state records to remain live-blocked.

## Verification

Attempted focused local pytest command:

`python -m pytest v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/domain/degraded_state_fail_closed_gates v2/backend/tests/unit/services/degraded_state_fail_closed_gates v2/backend/tests/unit/composition/degraded_state_fail_closed_gates v2/backend/tests/unit/domain/provenance_dedupe_attribution v2/backend/tests/unit/services/provenance_dedupe_attribution v2/backend/tests/unit/composition/provenance_dedupe_attribution v2/backend/tests/contract/test_middleware_order.py`

Result: not run because `/usr/bin/python` has no `pytest` module installed.

## GO/NO-GO

CODEX_RISK_GATEWAY_DEGRADED_STATE_FAIL
