# Operator Truth Generator Repair Report

Generated at: 2026-05-12T19:58:03.594Z

Command:

```bash
cd v2/frontend && npm run build:operator-truth
```

The payload includes generated_at, process snapshot, supervisor status, queue status, latest event, active workers/processes, current task, next task, git status, latest commit, trainer state, monitor_trainer_predictions state, orchestrator state, trader state, market ingestors, feature pipeline, Redis memory payload state, read-only market feed payload state, paper/shadow runtime payload state, signal lineage classification, payload freshness, missing evidence, and blockers.

Freshness model:

- CURRENT <= 120 seconds
- WARN 121-300 seconds
- STALE > 300 seconds
- STATIC_PROOF_FIXTURE never counts as current runtime truth
- MISSING_EVIDENCE never counts as current runtime truth
