# WEBSITE_PARALLEL_TASK_REALIGNED_TO_MIGRATED_V2 — Phase J

## Rule

The parallel website task (`parallel_trading_platform_consumer_ui_from_real_v2_payloads`) consumes **only** V2-namespaced worker payloads. It must **not** treat legacy runtime evidence as current truth.

## Allowed website data sources (only these)

| concern | source |
|---|---|
| selected paper symbol + live gate banner | `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` (when paper_online_runtime is running) |
| paper-shadow observation | `v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json` |
| feature snapshot (current) | `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json` (shipped, fresh) |
| market data | once v2_market_ingestor_from_legacy_baseline ships: `v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json` |
| CoinAnk market intelligence | once v2_coinank_and_liquidation_bridge ships: `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` |
| feature pipeline + TA | once v2_feature_pipeline_and_ta_worker ships: `v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json` |
| trainer prediction | once v2_trainer_bridge ships |
| orchestrator decision | once v2_orchestrator_adapter ships |
| signal lineage | once v2_signal_lineage_worker ships |
| risk decision | once v2_risk_gateway_runtime_worker ships |
| paper execution | once v2_paper_execution_worker ships |
| account/position state | once v2_account_position_monitor ships (and only with explicit `MISSING_CREDENTIALS` when keys absent) |
| migration progress | `v2/frontend/public/v2_worker_porting_orchestrator/latest/operator_dashboard_payload.json` |
| baseline migration status | `v2/frontend/public/legacy_startup_baseline_v2_migration/latest/operator_dashboard_payload.json` |

## Forbidden website behavior

- **Never** consume legacy Redis keys directly from the website. The legacy stack is a runtime reference for porting only; the website is built on V2 payloads.
- Never show `hist_*` records as current.
- Never show `STATIC_PROOF_FIXTURE` as primary.
- Never label a paper-mode simulation as real account/position evidence.
- Never enable any live trading control surface.
- If a V2 worker payload is missing, show explicit `MISSING_EVIDENCE` rather than falling back to legacy.

## Allowed labelled fallback

If a worker is not yet migrated and the operator chooses to surface a legacy stream temporarily, the panel must be labelled:

```text
LEGACY_RUNTIME_REFERENCE_ONLY
```

…and the GUI must indicate that this view will be replaced once the corresponding V2 worker ships.

## Hard-constraint compliance

- The website task remains lower priority than baseline worker migration; the non-drift governor lock continues to block it from running as primary.
- The website task does not modify legacy paths.
- The website task does not place orders, change leverage/margin, or unlock the gate.
- The website task does not write any Redis namespace.
