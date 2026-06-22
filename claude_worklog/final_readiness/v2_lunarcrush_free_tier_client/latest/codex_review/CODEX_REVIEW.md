# Codex Review: V2 LunarCrush Free-Tier Endpoint-Allowlist Client

Generated: `2026-05-21T19:46:16Z`

GO/NO-GO: `V2_LUNARCRUSH_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`

## Decision

Codex passes the LunarCrush free-tier paper/shadow client with endpoint allowlist hardening. The client remains bounded to paper/shadow scope, exposes no raw key, blocks unknown and paid-disabled endpoints before HTTP, writes only the LunarCrush V2 alt-data namespace, and has no trading authority.

This review does not approve LunarCrush daemon enrollment, symbol-universe production wiring, paid endpoints, external feed production adoption, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Scope Reviewed

Reviewed:

- `v2/backend/app/services/alternative_data/lunarcrush_client.py`
- `v2/backend/app/cli/v2_lunarcrush_altdata_ingestor.py`
- `v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py`
- `claude_worklog/final_readiness/v2_lunarcrush_free_tier_client/latest/V2_LUNARCRUSH_FREE_TIER_CLIENT_REPORT.md`
- `claude_worklog/final_readiness/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json`
- public LunarCrush operator payload mirrors
- current Redis keys under `v2:altdata:lunarcrush:*`

## Endpoint Boundary

Codex reran the endpoint bypass proof with `http_get` monkeypatched and no real LunarCrush provider network call:

- `LunarCrushClient(social_endpoint="/api/v4/paid/not-reviewed")`: `TypeError`;
- `LunarCrushClient(api_base_url="https://attacker.example/")`: `TypeError`;
- `LunarCrushClient(endpoint_id="/api/v4/paid/not-reviewed")`: `LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED`;
- unknown/raw endpoint HTTP call count: `0`;
- registered-paid endpoint with `ALT_DATA_ENABLE_PAID` unset: `LUNARCRUSH_PAID_ENDPOINT_DISABLED`;
- paid-disabled HTTP call count: `0`;
- key-missing path: `KEY_MISSING_NO_NETWORK`;
- key-missing HTTP call count: `0`.

The default free endpoint still works under monkeypatch only:

- endpoint ID: `public_coins_free`;
- URL base: `https://lunarcrush.com`;
- path: `/api/v4/public/coins`;
- auth header name: `Authorization`;
- auth header scheme: `Bearer`;
- monkeypatched HTTP call count: `1`.

No real LunarCrush socket was opened during this review.

## Free-Tier Controls

Codex verified the free-tier controls remain pinned:

- `DEFAULT_FREE_RATE_LIMIT_PER_MINUTE=6`;
- `DEFAULT_FREE_DAILY_BUDGET_INTERNAL=500`;
- `DEFAULT_FREE_DAILY_BUDGET_PROVIDER=1000`;
- `DEFAULT_FREE_CACHE_TTL_SECONDS=900`;
- `DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS=900`;
- paid endpoint IDs registered by default: `[]`;
- paid endpoints enabled: `false`.

Focused tests prove cache hit behavior, per-symbol cooldown, daily budget exhaustion, 401/403/429 handling, timeout/network failure handling, and provider failure isolation. Provider failure is converted into status payloads and the CLI exits normally.

## Runtime Status

Codex refreshed the CLI with `LUNARCRUSH_API_KEY` unset, so the key-missing path was exercised without a provider call. Current status reports:

- `go_no_go=V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY`;
- `key_present=false`;
- `network_call_attempted=false`;
- `provider_network_calls_attempted=false`;
- `source_status_counts={"KEY_MISSING_NO_NETWORK": 3}`;
- `credential_in_payload=NEVER`;
- `tier=free`;
- `endpoint_allowlist_enforced=true`;
- `free_endpoint_ids_allowed=["public_coins_free"]`;
- `paid_endpoint_ids_registered=[]`;
- `constructor_accepts_api_base_url_override=false`;
- `constructor_accepts_social_endpoint_override=false`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`.

## Redis Boundary

Allowed writes are exactly:

- `v2:altdata:lunarcrush:status`
- `v2:altdata:lunarcrush:symbol:{symbol}`

Current Redis scan found only:

- `v2:altdata:lunarcrush:status`

The status payload keeps `credential_in_payload=NEVER`, `writes_legacy_redis=false`, `writes_exchange_orders=false`, `live_gate=blocked_human_only`, and `live_symbols=[]`.

The only old-Redis token hit in the reviewed LunarCrush lane is a regression test asserting `_safe_redis_set(..., "prediction:BTCUSDT", ...) is refused.

## Safety

Codex verified:

- raw credential-value scan over reviewed source, tests, worklog/public payloads, and current LunarCrush Redis values: `0` hits outside `.local_secrets`;
- no old Redis write path in the reviewed LunarCrush client or CLI;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order endpoint in the reviewed LunarCrush client or CLI;
- no live/canary/shutdown/Redis-trim approval drift;
- alternative-data payloads keep `may_not_override_strict_paper_fill_gate=true`;
- alternative-data payloads keep `may_not_authorize_live_or_canary=true`;
- alternative-data payloads keep `may_not_place_orders=true`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`.

Source-scan hits for order/leverage strings are safety text or regression-test forbidden-token strings, not executable mutation paths.

Standing governors remain ready:

- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`;
- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`;
- fail blockers: none.

## Validation

- Constructor override proof: PASS.
- Unknown endpoint pre-HTTP block proof: PASS, `0` HTTP calls.
- Paid-disabled endpoint proof: PASS, `0` HTTP calls.
- Key-missing no-network proof: PASS, `0` HTTP calls.
- Default free endpoint proof: PASS, documented base/path only.
- Focused LunarCrush tests: `31 passed`.
- `py_compile`: PASS.
- Key-missing CLI status refresh: PASS, no provider network call.
- Redis key allowlist scan: PASS.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Standing governor check: PASS.

## Final Decision

`V2_LUNARCRUSH_FREE_TIER_CLIENT_CODEX_PASS_PAPER_SHADOW`
