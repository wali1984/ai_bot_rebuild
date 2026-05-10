# Handoff Back To Claude Policy

The scheduler should hand work back to Claude when:

1. `claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md` reports `ready`.
2. Git is clean.
3. No active Codex child task is running.
4. No final live/capital gate is pending.

Until then, the Claude planner lane remains paused and Codex/Ollama continue
safe non-live progress.
