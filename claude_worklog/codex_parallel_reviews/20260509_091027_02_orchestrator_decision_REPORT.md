# Codex Parallel Review: Orchestrator Decision MVP

Review timestamp: 2026-05-09 09:10:27 UTC

Verdict: READY

## Scope Reviewed

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- focused tests under `v2/backend/tests/unit/domain/orchestrator_decision/`, `v2/backend/tests/unit/services/orchestrator_decision/`, `v2/backend/tests/unit/composition/orchestrator_decision/`, `v2/backend/tests/unit/services/risk_gateway/`, and `v2/backend/tests/unit/composition/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`
  - result: `151 passed in 0.41s`
- Static source inspection for Redis writes, order placement/cancelation, leverage/margin changes, live enablement, deployment hooks, exchange client calls, and direct execution behavior.
  - result: no live side effects observed in the reviewed orchestrator decision or risk gateway source packages.

## Findings

### PASS - decision_id lineage is deterministic and preserved through risk gateway handoff

`assemble_orchestrator_decision_record` rejects prediction IDs longer than 124 characters before deriving `decision_id = "dec_" + prediction.prediction_id` in `v2/backend/app/services/orchestrator_decision/service.py:70-76`.

The orchestrator record preserves `prediction_id`, `feature_snapshot_id`, `symbol`, input direction, calibrated confidence, freshness flag, worker health status, and `live_blocked=True` in `v2/backend/app/services/orchestrator_decision/service.py:105-118`.

The risk gateway derives `risk_decision_id = "rd_" + decision.decision_id` and forwards `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` into `RiskDecisionRecord` in `v2/backend/app/services/risk_gateway/service.py:67-78`.

### PASS - risk gateway handoff is complete for the MVP contract

The risk gateway accepts only an `OrchestratorDecisionRecord`, validates the injected clock, bounds the incoming `decision_id`, and maps every current orchestrator action: `open_long` to `allow_proceed_long`, `open_short` to `allow_proceed_short`, `hold` to `deny_orchestrator_held`, and `abstain` to `deny_orchestrator_abstained` in `v2/backend/app/services/risk_gateway/service.py:25-79`.

`RiskDecisionRecord` freezes the handoff payload, validates all lineage fields and reason/action enums, enforces `live_blocked is True`, and checks reason/action consistency in `v2/backend/app/domain/risk_gateway/record.py:56-140`.

### PASS - stale and unsafe inputs fail closed before tradable decisions

Missing and stale prediction freshness are handled before worker health, confidence, and direction branches in `v2/backend/app/services/orchestrator_decision/service.py:77-82`, producing `abstain_freshness_missing` or `abstain_freshness_stale`.

Worker health states `CRITICAL`, `DEGRADED`, and `UNKNOWN` also abstain before low-confidence and tradable direction handling in `v2/backend/app/services/orchestrator_decision/service.py:83-94`.

Risk gateway converts all abstains to deny in `v2/backend/app/services/risk_gateway/service.py:58-60`, and tests cover stale/missing abstain propagation into `deny_orchestrator_abstained`.

### PASS WITH FOLLOW-UP - duplicate signal handling is upstream, not implemented inside this MVP

The reviewed MVP consumes a typed `TrainerPredictionRecord`; it does not consume raw signal streams or carry a `signal_id`. The Phase 2F evidence review explicitly reserves `signal_id` for an upstream signal layer, and the assembler's deterministic `decision_id` derivation makes repeated processing of the same prediction ID produce the same decision ID.

No orchestrator-local duplicate detector, seen-ID store, Redis key, stream ACK, or replay filter exists in the reviewed packages. That is acceptable for this MVP boundary because the package is pure domain/service/composition logic and has no persistence layer. The non-live follow-up is to add an upstream dedup ownership artifact and integration test proving duplicate raw signals cannot produce multiple unrelated prediction IDs.

### PASS - legacy orchestrator behavior is mapped to the available audit evidence

The legacy read-only audit identifies the running legacy orchestrator worker and requires V2 decisions to include `decision_id`, risk gateway default-deny for stale/unsafe signals, paper ledger capture, and shadow comparison. The 2F implementation maps those requirements into a pure decision record, deterministic decision lineage, stale/missing abstain reasons, worker-health abstain reasons, low-confidence abstain, flat hold, and long/short candidate decisions.

No more detailed legacy behavior was present in the provided `legacy_readonly_audit` inputs, so the authored Phase 2F specs and implementation reports are the acceptance contract for this MVP.

### PASS - no direct trade execution observed

The reviewed orchestrator decision and risk gateway packages are pure value-object, assembler, and binder code. They do not import exchange adapters, Redis clients, FastAPI startup hooks, execution routers, live trading toggles, environment URL loaders, or legacy runtime modules. They do not place or cancel orders, change leverage or margin, write Redis, restart services, deploy, or enable live trading.

## Concrete Blockers

None for the reviewed Orchestrator Decision MVP scope.

## Proposed Non-Live Follow-Up Tasks

1. Add an upstream duplicate-signal ownership note tying `signal_id` deduplication to signal ingestion or trainer prediction output, not to the orchestrator decision value-object layer.
2. Add a non-live integration test for trainer prediction output -> orchestrator decision -> risk gateway that asserts lineage preservation and deterministic IDs for repeated processing of the same prediction ID.
3. Add a fixture that proves stale/missing freshness flows from prediction output into orchestrator abstain and then into risk gateway deny without live side effects.

## Safety Statement

This review did not modify `/home/wali/Desktop/AI BOT`, did not read or write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
