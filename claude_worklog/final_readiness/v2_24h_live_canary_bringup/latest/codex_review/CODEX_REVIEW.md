# Codex Review: V2 24h Live-Canary Bring-Up

Generated: `2026-05-19T02:24:13Z`

GO/NO-GO: `V2_24H_LIVE_CANARY_CODEX_PASS_OPERATOR_APPROVAL_REQUIRED`

## Decision

Codex passes the packet only at the operator-approval-required, fail-closed scaffolding scope. The dry-run executor and read-only permission probe are safe to keep as status/audit surfaces, but this review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

The current runtime state is still blocked:

- operator approval file: absent
- Codex live-canary pass marker: absent
- `.local_secrets/live_canary.env`: absent
- permission probe: `V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED`
- executor: `V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED`
- `dry_run=true`
- `live_enabled=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

No live order can be placed from this packet because `submit_live_canary_order()` still raises `NotImplementedError` with the sentinel `LIVE_ORDER_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVED_PACKET`.

## Evidence Reviewed

Reviewed:

- `v2/backend/app/services/live_canary/permission_probe.py`
- `v2/backend/app/services/live_canary/execution_adapter.py`
- `v2/backend/app/cli/v2_live_canary_permission_probe.py`
- `v2/backend/app/cli/v2_live_canary_executor.py`
- `v2/backend/app/cli/v2_live_canary_kill_switch.py`
- `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
- `tools/v2_live_canary_validation_sweep.py`
- `claude_worklog/systemd/user/ai-bot-v2-live-canary-*`
- `claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/*`
- `v2/frontend/public/operator_runtime/v2_live_canary/latest/*`
- frontend `/market` and `/admin/war-room` live-canary displays

The packet GO/NO-GO remains `V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED`.

## Gate Cascade

Codex verified the live-canary gate cascade requires, at minimum:

- operator approval file present;
- Codex pass marker present;
- permission probe `READY`;
- symbol in the approved whitelist;
- requested notional within `max_notional_usdt`;
- daily trade count below `max_daily_live_trades`;
- daily realized loss below `max_daily_loss_usdt`;
- kill switch not armed;
- no leverage, margin, Redis-trim, or legacy-shutdown approval flags;
- V2-native mode also requires a V2 prediction and open strict paper-fill gate.

The permission probe never opens a network socket in this packet and remains blocked with `PERMISSION_PROBE_NETWORK_CALL_DEFERRED_TO_OPERATOR_PACKET`. Therefore this packet is not ready for operator final approval; it is only ready as blocked dry-run scaffolding.

## Runtime And Redis

Codex ran the permission probe and dry-run executor once.

Observed Redis keys were limited to:

- `v2:live_canary:intents`
- `v2:live_canary:ledger`
- `v2:live_canary:heartbeat`
- `v2:live_canary:status`

The live Redis payloads show:

- `live_enabled=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `live_symbols=[]`

The adapter `_safe_redis_set` refuses non-`v2:live_canary:*` keys, including old Redis namespaces and paper-position keys.

## Systemd

The live-canary systemd unit files are present but not installed/enabled in the user manager:

- executor timer: inactive / not-found
- permission-probe timer: inactive / not-found
- executor service: inactive
- permission-probe service: inactive

That matches the packet claim that systemd units are staged but not enabled by default. The unit files use the quoted/escaped workspace path and `LIVE_GATE=blocked_human_only`.

## Frontend

The public `/market` surface only displays live-canary status in the hero safety strip. It has no order entry, shutdown, leverage, or margin control.

The admin `/admin/war-room` live-canary panel is read-only. It surfaces approval absence, Codex marker absence, permission-probe blockers, dry-run intents, `live_enabled=false`, `real_order_attempted=false`, and the `NotImplementedError` submission boundary. It has no unreviewed one-click live order control.

The realtime website Codex review remains passed:

`V2_REALTIME_USER_WEBSITE_FROM_REAL_PAYLOADS_CODEX_PASS`

## Safety

Codex verified:

- no raw secret-value hits outside `.local_secrets`;
- no old Redis write path in the reviewed live-canary source;
- no reachable exchange order placement/cancel/modify implementation;
- no leverage or margin mutation path;
- no live/canary/shutdown/Redis-trim approval drift;
- full observation remains partial;
- `checkpoint_compatibility_claimed=false`;
- `policy_architecture_parity_claimed=false`;
- legacy shutdown remains blocked;
- live-canary is not represented as full production equivalence.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Runtime Governors

The standing governors remain healthy:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`

Full observation remains partial and does not claim parity.

## Validation

- Focused live-canary tests: `44 passed`.
- `py_compile`: PASS.
- Live permission-probe one-shot: PASS, blocked as expected.
- Live executor dry-run one-shot: PASS, `V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED`.
- Packet validation sweep: PASS.
- Frontend typecheck: PASS.
- Raw secret-value scan: PASS, `0` hits outside `.local_secrets`.
- Redis write boundary check: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Non-Approval Items

This review does not create the Codex pass marker file and does not create any operator approval. The next true gates before live canary are:

- operator approval file with explicit limits;
- local live-canary mode selection;
- separate reviewed exchange permission probe packet;
- separate reviewed exchange submission packet, because order submission is not implemented here.

## Final Decision

`V2_24H_LIVE_CANARY_CODEX_PASS_OPERATOR_APPROVAL_REQUIRED`
