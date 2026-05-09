# Codex Parallel Review: Orchestrator Decision MVP

Review timestamp: 2026-05-09 03:55:06 UTC

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl`
- `claude_worklog/legacy_readonly_audit`

Safety posture:
- Did not inspect or modify `/home/wali/Desktop/AI BOT`.
- Did not read or write Redis.
- Did not restart services, deploy, place/cancel orders, change leverage/margin, or enable live trading.

## Verdict

CODEX_PARALLEL_REVIEW_READY

The Orchestrator Decision MVP is ready for the reviewed scope. I found no blockers requiring a non-live autofix.

## Evidence

### decision_id lineage

Pass.

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` bounds `prediction.prediction_id` to 124 characters before deriving `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-117` propagates `prediction_id`, `feature_snapshot_id`, `symbol`, prediction direction, calibrated confidence, freshness flag, worker health, and hard-codes `live_blocked=True`.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-164` freezes and validates the decision record, including ID fields, uppercase symbol, timestamp, allowed action/reason taxonomies, input freshness/health fields, and `live_blocked is True`.
- `v2/backend/app/services/risk_gateway/service.py:67-78` derives `risk_decision_id="rd_" + decision.decision_id` and preserves `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` into the risk decision record.

### risk gateway handoff completeness

Pass for MVP handoff.

- `v2/backend/app/services/risk_gateway/service.py:30-47` only accepts an `OrchestratorDecisionRecord`, validates the injected clock, and rejects too-long decision IDs before risk ID derivation.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` and `open_short` to risk `allow`, and maps `hold` and `abstain` to risk `deny`.
- `v2/backend/app/domain/risk_gateway/record.py:56-81` freezes and validates the risk decision fields, including risk/action reason enums and `live_blocked=True`.
- `v2/backend/app/domain/risk_gateway/record.py:97-140` enforces cross-field consistency between allow/deny reasons and the input orchestrator action/reason.

### stale/duplicate signal handling

Pass for stale inputs; duplicate signal handling is not part of this MVP surface.

- `v2/backend/app/services/orchestrator_decision/service.py:77-82` maps missing and stale prediction freshness to `abstain_freshness_missing` and `abstain_freshness_stale`.
- `v2/backend/app/services/orchestrator_decision/service.py:83-94` further abstains on critical/degraded/unknown worker health and low calibrated confidence before any tradable action branch.
- The legacy audit requires default-deny for stale/unsafe signals in `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`.
- The 2F evidence/spec documents `signal_id` as reserved for an upstream signal layer, not introduced by this milestone. This MVP consumes a validated `TrainerPredictionRecord`, so duplicate-signal deduplication should remain an upstream signal-ingest or trainer-output responsibility.

### legacy orchestrator behavior mapping

Pass for the available legacy evidence.

- The legacy audit lists required V2 impact as `decision_id`, risk-gateway default-deny for stale/unsafe signals, paper ledger capture, and shadow comparison.
- The Phase 2F specs intentionally map the available evidence into a pure decision record plus default-deny derivation table: missing/stale freshness, unhealthy worker, low confidence, flat hold, then long/short proceed.
- No concrete legacy code behavior beyond the audit requirements was available in the provided legacy read-only audit input, so this review treats the authored 2F specs as the acceptance contract for the MVP.

### no direct trade execution

Pass.

- `v2/backend/app/domain/orchestrator_decision`, `v2/backend/app/services/orchestrator_decision`, and `v2/backend/app/composition/orchestrator_decision` contain no exchange adapter imports, Redis imports, order-placement calls, leverage/margin calls, service startup hooks, or live execution toggles.
- The targeted forbidden-token scan only found Redis wording in test names/assertion construction for no-Redis import checks, not in the orchestrator decision source implementation.
- The orchestrator decision source is a pure value/domain/service/composition path. It returns records only and does not emit signals, intents, orders, or Redis writes.

## Tests

Command run:

`PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`

Result:

`151 passed in 0.46s`

## Proposed non-live follow-up tasks

No blocking autofix tasks are required.

Recommended non-live hardening tasks:
- Add an explicit upstream duplicate-signal/dedup review artifact tying `signal_id` ownership to signal ingestion or trainer prediction output.
- Add an integration-level non-live test that chains trainer prediction output -> orchestrator decision -> risk gateway and asserts lineage preservation across all IDs.
