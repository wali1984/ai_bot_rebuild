# V2 24h Live-Canary Bring-Up — Implementation Report

**Generated:** 2026-05-19 (UTC)
**GO_NO_GO:** `V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`

This packet ships the minimum controlled bring-up scaffolding for a
24h live-canary path. It is fail-closed by construction:

- No real exchange call exists anywhere in the source.
- The advance method `submit_live_canary_order` raises
  `NotImplementedError("LIVE_ORDER_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVED_PACKET")`.
- The permission probe NEVER opens a network socket in this packet;
  it always reports
  `PERMISSION_PROBE_NETWORK_CALL_DEFERRED_TO_OPERATOR_PACKET`.
- The kill switch fails closed when its value is set to any
  non-empty / non-`false` value, and is also active when Redis is
  unreachable.
- Every status payload pins `approves_*: false`, `live_gate:
  blocked_human_only`, `live_symbols: []`,
  `raw_credential_in_payload: NEVER`,
  `writes_legacy_redis: false`, `writes_exchange_orders: false`,
  `real_order_attempted: false`, `leverage_changed: false`,
  `margin_mode_changed: false`,
  `checkpoint_compatibility_claimed: false`,
  `policy_architecture_parity_claimed: false`.
- The execution adapter's internal `_safe_redis_set` refuses any key
  that is not under `v2:live_canary:*`.
- Systemd unit files are present on disk but are NOT enabled and NOT
  active.

## Phase-by-phase status

### Phase 0 — Truth packet

Captured under
`claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/current_truth.json`:
runtime ready, website ready, shadow-metrics ready,
full-observation partial, checkpoint parity false, policy parity
false, accepted paper fills 0, legacy shutdown not allowed, live
canary possible only with operator approval, default live gate
`blocked_human_only`, default live symbols `[]`, all non-approved
states fail closed.

### Phase 3 — Read-only permission probe

- Service:
  `v2/backend/app/services/live_canary/permission_probe.py`
  - Parses `.local_secrets/live_canary.env` for
    `V2_LIVE_CANARY_MODE` selection, NEVER returning or logging the
    file contents.
  - `PermissionProbeResult` pins
    `test_order_endpoint_attempted=false`,
    `real_order_attempted=false`, `leverage_changed=false`,
    `margin_mode_changed=false`,
    `raw_credential_in_payload="NEVER"`,
    `live_gate="blocked_human_only"`, `live_symbols=()`,
    `approves_*=false`.
  - `run_probe()` always returns `BLOCKED` with at minimum the
    `PERMISSION_PROBE_NETWORK_CALL_DEFERRED_TO_OPERATOR_PACKET`
    blocker.
- CLI: `v2/backend/app/cli/v2_live_canary_permission_probe.py`
  - Writes status to:
    - `claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/permission_probe_status.json`
    - `v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json`

### Phase 4 — Execution adapter + dry-run executor CLI

- Service:
  `v2/backend/app/services/live_canary/execution_adapter.py`
  - `ApprovalEnvelope` constructs `closed_default()` with no
    canary mode selected, no allowed symbols, no notional cap, no
    daily trade/loss caps, and every "approval that must NOT be
    permitted" (leverage/margin/redis-trim/legacy-shutdown) flag set
    to `false`.
  - `evaluate_pretrade_blockers()` returns the full blocker list
    (approval file, codex pass marker, permission probe go state,
    symbol whitelist, notional cap, daily trade count cap, daily
    loss cap, kill switch armed, leverage/margin/redis-trim/legacy-
    shutdown approvals must be `false`, feature freshness CURRENT,
    V2-native mode requires `v2_prediction_present` and
    `paper_fill_gate_open`).
  - `submit_live_canary_order()` persists the intent then raises
    `NotImplementedError` with the sentinel
    `LIVE_ORDER_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVED_PACKET`.
  - `_safe_redis_set()` refuses any key not under
    `v2:live_canary:*`.
  - `parse_approval_file()` parses operator approval markdown by
    `KEY: VALUE` lines; boolean fields are strictly `YES`/`TRUE`/`1`
    (fail closed otherwise).
- CLI: `v2/backend/app/cli/v2_live_canary_executor.py`
  - Reads `v2:paper:shadow_observations` and
    `v2:paper:intents_held_by_paper_fill_gate` (last 20 each),
    builds `IntentCandidate`s, calls `build_intent_record` to
    produce the full blocker list, persists dry-run rows.
  - Writes status to:
    - `claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/live_canary_executor_status.json`
    - `v2/frontend/public/operator_runtime/v2_live_canary/latest/live_canary_executor_status.json`
- Tests:
  `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
  — 13 tests covering: no-approval to operator-approval-required,
  approval-present + probe-blocked to permission-unknown, kill switch
  arm/disarm semantics including fail-closed-on-redis-missing,
  `submit_live_canary_order` raises `NotImplementedError`, notional
  cap, leverage/margin/redis-trim/legacy-shutdown approvals are
  blockers (not allowances), kill-switch-armed blocks, symbol not in
  list blocks, V2-native mode requires `v2_prediction_present` +
  open paper-fill gate + CURRENT freshness, `_safe_redis_set`
  refuses non-live-canary keys, approval parser strict-no default,
  status payload has no raw credentials and no
  `approves_live`/`approves_canary`/etc.=true, permission probe
  always BLOCKED in this packet.
- Test result: **13 passed.**

### Phase 6 — Emergency stop kill-switch CLI

`v2/backend/app/cli/v2_live_canary_kill_switch.py` — actions
`arm` / `disarm` / `status`. Arming is idempotent and immediate.
Disarming is refused unless: operator approval file present + codex
pass marker present + `--confirm` flag. Writes ONLY to
`v2:live_canary:kill_switch`. NEVER places exchange orders. NEVER
flips `live_enabled`.

### Phase 7 — Systemd units (NOT enabled by default)

Created in `claude_worklog/systemd/user/`:

- `ai-bot-v2-live-canary-executor.service`
- `ai-bot-v2-live-canary-executor.timer`
- `ai-bot-v2-live-canary-permission-probe.service`
- `ai-bot-v2-live-canary-permission-probe.timer`

`systemctl --user is-enabled` reports `not-found` and `is-active`
reports `inactive` for both timers (verified pre-install).
ExecStart uses `bash -lc` with escaped spaces to tolerate the repo
path. The executor service runs `--once --dry-run`; the probe
service runs `--once`. Operator must run `systemctl --user
daemon-reload && systemctl --user enable --now <unit>` to schedule
either.

### Phase 8 — Frontend wiring

- `v2/frontend/src/data/realtimeUserWebsitePayloads.ts`
  - New paths: `live_canary_bringup_dashboard`,
    `live_canary_executor_status`,
    `live_canary_permission_probe`.
  - New types: `LiveCanaryDashboardPayload`,
    `LiveCanaryExecutorStatus`,
    `LiveCanaryPermissionProbeStatus`.
  - New hooks: `useLiveCanaryBringupDashboard`,
    `useLiveCanaryExecutorStatus`,
    `useLiveCanaryPermissionProbe`.
- `v2/frontend/src/pages/admin-war-room/index.tsx` — Added a
  read-only panel "24h live-canary bring-up (dry-run scaffolding; no
  controls)" that surfaces go/no-go, live_gate, live_symbols,
  dry_run, live_enabled, real_order_attempted, leverage_changed,
  margin_mode_changed, approval_file_present, codex_pass_marker
  presence, permission_probe go/no-go, intent_count,
  raw_credential_in_payload, the per-intent dry-run table with
  blocker chips, and an explicit note that no control surface exists
  and `submit_live_canary_order` raises `NotImplementedError`.
- `v2/frontend/src/pages/market/index.tsx` — Hero strip's "Live
  gate" cell now reads `canaryDash.payload?.live_gate` (defaulting
  to `blocked_human_only`) and surfaces `canary go/no-go` and
  `live_symbols` count as a detail.
- `npm run typecheck` PASS.

### Phase 9 — Validation sweep

`tools/v2_live_canary_validation_sweep.py` scans every source +
status + systemd artifact for: raw secret regex patterns,
`"approves_X": true` (and related forbidden true keys), legacy
Redis namespaces, exchange-mutation verbs in `.py` files, and JSON
parseability. Result snapshot:

```
{
  "files_scanned": 15,
  "missing_files": [],
  "secret_hits": 0,
  "approval_true_hits": 0,
  "legacy_redis_hits": 0,
  "exchange_mutation_hits": 0,
  "json_parse_failures": 0,
  "status": "PASS"
}
```

## Operator next steps to advance beyond
`V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED`

1. Author and place the operator approval file at
   `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md`
   with `KEY: VALUE` lines for `canary_mode`, `live_symbols`,
   `max_notional_usdt`, `max_daily_live_trades`,
   `max_daily_loss_usdt`, and the four
   `leverage_change_approved`/`margin_mode_change_approved`/
   `redis_trim_approved`/`legacy_shutdown_approved` fields (all four
   MUST stay `NO`).
2. Place `.local_secrets/live_canary.env` with
   `V2_LIVE_CANARY_MODE=V2_NATIVE_SIGNAL_CANARY` (or
   `LEGACY_SIGNAL_V2_EXECUTION_CANARY`). The file's contents are
   NEVER read into payloads beyond the mode label.
3. Submit this packet to Codex for adversarial review. When
   Codex passes, place the marker file at
   `claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/codex_review/CODEX_LIVE_CANARY_PASS.marker`.
4. Build and submit a separate operator-approved packet that wires
   the real exchange call. The current
   `submit_live_canary_order` will continue to raise
   `NotImplementedError` until that packet ships.
5. (Optional) `systemctl --user daemon-reload` then `systemctl
   --user enable --now ai-bot-v2-live-canary-executor.timer
   ai-bot-v2-live-canary-permission-probe.timer` to begin the
   dry-run scheduling cadence. The executor still cannot place real
   orders because the submit method is `NotImplementedError`.

## What this packet did NOT do

- Did NOT modify the legacy bot working tree at
  `/home/wali/Desktop` — only the rebuild tree under this repo.
- Did NOT stop or shut down legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT change leverage or margin mode.
- Did NOT create any approval tokens.
- Did NOT expose raw API key values; the probe parses a file but
  NEVER returns or logs its contents — only the validated mode
  label.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT add any symbol to `live_symbols`.
- Did NOT install or enable any systemd timer.
- Did NOT claim checkpoint compatibility or policy parity.
- Did NOT call `subprocess.run`, `socket.connect`, or any HTTP
  client.

## Source pointers

- `v2/backend/app/services/live_canary/permission_probe.py:142-198`
  — `run_probe` always BLOCKED with sentinel.
- `v2/backend/app/services/live_canary/execution_adapter.py:333-357`
  — `submit_live_canary_order` raises `NotImplementedError`.
- `v2/backend/app/services/live_canary/execution_adapter.py:62-83`
  — `_safe_redis_set` namespace allowlist.
- `v2/backend/app/services/live_canary/execution_adapter.py:86-104`
  — kill-switch fail-closed semantics.
- `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
  — full gate-cascade coverage; all 13 tests pass.
- `tools/v2_live_canary_validation_sweep.py` — adversarial offline
  scanner; PASS at 15 files scanned, 0 hits.
