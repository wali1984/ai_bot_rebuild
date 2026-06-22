# V2 Nansen Free-Tier Paper/Shadow Client Report

Generated: `2026-05-21T04:03:33Z`

GO/NO-GO: `V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY`

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT enable live. It does NOT write old Redis keys. It does NOT call
paid endpoints. It does NOT log or persist the raw API key.

## Scope

Implements the Nansen free-tier provider client in paper/shadow mode
only. The client can publish redacted status and per-symbol
smart-money signal payloads for downstream alternative-data scoring,
but it has no trading authority and cannot override the strict
paper-fill gate.

## Files Implemented

- `v2/backend/app/services/alternative_data/nansen_client.py`
- `v2/backend/app/cli/v2_nansen_altdata_ingestor.py`
- `v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py`

## Key Custody

The client reads `NANSEN_API_KEY` from local custody only:

- process environment, or
- `.local_secrets/alternative_data.env`

The raw key is used only to construct the outbound `apikey` header
inside the bounded request path. It is never serialized to status
payloads, per-symbol payloads, stdout, Redis values, logs, or public
artifacts. Payloads expose only:

- `key_present`
- `credential_in_payload="NEVER"`
- `auth_header_name_documented_only="apikey"`

## Runtime Behavior

If the key is absent, the client returns:

- `KEY_MISSING_NO_NETWORK`
- `network_call_attempted=false`
- no per-symbol Redis writes
- no provider socket opened

If the key is present, the client performs bounded one-shot paper
requests only through the client boundary. The request path enforces:

- free tier only
- no paid endpoints
- cache TTL: `600` seconds
- per-symbol cooldown: `300` seconds
- internal daily budget: `800`
- provider free-tier ceiling documented: `1000`
- `401` -> `API_AUTH_ERROR_401`
- `403` -> `API_FORBIDDEN_403`
- `429` -> `API_RATE_LIMITED_429`
- timeout -> `API_TIMEOUT`
- provider/network failure -> `API_NETWORK_ERROR`
- parse failure -> `API_PARSE_ERROR`

Provider failures are caught and converted into status payloads. The
CLI exits normally on provider failure so this path cannot stop the V2
runtime.

## Redis Boundary

Allowed writes are exactly:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:{symbol}`

`_safe_redis_set` refuses all other keys, including old Redis
namespaces and other V2 provider namespaces.

## Safety Pins

Status and per-symbol payloads include:

- `live_gate="blocked_human_only"`
- `live_symbols=[]`
- `approves_live=false`
- `approves_real=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `paid_endpoints_enabled=false`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`
- `no_synthetic_signals=true`
- `no_torch_imported=true`
- `no_pickle_loaded=true`
- `no_legacy_filesystem_modified=true`

## Validation

- Focused tests: `20 passed`.
- `py_compile`: PASS.
- Local key-custody fallback test: PASS.
- KEY_MISSING_NO_NETWORK no-socket path: PASS.
- Cache TTL behavior: PASS.
- Per-symbol cooldown behavior: PASS.
- Daily budget exhaustion behavior: PASS.
- 401/403/429 explicit handling: PASS.
- Provider failure isolation: PASS.
- Redis write allowlist: PASS.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Exchange mutation scan: PASS.
- Old Redis write scan: PASS.

## Outputs

- `claude_worklog/final_readiness/v2_nansen_free_tier_client/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_nansen_free_tier_client/latest/V2_NANSEN_FREE_TIER_CLIENT_REPORT.md`
- `v2/backend/app/services/alternative_data/nansen_client.py`
- `v2/backend/app/cli/v2_nansen_altdata_ingestor.py`
- `v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py`

## Final Decision

`V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY`
