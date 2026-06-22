# V2 Live-Canary Dry-Run Service — Implementation Report

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_DRY_RUN_SERVICE_READY`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`
**Default `exchange_adapter_kind`:** `FakeExchangeAdapter`

## What this packet did

After the final operator-approval review passed Codex, the next
approved gate is dry-run service validation: enable the V2 live-canary
executor on a systemd user timer in dry-run mode only, prove the
service ticks, and prove that no real order is reachable from this
service surface.

This packet:

1. Ships explicit dry-run systemd unit files:
   - `claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service`
   - `claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.timer`
2. Ships operator helper scripts:
   - `start_v2_live_canary_dry_run.sh`
   - `status_v2_live_canary_dry_run.sh`
   - `stop_v2_live_canary_dry_run.sh`
3. Symlinks the units into `~/.config/systemd/user/`, runs
   `daemon-reload`, and enables + starts the timer.
4. Verifies the timer is active + enabled, the first tick fires,
   and the resulting Redis state shows the executor running with
   `FakeExchangeAdapter`, `dry_run=true`, `live_enabled=false`.
5. Refreshes the operator dashboard payload at
   `v2/frontend/public/v2_live_canary_dry_run_service/latest/operator_dashboard_payload.json`
   and the live-canary runtime payload at
   `v2/frontend/public/operator_runtime/v2_live_canary/latest/v2_live_canary_status.json`.
6. Extends the `/admin/war-room` live-canary panel with new chips
   for `dry_run_service_active`, `private_signed_post_callable`,
   `final_order_post_boundary_count`, and `exchange_adapter_kind`.
   No buttons. No live controls. No order controls.
7. Includes the dry-run unit files in the offline validation sweep
   (now 22 files scanned, all PASS).

## Runtime proof

- `systemctl --user is-active ai-bot-v2-live-canary-dry-run.timer` → `active`
- `systemctl --user is-enabled ai-bot-v2-live-canary-dry-run.timer` → `enabled`
- Timer cadence: every 60s (`OnUnitActiveSec=60s`)
- Service type: `oneshot`
- ExecStart runs `python3 -m v2.backend.app.cli.v2_live_canary_executor --once --dry-run`
- Working directory: `/home/wali/Desktop/AI BOT REBUILD`
- Environment pinned: `LIVE_GATE=blocked_human_only`,
  `V2_LIVE_CANARY_DRY_RUN=true`
- Service log: `claude_worklog/agent_supervisor/logs/control_plane/v2_live_canary_dry_run.log`

Redis state after the first scheduled tick:

- `v2:live_canary:heartbeat` — fresh; safety pins intact.
- `v2:live_canary:status` — fresh; payload safety pins intact:
  - `dry_run=true`
  - `live_enabled=false`
  - `real_order_submitted=false`
  - `real_order_attempted=false`
  - `places_real_order=false`
  - `writes_exchange_orders=false`
  - `writes_legacy_redis=false`
  - `leverage_changed=false`
  - `margin_mode_changed=false`
  - `live_gate=blocked_human_only`
  - `live_symbols=[]`
  - `exchange_adapter_kind=FakeExchangeAdapter`
  - `private_signed_post_bypass_remediated=true`
  - `private_signed_post_callable=false`
  - `final_order_post_boundary_count=1`
  - `final_post_revalidates_all_gates=true`
- `v2:live_canary:intents` — populated with dry-run intent records
  whose `fail_blockers` list every GATE the cascade flags
  (operator-final 14-gate plus the appropriate informational
  blockers from the executor's runtime checks). No intent has
  `real_order_attempted=true` or `real_order_submitted=true`.
- `v2:live_canary:ledger` — every entry pinned to dry-run; zero
  entries with `real_order_attempted=true`, zero with
  `real_order_submitted=true`, zero with
  `writes_exchange_orders=true`.

## Kill switch dry-run proof

The dry-run service inherits the executor's kill-switch behavior.
Direct unit tests prove the property:

- `test_gate_11_blocks_when_kill_switch_armed` — PASS
- `test_direct_import_with_kill_switch_armed_makes_zero_urlopen_calls` — PASS
- `test_kill_switch_active_when_set_or_missing` — PASS
- `test_kill_switch_armed_blocks` — PASS

These four tests collectively prove that when
`v2:live_canary:kill_switch` is set to any truthy value (or when
Redis is unreachable), the executor's gate cascade records
`GATE_11_KILL_SWITCH_ARMED` and refuses to advance to any
exchange-shaped action. The fail-closed semantic also applies when
the Redis connection itself is `None`.

The kill switch was NOT armed during this validation cycle (no
operator instruction to do so); the unit-test proof is sufficient.

## What this packet did NOT do

- Did NOT place a real order.
- Did NOT call the real exchange network in any code path; the
  service uses `FakeExchangeAdapter` only.
- Did NOT cancel or modify any order.
- Did NOT change leverage or margin mode.
- Did NOT enable live trading.
- Did NOT create any operator approval token or final Codex marker.
- Did NOT add any symbol to `live_symbols`.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT touch the kill switch state.
- Did NOT modify the legacy bot tree or stop legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT enable any live-canary executor / permission-probe timer
  beyond the explicit DRY-RUN unit shipped here.
- Did NOT expose any raw API key/secret value in payloads or logs.
- Did NOT add any frontend control surface; the war-room panel is
  display-only with no buttons.
- Did NOT drift into website, paper analytics, full observation,
  alt-data, checkpoint, policy-architecture, or shutdown work.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 22 files
scanned (6 source + 6 systemd unit files including the new dry-run
units + status payloads + test files in their separate band):

```
{
  "files_scanned": 22,
  "missing_files": [],
  "secret_hits": 0,
  "approval_true_hits": 0,
  "legacy_redis_hits": 0,
  "exchange_mutation_hits": 0,
  "json_parse_failures": 0,
  "status": "PASS"
}
```

## Test results

- `test_v2_live_canary_execution_adapter_operator_gated.py` — **71 passed**.
- `test_v2_live_canary_executor.py` — **13 passed**.
- `test_v2_live_canary_permission_probe.py` — **13 passed**.
- Total: **97 passed.**
- `npm run typecheck` (frontend) — PASS.

## Operator next steps

1. Submit this dry-run service packet to Codex for review.
2. The dry-run timer continues running every 60s; safety pins
   never change regardless of cadence.
3. To pause: run
   `claude_worklog/systemd/user/stop_v2_live_canary_dry_run.sh`.
   This does NOT modify the kill switch and does NOT touch live
   mode.
4. To verify health at any time: run
   `claude_worklog/systemd/user/status_v2_live_canary_dry_run.sh`.
5. Final live-canary enablement remains a separate, reviewed
   packet. This dry-run service does not advance toward real
   orders by itself.

## Source pointers

- [ai-bot-v2-live-canary-dry-run.service](claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service)
- [ai-bot-v2-live-canary-dry-run.timer](claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.timer)
- [start_v2_live_canary_dry_run.sh](claude_worklog/systemd/user/start_v2_live_canary_dry_run.sh)
- [status_v2_live_canary_dry_run.sh](claude_worklog/systemd/user/status_v2_live_canary_dry_run.sh)
- [stop_v2_live_canary_dry_run.sh](claude_worklog/systemd/user/stop_v2_live_canary_dry_run.sh)
- [v2/backend/app/services/live_canary/execution_adapter.py](v2/backend/app/services/live_canary/execution_adapter.py)
  — single `urlopen` call site inside `submit_signed_canary_order`.
- [v2/backend/app/cli/v2_live_canary_executor.py](v2/backend/app/cli/v2_live_canary_executor.py)
  — dry-run CLI invoked by the timer.
- [v2/frontend/src/pages/admin-war-room/index.tsx](v2/frontend/src/pages/admin-war-room/index.tsx)
  — display-only dry-run service chips.

## Non-approvals (unchanged)

This dry-run-service packet does NOT approve live trading, canary
trading, exchange mutation, leverage/margin change, Redis trim,
legacy shutdown, checkpoint compatibility, policy architecture
parity, or production equivalence. Final live-canary enablement
requires a separate, operator-reviewed entrypoint after the
dry-run service is validated.
