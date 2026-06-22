# V2 LunarCrush Free-Tier Paper/Shadow Client Report

GO/NO-GO: V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT call paid endpoints. It does NOT log or persists the raw API key.

## Scope

Implements the LunarCrush free-tier paper/shadow client from the alt-
data integration plan. Provides off-chain social / sentiment /
momentum signals as one of the alternative-data inputs to the future
symbol-universe ranking and feature-family integration. The trainer,
trader, risk, and orchestrator overlays remain unmodified by this
packet; the alt-data signals can only filter or annotate decisions,
not override the strict paper-fill gate, not authorize real or canary
trading, and not place exchange entries.

## Files added

### v2/backend/app/services/alternative_data/lunarcrush_client.py

- Module constants:
  - V2_REDIS_PREFIX = `v2:`
  - KEY_STATUS = `v2:altdata:lunarcrush:status`
  - KEY_PER_SYMBOL_TEMPLATE = `v2:altdata:lunarcrush:symbol:{symbol}`
  - LUNARCRUSH_API_KEY_ENV_VAR = `LUNARCRUSH_API_KEY`
  - LUNARCRUSH_AUTH_HEADER_NAME = `Authorization`
  - LUNARCRUSH_AUTH_HEADER_VALUE_PREFIX = `Bearer `  (Bearer scheme
    per LunarCrush developer API docs; documented only, never
    serialized into payloads or stdout)
  - LUNARCRUSH_API_BASE_URL_DOCUMENTED = `https://lunarcrush.com`
  - LUNARCRUSH_API_DOCS_URL_DOCUMENTED = `https://lunarcrush.com/developers/api`
  - DEFAULT_FREE_RATE_LIMIT_PER_MINUTE = 10
  - DEFAULT_FREE_DAILY_BUDGET_PROVIDER = 1000
  - DEFAULT_FREE_DAILY_BUDGET_INTERNAL = 800 (strictly below provider
    free-tier ceiling)
  - DEFAULT_FREE_CACHE_TTL_SECONDS = 600
  - DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS = 300
- `_safe_redis_set` allowlist refuses anything outside
  `v2:altdata:lunarcrush:status` and `v2:altdata:lunarcrush:symbol:*`.
- `safe_load_api_key()` reads env at call time only.
  `redact_for_payload()` returns a placeholder for any credential-
  shaped value that surfaces in payloads or stdout.
- `parse_social_response()` is defensive: accepts dict / list / None /
  garbage; normalizes sentiment across {-1..1, 0..5, 0..100} scales;
  clamps galaxy_or_equivalent_score to [0, 100] and momentum to
  [0, 1].
- `LunarCrushClient.fetch_symbol(symbol)` enforces the same precedence
  as the Nansen client:
  1. KEY_MISSING_NO_NETWORK if env absent.
  2. CACHE_HIT if cache fresh.
  3. COOLDOWN_ACTIVE if per-symbol cooldown not elapsed.
  4. DAILY_BUDGET_EXHAUSTED if internal daily budget reached zero.
  5. Otherwise one bounded HTTP GET with the Bearer auth header.
     Maps 200, 401, 403, 429, TimeoutError, other exception
     explicitly to source_status sentinels.

### v2/backend/app/cli/v2_lunarcrush_altdata_ingestor.py

- Bounded one-shot. No --loop flag; future loop mode is an explicit
  operator decision.
- Key-missing path writes a KEY_MISSING_NO_NETWORK status to
  `v2:altdata:lunarcrush:status` AND to the worklog + 2 public
  payload files, with zero per-symbol keys written.
- Key-present path iterates the symbol set, writes per-symbol
  payloads, aggregates a source-status counter, and writes the
  global status payload.

### v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py

19/19 tests pass. Coverage matches the Nansen suite:

- KEY_MISSING_NO_NETWORK skips network entirely.
- CLI key-missing path writes status and no per-symbol key.
- 200 response → API_OK with Bearer auth header observed.
- 401, 403, 429 each map to their distinct source_status.
- Per-symbol cooldown blocks repeated calls.
- Internal daily budget exhausts.
- DEFAULT_FREE_DAILY_BUDGET_INTERNAL strictly below
  DEFAULT_FREE_DAILY_BUDGET_PROVIDER.
- Sentinel test key NEVER appears in status payload, per-symbol
  payload, Redis write log, or CLI stdout.
- `_safe_redis_set` accepts only `v2:altdata:lunarcrush:*`; refuses
  unrelated v2 namespaces (including `v2:altdata:nansen:status`).
- Sentiment normalization across three documented scales.
- Provider failure does not crash the CLI; rc stays 0 and the
  source_status counter records API_NETWORK_ERROR.
- No torch import. No pickle deserialization. No exchange-mutation
  verb in either module source (piecewise composition check).
- Status and per-symbol payloads include the contract fields.

## Behavior summary

- Implementation tier: free.
- Paid endpoints: not enabled.
- Auth header name: `Authorization` with `Bearer ` value prefix
  (documented only; value never serialized).
- Internal daily budget: 800 (below provider free-tier 1000).
- Cache TTL: 600 seconds.
- Per-symbol cooldown: 300 seconds.
- Failure isolation: provider unreachability, parse failure, 401,
  403, 429, timeout, and arbitrary exceptions are caught at the
  client boundary. None can crash the V2 runtime or interrupt the
  active soak.

## Allowed Redis writes

Only:

- `v2:altdata:lunarcrush:status`
- `v2:altdata:lunarcrush:symbol:{symbol}`

The safe-set boundary refuses any other key. Cross-provider isolation
is direct: the LunarCrush client cannot write
`v2:altdata:nansen:status` and vice versa.

## Safety invariants

- gate = blocked_human_only
- symbols_real = []
- approves_real = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- writes_legacy_redis = false
- writes_exchange_orders = false
- no_synthetic_signals = true
- no_torch_imported = true
- no_pickle_loaded = true
- no_legacy_filesystem_modified = true
- credential_in_payload = NEVER

## Runtime impact

This client is NOT yet wired into the symbol-universe automation, the
full-observation builder, or any scheduled daemon. The CLI is
operator-invocable. The continuous remediation governor was not
asked to require this CLI as a process; that is an operator/Codex
decision for a later packet.

The V2 paper/shadow runtime was not paused or reconfigured by this
packet.

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not enable paid endpoints.
- Does not modify legacy.
- Does not wire alt-data into the trainer / risk / orchestrator.
- Does not override the strict paper-fill gate.
- Does not synthesize signals.
- Does not commit any credential.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not create approval tokens.

## Outputs

- claude_worklog/final_readiness/v2_lunarcrush_free_tier_client/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_lunarcrush_free_tier_client/latest/V2_LUNARCRUSH_FREE_TIER_CLIENT_REPORT.md
- v2/backend/app/services/alternative_data/lunarcrush_client.py (added)
- v2/backend/app/cli/v2_lunarcrush_altdata_ingestor.py (added)
- v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py (31/31 pass after endpoint-allowlist hardening)

---

## Endpoint Allowlist Hardening (2026-05-21 addendum)

After the Nansen free-tier client received Codex PASS for its
endpoint-allowlist remediation
(`V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_CODEX_PASS`),
the same hardening pattern was applied here to close the
constructor-override class of bypass at the LunarCrush surface.

### Patch summary

`v2/backend/app/services/alternative_data/lunarcrush_client.py`
(sha256 `73f3fdd012c43d7a56308d00ac56c453a8ef9a02ebe7c9b99b457cf5192dbe49`)

1. **Constructor refuses raw URL kwargs.** The `api_base_url` and
   `social_endpoint` kwargs were removed entirely; passing either
   now raises `TypeError`. The base URL is the module-level
   `LUNARCRUSH_API_BASE_URL_DOCUMENTED` constant and is never taken
   from caller input.

2. **Endpoint allowlist by ID.**

   ```python
   DEFAULT_ENDPOINT_ID = "public_coins_free"
   FREE_ENDPOINT_PATHS = {"public_coins_free": "/api/v4/public/coins"}
   PAID_ENDPOINT_PATHS = {}            # reserved for future
   PAID_ENABLED_ENV_VAR = "ALT_DATA_ENABLE_PAID"
   ```

   Public helpers `is_free_endpoint`, `is_paid_endpoint`, and
   `is_allowlisted_endpoint` expose the contract.

3. **New refusal sentinels.**

   - `SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED = "LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED"`
   - `SOURCE_STATUS_PAID_ENDPOINT_DISABLED  = "LUNARCRUSH_PAID_ENDPOINT_DISABLED"`

4. **`fetch_symbol` short-circuit.** The first step inside
   `fetch_symbol` is an endpoint-allowlist decision. Unknown IDs
   exit with `LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED`; paid IDs with
   paid disabled exit with `LUNARCRUSH_PAID_ENDPOINT_DISABLED`. Both
   refusals run BEFORE the key-presence check and BEFORE any HTTP,
   so `rate_limit.last_request_ms` stays `None` and
   `network_call_attempted` stays `False`.

5. **`_build_url(symbol, endpoint_path)`** takes the path from the
   allowlisted ID lookup and prepends the module-level base URL.
   No instance state, no caller input, no host override.

6. **Status payload surfaces the contract:**

   - `endpoint_allowlist_enforced: true`
   - `constructor_accepts_api_base_url_override: false`
   - `constructor_accepts_social_endpoint_override: false`
   - `free_endpoint_ids_allowed: ["public_coins_free"]`
   - `paid_endpoint_ids_registered: []`
   - `paid_endpoints_env_var: "ALT_DATA_ENABLE_PAID"`
   - `paid_endpoints_env_value: false`
   - `network_call_attempted` / `provider_network_calls_attempted`
     (mirrored from the rate-limit state)
   - `live_gate: "blocked_human_only"`, `live_symbols: []`,
     `approves_live: false`, `approves_canary: false`,
     `approves_legacy_shutdown: false`, `approves_redis_trim: false`,
     `may_not_override_strict_paper_fill_gate: true`,
     `may_not_authorize_live_or_canary: true`,
     `may_not_place_orders: true`.

7. **Per-symbol payload** carries the same `endpoint_allowlist_enforced`
   and `constructor_accepts_*_override` flags so the operator
   dashboard can audit any single-symbol result end-to-end.

8. **CLI** (`v2_lunarcrush_altdata_ingestor.py`) now derives
   `network_call_attempted` from `client.rate_limit.last_request_ms`
   so the status payload's claim about provider network activity
   matches reality even when the gate refuses before HTTP.

### Auth Header

Header name is `Authorization`, value `Bearer <key>`. Raw key value
NEVER appears in any payload, status JSON, log line, or stdout. The
key is loaded inside `fetch_symbol`, used to build the header, then
released via `del key` — and only after the endpoint-allowlist
short-circuit has passed.

### Allowed Writes (unchanged)

`_safe_redis_set` refuses any key outside:

- `v2:altdata:lunarcrush:status`
- `v2:altdata:lunarcrush:symbol:{symbol}`

### Regression Tests (10 new)

`v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py`
(sha256 `d9d7946a41bf89a498d747d6975c2075c85ff19a13dfa8f4659e9dc3b48c82c6`)

- `test_constructor_refuses_social_endpoint_override` — the analogue
  of the original Nansen bypass proof: passing a raw endpoint via
  the constructor must raise `TypeError`.
- `test_constructor_refuses_api_base_url_override`
- `test_endpoint_allowlist_blocks_unknown_endpoint_id_before_http` —
  zero HTTP calls when `endpoint_id` is unknown.
- `test_paid_endpoint_unreachable_when_paid_disabled` — registers a
  paid ID at runtime, verifies it cannot be reached without the env
  flag set.
- `test_paid_endpoint_disabled_when_env_var_not_true`
- `test_free_endpoint_id_reaches_documented_base_url_only` — the URL
  passed to `http_get` starts with the documented base URL only.
- `test_raw_key_never_appears_in_payload` — sentinel-key scan over
  serialized payload on the refusal path.
- `test_no_legacy_redis_or_exchange_writes_on_refusal_paths`
- `test_module_allowlist_contains_only_free_public_coins_today` —
  pins the current allowlist contract.
- `test_status_payload_surfaces_endpoint_allowlist_contract` —
  end-to-end CLI status check.

The pre-existing forbidden-token source-scan test was upgraded to
regex word boundaries so legitimate safety-flag identifiers
(`may_not_place_orders` etc.) cannot accidentally trip the scan.

### Validation

| Check | Result |
| ----- | ------ |
| Focused LunarCrush tests | PASS (31 of 31) |
| `py_compile` of patched client + CLI | PASS |
| Raw credential scan on patched files | PASS (0 hits outside `.local_secrets`) |
| Old Redis write scan on patched files | PASS (0 hits) |
| Exchange-mutation source scan (word-boundary) | PASS (0 hits) |
| Status refresh via CLI with no key | PASS (no provider network call) |
| JSON validation of refreshed payloads | PASS |

### Refreshed Status Mirrors (all 3 paths)

- `claude_worklog/final_readiness/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json`
- `v2/frontend/public/operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json`
- `v2/frontend/public/v2_lunarcrush_altdata_client/latest/operator_dashboard_payload.json`

All three report `go_no_go=V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY`,
`endpoint_allowlist_enforced=true`, `paid_endpoints_enabled=false`,
`network_call_attempted=false`, `key_present=false` (no key in env
at refresh time), `credential_in_payload=NEVER`,
`live_gate=blocked_human_only`, `live_symbols=[]`.

### Safety Posture (preserved)

- raw API key never emitted
- auth header name documented as `Authorization` (Bearer scheme)
- allowed writes restricted to `v2:altdata:lunarcrush:status` and
  `v2:altdata:lunarcrush:symbol:{symbol}`
- alternative data may not override the strict paper-fill gate
- alternative data may not authorize live or canary
- alternative data may not submit exchange entries
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- provider failure routes through source-status sentinels and never
  re-raises into the V2 runtime
- LunarCrush is paper/shadow only; no paid endpoints, no live
  trading, no leverage/margin mutation, no approval drift

### Final Decision (still)

`V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY`
