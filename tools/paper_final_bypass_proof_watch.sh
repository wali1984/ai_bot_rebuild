#!/usr/bin/env bash
# Session-independent proof watch for the FINAL PAPER POLICY-GATE BYPASS
# acceptance (item 10).  Runs the READ-ONLY collector once a minute and logs
# criterion transitions; exits 0 when ACCEPTANCE_PASS is reached.
set -u
REPO="/home/wali/Desktop/AI BOT REBUILD"
PY="$REPO/.venv/bin/python3"
LOG="$REPO/claude_worklog/paper_final_bypass_proof_watch.log"
PREV=""
while true; do
  OUT="$($PY "$REPO/tools/paper_final_bypass_acceptance_proof.py" check 2>/dev/null | tail -1)"
  if [ "$OUT" != "$PREV" ]; then
    echo "$(date -u +%FT%TZ) $OUT" >> "$LOG"
    PREV="$OUT"
  fi
  case "$OUT" in
    *ACCEPTANCE_PASS*) echo "$(date -u +%FT%TZ) ACCEPTANCE_PASS reached" >> "$LOG"; exit 0 ;;
    *DEFECT*) echo "$(date -u +%FT%TZ) DEFECT observed — investigate immediately" >> "$LOG" ;;
  esac
  sleep 60
done
