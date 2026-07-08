# Claude/Fable Alignment Review - 2026-07-08

## Scope

This review reconciles the Claude/Fable audit artifacts with the current V2
same-day provider-rate-limited cutover plan. It does not approve live trading,
test orders, leverage changes, margin-mode changes, or unrestricted runtime
restarts.

Reviewed artifacts:

- `claude_worklog/COMPREHENSIVE_COINANK_LEGACY_V2_AUDIT_2026_07_08.md`
- `claude_worklog/COINANK_AUDIT_TECHNICAL_FINDINGS_2026_07_08.md`
- `claude_worklog/AUDIT_EXECUTIVE_SUMMARY_2026_07_08.txt`
- `claude_worklog/NEXT_STEPS_AND_DECISIONS_2026_07_08.md`
- `/home/wali/.codex/attachments/51d92840-98c3-4dfa-a990-2f26a6cb0021/pasted-text-1.txt`
- `/home/wali/.codex/attachments/87284e03-660e-4f37-911c-38769e16cfd0/goal-objective.md`

## Resolution Summary

The Claude/Fable audit is useful as historical context, but it contained
operator-facing instructions and readiness claims that were not safe to treat as
an execution plan. The four worklog documents now include Codex alignment notes.
The actionable runbook sections were changed to read-only verification first and
explicit operator approval for runtime repair or Redis mutation.

## Conflicts Resolved

| Conflict | Resolution |
|---|---|
| Directly restart legacy CoinAnk ingestor from audit docs | Replaced with read-only CoinAnk truth checks and explicit operator-approval requirement before runtime repair. |
| Ad hoc `redis-cli KEYS ... EXPIRE ...` TTL mutation | Replaced with reviewed-code TTL hygiene requirement. |
| Heartbeat-only provider status could be interpreted as green | Marked as forbidden. Current provider panels require actual payloads. |
| CoinGlass/Moralis described mainly as generic supplement choices | Reframed around the provider-rate-limited implementation with registries, cadences, budgets, contracts, and feature mapping. |
| Moralis free-tier assumptions and per-symbol polling risk | Replaced with CU-budgeted wallet/token/stream cadence; every-symbol-every-minute polling is forbidden. |
| Optional provider failures could look core-blocking | Marked non-core-blocking unless a consumer explicitly requires a provider. |
| Probation/live-readiness language was too loose | Marked probation as not final A+ and not live-ready. |
| Historical counts and health claims sounded current | Marked all Redis counts, endpoint health, feature counts, and win-rate claims as point-in-time evidence requiring re-verification. |

## Provider-Rate-Limited Artifacts

The current implementation addresses the provider plan with these concrete files:

- CoinGlass endpoint registry: `v2/backend/app/services/coinglass_provider/endpoint_registry.py`
- CoinGlass token-bucket limiter: `v2/backend/app/services/coinglass_provider/rate_limit.py`
- CoinGlass per-endpoint cadence and request budget: `coinglass_endpoint_registry()` and `v2/backend/app/cli/v2_provider_scheduler_status.py`
- Moralis endpoint registry: `v2/backend/app/services/smart_money_wallets/endpoint_registry.py`
- Moralis compute-unit budget limiter: `v2/backend/app/services/smart_money_wallets/cu_budget.py`
- Moralis wallet/token/stream cadence: `moralis_endpoint_registry()` and `v2/backend/app/cli/v2_provider_scheduler_status.py`
- Provider Redis key contract: `v2/backend/app/services/provider_features/contracts.py`
- Endpoint-to-feature mapping: `endpoint_to_feature_mapping()` in `v2/backend/app/services/provider_features/contracts.py`
- Actual-data dashboard/iOS panel contract: `ProviderFeatureBridge.actual_data_panel()` in `v2/backend/app/services/provider_features/provider_feature_bridge.py`
- Trainer/risk/orchestrator/allocator/paper/live-dry-run consumption: `CONSUMER_ROLES` and `build_provider_consumer_context()` in `v2/backend/app/services/provider_features/`
- Same-day cutover CLI and final CEO packet: `v2/backend/app/cli/v2_same_day_production_cutover_status.py`

## Safety Contract

The aligned plan keeps these guarantees:

- Do not only publish health keys.
- Do not mark heartbeat-only green.
- Do not call Moralis on every symbol every minute.
- Do not exceed CoinGlass public request limits.
- Do not expose API keys.
- Do not count optional provider failures as core-blocking.
- Do not mark live-ready from probation.
- Do not submit live orders, test orders, cancellations, leverage changes, margin
  changes, transfers, or withdrawals from this worklog.

## Current State

Status: `ALIGNMENT_DOCS_PATCHED_RUNTIME_UNCHANGED`

The docs are now aligned with the provider-rate-limited cutover design. Runtime
execution still requires separate validation and operator approval where it
changes live or exchange-touching behavior.
