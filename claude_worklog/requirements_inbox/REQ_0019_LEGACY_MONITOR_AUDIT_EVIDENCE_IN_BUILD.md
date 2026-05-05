# Requirement 0019 - Use Legacy Monitor and Audit Evidence During V2 Build

## Objective

Claude must use read-only legacy monitor/audit evidence while building V2 so the new system is based on actual legacy runtime behavior, failures, and gaps.

This must support the paper/backtest MVP path, not distract from it.

## Core rule

Legacy monitoring and audit evidence should inform V2 build decisions.

Claude may read:
- legacy read-only audit reports
- monitor snapshots
- process/service inventories
- Redis read-only health summaries
- trainer liveness reports
- trader/orchestrator status reports
- ingestor freshness reports
- symbol universe evidence
- feature pipeline audit reports
- signal/proposal/execution audit reports
- failure/gap registers

Claude may not mutate the legacy bot.

## Hard safety boundaries

Forbidden:
- modifying `/home/wali/Desktop/AI BOT`
- Redis writes/deletes
- live service restarts
- exchange/order/leverage/margin actions
- deployment
- live trading enablement
- secret exposure

## Required use in V2 build

For each V2 module, Claude must check legacy audit evidence before implementation.

### Trainer prediction output

Use legacy evidence to answer:
- how trainer currently starts
- what GPU/checkpoint assumptions exist
- what prediction worker failures were observed
- what prediction/proposal streams exist
- whether confidence is missing or unreliable
- how process-alive/worker-dead states appear

### Orchestrator decision MVP

Use legacy evidence to answer:
- what signals/proposals exist
- what decision routing exists
- what missing lineage exists
- what duplicate/stale signal behavior exists

### Risk gateway MVP

Use legacy evidence to answer:
- which bad trades should have been blocked
- which stale/missing data cases occurred
- what drawdown/loss patterns were observed
- what external/manual position risks exist

### Paper/backtest runner

Use legacy evidence to answer:
- what data streams can be replayed
- which symbols/timeframes have sufficient evidence
- what legacy actions should be compared against V2
- what PnL/drawdown attribution is available

### Website/explainability

Use legacy evidence to show:
- trainer health
- worker liveness
- ingestor freshness
- symbol state
- signal lineage
- risk decisions
- paper/shadow vs legacy comparison

## Required artifacts

Create or maintain:

- `claude_worklog/legacy_runtime_audit/`
- `claude_worklog/continuous_monitoring/`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/00_EVIDENCE_INDEX.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/01_BUILD_IMPACT_MAP.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/03_V2_REQUIREMENTS_FROM_RUNTIME_AUDIT.md`

## Planner rule

Until `V2_BACKTEST_AND_PAPER_MVP_READY`, legacy evidence may only drive tasks in approved lanes:

- paper_backtest_mvp
- explainability_ui
- codex_watchdog
- legacy_parity

Do not create broad audit-only work unless it directly supports the MVP path.

## Codex role

Codex must verify:
- legacy evidence was read
- V2 module reflects actual legacy behavior
- no legacy mutation occurred
- no Redis write occurred
- no live service restart occurred
- no exchange action occurred
- evidence improves paper/backtest readiness

REQ_LEGACY_MONITOR_AUDIT_EVIDENCE_IN_BUILD_READY
