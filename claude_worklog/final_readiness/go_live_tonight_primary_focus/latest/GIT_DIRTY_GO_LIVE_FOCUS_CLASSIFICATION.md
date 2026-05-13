# Git Dirty Go-Live Focus Classification

Generated at: 2026-05-13T06:35:06.322Z

Dirty state is not allowed to stall primary go-live work indefinitely. This packet classifies every path from `git status --short -uall`.

| classification | count |
| --- | --- |
| active_daemon_owned | 76 |
| durable_artifact_to_commit | 69 |
| runtime_churn_to_restore | 113 |

Policy:

- Leave active daemon/task-owned files alone.
- Validate and commit durable go-live focus artifacts.
- Restore runtime churn only when no worker owns it and no evidence would be erased.
- Unknown dirty ownership is a blocker; this run has no unknown classification.

Detailed matrix: `git_dirty_go_live_focus_classification.json`.
