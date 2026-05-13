
# Git Dirty Final Gate Classification

Generated: 2026-05-13T04:00:24.605211+00:00

## Counts
```json
{
  "active_daemon_owned": 13,
  "durable_artifact_to_commit": 15,
  "runtime_status_churn_to_restore": 149
}
```

## Policy
No active Claude/Codex child was visible. Durable final-gate and completed primary-chain artifacts may be validated, committed, and pushed. Active daemon-owned status files and runtime churn are left in place and not erased. Unknown files block cleanup; current unknown count is `0`.

Full classification is in `git_dirty_final_gate_classification.json`.
