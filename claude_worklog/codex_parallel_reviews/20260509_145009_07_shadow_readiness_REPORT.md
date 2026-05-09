# Shadow Mode Readiness Parallel Review

Review date: 2026-05-09

Verdict: BLOCKED

## Scope

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

No legacy files, Redis state, live services, exchange orders, leverage/margin settings, deployment paths, or live-trading controls were modified or invoked.

## Safety Evidence

- `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-18` defines only `not_ready` and `ready` flag states, and `v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55` rejects any flag whose `live_blocked` value is not boolean `True`.
- `v2/backend/app/services/shadow_mode_readiness/service.py:21-29` rejects non-string and unrecognized requested states, while `v2/backend/app/services/shadow_mode_readiness/service.py:47-50` emits the flag with literal `live_blocked=True`.
- `v2/backend/app/api/middleware/live_block_guard.py:40-56` still default-denies `/api/v1/live` and `/api/v1/live/**` with HTTP 403 and `x-live-blocked: default`.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:10-12` and `v2/backend/app/proof/non_live_operational_proof.py:26` keep proof outputs labeled `blocked_human_only`.

I did not find evidence that shadow readiness can place or cancel orders, write Redis, change leverage or margin, restart services, enable live trading, or bypass the live gate.

## Blockers

### Blocker 1 - Shadow readiness is only a typed flag, not legacy-vs-V2 comparison readiness

`v2/backend/app/services/shadow_mode_readiness/service.py:16-51` only maps `requested_state` to `ShadowModeReadinessFlag`. `v2/backend/app/composition/shadow_mode_readiness/runtime.py:34-40` only binds a clock and exposes a wrapper around that assembler.

This proves a non-live readiness flag can be emitted, but it does not prove the review requirement from `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`, which says shadow mode must compare legacy versus V2. The production readiness object carries no legacy decision input, V2 decision input, symbol-pair validation, snapshot-pair validation, or divergence audit summary.

### Blocker 2 - Same-symbol same-snapshot comparison is not enforced

The test harness pairs an opaque legacy evidence pointer with a V2 risk decision:

- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-24`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:59-65`

The fixtures create V2 `OrchestratorDecisionRecord` values with `symbol`, `feature_snapshot_id`, and `live_blocked=True` at `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:157-170`, but the legacy side is only `legacy_action_evidence_pointer` at `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:171-173`.

Because there is no typed legacy symbol or typed legacy feature snapshot id, the harness cannot reject mismatched legacy/V2 symbols or mismatched legacy/V2 snapshots before treating a row as comparison-ready.

### Blocker 3 - Divergence audit exists as fixture output, not as a readiness gate

`v2/backend/app/proof/non_live_operational_proof.py:281-296` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239` emit `diverged` rows, and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:275-278` emits a divergence count for the dashboard payload.

Those artifacts are useful offline proof fixtures, but they derive legacy and V2 fields from the same local fixture row. They do not independently validate a legacy evidence record against a V2 record, and no production V2 service consumes those rows to block readiness when comparison preconditions fail.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with immutable records for legacy evidence, V2 evidence, comparison result, and divergence audit summary. Include explicit `legacy_symbol`, `v2_symbol`, `legacy_feature_snapshot_id`, `v2_feature_snapshot_id`, actions, reasons, timestamps, evidence pointers, and `live_blocked=True`.
2. Add a pure `v2/backend/app/services/shadow_comparison/` comparator that rejects mismatched symbols, rejects mismatched snapshot ids, computes `diverged`, and returns audit-ready rows without Redis, DB, exchange, order, scheduler, subprocess, or live-router imports.
3. Add a non-live `v2/backend/app/composition/shadow_comparison/` binder that accepts injected clocks/readers only and introduces no persistence, background loop, FastAPI route, Redis write, or exchange client.
4. Extend tests to cover same-symbol same-snapshot success, symbol mismatch blocked/not-ready, snapshot mismatch blocked/not-ready, divergence row required fields, and live-side-effect forbidden-token scans.
5. Add a read-only readiness aggregation test proving `ShadowModeReadinessFlag(state="ready", live_blocked=True)` plus at least one valid comparison bundle can be inspected while `/api/v1/live/**` remains blocked.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
