#!/usr/bin/env bash
set -uo pipefail
AGENT_CMD="your-agent-cli"   # e.g. codex exec / claude -p, reading PROMPT.md

for P in 1 2 3 4 5 6 7 8 9 10; do
  echo "=== PHASE $P ==="
  $AGENT_CMD --phase "$P" --spec PROMPT.md
  if ! ./validate_phase.sh "$P"; then
    echo "Phase $P failed validation — re-prompting once with failure output"
    ./validate_phase.sh "$P" > /tmp/phase_${P}_fail.txt 2>&1
    $AGENT_CMD --phase "$P" --spec PROMPT.md --fix /tmp/phase_${P}_fail.txt
    ./validate_phase.sh "$P" || { echo "Phase $P still failing. HALT."; exit 1; }
  fi
  git add -A && git commit -m "phase $P verified" >/dev/null
done
echo "All 10 phases verified."