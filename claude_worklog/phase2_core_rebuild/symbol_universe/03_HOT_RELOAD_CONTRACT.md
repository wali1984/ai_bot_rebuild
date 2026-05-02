# Hot Reload Contract

Universe version fields:
- `universe_version_id`
- `generated_ts`
- `source_snapshot_ids`
- `changed_symbols`
- `added_symbols`
- `removed_symbols`
- `disabled_symbols`
- `override_symbols`
- `reason`
- `approval_state`
- `hot_reload_required_components`

Required hot-reload components:
- ingestors
- feature_pipeline
- trainer
- orchestrator
- risk_gateway
- trader_fleet
- monitor
- gui

The contract is local and non-live. It identifies which components must observe a universe version change. It does not restart live services.

HOT_RELOAD_CONTRACT_READY
