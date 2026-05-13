
# P0/P1 Script Migration Execution Plan

Generated: `2026-05-13T05:08:06Z`

The backlog remains incomplete. This sprint does not claim full script migration. It selects two high-impact rows and converts them into V2 modules with tests.

| priority | legacy path | V2 module | action | test | GUI route |
|---|---|---|---|---|---|
| P0 execution/risk/live safety | legacy_reference/trading/trader.py | v2.backend.app.composition.execution_attribution_normalizer | migrated_to_v2 | v2/backend/tests/unit/composition/execution_attribution_normalizer/test_runtime.py | /admin/executions?role=admin |
| P1 trainer/feature/signal lineage | legacy_reference/feature_pipeline.py | v2.backend.app.composition.current_signal_lineage_adapter | migrated_to_v2 | v2/backend/tests/unit/composition/current_signal_lineage_adapter/test_runtime.py | /admin/signal-explainability?role=admin |

Backlog counts are still operationally significant: `{'backlog_not_migrated': 188, 'v2_namespace_wrapper_exists': 224, 'monitor_only': 1671, 'wrapped_readonly_in_v2': 2112}`.
