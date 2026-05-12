# Codex Parallel Review - Orchestrator Decision MVP

Review mode: read-only inspection plus targeted non-live tests. I did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, deploy, or expose secrets. Only the requested review artifacts were authored.

## Scope inspected

- `v2/backend/app/domain/orchestrator_decision/record.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/composition/orchestrator_decision/runtime.py`
- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/app/composition/risk_gateway/runtime.py`
- focused orchestrator/risk unit tests under `v2/backend/tests/unit/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Validation performed

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway -q`
  - result: `151 passed in 0.36s`
- Static scan over orchestrator decision and risk gateway source paths for Redis, execution, order, leverage, margin, and live-trading mutation terms.
  - result: no production-source matches in the reviewed MVP paths.

## Findings

### PASS - decision_id lineage is deterministic and preserved

`OrchestratorDecisionRecord` requires `decision_id`, `prediction_id`, and `feature_snapshot_id`, with non-empty, whitespace-free, length-bounded validation in `v2/backend/app/domain/orchestrator_decision/record.py:73`.

`assemble_orchestrator_decision_record` rejects overlong `prediction_id` values, derives `decision_id = "dec_" + prediction.prediction_id`, and forwards prediction lineage into the decision record in `v2/backend/app/services/orchestrator_decision/service.py:70`.

Risk gateway continues lineage with `risk_decision_id = "rd_" + decision.decision_id` and preserves `decision_id`, `prediction_id`, and `feature_snapshot_id` in `v2/backend/app/services/risk_gateway/service.py:67`.

### PASS - stale/missing prediction handling fails closed

The orchestrator assembler checks freshness before worker health, confidence, or direction. `missing` maps to `abstain_freshness_missing`; `stale` maps to `abstain_freshness_stale` in `v2/backend/app/services/orchestrator_decision/service.py:77`.

Risk gateway maps orchestrator `abstain` decisions to `deny_orchestrator_abstained` in `v2/backend/app/services/risk_gateway/service.py:58`, so stale/missing prediction inputs do not become risk `allow`.

### BLOCKER - duplicate signal handling is not represented in the orchestrator-to-risk handoff

The reviewed orchestrator decision record has no `signal_id`, dedupe state, duplicate-of reference, source sequence, or stale-out-of-order field. Its only safety inputs are prediction direction, calibrated confidence, freshness flag, and worker health in `v2/backend/app/domain/orchestrator_decision/record.py:75`.

The assembler only accepts `prediction`, `low_confidence_threshold`, and `now_ms_clock` in `v2/backend/app/services/orchestrator_decision/service.py:34`, so it cannot abstain for `duplicate_signal`, `duplicate_of_prior`, or `stale_out_of_order`.

Risk gateway only accepts an `OrchestratorDecisionRecord` and a clock in `v2/backend/app/services/risk_gateway/service.py:25`. It maps any `open_long` or `open_short` decision directly to `allow` in `v2/backend/app/services/risk_gateway/service.py:49`, without seeing duplicate classification.

There is a separate dedupe domain downstream of risk gateway (`v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py:24`), but that does not complete the requested risk-gateway handoff because risk can already emit `allow` before duplicate state is available.

### PASS - legacy behavior mapping is partially covered

Legacy read-only evidence requires decisions to include `decision_id` and the risk gateway to default-deny stale/unsafe signals in `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13`.

The MVP covers `decision_id`, stale/missing fail-closed behavior, worker-health fail-closed behavior, low-confidence abstain, flat hold, and downstream risk denial for hold/abstain. It does not yet cover duplicate-signal default-deny at the orchestrator/risk boundary.

### PASS - no direct trade execution observed

The orchestrator decision and risk gateway MVP source paths are pure value/service/composition code. I observed no Redis writes, Redis deletes, order placement/cancelation, exchange client calls, leverage/margin mutation, live-trading enablement, deployment, or service restart logic.

Both `OrchestratorDecisionRecord` and `RiskDecisionRecord` require `live_blocked is True`, enforced in `v2/backend/app/domain/orchestrator_decision/record.py:159` and `v2/backend/app/domain/risk_gateway/record.py:214`.

## Concrete blockers

1. Duplicate-signal state is absent from `OrchestratorDecisionRecord` and `assemble_orchestrator_decision_record`.
2. `assemble_risk_decision_record` can emit `allow` for `open_long`/`open_short` without seeing whether the candidate is duplicate or stale-out-of-order.
3. Existing dedupe handling is downstream/separate and does not satisfy risk gateway handoff completeness for duplicate signal default-deny.

## Proposed non-live autofix tasks

1. Add a pure, non-live duplicate classification input before risk allow decisions. Conservative option: extend orchestrator decision with `input_dedupe_state`, `duplicate_of_decision_id`, and abstain reasons for duplicate/stale-out-of-order.
2. Alternatively, require risk gateway to consume a dedupe/gating record alongside `OrchestratorDecisionRecord` and deny unless dedupe state is `DEDUPE_NEW`.
3. Add unit tests proving duplicate and stale-out-of-order candidates become orchestrator `abstain` or risk `deny`, while fresh non-duplicate long/short candidates preserve current behavior.
4. Add a non-live projection/replay fixture for two repeated prediction/signal candidates sharing lineage, proving the second candidate cannot produce risk `allow`.

## Recommendation

CODEX_PARALLEL_REVIEW_BLOCKED
