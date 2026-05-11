# Handoff Artifact Path Mapping

Generated: 2026-05-11T07:45:58.228145+00:00

Canonical path: `claude_worklog/final_readiness/claude_primary_handoff/latest/`

Source paths normalized into this canonical path:

- `claude_worklog/final_readiness/claude_primary_handoff_state_refresh/latest/`
- `claude_worklog/final_readiness/claude_codex_rate_limit_handoff/latest/`
- `claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.*`

The canonical path is now the operator-facing source for Claude-primary routing. Claude is primary planner/builder, Codex is parallel reviewer/auditor, Codex acting-governor is standby-only, and Ollama remains draft-only. Human input is not required unless the final live/capital gate is explicitly selected.
