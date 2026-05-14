# Codex Review: v2_replay_worker

review_status: PASS
go_no_go: V2_REPLAY_WORKER_CODEX_PASS
live_gate: blocked_human_only
review_date: 2026-05-14

## Scope Audited

- `v2/backend/app/cli/v2_replay_worker.py`
- `v2/backend/tests/integration/cli/test_v2_replay_worker.py`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_legacy_behavior_mapping.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_status.json`
- `v2/frontend/public/operator_runtime/v2_replay_worker/latest/v2_replay_worker_status.json`

## Remediation Verified

- Canonical `legacy_active_symbols` are now always sourced from the V2 Symbol Universe service seeded by `LEGACY_ACTIVE_SYMBOLS_25`; a public payload mismatch is surfaced as `PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED` and cannot override the legacy 25.
- Public Symbol Universe payload-present behavior is tested, including separate `dynamic_discovered_symbols`, `training_symbols`, `paper_symbols`, empty `live_symbols`, Binance USD-M confirmation separation, CoinAnk non-tradability, and the full symbol-selection scoring factor list.
- Legacy `fetch_executions` behavior is preserved by `_index_executions_by_signal_id`, surfaced in the payload, and covered by `test_execution_index_by_signal_id_is_preserved`.
- Replay output paths are repo-relative in public payloads and remain scoped away from `operator_runtime/paper_online/`.

## Validation

- `.venv/bin/python3 -m py_compile v2/backend/app/cli/v2_replay_worker.py v2/backend/tests/integration/cli/test_v2_replay_worker.py`: PASS
- `.venv/bin/pytest -q v2/backend/tests/integration/cli/test_v2_replay_worker.py`: PASS, 21 passed
- JSON validation for worker mapping, worklog status payload, and public status payload: PASS
- Forbidden action scan over replay worker files and artifacts: PASS
- Final live approval token: absent
- Redis trim approval token: absent

## Safety Result

- Old Redis writes: none
- Legacy mutation: none
- Exchange actions: none
- Leverage or margin mutation: none
- Live enablement: none
- Live gate remains `blocked_human_only`

Final decision: V2_REPLAY_WORKER_CODEX_PASS.
