#!/usr/bin/env bash
set -uo pipefail

ROOT="/home/wali/Desktop/AI BOT REBUILD"
SESSION_NAME="v2-capital-guardian"
GOAL_FILE="$ROOT/.claude/guardian-goal.txt"
VERIFY="/usr/local/lib/ai-bot-guardian/verify_claude_guardian_completion.py"
STARTED_MARKER="$ROOT/.claude/guardian-session-started"
LOG="$ROOT/logs/claude-capital-guardian-runner.log"

cd "$ROOT" || exit 1
mkdir -p "$(dirname "$LOG")"

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
if [ -z "$CLAUDE_BIN" ]; then
    echo "claude binary not found" | tee -a "$LOG"
    exit 1
fi

if [ ! -s "$GOAL_FILE" ]; then
    echo "goal file missing or empty: $GOAL_FILE" | tee -a "$LOG"
    exit 1
fi

while true; do
    if "$VERIFY" >>"$LOG" 2>&1; then
        echo "$(date -u +%FT%TZ) guardian COMPLETE" | tee -a "$LOG"
        exit 0
    fi

    echo "$(date -u +%FT%TZ) guardian incomplete; launching/resuming" \
        | tee -a "$LOG"

    if [ ! -f "$STARTED_MARKER" ]; then
        GOAL_TEXT="$(tr '\n' ' ' < "$GOAL_FILE")"

        "$CLAUDE_BIN" -p \
          --name "$SESSION_NAME" \
          --permission-mode auto \
          --effort high \
          "/goal $GOAL_TEXT" \
          >>"$LOG" 2>&1

        RC=$?
        touch "$STARTED_MARKER"
    else
        "$CLAUDE_BIN" -p \
          --resume "$SESSION_NAME" \
          --permission-mode auto \
          --effort high \
          "Resume the still-active /goal. Read the guardian state files. Run scripts/verify_claude_guardian_completion.py, surface its output, then immediately execute the next incomplete WORK_QUEUE or FINDINGS item. Do not summarize and stop." \
          >>"$LOG" 2>&1

        RC=$?
    fi

    if "$VERIFY" >>"$LOG" 2>&1; then
        echo "$(date -u +%FT%TZ) guardian COMPLETE after Claude exit" \
            | tee -a "$LOG"
        exit 0
    fi

    if [ "$RC" -ne 0 ]; then
        echo "$(date -u +%FT%TZ) Claude exited rc=$RC; retry in 15m" \
            | tee -a "$LOG"
        sleep 900
    else
        echo "$(date -u +%FT%TZ) Claude returned prematurely; retry in 60s" \
            | tee -a "$LOG"
        sleep 60
    fi
done
