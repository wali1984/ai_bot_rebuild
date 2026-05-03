#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

BRIEF="claude_worklog/phase2_core_rebuild/frontend_design/05_CLAUDE_DESIGN_SESSION_BRIEF.md"
OUT="claude_worklog/phase2_core_rebuild/frontend_design/06_CLAUDE_DESIGN_OUTPUT.md"
STATUS="claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_HANDOFF_STATUS.md"

mkdir -p "claude_worklog/phase2_core_rebuild/frontend_design"

if [ ! -f "$BRIEF" ]; then
  echo "Missing design brief: $BRIEF"
  exit 2
fi

cat > "$STATUS" <<EOF
# Claude Design Handoff Status

Generated: $(date -Is)

Input brief:
$BRIEF

Expected output:
$OUT

Status:
CLAUDE_DESIGN_HANDOFF_PREPARED

Instructions:
1. Claude Code must remain paused.
2. Open Claude Design.
3. Paste the copied prompt.
4. Generate the design system output.
5. Save the result into:
   $OUT
6. Run:
   ./claude_worklog/tools/finalize_claude_design_output.sh

CLAUDE_DESIGN_HANDOFF_READY
EOF

echo "=== Claude Design brief ==="
sed -n '1,260p' "$BRIEF"

echo
echo "=== Copying brief to clipboard if clipboard tool exists ==="
if command -v xclip >/dev/null 2>&1; then
  xclip -selection clipboard < "$BRIEF"
  echo "Copied brief to clipboard with xclip."
elif command -v xsel >/dev/null 2>&1; then
  xsel --clipboard --input < "$BRIEF"
  echo "Copied brief to clipboard with xsel."
elif command -v wl-copy >/dev/null 2>&1; then
  wl-copy < "$BRIEF"
  echo "Copied brief to clipboard with wl-copy."
else
  echo "No clipboard tool found. Manually copy the brief above."
fi

echo
echo "=== Opening Claude Design in browser if possible ==="
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "https://claude.ai" >/dev/null 2>&1 || true
fi

echo
echo "Prepared Claude Design handoff."
echo "Paste the brief into Claude Design."
echo "Save output to:"
echo "$OUT"
echo
echo "Then run:"
echo "./claude_worklog/tools/finalize_claude_design_output.sh"
