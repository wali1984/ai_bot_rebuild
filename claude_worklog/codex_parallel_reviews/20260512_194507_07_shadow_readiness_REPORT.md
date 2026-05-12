BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_194507_07_shadow_readiness_REPORT.md
# Codex Parallel Review: Shadow Mode Readiness

Review date: 2026-05-12
Mode: read-only parallel review, except for this requested report artifact.

## Verdict

BLOCKED.

The inspected V2 shadow-mode-readiness flag, service, and composition-root surfaces remain live-safe: they only accept `not_ready` / `ready` readiness states, every produced readiness flag carries `live_blocked=True`, and the online-readiness gate reports `blocked_human_only`. However, shadow readiness is not ready for promotion because the focused proof suite is still red and the existing legacy-vs-V2 comparison evidence is fixture/harness based rather than a production typed comparator that fails closed on symbol or snapshot mismatch before emitting divergence audit rows.

## Evidence Reviewed

- `v2/backend/app/domain/shadow_mode_readiness/flag.py`
- `v2/backend/app/services/shadow_mode_readiness/service.py`
- `v2/backend/app/composition/shadow_mode_readiness/runtime.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/online_readiness_aggregator.py`
- `v2/backend/app/api/v1/live_readiness.py`
- `v2/backend/tests/unit/domain/shadow_mode_readiness/`
- `v2/backend/tests/unit/services/shadow_mode_readiness/`
- `v2/backend/tests/unit/composition/shadow_mode_readiness/`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`
- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Checks

### Legacy-vs-V2 comparison readiness

Partially ready. The fixture proof builder emits comparison rows with `legacy_action`, `v2_action`, and `diverged` fields in `v2/backend/app/proof/non_live_operational_proof.py:226-240`, and historical proof emits equivalent 30-day fixture rows in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`. Tests assert at least one divergence in `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py` and `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`.

Blocker: this is not yet a production V2 comparator contract. The test-only harness `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-76` pairs a `legacy_action_evidence_pointer` with a V2 `RiskDecisionRecord`; it does not accept a typed legacy decision payload and does not validate legacy and V2 `symbol` / `feature_snapshot_id` fields against each other before audit emission.

### Shadow decisions do not affect live

Pass for inspected surfaces. `ShadowModeReadinessFlag` allows only `not_ready` / `ready` and rejects any `live_blocked` value other than `True` in `v2/backend/app/domain/shadow_mode_readiness/flag.py:8-55`. The service accepts only the two allowed states and constructs the flag with literal `live_blocked=True` in `v2/backend/app/services/shadow_mode_readiness/service.py:13-51`. No inspected shadow-readiness code places orders, cancels orders, changes leverage, changes margin, writes Redis, restarts services, or exposes a live-enable branch.

### Same-symbol same-snapshot comparison

Blocked for production readiness. V2 replay/backtest service coverage does reject paper ledger vs replay-run symbol mismatch, and the evidence harness carries V2 `symbol` and `feature_snapshot_id` lineage through risk decisions. The missing piece is a typed legacy-vs-V2 shadow comparison record where both sides independently carry `symbol` and `feature_snapshot_id`, and where mismatch fails closed before any divergence row is emitted.

### Audit output for divergence

Partially ready. The non-live proof writer emits JSON/Markdown shadow comparison artifacts and includes divergence counts in Markdown output at `v2/backend/app/proof/non_live_operational_proof.py:341-344`. Historical proof exposes `shadow_summary.comparison_count` and `shadow_summary.divergence_count`. This is useful operator evidence, but it is based on deterministic fixtures and not backed by the typed comparator guard described above.

### Live gate remains blocked

Pass. `LIVE_GATE_STATUS` is `blocked_human_only` in the online-readiness aggregator at `v2/backend/app/proof/online_readiness_aggregator.py:63`, and rollups include the same live gate status at `v2/backend/app/proof/online_readiness_aggregator.py:310-316`. The live-readiness API banner is read-only and returns the aggregator rollup without importing the writer helper.

## Blockers

1. Focused shadow-readiness/proof test suite is red.
   - Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/shadow_mode_readiness v2/backend/tests/unit/services/shadow_mode_readiness v2/backend/tests/unit/composition/shadow_mode_readiness v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q`
   - Result: 93 passed, 1 failed.
   - Failure: `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py::test_harness_does_not_use_live_side_effect_terms`.

2. Exact live mutation method tokens remain under `v2/backend/app/proof/`, which the proof hygiene test scans.
   - `v2/backend/app/proof/readonly_market_exchange_data_plane.py:40-43` lists `create_order`, `cancel_order`, `change_leverage`, and `change_margin`.
   - `v2/backend/app/proof/readonly_market_exchange_data_plane.py:95-105` defines stubs with the same exact names.
   - These stubs are fail-closed, but their exact tokens still fail the current non-live proof scan.

3. No production typed same-symbol same-snapshot legacy-vs-V2 comparator was found.
   - Existing shadow comparison output is fixture generated.
   - The test harness comparison record has only `legacy_action_evidence_pointer` and `v2_risk_decision_record`, so it cannot prove legacy and V2 were compared for the same symbol and same feature snapshot.

## Proposed Non-Live Autofix Tasks

1. Fix proof-package token hygiene without adding live capability.
   - Keep the read-only exchange connector fail-closed.
   - Either reconstruct forbidden method names at runtime so exact static tokens do not appear under `v2/backend/app/proof/`, or narrow the non-live proof scan to the specific proof harness modules while retaining dedicated fail-closed tests for the read-only data-plane stubs.

2. Add a pure typed shadow-comparison domain/service surface.
   - Inputs: typed legacy observation/decision payload and typed V2 risk or paper record.
   - Guards: same `symbol`, same `feature_snapshot_id`, `live_blocked=True`, and no Redis/network/exchange imports.
   - Output: immutable audit row with legacy action, V2 action, divergence flag, lineage IDs, `live_gate_status=blocked_human_only`, and operator note.

3. Add comparator tests.
   - Same symbol and same snapshot succeeds.
   - Symbol mismatch fails closed.
   - Snapshot mismatch fails closed.
   - Divergence count appears in JSON and Markdown audit output.
   - Live mutation tokens remain absent from shadow proof modules.

## Verification

- Static inspection completed with `rg`, `sed`, and `nl`.
- Focused pytest run completed with cache disabled: 93 passed, 1 failed.

END_FILE: claude_worklog/codex_parallel_reviews/20260512_194507_07_shadow_readiness_REPORT.md
