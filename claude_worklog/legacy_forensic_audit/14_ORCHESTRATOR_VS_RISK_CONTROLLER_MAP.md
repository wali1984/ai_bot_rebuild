# 14 Orchestrator vs Risk Controller Map

## Summary
Boundary definition for legacy-to-V2 governance:
- Legacy orchestrator: proposal shaping, action routing, timing/aggregation semantics.
- New orchestrator (target): deterministic proposal planner, not final risk authority.
- Risk gateway (must own): allow/block decisions, margin/leverage policy, safety overrides, execution eligibility.
- Anti-redundancy boundary: one final execution authority, no duplicated risk logic across orchestrator/trader.
- Audit ledger requirement: every decision edge must be attributable and replayable.

## Evidence anchors
- `rl/orchestrator_worker.py`, `rl/tradeplan_orchestrator.py` via Tier A plan.
- Trader execution/risk paths via exchange+redis maps.
- Codex checker confirms critical coverage complete for forensic analysis phase.

## Raw evidence pointers
- claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md

## Source artifacts used
- claude_worklog/coverage/FILE_MANIFEST.json
- claude_worklog/coverage/SCRIPT_REGISTRY.json
- claude_worklog/coverage/SCRIPT_DEPENDENCY_GRAPH.json
- claude_worklog/coverage/STARTUP_PATH_MAP.json
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/CONFIG_ENV_MAP.json

## Verification commands
- python3 tools/show_file_range.py --file "./legacy_reference/rl/hybrid_trainer.py" --start 1 --end 80
- python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 30000 --end 30120
- python3 tools/codex_adversarial_coverage_check.py

## Unresolved questions
- Which Tier A unresolved items need code-owner adjudication before production deprecation mapping?
- Which legacy scripts are wrappers only and can be archived in V2 migration phase?

## Confidence level
- Medium-High
