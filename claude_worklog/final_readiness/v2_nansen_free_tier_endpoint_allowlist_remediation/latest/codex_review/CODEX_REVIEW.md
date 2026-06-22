# Codex Review: V2 Nansen Free-Tier Endpoint Allowlist Remediation

Generated: `2026-05-21T05:49:19Z`

GO/NO-GO: `V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_CODEX_PASS`

## Decision

Codex passes the Nansen endpoint allowlist remediation. The prior direct endpoint override path is closed: `smart_money_endpoint` and `api_base_url` constructor kwargs are no longer accepted, unknown endpoint IDs are blocked before HTTP, and paid endpoint IDs are not registered in the current client.

This review does not approve provider adoption beyond paper/shadow, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Prior Bypass Proof Rerun

Codex reran the prior bypass shape with a monkeypatched `http_get` and no real provider network call:

- `NansenClient(smart_money_endpoint="/api/v1/paid/not-reviewed")`: `TypeError`
- `NansenClient(api_base_url="https://attacker.example/")`: `TypeError`
- `NansenClient(endpoint_id="/api/v1/paid/not-reviewed")`: `NANSEN_ENDPOINT_NOT_ALLOWLISTED`
- unknown/raw endpoint HTTP call count: `0`
- registered-paid endpoint with `ALT_DATA_ENABLE_PAID` unset: `NANSEN_PAID_ENDPOINT_DISABLED`
- paid-disabled HTTP call count: `0`

The allowlisted default free endpoint still works under monkeypatch:

- endpoint ID: `smart_money_holdings_free`
- URL starts with documented base: `https://api.nansen.ai`
- path: `/api/v1/smart-money/holdings`
- auth header name: `apikey`
- HTTP call count: `1` only on the allowlisted free path

No real Nansen socket was opened during this review.

## Endpoint Contract

Reviewed `v2/backend/app/services/alternative_data/nansen_client.py`.

Current endpoint contract:

- default endpoint ID: `smart_money_holdings_free`
- free endpoint allowlist: `{"smart_money_holdings_free": "/api/v1/smart-money/holdings"}`
- paid endpoint IDs registered today: `[]`
- base URL: module constant `https://api.nansen.ai`
- caller-supplied base URL: not accepted
- caller-supplied raw endpoint path: not accepted

`fetch_symbol` calls `_endpoint_decision()` before key lookup, budget checks, or HTTP construction. Refusal paths return a source-status sentinel and leave `rate_limit.last_request_ms` unset, so aggregate status reports `network_call_attempted=false`.

## Status Payloads

Reviewed:

- `claude_worklog/final_readiness/v2_nansen_free_tier_endpoint_allowlist_remediation/latest/nansen_endpoint_allowlist_status.json`
- `claude_worklog/final_readiness/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- `v2/frontend/public/operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- `v2/frontend/public/v2_nansen_altdata_client/latest/operator_dashboard_payload.json`

The payloads report:

- `endpoint_allowlist_enforced=true`
- `constructor_accepts_api_base_url_override=false`
- `constructor_accepts_smart_money_endpoint_override=false`
- `free_endpoint_ids_allowed=["smart_money_holdings_free"]`
- `paid_endpoint_ids_registered=[]`
- `paid_endpoints_enabled=false`
- `paid_endpoints_env_value=false`
- `credential_in_payload=NEVER`
- `network_call_attempted=false`
- `provider_network_calls_attempted=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

The current refreshed Nansen status is `KEY_MISSING_NO_NETWORK`, so no provider network path is active in runtime payloads.

## Redis Boundary

The Nansen client still writes only through `_safe_redis_set`.

Allowed writes:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:{symbol}`

Codex found no production write path to old Redis namespaces or to other provider namespaces. Current Redis scan found no active `v2:altdata:nansen:*` keys; therefore no unexpected Nansen Redis state is present.

## Safety

Codex verified:

- raw credential-value scan over reviewed source, tests, worklog/public payloads, and current Nansen Redis values: `0` hits outside `.local_secrets`;
- no old Redis write path in the reviewed Nansen client/CLI;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed Nansen client/CLI;
- alternative-data payloads keep `may_not_override_strict_paper_fill_gate=true`;
- alternative-data payloads keep `may_not_authorize_live_or_canary=true`;
- alternative-data payloads keep `may_not_place_orders=true`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for old Redis key strings and leverage/order strings are regression-test assertions and safety-text fields, not executable mutation paths.

## Validation

- Focused Nansen tests: `30 passed`.
- `py_compile`: PASS.
- Prior endpoint-override bypass proof: PASS, constructor rejected.
- Unknown endpoint pre-HTTP block proof: PASS, `0` HTTP calls.
- Paid-disabled endpoint proof: PASS, `0` HTTP calls.
- Default free endpoint proof: PASS, documented base/path only.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Redis write allowlist scan: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- JSON/status payload inspection: PASS.

## Final Decision

`V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_CODEX_PASS`
