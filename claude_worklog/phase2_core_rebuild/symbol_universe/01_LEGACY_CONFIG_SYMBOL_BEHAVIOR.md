# Legacy Config Symbol Behavior

The current legacy `config.py` symbol list is preserved as the current active legacy ingestion/trading subset.

It is not the complete V2 universe.

V2 distinguishes:
- `all_discovered_symbols`
- `observed_symbols`
- `training_symbols`
- `paper_symbols`
- `shadow_symbols`
- `live_blocked_symbols`
- `manual_override_symbols`
- `legacy_active_symbols`

Rules:
- Do not overwrite legacy `config.py`.
- Do not remove the current legacy active behavior.
- V2 may read key names and active symbol shape from local copied/config snapshots without secret values.
- Dynamic V2 universe changes are additive and adapter-driven.
- GUI/admin controls later choose active subsets from the broader discovered universe.

LEGACY_CONFIG_SYMBOL_BEHAVIOR_PRESERVED_AS_SUBSET
