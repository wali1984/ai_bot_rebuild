# Lane 1 — V2 Live-Canary Dry-Run Approval Binding Remediation

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY`
**Closes audit finding:** AUD-013

## Two changes shipped

### 1. Approval-file parser binds to the operator's prose template
`parse_approval_file` now accepts both the strict ``KEY: VALUE``
form and the natural-language form used by
`claude_worklog/approvals/OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md`:

- `Approved live canary mode:` → `canary_mode`
- `Approved live symbols:` → `live_symbols`
- `Max notional USDT per order:` → `max_notional_usdt`
- `Max daily live trades:` → `max_daily_live_trades`
- `Max daily loss USDT:` → `max_daily_loss_usdt`
- `live_gate target for canary only:` → `runtime_live_gate`
- `live_symbols target for canary only:` → `runtime_live_symbols`

Prose-deny sentences (`Leverage change is not approved.`,
`Margin mode change is not approved.`, `Redis trim is not
approved.`, `Legacy shutdown is not approved.`) now BIND those
four mutation-approval flags to `False` regardless of any
contradicting `KEY: YES` line elsewhere in the file.

### 2. Permission probe refresh happens inline per dry-run tick
The dry-run executor's `run_once()` writes the probe snapshot to
`claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json`
on every tick, so the executor's gate-3 freshness check always
reads a current snapshot. The systemd permission-probe TIMER is
**not** enabled in this packet (timer-enable was intentionally
rejected — a recurring credentialed Binance call is operator
infrastructure, not a code-side default).

The `.local_secrets/live_canary.env` file is loaded into the
dry-run systemd service via `EnvironmentFile=-…`. Credentials are
NOT loaded into the dry-run service env (FakeExchangeAdapter
doesn't need them). Both systemd unit files now carry these
`EnvironmentFile=-` directives:
- `ai-bot-v2-live-canary-dry-run.service` — config only
- `ai-bot-v2-live-canary-permission-probe.service` — config +
  credentials (loaded if file exists; operator action to enable
  the probe timer if needed)

## Runtime proof

After the dry-run service runs one tick under the new build:

```
approval_file_present=True
canary_mode_selected=LEGACY_SIGNAL_V2_EXECUTION_CANARY
allowed_symbols=['BTCUSDT']
max_notional_usdt=55.0
max_daily_live_trades=1
max_daily_loss_usdt=5.0
runtime_live_gate_requested=live_canary_operator_approved
runtime_live_symbols_requested=['BTCUSDT']
leverage_change_approved=False
margin_mode_change_approved=False
redis_trim_approved=False
legacy_shutdown_approved=False

fail_blockers=[
  GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT,
  GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT,
  GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST,
  GATE_12_LIVE_ENABLED_FALSE,
  GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER,
]
```

The previously-firing `GATE_3_PERMISSION_PROBE_STALE_AGE_SECONDS_*`
blocker is **gone**. Every remaining blocker is INTENTIONAL:

| Blocker | Why it's intentional |
| --- | --- |
| `GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT` | Final operator+Codex approval is a separate, dedicated packet. |
| `GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT` | The probe now runs FRESH on every tick but cannot reach READY without operator-shell BINANCE credentials; the dry-run service does NOT carry creds in its Environment by design. |
| `GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST` | Shadow-observation candidates may carry non-BTCUSDT symbols; the gate correctly refuses them. |
| `GATE_12_LIVE_ENABLED_FALSE` | dry-run service pins `live_enabled=False`. |
| `GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER` | dry-run service pins `dry_run=True`. |

## Safety pins (unchanged)

`dry_run=true`, `live_enabled=false`,
`exchange_adapter_kind=FakeExchangeAdapter`,
`real_order_attempted=false`, `real_order_submitted=false`,
`writes_exchange_orders=false`, `writes_legacy_redis=false`,
`leverage_changed=false`, `margin_mode_changed=false`,
`live_gate=blocked_human_only`, `live_symbols=[]`,
`approves_*=false`, `raw_credential_in_payload=NEVER`,
`private_signed_post_bypass_remediated=true`,
`final_post_revalidates_all_gates=true`.

## What this packet did NOT do

- Did NOT enable the permission-probe systemd timer.
- Did NOT add BINANCE credentials to the dry-run service env.
- Did NOT modify the legacy bot tree.
- Did NOT write any legacy Redis key.
- Did NOT call `/fapi/v1/order` or `/fapi/v1/order/test`.
- Did NOT create a Codex final pass marker.
- Did NOT flip `live_gate` or `live_symbols`.
- Did NOT add any frontend control button.
- Did NOT install missing pip packages.
- Did NOT touch any other audit finding.

## Test totals (unchanged from prior packet)

- 100 live-canary tests pass (13 executor + 13 probe + 74
  operator-gated, including the three new approval-binding tests).

## Source pointers

- [v2/backend/app/cli/v2_live_canary_executor.py](v2/backend/app/cli/v2_live_canary_executor.py)
  — inline probe-status refresh added inside `run_once()`.
- [v2/backend/app/services/live_canary/execution_adapter.py](v2/backend/app/services/live_canary/execution_adapter.py)
  — `APPROVAL_FILE_KEY_ALIASES` + `APPROVAL_FILE_PROSE_DENIES`.
- [claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service](claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service)
  — `EnvironmentFile=-…live_canary.env`.
- [claude_worklog/systemd/user/ai-bot-v2-live-canary-permission-probe.service](claude_worklog/systemd/user/ai-bot-v2-live-canary-permission-probe.service)
  — optional `EnvironmentFile=-…live_canary.env` and
  `EnvironmentFile=-…live_canary_credentials.env` (operator
  action required to enable the probe timer).
