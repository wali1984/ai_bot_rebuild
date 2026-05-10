# Shadow Mode Readiness Parallel Review

Review date: 2026-05-10

Verdict: BLOCKED

## Scope

- Inspected `v2/backend/app`, `v2/backend/tests`, `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`, and `claude_worklog/legacy_readonly_audit`.
- Observed read-only safety constraints except for writing this requested report and the requested GO/NO-GO marker.
- Did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets.

## Evidence Reviewed

- Legacy audit requires shadow mode to compare legacy vs V2: `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`.
- Legacy audit sentinel is present: `claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md:1`.
- Shadow readiness domain only models `not_ready`, `ready`, `flag_emitted_ts_ms`, and `live_blocked`: `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-18`.
- Shadow readiness rejects any non-true `live_blocked`: `v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55`.
- Shadow readiness service accepts only `requested_state` plus `now_ms_clock` and always returns `live_blocked=True`: `v2/backend/app/services/shadow_mode_readiness/service.py:16-50`.
- Shadow readiness composition root injects only a clock and forwards to the flag assembler: `v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-41`.
- Live API default-deny remains in place for `/api/v1/live` and `/api/v1/live/**`: `v2/backend/app/api/middleware/live_block_guard.py:40-56`.
- Shadow evidence harness pairs an opaque legacy pointer with a V2 risk decision record: `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`.
- Harness fixture legacy side has only `legacy_action_evidence_pointer`; V2 side has `feature_snapshot_id` and `symbol`: `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:27-30` and `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:156-173`.
- Offline proof emits divergence rows from fixture fields: `v2/backend/app/proof/non_live_operational_proof.py:316-330` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239`.
- Dashboard payload includes divergence counts for proof output: `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:265-278`.

## Check Results

- Legacy-vs-V2 comparison readiness: BLOCKED. The production shadow-readiness surface is a flag, not a typed comparison pipeline. It has no legacy decision input, no V2 decision input, no pair compatibility check, no divergence record, and no readiness aggregation based on valid comparisons.
- Shadow decisions do not affect live: PASS for inspected code. The flag and harness preserve `live_blocked=True`, and no order, exchange, leverage, margin, Redis writer, live-router, scheduler, deploy, or live-enable path was found in the inspected shadow-readiness implementation.
- Same-symbol same-snapshot comparison: BLOCKED. The V2 side carries `symbol` and `feature_snapshot_id`; the legacy side is an opaque pointer. The current model cannot reject BTC-vs-ETH, stale-vs-fresh, or snapshot-A-vs-snapshot-B pairings.
- Audit output for divergence: PARTIAL. Offline proof code emits `diverged` rows and counts, but this output is fixture-derived and does not gate readiness or prove independently sourced legacy and V2 records were compared under same-symbol same-snapshot constraints.
- Live gate remains blocked: PASS. The default-deny middleware still returns HTTP 403 with `x-live-blocked: default`, and shadow readiness does not flip it.

## Concrete Blockers

### Blocker 1 - Readiness can be requested without comparison evidence

`assemble_shadow_mode_readiness_flag` only validates `requested_state` and a clock. A caller can request `ready` without supplying any legacy evidence, V2 evidence, matched symbol, matched snapshot, or divergence audit bundle.

Impact: the flag can represent readiness without satisfying the legacy audit requirement that shadow mode compare legacy vs V2.

### Blocker 2 - Same-symbol same-snapshot enforcement is impossible with current legacy input

`ShadowModeComparisonInput` stores `legacy_action_evidence_pointer` as a string only. There is no typed legacy symbol, feature snapshot id, action, reason, decision timestamp, or evidence id to compare against the V2 risk decision lineage.

Impact: invalid comparison pairs can be represented as valid evidence because the code has no fields with which to detect mismatches.

### Blocker 3 - Divergence audit is not connected to readiness gating

The proof writers emit divergence fields from local fixture rows, while the shadow readiness flag remains independent of those rows. No production service consumes typed legacy and V2 rows, validates pairing preconditions, computes divergence, and blocks readiness on incomplete or invalid audit output.

Impact: divergence output exists for operator display, but it is not yet a readiness gate.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with frozen records for `LegacyShadowDecisionEvidence`, `V2ShadowDecisionEvidence`, `ShadowComparisonResult`, and `ShadowDivergenceAuditSummary`. Include legacy/V2 symbol, feature snapshot id, action, reason fields, ids or evidence pointers, timestamps, divergence state, comparison readiness state, not-ready reason, and `live_blocked=True`.
2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects symbol mismatch, rejects feature snapshot mismatch, computes action divergence, and returns audit-ready records without importing Redis, DB, exchange clients, order routers, schedulers, subprocess runners, or live routes.
3. Add unit tests for same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, action divergence, action parity, required audit fields, immutable records, no Redis import, and no live-side-effect tokens.
4. Add a read-only readiness aggregation service that can emit `ShadowModeReadinessFlag(state="ready", live_blocked=True)` only when valid comparison bundles exist and all comparison preconditions pass.
5. Extend the evidence harness to use typed legacy evidence instead of an opaque pointer, while keeping fixture-only operation and no live writes.

## Validation

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/shadow_mode_readiness v2/backend/tests/unit/services/shadow_mode_readiness v2/backend/tests/unit/composition/shadow_mode_readiness v2/backend/tests/unit/shadow_mode_evidence_collection_harness -q` passed with `91 passed`.
- Read-only live-side-effect token scan over the shadow readiness package and shadow evidence harness found no order, cancel, leverage, margin, live-enable, or Redis write calls.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
