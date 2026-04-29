#!/usr/bin/env bash
set -euo pipefail

WORK_MINUTES="${WORK_MINUTES:-240}"
WARN_MINUTES="${WARN_MINUTES:-210}"
STATE_DIR="${STATE_DIR:-$HOME/Desktop/AI BOT REBUILD/claude_worklog/session_guard}"
mkdir -p "$STATE_DIR"

START_FILE="$STATE_DIR/session_start_epoch.txt"

if [ ! -f "$START_FILE" ]; then
  date +%s > "$START_FILE"
  echo "Session guard started at $(date). Work budget: ${WORK_MINUTES} minutes."
  exit 0
fi

START="$(cat "$START_FILE")"
NOW="$(date +%s)"
ELAPSED_MIN=$(( (NOW - START) / 60 ))

echo "Claude session elapsed: ${ELAPSED_MIN} minutes."

if [ "$ELAPSED_MIN" -ge "$WORK_MINUTES" ]; then
  echo "PAUSE_REQUIRED: Work block reached ${WORK_MINUTES} minutes. Run /compact, save worklog, then pause until reset window."
  exit 2
fi

if [ "$ELAPSED_MIN" -ge "$WARN_MINUTES" ]; then
  echo "WARNING: Approaching Claude 5-hour window. Finish current task, run /compact, then pause soon."
  exit 1
fi

echo "OK: within work budget."
