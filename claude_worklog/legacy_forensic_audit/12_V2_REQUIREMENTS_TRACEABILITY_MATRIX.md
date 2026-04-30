# 12 V2 Requirements Traceability Matrix

## Summary
Legacy forensic findings mapped to V2 requirements (traceability only; V2 build still blocked).

| Legacy issue/theme | V2 requirement |
|---|---|
| Exchange mutation risk surfaces | Risk gateway ownership + audited execution contract |
| Signal lineage gaps | Audit ledger + signal explainability |
| Config drift/docs mismatch | Config admin + policy-controlled runtime config |
| Multi-script operational sprawl | Script registry + monitor center |
| Trainer confidence/reward opacity | Trainer prediction monitor + explainability |
| Replayability gaps | Paper/replay framework |
| Operator control-plane gaps | Admin AI + hosting/mobile readiness controls |
| Premature live activation risk | Explicit live-trading blocked gates |

## Ollama optional support note
- Ollama may assist with local summarization/evidence packet drafting only.
- Ollama cannot authorize V2 build, risk acceptance, or live trading transitions.
- All safety-critical claims in traceability must be verified via deterministic artifacts and raw evidence.


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
