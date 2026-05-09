# Shadow Mode Readiness Review

Status: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

No live services, Redis state, exchange actions, leverage/margin settings, or deployment paths were touched.

## Findings

### Blocker 1: Phase 2K readiness is only a typed flag, not legacy-vs-V2 comparison readiness

`v2/backend/app/services/shadow_mode_readiness/service.py:16-51` only validates `requested_state in {"not_ready", "ready"}` and emits `ShadowModeReadinessFlag(live_blocked=True)`. `v2/backend/app/composition/shadow_mode_readiness/runtime.py:21-41` only binds a clock and forwards the requested state.

That satisfies a narrow live-blocked readiness flag, but it does not prove the requested review topic:
- no legacy decision input
- no V2 decision input
- no same-symbol comparison
- no same-snapshot comparison
- no divergence audit contract
- no operator-visible comparison readiness gate

The Phase 2K planning docs confirm this was intentionally scoped as a precondition flag only, not a shadow trader, comparison runner, scheduler, persistence layer, or shadow-decision surface.

### Blocker 2: Existing comparison artifacts are deterministic fixture outputs, not same-symbol same-snapshot comparison machinery

`v2/backend/app/proof/non_live_operational_proof.py:74-146` defines static `ProofScenario` fixtures. Its shadow comparison output at `v2/backend/app/proof/non_live_operational_proof.py:281-296` compares `scenario.legacy_action` to `scenario.expected_v2_action` from the same fixture row.

`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80-152` similarly defines static `HistoricalTradeFixture` rows. Its comparison output at `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239` marks divergence by comparing fixture `legacy_action` and `v2_action`.

These are useful offline proof fixtures, but they do not enforce that legacy and V2 decisions were produced for the same symbol from the same market/feature snapshot. The emitted rows carry a single derived `feature_snapshot_id` (`non_live`: `fs_<scenario_id>` at lines 45-47; historical: `hist_fs_<trade_id>` at lines 51-53), not separate legacy and V2 snapshot identities with an equality check.

### Blocker 3: Divergence audit exists as artifact text/JSON only, not as a readiness gate

Both proof harnesses emit `diverged` fields and summary counts:
- `non_live_operational_proof.py:281-296`
- `historical_30d_replay_and_paper_proof.py:226-239`
- `historical_30d_replay_and_paper_proof.py:275-278`

But no production V2 service consumes those divergence rows, validates required audit fields, or blocks readiness when comparison preconditions fail. There is no stable non-live shadow comparison domain/service/composition surface in `v2/backend/app` that can be invoked by a readiness gate.

### Passing safety observations

Shadow readiness and related non-live records keep live blocked:
- `ShadowModeReadinessFlag` is emitted with `live_blocked=True` in `v2/backend/app/services/shadow_mode_readiness/service.py:47-50`.
- `/api/v1/live/**` remains default-denied by `LiveBlockGuardMiddleware` in `v2/backend/app/api/middleware/live_block_guard.py:40-56`.
- Proof artifacts label live status as `blocked_human_only` in `v2/backend/app/proof/non_live_operational_proof.py:26` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:11`.

I did not find evidence that shadow decisions currently place/cancel orders, change leverage/margin, enable live trading, or bypass the live guard.

## Proposed Non-Live Autofix Tasks

1. Add a pure `v2/backend/app/domain/shadow_comparison/` package with immutable records for:
   - legacy decision snapshot
   - V2 decision snapshot
   - comparison result
   - divergence audit summary
   Each record must carry `symbol`, `feature_snapshot_id` or equivalent canonical snapshot id, decision/action fields, `live_blocked=True`, and no live execution affordance.

2. Add `v2/backend/app/services/shadow_comparison/` with a pure comparator:
   - reject mismatched symbols
   - reject mismatched snapshot ids
   - compute `diverged`
   - emit required audit fields
   - never import Redis, exchange adapters, live routers, order clients, or subprocess runners

3. Add `v2/backend/app/composition/shadow_comparison/` as a non-live binder only:
   - injected clock only
   - no persistence
   - no background loop
   - no FastAPI route
   - no Redis writes
   - no live execution dependency

4. Add tests proving:
   - same-symbol same-snapshot rows pass
   - symbol mismatch blocks comparison readiness
   - snapshot mismatch blocks comparison readiness
   - divergence output includes legacy action, V2 action, reason, lineage, and live-blocked status
   - no live/exchange/order/leverage/margin tokens or imports are introduced

5. Add a read-only readiness aggregation test that combines:
   - `ShadowModeReadinessFlag(state="ready", live_blocked=True)`
   - at least one valid same-symbol same-snapshot comparison bundle
   - divergence audit summary
   and proves the live gate remains blocked.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
