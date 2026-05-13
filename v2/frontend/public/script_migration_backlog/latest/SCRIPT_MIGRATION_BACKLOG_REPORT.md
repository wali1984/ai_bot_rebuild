# Script Migration Backlog Report

Status: `SCRIPT_MIGRATION_BACKLOG_READY`

- generated_at: `2026-05-12T23:21:55.321642+00:00`
- source registry: `claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json`
- canonical registry decision: `Phase 3A SCRIPT_REGISTRY.json plus Phase 3B remediation overlays`
- Phase 3A raw atlas marker: `PHASE3A_SYSTEM_ATLAS_12H_RUNTIME_COVERAGE_AND_EVIDENCE_INTEGRITY_BLOCKED`
- Phase 3B remediation overlay marker: `PHASE3B_SYSTEM_ATLAS_GAP_REMEDIATION_ZERO_UNKNOWNS_READY`
- scripts inventoried: `4194`
- active runtime scripts: `7`
- zero unclassified active runtime scripts: `True`
- exchange-action scripts mapped: `344`
- Redis-writer scripts mapped: `445`
- unsafe_unknown total: `2093`

Active runtime scripts are explicitly classified in `script_migration_backlog.json`. The raw Phase 3A atlas remains blocked as a standalone live-readiness source, so this backlog uses the Phase 3A registry plus Phase 3B remediation overlays. Unknown non-active scripts remain queued as `unknown_needs_evidence` and must be cleared before live cutover.

## CoinAnk Plan-3 Bridge Update
- Updated at: `2026-05-13T00:45:24Z`
- Updated paths: `feature_pipeline.py, ingest/coinank_pipeline_monitor.py, ingest/liquidation_bridge.py, ingest/liquidation_levels_engine.py, ingest/live_coinank.py, ingest/live_coinank_global_aggregator.py`
- V2 action: live CoinAnk remains read-only evidence until ported; V2 bridge writes only V2 payloads.
- Runtime classifications: `COINANK_PATCH_RUNTIME_CURRENT, COINANK_MANIFEST_MISSING, COINANK_GLOBAL_11_KEY_CONTRACT_CURRENT, COINANK_FORBIDDEN_MARKET_SOURCE_OBSERVED, COINANK_CONTRACT_BLOCKED`
- Live gate: `blocked_human_only`

## CoinAnk Plan-3 Runtime Remediation Update
- Updated at: 2026-05-13T01:10:03Z
- Runtime classifications: LASTPRICE_STALE_KEY_ONLY, COINANK_MANIFEST_CURRENT, COINANK_GLOBAL_11_KEY_CONTRACT_CURRENT, NO_FORBIDDEN_ORDERBOOK_SOURCE_CURRENT, RUNTIME_CYCLES_PASSED, COINANK_PATCH_RUNTIME_CURRENT
- V2 action remains wrap/read-only first, then port to V2-owned market data workers.
