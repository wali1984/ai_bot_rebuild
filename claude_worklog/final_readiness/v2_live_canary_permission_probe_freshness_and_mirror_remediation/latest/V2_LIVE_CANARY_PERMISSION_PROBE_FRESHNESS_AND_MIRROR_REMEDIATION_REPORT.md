# V2 Live-Canary Permission Probe — Freshness + Mirror Remediation

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_PERMISSION_PROBE_FRESHNESS_AND_MIRROR_REMEDIATION_READY`
**Codex prior fail:** `PERMISSION_PROBE_NOT_READY_AND_PUBLIC_MIRROR_STALE`
**Closes audit finding:** AUD-013 (live-canary approval binding)

## Outcome path A

Per Codex's spec, the acceptable outcomes were:

- **A. READY** if credentials are available and account-read
  succeeds → both mirrors READY.
- B. BLOCKED if credentials are absent → both mirrors BLOCKED.

This packet shipped path **A**: probe transitioned to READY in
both mirrors after the dry-run service loaded
`.local_secrets/live_canary_credentials.env`.

## Two changes shipped

### 1. Dual-mirror inline refresh (kept from prior pass)
`v2/backend/app/cli/v2_live_canary_executor.py` writes the probe
snapshot to BOTH:

- `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json`
- `v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json`

plus the `GO_NO_GO.md` marker, on every dry-run tick.

### 2. Credentialed env binding for the inline probe (new)
`claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service`
now carries:

```
EnvironmentFile=-/home/wali/Desktop/AI BOT REBUILD/.local_secrets/live_canary.env
EnvironmentFile=-/home/wali/Desktop/AI BOT REBUILD/.local_secrets/live_canary_credentials.env
```

The `-` prefix keeps absence non-fatal: if either file is absent
the probe reports a corresponding `*_ENV_VAR_ABSENT` blocker and
both mirrors get the honest BLOCKED snapshot. With both files
present, the inline probe receives `BINANCE_API_KEY` and
`BINANCE_API_SECRET` from the credentials file, calls
`/fapi/v1/exchangeInfo` (public) and `/fapi/v2/account` (signed,
read-only), and reports READY.

The dry-run executor still uses `FakeExchangeAdapter` and never
constructs the real `BinanceFuturesExchangeAdapter`, so the only
credentialed code path that actually fires is the probe's
read-only account-info call.

## Runtime proof (READY)

Both mirrors after the dry-run tick that followed the credentials
load:

```
--- worklog ---
go_no_go=V2_LIVE_CANARY_PERMISSION_PROBE_READY
generated_utc=2026-05-20T19:53:49Z
account_read_permission_status=OK
exchange_info_call_status=OK
binance_api_key_env_present=True
binance_api_secret_env_present=True
exchange_credentials_present=True
raw_credential_in_payload=NEVER
test_order_endpoint_status=NOT_CHECKED_FLAG_NOT_SET

--- public mirror ---
go_no_go=V2_LIVE_CANARY_PERMISSION_PROBE_READY
generated_utc=2026-05-20T19:53:49Z
account_read_permission_status=OK
exchange_info_call_status=OK
binance_api_key_env_present=True
exchange_credentials_present=True
raw_credential_in_payload=NEVER

--- GO_NO_GO marker ---
V2_LIVE_CANARY_PERMISSION_PROBE_READY
```

Mirror consistency invariant met:
- `worklog_go_no_go == public_runtime_go_no_go` → **true**
- `worklog.generated_utc == public.generated_utc` → **true**
- both ages < 600 s ✓
- `account_read_permission_status` agrees on `OK` ✓
- raw credentials never serialized ✓
- test-order endpoint NOT called (its gate flag was not set) ✓

## GATE_3 cleared in the dry-run cascade

Latest dry-run intent record:

```
fail_blockers=[
  GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT,
  GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST,
  GATE_12_LIVE_ENABLED_FALSE,
  GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER,
]
```

The previously-firing
`GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT` and
`GATE_3_PERMISSION_PROBE_STALE_AGE_SECONDS_*` blockers are
**gone**. Every remaining blocker is intentional:

| Blocker | Why intentional |
| --- | --- |
| `GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT` | Codex final review is a separate packet; marker is operator-only. |
| `GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST` | Shadow-observation candidates may carry non-BTCUSDT symbols. |
| `GATE_12_LIVE_ENABLED_FALSE` | Dry-run service pins `live_enabled=False`. |
| `GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER` | Dry-run service pins `dry_run=True`. |

## Tracker update

`AUD-013` (live-canary approval binding) is now **Done**:
- Approval-file parser correctness ✓ (prior pass)
- Mirror consistency invariant ✓ (this packet)
- Probe READY in both mirrors ✓ (this packet)
- GATE_3 cleared from the dry-run cascade ✓ (this packet)

The reopen → done transition is recorded in
[V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md](../../../trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.md)
and [V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json](../../../trackers/V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json).

## Safety pins (unchanged)

- `dry_run=true`
- `live_enabled=false`
- `exchange_adapter_kind=FakeExchangeAdapter`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `private_signed_post_bypass_remediated=true`
- `private_signed_post_callable=false`
- `final_order_post_boundary_count=1`
- `final_post_revalidates_all_gates=true`

## What this packet did NOT do

- Did NOT enable the standalone permission-probe systemd timer
  (the dry-run service's inline probe covers refresh; a separate
  credentialed timer remains a future operator-explicit step).
- Did NOT modify the exchange adapter code.
- Did NOT modify the live gate or live symbols.
- Did NOT modify the approval file or max notional.
- Did NOT enable any live service.
- Did NOT call `/fapi/v1/order`.
- Did NOT call `/fapi/v1/order/test` (both gates remain unset).
- Did NOT change leverage or margin mode.
- Did NOT create any approval token, Codex marker, or live
  enablement.
- Did NOT modify the legacy bot tree.
- Did NOT write any legacy Redis key.
- Did NOT expose raw credentials in any payload, log, or
  artifact (`raw_credential_in_payload=NEVER` enforced by the
  probe service's discard-body design).
- Did NOT touch the website backend service (it remains active +
  enabled with Codex PASS already).

## Test results

- `test_v2_live_canary_permission_probe.py` — **13 passed**
- `test_v2_live_canary_executor.py` — **13 passed**
- `test_v2_live_canary_execution_adapter_operator_gated.py` — **74 passed**
- Total: **100 tests pass**.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 22 files. 0
secret hits, 0 approval_true hits, 0 legacy Redis writes, 0
exchange-mutation verbs, 0 JSON parse failures.

## Operator awareness

The dry-run service now loads BINANCE credentials via
`EnvironmentFile=-`. This means:

- Every 60 s, the dry-run executor's inline probe makes ONE
  signed read-only call to `/fapi/v2/account`.
- The probe NEVER calls `/fapi/v1/order` and NEVER calls
  `/fapi/v1/order/test` (both gates remain disabled).
- The dry-run executor still uses `FakeExchangeAdapter`; there is
  no real-order code path reachable from this process.
- If the operator wants to suspend probe calls, stopping the
  dry-run timer (`stop_v2_live_canary_dry_run.sh`) stops both the
  dry-run cycle and the probe refresh. Both mirrors will then
  freeze at the last snapshot — they will not diverge, just
  become stale, and the gate cascade will fire
  `GATE_3_PERMISSION_PROBE_STALE_AGE_SECONDS_*`.
