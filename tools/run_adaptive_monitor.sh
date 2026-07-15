#!/bin/bash
# Continuous adaptive monitoring loop: runs adaptive gate tuner every 60s
# Logs to claude_worklog/12_hour_continuous_monitor.md
# Exits when A-grades ready or 12 hours elapsed

set -e

REPO_ROOT="/home/wali/Desktop/AI BOT REBUILD"
cd "$REPO_ROOT"

VENV="./.venv/bin/python3"
TUNER="v2.backend.app.cli.v2_adaptive_gate_tuner"
LOG_FILE="claude_worklog/12_hour_continuous_monitor.md"

ITERATION=0
START_TIME=$(date +%s)
MAX_DURATION=$((12 * 3600))  # 12 hours in seconds

echo "🚀 Starting adaptive monitoring loop at $(date)"
echo "📊 Logging to: $LOG_FILE"
echo ""

while true; do
  ITERATION=$((ITERATION + 1))
  ELAPSED=$(($(date +%s) - START_TIME))
  ELAPSED_MIN=$((ELAPSED / 60))
  HOURS=$((ELAPSED / 3600))

  echo ">>> ITERATION $ITERATION | Elapsed: ${HOURS}h ${ELAPSED_MIN}m | $(date '+%Y-%m-%d %H:%M:%S Z')"

  # Run adaptive tuner (always exits 0; JSON output is source of truth)
  TUNING_STATE=$(timeout 30 $VENV -m $TUNER 2>&1)
  TUNER_EXIT=$?
  if [[ $TUNER_EXIT -ne 0 ]]; then
    echo "⚠️  Tuner exited with code $TUNER_EXIT (timeout or error)"
    TUNING_STATE="{\"error\": \"tuner timeout or error\", \"exit_code\": $TUNER_EXIT}"
  fi

  A_GRADE_READY=$(echo "$TUNING_STATE" | grep -o '"a_grade_ready":\s*true' || echo "false")
  CONFIDENCE_THRESHOLD=$(echo "$TUNING_STATE" | grep -o '"adaptive_confidence_threshold":\s*[0-9.]*' | cut -d: -f2 | tr -d ' ')
  B_GRADE_ENABLED=$(echo "$TUNING_STATE" | grep -o '"enable_b_grade":\s*true' || echo "false")

  # Append to log
  cat >> "$LOG_FILE" << EOF

### Iteration $ITERATION — T+${ELAPSED_MIN}:00 ($(date -u +'%Y-%m-%dT%H:%M:%SZ'))
\`\`\`
Timestamp: $(date)
Elapsed: ${HOURS}h${ELAPSED_MIN}m
A-Grade Ready: $(if [[ "$A_GRADE_READY" == "false" ]]; then echo "FALSE"; else echo "TRUE ✅"; fi)
Confidence Threshold: ${CONFIDENCE_THRESHOLD:-computing}
B-Grade Enabled: $(if [[ "$B_GRADE_ENABLED" == "false" ]]; then echo "FALSE"; else echo "TRUE ✅"; fi)

Full Tuning State:
$TUNING_STATE
\`\`\`
EOF

  # Print to console
  echo "  A-Grade Ready: $(if [[ "$A_GRADE_READY" == "false" ]]; then echo "❌"; else echo "✅"; fi)"
  echo "  B-Grade Enabled: $(if [[ "$B_GRADE_ENABLED" == "false" ]]; then echo "❌"; else echo "✅"; fi)"
  echo "  Confidence Threshold: ${CONFIDENCE_THRESHOLD:-computing}"
  echo ""

  # Check success condition
  if [[ "$A_GRADE_READY" == "true" ]]; then
    echo "🎉 SUCCESS! A-GRADES READY AT ITERATION $ITERATION"
    echo "Final timestamp: $(date)"
    break
  fi

  # Check timeout
  if [[ $ELAPSED -gt $MAX_DURATION ]]; then
    echo "⏱️  12-HOUR LIMIT REACHED"
    break
  fi

  # Wait 60 seconds before next iteration
  echo "⏳ Waiting 60s for next iteration..."
  sleep 60
done

echo "📋 Final log: $LOG_FILE"
