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

## Guard Command

Use the quota guard during autonomous rebuild sessions:

`./claude_worklog/tools/start_claude_code_quota_guard.sh`

The guard:
- records the 5-hour ready-probe cadence
- stops the Claude Master Rebuild Planner if Claude Code is blocked or limited
- probes more frequently while blocked
- restarts the planner only after the probe reports ready and git is clean except runtime prompt/quota files

## Suggested Cadence

Every 5 hours during active rebuild days.

CLAUDE_CODE_QUOTA_MONITORING_POLICY_READY
