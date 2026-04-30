# 04 Legacy Config Map

## Summary
- Config/env reference matches: 18596
- Files with config/env references: 3827
- Core config anchors observed: `config.py`, `config/settings.py`, startup scripts, API routes.

## Config areas
- Symbol/timeframe configuration: references through `config.py` and trainer/trader imports.
- Leverage/margin/risk config: observed in trader/base_executor/config references.
- Trainer config: trainer atlas + config usage artifacts.
- Runtime config sources: startup scripts + env map references.

## Missing or unclear config sources
- Env-defined toggles referenced in docs/start scripts may not map 1:1 to runtime code paths.
- Some docs reference legacy env wrappers; treat docs as claims pending runtime validation.

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
- Medium
