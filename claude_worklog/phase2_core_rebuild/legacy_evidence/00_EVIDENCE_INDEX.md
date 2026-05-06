# Legacy Evidence Index (REQ_0019)

Generated: 2026-05-06
Lane: `legacy_parity` (Lane D, read-only).
Purpose: single canonical citation index that V2 build milestones reference for `legacy_evidence_consulted`.

This file is a pointer index. It does not duplicate audit content. Each row names a source file and the subsections that cover the topic. Callers cite this index path plus the named anchor.

## Audit roots

| Root | Requirement | GO / NO-GO marker | Marker file |
|---|---|---|---|
| `claude_worklog/legacy_runtime_audit/` | REQ_0019 | `LEGACY_RUNTIME_AUDIT_READY` | `12_LEGACY_AUDIT_GO_NO_GO.md` |
| `claude_worklog/legacy_readonly_audit/` | REQ_0023 | `LEGACY_READONLY_AUDIT_SENTINEL_READY` | `10_GO_NO_GO.md` |
| `claude_worklog/historical_pnl_audit/` | REQ_0024 | `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` | `10_GO_NO_GO.md` |

## Topic → audit pointer

| Topic | REQ_0019 root | REQ_0023 root | REQ_0024 root |
|---|---|---|---|
| Process / service inventory | `01_PROCESS_AND_SERVICE_INVENTORY.md` | `01_PROCESS_SNAPSHOT.md` | — |
| Startup script / runtime map | — | `02_STARTUP_SCRIPT_MAP.md` | — |
| Code / function inventory | — | `03_LEGACY_CODE_FUNCTION_INVENTORY.md` | — |
| Service dependency graph | — | `04_SERVICE_DEPENDENCY_GRAPH.md` | — |
| Re-d-i-s read-only key / stream metadata | `02_REDIS_READ_ONLY_KEYSPACE_HEALTH.md` | `05_REDIS_READONLY_KEY_STREAM_INVENTORY.md` | — |
| Trainer runtime evidence | `03_TRAINER_RUNTIME_AUDIT.md` | `06_TRAINER_RUNTIME_EVIDENCE.md` | `07_LEGACY_TRAINER_DECISION_EVIDENCE.md` |
| Trader runtime evidence | `04_TRADER_RUNTIME_AUDIT.md` | `07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` | — |
| Orchestrator runtime evidence | `05_ORCHESTRATOR_RUNTIME_AUDIT.md` | `07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` | — |
| Ingestor runtime evidence | `06_INGESTOR_RUNTIME_AUDIT.md` | — | — |
| Symbol-universe runtime evidence | `07_SYMBOL_UNIVERSE_RUNTIME_AUDIT.md` | — | — |
| Feature-flow runtime evidence | `08_FEATURE_FLOW_RUNTIME_AUDIT.md` | — | — |
| Signal-to-execution runtime evidence | `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` | — | — |
| Risk / safety runtime evidence | `10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | — | — |
| Failure-mode register | `11_FAILURE_MODE_AND_GAP_REGISTER.md` | `08_FAILURE_CASE_REGISTER.md` | `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` |
| Realized PnL by day | — | — | `03_30D_REALIZED_PNL_BY_DAY.md` |
| Realized PnL by symbol | — | — | `04_30D_PNL_BY_SYMBOL.md` |
| Fees / funding / commission drag | — | — | `05_30D_FEES_FUNDING_COMMISSION.md` |
| Large winners / losers | — | — | `06_LARGE_WINNERS_AND_LOSERS.md` |
| Binance read-only pull summary | — | — | `02_BINANCE_READONLY_PULL_SUMMARY.md` |
| V2 build impact map | — | `09_V2_BUILD_IMPACT_MAP.md` | `09_V2_BUILD_IMPACT_MAP.md` |

## How to cite from a V2 build milestone

In a milestone's `legacy_evidence_consulted` field, list:

1. `claude_worklog/phase2_core_rebuild/legacy_evidence/00_EVIDENCE_INDEX.md`
2. The specific audit anchors the milestone actually consulted (filename + section heading), drawn from the topic table above.
3. Any milestone-specific evidence outside the three audit roots (for example `claude_worklog/legacy_preservation/…` or `claude_worklog/secret_migration/…`).

This pattern resolves the narrow-vs-wide citation argument flagged in `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_…RECONCILIATION_ADDENDUM.md`, `19_…RECONCILIATION_ADDENDUM.md`, and `27_…RECONCILIATION_ADDENDUM.md`.

## Hard safety

This index does not enable, suggest, justify, or describe any:

- modification of `/home/wali/Desktop/AI BOT`
- read or write of any Re-d-i-s key
- restart of any live trainer / trader / orchestrator / ingestor / Re-d-i-s service
- exchange order, leverage, or margin action
- live-trading enablement
- deployment or production migration
- exposure or commit of any secret value

REQ_0019_LEGACY_EVIDENCE_INDEX_READY
