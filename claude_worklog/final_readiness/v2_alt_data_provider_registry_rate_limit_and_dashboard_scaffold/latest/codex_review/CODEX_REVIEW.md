# Codex Review: V2 Alternative Data Provider Registry, Rate Limit, And Dashboard Scaffold

Generated: `2026-05-21T03:50:28Z`

GO/NO-GO: `V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_CODEX_PASS`

## Decision

Codex passes the alternative-data scaffold at the registry, free-tier rate-limit/cache, symbol scoring contract, dashboard/status payload, and status CLI scope.

This review does not approve provider-client implementation, provider network calls, paid endpoints, external feed adoption, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Scope Reviewed

Reviewed:

- `v2/backend/app/services/alternative_data/provider_registry.py`
- `v2/backend/app/services/alternative_data/rate_limits.py`
- `v2/backend/app/services/alternative_data/cache.py`
- `v2/backend/app/services/alternative_data/symbol_scoring_contract.py`
- `v2/backend/app/cli/v2_alternative_data_status.py`
- `v2/backend/tests/integration/cli/test_v2_alternative_data_status.py`
- `claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/alt_data_status.json`
- `v2/frontend/public/operator_runtime/v2_alternative_data/latest/v2_alternative_data_status.json`
- `v2/frontend/public/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/operator_dashboard_payload.json`

Codex treated later provider-client modules in the broader `alternative_data` package as out of scope for this scaffold review. The reviewed scaffold CLI does not import Nansen, LunarCrush, Arkham, Binance, CoinAnk, liquidation provider clients, or network libraries.

## Provider Registry

The provider set is exactly:

- `nansen`
- `lunarcrush`
- `arkham_future`
- `binance_existing`
- `coinank_existing`
- `liquidation_wss_existing`

`arkham_future` is `PLACEHOLDER_FUTURE_ONLY_NO_INTEGRATION_TODAY` with `future_placeholder_only=true`. The only Arkham dashboard reference is explicitly future-only. No extra provider IDs were found in the reviewed scaffold payloads.

## Tier And Network Boundary

The scaffold remains default-free-tier and dry-run only:

- `ALT_DATA_TIER=free`
- `ALT_DATA_ENABLE_PAID=false`
- `paid_tier_enabled=false`
- `provider_network_calls_attempted=false`
- `dry_run_only=true`
- `raw_values_exposed=false`

Static/import checks show the reviewed scaffold path does not import `urllib.request`, `requests`, `httpx`, `aiohttp`, `websockets`, `nansen_client`, or `lunarcrush_client`. The focused source scan found no provider API call, Binance order endpoint, test-order endpoint, leverage/margin endpoint, cancel/modify endpoint, or exchange mutation path.

## Redis Contract

The only allowed Redis writes are:

- `v2:altdata:provider_status`
- `v2:altdata:symbol_score:{symbol}`
- `v2:symbol_universe:altdata_candidates`

`safe_redis_set` refuses all other keys. The current Redis scan found no live `v2:altdata:*` or `v2:symbol_universe:altdata_candidates` keys, so there is no unexpected active Redis state. The reviewed source contains no old Redis namespace writes.

## Symbol Scoring And Gate Safety

The symbol scoring contract consumes only already-provided payloads. It never calls provider APIs, never writes Redis, leaves missing provider data explicit, and emits:

- `network_call_attempted=false`
- `paper_shadow_only=true`
- `may_not_override_strict_paper_fill_gate=true`
- `may_not_authorize_live_or_canary=true`
- `may_not_place_orders=true`

The symbol-universe contract also leaves paper symbol expansion blocked and keeps `live_symbols=[]`.

## Runtime And Approval Safety

The reviewed status mirrors report:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `writes_old_redis=false`
- `exchange_mutation=false`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

Codex loaded local secret values for comparison only and scanned reviewed source, worklog status, public payloads, and tests. Raw secret-value hits outside `.local_secrets`: `0`.

## Governors

Standing governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- fail blockers: none

## Validation

- Focused scaffold tests: `8 passed`.
- `py_compile`: PASS.
- JSON payload inspection: PASS.
- Provider set exact-match check: PASS.
- Arkham future-placeholder check: PASS.
- Free-tier / paid-disabled check: PASS.
- Network-client import check: PASS.
- Provider API / exchange mutation source scan: PASS.
- Redis write allowlist scan: PASS.
- Old Redis write scan: PASS.
- Raw credential scan: PASS, `0` hits outside `.local_secrets`.
- Approval drift scan: PASS.

## Final Decision

`V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_CODEX_PASS`
