# V2 Alternative Data Provider Registry, Rate Limit, And Dashboard Scaffold

Generated: `2026-05-18T01:27:28Z`

GO/NO-GO: `V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_READY`

## Decision

The V2 alternative-data scaffold is implemented at the registry/rate-limit/cache/dashboard-contract scope. This packet does not implement provider clients and does not call Nansen, LunarCrush, Arkham, Binance, CoinAnk, or liquidation provider APIs.

This packet does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, external feed adoption, paid endpoints, or legacy shutdown.

## Implemented Files

- `v2/backend/app/services/alternative_data/provider_registry.py`
- `v2/backend/app/services/alternative_data/rate_limits.py`
- `v2/backend/app/services/alternative_data/cache.py`
- `v2/backend/app/services/alternative_data/symbol_scoring_contract.py`
- `v2/backend/app/cli/v2_alternative_data_status.py`
- `v2/backend/tests/integration/cli/test_v2_alternative_data_status.py`

## Providers

The scaffold contains exactly the allowed provider set:

- `nansen`
- `lunarcrush`
- `arkham_future`
- `binance_existing`
- `coinank_existing`
- `liquidation_wss_existing`

Arkham remains future-placeholder only. Existing Binance, CoinAnk, and liquidation WSS are preserved as already-integrated V2/native baseline sources.

## Safety And Scope

- Raw key values are never emitted in status payloads, public payloads, Redis values, task descriptors, or stdout.
- Provider network calls attempted: `false`.
- Dry-run only: `true`.
- Paid tier enabled: `false`.
- Checkpoint compatibility claimed: `false`.
- Policy architecture parity claimed: `false`.
- Alternative data may not override the strict paper-fill gate.
- Alternative data may not authorize live/canary or place/cancel/modify orders.

## Redis Writes

The CLI writes only the approved V2 namespaces:

- `v2:altdata:provider_status`
- `v2:altdata:symbol_score:BTCUSDT`
- `v2:altdata:symbol_score:ETHUSDT`
- `v2:altdata:symbol_score:SOLUSDT`
- `v2:symbol_universe:altdata_candidates`

No old Redis key is written.

## Outputs

- `claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/alt_data_status.json`
- `claude_worklog/final_readiness/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/GO_NO_GO.md`
- `v2/frontend/public/operator_runtime/v2_alternative_data/latest/v2_alternative_data_status.json`
- `v2/frontend/public/v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/operator_dashboard_payload.json`

## Validation

- Focused tests: `8 passed`.
- `py_compile`: PASS.
- Raw secret-value scan: PASS.
- Forbidden provider occurrence scan: PASS, `0` hits.
- Network/exchange mutation import scan over app code: PASS.
- Redis write contract check: PASS.
- `git diff --check`: PASS.
- Continuous remediation governor refresh: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_old_redis`: `false`
- `exchange_mutation`: `false`

## Final Decision

`V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_READY`
