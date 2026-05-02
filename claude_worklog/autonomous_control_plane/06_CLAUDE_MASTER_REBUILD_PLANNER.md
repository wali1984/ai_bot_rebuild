# Claude Master Rebuild Planner

## Purpose

Stop hand-authored task sequencing for the non-live V2 rebuild.

Claude Code should read the full repository context, legacy audits, preservation policies, V2 scaffold, and `legacy_reference`, then autonomously select the next safe non-live rebuild milestone.

## Workflow

1. Claude maps legacy behavior and current V2 state.
2. Claude plans the next non-live milestone.
3. Supervisor executes safely inside AI BOT REBUILD.
4. Codex reviews adversarially.
5. Claude remediates safe findings.
6. The sequence continues until final live gate.

## Human Intervention Gates

Human approval is required only for:
- live trading
- legacy bot mutation
- Redis writes/deletes
- live service restarts
- exchange actions
- deployment
- secrets exposure
- L4/L5 actions
- Codex hard fail with no safe remediation

## Preservation Requirements

- `live_coinank.py` remains exact copy-as-is.
- Ingestors and `feature_pipeline.py` preserve behavior before enhancement.
- Trainer/GPU behavior must be parity-rebuilt, not replaced with a basic trainer.
- Current legacy config symbols are active subset only.
- V2 symbol universe is all discoverable futures markets plus normalized aliases.

CLAUDE_MASTER_REBUILD_PLANNER_READY
