# Codex Review: LunarCrush Developer API Docs Validation For V2 Free-Tier Client

Generated: `2026-05-18T02:46:00Z`

GO/NO-GO: `V2_LUNARCRUSH_DOCS_VALIDATION_CODEX_PASS`

## Decision

Codex passes the LunarCrush docs validation gate for planning a future V2 LunarCrush free-tier paper/shadow one-shot client. This is documentation validation only. No code was implemented, no provider API call was made, and no raw key was exposed.

This review does not approve provider-client implementation, external feed adoption, paid endpoints, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Sources Checked

- Required docs URL: `https://lunarcrush.com/developers/api/overview`
- API v4 markdown output: `https://lunarcrush.com/api4?format=markdown`
- LunarCrush API docs mirror snippets for coin endpoints under `https://lunarcrush.ai/mdx/api/public/coins/:coin/time-series/v2`

The required overview page is client-rendered, but its page metadata identifies it as the LunarCrush API Documentation v4 RESTful JSON API. The rendered bundle points to API v4 documentation outputs including markdown, JSON, and OpenAPI formats.

## Authentication

The API v4 docs show Bearer-token authentication:

```text
Authorization: Bearer <API_KEY>
```

The future V2 client must therefore use:

- header: `Authorization`
- value shape: `Bearer <redacted key>`
- raw key source: `.local_secrets/alternative_data.env`
- no raw key in worklogs, public payloads, task descriptors, stdout, stderr, Redis, or frontend.

## Symbol/Asset Metrics Endpoints

Docs identify these candidate endpoints for the planned symbol-level social metrics client:

- `https://lunarcrush.com/api4/public/coins/list/v2`
- `https://lunarcrush.com/api4/public/coins/:coin/v1`
- `https://lunarcrush.com/api4/public/coins/:coin/time-series/v2`
- `https://lunarcrush.com/api4/public/coins/:coin/meta/v1`

The docs state that `coins/list/v2` returns a general snapshot for tracked coins and includes fields suitable for V2 symbol-level social metrics:

- `social_volume_24h`
- `social_dominance`
- `interactions_24h`
- `galaxy_score`
- `alt_rank`
- `sentiment`
- symbol/name/category metadata

The time-series endpoint accepts a coin by numeric ID or symbol, which is sufficient for the planned BTC/ETH/SOL-style symbol mapping once V2 adds an explicit symbol-normalization map.

## Free-Tier Limits

The API markdown itself did not include a dedicated free-tier quota table. The official site bundle/pricing text observed during validation references a lower-tier API allowance of:

- `10` requests per minute
- `2,000` requests per day

Because pricing/entitlements can vary by account and the supplied key was not called in this docs-only step, V2 must use stricter internal defaults until a client-specific Codex review passes.

Safe internal V2 budget for the first client implementation:

- max requests per minute: `6`
- max requests per day: `500`
- per-symbol cooldown: `900` seconds
- cache TTL for symbol metrics: `900` seconds
- no automatic retry after 401 or 403 in the same run
- after 429, stop provider calls for the run and mark provider cooldown active

## Error Handling

The docs examples do not define detailed response-body contracts for 401, 403, or 429. The future V2 client must still classify them explicitly:

- `401` -> `API_AUTH_ERROR_401`
- `403` -> `API_FORBIDDEN_403_OR_TIER_BLOCKED`
- `429` -> `API_RATE_LIMITED_429`
- timeout -> `API_TIMEOUT`
- network exception -> `API_NETWORK_ERROR`
- malformed JSON -> `API_PARSE_ERROR`

Provider failure must never stop V2 runtime, soak, remediation, log observer, comparator, liquidation WSS, paper gate, or frontend payload refresh.

## Implementation Constraints For Future Client

The future LunarCrush client must be one-shot paper/shadow first:

- no daemon enrollment before Codex review;
- no paid endpoints;
- no old Redis writes;
- writes only a future reviewed `v2:altdata:lunarcrush:*` namespace;
- no exchange mutation;
- no live/canary/shutdown/Redis-trim approvals;
- cannot override strict paper-fill gate;
- cannot claim checkpoint compatibility or policy parity;
- must expose missing/stale/rate-limit flags in public payloads.

## Safety State

- raw key exposed: `false`
- provider API call made: `false`
- implementation created: `false`
- paid tier enabled: `false`
- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Final Decision

`V2_LUNARCRUSH_DOCS_VALIDATION_CODEX_PASS`
