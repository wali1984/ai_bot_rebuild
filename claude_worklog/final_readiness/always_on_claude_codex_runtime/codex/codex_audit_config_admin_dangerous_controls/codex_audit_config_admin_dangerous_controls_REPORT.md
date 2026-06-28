# Codex Audit: config admin dangerous controls

Generated: 2026-06-27T22:17:15-04:00  
Scope: non-live audit in `/home/wali/Desktop/AI BOT REBUILD`.

## Verdict

FAIL for final readiness of config/admin dangerous-control truth surfaces.

Safety posture remains fail-closed: I found no active order placement, cancellation, leverage/margin mutation, live-trading enablement, or old-Redis write from this audit. The active backend `/health`, `/api/v1/live-gate/status`, Redis `v2:live_gate:state`, Redis `v2:live_order_transport:status`, and focused tests all keep execution blocked.

## Current runtime truth

- Backend process `uvicorn` runs with `V2_MODE=paper`, `LIVE_GATE=blocked_human_only`, `REDIS_URL=redis://localhost:6379/0`, and `LEGACY_REDIS_URL=redis://localhost:6379/0`.
- Paper loop process `v2_trade_management_paper_loop --loop --interval-seconds 60` runs with `LIVE_GATE=blocked_human_only`.
- Live transport monitor process runs with `--no-submit --skip-validation`.
- `/health` returns `places_real_order=false` and `live_gate=blocked_human_only`.
- `/api/v1/live-gate/status` returns `V2_AUDITED_OPERATOR_LIVE_ACCEPTANCE_AND_ENABLE_FLOW_BLOCKED`, `backend_live_enable_callable=false`, `live_symbols=[]`, `execution_live_symbols=[]`, and blockers:
  - `accepted_risk_profile_fields_do_not_match_current_proposal`
  - `risk_profile_operator_accepted`
  - `website_enable_flow_writes_audit_record`
- Redis `v2:live_gate:state` is stale from 2026-06-12T17:59:32-04:00 and blocked: `live_gate=blocked_human_only`, `live_trading_enabled=false`, `trader_execution_enabled=false`, `order_transport_submit_enabled=false`, `places_real_order=false`, `release_mode=NON_LIVE`.
- Redis `v2:live_order_transport:status` is blocked with blockers including `LIVE_GATE_NOT_ENABLED`, `LIVE_GATE_RUNTIME_STATE_STALE`, `ORDER_TRANSPORT_SUBMIT_NOT_ENABLED`, `LIVE_CANARY:RELEASE_MODE_NON_LIVE`, and `TRADER_EXECUTION_ENABLED_NOT_TRUE`.

## Findings

1. Runtime truth drift: `v2/frontend/public/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json` and `v2/frontend/public/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json` currently report `live_gate=enabled_operator_approved` while also reporting `live_trading_enabled=false`, `live_blocked=true`, `trader_execution_enabled=false`, `order_transport_submit_enabled=false`, and `places_real_order=false`. This is safety-preserving but operator-confusing.

2. Display mirror writes accepted symbols into live execution fields. `build_live_gate_runtime_display_state()` in `v2/backend/app/services/operator_truth/realtime_runtime_truth.py` maps `accepted_live_symbols` into both `live_symbols` and `execution_live_symbols` even when execution is blocked.

3. Several non-execution data/status processes carry `LIVE_GATE=enabled_operator_approved` in their environment: `v2_coinank_direct_runtime_status_publisher`, `v2_liquidation_runtime_status_publisher`, and legacy-owned CoinAnk ingestors under the rebuilt tree. I found no evidence that these processes can submit orders, but the env value violates current runtime truth.

4. Config-admin API module exists but is not mounted. `/api/v1/config-admin/status` falls through to the SPA HTML shell; route listing shows live-gate routes mounted but no config-admin route. The config-admin worker itself builds a safe status, but the API surface is not currently a reliable admin truth endpoint.

5. Historical live acceptance artifacts still contaminate current display state. Live-gate status correctly blocks on current risk-profile mismatch and stale runtime state, but display payloads still show historical accepted symbols and `enabled_operator_approved` language.

## Safety review

- `v2_config_admin_manager.build_status()` is fail-closed: `live_gate=blocked_human_only`, `live_blocked=true`, no approval token creation, no exchange action, no leverage/margin change, no old Redis write, secrets redacted, `live_symbols=[]`.
- Dangerous config defaults are safe: `live_trading_enabled=false`, `live_api_keys_active=false`, `leverage_cap=1`, `margin_mode=ISOLATED_ONLY`, `max_position_usd=0`, `kill_switch_enabled=true`, `mandatory_stop_enabled=true`, `paper_to_live_switch=blocked_human_only`.
- Live-gate API requires superadmin dependency for mutating endpoints, typed confirmations, matching current proposal records, max leverage `1.0`, and release-mode approval.
- Runtime execution state has a `V2_RELEASE_MODE=LIVE_CANARY_APPROVED` backstop; default `NON_LIVE` disarms submit even after approval-chain payload construction.
- Live transport REST order fallback is disabled by default and current transport status is blocked.
- Frontend dangerous controls are rendered disabled in the dedicated dangerous-control panel.

## Remediation task recommendations

1. Canonicalize all public live-gate payloads through `get_canonical_live_gate_status()`. If `live_trading_enabled=false`, `live_blocked=true`, `order_transport_submit_enabled=false`, or `release_mode!=LIVE_CANARY_APPROVED`, public `live_gate` must be `blocked_human_only`.

2. Change `build_live_gate_runtime_display_state()` so accepted historical symbols are not written to `live_symbols` or `execution_live_symbols` unless canonical runtime validation is valid. Use `accepted_live_symbols_display_only` for historical acceptance.

3. Remove `LIVE_GATE=enabled_operator_approved` from market-data/status process environments unless the process is an approved live-execution process and release mode is live-canary approved. Add startup validation that fails closed on this mismatch.

4. Mount `v2/backend/app/api/v1/config_admin.py` or remove stale route assumptions. Add a route test proving `/api/v1/config-admin/status` returns JSON, not the SPA shell, and does not mutate Redis/exchange state.

5. Add a runtime-truth invariant test: no public `operator_runtime/**` payload may report `live_gate=enabled_operator_approved` unless live trading, trader execution, order submit, release mode, and Redis runtime validation are all true.

6. Mark historical live acceptance records as historical/stale when the current proposal hash no longer matches. Current acceptance records must not imply current enablement.

7. Update frontend labels so `enabled_operator_approved` is not rendered as current approval unless `live_order_submit_allowed=true` and `live_blocked=false`.

## Verification

Passed:
- `PYTHONPATH=v2/backend .venv/bin/pytest v2/backend/tests/integration/cli/test_v2_config_admin_manager.py v2/backend/tests/unit/services/live_gate/test_runtime_execution_state.py v2/backend/tests/unit/services/live_gate/test_binance_live_order_transport.py -q`  
  Result: 32 passed.
- `PYTHONPATH=v2/backend .venv/bin/pytest v2/backend/tests/unit/api/test_live_gate.py -q`  
  Result: 7 passed.

No code edits were made. Direct repo file modifications by Codex: none. This report is emitted as the requested artifact block.

## Commands run

Exact command log is summarized below; all were run from `/home/wali/Desktop/AI BOT REBUILD`. Redis usage was read-only (`GET`/`MGET`), API usage was `GET`/`HEAD`, and pytest used temp/fake clients.

- `pwd`
- `git status --short`
- `rg --files -g '!*__pycache__*' -g '!*.pyc' | sed -n '1,200p'`
- `ls`
- Broad `rg` scans for live/order/leverage/margin, Redis, admin/control/safety terms.
- Targeted `rg --files`, `find`, `nl -ba`, and `sed` reads for config-admin, live-gate, runtime truth, auth/RBAC, frontend controls, and tests.
- `ps -eo pid,ppid,stat,lstart,cmd --sort=pid | rg -i 'AI BOT REBUILD|v2_|uvicorn|gunicorn|python|redis|binance|paper|live|trainer|claude|codex'`
- Process-environment read-only Python scans for `LIVE_GATE`, `V2_*`, Redis, release, order, margin, and leverage flags.
- `curl -sS http://127.0.0.1:8000/health`
- `curl -sS http://127.0.0.1:8000/api/v1/live-gate/status`
- `curl -sS -H 'Accept: application/json' -D - http://127.0.0.1:8000/api/v1/config-admin/status`
- `curl -sS -I http://127.0.0.1:8000/api/v1/config-admin/settings`
- `curl -sS -I http://127.0.0.1:8000/api/v1/live-gate/status`
- `redis-cli --no-auth-warning GET v2:live_gate:state`
- `redis-cli --no-auth-warning GET v2:trader:execution_state`
- `redis-cli --no-auth-warning GET v2:trader:accepted_live_symbols`
- `redis-cli --no-auth-warning GET v2:risk:active_profile`
- `redis-cli --no-auth-warning GET v2:live_order_transport:status`
- `redis-cli --no-auth-warning GET v2:live_order_transport:kill_switch`
- `.venv/bin/python` route listing for mounted FastAPI routes.
- `PYTHONPATH=v2/backend .venv/bin/pytest v2/backend/tests/integration/cli/test_v2_config_admin_manager.py v2/backend/tests/unit/services/live_gate/test_runtime_execution_state.py v2/backend/tests/unit/services/live_gate/test_binance_live_order_transport.py -q`
- `PYTHONPATH=v2/backend .venv/bin/pytest v2/backend/tests/unit/api/test_live_gate.py -q`
- `find claude_worklog/final_readiness -maxdepth 4 -type f | rg 'codex_.*REPORT|GO_NO_GO|codex_audit' | sed -n '1,80p'`
- `date -Iseconds`
