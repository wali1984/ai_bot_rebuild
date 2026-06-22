# Codex Review: V2 Nansen Free-Tier Client After Endpoint Allowlist Remediation

Generated: `2026-05-21T16:35:25Z`

GO/NO-GO: `V2_NANSEN_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`

## Decision

Codex passes the complete Nansen free-tier paper/shadow client after the endpoint allowlist remediation. The prior arbitrary endpoint override bypass is closed, paid/unreviewed endpoints are blocked before HTTP, the default path is limited to the allowlisted free endpoint, and the client remains paper/shadow only with no trading authority.

This review does not approve paid endpoints, provider adoption beyond paper/shadow, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Remediation Prerequisite

Codex verified the endpoint allowlist remediation PASS exists:

`V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_CODEX_PASS`

That remediation closed the previous fail blocker where a caller could construct a client with an arbitrary `smart_money_endpoint` or `api_base_url`.

## Endpoint Enforcement

Codex reran the bypass proof with `http_get` monkeypatched and no real Nansen provider network call:

- `NansenClient(smart_money_endpoint="/api/v1/paid/not-reviewed")`: `TypeError`;
- `NansenClient(api_base_url="https://attacker.example/")`: `TypeError`;
- `NansenClient(endpoint_id="/api/v1/paid/not-reviewed")`: `NANSEN_ENDPOINT_NOT_ALLOWLISTED`;
- unknown/raw endpoint HTTP call count: `0`;
- registered-paid endpoint with `ALT_DATA_ENABLE_PAID` unset: `NANSEN_PAID_ENDPOINT_DISABLED`;
- paid-disabled HTTP call count: `0`.

The default free path still works under monkeypatch only:

- endpoint ID: `smart_money_holdings_free`;
- URL base: `https://api.nansen.ai`;
- path: `/api/v1/smart-money/holdings`;
- auth header name: `apikey`;
- monkeypatched HTTP call count: `1`.

No real Nansen socket was opened during review.

## Key Custody And Runtime Status

Codex verified key custody reads only from:

- process environment variable `NANSEN_API_KEY`; or
- `.local_secrets/alternative_data.env`.

The current status refresh was run with `--daily-budget-internal 0`, so even with a key present it made no provider network call. Current Nansen status reports:

- `go_no_go=V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY`;
- `key_present=true`;
- `network_call_attempted=false`;
- `provider_network_calls_attempted=false`;
- `source_status_counts={"DAILY_BUDGET_EXHAUSTED": 3}`;
- `credential_in_payload=NEVER`;
- `tier=free`;
- `paid_endpoints_enabled=false`;
- `endpoint_allowlist_enforced=true`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`.

Raw credential-value scan over reviewed source, tests, worklog/public payloads, and current `v2:altdata:nansen:*` Redis values found `0` hits outside `.local_secrets`.

## Free-Tier Controls

The reviewed client enforces:

- free tier only by default;
- paid endpoints disabled unless separately registered and explicitly enabled;
- cache TTL: `600` seconds;
- per-symbol cooldown: `300` seconds;
- internal daily budget: `800`;
- documented provider free-tier ceiling: `1000`;
- explicit status handling for `401`, `403`, `429`, timeout, network failure, and parse failure.

Focused tests cover the env and local-vault key paths, cache hits, cooldown, daily-budget exhaustion, explicit provider status handling, and provider failure isolation. Provider failure is converted into status payloads and does not crash the CLI.

## Redis Boundary

Allowed writes are exactly:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:{symbol}`

Current Redis keys under `v2:altdata:nansen:*` are:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:BTCUSDT`
- `v2:altdata:nansen:symbol:ETHUSDT`
- `v2:altdata:nansen:symbol:SOLUSDT`

The current payloads keep `credential_in_payload=NEVER`, `writes_legacy_redis=false`, `writes_exchange_orders=false`, `live_gate=blocked_human_only`, and `live_symbols=[]`.

## Safety

Codex verified:

- no old Redis write path in the reviewed Nansen client or CLI;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed Nansen client or CLI;
- no live/canary/shutdown/Redis-trim approval drift;
- alternative-data payloads keep `may_not_override_strict_paper_fill_gate=true`;
- alternative-data payloads keep `may_not_authorize_live_or_canary=true`;
- alternative-data payloads keep `may_not_place_orders=true`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for old Redis key strings are regression tests asserting refusal of forbidden keys, not executable production writes.

Standing governors remain ready:

- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`;
- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`;
- fail blockers: none.

## Validation

- Endpoint allowlist remediation marker: PASS.
- Prior endpoint-override bypass proof: PASS, constructor rejects raw overrides.
- Unknown endpoint pre-HTTP block proof: PASS, `0` HTTP calls.
- Paid-disabled endpoint proof: PASS, `0` HTTP calls.
- Default free endpoint proof: PASS, allowlisted base/path only.
- Focused Nansen tests: `30 passed`.
- `py_compile`: PASS.
- Zero-budget status refresh: PASS, no provider network call.
- Redis key allowlist scan: PASS.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Standing governor check: PASS.

## Final Decision

`V2_NANSEN_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`
