# Shadow Mode Readiness Parallel Review

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

Read-only constraints observed: no Redis writes/deletes, no live service restarts, no order placement/cancel, no leverage/margin changes, no live enablement, no deployment, and no modification of `/home/wali/Desktop/AI BOT`.

## Pass Evidence

- Legacy audit sentinel is present: `claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md` contains `LEGACY_READONLY_AUDIT_SENTINEL_READY`.
- Legacy audit explicitly requires shadow mode to compare legacy vs V2: `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`.
- Shadow readiness flag is non-live-only: `v2/backend/app/domain/shadow_mode_readiness/flag.py` allows only `not_ready` and `ready`, and requires `live_blocked is True`.
- Shadow readiness service always returns `live_blocked=True`: `v2/backend/app/services/shadow_mode_readiness/service.py`.
- Runtime composition is only a captured-clock binder around the readiness service: `v2/backend/app/composition/shadow_mode_readiness/runtime.py`.
- Live gate remains blocked/human-only in online readiness aggregation: `v2/backend/app/proof/online_readiness_aggregator.py` sets `LIVE_GATE_STATUS = "blocked_human_only"` and lists live/order/Redis mutation operations as forbidden.
- Fixture/proof divergence output exists in `v2/backend/app/proof/non_live_operational_proof.py` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`.

## Blockers

1. No app-layer legacy-vs-V2 shadow comparison surface exists.

   The implemented `shadow_mode_readiness` app surface is only a readiness flag. It does not accept a legacy decision/projection, a V2 decision/risk record pair, or comparison prerequisites. The only comparison-like structure found is under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, which is test harness code.

2. Same-symbol same-snapshot comparison is not enforced.

   `ShadowModeComparisonInput` carries a V2 `OrchestratorDecisionRecord` plus an opaque `legacy_action_evidence_pointer`. The legacy side has no typed `symbol`, `feature_snapshot_id`, action, timestamp, or reason fields, so mismatched legacy/V2 symbol or snapshot pairs cannot be rejected before comparison.

3. Audit output for divergence is fixture-ready, not readiness-gating.

   `non_live_operational_proof.py` and `historical_30d_replay_and_paper_proof.py` emit `diverged` fields from fixture rows, but no reusable app-layer comparator validates independently typed legacy and V2 records, computes bounded divergence reasons, and gates readiness on comparison validity.

4. Shadow decisions are not modeled with typed non-live invariants.

   Current readiness flags are safe, but there is no `ShadowComparisonRecord`/`ShadowDecisionRecord` domain object requiring `live_blocked=True`, `non_live_only=True`, no execution intent, and no order-placement dependency.

## Check Results

- legacy-vs-V2 comparison readiness: BLOCKED
- shadow decisions do not affect live: PASS for inspected readiness flag and proof surfaces
- same-symbol same-snapshot comparison: BLOCKED
- audit output for divergence: PARTIAL/BLOCKED, fixture output exists but no app-layer validated comparator
- live gate remains blocked: PASS

## Proposed Non-Live Autofix Tasks

1. Add `v2/backend/app/domain/shadow_comparison/` with frozen/slotted records for typed legacy projection, V2 projection, comparison result, and divergence audit summary. Require legacy/V2 symbol and `feature_snapshot_id` fields, `live_blocked=True`, and `non_live_only=True`.

2. Add `v2/backend/app/services/shadow_comparison/service.py` that assembles a comparison from one typed legacy projection and one V2 `RiskDecisionRecord`, rejects symbol mismatch, rejects snapshot mismatch, computes `diverged`, and emits bounded divergence reason codes.

3. Add `v2/backend/app/composition/shadow_comparison/runtime.py` as a pure binder for clock/id factories only. It must not import Redis, exchange clients, FastAPI routers, execution adapters, paper loops, schedulers, subprocess, or network clients.

4. Add focused unit tests for same-symbol same-snapshot pass, symbol mismatch blocked, snapshot mismatch blocked, action parity, action divergence, required audit fields, immutable records, `live_blocked=False` rejection, `non_live_only=False` rejection, and forbidden live-side-effect imports/tokens.

5. Wire the proof modules to use the new non-live shadow comparison assembler instead of hand-built fixture comparison dicts, while preserving existing allowed output prefixes and no live/Redis/order side effects.

CODEX_PARALLEL_REVIEW_BLOCKED
