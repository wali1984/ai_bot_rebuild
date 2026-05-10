# Codex Parallel Review - Orchestrator Decision MVP

Review timestamp: 2026-05-10 18:15:35 America/New_York

Scope inspected:
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

Validation run:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`
- Result: `151 passed in 0.35s`

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED

The MVP has solid decision lineage, stale/missing freshness default-deny handling, risk-gateway handoff, and no direct trade execution in the inspected orchestrator/risk surfaces. It is blocked for this review because duplicate signal handling is absent from the Orchestrator Decision MVP contract and tests.

## Findings

### Blocker 1 - Duplicate signal handling is not represented in Orchestrator Decision MVP

The review checklist explicitly includes stale/duplicate signal handling. Stale/missing handling exists, but duplicate handling is absent from the orchestrator decision domain, service, composition root, and tests.

Evidence:
- `rg -n "duplicate|dedupe|duplicate_of" v2/backend/app/domain/orchestrator_decision v2/backend/app/services/orchestrator_decision v2/backend/app/composition/orchestrator_decision v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision` returned no matches.
- `OrchestratorDecisionRecord` fields are limited to `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, decision action/reason, input prediction fields, worker health, and `live_blocked`; there is no `signal_id`, `dedupe_state`, `duplicate_of_decision_id`, or equivalent duplicate lineage/control field (`v2/backend/app/domain/orchestrator_decision/record.py:73-86`).
- The assembler decision table checks freshness, worker health, confidence, and direction only (`v2/backend/app/services/orchestrator_decision/service.py:77-103`).
- Phase 2F legacy evidence explicitly says `signal_id` is reserved for an upstream signal layer and not introduced by 2F.A (`claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md:23-25`).
- A later provenance/dedupe domain exists with `DEDUPE_DUPLICATE_OF_PRIOR` and `duplicate_of_decision_id` invariants (`v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py:15-20`, `:41-58`), but that is downstream of `RiskDecisionRecord` assembly and is not integrated into the Orchestrator Decision MVP boundary.

Risk:
- A duplicate but otherwise fresh/high-confidence prediction can still produce `open_long` or `open_short` at the orchestrator layer. The risk gateway then allows open actions based only on the orchestrator decision action (`v2/backend/app/services/risk_gateway/service.py:49-60`), with no duplicate-state input.

Required non-live autofix tasks:
1. Add a non-live duplicate guard before risk allow decisions. Prefer a pure additive contract that accepts explicit duplicate/dedupe state and maps duplicates to `abstain` or risk `deny`, without Redis, exchange, service restart, or live execution.
2. Add unit tests for duplicate fresh/high-confidence long and short inputs proving they cannot become risk `allow`.
3. Add lineage propagation tests proving duplicate decisions retain `decision_id`, `prediction_id`, `feature_snapshot_id`, and `duplicate_of_decision_id` or equivalent provenance.
4. Re-run the focused orchestrator/risk/provenance tests with cache writes disabled.

## Passing Checks

### decision_id lineage

Pass. The orchestrator assembler derives `decision_id = "dec_" + prediction.prediction_id` after validating the derived length cap (`v2/backend/app/services/orchestrator_decision/service.py:70-76`). It propagates `prediction_id`, `feature_snapshot_id`, `symbol`, freshness, confidence, and worker health into `OrchestratorDecisionRecord` (`service.py:105-117`). The risk gateway derives `risk_decision_id = "rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, and `feature_snapshot_id` (`v2/backend/app/services/risk_gateway/service.py:67-78`).

### risk gateway handoff completeness

Pass for current orchestrator actions. `open_long` maps to `allow_proceed_long`, `open_short` maps to `allow_proceed_short`, `hold` maps to `deny_orchestrator_held`, and `abstain` maps to `deny_orchestrator_abstained` (`v2/backend/app/services/risk_gateway/service.py:49-60`). Risk records are `live_blocked=True` (`service.py:78`).

### stale signal handling

Pass. Missing freshness is checked first and maps to `abstain_freshness_missing`; stale freshness maps to `abstain_freshness_stale` before worker-health, confidence, or direction can produce a tradable action (`v2/backend/app/services/orchestrator_decision/service.py:77-82`). The domain allows only `fresh`, `stale`, and `missing` freshness values (`v2/backend/app/domain/orchestrator_decision/record.py:45`, `:146-151`).

### legacy orchestrator behavior mapping

Partial pass. The available legacy read-only audit confirms runtime orchestrator/trader processes and requires `decision_id`, stale/unsafe default-deny through risk gateway, paper ledger coverage, and shadow comparison (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:7-16`). The Phase 2F evidence review records that concrete legacy decision behavior was not available from the stubs and therefore the MVP was derived from trainer prediction, lineage, and default-deny contracts (`claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md:15-26`). This is acceptable for stale/default-deny behavior, but duplicate handling remains unmapped in this MVP.

### no direct trade execution

Pass. Static search across the inspected orchestrator and risk service/composition surfaces found no exchange/order/leverage/margin/Redis execution tokens. The orchestrator composition root only validates injected configuration and returns a pure evaluator that calls the assembler (`v2/backend/app/composition/orchestrator_decision/runtime.py:15-51`). The orchestrator record requires `live_blocked=True` (`v2/backend/app/domain/orchestrator_decision/record.py:159-164`).

## Safety posture

No `/home/wali/Desktop/AI BOT` files were modified. No Redis command was invoked. No live services were restarted. No orders, leverage, margin, live trading, or deployment actions were performed.
