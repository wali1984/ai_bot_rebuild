# Codex Risk Gateway Degraded-State Review

- task_id: `codex_parallel_review_risk_gateway_degraded_state_online_readiness`
- mode: read-only parallel review
- decision: `CODEX_RISK_GATEWAY_DEGRADED_STATE_FAIL`
- reviewed_at: `2026-05-11`
- safety: no legacy bot mutation, no Redis mutation, no exchange order/margin/leverage/position-mode mutation, no live enablement

## NO-GO Findings

1. Risk gateway allows `open_long` and `open_short` solely from the orchestrator decision action. `v2/backend/app/services/risk_gateway/service.py:49` maps those actions directly to `allow_*`, and `v2/backend/app/services/risk_gateway/service.py:67` only stamps `live_blocked=True` on the returned record. The gateway has no local inputs or checks for missing attribution, stale risk-add state, duplicate execution/order IDs, stop policy, kill switch, margin mode, leverage cap, or `ADJUST_LEVERAGE`.

2. Required attribution is incomplete at the implemented risk boundary. `v2/backend/app/api/v1/risk_decisions.py:22` declares `signal_id` as a required stage ID, but `v2/backend/app/domain/risk_gateway/record.py:56` has no `signal_id`, no confidence fields, and no execution/order attribution fields. Missing `signal_id` and missing confidence therefore cannot fail closed inside the risk gateway.

3. Stale/missing freshness and low confidence are upstream orchestrator behavior, not independent risk-gateway enforcement. `v2/backend/app/services/orchestrator_decision/service.py:77` abstains for missing/stale freshness and `v2/backend/app/services/orchestrator_decision/service.py:92` abstains for low confidence, but `v2/backend/app/services/risk_gateway/service.py:25` accepts only an `OrchestratorDecisionRecord` plus a clock and trusts the action already present on that record.

4. Kill switch, policy bundles, and live readiness are still scaffold placeholders. `/risk/kill-switch` is metadata-only in `v2/backend/app/api/v1/risk.py:1`, and `v2/backend/app/domain/risk/kill_switch.py:1`, `policy_bundle.py:1`, and `live_readiness_state.py:1` are placeholder modules. A disabled or unknown kill switch cannot currently force a risk denial.

5. Margin and leverage blockers are observed/documented but not enforced by the risk gateway. `v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json` reports `cross_margin_pos_before_hits=397` and `high_leverage_pos_ge_25=84`, while `v2/backend/app/domain/risk_gateway/record.py:56` has no margin/leverage fields and `v2/backend/app/services/risk_gateway/service.py:25` has no margin/leverage inputs.

6. Duplicate execution/order identifier handling is not fail-closed in the runtime path. `v2/backend/app/services/orchestrator_decision/service.py:76`, `v2/backend/app/services/risk_gateway/service.py:67`, and `v2/backend/app/services/paper_execution_ledger/service.py:80` derive IDs deterministically from upstream IDs, while `v2/backend/app/adapters/db/repositories/decisions.py:1`, `risk_decisions.py:1`, and `execution_intents.py:1` are placeholders. Replaying the same upstream input can recreate the same derived identifiers without an idempotency or duplicate-deny layer.

7. Degraded-state fail-closed logic exists as a separate record builder, not as an execution blocker. `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:37` derives `fail_closed` from per-source states and `v2/backend/app/domain/degraded_state_fail_closed_gates/degraded_state_record.py:49` validates consistency, but there is no evidence that a `fail_closed=True` degraded-state record feeds back into `RiskDecisionRecord` as a deny.

8. External/manual attribution quarantine is proof-only and fixture-based. `v2/backend/app/proof/external_manual_position_quarantine.py:186` classifies missing/duplicate/manual/protective rows and `v2/backend/app/proof/external_manual_position_quarantine.py:433` writes static risk-gateway rules, but `v2/backend/app/proof/external_manual_position_quarantine.py:501` labels them non-live stubs. The proof also records unavailable read-only exchange snapshots in its data gaps, so it cannot prove live fail-closed coverage.

9. Online readiness can become `READY` from marker text without validating degraded evidence. `v2/backend/app/proof/online_readiness_aggregator.py:189` reads lane marker files and `v2/backend/app/proof/online_readiness_aggregator.py:206` sets the aggregate marker from string matches. Its required lanes at `v2/backend/app/proof/online_readiness_aggregator.py:87` omit realtime legacy monitoring continuity, external/manual quarantine, orchestrator risk boundary, and this Codex audit lane.

10. Some existing GO markers overstate readiness relative to the data. `v2/frontend/public/orchestrator_risk_boundary/latest/ORCHESTRATOR_RISK_GATEWAY_BOUNDARY.md:3` claims risk blocks stale/missing/confidence/margin/leverage/duplicate/kill-switch issues, but the implemented gateway does not. Realtime monitoring and readonly data-plane artifacts carry stale/missing/degraded observations while still emitting READY markers.

## Bypass Assessment

No active execution router, paper loop, or exchange mutation path was found in the reviewed V2 scaffolds; `v2/backend/app/services/execution_router.py:1` and `v2/backend/app/services/paper_loop.py:1` are placeholders, and route modules are metadata-only. That limits immediate live-order blast radius, but it does not satisfy the requested risk-gateway boundary: the implemented gateway is not yet a final fail-closed policy authority.

## Required Remediation Before PASS

- Move attribution, signal ID, confidence, stale source, duplicate identifier, stop policy, kill switch, margin mode, leverage cap, and `ADJUST_LEVERAGE` inputs into the risk-gateway decision contract.
- Ensure every degraded-state `fail_closed=True`, missing/unknown kill-switch state, missing/stale source state, and quarantine hit produces a risk `deny`.
- Add idempotency/dedupe enforcement at decision, risk decision, execution intent, and paper execution boundaries.
- Make readiness aggregators block on degraded evidence, not only marker strings.
- Update tests so READY cannot be emitted while any required fail-closed blocker is present.

## Review Result

`CODEX_RISK_GATEWAY_DEGRADED_STATE_FAIL`
