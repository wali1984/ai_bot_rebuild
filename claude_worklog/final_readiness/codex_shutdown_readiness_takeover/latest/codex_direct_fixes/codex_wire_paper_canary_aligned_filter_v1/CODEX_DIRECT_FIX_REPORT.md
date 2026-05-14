# Codex Direct Fix - paper_canary_aligned_filter_v1

As of: 2026-05-14T22:40:46Z

Result: V2 paper execution boundary now evaluates the existing canary-profile tightening predicate before materializing an allowed paper fill.

Changed files:

- `v2/backend/app/cli/v2_paper_execution_worker.py`
- `v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py`

Behavior:

- Allow decisions call `build_canary_profile_tightening_runtime(...).evaluate_now(...)` before the paper ledger recorder is invoked.
- If the predicate blocks the intent, the worker emits `ledger_action=denied_by_paper_filter`, uses the first blocker as `ledger_reason_code`, records no fill, and keeps `live_gate=blocked_human_only`.
- Deny decisions and missing runtime evidence remain fail-closed.
- The public worker payload now includes `paper_filter_profile`, `paper_filter_applied`, `paper_filter_denied`, `paper_filter_classification`, blocker, cost, confidence, and recent-fill evidence fields.

Legacy evidence:

- `rl/unified_feature_builder.py` full-runtime SHA256 `2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5`
- `rl/obs_schema.py` full-runtime SHA256 `9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f`
- `rl/increase_signal_validator.py` full-runtime SHA256 `6b1dbcb61bac934038d7be3ca16721453e4eda7263c6f7527c5583f23c7d12a0`
- `rl/advanced_risk_management.py` full-runtime SHA256 `db2fc5c91f270f69790c4d3e25e9b6007384b6c788a2c6dc00cf3305cf829697`

Validation:

- `.venv/bin/python3 -m py_compile v2/backend/app/cli/v2_paper_execution_worker.py v2/backend/app/composition/canary_profile_tightening/runtime.py`
- `PYTHONPATH=. .venv/bin/pytest v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py v2/backend/tests/unit/composition/canary_profile_tightening -q` -> 44 passed
- Risk/paper expanded subset -> 172 passed
- Account/freshness subset -> 32 passed
- `npm run build:operator-truth` from `v2/frontend` -> passed
- `npm run sync:proof-artifacts` from `v2/frontend` -> passed
- `npm run typecheck` from `v2/frontend` -> passed
- `npm run build` from `v2/frontend` -> passed
- `git diff --check` on scoped files -> passed
- `git fsck --no-dangling --connectivity-only` -> passed
- High-confidence secret scan -> passed
- High-confidence forbidden-action scan -> passed

Shutdown impact:

This direct fix closes the concrete worker-wiring defect from the failed Codex paper-edge review, but it does not clear `PAPER_PNL_NEGATIVE_BLOCKS_CANARY` or `PAPER_EDGE_UNPROVEN`. Fresh paper/shadow soak evidence is still required before shutdown can advance.

Safety:

- live gate remains `blocked_human_only`
- `live_symbols` remains `[]`
- final approval token remains absent
- Redis trim approval remains absent
- no old Redis write was introduced
- no exchange action, leverage change, or margin-mode change was introduced
