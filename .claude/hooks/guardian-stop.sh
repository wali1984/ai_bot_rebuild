#!/usr/bin/env bash
set -u

INPUT="$(cat)"

# Prevent recursive Stop-hook loops. /goal and the external watchdog will
# start subsequent turns when completion remains false.
if [ "$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false')" = "true" ]; then
    exit 0
fi

ROOT="/home/wali/Desktop/AI BOT REBUILD"
# Use repo copy so updates take effect without sudo reinstall.
# Fall back to installed system copy if repo copy is missing.
if [ -f "$ROOT/scripts/verify_claude_guardian_completion.py" ]; then
    VERIFY="$ROOT/scripts/verify_claude_guardian_completion.py"
else
    VERIFY="/usr/local/lib/ai-bot-guardian/verify_claude_guardian_completion.py"
fi
RESULT="/tmp/v2_claude_guardian_verify.json"

if "$VERIFY" >"$RESULT" 2>&1; then
    echo "Guardian completion verifier passed." >&2
    cat "$RESULT" >&2
    exit 0
fi

echo "Guardian goal is incomplete. Continue working immediately." >&2
cat "$RESULT" >&2
echo "Read WORK_QUEUE.json and FINDINGS.jsonl; execute the next incomplete task. A cycle summary, WAITING state, or report is not completion." >&2
exit 2
