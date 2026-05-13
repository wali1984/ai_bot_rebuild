# Risk Gateway Canary Hard Gates Runtime Proof Report

Generated at: 2026-05-13T06:59:54.381Z

Risk gateway hard-gate proof is READY as a non-live proof package. Canary itself remains blocked: read-only account evidence, trade-permission evidence, weekly-loss runtime emission, and 6h/24h paper proof are not complete. The current paper runtime has current lineage and a paper-only simulated fill, but this is not profitability proof and does not authorize live.

## Test Result

PYTHONPATH=. .venv/bin/pytest v2/backend/tests/unit/composition/live_canary_blocker_guard/test_runtime.py

Result: 30 passed, 0 failed.

## Current Runtime

| Field | Value |
| --- | --- |
| Runtime state | PAPER_RUNTIME_ONLINE_ACTIVE |
| Latest tick | paper_tick_1778655582990 |
| Latest prediction | pred_paper_tick_1778655582990 |
| Latest signal | sig_paper_tick_1778655582990 |
| Latest risk decision | risk_paper_tick_1778655582990 |
| Latest paper event | pledger_paper_tick_1778655582990 |
| Paper events | 3018 |
| Current tail fills | 1 |
| Live gate | blocked_human_only |

## Gate Summary

| Gate | Status | Evidence |
| --- | --- | --- |
| final_approval_token_absent_blocks_live | PASS | Approval token absent and live_gate_status remains blocked_human_only. |
| read_only_account_evidence_required | MISSING_EVIDENCE | No current V2 read-only exchange account payload was found. |
| trade_permission_known_required | MISSING_EVIDENCE | No current V2 trade-permission status payload was found. |
| cross_margin_blocks_canary | PASS | Runtime decision checks cross-margin block code; V2 unit tests cover cross margin intent blocker. |
| isolated_margin_unknown_blocks_canary | PASS | V2 unit tests cover isolated-margin missing/unknown blocker. |
| leverage_cap_unknown_blocks_canary | PASS | V2 unit tests cover missing cap and above-cap blockers. |
| ADJUST_LEVERAGE_disabled_by_default | PASS | Runtime decision checks adjust-leverage block code; V2 unit tests cover adjust-leverage actions. |
| hedge_dca_disabled_initially | PASS | V2 unit tests cover HEDGE and DCA default blockers. |
| missing_signal_id_blocks | PASS | Runtime decision checks missing signal_id; V2 unit tests cover intent blocker. |
| missing_prediction_id_blocks | PASS | Runtime decision checks missing prediction_id; V2 unit tests cover intent blocker. |
| missing_feature_snapshot_id_blocks | PASS | Runtime decision checks missing feature_snapshot_id; V2 unit tests cover intent blocker. |
| missing_confidence_blocks | PASS | Runtime decision checks missing confidence; V2 unit tests cover intent blocker. |
| stale_risk_add_signal_blocks | PASS | Runtime decision checks stale signal; V2 unit tests cover >10s risk-add signal. |
| duplicate_execution_dedupes_or_blocks | PASS | Runtime decision checks duplicate signal execution; V2 unit tests cover duplicate order, intent, signal IDs. |
| mandatory_stop_policy_required | PASS | Runtime decision checks missing stop policy; V2 unit tests cover missing stop. |
| kill_switch_required | PASS | Runtime decision checks disabled kill switch; V2 unit tests cover unhealthy switch. |
| daily_loss_gate_required | PASS | Runtime decision checks daily-loss breach; V2 unit tests cover missing daily gate. |
| weekly_loss_gate_required | MISSING_EVIDENCE | Current runtime decisions still do not list weekly_loss_breach; V2 unit tests cover missing weekly gate. |
| market_and_feature_freshness_required | PASS | Market=CURRENT, feature=CURRENT. |
| live_gate_remains_blocked_human_only | PASS | live_gate_status=blocked_human_only |

## Remaining Blockers

- Read-only account evidence is missing.
- Trade permission evidence is missing.
- Weekly-loss runtime evidence is missing from current risk decisions/runtime payloads.
- 6h/24h paper/shadow profitability proof remains pending.

## Safety

No final approval token was created. No exchange action occurred. No old Redis write occurred. No leverage or margin mode was changed. Live remains blocked_human_only.

## Validation

- `python3 -m py_compile v2/backend/app/composition/live_canary_blocker_guard/runtime.py v2/backend/tests/unit/composition/live_canary_blocker_guard/test_runtime.py` passed.
- `PYTHONPATH=. .venv/bin/pytest v2/backend/tests/unit/composition/live_canary_blocker_guard/test_runtime.py` passed: 30 tests.
- JSON validation passed for generated risk-gate payloads.
- `npm run build:operator-truth` passed.
- `npm run sync:proof-artifacts` passed and mirrored this packet to `v2/frontend/public/risk_gateway_canary_hard_gates/latest/`.
- `npm run typecheck` passed.
- `npm run build` passed.
- Scoped secret and forbidden-action added-line scans passed.
- Final live approval token absent.
- Redis trim approval token absent.
- Scoped `git diff --check` passed. Global `git diff --check` still reports unrelated pre-existing trailing whitespace in `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md`; that file is outside this task scope and was not edited here.
