# Codex Review: V2 Alternative Data Integration Plan Clean No Forbidden Provider

Generated: `2026-05-18T01:20:58Z`

GO/NO-GO: `V2_ALTERNATIVE_DATA_INTEGRATION_PLAN_CODEX_PASS`

## Decision

Codex passes the cleaned alternative-data integration plan at the plan-only scope. The provider family that caused the prior fail is no longer present in the new lane, and there is no exclusion-marker row for it.

This review does not approve provider-client implementation, external feed adoption, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Evidence Reviewed

Reviewed current artifacts:

- `V2_ALTERNATIVE_DATA_INTEGRATION_PLAN.md`
- `alternative_data_provider_registry.json`
- `alternative_data_feature_contract.json`
- `alternative_data_symbol_universe_contract.json`
- `alternative_data_dashboard_contract.json`
- `v2/frontend/public/v2_alternative_data_integration/latest/operator_dashboard_payload.json`
- Codex-only custody payloads under `v2_alternative_data_secret_custody/latest`

JSON validation passed for the provider registry, feature contract, symbol-universe contract, dashboard contract, and public dashboard payload.

## Provider Scope

The approved plan providers are exactly:

- `nansen`
- `lunarcrush`
- `arkham_future`
- `binance_existing`
- `coinank_existing`
- `liquidation_wss_existing`

Codex verified:

- Nansen is present as a planned provider.
- LunarCrush is present as a planned provider.
- Arkham is future/placeholder-only and not integrated today.
- Existing Binance, CoinAnk, and liquidation WSS lanes are preserved.
- The previously forbidden provider family has `0` occurrences in the new lane.
- No exclusion-marker provider row exists for the forbidden provider family.

## Credential Safety

The raw Nansen and LunarCrush key values remain only in `.local_secrets/alternative_data.env`. Codex scanned the plan, public payload, task descriptors, and non-secret git diff against the local vault values and found no raw secret-value hits.

The plan requires:

- no raw credentials in worklogs;
- no raw credentials in public payloads or frontend;
- no raw credentials in task descriptors;
- no raw credentials in logs/stdout/stderr;
- dashboard payloads show only redacted/env-name status.

## Tier And Rate Controls

The plan defaults to free tier:

- `ALT_DATA_TIER=free`
- `ALT_DATA_ENABLE_PAID=false`

Paid mode is disabled by default. The paid upgrade is config-only, but paid endpoints remain blocked until later operator approval and Codex review.

Rate controls are defined:

- provider rate limits;
- cache TTLs;
- daily request budgets;
- per-symbol cooldowns;
- stale-but-safe fallback;
- provider failure isolation.

Provider failure is explicitly forbidden from stopping the V2 runtime.

## Integration Boundaries

The plan is explicit and bounded:

- Symbol Universe integration is documented under `v2:symbol_universe:altdata_candidates`.
- Full-observation/feature integration remains not wired pending Codex dimension-contract review.
- `checkpoint_compatibility_claimed=false`.
- `policy_architecture_parity_claimed=false`.
- Trainer/trader/risk/orchestrator use is paper/shadow-only.
- Alternative data may score, filter, or annotate, but cannot override the strict paper-fill gate.
- Alternative data cannot authorize live/canary and cannot place/cancel/modify orders.

## Dashboard Contract

The top-10 dashboard contract is present with `panel_count=10` and includes the Binance panels:

- `binance_12h_volume_leaders`
- `binance_12h_most_traded`
- `binance_12h_volatility_leaders`

The remaining contracted panels cover liquidation tape, funding/open-interest intelligence, Nansen, LunarCrush, Arkham future placeholder, Symbol Universe ranking, and trainer/risk decision overlay. Each panel requires missing/stale flags and forbids raw credentials in payloads.

## Runtime Governor

The standing remediation governor was refreshed and remains healthy:

- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- V2/remediation processes: `12/12`
- 6h soak remains passed.
- V2 Redis namespaces remain non-empty.
- Full observation builder payload remains fresh and partial.
- No fail blockers were emitted.
- Liquidation WSS and existing runtime/remediation loops were not paused by this plan.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- `writes_old_redis`: `false`
- `exchange_mutation`: `false`

## Validation

- Structured plan checks: PASS.
- Raw secret-value scan: PASS.
- Forbidden provider occurrence scan: PASS, `0` hits.
- JSON validation: PASS.
- `git diff --check`: PASS for reviewed artifacts.
- Runtime governor refresh: PASS.

## Non-Approval Items

- Provider clients are not implemented.
- External feed adoption is not approved.
- Paid tier is not enabled.
- Checkpoint compatibility is not claimed.
- Policy architecture parity is not claimed.
- Live and shutdown remain blocked.

## Final Decision

`V2_ALTERNATIVE_DATA_INTEGRATION_PLAN_CODEX_PASS`
