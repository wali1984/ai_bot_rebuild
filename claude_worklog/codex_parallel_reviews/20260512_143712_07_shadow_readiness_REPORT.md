BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_143712_07_shadow_readiness_REPORT.md
# Codex Parallel Review: Shadow Mode Readiness

Review date: 2026-05-12
Mode: read-only parallel review, except for this requested report artifact.

## Verdict

BLOCKED.

The V2 shadow-readiness flag slice is live-safe and well isolated, and there is local fixture evidence for legacy-vs-V2 comparison output. However, the focused readiness test run is not green: `test_harness_does_not_use_live_side_effect_terms` fails because the proof package contains exact live mutation method tokens in `v2/backend/app/proof/readonly_market_exchange_data_plane.py`. Until that non-live proof/package hygiene issue is resolved, this review cannot mark shadow-mode readiness ready.

## Evidence Reviewed

- `v2/backend/app/domain/shadow_mode_readiness/flag.py`
- `v2/backend/app/services/shadow_mode_readiness/service.py`
- `v2/backend/app/composition/shadow_mode_readiness/runtime.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/shadow_mode_readiness/`
- `v2/backend/tests/unit/services/shadow_mode_readiness/`
- `v2/backend/tests/unit/composition/shadow_mode_readiness/`
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`
- `v2/backend/tests/unit/proof/`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Checks

### Legacy-vs-V2 comparison readiness

Partially ready. Legacy audit requires that shadow mode compare legacy vs V2 (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:15-19`). V2 has fixture proof output for this:

- `v2/backend/app/proof/non_live_operational_proof.py:226-240` emits `shadow_comparison_result` rows with `legacy_action`, `v2_action`, and `diverged`.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:226-239` emits `shadow_comparison_30d` rows with divergence flags.
- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py:74-80` asserts at least one divergence and required legacy/V2 fields.
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py:81-87` asserts historical shadow comparison divergence and blocked live gate status.

### Shadow decisions do not affect live

Pass for the inspected implementation surfaces. `ShadowModeReadinessFlag` requires `live_blocked is True` (`v2/backend/app/domain/shadow_mode_readiness/flag.py:46-55`). The service always returns `live_blocked=True` (`v2/backend/app/services/shadow_mode_readiness/service.py:47-50`) and accepts only `not_ready` or `ready` (`v2/backend/app/services/shadow_mode_readiness/service.py:13-29`). Tests assert rejection of live/live-enabled states and no Redis/FastAPI/lifecycle imports in the 2K slice.

### Same-symbol same-snapshot comparison

Partially ready. The shadow evidence harness preserves V2 decision lineage into risk records:

- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py:141-157` asserts `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` carry from orchestrator decision to risk decision.
- `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/fixtures.py:157-170` builds each comparison input with a single symbol and feature snapshot id.
- Historical replay wiring similarly asserts ledger entries retain `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` from input risk records (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:75-88`) and per-run symbol matching (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:137-144`).

Remaining gap: the legacy side is represented as evidence pointers, not a typed legacy decision payload carrying independently asserted `symbol` and `feature_snapshot_id`. This is acceptable for fixture review, but not enough to claim production shadow comparison readiness without a typed comparator contract.

### Audit output for divergence

Pass for local fixture/proof artifacts. Non-live and historical proof builders emit JSON/Markdown artifacts and divergence counts:

- `v2/backend/app/proof/non_live_operational_proof.py:341-344` writes comparison and divergence counts into Markdown output.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:275-278` exposes `shadow_summary.comparison_count` and `shadow_summary.divergence_count`.

### Live gate remains blocked

Pass for inspected shadow/proof paths. `LIVE_GATE_STATUS` is `blocked_human_only` in proof builders (`v2/backend/app/proof/non_live_operational_proof.py:26`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:11`), shadow readiness flags require `live_blocked=True`, and proof tests assert blocked gate status (`v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py:87`, `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py:70-71`).

## Blockers

1. Focused shadow readiness/proof test suite is red.
   - Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/shadow_mode_readiness v2/backend/tests/unit/services/shadow_mode_readiness v2/backend/tests/unit/composition/shadow_mode_readiness v2/backend/tests/unit/shadow_mode_evidence_collection_harness v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q`
   - Result: 106 passed, 1 failed.
   - Failure: `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py::test_harness_does_not_use_live_side_effect_terms`.

2. Exact live mutation tokens exist under `v2/backend/app/proof/`.
   - `v2/backend/app/proof/readonly_market_exchange_data_plane.py:40-43` lists exact forbidden method names.
   - `v2/backend/app/proof/readonly_market_exchange_data_plane.py:95-105` defines exact forbidden mutation method stubs.
   - The non-live proof test scans all proof modules, so these tokens block readiness even though the file appears to be a read-only fail-closed connector policy.

3. Production-grade same-symbol same-snapshot comparison is not yet a typed legacy-vs-V2 comparator.
   - Current evidence pairs legacy evidence pointers with V2 typed records.
   - There is no inspected domain/service object that validates both legacy and V2 records carry the same symbol and same feature snapshot id before emitting a divergence audit row.

## Proposed Non-Live Autofix Tasks

1. Split `readonly_market_exchange_data_plane.py` token hygiene from proof-package scans without adding live behavior.
   - Option A: reconstruct forbidden method names at runtime in the read-only policy/stub so exact static tokens do not appear under `v2/backend/app/proof/`.
   - Option B: narrow `test_harness_does_not_use_live_side_effect_terms` to the non-live proof modules it intends to validate, while keeping dedicated read-only exchange-data-plane tests for fail-closed mutation stubs.

2. Add a pure, local `ShadowComparisonRecord`/assembler for legacy-vs-V2 audit rows.
   - Inputs: typed legacy observation payload, typed V2 risk or paper record.
   - Guards: same `symbol`, same `feature_snapshot_id`, `live_blocked=True`, no Redis/network/exchange imports.
   - Output: immutable audit row with `legacy_action`, `v2_action`, `diverged`, lineage ids, and `live_gate_status=blocked_human_only`.

3. Add unit tests for the typed comparator.
   - Same symbol/snapshot succeeds.
   - Symbol mismatch fails closed.
   - Snapshot mismatch fails closed.
   - Divergence count appears in JSON/Markdown audit output.
   - No exact live side-effect tokens appear in the shadow proof modules.

## Verification

- Static inspection completed with `rg`, `sed`, and `nl`.
- Focused pytest run completed with cache disabled: 106 passed, 1 failed.

END_FILE: claude_worklog/codex_parallel_reviews/20260512_143712_07_shadow_readiness_REPORT.md
