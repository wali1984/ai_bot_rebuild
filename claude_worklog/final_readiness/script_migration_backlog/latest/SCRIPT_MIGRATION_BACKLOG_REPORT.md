# Script Migration Backlog Report

Status: `SCRIPT_MIGRATION_BACKLOG_READY`

- generated_at: `2026-05-12T23:07:37.841899+00:00`
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
