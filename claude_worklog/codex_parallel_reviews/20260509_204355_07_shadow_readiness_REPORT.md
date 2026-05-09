# Shadow Mode Readiness Parallel Review

Review date: 2026-05-09

Verdict: BLOCKED

## Scope

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only constraints observed except for writing this requested report and GO/NO-GO marker. I did not modify `/home/wali/Desktop/AI BOT`, write or delete Redis keys, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets.

## Evidence Reviewed

- Legacy audit impact requirement: `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17` explicitly requires shadow mode to compare legacy vs V2.
- Legacy audit sentinel: `claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md` contains `LEGACY_READONLY_AUDIT_SENTINEL_READY`.
- Shadow readiness domain: `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-18` defines only `not_ready` / `ready`, timestamp, and `live_blocked`.
- Shadow readiness live block invariant: `v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55` rejects any flag where `live_blocked` is not exactly `True`.
- Shadow readiness service: `v2/backend/app/services/shadow_mode_readiness/service.py:16-50` validates the requested state and returns `ShadowModeReadinessFlag(..., live_blocked=True)`.
- Shadow readiness composition root: `v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-41` injects only a clock and exposes the flag assembler wrapper.
- Live gate: `v2/backend/app/api/middleware/live_block_guard.py:40-56` still default-denies `/api/v1/live` and `/api/v1/live/**` with HTTP 403 and `x-live-blocked: default`.
- Evidence harness comparison record: `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24` pairs only `legacy_action_evidence_pointer` with a V2 `RiskDecisionRecord`.
- Evidence harness replay: `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:57-76` projects V2 risk decisions and stores the legacy pointer without validating legacy symbol, legacy snapshot, or legacy action fields.
- Harness fixtures: `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30` define the legacy side as only an evidence pointer; `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:156-173` put symbol and feature snapshot on the V2 orchestrator decision only.
- Offline proof divergence output: `v2/backend/app/proof/non_live_operational_proof.py:316-330` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239` emit fixture-level `diverged` rows; `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:265-278` exposes a dashboard divergence count.

## Check Results

- Legacy-vs-V2 comparison readiness: BLOCKED. The implemented production shadow-readiness surface is a flag, not a typed comparison pipeline. It has no legacy decision input, V2 decision input, matching precondition, divergence record, or readiness aggregation based on comparison validity.
- Shadow decisions do not affect live: PASS for inspected code. The flag and harness keep `live_blocked=True`; no order, exchange, leverage, margin, Redis writer, live-router, scheduler, or deploy path was found in the shadow-readiness implementation.
- Same-symbol same-snapshot comparison: BLOCKED. V2 records have `symbol` and `feature_snapshot_id`, but the legacy side is an opaque pointer only. There is no field or test that can reject BTC-vs-ETH, stale-vs-fresh, or snapshot-A-vs-snapshot-B pairings.
- Audit output for divergence: PARTIAL. Fixture/proof code emits `diverged`, but this is offline proof output. It does not gate readiness and does not prove independently sourced legacy and V2 rows were compared under same-symbol same-snapshot constraints.
- Live gate remains blocked: PASS. The default-deny middleware remains in place and shadow readiness does not flip it.

## Concrete Blockers

### Blocker 1 - Shadow readiness is a flag, not comparison readiness

`assemble_shadow_mode_readiness_flag` accepts only `requested_state` and `now_ms_clock` (`v2/backend/app/services/shadow_mode_readiness/service.py:16-20`). The runtime injects only the clock (`v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-37`). This cannot satisfy the legacy audit requirement that shadow mode compare legacy vs V2.

Impact: a caller can request `ready` without proving any legacy-vs-V2 pair exists, without proving pair compatibility, and without producing a comparison audit bundle.

### Blocker 2 - Same-symbol same-snapshot comparison cannot be enforced

`ShadowModeComparisonInput` contains `orchestrator_decision` and `legacy_action_evidence_pointer` only (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30`). The V2 decision includes `feature_snapshot_id`, `symbol`, and `live_blocked=True` (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:157-169`), but the legacy side has no typed `legacy_symbol` or `legacy_feature_snapshot_id`.

Impact: mismatched legacy/V2 comparison rows can be represented as valid evidence because there is no data model or comparator that can detect the mismatch.

### Blocker 3 - Divergence audit is output-only and fixture-derived

The proof writers emit divergence rows by comparing local fixture fields (`v2/backend/app/proof/non_live_operational_proof.py:316-330`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239`). Those rows are useful for operator display, but no V2 service consumes an independently typed legacy record and V2 record to block readiness when pairing preconditions fail.

Impact: divergence output exists, but shadow readiness is not gated by divergence audit completeness or by comparison precondition failures.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with frozen records for `LegacyShadowDecisionEvidence`, `V2ShadowDecisionEvidence`, `ShadowComparisonResult`, and `ShadowDivergenceAuditSummary`. Required fields: legacy/V2 symbol, legacy/V2 feature snapshot id, legacy/V2 action, reason fields, decision ids/evidence pointers, timestamps, `diverged`, `comparison_ready`, `not_ready_reason`, and `live_blocked=True`.
2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects mismatched symbols, rejects mismatched feature snapshot ids, computes divergence, and returns audit-ready records without importing Redis, DB, exchange clients, order routers, schedulers, subprocess runners, or live-mode routes.
3. Add tests for same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, action divergence, action parity, required audit fields, immutable records, and forbidden live-side-effect imports/tokens.
4. Add a read-only readiness aggregation service that can emit `ShadowModeReadinessFlag(state="ready", live_blocked=True)` only when at least one valid comparison bundle exists and all comparison preconditions pass. Keep the existing default-deny live gate untouched.
5. Extend the evidence harness to use typed legacy evidence instead of an opaque pointer, while preserving non-live fixture-only operation and no Redis writes.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
