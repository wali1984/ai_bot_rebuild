# Legacy Script Validation Report

Generated UTC: 2026-06-03T22:55:42Z
Scope: `v2/legacy_owned_runtime` Python, shell, and PowerShell scripts.
Safety: static pass only; no legacy Python modules were imported or executed.

## Summary
- Scripts inventoried: 708
- Syntax status: `{'not_checked_pwsh_missing': 2, 'ok': 706}`
- Runtime classes: `{'api_static_validated_runtime_not_started': 5, 'covered_by_v2_native_ingestors_live_loop': 1, 'legacy_ingestor_static_validated_runtime_not_started': 5, 'operator_gated_destructive_or_maintenance_not_executed': 91, 'operator_gated_exchange_mutation_not_executed': 13, 'operator_gated_keyed_or_paid_ingestor_not_executed': 15, 'operator_gated_trading_runtime_not_executed': 65, 'static_validated_not_runtime_started': 133, 'trainer_or_rl_static_validated_runtime_gated': 376, 'validated_by_v2_coinank_and_liquidation_bridge': 2, 'validated_by_v2_legacy_ingestor_adapter': 2}`
- Safe V2-covered runtime probes: 5
- Operator-gated scripts not executed: 184

## Syntax Failures
- None.

## Safe V2-Covered Scripts
- `ingest/liquidation_bridge.py` -> `validated_by_v2_coinank_and_liquidation_bridge`
- `ingest/live_coinank_global_aggregator.py` -> `validated_by_v2_coinank_and_liquidation_bridge`
- `ingest/live_coinapi_v1.py` -> `validated_by_v2_legacy_ingestor_adapter`
- `ingest/live_kucoin.py` -> `validated_by_v2_legacy_ingestor_adapter`
- `ingest/realtime_price_provider.py` -> `covered_by_v2_native_ingestors_live_loop`

## Top Missing Third-Party Imports
- None detected by static import scan.

## Verdict
All legacy scripts were inventoried and statically classified. Runtime execution is only considered safe through V2-covered adapters/native workers or explicit operator-gated starts; direct blanket execution of the legacy folder remains blocked because trading, cleanup, restart, and un-prefixed Redis-write scripts are present.
