#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

OUT="claude_worklog/phase2_core_rebuild/frontend_design/06_CLAUDE_DESIGN_OUTPUT.md"
STATUS="claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_HANDOFF_STATUS.md"

if [ ! -f "$OUT" ]; then
  echo "Missing Claude Design output:"
  echo "$OUT"
  exit 2
fi

if [ ! -s "$OUT" ]; then
  echo "Claude Design output exists but is empty:"
  echo "$OUT"
  exit 2
fi

echo "=== Validate no live/secret material in design output ==="

grep -RIE \
"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----|xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}" \
  "$OUT" \
  --exclude="*.pyc" \
  > claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_SECRET_SCAN.txt || true

if [ -s claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_SECRET_SCAN.txt ]; then
  echo "CLAUDE_DESIGN_SECRET_SCAN_FAILED"
  sed -n '1,160p' claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_SECRET_SCAN.txt
  exit 2
else
  echo "CLAUDE_DESIGN_SECRET_SCAN_CLEAN"
fi

cat > "$STATUS" <<EOF
# Claude Design Handoff Status

Generated: $(date -Is)

Output:
$OUT

Validation:
- output file exists
- output file non-empty
- high-confidence secret scan clean

Status:
CLAUDE_DESIGN_OUTPUT_READY_FOR_COMMIT

CLAUDE_DESIGN_HANDOFF_COMPLETE
EOF

git add \
  "$OUT" \
  "$STATUS" \
  claude_worklog/phase2_core_rebuild/frontend_design/CLAUDE_DESIGN_SECRET_SCAN.txt \
  claude_worklog/tools/start_claude_design_handoff.sh \
  claude_worklog/tools/finalize_claude_design_output.sh

git commit -m "Add Claude Design enterprise website output" || echo "Nothing to commit"
git push

echo "=== git status ==="
git status --short

echo "Claude Design output finalized and pushed."
