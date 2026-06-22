# Codex Review: V2 Live-Canary Network-Safe Permission Probe

Generated: `2026-05-19T02:51:32Z`

GO/NO-GO: `V2_LIVE_CANARY_PERMISSION_PROBE_CODEX_PASS`

## Decision

Codex passes the network-safe permission probe implementation. The probe verifies exchange access preconditions without placing a real order, without cancelling or modifying orders, without changing leverage or margin mode, and without exposing raw credentials.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

Current runtime probe state remains blocked because operator inputs are absent:

- `.local_secrets/live_canary.env`: absent
- `BINANCE_API_KEY`: absent from the review shell
- `BINANCE_API_SECRET`: absent from the review shell
- operator approval file: absent
- Codex test-order docs marker: absent
- live gate: `blocked_human_only`
- live symbols: `[]`

The Codex PASS here means the permission-probe implementation is safe. It does not mean live canary is approved or ready to submit orders.

## Official Docs Check

Codex validated the endpoint contract against official Binance USD-M Futures documentation:

- `GET /fapi/v1/exchangeInfo` is documented as current trading rules and symbol information.
- `GET /fapi/v2/account` is documented as account information and requires signed USER_DATA access.
- `POST /fapi/v1/order/test` is documented as a test order request that is not submitted to the matching engine.

The implementation matches that boundary: public exchange info is used for tradability and filter checks, signed account info is used only for account-read permission status, and the test-order endpoint is disabled unless both `V2_LIVE_CANARY_ALLOW_TEST_ORDER=true` and a Codex docs marker are present.

Docs used:

- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V2
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order-Test

## Evidence Reviewed

Reviewed:

- `v2/backend/app/services/live_canary/permission_probe.py`
- `v2/backend/app/cli/v2_live_canary_permission_probe.py`
- `v2/backend/tests/integration/cli/test_v2_live_canary_permission_probe.py`
- `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
- `tools/v2_live_canary_validation_sweep.py`
- `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/*`
- `v2/frontend/public/v2_live_canary_permission_probe/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json`

The packet status remains `V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED` because credentials and operator config are absent. That blocked runtime state is honest.

## Endpoint Boundary

The probe uses only:

- `GET /fapi/v1/exchangeInfo`
- `GET /fapi/v2/account`
- optionally `POST /fapi/v1/order/test`

No real order endpoint, cancel endpoint, modify endpoint, leverage endpoint, or margin endpoint appears in the reviewed implementation.

The optional test-order endpoint is order-shaped but not a real order endpoint. It remains gated by both:

- operator env config: `V2_LIVE_CANARY_ALLOW_TEST_ORDER=true`;
- Codex marker: `CODEX_TEST_ORDER_DOCS_APPROVED.marker`.

The marker is currently absent. Codex did not create it. Therefore the current probe cannot call `/fapi/v1/order/test`.

## Permission And Market Checks

Codex verified the probe:

- checks credential presence without returning raw values;
- discards signed account response bodies and emits only status labels;
- reads `.local_secrets/live_canary.env` only for recognized `V2_LIVE_CANARY_*` config keys;
- drops accidental credential-like lines from the env-file parser;
- checks symbol tradability from `exchangeInfo`;
- extracts `MIN_NOTIONAL`, `LOT_SIZE.stepSize`, and `PRICE_FILTER.tickSize`;
- reports missing/denied permissions explicitly instead of guessing.

A safe public-network sample against `exchangeInfo` with temporary BTCUSDT config returned:

- `exchange_info_call_status=OK`
- `symbols_tradable={'BTCUSDT': True}`
- `min_notional_by_symbol={'BTCUSDT': 50.0}`
- `account_read_permission_status=NOT_CHECKED_CREDENTIALS_ABSENT`
- `test_order_endpoint_status=NOT_CHECKED_FLAG_NOT_SET`
- `test_order_endpoint_attempted=False`

No signed call or order-like call was made in that sample because credentials and the test-order flag were absent.

## Writes

The service module has no Redis dependency and writes no Redis keys. The CLI writes only status files:

- `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json`
- `v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json`
- `claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/GO_NO_GO.md`

No old Redis write path was found. No `v2:live_canary:*` Redis write is used by this probe lane.

## Safety

Codex verified:

- raw credentials are not printed or written;
- no real order endpoint is called;
- no cancel/modify endpoint is called;
- no leverage/margin mutation endpoint is called;
- optional no-fill test endpoint is documented and dual-gated;
- no old Redis write exists;
- no exchange mutation is reachable from this probe;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- no live/canary/shutdown/Redis-trim approval is created.

Safety state remains:

- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `real_order_attempted=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`

## Runtime Governors

Standing governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`

## Validation

- Focused permission-probe and executor tests: `26 passed`.
- `py_compile`: PASS.
- Validation sweep: PASS, 17 files scanned.
- Public `exchangeInfo` sample with temporary config: PASS.
- Raw secret-value scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Non-Approval Items

Codex did not create:

- operator approval file;
- live-canary env file;
- Codex live-canary pass marker;
- Codex test-order docs marker.

The next gate remains the operator-gated execution adapter review and final canary approval review. This probe PASS does not authorize any live order path.

## Final Decision

`V2_LIVE_CANARY_PERMISSION_PROBE_CODEX_PASS`
