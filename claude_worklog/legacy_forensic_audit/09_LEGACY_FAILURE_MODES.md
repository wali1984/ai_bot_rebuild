# 09 Legacy Failure Modes

## Summary
Failure modes tracked for forensic continuity (evidence-backed + known incident references):
- HTTP 451 / VPN routing incident class.
- Memory pressure / n_envs compatibility incident class.
- Stale symbol/universe validation drift.
- Missing signal attribution lineage.
- Duplicate execution risk.
- CROSS margin risk.
- High leverage risk.
- Stale execution risk.
- Redis write collision risk.
- Docs/runtime mismatch risk.

## Evidence anchors
- Codex review + checker pass artifacts.
- Tier A unresolved exchange review entries: 1361.
- Runtime/startup map artifacts for docs-vs-runtime mismatch analysis.

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
