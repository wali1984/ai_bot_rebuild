# 13 PPO/MASS Trainer Audit

## Summary
Trainer forensic summary from atlas + Tier A:
- PPO worker/env structure observed in trainer code paths.
- MASS/state-space and feature-state mass paths extracted.
- obs_dim/action_dim compatibility concerns tracked through checkpoint and env setup paths.
- Reward and confidence path extraction complete.
- Checkpoint compatibility and n_envs compatibility remain known risk classes.

## Evidence counts
- trainer_reward matches: 4909
- trainer_confidence matches: 2735
- trainer_signal matches: 9620
- trainer_checkpoint matches: 2535

## Risk statements
- memory/resource pressure risk: present historically and must remain monitored.
- calibration risk: confidence/reward tuning remains a live-risk domain.
- dry-run requirement: required before any parameterization changes that alter runtime behavior.

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
- High
