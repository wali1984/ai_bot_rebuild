V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_REMEDIATION

Generated: 2026-05-15T00:10:24Z

Status: BLOCKED

Codex took over this remediation because the supervised Claude task `claude_v2_trainer_lineage_attribution_parity_remediation` stalled for more than 10 minutes with zero stdout, zero stderr, and no emitted artifacts.

Evidence inspected:
- `v2/backend/app/services/trainer_bridge/service.py`
- `v2/backend/app/cli/v2_trainer_bridge.py`
- `v2/legacy_preserved/full_runtime_closure/rl/hybrid_trainer.py`
- `v2/legacy_preserved/full_runtime_closure/rl/confidence_gates.py`
- `v2/legacy_preserved/full_runtime_closure/rl/calibrated_confidence.py`
- `v2/legacy_preserved/full_runtime_closure/rl/decision_trace.py`
- `v2/legacy_preserved/full_runtime_closure/rl/unified_feature_builder.py`
- `v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py`
- `v2/legacy_preserved/full_runtime_closure/rl/feature_health.py`
- read-only legacy trainer log evidence
- V2 feature snapshot, feature pipeline, and Symbol Universe public payloads

Implemented remediation:
- Legacy log action-probability evidence is no longer exposed as `top_positive_features` or `top_negative_features`.
- Action probabilities remain available as `action_probability_evidence`.
- `feature_snapshot_link_mode`, `feature_snapshot_id_classification`, `confidence_calibration_mode`, `feature_attribution_status`, `field_classification`, `remaining_parity_gaps`, `trainer_parity_status`, `derived_feature_snapshot_link`, and `symbol_universe_scope` are now emitted.
- V2 feature snapshot `unused_features` now propagates as `unused_feature_flags`.
- Derived V2 feature snapshot links are labeled `derived_feature_snapshot_link` only when timestamp, symbol, timeframe, and freshness match. The link remains derived evidence, not native trainer parity.

Current classification:
- feature_snapshot_id: DERIVED_FROM_LEGACY_LOG
- confidence_calibration: DERIVED_FROM_LEGACY_LOG
- feature_attribution: INCOMPLETE_ATTRIBUTION
- trainer_parity_status: BLOCKS_LEGACY_SHUTDOWN

Current runtime payload evidence:
- `prediction_id`: present
- `feature_snapshot_id`: present but derived from legacy log evidence unless a matched V2 snapshot link is available
- `feature_snapshot_link_mode`: DERIVED_FROM_LEGACY_LOG
- `raw_confidence`: present
- `calibrated_confidence`: present but derived from the same legacy log confidence field
- `confidence_calibration_mode`: DERIVED_FROM_LEGACY_LOG
- `top_positive_features`: []
- `top_negative_features`: []
- `action_probability_evidence`: present
- `checkpoint_id`: present
- `model_version`: legacy_hybrid_trainer_live_legacy
- `live_gate`: blocked_human_only
- `live_symbols`: []

Remaining parity gaps:
- LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED
- LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED
- LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE

Safety result:
- No legacy tree mutation.
- No old Redis write.
- No exchange action.
- No leverage or margin change.
- No live activation.
- No final approval token creation.

Validation:
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/integration/cli/test_v2_trainer_bridge.py -p no:cacheprovider --basetemp=/tmp/codex_trainer_lineage_pytest`
- Result: 11 passed.

GO/NO-GO:
- V2_TRAINER_LINEAGE_ATTRIBUTION_PARITY_BLOCKED
