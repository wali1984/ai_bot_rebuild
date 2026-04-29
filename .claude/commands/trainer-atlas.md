---
description: Build and verify atlas for the 250k-line hybrid trainer.
---

The legacy trainer is over 250k lines.

Do not read it end-to-end.

First create deterministic trainer atlas tools if missing.

Required outputs:
- claude_worklog/trainer_atlas/HYBRID_TRAINER_ATLAS.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_FUNCTION_INDEX.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_CLASS_INDEX.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_IMPORT_GRAPH.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIG_USAGE.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_USAGE.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_REWARD_PATHS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_FEATURE_PATHS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_SIGNAL_PATHS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_RUNTIME_ENTRYPOINTS.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_TIER_A_REVIEW_PLAN.md

Then raw-review all Tier A line ranges.
No unknown chunks allowed.
