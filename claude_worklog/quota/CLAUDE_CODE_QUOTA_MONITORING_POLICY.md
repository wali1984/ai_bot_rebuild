# Claude Code Quota Monitoring Policy

## Objective

Check Claude Code readiness every 5 hours during long autonomous rebuild work.

## Policy

- Do not keep the planner running through hard quota exhaustion loops.
- If Claude Code is blocked or limited, pause planner.
- Use Claude Design, Codex review, Ollama summarization, or deterministic local validation during cooldown.
- Resume planner only after readiness probe passes and git state is clean.

## Check Command

`./claude_worklog/tools/check_claude_code_quota_status.sh`

## Suggested Cadence

Every 5 hours during active rebuild days.

CLAUDE_CODE_QUOTA_MONITORING_POLICY_READY
