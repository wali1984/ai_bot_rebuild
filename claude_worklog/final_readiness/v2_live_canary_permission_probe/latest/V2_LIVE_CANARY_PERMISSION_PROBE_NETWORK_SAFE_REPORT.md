# V2 Live-Canary Network-Safe Permission Probe — Implementation Report

**Generated:** 2026-05-19 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED`
**Probe state:** non-mutating; no real order placed
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`

This packet upgrades the live-canary permission probe from the
network-deferred scaffolding state to a real but non-mutating
Binance Futures probe. The probe NEVER places a real order, NEVER
cancels or modifies orders, NEVER changes leverage or margin mode,
NEVER writes legacy Redis, and NEVER returns or logs raw API
credential values.

## What the probe now does

1. Reads the operator config file at
   `.local_secrets/live_canary.env` and surfaces only V2_LIVE_CANARY_*
   keys (the file's other lines, including any accidentally placed
   credential lines, are dropped at parse time).
2. Reads credential PRESENCE (not value) from OS env vars
   `BINANCE_API_KEY` and `BINANCE_API_SECRET`.
3. Calls Binance Futures `/fapi/v1/exchangeInfo` (public, read-only)
   to extract per-symbol tradability, MIN_NOTIONAL, LOT_SIZE
   stepSize, and PRICE_FILTER tickSize.
4. Calls Binance Futures `/fapi/v2/account` (signed GET, read-only)
   to verify the account-read permission. The signed response body
   is discarded; only the HTTP status is mapped to a status label
   so account balances / addresses / positions can never leak.
5. The documented Binance no-fill validation endpoint
   `/fapi/v1/order/test` is reachable ONLY when BOTH gates are
   open:
   - `V2_LIVE_CANARY_ALLOW_TEST_ORDER=true` in the env config file
   - A Codex test-order-docs marker present at
     `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/codex_review/CODEX_TEST_ORDER_DOCS_APPROVED.marker`
   When either gate is closed the probe returns an explicit
   `NOT_CHECKED_*` reason without touching that path.
6. Outputs explicit blockers for every missing precondition
   instead of guessing.

## Output payload fields (exactly per request)

- `go_no_go`
- `exchange_credentials_present` (`true` / `false`)
- `raw_credential_in_payload` (always `NEVER`)
- `mode_selected`
- `symbols_requested`
- `symbols_tradable`
- `min_notional_by_symbol`
- `step_size_by_symbol`
- `tick_size_by_symbol`
- `account_read_permission_status`
- `test_order_endpoint_status`
- `real_order_attempted` (always `false`)
- `leverage_changed` (always `false`)
- `margin_mode_changed` (always `false`)
- `writes_exchange_orders` (always `false`)
- `writes_legacy_redis` (always `false`)
- `live_gate` (always `blocked_human_only`)
- `live_symbols` (always `[]`)
- Plus: `exchange_info_call_status`, `test_order_endpoint_attempted`,
  `fail_blockers`, `network_probe_enabled`,
  `network_base_url_documented_only`, and presence flags for the
  env file, operator approval, Codex pass marker, Codex test-order
  docs marker.

## Output paths (exactly per request)

- `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json`
- `v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json`

Plus the GO_NO_GO marker at
`claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/GO_NO_GO.md`
and the operator dashboard payload at
`v2/frontend/public/v2_live_canary_permission_probe/latest/operator_dashboard_payload.json`.

## Files shipped

- `v2/backend/app/services/live_canary/permission_probe.py` — full
  rewrite with `read_env_config`, `_http_get_public_default`,
  `_http_get_signed_default`, `_http_post_signed_test_default`,
  `_probe_exchange_info`, `_probe_account_read_permission`,
  `_probe_documented_no_fill_endpoint`, and a `run_probe`
  signature that accepts injectable HTTP functions for tests.
- `v2/backend/app/cli/v2_live_canary_permission_probe.py` — rewritten
  CLI with `--no-network` flag, the new status output paths, and a
  go/no-go marker write.
- `v2/backend/tests/integration/cli/test_v2_live_canary_permission_probe.py`
  — 13 tests covering: BLOCKED with no env file, BLOCKED when
  credentials absent, READY when all checks pass, BLOCKED when a
  symbol is not tradable, BLOCKED when account-read is denied,
  BLOCKED when the public endpoint is unreachable, test-order
  endpoint NOT_CHECKED when the env flag is missing, NOT_CHECKED
  when the Codex docs marker is missing, CALLED only when BOTH
  gates are open, the status payload never contains raw credential
  values, the env-config parser drops accidentally placed
  credential lines, the probe never imports redis, and the CLI
  writes the status + GO/NO-GO files.
- `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
  — one test updated to drop the obsolete
  `PERMISSION_PROBE_NETWORK_CALL_DEFERRED_TO_OPERATOR_PACKET`
  sentinel and assert the new blocker set.

## Test results

- `test_v2_live_canary_permission_probe.py` — **13 passed.**
- `test_v2_live_canary_executor.py` — **13 passed** (existing suite
  retained after sentinel-assertion swap).

## Validation sweep (offline)

`tools/v2_live_canary_validation_sweep.py` now scans 17 artifacts
(15 from the bring-up packet + 2 new probe artifacts). Result:

```
{
  "files_scanned": 17,
  "missing_files": [],
  "secret_hits": 0,
  "approval_true_hits": 0,
  "legacy_redis_hits": 0,
  "exchange_mutation_hits": 0,
  "json_parse_failures": 0,
  "status": "PASS"
}
```

No secret-like value, no `"approves_X": true` drift, no legacy Redis
key reference, no exchange-mutation verb in any source file, and
every status payload parses as valid JSON.

## What this packet did NOT do

- Did NOT place a real order.
- Did NOT cancel or modify an order.
- Did NOT change leverage.
- Did NOT change margin mode.
- Did NOT enable live trading.
- Did NOT create any operator approval token.
- Did NOT add any symbol to `live_symbols`.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT modify the legacy bot tree or stop legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT expose any raw API key/secret value in payloads or logs.
- Did NOT call any order-shaped endpoint (the documented no-fill
  endpoint stays NOT_CHECKED until both gates are open).
- Did NOT claim checkpoint compatibility or policy parity.
- Did NOT expand paper analytics, alternative data, website work,
  or shutdown work.

## Why the current state is BLOCKED

The probe runs in an environment where:

- The operator has not yet placed `.local_secrets/live_canary.env`
  with a valid `V2_LIVE_CANARY_MODE` selection.
- The operator has not yet exported `BINANCE_API_KEY` /
  `BINANCE_API_SECRET` into the shell where the probe runs.
- The Codex test-order-docs marker is absent (so the no-fill
  endpoint stays NOT_CHECKED even if the operator flag were set).

The fail_blockers list in the status payload enumerates each
missing precondition. None of these blockers can be bypassed by the
probe; they require explicit operator action.

## Operator next steps to advance to `V2_LIVE_CANARY_PERMISSION_PROBE_READY`

1. Author `.local_secrets/live_canary.env` with these keys (and only
   these keys):

   ```
   V2_LIVE_CANARY_MODE=V2_NATIVE_SIGNAL_CANARY
   V2_LIVE_CANARY_SYMBOLS=BTCUSDT
   V2_LIVE_CANARY_MAX_NOTIONAL_USDT=20
   V2_LIVE_CANARY_MAX_DAILY_TRADES=3
   V2_LIVE_CANARY_MAX_DAILY_LOSS_USDT=10
   V2_LIVE_CANARY_DRY_RUN=true
   ```

   Do NOT place raw API credentials in this file. The parser drops
   any non-`V2_LIVE_CANARY_*` line.

2. Export the API credentials in the operator's shell:

   ```
   export BINANCE_API_KEY=<your-key>
   export BINANCE_API_SECRET=<your-secret>
   ```

   The probe NEVER prints or writes these values; it only checks
   their presence and uses them to sign a single read-only
   `/fapi/v2/account` GET call.

3. Re-run the probe one-shot:

   ```
   python3 -m v2.backend.app.cli.v2_live_canary_permission_probe --once
   ```

   The public `/fapi/v1/exchangeInfo` call will populate
   `symbols_tradable`, `min_notional_by_symbol`, `step_size_by_symbol`,
   and `tick_size_by_symbol`. The signed `/fapi/v2/account` call will
   resolve `account_read_permission_status` to `OK` or to a
   `DENIED_*` / `HTTP_*` status. If every check passes, the probe
   transitions to `V2_LIVE_CANARY_PERMISSION_PROBE_READY` and the
   GO/NO-GO marker is written accordingly.

4. To opt in to the documented Binance no-fill validation endpoint
   (still NOT a real order), submit the docs review to Codex. When
   Codex passes the docs review, place the marker at
   `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/codex_review/CODEX_TEST_ORDER_DOCS_APPROVED.marker`
   and add `V2_LIVE_CANARY_ALLOW_TEST_ORDER=true` to the env file.
   Only then will the probe exercise `/fapi/v1/order/test`.

5. Bring the probe READY state into the executor gate cascade by
   re-running `v2_live_canary_executor`. The executor still cannot
   place a real order because `submit_live_canary_order` raises
   `NotImplementedError`; that path requires a separate
   operator-approved packet beyond this one.

## Source pointers

- [permission_probe.py](v2/backend/app/services/live_canary/permission_probe.py:154)
  — `read_env_config` filtering on `ENV_CONFIG_KEYS` so credentials
  in the file are dropped at parse time.
- [permission_probe.py:241](v2/backend/app/services/live_canary/permission_probe.py#L241)
  — `_probe_exchange_info` extracts MIN_NOTIONAL / LOT_SIZE / PRICE_FILTER.
- [permission_probe.py:298](v2/backend/app/services/live_canary/permission_probe.py#L298)
  — `_probe_account_read_permission` returns only a status label;
  the response body is read and discarded.
- [permission_probe.py:317](v2/backend/app/services/live_canary/permission_probe.py#L317)
  — `_probe_documented_no_fill_endpoint` requires the env flag AND
  the Codex marker before any request is sent.
- [v2_live_canary_permission_probe.py](v2/backend/app/cli/v2_live_canary_permission_probe.py)
  — CLI writes to the new claude_worklog + frontend paths and emits
  GO_NO_GO.md exactly as specified.
- [test_v2_live_canary_permission_probe.py](v2/backend/tests/integration/cli/test_v2_live_canary_permission_probe.py)
  — 13 mocked-HTTP tests; uses `monkeypatch.delenv` so test runs
  never depend on operator credentials.
- [v2_live_canary_validation_sweep.py](tools/v2_live_canary_validation_sweep.py)
  — adversarial offline scanner; PASS at 17 files scanned, 0 hits.

## Non-approvals

This packet does NOT approve live trading, canary trading, exchange
mutation, leverage/margin change, Redis trim, legacy shutdown,
checkpoint compatibility, policy architecture parity, or production
equivalence. The probe being READY only certifies that the *exchange
preconditions* (credentials, tradability, account-read permission)
are met. The executor and operator-approval gates remain enforced
separately.
