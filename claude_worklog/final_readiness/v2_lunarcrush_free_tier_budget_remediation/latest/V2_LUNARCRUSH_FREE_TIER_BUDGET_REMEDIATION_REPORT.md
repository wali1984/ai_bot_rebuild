# V2 LunarCrush Free-Tier Budget Remediation Report

GO/NO-GO: V2_LUNARCRUSH_FREE_TIER_BUDGET_REMEDIATION_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT call paid endpoints. It does NOT change the LunarCrush integration
scope; only the free-tier budget / cooldown / cache TTL values change.

## Codex fail blocker addressed

The previous LunarCrush free-tier client used budget / cooldown / TTL
values looser than the docs-validation-approved safe values. Codex
flagged this drift. This packet narrows the four free-tier constants
in lunarcrush_client.py to the Codex-approved values and proves the
new values with explicit tests.

## Constants patched

The four free-tier constants now match Codex docs-validation:

| Constant                                  | Prior | Now |
| ----------------------------------------- | ----- | --- |
| DEFAULT_FREE_RATE_LIMIT_PER_MINUTE        | 10    | 6   |
| DEFAULT_FREE_DAILY_BUDGET_INTERNAL        | 800   | 500 |
| DEFAULT_FREE_CACHE_TTL_SECONDS            | 600   | 900 |
| DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS  | 300   | 900 |

Unchanged for reference:

- DEFAULT_FREE_DAILY_BUDGET_PROVIDER = 1000 (provider documented
  ceiling; internal budget must remain strictly below it)
- DEFAULT_HTTP_TIMEOUT_SECONDS = 10

After the patch:

- Internal budget 500 is strictly below provider 1000.
- Cache TTL 900 is greater than or equal to per-symbol cooldown 900,
  so cooldowns cannot push consumers off cache too early.
- LunarCrush rate limit 6/min is at or below the Nansen free-tier
  rate limit 10/min, keeping the social lane on a stricter request
  cadence than the on-chain lane.
- LunarCrush daily internal budget 500 is at or below the Nansen
  free-tier daily internal budget 800.

## Source change

### v2/backend/app/services/alternative_data/lunarcrush_client.py

The four module-level constants in the free-tier defaults block were
updated. No other behavior changed: precedence (KEY_MISSING_NO_NETWORK
to CACHE_HIT to COOLDOWN_ACTIVE to DAILY_BUDGET_EXHAUSTED to bounded
HTTP GET), HTTP status mapping (401, 403, 429, timeout, generic
exception), defensive parsing, allowed Redis-write set, schema names,
and the credential-handling pattern are all unchanged.

### v2/backend/app/cli/v2_lunarcrush_altdata_ingestor.py

No edits required. The ingestor reads defaults from the client
module via constructor defaults, so the stricter constants flow
through without code changes.

### v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py

Two new test cases pin the stricter values:

- test_free_tier_budget_constants_match_docs_validation
  Asserts each of the four constants equals the Codex-approved value
  and verifies the cache-TTL-greater-or-equal-to-cooldown sanity
  invariant.
- test_lunarcrush_free_tier_strictly_below_nansen_rate_limit
  Cross-provider check: LunarCrush rate limit and daily budget must
  stay at or below Nansen's, so the social lane is the stricter of
  the two providers.

## Tests

Full focused sweep across the four related suites:

- v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py
- v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py
- v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py
- v2/backend/tests/integration/cli/test_v2_top10_binance_dashboard_feed.py

85 of 85 tests pass. The LunarCrush suite grew from 19 to 21 cases.

## Allowed Redis writes (unchanged)

Only:

- v2:altdata:lunarcrush:status
- v2:altdata:lunarcrush:symbol:{symbol}

The safe-set boundary in _safe_redis_set is unchanged. Provider
integration scope is unchanged.

## Safety invariants (unchanged from the prior LunarCrush packet)

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
- paid_endpoints_enabled = false

## Runtime impact

LunarCrush is operator-invocable only; no LunarCrush daemon is
running. The four stricter constants take effect on the next
operator invocation of the CLI. The V2 paper/shadow runtime (full
observation builder, continuous remediation governor, liquidation
WSS persistent daemon, legacy log intelligence observer, account
permission soak) was not paused or reconfigured by this packet.

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not enable paid endpoints.
- Does not modify legacy.
- Does not change provider integration scope.
- Does not wire LunarCrush into the trainer / risk / orchestrator.
- Does not override the strict paper-fill gate.
- Does not synthesize signals.
- Does not commit any credential.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not create approval tokens.

## Outputs

- claude_worklog/final_readiness/v2_lunarcrush_free_tier_budget_remediation/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_lunarcrush_free_tier_budget_remediation/latest/V2_LUNARCRUSH_FREE_TIER_BUDGET_REMEDIATION_REPORT.md
- claude_worklog/final_readiness/v2_lunarcrush_free_tier_budget_remediation/latest/lunarcrush_free_tier_budget_remediation_status.json
- v2/frontend/public/operator_runtime/v2_lunarcrush_free_tier_budget_remediation/latest/operator_dashboard_payload.json
- v2/backend/app/services/alternative_data/lunarcrush_client.py (modified; 4 constants)
- v2/backend/tests/integration/cli/test_v2_lunarcrush_altdata_ingestor.py (modified; 2 new test cases)
