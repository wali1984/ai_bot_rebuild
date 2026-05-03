#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

mkdir -p claude_worklog/quota

OUT="claude_worklog/quota/CLAUDE_CODE_QUOTA_CHECK_OUTPUT.txt"
ERR="claude_worklog/quota/CLAUDE_CODE_QUOTA_CHECK_ERROR.txt"
STATUS="claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md"

echo "=== Claude Code quota probe at $(date -Is) ==="

claude --print "Print CLAUDE_CODE_QUOTA_PROBE_OK" --output-format text > "$OUT" 2> "$ERR" || true

if grep -q "CLAUDE_CODE_QUOTA_PROBE_OK" "$OUT"; then
  STATE="ready"
else
  STATE="blocked_or_limited"
fi

cat > "$STATUS" <<STATUS_EOF
# Claude Code Quota Status

Generated: $(date -Is)

State:
$STATE

Output:
\`\`\`
$(cat "$OUT" 2>/dev/null)
\`\`\`

Error:
\`\`\`
$(cat "$ERR" 2>/dev/null)
\`\`\`

Notes:
- This is a lightweight readiness probe.
- If blocked_or_limited, pause master planner and avoid new Claude Code tasks.
- Check full UI usage panel manually for exact reset time.

CLAUDE_CODE_QUOTA_STATUS_RECORDED
STATUS_EOF

cat "$STATUS"
